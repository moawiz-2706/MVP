from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.entities import (
    Booking,
    BookingOrder,
    Operator,
    Payment,
    PublicAccessCredential,
)
from app.schemas.order import (
    OrderCreateRequest,
    OrderCreateResponse,
    OrderQuoteRequest,
    OrderQuoteResponse,
    PublicOrderItem,
    PublicOrderStatus,
)
from app.services.order_service import OrderService
from app.services.outbox_service import OutboxService
from app.services.public_rate_limit_service import enforce_public_rate_limit
from app.services.stripe_payment_reconciliation_service import StripePaymentReconciliationService
from app.services.waiver_service import SIGNABLE_STATUSES, WaiverService, waiver_url

router = APIRouter(tags=["public orders"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/public/{operator_slug}/orders/quote", response_model=OrderQuoteResponse)
def quote_order(
    operator_slug: str,
    data: OrderQuoteRequest,
    db: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
):
    enforce_public_rate_limit(request, db, settings, scope=f"quote:{operator_slug}")
    return OrderService(db, settings).quote(operator_slug, data)


@router.post(
    "/public/{operator_slug}/orders",
    response_model=OrderCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    operator_slug: str,
    data: OrderCreateRequest,
    db: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
    checkout_key: Annotated[str | None, Header(alias="X-Checkout-Key")] = None,
):
    enforce_public_rate_limit(request, db, settings, scope=f"checkout:{operator_slug}")
    result = OrderService(db, settings).create(operator_slug, data, checkout_key=checkout_key)
    try:
        OutboxService(db, settings).process(limit=10)
    except Exception:
        # Booking/payment state is already committed. Failed GHL work stays in
        # the outbox and is retried by the internal worker.
        pass
    return result


@router.get("/public/orders/{public_reference}/status", response_model=PublicOrderStatus)
def order_status(
    public_reference: str,
    db: DB,
    response: Response,
    request: Request,
    access_token: Annotated[str | None, Query(min_length=20, max_length=512)] = None,
    reconcile: Annotated[bool, Query()] = False,
):
    enforce_public_rate_limit(request, db, get_settings(), scope=f"status:{public_reference}")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    row = db.execute(
        select(BookingOrder, Payment, Operator)
        .join(Payment, Payment.booking_order_id == BookingOrder.id)
        .join(Operator, Operator.id == BookingOrder.operator_id)
        .where(BookingOrder.public_reference == public_reference)
    ).one_or_none()
    if row is None:
        raise NotFoundError("Order not found")
    order, payment, operator = row
    if reconcile and payment.status == "processing" and payment.stripe_payment_intent_id:
        try:
            StripePaymentReconciliationService(db, get_settings()).reconcile(payment.id)
            row = db.execute(
                select(BookingOrder, Payment, Operator)
                .join(Payment, Payment.booking_order_id == BookingOrder.id)
                .join(Operator, Operator.id == BookingOrder.operator_id)
                .where(BookingOrder.public_reference == public_reference)
            ).one_or_none()
            if row is None:
                raise NotFoundError("Order not found")
            order, payment, operator = row
        except Exception:
            # Status polling must remain available even when Stripe is temporarily
            # unreachable. The scheduled reconciliation job remains the fallback.
            db.rollback()
    if access_token:
        from app.services.public_access_service import PublicAccessService

        PublicAccessService(db).verify(
            access_token, purpose="order_status", order_id=order.id
        )
    elif db.scalar(
        select(PublicAccessCredential.id).where(
            PublicAccessCredential.order_id == order.id,
            PublicAccessCredential.purpose == "order_status",
            PublicAccessCredential.revoked_at.is_(None),
        )
    ):
        raise NotFoundError("Order access link is required")
    bookings = list(
        db.scalars(
            select(Booking)
            .where(Booking.booking_order_id == order.id)
            .order_by(Booking.start_at)
        )
    )
    confirmed = order.status == "confirmed" and all(
        booking.status == "confirmed" for booking in bookings
    )
    # Waiver links appear once the order is confirmed and the operator has a waiver.
    waivers = WaiverService(db)
    links: dict = {}
    if confirmed and waivers.configured(operator.id):
        for booking in bookings:
            if booking.status in SIGNABLE_STATUSES:
                waiver = waivers.ensure(booking)
                links[booking.id] = (waiver_url(waiver.token), waiver.status == "signed")
    return PublicOrderStatus(
        public_reference=order.public_reference,
        access_token=None,
        status=order.status,
        time_zone=operator.time_zone,
        payment_status=payment.status,
        confirmed=confirmed,
        customer_name=f"{order.customer_first_name} {order.customer_last_name}",
        currency=order.currency,
        subtotal_minor=order.subtotal_minor,
        platform_fee_and_taxes_minor=order.platform_fee_and_taxes_minor,
        customer_total_minor=order.customer_total_minor,
        items=[
            PublicOrderItem(
                calendar_id=booking.calendar_id,
                calendar_name=booking.calendar_name_snapshot,
                start_at=booking.start_at,
                end_at=booking.end_at,
                units=booking.units,
                base_price_minor=booking.base_price_minor,
                line_subtotal_minor=booking.base_price_minor * booking.units,
                departure_location_name=booking.departure_location_name_snapshot,
                departure_location_address=booking.departure_location_address_snapshot,
                waiver_url=links.get(booking.id, (None, False))[0],
                waiver_signed=links.get(booking.id, (None, False))[1],
            )
            for booking in bookings
        ],
    )
