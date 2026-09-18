import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";

export default function App() {
  const [username, setUsername] = useState("demo");
  const [session, setSession] = useState("");
  const [loginMs, setLoginMs] = useState(null);
  const [loginError, setLoginError] = useState("");
  const [pingMs, setPingMs] = useState(null);
  const [pingError, setPingError] = useState("");
  const [jobs, setJobs] = useState([]);
  const [health, setHealth] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const { body } = await api.health();
      setHealth(body);
    } catch {
      setHealth({ status: "degraded", api: "down", redis: "down", worker: "down" });
    }
    try {
      const { body } = await api.jobs();
      setJobs(body.jobs || []);
    } catch {
      setJobs([]);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [refresh]);

  async function onLogin(event) {
    event.preventDefault();
    setLoginError("");
    setSession("");
    try {
      const { body, ms } = await api.login(username);
      setSession(body.session_id);
      setLoginMs(ms);
    } catch (err) {
      setLoginMs(err.ms ?? null);
      setLoginError(err.detail === "fail_closed" ? "fail_closed" : String(err.message));
    }
  }

  async function onPing() {
    setPingError("");
    try {
      const { ms } = await api.enqueue({ kind: "handler" });
      setPingMs(ms);
      await refresh();
    } catch (err) {
      setPingMs(err.ms ?? null);
      setPingError(String(err.detail || err.message));
    }
  }

  async function onEnqueue() {
    setPingError("");
    try {
      const { ms } = await api.enqueue({ kind: "work" });
      setPingMs(ms);
      await refresh();
    } catch (err) {
      setPingMs(err.ms ?? null);
      setPingError(String(err.detail || err.message));
    }
  }

  const status = health?.status === "degraded" ? "degraded" : "ok";

  return (
    <div className="page">
      <header>
        <div>
          <h1>Shop</h1>
          <p>Demo app. Chaos is gated elsewhere.</p>
        </div>
        <span className={`chip ${status}`}>{status}</span>
      </header>

      <section>
        <h2>Login</h2>
        <form onSubmit={onLogin}>
          <label>
            username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <button type="submit">Sign in</button>
        </form>
        {loginError ? <p className="fail">{loginError}</p> : null}
        {session && !loginError ? (
          <p className="note">
            session {session.slice(0, 8)}… · {loginMs} ms
          </p>
        ) : null}
        {loginMs != null && loginError ? <p className="note">{loginMs} ms</p> : null}
      </section>

      <section>
        <h2>Handler</h2>
        <div className="stack">
          <button type="button" onClick={onPing}>
            Hit handler
          </button>
          {pingMs != null ? <p className="note">{pingMs} ms</p> : null}
          {pingError ? <p className="fail">{pingError}</p> : null}
        </div>
      </section>

      <section>
        <h2>Jobs</h2>
        <div className="stack">
          <button type="button" onClick={onEnqueue}>
            Enqueue job
          </button>
          {jobs.length === 0 ? (
            <p className="note">No jobs yet.</p>
          ) : (
            <ul className="jobs">
              {jobs.map((job) => (
                <li key={job.id}>
                  <span>{String(job.id).slice(0, 8)}</span>
                  <span className={`status ${job.status}`}>{job.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
