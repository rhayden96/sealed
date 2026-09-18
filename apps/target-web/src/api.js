async function req(path, opts = {}) {
  const started = performance.now();
  const response = await fetch(`/api${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  const ms = Math.round(performance.now() - started);
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
        ? String(body.detail ?? JSON.stringify(body))
        : text || response.statusText,
    );
    error.status = response.status;
    error.detail = body?.detail ?? body;
    error.ms = ms;
    throw error;
  }
  return { body, ms };
}

export const api = {
  health: () => req("/health"),
  login: (username) =>
    req("/login", { method: "POST", body: JSON.stringify({ username }) }),
  enqueue: (payload) =>
    req("/jobs", { method: "POST", body: JSON.stringify({ payload }) }),
  jobs: () => req("/jobs"),
};
