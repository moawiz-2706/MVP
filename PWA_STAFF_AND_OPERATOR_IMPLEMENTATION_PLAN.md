# PWA Staff Booking and Operator Console Implementation Plan

**Repository reviewed:** `/home/ubuntu/MVP_20261016`  
**Source repository:** `https://github.com/moawiz-2706/MVP.git`  
**Status:** Planning only. No application source code or database migration is changed by this document.

## 1. Direct answer

Yes, this application can be extended into an installable Progressive Web App (PWA).

The safest design is **not** to turn the current staff booking link into an administrator credential. The current link is a long-lived, revocable private capability intended for booking creation. It can create a booking for a client, choose a calendar, select a time, choose card/invoice/free payment, and recover a card-payment result. It does not currently provide permission to view every booking, edit calendars, manage staff, or change configuration.

The PWA should therefore have two permission levels:

1. **Staff Booking PWA** — opened from a staff member's private link. It is limited to the capabilities of that staff member.
2. **Operator/Admin PWA** — opened with a real authenticated operator session and permission checks. It can view bookings, operate bookings, and, for administrators, create/update calendars and configuration.

This separation is required because the current embedded HighLevel login depends on `window.parent.postMessage()` from the HighLevel iframe. An installed standalone PWA has no HighLevel parent frame, so the existing `GHLSessionProvider` cannot be used as the only standalone login mechanism.

## 2. Current repository capabilities

### Existing staff booking link

Current frontend route:

```text
/staff-book/:token
```

Current backend routes:

```text
GET  /api/v1/staff-booking/{token}/context
GET  /api/v1/staff-booking/{token}/calendars/{calendar_id}/availability
GET  /api/v1/staff-booking/{token}/calendars/{calendar_id}/rates
GET  /api/v1/staff-booking/{token}/calendars/{calendar_id}/custom-fields
POST /api/v1/staff-booking/{token}/orders
GET  /api/v1/staff-booking/{token}/orders/{public_reference}
```

The context response currently contains:

```json
{
  "staff_id": "uuid",
  "staff_name": "Alex Smith",
  "operator_name": "Example Operator",
  "time_zone": "America/New_York",
  "calendars": ["CalendarRead objects"]
}
```

The private-link order request supports:

```json
{
  "items": [
    {
      "calendar_id": "uuid",
      "start_at": "2026-10-20T14:00:00Z",
      "units": 1,
      "rate_id": "uuid"
    }
  ],
  "customer": {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "phone": "+15555555555"
  },
  "custom_fields": {},
  "payment_method": "card"
}
```

The supported payment values are:

```text
card
invoice
none
```

### Existing authenticated operator console

Current application route:

```text
/app
```

The current operator console already contains pages for:

- Bookings and calendar view
- Notifications
- Resources
- Locations
- Calendars
- Staff
- Customers
- Reports
- Settings

It already has reusable backend APIs for calendar creation/update, booking lists/details, staff assignment, waivers, payments, reports, and HighLevel synchronization status.

### Existing authentication limitation

The current operator authentication flow is:

1. Passport asks the HighLevel parent iframe for encrypted user context.
2. Passport exchanges that context through `POST /api/v1/auth/ghl-session`.
3. Passport receives a short-lived Passport JWT.
4. Passport calls `GET /api/v1/me`.
5. The frontend refreshes the session before expiry.

This works inside HighLevel. It does not work as a standalone installed PWA unless a separate standalone authentication flow is added.

## 3. Recommended product structure

### A. Staff Booking PWA

Primary route:

```text
/staff-app/:token
```

The existing `/staff-book/:token` route can remain as a compatibility route and redirect into the PWA shell.

Staff users should be able to:

- Open their private staff app link.
- See their staff name and operator name.
- See calendars they are allowed to use.
- View available dates and times.
- Create a booking for a client.
- Select card, invoice, or free booking.
- Enter client contact details.
- Enter booking custom fields.
- See the waiver status/link after booking when applicable.
- See the payment or invoice result.
- Recover a card-payment result after returning from Stripe.
- View bookings created through their staff credential, if this scope is approved.
- View bookings assigned to them, if this scope is approved.

Staff should not automatically be able to:

- View all operator bookings.
- Create or edit calendars.
- Change prices or rates.
- Change availability rules.
- Delete calendars.
- Manage other staff members.
- Change Stripe Connect settings.
- Change waiver text.
- View unrelated customer records.

### B. Operator/Admin PWA

Primary route:

```text
/app
```

This is the installable standalone version of the current operator console.

Operator users should be able to:

- View today's and upcoming booking calendar.
- View all bookings permitted by their role.
- Search and filter bookings.
- Open full booking details.
- View payment status, invoice status, waiver status, customer details, participants, notes, resources, and GHL sync status.
- Create bookings for customers.
- Update booking time and quantity where allowed.
- Cancel bookings.
- Mark bookings completed or no-show.
- Apply weather closure outcomes where permitted.
- Assign and reassign staff.
- View staff conflicts.
- View notifications and failed GHL synchronization.
- Manually resynchronize GHL records.
- View reports.

Administrator/agency-owner users should additionally be able to:

- Create and update calendars.
- Configure calendar hours and date-specific hours.
- Configure pushed slots.
- Add and remove blocked dates.
- Configure resources and capacity.
- Configure customer types and rates.
- Configure locations and categories.
- Configure booking custom fields.
- Configure waiver text and policy.
- Manage staff and staff roles.
- Manage Stripe Connect settings.
- Issue and revoke staff booking links.

## 4. Authentication and credential design

### Phase 1: Staff PWA credential exchange

The current staff link token should not be used as an unrestricted bearer token for every new API. Instead, implement a short-lived exchange:

```text
GET  /staff-booking/{token}/context
POST /staff-auth/exchange
```

Suggested exchange request:

```json
{
  "token": "private-link-token",
  "device_name": "Alex iPhone"
}
```

Suggested exchange response:

```json
{
  "access_token": "short-lived-staff-jwt",
  "expires_in": 900,
  "staff": {
    "id": "uuid",
    "name": "Alex Smith",
    "operator_id": "uuid"
  },
  "scopes": [
    "staff_booking.create",
    "staff_booking.read_own"
  ]
}
```

Security requirements:

- Continue storing only a digest of the private token where the current schema supports it.
- Never log the raw token.
- Make the exchange token single-use or rotate it after exchange where practical.
- Store the short-lived access token in memory when possible.
- Do not store a long-lived raw token in `localStorage`.
- Remove the token from the visible URL with `history.replaceState()` after exchange.
- Keep link regeneration revocation behavior.
- Apply rate limits to exchange and staff booking routes.
- Enforce operator and staff ownership on every request.
- Use explicit scopes rather than trusting frontend route visibility.

### Phase 2: Standalone operator/admin login

The PWA needs a standalone login because the existing HighLevel embedded session requires a HighLevel iframe parent.

Recommended choices, in order:

1. **HighLevel OAuth / standalone authorization callback**, if the product is always used by HighLevel-connected operators and the OAuth flow can safely identify the location and user.
2. **Passwordless one-time login or magic link**, if a separate Passport identity is acceptable.
3. **Email/password with MFA**, only if Passport will own credential storage, password reset, lockout, and MFA security.

Do not copy the HighLevel encrypted iframe payload into the PWA or ask users to paste it into the PWA. It is not a suitable standalone credential.

The final choice must be confirmed before implementation because it changes database tables, security requirements, and the user experience.

### Role mapping

The existing backend permission model can be reused:

```text
VIEW_BOOKINGS
OPERATE_BOOKINGS
MANAGE_CONFIGURATION
MANAGE_PAYMENTS
DELETE_CONFIGURATION
```

The backend must remain the authority. Hiding a menu item in the PWA is not an authorization mechanism.

## 5. Existing APIs to reuse in the PWA

### Booking calendar and bookings

```text
GET  /api/v1/booking-slots?range_start=...&range_end=...
GET  /api/v1/bookings?range_start=...&range_end=...&calendar_id=...&status=...&search=...
GET  /api/v1/bookings/{booking_id}
PATCH /api/v1/bookings/{booking_id}
POST /api/v1/bookings/{booking_id}/cancel
POST /api/v1/bookings/{booking_id}/status
POST /api/v1/bookings/{booking_id}/weather-cancel
POST /api/v1/bookings
```

A booking list item currently contains:

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

The detail response also contains payment, waiver, participants, notes, resources, and HighLevel synchronization fields.

### Notes and participants

```text
GET    /api/v1/bookings/{booking_id}/participants
PUT    /api/v1/bookings/{booking_id}/participants
DELETE /api/v1/bookings/{booking_id}/participants/{participant_id}
POST   /api/v1/bookings/{booking_id}/notes
DELETE /api/v1/bookings/{booking_id}/notes/{note_id}
```

### Staff assignments

```text
GET    /api/v1/staff-assignments?range_start=...&range_end=...
GET    /api/v1/staff-assignments/candidates?calendar_id=...&start_at=...
POST   /api/v1/staff-assignments
PATCH  /api/v1/staff-assignments/{assignment_id}
DELETE /api/v1/staff-assignments/{assignment_id}
GET    /api/v1/staff-assignments/conflicts
```

### Calendar configuration

The current API already supports the main calendar management requirements:

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

Supporting configuration endpoints:

```text
GET/POST/PATCH/DELETE /api/v1/locations
GET/POST/PATCH/DELETE /api/v1/resources
GET/POST/PATCH/DELETE /api/v1/customer-types
GET/POST/PATCH/DELETE /api/v1/calendar-categories
```

The existing frontend already converts calendar prices from dollars to minor units at the API boundary. The PWA must use the same rule: display dollars, send `base_price_minor` and `price_minor` in minor units.

### Waivers and payments

```text
GET /api/v1/settings/waiver
PUT /api/v1/settings/waiver
GET /api/v1/public/waivers/{token}
POST /api/v1/public/waivers/{token}/sign
GET /api/v1/stripe/connect/status
POST /api/v1/stripe/connect/onboarding-link
```

The PWA should display waiver and payment status, but it must not expose Stripe secret keys or raw payment-card data.

### GHL synchronization and notifications

```text
GET  /api/v1/notifications
POST /api/v1/orders/{order_id}/retry-ghl-sync
POST /api/v1/orders/{order_id}/resync-ghl
```

The PWA should show synchronization state and manual resync controls to authorized operator users.

## 6. New APIs recommended for implementation

The existing APIs are sufficient for much of the first version, but these additions are recommended.

### Staff session endpoints

```text
POST /api/v1/staff-auth/exchange
POST /api/v1/staff-auth/refresh
POST /api/v1/staff-auth/revoke
GET  /api/v1/staff-auth/me
```

### Staff-scoped booking read endpoints

```text
GET /api/v1/staff-portal/bookings?range_start=...&range_end=...
GET /api/v1/staff-portal/bookings/{booking_id}
```

These must return only bookings allowed by the staff scope, such as:

- Bookings created using that staff link; or
- Bookings assigned to that staff member.

The rule must be selected explicitly before implementation. Do not silently return all operator bookings.

### PWA bootstrap endpoint

```text
GET /api/v1/pwa/bootstrap
```

Suggested response:

```json
{
  "user": {
    "id": "uuid",
    "name": "Alex Smith",
    "role": "admin",
    "is_agency_owner": false
  },
  "operator": {
    "id": "uuid",
    "name": "Example Operator",
    "slug": "example-operator",
    "time_zone": "America/New_York"
  },
  "permissions": [
    "view_bookings",
    "operate_bookings",
    "manage_configuration"
  ],
  "features": {
    "calendar_management": true,
    "staff_assignment": true,
    "reports": true,
    "waivers": true,
    "stripe_connect": false
  }
}
```

This avoids making the PWA call multiple configuration endpoints simply to decide which navigation items to display.

### Calendar management aggregate endpoint

The current calendar editor makes several requests. A PWA-specific aggregate endpoint can reduce mobile latency:

```text
GET /api/v1/calendar-management/{calendar_id}
```

Suggested response:

```json
{
  "calendar": "CalendarRead",
  "hours": ["CalendarHourRead"],
  "date_hours": ["CalendarDateHourRead"],
  "blocks": ["CalendarBlockRead"],
  "resources": ["CalendarResourceRead"],
  "rates": ["CalendarRateRead"],
  "categories": ["CategoryRead"],
  "locations": ["LocationRead"]
}
```

This endpoint should be read-only and use the existing service methods internally. Mutations should continue using the existing focused endpoints or a carefully designed transactional save endpoint.

### Booking summary endpoint

For mobile dashboards, add a compact summary endpoint:

```text
GET /api/v1/bookings/summary?range_start=...&range_end=...
```

Suggested response:

```json
{
  "range_start": "2026-10-16T00:00:00Z",
  "range_end": "2026-10-23T00:00:00Z",
  "totals": {
    "all": 24,
    "confirmed": 18,
    "pending_payment": 3,
    "cancelled": 3
  },
  "upcoming": ["BookingListItem objects"],
  "staff_conflicts": 1,
  "unresolved_notifications": 2
}
```

## 7. Database changes

### Staff PWA sessions

Add a migration only if the selected standalone credential flow needs durable sessions. A recommended table is:

```text
staff_app_sessions
- id UUID primary key
- operator_id UUID not null
- staff_id UUID not null
- token_digest TEXT unique not null
- scopes JSONB not null
- device_name TEXT null
- created_at TIMESTAMPTZ not null
- last_used_at TIMESTAMPTZ null
- expires_at TIMESTAMPTZ not null
- revoked_at TIMESTAMPTZ null
- created_ip INET null
```

Required indexes:

```text
(token_digest)
(operator_id, staff_id, revoked_at, expires_at)
```

Do not store raw refresh tokens. Store a digest and rotate refresh tokens.

### Standalone operator sessions

If a standalone operator login is added, use a separate session table rather than reusing staff links:

```text
operator_app_sessions
- id UUID primary key
- operator_id UUID not null
- app_user_id UUID not null
- refresh_token_digest TEXT unique not null
- auth_method TEXT not null
- created_at TIMESTAMPTZ not null
- last_used_at TIMESTAMPTZ null
- expires_at TIMESTAMPTZ not null
- revoked_at TIMESTAMPTZ null
```

Passwords, if ever introduced, require a separate credential table with password hashes, reset tokens, failed-attempt counters, lockout timestamps, and audit records. Password storage should not be added casually.

### Optional PWA push subscriptions

Push notifications are optional and should not be part of the first PWA milestone. If they are required later:

```text
pwa_push_subscriptions
- id UUID primary key
- operator_id UUID not null
- staff_id UUID null
- app_user_id UUID null
- endpoint TEXT unique not null
- p256dh TEXT not null
- auth TEXT not null
- user_agent TEXT null
- created_at TIMESTAMPTZ not null
- revoked_at TIMESTAMPTZ null
```

The first version can use in-app notifications and normal Passport staff reminders without adding browser push complexity.

### Existing booking schema

The PWA itself does not require changing booking, payment, waiver, or calendar tables if it reuses the existing API contracts. The important database work is authentication/session storage and indexes needed for staff-scoped reads.

Recommended indexes for PWA reads:

```text
bookings(operator_id, start_at, status)
booking_orders(operator_id, created_at, status)
staff_assignments(operator_id, staff_id, start_at, end_at)
public_access_credentials(operator_id, purpose, token_digest)
outbox_jobs(status, next_attempt_at)
```

Any migration must be forward-only and added to the repository's migration sequence. It must not modify production data destructively without a separate approved migration decision.

## 8. PWA technical design

### Manifest

The application should own its PWA manifest because it needs custom name, icons, colors, display mode, and start routes. Configure the platform PWA mode as application-owned before implementation and provide:

```text
frontend/public/manifest.webmanifest
frontend/public/icons/icon-192.png
frontend/public/icons/icon-512.png
frontend/public/icons/maskable-512.png
```

Suggested manifest behavior:

```json
{
  "name": "Passport Operations",
  "short_name": "Passport",
  "start_url": "/app",
  "display": "standalone",
  "background_color": "#f6f8f8",
  "theme_color": "#527a73",
  "icons": []
}
```

### Service worker

Cache only:

- Application shell assets
- Fonts and static icons
- Versioned JavaScript/CSS assets
- Non-sensitive route fallback content

Do not cache by default:

- Access tokens
- Customer personal data
- Payment data
- Waiver signatures
- Booking details in a shared browser cache
- API responses containing operator or staff records

Booking, availability, payment, waiver, staff assignment, and calendar mutations must require a live network connection. Offline mode should be limited to opening the shell and showing a clear offline state.

### Mobile navigation

The operator PWA should use a bottom navigation or compact mobile drawer:

```text
Today
Calendar
Bookings
Staff
More
```

The staff PWA should use a smaller navigation:

```text
Book
My bookings
Profile
```

### Mobile performance

The PWA should:

- Use route-level lazy loading.
- Use React Query cache with short stale times for live availability.
- Avoid aggressive polling when the app is backgrounded.
- Load booking details only after a user opens a booking.
- Use compact summary endpoints for the dashboard.
- Keep availability and payment states live.
- Never treat cached availability as confirmation that a slot is still available.

## 9. Proposed project structure

The first implementation should reuse the existing frontend rather than create a second unrelated application.

```text
frontend/
├── public/
│   ├── manifest.webmanifest
│   ├── icons/
│   └── sw.js or generated service-worker assets
├── src/
│   ├── app/
│   │   ├── PwaInstallPrompt.tsx
│   │   ├── PwaUpdatePrompt.tsx
│   │   └── pwa.ts
│   ├── auth/
│   │   ├── GHLSessionProvider.tsx
│   │   ├── StaffPwaSessionProvider.tsx
│   │   └── OperatorPwaSessionProvider.tsx
│   ├── staff-pwa/
│   │   ├── StaffPwaShell.tsx
│   │   ├── StaffPwaDashboard.tsx
│   │   ├── StaffPwaBookingForm.tsx
│   │   ├── StaffPwaBookings.tsx
│   │   └── StaffPwaProfile.tsx
│   ├── operator-pwa/
│   │   ├── OperatorPwaShell.tsx
│   │   ├── TodayPage.tsx
│   │   ├── CalendarPage.tsx
│   │   ├── BookingsPage.tsx
│   │   ├── CalendarManagementPage.tsx
│   │   └── MorePage.tsx
│   └── api/
│       ├── client.ts
│       ├── staffPwaApi.ts
│       └── operatorPwaApi.ts
└── vite.config.ts

backend/app/
├── api/v1/
│   ├── staff_auth.py
│   ├── operator_auth.py or standalone_auth.py
│   ├── pwa.py
│   └── existing routes reused by the PWA
├── services/
│   ├── staff_pwa_session_service.py
│   ├── standalone_auth_service.py
│   └── pwa_bootstrap_service.py
├── schemas/
│   ├── staff_auth.py
│   └── pwa.py
└── models/entities.py

supabase/migrations/
└── next migration for session tables and indexes only if required
```

## 10. Recommended implementation phases

### Phase 1 — PWA shell and restricted staff flow

- Add application-owned manifest and installable shell.
- Add responsive staff PWA route.
- Reuse the current staff booking APIs.
- Add safe staff-token exchange and short-lived staff session.
- Add staff booking dashboard and booking result screens.
- Preserve card, invoice, and free booking behavior.
- Keep the current `/staff-book/:token` route working.

### Phase 2 — Standalone operator authentication

- Select OAuth, passwordless, or another approved standalone login.
- Add secure session storage and refresh/revocation.
- Reuse existing permissions and `/me` response concepts.
- Add PWA bootstrap endpoint.
- Add role-based navigation and route guards.

### Phase 3 — Operator booking and calendar experience

- Add mobile today view.
- Add booking calendar view.
- Add all-bookings list with search/filter.
- Add booking detail, waiver, payment, customer, notes, participants, and staff assignment actions.
- Add GHL synchronization state and manual resync.

### Phase 4 — Calendar administration

- Add calendar create/update screens.
- Add hours and date-specific hours.
- Add pushed slots and blocked dates.
- Add resources and capacity mapping.
- Add rates and customer types.
- Add locations and categories.
- Add destructive-action protections.

### Phase 5 — Performance and operational hardening

- Add aggregate bootstrap and summary endpoints.
- Reduce duplicate polling.
- Lazy-load operator routes.
- Add staff-scoped query indexes.
- Confirm the PWA does not cache sensitive API responses.
- Add audit records for standalone authentication and privileged configuration changes.

## 11. Decisions required before implementation

The following choices materially affect the database and security design:

1. Should the PWA be for **staff only**, **operators/admins only**, or both?
2. Should a staff member see only bookings they created, only bookings assigned to them, or both?
3. Should staff be allowed to create calendars, or should calendar management be admin-only?
4. For standalone operator login, should the app use HighLevel OAuth, passwordless login, or another identity method?
5. Should the first PWA work offline only for the shell, or should it support cached read-only booking views?
6. Should browser push notifications be included in the first version?
7. Should the current one-year private booking link remain the credential, or should staff links expire sooner and require renewal?

## 12. Recommended default decisions

Unless you choose differently, the safest first implementation would use:

- Both staff and operator PWA modes.
- Staff booking links limited to booking creation plus staff-scoped booking history.
- Calendar creation/update restricted to administrator and agency-owner roles.
- Standalone operator authentication through an approved passwordless or OAuth flow, not the existing iframe-only session.
- Online-only booking/payment/configuration actions.
- Offline support limited to the application shell and a clear offline screen.
- No browser push notifications in the first release.
- The existing private link retained for compatibility, but exchanged for a short-lived scoped session.
- Existing backend booking, payment, waiver, calendar, and staff APIs reused wherever possible.

## 13. Important boundary

A PWA can make the application easier to install and use on phones, but it does not remove the need for backend authorization or background processing.

Availability, bookings, payments, waivers, calendar changes, and staff assignments remain server-controlled operations. The PWA should improve the interface and credential experience while Passport remains the source of truth.
