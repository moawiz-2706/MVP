import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin, { type DateClickArg } from "@fullcalendar/interaction";
// FullCalendar only honours a named timeZone (e.g. America/New_York) with a
// time-zone plugin; without one it silently renders in UTC.
import luxonPlugin from "@fullcalendar/luxon3";
import type { DatesSetArg, EventClickArg, EventContentArg } from "@fullcalendar/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarPlus, Check, ChevronRight, Copy, ExternalLink, Search, Settings2, Trash2, UserPlus, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { api, json } from "../api/client";
import type { Booking, BookingDetail, BookingNote, BookingNotificationsResponse, Calendar, Category, DashboardSlot, SlotCalendar, StaffAssignment, StaffCandidate } from "../api/types";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { useSession } from "../auth/GHLSessionProvider";
import { formatLongDate, formatTime, zoneLabel, zonedWallTimeToISO } from "../lib/datetime";
import { PaymentPanel } from "../public-booking/PaymentPanel";

function money(value: number, currency = "usd") { return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(value / 100); }
function badge(status: string) { return status === "confirmed" || status === "succeeded" || status === "synced" || status === "sent" ? "success" : status.includes("fail") || status === "cancelled" ? "danger" : "warning"; }

const STATUSES: [string, string][] = [["confirmed", "Confirmed"], ["pending_payment", "Pending payment"], ["cancelled", "Cancelled"], ["completed", "Completed"], ["no_show", "No show"], ["failed", "Failed"]];
const ROLE_SUGGESTIONS = ["Captain", "First Mate", "Guide", "Deckhand", "Instructor"];
const holdsSeat = (booking: Booking) => booking.status !== "cancelled" && booking.status !== "failed";
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;
const localDateTime = (iso: string, timeZone: string) => {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date(iso));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}T${values.hour === "24" ? "00" : values.hour}:${values.minute}`;
};

const ADMIN_ROLES = ["admin", "administrator", "agency_admin"];

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    // Clipboard access can be blocked inside the HighLevel iframe; fall back.
    const field = document.createElement("textarea");
    field.value = value;
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    document.execCommand("copy");
    field.remove();
  }
}

function WaiverStatus({ waiver }: { waiver: BookingDetail["waiver"] }) {
  const [copied, setCopied] = useState(false);
  if (waiver.status === "signed" && waiver.url) {
    return <span className="waiver-status"><span className="badge success">Signed</span><button className="button ghost small" onClick={() => window.open(waiver.url!, "_blank", "noopener")}><ExternalLink size={14} />View</button></span>;
  }
  if (waiver.status === "pending" && waiver.url) {
    return <span className="waiver-status"><span className="badge warning">Not signed</span><button className="button ghost small" onClick={async () => { await copyText(waiver.url!); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy link"}</button></span>;
  }
  if (waiver.status === "not_set_up") {
    return <span className="waiver-status"><span className="badge">Not signed</span><span style={{ color: "#697386", fontWeight: 400 }}>Add waiver text in Settings</span></span>;
  }
  return <span className="badge">Not signed</span>;
}

function NotesSection({ bookingId, notes }: { bookingId: string; notes: BookingNote[] }) {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const client = useQueryClient();
  const [body, setBody] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["booking", bookingId] });
  const add = useMutation({ mutationFn: () => api<BookingNote>(`/bookings/${bookingId}/notes`, json("POST", { body: body.trim() })), onSuccess: async () => { setBody(""); await refresh(); } });
  const remove = useMutation({ mutationFn: (noteId: string) => api<void>(`/bookings/${bookingId}/notes/${noteId}`, { method: "DELETE" }), onSuccess: refresh });
  const isAdmin = me.user.is_agency_owner || ADMIN_ROLES.includes(me.user.role.toLowerCase());
  const error = add.error || remove.error;
  return (
    <div className="detail-section">
      <h3>Notes</h3>
      {notes.length ? (
        <div className="notes-list">
          {notes.map((note) => (
            <div key={note.id} className="note">
              <p>{note.body}</p>
              <div className="note-meta">
                <span>{note.author_name || "Team member"} · {formatLongDate(note.created_at, tz)}, {formatTime(note.created_at, tz)}</span>
                {(note.author_user_id === me.user.id || isAdmin) && <button className="icon-button" aria-label="Delete note" disabled={remove.isPending} onClick={() => remove.mutate(note.id)}><Trash2 size={13} /></button>}
              </div>
            </div>
          ))}
        </div>
      ) : <p className="muted-note" style={{ marginBottom: 8 }}>No notes yet.</p>}
      <form className="note-form" onSubmit={(e: FormEvent) => { e.preventDefault(); if (body.trim()) add.mutate(); }}>
        <textarea className="control" rows={3} maxLength={5000} placeholder="Add a note for your team..." value={body} onChange={(e) => setBody(e.target.value)} />
        <button className="button small" disabled={!body.trim() || add.isPending}>{add.isPending ? "Saving..." : "Add note"}</button>
      </form>
      {error && <div className="error-banner" style={{ marginTop: 8 }}>{error.message}</div>}
    </div>
  );
}

function BookingDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const client = useQueryClient();
  // Always refetch on open: a customer may have just signed the waiver elsewhere.
  const { data, isLoading } = useQuery({ queryKey: ["booking", id], queryFn: () => api<BookingDetail>(`/bookings/${id}`), staleTime: 0 });
  const [editStart, setEditStart] = useState("");
  const [editUnits, setEditUnits] = useState(1);
  const [editing, setEditing] = useState(false);
  const edit = useMutation({
    mutationFn: () => api<BookingDetail>(`/bookings/${id}`, json("PATCH", { start_at: editStart ? zonedWallTimeToISO(editStart, tz) : undefined, units: editUnits })),
    onSuccess: async () => { setEditing(false); await Promise.all([client.invalidateQueries({ queryKey: ["booking", id] }), client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking-notifications"] })]); },
  });
  const cancel = useMutation({ mutationFn: () => api<void>(`/bookings/${id}/cancel`, { method: "POST" }), onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking", id] }), client.invalidateQueries({ queryKey: ["booking-notifications"] })]); } });
  const retry = useMutation({ mutationFn: () => api<void>(`/orders/${data?.booking_order_id}/retry-ghl-sync`, { method: "POST" }), onSuccess: () => client.invalidateQueries({ queryKey: ["booking", id] }) });
  return (
    <>
      <button className="drawer-overlay" onClick={onClose} aria-label="Close booking details" />
      <aside className="drawer" aria-label="Booking details">
        {isLoading || !data ? <div className="loading">Loading booking...</div> : (
          <>
            <div className="drawer-header"><div><h2>{data.customer_name}</h2><p>{data.public_reference}</p></div><button className="icon-button" onClick={onClose}><X size={18} /></button></div>
            <div className="detail-section">
              <h3>Booking</h3>
              {editing ? <form className="edit-booking-form" onSubmit={(event) => { event.preventDefault(); edit.mutate(); }}><label className="field"><span>Date and time ({zoneLabel(tz)})</span><input type="datetime-local" required value={editStart || localDateTime(data.start_at, tz)} onChange={(event) => setEditStart(event.target.value)} /></label><label className="field"><span>Quantity</span><input type="number" min={1} required value={editUnits} onChange={(event) => setEditUnits(Number(event.target.value))} /></label><div className="toolbar"><button type="button" className="button ghost small" onClick={() => setEditing(false)}>Cancel</button><button className="button small" disabled={edit.isPending}>{edit.isPending ? "Checking…" : "Save changes"}</button></div></form> : <div className="toolbar" style={{ marginBottom: 12 }}><button className="button secondary small" disabled={!(["pending_payment", "confirmed"].includes(data.status))} onClick={() => { setEditStart(localDateTime(data.start_at, tz)); setEditUnits(data.units); setEditing(true); }}>Edit time or quantity</button></div>}
              {edit.error && <div className="error-banner">{edit.error.message}</div>}
              <dl className="detail-list">
                <dt>Status</dt><dd><span className={`badge ${badge(data.status)}`}>{data.status.replaceAll("_", " ")}</span></dd>
                <dt>Waiver</dt><dd><WaiverStatus waiver={data.waiver} /></dd>
                <dt>Calendar</dt><dd>{data.calendar_name}</dd>
                <dt>Date</dt><dd>{formatLongDate(data.start_at, tz)}</dd>
                <dt>Time</dt><dd>{formatTime(data.start_at, tz)} – {formatTime(data.end_at, tz)} ({zoneLabel(tz)})</dd>
                <dt>Quantity</dt><dd>{data.units}</dd>
                <dt>Location</dt><dd>{data.location_name || "Not assigned"}{data.location_address && <><br /><span style={{ color: "#697386", fontWeight: 400 }}>{data.location_address}</span></>}</dd>
              </dl>
            </div>
            <NotesSection bookingId={data.id} notes={data.notes} />
            <div className="detail-section"><h3>Customer</h3><dl className="detail-list"><dt>Email</dt><dd>{data.customer_email}</dd><dt>Phone</dt><dd>{data.customer_phone || "—"}</dd></dl></div>
            <div className="detail-section"><h3>Resources</h3><dl className="detail-list">{data.resources.length ? data.resources.map((resource) => <span style={{ display: "contents" }} key={resource.resource_id}><dt>{resource.name}</dt><dd>{resource.quantity}</dd></span>) : <><dt>Inventory</dt><dd>No mapped resources</dd></>}</dl></div>
            <div className="detail-section"><h3>Payment</h3><dl className="detail-list"><dt>Status</dt><dd><span className={`badge ${badge(data.payment_status)}`}>{data.payment_status}</span></dd><dt>Subtotal</dt><dd>{money(data.subtotal_minor)}</dd><dt>Platform Fee &amp; Taxes</dt><dd>{money(data.platform_fee_and_taxes_minor)}</dd><dt>Total</dt><dd>{money(data.customer_total_minor)}</dd></dl></div>
            <div className="detail-section"><h3>GoHighLevel</h3><dl className="detail-list"><dt>Contact sync</dt><dd>{data.ghl_contact_sync_status}</dd><dt>Confirmation</dt><dd>{data.ghl_confirmation_email_status}</dd><dt>Appointment sync</dt><dd>{data.ghl_appointment_sync_status}{data.ghl_appointment_event_id && <><br /><span style={{ color: "#697386", fontWeight: 400 }}>Event: {data.ghl_appointment_event_id}</span></>}{data.ghl_appointment_last_error && <><br /><span style={{ color: "#9b2822", fontWeight: 400 }}>{data.ghl_appointment_last_error}</span></>}</dd></dl></div>
            {retry.error && <div className="error-banner">{retry.error.message}</div>}
            {retry.isSuccess && <div className="success-banner">GHL synchronization retry queued.</div>}
            <div className="toolbar"><button className="button secondary" disabled={data.status === "cancelled" || cancel.isPending} onClick={() => cancel.mutate()}>Cancel booking</button>{(data.ghl_contact_sync_status === "failed" || data.ghl_confirmation_email_status === "failed" || data.ghl_appointment_sync_status === "failed" || data.ghl_appointment_sync_status === "dead") && <button className="button secondary" disabled={retry.isPending} onClick={() => retry.mutate()}>{retry.isPending ? "Retrying…" : "Retry GHL sync"}</button>}</div>
          </>
        )}
      </aside>
    </>
  );
}

interface CreatedOrder { public_reference: string; status: string; client_secret: string | null }
function NewBookingForm({ calendars, onDone }: { calendars: Calendar[]; onDone: () => void }) {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const client = useQueryClient();
  const [calendarId, setCalendarId] = useState(calendars[0]?.id || "");
  const [start, setStart] = useState(""); const [units, setUnits] = useState(1);
  const [first, setFirst] = useState(""); const [last, setLast] = useState(""); const [email, setEmail] = useState(""); const [phone, setPhone] = useState("");
  const [created, setCreated] = useState<CreatedOrder | null>(null);
  const mutation = useMutation({ mutationFn: () => api<CreatedOrder>("/bookings", json("POST", { items: [{ calendar_id: calendarId, start_at: zonedWallTimeToISO(start, tz), units }], customer: { first_name: first, last_name: last, email, phone: phone || null } })), onSuccess: async (result) => { setCreated(result); await Promise.all([client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking-notifications"] })]); if (!result.client_secret) onDone(); } });
  if (created?.client_secret) return <div><p style={{fontSize:12,color:"#697386",marginTop:0}}>Inventory is held while the customer payment is completed.</p><PaymentPanel clientSecret={created.client_secret} publicReference={created.public_reference} /></div>;
  return <form onSubmit={(e: FormEvent) => { e.preventDefault(); mutation.mutate(); }}><p className="muted-note" style={{ marginTop: 0, marginBottom: 12 }}>Bookable times appear only after an active Captain covers the full interval. Configure a slot from the calendar if no times are available.</p><div className="form-grid"><label className="field full"><span>Calendar</span><select required value={calendarId} onChange={(e) => setCalendarId(e.target.value)}>{calendars.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.name}</option>)}</select></label><label className="field"><span>Date and time</span><input type="datetime-local" required value={start} onChange={(e) => setStart(e.target.value)} /></label><label className="field"><span>Quantity</span><input type="number" min={1} required value={units} onChange={(e) => setUnits(Number(e.target.value))} /></label><label className="field"><span>First name</span><input required value={first} onChange={(e) => setFirst(e.target.value)} /></label><label className="field"><span>Last name</span><input required value={last} onChange={(e) => setLast(e.target.value)} /></label><label className="field"><span>Email</span><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label><label className="field"><span>Phone (optional)</span><input value={phone} onChange={(e) => setPhone(e.target.value)} /></label></div>{mutation.error && <div className="error-banner" style={{marginTop:12}}>{mutation.error.message}</div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={mutation.isPending || !calendarId}>{mutation.isPending ? "Checking availability…" : "Create booking"}</button></div></form>;
}

/** Step 1 of the slot popup: every calendar running at this start time. */
function SlotCalendarList({ slot, onPick }: { slot: DashboardSlot; onPick: (calendarId: string) => void }) {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  return (
    <div className="slot-list">
      {slot.calendars.map((entry) => {
        const seated = entry.bookings.filter(holdsSeat);
        const units = seated.reduce((total, booking) => total + booking.units, 0);
        const parts = [`${formatTime(slot.start_at, tz)} – ${formatTime(entry.end_at, tz)}`, entry.bookings.length ? `${plural(seated.length, "booking")} · ${plural(units, "unit")}` : "Open, no bookings yet"];
        if (entry.staff.length) parts.push(`${entry.staff.length} staff`);
        return (
          <button key={entry.calendar_id} className="slot-row" onClick={() => onPick(entry.calendar_id)}>
            <i className="filter-dot" style={{ background: entry.category_color || "#7b8792" }} />
            <div className="cell-title"><strong>{entry.calendar_name}</strong><span>{parts.join(" · ")}</span></div>
            <ChevronRight size={15} />
          </button>
        );
      })}
    </div>
  );
}

/** Step 2: one calendar's bookings (filterable by status) and its staff. */
function SlotCalendarDetail({ entry, startAt, onBack, onOpenBooking }: { entry: SlotCalendar; startAt: string; onBack: () => void; onOpenBooking: (id: string) => void }) {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const client = useQueryClient();
  const [status, setStatus] = useState("");
  const [staffId, setStaffId] = useState("");
  const [role, setRole] = useState("");
  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    for (const booking of entry.bookings) tally[booking.status] = (tally[booking.status] || 0) + 1;
    return tally;
  }, [entry.bookings]);
  const visible = status ? entry.bookings.filter((booking) => booking.status === status) : entry.bookings;

  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking-notifications"] }), client.invalidateQueries({ queryKey: ["staff-candidates"] }), client.invalidateQueries({ queryKey: ["staff"] })]);
  const candidates = useQuery({ queryKey: ["staff-candidates", entry.calendar_id, startAt], queryFn: () => api<StaffCandidate[]>(`/staff-assignments/candidates?${new URLSearchParams({ calendar_id: entry.calendar_id, start_at: startAt })}`) });
  const assign = useMutation({ mutationFn: () => api<StaffAssignment>("/staff-assignments", json("POST", { staff_id: staffId, calendar_id: entry.calendar_id, start_at: startAt, role: role.trim() || null })), onSuccess: async () => { setStaffId(""); setRole(""); await refresh(); } });
  const unassign = useMutation({ mutationFn: (id: string) => api<void>(`/staff-assignments/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const rename = useMutation({ mutationFn: ({ id, value }: { id: string; value: string }) => api<StaffAssignment>(`/staff-assignments/${id}`, json("PATCH", { role: value || null })), onSuccess: refresh });
  const reassign = useMutation({ mutationFn: ({ id, staffId, role }: { id: string; staffId: string; role: string | null }) => api<StaffAssignment>(`/staff-assignments/${id}`, json("PATCH", { staff_id: staffId, role })), onSuccess: refresh });
  const assigned = new Set(entry.staff.map((member) => member.staff_id));
  const options = (candidates.data || []).filter((candidate) => !assigned.has(candidate.staff_id));
  const staffError = assign.error || unassign.error || rename.error;

  return (
    <>
      <button className="button ghost small" style={{ paddingLeft: 0 }} onClick={onBack}><ArrowLeft size={14} />All calendars</button>
      <div className="slot-detail-head">
        <i className="filter-dot" style={{ background: entry.category_color || "#7b8792", width: 10, height: 10 }} />
        <div><strong>{entry.calendar_name}</strong><span>{formatTime(startAt, tz)} – {formatTime(entry.end_at, tz)} ({zoneLabel(tz)})</span></div>
      </div>

      <div className="detail-section">
        <h3>Bookings</h3>
        <div className="status-chips" role="group" aria-label="Filter by status">
          <button className={`chip ${status === "" ? "active" : ""}`} onClick={() => setStatus("")}>All <span>{entry.bookings.length}</span></button>
          {STATUSES.filter(([value]) => value !== "failed" || counts[value]).map(([value, label]) => (
            <button key={value} className={`chip ${status === value ? "active" : ""}`} onClick={() => setStatus(value)}>{label} <span>{counts[value] || 0}</span></button>
          ))}
        </div>
        {visible.length ? (
          <div className="slot-list">
            {visible.map((booking) => (
              <button key={booking.id} className="slot-row" onClick={() => onOpenBooking(booking.id)}>
                <div className="cell-title"><strong>{booking.customer_name}</strong><span>{booking.public_reference} · {plural(booking.units, "unit")}</span></div>
                <span className={`badge ${badge(booking.status)}`}>{booking.status.replaceAll("_", " ")}</span>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
        ) : <p className="muted-note">{entry.bookings.length ? "No bookings with this status." : entry.pushed ? "This pushed time is open — no bookings yet." : "No bookings."}</p>}
      </div>

      <div className="detail-section" style={{ marginBottom: 0 }}>
        <h3>Staff</h3>
        {entry.staff.length ? (
          <div className="slot-list">
            {entry.staff.map((member) => (
              <div key={member.id} className="staff-row staff-row-assignment">
                <strong>{member.staff_name}</strong>
                <select className="control" aria-label={`Captain for ${member.staff_name}`} value={member.staff_id} disabled={reassign.isPending} onChange={(e) => reassign.mutate({ id: member.id, staffId: e.target.value, role: member.role })}>{(candidates.data || []).map((candidate) => <option key={candidate.staff_id} value={candidate.staff_id} disabled={!candidate.available && candidate.staff_id !== member.staff_id}>{candidate.available ? candidate.name : `${candidate.name} — unavailable`}</option>)}</select><input key={`${member.id}-${member.role ?? ""}`} className="control" aria-label={`Role for ${member.staff_name}`} defaultValue={member.role || ""} placeholder="Role" list="staff-roles" maxLength={80} onBlur={(e) => { const value = e.target.value.trim(); if (value !== (member.role || "")) rename.mutate({ id: member.id, value }); }} />
                <button className="icon-button" aria-label={`Remove ${member.staff_name}`} disabled={unassign.isPending} onClick={() => unassign.mutate(member.id)}><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        ) : <p className="muted-note">No staff assigned to this time slot.</p>}
        <form className="assign-form" onSubmit={(e) => { e.preventDefault(); assign.mutate(); }}>
          <select className="control" required value={staffId} onChange={(e) => setStaffId(e.target.value)} aria-label="Staff member">
            <option value="">{candidates.isLoading ? "Loading staff…" : options.length ? "Choose staff" : "No staff to add"}</option>
            {options.map((candidate) => <option key={candidate.staff_id} value={candidate.staff_id} disabled={!candidate.available}>{candidate.available ? candidate.name : `${candidate.name} — ${(candidate.reason || "unavailable").replace(`${candidate.name} `, "").replace(/^is /, "")}`}</option>)}
          </select>
          <input className="control" placeholder="Role (e.g. Captain)" aria-label="Role" list="staff-roles" maxLength={80} value={role} onChange={(e) => setRole(e.target.value)} />
          <button className="button" disabled={!staffId || assign.isPending}><UserPlus size={15} />{assign.isPending ? "Assigning…" : "Assign"}</button>
        </form>
        <datalist id="staff-roles">{ROLE_SUGGESTIONS.map((suggestion) => <option key={suggestion} value={suggestion} />)}</datalist>
        {candidates.data?.length === 0 && <p className="muted-note">Add people on the Staff page to assign them here.</p>}
        {staffError && <div className="error-banner" style={{ marginTop: 10, marginBottom: 0 }}>{staffError.message}</div>}
      </div>
    </>
  );
}

function ConfigureSlotForm({ calendars, initialStart, onDone }: { calendars: Calendar[]; initialStart?: string; onDone: () => void }) {
  const client = useQueryClient();
  const { me } = useSession();
  const [calendarId, setCalendarId] = useState(calendars[0]?.id || "");
  const [start, setStart] = useState(initialStart ? localDateTime(initialStart, me.operator.time_zone) : "");
  const [staffId, setStaffId] = useState("");
  const [role, setRole] = useState("Captain");
  const candidates = useQuery({ queryKey: ["staff-candidates", calendarId, start], queryFn: () => api<StaffCandidate[]>(`/staff-assignments/candidates?${new URLSearchParams({ calendar_id: calendarId, start_at: zonedWallTimeToISO(start, me.operator.time_zone) })}`), enabled: Boolean(calendarId && start) });
  const assign = useMutation({ mutationFn: () => api<StaffAssignment>("/staff-assignments", json("POST", { staff_id: staffId, calendar_id: calendarId, start_at: zonedWallTimeToISO(start, me.operator.time_zone), role: role.trim() || null })), onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking-notifications"] }), client.invalidateQueries({ queryKey: ["staff-candidates"] })]); onDone(); } });
  const options = (candidates.data || []).filter((candidate) => candidate.available);
  return <form onSubmit={(event) => { event.preventDefault(); assign.mutate(); }}><p className="muted-note" style={{ marginTop: 0 }}>Assign a Captain before a booking exists. This creates the local staffing coverage that makes the interval bookable.</p><div className="form-grid"><label className="field full"><span>Calendar</span><select required value={calendarId} onChange={(event) => { setCalendarId(event.target.value); setStaffId(""); }}><option value="">Choose a calendar</option>{calendars.map((calendar) => <option key={calendar.id} value={calendar.id}>{calendar.name}</option>)}</select></label><label className="field full"><span>Slot start ({zoneLabel(me.operator.time_zone)})</span><input type="datetime-local" required value={start} onChange={(event) => { setStart(event.target.value); setStaffId(""); }} /></label><label className="field"><span>Captain</span><select required value={staffId} onChange={(event) => setStaffId(event.target.value)} disabled={!start || candidates.isLoading}><option value="">{candidates.isLoading ? "Checking availability…" : options.length ? "Choose Captain" : "No available Captain"}</option>{options.map((candidate) => <option key={candidate.staff_id} value={candidate.staff_id}>{candidate.name}</option>)}</select></label><label className="field"><span>Role</span><input required value={role} onChange={(event) => setRole(event.target.value)} maxLength={80} /></label></div>{candidates.error && <div className="error-banner" style={{ marginTop: 12 }}>{candidates.error.message}</div>}{assign.error && <div className="error-banner" style={{ marginTop: 12 }}>{assign.error.message}</div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={!staffId || assign.isPending}>{assign.isPending ? "Assigning…" : "Configure slot"}</button></div></form>;
}

export function BookingsPage() {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const location = useLocation();
  const now = new Date(); const [range, setRange] = useState({ start: new Date(now.getFullYear(), now.getMonth(), 1).toISOString(), end: new Date(now.getFullYear(), now.getMonth() + 1, 8).toISOString() });
  const [filter, setFilter] = useState<{type:"all"|"category"|"calendar"; id?:string}>({type:"all"}); const [search, setSearch] = useState(""); const [selected, setSelected] = useState<string | null>(null); const [creating, setCreating] = useState(false); const [configuring, setConfiguring] = useState<string | null>(null);
  const [open, setOpen] = useState<{ start: string; calendarId: string | null } | null>(null);
  const calendars = useQuery({ queryKey:["calendars"], queryFn:() => api<Calendar[]>("/calendars?is_active=true") });
  const categories = useQuery({ queryKey:["categories"], queryFn:() => api<Category[]>("/calendar-categories") });
  const params = new URLSearchParams({ range_start: range.start, range_end: range.end }); if (filter.type === "calendar" && filter.id) params.set("calendar_id", filter.id); if (filter.type === "category" && filter.id) params.set("category_id", filter.id); if (search.trim()) params.set("search", search.trim());
  const slots = useQuery({ queryKey:["bookings","slots",params.toString()], queryFn:() => api<DashboardSlot[]>(`/booking-slots?${params}`), refetchInterval:45_000 });
  const notifications = useQuery({ queryKey: ["booking-notifications"], queryFn: () => api<BookingNotificationsResponse>("/booking-notifications"), refetchInterval: 45_000 });
  useEffect(() => { const bookingId = new URLSearchParams(location.search).get("booking"); if (bookingId) setSelected(bookingId); }, [location.search]);
  // One neutral entry per start time; calendars and bookings live behind the click.
  const eventData = useMemo(() => (slots.data || []).map((slot) => {
    const end = slot.calendars.reduce((latest, entry) => entry.end_at > latest ? entry.end_at : latest, slot.start_at);
    return { id: slot.start_at, start: slot.start_at, end, backgroundColor: "#527a7318", borderColor: "#527a73", textColor: "#26323c", extendedProps: { slot } };
  }), [slots.data]);
  const eventContent = (arg: EventContentArg) => {
    const slot = arg.event.extendedProps.slot as DashboardSlot;
    const seated = slot.calendars.flatMap((entry) => entry.bookings).filter(holdsSeat).length;
    return <div className="event-compact" title={`${plural(slot.calendars.length, "calendar")} · ${plural(seated, "booking")}`}><time>{formatTime(slot.start_at, tz)}</time></div>;
  };
  const openSlot = open ? slots.data?.find((slot) => slot.start_at === open.start) : undefined;
  const openEntry = open?.calendarId ? openSlot?.calendars.find((entry) => entry.calendar_id === open.calendarId) : undefined;
  return <div className="page"><PageHeader title="Bookings" description="Every time slot across your calendars. Click a time to see its calendars, bookings, and staff." action={<button className="button" onClick={() => setCreating(true)}><CalendarPlus size={16}/>New booking</button>} /><div className="booking-layout"><aside className="card filter-panel"><h3>Calendar filters</h3><div className="filter-list"><button className={`filter-button ${filter.type === "all" ? "active" : ""}`} onClick={() => setFilter({type:"all"})}>All calendars</button>{(categories.data || []).map((category) => <div key={category.id}><button className={`filter-button ${filter.type === "category" && filter.id === category.id ? "active" : ""}`} onClick={() => setFilter({type:"category",id:category.id})}><i className="filter-dot" style={{background:category.display_color || "#7b8792"}} />{category.name}</button>{(calendars.data || []).filter((c) => c.calendar_category_id === category.id).map((calendar) => <button key={calendar.id} className={`filter-button filter-calendar ${filter.type === "calendar" && filter.id === calendar.id ? "active" : ""}`} onClick={() => setFilter({type:"calendar",id:calendar.id})}>{calendar.name}</button>)}</div>)}{(calendars.data || []).filter(c => !c.calendar_category_id).map(calendar => <button key={calendar.id} className={`filter-button ${filter.type === "calendar" && filter.id === calendar.id ? "active" : ""}`} onClick={() => setFilter({type:"calendar",id:calendar.id})}>{calendar.name}</button>)}</div></aside><section className="card calendar-card"><div className="calendar-toolbar"><div style={{position:"relative",flex:"1 1 180px",maxWidth:260}}><Search size={14} style={{position:"absolute",left:10,top:11,color:"#8a94a1"}}/><input className="control" style={{paddingLeft:31}} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search customer or reference" /></div><button className="button secondary small" onClick={() => setConfiguring("")}><Settings2 size={14} />Configure slot</button>{notifications.data?.pending_count ? <span className="badge warning">{notifications.data.pending_count} need Captain</span> : null}</div>{slots.error && <div className="error-banner">{slots.error.message}</div>}<FullCalendar timeZone={tz} plugins={[dayGridPlugin,timeGridPlugin,interactionPlugin,luxonPlugin]} initialView="dayGridMonth" headerToolbar={{left:"prev,next today",center:"title",right:"dayGridMonth,timeGridWeek,timeGridDay"}} buttonText={{month:"Month",week:"Week",day:"Day",today:"Today"}} events={eventData} eventContent={eventContent} eventClick={(arg:EventClickArg) => setOpen({ start: arg.event.id, calendarId: null })} dateClick={(arg: DateClickArg) => setConfiguring(arg.date.toISOString())} datesSet={(arg:DatesSetArg) => setRange({start:arg.start.toISOString(),end:arg.end.toISOString()})} dayMaxEventRows={3} height="auto" nowIndicator slotMinTime="06:00:00" slotMaxTime="22:00:00" /></section></div>{selected && <BookingDrawer id={selected} onClose={() => setSelected(null)} />}<Modal open={!!open && !selected} onOpenChange={(isOpen) => !isOpen && setOpen(null)} title={open ? `${formatLongDate(open.start, tz)} · ${formatTime(open.start, tz)}` : ""} description={`Times shown in ${zoneLabel(tz)}. ${openEntry ? "Choose a status to filter bookings." : "Choose a calendar to see its bookings and staff."}`}>{!openSlot ? <p className="muted-note">Nothing is scheduled at this time any more.</p> : openEntry ? <SlotCalendarDetail key={openEntry.calendar_id} entry={openEntry} startAt={openSlot.start_at} onBack={() => setOpen({ start: openSlot.start_at, calendarId: null })} onOpenBooking={setSelected} /> : <SlotCalendarList slot={openSlot} onPick={(calendarId) => setOpen({ start: openSlot.start_at, calendarId })} />}</Modal><Modal open={creating} onOpenChange={setCreating} title="New booking" description="Availability and pricing are revalidated by the booking engine."><NewBookingForm calendars={calendars.data || []} onDone={() => setCreating(false)} /></Modal><Modal open={configuring !== null} onOpenChange={(open) => !open && setConfiguring(null)} title="Configure a slot" description="Assign an active Captain before booking. The Captain must cover the entire interval in the business timezone."><ConfigureSlotForm calendars={calendars.data || []} initialStart={configuring || undefined} onDone={() => setConfiguring(null)} /></Modal></div>;
}
