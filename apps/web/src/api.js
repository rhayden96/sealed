import { ApiError, request } from '../../../packages/web/client.js';
export { ApiError, formatDetail } from '../../../packages/web/client.js';

const id = encodeURIComponent;
const req = async (path, options) => (await request(path, options)).body;
const post = (path, body, options) => req(path, { ...options, method: 'POST', body });

// The transport accepts arbitrary JSON. This facade validates the containers
// and values the console renders, preserving last-known data on invalid 200s.
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value) => typeof value === 'string';
const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const nullable = (check) => (value) => value === null || check(value);
const array = (check) => (value) => Array.isArray(value) && value.every(check);
const optional = (check, value) => value === undefined || check(value);
const identified = (value) => object(value) && text(value.id) && value.id.length > 0;
const hypothesis = (value) =>
  object(value) &&
  object(value.slo) &&
  finite(value.slo.p95_ms) &&
  finite(value.slo.error_rate) &&
  array(text)(value.must);
const evidence = (value) => {
  if (!object(value)) return false;
  if (value.evaluation === undefined) return true;
  const evaluation = value.evaluation;
  return (
    object(evaluation) &&
    object(evaluation.summary) &&
    Object.values(evaluation.summary).every(
      (summary) =>
        object(summary) &&
        finite(summary.sample_count) &&
        finite(summary.valid_count) &&
        nullable(finite)(summary.p95_ms) &&
        nullable(finite)(summary.error_rate),
    ) &&
    array(
      (check) =>
        object(check) &&
        text(check.id) &&
        typeof check.passed === 'boolean' &&
        optional(nullable(text), check.phase),
    )(evaluation.checks)
  );
};
const run = (value) =>
  identified(value) &&
  ['catalog_id', 'environment', 'target', 'status'].every((key) => text(value[key])) &&
  finite(value.duration_s) &&
  object(value.params) &&
  hypothesis(value.hypothesis) &&
  optional(text, value.source) &&
  optional(nullable(evidence), value.evidence);
const seal = (value) =>
  identified(value) &&
  text(value.draft_id) &&
  text(value.catalog_id) &&
  ['pass', 'fail', 'aborted'].includes(value.verdict) &&
  hypothesis(value.hypothesis) &&
  optional(nullable(evidence), value.evidence);
const day = (value) =>
  identified(value) &&
  text(value.status) &&
  array(
    (step) =>
      object(step) &&
      text(step.draft_id) &&
      text(step.catalog_id) &&
      text(step.status) &&
      finite(step.index),
  )(value.steps);
const event = (value) =>
  identified(value) &&
  text(value.run_id) &&
  text(value.kind) &&
  finite(value.ts) &&
  finite(value.seq) &&
  object(value.details);
const catalog = (value) =>
  object(value) &&
  array(
    (item) =>
      identified(item) &&
      text(item.description) &&
      finite(item.default_duration_s) &&
      array(text)(item.allowed_targets) &&
      item.allowed_targets.length > 0 &&
      object(item.params) &&
      hypothesis(item.hypothesis),
  )(value.experiments);
const policy = (value) =>
  object(value) &&
  array(text)(value.target_allowlist) &&
  array(text)(value.environment_allowlist) &&
  finite(value.max_duration_s) &&
  object(value.auto_unseal) &&
  typeof value.auto_unseal.enabled === 'boolean' &&
  text(value.auto_unseal.environment) &&
  array(text)(value.auto_unseal.catalog_ids) &&
  finite(value.auto_unseal.max_duration_s);
const trace = (value) =>
  object(value) &&
  text(value.planner) &&
  array(
    (line) =>
      object(line) &&
      text(line.tool) &&
      text(line.result_summary) &&
      finite(line.ts) &&
      optional(finite, line.seq),
  )(value.trace);
const proposal = (value) =>
  object(value) &&
  nullable(run)(value.draft) &&
  text(value.outcome) &&
  text(value.explanation) &&
  ['requested_provider', 'actual_provider', 'planner', 'fallback_reason'].every((key) =>
    optional(nullable(text), value[key]),
  );
const health = (value) =>
  object(value) && ['status', 'api', 'redis', 'worker'].every((key) => text(value[key]));
const metrics = (value) =>
  object(value) &&
  finite(value.sample_count) &&
  finite(value.inflight) &&
  nullable(finite)(value.p95_ms) &&
  nullable(finite)(value.error_rate) &&
  optional(
    (item) =>
      object(item) &&
      typeof item.available === 'boolean' &&
      (!item.available || ['done', 'dropped', 'failed'].every((key) => finite(item[key]))),
    value.job_outcomes,
  );

async function checked(promise, accepts, label) {
  const body = await promise;
  if (!accepts(body))
    throw new ApiError(
      `The service returned an invalid ${label} response. Refresh to inspect current state.`,
      { status: 200, code: 'invalid_response' },
    );
  return body;
}
const query = (values) => {
  const search = new URLSearchParams(
    Object.entries(values).filter(([, value]) => value != null && value !== ''),
  );
  return search.size ? `?${search}` : '';
};

export const api = {
  catalog: (options) => checked(req('/api/catalog', options), catalog, 'catalog'),
  policy: (options) => checked(req('/api/policy', options), policy, 'policy'),
  drafts: (filters = {}, options) =>
    checked(req(`/api/drafts${query(filters)}`, options), array(run), 'run list'),
  draft: (runId, options) => checked(req(`/api/drafts/${id(runId)}`, options), run, 'run'),
  activeRun: (options) => checked(req('/api/active-run', options), nullable(run), 'active run'),
  events: (runId, options) =>
    checked(req(`/api/drafts/${id(runId)}/events`, options), array(event), 'run events'),
  runSeal: (runId, options) =>
    checked(req(`/api/drafts/${id(runId)}/seal`, options), nullable(seal), 'run seal'),
  evaluate: (runId, options) =>
    checked(
      req(`/api/drafts/${id(runId)}/evaluate`, options),
      (value) => object(value) && typeof value.allowed === 'boolean' && array(text)(value.reasons),
      'policy evaluation',
    ),
  createDraft: (body, options) =>
    checked(post('/api/drafts', body, { timeoutMs: 15000, ...options }), run, 'created run'),
  approve: (runId, options) =>
    checked(post(`/api/drafts/${id(runId)}/approve`, undefined, options), run, 'approved run'),
  unseal: (runId, options) =>
    checked(
      post(`/api/drafts/${id(runId)}/unseal`, undefined, {
        timeoutMs: 15000,
        ...options,
      }),
      run,
      'unseal',
    ),
  reseal: (runId, options) =>
    checked(
      post(`/api/drafts/${id(runId)}/reseal`, undefined, {
        timeoutMs: 5000,
        ...options,
      }),
      (value) => object(value) && run(value.draft) && nullable(seal)(value.seal),
      'reseal',
    ),
  seals: (options) => checked(req('/api/seals', options), array(seal), 'seal list'),
  propose: ({ idempotencyKey, ...options } = {}) =>
    checked(
      post('/api/agent/propose', undefined, {
        timeoutMs: 20000,
        ...options,
        headers: {
          ...(options.headers || {}),
          ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
        },
      }),
      proposal,
      'planner',
    ),
  cancelProposal: (proposalId, options) =>
    post(`/api/agent/proposals/${id(proposalId)}/cancel`, undefined, options),
  agentTrace: (options) => checked(req('/api/agent/trace', options), trace, 'planner diagnostics'),
  fixtures: (options) =>
    checked(
      req('/replay/seals/index.json', options),
      (value) => object(value) && array(seal)(value.seals),
      'fixture index',
    ),
  fixture: (sealId, options) =>
    checked(req(`/replay/seals/${id(sealId)}.json`, options), seal, 'fixture'),
  controlHealth: (options) =>
    checked(
      req('/api/health', options),
      (value) => object(value) && text(value.status),
      'control health',
    ),
  gameDays: (options) => checked(req('/api/game-days', options), array(day), 'game-day list'),
  createGameDay: (steps, options) =>
    checked(post('/api/game-days', { steps }, options), day, 'created game day'),
  gameDay: (dayId, options) =>
    checked(req(`/api/game-days/${id(dayId)}`, options), day, 'game day'),
  abortGameDay: (dayId, options) => post(`/api/game-days/${id(dayId)}/abort`, undefined, options),
  endGameDay: (dayId, options) =>
    checked(post(`/api/game-days/${id(dayId)}/end`, undefined, options), day, 'ended game day'),
  health: (options) => checked(req('/target/health', options), health, 'target health'),
  metrics: (options) => checked(req('/target/metrics', options), metrics, 'metrics'),
};
