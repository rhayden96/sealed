/** Built-asset demo server. The only upstreams are the two Compose APIs. */
import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};
const HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);
const BODY_LIMIT = 65536;

export function publicTargetPath(method, rawPath) {
  return method === 'GET'
    ? /^\/(health|metrics|probe|jobs(?:\/[A-Za-z0-9_-]{1,128})?)$/.test(rawPath)
    : method === 'POST' && /^\/(login|jobs)$/.test(rawPath);
}

export function targetDisplayUrl(value = 'http://localhost:5174') {
  const url = new URL(value);
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ||
    url.username ||
    url.password
  ) {
    throw new Error('TARGET_APP_URL must be a local HTTP(S) demo display URL');
  }
  return url.href;
}

function send(response, status, body, type = 'application/json') {
  if (response.headersSent || response.destroyed) return;
  response.writeHead(status, {
    'Content-Type': type,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  response.end(typeof body === 'string' ? body : JSON.stringify(body));
}

function headersWithoutPrivate(headers) {
  const result = {};
  const connectionNames = String(headers.connection || '')
    .toLowerCase()
    .split(',')
    .map((value) => value.trim());
  for (const [key, value] of Object.entries(headers)) {
    if (
      !HOP.has(key.toLowerCase()) &&
      !connectionNames.includes(key.toLowerCase()) &&
      !key.toLowerCase().startsWith('x-sealed-')
    )
      result[key] = value;
  }
  return result;
}

async function proxy(request, response, base, upstreamPath, timeoutMs) {
  if (Number(request.headers['content-length']) > BODY_LIMIT) {
    request.resume();
    send(response, 413, { detail: 'payload_too_large' });
    return;
  }
  let bytes = 0;
  const chunks = [];
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > BODY_LIMIT) {
      send(response, 413, { detail: 'payload_too_large' });
      return;
    }
    chunks.push(chunk);
  }
  if (response.destroyed) return;
  const body = Buffer.concat(chunks);
  const destination = new URL(base);
  const headers = headersWithoutPrivate(request.headers);
  headers.host = destination.host;
  headers['content-length'] = String(body.length);
  const upstream = http.request(
    {
      hostname: destination.hostname,
      port: destination.port,
      method: request.method,
      path: upstreamPath,
      headers,
    },
    (incoming) => {
      // Keep the absolute deadline through the final response byte.
      response.writeHead(incoming.statusCode || 502, headersWithoutPrivate(incoming.headers));
      incoming.pipe(response);
      incoming.on('error', () => response.destroy());
    },
  );
  const deadline = setTimeout(() => {
    send(response, 504, { detail: 'upstream_timeout' });
    upstream.destroy();
  }, timeoutMs);
  deadline.unref();
  upstream.on('error', () => {
    clearTimeout(deadline);
    send(response, 502, { detail: 'upstream_unavailable' });
  });
  response.on('close', () => {
    clearTimeout(deadline);
    upstream.destroy();
  });
  upstream.end(body);
}

export function createDemoServer({
  mode = 'console',
  dist,
  controlUrl = 'http://control:8081',
  targetUrl = 'http://target:8080',
  displayUrl = 'http://localhost:5174',
  proxyTimeoutMs = 25000,
}) {
  if (!['console', 'target'].includes(mode)) throw new Error('invalid_demo_web_mode');
  const root = path.resolve(dist);
  const targetAppUrl = targetDisplayUrl(displayUrl);
  const server = http.createServer(async (request, response) => {
    try {
      const rawUrl = request.url || '/';
      const rawPath = rawUrl.split('?', 1)[0];
      if (rawPath === '/healthz' && request.method === 'GET')
        return send(response, 200, {
          status: 'ok',
          service: `${mode}-web`,
          runtime: 'built-assets',
        });
      const prefix = mode === 'console' ? '/target' : '/api';
      if (rawPath === prefix || rawPath.startsWith(`${prefix}/`)) {
        const targetPath = rawPath.slice(prefix.length);
        if (!publicTargetPath(request.method, targetPath))
          return send(response, 404, { detail: 'not_found' });
        return await proxy(
          request,
          response,
          targetUrl,
          rawUrl.slice(prefix.length),
          proxyTimeoutMs,
        );
      }
      if (mode === 'console' && (rawPath === '/api' || rawPath.startsWith('/api/'))) {
        return await proxy(request, response, controlUrl, rawUrl.slice(4) || '/', proxyTimeoutMs);
      }
      if (!['GET', 'HEAD'].includes(request.method))
        return send(response, 405, { detail: 'method_not_allowed' });
      if (rawPath === '/config.js')
        return send(
          response,
          200,
          `window.SEALED_CONFIG = ${JSON.stringify({ targetAppUrl }).replaceAll('<', '\\u003c')};\n`,
          MIME['.js'],
        );
      let decoded;
      try {
        decoded = decodeURIComponent(rawPath);
      } catch {
        return send(response, 400, { detail: 'invalid_path' });
      }
      if (decoded.includes('\\') || decoded.includes('\0') || decoded.split('/').includes('..'))
        return send(response, 404, { detail: 'not_found' });
      let filename = path.resolve(root, `.${decoded === '/' ? '/index.html' : decoded}`);
      if (!filename.startsWith(root + path.sep))
        return send(response, 404, { detail: 'not_found' });
      try {
        if (!(await stat(filename)).isFile()) return send(response, 404, { detail: 'not_found' });
      } catch {
        if (path.extname(decoded)) return send(response, 404, { detail: 'not_found' });
        filename = path.join(root, 'index.html');
      }
      const content = await readFile(filename);
      response.writeHead(200, {
        'Content-Type': MIME[path.extname(filename)] || 'application/octet-stream',
        'Content-Length': content.length,
        'Cache-Control': decoded.startsWith('/assets/')
          ? 'public, max-age=31536000, immutable'
          : 'no-cache',
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy':
          "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'",
        'Referrer-Policy': 'no-referrer',
      });
      response.end(request.method === 'HEAD' ? undefined : content);
    } catch {
      send(response, 500, { detail: 'web_request_failed' });
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 10000;
  server.keepAliveTimeout = 5000;
  return server;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const mode = process.env.WEB_MODE || 'console';
  const dist = process.env.STATIC_DIR || '/app/dist';
  const controlUrl = process.env.CONTROL_URL || 'http://control:8081';
  const targetUrl = process.env.TARGET_URL || 'http://target:8080';
  if (controlUrl !== 'http://control:8081' || targetUrl !== 'http://target:8080')
    throw new Error('demo_upstreams_must_be_compose_services');
  await stat(path.join(dist, 'index.html'));
  const server = createDemoServer({
    mode,
    dist,
    controlUrl,
    targetUrl,
    displayUrl: process.env.TARGET_APP_URL,
  });
  const port = Number(process.env.PORT || (mode === 'console' ? 5173 : 5174));
  server.listen(port, '0.0.0.0', () =>
    process.stdout.write(
      `Sealed ${mode} built assets ready on :${port}; /healthz checks web only.\n`,
    ),
  );
  const stop = () => {
    server.close(() => process.exit(0));
    setTimeout(() => {
      server.closeAllConnections();
      process.exit(0);
    }, 5000).unref();
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
}
