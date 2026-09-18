export const STALE_AFTER_MS = 7000;

export function observationState(resource, now = Date.now()) {
  if (resource.updatedAt == null) return resource.error ? 'unavailable' : 'loading';
  if (resource.error || now - resource.updatedAt > STALE_AFTER_MS) return 'stale';
  return 'current';
}

export function healthState(resource, now = Date.now()) {
  const state = observationState(resource, now);
  if (state !== 'current') return state;
  const values = [resource.data?.api, resource.data?.redis, resource.data?.worker];
  if (resource.data?.status === 'ok' && values.every((value) => value === 'ok')) return 'healthy';
  if (resource.data?.status === 'degraded' || values.some((value) => value === 'down'))
    return 'degraded';
  return 'unknown';
}

export function serviceLabel(value) {
  return mappedLabel({ ok: 'Healthy', down: 'Unhealthy', unknown: 'Unknown' }, value, 'Unknown');
}

function mappedLabel(labels, value, fallback) {
  return typeof value === 'string' && Object.hasOwn(labels, value) ? labels[value] : fallback;
}

export function ageLabel(updatedAt, now = Date.now()) {
  if (updatedAt == null) return 'No successful observation yet';
  const seconds = Math.max(0, Math.floor((now - updatedAt) / 1000));
  return seconds < 1 ? 'Updated just now' : `Updated ${seconds}s ago`;
}

export function jobLabel(status) {
  return mappedLabel(
    {
      queued: 'Queued',
      processing: 'Processing',
      done: 'Done',
      dropped: 'Dropped',
      failed: 'Failed',
    },
    status,
    'Unknown',
  );
}

export function jobReason(reason) {
  return mappedLabel(
    {
      injected_worker_drop: 'Simulated worker drop',
      attempts_exhausted: 'Worker retry budget exhausted',
      worker_interrupted_retry: 'Retrying interrupted work',
    },
    reason,
    '',
  );
}
