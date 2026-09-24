# Passport FareHarbor Alternative: Production Implementation Plan

## Phase 0 — Baseline and boundaries

Preserve the existing multi-tenant FastAPI, SQLAlchemy/PostgreSQL, React, Stripe, waiver, outbox, and GHL OAuth architecture. Passport is authoritative for products, availability, inventory, pricing, customers, participants, policies, payments, waivers, booking state, reports, and customer self-service. GHL is authoritative for staff-directory records and remains the projection target for calendars, contacts, appointments, and approved staff-role identity data.

Required baseline gates are application import, migration-chain application to a disposable PostgreSQL database, backend regression tests, frontend typecheck/build, public booking smoke flow, Stripe webhook reconciliation tests, outbox retry tests, and responsive/accessibility checks.

## Phase 1 — Booking engine integrity

Add transaction-safe availability reservation primitives: a booking hold table or immutable reservation ledger, a unique/overlap-safe inventory allocation rule, staff-role conflict evaluation, and an explicit conflict response. Ensure every quote is revalidated at order creation, every pending payment has an expiry, and expiry releases all resource allocations and cancels the associated GHL appointment projection.

Add public and operator booking mutation contracts for cancellation and rescheduling. Each mutation must evaluate the immutable policy version captured on the booking, calculate cancellation/reschedule fees or credit/refund outcomes, append an audit event, update Passport status, and enqueue an idempotent GHL appointment update/cancellation.

## Phase 2 — Commercial rules

Introduce promotion campaigns, coupon codes, eligibility windows, usage limits, per-customer limits, calendar/rate scope, stacking rules, and immutable discount snapshots. Add a gift-card liability ledger with issuance, redemption, partial redemption, expiration, refund reversal, and concurrency-safe balance updates. Only after ledger tests pass should the public checkout expose discount or gift-card fields.

Add optional paid extended options as line items with inventory/resource constraints, tax/fee behavior, pricing snapshots, and refund rules. Keep the current rate/line-item model backward compatible.

## Phase 3 — Customers, participants, and communications

Complete customer deduplication and customer profile CRUD, participant manifest editing, minor/guardian validation, emergency contact capture, notes, consent records, and export. Add customer self-service status, waiver, cancellation, and reschedule endpoints authenticated by access-token digest and rate limited per order.

Implement Passport confirmation and operational notifications through a capability-gated provider interface. GHL messaging is optional and must not be required for booking success. Calendar/contact/appointment synchronization remains the default GHL boundary.

## Phase 4 — Operator operations and reporting

Upgrade the dashboard with today/upcoming bookings, gross/net revenue, payment exceptions, capacity utilization, cancellations, pending waivers, staff-role gaps, failed outbox jobs, and GHL sync health. Upgrade calendar views with month/week/day modes, filters by activity/status/staff, capacity/resource indicators, block controls, and click-through booking drawers.

Add reports and exports for bookings, revenue, taxes/fees, refunds/credits, customer activity, cancellation/no-show rates, inventory utilization, and staff assignment coverage. All report queries must be tenant-scoped and support bounded date ranges.

## Phase 5 — GHL reconciliation and scale

Complete staff directory reconciliation with source-of-truth rules, deactivation handling, role assignment cache, and retryable permission verification. Add calendar/appointment webhook reconciliation where provider support allows, provider request IDs, rate-limit backoff, dead-letter visibility, manual retry, and repair commands. Ensure calendar/rate/resource/policy changes all create a desired revision and reconcile future appointments.

## Phase 6 — UX and release

Use a consistent FareHarbor-inspired visual system: activity-first public cards, clear option/quantity cards, sticky order summary on desktop, single-column mobile checkout, visible taxes/fees, policy disclosure, accessible labels, keyboard navigation, empty/loading/error states, and clear confirmation/waiver actions. Operator pages should use consistent table, filter, modal, drawer, and confirmation components.

Release only after each inventory row has a database/API/UI/test status, no unresolved import or migration errors, and a clean repository package containing complete Git history.

## Immediate next implementation increment

The next code increment should implement the missing customer self-service cancellation/reschedule workflow, reporting/dashboard read models, and conflict-focused booking tests. These provide the highest production value after the already-completed public checkout, rate/resource capacity, policy display, payment, waiver, booking operations, and GHL outbox foundation.
