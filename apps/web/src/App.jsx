import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import { PlannerDrawer } from './PlannerDrawer.jsx';
import { IconChevron, IconMark, NAV } from './icons.jsx';
import { ACTIVE, errorText, liveState, resourceState, title } from './domain.js';
import { useActions, useResource, useRoute } from './hooks.js';
import {
  ActiveRunBanner,
  Composer,
  EvidencePanel,
  FixturesPanel,
  LivePanel,
  RunHistory,
  SelectedRun,
} from './panels.jsx';

const DEMO_DAY = ['handler_latency', 'redis_down', 'worker_drop'];
const TARGET_URL =
  window.SEALED_CONFIG?.targetAppUrl ||
  import.meta.env.VITE_TARGET_APP_URL ||
  'http://localhost:5174';

export default function App() {
  const [route, navigate] = useRoute();
  const [collapsed, setCollapsed] = useState(false);
  const [catalogId, setCatalogId] = useState('handler_latency');
  const [environment, setEnvironment] = useState('demo');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [decision, setDecision] = useState(null);
  const [proposal, setProposal] = useState(null);
  const [proposalId, setProposalId] = useState('');
  const actions = useActions();
  const catalog = useResource(api.catalog, { interval: 0 });
  const policy = useResource(api.policy, { interval: 0 });
  const fixtures = useResource(api.fixtures, { interval: 0 });
  const control = useResource(api.controlHealth);
  const active = useResource(api.activeRun);
  const health = useResource(api.health);
  const metrics = useResource(api.metrics);
  const days = useResource(api.gameDays, { interval: 4000 });
  const trace = useResource(api.agentTrace, { interval: 3000 });
  const draftLoader = useCallback(
    (options) =>
      api.drafts({ limit: 25, offset, q: search, ...(status ? { status } : {}) }, options),
    [offset, search, status],
  );
  const drafts = useResource(draftLoader);
  const selectedLoader = useCallback((options) => api.draft(route.run, options), [route.run]);
  const selectedResource = useResource(selectedLoader, {
    enabled: Boolean(route.run),
  });
  const eventLoader = useCallback((options) => api.events(route.run, options), [route.run]);
  const events = useResource(eventLoader, { enabled: Boolean(route.run) });
  const sealLoader = useCallback((options) => api.runSeal(route.run, options), [route.run]);
  const sealResource = useResource(sealLoader, { enabled: Boolean(route.run) });
  const dayLoader = useCallback((options) => api.gameDay(route.day, options), [route.day]);
  const dayResource = useResource(dayLoader, { enabled: Boolean(route.day) });
  const selected =
    selectedResource.data?.id === route.run
      ? selectedResource.data
      : drafts.data?.find((run) => run.id === route.run);
  const seal = sealResource.data?.draft_id === route.run ? sealResource.data : null;
  const day = dayResource.data?.id === route.day ? dayResource.data : null;
  const currentStep = day?.steps?.find((step) => step.current);
  const healthState = liveState(health, now);
  const controlState = resourceState(control, now);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setDecision(null);
  }, [route.run]);
  useEffect(() => {
    if (!route.run) {
      const candidate = active.data?.id || drafts.data?.at(-1)?.id;
      if (candidate) navigate({ run: candidate }, true);
    }
  }, [route.run, active.data, drafts.data, navigate]);
  useEffect(() => {
    if (!route.day) {
      const candidate = days.data?.find(
        (item) => item.status === 'open' || item.status === 'ending',
      );
      if (candidate) navigate({ day: candidate.id }, true);
    }
  }, [route.day, days.data, navigate]);

  function refreshMutable() {
    for (const resource of [
      active,
      drafts,
      selectedResource,
      events,
      sealResource,
      days,
      dayResource,
      health,
      metrics,
      trace,
    ])
      resource.refresh();
  }
  function inspect(runId, view = route.view) {
    navigate({ run: runId, view });
  }

  function createDraft() {
    const experiment = catalog.data?.experiments?.find((item) => item.id === catalogId);
    if (!experiment) return;
    return actions.act('create', async () => {
      try {
        const run = await api.createDraft({
          catalog_id: experiment.id,
          environment,
          target: experiment.allowed_targets[0],
          duration_s: experiment.default_duration_s,
        });
        inspect(run.id, 'ops');
        actions.setNotice(`${title(run.catalog_id)} ${run.id}: ${run.status}.`);
      } catch (error) {
        if (error.detail?.draft_id) inspect(error.detail.draft_id, 'ops');
        throw error;
      } finally {
        refreshMutable();
      }
    });
  }
  function approveOnly(id) {
    return actions.act(`run:${id}`, async () => {
      try {
        await api.approve(id);
        actions.setNotice(`Approval saved for ${id}. The clerk has not unsealed this draft.`);
      } finally {
        refreshMutable();
      }
    });
  }
  function startRun(id) {
    return actions.act(`run:${id}`, async () => {
      let approvalSaved = false;
      try {
        const current = await api.draft(id);
        if (!current.approved) await api.approve(id);
        approvalSaved = true;
        const result = await api.unseal(id);
        actions.setNotice(`${title(result.catalog_id)} ${id}: ${result.status}.`);
      } catch (error) {
        throw new Error(
          `${approvalSaved ? `Approval is saved for ${id}. Unseal did not complete. Inspect its current state before retrying. ` : ''}${errorText(error)}`,
        );
      } finally {
        refreshMutable();
      }
    });
  }
  function abortRun(id) {
    return actions.act(`abort:${id}`, async () => {
      try {
        const result = await api.reseal(id);
        actions.setNotice(
          `${id}: ${result.draft?.status === 'resealed' ? 'resealed; target cleanup confirmed. Inspect recovery evidence for its outcome.' : 'reseal requested. Ownership remains until cleanup and recovery checks finish.'}`,
        );
      } finally {
        refreshMutable();
      }
    });
  }
  function evaluateRun(id) {
    return actions.act(`run:${id}`, async () => {
      const result = await api.evaluate(id);
      setDecision({ runId: id, evaluatedAt: Date.now(), ...result });
      actions.setNotice(
        `${id}: policy ${result.allowed ? 'allows unseal' : 'denies unseal'}. No injection requested.`,
      );
    });
  }
  function propose() {
    return actions.act('propose', async () => {
      const id = crypto.randomUUID();
      setProposalId(id);
      try {
        const result = await api.propose({ idempotencyKey: id });
        setProposal(result);
        if (result.draft?.id) inspect(result.draft.id, 'ops');
        actions.setNotice(
          `Planner requested ${result.requested_provider || 'unknown'}, used ${result.actual_provider || result.planner || 'unknown'}; ${result.outcome}. ${result.explanation || ''}`,
        );
      } finally {
        refreshMutable();
      }
    });
  }
  function cancelProposal(id) {
    return actions.act('cancel-proposal', async () => {
      await api.cancelProposal(id);
      actions.setNotice(`Cancellation requested for proposal ${id}.`);
    });
  }
  function createDay() {
    return actions.act('day-create', async () => {
      try {
        const result = await api.createGameDay(DEMO_DAY);
        navigate({ day: result.id, view: 'gameday' });
        actions.setNotice(`Game day ${result.id} saved. All steps are drafts.`);
      } finally {
        refreshMutable();
      }
    });
  }
  function endDay(id) {
    return actions.act(`day-end:${id}`, async () => {
      try {
        await api.endGameDay(id);
        actions.setNotice(
          `Game day ${id} ended. Remaining drafts are cancelled; any active step is resealing.`,
        );
      } finally {
        refreshMutable();
      }
    });
  }
  const historyPanel = (
    <RunHistory
      resource={drafts}
      selectedId={route.run}
      search={search}
      setSearch={setSearch}
      status={status}
      setStatus={setStatus}
      offset={offset}
      setOffset={setOffset}
      onSelect={(id) => inspect(id)}
    />
  );
  const runPanel = (
    <SelectedRun
      run={selected}
      resource={selectedResource}
      now={now}
      decision={decision?.runId === route.run ? decision : selected?.policy_decision}
      pending={actions.pending[`run:${route.run}`]}
      aborting={actions.pending[`abort:${route.run}`]}
      onApprove={approveOnly}
      onStart={startRun}
      onAbort={abortRun}
      onEvaluate={evaluateRun}
    />
  );
  const evidencePanel = (
    <EvidencePanel
      run={selected}
      seal={seal}
      events={events.data}
      eventError={events.error}
      sealError={sealResource.error}
    />
  );

  return (
    <div className={collapsed ? 'shell collapsed' : 'shell'}>
      <aside className="sidebar">
        <button
          className="side-toggle"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          <IconChevron left={!collapsed} />
        </button>
        <nav className="nav" aria-label="Main navigation">
          {NAV.map(({ id, label, Icon }) => (
            <button
              key={id}
              className={route.view === id ? 'active' : ''}
              aria-label={label}
              aria-current={route.view === id ? 'page' : undefined}
              onClick={() => navigate({ view: id })}
              title={label}
            >
              <Icon />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <p className="sidebar-caption">Nothing injects until policy unseals it.</p>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="mark">
            <IconMark />
            Sealed
          </div>
          <span className="env">demo</span>
          <span className={`pill ${healthState}`}>Target {healthState}</span>
          <a className="target-link" href={TARGET_URL} target="_blank" rel="noopener noreferrer">
            Open target app ↗
          </a>
        </header>
        <ActiveRunBanner
          resource={active}
          now={now}
          pending={actions.pending[`abort:${active.data?.id}`]}
          onAbort={abortRun}
          onInspect={(id) => inspect(id, 'ops')}
        />
        {['stale', 'unavailable'].includes(controlState) && (
          <div className="banner" role="status">
            Control {controlState}. Live run information may be stale. Offline fixture replay
            remains available.
          </div>
        )}
        <div className="feedback" aria-live="polite">
          {actions.notice && (
            <p className="helper" role="status">
              {actions.notice}
            </p>
          )}
          {actions.error && (
            <p className="error" role="alert">
              {actions.error}
            </p>
          )}
        </div>
        <div className="content">
          {route.view === 'ops' && (
            <>
              <div className="ops">
                <div className="ops-right">
                  <LivePanel health={health} metrics={metrics} now={now} activeRun={active.data} />
                  {historyPanel}
                </div>
                <div className="ops-right">
                  <Composer
                    catalog={catalog.data?.experiments || []}
                    policy={policy.data}
                    catalogId={catalogId}
                    setCatalogId={setCatalogId}
                    environment={environment}
                    setEnvironment={setEnvironment}
                    pending={actions.pending.create}
                    onCreate={createDraft}
                    onPropose={propose}
                    proposing={actions.pending.propose}
                    locked={Boolean(active.data)}
                  />
                  {(catalog.error || policy.error) && (
                    <div className="error">
                      Configuration unavailable.{' '}
                      <button
                        className="ghost"
                        onClick={() => {
                          catalog.refresh();
                          policy.refresh();
                        }}
                      >
                        Retry configuration
                      </button>
                    </div>
                  )}
                  {runPanel}
                </div>
              </div>
              {evidencePanel}
            </>
          )}
          {route.view === 'tape' && (
            <div className="tape-layout">
              <div>{historyPanel}</div>
              <div className="ops-right">
                {runPanel}
                {evidencePanel}
              </div>
            </div>
          )}
          {route.view === 'fixtures' && <FixturesPanel resource={fixtures} />}
          {route.view === 'gameday' && (
            <section className="panel" aria-label="Game day">
              <h2>Game day</h2>
              <p className="helper">
                A resumable sequence of draft experiments. Aborting a step allows progression;
                ending the day cancels all remaining steps.
              </p>
              <div className="action-row">
                <button
                  className="primary"
                  disabled={actions.pending['day-create']}
                  onClick={createDay}
                >
                  {actions.pending['day-create'] ? 'Creating day…' : 'Create demo day'}
                </button>
              </div>
              <label className="field">
                Saved game day
                <select
                  value={route.day}
                  onChange={(event) => navigate({ day: event.target.value })}
                >
                  <option value="">Select a game day</option>
                  {days.data?.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id} · {item.status}
                    </option>
                  ))}
                </select>
              </label>
              {days.error && <p className="error">Game days stale: {days.error}</p>}
              {day && (
                <>
                  <h3>
                    {day.id} · {day.status}
                  </h3>
                  <div className="gd-cards">
                    {day.steps.map((step) => (
                      <article
                        className={`gd-card ${step.current ? 'current' : ''}`}
                        key={step.draft_id}
                      >
                        <span>Step {step.index + 1}</span>
                        <b>{title(step.catalog_id)}</b>
                        <code>{step.draft_id}</code>
                        <span>{step.status}</span>
                        <button className="ghost" onClick={() => inspect(step.draft_id, 'ops')}>
                          Inspect {step.current ? 'current' : 'saved'} step
                        </button>
                      </article>
                    ))}
                  </div>
                  {currentStep && ACTIVE.has(currentStep.status) && (
                    <button
                      className="primary abort"
                      disabled={actions.pending[`abort:${currentStep.draft_id}`]}
                      onClick={() => abortRun(currentStep.draft_id)}
                    >
                      Abort current step
                    </button>
                  )}
                  {['open', 'ending'].includes(day.status) && (
                    <button
                      className="ghost"
                      disabled={actions.pending[`day-end:${day.id}`]}
                      onClick={() => endDay(day.id)}
                    >
                      End game day & cancel remaining steps
                    </button>
                  )}
                </>
              )}
              {dayResource.error && <p className="error">{dayResource.error}</p>}
            </section>
          )}
        </div>
        <PlannerDrawer
          resource={trace}
          result={proposal}
          pending={actions.pending.propose}
          proposalId={proposalId}
          onPropose={propose}
          onCancel={cancelProposal}
        />
      </main>
    </div>
  );
}
