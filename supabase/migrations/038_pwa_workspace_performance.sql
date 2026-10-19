-- PWA workspace read-model performance indexes.
-- This migration is additive and safe to run after 037_pwa_auth_handoffs.sql.

BEGIN;

-- Serves the mobile dashboard's upcoming, pending-payment, and assignment-gap counts.
CREATE INDEX IF NOT EXISTS ix_bookings_operator_status_start
  ON public.bookings (operator_id, status, start_at);

-- Serves pending waiver counts without scanning all waiver records for an operator.
CREATE INDEX IF NOT EXISTS ix_booking_waivers_operator_status_booking
  ON public.booking_waivers (operator_id, status, booking_id);

-- Covers the correlated dashboard test for a fully covering staff assignment.
CREATE INDEX IF NOT EXISTS ix_staff_assignments_operator_calendar_interval
  ON public.staff_assignments (operator_id, calendar_id, start_at, end_at);

INSERT INTO public.passport_schema_version(version)
VALUES ('038_pwa_workspace_performance')
ON CONFLICT (version) DO NOTHING;

COMMIT;
