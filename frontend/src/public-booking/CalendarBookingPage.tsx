import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Clock3, MapPin, Minus, Plus, ShoppingBag, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { AvailabilityResponse, AvailabilitySlot, PublicCalendar, PublicCatalog } from "../api/types";
import { PaymentPanel } from "./PaymentPanel";
import { PublicFrame } from "./OperatorBookingPage";
import { useEmbed, withEmbed } from "./embed";
import { formatDay, formatTime, tomorrowInZone, zoneLabel } from "../lib/datetime";

interface CartItem { calendar_id: string; start_at: string; units: number; slot: AvailabilitySlot }
interface Quote { currency: string; subtotal_minor: number; platform_fee_and_taxes_minor: number; customer_total_minor: number }
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

export function CalendarBookingPage() {
  const { operatorSlug = "", calendarSlug = "" } = useParams();
  const navigate = useNavigate();
  const embed = useEmbed();
  const catalog = useQuery({ queryKey: ["public-catalog", operatorSlug], queryFn: () => api<PublicCatalog>(`/public/${operatorSlug}`) });
  const calendar = catalog.data?.calendars.find((item) => item.slug === calendarSlug);
  const defaultTimeZone = catalog.data?.time_zone ?? "";
  const [selectedTimeZone, setSelectedTimeZone] = useState("");
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null);
  const [units, setUnits] = useState(1);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [checkoutKey] = useState(() => crypto.randomUUID());

  useEffect(() => {
    if (defaultTimeZone && !selectedTimeZone) setSelectedTimeZone(defaultTimeZone);
  }, [defaultTimeZone, selectedTimeZone]);

  useEffect(() => {
    if (selectedTimeZone && !day) setDay(tomorrowInZone(selectedTimeZone));
  }, [selectedTimeZone, day]);

  const availability = useQuery({
    queryKey: ["availability", operatorSlug, calendarSlug, day, selectedTimeZone],
    queryFn: () => api<AvailabilityResponse>(`/public/${operatorSlug}/calendars/${calendarSlug}/availability?${new URLSearchParams({ date: day, timezone: selectedTimeZone })}`),
    enabled: Boolean(calendar && day && selectedTimeZone),
  });
  const requestItems = useMemo(() => cart.map(({ calendar_id, start_at, units: itemUnits }) => ({ calendar_id, start_at, units: itemUnits })), [cart]);
  const quote = useQuery({ queryKey: ["quote", operatorSlug, JSON.stringify(requestItems)], queryFn: () => api<Quote>(`/public/${operatorSlug}/orders/quote`, json("POST", { items: requestItems })), enabled: cart.length > 0 });
  const create = useMutation({
    mutationFn: () => api<Created>(`/public/${operatorSlug}/orders`, { ...json("POST", { items: requestItems, customer: { first_name: first, last_name: last, email, phone: phone || null } }), headers: { "X-Checkout-Key": checkoutKey } }),
    onSuccess: (result) => {
      setCreated(result);
      const suffix = result.access_token ? `?access_token=${encodeURIComponent(result.access_token)}` : "";
      if (!result.client_secret) navigate(withEmbed(`/booking/${result.public_reference}/confirmation${suffix}`, embed));
    },
  });

  if (catalog.isLoading) return <div className="center-state"><div className="spinner" /></div>;
  if (!catalog.data || !calendar) return <div className="center-state"><div className="state-card"><h1>Calendar unavailable</h1><p>This booking calendar may be inactive or the link is incorrect.</p></div></div>;

  const add = () => {
    if (!slot) return;
    setCart([...cart, { calendar_id: calendar.id, start_at: slot.start_at, units, slot }]);
    setSlot(null);
    setUnits(1);
  };
  const zones = timeZoneOptions(defaultTimeZone);

  return <PublicFrame name={catalog.data.name} embed={embed}>
    <div style={{ marginBottom: 20 }}><Link to={withEmbed(`/book/${operatorSlug}`, embed)} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#61706d" }}><ArrowLeft size={14} />All experiences</Link></div>
    <div className="public-hero" style={{ marginBottom: 25 }}><span className="eyebrow">{calendar.category_name || "Online booking"}</span><h1 style={{ fontSize: "clamp(27px,4vw,39px)" }}>{calendar.name}</h1><p>{calendar.description}</p><div className="service-meta" style={{ marginTop: 15, display: "flex", gap: 18 }}><span><Clock3 size={15} />{calendar.duration_minutes} minutes</span>{calendar.location && <span><MapPin size={15} />{calendar.location.name} · {calendar.location.address}</span>}</div></div>
    {created?.client_secret ? <div className="public-card" style={{ maxWidth: 620 }}><h2>Complete secure payment</h2><PaymentPanel clientSecret={created.client_secret} publicReference={created.public_reference} accessToken={created.access_token} embed={embed} /></div> : <div className="booking-panel">
      <section className="public-card"><h2>Choose a date and time</h2>
        <p style={{ fontSize: 12, color: "#78827f", marginTop: -6, marginBottom: 12 }}>Times are shown in your selected timezone. Availability remains governed by the operator's calendar and resources.</p>
        <label className="field" style={{ marginBottom: 12 }}><span>Time zone</span><select value={selectedTimeZone} onChange={(event) => { setSelectedTimeZone(event.target.value); setSlot(null); }}><option value="" disabled>Select a time zone</option>{zones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")} {zone === defaultTimeZone ? "(operator default)" : ""}</option>)}</select></label>
        <label className="field" style={{ maxWidth: 220, marginBottom: 17 }}><span>Date</span><input type="date" min={tomorrowInZone(selectedTimeZone)} value={day} onChange={(event) => { setDay(event.target.value); setSlot(null); }} /></label>
        {availability.isLoading ? <div className="loading">Checking live availability…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : <div className="slot-grid">{availability.data?.slots.map((item) => <button key={item.start_at} disabled={!item.available} className={`slot ${slot?.start_at === item.start_at ? "selected" : ""}`} onClick={() => { setSlot(item); setUnits(1); }}>{formatTime(item.start_at, selectedTimeZone)}<span>{item.available ? `${item.max_bookable_units} available` : "Sold out"}</span></button>)}</div>}
        {availability.data && !availability.data.slots.length && <div className="empty-state"><strong>No times on this date</strong><span>Choose another date to continue.</span></div>}
        {slot && <div style={{ marginTop: 20, paddingTop: 17, borderTop: "1px solid #e6e9e8" }}><div className="summary-row"><span>Quantity</span><div className="quantity"><button onClick={() => setUnits(Math.max(1, units - 1))}><Minus size={14} /></button><strong>{units}</strong><button onClick={() => setUnits(Math.min(slot.max_bookable_units, units + 1))}><Plus size={14} /></button></div></div><div className="summary-row"><span>Base price</span><strong>{formatMoney(calendar.base_price_minor, calendar.currency)} each</strong></div><button className="button" style={{ width: "100%", marginTop: 12 }} onClick={add}><ShoppingBag size={15} />Add booking</button></div>}
      </section>
      <aside className="public-card"><h2>Your booking</h2>{cart.length === 0 ? <p style={{ fontSize: 12, color: "#78827f" }}>Select a time to begin.</p> : <>{cart.map((item, index) => <div key={`${item.start_at}-${index}`} style={{ padding: "10px 0", borderBottom: "1px solid #edf0ef", display: "flex", justifyContent: "space-between", gap: 10 }}><div className="cell-title"><strong>{formatDay(item.start_at, selectedTimeZone)} · {formatTime(item.start_at, selectedTimeZone)}</strong><span>{item.units} × {calendar.name}</span></div><button className="icon-button" onClick={() => setCart(cart.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={14} /></button></div>)}{quote.data && <div style={{ marginTop: 10 }}><div className="summary-row"><span>Subtotal</span><span>{formatMoney(quote.data.subtotal_minor, quote.data.currency)}</span></div><div className="summary-row"><span>Platform Fee &amp; Taxes</span><span>{formatMoney(quote.data.platform_fee_and_taxes_minor, quote.data.currency)}</span></div><div className="summary-row total"><span>Total</span><span>{formatMoney(quote.data.customer_total_minor, quote.data.currency)}</span></div></div>}<form onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate(); }} style={{ marginTop: 17 }}><div className="form-grid"><label className="field"><span>First name</span><input required value={first} onChange={(event) => setFirst(event.target.value)} /></label><label className="field"><span>Last name</span><input required value={last} onChange={(event) => setLast(event.target.value)} /></label><label className="field full"><span>Email</span><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label><label className="field full"><span>Phone (optional)</span><input value={phone} onChange={(event) => setPhone(event.target.value)} /></label></div>{create.error && <div className="error-banner" style={{ marginTop: 12 }}>{create.error.message}</div>}<button className="button" style={{ width: "100%", marginTop: 15 }} disabled={create.isPending || quote.isLoading}>{create.isPending ? "Reserving inventory…" : "Continue to payment"}</button></form></>}</aside>
    </div>}
  </PublicFrame>;
}
