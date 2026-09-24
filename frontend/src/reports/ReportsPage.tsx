import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, CalendarCheck2, CircleDollarSign, Users } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import type { ReportSummary } from "../api/types";

const today = () => new Date().toISOString().slice(0, 10);
const inThirtyDays = () => new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
const money = (minor: number) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(minor / 100);

function Metric({ icon: Icon, label, value, detail }: { icon: typeof Activity; label: string; value: string; detail: string }) {
  return <div className="card metric-card"><div className="metric-icon"><Icon size={17} /></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>;
}

export function ReportsPage() {
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(inThirtyDays);
  const query = useQuery({ queryKey: ["reports-summary", startDate, endDate], queryFn: () => api<ReportSummary>(`/reports/summary?${new URLSearchParams({ start_date: startDate, end_date: endDate })}`) });
  const report = query.data;
  return <div className="page"><PageHeader title="Reports" description="Booking, revenue, capacity, and synchronization health for the selected period." /><div className="card report-filter"><label className="field"><span>From</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label className="field"><span>To</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>{query.isLoading ? <div className="loading">Loading report…</div> : query.error ? <div className="error-banner">{query.error.message}</div> : report && <><div className="metric-grid"><Metric icon={CalendarCheck2} label="Bookings" value={String(report.total_bookings)} detail={`${report.upcoming_bookings} upcoming`} /><Metric icon={Users} label="Units booked" value={String(report.units_booked)} detail={`${report.confirmed_bookings} confirmed`} /><Metric icon={CircleDollarSign} label="Gross sales" value={money(report.gross_sales_minor)} detail={`${money(report.taxes_minor)} taxes`} /><Metric icon={Activity} label="Sync health" value={String(report.failed_sync_jobs)} detail="failed outbox jobs" /></div><div className="card report-table"><h2>Booking breakdown</h2><div className="list-row"><span>Confirmed</span><strong>{report.confirmed_bookings}</strong></div><div className="list-row"><span>Pending payment</span><strong>{report.pending_payment_bookings}</strong></div><div className="list-row"><span>Completed</span><strong>{report.completed_bookings}</strong></div><div className="list-row"><span>Cancelled</span><strong>{report.cancelled_bookings}</strong></div><div className="list-row"><span>Booking fees</span><strong>{money(report.booking_fees_minor)}</strong></div></div></>}</div>;
}
