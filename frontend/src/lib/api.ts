/**
 * Browser: same-origin /api/* (Next.js rewrites → backend, no CORS).
 * Server: full backend URL.
 */
function apiBase(): string {
  if (typeof window !== "undefined") {
    return "";
  }
  return (
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.BACKEND_INTERNAL_URL ||
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

export type TokenResponse = { access_token: string; token_type: string };

export const POSTGRES_RECOVERY_COPY =
  "Postgres is recovering after the disk filled with 1m bars. On Railway: open the Postgres plugin → Restart. Wait until it is Running, then sign in. Increase the Postgres volume so this cannot happen again.";

export function friendlyApiDetail(detail: string, status?: number): string {
  const text = (detail || "").trim();
  const lower = text.toLowerCase();
  if (
    /recovery mode|starting up|is recovering after the disk|could not connect to server|connection reset|last database write failed/.test(
      lower,
    ) ||
    (status === 502 && /failed to respond|application failed/.test(lower))
  ) {
    return POSTGRES_RECOVERY_COPY;
  }
  return text;
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("propedge_token");
}

export function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("propedge_token", token);
  else localStorage.removeItem("propedge_token");
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", headers.get("Content-Type") || "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${apiBase()}${path}`, { ...init, headers });
  if (res.status === 401) {
    setStoredToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = "";
    try {
      const parsed = JSON.parse(text) as { detail?: string | { msg?: string }[] };
      if (typeof parsed.detail === "string") detail = parsed.detail;
      else if (Array.isArray(parsed.detail)) {
        detail = parsed.detail.map((d) => d.msg).filter(Boolean).join("; ");
      }
    } catch {
      detail = "";
    }
    if (!detail) {
      detail = text.trim().startsWith("Internal")
        ? "The server hit an error. Wait a few seconds and press Run prop search again."
        : text.trim().slice(0, 240) || res.statusText || "Request failed";
    }
    throw new Error(friendlyApiDetail(detail, res.status));
  }
  return res.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  const res = await fetch(`${apiBase()}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
    if (!res.ok) {
    if (res.status === 401) throw new Error("INVALID_CREDENTIALS");
    const text = await res.text();
    let detail = "";
    try {
      const parsed = JSON.parse(text) as { detail?: string; message?: string };
      if (typeof parsed.detail === "string") detail = parsed.detail;
      else if (typeof parsed.message === "string") detail = parsed.message;
    } catch {
      detail = "";
    }
    throw new Error(
      friendlyApiDetail(detail.trim() || text.trim(), res.status) || `API_ERROR_${res.status}`,
    );
  }
  return res.json();
}