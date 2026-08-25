// Confirm-dialog stacking, exit-review, and the already-signed-in warning.
// Reuses the owner login created by 01-review-flow.mjs (only the first user in a fresh
// database becomes a site admin, and the fixture needs admin rights).
import { readFileSync } from 'fs';

import {
  BASE, SHOT, api, chromeArgs, loadChromium, login, makeChecker,
  newPage, openModal, signIn, waitForStable,
} from './helpers.mjs';

const chromium = loadChromium();
const { check, report } = makeChecker();

const LOGIN = process.argv[2] ||
  readFileSync(new URL('./.owner', import.meta.url), 'utf8').trim();

const token = await login(LOGIN);
const coll = (await api('/collection', { token })).json.find((c) => c.name.startsWith('Reviewed'));
if (!coll) throw new Error('no "Reviewed *" collection; run 01-review-flow.mjs first');

const browser = await chromium.launch(chromeArgs);

// ---------- 1. End a review from the modal: the confirm dialog must stack usably ----------
console.log('== Owner: End review via the confirm dialog ==');
{
  // Provision our own round rather than relying on 01 leaving one open -- it closes the
  // review it creates, as part of testing the end-of-review path.
  await api('/review', { method: 'POST', token, form: { collectionId: coll._id, duration: '9' } });

  const { ctx, page: p } = await newPage(browser);
  const errs = [];
  p.on('pageerror', (e) => { if (String(e.stack).includes('collection-review')) errs.push(e.message); });

  await signIn(p, token);
  await p.goto(`${BASE}/#collection/${coll._id}`, { waitUntil: 'networkidle' });
  await p.click('.g-collection-actions-button');
  await openModal(p, '.g-collection-manage-review', '.modal.in .g-review-open');

  const openRows = await p.$$('.g-review-row-open .g-review-close');
  check('an open round with an End button is listed', openRows.length >= 1, `rows=${openRows.length}`);
  if (!openRows.length) { await ctx.close(); throw new Error('no open round to end'); }

  // core's dialog.confirm renders into #g-dialog-container -- the same container the manage
  // modal occupies, so this is the Bootstrap-3 modal-stacking risk.
  await openRows[0].click();
  let confirmOk = false;
  try {
    await p.waitForSelector('#g-confirm-button', { timeout: 8000 });
    await waitForStable(p, '#g-confirm-button');
    confirmOk = true;
  } catch { /* reported below */ }
  check('confirm dialog appears and settles', confirmOk);
  await p.screenshot({ path: `${SHOT}/11-owner-confirm-end.png` });

  if (confirmOk) {
    const hit = await p.evaluate(() => {
      const btn = document.querySelector('#g-confirm-button');
      const r = btn.getBoundingClientRect();
      const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return {
        visible: r.width > 0 && r.height > 0,
        topMost: btn === at || btn.contains(at),
        opacity: getComputedStyle(btn.closest('.modal') || btn).opacity,
      };
    });
    check('confirm button is opaque, visible and not covered by the manage modal',
      hit.visible && hit.topMost && hit.opacity === '1', JSON.stringify(hit));

    await p.click('#g-confirm-button');
    await p.waitForFunction(() => document.querySelectorAll('.g-review-row-open').length === 0,
      { timeout: 12000 })
      .then(() => check('ending the review updates the table to no open rounds', true))
      .catch(() => check('ending the review updates the table to no open rounds', false,
        'table did not refresh'));
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

  const { ctx, page: p } = await newPage(browser);
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
  await p.waitForFunction(() =>
    getComputedStyle(document.querySelector('#g-app-header-container')).display !== 'none',
  { timeout: 15000 }).catch(() => {});
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

  const still = await api(`/collection/${coll._id}`);
  check('after exit, the review token no longer grants access',
    still.status === 401 || still.status === 403, String(still.status));
  await ctx.close();
}

// ---------- 3. Warning when somebody is already signed in ----------
console.log('\n== Reviewer: already-signed-in warning ==');
{
  const { ctx, page: p } = await newPage(browser);
  await signIn(p, token);
  await p.goto(`${BASE}/#review`, { waitUntil: 'networkidle' });
  await p.waitForSelector('.g-review-key', { timeout: 15000 });
  const warn = await p.waitForSelector('.g-review-warning', { timeout: 8000 }).catch(() => null);
  const warnText = warn ? (await warn.textContent()).trim() : null;
  check('signed-in visitor is warned that a review session replaces their sign-in',
    !!warnText && /currently signed in/i.test(warnText), String(warnText).slice(0, 80));
  await p.screenshot({ path: `${SHOT}/14-signed-in-warning.png` });
  await ctx.close();
}

await browser.close();
process.exit(report() ? 1 : 0);
