# Database-First Plan: Immediate GHL Booking Sync and GHL-Owned Messaging

**Repository:** `/home/ubuntu/MVP`  
**Status:** Phased implementation in progress — database foundation, synchronous sync service, notifications, and frontend recovery are implemented and tested; production database/provider validation remains  
**Source reviewed:** current repository plus the attached schema dump

> Implementation was approved on 2026-10-08 and is being delivered in tested slices. The live database migration and provider-backed verification must still be completed before production rollout.

---

## 1. Objective

Change the booking integration so that:

1. Passport remains the authoritative booking and payment database.
2. A completed Passport booking synchronizes to HighLevel immediately after the local transaction commits.
3. Passport performs at most three immediate GHL attempts.
4. A final failure is visible to the operator with a clear error and a **Resync to GHL** action.
5. GHL workflows own customer email, SMS, confirmation, waiver reminders, and booking reminders.
6. Passport does not use `outbox_jobs` or cron for the primary GHL appointment/contact synchronization path.
7. Stripe financial operations continue to use durable asynchronous processing where required.

The safe target architecture is:

```text
Passport transaction commits
        ↓
Create durable GHL sync-run record
        ↓
Immediate synchronous GHL sync
        ↓
Contact upsert
        ↓
Appointment create/update
        ↓
Three short retries on retryable failure
        ↓
Mark success or failure
        ↓
Show failure notification with manual resync
```

The local booking must not be rolled back because GHL is unavailable.

---

## 2. Important decision: do not remove the entire outbox system

The request is to stop using cron/outbox for **GHL booking synchronization**. It should not mean dropping `outbox_jobs` from the database.

The existing outbox is still needed for high-risk financial and provider operations, including:

- Stripe transfers
- Stripe refunds
- Stripe transfer reversals
- Hosted Stripe invoices
- PaymentIntent reconciliation
- Some GHL calendar projection/deletion operations unless those are also deliberately converted

### Recommendation

Initially:

- Keep the `outbox_jobs` table.
- Keep Stripe-related job types.
- Keep existing async financial recovery behavior.
- Stop creating `ghl_upsert_contact`, `ghl_sync_appointment`, and GHL confirmation-message jobs for the new booking path.
- Do not remove old GHL job types in the first migration. Leave them available while existing records drain and while the new path is verified.

Only after production verification should a later cleanup migration remove obsolete GHL job types from the check constraint.

---

## 3. Schema audit of the attached dump

The attached dump is explicitly marked as context-only and not executable. It should be treated as a schema snapshot, not as a migration file.

### What matches

The dump contains the same major tables represented by the current SQLAlchemy model, including:

- Operators, users, operator settings
- Calendars, availability, resources, rates
- Customers, booking orders, bookings, participants
- Payments, Stripe connections, transfers, webhook events
- Waivers, notes, booking events, financial adjustments
- GHL installations, calendar mappings, appointment mappings
- Public credentials and rate-limit buckets
- Staff, assignments, availability windows
- Migration and reconciliation tables
- Message templates

The only table present in the dump but not represented as a SQLAlchemy entity is `passport_schema_version`. That is expected because it is used by readiness/migration tracking rather than application ORM operations.

### Schema drift found: waiver token digest

The attached dump has:

```text
booking_waivers.token_digest
```

The repository migrations also add this column in migrations `008`/`021`, but the current SQLAlchemy `BookingWaiver` model and `WaiverService` still use the raw `booking_waivers.token` column for lookup.

Current behavior:

```text
URL token → WHERE booking_waivers.token = supplied_token
```

The public/staff credential system already uses digests, but waiver links do not consistently use the digest column.

### Required pre-implementation decision

Before implementing GHL sync, choose one of these:

#### Recommended: complete the digest migration

- Add `token_digest` to the ORM model.
- Backfill it as a SHA-256 digest of the existing raw token.
- Dual-read during a short compatibility period.
- New waiver links write both the raw compatibility value and digest initially.
- Move lookup to digest-only.
- Decide whether the raw token should remain encrypted for link reconstruction or be removed after a controlled compatibility period.
- Keep signed waiver rows immutable.

#### Lower-risk short-term option

- Add `token_digest` to the ORM model.
- Backfill and maintain it for new rows.
- Continue raw-token lookup temporarily.
- Create a later security migration to remove raw lookup/storage.

The first option is more secure; the second has less immediate application impact.

---

## 4. Proposed database changes

### 4.1 Add a durable GHL sync-run table

Because the new design does not rely on an outbox for GHL booking synchronization, the database needs a durable record of each synchronous sync operation.

Proposed table: `ghl_sync_runs`

| Column | Purpose |
|---|---|
| `id` | UUID primary key |
| `operator_id` | Tenant ownership |
| `booking_order_id` | Order being synchronized; nullable for calendar-only operations |
| `trigger_type` | `booking_created`, `payment_confirmed`, `waiver_updated`, `booking_updated`, `cancelled`, `manual_resync` |
| `status` | `running`, `succeeded`, `partial`, `failed`, `manual_review` |
| `max_attempts` | Default `3` |
| `attempt_count` | Number of attempts made |
| `last_error_code` | Normalized error category |
| `last_error` | Human-readable diagnostic, capped in length |
| `last_http_status` | Provider status where available |
| `started_at` | Start timestamp |
| `completed_at` | End timestamp |
| `resolved_at` | When a failed sync was later fixed |
| `requested_by_user_id` | Operator user for manual resync; nullable for system trigger |
| `created_at`, `updated_at` | Audit timestamps |

Recommended constraints:

- `max_attempts BETWEEN 1 AND 3` for the immediate-sync path.
- `attempt_count >= 0`.
- `status` check constraint.
- Tenant-scoped indexes on `(operator_id, status, created_at)`.
- Booking-order index on `(booking_order_id, created_at DESC)`.
- A partial unique index for only one active manual/system run per booking order if required.

This table is **not a queue**. It is an audit, state, and recovery record for a synchronous operation.

### 4.2 Add a GHL sync-attempt table

Proposed table: `ghl_sync_attempts`

One row should be created for every provider attempt, including successful attempts.

| Column | Purpose |
|---|---|
| `id` | UUID primary key |
| `run_id` | Parent sync run |
| `operator_id` | Tenant ownership |
| `booking_order_id` | Order context |
| `booking_id` | Specific appointment context; nullable for contact-only work |
| `entity_type` | `contact`, `appointment`, `calendar`, `custom_fields` |
| `operation` | `upsert`, `create`, `update`, `cancel`, `reconcile` |
| `attempt_number` | 1, 2, or 3 |
| `status` | `started`, `succeeded`, `failed`, `unknown`, `manual_review` |
| `provider_http_status` | HTTP status if available |
| `error_code` | Normalized Passport/provider code |
| `error_message` | Capped diagnostic text |
| `payload_hash` | Hash of the sent logical payload |
| `remote_id` | GHL contact/event ID if known |
| `started_at`, `completed_at` | Timing/audit |

Recommended indexes:

```text
(run_id, attempt_number)
(operator_id, status, created_at DESC)
(booking_id, entity_type, created_at DESC)
```

Do not store full request payloads by default because they contain customer PII. Store a hash and the normalized error. If full payload retention is required for debugging, use a controlled retention policy and encrypt or redact it.

### 4.3 Extend GHL calendar and appointment mappings

The existing tables are the correct relationship model:

```text
operators 1──N calendars
calendars 1──1 operator GHL calendar mapping
bookings  1──1 GHL appointment mapping
```

Keep the current mappings and add operational fields:

```text
last_attempt_at
last_synced_at
sync_attempt_count
last_error_code
last_http_status
last_sync_trigger
```

The current fields should remain authoritative for remote identity and payload reconciliation:

- `ghl_event_id`
- `desired_revision`
- `applied_revision`
- `status`
- `payload_hash`
- `last_error`

Do not create a separate `ghl_booking` table unless the product later needs a full local mirror of the GHL appointment. The existing mapping is sufficient.

### 4.4 Make customer GHL identity canonical

The current schema has GHL contact IDs in both:

- `customers.ghl_contact_id`
- `booking_orders.ghl_contact_id`

This creates a risk of conflicting identifiers.

Recommended model:

- `customers.ghl_contact_id` becomes the canonical customer-level GHL contact ID.
- Add customer-level sync fields:
  - `ghl_contact_sync_status`
  - `ghl_contact_sync_attempt_count`
  - `ghl_contact_last_synced_at`
  - `ghl_contact_last_error`
  - `ghl_contact_payload_hash`
- Keep `booking_orders.ghl_contact_id` temporarily as a historical/snapshot field for compatibility.
- Backfill it from `customers.ghl_contact_id` where possible.
- Update the service to use the customer record first.
- Deprecate order-level contact identity only after all existing code paths are migrated.

Do not make `booking_orders.customer_id` non-null in the same change without first auditing historical rows. If every production order is guaranteed to have a customer, make it non-null in a separate validated migration.

### 4.5 Add GHL custom-field mapping metadata

GHL custom-field IDs are location-specific. They should not be hardcoded in application code.

Proposed table: `ghl_custom_field_mappings`

| Column | Purpose |
|---|---|
| `id` | UUID primary key |
| `operator_id` | GHL location/tenant ownership |
| `object_type` | `contact` for the current public API; appointment reserved for a future supported endpoint |
| `passport_key` | Stable local key, e.g. `passport_waiver_url` |
| `ghl_field_id` | Actual GHL custom-field ID |
| `ghl_field_name` | Human-readable provider name |
| `data_type` | `text`, `number`, `date_time`, `boolean`, `url` |
| `enabled` | Whether Passport should populate it |
| `last_verified_at` | Last successful provider validation |
| `last_error` | Mapping error |
| timestamps | Audit |

Constraints:

```text
UNIQUE(operator_id, object_type, passport_key)
UNIQUE(operator_id, object_type, ghl_field_id)
```

### 4.6 Recommended custom fields

#### Standard appointment fields and description — booking-specific values

The official HighLevel v3 create/update appointment schemas do not expose an appointment `customFields` property. Passport therefore sends booking-specific correlation data through standard appointment fields and the description:

```text
passport_booking_id
passport_booking_reference
passport_booking_status
passport_payment_status
passport_service_name
passport_calendar_id
passport_operator_id
passport_quantity
passport_customer_type
passport_total
passport_currency
passport_start_at
passport_end_at
passport_location_name
passport_location_address
passport_staff_names
passport_waiver_url
passport_waiver_status
passport_waiver_expires_at
```

#### Contact custom fields — workflow values supported by the current API

```text
passport_customer_id
passport_marketing_opt_in
passport_last_booking_reference
passport_last_booking_date
passport_last_booking_status
passport_latest_waiver_url
```

Do not send these sensitive waiver values to GHL:

- Signature PNG
- Date of birth
- Full home address
- Emergency contact data
- Internal operational notes
- Full waiver text unless there is an explicit legal/business reason

The waiver URL and status are sufficient for GHL workflows.

### 4.7 Do not add a duplicate waiver-link column to bookings

The authoritative waiver data already exists in `booking_waivers`:

- Token/link source
- Status
- Expiry
- Signed timestamp
- Snapshot

The GHL sync payload should join the booking to `booking_waivers` and populate the remote custom fields. Do not add `waiver_url` as a second authoritative column on `bookings` or `booking_orders`.

A derived/cache field such as `last_ghl_waiver_payload_hash` is acceptable if needed for synchronization diagnostics, but it must not replace `booking_waivers`.

---

## 5. ERD relationship corrections/recommendations

The ERD should show the following clearly:

```text
Operator
 ├── GHLInstallation
 ├── OperatorSettings
 ├── Customers
 │    └── BookingOrders
 │         ├── Payments
 │         └── Bookings
 │              ├── BookingWaiver
 │              ├── BookingParticipants
 │              ├── BookingLineItem
 │              └── GHLAppointmentMapping
 ├── Calendars
 │    └── GHLCalendarMapping
 ├── GHLCustomFieldMappings
 └── GHLSyncRuns
      └── GHLSyncAttempts
```

The ERD should also identify these as separate concerns:

- `booking_orders` = customer/order/payment aggregate
- `bookings` = one scheduled activity per order item
- `payments` = one payment aggregate per order
- `booking_adjustments` = immutable financial outcome records
- `ghl_*_mappings` = remote identity and projection state
- `ghl_sync_*` = operational execution/audit state
- `booking_waivers` = legal snapshot, not messaging state

### Tenant integrity

Existing application code consistently filters by `operator_id`, but many tables use separate foreign keys without composite tenant-enforcement constraints. For the new tables, enforce tenant consistency using one of:

1. Composite foreign keys with `(operator_id, id)` parent keys, or
2. PostgreSQL triggers like the existing booking-child tenant trigger.

At minimum, new GHL sync tables must not allow a run for operator A to reference an order, booking, calendar mapping, or customer belonging to operator B.

Do not attempt a broad tenant-integrity rewrite in the same first migration. Harden the new tables first, then handle legacy tables in a separate project.

---

## 6. Migration sequence

Do not edit old migrations in place. Create new forward-only migrations.

### Migration A — schema reconciliation

Proposed next migration number: `035_schema_reconciliation.sql`

Scope:

- Add missing ORM/model alignment for `booking_waivers.token_digest`.
- Decide and implement the waiver digest compatibility path.
- Inspect and validate all `NOT VALID` constraints from migrations `021`, `032`, and `034`.
- Add missing indexes identified by actual query plans.
- Add any missing uniqueness constraints only after duplicate-data checks.
- Ensure migration version tracking records the migration.

Before validating any constraint:

```sql
SELECT conrelid::regclass, conname
FROM pg_constraint
WHERE NOT convalidated;
```

For each constraint, first run a data-quality query, repair or quarantine bad rows, then run `VALIDATE CONSTRAINT`.

### Migration B — synchronous sync state

Proposed: `036_ghl_sync_state.sql`

Scope:

- Create `ghl_sync_runs`.
- Create `ghl_sync_attempts`.
- Add sync diagnostic fields to appointment/calendar mappings.
- Add customer-level contact synchronization fields.
- Add indexes and tenant constraints.

### Migration C — GHL custom-field mappings

Proposed: `037_ghl_custom_field_mappings.sql`

Scope:

- Create `ghl_custom_field_mappings`.
- Add object type/data type checks.
- Add tenant/location-scoped uniqueness.
- Seed only Passport keys, not provider IDs, because provider field IDs must be configured per GHL location.

### Migration D — safe backfill

Proposed: `038_ghl_sync_backfill.sql`

Scope:

- Backfill canonical customer GHL IDs where safely possible.
- Backfill mapping sync status from existing rows.
- Create failed-sync visibility for existing `failed`/`manual_review` mappings.
- Do not automatically call GHL during the migration.

### Migration E — optional cleanup later

Only after the new path is stable:

- Remove obsolete GHL booking job types from the `outbox_jobs` check constraint.
- Remove deprecated duplicate order-level contact ID only after code and data migration.
- Remove legacy raw waiver token lookup only after all existing links are safely handled.

---

## 7. Application implementation phases after database approval

### Phase 1 — database verification

- Apply all existing migrations `001` through `034` to a disposable PostgreSQL database.
- Compare the resulting database schema with the attached dump.
- Resolve the waiver `token_digest` drift.
- Validate all `NOT VALID` constraints.
- Generate a clean ERD from the actual live schema.
- Run the database-backed test suite.

### Phase 2 — GHL sync service

Create one orchestration service responsible for:

```text
sync_order_to_ghl(order_id, trigger_type, requested_by)
```

It should:

1. Create a sync run.
2. Commit the run before network calls.
3. Sync the canonical contact.
4. Sync each booking appointment.
5. Populate mapped custom fields.
6. Use the existing remote-event recovery search before retrying a timed-out create.
7. Retry only retryable errors.
8. Stop after three attempts.
9. Mark success, partial, failed, or manual review.
10. Never roll back the Passport booking because GHL fails.

### Phase 3 — booking lifecycle integration

Trigger direct GHL synchronization after the local transaction commits for:

- Free booking creation
- Initial paid/card booking creation
- Invoice booking creation
- Verified card payment success
- Verified invoice payment
- Booking reschedule
- Booking cancellation
- Weather cancellation
- Staff assignment changes if GHL appointment ownership/details must change
- Waiver signing

For card/invoice bookings, create the GHL appointment with a pending/new status, then update it to confirmed only after verified payment.

### Phase 4 — notifications and resync

- Derive an actionable notification from failed/partial `ghl_sync_runs`.
- Display the booking/order, operation, attempt count, last error, and timestamp.
- Add **Resync to GHL**.
- Manual resync creates a new run rather than mutating historical attempts.
- On success, mark the previous failure resolved.
- Make resync idempotent and safe to click multiple times.

A separate generic notifications table is not required for the first version if the UI can derive current failures from `ghl_sync_runs`. Add a generic notification table later only if users need unread/read, dismissal, assignment, or notification history.

### Phase 5 — GHL workflow handoff

Configure Passport to populate appointment-level fields and let GHL workflows own:

- Confirmation email
- Confirmation SMS
- Waiver reminder
- Day-before reminder
- Same-day reminder
- Cancellation message
- Reschedule message

Passport should disable its own message delivery after the GHL workflow is verified, but it should continue updating booking/appointment state.

### Phase 6 — production rollout

Use a feature flag per operator:

```text
GHL_SYNC_MODE = outbox | synchronous | disabled
```

Recommended rollout:

1. Existing outbox mode remains default.
2. Enable synchronous mode for one staging operator.
3. Verify success, timeout, duplicate recovery, manual resync, payment-state gating, waiver updates, and cancellations.
4. Enable for one production operator.
5. Monitor failed/partial/manual-review sync runs.
6. Expand gradually.
7. Remove the old GHL booking outbox path only after all operators are migrated.

---

## 8. Database tests required before production

### Migration tests

- Fresh database applying migrations `001`–`038`.
- Existing production-like database applying migrations `035`–`038`.
- Migration replay/idempotency where intended.
- Schema dump comparison.
- All constraints validated.
- No orphaned mappings.
- No cross-tenant references.

### Sync tests

1. Contact and appointment sync succeeds on first attempt.
2. Timeout succeeds on second attempt.
3. Three retryable failures produce one failed run and one actionable notification.
4. Permanent 400/401/403 produces an actionable error without pointless retries.
5. GHL create succeeds but response is lost; reconciliation finds the remote event and prevents a duplicate.
6. Contact succeeds but appointment fails; run is marked partial/failed correctly.
7. Manual resync retries only the failed/missing component and is idempotent.
8. Multiple bookings in one order each receive the correct appointment mapping.
9. Waiver URL is absent for pending payment and present after confirmation.
10. Waiver signing updates only the correct appointment custom fields.
11. Reschedule updates the existing remote appointment rather than creating a duplicate.
12. Cancellation updates the existing remote appointment.
13. Cross-tenant access is rejected.
14. PII is not written into GHL custom fields beyond the approved contract.
15. Existing Stripe outbox operations continue to work.

---

## 9. Recommended decisions

| Decision | Recommendation |
|---|---|
| Remove all outbox jobs? | No. Remove only GHL booking sync from the primary path; retain financial outbox jobs. |
| Sync before or after DB commit? | After commit. Never hold a DB transaction open across GHL calls. |
| Retry count | Three immediate attempts, with short exponential delays. |
| Booking failure when GHL fails? | No. Passport booking remains valid; show sync failure. |
| Retry persistence | `ghl_sync_runs` + `ghl_sync_attempts`, not a queue. |
| GHL field location | Appointment-level for booking data; contact-level only for customer/latest-booking convenience. |
| Waiver link source | `booking_waivers`; do not duplicate as authoritative booking text. |
| Waiver sensitive data in GHL | Do not send signature, DOB, address, emergency contact, or full waiver snapshot. |
| Notification persistence | Derive current actionable errors from sync runs first; add generic notification table only if needed later. |
| Customer GHL ID | Make `customers.ghl_contact_id` canonical; deprecate order duplication gradually. |
| Feature rollout | Per-operator `outbox`/`synchronous`/`disabled` mode. |
| ERD authority | Actual PostgreSQL schema plus forward migrations, not the context-only dump. |

---

## 10. Implementation checkpoint

The following slices are now implemented and locally tested:

1. Waiver token-digest model/service alignment and migration `035`.
2. Durable GHL sync runs, attempts, mapping diagnostics, customer sync state, and custom-field mapping schema in migration `036`.
3. Feature-flagged synchronous GHL order synchronization with three bounded attempts.
4. Post-commit Stripe payment webhook synchronization and protected manual resync endpoint.
5. Contact custom-field payloads, waiver URL/status propagation, appointment description correlation, and GHL workflow notification behavior.
6. Derived operator failure notifications and frontend **Resync to GHL** action.

The remaining database gate, which must be completed before production rollout, is:

1. Establish a disposable PostgreSQL database.
2. Apply migrations `001`–`034`.
3. Compare the real schema to the attached dump and ORM.
4. Resolve `booking_waivers.token_digest` drift.
5. Validate all `NOT VALID` constraints and repair any existing bad rows.
6. Apply migrations `035` and `036` and run database-backed tests.
7. Configure and verify location-specific GHL contact custom-field mappings.
8. Run provider-backed integration tests and staged rollout.

Only after that database gate passes should the synchronous GHL integration be implemented.
