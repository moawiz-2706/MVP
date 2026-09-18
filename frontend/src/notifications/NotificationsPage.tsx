import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CheckCircle2, Package, UserPlus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, json } from "../api/client";
import type { Calendar, CalendarResource, NotificationItem, NotificationsResponse, Resource, StaffCandidate, BookingDetail } from "../api/types";
import { useSession } from "../auth/GHLSessionProvider";
import { PageHeader } from "../components/PageHeader";
import { AvailabilityEditor } from "../calendars/AvailabilityEditor";
import { formatLongDate, formatTime, zoneLabel } from "../lib/datetime";

const iconFor = (type: NotificationItem["type"]) => {
  if (type === "booking_staff") return UserPlus;
  if (type === "calendar_resources") return Package;
  return CalendarClock;
};

function ResourceAction({ calendar, onSaved }: { calendar: Calendar; onSaved: () => void }) {
  const client = useQueryClient();
  const resources = useQuery({ queryKey: ["resources"], queryFn: () => api<Resource[]>("/resources") });
  const mapped = useQuery({ queryKey: ["calendar-resources", calendar.id], queryFn: () => api<CalendarResource[]>(`/calendars/${calendar.id}/resources`) });
  const [selected, setSelected] = useState<Record<string, number>>({});
  const [initialized, setInitialized] = useState(false);
  useEffect(() => {
    if (mapped.data && !initialized) {
    setSelected(Object.fromEntries(mapped.data.map((item) => [item.resource_id, item.default_quantity_per_unit])));
    setInitialized(true);
    }
  }, [initialized, mapped.data]);
  const save = useMutation({
    mutationFn: () => api<CalendarResource[]>(`/calendars/${calendar.id}/resources`, json("PUT", {
      resources: Object.entries(selected).map(([resource_id, default_quantity_per_unit]) => ({ resource_id, default_quantity_per_unit })),
    })),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["calendar-resources", calendar.id] }),
        client.invalidateQueries({ queryKey: ["notifications"] }),
      ]);
      onSaved();
    },
  });
  return <div className="drawer-action-content">
    <p className="muted-note">Select the shared resource pools required by this calendar. Every selected resource must have a quantity per booking unit.</p>
    {resources.isLoading || mapped.isLoading ? <div className="loading">Loading resources…</div> : resources.data?.length ? <div className="drawer-resource-list">
      {resources.data.map((resource) => <div className="drawer-resource-row" key={resource.id}>
        <label className="check-field"><input type="checkbox" checked={resource.id in selected} onChange={(event) => setSelected((current) => { const next = { ...current }; if (event.target.checked) next[resource.id] = 1; else delete next[resource.id]; return next; })} /><span><strong>{resource.name}</strong><small>{resource.quantity} total available</small></span></label>
        {resource.id in selected && <input className="control resource-quantity" type="number" min={1} value={selected[resource.id]} onChange={(event) => setSelected((current) => ({ ...current, [resource.id]: Number(event.target.value) }))} aria-label={`Quantity of ${resource.name} per booking unit`} />}
      </div>)}
    </div> : <p className="muted-note">No resources exist yet. Create a resource from the Resources page first.</p>}
    {save.error && <div className="error-banner">{save.error.message}</div>}
    <button className="button" disabled={save.isPending || resources.isLoading || mapped.isLoading} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save resources"}</button>
  </div>;
}

function BookingStaffAction({ item, onSaved }: { item: NotificationItem; onSaved: () => void }) {
  const { me } = useSession();
  const client = useQueryClient();
  const detail = useQuery({ queryKey: ["booking", item.booking_id], queryFn: () => api<BookingDetail>(`/bookings/${item.booking_id}`), enabled: Boolean(item.booking_id) });
  const [selectedRole, setSelectedRole] = useState(item.missing_roles[0] || item.required_roles[0] || "");
  const [staffId, setStaffId] = useState("");
  const roleQueries = useQueries({ queries: item.missing_roles.map((role) => ({
    queryKey: ["staff-candidates", item.calendar_id, item.start_at, role],
    queryFn: () => api<StaffCandidate[]>(`/staff-assignments/candidates?${new URLSearchParams({ calendar_id: item.calendar_id, start_at: item.start_at || "", required_role: role })}`),
    enabled: Boolean(item.start_at),
  })) });
  const candidateQuery = roleQueries[item.missing_roles.indexOf(selectedRole)] || roleQueries[0];
  const assign = useMutation({
    mutationFn: () => api(`/staff-assignments`, json("POST", { staff_id: staffId, calendar_id: item.calendar_id, start_at: item.start_at, role: selectedRole })),
    onSuccess: async () => {
      setStaffId("");
      await Promise.all([
        client.invalidateQueries({ queryKey: ["notifications"] }),
        client.invalidateQueries({ queryKey: ["booking", item.booking_id] }),
        client.invalidateQueries({ queryKey: ["bookings"] }),
        client.invalidateQueries({ queryKey: ["staff-candidates"] }),
      ]);
      onSaved();
    },
  });
  return <div className="drawer-action-content">
    <div className="notification-detail-meta"><strong>{item.customer_name || "Booking"}</strong><span>{item.calendar_name}</span>{item.start_at && <span>{formatLongDate(item.start_at, me.operator.time_zone)} · {formatTime(item.start_at, me.operator.time_zone)} ({zoneLabel(me.operator.time_zone)})</span>}</div>
    {detail.isLoading ? <div className="loading">Loading booking details…</div> : detail.data && <dl className="detail-list"><dt>Customer</dt><dd>{detail.data.customer_name}</dd><dt>Status</dt><dd>{detail.data.status.replaceAll("_", " ")}</dd><dt>Quantity</dt><dd>{detail.data.units}</dd></dl>}
    <div className="warning-box"><AlertTriangle size={17} /><p>{item.description}</p></div>
    <div className="form-grid">
      <label className="field"><span>Required role</span><select value={selectedRole} onChange={(event) => { setSelectedRole(event.target.value); setStaffId(""); }}>{item.missing_roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
      <label className="field"><span>Matching staff member</span><select value={staffId} onChange={(event) => setStaffId(event.target.value)} disabled={!selectedRole || candidateQuery?.isLoading}><option value="">{candidateQuery?.isLoading ? "Loading staff…" : "Choose staff"}</option>{(candidateQuery?.data || []).filter((candidate) => candidate.available).map((candidate) => <option key={candidate.staff_id} value={candidate.staff_id}>{candidate.name}</option>)}</select></label>
    </div>
    {candidateQuery?.error && <div className="error-banner">{candidateQuery.error.message}</div>}
    {assign.error && <div className="error-banner">{assign.error.message}</div>}
    {!candidateQuery?.data?.some((candidate) => candidate.available) && !candidateQuery?.isLoading && <p className="muted-note">No available staff member currently matches this role. Sync GHL staff availability and assign the custom role on the Staff page first.</p>}
    <button className="button" disabled={!staffId || assign.isPending} onClick={() => assign.mutate()}>{assign.isPending ? "Assigning…" : "Assign staff"}</button>
  </div>;
}

function NotificationDrawer({ item, onClose, onResolved }: { item: NotificationItem; onClose: () => void; onResolved: () => void }) {
  const client = useQueryClient();
  const calendar = useQuery({ queryKey: ["calendar", item.calendar_id], queryFn: () => api<Calendar>(`/calendars/${item.calendar_id}`), enabled: item.type !== "booking_staff" });
  const title = item.type === "booking_staff" ? "Assign booking staff" : item.type === "calendar_resources" ? "Configure calendar resources" : "Configure calendar availability";
  return <><button className="drawer-overlay" onClick={onClose} aria-label="Close notification details" /><aside className="drawer notification-drawer" aria-label="Notification details"><div className="drawer-header"><div><h2>{title}</h2><p>{item.calendar_name}</p></div><button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button></div><div className="notification-drawer-summary"><strong>{item.title}</strong><p>{item.description}</p></div>{item.type === "booking_staff" && <BookingStaffAction item={item} onSaved={onResolved} />}{item.type === "calendar_resources" && (calendar.isLoading || !calendar.data ? <div className="loading">Loading calendar…</div> : <ResourceAction calendar={calendar.data} onSaved={onResolved} />)}{item.type === "calendar_availability" && (calendar.isLoading || !calendar.data ? <div className="loading">Loading calendar…</div> : <AvailabilityEditor calendar={calendar.data} onCalendarChange={(updated) => { client.setQueryData(["calendar", item.calendar_id], updated); void client.invalidateQueries({ queryKey: ["notifications"] }); }} onSaved={() => void client.invalidateQueries({ queryKey: ["notifications"] })} />)}</aside></>;
}

export function NotificationsPage() {
  const { me } = useSession();
  const client = useQueryClient();
  const [selected, setSelected] = useState<NotificationItem | null>(null);
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => api<NotificationsResponse>("/notifications"), refetchInterval: 15_000 });
  const refresh = async () => { await client.invalidateQueries({ queryKey: ["notifications"] }); setSelected(null); };
  const items = notifications.data?.items || [];
  return <div className="page"><PageHeader title="Notifications" description="Resolve the setup and booking actions currently required by your account." action={<button className="button secondary" onClick={() => notifications.refetch()}>Refresh</button>} />{notifications.error && <div className="error-banner">{notifications.error.message}</div>}{notifications.isLoading ? <div className="card loading">Checking account setup…</div> : !items.length ? <div className="card empty-state"><CheckCircle2 size={26} color="#176b4f" /><strong>Everything is up to date</strong><span>No booking or calendar setup actions currently require attention.</span></div> : <div className="notification-list">{items.map((item) => { const Icon = iconFor(item.type); return <button className="notification-card" key={item.id} onClick={() => setSelected(item)}><span className={`notification-icon ${item.type}`}><Icon size={18} /></span><span className="notification-card-body"><strong>{item.title}</strong><span>{item.description}</span><small>{item.calendar_name}{item.start_at ? ` · ${formatLongDate(item.start_at, me.operator.time_zone)} at ${formatTime(item.start_at, me.operator.time_zone)}` : ""}</small></span><span className="button ghost small">{item.action_label}</span></button>; })}</div>}{selected && <NotificationDrawer item={selected} onClose={() => setSelected(null)} onResolved={refresh} />}</div>;
}
