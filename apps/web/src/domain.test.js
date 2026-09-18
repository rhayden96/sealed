import test from 'node:test';
import assert from 'node:assert/strict';
import {
  autoEligible,
  liveState,
  number,
  orderedEvents,
  resourceState,
  routeFromSearch,
  title,
  reason,
} from './domain.js';

test('unknown experiment and reason strings cannot resolve inherited object properties', () => {
  for (const value of ['__proto__', 'constructor', 'toString']) {
    assert.equal(typeof title(value), 'string');
    assert.equal(typeof reason(value), 'string');
  }
  assert.equal(title('__proto__'), '__proto__');
});

test('missing and failed observations never become healthy or zero', () => {
  assert.equal(liveState({ data: null, loading: true }), 'loading');
  assert.equal(liveState({ data: null, error: 'offline' }), 'unavailable');
  assert.equal(number(null), '—');
  assert.equal(number(undefined), '—');
  assert.equal(number(0), '0');
});
test('last known healthy data is stale after failure or age', () => {
  const resource = {
    data: { status: 'ok', api: 'ok', redis: 'ok', worker: 'ok' },
    lastSuccess: 1000,
  };
  assert.equal(liveState(resource, 2000), 'healthy');
  assert.equal(liveState({ ...resource, error: 'offline' }, 2000), 'stale');
  assert.equal(resourceState(resource, 9000), 'stale');
  assert.equal(liveState({ data: { status: 'ok' }, lastSuccess: 1000 }, 2000), 'unknown');
});
test('auto-unseal label follows loaded policy and composer environment', () => {
  const experiment = { id: 'handler_latency', default_duration_s: 5 };
  const policy = {
    auto_unseal: {
      enabled: true,
      environment: 'demo',
      catalog_ids: ['handler_latency'],
      max_duration_s: 5,
    },
  };
  assert.equal(autoEligible(experiment, policy), true);
  assert.equal(autoEligible(experiment, policy, 'prod'), false);
  assert.equal(autoEligible({ ...experiment, default_duration_s: 6 }, policy), false);
  assert.equal(autoEligible(experiment, null), false);
});
test('history filters by exact run and authoritative event sequence', () => {
  const events = [
    { id: 'e2', run_id: 'selected', seq: 2, ts: 5 },
    { id: 'e1', run_id: 'selected', seq: 1, ts: 6 },
    { id: 'other', run_id: 'another', seq: 3, ts: 7 },
  ];
  assert.deepEqual(
    orderedEvents(events, 'selected').map((event) => event.id),
    ['e1', 'e2'],
  );
});
test('deep links recover view, selected run and game day', () => {
  assert.deepEqual(routeFromSearch('?view=tape&run=d-123&day=g-1'), {
    view: 'tape',
    run: 'd-123',
    day: 'g-1',
  });
  assert.equal(routeFromSearch('?view=invalid').view, 'ops');
});
