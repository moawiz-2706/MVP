# GHL Custom Trigger Workflow Workaround

## Short answer

Yes. We can remove the Passport Booking Custom Object from the design.

The simpler architecture is:

1. Passport creates or updates the GHL Contact.
2. Passport creates or updates the GHL calendar appointment.
3. Passport sends a JSON payload to a GHL **Inbound Webhook / Custom Trigger**.
4. The GHL workflow reads the payload and sends the customer email and SMS.
5. Passport remains responsible for staff assignment messages and staff reminders.

This avoids storing booking information in GHL custom objects and avoids manually configuring object field IDs.

## Important distinction

The GHL Custom Trigger is a workflow event, not a permanent booking database.

The booking payload is available during the workflow execution and can be used in:

- If/Else conditions
- Email content
- SMS content
- Contact creation/update
- Workflow logging and actions

Passport remains the permanent source of truth for booking, payment, waiver, and staff data. The GHL calendar appointment remains the source of the GHL calendar date/time record.

HighLevel documents this capability as the **Inbound Webhook Workflow Premium Trigger**. An external application sends a JSON request to the generated URL, and the workflow can use the incoming values in email, SMS, conditions, and other actions. [1]

## Booking flow

```text
Public booking link or staff booking link
        ↓
Passport creates the local booking
        ↓
Passport creates/updates the GHL Contact
        ↓
Passport creates/updates the GHL calendar appointment
        ↓
Passport sends booking JSON to the GHL Custom Trigger URL
        ↓
GHL creates/updates the Contact if needed
        ↓
GHL checks payment and booking status
        ↓
GHL sends the customer email and SMS
```

The public and staff booking endpoints already share `OrderService.create()`, so one integration service can send the same payload for both booking methods.

## Payload Passport should send

Use a flat JSON payload. Flat fields are easier to map in the GHL workflow than deeply nested objects.

```json
{
  "event_type": "booking_created",
  "event_id": "booking:LOCAL_BOOKING_ID:confirmed",
  "source": "public_booking_link",
  "booking_id": "LOCAL_BOOKING_ID",
  "booking_reference": "PASSPORT-ABC123",
  "booking_status": "confirmed",
  "payment_status": "succeeded",
  "payment_method": "card",
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@example.com",
  "phone": "+15551234567",
  "service_name": "Kayak Tour",
  "quantity": 2,
  "start_at": "2026-10-16T15:00:00Z",
  "end_at": "2026-10-16T17:00:00Z",
  "time_zone": "America/New_York",
  "currency": "USD",
  "subtotal": "100.00",
  "booking_fee": "10.00",
  "tax": "15.00",
  "total": "125.00",
  "waiver_url": "https://passport.example/waivers/secure-token",
  "waiver_status": "pending",
  "waiver_expires_at": "2026-11-15T00:00:00Z",
  "ghl_contact_id": "GHL_CONTACT_ID",
  "ghl_appointment_id": "GHL_APPOINTMENT_ID",
  "marketing_opt_in": false
}
```

### Recommended event types

Use different event IDs for different business events:

- `booking_created` — free booking already confirmed.
- `payment_confirmed` — card or invoice booking became confirmed.
- `booking_cancelled` — optional future customer-cancellation workflow.
- `booking_rescheduled` — optional future customer-reschedule workflow.

The `event_id` must be deterministic, for example:

```text
booking:{booking_id}:booking_created
booking:{booking_id}:payment_confirmed
```

This allows Passport to avoid sending the same event twice.

## Payment-state protection

Do not allow the GHL workflow to send a confirmation for an unpaid booking.

### Free booking

Send:

```json
{
  "event_type": "booking_created",
  "booking_status": "confirmed",
  "payment_status": "succeeded",
  "payment_method": "none"
}
```

### Card booking

At initial checkout, the local booking is usually `pending_payment`. Do not send a customer confirmation at that stage.

After Stripe confirms payment, send:

```json
{
  "event_type": "payment_confirmed",
  "booking_status": "confirmed",
  "payment_status": "succeeded",
  "payment_method": "card"
}
```

### Invoice booking

At creation, keep the booking as `pending_payment`. After Stripe confirms the invoice as paid, send the `payment_confirmed` event.

### Workflow guard

The workflow should include an If/Else condition such as:

```text
Continue only when:
booking_status = confirmed
AND payment_status = succeeded OR payment_method = none
AND event_type is booking_created OR payment_confirmed
```

The exact variable names must be selected from the trigger's mapping picker after the sample payload is loaded.

## Step-by-step GHL setup

### 1. Create the trigger workflow

1. Open the correct GHL sub-account/location.
2. Go to **Automation → Workflows**.
3. Create a new workflow.
4. Select **Inbound Webhook** or **Custom Trigger**, depending on the label shown in the account.
5. Copy the generated webhook URL.
6. Keep the URL private. It acts as a secret trigger address.

HighLevel currently describes this as a Premium Trigger. The account or agency must have Premium Triggers enabled. [1]

### 2. Send a sample request

Send one sample JSON request from Passport or from a test tool to the generated URL.

Use a real test email and phone number:

```bash
curl -X POST 'GHL_TRIGGER_URL' \
  -H 'Content-Type: application/json' \
  --data '{
    "event_type": "booking_created",
    "event_id": "test-booking-001",
    "booking_reference": "TEST-001",
    "booking_status": "confirmed",
    "payment_status": "succeeded",
    "payment_method": "none",
    "first_name": "Test",
    "last_name": "Customer",
    "email": "your-test-email@example.com",
    "phone": "+15551234567",
    "service_name": "Test Activity",
    "quantity": 1,
    "start_at": "2026-10-16T15:00:00Z",
    "end_at": "2026-10-16T17:00:00Z",
    "currency": "USD",
    "total": "25.00",
    "waiver_url": "https://example.com/test-waiver",
    "waiver_status": "pending"
  }'
```

7. In GHL, click **Test Trigger**.
8. Select the latest sample request.
9. Save it as the mapping reference.
10. Confirm that the individual booking, waiver, payment, and Contact fields appear in the variable picker.

HighLevel requires JSON, and keys should not contain spaces. Email or phone should be included when the workflow needs to create or update a Contact. [1]

### 3. Create or update the Contact

After the trigger, add **Create/Update Contact**.

Map:

- First Name → `first_name`
- Last Name → `last_name`
- Email → `email`
- Phone → `phone`

Because Passport already creates/updates the Contact before sending the trigger, this action is a safety net and keeps the workflow usable if a Contact was not created by Passport.

If Passport sends the GHL Contact ID and the GHL UI supports Find Contact by ID, use it. Otherwise, email or phone is sufficient for Contact matching.

### 4. Add the payment guard

Add **If/Else** after Contact creation/update.

Recommended branch:

```text
booking_status equals confirmed
AND (
  payment_status equals succeeded
  OR payment_method equals none
)
```

The false branch should end without sending a customer confirmation.

### 5. Add the customer email

On the confirmed branch:

1. Add **Send Email**.
2. Select the workflow Contact as the recipient.
3. Create the confirmation email.
4. Insert trigger variables using the GHL variable picker.

Example content:

```text
Hi {{first_name}},

Your booking {{booking_reference}} for {{service_name}} is confirmed.

Date/time: {{start_at}}
Quantity: {{quantity}}
Total: {{currency}} {{total}}

Please complete your waiver here:
{{waiver_url}}

Thank you.
```

The exact merge syntax should be selected from the trigger variable picker. Do not manually type a token until GHL displays the saved mapping reference.

### 6. Add the customer SMS

On the same confirmed branch:

1. Add **Send SMS**.
2. Select the workflow Contact as the recipient.
3. Use the trigger variables for booking reference, service, time, and waiver URL.

Example:

```text
Hi {{first_name}}, your {{service_name}} booking {{booking_reference}} is confirmed for {{start_at}}. Complete your waiver: {{waiver_url}}
```

The SMS action requires a valid Contact phone number and the appropriate GHL messaging configuration.

### 7. Publish and test

Test all of these cases:

- Free booking through the public booking link.
- Free booking through the staff booking link.
- Card booking before payment.
- Card booking after payment succeeds.
- Invoice booking before payment.
- Invoice booking after payment succeeds.
- Missing phone number.
- Missing email address.
- Waiver pending.
- Waiver already signed.
- Duplicate delivery of the same `event_id`.

The expected result is one email and one SMS only after the booking is confirmed and paid/free.

## Passport implementation changes

### Keep

- `GHLContactService` for Contact creation/update.
- `GHLAppointmentService` for calendar synchronization.
- Existing three-attempt GHL synchronization behavior.
- Manual GHL resynchronization and error notification behavior.
- Passport reminder scheduling for staff.

### Add

Create a service such as:

```text
GHLWorkflowTriggerService
```

Responsibilities:

1. Build the flat booking payload.
2. Include waiver summary and secure waiver URL.
3. Include payment and booking status.
4. Include `source` as public or staff booking.
5. Send a POST request to the configured GHL trigger URL.
6. Retry immediately up to three times.
7. Record the event ID, attempt number, response status, and error.
8. Provide a manual resync endpoint.

The request should happen after the local database transaction commits. A GHL failure must not roll back a valid Passport booking.

### Do not use the Custom Object

The following are no longer needed for this design:

- Passport Booking custom object.
- Object field mappings.
- Object schema lookup.
- Contact-to-object association.
- Object record search/create/update.

## Minimal database changes

This approach needs fewer database changes than the Custom Object design.

### Configuration table

Add or extend a per-operator GHL workflow configuration with:

- `operator_id`
- `booking_trigger_url_encrypted`
- `enabled`
- `last_verified_at`
- `last_error`

The webhook URL should be encrypted at rest because possession of the URL can allow an outside party to trigger the workflow.

### Delivery table or sync extension

Reuse the existing GHL sync run/attempt diagnostics if practical. Otherwise add a small delivery table containing:

- `operator_id`
- `booking_order_id`
- `event_id` unique per booking event
- `event_type`
- `payload_hash`
- `status`
- `attempt_count`
- `last_http_status`
- `last_error`
- `sent_at`

The unique `event_id` prevents duplicate customer messages during retries or repeated webhook processing.

This does not require a cron job or scheduled outbox worker for the normal path. The three retries happen immediately in the request/webhook path after commit. The database record is only for diagnostics, idempotency, and manual resync.

## Staff reminders remain in Passport

The current repository already calculates staff reminders through `ReminderService` and queues them for the internal cron/outbox process.

However, the current delivery implementation calls `GHLEmailService`, which sends through GHL. To make staff reminders truly originate from Passport, replace the staff delivery adapter with a Passport-owned email/SMS provider while retaining the existing scheduling and retry logic.

Customer messages:

```text
GHL Custom Trigger → GHL Email/SMS
```

Staff messages:

```text
Passport ReminderService → Passport notification provider
```

## Important limitations

1. A Custom Trigger payload is not permanent booking storage in GHL. Passport remains the source of truth.
2. If the GHL trigger URL is leaked, it must be deleted and regenerated in GHL, then updated in Passport. HighLevel documents this behavior. [1]
3. GHL workflow execution and delivery logs should be monitored separately from Passport sync status.
4. Payment guards are mandatory so pending card/invoice bookings do not send false confirmations.
5. The GHL calendar appointment still needs to be synchronized separately. The Custom Trigger does not automatically create a calendar event unless the workflow is explicitly configured to do so.

## Recommendation

Use this Custom Trigger design instead of the Custom Object design.

It is simpler, requires fewer database tables, avoids custom-object associations, supports all booking/waiver/payment fields in the workflow payload, and is a better match for the requirement that GHL only handles customer email/SMS automation.

### Sources

[1]: https://help.gohighlevel.com/support/solutions/articles/48001237383-how-to-use-the-inbound-webhook-workflow-premium-trigger "HighLevel: How to use the Inbound Webhook Workflow Premium Trigger"
[2]: https://help.gohighlevel.com/support/solutions/articles/155000003305-workflow-action-custom-webhook "HighLevel: Workflow Action - Custom Webhook"
