# Paid booking adjustments and persistent Staff PWA session

## Problem

The current booking PATCH endpoint intentionally rejects paid time or quantity changes with HTTP 409. This prevents a booking from being changed without collecting an additional amount or refunding a decrease. The current PWA also depends on an HTTP-only recovery cookie, so the cookie must be preserved by the deployment topology and refreshed before the app shows the login screen.

## Approved payment workflow

1. Load and lock the booking, order, payment, and current reservation rows.
2. Calculate the old and new booking totals from the stored line total and unit count.
3. For an increase, create a durable `booking_adjustments` row with `action = charge`, create a Stripe PaymentIntent only for the positive difference, and return its client secret. The booking and resource reservation are not changed until Stripe confirms the adjustment PaymentIntent.
4. When Stripe confirms that PaymentIntent, validate its metadata, amount, currency, account, and live/test mode. Then rebuild the reservation using the same availability/resource calculation used by normal booking edits, mark the adjustment succeeded, and append a booking audit event.
5. For a decrease, rebuild the reservation immediately, create a durable `refund` adjustment, and queue the existing Stripe refund/transfer-reversal infrastructure. The refund amount is the negative difference.
6. For a time-only change with no price difference, update the reservation immediately and record a zero-value audit adjustment.
7. Every operation uses an idempotency key. A repeated request returns the existing adjustment instead of creating another charge or refund.
8. If an additional payment succeeds but the new slot is no longer available, the adjustment is moved to manual review and a compensating refund is required; the booking is never silently changed.

## PWA session workflow

1. Keep short-lived access tokens in memory only.
2. Keep the long-lived recovery credential in an HTTP-only, Secure, SameSite cookie.
3. Refresh from the cookie on every standalone PWA launch before showing the login screen.
4. Make the cookie path and API topology explicit. The installed PWA must call `/api/v1` on the same Passport origin; a separate API origin cannot receive a same-origin cookie.
5. Treat temporary network/504/cold-start failures as reconnectable and do not clear the session. Only a confirmed 401 from the refresh endpoint or an explicit user sign-out ends the session.
6. Keep the durable server-side PWA device session revocable and rotate the refresh nonce on every refresh.
7. Add a visible Sign out action that revokes the device session.

## Deployment requirements

- Apply the existing PWA session migration before deploying the code.
- Keep the frontend and API under the same public origin (for example `https://mvp-one-hazel.vercel.app` with `/api/v1` routed to the backend).
- Do not set `VITE_API_BASE_URL` to a different domain in production.
- Verify that the production response contains `Set-Cookie: passport_pwa_session=...; HttpOnly; Secure; SameSite=Lax` and that a second launch sends the cookie to `POST /api/v1/pwa-auth/refresh`.
- Stripe webhooks remain the source of truth for successful adjustment payments; the browser never marks an adjustment paid by itself.
