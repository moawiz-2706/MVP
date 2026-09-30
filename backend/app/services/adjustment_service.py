from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import (
    Booking,
    BookingAdjustment,
    BookingFinancialAllocation,
    BookingOrder,
    OutboxJob,
    Payment,
    PaymentRefundAttempt,
    StripeTransfer,
    TransferReversalAttempt,
)
from app.services.policy_service import PolicySnapshot


class AdjustmentService:
    """Create idempotent, append-only financial outcomes for lifecycle changes."""

    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def ensure_financial_allocations(
        self, order: BookingOrder, payment: Payment, bookings: list[Booking]
    ) -> None:
        existing = list(
            self.db.scalars(
                select(BookingFinancialAllocation).where(
                    BookingFinancialAllocation.payment_id == payment.id
                )
            )
        )
        if len(existing) == len(bookings):
            return
        subtotal_total = sum(booking.base_price_minor * booking.units for booking in bookings)
        if subtotal_total <= 0:
            subtotal_total = len(bookings)
        allocated_customer = 0
        allocated_operator = 0
        for index, booking in enumerate(bookings):
            subtotal = booking.base_price_minor * booking.units
            if index == len(bookings) - 1:
                customer = order.customer_total_minor - allocated_customer
                operator = order.operator_transfer_minor - allocated_operator
            else:
                customer = (order.customer_total_minor * subtotal) // subtotal_total
                operator = (order.operator_transfer_minor * subtotal) // subtotal_total
            self.db.add(
                BookingFinancialAllocation(
                    operator_id=self.operator_id,
                    booking_id=booking.id,
                    payment_id=payment.id,
                    subtotal_minor=subtotal,
                    customer_refund_minor=max(0, customer),
                    operator_recovery_minor=max(0, operator),
                    source_snapshot={
                        "calendar_id": str(booking.calendar_id),
                        "base_price_minor": booking.base_price_minor,
                        "units": booking.units,
                    },
                )
            )
            allocated_customer += max(0, customer)
            allocated_operator += max(0, operator)
        self.db.flush()

    def existing(self, idempotency_key: str) -> BookingAdjustment | None:
        return self.db.scalar(
            select(BookingAdjustment).where(
                BookingAdjustment.operator_id == self.operator_id,
                BookingAdjustment.idempotency_key == idempotency_key,
            )
        )

    def record(
        self,
        booking: Booking,
        payment: Payment | None,
        *,
        action: str,
        amount_minor: int,
        original_amount_minor: int,
        reason: str,
        policy_version: int,
        idempotency_key: str,
        status: str = "pending",
        metadata: dict[str, Any] | None = None,
    ) -> BookingAdjustment:
        existing = self.existing(idempotency_key)
        if existing is not None:
            return existing
        adjustment = BookingAdjustment(
            operator_id=self.operator_id,
            booking_id=booking.id,
            payment_id=payment.id if payment else None,
            action=action,
            amount_minor=max(0, amount_minor),
            original_amount_minor=max(0, original_amount_minor),
            currency=payment.currency if payment else "usd",
            reason=reason,
            policy_version=policy_version,
            idempotency_key=idempotency_key,
            status=status,
            adjustment_metadata=metadata or {},
        )
        self.db.add(adjustment)
        self.db.flush()
        return adjustment

    def _schedule_refund(
        self,
        booking: Booking,
        order: BookingOrder,
        payment: Payment,
        *,
        amount_minor: int,
        original_amount_minor: int,
        reason: str,
        policy_version: int,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> BookingAdjustment:
        if amount_minor <= 0 or payment.status != "succeeded":
            return self.record(
                booking,
                payment,
                action="none",
                amount_minor=0,
                original_amount_minor=original_amount_minor,
                reason=reason,
                policy_version=policy_version,
                idempotency_key=idempotency_key,
                status="completed",
                metadata=metadata,
            )
        attempt_scope = f"adjustment:{booking.id}:{idempotency_key}"
        attempt_id = self.db.scalar(
            insert(PaymentRefundAttempt)
            .values(
                operator_id=self.operator_id,
                payment_id=payment.id,
                scope_key=attempt_scope,
                amount_minor=amount_minor,
                currency=payment.currency,
                idempotency_key=f"payment:{payment.id}:refund:{idempotency_key}",
                status="requested",
            )
            .on_conflict_do_nothing(
                index_elements=[PaymentRefundAttempt.payment_id, PaymentRefundAttempt.scope_key]
            )
            .returning(PaymentRefundAttempt.id)
        )
        adjustment = self.record(
            booking,
            payment,
            action="refund",
            amount_minor=amount_minor,
            original_amount_minor=original_amount_minor,
            reason=reason,
            policy_version=policy_version,
            idempotency_key=idempotency_key,
            status="pending",
            metadata={**(metadata or {}), "refund_attempt_scope": attempt_scope},
        )
        payment.reconciliation_status = "refund_pending"
        if attempt_id is not None:
            self.db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=self.operator_id,
                    booking_order_id=order.id,
                    job_type="stripe_create_refund",
                    idempotency_key=f"payment:{payment.id}:refund-job:{idempotency_key}",
                    payload={"refund_attempt_id": str(attempt_id)},
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )
        return adjustment

    def cancellation(
        self,
        booking: Booking,
        order: BookingOrder,
        payment: Payment,
        policy: PolicySnapshot,
        *,
        mode: str | None = None,
        reason: str = "booking_cancelled",
        idempotency_key: str,
    ) -> BookingAdjustment:
        allocation = self.db.scalar(
            select(BookingFinancialAllocation).where(
                BookingFinancialAllocation.booking_id == booking.id,
                BookingFinancialAllocation.payment_id == payment.id,
            )
        )
        gross = allocation.customer_refund_minor if allocation else 0
        chosen_mode = mode or "policy"
        if payment.status != "succeeded":
            return self.record(
                booking, payment, action="none", amount_minor=0, original_amount_minor=gross,
                reason=reason, policy_version=policy.version, idempotency_key=idempotency_key,
                status="completed", metadata={"payment_status": payment.status},
            )
        if chosen_mode == "full_refund":
            refund, fee = gross, 0
        elif chosen_mode == "credit":
            return self.record(
                booking, payment, action="credit", amount_minor=gross, original_amount_minor=gross,
                reason=reason, policy_version=policy.version, idempotency_key=idempotency_key,
                status="completed", metadata={"credit_ledger": True},
            )
        elif chosen_mode == "manual_review":
            return self.record(
                booking, payment, action="manual_review", amount_minor=gross, original_amount_minor=gross,
                reason=reason, policy_version=policy.version, idempotency_key=idempotency_key,
                status="pending", metadata={"requires_operator_review": True},
            )
        elif chosen_mode == "no_refund":
            refund, fee = 0, gross
        else:
            fee = (gross * policy.cancellation_fee_bps) // 10_000
            refund = max(0, gross - fee)
        if refund:
            return self._schedule_refund(
                booking, order, payment, amount_minor=refund, original_amount_minor=gross,
                reason=reason, policy_version=policy.version, idempotency_key=idempotency_key,
                metadata={"gross_eligible_minor": gross, "retained_fee_minor": fee},
            )
        return self.record(
            booking, payment, action="charge" if fee else "none", amount_minor=fee,
            original_amount_minor=gross, reason=reason, policy_version=policy.version,
            idempotency_key=idempotency_key, status="completed",
            metadata={"retained_fee_minor": fee},
        )

    def reschedule_refund(
        self,
        booking: Booking,
        order: BookingOrder,
        payment: Payment,
        *,
        amount_minor: int,
        original_amount_minor: int,
        policy_version: int,
        idempotency_key: str,
    ) -> BookingAdjustment:
        return self._schedule_refund(
            booking, order, payment, amount_minor=amount_minor,
            original_amount_minor=original_amount_minor, reason="reschedule_price_decrease",
            policy_version=policy_version, idempotency_key=idempotency_key,
        )

    def no_show(
        self,
        booking: Booking,
        order: BookingOrder,
        payment: Payment,
        policy: PolicySnapshot,
        *,
        idempotency_key: str,
    ) -> BookingAdjustment:
        allocation = self.db.scalar(
            select(BookingFinancialAllocation).where(
                BookingFinancialAllocation.booking_id == booking.id,
                BookingFinancialAllocation.payment_id == payment.id,
            )
        )
        gross = allocation.customer_refund_minor if allocation else 0
        if policy.no_show_mode == "partial_refund" and gross:
            return self._schedule_refund(
                booking, order, payment, amount_minor=gross // 2,
                original_amount_minor=gross, reason="no_show_partial_refund",
                policy_version=policy.version, idempotency_key=idempotency_key,
            )
        if policy.no_show_mode == "manual_review":
            return self.record(
                booking, payment, action="manual_review", amount_minor=gross,
                original_amount_minor=gross, reason="no_show_manual_review",
                policy_version=policy.version, idempotency_key=idempotency_key,
                status="pending", metadata={"requires_operator_review": True},
            )
        return self.record(
            booking, payment, action="charge" if gross else "none", amount_minor=gross,
            original_amount_minor=gross, reason="no_show_forfeit",
            policy_version=policy.version, idempotency_key=idempotency_key,
            status="completed", metadata={"forfeited": True},
        )

    def schedule_transfer_reversal(
        self, booking: Booking, order: BookingOrder, payment: Payment, allocation: BookingFinancialAllocation,
        *, scope_key: str,
    ) -> None:
        if allocation.operator_recovery_minor <= 0:
            return
        transfer = self.db.scalar(select(StripeTransfer).where(StripeTransfer.payment_id == payment.id))
        if transfer is None or not transfer.stripe_transfer_id:
            return
        reversal_id = self.db.scalar(
            insert(TransferReversalAttempt)
            .values(
                operator_id=self.operator_id,
                transfer_id=transfer.id,
                scope_key=scope_key,
                amount_minor=allocation.operator_recovery_minor,
                idempotency_key=f"transfer:{transfer.id}:reversal:{scope_key}",
                status="requested",
            )
            .on_conflict_do_nothing(
                index_elements=[TransferReversalAttempt.transfer_id, TransferReversalAttempt.scope_key]
            )
            .returning(TransferReversalAttempt.id)
        )
        if reversal_id is not None:
            self.db.execute(
                insert(OutboxJob)
                .values(
                    operator_id=self.operator_id,
                    booking_order_id=order.id,
                    job_type="stripe_create_transfer_reversal",
                    idempotency_key=f"transfer:{transfer.id}:reversal-job:{scope_key}",
                    payload={"reversal_attempt_id": str(reversal_id)},
                    status="pending",
                )
                .on_conflict_do_nothing(index_elements=[OutboxJob.idempotency_key])
            )
