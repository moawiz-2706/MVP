# Passport TODO

Updated 2026-11-02. Baseline: `fa90589`. See `plan.md` for findings L1–L7 and the phase plan, and `docs/OPERATIONS_RUNBOOK.md` for procedures.

## Blockers needing the owner

- [x] **Disposable PostgreSQL for tests.** PostgreSQL 17.5 portable binaries in `D:\passport\pgdl`, data in `D:\passport\pgdata`, port 55432 (outside the repo).
- [ ] **L1: outbox runner is down** (GitHub billing lock). Decision: use the free Supabase scheduler. **Owner action:** run `supabase/manual_schedule_outbox_pg_cron.sql` in the Supabase SQL editor with the real `CRON_SECRET`.
- [x] **L2/L3: `038`, `040`, `041`, `042` applied to production** by the owner on 2026-11-02, via `supabase/manual_2026-11-02_production_apply.sql`. Verified read-only: the schema marker reaches `042`.
- [ ] **Apply `supabase/migrations/043_attribution_checkin_intent_cancel.sql` to production before deploying this branch.** The new code reads its columns on every booking query, and readiness requires marker `043`. It is additive, idempotent, and tested on a fresh 001→043 chain.
- [ ] **L4:** set `ENVIRONMENT=production` on the Vercel backend after the migrations. Authorized; needs the Vercel dashboard (no Vercel CLI access here). Check that every variable in `Settings.validate_runtime` is set first, or the API will refuse to start. To roll back, remove the variable and redeploy.
- [x] **L5:** the owner confirmed the two failed-webhook payments are test data. **Voided, not deleted** (Part B of the apply script): booking and order cancelled, payment `failed`, webhook rows annotated, HighLevel appointment cancellation queued. All rows are kept for audit.

## Phase 1: Reliability and production foundations, code complete and DB-verified locally

Done:
- [x] Marked the 2 DB tests in `test_private_staff_booking_links.py` as skip-without-DB (they errored before).
- [x] `Settings.secure_cookies`: the PWA refresh cookie, PWA OAuth state cookie and install OAuth state cookie are `Secure` on any HTTPS or Vercel-production deployment. Logout deletes the cookie with matching attributes.
- [x] `/api/readiness` reports `environment` and warns when a Vercel production deployment is not in production mode. In production mode it also warns about outbox jobs overdue by more than 15 minutes, and logs (but does not publish) a warning for tables without RLS. The required-table contract grew from 12 to 27 tables.
- [x] `POST /internal/process-outbox` expires abandoned holds before draining, so hold release no longer waits for the daily cron.
- [x] Migration `041_enable_row_level_security.sql` (reversible; rollback in header). **Not applied.**
- [x] `docs/OPERATIONS_RUNBOOK.md`.
- [x] Tests: secure-cookie matrix, env warning, RLS migration contract, process-outbox ordering.

Evidence:
- Migration chain `001`→`041` applies cleanly to a fresh PostgreSQL 17.5 database.
- The migrated schema matches production column-for-column (name, type, nullability) on all 62 tables. Compared by per-table fingerprint against the live DB, read-only.
- Backend with `TEST_DATABASE_URL` set: **239 passed, 0 skipped, 0 failed**. Without a DB: 141 passed, 98 skipped. The baseline was 137 passed, 96 skipped, 2 errors.
 Frontend typecheck, tests and build pass (unchanged). The readiness SQL was validated read-only against production: 62 unprotected tables, 2 overdue jobs.

Remaining:
- [ ] Tests build their schema from the SQLAlchemy models, not the migrations, so they miss migration-only objects such as `staff_assignments.assignment_range` (the overlap exclusion). Add a fixture that runs the real migration chain (needed in Phase 3).
- [ ] PWA close/reopen persistence on real iOS and Android devices (needs devices and the deployed app).
- [ ] Structured JSON logging with redaction (not started).

## Phase 2: Mobile departure board, complete and verified locally

Done:
- [x] `GET /api/v1/pwa/departures?date=YYYY-MM-DD[&calendar_id=]` (`DepartureBoardService`). It lists every departure an active calendar offers on that operator-local day, **including empty ones**, using the same candidate generation as public booking. Pushed calendars show only their exact pushed times; there are no artificial half-hour slots beyond what the calendar's own interval sells. Bookings at times no longer in the schedule appear as `unscheduled`.
- [x] Capacity is **per resource type** (Single Kayaks and Tandem Kayaks are never summed), with `total / confirmed / held / remaining`. It is computed across *all* calendars sharing the resource, and active holds are shown separately from confirmed bookings. Expired holds are not counted.
- [x] Each departure shows lead booker name, reference, units, booking status, staff-worded payment state ("Invoice unpaid", "Awaiting card", "Paid", "Free"), weather or closure blocks, and assigned staff. A staff member is attached to a departure their assignment starts at, or a shift that fully covers it, not to a neighbouring overlapping trip.
- [x] PWA screen `/app/departures`: day picker, filters (All, Booked, No bookings, Needs staff), auto-refresh every 60 s, tap-through to the booking. **Standalone PWA only:** a sidebar link and a bottom bar with New booking, Bookings and Departures. The embedded HighLevel desktop navigation is unchanged.
- [x] Booking drawer in the standalone PWA: the "FareHarbor-style rate line" section is hidden (underlying data untouched, embedded desktop unchanged), and the lead booker is labelled.
- [x] Role restrictions audited: every configuration, resource, calendar, Stripe and custom-field mutation enforces admin permission in the backend. Non-admins do not see admin links (UI) and get 403 (API).
- [x] **PWA sign-out bug fixed (found while testing).** Two refreshes racing with one cookie: the first rotated the nonce and the second got 401, which signed the staff member out. Reproduced in the browser (each pair was 200 + 401). The fix is a 30 s grace window for the replaced nonce: the racer gets an access token without a new cookie, a two-rotations-old cookie is still rejected, and revocation still wins. Migration `042_pwa_refresh_grace.sql`; schema marker bumped to `042`.

Evidence:
- 6 departure-board DB tests (empty departures, cross-calendar shared pool, unit types separate, holds, cancelled and expired, unscheduled, pushed, staff attachment, blocks, tenant isolation). 4 refresh-race DB tests.
- Backend with DB: **249 passed, 0 failed**. Without a DB: 141 passed, 108 skipped. Frontend typecheck, tests and build pass.
- Browser check on a 375 px viewport against seeded synthetic data: no horizontal overflow, numbers reconcile (for example, the 8:00 tour shows 10 singles booked: 4 own plus 6 from the overlapping rental), the refresh race now returns 200/200.
- Models vs migrations: `pwa_sessions` identical after `042`.

Remaining / notes:
- [ ] Branding colours: the PWA uses the existing teal accent. **Need the approved brand colours** to apply them.
- [ ] "Keep one Passport app/menu entry": the duplicate entry lives in the HighLevel Marketplace or custom-menu configuration, not in this repo. Needs a check in the HighLevel location before removing anything.
- [ ] New booking from a departure card does not yet pre-select that activity and time (Phase 3 booking flow).
- [ ] Live config issues seen in production (read-only): one active rate ("Single Kayak") has **no resource mapping**, so its capacity falls back to the per-booking maximum. "Tandem Kayak" counts 2 seats while "Tandem Kayak Rental" counts 1. Owner should confirm the intended values.
- [ ] Found in passing: `/me` returns 500 if a stored user email fails strict validation (for example a reserved domain), which would lock that user out. Low likelihood with HighLevel emails; fix by relaxing that response field.

## Phase 3: Staff booking, attribution and assignment, built in part

- [x] The booking's creator is stored separately from the trip staff: `booking_orders.created_by_user_id`, `created_by_staff_id` and `booking_source` (`public`, `staff_link`, `pwa`, `desktop`), set on all four paths. **Staff-link bookings previously recorded no staff member at all.** A signed-in user's staff record is found through their shared HighLevel user. An `X-Passport-Client` header tells the PWA and desktop apart; it is used for reporting only and grants nothing.
- [x] Multi-staff per departure, and no double-booking of one person: these already existed (DB exclusion constraint `staff_assignments_no_overlap`, row-lock serialisation tests). They are **now tested against the real migrated schema** (`tests/test_migrated_schema.py` with `TEST_MIGRATED_DATABASE_URL`).
- [x] The PWA booking detail shows "Created by".
- [ ] New booking from a departure card pre-selecting that activity and time, and the explicit close/return flow.
- [ ] **Decision needed:** must a departure have required staff before it can be sold?

## Phase 4: Payment and capacity, built in part

- [x] Abandoned card checkouts (finding L6): a card hold more than 30 minutes past expiry is released, and a `stripe_cancel_payment_intent` job cancels the PaymentIntent. It is idempotent, and does nothing if Stripe has already taken the money. A payment that still lands is refunded by the existing verified-webhook path. Invoice and paid orders are untouched.
- [x] Already covered by existing tests: last-unit concurrency (`test_spec154_18_row_lock_serializes_last_unit`), webhook idempotency, refund and adjustment ledgers.
- [ ] Stripe test-mode end-to-end runs (card, 3DS, failure, replay, paid increase and decrease). These need Stripe test keys on a staging deployment.

## Phase 5: Manifest and check-in, built in part

- [x] `GET /pwa/manifest` for one exact departure: lead booker with tap-to-call, parties, named attendees, minors with their guardian, payment state, waiver state, staff, and booked, named and checked-in totals. The PWA screen opens from each departure card.
- [x] Per-person check-in. It is idempotent: a double tap keeps the first timestamp and writes one audit event. It is undoable, with its own audit event, blocked on cancelled, failed or no-show bookings, and tenant-isolated. Stored as `checked_in_at` and `checked_in_by_user_id`.
- [ ] Per-attendee secure waiver links, guardian-signs-for-minor, required adult fields, and HighLevel attachment. **Need the client's waiver, retention and data-mapping decisions first.**

## Phase 6: Slot-wide weather closure, built

- [x] Admin-only preview of everything affected: bookings, guests, paid count, payment and waiver states, staff, and the calendar's configured refund policy as the default.
- [x] Admin-only confirm, recording the reason and actor:
  - A stale preview (the booking count changed in between) is refused.
  - New sales for the interval are **blocked** with a calendar block.
  - Each booking's cancellation and refund are keyed by closure and booking, so **a retry repeats no refund, message or block**.
  - One booking failing does not undo the others; failures are reported for retry.
- [x] The existing per-booking weather cancel in the desktop uses the same service, so it gains the sales block and retry safety. This is a shared safety fix.
- [ ] **Decision needed:** the refund rule per calendar (`full_refund`, `credit`, `manual_review` or `no_refund`). The current default is the calendar's policy, otherwise a full refund.

## Phase 7: HighLevel Marketplace custom trigger, **blocked**

- [ ] Needs verification in the client's HighLevel location that the approved custom trigger is installed and visible in the workflow builder, plus the Marketplace app's trigger contract. Not implemented: guessing the payload or endpoint, or substituting an inbound webhook, is excluded by the brief. Customer messages still use the existing Passport → HighLevel Conversations path.

## Phase 8: Attribution and commission, built in part

- [x] Admin-only report `GET /reports/bookings-by-creator`, plus a PWA Reports section: orders, confirmed, cancelled, sales and refunded per creator and channel. Non-admins get 403. **These are order totals, not commission.**
- [ ] Commission ledger and calculations. **Need the rules:** percentage or fixed, the base (gross, net, tax, fees), when it is earned, and how invoices, free bookings, partial refunds and cancellations are treated.

## Phase 9: Viator, **blocked**

- [ ] Needs Viator supplier eligibility, sandbox access, credentials and certification requirements. Nothing has been built.

## Also fixed in this round

- [x] **PWA sign-out after a lost refresh response** (app closed, or network dropped mid-refresh). The server had rotated the cookie, but the phone never received the new one and was signed out 30 seconds later. Reproduced locally. The replaced cookie now stays valid until its successor is used: within 30 seconds it is treated as a racing request, afterwards as a lost-response recovery. A cookie two rotations old is still rejected, and logout still revokes. Verified by surviving four aborted refreshes in the browser.

## Evidence (this round)

- Backend with the test DB and migrated-schema DB: **267 passed, 0 failed**. 18 tests are new: abandoned checkout (6), attribution (2), migrated schema (5), manifest and closure (5), plus the rewritten refresh-recovery test. Without a DB: 141 passed.
- A fresh 001→043 chain applies cleanly, and its columns match the models apart from the known migration-only objects.
- Frontend typecheck, tests and production build pass.
- Browser at 375 px against seeded synthetic data, with no horizontal overflow:
  - Manifest, check-in, undo and re-check-in.
  - Closure preview and confirm. The DB then showed 1 closure, 1 block, 2 weather cancels, 2 check-ins and 1 undo.
  - The creator report.

## Client decisions needed (from the brief)

- Capacity unit per activity (seats, kayaks or boats), and whether there are multiple resource types per departure.
- Whether a departure must have assigned staff before it can be sold.
- Refund rules for paid quantity decreases and weather closures.
- Waiver: required adult fields, guardian verification, retention period, and HighLevel attachment versus secure-link fallback.
- Commission: percentage or fixed, calculation base, earning time, treatment of invoices, free bookings and refunds.
- Customer message copy, timing and consent (two emails and two SMS).
- Late payment for an expired hold: confirm if capacity fits (current behavior) or always refund.
