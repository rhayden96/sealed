import { useCallback, useEffect, useRef, useState } from 'react';

export function useResource(load) {
  const [resource, setResource] = useState({
    data: null,
    updatedAt: null,
    error: null,
  });
  const refreshRef = useRef(() => {});

  useEffect(() => {
    let alive = true;
    let timer;
    let controller = null;
    let refreshRequested = false;
    let revision = 0;

    async function poll() {
      if (!alive) return;
      if (controller) {
        refreshRequested = true;
        return;
      }
      clearTimeout(timer);
      controller = new AbortController();
      const current = controller;
      const requestRevision = revision;
      try {
        const { body } = await load({
          signal: current.signal,
          timeoutMs: 3000,
        });
        if (alive && !current.signal.aborted && requestRevision === revision) {
          setResource({ data: body, updatedAt: Date.now(), error: null });
        }
      } catch (error) {
        if (alive && !current.signal.aborted && requestRevision === revision) {
          setResource((previous) => ({ ...previous, error }));
        }
      } finally {
        controller = null;
        if (alive) {
          const delay = refreshRequested ? 0 : document.hidden ? 10000 : 2000;
          refreshRequested = false;
          timer = setTimeout(poll, delay);
        }
      }
    }

    const onVisibility = () => {
      if (!document.hidden) poll();
    };
    refreshRef.current = () => {
      // A mutation may complete while an older GET is still in flight. That
      // response must not replace data or advance the successful-observation
      // timestamp after the caller requested a fresh view of changed state.
      revision += 1;
      return poll();
    };
    document.addEventListener('visibilitychange', onVisibility);
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
      refreshRef.current = () => {};
    };
  }, [load]);

  const refresh = useCallback(() => refreshRef.current(), []);
  return [resource, refresh];
}

export function useAction() {
  const [state, setState] = useState({
    pending: false,
    result: null,
    error: null,
    completedAt: null,
  });
  const controller = useRef(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);

  const run = useCallback(async (operation, onSuccess) => {
    if (controller.current) return;
    const current = new AbortController();
    controller.current = current;
    setState({ pending: true, result: null, error: null, completedAt: null });
    try {
      const result = await operation({
        signal: current.signal,
        timeoutMs: 5000,
      });
      if (mounted.current && !current.signal.aborted) {
        setState({
          pending: false,
          result,
          error: null,
          completedAt: Date.now(),
        });
        onSuccess?.(result);
      }
    } catch (error) {
      if (mounted.current && !current.signal.aborted) {
        setState({
          pending: false,
          result: null,
          error,
          completedAt: Date.now(),
        });
      }
    } finally {
      if (controller.current === current) controller.current = null;
    }
  }, []);

  return { ...state, run };
}
