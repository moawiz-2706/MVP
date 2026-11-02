# Contributing

## Workflow

1. Branch from `main` (`feature/...`, `fix/...`). `main` deploys to production.
2. Keep changes focused; one concern per pull request.
3. Run the full test suite (see the README) and the frontend build before
   opening a pull request. CI runs the same checks.
4. Describe migration and deployment order in the pull request when the
   schema changes.

## Code conventions

- **Routes stay thin.** `app/api/v1/*` handles auth, permissions and request
  validation, then delegates to a service in `app/services/`.
- **Permissions are enforced in the backend** with `require_permission`. Hiding
  a button is never the only control.
- **Money is integer minor units** (cents). Never use floats for amounts.
- **External calls go through the outbox.** Commit Passport's data first, then
  enqueue a job; never call Stripe or HighLevel inside the booking transaction.
- **Idempotency** for anything that can be retried: refunds, transfers,
  messages, webhook handling and closure operations use stable keys.
- **No destructive data paths.** Bookings, payments, waivers and audit events
  are never hard-deleted by application code; archive instead.
- **Logs never contain secrets, card data, waiver signatures or personal data.**

## Database changes

- Add a new numbered file to `supabase/migrations/`; never edit an applied one
  (comments excepted).
- Make it idempotent (`IF NOT EXISTS`, guarded constraints) and end it by
  inserting its marker into `passport_schema_version`.
- Put rollback SQL in the header comment.
- Mirror the change in `backend/app/models/entities.py` and bump
  `REQUIRED_SCHEMA_VERSION` when the code depends on it.
- Add a test to `tests/test_migrated_schema.py` for anything the ORM cannot
  express (constraints, triggers, RLS).

## Frontend

- The embedded HighLevel desktop and the standalone staff PWA share one app.
  Staff-PWA-only screens check `isEmbeddedInHighLevel()`; do not change the
  embedded desktop experience without agreement.
- Use the shared `api()` client and TanStack Query; read permissions through
  `usePwaBootstrap()` / `useHasPermission()`.
