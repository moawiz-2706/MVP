import { Outlet } from "react-router-dom";
import { OperationNotice } from "../components/OperationNotice";

export function AppShell() {
  return <div className="app-shell"><main className="app-main"><OperationNotice /><Outlet /></main></div>;
}
