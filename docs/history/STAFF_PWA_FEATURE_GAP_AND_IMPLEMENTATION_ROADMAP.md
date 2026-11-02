# Staff PWA Feature Gap and Implementation Roadmap

**Repository:** `https://github.com/moawiz-2706/MVP.git`
**Fresh clone reviewed:** `/home/ubuntu/MVP_20261020`
**Commit reviewed:** `c5393a1 Fix standalone PWA origin and persistent sessions`
**Status:** The first implementation release is complete and tested. The Home dashboard, universal search, phone-oriented Customers/Staff views, lazy-loaded route performance work, and PWA workspace indexes are implemented. Later sections that require product, payment, or CRM-data-policy decisions remain roadmap items.

## Current conclusion

The current PWA is a useful Passport operations console, but it is not yet a full LeadConnector-style mobile workspace. It already covers the core booking domain: calendars, availability, resources, rates, bookings, customers, staff assignments, payments, waivers, reports, notifications, and GHL synchronization.

The largest gap is not the existence of screens. The largest gap is that several screens expose only a narrow slice of each workflow. For example, the booking drawer shows payment, waiver, participant, note, resource, and GHL information, but it does not yet provide a complete unified appointment workspace with activity history, customer actions, payment collection, reschedule-link sharing, attendee-level actions, documents, or communications.

LeadConnector’s current mobile experience is broader than a booking application. Its mobile homepage includes role-aware widgets, pinned apps, quick actions, universal search, notifications, dark mode, and an AI assistant. Its unified appointment experience includes details, attendees, forms, notes, activity history, and payments. Its contact experience includes conversations, activities, tasks, notes, appointments, documents, payments, and associations. These capabilities are documented by HighLevel’s official support material. [1] [2] [3] [4] [5]

Passport should not blindly clone every LeadConnector module. It should become a strong mobile-first booking and staff operations product, while integrating with GHL for CRM and communications where GHL is the chosen system of record.

## What exists today

### PWA shell and authentication

The frontend is a React/Vite application with a single `/app` workspace. The current shell contains a sidebar, mobile drawer navigation, an install prompt, an operation notice area, and the following pages:

- Bookings;
- Notifications;
- Resources;
- Locations;
- Calendars;
- Staff;
- Customers;
- Reports; and
- Settings.

The PWA currently uses HighLevel OAuth for standalone login and the HighLevel iframe handshake for the embedded version. After HighLevel authentication, Passport creates its own session. The browser stores the Passport JWT in `localStorage` and refreshes it through Passport. This is better than storing a HighLevel refresh token in the browser, but a future Passport-owned staff login should preferably use an HttpOnly cookie and rotating refresh sessions.

The PWA service worker caches the application shell but intentionally does not cache API responses. The app can show an offline page, but it is not an offline-capable operations app. Booking creation, calendar changes, payments, staff assignments, and booking updates require a live network connection.

### Bookings and calendar operations

The Bookings page currently provides:

- FullCalendar month, week, and day views on larger screens;
- a compact mobile agenda;
- calendar, category, and search filtering;
- slot-level booking counts and capacity context;
- booking creation from a live available slot;
- customer, quantity, rate, and custom-field entry;
- payment-required or free booking behavior in the operator booking form;
- booking detail drawer;
- booking time and quantity editing where allowed;
- cancellation;
- completed and no-show status actions;
- weather closure with refund, credit, manual-review, or no-refund outcome;
- participant manifest add/remove;
- internal booking notes;
- resource consumption display;
- waiver status and waiver-link copy/view actions;
- payment and hosted invoice status;
- GHL contact, confirmation, and appointment synchronization status;
- GHL synchronization retry/resync; and
- staff assignment, reassignment, role, and availability checks from a slot view.

The Calendars page currently provides:

- calendar create, edit, archive/delete;
- public slug, description, instructions, hero image, and gallery URLs;
- category and departure location assignment;
- duration and slot interval;
- dollar-based base price input;
- public booking mode and cutoff;
- party-size limits;
- weekly availability;
- explicit date availability;
- pushed slots;
- blocked dates;
- shared resources and capacity mappings;
- customer types and rate plans;
- rate-level fees and taxes; and
- public booking links.

The calendar screen has a mobile card list, but most editing remains a dense form/modal experience rather than a guided phone workflow.

### Staff operations

The Staff page currently:

- synchronizes staff identity and weekly availability from GHL;
- shows name, email, phone, GHL user ID, active status, and cached availability;
- lets Passport assign a predefined operational role such as Captain, First Mate, Guide, Deckhand, or Instructor;
- shows overlapping assignment conflicts;
- generates a private mobile booking link; and
- lets an operator copy or regenerate that link.

The link currently supports quick staff booking. It is not a complete authenticated Staff PWA identity and does not replace the HighLevel login for the full operator workspace.

### Customers, reports, payments, waivers, and notifications

Customers currently support search, a customer drawer, booking history, lifetime paid value, GHL contact ID visibility, and Passport internal notes. There is no complete CRM-style customer workspace.

Reports currently provide summary metrics and CSV booking export. They do not yet provide a mobile dashboard with charts, drill-downs, date presets, resource utilization, staff utilization, cancellation reasons, payment exceptions, or export filtering.

Settings currently include general business information, Stripe Connect onboarding/status, communications copy, message templates, and waiver settings. Stripe status can be refreshed, but the booking detail screen is primarily read-only for payments. It does not yet offer a complete appointment payment workspace for collecting a balance, recording a manual payment, viewing transaction history, issuing a refund, or managing payment exceptions from one mobile screen.

Notifications currently poll the backend and surface setup actions, missing staff assignment, calendar/resource problems, and failed GHL synchronization. They are action-oriented but are not a general mobile notification center with read/unread state, per-user preferences, push notifications, or deep links to all affected records.

## What LeadConnector provides that Passport does not yet provide

HighLevel’s current mobile documentation describes a mobile command-center experience with a role-aware home screen, pinned apps, quick actions, universal search, notifications, dark mode, and Ask AI. The official mobile overview lists widgets for tasks, opportunity pipeline value, unread messages, and today’s appointments, plus quick actions for creating contacts, opportunities, tasks, and messages. [1]

The unified appointment screen consolidates appointment details, attendees, form submissions, notes, activity history, and payments into tabs. It also supports attendee-level status changes, rescheduling, contact access, cancellation, and customer reschedule-link generation where supported. [2]

Service appointments can be edited, rescheduled, duplicated, deleted, or shared through a reschedule link. Paid appointments apply restrictions to protect payment-related data, and location details can open navigation or a virtual meeting link. [3]

The contact detail page provides a broader CRM workspace with editable contact information, tags, DND preferences, conversations, activities, opportunities, tasks, notes, appointments, documents, payments, companies, and custom-object associations. [4]

HighLevel also supports user-level notification preferences across in-app/web, desktop, email, mobile, and SMS channels for supported conversations, tasks, appointments, reviews, and related activity. [5]

## Improvements that should be implemented in Passport

### 1. Build a real mobile home dashboard

**Current gap:** The PWA opens into the Bookings page. There is no operational home screen showing what needs attention today.

**Recommended feature:** Create `/app/home` or make `/app` a dashboard with:

- today’s bookings;
- next upcoming booking;
- unassigned bookings;
- staff conflicts;
- pending payments and unpaid invoices;
- waivers awaiting signature;
- failed GHL syncs;
- today’s revenue and booking count;
- capacity warnings;
- weather-closure candidates;
- quick actions for new booking, calendar view, customer search, and staff assignment.

**Implementation:** Add one backend bootstrap/dashboard endpoint that returns a tenant-scoped summary in one response. Add date presets such as Today, Tomorrow, This Week, and Next 7 Days. Use compact mobile cards and allow each card to deep-link to the relevant page or drawer. Avoid making the dashboard call ten independent endpoints on startup.

**Database/API work:** Add indexed aggregate queries or summary views for bookings, payment exceptions, waiver status, staff gaps, and failed syncs. Add a per-user dashboard preference table later for pinned widgets.

### 2. Add a universal search

**Current gap:** Customers have a search box, and bookings have a customer/reference search, but there is no search across the whole Passport workspace.

**Recommended feature:** A top-level search that searches:

- customer name, email, and phone;
- booking reference;
- calendar/activity name;
- staff name;
- payment/invoice reference;
- waiver reference; and
- internal notes where permission allows.

**Implementation:** Add `GET /search?q=&types=&limit=`. Return grouped results with the record type, title, subtitle, status, and deep-link URL. Add recent-search storage locally and keyboard/mobile shortcuts. Add PostgreSQL indexes or trigram search only after measuring query volume.

### 3. Upgrade the booking calendar to a complete mobile calendar

**Current gap:** The current calendar supports viewing and tapping slots, but it does not behave like a full mobile scheduling tool.

**Recommended feature:** Add:

- agenda, day, week, and month views with a simple view switcher;
- date jump and today button;
- calendar/category/staff/status filters in a bottom sheet;
- capacity coloring for available, nearly full, full, and blocked slots;
- unassigned-booking indicators;
- staff workload indicators;
- tap-and-hold or action-menu behavior for bookings;
- drag-and-drop rescheduling only after backend validation is complete;
- timezone display on every scheduling action; and
- quick action to create a booking from an open slot.

**Implementation:** Keep Passport’s availability service authoritative. Add a compact `calendar_day_summary` endpoint rather than sending the entire month of bookings to the phone. For drag/drop, send a mutation with an idempotency key and revalidate capacity, staff conflict, cancellation/reschedule policy, payment restrictions, and waiver implications on the server.

### 4. Create a unified booking/appointment workspace

**Current gap:** Booking data is split into sections inside a drawer. It does not yet match the unified appointment concept of details, attendees, forms, notes, activity, and payments.

**Recommended tabs:**

- Overview;
- Attendees;
- Customer;
- Custom fields/forms;
- Notes;
- Activity history;
- Payment;
- Waiver;
- Resources and staff;
- GHL synchronization; and
- Documents, when document storage is added.

**Overview should include:** activity/calendar, date/time, timezone, location, booking status, source, quantity, rate, customer, quick actions, and a clear action menu.

**Implementation:** Add a booking detail response designed for the mobile workspace, or add a `/bookings/{id}/workspace` endpoint that returns the data needed by the tabs. Keep mutations separate and idempotent. Do not allow the frontend to infer whether a paid booking may be edited.

### 5. Improve attendee and participant management

**Current gap:** Passport can add/remove participants, but participant-level status and actions are limited.

**Recommended feature:** For each participant:

- confirm;
- showed;
- no-show;
- cancelled;
- reschedule where policy allows;
- view or create a customer record;
- add email/phone;
- capture emergency/guardian information where required; and
- attach participant-specific waiver/signature state.

**Implementation:** Add participant status transitions and audit events. Add participant-level authorization and capacity rules. Keep the lead customer/order separate from individual participants. Add status and participant filters in the booking drawer.

### 6. Add proper reschedule, duplicate, and customer-link actions

**Current gap:** Passport supports some time/quantity edits, but there is no complete mobile action menu like Service v2.

**Recommended actions:**

- Reschedule booking;
- Generate customer reschedule link;
- Duplicate booking;
- Cancel booking;
- Reopen or retry a failed payment where permitted;
- Mark completed;
- Mark no-show;
- Create a follow-up task; and
- Share booking/waiver/invoice links through the phone share sheet.

**Implementation:** Reuse the existing lifecycle and policy services. Add a secure, purpose-bound reschedule credential. Generate a shareable link without exposing operator sessions. Duplicate should create a new draft/order flow, not silently clone a confirmed payment.

### 7. Add a real payment workspace

**Current gap:** Staff can see payment/invoice status and initiate some booking payment flows, but the booking detail does not act as a full payment center.

**Recommended feature:**

- payment timeline;
- PaymentIntent status and failure reason;
- hosted invoice state and payment link;
- collect remaining balance;
- record a manual payment for authorized roles;
- partial refund/full refund action;
- transfer/payout status;
- payment exception and provider-unknown resolution;
- secure card entry through Stripe Elements only; and
- no raw card data stored by Passport.

**Implementation:** Add explicit payment commands with server-side permission checks and idempotency keys. Use the existing Stripe reconciliation and refund services. Add confirmation dialogs for refunds and manual payments. Never put Stripe secret values or card data in the PWA.

### 8. Improve customer records toward a CRM workspace

**Current gap:** The customer page is a list and drawer with booking history and notes. It does not support the richer contact view documented for LeadConnector.

**Recommended feature:**

- edit customer name, email, and phone;
- tags;
- communication preferences/DND;
- booking timeline;
- payment timeline;
- waiver history;
- notes and mentions;
- participant relationships;
- upcoming appointments;
- documents and links;
- GHL contact link/status; and
- duplicate/merge workflow.

**Implementation:** Add `PATCH /customers/{id}`, customer tags, customer activity records, and a paginated activity endpoint. Add audit events for profile changes. Keep GHL contact identity as a projection and define which fields Passport owns versus which fields GHL owns.

### 9. Add communications and contact activity only if the product wants CRM parity

**Current gap:** Passport has message template settings and GHL delivery, but it does not present the GHL conversation inbox inside the PWA.

**Recommended feature if required:**

- inbox/conversations;
- SMS/email/WhatsApp channel indicator;
- conversation list and filters;
- unread count;
- contact conversation view;
- internal comments;
- attachments;
- appointment/invoice activity cards;
- DND status; and
- assignment/follower state.

**Implementation choices:**

1. Keep GHL as the conversation system and proxy the required GHL APIs through the backend. This avoids duplicating message storage but requires provider scopes, rate limits, pagination, webhook events, and careful error handling.
2. Make Passport the conversation system. This is a much larger project requiring message storage, provider adapters, delivery status, opt-outs, templates, attachments, compliance, and channel-specific handling.

For this product, the first option is more practical. If customer communication is meant to go through GHL workflows, Passport should show sync/automation status rather than duplicate the entire inbox.

### 10. Add tasks and staff follow-ups

**Current gap:** The current PWA has internal notes but no task system comparable to LeadConnector tasks and reminders.

**Recommended feature:**

- create task from a booking/customer;
- assign task to staff;
- due date/time;
- priority;
- status: open, completed, cancelled;
- recurring or follow-up task later;
- task list and Today/Overdue filters;
- task count on dashboard; and
- optional push/email notification preferences.

**Implementation:** Add `tasks` and `task_events` tables with operator/staff ownership and indexes on assignee/status/due time. Add API routes for CRUD and completion. Keep tasks separate from booking notes because tasks have lifecycle and reminders.

### 11. Build the staff operations workspace

**Current gap:** The Staff page is mostly a synced directory. Staff cannot manage their own operational day as a first-class mobile workflow.

**Recommended feature:**

- My Day view;
- today’s assigned bookings;
- route/location information;
- customer and participant details;
- check-in/showed/no-show actions;
- staff notes;
- customer phone/email shortcuts;
- assignment acceptance or decline;
- availability exceptions;
- shift start/end or working blocks;
- leave/unavailable dates; and
- staff PWA invite/session management.

**Implementation:** Add a staff-scoped API that uses a Passport staff principal. Do not rely on the current GHL user ID for every staff PWA session if HighLevel login is removed. Add staff assignment status and audit events. Keep the operator/admin calendar view separate from the staff’s personal view.

### 12. Add notifications and push behavior

**Current gap:** Notifications are polled every 15 seconds and mainly represent setup actions and failed synchronization. There is no personal notification center or push channel.

**Recommended feature:**

- unread/read state;
- mark one or all as read;
- notification categories;
- deep link to booking/customer/calendar;
- staff assignment alerts;
- new booking alerts;
- cancellation/reschedule alerts;
- payment failure alerts;
- waiver signed alerts;
- task reminders;
- GHL sync failure alerts; and
- browser/mobile push notifications.

LeadConnector supports notification preferences across in-app/web, desktop, email, mobile, and SMS for supported activities. [5]

**Implementation:** Add a `notifications` and `notification_preferences` model with deduplication keys. For PWA push, add a web-push subscription endpoint and store device subscriptions. Use a reliable background execution path for delivery. Vercel serverless requests should not be treated as a continuously running worker. Keep in-app notification creation transactional and delivery asynchronous.

### 13. Improve resources and capacity management

**Current gap:** Resources can be configured and mapped, but the mobile app lacks a visual inventory/capacity board.

**Recommended feature:**

- resource list with quantity and active state;
- booked/reserved/available counts by day;
- calendar/resource utilization;
- capacity warnings;
- resource conflict explanation;
- quick adjustment with audit trail;
- resource maintenance/block periods; and
- resource history.

**Implementation:** Add resource utilization queries by date range and calendar. Keep booking-time locking in the backend. Do not allow a mobile convenience action to bypass the resource lock or create negative capacity.

### 14. Improve locations and field operations

**Current gap:** Locations are managed as configuration records, but booking users do not get a strong field-use experience.

**Recommended feature:**

- address display and copy;
- open in Apple Maps/Google Maps;
- pickup instructions;
- parking/check-in notes;
- meeting point image;
- virtual meeting URL where relevant;
- location-specific calendar filtering; and
- location conflict warnings.

**Implementation:** Add structured location fields and secure rendering. Use external map links generated from normalized address data. Keep customer-facing and staff-only instructions separate.

### 15. Improve reporting and dashboard analytics

**Current gap:** Reports provide summary numbers and CSV export, but not an operational mobile analytics experience.

**Recommended feature:**

- date presets;
- gross/net revenue;
- collected, pending, failed, refunded, and disputed payments;
- bookings by calendar/category;
- conversion from quote to booking;
- cancellation and no-show rate;
- resource utilization;
- staff assignment/utilization;
- waiver completion rate;
- GHL sync health;
- customer repeat-booking rate; and
- CSV exports with filters.

**Implementation:** Add aggregate queries or materialized summaries only after measuring. Use server-side pagination and date limits. Keep financial values in minor units internally and format to dollars only at the UI boundary.

### 16. Add audit history everywhere important

**Current gap:** Booking events exist, but there is no complete user-facing audit timeline across customer, payment, calendar, staff, and configuration actions.

**Recommended feature:** An Activity tab should show:

- who changed the booking;
- what changed;
- previous and new values;
- payment/waiver/GHL events;
- staff assignment changes;
- customer profile changes;
- cancellation/reschedule reasons; and
- provider request IDs/error details where relevant.

**Implementation:** Standardize an `audit_log` event schema with actor, operator, entity type, entity ID, action, before JSON, after JSON, correlation ID, and timestamp. Make the UI read-only. Keep sensitive payment/card data out of audit payloads.

### 17. Add dark mode and phone-quality UI behavior

**Current gap:** The PWA has responsive layouts and a mobile sidebar, but no complete mobile design system or dark mode.

**Recommended feature:**

- system/light/dark theme;
- larger tap targets;
- safe-area support;
- bottom-sheet filters;
- sticky action bars;
- skeleton loaders;
- empty states;
- optimistic updates only for safe local UI actions;
- clear offline/read-only mode;
- pull-to-refresh or a visible refresh action;
- haptic-like visual feedback where supported; and
- native share links.

HighLevel’s current mobile overview explicitly positions role-aware navigation, pinned apps, faster transitions, true-black dark mode, and role-based module visibility as mobile experience improvements. [1]

**Implementation:** Create shared mobile primitives instead of styling each page separately: `MobileHeader`, `BottomSheet`, `ActionMenu`, `SegmentedFilter`, `Skeleton`, `StatusBadge`, `EmptyState`, and `ConfirmAction`. Store only non-sensitive display preferences locally.

### 18. Improve performance and perceived speed

**Current gap:** The shell performs several queries and some pages poll frequently. The Staff page refreshes staff every 15 seconds, Notifications every 15 seconds, and the app shell also loads staff and notifications for badges. This can create duplicate requests and visible delay, especially on mobile or serverless cold starts.

**Recommended improvements:**

- add one bootstrap endpoint for user, permissions, operator, feature flags, and badge counts;
- avoid loading all calendars/resources/locations when opening unrelated pages;
- use query caching and targeted invalidation;
- pause polling when the page is hidden;
- use longer stale times for configuration data;
- use push/SSE/realtime only for events that need immediate updates;
- paginate bookings, customers, notes, and activity timelines;
- return compact mobile list projections rather than full detail objects;
- add database indexes for tenant/date/status/assignee queries;
- move GHL and Stripe external calls out of request paths where possible;
- keep outbox/worker work separate from page loads; and
- add timing logs with correlation IDs for slow requests.

### 19. Add offline behavior, but keep booking mutations online-only

**Current gap:** The shell can load an offline page, but the application cannot safely create or change bookings offline.

**Recommended feature:**

- cache the shell and non-sensitive read-only configuration;
- show last successful synchronization time;
- display an offline banner;
- allow viewing a small cached My Day list only if risk is acceptable;
- queue harmless notes/tasks only if conflict handling is designed; and
- disable booking, payment, cancellation, and calendar mutations offline.

**Implementation:** Never cache payment data, customer-sensitive data, waiver signatures, or bearer tokens in a public service-worker cache. Start with offline detection and clear read-only messaging rather than pretending the app is fully offline.

### 20. Add a safer Passport-owned login

**Current gap:** Standalone PWA login depends on HighLevel OAuth and the PWA stores its Passport JWT in browser storage.

**Recommended feature:** Replace only the Staff PWA login with Passport staff invite + PIN/password + revocable session, while retaining server-side GHL installation credentials for synchronization.

The detailed design is in `STAFF_PWA_NO_GHL_AUTH_WORKAROUND.md`. This should be implemented before expanding staff-only workflows, because the authorization model needs to identify a Passport staff member independently of GHL.

### 21. Add subscription/feature gating later

LeadConnector’s mobile experience hides modules according to role and account subscription tier. [1] Passport currently has permissions but not a complete feature-entitlement system.

**Recommended feature:** Add operator feature flags and plan entitlements for modules such as reports, staff management, payments, messaging proxy, and advanced automation.

**Implementation:** Resolve entitlements in the backend bootstrap response. Use them to hide navigation and block APIs. Never rely only on frontend hiding.

### 22. Add automation and workflow visibility carefully

**Current gap:** Passport has message templates and GHL synchronization, but the PWA does not show which automations were triggered or whether a customer workflow is pending.

**Recommended feature:**

- booking-created automation status;
- payment-confirmed automation status;
- waiver-pending/signed status;
- cancellation/reschedule automation status;
- last GHL workflow/event timestamp;
- failed automation details; and
- manual retry where safe.

**Implementation:** Add an event ledger for booking lifecycle events. Publish events after the local transaction commits. Let GHL workflows own customer email/SMS if that remains the product decision. Passport should not duplicate customer messages; it should expose automation status and failures.

### 23. Ask AI and marketing features should not be first priority

LeadConnector also includes Ask AI for drafting content, updating CRM records, and generating images, plus communications, opportunities, pipelines, social, funnels, and marketing modules. [1]

These are not natural first-party features for Passport’s booking operations product. If the client wants full LeadConnector parity, they become separate products:

- Conversations and communications;
- Contacts/CRM;
- Opportunities and pipeline;
- Tasks;
- Reviews;
- Social/marketing;
- Campaigns and workflows;
- AI assistant; and
- documents/client portal.

The safer workaround is to keep these in GHL and connect the Passport booking/contact events to GHL. Rebuilding them inside Passport would duplicate the system the client already pays for and would substantially increase security, compliance, messaging, and maintenance requirements.

## Recommended navigation redesign

The current sidebar should evolve into a mobile-first app drawer with these groups:

### Home

- Today;
- My assignments;
- Alerts; and
- Quick actions.

### Bookings

- Calendar;
- All bookings;
- Unassigned;
- Pending payment;
- Waivers; and
- Activity/history.

### Customers

- Customer search;
- Recent customers;
- Follow-ups/tasks; and
- Customer activity.

### Operations

- Calendars;
- Resources;
- Staff;
- Locations; and
- Reports.

### Settings

- Business;
- Payments;
- Waivers;
- Notifications;
- Permissions;
- GHL sync; and
- PWA/session management.

On mobile, the most common actions should also be available through a bottom action button: New booking, Search, Add note/task, and Open calendar.

## Recommended implementation order

### Phase 0: security and product boundary

Decide whether the PWA is only for staff operations or also a full GHL CRM replacement. Do not begin with Conversations, AI, or marketing. First implement Passport-owned Staff PWA authentication or keep HighLevel OAuth stable as a temporary fallback.

Define staff, operator, admin, and read-only permissions. Add a feature/permission bootstrap response.

### Phase 1: mobile operations foundation

Implement the dashboard, compact bootstrap endpoint, universal search, mobile header/action menu, loading skeletons, offline banner, dark mode, and notification read/unread foundation.

### Phase 2: unified booking workspace

Implement booking tabs, attendee status actions, reschedule/duplicate/share-link actions, payment timeline, waiver actions, activity history, and clear permission-aware action menus.

### Phase 3: staff day-to-day workflow

Implement My Day, assigned bookings, check-in/no-show/completion, customer contact shortcuts, staff notes, assignment changes, availability exceptions, and staff PWA session management.

### Phase 4: calendar and inventory operations

Implement capacity heatmaps, resource utilization, mobile calendar editing, better filters, slot actions, location navigation, and safe drag/drop rescheduling.

### Phase 5: customer and task workspace

Implement editable customer profiles, tags, activity timeline, tasks, follow-ups, duplicate detection, notes/mentions, and GHL contact status.

### Phase 6: payment, reporting, and reliability

Implement payment collection/refunds/manual payment permissions, payment exception recovery, report drilldowns, exports, audit history, performance instrumentation, and background job monitoring.

### Phase 7: optional GHL workspace parity

Only if required, add a GHL conversation proxy, activity cards, task synchronization, workflow status, and deep links. Keep GHL-owned customer communications in GHL workflows rather than building a second message system.

## Acceptance criteria before calling the PWA complete

The PWA should not be considered complete when only the page layouts exist. Each feature should have:

- a backend API;
- tenant and permission checks;
- database constraints and indexes;
- loading, empty, error, and offline states;
- idempotency for important mutations;
- audit events for destructive or financial changes;
- mobile visual validation;
- automated tests;
- a production smoke test; and
- documentation for operator behavior.

The most important end-to-end test should cover this sequence:

1. Staff opens Passport and authenticates.
2. Staff sees the correct operator and only permitted modules.
3. Staff opens My Day and a booking.
4. Staff views customer, attendees, payment, waiver, notes, resources, and activity.
5. Staff changes a participant status or reschedules within policy.
6. Passport revalidates inventory and financial rules.
7. GHL synchronization or workflow projection is recorded.
8. Another staff member sees the update without a stale page.
9. Failed external work appears as an actionable notification.
10. Revoking the staff account immediately blocks the PWA session.

## Recommended workaround

Do not attempt to duplicate the entire LeadConnector app inside Passport. Build the PWA around the operational jobs the staff actually perform:

- see today’s work;
- find a booking or customer quickly;
- manage appointment details and attendees;
- collect or verify payment;
- manage waivers;
- assign and complete staff work;
- update calendars and capacity;
- resolve exceptions; and
- share the correct customer links.

Use GHL as the communication/CRM/automation companion. Passport should be the authoritative source for booking availability, resources, pricing, waivers, payment state, and operational booking lifecycle. This keeps the system focused and avoids building a second version of every GHL marketing and communication module.

## References

[1]: https://help.gohighlevel.com/support/solutions/articles/155000008398-highlevel-mobile-app-experience "HighLevel Mobile App Experience"

[2]: https://help.gohighlevel.com/support/solutions/articles/155000007952-unified-appointment-screen-in-the-highlevel-mobile-app "Unified Appointment Screen in the HighLevel Mobile App"

[3]: https://help.gohighlevel.com/support/solutions/articles/155000007941-manage-service-v2-appointments-in-the-mobile-app "Manage Service v2 Appointments in the Mobile App"

[4]: https://help.gohighlevel.com/support/solutions/articles/155000006651-contacts-all-new-contact-detail-page "Contacts All-New Contact Detail Page"

[5]: https://help.gohighlevel.com/support/solutions/articles/48001224427-manage-notification-settings-in-a-sub-account "Manage Notification Settings in a Sub-Account"
