# Passport outbound-message delivery audit

## Executive result

Passport uses a durable outbox for customer and staff messages. The message body and subject are rendered at delivery time from the account's `message_templates` row, falling back to the built-in default when no custom template exists or a saved template is malformed.

The ten customizable message types are connected to the delivery service and HighLevel's `POST /conversations/messages` endpoint. Failed provider calls remain retryable through the outbox lease/backoff flow. Booking state is committed before external delivery, so a temporary HighLevel outage does not cancel a valid booking.

**Production requirement:** set `GHL_NOTIFICATIONS_ENABLED=true` in the backend environment. The application-level default is `false` so an unconfigured deployment cannot unexpectedly send messages. The account owner must also leave **confirmation/customer communications enabled** in the account settings for customer messages.

## Message matrix

| Message | Recipient | Trigger | Template event | Delivery path | Suppression rules |
|---|---|---|---|---|---|
| Booking confirmation | Customer | Free booking is confirmed immediately; paid card booking after verified `payment_intent.succeeded`; invoice booking after verified `invoice.paid` | `booking_confirmation` | `ghl_upsert_contact` then `ghl_send_confirmation_email` → HighLevel Email conversation | Global `GHL_NOTIFICATIONS_ENABLED`; account confirmation-email switch; template enabled |
| Hosted invoice | Customer | Staff/team booking uses **Send invoice** | Not a Message Template event; Stripe owns this email | `stripe_create_invoice` → Stripe Customer → Invoice Item → hosted `send_invoice` Invoice | Requires Stripe configuration and connected-account readiness; Stripe must return an open invoice and hosted URL |
| Booking cancellation | Customer | Operator/public cancellation completes | `booking_cancellation` | `ghl_booking_cancellation_email` → HighLevel Email conversation | Global notification switch; account confirmation-email switch; template enabled |
| Weather cancellation | Customer | Operator weather closure cancels a booking | `weather_cancellation` | `ghl_booking_weather_email` → HighLevel Email conversation | Same as cancellation; includes refund/credit/manual-review outcome |
| Booking reschedule | Customer | Operator/public reschedule completes | `booking_reschedule` | `ghl_booking_reschedule_email` → HighLevel Email conversation | Same as cancellation; includes previous time and payment outcome |
| Customer day-before reminder | Customer | Daily cron finds a confirmed booking starting tomorrow in the operator timezone | `booking_reminder_day_before` | `ghl_booking_reminder` → HighLevel Email conversation | Global switch; account confirmation-email switch; booking must still be confirmed and due at send time |
| Customer same-day reminder | Customer | Daily cron finds a confirmed booking later today in the operator timezone | `booking_reminder_same_day` | `ghl_booking_reminder` → HighLevel Email conversation | Same reminder checks; bookings already underway are skipped |
| Staff assignment | Staff member | Staff member is assigned to a future slot | `staff_assignment` | `ghl_staff_assigned_email` → staff contact → HighLevel Email conversation | Global switch; staff must be active and have an email; future assignments only |
| Staff removal | Staff member | Staff member is removed from a future slot | `staff_unassignment` | `ghl_staff_unassigned_email` → snapshot-based HighLevel Email conversation | Global switch; staff must still exist and have an email; past slots are skipped |
| Staff day-before reminder | Staff member | Daily cron finds an active staff assignment starting tomorrow | `staff_reminder_day_before` | `ghl_staff_reminder` → HighLevel Email conversation | Global switch; staff active with email; assignment must still be due |
| Staff same-day reminder | Staff member | Daily cron finds an active staff assignment later today | `staff_reminder_same_day` | `ghl_staff_reminder` → HighLevel Email conversation | Same reminder checks |

There are **ten customizable templates**. The hosted Stripe invoice email is an additional provider email and is intentionally not rendered by the HighLevel message-template editor.

## Template customization

Templates are tenant-scoped by `operator_id` and are edited in **Settings → Messages**. The supported events are:

- `booking_confirmation`
- `booking_cancellation`
- `weather_cancellation`
- `booking_reschedule`
- `booking_reminder_day_before`
- `booking_reminder_same_day`
- `staff_assignment`
- `staff_unassignment`
- `staff_reminder_day_before`
- `staff_reminder_same_day`

Templates support validated merge fields such as customer name, booking reference, calendar, date/time, location, payment outcome, adjustment outcome, waiver URL, staff name, and guest count. Subjects reject line breaks, unknown fields are rejected, and HTML is generated from escaped text. A malformed persisted template falls back to the safe default instead of breaking a booking notification.

## Delivery and retry behavior

1. Passport writes the booking/lifecycle mutation and its outbox jobs transactionally.
2. The inline request may process a bounded batch immediately after commit.
3. The persistent worker processes remaining jobs continuously when deployed.
4. The protected daily cron queues reminders and drains the outbox as a fallback.
5. Provider failures mark the job `failed`, record the error, and schedule exponential backoff retries.
6. Jobs use unique idempotency keys and leases, preventing duplicate sends during normal retries.
7. After the configured maximum attempts, a job becomes `dead` and requires operational review.

HighLevel contact synchronization occurs before customer confirmation delivery. Staff contacts are synchronized when staff records are saved or before staff email delivery. A missing/invalid contact, expired HighLevel token, missing scope, or provider error is retained as an outbox failure rather than being treated as a successful send.

## Paid invoice flow

For an invoice booking, Passport does not collect client card details. It creates the local pending booking first, then the outbox creates and sends the Stripe hosted invoice to the customer's submitted email. The booking remains pending until a verified `invoice.paid` event confirms the payment. Only then is the customer confirmation message queued.

If Stripe cannot return an open invoice with a hosted URL, the invoice outbox job remains retryable and the staff page shows that invoice delivery is pending. `invoice.payment_failed`, `invoice.voided`, and `invoice.marked_uncollectible` update the local payment/booking lifecycle safely.

## Deployment checklist

- Set `GHL_NOTIFICATIONS_ENABLED=true` in the backend production environment.
- Apply migrations through `034_fix_staff_booking_target_constraint`.
- Reauthorize each HighLevel sub-account with the required contacts and conversations permissions.
- Confirm the HighLevel location has permission to create/update contacts and send conversation emails.
- Ensure the operator's account-level customer email switch is enabled when customer messages are wanted.
- Run `backend/worker.py` continuously, or provide an equivalent frequent protected outbox runner. The daily Vercel cron is a fallback and is not a substitute for a continuously running worker for prompt delivery.
- Configure Stripe and register `invoice.paid`, `invoice.payment_failed`, `invoice.voided`, and `invoice.marked_uncollectible` webhook events.
- Test one free booking, one card-paid booking, one invoice booking, one cancellation, one reschedule, one weather cancellation, one staff assignment/removal, and both reminder windows in a staging HighLevel/Stripe account.
- Review dead outbox jobs and provider errors before opening production traffic.

## Important limitation

The application can verify that HighLevel or Stripe accepted a message for delivery. It cannot guarantee inbox placement after the provider accepts it. Bounces, spam filtering, sender-domain configuration, HighLevel email permissions, Stripe test mode, and invalid customer addresses must still be monitored at the provider level.
