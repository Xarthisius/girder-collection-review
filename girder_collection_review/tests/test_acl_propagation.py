"""Keeping the reviewer's ACL in step with the collection's contents.

Creation is handled by core (``Folder().createFolder`` copies the parent's access policies).
Moves are not: ``Folder().move()`` never touches ACLs and propagates to descendants with a
raw ``$set`` that fires no model events, so the REST hooks in ``__init__.py`` are the only
thing covering that path.
"""

import json

import pytest
from girder.models.folder import Folder
from pytest_girder.assertions import assertStatus, assertStatusOk

from .conftest import other_collection

pytestmark = pytest.mark.plugin('collection_review')


def test_folder_created_during_review_is_visible(server, user, reviewed_collection, review_token):
    """Relies on core's copyAccessPolicies; there is deliberately no event hook for this."""
    resp = server.request(
        '/folder',
        method='POST',
        params={
            'parentType': 'collection',
            'parentId': str(reviewed_collection['collection']['_id']),
            'name': 'added later',
        },
        user=user,
    )
    assertStatusOk(resp)
    newTopId = resp.json['_id']

    resp = server.request(
        '/folder',
        method='POST',
        params={
            'parentType': 'folder',
            'parentId': newTopId,
            'name': 'nested later',
        },
        user=user,
    )
    assertStatusOk(resp)
    nestedId = resp.json['_id']

    for folderId in (newTopId, nestedId):
        resp = server.request('/folder/%s' % folderId, token=review_token)
        assertStatusOk(resp)


def test_folder_moved_into_collection_is_visible(server, user, reviewed_collection, review_token):
    """Exercises the ``rest.put.folder/:id.after`` hook, including descendants."""
    outside = other_collection(user)
    stray = Folder().createFolder(
        outside, 'stray', parentType='collection', creator=user, public=False
    )
    strayChild = Folder().createFolder(
        stray, 'stray child', parentType='folder', creator=user, public=False
    )

    resp = server.request('/folder/%s' % stray['_id'], token=review_token)
    assertStatus(resp, 403)

    resp = server.request(
        '/folder/%s' % stray['_id'],
        method='PUT',
        params={
            'parentType': 'collection',
            'parentId': str(reviewed_collection['collection']['_id']),
        },
        user=user,
    )
    assertStatusOk(resp)

    for folderId in (stray['_id'], strayChild['_id']):
        resp = server.request('/folder/%s' % folderId, token=review_token)
        assertStatusOk(resp)


def test_folder_moved_out_of_collection_is_hidden(server, user, reviewed_collection, review_token):
    outside = other_collection(user)

    resp = server.request('/folder/%s' % reviewed_collection['top']['_id'], token=review_token)
    assertStatusOk(resp)

    resp = server.request(
        '/folder/%s' % reviewed_collection['top']['_id'],
        method='PUT',
        params={'parentType': 'collection', 'parentId': str(outside['_id'])},
        user=user,
    )
    assertStatusOk(resp)

    for folderId in (reviewed_collection['top']['_id'], reviewed_collection['sub']['_id']):
        resp = server.request('/folder/%s' % folderId, token=review_token)
        assertStatus(resp, 403)


def test_rename_does_not_change_visibility(server, user, reviewed_collection, review_token):
    """
    The sync runs on every ``PUT /folder/:id`` -- it cannot be gated on the ``parentId``
    param, because autoDescribeRoute empties the params dict before the .after event fires.
    So a plain rename must be a no-op, which is what the short-circuit in syncMovedFolder is
    for.
    """
    resp = server.request(
        '/folder/%s' % reviewed_collection['top']['_id'],
        method='PUT',
        params={'name': 'renamed'},
        user=user,
    )
    assertStatusOk(resp)

    resp = server.request('/folder/%s' % reviewed_collection['top']['_id'], token=review_token)
    assertStatusOk(resp)


def test_resource_move_is_synced(server, user, reviewed_collection, review_token):
    """Exercises the ``rest.put.resource/move.before``/``.after`` pair."""
    outside = other_collection(user)
    stray = Folder().createFolder(
        outside, 'stray', parentType='collection', creator=user, public=False
    )

    resp = server.request(
        '/resource/move',
        method='PUT',
        params={
            'resources': json.dumps({'folder': [str(stray['_id'])]}),
            'parentType': 'collection',
            'parentId': str(reviewed_collection['collection']['_id']),
        },
        user=user,
    )
    assertStatusOk(resp)

    resp = server.request('/folder/%s' % stray['_id'], token=review_token)
    assertStatusOk(resp)


def test_resource_move_still_works_for_non_admins(server, user, reviewed_collection, review):
    """
    Regression guard. ``handleRoute`` runs ``Resource._defaultAccess`` over every
    ``rest.*.before`` handler, which calls ``requireAdmin`` on any handler without an
    ``accessLevel``. Dropping ``@access.public`` from ``onResourcesMoveBefore`` would make
    this endpoint admin-only for the whole site.
    """
    assert user['admin'] is False

    outside = other_collection(user, name='Non admin source')
    stray = Folder().createFolder(
        outside, 'stray', parentType='collection', creator=user, public=False
    )

    resp = server.request(
        '/resource/move',
        method='PUT',
        params={
            'resources': json.dumps({'folder': [str(stray['_id'])]}),
            'parentType': 'collection',
            'parentId': str(reviewed_collection['collection']['_id']),
        },
        user=user,
    )
    assertStatusOk(resp)
