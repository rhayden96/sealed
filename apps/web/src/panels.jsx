import { useCallback, useState } from 'react';
import { api } from './api.js';
import { PhaseTrends } from './PhaseTrends.jsx';
import { useResource } from './hooks.js';
import {
  ACTIVE,
  autoEligible,
  liveState,
  number,
  orderedEvents,
  reason,
  resourceState,
  time,
  title,
} from './domain.js';
import { FAULT_ICONS, IconApi, IconDatabase, IconQueue } from './icons.jsx';

export function ResourceNote({ resource, now, label = 'Data' }) {
  const state = resourceState(resource, now);
  return (
    <p className={`resource-note ${state}`}>
      {label}: {state}.{' '}
      {resource.lastSuccess ? (
        <>
          Last successful observation{' '}
          <time>{new Date(resource.lastSuccess).toLocaleTimeString()}</time>.
        </>
      ) : (
        'No successful observation yet.'
      )}
      {resource.error ? ` ${resource.error}` : ''}
    </p>
  );
}

export function RunIdentity({ run }) {
  return (
    <div className="run-identity">
      <strong>{title(run.catalog_id)}</strong>
      <code>{run.id}</code>
      <p>
        {run.catalog_id} · {run.environment} · {run.target} · {run.duration_s}s ·{' '}
        {run.source || 'manual'} · <b>{run.status}</b>
      </p>
      <p>
        Effective parameters: <code>{JSON.stringify(run.params || {})}</code>
      </p>
    </div>
  );
}

export function ActiveRunBanner({ resource, now, pending, onAbort, onInspect }) {
  const run = resource.data;
  if (!run)
    return resource.error ? (
      <div className="banner" role="status">
        Active run status unavailable. {resource.error} Previously selected runs remain inspectable
        below.
      </div>
    ) : null;
  const remaining =
    typeof run.unsealed_until === 'number'
      ? Math.max(0, Math.ceil(run.unsealed_until - now / 1000))
      : null;
  const recovering = ['cleanup_pending', 'recovering'].includes(run.status);
  return (
    <section className={`active-run ${recovering ? 'cleaning' : ''}`} aria-label="Active run">
      <div>
        <p className="eyebrow">
          {recovering ? 'Stopping & verifying recovery' : 'Active run · admission owned'}
        </p>
        <RunIdentity run={run} />
        <p>
          {remaining != null && run.status === 'unsealed' ? `${remaining}s remaining. ` : ''}
          {run.cleanup_confirmed
            ? 'Target cleanup confirmed. Recovery observations pending.'
            : recovering
              ? 'Cleanup requested; recovery is not yet confirmed.'
              : 'Only this run may inject.'}
        </p>
        <ResourceNote resource={resource} now={now} label="Run ownership" />
      </div>
      <div className="action-row">
        <button className="ghost" onClick={() => onInspect(run.id)}>
          Inspect active run
        </button>
        <button className="primary abort" disabled={pending} onClick={() => onAbort(run.id)}>
          {pending ? 'Requesting reseal…' : 'Abort / reseal active run'}
        </button>
      </div>
    </section>
  );
}

export function LivePanel({ health, metrics, now, activeRun }) {
  const state = liveState(health, now);
  const healthStale = state === 'stale';
  const metricsStale = resourceState(metrics, now) === 'stale';
  return (
    <section className="panel live-panel" aria-label="Live target">
      <h2>Live target</h2>
      <p className={`status-word ${state}`} role="status">
        {state === 'healthy' ? 'Services healthy' : `Services ${state}`}
      </p>
      {activeRun && (
        <p className="eligibility">
          Reported fault: {title(activeRun.catalog_id)} · {activeRun.status}. Service health alone
          does not establish the experiment verdict. Inspect its measured evidence.
        </p>
      )}
      <div className="tiles">
        {[
          ['api', IconApi],
          ['redis', IconDatabase],
          ['worker', IconQueue],
        ].map(([name, Icon]) => (
          <article
            className={`tile ${healthStale ? 'stale' : health.data?.[name] || 'unknown'}`}
            key={name}
          >
            <header>
              <Icon />
              {name}
            </header>
            <strong>{health.data?.[name] || 'unknown'}</strong>
            {healthStale && <small>Last known</small>}
          </article>
        ))}
      </div>
      <ResourceNote resource={health} now={now} label="Target health" />
      <p className="stats">
        <span>
          p95 <b>{number(metrics.data?.p95_ms)}</b> ms
        </span>
        <span>
          HTTP errors{' '}
          <b>
            {metrics.data?.error_rate == null
              ? '—'
              : number(metrics.data.error_rate * 100, 1) + '%'}
          </b>
        </span>
        <span>
          inflight <b>{metrics.data?.inflight ?? '—'}</b>
        </span>
      </p>
      <p className="helper">
        {metricsStale ? 'Last known metrics. ' : ''}
        {metrics.data?.sample_count ?? 'Unknown number of'} business samples in the last{' '}
        {metrics.data?.window_s ?? 60}s. Management probes are excluded.
      </p>
      <ResourceNote resource={metrics} now={now} label="Metrics" />
      {metrics.data?.job_outcomes && (
        <p className="helper">
          Worker outcomes:{' '}
          {metrics.data.job_outcomes.available
            ? `${metrics.data.job_outcomes.done ?? 0} done · ${metrics.data.job_outcomes.dropped ?? 0} dropped · ${metrics.data.job_outcomes.failed ?? 0} failed`
            : 'unavailable'}
        </p>
      )}
    </section>
  );
}

export function Composer({
  catalog,
  policy,
  catalogId,
  setCatalogId,
  environment,
  setEnvironment,
  pending,
  onCreate,
  onPropose,
  proposing,
  locked,
}) {
  const experiment = catalog.find((item) => item.id === catalogId);
  const auto = autoEligible(experiment, policy, environment);
  return (
    <section className="panel" aria-label="New experiment">
      <h2>New experiment</h2>
      <p className="helper">
        Choose the next experiment. Existing run actions stay bound to the selected run below.
      </p>
      <div className="catalog-grid">
        {catalog.map((item) => {
          const Icon = Object.hasOwn(FAULT_ICONS, item.id) ? FAULT_ICONS[item.id] : IconApi;
          return (
            <button
              key={item.id}
              type="button"
              className={`fault ${item.id === catalogId ? 'active' : ''}`}
              aria-pressed={item.id === catalogId}
              aria-label={`Compose ${title(item.id)}`}
              onClick={() => setCatalogId(item.id)}
            >
              <Icon />
              <h3>{title(item.id)}</h3>
              <code>{item.id}</code>
              <p>{item.description}</p>
              <small>
                {item.default_duration_s}s · {item.allowed_targets.join(', ')}
              </small>
            </button>
          );
        })}
      </div>
      {experiment && (
        <>
          <label className="field">
            Environment
            <select value={environment} onChange={(event) => setEnvironment(event.target.value)}>
              <option value="demo">demo</option>
              <option value="prod">prod (denial example only)</option>
            </select>
          </label>
          <p className="helper">
            Parameters: <code>{JSON.stringify(experiment.params)}</code>
          </p>
          <Hypothesis hypothesis={experiment.hypothesis} />
          <p className={auto ? 'eligibility' : 'helper'}>
            {auto
              ? 'Auto-unseal eligible. This action starts a fault immediately when policy permits.'
              : environment === 'prod'
                ? 'Prod is a policy-denial example. It cannot inject.'
                : 'Creates a draft. Human approval and clerk evaluation are required before injection.'}
          </p>
          {locked && (
            <p className="helper">
              Another run owns admission. A new draft can be saved, but it cannot unseal until
              recovery finishes.
            </p>
          )}
          <div className="action-row">
            <button className="primary" disabled={pending || !policy} onClick={onCreate}>
              {pending ? 'Creating…' : auto ? 'Create & auto-unseal' : 'Create draft'}
            </button>
            <button className="ghost" disabled={proposing} onClick={onPropose}>
              {proposing ? 'Planning…' : 'Propose draft'}
            </button>
          </div>
        </>
      )}
      {!catalog.length && (
        <p className="helper">Catalog unavailable. Fixture replay remains available.</p>
      )}
    </section>
  );
}

export function Hypothesis({ hypothesis }) {
  if (!hypothesis) return <p className="helper">No hypothesis recorded.</p>;
  return (
    <details className="hypothesis">
      <summary>Hypothesis & required assertions</summary>
      <p>
        p95 ≤ {hypothesis.slo?.p95_ms ?? '—'} ms · HTTP error rate ≤{' '}
        {hypothesis.slo?.error_rate ?? '—'}
      </p>
      <ul>
        {(hypothesis.must || []).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </details>
  );
}

export function SelectedRun({
  run,
  resource,
  now,
  decision,
  pending,
  aborting,
  onApprove,
  onStart,
  onAbort,
  onEvaluate,
}) {
  if (!run)
    return (
      <section className="panel" aria-label="Selected run">
        <h2>Selected run</h2>
        <p className="helper">
          {resource.loading
            ? 'Loading selected run…'
            : 'Choose a run from history or create a new draft.'}
        </p>
        {resource.error && <p className="error">{resource.error}</p>}
      </section>
    );
  const startable = ['draft', 'approved'].includes(run.status);
  return (
    <section className="panel selected-run" aria-label="Selected run">
      <h2>Selected run</h2>
      <RunIdentity run={run} />
      <ResourceNote resource={resource} now={now} label="Run state" />
      <Hypothesis hypothesis={run.hypothesis} />
      {run.source === 'agent' && (
        <p className="helper">Planner proposal only. Creating this proposal did not inject.</p>
      )}
      <div className="policy-details">
        <b>{decision?.evaluatedAt ? 'Policy evaluation' : 'Recorded clerk decision'}</b>
        {decision ? (
          <>
            <p>
              {decision.allowed
                ? 'Policy allowed unseal at this evaluation.'
                : 'Policy denied unseal at this evaluation.'}{' '}
              {decision.evaluatedAt
                ? `Evaluated ${new Date(decision.evaluatedAt).toLocaleTimeString()}.`
                : 'This recorded result may change as approval and run ownership change.'}
            </p>
            {decision.reasons?.length > 0 && (
              <ul>
                {decision.reasons.map((item) => (
                  <li key={item}>
                    {reason(item)} <code>{item}</code>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p>Evaluate policy before starting to inspect current conditions.</p>
        )}
      </div>
      <div className="action-row">
        {startable && (
          <>
            <button className="primary" disabled={pending} onClick={() => onStart(run.id)}>
              {pending
                ? 'Saving / evaluating…'
                : run.approved
                  ? 'Unseal approved draft'
                  : 'Approve & unseal'}
            </button>
            {!run.approved && (
              <button className="ghost" disabled={pending} onClick={() => onApprove(run.id)}>
                Approve only
              </button>
            )}
            <button className="ghost" disabled={pending} onClick={() => onEvaluate(run.id)}>
              Evaluate policy
            </button>
          </>
        )}
        {ACTIVE.has(run.status) && (
          <button className="primary abort" disabled={aborting} onClick={() => onAbort(run.id)}>
            {aborting ? 'Requesting reseal…' : 'Abort / reseal selected run'}
          </button>
        )}
      </div>
      {!startable && !ACTIVE.has(run.status) && (
        <p className="helper">
          This run is terminal. Create a new draft to run the experiment again.
        </p>
      )}
      {run.execution_error && <p className="error">Execution: {reason(run.execution_error)}</p>}
      {run.cleanup_error && <p className="error">Cleanup pending: {reason(run.cleanup_error)}</p>}
    </section>
  );
}

export function RunHistory({
  resource,
  selectedId,
  search,
  setSearch,
  status,
  setStatus,
  offset,
  setOffset,
  onSelect,
}) {
  return (
    <section className="panel" aria-label="Run history">
      <h2>Run history</h2>
      <div className="history-filters">
        <label className="field">
          Search runs
          <input
            value={search}
            placeholder="Run ID, fault, or origin"
            onChange={(event) => {
              setSearch(event.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label className="field">
          Run status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All statuses</option>
            {[
              'draft',
              'approved',
              'reserved',
              'injecting',
              'unsealed',
              'cleanup_pending',
              'recovering',
              'completed',
              'resealed',
              'cancelled',
            ].map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
      </div>
      {resource.error && <p className="error">History stale: {resource.error}</p>}
      <div className="run-list">
        {[...(resource.data || [])].reverse().map((run) => (
          <button
            key={run.id}
            className={run.id === selectedId ? 'history-run active' : 'history-run'}
            aria-label={`Inspect run ${run.id}`}
            aria-pressed={run.id === selectedId}
            onClick={() => onSelect(run.id)}
          >
            <span>
              <b>{title(run.catalog_id)}</b> · {run.source || 'manual'}
            </span>
            <span>{run.status}</span>
            <code>{run.id}</code>
          </button>
        ))}
      </div>
      {!resource.data?.length && (
        <p className="helper">{resource.loading ? 'Loading runs…' : 'No matching runs.'}</p>
      )}
      <div className="action-row">
        <button
          className="ghost"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 25))}
        >
          Newer runs
        </button>
        <button
          className="ghost"
          disabled={(resource.data?.length || 0) < 25}
          onClick={() => setOffset(offset + 25)}
        >
          Older runs
        </button>
      </div>
    </section>
  );
}

export function EvidencePanel({ run, seal, events, eventError, sealError }) {
  const evidence = seal?.evidence || run?.evidence;
  const evaluation = evidence?.evaluation;
  return (
    <section className="panel" aria-label="Run evidence">
      <h2>Run evidence & tape</h2>
      {!run ? (
        <p className="helper">Select a run to inspect its events and seal.</p>
      ) : (
        <>
          <p className="muted">
            {title(run.catalog_id)} · <code>{run.id}</code>
          </p>
          {seal ? (
            <div className="seal-card">
              <div>
                <b className={`verdict ${seal.verdict}`}>{seal.verdict.toUpperCase()}</b>
                <p>{reason(seal.reason || 'No reason recorded')}</p>
                <code>{seal.id}</code>
              </div>
              <time>{time(seal.created_at)}</time>
            </div>
          ) : (
            <p className="helper">
              {sealError ? `Seal unavailable: ${sealError}` : 'No terminal seal for this run yet.'}
            </p>
          )}
          {evaluation ? (
            <>
              <PhaseTrends evidence={evidence} />
              <div className="evidence-summary">
                {Object.entries(evaluation.summary || {}).map(([phase, summary]) => (
                  <article key={phase}>
                    <b>{phase}</b>
                    <p>
                      {summary.valid_count}/{summary.sample_count} valid samples
                    </p>
                    <p>
                      p95 {number(summary.p95_ms)} ms · errors {number(summary.error_rate, 3)}
                    </p>
                    {summary.drop_rate != null && <p>Drop rate {number(summary.drop_rate, 3)}</p>}
                  </article>
                ))}
              </div>
              <div className="table-scroll">
                <table>
                  <caption>Expected versus observed hypothesis checks</caption>
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>Phase</th>
                      <th>Result</th>
                      <th>Expected / observed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluation.checks?.map((check, index) => (
                      <tr key={`${check.id}-${index}`}>
                        <td>{check.id}</td>
                        <td>{check.phase || 'run'}</td>
                        <td className={check.passed ? 'pass' : 'fail'}>
                          {check.passed ? 'PASS' : 'FAIL'}
                        </td>
                        <td>
                          <div>
                            Expected: <code>{JSON.stringify(check.expected)}</code>
                          </div>
                          <div>
                            Observed: <code>{JSON.stringify(check.observed)}</code>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="helper">
              {evidence
                ? 'Measurements are being collected. No passing verdict has been established.'
                : 'No measured evidence recorded.'}
            </p>
          )}
          {evidence && (
            <details>
              <summary>Raw observations & timestamps</summary>
              <pre>{JSON.stringify(evidence, null, 2)}</pre>
            </details>
          )}
          <h3>Authoritative run events</h3>
          <p className="helper">
            Actual server timestamps, shown in your local timezone (
            {Intl.DateTimeFormat().resolvedOptions().timeZone}). Events are ordered by server
            sequence.
          </p>
          {eventError && <p className="error">Events stale: {eventError}</p>}
          <ol className="timeline">
            {orderedEvents(events, run.id).map((event) => (
              <li key={event.id}>
                <time>{time(event.ts)}</time>
                <b>{reason(event.kind)}</b>
                {Object.keys(event.details || {}).length > 0 && (
                  <details>
                    <summary>Event details</summary>
                    <pre>{JSON.stringify(event.details, null, 2)}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

export function FixturesPanel({ resource }) {
  const [fixtureId, setFixtureId] = useState('');
  const load = useCallback((options) => api.fixture(fixtureId, options), [fixtureId]);
  const detail = useResource(load, {
    enabled: Boolean(fixtureId),
    interval: 0,
  });
  const fixture = detail.data?.id === fixtureId ? detail.data : null;
  return (
    <section className="panel" aria-label="Fixture replay">
      <h2>Offline fixture replay</h2>
      <p className="helper">
        Historical / synthetic examples bundled with the app. Opening a fixture makes no mutations
        or injection requests. Live services and a planner provider are not required.
      </p>
      {resource.error && <p className="error">{resource.error}</p>}
      <div className="run-list">
        {resource.data?.seals?.map((item) => (
          <button
            key={item.id}
            className="history-run"
            aria-label={`Replay fixture ${item.id}`}
            onClick={() => setFixtureId(item.id)}
          >
            <b>{title(item.catalog_id)}</b>
            <span className={`verdict ${item.verdict}`}>{item.verdict}</span>
            <code>{item.id}</code>
          </button>
        ))}
      </div>
      <button className="ghost" onClick={resource.refresh}>
        Reload fixture index
      </button>
      {fixtureId && (
        <section className="fixture-detail" aria-label="Fixture details">
          <h3>{fixture ? title(fixture.catalog_id) : 'Loading fixture…'}</h3>
          {detail.error && <p className="error">{detail.error}</p>}
          {fixture && (
            <>
              <p>
                <code>{fixture.id}</code> · {fixture.target} · {fixture.duration_s}s · recorded
                verdict <b className={`verdict ${fixture.verdict}`}>{fixture.verdict}</b>
              </p>
              <p>
                {fixture.reason
                  ? reason(fixture.reason)
                  : 'No verdict reason recorded in this legacy fixture.'}
              </p>
              <Hypothesis hypothesis={fixture.hypothesis} />
              {!fixture.evidence && (
                <p className="eligibility">
                  Legacy synthetic fixture: no measured evidence is included. Its recorded verdict
                  is not proof of a live run.
                </p>
              )}
              <details open>
                <summary>Exact fixture contents</summary>
                <pre>{JSON.stringify(fixture, null, 2)}</pre>
              </details>
            </>
          )}
        </section>
      )}
    </section>
  );
}
