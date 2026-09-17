export const RECENT_BOOKING_WINDOW_MS = 86_400_000;

/** True when a booking was created within the recent indicator window. */
export function isRecentlyCreatedBooking(createdAt: string, now = Date.now()): boolean {
  const created = Date.parse(createdAt);
  return Number.isFinite(created) && created <= now && now - created < RECENT_BOOKING_WINDOW_MS;
}
