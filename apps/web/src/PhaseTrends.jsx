import { number } from './domain.js';
import { measuredTrends } from './presentation.js';

export function PhaseTrends({ evidence }) {
  const trends = measuredTrends(evidence);
  if (!trends.length) return null;
  return (
    <section className="phase-trends" aria-label="Measured phase comparisons">
      <h3>Measured phase comparisons</h3>
      <p className="helper">
        Baseline → fault active → recovery. Bars compare recorded observations; hypothesis checks
        below determine the verdict.
      </p>
      <div className="trend-grid">
        {trends.map((metric) => (
          <figure key={metric.key}>
            <figcaption>{metric.label}</figcaption>
            <ol>
              {metric.points.map((point) => (
                <li key={point.phase}>
                  <div className="trend-label">
                    <span>{point.phase === 'during' ? 'Fault active' : point.phase}</span>
                    <b>
                      {point.value == null
                        ? 'Unavailable'
                        : `${number(point.value, 1)} ${metric.unit}`}
                    </b>
                  </div>
                  <div className="trend-track" aria-hidden="true">
                    <span
                      className={`trend-bar ${point.phase}`}
                      style={{
                        width: `${point.value == null ? 0 : Math.min(100, (point.value / metric.max) * 100)}%`,
                      }}
                    />
                  </div>
                  <small>
                    {point.value == null
                      ? 'No valid measured value'
                      : `${point.count} valid samples`}
                  </small>
                </li>
              ))}
            </ol>
          </figure>
        ))}
      </div>
    </section>
  );
}
