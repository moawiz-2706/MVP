import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { AvailabilityResponse } from "../api/types";
import { formatLongDate, formatTime, isoDayInZone, tomorrowInZone, zoneLabel } from "../lib/datetime";

interface Status {
  public_reference: string;
  operator_slug: string;
  status: string;
  time_zone: string;
  payment_status: string;
  confirmed: boolean;
  customer_name: string;
  currency: string;
  subtotal_minor: number;
  platform_fee_and_taxes_minor: number;
  customer_total_minor: number;
  items: {
    calendar_name: string;
    start_at: string;
    end_at: string;
    units: number;
    departure_location_name: string | null;
    departure_location_address: string | null;
    booking_id?: string;
    calendar_slug?: string;
    waiver_url: string | null;
    waiver_signed: boolean;
  }[];
}

const money = (value: number, currency: string) =>
  new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(value / 100);

export function ConfirmationPage() {
  const { publicReference = "" } = useParams();
  const [params] = useSearchParams();
  const accessToken = params.get("access_token");
  const [reconcile, setReconcile] = useState(params.get("reconcile") === "true");
  const queryClient = useQueryClient();
  const statusParams = new URLSearchParams();
  if (accessToken) statusParams.set("access_token", accessToken);
  if (reconcile) statusParams.set("reconcile", "true");
  const statusPath = `/public/orders/${publicReference}/status${statusParams.toString() ? `?${statusParams}` : ""}`;
  const query = useQuery({
    queryKey: ["order-status", publicReference, accessToken, reconcile],
    queryFn: () => api<Status>(statusPath),
    refetchInterval: (result) =>
      result.state.data?.confirmed || result.state.data?.status === "exception" ? false : 2000,
  });
  const cancel = useMutation({
    mutationFn: () => api<void>(`/public/orders/${publicReference}/cancel?access_token=${encodeURIComponent(accessToken || "")}`, { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["order-status", publicReference] });
    },
  });
  useEffect(() => {
    if (reconcile && query.data) setReconcile(false);
  }, [reconcile, query.data]);

  if (query.isLoading || !query.data) {
    return (
      <div className="center-state">
        <div className="state-card">
          <div className="spinner" />
          <h1>Confirming your booking</h1>
          <p>We’re waiting for secure payment confirmation. You can safely keep this page open.</p>
        </div>
      </div>
    );
  }

  const order = query.data;
  if (!order.confirmed && order.status !== "cancelled") {
    return (
      <div className="center-state">
        <div className="state-card">
          <Clock3 />
          <h1>{order.status === "exception" ? "Payment needs review" : "Finalizing your booking"}</h1>
          <p>
            {order.status === "exception"
              ? "Your payment was received, but the booking requires operator review. Keep your order reference for support."
              : "Payment processing can take a moment. This page updates automatically."}
          </p>
          <strong>{order.public_reference}</strong>
        </div>
      </div>
    );
  }

  const cancelled = order.status === "cancelled";
  return (
    <div className="public-shell">
      <main className="public-main">
        <section className="public-card confirmation">
          <div className={`success-icon ${cancelled ? "result-error-icon" : ""}`}>{cancelled ? <XCircle /> : <CheckCircle2 />}</div>
          <div className="public-hero" style={{ marginBottom: 25 }}>
            <span className="eyebrow">{order.public_reference}</span>
            <h1 style={{ fontSize: 34 }}>{cancelled ? "Booking cancelled" : "Booking confirmed"}</h1>
            <p>{cancelled ? "This reservation has been cancelled. Any eligible refund is processed separately." : `Thanks, ${order.customer_name}. Your reservation is complete.`}</p>
          </div>
          {!cancelled && order.items.some((item) => item.waiver_url && !item.waiver_signed) && (
            <div className="warning-box" style={{ marginBottom: 6 }}>
              <p>Everyone taking part must be on a signed waiver before the activity. It takes about a minute.</p>
            </div>
          )}
          {order.items.map((item, index) => (
            <div key={index} style={{ padding: "14px 0", borderTop: "1px solid #e6e9e8" }}>
              <strong>{item.calendar_name}</strong>
              <div className="service-meta" style={{ marginTop: 7 }}>
                <span>{formatLongDate(item.start_at, order.time_zone)} · {formatTime(item.start_at, order.time_zone)} – {formatTime(item.end_at, order.time_zone)} ({zoneLabel(order.time_zone)})</span>
                <span>Quantity: {item.units}</span>
                {item.departure_location_name && <span>{item.departure_location_name} · {item.departure_location_address}</span>}
              </div>
              {!cancelled && item.waiver_url && (
                <div style={{ marginTop: 10 }}>
                  {item.waiver_signed ? <span className="badge success">Waiver signed</span> : <a className="button small" href={item.waiver_url}>Sign waiver for {item.units} {item.units === 1 ? "person" : "people"}</a>}
                </div>
              )}
              {!cancelled && accessToken && <RescheduleControl order={order} item={item} accessToken={accessToken} onDone={() => queryClient.invalidateQueries({ queryKey: ["order-status", publicReference] })} />}
            </div>
          ))}
          <div style={{ paddingTop: 12, borderTop: "1px solid #e6e9e8" }}>
            <div className="summary-row"><span>Subtotal</span><span>{money(order.subtotal_minor, order.currency)}</span></div>
            <div className="summary-row"><span>Platform Fee &amp; Taxes</span><span>{money(order.platform_fee_and_taxes_minor, order.currency)}</span></div>
            <div className="summary-row total"><span>{cancelled ? "Original total" : "Total paid"}</span><span>{money(order.customer_total_minor, order.currency)}</span></div>
          </div>
          {!cancelled && accessToken && <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid #e6e9e8" }}><button className="button secondary" disabled={cancel.isPending} onClick={() => { if (window.confirm("Cancel this reservation? The configured cancellation policy will be applied.")) cancel.mutate(); }}>{cancel.isPending ? "Cancelling…" : "Cancel reservation"}</button>{cancel.error && <div className="error-banner" style={{ marginTop: 10 }}>{cancel.error.message}</div>}</div>}
        </section>
      </main>
    </div>
  );
}

function RescheduleControl({ order, item, accessToken, onDone }: { order: Status; item: Status["items"][number]; accessToken: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState(() => isoDayInZone(new Date(item.start_at), order.time_zone));
  const [selected, setSelected] = useState(item.start_at);
  const availability = useQuery({
    queryKey: ["public-reschedule-availability", order.operator_slug, item.calendar_slug, day],
    queryFn: () => api<AvailabilityResponse>(`/public/${order.operator_slug}/calendars/${item.calendar_slug}/availability?date=${day}`),
    enabled: Boolean(open && item.booking_id && item.calendar_slug),
  });
  const mutation = useMutation({
    mutationFn: () => api(`/public/orders/${order.public_reference}/bookings/${item.booking_id}/reschedule?access_token=${encodeURIComponent(accessToken)}`, json("POST", { start_at: selected })),
    onSuccess: () => { setOpen(false); onDone(); },
  });
  if (!item.booking_id || !item.calendar_slug) return null;
  return <div style={{ marginTop: 12 }}><button className="button small secondary" onClick={() => setOpen((value) => !value)}>{open ? "Close reschedule" : "Change date or time"}</button>{open && <div className="reschedule-box"><label className="field"><span>New date ({zoneLabel(order.time_zone)})</span><input type="date" min={tomorrowInZone(order.time_zone)} value={day} onChange={(event) => { setDay(event.target.value); setSelected(""); }} /></label>{availability.isLoading ? <div className="loading">Loading available times…</div> : availability.error ? <div className="error-banner">{availability.error.message}</div> : <div className="slot-grid">{availability.data?.slots.filter((slot) => slot.available).map((slot) => <button type="button" key={slot.start_at} className={`slot ${selected === slot.start_at ? "selected" : ""}`} onClick={() => setSelected(slot.start_at)}>{formatTime(slot.start_at, order.time_zone)}<span>{slot.max_bookable_units} available</span></button>)}</div>}{availability.data && !availability.data.slots.some((slot) => slot.available) && <div className="muted-note">No available times on this date.</div>}<button className="button" disabled={!selected || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? "Updating booking…" : "Confirm new time"}</button>{mutation.error && <div className="error-banner">{mutation.error.message}</div>}</div>}</div>;
}
