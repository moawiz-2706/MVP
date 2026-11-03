-- Marketplace trigger event names aligned with the published v1.0 trigger's
-- Event Type filter options (booking_created, booking_confirmed,
-- booking_rescheduled, payment_updated, booking_cancelled), so workflows that
-- filter on Event Type start for every event Passport sends.
--   payment_confirmed -> booking_confirmed
--   booking_updated   -> booking_rescheduled (time/quantity change) or
--                        payment_updated (refund or extra charge)
-- Additive and safe to re-run. Apply BEFORE deploying the code that sends
-- the new names (that code skips, and logs, any event it cannot store).
--
-- Undelivered events keep their event_id and idempotency_key; only the type
-- they are sent with changes, so a retry passes the workflow's filter.
--
-- Rollback (deploy the previous code first):
--   UPDATE public.ghl_workflow_trigger_events SET event_type = 'payment_confirmed'
--     WHERE event_type = 'booking_confirmed';
--   UPDATE public.ghl_workflow_trigger_events SET event_type = 'booking_updated'
--     WHERE event_type IN ('booking_rescheduled', 'payment_updated');
--   (re-apply the constraint from 045_marketplace_workflow_trigger.sql)
--   DELETE FROM public.passport_schema_version WHERE version = '046_trigger_event_type_names';

BEGIN;

ALTER TABLE public.ghl_workflow_trigger_events
  DROP CONSTRAINT IF EXISTS ghl_workflow_trigger_events_type_valid;
ALTER TABLE public.ghl_workflow_trigger_events
  ADD CONSTRAINT ghl_workflow_trigger_events_type_valid CHECK (event_type IN (
    'booking_created',
    'booking_confirmed',
    'booking_rescheduled',
    'payment_updated',
    'booking_cancelled',
    -- Names used before this migration, kept for delivered history.
    'payment_confirmed',
    'booking_updated'
  ));

UPDATE public.ghl_workflow_trigger_events
SET event_type = 'booking_confirmed', updated_at = now()
WHERE event_type = 'payment_confirmed' AND status <> 'delivered';

UPDATE public.ghl_workflow_trigger_events
SET event_type = 'booking_rescheduled', updated_at = now()
WHERE event_type = 'booking_updated' AND status <> 'delivered';

INSERT INTO public.passport_schema_version(version)
VALUES ('046_trigger_event_type_names')
ON CONFLICT (version) DO NOTHING;

COMMIT;
