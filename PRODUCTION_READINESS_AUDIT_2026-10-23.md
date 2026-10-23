# Passport Production-Readiness Audit

**Repository:** `moawiz-2706/MVP`
**Audit workspace:** `/home/ubuntu/MVP_20261023`
**Audited revision:** `8747919` — `Implement mobile-first PWA workspace`
**Audit date:** 2026-10-23
**Scope:** Staff PWA, HighLevel authentication and synchronization, Stripe payments and Connect, background jobs, database readiness, deployment, performance, security, and production launch blockers.

## Executive verdict

The codebase is structurally strong and the local frontend/backend checks pass, but I would **not start live production bookings yet**. The main risk is not a missing React page or a basic Stripe API call. It is the production execution model:

1. The application depends on an always-on worker for GHL synchronization, Stripe transfers/refunds/invoices, hold expiry, staff reconciliation, and reminders, but the repository is configured to deploy the API on Vercel and Vercel Hobby cron runs only once per day.
2. The Stripe webhook currently processes the event and then runs up to 100 outbox jobs synchronously before returning. Stripe officially recommends returning a 2xx response before complex work and processing asynchronously.
3. The standalone PWA stores a long-lived bearer JWT in browser storage, has a no-op logout route, and has no per-device session revocation. This is not ideal for staff phones.
4. The PWA and embedded GHL experience share the same frontend route tree. A top-level browser is classified as standalone PWA simply because `window.parent === window`, and `/app` always opens the Passport Home dashboard. There is no strict mobile-only gate or separate browser/PWA entry policy.
5. Database integration tests were not run in this audit because no disposable PostgreSQL database was supplied. The passing unit suite does not prove that the full migration chain, Supabase pooler behavior, Stripe webhooks, GHL OAuth, or live provider contracts work in production.

**Recommended launch status: `blocked pending P0 fixes and a staging smoke test`.**

## Verification performed

### Frontend

The following completed successfully from `frontend/`:

- `npm run typecheck`
- `npm run test:booking-notifications`
- `npm run test:money`
- `npm run build`

The production build completed and generated the SPA fallback. Code splitting is working: the initial shell is smaller and heavy booking/calendar screens are loaded as route chunks.

`npm audit --omit=dev --audit-level=high` reported **0 vulnerabilities** for the installed frontend dependency tree.

### Backend

The following completed successfully from `backend/`:

- Python compilation with `python3 -m compileall -q app`
- Non-database regression suite with `TEST_DATABASE_URL=''`
- JUnit totals: **216 collected, 131 passed, 85 skipped, 0 failed, 0 errors**
- `git diff --check` was clean before validation artifacts were generated

The 85 skipped tests are mostly PostgreSQL integration tests covering availability, lifecycle, staff, reminders, invoices, public pages, and related database behavior. Therefore the result is a **unit/contract baseline**, not a complete production verification.

`pip-audit` was not installed in the audit environment, so the backend dependency vulnerability scan remains outstanding. Backend requirements use open lower-bounded ranges such as `fastapi>=0.116,<1`, which is convenient for development but does not give reproducible production builds.

## Current architecture in simple terms

- Passport owns the authoritative PostgreSQL data: calendars, resources, availability, bookings, waivers, customers, staff assignments, payment state, and audit data.
- HighLevel owns the installation identity and is used for contacts, calendars/appointments, and staff directory synchronization.
- Stripe owns card collection, invoices, charges, refunds, connected-account onboarding, and provider-side payment state.
- Vercel hosts request-driven frontend/API functions.
- `backend/worker.py` is a separate long-running process intended to run every 10–60 seconds. It synchronizes GHL staff, expires payment holds, and processes the durable outbox.
- `vercel.json` also defines one daily Vercel cron at `GET /api/v1/internal/cron/daily`.

This is a good separation of data ownership, but the worker is operationally mandatory for timely external side effects.

## PWA audit

### What already works

The repository already contains:

- A Vite/React PWA manifest with standalone display mode, icons, theme color, and `/app` start URL.
- Apple mobile web-app metadata in `frontend/index.html`.
- A service worker that does not cache `/api/` responses.
- Network-first navigation with an offline HTML fallback.
- Route-level code splitting for bookings, calendars, reports, settings, customers, staff, and other pages.
- A responsive sidebar and phone-oriented cards/agenda views.
- A dedicated standalone OAuth handoff: HighLevel redirects to the backend, the backend creates a one-time handoff code, and the PWA exchanges that code for a Passport session without placing the JWT in the URL.
- A 31-day standalone session lifetime controlled by `PWA_SESSION_MINUTES`.
- Backend checks on every request for operator, installation, membership, active status, and installation authorization version.

### Remaining PWA problems

#### P0/P1 — Long-lived JWT in localStorage

`frontend/src/auth/GHLSessionProvider.tsx` stores the 31-day Passport bearer token in `localStorage` and also in `sessionStorage`. Any XSS or compromised third-party script running on the frontend origin can read the token and use it until it expires or the installation authorization version is rotated.

**Fix:** move to a short-lived in-memory access token plus a Secure, HttpOnly, SameSite refresh cookie. Add CSRF protection for cookie-authenticated mutations. If the current bearer design must remain temporarily, reduce the PWA access-token lifetime substantially and add strong CSP, dependency pinning, and a real logout/revocation mechanism.

#### P1 — Logout is not implemented

`POST /api/v1/pwa-auth/logout` returns 204 but does nothing. The shared shell does not expose a clear Staff PWA sign-out action. A staff member using a shared phone cannot reliably end their own session.

**Fix:** add a session record or per-user/session version, revoke the current device session on logout, clear the browser token, and add a visible “Sign out” action. Keep installation-level authorization rotation for emergency tenant-wide revocation.

#### P1 — PWA login and embedded installation use one redirect setting

Both `backend/app/api/v1/pwa_auth.py` and `backend/app/api/v1/ghl_oauth.py` use `settings.ghl_oauth_redirect_uri`. That value is also used by the embedded Marketplace installation flow. This is fragile because the standalone PWA and the embedded GHL installation are two different browser contexts and may require different approved redirect URLs.

**Fix:** add separate settings, for example:

- `GHL_INSTALL_OAUTH_REDIRECT_URI`
- `PWA_OAUTH_REDIRECT_URI`

Register both exact HTTPS URLs in the HighLevel app, use the correct value in each flow, and keep the state cookie/path scoped to the correct flow. This directly addresses the previously observed “login succeeds in HighLevel but does not return to Passport” class of problem.

#### P1 — The current route tree does not enforce “mobile PWA only”

`frontend/src/main.tsx` sends `/` to `/app`, and `/app` always renders the Passport shell and Home dashboard. `GHLSessionProvider.isStandalonePwa()` treats every top-level browser tab as standalone because `window.parent === window`. That means a desktop browser can open the PWA shell and the PWA login screen, even though the requested experience is intended for mobile staff use.

**Fix options:**

1. Keep one responsive web application and accept desktop access; this is the simplest and safest option.
2. Add explicit modes: embedded GHL mode, standalone PWA mode, and optional desktop browser mode. Detect PWA using `display-mode: standalone`/iOS standalone plus an explicit `/app` entry, not only `window.parent === window`.
3. If desktop browser access must be blocked, show a clear “Open this link on a staff phone” page rather than silently loading the same application.

Do not rely on user-agent checks for authorization. This should be a UX policy only; backend permissions must remain authoritative.

#### P1 — HighLevel user lookup is a live login dependency

Standalone PWA login exchanges the OAuth code and then calls the HighLevel `/users/{userId}` endpoint before creating the Passport session. If the user lookup is slow, lacks `users.readonly`, or returns a role shape that is not in the accepted set (`user`, `admin`, `administrator`), login fails even though OAuth itself succeeded.

**Fix:** keep the permission check, but show the exact safe failure category to the user, log the provider status/request ID, and add a deployment smoke test for an actual staff account. Confirm that the Marketplace app grants `users.readonly` and that the test staff role maps to the accepted role policy.

#### P2 — Service-worker cache safety

The service worker caches any successful-looking navigation response without checking `response.ok` before replacing `/index.html`. It should cache only an OK HTML response. Also bumping the cache name is currently a manual release step.

**Fix:** cache only `response.ok` responses with an HTML content type, and automate the cache version from the build revision if possible. Never cache API responses or authenticated HTML containing user-specific data.

## Stripe audit

### Current Stripe flow

1. A connected operator uses Stripe Express onboarding. Passport creates the account with the `transfers` capability and creates an Account Link with `refresh_url` and `return_url`.
2. A paid booking creates a local payment record and a Stripe PaymentIntent on the platform account. Amounts are integer minor units, which is correct for Stripe.
3. Stripe.js/PaymentElement handles card entry. Passport does not receive raw card details.
4. `payment_intent.succeeded` is verified using the Stripe signature, the PaymentIntent is matched to the local payment, amount/currency/metadata/livemode are checked, the Charge ID is stored, and the booking is confirmed.
5. A durable outbox job creates a separate transfer to the connected account using the Charge ID as `source_transaction` and an idempotency key.
6. Invoices, refunds, transfer reversals, provider-unknown PaymentIntents, and account updates have persistence and retry paths.

This is a valid high-level model. Stripe’s official documentation describes the same separate-charges-and-transfers model and requires a quick webhook acknowledgement followed by asynchronous processing.

### Stripe blockers and risks

#### P0 — Stripe webhook does external work before responding

`backend/app/api/v1/stripe_webhooks.py` calls `StripeWebhookService.process(event)` and then calls `OutboxService(db, settings).process(limit=100, prefer_newest=True)` before returning `{"received": true}`. That inline processing can call Stripe again, GHL, invoice services, transfers, refunds, and other provider APIs.

This creates three production risks:

- Stripe webhook response latency grows with the number and type of queued jobs.
- A provider outage makes the webhook function stay open until timeout.
- A burst of events can make one serverless function perform unrelated work and exhaust its time budget.

Stripe explicitly recommends returning a successful 2xx response before complex work and handling events asynchronously.

**Fix:** verify the signature, persist/claim the event and the resulting durable jobs, commit, and return 2xx immediately. Do not drain the outbox from the Stripe request. Let the dedicated worker consume the jobs. Keep event IDs idempotent and make event claiming concurrency-safe with a row lock or an atomic claim/update.

#### P0 — Transfers, refunds, invoices, and GHL side effects require a worker

The API can create durable jobs, but only `backend/worker.py` or the internal endpoints process them. If the only deployed runtime is Vercel Hobby, there is no continuous process to run the worker. The daily cron is not a substitute for near-real-time payment settlement or reminders.

**Fix:** deploy one always-on worker process on Railway, Render, Fly.io, Cloud Run, ECS, or another worker-capable host. Keep the API on Vercel if desired. The worker must share the same production environment variables and use the Supabase pooler. Add a worker heartbeat/health metric and alert if the last successful drain is older than a defined threshold.

#### P1 — Connect onboarding status is too optimistic

`StripeConnectService._sync()` marks onboarding complete when details are submitted, payouts are enabled, and transfers are active. It does not persist or expose `requirements.currently_due`, `requirements.past_due`, `disabled_reason`, or the full capability state.

Stripe states that returning from an Account Link does not mean onboarding is complete and recommends checking outstanding requirements or handling `account.updated` events.

**Fix:** persist the current/past-due requirement summary and disabled reason, show “needs attention” rather than simply connected, and block operator payouts when Stripe reports a capability or requirement problem. Continue to use `account.updated` as the source for status refresh.

#### P1 — Dispute handling is incomplete

`charge.dispute.created` changes the local order to `exception`, but the audit did not find a complete dispute evidence workflow, operator notification, or a defined transfer-reversal policy for funds already transferred.

**Fix:** persist dispute ID/status/amount/reason, notify the operator, prevent silent booking settlement assumptions, and define how a dispute after transfer is handled. Add tests for dispute-before-transfer and dispute-after-transfer scenarios.

#### P1 — Webhook event persistence is underused

`StripeWebhookEvent` has `payload` and `attempt_count`, but the webhook service does not appear to persist the full verified payload or increment the event attempt count. Failed events are retried by status, but diagnostics are weaker than they could be.

**Fix:** persist a redacted or encrypted event payload as appropriate, increment attempts atomically, record provider timestamps/request IDs, and expose failed webhook events in an operator/admin diagnostic view.

#### P1 — The Stripe API version is not pinned explicitly

The Stripe SDK is installed with `stripe>=12,<14`. The code does not visibly set an explicit Stripe API version on the client. Webhook event shapes depend on the endpoint/account API version.

**Fix:** pin the Stripe SDK version in the lock/deployment artifact and set or document the Stripe API version used by the application. Test webhook fixtures against that version before upgrading.

#### P2 — Existing-order retry performs an extra Stripe network request

`OrderService._existing_response()` retrieves the PaymentIntent from Stripe when a checkout key is replayed. This is safe but makes idempotent client retries depend on Stripe availability and adds latency.

**Fix:** persist the client secret only if the security model allows it, or return a local “payment setup pending” response and let the client use a dedicated reconciliation endpoint. Do not make every replay block on a provider request.

## HighLevel synchronization and messaging audit

### Current booking synchronization

With `GHL_SYNC_MODE=outbox` (the current default):

- Local booking data is committed first.
- Outbox jobs are created for contact and appointment synchronization.
- `GHLAppointmentService` creates/updates the GHL appointment, includes booking details in the description, and uses Passport booking IDs as correlation markers for recovery.
- Failed jobs use leases, retry counts, exponential backoff, and dead-job status.
- The worker is responsible for applying the jobs promptly.

With `GHL_SYNC_MODE=synchronous`:

- `GHLSyncService` performs up to three attempts with 0.5s and 1.0s delays.
- It records durable sync runs and attempts.
- The order request waits for contact and appointment calls after the local commit.
- In card checkout, the code performs synchronous GHL sync before creating the Stripe PaymentIntent, increasing booking latency and coupling checkout availability to GHL latency.

**Recommendation:** keep local booking/payment creation independent of GHL. Use a durable queue plus a real worker for near-real-time sync. If a synchronous “best effort” mode is required, cap it to one short attempt and return a pending sync state; do not block card setup on multiple provider calls.

### Current messaging ownership

The clean clone still contains Passport-managed message generation and direct HighLevel Conversations API delivery:

- `backend/app/services/ghl_email_service.py` renders templates, waiver links, booking details, staff assignment messages, reminders, cancellation messages, and reschedule messages.
- It sends `POST /conversations/messages` with `type: Email`.
- It requires `conversations/message.write` to be granted.
- `ReminderService` queues customer and staff reminders.
- `GHL_NOTIFICATIONS_ENABLED` controls whether these jobs are active.
- The repository’s `.env.example` says `GHL_NOTIFICATIONS_ENABLED=true`, while the Pydantic default is `False` and the README describes notifications as disabled by default. This is an unsafe deployment ambiguity.

If the desired final architecture is “GHL Workflows send customer email/SMS, Passport sends only staff operational reminders,” the current clone is not yet in that final state. It still has Passport-rendered/direct message jobs and does not have a complete inbound Custom Trigger event contract for all booking/payment/waiver transitions.

**Fix:** decide one owner per message category and enforce it in configuration and code:

- Customer confirmation/reminders/cancellation/reschedule: publish a durable booking event to the selected GHL workflow trigger, or use appointment `toNotify` only where the HighLevel workflow contract is proven.
- Staff assignment/reminders: keep Passport-owned jobs if that is the chosen requirement.
- Remove or disable direct customer message jobs once the GHL workflow path is verified.
- Add a message ownership regression test so a booking cannot send duplicate Passport and GHL Workflow messages.

## Background jobs and Vercel Hobby risk

The repository has three job execution paths:

1. `backend/worker.py`: continuous 15-second default loop for GHL staff directory/availability sync, hold expiration, and one outbox batch.
2. `POST /api/v1/internal/process-outbox`: protected manual/batch processing endpoint.
3. `GET /api/v1/internal/cron/daily`: protected daily job that queues reminders, expires holds, synchronizes all operators, and drains the outbox for up to 45 seconds.

Vercel’s current official documentation states that Hobby cron jobs can run only once per day and timing is approximate within the scheduled hour. Vercel Functions also have a maximum duration, not continuous execution.

Therefore:

- GHL appointment/contact sync may wait until the next day if the worker is absent.
- Stripe transfers, refunds, invoice creation, and transfer reversals can remain pending.
- Same-day staff/customer reminders can be late or missed.
- The daily endpoint may time out or process only part of a large tenant set.

**Production topology recommendation:**

```text
Vercel frontend + API functions
          |
          v
Supabase PostgreSQL (pooler)
          ^
          |
Always-on worker service running backend/worker.py
          |
Stripe webhooks / GHL webhooks enqueue durable local work
```

A queue service such as Redis, a managed queue, or Vercel Queues can be introduced later, but the existing PostgreSQL outbox can be the first reliable queue if one worker is deployed and monitored.

## Why pages and bookings can feel slow

The main code-level causes are:

1. **Cold starts and database connection setup** on serverless requests.
2. **One pooled database connection per warm API process**, which prevents connection explosion but queues concurrent work in the same instance.
3. **Synchronous external calls in request paths**, especially synchronous GHL mode and Stripe webhook inline outbox processing.
4. **Multiple sequential booking preparation queries**, resource locking, re-validation, customer upsert, payment setup, and possible external provider calls.
5. **FullCalendar and booking routes are heavy chunks**, although route-level code splitting has improved initial `/app` loading.
6. **Global React Query focus refetching** can refresh several queries when a phone tab/app returns to the foreground.
7. **Confirmation polling every two seconds** continues until payment confirmation or exception. This is acceptable for one active checkout but should use a bounded backoff for scale.
8. **The daily cron performs too many unrelated tasks in one request**, including all-tenant staff reconciliation and a 45-second outbox drain.

The largest improvement will come from removing provider calls from user/webhook request paths and deploying the worker. Database/query tuning should follow with real latency measurements rather than increasing pool sizes blindly.

## Database readiness audit

### Good controls

- The repository has forward-only Supabase SQL migrations through `038_pwa_workspace_performance`.
- The readiness probe checks core tables and a schema marker.
- Booking/payment/waiver and PWA indexes are represented in migrations.
- Token digests are stored instead of raw waiver/private-link tokens.

### Remaining database risks

#### P1 — Readiness checks too few tables

`backend/app/core/database.py` checks only a small subset of required tables: operators, calendars, bookings, payments, outbox jobs, OAuth states, booking adjustments, policies, message templates, public credentials, and PWA handoffs. Runtime code also requires Stripe connections, Stripe webhook events, payment intent requests, transfer/refund/reversal tables, GHL installations/mappings/sync tables, staff tables, customer tables, waiver tables, and others.

A partially applied database can therefore pass readiness and fail later on a specific feature.

**Fix:** expand the readiness contract to include every table needed by enabled production features, or validate each migration marker plus a generated schema contract. Run readiness against a freshly migrated staging database before deployment.

#### P1 — Full migration chain was not executed in this audit

The test run intentionally skipped database integration tests because `TEST_DATABASE_URL` was not set. Apply all migrations to a disposable PostgreSQL clone, run the complete suite, and run `EXPLAIN (ANALYZE, BUFFERS)` for dashboard, booking-slot, availability, notification, and outbox queries.

#### P2 — Production dependency reproducibility

`requirements.txt` uses broad version ranges and there is no backend lock file. Create a tested lock/constraints file and upgrade dependencies deliberately. Keep the frontend lock file as the source of truth.

## Security audit

### Positive findings

- OAuth state values are stored as digests and consumed once.
- HighLevel access/refresh tokens are encrypted at rest.
- Public access tokens and waiver tokens use digests rather than raw database values.
- Stripe signature verification is present.
- Public booking/status/cancel/reschedule routes use database-backed rate limiting.
- Protected application routes derive the tenant from the verified Passport session and check membership/authorization version.
- Raw card data is not handled by Passport.

### Remaining security work

1. Replace localStorage bearer persistence with an HttpOnly refresh-cookie/session design.
2. Implement real PWA logout and device-session revocation.
3. Add rate limiting to PWA OAuth start/exchange and sensitive admin resync endpoints.
4. Make the public readiness endpoint return a generic failure message rather than schema/internal diagnostic details.
5. Tighten CSP and add a production CSP for scripts, styles, API origin, Stripe.js, and frame ancestors. The backend middleware currently emits broad `frame-ancestors https:` while the frontend Vercel header is more restrictive.
6. Pin backend dependencies and run `pip-audit` in CI.
7. Add structured audit logs and alerts for failed payment webhooks, dead outbox jobs, GHL sync failures, and repeated login failures.

## Prioritized implementation plan

### Phase 0 — must complete before live bookings

1. Deploy an always-on worker and verify it processes a test GHL appointment, Stripe transfer, invoice, refund, and hold expiry.
2. Remove inline outbox draining from the Stripe webhook; return 2xx after durable event/job commit.
3. Run the complete backend suite against a fresh PostgreSQL migration clone.
4. Configure separate PWA and embedded HighLevel OAuth redirect environment variables and exact HighLevel allowlisted URLs.
5. Run a full Stripe test-mode smoke test: card success, 3DS, failed card, webhook redelivery, invoice paid/failed/voided, refund, transfer, transfer reversal, and connected-account requirement failure.
6. Make `.env.example`, runtime defaults, README, and the selected messaging architecture agree. Do not deploy with an accidental `GHL_NOTIFICATIONS_ENABLED=true`.

### Phase 1 — security and operational safety

1. Add real PWA logout and per-device revocation.
2. Replace localStorage session persistence or reduce the exposure window while the migration is staged.
3. Expand readiness table/schema checks.
4. Add worker heartbeat, outbox backlog/dead-job metrics, Stripe webhook failure alerts, and GHL sync failure notifications.
5. Add rate limits to OAuth and manual resync paths.

### Phase 2 — performance

1. Measure endpoint p50/p95 latency in staging.
2. Remove provider calls from booking and webhook request paths.
3. Add query plans and indexes based on measurements.
4. Tune Supabase pooler usage and serverless concurrency based on the real connection budget.
5. Replace unbounded 2-second confirmation polling with exponential backoff plus a final timeout/status message.
6. Keep route-level code splitting and consider reducing the initial vendor bundle after measuring mobile cold-load performance.

### Phase 3 — workflow ownership

1. Decide whether customer notifications are Passport-direct, GHL Workflow-triggered, or both by explicit event type.
2. Implement one durable event contract for booking-created, payment-confirmed, waiver-updated, cancelled, and rescheduled states.
3. Include booking reference, appointment ID, payment status, waiver URL/status, customer contact ID, and a deduplication key.
4. Test that every event produces exactly one customer workflow enrollment/message and that staff reminders remain Passport-owned if required.

## Release checklist

Before switching to live mode:

- [ ] Fresh Supabase database applies all migrations through `038_pwa_workspace_performance`.
- [ ] Full PostgreSQL-backed test suite passes; no integration suite remains skipped.
- [ ] `/api/readiness` is green against the production database.
- [ ] Vercel frontend has the correct `VITE_API_BASE_URL`, `VITE_PWA_APP_URL`, and Stripe publishable key.
- [ ] Backend has production URLs, encrypted GHL credentials, Stripe live keys, webhook secret, session secret, and cron secret.
- [ ] GHL app has the exact embedded and PWA redirect URLs and all required scopes.
- [ ] PWA login, callback, refresh, logout, and revocation have been tested on iPhone Safari and Android Chrome.
- [ ] An always-on worker is deployed and monitored.
- [ ] Stripe webhook returns quickly and no longer drains unrelated outbox work inline.
- [ ] Stripe endpoint subscribes only to required event types and has a replay/redelivery runbook.
- [ ] Connect onboarding handles outstanding requirements and `account.updated` events.
- [ ] Customer/staff message ownership is explicitly configured and duplicate sends are tested.
- [ ] Backup/restore and incident runbooks exist for Supabase, Stripe, GHL, and outbox failures.

## Official references consulted

- [Stripe webhooks](https://docs.stripe.com/webhooks) — signature verification, fast 2xx response, retries, duplicate events, event ordering, and asynchronous processing.
- [Stripe separate charges and transfers](https://docs.stripe.com/connect/separate-charges-and-transfers) — platform charges and connected-account transfers.
- [Stripe hosted Connect onboarding](https://docs.stripe.com/connect/hosted-onboarding) — Account Link refresh/return behavior and outstanding requirements.
- [Vercel Cron usage and pricing](https://vercel.com/docs/cron-jobs/usage-and-pricing) — Hobby cron once-per-day restriction and timing precision.
- [Vercel Function limitations](https://vercel.com/docs/functions/limitations) — request-driven execution and Hobby duration limits.
- [HighLevel Get Access Token](https://marketplace.gohighlevel.com/docs/ghl/oauth/get-access-token/) — v3 OAuth token contract, Location token fields, scopes, and required Version header.

## Final recommendation

Do not delete or rewrite the booking/payment domain. The core transactional design is a good foundation. Make the production changes in this order:

1. **Worker + asynchronous webhook processing.**
2. **Real staging database/provider smoke tests.**
3. **PWA redirect/session/logout hardening.**
4. **Stripe Connect requirements/dispute observability.**
5. **Performance measurement and query tuning.**
6. **Final GHL workflow/message ownership implementation.**

After Phase 0 is complete and the staging smoke test passes, the system can be moved toward a controlled pilot. It is not yet safe to call the current Vercel-only deployment production-ready for paid bookings.
