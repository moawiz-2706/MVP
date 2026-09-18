# Passport

Passport is a multi-tenant rental scheduling platform embedded in a
GoHighLevel Marketplace Custom Page. PostgreSQL is authoritative for calendars,
inventory, bookings, and payments. GoHighLevel is used only for installation,
embedded-user identity, Contacts, and confirmation email delivery.

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
10. Reliable GHL contact and confirmation-email jobs.
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
