# Passport

Passport is a multi-tenant rental scheduling platform embedded in a
GoHighLevel Marketplace Custom Page. PostgreSQL is authoritative for calendars,
inventory, customer-type rates, bookings, payments, waivers, and booking
policies. GoHighLevel is used only for installation, embedded-user identity,
the contacts required by appointments, calendar/appointment synchronization,
and staff identity synchronization.

The repository is split into independently deployable applications:

- `backend/` — FastAPI on Vercel, SQLAlchemy 2, Supabase PostgreSQL
- `frontend/` — Vite, React, TypeScript, Tailwind, FullCalendar, Stripe.js
- `supabase/migrations/` — the only authoritative database schema history
- `docs/` — architecture, integration, deployment, and operational guidance

## Implementation sequence

1. Foundation: schema, models, validation, configuration, crypto, and database.
2. GHL Marketplace trust chain: OAuth, encrypted user context, local sessions.
3. Tenant-scoped configuration CRUD and transactional soft-deletion.
4. Availability and shared-resource capacity calculation.
5. Concurrency-safe order holds and booking administration.
6. Embedded administration interface.
7. Public booking and multi-occurrence checkout.
8. Stripe Connect onboarding.
9. Payments, verified webhooks, transfers, and refund foundation.
10. Reliable Passport-owned booking and payment workflows with minimal GHL projection.
11. Deployment hardening and QA.

See [Architecture](docs/architecture.md) for the entity graph, trust boundaries,
and specification decisions.

## Production rollout: staff users and booking notifications

Migration `supabase/migrations/012_staff_ghl_users.sql` is mandatory before
deploying the staff-user and Booking Notifications backend code. It adds the
GHL-user columns selected by the `Staff` model and registers the
`ghl_sync_staff_user` outbox job type. Apply it to the production Supabase
database first, then deploy the backend and frontend. If the application is
deployed before this migration is applied, `GET /api/v1/booking-notifications`
and `POST /api/v1/staff` can fail with HTTP 500 because PostgreSQL cannot find
the new `staff.ghl_user_*` columns.

Keep `GHL_STAFF_USER_SYNC_ENABLED=true` after the migration is applied and the
HighLevel Marketplace app has `users.readonly`. Reinstall or reauthorize the
app in each sub-account so the installation stores that scope. The Staff page
then imports existing account users from the sub-account and stores their GHL
user IDs locally; Passport does not create duplicate GHL users. Roles are
assigned per booking time slot, so the same person can have different roles on
different bookings and multiple staff members can share a role. If the scope
is missing, the local roster remains visible and shows a sync error instead of
silently failing.

Migration `supabase/migrations/013_staff_custom_roles.sql` is also mandatory
for the Passport-owned role layer. Apply migration 012 first, then 013, before
deploying this version. The Staff page does not edit GHL names, email, phone,
permissions, or account status. It only stores `staff.custom_role` in Passport.
The Staff sidebar badge and highlighted rows identify synced GHL staff without
a custom role. Booking staff selectors use that Passport role as their source
of truth and show only matching staff.

Migration `supabase/migrations/014_staff_ghl_availability.sql` is required for
the GHL availability cache, and `supabase/migrations/015_staff_pool_two_week_availability.sql`
adds calendar staff pools plus concrete rolling availability windows. Apply both
after 013 and before deploying this version. The Staff page requests the
`calendars.readonly` schedule APIs on every directory refresh, stores the weekly
schedule for display, and expands each linked GHL user's schedule into the next
14 days of UTC intervals. The protected daily cron refreshes those windows
automatically; the Staff page and assignment tools use them for operational
staffing information, but they do not block public booking slots.
Passport cannot edit GHL-managed staff details or availability.

Migration `supabase/migrations/018_customer_type_rates_and_line_items.sql` is
required for customer-type pricing and resource-aware bookings. It adds
customer types, calendar rates, rate-to-resource mappings, booking line-item
snapshots, and configurable party-size and rate-level fee/tax fields. Apply it
after migration 017 before enabling the Kayak rate editor or public rate-aware
checkout.

Migration `supabase/migrations/019_calendar_bookability_policy.sql` adds
Passport-owned `online`, `call_to_book`, and `closed` calendar modes plus an
optional booking cutoff. Apply it after migration 018. GHL calendar hours and
staff schedules do not replace these Passport booking rules.

Migration `supabase/migrations/020_fareharbor_replica_core.sql` adds Passport
customer records, immutable booking-policy versions, booking adjustments,
custom booking fields, weather closure records, staged migration imports, and
reconciliation runs. The operator workspace exposes Customers and Migration &
reconciliation sections. Validate an export before committing it; no live
FareHarbor cutover should happen while blocking errors remain.

Migration `supabase/migrations/021_production_booking_hardening.sql` is required
before paid production bookings. It adds participant manifests, append-only
booking and payment event ledgers, hold-expiry and lookup indexes, credential
invariants, booking-total checks, staff-assignment overlap protection, and
append-only database triggers. Apply it after 020 and verify it on a staging
PostgreSQL clone before production.

Migration `supabase/migrations/024_resource_metadata_repair.sql` repairs older
databases whose `resources` table still lacks `resource_type`, `capacity_limit`,
or `notes`. It is idempotent and should be applied before opening the Resources
page.

Migration `supabase/migrations/025_booking_page_schema_repair.sql` repairs
databases that skipped the customer-rate and checkout migrations. It adds the
calendar party/fee/tax columns, customer types, calendar rates, rate-resource
mappings, booking line items, booking financial snapshot columns, and the
booking-order marketing flag. Apply it before opening the Booking page.

If the frontend and backend are deployed as separate Vercel projects, set the
frontend production variable `VITE_API_BASE_URL` to the backend URL ending in
`/api/v1`. Leaving it unset makes the production frontend call its own Vercel
site for `/api/v1`, which produces the same generic Booking-page request error.

The detailed API contract and GHL integration boundary are documented in
`docs/FAREHARBOR_REPLICA_IMPLEMENTATION_SPEC.md`.

Calendar editors can configure one or more independent staff pools for
assignment and GHL ownership. Existing calendars default to `Captain`; these
pools no longer make a booking slot unavailable when a staff member or role is
unavailable. Calendar hours, blocks, duration, and resource inventory remain
the booking availability rules.
The fixed custom-role dropdown contains only Captain, First Mate, Guide, Deckhand,
and Instructor.

For near-real-time synchronization, run `python worker.py` from the `backend/`
directory on an always-on worker service. It performs a complete GHL directory
and availability reconciliation every `GHL_STAFF_SYNC_INTERVAL_SECONDS` seconds
(15 by default), keeps removed GHL users inactive locally, and preserves their
historical bookings. Vercel cannot keep a persistent 10–15-second process alive;
its protected daily cron remains a fallback reconciliation mechanism only. Set
the same production environment variables on the worker as on the API, including
`DATABASE_URL`, the encrypted GHL credentials, `GHL_STAFF_USER_SYNC_ENABLED`,
`GHL_STAFF_SYNC_INTERVAL_SECONDS`, and the production secrets.

The same worker expires pending-payment holds on every loop. Expired holds are
transitioned locally, public access credentials are revoked, booking events are
recorded, and idempotent GHL appointment-cancellation jobs are queued. The
protected `/api/v1/internal/cron/daily` endpoint performs the same sweep as a
fallback, but an always-on worker remains the required primary lifecycle
process.

Calendar, resource, availability, and booking endpoints commit Passport data and
enqueue GHL work without waiting for external HTTP requests. This keeps the user
response fast; the worker must be running for queued GHL calendar, contact, staff,
and appointment jobs to be applied promptly. GHL notifications are disabled by
default through `GHL_NOTIFICATIONS_ENABLED=false`; Passport remains the owner of
customer communication unless that flag is intentionally enabled. The final booking validation remains
inside the database transaction, so asynchronous synchronization does not allow
an invalid or duplicate booking.

## Production database connection behavior

The API and worker each create one SQLAlchemy engine per running process with a
single pooled database connection and no overflow connections. GHL token refreshes
reuse the request or worker session instead of opening a nested database session.
This prevents `QueuePool limit ... overflow ... reached` errors on deployments with
a limited database connection budget. A serverless deployment can still have one
connection per simultaneously warm Vercel instance; this setting limits each
process, not the entire distributed platform. Use the Supabase pooler URL in
`DATABASE_URL` and keep only one persistent staff worker process running.
