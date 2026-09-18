import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText, routeFromSearch } from './domain.js';

export function useResource(load, { interval = 2000, enabled = true } = {}) {
  const [state, setState] = useState({
    data: null,
    error: '',
    lastSuccess: null,
    loading: enabled,
  });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const previousLoad = useRef(load);
  useEffect(() => {
    const changed = previousLoad.current !== load;
    previousLoad.current = load;
    if (changed) setState({ data: null, error: '', lastSuccess: null, loading: enabled });
    if (!enabled) return undefined;
    let stopped = false;
    let timer;
    const controller = new AbortController();
    async function pull() {
      setState((current) => ({ ...current, loading: true }));
      try {
        const data = await load({ signal: controller.signal });
        if (!stopped)
          setState({
            data,
            error: '',
            lastSuccess: Date.now(),
            loading: false,
          });
      } catch (error) {
        if (!stopped && error?.name !== 'AbortError')
          setState((current) => ({
            ...current,
            error: errorText(error),
            loading: false,
          }));
      } finally {
        if (!stopped && interval)
          timer = setTimeout(pull, document.hidden ? interval * 3 : interval);
      }
    }
    pull();
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [load, interval, enabled, revision]);
  return { ...state, refresh };
}

export function useRoute() {
  const [route, setRoute] = useState(() => routeFromSearch(location.search));
  const current = useRef(route);
  const navigate = useCallback((patch, replace = false) => {
    const next = { ...current.current, ...patch };
    current.current = next;
    const url = new URL(location.href);
    for (const key of ['view', 'run', 'day'])
      next[key] ? url.searchParams.set(key, next[key]) : url.searchParams.delete(key);
    history[replace ? 'replaceState' : 'pushState']({}, '', url);
    setRoute(next);
  }, []);
  useEffect(() => {
    const pop = () => {
      current.current = routeFromSearch(location.search);
      setRoute(current.current);
    };
    addEventListener('popstate', pop);
    return () => removeEventListener('popstate', pop);
  }, []);
  return [route, navigate];
}

export function useActions() {
  const running = useRef(new Set());
  const [pending, setPending] = useState({});
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const act = useCallback(async (key, operation) => {
    if (running.current.has(key)) return;
    running.current.add(key);
    setPending((current) => ({ ...current, [key]: true }));
    setError('');
    setNotice('');
    try {
      await operation();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      running.current.delete(key);
      setPending((current) => ({ ...current, [key]: false }));
    }
  }, []);
  return { pending, act, notice, setNotice, error, setError };
}
