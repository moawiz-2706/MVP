# Staff PWA Without HighLevel Login

**Repository:** `https://github.com/moawiz-2706/MVP.git`
**Fresh clone:** `/home/ubuntu/MVP_20261020`
**Commit reviewed:** `c5393a1 Fix standalone PWA origin and persistent sessions`
**Status:** Planning only; no application source code or database migration was changed.

## Short answer

Yes, the standalone Staff PWA can stop using HighLevel OAuth for staff login. However, it should **not** become an unauthenticated app.

The recommended design is:

```text
Operator/Admin creates a staff invite in Passport
        ↓
Passport generates a short-lived, single-use activation link for that staff member
        ↓
Staff opens the link and creates a Passport PIN/password
        ↓
Staff installs or opens the Passport Staff PWA
        ↓
Staff signs in with Passport email/username + PIN/password
        ↓
Passport creates its own secure session
        ↓
Backend authorizes the staff member by Passport staff/operator membership
```

HighLevel can remain connected on the **backend** for calendar, contact, appointment, and staff synchronization. The staff member’s PWA login would no longer depend on the HighLevel login page, HighLevel mobile support, OAuth redirects, or HighLevel user lookup.

## Why removing authentication completely is unsafe

A PWA URL is not a security boundary. If the app allows access just because someone knows a URL, the URL can be forwarded, copied from browser history, exposed in screenshots, or stolen from a device. A full Staff PWA can view bookings, customer details, payments, waivers, calendars, and possibly configuration. It must authenticate every user and enforce permissions on the backend.

The existing `/staff-book/{token}` link is a useful compatibility feature, but it is not sufficient as the main full PWA login:

- it is a bearer token; whoever has the token can use it;
- the current staff booking link is issued for up to 365 days;
- it is designed around booking-link routes, not the complete operator/staff workspace;
- it does not provide a normal Passport login, device session management, or a staff password/PIN;
- it is scoped to the current `staff_booking` purpose and should not be reused as a full application session.

The existing implementation does correctly hash the stored token with SHA-256 and supports revocation through `PublicAccessService`. That mechanism can be reused for a one-time activation link, but the activation link itself should not become the long-lived PWA session.

## Recommended option: Passport staff invite plus PIN

### Initial activation

An operator or administrator opens the Staff page and clicks **Create Staff PWA Invite** for a specific active staff member. Passport creates a random one-time token, stores only its digest, and returns a URL such as:

```text
https://mvp-one-hazel.vercel.app/staff-pwa/activate/<one-time-token>
```

The invite should have these properties:

- expires after 10–15 minutes;
- can be consumed only once;
- is tied to exactly one `staff_id` and `operator_id`;
- is revocable by an operator/admin;
- is not accepted by booking-link endpoints;
- is not used directly as the authenticated API credential;
- is shown once to the admin for copying or sharing.

The staff member opens the link, verifies the staff name/operator shown on screen, and creates a PIN or password. A six-digit PIN is convenient for a phone; a longer password is stronger. For higher security, the system can require a one-time email code as an additional activation step, but this is optional and does not need to be sent through GHL.

### Normal login after activation

The staff member opens the installed Passport PWA and enters their Passport staff email/username and PIN/password. Passport verifies the stored password hash and creates a Passport session. The browser never receives a HighLevel access token or refresh token.

Recommended session behavior:

- use a secure, HttpOnly, SameSite cookie for the refresh/session credential where possible;
- use short-lived access sessions, for example 15–60 minutes;
- rotate refresh sessions on use;
- store only a session/refresh-token digest in the database;
- support logout from the current device;
- support **Revoke all Staff PWA sessions** from the Staff administration page;
- lock or rate-limit repeated failed PIN/password attempts;
- require a new activation or password reset if the staff account is revoked or disabled.

The current PWA stores its Passport JWT in `localStorage` as `passport_staff_session`. That works technically, but a new Passport-owned login should preferably move to an HttpOnly cookie/rotating refresh-session design to reduce exposure from browser XSS.

## Suggested database changes

The cleanest design is to add dedicated Passport staff-PWA tables instead of making GHL fields mandatory for every session.

### `staff_pwa_accounts`

One row per staff member who has activated the PWA:

- `id`;
- `operator_id`;
- `staff_id`;
- `login_email` or normalized login identifier;
- `password_hash` or `pin_hash` using Argon2id or bcrypt;
- `is_active`;
- `failed_attempt_count`;
- `locked_until`;
- `last_login_at`;
- `created_at` and `updated_at`.

Add a unique constraint for `(operator_id, staff_id)` and a suitable unique normalized login policy. Do not store a raw PIN or password.

### `staff_pwa_invites`

One row per activation/reset invitation:

- `id`;
- `operator_id`;
- `staff_id`;
- `token_digest`;
- `expires_at`;
- `consumed_at`;
- `revoked_at`;
- `created_by_user_id`;
- `created_at`.

Add a unique index on `token_digest`, indexes on `(staff_id, revoked_at)`, and a check preventing an already-consumed invite from being reused.

### `staff_pwa_sessions`

One row per active device/session if rotating refresh sessions are used:

- `id`;
- `operator_id`;
- `staff_id`;
- `session_token_digest` or refresh-token digest;
- `expires_at`;
- `last_used_at`;
- `revoked_at`;
- `user_agent` and optional device label;
- `created_at`.

This makes individual-device logout and global staff-session revocation possible.

### Optional changes to existing models

The existing `SessionPrincipal` currently includes `ghl_location_id`, and `get_current_principal()` validates an active `GHLInstallation` plus an `OperatorUser` membership. A Passport-owned staff login should not fail merely because the staff member cannot log in to HighLevel.

Two safe approaches are possible:

1. add an authentication-source claim, such as `auth_source = "ghl"` or `auth_source = "passport_staff"`, and validate Passport staff sessions through `staff_id`; or
2. introduce a separate `StaffSessionPrincipal` dependency for Staff PWA routes.

The second option is safer initially because it avoids accidentally weakening the existing GHL/operator authorization flow. Shared service methods can still receive the resolved `operator_id` and `staff_id`.

## Recommended API routes

The implementation should add routes similar to:

```text
POST /api/v1/staff-pwa/invites
POST /api/v1/staff-pwa/invites/revoke
POST /api/v1/staff-pwa/activate
POST /api/v1/staff-pwa/login
POST /api/v1/staff-pwa/refresh
POST /api/v1/staff-pwa/logout
POST /api/v1/staff-pwa/logout-all
GET  /api/v1/staff-pwa/me
```

### Create invite request

```json
{
  "staff_id": "staff-uuid"
}
```

The response should return the one-time activation URL only to the authorized operator/admin who created it:

```json
{
  "staff_id": "staff-uuid",
  "activation_url": "https://example.com/staff-pwa/activate/one-time-token",
  "expires_at": "2026-10-20T02:00:00Z"
}
```

### Activate request

```json
{
  "token": "one-time-token",
  "pin": "123456"
}
```

The endpoint should validate the invite, hash the PIN, create or update the staff PWA account, consume the invite, and issue the first session.

### Login request

```json
{
  "login": "staff@example.com",
  "pin": "123456"
}
```

The response should contain a Passport session only. It should never contain a HighLevel provider token.

## Permission behavior

The PWA can still have one interface, but the backend must enforce permissions. A staff member should normally receive:

- view calendar;
- view permitted bookings;
- create or update bookings if the operator grants it;
- add participants and notes if granted;
- view waiver status and links;
- view payment/invoice status without exposing unnecessary payment secrets.

Calendar creation, rate changes, resource changes, staff management, Stripe Connect settings, and destructive configuration should remain restricted to an operator/admin permission. The frontend may hide unavailable pages, but the backend must remain the final authority.

The staff identity should also be scoped to the staff member’s operator. Every route must prevent a staff session from reading another operator’s bookings or changing another operator’s calendar.

## What happens to HighLevel integration

Removing HighLevel OAuth from the PWA login does **not** require removing HighLevel from the backend integration.

Recommended separation:

```text
Staff login: Passport staff account/session
GHL integration: backend installation token/service connection
Calendar/contact/appointment sync: backend jobs or provider calls
```

The backend can continue using the existing encrypted GHL installation token for calendar and appointment synchronization. Staff members do not need to authenticate to HighLevel just to view or operate Passport data.

If the goal is to remove HighLevel completely, then the following must also be changed or disabled:

- GHL calendar projection;
- GHL contact and appointment sync;
- GHL staff directory synchronization;
- GHL OAuth installation records;
- GHL-specific session checks in `get_current_principal()`;
- GHL resync actions and GHL sync notifications;
- any routes that assume `ghl_location_id` exists.

That is a much larger product change than simply replacing PWA login.

## Alternative options

### Option A: Existing staff booking link as the only login

This is the fastest but least secure option. The existing 365-day link could open the PWA and act as a bearer credential. It is acceptable only for a limited booking page, not for a workspace containing customer, payment, waiver, calendar, and configuration data.

### Option B: Staff activation link plus PIN

This is the recommended option. It avoids HighLevel mobile OAuth problems, does not require Passport to send email/SMS, supports staff-specific access, and can be revoked. It is the best balance of implementation effort and security for this project.

### Option C: Email magic link on every login

Passport generates a short-lived login link and sends it to the staff email. This avoids a password but requires a reliable email provider and makes the email account the security boundary. It is not ideal if the product does not yet want Passport-owned messaging.

### Option D: Email plus one-time code

Passport sends a one-time code to the staff member’s email or authenticator. This is stronger than a permanent link but still requires a message delivery provider or authenticator setup.

### Option E: Keep HighLevel OAuth

This remains the most complete identity mapping because HighLevel already supplies the location, user, and role context. It is not the best user experience for the current iPhone/mobile problem, but it can remain available for installation/admin setup while staff use Passport login afterward.

## Recommended implementation phases

### Phase 1: Passport-only authentication foundation

Add staff PWA account, invite, and session tables. Add Argon2id/bcrypt hashing, rate limiting, invite expiry, revocation, session rotation, and a separate Passport staff principal. Keep the existing GHL OAuth routes unchanged for backward compatibility.

### Phase 2: Admin invite UI

Add a button beside each active staff member: **Create PWA Invite**, **Copy Invite**, **Revoke Invite**, and **Revoke All Sessions**. Display the expiry clearly. Never show the raw activation token again after the creation response.

### Phase 3: PWA activation and login screens

Add `/staff-pwa/activate/:token` and a Passport login screen. After activation, the staff member can install the PWA from the Passport domain and sign in without visiting HighLevel.

### Phase 4: Scope all Staff PWA routes

Move the Staff PWA pages from the current GHL-dependent principal to the Passport staff principal. Test booking creation, calendar view, booking update, waiver view, payment view, and permission failures with multiple staff members and multiple operators.

### Phase 5: Optional migration and fallback

Keep the current HighLevel OAuth login as an optional fallback for administrators during the migration. Once Passport login is proven, make it the default Staff PWA login. Keep `/staff-book/{token}` for quick booking compatibility, but do not use it as the full PWA session.

## Final recommendation

Do not make the PWA public or remove authentication completely. Replace the unreliable mobile HighLevel login with a **Passport-managed staff invite + PIN/password + revocable session**. Keep GHL authorization only on the backend for synchronization, unless the product decision is to remove GHL integration entirely.

No code or database changes were made during this review. The next implementation step should be the database/authentication slice first, followed by focused tests before changing the PWA screens.
