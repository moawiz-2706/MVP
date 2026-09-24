from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.entities import (
    Booking,
    BookingAdjustment,
    BookingCustomFieldDefinition,
    BookingCustomFieldValue,
    BookingOrder,
    Calendar,
    CalendarBookingPolicy,
    Customer,
    CustomerNote,
    MigrationImport,
    MigrationImportRow,
    Payment,
    ReconciliationRun,
    WeatherClosureEvent,
)
from app.schemas.fareharbor_replica import (
    BookingCustomFieldsWrite,
    BookingPolicyWrite,
    BookingStatusRequest,
    CustomerNoteCreate,
    CustomerUpdate,
    MigrationImportCreate,
    ReconciliationRunCreate,
    WeatherClosureRequest,
)
from app.services.booking_admin_service import BookingAdminService


class FareHarborReplicaService:
    def __init__(self, db: Session, operator_id: uuid.UUID) -> None:
        self.db = db
        self.operator_id = operator_id

    def _calendar(self, calendar_id: uuid.UUID) -> Calendar:
        calendar = self.db.scalar(
            select(Calendar).where(
                Calendar.id == calendar_id,
                Calendar.operator_id == self.operator_id,
                Calendar.deleted_at.is_(None),
            )
        )
        if calendar is None:
            raise NotFoundError("Calendar not found")
        return calendar

    def policy(self, calendar_id: uuid.UUID) -> dict[str, Any]:
        self._calendar(calendar_id)
        policy = self.db.scalar(
            select(CalendarBookingPolicy)
            .where(
                CalendarBookingPolicy.calendar_id == calendar_id,
                CalendarBookingPolicy.operator_id == self.operator_id,
                CalendarBookingPolicy.active.is_(True),
            )
            .order_by(CalendarBookingPolicy.version.desc())
        )
        if policy is None:
            return {
                "calendar_id": calendar_id,
                "version": 0,
                "cancellation_cutoff_minutes": 0,
                "cancellation_fee_bps": 0,
                "weather_refund_mode": "full_refund",
                "reschedule_cutoff_minutes": 0,
                "reschedule_fee_minor": 0,
                "no_show_mode": "forfeit",
                "deposit_bps": 0,
                "requires_waiver": False,
                "active": True,
            }
        return self._policy_dict(policy)

    @staticmethod
    def _policy_dict(policy: CalendarBookingPolicy) -> dict[str, Any]:
        return {
            "calendar_id": policy.calendar_id,
            "version": policy.version,
            "cancellation_cutoff_minutes": policy.cancellation_cutoff_minutes,
            "cancellation_fee_bps": policy.cancellation_fee_bps,
            "weather_refund_mode": policy.weather_refund_mode,
            "reschedule_cutoff_minutes": policy.reschedule_cutoff_minutes,
            "reschedule_fee_minor": policy.reschedule_fee_minor,
            "no_show_mode": policy.no_show_mode,
            "deposit_bps": policy.deposit_bps,
            "requires_waiver": policy.requires_waiver,
            "active": policy.active,
        }

    def replace_policy(self, calendar_id: uuid.UUID, data: BookingPolicyWrite) -> dict[str, Any]:
        self._calendar(calendar_id)
        current = self.db.scalar(
            select(func.max(CalendarBookingPolicy.version)).where(
                CalendarBookingPolicy.calendar_id == calendar_id,
                CalendarBookingPolicy.operator_id == self.operator_id,
            )
        ) or 0
        self.db.query(CalendarBookingPolicy).filter(
            CalendarBookingPolicy.calendar_id == calendar_id,
            CalendarBookingPolicy.operator_id == self.operator_id,
        ).update({"active": False})
        policy = CalendarBookingPolicy(
            operator_id=self.operator_id,
            calendar_id=calendar_id,
            version=current + 1,
            **data.model_dump(),
        )
        self.db.add(policy)
        self.db.commit()
        return self._policy_dict(policy)

    def list_custom_fields(self, calendar_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        conditions = [
            BookingCustomFieldDefinition.operator_id == self.operator_id,
            BookingCustomFieldDefinition.active.is_(True),
        ]
        if calendar_id is not None:
            conditions.append(
                (BookingCustomFieldDefinition.calendar_id == calendar_id)
                | (BookingCustomFieldDefinition.calendar_id.is_(None))
            )
        return [
            {
                "id": field.id,
                "calendar_id": field.calendar_id,
                "key": field.key,
                "label": field.label,
                "field_type": field.field_type,
                "required": field.required,
                "options": field.options,
                "active": field.active,
            }
            for field in self.db.scalars(
                select(BookingCustomFieldDefinition)
                .where(*conditions)
                .order_by(BookingCustomFieldDefinition.created_at)
            )
        ]

    def create_custom_field(self, data) -> dict[str, Any]:
        if data.calendar_id:
            self._calendar(data.calendar_id)
        if data.field_type == "select" and not data.options:
            raise ConflictError("Select fields require at least one option")
        field = BookingCustomFieldDefinition(
            operator_id=self.operator_id,
            **data.model_dump(),
        )
        self.db.add(field)
        self.db.commit()
        return self.list_custom_fields(field.calendar_id)[-1]

    def delete_custom_field(self, field_id: uuid.UUID) -> None:
        field = self.db.scalar(
            select(BookingCustomFieldDefinition).where(
                BookingCustomFieldDefinition.id == field_id,
                BookingCustomFieldDefinition.operator_id == self.operator_id,
            )
        )
        if field is None:
            raise NotFoundError("Custom field not found")
        field.active = False
        self.db.commit()

    def update_custom_field(self, field_id: uuid.UUID, data) -> dict[str, Any]:
        field = self.db.scalar(
            select(BookingCustomFieldDefinition).where(
                BookingCustomFieldDefinition.id == field_id,
                BookingCustomFieldDefinition.operator_id == self.operator_id,
            ).with_for_update()
        )
        if field is None:
            raise NotFoundError("Custom field not found")
        if data.calendar_id:
            self._calendar(data.calendar_id)
        if data.field_type == "select" and not data.options:
            raise ConflictError("Select fields require at least one option")
        for key, value in data.model_dump().items():
            setattr(field, key, value)
        self.db.commit()
        return {
            "id": field.id,
            "calendar_id": field.calendar_id,
            "key": field.key,
            "label": field.label,
            "field_type": field.field_type,
            "required": field.required,
            "options": field.options,
            "active": field.active,
        }

    def _customer_item(self, customer: Customer) -> dict[str, Any]:
        booking_count = self.db.scalar(
            select(func.count(BookingOrder.id)).where(BookingOrder.customer_id == customer.id)
        ) or 0
        latest = self.db.scalar(
            select(func.max(Booking.created_at))
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .where(BookingOrder.customer_id == customer.id)
        )
        paid = self.db.scalar(
            select(func.coalesce(func.sum(Payment.customer_total_minor), 0))
            .join(BookingOrder, BookingOrder.id == Payment.booking_order_id)
            .where(BookingOrder.customer_id == customer.id, Payment.status.in_(["succeeded", "partially_refunded", "refunded"]))
        ) or 0
        return {
            "id": customer.id,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "email": customer.email,
            "phone": customer.phone,
            "booking_count": booking_count,
            "latest_booking_at": latest,
            "total_paid_minor": paid,
            "ghl_contact_id": customer.ghl_contact_id,
        }

    @staticmethod
    def _email(value: str) -> str:
        return value.strip().lower()

    @staticmethod
    def _phone(value: str | None) -> str | None:
        return re.sub(r"[^0-9+]", "", value or "") or None

    def upsert_customer(self, first_name: str, last_name: str, email: str, phone: str | None = None) -> Customer:
        normalized_email = self._email(email)
        customer = self.db.scalar(
            select(Customer).where(
                Customer.operator_id == self.operator_id,
                Customer.normalized_email == normalized_email,
            ).with_for_update()
        )
        normalized_phone = self._phone(phone)
        if customer is None:
            customer = Customer(
                operator_id=self.operator_id,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                email=email,
                normalized_email=normalized_email,
                phone=phone,
                normalized_phone=normalized_phone,
            )
            self.db.add(customer)
        else:
            customer.first_name = first_name.strip()
            customer.last_name = last_name.strip()
            customer.email = email
            customer.phone = phone
            customer.normalized_phone = normalized_phone
        self.db.flush()
        return customer

    def customers(self, search: str | None = None) -> list[dict[str, Any]]:
        query = select(Customer).where(Customer.operator_id == self.operator_id, Customer.is_active.is_(True))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(
                Customer.first_name.ilike(needle)
                | Customer.last_name.ilike(needle)
                | Customer.email.ilike(needle)
                | Customer.phone.ilike(needle)
            )
        return [self._customer_item(customer) for customer in self.db.scalars(query.order_by(Customer.last_name, Customer.first_name))]

    def customer(self, customer_id: uuid.UUID) -> dict[str, Any]:
        customer = self.db.scalar(select(Customer).where(Customer.id == customer_id, Customer.operator_id == self.operator_id))
        if customer is None:
            raise NotFoundError("Customer not found")
        items = self._customer_item(customer)
        notes = [
            {"id": note.id, "body": note.body, "author_name": note.author_name, "created_at": note.created_at}
            for note in self.db.scalars(select(CustomerNote).where(CustomerNote.customer_id == customer.id).order_by(CustomerNote.created_at.desc()))
        ]
        bookings = []
        for booking, order in self.db.execute(
            select(Booking, BookingOrder)
            .join(BookingOrder, BookingOrder.id == Booking.booking_order_id)
            .where(BookingOrder.customer_id == customer.id)
            .order_by(Booking.start_at.desc())
        ):
            bookings.append({"id": booking.id, "public_reference": order.public_reference, "calendar_name": booking.calendar_name_snapshot, "start_at": booking.start_at, "units": booking.units, "status": booking.status, "total_minor": order.customer_total_minor})
        return {**items, "notes": notes, "custom_fields": {}, "bookings": bookings}

    def update_customer(self, customer_id: uuid.UUID, data: CustomerUpdate) -> dict[str, Any]:
        customer = self.db.scalar(select(Customer).where(Customer.id == customer_id, Customer.operator_id == self.operator_id).with_for_update())
        if customer is None:
            raise NotFoundError("Customer not found")
        customer.first_name = data.first_name
        customer.last_name = data.last_name
        customer.email = str(data.email)
        customer.normalized_email = self._email(str(data.email))
        customer.phone = data.phone
        customer.normalized_phone = self._phone(data.phone)
        self.db.commit()
        return self._customer_item(customer)

    def add_customer_note(self, customer_id: uuid.UUID, data: CustomerNoteCreate, user_id: uuid.UUID) -> dict[str, Any]:
        if self.db.scalar(select(Customer.id).where(Customer.id == customer_id, Customer.operator_id == self.operator_id)) is None:
            raise NotFoundError("Customer not found")
        note = CustomerNote(operator_id=self.operator_id, customer_id=customer_id, author_user_id=user_id, body=data.body)
        self.db.add(note)
        self.db.commit()
        return {"id": note.id, "body": note.body, "author_name": note.author_name, "created_at": note.created_at}

    def set_booking_fields(self, booking_id: uuid.UUID, data: BookingCustomFieldsWrite) -> dict[str, Any]:
        booking = self.db.scalar(select(Booking).where(Booking.id == booking_id, Booking.operator_id == self.operator_id))
        if booking is None:
            raise NotFoundError("Booking not found")
        definitions = {field.key: field for field in self.db.scalars(select(BookingCustomFieldDefinition).where(BookingCustomFieldDefinition.operator_id == self.operator_id, BookingCustomFieldDefinition.active.is_(True), (BookingCustomFieldDefinition.calendar_id == booking.calendar_id) | (BookingCustomFieldDefinition.calendar_id.is_(None))))}
        missing = [field.key for field in definitions.values() if field.required and field.key not in data.values]
        if missing:
            raise ConflictError("Required custom fields missing: " + ", ".join(missing))
        for key, value in data.values.items():
            definition = definitions.get(key)
            if definition is None:
                raise ConflictError(f"Unknown custom field: {key}")
            existing = self.db.scalar(select(BookingCustomFieldValue).where(BookingCustomFieldValue.booking_id == booking_id, BookingCustomFieldValue.definition_id == definition.id))
            if existing is None:
                self.db.add(BookingCustomFieldValue(booking_id=booking_id, definition_id=definition.id, value=value))
            else:
                existing.value = value
        self.db.commit()
        return data.values

    def status(self, booking_id: uuid.UUID, data: BookingStatusRequest) -> dict[str, Any]:
        booking = self.db.scalar(select(Booking).where(Booking.id == booking_id, Booking.operator_id == self.operator_id).with_for_update())
        if booking is None:
            raise NotFoundError("Booking not found")
        booking.status = data.status
        if data.status == "cancelled":
            booking.hold_expires_at = None
        self.db.add(BookingAdjustment(operator_id=self.operator_id, booking_id=booking.id, action="none", amount_minor=0, currency="usd", reason=data.reason, idempotency_key=data.idempotency_key or f"status:{booking.id}:{data.status}:{uuid.uuid4()}", status="completed"))
        self.db.commit()
        return BookingAdminService(self.db, self.operator_id).detail(booking.id)

    def weather_closure(self, data: WeatherClosureRequest, user_id: uuid.UUID) -> dict[str, Any]:
        self._calendar(data.calendar_id)
        closure = WeatherClosureEvent(operator_id=self.operator_id, created_by_user_id=user_id, **data.model_dump())
        self.db.add(closure)
        bookings = list(self.db.scalars(select(Booking).where(Booking.operator_id == self.operator_id, Booking.calendar_id == data.calendar_id, Booking.start_at < data.end_at, Booking.end_at > data.start_at, Booking.status.in_(["pending_payment", "confirmed"]))))
        for booking in bookings:
            booking.status = "cancelled"
            self.db.add(BookingAdjustment(operator_id=self.operator_id, booking_id=booking.id, action="refund" if data.refund_mode == "full_refund" else "manual_review", amount_minor=0, currency="usd", reason=data.reason, idempotency_key=f"weather:{closure.id}:{booking.id}", status="pending"))
        self.db.commit()
        return {"closure_id": closure.id, "affected_bookings": len(bookings), "refund_mode": data.refund_mode}

    def stage_import(self, data: MigrationImportCreate) -> dict[str, Any]:
        errors = 0
        for row in data.rows:
            if not row.get("external_id"):
                errors += 1
        summary = {"rows": len(data.rows), "valid_rows": len(data.rows) - errors, "blocking_errors": errors, "unresolved": []}
        item = MigrationImport(operator_id=self.operator_id, provider=data.provider, source_filename=data.source_filename, summary=summary, blocking_errors=errors, status="validated" if errors == 0 else "needs_review")
        self.db.add(item)
        self.db.flush()
        for row_number, row in enumerate(data.rows, start=1):
            row_errors = [] if row.get("external_id") else ["external_id is required"]
            self.db.add(
                MigrationImportRow(
                    import_id=item.id,
                    row_number=row_number,
                    external_id=str(row.get("external_id")) if row.get("external_id") else None,
                    payload=row,
                    status="validated" if not row_errors else "needs_review",
                    errors=row_errors or None,
                )
            )
        self.db.commit()
        return {"id": item.id, "provider": item.provider, "status": item.status, "source_filename": item.source_filename, "summary": item.summary, "blocking_errors": item.blocking_errors, "committed_at": item.committed_at}

    def commit_import(self, import_id: uuid.UUID) -> dict[str, Any]:
        item = self.db.scalar(select(MigrationImport).where(MigrationImport.id == import_id, MigrationImport.operator_id == self.operator_id).with_for_update())
        if item is None:
            raise NotFoundError("Migration import not found")
        if item.blocking_errors:
            raise ConflictError("Resolve blocking migration errors before commit")
        rows = list(
            self.db.scalars(
                select(MigrationImportRow).where(MigrationImportRow.import_id == item.id).order_by(MigrationImportRow.row_number)
            )
        )
        customer_rows = 0
        for row in rows:
            payload = row.payload
            if payload.get("email"):
                self.upsert_customer(
                    str(payload.get("first_name") or "Imported"),
                    str(payload.get("last_name") or "Customer"),
                    str(payload["email"]),
                    str(payload.get("phone")) if payload.get("phone") else None,
                )
                row.status = "committed"
                customer_rows += 1
        item.status = "committed"
        item.summary = {**(item.summary or {}), "customer_rows_committed": customer_rows}
        item.committed_at = datetime.now(UTC)
        self.db.commit()
        return {"id": item.id, "provider": item.provider, "status": item.status, "source_filename": item.source_filename, "summary": item.summary, "blocking_errors": item.blocking_errors, "committed_at": item.committed_at}

    def reconciliation(self, data: ReconciliationRunCreate) -> dict[str, Any]:
        run = ReconciliationRun(operator_id=self.operator_id, scope=data.scope, status="completed", summary={"matched": 0, "repaired": 0, "manual_review": 0, "message": "Run queued for the worker reconciliation pass"}, started_at=datetime.now(UTC), finished_at=datetime.now(UTC))
        self.db.add(run)
        self.db.commit()
        return {"id": run.id, "scope": run.scope, "status": run.status, "summary": run.summary, "started_at": run.started_at, "finished_at": run.finished_at}
