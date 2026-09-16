# Architecture

## System boundaries

The application is one coherent React + FastAPI + PostgreSQL system. Durable
state is never kept in a Vercel process. Supabase PostgreSQL owns scheduling and
financial records; Stripe owns payment objects; GHL owns OAuth authorization,
the signed Custom Page identity context, Contacts, and sent messages.

The browser never selects a tenant. An embedded session is established only by
decrypting GHL's user context, reading `activeLocation`, and mapping it to one
active `ghl_installations` row. The resulting short-lived bearer token carries
the resolved operator ID and stays in React memory.

## Entity and relationship summary

```text
Operator (one installed GHL Location)
├── GHLInstallation (1:1, encrypted rotating token pair)
├── OperatorSettings (1:1)
├── OperatorUser (*:*, through AppUser)
├── DepartureLocation (1:*) ──< Calendar (optional location)
├── CalendarCategory (1:*) ──< Calendar (optional category)
├── Resource (1:*) >──< Calendar (through CalendarResource)
├── Staff (1:*)
│   ├── StaffHour (1:*)
│   └── StaffAssignment (1:*) >── Calendar
├── BookingOrder (1:*)
│   ├── Booking (1:*) >── Calendar
│   │   └── BookingResource (*:*) >── Resource
│   ├── Payment (1:1)
│   │   └── StripeTransfer (1:*)
│   └── OutboxJob (1:*)
└── StripeConnection (1:1)

Calendar
├── CalendarHour (1:*)        (day_wise mode)
├── CalendarDateHour (1:*)    (date_wise mode)
├── CalendarPushedSlot (1:*)  (pushed mode)
└── CalendarBlock (1:*)

StripeWebhookEvent is globally unique by Stripe event ID.
```

All protected queries begin with the operator ID from the verified application
session. Child IDs are never sufficient by themselves: ownership is checked by
joining or filtering back to that operator.

## Important invariants

- A resource pool is shared by every mapped calendar in its operator.
- Intervals overlap only when `existing.start < requested.end` and
  `existing.end > requested.start`; touching boundaries do not overlap.
- Confirmed bookings and unexpired `pending_payment` holds consume inventory.
- Reservation transactions lock all relevant resource rows in UUID order and
  validate existing usage plus every new occurrence as one batch.
- Weekly hours use operator-local wall time; persisted bookings and blocks use
  `TIMESTAMPTZ`.
- Money is integer minor units. Percentage calculations use `Decimal` and
  `ROUND_HALF_UP`.
- Business configuration uses soft deletion. Booking/payment snapshots preserve
  history independently of later configuration changes.
- Stripe webhooks, not Stripe.js, authorize paid-booking confirmation.
- Transfers are separate from platform charges and use the successful `ch_...`
  Charge as `source_transaction`.
- External operations use unique outbox idempotency keys and bounded retries.

## Resolved ambiguities and contradictions

1. **OAuth callback method.** OAuth redirects are GET requests. The canonical
   route is `GET /api/v1/integrations/marketplace/oauth/callback`. The path avoids
   the substring "ghl" because the GHL Marketplace rejects redirect URLs
   containing a HighLevel reference. The embedded Custom Page is served at `/app`
   for the same reason.
2. **Exact GHL context cryptography.** This is deliberately isolated behind a
   context decoder. Its implementation must match the current Marketplace
   documentation and test vectors; it is not treated as a normal JWT or replaced
   with an invented format.
3. **Public references.** The six-character example is human-friendly but not
   strong enough to serve as the sole credential for public order details. The
   implementation uses a longer non-sequential reference with at least 72 bits
   of randomness.
4. **Free bookings.** A zero-total order is confirmed transactionally without a
   PaymentIntent. It still creates immutable financial snapshots and reliable
   GHL outbox jobs.
5. **Expired hold followed by payment success.** The application does not silently
   overbook. It re-locks resources and confirms only if capacity is still valid;
   otherwise the order becomes `exception` for operator resolution/refund.
6. **`base_price_minor` on bookings.** This is the snapshotted per-unit price.
   Line subtotal is `base_price_minor * units`.
7. **Staff permissions.** Administrators/agency owners manage configuration,
   payments, and destructive actions. Ordinary GHL users may view and operate
   bookings but may not mutate tenant configuration or payment settings.
8. **GHL endpoint versioning and Stripe account creation.** External request
   shapes and version headers are centralized in adapter services so current API
   behavior can change without leaking into domain services.
9. **Tax wording.** The required customer label remains “Platform Fee & Taxes”.
   The code does not calculate jurisdictional tax or claim Stripe Tax compliance.

## Availability algorithm

Availability is computed per requested interval, per resource, across the whole
operator — never per calendar.

1. Resolve the calendar (active, not soft-deleted, and for public flows also
   `public_booking_enabled` with an active publicly-bookable operator).
2. Derive `end_at = start_at + duration_minutes`, then apply the calendar's one
   active `availability_mode` (the other modes' rows are kept but ignored):
   - `day_wise`: the slot must fall entirely within one `calendar_hours`
     interval on that operator-local weekday, so the latest valid start is
     `close - duration` (a 3-hour booking against 08:00–17:00 may start no
     later than 14:00). Public starts step by `slot_interval_minutes`.
   - `date_wise`: the same, against `calendar_date_hours` ranges covering the
     date.
   - `pushed`: `start_at` must exactly equal a `calendar_pushed_slots` row.
     Opening hours and `slot_interval_minutes` do not apply; the operator
     offers each start explicitly. Push times are entered as operator-local
     wall time and rejected if they fall in a DST gap or in the past.
3. Reject the slot if any `calendar_blocks` row overlaps it.
4. For every mapped resource, sum the **peak concurrent** reserved quantity over
   the requested window from all resource-consuming bookings in the operator
   (any calendar), then `available = quantity − reserved`. Reserved is the
   sweep-line peak, not the sum of every booking that grazes a long window.
5. `resource_available_units = floor(available / default_quantity_per_unit)`;
   the slot maximum is the minimum across all required resources, then capped by
   `max_units_per_booking`. A calendar with no resource mappings defaults to a
   maximum of one unit unless `max_units_per_booking` says otherwise.

A booking is bookable only when every required resource has enough inventory for
the requested units.

## Concurrency and overbooking protection

Availability reads are advisory. Correctness comes from the reservation
transaction (`OrderService.create`):

1. Prepare and validate the cart, then `SELECT resources ... ORDER BY id FOR
   UPDATE` — locking every relevant resource row in deterministic UUID order to
   avoid deadlocks.
2. Re-prepare and re-validate **after** the locks are held, so a competing
   transaction cannot have committed inventory in between.
3. Validate the whole cart as one batch: a sweep-line over existing reservations
   plus every new occurrence in the same order. Two occurrences that overlap
   each other are counted together, so an order that only overbooks against
   itself is rejected as a unit (§44).
4. On success, create the order, `pending_payment` bookings, and
   `booking_resources`, then commit. On failure, roll back and return 409.

Resource-consuming bookings are exactly `confirmed` plus `pending_payment` whose
`hold_expires_at > now()`. Expired holds stop consuming inventory the moment
they lapse — the availability query filters them out directly, so correctness
never depends on a cleanup job running.

## Staff scheduling

Staff are assigned to a **calendar time slot** (calendar + start instant), not
to an individual booking, with an optional free-text role ("Captain", "First
Mate"). The assignment spans `[start_at, start_at + duration)`.

- A staff member has weekly working hours (`staff_hours`, operator-local wall
  time, several intervals per weekday allowed). An assignment must fit inside
  one interval, like a booking must fit calendar hours.
- A staff member is busy for the whole slot **across every calendar**; any
  overlapping assignment is rejected (touching boundaries do not overlap).
- `StaffService.assign` takes the staff row `FOR UPDATE` before the overlap
  check, so two concurrent assignments of the same person serialize and the
  second sees the first.
- Staff do not gate customer availability; they are operational scheduling
  only. Changing someone's hours affects new assignments, not existing ones.
- Deleting staff is a soft delete that releases their upcoming assignments and
  keeps past ones.

Managing the roster is configuration (admins). Assigning staff to slots is
booking operation, open to every operator user.

The dashboard reads `GET /booking-slots`, which groups bookings, staff
assignments and (for pushed calendars) offered starts by start instant, then by
calendar.

## Reminders and scheduled jobs

A Vercel Cron (`vercel.json` → `GET /api/v1/internal/cron/daily`, daily at
11:00 UTC, authorized by `Authorization: Bearer $CRON_SECRET`) does two things:

1. `ReminderService.enqueue` queues an outbox job for every confirmed booking and
   every staff assignment starting later **today** (`same_day`) or **tomorrow**
   (`day_before`), where days are the operator's local days. Keys are
   `booking:{id}:reminder:{kind}` / `assignment:{id}:reminder:{kind}`, unique, so
   a duplicated or repeated cron run cannot queue a reminder twice.
2. The outbox is drained (with a time budget), sending those reminders and
   retrying anything that failed earlier.

At send time each reminder is re-checked: the booking must still be confirmed
(assignment still present, staff still active with an email), and the start must
still fall in that kind's window — so a failed day-before reminder retried the
next morning is dropped rather than telling someone "tomorrow" on the day.
Customer reminders follow the operator's confirmation-email switch.

Staff emails: assigning staff queues `ghl_staff_assigned_email`, which is sent
immediately (inline, like the payment confirmation) with the cron as the retry
path. Staff need an email address to be emailed; those without one are skipped.
Removing staff from an upcoming slot queues `ghl_staff_unassigned_email`, built
from a snapshot of the slot because the assignment row is deleted.

HighLevel Contacts: customers are tagged `passport-customer` and staff
`passport-staff` (tags that must exist in the location). Tags are applied with
`POST /contacts/{id}/tags`, which appends — sending `tags` on a contact update
would replace every tag the operator's team had set. Staff Contacts are created
or updated whenever a staff member with an email is saved, and the ID is stored
in `staff.ghl_contact_id`.

On the Hobby plan Vercel runs crons at most once a day, anywhere within the
scheduled hour, and never retries a failed invocation; the idempotent keys and
the re-check make both duplicates and misses safe.

## Waivers and booking notes

Every confirmed booking has one waiver (`booking_waivers`), created on first
use with a secret link token. The customer gets the link in the confirmation
email, on the post-checkout confirmation page, and in reminders while it is
unsigned. The form lists one person per booked unit: the signer (18 or older,
with contact details and home address) plus everyone else (name and date of
birth; anyone under 18 on the activity date is flagged as a minor). One drawn
signature covers everyone.

Signing (`POST /public/waivers/{token}/sign`) locks the row `FOR UPDATE`,
checks the head count against `bookings.units`, and snapshots the waiver title,
text, activity and every detail, along with the signer's IP and browser. The
`prevent_signed_waiver_change` trigger then rejects any UPDATE or DELETE of a
signed waiver. Waiver text is set per operator in Settings; an operator with no
waiver text has waivers switched off.

Booking notes (`booking_notes`) are internal, per booking, with the author's
name and time. Any operator user can add one; only its author or an admin can
delete it.

## GHL trust chain

1. **Install (OAuth):** the callback exchanges the code for a rotating
   access/refresh pair, encrypts both, and provisions the operator. Tokens never
   reach React.
2. **Per-view identity:** the embedded page asks the GHL parent window for the
   encrypted user context and POSTs it to `/auth/ghl-session`. The backend
   decrypts it with `GHL_APP_SHARED_SECRET`, reads `activeLocation`, and maps it
   to exactly one installed `ghl_installations` row → operator. The browser
   never supplies the operator; an unmapped `activeLocation` is 403.
3. **Local session:** the backend issues a short-lived signed app JWT
   (`app_user_id`, `operator_id`, `ghl_location_id`, `role`, `exp`) kept only in
   React memory. Every protected query is scoped by the token's `operator_id`.
4. **Token refresh:** before any GHL call the installation row is taken
   `FOR UPDATE`, expiry is re-checked, and a refreshed rotating pair is
   persisted before release — so concurrent requests can never spend the same
   rotating refresh token twice.

## Payment math

All money is integer minor units; percentages use `Decimal` with
`ROUND_HALF_UP`. From `subtotal = Σ(base_price_minor × units)`:

- `platform_fee_and_taxes = round_half_up(subtotal × 13%)` → shown to the
  customer as “Platform Fee & Taxes”.
- `customer_total = subtotal + platform_fee_and_taxes`.
- `operator_transfer = subtotal + round_half_up(subtotal × 7%)`.
- `platform_gross_retained = customer_total − operator_transfer` (≈ 6% of
  subtotal, before Stripe fees, which the platform bears).

These five values are snapshotted onto the order and payment and never
recomputed from later configuration.

## Stripe source_transaction flow

Payments use **Separate Charges and Transfers**. The customer Charge lives on the
platform account; the operator is paid by a distinct Transfer. On verified
`payment_intent.succeeded` the handler reads `payment_intent.latest_charge`,
stores the `ch_...` id, and the transfer job creates the Transfer with
`source_transaction = <charge id>` (guarded to reject a `pi_...`). Binding the
Transfer to the Charge lets Stripe release operator funds as the charge settles
rather than requiring an immediately-available platform balance. A stable
`transfer_group = booking_order_{public_reference}` aids reconciliation, and a
`booking_order:{order_id}:operator_transfer` idempotency key plus a unique
`stripe_transfers.payment_id` prevent double payouts on any retry.

## Deletion and cascade behavior

Business configuration uses soft deletion; history is never destroyed.

- **Departure location:** soft-deleted; affected calendars have
  `departure_location_id` set to NULL; calendars and booking snapshots are kept.
- **Category:** transactional soft delete that also soft-deletes and deactivates
  every calendar under it; bookings and payments are preserved.
- **Calendar / resource:** soft-deleted (`deleted_at`, `is_active=false`);
  historical `bookings` and `booking_resources` remain as the record of what was
  consumed.
- Purely dependent, mutable config (`calendar_hours`, `calendar_blocks`,
  `calendar_resources`) may hard-cascade, but the delete **APIs** preserve
  business history. Every explicit delete requires typing `DELETE`.

## Refunds and cancellations — product scope

**Passport does not offer customer refunds or cancellations.** Bookings are
final from the customer's side; there is deliberately no self-service refund or
cancellation path, and no admin-initiated refund endpoint.

- **Cancellations** are an **admin-only** operational tool
  (`POST /bookings/{id}/cancel`): an operator may cancel a booking (weather,
  no-show, mistake), which marks it `cancelled` and returns its inventory to
  availability. No money moves. Customers cannot cancel.
- **Refunds** are handled **reactively only**. There is no refund feature in the
  app. The `charge.refunded` webhook exists purely as a safety net: if a refund
  is ever forced outside Passport — a Stripe dashboard action, or a
  chargeback/dispute — it reconciles `payments.refunded_minor` and status so the
  local records stay accurate. It does not, and is not meant to, initiate
  refunds or reverse Transfers.

If a paid refund feature is added later, note the Separate Charges and Transfers
consequence: a refund of the customer Charge and a reversal of the
connected-account Transfer are two independent operations, and a Charge-only
refund would leave the operator's Transfer intact — so any future refund flow
must reverse the Transfer (bounded by the amount transferred) in the same action
and record the audit trail (§69/§90).

## Testing strategy

Two layers:

- **Pure-logic unit tests** (`pytest`, no external services) cover the
  algorithms directly: capacity/overlap/batch (availability and cart-concurrency
  math, §153–§154), payment math (§156), timezone/DST and hours-fit (§42/§40),
  public-reference entropy (§126), permissions (§158 #47–48), and the GHL context
  crypto, app-session lifetime, and token encryption (§158 #43–44,49). These run
  everywhere.
- **PostgreSQL-gated integration tests** cover what only a real database can
  prove: the availability engine end-to-end (§153 #7–17) and true
  `SELECT … FOR UPDATE` serialization of the last unit (§154 #18). They are
  skipped unless `TEST_DATABASE_URL` points at a disposable Postgres, because
  SQLite honours neither `postgresql` column types nor row-lock semantics —
  emulating them there would be a false positive.

Run everything with `pytest`; add the integration layer with
`TEST_DATABASE_URL=postgresql+psycopg://… pytest`. Scenarios that still need a
live external account (Stripe transfer/webhook/refund §157, GHL contact/email
§159) are documented for manual/staging verification and are not asserted
against mocked doubles.

## Intended directory tree

```text
backend/
  api/index.py
  app/
    api/v1/                 # thin routers
    core/                   # config, DB, security, permissions
    models/                 # SQLAlchemy mappings
    schemas/                # Pydantic request/response contracts
    services/               # domain and external-integration logic
    utils/                  # money, time, identifiers
    main.py
  tests/                    # pure unit tests + Postgres-gated integration
  requirements.txt
  pyproject.toml
  vercel.json
frontend/
  src/
    api/ auth/ components/ layouts/
    bookings/ calendars/ locations/ resources/ settings/ public-booking/
  package.json
  vite.config.ts
  vercel.json
supabase/
  migrations/               # authoritative schema history (no seed data by design)
docs/
  architecture.md           # this document
```

Development seed data is intentionally out of scope: environments are
provisioned by applying the migrations and installing the Marketplace app
against a real GHL sub-account.

