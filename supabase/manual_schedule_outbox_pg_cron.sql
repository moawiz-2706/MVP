-- Run Passport's outbox every minute with Supabase's built-in scheduler.
--
-- pg_cron and pg_net are included free on every Supabase plan. This replaces
-- the GitHub Actions runner (.github/workflows/process-outbox.yml), which is
-- not running while the GitHub account is billing-locked.
--
-- HOW TO RUN (Supabase dashboard → SQL Editor):
--   1. Replace PASTE_CRON_SECRET_HERE with the exact CRON_SECRET value set on
--      the Vercel backend. It is stored encrypted in Supabase Vault and is
--      never written to this file or to source control.
--   2. Run the whole script once.
--   3. Check it with the verification queries at the bottom.
--
-- Each call expires abandoned payment holds (once the hold-expiry change is
-- deployed), then processes up to 20 outbox
-- jobs (HighLevel sync, confirmation emails, Stripe transfers/refunds/invoices).
-- Jobs use leases, so an overlap with the daily Vercel cron is safe.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Store the secret once. To change it later:
--   select vault.update_secret(
--     (select id from vault.secrets where name = 'passport_cron_secret'),
--     'NEW_VALUE');
select vault.create_secret('PASTE_CRON_SECRET_HERE', 'passport_cron_secret');

select cron.schedule(
  'passport-process-outbox',
  '* * * * *',
  $$
  select net.http_post(
    url := 'https://mvp-one-hazel.vercel.app/api/v1/internal/process-outbox',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (
        select decrypted_secret from vault.decrypted_secrets
        where name = 'passport_cron_secret'
      ),
      'Content-Type', 'application/json'
    ),
    timeout_milliseconds := 60000
  );
  $$
);

-- VERIFY (run a few minutes later):
--   select jobname, schedule, active from cron.job;
--   select status, return_message, start_time
--     from cron.job_run_details order by start_time desc limit 5;
--   select status_code, left(content::text, 200), created
--     from net._http_response order by created desc limit 5;
--   -- expect status_code 200 and a JSON body of job counts. "expired_holds"
--   -- appears only once the hold-expiry change is deployed.
--   -- 401 means the Vault secret does not match Vercel's CRON_SECRET.
--
-- DISABLE:
--   select cron.unschedule('passport-process-outbox');
