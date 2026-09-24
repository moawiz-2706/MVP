import hashlib
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingOrder,
    BookingResource,
    Calendar,
    CalendarResource,
    DepartureLocation,
    Operator,
    OutboxJob,
    Payment,
    PaymentIntentRequest,
    Resource,
    StripeConnection,
)
from app.schemas.order import (
    OrderCreateRequest,
    OrderCreateResponse,
    OrderQuoteRequest,
    OrderQuoteResponse,
    QuotedItem,
)
from app.services.availability_service import AvailabilityService
from app.services.capacity import CapacityInterval, batch_fits
from app.services.public_access_service import PublicAccessService
from app.services.outbox_service import OutboxService
from app.services.staffing_service import lock_calendars
from app.services.stripe_payment_service import StripePaymentService
from app.utils.identifiers import public_reference
from app.utils.money import PaymentBreakdown, calculate_payment


logger = logging.getLogger("passport.order")


@dataclass(slots=True)
class PreparedItem:
    request_calendar_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    units: int
    calendar: Calendar
    location: DepartureLocation | None
    resources: list[tuple[Resource, int]]

    def quote(self) -> QuotedItem:
        return QuotedItem(
            calendar_id=self.calendar.id,
            calendar_name=self.calendar.name,
            start_at=self.start_at,
            end_at=self.end_at,
            units=self.units,
            base_price_minor=self.calendar.base_price_minor,
            line_subtotal_minor=self.calendar.base_price_minor * self.units,
            departure_location_name=self.location.name if self.location else None,
            departure_location_address=self.location.address if self.location else None,
        )


class OrderService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _operator(self, slug: str) -> Operator:
        operator = self.db.scalar(
            select(Operator).where(
                Operator.slug == slug,
                Operator.is_active.is_(True),
                Operator.public_booking_enabled.is_(True),
            )
        )
        if operator is None:
            raise NotFoundError("Booking page not found")
        return operator

    def _prepare(self, operator: Operator, items: Iterable) -> list[PreparedItem]:
        prepared: list[PreparedItem] = []
        availability = AvailabilityService(self.db)
        for item in items:
            row = self.db.execute(
                select(Calendar, DepartureLocation)
                .outerjoin(DepartureLocation, DepartureLocation.id == Calendar.departure_location_id)
                .where(
                    Calendar.id == item.calendar_id,
                    Calendar.operator_id == operator.id,
                    Calendar.is_active.is_(True),
                    Calendar.public_booking_enabled.is_(True),
                    Calendar.deleted_at.is_(None),
                )
            ).one_or_none()
            if row is None:
                raise NotFoundError("Calendar not found")
            calendar, location = row
            result = availability.check(
                calendar.id, item.start_at, item.units, operator_id=operator.id, public=True
            )
            if not result.available:
                raise ConflictError(result.reason or "Requested booking is unavailable")
            mappings = list(
                self.db.execute(
                    select(Resource, CalendarResource.default_quantity_per_unit)
                    .join(CalendarResource, CalendarResource.resource_id == Resource.id)
                    .where(CalendarResource.calendar_id == calendar.id)
                    .order_by(Resource.id)
                ).all()
            )
            prepared.append(
                PreparedItem(
                    request_calendar_id=item.calendar_id,
                    start_at=item.start_at,
                    end_at=result.end_at,
                    units=item.units,
                    calendar=calendar,
                    location=location,
                    resources=mappings,
                )
            )
        currencies = {item.calendar.currency for item in prepared}
        if len(currencies) != 1:
            raise ConflictError("All items in an order must use the same currency")
        self._validate_requested_batch(prepared)
        return prepared

    def _validate_requested_batch(self, prepared: list[PreparedItem]) -> None:
        requested: dict[uuid.UUID, list[CapacityInterval]] = defaultdict(list)
        resource_lookup: dict[uuid.UUID, Resource] = {}
        for item in prepared:
            for resource, per_unit in item.resources:
                resource_lookup[resource.id] = resource
                requested[resource.id].append(
                    CapacityInterval(item.start_at, item.end_at, item.units * per_unit)
                )
        if not requested:
            return
        range_start = min(item.start_at for item in prepared)
        range_end = max(item.end_at for item in prepared)
        existing = AvailabilityService(self.db)._reservations(  # shared query, no calendar boundary
            list(requested), range_start, range_end
        )
        for resource_id, new_intervals in requested.items():
            resource = resource_lookup[resource_id]
            if not batch_fits(resource.quantity, existing.get(resource_id, []), new_intervals):
                raise ConflictError(
                    f"The selected occurrences exceed available {resource.name} inventory"
                )

    def _lock_resources(self, prepared: list[PreparedItem]) -> None:
        ids = sorted({resource.id for item in prepared for resource, _ in item.resources})
        if ids:
            list(
                self.db.scalars(
                    select(Resource).where(Resource.id.in_(ids)).order_by(Resource.id).with_for_update()
                )
            )

    @staticmethod
    def _quote(prepared: list[PreparedItem]) -> tuple[OrderQuoteResponse, PaymentBreakdown]:
        quoted_items = [item.quote() for item in prepared]
        subtotal = sum(item.line_subtotal_minor for item in quoted_items)
        payment = calculate_payment(subtotal)
        return (
            OrderQuoteResponse(
                currency=prepared[0].calendar.currency,
                items=quoted_items,
                subtotal_minor=payment.subtotal_minor,
                platform_fee_and_taxes_minor=payment.platform_fee_and_taxes_minor,
                customer_total_minor=payment.customer_total_minor,
            ),
            payment,
        )

    def quote(self, operator_slug: str, request: OrderQuoteRequest) -> OrderQuoteResponse:
        operator = self._operator(operator_slug)
        prepared = self._prepare(operator, request.items)
        return self._quote(prepared)[0]

    @staticmethod
    def _request_hash(request: OrderCreateRequest) -> str:
        payload = request.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _existing_response(
        self, order: BookingOrder, payment: Payment, checkout_hash: str
    ) -> OrderCreateResponse:
        if order.checkout_request_hash and order.checkout_request_hash != checkout_hash:
            raise ConflictError("Checkout key was already used with different booking details")
        items = [
            QuotedItem(
                calendar_id=booking.calendar_id,
                calendar_name=booking.calendar_name_snapshot,
                start_at=booking.start_at,
                end_at=booking.end_at,
                units=booking.units,
                base_price_minor=booking.base_price_minor,
                line_subtotal_minor=booking.base_price_minor * booking.units,
                departure_location_name=booking.departure_location_name_snapshot,
                departure_location_address=booking.departure_location_address_snapshot,
            )
            for booking in self.db.scalars(
                select(Booking).where(Booking.booking_order_id == order.id).order_by(Booking.start_at)
            )
        ]
        quote = OrderQuoteResponse(
            currency=order.currency,
            items=items,
            subtotal_minor=order.subtotal_minor,
            platform_fee_and_taxes_minor=order.platform_fee_and_taxes_minor,
            customer_total_minor=order.customer_total_minor,
        )
        client_secret = None
        if payment.stripe_payment_intent_id:
            try:
                intent = StripePaymentService(self.settings).retrieve_payment_intent(
                    payment.stripe_payment_intent_id
                )
                client_secret = intent.client_secret
            except Exception:
                client_secret = None
        token = PublicAccessService(self.db).issue(
            operator_id=order.operator_id,
            order_id=order.id,
            purpose="order_status",
            lifetime=timedelta(minutes=self.settings.public_access_minutes),
        )
        self.db.commit()
        return OrderCreateResponse(
            public_reference=order.public_reference,
            status=order.status,
            client_secret=client_secret,
            access_token=token,
            hold_expires_at=next(
                (booking.hold_expires_at for booking in self.db.scalars(
                    select(Booking).where(Booking.booking_order_id == order.id)
                ) if booking.hold_expires_at is not None),
                None,
            ),
            quote=quote,
        )

    def create(
        self,
        operator_slug: str,
        request: OrderCreateRequest,
        *,
        checkout_key: str | None = None,
    ) -> OrderCreateResponse:
        operator = self._operator(operator_slug)
        checkout_key = checkout_key or f"legacy:{uuid.uuid4()}"
        if len(checkout_key) > 160:
            raise ConflictError("Checkout key is too long")
        request_hash = self._request_hash(request)
        existing = self.db.scalar(
            select(BookingOrder).where(
                BookingOrder.operator_id == operator.id,
                BookingOrder.checkout_key == checkout_key,
            )
        )
        if existing is not None:
            payment = self.db.scalar(select(Payment).where(Payment.booking_order_id == existing.id))
            if payment is None:
                raise ConflictError("Existing checkout is missing its payment record")
            return self._existing_response(existing, payment, request_hash)
        # Serialize booking writes with Captain assignment writes on calendar rows.
        lock_calendars(self.db, operator.id, [item.calendar_id for item in request.items])
        prepared = self._prepare(operator, request.items)
        self._lock_resources(prepared)
        # Recalculate only after locks are held. Other reservations cannot lock/commit
        # these resource rows until this transaction completes.
        prepared = self._prepare(operator, request.items)
        quote, money = self._quote(prepared)
        paid = money.customer_total_minor > 0
        if paid:
            connection = self.db.scalar(
                select(StripeConnection).where(
                    StripeConnection.operator_id == operator.id,
                    StripeConnection.onboarding_complete.is_(True),
                    StripeConnection.payouts_enabled.is_(True),
                    StripeConnection.transfers_capability_status == "active",
                )
            )
            if connection is None:
                raise ConflictError("This operator is not ready to accept paid bookings")

        now = datetime.now(UTC)
        hold_expires = now + timedelta(minutes=self.settings.booking_hold_minutes) if paid else None
        reference = public_reference()
        order = BookingOrder(
            operator_id=operator.id,
            public_reference=reference,
            customer_first_name=request.customer.first_name,
            customer_last_name=request.customer.last_name,
            customer_email=str(request.customer.email),
            customer_phone=request.customer.phone or None,
            currency=quote.currency,
            subtotal_minor=money.subtotal_minor,
            platform_fee_and_taxes_minor=money.platform_fee_and_taxes_minor,
            customer_total_minor=money.customer_total_minor,
            operator_transfer_minor=money.operator_transfer_minor,
            platform_gross_retained_minor=money.platform_gross_retained_minor,
            checkout_key=checkout_key,
            checkout_request_hash=request_hash,
            status="pending_payment" if paid else "confirmed",
        )
        self.db.add(order)
        self.db.flush()
        for item in prepared:
            booking = Booking(
                operator_id=operator.id,
                booking_order_id=order.id,
                calendar_id=item.calendar.id,
                departure_location_id=item.location.id if item.location else None,
                start_at=item.start_at,
                end_at=item.end_at,
                units=item.units,
                base_price_minor=item.calendar.base_price_minor,
                status="pending_payment" if paid else "confirmed",
                hold_expires_at=hold_expires,
                calendar_name_snapshot=item.calendar.name,
                departure_location_name_snapshot=item.location.name if item.location else None,
                departure_location_address_snapshot=item.location.address if item.location else None,
            )
            self.db.add(booking)
            self.db.flush()
            self.db.add_all(
                [
                    BookingResource(
                        booking_id=booking.id,
                        resource_id=resource.id,
                        quantity=item.units * per_unit,
                    )
                    for resource, per_unit in item.resources
                ]
            )
        payment = Payment(
            operator_id=operator.id,
            booking_order_id=order.id,
            currency=quote.currency,
            subtotal_minor=money.subtotal_minor,
            platform_fee_and_taxes_minor=money.platform_fee_and_taxes_minor,
            customer_total_minor=money.customer_total_minor,
            operator_transfer_minor=money.operator_transfer_minor,
            platform_gross_retained_minor=money.platform_gross_retained_minor,
            status="requires_payment" if paid else "succeeded",
            paid_at=None if paid else now,
        )
        self.db.add(payment)
        self.db.flush()
        payment_request = None
        if paid:
            payment_request = PaymentIntentRequest(
                operator_id=operator.id,
                payment_id=payment.id,
                checkout_key=checkout_key,
                request_hash=request_hash,
                idempotency_key=f"booking_order:{order.id}:payment_intent",
                amount_minor=money.customer_total_minor,
                currency=quote.currency,
                request_payload={
                    "amount": money.customer_total_minor,
                    "currency": quote.currency,
                    "receipt_email": order.customer_email,
                    "order_id": str(order.id),
                    "operator_id": str(operator.id),
                    "public_reference": reference,
                },
                status="pending",
            )
            self.db.add(payment_request)
        if not paid:
            self._enqueue_confirmation_jobs(operator.id, order.id)
        access_token = PublicAccessService(self.db).issue(
            operator_id=operator.id,
            order_id=order.id,
            purpose="order_status",
            lifetime=timedelta(minutes=self.settings.public_access_minutes),
        )
        self.db.commit()

        # Apply the GHL contact/email/appointment jobs immediately after the
        # booking transaction is durable. Failed external calls remain in the
        # outbox with backoff and must not make the local booking fail.
        try:
            OutboxService(self.db, self.settings).process(limit=20)
        except Exception:
            logger.exception("Inline outbox processing failed after booking creation")

        client_secret = None
        if paid:
            try:
                intent_id, client_secret = StripePaymentService(self.settings).create_payment_intent(
                    order_id=str(order.id),
                    operator_id=str(operator.id),
                    public_reference=reference,
                    amount_minor=money.customer_total_minor,
                    currency=quote.currency,
                    receipt_email=order.customer_email,
                    idempotency_key=payment_request.idempotency_key if payment_request else None,
                )
                payment.stripe_payment_intent_id = intent_id
                payment.status = "processing"
                if payment_request:
                    payment_request.status = "processing"
                    payment_request.stripe_payment_intent_id = intent_id
                self.db.commit()
            except Exception as exc:
                payment.status = "processing"
                payment.reconciliation_status = "provider_unknown"
                payment.provider_unknown_at = datetime.now(UTC)
                if payment_request:
                    payment_request.status = "provider_unknown"
                    payment_request.last_error = str(exc)[:2000]
                    payment_request.provider_unknown_at = datetime.now(UTC)
                    self.db.add(
                        OutboxJob(
                            operator_id=operator.id,
                            booking_order_id=order.id,
                            job_type="stripe_reconcile_payment_intent",
                            idempotency_key=f"payment:{payment.id}:reconcile",
                            payload={"payment_id": str(payment.id)},
                            status="pending",
                        )
                    )
                self.db.commit()
                raise ConflictError(
                    "Payment setup could not be confirmed. Your checkout is reserved; refresh this page or contact support before retrying."
                ) from exc
        return OrderCreateResponse(
            public_reference=reference,
            status=order.status,
            client_secret=client_secret,
            access_token=access_token,
            hold_expires_at=hold_expires,
            quote=quote,
        )

    def _enqueue_confirmation_jobs(self, operator_id: uuid.UUID, order_id: uuid.UUID) -> None:
        jobs = [
                OutboxJob(
                    operator_id=operator_id,
                    booking_order_id=order_id,
                    job_type="ghl_upsert_contact",
                    idempotency_key=f"order:{order_id}:ghl_contact",
                    status="pending",
                ),
                OutboxJob(
                    operator_id=operator_id,
                    booking_order_id=order_id,
                    job_type="ghl_send_confirmation_email",
                    idempotency_key=f"order:{order_id}:ghl_email",
                    status="pending",
                ),
            ]
        bookings = list(self.db.scalars(select(Booking).where(Booking.booking_order_id == order_id)))
        jobs.extend(
            OutboxJob(
                operator_id=operator_id,
                booking_order_id=order_id,
                job_type="ghl_sync_appointment",
                    idempotency_key=f"booking:{booking.id}:ghl_appointment:create",
                payload={
                    "booking_id": str(booking.id),
                    "booking_order_id": str(order_id),
                },
                status="pending",
            )
            for booking in bookings
        )
        self.db.add_all(jobs)
