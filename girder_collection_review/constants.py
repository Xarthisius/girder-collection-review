PLUGIN_NAME = 'collection_review'

#: Mongo collection name backing the Review model.
REVIEW_COLLECTION = 'collection_review'

#: RFC 2606 reserved TLD. This MUST stay non-routable: ``PUT /user/password/temporary`` is
#: ``@access.public`` and works on passwordless users, so whoever controls the reviewer's
#: mailbox could convert the throwaway account into a full USER_AUTH session.
REVIEWER_EMAIL_DOMAIN = 'review.invalid'

#: ``User.validate`` lowercases the login before checking it against
#: ``^[a-z][\\da-z\\-\\.]{3,}$``, so the suffix must already be lowercase.
REVIEWER_LOGIN_PREFIX = 'reviewer-'

REVIEWER_FIRST_NAME = 'Anonymous'
REVIEWER_LAST_NAME = 'Reviewer'


class ReviewStatus:
    OPEN = 'open'
    CLOSED = 'closed'

    @staticmethod
    def isValid(status):
        return status in (ReviewStatus.OPEN, ReviewStatus.CLOSED)


class PluginSettings:
    DEFAULT_DURATION = 'collection_review.default_duration'
