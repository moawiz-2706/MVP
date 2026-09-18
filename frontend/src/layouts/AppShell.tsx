import { Bell, CalendarDays, MapPin, Menu, Settings, Shapes, Users, Warehouse, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "../auth/GHLSessionProvider";
import { api } from "../api/client";
import type { BookingNotificationsResponse, Staff } from "../api/types";
import { formatDay, formatTime } from "../lib/datetime";
import { isRecentlyCreatedBooking } from "../lib/bookingNotifications";
import { OperationNotice } from "../components/OperationNotice";

const links = [
  { to: "/app", label: "Bookings", icon: CalendarDays, end: true },
  { to: "/app/resources", label: "Resources", icon: Warehouse },
  { to: "/app/locations", label: "Locations", icon: MapPin },
  { to: "/app/calendars", label: "Calendars", icon: Shapes },
  { to: "/app/staff", label: "Staff", icon: Users },
];

function StaffRoleBadge() {
  const staff = useQuery({ queryKey: ["staff"], queryFn: () => api<Staff[]>("/staff"), refetchInterval: 45_000 });
  const unassigned = (staff.data || []).filter((member) => member.ghl_user_id && !member.custom_role).length;
  return unassigned ? <span className="nav-count" aria-label={`${unassigned} staff need a custom role`}>{unassigned > 99 ? "99+" : unassigned}</span> : null;
}

function NotificationBell() {
  const { me } = useSession();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const notifications = useQuery({ queryKey: ["booking-notifications"], queryFn: () => api<BookingNotificationsResponse>("/booking-notifications"), refetchInterval: 45_000 });
  const items = notifications.data?.items || [];
  return <div className="notification-wrap">
    <button className="notification-button" aria-label={`Booking notifications${notifications.data?.pending_count ? `, ${notifications.data.pending_count} need assignment` : ""}`} onClick={() => setOpen((value) => !value)}>
      <Bell size={17} />{notifications.data?.pending_count ? <span className="notification-count">{notifications.data.pending_count > 99 ? "99+" : notifications.data.pending_count}</span> : null}
    </button>
    {open && <div className="notification-popover">
      <div className="notification-heading"><strong>Booking notifications</strong><span>{notifications.data?.pending_count || 0} need assignment</span></div>
      {notifications.error && <div className="notification-error">{notifications.error.message}</div>}
      {!notifications.error && !items.length && <p className="muted-note">No recent or upcoming bookings.</p>}
      {items.map((item) => {
        const isNew = isRecentlyCreatedBooking(item.created_at);
        return <button key={item.booking_id} className={`notification-item ${item.assignment_status === "pending" ? "pending" : ""}`} onClick={() => { setOpen(false); navigate(`/app?booking=${encodeURIComponent(item.booking_id)}`); }}>
          <span className="notification-item-title"><strong>{item.customer_name}</strong><span className="notification-badges">{isNew && <span className="badge new">New</span>}{item.assignment_status === "pending" ? <span className="badge warning">Needs Captain</span> : <span className="badge success">Ready</span>}</span></span>
          <span>{item.calendar_name} · {formatDay(item.start_at, me.operator.time_zone)} at {formatTime(item.start_at, me.operator.time_zone)}</span>
          <span>{item.captain_name || item.reason || "Captain assigned"}</span>
        </button>;
      })}
    </div>}
  </div>;
}

export function AppShell() {
  const { me } = useSession();
  const [mobileOpen, setMobileOpen] = useState(false);
  return <div className="app-shell"><button className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu /></button>{mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />}<aside className={`app-sidebar ${mobileOpen ? "open" : ""}`}><div className="sidebar-brand"><div className="brand-mark">P</div><div><strong>Passport</strong><span>{me.operator.name}</span></div><button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)}><X size={18} /></button></div><nav>{links.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}><Icon size={18} />{label}{label === "Staff" && <StaffRoleBadge />}</NavLink>)}</nav><div className="sidebar-bottom"><div className="sidebar-actions"><NavLink to="/app/settings" onClick={() => setMobileOpen(false)}><Settings size={18} />Settings</NavLink><NotificationBell /></div><div className="user-chip"><div className="avatar">{(me.user.name || me.user.email || "U").charAt(0).toUpperCase()}</div><div><strong>{me.user.name || "HighLevel user"}</strong><span>{me.user.role}</span></div></div></div></aside><main className="app-main"><OperationNotice /><Outlet /></main></div>;
}
