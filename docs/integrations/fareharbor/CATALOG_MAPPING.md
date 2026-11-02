# FareHarbor → Passport catalogue mapping

Source: `MVP_FAREHARBOR_VISIBLE_INVENTORY_2026-11-03.csv`, a read-only
inspection of the Punta Gorda Adventures FareHarbor account. Only data marked
as observed is imported; nothing is inferred from item names or card prices.

**Import script (current): [`supabase/manual/2026-11-03_fareharbor_catalog_import_v2.sql`](../../../supabase/manual/2026-11-03_fareharbor_catalog_import_v2.sql)**,
which needs migration `044_rate_duration_and_limits` first. It is idempotent,
creates calendars **inactive**, never reconfigures a calendar that already has
bookings, and upgrades databases where batch 1 already ran.

## Import v2: everything currently sold

| FareHarbor item | Passport calendar | Schedule (from FareHarbor's availabilities to 2027-12-31) | Rates (before 7% tax) | Inventory |
|---|---|---|---|---|
| 502154 Sunset Cruise – Public | `oasis-sunset-cruise-public` | Nov 2–30 2026: 4:30 PM · Dec 1 2026 – Dec 31 2027: 5:15 & 7:45 PM · closed Nov 29 | Adult $59 · Child $35 (max 10 per departure) · Dec rates $69/$45 inactive | 1 Oasis seat per guest |
| 529145 Tropical Tides – Public | `tropical-tides-scenic-day-cruise` | Nov 2026: 2:30 PM · Dec 2026 – 2027: 1:00 & 3:00 PM · none Dec 25 | Adult $49 · Child $35 | 1 Oasis seat per guest |
| 508627 Private Cruise | `oasis-private-cruise` | Daily 10:00, 12:30, 3:00, 5:30, 8:00 | 2 h $1,600 → 8 h $3,250 (7 options) | All 30 seats **for the chosen length** |
| 577774 Public Holiday Canal Cruise | `oasis-holiday-canal-cruise` | The exact 79 departures, Nov 29 – Dec 31 2026 | Adult $69 · Child $45 | 1 Oasis seat per guest |
| 576786 Private Christmas Canal Cruise | `oasis-private-christmas-canal-cruise` | Dec 2026, 5:15 & 7:45 PM (55 of 61 FareHarbor departures; 6 one-off times not captured) | 2 h $1,600 → 8 h $3,000 | All 30 seats for the chosen length (FareHarbor's 7 h = 1 seat error not copied) |
| 508393 Escape Room | `escape-room-fountain-of-youth` | Daily 9, 11, 1, 3, 5, 7 (90 min) | Per player: 1–2 players $29 · 3 players $25 · 4–7 players $22 (enforced group ranges) | None (outdoor game) |

Crew role offered when assigning staff: Captain for boat trips, Guide for the
Escape Room. Staff are not required before a departure is sold.

Verified on a local database at batch-1 state: v2 ran twice cleanly and the
offered departures matched FareHarbor on every date checked (including the
Nov 29 closure, Christmas Day, the night-specific canal sailings, and every
private length holding the boat for its own duration).

Not imported: Club Tiki: LED Luau (Nov 14 2026, 9 PM) and New Years Eve 2027
(Dec 31, 10:30 PM) — single events whose customer types were not captured;
create them in Passport or re-run the review.

## Batch 1 (superseded)

Kept for reference; v2 above replaces it.

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

1. **Sunset cruise schedule.** Duration is confirmed as 2 hours, but the
   imported "daily 4:30 PM" only matches November; December runs 5:15 and
   7:45 PM (see the live review below). Adjust the hours before activating.
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

## Live FareHarbor review (2026-11-03, read-only, in Cole's dashboard)

Nothing was changed in FareHarbor. Customer names seen on departure pages
were not recorded.

### Which items are still sold

| Item | Future departures |
|---|---|
| 508393 Escape Room "Quest for the Fountain of Youth" | 2,546 |
| 508627 The Oasis Tiki Boat – Private Cruise | 2,123 |
| 502154 "The Oasis" BYOB Sunset Cruise – Public | 822 |
| 529145 Tropical Tides Scenic Day Cruise – Public | 820 |
| 577774 The Oasis Tiki Boat Public Holiday Canal Cruise | 79 (Nov 29 – Dec 31) |
| 576786 The Oasis Tiki Boat – Private Christmas Canal Cruise | 61 |
| 529151 Club Tiki: LED Luau · 581806 New Years Eve 2027 | 1 each |
| All other items (Brunch, Boca Grande 6-Hrs, Lunch 4-Hrs, Firework Show, Christmas Boat Parade, Access VIP, Valentine's, Special Event Day Cruise, Newlywed Game, Sunseeker VIP, Adult Trivia, Special Events!) | **None** — not imported until they are scheduled again |

### Verified item details

| Item | Duration | Rates (before 7% tax) | Inventory |
|---|---|---|---|
| Sunset Cruise – Public | **2 h** (4:30–6:30 PM) | Adult $59, Child $35 (December: Adult $69, Child $45) | 1 Oasis seat per guest; children capped at **10** on the departure checked (export said 8) |
| Tropical Tides Scenic Day Cruise – Public | 1.5 h | Adult (13+) $49, Child (12 and under) $35 | **1 Oasis seat per guest** — the same 30-seat boat |
| Public Holiday Canal Cruise | 2 h | Adult $69, Child $45 | 1 Oasis seat per guest |
| Private Cruise | 2–8 h by option | 2 h $1,600 · 3 h $2,000 · 4 h $2,350 · 5 h $2,650 · 6 h $2,900 · 7 h $3,100 · 8 h $3,250 | All 30 Oasis seats **for the chosen length** from the start time |
| Private Christmas Canal Cruise | 2–8 h by option | 2 h $1,600 · 3 h $1,800 · 4 h $2,000 · 5 h $2,250 · 6 h $2,520 · 7 h $2,800 · 8 h $3,000 | All 30 Oasis seats for the chosen length — **except the 7 h option, see below** |
| Escape Room | not shown | Per player by group size: 1–2 players $29 · 3 players $25 · 4–7 players $22 | **No resource** (outdoor game) |

### Problem found in FareHarbor (fix there)

**Private Christmas Canal Cruise, "Private Oasis 7 Hour" uses only 1 of The
Oasis Tiki Seats; every other length uses all 30.** A 7-hour Christmas
charter therefore leaves 29 seats open for public cruises on the same boat.
Passport will use 30 seats for every private length.

### Schedules are date-by-date, not weekly (resolved in import v2)

FareHarbor departures are created individually (bulk-created by FareHarbor
support) and change with the season:

- Sunset cruise: daily 4:30 PM in November (5:30 PM on Nov 29), then 5:15 PM
  **and** 7:45 PM in December.
- Holiday Canal Cruise: Nov 29 – Dec 31, mostly 5:15 and 7:45 PM, with extra
  10:15 / 10:30 PM sailings on some nights and 4:30, 7:00 or 9:30 PM on others.
- Tropical Tides: 2:30 PM (some dates moved to 3:30 PM).

FareHarbor's dashboard has no export of availabilities, so copying ~6,300
future departures screen by screen is not practical or reliable.

## Batch 2 decisions (resolved 2026-11-03: schedules read from FareHarbor, per-rate lengths, group tiers and the children cap of 10 are built into Passport and import v2)

1. **Schedules:** (a) set Passport schedules by season (date ranges with fixed
   start times, plus closures for exceptions) from a short list the operator
   confirms, or (b) obtain FareHarbor's API or an availability export from
   FareHarbor support and import every departure exactly.
2. **Private lengths (2–8 h):** add per-rate durations to Passport (one
   Private Cruise calendar holds the boat for the chosen length, as FareHarbor
   does) or create one calendar per length (7 calendars and 7 HighLevel
   calendars per private product).
3. **Escape Room group pricing:** Passport has no group-size price tiers.
   Either add tiered pricing or sell three rates and let staff pick the tier.
4. **Children cap:** 8 or 10 per sunset departure (needs a per-type cap
   feature in Passport either way).

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
