import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, apiUrl, json, setSessionRefresher, setSessionToken } from "../api/client";
import type { UserContext } from "../api/types";

interface SessionState { me: UserContext; refresh: () => Promise<void> }
const SessionContext = createContext<SessionState | null>(null);
const PWA_SESSION_KEY = "passport_staff_session";

function requestEncryptedContext(): Promise<string> {
  const allowedOrigins = (import.meta.env.VITE_GHL_PARENT_ORIGINS || "")
    .split(",")
    .map((origin: string) => origin.trim().replace(/\/$/, ""))
    .filter(Boolean);
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", handler);
      reject(new Error("Open Passport from your GoHighLevel sub-account."));
    }, 8000);
    const handler = (event: MessageEvent) => {
      if (event.source !== window.parent) return;
      if (allowedOrigins.length > 0 && !allowedOrigins.includes(event.origin)) return;
      if (event.data?.message !== "REQUEST_USER_DATA_RESPONSE" || typeof event.data.payload !== "string") return;
      window.clearTimeout(timeout);
      window.removeEventListener("message", handler);
      resolve(event.data.payload);
    };
    window.addEventListener("message", handler);
    window.parent.postMessage({ message: "REQUEST_USER_DATA" }, "*");
  });
}

function isStandalonePwa(): boolean {
  return window.parent === window;
}

function PwaLoginScreen({ error }: { error: string | null }) {
  return <main className="center-state"><section className="state-card pwa-login-card"><div className="brand-mark">P</div><h1>Passport Staff</h1><p>{error || "Sign in with your HighLevel account to manage bookings, calendars, staff, payments, and waivers."}</p>{error && <div className="error-banner">{error}</div>}<a className="button" href={apiUrl("/pwa-auth/highlevel/start")}>Login with HighLevel</a><small>HighLevel credentials are entered on HighLevel. Passport never stores your HighLevel password.</small></section></main>;
}

export function GHLSessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<UserContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [standaloneNeedsLogin, setStandaloneNeedsLogin] = useState(false);
  const refreshTimer = useRef<number | null>(null);
  const standalone = isStandalonePwa();

  const scheduleRefresh = useCallback((expiresIn: number, refresh: () => Promise<void>) => {
    if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
    const renewIn = Math.max(30_000, (expiresIn * 1000) - 60_000);
    refreshTimer.current = window.setTimeout(() => void refresh(), renewIn);
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    setMe(null);
    if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);

    if (standalone) {
      try {
        const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
        const handoff = params.get("pwa_code");
        const callbackError = new URLSearchParams(window.location.search).get("pwa_auth_error");
        if (callbackError) {
          window.history.replaceState({}, document.title, window.location.pathname);
          setStandaloneNeedsLogin(true);
          setError(callbackError);
          return;
        }

        let expiresIn = 0;
        if (handoff) {
          const session = await api<{ access_token: string; expires_in: number }>("/pwa-auth/exchange", json("POST", { code: handoff }), { retryOnUnauthorized: false, notifySessionExpired: false });
          setSessionToken(session.access_token);
          sessionStorage.setItem(PWA_SESSION_KEY, session.access_token);
          expiresIn = session.expires_in;
          window.history.replaceState({}, document.title, window.location.pathname);
        } else {
          const stored = sessionStorage.getItem(PWA_SESSION_KEY);
          if (!stored) {
            setStandaloneNeedsLogin(true);
            return;
          }
          setSessionToken(stored);
          const session = await api<{ access_token: string; expires_in: number }>("/pwa-auth/refresh", json("POST", {}), { retryOnUnauthorized: false, notifySessionExpired: false });
          setSessionToken(session.access_token);
          sessionStorage.setItem(PWA_SESSION_KEY, session.access_token);
          expiresIn = session.expires_in;
        }
        setStandaloneNeedsLogin(false);
        scheduleRefresh(expiresIn, refresh);
        setMe(await api<UserContext>("/me", {}, { retryOnUnauthorized: false, notifySessionExpired: false }));
      } catch (reason) {
        setSessionToken(null);
        sessionStorage.removeItem(PWA_SESSION_KEY);
        setStandaloneNeedsLogin(true);
        setError(reason instanceof Error ? reason.message : "HighLevel login could not be completed.");
      }
      return;
    }

    try {
      const encryptedData = await requestEncryptedContext();
      const session = await api<{ access_token: string; expires_in: number }>("/auth/ghl-session", json("POST", { encryptedData }), { retryOnUnauthorized: false, notifySessionExpired: false });
      setSessionToken(session.access_token);
      scheduleRefresh(session.expires_in, refresh);
      setMe(await api<UserContext>("/me", {}, { retryOnUnauthorized: false, notifySessionExpired: false }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to establish a secure session.");
    }
  }, [scheduleRefresh, standalone]);

  useEffect(() => {
    setSessionRefresher(refresh);
    void refresh();
    const expired = () => void refresh();
    window.addEventListener("passport:session-expired", expired);
    return () => {
      setSessionRefresher(null);
      window.removeEventListener("passport:session-expired", expired);
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
    };
  }, [refresh]);

  if (standalone && standaloneNeedsLogin) return <PwaLoginScreen error={error} />;
  if (error) return <div className="center-state"><div className="state-card"><div className="brand-mark">P</div><h1>Passport</h1><p>{error}</p><button className="button secondary" onClick={() => void refresh()}>Try again</button></div></div>;
  if (!me) return <div className="center-state"><div className="state-card"><div className="spinner" /><h1>Opening Passport</h1><p>{standalone ? "Verifying your HighLevel account…" : "Verifying your HighLevel workspace…"}</p></div></div>;
  return <SessionContext.Provider value={{ me, refresh }}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside GHLSessionProvider");
  return value;
}
