# FareHarbor Feature Inventory and Passport/GHL Responsibility Matrix

## Purpose

This inventory defines the production scope for turning Passport into a FareHarbor alternative while keeping GoHighLevel (GHL) as the CRM, calendar, contact, and staff-directory synchronization layer. Statuses describe the current Passport branch after the completed FareHarbor-style booking increment and identify the next implementation work rather than implying that a UI placeholder is complete.

## Responsibility boundaries

| Area | Passport responsibility | GHL responsibility | Integration requirement | Current status |
|---|---|---|---|---|
| Tenant/operator configuration | Operator identity, slug, timezone, public-booking switch, business settings | Location identity and installation context | OAuth/location mapping | Partial |
| Staff directory | Cached staff records, Passport role/resource assignments, booking assignments | Staff creation, profile, permissions, employment status | Directory sync and staff identity mapping | Partial |
| Products/activities | Calendars, categories, descriptions, duration, locations, public links | Calendar projection | Create/update/delete sync with idempotent outbox | Complete for core path |
| Customer types and rates | Customer types, prices, taxes, fees, seat counts, resource rules | None | Include snapshots in contacts/appointments | Complete for core path |
| Resource inventory | Quantity pools, resource type, capacity/use limit, notes, archive state, and per-rate consumption | None | Include capacity summary in appointment metadata | Complete for core path |
| Weekly/date availability | Hours, date hours, pushed times, blackout blocks, cutoff rules | Calendar projection only | Requeue calendar and future-appointment sync | Complete for core path |
| Staff operational labels | GHL staff directory sync, optional Passport role labels, and assignment visibility | Staff directory source | Sync staff identity and availability; no booking gate | Complete for the requested booking model |
| Public booking page | Catalog, category, calendar page, timezone, slots, rates, custom fields, policy, payment | None | Optional GHL embed/link distribution | Complete for core path |
| Multiple booking items | Cart and quote model | None | One appointment per booked activity where configured | Partial; needs stronger cross-item conflict tests |
| Participants/manifest | Primary customer, participant CRUD, minor/guardian/emergency fields | Contact remains the primary CRM identity | Appointment metadata and contact association | Complete for operator core |
| Booking holds | Pending-payment hold expiration and inventory release | Appointment cancellation for expired hold | Outbox cancellation | Complete for core path |
| Payments | Stripe PaymentIntent, quote, reconciliation, payment status, refunds | None | No payment authority in GHL | Partial; refund/credit ledger needs expansion |
| Gift cards | Gift-card issuance, balance ledger, redemption, reversal | Optional contact note only | No direct GHL authority | Missing |
| Discounts/promotions | Coupon rules, eligibility, usage limits, audit trail | None | Include applied discount in appointment metadata | Missing |
| Taxes/fees | Basis-point pricing, line-item quote, immutable snapshots | None | Include totals in appointment metadata | Complete for core path |
| Custom fields | Field definitions, options, required validation, booking snapshots | Optional contact custom fields | Map selected safe fields to contact/appointment | Complete for core path |
| Waivers | Waiver settings, signed documents, participant signatures, status | None | Link and status in appointment/contact metadata | Complete for core path |
| Cancellation | Policy versioning, operator cancellation, customer policy display, token-authenticated self-service cancellation | Appointment cancellation projection | Idempotent cancel and status update | Partial; refund/credit outcome UX remains |
| Rescheduling | Booking time update, availability recheck, cutoff enforcement, zero-fee public self-service, fee/policy evaluation | Appointment update projection | Idempotent appointment update | Partial; fee-bearing adjustment remains operator-assisted |
| Weather closures | Idempotent closure event, affected-booking workflow, refund/credit/manual-review decision | Appointment cancellation/update | Batch outbox and audit log | Complete for core workflow |
| No-show/completion | Booking status and operational notes | Appointment status/notes where supported | Status projection | Partial |
| Notifications | In-app operational notices, email policy, reminders | Only approved calendar/contact sync | Do not require GHL messaging scopes | Partial |
| Customer communications | Passport confirmation/status/waiver links; optional provider adapter | CRM contact timeline if explicitly enabled | Capability-gated | Partial |
| Booking confirmation | Public confirmation page, payment state, access token | Appointment/contact projection | Include reference and sync status | Complete for core path |
| Customer self-service | Status, waiver, cancellation link, live-slot rescheduling, and policy-aware outcome | None | Token-authenticated Passport endpoints | Partial; fee-bearing reschedules remain operator-assisted |
| Operator bookings | Search, dashboard, detail, notes, participants, assignment, cancel, sync retry | Calendar event projection | Booking mutation outbox | Complete for core path |
| Calendar operations | Date slot grid, slot details, filters, capacity/resource indicators, blocks, and manual booking drawer | Calendar projection | No availability authority in GHL | Partial; core date-slot/manual-booking flow complete |
| Reports | Revenue, bookings, utilization, capacity, cancellations, customer metrics, summary dashboard, CSV export | Optional CRM attribution | Read-only aggregated Passport queries | Partial; detailed drilldowns remain |
| Dashboard | Today, upcoming bookings, revenue, capacity warnings, sync failures, staff gaps | None | Surface outbox health | Partial |
| Business settings | Payment, waiver, timezone, policies, booking defaults, branding | OAuth/location install | Secure settings and audit trail | Partial |
| Audit trail | Booking, payment, policy, sync, refund, import-independent event records | Provider request IDs | Correlation IDs and retention | Partial |
| Mobile/responsive UX | Responsive public and operator screens, accessible forms, loading/error states | None | None | Partial |

## FareHarbor public booking flow observed

The inspected Kayak Swamp Tour flow shows: activity/date selection; a live calendar of available times; a plan-your-experience step with option names, seat counts, prices, and quantity controls; activity image, date, time, and review context; contact details with full name, phone, and email; optional marketing consent; secured card payment; cancellation policy; gift-card redemption; subtotal; taxes and fees; total; and a Book and pay action. FareHarbor templates also support custom fields, participant-level data, quantity fields, extended paid options, waivers, transportation, resource-capacity validation, and post-checkout receipt workflows.

Passport now covers the first-party Kayak core path through live availability, rate/resource capacity, itemized pricing, custom fields, policy display and acceptance, Stripe checkout, confirmation, and waivers. Gift cards, discount campaigns, extended paid options, and customer self-service cancellation/rescheduling require additional accounting-safe work and are therefore explicitly tracked below.

## Required production completion sequence

1. **Booking engine hardening:** enforce transactional resource and staff-role conflict checks, cross-calendar overlap rules, idempotent holds, and complete cancellation/reschedule state transitions.
2. **Customer self-service:** add token-authenticated cancellation and rescheduling with policy version evaluation, fee/credit/refund outcome, and GHL appointment projection.
3. **Commercial rules:** add discounts/promotions and a gift-card liability ledger before exposing either option publicly.
4. **Operations:** add dashboard metrics, calendar capacity views, reporting queries, exports, sync-health surfaces, and audit events.
5. **GHL boundary:** complete staff directory reconciliation, appointment status mapping, calendar deletion/update recovery, provider rate-limit backoff, and webhook reconciliation.
6. **Release controls:** add migration-chain verification, end-to-end booking tests, payment recovery tests, accessibility checks, responsive visual checks, and deployment configuration validation.

## Acceptance rule

A feature is complete only when Passport has the database model, authorized API contract, operator or public UI, validation/error states, audit/sync behavior where relevant, automated regression coverage, and documented deployment requirements. A visual control without these layers remains **Missing** rather than **Complete**.
