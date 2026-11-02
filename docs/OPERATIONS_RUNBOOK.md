# Passport Operations Runbook

Operational procedures for the production Passport deployment (Vercel plus Supabase project `quektyyqhzzyibozeyof`). Every step that writes to production requires explicit owner authorization.

## 1. Background job runner (outbox)

Customer confirmations, HighLevel contact and appointment sync, Stripe transfers, invoices, refunds and hold expiry are durable `outbox_jobs` rows. They are only applied when something calls a runner:

| Runner | Frequency | State on 2026-11-02 |
|---|---|---|
| GitHub Actions `process-outbox.yml` → `POST /api/v1/internal/process-outbox` | every 5 min | **Not running.** The GitHub account is locked because of a billing issue, and the last 100 runs failed before starting. |
| Vercel cron → `GET /api/v1/internal/cron/daily` | once a day, 11:00 UTC | Running. This is currently the only runner. |
| `backend/worker.py` (long-running) | every 10–60 s | Not deployed |

`/api/readiness` (production mode) now warns when jobs are overdue by more than 15 minutes. Tables without RLS are reported in the server logs only.

**Fix (pick one):**

1. **Resolve the GitHub billing lock.** The existing workflow resumes with no code change. Vercel and GitHub do not guarantee exact 5-minute timing.
2. **Supabase pg_cron + pg_net (no extra hosting, free on all plans; chosen 2026-11-02).** The ready-to-run script is `supabase/manual_schedule_outbox_pg_cron.sql`. In outline:

   ```sql
   create extension if not exists pg_cron;
   create extension if not exists pg_net;
   select vault.create_secret('<CRON_SECRET value>', 'passport_cron_secret');
   select cron.schedule(
     'passport-process-outbox',
     '* * * * *',
     $$
     select net.http_post(
       url := 'https://<passport-domain>/api/v1/internal/process-outbox',
       headers := jsonb_build_object(
         'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'passport_cron_secret'),
         'Content-Type', 'application/json'
       ),
       timeout_milliseconds := 60000
     );
     $$
   );
   ```

   To disable it: `select cron.unschedule('passport-process-outbox');`
3. **An always-on worker** (Railway, Render, Fly.io and similar) running `python worker.py` with the production environment. This is the lowest-latency option. It also runs the GHL staff directory sync.

`process-outbox` also expires abandoned payment holds on every run, so any of these options keeps holds and HighLevel cancellations current.

## 2. Pending migrations: apply order

Migrations are applied by hand in the Supabase SQL editor, one file at a time, in numeric order. Each file is wrapped in a transaction and writes its marker to `passport_schema_version`.

As of 2026-11-02, production has markers through `039_pwa_sessions`, **except `038`**. Apply in this order:

1. `038_pwa_workspace_performance.sql`: adds 3 indexes (additive).
2. `040_booking_adjustment_refunds.sql`: widens the outbox job-type check. **Required by the deployed code**; without it, paid quantity decreases cannot queue their refund.
3. `041_enable_row_level_security.sql`: blocks Supabase Data API access to all public tables. The rollback SQL is in the file header.
4. `042_pwa_refresh_grace.sql`: adds two nullable columns to `pwa_sessions`. **Must be applied before deploying the code that needs it**; that code's readiness marker is `042`.

5. `043_attribution_checkin_intent_cancel.sql`: booking creator and source columns, participant check-in columns, and the `stripe_cancel_payment_intent` job type. **Apply it before deploying the code that needs it** (readiness marker `043`). Run the file as-is in the SQL editor; it is idempotent.

`038`–`042` were combined, with the owner-approved voiding of two test payments, in `supabase/manual_2026-11-02_production_apply.sql`. That script was tested on a local copy in production's exact migration state, and is idempotent.

**Before applying:** take a backup (Supabase dashboard → Database → Backups, or `pg_dump`). Run each file against a staging copy first.

**Verify afterwards:**

```sql
select version from passport_schema_version order by 1;
select count(*) from pg_tables where schemaname = 'public' and not rowsecurity;  -- expect 0
```

Then check that `/api/readiness` reports `"status":"ready"`, and that the PWA and desktop pages load.

## 3. Production mode

The production API reports `"environment":"non-production"`. Set `ENVIRONMENT=production` in the Vercel backend service **only after** the migrations above are applied and every variable listed in `Settings.validate_runtime` is set. Otherwise the API will refuse to start, by design. Setting it turns on startup validation and the DB readiness contract.

Independently of that variable, cookies are now marked `Secure` on any HTTPS or Vercel-production deployment.

## 4. Reconciliation items found on 2026-11-02

Do these in Stripe **test or live mode, as appropriate**, with owner approval:

- **Two `payment_intent.succeeded` webhooks failed** (2026-09-25 00:35 UTC and 2026-09-30 16:09 UTC) because of a bug that has since been fixed, and were never reprocessed. Stripe can only resend events from the last 30 days, so **Resend is no longer available** for these two. Use Passport's own reconciliation instead: queue one `stripe_reconcile_payment_intent` outbox job per affected payment (payload `{"payment_id": "<uuid>"}`, with a unique `idempotency_key`). That job reads the PaymentIntent from Stripe and applies the same idempotent success handling: it confirms the booking if capacity still fits, and otherwise queues a refund. The 2026-09-30 booking is already `cancelled`, so reconciling it **queues a refund**. Confirm that this is the desired outcome before running it.
- **Five card bookings are stuck in `pending_payment`** with long-expired holds (payment status `processing`, meaning the PaymentIntent was created but never paid). They do not hold inventory. Once this branch is deployed, the next outbox run releases them and queues a Stripe PaymentIntent cancel for each. No manual action is needed.
- **Dead HighLevel jobs.** `ghl_sync_appointment` and `ghl_sync_calendar` are failing against a HighLevel calendar that was deleted in HighLevel. Re-link or re-create the calendar from Passport → Calendars, then retry from Notifications.
- **Missing scope.** One reminder failed because the installation lacks `conversations/message.write`. Reauthorize the Marketplace app with that scope, or move customer messages to HighLevel workflows (Phase 7).

## 5. Row Level Security

Until `041` is applied, every public table is readable and writable by anyone holding the project's anon key. Rotate the anon key (Supabase → Settings → API) if it has ever been shared.
