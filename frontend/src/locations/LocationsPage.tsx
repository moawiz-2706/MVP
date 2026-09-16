import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MapPin, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { Location } from "../api/types";
import { DestructiveConfirmationDialog } from "../components/DestructiveConfirmationDialog";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";

function LocationForm({ location, onDone }: { location: Location | null; onDone: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(location?.name || "");
  const [address, setAddress] = useState(location?.address || "");
  const [active, setActive] = useState(location?.is_active ?? true);
  useEffect(() => { setName(location?.name || ""); setAddress(location?.address || ""); setActive(location?.is_active ?? true); }, [location]);
  const mutation = useMutation({ mutationFn: () => api<Location>(location ? `/locations/${location.id}` : "/locations", json(location ? "PATCH" : "POST", { name, address, is_active: active })), onSuccess: async () => { await client.invalidateQueries({ queryKey: ["locations"] }); onDone(); } });
  return <form onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}><div className="form-grid"><label className="field full"><span>Location name</span><input autoFocus required value={name} onChange={(e) => setName(e.target.value)} placeholder="Laishley Park" /></label><label className="field full"><span>Customer-facing address</span><textarea required value={address} onChange={(e) => setAddress(e.target.value)} placeholder="120 Laishley Ct, Punta Gorda, FL" /></label><label className="check-field full"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Available for calendars</label></div>{mutation.error && <div className="error-banner">{mutation.error.message}</div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={mutation.isPending}>{mutation.isPending ? "Saving…" : "Save location"}</button></div></form>;
}

export function LocationsPage() {
  const client = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["locations"], queryFn: () => api<Location[]>("/locations") });
  const [editing, setEditing] = useState<Location | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Location | null>(null);
  const remove = useMutation({ mutationFn: (id: string) => api<void>(`/locations/${id}`, { method: "DELETE" }), onSuccess: async () => { setDeleting(null); await Promise.all([client.invalidateQueries({ queryKey: ["locations"] }), client.invalidateQueries({ queryKey: ["calendars"] })]); } });
  return <div className="page"><PageHeader title="Locations" description="Physical departure and service addresses shown to customers." action={<button className="button" onClick={() => setEditing(null)}><Plus size={16} />Add location</button>} />{error && <div className="error-banner">{error.message}</div>}<div className="card table-card">{isLoading ? <div className="loading">Loading locations…</div> : !data.length ? <EmptyState title="No locations yet" copy="Add the physical places where customers begin or receive their booking." /> : <table className="data-table"><thead><tr><th>Location</th><th>Address</th><th>Status</th><th>Calendars</th><th aria-label="Actions" /></tr></thead><tbody>{data.map((location) => <tr key={location.id}><td><div className="cell-title"><strong>{location.name}</strong><span>Departure location</span></div></td><td><span style={{display:"inline-flex", gap:6, alignItems:"center"}}><MapPin size={13} />{location.address}</span></td><td><span className={`badge ${location.is_active ? "success" : ""}`}><i className="status-dot" />{location.is_active ? "Active" : "Inactive"}</span></td><td>{location.calendars_count}</td><td><div className="toolbar"><button className="icon-button" onClick={() => setEditing(location)} aria-label={`Edit ${location.name}`}><Pencil size={15} /></button><button className="icon-button" onClick={() => setDeleting(location)} aria-label={`Delete ${location.name}`}><Trash2 size={15} /></button></div></td></tr>)}</tbody></table>}</div><Modal open={editing !== undefined} onOpenChange={(open) => !open && setEditing(undefined)} title={editing ? `Edit ${editing.name}` : "Add location"} description="This name and address appear throughout the customer journey."><LocationForm location={editing || null} onDone={() => setEditing(undefined)} /></Modal>{deleting && <DestructiveConfirmationDialog open itemName={deleting.name} consequences="This location will be removed from every calendar using it. The calendars themselves will not be deleted." onOpenChange={(open) => !open && setDeleting(null)} onConfirm={() => remove.mutate(deleting.id)} busy={remove.isPending} />}</div>;
}
