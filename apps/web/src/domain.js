export const ACTIVE = new Set([
  'reserved',
  'injecting',
  'unsealed',
  'cleanup_pending',
  'recovering',
]);
export const TERMINAL = new Set(['completed', 'resealed', 'cancelled']);
export const TITLES = {
  handler_latency: 'Handler latency',
  redis_down: 'Redis down',
  worker_drop: 'Worker drop',
};
export const title = (id) =>
  typeof id === 'string' ? (Object.hasOwn(TITLES, id) ? TITLES[id] : id) : 'Unknown experiment';
export const number = (value, digits = 0) =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
export const time = (value) =>
  typeof value === 'number' && Number.isFinite(value)
    ? new Date(value * 1000).toLocaleString([], {
        dateStyle: 'short',
        timeStyle: 'medium',
      })
    : 'Not observed';

export function resourceState(resource, now = Date.now(), maxAge = 7000) {
  if (!resource.lastSuccess)
    return resource.error ? 'unavailable' : resource.loading ? 'loading' : 'unknown';
  if (resource.error || (maxAge && now - resource.lastSuccess > maxAge)) return 'stale';
  return 'available';
}

export function liveState(resource, now) {
  const state = resourceState(resource, now);
  if (state !== 'available') return state;
  if (resource.data?.status === 'ok')
    return ['api', 'redis', 'worker'].every((name) => resource.data[name] === 'ok')
      ? 'healthy'
      : 'unknown';
  return resource.data?.status === 'degraded' ? 'degraded' : 'unknown';
}

const REASONS = {
  environment_denied: 'Prod is forbidden. Only demo may unseal.',
  environment_not_allowed: 'Only the demo environment may unseal.',
  duration_exceeded: 'Duration exceeds the policy limit of 20 seconds.',
  max_concurrent_unsealed: 'Another run owns admission until cleanup and recovery finish.',
  not_approved: 'Human approval is required before the clerk can unseal.',
  step_skipped: 'Finish the current game-day step before starting this one.',
  game_day_ended: 'This game day has ended. Create a new draft to run again.',
  target_inject_failed: 'Target delivery failed. Inspect the saved run before retrying.',
};
export function reason(value) {
  return typeof value === 'string' && Object.hasOwn(REASONS, value)
    ? REASONS[value]
    : String(value || '').replaceAll('_', ' ');
}
export function errorText(error) {
  const detail = error?.detail ?? error?.message ?? error;
  if (Array.isArray(detail?.reasons)) return detail.reasons.map(reason).join(' ');
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join('; ');
  if (detail && typeof detail === 'object') return reason(detail.reason || JSON.stringify(detail));
  return reason(detail || 'Request failed');
}
export function autoEligible(experiment, policy, environment = 'demo') {
  const auto = policy?.auto_unseal;
  return Boolean(
    experiment &&
    auto?.enabled &&
    environment === auto.environment &&
    auto.catalog_ids?.includes(experiment.id) &&
    experiment.default_duration_s <= auto.max_duration_s,
  );
}
export function routeFromSearch(search) {
  const params = new URLSearchParams(search);
  const view = params.get('view');
  return {
    view: ['ops', 'gameday', 'tape', 'fixtures'].includes(view) ? view : 'ops',
    run: params.get('run') || '',
    day: params.get('day') || '',
  };
}
export function orderedEvents(events, runId) {
  return (events || [])
    .filter((event) => event.run_id === runId)
    .slice()
    .sort((a, b) => a.seq - b.seq || a.ts - b.ts || a.id.localeCompare(b.id));
}
