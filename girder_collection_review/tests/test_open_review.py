"""Opening a review round: authorization, the one-shot key, and the reviewer identity."""

import pytest
from girder.constants import AccessType, TokenScope
from girder.models.api_key import ApiKey
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.user import User
from pytest_girder.assertions import assertStatus, assertStatusOk

from .conftest import open_review

pytestmark = pytest.mark.plugin('collection_review')


def test_only_collection_admin_can_open_review(server, admin, user, reviewed_collection):
    other = User().createUser(
        login='outsider',
        password='password',
        firstName='O',
        lastName='Utsider',
        email='outsider@girder.test',
    )

    resp = server.request(
        '/review',
        method='POST',
        params={'collectionId': str(reviewed_collection['collection']['_id'])},
        user=other,
    )
    assertStatus(resp, 403)

    resp = server.request(
        '/review',
        method='POST',
        params={'collectionId': str(reviewed_collection['collection']['_id'])},
    )
    assertStatus(resp, 401)


def test_open_review_returns_key_exactly_once(server, user, reviewed_collection, review):
    assert review['status'] == 'open'
    assert review['key']
    assert review['collectionId'] == str(reviewed_collection['collection']['_id'])

    # The key is not persisted on the review, so no later read can leak it.
    resp = server.request(
        '/review', params={'collectionId': str(reviewed_collection['collection']['_id'])}, user=user
    )
    assertStatusOk(resp)
    assert len(resp.json) == 1
    assert 'key' not in resp.json[0]

    resp = server.request('/review/%s' % review['_id'], user=user)
    assertStatusOk(resp)
    assert 'key' not in resp.json


def test_reviewer_account_is_not_loginable(server, review):
    reviewer = User().load(review['reviewerUserId'], force=True)

    assert reviewer['salt'] is None
    assert User().hasPassword(reviewer) is False
    assert reviewer['public'] is False
    assert reviewer['status'] == 'disabled'
    assert reviewer['email'].endswith('@review.invalid')

    # No home folders were created, so the reviewer cannot show up in resource search.
    assert Folder().findOne({'parentId': reviewer['_id'], 'parentCollection': 'user'}) is None

    # Passwordless accounts are refused by User().authenticate() outright.
    resp = server.request('/user/authentication', basicAuth='%s:password' % reviewer['login'])
    assertStatus(resp, 400)
    assert 'does not have a password' in resp.json['message']


def test_review_key_is_scoped_read_only(review):
    apiKey = ApiKey().load(review['apiKeyId'], force=True)

    assert set(apiKey['scope']) == {TokenScope.DATA_READ, TokenScope.USER_INFO_READ}
    assert apiKey['active'] is True
    # tokenDuration caps the lifetime of any token minted from this key, including one
    # minted through the core POST /api_key/token route that never sees our review doc.
    assert apiKey['tokenDuration'] == pytest.approx(90.0)


def test_duration_overrides_the_default(server, user, reviewed_collection):
    review = open_review(server, user, reviewed_collection['collection'], duration=3)
    apiKey = ApiKey().load(review['apiKeyId'], force=True)

    assert apiKey['tokenDuration'] == pytest.approx(3.0)


def test_non_positive_duration_is_rejected(server, user, reviewed_collection):
    resp = server.request(
        '/review',
        method='POST',
        params={
            'collectionId': str(reviewed_collection['collection']['_id']),
            'duration': 0,
        },
        user=user,
    )
    assertStatus(resp, 400)


def test_reviewer_has_only_read_access(review, reviewed_collection):
    reviewer = User().load(review['reviewerUserId'], force=True)
    coll = Collection().load(reviewed_collection['collection']['_id'], force=True)

    assert Collection().getAccessLevel(coll, reviewer) == AccessType.READ

    for folder in (reviewed_collection['top'], reviewed_collection['sub']):
        doc = Folder().load(folder['_id'], force=True)
        assert Folder().getAccessLevel(doc, reviewer) == AccessType.READ
