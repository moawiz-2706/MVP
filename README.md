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

