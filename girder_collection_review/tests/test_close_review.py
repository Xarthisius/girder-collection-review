"""Closing a review, expiry, and cleaning up reviews whose collection is gone."""

import datetime

import pytest
from girder.models.api_key import ApiKey
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.user import User
from pytest_girder.assertions import assertStatus, assertStatusOk

pytestmark = pytest.mark.plugin('collection_review')


def test_close_review_revokes_everything(server, user, reviewed_collection, review, review_token):
    reviewerId = review['reviewerUserId']

    resp = server.request(
        '/collection/%s' % reviewed_collection['collection']['_id'], token=review_token
    )
    assertStatusOk(resp)

    resp = server.request('/review/%s' % review['_id'], method='DELETE', user=user)
    assertStatusOk(resp)
    assert resp.json['status'] == 'closed'
    assert resp.json['closed'] is not None

    # The live session is dead because the API key -- and with it, its tokens -- is gone.
    resp = server.request(
        '/collection/%s' % reviewed_collection['collection']['_id'], token=review_token
    )
    assertStatus(resp, 401)

    # The throwaway account is gone, and no ACL anywhere still references it.
    assert User().load(reviewerId, force=True) is None
    assert ApiKey().findOne({'userId': reviewerId}) is None
    for model in (Folder(), Collection()):
        assert model.findOne({'access.users.id': reviewerId}) is None


def test_close_review_is_idempotent(server, user, review):
    resp = server.request('/review/%s' % review['_id'], method='DELETE', user=user)
    assertStatusOk(resp)

    # Read the persisted value back: Mongo truncates to milliseconds, so comparing against
    # the first response's in-memory timestamp would fail spuriously.
    resp = server.request('/review/%s' % review['_id'], user=user)
    assertStatusOk(resp)
    closedAt = resp.json['closed']
    assert closedAt is not None

    # The second close must be a no-op, not a second teardown with a fresh timestamp.
    resp = server.request('/review/%s' % review['_id'], method='DELETE', user=user)
    assertStatusOk(resp)
    assert resp.json['status'] == 'closed'
    assert resp.json['closed'] == closedAt


def test_revoked_key_cannot_mint_token_via_core_endpoint(server, user, review):
    """
    Closing must revoke the key itself, not merely mark our document closed: the core
    ``POST /api_key/token`` route is public and never consults the review.
    """
    key = review['key']

    resp = server.request('/api_key/token', method='POST', params={'key': key})
    assertStatusOk(resp)

    resp = server.request('/review/%s' % review['_id'], method='DELETE', user=user)
    assertStatusOk(resp)

    resp = server.request('/api_key/token', method='POST', params={'key': key})
    assertStatus(resp, 400)

    resp = server.request('/review/session', method='POST', params={'key': key})
    assertStatus(resp, 400)


def test_expired_review_is_closed_lazily(server, user, review):
    from girder_collection_review.models.review import Review as ReviewModel

    doc = ReviewModel().load(review['_id'])
    doc['expires'] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ReviewModel().save(doc)

    resp = server.request('/review/session', method='POST', params={'key': review['key']})
    assertStatus(resp, 400)

    resp = server.request('/review/%s' % review['_id'], user=user)
    assertStatusOk(resp)
    assert resp.json['status'] == 'closed'
    assert User().load(review['reviewerUserId'], force=True) is None


def test_orphaned_review_is_admin_closable(server, admin, user, reviewed_collection, review):
    """
    Collection deletion happens in a Celery worker where this plugin is not loaded, so a
    review can outlive its collection. A site admin must still be able to clean it up.
    """
    Collection().remove(reviewed_collection['collection'])

    resp = server.request('/review/%s' % review['_id'], method='DELETE', user=user)
    assertStatus(resp, 403)

    resp = server.request('/review/%s' % review['_id'], method='DELETE', user=admin)
    assertStatusOk(resp)
    assert resp.json['status'] == 'closed'


def test_list_all_reviews_requires_site_admin(server, admin, user, review):
    resp = server.request('/review', user=user)
    assertStatus(resp, 403)

    resp = server.request('/review', user=admin)
    assertStatusOk(resp)
    assert len(resp.json) == 1


def test_bad_review_id_is_a_client_error(server, user):
    resp = server.request('/review/not-an-objectid', user=user)
    assertStatus(resp, 400)
