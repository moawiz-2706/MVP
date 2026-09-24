const configuredApiBase = import.meta.env.VITE_API_BASE_URL;
const API_BASE = (configuredApiBase || (import.meta.env.DEV ? "http://localhost:8000/api/v1" : "/api/v1")).replace(/\/$/, "");

let sessionToken: string | null = null;
let refreshSession: (() => Promise<void>) | null = null;
let refreshInFlight: Promise<void> | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
  }
}

export function setSessionToken(token: string | null) {
  sessionToken = token;
}

export function setSessionRefresher(callback: (() => Promise<void>) | null) {
  refreshSession = callback;
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  options: { retryOnUnauthorized?: boolean; notifySessionExpired?: boolean } = {},
): Promise<T> {
  const retryOnUnauthorized = options.retryOnUnauthorized ?? true;
  const notifySessionExpired = options.notifySessionExpired ?? true;
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (sessionToken) headers.set("Authorization", `Bearer ${sessionToken}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (response.status === 401 && sessionToken && retryOnUnauthorized && refreshSession) {
    try {
      if (!refreshInFlight) {
        refreshInFlight = refreshSession().finally(() => {
          refreshInFlight = null;
        });
      }
      await refreshInFlight;
      if (sessionToken) return api<T>(path, init, { retryOnUnauthorized: false, notifySessionExpired: false });
    } catch {
      // The original 401 is reported below; the refresh failure is not exposed.
    }
  }
  if (response.status === 401 && notifySessionExpired) {
    setSessionToken(null);
    window.dispatchEvent(new Event("passport:session-expired"));
  }
  if (!response.ok) {
    let body: { detail?: string; error?: { message?: string; details?: unknown } } = {};
    try { body = await response.json(); } catch { /* non-JSON upstream error */ }
    const message = body.error?.message || body.detail || "Request failed";
    window.dispatchEvent(new CustomEvent("passport:operation", {
      detail: { method, path, success: false, message },
    }));
    throw new ApiError(response.status, `${message} (HTTP ${response.status}; ${method} ${path})`, body.error?.details);
  }
  if (method !== "GET" && method !== "HEAD") {
    window.dispatchEvent(new CustomEvent("passport:operation", {
      detail: { method, path, success: true },
    }));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function json(method: string, body: unknown): RequestInit {
  return { method, body: JSON.stringify(body) };
}

export async function download(path: string, filename: string): Promise<void> {
  const headers = new Headers();
  if (sessionToken) headers.set("Authorization", `Bearer ${sessionToken}`);
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) throw new ApiError(response.status, "Report download failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
