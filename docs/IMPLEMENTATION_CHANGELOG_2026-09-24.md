# Passport Fresh-Clone Implementation Changelog

## Baseline and branch

The repository was freshly cloned from the latest GitHub `main` branch and placed on `feat/production-fareharbor-ready`. The branch retains the latest remote GHL commits and cherry-picks the previously developed Passport customer-type, FareHarbor-replica, migration, and frontend CRUD work before adding this hardening increment.

## Implemented changes

The merged branch now includes Passport-owned customer types, rate plans, rate-to-resource mappings, itemized booking line snapshots, party-size validation, booking fee and tax components, bookability modes, cutoff enforcement, public custom fields, customer operations, staged migration imports, reconciliation workspace, and the professional operator CRUD screens documented in `docs/FRONTEND_CRUD_MATRIX.md`.

This increment adds a persistent reservation lifecycle service. It locks eligible pending-payment bookings, rechecks payment state, expires stale holds, records append-only booking events, revokes public status credentials, changes the local order to `expired` when no active booking remains, and queues an idempotent GHL appointment cancellation. The always-on `backend/worker.py` runs the sweep continuously and the protected daily cron runs it as a fallback.

Public order status now authenticates the purpose-bound status credential before optional Stripe reconciliation. The admin calendar booking modal and operator-created booking flow preserve that credential through Stripe confirmation. The frontend production API client uses same-origin `/api/v1` when a production build has no explicit API base, so localhost is not silently shipped.

The GHL installation contract no longer requests `conversations/message.write`. GHL confirmation, booking-reminder, and staff-email jobs are disabled by default and become no-ops unless the separately controlled `GHL_NOTIFICATIONS_ENABLED` switch is deliberately enabled. Calendar, appointment, contact, and staff synchronization remain independent capabilities.

Stripe provider-unknown reconciliation can search PaymentIntents by immutable booking-order metadata and will attach a candidate only after validating the local order ID, amount, and currency. The booking operator UI now exposes participant manifest CRUD, while checkout automatically seeds the primary customer as participant one.

Migration `021_production_booking_hardening.sql` adds participant, booking-event, and payment-event tables; required indexes; credential and money checks; staff assignment range exclusion; and append-only database triggers. The full ordered migration chain 001–021 was applied successfully to a disposable PostgreSQL database named `passport_migration_verify`.

## Verification

The focused backend suite passed with 13 tests covering customer-type rates, resource-aware availability, and the FareHarbor-replica core. Python compilation and fatal-error lint passed for all changed backend modules. The frontend passed TypeScript checking and the production Vite build; the build emitted only the existing chunk-size advisory. `git diff --check` passed and a repository scan found no supplied FareHarbor credentials or merge-conflict markers.

## Deployment requirement

This is a migration-ready implementation branch, not permission to bypass staged launch controls. Before live paid traffic, apply migrations 001–021 to staging and production in order, run Stripe test-mode and non-production GHL contract tests, operate the persistent worker, validate public-link/CSP behavior on the deployed domains, run a no-side-effect historical import dry run, and assign ownership for dead-letter, provider-unknown, expiry, refund, waiver, and reconciliation exceptions.
