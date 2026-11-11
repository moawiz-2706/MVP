import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, json } from "../api/client";
import type { AvailabilityResponse, AvailabilitySlot, Calendar, CalendarRate } from "../api/types";
import { useSession } from "../auth/GHLSessionProvider";
import { GuestDetailsQr } from "../components/GuestDetailsQr";
import { PartnerSelect } from "../components/PartnerSelect";
import { WaiverModeSelect, type WaiverMode } from "../components/WaiverModeSelect";
import { formatLongDate, formatTime, isoDayInZone, tomorrowInZone } from "../lib/datetime";
import { PaymentPanel } from "../public-booking/PaymentPanel";
import { isEmbeddedInHighLevel } from "../pwa";

interface CreatedOrder { public_reference: string; status: string; client_secret: string | null; invoice_url?: string | null; invoice_status?: string | null; payment_method?: string; access_token?: string | null }
interface BookingField { id: string; key: string; label: string; field_type: string; required: boolean; options: unknown[] | null }
type PaymentMethod = "card" | "invoice" | "none";
/** A departure chosen on the staff PWA board, used to preselect the form. */
export interface BookingPreset { calendarId: string; startAt: string }
/** One product in the booking: a calendar, time and rate. */
interface CartLine { key: string; calendar_id: string; calendar_name: string; currency: string; start_at: string; units: number; rate_id: string | null; rate_label: string; price_minor: number }

function money(value: number, currency = "usd") {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(value / 100);
}

/** Passport/PWA "New booking": add one or more products, then book them as one order. */
export function NewBookingForm({ calendars, onDone, preset }: { calendars: Calendar[]; onDone: () => void; preset?: BookingPreset | null }) {
  const { me } = useSession();
  const tz = me.operator.time_zone;
  const client = useQueryClient();
  // The staff PWA books same-day departures; the embedded desktop keeps its
  // existing next-day minimum.
  const earliestDay = !isEmbeddedInHighLevel() && tz ? isoDayInZone(new Date(), tz) : tomorrowInZone(tz);
  const [calendarId, setCalendarId] = useState(preset?.calendarId || calendars[0]?.id || "");
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null);
  const [rateId, setRateId] = useState("");
  const [units, setUnits] = useState(1);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [first, setFirst] = useState(""); const [last, setLast] = useState(""); const [email, setEmail] = useState(""); const [phone, setPhone] = useState("");
  const [customFields, setCustomFields] = useState<Record<string, string | boolean>>({});
  // Invoice stays the default for team bookings; card and free are available too.
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("invoice");
  const [waiverMode, setWaiverMode] = useState<WaiverMode>("party");
  const [partnerId, setPartnerId] = useState("");
  const [created, setCreated] = useState<CreatedOrder | null>(null);
  useEffect(() => { if (tz && !day) setDay(preset ? isoDayInZone(new Date(preset.startAt), tz) : tomorrowInZone(tz)); }, [tz, day, preset]);

  const rates = useQuery({ queryKey: ["calendar-rates", calendarId], queryFn: () => api<CalendarRate[]>(`/calendars/${calendarId}/rates`), enabled: Boolean(calendarId) });
  const availability = useQuery({ queryKey: ["calendar-availability", calendarId, day], queryFn: () => api<AvailabilityResponse>(`/calendars/${calendarId}/availability?date=${day}`), enabled: Boolean(calendarId && day) });
  const calendar = calendars.find((item) => item.id === calendarId);
  const activeRates = (rates.data || []).filter((rate) => rate.is_active);
  const selectedRate = activeRates.find((rate) => rate.id === rateId) || activeRates[0];
  const liveSlot = slot ? availability.data?.slots.find((item) => item.start_at === slot.start_at) || slot : null;
  const rawLimit = liveSlot?.rates?.find((rate) => rate.rate_id === (selectedRate?.id || rateId))?.available_quantity ?? liveSlot?.max_bookable_units ?? 0;
  const inCart = cart.filter((line) => line.calendar_id === calendarId && line.start_at === liveSlot?.start_at && (line.rate_id || "") === (selectedRate?.id || "")).reduce((sum, line) => sum + line.units, 0);
  const slotLimit = Math.max(0, rawLimit - inCart);
  useEffect(() => { if (!rateId && selectedRate) setRateId(selectedRate.id); }, [rateId, selectedRate]);

  // Select the preset departure once its availability has loaded.
  const [presetApplied, setPresetApplied] = useState(false);
  useEffect(() => {
    if (!preset || presetApplied || !availability.data || calendarId !== preset.calendarId) return;
    const target = availability.data.slots.find((item) => new Date(item.start_at).getTime() === new Date(preset.startAt).getTime() && item.available);
    if (target) setSlot(target);
    setPresetApplied(true);
  }, [preset, presetApplied, availability.data, calendarId]);

  // Booking questions for every product in the booking, each asked once.
  const cartCalendarIds = useMemo(() => [...new Set(cart.map((line) => line.calendar_id))], [cart]);
  const fieldQueries = useQueries({ queries: cartCalendarIds.map((id) => ({ queryKey: ["booking-fields", id], queryFn: () => api<BookingField[]>(`/booking-custom-fields?calendar_id=${id}`) })) });
  const fields = useMemo(() => {
    const seen = new Map<string, BookingField>();
    for (const query of fieldQueries) for (const field of query.data || []) if (!seen.has(field.key)) seen.set(field.key, field);
    return [...seen.values()];
  }, [fieldQueries]);

  const guests = cart.reduce((sum, line) => sum + line.units, 0);
  const currency = cart[0]?.currency || calendar?.currency || "usd";
  const total = cart.reduce((sum, line) => sum + line.price_minor * line.units, 0);

  const mutation = useMutation({
    mutationFn: () => {
      if (!cart.length) throw new Error("Add at least one product to the booking.");
      return api<CreatedOrder>("/bookings", json("POST", { items: cart.map((line) => ({ calendar_id: line.calendar_id, start_at: line.start_at, units: line.units, rate_id: line.rate_id })), customer: { first_name: first, last_name: last, email, phone: phone || null }, custom_fields: customFields, payment_method: paymentMethod, partner_id: partnerId || null, waiver_mode: waiverMode }));
    },
    onSuccess: async (result) => { setCreated(result); await Promise.all([client.invalidateQueries({ queryKey: ["bookings"] }), client.invalidateQueries({ queryKey: ["booking-notifications"] })]); },
  });

  const addToBooking = () => {
    if (!liveSlot || !calendar || units < 1 || units > slotLimit) return;
    const price = selectedRate?.price_minor ?? calendar.base_price_minor ?? 0;
    const label = selectedRate ? (units === 1 ? selectedRate.customer_type_name : selectedRate.customer_type_plural_name || selectedRate.customer_type_name) : "Booking";
    setCart((previous) => {
      const match = previous.find((line) => line.calendar_id === calendar.id && line.start_at === liveSlot.start_at && line.rate_id === (selectedRate?.id || null));
      if (match) return previous.map((line) => line === match ? { ...line, units: line.units + units, rate_label: selectedRate?.customer_type_plural_name || line.rate_label } : line);
      return [...previous, { key: crypto.randomUUID(), calendar_id: calendar.id, calendar_name: calendar.name, currency: calendar.currency, start_at: liveSlot.start_at, units, rate_id: selectedRate?.id || null, rate_label: label, price_minor: price }];
    });
    setUnits(1);
    mutation.reset();
  };
  // Keep the activity and date; clear the booking so the next one starts fresh.
  const bookAnother = () => { setCreated(null); setSlot(null); setUnits(1); setCart([]); setFirst(""); setLast(""); setEmail(""); setPhone(""); setCustomFields({}); setPartnerId(""); setWaiverMode("party"); mutation.reset(); };
  const qr = (reference: string) => <GuestDetailsQr linkPath={`/bookings/orders/${encodeURIComponent(reference)}/party-link`} reference={reference} />;

  if (created?.client_secret) return <div><p className="muted-note">A card payment is required for this booking.</p><PaymentPanel clientSecret={created.client_secret} publicReference={created.public_reference} accessToken={created.access_token} staffReturn="/app/bookings?new=1" /></div>;
  if (created) return <div>{created.invoice_url ? <><div className="success-banner">Booking {created.public_reference} is pending invoice payment.</div><p className="muted-note">The client must pay the hosted Stripe invoice before this appointment is confirmed.</p><a className="button" href={created.invoice_url} target="_blank" rel="noreferrer">Open invoice</a></> : <div className="success-banner">Booking {created.public_reference} was created successfully.</div>}{qr(created.public_reference)}<div className="dialog-actions"><button className="button secondary" onClick={bookAnother}>Book another</button><button className="button" onClick={onDone}>Done</button></div></div>;

  const selectSlot = (value: AvailabilitySlot) => { const firstAvailableRate = value.rates?.find((rate) => rate.available_quantity > 0); if (firstAvailableRate && (!selectedRate || (value.rates?.find((rate) => rate.rate_id === selectedRate.id)?.available_quantity ?? 0) < 1)) setRateId(firstAvailableRate.rate_id); setSlot(value); setUnits(1); };
  const changeCalendar = (value: string) => { setCalendarId(value); setSlot(null); setRateId(""); setUnits(1); };

  return <form onSubmit={(e: FormEvent) => { e.preventDefault(); mutation.mutate(); }}>
    <p className="muted-note" style={{ marginTop: 0, marginBottom: 12 }}>Add one or more products from Passport’s live availability, then enter the client once. Staff assignment remains an operational step and does not block a valid booking.</p>
    <section className="staff-step" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
      <h2>{cart.length ? "Add another product" : "Choose a product"}</h2>
      <div className="form-grid"><label className="field full"><span>Calendar</span><select required value={calendarId} onChange={(e) => changeCalendar(e.target.value)}>{calendars.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="field"><span>Date</span><input type="date" min={earliestDay} required value={day} onChange={(e) => { setDay(e.target.value); setSlot(null); }} /></label></div>
      {availability.isLoading ? <div className="loading">Checking live availability…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : <div className="slot-grid">{availability.data?.slots.filter((item) => item.available).map((item) => <button type="button" key={item.start_at} className={`slot ${slot?.start_at === item.start_at ? "selected" : ""}`} onClick={() => selectSlot(item)}>{formatTime(item.start_at, tz)}{item.rates?.length ? <span className="slot-rate-summary">{item.rates.map((rate) => <span key={rate.rate_id}>{rate.customer_type_name}: {rate.available_quantity} available</span>)}</span> : <span>{item.max_bookable_units} available</span>}</button>)}</div>}
      {availability.data && !availability.data.slots.some((item) => item.available) && <div className="empty-state"><strong>No available times on this date</strong><span>Choose another date to continue.</span></div>}
      {liveSlot && <div className="staff-add">
        <div className="staff-booking-summary"><strong>{formatTime(liveSlot.start_at, tz)} selected</strong><span>{slotLimit} more available{inCart ? ` (${inCart} already added)` : ""}</span></div>
        <label className="field"><span>Customer type / rate</span><select value={selectedRate?.id || ""} onChange={(e) => { setRateId(e.target.value); setUnits(1); }} disabled={!activeRates.length}>{activeRates.length ? activeRates.map((rate) => <option key={rate.id} value={rate.id}>{rate.customer_type_name} — {money(rate.price_minor, calendar?.currency)}</option>) : <option value="">Base calendar price</option>}</select></label>
        <div className="summary-row"><span>Quantity</span><div className="quantity"><button type="button" onClick={() => setUnits(Math.max(1, units - 1))}>−</button><strong>{units}</strong><button type="button" disabled={units >= slotLimit} onClick={() => setUnits(Math.min(slotLimit, units + 1))}>+</button></div></div>
        <div className="summary-row"><span>Price</span><strong>{money((selectedRate?.price_minor ?? calendar?.base_price_minor ?? 0) * units, calendar?.currency)}</strong></div>
        <button type="button" className="button secondary" style={{ width: "100%", marginTop: 10 }} disabled={slotLimit < 1 || units > slotLimit} onClick={addToBooking}><Plus size={15} />{slotLimit < 1 ? "No more available at this time" : "Add to booking"}</button>
      </div>}
    </section>
    {cart.length > 0 && <>
      <section className="staff-step">
        <h2>Booking ({cart.length} {cart.length === 1 ? "item" : "items"})</h2>
        <ul className="staff-cart">{cart.map((line) => <li key={line.key}>
          <div><strong>{line.calendar_name}</strong><span>{formatLongDate(line.start_at, tz)} · {formatTime(line.start_at, tz)}</span><span>{line.units} × {line.rate_label} · {money(line.price_minor * line.units, line.currency)}</span></div>
          <button type="button" className="icon-button" aria-label={`Remove ${line.calendar_name}`} title="Remove" onClick={() => setCart(cart.filter((item) => item.key !== line.key))}><Trash2 size={15} /></button>
        </li>)}</ul>
        <div className="summary-row"><span>Subtotal</span><strong>{money(total, currency)}</strong></div>
        <small className="muted-note">Booking fees and taxes are added when the booking is created.</small>
      </section>
      <section className="staff-step">
        <h2>Client details</h2>
        <div className="form-grid"><label className="field"><span>First name</span><input required value={first} onChange={(e) => setFirst(e.target.value)} /></label><label className="field"><span>Last name</span><input required value={last} onChange={(e) => setLast(e.target.value)} /></label><label className="field full"><span>Email</span><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label><label className="field full"><span>Phone (optional)</span><input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></label>{fields.map((field) => <label className="field full" key={field.id}><span>{field.label}{field.required ? " *" : ""}</span>{field.field_type === "select" ? <select required={field.required} value={String(customFields[field.key] || "")} onChange={(e) => setCustomFields({ ...customFields, [field.key]: e.target.value })}><option value="">Choose…</option>{(field.options || []).map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select> : field.field_type === "boolean" ? <input type="checkbox" checked={Boolean(customFields[field.key])} onChange={(e) => setCustomFields({ ...customFields, [field.key]: e.target.checked })} /> : field.field_type === "textarea" ? <textarea required={field.required} value={String(customFields[field.key] || "")} onChange={(e) => setCustomFields({ ...customFields, [field.key]: e.target.value })} /> : <input required={field.required} type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"} value={String(customFields[field.key] || "")} onChange={(e) => setCustomFields({ ...customFields, [field.key]: e.target.value })} />}</label>)}</div>
        <PartnerSelect value={partnerId} onChange={setPartnerId} />
        <WaiverModeSelect value={waiverMode} onChange={setWaiverMode} guests={guests} />
        <label className="field full"><span>Payment method</span><select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value as PaymentMethod)}><option value="card">Card — collect payment now</option><option value="invoice">Invoice — send payment request</option><option value="none">Free booking — no payment</option></select><small>{paymentMethod === "card" ? "Reserve the booking, then collect card payment securely with Stripe." : paymentMethod === "invoice" ? "Create the booking and send the client a hosted Stripe invoice." : "Confirm the booking immediately without collecting payment."}</small></label>
        {mutation.error && <div className="error-banner" style={{ marginTop: 12 }}>{mutation.error.message}</div>}
        <div className="dialog-actions"><button type="button" className="button secondary" onClick={onDone}>Cancel</button><button className="button" disabled={mutation.isPending}>{mutation.isPending ? "Reserving inventory…" : paymentMethod === "card" ? "Reserve and collect card payment" : paymentMethod === "invoice" ? "Create booking and send invoice" : "Create free booking"}</button></div>
      </section>
    </>}
  </form>;
}
