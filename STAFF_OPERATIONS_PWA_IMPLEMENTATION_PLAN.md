# Staff Operations PWA Implementation Plan

**Repository:** `https://github.com/moawiz-2706/MVP.git`  
**Local clone reviewed:** `/home/ubuntu/MVP_20261016`  
**Status:** In progress. The implementation is being delivered in tested slices inside the existing repository.

## 1. Product decision

The application will have **one PWA experience only**:

```text
Passport Staff Operations PWA
```

Every authorized staff/operator user enters the same PWA and receives the permissions assigned to their HighLevel user and Passport role.

This single PWA will include:

- View booking calendar
- View all permitted bookings
- Create bookings
- Update bookings
- Cancel bookings
- Manage booking participants and notes
- View and update staff assignments
- View waiver status and waiver links
- View payment and invoice status
- View HighLevel synchronization status and retry failed synchronization
- Create calendars
- Update calendars
- Configure calendar hours
- Configure blocked dates and pushed slots
- Configure calendar rates and customer types
- Configure resources and capacity
- Configure locations and categories
- View reports and notifications
- Manage staff roles and staff booking links where permitted

The existing `/staff-book/{token}` booking page should be retained as a compatibility route for quick booking links, but it will not be the main Staff Operations PWA login.

## 2. How staff will log in with HighLevel credentials

Passport must not ask staff to type their HighLevel username and password into Passport. Passport should never store HighLevel passwords.

The standalone PWA will use a **Login with HighLevel** OAuth authorization-code flow.

### Standalone login flow

```text
Staff opens the installed Passport PWA
        ↓
Staff clicks “Login with HighLevel”
        ↓
Passport redirects the browser to HighLevel
        ↓
Staff enters their normal HighLevel credentials on HighLevel
        ↓
HighLevel asks the staff member to authorize Passport
        ↓
HighLevel redirects back to Passport with a temporary code
        ↓
Passport exchanges the code server-side
        ↓
Passport receives the HighLevel userId and locationId
        ↓
Passport matches the user to the local operator and role
        ↓
Passport creates its own short-lived PWA session
        ↓
Staff enters the Staff Operations PWA
```

HighLevel OAuth returns an access token, refresh token, `locationId`, and the `userId` of the person who performed the authorization. The access token is used by the backend for authorized HighLevel API calls; the browser should receive only a Passport session, not the HighLevel client secret or provider refresh token.

### Existing embedded login

When the PWA is opened inside the HighLevel iframe, the current embedded login can continue to work:

```text
HighLevel iframe → REQUEST_USER_DATA → Passport /auth/ghl-session → Passport JWT
```

When the same PWA is opened as a standalone installed application, it will use the new OAuth login route instead. This gives one frontend experience with two supported authentication entry points:

```text
Inside HighLevel: existing embedded session
Standalone PWA: HighLevel OAuth login
```

## 3. HighLevel OAuth requirements

The HighLevel app must be configured as a private Marketplace app for the initial implementation.

Recommended settings:

- Target user: Sub-account/location
- Installers: Agency and sub-account, subject to the HighLevel account configuration
- Redirect URL: Passport backend OAuth callback URL
- Client ID: stored as a backend environment variable
- Client secret: stored only as a backend secret
- Minimum scopes required for the selected application features

The current repository already has reusable OAuth code in:

```text
backend/app/api/v1/ghl_oauth.py
backend/app/services/ghl_auth_service.py
```

The current OAuth installation flow already:

- Creates and validates a state value
- Exchanges the authorization code
- Requires a Location token
- Validates the location
- Stores HighLevel tokens encrypted
- Creates or updates the Passport operator installation

The new PWA login must be separate from the installation callback, because installation and user session creation are different operations.

## 4. New authentication routes

Add dedicated routes such as:

```text
GET  /api/v1/pwa-auth/highlevel/start
GET  /api/v1/pwa-auth/highlevel/callback
POST /api/v1/pwa-auth/refresh
POST /api/v1/pwa-auth/logout
GET  /api/v1/pwa-auth/me
GET  /api/v1/pwa/bootstrap
```

### Start response

The start route may redirect directly to HighLevel or return a URL:

```json
{
  "authorization_url": "https://...highlevel...",
  "state_expires_in": 600
}
```

The OAuth state must be stored as a digest, must expire quickly, and must be single-use.

### Callback behavior

The callback must:

1. Validate the OAuth state and browser session.
2. Exchange the authorization code only on the backend.
3. Validate `userType=Location`.
4. Validate the expected `locationId`.
5. Validate that the required scopes were granted.
6. Read the returned HighLevel `userId`.
7. Find or create the local `AppUser` using the HighLevel user ID.
8. Find the local `OperatorUser` membership for the location.
9. Resolve the Passport role and permissions.
10. Create a short-lived Passport access session.
11. Redirect to `/app` without putting provider tokens in the URL.

### Bootstrap response

The PWA should call one bootstrap endpoint after login instead of making many startup requests:

```json
{
  "user": {
    "id": "passport-user-uuid",
    "ghl_user_id": "highlevel-user-id",
    "name": "Staff Member",
    "email": "staff@example.com",
    "role": "admin",
    "is_agency_owner": false
  },
  "operator": {
    "id": "operator-uuid",
    "name": "Example Operator",
    "slug": "example-operator",
    "time_zone": "America/New_York",
    "ghl_location_id": "highlevel-location-id"
  },
  "permissions": [
    "view_bookings",
    "operate_bookings",
    "manage_configuration",
    "manage_payments",
    "delete_configuration"
  ],
  "features": {
    "calendar_management": true,
    "booking_management": true,
    "staff_assignment": true,
    "waivers": true,
    "payments": true,
    "reports": true,
    "ghl_resync": true
  }
}
```

## 5. Permission model for the one PWA

The PWA can have one interface while the backend still enforces permissions.

Existing Passport permissions:

```text
VIEW_BOOKINGS
OPERATE_BOOKINGS
MANAGE_CONFIGURATION
MANAGE_PAYMENTS
DELETE_CONFIGURATION
```

Recommended behavior:

| Feature | Required permission |
|---|---|
| View calendar | `VIEW_BOOKINGS` |
| View booking list/details | `VIEW_BOOKINGS` |
| Create a booking | `OPERATE_BOOKINGS` |
| Update time or quantity | `OPERATE_BOOKINGS` |
| Cancel booking | `OPERATE_BOOKINGS` |
| Assign staff | `OPERATE_BOOKINGS` |
| Add booking notes/participants | `OPERATE_BOOKINGS` |
| Create/update calendar | `MANAGE_CONFIGURATION` |
| Change rates/resources/hours | `MANAGE_CONFIGURATION` |
| Manage staff and roles | `MANAGE_CONFIGURATION` |
| Delete calendar/category/resource | `DELETE_CONFIGURATION` |
| Stripe Connect settings | `MANAGE_PAYMENTS` |
| Retry GHL synchronization | `OPERATE_BOOKINGS` or a dedicated sync permission |

If every authenticated staff member must literally have every feature, the Passport role mapping can grant all five permissions. The backend should still keep explicit permission checks so that roles can be restricted later without rewriting the PWA.

Irreversible actions such as deleting a calendar or cancelling a paid booking should require a visible confirmation and should be recorded in an audit event.

## 6. PWA screens

### Login and session screens

```text
/login
/login/callback
/session-expired
/offline
```

The login screen should provide:

- Login with HighLevel
- Clear message that credentials are entered on HighLevel
- Reconnect action when a session expires
- Location/operator name after successful login

### Staff Operations dashboard

```text
/app
```

Show:

- Today's bookings
- Upcoming bookings
- Pending payments
- Waivers awaiting signature
- Staff assignment conflicts
- GHL synchronization failures
- Quick actions for new booking and calendar view

### Booking calendar

```text
/app/calendar
```

Support:

- Day view
- Week view
- Month view
- Calendar filter
- Category filter
- Staff filter
- Booking status filter
- Open slot selection
- Staff assignment visibility
- Tap booking to open details

### All bookings

```text
/app/bookings
```

Support:

- Search by customer name, email, phone, or public reference
- Filter by date range
- Filter by calendar
- Filter by payment status
- Filter by booking status
- Filter by waiver status
- Open booking detail
- Create a new booking

### Booking detail

```text
/app/bookings/:bookingId
```

Show and allow, where permitted:

- Booking time and quantity
- Customer details
- Payment method and status
- Hosted invoice link
- Waiver status and secure link
- Participants
- Internal notes
- Resources
- Staff assignments
- HighLevel contact/appointment sync status
- Retry/resync action
- Update time or quantity
- Cancel booking
- Mark completed
- Mark no-show
- Weather closure

### Calendar management

```text
/app/calendars
/app/calendars/new
/app/calendars/:calendarId
```

Use sections or tabs for:

- General settings
- Name and slug
- Headline and description
- Booking instructions
- Hero and gallery images
- Location and category
- Duration and slot interval
- Base price in dollars
- Booking mode
- Booking cutoff
- Party-size limits
- Weekly availability
- Date-specific availability
- Pushed slots
- Blocked dates
- Resources and capacity
- Customer types and rates
- Booking custom fields
- Public booking link

The current backend API stores prices in minor units while the existing frontend displays dollars. The PWA must preserve this boundary:

```text
User enters: 125.00 dollars
PWA sends:   12500 minor units
```

### Staff management

```text
/app/staff
```

Support:

- View staff directory
- View HighLevel sync status
- Update Passport custom roles
- View weekly availability
- Generate/regenerate private booking links
- View staff assignments
- View conflicts

### Settings and reports

```text
/app/settings
/app/reports
/app/notifications
```

Reuse current settings areas for:

- Waiver configuration
- Stripe Connect status/onboarding
- HighLevel integration status
- Notifications
- Reports

## 7. Existing APIs to reuse

### Booking calendar and bookings

```text
GET    /api/v1/booking-slots?range_start=...&range_end=...
GET    /api/v1/bookings?range_start=...&range_end=...&calendar_id=...&status=...&search=...
GET    /api/v1/bookings/{booking_id}
POST   /api/v1/bookings
PATCH  /api/v1/bookings/{booking_id}
POST   /api/v1/bookings/{booking_id}/cancel
POST   /api/v1/bookings/{booking_id}/status
POST   /api/v1/bookings/{booking_id}/weather-cancel
GET    /api/v1/booking-notifications
```

The current booking list response includes:

```json
{
  "id": "uuid",
  "booking_order_id": "uuid",
  "public_reference": "ABC123",
  "calendar_id": "uuid",
  "calendar_name": "Mangrove Tour",
  "category_id": "uuid or null",
  "category_name": "Tours",
  "category_color": "#527a73",
  "customer_name": "Jane Doe",
  "customer_email": "jane@example.com",
  "start_at": "2026-10-20T14:00:00Z",
  "end_at": "2026-10-20T16:00:00Z",
  "units": 2,
  "status": "confirmed"
}
```

The detail response already includes:

- Payment status and method
- Invoice status and URL
- Totals, fees, and taxes
- Waiver summary
- Participants
- Notes
- Resources
- HighLevel contact status
- HighLevel appointment status
- Appointment event ID and last error

### Booking notes and participants

```text
GET    /api/v1/bookings/{booking_id}/participants
PUT    /api/v1/bookings/{booking_id}/participants
DELETE /api/v1/bookings/{booking_id}/participants/{participant_id}
POST   /api/v1/bookings/{booking_id}/notes
DELETE /api/v1/bookings/{booking_id}/notes/{note_id}
```

### Staff and assignments

```text
GET    /api/v1/staff
POST   /api/v1/staff
GET    /api/v1/staff/{staff_id}
PATCH  /api/v1/staff/{staff_id}
PATCH  /api/v1/staff/{staff_id}/custom-role
DELETE /api/v1/staff/{staff_id}
POST   /api/v1/staff/{staff_id}/booking-link

GET    /api/v1/staff-assignments
GET    /api/v1/staff-assignments/candidates
GET    /api/v1/staff-assignments/conflicts
POST   /api/v1/staff-assignments
PATCH  /api/v1/staff-assignments/{assignment_id}
DELETE /api/v1/staff-assignments/{assignment_id}
```

### Calendar, rate, and resource configuration

```text
GET    /api/v1/calendars
POST   /api/v1/calendars
GET    /api/v1/calendars/{calendar_id}
PATCH  /api/v1/calendars/{calendar_id}
DELETE /api/v1/calendars/{calendar_id}

GET    /api/v1/calendars/{calendar_id}/hours
PUT    /api/v1/calendars/{calendar_id}/hours
GET    /api/v1/calendars/{calendar_id}/date-hours
PUT    /api/v1/calendars/{calendar_id}/date-hours
GET    /api/v1/calendars/{calendar_id}/pushed-slots
POST   /api/v1/calendars/{calendar_id}/pushed-slots
DELETE /api/v1/calendars/{calendar_id}/pushed-slots/{slot_id}
GET    /api/v1/calendars/{calendar_id}/blocks
PUT    /api/v1/calendars/{calendar_id}/blocks
POST   /api/v1/calendars/{calendar_id}/blocks
PATCH  /api/v1/calendars/{calendar_id}/blocks/{block_id}
DELETE /api/v1/calendars/{calendar_id}/blocks/{block_id}
GET    /api/v1/calendars/{calendar_id}/resources
PUT    /api/v1/calendars/{calendar_id}/resources
GET    /api/v1/calendars/{calendar_id}/rates
PUT    /api/v1/calendars/{calendar_id}/rates
DELETE /api/v1/calendars/{calendar_id}/rates/{customer_type_id}
```

Supporting configuration APIs:

```text
GET/POST/PATCH/DELETE /api/v1/locations
GET/POST/PATCH/DELETE /api/v1/resources
GET/POST/PATCH/DELETE /api/v1/customer-types
GET/POST/PATCH/DELETE /api/v1/calendar-categories
GET/POST/PATCH/DELETE /api/v1/booking-custom-fields
GET/POST/PATCH/DELETE /api/v1/calendars/{calendar_id}/booking-policy
```

### Payments, waivers, HighLevel, and reports

```text
GET  /api/v1/settings/waiver
PUT  /api/v1/settings/waiver
GET  /api/v1/stripe/connect/status
POST /api/v1/stripe/connect/onboarding-link
GET  /api/v1/notifications
POST /api/v1/orders/{order_id}/retry-ghl-sync
POST /api/v1/orders/{order_id}/resync-ghl
GET  /api/v1/reports/summary
GET  /api/v1/reports/bookings.csv
```

## 8. New aggregate APIs recommended for mobile performance

The existing APIs can support the first version, but mobile startup will be faster with aggregate read endpoints.

### PWA bootstrap

```text
GET /api/v1/pwa/bootstrap
```

Returns the user, operator, permissions, feature flags, timezone, and compact navigation data.

### Dashboard summary

```text
GET /api/v1/pwa/dashboard?date=2026-10-16
```

Suggested response:

```json
{
  "date": "2026-10-16",
  "time_zone": "America/New_York",
  "today": ["BookingListItem objects"],
  "upcoming": ["BookingListItem objects"],
  "counts": {
    "today": 8,
    "pending_payment": 2,
    "waivers_pending": 3,
    "sync_failures": 1,
    "staff_conflicts": 0
  }
}
```

### Calendar management detail

```text
GET /api/v1/pwa/calendars/{calendar_id}/management
```

Suggested response:

```json
{
  "calendar": "CalendarRead",
  "hours": ["CalendarHourRead"],
  "date_hours": ["CalendarDateHourRead"],
  "blocks": ["CalendarBlockRead"],
  "pushed_slots": ["PushedSlotRead"],
  "resources": ["CalendarResourceRead"],
  "rates": ["CalendarRateRead"],
  "booking_policy": "BookingPolicyRead",
  "custom_fields": ["CustomFieldDefinitionRead"]
}
```

These endpoints should be read-only aggregates. Existing focused mutation endpoints should remain responsible for validation and database updates.

## 9. Database and session changes

### Reuse existing data

The PWA does not need a second booking, calendar, payment, waiver, or staff database. Passport remains the source of truth.

Existing tables can continue to store:

- Operators
- HighLevel installations
- HighLevel users
- Operator memberships
- Calendars
- Calendar hours and blocks
- Rates and customer types
- Resources
- Bookings and orders
- Payments and invoices
- Waivers
- Staff and assignments
- Notifications and synchronization state

### PWA session table

For persistent standalone login, add a session table such as:

```text
pwa_sessions
- id UUID primary key
- operator_id UUID not null
- app_user_id UUID not null
- highlevel_user_id TEXT not null
- access_token_digest TEXT unique not null
- refresh_token_digest TEXT unique null
- device_name TEXT null
- created_at TIMESTAMPTZ not null
- last_used_at TIMESTAMPTZ null
- expires_at TIMESTAMPTZ not null
- revoked_at TIMESTAMPTZ null
- last_ip INET null
- user_agent TEXT null
```

Store only digests for Passport session tokens. Keep HighLevel provider tokens encrypted in the existing installation/token storage. Do not expose HighLevel refresh tokens to the browser.

Required indexes:

```text
pwa_sessions(access_token_digest)
pwa_sessions(operator_id, app_user_id, revoked_at, expires_at)
pwa_sessions(highlevel_user_id, operator_id)
```

The existing `GHLOAuthState` table can be reused for OAuth state if its flow column is extended to distinguish installation from PWA login.

### Recommended data indexes

```text
bookings(operator_id, start_at, status)
booking_orders(operator_id, created_at, status)
staff_assignments(operator_id, staff_id, start_at, end_at)
outbox_jobs(status, next_attempt_at)
```

Any database change must be a forward-only migration and must be added to the repository's migration sequence.

## 10. PWA behavior and security

### Installability

Add an application-owned manifest with:

```text
frontend/public/manifest.webmanifest
frontend/public/icons/icon-192.png
frontend/public/icons/icon-512.png
frontend/public/icons/maskable-512.png
```

Suggested manifest values:

```json
{
  "name": "Passport Staff Operations",
  "short_name": "Passport Staff",
  "start_url": "/app",
  "display": "standalone",
  "background_color": "#f6f8f8",
  "theme_color": "#527a73"
}
```

### Service worker rules

Cache only:

- Application shell
- Versioned JavaScript and CSS
- Icons and static assets
- Offline fallback page

Do not cache by default:

- Passport access tokens
- HighLevel access or refresh tokens
- Customer contact details
- Payment data
- Waiver signatures
- Booking details in a shared browser cache
- Calendar mutation responses

The app may show the last visited screen when offline, but it must clearly mark the data as stale. Creating or editing a booking, calendar, price, staff assignment, waiver, or payment must require a live connection.

### Credential handling

- Never request HighLevel passwords inside Passport.
- Never include the HighLevel client secret in frontend code.
- Never put provider access tokens in query parameters.
- Use one-time OAuth state values.
- Use short-lived Passport sessions.
- Refresh and rotate sessions safely.
- Revoke sessions from the PWA logout route.
- Recheck operator membership and authorization version on every API request.
- Log security events without logging tokens or passwords.

## 11. Recommended implementation phases

### Phase 1 — One PWA shell and HighLevel login

- Add the installable PWA manifest and icons.
- Add service-worker shell caching.
- Add standalone HighLevel OAuth login.
- Keep the existing embedded HighLevel session working.
- Add PWA bootstrap and permission-aware navigation.
- Add session refresh and logout.

### Phase 2 — Booking operations

- Add dashboard.
- Add day/week/month calendar views.
- Add all-bookings list and filters.
- Add booking detail.
- Add booking creation.
- Add update, cancellation, completion, no-show, and weather actions.
- Add payment, invoice, waiver, notes, and participant sections.
- Add staff assignment controls.

### Phase 3 — Calendar and configuration operations

- Add calendar creation and editing.
- Add weekly and date-specific hours.
- Add pushed slots and blocked dates.
- Add rate and customer-type management.
- Add resources and capacity mappings.
- Add locations and categories.
- Add booking custom fields.
- Add destructive-action confirmations.

### Phase 4 — Staff, reports, and synchronization operations

- Add staff directory and role management.
- Add staff booking-link generation.
- Add assignment conflict views.
- Add notifications.
- Add GHL sync status and manual resync.
- Add reports and CSV export.
- Add dashboard aggregate endpoints for mobile performance.

### Phase 5 — Production hardening

- Reduce duplicate frontend polling.
- Lazy-load PWA routes.
- Add database indexes.
- Keep provider API work out of user-facing requests where possible.
- Confirm session revocation works.
- Confirm permissions are enforced server-side.
- Confirm sensitive API responses are not cached by the service worker.

## 12. Important clarification

A single PWA does not mean every user must have unrestricted administrator access.

It means there is one application experience. The backend still decides which buttons and APIs each authenticated HighLevel user can use.

If your requirement is literally that **every authenticated staff member can view and update calendars, view and update all bookings, manage rates, manage resources, and manage staff**, the implementation can grant all required Passport permissions to the staff role.

The safer default is:

- All staff can view calendars and bookings.
- All staff can create and update bookings.
- Authorized staff can assign staff and update operational data.
- Calendar configuration and destructive actions remain administrator-controlled.

This boundary should be confirmed before implementation because it directly controls access to pricing, inventory, customer data, payments, and deletion operations.

## 13. Final recommended authentication model

```text
One PWA: Passport Staff Operations

Inside HighLevel:
    Existing embedded GHL session

Standalone installed PWA:
    Login with HighLevel OAuth

Passport backend:
    Maps HighLevel userId + locationId to AppUser + OperatorUser
    Creates Passport session
    Enforces Passport permissions

HighLevel passwords:
    Entered only on HighLevel
    Never stored by Passport
```


## 14. Implementation status — 2026-10-16

The Staff Operations PWA is being implemented **inside this existing repository** and uses the same backend as the embedded HighLevel application:

- Same FastAPI application and `/api/v1` routes
- Same Supabase/PostgreSQL database and SQLAlchemy models
- Same HighLevel installation, encrypted token storage, contacts, calendars, appointments, and staff mappings
- Same Stripe Connect and payment services
- Same Passport role and permission checks
- No second backend, duplicate database, or separate payment integration

### Completed in the first implementation slice

1. Added installable PWA metadata and manifest.
2. Added branded 192px and 512px application icons.
3. Added production service-worker registration with an offline fallback shell.
4. Added the browser installation prompt.
5. Added a route inventory at `frontend/public/manus-routes.json`.
6. Added standalone HighLevel OAuth login while preserving the existing embedded iframe login.
7. Reused the existing registered HighLevel OAuth callback instead of introducing a second OAuth application callback.
8. Added a short-lived one-time server-side PWA handoff. The Passport JWT is issued by `/api/v1/pwa-auth/exchange` and is not placed in the browser URL.
9. Added PWA session refresh through `/api/v1/pwa-auth/refresh`.
10. Added migration `037_pwa_auth_handoffs.sql` and advanced production readiness to marker `037_pwa_auth_handoffs`.

### Validation completed

- Backend focused PWA/auth/schema tests: passed
- Backend non-database regression suite: passed
- Python compilation and `git diff --check`: passed
- Frontend typecheck: passed
- Existing frontend booking-notification tests: passed
- Existing frontend money tests: passed
- Production frontend build: passed

### Next implementation slice

The next slice will improve the shared existing Staff Operations pages for mobile/PWA use, starting with the booking calendar and booking list. It will reuse the current booking APIs and add only the missing staff-operation interactions, with focused tests after each slice.


## 15. Implementation status — phone-sized booking and calendar phase

Completed the next Staff PWA slice using the existing booking and calendar APIs:

- Added a phone agenda view for booking slots below the mobile breakpoint.
- Added tap targets for opening a slot, opening a booking, viewing staff assignments, and creating/operating bookings through the existing modal flows.
- Preserved the existing FullCalendar month/week/day interface for desktop and larger tablet screens.
- Added mobile calendar cards with category, location, duration, price, active status, Book, Edit, and Delete actions.
- Preserved the existing calendar management forms, availability editor, resource editor, rate editor, blocked-date editor, and booking modal.
- No new booking or calendar API endpoints were introduced.
- No duplicate backend or separate PWA database was introduced.

Validation for this phase:

- Frontend typecheck: passed
- Frontend booking-notification tests: passed
- Frontend money tests: passed
- Production frontend build: passed
- Backend Python compilation: passed
- Backend non-database regression suite: passed


## 16. Mobile login and installation troubleshooting fixes

The mobile testing issue identified two separate behaviors. iPhone does not expose the Android-style `beforeinstallprompt` event; installation must use Safari Share → Add to Home Screen. Android may also omit the event when the page is not yet installable or when the event fires before the authenticated shell mounts. The PWA now shows phone installation guidance on the login screen and a mobile fallback help dialog, while preserving the native Android install prompt when available.

The standalone HighLevel OAuth request no longer asks Passport to send conversation messages. Customer SMS and email delivery is intended to be handled by HighLevel workflows, so the obsolete `conversations/message.write` scope was removed. The OAuth callback now also converts unexpected server-side failures into a controlled login error redirect and logs the underlying exception for backend diagnosis. The service-worker cache version was advanced to force mobile clients to refresh stale shell code.
