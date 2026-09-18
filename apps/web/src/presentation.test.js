import test from 'node:test';
import assert from 'node:assert/strict';
import { clampDrawerHeight, drawerBounds, measuredTrends, traceProgress } from './presentation.js';

test('restored drawer size rejects invalid storage and clamps to a short viewport', () => {
  assert.equal(clampDrawerHeight(null, 900), 280);
  assert.equal(clampDrawerHeight('broken', 900), 280);
  assert.equal(clampDrawerHeight('9000', 420), 252);
  assert.equal(clampDrawerHeight('-100', 900), 200);
  assert.deepEqual(drawerBounds(180), { min: 120, max: 120 });
});

test('trace polling counts only new entries and retains its watermark across bounded snapshots', () => {
  const initial = [{ seq: 4 }, { seq: 5 }];
  assert.deepEqual(traceProgress(initial, null), { lastSeq: 5, added: 0 });
  assert.deepEqual(traceProgress(initial, 5), { lastSeq: 5, added: 0 });
  assert.deepEqual(traceProgress([{ seq: 5 }, { seq: 6 }, { seq: 7 }], 5), {
    lastSeq: 7,
    added: 2,
  });
  assert.deepEqual(traceProgress([], 7), { lastSeq: 7, added: 0 });
  assert.deepEqual(traceProgress([{ seq: 1 }], 7), { lastSeq: 7, added: 0 });
});

test('phase charts require real observations and never substitute zero for absent measurements', () => {
  const summary = {
    baseline: { valid_count: 3, p95_ms: 12, error_rate: 0 },
    during: { valid_count: 4, p95_ms: 310, error_rate: 0 },
  };
  assert.deepEqual(measuredTrends({ evaluation: { summary } }), []);
  assert.deepEqual(measuredTrends({ baseline: [{ real: true }], evaluation: { summary: {} } }), []);
  assert.deepEqual(
    measuredTrends({
      baseline: [{ real: false }],
      during: [{ real: false }],
      evaluation: { summary },
    }),
    [],
  );
  const trends = measuredTrends({
    baseline: [{ real: true }],
    during: [{ real: true }],
    evaluation: { summary },
  });
  assert.equal(trends.length, 2);
  assert.equal(trends[0].points[2].value, null);
  assert.equal(trends[1].points[0].value, 0);
  assert.equal(trends[0].max, 310);
});
