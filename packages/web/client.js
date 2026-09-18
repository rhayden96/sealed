/** Shared browser HTTP contract. No credentials or privileged target routes. */
export class ApiError extends Error {
  constructor(message, { status = 0, detail = null, ms = 0, code = 'request_failed' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.ms = ms;
    this.code = code;
  }
}

export function formatDetail(detail) {
  if (detail == null) return 'The service returned no error details.';
  if (typeof detail === 'string') {
    if (/^\s*</.test(detail))
      return 'The service returned an unexpected page. It may be unavailable.';
    return detail.replaceAll('_', ' ').slice(0, 500);
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        typeof item === 'object' && item
          ? `${(item.loc || []).join('.')}: ${item.msg || 'invalid value'}`
          : String(item),
      )
      .join('; ')
      .slice(0, 800);
  }
  if (Array.isArray(detail.reasons))
    return detail.reasons.map((reason) => formatDetail(reason)).join('; ');
  if (detail.reason) return formatDetail(detail.reason);
  return JSON.stringify(detail).slice(0, 800);
}

/** @param {string} url
 * @param {{method?: string, body?: unknown, headers?: Record<string,string>, signal?: AbortSignal, timeoutMs?: number}} [options]
 */
export async function request(
  url,
  { method = 'GET', body, headers = {}, signal, timeoutMs = 8000 } = {},
) {
  const started = performance.now();
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException('Request deadline exceeded', 'TimeoutError'));
  }, timeoutMs);
  try {
    const response = await fetch(url, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...headers,
      },
      signal: controller.signal,
      cache: 'no-store',
    });
    const text = await response.text();
    let parsed = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = text;
    }
    const ms = Math.round(performance.now() - started);
    if (!response.ok) {
      const detail =
        parsed && typeof parsed === 'object' && !Array.isArray(parsed)
          ? (parsed.detail ?? parsed)
          : parsed;
      throw new ApiError(`${response.status}: ${formatDetail(detail)}`, {
        status: response.status,
        detail,
        ms,
        code: response.status === 409 ? 'conflict' : 'http_error',
      });
    }
    return { body: parsed, ms };
  } catch (error) {
    const ms = Math.round(performance.now() - started);
    if (timedOut)
      throw new ApiError('The request timed out. Refresh the run to check its current state.', {
        ms,
        code: 'timeout',
      });
    if (signal?.aborted) throw new DOMException('Request cancelled', 'AbortError');
    if (error instanceof ApiError) throw error;
    throw new ApiError('The service is unavailable. Last-known observations may be stale.', {
      ms,
      code: 'unavailable',
    });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
