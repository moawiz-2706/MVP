import { RefreshCw, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";
import type { GHLStaffDetails, Staff } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";
import { formatLongDate, formatTime } from "../lib/datetime";

const STAFF_ROLES = ["Captain", "First Mate", "Guide", "Deckhand", "Instructor"] as const;
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function displayProfileValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function StaffDetailsDialog({ staff, onClose }: { staff: Staff | null; onClose: () => void }) {
  const details = useQuery({
    queryKey: ["staff-ghl-details", staff?.id],
    queryFn: () => api<GHLStaffDetails>(`/staff-ghl/${staff!.id}/details`),
    enabled: Boolean(staff),
    staleTime: 0,
  });
  const profile = details.data?.profile || {};
  return <Modal open={Boolean(staff)} onOpenChange={(open) => !open && onClose()} title={staff ? `${staff.name} — GHL details` : "GHL staff details"} description="Read-only information retrieved from GoHighLevel, including the latest availability schedule.">
    {details.isLoading && <div className="loading">Refreshing details and availability from GHL…</div>}
    {details.error && <div className="error-banner">Unable to load the latest GHL details: {details.error.message}</div>}
    {details.data && <div className="staff-details-dialog">
      <section className="detail-section"><h3>GHL profile</h3><dl className="detail-list">{Object.entries(profile).map(([key, value]) => <span style={{ display: "contents" }} key={key}><dt>{key}</dt><dd>{displayProfileValue(value)}</dd></span>)}</dl></section>
      <section className="detail-section"><h3>Availability from GHL Calendar</h3><dl className="detail-list"><dt>Time zone</dt><dd>{details.data.time_zone || "Not returned by GHL"}</dd><dt>Last synchronized</dt><dd>{details.data.availability_last_synced_at ? formatLongDate(details.data.availability_last_synced_at, details.data.time_zone || "UTC") : "Not synchronized"}</dd><dt>Sync status</dt><dd>{details.data.availability_sync_status}</dd></dl>{details.data.hours.length ? <div className="staff-schedule-list">{details.data.hours.map((hour) => <div className="staff-schedule-row" key={`${hour.day_of_week}-${hour.start_time}-${hour.end_time}`}><strong>{DAY_NAMES[hour.day_of_week] || `Day ${hour.day_of_week}`}</strong><span>{formatTime(`1970-01-01T${hour.start_time}Z`, details.data!.time_zone || "UTC")} – {formatTime(`1970-01-01T${hour.end_time}Z`, details.data!.time_zone || "UTC")}</span></div>)}</div> : <p className="muted-note">GHL returned no weekly availability intervals for this staff member.</p>}</section>
      <p className="muted-note">These details and availability are controlled by GHL. Passport only stores the custom role shown on the Staff page.</p>
    </div>}
  </Modal>;
}

function StaffRoleEditor({ member, onOpen }: { member: Staff; onOpen: (member: Staff) => void }) {
  const client = useQueryClient();
  const [role, setRole] = useState(member.custom_role || "");
  const roleMutation = useMutation({
    mutationFn: () => api<Staff>(`/staff/${member.id}/custom-role`, json("PATCH", { custom_role: role || null })),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff"] }),
  });
  useEffect(() => setRole(member.custom_role || ""), [member.custom_role]);
  const changed = role !== (member.custom_role || "");
  return <tr className={!member.custom_role ? "staff-role-missing" : undefined}>
    <td><button className="staff-name-button" onClick={() => onOpen(member)}><strong>{member.name}</strong><span>{member.email || "No email returned by GHL"}</span></button></td>
    <td>{member.phone || "—"}</td>
    <td><span className={`badge ${member.is_active ? "success" : "warning"}`}>{member.is_active ? "Active" : "Inactive"}</span></td>
    <td><span className="staff-ghl-id">{member.ghl_user_id}</span></td>
    <td><div className="staff-role-editor"><select className="control" aria-label={`Custom role for ${member.name}`} value={role} onChange={(event) => setRole(event.target.value)}><option value="">Select role</option>{STAFF_ROLES.map((option) => <option key={option} value={option}>{option}</option>)}</select><button className="button small" disabled={!changed || roleMutation.isPending} onClick={() => roleMutation.mutate()}><Save size={14} />{roleMutation.isPending ? "Saving…" : "Save role"}</button></div>{!member.custom_role && <span className="staff-role-warning">Select a role before booking assignment</span>}{roleMutation.error && <span className="staff-ghl-error">{roleMutation.error.message}</span>}{roleMutation.isSuccess && <span className="staff-role-saved">Role saved</span>}</td>
  </tr>;
}

export function StaffPage() {
  const client = useQueryClient();
  const [selected, setSelected] = useState<Staff | null>(null);
  const { data = [], isLoading, error } = useQuery({ queryKey: ["staff"], queryFn: () => api<Staff[]>("/staff") });
  const syncStarted = useRef(false);
  const directorySync = useMutation({
    mutationFn: () => api<{ synced: number; created: number; updated: number; availability_synced: number; availability_failed: number; error: string | null }>("/staff-ghl/directory/sync", json("POST", {})),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff"] }),
  });
  useEffect(() => { if (!syncStarted.current) { syncStarted.current = true; directorySync.mutate(); } }, []);

  const syncedStaff = data.filter((member) => member.ghl_user_id);
  const unassignedCount = syncedStaff.filter((member) => !member.custom_role).length;
  return <div className="page">
    <PageHeader title="Staff roles" description="GHL manages staff identity and availability. Passport manages only the fixed custom role used for booking eligibility." action={<button className="button secondary" disabled={directorySync.isPending} onClick={() => directorySync.mutate()}><RefreshCw size={16} />{directorySync.isPending ? "Syncing GHL…" : "Sync GHL staff"}</button>} />
    {error && <div className="error-banner">{error.message}</div>}
    {directorySync.error && <div className="error-banner">GHL staff and availability sync failed: {directorySync.error.message}</div>}
    {directorySync.isSuccess && <div className="success-banner">GHL staff and availability synchronized. Passport role assignments were preserved.</div>}
    {unassignedCount > 0 && <div className="warning-banner">{unassignedCount} synced staff member{unassignedCount === 1 ? "" : "s"} still need a custom role.</div>}
    {isLoading ? <div className="loading">Loading GHL staff…</div> : !syncedStaff.length ? <EmptyState title="No synced GHL staff" copy="Click Sync GHL staff after the GHL users.readonly and calendars.readonly scopes have been authorized." /> : <div className="card table-card"><table className="data-table staff-directory-table"><thead><tr><th>Name and email</th><th>Phone</th><th>GHL status</th><th>GHL user ID</th><th>Passport custom role</th></tr></thead><tbody>{syncedStaff.map((member) => <StaffRoleEditor key={member.id} member={member} onOpen={setSelected} />)}</tbody></table></div>}
    <p className="muted-note" style={{ marginTop: 12 }}>Click a staff member’s name to view the latest GHL profile and availability. Name, email, phone, GHL user ID, permissions, schedule, and account status are read-only. Only the predefined Passport role can be changed.</p>
    <StaffDetailsDialog staff={selected} onClose={() => setSelected(null)} />
  </div>;
}
