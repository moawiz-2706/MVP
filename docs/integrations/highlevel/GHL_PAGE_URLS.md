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

On the authenticated **Bookings** page, select **Booking link** to open the public operator booking URL, copy it, open it, or copy its embed code. The URL uses the current HighLevel subaccount's operator slug. Operator slugs are generated uniquely and protected by a database-wide unique constraint, so two subaccounts cannot receive the same operator booking path.

## Private staff mobile booking links

Private staff links are generated from a staff member's details dialog. They are not public customer links and should not be added as public HighLevel navigation items:

```text
https://YOUR-PASSPORT-FRONTEND-DOMAIN/staff-book/{privateToken}
```

The private staff page shows live available slots, collects the client's details, and lets the staff member either send a secure hosted invoice or create a free appointment. Regenerating a link immediately revokes the previous link, and inactive staff links stop working. Treat each link as a private bearer credential.

## HighLevel setup notes

- Add the authenticated `/app/...` links as menu items in the HighLevel app/navigation configuration.
- The user must still be authenticated through the existing HighLevel Passport session provider.
- Configure the frontend deployment to serve the SPA fallback for direct links; otherwise refreshing a nested URL can return a server 404.
- The route names are stable and use lowercase paths.
