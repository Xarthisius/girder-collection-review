"""
Global read-only guard for review sessions.

A review token carries ``[DATA_READ, USER_INFO_READ]``, and it is tempting to assume that
is inherently read-only. It is not:

* ``PUT /collection/:id`` is declared ``@access.user(scope=TokenScope.DATA_READ)``
  (``girder/api/v1/collection.py``). Only its ``modelParam(level=AccessType.WRITE)`` stops
  the write, which is a property of that one route rather than of the scope.
* Third-party plugins are worse. In this deployment,
  ``girder_jsonforms.rest.deposition.submit_deposition_task`` is declared with
  ``scope=DATA_READ`` and performs DataCite registration.

So a review token is strictly *more* capable than an anonymous visitor, and the scope
system cannot express "this session may not change anything". This guard says it directly.

``auth.user.get`` is the hook because it is the only global one available: REST event names
are per-route (``rest.<method>.<resource>.before``) with no wildcard, and this repo does not
use CherryPy tools or ``before_handler`` hooks anywhere. Every non-public route resolves the
current user via ``@access.user``/``admin``/``token``, so the guard sees them all.
``@access.public`` mutating routes are reachable by anonymous clients regardless and are not
a review-specific escalation.
"""

import cherrypy

from girder.api.rest import getCurrentToken
from girder.exceptions import AccessException

from ..constants import PLUGIN_NAME
from ..models.review import Review

#: Methods a review session is allowed to issue. All download routes are GET.
SAFE_METHODS = frozenset(('GET', 'HEAD', 'OPTIONS'))

#: Routes under our own resource that a review session must still be able to call with a
#: non-safe method, so a reviewer can end their own session.
EXEMPT_PREFIXES = ('/review/session',)


def _isExempt():
    if getattr(cherrypy.request, 'girderCollectionReviewExempt', False):
        return True

    path = cherrypy.request.path_info or ''
    return any(path.rstrip('/').endswith(prefix) for prefix in EXEMPT_PREFIXES)


def reviewReadOnlyGuard(event):
    """
    Reject any non-safe request made with an open review's API key token.

    Kept to a single indexed lookup, and only when the token was minted from an API key at
    all, since this runs on essentially every authenticated request.

    Raises at most once per request. This matters: ``_handleAccessException`` in
    ``girder/api/rest.py`` calls ``getCurrentUser()`` to decide between 401 and 403, which
    re-fires this event from *inside* the endpoint's exception handler. A second raise there
    escapes the try block entirely and surfaces as an unhandled exception instead of a 403.
    """
    if getattr(cherrypy.request, 'girderCollectionReviewDenied', False):
        return

    method = (cherrypy.request.method or 'GET').upper()
    if method in SAFE_METHODS:
        return

    token = getCurrentToken()
    if token is None or not token.get('apiKeyId'):
        return

    if Review().findOpenForApiKey(token['apiKeyId']) is None:
        return

    if _isExempt():
        return

    cherrypy.request.girderCollectionReviewDenied = True

    raise AccessException('Review sessions are read-only.')


def bind(events):
    events.bind('auth.user.get', PLUGIN_NAME, reviewReadOnlyGuard)
