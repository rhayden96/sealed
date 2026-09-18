async function req(path, opts = {}) {
  const response = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    const error = new Error(
      typeof body === "object"
        ? JSON.stringify(body.detail ?? body)
        : text || response.statusText,
    );
    error.status = response.status;
    error.detail = body?.detail ?? body;
    throw error;
  }
  return body;
}

export const api = {
  catalog: () => req("/api/catalog"),
  drafts: () => req("/api/drafts"),
  createDraft: (body) =>
    req("/api/drafts", { method: "POST", body: JSON.stringify(body) }),
  approve: (id) => req(`/api/drafts/${id}/approve`, { method: "POST" }),
  unseal: (id) => req(`/api/drafts/${id}/unseal`, { method: "POST" }),
  reseal: (id) => req(`/api/drafts/${id}/reseal`, { method: "POST" }),
  seals: () => req("/api/seals"),
  propose: () => req("/api/agent/propose", { method: "POST" }),
  fixtures: () => req("/api/fixtures"),
  controlHealth: () => req("/api/health"),
  createGameDay: (steps) =>
    req("/api/game-days", { method: "POST", body: JSON.stringify({ steps }) }),
  gameDay: (id) => req(`/api/game-days/${id}`),
  abortGameDay: (id) => req(`/api/game-days/${id}/abort`, { method: "POST" }),
  health: () => req("/target/health"),
  metrics: () => req("/target/metrics"),
};
