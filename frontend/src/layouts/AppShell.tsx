import { CalendarDays, ChevronLeft, MapPin, Menu, Settings, Shapes, Users, Warehouse, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useSession } from "../auth/GHLSessionProvider";
import { OperationNotice } from "../components/OperationNotice";

const links = [
  { to: "/app", label: "Bookings", icon: CalendarDays, end: true },
  { to: "/app/resources", label: "Resources", icon: Warehouse },
  { to: "/app/locations", label: "Locations", icon: MapPin },
  { to: "/app/calendars", label: "Calendars", icon: Shapes },
  { to: "/app/staff", label: "Staff", icon: Users },
];

export function AppShell() {
  const { me } = useSession();
  const [mobileOpen, setMobileOpen] = useState(false);
  return <div className="app-shell"><button className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu /></button>{mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />}<aside className={`app-sidebar ${mobileOpen ? "open" : ""}`}><div className="sidebar-brand"><div className="brand-mark">P</div><div><strong>Passport</strong><span>{me.operator.name}</span></div><button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)}><X size={18} /></button></div><nav>{links.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}><Icon size={18} />{label}</NavLink>)}</nav><div className="sidebar-bottom"><NavLink to="/app/settings" onClick={() => setMobileOpen(false)}><Settings size={18} />Settings</NavLink><div className="user-chip"><div className="avatar">{(me.user.name || me.user.email || "U").charAt(0).toUpperCase()}</div><div><strong>{me.user.name || "HighLevel user"}</strong><span>{me.user.role}</span></div></div></div></aside><main className="app-main"><OperationNotice /><Outlet /></main></div>;
}
