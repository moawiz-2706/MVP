# Passport Frontend CRUD Coverage

## Migration-critical operator workflows

| Area | Frontend location | Read | Create | Update | Delete or close | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Calendars | Calendars | Yes | Yes | Yes | Soft delete | Includes hours, date hours, pushed times, blocks, resources, rates, public booking mode, and booking link. |
| Categories | Calendars → Categories | Yes | Yes | Yes | Soft delete | Category deletion is confirmed and historical records remain protected by backend rules. |
| Resources | Resources | Yes | Yes | Yes | Soft delete | Shared inventory quantities and active state are editable. |
| Locations | Locations | Yes | Yes | Yes | Soft delete | Departure locations are attached to calendars. |
| Customer types | Booking setup → Customer types | Yes | Yes | Yes | Soft delete | Supports Single Kayak, Tandem Kayak, and other participant/equipment types. |
| Calendar rates | Calendars → Edit → Rates | Yes | Yes through rate replacement | Yes through rate replacement | Deactivated through replacement | Rates include price, booking fee, tax, and resource mapping. |
| Booking policies | Booking setup → Booking policy | Yes | Versioned publish | Versioned publish | Historical versions retained | Covers cancellation, reschedule, weather, no-show, deposit, and waiver requirements. |
| Participant fields | Booking setup → Participant fields | Yes | Yes | Yes | Soft delete | Fields are shown in public checkout and operator-created bookings. |
| Staff identity and roles | Staff | Yes | GHL sync | Passport custom role | Deactivate through GHL sync | GHL remains authoritative for staff identity. |
| Staff assignment | Bookings and Notifications | Yes | Yes | Yes | Yes | Assignment can be changed per booking time slot and role. |
| Booking operations | Bookings drawer | Yes | Operator booking | Edit time/quantity; status transitions | Cancel, no-show, weather closure | Includes notes, waiver link, payment state, GHL sync retry, and itemized rate information. |
| Customers | Customers | Yes/search/detail | Created by bookings | Yes plus notes | Historical records preserved | Customer records are Passport-owned and deduplicated by normalized email. |
| FareHarbor import | Migration & reconciliation | Yes | Stage import | Commit validated import | Not destructive | Rows are stored individually and blocking errors prevent commit. |
| Reconciliation | Migration & reconciliation | Yes | Start run | Worker/result state | Not applicable | Scopes include inventory, bookings, payments, waivers, and GHL projection. |
| Waivers | Settings and booking drawer | Yes | Configure | Configure | Disable by clearing setup | Customer signing remains public and booking-linked. |
| Stripe | Settings → Payments | Yes | Connect/onboard | Continue setup | Disconnect behavior remains provider-controlled | Passport owns payment state and refund foundations. |

## Recommended Kayak Swamp Tour setup order

First create the departure location and shared resource pools for single kayaks, tandem kayaks, guides, and any trailer or launch inventory. Then create the Kayak Swamp Tour calendar with duration, timezone-compatible weekly hours, slot interval, public booking mode, party-size limits, and resource mappings.

Next create customer types such as Single Kayak and Tandem Kayak. Configure each calendar rate with the customer-facing price, fee and tax basis points, seat count, and resource consumption. Publish a booking policy and define required participant fields such as launch site, emergency contact, experience level, or waiver-related details.

Before importing future FareHarbor bookings, stage a normalized export in Migration & reconciliation. Resolve every row with a missing external ID or unresolved identity, commit the clean import, and run bookings, inventory, payments, waivers, and GHL projection reconciliations. Only then enable public booking and begin the dual-run cutover.

## GHL boundary

The frontend never uses GHL as the source of truth for Passport price, inventory, customer fields, policy decisions, payment state, waiver state, or booking eligibility. GHL is used for embedded identity, staff identity, contact projection, and calendar/appointment synchronization.
