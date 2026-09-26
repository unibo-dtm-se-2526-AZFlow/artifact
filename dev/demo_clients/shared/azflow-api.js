export async function api(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

export function websocket(path) {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${scheme}//${location.host}/api/v1${path}`);
}

export function queryInt(name, fallback = null) {
  const value = new URLSearchParams(location.search).get(name);
  if (value === null || value === "") return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
