import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, ChevronLeft, ClipboardList, ChevronRight, CloudOff, Plus, RefreshCw, Users, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { PwaDeparture, PwaDeparturesResponse } from "../api/types";
import { useSession } from "../auth/GHLSessionProvider";
import { EmptyState } from "../components/EmptyState";

type Filter = "all" | "booked" | "open" | "unstaffed";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "booked", label: "Booked" },
  { value: "open", label: "No bookings" },
  { value: "unstaffed", label: "Needs staff" },
];

const INACTIVE = new Set(["cancelled", "failed"]);

function todayInZone(timeZone: string): string {
  const values = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(new Date())
      .map((part) => [part.type, part.value]),
  );
  return `${values.year}-${values.month}-${values.day}`;
}

function shiftDate(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatDay(value: string): string {
  return new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));
}

function formatTime(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone, hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatStatus(status: string | null): string {
  return (status || "none").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

// Staff wording for payment state; never implies an unpaid invoice/card is paid.
function paymentLabel(method: string | null, status: string | null): string {
  if (method === "none") return "Free";
  if (status === "succeeded") return "Paid";
  if (status === "partially_refunded") return "Partly refunded";
  if (status === "refunded") return "Refunded";
  if (status === "failed") return "Payment failed";
  if (method === "invoice") return "Invoice unpaid";
  if (method === "card") return "Awaiting card";
  return formatStatus(status);
}

function activeBookings(departure: PwaDeparture) {
  return departure.bookings.filter((booking) => !INACTIVE.has(booking.status));
}

function matches(departure: PwaDeparture, filter: Filter): boolean {
  const booked = activeBookings(departure).length > 0;
  if (filter === "booked") return booked;
  if (filter === "open") return !booked;
  if (filter === "unstaffed") return booked && departure.staff.length === 0;
  return true;
}

function ResourceMeter({ resource }: { resource: PwaDeparture["resources"][number] }) {
  const used = resource.confirmed + resource.held;
  const percent = resource.total ? Math.min(100, Math.round((used / resource.total) * 100)) : 100;
  return (
    <div className="departure-resource">
      <div className="departure-resource-label">
        <strong>{resource.name}</strong>
        <span><b>{resource.remaining}</b> of {resource.total} left</span>
      </div>
      <div className="departure-meter" role="img" aria-label={`${resource.confirmed} booked, ${resource.held} on hold, ${resource.remaining} remaining of ${resource.total}`}>
        <span className="confirmed" style={{ width: `${resource.total ? (resource.confirmed / resource.total) * 100 : 0}%` }} />
        <span className="held" style={{ width: `${resource.total ? (resource.held / resource.total) * 100 : 0}%` }} />
      </div>
      <div className="departure-resource-detail">{resource.confirmed} booked{resource.held ? ` · ${resource.held} on hold` : ""}{percent >= 100 ? " · Full" : ""}</div>
    </div>
  );
}

function DepartureCard({ departure, timeZone }: { departure: PwaDeparture; timeZone: string }) {
  const bookings = activeBookings(departure);
  const inactive = departure.bookings.length - bookings.length;
  return (
    <article className={`departure-card ${departure.blocked ? "blocked" : ""}`}>
      <header className="departure-card-header">
        <div className="departure-time">
          <time dateTime={departure.start_at}>{formatTime(departure.start_at, timeZone)}</time>
          <span>to {formatTime(departure.end_at, timeZone)}</span>
        </div>
        <div className="departure-title">
          <strong><span className="departure-dot" style={{ background: departure.category_color || "var(--accent)" }} aria-hidden="true" />{departure.calendar_name}</strong>
          <span>{bookings.length ? `${bookings.length} ${bookings.length === 1 ? "booking" : "bookings"} · ${departure.booked_units} ${departure.booked_units === 1 ? "unit" : "units"}` : "No bookings yet"}</span>
        </div>
        <div className="departure-flags">
          {departure.blocked && <span className="departure-flag danger"><CloudOff size={13} aria-hidden="true" />Closed</span>}
          {departure.source === "unscheduled" && <span className="departure-flag warning" title="This time is no longer in the calendar's schedule"><AlertTriangle size={13} aria-hidden="true" />Off schedule</span>}
        </div>
      </header>

      {departure.resources.length ? (
        <div className="departure-resources">{departure.resources.map((resource) => <ResourceMeter key={resource.resource_id} resource={resource} />)}</div>
      ) : (
        <p className="departure-note">No resources are linked to this calendar, so remaining capacity cannot be shown.</p>
      )}

      <div className="departure-staff">
        <Users size={15} aria-hidden="true" />
        {departure.staff.length
          ? <span>{departure.staff.map((member) => member.role ? `${member.staff_name} (${member.role})` : member.staff_name).join(", ")}</span>
          : <span className={bookings.length ? "missing" : ""}>No staff assigned</span>}
      </div>

      {bookings.length > 0 && (
        <ul className="departure-bookings">
          {bookings.map((booking) => (
            <li key={booking.id}>
              <Link to={`/app/bookings?booking=${encodeURIComponent(booking.id)}`}>
                <span className="departure-booking-main"><strong>{booking.lead_name || "Guest"}</strong><span>{booking.public_reference} · {booking.units} {booking.units === 1 ? "unit" : "units"}</span></span>
                <span className="departure-booking-status">
                  <span className={`status-pill ${booking.status}`}>{formatStatus(booking.status)}</span>
                  <span className="departure-payment">{paymentLabel(booking.payment_method, booking.payment_status)}</span>
                </span>
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {inactive > 0 && <p className="departure-note">{inactive} cancelled {inactive === 1 ? "booking" : "bookings"} not shown.</p>}
      {bookings.length > 0 && (
        <div className="departure-card-actions">
          <Link to={`/app/manifest?${new URLSearchParams({ calendar_id: departure.calendar_id, start_at: departure.start_at })}`}><ClipboardList size={15} aria-hidden="true" />Manifest &amp; check-in</Link>
        </div>
      )}
    </article>
  );
}

export function DeparturesPage() {
  const { me } = useSession();
  const operatorTimeZone = me.operator.time_zone || "UTC";
  const [selectedDate, setSelectedDate] = useState(() => todayInZone(operatorTimeZone));
  const [filter, setFilter] = useState<Filter>("all");
  const board = useQuery({
    queryKey: ["pwa-departures", selectedDate],
    queryFn: () => api<PwaDeparturesResponse>(`/pwa/departures?date=${encodeURIComponent(selectedDate)}`),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
  const timeZone = board.data?.time_zone || operatorTimeZone;
  const visible = useMemo(() => (board.data?.departures || []).filter((item) => matches(item, filter)), [board.data, filter]);

  return (
    <main className="page departures-page">
      <header className="departures-header">
        <div>
          <h1>Departures</h1>
          <p>{formatDay(selectedDate)} · {timeZone}</p>
        </div>
        <Link className="button" to="/app/bookings?new=1"><Plus size={17} aria-hidden="true" />New booking</Link>
      </header>

      <div className="departures-date" role="group" aria-label="Choose a day">
        <button className="icon-button" type="button" onClick={() => setSelectedDate((value) => shiftDate(value, -1))} aria-label="Previous day"><ChevronLeft size={18} /></button>
        <input type="date" value={selectedDate} onChange={(event) => event.target.value && setSelectedDate(event.target.value)} aria-label="Date" />
        <button className="icon-button" type="button" onClick={() => setSelectedDate((value) => shiftDate(value, 1))} aria-label="Next day"><ChevronRight size={18} /></button>
        <button className="button ghost" type="button" onClick={() => setSelectedDate(todayInZone(timeZone))}>Today</button>
      </div>

      <div className="departures-filters" role="group" aria-label="Filter departures">
        {FILTERS.map((item) => (
          <button key={item.value} type="button" className={`chip ${filter === item.value ? "active" : ""}`} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>
        ))}
      </div>

      {board.isLoading && <div className="dashboard-state loading" role="status"><div className="spinner" /><span>Loading departures…</span></div>}
      {board.error && (
        <section className="dashboard-state error-banner" role="alert">
          <XCircle size={20} aria-hidden="true" />
          <div><strong>Departures unavailable</strong><span>{board.error instanceof Error ? board.error.message : "We could not load departures."}</span></div>
          <button className="button secondary" type="button" onClick={() => void board.refetch()}><RefreshCw size={16} aria-hidden="true" />Try again</button>
        </section>
      )}
      {board.data && (visible.length ? (
        <div className="departure-list">{visible.map((departure) => <DepartureCard key={`${departure.calendar_id}-${departure.start_at}`} departure={departure} timeZone={timeZone} />)}</div>
      ) : (
        <EmptyState
          title={board.data.departures.length ? "Nothing matches this filter" : "No departures"}
          copy={board.data.departures.length ? "Choose another filter to see the rest of the day." : "No active calendar offers a departure on this day."}
        />
      ))}
    </main>
  );
}
