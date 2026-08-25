"""
Provisioning and tear-down of the throwaway reviewer identity, plus ACL propagation.

Two things here are deliberately not written the obvious way; both are load bearing.

1. The reviewer user document is built by hand instead of via ``User().createUser()``.
   ``createUser`` sends verification/approval mail *synchronously* through
   ``mail_utils._sendmail``, with no exception handling, so it would block on SMTP to a
   non-routable domain and could raise *after* the user row was already written. It also
   fires ``model.user.save.created``, whose core handlers create a **public** "Public"
   home folder that would show up in everyone's ``/resource/search``. Saving with
   ``triggerEvents=False`` still runs full validation but skips both.

2. ACLs are propagated with bulk Mongo updates rather than a ``setUserAccess`` loop.
   ``AccessControlledModel._saveAcl`` rewrites the entire document on every call, so a
   per-folder loop is a lost-update race against a concurrent rename and fires one
   ``model.folder.save`` event per folder.
"""

import datetime
import logging
import secrets

from girder.constants import AccessType, TokenScope
from girder.exceptions import ValidationException
from girder.models.api_key import ApiKey
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.setting import Setting
from girder.models.token import Token
from girder.models.user import User

from ..constants import (
    PluginSettings,
    REVIEWER_EMAIL_DOMAIN,
    REVIEWER_FIRST_NAME,
    REVIEWER_LAST_NAME,
    REVIEWER_LOGIN_PREFIX,
    ReviewStatus,
)
from ..models.review import Review

logger = logging.getLogger(__name__)

#: Read-only scopes. Every read route on collection/folder/item/file/resource declares
#: ``scope=TokenScope.DATA_READ``; ``USER_INFO_READ`` is what makes ``GET /user/me`` work so
#: the web client's normal auth plumbing does not 401. Note that DATA_READ alone is *not*
#: sufficient to make the session read-only -- ``PUT /collection/:id`` is declared with
#: ``scope=DATA_READ`` -- which is why ``lib/guard.py`` exists.
REVIEW_SCOPES = [TokenScope.DATA_READ, TokenScope.USER_INFO_READ]

_LOGIN_ATTEMPTS = 5


def defaultDuration():
    return float(Setting().get(PluginSettings.DEFAULT_DURATION))


def _aclEntry(reviewerId):
    return {'id': reviewerId, 'level': AccessType.READ, 'flags': []}


def _createReviewerUser():
    """
    Create a passwordless, non-public throwaway user.

    ``salt=None`` means ``User().authenticate()`` refuses the account outright, so the API
    key is the only way in. ``status='disabled'`` is set as an operator-visible marker only
    -- neither ``getCurrentUser`` nor ``ApiKey().createToken`` consults ``verifyLogin``.
    """
    lastError = None

    for _ in range(_LOGIN_ATTEMPTS):
        # token_hex, not genToken: User.validate lowercases the login before matching it
        # against ^[a-z][\da-z\-\.]{3,}$, which would silently case-fold a mixed-case
        # suffix and halve its entropy.
        login = REVIEWER_LOGIN_PREFIX + secrets.token_hex(8)
        user = {
            'login': login,
            'email': '%s@%s' % (login, REVIEWER_EMAIL_DOMAIN),
            'firstName': REVIEWER_FIRST_NAME,
            'lastName': REVIEWER_LAST_NAME,
            'admin': False,
            'status': 'disabled',
            'emailVerified': True,
            'created': datetime.datetime.now(datetime.timezone.utc),
            'size': 0,
            'groups': [],
            'groupInvites': [],
        }
        User().setPassword(user, None, save=False)
        User().setPublic(user, False, save=False)

        try:
            # triggerEvents=False still validates; it suppresses _addDefaultFolders and
            # _grantSelfAccess, which we do not want for a throwaway identity.
            return User().save(user, validate=True, triggerEvents=False)
        except ValidationException as e:
            # Login/email uniqueness is enforced in application code against non-unique
            # indices, so a collision is possible in principle. Retry with a fresh suffix.
            lastError = e

    raise lastError


def grantSubtree(collection, reviewerId):
    """
    Grant READ to the reviewer on every folder currently under ``collection``.

    Folders *created* later need no handling: ``Folder().createFolder`` calls
    ``copyAccessPolicies`` for folder/collection parents, so they inherit this entry.
    Folders *moved* in later are handled by ``syncMovedFolder``.
    """
    return Folder().collection.update_many(
        {
            'baseParentId': collection['_id'],
            'baseParentType': 'collection',
            'access.users.id': {'$ne': reviewerId},
        },
        {'$push': {'access.users': _aclEntry(reviewerId)}},
    )


def revokeEverywhere(reviewerId):
    """
    Remove the reviewer from every collection and folder ACL, site-wide.

    Deliberately not scoped to the collection subtree: a folder created during the review
    and then moved out keeps the reviewer's entry, and a ``baseParentId`` query would never
    find it again.
    """
    for model in (Folder(), Collection()):
        model.collection.update_many(
            {'access.users.id': reviewerId},
            {'$pull': {'access.users': {'id': reviewerId}}},
        )


def _subtreeFolderIds(folder):
    """Breadth-first walk of a folder and its descendants, via the indexed ``parentId``."""
    ids = [folder['_id']]
    frontier = [folder['_id']]

    while frontier:
        children = list(
            Folder().collection.find(
                {'parentId': {'$in': frontier}, 'parentCollection': 'folder'},
                projection=['_id'],
            )
        )
        frontier = [child['_id'] for child in children]
        ids.extend(frontier)

    return ids


def syncMovedFolder(folder):
    """
    Re-sync reviewer ACLs over a folder and its descendants.

    ``Folder().move()`` rewrites ``parentId``/``baseParent*`` but never touches ACLs, and
    propagates to descendants with a raw ``$set`` that fires no model events -- so neither
    ``model.folder.save.created`` nor ``copyAccessPolicies`` covers this path. Grants
    reviewers of the folder's current base collection and revokes reviewers of any other.

    Safe to call on any folder update. It short-circuits when the folder's own ACL already
    agrees with its location, which is what a plain rename looks like, so only a genuine
    move pays for the subtree walk.
    """
    openReviews = list(Review().find({'status': ReviewStatus.OPEN}))
    if not openReviews:
        return

    if folder.get('baseParentType') == 'collection':
        wanted = {
            review['reviewerUserId']
            for review in openReviews
            if review['collectionId'] == folder['baseParentId']
        }
    else:
        wanted = set()

    unwanted = {review['reviewerUserId'] for review in openReviews} - wanted

    present = {entry['id'] for entry in (folder.get('access') or {}).get('users', ())}
    if not (wanted - present) and not (unwanted & present):
        # This folder already sits where its ACL says it does, so nothing moved into or out
        # of a reviewed collection. Skip the subtree walk.
        return

    folderIds = _subtreeFolderIds(folder)

    if unwanted:
        Folder().collection.update_many(
            {'_id': {'$in': folderIds}},
            {'$pull': {'access.users': {'id': {'$in': list(unwanted)}}}},
        )

    for reviewerId in wanted:
        Folder().collection.update_many(
            {'_id': {'$in': folderIds}, 'access.users.id': {'$ne': reviewerId}},
            {'$push': {'access.users': _aclEntry(reviewerId)}},
        )


def openReview(collection, requester, days=None):
    """
    Provision a reviewer identity + API key for ``collection``.

    :returns: ``(review, key)``. ``key`` is the raw API key string; the caller is
        responsible for handing it to the requester, as it is not stored on the review.
    """
    days = float(days or defaultDuration())
    reviewer = _createReviewerUser()

    try:
        Collection().setUserAccess(collection, reviewer, AccessType.READ, save=True)
        grantSubtree(collection, reviewer['_id'])

        apiKey = ApiKey().createApiKey(
            reviewer,
            name='Review of %s' % collection['name'],
            scope=REVIEW_SCOPES,
            # tokenDuration is a hard cap in ApiKey().createToken, so this is what actually
            # bounds a review session -- our own expiry check cannot, because the core
            # POST /api_key/token endpoint is public and never sees the review document.
            days=days,
        )

        review = Review().createReview(collection, requester, reviewer, apiKey, days)
    except Exception:
        logger.exception('Failed to open review; unwinding reviewer %s', reviewer['login'])
        _unwindReviewer(reviewer['_id'])
        raise

    return review, apiKey['key']


def _unwindReviewer(reviewerId):
    """Best-effort teardown of a reviewer identity. Never raises."""
    try:
        revokeEverywhere(reviewerId)
    except Exception:
        logger.exception('Failed to revoke ACLs for reviewer %s', reviewerId)

    try:
        for apiKey in list(ApiKey().find({'userId': reviewerId})):
            ApiKey().remove(apiKey)
    except Exception:
        logger.exception('Failed to remove API keys for reviewer %s', reviewerId)

    try:
        Token().removeWithQuery({'userId': reviewerId})
    except Exception:
        logger.exception('Failed to remove tokens for reviewer %s', reviewerId)

    try:
        reviewer = User().load(reviewerId, force=True)
        if reviewer is not None:
            User().remove(reviewer)
    except Exception:
        logger.exception('Failed to remove reviewer %s', reviewerId)


def closeReview(review):
    """
    Revoke a review. Idempotent, and tolerant of every referent already being gone.

    Removing the API key is what kills live sessions: ``ApiKey().remove`` calls
    ``Token().clearForApiKey``. Marking the review closed on its own would do nothing,
    since ``POST /api_key/token`` is public and never consults this document.
    """
    if review.get('status') == ReviewStatus.CLOSED:
        return review

    _unwindReviewer(review['reviewerUserId'])

    review['status'] = ReviewStatus.CLOSED
    review['closed'] = datetime.datetime.now(datetime.timezone.utc)

    return Review().save(review)


def closeIfExpired(review):
    """Lazily enforce expiry on any read path. Returns the (possibly closed) review."""
    if review.get('status') == ReviewStatus.OPEN and Review().isExpired(review):
        return closeReview(review)

    return review
