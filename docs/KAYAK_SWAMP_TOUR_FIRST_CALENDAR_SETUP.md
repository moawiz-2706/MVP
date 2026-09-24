# Kayak Swamp Tour: First Calendar Setup

Kayak Swamp Tour is the first configured activity, not a hardcoded activity in the application. The same Passport calendar, rate, resource, staff-role, availability, booking, and GHL synchronization model can be reused for every later activity.

## 1. Complete the connection prerequisites

Deploy the latest Passport backend and frontend from the production branch. Apply the repository migrations in numeric order, including `023_resource_metadata.sql`, to the production Supabase database. Configure the GHL OAuth installation for the target location and confirm that the application has the approved calendar, contact, appointment, staff-directory, and staff-availability scopes. Configure Stripe Connect before opening public payment-enabled booking.

Set the production environment values for the database URL, public frontend origin, GHL client credentials, webhook verification key, Stripe keys, cron secret, and the operator's IANA timezone. The worker or protected cron endpoint must run frequently enough to process the outbox and expire pending-payment holds.

## 2. Synchronize the GHL staff directory

Open **Staff roles** and run **Sync GHL staff**. Passport will copy the GHL staff identity and availability cache. Passport does not edit the staff member's name, email, employment status, or schedule. Assign only a Passport custom role to each person who can satisfy a booking requirement. For Kayak Swamp Tour, the usual starting role is `Captain`, with `First Mate` or `Guide` added only if the operation actually requires them.

Resolve every warning about missing roles or overlapping assignments before opening the public link. A role without a current GHL availability window cannot satisfy a required role during slot generation.

## 3. Create reusable resources

Open **Resources** and create the inventory pools that are shared by calendars. A typical initial set is:

| Resource | Type | Quantity | Purpose |
|---|---|---:|---|
| Single Kayak | Equipment | Actual usable kayak count | One unit per customer or rate rule |
| Tandem Kayak | Equipment | Actual usable tandem count | Two-person kayak inventory |
| Captain | Guide pool | Number of simultaneous captains | Optional if the calendar uses a resource pool for crew |
| Safety Equipment | Equipment | Actual usable count | Shared operational capacity |

Keep resources generic. Do not create a resource named only for a single date or customer. Use the notes field for inspection or safety instructions, and deactivate a resource temporarily when it should not be bookable without deleting historical relationships.

## 4. Create the category and calendar

Open **Calendars** and create a category such as `Kayak Eco Tours`. Then create a calendar with:

| Field | Recommended starting value |
|---|---|
| Name | `Kayak Swamp Tour` |
| Slug | `kayak-swamp-tour` |
| Description | Customer-facing tour description and meeting instructions |
| Duration | Actual tour duration, including operational buffer if required |
| Slot interval | The time between departures |
| Public booking | Enabled after testing |
| Minimum party size | `1` unless the tour requires a group minimum |
| Maximum party size | Safe maximum for one booking |
| Currency | The business currency |
| Booking mode | `online` unless the activity is call-to-book |
| Required staff roles | `Captain`, plus `First Mate`/`Guide` only when operationally required |
| Booking cutoff | The number of minutes before departure when online checkout closes |

Saving or updating the calendar queues the GHL calendar synchronization. Confirm the synchronization status before continuing. If GHL has a matching calendar, Passport recovers and updates it instead of creating a duplicate.

## 5. Attach resources and customer rates

Map the reusable kayak and safety resources to the calendar. Then configure customer types and rates. A common starting model is:

| Customer type | Seat count | Example rate | Resource rule |
|---|---:|---:|---|
| Adult | 1 | Current adult price | One single-kayak unit per guest, or the configured tandem rule |
| Child | 1 | Current child price | Same inventory rule unless children use a different capacity |
| Tandem kayak | 2 | Current tandem price | One tandem resource unit per booking unit |

Enter the actual business prices from the approved Kayak pricing sheet. Configure whether fees and taxes are inclusive or added at checkout. Each rate can consume a different number of resource units, and the public slot response will calculate the remaining capacity for that rate.

After saving rates or resource mappings, confirm that Passport queues a GHL calendar synchronization. The authoritative price, capacity, and booking decision remains in Passport; GHL receives the operational calendar and appointment projection.

## 6. Configure hours, departure slots, blocks, and policy

Create the weekly operating hours for the tour and add date-specific hours for seasonal exceptions. Add pushed departure slots when the tour has fixed departure times. Use calendar blocks for holidays, maintenance, private events, or weather closures.

Configure the booking policy before enabling public bookings:

- Cancellation cutoff and cancellation fee.
- Rescheduling cutoff and rescheduling fee.
- Weather outcome: full refund, credit, manual review, or no refund.
- Deposit percentage, if used.
- Waiver requirement.
- No-show outcome.

The public calendar displays closed, cutoff, blocked, sold-out, and crew-unavailable states separately. Customers cannot book a slot that fails inventory, operating-hour, blackout, cutoff, or required-staff checks.

## 7. Test an operator booking

Use the calendar booking drawer to select a date. Confirm that every expected departure appears, unavailable times explain the reason, and the rate selector changes the available quantity and price. Create a test booking with a real test customer email and the correct customer type. Confirm the payment hold, Stripe PaymentIntent, booking status, resource reservation, participant manifest, waiver link, and GHL appointment/contact synchronization.

Then cancel the test booking through the operator page. Confirm that the inventory is released, the booking event is recorded, the GHL appointment cancellation is queued or completed, and any configured refund path is visible in the payment record.

## 8. Publish and test the booking link

From the calendar's booking-link panel, copy the public URL. Open it in a private browser window and verify the customer sees the correct category, calendar name, timezone, departure location, rates, custom fields, policy text, waiver requirement, and payment total.

Complete one controlled test booking. On the confirmation page, verify the status link, waiver link, cancellation control, and rescheduling control. The rescheduling control loads only currently bookable slots and preserves the operator timezone. A reschedule with a configured fee is intentionally routed to operator assistance until a new payment or adjustment is completed.

## 9. Verify GHL projections

In GHL, verify that the calendar exists once, the contact is associated with the booking, and the appointment has the correct start time, end time, customer, booking reference, rate, resource, fee, tax, waiver, and payment metadata. Do not treat GHL as the source of inventory or payment truth.

If a sync fails, use the booking's retry action or run the protected GHL projection reconciliation. Failed jobs under the retry threshold return to the idempotent outbox; jobs repeatedly failing remain visible for manual review rather than being duplicated.

## 10. Add future calendars

To add another activity, repeat the same workflow with a new category/calendar, new or shared resources, rates, hours, staff-role requirements, policy, and booking link. No code change is required. The application must not contain Kayak-specific conditionals for the calendar name or slug.

## Production go-live checklist

Before switching the calendar from test to live, confirm that the database migrations are applied, the worker/cron is running, GHL and Stripe installations are active, staff roles and schedules are current, resources reflect real usable inventory, calendar rates have been reviewed, waivers and policies are published, the public link has been tested, cancellation/reschedule behavior is understood, and reports show no failed sync jobs.
