# Staff PWA Hardening and HighLevel Booking Trigger Implementation Plan

**Repository:** `moawiz-2706/MVP`
**Workspace:** `/home/ubuntu/MVP_20261023`
**Baseline:** `8747919` — `Implement mobile-first PWA workspace`
**Status:** Planning only. Application source code has not been changed by this plan.

## 1. What this implementation will accomplish

This work has two connected goals:

1. Make the standalone Staff PWA reliable and safer on iPhone, Android, and desktop browsers used for testing, without breaking the existing embedded Passport experience inside HighLevel.
2. Send a complete, durable `booking_created` event from Passport to a HighLevel workflow so HighLevel can send customer email/SMS and use booking, payment, and waiver information in workflow conditions and message content.

Passport remains the source of truth for bookings, payment state, waivers, staff assignments, and calendar availability. HighLevel receives a workflow event and handles customer communication. Passport continues to own staff operational reminders unless that ownership is changed later.

## 2. Important HighLevel product decision

HighLevel uses two different features that are often both called a “custom trigger.” They must not be confused.

### Primary implementation: Marketplace Workflow Custom Trigger

The integration will use a real HighLevel Marketplace Workflow Custom Trigger inside the existing GHL app. The trigger will be named **Passport Booking Created**, use the immutable key `passport_booking_created`, expose the booking payload as custom variables, and appear as a native trigger when the app is installed in a location.

HighLevel’s Marketplace documentation defines the required pieces: trigger metadata, a sample JSON payload, filters, custom variables, and a subscription URL. When a location adds the trigger to a workflow, HighLevel sends the workflow instance configuration—including the location ID, workflow ID, event type, and execution `targetUrl`—to the app’s subscription URL. Passport stores that workflow subscription and later calls the provider execution URL when a booking is created. [3]

This is different from an inbound webhook. Passport will not create or store an inbound workflow webhook URL, and the implementation will not use the inbound-webhook trigger.

The trigger must be created/configured in the HighLevel Marketplace developer area for the existing app. The user must publish or otherwise make the app version available to the target location according to HighLevel’s Marketplace rules. Passport can implement the subscription endpoint and event sender, but it cannot bypass HighLevel’s Marketplace app version, installation, or review controls.

The booking event remains provider-neutral internally, while the production adapter is fixed to `marketplace_custom_trigger` for this release. This keeps the Passport event schema stable without adding the unwanted inbound-webhook path.

## 3. Existing system findings that drive the design

The current frontend uses one React route tree. `/app` renders the shared `AppShell`, and the index route renders `DashboardPage`. The same route is used by the embedded HighLevel page and the standalone PWA.

The current PWA login uses HighLevel OAuth, creates a one-time handoff, and returns to `/app#pwa_code=...`. The current implementation then stores a 31-day Passport JWT in both `localStorage` and `sessionStorage`. `POST /pwa-auth/logout` currently returns `204` without revoking anything.

The current embedded installation and standalone PWA login both use `settings.ghl_oauth_redirect_uri`. This can cause HighLevel to return a PWA login to an embedded-install callback or return an embedded installation to a PWA callback.

The current booking flow commits Passport data and then either queues GHL outbox jobs or performs synchronous GHL synchronization depending on `GHL_SYNC_MODE`. It does not yet have a durable booking-created workflow event with a complete payment/waiver payload.

The current repository has an outbox and a worker. This plan uses that existing durable mechanism instead of making the booking request wait for HighLevel workflow delivery.

## 4. Target architecture

```text
Customer/staff creates booking
          |
          v
Passport transaction validates availability and commits booking/payment state
          |
          +--> existing GHL contact/calendar sync job
          |
          +--> ghl_trigger_booking_created outbox job
                         |
                         v
                 Always-on Passport worker
                         |
                         v
           HighLevel Marketplace Custom Trigger
                         |
                         v
              HighLevel workflow execution URL
                         |
                         +--> Create/Update Contact
                         +--> payment-status guard
                         +--> email/SMS confirmation
                         +--> waiver link message
                         +--> optional follow-up/reminder actions
```

HighLevel sends Passport a subscription callback when the custom trigger is added, changed, or removed from a workflow. Passport stores the location/workflow subscription and its provider execution URL. The booking request must succeed even if HighLevel is temporarily unavailable. The outbox job records the failure, retries it, and exposes the failed state to operators. The event must not be sent directly from the Stripe webhook or from the frontend.

## 5. PWA hardening scope

### 5.1 Separate HighLevel OAuth redirect URLs

Add two runtime settings:

```text
GHL_INSTALL_OAUTH_REDIRECT_URI=https://api.example.com/api/v1/integrations/marketplace/oauth/callback
PWA_OAUTH_REDIRECT_URI=https://api.example.com/api/v1/integrations/marketplace/oauth/callback
```

The URL path may be shared if HighLevel requires one callback route, but the OAuth request must carry the correct configured redirect URI for the flow. If HighLevel app configuration allows separate callback URLs, use separate exact URLs such as:

```text
https://api.example.com/api/v1/integrations/marketplace/oauth/callback
https://api.example.com/api/v1/pwa-auth/oauth/callback
```

The safer design is to use a separate PWA callback route. The callback still validates the state cookie, consumes the state once, exchanges the code once, and redirects to the Passport frontend with a short-lived one-time handoff code. No Passport JWT is placed in the URL.

The GHL installation row must remember the redirect URI or flow used when its rotating refresh token was issued. Token refresh must send the same redirect URI required by the original HighLevel authorization flow. Existing installations should remain compatible through a migration backfill to the current installation redirect URI.

Production validation must require both redirect settings. Development can fall back to the existing value for backward compatibility, but the fallback must produce a warning.

### 5.2 Replace browser-stored long-lived JWTs

Replace the current localStorage/sessionStorage JWT approach with:

- A short-lived Passport access token held only in JavaScript memory.
- A rotating opaque refresh token stored only in a `Secure`, `HttpOnly`, `SameSite=Lax` cookie.
- A database row storing only a SHA-256 digest of the refresh token.
- Refresh-token rotation on every successful refresh.
- Expiry and revocation checks on every refresh.
- Access-token refresh before expiry and after a 401 response.

Proposed database entity: `pwa_sessions`.

Required fields:

```text
id uuid primary key
operator_id uuid not null
app_user_id uuid not null
session_token_digest text unique not null
created_at timestamptz not null
touched_at timestamptz not null
expires_at timestamptz not null
revoked_at timestamptz null
last_user_agent_hash text null
last_ip_hash text null
```

The raw refresh token is never stored. IP and user-agent values should be hashed or omitted; they are diagnostics, not authentication factors.

The existing `PWAAuthHandoff` remains one-time and short-lived. It is only used to exchange the HighLevel callback for the first Passport session.

### 5.3 PWA authentication API contract

#### `GET /api/v1/pwa-auth/highlevel/start`

Purpose: start standalone PWA HighLevel OAuth.

Query parameters:

```json
{
  "location_id": "optional-location-id"
}
```

Response:

```http
302 Found
Location: https://marketplace.gohighlevel.com/oauth/chooselocation?...&redirect_uri=<PWA_OAUTH_REDIRECT_URI>&state=<opaque-state>
Set-Cookie: pwa_oauth_state=<opaque-state>; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/pwa-auth
```

The state is stored as a digest and is bound to `flow = pwa_login`, the expected location when supplied, and a short expiry.

#### `GET /api/v1/pwa-auth/oauth/callback`

Purpose: receive the PWA OAuth callback.

Success behavior:

1. Validate the `pwa_oauth_state` cookie and query `state` using constant-time comparison.
2. Consume the state exactly once.
3. Exchange the HighLevel authorization code once.
4. Validate location, user, scopes, and membership.
5. Create or update the Passport installation and local user membership.
6. Create a one-time `PWAAuthHandoff`.
7. Redirect to the configured Passport frontend:

```text
https://passport.example.com/app#pwa_code=<one-time-code>
```

Failure behavior:

```text
https://passport.example.com/app?pwa_auth_error=<safe-error-code>
```

The error code must not contain access tokens, refresh tokens, raw provider payloads, or database details.

#### `POST /api/v1/pwa-auth/exchange`

Request:

```json
{
  "code": "one-time-handoff-code"
}
```

Success response:

```json
{
  "access_token": "short-lived-passport-jwt",
  "expires_in": 900,
  "token_type": "Bearer"
}
```

Response headers set the refresh cookie:

```http
Set-Cookie: passport_pwa_refresh=<opaque-refresh-token>; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/pwa-auth; Max-Age=2592000
```

The one-time handoff is consumed under row lock before the response is committed.

#### `POST /api/v1/pwa-auth/refresh`

Request body: empty JSON object.

Authentication: refresh cookie only.

Success response:

```json
{
  "access_token": "new-short-lived-passport-jwt",
  "expires_in": 900,
  "token_type": "Bearer"
}
```

The old refresh-token digest is revoked/replaced atomically. Reuse of an already-rotated refresh token revokes the entire device session and returns `401`.

#### `POST /api/v1/pwa-auth/logout`

Authentication: refresh cookie and, when present, current access token.

Success response:

```http
204 No Content
Set-Cookie: passport_pwa_refresh=; Max-Age=0; HttpOnly; Secure; SameSite=Lax; Path=/api/v1/pwa-auth
```

The current `pwa_sessions` row is marked revoked. Logout must be safe to repeat.

#### `GET /api/v1/pwa-auth/sessions`

Admin-only optional endpoint for later release. It lists active device sessions without token material and allows an administrator to revoke one device. This is not required for the first code slice if the session table and logout are implemented correctly.

### 5.4 Frontend PWA session behavior

Change `GHLSessionProvider` so it no longer writes access tokens to localStorage or sessionStorage.

The provider will:

- Detect embedded mode with `window.parent !== window`.
- Detect standalone mode with `display-mode: standalone`, iOS standalone mode, or an explicit PWA callback/pending-login marker.
- Use `credentials: "include"` for PWA exchange, refresh, and logout requests.
- Hold the access token in memory and pass it through the existing API client.
- Call `/pwa-auth/refresh` on app startup when the refresh cookie is present.
- Return to the PWA login screen only when refresh returns `401`.
- Clear the URL hash and query after consuming the handoff or safe error.
- Offer a visible “Sign out” action in the sidebar/mobile menu.

The existing embedded HighLevel session path remains unchanged: the embedded page requests the encrypted GHL parent-window context and calls `/auth/ghl-session`.

### 5.5 Browser versus PWA route policy

Do not use user-agent detection as authorization. Use explicit mode detection only for presentation.

Target behavior:

- Embedded HighLevel: keep the existing Passport pages and sidebar. Do not show a second native HighLevel page.
- Standalone installed PWA: show the Staff Operations PWA with the full Passport sidebar and mobile cards.
- Standalone browser at `/app`: allow it for login/testing unless `VITE_PWA_REQUIRE_STANDALONE=true` is explicitly enabled.
- When `VITE_PWA_REQUIRE_STANDALONE=true` and the app is opened in a normal browser on a phone, show an install/open instruction instead of silently showing the workspace.
- Preserve public booking, waiver, staff-booking, Stripe return, and integration-result routes.

The root redirect should remain compatible, but an optional environment setting may redirect normal browser `/` to the public booking entry or a clear “Open Staff PWA” page instead of forcing the PWA Home dashboard. This must be decided before implementation because changing `/` can affect existing embedded bookmarks.

### 5.6 Service worker and install fixes

Update the service worker so it only replaces the cached shell when the network response satisfies all of these conditions:

- `response.ok === true`
- response content type contains `text/html`
- request is a navigation request

Never cache `/api/`, OAuth callback responses, handoff codes, or authenticated response bodies.

Keep the manifest start URL as `/app`, keep the scope `/`, and retain separate Passport-origin install instructions. The PWA install prompt must never suggest installing from a HighLevel host.

Add an automated build-derived cache version, or require a single release version constant that is updated by the build script. The application must not serve an old cached login shell after deployment.

## 6. Booking-created HighLevel trigger design

### 6.1 Event ownership and timing

The event is created only after the Passport booking transaction commits. It is never sent before the local booking/payment state is durable.

The event should be queued for:

- Public booking links.
- Authenticated operator/staff bookings.
- Private staff booking links.
- Free bookings.
- Card-payment holds.
- Invoice-payment holds.

The event contains the current state at send time. This is important because a card booking may be `pending_payment` at creation and `confirmed` later.

Recommended event types:

```text
booking_created
booking_confirmed
booking_cancelled
booking_rescheduled
waiver_signed
payment_updated
```

The user request requires `booking_created` first. The event adapter should be designed for the other events so confirmation messages do not accidentally send before payment succeeds.

### 6.2 Marketplace Custom Trigger subscription storage

The existing GHL app’s Marketplace Custom Trigger will notify Passport whenever a location adds, updates, or removes `passport_booking_created` from a workflow. Passport must persist each active workflow subscription because a location may use the trigger in more than one workflow.

Proposed table: `ghl_marketplace_trigger_subscriptions`.

Required fields:

```text
id uuid primary key
operator_id uuid not null
ghl_location_id text not null
ghl_company_id text null
ghl_workflow_id text not null
ghl_trigger_instance_id text not null
trigger_key text not null default 'passport_booking_created'
event_type text not null
event_action text not null
target_url_encrypted text not null
filters_json jsonb not null default '{}'::jsonb
enabled boolean not null default true
last_sent_at timestamptz null
last_success_at timestamptz null
last_failure_at timestamptz null
last_http_status integer null
last_error text null
created_at timestamptz not null
updated_at timestamptz not null
```

Subscription callback fields:

- `triggerData.id` → `ghl_trigger_instance_id`.
- `triggerData.key` → `trigger_key`.
- `triggerData.eventType` → `event_action`.
- `triggerData.targetUrl` → encrypted `target_url_encrypted`.
- `triggerData.filters` → `filters_json`.
- `extras.locationId` → `ghl_location_id`.
- `extras.workflowId` → `ghl_workflow_id`.
- `extras.companyId` → `ghl_company_id`.

Constraints:

- Unique `(ghl_location_id, ghl_workflow_id, ghl_trigger_instance_id)`.
- Only the signed/validated Marketplace subscription callback may create or change a target URL.
- The target URL is encrypted at rest using the existing token cipher.
- The subscription endpoint validates that the callback belongs to an installed Passport location before saving it.
- API responses never return the raw target URL; they return subscription IDs, workflow IDs, trigger state, and delivery status.
- A `DELETED` callback disables the subscription but retains delivery history.
- A later `UPDATED` callback replaces the encrypted target URL and filters atomically.
- The provider target URL must be HTTPS and must match the HighLevel workflow-trigger execution host expected by the app.

### 6.3 Passport Marketplace Custom Trigger API

#### `POST /api/v1/integrations/marketplace/workflow-trigger/subscription`

This is the server-to-server callback configured in the existing GHL Marketplace app. It must be public to HighLevel but protected by the app’s verification mechanism, such as the existing shared-secret/signature validation supported by the Marketplace app configuration. The implementation must reject unknown locations and invalid callback event types.

Request:

```json
{
  "triggerData": {
    "id": "trigger-instance-id",
    "key": "passport_booking_created",
    "filters": [],
    "eventType": "CREATED",
    "targetUrl": "https://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/..."
  },
  "meta": {
    "key": "passport_booking_created",
    "version": "1.0"
  },
  "extras": {
    "locationId": "ghl-location-id",
    "workflowId": "workflow-id",
    "companyId": "company-id"
  }
}
```

Response:

```json
{
  "success": true
}
```

Callback behavior:

- `CREATED`: insert or upsert the active workflow subscription.
- `UPDATED`: replace filters and target URL atomically.
- `DELETED`: mark the subscription disabled while preserving delivery history.
- Any callback for a location that is not installed in Passport: return a safe `403` and do not store the target URL.
- Any unknown trigger key: return a safe `400`.

#### `GET /api/v1/ghl/workflow-triggers`

Protected by the existing application session and configuration-management permission. This endpoint is for operator diagnostics; the subscription itself is managed by HighLevel.

Response:

```json
{
  "items": [
    {
      "subscription_id": "uuid",
      "event_type": "booking_created",
      "trigger_type": "marketplace_custom_trigger",
      "trigger_key": "passport_booking_created",
      "ghl_location_id": "ghl-location-id",
      "ghl_workflow_id": "workflow-id",
      "enabled": true,
      "last_success_at": "2026-10-23T12:00:00Z",
      "last_failure_at": null,
      "last_http_status": 200,
      "last_error": null
    }
  ]
}
```

#### `POST /api/v1/ghl/workflow-triggers/booking-created/test`

Request:

```json
{
  "booking_order_id": "uuid"
}
```

Behavior:

- Does not create a customer booking.
- Builds the current event payload from the selected existing order.
- Sends it to every active Marketplace Custom Trigger subscription for the operator/location.
- Records one result per workflow subscription in durable attempt records.

Success response:

```json
{
  "status": "delivered",
  "http_status": 200,
  "event_id": "booking_order_uuid_created_v1_test"
}
```

Failure response:

```json
{
  "status": "failed",
  "http_status": 422,
  "error_code": "ghl_workflow_rejected",
  "message": "HighLevel rejected the workflow payload"
}
```

The response must not expose the encrypted HighLevel execution URL, provider secret, access token, or raw waiver token.

### 6.4 Outbox job contract

Add a job type:

```text
ghl_workflow_trigger_booking_created
```

Idempotency key:

```text
booking_order:{order_id}:workflow:booking_created:v1
```

Payload:

```json
{
  "booking_order_id": "uuid",
  "event_type": "booking_created",
  "schema_version": "1",
  "source": "passport",
  "created_at": "2026-10-23T12:00:00Z"
}
```

The payload intentionally stores IDs rather than a duplicated booking snapshot. The worker reads the canonical current data when sending. A separate event snapshot can be added later if audit requirements require the exact original state.

Retry policy:

- Retry transport failures, timeout, 408, 409, 425, 429, and 5xx responses.
- Do not automatically retry a malformed URL, 400, 401, 403, 404, or 422 response without operator correction.
- Use the existing outbox lease and attempt counters.
- Preserve the failed job and show a notification with a resync action.
- A successful later delivery marks the trigger attempt as resolved.

### 6.5 Booking event payload

Passport sends a stable JSON object with snake_case keys matching the Marketplace trigger sample payload and custom-variable references. HighLevel uses the configured sample payload to expose trigger values inside workflow actions, filters, and message templates. [3]

Example payload:

```json
{
  "event_type": "booking_created",
  "schema_version": "1",
  "event_id": "booking_order_8d7..._created_v1",
  "idempotency_key": "booking_order_8d7...:workflow:booking_created:v1",
  "occurred_at": "2026-10-23T12:00:00Z",
  "source": "passport",
  "operator_id": "internal-uuid",
  "operator_name": "Example Watersports",
  "operator_slug": "example-watersports",
  "location_id": "ghl-location-id",
  "booking_order_id": "internal-uuid",
  "public_reference": "PS-AB12CD34",
  "booking_status": "pending_payment",
  "payment_status": "requires_payment",
  "payment_method": "card",
  "confirmed": false,
  "currency": "USD",
  "subtotal_minor": 10000,
  "fees_and_taxes_minor": 1300,
  "customer_total_minor": 11300,
  "subtotal_amount": "100.00",
  "fees_and_taxes_amount": "13.00",
  "customer_total_amount": "113.00",
  "customer_first_name": "Alex",
  "customer_last_name": "Smith",
  "customer_full_name": "Alex Smith",
  "customer_email": "alex@example.com",
  "customer_phone": "+15555550123",
  "marketing_opt_in": false,
  "waiver_required": true,
  "waiver_status": "unsigned",
  "waiver_url": "https://passport.example.com/waiver/one-time-token",
  "items": [
    {
      "booking_id": "internal-uuid",
      "calendar_id": "internal-uuid",
      "calendar_name": "Sunset Boat Tour",
      "start_at": "2026-10-25T18:00:00Z",
      "end_at": "2026-10-25T20:00:00Z",
      "time_zone": "America/New_York",
      "units": 2,
      "status": "pending_payment",
      "departure_location_name": "Marina A",
      "departure_location_address": "1 Harbor Road",
      "assigned_staff_names": ["Taylor Jones"],
      "custom_fields": {
        "boat_type": "Center Console"
      }
    }
  ]
}
```

Rules:

- Never send waiver signatures, dates of birth, home addresses, emergency contacts, or full waiver text.
- The one-time waiver URL is sensitive. It may be sent to the workflow only if the operator explicitly enables it. The URL must not be logged in plaintext.
- Internal UUIDs are correlation values and must not be used as customer-facing links.
- Amounts are included both in minor units and formatted currency strings. HighLevel workflows should use the formatted fields in messages and minor fields in numeric conditions.
- Arrays are allowed, but workflow field mapping must be tested after the sample payload is saved.
- `items` may contain multiple bookings. Customer confirmation logic should use the first/summary values only if the workflow UI cannot iterate the array.

### 6.6 Payment and message guard

A workflow triggered by `booking_created` must not immediately send a paid confirmation when:

```text
payment_status in {"requires_payment", "processing", "provider_unknown"}
confirmed == false
```

Recommended workflow branches:

1. If `confirmed == true` or `payment_method == "none"`, send the confirmation email/SMS.
2. If `payment_status == "requires_payment"` and an invoice URL exists, send a payment-required message or wait for the separate `payment_updated`/`booking_confirmed` event.
3. If `payment_status == "processing"`, do not send a confirmation; wait for the confirmed event.
4. If `waiver_status == "unsigned"` and `waiver_url` is present, include the waiver link in the confirmed message.

This prevents a card or invoice hold from being communicated as a completed booking.

## 7. HighLevel Marketplace Custom Trigger setup steps

### Step 1 — Open the existing Marketplace app

1. Sign in to the HighLevel Marketplace developer portal.
2. Open the existing Passport/GHL app that is already used to install Passport.
3. Open **Modules → Workflow**.
4. Choose **Create Trigger**.

This trigger is created at the app/module level, not separately as an inbound webhook in each location. After the app version is available and installed in a location, the trigger becomes selectable in that location’s Workflow Builder. [3]

### Step 2 — Define the trigger

Use:

```text
Name: Passport Booking Created
Key: passport_booking_created
Short description: Starts when Passport creates or updates a booking event.
```

The key is immutable. Do not change it after the first version is published. The event payload uses `event_type` so the same trigger module can support the first `booking_created` event and later booking/payment/waiver events.

### Step 3 — Configure sample data, filters, and variables

Paste the sample JSON from Section 8 into the Marketplace trigger configuration. Add custom variables for customer name/email/phone, booking reference, calendar name, start/end time, amount, booking status, payment status, waiver status, waiver URL, staff names, and item data.

Add workflow filters for:

- `event_type` — `booking_created`, `booking_confirmed`, `payment_updated`, `waiver_signed`, and later lifecycle events.
- `payment_status` — `succeeded`, `requires_payment`, `processing`, `failed`, or `provider_unknown`.
- `booking_status` — `pending_payment`, `confirmed`, `cancelled`, `rescheduled`, or the exact values used by Passport.
- `confirmed` — boolean.
- `calendar_name` — dynamic filter if the account needs calendar-specific messages.

The trigger documentation supports sample JSON, select/dynamic filters, and custom variables. [3]

### Step 4 — Configure the subscription URL

Set the Marketplace module subscription URL to:

```text
https://<passport-api-domain>/api/v1/integrations/marketplace/workflow-trigger/subscription
```

Configure the verification header or shared secret required by the existing Marketplace app integration. Passport will validate the callback, confirm the location is installed, and save the workflow’s HighLevel execution `targetUrl` encrypted in the database.

### Step 5 — Create a new app version and make it available

Save the trigger, create a version, and follow the app’s draft/review/publish process. A draft version may be usable for the app owner’s test installation, but it is not equivalent to a generally available published version. Confirm the version is installed in the demo location before testing.

### Step 6 — Add the trigger to a location workflow

In the target HighLevel sub-account:

1. Open **Automation → Workflows**.
2. Create a workflow from scratch.
3. Select **Passport Booking Created** under Custom/Marketplace triggers.
4. Add a filter such as `event_type = booking_created`.
5. Save the workflow while it is in draft mode.

HighLevel will send the trigger subscription callback to Passport. Passport must return `200` and persist the `locationId`, `workflowId`, trigger instance ID, filters, and execution `targetUrl`.

### Step 7 — Create/update the customer Contact

Because a Marketplace trigger can be contactless, the workflow must explicitly establish the customer Contact before SMS/email actions:

- Use **Find Contact** by `customer_email` or `customer_phone` when a contact may already exist.
- If no contact is found, use **Create/Update Contact** with `customer_first_name`, `customer_last_name`, `customer_email`, and `customer_phone`.
- Preserve `ghl_contact_id` in the payload when Passport already has the canonical contact ID.
- Add the optional `passport-customer` tag.

HighLevel documents that Marketplace triggers can run contactless, while Contact-dependent actions require retrieving or creating a Contact. [3]

### Step 8 — Add the payment guard and customer messages

Add an **If/Else** action:

- Confirmed branch: `confirmed = true` or `payment_method = none`.
- Payment-required branch: `payment_status = requires_payment`.
- Processing/unknown branch: no confirmation message; wait for `booking_confirmed` or `payment_updated`.

In the confirmed branch, add **Send Email** and **Send SMS** using the Marketplace trigger custom-variable picker for the customer name, public reference, service, date/time, location, total, and waiver URL. Send the waiver link only when `waiver_status = unsigned` and `waiver_url` is not empty.

Keep staff operational reminders in Passport. HighLevel should handle customer-facing confirmation and customer follow-up only in this release.

### Step 9 — Test before activation

Use a test booking for each case:

- Free booking.
- Card booking before payment confirmation.
- Card booking after successful payment.
- Invoice booking before invoice payment.
- Invoice booking after payment.
- Unsigned waiver.
- Already signed waiver.
- Booking with email only.
- Booking with phone only.
- Staff-created booking.
- Public booking.

Review HighLevel workflow execution logs, Passport subscription records, and Passport trigger-attempt records. Activate the workflow only after the payment guard prevents premature confirmation messages.

## 8. Marketplace Custom Trigger implementation contract

Marketplace trigger definition:

```text
Name: Passport Booking Created
Key: passport_booking_created
Description: Starts when Passport creates a booking in the connected location.

Sample payload:
  event_type
  event_id
  public_reference
  booking_status
  payment_status
  confirmed
  customer_email
  customer_phone
  customer_first_name
  customer_last_name
  calendar_name
  start_at
  end_at
  customer_total_amount
  waiver_status
  waiver_url
  items
```

Custom variables should map the fields above. Filters should include:

- `payment_status` — dynamic/select.
- `booking_status` — select.
- `confirmed` — select/boolean.
- `calendar_name` — dynamic.
- `event_type` — select.

Subscription URL contract:

```http
POST /api/v1/integrations/marketplace/workflow-trigger/subscription
Content-Type: application/json
```

Expected body from HighLevel:

```json
{
  "triggerData": {
    "id": "trigger-instance-id",
    "key": "passport_booking_created",
    "filters": [],
    "eventType": "CREATED",
    "targetUrl": "https://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/..."
  },
  "meta": {
    "key": "passport_booking_created",
    "version": "1.0"
  },
  "extras": {
    "locationId": "ghl-location-id",
    "workflowId": "workflow-id",
    "companyId": "company-id"
  }
}
```

Passport should validate the location, store the workflow instance and target URL encrypted, and respond:

```json
{
  "success": true
}
```

The event sender would then POST the provider-required execution payload to the stored target URL. The exact execution body must be taken from the current Marketplace trigger execution contract or a real HighLevel trigger test; it must not be guessed from the subscription body. The Marketplace trigger requires developer-portal creation, versioning, and possibly review before it is available to installed locations. [3]

## 9. Database migrations

The first implementation should add forward-only migrations in this order:

### Migration 039 — PWA device sessions

Creates `pwa_sessions`, indexes active digests and expiry, and records a schema marker.

### Migration 040 — OAuth redirect-flow metadata

Adds `oauth_flow` or `oauth_redirect_uri` to `ghl_installations`, backfills existing rows to the current embedded redirect, and records a schema marker.

### Migration 041 — GHL Marketplace trigger subscriptions

Creates `ghl_marketplace_trigger_subscriptions` with encrypted execution target URL, HighLevel location/workflow/trigger identifiers, filter JSON, status fields, ownership constraints, and indexes. Adds the `ghl_workflow_trigger_booking_created` outbox job type.

### Migration 042 — workflow trigger delivery attempts

This may be merged into 041 if the existing `OutboxJob` and GHL sync attempt tables provide sufficient diagnostics. If not, create `ghl_workflow_trigger_attempts` with event ID, HTTP status, error code, attempt number, request hash, and timestamps.

Readiness must advance only after each migration is applied. The combined SQL deployment file must include the migrations in order. Existing migrations must not be edited or renumbered.

## 10. Configuration changes

Add to backend settings:

```text
GHL_INSTALL_OAUTH_REDIRECT_URI
PWA_OAUTH_REDIRECT_URI
PWA_REFRESH_COOKIE_NAME=passport_pwa_refresh
PWA_ACCESS_TOKEN_MINUTES=15
PWA_REFRESH_TOKEN_DAYS=31
PWA_REQUIRE_STANDALONE=false
GHL_WORKFLOW_TRIGGERS_ENABLED=false
GHL_BOOKING_CREATED_TRIGGER_ENABLED=false
GHL_WORKFLOW_TRIGGER_TIMEOUT_SECONDS=10
```

Keep backward-compatible aliases during rollout:

- If `GHL_INSTALL_OAUTH_REDIRECT_URI` is empty, use the current `GHL_OAUTH_REDIRECT_URI` in non-production environments.
- Production validation must require the new explicit variables.
- Do not place workflow webhook URLs in frontend environment variables.
- Do not place GHL client secrets, refresh tokens, or webhook URLs in client-side JavaScript.

## 11. Implementation phases

### Phase 1 — PWA authentication and logout

Implement the session migration, secure refresh cookie, refresh rotation, real logout, separate OAuth redirect settings, callback handling, and frontend in-memory access-token behavior. Preserve the embedded GHL session flow.

Completion evidence: PWA login works on Android Chrome and iPhone Safari, refresh survives closing/reopening the installed PWA, logout requires login again, and revoking the database session invalidates the device.

### Phase 2 — PWA routing, install, and cache hardening

Implement explicit embedded/standalone mode detection, optional standalone-only UX, safer service-worker caching, build cache versioning, and the final install prompt. Preserve public routes and embedded Passport navigation.

Completion evidence: embedded HighLevel opens Passport pages, installed PWA opens Passport pages rather than native HighLevel pages, normal browser testing is understandable, and a new deployment replaces the old shell.

### Phase 3 — Marketplace Custom Trigger subscription and delivery

Implement the Marketplace subscription callback, `ghl_marketplace_trigger_subscriptions` migration, trigger status API, test-send endpoint, booking-created outbox job, payload builder, retry behavior, failure notification, and manual resync.

Completion evidence: a test booking produces one HighLevel workflow execution, a repeated worker run does not duplicate it, a 5xx/timeout retries, a 4xx remains visible for operator correction, and a manual resync succeeds after the URL is fixed.

### Phase 4 — Message ownership cutover

After the HighLevel workflow has been tested, disable duplicate Passport customer confirmation jobs for the selected event types. Keep Passport staff assignment and staff reminder jobs. Add a feature flag and a migration-safe rollback switch during the cutover.

Completion evidence: customer receives exactly one intended email/SMS, staff receives the Passport-owned operational reminder, and payment-pending bookings do not receive a false confirmation.

### Phase 5 — Marketplace app version and rollout

Create the trigger module in the existing HighLevel app, configure sample data/filters/custom variables/subscription URL, complete the draft/review/publish requirements applicable to the app, install the version in the target location, and verify that every workflow subscription is delivered to Passport.

## 12. Required decisions before implementation

The following decisions affect database and API design:

1. Should normal browser access to `/app` remain allowed for desktop testing, or should `PWA_REQUIRE_STANDALONE=true` block it outside an installed PWA?
2. Should the first customer workflow receive `booking_created` for payment-pending bookings, or should Passport send only a confirmed booking event for customer confirmation? The safe default is to send both events but allow messages only on `confirmed == true`.
3. Is the existing HighLevel app configured with the Workflow/Custom Trigger module and a valid subscription URL? The implementation assumes yes and will not add an inbound-webhook fallback.
4. Should the Marketplace event include the one-time waiver URL? The safe default is yes only when the operator enables it, with URL redaction in logs.
5. Which user roles may activate the Marketplace-triggered customer workflow? Recommended: agency owner/admin only.
6. Where will the always-on worker run? Vercel Hobby is not suitable for this responsibility.

## 13. Definition of done

The implementation is complete only when:

- The PWA uses separate embedded and standalone OAuth redirect configuration.
- Access tokens are not persisted in localStorage/sessionStorage.
- Refresh tokens are HttpOnly, rotated, hashed in the database, expirable, and revocable.
- Logout really revokes the current device session.
- The embedded HighLevel Passport route and standalone PWA route both open the intended Passport UI.
- The service worker never caches API/authenticated responses and updates the shell safely.
- Booking creation queues a single idempotent HighLevel workflow event after commit.
- The event contains customer, booking, payment, waiver, time, location, and correlation data without sensitive waiver contents.
- The worker retries transient delivery failures and exposes permanent failures.
- HighLevel workflow setup can use the received fields as custom values in email/SMS and If/Else actions.
- Customer messages are not sent twice by Passport and HighLevel.
- Staff reminders remain Passport-owned.
- The full PostgreSQL-backed test suite and frontend build pass.
- A staging smoke test passes for public booking, staff booking, free booking, card booking, invoice booking, waiver link, PWA login, PWA refresh, logout, and HighLevel workflow delivery.

## References

[1]: https://help.gohighlevel.com/support/solutions/articles/48001237383-how-to-use-the-inbound-webhook-workflow-premium-trigger "How to use the Inbound Webhook Workflow Premium Trigger"

[2]: https://help.gohighlevel.com/support/solutions/articles/155000003147-workflow-trigger-inbound-webhook "Workflow Trigger - Inbound Webhook"

[3]: https://marketplace.gohighlevel.com/docs/marketplace-modules/CustomTriggers/ "Creating a Marketplace Workflow Trigger"

[4]: https://marketplace.gohighlevel.com/docs/Authorization/OAuth2.0/ "HighLevel OAuth 2.0"

[5]: https://docs.stripe.com/webhooks "Stripe webhooks"
