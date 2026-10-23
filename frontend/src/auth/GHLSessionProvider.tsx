import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ApiError, api, apiUrl, json, setSessionRefresher, setSessionToken } from "../api/client";
import type { UserContext } from "../api/types";

interface SessionState {
  me: UserContext;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);
const PWA_SESSION_KEY = "passport_staff_session";
const PWA_LOGIN_PENDING_KEY = "passport_staff_login_pending";

function readLegacyPwaSession(): string | null {
  try {
    const persistent = localStorage.getItem(PWA_SESSION_KEY);
    if (persistent) return persistent;
  } catch {
    // Continue to the tab storage fallback.
  }
  try {
    return sessionStorage.getItem(PWA_SESSION_KEY);
  } catch {
    return null;
  }
}

function clearLegacyPwaSession(): void {
  try {
    localStorage.removeItem(PWA_SESSION_KEY);
  } catch {
    // Continue clearing the tab session below.
  }
  try {
    sessionStorage.removeItem(PWA_SESSION_KEY);
  } catch {
    // The HTTP-only refresh cookie is cleared by the logout endpoint.
  }
}

function setPwaLoginPending(value: boolean): void {
  try {
    if (value) sessionStorage.setItem(PWA_LOGIN_PENDING_KEY, "1");
    else sessionStorage.removeItem(PWA_LOGIN_PENDING_KEY);
  } catch {
    // Standalone detection also works from window.parent and the callback hash.
  }
}

function hasPwaLoginPending(): boolean {
  try {
    return sessionStorage.getItem(PWA_LOGIN_PENDING_KEY) === "1";
  } catch {
    return false;
  }
}

function isDefinitiveSessionFailure(reason: unknown): boolean {
  return reason instanceof ApiError && reason.status === 401;
}

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
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const query = new URLSearchParams(window.location.search);
  const returnedFromPwaLogin = hash.has("pwa_code") || query.has("pwa_auth_error");
  return window.parent === window || returnedFromPwaLogin || hasPwaLoginPending();
}

function PwaLoginScreen({ error }: { error: string | null }) {
  return (
    <main className="center-state">
      <section className="state-card pwa-login-card">
        <div className="brand-mark">P</div>
        <h1>Passport Staff</h1>
        <p>{error || "Sign in with your HighLevel account to manage bookings, calendars, staff, payments, and waivers."}</p>
        {error && <div className="error-banner">{error}</div>}
        <a
          className="button"
          href={apiUrl("/pwa-auth/highlevel/start")}
          onClick={() => setPwaLoginPending(true)}
        >
          Login with HighLevel
        </a>
        <small>HighLevel credentials are entered on HighLevel. Passport never stores your HighLevel password.</small>
        <div className="pwa-login-install-note">
          <strong>Install on your phone</strong>
          <span>iPhone: open this page in Safari, tap Share, then Add to Home Screen. Android: open the browser menu, then choose Install app or Add to Home screen.</span>
        </div>
      </section>
    </main>
  );
}

export function GHLSessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<UserContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [standaloneNeedsLogin, setStandaloneNeedsLogin] = useState(false);
  // Keep callback mode stable after the one-time hash is removed on success.
  const [standalone] = useState(isStandalonePwa);
  const refreshTimer = useRef<number | null>(null);
  const sessionActive = useRef(false);

  const scheduleRefresh = useCallback((expiresIn: number, refresh: () => Promise<void>) => {
    if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
    const renewIn = Math.max(30_000, (expiresIn * 1000) - 60_000);
    refreshTimer.current = window.setTimeout(() => void refresh(), renewIn);
  }, []);

  const refresh = useCallback(async () => {
    if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);

    if (standalone) {
      try {
        const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
        const handoff = params.get("pwa_code");
        const callbackError = new URLSearchParams(window.location.search).get("pwa_auth_error");
        if (callbackError) {
          window.history.replaceState({}, document.title, window.location.pathname);
          setStandaloneNeedsLogin(true);
          setPwaLoginPending(false);
          setError(callbackError);
          return;
        }

        let expiresIn: number;
        if (handoff) {
          const session = await api<{ access_token: string; expires_in: number }>(
            "/pwa-auth/exchange",
            json("POST", { code: handoff }),
            { retryOnUnauthorized: false, notifySessionExpired: false },
          );
          setSessionToken(session.access_token);
          clearLegacyPwaSession();
          setPwaLoginPending(false);
          expiresIn = session.expires_in;
          window.history.replaceState({}, document.title, window.location.pathname);
        } else {
          // New PWA sessions are restored from the same-origin HTTP-only refresh
          // cookie. A previously deployed local-storage bearer is accepted once
          // by the backend and migrated to that cookie on this response.
          const stored = readLegacyPwaSession();
          setSessionToken(stored);
          const session = await api<{ access_token: string; expires_in: number }>(
            "/pwa-auth/refresh",
            json("POST", {}),
            { retryOnUnauthorized: false, notifySessionExpired: false },
          );
          setSessionToken(session.access_token);
          clearLegacyPwaSession();
          expiresIn = session.expires_in;
        }
        setError(null);
        setStandaloneNeedsLogin(false);
        scheduleRefresh(expiresIn, refresh);
        setMe(await api<UserContext>("/me", {}, { retryOnUnauthorized: false, notifySessionExpired: false }));
        sessionActive.current = true;
      } catch (reason) {
        if (isDefinitiveSessionFailure(reason)) {
          setSessionToken(null);
          clearLegacyPwaSession();
          sessionActive.current = false;
          setStandaloneNeedsLogin(true);
          setError("Your Passport session has expired or was revoked. Please sign in again.");
        } else if (!sessionActive.current) {
          setError("Passport could not reconnect. Check your connection and try again; your existing login has not been removed.");
        } else {
          // Do not discard a month-long mobile login because a Vercel cold start,
          // temporary network loss, or provider outage interrupted one refresh.
          console.warn("Passport PWA session refresh will be retried later", reason);
        }
      }
      return;
    }

    try {
      setError(null);
      const encryptedData = await requestEncryptedContext();
      const session = await api<{ access_token: string; expires_in: number }>(
        "/auth/ghl-session",
        json("POST", { encryptedData }),
        { retryOnUnauthorized: false, notifySessionExpired: false },
      );
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
  if (error) {
    return (
      <div className="center-state">
        <div className="state-card">
          <div className="brand-mark">P</div>
          <h1>Passport</h1>
          <p>{error}</p>
          <button className="button secondary" onClick={() => void refresh()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!me) {
    return (
      <div className="center-state">
        <div className="state-card">
          <div className="spinner" />
          <h1>Opening Passport</h1>
          <p>{standalone ? "Restoring your Passport session…" : "Verifying your HighLevel workspace…"}</p>
        </div>
      </div>
    );
  }
  return <SessionContext.Provider value={{ me, refresh }}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside GHLSessionProvider");
  return value;
}
