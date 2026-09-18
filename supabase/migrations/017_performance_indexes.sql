-- Performance indexes for public availability, booking reservation checks,
-- staff-pool filtering, and asynchronous outbox processing.
-- All indexes are additive and safe to apply to an existing installation.

CREATE INDEX IF NOT EXISTS ix_calendar_hours_calendar_day_start
    ON calendar_hours(calendar_id, day_of_week, start_time);

CREATE INDEX IF NOT EXISTS ix_calendar_pushed_slots_calendar_start
    ON calendar_pushed_slots(calendar_id, start_at);

CREATE INDEX IF NOT EXISTS ix_calendar_resources_calendar_resource
    ON calendar_resources(calendar_id, resource_id);

CREATE INDEX IF NOT EXISTS ix_booking_resources_resource_booking
    ON booking_resources(resource_id, booking_id);

CREATE INDEX IF NOT EXISTS ix_staff_operator_role_active
    ON staff(operator_id, custom_role, is_active)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_outbox_jobs_ready_order
    ON outbox_jobs(status, next_attempt_at, created_at);
