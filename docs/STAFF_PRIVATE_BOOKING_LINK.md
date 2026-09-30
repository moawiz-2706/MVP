# Private Staff Mobile Booking Link

## Goal

Each active Passport staff member can receive a private, revocable mobile booking link. The link is not the public customer booking page and does not expose the authenticated Passport operator app.

A staff member using the link can:

1. Select an active calendar.
2. Select a date.
3. Select only a live available slot returned by Passport's availability engine.
4. Enter the client's contact details and configured custom fields.
5. Choose **Send invoice to client** or **Book free appointment**.

## Security contract

- Account owners/admins generate or rotate the link from the Staff page.
- The database stores only a SHA-256 digest of the bearer token.
- Rotating a link revokes the previous link immediately.
- Inactive or deleted staff cannot use a link.
- The link is scoped to one staff record and one operator/subaccount.
- No HighLevel iframe session or client card details are required on mobile.
- The link is intentionally a bearer credential. It must be shared privately and regenerated if exposed.

## API

- `POST /api/v1/staff/{staff_id}/booking-link` — authenticated admin; revokes the prior token and returns the new one-time-visible link path and expiry.
- `GET /api/v1/staff-booking/{token}/context` — token-authenticated; returns staff name, operator name/time zone, and active calendars.
- `GET /api/v1/staff-booking/{token}/calendars/{calendar_id}/availability?date=YYYY-MM-DD` — token-authenticated live slots.
- `GET /api/v1/staff-booking/{token}/calendars/{calendar_id}/rates` — token-authenticated active rates.
- `GET /api/v1/staff-booking/{token}/calendars/{calendar_id}/custom-fields` — token-authenticated custom fields.
- `POST /api/v1/staff-booking/{token}/orders` — token-authenticated team booking; `payment_required=true` creates/sends a hosted invoice and leaves the booking pending until payment, while `false` confirms a free appointment immediately.

The staff booking order delegates to the same `OrderService` and payment/outbox/webhook pipeline as authenticated operator bookings. Public customer checkout behavior is unchanged.

## Deployment requirement

Apply migrations `032_private_staff_booking_links.sql` and `033_fix_staff_booking_purpose_constraint.sql` before generating links. Migration 033 is required for existing databases because the original public-access table used an unnamed PostgreSQL purpose constraint that otherwise rejects the new `staff_booking` purpose.
