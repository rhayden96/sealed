import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { reason, time } from './domain.js';
import { clampDrawerHeight, drawerBounds, traceProgress } from './presentation.js';

function readPreference(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function savePreference(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* Storage is optional. */
  }
}

export function PlannerDrawer({ resource, pending, result, proposalId, onPropose, onCancel }) {
  const [collapsed, setCollapsed] = useState(
    () => readPreference('sealed-agent-collapsed') === '1',
  );
  const [viewportHeight, setViewportHeight] = useState(() => window.innerHeight);
  const [height, setHeight] = useState(() =>
    clampDrawerHeight(readPreference('sealed-agent-height'), window.innerHeight),
  );
  const [follow, setFollow] = useState(true);
  const [unread, setUnread] = useState(0);
  const log = useRef(null);
  const previousSeq = useRef(null);
  const trace = resource.data?.trace;
  const bounds = drawerBounds(viewportHeight);

  useEffect(() => {
    const timer = setTimeout(() => savePreference('sealed-agent-height', height), 180);
    return () => clearTimeout(timer);
  }, [height]);

  useEffect(() => {
    let timer;
    const resize = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        setViewportHeight(window.innerHeight);
        setHeight((value) => clampDrawerHeight(value, window.innerHeight));
      }, 120);
    };
    window.addEventListener('resize', resize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', resize);
    };
  }, []);

  useLayoutEffect(() => {
    const progress = traceProgress(trace || [], previousSeq.current);
    previousSeq.current = progress.lastSeq;
    if (follow && !collapsed && log.current) {
      // Scroll only this log. Background polling must never move the page.
      log.current.scrollTop = log.current.scrollHeight;
      setUnread(0);
    } else if (progress.added) {
      setUnread((value) => value + progress.added);
    }
  }, [trace, follow, collapsed, height]);

  function onScroll() {
    const element = log.current;
    if (!element) return;
    const nearEnd = element.scrollHeight - element.scrollTop - element.clientHeight <= 32;
    setFollow(nearEnd);
    if (nearEnd) setUnread(0);
  }

  return (
    <aside
      className="drawer"
      style={{ height: collapsed ? 'auto' : height }}
      aria-label="Planner diagnostics"
    >
      <div className="drawer-head">
        <b>AGENT</b>
        <span>{resource.data?.planner || 'unknown'}</span>
        <span>{resource.data?.last_tool || 'No tool calls'}</span>
        {collapsed && unread > 0 && <span>{unread} unread entries</span>}
        <button
          aria-expanded={!collapsed}
          aria-controls="planner-drawer-content"
          onClick={() => {
            setCollapsed((value) => !value);
            savePreference('sealed-agent-collapsed', collapsed ? '0' : '1');
          }}
        >
          {collapsed ? 'Open agent' : 'Collapse agent'}
        </button>
      </div>
      {!collapsed && (
        <div className="drawer-body" id="planner-drawer-content">
          <div className="drawer-controls">
            <button className="ghost" disabled={pending} onClick={onPropose}>
              {pending ? 'Planning…' : 'Propose draft'}
            </button>
            {pending && proposalId && (
              <button className="ghost" onClick={() => onCancel(proposalId)}>
                Cancel planning
              </button>
            )}
            <label>
              <input
                type="checkbox"
                aria-label="Follow"
                checked={follow}
                onChange={(event) => setFollow(event.target.checked)}
              />{' '}
              Follow
            </label>
            <span className="unread-count" role="status" aria-live="polite">
              {unread} unread entries
            </span>
            <label>
              Log height
              <input
                type="range"
                aria-label="Agent log height"
                aria-valuetext={`${height} pixels`}
                min={bounds.min}
                max={bounds.max}
                step="1"
                value={height}
                onChange={(event) =>
                  setHeight(clampDrawerHeight(event.target.value, viewportHeight))
                }
              />
            </label>
          </div>
          {result && (
            <p className="planner-result" role="status">
              Requested: {result.requested_provider || 'unknown'} · Used:{' '}
              {result.actual_provider || result.planner || 'unknown'} · {reason(result.outcome)}.{' '}
              {result.fallback_reason ? `Fallback: ${reason(result.fallback_reason)}. ` : ''}
              {result.explanation}
            </p>
          )}
          {resource.error && (
            <p className="error drawer-error">Diagnostics stale: {resource.error}</p>
          )}
          <div
            className="drawer-log"
            ref={log}
            onScroll={onScroll}
            role="region"
            aria-label="Planner log"
            tabIndex={0}
          >
            {trace?.length ? (
              trace.map((line) => (
                <div className="drawer-line" key={line.seq || `${line.ts}-${line.tool}`}>
                  <time>{time(line.ts)}</time>
                  <span className="tool">{line.tool}</span>
                  <span>{line.result_summary}</span>
                </div>
              ))
            ) : (
              <p className="muted">
                Planner diagnostics only. Authoritative run events appear in Tape.
              </p>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
