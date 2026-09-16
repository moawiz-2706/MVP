/**
 * All customer- and operator-facing times are rendered in the OPERATOR's IANA
 * timezone, never the viewer's. A customer in London booking a Florida rental —
 * or an operator travelling — must see the operator's local hours, because those
 * are the hours the booking actually happens in.
 *
 * Locale stays `undefined` (the viewer's own formatting preference) while the
 * timeZone is pinned to the operator's zone.
 */

export function formatTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone, hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}

export function formatDay(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone, month: "short", day: "numeric" }).format(new Date(iso));
}

export function formatLongDate(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone, dateStyle: "long" }).format(new Date(iso));
}

/** YYYY-MM-DD as seen in the operator's zone, for <input type="date">. */
export function isoDayInZone(date: Date, timeZone: string): string {
  // en-CA renders ISO-shaped dates (YYYY-MM-DD).
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

/** Tomorrow's date in the operator's zone — the earliest bookable day. */
export function tomorrowInZone(timeZone: string): string {
  return isoDayInZone(new Date(Date.now() + 86_400_000), timeZone);
}

/** Short zone label (e.g. "EDT") so viewers can see which timezone applies. */
export function zoneLabel(timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" }).formatToParts(new Date());
  return parts.find((part) => part.type === "timeZoneName")?.value ?? timeZone;
}

/** Offset (ms) of `timeZone` from UTC at the given instant. */
function zoneOffsetMs(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, hour12: false,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(instant);
  const at = Object.fromEntries(parts.map((part) => [part.type, part.value])) as Record<string, string>;
  const asUTC = Date.UTC(
    Number(at.year), Number(at.month) - 1, Number(at.day),
    Number(at.hour) % 24, Number(at.minute), Number(at.second),
  );
  return asUTC - instant.getTime();
}

/**
 * Interpret a `datetime-local` value ("YYYY-MM-DDTHH:mm") as a wall-clock time
 * **in the operator's zone** and return the matching UTC instant as ISO.
 *
 * `new Date("2027-06-15T10:00")` would resolve against the browser's zone, so an
 * admin outside the operator's zone would silently book the wrong instant.
 * The offset is applied twice so the result stays correct across DST boundaries,
 * where the offset before and after the shift differ.
 */
export function zonedWallTimeToISO(localValue: string, timeZone: string): string {
  const [datePart = "", timePart = "00:00"] = localValue.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  const naiveUTC = Date.UTC(year ?? 0, (month ?? 1) - 1, day ?? 1, hour ?? 0, minute ?? 0);
  let instant = naiveUTC - zoneOffsetMs(new Date(naiveUTC), timeZone);
  instant = naiveUTC - zoneOffsetMs(new Date(instant), timeZone);
  return new Date(instant).toISOString();
}
