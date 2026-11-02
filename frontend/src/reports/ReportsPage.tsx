import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, CalendarCheck2, CircleDollarSign, Users } from "lucide-react";
import { useState } from "react";
import { api, download } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { useHasPermission } from "../api/bootstrap";
import type { CreatorReport, ReportSummary } from "../api/types";
import { isEmbeddedInHighLevel } from "../pwa";

const today = () => new Date().toISOString().slice(0, 10);
const inThirtyDays = () => new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
const money = (minor: number) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(minor / 100);

function Metric({ icon: Icon, label, value, detail }: { icon: typeof Activity; label: string; value: string; detail: string }) {
  return <div className="card metric-card"><div className="metric-icon"><Icon size={17} /></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>;
}

const SOURCE_LABELS: Record<string, string> = { public: "Public page", staff_link: "Staff link", pwa: "Staff app", desktop: "Desktop" };

// Admin-only, standalone PWA: bookings grouped by who created them. These are
// order totals for commission review, not commission amounts.
function CreatorReportSection({ startDate, endDate }: { startDate: string; endDate: string }) {
  const query = useQuery({ queryKey: ["reports-creators", startDate, endDate], queryFn: () => api<CreatorReport>(`/reports/bookings-by-creator?${new URLSearchParams({ start_date: startDate, end_date: endDate })}`) });
  return <div className="card creator-report"><h2>Bookings by creator</h2><p className="muted-note">Orders created in this period, by the staff member or channel that created them. Totals are order values, not commission.</p>{query.isLoading ? <div className="loading">Loading…</div> : query.error ? <div className="error-banner">{query.error.message}</div> : query.data && (query.data.rows.length ? <div className="table-scroll"><table><thead><tr><th>Created by</th><th>Channel</th><th className="num">Orders</th><th className="num">Confirmed</th><th className="num">Cancelled</th><th className="num">Sales</th><th className="num">Refunded</th></tr></thead><tbody>{query.data.rows.map((row) => <tr key={`${row.booking_source}-${row.staff_id}-${row.user_id}-${row.currency}`}><td>{row.creator_name}</td><td>{SOURCE_LABELS[row.booking_source || ""] || "Before tracking"}</td><td className="num">{row.orders}</td><td className="num">{row.confirmed_orders}</td><td className="num">{row.cancelled_orders}</td><td className="num">{money(row.gross_minor)}</td><td className="num">{money(row.refunded_minor)}</td></tr>)}</tbody></table></div> : <div className="loading">No bookings were created in this period.</div>)}</div>;
}

export function ReportsPage() {
  const isAdmin = useHasPermission("manage_payments");
  const showCreators = isAdmin && !isEmbeddedInHighLevel();
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(inThirtyDays);
  const query = useQuery({ queryKey: ["reports-summary", startDate, endDate], queryFn: () => api<ReportSummary>(`/reports/summary?${new URLSearchParams({ start_date: startDate, end_date: endDate })}`) });
  const report = query.data;
  return <div className="page"><PageHeader title="Reports" description="Booking, revenue, capacity, and synchronization health for the selected period." action={<button className="button secondary" onClick={() => download(`/reports/bookings.csv?${new URLSearchParams({ start_date: startDate, end_date: endDate })}`, `passport-bookings-${startDate}-${endDate}.csv`)}>Export CSV</button>} /><div className="card report-filter"><label className="field"><span>From</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label className="field"><span>To</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>{query.isLoading ? <div className="loading">Loading report…</div> : query.error ? <div className="error-banner">{query.error.message}</div> : report && <><div className="metric-grid"><Metric icon={CalendarCheck2} label="Bookings" value={String(report.total_bookings)} detail={`${report.upcoming_bookings} upcoming`} /><Metric icon={Users} label="Units booked" value={String(report.units_booked)} detail={`${report.confirmed_bookings} confirmed`} /><Metric icon={CircleDollarSign} label="Gross sales" value={money(report.gross_sales_minor)} detail={`${money(report.taxes_minor)} taxes`} /><Metric icon={Activity} label="Sync health" value={String(report.failed_sync_jobs)} detail="failed outbox jobs" /></div><div className="card report-table"><h2>Booking breakdown</h2><div className="list-row"><span>Confirmed</span><strong>{report.confirmed_bookings}</strong></div><div className="list-row"><span>Pending payment</span><strong>{report.pending_payment_bookings}</strong></div><div className="list-row"><span>Completed</span><strong>{report.completed_bookings}</strong></div><div className="list-row"><span>Cancelled</span><strong>{report.cancelled_bookings}</strong></div><div className="list-row"><span>Booking fees</span><strong>{money(report.booking_fees_minor)}</strong></div></div></>}{showCreators && <CreatorReportSection startDate={startDate} endDate={endDate} />}</div>;
}
