# GHL Customer Automation and Passport Staff Reminders Plan

## Scope

This plan is for the clean clone of `https://github.com/moawiz-2706/MVP.git` at commit `a0e1c1d`.

The requested split is:

- **HighLevel owns customer email and SMS automation** after a booking is ready for customer notification.
- **Passport owns staff follow-up messages and staff reminders**.
- Public booking links and private staff booking links must produce the same GHL customer/contact/booking projection.
- Passport must store one booking record in a HighLevel `Passport Booking` custom object and associate it with the customer Contact.
- Field IDs should be resolved by field name. The implementation must not require manually entering every field ID.

No application code or database schema is changed by this plan.

## What the clean repository does today

### Public and staff bookings use the same creation path

The public booking endpoint and the private staff booking endpoint both end in `OrderService.create()`.

The staff route is:

```text
POST /api/v1/staff-booking/{token}/orders
```

It calls `OrderService.create(..., allow_payment_override=True, allow_private_operator=True)`. The public booking route also uses `OrderService.create()`.

This is useful because the GHL projection can be implemented once in the shared order lifecycle instead of creating separate public and staff integrations.

### Contact creation/update already exists

`GHLContactService.sync(order_id)` currently:

1. Looks for an existing Contact by the saved GHL contact ID.
2. Otherwise looks for an exact email match.
3. Falls back to an exact normalized phone match.
4. Creates or updates the Contact.
5. Saves the returned GHL Contact ID in Passport.
6. Adds the `passport-customer` tag.

The contact operation must remain idempotent. Repeated retries must update the same Contact rather than create another Contact.

### Appointment synchronization already exists

`GHLAppointmentService.sync(booking_id)` already sends the following information to the GHL calendar appointment:

- GHL calendar ID
- Contact ID
- Title
- Description
- Start time
- End time
- Appointment status
- Assigned GHL user when Passport has a valid staff assignment

The appointment description already contains the booking reference, service, customer details, payment status, staff, resources, and waiver information.

### Synchronous retry infrastructure already exists

`GHLSyncService` already performs up to three short synchronous attempts and records:

- A durable synchronization run.
- Each individual provider attempt.
- The provider HTTP status.
- A normalized error code.
- The remote Contact or appointment ID.
- A final failed or manual-review state.

The clean clone currently synchronizes synchronously only when:

```env
GHL_SYNC_MODE=synchronous
```

Otherwise it uses the outbox path.

### Current messaging ownership must be changed

The current clean repository still contains GHL-owned messaging jobs such as:

- `ghl_send_confirmation_email`
- `ghl_booking_reminder`
- `ghl_staff_assigned_email`
- `ghl_staff_reminder`
- `ghl_staff_unassigned_email`
- `ghl_booking_cancellation_email`
- `ghl_booking_weather_email`
- `ghl_booking_reschedule_email`

The current `GHLEmailService` sends those messages through GHL. That does not match the requested final ownership split.

The customer message jobs must be removed from the Passport message path. Staff message jobs must be redirected to a Passport-owned notification provider instead of `GHLEmailService`.

## Recommended end-to-end data flow

### Public booking link

```text
Customer submits public booking
        ↓
Passport validates availability and creates the local order/booking
        ↓
Passport creates or updates the GHL Contact
        ↓
Passport creates or updates the GHL calendar appointment
        ↓
Passport creates or updates one GHL Passport Booking record
        ↓
Passport associates the Passport Booking record with the Contact
        ↓
HighLevel Custom Object workflow runs
        ↓
HighLevel sends customer email and SMS
```

### Staff booking link

```text
Staff submits private booking link
        ↓
The same Passport OrderService creates the local order/booking
        ↓
Passport creates or updates the same GHL Contact flow
        ↓
Passport creates or updates the same GHL appointment flow
        ↓
Passport creates or updates the same Passport Booking object flow
        ↓
HighLevel sends customer email and SMS
        ↓
Passport separately sends staff assignment/follow-up/reminder messages
```

There must not be separate customer-notification implementations for public and staff bookings.

## Payment-state rule

A booking can initially be `pending_payment` for card or invoice payments. Sending a customer confirmation immediately at object creation would be incorrect.

The object workflow must use the booking and payment status as a guard:

- Free booking: object is created with `confirmed` and the customer confirmation may run immediately.
- Card booking: object may be created with `pending_payment`; do not send the confirmation yet. After Stripe confirms payment, Passport updates the object to `confirmed` and the confirmation workflow runs.
- Invoice booking: object may be created with `pending_payment`; do not send the confirmation yet. After the invoice is paid, Passport updates the object to `confirmed` and the confirmation workflow runs.
- Payment failure, invoice expiry, or cancellation: update the object status and do not send a confirmation message.

Use both triggers where the HighLevel account exposes them:

1. **Passport Booking Created** with a condition that the booking is already confirmed.
2. **Passport Booking Changed** when `Passport Booking Status` changes to `confirmed` and `Passport Payment Status` is `succeeded` or `none`.

Configure the confirmation workflow so the same booking cannot re-enter the confirmation path repeatedly.

HighLevel documents Custom Object Created and Custom Object Changed workflow triggers. [1]

## HighLevel object configuration

Create this object in the target GHL location:

```text
Singular label: Passport Booking
Plural label: Passport Bookings
Primary display field: Passport Booking Reference
Internal name: passport_booking
```

Create these object fields:

- `Passport Booking ID` — Single Line Text, unique.
- `Passport Booking Reference` — Single Line Text.
- `Passport Booking Status` — Single Line Text.
- `Passport Payment Status` — Single Line Text.
- `Passport Service Name` — Single Line Text.
- `Passport Quantity` — Number.
- `Passport Total` — Number or Monetary.
- `Passport Currency` — Single Line Text.
- `Passport Waiver URL` — URL.
- `Passport Waiver Status` — Single Line Text.
- `Passport Waiver Expires At` — Single Line Text.
- `Passport GHL Appointment ID` — Single Line Text.

Do not use the object to replace the GHL calendar appointment. The appointment remains the source for appointment date/time and calendar assignment. The object is the durable booking projection used by workflows and booking history.

HighLevel Custom Objects have their own fields, associations, and object-based workflows. HighLevel also supports unique fields for supported field types, which is useful for the Passport booking ID. [2]

## Contact association

Create a paired Contact-to-Passport Booking association:

```text
Contact-side label: Has Booking
Passport Booking-side label: Booked By
Relationship: Contact one-to-many Passport Bookings
Limit on Passport Booking side: one Contact
```

This means:

- One customer Contact can have many Passport Booking records.
- One Passport Booking record belongs to one primary customer Contact.

Do not use many-to-many for the current code. Many-to-many would allow one booking to belong to multiple Contacts, but the current Passport order model stores one primary customer Contact ID per order.

HighLevel documents Contact associations with supported Custom Objects, paired labels, relationship types, and association limits. [3]

## Required Passport configuration

The system should resolve field keys by name, but two structural values still need to be configured for each location:

1. The actual HighLevel object schema key.
2. The actual Contact-to-Passport Booking association ID.

The association direction must also be stored, for example `contact_is_first = true`.

Recommended database configuration tables:

### `ghl_booking_object_configs`

One row per Passport operator/location:

- `operator_id`
- `schema_key`
- `association_id`
- `contact_is_first`
- `enabled`
- `last_verified_at`
- `last_error`

### `ghl_booking_object_field_mappings`

One row per mapped object field:

- `operator_id`
- `passport_key`
- `ghl_field_name`
- `ghl_field_key` nullable cache
- `data_type`
- `enabled`
- `last_verified_at`
- `last_error`

### `ghl_booking_object_mappings`

One row per local booking:

- `operator_id`
- `booking_id` unique
- `ghl_record_id`
- `status`
- `payload_hash`
- `last_attempt_at`
- `last_synced_at`
- `last_error`

The object mapping must search by the unique `Passport Booking ID` before creating a new remote record. This protects against a successful HighLevel create whose HTTP response was lost.

## Name-based field resolution

For every object synchronization, Passport should:

1. Read the configured object schema.
2. Read its field list.
3. Normalize field names by trimming whitespace and case-folding.
4. Find each configured Passport field by name.
5. Reject the sync if a required field is missing.
6. Reject the sync if the same normalized name maps to conflicting field keys.
7. Cache the resolved field key for diagnostics.
8. Send the values using the resolved field key.

The application should never require the operator to copy every custom-field ID manually. A field name is the configuration source; the resolved ID/key is only a provider-specific cache.

## HighLevel APIs required by the implementation

The API calls below are the provider operations the implementation should isolate behind the existing `GHLClient`.

### Create or update the Contact

Create when no exact Contact is found:

```http
POST /contacts/
Version: v3
```

Expected important response shape:

```json
{
  "contact": {
    "id": "CONTACT_ID",
    "locationId": "LOCATION_ID",
    "email": "customer@example.com"
  }
}
```

Update when a saved Contact ID or exact email/phone match exists:

```http
PUT /contacts/{contactId}
Version: v3
```

Passport must save the returned Contact ID locally.

### Create or update the calendar appointment

Create:

```http
POST /calendars/events/appointments
Version: v3
```

Update:

```http
PUT /calendars/events/appointments/{appointmentId}
Version: v3
```

Important fields:

```json
{
  "calendarId": "GHL_CALENDAR_ID",
  "locationId": "LOCATION_ID",
  "contactId": "CONTACT_ID",
  "startTime": "2026-10-16T15:00:00Z",
  "endTime": "2026-10-16T17:00:00Z",
  "appointmentStatus": "confirmed",
  "assignedUserId": "GHL_USER_ID",
  "toNotify": false
}
```

For this design, `toNotify` should be `false` if the custom-object workflow is the only customer-notification source. This prevents duplicate appointment-created notifications.

The appointment response should contain an appointment/event ID. Passport stores it in `ghl_appointment_mappings` and writes it into `Passport GHL Appointment ID` on the booking object.

### Create a Passport Booking record

```http
POST /objects/{schemaKey}/records
Version: v3
```

Expected request shape:

```json
{
  "locationId": "LOCATION_ID",
  "properties": {
    "OBJECT_FIELD_KEY_BOOKING_ID": "LOCAL_BOOKING_UUID",
    "OBJECT_FIELD_KEY_REFERENCE": "PASSPORT-ABC123",
    "OBJECT_FIELD_KEY_STATUS": "confirmed",
    "OBJECT_FIELD_KEY_PAYMENT_STATUS": "succeeded",
    "OBJECT_FIELD_KEY_SERVICE": "Kayak Tour",
    "OBJECT_FIELD_KEY_QUANTITY": 2,
    "OBJECT_FIELD_KEY_TOTAL": "125.00",
    "OBJECT_FIELD_KEY_CURRENCY": "USD",
    "OBJECT_FIELD_KEY_WAIVER_URL": "https://passport.example/waivers/...",
    "OBJECT_FIELD_KEY_WAIVER_STATUS": "pending",
    "OBJECT_FIELD_KEY_APPOINTMENT_ID": "GHL_APPOINTMENT_ID"
  }
}
```

The response must provide a remote record ID. Save it in `ghl_booking_object_mappings`.

### Search before creating

```http
POST /objects/{schemaKey}/records/search
Version: v3
```

Search by the resolved `Passport Booking ID` field key. If exactly one match is found, update it instead of creating a duplicate.

### Update a Passport Booking record

```http
PUT /objects/{schemaKey}/records/{recordId}?locationId=LOCATION_ID
Version: v3
```

Use this when payment changes from pending to succeeded, when a booking is cancelled, or when waiver status changes.

### Associate the object record with the Contact

```http
POST /associations/relations
Version: v3
```

Expected request shape:

```json
{
  "locationId": "LOCATION_ID",
  "associationId": "ASSOCIATION_ID",
  "firstRecordId": "CONTACT_ID",
  "secondRecordId": "PASSPORT_BOOKING_RECORD_ID"
}
```

If the association definition has the object first, reverse the record IDs. Repeating the same association should be treated as idempotent; a provider conflict indicating that the relation already exists should not fail the whole booking sync.

## Customer email workflow

HighLevel currently documents a direct **Send Email** action for Company and Custom Object workflows. It is a Labs feature. [4]

### Setup

1. Open **Settings → Labs**.
2. Enable **Email Action in Company & Custom Object Workflows**.
3. Go to **Automation → Workflows**.
4. Create a **Custom Object-based workflow** for `Passport Booking`.
5. Add the trigger:
   - `Passport Booking Created` for already-confirmed free bookings; and/or
   - `Passport Booking Changed` when the status becomes `confirmed` for paid bookings.
6. Add an If/Else guard:
   - `Passport Booking Status = confirmed`.
   - `Passport Payment Status = succeeded` or `none`.
7. Add **Send Email**.
8. Select the associated Contact using the `Booked By` association label.
9. Choose **Most recently associated contact** if the account exposes that option. Because Passport allows only one Contact per booking, this resolves to the primary customer.
10. Configure the sender, subject, and body.
11. Use Contact merge values for name and email.
12. Use Passport Booking fields for the booking reference, service, total, waiver status, and waiver URL where the editor exposes them.
13. Disable repeated enrollment for the same confirmation state.
14. Test with a free booking and a paid booking.
15. Publish only after the test confirms one email per booking.

The official HighLevel documentation says direct custom-object email can target associated contacts and can use custom-object and Contact personalization tokens. [4]

## Customer SMS workflow limitation and workaround

The current official Custom Object workflow action list documents Custom Object triggers, object updates, webhooks, and internal actions. It does **not** document a direct Send SMS action for Custom Object workflows. [1]

Therefore, do not assume that a Custom Object workflow can send an SMS directly to its associated Contact in every account.

### First choice: verify the account UI

In the demo location, create a test Custom Object workflow and inspect the Communication actions. If a supported **Send SMS** action is available with an associated-contact recipient selector, use:

- Trigger: Passport Booking Created/Changed.
- Guard: confirmed and paid/free.
- Recipient: associated Contact using `Booked By`.
- One-time enrollment for confirmation.

The action must be tested with a real test Contact before it is accepted as the production design.

### Supported fallback: enroll the Contact in a Contact workflow

HighLevel documents **Add Associated Records to Workflow** for Custom Object workflows. The action can select Contact as the target object, filter by association label, and enroll the associated Contact into another workflow. [5]

Configure:

1. Create a Contact-based workflow called `Passport Customer SMS - Booking Confirmation`.
2. Set its enrollment trigger to **Added to Workflow**.
3. Add the SMS action.
4. Use Contact data and standard appointment data in the SMS.
5. From the `Passport Booking` workflow, add **Add Associated Records to Workflow**.
6. Select object type **Contact**.
7. Select association label **Booked By**.
8. Select `Passport Customer SMS - Booking Confirmation`.
9. Publish both workflows.

This fallback is reliable for sending the SMS to the right Contact, but the availability of Passport Booking fields as merge values inside the Contact workflow must be tested in the target GHL account. HighLevel's merge-field documentation makes field availability dependent on workflow context. [6]

If the Contact workflow cannot access the booking object's fields, there are two choices:

- Keep the SMS generic and use standard Contact plus appointment values, while the detailed booking and waiver link are sent by the Custom Object email workflow; or
- Add a carefully controlled, short-lived notification projection to Contact fields. This is less desirable because one Contact can have multiple active bookings and a later booking could overwrite the notification fields.

The second option should not be implemented without a concurrency design. The Passport Booking custom object remains the source of truth.

## Staff follow-up and reminder ownership

Passport should continue to own:

- Staff assignment notification.
- Staff unassignment notification.
- Day-before staff reminder.
- Same-day staff reminder.
- Staff operational follow-up messages.

The clean repository already has the scheduling logic:

- `ReminderService.enqueue()` creates reminder jobs for confirmed bookings and staff assignments.
- `/api/v1/internal/cron/daily` expires holds, queues reminders, and drains the outbox.
- `worker.py` is the preferred always-on process for near-real-time outbox work.

The implementation change is the delivery provider, not the reminder decision logic.

### Required provider boundary

The current staff jobs call `GHLEmailService`, which sends through HighLevel. To make Passport the sender, introduce a Passport-owned interface such as:

```python
class PassportNotificationService:
    def send_staff_assigned(...): ...
    def send_staff_unassigned(...): ...
    def send_staff_reminder(...): ...
```

Then add provider adapters for the chosen transactional services:

- Email: Resend, Postmark, Amazon SES, SendGrid, or SMTP.
- SMS: Twilio, Telnyx, Vonage, or another approved provider.

The provider choice is still an implementation decision. Passport cannot send email or SMS directly without a provider account, sender identity, and credentials.

The staff notification jobs should remain durable and retryable through Passport's outbox/worker. The customer GHL workflow must not be used for staff reminders.

## Database and model changes required

The implementation should be split into small migrations and tested after each one.

### Migration A: GHL object configuration

Add:

- `ghl_booking_object_configs`
- `ghl_booking_object_field_mappings`
- `ghl_booking_object_mappings`

Add indexes and constraints for:

- One config per operator.
- One field mapping per operator and Passport key.
- One remote object mapping per local booking.
- Valid sync statuses.
- Payload hash and last-error diagnostics.

### Migration B: notification ownership cleanup

Remove or deprecate customer-message status columns and GHL customer message IDs after confirming no reporting/API client depends on them:

- `ghl_confirmation_email_status`
- `ghl_conversation_id`
- `ghl_message_id`
- `ghl_email_message_id`

Do not remove staff-reminder state until the Passport-owned provider is implemented and verified.

### Migration C: workflow projection state

Add only if needed after the GHL workflow test:

- Customer confirmation projection status.
- Last projected booking state.
- Last workflow-triggered state.
- A deduplication key such as `booking_id + notification_type + state`.

Do not rely only on a GHL workflow's re-entry setting. Passport should keep enough local state to explain whether the booking was projected and which booking state was sent.

## Implementation phases

### Phase 1 — Provider and workflow contract

- Confirm the target GHL location.
- Create the `Passport Booking` object and fields.
- Create the Contact association.
- Verify whether the location exposes direct SMS from Custom Object workflows.
- Enable the email Labs feature if approved.
- Configure test email/SMS workflows without publishing to the full audience.
- Select and configure the Passport-owned staff email/SMS providers.

### Phase 2 — Database and ORM

- Add the object configuration and mapping tables.
- Add the schema-version marker.
- Add ORM entities.
- Add contract tests for uniqueness, foreign keys, and status values.

### Phase 3 — Booking projection

- Implement object field name-to-key resolution.
- Implement idempotent object record search/create/update.
- Implement Contact association.
- Integrate object projection after Contact and appointment synchronization.
- Add the `created`, `payment_confirmed`, `cancelled`, and `rescheduled` trigger types to durable sync runs.

### Phase 4 — Customer workflow handoff

- Set the appointment `toNotify` behavior so appointment notifications do not duplicate the custom-object workflow.
- Create/update the object with `pending_payment` before payment and `confirmed` after payment.
- Verify that free bookings trigger exactly once.
- Verify that card and invoice bookings do not notify before payment.
- Verify that paid bookings trigger exactly once after payment.
- Verify public and staff booking links produce the same Contact/object/association result.

### Phase 5 — Staff Passport notifications

- Replace staff calls to `GHLEmailService` with Passport-owned provider adapters.
- Preserve outbox retry and idempotency keys.
- Add SMS delivery status and provider message IDs if staff SMS is required.
- Test assignment, unassignment, day-before, same-day, cancellation, and reschedule cases.

### Phase 6 — Remove obsolete customer messaging paths

Only after the GHL workflow path is verified:

- Stop queuing `ghl_send_confirmation_email`.
- Stop queuing customer booking reminder/cancellation/weather/reschedule messages if those are now handled by GHL workflows.
- Keep staff Passport-owned jobs.
- Remove unused GHL conversation-message scope only after no remaining code path sends customer or staff messages through GHL.
- Update documentation and deployment environment variables.

## Verification matrix

### Public booking

- Free booking creates/updates one Contact.
- Free booking creates one Passport Booking record.
- The record is associated with the Contact.
- The customer workflow sends one email and one SMS.
- No Passport customer message job is queued.

### Staff booking

- Free, card, and invoice staff bookings use the same projection.
- The staff link does not create a duplicate Contact when the email already exists.
- Paid staff bookings do not notify before payment confirmation.
- The customer workflow runs after successful payment.
- Staff assignment and reminders are sent through Passport's provider.

### Retry and idempotency

- A failed Contact request retries up to three times.
- A failed object request retries without creating duplicate records.
- A lost create response is reconciled by searching for the unique Passport Booking ID.
- A repeated association returns success or an already-associated result.
- A GHL workflow update does not cause duplicate confirmation messages.

### Failure visibility

- Passport records the failed GHL synchronization run.
- The operator can see the reason and manually resynchronize.
- A GHL workflow failure is distinguishable from a Passport provider failure.
- Staff message failures are retried by Passport and remain visible to operators.

## Open decision before implementation

The architecture is ready to implement, but the following provider decision is required for staff notifications:

- Which email provider should Passport use for staff email?
- Which SMS provider should Passport use for staff SMS?
- What verified sender email/domain and phone number should be used?

The customer GHL workflow path can proceed independently once the object, association, and target GHL workflow capabilities are verified.

## References

[1]: https://help.gohighlevel.com/support/solutions/articles/155000004389-using-custom-objects-in-workflow-actions-and-triggers "HighLevel: Using Custom Objects in Workflow Actions and Triggers"
[2]: https://help.gohighlevel.com/support/solutions/articles/155000003897-creating-and-editing-custom-objects "HighLevel: Creating and Editing Custom Objects"
[3]: https://help.gohighlevel.com/support/solutions/articles/155000003918-associating-contacts-using-custom-labels "HighLevel: Associating Contacts using Custom Labels"
[4]: https://help.gohighlevel.com/support/solutions/articles/155000008293-email-actions-for-company-custom-object-workflows "HighLevel: Email Actions for Company & Custom Object Workflows"
[5]: https://help.gohighlevel.com/support/solutions/articles/155000006486-workflow-action-add-associated-records-to-workflow "HighLevel: Add Associated Records to Workflow"
[6]: https://help.gohighlevel.com/support/solutions/articles/155000004390-overview-of-merge-fields-custom-variables "HighLevel: Overview of Merge Fields & Custom Variables"
