# Passport Staff PWA — Mobile Stability Release

**Release purpose:** make the installed Passport Staff PWA reliable on iPhone and Android without changing existing Passport booking, calendar, payment, waiver, staff, or desktop workflows.

## What changed

- **Persistent, revocable mobile login:** A staff member’s Passport PWA session now survives an installed-app restart for up to 31 days. The browser keeps only a host-only, HTTP-only recovery cookie; the short-lived API token stays in memory.
- **Immediate logout/revocation:** Every PWA device session is stored in `pwa_sessions`. Selecting **Sign out**, removing a user’s Passport membership, disabling an operator, or changing the installation authorization version takes effect immediately.
- **Refresh-token rotation:** Every successful PWA refresh changes the server-side nonce. An old recovery cookie cannot be used after rotation.
- **Same-origin guard:** The Staff PWA clearly rejects a separately hosted production API configuration, rather than appearing to log in and then losing its cookie on mobile. The root Vercel configuration must proxy `/api/v1` to the backend.
- **No stale reload loop:** The service worker gets a new cache name on each build, precaches the exact Vite production assets and PWA icons, avoids caching redirects/failed navigation HTML, and is delivered with no-cache headers.
- **Lower phone load:** Availability refreshes every 20 seconds only when the browser is visible; cart updates are safe against rapid taps; and Stripe webhooks return after their durable write instead of waiting for outbox processing.
- **Mobile sign out:** The standalone Passport PWA sidebar now includes **Sign out**. It is not shown in the embedded HighLevel iframe.

## Required deployment step

Run **all unapplied Supabase migrations in order**. For this release, the new required migration is:

```sql
supabase/migrations/039_pwa_sessions.sql
```

Or run the complete deployment bundle:

```sql
DATABASE_MIGRATIONS_TO_RUN.sql
```

The backend readiness endpoint will intentionally report the database as not ready until the `039_pwa_sessions` schema marker and `pwa_sessions` table exist.

## Required Vercel configuration

Use the repository-root Vercel project and its root `vercel.json` so the browser sees both frontend and API at one origin:

```text
https://your-passport-domain.example/app
https://your-passport-domain.example/api/v1/...
```

In the production **frontend** environment, leave `VITE_API_BASE_URL` unset. Set `VITE_PWA_APP_URL` to the Passport domain, without `/app`:

```text
VITE_PWA_APP_URL=https://your-passport-domain.example
```

Keep the existing backend values, especially `APP_SESSION_SECRET`, `PWA_SESSION_MINUTES=44640`, `FRONTEND_URL`, and `CORS_ORIGINS`, aligned with that same Passport domain.

## Smoke test after deployment

1. Open `https://your-passport-domain.example/app` in Safari (iPhone) or Chrome (Android), not within a HighLevel page.
2. Confirm the browser loads a Passport page and the install instructions appear.
3. Install it: **Safari Share → Add to Home Screen** or **Chrome menu → Install app/Add to Home screen**.
4. Open the installed icon, complete the HighLevel login once, and confirm it returns to Passport.
5. Force-close the installed app, reopen it, and confirm it restores the Passport session without asking for HighLevel login.
6. Use **Sign out**, reopen the app, and confirm it correctly requires login again.
7. On another test booking, verify the public booking page can add/remove a quantity on a phone and completes Stripe’s test payment path.
8. In Stripe test mode, deliver a webhook and confirm it returns HTTP 2xx promptly; the worker then processes the queued GHL/financial jobs.

## Validation completed locally

- Complete non-database backend regression suite passed (database-integrated tests remain skipped without a configured PostgreSQL test database).
- PWA authentication and migration contract tests passed.
- Frontend TypeScript check passed.
- Existing booking-notification and money-conversion tests passed.
- Production frontend build passed.
- Generated service worker verified to include 74 build/icon shell assets, an immutable build-specific cache name, and SPA fallback output.
- Root and frontend Vercel configuration JSON validated.

## Remaining external checks before a full live launch

A real-device test on your production domain is still necessary because iOS installation, cookie storage, and HighLevel OAuth redirects depend on Safari, your Vercel domain, and the HighLevel app configuration. A full Stripe Connect test should use Stripe test-mode connected accounts and Stripe CLI/dashboard webhook delivery before switching any account to live mode.
