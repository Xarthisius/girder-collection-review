# girder-collection-review

Share a Girder collection with anonymous peer reviewers via a single revocable access key.

Reviewers never create Girder accounts, cannot change anything, and lose access the moment
the collection owner ends the review.

## Workflow

1. The collection owner (ADMIN on the collection) opens **Actions → Manage review** on the
   collection page and opens a review round. The server provisions a throwaway read-only
   account plus an API key, and shows the key once.
2. The owner passes the key to the journal editor, who distributes it to reviewers.
3. A reviewer visits `#review`, pastes the key, and gets the collection hierarchy on a page
   with no navigation chrome — read only, with downloads working.
4. The owner ends the review. The key stops working immediately, live reviewer sessions die,
   every ACL entry for the reviewer is stripped, and the throwaway account is deleted.

## Install

```bash
pip install -e .
cd girder_collection_review/web_client && npm ci && npm run build
```

The web client bundle **must** be built before starting Girder:
`registerPluginStaticContent` hashes the files in `web_client/dist/` at plugin load time, so
a missing `dist/` fails server startup.

## Develop

```bash
tox -e lint      # ruff check
tox -e pytest    # pytest with coverage, 4-way xdist
tox -e format    # ruff format + ruff check --fix
```

Tests live in `girder_collection_review/tests/` and use the `pytest-girder` fixtures
(`db`, `server`, `admin`, `user`, `fsAssetstore`); plugin-specific fixtures are in
`tests/conftest.py`. Every test module needs
`pytestmark = pytest.mark.plugin('collection_review')` — pytest only honors module- and
class-level `pytestmark`, so it cannot be hoisted into the conftest.

Browser end-to-end checks live in `girder_collection_review/tests/e2e/` and are run by hand
with `./run.sh` — they need a built web client, a running Girder, a droppable Mongo and a
Chrome, so they are not part of `tox -e pytest`. See that directory's `README.md`.

JS/pug/stylus linting uses the girder checkout's root config rather than anything in this
repo, so it runs only when this repo is symlinked into `girder/plugins/`. See `CLAUDE.md`.

## Trust model

Several choices here are deliberate and non-obvious. Changing them will quietly weaken the
plugin, so the reasoning is recorded next to each one in the source, and enumerated in
`CLAUDE.md`.

**The reviewer account cannot be logged into.** It is created passwordless (`salt = None`),
which `User().authenticate()` refuses outright, and its email is on the RFC 2606 reserved
`.invalid` domain. The domain matters: `PUT /user/password/temporary` is a public route that
works on passwordless accounts, so a routable reviewer mailbox would let whoever controls it
upgrade the account to a full `USER_AUTH` session. `status` is also set to `disabled`, but
only as an operator-visible marker — neither `getCurrentUser` nor `ApiKey().createToken`
consults `verifyLogin`.

**Read-only is enforced by a request guard, not by token scope.** The review key is scoped
`[core.data.read, core.user_info.read]`, but scope alone is not sufficient:
`PUT /collection/:id` is declared `@access.user(scope=TokenScope.DATA_READ)` in core, and
plugins declare worse. A review token is therefore *more* capable than an anonymous visitor.
`lib/guard.py` binds `auth.user.get` and rejects any non-safe HTTP method from a review
session, which closes the whole class of mis-scoped routes at once.

**Ending a review revokes the key, not just the review document.** `POST /api_key/token` is
public and never sees the review record, so a reviewer who kept the key could keep minting
tokens. Closing a review removes the API key, which makes `Token().clearForApiKey` drop
every derived token. The key's `tokenDuration` is also set from the review's duration, so it
caps token lifetime independently.

**An auth cookie is set.** Download links in the hierarchy widget are plain `<a href>`
navigations that carry no `Girder-Token` header. Every `cookie=True` route in core is
read-only, and the guard rejects non-safe methods for the session, so the cookie adds no
write surface. Note that the cookie is `path=/` and replaces any existing `girderToken` in
that browser; the reviewer page warns before starting a session if somebody is already
signed in.

## Known limitations

* **The key is not truly single-view.** `ApiKey` exposes `key` at `READ` level, so a site
  admin can recover it from `GET /api_key?userId=...`. The UI shows it once as a convention,
  not a guarantee.
* **The site-wide `core.api_keys` switch is bypassed.** Only the core REST layer checks it;
  the model methods this plugin uses do not.
* **Reviewer search returns nothing.** `GET /resource/search` declares no scope, so a review
  token is treated as anonymous inside that handler.
* **A deleted collection can orphan a review.** `DELETE /collection/:id` dispatches the
  removal to a Celery worker where this plugin is not loaded, so no event fires. Read paths
  auto-close such reviews, and a site admin can list and close them with `GET /review` and
  `DELETE /review/:id`.
* **No throttle on key submission.** Keys are 40 characters from a CSPRNG, and the core
  `POST /api_key/token` route is unthrottled anyway, so a throttle here would buy nothing.
  The real risk is key leakage in transit; use a short duration and one key per reviewer
  where practical.
* **No maximum review duration.** `duration` is only validated as positive.

## Settings

| Key | Meaning |
| --- | --- |
| `collection_review.default_duration` | Days a review key stays valid when the owner does not specify a duration. Default 90. |

## Endpoints

| Route | Purpose |
| --- | --- |
| `POST /review` | Open a review round. Returns the review plus its `key`. |
| `GET /review` | List reviews for a collection (ADMIN), or all of them (site admin, for cleaning up orphans). |
| `GET /review/:id` | Read one review. |
| `DELETE /review/:id` | Close a review and revoke access. Idempotent. |
| `POST /review/session` | Reviewer-facing: exchange a key for a read-only session. |
| `GET /review/session` | Reviewer-facing: current session, for reload and end-of-review detection. |
| `DELETE /review/session` | Reviewer-facing: end the session. |

## License

BSD 3-Clause. See `LICENSE`.
