"""
Maya-side operations for the animation library.

The catalog half is DCC-agnostic and lives in :mod:`mca.common.animlib`; this is
everything that needs a Maya scene: taking a clip off a rig, putting one back on,
baking the portable FBX, and grabbing a preview.

What a capture writes
---------------------
Up to three files per clip, and the asymmetry between them is the point:

``.ma``  the master. Only the stored curve network - an ``AnimatedCurvesComponent``
         exported on its own - so it keeps animation layers, flag values and IK/FK
         state. A few hundred KB, against the ~28 MB a full rig scene costs.
``.fbx`` derived. A baked joints-only skeleton for Blender, MotionBuilder and the
         engine. Flattened: layers and flag context are gone. Always rebuildable
         from the ``.ma``, so when the two disagree the ``.ma`` wins.
``.jpg`` a playblast frame for the browser.

Applying does not consume a clip
--------------------------------
:func:`apply_clip` imports the clip's curve node, restores off it, and deletes the
import - the library file on disk is never touched, so the same clip applies to as
many rigs as you like.

:Requires: mca.common.animlib, mca.mya.rigging.frag, mca.mya.animation
:Side effects: Imports and exports files, and changes animation on the rig in the
    open scene.
"""

# python imports
import contextlib
import functools
import math
import os
import shutil
import tempfile
import traceback

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log
from mca.common.animlib import animlib_api, catalog as catalog_module, clip as clip_module
from mca.common.assetlist import get_asset_manager
from mca.mya.animation import time_utils
from mca.mya.rigging import frag, rig_utils
from mca.mya.rigging.flags import flag_mirror
from mca.mya.utils import attr_utils, dag, fbx_utils

logger = log.MCA_LOGGER

# How the browser's "Option" dropdown maps onto Maya's own pasteKey modes. The
# four are genuinely different questions about what happens to animation the rig
# already has:
#
#   replace      Wipe the frames the clip covers and put the clip there. Keys
#                either side of it are kept.
#   replace all  Throw away everything on those flags and put the clip on.
#   insert       Push the existing keys later by the clip's length and slot the
#                clip into the gap. Nothing is lost, everything after moves.
#   merge        Lay the clip over what is there. Only frames the clip actually
#                keys are overwritten.
#
# 'replace' is the only one Maya wants a time *range* for; 'replace all'
# actively refuses one.
PASTE_OPTIONS = {
    'replace': 'replace',
    'replace_all': 'replaceCompletely',
    'insert': 'insert',
    'merge': 'merge',
}

# The order the browser lists them in, which is the order Studio Library uses -
# animators read this dropdown by position as much as by name.
PASTE_OPTION_ORDER = ('replace', 'replace_all', 'insert', 'merge')

# Passed as `namespace` to mean the root namespace - a rig that was opened rather
# than referenced - as distinct from None, which means "work it out from the
# selection".
ROOT_NAMESPACE = ':'


def _response(ok, result=None, message=''):
    """
    :param bool ok: Success flag.
    :param object result: JSON-serialisable result.
    :param str message: Human readable summary.
    :return: The standard response dict.
    :rtype: dict
    """

    return {'ok': ok, 'result': result, 'message': message}


def _safe(func):
    """
    Decorator: turn exceptions into failed responses.

    Deliberately no undo chunk. Maya's file import wipes the undo queue outright
    (see ``swap_utils.import_source_file``), and every function here either
    imports or exports, so a chunk would only promise something it cannot keep.

    :param callable func: API function returning ``(result, message)``.
    :return: Wrapped function returning a response dict.
    :rtype: callable
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result, message = func(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            return _response(False, None, str(exc).strip("'\""))
        except Exception as exc:
            logger.error('animlib_maya.%s failed: %s\n%s',
                         func.__name__, exc, traceback.format_exc())
            return _response(False, None, '{}: {}'.format(type(exc).__name__, exc))
        return _response(True, result, message)

    return wrapper


# --- Scene lookups ------------------------------------------------------------------------------------------------

def scene_fps():
    """
    The open scene's frame rate.

    :return: Frames per second, defaulting when the unit is unrecognised.
    :rtype: float
    """

    from mca.mya.tools.animlibrary import consts
    unit = str(pm.currentUnit(q=True, time=True) or '')
    return consts.MAYA_TIME_TO_FPS.get(unit, consts.DEFAULT_FPS)


def rig_namespace(frag_rig):
    """
    The namespace a rig was brought in under.

    :param frag_rig: The rig.
    :return: The leading namespace with no colons, or '' for a rig in the root
        namespace.
    :rtype: str
    """

    try:
        return str(frag_rig.pynode.namespace()).strip(':').split(':')[0]
    except Exception:
        logger.debug('Could not read a namespace off %s', frag_rig, exc_info=True)
        return ''


def scene_rigs():
    """
    Every FRAG rig in the open scene, described for a picker.

    :return: ``[{'namespace', 'asset_id', 'node', 'flags'}]``, sorted by namespace.
    :rtype: list[dict]
    """

    rows = []
    for rig in frag.get_frag_rigs():
        if rig is None:
            continue
        try:
            flag_count = len(rig.get_flags())
        except Exception:
            flag_count = 0
        rows.append({'namespace': rig_namespace(rig),
                     'asset_id': rig_asset_id(rig),
                     'node': str(rig.pynode),
                     'flags': flag_count})
    return sorted(rows, key=lambda r: r['namespace'].lower())


def resolve_rig(frag_rig=None, namespace=None):
    """
    Work out which rig the caller means.

    Accepts a FRAGRig, the name of any node belonging to one, or None to take it
    from the selection and then the scene. The string form is what lets the MCP
    and AI tools name a rig at all - they cannot hold a PyNode.

    ``namespace`` beats everything else when it is given. With two of the same
    character referenced into one scene, the namespace is the only thing that
    tells them apart, and an animator who typed one meant it - falling back to
    the selection there would quietly animate the wrong rig.

    :param frag_rig: A FRAGRig, a node name, or None.
    :param str namespace: Pick the rig living under this namespace.
    :return: The rig.
    :rtype: frag.FRAGRig
    :raises ValueError: When there is no rig, or the choice is ambiguous.
    """

    if namespace:
        # ':' on its own means the root namespace - the rig that was opened
        # rather than referenced. It has to be sayable, or "no namespace" and
        # "namespace not specified" would be the same request.
        wanted = str(namespace).strip(':').lower()
        rigs = [r for r in frag.get_frag_rigs() if r is not None]
        matched = [r for r in rigs if rig_namespace(r).lower() == wanted]
        if not matched:
            present = sorted(set(rig_namespace(r) or '(no namespace)' for r in rigs))
            raise ValueError('{}. In the scene: {}.'.format(
                'No rig in the root namespace' if not wanted
                else 'No rig under the namespace {!r}'.format(namespace),
                ', '.join(present) or 'no rigs at all'))
        if len(matched) > 1:
            raise ValueError('{} rigs share the namespace {!r}, so it does not identify one.'
                             .format(len(matched), namespace))
        return matched[0]

    if frag_rig is not None and not isinstance(frag_rig, str):
        return frag_rig

    if frag_rig:
        # A name: it may be the rig's own node, or anything under it.
        if not pm.objExists(frag_rig):
            present = ', '.join(sorted(rig_asset_id(r) or str(r) for r in frag.get_frag_rigs()))
            raise ValueError('No node called {!r} in the scene. Rigs present: {}.'
                             .format(frag_rig, present or 'none'))
        found = frag.get_frag_rig(pm.PyNode(frag_rig))
        if not found:
            raise ValueError('{!r} is not part of a FRAG rig.'.format(frag_rig))
        return found

    for node in pm.selected():
        found = frag.get_frag_rig(node)
        if found:
            return found

    rigs = frag.get_frag_rigs()
    if not rigs:
        raise ValueError('No rig found in the scene. Import one with the Summoner first - a clip '
                         'is captured from a rig and applied onto one.')
    if len(rigs) > 1:
        raise ValueError('{} rigs are in the scene; select the one you mean.'.format(len(rigs)))
    return rigs[0]


def rig_asset_id(frag_rig):
    """
    The asset id a rig belongs to.

    :param frag_rig: The rig.
    :return: Its asset id, or '' when the rig does not carry one.
    :rtype: str
    """

    for getter in ('get_asset_id', 'assetID'):
        try:
            value = getattr(frag_rig, getter)
            value = value(frag_rig) if callable(value) else value
            if value:
                return str(value)
        except Exception:
            continue
    return ''


def keyed_flags(flags):
    """
    Narrow a list of flags to the ones that actually carry keys.

    Storing every flag would put empty compound attributes on the clip for the
    hundreds that were never touched.

    :param list flags: Flags to filter.
    :return: Flags with at least one keyframe.
    :rtype: list
    """

    keyed = []
    for flag in flags:
        try:
            if pm.keyframe(flag, q=True, keyframeCount=True):
                keyed.append(flag)
        except Exception:
            logger.debug('Could not read keys off %s', flag, exc_info=True)
    return keyed


def animated_flags(frag_rig):
    """
    The rig's flags that actually carry keys.

    :param frag_rig: The rig.
    :return: Flags with at least one keyframe.
    :rtype: list
    """

    return keyed_flags(frag_rig.get_flags())


def scene_has_layers():
    """
    :return: True when the scene has animation layers beyond the base layer.
    :rtype: bool
    """

    return len([x for x in pm.ls(type=pm.nt.AnimLayer)]) > 1


def detect_root_motion(frag_rig, tolerance=0.01):
    """
    Guess whether the clip travels or stays put.

    Compares the root flag's translation at the first and last key. Callers can
    always override the answer on the clip record - this is a starting guess so
    the field is not 'unknown' on every single clip.

    :param frag_rig: The rig.
    :param float tolerance: Distance under which the root counts as stationary.
    :return: One of clip.ROOT_MOTION_VALUES.
    :rtype: str
    """

    root_flag = None
    for flag in frag_rig.get_flags():
        name = flag.nodeName().split(':')[-1].lower()
        if name in ('root', 'root_flag', 'f_root', 'offset', 'world'):
            root_flag = flag
            break
    if root_flag is None:
        return 'unknown'

    times = pm.keyframe(root_flag, q=True) or []
    if len(times) < 2:
        return 'in_place'
    try:
        start, end = min(times), max(times)
        first = [pm.getAttr('{}.{}'.format(root_flag, a), time=start) for a in ('tx', 'ty', 'tz')]
        last = [pm.getAttr('{}.{}'.format(root_flag, a), time=end) for a in ('tx', 'ty', 'tz')]
    except Exception:
        logger.debug('Could not sample root motion off %s', root_flag, exc_info=True)
        return 'unknown'

    travelled = sum((b - a) ** 2 for a, b in zip(first, last)) ** 0.5
    return 'travelling' if travelled > tolerance else 'in_place'


def sequence_settings_for(frag_rig, clip_name):
    """
    Export settings the Animation Exporter already holds for this animation.

    The FRAG Sequencer is the authority on how a given rig's animation should
    leave the building - its frame range, whether it starts at zero, whether the
    root goes to origin. When a rig already has a sequence whose name matches the
    clip being captured, the library honours those settings instead of guessing,
    so a clip's FBX matches what the exporter would have produced for the same
    animation.

    Returns None when the exporter has nothing to say, which is the common case
    and not a problem - the caller falls back to its own defaults.

    :param frag_rig: The rig being captured.
    :param str clip_name: The clip's display name.
    :return: ``{'frame_range', 'start_at_zero', 'root_to_origin', 'sequence_path'}``
        or None.
    :rtype: dict or None
    """

    try:
        from mca.mya.tools.animationexporter import animationexporter_utils as ae_utils
        sequences = ae_utils.get_sequences().get(frag_rig.pynode) or {}
    except Exception:
        logger.debug('Could not read the FRAG Sequencer.', exc_info=True)
        return None

    wanted = str(clip_name or '').strip().lower()
    for sequence_path, wrapper in sequences.items():
        stem = os.path.splitext(os.path.basename(str(sequence_path)))[0].lower()
        if stem != wanted:
            continue
        try:
            return {'frame_range': list(wrapper.frame_range),
                    'start_at_zero': bool(wrapper.start_at_zero),
                    'root_to_origin': bool(wrapper.root_to_origin),
                    'sequence_path': str(sequence_path)}
        except Exception:
            logger.debug('Sequence %s could not be read.', sequence_path, exc_info=True)
            return None
    return None


def _clip_paths(character, category, name, library_root):
    """
    Where a clip's three files belong.

    :param str character: Owning character's asset id.
    :param str category: Grouping.
    :param str name: Clip display name.
    :param str library_root: The library root.
    :return: ``(folder, {kind: (relative, absolute)})``.
    :rtype: tuple
    """

    relative_dir = catalog_module.clip_relative_dir(character, category)
    folder = os.path.normpath(os.path.join(library_root, relative_dir))
    out = {}
    for kind, extension in (('curves', '.ma'), ('fbx', '.fbx'), ('preview', '.jpg'),
                            ('gif', '.gif')):
        relative = '{}/{}{}'.format(relative_dir, name, extension)
        out[kind] = (relative, os.path.normpath(os.path.join(library_root, relative)))
    return folder, out


def target_flags(frag_rig, selected_only=False):
    """
    The flags an operation should work on.

    :param frag_rig: The rig.
    :param bool selected_only: Narrow to the rig's flags that are selected.
    :return: Flags.
    :rtype: list
    :raises ValueError: When selected_only is asked for and nothing is selected.
    """

    flags = frag_rig.get_flags()
    if not selected_only:
        return flags

    wanted = set()
    for node in pm.selected():
        wanted.add(str(node))
        # A flag picked in the viewport can come back as its shape.
        try:
            parent = node.getParent()
        except Exception:
            parent = None
        if parent is not None:
            wanted.add(str(parent))

    chosen = [f for f in flags if str(f) in wanted]
    if not chosen:
        raise ValueError('None of this rig\'s flags are selected, so there is nothing to work on. '
                         'Select the flags you mean, or turn off "Selected flags only".')
    return chosen


def normalise_paste_option(option):
    """
    Accept the dropdown's wording and return the key :data:`PASTE_OPTIONS` uses.

    :param str option: 'replace', 'replace all', 'replace_all', 'insert' or 'merge'.
    :return: The canonical key.
    :rtype: str
    :raises ValueError: On anything else.
    """

    key = str(option or 'replace_all').strip().lower().replace(' ', '_').replace('-', '_')
    if key not in PASTE_OPTIONS:
        # Named the way the dropdown shows them, so the message matches what
        # the person was looking at when they got it wrong.
        raise ValueError('option must be one of: {}. Got {!r}.'
                         .format(', '.join(k.replace('_', ' ') for k in PASTE_OPTION_ORDER),
                                 option))
    return key


# Which half of a clip to put back. A capture can write both, and they are not
# two copies of the same thing:
#
#   curves  The flag curves - what the animator actually authored. Keeps layers,
#           IK/FK state and flag-level intent, and applies instantly because it
#           is a curve swap.
#   baked   The joints-only FBX. Flattened, and it has to be imported and baked
#           back through the rig to become flag values again, which takes
#           seconds rather than no time at all. What it buys is independence
#           from the flags: it still works when the rig has been rebuilt with
#           different controls, when the clip came off another character, and
#           when the curves were never saved.
CLIP_SOURCES = ('curves', 'baked')

# Imported skeletons land here so they can be found and removed again whatever
# the FBX happened to call its own top node.
BAKE_NAMESPACE = 'mca_animlib_bake'

# How much of the frame the subject fills in a thumbnail or GIF. Deliberately
# short of 1.0: the viewport and the playblast do not share an aspect ratio, so
# anything framed right to the panel's edge is cropped when the file is written.
PREVIEW_FIT_FACTOR = 0.7


def normalise_clip_source(source):
    """
    Accept the several reasonable ways of naming a clip's two halves.

    :param str source: 'curves', 'flags', 'flag animations', 'baked',
        'baked joints', 'joints', 'fbx' or 'skeleton'. None means curves.
    :return: 'curves' or 'baked'.
    :rtype: str
    """

    if source is None:
        return 'curves'
    key = str(source).strip().lower().replace('-', ' ').replace('_', ' ')
    if key in ('curves', 'curve', 'flag', 'flags', 'flag animation', 'flag animations'):
        return 'curves'
    if key in ('baked', 'bake', 'joints', 'joint', 'baked joint', 'baked joints', 'fbx',
               'skeleton'):
        return 'baked'
    raise ValueError('{!r} is not a clip source. Use {}.'
                     .format(source, ' or '.join(repr(s) for s in CLIP_SOURCES)))


def _paste_stored_curves(anim_comp, flags, option, offset=0.0, source_range=None,
                         frag_rig=None, mirror=False, conventions=None,
                         amount=1.0, additive=False):
    """
    Copy the clip's keys onto the rig instead of swapping whole curves.

    The plain restore path reconnects a stored curve straight onto a flag, which
    is fast and keeps animation layers - but it can only mean "this curve is now
    the animation". The moment somebody wants the clip laid *over* what is
    already there, or dropped into the middle of a shot, or mirrored, or at
    seventy percent, the keys themselves have to move, and Maya's own
    copyKey/pasteKey is the thing that knows how.

    Each curve is anchored on its own first key, so flags that start at different
    times keep their relative offsets.

    ``amount`` and ``additive`` are applied after the paste, key by key, against
    the values the rig held beforehand:

    ``final = before + amount * ((clip - rest) if additive else (clip - before))``

    which gives full replacement at ``amount = 1`` with ``additive`` off, a
    half-way blend at 0.5, and a clip laid on top as an offset from rest when
    ``additive`` is on. Sampling *before* pasting is the whole trick - afterwards
    the original values are gone.

    :param anim_comp: The imported AnimatedCurvesComponent holding the clip.
    :param list flags: Flags to paste onto.
    :param str option: A key from :data:`PASTE_OPTIONS`.
    :param float offset: Frames to shift the clip by.
    :param list source_range: ``[start, end]`` of the clip to take. None takes all.
    :param frag_rig: The rig, needed to find mirror partners.
    :param bool mirror: Send each flag's curves to its opposite number.
    :param dict conventions: As :func:`get_mirror_conventions` returns.
    :param float amount: How much of the clip to take, 0 to 1.
    :param bool additive: Add the clip to what is there rather than replacing it.
    :return: ``{'flags', 'attributes', 'skipped', 'unpaired'}``.
    :rtype: dict
    """

    maya_option = PASTE_OPTIONS[option]
    low = high = None
    if source_range:
        low, high = float(source_range[0]), float(source_range[1])
        if high < low:
            raise ValueError('The source range ends ({}) before it starts ({}).'.format(high, low))

    combining = additive or abs(float(amount) - 1.0) > 1e-6
    touched_flags, attributes, skipped, unpaired = 0, 0, 0, []

    for flag in flags:
        pairs = anim_comp.get_stored_curve_pairs(flag)
        if not pairs:
            continue

        destination, convention = flag, None
        if mirror:
            destination, convention = _mirror_destination(frag_rig, flag, conventions)
            if destination is None:
                unpaired.append(flag.nodeName().split(':')[-1])
                continue

        unlocked = False
        flag_touched = False
        for object_attribute, anim_curve in pairs:
            keys = pm.keyframe(anim_curve, q=True) or []
            if low is not None:
                keys = [k for k in keys if low - 1e-6 <= k <= high + 1e-6]
            if not keys:
                skipped += 1
                continue

            channel = object_attribute.attrName(longName=True)
            if mirror and not destination.hasAttr(channel):
                skipped += 1
                continue
            target_node = str(destination if mirror else object_attribute.node())
            plug = '{}.{}'.format(target_node, channel)

            if not unlocked:
                attr_utils.unlock_and_show_attrs([a for a, _c in pairs])
                unlocked = True
            if mirror:
                try:
                    attr_utils.unlock_and_show_attrs([destination.attr(channel)])
                except Exception:
                    logger.debug('Could not unlock %s', plug, exc_info=True)

            start = keys[0] + offset
            end = keys[-1] + offset
            landing = [k + offset for k in keys]

            # What the rig held at each landing frame, before anything is pasted.
            before = {}
            if combining:
                for frame in landing:
                    try:
                        before[frame] = cmds.getAttr(plug, time=frame)
                    except Exception:
                        before[frame] = None

            copied = cmds.copyKey(str(anim_curve),
                                  **({'time': (low, high)} if low is not None else {}))
            if not copied:
                skipped += 1
                continue

            # 'replace' clears a window before pasting, so it needs both ends;
            # a single-key curve would give a zero-width window, which Maya
            # will not take - widen it to the frame itself.
            when = (start, max(end, start)) if maya_option == 'replace' else (start,)
            try:
                cmds.pasteKey(target_node, attribute=channel, option=maya_option, time=when)
            except Exception:
                logger.debug('Could not paste onto %s', plug, exc_info=True)
                skipped += 1
                continue

            default = _attribute_default(plug)
            if mirror and flag_mirror.channel_sign(channel, convention) < 0:
                # Flipped around the attribute's rest value, not around zero, so
                # a channel whose rest is not zero is not thrown off it.
                try:
                    cmds.scaleKey(target_node, attribute=channel, valueScale=-1.0,
                                  valuePivot=default, time=(start, max(end, start)))
                except Exception:
                    logger.debug('Could not flip %s', plug, exc_info=True)

            if combining:
                for frame in landing:
                    was = before.get(frame)
                    if was is None:
                        continue
                    pasted = cmds.keyframe(target_node, attribute=channel,
                                           time=(frame, frame), q=True, valueChange=True)
                    if not pasted:
                        continue
                    contribution = (pasted[0] - default) if additive else (pasted[0] - was)
                    cmds.keyframe(target_node, attribute=channel, time=(frame, frame),
                                  valueChange=was + float(amount) * contribution,
                                  absolute=True)

            attributes += 1
            flag_touched = True

        if flag_touched:
            touched_flags += 1

    return {'flags': touched_flags, 'attributes': attributes, 'skipped': skipped,
            'unpaired': unpaired}


def _skeleton_root_of(nodes):
    """
    The top joint of whatever an FBX import brought in.

    :param list nodes: Nodes the import returned.
    :return: The root joint, or None when there were no joints at all.
    :rtype: pm.nt.Joint or None
    """

    for node in nodes:
        if isinstance(node, pm.nt.Joint):
            return dag.get_absolute_parent(node, node_type=pm.nt.Joint, inclusive=True)
    return None


def _remove_imported(nodes):
    """
    Take the imported skeleton back out of the scene.

    Deleting a parent takes its children with it, hence the existence check on
    each one rather than a single delete of the list.

    :param list nodes: Nodes the import returned.
    """

    for node in nodes:
        try:
            if pm.objExists(node):
                pm.delete(node)
        except Exception:
            logger.debug('Could not delete %s from the imported skeleton.', node, exc_info=True)
    try:
        if pm.namespace(exists=BAKE_NAMESPACE):
            pm.namespace(removeNamespace=BAKE_NAMESPACE, deleteNamespaceContent=True)
    except Exception:
        logger.debug('Could not remove the %s namespace.', BAKE_NAMESPACE, exc_info=True)


def _source_skeleton_path(entry, rig_id):
    """
    The .skel the clip's own character was built on, when that is not this rig's.

    Whether a bake needs retargeting is not a question worth asking the animator.
    The clip records which character it was captured from and the rig knows what
    it is; if those differ the bake needs the source skeleton, and if they match
    it does not. Making that a checkbox would only offer the chance to get it
    wrong.

    :param clip_module.AnimClip entry: The clip.
    :param str rig_id: The rig's asset id.
    :return: ``(skel_path, character)`` - both empty when no retarget is needed.
    :rtype: tuple
    """

    character = (entry.character or '').strip()
    if not character or not rig_id or character.lower() == str(rig_id).lower():
        return None, ''

    manager = get_asset_manager()
    record = manager.get_record_by_name(character) or manager.get_record(character)
    skel_path = getattr(record, 'skel_path', '') if record is not None else ''
    if not skel_path:
        raise ValueError('{} was captured on {}, and this rig is {}. Baking it across needs {}\'s '
                         'skeleton, which is not in the asset registry. Apply the flag curves '
                         'instead, or add the asset.'
                         .format(entry.name, character, rig_id, character))
    return skel_path, character


def _bake_range(skel_root, entry, source_range=None):
    """
    The frames to bake, taken from the skeleton itself.

    The catalog's frame range is what the clip *says*; the keys on the imported
    joints are what it has. They should agree, and when they do not the file
    wins.

    :param pm.nt.Joint skel_root: The imported skeleton's root.
    :param clip_module.AnimClip entry: The clip, for a fallback range.
    :param list source_range: ``[start, end]`` to narrow to. None takes it all.
    :return: ``(start, end)``.
    :rtype: tuple
    """

    nodes = [skel_root] + (pm.listRelatives(skel_root, ad=True, type=pm.nt.Joint) or [])
    keys = pm.keyframe(nodes, q=True) or []
    if keys:
        start, end = min(keys), max(keys)
    else:
        declared = [float(x) for x in (entry.frame_range or [0, 0])]
        start, end = declared[0], declared[-1]
    if source_range:
        start = max(start, float(source_range[0]))
        end = min(end, float(source_range[1]))
        if end < start:
            raise ValueError('Frames {:.0f}-{:.0f} are outside what {} covers ({:.0f}-{:.0f}).'
                             .format(float(source_range[0]), float(source_range[1]), entry.name,
                                     min(keys) if keys else start, max(keys) if keys else end))
    return float(start), float(end)


def _flag_channel_values(flags):
    """
    Every settable channel on the flags, and what it currently holds.

    :param list flags: Flags to read.
    :return: ``{'node.attr': value}``.
    :rtype: dict
    """

    snapshot = {}
    for flag in flags:
        node = str(flag)
        for attr in (cmds.listAttr(node, keyable=True, unlocked=True, scalar=True) or []):
            plug = '{}.{}'.format(node, attr)
            try:
                snapshot[plug] = cmds.getAttr(plug)
            except Exception:
                logger.debug('Could not read %s', plug, exc_info=True)
    return snapshot


def _restore_flag_channel_values(snapshot, skip=()):
    """
    Put those channels back.

    :param dict snapshot: As :func:`_flag_channel_values` returns.
    :param list skip: Flags whose animation was restored instead, and which must
        therefore not be dragged back to a single frame's values.
    """

    skipped = set(str(flag) for flag in skip)
    for plug, value in snapshot.items():
        if plug.rsplit('.', 1)[0] in skipped:
            continue
        try:
            cmds.setAttr(plug, value)
        except Exception:
            logger.debug('Could not put %s back to %r', plug, value, exc_info=True)


def _hand_the_rig_back(frag_rig, flags, keyed, values, before_file):
    """
    Undo a borrowed bake.

    :param frag_rig: The rig that was borrowed.
    :param list flags: The flags that were baked on.
    :param dict keyed: ``{flag name: had keys}`` before the bake.
    :param dict values: As :func:`_flag_channel_values` returns.
    :param str before_file: The stash of the rig's own animation, or '' when it
        had none.
    """

    try:
        pm.cutKey(flags, clear=True)
    except Exception:
        logger.warning('Could not clear the bake off the rig.', exc_info=True)

    animated = [flag for flag in flags if keyed.get(str(flag))]
    if animated and before_file and os.path.isfile(before_file):
        stash = None
        try:
            stash = frag.AnimatedCurvesComponent.import_animated_curve_data(before_file)
            if stash is not None:
                stash.restore_all_animation_curves(obj_list=animated, force_unlock=True,
                                                   keep_curves=False, delete_old_curves=True)
        except Exception:
            logger.warning("Could not put the rig's own animation back after the bake.",
                           exc_info=True)
        finally:
            if stash is not None:
                try:
                    stash.remove()
                except Exception:
                    logger.debug('Could not tidy up the stash node.', exc_info=True)
    else:
        animated = []
    _restore_flag_channel_values(values, skip=animated)


def bake_skeleton_to_stored_curves(frag_rig, flags, skel_root, start_frame, end_frame,
                                   diff_skel_path=None):
    """
    Bake a skeleton onto a rig, lift the result off as stored curves, and give
    the rig back the way it was found.

    Everything an apply offers - insert, merge, Mirror, Additive, Amount - is
    defined against a stored curve set. Rather than write a second
    implementation of all of it for baked joints, the baked route turns itself
    into one and goes through exactly the same code afterwards. What comes back
    is the same kind of object the curve route produces - a component imported
    from a file - so nothing downstream can tell the two apart.

    Going via files rather than keeping a component alive is not squeamishness.
    A staged component is a FRAG child of the rig, and a bake takes the rig
    apart: it strips constraints off every flag, zeroes them, re-attaches the
    whole thing to a skeleton and bakes. A node parented into that does not
    reliably survive it - the first version of this held one across the bake and
    came back to ``'AnimatedCurvesComponent' does not exist``. Writing it out
    means nothing of ours is in the scene while the bake runs.

    The rig is the solver here, not the destination: it is the thing that knows
    how to turn joint transforms back into flag values. Borrowing it means its
    own animation has to be put back, and that happens in a ``finally``, because
    a rig left holding a half-finished bake is a worse outcome than a failed
    apply.

    :param frag_rig: The rig to bake through.
    :param list flags: The flags to harvest.
    :param pm.nt.Joint skel_root: Root of the skeleton carrying the animation.
    :param float start_frame: First frame to bake.
    :param float end_frame: Last frame to bake.
    :param str diff_skel_path: The source character's .skel, when the animation
        came off a different skeleton to this rig's.
    :return: An AnimatedCurvesComponent holding the baked result. The caller owns
        it and must call ``remove()``.
    """

    keyed = {str(flag): bool(pm.keyframe(flag, q=True, keyframeCount=True)) for flag in flags}
    values = _flag_channel_values(flags)
    scratch = tempfile.mkdtemp(prefix='mca_animlib_bake_')
    before_file = os.path.join(scratch, 'before.ma')
    baked_file = os.path.join(scratch, 'baked.ma')
    stashed = ''
    try:
        animated = [flag for flag in flags if keyed[str(flag)]]
        if animated:
            _export_curve_master(frag_rig, animated, before_file, key_ikfk=False)
            stashed = before_file
        rig_utils.animate_rig_from_skeleton_cmd(
            frag_rig=frag_rig, skel_root=skel_root,
            start_frame=int(round(float(start_frame))), end_frame=int(round(float(end_frame))),
            append=False, motion_encode=False, diff_skel_path=diff_skel_path)
        _export_curve_master(frag_rig, flags, baked_file)
    finally:
        _hand_the_rig_back(frag_rig, flags, keyed, values, stashed)

    try:
        baked = frag.AnimatedCurvesComponent.import_animated_curve_data(baked_file)
        if baked is None:
            raise ValueError('The bake produced no curves. The skeleton may not match this rig.')
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return baked


def _stored_curves_from_clip_fbx(entry, frag_rig, flags, catalog, source_range=None):
    """
    The baked half of a clip, as stored curves ready to apply.

    :param clip_module.AnimClip entry: The clip.
    :param frag_rig: The rig to bake through.
    :param list flags: Flags to harvest.
    :param catalog_module.AnimCatalog catalog: For the library root.
    :param list source_range: ``[start, end]`` of the clip to take.
    :return: ``(component, note)``, where note carries the bake range, the
        character it was retargeted from if any, and the flags the bake did not
        reach.
    :rtype: tuple
    """

    fbx_path = entry.artifact_path('fbx', catalog.library_root)
    if not fbx_path or not os.path.isfile(fbx_path):
        raise ValueError('{} has no baked skeleton on disk, so there is nothing to bake from. '
                         'Apply its flag curves instead, or rebuild the FBX.'.format(entry.name))

    skel_path, retargeted_from = _source_skeleton_path(entry, rig_asset_id(frag_rig))

    imported = fbx_utils.import_fbx(fbx_path, import_namespace=BAKE_NAMESPACE)
    try:
        skel_root = _skeleton_root_of(imported)
        if skel_root is None:
            raise ValueError('{} has no joints in it, so there is nothing to bake from.'
                             .format(os.path.basename(fbx_path)))
        start, end = _bake_range(skel_root, entry, source_range)
        baked = bake_skeleton_to_stored_curves(frag_rig, flags, skel_root, start, end,
                                               diff_skel_path=skel_path)
    finally:
        _remove_imported(imported)

    # A bake only reaches the flags the rig's own components hand over to it, and
    # that is not always every flag - on Frostwind the pony tail comes back with
    # nothing. Saying which ones is the difference between a known limitation
    # and hair that mysteriously does not move.
    missed = sorted(flag.nodeName().split(':')[-1] for flag in flags
                    if not baked.get_stored_curve_pairs(flag))
    return baked, {'retargeted_from': retargeted_from, 'baked_range': [start, end],
                   'not_baked': missed}


# --- Public API ---------------------------------------------------------------------------------------------------

@_safe
def capture_clip(name, frag_rig=None, category='Uncategorised', character=None,
                 frame_range=None, tags=None, description='', export_curves=True,
                 export_fbx=True, capture_preview=True, capture_gif_preview=False,
                 clip_type='animation', selected_only=False, namespace=None, replace=False,
                 flatten_layers=False):
    """
    Save the animation on a rig in the scene as a library clip.

    Writes the curve master, and by default also the portable FBX and a preview,
    then registers the clip in the catalog. The rig keeps its animation - curves
    are duplicated on the way out, not moved.

    ``export_curves`` and ``export_fbx`` are the two halves of the clip and can
    be asked for separately. Curves only is the usual choice for something an
    animator will re-apply; FBX only is for animation leaving for another DCC
    that nobody will put back on a rig. Both is the default because the two
    answer different questions and the FBX is cheap once the bake has run.

    :param str name: Clip display name, e.g. 'FW_Idle_Combat_01'.
    :param frag_rig: The rig to capture: a FRAGRig or a node name. None takes
        it from the selection.
    :param str category: Grouping, e.g. 'Locomotion'.
    :param str character: Owning character's asset id. Defaults to the rig's own.
    :param list frame_range: ``[start, end]``. None uses the rig's keyframe range.
    :param list tags: Free-text tags.
    :param str description: Free text.
    :param bool export_curves: Write the curve master, which is what lets the
        clip be applied to a rig later.
    :param bool export_fbx: Bake a joints-only FBX for other DCCs.
    :param bool capture_preview: Grab a playblast frame for the browser.
    :param bool capture_gif_preview: Also play the range down to a looping GIF.
        Off by default because it costs a playblast of every frame - worth it for
        a clip somebody is saving by hand, not for a batch of 865.
    :param str clip_type: 'animation' or 'pose'.
    :param bool selected_only: Capture only the rig's selected flags.
    :param str namespace: Capture the rig under this namespace.
    :param bool replace: Overwrite a clip that already has this id.
    :param bool flatten_layers: Collapse animation layers into one curve per
        channel. Off by default, because a layered clip that comes back layered
        is the more recoverable mistake: flattening cannot be undone once the
        file is written, and only 'replace all' over the whole clip can put
        layers back, so a layered clip is one you cannot mirror or blend. The
        rig in the scene is never touched either way.
    :return: Response describing the clip.
    :rtype: dict
    """

    if not name:
        raise ValueError('name is required.')
    if not export_curves and not export_fbx:
        raise ValueError('Nothing to write: turn on the curves, the FBX, or both.')
    if clip_type not in clip_module.CLIP_TYPES:
        raise ValueError('clip_type must be one of: {}.'.format(', '.join(clip_module.CLIP_TYPES)))

    rig = resolve_rig(frag_rig, namespace=namespace)
    character = character or rig_asset_id(rig)
    if not character:
        raise ValueError('The rig does not carry an asset id, so the clip has no owner. Pass '
                         'character= explicitly.')

    candidates = target_flags(rig, selected_only=selected_only)
    flags = keyed_flags(candidates)
    if not flags:
        raise ValueError('Nothing on {} is keyed, so there is no animation to capture.{}'
                         .format('the selected flags' if selected_only else 'this rig',
                                 ' Use a pose capture to store the rig as it stands.'
                                 if clip_type == 'animation' else ''))

    # If the Animation Exporter already has a sequence for this animation, take
    # its settings: it is the pipeline's answer to how this clip gets exported.
    sequence = sequence_settings_for(rig, name)
    start_at_zero, root_to_origin = True, True
    if sequence:
        start_at_zero = sequence['start_at_zero']
        root_to_origin = sequence['root_to_origin']

    if frame_range:
        start_frame, end_frame = float(frame_range[0]), float(frame_range[1])
    elif sequence and sequence['frame_range']:
        start_frame, end_frame = (float(x) for x in sequence['frame_range'])
    else:
        start_frame, end_frame = time_utils.get_keyframe_range_from_nodes(flags)
        if start_frame is None:
            raise ValueError('Could not work out a keyframe range for this rig.')

    catalog = animlib_api.get_catalog()
    folder, paths = _clip_paths(character, category, name, catalog.library_root)
    if not os.path.isdir(folder):
        os.makedirs(folder)

    curves_relative, curves_absolute = paths['curves']
    if export_curves and os.path.isfile(curves_absolute) and not replace:
        raise ValueError('{} already exists. Pass replace=True to overwrite it, or pick another '
                         'name.'.format(curves_absolute))

    # Read before anything is written: flattening merges the layers and undoes
    # the merge, and asking afterwards has caught the scene mid-flight before.
    scene_layered = scene_has_layers()
    # What the *clip* carries, which is not what the scene carries.
    has_layers = scene_layered and not flatten_layers
    written = {}

    if export_curves:
        _export_curve_master(rig, flags, curves_absolute,
                             crop_range=[start_frame, end_frame] if frame_range else None,
                             merge_layers=flatten_layers)
        written['curves'] = curves_relative
    else:
        curves_relative = ''

    fbx_relative = ''
    if export_fbx:
        fbx_response = export_clip_fbx_file(rig, paths['fbx'][1],
                                            start_frame=start_frame, end_frame=end_frame,
                                            clip_name=name,
                                            start_at_zero=start_at_zero,
                                            root_to_origin=root_to_origin)
        if fbx_response['ok']:
            fbx_relative = paths['fbx'][0]
            written['fbx'] = fbx_relative
        else:
            logger.warning('Captured the curves but the FBX failed: %s', fbx_response['message'])

    preview_relative = ''
    if capture_preview:
        preview_response = capture_preview_image(paths['preview'][1],
                                                 frame=(start_frame + end_frame) / 2.0,
                                                 focus_nodes=preview_focus(rig, flags))
        if preview_response['ok']:
            preview_relative = paths['preview'][0]
            written['preview'] = preview_relative

    gif_relative = ''
    gif_note = ''
    if capture_gif_preview:
        gif_response = capture_gif(paths['gif'][1], start_frame=start_frame,
                                   end_frame=end_frame, focus_nodes=preview_focus(rig, flags))
        if gif_response['ok']:
            gif_relative = paths['gif'][0]
            written['gif'] = gif_relative
        else:
            # The clip is already safely on disk; a missing GIF is cosmetic.
            gif_note = ' No GIF: {}'.format(gif_response['message'])
            logger.warning('Captured %s but the GIF failed: %s', name, gif_response['message'])

    registered = animlib_api.register_clip(
        name=name, character=character, category=category,
        curves_file=curves_relative, fbx_file=fbx_relative, preview_file=preview_relative,
        gif_file=gif_relative,
        frame_range=[start_frame, end_frame], fps=scene_fps(),
        root_motion=detect_root_motion(rig), tags=tags or [], description=description,
        source_file=pm.sceneName() or '', has_layers=has_layers, flag_count=len(flags),
        clip_type=clip_type, replace=replace)
    if not registered['ok']:
        raise ValueError(registered['message'])

    result = dict(registered['result'])
    result['files_written'] = written
    message = 'Captured {} {} ({} flag{}, frames {:.0f}-{:.0f}).'.format(
        clip_type, name, len(flags), '' if len(flags) == 1 else 's', start_frame, end_frame)
    if selected_only:
        message += ' Selected flags only.'
    if sequence:
        message += ' Used the export settings already registered for this animation.'
    if export_curves and scene_layered:
        message += (' Animation layers flattened in the clip; your scene still has them.'
                    if flatten_layers else ' Animation layers preserved.')
    if not fbx_relative and export_fbx:
        message += ' FBX export failed; the curves are saved.'
    if not export_curves:
        message += ' FBX only, so it cannot be applied back onto a rig.'
    message += gif_note
    return result, message


@_safe
def capture_pose(name, frag_rig=None, category='Poses', character=None, frame=None,
                 tags=None, description='', selected_only=False, namespace=None,
                 capture_preview=True, replace=False, flatten_layers=False):
    """
    Save the rig's current pose as a library clip.

    A pose does not need the rig to be keyed - which is the whole point, because
    the rig an animator wants to save a pose off is usually one they have just
    posed by hand. The flags are keyed at the frame, stored, and then put back
    the way they were: a flag that had no animation before has none afterwards.

    No FBX. A single-frame skeleton bake is not something any other DCC wants,
    and the curve master restores the pose exactly.

    :param str name: Pose display name.
    :param frag_rig: The rig: a FRAGRig or a node name. None takes it from the
        selection.
    :param str category: Grouping. Defaults to 'Poses'.
    :param str character: Owning character's asset id. Defaults to the rig's own.
    :param float frame: Frame to read the pose at. None uses the current frame.
    :param bool flatten_layers: Collapse animation layers into one curve per
        channel on the way out. The rig in the scene keeps its layers.
    :param list tags: Free-text tags.
    :param str description: Free text.
    :param bool selected_only: Store only the rig's selected flags.
    :param str namespace: The rig under this namespace.
    :param bool capture_preview: Grab a playblast frame for the browser.
    :param bool replace: Overwrite a pose that already has this id.
    :return: Response describing the pose.
    :rtype: dict
    """

    if not name:
        raise ValueError('name is required.')

    rig = resolve_rig(frag_rig, namespace=namespace)
    character = character or rig_asset_id(rig)
    if not character:
        raise ValueError('The rig does not carry an asset id, so the pose has no owner. Pass '
                         'character= explicitly.')

    flags = target_flags(rig, selected_only=selected_only)
    if not flags:
        raise ValueError('This rig has no flags to pose.')

    frame = float(pm.currentTime(q=True) if frame is None else frame)

    catalog = animlib_api.get_catalog()
    folder, paths = _clip_paths(character, category, name, catalog.library_root)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    curves_relative, curves_absolute = paths['curves']
    if os.path.isfile(curves_absolute) and not replace:
        raise ValueError('{} already exists. Pass replace=True to overwrite it, or pick another '
                         'name.'.format(curves_absolute))

    # Remember what was keyed so the rig can be handed back untouched.
    before = {}
    for flag in flags:
        before[str(flag)] = set(pm.keyframe(flag, q=True) or [])

    # Read before the export, for the same reason as in capture_clip: flattening
    # merges the layers and undoes the merge, so asking afterwards can catch the
    # scene mid-flight.
    scene_layered = scene_has_layers()
    previous_time = pm.currentTime(q=True)
    try:
        pm.currentTime(frame)
        pm.setKeyframe(flags, time=frame)
        _export_curve_master(rig, flags, curves_absolute, crop_range=[frame, frame],
                             merge_layers=flatten_layers)
    finally:
        for flag in flags:
            keyed_before = before.get(str(flag)) or set()
            try:
                if not keyed_before:
                    pm.cutKey(flag, clear=True)
                elif frame not in keyed_before:
                    pm.cutKey(flag, time=(frame, frame), clear=True)
            except Exception:
                logger.debug('Could not undo the temporary key on %s', flag, exc_info=True)
        try:
            pm.currentTime(previous_time)
        except Exception:
            logger.debug('Could not restore the current frame.', exc_info=True)

    preview_relative = ''
    if capture_preview:
        preview_response = capture_preview_image(paths['preview'][1], frame=frame,
                                                 focus_nodes=preview_focus(rig, flags))
        if preview_response['ok']:
            preview_relative = paths['preview'][0]

    registered = animlib_api.register_clip(
        name=name, character=character, category=category,
        curves_file=curves_relative, preview_file=preview_relative,
        frame_range=[frame, frame], fps=scene_fps(), root_motion='in_place',
        tags=tags or [], description=description, source_file=pm.sceneName() or '',
        has_layers=scene_layered and not flatten_layers,
        flag_count=len(flags), clip_type='pose', replace=replace)
    if not registered['ok']:
        raise ValueError(registered['message'])

    result = dict(registered['result'])
    result['files_written'] = {'curves': curves_relative}
    message = 'Captured pose {} ({} flag{} at frame {:.0f}).'.format(
        name, len(flags), '' if len(flags) == 1 else 's', frame)
    if selected_only:
        message += ' Selected flags only.'
    if scene_layered:
        message += (' Animation layers flattened in the pose; your scene still has them.'
                    if flatten_layers else ' Animation layers preserved.')
    return result, message


@contextlib.contextmanager
def _undone_afterwards(what):
    """
    Run a block and then put the scene back the way it was.

    Maya has no non-destructive way to flatten animation layers: the merge bakes
    every layered attribute down and deletes the layers, and it does it to the
    scene, not to a copy. Since a capture duplicates the curves on the way out,
    the merge is only ever wanted for what gets written - so the whole thing is
    done inside one undo chunk and undone the moment the file is on disk.

    The file survives, because writing one is not an undoable operation.

    :param str what: Chunk name, for the undo queue.
    """

    pm.undoInfo(openChunk=True, chunkName=what)
    try:
        yield
    finally:
        pm.undoInfo(closeChunk=True)
        try:
            pm.undo()
        except Exception:
            logger.warning('Could not undo %s. The scene may have been left flattened.', what,
                           exc_info=True)


def _flattening_is_safe():
    """
    Refuse to flatten when the undo that puts the scene back is not available.

    Without undo the merge is permanent and scene-wide, and an animator who
    ticked a save option would lose their layer setup. That is a much worse
    outcome than a refused capture.

    :raise ValueError: When the undo queue is off.
    """

    try:
        enabled = bool(pm.undoInfo(q=True, state=True))
    except Exception:
        enabled = False
    if not enabled:
        raise ValueError('Flattening the layers needs the undo queue, because the only way Maya '
                         'merges layers is by doing it to the scene and undoing it afterwards. '
                         "Undo is off, so this would flatten your scene's layers for good. Turn "
                         'undo on, or capture with the layers preserved.')


def _export_curve_master(frag_rig, flags, curves_absolute, crop_range=None, key_ikfk=True,
                         merge_layers=False):
    """
    Stage the flags' curves on a component and export just that node.

    ``keep_animation`` duplicates the curves, so the rig in the scene keeps its
    animation and the staging node is thrown away afterwards either way.

    :param frag_rig: The rig the staging component hangs off.
    :param list flags: Flags whose curves are stored.
    :param str curves_absolute: Where to write the .ma.
    :param list crop_range: ``[start, end]`` to trim the stored curves to. None
        stores them whole.
    :param bool key_ikfk: Key the IK/FK switches so the clip carries the state it
        was authored in. Right for a capture; wrong when the file is only a
        stash of the rig's own animation that is about to be handed straight
        back, because it would come back with a key it did not go out with.
    :param bool merge_layers: Collapse the animation layers into one curve per
        channel on the way out. Maya can only merge layers destructively, so
        this happens inside an undo chunk that is rolled back once the file is
        written - see :func:`_undone_afterwards`.
    """

    if merge_layers and scene_has_layers():
        _flattening_is_safe()
        with _undone_afterwards('Flatten layers for {}'.format(os.path.basename(curves_absolute))):
            _stage_and_export(frag_rig, flags, curves_absolute, crop_range, key_ikfk, True)
        if not scene_has_layers():
            logger.warning('The animation layers did not come back after flattening %s.',
                           os.path.basename(curves_absolute))
        return
    _stage_and_export(frag_rig, flags, curves_absolute, crop_range, key_ikfk, False)


def _stage_and_export(frag_rig, flags, curves_absolute, crop_range, key_ikfk, merge_layers):
    """
    The staging itself, with no opinion about undo.

    :param frag_rig: The rig the staging component hangs off.
    :param list flags: Flags whose curves are stored.
    :param str curves_absolute: Where to write the .ma.
    :param list crop_range: ``[start, end]`` to trim to, or None.
    :param bool key_ikfk: Key the IK/FK switches first.
    :param bool merge_layers: Merge the layers before storing.
    """

    anim_comp = frag.AnimatedCurvesComponent.create(frag_rig)
    try:
        for flag in (flags if key_ikfk else []):
            if flag.hasAttr('ikfk_switch'):
                pm.setKeyframe(flag)
        store_kwargs = {'obj_list': flags, 'keep_animation': True,
                        'merge_layers': bool(merge_layers)}
        if crop_range:
            store_kwargs['min_time_range'] = crop_range[0]
            store_kwargs['max_time_range'] = crop_range[1]
        anim_comp.store_all_animation_curves(**store_kwargs)
        anim_comp.export(curves_absolute)
    finally:
        # Storing a layered rig duplicates its layer network so the clip can
        # carry it, and those duplicates are left in the scene - so every
        # layered capture used to add a ProbeLayer1, ProbeLayer2 to the
        # animator's layer list. They are safe to identify: the duplicates carry
        # 'original_anim_layer' and the animator's own layers do not.
        staged_layers = []
        try:
            staged_layers = [layer for layer
                             in (anim_comp.pynode.animationLayers.listConnections() or [])
                             if layer.hasAttr('original_anim_layer')]
        except Exception:
            logger.debug('Could not list the staged animation layers.', exc_info=True)
        try:
            anim_comp.remove()
        except Exception:
            logger.debug('Could not tidy up the staging component.', exc_info=True)
        for layer in staged_layers:
            try:
                if pm.objExists(layer):
                    pm.delete(layer)
            except Exception:
                logger.debug('Could not delete the staged layer %s.', layer, exc_info=True)


@_safe
def apply_clip(clip_id, frag_rig=None, start_time=None, option='replace_all',
               source_range=None, selected_only=False, namespace=None,
               mirror=False, additive=False, amount=100.0, source='curves'):
    """
    Put a library clip onto a rig in the scene.

    The clip file on disk is never modified, so the same clip applies to as many
    rigs as you like.

    Which half of the clip to use is ``source``. The flag curves are what the
    animator authored and are the default; the baked joints are the same
    performance flattened onto a skeleton, and applying those means importing it
    and baking back through the rig. That costs seconds instead of nothing, and
    in return it does not care what the flags are called - so it is the route
    that still works on a rebuilt rig, on another character, and on a clip whose
    curves were never saved. Whether the bake needs retargeting is worked out
    from the clip's character and the rig's asset id, not asked.

    Two routes then apply the result, picked by what is being asked for:

    * ``replace all`` over the whole clip reconnects the stored curves straight
      onto the flags. It is fast and it keeps animation layers, and it is the
      default because "put this animation on" is what people mean nearly always.
    * Anything else - a paste option that has to reckon with animation already on
      the rig, or only part of the clip - copies the keys across instead, using
      Maya's own paste modes. Layers cannot survive that route, so a layered clip
      asked for one is refused rather than quietly flattened.

    :param str clip_id: Clip id or display name.
    :param frag_rig: The rig to animate: a FRAGRig or a node name. None takes
        it from the selection.
    :param float start_time: Frame the animation should start on. None keeps the
        clip's own timing.
    :param str option: 'replace', 'replace all', 'insert' or 'merge' - see
        :data:`PASTE_OPTIONS`.
    :param list source_range: ``[start, end]`` of the clip to take. None takes
        all of it.
    :param bool selected_only: Apply only to the rig's selected flags.
    :param str namespace: Apply to the rig under this namespace.
    :param bool mirror: Send each flag's animation to its opposite number, with
        the channels the rig's measured convention says to flip.
    :param bool additive: Add the clip to the rig's existing animation as an
        offset from rest, rather than replacing it.
    :param float amount: How much of the clip to take, as a percentage. 100 is
        all of it; 50 lands the rig half way between what it was doing and what
        the clip says.
    :param str source: 'curves' for the flag animation, 'baked' for the joints -
        see :data:`CLIP_SOURCES`.
    :return: Response describing what was applied.
    :rtype: dict
    """

    option = normalise_paste_option(option)
    source = normalise_clip_source(source)
    amount = float(amount) / 100.0
    combining = additive or abs(amount - 1.0) > 1e-6

    catalog = animlib_api.get_catalog()
    entry = catalog.get(clip_id) or catalog.get_by_name(clip_id)
    if entry is None:
        raise ValueError('No clip with id or name {!r} in the library.'.format(clip_id))

    curves_path = entry.artifact_path('curves', catalog.library_root)
    if source == 'curves' and (not curves_path or not os.path.isfile(curves_path)):
        extra = (' It does have a baked skeleton - apply that with source="baked".'
                 if entry.has_baked_joints else
                 ' The file may have gone missing - run check_library.')
        raise ValueError('{} has no curve file on disk, so there is nothing to apply.{}'
                         .format(entry.name, extra))

    if (entry.get('clip_type') or 'animation') == 'pose':
        if source == 'baked':
            raise ValueError('{} is a pose, and poses are saved as flag values only - there is no '
                             'baked skeleton to apply. Use the flag animations.'.format(entry.name))
        # A pose belongs wherever the rig is now. Restoring its curves would put
        # keys back on whatever frame it happened to be captured on, which is
        # almost never what anyone wants, so this hands over to apply_pose and
        # the paste options simply do not apply.
        posed = apply_pose(entry.clip_id, frag_rig=frag_rig, namespace=namespace,
                           selected_only=selected_only, percent=float(amount) * 100.0,
                           mirror=mirror, additive=additive)
        if not posed['ok']:
            raise ValueError(posed['message'])
        ignored = [name for name, given in (('option', option != 'replace_all'),
                                            ('source range', bool(source_range)),
                                            ('start time', start_time is not None)) if given]
        message = posed['message']
        if ignored:
            message += ' ({} does not apply to a pose.)'.format(' or '.join(ignored))
        return posed['result'], message

    if source_range:
        source_range = [float(source_range[0]), float(source_range[1])]
        if source_range[1] < source_range[0]:
            raise ValueError('The source range ends ({:.0f}) before it starts ({:.0f}).'
                             .format(source_range[1], source_range[0]))

    # Mirroring, blending and adding all need the keys themselves, not a curve
    # swap, so any of them forces the paste route.
    paste_route = (option != 'replace_all' or bool(source_range)
                   or mirror or combining)
    if paste_route and entry.has_layers and source == 'curves':
        raise ValueError('{} carries animation layers, and only "replace all" over the whole clip '
                         'can put those back intact. Pasting keys would flatten them. Apply it '
                         'with "replace all", or capture a version without layers.'
                         .format(entry.name))

    rig = resolve_rig(frag_rig, namespace=namespace)
    rig_id = rig_asset_id(rig)
    note = ''
    if entry.character and rig_id and entry.character.lower() != rig_id.lower():
        note = (' Note: this clip was captured on {}, not {} - flags that do not match by name '
                'are skipped.'.format(entry.character, rig_id))

    flags = target_flags(rig, selected_only=selected_only)
    conventions = get_mirror_conventions(rig) if mirror else None

    bake_note = {}
    if source == 'baked':
        anim_comp, bake_note = _stored_curves_from_clip_fbx(
            entry, rig, flags, catalog, source_range=source_range)
    else:
        anim_comp = frag.AnimatedCurvesComponent.import_animated_curve_data(curves_path)
        if anim_comp is None:
            raise ValueError('{} does not contain a stored curve node. It may have been saved by '
                             'an older tool.'.format(os.path.basename(curves_path)))

    pasted = None
    try:
        if paste_route:
            # Everything is measured from the clip's own start, so a clip that
            # was authored at frame 30 still lands where it is asked to.
            clip_start = (bake_note['baked_range'][0] if bake_note
                          else source_range[0] if source_range
                          else float((entry.frame_range or [0, 0])[0]))
            offset = 0.0 if start_time is None else float(start_time) - clip_start
            pasted = _paste_stored_curves(anim_comp, flags, option,
                                          offset=offset, source_range=source_range,
                                          frag_rig=rig, mirror=mirror,
                                          conventions=conventions,
                                          amount=amount, additive=additive)
        else:
            # The stored restore only shifts on whole frames, so make that
            # explicit rather than letting a fractional value be ignored.
            restore_start = None if start_time is None else int(round(float(start_time)))
            anim_comp.restore_all_animation_curves(obj_list=flags,
                                                   force_unlock=True,
                                                   keep_curves=False,
                                                   delete_old_curves=True,
                                                   start_time=restore_start)
    finally:
        try:
            anim_comp.remove()
        except Exception:
            logger.debug('Could not tidy up the imported curve node.', exc_info=True)

    animated = [f.nodeName() for f in flags
                if pm.keyframe(f, q=True, keyframeCount=True)]
    result = {'clip_id': entry.clip_id, 'name': entry.name,
              'rig': rig_namespace(rig) or rig_id or str(rig.pynode),
              'rig_namespace': rig_namespace(rig), 'rig_asset_id': rig_id,
              'source': source, 'option': option, 'flags_animated': len(animated),
              'mirror': bool(mirror), 'additive': bool(additive),
              'amount': round(amount * 100.0, 1),
              'frame_range': list(entry.frame_range or [])}
    if pasted:
        result['pasted'] = pasted
    if bake_note:
        result['baked_range'] = bake_note['baked_range']
        result['not_baked'] = bake_note['not_baked']
        if bake_note['retargeted_from']:
            result['retargeted_from'] = bake_note['retargeted_from']

    how = '' if option == 'replace_all' and not source_range else ' with {}'.format(
        option.replace('_', ' '))
    if source == 'baked':
        how = ' from baked joints{}'.format(how)
    for label, on in (('mirrored', mirror), ('additive', additive)):
        if on:
            how += ', {}'.format(label) if how else ' {}'.format(label)
    if abs(amount - 1.0) > 1e-6:
        how += ' at {:.0f}%'.format(amount * 100.0)
    scope = ' (selected flags only)' if selected_only else ''
    message = 'Applied {}{} to {}{} - {} flag(s) animated.{}'.format(
        entry.name, how, rig_id or rig_namespace(rig) or str(rig.pynode), scope,
        len(animated), note)
    if source_range:
        message += ' Took frames {:.0f}-{:.0f} of the clip.'.format(*source_range)
    if bake_note and bake_note['retargeted_from']:
        message += " Retargeted from {}'s skeleton.".format(bake_note['retargeted_from'])
    if bake_note and bake_note['not_baked']:
        missed = bake_note['not_baked']
        message += (' {} flag(s) a bake does not drive were left at rest: {}{}.'
                    .format(len(missed), ', '.join(missed[:5]),
                            ' and {} more'.format(len(missed) - 5) if len(missed) > 5 else ''))
    if pasted and pasted['skipped']:
        message += ' {} attribute(s) had nothing to paste.'.format(pasted['skipped'])
    if pasted and pasted.get('unpaired'):
        message += (' {} flag(s) have no opposite number on this rig and were left alone: {}.'
                    .format(len(pasted['unpaired']), ', '.join(sorted(pasted['unpaired'])[:5])))
    return result, message


@_safe
def list_scene_rigs():
    """
    The FRAG rigs in the open scene, for a namespace picker.

    :return: Response with ``[{'namespace', 'asset_id', 'node', 'flags'}]``.
    :rtype: dict
    """

    rows = scene_rigs()
    if not rows:
        return rows, 'No rigs in the scene.'
    named = [r['namespace'] for r in rows if r['namespace']]
    return rows, '{} rig(s) in the scene{}.'.format(
        len(rows), ': {}'.format(', '.join(named)) if named else '')


# --- Mirroring ----------------------------------------------------------------------------------------------------

def flag_map(frag_rig):
    """
    A rig's flags, keyed by their short name.

    :param frag_rig: The rig.
    :return: ``{short_name: flag}``.
    :rtype: dict
    """

    return {f.nodeName().split(':')[-1]: f for f in frag_rig.get_flags()}


def mirror_partner(frag_rig, flag):
    """
    The flag on the other side of the rig, or the flag itself for a centre one.

    :param frag_rig: The rig.
    :param flag: A flag.
    :return: Its partner, or None when the flag is sided and its partner is absent.
    :rtype: pm.nt.Transform or None
    """

    by_name = flag_map(frag_rig)
    name = flag.nodeName().split(':')[-1]
    partner_name = flag_mirror.mirror_name(name)
    if not partner_name:
        return flag
    return by_name.get(partner_name)


def _reflection_matrix(centre_x):
    """
    The matrix that reflects a world point across the plane ``x = centre_x``.

    :param float centre_x: Where the rig's centre line sits in world X.
    :return: The reflection, in Maya's row-vector convention.
    :rtype: pm.dt.Matrix
    """

    return pm.dt.Matrix([-1.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0],
                        [2.0 * centre_x, 0.0, 0.0, 1.0])


def _probe_points(matrix, reach=5.0):
    """
    Four world points that pin down a frame's position *and* its orientation.

    Position alone cannot tell a rotation apart from no rotation at all, since a
    flag spinning in place does not move. Carrying three axis tips along with the
    origin makes every channel observable.

    :param pm.dt.Matrix matrix: A world matrix.
    :param float reach: How far along each local axis to place a probe.
    :return: ``[(x, y, z)] * 4`` in world space.
    :rtype: list[tuple]
    """

    points = []
    for local in ((0, 0, 0), (reach, 0, 0), (0, reach, 0), (0, 0, reach)):
        world = pm.dt.Point(local) * matrix
        points.append((world[0], world[1], world[2]))
    return points


def _attached_probes(rest_matrix, reach=10.0):
    """
    Probe offsets that are **world**-axis aligned at rest, expressed in the
    flag's local space so they travel with it.

    Using the flag's own axes instead makes reflection meaningless for a flag on
    the centre line: reflecting a frame flips its handedness, so its X axis tip
    lands where no rotation of that flag can put it, and the measurement comes
    back "no clear answer" for every rotation channel. World-aligned offsets have
    no handedness to lose - the Y and Z ones lie *in* the mirror plane and map
    onto themselves under it, which is exactly what makes them usable as a
    reference.

    There is no +X probe, and that omission is the point. A probe offset along
    world X does not reflect onto itself - it lands on the far side of the plane,
    where the partner flag's *-X* probe lives, so comparing it against the
    partner's +X probe compares two unrelated points. Adding one made the
    measurement fail outright for every finger, hand and foot. The origin and the
    two in-plane probes are three non-collinear points, which pin down a rigid
    motion completely.

    :param pm.dt.Matrix rest_matrix: The flag's world matrix at rest.
    :param float reach: How far to offset each probe.
    :return: ``[origin, +Y, +Z]`` as local points.
    :rtype: list[pm.dt.Point]
    """

    inverse = rest_matrix.inverse()
    origin = pm.dt.Point(0, 0, 0) * rest_matrix
    locals_ = []
    for offset in ((0, 0, 0), (0, reach, 0), (0, 0, reach)):
        world = pm.dt.Point(origin[0] + offset[0], origin[1] + offset[1], origin[2] + offset[2])
        locals_.append(world * inverse)
    return locals_


def _probe_attached(local_points, matrix):
    """
    :param list local_points: Local points from :func:`_attached_probes`.
    :param pm.dt.Matrix matrix: The flag's world matrix now.
    :return: Their world positions.
    :rtype: list[tuple]
    """

    out = []
    for point in local_points:
        world = point * matrix
        out.append((world[0], world[1], world[2]))
    return out


def _worst_distance(left, right):
    """
    :param list left: World points.
    :param list right: World points.
    :return: The largest distance between corresponding points.
    :rtype: float
    """

    worst = 0.0
    for (ax, ay, az), (bx, by, bz) in zip(left, right):
        worst = max(worst, ((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2) ** 0.5)
    return worst


def _subtract(points, origin_points):
    """
    :param list points: World points.
    :param list origin_points: The same points before whatever moved them.
    :return: The displacement of each point.
    :rtype: list[tuple]
    """

    return [(a[0] - b[0], a[1] - b[1], a[2] - b[2])
            for a, b in zip(points, origin_points)]


def _mirror_vectors(vectors):
    """
    Reflect displacement vectors across the centre line.

    A vector has no position, so only its X component turns over - unlike a
    point, which also has to move to the other side of the plane.

    :param list vectors: Displacements.
    :return: The reflected displacements.
    :rtype: list[tuple]
    """

    return [(-x, y, z) for x, y, z in vectors]


def _verdict(scores, tolerance, delta):
    """
    Decide which sign a measurement supports, if either.

    Two conditions, and both matter. The winning sign has to be *small* - the two
    poses really do land on top of each other - and it has to be decisively
    better than the alternative. A fixed epsilon alone was rejecting good
    measurements that missed by 0.117 on a long IK chain while, in principle,
    accepting a coin-flip between two equally bad scores.

    :param dict scores: ``{sign: worst distance}``.
    :param float tolerance: How close the winner has to be.
    :param float delta: How far the flag was posed, which sets the scale a
        genuine mismatch should show up at.
    :return: ``(sign or None, best_score, other_score)``.
    :rtype: tuple
    """

    best = min(scores, key=scores.get)
    other = max(scores, key=scores.get)
    best_score, other_score = scores[best], scores[other]
    if best_score > tolerance:
        return None, best_score, other_score
    # A real mismatch is on the order of the pose itself, not a rounding error.
    decisive = other_score - best_score > delta * 0.1 or other_score > best_score * 10
    return (best if decisive else None), best_score, other_score


def _measure_signs(couples, channels, matrices, corrections, reflection, defaults,
                   rest_pose, delta, tolerance, wanted=4):
    """
    For each channel, which sign makes these flag couples mirror each other.

    :param list couples: ``[(source_flag, target_flag)]``. A centre flag pairs
        with itself, which is the honest description of what mirroring one means.
    :param list channels: Channel names to measure.
    :param callable matrices: Takes a flag, returns its current world matrix.
    :param dict corrections: Couple index to the rest correction matrix.
    :param pm.dt.Matrix reflection: The reflection across the centre line.
    :param dict defaults: Plug name to rest value.
    :param callable rest_pose: Puts the whole rig back to its rest pose.
    :param float delta: How far to pose each channel.
    :param float tolerance: How close counts as equal.
    :param int wanted: Unused; every couple is measured, because a majority
        taken across flags with different axes is wrong for some of them.
    :return: ``(evidence, {flag_name: {channel: sign}})`` - the vote, and what
        each flag individually measured.
    :rtype: tuple
    """

    rest_pose()
    attached = {}
    for source, target in couples:
        for flag in (source, target):
            attached[flag.nodeName()] = _attached_probes(matrices(flag))

    evidence = {}
    per_flag = {}
    for channel in channels:
        votes, misses = {}, []
        for index, (source, target) in enumerate(couples):
            if not (source.hasAttr(channel) and target.hasAttr(channel)):
                continue
            source_plug = '{}.{}'.format(source, channel)
            target_plug = '{}.{}'.format(target, channel)
            try:
                if not (cmds.getAttr(source_plug, settable=True)
                        and cmds.getAttr(target_plug, settable=True)):
                    continue
            except Exception:
                continue

            source_probes = attached[source.nodeName()]
            target_probes = attached[target.nodeName()]

            rest_pose()
            rest_source = _probe_attached(source_probes, matrices(source))
            rest_target = _probe_attached(target_probes, matrices(target))

            cmds.setAttr(source_plug, defaults.get(source_plug, 0.0) + delta)
            moved_source = _probe_attached(source_probes, matrices(source))

            # Displacement from rest, mirrored - not absolute position through a
            # correction matrix. The correction absorbed whatever rigid
            # difference the two flags were built with, and that is exactly the
            # axis flip being measured: it made every channel look like it
            # crossed unchanged, and put a mirrored arm 41 units out.
            wanted_shift = _mirror_vectors(_subtract(moved_source, rest_source))

            scores = {}
            for sign in (1.0, -1.0):
                rest_pose()
                cmds.setAttr(target_plug, defaults.get(target_plug, 0.0) + delta * sign)
                got_shift = _subtract(_probe_attached(target_probes, matrices(target)),
                                      rest_target)
                scores[sign] = _worst_distance(wanted_shift, got_shift)

            sign, best_score, other_score = _verdict(scores, tolerance, delta)
            if sign is not None:
                votes[sign] = votes.get(sign, 0) + 1
                # Paired flags do not share one convention either. Six agreeing
                # votes from finger controls said translateY crosses unchanged,
                # and it does - on fingers. The arm IK control disagrees, because
                # its axes were built differently, and a shared answer put the
                # arm 41 units from where a mirror should have landed it. So each
                # flag keeps what it measured, and the relationship is symmetric:
                # whatever L needs to reach R, R needs to reach L.
                for flag in (source, target):
                    per_flag.setdefault(
                        flag.nodeName().split(':')[-1], {})[channel] = sign
            else:
                misses.append({'best': round(best_score, 4),
                               'other': round(other_score, 4)})

        if votes:
            winner = max(votes, key=votes.get)
            evidence[channel] = {'sign': winner, 'agreed': votes[winner],
                                 'measured': sum(votes.values()),
                                 'disagreed': sum(votes.values()) - votes[winner]}
        elif misses:
            evidence[channel] = {'sign': None, 'agreed': 0, 'measured': 0,
                                 'closest': min(m['best'] for m in misses),
                                 'alternative': min(m['other'] for m in misses)}
    return evidence, per_flag


def _measure_centre_signs(centre_flags, witness_pairs, channels, matrices, reflection,
                          defaults, rest_pose, delta, tolerance, wanted=4):
    """
    Which channels flip on a flag that sits on the centre line.

    Measured on the flag's own motion, using probes that are world-axis aligned
    at rest (see :func:`_attached_probes`). The origin and the +Y and +Z probes
    all lie in the mirror plane, so reflecting them is well defined and the
    comparison is a straight one: pose the flag by ``delta``, reflect where those
    points ended up, and ask which sign puts them there.

    Two earlier attempts got this wrong in instructive ways. Measuring a centre
    flag against itself through a rest-correction matrix collapsed to "does this
    flag equal itself" and answered *flips nothing* for every channel. Measuring
    it by its effect on the limbs worked for the chest but left the head, the
    neck, the pony tail and the root with **no answer at all** - they drive no
    paired flags, so nothing could testify for them, and every one of those fell
    back to "flips nothing" while being animated in real clips.

    ``witness_pairs`` is no longer used and is kept so callers do not have to
    change; it can go once nothing passes it.

    :param list centre_flags: Flags on the centre line.
    :param list witness_pairs: Unused.
    :param list channels: Channel names to measure.
    :param callable matrices: Takes a flag, returns its current world matrix.
    :param pm.dt.Matrix reflection: The reflection across the centre line.
    :param dict defaults: Plug name to rest value.
    :param callable rest_pose: Puts the whole rig back to its rest pose.
    :param float delta: How far to pose each channel.
    :param float tolerance: How close counts as equal.
    :param int wanted: Unused; every flag is measured.
    :return: ``(evidence, {flag_name: {channel: sign}})``.
    :rtype: tuple
    """

    evidence = {}
    per_flag = {}

    rest_pose()
    attached = {flag.nodeName(): _attached_probes(matrices(flag)) for flag in centre_flags}

    for channel in channels:
        votes, misses = {}, []
        for flag in centre_flags:
            if not flag.hasAttr(channel):
                continue
            plug = '{}.{}'.format(flag, channel)
            try:
                if not cmds.getAttr(plug, settable=True):
                    continue
            except Exception:
                continue

            probes = attached[flag.nodeName()]

            rest_pose()
            cmds.setAttr(plug, defaults.get(plug, 0.0) + delta)
            posed = _probe_attached(probes, matrices(flag))
            wanted_points = _probe_from_reflection(posed, reflection)

            scores = {}
            for sign in (1.0, -1.0):
                rest_pose()
                cmds.setAttr(plug, defaults.get(plug, 0.0) + delta * sign)
                scores[sign] = _worst_distance(
                    wanted_points, _probe_attached(probes, matrices(flag)))

            sign, best_score, other_score = _verdict(scores, tolerance, delta)
            if sign is not None:
                votes[sign] = votes.get(sign, 0) + 1
                per_flag.setdefault(flag.nodeName().split(':')[-1], {})[channel] = sign
            else:
                misses.append({'best': round(best_score, 4),
                               'other': round(other_score, 4)})

        if votes:
            winner = max(votes, key=votes.get)
            evidence[channel] = {'sign': winner, 'agreed': votes[winner],
                                 'measured': sum(votes.values()),
                                 'disagreed': sum(votes.values()) - votes[winner]}
        elif misses:
            evidence[channel] = {'sign': None, 'agreed': 0, 'measured': 0,
                                 'closest': min(m['best'] for m in misses),
                                 'alternative': min(m['other'] for m in misses)}
    rest_pose()
    return evidence, per_flag


def _probe_from_reflection(points, reflection):
    """
    :param list points: World points.
    :param pm.dt.Matrix reflection: The reflection across the centre line.
    :return: The points reflected.
    :rtype: list[tuple]
    """

    out = []
    for point in points:
        world = pm.dt.Point(point) * reflection
        out.append((world[0], world[1], world[2]))
    return out


@_safe
def calibrate_mirror(frag_rig=None, namespace=None, delta=12.0, tolerance=None,
                     channels=None, sample_pairs=6):
    """
    Measure which channels a mirror has to flip on this rig.

    Naming says which flag pairs with which, and that is certain. Which channels
    flip is a property of how the controls were oriented when the rig was built,
    and no amount of reading names will tell you - so this moves flags and watches
    where they end up rather than assuming.

    Two answers, not one
    --------------------
    **Paired** flags and **centre** flags need different answers, and running the
    measurement on pairs alone gives a confidently wrong one for the spine.

    On a rig built with mirrored control behaviour, a left flag and its right
    partner already have mirrored axes, so the same local values on both produce
    a mirrored pose and the convention flips *nothing*. A centre flag has no
    partner and no mirrored twin of its own axes, so mirroring it is a real
    geometric flip. Both are measured; both are reported.

    How it avoids assuming the answer
    ---------------------------------
    A first attempt compared the mirrored left flag's axes against the right
    flag's directly and rejected this rig as "not symmetric" - because reflecting
    a frame flips its handedness, so the two can never match outright. Each
    couple is therefore measured against its own rest relationship: with ``S``
    the reflection across the centre line, ``C = (M_rest_src · S)⁻¹ · M_rest_dst``
    is whatever constant difference the rig was built with, and the test is that
    ``M_moved_src · S · C ≈ M_moved_dst``. At rest that holds by construction, so
    the measurement is of the motion and nothing else.

    The rig is put back exactly as it was found.

    :param frag_rig: The rig to measure: a FRAGRig or a node name. None takes it
        from the selection.
    :param str namespace: The rig under this namespace.
    :param float delta: How far to pose each channel while measuring.
    :param float tolerance: How close two world points must be to count as equal.
        None scales it to the pose size, which is the only thing that makes sense
        across rigs built at different scales.
    :param list channels: Channels to measure. None does the six transform ones.
    :param int sample_pairs: How many *agreeing* measurements are enough to
        settle a channel. Every pair is offered; the measurement stops asking
        once it has this many answers.
    :return: Response with the measured conventions and the evidence for them.
    :rtype: dict
    """

    tolerance = float(delta) * 0.02 if tolerance is None else float(tolerance)
    rig = resolve_rig(frag_rig, namespace=namespace)
    channels = list(channels or ('translateX', 'translateY', 'translateZ',
                                 'rotateX', 'rotateY', 'rotateZ'))

    by_name = flag_map(rig)
    mapping = flag_mirror.build_mirror_map(list(by_name))
    sided = sorted(name for name, partner in mapping.items()
                   if partner != name and name < partner)
    centre = sorted(name for name, partner in mapping.items() if partner == name)
    if not sided:
        raise ValueError('This rig has no left/right flag pairs to measure.')

    restore, defaults = {}, {}
    for flag in rig.get_flags():
        for attribute in (flag.listAttr(keyable=True, settable=True, unlocked=True) or []):
            plug = str(attribute)
            try:
                restore[plug] = cmds.getAttr(plug)
                defaults[plug] = cmds.attributeQuery(
                    plug.split('.')[-1], node=plug.rsplit('.', 1)[0], listDefault=True)[0]
            except Exception:
                continue

    def rest_pose():
        for plug, value in defaults.items():
            try:
                cmds.setAttr(plug, value)
            except Exception:
                continue

    def matrices(flag):
        return flag.getMatrix(worldSpace=True)

    try:
        rest_pose()

        centre_x = sum((by_name[n].getTranslation(space='world')[0]
                        + by_name[mapping[n]].getTranslation(space='world')[0]) / 2.0
                       for n in sided) / float(len(sided))
        reflection = _reflection_matrix(centre_x)

        def prepare(couples):
            corrections, gap = {}, 0.0
            for index, (source, target) in enumerate(couples):
                rest_source, rest_target = matrices(source), matrices(target)
                corrections[index] = (rest_source * reflection).inverse() * rest_target
                # Origins only: the axes are allowed to disagree, the positions
                # are not, and the axes are the thing being measured.
                gap = max(gap, _worst_distance(
                    _probe_points(rest_source * reflection)[:1],
                    _probe_points(rest_target)[:1]))
            return corrections, gap

        paired_couples = [(by_name[n], by_name[mapping[n]]) for n in sided]
        paired_corrections, paired_gap = prepare(paired_couples)
        if paired_gap > max(tolerance * 20, 1.0):
            raise ValueError('This rig is not bilaterally symmetric at its rest pose - paired '
                             'flags sit up to {:.2f} apart when mirrored - so a mirror has no '
                             'well-defined meaning here. Set the convention by hand.'
                             .format(paired_gap))

        paired, paired_by_flag = _measure_signs(
            paired_couples, channels, matrices, paired_corrections,
            reflection, defaults, rest_pose, delta, tolerance, wanted=sample_pairs)

        # Only a flag that really sits on the centre line is something a mirror
        # has anything to say about; a "centre" flag parked off to one side is not.
        centre_flags, centre_names = [], []
        for name in centre:
            flag = by_name[name]
            if abs(flag.getTranslation(space='world')[0] - centre_x) > max(tolerance * 20, 1.0):
                continue
            centre_flags.append(flag)
            centre_names.append(name)

        # Watch the pairs furthest from the centre line: they swing the most for
        # a given twist of the chest, so the measurement has the most to go on.
        witnesses = [(by_name[n], by_name[mapping[n]]) for n in sided]
        centre_evidence, centre_by_flag = _measure_centre_signs(
            centre_flags, witnesses, channels, matrices, reflection, defaults,
            rest_pose, delta, tolerance, wanted=sample_pairs)
    finally:
        for plug, value in restore.items():
            try:
                cmds.setAttr(plug, value)
            except Exception:
                continue

    def summarise(evidence):
        flips = {c: info['sign'] for c, info in evidence.items() if info.get('sign') == -1.0}
        undecided = [c for c in channels if evidence.get(c, {}).get('sign') is None]
        split = [c for c, info in evidence.items() if info.get('disagreed')]
        return flips, undecided, split

    paired_flips, paired_undecided, paired_split = summarise(paired)
    centre_flips, centre_undecided, centre_split = summarise(centre_evidence)

    result = {
        'centre_by_flag': centre_by_flag,
        'paired_by_flag': paired_by_flag,
        'paired': paired_flips,
        'paired_name': flag_mirror.convention_name(paired_flips),
        'paired_evidence': paired,
        'centre': centre_flips,
        'centre_name': flag_mirror.convention_name(centre_flips),
        'centre_evidence': centre_evidence,
        'centre_flags_measured': centre_names,
        'undecided': sorted(set(paired_undecided) | set(centre_undecided)),
        'disagreed': sorted(set(paired_split) | set(centre_split)),
        'pairs': len(sided), 'centre_flags': len(centre), 'centre_x': centre_x,
    }
    message = ('Paired flags: {} ({}). Centre flags: {} ({}). Measured on {} pair(s) and {} '
               'centre flag(s).'.format(
                   flag_mirror.describe(paired_flips), result['paired_name'],
                   flag_mirror.describe(centre_flips), result['centre_name'],
                   len(paired_couples), len(centre_flags)))
    if result['undecided']:
        message += ' No clear answer for {}.'.format(', '.join(result['undecided']))
    if result['disagreed']:
        message += (' Centre flags disagreed on {}, so each keeps its own measured signs '
                    'rather than a shared answer.'.format(', '.join(result['disagreed'])))
    return result, message


# Calibration costs a few seconds of posing the rig, and the answer is a property
# of how the rig was built, so it is worked out once per asset and kept.
_MIRROR_CACHE = {}


def get_mirror_conventions(frag_rig, recalibrate=False):
    """
    The measured mirror conventions for a rig, calibrated on first use.

    :param frag_rig: The rig.
    :param bool recalibrate: Measure again even if the answer is already known.
    :return: ``{'paired': {...}, 'centre': {...}, 'source': str}``.
    :rtype: dict
    :raises ValueError: When the rig cannot be calibrated, because a guessed
        mirror is worse than no mirror - it produces a pose that looks almost
        right, which is the hardest kind of wrong to notice.
    """

    key = rig_asset_id(frag_rig) or str(frag_rig.pynode)
    if not recalibrate and key in _MIRROR_CACHE:
        return _MIRROR_CACHE[key]

    measured = calibrate_mirror(frag_rig=frag_rig)
    if not measured['ok']:
        raise ValueError('Cannot mirror on this rig: {}'.format(measured['message']))

    conventions = {'paired': measured['result']['paired'],
                   'centre': measured['result']['centre'],
                   'centre_by_flag': measured['result'].get('centre_by_flag') or {},
                   'paired_by_flag': measured['result'].get('paired_by_flag') or {},
                   'source': 'measured on {} pair(s)'.format(measured['result']['pairs'])}
    _MIRROR_CACHE[key] = conventions
    return conventions


def _mirror_destination(frag_rig, flag, conventions):
    """
    Where a flag's values should land when the clip is mirrored, and what happens
    to them on the way.

    :param frag_rig: The rig.
    :param flag: The flag the clip stored values for.
    :param dict conventions: As :func:`get_mirror_conventions` returns.
    :return: ``(destination_flag, channel_convention)``, or ``(None, None)`` when
        the flag has no partner on this rig.
    :rtype: tuple
    """

    partner = mirror_partner(frag_rig, flag)
    if partner is None:
        return None, None
    # A flag's own measured signs beat the majority answer, because the majority
    # is an average over flags whose axes point different ways.
    name = flag.nodeName().split(':')[-1]
    if partner.nodeName() != flag.nodeName():
        measured = (conventions.get('paired_by_flag') or {}).get(name)
        return partner, (measured if measured else conventions['paired'])

    measured = (conventions.get('centre_by_flag') or {}).get(name)
    return partner, (measured if measured else conventions['centre'])


def _attribute_default(plug):
    """
    :param str plug: A 'node.attribute' name.
    :return: The attribute's rest value, or 0.0 when it has none.
    :rtype: float
    """

    try:
        node, attribute = plug.rsplit('.', 1)
        return float(cmds.attributeQuery(attribute, node=node, listDefault=True)[0])
    except Exception:
        return 0.0


# --- Pose blending ------------------------------------------------------------------------------------------------

# The blend in progress. Module level because a slider drag is hundreds of
# updates against one pose, and re-reading the clip file for each of them would
# make the slider useless. Started once, updated cheaply, then finished.
_ACTIVE_BLEND = None


class PoseBlend(object):
    """
    A pose held part-way onto a rig.

    Holds, for every attribute the pose touches, where the rig was when the blend
    started and where the pose wants it. Everything in between is a straight
    interpolation, which is what makes dragging a slider feel like what it looks
    like.

    Plug names are strings and the writes go through ``cmds``: a drag is hundreds
    of updates across a thousand attributes, and PyNode round-trips at that rate
    are the difference between a slider and a slideshow.
    """

    def __init__(self, clip_name, targets):
        """
        :param str clip_name: The pose being blended, for messages.
        :param list targets: ``[(plug, base_value, target_value)]``.
        """

        self.clip_name = clip_name
        self.targets = targets
        self.percent = 0.0

    def __len__(self):
        return len(self.targets)

    def apply(self, percent):
        """
        Put the rig at this point between where it was and the pose.

        :param float percent: 0 is untouched, 100 is the pose. Values outside
            that range are allowed - overshooting a pose is a real thing to want.
        :return: How many attributes could not be set.
        :rtype: int
        """

        self.percent = float(percent)
        blend = self.percent / 100.0
        failed = 0
        for plug, base, target in self.targets:
            try:
                cmds.setAttr(plug, base + (target - base) * blend)
            except Exception:
                failed += 1
        return failed

    def key(self):
        """
        Set a key on everything the blend touched, at the current frame.

        :return: How many attributes were keyed.
        :rtype: int
        """

        plugs = [plug for plug, _base, _target in self.targets]
        if not plugs:
            return 0
        keyed = 0
        for plug in plugs:
            try:
                cmds.setKeyframe(plug)
                keyed += 1
            except Exception:
                logger.debug('Could not key %s', plug, exc_info=True)
        return keyed

    def cancel(self):
        """
        Put the rig back where it was before the blend started.
        """

        self.apply(0.0)


def _pose_targets(anim_comp, flags, frag_rig=None, mirror=False, conventions=None,
                  additive=False):
    """
    Read a stored pose off an imported component as plain values.

    The pose's value for an attribute is its first key's value. A pose has one
    key by construction; taking the first is also the sane reading of an
    animation clip somebody has chosen to blend as a pose.

    ``mirror`` sends each flag's values to its opposite number, flipping the
    channels the rig's measured convention says to flip. ``additive`` changes
    what the pose *means*: instead of a place to move to, it becomes an offset
    from the rest pose, laid on top of whatever the rig is already doing.

    :param anim_comp: The imported AnimatedCurvesComponent.
    :param list flags: Flags to read.
    :param frag_rig: The rig, needed to find mirror partners.
    :param bool mirror: Swap left and right.
    :param dict conventions: As :func:`get_mirror_conventions` returns.
    :param bool additive: Treat the pose as an offset from rest.
    :return: ``([(plug, base_value, target_value)], skipped_flag_names)``.
    :rtype: tuple
    """

    targets, skipped = [], []
    for flag in flags:
        pairs = anim_comp.get_stored_curve_pairs(flag)
        if not pairs:
            continue

        destination, convention = flag, None
        if mirror:
            destination, convention = _mirror_destination(frag_rig, flag, conventions)
            if destination is None:
                # A sided flag whose partner is missing. Putting its values back
                # on itself with the signs flipped is not a mirror, it is damage.
                skipped.append(flag.nodeName().split(':')[-1])
                continue

        attr_utils.unlock_and_show_attrs([attribute for attribute, _curve in pairs])
        for object_attribute, anim_curve in pairs:
            values = pm.keyframe(anim_curve, q=True, valueChange=True) or []
            if not values:
                continue
            channel = object_attribute.attrName(longName=True)
            if mirror and not destination.hasAttr(channel):
                continue
            plug = str(object_attribute) if not mirror else '{}.{}'.format(destination, channel)
            try:
                if not cmds.getAttr(plug, settable=True):
                    # Constrained or connected: nothing to blend into.
                    continue
                base = cmds.getAttr(plug)
            except Exception:
                logger.debug('Could not read %s for blending.', plug, exc_info=True)
                continue

            value = float(values[0])
            default = _attribute_default(plug)
            if mirror:
                value = flag_mirror.mirrored_value(channel, value, convention, default)
            if additive:
                # The pose stops being a destination and becomes a displacement.
                value = float(base) + (value - default)
            targets.append((plug, float(base), value))
    return targets, skipped


@_safe
def start_pose_blend(clip_id, frag_rig=None, namespace=None, selected_only=False,
                     mirror=False, additive=False):
    """
    Begin blending a pose onto a rig.

    Reads the pose once and remembers where the rig was, so the slider that
    follows costs nothing but attribute writes. Always finish with
    :func:`finish_pose_blend` - until then the rig is sitting part-way through
    something.

    :param str clip_id: Clip id or display name of a pose.
    :param frag_rig: The rig: a FRAGRig or a node name. None takes it from the
        selection.
    :param str namespace: The rig under this namespace.
    :param bool selected_only: Blend only the rig's selected flags.
    :param bool mirror: Put the pose on the other way round.
    :param bool additive: Lay the pose over what the rig is doing, as an offset
        from rest, instead of moving the rig to it.
    :return: Response with how many attributes are in play.
    :rtype: dict
    """

    global _ACTIVE_BLEND
    if _ACTIVE_BLEND is not None:
        _ACTIVE_BLEND.cancel()
        _ACTIVE_BLEND = None

    catalog = animlib_api.get_catalog()
    entry = catalog.get(clip_id) or catalog.get_by_name(clip_id)
    if entry is None:
        raise ValueError('No clip with id or name {!r} in the library.'.format(clip_id))

    curves_path = entry.artifact_path('curves', catalog.library_root)
    if not curves_path or not os.path.isfile(curves_path):
        raise ValueError('{} has no curve file on disk, so there is nothing to blend.'
                         .format(entry.name))

    rig = resolve_rig(frag_rig, namespace=namespace)
    flags = target_flags(rig, selected_only=selected_only)
    conventions = get_mirror_conventions(rig) if mirror else None

    anim_comp = frag.AnimatedCurvesComponent.import_animated_curve_data(curves_path)
    if anim_comp is None:
        raise ValueError('{} does not contain a stored curve node.'
                         .format(os.path.basename(curves_path)))
    try:
        targets, skipped = _pose_targets(anim_comp, flags, frag_rig=rig, mirror=mirror,
                                         conventions=conventions, additive=additive)
    finally:
        try:
            anim_comp.remove()
        except Exception:
            logger.debug('Could not tidy up the imported curve node.', exc_info=True)

    if not targets:
        raise ValueError('None of {}\'s attributes match this rig, so there is nothing to '
                         'blend. It may have been captured on another character.'
                         .format(entry.name))

    _ACTIVE_BLEND = PoseBlend(entry.name, targets)
    how = ' mirrored' if mirror else ''
    how += ' additively' if additive else ''
    message = 'Blending {}{} across {} attribute(s).'.format(entry.name, how, len(targets))
    if skipped:
        message += (' {} flag(s) have no opposite number on this rig and were left alone: {}.'
                    .format(len(skipped), ', '.join(sorted(skipped)[:5])))
    return ({'clip_id': entry.clip_id, 'name': entry.name, 'attributes': len(targets),
             'mirror': bool(mirror), 'additive': bool(additive), 'skipped': skipped},
            message)


@_safe
def update_pose_blend(percent):
    """
    Move the blend in progress.

    :param float percent: 0 leaves the rig as it was, 100 is the pose.
    :return: Response with the percentage applied.
    :rtype: dict
    """

    if _ACTIVE_BLEND is None:
        raise ValueError('No pose blend is in progress; call start_pose_blend first.')
    failed = _ACTIVE_BLEND.apply(percent)
    return ({'percent': float(percent), 'attributes': len(_ACTIVE_BLEND), 'failed': failed},
            '{} at {:.0f}%.'.format(_ACTIVE_BLEND.clip_name, float(percent)))


@_safe
def finish_pose_blend(percent=None, cancel=False, set_key=None):
    """
    End the blend in progress, keeping it or throwing it away.

    :param float percent: Where to leave the rig. None keeps the last value set.
    :param bool cancel: Put the rig back where it started instead.
    :param bool set_key: Key what was blended. None follows Maya's auto-key state,
        which is the answer an animator already configured.
    :return: Response describing what was left on the rig.
    :rtype: dict
    """

    global _ACTIVE_BLEND
    if _ACTIVE_BLEND is None:
        raise ValueError('No pose blend is in progress.')

    blend = _ACTIVE_BLEND
    _ACTIVE_BLEND = None

    if cancel:
        blend.cancel()
        return ({'name': blend.clip_name, 'percent': 0.0, 'keyed': 0},
                'Put the rig back; {} was not applied.'.format(blend.clip_name))

    if percent is not None:
        blend.apply(percent)

    if set_key is None:
        try:
            set_key = bool(pm.autoKeyframe(q=True, state=True))
        except Exception:
            set_key = False
    keyed = blend.key() if set_key else 0

    message = 'Applied {} at {:.0f}%.'.format(blend.clip_name, blend.percent)
    if keyed:
        message += ' Keyed {} attribute(s).'.format(keyed)
    return ({'name': blend.clip_name, 'percent': blend.percent, 'keyed': keyed}, message)


@_safe
def apply_pose(clip_id, percent=100.0, frag_rig=None, namespace=None, selected_only=False,
               set_key=None, mirror=False, additive=False):
    """
    Put a pose onto a rig in one go.

    A pose sets values at wherever the rig is now; it does not put keys back on
    the frame it happened to be captured on, which is what restoring its curves
    would do and is almost never what anyone wants from a pose.

    :param str clip_id: Clip id or display name of a pose.
    :param float percent: How much of the pose to apply. 100 is all of it.
    :param frag_rig: The rig: a FRAGRig or a node name. None takes it from the
        selection.
    :param str namespace: The rig under this namespace.
    :param bool selected_only: Pose only the rig's selected flags.
    :param bool set_key: Key the result. None follows Maya's auto-key state.
    :param bool mirror: Put the pose on the other way round.
    :param bool additive: Lay the pose over what the rig is doing.
    :return: Response describing what was posed.
    :rtype: dict
    """

    started = start_pose_blend(clip_id, frag_rig=frag_rig, namespace=namespace,
                               selected_only=selected_only, mirror=mirror,
                               additive=additive)
    if not started['ok']:
        raise ValueError(started['message'])
    finished = finish_pose_blend(percent=percent, set_key=set_key)
    if not finished['ok']:
        raise ValueError(finished['message'])

    result = dict(started['result'])
    result.update(finished['result'])
    return result, finished['message']


@_safe
def export_clip_fbx_file(frag_rig, fbx_path, start_frame=None, end_frame=None,
                         clip_name=None, start_at_zero=True, root_to_origin=True):
    """
    Bake the rig down to a joints-only skeleton and write an FBX.

    This is the portable half of a clip: no rig, no constraints, just joint
    transforms, so Blender, MotionBuilder and the engine can read it.

    It runs the Animation Exporter's pipeline rather than a private one of its
    own - bake, :func:`ae_utils.trim_export_hierarchy`, then
    :func:`ae_utils.export_baked_hierarchy`. That matters for three reasons a
    hand-rolled ``exportSelected`` gets wrong:

    * ``trim_export_hierarchy`` drops every joint not flagged ``animationExport``,
      so the FBX carries the joints the pipeline actually ships, not whatever
      the rig happens to have.
    * ``root_to_origin`` zeroes the root at the first frame, so the clip does not
      arrive in engine offset by wherever the shot happened to be.
    * ``start_at_zero`` shifts the clip to begin at frame 0.

    :param frag_rig: The rig to bake: a FRAGRig or a node name.
    :param str fbx_path: Absolute path to write.
    :param float start_frame: Bake range start. None uses the rig's range.
    :param float end_frame: Bake range end.
    :param str clip_name: Take name inside the FBX. Defaults to the file stem.
    :param bool start_at_zero: Shift the animation to begin at frame 0.
    :param bool root_to_origin: Move the root to the origin for the export.
    :return: Response with the path written.
    :rtype: dict
    """

    from mca.mya.tools.animationexporter import animationexporter_utils as ae_utils

    rig = resolve_rig(frag_rig)
    folder = os.path.dirname(fbx_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    if start_frame is None or end_frame is None:
        start_frame, end_frame = time_utils.get_keyframe_range_from_nodes(rig.get_flags())
    if start_frame is None or end_frame is None:
        raise ValueError('There are no keyframes on this rig, so there is no range to bake.')

    skeleton_root = rig_utils.bake_skeleton_from_rig(rig, start_frame, end_frame, False)
    if not skeleton_root:
        raise ValueError('Baking the rig to a skeleton produced nothing to export. Check the '
                         "asset's .skl file resolves.")

    try:
        export_hierarchy = ae_utils.trim_export_hierarchy(skeleton_root)
        if not export_hierarchy:
            raise ValueError('No joints on this skeleton are marked animationExport, so the FBX '
                             'would be empty.')
        ae_utils.export_baked_hierarchy(
            export_hierarchy,
            export_path=fbx_path,
            frame_range=[start_frame, end_frame],
            clip_name=clip_name or os.path.splitext(os.path.basename(fbx_path))[0],
            start_at_zero=start_at_zero,
            root_to_origin=root_to_origin)
    finally:
        if pm.objExists(skeleton_root):
            try:
                pm.delete(skeleton_root)
            except Exception:
                logger.debug('Could not clean up the temporary bake skeleton.', exc_info=True)

    if not os.path.isfile(fbx_path):
        raise ValueError('The FBX export reported success but wrote no file at {}.'.format(fbx_path))
    return {'path': fbx_path}, 'Exported {}.'.format(os.path.basename(fbx_path))


def _capture_panel():
    """
    A model panel to shoot from.

    :return: The panel name.
    :rtype: str
    :raises ValueError: When there is no viewport, as under mayabatch.
    """

    panel = cmds.getPanel(withFocus=True)
    if not panel or cmds.getPanel(typeOf=panel) != 'modelPanel':
        panels = cmds.getPanel(type='modelPanel') or []
        panel = panels[0] if panels else None
    if not panel:
        raise ValueError('No model panel to play blast from; previews need a viewport.')
    return panel


def preview_focus(frag_rig, flags=None):
    """
    What a thumbnail should actually be framed on: the character's meshes.

    Two wrong answers came before this one, and both produced a preview with the
    head cut off the top.

    **The flags** were the original. A flag set includes ``f_world`` and
    ``f_root``, which sit at the origin however high the character is, plus IK
    poles and weapon controls that reach well outside the silhouette. Their
    bounding box puts the character at the *top* of the box with the empty
    ground-to-feet span below, so any vertical crop takes the face first.

    **The joints** looked like the obvious correction and are worse: a joint has
    no renderable geometry, so ``exactWorldBoundingBox`` on one returns the
    degenerate ``±1e20``. ``viewFit`` on a selection of nothing-shaped nodes has
    nothing to fit and falls back to a default framing, which put the character
    at about a sixth of the frame.

    The meshes are what the picture is of, they have a real bounding box, and it
    is the silhouette rather than the rigging around it.

    :param frag_rig: The rig being captured.
    :param list flags: Flags to fall back to when the rig has no visible meshes.
    :return: Nodes to frame on.
    :rtype: list
    """

    try:
        root_joint = frag_rig.get_frag_parent().root_joint
        parents = pm.PyNode(root_joint).getAllParents()
        top = str(parents[-1]) if parents else str(root_joint)
        shapes = cmds.listRelatives(top, allDescendents=True, type='mesh',
                                    noIntermediate=True, fullPath=True) or []
        meshes = cmds.listRelatives(shapes, parent=True, fullPath=True) or [] if shapes else []
        if meshes:
            return sorted(set(meshes))
    except Exception:
        logger.debug('Could not find the meshes to frame the preview on.', exc_info=True)
    return list(flags or [])


@contextlib.contextmanager
def _framed_on(panel, focus_nodes):
    """
    Frame the camera on some nodes for the duration of a capture, then put the
    selection back.

    Without this the thumbnail is whatever the persp camera happened to be
    looking at, which in a freshly opened animation scene is usually nothing
    useful.

    :param str panel: The model panel to frame.
    :param list focus_nodes: Nodes to frame. None or empty leaves the view alone.
    """

    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        if focus_nodes:
            alive = [str(n) for n in focus_nodes if pm.objExists(n)]
            if alive:
                cmds.select(alive, replace=True)
                # 0.9 left nothing between the subject and the frame edge, and a
                # playblast is rendered at its own aspect rather than the
                # panel's - so whatever the panel showed right to the edge is
                # cropped on the way out. The headroom absorbs that.
                cmds.viewFit(cmds.modelPanel(panel, q=True, camera=True),
                             fitFactor=PREVIEW_FIT_FACTOR)
        cmds.select(clear=True)
        yield
    finally:
        try:
            if previous_selection:
                alive = [n for n in previous_selection if cmds.objExists(n)]
                cmds.select(alive, replace=True) if alive else cmds.select(clear=True)
            else:
                cmds.select(clear=True)
        except Exception:
            logger.debug('Could not restore the selection after the capture.', exc_info=True)


@_safe
def capture_preview_image(image_path, frame=None, focus_nodes=None, width=300, height=168):
    """
    Grab one viewport frame as the clip's browser thumbnail.

    Needs a viewport, so it does nothing under ``mayabatch``; the caller decides
    when to ask (see ``animlib_extract.previews_are_possible``).

    :param str image_path: Absolute path to write (a .jpg).
    :param float frame: Frame to capture. None uses the current frame.
    :param list focus_nodes: Nodes to frame. None leaves the view alone.
    :param int width: Image width.
    :param int height: Image height.
    :return: Response with the path written.
    :rtype: dict
    """

    folder = os.path.dirname(image_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    panel = _capture_panel()
    if frame is not None:
        pm.currentTime(frame)

    with _framed_on(panel, focus_nodes):
        current = pm.currentTime(q=True)
        produced = cmds.playblast(format='image', completeFilename=image_path,
                                  compression='jpg', widthHeight=(width, height),
                                  startTime=current, endTime=current,
                                  forceOverwrite=True, showOrnaments=False,
                                  offScreen=True, viewer=False, percent=100, quality=90)

    if not produced or not os.path.isfile(image_path):
        raise ValueError('Playblast wrote no image for {}.'.format(os.path.basename(image_path)))
    return ({'path': image_path},
            'Captured a preview for {}.'.format(os.path.splitext(os.path.basename(image_path))[0]))


def gifs_are_possible():
    """
    Can this Maya write a GIF?

    Two requirements, and they fail for different reasons worth telling apart:
    a viewport to play blast from, and Pillow to assemble the frames.

    :return: ``(possible, reason)`` - reason is '' when it is possible.
    :rtype: tuple
    """

    try:
        if pm.about(batch=True):
            return False, 'GIFs need a viewport, and this is a batch session.'
    except Exception:
        return False, 'Could not tell whether this is a batch session.'
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False, ('Pillow is not installed for this Maya, so the frames cannot be '
                       'assembled into a GIF.')
    return True, ''


@_safe
def capture_gif(gif_path, start_frame=None, end_frame=None, focus_nodes=None,
                width=320, height=180, max_frames=48):
    """
    Play the clip's range down to a looping GIF.

    A still frame is a poor preview for animation - a run cycle and a walk cycle
    look identical in one frame - so this is what makes the browser worth
    scrolling.

    Long clips are strided rather than truncated: taking every Nth frame keeps
    the whole action in view at a real-time rate, where a hard cut at frame 48
    would show the first second and a half of a ten-second clip. The playblast
    itself still renders every frame, because Maya has no stride, so the frames
    are kept small.

    :param str gif_path: Absolute path to write (a .gif).
    :param float start_frame: First frame. None uses the timeline start.
    :param float end_frame: Last frame. None uses the timeline end.
    :param list focus_nodes: Nodes to frame. None leaves the view alone.
    :param int width: Frame width.
    :param int height: Frame height.
    :param int max_frames: Most frames the GIF may hold.
    :return: Response with the path and frame count.
    :rtype: dict
    """

    possible, reason = gifs_are_possible()
    if not possible:
        raise ValueError(reason)
    from PIL import Image

    if start_frame is None or end_frame is None:
        start_frame, end_frame = time_utils.get_visible_range()
    start_frame, end_frame = float(start_frame), float(end_frame)
    if end_frame < start_frame:
        raise ValueError('The frame range ends ({:.0f}) before it starts ({:.0f}).'
                         .format(end_frame, start_frame))

    folder = os.path.dirname(gif_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    panel = _capture_panel()
    scratch = os.path.join(cmds.internalVar(userTmpDir=True),
                           'animlib_gif_{}'.format(os.getpid()))
    if os.path.isdir(scratch):
        shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)

    previous_time = pm.currentTime(q=True)
    try:
        with _framed_on(panel, focus_nodes):
            cmds.playblast(format='image', filename=os.path.join(scratch, 'frame'),
                           compression='png', widthHeight=(width, height),
                           startTime=start_frame, endTime=end_frame,
                           forceOverwrite=True, showOrnaments=False,
                           offScreen=True, viewer=False, percent=100, quality=100)

        frames = sorted(os.path.join(scratch, name) for name in os.listdir(scratch)
                        if name.lower().endswith('.png'))
        if not frames:
            raise ValueError('The playblast wrote no frames, so there is no GIF to build.')

        stride = max(1, int(math.ceil(len(frames) / float(max_frames))))
        chosen = frames[::stride]

        fps = scene_fps() or 30.0
        # Each kept frame stands in for `stride` source frames, so the GIF runs
        # at the speed the animation does rather than in slow motion.
        duration_ms = max(20, int(round(1000.0 * stride / fps)))

        images = [Image.open(path).convert('RGB') for path in chosen]
        try:
            first = images[0].convert('P', palette=Image.ADAPTIVE)
            rest = [image.convert('P', palette=Image.ADAPTIVE) for image in images[1:]]
            first.save(gif_path, save_all=True, append_images=rest, loop=0,
                       duration=duration_ms, optimize=True)
        finally:
            for image in images:
                try:
                    image.close()
                except Exception:
                    pass
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            pm.currentTime(previous_time)
        except Exception:
            logger.debug('Could not restore the current frame.', exc_info=True)

    if not os.path.isfile(gif_path):
        raise ValueError('No GIF was written at {}.'.format(gif_path))

    # The file usually holds fewer frames than were fed in: Pillow drops a frame
    # that is pixel-identical to the one before it and rolls its duration into
    # that one, so the clip still runs for the right length. Reporting the number
    # we sent would be a lie about the file, and a clip with very little movement
    # legitimately comes out with a handful of frames.
    written_frames = len(chosen)
    try:
        with Image.open(gif_path) as check:
            written_frames = getattr(check, 'n_frames', written_frames)
    except Exception:
        logger.debug('Could not re-read %s to count its frames.', gif_path, exc_info=True)

    return ({'path': gif_path, 'frames': written_frames, 'frames_captured': len(chosen),
             'stride': stride, 'duration_ms': duration_ms,
             'bytes': os.path.getsize(gif_path)},
            'Captured a {}-frame GIF for {}.'.format(
                written_frames, os.path.splitext(os.path.basename(gif_path))[0]))


@_safe
def rebuild_clip_gif(clip_id, frag_rig=None, namespace=None, width=320, height=180,
                     max_frames=48, thumbnail=True):
    """
    Re-record a clip's GIF by putting it on a rig and playing it down.

    The point of keeping the curve master is that everything else can be
    regenerated from it, and the GIF is the most regenerable thing there is. This
    is also how a library extracted headlessly - where there is no viewport to
    play blast from - gets its previews later.

    The rig is left with the clip on it, the same way :func:`rebuild_clip_fbx`
    leaves it: rebuilding is a scene-changing operation and pretending otherwise
    would mean another restore.

    :param str clip_id: Clip id or display name.
    :param frag_rig: The rig to play it on: a FRAGRig or a node name. None takes
        it from the selection.
    :param str namespace: The rig under this namespace.
    :param int width: Frame width.
    :param int height: Frame height.
    :param int max_frames: Most frames the GIF may hold.
    :param bool thumbnail: Re-take the still as well. On by default, because the
        browser shows the jpg and falls back to the GIF - so a rebuilt GIF beside
        a stale jpg is a fix you cannot see.
    :return: Response with the path written.
    :rtype: dict
    """

    possible, reason = gifs_are_possible()
    if not possible:
        raise ValueError(reason)

    catalog = animlib_api.get_catalog()
    entry = catalog.get(clip_id) or catalog.get_by_name(clip_id)
    if entry is None:
        raise ValueError('No clip with id or name {!r} in the library.'.format(clip_id))
    if (entry.get('clip_type') or 'animation') == 'pose':
        raise ValueError('{} is a pose. A one-frame GIF is a still, so poses keep their '
                         'thumbnail instead.'.format(entry.name))

    applied = apply_clip(entry.clip_id, frag_rig=frag_rig, namespace=namespace)
    if not applied['ok']:
        raise ValueError(applied['message'])

    rig = resolve_rig(frag_rig, namespace=namespace)
    _folder, paths = _clip_paths(entry.character, entry.category, entry.name,
                                 catalog.library_root)
    frame_range = entry.frame_range or [None, None]
    captured = capture_gif(paths['gif'][1],
                           start_frame=frame_range[0], end_frame=frame_range[1],
                           focus_nodes=preview_focus(
                               rig, keyed_flags(rig.get_flags()) or rig.get_flags()),
                           width=width, height=height, max_frames=max_frames)
    if not captured['ok']:
        raise ValueError(captured['message'])

    recorded = animlib_api.set_clip_file(entry.clip_id, 'gif', paths['gif'][1])
    if not recorded['ok']:
        raise ValueError(recorded['message'])

    still = ''
    if thumbnail:
        focus = preview_focus(rig, keyed_flags(rig.get_flags()) or rig.get_flags())
        middle = None
        if frame_range[0] is not None and frame_range[1] is not None:
            middle = (float(frame_range[0]) + float(frame_range[1])) / 2.0
        shot = capture_preview_image(paths['preview'][1], frame=middle, focus_nodes=focus)
        if shot['ok']:
            noted = animlib_api.set_clip_file(entry.clip_id, 'preview', paths['preview'][1])
            still = paths['preview'][0] if noted['ok'] else ''
        else:
            logger.warning('Could not re-take the thumbnail for %s: %s',
                           entry.name, shot['message'])

    return ({'clip_id': entry.clip_id, 'path': paths['gif'][0],
             'preview': still, 'frames': captured['result']['frames']},
            'Rebuilt the GIF for {} ({} frames).{}'.format(
                entry.name, captured['result']['frames'],
                ' Thumbnail re-taken.' if still else ''))


@_safe
def backfill_gifs(character=None, frag_rig=None, namespace=None, replace=False, limit=0):
    """
    Give every clip that has no GIF one.

    Meant for a library that was extracted headlessly, where there was no
    viewport to record from. It applies each clip to the rig in turn, so it needs
    a rig that the clips actually fit - run it per character.

    :param str character: Only do this character's clips. None does all of them,
        which only makes sense with one character's rig in the scene.
    :param frag_rig: The rig to play them on. None takes it from the selection.
    :param str namespace: The rig under this namespace.
    :param bool replace: Redo clips that already have a GIF.
    :param int limit: Stop after this many. 0 means all of them.
    :return: Response with per-clip results.
    :rtype: dict
    """

    possible, reason = gifs_are_possible()
    if not possible:
        raise ValueError(reason)

    catalog = animlib_api.get_catalog()
    wanted = []
    for entry in catalog.search(character=character, applicable_only=True):
        if (entry.get('clip_type') or 'animation') == 'pose':
            continue
        if entry.artifact('gif') and not replace:
            continue
        wanted.append(entry)
    if limit:
        wanted = wanted[:int(limit)]

    if not wanted:
        return ({'done': [], 'failed': []},
                'Every clip already has a GIF.' if not replace else 'No clips to do.')

    done, failed = [], []
    for entry in wanted:
        response = rebuild_clip_gif(entry.clip_id, frag_rig=frag_rig, namespace=namespace)
        if response['ok']:
            done.append(entry.name)
            logger.info('GIF for %s: %s', entry.name, response['message'])
        else:
            failed.append({'name': entry.name, 'message': response['message']})
            logger.warning('GIF for %s failed: %s', entry.name, response['message'])

    message = '{} GIF(s) written.'.format(len(done))
    if failed:
        message += ' {} failed: {}.'.format(len(failed),
                                            ', '.join(f['name'] for f in failed[:5]))
    return {'done': done, 'failed': failed}, message


@_safe
def rebuild_clip_fbx(clip_id, frag_rig=None):
    """
    Re-bake a clip's FBX from its curve master.

    Applies the clip to a rig, bakes, exports, and records the result - which is
    the whole point of the master/derived split: the FBX can always be rebuilt.

    :param str clip_id: Clip id or display name.
    :param frag_rig: The rig to bake onto: a FRAGRig or a node name. None takes
        it from the selection.
    :return: Response with the path written.
    :rtype: dict
    """

    catalog = animlib_api.get_catalog()
    entry = catalog.get(clip_id) or catalog.get_by_name(clip_id)
    if entry is None:
        raise ValueError('No clip with id or name {!r} in the library.'.format(clip_id))

    applied = apply_clip(entry.clip_id, frag_rig=frag_rig)
    if not applied['ok']:
        raise ValueError(applied['message'])

    rig = resolve_rig(frag_rig)
    _folder, paths = _clip_paths(entry.character, entry.category, entry.name,
                                 catalog.library_root)
    frame_range = entry.frame_range or [None, None]
    exported = export_clip_fbx_file(rig, paths['fbx'][1],
                                    start_frame=frame_range[0], end_frame=frame_range[1],
                                    clip_name=entry.name)
    if not exported['ok']:
        raise ValueError(exported['message'])

    recorded = animlib_api.set_clip_file(entry.clip_id, 'fbx', paths['fbx'][1])
    if not recorded['ok']:
        raise ValueError(recorded['message'])
    return ({'clip_id': entry.clip_id, 'path': paths['fbx'][1]},
            'Rebuilt the FBX for {}.'.format(entry.name))
