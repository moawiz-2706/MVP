# Passport Codebase Audit and Reliability Improvements

**Repository:** `https://github.com/moawiz-2706/MVP.git`  
**Audited commit:** `cc231e85e2bc80e9c0e7d8e8426431515d65aa8e` (`Revert to 7877cef`)  
**Working branch:** `fix/ghl-sync-and-resource-availability`

## Executive Summary

The repository uses a coherent split architecture. The React frontend communicates with a FastAPI backend, PostgreSQL is the authoritative store for calendars, resources, bookings, and payments, and GoHighLevel (GHL) synchronization is performed asynchronously through a durable outbox worker. The existing architecture already contained the main calendar and booking synchronization flows, so the changes preserve and harden those flows rather than introducing a parallel implementation.

The principal functional defect was in `AvailabilityService`. It required every configured staff role to have a currently available staff member before returning a bookable slot. That restriction has been removed from both authenticated and public availability paths. Calendar hours, pushed slots, date-wise hours, blocks, booking duration, and resource inventory remain active availability rules.

The GHL synchronization layer was also hardened. Calendar recovery now uses a stable Passport calendar marker rather than a mutable description containing staff names. Appointment retries now query GHL for the stable Passport booking marker before issuing another create request, including after an existing remote event ID is found to be stale. This reduces duplicate calendars and appointments when a response is lost, a worker retries, or a mapping is recovered.

Live GHL API calls could not be performed in this session because the HighLevel connector was disabled and the connector-access suggestion was declined. The implementation was therefore verified with local PostgreSQL integration tests, unit tests, source inspection, and documented GHL API behavior. The remaining live-access limitation is recorded below.

## Existing Architecture Found

The frontend is a Vite React TypeScript application. `frontend/src/main.tsx` registers the routes, `frontend/src/api/client.ts` centralizes authenticated API calls, TanStack Query manages server state, and the calendar, booking, staff, resource, and public-booking pages are organized into feature directories. The public booking page consumes the backend availability response and disables only slots returned as unavailable; it did not contain an independent staff-availability gate.

The backend is a FastAPI application under `backend/app`. Configuration, calendar CRUD, availability, public pages, orders, bookings, staff, OAuth, webhooks, payments, and notifications are exposed through `backend/app/api/v1`. SQLAlchemy models in `backend/app/models/entities.py` mirror the authoritative PostgreSQL schema history under `supabase/migrations`. The outbox model has unique idempotency keys and supports calendar synchronization, appointment synchronization, cancellation, contact, email, staff, and payment jobs.

GHL authentication is handled by `ghl_auth_service.py` and `ghl_client.py`. Access and refresh tokens are encrypted, refresh-token rotation is serialized with a database row lock, and a single 401 response causes one token refresh and request retry. Calendar and appointment work is performed by `ghl_calendar_service.py` and `ghl_appointment_service.py`. `backend/worker.py` drains the outbox and reschedules failures with exponential backoff.

## Findings and Changes

### Calendar-to-GHL synchronization

Calendar creation and update already committed the local calendar and enqueued a `ghl_sync_calendar` outbox job. The worker then creates or updates the corresponding GHL event calendar and synchronizes its schedule. Local mapping state records the GHL calendar ID, desired and applied revisions, status, and the latest error. Calendar deletion soft-deletes the local calendar, removes future operational records according to the existing retention rules, and queues `ghl_delete_calendar` with the captured remote ID.

The recovery weakness was that `_find_remote_calendar` matched the calendar name and the complete mutable description. Staff assignment changes therefore changed the description and could prevent recovery of a remote calendar after a lost create response. The implementation now adds `Passport calendar: <local UUID>` to the synchronized description and uses that marker for recovery. Staff names can still be displayed in the remote description, but they no longer determine identity.

A failed calendar operation remains visible in the mapping with `status="failed"` and `last_error`; the local transaction is not silently rolled back after the local calendar has already been committed. Retrying the outbox job uses the mapping and stable marker instead of blindly creating another remote calendar.

### Booking-to-GHL synchronization

An order is validated inside a transaction. The service locks calendar rows and resource rows, recalculates availability after the locks are held, snapshots booking details, and writes the booking, resources, payment, and required outbox jobs. Unpaid bookings enqueue contact, confirmation-email, and appointment work immediately. Paid bookings enqueue the same GHL work when the verified payment webhook transitions the order and bookings to confirmed.

The appointment service synchronizes the local booking to the mapped GHL calendar, upserts the contact when necessary, sends the relevant contact and booking metadata, and stores the remote appointment ID in `GHLAppointmentMapping`. Updates use the existing remote event ID, and cancellations update the remote appointment status rather than creating a new event.

The documented GHL appointment-create operation does not provide an idempotency-key field. To reduce duplicate appointments on retries, the appointment description already contains `Passport booking: <local UUID>`. The new recovery path calls GHL's calendar-events listing endpoint for the mapped remote calendar and the narrow booking time window, searches for the stable marker, and reuses the matching event ID before issuing another POST. This recovery also runs after a previously stored remote event ID returns 404. A prior `manual_review` mapping is now allowed to reconcile before another create attempt.

The existing outbox unique idempotency keys prevent duplicate job insertion for normal create, confirm, update, and cancel transitions. Appointment and calendar mappings remain the local source of truth for subsequent updates and cancellations.

### Staff and role availability removal

The following staff-based booking restrictions were removed from `backend/app/services/availability_service.py`:

- Required-role pool readiness in `AvailabilityService.check`.
- Staff roster, staff schedule, and rolling staff-window queries in public slot generation.
- Per-role staff availability checks in `AvailabilityService.public_day`.
- The final `staff_ready` condition that set `available=False` and `max_bookable_units=0`.

The remaining staff services are intentionally preserved. Staff hours, GHL staff availability windows, custom roles, assignment collision checks, and GHL ownership logic still support the staff-management and assignment workflows. They no longer suppress a public or authenticated booking slot. The calendar editor copy was updated from “required staff pools” to “staff assignment pools” and now explicitly states that those pools do not make public booking slots unavailable. The deployment README was updated to describe the same behavior.

### UI improvement

The existing calendar editor already had loading, empty, mutation-error, and success states. The staff-pool explanation contradicted the requested behavior, so it was corrected without redesigning the application. This removes a major source of operator confusion while preserving the existing layout, controls, and assignment configuration.

## Files Changed

| File | Change |
| --- | --- |
| `backend/app/services/availability_service.py` | Removed staff/role-based slot blocking while retaining calendar and resource rules. |
| `backend/app/services/ghl_calendar_service.py` | Added a stable Passport calendar marker and marker-based GHL recovery. |
| `backend/app/services/ghl_appointment_service.py` | Added marker-based appointment recovery and safe retry behavior for stale or missing remote IDs. |
| `backend/tests/test_availability_integration.py` | Updated the legacy role-availability expectation and added regression coverage for inactive/unavailable staff. |
| `backend/tests/test_crud_sync_contracts.py` | Added unit coverage for calendar and appointment recovery markers. |
| `frontend/src/calendars/CalendarsPage.tsx` | Clarified that staff pools guide assignment and GHL ownership but do not block public booking. |
| `README.md` | Corrected production guidance about the role of staff availability windows. |

## Final Calendar Synchronization Flow

1. The operator creates or updates a local calendar through the configuration API.
2. The local calendar transaction commits and a unique-revision `ghl_sync_calendar` outbox job is written.
3. The worker claims the job and loads the current local calendar and mapping.
4. If a mapped GHL ID exists, the worker updates that remote calendar. If it is stale, the worker clears it and performs marker-based recovery.
5. If no mapping is recoverable, the worker creates a GHL event calendar whose description includes the stable local marker.
6. The worker synchronizes the schedule, stores the correct GHL calendar ID, advances the applied revision, and marks the mapping `synced`.
7. On failure, the mapping is marked `failed`, the error is persisted, and the outbox retry policy reschedules the job.
8. Local deletion soft-deletes the calendar and queues a remote delete using the captured GHL ID. A 404 remote delete is treated as already deleted.

## Final Booking Synchronization Flow

1. The public or authenticated booking endpoint validates the calendar, time, duration, date rules, blocks, and resource inventory.
2. The order transaction locks the relevant calendar and resource rows, rechecks availability, and writes the order, booking snapshots, resource reservations, and payment state.
3. The transaction writes durable GHL contact, email, and appointment jobs. Paid bookings receive the same GHL jobs after verified payment confirmation.
4. The worker upserts the GHL contact and then synchronizes the appointment to the correctly mapped GHL calendar.
5. The appointment body includes the contact ID, calendar ID, location ID, title, description, start and end time, booking status, and relevant ownership metadata.
6. The appointment mapping stores the remote event ID and payload hash. Updates use that ID.
7. If a create response is lost or a remote ID is stale, the worker searches the mapped GHL calendar for the stable Passport booking marker before creating another appointment.
8. Cancellation uses the existing remote event ID and updates its GHL appointment status to cancelled. Failed work remains visible through the mapping and outbox state and can be retried through the existing retry endpoint.

## Testing Performed

The following checks passed after the changes:

- Python compilation with `python -m compileall -q app`.
- Focused PostgreSQL integration and unit suites: availability, date-wise availability, pushed availability, and GHL synchronization contracts. The focused run completed successfully.
- New regression test confirming an inactive staff member and unavailable role do not make a valid resource-backed slot unavailable.
- New unit test confirming calendar recovery uses the stable Passport calendar marker.
- New unit test confirming appointment recovery uses the stable booking marker.
- Modified-file Ruff checks with existing line-length findings excluded; all non-format checks passed.
- Frontend TypeScript typecheck.
- Frontend production build, including SPA fallback generation.
- Frontend booking-notification helper tests.
- `git diff --check`.

The frontend build completed successfully but retained the existing Vite warning that the main minified JavaScript chunk exceeds 500 kB. That warning is not a build failure.

The sequential full backend suite completed without schema-collision errors but still reports 21 failures that were also present in the untouched baseline. They are outside the requested booking-availability and GHL-sync changes: five direct route-function tests call FastAPI handlers without injected `Response`/`Request` objects, staff-assignment tests create staff without the custom-role fixture now required by the existing staff-assignment contract, and waiver tests contain older response-shape or route-signature expectations. None of those failures occurred in the focused modified-flow suites, and the new staff-independent availability regression passes.

## Remaining Issues and Limitations

Live create, update, delete, and booking calls against the user's GHL sub-account were not possible because no active HighLevel connector or live GHL credentials were available in this session. The implementation was checked against the official GHL v3 documentation and local fakes/unit tests, but a final production smoke test still needs a connected GHL location with `calendars.readonly`, `calendars.write`, `calendars/events.readonly`, and `calendars/events.write` scopes.

HighLevel's documented appointment-create endpoint does not expose an idempotency-key parameter. Marker-based lookup plus the durable local mapping substantially protects retries and lost responses, but two independent workers could still race between the lookup and POST if they process different appointment jobs for the same booking at exactly the same time. The existing outbox lease and unique job keys make this uncommon; eliminating the final race completely would require a provider-supported idempotency key or an additional database-level per-booking synchronization lock.

The repository does not currently contain a browser-driven end-to-end test harness. Frontend typecheck, production build, and helper tests pass, but a live browser smoke test of calendar management and public checkout remains part of the post-connection verification work.

## References

[1]: https://marketplace.gohighlevel.com/docs/ghl/calendars/create-calendar/ "HighLevel v3 Create Calendar"

[2]: https://marketplace.gohighlevel.com/docs/ghl/calendars/create-appointment/ "HighLevel v3 Create Appointment"

[3]: https://marketplace.gohighlevel.com/docs/ghl/calendars/get-calendar-events/ "HighLevel v3 Get Calendar Events"

[4]: https://marketplace.gohighlevel.com/docs/ghl/calendars/get-calendars/ "HighLevel v3 Get Calendars"
