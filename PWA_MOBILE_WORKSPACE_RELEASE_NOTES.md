# Passport Mobile Workspace — Release Notes

## What this release adds

This release upgrades the existing Passport app into a faster, more phone-friendly Staff Operations PWA. It does **not** create a second product or a separate backend.

- **Mobile Home (`/app`)**: today’s bookings, the next seven days, pending payments, pending waivers, unassigned bookings, staff conflicts, failed HighLevel synchronizations, and direct quick actions.
- **Universal Passport search**: search bookings, customers, calendars, staff, payment references, waivers, and Passport internal notes from the global search button or `Ctrl/Cmd + K`.
- **Phone-friendly workspace**: the established mobile booking agenda and calendar cards remain in place; Customers and Staff now have touch-friendly cards instead of requiring a wide table. The existing booking drawer, customer drawer, role editor, calendar editor, staff availability, and private booking-link controls remain the same underlying features.
- **More responsive loading**: every route is now code-split. The large FullCalendar code is loaded only when a person opens Bookings, rather than during the initial PWA launch.
- **Less unnecessary provider activity**: the Staff page now displays Passport’s stored staff directory immediately. A user deliberately selects **Sync GHL staff** when a fresh HighLevel directory/availability sync is needed. Background page polling is foreground-only and uses a longer interval.
- **Mobile resilience**: the app has an offline state, install prompt/help, persistent theme preference, and a bumped service-worker cache version so phones receive this release after deployment.

## One project, not a separate PWA project

Keep the existing Passport frontend and backend deployment. The PWA is built from `frontend/` in this same repository and uses the same Passport API. You do **not** need to make a new Vercel project or a second backend project for this release.

The production mobile app must be installed from the Passport frontend origin (for example, `https://mvp-one-hazel.vercel.app/app`) — never from a HighLevel/LeadConnector domain. Installing a HighLevel domain installs the HighLevel site, not Passport.

## Required database change

Run the forward-only migration below against the same Supabase/PostgreSQL database used by Passport **before** deploying the backend that has this release:

```sql
-- Run this file in order if migrations 035–037 are not already deployed:
DATABASE_MIGRATIONS_TO_RUN.sql

-- If your database already has 035_schema_reconciliation,
-- 036_ghl_sync_state, and 037_pwa_auth_handoffs, run only:
supabase/migrations/038_pwa_workspace_performance.sql
```

Migration `038_pwa_workspace_performance` adds only indexes and a schema-version marker. It does not delete or alter booking, payment, waiver, customer, staff, or calendar data.

After running it, confirm:

```sql
SELECT version
FROM public.passport_schema_version
WHERE version = '038_pwa_workspace_performance';
```

## Deployment checklist

1. Back up the production database as part of the normal release procedure.
2. Run the database migration above.
3. Deploy the backend and frontend from the same commit.
4. Confirm `GET /api/readiness` reports `schema_version: 038_pwa_workspace_performance`.
5. Visit `https://YOUR_PASSPORT_DOMAIN/app` in a normal mobile browser and complete the existing Passport/HighLevel sign-in flow.
6. On iPhone Safari, use **Share → Add to Home Screen**. On Android Chrome, use the browser menu’s **Install app** option. The PWA’s install help is also available on the sign-in screen.
7. After the frontend deploy, fully close and reopen the installed PWA once. The versioned `sw.js` cache will replace its old app shell.
8. Smoke-test: Home dashboard, global search, Bookings, new-booking quick action, one customer card, one staff card, calendar edit, and the manual **Sync GHL staff** action.

## Git push

The delivery archive includes the `.git` directory and a commit on `main`. Extract it, open that extracted folder in VS Code or a terminal, then run:

```bash
git status
git log --oneline -5
git push -u origin main
```

A successful `git status` must say `On branch main`; if it says the folder is not a Git repository, you opened the parent folder rather than the extracted repository root.

## Deliberate scope boundaries

This release preserves the current Passport functionality and adds a mobile operations layer. It does not silently add risky financial actions (manual payments/refunds), participant status policies, customer data ownership rules, or a duplicated GHL conversation inbox. Those require separate product and compliance decisions before implementation.
