import { useEffect, useState } from 'react';
import { formatDetail } from '../../../packages/web/client.js';
import { api } from './api.js';
import {
  ageLabel,
  healthState,
  jobLabel,
  jobReason,
  observationState,
  serviceLabel,
} from './observations.js';
import { useAction, useResource } from './useResource.js';

function failureMessage(error, action) {
  if (error?.detail === 'fail_closed') return 'Redis is unavailable. This request failed closed.';
  if (error?.detail === 'queue_full')
    return 'The queue is full. Wait for the worker to finish jobs, then retry.';
  if (error?.code === 'timeout')
    return 'The request timed out. Its outcome is unconfirmed; check observations before retrying.';
  return error?.detail != null
    ? formatDetail(error.detail)
    : error?.message || `${action} is unavailable. Try again.`;
}

function ActionError({ error, action, completedAt }) {
  return error ? (
    <p className="fail" role="alert">
      {failureMessage(error, action)}
      {Number.isFinite(error.ms) ? ` · ${Math.round(error.ms)} ms` : ''}
      <ActionTime at={completedAt} />
    </p>
  ) : null;
}

function ActionTime({ at }) {
  if (at == null) return null;
  const date = new Date(at);
  return (
    <span className="action-time">
      Last response{' '}
      <time
        dateTime={date.toISOString()}
        title={date.toLocaleString(undefined, { timeZoneName: 'short' })}
      >
        {date.toLocaleTimeString()}
      </time>
      . This records that request, not current service health.
    </span>
  );
}

function Updated({ at, now }) {
  return (
    <p className="note observation-age">
      {ageLabel(at, now)}
      {at != null && (
        <time
          dateTime={new Date(at).toISOString()}
          title={new Date(at).toLocaleString(undefined, {
            timeZoneName: 'short',
          })}
        >
          {' '}
          · {new Date(at).toLocaleTimeString()}
        </time>
      )}
    </p>
  );
}

export default function App() {
  const [username, setUsername] = useState('demo');
  const [health, refreshHealth] = useResource(api.health);
  const [jobs, refreshJobs] = useResource(api.jobs);
  const login = useAction();
  const probe = useAction();
  const enqueue = useAction();
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const status = healthState(health, now);
  const healthObservation = observationState(health, now);
  const jobsObservation = observationState(jobs, now);
  const jobList = jobs.data?.jobs || [];
  const currentHealth = healthObservation === 'current';

  function onLogin(event) {
    event.preventDefault();
    login.run((options) => api.login(username, options), refreshHealth);
  }

  return (
    <main className="page">
      <header>
        <div>
          <p className="eyebrow">Sealed · local demo target</p>
          <h1>Shop</h1>
          <p>Watch requests and worker jobs during an experiment.</p>
        </div>
        <span className={`chip ${status}`} role="status">
          {status}
        </span>
      </header>

      <section className="health-panel" aria-labelledby="health-title">
        <div className="section-heading">
          <h2 id="health-title">Service observations</h2>
          <button type="button" className="quiet-button" onClick={refreshHealth}>
            Refresh status
          </button>
        </div>
        <dl className="services">
          {[
            ['api', 'API'],
            ['redis', 'Redis'],
            ['worker', 'Worker'],
          ].map(([key, title]) => {
            const known = health.data?.[key];
            const current = currentHealth ? known : 'unknown';
            return (
              <div key={key}>
                <dt>{title}</dt>
                <dd className={`service-state ${current || 'unknown'}`}>{serviceLabel(current)}</dd>
                {!currentHealth && health.updatedAt != null && (
                  <span className="last-known">Last known: {serviceLabel(known)}</span>
                )}
              </div>
            );
          })}
        </dl>
        {healthObservation === 'loading' && (
          <p className="note">Waiting for the first target observation…</p>
        )}
        {(healthObservation === 'unavailable' || healthObservation === 'stale') && (
          <p className="fail" role="status">
            Target observations unavailable. Current service states are unknown.
          </p>
        )}
        {currentHealth && health.data?.worker_reason === 'heartbeat_stale' && (
          <p className="note">
            Worker heartbeat is stale. The worker may be stopped or disconnected.
          </p>
        )}
        <Updated at={health.updatedAt} now={now} />
      </section>

      <section aria-labelledby="login-title">
        <h2 id="login-title">Session probe</h2>
        <p className="note section-description">
          Synthetic Redis session probe for this local demo.
        </p>
        <form onSubmit={onLogin}>
          <label>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              maxLength={128}
              required
              autoComplete="off"
            />
          </label>
          <button type="submit" disabled={login.pending || !username.trim()}>
            {login.pending ? 'Checking session…' : 'Probe session'}
          </button>
        </form>
        <div className="action-feedback" aria-live="polite">
          {login.result && (
            <p className="note">
              Demo session {String(login.result.body?.session_id || '').slice(0, 8)}… ·{' '}
              {Math.round(login.result.ms)} ms
              <ActionTime at={login.completedAt} />
            </p>
          )}
        </div>
        <ActionError error={login.error} action="Session probe" completedAt={login.completedAt} />
      </section>

      <section aria-labelledby="handler-title">
        <h2 id="handler-title">Handler</h2>
        <p className="note section-description">
          Measure a request without creating a session or a job.
        </p>
        <div className="stack">
          <button type="button" onClick={() => probe.run(api.probe)} disabled={probe.pending}>
            {probe.pending ? 'Probing handler…' : 'Hit handler'}
          </button>
          <div className="action-feedback" aria-live="polite">
            {probe.result && (
              <p className="note">
                Handler responded · {Math.round(probe.result.ms)} ms
                <ActionTime at={probe.completedAt} />
              </p>
            )}
          </div>
          <ActionError error={probe.error} action="Handler probe" completedAt={probe.completedAt} />
        </div>
      </section>

      <section aria-labelledby="jobs-title">
        <div className="section-heading">
          <h2 id="jobs-title">Jobs</h2>
          <span className={`observation-badge ${jobsObservation}`}>
            {jobsObservation === 'current' ? 'Current' : jobsObservation}
          </span>
        </div>
        <div className="stack">
          <button
            type="button"
            onClick={() =>
              enqueue.run((options) => api.enqueue({ kind: 'demo-work' }, options), refreshJobs)
            }
            disabled={enqueue.pending}
          >
            {enqueue.pending ? 'Enqueuing…' : 'Enqueue job'}
          </button>
          <div className="action-feedback" aria-live="polite">
            {enqueue.result && (
              <p className="note">
                Queued job {String(enqueue.result.body?.job_id || '').slice(0, 8)}… ·{' '}
                {Math.round(enqueue.result.ms)} ms
                <ActionTime at={enqueue.completedAt} />
              </p>
            )}
          </div>
          <ActionError error={enqueue.error} action="Enqueue" completedAt={enqueue.completedAt} />
          {jobsObservation === 'loading' && <p className="note">Loading jobs…</p>}
          {jobsObservation === 'unavailable' && (
            <p className="fail" role="status">
              Job updates unavailable. No job history has been observed yet.
            </p>
          )}
          {jobsObservation === 'stale' && (
            <p className="fail" role="status">
              Job updates unavailable. Showing last-known jobs.
            </p>
          )}
          {jobsObservation === 'current' && jobList.length === 0 && (
            <p className="note">No jobs yet.</p>
          )}
          {jobList.length > 0 && (
            <ul className="jobs" aria-label="Recent jobs">
              {jobList.map((job) => (
                <li key={job.id}>
                  <div className="job-identity">
                    <code title={job.id}>{job.id.slice(0, 8)}</code>
                    {jobReason(job.reason) && (
                      <span className="job-detail">{jobReason(job.reason)}</span>
                    )}
                    {Number.isFinite(job.attempts) && job.attempts > 1 && (
                      <span className="job-detail">Attempt {job.attempts}</span>
                    )}
                  </div>
                  <span className={`status ${job.status || 'unknown'}`}>
                    {jobLabel(job.status)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Updated at={jobs.updatedAt} now={now} />
          {jobs.data?.next_offset != null && (
            <p className="note">Showing the latest 50 retained jobs.</p>
          )}
        </div>
      </section>
    </main>
  );
}
