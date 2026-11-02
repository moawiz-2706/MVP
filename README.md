# Passport

Passport is the booking and staff-operations platform for tour and charter
operators, embedded in HighLevel (GoHighLevel) and available to staff as a
standalone mobile PWA.

Passport's PostgreSQL database is the source of truth for calendars, inventory,
rates, bookings, payments, waivers, manifests and staff assignment. HighLevel
supplies installation identity and staff, and receives contacts, calendars and
appointments as a one-way projection. Stripe Connect handles card payments,
invoices, refunds and operator payouts.

## Repository layout

```text
backend/            FastAPI API, SQLAlchemy models, services, background worker
  app/api/v1/       HTTP routes (thin: auth, validation, delegation)
  app/services/     Business logic (booking, payments, availability, sync)
  app/models/       SQLAlchemy entities (mirror the migrations)
  tests/            pytest suite (unit + PostgreSQL integration)
frontend/           React + TypeScript (Vite) app: embedded desktop, staff PWA,
                    public booking pages
supabase/
  migrations/       The authoritative, numbered schema history (apply in order)
  manual/           One-off SQL for the Supabase SQL editor (not migrations)
docs/               Architecture, operations, planning, integrations, history
vercel.json         Single-origin deployment: frontend at /, API at /api
```

## Local development

Requirements: Python 3.12+, Node 20+, PostgreSQL 15+.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env                            # fill in local values
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm ci
cp .env.example .env.local
npm run dev                                      # http://localhost:5173/app
```

## Tests

```bash
cd backend
# Unit and contract tests (no database needed)
.venv/Scripts/python -m pytest

# Full suite: point at disposable databases. Integration tests drop and
# recreate tables in TEST_DATABASE_URL; TEST_MIGRATED_DATABASE_URL must be a
# database built by applying supabase/migrations in order (tests roll back).
TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/passport_test \
TEST_MIGRATED_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/passport_migrations \
  .venv/Scripts/python -m pytest

cd ../frontend
npm run typecheck && npm run test:money && npm run test:booking-notifications && npm run build
```

Never point a test URL at a shared or production database.

## Database migrations

- Every schema change is a new, numbered, idempotent file in
  `supabase/migrations/` that writes its marker to `passport_schema_version`.
- Keep `backend/app/models/entities.py` in sync; `backend/app/core/database.py`
  `REQUIRED_SCHEMA_VERSION` names the migration the code requires.
- Apply migrations to production **before** deploying code that needs them.
  `/api/readiness` reports `not_ready` if the marker is missing.

## Deployment and operations

Pushing to `main` deploys to Vercel production. The API serves `/api/health`
(liveness) and `/api/readiness` (configuration, schema and job-runner health).
A misconfigured deployment stays up but returns 503 for business routes and
names the missing setting in `/api/readiness`.

Background jobs (HighLevel sync, Stripe transfers and refunds, invoices, hold
expiry) run from the `outbox_jobs` table, triggered every minute by Supabase
pg_cron. See the [operations runbook](docs/operations/OPERATIONS_RUNBOOK.md).

## Documentation

| Area | Location |
|---|---|
| Architecture and trust boundaries | [docs/architecture.md](docs/architecture.md) |
| Operations runbook, migrations, incidents | [docs/operations/](docs/operations/) |
| Current plan and backlog | [docs/planning/](docs/planning/) |
| HighLevel and FareHarbor integration notes | [docs/integrations/](docs/integrations/) |
| Feature notes | [docs/features/](docs/features/) |
| Audits and historical plans | [docs/audits/](docs/audits/), [docs/history/](docs/history/) |
| Release notes | [CHANGELOG.md](CHANGELOG.md), [docs/releases/](docs/releases/) |

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.
