import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clock3, MapPin } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PublicCalendar, PublicCatalog } from "../api/types";
import { useEmbed, withEmbed } from "./embed";

export function money(value: number, currency: string) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(value / 100);
}

export function PublicFrame({ name, embed, children }: { name: string; embed?: boolean; children: ReactNode }) {
  if (embed) {
    // Embedded mode: no site header/nav/footer, transparent outer background,
    // full width. Only the booking experience renders inside the host iframe.
    return <main className="public-main embed" style={{ background: "transparent", paddingTop: 18 }}>{children}</main>;
  }
  return <div className="public-shell"><nav className="public-nav"><div className="public-nav-inner"><div className="brand-mark">P</div>{name}</div></nav><main className="public-main">{children}</main></div>;
}

interface Group { id: string | null; name: string; slug: string | null; color: string | null; calendars: PublicCalendar[] }

function groupByCategory(calendars: PublicCalendar[]): Group[] {
  const groups: Group[] = [];
  const index = new Map<string, Group>();
  for (const calendar of calendars) {
    const key = calendar.category_id ?? "__other__";
    let group = index.get(key);
    if (!group) {
      group = {
        id: calendar.category_id,
        name: calendar.category_name ?? "Other Services",
        slug: calendar.category_slug,
        color: calendar.category_color,
        calendars: [],
      };
      index.set(key, group);
      groups.push(group);
    }
    group.calendars.push(calendar);
  }
  // Uncategorized always sorts last.
  return groups.sort((a, b) => (a.id === null ? 1 : 0) - (b.id === null ? 1 : 0));
}

export function ServiceCard({ operatorSlug, calendar, embed }: { operatorSlug: string; calendar: PublicCalendar; embed: boolean }) {
  return <Link className="service-card" to={withEmbed(`/book/${operatorSlug}/${calendar.slug}`, embed)}>
    <div className="service-category"><i className="filter-dot" style={{ background: calendar.category_color || "#527a73" }} />{calendar.category_name || "Booking"}</div>
    <h2>{calendar.name}</h2>
    <p>{calendar.description || "Select a date to view live times and available quantity."}</p>
    <div className="service-meta">
      <span><Clock3 size={14} />{calendar.duration_minutes} minutes · from {money(calendar.base_price_minor, calendar.currency)}</span>
      {calendar.location && <span><MapPin size={14} />{calendar.location.name}</span>}
    </div>
  </Link>;
}

export function OperatorBookingPage() {
  const { operatorSlug = "" } = useParams();
  const embed = useEmbed();
  const query = useQuery({ queryKey: ["public-catalog", operatorSlug], queryFn: () => api<PublicCatalog>(`/public/${operatorSlug}`) });
  if (query.isLoading) return <div className="center-state"><div className="spinner" /></div>;
  if (!query.data) return <div className="center-state"><div className="state-card"><h1>Booking page unavailable</h1><p>{query.error?.message || "Please check the link and try again."}</p></div></div>;
  const data = query.data;
  const groups = groupByCategory(data.calendars);
  return <PublicFrame name={data.name} embed={embed}>
    <div className="public-hero"><span className="eyebrow">Online booking</span><h1>Book with {data.name}</h1><p>Browse live availability and reserve your time. Inventory is updated across every service as bookings are made.</p></div>
    {groups.length === 0 && <div className="empty-state"><strong>No services available</strong><span>Please check back soon.</span></div>}
    {groups.map(group => <section key={group.id ?? "other"} style={{ marginBottom: 30 }}>
      <div className="category-heading" style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 13 }}>
        {group.id && <i className="filter-dot" style={{ background: group.color || "#527a73" }} />}
        {group.slug
          ? <Link to={withEmbed(`/book/${operatorSlug}/category/${group.slug}`, embed)} style={{ fontSize: 15, fontWeight: 600, color: "inherit" }}>{group.name}</Link>
          : <h2 style={{ fontSize: 15, margin: 0 }}>{group.name}</h2>}
      </div>
      <div className="service-grid">{group.calendars.map(calendar => <ServiceCard key={calendar.id} operatorSlug={operatorSlug} calendar={calendar} embed={embed} />)}</div>
    </section>)}
  </PublicFrame>;
}
