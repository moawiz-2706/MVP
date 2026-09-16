const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");

let sessionToken: string | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
  }
}

export function setSessionToken(token: string | null) {
  sessionToken = token;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (sessionToken) headers.set("Authorization", `Bearer ${sessionToken}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (response.status === 401 && sessionToken) {
    setSessionToken(null);
    window.dispatchEvent(new Event("passport:session-expired"));
  }
  if (!response.ok) {
    let body: { detail?: string; error?: { message?: string; details?: unknown } } = {};
    try { body = await response.json(); } catch { /* non-JSON upstream error */ }
    throw new ApiError(response.status, body.error?.message || body.detail || "Request failed", body.error?.details);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function json(method: string, body: unknown): RequestInit {
  return { method, body: JSON.stringify(body) };
}

