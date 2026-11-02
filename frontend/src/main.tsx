import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, isRouteErrorResponse, Navigate, RouterProvider, useRouteError } from "react-router-dom";
import { GHLSessionProvider } from "./auth/GHLSessionProvider";
import { AppShell } from "./layouts/AppShell";
import { registerPwaServiceWorker } from "./pwa";
import "./styles.css";

const DashboardPage = lazy(() => import("./home/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const BookingsPage = lazy(() => import("./bookings/BookingsPage").then((module) => ({ default: module.BookingsPage })));
const ResourcesPage = lazy(() => import("./resources/ResourcesPage").then((module) => ({ default: module.ResourcesPage })));
const LocationsPage = lazy(() => import("./locations/LocationsPage").then((module) => ({ default: module.LocationsPage })));
const CalendarsPage = lazy(() => import("./calendars/CalendarsPage").then((module) => ({ default: module.CalendarsPage })));
const StaffPage = lazy(() => import("./staff/StaffPage").then((module) => ({ default: module.StaffPage })));
const NotificationsPage = lazy(() => import("./notifications/NotificationsPage").then((module) => ({ default: module.NotificationsPage })));
const SettingsPage = lazy(() => import("./settings/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const CustomersPage = lazy(() => import("./customers/CustomersPage").then((module) => ({ default: module.CustomersPage })));
const ReportsPage = lazy(() => import("./reports/ReportsPage").then((module) => ({ default: module.ReportsPage })));
const OperatorBookingPage = lazy(() => import("./public-booking/OperatorBookingPage").then((module) => ({ default: module.OperatorBookingPage })));
const CategoryBookingPage = lazy(() => import("./public-booking/CategoryBookingPage").then((module) => ({ default: module.CategoryBookingPage })));
const CalendarBookingPage = lazy(() => import("./public-booking/CalendarBookingPage").then((module) => ({ default: module.CalendarBookingPage })));
const ConfirmationPage = lazy(() => import("./public-booking/ConfirmationPage").then((module) => ({ default: module.ConfirmationPage })));
const StripeReturnPage = lazy(() => import("./settings/StripeReturnPage").then((module) => ({ default: module.StripeReturnPage })));
const WaiverPage = lazy(() => import("./waivers/WaiverPage").then((module) => ({ default: module.WaiverPage })));
const IntegrationResultPage = lazy(() => import("./IntegrationResultPage").then((module) => ({ default: module.IntegrationResultPage })));
const StaffBookingPage = lazy(() => import("./staff-booking/StaffBookingPage").then((module) => ({ default: module.StaffBookingPage })));

const queryClient = new QueryClient({
  // Mobile PWAs regain focus whenever users switch apps, complete a payment, or
  // unlock their phone. Refetching every mounted query at that point looked like
  // a full page reload and created unnecessary requests. Screens still refetch
  // after reconnecting, from their explicit refresh actions, or by their own
  // focused polling interval where one is needed.
  defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } },
});
const embedded = <GHLSessionProvider><AppShell /></GHLSessionProvider>;

function AppErrorBoundary() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : error instanceof Error ? error.message : "Unexpected application error";
  return <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, background: "#f6f8f8" }}><section className="card" style={{ maxWidth: 560, width: "100%" }}><h1 style={{ marginTop: 0 }}>Passport could not load this page</h1><p className="muted-note">{message}</p><p className="muted-note">Reload the page. If the problem continues, verify the Supabase migrations and the frontend <code>VITE_API_BASE_URL</code> setting.</p><button className="button" onClick={() => window.location.reload()}>Reload Passport</button></section></main>;
}

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/app" replace /> },
  { path: "/app", element: embedded, errorElement: <AppErrorBoundary />, children: [
    { index: true, element: <DashboardPage /> },
    { path: "bookings", element: <BookingsPage /> },
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
  { path: "/staff-book/:token", element: <StaffBookingPage /> },
  { path: "/booking/:publicReference/confirmation", element: <ConfirmationPage /> },
  { path: "/integration-result", element: <IntegrationResultPage /> },
  { path: "/stripe/connect/return", element: <StripeReturnPage /> },
  { path: "/stripe/connect/refresh", element: <StripeReturnPage refresh /> },
  { path: "/waiver/:token", element: <WaiverPage /> },
  { path: "*", element: <Navigate to="/" replace /> },
]);

createRoot(document.getElementById("root")!).render(<StrictMode><QueryClientProvider client={queryClient}><Suspense fallback={<div className="center-state"><div className="state-card"><div className="spinner" /><h1>Opening Passport…</h1></div></div>}><RouterProvider router={router} /></Suspense></QueryClientProvider></StrictMode>);
registerPwaServiceWorker();
