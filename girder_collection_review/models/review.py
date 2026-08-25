import datetime

from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.model_base import Model

from ..constants import REVIEW_COLLECTION, ReviewStatus


class Review(Model):
    """
    A review round: a throwaway reviewer identity plus an API key, both scoped to one
    collection.

    This is deliberately a plain ``Model`` rather than an ``AccessControlledModel``.
    Authorization for a review is *derived* -- it is ADMIN on the referenced collection --
    so an ACL on the review document would be a second source of truth that could drift
    away from the collection's own ACL. The REST layer performs the check instead.

    The API key itself is never stored on, or exposed through, this document.
    """

    def initialize(self):
        self.name = REVIEW_COLLECTION
        self.ensureIndices(
            (
                'collectionId',
                'apiKeyId',
                'reviewerUserId',
                ([('collectionId', 1), ('status', 1)], {}),
            )
        )

        self.exposeFields(
            level=AccessType.READ,
            fields={
                '_id',
                'collectionId',
                'requesterId',
                'reviewerUserId',
                'reviewerLogin',
                'apiKeyId',
                'status',
                'created',
                'expires',
                'closed',
            },
        )

    def validate(self, doc):
        if not ReviewStatus.isValid(doc.get('status')):
            raise ValidationException('Invalid review status.', 'status')

        if not doc.get('collectionId'):
            raise ValidationException('Review must reference a collection.', 'collectionId')

        return doc

    def createReview(self, collection, requester, reviewer, apiKey, days):
        now = datetime.datetime.now(datetime.timezone.utc)

        return self.save(
            {
                'collectionId': collection['_id'],
                'requesterId': requester['_id'],
                'reviewerUserId': reviewer['_id'],
                'reviewerLogin': reviewer['login'],
                'apiKeyId': apiKey['_id'],
                'status': ReviewStatus.OPEN,
                'created': now,
                'expires': now + datetime.timedelta(days=float(days)),
                'closed': None,
            }
        )

    def findOpenForApiKey(self, apiKeyId):
        """
        Look up the open review a token's API key belongs to, or None.

        Used by the read-only request guard on every request that carries an API-key token,
        so this must stay a single indexed query.
        """
        if not apiKeyId:
            return None

        return self.findOne({'apiKeyId': apiKeyId, 'status': ReviewStatus.OPEN})

    def listForCollection(self, collection, status=None, limit=0, offset=0, sort=None):
        query = {'collectionId': collection['_id']}
        if status is not None:
            query['status'] = status

        return self.find(query, limit=limit, offset=offset, sort=sort)

    def isExpired(self, review, now=None):
        expires = review.get('expires')
        if expires is None:
            return False

        now = now or datetime.datetime.now(datetime.timezone.utc)
        # Documents written before pymongo's tz_aware option took effect may be naive.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=datetime.timezone.utc)

        return expires < now
