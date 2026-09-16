import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PublicCategoryPage } from "../api/types";
import { PublicFrame, ServiceCard } from "./OperatorBookingPage";
import { useEmbed, withEmbed } from "./embed";

export function CategoryBookingPage() {
  const { operatorSlug = "", categorySlug = "" } = useParams();
  const embed = useEmbed();
  const query = useQuery({
    queryKey: ["public-category", operatorSlug, categorySlug],
    queryFn: () => api<PublicCategoryPage>(`/public/${operatorSlug}/category/${categorySlug}`),
  });
  if (query.isLoading) return <div className="center-state"><div className="spinner" /></div>;
  if (!query.data) return <div className="center-state"><div className="state-card"><h1>Category unavailable</h1><p>{query.error?.message || "This category may be inactive or the link is incorrect."}</p></div></div>;
  const data = query.data;
  return <PublicFrame name={data.operator_name} embed={embed}>
    <div style={{ marginBottom: 18 }}>
      <Link to={withEmbed(`/book/${operatorSlug}`, embed)} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#61706d" }}><ArrowLeft size={14} />All experiences</Link>
    </div>
    <div className="public-hero"><span className="eyebrow">{data.operator_name}</span><h1>{data.category_name}</h1><p>Choose your rental to view live times and available quantity.</p></div>
    <div className="service-grid">{data.calendars.map(calendar => <ServiceCard key={calendar.id} operatorSlug={operatorSlug} calendar={calendar} embed={embed} />)}</div>
  </PublicFrame>;
}
