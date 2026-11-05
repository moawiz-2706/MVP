# Changelog

Notable changes to Passport. Dates are deployment dates (UTC).

## Unreleased

### Added
- **Staff bookings with several products**: the private staff link now has a
  booking list, so staff add several calendars, times and rates and take one
  payment, as on the public booking link.
- **Guest-details QR code** on a staff booking's confirmation (migration 050):
  the party scans it and each guest fills in their own waiver (name, date of
  birth, phone, email). The page only shows waivers; it cannot cancel,
  reschedule or see payment details, and it lasts as long as a waiver link.
- **Calendar photos and video** (migration 050): upload photos or paste links
  in Calendars → Edit; Passport stores a copy in HighLevel Media Storage
  (needs the `medias.write` scope and a reconnect). A YouTube, Vimeo or short
  video file shows on the public booking page.
- **HighLevel contacts from waivers**: phone and date of birth fill in only
  when the contact has none; every other adult on a waiver gets their own
  contact, tagged `passport-guest`. US 10-digit phone numbers are accepted.
- TanMan Charters beach cruises import script
  (`supabase/manual/2026-11-06_tanman_beach_cruises_import.sql`) and the
  FareHarbor photo links for every calendar
  (`docs/integrations/fareharbor/PHOTO_LINKS.md`).
- HighLevel Marketplace Custom Trigger `passport_booking_created` runtime
  (off until `GHL_WORKFLOW_TRIGGER_ENABLED=true`, after migration 045): the
  Subscription URL callback, durable `booking_created` / `payment_confirmed` /
  `booking_updated` / `booking_cancelled` events from all booking entry
  points, per-workflow delivery with retry, and status plus retry in the
  booking drawer and Notifications. See
  `docs/integrations/highlevel/MARKETPLACE_TRIGGER_RUNTIME.md`.
- **Per-rate booking rules** (migration 044): a rate can hold its resources
  for its own length (e.g. 2–8 hour private charters on one calendar), have a
  per-booking minimum/maximum (group-size price tiers like the escape room),
  and a per-departure cap (e.g. at most 10 children). Enforced by the
  availability engine, order creation and booking edits; editable in the
  Calendars rate editor.
- **FareHarbor-style public booking page**: listing with photo gallery, prices
  per customer type and overview; sticky booking widget with a month calendar
  of bookable days, time list and a counter per customer type. New endpoint
  `GET /public/{operator}/calendars/{calendar}/availability/month`.
- FareHarbor catalogue import v2 for every currently sold item, with the
  exact FareHarbor schedules through 2027.

### Added (earlier in this release)
- Staff PWA: "Book this departure" on the Departures board opens New Booking
  with the activity, date and time preselected (same-day allowed) and returns
  to the board when closed or finished.
- Waivers: every adult in the party must give email and phone; signed
  attendees are added to the departure manifest automatically, with the adult
  signer recorded as guardian for minors.
- FareHarbor catalogue import, batch 1 (`supabase/manual/2026-11-03_fareharbor_catalog_import.sql`):
  7 resources, the Laishley Park Marina location, the public Oasis sunset
  cruise and the 2-hour private charter sharing the 30 Oasis seats, created
  inactive for review. Mapping and open decisions in
  `docs/integrations/fareharbor/CATALOG_MAPPING.md`.
- `docs/planning/SCOPE_STATUS.md`: client scope item-by-item status.

### Changed
- Removing a calendar that has bookings now **archives** it: it is hidden and
  stops taking bookings, while every booking, payment, note and waiver is kept
  and its HighLevel calendar is marked inactive. A calendar or category with
  upcoming bookings cannot be removed until they are cancelled or moved.
  Calendars without bookings are deleted as before.
- Bookings without assigned staff no longer raise a notification or a dashboard
  alert; staff are assigned after a departure is sold.
- Repository reorganised: documentation under `docs/`, manual SQL under
  `supabase/manual/`, standard `.gitignore`, `.gitattributes`, `.editorconfig`,
  contributor guide and CI workflow.

## 2026-11-02

### Added
- Staff PWA departure board with per-resource capacity, manifest and
  per-person check-in, admin slot-wide weather closure with preview.
- Booking creator and channel attribution, and an admin bookings-by-creator
  report.
- Release of abandoned card checkouts and cancellation of their Stripe
  PaymentIntents.
- Fail-safe startup: a misconfigured deployment keeps `/api/health` and
  `/api/readiness` up, names the missing setting and returns 503 elsewhere.
- Migrations 041 (row level security), 042 (PWA refresh grace) and 043
  (attribution, check-in, intent cancel).

### Fixed
- Staff PWA sign-outs caused by racing refreshes and lost refresh responses.
- PWA and OAuth cookies are marked `Secure` on every HTTPS deployment.
