# HighLevel workflows for Passport messages

Who sends what:

| Message | Sent by | How |
|---|---|---|
| Customer booking confirmation (email + SMS, with waiver link) | **HighLevel workflow** | "Passport Booking Created" trigger |
| Customer reminders (day before, same day) | **Passport** | HighLevel Conversations API, templates in Passport → Settings → Messages |
| Staff assignment, unassignment and reminders | **Passport** | Same |
| Cancellation, weather cancellation, reschedule | **Passport** (templates on) | Same. Do not also build workflows for these, or customers get two messages. |
| Waiver status on the Passport Booking record | **Passport** | Updated when the booking changes and the moment a waiver is signed |

Passport's own confirmation template is switched off, so the workflow is the only confirmation.

## 1. HighLevel app setup (once)

In the Marketplace developer portal, the Passport app needs these scopes. After saving, re-authorize the app in the sub-account:

- `workflows.readonly`: the custom trigger
- `conversations/message.write` (with `conversations.readonly`/`conversations.write` if offered): Passport's reminders and staff emails
- `objects/record.readonly`, `objects/record.write`, `associations.readonly`, `associations/relation.write`: Passport Booking records
- the existing calendars, calendar events, contacts, locations and users scopes

In Vercel: `GHL_WORKFLOW_TRIGGER_ENABLED=true`, `GHL_NOTIFICATIONS_ENABLED=true`, `GHL_BOOKING_RECORD_SYNC_ENABLED=true`.

## 2. New trigger version (for the new variables)

In the developer portal, open **Modules → Workflow → Passport Booking Created → + New Version**:

1. Replace the sample payload with the one below. Keep the key `passport_booking_created`.
2. Under **Custom Variables**, add the new ones: `tour_start_local`, `tour_end_local`, `tour_date`, `tour_type`, `number_of_guests`, `source_partner`, `gross_booking_amount`, `hotel_commission_20pct`, `pga_commission_30pct`, `net_to_operator`, `gratuity_amount`.
3. Keep the subscription URL and its `X-Passport-Trigger-Secret` header.
4. Submit the version for review. Workflows can use the new variables once it is live.

```json
{
  "event_type": "booking_confirmed",
  "schema_version": "1",
  "event_id": "order-id:booking_confirmed:v1",
  "idempotency_key": "booking_order:order-id:workflow:booking_confirmed:v1",
  "occurred_at": "2026-12-01T14:00:00Z",
  "source": "passport",
  "location_id": "ghl-location-id",
  "booking_order_id": "passport-order-id",
  "public_reference": "RM-DEMO1234",
  "booking_status": "confirmed",
  "payment_status": "succeeded",
  "payment_method": "card",
  "confirmed": true,
  "currency": "USD",
  "subtotal_amount": "118.00",
  "fees_and_taxes_amount": "15.34",
  "customer_total_amount": "133.34",
  "customer_first_name": "Alex",
  "customer_last_name": "Smith",
  "customer_full_name": "Alex Smith",
  "customer_email": "alex@example.com",
  "customer_phone": "+15555550123",
  "ghl_contact_id": "existing-ghl-contact-id",
  "calendar_name": "\"The Oasis\" BYOB Sunset Cruise - Public",
  "calendar_id": "passport-calendar-id",
  "start_at": "2026-12-09T22:15:00Z",
  "end_at": "2026-12-10T00:15:00Z",
  "timezone": "America/New_York",
  "location_name": "Laishley Park Marina Public Dock",
  "waiver_required": true,
  "waiver_status": "unsigned",
  "waiver_url": "https://mvp-one-hazel.vercel.app/waiver/demo-token",
  "staff_names": "Jordan Lee",
  "items": [
    {
      "name": "Adult (13+)",
      "quantity": 2,
      "amount": "118.00",
      "booking_status": "confirmed",
      "calendar_id": "passport-calendar-id",
      "calendar_name": "\"The Oasis\" BYOB Sunset Cruise - Public",
      "start_at": "2026-12-09T22:15:00Z",
      "end_at": "2026-12-10T00:15:00Z"
    }
  ],
  "source_partner": "Sunseeker",
  "gross_booking_amount": "118.00",
  "hotel_commission_20pct": "23.60",
  "pga_commission_30pct": "35.40",
  "net_to_operator": "59.00",
  "gratuity_amount": "0.00",
  "number_of_guests": 2,
  "tour_date": "2026-12-09",
  "tour_type": "Public Cruises",
  "tour_start_local": "Wednesday, December 9, 2026 at 5:15 PM",
  "tour_end_local": "7:15 PM"
}
```

## 3. Workflow: booking confirmation

**Automation → Workflows → Create workflow → Start from scratch**, named "Passport – Booking confirmation".

1. **Trigger:** *Passport Booking Created* (under the Passport app's triggers).
   - Filter **Event Type** is any of `booking_created`, `booking_confirmed`.
   - Filter **Confirmed** is `true`.

   This sends free bookings at creation, and card/invoice bookings only after payment succeeds. Never filter on `booking_created` alone: a card booking is created as `pending_payment` with `confirmed: false`.
2. **Find Contact:** look up by **Contact ID** = `ghl_contact_id` from the trigger (or by email = `customer_email`). Marketplace triggers start without a contact, so this step is needed before email or SMS.
3. **Send Email** to the contact:
   - Subject: `You're booked: {{calendar_name}} – {{public_reference}}`
   - Body (insert each value from the trigger's variables):
     - Hi `customer_first_name`, your booking is confirmed.
     - When: `tour_start_local` to `tour_end_local`
     - Where: `location_name`
     - Guests: `number_of_guests` · Total paid: `customer_total_amount` `currency`
     - Reference: `public_reference`
     - An **If/Else** on `waiver_status` = `unsigned` for the waiver paragraph: "Please sign your waiver before you arrive: `waiver_url`"
4. **Send SMS** (if the contact has a phone): "Booked! `calendar_name`, `tour_start_local`. Ref `public_reference`. Waiver: `waiver_url`"
5. **Settings:** turn on **Allow re-entry**, so a returning customer's next booking also gets a confirmation.

Until the new trigger version is live, use `start_at` (UTC) or leave the time out. `waiver_url`, `public_reference`, `calendar_name` and `location_name` are already in v1.0.

## 4. Checking it

- Passport booking drawer → **HighLevel workflow trigger** shows delivered or failed per event, with a retry button.
- HighLevel workflow **Execution logs** show each run and which filter stopped it.
- Passport Booking record (Contacts → the contact → associated Passport Bookings) shows `payment_status` and `waiver_status`. `waiver_status` turns to `signed` within about a minute of signing.
EOF
cd "C:/Users/PC/AppData/Local/Temp/claude/D--MVP-main/79fc2744-b017-49bf-b60c-17c0a6353f74/scratchpad/wfwt"; git add -A; git commit -q -F - <<'EOF'
Add the tour's local start and end time to the trigger payload

Customer confirmations need a readable time; start_at is UTC. New
tour_start_local ("Wednesday, December 9, 2026 at 5:15 PM") and
tour_end_local ("7:15 PM") in the operator's time zone, after the existing
keys. Adds docs/integrations/highlevel/WORKFLOW_SETUP.md: who sends which
message, required scopes, the sample payload for the next trigger version,
and the confirmation workflow steps.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
git push -q -u origin feature/trigger-local-time 2>&1 | grep -v "^remote:\s*$" | tail -1