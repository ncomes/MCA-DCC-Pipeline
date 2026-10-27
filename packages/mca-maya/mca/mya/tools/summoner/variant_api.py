"""
Headless variant API: swap a character's whole body for another look, keeping its gear on.

A variant is the character-sized version of gear. Gear goes *on* a character; a
variant *is* the character - a different body riding the same skeleton. In the
registry a variant is an ordinary Characters record that names its base in
``variant_of`` (see :func:`mca.common.assetlist.assetlist_api.list_variants`).

Every function returns ``{'ok': bool, 'result': <json>, 'message': str}``, the
same contract as ``assetlist_api``, ``gear_api`` and ``toolbox_api``.

Why gear survives a swap
------------------------
The skeleton belongs to the character, not to the body mesh. A variant is
rebound onto the skeleton already in the scene, exactly as gear is, so the
joints gear is bound to never move and equipped gear keeps working across a
swap. Joints a variant brings in of its own are reference counted in the same
``mcaJointSource`` ledger gear uses, so a variant cannot delete a joint a hat
still needs, and vice versa.

Reverting
---------
Applying a variant deletes the body it replaced, so reverting re-imports the
base character's source file. That restores the body mesh and its skinning; it
does **not** restore anything else the original body carried, such as blend
shape targets or rig connections that were authored into the rig file rather
than the skin file. Reload the rig if you need those back.

:Requires: mca.mya.tools.summoner.swap_utils, mca.common.assetlist
:Side effects: Imports files into the scene, deletes body meshes, creates and
    deletes joints, and rebinds skin clusters.
"""

# python imports
import os

# software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log
from mca.mya.deformations import skin_utils
from mca.mya.rigging import skel_utils
from mca.mya.rigging import mesh_markup_rig
from mca.mya.tools.summoner import swap_utils

logger = log.MCA_LOGGER

_safe = swap_utils.safe

# MeshMarkup written on a body that a variant put in place. The character's own
# body carries no markup at all, which is how "has anything been swapped in
# here yet" is answered.
VARIANT_TYPE_NAME = 'variant_mesh'
VARIANT_CATEGORY = 'variant'

# Source kinds tried, in order, when looking for a body to import.
BODY_FILE_KINDS = ('skin', 'rig', 'mesh')


# --- Scene lookups ------------------------------------------------------------------------------------------------

def _variant_meshes(character_id=None):
    """
    Find every body mesh a variant put into the scene.

    :param str character_id: Restrict to one character.
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
        if markup.get('category') != VARIANT_CATEGORY:
            continue
        if character_id and markup.get('character_id') != character_id:
            continue
        found.append((mesh, markup))
    return found


def _body_meshes(frag_node, root_joint, character_id):
    """
    Find the meshes that currently make up this character's body.

    Three things are deliberately excluded: gear, which is worn on top and must
    survive the swap; unskinned meshes, which are blend shape targets rather
    than body; and anything outside the character's own hierarchy.

    Prefers the rig's own SkeletalMesh node when the rig has one, because that
    is the rig saying what its body is. Falls back to walking the character's
    assembly, which is what an older rig without the node needs.

    :param frag_node: The character's FRAG root.
    :param pm.nt.Joint root_joint: The character's root joint.
    :param str character_id: The character's asset id.
    :return: Body mesh transforms.
    :rtype: list
    """

    swapped = [mesh for mesh, _markup in _variant_meshes(character_id)]
    if swapped:
        # A variant is already on; that is the body now.
        return swapped

    candidates = []
    try:
        skeletal_mesh = frag_node.get_skeletal_mesh()
    except Exception:
        skeletal_mesh = None
    if skeletal_mesh is not None:
        try:
            candidates = list(skeletal_mesh.get_meshes())
        except Exception:
            logger.debug('SkeletalMesh node gave no meshes; walking the hierarchy instead.',
                         exc_info=True)
            candidates = []

    if not candidates:
        top = root_joint
        while top.getParent() is not None:
            top = top.getParent()
        candidates = list(top.listRelatives(ad=True, type='transform'))

    meshes = []
    for candidate in candidates:
        if not candidate.getShapes(type='mesh'):
            continue
        # Unskinned: a blend shape target, not body.
        if not skin_utils.find_related_skin_cluster(candidate):
            continue
        if candidate.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP):
            try:
                markup = mesh_markup_rig.MeshMarkup(candidate).get_dict() or {}
            except Exception:
                markup = {}
            # Gear stays on through a swap.
            if markup.get('category') and markup.get('category') != VARIANT_CATEGORY:
                continue
        if candidate not in meshes:
            meshes.append(candidate)
    return meshes


def _resolve_body_source(record):
    """
    Find the file to import for a character body.

    :param record: The character's registry record.
    :return: ``(absolute_path, kind)``.
    :rtype: tuple
    :raises ValueError: When nothing can be found on disk.
    """

    entry = record.source_entry
    if entry is not None:
        for kind in BODY_FILE_KINDS:
            path = entry.resolve_file(kind)
            if path and os.path.isfile(path):
                return path, kind
    raise ValueError(
        '{} has no Maya source file on disk, so there is no body to import. Looked for {} '
        "under {}. Record the file with assetlist_api.set_asset_file, or check the record's "
        'path - a character whose path starts "Game/" is pointing at an engine path '
        'and will never resolve.'
        .format(record.name, '/'.join(BODY_FILE_KINDS), record.relative_path or '(no path)'))


def _family_for(character_id):
    """
    The base and every variant for the character in the scene.

    :param str character_id: The character's asset id.
    :return: ``(base_record, [variant_records])``.
    :rtype: tuple
    :raises ValueError: When the character is not in the registry.
    """

    asset_list = swap_utils.manager()
    record = asset_list.get_record(character_id)
    if record is None:
        raise ValueError(
            '{!r} is in the scene but not in the registry, so its variants cannot be looked up.'
            .format(character_id))
    family = asset_list.get_variant_family(record.asset_id)
    if not family:
        return record, []
    return family[0], list(family[1:])


def _swap_body(record, root_joint, character_id, outgoing, group_parent):
    """
    Bring a body in, rebind it, and take the old one out.

    Shared by :func:`apply_variant` and :func:`revert_variant` - reverting is
    just applying the base's body - so the joint bookkeeping cannot drift
    between the two directions.

    :param record: Registry record for the body being brought in.
    :param pm.nt.Joint root_joint: The character's root joint.
    :param str character_id: The character's asset id.
    :param list outgoing: Body meshes to delete once the new body is in.
    :param group_parent: Transform to parent the new meshes under, or None to
        leave them where the import put them.
    :return: ``(result_dict, added_joint_names, removed_ids)``.
    :rtype: tuple
    """

    source_path, source_kind = _resolve_body_source(record)
    entry = record.source_entry

    # Joints cannot be added safely to a posed skeleton.
    character_skel = entry.resolve_file('skel') if entry else ''
    if character_skel and os.path.isfile(character_skel):
        skel_utils.restore_skeleton_bindpose(character_skel, root_joint)

    before = skel_utils.create_skeleton_dict(root_joint)
    before_names = set(before)
    owned = {name for name, joint in before.items() if swap_utils.joint_sources(joint)}

    variant_skel = entry.resolve_file('skel') if entry else ''
    declared = set()
    if variant_skel and os.path.isfile(variant_skel):
        skel_utils.import_merge_skeleton(variant_skel, root_joint)
        declared = set(skel_utils.SkeletonData(variant_skel.replace('.skl', '')).read_data() or {})

    after_names = set(skel_utils.create_skeleton_dict(root_joint))
    added = sorted(after_names - before_names)

    imported = swap_utils.import_source_file(source_path)
    meshes = swap_utils.skinned_meshes_under(imported)
    if not meshes:
        pm.delete([n for n in imported if pm.objExists(n)])
        raise ValueError('{} imported no skinned mesh from {}. A body has to be skinned; '
                         'a static mesh cannot stand in for one.'
                         .format(record.name, os.path.basename(source_path)))

    skin_utils.rebind_mesh_to_skel(meshes, root_joint)

    # Same rule as gear: claim what we created, plus any joint another asset
    # already owns that this body also names. Character joints are never tagged.
    needed = set(added) | (declared & owned)
    swap_utils.tag_joints(root_joint, needed, record.asset_id)

    # The old body goes only once the new one is bound, so a failure above
    # leaves the character with a body rather than none.
    removed_ids = []
    for mesh in outgoing:
        if not pm.objExists(mesh):
            continue
        if mesh.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP):
            try:
                markup = mesh_markup_rig.MeshMarkup(mesh).get_dict() or {}
                if markup.get('asset_id'):
                    removed_ids.append(markup['asset_id'])
            except Exception:
                pass
        pm.delete(mesh)

    released = []
    for removed_id in sorted(set(removed_ids)):
        if removed_id == record.asset_id:
            continue
        rel, _deleted = swap_utils.release_joints(root_joint, removed_id)
        released += rel

    for mesh in meshes:
        if not pm.objExists(mesh):
            continue
        if group_parent is not None:
            try:
                mesh.setParent(group_parent)
            except Exception:
                logger.debug('Could not parent %s under %s', mesh, group_parent)
        mesh_markup_rig.MeshMarkup.create(
            mesh, type_name=VARIANT_TYPE_NAME, category=VARIANT_CATEGORY, side='center',
            asset_id=record.asset_id, slot='Body', character_id=character_id,
            gear_category=record.category)

    leftovers = [n for n in imported
                 if pm.objExists(n) and n not in meshes
                 and not n.listRelatives(ad=True, type='mesh')]
    if leftovers:
        pm.delete(leftovers)

    result = {'asset_id': record.asset_id, 'name': record.name, 'character': character_id,
              'source_file': source_path, 'source_kind': source_kind,
              'meshes': [m.nodeName() for m in meshes if pm.objExists(m)],
              'joints_added': added, 'joints_needed': sorted(needed),
              'replaced': sorted(set(removed_ids))}
    return result, added, sorted(set(removed_ids))


# --- Public API ---------------------------------------------------------------------------------------------------

@_safe
def list_variants(character=None):
    """
    List the looks the character in the scene can be swapped to.

    :param str character: Asset id or name. Optional when one character is in the scene.
    :return: Response with ``{'character', 'base', 'current', 'variants'}``, where
        each variant says whether it is applied and whether a file backs it.
    :rtype: dict
    """

    _node, _root, character_id = swap_utils.resolve_character(character)
    base, variants = _family_for(character_id)
    applied = {markup.get('asset_id') for _mesh, markup in _variant_meshes(character_id)}
    current = sorted(applied)[0] if applied else base.asset_id

    def row(record):
        entry = record.source_entry
        has_file = bool(entry and any(entry.resolve_file(k) for k in BODY_FILE_KINDS))
        return {'asset_id': record.asset_id, 'name': record.name,
                'subtype': record.subtype, 'applicable': has_file,
                'applied': record.asset_id == current}

    result = {'character': character_id, 'base': row(base), 'current': current,
              'variants': [row(r) for r in variants]}
    if not variants:
        return result, ('{} has no variants registered. Set one with '
                        "assetlist_api.set_variant_base(<variant>, '{}')."
                        .format(base.name, base.asset_id))
    ready = sum(1 for r in result['variants'] if r['applicable'])
    return result, ('{} has {} variant(s), {} with a Maya file. Currently showing {}.'
                    .format(base.name, len(variants), ready, current))


@_safe
def current_variant(character=None):
    """
    Say which body the character in the scene is currently wearing.

    :param str character: Asset id or name.
    :return: Response with ``{'character', 'current', 'is_base', 'meshes'}``.
    :rtype: dict
    """

    _node, _root, character_id = swap_utils.resolve_character(character)
    base, _variants = _family_for(character_id)
    applied = _variant_meshes(character_id)
    if not applied:
        return ({'character': character_id, 'current': base.asset_id, 'is_base': True,
                 'meshes': []},
                '{} is showing its base body.'.format(base.name))

    asset_id = sorted({m.get('asset_id') for _mesh, m in applied})[0]
    record = swap_utils.manager().get_record(asset_id)
    return ({'character': character_id, 'current': asset_id, 'is_base': False,
             'meshes': [mesh.nodeName() for mesh, _m in applied]},
            '{} is showing the {} variant.'.format(base.name, record.name if record else asset_id))


@_safe
def apply_variant(asset_id, character=None):
    """
    Swap the character's body for one of its variants.

    The skeleton is untouched, so anything equipped stays equipped. Applying a
    second variant replaces the first; applying the base is the same as
    :func:`revert_variant`.

    :param str asset_id: The variant's asset id or display name.
    :param str character: Asset id or name. Optional when one character is in the scene.
    :return: Response describing the swap.
    :rtype: dict
    """

    record = swap_utils.require_record(asset_id)
    node, root_joint, character_id = swap_utils.resolve_character(character)
    base, variants = _family_for(character_id)

    family_ids = {base.asset_id} | {r.asset_id for r in variants}
    if record.asset_id not in family_ids:
        raise ValueError(
            '{} is not a variant of {}. Its variants are: {}. Register it with '
            "assetlist_api.set_variant_base('{}', '{}') if it should be one."
            .format(record.name, base.name,
                    ', '.join(sorted(r.asset_id for r in variants)) or 'none',
                    record.asset_id, base.asset_id))

    already = {m.get('asset_id') for _mesh, m in _variant_meshes(character_id)}
    if record.asset_id in already:
        return ({'asset_id': record.asset_id, 'name': record.name, 'character': character_id,
                 'meshes': [], 'joints_added': [], 'replaced': []},
                '{} is already showing {}.'.format(base.name, record.name))

    outgoing = _body_meshes(node, root_joint, character_id)
    parent_group = outgoing[0].getParent() if outgoing else None

    result, added, replaced = _swap_body(record, root_joint, character_id, outgoing, parent_group)

    message = '{} is now showing {}.'.format(base.name, record.name)
    if replaced:
        message += ' Replaced {}.'.format(', '.join(replaced))
    if added:
        message += ' Added {} joint(s).'.format(len(added))
    equipped = len({m.get('asset_id') for _mesh, m in _gear_still_on(character_id)})
    if equipped:
        message += ' {} piece(s) of gear stayed on.'.format(equipped)
    return result, message


@_safe
def revert_variant(character=None):
    """
    Put the character's base body back.

    Applying a variant deletes the body it replaced, so this re-imports the base
    character's source file. Blend shape targets and rig connections authored
    into the rig file do not come back with it - reload the rig for those.

    :param str character: Asset id or name.
    :return: Response describing the swap.
    :rtype: dict
    """

    node, root_joint, character_id = swap_utils.resolve_character(character)
    base, _variants = _family_for(character_id)

    outgoing = [mesh for mesh, _m in _variant_meshes(character_id)]
    if not outgoing:
        return ({'asset_id': base.asset_id, 'name': base.name, 'character': character_id,
                 'meshes': [], 'joints_added': [], 'replaced': []},
                '{} is already showing its base body.'.format(base.name))

    parent_group = outgoing[0].getParent()
    result, added, replaced = _swap_body(base, root_joint, character_id, outgoing, parent_group)

    # The base body is the character's own, not a variant sitting on top.
    for mesh in result['meshes']:
        if pm.objExists(mesh):
            node_ref = pm.PyNode(mesh)
            if node_ref.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP):
                node_ref.attr(mesh_markup_rig.MCA_MESH_MARKUP).unlock()
                node_ref.deleteAttr(mesh_markup_rig.MCA_MESH_MARKUP)

    message = '{} is back to its base body.'.format(base.name)
    if replaced:
        message += ' Removed {}.'.format(', '.join(replaced))
    return result, message


def _gear_still_on(character_id):
    """
    Gear equipped on this character, read without importing gear_api at module
    scope - the two APIs are siblings and neither should need the other to load.

    :param str character_id: The character's asset id.
    :return: ``[(mesh, markup)]``.
    :rtype: list[tuple]
    """

    from mca.mya.tools.summoner import gear_api
    return gear_api._gear_meshes(character_id)
