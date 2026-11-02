import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, CloudLightning, FileCheck2, Phone, RefreshCw, UserRound, Users, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useHasPermission } from "../api/bootstrap";
import { api, json } from "../api/client";
import type { PwaClosurePreview, PwaCloseDepartureResponse, PwaManifestBooking, PwaManifestParticipant, PwaManifestResponse, WeatherRefundMode } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";

const REFUND_MODES: { value: WeatherRefundMode; label: string }[] = [
  { value: "full_refund", label: "Full refund" },
  { value: "credit", label: "Account credit" },
  { value: "manual_review", label: "Hold for manual review" },
  { value: "no_refund", label: "No refund" },
];

function formatTime(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone, hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatDay(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone, weekday: "long", month: "short", day: "numeric" }).format(new Date(value));
}

function paymentLabel(method: string | null, status: string | null): string {
  if (method === "none") return "Free";
  if (status === "succeeded") return "Paid";
  if (status === "partially_refunded") return "Partly refunded";
  if (status === "refunded") return "Refunded";
  if (status === "failed") return "Payment failed";
  if (method === "invoice") return "Invoice unpaid";
  return "Awaiting card";
}

const WAIVER_LABEL = { signed: "Waiver signed", pending: "Waiver pending", none: "No waiver" } as const;

function ParticipantRow({ participant, onToggle, busy }: { participant: PwaManifestParticipant; onToggle: (checkedIn: boolean) => void; busy: boolean }) {
  const checkedIn = Boolean(participant.checked_in_at);
  return (
    <li className={`manifest-person ${checkedIn ? "checked-in" : ""}`}>
      <span className="manifest-person-main">
        <strong>{participant.name}</strong>
        <span>
          {participant.is_minor ? `Minor${participant.guardian_name ? ` · guardian ${participant.guardian_name}` : " · no guardian listed"}` : "Adult"}
          {participant.phone ? ` · ${participant.phone}` : ""}
        </span>
      </span>
      <button
        type="button"
        className={`check-in-button ${checkedIn ? "done" : ""}`}
        aria-pressed={checkedIn}
        disabled={busy}
        onClick={() => onToggle(!checkedIn)}
      >
        {checkedIn ? <><Check size={16} aria-hidden="true" />Checked in</> : "Check in"}
      </button>
    </li>
  );
}

function BookingBlock({ booking, busyId, onToggle }: { booking: PwaManifestBooking; busyId: string | null; onToggle: (participant: PwaManifestParticipant, checkedIn: boolean) => void }) {
  const unnamed = Math.max(0, booking.units - booking.participants.length);
  return (
    <section className="manifest-booking">
      <header>
        <Link to={`/app/bookings?booking=${encodeURIComponent(booking.id)}`} className="manifest-lead">
          <UserRound size={16} aria-hidden="true" />
          <span><strong>{booking.lead_name}</strong><span>Lead booker · {booking.public_reference} · {booking.units} {booking.units === 1 ? "unit" : "units"}</span></span>
        </Link>
        {booking.lead_phone && <a className="icon-button manifest-call" href={`tel:${booking.lead_phone}`} aria-label={`Call ${booking.lead_name}`}><Phone size={16} /></a>}
      </header>
      <div className="manifest-tags">
        <span className={`status-pill ${booking.status}`}>{booking.status.replaceAll("_", " ")}</span>
        <span className="manifest-tag">{paymentLabel(booking.payment_method, booking.payment_status)}</span>
        <span className={`manifest-tag ${booking.waiver_status === "signed" ? "ok" : booking.waiver_status === "pending" ? "warn" : ""}`}><FileCheck2 size={12} aria-hidden="true" />{WAIVER_LABEL[booking.waiver_status]}</span>
      </div>
      {booking.participants.length > 0 && (
        <ul className="manifest-people">
          {booking.participants.map((participant) => (
            <ParticipantRow key={participant.id} participant={participant} busy={busyId === participant.id} onToggle={(checkedIn) => onToggle(participant, checkedIn)} />
          ))}
        </ul>
      )}
      {unnamed > 0 && <p className="departure-note">{unnamed} {unnamed === 1 ? "guest has" : "guests have"} not been named yet. Add attendees from the booking.</p>}
    </section>
  );
}

function WeatherClosure({ calendarId, startAt, timeZone, onClosed }: { calendarId: string; startAt: string; timeZone: string; onClosed: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("Unsafe weather");
  const [mode, setMode] = useState<WeatherRefundMode | null>(null);
  const params = new URLSearchParams({ calendar_id: calendarId, start_at: startAt });
  const preview = useQuery({
    queryKey: ["closure-preview", calendarId, startAt],
    queryFn: () => api<PwaClosurePreview>(`/pwa/departures/closure-preview?${params}`),
    enabled: open,
    staleTime: 0,
  });
  const refundMode = mode ?? preview.data?.default_refund_mode ?? "full_refund";
  const close = useMutation({
    mutationFn: () => api<PwaCloseDepartureResponse>("/pwa/departures/close", json("POST", {
      calendar_id: calendarId,
      start_at: startAt,
      reason,
      refund_mode: refundMode,
      expected_bookings: preview.data?.manifest.bookings.length ?? 0,
    })),
    onSuccess: (result) => { if (!result.failed.length) onClosed(); },
  });
  const bookings = preview.data?.manifest.bookings || [];
  const paid = bookings.filter((booking) => booking.payment_status === "succeeded").length;
  return (
    <>
      <button className="button secondary danger-outline" type="button" onClick={() => { setOpen(true); close.reset(); }}><CloudLightning size={16} aria-hidden="true" />Close for weather</button>
      <Modal open={open} onOpenChange={setOpen} title="Close this departure for weather" description={`${formatDay(startAt, timeZone)} at ${formatTime(startAt, timeZone)}. New bookings for this time will be blocked.`}>
        {preview.isLoading && <div className="loading">Checking who is affected…</div>}
        {preview.error && <div className="error-banner">{preview.error.message}</div>}
        {preview.data && (
          <div className="closure-preview">
            {preview.data.already_closed && <div className="notice">This departure was already closed. Confirming again retries only the bookings that are still active; completed refunds and messages are not repeated.</div>}
            <dl className="detail-list">
              <dt>Bookings to cancel</dt><dd>{bookings.length}</dd>
              <dt>Guests</dt><dd>{preview.data.manifest.expected_units}</dd>
              <dt>Paid bookings</dt><dd>{paid}</dd>
              <dt>Staff assigned</dt><dd>{preview.data.manifest.staff.map((member) => member.staff_name).join(", ") || "None"}</dd>
            </dl>
            {bookings.length > 0 && <ul className="closure-list">{bookings.map((booking) => <li key={booking.id}><strong>{booking.lead_name}</strong><span>{booking.units} · {paymentLabel(booking.payment_method, booking.payment_status)} · {WAIVER_LABEL[booking.waiver_status]}</span></li>)}</ul>}
            <label className="field"><span>Refund for paid bookings</span><select value={refundMode} onChange={(event) => setMode(event.target.value as WeatherRefundMode)}>{REFUND_MODES.map((item) => <option key={item.value} value={item.value}>{item.label}{item.value === preview.data!.default_refund_mode ? " (calendar policy)" : ""}</option>)}</select></label>
            <label className="field"><span>Reason (recorded and shared with guests)</span><input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} /></label>
            {close.error && <div className="error-banner">{close.error.message}</div>}
            {close.data && close.data.failed.length > 0 && (
              <div className="error-banner">
                {close.data.cancelled_bookings} cancelled. {close.data.failed.length} could not be processed and are still active. Confirm again to retry them; nothing already done will be repeated.
              </div>
            )}
            <div className="dialog-actions">
              <button className="button secondary" type="button" onClick={() => setOpen(false)}>Keep departure</button>
              <button className="button danger" type="button" disabled={close.isPending || reason.trim().length < 3} onClick={() => close.mutate()}>
                {close.isPending ? "Closing…" : `Cancel ${bookings.length} ${bookings.length === 1 ? "booking" : "bookings"} and close`}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

export function ManifestPage() {
  const [params] = useSearchParams();
  const calendarId = params.get("calendar_id") || "";
  const startAt = params.get("start_at") || "";
  const client = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);
  const manifest = useQuery({
    queryKey: ["pwa-manifest", calendarId, startAt],
    queryFn: () => api<PwaManifestResponse>(`/pwa/manifest?${new URLSearchParams({ calendar_id: calendarId, start_at: startAt })}`),
    enabled: Boolean(calendarId && startAt),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
  const isAdmin = useHasPermission("manage_configuration");
  const checkIn = useMutation({
    mutationFn: ({ participant, checkedIn }: { participant: PwaManifestParticipant; checkedIn: boolean }) =>
      api<PwaManifestParticipant>(`/pwa/participants/${participant.id}/check-in`, json("POST", { checked_in: checkedIn })),
    onMutate: ({ participant }) => setBusyId(participant.id),
    onSettled: async () => { setBusyId(null); await client.invalidateQueries({ queryKey: ["pwa-manifest", calendarId, startAt] }); },
  });
  const data = manifest.data;
  const timeZone = data?.time_zone || "UTC";

  if (!calendarId || !startAt) return <main className="page departures-page"><EmptyState title="Choose a departure" copy="Open a manifest from the Departures board." /></main>;

  return (
    <main className="page departures-page">
      <Link className="manifest-back" to="/app/departures"><ArrowLeft size={16} aria-hidden="true" />Departures</Link>
      {manifest.isLoading && <div className="dashboard-state loading" role="status"><div className="spinner" /><span>Loading manifest…</span></div>}
      {manifest.error && (
        <section className="dashboard-state error-banner" role="alert">
          <XCircle size={20} aria-hidden="true" />
          <div><strong>Manifest unavailable</strong><span>{manifest.error.message}</span></div>
          <button className="button secondary" type="button" onClick={() => void manifest.refetch()}><RefreshCw size={16} aria-hidden="true" />Try again</button>
        </section>
      )}
      {data && (
        <>
          <header className="departures-header">
            <div>
              <h1>{data.calendar_name}</h1>
              <p>{formatDay(data.start_at, timeZone)} · {formatTime(data.start_at, timeZone)}–{formatTime(data.end_at, timeZone)}</p>
            </div>
            {isAdmin && data.bookings.length > 0 && <WeatherClosure calendarId={data.calendar_id} startAt={data.start_at} timeZone={timeZone} onClosed={() => void manifest.refetch()} />}
          </header>
          <section className="manifest-summary" aria-label="Manifest totals">
            <div><span>Guests booked</span><strong>{data.expected_units}</strong></div>
            <div><span>Named</span><strong>{data.named_participants}</strong></div>
            <div><span>Checked in</span><strong>{data.checked_in}</strong></div>
          </section>
          <div className="departure-staff"><Users size={15} aria-hidden="true" />{data.staff.length ? <span>{data.staff.map((member) => member.role ? `${member.staff_name} (${member.role})` : member.staff_name).join(", ")}</span> : <span className="missing">No staff assigned</span>}</div>
          {checkIn.error && <div className="error-banner">{checkIn.error.message}</div>}
          {data.bookings.length ? (
            <div className="departure-list">
              {data.bookings.map((booking) => <BookingBlock key={booking.id} booking={booking} busyId={busyId} onToggle={(participant, checkedIn) => checkIn.mutate({ participant, checkedIn })} />)}
            </div>
          ) : <EmptyState title="No guests" copy="There are no active bookings on this departure." />}
        </>
      )}
    </main>
  );
}
