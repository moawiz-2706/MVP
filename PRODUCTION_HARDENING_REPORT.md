# Passport MVP — Production Hardening Implementation Report

**Repository:** `moawiz-2706/MVP`  
**Implementation workspace:** `/home/ubuntu/audit_MVP`  
**Scope:** release safety, OAuth CSRF protection, database readiness, booking lifecycle centralization, financial adjustment auditability, account-level message customization, frontend contract alignment, and verification.

## Executive result

The hardening work is implemented and verified against a real local PostgreSQL 16 instance.

- The complete migration chain applies cleanly through `030_message_templates`.
- The production readiness probe returns `{"status":"ready","schema_version":"030_message_templates"}` on a freshly migrated database.
- The complete backend PostgreSQL-backed test suite passes.
- New lifecycle and release-gate tests pass.
- Frontend typecheck, booking-notification tests, and production build pass.
- `git diff --check` and conflict-marker scans pass after excluding dependency/build directories.

## Implemented controls

### Phase 0 — release safety

- Production runtime validation now requires `DATABASE_URL`, `API_URL`, `FRONTEND_URL`, GHL credentials, Stripe secret/webhook/publishable keys, and `CRON_SECRET`.
- Production rejects localhost/loopback database and application URLs.
- Added `/api/readiness`, separate from liveness `/api/health`.
- Production startup validates configuration and database readiness before serving.
- Readiness checks connectivity, required operational tables, and the schema marker for migration `030`.
- OAuth callback `state` is mandatory, must match the HttpOnly browser cookie, is consumed once, and the browser cookie is cleared on both success and failure redirects.
- Added `API_URL` to `backend/.env.example`.

### Phase 1 — centralized booking lifecycle

Added three services:

- `PolicyService`: resolves the policy version captured on the booking, rather than silently using current calendar defaults.
- `AdjustmentService`: creates idempotent append-only refund, credit, manual-review, retained-fee, no-show, and transfer-reversal outcomes. Refunds enqueue durable Stripe outbox jobs; credits are non-zero ledger entries.
- `BookingLifecycleService`: owns cancellation, weather cancellation, status transitions, no-show handling, policy cutoffs, rescheduling, events, public-link revocation, and GHL cancellation outbox records.

Routed through the lifecycle service:

- Admin cancellation and rescheduling.
- Public cancellation and rescheduling.
- Admin status changes.
- Weather closures.

Financial audit fields added to `booking_adjustments`:

- `original_amount_minor`
- `policy_version`
- `stripe_reference`

### Frontend alignment

- Operator weather closure UI now selects full refund, operator credit, manual review, or no refund instead of hardcoding full refund.
- No-show controls are disabled for unpaid pending bookings.
- Public reschedule UI consumes explicit `payment_outcome` values and explains when a refund is being processed.

### Account-level message customization

- Added `message_templates`, scoped by `operator_id`, with safe subject/body merge-field validation and reset-to-default behavior.
- Added `GET`, `PUT`, `DELETE`, and preview endpoints under `/api/v1/settings/messages` protected by the existing view/manage-configuration permissions.
- Added Settings → Messages with per-event enable switches, subject/body editors, merge-field insertion, preview, save, and restore-default controls.
- Confirmation, customer reminders, staff assignment/removal/reminders, customer cancellation, weather cancellation, and reschedule messages now resolve the account template at delivery time.
- Cancellation, weather-cancellation, and reschedule notifications are durable outbox jobs with idempotency keys and existing retry/lease behavior.
- HTML output is generated from escaped plain text; waiver links are rendered as safe links, preventing account-authored content from becoming executable markup.

### Compatibility fixes discovered by the real DB gate

- Preserved direct-call compatibility for public catalog/status handlers while retaining HTTP cache/security headers.
- Restored signed-waiver detail snapshots in the response.
- Made inline staff outbox processing use caller settings deterministically.
- Corrected unsynced staff-hours fallback to use the operator timezone.
- Aligned the staff-pool regression test with migration `027`, which intentionally removed the staff booking gate.

## Conservative behavior

A paid reschedule that increases the amount is rejected with **“Additional payment is required before this reschedule”** rather than moving the booking and leaving an uncollected balance. The existing public payment flow has no adjustment-payment confirmation endpoint, so silent under-collection was intentionally not introduced. Price decreases produce an idempotent refund adjustment and Stripe refund outbox job.

## Verification commands

```bash
# Backend
TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/passport_audit' \
  /home/ubuntu/audit-venv/bin/python -m pytest -q

# Focused new tests
TEST_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/passport_audit' \
  /home/ubuntu/audit-venv/bin/python -m pytest -q \
  tests/test_release_hardening.py tests/test_lifecycle_hardening.py

# Frontend
npm ci
npm run typecheck
npm run test:booking-notifications
npm run build
```

## Deployment notes

1. Apply migrations `028_release_readiness.sql`, `029_booking_adjustment_audit_fields.sql`, and `030_message_templates.sql` before deploying the hardened backend.
2. Set `API_URL` to the externally reachable API origin and keep `FRONTEND_URL` on the externally reachable frontend origin.
3. Do not deploy production with localhost/loopback database or application URLs.
4. Configure the worker/outbox process so Stripe refund and transfer-reversal jobs are continuously drained.
5. Treat the readiness probe as the deployment health gate; `/api/health` only proves process liveness.
