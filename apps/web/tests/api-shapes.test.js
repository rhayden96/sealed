import test from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError } from '../src/api.js';

const hypothesis = {
  slo: { p95_ms: 500, error_rate: 0.01 },
  must: ['latency_recovers_after_reseal'],
};
const run = {
  id: 'd-1',
  catalog_id: 'handler_latency',
  environment: 'demo',
  target: 'api',
  status: 'draft',
  duration_s: 5,
  params: { delay_ms: 300 },
  hypothesis,
};
const seal = {
  id: 's-1',
  draft_id: run.id,
  catalog_id: run.catalog_id,
  verdict: 'pass',
  hypothesis,
};
const policy = {
  target_allowlist: ['api', 'redis', 'worker'],
  environment_allowlist: ['demo'],
  max_duration_s: 20,
  auto_unseal: {
    enabled: true,
    environment: 'demo',
    catalog_ids: ['handler_latency'],
    max_duration_s: 5,
  },
};

const routes = [
  [
    'catalog',
    () => api.catalog(),
    {
      experiments: [
        {
          id: 'handler_latency',
          description: 'Delay handler',
          default_duration_s: 5,
          allowed_targets: ['api'],
          params: run.params,
          hypothesis,
        },
      ],
    },
  ],
  ['policy', () => api.policy(), policy],
  ['drafts', () => api.drafts(), [run]],
  ['draft', () => api.draft('d-1'), run],
  [
    'events',
    () => api.events('d-1'),
    [{ id: 'e-1', run_id: 'd-1', kind: 'created', ts: 1, seq: 1, details: {} }],
  ],
  [
    'game days',
    () => api.gameDays(),
    [
      {
        id: 'g-1',
        status: 'open',
        steps: [{ draft_id: 'd-1', catalog_id: run.catalog_id, status: 'draft', index: 0 }],
      },
    ],
  ],
  [
    'agent trace',
    () => api.agentTrace(),
    { planner: 'stub', trace: [{ tool: 'get_run', result_summary: 'draft d-1', ts: 1, seq: 1 }] },
  ],
  ['fixture index', () => api.fixtures(), { seals: [seal] }],
  ['fixture detail', () => api.fixture('s-1'), seal],
  ['target health', () => api.health(), { status: 'ok', api: 'ok', redis: 'ok', worker: 'ok' }],
  [
    'metrics',
    () => api.metrics(),
    { sample_count: 0, inflight: 0, p95_ms: null, error_rate: null },
  ],
];

for (const [name, call, valid] of routes) {
  test(`${name} rejects a successful HTML page/null/wrong container and accepts its documented shape`, async (t) => {
    let body;
    t.mock.method(globalThis, 'fetch', async () => new Response(body, { status: 200 }));
    for (body of ['<!doctype html><title>Proxy login</title>', 'null', '42', '"unexpected text"']) {
      await assert.rejects(
        call(),
        (error) =>
          error instanceof ApiError && error.code === 'invalid_response' && error.status === 200,
      );
    }
    body = JSON.stringify(Array.isArray(valid) ? {} : []);
    await assert.rejects(call(), (error) => error.code === 'invalid_response');
    body = JSON.stringify(valid);
    assert.deepEqual(await call(), valid);
  });
}

test('nullable active run/seal and genuinely empty collections preserve their meaning', async (t) => {
  let body = 'null';
  t.mock.method(globalThis, 'fetch', async () => new Response(body, { status: 200 }));
  assert.equal(await api.activeRun(), null);
  assert.equal(await api.runSeal('d-1'), null);
  body = '[]';
  for (const call of [
    () => api.drafts(),
    () => api.events('d-1'),
    () => api.gameDays(),
    () => api.seals(),
  ])
    assert.deepEqual(await call(), []);
  await assert.rejects(api.activeRun(), (error) => error.code === 'invalid_response');
  await assert.rejects(api.runSeal('d-1'), (error) => error.code === 'invalid_response');
});

test('nested malformed render containers fail instead of becoming empty or healthy', async (t) => {
  let body;
  t.mock.method(
    globalThis,
    'fetch',
    async () => new Response(JSON.stringify(body), { status: 200 }),
  );
  for (const [call, invalid] of [
    [() => api.catalog(), { experiments: {} }],
    [() => api.catalog(), { experiments: [null] }],
    [() => api.policy(), {}],
    [() => api.drafts(), [null]],
    [() => api.agentTrace(), { planner: 'stub', trace: {} }],
    [() => api.gameDays(), [{ id: 'g-1', status: 'open', steps: null }]],
    [() => api.fixtures(), { seals: {} }],
    [() => api.health(), { status: 'ok' }],
    [() => api.draft('d-1'), { ...run, evidence: { evaluation: { summary: {}, checks: {} } } }],
  ]) {
    body = invalid;
    await assert.rejects(call(), (error) => error.code === 'invalid_response');
  }
});

test('no-proposal and cancellation results remain compatible with the planner UI', async (t) => {
  let body = {
    draft: null,
    explanation: 'No proposal.',
    requested_provider: 'stub',
    actual_provider: 'stub',
    planner: 'stub',
    outcome: 'no_proposal',
    trace: [],
  };
  t.mock.method(
    globalThis,
    'fetch',
    async () => new Response(JSON.stringify(body), { status: 200 }),
  );
  assert.deepEqual(await api.propose(), body);
  body = { draft: null, explanation: 'Planning cancelled.', outcome: 'cancelled' };
  assert.deepEqual(await api.propose(), body);
});

test('HTTP failures retain transport status instead of being replaced by shape errors', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('null', { status: 503 }));
  await assert.rejects(
    api.catalog(),
    (error) => error instanceof ApiError && error.status === 503 && error.code === 'http_error',
  );
});
