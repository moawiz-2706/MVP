import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Clock3, MapPin, Minus, Plus, ShieldCheck, ShoppingBag, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { AvailabilityResponse, AvailabilitySlot, PublicCalendar, PublicCatalog, PublicCustomField, PublicRate } from "../api/types";
import { PaymentPanel } from "./PaymentPanel";
import { PublicFrame } from "./OperatorBookingPage";
import { useEmbed, withEmbed } from "./embed";
import { formatDay, formatTime, safeTimeZone, tomorrowInZone } from "../lib/datetime";

interface CartItem { calendar_id: string; start_at: string; units: number; slot: AvailabilitySlot; rate_id?: string; rate?: PublicRate }
interface Quote { currency: string; subtotal_minor: number; platform_fee_and_taxes_minor: number; customer_total_minor: number; booking_fee_minor?: number; tax_minor?: number }
interface Created extends Quote { public_reference: string; status: string; client_secret: string | null; access_token?: string | null; quote: Quote }
const formatMoney = (value: number, currency = "usd") => new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(value / 100);

const COMMON_TIME_ZONES = [
  "UTC", "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York",
  "America/Toronto", "America/Sao_Paulo", "Atlantic/Reykjavik", "Europe/London", "Europe/Paris",
  "Europe/Berlin", "Europe/Athens", "Africa/Cairo", "Africa/Johannesburg", "Asia/Dubai",
  "Asia/Karachi", "Asia/Kolkata", "Asia/Bangkok", "Asia/Singapore", "Asia/Tokyo",
  "Australia/Sydney", "Pacific/Auckland",
];

function timeZoneOptions(defaultZone: string): string[] {
  const intlWithZones = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  const supported = intlWithZones.supportedValuesOf?.("timeZone") || COMMON_TIME_ZONES;
  return Array.from(new Set([defaultZone, ...supported])).sort((a, b) => a.localeCompare(b));
}

function cancellationCopy(calendar: PublicCalendar): string {
  const policy = calendar.booking_policy;
  if (!policy) return "Cancellation and rescheduling terms are set by the operator and shown before payment.";
  if (policy.cancellation_cutoff_minutes === 0 && policy.cancellation_fee_bps === 0) {
    return "Cancellations are reviewed by the operator. Weather closures follow the operator's weather policy.";
  }
  const hours = Math.max(1, Math.round(policy.cancellation_cutoff_minutes / 60));
  const fee = policy.cancellation_fee_bps ? ` A ${policy.cancellation_fee_bps / 100}% cancellation fee may apply.` : " No cancellation fee applies within the allowed window.";
  return `To avoid a cancellation fee, provide notice at least ${hours} hours before the appointment.${fee}`;
}

function weatherCopy(mode: string): string {
  if (mode === "full_refund") return "Weather cancellations receive a full refund.";
  if (mode === "credit") return "Weather cancellations receive an operator credit.";
  if (mode === "no_refund") return "Weather cancellations follow the operator's no-refund policy.";
  return "Weather cancellations are reviewed by the operator.";
}

export function CalendarBookingPage() {
  const { operatorSlug = "", calendarSlug = "" } = useParams();
  const navigate = useNavigate();
  const embed = useEmbed();
  const catalog = useQuery({ queryKey: ["public-catalog", operatorSlug], queryFn: () => api<PublicCatalog>(`/public/${operatorSlug}`), staleTime: 30_000 });
  const calendar = catalog.data?.calendars.find((item) => item.slug === calendarSlug);
  const defaultTimeZone = safeTimeZone(catalog.data?.time_zone);
  const [selectedTimeZone, setSelectedTimeZone] = useState("UTC");
  const timezoneInitialized = useRef(false);
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null);
  const [units, setUnits] = useState(1);
  const [selectedRateId, setSelectedRateId] = useState("");
  const [cart, setCart] = useState<CartItem[]>([]);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [policyAccepted, setPolicyAccepted] = useState(false);
  const [customFields, setCustomFields] = useState<Record<string, string | boolean>>({});
  const [created, setCreated] = useState<Created | null>(null);
  const [checkoutKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    if (defaultTimeZone && !timezoneInitialized.current) {
      timezoneInitialized.current = true;
      setSelectedTimeZone(defaultTimeZone);
    }
  }, [defaultTimeZone]);

  useEffect(() => {
    if (selectedTimeZone && !day) setDay(tomorrowInZone(selectedTimeZone));
  }, [selectedTimeZone, day]);

  const availability = useQuery({
    queryKey: ["availability", operatorSlug, calendarSlug, day, selectedTimeZone],
    queryFn: () => api<AvailabilityResponse>(`/public/${operatorSlug}/calendars/${calendarSlug}/availability?${new URLSearchParams({ date: day, timezone: selectedTimeZone })}`),
    enabled: Boolean(calendar && day && selectedTimeZone && calendar.public_booking_mode === "online"),
    staleTime: 3_000,
    gcTime: 60_000,
  });
  const rates = useQuery({
    queryKey: ["public-rates", operatorSlug, calendarSlug],
    queryFn: () => api<PublicRate[]>(`/public/${operatorSlug}/calendars/${calendarSlug}/rates`),
    enabled: Boolean(calendar),
    staleTime: 30_000,
  });
  const publicFields = useQuery({
    queryKey: ["public-custom-fields", operatorSlug, calendarSlug],
    queryFn: () => api<PublicCustomField[]>(`/public/${operatorSlug}/calendars/${calendarSlug}/custom-fields`),
    enabled: Boolean(calendar),
    staleTime: 30_000,
  });
  const selectedRate = rates.data?.find((rate) => rate.id === selectedRateId) || null;
  const selectedRateAvailability = slot?.rates?.find((rate) => rate.rate_id === selectedRateId);
  const maxAllowedUnits = selectedRateAvailability?.available_quantity ?? slot?.max_bookable_units ?? 1;
  const requestItems = useMemo(() => cart.map(({ calendar_id, start_at, units: itemUnits, rate_id }) => rate_id ? ({ calendar_id, start_at, quantity: itemUnits, rate_id }) : ({ calendar_id, start_at, units: itemUnits })), [cart]);
  const quote = useQuery({ queryKey: ["quote", operatorSlug, JSON.stringify(requestItems)], queryFn: () => api<Quote>(`/public/${operatorSlug}/orders/quote`, json("POST", { items: requestItems })), enabled: cart.length > 0 });
  const create = useMutation({
    mutationFn: () => api<Created>(`/public/${operatorSlug}/orders`, { ...json("POST", { items: requestItems, customer: { first_name: first, last_name: last, email, phone: phone || null, marketing_opt_in: marketingOptIn }, custom_fields: customFields }), headers: { "X-Checkout-Key": checkoutKey } }),
    onSuccess: (result) => {
      setCreated(result);
      const suffix = result.access_token ? `?access_token=${encodeURIComponent(result.access_token)}` : "";
      if (!result.client_secret) navigate(withEmbed(`/booking/${result.public_reference}/confirmation${suffix}`, embed));
    },
  });

  if (catalog.isLoading) return <div className="center-state"><div className="spinner" /></div>;
  if (!catalog.data || !calendar) return <div className="center-state"><div className="state-card"><h1>Calendar unavailable</h1><p>This booking calendar may be inactive or the link is incorrect.</p></div></div>;

  const add = () => {
    if (!slot || calendar.public_booking_mode !== "online") return;
    if (rates.data?.length && (!selectedRate || units > maxAllowedUnits)) return;
    setCart([...cart, { calendar_id: calendar.id, start_at: slot.start_at, units, slot, rate_id: selectedRate?.id, rate: selectedRate || undefined }]);
    setSlot(null);
    setUnits(1);
  };
  const zones = timeZoneOptions(defaultTimeZone);
  const policy = calendar.booking_policy;
  const requiresPolicyAcceptance = Boolean(policy || calendar.public_booking_mode === "online");

  return <PublicFrame name={catalog.data.name} embed={embed}>
    <div style={{ marginBottom: 20 }}><Link to={withEmbed(`/book/${operatorSlug}`, embed)} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#61706d" }}><ArrowLeft size={14} />All experiences</Link></div>
    <div className="public-hero" style={{ marginBottom: 25 }}><span className="eyebrow">{calendar.category_name || "Online booking"}</span><h1 style={{ fontSize: "clamp(27px,4vw,39px)" }}>{calendar.name}</h1><p>{calendar.description}</p><div className="service-meta" style={{ marginTop: 15, display: "flex", gap: 18 }}><span><Clock3 size={15} />{calendar.duration_minutes} minutes</span>{calendar.location && <span><MapPin size={15} />{calendar.location.name} · {calendar.location.address}</span>}</div></div>
    {calendar.public_booking_mode === "call_to_book" ? <div className="public-card booking-callout"><h2>Call to book</h2><p>This experience is available by phone so the operator can confirm the right equipment and schedule.</p>{calendar.call_to_book_phone && <a className="button" href={`tel:${calendar.call_to_book_phone}`}>Call {calendar.call_to_book_phone}</a>}</div> : calendar.public_booking_mode === "closed" ? <div className="public-card booking-callout"><h2>Online booking is closed</h2><p>Please contact the operator for the next available booking window.</p>{calendar.call_to_book_phone && <a className="button" href={`tel:${calendar.call_to_book_phone}`}>Call the operator</a>}</div> : created?.client_secret ? <div className="public-card" style={{ maxWidth: 620 }}><h2>Payment details</h2><p style={{ color: "#78827f", fontSize: 13, display: "flex", gap: 7, alignItems: "center" }}><ShieldCheck size={15} />Secured and encrypted payment</p><PaymentPanel clientSecret={created.client_secret} publicReference={created.public_reference} accessToken={created.access_token} embed={embed} /></div> : <div className="booking-panel">
      <section className="public-card"><h2>Choose a date and time</h2>
        <p style={{ fontSize: 12, color: "#78827f", marginTop: -6, marginBottom: 12 }}>Choose a time first, then select the equipment or customer type for your party.</p>
        <label className="field" style={{ marginBottom: 12 }}><span>Time zone</span><select value={selectedTimeZone} onChange={(event) => { setSelectedTimeZone(event.target.value); setSlot(null); }}><option value="" disabled>Select a time zone</option>{zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")} {zone === defaultTimeZone ? "(operator default)" : ""}</option>)}</select></label>
        <label className="field" style={{ maxWidth: 220, marginBottom: 17 }}><span>Date</span><input type="date" min={tomorrowInZone(selectedTimeZone)} value={day} onChange={(event) => { setDay(event.target.value); setSlot(null); }} /></label>
        {availability.isLoading ? <div className="loading">Checking live availability…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : <div className="slot-grid">{availability.data?.slots.map((item) => <button key={item.start_at} disabled={!item.available} className={`slot ${slot?.start_at === item.start_at ? "selected" : ""}`} onClick={() => { setSlot(item); setUnits(1); }}>{formatTime(item.start_at, selectedTimeZone)}<span>{item.available ? `${item.max_bookable_units} available` : item.status === "call_to_book" ? "Call to book" : item.status === "past_cutoff" ? "Booking closed" : item.status === "closed" ? "Closed" : item.status === "blocked" ? "Unavailable" : item.status === "staff_unavailable" ? "Crew unavailable" : "Sold out"}</span></button>)}</div>}
        {availability.data && !availability.data.slots.length && <div className="empty-state"><strong>No times on this date</strong><span>Choose another date to continue.</span></div>}
        {slot && <div style={{ marginTop: 20, paddingTop: 17, borderTop: "1px solid #e6e9e8" }}>{rates.data?.length ? <label className="field" style={{ marginBottom: 12 }}><span>Plan your experience</span><select required value={selectedRateId} onChange={(event) => { setSelectedRateId(event.target.value); setUnits(1); }}><option value="">Choose an option</option>{rates.data.map((rate) => <option key={rate.id} value={rate.id}>{rate.customer_type_name} · {formatMoney(rate.price_minor, calendar.currency)} · {rate.seat_count} seat{rate.seat_count === 1 ? "" : "s"}</option>)}</select>{selectedRate?.note && <small>{selectedRate.note}</small>}</label> : null}<div className="summary-row"><span>Quantity</span><div className="quantity"><button aria-label="Decrease quantity" onClick={() => setUnits(Math.max(1, units - 1))}><Minus size={14} /></button><strong>{units}</strong><button aria-label="Increase quantity" onClick={() => setUnits(Math.min(maxAllowedUnits, units + 1))}><Plus size={14} /></button></div></div><div className="summary-row"><span>Price</span><strong>{formatMoney(selectedRate?.price_minor ?? calendar.base_price_minor, calendar.currency)} each</strong></div><button className="button" style={{ width: "100%", marginTop: 12 }} disabled={Boolean(rates.data?.length && (!selectedRate || maxAllowedUnits < 1))} onClick={add}><ShoppingBag size={15} />Add to booking</button></div>}
      </section>
      <aside className="public-card"><h2>Your booking</h2>{cart.length === 0 ? <p style={{ fontSize: 12, color: "#78827f" }}>Select a time to begin.</p> : <>{cart.map((item, index) => <div key={`${item.start_at}-${index}`} style={{ padding: "10px 0", borderBottom: "1px solid #edf0ef", display: "flex", justifyContent: "space-between", gap: 10 }}><div className="cell-title"><strong>{formatDay(item.start_at, selectedTimeZone)} · {formatTime(item.start_at, selectedTimeZone)}</strong><span>{item.units} × {item.rate?.customer_type_name || calendar.name}</span></div><button className="icon-button" aria-label="Remove booking item" onClick={() => setCart(cart.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={14} /></button></div>)}{quote.data && <div style={{ marginTop: 10 }}><div className="summary-row"><span>Subtotal</span><span>{formatMoney(quote.data.subtotal_minor, quote.data.currency)}</span></div><div className="summary-row"><span>Taxes & fees</span><span>{formatMoney(quote.data.booking_fee_minor !== undefined ? (quote.data.booking_fee_minor + (quote.data.tax_minor || 0)) : quote.data.platform_fee_and_taxes_minor, quote.data.currency)}</span></div><div className="summary-row total"><span>Total</span><span>{formatMoney(quote.data.customer_total_minor, quote.data.currency)}</span></div></div>}<form onSubmit={(event: FormEvent) => { event.preventDefault(); if (!policyAccepted && requiresPolicyAcceptance) return; create.mutate(); }} style={{ marginTop: 17 }}><h3 style={{ margin: "20px 0 10px", fontSize: 15 }}>Contact details</h3><div className="form-grid"><label className="field"><span>First name</span><input required value={first} onChange={(event) => setFirst(event.target.value)} /></label><label className="field"><span>Last name</span><input required value={last} onChange={(event) => setLast(event.target.value)} /></label><label className="field full"><span>Email address</span><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label className="field full"><span>Phone number</span><input required value={phone} onChange={(event) => setPhone(event.target.value)} /></label>{publicFields.data?.map((field) => <label className="field full" key={field.id}><span>{field.label}{field.required ? " *" : ""}</span>{field.field_type === "textarea" ? <textarea required={field.required} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })} /> : field.field_type === "select" ? <select required={field.required} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })}><option value="">Choose…</option>{(field.options || []).map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select> : field.field_type === "boolean" ? <input type="checkbox" checked={Boolean(customFields[field.key])} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.checked })} /> : <input required={field.required} type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })} />}</label>)}</div><label className="checkbox-row"><input type="checkbox" checked={marketingOptIn} onChange={(event) => setMarketingOptIn(event.target.checked)} /><span>Send me marketing emails from {catalog.data.name} and its partners</span></label><section className="policy-box"><h3>Cancellation policy</h3><p>{cancellationCopy(calendar)}</p>{policy && <p>{weatherCopy(policy.weather_refund_mode)} {policy.reschedule_cutoff_minutes ? `Rescheduling requires at least ${Math.max(1, Math.round(policy.reschedule_cutoff_minutes / 60))} hours notice.` : ""}</p>}{policy?.requires_waiver && <p>A waiver is required before this activity. You will receive a secure signing link after booking.</p>}<label className="checkbox-row"><input type="checkbox" required={requiresPolicyAcceptance} checked={policyAccepted} onChange={(event) => setPolicyAccepted(event.target.checked)} /><span>I agree to the cancellation policy and booking terms.</span></label></section>{create.error && <div className="error-banner" style={{ marginTop: 12 }}>{create.error.message}</div>}<button className="button" style={{ width: "100%", marginTop: 15 }} disabled={create.isPending || quote.isLoading || (requiresPolicyAcceptance && !policyAccepted)}>{create.isPending ? "Reserving inventory…" : "Book and pay"}</button></form></>}</aside>
    </div>}
  </PublicFrame>;
}
