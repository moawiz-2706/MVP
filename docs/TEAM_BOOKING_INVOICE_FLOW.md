# Team Booking and Client Invoice Flow

## Goal

Allow an authenticated Passport account owner or team member to book a client into any available calendar slot without collecting the client's card details.

The existing public booking flow remains unchanged. Existing public paid bookings continue to use the customer-facing Stripe PaymentIntent flow. The new team flow adds an explicit payment choice:

- **Payment required:** create a pending booking, create and send a Stripe hosted invoice to the client's email, and confirm the booking only after `invoice.paid` is received and verified.
- **Payment not required:** create a confirmed booking immediately, with no invoice and no payment-provider call.

## API contract

### Team booking creation

`POST /api/v1/bookings`

Existing request fields remain supported:

```json
{
  "items": [
    {
      "calendar_id": "uuid",
      "start_at": "2026-10-05T14:00:00-04:00",
      "units": 2,
      "rate_id": "uuid-or-null"
    }
  ],
  "customer": {
    "first_name": "Alex",
    "last_name": "Morgan",
    "email": "alex@example.com",
    "phone": "+1 941 555 0100"
  },
  "custom_fields": {},
  "payment_required": true
}
```

`payment_required` is accepted only on the authenticated team endpoint. Public checkout requests omit it and retain their existing behavior.

Response additions are backward-compatible optional fields:

```json
{
  "public_reference": "PGA-12345",
  "status": "pending_payment",
  "client_secret": null,
  "invoice_url": "https://invoice.stripe.com/i/acct_...",
  "invoice_status": "sent",
  "payment_method": "invoice",
  "quote": {}
}
```

For a free team booking:

```json
{
  "status": "confirmed",
  "client_secret": null,
  "invoice_url": null,
  "invoice_status": null,
  "payment_method": "none"
}
```

For existing public paid checkout, `payment_method` remains `card` and `client_secret` remains populated. Existing clients may ignore the new response fields.

## State and provider behavior

### Invoice booking

1. Validate calendars, availability, resource capacity, rate, customer, permissions, and Stripe account readiness.
2. Create local order/payment/booking rows in `pending_payment` with a booking hold.
3. Enqueue an idempotent `stripe_create_invoice` outbox job.
4. The worker creates or reuses a Stripe Customer, Invoice Item, and `send_invoice` Invoice using stable idempotency keys.
5. Finalize and send the hosted invoice to the client's email.
6. Store invoice ID, hosted invoice URL, customer ID, and invoice status locally.
7. Return the hosted invoice URL when inline outbox delivery succeeds; otherwise return a pending invoice status while the durable worker retries.
8. On a verified `invoice.paid` webhook, verify metadata, amount, currency, payment intent, and charge, then reuse the existing payment-success transition to confirm the booking and enqueue confirmation/GHL sync jobs.

### Free booking

1. Validate availability and all booking rules.
2. Create the order/payment/booking as confirmed/succeeded.
3. Do not create a Stripe invoice, PaymentIntent, or payment-intent request.
4. Continue existing GHL appointment/contact/confirmation behavior.

### Failure handling

- Invoice creation failures remain in the outbox with retry/backoff; the local booking is not silently confirmed.
- Invoice payment failures leave the booking pending until the hold expires or an operator takes action.
- Voided invoices release the pending booking hold and mark the booking failed/expired.
- Duplicate webhook deliveries are ignored through the existing Stripe webhook event idempotency table.
- Paid invoice events are quarantined if amount, currency, operator, order, or charge verification fails.

## Database changes

Migration `031_team_invoice_bookings.sql` adds:

- `payments.stripe_customer_id`
- `payments.stripe_invoice_id`
- `payments.stripe_invoice_url`
- `payments.invoice_status`
- `OutboxJob.job_type = stripe_create_invoice`
- relevant indexes and constraints

The migration is additive and does not modify existing booking status meanings.

## UI behavior

The existing authenticated Bookings calendar remains the primary booking page and continues to show all calendars, dates, times, bookings, and availability.

The **New booking** workflow adds:

- calendar selection
- live date/time availability validation
- client details
- quantity/rate selection
- **Payment required** toggle, defaulting to enabled when the selected booking has a positive total
- a clear explanation that Passport sends a hosted invoice and never asks the team member for card details

The same payment choice is available from the Calendars page's **Book** action.

After creation:

- paid invoice booking: show pending status, invoice recipient email, and a copy/open invoice link
- free booking: show immediate confirmation and no invoice language

## Compatibility and verification

- Public booking pages continue to use PaymentIntent + client-side Stripe Elements.
- Existing `OrderCreateRequest` consumers remain valid because the new flag is optional.
- Existing outbox jobs and migrations remain unchanged except for the additive invoice job type/fields.
- Backend tests cover free override, invoice mode, idempotent invoice job creation, invoice-paid confirmation, failed/voided invoices, and public-flow regression.
- Frontend validation includes typecheck, existing notification tests, and production build.
