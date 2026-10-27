"""
Shared mechanics for putting a mesh onto a character in the scene.

Gear (:mod:`gear_api`) and whole-character variants (:mod:`variant_api`) are the
same operation underneath: bring a mesh in from its own source file, merge the
joints it needs into the character's skeleton, and rebind its skin cluster onto
those joints. Only what the mesh *means* differs - a shirt occupies a slot, a
variant replaces the body - so the mechanics live here and the two APIs supply
the meaning.

Joints are reference counted
----------------------------
A joint records **every** asset that needs it, not just the one that created it,
in :data:`MCA_JOINT_SOURCE`. Two hats sharing ``head_gear_01`` both list
themselves; taking one off removes its id and leaves the joint, and only the
last one out deletes it. That counting spans gear and variants, so a variant
that brings a joint a hat also needs will not strand the hat when it is swapped.

Joints the character arrived with never carry the attribute, which is how
"is this joint ours to delete" is answered without a second bookkeeping list.

:Requires: mca.common.assetlist, mca.mya.rigging, mca.mya.deformations
:Side effects: Imports files into the scene, creates and deletes joints, and
    rebinds skin clusters. Writes are wrapped in an undo chunk - see
    :func:`import_source_file` for why an import cannot be undone.
"""

# python imports
import functools
import json
import os
import re
import traceback

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_manager
from mca.mya.deformations import skin_utils
from mca.mya.modifiers import contexts
from mca.mya.rigging import skel_utils
from mca.mya.rigging.frag import frag_root

logger = log.MCA_LOGGER

# Attribute holding the JSON list of asset ids that need a joint.
MCA_JOINT_SOURCE = 'mcaJointSource'

# What the attribute was called when only gear used it. Read, never written, so
# a scene saved before variants existed still unequips correctly.
LEGACY_JOINT_SOURCE = 'mcaGearSource'

# Set by :func:`import_source_file`. Maya's file import wipes the undo queue, so
# anything recorded after it is a half-operation waiting to corrupt the scene;
# :func:`safe` flushes on the way out when this is set.
undo_queue_wrecked = False


def response(ok, result=None, message=''):
    """
    :param bool ok: Success flag.
    :param object result: JSON-serialisable result.
    :param str message: Human readable summary.
    :return: The standard response dict.
    :rtype: dict
    """

    return {'ok': ok, 'result': result, 'message': message}


def safe(func):
    """
    Decorator: turn exceptions into failed responses, inside one undo chunk,
    leaving the selection as it found it.

    Scene edits are grouped into one chunk so they undo together rather than
    one node at a time.

    An import is the exception: Maya's file import wipes
    the undo queue (see :func:`import_source_file`), so there is nothing left for
    Ctrl+Z to reverse. Rather than leave the half of the operation that *did*
    record - which handed the character back joints it never had - the queue is
    flushed on the way out. Anything that imports nothing undoes normally.

    Importing and skinning both take the selection over, and it is jarring to
    lose what you had picked because you double-clicked a shirt, so
    :func:`~mca.mya.modifiers.contexts.maintained_selection_context` puts it
    back - dropping anything the call deleted, which is how a swap should
    behave.

    :param callable func: API function returning ``(result, message)``.
    :return: Wrapped function returning a response dict.
    :rtype: callable
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global undo_queue_wrecked
        undo_queue_wrecked = False
        try:
            # Selection restore goes *inside* the undo chunk. Outside it, the
            # reselect is its own undo entry and the user's first Ctrl+Z eats
            # that instead of the equip, which reads as "undo did nothing".
            with contexts.undo_chunk_context('mca_swap_{}'.format(func.__name__)):
                with contexts.maintained_selection_context():
                    result, message = func(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            return response(False, None, str(exc).strip("'\""))
        except Exception as exc:
            logger.error('%s failed: %s\n%s',
                         func.__qualname__, exc, traceback.format_exc())
            return response(False, None, '{}: {}'.format(type(exc).__name__, exc))
        finally:
            if undo_queue_wrecked:
                # Leave nothing behind rather than half an equip. See
                # import_source_file for why there is nothing to preserve.
                try:
                    cmds.flushUndo()
                except Exception:
                    logger.debug('Could not flush the undo queue.', exc_info=True)
                undo_queue_wrecked = False
        return response(True, result, message)

    return wrapper


def manager():
    """
    :return: The shared asset manager.
    :rtype: asset_manager.AssetManager
    """

    return asset_manager.get_asset_manager()


def require_record(asset_id):
    """
    Resolve an asset id (or display name) to its registry record.

    :param str asset_id: Asset id or display name.
    :return: The matching record.
    :rtype: asset_manager.AssetRecord
    :raises ValueError: When the id is empty or unknown.
    """

    if not asset_id:
        raise ValueError('asset_id is required.')
    asset_list = manager()
    record = asset_list.get_record(asset_id) or asset_list.get_record_by_name(asset_id)
    if not record:
        raise ValueError('No asset with id or name {!r}. Use assetlist_api.search_assets '
                         'to find it.'.format(asset_id))
    return record


def character_roots():
    """
    Find every character in the scene that a mesh can be put on.

    :return: ``[(frag_root_node, root_joint, asset_id)]`` for each rig found.
    :rtype: list[tuple]
    """

    found = []
    for node in (frag_root.get_all_frag_roots() or []):
        try:
            root_joint = node.root_joint
        except Exception:
            root_joint = None
        if root_joint is None:
            continue
        try:
            asset_id = node.assetID
        except Exception:
            asset_id = ''
        found.append((node, root_joint, character_key(asset_id, root_joint)))
    return found


def has_source_file(record, kinds=('rig', 'skin', 'mesh')):
    """
    Does a record resolve to a Maya source file on disk?

    :param record: The registry record.
    :param tuple kinds: File kinds to try, in order.
    :return: True when any of them resolves.
    :rtype: bool
    """

    entry = getattr(record, 'source_entry', None)
    if entry is None:
        return False
    for kind in kinds:
        try:
            if entry.resolve_file(kind):
                return True
        except Exception:
            continue
    return False


def _best_record_for(candidate):
    """
    Resolve a name or id to the record most likely to be the one in the scene.

    Character display names are not unique in this depot: seven characters have
    two records each, one of which stores an engine path in ``path`` and so
    resolves to nothing on disk. Preferring a record with a real file picks the
    usable one without needing the data cleaned up first.

    :param str candidate: An asset id or display name.
    :return: The best matching record, or None.
    :rtype: AssetRecord or None
    """

    asset_list = manager()
    matches = []
    for found in (asset_list.get_record(candidate), asset_list.get_record_by_name(candidate)):
        if found is not None and found not in matches:
            matches.append(found)

    # Same display name, different record: consider those too.
    for record in asset_list.iter_all():
        if record in matches:
            continue
        if (record.name or '').lower() == str(candidate).lower():
            matches.append(record)

    if not matches:
        return None
    for record in matches:
        if has_source_file(record):
            return record
    return matches[0]


def character_key(asset_id, root_joint):
    '''
    A stable key for a character in the scene.

    The FRAG root's ``assetID`` is the right answer, but plenty of rigs in the
    depot were built without it. Rather than keying off an empty string - which
    would name the group ``_gear_grp`` and make two characters collide - the rig
    assembly's name (``jellybeanbase_all``) is looked up in the asset list, and
    only then the root joint's namespace.

    Where two records answer to the same name - and the depot has seven such
    pairs - the one with a Maya source file on disk wins. The rig in the scene
    was loaded from a file, so a record that resolves to no file cannot be the
    one it came from, however well its name matches.

    :param str asset_id: The FRAG root's assetID, possibly empty.
    :param pm.nt.Joint root_joint: The character's root joint.
    :return: A non-empty key.
    :rtype: str
    '''

    if asset_id:
        return asset_id

    parent = root_joint.getParent()
    if parent is not None:
        stem = parent.nodeName().split(':')[-1]
        for candidate in (stem, re.sub(r'_all$', '', stem)):
            if not candidate:
                continue
            record = _best_record_for(candidate)
            if record:
                return record.asset_id

    name = root_joint.nodeName()
    if ':' in name:
        return name.rsplit(':', 1)[0]
    return parent.nodeName() if parent is not None else name


def resolve_character(character=None):
    """
    Work out which character in the scene the caller means.

    :param str character: Asset id or name. When omitted and exactly one
        character is in the scene, that one is used.
    :return: ``(frag_root_node, root_joint, asset_id)``.
    :rtype: tuple
    :raises ValueError: When there is no character, or the choice is ambiguous.
    """

    roots = character_roots()
    if not roots:
        raise ValueError('No character rig found in the scene. Import one with the Summoner '
                         'first; gear and variants go onto a character, not on their own.')

    if not character:
        if len(roots) == 1:
            return roots[0]
        names = ', '.join(sorted(r[2] for r in roots))
        raise ValueError('{} characters are in the scene ({}); say which one to use.'
                         .format(len(roots), names))

    wanted = str(character).lower()
    for node, root_joint, asset_id in roots:
        if asset_id.lower() == wanted:
            return node, root_joint, asset_id
    # Fall back to the display name, which is what a user is likely to type.
    record = manager().get_record_by_name(character)
    if record:
        for node, root_joint, asset_id in roots:
            if asset_id.lower() == record.asset_id.lower():
                return node, root_joint, asset_id

    present = ', '.join(sorted(r[2] for r in roots)) or 'none'
    raise ValueError('{!r} is not in the scene. Present: {}.'.format(character, present))


def joint_sources(joint_node):
    """
    Read the asset ids recorded against a joint.

    :param pm.nt.Joint joint_node: Joint to inspect.
    :return: Asset ids that need this joint.
    :rtype: list[str]
    """

    attribute = MCA_JOINT_SOURCE
    if not joint_node.hasAttr(attribute):
        # A scene saved while the attribute was still gear-specific.
        attribute = LEGACY_JOINT_SOURCE
        if not joint_node.hasAttr(attribute):
            return []
    raw = joint_node.attr(attribute).get() or ''
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        # Tolerate a hand-edited single id.
        return [raw]
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def set_joint_sources(joint_node, sources):
    """
    Write the asset ids against a joint, removing the attribute when empty.

    :param pm.nt.Joint joint_node: Joint to tag.
    :param list[str] sources: Asset ids that need it.
    """

    if not sources:
        for attribute in (MCA_JOINT_SOURCE, LEGACY_JOINT_SOURCE):
            if joint_node.hasAttr(attribute):
                joint_node.attr(attribute).unlock()
                joint_node.deleteAttr(attribute)
        return
    if not joint_node.hasAttr(MCA_JOINT_SOURCE):
        joint_node.addAttr(MCA_JOINT_SOURCE, dt='string')
    joint_node.attr(MCA_JOINT_SOURCE).set(json.dumps(sorted(set(sources))))


def tag_joints(root_joint, joint_names, asset_id):
    """
    Record that an asset needs each of the given joints.

    Only joints that were brought in are tagged; a joint that belongs to the
    character skeleton is left alone so it can never be deleted on the way out.

    :param pm.nt.Joint root_joint: Character skeleton root.
    :param set joint_names: Joint names the incoming skeleton declares.
    :param str asset_id: The asset id.
    :return: Number of joints tagged.
    :rtype: int
    """

    skeleton = skel_utils.create_skeleton_dict(root_joint)
    tagged = 0
    for name in joint_names:
        joint_node = skeleton.get(name)
        if joint_node is None:
            continue
        sources = joint_sources(joint_node)
        if asset_id not in sources:
            sources.append(asset_id)
            set_joint_sources(joint_node, sources)
        tagged += 1
    return tagged


def release_joints(root_joint, asset_id):
    """
    Drop an asset's claim on the joints it needed, deleting any left unused.

    :param pm.nt.Joint root_joint: Character skeleton root.
    :param str asset_id: The asset being removed.
    :return: ``(released, deleted)`` joint name lists.
    :rtype: tuple
    """

    released, deletable = [], []
    for joint_node in ([root_joint] + list(root_joint.listRelatives(ad=True, type='joint'))):
        sources = joint_sources(joint_node)
        if asset_id not in sources:
            continue
        released.append(joint_node.nodeName())
        sources.remove(asset_id)
        set_joint_sources(joint_node, sources)
        if not sources:
            deletable.append(joint_node)

    # Delete deepest first so a parent never takes its children with it.
    deleted = []
    for joint_node in sorted(deletable, key=lambda j: len(j.longName().split('|')), reverse=True):
        if not pm.objExists(joint_node):
            continue
        # A joint still driving a skin cluster is left in place; something else
        # is using it even though the markup says otherwise.
        if joint_node.listConnections(type='skinCluster'):
            logger.debug('Keeping %s: still connected to a skin cluster.', joint_node)
            continue
        deleted.append(joint_node.nodeName())
        pm.delete(joint_node)
    return released, deleted


# --- Equipped state -----------------------------------------------------------------------------------------------

def import_source_file(file_path):
    """
    Import a source file and return the nodes it brought in.

    Maya's file import is not undoable and, worse, it flushes the whole undo
    queue - verified: a node created before the import survives Ctrl+Z and Maya
    reports "there are no more commands to undo". Everything after the import
    does queue normally, which is the dangerous part: undoing an equip used to
    reverse only the tail and hand the character back 26 joints it never had.

    So this flags the queue as wrecked and :func:`safe` flushes on the way out.
    That costs nothing - the history was already destroyed by the import itself,
    not by the flush - and it means Ctrl+Z after an equip does nothing rather
    than something wrong. Each API offers an explicit reverse instead -
    ``gear_api.unequip``, ``variant_api.revert_variant``.

    :param str file_path: Absolute path to a .ma / .fbx.
    :return: The newly created nodes.
    :rtype: list
    """

    global undo_queue_wrecked

    before = set(pm.ls(assemblies=True))
    cmds.file(file_path, i=True, ignoreVersion=True, mergeNamespacesOnClash=True,
              namespace=':', preserveReferences=False, returnNewNodes=False)
    undo_queue_wrecked = True
    after = set(pm.ls(assemblies=True))
    return list(after - before)


def skinned_meshes_under(nodes):
    """
    Collect the meshes carrying a skin cluster from a set of imported nodes.

    :param list nodes: Imported top-level nodes.
    :return: Mesh transforms that are skinned.
    :rtype: list
    """

    meshes = []
    for node in nodes:
        if not pm.objExists(node):
            continue
        candidates = [node] + list(node.listRelatives(ad=True, type='transform'))
        for candidate in candidates:
            if not candidate.getShapes(type='mesh'):
                continue
            if skin_utils.find_related_skin_cluster(candidate):
                meshes.append(candidate)
    return meshes
