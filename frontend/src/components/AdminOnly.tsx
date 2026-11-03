import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useHasPermission, usePwaBootstrap } from "../api/bootstrap";

/** True once the session is known to be an admin's (calendars, resources,
 *  locations, staff and roles, settings). False while still loading. */
export function useIsAdmin(): boolean {
  return useHasPermission("manage_configuration");
}

/** Admin-only page. The API refuses these changes for everyone else; this
 *  keeps non-admins from landing on a page that can only show errors. */
export function AdminOnly({ children }: { children: ReactNode }) {
  const bootstrap = usePwaBootstrap();
  const admin = useIsAdmin();
  if (bootstrap.isLoading) return <div className="loading">Checking access…</div>;
  if (admin) return <>{children}</>;
  return <div className="page">
    <div className="card" style={{ maxWidth: 520 }}>
      <div className="empty-state">
        <ShieldAlert size={22} />
        <strong>Admins only</strong>
        <span>Only a HighLevel admin of this sub-account can manage calendars, resources, locations, staff roles and settings.</span>
        <Link className="button secondary small" to="/app">Back to home</Link>
      </div>
    </div>
  </div>;
}
