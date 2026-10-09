# Passport MVP — Complete Repository Scan

**Repository:** `https://github.com/moawiz-2706/MVP.git`  
**Scanned commit:** `4974ff8` — `Fix HighLevel email delivery and async bookings`  
**Scan date:** 2026-10-08  
**Workspace:** `/home/ubuntu/MVP`

## Executive summary

This is a substantial multi-tenant booking and rental platform named **Passport**. It is implemented as:

- **Backend:** FastAPI, SQLAlchemy 2, PostgreSQL/Supabase, Python 3.12+
- **Frontend:** React, TypeScript, Vite, React Query, FullCalendar, Stripe.js
- **External systems:** GoHighLevel (identity/CRM/calendar/contact/staff projection and email conversations), Stripe Connect (payments and operator transfers), Supabase PostgreSQL (authoritative application state)
- **Async processing:** transactional outbox plus a persistent `backend/worker.py`; Vercel Cron is a fallback
- **Schema:** 34 SQL migration files under `supabase/migrations/` (migration `009` is absent; migrations are intended to be applied by filename order)

The core booking product is implemented: tenant/session setup, calendars, availability, resource capacity, customer types/rates, public checkout, operator bookings, staff assignment, customer records, reports, Stripe payments, invoices, lifecycle adjustments, GHL projection, message templates, and waivers.

The most important product boundary is:

> **Passport is authoritative for availability, inventory, pricing, booking state, payment state, waivers, policies, and customer-facing checkout. GHL is an integration/projection target for identity, contacts, calendars, appointments, staff identity, and outbound email conversations.**

---

## 1. Repository structure and application surfaces

### Backend route groups

| Area | Main routes/files | Status |
|---|---|---|
| Liveness/readiness | `backend/app/main.py` | Implemented; readiness checks production configuration/database |
| Embedded auth | `api/v1/auth.py`, `core/app_session.py` | GHL encrypted context → short-lived in-memory frontend bearer JWT |
| GHL Marketplace OAuth | `api/v1/ghl_oauth.py`, `services/ghl_auth_service.py` | OAuth state cookie/database state, token encryption/rotation, installation provisioning |
| GHL lifecycle webhooks | `api/v1/ghl_webhooks.py` | Signed lifecycle webhook handling and deduplication |
| Public catalog/availability | `api/v1/public.py`, `api/v1/availability.py` | Catalog, categories, rates, custom fields, live availability |
| Public orders | `api/v1/orders.py` | Quote, create, status, cancellation, rescheduling |
| Operator bookings | `api/v1/bookings.py` | List/detail/create/update/cancel/status/participants/notes/retry sync |
| Configuration | `api/v1/configuration.py` | Locations, resources, customer types, categories, calendars, hours, blocks, pushed slots, rates |
| FareHarbor-style backend | `api/v1/fareharbor_replica.py` | Policies, custom fields, customers, weather closure, migration/reconciliation APIs |
| Staff | `api/v1/staff.py`, `staff_ghl.py`, `staff_booking.py` | Roster, GHL user sync, assignments, conflicts, private staff booking links |
| Messages | `api/v1/messages.py` | Tenant-scoped templates, preview, reset |
| Notifications | `api/v1/notifications.py` | In-app operational notifications |
| Stripe Connect/payments | `api/v1/stripe_connect.py`, `stripe_webhooks.py` | Onboarding/status, signed webhook processing |
| Waivers | `api/v1/waivers.py` | Public view/sign and operator settings |
| Reports | `api/v1/reports.py` | Summary and CSV export |
| Internal jobs | `api/v1/internal_jobs.py` | Protected outbox processing and daily cron |

### Frontend routes

The frontend includes embedded operator pages for bookings, notifications, resources, locations, calendars, staff, customers, reports, settings, message templates, Stripe settings, and waiver settings. Public pages cover operator/category/calendar booking, confirmation, Stripe payment, waiver signing, and private staff booking.

The frontend API client keeps the operator session token in module memory rather than local storage and retries one request after a session refresh on HTTP 401.

---

## 2. Main booking and availability behavior

1. A public or authenticated booking request resolves the operator and calendar, validates active/public state, time zone, calendar hours/mode, cutoff, blocks, party size, rate/customer type, custom fields, and resources.
2. Availability supports:
   - `day_wise` weekly hours
   - `date_wise` date ranges
   - `pushed` explicitly offered departure slots
3. Shared resources are calculated across all calendars in the operator. Capacity uses peak concurrent usage rather than simply summing every overlapping booking.
4. The booking transaction locks relevant resource rows in deterministic UUID order, recalculates availability after acquiring locks, and validates the whole cart as one batch.
5. The transaction creates the order, bookings, resource reservations, participants, line-item snapshots, custom-field values, and payment record.
6. Paid card bookings receive a local hold and then a Stripe PaymentIntent. Free bookings are confirmed transactionally without a PaymentIntent.
7. GHL appointment/contact work is represented as outbox jobs. Provider failures do not roll back a valid local booking.
8. Stripe webhooks, not the browser, authorize final paid confirmation.
9. Hold expiry releases pending reservations and queues GHL appointment cancellation.

Financial values are integer minor units. The payment utility snapshots subtotal, platform fee/taxes, customer total, operator transfer, and platform retained amount onto the order/payment records.

---

# 3. Messaging and email handling

## Provider and delivery path

Passport does **not** use SMTP, SendGrid, SES, or a first-party mail server. Customer and staff email is sent through **GoHighLevel's Conversations API**:

```text
Passport booking/lifecycle event
        ↓
Local database transaction
        ↓
Transactional outbox_jobs row with unique idempotency key
        ↓
Persistent worker or protected cron
        ↓
GHL contact upsert/sync
        ↓
POST /conversations/messages
  { type: "Email", contactId, subject, html, message }
```

The provider call is implemented in `backend/app/services/ghl_email_service.py` and uses `GHLClient`, which is the only authenticated HighLevel API adapter. The required HighLevel scope is `conversations/message.write`.

## Message types

There are ten customizable template events in `message_template_service.py`:

1. Booking confirmation
2. Booking cancellation
3. Weather cancellation
4. Booking reschedule
5. Customer day-before reminder
6. Customer same-day reminder
7. Staff assignment
8. Staff removal
9. Staff day-before reminder
10. Staff same-day reminder

Hosted Stripe invoice delivery is separate: Stripe owns the invoice email and it is intentionally not rendered by the Passport message-template editor.

## Trigger behavior

| Event | Trigger | Delivery details |
|---|---|---|
| Confirmation | Free booking confirmation, verified card `payment_intent.succeeded`, or verified invoice `invoice.paid` | GHL contact sync first, then confirmation email |
| Cancellation | Operator/customer lifecycle cancellation | Durable GHL cancellation email job |
| Weather cancellation | Weather closure lifecycle action | Durable GHL weather email job with refund/credit/manual-review outcome |
| Reschedule | Successful lifecycle reschedule | Durable GHL reschedule email job with previous time/payment outcome |
| Customer reminders | Daily cron finds confirmed bookings due today/tomorrow in operator time zone | Re-checks booking status and reminder window at send time |
| Staff assignment/removal | Assignment changes for future slots | Staff contact sync plus assignment/removal email; removal uses a snapshot because the assignment row is deleted |
| Staff reminders | Daily cron finds active future assignments due today/tomorrow | Re-checks staff activity, assignment, email, and reminder window |

## Template behavior

- Templates are tenant-scoped in `message_templates` by `operator_id` and `event_type`.
- Defaults are embedded in `message_template_service.py`.
- Settings UI: `frontend/src/settings/MessageTemplatesSettings.tsx`.
- Operators can enable/disable each message, edit subject/body, preview, save, and restore defaults.
- Merge fields are allowlisted. Unknown fields, blank subjects/bodies, line breaks in subjects, and unbalanced merge braces are rejected.
- Persisted malformed templates fall back to the built-in safe default rather than breaking delivery.
- Body text is HTML-escaped before HTML generation. Waiver URLs are rendered as links after escaping.
- Templates are rendered at **delivery time**, so an outbox retry uses the current account template.

## Suppression and configuration gates

An email is suppressed if any of the following applies:

- Backend environment variable `GHL_NOTIFICATIONS_ENABLED` is false. The application default is false.
- The operator's `confirmation_email_enabled` setting is false for customer communications.
- The message-specific template is disabled.
- The required GHL contact/staff record or email is unavailable.
- The installation lacks the required HighLevel scope.
- The staff member is inactive/deleted or the booking/assignment is no longer eligible.

## Reliability behavior

- Booking/lifecycle state is committed before external delivery.
- Outbox jobs use unique idempotency keys, leases, fencing tokens, attempt counters, exponential backoff, and a terminal `dead` state.
- The worker in `backend/worker.py` runs staff reconciliation, hold expiry, and outbox processing on a configurable 10–60 second interval.
- `GET /api/v1/internal/cron/daily` is a protected fallback that queues reminders, expires holds, syncs staff, and drains the outbox for a bounded time.
- Inline processing is best effort only; failures are retained for worker retry.

## Messaging conclusions

The messaging architecture is strong for an MVP because local booking state is not coupled to provider availability. The main operational requirement is that a persistent worker or frequent protected runner must be deployed; Vercel's daily cron is not sufficient for prompt messages. Actual inbox placement, bounces, spam, sender-domain setup, and GHL account permissions remain provider-level concerns.

---

# 4. Payments and Stripe Connect handling

## Stripe Connect onboarding

Implemented in `backend/app/services/stripe_connect_service.py` and exposed under `/api/v1/settings/payments/stripe`.

1. An operator with payment-management permission calls **Connect Stripe**.
2. Passport creates a Stripe **Express** connected account with the `transfers` capability requested.
3. The connected account ID and onboarding status are stored in `stripe_connections`.
4. Passport creates a Stripe Account Link with return/refresh URLs on the frontend.
5. The operator completes Stripe-hosted onboarding.
6. Status is considered ready only when `details_submitted`, `payouts_enabled`, and the `transfers` capability is `active`.
7. `account.updated` webhook events synchronize the local onboarding fields.
8. Paid booking creation rejects the booking if the operator is not payout-ready.

The settings UI is `frontend/src/settings/SettingsPage.tsx`; the connected account's full ID is not displayed, only a masked suffix.

## Public card payment flow

```text
POST /public/{operator}/orders
        ↓
Create local pending-payment hold and Payment record
        ↓
Commit local transaction
        ↓
Create Stripe PaymentIntent server-side
        ↓
Return client_secret to browser
        ↓
Stripe.js PaymentElement confirms card payment
        ↓
Stripe signs payment_intent.succeeded webhook
        ↓
Passport verifies and confirms booking
```

PaymentIntent creation (`stripe_payment_service.py`) includes:

- Amount and currency from the locally calculated immutable total
- `receipt_email` from the customer
- `transfer_group=booking_order_{public_reference}`
- Metadata for local order ID, operator ID, and public reference
- Stable idempotency key `booking_order:{order_id}:payment_intent`

The frontend uses Stripe Elements in `frontend/src/public-booking/PaymentPanel.tsx`. Card details are handled by Stripe.js and are not sent to Passport.

## Signed Stripe webhook processing

`POST /api/v1/webhooks/stripe`:

- Reads the raw request body.
- Requires `Stripe-Signature` and `STRIPE_WEBHOOK_SECRET`.
- Verifies the signature with Stripe's webhook utility.
- Deduplicates by Stripe event ID in `stripe_webhook_events`.
- Persists failure state for retryable provider redelivery.
- Processes payment, invoice, account, refund, and dispute events.

For `payment_intent.succeeded`, Passport validates:

- PaymentIntent status
- Amount and amount received
- Currency
- Local order metadata
- Operator metadata
- Public reference metadata
- Expected platform account, if configured
- Test/live mode against the configured secret key
- A real successful `ch_...` Charge ID in `latest_charge`

After validation, Passport re-locks the booking/resources, confirms only if capacity is still valid, records the charge, marks the order/payment successful, and queues transfer/contact/email/appointment jobs. If a hold expired and capacity is no longer available, the order becomes an exception and a refund outbox job is created instead of silently overbooking.

## Hosted invoice flow for team/staff bookings

Authenticated operator/team booking can select `payment_required`:

- `payment_required=true`: create local pending hold and `stripe_create_invoice` outbox job.
- `payment_required=false`: create and confirm a free booking immediately.
- Public checkout cannot use this override; public paid checkout remains card-based.

`StripeInvoiceService` creates/reuses:

1. Stripe Customer
2. Stripe Invoice Item
3. Stripe Invoice with `collection_method=send_invoice`
4. Finalized/open hosted invoice
5. Stripe `send_invoice` email

Passport stores invoice/customer/item IDs, invoice status, and hosted URL. Stripe owns the invoice email and card-entry page.

`invoice.paid` verifies the local payment, order, customer, amount, currency, and PaymentIntent, then routes into the same successful-payment confirmation path. `invoice.payment_failed`, `invoice.voided`, and `invoice.marked_uncollectible` safely update payment/booking state and release pending holds when appropriate.

## Separate Charges and Transfers

The platform uses Stripe's **separate charges and transfers** model:

- The customer charge is on the platform account.
- The operator receives a distinct Transfer to the connected account.
- The transfer uses the successful `ch_...` Charge ID as `source_transaction`.
- The transfer amount is the snapshotted `operator_transfer_minor`.
- `transfer_group=booking_order_{public_reference}` supports reconciliation.
- Idempotency key: `booking_order:{order_id}:operator_transfer`.
- A unique `stripe_transfers.payment_id` prevents duplicate local transfers.

This is not destination-charge behavior. The source transaction binding lets Stripe tie the transfer to the charge's settlement.

## Refunds, credits, and transfer reversals

There is no standalone customer-facing refund form. Refunds arise from lifecycle/exception workflows:

- Cancellation policy outcome
- Weather cancellation mode
- No-show policy
- Paid reschedule price decrease
- Late payment against an expired/unavailable booking
- Provider reconciliation/exception paths

`AdjustmentService` creates durable, idempotent adjustment records. Refund attempts create `stripe_create_refund` jobs. If an operator transfer already exists, a corresponding transfer-reversal attempt/job is created. `charge.refunded` is also handled as a reactive reconciliation event for refunds made outside Passport.

A paid reschedule price increase is deliberately rejected because the current flow has no safe additional-payment confirmation step.

## Payment conclusions

The Stripe design has good foundations: server-side totals, webhook authority, metadata validation, idempotency, late-payment capacity checks, separate transfer records, and durable refund/reversal jobs. The remaining work for production confidence is real Stripe test-mode end-to-end verification and operational monitoring of dead outbox jobs, webhook failures, disputes, and reconciliation exceptions.

---

# 5. Waiver handling

## Configuration

Operator settings are stored in `operator_settings`:

- `waiver_title`
- `waiver_website`
- `waiver_text`
- `waiver_opt_in_label`

Settings UI: `frontend/src/settings/WaiverSettings.tsx`.

A blank `waiver_text` means waivers are disabled for that operator. The policy object also has `requires_waiver`, which is exposed in the public booking policy and displayed to customers.

## Link creation and access

- One `booking_waivers` row is created lazily per booking when a confirmed/completed booking needs a link.
- The link token is generated with `secrets.token_urlsafe(24)`.
- The raw token is placed in the frontend URL `/waiver/{token}`.
- Default link expiry is controlled by `WAIVER_PUBLIC_DAYS` (30 days by default).
- Waiver links are returned on the public confirmation/status page, booking detail, confirmation message, and reminders while unsigned.
- The public API is `GET /api/v1/public/waivers/{token}` and `POST /api/v1/public/waivers/{token}/sign`.

## Signing validation

`WaiverService.sign()` locks the waiver row with `FOR UPDATE` and verifies:

- Link is not expired
- Waiver is not already signed
- Operator still has waiver text
- Booking is still `confirmed` or `completed`
- Number of people equals booking units
- No date of birth is in the future
- Signer is at least 18 on the current date
- Signature is a real PNG data URL, max 300 KB
- User agreed to the waiver

The frontend collects:

- Signer's name, email, phone, date of birth
- Signer's home address
- Every other participant's name and date of birth
- Optional marketing/opt-in choice
- Drawn signature from `SignaturePad`

A participant is marked as a minor based on age on the activity date, not merely age on signing date.

## Legal/audit snapshot

On signing, the backend snapshots:

- Exact waiver title/text at signing time
- Activity name and start time from the booking snapshot
- Signer details and address
- Participant details and minor flags
- Opt-in state and label
- Base64 PNG signature
- Signer IP and user-agent
- Signature timestamp

The database migration installs `prevent_signed_waiver_change`, which rejects updates/deletes once `status='signed'`. The signed frontend view is read-only and supports print/save as PDF.

## Waiver conclusions and gaps

The core waiver record path is complete and has good concurrency/immutability controls. Two important product/security points should be decided before expanding it:

1. **`requires_waiver` is currently informational, not a hard gate.** It is returned in public policy and shown in the booking UI, but `rg` shows no booking/lifecycle enforcement that blocks activity, confirmation, or operations until the waiver is signed. If the requirement is legally mandatory, add an explicit enforcement policy at the relevant operational boundary.
2. **Waiver tokens are stored as raw token text and waiver endpoints do not call the public rate-limit service.** Order/staff access credentials are digest-based, but waiver bearer links use direct token lookup. Consider storing a digest and adding rate limits/audit monitoring if the threat model requires the same protection level.

---

## 6. Security and reliability observations

### Positive controls found

- Short-lived bearer sessions held in frontend memory
- GHL access/refresh tokens encrypted at rest
- OAuth state is mandatory, cookie-bound, database-backed, single-use, and location-checked
- Stripe webhook signature verification
- GHL webhook signature verification
- Server-side payment amount/currency/metadata checks
- Public order/staff credentials use digests
- Public order rate limiting
- Transactional outbox with idempotency, leasing, fencing, retry, and dead-letter state
- Resource row locking and PostgreSQL staff-assignment exclusion constraint
- Signed waiver database immutability trigger
- SQLAlchemy parameterized queries and Pydantic validation

### Items to address

- No PostgreSQL RLS statements were found in the migration history; tenant isolation currently depends on application predicates and database trigger checks.
- The combined root Vercel manifest sends `frame-ancestors https:`, while `frontend/vercel.json` uses a narrower allowlist. Deployment should use one explicit, consistent policy.
- The CSP is minimal and does not define `default-src`, `script-src`, `connect-src`, `img-src`, or Stripe-specific directives.
- HighLevel request handling retries one 401 but does not have an explicit provider-aware 429/backoff strategy; the outbox provides generic retry/backoff.
- The frontend production bundle is approximately 908 kB minified in this build, triggering Vite's chunk-size warning; route-level code splitting would improve embedded/public performance.
- `on_event` startup hooks produce a FastAPI deprecation warning; this is not currently a correctness failure.

---

## 7. Verification performed

### Passed

- Frontend `npm ci`
- Frontend `npm run typecheck`
- Frontend `npm run test:booking-notifications`
- Frontend `npm run build`
- Backend Python compilation via `python -m compileall -q backend`
- `git diff --check`
- Merge-conflict-marker scan
- Backend pure/unit-oriented suite after excluding DB-dependent tests: **110 passed, 95 skipped, 0 failed**

### Not fully executable in this sandbox

- PostgreSQL-backed integration tests: no local PostgreSQL service is available and `TEST_DATABASE_URL` was not supplied.
- External GHL/Stripe provider contract tests: no staging provider credentials were used.
- Browser checkout → Stripe webhook → confirmation → waiver → cancellation/refund → GHL projection smoke test: not run.

### Test-suite issue discovered

`backend/tests/test_private_staff_booking_links.py` has two tests that use the `db` fixture but do not consistently skip when `TEST_DATABASE_URL` is absent. The normal suite therefore produces two setup errors in this environment rather than clean skips. Excluding that file allows the remaining non-PostgreSQL suite to pass.

Recommended test fix: apply the shared database skip marker to the whole module or make the `engine` fixture skip when `TEST_DATABASE_URL` is unset.

---

## 8. Recommended implementation order for new features

1. **Decide the waiver requirement contract:** informational reminder versus hard operational gate.
2. **Finish the staging verification gate:** run all migrations through `034`, then run PostgreSQL-backed tests against a disposable database.
3. **Fix the private staff test skip behavior** so missing infrastructure produces skips rather than errors.
4. **Add provider contract smoke tests** for card payment, invoice payment, transfer, refund, transfer reversal, GHL contact/email, and webhook replay.
5. **Keep new external side effects behind the existing outbox** and preserve local-first transaction semantics.
6. **For new payment-affecting features**, extend immutable adjustment/allocation records and webhook/idempotency handling before adding UI.
7. **For new message types**, add an event type/default template, merge-field validation, outbox job type/migration constraint, delivery handler, suppression rules, and tests together.
8. **For waiver changes**, preserve signed snapshots and never mutate signed records in place.

## Key files to start from

- Messaging: `backend/app/services/ghl_email_service.py`, `message_template_service.py`, `outbox_service.py`, `api/v1/messages.py`
- Stripe: `stripe_connect_service.py`, `stripe_payment_service.py`, `stripe_invoice_service.py`, `stripe_webhook_service.py`, `stripe_transfer_service.py`, `adjustment_service.py`
- Waivers: `waiver_service.py`, `api/v1/waivers.py`, `schemas/waiver.py`, `frontend/src/waivers/WaiverPage.tsx`
- Booking lifecycle: `booking_lifecycle_service.py`, `order_service.py`, `api/v1/orders.py`, `api/v1/bookings.py`
- Schema: `backend/app/models/entities.py`, `supabase/migrations/`
