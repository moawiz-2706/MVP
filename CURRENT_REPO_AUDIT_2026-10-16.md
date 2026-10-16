# Current Repository Audit — 2026-10-16

Repository reviewed: `https://github.com/moawiz-2706/MVP.git`

Local clone: `/home/ubuntu/MVP_20261016`

Commit reviewed: `a0e1c1d` (`update`)

## Executive summary

The system is a Passport booking platform where Passport is the source of truth for calendars, availability, bookings, waivers, payments, and staff scheduling. HighLevel is used as an external projection for contacts, calendars, appointments, and staff identities. Stripe handles card payments, hosted invoices, connected-account onboarding, transfers, refunds, and reversals.

The main reason the application feels slow is not one single query. It is the combination of:

1. One database connection per backend process, so concurrent requests queue behind one connection.
2. Some HighLevel and Stripe network calls run inside user-facing requests or webhook requests.
3. The frontend polls several endpoints repeatedly.
4. Some synchronization operations call other synchronization operations, creating multiple database and HighLevel requests for one action.
5. The current repository defaults to the durable outbox mode, but has also retained a synchronous GHL mode that can intentionally add provider latency to booking creation.

## 1. How messaging currently works

### Customer and staff messages

Passport currently sends messages through HighLevel's Conversations API, specifically `POST /conversations/messages`.

The main implementation is:

- `backend/app/services/ghl_email_service.py`
- `backend/app/services/message_template_service.py`
- `backend/app/services/outbox_service.py`
- `backend/app/services/reminder_service.py`

The current flow is:

1. A booking or staff action changes local Passport data.
2. Passport creates an `outbox_jobs` row for the message.
3. The worker or internal cron claims the job.
4. `GHLEmailService` renders the message template and sends it through HighLevel.
5. Failed jobs are retried with increasing delays until `OUTBOX_MAX_ATTEMPTS` is reached.

Message types currently present include:

- Booking confirmation
- Booking cancellation
- Weather cancellation
- Booking reschedule
- Customer day-before reminder
- Customer same-day reminder
- Staff assignment
- Staff unassignment
- Staff day-before reminder
- Staff same-day reminder

Message bodies are configurable through the `message_templates` table and the Messages settings API/UI.

### Important configuration

- `GHL_NOTIFICATIONS_ENABLED=false` by default in application settings.
- `backend/.env.example` currently shows `GHL_NOTIFICATIONS_ENABLED=true`, so the deployed environment can override the safe code default.
- `OperatorSettings.confirmation_email_enabled` also controls customer confirmation/reminder delivery.
- The HighLevel installation requests `conversations/message.write` in `backend/app/services/ghl_auth_service.py`.

### Reminder ownership

The current clean clone sends both customer reminders and staff reminders through HighLevel. `ReminderService` queues both kinds, and the daily cron endpoint runs the reminder enqueue step before draining the outbox.

This is different from the desired architecture you described earlier, where customer emails/SMS should be handled by HighLevel workflows but staff reminders should remain Passport-owned. That split has not yet been implemented in this clean GitHub clone.

## 2. How Stripe Connect and payments work

### Stripe Connect onboarding

The implementation is in:

- `backend/app/services/stripe_connect_service.py`
- `backend/app/api/v1/stripe_connect.py`
- `frontend/src/settings/SettingsPage.tsx`

Passport creates a Stripe Express connected account for each operator. It requests the `transfers` capability, stores the connected account ID in `stripe_connections`, and creates a hosted Stripe onboarding link.

The operator is considered ready only when:

- Stripe account details were submitted.
- Payouts are enabled.
- The transfers capability is active.

The status endpoint can refresh the account directly from Stripe. That refresh is a live Stripe API call and can feel slow when the settings page requests it.

### Card payment flow

The card flow is:

1. Passport calculates the booking total in minor currency units, for example cents.
2. Passport creates a local `payments` row and a `payment_intent_requests` row.
3. Passport creates a Stripe PaymentIntent with:
   - Amount
   - Currency
   - Receipt email
   - Booking/order metadata
   - Transfer group
   - An idempotency key
4. Stripe returns a client secret.
5. The browser uses Stripe Elements/PaymentElement. Raw card details do not enter Passport.
6. Stripe sends `payment_intent.succeeded` to Passport.
7. Passport verifies the webhook, validates amount/currency/metadata, confirms the booking, and queues the operator transfer.

If the PaymentIntent request times out, Passport marks it `provider_unknown` and queues a reconciliation job. It can search Stripe by booking metadata before attaching a provider-created PaymentIntent.

### Hosted invoice flow

For invoice bookings:

1. Passport creates a Stripe Customer.
2. It creates an invoice item.
3. It creates or recovers an invoice using booking metadata.
4. It finalizes and sends the hosted invoice.
5. The client receives the hosted invoice URL.
6. Stripe sends invoice lifecycle webhooks back to Passport.
7. `invoice.paid` ultimately confirms the booking.

Stripe owns the invoice payment page and invoice delivery.

### Connected-account transfer flow

After a successful customer payment, Passport creates a transfer to the operator's connected account. It uses the successful Stripe Charge as `source_transaction`, includes the booking transfer group, and uses an idempotency key.

This is performed through the outbox worker rather than inside the payment webhook's main database transaction.

### Refunds, reversals, and disputes

- Refunds are recorded as `payment_refund_attempts` and executed by an idempotent outbox job.
- If money was already transferred to an operator, Passport can create a transfer reversal.
- Refund and reversal failures remain recorded for retry/manual review.
- Stripe webhook events are deduplicated through `stripe_webhook_events`.
- Webhook signatures are checked using `STRIPE_WEBHOOK_SECRET`.

## 3. How booking synchronization with HighLevel works

### Calendar sync

Passport is the source of truth for availability. HighLevel event calendars are projections.

When a calendar is synchronized, Passport:

1. Finds an existing HighLevel calendar using a Passport marker.
2. Updates it if a mapping exists.
3. Creates it if it does not exist.
4. Pushes schedule rules and timezone.
5. Stores the remote ID in `ghl_calendar_mappings`.

The calendars are intentionally left open enough for Passport to remain the availability authority. Booking availability and capacity are calculated by Passport, not trusted to HighLevel.

### Contact sync

`GHLContactService` creates or updates the customer contact in HighLevel and stores the remote contact ID on the Passport order/customer record.

Contact custom-field mappings exist in `ghl_custom_field_mappings`. In this clean clone the mapping service still expects configured remote field IDs for its payload path; it is not the newer custom-object implementation discussed in previous planning notes.

### Appointment sync

`GHLAppointmentService` creates or updates a HighLevel appointment in the event calendar.

The appointment payload includes:

- HighLevel calendar ID
- Location ID
- Contact ID
- Title
- Passport booking marker in the description
- Booking start/end time
- Appointment status
- Staff assignment when a verified HighLevel user exists
- Waiver status and waiver URL in the description
- `ignoreFreeSlotValidation: true`
- `toNotify` based on synchronization mode

The booking marker is important because HighLevel's appointment create endpoint does not provide a normal idempotency-key field. If a create request times out, Passport searches the relevant time range for the Passport marker before creating another appointment.

### Synchronization modes

`GHL_SYNC_MODE` supports:

- `outbox`: queue external work and process it asynchronously. This is the current default in `backend/.env.example`.
- `synchronous`: after local booking commit, attempt contact and appointment synchronization immediately, up to three attempts.
- `disabled`: skip the GHL projection path.

The synchronous service is `backend/app/services/ghl_sync_service.py`. It records `ghl_sync_runs` and `ghl_sync_attempts`, retries up to three times, and exposes failed synchronization through Passport notifications/manual resync paths.

### Important current limitation

The clean clone contains migration 036 for synchronous GHL sync state, but it does not contain the later custom-object migration/implementation from the previous local implementation workspace. This clean GitHub clone therefore does **not** currently implement the Passport Booking custom-object projection.

## 4. Why the system is slow

### A. The database pool is deliberately limited to one connection

`backend/app/core/database.py` configures:

- `pool_size=1`
- `max_overflow=0`
- `pool_timeout=10`

That means each backend process can use only one PostgreSQL connection. If several requests arrive together, they wait in line. This is likely the biggest general reason that unrelated features feel slow.

This setting was intended to protect a serverless/session-pooler deployment, but it also serializes dashboard queries, availability checks, webhooks, and background work inside the same process.

### B. HighLevel calls can run synchronously in a request

Examples:

- If `GHL_SYNC_MODE=synchronous`, booking creation calls `GHLSyncService.sync_order()` after committing the booking.
- A synchronous run may perform contact sync, calendar sync, appointment sync, staff lookup, and owner updates.
- It can make up to three attempts with waits of 0.5 and 1.0 seconds between retries.
- Calendar/configuration mutations often queue work and then immediately drain some outbox jobs in the same request.
- Staff assignment routes also invoke inline outbox processing.

This makes the user wait for HighLevel network latency even though the Passport booking itself is already safely committed.

### C. Stripe webhook requests process outbox jobs inline

`backend/app/api/v1/stripe_webhooks.py` processes the Stripe event and then calls:

`OutboxService(db, settings).process(limit=100, prefer_newest=True)`

That means a Stripe webhook request can perform up to 100 additional external jobs before returning. Those jobs may include Stripe transfers, GHL contact sync, GHL appointments, invoice work, refunds, or other provider calls.

This is a major latency and reliability risk. Webhooks should acknowledge quickly after durable local processing and let a worker drain external jobs separately.

### D. The frontend polls frequently

Current examples:

- Confirmation page polls order status every 2 seconds until the order is confirmed or reaches an exception state.
- Public calendar availability polls every 5 seconds.
- Staff booking availability polls every 30 seconds.
- Notifications poll every 15 seconds.
- The application shell also polls notifications every 15 seconds, so the same endpoint can be requested by both the shell and the Notifications page.
- Staff data and conflict data also refresh at intervals.

Polling is useful for freshness, but with one database connection it creates a constant queue of competing requests.

### E. Notifications perform additional per-booking queries

`NotificationService._booking_items()` loads up to 200 bookings and then calls `readiness_for_booking()` and loads staff assignments for each booking. That can become an N+1 pattern as the number of bookings grows.

`NotificationService._ghl_sync_items()` separately queries the first booking for each failed sync run. Many unresolved failures can therefore create many additional queries.

### F. One GHL appointment sync can call several other services

Appointment sync can:

1. Synchronize the calendar.
2. Find/create the appointment mapping.
3. Synchronize the contact if necessary.
4. Check staff readiness.
5. Check the verified HighLevel staff user.
6. Update the contact owner.
7. Query assigned staff names.
8. Create/update/reconcile the appointment.

This is correct from a consistency perspective, but it is expensive when executed inline or repeatedly.

### G. The frontend production bundle is large

The production build succeeds, but Vite reports a JavaScript chunk of about 912 KB before gzip. This does not explain slow backend API calls, but it can make the initial app load slower, especially inside the embedded HighLevel iframe.

## 5. Current verification result

### Backend

The non-database backend suite completed successfully in the sandbox. Database integration tests were skipped because no disposable PostgreSQL test database was configured.

Therefore, the result verifies Python/service behavior that does not require a live database, but it does not prove production schema/query performance.

### Frontend

The clean clone passed:

- TypeScript typecheck
- Booking notification helper test
- Production Vite build

The production build emitted only the bundle-size warning described above.

## 6. Recommended order of fixes

### Priority 1 — remove provider work from request/webhook latency

- Do not call `OutboxService.process(limit=100)` inside the Stripe webhook route.
- Keep the webhook transaction short and return after local event processing is durable.
- Let the worker process transfer, GHL, invoice, refund, and reversal jobs.
- Keep synchronous GHL mode disabled for production booking creation unless immediate consistency is absolutely required.

### Priority 2 — fix the database connection strategy

- Measure actual concurrent request volume and Supabase pooler mode.
- Use a small safe pool per process instead of exactly one connection, or move to a dedicated worker/API deployment with separate pool budgets.
- Do not allow long provider calls to hold a database connection.
- Add request timing and pool-wait metrics before changing pool sizes.

### Priority 3 — reduce polling and duplicate queries

- Share one notifications query between the shell badge and Notifications page.
- Replace fixed polling with invalidation after mutations where possible.
- Use slower polling when the page is hidden.
- Increase availability polling intervals or use a booking/slot push mechanism.
- Batch notification readiness and staff-assignment queries.

### Priority 4 — separate synchronization responsibilities

For the desired future design:

- Passport remains authoritative for booking, availability, waivers, payment, and staff reminders.
- HighLevel receives the contact and appointment projection.
- HighLevel workflows send customer email/SMS after the appointment/contact projection is ready.
- Passport continues to send staff reminders directly, using its own worker/cron.
- A custom inbound workflow trigger can be added later if HighLevel must receive a full booking payload, but the current clone does not yet have that trigger endpoint.

### Priority 5 — verify the invoice mode edge case

In `backend/app/services/order_service.py`, the invoice job is added under `elif invoice_mode` after the `if ghl_sync_mode == "outbox"` branch. If `GHL_SYNC_MODE=synchronous` and a booking uses invoice payment, the invoice job is not added by this branch. The deployed mode should be checked immediately, and this branch should be covered by an integration test before changing modes.

## Bottom line

The current application is functionally comprehensive, but it mixes three different workloads in the same execution path:

- Fast booking/database work
- Slow external provider calls
- Repeated polling/read-model work

The safest performance fix is to make web requests and Stripe webhooks persist local state only, acknowledge quickly, and let dedicated workers handle GHL/Stripe side effects. The database pool and frontend polling should then be tuned using real timing metrics rather than increasing timeouts blindly.
