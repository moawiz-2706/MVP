import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CalendarDays, CheckCircle2, CircleUserRound, Clock3, CreditCard, FileCheck2, Plus, RefreshCw, UserRound, Users, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Booking, PwaDashboardResponse } from "../api/types";
import { useSession } from "../auth/GHLSessionProvider";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";

function todayInZone(timeZone: string): string {
  const values = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(new Date())
      .map((part) => [part.type, part.value]),
  );
  return `${values.year}-${values.month}-${values.day}`;
}

function formatDate(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T12:00:00Z`));
}

function formatTime(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatStatus(status: string): string {
  return status.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function BookingList({ bookings, timeZone, emptyCopy }: { bookings: Booking[]; timeZone: string; emptyCopy: string }) {
  if (!bookings.length) {
    return <EmptyState title="No bookings" copy={emptyCopy} />;
  }

  return (
    <div className="dashboard-booking-list">
      {bookings.map((booking) => (
        <Link className="dashboard-booking" key={booking.id} to={`/app/bookings?booking=${encodeURIComponent(booking.id)}`}>
          <span className="dashboard-booking-main">
            <strong>{booking.customer_name || "Guest"}</strong>
            <span>{booking.calendar_name}</span>
          </span>
          <span className="dashboard-booking-meta">
            <time dateTime={booking.start_at}>{formatTime(booking.start_at, timeZone)}</time>
            <span>{booking.units} {booking.units === 1 ? "guest" : "guests"}</span>
            <span className="dashboard-booking-status">{formatStatus(booking.status)}</span>
          </span>
          <ArrowRight size={17} aria-hidden="true" />
        </Link>
      ))}
    </div>
  );
}

export function DashboardPage() {
  const { me } = useSession();
  const operatorTimeZone = me.operator.time_zone || "UTC";
  const [selectedDate, setSelectedDate] = useState(() => todayInZone(operatorTimeZone));
  const dashboard = useQuery({
    queryKey: ["pwa-dashboard", selectedDate],
    queryFn: () => api<PwaDashboardResponse>(`/pwa/dashboard?date=${encodeURIComponent(selectedDate)}`),
  });
  const data = dashboard.data;
  const timeZone = data?.time_zone || operatorTimeZone;
  const dateLabel = data ? formatDate(data.date, timeZone) : formatDate(selectedDate, timeZone);

  const submitDate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void dashboard.refetch();
  };

  return (
    <main className="pwa-dashboard">
      <section className="dashboard-hero">
        <PageHeader
          title={`Welcome back, ${me.user.name || "team"}`}
          description={data ? `${dateLabel} · ${timeZone}` : "Your bookings and operational priorities at a glance."}
          action={
            <form className="dashboard-date" onSubmit={submitDate}>
              <label htmlFor="dashboard-date">Date</label>
              <input id="dashboard-date" type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
              <button className="button secondary" type="submit">View date</button>
              <button className="button ghost" type="button" onClick={() => setSelectedDate(todayInZone(timeZone))}>Today</button>
            </form>
          }
        />
        <div className="dashboard-actions" aria-label="Quick actions">
          <Link className="button" to="/app/bookings?new=1"><Plus size={17} aria-hidden="true" />New booking</Link>
          <Link className="button secondary" to="/app/bookings"><CalendarDays size={17} aria-hidden="true" />Bookings</Link>
          <Link className="button secondary" to="/app/calendars"><Clock3 size={17} aria-hidden="true" />Calendars</Link>
          <Link className="button secondary" to="/app/customers"><UserRound size={17} aria-hidden="true" />Customers</Link>
        </div>
      </section>

      {dashboard.isLoading && (
        <div className="dashboard-state loading" role="status">
          <div className="spinner" />
          <span>Loading your dashboard…</span>
        </div>
      )}

      {dashboard.error && (
        <section className="dashboard-state error-banner" role="alert">
          <XCircle size={20} aria-hidden="true" />
          <div><strong>Dashboard unavailable</strong><span>{dashboard.error instanceof Error ? dashboard.error.message : "We could not load your dashboard."}</span></div>
          <button className="button secondary" type="button" onClick={() => void dashboard.refetch()}><RefreshCw size={16} aria-hidden="true" />Try again</button>
        </section>
      )}

      {data && (
        <>
          <section className="dashboard-metrics" aria-label="Booking metrics">
            <div className="dashboard-metric"><CalendarDays size={19} aria-hidden="true" /><span>Today</span><strong>{data.counts.today}</strong></div>
            <div className="dashboard-metric"><Clock3 size={19} aria-hidden="true" /><span>Next 7 days</span><strong>{data.counts.upcoming}</strong></div>
            <div className="dashboard-metric"><CreditCard size={19} aria-hidden="true" /><span>Pending payment</span><strong>{data.counts.pending_payment}</strong></div>
            <div className="dashboard-metric"><FileCheck2 size={19} aria-hidden="true" /><span>Waivers pending</span><strong>{data.counts.waivers_pending}</strong></div>
            <div className="dashboard-metric"><Users size={19} aria-hidden="true" /><span>Unassigned</span><strong>{data.counts.unassigned_bookings}</strong></div>
            <div className="dashboard-metric"><RefreshCw size={19} aria-hidden="true" /><span>Sync failures</span><strong>{data.counts.sync_failures}</strong></div>
            <div className="dashboard-metric"><CircleUserRound size={19} aria-hidden="true" /><span>Staff conflicts</span><strong>{data.counts.staff_conflicts}</strong></div>
          </section>

          <section className="dashboard-attention" aria-labelledby="dashboard-attention-title">
            <div className="section-heading"><div><h2 id="dashboard-attention-title">Needs attention</h2><p>Resolve operational issues before they affect a guest.</p></div><AlertTriangle size={21} aria-hidden="true" /></div>
            {data.attention.length ? (
              <div className="dashboard-alert-list">
                {data.attention.map((item) => (
                  <Link className={`dashboard-alert ${item.severity}`} key={item.id} to={item.href}>
                    <AlertTriangle size={19} aria-hidden="true" />
                    <span><strong>{item.title}</strong><span>{item.description}</span></span>
                    <ArrowRight size={17} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            ) : (
              <div className="dashboard-clear"><CheckCircle2 size={20} aria-hidden="true" /><span><strong>All clear</strong><span>No operational issues need your attention.</span></span></div>
            )}
          </section>

          <section className="dashboard-schedule" aria-label="Booking schedule">
            <div className="dashboard-schedule-section">
              <div className="section-heading"><div><h2>Today</h2><p>{formatDate(data.date, timeZone)}</p></div><CalendarDays size={21} aria-hidden="true" /></div>
              <BookingList bookings={data.today} timeZone={timeZone} emptyCopy="There are no bookings scheduled for this day." />
            </div>
            <div className="dashboard-schedule-section">
              <div className="section-heading"><div><h2>Next 7 days</h2><p>Upcoming bookings after today</p></div><Clock3 size={21} aria-hidden="true" /></div>
              <BookingList bookings={data.upcoming} timeZone={timeZone} emptyCopy="No upcoming bookings in the next 7 days." />
            </div>
          </section>
        </>
      )}
    </main>
  );
}
