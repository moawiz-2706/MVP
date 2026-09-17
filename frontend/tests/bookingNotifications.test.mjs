import assert from "node:assert/strict";
import { isRecentlyCreatedBooking, RECENT_BOOKING_WINDOW_MS } from "../src/lib/bookingNotifications.ts";

const now = Date.parse("2026-09-18T12:00:00.000Z");
assert.equal(isRecentlyCreatedBooking("2026-09-18T11:59:59.999Z", now), true);
assert.equal(isRecentlyCreatedBooking(new Date(now - RECENT_BOOKING_WINDOW_MS).toISOString(), now), false);
assert.equal(isRecentlyCreatedBooking(new Date(now + 1).toISOString(), now), false);
assert.equal(isRecentlyCreatedBooking("not-a-date", now), false);
console.log("bookingNotifications helper tests passed");
