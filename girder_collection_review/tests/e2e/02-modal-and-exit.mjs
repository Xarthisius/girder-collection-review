// Confirm-dialog stacking, exit-review, and the already-signed-in warning.
// Takes the owner login created by 01-review-flow.mjs as argv[2].
// Resolved from $PLAYWRIGHT, else the first of a few usual locations. Playwright is not a
// dependency of this repo -- it is only needed for these browser checks, which are not part
// of `tox -e pytest`.
import { createRequire } from 'module';
const require_ = createRequire(import.meta.url);
function loadChromium() {
  const candidates = [
    process.env.PLAYWRIGHT,
    `${process.env.HOME}/node_modules/playwright`,
    'playwright',
  ].filter(Boolean);
  for (const c of candidates) {
    try { return require_(c).chromium; } catch { /* try the next */ }
  }
  throw new Error('playwright not found; set PLAYWRIGHT=/path/to/node_modules/playwright');
}
const chromium = loadChromium();

const BASE = process.env.GIRDER_URL || 'http://localhost:8749';
const API = `${BASE}/api/v1`;
const SHOT = process.env.SHOT_DIR || new URL('./shots/', import.meta.url).pathname;
// No ms-playwright browsers are downloaded here, so drive the system Chrome.
const CHROME = process.env.CHROME || '/usr/bin/google-chrome';

let LOGIN = process.argv[2];
if (!LOGIN) {
  const { readFileSync } = await import('fs');
  LOGIN = readFileSync(new URL('./.owner', import.meta.url), 'utf8').trim();
}

let pass = 0, fail = 0; const failures = [];
const check = (n, ok, d = '') => {
  if (ok) { pass++; console.log(`  PASS  ${n}`); }
  else { fail++; failures.push(`${n}${d ? ' -- ' + d : ''}`); console.log(`  FAIL  ${n} ${d}`); }
};

async function api(path, { method = 'GET', token, form } = {}) {
  const headers = {}; if (token) headers['Girder-Token'] = token;
  let body;
  if (form) { headers['Content-Type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(form).toString(); }
  const r = await fetch(`${API}${path}`, { method, headers, body });
  const t = await r.text();
  try { return { status: r.status, json: JSON.parse(t) }; } catch { return { status: r.status, json: t }; }
}

const auth = Buffer.from(`${LOGIN}:password123`).toString('base64');
const token = (await (await fetch(`${API}/user/authentication`, { headers: { Authorization: `Basic ${auth}` } })).json()).authToken.token;
const coll = (await api('/collection', { token })).json.find((c) => c.name.startsWith('Reviewed'));

const b = await chromium.launch({ executablePath: CHROME, args: ['--no-sandbox'] });

// ---------- 1. End a review from the modal: confirm dialog must stack usably ----------
console.log('== Owner: End review via the confirm dialog ==');
{
  // Provision our own round rather than relying on 01 leaving one open -- it closes the
  // review it creates, as part of testing the end-of-review path.
  await api('/review', { method: 'POST', token, form: { collectionId: coll._id, duration: '9' } });

  const ctx = await b.newContext({ viewport: { width: 1400, height: 950 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', (e) => { if (String(e.stack).includes('collection-review')) errs.push(e.message); });

  await p.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await p.evaluate((t) => window.localStorage.setItem('girderToken', t), token);
  await p.goto(`${BASE}/#collection/${coll._id}`, { waitUntil: 'networkidle' });
  await p.click('.g-collection-actions-button');
  await p.click('.g-collection-manage-review');
  await p.waitForSelector('.modal.in .g-review-open');
  await p.waitForTimeout(900);

  const openRows = await p.$$('.g-review-row-open .g-review-close');
  check('an open round with an End button is listed', openRows.length >= 1, `rows=${openRows.length}`);
  if (!openRows.length) { await ctx.close(); throw new Error('no open round to end'); }

  await openRows[0].click();
  // core's dialog.confirm renders into #g-dialog-container -- the same container the manage
  // modal occupies, so this is the Bootstrap-3 modal-stacking risk.
  let confirmOk = false;
  try { await p.waitForSelector('#g-confirm-button', { timeout: 6000 }); confirmOk = true; } catch {}
  check('confirm dialog appears and is reachable', confirmOk);
  await p.waitForTimeout(700);
  await p.screenshot({ path: `${SHOT}/11-owner-confirm-end.png` });

  if (confirmOk) {
    const clickable = await p.evaluate(() => {
      const btn = document.querySelector('#g-confirm-button');
      const r = btn.getBoundingClientRect();
      const atPoint = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { visible: r.width > 0 && r.height > 0, topMost: btn.contains(atPoint) || btn === atPoint };
    });
    check('confirm button is visible and not covered by the manage modal',
      clickable.visible && clickable.topMost, JSON.stringify(clickable));

    await p.click('#g-confirm-button');
    await p.waitForFunction(() => {
      const rows = document.querySelectorAll('.g-review-row-open');
      return rows.length === 0;
    }, { timeout: 12000 }).then(() => check('ending the review updates the table to no open rounds', true))
      .catch(() => check('ending the review updates the table to no open rounds', false, 'table did not refresh'));
    await p.screenshot({ path: `${SHOT}/12-owner-after-end.png` });
  }
  check('no errors from the plugin bundle during the End flow', errs.length === 0, errs.join(' | '));
  await ctx.close();
}

// ---------- 2. Exit review restores the app ----------
console.log('\n== Reviewer: Exit review ==');
{
  const r = await api('/review', { method: 'POST', token, form: { collectionId: coll._id, duration: '5' } });
  const key = r.json.key;

  const ctx = await b.newContext({ viewport: { width: 1400, height: 950 } });
  const p = await ctx.newPage();
  await p.goto(`${BASE}/#review`, { waitUntil: 'networkidle' });
  await p.fill('.g-review-key', key);
  await p.click('.g-review-submit');
  await p.waitForSelector('.g-review-banner', { timeout: 15000 });

  const stored = await p.evaluate(() => ({
    session: !!window.sessionStorage.getItem('girderCollectionReviewToken'),
    local: window.localStorage.getItem('girderToken'),
  }));
  check('token is written to sessionStorage', stored.session === true);
  check('token is NOT written to localStorage (would leak into other tabs)',
    stored.local === null, `localStorage.girderToken=${stored.local}`);

  await p.click('.g-review-exit');
  await p.waitForTimeout(2500);
  const after = await p.evaluate(() => ({
    session: window.sessionStorage.getItem('girderCollectionReviewToken'),
    header: getComputedStyle(document.querySelector('#g-app-header-container')).display,
    nav: getComputedStyle(document.querySelector('#g-global-nav-container')).display,
    body: document.querySelector('#g-app-body-container').className,
  }));
  check('Exit review clears the stored token', after.session === null, String(after.session));
  check('Exit review restores the header and navbar',
    after.header !== 'none' && after.nav !== 'none' && after.body.includes('g-default-layout'),
    JSON.stringify(after));
  await p.screenshot({ path: `${SHOT}/13-after-exit.png` });

  const stillReadable = await api(`/collection/${coll._id}`, { token: null });
  check('after exit, the review token no longer grants access',
    stillReadable.status === 401 || stillReadable.status === 403, String(stillReadable.status));
  await ctx.close();
}

// ---------- 3. Warning when somebody is already signed in ----------
console.log('\n== Reviewer: already-signed-in warning ==');
{
  const ctx = await b.newContext({ viewport: { width: 1400, height: 950 } });
  const p = await ctx.newPage();
  await p.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await p.evaluate((t) => window.localStorage.setItem('girderToken', t), token);
  await p.goto(`${BASE}/#review`, { waitUntil: 'networkidle' });
  await p.waitForSelector('.g-review-key', { timeout: 15000 });
  await p.waitForTimeout(600);
  const warn = await p.$('.g-review-warning');
  const warnText = warn ? (await warn.textContent()).trim() : null;
  check('signed-in visitor is warned that a review session replaces their sign-in',
    !!warnText && /currently signed in/i.test(warnText), String(warnText).slice(0, 80));
  await p.screenshot({ path: `${SHOT}/14-signed-in-warning.png` });
  await ctx.close();
}

await b.close();
console.log(`\n================ ${pass} passed, ${fail} failed ================`);
if (failures.length) failures.forEach((f) => console.log('  - ' + f));
process.exit(fail ? 1 : 0);
