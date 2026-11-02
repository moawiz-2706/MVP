# Passport — Production Readiness Plan

**Baseline commit:** `fa905897a37a8449169fd16651d242cd04192c60` (`main`, 2026-10-26), clean working tree.
**Live deployment:** Vercel production `https://mvp-one-hazel.vercel.app` is on the same commit.
**Live database:** Supabase project `quektyyqhzzyibozeyof`. It was inspected **read-only** through the Supabase MCP server. No production writes were made.
**Audit date:** 2026-11-02

## 1. Confirmed stack

| Layer | Technology | Where |
|---|---|---|
| Frontend | React + Vite + TypeScript, TanStack Query, FullCalendar, Stripe Payment Element, service-worker PWA | `frontend/` |
| Backend | FastAPI, SQLAlchemy 2, psycopg 3, Stripe SDK, httpx | `backend/` |
| Database | Supabase PostgreSQL. Forward-only SQL migrations `001`–`040` plus a `passport_schema_version` marker table | `supabase/migrations/` |
| Hosting | Vercel multi-service project: the frontend serves `/`, and FastAPI serves `/api/*` on the same origin | `vercel.json` |
| Background work | Postgres outbox (`outbox_jobs`) drained by three possible runners: `backend/worker.py` (long-running), `POST /api/v1/internal/process-outbox` (GitHub Actions every 5 minutes), and `GET /api/v1/internal/cron/daily` (Vercel cron, 11:00 UTC) | |
| Integrations | HighLevel Marketplace OAuth, contacts and appointments, staff directory, Conversations email. Stripe separate charges and transfers to an Express connected account | |

## 2. Baseline evidence (before any edits)

| Check | Result |
|---|---|
| `npm run typecheck` | pass |
| `npm run test:money`, `npm run test:booking-notifications` | pass |
| `npm run build` | pass (74 PWA shell assets precached) |
| `pytest` (backend) | **137 passed, 96 skipped, 2 errors**. The skips need `TEST_DATABASE_URL`. The 2 errors are DB tests missing the `requires_db` marker |
| DB-backed suite / migration chain on a disposable DB | **not run.** No local PostgreSQL or Docker is available on this machine |

## 3. Live-system findings (production, read-only inspection)

These outrank anything found in the code alone.

| # | Severity | Finding | Evidence |
|---|---|---|---|
| L1 | **P0** | **The 5-minute outbox runner has not run.** All of the last 100 GitHub Actions runs of `process-outbox.yml` failed with "account is locked due to a billing issue". Jobs are only drained by the daily Vercel cron, so customer confirmations, HighLevel sync, Stripe transfers, invoices and refunds can be delayed by up to about 24 hours. | `gh run list`; `outbox_jobs.updated_at` peaks at 11:02 UTC daily |
| L2 | **P0** | **Production database is behind the deployed code.** Migrations `038_pwa_workspace_performance` and `040_booking_adjustment_refunds` are not applied. The `outbox_jobs` check constraint does not allow `stripe_create_adjustment_refund`, so a paid booking quantity decrease (refund) fails at the database level in production. | `passport_schema_version`, `pg_constraint`, `pg_indexes` |
| L3 | **P0** | **Row Level Security is disabled on all 62 public tables.** Anyone with the project's anon key can use Supabase's Data API to read and write customers, waivers, payments, encrypted GHL tokens and sessions. The frontend does not use supabase-js, and the backend connects as the table owner, so enabling RLS with no policies blocks the Data API without affecting Passport. | Supabase security advisor |
| L4 | **P0** | **Production API is not running in production mode.** `/api/readiness` returns `schema_version: "development"`. As a result, production setting validation and DB readiness checks are skipped, and the PWA refresh cookie and OAuth state cookies are issued **without `Secure`**. | `curl /api/readiness`; `pwa_auth.py`, `ghl_oauth.py` |
| L5 | P1 | **Two `payment_intent.succeeded` webhooks failed** (2026-09-25 and 2026-09-30) with `'StripeWebhookService' object has no attribute 'settings'`, a since-fixed bug. They were never reprocessed (`attempt_count = 0`). One booking is still `pending_payment` and one is `cancelled`, although Stripe reported success. The money state needs reconciling. | `stripe_webhook_events` |
| L6 | P1 | **Abandoned card checkouts never resolve.** Five bookings are `pending_payment` with holds that expired weeks ago, and 7 payments are stuck at `processing`. `ReservationLifecycleService.expire_pending_holds` skips every hold whose payment is `processing`, and a card payment becomes `processing` as soon as the PaymentIntent is created. Capacity is **not** over-held, because availability ignores expired holds, but staff see stale "pending" bookings and the PaymentIntent stays payable. | `bookings`, `payments` |
| L7 | P2 | Three `ghl_sync_appointment` jobs are dead and two are retrying against a HighLevel calendar that was deleted in HighLevel. One reminder failed because `conversations/message.write` is not granted. | `outbox_jobs.last_error` |

## 4. Booking paths (as implemented)

All three paths converge on `OrderService.create_order` (`backend/app/services/order_service.py`), so locking, holds and pricing are shared.

1. **Public booking page:** `/book/{operator}/{calendar}`. The frontend calls `POST /api/v1/public/.../orders` with an `X-Checkout-Key` idempotency header. `OrderService` locks resources (`SELECT … FOR UPDATE`), re-validates availability, writes `booking_orders`, `bookings`, `booking_resources`, `booking_line_items`, `payments` and `payment_intent_requests`, and sets a hold of `BOOKING_HOLD_MINUTES` (10). It commits, then creates a Stripe PaymentIntent (status becomes `processing`). The Stripe webhook `payment_intent.succeeded` then confirms the booking and enqueues the transfer, GHL contact/appointment and confirmation-email jobs.
2. **Private staff booking link:** `/staff-book/...` with `X-Staff-Booking-Key`. The digest-only token resolves the staff member (`api/v1/staff_booking.py`), then follows the same `OrderService` path, recording the staff member.
3. **Staff-created booking (PWA and embedded desktop):** an authenticated session calls `api/v1/orders.py`. Payment modes are card, invoice (`stripe_create_invoice` outbox job) or none (free, confirmed immediately).

Holds expire through `expire_pending_holds`. It runs in `worker.py` and the daily cron, **not** on the 5-minute action. Late payments for expired holds are confirmed if capacity still fits; otherwise they are refunded automatically (`late-unavailable`).

## 5. Phases

Each phase follows the cycle in the brief: goal, implement, tests, full regression, diff review, then update `TODO.md`.

### Phase 1: Reliability and production foundations (complete; see TODO.md)
- Fix the 2 erroring tests (`requires_db`).
- Cookie `Secure` flag: set it whenever the site is served over HTTPS, not only when `ENVIRONMENT=production` (fixes L4's cookie exposure regardless of the env var).
- Readiness: report the environment, warn when a Vercel production deployment is not in production mode, and expand the required-table contract to every table runtime code needs.
- Migration `041_enable_rls.sql`: enable RLS on every public table (fixes L3). It is reversible.
- Runbook `docs/OPERATIONS_RUNBOOK.md`: scheduler options for L1, the migration apply and rollback order for L2–L3, and reconciliation steps for L5–L6.
- Verified on a local PostgreSQL 17.5: migration chain 001→042 and the full DB suite.

### Phase 2: Mobile departure calendar and slot operations (complete; see TODO.md)
`pwa_workspace_service.py`, `api/v1/pwa.py`, `frontend/src/pwa/*`. Slot list built from `availability_service` (configured, date-specific and pushed slots), with per-resource-type totals (no mixed units), held/booked/remaining, assigned staff, and a manifest link.

### Phase 3: Staff booking flow, availability and assignment (attribution built; see TODO.md)
`staffing_service.py`, `staff_service.py`, PWA booking wizard. Store `created_by` separately from `staff_assignments`.

### Phase 4: Payment, capacity and paid changes (abandoned checkouts built; see TODO.md)
`order_service.py`, `stripe_webhook_service.py`, `reservation_lifecycle_service.py`, `booking_adjustment_service.py`. Resolve L6 (abandoned-intent expiry with grace period plus a Stripe PaymentIntent cancel job, which needs a migration). Add concurrency tests for the last unit.

### Phase 5: Group manifest, waivers and check-in (manifest and check-in built; see TODO.md)
`waiver_service.py`, `booking_participants`. Add a per-participant check-in column (migration) and guardian links.

### Phase 6: Slot-wide weather closure (built; see TODO.md)
Extend `weather_closure_events` to a slot-level preview and confirm flow, with idempotent per-booking application.

### Phase 7: HighLevel Marketplace custom trigger (blocked; see TODO.md)
Needs verification in the actual HighLevel location. Versioned event outbox with 3 bounded attempts and manual retry.

### Phase 8: Booking attribution and commission ledger (attribution and report built; ledger needs rules)
New `commission_rules` and `commission_ledger` tables (migration). **Rules require client decisions.**

### Phase 9: Viator (blocked)
**Externally blocked:** no Viator sandbox or credentials.

## 6. Risks
- Every schema change is shared by the desktop and PWA, so the full suite must run against Postgres before any migration ships.
- Migrations are applied by hand in the Supabase SQL editor. There is no migration runner, and Supabase's `list_migrations` is empty. Order and marker discipline must be documented.
- Production currently holds real-looking data (20 bookings, 5 customers). Every production change requires explicit authorization.
