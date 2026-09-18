export const PHASES = ['baseline', 'during', 'recovery'];

export function drawerBounds(viewportHeight) {
  const max = Math.max(120, Math.min(640, Math.floor(viewportHeight * 0.6)));
  return { min: Math.min(200, max), max };
}

export function clampDrawerHeight(value, viewportHeight) {
  const { min, max } = drawerBounds(viewportHeight);
  const candidate = value == null || value === '' ? 280 : Number(value);
  return Math.round(Math.max(min, Math.min(max, Number.isFinite(candidate) ? candidate : 280)));
}

export function traceProgress(trace, previousSeq) {
  const sequences = trace.map((item) => item.seq).filter(Number.isFinite);
  const latest = sequences.length ? Math.max(...sequences) : previousSeq;
  return {
    lastSeq: previousSeq == null ? latest : Math.max(previousSeq, latest ?? previousSeq),
    added: previousSeq == null ? 0 : sequences.filter((seq) => seq > previousSeq).length,
  };
}

// Summaries come from the server evaluator. Do not turn missing or synthetic
// observations into a chart, or infer an experiment verdict from these bars.
export function measuredTrends(evidence) {
  const summary = evidence?.evaluation?.summary;
  if (!summary) return [];
  return [
    { key: 'p95_ms', label: 'Request p95', unit: 'ms', factor: 1 },
    { key: 'error_rate', label: 'HTTP error rate', unit: '%', factor: 100 },
    { key: 'drop_rate', label: 'Worker drop rate', unit: '%', factor: 100 },
  ]
    .map((metric) => {
      const points = PHASES.map((phase) => {
        const phaseSummary = summary[phase];
        const hasRealSamples =
          Array.isArray(evidence[phase]) && evidence[phase].some((sample) => sample?.real === true);
        const value = phaseSummary?.[metric.key];
        const valid =
          hasRealSamples && phaseSummary?.valid_count > 0 && Number.isFinite(value) && value >= 0;
        return {
          phase,
          value: valid ? value * metric.factor : null,
          count: phaseSummary?.valid_count ?? null,
        };
      });
      return {
        ...metric,
        points,
        max: metric.unit === '%' ? 100 : Math.max(1, ...points.map((point) => point.value ?? 0)),
      };
    })
    .filter((metric) => metric.points.filter((point) => point.value != null).length >= 2);
}
