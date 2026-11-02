import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Clock3, MapPin, Minus, Plus, ShieldCheck, Trash2, Users, XCircle } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { AvailabilityMonth, AvailabilityResponse, AvailabilitySlot, PublicCalendar, PublicCatalog, PublicCustomField, PublicRate, SlotRate } from "../api/types";
import { PaymentPanel } from "./PaymentPanel";
import { PublicFrame } from "./OperatorBookingPage";
import { useEmbed, withEmbed } from "./embed";
import { formatDay, formatTime, isoDayInZone, safeTimeZone } from "../lib/datetime";

interface CartItem { calendar_id: string; start_at: string; units: number; slot: AvailabilitySlot; rate_id?: string; rate?: PublicRate }
interface Quote { currency: string; subtotal_minor: number; platform_fee_and_taxes_minor: number; customer_total_minor: number; booking_fee_minor?: number; tax_minor?: number }
interface Created extends Quote { public_reference: string; status: string; client_secret: string | null; access_token?: string | null; quote: Quote }
const formatMoney = (value: number, currency = "usd") => new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(value / 100);
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function formatDuration(minutes: number): string {
  if (minutes % 60 === 0) return `${minutes / 60} hour${minutes === 60 ? "" : "s"}`;
  if (minutes > 60) return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
  return `${minutes} minutes`;
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

function shiftMonth(month: string, delta: number): string {
  const [year = 1970, monthIndex = 1] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, monthIndex - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** FareHarbor-style month picker: bookable days are filled, others muted. */
function MonthCalendar({ month, onMonth, data, loading, selected, onSelect, earliestMonth }: {
  month: string; onMonth: (value: string) => void; data?: AvailabilityMonth; loading: boolean;
  selected: string; onSelect: (day: string) => void; earliestMonth: string;
}) {
  const [year = 1970, monthIndex = 1] = month.split("-").map(Number);
  const leading = new Date(Date.UTC(year, monthIndex - 1, 1)).getUTCDay();
  const label = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, monthIndex - 1, 1)));
  const statuses = new Map((data?.days || []).map((day) => [day.date, day.status]));
  const daysInMonth = new Date(Date.UTC(year, monthIndex, 0)).getUTCDate();
  return (
    <div className="fh-calendar" aria-busy={loading}>
      <div className="fh-calendar-head">
        <strong>{label}</strong>
        <div>
          <button type="button" className="icon-button" aria-label="Previous month" disabled={month <= earliestMonth} onClick={() => onMonth(shiftMonth(month, -1))}><ChevronLeft size={17} /></button>
          <button type="button" className="icon-button" aria-label="Next month" onClick={() => onMonth(shiftMonth(month, 1))}><ChevronRight size={17} /></button>
        </div>
      </div>
      <div className="fh-calendar-grid" role="grid">
        {WEEKDAYS.map((name) => <span key={name} className="fh-weekday">{name}</span>)}
        {Array.from({ length: leading }, (_, index) => <span key={`pad-${index}`} />)}
        {Array.from({ length: daysInMonth }, (_, index) => {
          const day = `${month}-${String(index + 1).padStart(2, "0")}`;
          const status = statuses.get(day) || "none";
          return (
            <button key={day} type="button" className={`fh-day ${status} ${selected === day ? "selected" : ""}`} disabled={status !== "available"} aria-pressed={selected === day} aria-label={`${day}${status === "sold_out" ? ", sold out" : status === "available" ? ", available" : ""}`} onClick={() => onSelect(day)}>
              {index + 1}
            </button>
          );
        })}
      </div>
      <p className="fh-calendar-note">{loading ? "Checking availability…" : "Choose a highlighted date to see times."}</p>
    </div>
  );
}

/** Quantity counter honouring a rate's per-booking minimum and live availability. */
function RateCounter({ rate, slotRate, value, onChange, currency, calendarMinutes }: { rate: PublicRate; slotRate?: SlotRate; value: number; onChange: (next: number) => void; currency: string; calendarMinutes: number }) {
  const available = slotRate?.available_quantity ?? 0;
  const minimum = rate.min_units_per_booking || 1;
  const increase = () => onChange(value === 0 ? Math.min(minimum, available) : Math.min(value + 1, available));
  const decrease = () => onChange(value <= minimum ? 0 : value - 1);
  const hint = [
    rate.duration_minutes && rate.duration_minutes !== calendarMinutes ? formatDuration(rate.duration_minutes) : null,
    rate.min_units_per_booking || rate.max_units_per_booking ? `${rate.min_units_per_booking || 1}–${rate.max_units_per_booking || "any"} per booking` : null,
    available < 1 ? "Unavailable" : available < 6 ? `${available} left` : null,
  ].filter(Boolean).join(" · ");
  return (
    <div className={`fh-rate ${available < 1 ? "unavailable" : ""}`}>
      <div className="fh-rate-copy">
        <strong>{formatMoney(rate.price_minor, currency)}</strong>
        <span className="fh-rate-name">{rate.customer_type_plural_name || rate.customer_type_name}</span>
        {rate.note && <span className="fh-rate-note">{rate.note}</span>}
        {hint && <span className="fh-rate-hint">{hint}</span>}
      </div>
      <div className="quantity">
        <button type="button" aria-label={`Fewer ${rate.customer_type_name}`} disabled={value === 0} onClick={decrease}><Minus size={14} /></button>
        <strong>{value}</strong>
        <button type="button" aria-label={`More ${rate.customer_type_name}`} disabled={available < 1 || value >= available} onClick={increase}><Plus size={14} /></button>
      </div>
    </div>
  );
}

export function CalendarBookingPage() {
  const { operatorSlug = "", calendarSlug = "" } = useParams();
  const navigate = useNavigate();
  const embed = useEmbed();
  const catalog = useQuery({ queryKey: ["public-catalog", operatorSlug], queryFn: () => api<PublicCatalog>(`/public/${operatorSlug}`), staleTime: 30_000 });
  const calendar = catalog.data?.calendars.find((item) => item.slug === calendarSlug);
  const timeZone = safeTimeZone(catalog.data?.time_zone);
  const today = isoDayInZone(new Date(), timeZone);
  const [month, setMonth] = useState("");
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null);
  const [units, setUnits] = useState(1);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
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
  const [photo, setPhoto] = useState(0);

  useEffect(() => { if (catalog.data && !month) setMonth(today.slice(0, 7)); }, [catalog.data, month, today]);

  const online = calendar?.public_booking_mode === "online";
  const monthQuery = useQuery({
    queryKey: ["availability-month", operatorSlug, calendarSlug, month],
    queryFn: () => api<AvailabilityMonth>(`/public/${operatorSlug}/calendars/${calendarSlug}/availability/month?${new URLSearchParams({ month })}`),
    enabled: Boolean(calendar && month && online),
    staleTime: 30_000,
  });
  const availability = useQuery({
    queryKey: ["availability", operatorSlug, calendarSlug, day],
    queryFn: () => api<AvailabilityResponse>(`/public/${operatorSlug}/calendars/${calendarSlug}/availability?${new URLSearchParams({ date: day })}`),
    enabled: Boolean(calendar && day && online),
    staleTime: 0,
    gcTime: 60_000,
    refetchInterval: () => document.visibilityState === "visible" ? 20_000 : false,
    refetchIntervalInBackground: false,
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
  // Availability is polled while this page is open. Always resolve the selected
  // slot from the newest response so inventory changes are reflected.
  const liveSlot = slot ? availability.data?.slots.find((item) => item.start_at === slot.start_at) || slot : null;
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

  const rateList = rates.data || [];
  const hasRates = rateList.length > 0;
  const selectedCount = Object.values(quantities).reduce((sum, value) => sum + value, 0);
  const photos = [calendar.hero_image_url, ...(calendar.gallery_image_urls || [])].filter((url): url is string => Boolean(url));
  const lowestPrice = hasRates ? Math.min(...rateList.map((rate) => rate.price_minor)) : calendar.base_price_minor;
  const policy = calendar.booking_policy;
  const requiresPolicyAcceptance = Boolean(policy || online);
  const legacyMax = liveSlot?.max_bookable_units ?? 1;

  const chooseDay = (value: string) => { setDay(value); setSlot(null); setQuantities({}); };
  const chooseSlot = async (item: AvailabilitySlot) => {
    const refreshed = await availability.refetch();
    setSlot(refreshed.data?.slots.find((candidate) => candidate.start_at === item.start_at) || item);
    setQuantities({});
    setUnits(1);
  };
  const add = () => {
    if (!liveSlot || !online) return;
    if (hasRates) {
      const items = rateList.filter((rate) => (quantities[rate.id] || 0) > 0).map((rate) => ({ calendar_id: calendar.id, start_at: liveSlot.start_at, units: quantities[rate.id] || 0, slot: liveSlot, rate_id: rate.id, rate }));
      if (!items.length) return;
      setCart((previous) => [...previous, ...items]);
    } else {
      setCart((previous) => [...previous, { calendar_id: calendar.id, start_at: liveSlot.start_at, units, slot: liveSlot }]);
    }
    setSlot(null);
    setQuantities({});
    setUnits(1);
  };

  const listing = (
    <article className="fh-listing">
      <Link className="fh-back" to={withEmbed(`/book/${operatorSlug}`, embed)}><ArrowLeft size={14} />All experiences</Link>
      <h1>{calendar.name}</h1>
      {calendar.headline && <p className="fh-headline">{calendar.headline}</p>}
      {photos.length > 0 ? (
        <div className="fh-gallery">
          <img className="fh-photo" src={photos[photo] || photos[0]} alt={calendar.name} />
          {photos.length > 1 && <div className="fh-thumbs">{photos.map((url, index) => <button key={`${url}-${index}`} type="button" className={index === photo ? "active" : ""} onClick={() => setPhoto(index)} aria-label={`Show photo ${index + 1}`}><img src={url} alt="" loading="lazy" /></button>)}</div>}
        </div>
      ) : <div className="fh-photo fh-photo-fallback">{calendar.name.slice(0, 1)}</div>}
      <ul className="fh-prices">
        {hasRates ? rateList.map((rate) => <li key={rate.id}><strong>{formatMoney(rate.price_minor, calendar.currency)}</strong><span>{rate.customer_type_plural_name || rate.customer_type_name}</span>{rate.note && <small>{rate.note}</small>}</li>) : <li><strong>{formatMoney(calendar.base_price_minor, calendar.currency)}</strong><span>per booking</span></li>}
      </ul>
      <a className="button fh-jump" href="#book">Check availability</a>
      {calendar.description && <section className="fh-section"><p className="fh-description">{calendar.description}</p></section>}
      <section className="fh-section">
        <h2>Overview</h2>
        <dl className="fh-overview">
          <div><dt><Clock3 size={15} />Duration</dt><dd>{formatDuration(calendar.duration_minutes)}{rateList.some((rate) => rate.duration_minutes && rate.duration_minutes !== calendar.duration_minutes) ? " (longer options available)" : ""}</dd></div>
          {calendar.location && <div><dt><MapPin size={15} />Meeting point</dt><dd>{calendar.location.name}<br />{calendar.location.address}</dd></div>}
          <div><dt><ShieldCheck size={15} />Cancellations</dt><dd>{cancellationCopy(calendar)}</dd></div>
          <div><dt><Users size={15} />From</dt><dd>{formatMoney(lowestPrice, calendar.currency)} per {hasRates ? "guest" : "booking"}</dd></div>
        </dl>
      </section>
      {calendar.booking_instructions && <section className="fh-section"><h2>Good to know</h2><p className="fh-description">{calendar.booking_instructions}</p></section>}
    </article>
  );

  let widget;
  if (calendar.public_booking_mode === "call_to_book") {
    widget = <div className="fh-widget-card"><h2>Call to book</h2><p>This experience is booked by phone so the operator can confirm the right equipment and schedule.</p>{calendar.call_to_book_phone && <a className="button" href={`tel:${calendar.call_to_book_phone}`}>Call {calendar.call_to_book_phone}</a>}</div>;
  } else if (calendar.public_booking_mode === "closed") {
    widget = <div className="fh-widget-card"><h2>Online booking is closed</h2><p>Please contact the operator for the next available booking window.</p>{calendar.call_to_book_phone && <a className="button" href={`tel:${calendar.call_to_book_phone}`}>Call the operator</a>}</div>;
  } else if (created?.client_secret) {
    widget = <div className="fh-widget-card"><h2>Payment details</h2><p className="fh-secure"><ShieldCheck size={15} />Secured and encrypted payment</p><PaymentPanel clientSecret={created.client_secret} publicReference={created.public_reference} accessToken={created.access_token} embed={embed} /></div>;
  } else {
    widget = (
      <>
        <div className="fh-widget-card">
          {month && <MonthCalendar month={month} onMonth={setMonth} data={monthQuery.data} loading={monthQuery.isFetching} selected={day} onSelect={chooseDay} earliestMonth={today.slice(0, 7)} />}
          {monthQuery.error && <div className="error-banner"><XCircle size={14} /> {monthQuery.error.message}</div>}
          {day && (
            <div className="fh-times">
              <h3>{formatDay(`${day}T12:00:00Z`, "UTC")}</h3>
              {availability.isLoading ? <div className="loading">Checking live availability…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : availability.data?.slots.length ? (
                <div className="fh-time-list">
                  {availability.data.slots.map((item) => (
                    <button key={item.start_at} type="button" disabled={!item.available || availability.isFetching} className={`fh-time ${slot?.start_at === item.start_at ? "selected" : ""}`} onClick={() => { void chooseSlot(item); }}>
                      <span>{formatTime(item.start_at, timeZone)}</span>
                      <small>{item.available ? (item.max_bookable_units < 6 ? `${item.max_bookable_units} left` : "Available") : item.status === "call_to_book" ? "Call to book" : item.status === "past_cutoff" ? "Booking closed" : item.status === "closed" ? "Closed" : item.status === "blocked" ? "Unavailable" : "Sold out"}</small>
                      <ChevronRight size={16} aria-hidden="true" />
                    </button>
                  ))}
                </div>
              ) : <p className="fh-calendar-note">No times on this date. Choose another date.</p>}
            </div>
          )}
          {liveSlot && (
            <div className="fh-party">
              <h3>{formatTime(liveSlot.start_at, timeZone)} · how many?</h3>
              {hasRates ? rateList.map((rate) => <RateCounter key={rate.id} rate={rate} slotRate={liveSlot.rates?.find((item) => item.rate_id === rate.id)} value={quantities[rate.id] || 0} currency={calendar.currency} calendarMinutes={calendar.duration_minutes} onChange={(next) => setQuantities((current) => ({ ...current, [rate.id]: next }))} />) : (
                <div className="fh-rate"><div className="fh-rate-copy"><strong>{formatMoney(calendar.base_price_minor, calendar.currency)}</strong><span className="fh-rate-name">per booking</span></div><div className="quantity"><button type="button" aria-label="Decrease quantity" onClick={() => setUnits(Math.max(1, units - 1))}><Minus size={14} /></button><strong>{units}</strong><button type="button" aria-label="Increase quantity" disabled={units >= legacyMax} onClick={() => setUnits(Math.min(legacyMax, units + 1))}><Plus size={14} /></button></div></div>
              )}
              <button type="button" className="button fh-continue" disabled={hasRates ? selectedCount < 1 : legacyMax < 1} onClick={add}>Add to booking</button>
            </div>
          )}
        </div>
        {cart.length > 0 && (
          <div className="fh-widget-card">
            <h2>Your booking</h2>
            {cart.map((item, index) => <div key={`${item.start_at}-${item.rate_id}-${index}`} className="fh-cart-line"><div className="cell-title"><strong>{formatDay(item.start_at, timeZone)} · {formatTime(item.start_at, timeZone)}</strong><span>{item.units} × {item.rate?.customer_type_name || calendar.name}</span></div><button type="button" className="icon-button" aria-label="Remove booking item" onClick={() => setCart((previous) => previous.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={14} /></button></div>)}
            {quote.data && <div className="fh-totals"><div className="summary-row"><span>Subtotal</span><span>{formatMoney(quote.data.subtotal_minor, quote.data.currency)}</span></div><div className="summary-row"><span>Taxes & fees</span><span>{formatMoney(quote.data.booking_fee_minor !== undefined ? (quote.data.booking_fee_minor + (quote.data.tax_minor || 0)) : quote.data.platform_fee_and_taxes_minor, quote.data.currency)}</span></div><div className="summary-row total"><span>Total</span><span>{formatMoney(quote.data.customer_total_minor, quote.data.currency)}</span></div></div>}
            {quote.error && <div className="error-banner">{quote.error.message}</div>}
            <form onSubmit={(event: FormEvent) => { event.preventDefault(); if (!policyAccepted && requiresPolicyAcceptance) return; create.mutate(); }}>
              <h3>Contact details</h3>
              <div className="form-grid">
                <label className="field"><span>First name</span><input required value={first} onChange={(event) => setFirst(event.target.value)} /></label>
                <label className="field"><span>Last name</span><input required value={last} onChange={(event) => setLast(event.target.value)} /></label>
                <label className="field full"><span>Email address</span><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
                <label className="field full"><span>Phone number</span><input required value={phone} onChange={(event) => setPhone(event.target.value)} /></label>
                {publicFields.data?.map((field) => <label className="field full" key={field.id}><span>{field.label}{field.required ? " *" : ""}</span>{field.field_type === "textarea" ? <textarea required={field.required} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })} /> : field.field_type === "select" ? <select required={field.required} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })}><option value="">Choose…</option>{(field.options || []).map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select> : field.field_type === "boolean" ? <input type="checkbox" checked={Boolean(customFields[field.key])} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.checked })} /> : <input required={field.required} type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"} value={String(customFields[field.key] || "")} onChange={(event) => setCustomFields({ ...customFields, [field.key]: event.target.value })} />}</label>)}
              </div>
              <label className="checkbox-row"><input type="checkbox" checked={marketingOptIn} onChange={(event) => setMarketingOptIn(event.target.checked)} /><span>Send me marketing emails from {catalog.data.name} and its partners</span></label>
              <section className="policy-box"><h3>Cancellation policy</h3><p>{cancellationCopy(calendar)}</p>{policy && <p>{weatherCopy(policy.weather_refund_mode)} {policy.reschedule_cutoff_minutes ? `Rescheduling requires at least ${Math.max(1, Math.round(policy.reschedule_cutoff_minutes / 60))} hours notice.` : ""}</p>}{policy?.requires_waiver && <p>A waiver is required before this activity. You will receive a secure signing link after booking.</p>}<label className="checkbox-row"><input type="checkbox" required={requiresPolicyAcceptance} checked={policyAccepted} onChange={(event) => setPolicyAccepted(event.target.checked)} /><span>I agree to the cancellation policy and booking terms.</span></label></section>
              {create.error && <div className="error-banner">{create.error.message}</div>}
              <button className="button fh-continue" disabled={create.isPending || quote.isLoading || Boolean(quote.error) || (requiresPolicyAcceptance && !policyAccepted)}>{create.isPending ? "Reserving inventory…" : "Book and pay"}</button>
            </form>
          </div>
        )}
      </>
    );
  }

  return <PublicFrame name={catalog.data.name} embed={embed}>
    <div className="fh-layout">
      {listing}
      <aside className="fh-widget" id="book">{widget}</aside>
    </div>
  </PublicFrame>;
}
