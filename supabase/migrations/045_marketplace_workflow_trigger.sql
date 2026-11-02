-- HighLevel Marketplace Workflow Custom Trigger runtime (passport_booking_created).
-- Additive and safe to re-run. Apply BEFORE setting GHL_WORKFLOW_TRIGGER_ENABLED=true;
-- with the flag off (the default) no booking path touches these tables.
--
-- 1. ghl_workflow_trigger_subscriptions: one row per workflow trigger instance
--    HighLevel registers through the Subscription URL (CREATED / UPDATED /
--    DELETED). The execution targetUrl is stored encrypted, never in plain text.
-- 2. ghl_workflow_trigger_events: one row per logical Passport booking event,
--    unique by idempotency key, so a Stripe redelivery or outbox retry never
--    creates a second event.
-- 3. ghl_workflow_trigger_deliveries: one row per (event, subscription), with
--    attempt count, last HTTP status and a redacted error.
-- 4. Outbox job type 'ghl_workflow_trigger'.
--
-- Rollback (set GHL_WORKFLOW_TRIGGER_ENABLED=false and deploy first):
--   DROP TABLE IF EXISTS public.ghl_workflow_trigger_deliveries;
--   DROP TABLE IF EXISTS public.ghl_workflow_trigger_events;
--   DROP TABLE IF EXISTS public.ghl_workflow_trigger_subscriptions;
--   (re-apply the job type list from 043_attribution_checkin_intent_cancel.sql)
--   DELETE FROM public.passport_schema_version WHERE version = '045_marketplace_workflow_trigger';

BEGIN;

CREATE TABLE IF NOT EXISTS public.ghl_workflow_trigger_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  ghl_location_id text NOT NULL,
  ghl_company_id text,
  ghl_workflow_id text NOT NULL,
  ghl_trigger_id text NOT NULL,
  trigger_key text NOT NULL,
  trigger_version text,
  target_url_encrypted text NOT NULL,
  filters jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'active',
  last_callback_event text NOT NULL,
  last_callback_hash text NOT NULL,
  last_callback_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ghl_workflow_trigger_subscriptions_status_valid CHECK (status IN ('active', 'deleted')),
  CONSTRAINT ghl_workflow_trigger_subscriptions_event_valid
    CHECK (last_callback_event IN ('CREATED', 'UPDATED', 'DELETED')),
  CONSTRAINT uq_ghl_workflow_trigger_subscription
    UNIQUE (ghl_location_id, ghl_workflow_id, ghl_trigger_id)
);
CREATE INDEX IF NOT EXISTS ix_ghl_workflow_trigger_subscriptions_operator_status
  ON public.ghl_workflow_trigger_subscriptions (operator_id, status);

CREATE TABLE IF NOT EXISTS public.ghl_workflow_trigger_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  booking_order_id uuid NOT NULL REFERENCES public.booking_orders(id),
  event_type text NOT NULL,
  event_id text NOT NULL,
  idempotency_key text NOT NULL,
  occurred_at timestamptz NOT NULL,
  snapshot jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending',
  last_error text,
  delivered_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ghl_workflow_trigger_events_type_valid
    CHECK (event_type IN ('booking_created', 'payment_confirmed', 'booking_updated', 'booking_cancelled')),
  CONSTRAINT ghl_workflow_trigger_events_status_valid
    CHECK (status IN ('pending', 'delivered', 'partially_delivered', 'failed', 'no_subscriber')),
  CONSTRAINT uq_ghl_workflow_trigger_events_idempotency_key UNIQUE (idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_ghl_workflow_trigger_events_order
  ON public.ghl_workflow_trigger_events (booking_order_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ghl_workflow_trigger_events_operator_status
  ON public.ghl_workflow_trigger_events (operator_id, status);

CREATE TABLE IF NOT EXISTS public.ghl_workflow_trigger_deliveries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  operator_id uuid NOT NULL REFERENCES public.operators(id),
  event_id uuid NOT NULL REFERENCES public.ghl_workflow_trigger_events(id) ON DELETE CASCADE,
  subscription_id uuid NOT NULL REFERENCES public.ghl_workflow_trigger_subscriptions(id),
  status text NOT NULL DEFAULT 'pending',
  attempt_count integer NOT NULL DEFAULT 0,
  last_http_status integer,
  last_error text,
  last_attempt_at timestamptz,
  delivered_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ghl_workflow_trigger_deliveries_status_valid
    CHECK (status IN ('pending', 'delivered', 'retrying', 'failed', 'filtered')),
  CONSTRAINT ghl_workflow_trigger_deliveries_attempts_nonnegative CHECK (attempt_count >= 0),
  CONSTRAINT uq_ghl_workflow_trigger_delivery UNIQUE (event_id, subscription_id)
);
CREATE INDEX IF NOT EXISTS ix_ghl_workflow_trigger_deliveries_operator_status
  ON public.ghl_workflow_trigger_deliveries (operator_id, status);

ALTER TABLE public.outbox_jobs DROP CONSTRAINT IF EXISTS outbox_jobs_job_type_check;
ALTER TABLE public.outbox_jobs
  ADD CONSTRAINT outbox_jobs_job_type_check CHECK (job_type IN (
    'stripe_create_transfer',
    'stripe_create_invoice',
    'ghl_upsert_contact',
    'ghl_send_confirmation_email',
    'ghl_booking_reminder',
    'ghl_upsert_staff_contact',
    'ghl_staff_assigned_email',
    'ghl_staff_reminder',
    'ghl_staff_unassigned_email',
    'ghl_booking_cancellation_email',
    'ghl_booking_weather_email',
    'ghl_booking_reschedule_email',
    'stripe_create_refund',
    'stripe_create_adjustment_refund',
    'stripe_create_transfer_reversal',
    'stripe_reconcile_payment_intent',
    'stripe_cancel_payment_intent',
    'ghl_sync_staff_user',
    'ghl_sync_calendar',
    'ghl_delete_calendar',
    'ghl_sync_appointment',
    'ghl_cancel_appointment',
    'ghl_workflow_trigger'
  ));

-- Server-side only: the browser never reads these tables (041 keeps RLS on).
ALTER TABLE public.ghl_workflow_trigger_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghl_workflow_trigger_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ghl_workflow_trigger_deliveries ENABLE ROW LEVEL SECURITY;

INSERT INTO public.passport_schema_version(version)
VALUES ('045_marketplace_workflow_trigger')
ON CONFLICT (version) DO NOTHING;

COMMIT;
