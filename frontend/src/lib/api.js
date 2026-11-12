// Thin fetch wrapper. Every API error has the shape {error: {code, message}} (ADR-0011).

const STAFF_TOKEN_KEY = "ql.staffToken";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export const staffToken = {
  get: () => localStorage.getItem(STAFF_TOKEN_KEY),
  set: (t) => localStorage.setItem(STAFF_TOKEN_KEY, t),
  clear: () => localStorage.removeItem(STAFF_TOKEN_KEY),
};

export async function api(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && staffToken.get()) headers.Authorization = `Bearer ${staffToken.get()}`;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the server. Check your connection.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? {};
    if (res.status === 401 && auth) staffToken.clear();
    throw new ApiError(res.status, err.code ?? "HTTP_" + res.status, err.message ?? res.statusText);
  }
  return data;
}

export function wsUrl(path) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}
