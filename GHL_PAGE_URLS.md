# Passport direct page URLs for HighLevel

Replace `https://YOUR-PASSPORT-FRONTEND-DOMAIN` with the deployed Passport frontend origin.

## Authenticated Passport app pages

Use these URLs for HighLevel navigation links. Each page is directly routable and retains the restored global Passport sidebar.

| Page | Direct URL |
|---|---|
| Bookings | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/bookings` |
| Notifications | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/notifications` |
| Resources | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/resources` |
| Locations | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/locations` |
| Calendars | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/calendars` |
| Staff | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/staff` |
| Customers | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/customers` |
| Reports | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/reports` |
| Settings | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/app/settings` |

`https://YOUR-PASSPORT-FRONTEND-DOMAIN/app` remains supported and redirects to Bookings.

## Settings sections

Settings includes the global Passport sidebar plus an internal settings side navigation. Its sections are currently tabs rather than separate browser URLs:

- General
- Payments
- Communications
- Waiver

## Public/customer-facing page templates

These routes are separate from the authenticated HighLevel app navigation:

| Page | URL template |
|---|---|
| Operator booking page | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/book/{operatorSlug}` |
| Category booking page | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/book/{operatorSlug}/category/{categorySlug}` |
| Calendar booking page | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/book/{operatorSlug}/{calendarSlug}` |
| Booking confirmation | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/booking/{publicReference}/confirmation` |
| Waiver signing | `https://YOUR-PASSPORT-FRONTEND-DOMAIN/waiver/{token}` |

## HighLevel setup notes

- Add the authenticated `/app/...` links as menu items in the HighLevel app/navigation configuration.
- The user must still be authenticated through the existing HighLevel Passport session provider.
- Configure the frontend deployment to serve the SPA fallback for direct links; otherwise refreshing a nested URL can return a server 404.
- The route names are stable and use lowercase paths.
