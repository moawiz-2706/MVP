import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { AvailabilityResponse, AvailabilitySlot, Calendar, PublicCustomField, PublicRate } from "../api/types";
import { formatTime, tomorrowInZone } from "../lib/datetime";

interface StaffBookingContext { staff_id: string; staff_name: string; operator_name: string; time_zone: string; calendars: Calendar[] }
interface CreatedOrder { public_reference: string; status: string; client_secret: string | null; invoice_url?: string | null; invoice_status?: string | null; payment_method?: string }

function money(value: number, currency = "usd") {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(value / 100);
}

export function StaffBookingPage() {
  const { token = "" } = useParams();
  const context = useQuery({ queryKey: ["staff-booking-context", token], queryFn: () => api<StaffBookingContext>(`/staff-booking/${encodeURIComponent(token)}/context`), enabled: Boolean(token), retry: false });
  const data = context.data;
  const tz = data?.time_zone || "UTC";
  const [calendarId, setCalendarId] = useState("");
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null);
  const [rateId, setRateId] = useState("");
  const [units, setUnits] = useState(1);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [customFields, setCustomFields] = useState<Record<string, string | boolean>>({});
  const [paymentRequired, setPaymentRequired] = useState(true);
  const [created, setCreated] = useState<CreatedOrder | null>(null);
  const [checkoutKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    if (data && !calendarId) setCalendarId(data.calendars[0]?.id || "");
    if (data && !day) setDay(tomorrowInZone(tz));
  }, [data, calendarId, day, tz]);

  const calendar = data?.calendars.find((item) => item.id === calendarId);
  const availability = useQuery({ queryKey: ["staff-booking-availability", token, calendarId, day], queryFn: () => api<AvailabilityResponse>(`/staff-booking/${encodeURIComponent(token)}/calendars/${calendarId}/availability?date=${day}`), enabled: Boolean(token && calendarId && day), staleTime: 10000, refetchInterval: 30000, refetchIntervalInBackground: false, refetchOnWindowFocus: true });
  const rates = useQuery({ queryKey: ["staff-booking-rates", token, calendarId], queryFn: () => api<PublicRate[]>(`/staff-booking/${encodeURIComponent(token)}/calendars/${calendarId}/rates`), enabled: Boolean(token && calendarId), staleTime: 30000 });
  const fields = useQuery({ queryKey: ["staff-booking-fields", token, calendarId], queryFn: () => api<PublicCustomField[]>(`/staff-booking/${encodeURIComponent(token)}/calendars/${calendarId}/custom-fields`), enabled: Boolean(token && calendarId), staleTime: 30000 });
  const selectedRate = rates.data?.find((rate) => rate.id === rateId) || rates.data?.[0];
  const liveSlot = slot ? availability.data?.slots.find((item) => item.start_at === slot.start_at) || slot : null;
  const selectedRateAvailability = liveSlot?.rates?.find((item) => item.rate_id === (selectedRate?.id || rateId));
  const slotLimit = selectedRateAvailability?.available_quantity ?? liveSlot?.max_bookable_units ?? 0;

  useEffect(() => {
    if (!rateId && selectedRate) setRateId(selectedRate.id);
  }, [rateId, selectedRate]);

  const create = useMutation({
    mutationFn: () => {
      if (!liveSlot || !calendarId) throw new Error("Choose an available slot first.");
      return api<CreatedOrder>(`/staff-booking/${encodeURIComponent(token)}/orders`, { ...json("POST", { items: [{ calendar_id: calendarId, start_at: liveSlot.start_at, units, rate_id: selectedRate?.id || null }], customer: { first_name: first.trim(), last_name: last.trim(), email: email.trim(), phone: phone.trim() || null }, custom_fields: customFields, payment_required: paymentRequired }), headers: { "X-Staff-Booking-Key": checkoutKey } });
    },
    onSuccess: (result) => setCreated(result),
  });

  if (context.isLoading) return <main className="public-main"><div className="center-state"><div className="spinner" /></div></main>;
  if (context.error || !data) return <main className="public-main"><div className="center-state"><div className="state-card"><h1>Private staff link unavailable</h1><p>{context.error?.message || "This link may have expired, been revoked, or the staff member may be inactive."}</p></div></div></main>;
  if (created) return <main className="public-main"><div className="public-card staff-booking-mobile-card"><span className="eyebrow">Staff booking</span><h1>{created.payment_method === "invoice" ? (created.invoice_url ? "Invoice sent" : "Invoice delivery pending") : "Appointment booked"}</h1>{created.payment_method === "invoice" ? <><div className="success-banner">Booking {created.public_reference} is pending invoice payment.</div><p className="muted-note">{created.invoice_url ? "Stripe has accepted the invoice for delivery to the customer’s email. The appointment will be confirmed automatically after payment." : "The booking is safely held and the invoice delivery job will retry automatically. Check the outbox/worker logs if the customer does not receive it."}</p>{created.invoice_url && <a className="button" href={created.invoice_url} target="_blank" rel="noreferrer">Open invoice</a>}</> : <div className="success-banner">Booking {created.public_reference} was created as a free appointment.</div>}<p className="muted-note">You can close this page after sharing the invoice with the client, if payment is required.</p></div></main>;

  const selectSlot = (value: AvailabilitySlot) => {
    setSlot(value);
    const limit = value.rates?.find((item) => item.rate_id === (selectedRate?.id || rateId))?.available_quantity ?? value.max_bookable_units;
    setUnits(Math.min(1, limit));
  };
  const resetCalendar = (value: string) => { setCalendarId(value); setDay(tomorrowInZone(tz)); setSlot(null); setRateId(""); setCustomFields({}); };

  return <main className="public-main"><div className="public-card staff-booking-mobile-card"><span className="eyebrow">Private staff booking</span><h1>Book for a client</h1><p className="muted-note">Staff member: <strong>{data.staff_name}</strong> · {data.operator_name}</p><p className="muted-note">Choose only a live available slot. The client’s card details are never collected here.</p><label className="field"><span>Calendar</span><select required value={calendarId} onChange={(event) => resetCalendar(event.target.value)}>{data.calendars.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="field"><span>Date</span><input type="date" min={tomorrowInZone(tz)} required value={day} onChange={(event) => { setDay(event.target.value); setSlot(null); }} /></label>{availability.isLoading ? <div className="loading">Checking live availability…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : <div className="slot-grid">{availability.data?.slots.filter((item) => item.available).map((item) => <button type="button" key={item.start_at} className={`slot ${slot?.start_at === item.start_at ? "selected" : ""}`} onClick={() => selectSlot(item)}>{formatTime(item.start_at, tz)}<span>{item.max_bookable_units} available</span></button>)}</div>}{availability.data && !availability.data.slots.some((item) => item.available) && <div className="empty-state"><strong>No available times on this date</strong><span>Choose another date.</span></div>}{liveSlot && <form onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate(); }}><div className="staff-booking-summary"><strong>{formatTime(liveSlot.start_at, tz)} selected</strong><span>{slotLimit} available for this booking</span></div><label className="field"><span>Customer type / rate</span><select value={selectedRate?.id || ""} onChange={(event) => { setRateId(event.target.value); setUnits(1); }} disabled={!rates.data?.length}>{rates.data?.length ? rates.data.map((rate) => <option key={rate.id} value={rate.id}>{rate.customer_type_name} — {money(rate.price_minor, calendar?.currency)}</option>) : <option value="">Base calendar price</option>}</select></label><div className="summary-row"><span>Quantity</span><div className="quantity"><button type="button" onClick={() => setUnits(Math.max(1, units - 1))}>−</button><strong>{units}</strong><button type="button" disabled={units >= slotLimit} onClick={() => setUnits(Math.min(slotLimit, units + 1))}>+</button></div></div><div className="summary-row"><span>Price</span><strong>{money((selectedRate?.price_minor ?? calendar?.base_price_minor ?? 0) * units, calendar?.currency)}</strong></div><div className="form-grid" style={{ marginTop: 15 }}><label className="field"><span>First name</span><input required value={first} onChange={(event) => setFirst(event.target.value)} /></label><label className="field"><span>Last name</span><input required value={last} onChange={(event) => setLast(event.target.value)} /></label><label className="field full"><span>Email</span><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label className="field full"><span>Phone (optional)</span><input value={phone} onChange={(event) => setPhone(event.target.value)} /></label>{fields.data?.map((field) => <label className="field full" key={field.id}><span>{field.label}{field.required ? " *" : ""}</span>{field.field_type === "textarea" ? <textarea required={field.required} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })} /> : field.field_type === "select" ? <select required={field.required} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })}><option value="">Choose…</option>{(field.options || []).map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select> : field.field_type === "boolean" ? <input type="checkbox" checked={Boolean(customFields[field.key])} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.checked })} /> : <input required={field.required} type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })} />}</label>)}</div><label className="check-field"><input type="checkbox" checked={paymentRequired} onChange={(event) => setPaymentRequired(event.target.checked)} /><span><strong>{paymentRequired ? "Send invoice to client" : "Book appointment for free"}</strong><small>{paymentRequired ? "The client receives a secure hosted invoice. The appointment remains pending until payment." : "The appointment is confirmed immediately. No invoice is created."}</small></span></label>{create.error && <div className="error-banner">{create.error.message}</div>}<button className="button" style={{ width: "100%", marginTop: 16 }} disabled={create.isPending || !slotLimit}>{create.isPending ? "Booking…" : paymentRequired ? "Create booking and send invoice" : "Book free appointment"}</button></form>}</div></main>;
}
