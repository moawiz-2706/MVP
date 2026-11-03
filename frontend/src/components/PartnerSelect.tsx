import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Partner } from "../api/types";

/** Hotel partner that sent this booking; empty means Direct. */
export function PartnerSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const partners = useQuery({ queryKey: ["partners"], queryFn: () => api<Partner[]>("/partners") });
  const active = (partners.data || []).filter((partner) => partner.is_active);
  if (!active.length) return null;
  return <label className="field"><span>Booked through</span><select value={value} onChange={(event) => onChange(event.target.value)}><option value="">Direct</option>{active.map((partner) => <option key={partner.id} value={partner.id}>{partner.name}</option>)}</select></label>;
}
