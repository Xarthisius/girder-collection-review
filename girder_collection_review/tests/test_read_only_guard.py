"""The ``auth.user.get`` guard that makes a review session read-only.

Token scope alone is not sufficient. ``PUT /collection/:id`` is declared
``@access.user(scope=TokenScope.DATA_READ)`` in core, so a review token satisfies its scope
and reaches the handler; plugins declare worse. These tests pin the guard's behaviour, and
equally that it is invisible to everybody else.
"""

import pytest
from girder.models.collection import Collection
from pytest_girder.assertions import assertStatus, assertStatusOk

pytestmark = pytest.mark.plugin('collection_review')


@pytest.mark.parametrize(
    'method,path,params',
    [
        ('POST', '/folder', {'parentType': 'collection', 'name': 'evil'}),
        ('POST', '/item', {'name': 'evil'}),
        ('PUT', '/collection/COLLECTION_ID', {'description': 'defaced'}),
        ('PUT', '/folder/TOP_ID', {'name': 'defaced'}),
        ('DELETE', '/collection/COLLECTION_ID', {}),
        ('POST', '/collection', {'name': 'a collection of my own'}),
        ('PUT', '/item/ITEM_ID', {'name': 'defaced'}),
    ],
)
def test_every_write_is_refused(server, reviewed_collection, review_token, method, path, params):
    """
    Rejected with either 401 (the route declares a scope the review token does not hold) or
    403 (it does, and the guard is what stops it).
    """
    coll = reviewed_collection['collection']
    path = path.replace('COLLECTION_ID', str(coll['_id']))
    path = path.replace('TOP_ID', str(reviewed_collection['top']['_id']))
    path = path.replace('ITEM_ID', str(reviewed_collection['item']['_id']))

    params = dict(params)
    if params.get('parentType') == 'collection':
        params['parentId'] = str(coll['_id'])
    elif path == '/item':
        params['folderId'] = str(reviewed_collection['sub']['_id'])

    resp = server.request(path, method=method, params=params, token=review_token)
    assert resp.output_status.startswith((b'401', b'403')), resp.output_status

    assert Collection().load(coll['_id'], force=True)['description'] == 'Under review'


def test_guard_blocks_the_data_read_write_route(server, reviewed_collection, review_token):
    """
    ``PUT /collection/:id`` is the case scope cannot cover, so assert the guard by name.
    Only its ``modelParam(level=WRITE)`` would otherwise stand in the way, which is a
    property of that one route rather than of the token.
    """
    resp = server.request(
        '/collection/%s' % reviewed_collection['collection']['_id'],
        method='PUT',
        params={'description': 'defaced'},
        token=review_token,
    )
    assertStatus(resp, 403)
    assert resp.json['message'] == 'Review sessions are read-only.'


def test_guard_does_not_affect_normal_users(server, admin, user, reviewed_collection, review):
    """The guard must be invisible to everyone who is not in a review session."""
    resp = server.request(
        '/folder',
        method='POST',
        params={
            'parentType': 'collection',
            'parentId': str(reviewed_collection['collection']['_id']),
            'name': 'more data',
        },
        user=user,
    )
    assertStatusOk(resp)

    resp = server.request(
        '/collection/%s' % reviewed_collection['collection']['_id'],
        method='PUT',
        params={'description': 'still editable'},
        user=user,
    )
    assertStatusOk(resp)

    resp = server.request('/collection', method='POST', params={'name': 'admin coll'}, user=admin)
    assertStatusOk(resp)


def test_reviewer_can_end_own_session(server, reviewed_collection, review_token):
    """
    DELETE from a review token is normally refused, but this one route is exempt so a
    reviewer can log themselves out -- core's logout route requires USER_AUTH, which a
    review token does not carry.
    """
    resp = server.request('/review/session', method='DELETE', token=review_token)
    assertStatusOk(resp)

    resp = server.request(
        '/collection/%s' % reviewed_collection['collection']['_id'], token=review_token
    )
    # 401, not 403: the token is gone entirely, so the request is anonymous.
    assertStatus(resp, 401)
