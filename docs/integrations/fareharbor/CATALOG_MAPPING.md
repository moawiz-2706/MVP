# FareHarbor → Passport catalogue mapping

Source: `MVP_FAREHARBOR_VISIBLE_INVENTORY_2026-11-03.csv`, a read-only
inspection of the Punta Gorda Adventures FareHarbor account. Only data marked
as observed is imported; nothing is inferred from item names or card prices.

Import script: [`supabase/manual/2026-11-03_fareharbor_catalog_import.sql`](../../../supabase/manual/2026-11-03_fareharbor_catalog_import.sql)
(idempotent, additive, calendars created **inactive**).

## How FareHarbor concepts map

| FareHarbor | Passport | Notes |
|---|---|---|
| Resource (max uses) | Resource (quantity) | Shared across calendars; this is the real inventory. |
| Item | Calendar | One calendar per sellable product and duration. |
| Customer type + price | Customer type + calendar rate | Price in cents; 7% tax added on top (`tax_bps = 700`). |
| Item resource rule | Rate → resource, quantity per unit | Public guest = 1 seat; private charter = 30 seats. |
| Fixed availabilities | Weekly hours window + slot interval | Window sized so only the real start times are offered. |
| Calendar view (Default, Gift Card, Christmas Lights Tours) | Calendar category | Display grouping only, never separate inventory. |
| Location | Departure location | |
| Cancellation policy | Calendar booking policy | Account default: full refund > 48 h before start. |
| Booking flows, affiliates, affiliate price sheets | Not imported | FareHarbor checkout/reseller setup; not Passport concepts. Affiliate "Referral/Billing %" is not staff commission. |

## Batch 1: imported (inactive until reviewed)

| FareHarbor item | Passport calendar | Schedule | Rates (before 7% tax) | Inventory |
|---|---|---|---|---|
| 502154 "The Oasis" BYOB Sunset Cruise – Public | `oasis-sunset-cruise-public` | Daily 4:30 PM | Adult (13+) $59 · Child (12 and under) $35 · *Adult (Dec) $69, Child (Dec) $45 — inactive* | 1 Oasis Tiki seat per guest, 30 per departure |
| 508627 The Oasis Tiki Boat – Private Cruise (2 h) | `oasis-private-cruise-2h` | Daily 10:00, 12:30, 3:00, 5:30, 8:00 | Private Oasis 2 Hour $1,600 | All 30 Oasis Tiki seats; 1 charter per departure |

Plus all 7 resources (Motor Yacht 55ft ×1, SV Sea Dancer Seats ×6,
S/V Courageous Seats ×6, The Oasis Tiki Seats ×30, 37ft Hunter ×1,
41ft Morgan ×1, Carver 52ft MY ×1) and the Laishley Park Marina Public Dock
location (120 Laishley Ct, Punta Gorda, FL 33950).

Verified locally on a database built from all migrations: the departures
match FareHarbor exactly, and booking the 3:00 PM private charter makes the
4:30 PM public sunset cruise unavailable (shared seats), while the 5:30 PM
charter stays available.

## Decisions needed before activating batch 1

1. **Sunset cruise duration.** Not visible in the export; set to 2 hours as a
   placeholder. Duration decides which private charters it conflicts with.
2. **December prices.** Passport rates have no date range. The December rates
   are imported switched off; switch them on for December (and the standard
   rates off), or ask for date-ranged rates as a feature.
3. **Child cap of 8 per sunset departure.** Passport has no per-customer-type
   cap per departure yet. Until it does, children can take any of the 30 seats.
4. **Private cruise 3–8 hours** ($2,000–$3,250). In Passport, duration belongs
   to the calendar, so each length is its own calendar (and HighLevel
   calendar). Confirm which lengths are sold and their start times.
5. **Optional gratuity** (+15/20/22/25%) is not supported; tips are outside the
   approved scope.
6. **Hidden rates** "Pure Florida" ($500) and "Adult airBNB" ($55.20) and the
   inactive backend $800 rate were not imported; confirm if any are needed.

## Not yet importable (data missing in the export)

| FareHarbor item | Missing |
|---|---|
| 529145 Tropical Tides Scenic Day Cruise – Public | Customer-type prices and resource mapping (1.5 h, daily 2:30 PM, 30 per departure observed) |
| 508393 Escape Room "Quest for the Fountain of Youth" | Prices per player band, capacity, resource (times 9, 11, 1, 3, 5, 7 observed) |
| 529151 Club Tiki: LED Luau | Schedule, customer types, resources |
| 554566 Brunch On The Bay | Everything except the name |
| 535797 Private Boca Grande Cruise 6-Hrs · 536968 Private Lunch Cruise 4-Hrs | Schedule, price, resource |
| 553083 Firework Tiki Boat Show · 581806 New Years Eve 2027 · 524913 Valentine's Day Tour · 606282 Special Event Day Cruise | Event dates, prices, resources |
| 576786 / 576865 / 577774 Christmas canal cruise, boat parade, holiday canal cruise | Season dates, rates, resources |
| 579521 Access VIP Private Cruise · 617373 The NOT So Newlywed Game · 638865 Adult Trivia · 502144 Sunseeker VIP Cruise | Schedule, rates, resources |

## Deliberately not imported

- **Gift Card (431395)** — not a timed departure; gift cards would be a
  separate feature.
- **Credit Card Deposit (675245)** — FareHarbor internal-use item.
- **Special Events! (594477)** — a catalogue landing card, not bookable.
- Draft and test items seen only in affiliate filters.

## Waiver

FareHarbor's "Punta Gorda Adventures Waiver" text could not be exported.
Passport already holds operator waiver text in
[`docs/content/waiver-text-punta-gorda.txt`](../../content/waiver-text-punta-gorda.txt);
compare it with the FareHarbor template before relying on it.
