# HighLevel Sub-Account Sidebar Navigation

Passport supports two navigation modes. A direct visit to `/app` keeps the Passport sidebar. A HighLevel Custom Page or Custom Menu Link adds `ghl_nav=1` to the URL, and Passport hides its internal sidebar so HighLevel remains the only primary sidebar.

## Configure these HighLevel sub-account links

| Label | URL |
| --- | --- |
| Bookings | `https://mvp-one-hazel.vercel.app/app?ghl_nav=1` |
| Notifications | `https://mvp-one-hazel.vercel.app/app/notifications?ghl_nav=1` |
| Resources | `https://mvp-one-hazel.vercel.app/app/resources?ghl_nav=1` |
| Locations | `https://mvp-one-hazel.vercel.app/app/locations?ghl_nav=1` |
| Calendars | `https://mvp-one-hazel.vercel.app/app/calendars?ghl_nav=1` |
| Staff | `https://mvp-one-hazel.vercel.app/app/staff?ghl_nav=1` |
| Settings | `https://mvp-one-hazel.vercel.app/app/settings?ghl_nav=1` |

Configure each item as an embedded iframe page in the **sub-account sidebar**. Give the user role access required by the account. HighLevel supports Custom Pages in the sub-account left navigation and also supports Custom Menu Links configured for the sub-account sidebar.

## Settings behavior

Create only one HighLevel item called **Settings**. Passport's Settings page keeps its own internal navigation for General, Payments, Communications, and Waiver. Do not create separate HighLevel sidebar entries for those tabs unless they are intentionally needed at the top level.

## Required hosting behavior

The frontend must be served over HTTPS and allow HighLevel to embed it. The current Vercel configuration permits the relevant HighLevel frame ancestors. The existing signed HighLevel user-context handshake is reused for every page, so separate OAuth applications are not needed.

## Test checklist

1. Open each link from the HighLevel sub-account sidebar.
2. Confirm the HighLevel sidebar is visible and the Passport sidebar is hidden.
3. Confirm the page loads in the iframe and completes the signed user-context handshake.
4. Open Settings and confirm its internal left navigation appears.
5. Open `/app` directly outside HighLevel and confirm the Passport sidebar remains available.
6. Test both an admin and a user account according to the configured HighLevel role visibility.
