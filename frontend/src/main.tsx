import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, isRouteErrorResponse, Navigate, RouterProvider, useRouteError } from "react-router-dom";
import { GHLSessionProvider } from "./auth/GHLSessionProvider";
import { AppShell } from "./layouts/AppShell";
import { BookingsPage } from "./bookings/BookingsPage";
import { ResourcesPage } from "./resources/ResourcesPage";
import { LocationsPage } from "./locations/LocationsPage";
import { CalendarsPage } from "./calendars/CalendarsPage";
import { StaffPage } from "./staff/StaffPage";
import { NotificationsPage } from "./notifications/NotificationsPage";
import { SettingsPage } from "./settings/SettingsPage";
import { OperatorBookingPage } from "./public-booking/OperatorBookingPage";
import { CategoryBookingPage } from "./public-booking/CategoryBookingPage";
import { CalendarBookingPage } from "./public-booking/CalendarBookingPage";
import { ConfirmationPage } from "./public-booking/ConfirmationPage";
import { StripeReturnPage } from "./settings/StripeReturnPage";
import { WaiverPage } from "./waivers/WaiverPage";
import { IntegrationResultPage } from "./IntegrationResultPage";
import { CustomersPage } from "./customers/CustomersPage";
import { ReportsPage } from "./reports/ReportsPage";
import "./styles.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 20_000, retry: 1, refetchOnWindowFocus: true } } });
const embedded = <GHLSessionProvider><AppShell /></GHLSessionProvider>;
function AppErrorBoundary() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "Unexpected application error";
  return <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, background: "#f6f8f8" }}><section className="card" style={{ maxWidth: 560, width: "100%" }}><h1 style={{ marginTop: 0 }}>Passport could not load this page</h1><p className="muted-note">{message}</p><p className="muted-note">Reload the page. If the problem continues, verify the Supabase migrations and the frontend <code>VITE_API_BASE_URL</code> setting.</p><button className="button" onClick={() => window.location.reload()}>Reload Passport</button></section></main>;
}
const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/app" replace /> },
  { path: "/app", element: embedded, errorElement: <AppErrorBoundary />, children: [
    { index: true, element: <BookingsPage /> },
    { path: "notifications", element: <NotificationsPage /> },
    { path: "resources", element: <ResourcesPage /> },
    { path: "locations", element: <LocationsPage /> },
    { path: "calendars", element: <CalendarsPage /> },
    { path: "staff", element: <StaffPage /> },
    { path: "customers", element: <CustomersPage /> },
    { path: "reports", element: <ReportsPage /> },
    { path: "settings", element: <SettingsPage /> },
  ] },
  { path: "/book/:operatorSlug", element: <OperatorBookingPage /> },
  { path: "/book/:operatorSlug/category/:categorySlug", element: <CategoryBookingPage /> },
  { path: "/book/:operatorSlug/:calendarSlug", element: <CalendarBookingPage /> },
  { path: "/booking/:publicReference/confirmation", element: <ConfirmationPage /> },
  { path: "/integration-result", element: <IntegrationResultPage /> },
  { path: "/stripe/connect/return", element: <StripeReturnPage /> },
  { path: "/stripe/connect/refresh", element: <StripeReturnPage refresh /> },
  { path: "/waiver/:token", element: <WaiverPage /> },
  { path: "*", element: <Navigate to="/" replace /> },
]);

createRoot(document.getElementById("root")!).render(<StrictMode><QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider></StrictMode>);
