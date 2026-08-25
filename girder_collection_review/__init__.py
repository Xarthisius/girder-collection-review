import json
import logging
from pathlib import Path

import cherrypy

from girder import events
from girder.api import access
from girder.models.folder import Folder
from girder.plugin import GirderPlugin, registerPluginStaticContent
from girder.utility.model_importer import ModelImporter

from . import rest, settings  # noqa: F401 -- settings imported for its decorators
from .constants import PLUGIN_NAME
from .lib import guard, provisioning
from .models.review import Review

logger = logging.getLogger(__name__)


def _syncFolderById(folderId):
    folder = Folder().load(folderId, force=True, exc=False)
    if folder is not None:
        provisioning.syncMovedFolder(folder)


#: Attribute on ``cherrypy.request`` carrying folder ids from a move's .before to its .after.
_MOVED_FOLDERS = 'girderCollectionReviewMovedFolders'


def onFolderUpdated(event):
    """
    Re-sync reviewer ACLs after ``PUT /folder/:id``.

    ``Folder().move()`` never touches ACLs and propagates to descendants with a raw ``$set``
    that fires no model events, so the REST layer is the only place a move is observable.
    This cannot be gated on the ``parentId`` parameter: ``autoDescribeRoute`` consumes the
    params dict in place, so by the time the .after event fires it is empty.
    ``syncMovedFolder`` short-circuits on non-moves instead.
    """
    folderId = event.info.get('id')
    if not folderId:
        return

    try:
        _syncFolderById(folderId)
    except Exception:
        logger.exception('Failed to sync review ACLs for folder %s', folderId)


@access.public
def onResourcesMoveBefore(event):
    """
    Stash the folder ids being moved by ``PUT /resource/move``.

    Needed because the .after event can see neither the ids (``autoDescribeRoute`` has
    emptied ``params`` by then) nor the result (``moveResources`` returns nothing).

    The ``@access.public`` decorator is load bearing, not documentation: ``handleRoute``
    passes ``Resource._defaultAccess`` as the ``pre`` callback for every ``rest.*.before``
    handler, and that helper calls ``requireAdmin`` on any handler lacking an
    ``accessLevel`` attribute. Without the decorator, merely binding here would make
    ``PUT /resource/move`` admin-only for everyone. This handler only reads request params,
    and never short-circuits the endpoint, so declaring it public lowers nothing.
    """
    resources = (event.info.get('params') or {}).get('resources')

    if isinstance(resources, str):
        try:
            resources = json.loads(resources)
        except ValueError:
            return

    if not isinstance(resources, dict):
        return

    # Items and files need no work: AccessControlMixin resolves their access through the
    # parent folder, including after a move.
    folderIds = list(resources.get('folder') or ())
    if folderIds:
        setattr(cherrypy.request, _MOVED_FOLDERS, folderIds)


def onResourcesMoveAfter(event):
    """Re-sync reviewer ACLs for the folders stashed by ``onResourcesMoveBefore``."""
    for folderId in getattr(cherrypy.request, _MOVED_FOLDERS, ()):
        try:
            _syncFolderById(folderId)
        except Exception:
            logger.exception('Failed to sync review ACLs for moved folder %s', folderId)


class CollectionReviewPlugin(GirderPlugin):
    DISPLAY_NAME = 'Collection Review'

    def load(self, info):
        ModelImporter.registerModel('collection_review', Review, PLUGIN_NAME)

        # Neither of these is declared by core Folder().initialize(): the subtree grant
        # queries {baseParentId, baseParentType}, and revocation queries access.users.id.
        # Without them both are full collection scans.
        Folder().ensureIndices(
            [
                ([('baseParentId', 1), ('baseParentType', 1)], {}),
                'access.users.id',
            ]
        )

        info['apiRoot'].review = rest.Review()

        guard.bind(events)
        events.bind('rest.put.folder/:id.after', PLUGIN_NAME, onFolderUpdated)
        events.bind('rest.put.resource/move.before', PLUGIN_NAME, onResourcesMoveBefore)
        events.bind('rest.put.resource/move.after', PLUGIN_NAME, onResourcesMoveAfter)

        registerPluginStaticContent(
            plugin='collection_review',
            css=['/style.css'],
            js=['/girder-plugin-collection-review.umd.cjs'],
            staticDir=Path(__file__).parent / 'web_client' / 'dist',
            tree=info['serverRoot'],
        )
