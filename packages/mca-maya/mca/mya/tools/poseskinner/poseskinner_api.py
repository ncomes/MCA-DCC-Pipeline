"""
Turn a deformation into joints and skin weights.

You have a face driven by forty blendshapes and a skeleton that has to reproduce
it in an engine. Or a cloth cache, or a muscle sim, or a lattice - anything that
moves a mesh and cannot be exported. Pose it, sample it, and this works out the
skinning that matches.

The workflow this is built around
---------------------------------
1. Get the deformation onto frames: one pose per frame, with the joints posed to
   match. :func:`poses_from_blendshape` will key a blendShape's targets out onto
   frames for you if that is where the poses live.
2. Pick the joints. They must already move - this solves weights, not motion,
   unless you ask for :func:`auto_joints`.
3. Run :func:`skin_from_poses`. It builds or fills a skinCluster and tells you how
   close it got, in scene units, per pose and per vertex.

What to know before running it
------------------------------
**Hold some poses back.** ``holdout`` keeps frames out of the fit and reports
their error separately. Error on the poses you fitted always looks good - add
joints and it goes to zero - and it says nothing about the poses you did not.
This is the number that tells you whether the skin will hold up on a pose the
solve never saw.

**Locality is worth turning on.** Restricting each vertex to its nearest joints
lands measurably closer to the truth - 31% on the test suite's noisy case - and
it rescues cases where there are more joints than the poses can tell apart. It is
on by default at four times ``max_influences``. Turn it off for a rig where a
joint deliberately drives something far away from it.

**More poses beat more joints.** Every pose adds three numbers per vertex to
solve against; every joint adds an unknown. A face with twelve poses and eighty
joints is under-determined however long it runs, and the symptom is a skin that
looks right on those twelve and falls apart in between.

:Requires: the mcaPoseSkinner plug-in
:Side effects: Creates or fills a skinCluster; moves the current time while
    sampling and puts it back.
"""

# python imports
import functools

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

PLUGIN_NAME = 'mcaPoseSkinner'
COMMAND_NAME = 'mcaPoseSkinner'

#: Influences per vertex. Eight is Maya's usual default and what most engines
#: take; four is the common budget on mobile and in older pipelines.
DEFAULT_MAX_INFLUENCES = 8

#: Candidate joints per vertex, as a multiple of ``max_influences``.
#:
#: Four, from measurement. Restricting a vertex to its nearest joints is the one
#: option in here that reliably improves accuracy: on noisy poses with twelve
#: joints the error against the truth went from 0.0251 to 0.0172, and on a case
#: with more joints than the poses could distinguish - 24 joints, 3 poses - it
#: went from 0.83 scene units to exact. The multiple matters less than having one
#: at all; tighter is slightly better and slower to go wrong.
DEFAULT_LOCALITY_MULTIPLE = 4

#: The layout version the command writes. Bumped by the command, checked here.
RESULT_LAYOUT = 3

#: The colour set the heat map lives in.
#:
#: Named, because the first version deleted EVERY colour set on the mesh when
#: clearing. On a test sphere there are none and it looked fine; on a production
#: head there are authored ones - AO masks, wind weights, blend masks - and it would
#: have eaten somebody's afternoon's work with no warning and no undo entry worth
#: having.
ERROR_COLOUR_SET = 'mcaPoseSkinnerError'

#: Tag put on a mesh this tool duplicated, naming the mesh it came from.
#:
#: **This is what makes the tool runnable twice.** Without it every run leaves another
#: `head_skinned`, `head_skinned1`, `head_skinned2` behind, each with its own skinCluster
#: and none of them obviously the current one - and the only safe way to clear them would
#: be to guess from the name, which would eventually delete a mesh somebody made by hand
#: and called the same thing. A tag naming the source means the tool deletes exactly its
#: own previous output and nothing else.
COPY_TAG = 'mcaPoseSkinnerCopyOf'

#: Tag put on every history node the heat map creates.
#:
#: Painting vertex colours on a DEFORMED mesh needs construction history: colours
#: written straight onto the output shape are discarded the next time the skinCluster
#: evaluates, which is why `polyColorPerVertex` inserts a node. So the nodes are not
#: waste while the map is shown - they are waste afterwards, and this tag is how
#: clearing finds exactly the ones we made and nothing else.
HEAT_MAP_TAG = 'mcaPoseSkinnerHeatMap'

#: Tag put on every node made to pin a joint to a mesh, naming the mesh it reads.
#:
#: Same reason as :data:`COPY_TAG`. Pinning again has to take off exactly the network this
#: tool put on last time, and a name is not safe to guess from: `head_pinMult` is a
#: perfectly ordinary thing for a rigger to have made by hand, and deleting it because it
#: matched a pattern would be unforgivable.
PIN_TAG = 'mcaPoseSkinnerPinOf'

#: Where a pinned joint's original ``offsetParentMatrix`` is kept, so unpinning restores it.
#:
#: A joint that already had an offset baked into that plug - which is common on a rig built
#: with matrix constraints - would otherwise come back from unpinning sitting somewhere
#: else, and the rigger would have no way to know what it used to be.
PIN_RESTORE = 'mcaPoseSkinnerPinRestore'

#: How far off the surface a pinned joint may sit before the report says so, in scene units.
#:
#: One unit, which on a head modelled in centimetres is a centimetre. Not a refusal: an eye
#: joint an inch inside the head is pinned to the inside of an eyelid and follows the wrong
#: thing, and a jaw joint under the chin is pinned exactly where it should be. Only the
#: rigger can tell those apart, so this measures it and names the worst.
PIN_SURFACE_WARNING = 1.0

#: How far a pin may land from the point it was made for before the report says so.
#:
#: A pin is placed by UV, and the UV is read at the closest point on the triangulated
#: mesh, so a curved quad puts the pin a fraction of a millimetre off its target: on a
#: 173-target head the worst was 0.0157 units, which is nothing. Overlapping or mirrored
#: UVs put it on the other side of the face, which is everything. A tenth of a unit
#: separates the two.
PIN_MISMATCH_WARNING = 0.1


def _response(ok, result=None, message=''):
    """
    :param bool ok: Whether the call did what was asked.
    :param result: Whatever the caller wanted back.
    :param str message: One line fit to show a person.
    :return: ``{'ok', 'result', 'message'}``.
    :rtype: dict
    """

    return {'ok': bool(ok), 'result': result, 'message': message}


def _safe(func):
    """
    Turn an exception into a response rather than a traceback in the script
    editor, so a caller can report it and carry on.

    :param func: The function to wrap.
    :return: The wrapped function.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result, message = func(*args, **kwargs)
            return _response(True, result, message)
        except Exception as exc:
            logger.warning('%s failed.', func.__name__, exc_info=True)
            return _response(False, None, '{}: {}'.format(type(exc).__name__, exc))

    return wrapper


def plugin_is_available():
    """
    Load the plug-in if it is not already up.

    :return: ``(available, reason)``.
    :rtype: tuple
    """

    from mca.mya.utils import maya_utils
    versioned = '{}_maya{}'.format(PLUGIN_NAME, maya_utils.get_version())
    for name in (versioned, PLUGIN_NAME):
        try:
            if cmds.pluginInfo(name, q=True, loaded=True):
                return True, ''
        except Exception:
            continue

    try:
        from mca.mya.plugins import loader
        if loader.load_pose_skinner_plugin():
            return True, ''
    except Exception as exc:
        return False, ('The {} plug-in could not be loaded: {}. It may not have been built '
                       'for this Maya version yet - check plugins/mcaPoseSkinner/plug-in/.'
                       .format(PLUGIN_NAME, exc))
    return False, ('The {} plug-in could not be loaded. Check that it has been built for '
                   'this Maya version under plugins/mcaPoseSkinner/plug-in/.'
                   .format(PLUGIN_NAME))


def _require_plugin():
    """
    :raises RuntimeError: When the plug-in is not there, saying so in a sentence
        rather than failing later on an unknown command.
    """

    available, reason = plugin_is_available()
    if not available:
        raise RuntimeError(reason)


def _mesh_shape(node):
    """
    The mesh shape under whatever was passed - a transform, a shape, or a name.

    :param node: Transform, shape or name.
    :return: The mesh shape.
    :rtype: pm.nt.Mesh
    :raises ValueError: When there is no mesh there.
    """

    found = pm.PyNode(node)
    if isinstance(found, pm.nt.Transform):
        shapes = found.getShapes(noIntermediate=True, type='mesh')
        if not shapes:
            raise ValueError('{} has no mesh shape under it.'.format(found))
        return shapes[0]
    if isinstance(found, pm.nt.Mesh):
        return found
    raise ValueError('{} is not a mesh.'.format(found))


def _one_undo(func):
    """
    Make everything the wrapped function does a single undo step.

    A run of this tool is several Maya operations - duplicate the mesh, carry the skinning
    over, add the influences, write the weights - and without a chunk each one is its own
    undo. Somebody presses Ctrl+Z expecting to be back where they started and instead
    peels the run apart one layer at a time, which on a 200-joint face is unusable.

    :param func: The function to wrap.
    :return: The wrapper.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        cmds.undoInfo(openChunk=True, chunkName=func.__name__)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)

    return wrapper


def _keep_selection(func):
    """
    Put the selection back after the wrapped function runs.

    Binding a skinCluster selects. Parenting selects. `pm.copySkinWeights` only works on
    the selection. So a tool that does any of those hands the user back a selection they
    did not make, and running it twice in a row means re-picking the mesh and the joints
    every time. Applied BELOW `_safe`, so the selection is restored even when the function
    raises and `_safe` turns that into a response.

    :param func: The function to wrap.
    :return: The wrapper.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _KeepSelection():
            return func(*args, **kwargs)

    return wrapper


class _KeepSelection(object):
    """
    Put the selection back the way it was found.

    `pm.copySkinWeights` and a few other Maya commands only work on the selection, so
    using them changes it. A tool that silently clears what somebody had selected cannot
    be run twice in a row without them re-picking everything, which is exactly the
    complaint this guards against.
    """

    def __enter__(self):
        self._was = cmds.ls(selection=True, long=True) or []
        return self

    def __exit__(self, kind, value, trace):
        try:
            alive = [each for each in self._was if cmds.objExists(each)]
            if alive:
                cmds.select(alive, replace=True)
            else:
                cmds.select(clear=True)
        except Exception:
            logger.debug('Could not put the selection back.', exc_info=True)
        return False


def _working_copy(shape, rest_frame, carry_skin):
    """
    The clean copy the skin goes on, with the existing skinning carried over.

    Both entry points need exactly this, at exactly the rest frame, so it lives in one
    place: duplicating and binding are two operations that must agree about which pose is
    the rest pose, and the bug that made this a function was them disagreeing.

    :param shape: The mesh to copy.
    :param float rest_frame: The neutral pose. None uses the current time.
    :param bool carry_skin: Transfer the source's skinning onto the copy when it has one.
    :return: ``(copy transform, the transfer response or None)``.
    :rtype: tuple
    """

    with _AtFrame(rest_frame):
        copy = clean_copy(shape, rest_frame)
        carried = None
        if carry_skin and existing_skin(shape) is not None:
            carried = transfer_skin(shape, copy)
            if not carried['ok']:
                raise ValueError('Could not carry the existing skinning onto the copy: {}'
                                 .format(carried['message']))
    return copy, carried


class _AtFrame(object):
    """
    Hold the time at one frame, and put it back afterwards.

    **Binding a skinCluster uses the joints where they are right now.** So a copy bound
    while the artist is parked on frame 60 gets bind matrices from frame 60, and every
    weight after that is measured against the wrong rest pose - a result that is wrong
    and looks plausible. `clean_copy` already went to the rest frame and put the time
    back before returning, which left the skin transfer that follows it binding at
    whatever frame happened to be current. This holds the frame across both.

    It matters more now that joints can be UV-pinned to the mesh: pinned joints move with
    time, so "wherever the timeline happens to be" is never the right answer.
    """

    def __init__(self, frame):
        self._frame = frame

    def __enter__(self):
        self._was = pm.currentTime(q=True)
        if self._frame is not None and self._frame != self._was:
            pm.currentTime(self._frame, edit=True)
        return self

    def __exit__(self, kind, value, trace):
        if self._frame is not None and self._frame != self._was:
            pm.currentTime(self._was, edit=True)
        return False


def _previous_copies(source):
    """
    Meshes this tool made from `source` on an earlier run.

    :param source: The mesh that was duplicated.
    :return: Transform names, tagged by us and naming this source.
    :rtype: list
    """

    wanted = str(_mesh_shape(source).getParent() or _mesh_shape(source)).split('|')[-1]
    found = []
    for node in (cmds.ls('*.' + COPY_TAG, objectsOnly=True, long=True) or []):
        try:
            if cmds.getAttr('{}.{}'.format(node, COPY_TAG)) == wanted:
                found.append(node)
        except Exception:
            logger.debug('Could not read %s on %s.', COPY_TAG, node, exc_info=True)
    return found


def _deforms_our_copy(cluster):
    """
    Is every mesh this skinCluster deforms one that this tool duplicated?

    Used to decide whether a joint from an earlier run is safe to remove: a joint whose
    only remaining use is our own previous copy is ours to clear, and one that something
    else has started skinning with is not.

    :param cluster: A skinCluster name.
    :return: True when it only deforms meshes we made.
    :rtype: bool
    """

    geometry = cmds.skinCluster(cluster, q=True, geometry=True) or []
    if not geometry:
        return False
    for shape in geometry:
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]
        if not cmds.attributeQuery(COPY_TAG, node=transform, exists=True):
            return False
    return True


def _history(shape):
    """
    Every node feeding this shape, DAG nodes included.

    :param shape: The mesh shape.
    :return: Node names.
    :rtype: set
    """

    return set(cmds.listHistory(str(shape)) or [])


def _tag_new_nodes(shape, before):
    """
    Mark whatever appeared in the shape's history as ours.

    Diffing the history rather than assuming which node type Maya will make: a
    colour-set operation on a deformed mesh can add a `createColorSet`, a
    `polyColorPerVertex`, a `deleteColorSet` or several, and which ones depends on
    the Maya version and on what was already there. Tagging what actually appeared
    means clearing removes exactly the right nodes without a list to keep up to date.

    :param shape: The mesh shape.
    :param set before: The history before the operation.
    :return: The nodes tagged.
    :rtype: list
    """

    tagged = []
    for node in sorted(_history(shape) - before):
        if not cmds.objExists(node):
            continue
        try:
            if not cmds.attributeQuery(HEAT_MAP_TAG, node=node, exists=True):
                cmds.addAttr(node, longName=HEAT_MAP_TAG, attributeType='bool',
                             hidden=True)
            cmds.setAttr('{}.{}'.format(node, HEAT_MAP_TAG), True)
            tagged.append(node)
        except Exception:
            logger.debug('Could not tag %s as heat-map history.', node, exc_info=True)
    return tagged


def _remove_heat_map(shape):
    """
    Delete the heat map's history nodes, and only those.

    :param shape: The mesh shape.
    :return: The nodes deleted.
    :rtype: list
    """

    doomed = [node for node in _history(shape)
              if cmds.objExists(node)
              and cmds.attributeQuery(HEAT_MAP_TAG, node=node, exists=True)]
    for node in doomed:
        try:
            cmds.delete(node)
        except Exception:
            logger.debug('Could not delete heat-map node %s.', node, exc_info=True)
    return sorted(doomed)


def _joint_names(joints):
    """
    :param joints: Joints, names or a single one.
    :return: Full path names, in the order given, with duplicates removed.
    :rtype: list(str)
    :raises ValueError: When one of them is not a transform.
    """

    if isinstance(joints, (str, pm.nt.Transform)):
        joints = [joints]
    names = []
    for each in joints:
        node = pm.PyNode(each)
        if not isinstance(node, pm.nt.Transform):
            raise ValueError('{} is not a transform, so it cannot be an influence.'
                             .format(node))
        name = node.longName()
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError('No joints given.')
    return names


def _parse_result(values, joints):
    """
    Read the command's flat double array into something with names on it.

    The command returns one array because a Maya command result cannot carry a
    structure - see the layout comment in mca_pose_skinner_command.cpp, which this
    is the other half of. The version number in front is checked rather than
    assumed: a mismatch here means the plug-in and this file came from different
    builds, and that is much better said out loud than parsed into plausible
    nonsense.

    :param values: What the command returned.
    :param list joints: The joint names, in the order they were given to it.
    :return: The parsed result.
    :rtype: dict
    """

    values = list(values or [])
    if len(values) < 16:
        raise ValueError('The plug-in returned {} values, which is not a result at all.'
                         .format(len(values)))
    version = int(round(values[0]))
    if version != RESULT_LAYOUT:
        raise ValueError('The plug-in returned layout version {} and this module reads {}. '
                         'The .mll and the Python are from different builds - rebuild the '
                         'plug-in.'.format(version, RESULT_LAYOUT))

    out = {'rms': values[1],
           'worst': values[2],
           'holdout_rms': values[3] if values[3] >= 0.0 else None,
           'holdout_worst': values[4] if values[4] >= 0.0 else None,
           'iterations': int(round(values[5]))}
    vertex_count = int(round(values[6]))
    pose_count = int(round(values[7]))
    joint_count = int(round(values[8]))
    degenerate_count = int(round(values[9]))
    unweighted_count = int(round(values[10]))
    has_vertex_error = bool(round(values[11]))
    has_bones = bool(round(values[12]))
    out['applied'] = bool(round(values[13]))
    out['cancelled'] = bool(round(values[14]))
    out['capped_vertices'] = int(round(values[15]))

    at = 16

    def take(count):
        nonlocal at
        chunk = values[at:at + count]
        at += count
        return chunk

    out['pose_error'] = list(take(pose_count))
    out['degenerate_joints'] = [joints[int(round(value))] for value in take(degenerate_count)
                               if 0 <= int(round(value)) < len(joints)]
    out['unweighted_vertices'] = [int(round(value)) for value in take(unweighted_count)]

    weights = {}
    order = []
    for _ in range(vertex_count):
        vertex = int(round(values[at]))
        count = int(round(values[at + 1]))
        at += 2
        entry = {}
        for _ in range(count):
            index = int(round(values[at]))
            entry[joints[index]] = values[at + 1]
            at += 2
        weights[vertex] = entry
        order.append(vertex)
    out['weights'] = weights
    out['vertices'] = order

    out['vertex_error'] = {}
    if has_vertex_error:
        for vertex in order:
            out['vertex_error'][vertex] = values[at]
            at += 1

    out['bones'] = None
    if has_bones:
        poses = []
        for _ in range(pose_count):
            per_joint = []
            for _ in range(joint_count):
                per_joint.append(list(values[at:at + 16]))
                at += 16
            poses.append(per_joint)
        out['bones'] = poses

    return out


def _frame_list(frames):
    """
    :param frames: A list of frames, or a ``(start, end)`` tuple, or a range.
    :return: Frames as floats, in order, without duplicates.
    :rtype: list(float)
    """

    if frames is None:
        raise ValueError('No frames given. Each frame is one pose to fit.')
    values = [float(frame) for frame in frames]
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    if not seen:
        raise ValueError('No frames given. Each frame is one pose to fit.')
    return seen


@_safe
def solve(mesh, joints, frames, rest_frame=None, max_influences=DEFAULT_MAX_INFLUENCES,
          locality=None, geodesic=True, smoothing=0.0, smoothing_rounds=3, affinity=1.0,
          prune_per_step=True, weight_floor=1e-5, holdout=None, vertices=None,
          candidates_from=None, iterations=1, solve_bones=False, rigid_bones=True,
          update_bind_pose=False, improvement_break=0.01, threads=0, apply_to=None,
          per_vertex_error=True, return_bones=False, donors=None):
    """
    Solve the weights and hand them back without touching the scene.

    This is the thin wrapper around the plug-in. :func:`skin_from_poses` is the one
    to call for the whole job; this one is for when you want the numbers.

    :param mesh: The mesh that deforms.
    :param joints: The influences. They must already be posed on each frame.
    :param frames: One frame per pose.
    :param float rest_frame: The neutral pose the weights are relative to. None
        uses the current time, which is the frame you are looking at.
    :param int max_influences: Most joints one vertex may end up with.
    :param int locality: Candidate joints per vertex, nearest first. None uses
        :data:`DEFAULT_LOCALITY_MULTIPLE` times ``max_influences``; 0 turns it off
        and lets every vertex consider every joint.
    :param bool geodesic: Measure "nearest" across the surface rather than through
        the air. On by default: the upper and lower lip are a millimetre apart
        through the air and on opposite sides of a hole, and eyeballs, teeth and a
        tongue modelled as their own shells cannot be reached from a face joint at
        all, so they stop being weighted to the jaw. Turn it off when a joint is
        MEANT to carry a separate piece of geometry.
    :param float smoothing: Pull each vertex's weights toward its neighbours'. See
        :func:`skin_from_poses` for what this does and does not buy.
    :param int smoothing_rounds: Re-solves with the neighbourhood prior.
    :param float affinity: How hard the weights are pushed to sum to one.
    :param bool prune_per_step: Drop one influence at a time and re-solve, rather
        than ranking once and re-solving once.
    :param float weight_floor: Weights below this are dropped.
    :param holdout: Frames kept OUT of the fit and reported on separately. Pass
        frames, not indices - they are matched against ``frames``.
    :param vertices: Vertex ids to solve. None does the whole mesh.
    :param candidates_from: An existing skinCluster whose per-vertex influence sets
        restrict the candidates, for improving a skin without moving influences
        around.
    :param int iterations: Weight/bone alternations. 1 solves weights only.
    :param bool solve_bones: Also solve the joint transforms. Needs iterations > 1.
    :param bool rigid_bones: Bones rotate and translate only, rather than scaling
        and shearing.
    :param bool update_bind_pose: Move each joint's bind position to the middle of
        what it weights, between iterations.
    :param float improvement_break: Stop when an iteration improves by less than
        this fraction. Negative runs them all.
    :param int threads: 0 lets the solver choose, which asks the hardware and
        then caps at 8. The cap guards an open race that has only ever faulted
        at 24 threads and above, and costs about 0.7s on a whole face. Passing
        a number uses exactly that number, cap or no cap.
    :param apply_to: A skinCluster to write the weights into, in one undoable step.
    :param bool per_vertex_error: Return the per-vertex error, which is what
        :func:`show_error` draws.
    :param bool return_bones: Return the solved joint transforms.
    :return: Response whose result is the parsed solve - see :func:`_parse_result`.
    :rtype: dict
    """

    _require_plugin()

    shape = _mesh_shape(mesh)
    names = _joint_names(joints)
    frames = _frame_list(frames)

    if max_influences < 1:
        raise ValueError('max_influences has to be at least 1.')
    if locality is None:
        locality = DEFAULT_LOCALITY_MULTIPLE * int(max_influences)
    if locality and locality >= len(names):
        # Restricting to more joints than exist is the same as not restricting,
        # and saying 0 makes the result's provenance clearer.
        locality = 0

    holdout_indices = []
    for frame in (holdout or []):
        frame = float(frame)
        if frame not in frames:
            raise ValueError('Held-out frame {} is not one of the frames being fitted.'
                             .format(frame))
        holdout_indices.append(frames.index(frame))
    if holdout_indices and len(holdout_indices) >= len(frames):
        raise ValueError('Every frame was held out, so there is nothing left to fit.')

    # Keyword arguments, and a LIST for each flag the command declared multi-use.
    # Passing the flags positionally - `cmds.mcaPoseSkinner('-mesh', name, ...)` -
    # looks like the MEL call and fails with "Object -mesh is invalid", because the
    # Python wrapper hands leading arguments to the object parser before it ever
    # looks for flags.
    flags = {'mesh': shape.longName(),
             'joint': list(names),
             'frame': [float(frame) for frame in frames],
             'maxInfluences': int(max_influences),
             'locality': int(locality),
             'geodesic': bool(geodesic),
             'smoothing': float(smoothing),
             'smoothingRounds': int(smoothing_rounds),
             'affinity': float(affinity),
             'prunePerStep': bool(prune_per_step),
             'weightFloor': float(weight_floor),
             'maxIterations': int(iterations),
             'solveBones': bool(solve_bones),
             'rigidBones': bool(rigid_bones),
             'updateBindPose': bool(update_bind_pose),
             'improvementBreak': float(improvement_break),
             'threads': int(threads),
             'perVertexError': bool(per_vertex_error),
             'returnBones': bool(return_bones)}
    if rest_frame is not None:
        flags['restFrame'] = float(rest_frame)
    if holdout_indices:
        flags['holdout'] = [int(index) for index in holdout_indices]
    if vertices:
        flags['vertex'] = [int(vertex) for vertex in vertices]
    if apply_to is not None:
        flags['applyTo'] = str(apply_to)
    if candidates_from is not None:
        flags['candidatesFrom'] = str(candidates_from)
    if donors:
        # Additive mode. The command infers it from the presence of donors rather than
        # taking a separate switch, so the two can never disagree.
        flags['donor'] = [str(each) for each in
                          ([donors] if isinstance(donors, str) else donors)]

    values = cmds.mcaPoseSkinner(**flags)
    parsed = _parse_result(values, names)
    parsed['joints'] = names
    parsed['frames'] = frames
    parsed['mesh'] = shape.longName()

    message = ('Fitted {} pose(s) on {} vertices with {} joint(s): rms {:.4f}, worst {:.4f} '
               'scene units.'.format(len(frames) - len(holdout_indices),
                                     len(parsed['vertices']), len(names), parsed['rms'],
                                     parsed['worst']))
    if parsed['holdout_rms'] is not None:
        message += ('  Held out {} pose(s): rms {:.4f}, worst {:.4f}.'
                    .format(len(holdout_indices), parsed['holdout_rms'],
                            parsed['holdout_worst']))
    if parsed.get('cancelled'):
        message += ('  Stopped early on escape, after {} iteration(s) - these weights are '
                    'complete as of that iteration.'.format(parsed['iterations']))
    if parsed['degenerate_joints']:
        message += ('  {} joint(s) had too few vertices to fit a transform: {}.'
                    .format(len(parsed['degenerate_joints']),
                            ', '.join(str(each).split('|')[-1]
                                      for each in parsed['degenerate_joints'][:6])))
    return parsed, message


def existing_skin(mesh):
    """
    :param mesh: The mesh to look under.
    :return: The skinCluster on it, or None.
    :rtype: pm.nt.SkinCluster or None
    """

    shape = _mesh_shape(mesh)
    found = [node for node in pm.listHistory(shape, type='skinCluster')]
    return found[0] if found else None


def other_deformers(shape):
    """
    Deformers on this mesh that are not a skinCluster.

    :param shape: The mesh shape.
    :return: The deformer nodes.
    :rtype: list
    """

    found = []
    for node in pm.listHistory(_mesh_shape(shape)):
        if isinstance(node, pm.nt.SkinCluster) or isinstance(node, pm.nt.Tweak):
            continue
        if isinstance(node, pm.nt.GeometryFilter):
            found.append(node)
    return found


def clean_copy(shape, rest_frame=None, name=None):
    """
    A history-free copy of a mesh at its rest pose, with its transform baked in.

    This is where the solved skin goes when the mesh being sampled still has the
    deformers that made the poses. Skinning the original instead puts the skin ON
    TOP of the blendShape that the skin was fitted to reproduce, so the result is
    the deformation applied twice - which looks like the solve having gone wrong.

    The transform is frozen deliberately: object space and world space then agree,
    which is what makes :func:`add_correctives` able to convert a world-space
    residual back into a blendShape target.

    :param shape: The mesh to copy.
    :param float rest_frame: The frame to copy it on. None uses the current time.
    :param str name: Name for the copy. None appends "_skinned".
    :return: The new mesh's transform.
    :rtype: pm.nt.Transform
    """

    source = _mesh_shape(shape)
    parent = source.getParent() or source
    stem = str(parent).split('|')[-1]

    # Replace the copy from last time rather than adding another one beside it. Only ever
    # a mesh this tool tagged as a copy of THIS source - a mesh somebody made by hand and
    # happened to call `head_skinned` carries no tag and is left alone.
    replaced = []
    for old_copy in _previous_copies(parent):
        try:
            cmds.delete(old_copy)
            replaced.append(old_copy.split('|')[-1])
        except Exception:
            logger.debug('Could not remove the previous copy %s.', old_copy, exc_info=True)
    if replaced:
        logger.info('Replaced %d copy(ies) from an earlier run: %s.',
                    len(replaced), ', '.join(replaced))

    was_at = pm.currentTime(q=True)
    if rest_frame is not None and rest_frame != was_at:
        pm.currentTime(rest_frame, edit=True)
    try:
        made = cmds.duplicate(str(parent), returnRootsOnly=True,
                              name=name or '{}_skinned'.format(stem))[0]
        cmds.delete(made, constructionHistory=True)
        # Any intermediate shapes the duplicate brought along would confuse every
        # later lookup of "the mesh under this transform".
        for extra in (cmds.listRelatives(made, shapes=True, fullPath=True) or []):
            if cmds.getAttr(extra + '.intermediateObject'):
                cmds.delete(extra)

        # And anything PARENTED under the mesh comes along too, which is worse than
        # untidy: a joint or a locator under the geometry gets a duplicate with the same
        # short name, and from then on that name means two different nodes. Found by a
        # test whose helper joint happened to be a child of the mesh - a production mesh
        # with a helper under it would have done the same thing quietly.
        for child in (cmds.listRelatives(made, children=True, fullPath=True) or []):
            if cmds.nodeType(child) == 'mesh':
                continue
            try:
                cmds.delete(child)
            except Exception:
                logger.debug('Could not remove %s from the copy.', child, exc_info=True)
        # Unlock and disconnect the copy's own transform channels first.
        #
        # A production mesh almost always has its transform locked - it is how a
        # rigger stops an animator moving the geometry - and `makeIdentity` refuses
        # outright on a locked channel: "Freeze Transform was not applied because
        # <mesh>.translateX is locked". This is OUR copy, made a moment ago, so
        # unlocking it takes nothing away from anyone.
        for channel in ('translate', 'rotate', 'scale'):
            for axis in ('X', 'Y', 'Z'):
                plug = '{}.{}{}'.format(made, channel, axis)
                try:
                    cmds.setAttr(plug, lock=False)
                except Exception:
                    logger.debug('Could not unlock %s.', plug, exc_info=True)
                for source in (cmds.listConnections(plug, source=True, destination=False,
                                                    plugs=True) or []):
                    try:
                        cmds.disconnectAttr(source, plug)
                    except Exception:
                        logger.debug('Could not disconnect %s.', plug, exc_info=True)
        try:
            cmds.makeIdentity(made, apply=True, translate=True, rotate=True, scale=True,
                              normal=0, preserveNormals=True)
        except Exception:
            logger.warning('Could not freeze %s. The skin will still be correct; building '
                           'correctives on it will refuse until its transform is identity.',
                           made, exc_info=True)
        # Tagged with where it came from, so the next run can find and replace exactly
        # this and nothing else.
        if not cmds.attributeQuery(COPY_TAG, node=made, exists=True):
            cmds.addAttr(made, longName=COPY_TAG, dataType='string', hidden=True)
        cmds.setAttr('{}.{}'.format(made, COPY_TAG), stem, type='string')
    finally:
        if rest_frame is not None and rest_frame != was_at:
            pm.currentTime(was_at, edit=True)
    return pm.PyNode(made)


def _ensure_skin(shape, names, max_influences, rest_frame):
    """
    The skinCluster to write into: the one that is there, or a new one bound at the
    rest pose.

    **Bound at the REST frame, not wherever the artist is standing.** A
    skinCluster records the joints' matrices at the moment it is made, and every
    weight is relative to that. Bind it on frame 30 of a walk and the whole solve
    is measured from one pose and applied from another - which looks like the
    weights being wrong rather than the bind being wrong.

    :param shape: The mesh shape.
    :param list names: Influences.
    :param int max_influences: Passed to the skinCluster.
    :param float rest_frame: The frame to bind on.
    :return: ``(skinCluster, created)``.
    :rtype: tuple
    """

    found = existing_skin(shape)
    if found is not None:
        missing = [name for name in names
                   if pm.PyNode(name) not in list(found.getInfluence())]
        if missing:
            for name in missing:
                # Added at weight 0, so adding an influence cannot move the mesh.
                cmds.skinCluster(str(found), edit=True, addInfluence=name, weight=0.0,
                                 lockWeights=False)
        return found, False

    was_at = pm.currentTime(q=True)
    if rest_frame is not None and rest_frame != was_at:
        pm.currentTime(rest_frame, edit=True)
    try:
        made = cmds.skinCluster(names, str(shape), toSelectedBones=True,
                                maximumInfluences=int(max_influences),
                                obeyMaxInfluences=False, normalizeWeights=1,
                                removeUnusedInfluence=False)[0]
    finally:
        if rest_frame is not None and rest_frame != was_at:
            pm.currentTime(was_at, edit=True)
    return pm.PyNode(made), True


@_safe
@_one_undo
@_keep_selection
def skin_from_poses(mesh, joints, frames, rest_frame=None,
                    max_influences=DEFAULT_MAX_INFLUENCES, holdout=None, show=False,
                    duplicate=None, locality=None, geodesic=True, smoothing=0.0,
                    candidates_from=None, transfer_skin_first=True, **kwargs):
    """
    Solve the weights and put them on the mesh, in one undoable step.

    What it does, in order: sample the mesh and the joints on every frame, solve,
    make a skinCluster if there is not one already (bound at the rest frame), write
    the weights into it, and report how close it got.

    Reading the report
    ------------------
    ``rms`` and ``worst`` are in SCENE UNITS, over the poses that were fitted. On a
    177-unit character, an rms of 0.2 is invisible and a worst of 2.0 is a dent
    somebody will notice - which is why both are reported rather than one number
    scaled into a percentage.

    ``holdout_rms`` is the one to trust. Error on the poses that were fitted falls
    as you add joints whether or not the skin is any good; error on poses that were
    held back does not.

    ``show=True`` paints the per-vertex error onto the mesh as vertex colours. A
    single number cannot tell you that everything is fine except the armpits.

    :param mesh: The mesh that deforms.
    :param joints: The influences, already posed on every frame.
    :param frames: One frame per pose.
    :param float rest_frame: The neutral pose. None uses the current time.
    :param int max_influences: Most joints one vertex may end up with.
    :param holdout: Frames to keep out of the fit and measure separately.
    :param bool show: Paint the per-vertex error on the mesh afterwards.
    :param duplicate: Put the skin on a clean copy rather than on the mesh itself.
        None decides: a mesh that still carries the deformers which made the poses
        gets a copy, because skinning it in place would apply the deformation twice.
        The message says which happened.
    :param int locality: Candidate joints per vertex, nearest first. None uses four
        times ``max_influences``, which measured 31% closer to the truth than no
        restriction at all. 0 turns it off.
    :param bool geodesic: Measure that nearness across the surface rather than
        through the air. See :func:`solve`.
    :param float smoothing: Pull each vertex's weights toward its neighbours'. This
        buys a weight map that is easier to edit and LODs better; measured, it costs
        a little accuracy rather than adding any. 0 is off.
    :param candidates_from: An existing skinCluster whose per-vertex influence sets
        restrict which joints may be used, for improving a skin without moving
        influences around.
    :param bool transfer_skin_first: When a copy is made and the original was already
        skinned, carry that skinning onto the copy before solving. On by default: a mesh
        that is already bound has its skin as part of the answer rather than as something
        to discard, and it leaves the shapes on one mesh and the skin on another.
    :param kwargs: Passed to :func:`solve`.
    :return: Response whose result carries the solve, the skinCluster and whether
        it was created.
    :rtype: dict
    """

    _require_plugin()
    shape = _mesh_shape(mesh)
    names = _joint_names(joints)
    frames = _frame_list(frames)
    if rest_frame is None:
        rest_frame = pm.currentTime(q=True)

    if duplicate is None:
        duplicate = bool(other_deformers(shape))
    target = shape
    copy = None
    carried = None
    if duplicate:
        copy, carried = _working_copy(shape, rest_frame, carry_skin=transfer_skin_first)
        target = _mesh_shape(copy)
        # The copy carries the original's skinning when it had any - see `_working_copy`.
        # One mesh holds the shapes, the other holds the skin, and a mesh that was already
        # bound has that skin as part of the answer rather than as something to discard.

    cluster, created = _ensure_skin(target, names, max_influences, rest_frame)

    response = solve(shape, names, frames, rest_frame=rest_frame,
                     max_influences=max_influences, holdout=holdout,
                     apply_to=str(cluster), per_vertex_error=True, locality=locality,
                     geodesic=geodesic, smoothing=smoothing,
                     candidates_from=candidates_from, **kwargs)
    if not response['ok']:
        raise RuntimeError(response['message'])
    parsed = response['result']

    if not parsed['applied']:
        raise RuntimeError('The solve ran but the weights were not written into {}.'
                           .format(cluster))

    # Maya keeps its own idea of the influence limit, and it prunes on ITS terms -
    # dropping the smallest weights and renormalising - which would quietly undo
    # the choice the solve just made. Set it to what was solved for, so the two
    # agree.
    try:
        cluster.maxInfluences.set(int(max_influences))
        cluster.maintainMaxInfluences.set(True)
    except Exception:
        logger.debug('Could not set the influence limit on %s.', cluster, exc_info=True)

    painted = 0
    if show:
        shown = show_error(target, parsed['vertex_error'])
        painted = shown['result'] if shown['ok'] else 0

    result = {'solve': parsed, 'skin_cluster': str(cluster), 'created': created,
              'mesh': shape.longName(), 'skinned_mesh': target.longName(),
              'copy': str(copy) if copy is not None else None,
              'skin_carried_over': carried['result'] if carried and carried['ok'] else None}
    message = response['message']
    if copy is not None:
        message += ('  The skin went on a clean copy, {}, because {} still has the '
                    'deformer(s) that made the poses on it.'
                    .format(str(copy).split('|')[-1],
                            str(shape.getParent() or shape).split('|')[-1]))
    if carried and carried['ok']:
        message += ('  The existing skinning was carried onto the copy first ({} '
                    'influence(s), weights matching to {:.1e}).'.format(
                        carried['result']['influences'],
                        carried['result']['worst_difference']))
    if created:
        message += '  Bound a new skinCluster at frame {:g}.'.format(rest_frame)
    if parsed['unweighted_vertices']:
        message += ('  {} vertex(es) could not be fitted by any allowed joint and were '
                    'given their nearest one.'.format(len(parsed['unweighted_vertices'])))
    if show and painted:
        message += '  Error painted onto the mesh as vertex colours.'
    return result, message


@_safe
def show_error(mesh, vertex_error, limit=None, bands=24):
    """
    Paint per-vertex error onto the mesh as vertex colours.

    Black is a perfect fit, then blue, green, yellow, red at the limit. The point
    is not the colours, it is that one number for the whole mesh cannot tell you
    the fit is fine everywhere except the armpits - and the armpits are where
    somebody will look.

    :param mesh: The mesh to paint.
    :param dict vertex_error: ``{vertex id: error}``, as a solve returns.
    :param float limit: The error that reads as full red. None uses the worst
        there is, which makes the picture self-scaling - so read the number, not
        the colour, when comparing two runs.
    :param int bands: Colour steps. Vertices are painted a band at a time because
        one call per vertex on a dense mesh takes longer than the solve did.
    :return: Response whose result is how many vertices were painted.
    :rtype: dict
    """

    shape = _mesh_shape(mesh)
    if not vertex_error:
        raise ValueError('No per-vertex error to paint. Solve with per_vertex_error=True.')

    worst = float(limit) if limit else max(vertex_error.values())
    if worst <= 0.0:
        worst = 1.0

    def colour(fraction):
        """Black to blue to green to yellow to red."""
        stops = ((0.0, (0.0, 0.0, 0.0)), (0.25, (0.0, 0.1, 0.8)), (0.5, (0.0, 0.7, 0.2)),
                 (0.75, (0.9, 0.8, 0.0)), (1.0, (1.0, 0.0, 0.0)))
        for index in range(len(stops) - 1):
            low, lowColour = stops[index]
            high, highColour = stops[index + 1]
            if fraction <= high:
                span = (fraction - low) / (high - low) if high > low else 0.0
                return tuple(lowColour[axis] + span * (highColour[axis] - lowColour[axis])
                             for axis in range(3))
        return stops[-1][1]

    buckets = {}
    for vertex, error in vertex_error.items():
        band = min(int(bands * (error / worst)), bands - 1)
        buckets.setdefault(band, []).append(vertex)

    name = shape.longName()

    # Painting twice used to leave two sets of history nodes, three times three, and
    # nothing ever removed them. Clear ours first, every time.
    _remove_heat_map(shape)
    before = _history(shape)

    existing = cmds.polyColorSet(name, q=True, allColorSets=True) or []
    if ERROR_COLOUR_SET not in existing:
        cmds.polyColorSet(name, create=True, clamped=False, representation='RGB',
                          colorSet=ERROR_COLOUR_SET)
    cmds.polyColorSet(name, currentColorSet=True, colorSet=ERROR_COLOUR_SET)

    painted = 0
    for band, vertices in sorted(buckets.items()):
        red, green, blue = colour((band + 0.5) / float(bands))
        cmds.polyColorPerVertex(['{}.vtx[{}]'.format(name, vertex) for vertex in vertices],
                                rgb=(red, green, blue), colorDisplayOption=True)
        painted += len(vertices)

    # Whatever Maya just added to the history is the heat map's, and is what
    # clear_error_colours will take away again.
    _tag_new_nodes(shape, before)

    try:
        shape.displayColors.set(True)
    except Exception:
        logger.debug('Could not turn on colour display for %s.', shape, exc_info=True)

    return painted, ('Painted {} vertices. Red is {:.4f} scene units out; black is a match.'
                     .format(painted, worst))


@_safe
def clear_error_colours(mesh):
    """
    Take the heat map off again.

    :param mesh: The mesh to clean.
    :return: Response.
    :rtype: dict
    """

    shape = _mesh_shape(mesh)
    name = shape.longName()
    try:
        shape.displayColors.set(False)
    except Exception:
        logger.debug('Could not turn off colour display.', exc_info=True)

    # The nodes first. Deleting them is what actually takes the colours off a
    # deformed mesh, and it leaves the history the length it was before the map went
    # on - the previous version deleted the colour SET and added a `deleteColorSet`
    # node to do it, so clearing the heat map made the history one node LONGER and
    # left a dead `polyColorPerVertex` in front of it.
    removed_nodes = _remove_heat_map(shape)

    # Then our colour set, if deleting the nodes did not take it with them. Only
    # ours: a production mesh carries authored colour sets and they are not ours to
    # delete.
    before = _history(shape)
    removed_sets = []
    if ERROR_COLOUR_SET in (cmds.polyColorSet(name, q=True, allColorSets=True) or []):
        try:
            cmds.polyColorSet(name, delete=True, colorSet=ERROR_COLOUR_SET)
            removed_sets.append(ERROR_COLOUR_SET)
        except Exception:
            logger.debug('Could not delete colour set %s.', ERROR_COLOUR_SET, exc_info=True)
        # And whatever that delete added to the history goes too.
        for node in _tag_new_nodes(shape, before):
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                    removed_nodes.append(node)
                except Exception:
                    logger.debug('Could not delete %s.', node, exc_info=True)

    kept = [each for each in (cmds.polyColorSet(name, q=True, allColorSets=True) or [])]
    result = {'nodes': sorted(set(removed_nodes)), 'colour_sets': removed_sets,
              'colour_sets_left_alone': kept}
    message = 'Removed the heat map from {}: {} colour set(s) and {} history node(s).'.format(
        shape, len(removed_sets), len(set(removed_nodes)))
    if kept:
        message += '  Left {} other colour set(s) alone: {}.'.format(len(kept), ', '.join(kept))
    return result, message


def _skin_weights(shape, cluster):
    """
    Every weight on the mesh, and the influences in the same column order.

    Read through ``MFnSkinCluster`` rather than ``skinPercent`` - see
    :func:`add_correctives` for what that cost to find out.

    :param shape: The mesh shape.
    :param cluster: The skinCluster.
    :return: ``(weights as vertices x influences, [influence long names])``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma

    numpy = _numpy()
    selection = om.MSelectionList()
    selection.add(_mesh_shape(shape).longName())
    path = selection.getDagPath(0)
    count = _mesh_shape(shape).numVertices()

    components = om.MFnSingleIndexedComponent()
    component = components.create(om.MFn.kMeshVertComponent)
    components.addElements(list(range(count)))

    holder = om.MSelectionList()
    holder.add(str(cluster))
    fn = oma.MFnSkinCluster(holder.getDependNode(0))
    flat, influenceCount = fn.getWeights(path, component)
    weights = numpy.array(flat).reshape(count, influenceCount)
    names = [each.fullPathName() for each in fn.influenceObjects()]
    return weights, names


@_safe
def transfer_skin(source, target, max_influences=None):
    """
    Copy a skinCluster's weights from one mesh onto another, and check that it worked.

    Uses the framework's own :func:`mca.mya.deformations.skin_utils.copy_skin_weights`
    rather than a second implementation of the same thing.

    **The check matters.** That function creates the target's skinCluster when there is
    not one, and the skinCluster it creates obeys a maximum influence count - four, by
    default, because that is what most of this pipeline binds at. Copying a head that
    has six influences on a vertex onto a cluster capped at four silently drops two of
    them, and the only sign is a slightly different shape. So the influence count is
    taken from the source, and the transfer is measured afterwards: on identical
    topology the weights should come back the same to within rounding.

    :param source: The skinned mesh to copy from.
    :param target: The mesh to copy onto - normally a duplicate of the source.
    :param int max_influences: Cap for a newly created skinCluster. None takes the
        source's own cap, or the worst per-vertex count it actually uses, whichever is
        larger.
    :return: Response whose result carries the new skinCluster and ``worst_difference``.
    :rtype: dict
    """

    from mca.mya.deformations import skin_utils

    numpy = _numpy()
    source_shape = _mesh_shape(source)
    target_shape = _mesh_shape(target)
    cluster = existing_skin(source_shape)
    if cluster is None:
        raise ValueError('{} has no skinCluster to copy from.'.format(source_shape))

    before, columns = _skin_weights(source_shape, cluster)
    if source_shape.numVertices() != target_shape.numVertices():
        raise ValueError(
            '{} has {} vertices and {} has {} - a weight is matched to a vertex by its '
            'number, so the two have to agree.'.format(
                source_shape, source_shape.numVertices(),
                target_shape, target_shape.numVertices()))

    if max_influences is None:
        used = int((before > 0.0).sum(axis=1).max())
        try:
            capped = int(cmds.getAttr(str(cluster) + '.maxInfluences'))
        except Exception:
            capped = 0
        max_influences = max(used, capped, 1)

    with _KeepSelection():
        skin_utils.copy_skin_weights([source_shape.getParent() or source_shape],
                                     [target_shape.getParent() or target_shape],
                                     match_influences=True, max_influences=max_influences)

    made = existing_skin(target_shape)
    if made is None:
        raise ValueError('The weight copy did not leave a skinCluster on {}.'.format(
            target_shape))

    after, after_columns = _skin_weights(target_shape, made)
    lookup = {name: index for index, name in enumerate(after_columns)}
    worst = 0.0
    missing = []
    for index, name in enumerate(columns):
        target_column = lookup.get(name)
        if target_column is None:
            if float(numpy.abs(before[:, index]).max()) > 0.0:
                missing.append(name.split('|')[-1])
            continue
        worst = max(worst, float(numpy.abs(after[:, target_column] - before[:, index]).max()))

    result = {'skin_cluster': str(made), 'influences': len(after_columns),
              'worst_difference': worst, 'max_influences': max_influences,
              'influences_lost': missing}
    message = ('Transferred {} influence(s) of skinning from {} onto {}; the weights differ '
               'by at most {:.2e}.'.format(len(columns), source_shape.nodeName(),
                                           target_shape.nodeName(), worst))
    if missing:
        message += ('  WARNING: {} influence(s) carried weight on the source and are not on '
                    'the copy at all: {}.'.format(len(missing), ', '.join(missing[:6])))
    elif worst > 1e-6:
        message += ('  That is larger than rounding - the copy is not an exact match, so check '
                    'it before relying on it.')
    return result, message


@_safe
@_one_undo
@_keep_selection
def add_to_skin(mesh, joints, frames, donors, skin_cluster=None, rest_frame=None,
                max_influences=DEFAULT_MAX_INFLUENCES, solve_bones=False, iterations=1,
                holdout=None, show=False, duplicate=True, **kwargs):
    """
    Add joints to a skin that already exists, taking their weight from named donors.

    **What this is for.** :func:`skin_from_poses` solves the whole skin: it fits
    absolute position with the weights constrained to sum to one, so every vertex has
    to be explained by the joints it was given. Hand it a left-cheek joint and the
    back of the head must also reach 1.0 out of the candidates available - so the
    cheek joint ends up with weight on the back of the head. That is the objective
    doing as it was told, and locality only narrows it.

    This fits the RESIDUAL instead - the difference between where the existing skin
    already puts each vertex and where the pose actually is - and takes the weight it
    needs out of the influences you nominate::

        add_to_skin('head_mesh', ['cheek_l', 'cheek_r', 'jaw'], frames, donors=['head'])

    Three things follow, and none of them is a heuristic:

    - **The back of the head gets nothing.** Not forbidden - unearned. The existing
      skin already fits there, so the residual is zero and no cheek joint can reduce
      it.
    - **Influences you did not nominate come out bit-identical.** Weight can only
      leave a donor.
    - **The weights still sum to exactly one**, because what the new joints gain the
      donors lose. Nothing is renormalised, so nothing drifts - and Maya never prints
      "weights required modification for normalization".

    A vertex where the donors hold nothing receives nothing, automatically.

    :param mesh: The mesh that deforms.
    :param joints: The joints to add. They must not be donors.
    :param frames: One frame per pose.
    :param donors: The existing influence(s) to take weight from - a name or a list.
    :param skin_cluster: Which skinCluster to add to. None finds the one on the mesh.
    :param float rest_frame: The neutral pose.
    :param int max_influences: Most NEW joints on one vertex. The existing influences
        are not counted against this, because they are not being solved.
    :param bool solve_bones: Solve the new joints' motion as well as their weights.
    :param int iterations: Weight/bone alternations. Needs to be > 1 for
        ``solve_bones`` to do anything.
    :param holdout: Frames to keep out of the fit and report separately.
    :param bool show: Paint the per-vertex error as a heat map afterwards.
    :param bool duplicate: **On by default.** Put the result on a clean copy of the
        mesh, carrying the existing skinning across first, and leave the original with
        its blendShape untouched. One mesh holds the shapes, the other holds the skin -
        which is what you want in an engine, and it means the original is still there to
        compare against. Off writes into the skinCluster on the mesh itself.
    :return: Response whose result carries the solve, ``weight_moved``,
        ``vertices_changed``, ``capped``, ``verified`` and ``copy``.
    :rtype: dict
    """

    numpy = _numpy()
    original = _mesh_shape(mesh)
    shape = original
    source_cluster = pm.PyNode(skin_cluster) if skin_cluster is not None \
        else existing_skin(original)
    if source_cluster is None:
        raise ValueError(
            '{} has no skinCluster. Additive mode adds joints to a skin that already '
            'exists - use skin_from_poses to build one from nothing.'.format(original))

    # The copy, and the skinning carried onto it.
    #
    # The poses are still SAMPLED from the original, because that is where the
    # blendShape that makes them lives. Only the skin moves to the copy.
    copy = None
    cluster = source_cluster
    if duplicate:
        copy, moved = _working_copy(original, rest_frame, carry_skin=True)
        if moved is None:
            raise ValueError(
                '{} has a skinCluster but the copy did not receive it, so there is nothing '
                'to add to.'.format(original))
        cluster = pm.PyNode(moved['result']['skin_cluster'])

    wanted = [donors] if isinstance(donors, str) else list(donors)
    if not wanted:
        raise ValueError('Name at least one donor influence to take the weight from.')

    names = _joint_names(joints)
    skinned = _mesh_shape(copy) if copy is not None else shape

    # Add the joints as influences HERE, not in the plug-in.
    #
    # The command used to do it with `skinCluster -edit -addInfluence`, and then its undo
    # had to take them off again - which means running a command from inside `undoIt`,
    # which Maya does not support. The weights came back and the influence stayed, so
    # undoing left a joint bound at whatever the renormalise decided. Done here it is an
    # ordinary scene edit inside this run's undo chunk, and one Ctrl+Z takes the lot.
    have = {pm.PyNode(each).longName() for each in
            (cmds.skinCluster(str(cluster), q=True, influence=True) or [])}
    missing = [each for each in names if pm.PyNode(each).longName() not in have]
    if missing:
        cmds.skinCluster(str(cluster), edit=True, addInfluence=missing, weight=0.0,
                         lockWeights=False)

    before, columns = _skin_weights(skinned, cluster)

    donor_paths = set()
    for each in wanted:
        donor_paths.add(pm.PyNode(each).longName())
    donor_columns = [index for index, name in enumerate(columns) if name in donor_paths]
    if not donor_columns:
        raise ValueError(
            'None of {} is an influence of {}. Name one of its influences as the '
            'donor: {}.'.format(wanted, cluster, ', '.join(
                name.split('|')[-1] for name in columns)))
    # Keepers are the influences that are NEITHER donors NOR joints being solved.
    #
    # The joints are added as influences before the weights are read, so they appear in
    # `columns` with zero weight - and counting them as keepers made the verification
    # report that a keeper had "moved by 1.0" on the very vertex where the new joint had
    # correctly taken all of it. A check that fails on the right answer is worse than no
    # check, because the next person turns it off.
    solved_paths = {pm.PyNode(each).longName() for each in names}
    keeper_columns = [index for index, name in enumerate(columns)
                      if index not in donor_columns and name not in solved_paths]

    response = solve(shape, names, frames, rest_frame=rest_frame,
                     max_influences=max_influences, solve_bones=solve_bones,
                     iterations=iterations, holdout=holdout, apply_to=str(cluster),
                     donors=[str(each) for each in wanted], **kwargs)
    if not response['ok']:
        return response['result'], response['message']
    solved = response['result']

    # ---- verify the claim, here, independently of the plug-in ----------------- #
    #
    # The C++ side refuses to write weights that do not sum to one, but that check is
    # made from the same numbers that produced them. This one reads the skinCluster
    # back afterwards and is the claim this function makes, stated as arithmetic:
    # the keepers did not move, and the totals are still one.
    after, columns_after = _skin_weights(skinned, cluster)
    verified = {}
    if columns_after[:len(columns)] == columns:
        moved_keepers = float(numpy.abs(after[:, keeper_columns] -
                                        before[:, keeper_columns]).max()) \
            if keeper_columns else 0.0
    else:
        # Adding influences appended columns; match the keepers up by name instead of
        # trusting the order.
        lookup = {name: index for index, name in enumerate(columns_after)}
        moved_keepers = 0.0
        for index in keeper_columns:
            target = lookup.get(columns[index])
            if target is None:
                continue
            moved_keepers = max(moved_keepers,
                                float(numpy.abs(after[:, target] - before[:, index]).max()))
    totals = after.sum(axis=1)
    verified['keepers_moved_by'] = moved_keepers
    verified['worst_total_error'] = float(numpy.abs(totals - 1.0).max())
    verified['ok'] = moved_keepers < 1e-9 and verified['worst_total_error'] < 1e-6

    taken = float(numpy.abs(after[:, donor_columns].sum(axis=1) -
                            before[:, donor_columns].sum(axis=1)).sum())
    changed = int((numpy.abs(after[:, donor_columns].sum(axis=1) -
                             before[:, donor_columns].sum(axis=1)) > 1e-9).sum())

    if show and solved.get('vertex_error'):
        show_error(skinned, solved['vertex_error'])

    result = {'solve': solved, 'skin_cluster': str(cluster),
              'copy': str(copy) if copy is not None else None,
              'skinned_mesh': str(skinned.getParent() or skinned),
              'donors': [name.split('|')[-1] for name in
                         (columns[index] for index in donor_columns)],
              'joints': names, 'weight_moved': taken, 'vertices_changed': changed,
              'capped': solved.get('capped_vertices', 0), 'verified': verified}

    message = ('Added {} joint(s) to {}, taking {:.2f} of weight off {} across {} of {} '
               'vertices. rms {:.4f}, worst {:.4f}.'.format(
                   len(names), cluster, taken,
                   ', '.join(result['donors']), changed, before.shape[0],
                   solved['rms'], solved['worst']))
    if copy is not None:
        message += ('  The skin went on a copy, {}, with the existing skinning carried over '
                    'first; {} keeps its blendShape and is untouched.'.format(
                        str(copy).split('|')[-1], original.getParent().nodeName()))
    # `holdout_rms` is None when nothing was held out, not a negative number: the
    # parser turns the command's -1 sentinel into None so that a caller cannot read
    # "-1 scene units of error" as a measurement.
    if solved.get('holdout_rms') is not None:
        message += '  Held out {} pose(s): rms {:.4f}.'.format(
            len(_frame_list(holdout or [])), solved['holdout_rms'])
    if result['capped']:
        message += ('  {} vertex(es) wanted more weight than the donor had and were scaled '
                    'back - usually a sign the deformation needs weight from an influence '
                    'that was not offered.'.format(result['capped']))
    if verified['ok']:
        message += ('  Checked: the other influences did not move (worst {:.1e}) and every '
                    'vertex still sums to 1 (worst {:.1e}).'.format(
                        verified['keepers_moved_by'], verified['worst_total_error']))
    else:
        message += ('  WARNING: the check failed - other influences moved by {:.3e} and the '
                    'worst total is off by {:.3e}. Undo this.'.format(
                        verified['keepers_moved_by'], verified['worst_total_error']))
    return result, message


@_safe
def influence_report(mesh, joints, frames, budgets=(4, 8, 12), rest_frame=None,
                     holdout=None, **kwargs):
    """
    What each influence budget costs, measured rather than guessed.

    An engine gives you four or eight or twelve influences per vertex and the
    question is always what the cheaper one costs. This solves each budget and puts
    the numbers side by side, which takes as long as that many solves and settles
    the argument.

    :param mesh: The mesh that deforms.
    :param joints: The influences.
    :param frames: One frame per pose.
    :param budgets: The influence limits to try.
    :param float rest_frame: The neutral pose.
    :param holdout: Frames to keep out of the fit.
    :param kwargs: Passed to :func:`solve`.
    :return: Response whose result is ``[{'max_influences', 'rms', 'worst',
        'holdout_rms', 'holdout_worst'}]``.
    :rtype: dict
    """

    rows = []
    for budget in budgets:
        response = solve(mesh, joints, frames, rest_frame=rest_frame,
                         max_influences=int(budget), holdout=holdout,
                         per_vertex_error=False, **kwargs)
        if not response['ok']:
            raise RuntimeError(response['message'])
        parsed = response['result']
        rows.append({'max_influences': int(budget), 'rms': parsed['rms'],
                     'worst': parsed['worst'], 'holdout_rms': parsed['holdout_rms'],
                     'holdout_worst': parsed['holdout_worst']})

    best = min(rows, key=lambda row: row['rms'])
    lines = ', '.join('{}: rms {:.4f}'.format(row['max_influences'], row['rms'])
                      for row in rows)
    return rows, ('Influence budgets on {} - {}. Nothing here is free; {} is the best of '
                  'them.'.format(_mesh_shape(mesh), lines, best['max_influences']))


@_safe
def poses_from_blendshape(mesh, blendshape=None, start_frame=None, value=1.0, step=1.0):
    """
    Key a blendShape's targets out onto one frame each, so they can be solved from.

    A solve needs poses on frames, and on a face the poses are usually channels on
    a blendShape rather than an animation. This lays them out: the start frame with
    everything at zero, then one frame per channel with that channel at ``value``
    and the rest at zero.

    **The joints have to follow.** This keys the blendShape and nothing else. If
    the rig's joints are driven by those same channels - through set-driven keys, a
    pose reader, or the face pose system - then they are now posed on every frame
    and a solve will work. If they are not, the frames will show the shapes with
    the skeleton standing still, and the solve will honestly report that no
    skinning reproduces that. :func:`auto_joints` is the way round it when there is
    no skeleton to follow yet.

    :param mesh: The mesh to find a blendShape on, when one is not given.
    :param blendshape: The blendShape node. None finds the one on ``mesh``.
    :param float start_frame: Where to put the neutral pose. None uses the current
        time.
    :param float value: What to drive each channel to. 1.0 is the full shape.
    :param float step: Frames between poses.
    :return: Response whose result is ``{'rest_frame', 'frames', 'channels',
        'blendshape'}``.
    :rtype: dict
    """

    shape = _mesh_shape(mesh)
    if blendshape is None:
        found = list(pm.listHistory(shape, type='blendShape'))
        if not found:
            raise ValueError('There is no blendShape on {}. Pass one, or pose the rig on '
                             'frames yourself.'.format(shape))
        blendshape = found[0]
        if len(found) > 1:
            logger.warning('%s has %s blendShapes; used %s.', shape, len(found), blendshape)
    node = pm.PyNode(blendshape)

    indices = cmds.getAttr(str(node) + '.weight', multiIndices=True) or []
    if not indices:
        raise ValueError('{} has no weights to lay out.'.format(node))

    channels = []
    for index in indices:
        plug = '{}.weight[{}]'.format(node, index)
        alias = cmds.aliasAttr(plug, query=True)
        channels.append((alias or 'weight[{}]'.format(index), plug))

    if start_frame is None:
        start_frame = pm.currentTime(q=True)
    start_frame = float(start_frame)

    frames = []
    for position in range(len(channels)):
        frames.append(start_frame + step * float(position + 1))

    # Four keys per channel: zero at the neutral, zero the frame before its own,
    # the value on its own frame, zero the frame after. Every channel is keyed, so
    # nothing holds a value it happened to have when this ran - a face with one
    # shape already dialled in would otherwise be baked into every pose - and every
    # channel reads exactly zero on every frame but its own.
    #
    # The obvious version keys every channel on every frame, which on this face is
    # 173 channels x 174 frames = 30,102 `setKeyframe` calls. Each one is a Maya
    # command with its own undo entry; the sparse version is 692 and runs in about a
    # second.
    for position, (_, plug) in enumerate(channels):
        own = frames[position]
        cmds.setKeyframe(plug, time=start_frame, value=0.0)
        if own - step > start_frame:
            cmds.setKeyframe(plug, time=own - step, value=0.0)
        cmds.setKeyframe(plug, time=own, value=float(value))
        cmds.setKeyframe(plug, time=own + step, value=0.0)

    result = {'rest_frame': start_frame, 'frames': frames, 'blendshape': str(node),
              'channels': [name for name, _ in channels]}
    return result, ('Laid {} shape(s) out on frames {:g} to {:g}, with the neutral on {:g}. '
                    'The joints have to be driven by the same channels for a solve to have '
                    'anything to fit.'.format(len(channels), frames[0], frames[-1],
                                              start_frame))


def _numpy():
    """
    :return: numpy.
    :raises RuntimeError: When it is not there, saying what cannot be done without
        it rather than failing on an import line.
    """

    try:
        import numpy
    except ImportError:
        raise RuntimeError('This needs numpy, which is not available in this Maya. The solve '
                           'itself does not - only the parts done in Python.')
    return numpy


def _points(shape, space=None):
    """
    A mesh's world points, read in a way that forces the DG to evaluate.

    **`MFnMesh(dagPath).getPoints()` does not force evaluation.** Under parallel
    evaluation a shape recomputes when something pulls on it, usually the viewport;
    a mesh nobody is looking at - hidden, or freshly built, or in a headless
    session - keeps handing back whatever it last computed. Reading it that way
    after a time change or a rig edit gives the previous answer, silently.

    That cost real time twice in one evening: a scene audit built on the unsafe read
    reported twenty times the error that was actually there, and the corrective
    check refused a correct skin because the rest shape it compared against had
    never been evaluated. Asking for the `outMesh` plug's value is a pull, and so is
    asking for `worldMatrix` - which has to be read the same way, for the same
    reason, or the world-space transform is stale instead.

    :param shape: A mesh shape.
    :param space: Ignored; kept so existing callers do not change. World space is
        the only thing this is used for, and doing it properly needs the transform
        pulled as well.
    :return: ``[(x, y, z)]`` in world space.
    :rtype: list
    """

    import maya.api.OpenMaya as om
    selection = om.MSelectionList()
    selection.add(str(shape))
    path = selection.getDagPath(0)
    node = om.MFnDagNode(path)

    data = node.findPlug('outMesh', False).asMObject()
    matrix = om.MFnMatrixData(
        node.findPlug('worldMatrix', False)
        .elementByLogicalIndex(path.instanceNumber()).asMObject()).matrix()
    points = om.MFnMesh(data).getPoints(om.MSpace.kObject)
    return [tuple(om.MPoint(point) * matrix)[:3] for point in points]


def _deformer_input_points(cluster, shape):
    """
    The geometry going INTO a deformer - for a skinCluster, the bind shape.

    :param cluster: The skinCluster.
    :param shape: The mesh it deforms, used to work out which input to read.
    :return: ``[(x, y, z)]`` in the shape's object space, which is its world space
        when the transform is identity - and :func:`add_correctives` refuses if it is
        not.
    :rtype: list
    :raises ValueError: When the input geometry cannot be read, which would
        otherwise become a silently wrong rest pose.
    """

    import maya.api.OpenMaya as om

    selection = om.MSelectionList()
    selection.add(str(cluster))
    node = om.MFnDependencyNode(selection.getDependNode(0))
    inputs = node.findPlug('input', False)
    for index in range(inputs.numElements()):
        element = inputs.elementByPhysicalIndex(index)
        geometry = element.child(0)  # inputGeometry
        data = geometry.asMObject()
        if data.isNull() or not data.hasFn(om.MFn.kMeshData):
            continue
        points = om.MFnMesh(data).getPoints(om.MSpace.kObject)
        return [(point.x, point.y, point.z) for point in points]
    raise ValueError('Could not read the bind shape going into {}. Without it there is '
                     'nothing to measure a corrective against.'.format(cluster))


def _sample_points(shape, frames, numpy=None):
    """
    World points at each frame, and the time put back afterwards.

    With numpy, each frame is converted as it is read rather than at the end. The
    difference is not cosmetic: 173 poses of a 5,348-vertex head held as Python
    tuples is 925,000 objects and a few hundred megabytes, and the same numbers as
    one array are 22 MB.

    :param shape: A mesh shape.
    :param frames: Frames to read.
    :param numpy: Pass numpy to get an (f, v, 3) array; None gives nested lists.
    :return: One entry per frame.
    """

    was_at = pm.currentTime(q=True)
    out = []
    try:
        for frame in frames:
            pm.currentTime(frame, edit=True)
            points = _points(shape)
            out.append(numpy.array(points, dtype=float) if numpy is not None else points)
    finally:
        pm.currentTime(was_at, edit=True)
    return numpy.array(out) if numpy is not None else out


@_safe
@_one_undo
@_keep_selection
def add_correctives(mesh, source, frames, skin_cluster=None, name=None, tolerance=0.01):
    """
    Absorb whatever the skin could not reach into a corrective blendShape.

    A skin fitted to poses is a compromise; this closes the gap. For every pose it
    measures what is left over, converts that back into the rest pose's space, and
    builds it as a blendShape target in front of the skinCluster - so the
    corrective rides the joints instead of fighting them, which is the whole reason
    it goes in front rather than behind.

    After this, the skinned mesh reproduces the original on the poses it was given.
    Between them it is the skin plus whatever the correctives interpolate to, which
    is a real answer rather than an exact one - the same deal as any corrective.

    What it checks before it writes anything
    ----------------------------------------
    It predicts the skinned position from the weights, the bind matrices and the
    joints, and compares that against where the mesh actually is. If those two
    disagree, the space the correction is being converted into is not the space the
    blendShape will apply it in, and the corrective would be wrong in a way that
    looks like a rigging mistake. It refuses instead, and says by how much.

    :param mesh: The SKINNED mesh - the one with the skinCluster on it.
    :param source: The mesh that actually deforms, which the skin is chasing.
    :param frames: The poses to correct, normally the ones that were solved.
    :param skin_cluster: The skinCluster. None finds the one on ``mesh``.
    :param str name: Name for the blendShape. None names it after the mesh.
    :param float tolerance: How far the predicted skinning may be from the real
        thing, as a fraction of the mesh's size, before this refuses.

    The current frame does not matter to this call. It reads the bind shape from the
    skinCluster's own input and goes to each pose itself.
    :return: Response whose result is ``{'blendshape', 'targets', 'worst_before',
        'worst_after'}``.
    :rtype: dict
    """

    numpy = _numpy()
    import maya.api.OpenMaya as om

    shape = _mesh_shape(mesh)
    source_shape = _mesh_shape(source)
    frames = _frame_list(frames)

    cluster = pm.PyNode(skin_cluster) if skin_cluster is not None else existing_skin(shape)
    if cluster is None:
        raise ValueError('{} has no skinCluster, so there is nothing to correct.'.format(shape))

    # The weights, read through MFnSkinCluster rather than skinPercent.
    #
    # `skinPercent -q -transform joint` over `vtx[*]` looks like the obvious way to
    # do this and it returns the wrong numbers: on a 58-vertex sphere its answers
    # differed from the API's by 0.57 on a single weight. The prediction check below
    # is what caught it - built on the API's weights the predicted skinning lands on
    # the mesh to 1e-7, and built on skinPercent's it was 0.26 scene units out. It
    # is also one call instead of one per influence, which on a character with
    # eighty of them is the difference between a second and a minute.
    import maya.api.OpenMayaAnim as oma

    selection = om.MSelectionList()
    selection.add(shape.longName())
    path = selection.getDagPath(0)
    vertexCount = shape.numVertices()

    components = om.MFnSingleIndexedComponent()
    component = components.create(om.MFn.kMeshVertComponent)
    components.addElements(list(range(vertexCount)))

    clusterSelection = om.MSelectionList()
    clusterSelection.add(str(cluster))
    clusterFn = oma.MFnSkinCluster(clusterSelection.getDependNode(0))

    flat, influenceCount = clusterFn.getWeights(path, component)
    weights = numpy.array(flat).reshape(vertexCount, influenceCount)

    # And the joints in the SAME order as those columns, with each one's bind matrix
    # taken by its logical index - the two agree on a skinCluster nobody has edited
    # and stop agreeing the moment an influence is removed.
    influencePaths = clusterFn.influenceObjects()
    influences = [pm.PyNode(each.fullPathName()) for each in influencePaths]
    bind = numpy.array(
        [numpy.array(cluster.bindPreMatrix[clusterFn.indexForInfluenceObject(each)].get())
         .reshape(4, 4) for each in influencePaths])

    # The rest shape comes from the skinCluster's INPUT, not from the mesh at
    # whatever frame the clock happens to be on.
    #
    # Reading the deformed mesh and calling it the rest pose works only if the
    # caller has already moved to the bind frame, and there is no reason they
    # should know that: the first version did exactly that and a caller who left
    # the time on frame 3 got a "rest" shape that was already bent, which put the
    # whole correction out by the size of the bend - 2.96 units, refused by the
    # check below. The skinCluster's input geometry IS the bind shape, by
    # definition, and it does not depend on the clock at all.
    rest = numpy.array(_deformer_input_points(cluster, shape), dtype=float)
    scale = float(numpy.linalg.norm(rest.max(axis=0) - rest.min(axis=0))) or 1.0

    was_at = pm.currentTime(q=True)
    targets = []
    worst_before = 0.0
    try:
        for frame in frames:
            pm.currentTime(frame, edit=True)
            truth = numpy.array(_points(source_shape), dtype=float)
            actual = numpy.array(_points(shape), dtype=float)

            # The skinning matrix per vertex, built the way Maya builds it: the
            # bind pre-matrix times the joint's world matrix, weighted.
            world = numpy.array([numpy.array(influence.worldMatrix[0].get()).reshape(4, 4)
                                 for influence in influences])
            perJoint = numpy.matmul(bind, world)                       # J, 4, 4
            perVertex = numpy.einsum('vj,jab->vab', weights, perJoint)  # V, 4, 4

            # The check that makes the rest of this trustworthy.
            homogeneous = numpy.concatenate([rest, numpy.ones((len(rest), 1))], axis=1)
            predicted = numpy.einsum('va,vab->vb', homogeneous, perVertex)[:, :3]
            disagreement = float(numpy.abs(predicted - actual).max())
            if disagreement > tolerance * scale:
                raise RuntimeError(
                    'The skinning predicted from the weights is {:.4f} scene units away from '
                    'where {} actually is on frame {:g} ({:.2f}% of the mesh). Something else '
                    'is deforming it - another deformer, a non-identity transform, or a '
                    'bindPreMatrix that does not match the bind pose - and a corrective built '
                    'on that assumption would be wrong. Freeze the skinned mesh\'s transform '
                    'and take other deformers off it first.'
                    .format(disagreement, shape, frame, 100.0 * disagreement / scale))

            deltaWorld = truth - actual
            worst_before = max(worst_before, float(numpy.linalg.norm(deltaWorld, axis=1).max()))

            # A delta is a direction, so only the linear part of the skinning
            # matrix applies to it - and it has to be undone to get back to the
            # space the blendShape target lives in.
            linear = perVertex[:, :3, :3]
            inverted = numpy.linalg.pinv(linear)
            deltaRest = numpy.einsum('va,vab->vb', deltaWorld, inverted)
            targets.append(rest + deltaRest)
    finally:
        pm.currentTime(was_at, edit=True)

    if worst_before <= 1e-6 * scale:
        # Nothing to correct. Building a blendShape whose targets are identical to
        # the base would leave a node in the scene that does nothing and reads as if
        # it were doing something.
        return ({'blendshape': None, 'targets': 0, 'worst_before': worst_before,
                 'worst_after': worst_before},
                'The skin already reproduces those poses to {:.6f} scene units, so there '
                'is nothing for a corrective to hold.'.format(worst_before))

    # Build the target meshes at rest, hook them up, and key one frame each.
    blend_name = name or '{}_correctives'.format(shape.getParent() or shape)
    made = []
    try:
        for index, positions in enumerate(targets):
            duplicate = cmds.duplicate(shape.longName(), name='{}_pose{}'.format(blend_name,
                                                                                 index),
                                       returnRootsOnly=True)[0]
            cmds.delete(duplicate, constructionHistory=True)
            target_shape = _mesh_shape(duplicate)
            selection = om.MSelectionList()
            selection.add(str(target_shape))
            fn = om.MFnMesh(selection.getDagPath(0))
            fn.setPoints(om.MPointArray([om.MPoint(*row) for row in positions]),
                         om.MSpace.kWorld)
            made.append(duplicate)

        node = cmds.blendShape(made, shape.longName(), frontOfChain=True, name=blend_name)[0]
    finally:
        pass

    for index, frame in enumerate(frames):
        plug = '{}.weight[{}]'.format(node, index)
        for other in frames:
            cmds.setKeyframe(plug, time=other, value=0.0)
        cmds.setKeyframe(plug, time=frame, value=1.0)
    cmds.delete(made)

    # What it is worth, measured the same way as before.
    worst_after = 0.0
    try:
        for frame in frames:
            pm.currentTime(frame, edit=True)
            truth = numpy.array(_points(source_shape), dtype=float)
            actual = numpy.array(_points(shape), dtype=float)
            worst_after = max(worst_after,
                              float(numpy.linalg.norm(truth - actual, axis=1).max()))
    finally:
        pm.currentTime(was_at, edit=True)

    result = {'blendshape': node, 'targets': len(targets), 'worst_before': worst_before,
              'worst_after': worst_after}
    return result, ('Built {} corrective(s) on {}. Worst error on those poses went from '
                    '{:.4f} to {:.4f} scene units.'
                    .format(len(targets), shape, worst_before, worst_after))


def _kabsch(numpy, source, target):
    """
    The rigid transform that best takes one point set to another.

    A Python copy of the fit in the plug-in, and used only to INITIALISE the
    joints: every number it produces is refined by the real solver afterwards. The
    same reasoning as the retargeter's point picking - a heuristic in Python cannot
    disagree with the answer, because it does not produce the answer.

    :param source: (n, 3) rest positions.
    :param target: (n, 3) where they went.
    :return: A 4x4 in Maya's row-vector convention.
    """

    sourceCentre = source.mean(axis=0)
    targetCentre = target.mean(axis=0)
    covariance = (source - sourceCentre).T @ (target - targetCentre)
    u, _, vt = numpy.linalg.svd(covariance)
    sign = numpy.sign(numpy.linalg.det(vt.T @ u.T))
    correction = numpy.diag([1.0, 1.0, sign])
    rotation = vt.T @ correction @ u.T          # column-vector convention
    matrix = numpy.identity(4)
    matrix[:3, :3] = rotation.T                 # row-vector convention
    matrix[3, :3] = targetCentre - rotation @ sourceCentre
    return matrix


def _cluster_by_motion(numpy, rest, poses, count, rounds=15):
    """
    Group vertices that move together, deterministically.

    **By motion, not by position.** A bone is a set of vertices that share a rigid
    transform, and what identifies them is their trajectory: the chin and the lower
    lip sit close together and move apart, the two eyelids sit apart and move
    together. Clustering rest positions - which is what the tool this replaces did -
    describes the model rather than the deformation, so it cuts across the places
    the deformation actually hinges.

    **And deterministically.** The original seeded k-means with
    ``random.choice``, so two runs on the same mesh produced two different
    skeletons, and there was no way to reproduce yesterday's result. Here the first
    centre is the vertex that moves most and each next one is the vertex furthest
    from every centre so far, which is a fixed answer for a fixed input.

    :param rest: (v, 3) rest positions.
    :param poses: (f, v, 3) posed positions.
    :param int count: How many groups.
    :param int rounds: Lloyd iterations.
    :return: (labels per vertex, features) .
    """

    displacement = numpy.concatenate([pose - rest for pose in poses], axis=1)  # v, 3f
    # Position is included, weakly, to keep a group from spanning two parts of the
    # mesh that happen to move alike - the same reasoning as the solver's locality
    # restriction, and measured there.
    scale = float(numpy.abs(displacement).max()) or 1.0
    span = float(numpy.linalg.norm(rest.max(axis=0) - rest.min(axis=0))) or 1.0
    features = numpy.concatenate([displacement / scale, rest / span], axis=1)

    chosen = [int(numpy.argmax((displacement ** 2).sum(axis=1)))]
    nearest = ((features - features[chosen[0]]) ** 2).sum(axis=1)
    while len(chosen) < count:
        pick = int(numpy.argmax(nearest))
        chosen.append(pick)
        nearest = numpy.minimum(nearest, ((features - features[pick]) ** 2).sum(axis=1))
    centres = features[chosen].copy()

    # Squared distances by expansion rather than by broadcasting.
    #
    # `((features[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)` reads better
    # and allocates vertices x centres x features doubles to do it: on this face -
    # 5,348 vertices, 60 joints, 173 poses - that is 1.3 GB for a 5,348 x 60 answer.
    # |a - b|^2 = |a|^2 - 2ab + |b|^2 needs one matrix product and no such array.
    featureNorms = (features ** 2).sum(axis=1)

    def squaredDistances(points):
        out = (featureNorms[:, None] - 2.0 * features @ points.T +
               (points ** 2).sum(axis=1)[None, :])
        return numpy.maximum(out, 0.0)

    labels = numpy.zeros(len(features), dtype=int)
    for _ in range(rounds):
        distances = squaredDistances(centres)
        labels = numpy.argmin(distances, axis=1)
        moved = False
        for index in range(count):
            members = features[labels == index]
            if len(members) == 0:
                # An empty group is a wasted joint. Re-seed it on whichever vertex
                # its own centre fits worst, rather than leaving it where nothing
                # is.
                worst = int(numpy.argmax(distances.min(axis=1)))
                centres[index] = features[worst]
                moved = True
                continue
            centre = members.mean(axis=0)
            if not numpy.allclose(centre, centres[index]):
                centres[index] = centre
                moved = True
        if not moved:
            break
    labels = numpy.argmin(squaredDistances(centres), axis=1)
    return labels


@_safe
@_one_undo
@_keep_selection
def auto_joints(mesh, count, frames, rest_frame=None, prefix='poseJoint', parent=None,
                max_influences=DEFAULT_MAX_INFLUENCES, iterations=15, rigid_bones=True,
                skin=True, **kwargs):
    """
    Make the joints as well as the weights, from nothing but the deformation.

    For a cloth cache, a lattice, a prop that squashes - anything with no skeleton
    to start from. It groups vertices that move together, drops a joint in the
    middle of each group, keys each one to follow its group, and then lets the
    solver refine both the weights and the joint motion.

    What to expect
    --------------
    **The starting guess is the whole game.** The alternating solve is a local
    method: measured on synthetic data, from a deliberately hostile start - every
    joint sitting still - it improves the fit about three times over and then
    stops, while from a rough guess it walks all the way to exact. So the
    clustering here is not a nicety, it is the difference between a usable result
    and a stuck one.

    **Joints come out unparented and unoriented.** They are transforms that
    reproduce the deformation, not a rig. Orienting and parenting them is a
    separate job, and doing it changes nothing about the weights.

    :param mesh: The mesh that deforms.
    :param int count: How many joints to make.
    :param frames: One frame per pose.
    :param float rest_frame: The neutral pose. None uses the current time.
    :param str prefix: Name for the joints.
    :param parent: Something to put them under.
    :param int max_influences: Most joints one vertex may end up with.
    :param int iterations: Weight/bone alternations for the refinement.
    :param bool rigid_bones: Keep the joints rigid rather than letting them scale.
    :param bool skin: Also build the skin. False stops after making the joints,
        which is the way to check them before committing.
    :param kwargs: Passed to :func:`skin_from_poses`.
    :return: Response whose result carries the joints and, unless ``skin`` is off,
        the solve.
    :rtype: dict
    """

    numpy = _numpy()
    _require_plugin()

    shape = _mesh_shape(mesh)
    frames = _frame_list(frames)
    if rest_frame is None:
        rest_frame = pm.currentTime(q=True)
    count = int(count)
    if count < 1:
        raise ValueError('At least one joint, please.')
    if count > shape.numVertices():
        raise ValueError('{} joints for {} vertices is more joints than vertices.'
                         .format(count, shape.numVertices()))

    was_at = pm.currentTime(q=True)
    pm.currentTime(rest_frame, edit=True)
    rest = numpy.array(_points(shape), dtype=float)
    pm.currentTime(was_at, edit=True)
    poses = _sample_points(shape, frames, numpy=numpy)

    labels = _cluster_by_motion(numpy, rest, poses, count)

    # Clear the joints from a previous run before making new ones.
    #
    # **This is what stops the tool being single-use.** `createNode` uniquifies, so a
    # second run on the same mesh produced poseJoint201..400 alongside the first 200, all
    # still bound to the previous copy, and a third run produced 600. Only joints this
    # tool made and that nothing else is now using are removed: a joint that has become
    # an influence of a skinCluster other than our own previous copy is left alone, since
    # somebody has started relying on it.
    removed_joints = []
    for node in (cmds.ls('{}*'.format(prefix), type='joint', long=True) or []):
        clusters = set(cmds.listConnections(node, type='skinCluster') or [])
        if any(not _deforms_our_copy(cluster) for cluster in clusters):
            continue
        try:
            cmds.delete(node)
            removed_joints.append(node.split('|')[-1])
        except Exception:
            logger.debug('Could not remove the stale joint %s.', node, exc_info=True)
    if removed_joints:
        logger.info('Removed %d joint(s) from an earlier run.', len(removed_joints))

    # A joint per group, keyed to follow its group's rigid motion.
    joints = []
    fits = []
    restMatrices = []
    for index in range(count):
        members = numpy.where(labels == index)[0]
        if len(members) == 0:
            continue
        centre = rest[members].mean(axis=0)
        joint = cmds.createNode('joint', name='{}{}'.format(prefix, len(joints) + 1),
                                skipSelect=True)
        if parent is not None:
            joint = cmds.parent(joint, str(parent))[0]
        cmds.setAttr(joint + '.translate', *[float(value) for value in centre])
        joints.append(joint)

        restWorld = numpy.identity(4)
        restWorld[3, :3] = centre
        perFrame = []
        for pose in range(len(frames)):
            if len(members) >= 3:
                fit = _kabsch(numpy, rest[members], poses[pose][members])
            else:
                # Too few points to fit a rotation: follow the group's centre and
                # leave the orientation alone.
                fit = numpy.identity(4)
                fit[3, :3] = poses[pose][members].mean(axis=0) - centre
            perFrame.append(restWorld @ fit)
        fits.append(perFrame)
        # Kept per JOINT, not per cluster.
        #
        # A cluster can come out empty, and an empty cluster makes no joint - so
        # from that point on the joint list and the cluster numbering no longer
        # agree. Recomputing a joint's rest position from `labels == index` later
        # therefore reads the wrong cluster, and for a skipped index it averages an
        # empty array into NaN, which is keyed onto the joint and takes Maya down
        # with it. The number is known here, where it is right; it gets written
        # down rather than worked out again.
        restMatrices.append(restWorld.copy())

    # Key them, the rest frame included: the joints have to agree with the bind pose
    # there, or the skinCluster is bound to a skeleton that is already somewhere
    # else.
    for index, joint in enumerate(joints):
        _key_transforms(joint, [rest_frame] + list(frames),
                        [restMatrices[index]] + list(fits[index]))

    result = {'joints': joints, 'clusters': count, 'frames': frames,
              'rest_frame': rest_frame}
    if not skin:
        return result, ('Made {} joint(s) from the deformation and keyed them to follow it. '
                        'Nothing is skinned yet.'.format(len(joints)))

    response = skin_from_poses(shape, joints, frames, rest_frame=rest_frame,
                               max_influences=max_influences, iterations=iterations,
                               solve_bones=True, rigid_bones=rigid_bones,
                               return_bones=True, **kwargs)
    if not response['ok']:
        raise RuntimeError(response['message'])
    parsed = response['result']['solve']
    result.update(response['result'])

    # The solve moved the joints; put that motion back on them, or the skin
    # describes a skeleton nobody has.
    if parsed.get('bones'):
        # The REST frame is keyed again along with the poses, at the joint's rest
        # transform.
        #
        # The write-back clears the curves before rewriting them, and the first
        # version rewrote only the pose frames - so the rest key went and did not
        # come back. Nothing looked wrong: the skinCluster's bind matrices were
        # recorded when it was bound, so the poses still evaluated correctly. What
        # broke was everything that samples the rig AGAIN at the rest frame, because
        # the joints were sitting at their first pose instead of at bind. An
        # Influence Report run straight afterwards read rms 0.10 on a skin that was
        # really at 0.01, and the numbers looked like the solver's fault.
        for index, joint in enumerate(joints):
            _key_transforms(joint, [rest_frame] + list(frames),
                            [restMatrices[index]] +
                            [parsed['bones'][position][index]
                             for position in range(len(frames))])

    message = ('Made {} joint(s) from the deformation, then solved both the weights and '
               'their motion. {}'.format(len(joints), response['message']))
    return result, message


def _key_transforms(node, frames, matrices):
    """
    Key a transform's nine channels from a list of world matrices, in bulk.

    **Nine `setKeyframe` calls per joint per frame does not scale.** On the face
    this was built against - 80 joints, 174 frames - that is 125,000 Maya commands
    for one pass and another 125,000 to write the refined bones back afterwards,
    and Maya spends the time parsing them rather than doing anything. Written
    straight into anim curves through the API it is nine calls per joint, each
    carrying every key it needs.

    :param str node: The transform. Assumed to have no moving parent, which is what
        :func:`auto_joints` makes.
    :param frames: One frame per matrix.
    :param matrices: World matrices, each a sequence of 16 numbers or a
        ``pm.dt.Matrix``.
    """

    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma

    times = [om.MTime(float(frame), om.MTime.uiUnit()) for frame in frames]
    for matrix in matrices:
        flat = [value for row in matrix for value in row] \
            if hasattr(matrix, '__len__') and len(matrix) == 4 and hasattr(matrix[0], '__len__') \
            else list(matrix)
        if any(value != value or abs(value) > 1e12 for value in flat):
            # NaN or an absurd number written into an anim curve is not something
            # Maya recovers from - it propagates into the skinCluster and takes the
            # process with it. Refusing here names the joint instead.
            raise ValueError('Refusing to key {} with a transform that is not a number. '
                             'That means the solve produced a joint with nothing valid '
                             'behind it.'.format(node))
    channels = {'translate': ([], [], []), 'rotate': ([], [], []), 'scale': ([], [], [])}
    for matrix in matrices:
        flat = [float(value) for row in matrix for value in row] \
            if hasattr(matrix, '__len__') and len(matrix) == 4 and hasattr(matrix[0], '__len__') \
            else [float(value) for value in matrix]
        transform = om.MTransformationMatrix(om.MMatrix(flat))
        translate = transform.translation(om.MSpace.kWorld)
        # An angular curve stores radians, which is what MEulerRotation gives, so
        # there is no conversion here and there must not be one.
        rotate = transform.rotation(asQuaternion=False)
        scale = transform.scale(om.MSpace.kWorld)
        for axis in range(3):
            channels['translate'][axis].append(translate[axis])
            channels['rotate'][axis].append(rotate[axis])
            channels['scale'][axis].append(scale[axis])

    selection = om.MSelectionList()
    selection.add(str(node))
    dependency = om.MFnDependencyNode(selection.getDependNode(0))
    kinds = {'translate': oma.MFnAnimCurve.kAnimCurveTL,
             'rotate': oma.MFnAnimCurve.kAnimCurveTA,
             'scale': oma.MFnAnimCurve.kAnimCurveTU}

    for channel, perAxis in channels.items():
        for axis in range(3):
            plug = dependency.findPlug('{}{}'.format(channel, 'XYZ'[axis]), False)
            curve = oma.MFnAnimCurve()
            if plug.isDestination:
                # Second pass: the same curves, rekeyed, so the joints are not left
                # holding a mixture of the initial guess and the solved answer.
                curve.setObject(plug.source().node())
                for index in reversed(range(curve.numKeys)):
                    curve.remove(index)
            else:
                curve.create(plug, kinds[channel])
            curve.addKeys(times, perAxis[axis])


@_safe
def remove_solved_skin(mesh_or_joints=None, joint_prefix='poseJoint', skinned_suffix='_skinned'):
    """
    Take a solved skin back off: the skinned copy first, then the joints.

    **The order is the whole point.** Deleting a joint that is still an influence of
    a live skinCluster makes Maya recompute the deformation with an influence
    missing, and doing that forty times in a row - once per joint - is a documented
    way to bring it down. It did, during a joint-count sweep on a face. Delete the
    deformed geometry and its skinCluster first and there is nothing left holding a
    reference to the joints.

    :param mesh_or_joints: Optional explicit list of things to remove. None finds
        them by name, which is how :func:`auto_joints` names what it makes.
    :param str joint_prefix: Name prefix of the joints to remove.
    :param str skinned_suffix: Name suffix of the skinned copies to remove.
    :return: Response whose result is what was removed.
    :rtype: dict
    """

    meshes = []
    joints = []
    if mesh_or_joints:
        for each in ([mesh_or_joints] if isinstance(mesh_or_joints, str) else mesh_or_joints):
            if not cmds.objExists(each):
                continue
            (joints if cmds.nodeType(each) == 'joint' else meshes).append(each)
    else:
        meshes = [node for node in (cmds.ls('*{}*'.format(skinned_suffix),
                                            transforms=True) or [])
                  if cmds.listRelatives(node, shapes=True, type='mesh')]
        joints = cmds.ls('{}*'.format(joint_prefix), type='joint') or []

    removed = {'meshes': [], 'joints': []}
    for node in meshes:
        if cmds.objExists(node):
            cmds.delete(node)
            removed['meshes'].append(node)
    for node in joints:
        if cmds.objExists(node):
            cmds.delete(node)
            removed['joints'].append(node)

    return removed, ('Removed {} skinned mesh(es) and {} joint(s), in that order.'
                     .format(len(removed['meshes']), len(removed['joints'])))


def _pin_tag(node, tag, value):
    """
    Put a hidden string attribute on a node and set it.

    :param str node: The node to tag.
    :param str tag: Attribute name.
    :param str value: What to write.
    """

    if not cmds.attributeQuery(tag, node=node, exists=True):
        cmds.addAttr(node, longName=tag, dataType='string', hidden=True)
    cmds.setAttr('{}.{}'.format(node, tag), value, type='string')


def _pin_nodes(mesh=None):
    """
    Every node this tool made to pin joints with.

    :param mesh: Only pins reading this mesh. None finds all of them.
    :return: Node names.
    :rtype: list
    """

    wanted = None
    if mesh is not None:
        shape = _mesh_shape(mesh)
        wanted = str(shape.getParent() or shape).split('|')[-1]
    found = []
    for node in (cmds.ls('*.' + PIN_TAG, objectsOnly=True, long=True) or []):
        try:
            if wanted is None or cmds.getAttr('{}.{}'.format(node, PIN_TAG)) == wanted:
                found.append(node)
        except Exception:
            logger.debug('Could not read %s on %s.', PIN_TAG, node, exc_info=True)
    return found


def _pinned_joint(node):
    """
    The joint a pin node ends up driving, by following the connections.

    :param str node: One of our pin nodes.
    :return: The joint's name, or None.
    :rtype: str or None
    """

    seen = set()
    front = [node]
    while front:
        current = front.pop()
        if current in seen:
            continue
        seen.add(current)
        for plug in (cmds.listConnections(current, source=False, destination=True,
                                         plugs=True) or []):
            target = plug.split('.')[0]
            if plug.split('.', 1)[-1].startswith('offsetParentMatrix'):
                return cmds.ls(target, long=True)[0]
            front.append(target)
    return None


def _drop_pin(joint):
    """
    Take our pin off one joint and put its offsetParentMatrix back.

    :param str joint: The joint.
    :return: The nodes deleted.
    :rtype: list
    """

    plug = '{}.offsetParentMatrix'.format(joint)
    sources = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    if not sources:
        return []
    owner = sources[0].split('.')[0]
    if not cmds.attributeQuery(PIN_TAG, node=owner, exists=True):
        raise ValueError(
            '{}.offsetParentMatrix is driven by {}, which this tool did not make. Disconnect '
            'it yourself if you want the joint pinned - refusing to overwrite somebody '
            'else\'s rig.'.format(joint.split('|')[-1], owner))

    doomed = []
    front = [owner]
    seen = set()
    restore = None
    while front:
        current = front.pop()
        if current in seen or not cmds.objExists(current):
            continue
        seen.add(current)
        if not cmds.attributeQuery(PIN_TAG, node=current, exists=True):
            continue
        if cmds.attributeQuery(PIN_RESTORE, node=current, exists=True) and restore is None:
            try:
                restore = [float(each) for each in
                           cmds.getAttr('{}.{}'.format(current, PIN_RESTORE)).split()]
            except Exception:
                logger.debug('Could not read the stored offsetParentMatrix off %s.', current,
                             exc_info=True)
        if cmds.nodeType(current) != 'uvPin':
            doomed.append(current)
        front.extend(node.split('.')[0] for node in
                     (cmds.listConnections(current, source=True, destination=False) or []))

    cmds.disconnectAttr(sources[0], plug)
    if restore and len(restore) == 16:
        cmds.setAttr(plug, restore, type='matrix')
    else:
        cmds.setAttr(plug, [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0], type='matrix')
    for node in doomed:
        if cmds.objExists(node):
            cmds.delete(node)
    return sorted(doomed)


def _drop_empty_pins():
    """
    Delete our uvPin nodes that nothing reads any more.

    :return: The nodes deleted.
    :rtype: list
    """

    gone = []
    for node in _pin_nodes():
        if cmds.nodeType(node) != 'uvPin' or not cmds.objExists(node):
            continue
        if cmds.listConnections(node + '.outputMatrix', source=False, destination=True):
            continue
        cmds.delete(node)
        gone.append(node)
    return sorted(gone)


def _pin_geometry_plug(shape):
    """
    Which plug the pins should read the moving shape from.

    **The blendShape output, not the shape itself.** On a face the shape's own output is
    the end of the chain - blendShape, then the skinCluster the solved joints drive - and
    a pin reading that, driving a joint, driving that skinCluster, is a cycle. One frame
    later Maya is evaluating a loop and the whole thing is unusable. The blendShape's
    output is the deformation the joints are supposed to follow and nothing downstream of
    it, so that is what gets pinned to.

    :param shape: The mesh shape.
    :return: ``(plug, in_world)`` - the plug, and whether its data is already in world
        space.
    :rtype: tuple
    """

    shape = cmds.ls(str(shape), long=True)[0]
    wanted = cmds.ls(shape, long=True)
    for node in (cmds.listHistory(shape, pruneDagObjects=True) or []):
        if cmds.nodeType(node) != 'blendShape':
            continue
        geometry = cmds.deformer(node, q=True, geometry=True) or []
        indices = cmds.deformer(node, q=True, geometryIndices=True) or []
        for geo, index in zip(geometry, indices):
            if cmds.ls(geo, long=True) == wanted:
                return '{}.outputGeometry[{}]'.format(node, index), False
    return '{}.worldMesh[0]'.format(shape), True


def _refuse_pin_cycle(plug, joints):
    """
    Refuse to pin to geometry that the joints themselves deform.

    :param str plug: The geometry plug the pins would read.
    :param list joints: The joints being pinned, as full paths.
    :raises ValueError: When one of the joints already deforms that geometry.
    """

    wanted = set(joints)
    for node in (cmds.listHistory(plug.split('.')[0]) or []):
        if cmds.nodeType(node) != 'skinCluster':
            continue
        influences = cmds.ls(cmds.skinCluster(node, q=True, influence=True) or [], long=True)
        clash = sorted(wanted.intersection(influences))
        if clash:
            raise ValueError(
                '{} is deformed by {}, which {} already influences. Pinning those joints to it '
                'would make the pin drive the joint drive the deformation drive the pin - a '
                'cycle. Pin to the mesh that carries the blendShapes, not to the one the '
                'solved skin is on.'.format(
                    plug, node, ', '.join(each.split('|')[-1] for each in clash[:4])))


@_safe
@_one_undo
@_keep_selection
def pin_joints(mesh, joints, rotate=False, source=None, rest_frame=None, name=None):
    """
    Stick joints to a moving mesh, each one following the surface it sits on.

    This is the other half of driving a face the way a face is usually driven: the
    blendShapes stay on the original mesh, the joints ride along on its surface, and the
    skin those joints deform is on a second mesh. :func:`skin_from_poses` and
    :func:`add_to_skin` make that second mesh; this is what makes the joints move in the
    first place, so a solve has something to fit.

    Each joint is pinned to the closest point on the mesh, by UV, through one `uvPin`.
    UV rather than vertex number, so it holds up if the mesh is later retopologised in a
    way that keeps its layout.

    **The rest pose does not move.** The pin drives `offsetParentMatrix` with the surface
    point's movement SINCE the frame you pinned on, not with its position - so at that
    frame the offset is identity and every joint is exactly where the rigger put it. The
    joint's own translate and rotate are left alone and still work, which means a
    rigger's existing offsets and an animator's keys both survive the pin.

    **A joint far from the surface gets a meaningless answer.** Closest-point is the right
    question for a cheek joint a few millimetres under the skin and the wrong one for an
    eye joint an inch inside the head: that one pins to whatever happens to be nearest,
    usually the inside of an eyelid, and then follows it. The distance is measured and the
    worst offenders are named in the message rather than refused, because only the rigger
    knows which joints are meant to sit off the surface.

    :param mesh: The mesh the joints should follow - the one with the blendShapes on it.
    :param joints: The joints to pin.
    :param bool rotate: Also let the surface's tangent frame rotate the joints. Off by
        default: rotation from a tangent frame twists wherever the UVs do, and a face rig
        usually wants the joints' orientation kept. Turning it on bakes the joints' rest
        local matrix into the pin, so their current rotate values become the rest.
    :param str source: The geometry plug to read, when the automatic choice is wrong.
        A plug whose name contains "world" is taken as world-space data.
    :param float rest_frame: The frame to measure the rest pose on. None uses the current
        frame.
    :param str name: Base name for the uvPin. None names it after the mesh.
    :return: Response whose result carries the pin, the joints, and the measurements.
    :rtype: dict
    """

    import maya.api.OpenMaya as om

    shape = _mesh_shape(mesh)
    transform = shape.getParent() or shape
    names = _joint_names(joints)

    with _AtFrame(rest_frame):
        if source:
            plug, in_world = source, 'world' in source.rsplit('.', 1)[-1].lower()
        else:
            plug, in_world = _pin_geometry_plug(shape)
        if not cmds.objExists(plug.split('.')[0]):
            raise ValueError('{} does not exist.'.format(plug))
        _refuse_pin_cycle(plug, names)

        # Take the joints that are already pinned off first, so re-running replaces the
        # network rather than stacking a second one on top of it.
        replaced = []
        for joint in names:
            if _drop_pin(joint):
                replaced.append(joint)
        _drop_empty_pins()

        holder = om.MSelectionList()
        holder.add(plug)
        fn = om.MFnMesh(holder.getPlug(0).asMObject())
        uv_set = fn.currentUVSetName()
        if not uv_set or not fn.numUVs(uv_set):
            raise ValueError(
                '{} has no UVs in its current UV set, and a uvPin finds its point on the '
                'surface by UV. Lay the mesh out first.'.format(
                    str(transform).split('|')[-1]))
        to_world = om.MMatrix() if in_world else om.MMatrix(
            cmds.getAttr('{}.worldMatrix[0]'.format(transform)))
        to_local = to_world.inverse()

        stem = name or str(transform).split('|')[-1]
        tag = str(transform).split('|')[-1]
        pin = cmds.createNode('uvPin', name='{}_uvPin'.format(stem), skipSelect=True)
        _pin_tag(pin, PIN_TAG, tag)
        cmds.connectAttr(plug, pin + '.deformedGeometry', force=True)
        original = cmds.deformableShape(str(shape), originalGeometry=True) or []
        if original and original[0] and cmds.objExists(original[0].split('.')[0]):
            cmds.connectAttr(original[0], pin + '.originalGeometry', force=True)
        try:
            cmds.setAttr(pin + '.uvSetName', uv_set, type='string')
        except Exception:
            logger.debug('Could not set the uvPin\'s UV set to %s.', uv_set, exc_info=True)

        # Every coordinate first, then the matrices: a uvPin recomputes when its
        # coordinate array changes, and reading outputMatrix[i] before the array is
        # complete can hand back a stale frame.
        rest = []
        targets = []
        surface = []
        for index, joint in enumerate(names):
            pivot = om.MPoint(cmds.xform(joint, q=True, worldSpace=True, translation=True))
            closest, _face = fn.getClosestPoint(om.MPoint(pivot * to_local),
                                                om.MSpace.kObject)
            u, v = fn.getUVAtPoint(closest, om.MSpace.kObject, uv_set)[:2]
            cmds.setAttr('{}.coordinate[{}].coordinateU'.format(pin, index), u)
            cmds.setAttr('{}.coordinate[{}].coordinateV'.format(pin, index), v)
            rest.append(pivot)
            targets.append(om.MPoint(closest * to_world))
            surface.append(targets[-1].distanceTo(pivot))

        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        landed = []
        for index, joint in enumerate(names):
            short = joint.split('|')[-1]
            pinned = om.MMatrix(cmds.getAttr('{}.outputMatrix[{}]'.format(pin, index)))
            world = pinned * to_world
            # Against the point the pin was MADE for, not against the joint: a joint that
            # deliberately sits off the surface is reported separately, and confusing the
            # two would cry overlapping UVs at every eye joint in the business.
            landed.append(om.MPoint(world[12], world[13], world[14])
                          .distanceTo(targets[index]))

            parents = cmds.listRelatives(joint, parent=True, fullPath=True) or []
            parent_world = om.MMatrix(cmds.getAttr('{}.worldMatrix[0]'.format(parents[0]))) \
                if parents else om.MMatrix()
            parent_inverse = parent_world.inverse()

            mult = cmds.createNode('multMatrix', name='{}_pinMult'.format(short),
                                   skipSelect=True)
            pick = cmds.createNode('pickMatrix', name='{}_pinPick'.format(short),
                                   skipSelect=True)
            for node in (mult, pick):
                _pin_tag(node, PIN_TAG, tag)
            _pin_tag(mult, PIN_RESTORE,
                     ' '.join('{:.17g}'.format(each) for each in
                              cmds.getAttr('{}.offsetParentMatrix'.format(joint))))

            if rotate:
                # The whole frame, offset so that this frame comes out as it is now:
                #   opm = restLocal^-1 * restWorld * pinRest^-1 * pin * parentWorld^-1
                local = om.MMatrix(cmds.getAttr('{}.matrix'.format(joint)))
                rest_world = om.MMatrix(cmds.getAttr('{}.worldMatrix[0]'.format(joint)))
                before = local.inverse() * rest_world * world.inverse()
                slots = [before, None, parent_inverse] if in_world else \
                    [before, None, to_world, parent_inverse]
            else:
                # Position only, as a movement since now:
                #   opm = translate((pin.t - pinRest.t) * parentWorld^-1 rotation)
                # which is identity at this frame however the rig is built.
                moved = list(identity)
                moved[12:15] = [-world[12], -world[13], -world[14]]
                turned = [parent_inverse[each] for each in range(16)]
                turned[12:15] = [0.0, 0.0, 0.0]
                offset = om.MMatrix(moved) * om.MMatrix(turned)
                slots = [None, offset] if in_world else [None, to_world, offset]

            for slot, value in enumerate(slots):
                plug_name = '{}.matrixIn[{}]'.format(mult, slot)
                if value is None:
                    cmds.connectAttr('{}.outputMatrix[{}]'.format(pin, index), plug_name)
                elif value is to_world and not in_world:
                    cmds.connectAttr('{}.worldMatrix[0]'.format(transform), plug_name)
                else:
                    cmds.setAttr(plug_name, [value[each] for each in range(16)],
                                 type='matrix')

            cmds.setAttr(pick + '.useTranslate', True)
            cmds.setAttr(pick + '.useRotate', bool(rotate))
            cmds.setAttr(pick + '.useScale', False)
            cmds.setAttr(pick + '.useShear', False)
            cmds.connectAttr(mult + '.matrixSum', pick + '.inputMatrix')
            cmds.connectAttr(pick + '.outputMatrix',
                             '{}.offsetParentMatrix'.format(joint), force=True)

        # Measured, not assumed: the joints must be exactly where they were.
        drift = 0.0
        worst_joint = names[0]
        for index, joint in enumerate(names):
            moved = om.MPoint(cmds.xform(joint, q=True, worldSpace=True,
                                         translation=True)).distanceTo(rest[index])
            if moved > drift:
                drift, worst_joint = moved, joint

    cycles = []
    try:
        cycles = cmds.cycleCheck(names, all=False, list=True) or []
    except Exception:
        logger.debug('Could not run a cycle check.', exc_info=True)

    far = sorted(((distance, names[index].split('|')[-1])
                  for index, distance in enumerate(surface)), reverse=True)
    mismatch, mismatch_joint = max(
        ((distance, names[index]) for index, distance in enumerate(landed)),
        default=(0.0, names[0]))
    result = {'pin': pin, 'joints': names, 'reads': plug, 'rotate': bool(rotate),
              'replaced': replaced, 'worst_rest_drift': drift,
              'worst_rest_drift_joint': worst_joint.split('|')[-1],
              'worst_pin_mismatch': mismatch,
              'worst_pin_mismatch_joint': mismatch_joint.split('|')[-1],
              'worst_surface_distance': far[0][0] if far else 0.0,
              'far_from_surface': [name for distance, name in far
                                   if distance > PIN_SURFACE_WARNING],
              'surface_distance': {names[index].split('|')[-1]: distance
                                   for index, distance in enumerate(surface)},
              'cycles': len(cycles)}

    message = ('Pinned {} joint(s) to {} through {}; they follow it by {}. The joints did not '
               'move: worst rest drift {:.3e} scene units ({}).'.format(
                   len(names), str(transform).split('|')[-1], plug,
                   'position and rotation' if rotate else 'position only',
                   drift, worst_joint.split('|')[-1]))
    if replaced:
        message += '  {} joint(s) were already pinned and were re-pinned.'.format(len(replaced))
    if result['far_from_surface']:
        message += ('  {} joint(s) sit more than {:g} units off the surface and are pinned to '
                    'whatever was nearest them, which is probably not what you want: {}.'
                    .format(len(result['far_from_surface']), PIN_SURFACE_WARNING,
                            ', '.join(result['far_from_surface'][:6])))
    if result['worst_pin_mismatch'] > PIN_MISMATCH_WARNING:
        message += ('  WARNING: the pin for {} sits {:.3g} units from the point on the surface it '
                    'was made for. A small gap is the quad it landed in being curved; this much '
                    'usually means the UVs overlap there, and the pin will follow the wrong bit '
                    'of surface.'.format(result['worst_pin_mismatch_joint'],
                                         result['worst_pin_mismatch']))
    if cycles:
        message += '  WARNING: {} cycle(s) reported. That has to be cleared.'.format(len(cycles))
    return result, message


@_safe
@_one_undo
@_keep_selection
def unpin_joints(joints=None, mesh=None):
    """
    Take this tool's pins off again, and put the joints' offsets back as they were.

    :param joints: The joints to unpin. None takes every joint pinned to ``mesh``, or
        every joint this tool pinned at all when that is None too.
    :param mesh: Only pins reading this mesh.
    :return: Response whose result names what was unpinned.
    :rtype: dict
    """

    if joints:
        wanted = _joint_names(joints)
    else:
        wanted = []
        for node in _pin_nodes(mesh):
            joint = _pinned_joint(node)
            if joint and joint not in wanted:
                wanted.append(joint)

    unpinned = []
    removed = []
    for joint in wanted:
        gone = _drop_pin(joint)
        if gone:
            unpinned.append(joint)
            removed.extend(gone)
    removed.extend(_drop_empty_pins())

    result = {'joints': unpinned, 'nodes_removed': sorted(removed)}
    return result, ('Unpinned {} joint(s) and removed {} node(s); their offsetParentMatrix '
                    'is back as it was.'.format(len(unpinned), len(removed)))
