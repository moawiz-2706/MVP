import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock3, PenLine } from "lucide-react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { formatLongDate, formatTime } from "../lib/datetime";

interface PartyGuest { guest_number: number; label: string; url: string; signed: boolean; signed_by: string | null }
interface PartyItem { booking_id: string; calendar_name: string; start_at: string; units: number; per_guest: boolean; waivers_open: boolean; guests: PartyGuest[] }
interface Party { operator_name: string; public_reference: string; customer_first_name: string; time_zone: string; waivers_enabled: boolean; items: PartyItem[] }

/** Opened from the QR code on a staff booking: every guest adds their own details. */
export function PartyPage() {
  const { token = "" } = useParams();
  const party = useQuery({
    queryKey: ["party", token],
    queryFn: () => api<Party>(`/public/party/${encodeURIComponent(token)}`),
    enabled: Boolean(token),
    retry: false,
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
  });
  if (party.isLoading) return <main className="public-main"><div className="center-state"><div className="spinner" /></div></main>;
  if (party.error || !party.data) return <main className="public-main"><div className="center-state"><div className="state-card"><h1>Link unavailable</h1><p>This guest link has expired or is no longer valid. Ask the person who booked for a new one.</p></div></div></main>;
  const data = party.data;
  return <main className="public-main"><div className="public-card party-card">
    <span className="eyebrow">{data.operator_name}</span>
    <h1>Guest details</h1>
    <p className="muted-note">Booking <strong>{data.public_reference}</strong>{data.customer_first_name ? ` · booked by ${data.customer_first_name}` : ""}. Each guest taps their own line below and fills in their details and waiver.</p>
    {!data.waivers_enabled && <div className="empty-state"><strong>Nothing to fill in</strong><span>This operator doesn't need guest details online.</span></div>}
    {data.items.map((item) => <section key={item.booking_id} className="party-item">
      <header><strong>{item.calendar_name}</strong><span>{formatLongDate(item.start_at, data.time_zone)} · {formatTime(item.start_at, data.time_zone)} · {item.units} {item.units === 1 ? "guest" : "guests"}</span></header>
      {data.waivers_enabled && !item.waivers_open && <div className="muted-note party-wait"><Clock3 size={15} />Guest details open once the booking is paid.</div>}
      {item.waivers_open && !item.per_guest && <p className="muted-note" style={{ margin: "4px 0 8px" }}>One adult fills this in and lists everyone taking part.</p>}
      <ul className="party-guests">
        {item.guests.map((guest) => <li key={guest.guest_number}>
          {guest.signed
            ? <div className="party-guest done"><CheckCircle2 size={18} /><span><strong>{guest.label}</strong><small>Completed{guest.signed_by ? ` by ${guest.signed_by}` : ""}</small></span></div>
            : <a className="party-guest" href={guest.url}><PenLine size={18} /><span><strong>{guest.label}</strong><small>Tap to add details and sign</small></span></a>}
        </li>)}
      </ul>
    </section>)}
  </div></main>;
}
