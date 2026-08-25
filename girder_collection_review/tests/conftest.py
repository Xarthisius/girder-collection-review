"""Shared fixtures for the collection-review tests.

Girder's own fixtures (``db``, ``server``, ``admin``, ``user``, ``fsAssetstore``) come from
pytest-girder; everything here is specific to this plugin. It lives in a conftest rather
than being imported between test modules so pytest resolves it without cross-module fixture
imports.

Each test module declares ``pytestmark = pytest.mark.plugin('collection_review')`` itself.
That marker cannot live here: pytest only honors module- and class-level ``pytestmark``, so
a ``pytestmark`` in a conftest would be silently ignored and every test would run against a
server without the plugin loaded.
"""

import pytest
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.item import Item
from pytest_girder.assertions import assertStatusOk


def open_review(server, user, collection, duration=None):
    """Open a review round as ``user``. Returns the response JSON, including ``key``."""
    params = {'collectionId': str(collection['_id'])}
    if duration is not None:
        params['duration'] = duration

    resp = server.request('/review', method='POST', params=params, user=user)
    assertStatusOk(resp)

    return resp.json


def start_session(server, key):
    """Exchange a review key for a session. Returns the auth token string."""
    resp = server.request('/review/session', method='POST', params={'key': key})
    assertStatusOk(resp)

    return resp.json['authToken']['token']


def other_collection(user, name='Elsewhere'):
    """A second collection, outside any review, to move folders in and out of."""
    return Collection().createCollection(name, creator=user, description='', public=False)


@pytest.fixture
def reviewed_collection(db, user):
    """A private collection owned by ``user``, with a nested folder and an item."""
    coll = Collection().createCollection(
        'Curated dataset', creator=user, description='Under review', public=False
    )
    top = Folder().createFolder(coll, 'data', parentType='collection', creator=user, public=False)
    sub = Folder().createFolder(top, 'raw', parentType='folder', creator=user, public=False)
    item = Item().createItem('sample.csv', creator=user, folder=sub)

    yield {'collection': coll, 'top': top, 'sub': sub, 'item': item}


@pytest.fixture
def review(server, user, reviewed_collection):
    """An open review on ``reviewed_collection``, as its owner."""
    yield open_review(server, user, reviewed_collection['collection'])


@pytest.fixture
def review_token(server, review):
    """A live reviewer session token for ``review``."""
    yield start_session(server, review['key'])
