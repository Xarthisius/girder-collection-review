"""What a reviewer session can read, and how sessions are established and reported."""

import pytest
from girder.models.api_key import ApiKey
from pytest_girder.assertions import assertStatus, assertStatusOk

pytestmark = pytest.mark.plugin('collection_review')


def test_reviewer_can_browse_the_collection(
    server, reviewed_collection, review_token, fsAssetstore
):
    coll = reviewed_collection['collection']

    resp = server.request('/collection/%s' % coll['_id'], token=review_token)
    assertStatusOk(resp)
    assert resp.json['name'] == 'Curated dataset'

    resp = server.request(
        '/folder',
        params={'parentType': 'collection', 'parentId': str(coll['_id'])},
        token=review_token,
    )
    assertStatusOk(resp)
    assert [f['name'] for f in resp.json] == ['data']

    resp = server.request(
        '/folder',
        params={'parentType': 'folder', 'parentId': str(reviewed_collection['top']['_id'])},
        token=review_token,
    )
    assertStatusOk(resp)
    assert [f['name'] for f in resp.json] == ['raw']

    resp = server.request(
        '/item', params={'folderId': str(reviewed_collection['sub']['_id'])}, token=review_token
    )
    assertStatusOk(resp)
    assert [i['name'] for i in resp.json] == ['sample.csv']

    resp = server.request('/item/%s/files' % reviewed_collection['item']['_id'], token=review_token)
    assertStatusOk(resp)


def test_reviewer_can_read_own_user(server, review_token):
    # USER_INFO_READ is in the key's scope purely so this works; without it the web
    # client's normal auth plumbing 401s and pops a login modal.
    resp = server.request('/user/me', token=review_token)
    assertStatusOk(resp)
    assert resp.json['login'].startswith('reviewer-')


def test_session_reports_the_collection_under_review(server, review_token):
    resp = server.request('/review/session', token=review_token)
    assertStatusOk(resp)
    assert resp.json['review']['status'] == 'open'
    assert resp.json['collection']['name'] == 'Curated dataset'


def test_session_is_null_for_anonymous_callers(server, db):
    resp = server.request('/review/session')
    assertStatusOk(resp)
    assert resp.json['review'] is None


def test_session_rejects_an_unknown_key(server, db):
    resp = server.request('/review/session', method='POST', params={'key': 'nope'})
    assertStatus(resp, 400)


def test_session_rejects_a_personal_api_key(server, user):
    """A key that is not tied to an open review must not open a review session."""
    resp = server.request('/api_key', method='POST', params={'name': 'mine'}, user=user)
    assertStatusOk(resp)
    personal = ApiKey().load(resp.json['_id'], force=True)

    resp = server.request('/review/session', method='POST', params={'key': personal['key']})
    assertStatus(resp, 400)
