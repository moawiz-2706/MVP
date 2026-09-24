# FareHarbor-style Passport Booking Parity Specification

## Scope

Passport is the system of record for customer-facing availability, customer types, rate plans, inventory resources, booking policies, customer fields, waivers, payments, booking lifecycle, and operator booking operations. GoHighLevel remains a synchronization target for calendars, contacts, appointments, and staff identity/role projections. The Migration and Booking Setup workspaces are not exposed in the operator UI; calendar configuration, rates, resources, policy, and booking links are managed through the existing Calendars, Resources, and public booking-link surfaces.

## Customer booking flow

The public booking link follows the observed Kayak Swamp Tour pattern: the customer selects a date and timezone, chooses a live slot, selects a customer/equipment type, chooses quantity within resource capacity, reviews subtotal plus taxes and fees, enters contact details, completes configured custom fields, optionally opts into marketing, reviews the cancellation/weather/reschedule policy, accepts the policy, and clicks Book and pay. Passport creates a pending-payment hold, confirms the Stripe PaymentIntent, exposes a confirmation link, and presents waiver signing when configured.

The booking contract is `GET /public/{operator_slug}`, `GET /public/{operator_slug}/calendars/{calendar_slug}/availability`, `GET /public/{operator_slug}/calendars/{calendar_slug}/rates`, `GET /public/{operator_slug}/calendars/{calendar_slug}/custom-fields`, `POST /public/{operator_slug}/orders/quote`, and `POST /public/{operator_slug}/orders`. The response includes customer-facing calendar policy metadata, resource-aware rate availability, itemized fees/taxes, and the access token required by the confirmation and waiver flows.

## Operator configuration

Calendar creation and update are handled by `POST /calendars` and `PATCH /calendars/{calendar_id}`. Hours, date-specific hours, pushed times, blocks, rate plans, resource mappings, bookability mode, booking cutoff, call-to-book phone, customer types, and public links are configured from the Calendars and Resources pages. Calendar create/update, rate replacement, resource replacement, hour changes, pushed times, blocks, and policy replacement all enqueue the existing idempotent GHL calendar sync and reconcile future appointments where relevant.

Resources are quantity pools. A rate may consume one or more resource pools per booking unit. Inventory is checked transactionally in Passport; GHL is not used as the availability authority. Staff identities continue to originate from GHL. Passport only assigns custom operational roles and booking assignments, and those assignments are included in appointment metadata/sync.

## Operator booking operations

The Bookings page supports search, date/calendar filtering, booking detail, participant manifest, notes, status actions, cancellation, rescheduling/quantity updates where allowed, waiver state, payment state, resource consumption, retrying failed GHL sync, and staff assignment. A booking mutation updates Passport first and creates the correct GHL appointment sync or cancellation outbox job. The worker processes retries idempotently.

## GHL synchronization boundary

GHL receives a calendar projection, contact upsert, appointment create/update/cancel, and staff identity synchronization. Passport does not delegate booking inventory, prices, policies, payments, waivers, or customer-facing checkout to GHL. Every external mutation is represented by an outbox job with an idempotency key and a visible sync status/error in the operator booking detail.

## Deliberate exclusions

FareHarbor's optional gift-card balance/ledger, advanced paid extended-option pricing, reseller channels, split payments, and abandoned-cart marketing are separate accounting or channel products. They should not be represented by a UI-only placeholder. If required later, they need dedicated immutable ledger tables, quote recalculation, redemption rules, and refund/reversal handling.
