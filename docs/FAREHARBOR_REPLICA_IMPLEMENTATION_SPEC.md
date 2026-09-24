# Passport FareHarbor-Replica Implementation Specification

## Purpose

Passport will become the authoritative booking, inventory, pricing, customer, payment, waiver, notification, and reconciliation layer. GoHighLevel will remain a projection and operational companion for calendar events, appointment assignment, staff identity, and contact identity. Passport must not depend on GHL availability or GHL custom objects to decide whether a booking can be sold.

## Scope and delivery phases

| Phase | Passport capability | Primary API surface | GHL dependency |
| --- | --- | --- | --- |
| A | Customer types, resource-aware rates, itemized pricing, party rules, bookability modes | `/customer-types`, `/calendars/{id}/rates`, `/public/{operator}/calendars/{slug}/rates` | None |
| B | Cancellation, rescheduling, no-show, weather closure, refunds, and custom booking fields | `/booking-policies`, `/bookings/{id}/reschedule`, `/bookings/{id}/status`, `/bookings/{id}/custom-fields` | Appointment update/cancel projection only |
| C | FareHarbor-style migration and reconciliation | `/migration/imports`, `/migration/mappings`, `/reconciliation/runs` | Read-only import or operator-provided export; optional GHL projection |
| D | Operator workspace, booking board, inventory board, customer records, exceptions, audit log | `/customers`, `/inventory`, `/exceptions`, `/audit` | Staff/contact/calendar status only |
| E | Customer-facing FareHarbor-style checkout | `/public/{operator}`, `/availability`, `/orders/quote`, `/orders` | Stripe only for payment; GHL not authoritative |

## Domain requirements

Passport must retain immutable snapshots at booking time for calendar, rate, customer type, resource consumption, pricing components, taxes, fees, policy version, waiver text, and custom-field definitions. Updating a calendar or rate must never rewrite an historical booking.

Every booking mutation must be idempotent, tenant-scoped, transaction-safe, and represented in the outbox. A booking can be confirmed only after capacity validation and payment state validation. A cancellation or reschedule must create a financial adjustment record before a refund or transfer reversal job is emitted.

## Required APIs and expected responses

### Booking policies

`GET /calendars/{calendar_id}/booking-policy` returns:

```json
{
  "calendar_id": "uuid",
  "version": 3,
  "cancellation_cutoff_minutes": 1440,
  "cancellation_fee_bps": 0,
  "weather_refund_mode": "full_refund",
  "reschedule_cutoff_minutes": 720,
  "reschedule_fee_minor": 0,
  "no_show_mode": "forfeit",
  "deposit_bps": 0,
  "requires_waiver": true,
  "active": true
}
```

`PUT /calendars/{calendar_id}/booking-policy` creates a new version and returns the same object with the new version number. Existing bookings retain the previous policy version.

### Booking operations

`POST /bookings/{booking_id}/reschedule` accepts `start_at`, `rate_id` or `units`, `reason`, and an idempotency key. It returns the updated booking, an adjustment summary, and an `action` of `none`, `collect_payment`, `refund`, or `manual_review`.

`POST /bookings/{booking_id}/status` accepts `status` in `confirmed`, `completed`, `no_show`, `cancelled`, or `failed`, plus `reason`. It returns the updated booking and any queued financial action.

`POST /bookings/{booking_id}/weather-cancel` accepts an operator reason and returns the booking status, refund decision, refund amount, and customer notification status.

`POST /bookings/{booking_id}/custom-fields` accepts a field-value map keyed by Passport field IDs. It returns validated values plus any validation errors.

### Customer records

`GET /customers?search=&status=&page=` returns paginated customers with booking count, total paid, latest booking, waiver status, and contact synchronization state.

`GET /customers/{customer_id}` returns profile data, booking history, custom-field values, payment summary, waiver history, and internal notes.

`PATCH /customers/{customer_id}` updates Passport-owned customer information without mutating GHL-managed identity fields unless explicitly projected.

### Migration and reconciliation

`POST /migration/imports` accepts a FareHarbor export file or normalized JSON payload and creates a staged import. It must not create live bookings until validation succeeds.

`GET /migration/imports/{id}` returns row counts, validation errors, duplicate matches, unresolved calendars, unresolved customer types, unresolved resources, and payment/waiver warnings.

`POST /migration/imports/{id}/commit` requires a dry-run validation result with zero blocking errors and creates idempotent historical records.

`POST /reconciliation/runs` accepts `scope` (`inventory`, `bookings`, `payments`, `waivers`, `ghl_projection`) and a date range. It returns a run ID.

`GET /reconciliation/runs/{id}` returns counts of matched, repaired, skipped, and exception records. Automatic repair is permitted only for deterministic, reversible projections; payment and refund mismatches must be marked for manual review.

## Data model additions

The next schema increment must add:

- `calendar_booking_policies` with immutable version rows.
- `booking_adjustments` for refunds, extra charges, reschedule differences, and manual review.
- `booking_custom_field_definitions` and `booking_custom_field_values`.
- `customers` with normalized email/phone identity and merge history.
- `customer_notes` and customer-level audit records.
- `migration_imports`, `migration_rows`, and mapping tables.
- `reconciliation_runs` and `reconciliation_exceptions`.
- `audit_log` with actor, tenant, action, entity, before/after JSON, and correlation ID.
- `weather_closure_events` for operator-approved closures and affected bookings.

## FareHarbor-style frontend requirements

The operator interface should use a compact operations workspace with a date navigator, calendar grid, color-coded availability, booking counts, capacity indicators, resource usage, staff assignment, and one-click booking actions. Booking details should open in a drawer with customer, participants, rate lines, resources, waiver, payment, policy, custom fields, notes, audit history, and synchronization state.

The public checkout should use a FareHarbor-like sequence: experience selection, date selection, time selection, customer type and quantity selection, participant/custom-field collection, waiver acceptance, order review, payment, and confirmation. Every step must preserve the cart and show explicit capacity, fees, taxes, cancellation terms, and required fields.

## GHL integration boundary

Passport emits the following projection jobs only:

- `ghl_sync_calendar` and `ghl_delete_calendar`.
- `ghl_upsert_contact` for appointment-associated customers.
- `ghl_sync_appointment` and `ghl_cancel_appointment`.
- `ghl_sync_staff_user` and staff availability reconciliation.

GHL is not permitted to determine Passport slot availability, price, inventory, cancellation eligibility, customer payment state, waiver state, or refund amount. Every projection includes a Passport ID marker and is recoverable by reconciliation.

## Production requirements

Before cutover, the operator must import future FareHarbor bookings, reconcile the next 90 days of inventory and bookings, configure every customer type and resource pool, verify Stripe Connect and refund behavior, publish cancellation and weather policies, complete a dual-run period, and define a rollback date. No live FareHarbor shutdown should occur until the reconciliation exception count is zero or explicitly accepted by the operator.
