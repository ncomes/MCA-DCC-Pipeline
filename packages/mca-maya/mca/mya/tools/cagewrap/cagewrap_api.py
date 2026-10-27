"""
Deform a mesh with a cage wrapped around it.

A low-resolution cage around a high-resolution mesh: move the cage, the mesh follows.
For squash and stretch a joint cannot do, for bending a prop that has no skeleton, and
for driving dense cloth from something an animator can actually grab.

What makes this one different from a lattice or Maya's wrap
----------------------------------------------------------
It carries the cage's face NORMALS as well as its vertex positions (Green coordinates,
Lipman et al. 2008). A deformer built from positions alone has no idea which way the
surface is facing, so twisting or shearing the cage slides the enclosed shape sideways.
Measured on a sheared cage, worst local skew:

    carrying the normals      0.000047
    positions only            0.181

Three thousand times less, which is the difference between a bend that looks like a
bend and one that looks like a mistake.

The workflow
------------
1. :func:`cage_from_mesh` builds a cage for you, or model your own - any closed mesh,
   quads are fine.
2. :func:`wrap` binds the mesh to it. The cage you get back is the one to animate; a
   hidden copy of it is kept as the rest pose, so there is nothing to freeze and
   nothing to remember not to touch.
3. Animate, deform, or simulate the cage. Anything that moves it works.
4. :func:`bake_to_skin` turns the result into joints and skin weights, through the
   pose skinner, for an engine that cannot run any of this.

What to know before running it
------------------------------
**The cage has to be closed.** The coordinates are an integral over a surface that
encloses something, so a cage with a hole in it is not a cage. It is checked before
anything is bound and refused by name, and the deformer passes the mesh through
untouched rather than exploding it.

**Points outside the cage still work, but they are guessing.** Anything poking through
is bound to its closest cage triangle, which is exact for a rigid or affine move of
that triangle and approximate for everything else. The count comes back in the report,
because a cage that misses part of the mesh is usually a mistake rather than a choice.

**Stretch is a real decision.** At 0 the enclosed shape keeps its thickness however
much the cage is stretched, which is what a bending gun barrel wants. At 1 it thickens
and thins with the cage, which is what squash and stretch means. Neither is right.

:Requires: the mcaCageWrap plug-in
:Side effects: Creates a deformer and a hidden rest cage; :func:`bake_to_skin` creates
    joints and a skinCluster.
"""

# python imports
import functools
import math

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

PLUGIN_NAME = 'mcaCageWrap'
NODE_TYPE = 'mcaCageWrap'

#: Tag put on a rest cage this tool made, naming the cage it was copied from.
#:
#: The rest cage is bookkeeping, not art: it is a frozen snapshot of where the cage was
#: when the mesh was bound, and the artist should never have to think about it. Tagging
#: it means the tool can find and clean up exactly its own, the same way the pose
#: skinner finds its own copies, rather than guessing from a name and one day deleting
#: something somebody modelled.
REST_TAG = 'mcaCageWrapRestOf'

#: Tag put on a cage this tool generated: the mesh it was built around, and by which
#: builder.
#:
#: The builder matters, and it took a real asset to notice. Both builders used to write
#: just the mesh's name, and both delete their own previous output before making a new one -
#: so building a cage from the skeleton and then one from the shape left only the second,
#: silently. Two different answers to the same question are things a rigger wants side by
#: side to choose between.
CAGE_TAG = 'mcaCageWrapCageFor'

#: How far out a generated cage is pushed, as a fraction of the mesh's bounding
#: diagonal.
#:
#: Two percent, from measurement rather than taste: it is the smallest offset that put
#: every vertex of a retopologised head, hand and cylinder inside the cage on the first
#: try. Too small and the mesh pokes through, which costs accuracy exactly where the
#: silhouette is; too large and the cage stops following the shape, which costs control.
#: It grows automatically when points are left outside.
DEFAULT_OFFSET = 0.02

#: The most memory a bind may be estimated to need before `wrap` refuses, in megabytes.
#:
#: **A cage is a LOW-resolution shell, and there is no cheap way to find out you forgot
#: that.** The bind holds one float per cage element per mesh point, so the cost is the
#: product of the two: a 13,568-point prop on a 68-element bone cage is 3.5 MB and binds in
#: a tenth of a second, while the same prop on a cage of its own resolution is **1.4 GB**
#: and a bind that looks exactly like a hang. Found that way, on a real teapot, when a
#: retopology silently failed and left a full-resolution duplicate behind for the cage.
#:
#: Expressed as MEMORY rather than as a ratio, and that took a second attempt. The first
#: version refused any cage with more than a tenth of an element per mesh point, which
#: reads sensibly and is wrong: a 242-point test sphere in a 276-element cage is a
#: perfectly good cage and trips that rule instantly, while the number that actually hurts
#: is the product.
#:
#: The ceiling comes from the heaviest bind that is still a reasonable thing to ask for -
#: a 100,000-point cloth mesh on a 250-element cage, which is 95 MB - with headroom, rather
#: than from a round number. 512 was the first guess and sat just above a case worth
#: refusing (8,012 points on a duplicate of themselves is 492 MB), which is how the wrong
#: kind of threshold announces itself.
MAX_BIND_MEGABYTES = 256.0

#: How far a cage may sit from the mesh, as a fraction of the mesh's bounding diagonal,
#: before it is too loose to be worth posing. A good cage on a lumpy sphere measured 0.51
#: units on a 20-unit shape; the runaway cage on a human body measured a median 67.55 on a
#: 234-unit diagonal, which is 0.29. Ten per cent is generous and still catches that by a
#: factor of three.
LOOSE_CAGE_FRACTION = 0.10

#: Rounds of relaxing a generated cage gets. **Zero, from measurement.**
#:
#: Relaxing was added on the assumption that a retopologised cage arrives covered in the
#: mesh's own small detail and wants smoothing. Swept on a lumpy sphere at 60, 140 and
#: 300 cage faces, it is a trade rather than a win - each round takes about 10% off the
#: roughness and pushes the cage about a quarter of its base offset further out, because
#: averaging pulls points inward and the containment loop then has to push everything
#: back:
#:
#:     relax   offset   roughness   bind error
#:     0       0.262    0.0265      4.8e-06
#:     1       0.326    0.0234      2.4e-06
#:     2       0.385    0.0209      2.1e-06
#:     4       0.497    0.0174      2.3e-06
#:     8       0.693    0.0137      3.8e-08
#:
#: A cage further from the mesh is a cage with less control over it, so the default is to
#: leave it alone. What that table DOES show, and is worth knowing: the bind is more
#: accurate when there is more clearance, because the coordinates are singular at the
#: cage surface. The knob to reach for if a cage is too detailed is the face count.
DEFAULT_RELAX = 0

#: Cage faces a generated cage aims for.
#:
#: 200 is enough to follow a limbed shape and few enough to grab. The bind is
#: O(mesh points x cage faces), so this number is the one that decides what binding
#: costs - 200 faces on a 20,000-point mesh is about a second.
DEFAULT_CAGE_FACES = 200


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
    Turn an exception into a response rather than a traceback in the script editor.

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


def _one_undo(func):
    """
    Make everything the call does undo in one step.

    :param func: The function to wrap.
    :return: The wrapped function.
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
    Put the selection back. Several of the commands used in here change it.

    :param func: The function to wrap.
    :return: The wrapped function.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        was = cmds.ls(selection=True, long=True) or []
        try:
            return func(*args, **kwargs)
        finally:
            alive = [node for node in was if cmds.objExists(node)]
            if alive:
                cmds.select(alive, replace=True)
            else:
                cmds.select(clear=True)

    return wrapper


def plugin_is_available():
    """
    :return: ``(True, '')`` when the plug-in is loaded, or ``(False, why not)``.
    :rtype: tuple
    """

    try:
        from mca.mya.plugins import loader
    except Exception as exc:
        return False, 'Could not reach the plug-in loader: {}'.format(exc)

    if NODE_TYPE in (cmds.allNodeTypes() or []):
        return True, ''
    try:
        if loader.load_cage_wrap_plugin():
            return True, ''
    except Exception as exc:
        return False, 'The {} plug-in would not load: {}'.format(PLUGIN_NAME, exc)
    return False, 'The {} plug-in is not loaded.'.format(PLUGIN_NAME)


def _require_plugin():
    """
    :raises RuntimeError: When the plug-in is not available.
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


def _transform_of(shape):
    """
    :param shape: A mesh shape.
    :return: Its transform's full path.
    :rtype: str
    """

    shape = str(_mesh_shape(shape))
    return (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]


def _tag(node, tag, value):
    """
    Put a hidden string attribute on a node and set it.

    :param str node: The node to tag.
    :param str tag: Attribute name.
    :param str value: What to write.
    """

    if not cmds.attributeQuery(tag, node=node, exists=True):
        cmds.addAttr(node, longName=tag, dataType='string', hidden=True)
    cmds.setAttr('{}.{}'.format(node, tag), value, type='string')


def _tagged(tag, value=None):
    """
    :param str tag: The attribute to look for.
    :param str value: Only nodes whose tag reads this. None finds all of them.
    :return: Node names.
    :rtype: list
    """

    found = []
    for node in (cmds.ls('*.' + tag, objectsOnly=True, long=True) or []):
        try:
            if value is None or cmds.getAttr('{}.{}'.format(node, tag)) == value:
                found.append(node)
        except Exception:
            logger.debug('Could not read %s on %s.', tag, node, exc_info=True)
    return found


def _diagonal(shape):
    """
    :param shape: A mesh.
    :return: The length of its bounding box's diagonal, in world units.
    :rtype: float
    """

    box = cmds.exactWorldBoundingBox(str(_transform_of(shape)))
    return ((box[3] - box[0]) ** 2 + (box[4] - box[1]) ** 2 + (box[5] - box[2]) ** 2) ** 0.5


def existing_skin(mesh):
    """
    The skinCluster on a mesh, if it has one.

    :param mesh: The mesh to look at.
    :return: The skinCluster's name, or None.
    :rtype: str or None
    """

    shape = str(_mesh_shape(mesh))
    found = cmds.ls(cmds.listHistory(shape) or [], type='skinCluster') or []
    return found[0] if found else None


def border_edges(mesh):
    """
    How many border edges a mesh has. Zero means closed, which is what a cage has to be.

    :param mesh: The mesh to look at.
    :return: The number of border edges.
    :rtype: int
    """

    shape = str(_mesh_shape(mesh))
    cmds.select(shape, replace=True)
    try:
        cmds.polySelectConstraint(mode=3, type=0x8000, where=1)
        edges = cmds.ls(selection=True, flatten=True) or []
        return len([edge for edge in edges if '.e[' in edge])
    finally:
        cmds.polySelectConstraint(mode=0, where=0)
        cmds.select(clear=True)


def points_outside(mesh, cage):
    """
    How many of the mesh's points fall outside the cage.

    Closest point and its normal: a point on the inside of a closed surface is on the
    negative side of the surface's normal there. Cheap, and independent of the bind, so
    a cage can be judged before anything is bound to it.

    :param mesh: The mesh.
    :param cage: The cage.
    :return: ``(count, worst distance outside)``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(cage)))
    cage_fn = om.MFnMesh(holder.getDagPath(0))

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(mesh)))
    mesh_fn = om.MFnMesh(holder.getDagPath(0))

    outside = 0
    worst = 0.0
    for point in mesh_fn.getPoints(om.MSpace.kWorld):
        closest, normal, _face = cage_fn.getClosestPointAndNormal(om.MPoint(point),
                                                                 om.MSpace.kWorld)
        away = om.MVector(point - closest)
        if away * normal > 0.0:
            outside += 1
            worst = max(worst, away.length())
    return outside, worst


def fit_to_mesh(mesh, cage):
    """
    How closely a cage hugs the mesh, rather than merely containing it.

    Containment on its own says nothing about whether a cage is usable: a sphere of radius
    200 contains a man perfectly and is worthless to pose. **Nothing measured this, which
    is how a cage sitting a median 67 units off a 38-unit-deep body passed every check the
    builder had** - it was closed, and the whole mesh was inside it.

    :param mesh: The mesh.
    :param cage: The cage.
    :return: ``(median distance, worst distance, fraction of the mesh's diagonal)``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(mesh)))
    mesh_fn = om.MFnMesh(holder.getDagPath(0))

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(cage)))
    cage_fn = om.MFnMesh(holder.getDagPath(0))

    spans = []
    for point in cage_fn.getPoints(om.MSpace.kWorld):
        closest = mesh_fn.getClosestPoint(om.MPoint(point), om.MSpace.kWorld)[0]
        spans.append(om.MVector(point - closest).length())
    if not spans:
        return 0.0, 0.0, 0.0
    spans.sort()
    median = spans[len(spans) // 2]
    diagonal = _diagonal(mesh) or 1.0
    return median, spans[-1], median / diagonal


def roughness(mesh):
    """
    How lumpy a mesh is: how far its points sit from the average of their neighbours,
    as a fraction of its own size.

    Worth measuring rather than eyeballing, because it is what relaxing a cage is for
    and because a cage's own normals are half of what the deformation is built from - a
    noisy cage makes a noisy deformation, whatever the silhouette looks like.

    :param mesh: The mesh to measure.
    :return: The worst distance, over the bounding diagonal.
    :rtype: float
    """

    import maya.api.OpenMaya as om

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(mesh)))
    shape = om.MFnMesh(holder.getDagPath(0))
    points = shape.getPoints(om.MSpace.kWorld)

    neighbours = [[] for _ in range(len(points))]
    edges = om.MItMeshEdge(holder.getDagPath(0))
    while not edges.isDone():
        first = edges.vertexId(0)
        second = edges.vertexId(1)
        neighbours[first].append(second)
        neighbours[second].append(first)
        edges.next()

    size = _diagonal(mesh) or 1.0
    worst = 0.0
    for index, point in enumerate(points):
        if not neighbours[index]:
            continue
        average = om.MPoint(0.0, 0.0, 0.0)
        for other in neighbours[index]:
            average += om.MVector(points[other])
        average = om.MPoint(om.MVector(average) / float(len(neighbours[index])))
        worst = max(worst, (om.MVector(point - average)).length() / size)
    return worst


def symmetrise(mesh, axis='x', tolerance=None):
    """
    Make a mesh symmetrical about an axis, in place, without changing its topology.

    Every point is paired with the point closest to its own mirror image, and each
    mutual pair is moved to the average of the two. A point whose mirror is itself is
    snapped onto the plane.

    **Why a cage wants this even when the mesh is not symmetrical.** The cage is what an
    animator grabs. A cage where the left cheek has five points and the right has six,
    each a little off from its opposite, cannot be posed symmetrically at all - every
    symmetrical shape has to be built twice by hand. Retopology never comes out
    symmetrical on its own.

    :param mesh: The mesh to alter.
    :param str axis: 'x', 'y' or 'z'.
    :param float tolerance: How close a mirror has to be to count as a pair. None takes
        a fiftieth of the bounding diagonal.
    :return: ``(pairs matched, points left unpaired, worst distance moved)``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(mesh)))
    path = holder.getDagPath(0)
    shape = om.MFnMesh(path)
    points = shape.getPoints(om.MSpace.kWorld)

    which = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]
    limit = tolerance if tolerance is not None else (_diagonal(mesh) or 1.0) / 50.0

    def mirrored(point):
        values = [point[0], point[1], point[2]]
        values[which] = -values[which]
        return om.MPoint(values[0], values[1], values[2])

    # Closest point to each mirror image. O(n^2), and n is a few hundred - a cage, not a
    # mesh - so a spatial structure would cost more to build than it saves.
    partner = []
    for index in range(len(points)):
        target = mirrored(points[index])
        best = -1
        best_distance = 0.0
        for other in range(len(points)):
            distance = (om.MVector(points[other] - target)).length()
            if best < 0 or distance < best_distance:
                best = other
                best_distance = distance
        partner.append(best if best_distance <= limit else -1)

    moved = list(points)
    pairs = 0
    unpaired = 0
    worst = 0.0
    for index in range(len(points)):
        other = partner[index]
        if other < 0:
            unpaired += 1
            continue
        if partner[other] != index:
            # Not mutual, so this is a guess rather than a pair. Left alone.
            unpaired += 1
            continue
        if other < index:
            continue
        if other == index:
            # Its own mirror: it belongs on the plane.
            values = [points[index][0], points[index][1], points[index][2]]
            values[which] = 0.0
            moved[index] = om.MPoint(values[0], values[1], values[2])
            worst = max(worst, (om.MVector(moved[index] - points[index])).length())
            pairs += 1
            continue

        average = om.MPoint((om.MVector(points[index]) +
                             om.MVector(mirrored(points[other]))) / 2.0)
        moved[index] = average
        moved[other] = mirrored(average)
        worst = max(worst, (om.MVector(moved[index] - points[index])).length(),
                    (om.MVector(moved[other] - points[other])).length())
        pairs += 1

    shape.setPoints(moved, om.MSpace.kWorld)
    return pairs, unpaired, worst


def grow_to_contain(mesh, cage, step, attempts=3):
    """
    Find the push, along the cage's own normals, that leaves the least of the mesh outside.

    **Containment is not monotonic in push distance, and the version this replaces assumed
    it was.** It read how far the worst point was sticking out, pushed by that much plus a
    fifth, and repeated - which is only sound if pushing harder always helps. It does not.
    A uniform normal offset self-intersects wherever the surface's concave radius is
    smaller than the offset, and on a character the armpits, the crotch and the gaps
    between fingers are all a couple of units across. Past that, the offset surface folds
    through itself and *more* of the mesh reads as outside, not less.

    Measured on a 16,747-point human body against a 2,000-face retopologised shell, by
    push distance - points outside, worst distance out, and the cage's own surface area::

        0.0    14367    4.05     17824
        1.0     2101    3.08     20968
        1.5     2095    2.61     22576      <- best
        2.0     2837    2.53     24226
        4.0     3871    5.82     31402
        8.0     7457    9.06     49018
       16.0    11186   15.85    100007
       32.0    15222   22.62    276632

    The old loop walked straight up that table. Each pass made ``worst`` bigger, which made
    the next push bigger, so it ran away: on that body it pushed **92.01 units** before it
    ran out of attempts, leaving a cage 209 units deep around a man 38 units deep, with a
    median cage point sitting 67 units from the nearest skin. Fifteen-fold area growth is
    the surface folding, not expanding.

    So this searches a ladder of distances instead of extrapolating, and keeps the best one
    it measured. It can return a push of zero, and it never returns a cage that contains
    less of the mesh than the one it was handed.

    :param mesh: The mesh that has to end up inside.
    :param cage: The cage to push. Altered in place.
    :param float step: The middle of the range to search, in scene units.
    :param int attempts: How many distances above ``step`` to try as well.
    :return: ``(pushed, points still outside, worst distance outside, distances tried)``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(cage)))
    path = holder.getDagPath(0)
    rest = om.MFnMesh(path).getPoints(om.MSpace.kWorld)

    def restore():
        om.MFnMesh(path).setPoints(rest, om.MSpace.kWorld)

    def push(distance):
        cmds.select(str(cage), replace=True)
        cmds.polyMoveVertex(str(cage) + '.vtx[*]', localTranslate=(0.0, 0.0, distance),
                            constructionHistory=False)

    # Below `step` as well as above it. The best answer on the body above was a third of
    # the default first push, and a ladder that only ever grows can never find that.
    fractions = [0.125, 0.25, 0.5, 0.75, 1.0]
    fractions += [1.5 * (1.6 ** n) for n in range(max(int(attempts), 0))]

    best_push, (best_outside, best_worst) = 0.0, points_outside(mesh, cage)
    tried = 0
    for fraction in fractions:
        distance = step * fraction
        if distance <= 0.0:
            continue
        restore()
        push(distance)
        tried += 1
        outside, worst = points_outside(mesh, cage)
        if (outside, worst) < (best_outside, best_worst):
            best_push, best_outside, best_worst = distance, outside, worst

    restore()
    if best_push > 0.0:
        push(best_push)
    return best_push, best_outside, best_worst, tried


@_safe
@_one_undo
@_keep_selection
def example_scene(name='cagewrap_example', frames=48, build=True):
    """
    Build a scene that shows what the deformer is for, from nothing.

    **Generated rather than shipped.** A sample saved as a .ma carries a
    ``requires -nodeType`` line naming one plug-in build, so it opens in the Maya it was
    saved from and warns in every other one - which is how the mesh tiler's sample ended
    up locked to 2025. Nothing here is loaded from disk, so it works in every version the
    plug-in builds for and cannot rot.

    What it makes: a lumpy prop with no skeleton, a cage built from its own shape, the
    prop wrapped to the cage, and the cage keyed through a squash-and-stretch bounce.
    Press play. The point it makes in one shot is that a skeleton cannot do this - there
    is no skeleton - and that the handles are few enough to grab.

    ``stretch`` is left at 1.0, because thickness following the cage *is* squash and
    stretch; at 0 the prop would keep its thickness and the bounce would read as a slide.

    :param str name: What to call the prop. The cage and the wrap are named after it.
    :param int frames: How long the bounce runs. The playback range is set to match.
    :param bool build: False lays out the geometry and stops, for a before-and-after shot.
    :return: ``(what was made, a sentence about it)``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om

    for previous in (name, '{}_cage'.format(name), '{}_cage_rest'.format(name),
                     '{}_squash'.format(name)):
        if cmds.objExists(previous):
            cmds.delete(previous)

    # A prop with enough detail that nobody mistakes it for a primitive, and enough
    # roundness that the shape builder has an easy time of it - this scene is about the
    # deformer, not about the cage builder's hard cases.
    prop = cmds.polySphere(name=name, radius=10.0, subdivisionsX=64, subdivisionsY=64,
                           constructionHistory=False)[0]
    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(prop)))
    fn = om.MFnMesh(holder.getDagPath(0))
    points = fn.getPoints(om.MSpace.kObject)
    for index, point in enumerate(points):
        height = (point.y + 10.0) / 20.0
        # a waist, a flared base, and a shallow ripple so the silhouette has something to
        # say when it squashes
        profile = 1.0 - 0.28 * math.sin(math.pi * height) + 0.16 * (1.0 - height) ** 2
        ripple = 1.0 + 0.045 * math.sin(height * math.pi * 7.0)
        scale = profile * ripple
        points[index] = om.MPoint(point.x * scale, point.y, point.z * scale)
    fn.setPoints(points, om.MSpace.kObject)
    box = cmds.exactWorldBoundingBox(prop)
    cmds.move(0.0, -box[1], 0.0, prop, relative=True)
    cmds.makeIdentity(prop, apply=True, translate=True)
    cmds.delete(prop, constructionHistory=True)

    made = {'mesh': prop, 'vertices': cmds.polyEvaluate(prop, vertex=True),
            'faces': cmds.polyEvaluate(prop, face=True)}
    if not build:
        return made, ('Laid out {} - {} points, no skeleton, nothing bound. Build a cage and '
                      'wrap it to see the other half.'
                      .format(prop, made['vertices']))

    # Both of these are @_safe, so they hand back a response rather than raising - which
    # means a failure here would otherwise sail on and fall over somewhere less obvious.
    answer = cage_from_mesh(prop, faces=120, name='{}_cage'.format(name))
    if not answer['ok']:
        raise ValueError('The example could not build its cage: {}'.format(answer['message']))
    built = answer['result']
    cage = built['cage']

    answer = wrap(prop, cage=cage, stretch=1.0)
    if not answer['ok']:
        raise ValueError('The example could not wrap its prop: {}'.format(answer['message']))
    wrapped = answer['result']

    # The bounce is driven by MOVING CAGE POINTS, not by scaling the cage's transform.
    #
    # **Scaling the transform is the obvious way to do it and it reads as broken.** Green
    # coordinates are quasi-conformal: they preserve local shape, so a uniform scale of the
    # cage comes through exactly while a non-uniform one is deliberately damped. Measured on
    # this prop, scaling the cage uniformly by 1.5 and by 0.6 moved the mesh by exactly 1.50
    # and 0.60 - but squashing the cage to 0.60 in Y alone moved the mesh to 0.73, and
    # stretching it to 1.60 in Y gave 1.41. That is the deformer being correct, and it is
    # also why the first version of this example looked like it was barely working.
    #
    # A squash deformer on the cage moves the cage's own points, which is what an animator
    # does by hand and what the method is built to follow.
    last = max(int(frames), 2)
    cmds.select(cage, replace=True)
    handle = cmds.nonLinear(cage, type='squash')
    squash, squash_handle = handle[0], handle[1]
    cmds.setAttr(squash_handle + '.rotateZ', 0)
    box = cmds.exactWorldBoundingBox(cage)
    cmds.setAttr(squash_handle + '.translateY', (box[1] + box[4]) * 0.5)
    cmds.setAttr(squash + '.lowBound', -1.0)
    cmds.setAttr(squash + '.highBound', 1.0)
    cmds.setAttr(squash + '.startSmoothness', 1.0)
    cmds.setAttr(squash + '.endSmoothness', 1.0)

    # squash factor: negative squashes and widens, positive stretches and narrows.
    beats = [(0.0, 0.0), (0.16, -0.45), (0.33, 0.30), (0.52, -0.20),
             (0.70, 0.12), (0.86, -0.05), (1.0, 0.0)]
    cmds.cutKey(squash, attribute='factor', clear=True)
    for where, factor in beats:
        cmds.setKeyframe(squash, attribute='factor',
                         time=1 + int(round(where * (last - 1))), value=factor)
    cmds.keyTangent(squash, attribute='factor', inTangentType='auto', outTangentType='auto')
    cmds.playbackOptions(minTime=1, maxTime=last, animationStartTime=1,
                         animationEndTime=last)
    cmds.currentTime(1)

    squash_handle = cmds.rename(squash_handle, '{}_squash'.format(name))

    # Draw the cage as a wire even in a shaded viewport, and keep the squash handle out of
    # the shot. A shaded cage hides the thing it is deforming, which is the wrong way round
    # for anyone watching - or filming.
    for attribute, value in (('overrideEnabled', 1), ('overrideShading', 0),
                             ('overrideColor', 18)):
        try:
            cmds.setAttr('{}.{}'.format(cage, attribute), value)
        except Exception:
            logger.debug('Could not set the cage display override.', exc_info=True)
    try:
        cmds.setAttr(squash_handle + '.visibility', 0)
    except Exception:
        logger.debug('Could not hide the squash handle.', exc_info=True)
    cmds.select(clear=True)

    made.update({'squash': squash_handle, 'cage': cage, 'cage_points': built['points'], 'cage_faces': built['faces'],
                 'deformer': wrapped['deformer'], 'rest_cage': wrapped['rest_cage'],
                 'rest_error': wrapped['worst_rest_error'],
                 'points_outside': wrapped['points_outside'],
                 'start': 1, 'end': last})
    return made, (
        'Built an example: {} has {} points and no skeleton, and is driven by {} cage '
        'points. The bind moved it {:.3g} units. Press play - the cage is keyed through a '
        'squash and stretch over {} frames, and the prop follows. Scrub to a frame you '
        'like and pull a cage point to see it answer live. The bounce is a squash deformer '
        'on the {}-point cage - the prop itself has nothing on it but the wrap.'
        .format(prop, made['vertices'], built['points'], wrapped['worst_rest_error'], last,
                built['points']))


@_safe
@_one_undo
@_keep_selection
def cage_from_mesh(mesh, faces=DEFAULT_CAGE_FACES, offset=None, name=None, grow=3,
                   relax=DEFAULT_RELAX, symmetry=False):
    """
    Build a cage around a mesh, so nobody has to model one.

    **This is the reason cage deformers go unused.** The deformation is better than a
    lattice at almost everything, and getting one takes an afternoon of modelling a
    closed low-poly shell that follows the silhouette without touching it. This
    retopologises the mesh down to a few hundred faces, pushes the result outward until
    the mesh is entirely inside it, and checks both.

    It is a starting point, not a final answer: a generated cage follows the shape
    faithfully, which is not the same as being easy to animate. Delete the bits you do
    not need and move the rest.

    :param mesh: The mesh to build a cage around.
    :param int faces: Roughly how many faces the cage should have. More follows the
        shape more closely and costs more to bind against.
    :param float offset: How far out to push, in scene units. None takes 2% of the
        mesh's bounding diagonal and grows it until nothing is left outside.
    :param str name: Name for the cage. None names it after the mesh.
    :param int grow: How many times to try again with a larger offset.
    :param int relax: Rounds of averaging to take the mesh's own small detail off the
        cage. 0 leaves it exactly as the retopology made it.
    :param bool symmetry: Make the cage symmetrical about X, so it can be posed
        symmetrically - retopology never comes out symmetrical on its own. Built by
        keeping the +X half and mirroring it, so the face count lands about a quarter
        above ``faces``.
    :return: Response whose result carries the cage and what was measured about it.
    :rtype: dict
    """

    shape = _mesh_shape(mesh)
    source = _transform_of(shape)
    stem = name or '{}_cage'.format(str(source).split('|')[-1])
    diagonal = _diagonal(shape)
    if diagonal <= 0.0:
        raise ValueError('{} has no size, so there is nothing to build a cage around.'
                         .format(source))

    step = offset if offset is not None else DEFAULT_OFFSET * diagonal

    # Clear out whatever THIS builder made for this mesh last time, and nothing else.
    kind = '{}:shape'.format(str(source).split('|')[-1])
    for previous in _tagged(CAGE_TAG, kind):
        if cmds.objExists(previous):
            cmds.delete(previous)

    made = cmds.duplicate(source, name=stem, returnRootsOnly=True)[0]
    for child in (cmds.listRelatives(made, children=True, fullPath=True) or []):
        if cmds.nodeType(child) != 'mesh':
            cmds.delete(child)
    for channel in ('translate', 'rotate', 'scale'):
        for axis in ('X', 'Y', 'Z'):
            plug = '{}.{}{}'.format(made, channel, axis)
            try:
                cmds.setAttr(plug, lock=False)
            except Exception:
                logger.debug('Could not unlock %s.', plug, exc_info=True)
            for source_plug in (cmds.listConnections(plug, source=True, destination=False,
                                                     plugs=True) or []):
                cmds.disconnectAttr(source_plug, plug)

    # Clear the non-manifold geometry off OUR copy first.
    #
    # **Production meshes are non-manifold, and both of Maya's reducers refuse outright.**
    # A game-ready teapot - 13,568 points, three shells, 403 border edges - had four
    # non-manifold vertices and two edges in it, and that was enough for `polyRetopo` and
    # `polyReduce` to both decline with "Cleanup the object using Mesh->Cleanup". Without
    # this, the builder handed back a full-resolution duplicate as the cage, which then
    # binds, slowly, holding 1.5 GB.
    #
    # Splitting the offending vertices is exactly what Mesh > Cleanup does for
    # non-manifold, and this is our own copy, so it costs the artist nothing. One pass took
    # that teapot from six bad components to none, after which retopology reduced it to 151
    # faces.
    bad = ((cmds.polyInfo(made, nonManifoldVertices=True) or []) +
           (cmds.polyInfo(made, nonManifoldEdges=True) or []))
    split = len(bad)
    if bad:
        try:
            cmds.select(bad, replace=True)
            cmds.polySplitVertex(constructionHistory=False)
        except Exception:
            logger.debug('Could not split the non-manifold components of %s.', made,
                         exc_info=True)
        left = ((cmds.polyInfo(made, nonManifoldVertices=True) or []) +
                (cmds.polyInfo(made, nonManifoldEdges=True) or []))
        if left:
            logger.warning('%s still has %s non-manifold component(s) after splitting; the '
                           'reducers may refuse it.', made, len(left))

    # Retopologise, then fall back to a plain reduction. `polyRetopo` gives an even
    # quad mesh that follows the silhouette; `polyReduce` takes more and gives a messier
    # answer. A messier cage is worth far more than no cage.
    how = 'retopologised'
    try:
        cmds.polyRetopo(made, constructionHistory=False, targetFaceCount=int(faces))
    except Exception:
        logger.debug('polyRetopo would not run on %s; reducing instead.', made,
                     exc_info=True)
        how = 'reduced'
        count = cmds.polyEvaluate(made, face=True) or int(faces)
        percentage = max(1.0, min(99.0, 100.0 - (float(faces) / max(count, 1)) * 100.0))
        cmds.polyReduce(made, version=1, percentage=percentage, keepQuadsWeight=1.0,
                        constructionHistory=False)

    # Did the reduction actually happen? Both of those commands can fail in ways that
    # leave the duplicate at full resolution, and a "cage" the size of the mesh is worse
    # than no cage: it binds, slowly, and holds gigabytes. Refused here rather than
    # discovered later.
    after = cmds.polyEvaluate(made, face=True) or 0
    before_faces = cmds.polyEvaluate(str(shape), face=True) or 0
    if before_faces and after > max(int(faces) * 4, before_faces * 0.25):
        cmds.delete(made)
        raise ValueError(
            'Neither retopology nor reduction would run on {}: the copy still has {} faces '
            'against the {} asked for, so it is a duplicate of the mesh rather than a cage. '
            'That usually means the mesh is non-manifold or has zero-area faces - Mesh > '
            'Cleanup will say which. Building a cage from the skeleton instead does not care '
            'about any of that.'.format(str(source).split('|')[-1], after, int(faces)))

    # A cage has to be closed. Retopology of a mesh with holes leaves holes.
    if border_edges(made):
        cmds.select(made, replace=True)
        try:
            cmds.polyCloseBorder(made, constructionHistory=False)
        except Exception:
            logger.debug('Could not close the borders of %s.', made, exc_info=True)

    # Relaxing and symmetry come BEFORE the offset, not after. Both move points, and
    # moving points after the containment loop has finished is how you end up with a
    # cage that was checked and then quietly broken.
    rough_before = roughness(made)
    if relax:
        cmds.select(made, replace=True)
        for _ in range(int(relax)):
            try:
                cmds.polyAverageVertex(made + '.vtx[*]', iterations=1,
                                       constructionHistory=False)
            except Exception:
                logger.debug('Could not relax %s.', made, exc_info=True)
                break
    rough_after = roughness(made)

    # Symmetry is built by MIRRORING, not by pairing points up.
    #
    # Pairing was the first attempt and it does not work: retopology gives a topology
    # whose points have no mirror partners at all, and on a 127-point cage only 8 of them
    # could be matched. So the +X half is kept and mirrored back over, which comes out
    # exactly symmetrical - 95 pairs, nothing unpaired, points moved by 3e-17 - at the
    # cost of a face count about a quarter above what was asked for.
    symmetry_pairs = 0
    symmetry_unpaired = 0
    symmetry_moved = 0.0
    if symmetry:
        try:
            cmds.polyCut(made, constructionHistory=False, pc=(0.0, 0.0, 0.0),
                         ro=(0.0, 90.0, 0.0), ef=True, eo=(0.0, 0.0, 0.0))
            doomed = []
            for face in range(cmds.polyEvaluate(made, face=True) or 0):
                box = cmds.exactWorldBoundingBox('{}.f[{}]'.format(made, face))
                if (box[0] + box[3]) / 2.0 < -1e-6:
                    doomed.append('{}.f[{}]'.format(made, face))
            if doomed:
                cmds.delete(doomed)
            cmds.polyMirrorFace(made, constructionHistory=False, direction=0, mergeMode=1,
                                mergeThreshold=max(_diagonal(shape) / 500.0, 1e-4),
                                axis=0, pivot=(0.0, 0.0, 0.0))

            # Measured, not assumed: pair the points up afterwards and see whether every
            # one of them found its mirror.
            symmetry_pairs, symmetry_unpaired, symmetry_moved = symmetrise(made, axis='x')
            if border_edges(made):
                cmds.polyCloseBorder(made, constructionHistory=False)
        except Exception:
            logger.warning('Could not make %s symmetrical; keeping the cage as it was.',
                           made, exc_info=True)
            symmetry_pairs = symmetry_unpaired = -1

    step, outside, worst, attempts = grow_to_contain(shape, made, step, grow)
    fit_median, fit_worst, fit_fraction = fit_to_mesh(shape, made)

    borders = border_edges(made)
    cage_faces = cmds.polyEvaluate(made, face=True)
    cage_points = cmds.polyEvaluate(made, vertex=True)
    _tag(made, CAGE_TAG, kind)

    # An open cage is not a cage, and saying so here is much kinder than letting the bind
    # refuse it later. **This is what a real game asset does to this builder**: a teapot
    # made of three open shells with 403 border edges retopologises into five open shells
    # with 34, and no amount of hole filling makes that one closed volume. The cage is left
    # in the scene, because somebody who knows the asset may well be able to fix it by hand.
    if borders:
        raise ValueError(
            '{} came out with {} border edge(s) in {} shell(s), so it is not closed and '
            'cannot be bound to. That happens when the mesh itself is open or in pieces - '
            'this one has {} border edge(s) of its own. The cage is in the scene as {} if '
            'you want to fill the holes by hand; building one from the skeleton instead does '
            'not care about any of it.'
            .format(made.split('|')[-1], borders, cmds.polyEvaluate(made, shell=True),
                    border_edges(shape), made.split('|')[-1]))

    result = {'cage': made, 'faces': cage_faces, 'points': cage_points,
              'offset': step, 'closed': borders == 0, 'border_edges': borders,
              'points_outside': outside, 'worst_outside': worst, 'method': how,
              'fit_median': fit_median, 'fit_worst': fit_worst,
              'fit_fraction': fit_fraction,
              'nonmanifold_split': split,
              'roughness_before': rough_before, 'roughness_after': rough_after,
              'symmetry_pairs': symmetry_pairs, 'symmetry_unpaired': symmetry_unpaired,
              'symmetry_moved': symmetry_moved}
    message = ('Built {} from {}: {} faces, {} points, {} {:.4g} units out. '
               .format(made.split('|')[-1], str(source).split('|')[-1], cage_faces,
                       cage_points, how, step))
    if split:
        message += ('Split {} non-manifold component(s) off the copy first, because both of '
                    'Maya\'s reducers refuse geometry with any. '.format(split))
    if relax:
        message += ('Relaxed {} time(s), which took its roughness from {:.3f} to {:.3f}. '
                    .format(int(relax), rough_before, rough_after))
    if symmetry and symmetry_unpaired >= 0:
        message += ('Mirrored about X into a symmetrical cage: {} pair(s), {} point(s) '
                    'without a mirror. '.format(symmetry_pairs, symmetry_unpaired))
        if symmetry_unpaired:
            message += ('That it is not perfectly symmetrical means the mirror did not merge '
                        'cleanly - usable, but pose it with that in mind. ')
    elif symmetry:
        message += 'Could not be made symmetrical, so it is the shape the retopology gave. '
    if borders:
        message += ('WARNING: it is NOT closed - {} border edge(s) - so it cannot be bound '
                    'to until those holes are filled.'.format(borders))
    elif outside:
        message += ('{} of the mesh\'s points are still outside it - {} distance(s) were '
                    'measured and this one left the least out, the worst by {:.4g} units. '
                    'Those points get bound to their closest cage face, which is a guess. '
                    'Pushing harder does not fix this: a uniform offset folds through '
                    'itself in the armpits, the crotch and between the fingers, so past a '
                    'unit or two MORE of the mesh ends up outside, not less. For a limbed '
                    'character, build the cage from the skeleton instead.'
                    .format(outside, attempts, worst))
    else:
        message += 'It is closed and the whole mesh is inside it.'
    message += (' It sits a median {:.4g} units off the mesh, {:.1%} of the mesh\'s '
                'diagonal.'.format(fit_median, fit_fraction))
    if fit_fraction > LOOSE_CAGE_FRACTION:
        message += (' WARNING: that is far too loose to pose - a cage this size contains the '
                    'mesh without following it. Build from the skeleton instead.')
    return result, message


@_safe
@_one_undo
@_keep_selection
def wrap(mesh, cage=None, stretch=0.0, rest_cage=None, faces=DEFAULT_CAGE_FACES,
         threads=0, name=None, relax=DEFAULT_RELAX, symmetry=False):
    """
    Bind a mesh to a cage.

    The cage handed back is the one to animate. A hidden copy of it is kept as the rest
    pose, because the deformation is the difference between the two - so there is
    nothing to freeze, nothing to remember not to touch, and the cage can be moved,
    parented, deformed or simulated from the moment this returns.

    :param mesh: The mesh to deform.
    :param cage: The cage. None builds one with :func:`cage_from_mesh`.
    :param float stretch: 0 keeps the enclosed shape's thickness, 1 lets it thicken and
        thin with the cage. Keyable afterwards.
    :param rest_cage: Use this as the rest pose instead of a copy of ``cage`` - for a
        cage that is already animated, or one shared between meshes.
    :param int faces: Face count for a cage this has to build.
    :param int relax: Relaxing rounds for a cage this has to build.
    :param bool symmetry: Make a cage this has to build symmetrical about X.
    :param int threads: 0 lets it choose.
    :param str name: Name for the deformer.
    :return: Response whose result carries the deformer, the cage, and what the bind
        measured about itself.
    :rtype: dict
    """

    _require_plugin()

    shape = _mesh_shape(mesh)
    target = _transform_of(shape)

    built = None
    if cage is None:
        built = cage_from_mesh(target, faces=faces, relax=relax, symmetry=symmetry)
        if not built['ok']:
            raise ValueError('Could not build a cage: {}'.format(built['message']))
        cage = built['result']['cage']

    cage_shape = _mesh_shape(cage)
    cage_transform = _transform_of(cage_shape)

    # Is this actually a cage? Checked before anything is allocated, because the failure
    # mode otherwise is gigabytes of weights and a Maya that looks hung.
    mesh_points = cmds.polyEvaluate(str(shape), vertex=True) or 0
    elements = ((cmds.polyEvaluate(str(cage_shape), vertex=True) or 0) +
                (cmds.polyEvaluate(str(cage_shape), face=True) or 0))
    estimate = mesh_points * elements * 4.0 / (1024.0 * 1024.0)
    if estimate > MAX_BIND_MEGABYTES:
        raise ValueError(
            'Binding {} mesh points to {} cage elements would hold about {:.0f} MB of weights '
            'and take minutes - {} has {} points and {} faces, which is not a low-resolution '
            'cage. A cage wants tens or low hundreds of faces; build one with Build A Cage or '
            'Build From Bones, or model one.'
            .format(mesh_points, elements, estimate, str(cage_transform).split('|')[-1],
                    cmds.polyEvaluate(str(cage_shape), vertex=True),
                    cmds.polyEvaluate(str(cage_shape), face=True)))

    holes = border_edges(cage_shape)
    if holes:
        raise ValueError(
            '{} has {} border edge(s), so it is not closed, and an open cage encloses '
            'nothing. Fill the holes - Mesh > Fill Hole, or polyCloseBorder - and try '
            'again.'.format(str(cage_transform).split('|')[-1], holes))

    # The rest pose. Copied rather than demanded, and tagged so a later run replaces
    # exactly this one.
    if rest_cage is None:
        for previous in _tagged(REST_TAG, str(cage_transform).split('|')[-1]):
            if cmds.objExists(previous):
                cmds.delete(previous)
        rest = cmds.duplicate(str(cage_transform),
                              name='{}_rest'.format(str(cage_transform).split('|')[-1]),
                              returnRootsOnly=True)[0]
        for child in (cmds.listRelatives(rest, children=True, fullPath=True) or []):
            if cmds.nodeType(child) != 'mesh':
                cmds.delete(child)
        cmds.setAttr(rest + '.visibility', False)
        _tag(rest, REST_TAG, str(cage_transform).split('|')[-1])
    else:
        rest = str(_transform_of(rest_cage))

    rest_shape = _mesh_shape(rest)

    node = cmds.deformer(str(target), type=NODE_TYPE,
                        name=name or '{}_cageWrap'.format(str(target).split('|')[-1]))[0]

    cmds.connectAttr('{}.outMesh'.format(rest_shape), '{}.restCage'.format(node))
    cmds.connectAttr('{}.worldMatrix[0]'.format(_transform_of(rest_shape)),
                     '{}.restCageMatrix'.format(node))
    cmds.connectAttr('{}.outMesh'.format(cage_shape), '{}.cage'.format(node))
    cmds.connectAttr('{}.worldMatrix[0]'.format(cage_transform), '{}.cageMatrix'.format(node))

    cmds.setAttr('{}.stretch'.format(node), float(stretch))
    cmds.setAttr('{}.threads'.format(node), int(threads))

    # Force the bind now rather than at the next viewport refresh, so the numbers below
    # are about this mesh and not about nothing.
    cmds.dgeval('{}.outMesh'.format(shape))

    measured = report(node)
    result = {'deformer': node, 'cage': str(cage_transform), 'rest_cage': rest,
              'mesh': str(target)}
    result.update(measured.get('result') or {})
    if built:
        result['cage_built'] = built['result']

    message = ('{} now follows {}. The bind puts every point back within {:.3g} units of '
               'where it was; {} point(s) sit outside the cage, {} were rebound to their '
               'closest face; {} weight(s) holding {:.1f} MB.'
               .format(str(target).split('|')[-1], str(cage_transform).split('|')[-1],
                       result.get('worst_rest_error', 0.0), result.get('points_outside', 0),
                       result.get('points_rebound', 0), result.get('weights_kept', 0),
                       result.get('megabytes', 0.0)))
    if result.get('points_outside'):
        message += ('  Those outside points are bound to their closest cage face, which is '
                    'exact for a rigid move and a guess for anything else.')
    if built:
        message += '  ' + built['message']
    return result, message


def _wrap_cages(node):
    """
    The cage and the rest copy a wrap node is actually reading.

    :param node: An mcaCageWrap node.
    :return: (cage transform, rest cage transform), either may be None.
    :rtype: tuple
    """

    found = []
    for plug in ('.cage', '.restCage'):
        sources = cmds.listConnections(str(node) + plug, source=True, destination=False,
                                       shapes=True) or []
        found.append(str(_transform_of(sources[0])) if sources else None)
    return found[0], found[1]


def _parent_of(name):
    """:return: The full path of a node's parent, or None at the root."""

    return (cmds.listRelatives(name, parent=True, fullPath=True) or [None])[0]


def _parented_apart(cage, rest):
    """
    Do the cage and its rest copy hang off different parents?

    They start as siblings, because the rest copy is a duplicate. Grouping a finished setup
    up for shipping takes the cage and leaves the rest copy behind at the root, and from
    then on the group's own transform reads as the cage having moved: the mesh follows it
    on top of its own transform and flies off. Found in our own sample scene, where three
    of the four setups did exactly that and only the one at index 0 - the group that never
    moved - looked right.

    Worth a sentence in the report rather than a refusal, because it is legal, it is
    occasionally deliberate, and the symptom otherwise looks like a broken bind rather than
    an outliner problem.

    :param cage: The cage transform.
    :param rest: The rest cage transform.
    :rtype: bool
    """

    if not cage or not rest:
        return False
    return _parent_of(cage) != _parent_of(rest)


@_safe
def report(deformer):
    """
    What the bind measured about itself.

    :param deformer: An mcaCageWrap node.
    :return: Response whose result carries the numbers.
    :rtype: dict
    """

    node = str(deformer)
    if cmds.nodeType(node) != NODE_TYPE:
        raise ValueError('{} is not a {} node.'.format(node, NODE_TYPE))

    weights = cmds.getAttr(node + '.weightsKept')
    result = {
        'worst_rest_error': cmds.getAttr(node + '.worstRestError'),
        'points_outside': cmds.getAttr(node + '.pointsOutside'),
        'points_rebound': cmds.getAttr(node + '.pointsRebound'),
        'weights_kept': weights,
        # One float per cage element per mesh point. Said out loud because on a dense
        # mesh it is the number that decides whether this is usable, and it is the one
        # thing about a cage deformer nobody tells you until the scene will not open.
        'megabytes': weights * 4.0 / (1024.0 * 1024.0),
        'stretch': cmds.getAttr(node + '.stretch'),
        'envelope': cmds.getAttr(node + '.envelope'),
    }
    message = ('{}: worst rest error {:.3g} units, {} point(s) outside the cage, {} rebound '
               'to their closest face, {} weight(s) holding {:.1f} MB, stretch {:.2f}.'
               .format(node.split('|')[-1], result['worst_rest_error'],
                       result['points_outside'], result['points_rebound'],
                       result['weights_kept'], result['megabytes'], result['stretch']))
    cage, rest = _wrap_cages(node)
    result['cage'] = cage
    result['rest_cage'] = rest
    result['parented_apart'] = _parented_apart(cage, rest)
    if result['parented_apart']:
        message += ('  {} and {} sit under different parents, so any transform above one of '
                    'them reads as the cage having moved and the mesh follows it twice. Put '
                    'them back under the same parent.'
                    .format(str(cage).split('|')[-1], str(rest).split('|')[-1]))
    return result, message


def find_wraps(mesh=None):
    """
    :param mesh: Only deformers on this mesh. None finds all of them.
    :return: mcaCageWrap node names.
    :rtype: list
    """

    if mesh is None:
        return cmds.ls(type=NODE_TYPE, long=True) or []
    shape = str(_mesh_shape(mesh))
    return [node for node in (cmds.listHistory(shape) or [])
            if cmds.nodeType(node) == NODE_TYPE]


@_safe
@_one_undo
@_keep_selection
def remove(mesh_or_deformer, keep_cage=True):
    """
    Take the deformer off and clean up after it.

    :param mesh_or_deformer: A deformed mesh, or the deformer itself.
    :param bool keep_cage: Keep the cage the artist has been animating. The hidden rest
        cage goes either way - it is this tool's own bookkeeping.
    :return: Response whose result names what was removed.
    :rtype: dict
    """

    node = str(mesh_or_deformer)
    nodes = [node] if cmds.objExists(node) and cmds.nodeType(node) == NODE_TYPE \
        else find_wraps(mesh_or_deformer)
    if not nodes:
        raise ValueError('There is no {} to remove on {}.'.format(NODE_TYPE, node))

    removed = {'deformers': [], 'rest_cages': [], 'cages': []}
    for each in nodes:
        for plug, kind in (('.restCage', 'rest_cages'), ('.cage', 'cages')):
            for source in (cmds.listConnections(each + plug, source=True, destination=False,
                                                shapes=True) or []):
                transform = (cmds.listRelatives(source, parent=True, fullPath=True) or
                             [source])[0]
                doomed = kind == 'rest_cages' and cmds.attributeQuery(
                    REST_TAG, node=transform, exists=True)
                if kind == 'cages' and not keep_cage:
                    doomed = True
                if doomed and cmds.objExists(transform):
                    cmds.delete(transform)
                    removed[kind].append(transform)
        if cmds.objExists(each):
            cmds.delete(each)
            removed['deformers'].append(each)

    return removed, ('Removed {} deformer(s), {} rest cage(s) and {} cage(s).'
                     .format(len(removed['deformers']), len(removed['rest_cages']),
                             len(removed['cages'])))


def moving_frames(mesh, frames, tolerance=1e-5):
    """
    Which of these frames actually show the mesh in a different shape.

    :param mesh: The deformed mesh.
    :param frames: Frames to look at.
    :param float tolerance: How far a point has to move to count.
    :return: ``(frames that move, worst movement)``.
    :rtype: tuple
    """

    import maya.api.OpenMaya as om

    shape = str(_mesh_shape(mesh))
    was = cmds.currentTime(query=True)

    def points():
        holder = om.MSelectionList()
        holder.add(shape)
        return om.MFnMesh(holder.getDagPath(0)).getPoints(om.MSpace.kWorld)

    try:
        cmds.currentTime(frames[0])
        rest = points()
        moving = []
        worst = 0.0
        for frame in frames:
            cmds.currentTime(frame)
            now = points()
            far = max((om.MVector(now[index] - rest[index])).length()
                      for index in range(len(rest))) if len(rest) else 0.0
            worst = max(worst, far)
            if far > tolerance:
                moving.append(frame)
        return moving, worst
    finally:
        cmds.currentTime(was)


@_safe
@_one_undo
@_keep_selection
def bake_to_skin(mesh, frames, count=20, joints=None, max_influences=8, rest_frame=None,
                 iterations=3, holdout=None, **kwargs):
    """
    Turn a cage deformation into joints and skin weights an engine can take.

    None of this runs outside Maya - not the cage, not the coordinates, not the hidden
    rest pose. So for anything that ships, the cage is the authoring tool and a
    skinCluster is the deliverable, and this is the bridge: animate the cage across a
    range of frames, and the pose skinner fits joints and weights to the shapes that
    come out.

    The two plug-ins already fit together - this hands one's output to the other's
    input and checks the result rather than reimplementing either.

    **What decides whether this works is the poses, not this function.** Every pose is
    three numbers per vertex to fit against; every joint is an unknown. Animate the cage
    through the extremes the rig has to reach, one shape per frame, and hold some of
    them back (``holdout``) so the error you read is about a pose nobody solved for.

    :param mesh: The cage-deformed mesh.
    :param frames: One frame per pose. The cage has to actually move across them.
    :param int count: How many joints to invent, when ``joints`` is not given.
    :param joints: Use these joints instead of inventing any. They have to already move.
    :param int max_influences: Influences per vertex the engine allows.
    :param float rest_frame: The neutral shape. None takes the first frame.
    :param int iterations: Weight/bone alternations when inventing joints.
    :param holdout: Frames to keep out of the fit and report separately. None holds back
        every fourth frame, which is the number that tells you whether the skin
        generalises.
    :return: Response whose result carries the pose skinner's own report.
    :rtype: dict
    """

    from mca.mya.tools.poseskinner import poseskinner_api

    shape = _mesh_shape(mesh)
    target = _transform_of(shape)

    wraps = find_wraps(shape)
    if not wraps:
        raise ValueError(
            '{} has no {} on it, so there is no cage deformation to bake. Wrap it first.'
            .format(str(target).split('|')[-1], NODE_TYPE))

    frames = [float(frame) for frame in frames]
    if len(frames) < 2:
        raise ValueError('Baking needs at least two frames - a neutral one and a pose.')

    rest = float(rest_frame) if rest_frame is not None else frames[0]
    moving, worst = moving_frames(target, frames)
    if not moving:
        raise ValueError(
            'The mesh is the same shape on all {} frames, to within a hundred-thousandth of '
            'a unit. Animate the cage across those frames first - the solve fits the '
            'DIFFERENCES between poses, so identical poses carry no information.'
            .format(len(frames)))

    if holdout is None:
        holdout = frames[3::4]
        if len(holdout) >= len(frames):
            holdout = []

    if joints:
        solved = poseskinner_api.skin_from_poses(
            target, joints, frames, rest_frame=rest, max_influences=max_influences,
            holdout=holdout, **kwargs)
    else:
        solved = poseskinner_api.auto_joints(
            target, int(count), frames, rest_frame=rest, max_influences=max_influences,
            iterations=iterations, **kwargs)

    if not solved['ok']:
        raise ValueError('The pose skinner refused: {}'.format(solved['message']))

    result = {'pose_skinner': solved['result'], 'frames': frames, 'holdout': holdout,
              'frames_that_move': len(moving), 'worst_movement': worst,
              'joints_given': bool(joints)}
    message = ('Baked {} frame(s) of cage deformation into a skin. {} '
               .format(len(frames), solved['message']))
    if len(moving) < len(frames) - 1:
        message += (' Note that only {} of those {} frames are a different shape - the rest '
                    'carry no information for the fit.'.format(len(moving), len(frames)))
    return result, message


def bone_chains(joints):
    """
    Split a set of joints into chains, breaking at every branch.

    A chain is a run of joints with one child each. At a branch, every child starts a new
    chain **beginning at the branch joint**, so the tubes built from them meet there
    instead of leaving a gap.

    :param joints: Joints to consider. Anything outside this set is ignored, so handing in
        one arm's joints gives one chain even though the shoulder has a spine above it.
    :return: Lists of full path names, parent first.
    :rtype: list
    """

    names = []
    for each in ([joints] if isinstance(joints, str) else joints):
        for found in (cmds.ls(str(each), long=True) or []):
            if found not in names:
                names.append(found)
    if not names:
        raise ValueError('No joints given.')

    inside = set(names)
    children = {name: [] for name in names}
    starts = []
    for name in names:
        parents = cmds.listRelatives(name, parent=True, fullPath=True) or []
        if parents and parents[0] in inside:
            children[parents[0]].append(name)
        else:
            starts.append(name)

    chains = []

    def walk(first):
        chain = [first]
        current = first
        while len(children[current]) == 1:
            current = children[current][0]
            chain.append(current)
        if len(chain) > 1 or not children[current]:
            chains.append(chain)
        for child in children[current]:
            walk_from(current, child)

    def walk_from(branch, child):
        chain = [branch, child]
        current = child
        while len(children[current]) == 1:
            current = children[current][0]
            chain.append(current)
        chains.append(chain)
        for other in children[current]:
            walk_from(current, other)

    for first in starts:
        walk(first)
    return chains


def skin_owners(shape, joints):
    """
    The one joint that owns each vertex, by heaviest skin weight, across the WHOLE skeleton.

    **"Has some weight here" is not ownership, and the difference only shows on a compact
    figure.** A smooth bind spreads a little weight a long way, so on a character a toe
    genuinely has zero weight on the spine and a per-chain "is this weight above zero" test
    looks right. Shrink the figure until the bind bleeds and every vertex has a sliver of
    weight on everything, and that test hands the whole mesh to every chain again. The
    question has to be *which joint holds the most*, asked once against every influence.

    :param shape: The skinned mesh.
    :param joints: The joints to resolve against, in any order.
    :return: A list, one entry per vertex, holding the owning joint's name or None.
    :rtype: list
    """

    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma

    cluster = existing_skin(shape)
    if cluster is None:
        return None
    try:
        holder = om.MSelectionList()
        holder.add(str(_mesh_shape(shape)))
        path = holder.getDagPath(0)
        count_points = om.MFnMesh(path).numVertices

        holder = om.MSelectionList()
        holder.add(str(cluster))
        fn = oma.MFnSkinCluster(holder.getDependNode(0))
        influences = [each.fullPathName() for each in fn.influenceObjects()]

        component = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
        om.MFnSingleIndexedComponent(component).setCompleteData(count_points)
        flat, count = fn.getWeights(path, component)
    except Exception:
        logger.debug('Could not read the skin weights to decide ownership.', exc_info=True)
        return None

    owners = []
    for vertex in range(count_points):
        base = vertex * count
        top, pick = 0.0, -1
        for column in range(count):
            value = flat[base + column]
            if value > top:
                top, pick = value, column
        owners.append(influences[pick] if pick >= 0 and top > 0.0 else None)
    return owners


def _bone_vertices(shape, joints, skeleton=None, owners=None):
    """
    Which mesh points belong to which bone.

    By skin weight when the mesh is skinned - that is the rigger's own answer and there is
    no reason to second-guess it - and by closest bone segment when it is not.

    :param shape: The mesh shape.
    :param joints: Full path names, in order.
    :return: ``{joint index: [world MPoint, ...]}``.
    :rtype: dict
    """

    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma

    holder = om.MSelectionList()
    holder.add(str(shape))
    path = holder.getDagPath(0)
    points = om.MFnMesh(path).getPoints(om.MSpace.kWorld)

    owned = {index: [] for index in range(len(joints))}

    cluster = existing_skin(shape)
    weights = None
    if cluster is not None:
        try:
            holder = om.MSelectionList()
            holder.add(str(cluster))
            fn = oma.MFnSkinCluster(holder.getDependNode(0))
            influences = [each.fullPathName() for each in fn.influenceObjects()]
            column = {name: index for index, name in enumerate(influences)}
            wanted = [column.get(name, -1) for name in joints]
            if any(index >= 0 for index in wanted):
                component = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
                om.MFnSingleIndexedComponent(component).setCompleteData(len(points))
                flat, count = fn.getWeights(path, component)
                weights = (flat, count, wanted)
        except Exception:
            logger.debug('Could not read the skin weights; falling back to distance.',
                         exc_info=True)

    positions = [om.MPoint(cmds.xform(joint, q=True, worldSpace=True, translation=True))
                 for joint in joints]

    # Every vertex that is not this chain's gets DROPPED, not handed to the nearest joint
    # in it. That is the whole of the fix, and it is why a character used to come out as a
    # pile of beach balls: the fallback below answers "which of these joints is nearest",
    # which always has an answer, so a three-joint shoulder chain was handed the toes, the
    # fingertips and the top of the head. Measured on a 16,747-point body, every one of the
    # 40 chains owned all 16,747 points, and every ring radius came out between 145 and 168
    # units on a figure 38 units deep.
    #
    # It hid because the chains the builder was proven on - a tapered tentacle, a teapot on
    # one bone - are SINGLE chains, where "every point belongs to this chain" happens to be
    # true. The branching test checked that branching gives one cage per chain and that each
    # starts at the branch joint; it never looked at a radius.
    skeleton_positions = None
    if skeleton:
        skeleton_positions = [om.MPoint(cmds.xform(joint, q=True, worldSpace=True,
                                                   translation=True))
                              for joint in skeleton]

    def nearest_segment(point, places):
        """Index of the closest bone SEGMENT - not the closest joint, because a point beside
        the middle of a long bone belongs to that bone and its nearest joint may well be the
        next one along."""
        closest, pick = None, -1
        for index in range(len(places)):
            start = places[index]
            end = places[index + 1] if index + 1 < len(places) else places[index]
            direction = om.MVector(end - start)
            length = direction.length()
            if length < 1e-9:
                distance = (om.MVector(point - start)).length()
            else:
                along = max(0.0, min(1.0, (om.MVector(point - start) * direction) /
                                     (length * length)))
                distance = (om.MVector(point - (start + direction * along))).length()
            if closest is None or distance < closest:
                closest, pick = distance, index
        return pick

    mine = set(str(joint) for joint in joints)

    for vertex, point in enumerate(points):
        best = -1
        if owners is not None:
            # Ownership was settled once, against every influence in the skeleton.
            if owners[vertex] not in mine:
                continue
            best = nearest_segment(point, positions)
        elif weights is not None:
            flat, count, wanted = weights
            heaviest = 0.0
            for index, column in enumerate(wanted):
                if column < 0:
                    continue
                value = flat[vertex * count + column]
                if value > heaviest:
                    heaviest = value
                    best = index
            if heaviest <= 1e-6:
                # The skin says this vertex is somebody else's. Believe it.
                continue
        elif skeleton_positions is not None:
            # No skin to ask, so ask the WHOLE skeleton who owns this vertex and keep it
            # only if the answer is one of ours.
            if str(skeleton[nearest_segment(point, skeleton_positions)]) not in mine:
                continue
            best = nearest_segment(point, positions)
        else:
            # No skin and no skeleton given: the caller is asking about one chain in
            # isolation, which is only meaningful when that chain is the whole skeleton.
            best = nearest_segment(point, positions)

        if best < 0:
            best = nearest_segment(point, positions)
        owned[best].append(point)

    return owned


@_safe
@_one_undo
@_keep_selection
def cage_from_skeleton(mesh, joints=None, sides=6, rings=1, grow=3, name=None, padding=0.08):
    """
    Build a cage that follows a skeleton, as a tube of rings around each chain of bones.

    A cage built from the mesh's silhouette is faithful and awkward: it has a point wherever
    the model has detail, and none of them mean anything to an animator. A cage built from
    the **bones** has a ring where each joint is, which is where somebody posing it expects
    to find a handle - so it reads like a cage a rigger would have modelled, because it is
    laid out the way they would have laid it out.

    One cage per chain, breaking at every branch, because a deformer takes one closed cage
    and a skeleton is a tree. For an arm, a tail, a cape spine, a rope or a spout that is
    exactly right. For a whole character it means several cages and several wraps - which is
    usually what you want anyway, since a cage that spans a shoulder cannot be posed
    sensibly.

    Each ring's radius comes from the mesh points that bone owns - by skin weight where the
    mesh is skinned, since that is the rigger's own answer - so a thick part of the mesh gets
    a wide ring and a thin part a narrow one.

    :param mesh: The mesh the cage is for. Only measured, never altered.
    :param joints: The joints to follow. None takes the influences of the mesh's own
        skinCluster, which for a rigged asset is the right set.
    :param int sides: Points per ring. 6 is a good compromise: round enough to follow a
        limb, few enough to grab. 4 gives a box-section tube, 8 a smoother one.
    :param int rings: Extra rings along each bone, between its ends. 0 puts a ring only at
        each joint; 1 adds one at the middle of every bone, which a long bone wants.
    :param int grow: How many times to push the cage further out if the mesh still pokes
        through.
    :param str name: Base name. None names them after the mesh and the first joint.
    :param float padding: How much wider than the mesh each ring starts, as a fraction of
        its own radius.
    :return: Response whose result lists a cage per chain, with what was measured about each.
    :rtype: dict
    """

    import maya.api.OpenMaya as om

    shape = _mesh_shape(mesh)
    source = _transform_of(shape)
    sides = max(3, int(sides))
    rings = max(0, int(rings))

    if joints is None:
        cluster = existing_skin(shape)
        if cluster is None:
            raise ValueError(
                '{} has no skinCluster, so there is no skeleton to follow. Give the joints '
                'explicitly, or use cage_from_mesh to build one from the shape instead.'
                .format(str(source).split('|')[-1]))
        joints = cmds.skinCluster(str(cluster), query=True, influence=True) or []
        if not joints:
            raise ValueError('{} has a skinCluster with no influences.'.format(cluster))

    chains = bone_chains(joints)
    stem = name or '{}_boneCage'.format(str(source).split('|')[-1])

    # Clear out whatever THIS builder made for this mesh last time, and nothing else - a
    # cage built from the shape is a different answer to the same question and stays.
    kind = '{}:bones'.format(str(source).split('|')[-1])
    for previous in _tagged(CAGE_TAG, kind):
        if cmds.objExists(previous):
            cmds.delete(previous)

    # Settle ownership ONCE for the whole mesh rather than per chain - it is the same
    # question each time, and asking it per chain is what let every chain answer "mine".
    owners = skin_owners(shape, joints)

    made = []
    for number, chain in enumerate(chains):
        owned = _bone_vertices(shape, chain, skeleton=joints, owners=owners)
        positions = [om.MPoint(cmds.xform(joint, q=True, worldSpace=True, translation=True))
                     for joint in chain]

        # Where the rings go: at every joint, plus `rings` along each bone. A single-joint
        # chain gets a short tube along the joint's own X, which is the best that can be
        # said about a skeleton with one bone in it.
        stops = []
        if len(positions) == 1:
            reach = max((om.MVector(point - positions[0])).length()
                        for point in owned.get(0, [positions[0]])) or 1.0
            axis = om.MVector(cmds.xform(chain[0], query=True, worldSpace=True,
                                         matrix=True)[0:3]).normal()
            stops = [(positions[0] - axis * reach, axis, 0),
                     (positions[0], axis, 0),
                     (positions[0] + axis * reach, axis, 0)]
        else:
            for index in range(len(positions) - 1):
                start = positions[index]
                end = positions[index + 1]
                axis = om.MVector(end - start)
                if axis.length() < 1e-9:
                    continue
                axis = axis.normal()
                for step in range(rings + 1):
                    where = start + om.MVector(end - start) * (float(step) / (rings + 1))
                    stops.append((where, axis, index))
            stops.append((positions[-1], stops[-1][1], len(positions) - 1))

        if len(stops) < 2:
            continue

        # A radius per ring, from the points the nearby bones own, measured across the axis
        # rather than as a straight distance - what a ring has to clear is how far the mesh
        # sticks out sideways, not how far away the far end of it is.
        #
        # **A ring only measures the slab of mesh beside it.** The window has to be an
        # independent length, and the version this replaces made it `across * 2`, derived
        # from the very point being judged - so the further out sideways a point was, the
        # wider the window that admitted it. A point could not be rejected for being far
        # away along the bone as long as it was also far away across it, which is exactly
        # the toe seen from the ankle: across 30, along 40, 40 < 60, admitted. Every such
        # point then raised `reach`, which admitted more. The foot ring came out at 64.43
        # units on a leg about 12 thick.
        #
        # The window is now half the gap to the neighbouring rings, which is the slab this
        # ring is actually responsible for, with a floor so a dense run of rings still sees
        # enough mesh to measure.
        spacing = []
        for index in range(len(stops)):
            gaps = []
            if index > 0:
                gaps.append(om.MVector(stops[index][0] - stops[index - 1][0]).length())
            if index + 1 < len(stops):
                gaps.append(om.MVector(stops[index + 1][0] - stops[index][0]).length())
            spacing.append(max(gaps) if gaps else 0.0)
        floor = (max(spacing) or _diagonal(shape) / 20.0) * 0.5

        radii = []
        for index, (where, axis, bone) in enumerate(stops):
            window = max(spacing[index] * 0.5, floor * 0.5, 1e-9)
            reach = 0.0
            for offset in (bone - 1, bone, bone + 1):
                for point in owned.get(offset, []):
                    away = om.MVector(point - where)
                    across = away - axis * (away * axis)
                    along = abs(away * axis)
                    if along <= window:
                        reach = max(reach, across.length())
            radii.append(reach)

        # A ring with nothing to measure borrows from its neighbours, and everything gets
        # the padding. Without this a joint sitting outside the mesh gets a zero-radius ring
        # and the tube pinches shut.
        biggest = max(radii) or (_diagonal(shape) / 10.0)
        for index, value in enumerate(radii):
            if value <= 1e-9:
                radii[index] = biggest * 0.35
        radii = [value * (1.0 + max(padding, 0.0)) for value in radii]

        # Stand the end caps clear of the geometry, or the mesh pokes out of them.
        first_point, first_axis, _ = stops[0]
        last_point, last_axis, _ = stops[-1]
        stops[0] = (first_point - first_axis * radii[0], first_axis, stops[0][2])
        stops[-1] = (last_point + last_axis * radii[-1], last_axis, stops[-1][2])

        # Build it. One MFnMesh.create, so there is no history and no chance of Maya
        # choosing a topology of its own.
        points = om.MPointArray()
        for (where, axis, _bone), radius in zip(stops, radii):
            helper = om.MVector(0.0, 1.0, 0.0)
            if abs(axis * helper) > 0.95:
                helper = om.MVector(1.0, 0.0, 0.0)
            across = (axis ^ helper).normal()
            other = (axis ^ across).normal()
            for step in range(sides):
                angle = 2.0 * math.pi * float(step) / float(sides)
                points.append(om.MPoint(where + across * (radius * math.cos(angle)) +
                                        other * (radius * math.sin(angle))))

        counts = []
        connects = []
        for ring in range(len(stops) - 1):
            for step in range(sides):
                next_step = (step + 1) % sides
                counts.append(4)
                connects.extend([ring * sides + step,
                                 ring * sides + next_step,
                                 (ring + 1) * sides + next_step,
                                 (ring + 1) * sides + step])
        # The caps, wound the other way round from each other so both face outward.
        counts.append(sides)
        connects.extend(list(range(sides))[::-1])
        counts.append(sides)
        connects.extend([(len(stops) - 1) * sides + step for step in range(sides)])

        transform = cmds.createNode('transform',
                                    name='{}_{}'.format(stem, number + 1), skipSelect=True)
        holder = om.MSelectionList()
        holder.add(transform)
        om.MFnMesh().create(points, counts, connects, parent=holder.getDependNode(0))
        cage = cmds.ls(transform, long=True)[0]
        cmds.sets(cage, edit=True, forceElement='initialShadingGroup')

        # Outward or inward? Six times the signed volume says which, and a tube built from
        # rings can come out either way depending on which side of the axis the first helper
        # vector landed.
        volume = 0.0
        shape_fn = om.MFnMesh(_shape_path(cage))
        vertices = shape_fn.getPoints(om.MSpace.kWorld)
        for face in range(shape_fn.numPolygons):
            corners = shape_fn.getPolygonVertices(face)
            for corner in range(1, len(corners) - 1):
                a = om.MVector(vertices[corners[0]])
                b = om.MVector(vertices[corners[corner]])
                c = om.MVector(vertices[corners[corner + 1]])
                volume += a * (b ^ c)
        if volume < 0.0:
            cmds.polyNormal(cage, normalMode=0, constructionHistory=False)

        step, outside, worst, used = grow_to_contain(shape, cage, max(_diagonal(shape) * 1e-4,
                                                                     1e-6), grow)
        borders = border_edges(cage)
        _tag(cage, CAGE_TAG, kind)

        made.append({'cage': cage, 'chain': [joint.split('|')[-1] for joint in chain],
                     'rings': len(stops), 'sides': sides,
                     'faces': cmds.polyEvaluate(cage, face=True),
                     'points': cmds.polyEvaluate(cage, vertex=True),
                     'closed': borders == 0, 'border_edges': borders,
                     'points_outside': outside, 'worst_outside': worst,
                     'grown': step, 'grow_passes': used,
                     'radius_smallest': min(radii), 'radius_largest': max(radii)})

    if not made:
        raise ValueError('Those joints do not make a chain with a bone in it.')

    loose = [entry for entry in made if not entry['closed'] or entry['points_outside']]
    result = {'cages': made, 'chains': len(made),
              'joints_used': sum(len(entry['chain']) for entry in made)}
    message = ('Built {} cage(s) from {} chain(s) of bones around {}: {}. '
               .format(len(made), len(chains), str(source).split('|')[-1],
                       ', '.join('{} ({} rings, {} faces)'
                                 .format(entry['cage'].split('|')[-1], entry['rings'],
                                         entry['faces']) for entry in made[:4])))
    if loose:
        message += ('{} of them do not yet hold the mesh: {}. A chain whose bones do not '
                    'reach the ends of the mesh cannot, so wrap the parts each chain covers '
                    'or fall back to cage_from_mesh.'
                    .format(len(loose), ', '.join(entry['cage'].split('|')[-1]
                                                  for entry in loose[:4])))
    else:
        message += 'All closed, and each holds the mesh it was measured from.'
    return result, message


def _shape_path(transform):
    """
    :param transform: A transform name.
    :return: A dag path to its mesh shape.
    """

    import maya.api.OpenMaya as om

    holder = om.MSelectionList()
    holder.add(str(_mesh_shape(transform)))
    return holder.getDagPath(0)
