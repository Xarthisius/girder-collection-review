// Reviewer + owner happy path in a real browser.
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

let pass = 0, fail = 0;
const failures = [];
function check(name, ok, detail = '') {
  if (ok) { pass++; console.log(`  PASS  ${name}`); }
  else { fail++; failures.push(name + (detail ? ` -- ${detail}` : '')); console.log(`  FAIL  ${name} ${detail}`); }
}

// --- fixture setup over the REST API -----------------------------------------
async function api(path, { method = 'GET', token, form } = {}) {
  const headers = {};
  if (token) headers['Girder-Token'] = token;
  let body;
  if (form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    body = new URLSearchParams(form).toString();
  }
  const r = await fetch(`${API}${path}`, { method, headers, body });
  const text = await r.text();
  let json; try { json = JSON.parse(text); } catch { json = text; }
  return { status: r.status, json };
}

async function setup() {
  const stamp = Date.now().toString(36);
  const login = `owner${stamp}`.slice(0, 20);
  let r = await api('/user', { method: 'POST', form: {
    login, password: 'password123', firstName: 'Own', lastName: 'Er',
    email: `${login}@example.com` } });
  if (r.status !== 200) throw new Error('user create failed: ' + JSON.stringify(r.json));
  const token = r.json.authToken.token;

  r = await api('/collection', { method: 'POST', token, form: {
    name: `Reviewed Study ${stamp}`, description: 'A curated study', public: 'false' } });
  const coll = r.json._id;
  r = await api('/folder', { method: 'POST', token, form: {
    parentType: 'collection', parentId: coll, name: 'data', public: 'false' } });
  const f1 = r.json._id;
  r = await api('/folder', { method: 'POST', token, form: {
    parentType: 'folder', parentId: f1, name: 'raw', public: 'false' } });
  const f2 = r.json._id;
  r = await api('/item', { method: 'POST', token, form: { folderId: f2, name: 'sample.csv' } });
  const item = r.json._id;

  // upload a small file so downloads and the file list have something real
  const content = 'a,b\n1,2\n';
  r = await api('/file', { method: 'POST', token, form: {
    parentType: 'item', parentId: item, name: 'sample.csv', size: String(content.length) } });
  const uploadId = r.json._id;
  await fetch(`${API}/file/chunk?uploadId=${uploadId}&offset=0`, {
    method: 'POST',
    headers: { 'Girder-Token': token, 'Content-Type': 'application/octet-stream' },
    body: content });

  return { login, token, coll, f1, f2, item, stamp };
}

// --- helpers -----------------------------------------------------------------
const chromeArgs = { executablePath: CHROME, args: ['--no-sandbox'] };

const KNOWN_NOISE = [
  /reading 'History'/,                 // google_analytics plugin, fires on every page
  /notifications\/me\?token=null/,     // core EventStream handshake with no user
  /WebSocket connection to/,
  /status of 400/,                     // our own deliberate bad-key submission
  /401 \(Unauthorized\)|You must be logged in/,
];
function watch(page, sink) {
  const add = (s) => { if (!KNOWN_NOISE.some((re) => re.test(s))) sink.push(s); };
  page.on('console', (m) => { if (m.type() === 'error') add(`console.error: ${m.text()}`); });
  page.on('pageerror', (e) => add(`pageerror: ${e.message} @ ${String(e.stack).split('\n')[1] || ''}`));
  // Anything thrown from our own bundle is never noise.
  page.on('pageerror', (e) => {
    if (String(e.stack).includes('collection-review')) sink.push(`PLUGIN pageerror: ${e.message}`);
  });
}

/** Are the three chrome containers hidden and the body edge-to-edge? */
function layoutState(page) {
  return page.evaluate(() => {
    const vis = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return 'missing';
      return getComputedStyle(el).display === 'none' ? 'hidden' : 'visible';
    };
    const body = document.querySelector('#g-app-body-container');
    return {
      header: vis('#g-app-header-container'),
      nav: vis('#g-global-nav-container'),
      footer: vis('#g-app-footer-container'),
      bodyClass: body ? body.className : null,
      loginModalVisible: !!document.querySelector('#g-dialog-container.in, .modal.in #g-login-form'),
    };
  });
}

async function run() {
  const fx = await setup();
  console.log(`fixture: collection=${fx.coll} owner=${fx.login}\n`);
  // Hand the owner login to 02-modal-and-exit.mjs: only the first user created in a fresh
  // database becomes a site admin, so the two scripts must share one.
  const { writeFileSync } = await import('fs');
  writeFileSync(new URL('./.owner', import.meta.url), fx.login);
  const browser = await chromium.launch(chromeArgs);

  // ========================= OWNER SIDE =========================
  console.log('== Owner: manage-review modal ==');
  const ownerCtx = await browser.newContext({ viewport: { width: 1400, height: 950 } });
  const owner = await ownerCtx.newPage();
  const ownerLogs = [];
  watch(owner, ownerLogs);

  // adopt the owner token the way the app does, before the app boots
  await owner.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
  await owner.evaluate((t) => window.localStorage.setItem('girderToken', t), fx.token);
  await owner.goto(`${BASE}/#collection/${fx.coll}`, { waitUntil: 'networkidle' });
  await owner.waitForSelector('.g-collection-actions-button', { timeout: 15000 });

  await owner.click('.g-collection-actions-button');
  const manageVisible = await owner.isVisible('.g-collection-manage-review');
  check('"Manage review" appears in the collection Actions menu for an ADMIN', manageVisible);

  await owner.click('.g-collection-manage-review');
  // THE risk: .girderModal() is a jQuery plugin core registers on its own jQuery instance
  let modalOk = false;
  try {
    await owner.waitForSelector('.modal.in .g-review-open', { timeout: 8000 });
    modalOk = true;
  } catch (e) { /* captured below */ }
  check('manage modal opens (girderModal reachable from a plugin bundle)', modalOk,
    modalOk ? '' : ownerLogs.slice(-3).join(' | '));

  await owner.screenshot({ path: `${SHOT}/01-owner-manage-modal.png` });

  let key = null;
  if (modalOk) {
    const emptyMsg = await owner.textContent('.g-review-empty').catch(() => null);
    check('modal reports no prior review rounds', (emptyMsg || '').includes('never been under review'));

    await owner.fill('.g-review-duration', '7');
    await owner.click('.g-review-open');
    await owner.waitForSelector('.g-review-key-value', { timeout: 10000 });
    key = await owner.inputValue('.g-review-key-value');
    check('opening a review surfaces the access key once', !!key && key.length === 40, `len=${key && key.length}`);

    const rows = await owner.$$eval('.g-review-table tbody tr',
      (trs) => trs.map((tr) => tr.className.trim()));
    check('review table now lists one open round', rows.length === 1 && rows[0].includes('g-review-row-open'),
      JSON.stringify(rows));

    await owner.screenshot({ path: `${SHOT}/02-owner-key-shown.png` });

    // copy button: selects the field (execCommand may be a no-op headless)
    await owner.click('.g-review-copy-key');
    const selected = await owner.evaluate(() => {
      const el = document.querySelector('.g-review-key-value');
      return el.selectionStart === 0 && el.selectionEnd === el.value.length;
    });
    check('Copy button selects the key field', selected);
  }

  check('no unexpected JS errors on the owner page', ownerLogs.length === 0, ownerLogs.slice(0, 3).join(' | '));

  if (!key) { await browser.close(); return { pass, fail, failures }; }

  // ========================= REVIEWER SIDE =========================
  console.log('\n== Reviewer: cold load of #review (empty layout) ==');
  const revCtx = await browser.newContext({ viewport: { width: 1400, height: 950 }, acceptDownloads: true });
  const rev = await revCtx.newPage();
  const revLogs = [];
  watch(rev, revLogs);

  // Cold load straight to #review -- the case where Layout.EMPTY has to hide the chrome
  // via _defaultLayout.hide() during the very first transition.
  await rev.goto(`${BASE}/#review`, { waitUntil: 'networkidle' });
  await rev.waitForSelector('.g-review-key', { timeout: 15000 });

  let st = await layoutState(rev);
  check('cold load: header hidden', st.header === 'hidden', st.header);
  check('cold load: left navbar hidden', st.nav === 'hidden', st.nav);
  check('cold load: footer hidden', st.footer === 'hidden', st.footer);
  check('cold load: body has g-empty-layout, not g-default-layout',
    st.bodyClass.includes('g-empty-layout') && !st.bodyClass.includes('g-default-layout'), st.bodyClass);
  await rev.screenshot({ path: `${SHOT}/03-reviewer-key-entry.png` });

  // wrong key -> inline error, no login modal
  await rev.fill('.g-review-key', 'definitely-not-a-real-key');
  await rev.click('.g-review-submit');
  await rev.waitForFunction(() => {
    const e = document.querySelector('.g-review-error');
    return e && e.textContent.trim().length > 0;
  }, { timeout: 10000 });
  const errText = await rev.textContent('.g-review-error');
  check('wrong key shows an inline error', /invalid|expired/i.test(errText), errText.trim());
  st = await layoutState(rev);
  check('wrong key does NOT pop the core login modal', st.loginModalVisible === false);
  check('wrong key leaves the chrome hidden', st.header === 'hidden' && st.nav === 'hidden');
  await rev.screenshot({ path: `${SHOT}/04-reviewer-bad-key.png` });

  // correct key
  console.log('\n== Reviewer: browsing ==');
  await rev.fill('.g-review-key', key);
  await rev.click('.g-review-submit');
  await rev.waitForSelector('.g-review-banner', { timeout: 15000 });
  await rev.waitForSelector('.g-hierarchy-widget', { timeout: 15000 });

  check('correct key lands on #review/<collectionId>', /#review\/[0-9a-f]{24}$/.test(rev.url()), rev.url());
  const banner = await rev.textContent('.g-review-banner-name');
  check('banner names the collection under review', banner.includes('Reviewed Study'), banner);
  st = await layoutState(rev);
  check('browse page: chrome still hidden', st.header === 'hidden' && st.nav === 'hidden' && st.footer === 'hidden',
    JSON.stringify(st));

  await rev.waitForSelector('.g-folder-list-entry .g-folder-list-link', { timeout: 10000 });
  const topFolders = await rev.$$eval('.g-folder-list-entry .g-folder-list-link',
    (els) => els.map((e) => e.textContent.trim()));
  check('hierarchy lists the top folder', topFolders.includes('data'), JSON.stringify(topFolders));
  await rev.screenshot({ path: `${SHOT}/05-reviewer-hierarchy.png` });

  // mutation affordances must be absent at READ
  const affordances = await rev.evaluate(() => {
    const q = (s) => !!document.querySelector(s);
    return {
      upload: q('.g-upload-here-button'),
      accessCtl: q('.g-folder-access-button, .g-collection-access-button'),
      createFolder: q('.g-create-subfolder'),
      createItem: q('.g-create-item'),
      editFolder: q('.g-edit-folder'),
      deleteFolder: q('.g-delete-folder'),
      checkboxes: q('.g-list-checkbox, .g-select-all'),
      checkedActions: q('.g-checked-actions-button'),
      downloadFolder: q('.g-download-folder'),
    };
  });
  const mutators = Object.entries(affordances).filter(([k]) => k !== 'downloadFolder');
  check('no mutation affordances rendered at READ',
    mutators.every(([, v]) => v === false), JSON.stringify(affordances));
  check('"Download collection" IS still present (showActions: true earns its keep)',
    affordances.downloadFolder === true);

  // descend, and confirm the hash is not rewritten (routing: false)
  const urlBefore = rev.url();
  await rev.click('.g-folder-list-link >> nth=0');
  await rev.waitForFunction(() => {
    const bc = document.querySelector('.g-hierarchy-breadcrumb-bar');
    return bc && bc.textContent.includes('data');
  }, { timeout: 10000 });
  check('descending into a folder works', true);
  check('descending does NOT rewrite the URL hash (routing: false)', rev.url() === urlBefore,
    `${urlBefore} -> ${rev.url()}`);

  // descend again to the item level
  await rev.click('.g-folder-list-link >> nth=0');
  await rev.waitForSelector('.g-item-list-link', { timeout: 10000 });
  const items = await rev.$$eval('.g-item-list-link', (els) => els.map((e) => e.textContent.trim()));
  check('item list renders inside the nested folder', items.includes('sample.csv'), JSON.stringify(items));

  // ---- item click must NOT restore the chrome (the onItemClick fix) ----
  console.log('\n== Reviewer: item detail ==');
  await rev.click('.g-item-list-link >> nth=0');
  await rev.waitForSelector('.g-review-item', { timeout: 10000 });
  st = await layoutState(rev);
  check('clicking an item keeps the chrome hidden (onItemClick override)',
    st.header === 'hidden' && st.nav === 'hidden', JSON.stringify(st));
  check('item click does not navigate to the core item route', !rev.url().includes('#item/'), rev.url());
  await rev.waitForSelector('.g-file-list-link', { timeout: 10000 });
  const fileRows = await rev.$$eval('.g-file-list-link', (els) => els.map((e) => e.textContent.trim()));
  check('FileListWidget renders the item files', fileRows.length >= 1, JSON.stringify(fileRows));
  const itemMutators = await rev.evaluate(() => ({
    addMeta: !!document.querySelector('.g-add-json-metadata, .g-add-simple-metadata'),
    editFile: !!document.querySelector('.g-update-info, .g-update-contents'),
    deleteFile: !!document.querySelector('.g-delete-file'),
  }));
  check('item detail exposes no edit affordances at READ',
    Object.values(itemMutators).every((v) => v === false), JSON.stringify(itemMutators));
  await rev.screenshot({ path: `${SHOT}/06-reviewer-item.png` });

  // ---- download via a real browser navigation (the cookie path) ----
  const dl = await Promise.all([
    rev.waitForEvent('download', { timeout: 20000 }),
    rev.click('.g-file-list-link >> nth=0'),
  ]).then((r) => r[0]).catch((e) => null);
  if (dl) {
    const p = await dl.path();
    const fs = await import('fs');
    const bytes = p ? fs.statSync(p).size : -1;
    check('file downloads from a browser navigation (auth cookie path)', bytes === 8, `bytes=${bytes}`);
  } else {
    check('file downloads from a browser navigation (auth cookie path)', false, 'no download event');
  }

  await rev.click('.g-review-back-to-hierarchy');
  await rev.waitForSelector('.g-hierarchy-widget', { timeout: 10000 });
  check('"Back to collection" returns to the hierarchy', await rev.isVisible('.g-hierarchy-widget'));

  // ---- refresh: sessionStorage must carry the token ----
  console.log('\n== Reviewer: reload, exit, ended ==');
  await rev.reload({ waitUntil: 'networkidle' });
  let survived = true;
  try { await rev.waitForSelector('.g-review-banner', { timeout: 12000 }); }
  catch { survived = false; }
  check('session survives a page refresh (sessionStorage)', survived);
  if (survived) {
    st = await layoutState(rev);
    check('after refresh the chrome is still hidden', st.header === 'hidden' && st.nav === 'hidden',
      JSON.stringify(st));
  }

  check('no unexpected JS errors on the reviewer pages', revLogs.length === 0, revLogs.slice(0, 4).join(' | '));

  // ---- owner ends the review -> reviewer page reports it ----
  const reviewList = await api(`/review?collectionId=${fx.coll}`, { token: fx.token });
  const reviewId = reviewList.json[0]._id;
  await api(`/review/${reviewId}`, { method: 'DELETE', token: fx.token });

  // force the poll rather than waiting 60s
  const ended = await rev.evaluate(async () => {
    const r = await fetch('/api/v1/review/session', {
      headers: { 'Girder-Token': window.sessionStorage.getItem('girderCollectionReviewToken') || '' } });
    return (await r.json()).review;
  });
  check('after close, GET /review/session reports no session', ended === null, JSON.stringify(ended));

  await rev.goto('about:blank');
  await rev.goto(`${BASE}/#review/${fx.coll}`, { waitUntil: 'networkidle' });
  await rev.waitForSelector('.g-review-notice, .g-review-card-title', { timeout: 15000 });
  const endedText = await rev.textContent('body');
  check('revisiting a closed review shows an end-of-review message',
    /review has ended|access key/i.test(endedText));
  st = await layoutState(rev);
  check('end-of-review page keeps the empty layout', st.header === 'hidden' && st.nav === 'hidden',
    JSON.stringify(st));
  await rev.screenshot({ path: `${SHOT}/07-reviewer-ended.png` });

  // ---- navigating away restores the chrome ----
  await rev.goto(`${BASE}/#collections`, { waitUntil: 'networkidle' });
  await rev.waitForTimeout(1200);
  st = await layoutState(rev);
  check('navigating away from a review page restores the chrome',
    st.header === 'visible' && st.nav === 'visible' && st.bodyClass.includes('g-default-layout'),
    JSON.stringify(st));
  await rev.screenshot({ path: `${SHOT}/08-chrome-restored.png` });

  await browser.close();
  return { pass, fail, failures };
}

run().then(({ pass, fail, failures }) => {
  console.log(`\n================ ${pass} passed, ${fail} failed ================`);
  if (failures.length) { console.log('FAILURES:'); failures.forEach((f) => console.log('  - ' + f)); }
  process.exit(fail ? 1 : 0);
}).catch((e) => { console.error('HARNESS ERROR:', e); process.exit(2); });
