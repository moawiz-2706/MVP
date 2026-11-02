# Client scope status

Tracks *Passport — Feature Scope for Approval* (prepared for Cole Kelly,
Maritime Digital, 2 November 2026) against the code on `main`.

Legend: **Done** = built and tested locally against PostgreSQL and deployed.
**Partly done** = what can be built without a pending decision is done.
**Blocked** = needs a client decision or third-party access first.

| # | Scope item | Status | What is in Passport | What is left / blocker |
|---|---|---|---|---|
| 1 | Mobile departure calendar | **Done** | Staff PWA Departures board: every configured departure including empty ones, activity, time, total/booked/held/remaining per resource type (never mixed), assigned staff, closures. | — |
| 2 | Simpler staff booking | **Done** | "Book this departure" opens New Booking with the activity, date and time preselected (same-day allowed in the PWA); closing or finishing returns to the board; lead booker's name shown; FareHarbor-style rate line removed from the PWA. Card, invoice and free options kept. | Card entry is the Stripe Payment Element inside the same form. |
| 3 | Booking and payment safety | **Partly done** | Checkout bookings stay "pending payment" until Stripe confirms; holds stop counting against capacity when they expire; abandoned card checkouts are released and their PaymentIntents cancelled; paid increase/decrease workflow; idempotent webhooks; last-unit concurrency test. | End-to-end runs in Stripe **test mode** (card, 3DS, failure, invoice, paid change, refund) need Stripe test keys on a staging deployment. |
| 4 | Slot-wide weather closure | **Done** | Admin preview of every booking/guest/payment/waiver/staff on the departure; confirm cancels and refunds each booking once, blocks new sales, queues the weather customer message once, and reports failures for a safe retry. | The refund rule per calendar must be approved (defaults to the calendar policy, else full refund). |
| 5 | Passenger manifest and waivers | **Partly done** | Lead booker reserves for the party; secure waiver link; **every adult in the party must give email and phone**; the adult signer signs as parent/guardian for listed minors; signed attendees are **added to the departure manifest automatically** (no duplicates with staff-entered names); waiver/payment status on the manifest; per-person check-in with audit. | A **separate link for each attendee** to sign individually (today one adult signs for the party). Needs a small schema change; can be built next. |
| 6 | HighLevel contact and waiver information | **Blocked** | Passport keeps the signed waiver record. | Cole to approve a secure link vs file attachment and which participant fields go to the HighLevel contact. |
| 7 | Staff-booking commission tracking | **Partly done** | Records which staff member and channel created each booking (separate from trip staff); admin-only report of orders, sales and refunds per creator. | Commission rules from Cole (percentage/fixed, base, timing, refunds/cancellations) before the commission ledger is built. |
| 8 | HighLevel custom trigger and workflows | **Blocked** | Customer messages use the existing Passport → HighLevel Conversations path; staff reminders stay in Passport. | Verify the approved custom trigger in the real HighLevel app and location, and its trigger contract. |
| 9 | Viator / OTA connection | **Blocked** | — | Viator supplier eligibility, sandbox access and certification, as listed in the scope. |

## Decisions recorded

- 2026-11-02: departures are sold without assigned staff; staff are added
  afterwards. Unstaffed bookings raise no notification.
- 2026-11-02: the two September test payments were voided, not refunded.
- 2026-11-03: a calendar with bookings is archived (history kept); one with
  upcoming bookings cannot be removed.

## FareHarbor parity added 2026-11-03

- Per-rate length, per-booking range and per-departure cap (migration 044),
  so 2–8 hour charters, group-size tiers and the children cap work like
  FareHarbor.
- Public booking page redesigned on FareHarbor's layout (listing + month
  calendar + time list + per-customer-type counters).
- Import v2 recreates every currently sold FareHarbor item with its real
  schedule through 2027 (calendars arrive inactive for review).
