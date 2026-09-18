import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createDemoServer, publicTargetPath, targetDisplayUrl } from './server.mjs';

async function listen(server, t) {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(
    () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(resolve);
      }),
  );
  return `http://127.0.0.1:${server.address().port}`;
}

async function fixture(t) {
  const directory = await mkdtemp(path.join(tmpdir(), 'sealed-web-test-'));
  t.after(async () => {
    assert.equal(path.dirname(path.resolve(directory)), path.resolve(tmpdir()));
    assert(path.basename(directory).startsWith('sealed-web-test-'));
    await rm(directory, { recursive: true, force: true });
  });
  await mkdir(path.join(directory, 'replay', 'seals'), { recursive: true });
  await writeFile(path.join(directory, 'index.html'), '<title>Built Sealed</title>');
  await writeFile(
    path.join(directory, 'replay', 'seals', 'index.json'),
    '{"seals":[{"id":"historical"}]}',
  );
  return directory;
}

test('built shell, deep links, runtime configuration and fixtures work with no upstream', async (t) => {
  const dist = await fixture(t);
  const base = await listen(
    createDemoServer({
      dist,
      controlUrl: 'http://127.0.0.1:1',
      targetUrl: 'http://127.0.0.1:1',
      displayUrl: 'http://127.0.0.1:5174/demo',
    }),
    t,
  );
  assert.match(await (await fetch(base + '/?view=fixtures')).text(), /Built Sealed/);
  assert.match(await (await fetch(base + '/saved/run')).text(), /Built Sealed/);
  assert.deepEqual(await (await fetch(base + '/replay/seals/index.json')).json(), {
    seals: [{ id: 'historical' }],
  });
  assert.match(await (await fetch(base + '/config.js')).text(), /127.0.0.1:5174\/demo/);
  assert.equal((await fetch(base + '/api/health')).status, 502);
  assert.equal((await fetch(base + '/healthz')).status, 200);
  assert.equal((await fetch(base + '/replay/seals/missing.json')).status, 404);
  assert.equal((await fetch(base + '/%2e%2e%2f.env')).status, 404);
});

test('same-origin proxy preserves methods/body/query and strips privileged headers', async (t) => {
  const calls = [];
  const upstream = http.createServer(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    calls.push({
      path: request.url,
      method: request.method,
      token: request.headers['x-sealed-token'],
      body,
    });
    response.writeHead(200, {
      'Content-Type': 'application/json',
      'X-Sealed-Token': 'must-not-reach-browser',
    });
    response.end('{"status":"ok"}');
  });
  const upstreamUrl = await listen(upstream, t);
  const dist = await fixture(t);
  for (const mode of ['console', 'target']) {
    const base = await listen(
      createDemoServer({ mode, dist, targetUrl: upstreamUrl, controlUrl: upstreamUrl }),
      t,
    );
    const prefix = mode === 'console' ? '/target' : '/api';
    for (const suffix of [
      '/_faults',
      '/%5Ffaults',
      '/_faults/run',
      '/jobs/../_faults',
      '/jobs%2f..%2f_faults',
    ]) {
      for (const method of ['GET', 'POST', 'DELETE']) {
        assert.equal((await fetch(base + prefix + suffix, { method })).status, 404);
      }
    }
    assert.equal(calls.length, mode === 'console' ? 0 : 2);
    const response = await fetch(base + prefix + '/jobs?limit=25', {
      headers: { 'X-Sealed-Token': 'private' },
    });
    assert.equal(response.headers.get('x-sealed-token'), null);
    assert.deepEqual(calls.at(-1), {
      path: '/jobs?limit=25',
      method: 'GET',
      token: undefined,
      body: '',
    });
    await fetch(base + prefix + '/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"payload":{"ok":true}}',
    });
    assert.equal(calls.at(-1).body, '{"payload":{"ok":true}}');
    const count = calls.length;
    assert.equal(
      (await fetch(base + prefix + '/jobs', { method: 'POST', body: 'x'.repeat(65537) })).status,
      413,
    );
    assert.equal(calls.length, count);
  }
});

test('proxy has an absolute response deadline', async (t) => {
  const upstream = await listen(
    http.createServer(() => {}),
    t,
  );
  const base = await listen(
    createDemoServer({ dist: await fixture(t), controlUrl: upstream, proxyTimeoutMs: 30 }),
    t,
  );
  const response = await fetch(base + '/api/health');
  assert.equal(response.status, 504);
  assert.equal((await response.json()).detail, 'upstream_timeout');
});

test('proxy deadline also bounds an upstream that sends headers but never finishes', async (t) => {
  const upstream = await listen(
    http.createServer((_request, response) => {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.write('{');
    }),
    t,
  );
  const base = await listen(
    createDemoServer({ dist: await fixture(t), controlUrl: upstream, proxyTimeoutMs: 100 }),
    t,
  );
  const response = await fetch(base + '/api/health');
  await assert.rejects(response.text());
});

test('public target allowlist and local display configuration cannot become fault targets', () => {
  assert.equal(publicTargetPath('GET', '/jobs/job-1'), true);
  assert.equal(publicTargetPath('DELETE', '/jobs/job-1'), false);
  assert.equal(publicTargetPath('POST', '/probe'), false);
  for (const url of [
    'https://outside.example',
    'javascript:alert(1)',
    'http://user:secret@localhost:5174',
  ])
    assert.throws(() => targetDisplayUrl(url));
});
