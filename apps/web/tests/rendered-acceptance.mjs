/** Render/accessibility acceptance against Compose only. No app server starts.
 * `node apps/web/tests/rendered-acceptance.mjs audit|full`.
 * AXE_MODULE and PLAYWRIGHT_MODULE optionally point to installed packages.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const axePath = require.resolve(process.env.AXE_MODULE || 'axe-core/axe.min.js');
const axeSource = await fs.readFile(axePath, 'utf8');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const consoleUrl = process.env.CONSOLE_URL || 'http://127.0.0.1:5173';
const targetUrl = process.env.TARGET_WEB_URL || 'http://127.0.0.1:5174';
const mode = process.argv[2] || 'full';
const results = [];
const failures = [];
const screenshots = path.join(root, 'docs/screenshots');
await fs.mkdir(screenshots, { recursive: true });

function record(check, detail = {}, failed = false) {
  const row = { check, result: failed ? 'fail' : 'pass', ...structuredClone(detail) };
  results.push(row);
  if (failed) failures.push(row);
  const output = row.incomplete
    ? {
        ...row,
        incomplete: row.incomplete.map((item) => ({ id: item.id, count: item.nodes.length })),
      }
    : row;
  process.stdout.write(JSON.stringify(output) + '\n');
}
async function until(check, label, timeout = 10000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(label);
}
async function shot(page, name, fullPage = false) {
  await page.screenshot({ path: path.join(screenshots, `${name}.png`), fullPage });
}
async function audit(page, label) {
  const instrumentationUrl = `${new URL(page.url()).origin}/__acceptance-axe.js`;
  await page.route(instrumentationUrl, (route) =>
    route.fulfill({ status: 200, contentType: 'application/javascript', body: axeSource }),
  );
  await page.addScriptTag({ url: instrumentationUrl });
  await page.unroute(instrumentationUrl);
  const result = await page.evaluate(async () => {
    const outcome = await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
    });
    return {
      violations: outcome.violations.map((item) => ({
        id: item.id,
        impact: item.impact,
        description: item.description,
        nodes: item.nodes.map((node) => ({
          target: node.target,
          failureSummary: node.failureSummary,
        })),
      })),
      incomplete: outcome.incomplete.map((item) => ({
        id: item.id,
        nodes: item.nodes.map((node) => ({
          target: node.target,
          failureSummary: node.failureSummary,
        })),
      })),
      passes: outcome.passes.length,
    };
  });
  record(`${label}: automated WCAG audit`, result, result.violations.length > 0);
}
async function layout(page, label) {
  const dimensions = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  record(
    `${label}: no document horizontal overflow`,
    dimensions,
    Math.max(dimensions.document, dimensions.body) > dimensions.viewport + 1,
  );
}
async function keyboardReach(page, locator, label) {
  await page.evaluate(() => {
    document.activeElement?.blur();
    window.scrollTo(0, 0);
  });
  let reached = false;
  for (let index = 0; index < 100; index += 1) {
    await page.keyboard.press('Tab');
    if (await locator.evaluate((element) => element === document.activeElement)) {
      reached = true;
      break;
    }
  }
  assert(reached, `Keyboard can reach ${label}`);
  const focus = await locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      focusVisible: element.matches(':focus-visible'),
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      boxShadow: style.boxShadow,
    };
  });
  record(
    `${label}: keyboard reachable with visible focus`,
    focus,
    !focus.focusVisible || (focus.outlineStyle === 'none' && focus.boxShadow === 'none'),
  );
}

async function matrix(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const target = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  target.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(consoleUrl);
    await page.getByRole('region', { name: 'New experiment', exact: true }).waitFor();
    await until(
      async () =>
        /healthy/i.test(
          await page.getByRole('region', { name: 'Live target', exact: true }).innerText(),
        ),
      'healthy console observation',
    );
    await target.goto(targetUrl);
    await until(
      async () => /healthy/i.test(await target.locator('header').first().innerText()),
      'healthy target observation',
    );
    for (const width of [360, 390, 768, 1280, 1440]) {
      for (const [name, current] of [
        ['console', page],
        ['target', target],
      ]) {
        await current.setViewportSize({ width, height: 900 });
        await current.evaluate(() => scrollTo(0, 0));
        await layout(current, `${name} ${width}px`);
        await shot(current, `after-${name}-${width}`);
      }
    }
    for (const [name, current] of [
      ['console', page],
      ['target', target],
    ]) {
      await current.setViewportSize({ width: 720, height: 450 });
      await layout(current, `${name} effective 200% zoom (1440×900 to 720×450 CSS viewport)`);
      await shot(current, `after-${name}-200-percent`);
      await current.setViewportSize({ width: 1440, height: 900 });
      await audit(current, `${name} desktop`);
      await current.setViewportSize({ width: 390, height: 844 });
      await audit(current, `${name} narrow`);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    const fixtures = page.getByRole('button', { name: 'Fixtures', exact: true });
    await keyboardReach(page, fixtures, 'Fixtures navigation');
    await page.keyboard.press('Enter');
    assert.equal(await fixtures.getAttribute('aria-current'), 'page');
    const fixture = page.getByRole('button', { name: /^Replay fixture / }).first();
    await keyboardReach(page, fixture, 'Fixture replay');
    await page.keyboard.press('Enter');
    await page.getByRole('region', { name: 'Fixture details', exact: true }).waitFor();
    await audit(page, 'fixture detail');
    await shot(page, 'after-fixture-detail-desktop');
    record('fixture navigation and replay work using keyboard only');
    await keyboardReach(
      target,
      target.getByRole('button', { name: 'Hit handler', exact: true }),
      'Target handler action',
    );
    await page.getByRole('button', { name: 'Tape', exact: true }).click();
    const history = page.getByRole('region', { name: 'Run history', exact: true });
    const pass = history
      .getByRole('button', { name: /^Inspect run / })
      .filter({ hasText: 'completed' })
      .first();
    if (await pass.count()) {
      await pass.click();
      const evidence = page.getByRole('region', { name: 'Run evidence', exact: true });
      await until(
        async () => /valid samples/.test(await evidence.innerText()),
        'measured evidence rendered',
      );
      await evidence.scrollIntoViewIfNeeded();
      await shot(page, 'after-measured-evidence-desktop');
      await audit(page, 'measured evidence');
    }
    record('render matrix has no unhandled browser errors', { errors }, errors.length > 0);
  } finally {
    await context.close();
  }
}

async function operatorStates(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  const mutations = [];
  let seq = 80;
  const draft = {
    id: 'd-rendered-browser-fixture',
    catalog_id: 'redis_down',
    environment: 'demo',
    target: 'redis',
    duration_s: 15,
    params: {},
    hypothesis: { slo: { p95_ms: 2000, error_rate: 1 }, must: ['fail_closed_on_redis_loss'] },
    approved: true,
    source: 'manual',
    status: 'unsealed',
    cleanup_confirmed: false,
    unsealed_until: Date.now() / 1000 + 15,
    policy_decision: { allowed: true, reasons: [] },
  };
  page.on('pageerror', (error) => errors.push(error.message));
  await context.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    const respond = (body, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (request.method() !== 'GET') {
      mutations.push({ method: request.method(), path: pathname });
      if (pathname === '/api/agent/propose')
        return respond({
          draft: null,
          requested_provider: 'xai',
          actual_provider: 'stub',
          planner: 'stub',
          outcome: 'fallback_proposed',
          fallback_reason: 'provider_unavailable',
          explanation: 'Synthetic browser acceptance response. No provider was contacted.',
        });
      if (pathname === `/api/drafts/${draft.id}/reseal`) {
        draft.status = 'cleanup_pending';
        return respond({ draft, seal: null });
      }
      return respond({ detail: 'Browser rendering test blocks every other mutation.' }, 403);
    }
    if (pathname === '/api/active-run') return respond(draft);
    if (pathname === '/api/drafts') return respond([draft]);
    if (pathname === `/api/drafts/${draft.id}`) return respond(draft);
    if (pathname === `/api/drafts/${draft.id}/seal`) return respond(null);
    if (pathname === `/api/drafts/${draft.id}/events`) return respond([]);
    if (pathname === '/api/agent/trace')
      return respond({
        planner: 'stub',
        last_tool: 'propose_draft',
        trace: Array.from({ length: seq }, (_, index) => ({
          seq: index + 1,
          ts: Date.now() / 1000 - seq + index,
          tool: 'explain',
          result_summary: `Synthetic browser diagnostic entry ${index + 1}. Proposed changes do not inject faults.`,
        })),
      });
    return route.continue();
  });
  try {
    await page.goto(`${consoleUrl}/?view=tape&run=${draft.id}`);
    const active = page.getByRole('region', { name: 'Active run', exact: true });
    await active.waitFor();
    for (const width of [390, 720]) {
      await page.setViewportSize({ width, height: 420 });
      await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
      const abort = active.getByRole('button', { name: 'Abort / reseal active run', exact: true });
      const geometry = await abort.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return {
          top: box.top,
          bottom: box.bottom,
          viewport: innerHeight,
          unobscured: hit === element || element.contains(hit),
        };
      });
      record(
        `global abort remains visible in ${width}×420 after scrolling`,
        geometry,
        geometry.top < 0 || geometry.bottom > geometry.viewport || !geometry.unobscured,
      );
      await shot(page, `after-active-abort-${width}-short-mocked`);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => scrollTo(0, 0));
    await keyboardReach(
      page,
      active.getByRole('button', { name: 'Abort / reseal active run', exact: true }),
      'Global active abort',
    );
    await page.keyboard.press('Enter');
    await until(
      async () => /cleanup_pending/.test(await active.innerText()),
      'scoped abort shows pending cleanup',
    );
    await shot(page, 'after-cleanup-pending-mocked');
    assert.match(await active.innerText(), /not yet confirmed/i);
    assert(mutations.some((item) => item.path === `/api/drafts/${draft.id}/reseal`));
    record('mocked scoped abort preserves cleanup-pending ownership and uncertainty', {
      mutations,
    });
    draft.status = 'recovering';
    draft.cleanup_confirmed = true;
    await page.reload();
    await until(
      async () => /Recovery observations pending/i.test(await active.innerText()),
      'recovery remains explicit after cleanup confirmation',
    );
    await shot(page, 'after-recovery-pending-mocked');
    await audit(page, 'active recovery state');

    const drawer = page.getByRole('complementary', { name: 'Planner diagnostics', exact: true });
    if (await drawer.getByRole('button', { name: 'Open agent', exact: true }).count())
      await drawer.getByRole('button', { name: 'Open agent', exact: true }).click();
    const log = page.getByRole('region', { name: 'Planner log', exact: true });
    const follow = drawer.getByRole('checkbox', { name: 'Follow', exact: true });
    const height = drawer.getByRole('slider', { name: 'Agent log height', exact: true });
    await height.focus();
    await page.keyboard.press('End');
    const storedHeight = Number(await height.inputValue());
    await until(
      async () =>
        Number(await page.evaluate(() => localStorage.getItem('sealed-agent-height'))) ===
        storedHeight,
      'drawer height preference is persisted',
    );
    await page.reload();
    assert.equal(Number(await height.inputValue()), storedHeight);
    await page.setViewportSize({ width: 390, height: 420 });
    await until(
      async () => Number(await height.inputValue()) <= 252,
      'drawer restored height clamps to 60% of viewport',
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    await follow.check();
    await log.evaluate((element) => {
      element.scrollTop = 0;
      element.dispatchEvent(new Event('scroll', { bubbles: true }));
    });
    await until(async () => !(await follow.isChecked()), 'manual log scroll pauses Follow');
    const scrollBefore = await log.evaluate((element) => element.scrollTop);
    seq += 3;
    await until(
      async () => /3 unread entries/.test(await drawer.innerText()),
      'new diagnostics increment unread count while follow is paused',
      12000,
    );
    assert.equal(await log.evaluate((element) => element.scrollTop), scrollBefore);
    await follow.check();
    await until(
      async () => /\b0 unread entries/.test(await drawer.innerText()),
      'follow clears unread count',
    );
    assert(
      await log.evaluate(
        (element) => element.scrollHeight - element.scrollTop - element.clientHeight < 3,
      ),
    );
    await drawer.getByRole('button', { name: 'Collapse agent', exact: true }).click();
    await page.reload();
    assert(await drawer.getByRole('button', { name: 'Open agent', exact: true }).isVisible());
    await drawer.getByRole('button', { name: 'Open agent', exact: true }).click();
    record(
      'drawer restores collapse and bounded height, pauses follow on scroll and tracks unread entries',
      { restored_height: storedHeight, unread_added: 3 },
    );
    await drawer.getByRole('button', { name: 'Propose draft', exact: true }).click();
    await until(
      async () =>
        /Requested: xai/.test(await drawer.innerText()) &&
        /Used: stub/.test(await drawer.innerText()),
      'planner fallback shows requested and actual provider',
    );
    assert.match(await drawer.innerText(), /Fallback:/);
    await drawer.locator('.planner-result').scrollIntoViewIfNeeded();
    await shot(page, 'after-planner-fallback-mocked');
    await audit(page, 'planner fallback and diagnostics');
    await layout(page, 'planner fallback desktop');
    await page.setViewportSize({ width: 390, height: 844 });
    const provenance = drawer.locator('.planner-result');
    await provenance.scrollIntoViewIfNeeded();
    const visibleProvenance = await provenance.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const hit = document.elementFromPoint(
        box.left + box.width / 2,
        box.top + Math.min(12, box.height / 2),
      );
      return {
        top: box.top,
        bottom: box.bottom,
        viewport: innerHeight,
        unobscured: element === hit || element.contains(hit),
      };
    });
    record(
      'fallback provenance remains visible at390px',
      visibleProvenance,
      visibleProvenance.top < 0 ||
        visibleProvenance.bottom > visibleProvenance.viewport ||
        !visibleProvenance.unobscured,
    );
    await shot(page, 'after-planner-fallback-narrow-mocked');
    await layout(page, 'planner fallback narrow');
    await log.locator('.drawer-line').last().scrollIntoViewIfNeeded();
    const readableColors = await log.evaluate((element) => {
      const luminance = (value) => {
        const rgb = value
          .match(/[\d.]+/g)
          .slice(0, 3)
          .map(Number)
          .map((channel) => {
            const normalized = channel / 255;
            return normalized <= 0.04045
              ? normalized / 12.92
              : ((normalized + 0.055) / 1.055) ** 2.4;
          });
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
      };
      return [...element.querySelector('.drawer-line:last-child').children].map((child) => {
        let background;
        for (let ancestor = child; ancestor; ancestor = ancestor.parentElement) {
          const candidate = getComputedStyle(ancestor).backgroundColor;
          if (candidate.startsWith('rgb(')) {
            background = candidate;
            break;
          }
        }
        const color = getComputedStyle(child).color;
        if (!background) throw new Error('No opaque text background found');
        const light = luminance(color),
          dark = luminance(background);
        return {
          color,
          background,
          ratio: (Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05),
        };
      });
    });
    record(
      'diagnostic text colors satisfy4.5:1 normal text contrast',
      { colors: readableColors },
      readableColors.some((item) => item.ratio < 4.5),
    );
    record('fallback provenance explicitly identifies requested xai and actual stub', {
      source: 'intercepted browser response; no provider contacted',
    });
    record(
      'mocked operator states have no unhandled browser errors',
      { errors },
      errors.length > 0,
    );
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
});
try {
  await matrix(browser);
  if (mode === 'full') await operatorStates(browser);
} catch (error) {
  record('rendered acceptance execution', { error: error.stack }, true);
} finally {
  await browser.close();
  await fs.writeFile(
    path.join(root, mode === 'audit' ? 'docs/D_RENDER_AUDIT.json' : 'docs/D_BROWSER_RESULTS.json'),
    JSON.stringify(results, null, 2) + '\n',
  );
  if (failures.length) process.exitCode = 1;
}
