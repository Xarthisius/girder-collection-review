import datetime

import cherrypy

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, RestException
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import AccessException, ValidationException
from girder.models.api_key import ApiKey
from girder.models.collection import Collection as CollectionModel
from girder.models.token import Token

from .constants import ReviewStatus
from .lib import provisioning
from .models.review import Review as ReviewModel


def _daysUntil(review):
    expires = review.get('expires')
    if expires is None:
        return None

    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)

    delta = expires - datetime.datetime.now(datetime.timezone.utc)

    return max(delta.total_seconds() / 86400.0, 0)


class Review(Resource):
    def __init__(self):
        super().__init__()
        self.resourceName = 'review'

        self.route('GET', (), self.listReviews)
        self.route('POST', (), self.createReview)
        self.route('GET', ('session',), self.getSession)
        self.route('POST', ('session',), self.createSession)
        self.route('DELETE', ('session',), self.deleteSession)
        self.route('GET', (':id',), self.getReview)
        self.route('DELETE', (':id',), self.deleteReview)

    # ------------------------------------------------------------------ helpers

    def _loadReview(self, reviewId):
        """
        Load a review by id.

        Done by hand rather than with ``modelParam``: ``autoDescribeRoute`` calls
        ``model.load(id, force=True)`` for ``force=True`` params, and a plain ``Model``
        (which ``Review`` deliberately is) has no ``force`` argument.
        """
        try:
            review = ReviewModel().load(reviewId, exc=False)
        except ValidationException:
            raise RestException('Invalid review id (%s).' % reviewId, code=400)

        if review is None:
            raise RestException('Invalid review id (%s).' % reviewId, code=400)

        return review

    def _requireReviewAdmin(self, review):
        """
        Authorize against the *collection*, not the review document.

        If the collection is gone -- ``DELETE /collection/:id`` dispatches the actual
        removal to a Celery worker, where this plugin's event bindings do not exist, so
        orphaned reviews are expected -- fall back to requiring a site admin so the
        leftover can still be cleaned up.
        """
        user = self.getCurrentUser()
        collection = CollectionModel().load(
            review['collectionId'], user=user, level=AccessType.ADMIN, exc=False
        )

        if collection is None and not (user and user['admin']):
            raise AccessException('Admin access required for this review.')

        return collection

    def _filter(self, review):
        return ReviewModel().filter(review, self.getCurrentUser())

    @staticmethod
    def _collectionSummary(collection):
        return {
            '_id': collection['_id'],
            'name': collection['name'],
            'description': collection.get('description', ''),
        }

    @staticmethod
    def _sessionReview(review):
        """The subset of a review that is safe to show a reviewer."""
        return {
            '_id': review['_id'],
            'collectionId': review['collectionId'],
            'status': review['status'],
            'expires': review.get('expires'),
        }

    # ------------------------------------------------------------------ owner side

    @access.user
    @autoDescribeRoute(
        Description('List review rounds for a collection.')
        .notes(
            'Requires ADMIN access on the collection. Omit collectionId to list every '
            'review on the site, which requires site admin and is intended for cleaning '
            'up reviews whose collection has been deleted.'
        )
        .modelParam(
            'collectionId',
            'The collection to list reviews for.',
            model=CollectionModel,
            level=AccessType.ADMIN,
            paramType='query',
            required=False,
            destName='collection',
        )
        .param(
            'status',
            'Only list reviews with this status.',
            required=False,
            enum=[ReviewStatus.OPEN, ReviewStatus.CLOSED],
        )
        .pagingParams(defaultSort='created', defaultSortDir=SortDir.DESCENDING)
        .errorResponse()
        .errorResponse('Admin permission denied on the collection.', 403)
    )
    def listReviews(self, collection, status, limit, offset, sort):
        if collection is None:
            user = self.getCurrentUser()
            if not user['admin']:
                raise AccessException('Site admin access required to list all reviews.')
            query = {}
        else:
            query = {'collectionId': collection['_id']}

        if status is not None:
            query['status'] = status

        reviews = list(ReviewModel().find(query, limit=limit, offset=offset, sort=sort))

        return [self._filter(provisioning.closeIfExpired(review)) for review in reviews]

    @access.user
    @autoDescribeRoute(
        Description('Get a single review round.')
        .param('id', 'The review ID.', paramType='path')
        .errorResponse()
        .errorResponse('Admin permission denied on the collection.', 403)
    )
    def getReview(self, id):
        review = self._loadReview(id)
        self._requireReviewAdmin(review)

        return self._filter(provisioning.closeIfExpired(review))

    @access.user
    @autoDescribeRoute(
        Description('Open a review round on a collection.')
        .notes(
            'Creates a throwaway read-only account with an API key scoped to this '
            'collection. The key is returned in the "key" field of the response and is '
            'not stored on the review document -- hand it to the journal editor now.'
        )
        .modelParam(
            'collectionId',
            'The collection to put under review.',
            model=CollectionModel,
            level=AccessType.ADMIN,
            paramType='formData',
            destName='collection',
        )
        .param(
            'duration',
            'How many days the review key stays valid.',
            dataType='number',
            required=False,
        )
        .errorResponse()
        .errorResponse('Admin permission denied on the collection.', 403)
    )
    def createReview(self, collection, duration):
        if duration is not None and float(duration) <= 0:
            raise RestException('Duration must be positive.', code=400)

        review, key = provisioning.openReview(collection, self.getCurrentUser(), days=duration)

        result = self._filter(review)
        result['key'] = key

        return result

    @access.user
    @autoDescribeRoute(
        Description("Close a review round, revoking the reviewers' access immediately.")
        .notes(
            'Removes the API key (which kills any live reviewer session), strips the '
            'reviewer from every ACL, and deletes the throwaway account. Idempotent.'
        )
        .param('id', 'The review ID.', paramType='path')
        .errorResponse()
        .errorResponse('Admin permission denied on the collection.', 403)
    )
    def deleteReview(self, id):
        review = self._loadReview(id)
        self._requireReviewAdmin(review)

        return self._filter(provisioning.closeReview(review))

    # ------------------------------------------------------------------ reviewer side

    @access.public
    @autoDescribeRoute(
        Description('Start a review session from an access key.')
        .notes(
            'Exchanges a review access key for a read-only auth token, and sets the '
            'auth cookie so that file download links work.'
        )
        .param('key', 'The review access key.', strip=True)
        .errorResponse('The key is invalid, or its review has ended.', 400)
    )
    def createSession(self, key):
        try:
            _, token = ApiKey().createToken(key)
        except ValidationException:
            raise RestException('Invalid or expired review key.', code=400)

        review = ReviewModel().findOpenForApiKey(token.get('apiKeyId'))
        if review is None:
            # Either not a review key at all, or the review is closed. Either way, do not
            # leave a usable token behind.
            Token().remove(token)
            raise RestException('Invalid or expired review key.', code=400)

        if ReviewModel().isExpired(review):
            provisioning.closeReview(review)
            raise RestException('This review has ended.', code=400)

        collection = CollectionModel().load(review['collectionId'], force=True, exc=False)
        if collection is None:
            provisioning.closeReview(review)
            raise RestException('The collection under review no longer exists.', code=400)

        # The hierarchy widget's download affordances are plain <a href> navigations, which
        # carry no Girder-Token header. Every cookie=True route in core is read-only, and
        # lib/guard.py rejects non-safe methods for this token, so the cookie adds no write
        # surface. Note it is path=/ and therefore replaces any existing girderToken in this
        # browser -- the client warns about that before starting a session.
        self.sendAuthTokenCookie(token=token, days=_daysUntil(review))

        return {
            'authToken': {
                'token': token['_id'],
                'expires': token['expires'],
                'scope': token['scope'],
            },
            'review': self._sessionReview(review),
            'collection': self._collectionSummary(collection),
        }

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Get the review session the current token belongs to, if any.').notes(
            'Used by the reviewer UI to restore a session after a page reload and to '
            'notice that a review has been closed out from under it.'
        )
    )
    def getSession(self):
        token = self.getCurrentToken()
        if token is None or not token.get('apiKeyId'):
            return {'review': None}

        review = ReviewModel().findOpenForApiKey(token['apiKeyId'])
        if review is None:
            return {'review': None}

        if ReviewModel().isExpired(review):
            provisioning.closeReview(review)
            return {'review': None}

        collection = CollectionModel().load(review['collectionId'], force=True, exc=False)
        if collection is None:
            provisioning.closeReview(review)
            return {'review': None}

        return {
            'review': self._sessionReview(review),
            'collection': self._collectionSummary(collection),
        }

    @access.public
    @autoDescribeRoute(
        Description('End the current review session.').notes(
            'Needed because the core DELETE /user/authentication route requires the '
            'USER_AUTH scope, which a review token does not carry.'
        )
    )
    def deleteSession(self):
        # Signals lib/guard.py that this DELETE is legitimate for a review token.
        cherrypy.request.girderCollectionReviewExempt = True

        token = self.getCurrentToken()
        if token is not None:
            Token().remove(token)

        self.deleteAuthTokenCookie()

        return {'message': 'Review session ended.'}
