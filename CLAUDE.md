# CLAUDE.md — girder-collection-review

Handoff notes for this Girder 5 plugin. Covers only this repo and the work still
outstanding; repo-wide Girder architecture lives in the girder checkout's own
`CLAUDE.md` (`/home/xarth/codes/wholetale-ng/girder/CLAUDE.md`).

Original design plan, with the exploration that produced it:
`/home/xarth/.claude/plans/i-d-like-to-write-sunny-liskov.md`

## Layout on this machine

```
/home/xarth/codes/wholetale-ng/
  girder/                                  # Girder 5 checkout
    plugins/collection_review -> ../../girder-collection-review   # symlink
  girder-collection-review/                # THIS REPO
  girder-jsonforms/                        # sibling plugin repo this one is modelled on
```

The symlink mirrors how `plugins/jsonforms` is wired. It matters for two things:
`.circleci/build_plugins.py` in the girder checkout discovers the web client through it, and
the JS/pug/stylus linters (configured in the girder root `package.json`, not here) can only
run through it.

## Status

| Area | State |
|---|---|
| Server (model, provisioning, REST, guard, ACL sync) | **Done.** 36/36 tests pass, 85.6% line coverage. |
| Web client (routes, 4 views, templates, styles) | **Done.** 47 browser checks pass in real Chrome (`tests/e2e/run.sh`). |
| `tox -e lint` (ruff) / `tox -e pytest` | Both green. |
| JS lint (eslint, pug-lint, stylelint) | Clean — but only runnable via the girder symlink. |
| Server end-to-end vs a live `girder serve` | Verified (see "What was actually verified"). |
| Browser / visual verification | Done — see `girder_collection_review/tests/e2e/`. |
| Git | `main` branch, one initial commit. No remote configured. |

What it does: a collection owner opens **Actions → Manage review**, gets a one-shot access
key, hands it to a journal editor; a reviewer pastes it at `#review` and gets the collection
hierarchy on a navigation-free page, read only, with downloads working; the owner ends the
review and access dies immediately.

Three test layers: `tox -e pytest` (36 server tests), `tests/e2e/run.sh` (47 browser checks),
and a `girder serve` + curl pass recorded under "What was actually verified".

## Commands

```bash
# from this repo
tox -e lint      # ruff check .
tox -e pytest    # pytest, coverage.xml, 4-way xdist; builds a wheel and pulls girder from PyPI
tox -e format    # ruff format . && ruff check --fix .

# build the web client (required before starting Girder: registerPluginStaticContent
# md5s the files in web_client/dist/ at plugin load time, so a missing dist/ 500s startup)
cd girder_collection_review/web_client && npm ci && npm run build

# install into the girder dev venv, for running an actual server
/home/xarth/codes/wholetale-ng/girder/venv/bin/pip install -e . --no-deps

# JS lint — must run from the girder checkout, which owns the configs
cd /home/xarth/codes/wholetale-ng/girder
npx eslint --no-cache "plugins/collection_review/girder_collection_review/web_client/**/*.js"
npx pug-lint plugins/collection_review/girder_collection_review/web_client/templates/
npx stylelint "plugins/collection_review/girder_collection_review/web_client/stylesheets/*.styl"

# a server on a scratch database (never point this at the dev `girder` db — it creates
# throwaway users and collections)
/home/xarth/codes/wholetale-ng/girder/venv/bin/girder serve \
    -p 8749 -d mongodb://localhost:27017/girder_review_e2e --with-temp-assetstore
```

**Environment gotchas**

- `tox -e pytest` builds a wheel and resolves `girder>=5.0.6` from PyPI into `.tox/pytest`
  (it picked up 5.0.16). It therefore tests against a *released* Girder, not the local
  checkout. To test against the working tree, run pytest directly with the girder venv:
  `/home/xarth/codes/wholetale-ng/girder/venv/bin/python -m pytest -q -p no:celery`.
- **`-p no:celery` is required when using the girder venv.** The `pytest-celery` installed
  there imports `pkg_resources`, which no longer exists on that Python, so pytest cannot
  even start collection. `tox -e pytest` has its own env and does not need the flag.
- MongoDB is expected on `localhost:27017`.
- `pkill -f "girder serve -p 8749"` kills the calling shell too (the pattern matches the
  shell's own argv). Match on the PID instead.
- `node_modules/lightningcss-linux-x64-musl/` is **root-owned** from an earlier npm run, so
  `rm -rf node_modules` fails partway and leaves a broken tree. `npm install` recovers it.
  A clean `npm ci` needs that directory removed with sudo first.

## Repo layout

```
girder-collection-review/
  setup.py  tox.ini  ruff.toml  requirements-dev.txt  .coveragerc  MANIFEST.in
  README.md  CLAUDE.md  LICENSE  .gitignore
  .github/workflows/build-test.yaml
  girder_collection_review/
    __init__.py            # CollectionReviewPlugin.load() + the two move hooks
    constants.py           # PLUGIN_NAME, ReviewStatus, PluginSettings, reviewer identity consts
    settings.py            # collection_review.default_duration (@validator/@default)
    rest.py                # class Review(Resource) -> /api/v1/review
    models/review.py       # plain Model, Mongo collection 'collection_review'
    lib/provisioning.py    # openReview / closeReview / ACL grant+revoke / syncMovedFolder
    lib/guard.py           # auth.user.get read-only guard
    tests/
      conftest.py                # reviewed_collection / review / review_token fixtures + helpers
      test_open_review.py        # authorization, one-shot key, reviewer identity, duration
      test_reviewer_access.py    # what a session can read; session establishment
      test_read_only_guard.py    # every write refused; guard invisible to normal users
      test_acl_propagation.py    # create / move in / move out / rename / resource-move
      test_close_review.py       # revocation, idempotency, expiry, orphans
      e2e/                       # real-Chrome checks; NOT part of tox -e pytest
        run.sh  01-review-flow.mjs  02-modal-and-exit.mjs  README.md
    web_client/
      main.js routes.js session.js
      views/{CollectionView,ReviewManageWidget,ReviewLoginView,ReviewBrowseView,ReviewItemView}.js
      templates/*.pug  stylesheets/review.styl
      vite.config.ts  package.json  package-lock.json  tsconfig.json  vite-env.d.ts
```

### Divergences from girder-jsonforms (all deliberate)

1. **`[pytest]`, not `[tool:pytest]`, in `tox.ini`.** pytest only reads `[tool:pytest]` from
   `setup.cfg`; in a tox.ini that section is silently ignored, which is why jsonforms'
   `testpaths = test` has no effect despite pointing at a directory that does not exist.
   Here it is `[pytest]` with a real `testpaths`.
2. **`--strict-markers`, not `--strict`.** `--strict` was removed in pytest 8; the venv here
   has pytest 9.
3. **`quote-style = "single"` and `line-length = 100` in `ruff.toml`.** The Python follows
   Girder core's convention (core enforces single quotes with `double-quote-string-fixer`)
   and core's 100-column limit. Neither is checked by the shared
   `select = ["E4","E7","E9","F"]` list, so both only affect `ruff format`. The tree **has**
   been run through `ruff format` once and is clean; note that it still applies black-style
   call wrapping, which is not how Girder core hand-wraps arguments, so run `tox -e format`
   on new code rather than hand-wrapping it. Flip the quote style and the code together if
   you would rather match jsonforms' double quotes.
4. **No `@girder/core` npm dependency.** jsonforms declares `"@girder/core": "*"`, but the
   newest release on npm is **3.2.16** — Girder 3 — so those types describe a different
   major version. A `file:` path to the local `girder/web` would only resolve when the two
   repos sit side by side. Nothing typechecks this package (vite builds plain `.js`), so
   `vite-env.d.ts` declares the `girder` global locally instead. The runtime contract is
   unchanged: core is never bundled, it is read off `window`.
5. **No JS lint step in CI.** Those linters live in the girder root `package.json`. Adding
   eslint/pug-lint/stylelint configs to `web_client/` would let CI cover them.

## Invariants — do not "simplify" these

Each looks like removable complexity and is not. Breaking any one silently weakens the
security of the feature.

1. **`lib/guard.py` is what makes a review session read-only — not the token scope.**
   `PUT /collection/:id` is declared `@access.user(scope=TokenScope.DATA_READ)`
   (`girder/api/v1/collection.py:170`), and third-party plugins are worse: in this
   deployment `girder-jsonforms/girder_jsonforms/rest/deposition.py:554` performs DataCite
   registration under `scope=DATA_READ`. A `DATA_READ` token is therefore strictly *more*
   capable than an anonymous visitor.
2. **The guard must deny at most once per request.** `_handleAccessException`
   (`girder/api/rest.py:552`) calls `getCurrentUser()` to choose 401 vs 403, which re-fires
   `auth.user.get` from *inside* the endpoint's `except` block. A second raise there escapes
   the `try` entirely and surfaces as an unhandled exception instead of a 403. Hence the
   `cherrypy.request.girderCollectionReviewDenied` latch.
3. **`onResourcesMoveBefore` must keep its `@access.public` decorator.** `handleRoute`
   passes `Resource._defaultAccess` as the `pre` callback for every `rest.*.before` handler
   (`girder/api/rest.py:977`, `:1262`), and that helper calls `requireAdmin` on any handler
   without an `accessLevel` attribute. Without the decorator, merely *binding* here makes
   `PUT /resource/move` admin-only for the whole site.
   `test_resource_move_still_works_for_non_admins` guards this.
4. **Closing a review must remove the API key, not just flip `status`.**
   `POST /api_key/token` is `@access.public` and never sees the review document, so a
   reviewer holding the key could keep minting tokens for up to `COOKIE_LIFETIME`
   (180 days). `ApiKey().remove` triggers `Token().clearForApiKey`, which is what actually
   kills live sessions. `tokenDuration` is also set from the review duration as a second cap.
5. **Do not switch reviewer creation to `User().createUser()`.** It sends
   verification/approval mail *synchronously* with no exception handling
   (`girder/utility/mail_utils.py:169-179`), so it would block on SMTP to a non-routable
   domain and can raise *after* the row is written. It also fires
   `model.user.save.created`, whose core handler creates a **public** "Public" home folder
   that would appear in everyone's `/resource/search`. `save(validate=True,
   triggerEvents=False)` validates fully and suppresses both.
6. **The reviewer email domain must stay non-routable (`review.invalid`).**
   `PUT /user/password/temporary` is `@access.public` and works on passwordless accounts, so
   whoever controls a routable reviewer mailbox could upgrade the throwaway into a full
   `USER_AUTH` session.
7. **Revocation is global by `userId`, not scoped to the collection subtree.** A folder
   created during a review and later moved out keeps the reviewer's ACL entry, and a
   `baseParentId` query would never find it again.
8. **ACL changes use bulk `update_many`, not a `setUserAccess` loop.**
   `AccessControlledModel._saveAcl` rewrites the *entire document* on every call
   (`girder/models/model_base.py:982`), so a per-folder loop is a lost-update race against a
   concurrent rename plus one `model.folder.save` event per folder.
9. **`Review` is a plain `Model`, not `AccessControlledModel`,** and cannot be used with
   `modelParam` — `autoDescribeRoute` calls `model.load(id, force=True)` for `force=True`
   params, and plain `Model.load` has no `force` argument. `rest.py` loads reviews by hand
   via `_loadReview`.
10. **`routing: false` + explicit `onItemClick` on the HierarchyWidget.** The default
    `onItemClick` is `router.navigate('item/' + id, {trigger: true})`
    (`girder/web/src/views/widgets/HierarchyWidget.js:181`) and is *not* gated by `routing`.
    The core `item/:id` route triggers `g:navigateTo` with no layout option, and
    `App.navigateTo` then resets to `Layout.DEFAULT`, restoring the header and navbar the
    review page exists to hide.
11. **`showActions: true` is deliberate.** Every mutating control inside the hierarchy
    actions header is separately gated on WRITE/ADMIN in
    `girder/web/src/templates/widgets/hierarchyWidget.pug`, so at READ the menu collapses to
    just "Download collection/folder". Setting it to `false` would throw the download away
    for no security gain.
12. **Reviewer requests pass `error: null` / `ignoreError: true`.** Core's default
    `restRequest` error handler turns any 401 into `setCurrentToken(null)` + `g:loginUi`
    (`girder/web/src/rest.js:91-100`) — a login modal floating over a page with no chrome.
13. **The token lives in `sessionStorage`, never `localStorage`.** Core seeds its own token
    from `localStorage` at module load and falls back to it on every request, so writing
    there would leak the review session into the reviewer's normal Girder session in other
    tabs. `sessionStorage` is tab-scoped and still survives F5.
14. **Never call `setCurrentUser` via `g:login`.** The `g:login` handler
    (`girder/web/src/views/App.js:345`) reopens the EventStream and does
    `router.navigate('/')`, which navigates straight out of the review page. The websocket
    also requires `USER_AUTH` (`girder/notification.py:62`), which a review token lacks.
    `session.loadReviewerUser()` sets the user directly, which fires no events.
15. **Every test module needs its own `pytestmark = pytest.mark.plugin('collection_review')`.**
    pytest only honors module- and class-level `pytestmark`; one in `conftest.py` is silently
    ignored, and the tests would then run against a server with the plugin not loaded — which
    mostly shows up as confusing 400s rather than an obvious failure.

## Traps discovered in Girder core (cost real time; likely to bite again)

- `autoDescribeRoute` **consumes the `params` dict in place**. A `rest.*.after` handler sees
  an empty `params`, and the coerced values are never written back into `event.info`. Route
  wildcards *are* present (`event.info['id']`). This is why the folder hook reads
  `event.info['id']` and the resource-move hook stashes ids at `.before`.
- Binding to any `rest.*.before` event without an access decorator silently makes that
  endpoint admin-only (invariant 3).
- `_handleAccessException` calls `getCurrentUser()`, so exceptions raised from
  `auth.user.get` handlers can escape the endpoint's `try` (invariant 2).
- `Folder().createFolder` calls `copyAccessPolicies` for folder/collection parents
  (`girder/models/folder.py:526`), so folders created during a review inherit the reviewer
  entry automatically — **do not** add a `model.folder.save.created` hook, it is redundant.
- `Folder().move()` never touches ACLs and propagates to descendants with a raw `$set` that
  fires **no** model events (`girder/models/folder.py:282-326`). The REST layer is the only
  observation point.
- `{baseParentId, baseParentType}` and `access.users.id` are **not** indexed by core
  `Folder().initialize()`; our `load()` adds both.
- `DELETE /collection/:id` dispatches to a Celery worker (`girder/tasks.py:115`) where this
  plugin is not loaded, so `model.collection.remove` never fires for us.

## Outstanding work

### 1. Browser verification — done

`girder_collection_review/tests/e2e/run.sh` drives the real UI in system Chrome via
playwright (resolved from `$PLAYWRIGHT` or `~/node_modules/playwright`; no `ms-playwright`
browsers needed). It drops its database, starts Girder on :8749, runs both scripts, and stops
the server. **47 checks, all passing.** Re-run it after any `web_client/` change.

Confirmed in the browser, including the items that were previously only guesses:

- `girderModal` **is** reachable on `girder.$` from a plugin bundle — the manage modal opens,
  and `girder.dialog.confirm` stacks over it with a clickable button (verified with
  `elementFromPoint`, not just visibility).
- `Layout.EMPTY` hides header, navbar and footer on a **cold load** straight to `#review`,
  and `#g-app-body-container` carries `g-empty-layout` without `g-default-layout`.
- Clicking an item keeps the chrome hidden and never reaches the core `#item/` route, so the
  `onItemClick` override does its job.
- Descending a folder does not rewrite the URL hash (`routing: false`).
- A file downloads from a real browser **navigation** — the auth-cookie path, which no
  header-authenticated request can exercise.
- The token is in `sessionStorage` and `localStorage.girderToken` stays `null`.
- The session survives F5; Exit review clears it and restores the chrome; a closed review
  shows the end-of-review page; navigating away restores the default layout.
- At READ there are no upload/create/edit/delete/access-control affordances and no
  checkboxes, but "Download collection" is still present.
- The already-signed-in warning renders for a logged-in visitor.

Two things looked like bugs and were not. The first screenshot of the manage modal showed a
clipped title and overlapping text; measuring the geometry after the fade settled showed it
is correct (dialog top 30, header present, no overlapping boxes) — the screenshot had caught
Bootstrap 3's slide-in mid-transform. And a `Cannot read properties of undefined (reading
'History')` page error turned out to come from the **google_analytics** plugin bundle on
every Girder page, including `/` and `#collections`; `tests/e2e/README.md` documents the
noise filter, which never suppresses anything thrown from this plugin's bundle.

Still absent: **web-client unit tests** (jasmine). The e2e harness covers the flows, but
there is no fast test for the view classes in isolation.

### 2. Deliberately deferred (also listed in README.md)

- **No periodic prune for orphaned reviews.** Collection deletion runs in a Celery worker
  where the plugin is not loaded, so a review can outlive its collection. Read paths
  auto-close such reviews and a site admin can clean up via `GET /review` (no
  `collectionId`) + `DELETE /review/:id`, but there is no scheduled task. Adding one means a
  `girder_worker_plugins` entry point, as girder-jsonforms has.
- **Reviewer search returns nothing.** `GET /resource/search`
  (`girder/api/v1/resource.py:39`) declares no scope, so a review token is anonymous inside
  that handler. Fix would be a plugin-owned `@access.public(scope=DATA_READ)` endpoint.
- **The key is not truly single-view.** `ApiKey` exposes `key` at READ level, so a site admin
  can recover it from `GET /api_key?userId=...`.
- **`core.api_keys` kill switch is bypassed** — only the core REST layer checks it, not the
  model methods this plugin uses.
- **No throttle on `POST /review/session`.** Keys are 40 chars from a CSPRNG and the core
  `POST /api_key/token` route is unthrottled anyway. The real risk is key leakage.
- **ACL drift.** The reviewer shows up in the owner's Access Control dialog and can be
  deleted there, leaving an `open` review with no ACL. `closeReview` is idempotent so this
  degrades gracefully, but nothing detects it.
- **No maximum review duration.** `duration` is only checked for `> 0`. A
  `collection_review.max_duration` setting would be the fix.
- **Coverage gaps.** 85.6% overall; the thinnest are `settings.py` (53%, the validator's
  rejection paths) and `models/review.py` (75%, `listForCollection` and the naive-datetime
  branch of `isExpired`).

### 3. Open decisions

- **No git remote.** The repo has an initial commit on `main` but no origin. Needs creating
  and pushing before the GitHub Actions workflow does anything.
- **License is BSD-3-Clause, copied from girder-jsonforms** (`Copyright (c) 2024,
  data-exp-lab`) on the assumption this should match the sibling repo. The code was
  originally scaffolded from Girder's Apache-2.0 bundled plugins; change `LICENSE` and
  `setup.py`'s `license=` together if Apache-2.0 is wanted instead.
- **Version is pinned at `1.0.0`** in `setup.py` (jsonforms-style hardcoded version rather
  than `setuptools-scm`). Bump manually on release.

## What was actually verified

Against a live `girder serve` on a scratch database, with curl:

- Static content registered and served (`plugin_static/collection_review/...umd.cjs`,
  `style.css`).
- Reviewer reads: `collection/:id`, folder listings at both levels, `item?folderId`,
  `item/:id`, `item/:id/files`, `user/me` → all 200.
- **Cookie-only** downloads (what an `<a href>` navigation does): item, folder and
  collection → all 200 with correct byte counts.
- Writes refused with the collection left unmodified: `POST /folder`, `POST /item`,
  `POST /collection`, `PUT /collection/:id` (403 with `Review sessions are read-only.` —
  the scope-satisfying route, so this specifically proves the guard), `PUT /item/:id`,
  `DELETE /collection/:id`.
- ACL propagation: folders created after the review opens are visible (inheritance); a
  folder + child moved *in* becomes visible; a **rename does not** change visibility; moving
  *out* revokes.
- `PUT /resource/move` still works for a non-admin (regression check for invariant 3).
- Reviewer ends own session → subsequent read 401, old cookie download 401.
- Owner closes review → live session 401, reviewer account gone, core `POST /api_key/token`
  with the old key 400, second close idempotent, and 0 rows remaining across
  `folder.access.users`, `collection.access.users`, `user` (`reviewer-*`), `api_key`,
  `token`.

While the plugin lived in the girder tree, the core suite (`pytest test/`) was run with and
without it installed: 33 pre-existing failures in that environment (slicer_cli_web needs
docker, worker tests need celery, notification websocket), **byte-identical** either way.
