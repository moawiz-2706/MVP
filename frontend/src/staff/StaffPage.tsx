import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { Staff } from "../api/types";
import { DestructiveConfirmationDialog } from "../components/DestructiveConfirmationDialog";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { useSession } from "../auth/GHLSessionProvider";
import { WeeklyHoursFields, hhmm, type WeeklyInterval } from "../components/WeeklyHoursFields";

const shortDays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function hoursSummary(hours: Staff["hours"]): string[] {
  return shortDays.flatMap((day, index) => {
    const intervals = hours.filter((h) => h.day_of_week === index);
    return intervals.length ? [`${day} ${intervals.map((h) => `${hhmm(h.start_time)}–${hhmm(h.end_time)}`).join(", ")}`] : [];
  });
}

function StaffForm({ staff, onDone }: { staff: Staff | null; onDone: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(staff?.name || "");
  const [email, setEmail] = useState(staff?.email || "");
  const [phone, setPhone] = useState(staff?.phone || "");
  const [active, setActive] = useState(staff?.is_active ?? true);
  const [hours, setHours] = useState<WeeklyInterval[]>(() => (staff?.hours || []).map((h) => ({ day_of_week: h.day_of_week, start_time: hhmm(h.start_time), end_time: hhmm(h.end_time) })));
  const mutation = useMutation({
    mutationFn: () => api<Staff>(staff ? `/staff/${staff.id}` : "/staff", json(staff ? "PATCH" : "POST", { name, email: email || null, phone: phone || null, is_active: active, hours })),
    onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["staff"] }), client.invalidateQueries({ queryKey: ["staff-candidates"] })]); onDone(); },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); mutation.mutate(); };
  return (
    <form onSubmit={submit}>
      <div className="form-grid">
        <label className="field full"><span>Name</span><input autoFocus required maxLength={160} value={name} onChange={(e) => setName(e.target.value)} placeholder="Jordan Reyes" /></label>
        <label className="field"><span>Email (for assignment emails and reminders)</span><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="field"><span>Phone (optional)</span><input maxLength={40} value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
        <label className="check-field"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Available for assignment</label>
      </div>
      <div className="detail-section" style={{ marginTop: 20 }}>
        <h3>Working hours</h3>
        <p className="muted-note" style={{ marginBottom: 6 }}>Staff can only be put on a time slot that fits completely inside one of these intervals. Add several intervals on a day for split shifts. Hours are in the business timezone.</p>
        <WeeklyHoursFields hours={hours} onChange={setHours} />
      </div>
      {mutation.error && <div className="error-banner" style={{ marginTop: 12 }}>{mutation.error.message}</div>}
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={mutation.isPending}>{mutation.isPending ? "Saving…" : "Save staff member"}</button></div>
    </form>
  );
}

export function StaffPage() {
  const client = useQueryClient();
  const { me } = useSession();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["staff"], queryFn: () => api<Staff[]>("/staff") });
  const [editing, setEditing] = useState<Staff | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Staff | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/staff/${id}`, { method: "DELETE" }),
    onSuccess: async () => { setDeleting(null); await Promise.all([client.invalidateQueries({ queryKey: ["staff"] }), client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking-notifications"] }), client.invalidateQueries({ queryKey: ["staff-candidates"] })]); },
  });
  const canManageGhl = me.user.is_agency_owner || ["admin", "administrator", "agency_admin"].includes(me.user.role.toLowerCase());
  const verify = useMutation({
    mutationFn: (id: string) => api<Staff>(`/staff/${id}/ghl-user/verify-permissions`, json("POST", { confirmed: true })),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff"] }),
  });
  const retryGhl = useMutation({
    mutationFn: (id: string) => api<Staff>(`/staff/${id}/ghl-user/retry`, json("POST", {})),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff"] }),
  });
  return (
    <div className="page">
      <PageHeader title="Staff" description="Captains, guides, and crew who can be assigned to calendar time slots." action={<button className="button" onClick={() => setEditing(null)}><Plus size={16} />Add staff</button>} />
      {error && <div className="error-banner">{error.message}</div>}
      <div className="card table-card">
        {isLoading ? <div className="loading">Loading staff…</div> : data.length === 0 ? <EmptyState title="No staff yet" copy="Add the people who run your trips, then assign them to time slots from the Bookings calendar." /> : (
          <table className="data-table">
            <thead><tr><th>Staff member</th><th>Working hours</th><th>Upcoming</th><th>Status</th><th>GHL user</th><th aria-label="Actions" /></tr></thead>
            <tbody>
              {data.map((member) => {
                const summary = hoursSummary(member.hours);
                return (
                  <tr key={member.id}>
                    <td><div className="cell-title"><strong>{member.name}</strong><span>{[member.email, member.phone].filter(Boolean).join(" · ") || "No contact details"}</span></div></td>
                    <td>{summary.length ? <div className="cell-title">{summary.map((line) => <span key={line}>{line}</span>)}</div> : <span style={{ color: "#98a2b3" }}>No hours set</span>}</td>
                    <td>{member.upcoming_assignments}</td>
                    <td><span className={`badge ${member.is_active ? "success" : ""}`}><i className="status-dot" />{member.is_active ? "Active" : "Inactive"}</span></td>
                    <td><div className="cell-title"><span><span className={`badge ${member.ghl_user_sync_status === "synced" ? "success" : member.ghl_user_sync_status.includes("fail") ? "danger" : "warning"}`}>{member.ghl_user_sync_status.replaceAll("_", " ")}</span></span>{member.ghl_user_id && <span>User ID: {member.ghl_user_id}</span>}{member.ghl_user_last_error && <span className="staff-ghl-error">{member.ghl_user_last_error}</span>}</div></td>
                    <td><div className="toolbar"><button className="icon-button" aria-label={`Edit ${member.name}`} onClick={() => setEditing(member)}><Pencil size={15} /></button>{canManageGhl && member.ghl_user_id && <button className="icon-button" aria-label={`Verify GHL permissions for ${member.name}`} title="Verify GHL permissions" disabled={verify.isPending} onClick={() => { if (window.confirm(`Confirm that ${member.name} has only Calendar/Appointments View permissions, no Manage permissions, and access scoped to this installed location.`)) verify.mutate(member.id); }}><ShieldCheck size={15} /></button>}{canManageGhl && (member.ghl_user_sync_status.includes("fail") || member.ghl_user_sync_status === "needs_permission_review") && <button className="icon-button" aria-label={`Retry GHL sync for ${member.name}`} title="Retry GHL sync" disabled={retryGhl.isPending} onClick={() => retryGhl.mutate(member.id)}><RefreshCw size={15} /></button>}<button className="icon-button" aria-label={`Delete ${member.name}`} onClick={() => setDeleting(member)}><Trash2 size={15} /></button></div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <Modal open={editing !== undefined} onOpenChange={(open) => !open && setEditing(undefined)} title={editing ? `Edit ${editing.name}` : "Add staff"} description="Assignments are checked against these hours and against the person's other assignments.">
        <><StaffForm key={editing?.id ?? "new"} staff={editing || null} onDone={() => setEditing(undefined)} />{editing && <p className="muted-note" style={{ marginTop: 10 }}>GHL sync status is shown on the Staff page. Password resets are handled in GoHighLevel; Passport never displays a temporary password.</p>}</>
      </Modal>
      {verify.error && <div className="error-banner">GHL permission verification failed: {verify.error.message}</div>}
      {retryGhl.error && <div className="error-banner">GHL sync retry failed: {retryGhl.error.message}</div>}
      {deleting && <DestructiveConfirmationDialog open itemName={deleting.name} consequences={deleting.upcoming_assignments ? `This removes ${deleting.name} from ${deleting.upcoming_assignments} upcoming time slot${deleting.upcoming_assignments === 1 ? "" : "s"}. Past assignments are kept.` : "Past assignments are kept for your records."} onOpenChange={(open) => !open && setDeleting(null)} onConfirm={() => remove.mutate(deleting.id)} busy={remove.isPending} />}
    </div>
  );
}
