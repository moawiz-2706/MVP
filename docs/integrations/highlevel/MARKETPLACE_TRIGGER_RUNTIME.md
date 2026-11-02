# Marketplace Custom Trigger runtime: `passport_booking_created`

Passport starts the **published v1.0 Marketplace Workflow Custom Trigger**
`passport_booking_created` (name "Passport Booking Created"). It does not create
a second trigger and does not use the Inbound Webhook trigger. Passport stays
the source of truth; the HighLevel workflow owns customer email/SMS.

Code: `backend/app/services/ghl_workflow_trigger_service.py`,
`backend/app/api/v1/ghl_workflow_trigger.py`. Migration:
`supabase/migrations/045_marketplace_workflow_trigger.sql`.

## What HighLevel documents, and what it does not

Source: [Marketplace Workflow Triggers](https://help.gohighlevel.com/support/solutions/articles/155000001024-marketplace-workflow-triggers)
and [Creating a Marketplace Workflow Trigger](https://marketplace.gohighlevel.com/docs/marketplace-modules/CustomTriggers)
(read 2026-11-03).

| Topic | Documented? | Passport's choice |
|---|---|---|
| Subscription callback body (`triggerData.id/key/filters/eventType/targetUrl`, `meta.key/version`, `extras.locationId/workflowId/companyId`) for CREATED / UPDATED / DELETED | **Yes** | Implemented exactly. |
| Subscription callback authentication | **No signature.** The developer can add "required header data" to the Subscription URL. | Passport requires the header `X-Passport-Trigger-Secret` = `GHL_WORKFLOW_TRIGGER_SECRET` (constant-time compare). With no secret configured, every callback gets 503. |
| Execution request to `targetUrl` (method, headers, body) | **No** | `POST` the payload JSON as-is, with `Authorization: Bearer <location access token>`, `Version: 2021-07-28`, `Content-Type: application/json`. This is the convention every `services.leadconnectorhq.com` call uses. **Confirm it on a test location before relying on it.** |
| Who evaluates workflow filters | **No** | Passport also applies `==` / `!=` filters on its own fields before sending (harmless if HighLevel filters too). Other operators are left to HighLevel. |
| Retries / rate limits | **No** | Passport retries transport errors, 408, 409, 425, 429 and 5xx. |

## Subscription URL

`POST /api/v1/integrations/marketplace/workflow-trigger/subscription`

Vercel rewrites `/api/*` to the FastAPI service, the same route as the
existing `/api/v1/integrations/marketplace/webhook` (checked 2026-11-03: that
route answers with FastAPI's JSON 405 to a GET; the trigger route answered
FastAPI's JSON 404 because it was not deployed yet).

Checks, in order:

1. The secret header matches (otherwise 401, or 503 if unset).
2. The body is JSON, the key is `passport_booking_created`, `eventType` is
   CREATED, UPDATED or DELETED, and `triggerData.id`, `extras.locationId` and
   `extras.workflowId` are present (otherwise 400).
3. For CREATED and UPDATED, `targetUrl` must be
   `https://services.leadconnectorhq.com/workflows-marketplace/triggers/execute/…` (otherwise 400).
4. The location has an active Passport installation (otherwise 403, and nothing is stored).

Storage, in `ghl_workflow_trigger_subscriptions`: one row per (location,
workflow, trigger instance), so a location can run the trigger in several
workflows. `targetUrl` is Fernet-encrypted with `GHL_TOKEN_ENCRYPTION_KEY`. It
is never logged, never returned by an API, and never shown in an error. The
SHA-256 of the last callback body makes duplicate deliveries a no-op. DELETED
is final for that trigger instance: a replayed CREATED or UPDATED is ignored.

## Events

Producers write the event row and its outbox job **inside the booking's own
transaction**, so the booking and its event commit together or not at all.
Delivery runs later in the outbox, so a HighLevel failure can never roll back
a booking or a Stripe payment.

| `event_type` | Produced by | Idempotency discriminator |
|---|---|---|
| `booking_created` | `OrderService.create`: public link `POST /public/{slug}/orders`, staff link `POST /staff-booking/{token}/orders`, Passport/PWA `POST /bookings` | `v1` (once per order) |
| `payment_confirmed` | Verified Stripe `payment_intent.succeeded` or `invoice.paid` that confirms the order | `v1` (once per order; Stripe redelivery is a no-op) |
| `booking_cancelled` | `BookingLifecycleService.cancel` (operator cancel, weather closure), after the refund/reversal is recorded | booking id |
| `booking_updated` | Staff edit (`BookingAdminService.update`), reschedule, party-size adjustment (immediate, or after the verified extra charge) | booking id + `updated_at` |

`idempotency_key` = `booking_order:{order_id}:workflow:{event_type}:{discriminator}`,
`event_id` = `{order_id}:{event_type}:{discriminator}`. Both are deterministic.

**Not emitted (no event type yet):** expired card holds, voided or
uncollectible invoices, check-in / no-show / completed, waiver signed, staff
assignment changes, and Stripe-side refunds (`charge.refunded`). Exposing more
event types to workflow authors needs a new trigger version (see below).

### Status snapshot

When the event is created, it snapshots `booking_status`, `payment_status`,
`payment_method`, `confirmed`, the amounts, the customer, the primary
booking's calendar and times, and the items. So `booking_created` for a card
booking always says `pending_payment` / `requires_payment` / `confirmed:
false`, even if it is delivered after the payment. The paid state arrives as
its own `payment_confirmed` event. The contact id, waiver and staff are read
when the event is sent.

- `confirmed` is true only when the order is `confirmed` **and** the payment is `succeeded`. Free bookings are confirmed at creation; their `payment_method` is `none`.
- `booking_status` is the order status (`pending_payment`, `confirmed`, `cancelled`, `refunded`…). `payment_status` is the Passport payment status (`requires_payment`, `processing`, `succeeded`, `failed`…).

## Payload

The top-level keys and JSON types are exactly the published v1.0 sample:
strings, `confirmed` and `waiver_required` booleans, `items` an array.

- `location_id`: the operator's HighLevel location id. `ghl_contact_id`: the real contact. When the order has none yet, the existing contact sync runs before the first send. The trigger never creates contacts or appointments itself.
- `start_at`, `end_at`, `occurred_at`: ISO-8601 UTC with `Z`. `timezone`: the operator's IANA zone.
- Amounts: decimal strings with two places (`"113.00"`), from the stored minor units.
- **One event per order.** `calendar_id`, `calendar_name`, `start_at`, `end_at` and `location_name` describe the *primary* booking: the one that changed, else the earliest active one. `items` lists every line of every booking in the order: `name` (customer type), `quantity`, `amount` = the line subtotal **before** booking fee and tax (the `items` amounts add up to `subtotal_amount`). Each item also carries `calendar_id`, `calendar_name`, `start_at`, `end_at` and `booking_status`, so a multi-calendar checkout is never flattened.
- `waiver_required`: the operator has waiver text. `waiver_status`:

  | Value | Meaning | `waiver_url` |
  |---|---|---|
  | `signed` | Signed | Link |
  | `unsigned` | Link issued, not yet signed | Link |
  | `not_available` | Booking not confirmed, or cancelled | `""` |
  | `not_required` | Operator has no waiver | `""` |

- `staff_names`: staff assigned to the primary booking's calendar and start time, comma-separated, `""` if none.
- `customer_phone`: `""` when not given. Missing optional values are `""`, never `null`.

## Delivery

Outbox job `ghl_workflow_trigger`, one per event. Each run:

1. With no active subscription for the location, the event becomes `no_subscriber`. That is not counted as delivered.
2. The contact is ensured, then the payload is built.
3. For each active workflow, a delivery row is written (`ghl_workflow_trigger_deliveries`, unique per event and workflow). Delivered, filtered or permanently failed workflows are skipped, so **a retry never re-sends to a workflow that already received the event**.
4. Each delivery is committed as it completes. Transient failures (transport error, 408, 409, 425, 429, 5xx) mark it `retrying` and the job fails, so the outbox retries it with its existing backoff (2^n minutes, capped at 24 h, 12 attempts, then `dead`). Permanent failures (400, 401 after a token refresh, 403, 404, 422) mark it `failed`.
5. Event status: `delivered`, `partially_delivered`, `failed`, `pending` (retrying), or `no_subscriber` (also used when every workflow's filters excluded the event).

Errors are stored without URLs and capped at 500 characters.

### Timing

Delivery happens when the outbox runs. **It is not real-time today:** per
`docs/operations/OPERATIONS_RUNBOOK.md`, the only runner in production is the
daily Vercel cron at 11:00 UTC. Staff edits, cancellations and manual retries
also process the outbox inline, so those are sent within the request. To send
new-booking and payment events within a minute, schedule
`supabase/manual/schedule_outbox_pg_cron.sql` (or run `backend/worker.py`).

## Status and retry

- `GET /api/v1/orders/{order_id}/workflow-trigger` (`view_bookings`): events and per-workflow deliveries for the order. Tenant-scoped; never includes a target URL.
- `POST /api/v1/orders/{order_id}/workflow-trigger/retry` (`operate_bookings`): re-queues every undelivered event, resets failed and retrying deliveries, and runs the outbox once. Idempotent: delivered workflows are not sent again.
- `GET /api/v1/ghl/workflow-triggers` (admin): the location's subscribed workflows, without target URLs.
- UI: the booking drawer has a "HighLevel workflow trigger" section below the GoHighLevel sync section, with a retry button. Notifications gets a `ghl_workflow_trigger_failed` item, separate from `ghl_sync_failed`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GHL_WORKFLOW_TRIGGER_ENABLED` | `false` | Records events and enables the status endpoints. Set it only **after** migration 045 is applied. While false, nothing touches the new tables. |
| `GHL_WORKFLOW_TRIGGER_SECRET` | empty | Value of `X-Passport-Trigger-Secret`. Empty refuses all subscription callbacks. |

`GHL_SYNC_MODE` is unchanged (`outbox`). With `GHL_SYNC_MODE=disabled`, no
events are recorded, because no contact sync runs to supply `ghl_contact_id`.

### Avoiding duplicate customer confirmations

Passport's own confirmation email runs only when `GHL_NOTIFICATIONS_ENABLED=true`
(and the operator's `confirmation_email_enabled` is on). Before a HighLevel
workflow sends confirmations, set `GHL_NOTIFICATIONS_ENABLED=false`, or switch
off "confirmation email" in the operator's settings, so only the workflow
sends. In the workflow, send "booking confirmed" only when `confirmed` is
`true` (for example on `payment_confirmed`, or on `booking_created` with
`confirmed == true` for free bookings). `booking_created` with
`confirmed == false` means payment is still pending.

## HighLevel-side steps (manual)

1. **Add the header** `X-Passport-Trigger-Secret: <GHL_WORKFLOW_TRIGGER_SECRET>` to the trigger's Subscription URL. This is a change to the trigger, so it needs a new trigger version and review in the Marketplace developer portal. The key, name, sample payload, filters and variables stay as published.
2. **Re-save the workflows.** The Subscription URL returned 404 until this code is deployed, so any workflow that added the trigger before then was never stored. Open each workflow that uses "Passport Booking Created" and save it again (or remove and re-add the trigger) so HighLevel sends a fresh CREATED/UPDATED.
3. **Optional new version:** to let workflow authors pick `payment_confirmed`, `booking_updated` or `booking_cancelled` from the Event Type filter, add them as options in a new trigger version. The repository cannot change the published trigger.
4. On a **test** location, confirm one delivery end to end (the execution contract is undocumented) before enabling the feature for the client.
