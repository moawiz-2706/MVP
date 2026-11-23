import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, json } from "../api/client";
import { MutationNotice } from "../components/MutationNotice";

interface PayoutCalendar { id: string; name: string; category: string | null; is_active: boolean; included: boolean }
interface PayoutSettings { payout_share_bps: number; calendars: PayoutCalendar[] }

const EXAMPLE_TICKET = 10000; // $100.00
const usd = (minor: number) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(minor / 100);

/** How much of each ticket price goes to the connected Stripe account, and for which calendars. */
export function PayoutSplitSettings() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["payout-settings"], queryFn: () => api<PayoutSettings>("/settings/payments/payouts") });
  const [percent, setPercent] = useState("80");
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!query.data) return;
    setPercent(String(query.data.payout_share_bps / 100));
    setIncluded(Object.fromEntries(query.data.calendars.map((calendar) => [calendar.id, calendar.included])));
  }, [query.data]);

  const groups = useMemo(() => {
    const byCategory = new Map<string, PayoutCalendar[]>();
    for (const calendar of query.data?.calendars || []) {
      const key = calendar.category || "Uncategorized";
      byCategory.set(key, [...(byCategory.get(key) || []), calendar]);
    }
    return [...byCategory.entries()];
  }, [query.data]);

  const value = Number(percent);
  const valid = percent.trim() !== "" && Number.isFinite(value) && value >= 0 && value <= 100;
  const bps = valid ? Math.round(value * 100) : 0;
  const share = Math.round((EXAMPLE_TICKET * bps) / 10000);
  const includedCount = Object.values(included).filter(Boolean).length;

  const save = useMutation({
    mutationFn: () => api<PayoutSettings>("/settings/payments/payouts", json("PUT", {
      payout_share_bps: bps,
      calendars: Object.entries(included).map(([id, on]) => ({ id, included: on })),
    })),
    onSuccess: (result) => { client.setQueryData(["payout-settings"], result); setSuccess("Payout split saved. It applies to bookings made from now on."); },
  });

  const setGroup = (calendars: PayoutCalendar[], on: boolean) => setIncluded((current) => ({ ...current, ...Object.fromEntries(calendars.map((calendar) => [calendar.id, on])) }));

  if (query.isLoading) return <div className="loading">Loading payout split…</div>;
  if (query.error) return <div className="error-banner">{query.error.message}</div>;

  return <div className="payout-split">
    <h2>Payout split</h2>
    <p>Customers pay into the main Stripe account. After each payment, the connected account receives a share of the <strong>ticket price</strong> of every product on an included calendar. Booking fees and taxes always stay in the main account.</p>
    <label className="field" style={{ maxWidth: 260 }}>
      <span>Connected account receives (% of ticket price)</span>
      <input type="number" min={0} max={100} step={0.5} value={percent} onChange={(event) => { setPercent(event.target.value); setSuccess(null); }} />
      {!valid && <small style={{ color: "#b42318" }}>Enter a percentage from 0 to 100.</small>}
    </label>
    {valid && <div className="payout-example">
      <span>Example: a {usd(EXAMPLE_TICKET)} ticket</span>
      <strong>Connected account {usd(share)}</strong>
      <strong>Main account {usd(EXAMPLE_TICKET - share)} + fees &amp; taxes</strong>
    </div>}
    <h3 style={{ marginTop: 20 }}>Calendars in the split <small className="muted-note">({includedCount} of {query.data?.calendars.length || 0})</small></h3>
    <p className="muted-note" style={{ marginTop: 0 }}>Bookings on calendars that are switched off keep 100% in the main account and can take payments even before the connected account is verified.</p>
    {groups.map(([category, calendars]) => <section key={category} className="payout-group">
      <header>
        <strong>{category}</strong>
        <span className="toolbar">
          <button type="button" className="button ghost small" onClick={() => setGroup(calendars, true)}>Include all</button>
          <button type="button" className="button ghost small" onClick={() => setGroup(calendars, false)}>Exclude all</button>
        </span>
      </header>
      {calendars.map((calendar) => <label key={calendar.id} className="check-field payout-row">
        <input type="checkbox" checked={Boolean(included[calendar.id])} onChange={(event) => { setIncluded({ ...included, [calendar.id]: event.target.checked }); setSuccess(null); }} />
        <span>{calendar.name}{!calendar.is_active && <small className="muted-note"> · inactive</small>}</span>
      </label>)}
    </section>)}
    <MutationNotice success={success} error={save.error} />
    <div className="dialog-actions"><button type="button" className="button" disabled={!valid || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save payout split"}</button></div>
  </div>;
}
