# HighLevel Marketplace Custom Trigger Setup for Passport

This guide configures a native **HighLevel Marketplace Workflow Custom Trigger** in the existing Passport GHL app. It does **not** use the Inbound Webhook workflow trigger.

The official HighLevel documentation describes the required flow as: create a trigger in the app's Workflow module, define its key and metadata, provide sample JSON, configure filters and custom variables, add a subscription URL, create an app version, and submit the module/version for review or testing.

## Before you start

You need:

- Access to the HighLevel Marketplace developer portal.
- Access to the existing Passport Marketplace app.
- The Passport backend deployed on a public HTTPS domain.
- A test HighLevel sub-account/location where the app is installed.
- The Passport subscription endpoint implemented and deployed before you activate a workflow.

The subscription URL will be:

```text
https://<passport-api-domain>/api/v1/integrations/marketplace/workflow-trigger/subscription
```

Do not use the HighLevel Inbound Webhook trigger and do not create a per-location webhook URL.

## Part 1 — Open the existing GHL Marketplace app

1. Open the HighLevel Marketplace developer portal: <https://marketplace.gohighlevel.com/>.
2. Sign in with the developer account that owns the Passport app.
3. Open **My Apps**.
4. Select the existing Passport/GHL app. Do not create a second app.
5. Open the app's **Build** section.
6. Open **Modules**.
7. Open the **Workflow** module.
8. Click **Create Trigger**.

HighLevel's current interface documents Marketplace Workflow Triggers under **Modules → Workflow**. The exact labels may vary slightly if HighLevel changes the developer portal UI.

## Part 2 — Enter the trigger information

Use these values:

```text
Name:
Passport Booking Created

Key:
passport_booking_created

Short description:
Starts a workflow when Passport creates a booking or publishes a booking lifecycle event.
```

Choose a clear workflow icon. In the summary/long description, enter:

```text
Passport sends booking, customer, payment, waiver, calendar, and staff information to this trigger. Use payment_status and confirmed to decide whether a customer confirmation should be sent.
```

The key is permanent after the trigger is created or published. Do not rename it, change its capitalization, or create a second spelling such as `passport-booking-created`.

## Part 3 — Add the sample trigger payload

In **Trigger Data** or **Sample JSON**, paste a representative payload like this:

```json
{
  "event_type": "booking_created",
  "schema_version": "1",
  "event_id": "booking_order_demo_created_v1",
  "idempotency_key": "booking_order_demo:workflow:booking_created:v1",
  "occurred_at": "2026-10-23T12:00:00Z",
  "source": "passport",
  "location_id": "ghl-location-id",
  "booking_order_id": "passport-order-id",
  "public_reference": "PS-DEMO1234",
  "booking_status": "confirmed",
  "payment_status": "succeeded",
  "payment_method": "card",
  "confirmed": true,
  "currency": "USD",
  "subtotal_amount": "100.00",
  "fees_and_taxes_amount": "13.00",
  "customer_total_amount": "113.00",
  "customer_first_name": "Alex",
  "customer_last_name": "Smith",
  "customer_full_name": "Alex Smith",
  "customer_email": "alex@example.com",
  "customer_phone": "+15555550123",
  "ghl_contact_id": "existing-ghl-contact-id",
  "calendar_name": "Sunset Boat Tour",
  "calendar_id": "passport-calendar-id",
  "start_at": "2026-10-25T15:00:00Z",
  "end_at": "2026-10-25T17:00:00Z",
  "timezone": "America/New_York",
  "location_name": "Main Marina",
  "waiver_required": true,
  "waiver_status": "unsigned",
  "waiver_url": "https://passport.example.com/public/waivers/demo-token",
  "staff_names": "Jordan Lee",
  "items": [
    {
      "name": "Adult ticket",
      "quantity": 2,
      "amount": "100.00"
    }
  ]
}
```

Use a real Passport-generated sample later through the test endpoint. The sample above only defines the fields that HighLevel will show in the filter and custom-variable pickers.

Never include a raw payment-card number, CVC, private integration token, GHL access token, or raw internal waiver token in the sample payload.

## Part 4 — Configure trigger filters

Create filters using the sample JSON references. Recommended filters are:

### Filter 1: Event Type

```text
Name: Event Type
Type: Select or Multi-Select
Reference: event_type
Options:
- booking_created
- booking_confirmed
- payment_updated
- waiver_signed
- booking_cancelled
- booking_rescheduled
```

### Filter 2: Payment Status

```text
Name: Payment Status
Type: Select or Multi-Select
Reference: payment_status
Options:
- succeeded
- requires_payment
- processing
- failed
- provider_unknown
- not_required
```

### Filter 3: Booking Status

```text
Name: Booking Status
Type: Select or Multi-Select
Reference: booking_status
Options:
- pending_payment
- confirmed
- cancelled
- rescheduled
- expired
```

Use the exact status values that Passport actually sends. If the application uses different values, use those values instead.

### Filter 4: Confirmed

```text
Name: Confirmed
Type: Select
Reference: confirmed
Options:
- true
- false
```

### Optional Filter 5: Calendar

```text
Name: Calendar
Type: Select
Reference: calendar_id
```

Use a Dynamic filter only if Passport has a deployed API endpoint that HighLevel can call to load calendar options. HighLevel allows only one Dynamic filter per trigger, so do not mark every filter as Dynamic. For the first version, Select filters are safer.

## Part 5 — Configure custom variables

Open **Custom Variables** and create variables by mapping each variable to the matching sample JSON reference.

Create at least these variables:

```text
Event Type              → event_type
Booking Reference       → public_reference
Booking Status          → booking_status
Payment Status          → payment_status
Payment Method          → payment_method
Confirmed               → confirmed
Customer First Name     → customer_first_name
Customer Last Name      → customer_last_name
Customer Full Name      → customer_full_name
Customer Email          → customer_email
Customer Phone          → customer_phone
GHL Contact ID          → ghl_contact_id
Calendar Name           → calendar_name
Start Time              → start_at
End Time                → end_at
Timezone                → timezone
Location Name           → location_name
Total Amount            → customer_total_amount
Currency                → currency
Waiver Required         → waiver_required
Waiver Status           → waiver_status
Waiver URL              → waiver_url
Staff Names             → staff_names
Passport Booking ID     → booking_order_id
Event ID                → event_id
```

Use simple labels in HighLevel. The value on the right is the reference key from the sample JSON.

## Part 6 — Configure the Subscription URL

In the trigger's **Subscription URL** section, choose **POST** and enter:

```text
https://<passport-api-domain>/api/v1/integrations/marketplace/workflow-trigger/subscription
```

If the Marketplace app UI allows custom headers, configure the verification header required by the Passport backend, for example:

```text
X-Passport-Marketplace-Signature: <configured-secret>
```

Do not place the secret in the frontend or in a public Git repository.

HighLevel will call this URL when a workflow creates, updates, or deletes a Passport trigger instance. The callback includes:

- `triggerData.id`
- `triggerData.key`
- `triggerData.filters`
- `triggerData.eventType`
- `triggerData.targetUrl`
- `meta.key`
- `meta.version`
- `extras.locationId`
- `extras.workflowId`
- `extras.companyId`

Passport should return:

```json
{
  "success": true
}
```

The Passport backend must store the `targetUrl` encrypted. It must never show the raw URL in the frontend or logs.

## Part 7 — Save and create an app version

1. Save the trigger configuration.
2. Verify the trigger key is exactly `passport_booking_created`.
3. Verify the sample JSON parses successfully.
4. Verify every custom-variable reference points to a sample JSON key.
5. Verify the subscription URL uses HTTPS.
6. Open **Manage → Versions**.
7. Create a new draft version of the existing app.
8. Include the new Workflow Custom Trigger module in that version.
9. Add a changelog entry such as:

```text
Added Passport Booking Created Marketplace Workflow Custom Trigger for customer booking automation.
```

10. Save the draft version.

A draft version may be suitable for the app owner's test environment, but it is not automatically available to every installed location. A version may need to be submitted for review and approved before it is available broadly.

## Part 8 — Submit for review or install for testing

For a test environment:

1. Use the HighLevel app testing/sandbox process.
2. Install the draft/private app version in the test location.
3. Confirm the Passport OAuth scopes and installation are working.
4. Confirm the trigger module appears in the location's Workflow Builder.

For production:

1. Submit the app version or trigger module for review as required by HighLevel.
2. Wait until the version is approved or otherwise made available to the production location.
3. Install or update the existing Passport app in the target location.
4. Confirm that the new version contains the trigger.

If the trigger does not appear, the most common causes are that the location still has an older app version, the trigger version is still draft-only, or the module has not completed the required review.

## Part 9 — Create the workflow in the GHL location

After the correct app version is installed:

1. Open the target HighLevel sub-account/location.
2. Go to **Automation → Workflows**.
3. Click **Create Workflow**.
4. Choose **Start from Scratch**.
5. Add a workflow trigger.
6. Find **Passport Booking Created** under the Marketplace/custom app triggers.
7. Select it.
8. Add the filter:

```text
Event Type equals booking_created
```

9. Save the workflow while it is still inactive/draft.

HighLevel should now send the subscription callback to Passport. Confirm that Passport returns HTTP `200` and records the location ID, workflow ID, trigger instance ID, filters, and encrypted execution target URL.

## Part 10 — Find or create the customer Contact

Marketplace Custom Triggers can run without a Contact. Email and SMS actions, however, need a Contact context.

Add one of these actions near the start of the workflow:

1. **Find Contact** using `ghl_contact_id` when Passport already has the HighLevel contact ID.
2. If no contact ID is available, find the contact by `customer_email` or `customer_phone`.
3. If no contact exists, use **Create/Update Contact**.
4. Map the first name, last name, email, and phone custom variables.
5. Optionally add the tag `passport-customer`.

Use an If/Else branch if you need to handle customers who provide only an email or only a phone number.

## Part 11 — Add the payment guard

Before sending any customer confirmation, add an **If/Else** action.

Use this logic:

```text
IF confirmed equals true
   OR payment_method equals none
       → customer confirmation branch

ELSE IF payment_status equals requires_payment
       → payment-required branch

ELSE IF payment_status equals processing
       → no confirmation yet

ELSE
       → no confirmation; log or notify for review
```

The confirmation branch can send the customer email and SMS. The payment-required branch should send payment instructions only if you intentionally want that behavior. Do not send a booking-confirmed message for a card or invoice booking that has not been paid.

## Part 12 — Add the customer email

In the confirmed branch:

1. Add **Send Email**.
2. Select the customer Contact created/found earlier.
3. Use the Marketplace trigger custom-variable picker.
4. Include:
   - Customer name.
   - Booking reference.
   - Calendar/service name.
   - Start date and time.
   - Timezone.
   - Location.
   - Total amount and currency.
   - Waiver instructions.
5. Add the waiver URL only when `waiver_status` is `unsigned` and `waiver_url` is not empty.

Example email text:

```text
Subject: Booking {{public_reference}} confirmed

Hi {{customer_first_name}},

Your {{calendar_name}} booking is confirmed for {{start_at}}.

Booking reference: {{public_reference}}
Location: {{location_name}}
Total: {{customer_total_amount}} {{currency}}

Please sign your waiver here if required:
{{waiver_url}}
```

Select the variables from HighLevel's picker instead of manually guessing merge-field syntax.

## Part 13 — Add the customer SMS

After the email, add **Send SMS** in the same confirmed branch.

Example:

```text
Hi {{customer_first_name}}, your booking {{public_reference}} for {{calendar_name}} is confirmed for {{start_at}}. Waiver: {{waiver_url}}
```

Create a separate If/Else branch when the waiver URL is empty so the SMS does not end with a broken or blank link.

Keep staff assignment messages and staff operational reminders in Passport, as requested. HighLevel should handle customer-facing email/SMS automation only.

## Part 14 — Test the complete flow

Run these tests before activating the workflow:

1. Free booking.
2. Card booking before payment confirmation.
3. Card booking after successful payment.
4. Invoice booking before payment.
5. Invoice booking after payment.
6. Booking with an unsigned waiver.
7. Booking with a signed waiver.
8. Customer with email and phone.
9. Customer with email only.
10. Customer with phone only.
11. Booking created by staff.
12. Booking created through the public booking link.
13. Booking cancellation or update if those events are included in the trigger version.

For every test, check:

- Passport created the booking.
- Passport created or updated the GHL contact.
- HighLevel received the Marketplace trigger event.
- The workflow execution appears in HighLevel history.
- A payment-pending booking did not receive a false confirmation.
- The waiver link is present only when appropriate.
- Staff reminders remain in Passport.
- A repeated delivery does not send duplicate messages.

Keep the workflow inactive until all tests pass. Then activate it and monitor the first production bookings.

## Common problems

### The trigger is not visible in the workflow builder

Check that the target location has the latest Passport app version installed, the trigger is included in that version, the app/module is available to the location, and any required Marketplace review has completed.

### The trigger appears but Passport does not receive a subscription callback

Check that the subscription URL is public HTTPS, the endpoint returns HTTP `200`, the URL is not pointing to the frontend domain, and the Passport backend accepts the exact HighLevel request shape.

### The workflow runs but email/SMS actions do not send

The trigger can be contactless. Add Find Contact or Create/Update Contact before the email/SMS action and ensure the workflow has a valid Contact context.

### The workflow sends a confirmation before payment

Inspect the If/Else condition. The confirmation branch must require `confirmed = true` or a payment method that does not require payment. Do not use only `booking_status = pending_payment` as a confirmation condition.

### The field is not available in the workflow variable picker

Update the sample JSON in the Marketplace trigger, save a new trigger version, and reinstall/update the app version in the test location. Custom variables are generated from the trigger sample data.

## Official references

- [HighLevel Marketplace Workflow Triggers](https://marketplace.gohighlevel.com/docs/marketplace-modules/CustomTriggers/)
- [HighLevel Create a Marketplace App](https://marketplace.gohighlevel.com/docs/oauth/CreateMarketplaceApp/)
- [HighLevel App Testing Guide](https://marketplace.gohighlevel.com/docs/oauth/AppTestingGuide)
