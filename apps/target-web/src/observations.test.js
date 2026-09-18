import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ageLabel,
  healthState,
  observationState,
  serviceLabel,
  jobLabel,
  jobReason,
} from './observations.js';

test('unknown and inherited status names always render safe labels', () => {
  for (const value of [
    '__proto__',
    'constructor',
    'toString',
    'unexpected',
    { toString: 'invalid' },
  ]) {
    assert.equal(serviceLabel(value), 'Unknown');
    assert.equal(jobLabel(value), 'Unknown');
    assert.equal(jobReason(value), '');
  }
});

test('missing health stays loading or unavailable, never healthy', () => {
  assert.equal(healthState({ data: null, updatedAt: null, error: null }, 10000), 'loading');
  assert.equal(
    healthState({ data: null, updatedAt: null, error: new Error('offline') }, 10000),
    'unavailable',
  );
  assert.equal(serviceLabel(undefined), 'Unknown');
});

test('fresh healthy observations become visibly stale after failure or age', () => {
  const known = {
    data: { status: 'ok', api: 'ok', redis: 'ok', worker: 'ok' },
    updatedAt: 10000,
    error: null,
  };
  assert.equal(healthState(known, 12000), 'healthy');
  assert.equal(healthState(known, 18000), 'stale');
  assert.equal(healthState({ ...known, error: new Error('offline') }, 12000), 'stale');
  assert.equal(
    known.data.worker,
    'ok',
    'last known observation remains available for a stale label',
  );
});

test('unknown worker cannot become healthy from an aggregate label', () => {
  const partial = {
    data: { status: 'ok', api: 'ok', redis: 'ok', worker: 'unknown' },
    updatedAt: 10000,
    error: null,
  };
  assert.equal(healthState(partial, 11000), 'unknown');
  assert.equal(
    healthState(
      {
        ...partial,
        data: { ...partial.data, status: 'degraded', redis: 'down' },
      },
      11000,
    ),
    'degraded',
  );
});

test('retained empty job history is stale after failure, not a current empty result', () => {
  assert.equal(
    observationState({ data: { jobs: [] }, updatedAt: 10000, error: new Error('offline') }, 11000),
    'stale',
  );
  assert.equal(ageLabel(10000, 12500), 'Updated 2s ago');
  assert.equal(ageLabel(null, 12500), 'No successful observation yet');
});
