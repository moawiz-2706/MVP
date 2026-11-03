import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { Partner } from "../api/types";
import { DestructiveConfirmationDialog } from "../components/DestructiveConfirmationDialog";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { PageHeader } from "../components/PageHeader";

const percent = (bps: number) => `${(bps / 100).toFixed(bps % 100 ? 2 : 0)}%`;
const operatorShare = (partner: Pick<Partner, "hotel_commission_bps" | "pga_commission_bps">) =>
  10_000 - partner.hotel_commission_bps - partner.pga_commission_bps;

function PartnerForm({ partner, onDone }: { partner: Partner | null; onDone: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState(partner?.name || "");
  const [code, setCode] = useState(partner?.code || "");
  const [hotel, setHotel] = useState(String((partner?.hotel_commission_bps ?? 2000) / 100));
  const [pga, setPga] = useState(String((partner?.pga_commission_bps ?? 3000) / 100));
  const [active, setActive] = useState(partner?.is_active ?? true);
  useEffect(() => {
    setName(partner?.name || "");
    setCode(partner?.code || "");
    setHotel(String((partner?.hotel_commission_bps ?? 2000) / 100));
    setPga(String((partner?.pga_commission_bps ?? 3000) / 100));
    setActive(partner?.is_active ?? true);
  }, [partner]);
  const hotelBps = Math.round(Number(hotel) * 100);
  const pgaBps = Math.round(Number(pga) * 100);
  const invalid = !Number.isFinite(hotelBps) || !Number.isFinite(pgaBps) || hotelBps < 0 || pgaBps < 0 || hotelBps + pgaBps > 10_000;
  const mutation = useMutation({
    mutationFn: () => api<Partner>(partner ? `/partners/${partner.id}` : "/partners", json(partner ? "PATCH" : "POST", {
      name: name.trim(),
      code: code.trim() || null,
      hotel_commission_bps: hotelBps,
      pga_commission_bps: pgaBps,
      is_active: active,
    })),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ["partners"] }); onDone(); },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); if (!invalid) mutation.mutate(); };
  return <form onSubmit={submit}>
    <div className="form-grid">
      <label className="field full"><span>Partner name</span><input autoFocus required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Sunseeker Resort" /></label>
      <label className="field full"><span>Link code</span><input maxLength={80} value={code} onChange={(event) => setCode(event.target.value)} placeholder="Made from the name, e.g. sunseeker" /><small>Used in the partner's booking link: ?partner=code</small></label>
      <label className="field"><span>Hotel commission (%)</span><input required type="number" min={0} max={100} step="0.01" value={hotel} onChange={(event) => setHotel(event.target.value)} /></label>
      <label className="field"><span>PGA commission (%)</span><input required type="number" min={0} max={100} step="0.01" value={pga} onChange={(event) => setPga(event.target.value)} /></label>
      <p className="muted-note field full" style={{ margin: 0 }}>{invalid ? "Hotel and PGA commission together cannot exceed 100%." : `Operator keeps ${percent(10_000 - hotelBps - pgaBps)} of the price before tax and fees.`}</p>
      <label className="check-field"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />Active (its link tags bookings)</label>
    </div>
    {mutation.error && <div className="error-banner">{mutation.error.message}</div>}
    <div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={mutation.isPending || invalid}>{mutation.isPending ? "Saving…" : "Save partner"}</button></div>
  </form>;
}

function CopyLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { window.prompt("Copy this booking link", url); }
  };
  return <button type="button" className="button secondary small" onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy link"}</button>;
}

export function PartnersPage() {
  const client = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ["partners"], queryFn: () => api<Partner[]>("/partners") });
  const [editing, setEditing] = useState<Partner | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Partner | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/partners/${id}`, { method: "DELETE" }),
    onSuccess: async () => { setDeleting(null); await client.invalidateQueries({ queryKey: ["partners"] }); },
  });
  const split = (partner: Partner) => `${percent(partner.hotel_commission_bps)} hotel · ${percent(partner.pga_commission_bps)} PGA · ${percent(operatorShare(partner))} operator`;
  return <div className="page">
    <PageHeader title="Partners" description="Hotels that send bookings and share the revenue. Bookings without a partner are Direct: the operator keeps 100%." action={<button className="button" onClick={() => setEditing(null)}><Plus size={16} />Add partner</button>} />
    {error && <div className="error-banner">{error.message}</div>}
    <div className="card table-card">
      {isLoading ? <div className="loading">Loading partners…</div> : data.length === 0 ? <EmptyState title="No partners yet" copy="Add a hotel such as Sunseeker, Wyvern or Four Points, then share its booking link." /> : <>
        <div className="desktop-resource-table"><table className="data-table"><thead><tr><th>Partner</th><th>Split</th><th>Status</th><th>Booking link</th><th aria-label="Actions" /></tr></thead><tbody>{data.map((partner) => <tr key={partner.id}>
          <td><div className="cell-title"><strong>{partner.name}</strong><span>?partner={partner.code}</span></div></td>
          <td>{split(partner)}</td>
          <td><span className={`badge ${partner.is_active ? "success" : ""}`}><i className="status-dot" />{partner.is_active ? "Active" : "Inactive"}</span></td>
          <td><CopyLink url={partner.booking_link} /></td>
          <td><div className="toolbar"><button className="icon-button" aria-label={`Edit ${partner.name}`} onClick={() => setEditing(partner)}><Pencil size={14} /></button><button className="icon-button" aria-label={`Delete ${partner.name}`} onClick={() => setDeleting(partner)}><Trash2 size={14} /></button></div></td>
        </tr>)}</tbody></table></div>
        <div className="mobile-resource-list">{data.map((partner) => <article className="mobile-resource-card" key={partner.id}>
          <div className="mobile-resource-heading"><div><strong>{partner.name}</strong><span>?partner={partner.code}</span></div><span className={`badge ${partner.is_active ? "success" : ""}`}><i className="status-dot" />{partner.is_active ? "Active" : "Inactive"}</span></div>
          <dl className="mobile-resource-meta"><div><dt>Split</dt><dd>{split(partner)}</dd></div></dl>
          <div className="mobile-resource-actions"><CopyLink url={partner.booking_link} /><button className="button secondary small" onClick={() => setEditing(partner)}><Pencil size={14} />Edit</button><button className="button ghost small" onClick={() => setDeleting(partner)}><Trash2 size={14} />Delete</button></div>
        </article>)}</div>
      </>}
    </div>
    <Modal open={editing !== undefined} onOpenChange={(open) => !open && setEditing(undefined)} title={editing ? `Edit ${editing.name}` : "Add partner"} description="Rate changes apply to new bookings; existing bookings keep the split they were made with."><PartnerForm partner={editing || null} onDone={() => setEditing(undefined)} /></Modal>
    {deleting && <DestructiveConfirmationDialog open itemName={deleting.name} consequences="Its booking link stops tagging new bookings. Past bookings keep this partner and their split." onOpenChange={(open) => !open && setDeleting(null)} onConfirm={() => remove.mutate(deleting.id)} busy={remove.isPending} />}
  </div>;
}
