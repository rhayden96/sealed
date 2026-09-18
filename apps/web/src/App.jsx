import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import {
  FAULT_ICONS,
  IconApi,
  IconChevron,
  IconDatabase,
  IconMark,
  IconQueue,
  NAV,
} from "./icons.jsx";

function formatTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString();
}

function formatDetail(detail) {
  if (detail == null) return "request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail.reasons)) {
    return `denied: ${detail.reasons.join(", ")}`;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

function isEmptyPropose(explanation) {
  const text = (explanation || "").toLowerCase();
  return (
    text.includes("no failed or aborted redis_down") ||
    text.includes("nothing to propose")
  );
}

function buildTimeline(draft, seals) {
  if (!draft) return [];
  const events = [{ at: draft.created_at, label: "draft", verdict: "" }];
  if (draft.approved) {
    events.push({ at: draft.created_at, label: "approved", verdict: "" });
  }
  if (draft.unsealed_at) {
    events.push({ at: draft.unsealed_at, label: "unsealed", verdict: "" });
  }
  if (draft.status === "resealed") {
    events.push({
      at: draft.unsealed_until || Date.now() / 1000,
      label: "resealed",
      verdict: "",
    });
  }
  if (draft.status === "completed") {
    events.push({
      at: draft.unsealed_until,
      label: "completed",
      verdict: "",
    });
  }
  const seal = seals
    .filter((item) => item.draft_id === draft.id)
    .sort((a, b) => a.created_at - b.created_at)
    .at(-1);
  if (seal) {
    events.push({
      at: seal.created_at,
      label: "seal",
      verdict: seal.verdict,
    });
  }
  return events;
}

function runPhase(draft) {
  if (!draft) return "none";
  if (draft.status === "unsealed") return "unsealed";
  if (draft.status === "resealed" || draft.status === "completed") {
    return "completed";
  }
  return "draft";
}

function stepVocab(status) {
  if (status === "unsealed") return "unsealed";
  if (status === "resealed") return "resealed";
  if (status === "completed") return "sealed";
  return "pending";
}

const WATCH = {
  handler_latency: "Watch the app for slowness.",
  redis_down: "Watch login — it fail-closes.",
  worker_drop: "Watch jobs — some are dropped.",
};

const DEMO_DAY = ["handler_latency", "redis_down", "worker_drop"];

const SIDE_KEY = "sealed-sidebar-collapsed";

export default function App() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [panel, setPanel] = useState("live");
  const [catalog, setCatalog] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [seals, setSeals] = useState([]);
  const [fixtures, setFixtures] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [catalogId, setCatalogId] = useState("handler_latency");
  const [error, setError] = useState("");
  const [helper, setHelper] = useState("");
  const [health, setHealth] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [controlDown, setControlDown] = useState(false);
  const [gameDay, setGameDay] = useState(null);

  const selected = drafts.find((d) => d.id === selectedId) || null;
  const experiment = catalog.find((item) => item.id === catalogId);
  const lastSeal = useMemo(
    () => [...seals].sort((a, b) => b.created_at - a.created_at)[0] || null,
    [seals],
  );
  const timeline = buildTimeline(selected, seals);
  const phase = runPhase(selected);
  const liveDraft = drafts.find((d) => d.status === "unsealed");
  const healthMoved = health?.status === "degraded";
  const liveStatus = healthMoved
    ? "degraded"
    : liveDraft
      ? "watch"
      : "ok";
  const livePill =
    liveStatus === "degraded"
      ? "LIVE degraded"
      : liveStatus === "watch"
        ? "LIVE · health unchanged — watch the app"
        : "LIVE ok";
  const currentStep = gameDay?.steps.find((step) => step.current) || null;
  const dayDone = Boolean(gameDay && gameDay.current_index == null);
  const currentVocab = currentStep ? stepVocab(currentStep.status) : "pending";

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem(SIDE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  const refreshControl = useCallback(async () => {
    try {
      await api.controlHealth();
      setControlDown(false);
    } catch {
      setControlDown(true);
      return;
    }
    const [nextCatalog, nextDrafts, nextSeals, nextFixtures] = await Promise.all([
      api.catalog(),
      api.drafts(),
      api.seals(),
      api.fixtures().catch(() => ({ seals: [] })),
    ]);
    setCatalog(nextCatalog.experiments || []);
    setDrafts(nextDrafts);
    setSeals(nextSeals);
    setFixtures(nextFixtures.seals || []);
  }, []);

  const refreshLive = useCallback(async () => {
    const [nextHealth, nextMetrics] = await Promise.all([
      api.health(),
      api.metrics(),
    ]);
    setHealth(nextHealth);
    setMetrics(nextMetrics);
  }, []);

  useEffect(() => {
    refreshControl().catch((err) =>
      setError(formatDetail(err.detail || err.message)),
    );
    refreshLive().catch(() => {});
  }, [refreshControl, refreshLive]);

  useEffect(() => {
    const id = setInterval(() => refreshControl().catch(() => {}), 2000);
    return () => clearInterval(id);
  }, [refreshControl]);

  useEffect(() => {
    const id = setInterval(() => refreshLive().catch(() => {}), 2000);
    return () => clearInterval(id);
  }, [refreshLive]);

  useEffect(() => {
    if (!gameDay?.id) return undefined;
    const id = setInterval(() => {
      api.gameDay(gameDay.id).then(setGameDay).catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [gameDay?.id]);

  async function createDraft() {
    if (!experiment) return;
    setError("");
    setHelper("");
    try {
      const draft = await api.createDraft({
        catalog_id: experiment.id,
        environment: "demo",
        target: experiment.allowed_targets?.[0] || "api",
        duration_s: Number(experiment.default_duration_s ?? 5),
      });
      setSelectedId(draft.id);
      await refreshControl();
    } catch (err) {
      setError(formatDetail(err.detail || err.message));
    }
  }

  async function approveAndUnseal() {
    if (!selected) return;
    setError("");
    setHelper("");
    try {
      await api.approve(selected.id);
      await api.unseal(selected.id);
      await refreshControl();
      await refreshLive();
    } catch (err) {
      setError(formatDetail(err.detail || err.message));
      await refreshControl();
    }
  }

  async function abort() {
    if (!selected) return;
    setError("");
    setHelper("");
    try {
      await api.reseal(selected.id);
      await refreshControl();
      await refreshLive();
    } catch (err) {
      setError(formatDetail(err.detail || err.message));
    }
  }

  async function unsealOnly() {
    if (!selected) return;
    setError("");
    setHelper("");
    try {
      await api.unseal(selected.id);
      await refreshControl();
      await refreshLive();
    } catch (err) {
      setError(formatDetail(err.detail || err.message));
    }
  }

  async function propose() {
    setError("");
    setHelper("");
    try {
      const result = await api.propose();
      if (result.draft?.id) {
        setSelectedId(result.draft.id);
        setHelper("");
        setPanel("run");
      } else {
        setHelper(
          result.explanation ||
            "No failed or aborted redis_down seal; nothing to propose.",
        );
      }
      await refreshControl();
    } catch (err) {
      const text = formatDetail(err.detail || err.message);
      if (isEmptyPropose(text)) setHelper(text);
      else setError(text);
    }
  }

  const canUnseal =
    selected &&
    selected.status !== "unsealed" &&
    selected.status !== "resealed" &&
    selected.status !== "completed";

  return (
    <div className={collapsed ? "shell collapsed" : "shell"}>
      <aside className="sidebar">
        <button
          type="button"
          className="side-toggle"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <IconChevron left={!collapsed} />
        </button>
        <nav className="nav">
          {NAV.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              className={panel === id ? "active" : ""}
              onClick={() => setPanel(id)}
              title={label}
            >
              <Icon />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="mark">
            <IconMark />
            Sealed
          </div>
          <span className="env">demo</span>
          <span className={`pill ${liveStatus}`}>{livePill}</span>
          <a className="target-link" href="http://localhost:5174">
            Open target app
          </a>
        </header>
        {controlDown ? (
          <div className="banner">Control unreachable. Start the stack, then refresh.</div>
        ) : null}

        <div className="content">
          {panel === "live" ? (
            <section className="panel">
              <h2>Live</h2>
              <p className={`status-word ${healthMoved ? "degraded" : "ok"}`}>
                {healthMoved ? "DEGRADED" : "OK"}
              </p>
              <div className="tiles">
                <article className={`tile ${health?.api === "down" ? "down" : "ok"}`}>
                  <header>
                    <IconApi /> API
                  </header>
                  <strong>{health?.api ?? "—"}</strong>
                </article>
                <article
                  className={`tile ${health?.redis === "down" ? "down" : "ok"}`}
                >
                  <header>
                    <IconDatabase /> Redis
                  </header>
                  <strong>{health?.redis ?? "—"}</strong>
                </article>
                <article
                  className={`tile ${health?.worker === "down" ? "down" : "ok"}`}
                >
                  <header>
                    <IconQueue /> Worker
                  </header>
                  <strong>{health?.worker ?? "—"}</strong>
                </article>
              </div>
              <p className="stats">
                <span>
                  p95 <b>{metrics ? Number(metrics.p95_ms).toFixed(0) : "—"}</b> ms
                </span>
                <span>
                  error <b>{metrics ? Number(metrics.error_rate).toFixed(2) : "—"}</b>
                </span>
                <span>
                  inflight <b>{metrics?.inflight ?? "—"}</b>
                </span>
              </p>
            </section>
          ) : null}

          {panel === "catalog" ? (
            <section className="panel">
              <h2>Catalog</h2>
              <div className="catalog-grid">
                {catalog.map((item) => {
                  const Icon = FAULT_ICONS[item.id] || IconApi;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={item.id === catalogId ? "fault active" : "fault"}
                      onClick={() => {
                        setCatalogId(item.id);
                        setHelper("");
                        setError("");
                      }}
                    >
                      <Icon />
                      <h3>{item.id}</h3>
                      <p>
                        {item.description} · {item.default_duration_s}s ·{" "}
                        {(item.allowed_targets || []).join(", ")}
                      </p>
                    </button>
                  );
                })}
              </div>
            </section>
          ) : null}

          {panel === "run" ? (
            <section className="panel">
              <h2>Run</h2>
              <p className="run-meta">
                {experiment ? (
                  <>
                    <strong>{experiment.id}</strong> · demo ·{" "}
                    {experiment.allowed_targets?.[0]} ·{" "}
                    {experiment.default_duration_s}s
                  </>
                ) : (
                  "Select an experiment."
                )}
                {selected ? (
                  <>
                    <br />
                    {selected.id} · {selected.status}
                    {selected.source === "agent" ? " · agent" : ""}
                  </>
                ) : null}
              </p>

              {phase === "none" || phase === "completed" ? (
                <button
                  type="button"
                  className="primary"
                  disabled={!experiment}
                  onClick={createDraft}
                >
                  {phase === "completed" ? "New draft" : "Create draft"}
                </button>
              ) : null}
              {phase === "draft" ? (
                <button
                  type="button"
                  className="primary"
                  onClick={approveAndUnseal}
                >
                  Approve + unseal
                </button>
              ) : null}
              {phase === "unsealed" ? (
                <button type="button" className="primary abort" onClick={abort}>
                  Abort / reseal
                </button>
              ) : null}

              <div className="ghosts">
                <button
                  type="button"
                  className="ghost"
                  disabled={!canUnseal}
                  onClick={unsealOnly}
                >
                  Unseal
                </button>
                <button type="button" className="ghost" onClick={propose}>
                  Propose
                </button>
              </div>
              {helper ? <p className="helper">{helper}</p> : null}
              {error ? <p className="error">{error}</p> : null}
            </section>
          ) : null}

          {panel === "gameday" ? (
            <section className="panel">
              <h2>Game day</h2>
              {!gameDay ? (
                <button
                  type="button"
                  className="primary"
                  onClick={async () => {
                    setError("");
                    try {
                      const day = await api.createGameDay(DEMO_DAY);
                      setGameDay(day);
                    } catch (err) {
                      setError(formatDetail(err.detail || err.message));
                    }
                  }}
                >
                  Start demo day
                </button>
              ) : (
                <>
                  <div className="gd-head">
                    <p className="gd-headline">
                      {dayDone
                        ? "Day complete"
                        : `Step ${currentStep.index + 1} of ${gameDay.steps.length} — ${currentStep.catalog_id} is ${currentVocab}`}
                    </p>
                    {currentVocab === "unsealed" ? (
                      <a className="gd-open" href="http://localhost:5174">
                        Open target app :5174
                      </a>
                    ) : null}
                  </div>
                  {currentVocab === "unsealed" ? (
                    <p className="helper">
                      {WATCH[currentStep.catalog_id] ||
                        "Watch the target app."}
                    </p>
                  ) : null}

                  <div className="gd-cards">
                    {gameDay.steps.map((step) => {
                      const vocab = stepVocab(step.status);
                      return (
                        <article
                          key={step.draft_id}
                          className={
                            step.current ? "gd-card current" : "gd-card"
                          }
                        >
                          <span className="muted">
                            Step {step.index + 1}
                          </span>
                          <strong>{step.catalog_id}</strong>
                          <span className={`gd-state ${vocab}`}>{vocab}</span>
                        </article>
                      );
                    })}
                  </div>

                  {dayDone ? (
                    <button
                      type="button"
                      className="primary"
                      onClick={() => {
                        setGameDay(null);
                        setError("");
                      }}
                    >
                      End day
                    </button>
                  ) : currentVocab === "unsealed" ? (
                    <button
                      type="button"
                      className="primary abort"
                      onClick={async () => {
                        setError("");
                        try {
                          const result = await api.abortGameDay(gameDay.id);
                          setGameDay(result.game_day);
                          await refreshLive();
                        } catch (err) {
                          setError(formatDetail(err.detail || err.message));
                        }
                      }}
                    >
                      Abort this step
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="primary"
                      onClick={async () => {
                        if (!currentStep) return;
                        setError("");
                        try {
                          await api.approve(currentStep.draft_id);
                          await api.unseal(currentStep.draft_id);
                          setGameDay(await api.gameDay(gameDay.id));
                          await refreshLive();
                        } catch (err) {
                          setError(formatDetail(err.detail || err.message));
                          setGameDay(await api.gameDay(gameDay.id));
                        }
                      }}
                    >
                      Approve + unseal
                    </button>
                  )}
                </>
              )}
              {error ? <p className="error">{error}</p> : null}
            </section>
          ) : null}

          {panel === "tape" ? (
            <section className="panel">
              <h2>Tape</h2>
              {timeline.length === 0 ? (
                <p className="helper">No run selected.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Event</th>
                      <th>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {timeline.map((event, index) => (
                      <tr key={`${event.label}-${index}`}>
                        <td>
                          <time>{formatTime(event.at)}</time>
                        </td>
                        <td>{event.label}</td>
                        <td>
                          {event.verdict ? (
                            <span className={`verdict ${event.verdict}`}>
                              {event.verdict.toUpperCase()}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="seal-card">
                {lastSeal ? (
                  <>
                    <span className="muted">
                      {lastSeal.id} · {lastSeal.catalog_id} · {lastSeal.draft_id}
                    </span>
                    <span className={`verdict ${lastSeal.verdict}`}>
                      {lastSeal.verdict.toUpperCase()}
                    </span>
                  </>
                ) : (
                  <span className="muted">No seals yet.</span>
                )}
              </div>
            </section>
          ) : null}

          {panel === "fixtures" ? (
            <section className="panel">
              <h2>Fixtures</h2>
              <p className="helper">Replay only. Does not unseal or inject.</p>
              {fixtures.length === 0 ? (
                <p className="helper">No fixtures loaded.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Id</th>
                      <th>Catalog</th>
                      <th>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fixtures.map((seal) => (
                      <tr key={seal.id}>
                        <td>{seal.id}</td>
                        <td>{seal.catalog_id}</td>
                        <td>
                          <span className={`verdict ${seal.verdict}`}>
                            {(seal.verdict || "").toUpperCase()}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
