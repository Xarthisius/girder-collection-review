# Browser end-to-end checks

The Python tests cover the server. These cover the parts only a real browser can answer:
whether `Layout.EMPTY` actually hides the navigation, whether a plugin bundle can reach
core's `girderModal` jQuery plugin, whether clicking an item keeps the chrome hidden, and
whether a download link works as a browser *navigation* (the auth-cookie path, which no
header-authenticated request exercises).

```bash
./run.sh                       # uses ../../../../girder/venv by default
./run.sh /path/to/girder/venv
```

`run.sh` drops its database, starts Girder on a scratch port, runs both scripts, and stops
the server. 49 checks; screenshots land in `shots/` (gitignored).

Not wired into `tox -e pytest` on purpose — it needs a built web client, a running server, a
droppable Mongo, and a Chrome, none of which belong in a unit-test env.

## Determinism

Contexts disable every CSS transition and animation from the first paint (via
`addInitScript`, so it survives reloads and hash routing), and modal opens wait on
Bootstrap's own `shown.bs.modal` event plus a frame-stability and opacity check — never on a
sleep. Without that, screenshots land mid-fade on a half-transparent, still-sliding dialog,
and `elementFromPoint` hit-testing can resolve to the backdrop instead of the button.

## Requirements

- Chrome — `CHROME=/usr/bin/google-chrome` by default.
- playwright, resolved from `$PLAYWRIGHT`, else `~/node_modules/playwright`, else the ambient
  `node_modules`. It is **not** a dependency of this repo. No `ms-playwright` browsers need
  downloading; the scripts drive the system Chrome via `executablePath`.
- MongoDB on `localhost:27017`.
- A built web client (`cd ../../web_client && npm ci && npm run build`).

## Files

| File | Covers |
| --- | --- |
| `01-review-flow.mjs` | Owner opens a review and reads the key; reviewer cold-loads `#review`, is rejected on a bad key, browses, opens an item, downloads, refreshes; review is closed and the page notices. 38 checks. |
| `02-modal-and-exit.mjs` | Confirm-dialog stacking over the manage modal, the exit-review flow, `sessionStorage`/`localStorage` placement, and the already-signed-in warning. 11 checks. |

`01` writes the owner login to `.owner` because only the first user created in a fresh
database becomes a site admin, and `02` needs the same account.

## Known-noise filter

`01-review-flow.mjs` asserts there are no unexpected JS errors, filtering three things that
are **not** this plugin and reproduce on a stock Girder page:

- `Cannot read properties of undefined (reading 'History')` — thrown by the
  **google_analytics** plugin bundle on every page, including `/` and `#collections`.
- A `403` websocket handshake for `notifications/me?token=null` — core's EventStream with no
  signed-in user.
- A `400` from `POST /review/session` — the script's own deliberate bad-key submission.

Anything thrown from the `collection-review` bundle is never filtered.
