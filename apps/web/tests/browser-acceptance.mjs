/** Compose browser checks. Set PLAYWRIGHT_MODULE to an installed Playwright
 * package when dependencies are provided outside this checkout. No app server
 * is started here. Run `node apps/web/tests/browser-acceptance.mjs live|replay`.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const consoleUrl = process.env.CONSOLE_URL || 'http://127.0.0.1:5173';
const targetUrl = process.env.TARGET_WEB_URL || 'http://127.0.0.1:5174';
const mode = process.argv[2] || 'live';
const screenshots = path.join(root, 'docs/screenshots');
const resultsPath = path.resolve(
  root,
  process.env.BROWSER_RESULTS_PATH || 'docs/C_BROWSER_RESULTS.json',
);
const results = [];
await fs.mkdir(screenshots, { recursive: true });

async function until(check, message, timeout = 10000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      if (await check()) return;
    } catch (error) {
      last = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`${message}${last ? `: ${last.message}` : ''}`);
}

function report(check, detail = {}) {
  const result = { check, result: 'pass', ...structuredClone(detail) };
  results.push(result);
  process.stdout.write(JSON.stringify(result) + '\n');
}

async function screenshot(page, name) {
  const prefix = process.env.BROWSER_SCREENSHOT_PREFIX
    ? `${process.env.BROWSER_SCREENSHOT_PREFIX}-`
    : '';
  await page.screenshot({ path: path.join(screenshots, `${prefix}${name}.png`), fullPage: true });
}

async function textMatches(locator, pattern, message) {
  await locator.waitFor({ state: 'visible' });
  await until(async () => pattern.test(await locator.innerText()), message);
}

async function responseFor(page, method, suffix, action) {
  const pending = page.waitForResponse(
    (response) =>
      response.request().method() === method && new URL(response.url()).pathname.endsWith(suffix),
  );
  await action();
  const response = await pending;
  assert(response.ok(), `${method} ${suffix}: ${response.status()} ${await response.text()}`);
  return response.json();
}

async function live(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const target = await context.newPage();
  const errors = [];
  const ownedRunIds = [];
  for (const current of [page, target])
    current.on('pageerror', (error) => errors.push(error.message));
  try {
    await target.goto(targetUrl, { waitUntil: 'domcontentloaded' });
    await target.getByRole('button', { name: 'Hit handler', exact: true }).waitFor();
    const businessCalls = [];
    target.on('request', (request) => {
      if (/\/(probe|jobs)(?:\?|$)/.test(request.url()))
        businessCalls.push({ method: request.method(), path: new URL(request.url()).pathname });
    });
    await responseFor(target, 'GET', '/api/probe', () =>
      target.getByRole('button', { name: 'Hit handler', exact: true }).click(),
    );
    assert.equal(
      businessCalls.filter((call) => call.method === 'POST' && call.path.endsWith('/jobs')).length,
      0,
    );
    report('target handler action is non-mutating GET /probe', { calls: businessCalls });
    let enqueueCount = 0;
    let releaseEnqueue;
    const enqueueGate = new Promise((resolve) => {
      releaseEnqueue = resolve;
    });
    await target.route('**/api/jobs', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      enqueueCount += 1;
      const response = await route.fetch();
      await enqueueGate;
      await route.fulfill({ response });
    });
    const enqueueResponse = target.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/jobs',
    );
    const enqueue = target.getByRole('button', { name: 'Enqueue job', exact: true });
    try {
      await enqueue.evaluate((button) => {
        button.click();
        button.click();
      });
      await until(() => enqueueCount === 1, 'first enqueue is pending');
      assert.equal(enqueueCount, 1, 'rapid repeated activation must not duplicate an enqueue');
      assert(await target.getByRole('button', { name: 'Enqueuing…', exact: true }).isDisabled());
    } finally {
      releaseEnqueue();
    }
    const enqueuedResponse = await enqueueResponse;
    assert(enqueuedResponse.ok());
    const enqueued = await enqueuedResponse.json();
    await target.unroute('**/api/jobs');
    report('rapid repeated enqueue is deduplicated while its response is pending', {
      requests: enqueueCount,
    });
    const shortJob = enqueued.job_id.slice(0, 8);
    const jobs = target.getByRole('list', { name: 'Recent jobs' });
    await textMatches(jobs, new RegExp(shortJob), 'new job is visible in target history');

    await page.goto(consoleUrl, { waitUntil: 'domcontentloaded' });
    const composer = page.getByRole('region', { name: 'New experiment', exact: true });
    const selected = page.getByRole('region', { name: 'Selected run', exact: true });
    const active = page.getByRole('region', { name: 'Active run', exact: true });
    await composer.getByRole('button', { name: 'Compose Handler latency', exact: true }).click();
    const latency = await responseFor(page, 'POST', '/api/drafts', () =>
      composer.getByRole('button', { name: 'Create & auto-unseal', exact: true }).click(),
    );
    ownedRunIds.push(latency.id);
    assert.equal(latency.catalog_id, 'handler_latency');
    assert.equal(latency.status, 'unsealed');
    await composer.getByRole('button', { name: 'Compose Worker drop', exact: true }).click();
    await textMatches(
      selected,
      /Handler latency/,
      'composer switching preserves selected latency identity',
    );
    assert((await selected.innerText()).includes(latency.id));
    await screenshot(page, 'c-console-auto-unseal-desktop');
    report('explicit auto-unseal and selected run survive composer switching', {
      run_id: latency.id,
    });
    await until(
      async () => {
        const response = await page.request.get(`${consoleUrl}/api/drafts/${latency.id}/seal`);
        return response.ok() && (await response.json())?.verdict === 'pass';
      },
      'auto-unsealed latency completes with measured passing seal',
      10000,
    );

    await composer.getByRole('button', { name: 'Compose Redis down', exact: true }).click();
    const redis = await responseFor(page, 'POST', '/api/drafts', () =>
      composer.getByRole('button', { name: 'Create draft', exact: true }).click(),
    );
    ownedRunIds.push(redis.id);
    await composer.getByRole('button', { name: 'Compose Worker drop', exact: true }).click();
    await textMatches(
      selected,
      /Redis down/,
      'selected Redis draft retains its identity before approval',
    );
    assert((await selected.innerText()).includes(redis.id));
    const mutations = [];
    page.on('request', (request) => {
      if (
        request.method() === 'POST' &&
        /\/(approve|unseal)$/.test(new URL(request.url()).pathname)
      )
        mutations.push(new URL(request.url()).pathname);
    });
    await responseFor(page, 'POST', `/api/drafts/${redis.id}/unseal`, () =>
      selected.getByRole('button', { name: 'Approve & unseal', exact: true }).click(),
    );
    assert(mutations.length >= 2);
    assert(mutations.every((url) => url.includes(`/drafts/${redis.id}/`)));
    report('approval after composer switching affects the selected Redis run', {
      run_id: redis.id,
      mutations,
    });

    await textMatches(
      target.locator('body'),
      /Job updates unavailable\. Showing last-known jobs\./,
      'target retains jobs during Redis outage',
    );
    assert((await jobs.innerText()).includes(shortJob));
    const deniedLogin = target.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/login',
    );
    await target.getByRole('button', { name: 'Probe session', exact: true }).click();
    assert.equal((await deniedLogin).status(), 503);
    await textMatches(
      target.locator('body'),
      /fail(?:ed)?[ _-]closed/i,
      'target explains synthetic login failure',
    );
    await screenshot(target, 'c-target-redis-outage-desktop');
    report('target Redis outage retains last-known jobs and shows fail-closed login', {
      retained_job: enqueued.job_id,
    });

    await page.getByRole('button', { name: 'Tape', exact: true }).click();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await textMatches(
      active,
      new RegExp(redis.id),
      'active run recovered after navigation and refresh',
    );
    let releasePlanner;
    let plannerEntered = false;
    const released = new Promise((resolve) => {
      releasePlanner = resolve;
    });
    await page.route('**/api/agent/propose', async (route) => {
      plannerEntered = true;
      await released;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          draft: null,
          explanation: 'Browser acceptance held this request pending.',
          requested_provider: 'stub',
          actual_provider: 'stub',
          planner: 'stub',
          outcome: 'no_proposal',
          trace: [],
        }),
      });
    });
    try {
      await page.getByRole('button', { name: 'Propose draft', exact: true }).click();
      await until(() => plannerEntered, 'planner request becomes pending', 5000);
      const abort = active.getByRole('button', { name: 'Abort / reseal active run', exact: true });
      assert(await abort.isEnabled(), 'pending planning must not disable abort');
      await screenshot(page, 'c-console-planner-pending-active-abort');
      const start = Date.now();
      await responseFor(page, 'POST', `/api/drafts/${redis.id}/reseal`, () => abort.click());
      report('global scoped abort works after navigation/refresh while planning is pending', {
        run_id: redis.id,
        response_ms: Date.now() - start,
        planner_request: 'intercepted pending',
      });
    } finally {
      releasePlanner();
    }
    await until(async () => {
      const response = await page.request.get(`${consoleUrl}/api/drafts/${redis.id}/seal`);
      return response.ok() && (await response.json())?.verdict === 'aborted';
    }, 'Redis abort finalizes with aborted seal');
    await page.unroute('**/api/agent/propose');

    await page.getByRole('button', { name: 'Console', exact: true }).click();
    const liveTarget = page.getByRole('region', { name: 'Live target', exact: true });
    await textMatches(
      liveTarget,
      /Healthy/i,
      'live target recovers before stale-observation check',
    );
    await page.route('**/target/health', (route) => route.abort('failed'));
    await textMatches(liveTarget, /Stale/i, 'failed health request becomes visibly stale');
    await textMatches(
      liveTarget,
      /Last known|Last successful/i,
      'stale health retains labeled observations',
    );
    await screenshot(page, 'c-console-stale-health-desktop');
    report(
      'failed live health request keeps labeled last-known values instead of green current status',
    );
    await page.unroute('**/target/health');
    await textMatches(liveTarget, /Healthy/i, 'healthy polling resumes after network failure');
    await page.route('**/target/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<html>Unexpected upstream page</html>',
      }),
    );
    await textMatches(liveTarget, /Stale/i, 'malformed successful health response becomes stale');
    await textMatches(
      liveTarget,
      /Last known|Last successful/i,
      'malformed health response preserves prior observations',
    );
    report('malformed HTTP 200 health response cannot replace valid observations');
    await page.unroute('**/target/health');

    await composer.getByRole('combobox', { name: 'Environment', exact: true }).selectOption('prod');
    await composer.getByRole('button', { name: 'Compose Handler latency', exact: true }).click();
    const prod = await responseFor(page, 'POST', '/api/drafts', () =>
      composer.getByRole('button', { name: 'Create draft', exact: true }).click(),
    );
    const decision = await responseFor(page, 'GET', `/api/drafts/${prod.id}/evaluate`, () =>
      selected.getByRole('button', { name: 'Evaluate policy', exact: true }).click(),
    );
    assert.equal(decision.allowed, false);
    assert(decision.reasons.includes('environment_denied'));
    await screenshot(page, 'c-console-prod-denied-desktop');
    report('prod denial example exposes clerk reasons without injecting', { run_id: prod.id });

    await page.getByRole('button', { name: 'Tape', exact: true }).click();
    const history = page.getByRole('region', { name: 'Run history', exact: true });
    await history.getByLabel('Search runs', { exact: true }).fill(latency.id);
    await history.getByRole('button', { name: `Inspect run ${latency.id}`, exact: true }).click();
    const evidence = page.getByRole('region', { name: 'Run evidence', exact: true });
    await textMatches(evidence, /pass/i, 'selected historical latency shows its own pass seal');
    assert((await evidence.innerText()).includes(latency.id));
    assert(!(await evidence.innerText()).includes(redis.id));
    await screenshot(page, 'c-console-selected-evidence-desktop');
    await page.setViewportSize({ width: 390, height: 844 });
    await screenshot(page, 'c-console-selected-evidence-narrow');
    await target.setViewportSize({ width: 390, height: 844 });
    await screenshot(target, 'c-target-recovered-narrow');
    report('historical evidence is associated with selected run, not latest global seal', {
      run_id: latency.id,
    });
    assert.deepEqual(errors, [], 'no browser page errors');
    report('both frontends have no unhandled browser errors');
  } catch (error) {
    await screenshot(page, 'c-live-failure').catch(() => {});
    throw error;
  } finally {
    for (const runId of ownedRunIds) {
      try {
        const response = await page.request.get(`${consoleUrl}/api/drafts/${runId}`);
        const draft = response.ok() ? await response.json() : null;
        if (
          ['reserved', 'injecting', 'unsealed', 'cleanup_pending', 'recovering'].includes(
            draft?.status,
          )
        ) {
          await page.request.post(`${consoleUrl}/api/drafts/${runId}/reseal`);
        }
      } catch {
        /* A server outage remains visible in the failing test result. */
      }
    }
    await context.close();
  }
}

async function targetPollRace(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  let holdNextPoll = false;
  let oldPollPending = false;
  let releaseOld;
  const held = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route(/\/api\/jobs\?limit=50$/, async (route) => {
    if (!holdNextPoll)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          jobs: [{ id: 'retained-first-job', status: 'done' }],
          next_offset: null,
        }),
      });
    if (!oldPollPending) {
      oldPollPending = true;
      await held;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          jobs: [{ id: 'obsolete-old-poll', status: 'done' }],
          next_offset: null,
        }),
      });
    }
    return route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'unavailable' }),
    });
  });
  await page.route('**/api/jobs', (route) =>
    route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'synthetic-new-job', status: 'queued' }),
    }),
  );
  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });
    const jobs = page.getByRole('list', { name: 'Recent jobs', exact: true });
    await textMatches(jobs, /retained/, 'initial job observation is rendered');
    holdNextPoll = true;
    await until(() => oldPollPending, 'older jobs poll is held pending', 5000);
    await responseFor(page, 'POST', '/api/jobs', () =>
      page.getByRole('button', { name: 'Enqueue job', exact: true }).click(),
    );
    await textMatches(
      page.locator('body'),
      /Queued job syntheti/,
      'mutation response requests a new jobs observation',
    );
    releaseOld();
    await textMatches(
      page.locator('body'),
      /Job updates unavailable\. Showing last-known jobs\./,
      'new poll failure is visibly stale',
    );
    assert.match(await jobs.innerText(), /retained/);
    assert.doesNotMatch(await jobs.innerText(), /obsolete/);
    assert.deepEqual(errors, []);
    report('older jobs response cannot overwrite cached observations after mutation refresh', {
      requests: 'intercepted GET/POST fixtures',
      retained: 'retained-first-job',
    });
  } finally {
    releaseOld();
    await context.close();
  }
}

async function targetInvalidResponses(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(targetUrl);
    await textMatches(page.locator('header').first(), /healthy/i, 'target initially healthy');
    const jobs = page.getByRole('list', { name: 'Recent jobs', exact: true });
    await jobs.waitFor();
    const before = await jobs.innerText();
    await page.route('**/api/health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
    );
    await page.route(/\/api\/jobs\?limit=50$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [{ id: 'bad-status', status: {} }] }),
      }),
    );
    await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
    await textMatches(
      page.locator('body'),
      /Current service states are unknown/,
      'invalid200 health preserves stale state',
    );
    await textMatches(
      page.locator('body'),
      /Job updates unavailable\. Showing last-known jobs\./,
      'invalid200 jobs preserve history',
    );
    assert.equal(await jobs.innerText(), before);
    await textMatches(
      page.locator('body'),
      /Last known: Healthy/,
      'last known health remains visible',
    );
    await screenshot(page, 'target-invalid-response-stale');
    report('target invalid HTTP200 health/jobs retain labeled last-known observations');
    await page.unroute('**/api/health');
    await page.unroute(/\/api\/jobs\?limit=50$/);
    await page.route('**/api/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', api: '__proto__', redis: 'ok', worker: 'ok' }),
      }),
    );
    await page.route(/\/api\/jobs\?limit=50$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          jobs: [{ id: 'prototype-job', status: '__proto__', reason: 'constructor' }],
        }),
      }),
    );
    await page.reload();
    await textMatches(
      page.locator('header').first(),
      /unknown/i,
      'unknown health value displays safe unknown state',
    );
    await textMatches(jobs, /Unknown/, 'unknown job string displays safe Unknown label');
    assert.deepEqual(errors, []);
    report('prototype-named health/job values render Unknown without page errors', {
      page_errors: 0,
      source: 'intercepted browser responses',
    });
  } finally {
    await context.close();
  }
}

async function replay(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const mutations = [];
  const errors = [];
  page.on('request', (request) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()))
      mutations.push({ method: request.method(), url: request.url() });
  });
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(consoleUrl, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Fixtures', exact: true }).click();
    await page
      .getByRole('button', { name: /^Replay fixture / })
      .first()
      .click();
    const details = page.getByRole('region', { name: 'Fixture details', exact: true });
    await textMatches(
      details,
      /historical|synthetic/i,
      'replay explicitly identifies historical or synthetic fixture',
    );
    await textMatches(details, /hypothesis/i, 'replay includes hypothesis detail');
    await textMatches(
      details,
      /no measured|legacy|not measured|evidence unavailable/i,
      'legacy replay does not invent measured evidence',
    );
    await screenshot(page, 'c-offline-fixture-desktop');
    await page.setViewportSize({ width: 390, height: 844 });
    await screenshot(page, 'c-offline-fixture-narrow');
    assert.deepEqual(mutations, [], 'opening and replaying fixtures performs zero mutations');
    assert.deepEqual(errors, [], 'offline fixture rendering has no browser errors');
    report('offline fixture detail renders without live services or mutations', {
      mutations: 0,
      page_errors: 0,
    });
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
});
try {
  if (mode === 'live') await live(browser);
  else if (mode === 'target-race') await targetPollRace(browser);
  else if (mode === 'target-invalid') await targetInvalidResponses(browser);
  else if (mode === 'replay') await replay(browser);
  else throw new Error(`Unknown browser acceptance mode: ${mode}`);
} catch (error) {
  results.push({ check: `${mode} browser acceptance`, result: 'fail', error: error.message });
  process.stderr.write(error.stack + '\n');
  process.exitCode = 1;
} finally {
  await browser.close();
  let previous = [];
  if (mode !== 'live') {
    try {
      previous = JSON.parse(await fs.readFile(resultsPath, 'utf8'));
    } catch {
      /* First run. */
    }
  }
  await fs.writeFile(resultsPath, JSON.stringify([...previous, ...results], null, 2) + '\n');
}
