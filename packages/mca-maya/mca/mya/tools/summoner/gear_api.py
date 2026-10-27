"""
Headless gear API: put a piece of gear on a character in the scene, and take it off again.

Every function takes plain values, never raises, and returns
``{'ok': bool, 'result': <json>, 'message': str}`` - the same contract as
``assetlist_api`` and ``toolbox_api``, so the Summoner UI, the in-Maya AI and
the MCP tools all drive the identical code path.

How equipping works
-------------------
Gear is authored against its own skeleton, so its skin cluster is bound to
joints that are not the character's. Rather than keeping two skeletons in the
scene (Maya handles that badly), the gear's joints are merged into the
character's skeleton by name and the gear's skin cluster is rebound onto the
character's joints:

1. Resolve the character in the scene and the gear entry in the registry.
2. Return the character skeleton to bind pose - joints cannot be added safely
   to a posed skeleton.
3. ``skel_utils.import_merge_skeleton`` adds only the joints the character does
   not already have.
4. Import the gear's skinned source file and rebind its meshes with
   ``skin_utils.rebind_mesh_to_skel``, which now resolves every influence
   because step 3 supplied the missing ones.
5. Tag the meshes with their asset id and slot, and tag every joint the gear
   needs with its asset id.

Joints are reference counted
----------------------------
A joint records **every** gear asset that needs it, not just the one that
created it. Two hats sharing ``head_gear_01`` both list themselves; taking one
off removes its id and leaves the joint, and only the last one out deletes it.
Tracking a single owner would let the second hat lose its influences the moment
the first was removed - and ``Head`` alone has 24 competing pieces.

Slots
-----
A character wears one thing per slot. Equipping into an occupied slot removes
what was there first, which is the "double click swaps it out" behaviour.
Gear with no slot recorded falls back to its category, so an unslotted shirt
still replaces the previous shirt rather than stacking.

:Requires: mca.mya.tools.summoner.swap_utils, mca.common.assetlist, mca.mya.rigging
:Side effects: Imports files into the scene, creates and deletes joints, and
    rebinds skin clusters.

The mechanics above - the response contract, the character lookup, the joint
reference counting and the import - are shared with whole-character variants
and live in :mod:`swap_utils`. What is here is what makes gear *gear*: slots,
mesh markup, and which records count as gear at all.
"""

# python imports
import os

# software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log
from mca.common.paths import paths
from mca.common.textio import alistio
from mca.mya.deformations import skin_utils
from mca.mya.rigging import skel_utils
from mca.mya.rigging import mesh_markup_rig
from mca.mya.tools.summoner import swap_utils

logger = log.MCA_LOGGER

# The shared response/undo/selection wrapper. Aliased so the decorators below
# read as @_safe rather than @swap_utils.safe.
_safe = swap_utils.safe

# MeshMarkup entries written on an equipped mesh.
GEAR_TYPE_NAME = 'gear_mesh'
GEAR_CATEGORY = 'gear'

# Group the equipped meshes are parented under, created per character.
GEAR_GROUP_SUFFIX = '_gear_grp'


# --- Scene lookups ------------------------------------------------------------------------------------------------

def _slot_for(record):
    """
    The slot a piece of gear occupies.

    Falls back to the category when no slot is recorded, so unslotted gear still
    replaces its own kind instead of stacking up.

    :param asset_manager.AssetRecord record: The gear record.
    :return: Slot key.
    :rtype: str
    """

    return (record.slot or record.category or 'General').strip()


# --- Joint provenance ---------------------------------------------------------------------------------------------

def _gear_meshes(character_id=None):
    """
    Find every equipped gear mesh in the scene.

    :param str character_id: Restrict to gear worn by this character.
    :return: ``[(mesh_transform, markup_dict)]``.
    :rtype: list[tuple]
    """

    found = []
    for mesh in pm.ls(type='transform'):
        if not mesh.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP):
            continue
        try:
            markup = mesh_markup_rig.MeshMarkup(mesh).get_dict() or {}
        except Exception:
            continue
        if markup.get('category') != GEAR_CATEGORY:
            continue
        if character_id and markup.get('character_id') != character_id:
            continue
        found.append((mesh, markup))
    return found


def _gear_group(character_id):
    """
    Return (creating if needed) the group equipped meshes are parented under.

    :param str character_id: The character's asset id.
    :return: The group transform.
    :rtype: pm.nt.Transform
    """

    name = '{}{}'.format(character_id, GEAR_GROUP_SUFFIX)
    if pm.objExists(name):
        return pm.PyNode(name)
    return pm.group(name=name, empty=True, world=True)


# --- What counts as gear ------------------------------------------------------------------------------------------

def has_maya_source(record, folder_cache=None):
    """
    Is there a Maya source file for this record on disk?

    Deliberately cheap - one directory listing per source folder - because it
    runs over whole categories. It answers "could this be equipped at all",
    not "which file would we import"; :func:`_resolve_gear_source` decides that
    properly at equip time.

    :param AssetRecord record: Record to check.
    :param dict folder_cache: Optional ``{folder: bool}`` memo shared across a
        sweep, so one folder is listed once however many records live in it.
    :return: True when the record's source rig folder holds a .ma file.
    :rtype: bool
    """

    folder = record.src_rig_path
    if not folder:
        return False
    key = os.path.normcase(folder)
    if folder_cache is None:
        folder_cache = {}
    if key not in folder_cache:
        try:
            folder_cache[key] = any(name.lower().endswith('.ma') for name in os.listdir(folder))
        except OSError:
            folder_cache[key] = False
    return folder_cache[key]


def gear_capable_categories():
    """
    The categories a piece of gear could live in, from the categories manifest.

    A character, prop, vehicle or camera is a thing in its own right, never
    something worn, and each of those has a rig file on disk - so without this
    filter the "no parent but has a Maya file" rule below would call every
    character gear.

    The split is taken from the manifest rather than hardcoded: a category is
    gear-capable unless it is listed as primary and not also listed as gear.
    Weapons, Heads and Faces are both, and stay in.

    :return: Category names.
    :rtype: set[str]
    """

    manifest = alistio.read_alist_file(paths.get_categories_manifest_path()) or {}
    names = lambda key: {e.get('name') for e in (manifest.get(key) or []) if e.get('name')}
    declared = names('categories')
    primary = names('primary_categories')
    gear = names('gear_categories')
    if not declared:
        logger.warning('Categories manifest is empty or unreadable; treating every category '
                       'as gear-capable.')
        return set()
    return (declared - primary) | gear


def is_gear_record(record, folder_cache=None, capable=None):
    """
    Is this record a piece of gear?

    Two things make a record gear, and the second one matters:

    1. It names a parent character in ``built_for``. That is the intended
       marker and covers most of the depot.
    2. Its category could hold gear at all, it names no parent, and it has a
       Maya source file on disk. Plenty of real gear was registered without a
       parent - every JellyBean shirt, for one - and hiding those is exactly
       what made the Summoner disagree with the registry. The non-gear assets
       a category also holds have neither a parent nor a rig source, so they
       still stay out.

    :param AssetRecord record: Record to judge.
    :param dict folder_cache: Optional memo passed straight to
        :func:`has_maya_source`.
    :param set capable: Optional result of :func:`gear_capable_categories`,
        passed in when judging many records so the manifest is read once.
    :return: True when the record is gear.
    :rtype: bool
    """

    if record.built_for_all:
        return True
    if capable is None:
        capable = gear_capable_categories()
    if capable and record.category not in capable:
        return False
    return has_maya_source(record, folder_cache)


def gear_categories():
    """
    The categories that hold gear, derived from the data rather than a flag.

    ``asset_data.config``'s ``is_gear`` flag disagrees with the data - Armor is
    flagged False while every Armor asset has a parent - so it is not consulted.

    :return: Category names, sorted.
    :rtype: list[str]
    """

    folder_cache = {}
    capable = gear_capable_categories()
    return sorted({record.category for record in swap_utils.manager().iter_all()
                   if record.category and is_gear_record(record, folder_cache, capable)})


# --- Public API ---------------------------------------------------------------------------------------------------

@_safe
def list_gear(character=None, category=None, limit=200):
    """
    List the gear that can be put on a character.

    This is the discovery call to make before :func:`equip`: it says which
    pieces exist, which slot each one fills, whether a Maya file backs it, and
    what is already worn.

    :param str character: Asset id or name. Optional when one character is in
        the scene; when neither is given, every piece of gear is listed.
    :param str category: Restrict to one category, e.g. 'Shirts'.
    :param int limit: Most rows to return.
    :return: Response with ``[{'asset_id', 'name', 'category', 'slot',
        'built_for', 'equippable', 'equipped'}]``.
    :rtype: dict
    """

    manager = swap_utils.manager()

    character_id, worn = '', {}
    try:
        _node, _root, character_id = swap_utils.resolve_character(character)
    except ValueError:
        if character:
            raise
    if character_id:
        worn = {markup.get('asset_id') for _mesh, markup in _gear_meshes(character_id)}

    character_record = manager.get_record(character_id) if character_id else None
    character_name = (character_record.name if character_record else character_id) or ''

    folder_cache = {}
    capable = gear_capable_categories()
    rows = []
    for record in manager.iter_all():
        if category and (record.category or '').lower() != category.lower():
            continue
        if not is_gear_record(record, folder_cache, capable):
            continue
        parents = list(record.built_for_all or [])
        # A piece built for somebody else is not offered; one built for nobody
        # is, because the registry simply does not say and the file is there.
        if character_name and parents and character_name.lower() not in [p.lower() for p in parents]:
            continue
        rows.append({'asset_id': record.asset_id,
                     'name': record.name,
                     'category': record.category,
                     'slot': _slot_for(record),
                     'built_for': parents,
                     'equippable': has_maya_source(record, folder_cache),
                     'equipped': record.asset_id in worn})
        if len(rows) >= limit:
            break

    rows.sort(key=lambda r: (r['category'], r['slot'], r['name'] or r['asset_id']))
    who = ' for {}'.format(character_name) if character_name else ''
    if not rows:
        return rows, 'No gear found{}{}.'.format(
            ' in {}'.format(category) if category else '', who)
    ready = sum(1 for r in rows if r['equippable'])
    return rows, '{} piece(s) of gear{}; {} have a Maya file and can be equipped.'.format(
        len(rows), who, ready)



@_safe
def list_characters():
    """
    List the characters in the scene that gear can be applied to.

    :return: Response with ``[{'asset_id', 'name', 'root_joint'}]``.
    :rtype: dict
    """

    manager = swap_utils.manager()
    result = []
    for node, root_joint, asset_id in swap_utils.character_roots():
        record = manager.get_record(asset_id) if asset_id else None
        result.append({'asset_id': asset_id,
                       'name': record.name if record else asset_id,
                       'root_joint': root_joint.nodeName()})
    if not result:
        return result, 'No character rig in the scene.'
    return result, '{} character(s) in the scene.'.format(len(result))


@_safe
def list_equipped(character=None):
    """
    List what a character is currently wearing, by slot.

    :param str character: Asset id or name. Optional when one character is in the scene.
    :return: Response with ``{slot: {'asset_id', 'name', 'meshes'}}``.
    :rtype: dict
    """

    _node, _root, character_id = swap_utils.resolve_character(character)
    manager = swap_utils.manager()

    by_slot = {}
    for mesh, markup in _gear_meshes(character_id):
        slot = markup.get('slot') or 'General'
        asset_id = markup.get('asset_id') or ''
        record = manager.get_record(asset_id) if asset_id else None
        entry = by_slot.setdefault(slot, {'asset_id': asset_id,
                                          'name': record.name if record else asset_id,
                                          'meshes': []})
        entry['meshes'].append(mesh.nodeName())

    if not by_slot:
        return by_slot, '{} is wearing nothing.'.format(character_id)
    worn = ', '.join('{}={}'.format(s, v['name']) for s, v in sorted(by_slot.items()))
    return by_slot, '{} is wearing {} piece(s): {}'.format(character_id, len(by_slot), worn)


@_safe
def unequip(asset_id=None, slot=None, character=None):
    """
    Take a piece of gear off a character.

    Removes the meshes, drops the asset's claim on the joints it needed, and
    deletes any joint no other gear still needs. Pass an asset id or a slot.

    :param str asset_id: The gear to remove.
    :param str slot: Remove whatever occupies this slot instead.
    :param str character: Asset id or name. Optional when one character is in the scene.
    :return: Response with what was removed.
    :rtype: dict
    """

    return _unequip(asset_id=asset_id, slot=slot, character=character)


def _unequip(asset_id=None, slot=None, character=None):
    """
    The body of :func:`unequip`, without the decorator.

    :func:`equip` removes whatever is in the slot before putting the new piece
    on, and calling the decorated function for that would nest a second undo
    chunk and a second selection context inside the first - so a swap would end
    up restoring a half-finished selection. Both callers share this instead.

    :param str asset_id: The gear to remove.
    :param str slot: Remove whatever occupies this slot instead.
    :param str character: Asset id or name.
    :return: ``(result, message)``.
    :rtype: tuple
    """

    if not asset_id and not slot:
        raise ValueError('Pass either asset_id or slot.')

    _node, root_joint, character_id = swap_utils.resolve_character(character)

    targets = []
    for mesh, markup in _gear_meshes(character_id):
        if asset_id and markup.get('asset_id') == asset_id:
            targets.append((mesh, markup))
        elif slot and (markup.get('slot') or 'General') == slot:
            targets.append((mesh, markup))

    if not targets:
        what = asset_id or 'slot {!r}'.format(slot)
        return ({'removed': [], 'joints_deleted': []},
                '{} is not wearing {}.'.format(character_id, what))

    removed_ids = sorted({m.get('asset_id') for _, m in targets if m.get('asset_id')})
    mesh_names = [mesh.nodeName() for mesh, _ in targets]
    pm.delete([mesh for mesh, _ in targets])

    released, deleted = [], []
    for gear_id in removed_ids:
        rel, dele = swap_utils.release_joints(root_joint, gear_id)
        released += rel
        deleted += dele

    result = {'removed': removed_ids, 'meshes': mesh_names,
              'joints_released': sorted(set(released)),
              'joints_deleted': sorted(set(deleted))}
    message = 'Removed {} from {}.'.format(', '.join(removed_ids) or 'gear', character_id)
    if deleted:
        message += ' Deleted {} joint(s) nothing else needed.'.format(len(deleted))
    kept = len(set(released)) - len(set(deleted))
    if kept > 0:
        message += ' Kept {} joint(s) still used by other gear.'.format(kept)
    return result, message


def _resolve_gear_source(record):
    """
    Find the file to import for a piece of gear.

    Prefers the skinned source (``_skn.ma``), which carries the mesh and its
    skin cluster together; falls back to the rig file, then the source mesh.

    :param asset_manager.AssetRecord record: The gear record.
    :return: ``(absolute_path, kind)``.
    :rtype: tuple
    :raises ValueError: When nothing can be found on disk.
    """

    entry = record.source_entry
    if entry is None:
        raise ValueError('{!r} has no backing entry to read files from.'.format(record.asset_id))

    for kind in ('skin', 'rig', 'mesh'):
        path = entry.resolve_file(kind)
        if path and os.path.isfile(path):
            return path, kind

    raise ValueError(
        'No source file on disk for {!r}. Looked for a skin, rig then mesh file under {}. '
        'Record one with assetlist_api.set_asset_file, or check the asset path.'
        .format(record.asset_id, record.relative_path or '(no path)'))


@_safe
def equip(asset_id, character=None, replace=True):
    """
    Put a piece of gear on a character.

    Merges the gear's extra joints into the character skeleton, imports the
    gear, and rebinds its skin cluster onto the character's joints. When the
    slot is already filled the previous piece is removed first - that is the
    double-click-to-swap behaviour.

    :param str asset_id: The gear asset id or display name.
    :param str character: Asset id or name. Optional when one character is in the scene.
    :param bool replace: Remove whatever occupies the slot first. False refuses
        instead, which is useful for a caller that wants to ask.
    :return: Response describing what was equipped.
    :rtype: dict
    """

    record = swap_utils.require_record(asset_id)
    node, root_joint, character_id = swap_utils.resolve_character(character)
    slot = _slot_for(record)

    # Check the parent is right, but do not refuse: a piece can legitimately be
    # re-used on a character it was not authored for, and saying so is enough.
    parents = [p.lower() for p in (record.built_for_all or ())]
    character_record = swap_utils.manager().get_record(character_id)
    character_name = (character_record.name if character_record else character_id) or ''
    parent_note = ''
    if parents and character_name.lower() not in parents:
        parent_note = (' Note: {} is built for {}, not {}.'
                       .format(record.name, '/'.join(record.built_for_all), character_name))

    source_path, source_kind = _resolve_gear_source(record)

    # What is already in this slot?
    occupied = [(m, mk) for m, mk in _gear_meshes(character_id)
                if (mk.get('slot') or 'General') == slot]
    swapped_out = sorted({mk.get('asset_id') for _, mk in occupied if mk.get('asset_id')})
    if occupied:
        if not replace:
            raise ValueError('{} already has {} in the {} slot. Pass replace=True to swap it.'
                             .format(character_id, ', '.join(swapped_out) or 'gear', slot))
        for gear_id in swapped_out:
            _unequip(asset_id=gear_id, character=character_id)

    # Joints cannot be added safely to a posed skeleton, so go back to bind
    # first. Always, rather than only when the gear needs new joints: it is one
    # cheap call and it removes a whole class of "it worked last time" bugs.
    entry = record.source_entry
    character_entry = character_record.source_entry if character_record else None
    character_skel = character_entry.resolve_file('skel') if character_entry else ''
    if character_skel and os.path.isfile(character_skel):
        skel_utils.restore_skeleton_bindpose(character_skel, root_joint)

    before = skel_utils.create_skeleton_dict(root_joint)
    before_names = set(before)
    # Joints another piece of gear brought in. These are the only pre-existing
    # joints this piece may claim a share of; everything else in the skeleton
    # belongs to the character and must never be tagged, or an unequip could
    # delete part of the character.
    gear_owned = {name for name, joint_node in before.items() if swap_utils.joint_sources(joint_node)}

    gear_skel = entry.resolve_file('skel') if entry else ''
    gear_joint_names = set()
    if gear_skel and os.path.isfile(gear_skel):
        skel_utils.import_merge_skeleton(gear_skel, root_joint)
        gear_joint_names = set(skel_utils.SkeletonData(
            gear_skel.replace('.skl', '')).read_data() or {})

    after_names = set(skel_utils.create_skeleton_dict(root_joint))
    added_names = sorted(after_names - before_names)

    # Import and rebind.
    imported = swap_utils.import_source_file(source_path)
    meshes = swap_utils.skinned_meshes_under(imported)
    if not meshes:
        pm.delete([n for n in imported if pm.objExists(n)])
        raise ValueError('{} imported no skinned mesh from {}. It may be a static mesh; '
                         'socket attachment is not wired up yet.'
                         .format(record.name, os.path.basename(source_path)))

    skin_utils.rebind_mesh_to_skel(meshes, root_joint)

    # What this piece created, plus any gear joint another piece brought in that
    # this one also names - that second part is what makes the reference count
    # work when two pieces share a joint. Character joints are excluded, so an
    # unequip can never take the skeleton with it.
    needed = set(added_names) | (gear_joint_names & gear_owned)
    swap_utils.tag_joints(root_joint, needed, record.asset_id)

    # Park the meshes and tag them.
    group = _gear_group(character_id)
    for mesh in meshes:
        if pm.objExists(mesh):
            try:
                mesh.setParent(group)
            except Exception:
                logger.debug('Could not parent %s under %s', mesh, group)
            mesh_markup_rig.MeshMarkup.create(
                mesh, type_name=GEAR_TYPE_NAME, category=GEAR_CATEGORY, side='center',
                asset_id=record.asset_id, slot=slot, character_id=character_id,
                gear_category=record.category)

    # Remove any leftovers the import brought that were not meshes we kept.
    leftovers = [n for n in imported
                 if pm.objExists(n) and n not in meshes and not n.listRelatives(ad=True, type='mesh')]
    if leftovers:
        pm.delete(leftovers)

    result = {'asset_id': record.asset_id, 'name': record.name, 'slot': slot,
              'character': character_id, 'source_file': source_path, 'source_kind': source_kind,
              'meshes': [m.nodeName() for m in meshes if pm.objExists(m)],
              'joints_added': added_names, 'joints_needed': sorted(needed),
              'swapped_out': swapped_out}
    message = 'Equipped {} on {} ({} slot).'.format(record.name, character_id, slot)
    if swapped_out:
        message += ' Replaced {}.'.format(', '.join(swapped_out))
    if added_names:
        message += ' Added {} joint(s).'.format(len(added_names))
    message += parent_note
    return result, message


@_safe
def clear_slot(slot, character=None):
    """
    Remove whatever a character is wearing in one slot.

    :param str slot: Slot name.
    :param str character: Asset id or name.
    :return: Response describing what was removed.
    :rtype: dict
    """

    return _unequip(slot=slot, character=character)
