import test from 'node:test';
import assert from 'node:assert/strict';
import { api } from './api.js';
import { healthState, jobLabel, serviceLabel } from './observations.js';

function respond(t, body) {
  t.mock.method(
    globalThis,
    'fetch',
    async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
}

test('malformed successful health responses reject instead of replacing the last observation', async (t) => {
  const healthy = { status: 'ok', api: 'ok', redis: 'ok', worker: 'ok' };
  for (const body of [null, [], {}, { status: 'ok' }, { ...healthy, worker: {} }]) {
    respond(t, body);
    await assert.rejects(api.health(), /invalid health response/);
    t.mock.restoreAll();
  }
  respond(t, healthy);
  const response = await api.health();
  assert.deepEqual(response.body, healthy);
  assert.equal(healthState({ data: response.body, updatedAt: 1000, error: null }, 1100), 'healthy');
});

test('unknown health strings remain observable but cannot render objects or healthy state', async (t) => {
  respond(t, { status: 'ok', api: 'ok', redis: 'ok', worker: '__proto__' });
  const response = await api.health();
  assert.equal(healthState({ data: response.body, updatedAt: 1000, error: null }, 1100), 'unknown');
  assert.equal(serviceLabel(response.body.worker), 'Unknown');
});

test('malformed successful job records reject, while empty history and unknown statuses stay distinct', async (t) => {
  for (const body of [
    null,
    [],
    {},
    { jobs: null },
    { jobs: [null] },
    { jobs: [{}] },
    { jobs: [{ id: 'job', status: {} }] },
  ]) {
    respond(t, body);
    await assert.rejects(api.jobs(), /invalid jobs response/);
    t.mock.restoreAll();
  }
  respond(t, { jobs: [] });
  assert.deepEqual((await api.jobs()).body.jobs, []);
  t.mock.restoreAll();
  respond(t, { jobs: [{ id: 'job', status: '__proto__' }] });
  assert.equal(jobLabel((await api.jobs()).body.jobs[0].status), 'Unknown');
});
