import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Bell,
  CalendarDays,
  Home,
  MapPin,
  Menu,
  Moon,
  Search,
  Settings,
  Shapes,
  Sun,
  UserRound,
  Users,
  Warehouse,
  X,
} from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import type { PwaBootstrapResponse } from "../api/types";
import { useSession } from "../auth/GHLSessionProvider";
import { GlobalSearch } from "../components/GlobalSearch";
import { OperationNotice } from "../components/OperationNotice";
import { PwaInstallPrompt } from "../components/PwaInstallPrompt";

const links = [
  { to: "/app", label: "Home", icon: Home, end: true },
  { to: "/app/bookings", label: "Bookings", icon: CalendarDays },
  { to: "/app/notifications", label: "Notifications", icon: Bell },
  { to: "/app/resources", label: "Resources", icon: Warehouse, feature: "calendar_management" },
  { to: "/app/locations", label: "Locations", icon: MapPin, feature: "calendar_management" },
  { to: "/app/calendars", label: "Calendars", icon: Shapes, feature: "calendar_management" },
  { to: "/app/staff", label: "Staff", icon: Users },
  { to: "/app/customers", label: "Customers", icon: UserRound },
  { to: "/app/reports", label: "Reports", icon: BarChart3 },
];

type Theme = "light" | "dark";

function loadTheme(): Theme {
  try {
    return localStorage.getItem("passport-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function OfflineStatus() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);
  return online ? null : <div className="offline-status" role="status">You are offline. Reconnect to view live bookings or make changes.</div>;
}

export function AppShell() {
  const { me } = useSession();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const bootstrap = useQuery({
    queryKey: ["pwa-bootstrap"],
    queryFn: () => api<PwaBootstrapResponse>("/pwa/bootstrap"),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  });
  const features = bootstrap.data?.features;
  const notificationCount = bootstrap.data?.badge_counts.notifications || 0;
  const staffMissingRoles = bootstrap.data?.badge_counts.staff_missing_roles || 0;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("passport-theme", theme);
    } catch {
      // Private browsing can disallow storage; the theme still applies for this session.
    }
  }, [theme]);

  useEffect(() => {
    const openSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", openSearch);
    return () => window.removeEventListener("keydown", openSearch);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("passport-mobile-nav-open", mobileOpen);
    return () => document.body.classList.remove("passport-mobile-nav-open");
  }, [mobileOpen]);

  return (
    <div className="app-shell">
      <button className={`mobile-menu ${mobileOpen ? "menu-hidden" : ""}`} onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu /></button>
      {mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />}
      <aside className={`app-sidebar ${mobileOpen ? "open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">P</div>
          <div><strong>Passport</strong><span>{me.operator.name}</span></div>
          <button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>
        <nav>
          {links.filter((item) => !item.feature || features?.[item.feature] !== false).map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>
              <Icon size={18} />{label}
              {label === "Staff" && staffMissingRoles > 0 && <span className="nav-count" aria-label={`${staffMissingRoles} staff need a custom role`}>{staffMissingRoles > 99 ? "99+" : staffMissingRoles}</span>}
              {label === "Notifications" && notificationCount > 0 && <span className="nav-count" aria-label={`${notificationCount} notifications require attention`}>{notificationCount > 99 ? "99+" : notificationCount}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/app/settings" onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}><Settings size={18} />Settings</NavLink>
          <div className="user-chip"><div className="avatar">{(me.user.name || me.user.email || "U").charAt(0).toUpperCase()}</div><div><strong>{me.user.name || "Passport user"}</strong><span>{me.user.role}</span></div></div>
        </div>
      </aside>
      <main className="app-main">
        <header className="pwa-topbar">
          <button className="pwa-search-launcher" type="button" onClick={() => setSearchOpen(true)} aria-label="Search Passport">
            <Search size={17} aria-hidden="true" /><span>Search Passport</span><kbd>⌘ K</kbd>
          </button>
          <button className="icon-button theme-toggle" type="button" onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")} aria-label={`Use ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </header>
        <OfflineStatus />
        <PwaInstallPrompt />
        <OperationNotice />
        <Suspense fallback={<div className="page-route-loading" role="status"><div className="spinner" /><span>Loading Passport workspace…</span></div>}>
          <Outlet />
        </Suspense>
      </main>
      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
