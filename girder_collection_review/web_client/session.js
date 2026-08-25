/**
 * Review session state for the reviewer-facing pages.
 *
 * The token is kept in ``sessionStorage`` rather than ``localStorage`` on purpose. Core
 * seeds its own token from ``localStorage`` at module load (``auth.js``) and falls back to
 * it on every request (``rest.js``), so writing there would make a review session leak into
 * the reviewer's normal Girder session in other tabs. ``sessionStorage`` is scoped to this
 * tab and still survives a reload, which an in-memory-only token would not.
 */

const { getCurrentUser, setCurrentToken, setCurrentUser } = girder.auth;
const { restRequest } = girder.rest;
const UserModel = girder.models.UserModel;

const STORAGE_KEY = 'girderCollectionReviewToken';

function _read() {
    try {
        return window.sessionStorage.getItem(STORAGE_KEY);
    } catch (e) {
        return null;
    }
}

function _write(token) {
    try {
        if (token) {
            window.sessionStorage.setItem(STORAGE_KEY, token);
        } else {
            window.sessionStorage.removeItem(STORAGE_KEY);
        }
    } catch (e) {
        // Private browsing modes can throw on any storage access; the in-memory token
        // still works for the life of the page.
    }
}

/** Adopt a freshly minted review token. */
function adopt(token) {
    setCurrentToken(token);
    _write(token);
}

/** Re-adopt the token stashed for this tab, if any. Returns the token or null. */
function restore() {
    const token = _read();
    if (token) {
        setCurrentToken(token);
    }
    return token;
}

/** Forget the review token locally. Does not contact the server. */
function forget() {
    _write(null);
    setCurrentToken(null);
    setCurrentUser(null);
}

/**
 * Ask the server which review the current token belongs to.
 *
 * ``error: null`` is required: the default handler in core's ``restRequest`` treats any 401
 * as a session expiry, clears the token and pops the login modal -- which on a chrome-free
 * page appears as a dialog over nothing.
 */
function fetch() {
    return restRequest({ url: 'review/session', error: null });
}

/** Populate the current user so core widgets behave normally. */
function loadReviewerUser() {
    return restRequest({ url: 'user/me', error: null }).done((resp) => {
        if (resp) {
            setCurrentUser(new UserModel(resp));
        }
    });
}

/** End the session server-side (revoking the token and cookie), then locally. */
function end() {
    return restRequest({
        url: 'review/session',
        method: 'DELETE',
        error: null
    }).always(forget);
}

/** True if somebody is already signed in normally; starting a session replaces their cookie. */
function hasNormalSession() {
    return !!(getCurrentUser() && !_read());
}

export { adopt, end, fetch, forget, hasNormalSession, loadReviewerUser, restore };
