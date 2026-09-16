import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    OutboxJob,
    Payment,
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
                self._payment_succeeded(data)
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

    def _payment_succeeded(self, intent: dict[str, Any]) -> None:
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
            return

        for booking in bookings:
            booking.status = "confirmed"
            booking.hold_expires_at = None
        payment.status = "succeeded"
        payment.stripe_charge_id = charge_id
        payment.paid_at = now
        order.status = "confirmed"
        self._enqueue(order, payment)

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

    def _payment_failed(self, intent: dict[str, Any]) -> None:
        payment = self.db.scalar(
            select(Payment)
            .where(Payment.stripe_payment_intent_id == str(intent["id"]))
            .with_for_update()
        )
        if payment is None or payment.status == "succeeded":
            return
        payment.status = "failed"
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

