import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    OutboxJob,
    Payment,
    PaymentIntentRequest,
    PaymentRefundAttempt,
    Resource,
    StripeConnection,
    StripeWebhookEvent,
)
from app.services.availability_service import AvailabilityService
from app.services.capacity import CapacityInterval, batch_fits


class StripeWebhookService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def process(self, event: dict[str, Any]) -> bool:
        event_id, event_type = str(event["id"]), str(event["type"])
        inserted = self.db.scalar(
            insert(StripeWebhookEvent)
            .values(stripe_event_id=event_id, event_type=event_type, status="processing")
            .on_conflict_do_nothing(index_elements=[StripeWebhookEvent.stripe_event_id])
            .returning(StripeWebhookEvent.id)
        )
        if inserted is None:
            existing = self.db.scalar(
                select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
            )
            if existing and existing.status == "processed":
                self.db.rollback()
                return False
            # A failed delivery is deliberately retried using the same durable row.
            event_row = existing
            if event_row is None:
                raise RuntimeError("Unable to claim Stripe event")
            event_row.status = "processing"
            event_row.error_message = None
        else:
            event_row = self.db.get(StripeWebhookEvent, inserted)

        data = event.get("data", {}).get("object", {})
        try:
            if event_type == "payment_intent.succeeded":
                self._payment_succeeded(data, event)
            elif event_type == "payment_intent.payment_failed":
                self._payment_failed(data)
            elif event_type == "account.updated":
                self._account_updated(data)
            elif event_type == "charge.refunded":
                self._charge_refunded(data)
            elif event_type == "charge.dispute.created":
                self._charge_disputed(data)
            event_row.status = "processed"
            event_row.processed_at = datetime.now(UTC)
            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            failed = self.db.scalar(
                select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
            )
            if failed is None:
                failed = StripeWebhookEvent(
                    stripe_event_id=event_id, event_type=event_type, status="failed"
                )
                self.db.add(failed)
            failed.status = "failed"
            failed.error_message = str(exc)[:2000]
            self.db.commit()
            raise

    def _payment_succeeded(self, intent: dict[str, Any], event: dict[str, Any]) -> None:
        intent_id = str(intent["id"])
        payment = self.db.scalar(
            select(Payment)
            .where(Payment.stripe_payment_intent_id == intent_id)
            .with_for_update()
        )
        if payment is None:
            raise RuntimeError("PaymentIntent does not map to a local payment")
        order = self.db.scalar(
            select(BookingOrder)
            .where(BookingOrder.id == payment.booking_order_id)
            .with_for_update()
        )
        if order is None:
            raise RuntimeError("Payment order not found")
        if payment.status == "succeeded" and order.status == "confirmed":
            return

        mismatches = self._payment_mismatches(payment, order, intent, event)
        if mismatches:
            payment.reconciliation_status = "quarantined"
            payment.observed_amount_minor = self._int_or_none(intent.get("amount"))
            payment.observed_amount_received_minor = self._int_or_none(
                intent.get("amount_received")
            )
            payment.observed_currency = str(intent.get("currency") or "").lower() or None
            payment.stripe_livemode = bool(intent.get("livemode"))
            payment.stripe_account_id = str(event.get("account")) if event.get("account") else None
            order.status = "exception"
            payment.provider_unknown_at = datetime.now(UTC)
            return

        latest_charge = intent.get("latest_charge")
        if isinstance(latest_charge, dict):
            charge_id = latest_charge.get("id")
        else:
            charge_id = latest_charge
        if not isinstance(charge_id, str) or not charge_id.startswith("ch_"):
            raise RuntimeError("Successful PaymentIntent is missing a Charge ID")

        bookings = list(
            self.db.scalars(
                select(Booking)
                .where(Booking.booking_order_id == order.id)
                .order_by(Booking.id)
                .with_for_update()
            )
        )
        if not bookings:
            raise RuntimeError("Paid order has no bookings")
        unexpected = [b for b in bookings if b.status not in {"pending_payment", "confirmed"}]
        if unexpected:
            order.status = "exception"
            payment.status = "succeeded"
            payment.stripe_charge_id = charge_id
            payment.paid_at = datetime.now(UTC)
            self._enqueue_refund(payment, order, scope_key="late-invalid-booking")
            return

        now = datetime.now(UTC)
        expired = any(
            booking.status == "pending_payment"
            and (booking.hold_expires_at is None or booking.hold_expires_at <= now)
            for booking in bookings
        )
        resource_rows = self.db.execute(
            select(BookingResource.booking_id, BookingResource.resource_id, BookingResource.quantity)
            .where(BookingResource.booking_id.in_([booking.id for booking in bookings]))
        ).all()
        resource_ids = sorted({row.resource_id for row in resource_rows})
        resources = {
            resource.id: resource
            for resource in self.db.scalars(
                select(Resource)
                .where(Resource.id.in_(resource_ids))
                .order_by(Resource.id)
                .with_for_update()
            )
        }
        if expired and not self._expired_order_still_fits(bookings, resource_rows, resources):
            for booking in bookings:
                if booking.status == "pending_payment":
                    booking.status = "failed"
                    booking.hold_expires_at = None
            order.status = "exception"
            payment.status = "succeeded"
            payment.stripe_charge_id = charge_id
            payment.paid_at = now
            self._enqueue_refund(payment, order, scope_key="late-unavailable")
            return

        for booking in bookings:
            booking.status = "confirmed"
            booking.hold_expires_at = None
        payment.status = "succeeded"
        payment.stripe_charge_id = charge_id
        payment.paid_at = now
        request_row = self.db.scalar(
            select(PaymentIntentRequest).where(PaymentIntentRequest.payment_id == payment.id)
        )
        if request_row:
            request_row.status = "succeeded"
            request_row.stripe_payment_intent_id = intent_id
        order.status = "confirmed"
        self._enqueue(order, payment)

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _payment_mismatches(
        payment: Payment,
        order: BookingOrder,
        intent: dict[str, Any],
        event: dict[str, Any],
    ) -> list[str]:
        mismatches: list[str] = []
        if str(intent.get("status")) != "succeeded":
            mismatches.append("status")
        if StripeWebhookService._int_or_none(intent.get("amount")) != payment.customer_total_minor:
            mismatches.append("amount")
        amount_received = StripeWebhookService._int_or_none(intent.get("amount_received"))
        if amount_received is not None and amount_received != payment.customer_total_minor:
            mismatches.append("amount_received")
        if str(intent.get("currency") or "").lower() != payment.currency.lower():
            mismatches.append("currency")
        metadata = intent.get("metadata") or {}
        if metadata.get("booking_order_id") and str(metadata["booking_order_id"]) != str(order.id):
            mismatches.append("booking_order_id")
        if metadata.get("operator_id") and str(metadata["operator_id"]) != str(order.operator_id):
            mismatches.append("operator_id")
        if metadata.get("public_reference") and metadata["public_reference"] != order.public_reference:
            mismatches.append("public_reference")
        settings = get_settings()
        if settings.stripe_platform_account_id and event.get("account"):
            if event.get("account") != settings.stripe_platform_account_id:
                mismatches.append("account")
        if intent.get("livemode") is not None:
            expected_live = settings.stripe_secret_key.startswith("sk_live_")
            if bool(intent.get("livemode")) != expected_live:
                mismatches.append("livemode")
        return mismatches

    def _expired_order_still_fits(self, bookings, resource_rows, resources) -> bool:
        booking_lookup = {booking.id: booking for booking in bookings}
        requested: dict[uuid.UUID, list[CapacityInterval]] = defaultdict(list)
        for booking_id, resource_id, quantity in resource_rows:
            booking = booking_lookup[booking_id]
            requested[resource_id].append(
                CapacityInterval(booking.start_at, booking.end_at, quantity)
            )
        if not requested:
            return True
        existing = AvailabilityService(self.db)._reservations(
            list(requested),
            min(booking.start_at for booking in bookings),
            max(booking.end_at for booking in bookings),
        )
        return all(
            resource_id in resources
            and resources[resource_id].is_active
            and resources[resource_id].deleted_at is None
            and batch_fits(
                resources[resource_id].quantity,
                existing.get(resource_id, []),
                intervals,
            )
            for resource_id, intervals in requested.items()
        )

    def _enqueue(self, order: BookingOrder, payment: Payment) -> None:
        jobs = [
            ("stripe_create_transfer", f"order:{order.id}:stripe_transfer"),
            ("ghl_upsert_contact", f"order:{order.id}:ghl_contact"),
            ("ghl_send_confirmation_email", f"order:{order.id}:ghl_email"),
        ]
        for job_type, key in jobs:
            if job_type == "stripe_create_transfer" and payment.operator_transfer_minor == 0:
                continue
            self.db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=order.operator_id,
                    booking_order_id=order.id,
                    job_type=job_type,
                    idempotency_key=key,
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )
        for booking in self.db.scalars(
            select(Booking).where(Booking.booking_order_id == order.id)
        ):
            self.db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=order.operator_id,
                    booking_order_id=order.id,
                    job_type="ghl_sync_appointment",
                    idempotency_key=f"booking:{booking.id}:ghl_appointment:confirmed",
                    payload={"booking_id": str(booking.id)},
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )

    def _enqueue_refund(self, payment: Payment, order: BookingOrder, *, scope_key: str) -> None:
        attempt_id = self.db.scalar(
            insert(PaymentRefundAttempt)
            .values(
                operator_id=payment.operator_id,
                payment_id=payment.id,
                scope_key=scope_key,
                amount_minor=payment.customer_total_minor,
                currency=payment.currency,
                idempotency_key=f"payment:{payment.id}:refund:{scope_key}",
                status="requested",
            )
            .on_conflict_do_nothing(
                index_elements=[PaymentRefundAttempt.payment_id, PaymentRefundAttempt.scope_key]
            )
            .returning(PaymentRefundAttempt.id)
        )
        payment.reconciliation_status = "refund_pending"
        if attempt_id is not None:
            self.db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=order.operator_id,
                    booking_order_id=order.id,
                    job_type="stripe_create_refund",
                    idempotency_key=f"payment:{payment.id}:refund-job:{scope_key}",
                    payload={"refund_attempt_id": str(attempt_id)},
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )

    def _payment_failed(self, intent: dict[str, Any]) -> None:
        payment = self.db.scalar(
            select(Payment)
            .where(Payment.stripe_payment_intent_id == str(intent["id"]))
            .with_for_update()
        )
        if payment is None or payment.status == "succeeded":
            return
        if str(intent.get("status")) == "requires_payment_method":
            payment.status = "requires_payment"
            order = self.db.get(BookingOrder, payment.booking_order_id)
            if order and order.status == "pending_payment":
                order.status = "pending_payment"
            return
        # A canceled PaymentIntent is terminal and must release the booking hold.
        payment.status = "failed"
        request_row = self.db.scalar(
            select(PaymentIntentRequest).where(PaymentIntentRequest.payment_id == payment.id)
        )
        if request_row:
            request_row.status = "failed"
        order = self.db.get(BookingOrder, payment.booking_order_id)
        if order:
            order.status = "expired"
        for booking in self.db.scalars(
            select(Booking).where(Booking.booking_order_id == payment.booking_order_id)
        ):
            if booking.status == "pending_payment":
                booking.status = "failed"
                booking.hold_expires_at = None

    def _account_updated(self, account: dict[str, Any]) -> None:
        connection = self.db.scalar(
            select(StripeConnection).where(
                StripeConnection.stripe_account_id == str(account["id"])
            )
        )
        if connection is None:
            return
        capabilities = account.get("capabilities") or {}
        transfers = capabilities.get("transfers")
        connection.details_submitted = bool(account.get("details_submitted"))
        connection.payouts_enabled = bool(account.get("payouts_enabled"))
        connection.charges_enabled = bool(account.get("charges_enabled"))
        connection.transfers_capability_status = transfers
        connection.onboarding_complete = (
            connection.details_submitted and connection.payouts_enabled and transfers == "active"
        )

    def _charge_refunded(self, charge: dict[str, Any]) -> None:
        payment = self.db.scalar(
            select(Payment).where(Payment.stripe_charge_id == str(charge["id"])).with_for_update()
        )
        if payment is None:
            return
        refunded = int(charge.get("amount_refunded") or 0)
        payment.refunded_minor = max(payment.refunded_minor, refunded)
        full = bool(charge.get("refunded")) or refunded >= payment.customer_total_minor
        payment.status = "refunded" if full else "partially_refunded"
        order = self.db.get(BookingOrder, payment.booking_order_id)
        if order:
            order.status = "refunded" if full else "partially_refunded"

    def _charge_disputed(self, dispute: dict[str, Any]) -> None:
        charge = dispute.get("charge")
        charge_id = charge.get("id") if isinstance(charge, dict) else charge
        payment = self.db.scalar(select(Payment).where(Payment.stripe_charge_id == charge_id))
        if payment:
            order = self.db.get(BookingOrder, payment.booking_order_id)
            if order:
                order.status = "exception"
