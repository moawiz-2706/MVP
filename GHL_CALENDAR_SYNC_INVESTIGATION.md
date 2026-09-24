# GoHighLevel Calendar Sync Investigation

**Repository:** `https://github.com/moawiz-2706/MVP.git`  
**Checked-out revision:** `241e1b04490d357f6fa651bb8956e095ea4efa54` (`241e1b0`)  
**Working tree:** clean

## Conclusion

The calendar create/update code does enqueue GoHighLevel synchronization work, but the repository does not run the outbox consumer continuously for calendar jobs. The standalone `backend/worker.py` only performs GHL staff-directory and staff-availability synchronization; it never calls `OutboxService.process()` or `OutboxService.drain()`. Therefore, calendar jobs remain pending unless the protected internal endpoint is invoked or the daily Vercel Cron runs.

This explains why a calendar may be created or updated inside Passport but not appear or change promptly in the GHL calendar.

## Evidence

| Area | Finding |
|---|---|
| Calendar create/update | `ConfigurationService.create_calendar()` and `update_calendar()` call `_queue_ghl_calendar_sync()` after committing the local change. |
| Queue behavior | `_queue_ghl_calendar_sync()` writes `ghl_sync_calendar` to `outbox_jobs`, then queues appointment work. It does not process the job inline. |
| Outbox implementation | `OutboxService._run()` correctly contains handlers for `ghl_sync_calendar`, `ghl_delete_calendar`, and `ghl_sync_appointment`. |
| Actual worker | `backend/worker.py` loops only through `GHLStaffUserService.sync_all()`. It does not drain the outbox. |
| Scheduled fallback | `vercel.json` configures only `/api/v1/internal/cron/daily` at `0 11 * * *`, so queued syncs may wait until that daily run. |
| Feature flag | `ghl_calendar_sync_enabled` defaults to `False`; when false, calendar jobs are not even enqueued and the sync service returns immediately. |
| API authentication | OAuth requests require calendar read/write scopes, including `calendars.write`, `calendars/events.write`, and the corresponding read scopes. |

## Primary issues to fix

### 1. The production worker does not consume the outbox

`backend/worker.py` is described as the near-real-time worker, but it only reconciles GHL users and availability. It should also process pending outbox jobs on every loop, for example by calling `OutboxService(db, settings).drain(...)` for each iteration or by using a separate outbox worker process.

Alternatively, deploy a separate always-on process that repeatedly calls the protected `POST /api/v1/internal/process-outbox` endpoint. The current endpoint is suitable for this, but it is not automatically called by the worker.

### 2. Calendar sync is disabled by default

The production environment must explicitly set:

```text
GHL_CALENDAR_SYNC_ENABLED=true
```

If this variable is absent or false in the deployed API/worker environment, the application intentionally skips queueing and syncing calendars.

### 3. The only configured Vercel fallback runs once per day

The Vercel Cron entry point drains the outbox only once daily. That is not near-real-time and is not sufficient for the requested behavior. It should either be changed to a more frequent supported schedule or, preferably, complemented by the always-on outbox worker described above.

The cron also depends on `CRON_SECRET` being configured correctly, because `/internal/cron/daily` rejects requests without valid authorization.

## GHL API review

The calendar service uses the current documented v3 routes:

- `POST /calendars/` for creation
- `PUT /calendars/{calendarId}` for updates
- `PUT /calendars/schedules/event-calendar/{calendarId}` for availability schedule updates
- `POST /calendars/events/appointments` for appointments

These routes and the main request fields match the current official HighLevel documentation. The calendar update body also correctly omits `locationId`, which is required on create but is not an update field.

One lower-priority issue is that `_sync_schedule()` tries `POST` on the same schedule URL after a `404`. The current API documentation documents `PUT` for schedule updates; there is no documented POST fallback on that page. This fallback should be removed or replaced with a documented recovery path after the primary queue/worker issue is fixed.

## Validation performed

- Python bytecode compilation passed.
- Backend test suite passed after installing the declared requirements: all executed tests passed; database-gated tests were skipped when no `TEST_DATABASE_URL` was supplied.
- No live GHL account/API call was made because the repository clone does not contain production credentials.

## Remaining deployment requirements

The deployed API and worker environments must set `GHL_CALENDAR_SYNC_ENABLED=true`, provide valid GHL credentials and scopes, and run `python worker.py` as an always-on process. The daily cron can remain as a retry/reconciliation fallback, but it is no longer the normal synchronization path. Monitoring should be added for `outbox_jobs.status IN ('failed','dead')` and `ghl_calendar_mappings.last_error` so failed external calls are visible. The undocumented POST fallback in `_sync_schedule()` should also be removed or replaced with a documented recovery path.

## References

- [Configuration service](backend/app/services/configuration_service.py)
- [GHL calendar service](backend/app/services/ghl_calendar_service.py)
- [Outbox service](backend/app/services/outbox_service.py)
- [Standalone worker](backend/worker.py)
- [Runtime configuration](backend/app/core/config.py)
- [Deployment configuration](vercel.json)
- [HighLevel Create Calendar API](https://marketplace.gohighlevel.com/docs/ghl/calendars/create-calendar/)
- [HighLevel Update Calendar API](https://marketplace.gohighlevel.com/docs/ghl/calendars/update-calendar/)
- [HighLevel Create Appointment API](https://marketplace.gohighlevel.com/docs/ghl/calendars/create-appointment/)
- [HighLevel Update Calendar Schedule API](https://marketplace.gohighlevel.com/docs/ghl/calendars/update-calendar-schedule/)


## Implementation update — 2026-09-24

The immediate-sync behavior has now been implemented in the working tree:

- `ConfigurationService` processes calendar and affected appointment jobs immediately after the calendar mutation is committed.
- `OrderService` processes booking creation jobs immediately after the booking transaction is committed.
- `BookingAdminService` processes appointment update and cancellation jobs immediately after those mutations commit.
- `backend/worker.py` now processes pending outbox jobs on each worker loop, so failed immediate calls retry without depending on the daily cron.
- External GHL failures remain durable outbox failures with retry backoff; they do not roll back the successful local calendar or booking operation.

The final backend test suite and Python compilation both pass after these changes. Production still needs `GHL_CALENDAR_SYNC_ENABLED=true`, valid GHL credentials/scopes, and the always-on worker process running. The daily cron is retained only as a fallback/reconciliation path, not as the normal sync mechanism.
