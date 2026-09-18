import test from 'node:test';
import assert from 'node:assert/strict';
import { request, ApiError, formatDetail } from '../../../packages/web/client.js';
import { api } from '../src/api.js';

for (const [body, status, expected] of [
  ['', 503, 'no error details'],
  ['null', 500, 'no error details'],
  ['<!doctype html><title>Bad gateway</title>', 502, 'unexpected page'],
  ['{"detail":[{"loc":["body","duration_s"],"msg":"must be positive"}]}', 422, 'duration_s'],
  ['{"detail":{"reasons":["max_concurrent_unsealed"]}}', 403, 'max concurrent unsealed'],
  ['{"detail":"run_not_active"}', 409, 'run not active'],
]) {
  test(`HTTP ${status} ${body.slice(0, 16)} returns a readable typed error`, async (t) => {
    t.mock.method(globalThis, 'fetch', async () => new Response(body, { status }));
    await assert.rejects(request('/api/example'), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.match(error.message, new RegExp(expected));
      if (status === 409) assert.equal(error.code, 'conflict');
      return true;
    });
  });
}

test('serializes a mutation once and preserves successful empty/null responses', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    return new Response('null', { status: 200 });
  });
  assert.equal(
    (await request('/api/jobs', { method: 'POST', body: { payload: 'demo' } })).body,
    null,
  );
  assert.deepEqual(JSON.parse(calls[0].options.body), { payload: 'demo' });
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
});

function stalledFetch(url, { signal }) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) reject(signal.reason);
    else signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
}

test('deadline aborts the request and distinguishes timeout', async (t) => {
  t.mock.method(globalThis, 'fetch', stalledFetch);
  await assert.rejects(
    request('/api/slow', { timeoutMs: 10 }),
    (error) => error.code === 'timeout' && error.ms >= 0,
  );
});

test('caller cancellation stays cancellation, not an outage message', async (t) => {
  t.mock.method(globalThis, 'fetch', stalledFetch);
  const controller = new AbortController();
  const pending = request('/api/slow', { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, (error) => error.name === 'AbortError');
});

test('network failure has no false downstream status', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('connection refused');
  });
  await assert.rejects(
    request('/target/health'),
    (error) => error.code === 'unavailable' && error.status === 0 && error.detail === null,
  );
});

test('fixture listing/detail and policy evaluation use GET; run paths are scoped', async (t) => {
  const calls = [];
  const hypothesis = {
    slo: { p95_ms: 500, error_rate: 0.01 },
    must: ['latency_recovers_after_reseal'],
  };
  const fixture = {
    id: 's-fx-latency',
    draft_id: 'd-1',
    catalog_id: 'handler_latency',
    hypothesis,
    verdict: 'pass',
  };
  const draft = {
    id: 'run/with/slashes',
    catalog_id: 'handler_latency',
    environment: 'demo',
    target: 'api',
    status: 'cleanup_pending',
    duration_s: 5,
    params: { delay_ms: 300 },
    hypothesis,
  };
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, method: options.method });
    const body = url.endsWith('index.json')
      ? { seals: [fixture] }
      : url.endsWith('.json')
        ? fixture
        : url.endsWith('/evaluate')
          ? { allowed: false, reasons: ['not_approved'] }
          : { draft, seal: null };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  await api.fixtures();
  await api.fixture('s-fx-latency');
  await api.evaluate('d-1');
  await api.reseal('run/with/slashes');
  assert.deepEqual(calls, [
    { url: '/replay/seals/index.json', method: 'GET' },
    { url: '/replay/seals/s-fx-latency.json', method: 'GET' },
    { url: '/api/drafts/d-1/evaluate', method: 'GET' },
    { url: '/api/drafts/run%2Fwith%2Fslashes/reseal', method: 'POST' },
  ]);
});

test('error formatting handles plain validation arrays and malformed details', () => {
  assert.match(formatDetail([null, 'bad value']), /bad value/);
  assert.match(formatDetail({ reason: 'cleanup_pending' }), /cleanup pending/);
});
