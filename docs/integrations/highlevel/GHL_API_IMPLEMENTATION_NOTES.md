# HighLevel API Implementation Notes

Verified on 2026-10-08 against the official HighLevel v3 API documentation.

## Sources

- [Create appointment](https://marketplace.gohighlevel.com/docs/ghl/calendars/create-appointment/)
- [Update appointment](https://marketplace.gohighlevel.com/docs/ghl/calendars/edit-appointment/)
- [Update contact](https://marketplace.gohighlevel.com/docs/ghl/contacts/update-contact/)
- [Get location custom fields](https://marketplace.gohighlevel.com/docs/ghl/locations/get-custom-fields/)

## Confirmed contract

- Contact update accepts `customFields` as an array of objects containing `id`, `key`, and `fieldValue`.
- HighLevel appointment create/update supports standard fields such as title, description, status, calendar, contact, start/end time, assigned user, and `toNotify`.
- The documented appointment create/update request schemas do **not** expose an appointment `customFields` property.
- `toNotify: false` suppresses HighLevel automations; synchronous Passport mode therefore uses `toNotify: true` so GHL-owned workflows can run.
- Custom-field IDs are location-specific and must be stored per operator/location, not hardcoded globally.

## Passport decision

- Use standard appointment fields and the description for booking-specific context.
- Use mapped **contact** custom fields for waiver URL/status, booking reference, payment status, and other workflow values.
- Do not send signatures, DOB, address, emergency contact data, or full waiver text.
- Because contact fields are shared across a customer, multi-booking values must be treated as a latest/order aggregate. The appointment description remains the per-booking correlation source.
