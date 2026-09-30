"""
Clearing the rubbish out of a Maya scene, and saving it.

A scene that has been through a few imports, a few reference swaps and a plugin nobody has any
more collects nodes that do nothing: unknown nodes from plugins that are gone, empty shading
groups, orphaned controller tags, graph editor bookkeeping. They make the file bigger, they make
it slower to open, and some of them make an export fail. :func:`clean_scene` is the pass that
takes them out.

What was wrong before:

- **``backup_scene`` wrote to a hard-coded ``C:\\export_backup``.** Not under the project, not
  under the user's preferences, not configurable, and not a path that exists on a machine that is
  not Windows. It writes beside the rest of this machine's pipeline state now, which is where
  ``mca-common`` puts everything else of the kind.
- **``backup_scene`` cleaned the scene before saving it.** A function called "backup" that
  modifies the thing it is backing up is a poor trade: the file on disk is a *cleaned* copy, and
  the scene the artist is looking at has had nodes deleted out from under it. The clean is a
  separate call now, and the caller decides.
- **``delete_garbage``'s skip list could never match.** ``connection_node in
  ['characterPartition']`` compares a PyNode against a string, which is never equal, so the one
  node it meant to protect was deleted like any other. Its Maya-version check
  (``get_version() > 2014``) is dead, and inside it was a second dead check - ``if
  'hyperGraphLayout' in straight_delete_types: remove(...)`` - on a list that has just been built
  from two literals, neither of which is that.
- **``clean_imported_nodes`` broke every name it answered with.** ``node.replace('|', '')`` strips
  the separators out of a DAG path, so ``grpA|grpB|pSphere1`` came back as ``grpAgrpBpSphere1`` -
  a name for nothing. It also used the *old* Maya API, ``maya.OpenMaya``, alone among the modules
  in this package, and its index bookkeeping assumed one node added to a selection list is one
  entry in it, which is not true of a name with a wildcard in it.
- **Two functions were second copies of other modules' work.**
  ``scene_utils.delete_empty_namespaces`` and ``scene_utils.delete_empty_display_layers`` did
  the same jobs as the ones in :mod:`mca.mya.utils.namespace` and
  :mod:`mca.mya.utils.display_layers`, differently. They call those now.
- ``delete_unused_plugins`` began by checking ``if 'unknownPlugin' not in dir(pm)``, for a Maya
  old enough not to have the command. Every Maya the pipeline supports has it.
"""

# python imports
import os
import traceback

# software specific imports
import maya.api.OpenMaya as om2
import maya.cmds as cmds
import maya.mel as mel
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.paths import project_paths
from mca.common.utils import fileio
from mca.mya.modifiers import ma_decorators
from mca.mya.utils import display_layers
from mca.mya.utils import maya_utils
from mca.mya.utils import namespace
from mca.mya.utils import node_util


logger = log.MCA_LOGGER

#: How many backups to keep before writing over the oldest.
MAX_BACKUPS = 10

#: What a backup is called when the caller does not say.
DEFAULT_BACKUP_NAME = 'mca_backup'

#: Node types that are always rubbish once nothing is using them.
GARBAGE_NODE_TYPES = ('hyperLayout', 'hyperView')

#: Node types worth deleting only when nothing is connected to them.
CONNECTION_CHECKED_TYPES = ('shadingEngine', 'partition', 'objectSet')

#: Nodes in those types that are Maya's own, whatever their connections say. Compared by name -
#: the version this replaces compared a PyNode against these strings, which is never equal.
GARBAGE_SKIP_NAMES = ('characterPartition',)

#: The nodes Turtle leaves behind. Turtle was Maya's old bake renderer; its nodes survive in any
#: scene that has ever been opened with it loaded.
TURTLE_NODE_TYPES = ('ilrBakeLayer', 'ilrBakeLayerManager', 'ilrOptionsNode', 'ilrUIOptionsNode')


def delete_unknown_nodes():
    """
    Delete the nodes left behind by a plugin this Maya does not have.

    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for node in cmds.ls(type='unknown') or []:
        if not cmds.objExists(node):
            continue
        cmds.lockNode(node, lock=False)
        try:
            cmds.delete(node)
        except RuntimeError as error:
            logger.debug('Could not delete the unknown node %s: %s', node, error)
            continue
        deleted.append(node)

    if deleted:
        logger.info('Deleted unknown nodes: %s', ', '.join(deleted))
    return deleted


def delete_turtle_nodes():
    """
    Delete Turtle's nodes, if Turtle is loaded.

    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    plugins_in_use = cmds.pluginInfo(query=True, pluginsInUse=True) or []
    # pluginInfo answers a flat list of name, version, name, version - so the names are every
    # other entry.
    if 'Turtle' not in plugins_in_use[::2]:
        return []

    deleted = maya_utils.delete_nodes_of_type(list(TURTLE_NODE_TYPES))
    if deleted:
        logger.info('Removed Turtle nodes: %s', ', '.join(deleted))
    return deleted


def delete_unused_plugins():
    """
    Tell Maya to stop asking for plugins the scene does not need.

    A scene remembers every plugin it has ever been saved with, and Maya warns about each missing
    one on every open. This is only safe once the unknown nodes are gone, so
    :func:`delete_unknown_nodes` runs first in :func:`clean_scene`.

    :return: The plugins the scene will no longer ask for.
    :rtype: list(str)
    """

    if cmds.ls(type='unknown'):
        # Removing the plugin while its nodes are still in the scene loses the nodes' data.
        logger.debug('There are still unknown nodes, so no plugin requirement was removed.')
        return []

    removed = []
    for plugin_name in cmds.unknownPlugin(query=True, list=True) or []:
        try:
            cmds.unknownPlugin(plugin_name, remove=True)
        except RuntimeError as error:
            logger.debug('Could not stop the scene asking for %s: %s', plugin_name, error)
            continue
        removed.append(plugin_name)

    if removed:
        logger.info('Removed unused plugin requirements: %s', ', '.join(removed))
    return removed


def delete_garbage():
    """
    Delete the bookkeeping nodes nothing is using.

    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    deleted = maya_utils.delete_nodes_of_type(list(GARBAGE_NODE_TYPES))

    for node_type in CONNECTION_CHECKED_TYPES:
        for node in cmds.ls(type=node_type) or []:
            if not cmds.objExists(node):
                continue
            if node.split('|')[-1].split(':')[-1] in GARBAGE_SKIP_NAMES:
                continue
            if not node_util.is_empty(pm.PyNode(node)):
                continue
            cmds.lockNode(node, lock=False)
            try:
                cmds.delete(node)
            except RuntimeError as error:
                logger.debug('Could not delete %s: %s', node, error)
                continue
            deleted.append(node)

    if deleted:
        logger.info('Deleted garbage nodes: %s', ', '.join(deleted))
    return deleted


def delete_unused_shader_nodes():
    """
    Run Maya's own "delete unused nodes" over the shading network.

    Only in an interactive Maya: the command is a menu item in the Hypershade, driven through MEL,
    and a batch Maya has not loaded the script that defines it.

    Since Maya 2020 the command fails when the default ``standardSurface1`` material is assigned
    to nothing, so a cube is made, shaded with it, and thrown away again.

    :return: Whether the pass ran.
    :rtype: bool
    """

    if cmds.about(batch=True):
        logger.debug('The unused-shader pass needs an interactive Maya.')
        return False

    temp_cube = None
    try:
        temp_cube = pm.polyCube(name='TEMP_StandardSurface_Assignment')[0]
        temp_group = pm.sets(renderable=True, noSurfaceShader=True, empty=True,
                             name='standardSurface1SG')
        pm.PyNode('standardSurface1').outColor.connect(temp_group.surfaceShader)
        pm.sets(temp_group, edit=True, forceElement=temp_cube)
        mel.eval('hyperShadePanelMenuCommand("hyperShadePanel1", "deleteUnusedNodes");')
    except Exception as error:                                          # noqa: BLE001
        logger.warning('The unused-shader pass did not finish: %s', error)
        return False
    finally:
        if temp_cube and pm.objExists(temp_cube):
            pm.delete(temp_cube)
    return True


def delete_empty_namespaces():
    """
    Remove every namespace with nothing in it.

    :mod:`mca.mya.utils.namespace` holds the implementation; this module had a second one of its
    own, which walked the scene differently and answered differently.

    :return: The namespaces that were removed.
    :rtype: list(str)
    """

    return namespace.delete_empty_namespaces()


def delete_empty_display_layers():
    """
    Remove every display layer with nothing on it.

    :mod:`mca.mya.utils.display_layers` holds the implementation; this module had a second one.

    :return: The layers that were deleted.
    :rtype: list(str)
    """

    return display_layers.delete_empty_display_layers()


def delete_render_layers():
    """
    Delete every render layer but Maya's own.

    :return: The names of the layers that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for layer in cmds.ls(type='renderLayer') or []:
        if layer == 'defaultRenderLayer':
            continue
        if not cmds.objExists(layer):
            continue
        try:
            cmds.delete(layer)
        except RuntimeError as error:
            logger.debug('Could not delete the render layer %s: %s', layer, error)
            continue
        deleted.append(layer)

    if deleted:
        logger.info('Deleted render layers: %s', ', '.join(deleted))
    return deleted


def _delete_orphans(node_type, label, has_owner=None):
    """
    Delete every node of a type that nothing is connected to.

    :param str node_type: The Maya node type.
    :param str label: What to call them in the log.
    :param callable has_owner: Asked about each node instead of "has any connection", where the
        type keeps its owner somewhere particular.
    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for node in cmds.ls(type=node_type) or []:
        if not cmds.objExists(node):
            continue
        if has_owner is not None:
            if has_owner(node):
                continue
        elif cmds.listConnections(node):
            continue
        try:
            cmds.delete(node)
        except RuntimeError as error:
            logger.debug('Could not delete %s: %s', node, error)
            continue
        deleted.append(node)

    if deleted:
        logger.info('Deleted orphaned %s: %s', label, ', '.join(deleted))
    return deleted


def delete_orphaned_controller_tags():
    """
    Delete controller tags whose control is gone.

    A controller tag is judged by its ``controllerObject`` rather than by its connections,
    because tags are wired to each other to describe pick-walking and so always have some.

    :return: The names of the tags that were deleted.
    :rtype: list(str)
    """

    return _delete_orphans(
        'controller', 'controller tags',
        has_owner=lambda node: bool(cmds.listConnections('{}.controllerObject'.format(node))))


def delete_orphaned_group_id_nodes():
    """
    :return: The names of the groupId nodes nothing was using, now deleted.
    :rtype: list(str)
    """

    return _delete_orphans('groupId', 'groupId nodes')


def delete_orphaned_time_editor_tracks():
    """
    :return: The names of the time editor track nodes nothing was using, now deleted.
    :rtype: list(str)
    """

    return _delete_orphans('timeEditorTracks', 'time editor tracks')


def delete_orphaned_graph_editor_infos():
    """
    :return: The names of the graph editor bookkeeping nodes nothing was using, now deleted.
    :rtype: list(str)
    """

    return _delete_orphans('nodeGraphEditorInfo', 'graph editor info nodes')


def delete_orphaned_reference_nodes():
    """
    Delete reference nodes that reference nothing.

    A locked reference node is Maya's own and is left alone.

    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for node in cmds.ls(type='reference') or []:
        if not cmds.objExists(node) or cmds.lockNode(node, query=True, lock=True)[0]:
            continue
        if cmds.listConnections(node):
            continue
        try:
            cmds.delete(node)
        except RuntimeError as error:
            logger.debug('Could not delete the reference node %s: %s', node, error)
            continue
        deleted.append(node)

    if deleted:
        logger.info('Deleted orphaned reference nodes: %s', ', '.join(deleted))
    return deleted


def delete_orphaned_nodes():
    """
    Every orphan pass, in one call.

    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    deleted = []
    deleted += delete_orphaned_controller_tags()
    deleted += delete_orphaned_group_id_nodes()
    deleted += delete_orphaned_time_editor_tracks()
    deleted += delete_orphaned_graph_editor_infos()
    deleted += delete_orphaned_reference_nodes()
    return deleted


def clean_scene():
    """
    Every clean-up pass, in the order they have to run in.

    The unknown nodes go before the plugin requirements, because removing a plugin's requirement
    while its nodes are still in the scene loses what those nodes held.

    :return: The names of everything that was deleted.
    :rtype: list(str)
    """

    deleted = []
    deleted += delete_unknown_nodes()
    deleted += delete_turtle_nodes()
    deleted += delete_unused_plugins()
    deleted += delete_garbage()
    delete_unused_shader_nodes()
    deleted += delete_empty_namespaces()
    deleted += delete_empty_display_layers()
    deleted += delete_render_layers()
    deleted += delete_orphaned_nodes()
    return deleted


def backup_folder():
    """
    Where this machine keeps scene backups.

    Under the pipeline's own preferences folder, beside the logs - not the hard-coded
    ``C:\\export_backup`` the version this replaces used, which is not a path that exists on a
    machine that is not Windows and not one anybody could point somewhere else.

    :return: The folder. Made if it is not there.
    :rtype: str
    """

    folder = os.path.join(project_paths.get_preferences_root(), 'scene_backups')
    fileio.touch_path(os.path.join(folder, ''))
    return os.path.normpath(folder)


def backup_scene(backup_name=None, clean=False):
    """
    Save a copy of the scene, keeping the last :data:`MAX_BACKUPS` of them.

    The scene's own name is put back afterwards, so this does not turn the artist's file into the
    backup.

    :param str backup_name: What to call it. ``'mca_backup'`` otherwise.
    :param bool clean: Run :func:`clean_scene` first. The version this replaces did this
        unconditionally, which means a function called "backup" deleted nodes out of the scene the
        artist was looking at, and wrote a file that is not what they had.
    :return: The path the backup was written to, or '' when it could not be written.
    :rtype: str
    """

    scene_name = cmds.file(query=True, sceneName=True)
    backup_name = backup_name or DEFAULT_BACKUP_NAME

    if clean:
        clean_scene()

    folder = backup_folder()
    existing = sorted(
        (os.path.join(folder, name) for name in os.listdir(folder)
         if name.endswith('.ma') and backup_name in name),
        key=os.path.getmtime)

    if len(existing) >= MAX_BACKUPS:
        # Over the oldest one.
        backup_path = existing[0]
    else:
        backup_path = os.path.join(folder, '{}{}.ma'.format(backup_name, len(existing) + 1))

    try:
        pm.saveAs(backup_path, force=True)
    except Exception as error:                                          # noqa: BLE001
        logger.warning('Could not write the backup %s: %s', backup_path, error)
        return ''
    finally:
        if scene_name:
            pm.renameFile(scene_name)

    logger.info('Backed the scene up to %s.', backup_path)
    return backup_path


@ma_decorators.not_undoable_decorator
def clean_imported_nodes(new_nodes):
    """
    Throw away everything an import brought in that is not geometry.

    An FBX or an OBJ arrives with its own lights, cameras, materials and layers. This keeps the
    transforms and the meshes, shades them with Maya's default, and deletes the rest.

    :param new_nodes: The names of the nodes the import made.
    :type new_nodes: list(str)
    :return: The names of the transforms that were kept, as full DAG paths. The version this
        replaces answered with ``name.replace('|', '')`` - the path with its separators deleted,
        which names nothing at all.
    :rtype: list(str)
    """

    kept = []
    junk = []

    for name in new_nodes:
        if not cmds.objExists(name):
            continue
        # One name at a time. The version this replaces added every name to one selection list
        # and then read them back by index, which assumes one name is one entry - not true of a
        # name with a wildcard in it.
        selection = om2.MSelectionList()
        try:
            selection.add(name)
        except RuntimeError:
            logger.debug('%s is not a node this Maya knows.', name)
            continue
        api_type = selection.getDependNode(0).apiTypeStr

        if api_type == 'kTransform':
            kept.append(name)
        elif api_type != 'kMesh':
            junk.append(name)

    if kept:
        pm.sets('initialShadingGroup', forceElement=kept)
    for name in junk:
        if cmds.objExists(name):
            try:
                cmds.delete(name)
            except RuntimeError as error:
                logger.debug('Could not delete the imported node %s: %s', name, error)
    delete_garbage()
    return kept


def save_as(file_path):
    """
    Save the scene to a path, as ASCII or binary depending on the extension.

    :param str file_path: Where to save it.
    :return: Whether it saved.
    :rtype: bool
    """

    if not file_path:
        return False

    logger.debug('Saving %s.', file_path)
    file_type = 'mayaBinary' if file_path.endswith('.mb') else 'mayaAscii'

    try:
        pm.renameFile(file_path)
        pm.saveFile(type=file_type)
    except Exception:                                                   # noqa: BLE001
        logger.error('Could not save %s:\n%s', file_path, traceback.format_exc())
        if not cmds.about(batch=True):
            pm.confirmDialog(message='Warning:\n\nMaya was unable to save!', button='Confirm')
        return False

    logger.debug('Saved %s.', file_path)
    return True
