import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, json, setSessionRefresher, setSessionToken } from "../api/client";
import type { UserContext } from "../api/types";

interface SessionState { me: UserContext; refresh: () => Promise<void> }
const SessionContext = createContext<SessionState | null>(null);

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

export function GHLSessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<UserContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    setMe(null);
    setSessionToken(null);
    try {
      const encryptedData = await requestEncryptedContext();
      const session = await api<{ access_token: string; expires_in: number }>("/auth/ghl-session", json("POST", { encryptedData }), { retryOnUnauthorized: false, notifySessionExpired: false });
      setSessionToken(session.access_token);
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
      const renewIn = Math.max(30_000, (session.expires_in * 1000) - 60_000);
      refreshTimer.current = window.setTimeout(() => void refresh(), renewIn);
      setMe(await api<UserContext>("/me", {}, { retryOnUnauthorized: false, notifySessionExpired: false }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to establish a secure session.");
    }
  }, [refreshTimer]);

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
  }, [refresh, refreshTimer]);

  if (error) return <div className="center-state"><div className="state-card"><div className="brand-mark">P</div><h1>Passport</h1><p>{error}</p><button className="button secondary" onClick={() => void refresh()}>Try again</button></div></div>;
  if (!me) return <div className="center-state"><div className="state-card"><div className="spinner" /><h1>Opening Passport</h1><p>Verifying your HighLevel workspace…</p></div></div>;
  return <SessionContext.Provider value={{ me, refresh }}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside GHLSessionProvider");
  return value;
}
