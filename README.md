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

Set `GHL_STAFF_USER_SYNC_ENABLED=false` during the initial migration rollout.
After the migration and deployment are healthy, add `users.readonly` and
`users.write` to the HighLevel Marketplace app, reinstall or reauthorize the
app in each sub-account, and then set `GHL_STAFF_USER_SYNC_ENABLED=true`.
Existing staff records are not automatically assigned a HighLevel login until
they are retried from the Staff page.
