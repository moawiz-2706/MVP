# Hotel partners and revenue split

Hotels (Sunseeker, Wyvern, Four Points, …) send bookings and share the
revenue. A booking with no partner is **Direct**.

| | Partner booking | Direct |
|---|---|---|
| `hotel_commission_20pct` | gross × hotel rate (default 20%) | 0 |
| `pga_commission_30pct` | gross × PGA rate (default 30%) | 0 |
| `net_to_operator` | gross − hotel − PGA (default 50%) | gross (100%) |

- **Gross** (`gross_booking_amount`) is the booking price before tax, booking fee and gratuity (the order subtotal).
- A **partial refund** lowers gross in proportion to the amount refunded. A **cancelled, refunded or expired** order has a zero split.
- **Gratuity** is not collected yet; `gratuity_amount` is always 0.
- Each booking keeps the partner's name and rates from when it was made, so changing a partner's rates only affects new bookings.

## How a booking gets its partner

- **Partner booking link:** `https://<passport>/book/<operator>?partner=<code>`, copied from **Partners**. The code is remembered for the browser tab through checkout. An unknown or switched-off code books as Direct; it never blocks a sale.
- **Staff choice:** the "Booked through" dropdown on New booking (Passport desktop and PWA).

## Where it shows

- **Partners** page (admins only): add, edit, switch off, copy each partner's link.
- **Booking drawer:** "Partner split" section.
- **Reports** (admins): "Partner commissions" by tour date (operator-local), per partner and Direct.
- **Marketplace trigger payload:** `source_partner`, `gross_booking_amount`, `hotel_commission_20pct`, `pga_commission_30pct`, `net_to_operator`, `gratuity_amount`, `number_of_guests`, `tour_date` (operator-local `YYYY-MM-DD`), `tour_type` (calendar category). These follow the published v1.0 keys. Workflows can use them as custom variables only after a new trigger version adds them to the sample payload.

HighLevel Opportunities and pipelines are deliberately not created.

Migration: `supabase/migrations/047_booking_partners.sql` (readiness marker 047: apply it before deploying).
