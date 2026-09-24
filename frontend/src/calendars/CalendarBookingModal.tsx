import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus, ShoppingBag } from "lucide-react";
import { useEffect, useState } from "react";
import { api, json } from "../api/client";
import { useSession } from "../auth/GHLSessionProvider";
import type { AvailabilityResponse, AvailabilitySlot, Calendar, CalendarRate } from "../api/types";
import { PaymentPanel } from "../public-booking/PaymentPanel";
import { formatTime, tomorrowInZone, zoneLabel } from "../lib/datetime";

interface OrderCreateResponse { public_reference: string; status: string; client_secret: string | null; access_token?: string | null }

export function CalendarBookingModal({ calendar, onDone }: { calendar: Calendar; onDone: () => void }) {
  const client = useQueryClient();
  const { me } = useSession();
  const timeZone = me.operator.time_zone;
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null);
  const [rateId, setRateId] = useState("");
  const [units, setUnits] = useState(1);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [created, setCreated] = useState<OrderCreateResponse | null>(null);
  useEffect(() => { if (timeZone && !day) setDay(tomorrowInZone(timeZone)); }, [timeZone, day]);
  const rates = useQuery({ queryKey: ["calendar-rates", calendar.id], queryFn: () => api<CalendarRate[]>(`/calendars/${calendar.id}/rates`) });
  const availability = useQuery({ queryKey: ["calendar-availability", calendar.id, day], queryFn: () => api<AvailabilityResponse>(`/calendars/${calendar.id}/availability?date=${day}`), enabled: Boolean(day) });
  const selectedRate = rates.data?.find((rate) => rate.id === rateId) || rates.data?.[0];
  useEffect(() => { if (!rateId && selectedRate) setRateId(selectedRate.id); }, [rateId, selectedRate]);
  const slotLimit = slot?.rates?.find((rate) => rate.rate_id === (selectedRate?.id || rateId))?.available_quantity || slot?.max_bookable_units || 0;
  const create = useMutation({ mutationFn: () => { if (!slot) throw new Error("Choose an available time first."); return api<OrderCreateResponse>("/bookings", json("POST", { items: [{ calendar_id: calendar.id, start_at: slot.start_at, units, rate_id: selectedRate?.id || null }], customer: { first_name: first.trim(), last_name: last.trim(), email: email.trim(), phone: phone.trim() || null } })); }, onSuccess: async (result) => { setCreated(result); await client.invalidateQueries({ queryKey: ["bookings"] }); } });
  if (created?.client_secret) return <div><p className="muted-note">Inventory is held while payment is completed.</p><PaymentPanel clientSecret={created.client_secret} publicReference={created.public_reference} accessToken={created.access_token} /></div>;
  if (created) return <div><div className="success-banner">Booking {created.public_reference} was created successfully.</div><div className="dialog-actions"><button className="button" onClick={onDone}>Done</button></div></div>;
  const selectSlot = (value: AvailabilitySlot) => { setSlot(value); const limit = value.rates?.find((rate) => rate.rate_id === (selectedRate?.id || rateId))?.available_quantity || value.max_bookable_units; setUnits(Math.min(1, limit)); };
  const selectRate = (value: string) => { setRateId(value); if (slot) { const limit = slot.rates?.find((rate) => rate.rate_id === value)?.available_quantity || slot.max_bookable_units; setUnits(Math.min(units, limit || 1)); } };
  return <div><p className="muted-note" style={{ marginTop: -5, marginBottom: 14 }}>Live availability for <strong>{calendar.name}</strong>. Select a date to see every valid slot in {zoneLabel(timeZone)} ({timeZone}).</p><label className="field" style={{ maxWidth: 220, marginBottom: 17 }}><span>Date</span><input type="date" min={tomorrowInZone(timeZone)} value={day} onChange={(event) => { setDay(event.target.value); setSlot(null); }} /></label>{availability.isLoading ? <div className="loading">Checking live availability…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : <div className="slot-grid">{availability.data?.slots.map((item) => <button type="button" key={item.start_at} disabled={!item.available} className={`slot ${slot?.start_at === item.start_at ? "selected" : ""}`} onClick={() => selectSlot(item)}>{formatTime(item.start_at, timeZone)}<span>{item.available ? `${item.max_bookable_units} available` : "Unavailable"}</span></button>)}</div>}{availability.data && !availability.data.slots.length && <div className="empty-state"><strong>No times on this date</strong><span>Choose another date to continue.</span></div>}{slot && <div style={{ marginTop: 20, paddingTop: 17, borderTop: "1px solid #e6e9e8" }}><label className="field"><span>Customer type / rate</span><select value={selectedRate?.id || ""} onChange={(event) => selectRate(event.target.value)} disabled={!rates.data?.length}>{rates.data?.length ? rates.data.map((rate) => <option key={rate.id} value={rate.id}>{rate.customer_type_name} — {new Intl.NumberFormat(undefined, { style: "currency", currency: calendar.currency.toUpperCase() }).format(rate.price_minor / 100)}</option>) : <option value="">Base calendar price</option>}</select></label><div className="summary-row"><span>Quantity</span><div className="quantity"><button type="button" onClick={() => setUnits(Math.max(1, units - 1))}><Minus size={14} /></button><strong>{units}</strong><button type="button" disabled={units >= slotLimit} onClick={() => setUnits(Math.min(slotLimit, units + 1))}><Plus size={14} /></button></div></div><div className="summary-row"><span>Available for selected rate</span><strong>{slotLimit}</strong></div><div className="summary-row"><span>Price</span><strong>{new Intl.NumberFormat(undefined, { style: "currency", currency: calendar.currency.toUpperCase() }).format(((selectedRate?.price_minor ?? calendar.base_price_minor) * units) / 100)}</strong></div><div className="form-grid" style={{ marginTop: 15 }}><label className="field"><span>First name</span><input required value={first} onChange={(event) => setFirst(event.target.value)} /></label><label className="field"><span>Last name</span><input required value={last} onChange={(event) => setLast(event.target.value)} /></label><label className="field full"><span>Email</span><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label className="field full"><span>Phone (optional)</span><input value={phone} onChange={(event) => setPhone(event.target.value)} /></label></div>{create.error && <div className="error-banner" style={{ marginTop: 12 }}>{create.error.message}</div>}<button type="button" className="button" style={{ width: "100%", marginTop: 15 }} disabled={create.isPending || !slotLimit} onClick={() => create.mutate()}><ShoppingBag size={15} />{create.isPending ? "Reserving inventory…" : "Create booking"}</button></div>}</div>;
}
