import { RefreshCw, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";
import type { Staff } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";

const ROLE_SUGGESTIONS = ["Captain", "First Mate", "Guide", "Deckhand", "Instructor"];

function StaffRoleEditor({ member }: { member: Staff }) {
  const client = useQueryClient();
  const [role, setRole] = useState(member.custom_role || "");
  const roleMutation = useMutation({
    mutationFn: () => api<Staff>(`/staff/${member.id}/custom-role`, json("PATCH", { custom_role: role.trim() || null })),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff"] }),
  });
  useEffect(() => setRole(member.custom_role || ""), [member.custom_role]);
  const changed = role.trim() !== (member.custom_role || "");
  return (
    <tr className={!member.custom_role ? "staff-role-missing" : undefined}>
      <td>
        <div className="cell-title"><strong>{member.name}</strong><span>{member.email || "No email returned by GHL"}</span></div>
      </td>
      <td>{member.phone || "—"}</td>
      <td><span className={`badge ${member.is_active ? "success" : "warning"}`}>{member.is_active ? "Active" : "Inactive"}</span></td>
      <td><span className="staff-ghl-id">{member.ghl_user_id}</span></td>
      <td>
        <div className="staff-role-editor">
          <input
            className="control"
            aria-label={`Custom role for ${member.name}`}
            list="custom-staff-roles"
            maxLength={80}
            placeholder="Assign custom role"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          />
          <button className="button small" disabled={!changed || roleMutation.isPending} onClick={() => roleMutation.mutate()}>
            <Save size={14} />{roleMutation.isPending ? "Saving…" : "Save role"}
          </button>
        </div>
        {!member.custom_role && <span className="staff-role-warning">Custom role required before booking assignment</span>}
        {roleMutation.error && <span className="staff-ghl-error">{roleMutation.error.message}</span>}
        {roleMutation.isSuccess && !roleMutation.error && <span className="staff-role-saved">Role saved</span>}
      </td>
    </tr>
  );
}

export function StaffPage() {
  const client = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["staff"], queryFn: () => api<Staff[]>("/staff") });
  const syncStarted = useRef(false);
  const directorySync = useMutation({
    mutationFn: () => api<{ synced: number; created: number; updated: number; error: string | null }>("/staff-ghl/directory/sync", json("POST", {})),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff"] }),
  });
  useEffect(() => {
    if (!syncStarted.current) {
      syncStarted.current = true;
      directorySync.mutate();
    }
  }, []);

  const syncedStaff = data.filter((member) => member.ghl_user_id);
  const unassignedCount = syncedStaff.filter((member) => !member.custom_role).length;
  return (
    <div className="page">
      <PageHeader
        title="Staff roles"
        description="GHL manages staff identity and permissions. Passport manages only the custom role used for booking eligibility."
        action={<button className="button secondary" disabled={directorySync.isPending} onClick={() => directorySync.mutate()}><RefreshCw size={16} />{directorySync.isPending ? "Syncing GHL…" : "Sync GHL staff"}</button>}
      />
      {error && <div className="error-banner">{error.message}</div>}
      {directorySync.error && <div className="error-banner">GHL staff directory sync failed: {directorySync.error.message}</div>}
      {directorySync.isSuccess && <div className="success-banner">GHL staff synchronized. Assign a Passport custom role to each staff member before booking.</div>}
      {unassignedCount > 0 && <div className="warning-banner">{unassignedCount} synced staff member{unassignedCount === 1 ? "" : "s"} still need a custom role.</div>}
      {isLoading ? <div className="loading">Loading GHL staff…</div> : !syncedStaff.length ? <EmptyState title="No synced GHL staff" copy="Click Sync GHL staff after the GHL users.readonly scope has been authorized." /> : (
        <div className="card table-card">
          <table className="data-table staff-directory-table">
            <thead><tr><th>Name and email</th><th>Phone</th><th>GHL status</th><th>GHL user ID</th><th>Passport custom role</th></tr></thead>
            <tbody>{syncedStaff.map((member) => <StaffRoleEditor key={member.id} member={member} />)}</tbody>
          </table>
          <datalist id="custom-staff-roles">{ROLE_SUGGESTIONS.map((role) => <option key={role} value={role} />)}</datalist>
        </div>
      )}
      <p className="muted-note" style={{ marginTop: 12 }}>Name, email, phone, GHL user ID, GHL permissions, and account status are read-only here and remain managed in GoHighLevel. Booking roles are filtered from the Passport custom role.</p>
    </div>
  );
}
