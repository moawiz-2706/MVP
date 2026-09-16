import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { Resource } from "../api/types";
import { DestructiveConfirmationDialog } from "../components/DestructiveConfirmationDialog";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";

function ResourceForm({ resource, onDone }: { resource: Resource | null; onDone: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(resource?.name || "");
  const [quantity, setQuantity] = useState(resource?.quantity ?? 1);
  const [active, setActive] = useState(resource?.is_active ?? true);
  useEffect(() => { setName(resource?.name || ""); setQuantity(resource?.quantity ?? 1); setActive(resource?.is_active ?? true); }, [resource]);
  const mutation = useMutation({ mutationFn: () => api<Resource>(resource ? `/resources/${resource.id}` : "/resources", json(resource ? "PATCH" : "POST", { name, quantity, is_active: active })), onSuccess: async () => { await client.invalidateQueries({ queryKey: ["resources"] }); onDone(); } });
  const submit = (event: FormEvent) => { event.preventDefault(); mutation.mutate(); };
  return <form onSubmit={submit}><div className="form-grid"><label className="field full"><span>Name</span><input autoFocus required maxLength={160} value={name} onChange={(e) => setName(e.target.value)} placeholder="Single Kayaks" /></label><label className="field"><span>Total quantity</span><input required type="number" min={0} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} /></label><label className="check-field"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Available for scheduling</label></div>{mutation.error && <div className="error-banner">{mutation.error.message}</div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={mutation.isPending}>{mutation.isPending ? "Saving…" : "Save resource"}</button></div></form>;
}

export function ResourcesPage() {
  const client = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["resources"], queryFn: () => api<Resource[]>("/resources") });
  const [editing, setEditing] = useState<Resource | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Resource | null>(null);
  const remove = useMutation({ mutationFn: (id: string) => api<void>(`/resources/${id}`, { method: "DELETE" }), onSuccess: async () => { setDeleting(null); await Promise.all([client.invalidateQueries({ queryKey: ["resources"] }), client.invalidateQueries({ queryKey: ["calendars"] })]); } });
  return <div className="page"><PageHeader title="Resources" description="Shared inventory pools used across all booking calendars." action={<button className="button" onClick={() => setEditing(null)}><Plus size={16} />Add resource</button>} />{error && <div className="error-banner">{error.message}</div>}<div className="card table-card">{isLoading ? <div className="loading">Loading inventory…</div> : data.length === 0 ? <EmptyState title="No resources yet" copy="Create a quantity pool such as Single Kayaks, Guides, or Trailers." /> : <table className="data-table"><thead><tr><th>Resource</th><th>Quantity</th><th>Status</th><th>Calendars</th><th aria-label="Actions" /></tr></thead><tbody>{data.map((resource) => <tr key={resource.id}><td><div className="cell-title"><strong>{resource.name}</strong><span>Quantity pool</span></div></td><td>{resource.quantity}</td><td><span className={`badge ${resource.is_active ? "success" : ""}`}><i className="status-dot" />{resource.is_active ? "Active" : "Inactive"}</span></td><td>{resource.calendars_count}</td><td><div className="toolbar"><button className="icon-button" aria-label={`Edit ${resource.name}`} onClick={() => setEditing(resource)}><Pencil size={15} /></button><button className="icon-button" aria-label={`Delete ${resource.name}`} onClick={() => setDeleting(resource)}><Trash2 size={15} /></button></div></td></tr>)}</tbody></table>}</div><Modal open={editing !== undefined} onOpenChange={(open) => !open && setEditing(undefined)} title={editing ? `Edit ${editing.name}` : "Add resource"} description="Resource quantity is shared by every calendar mapped to this pool."><ResourceForm resource={editing || null} onDone={() => setEditing(undefined)} /></Modal>{deleting && <DestructiveConfirmationDialog open itemName={deleting.name} consequences={`This detaches the resource from ${deleting.calendars_count} active calendar${deleting.calendars_count === 1 ? "" : "s"}.`} onOpenChange={(open) => !open && setDeleting(null)} onConfirm={() => remove.mutate(deleting.id)} busy={remove.isPending} />}</div>;
}

