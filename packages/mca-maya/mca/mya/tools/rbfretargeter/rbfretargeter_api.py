"""
Rebuild one mesh's blendshapes on another mesh.

You have a head with forty correctives and a second head - same topology,
different proportions. This moves all forty onto the second head.

The workflow this is built around
---------------------------------
1. Pick the SOURCE (the head the shapes were sculpted on) and the TARGET (the
   head you want them on). They must share topology.
2. Optionally select a few dozen well-spread vertices on the source to solve on.
   Nothing selected means every vertex, which is what makes
   :data:`DEFAULT_MAX_SOLVER_POINTS` matter.
3. Give it the shapes and let it run.

What to know before you pick solver vertices
--------------------------------------------
The cost is cubic in the number of solver points, so a few hundred spread over
the mesh beats every vertex on every axis - it is faster, it is better
conditioned, and it extrapolates more sensibly. They do have to span three
dimensions: vertices that all lie on one plane cannot describe motion off that
plane, and the result comes back flattened. ``sphere_anchors`` is the cheap fix
when the natural picks are flat.

:Requires: the mcaRBFRetargeter plug-in
:Side effects: Creates new meshes in the open scene.
"""

# python imports
import functools

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

PLUGIN_NAME = 'mcaRBFRetargeter'
COMMAND_NAME = 'mcaRetargetShapes'

#: Above this the command refuses rather than allocating a matrix nobody can
#: hold. The tool this replaces had no such limit and would happily start a
#: 3.2 GB solve on a 20,000-vertex head.
DEFAULT_MAX_SOLVER_POINTS = 5000

#: How many solver vertices Auto-pick takes by default.
#:
#: 1000, from measurement rather than taste. Against ground truth on a
#: 16,747-vertex body, an error-driven pick of 1000 beats an even spread of
#: 2000 on every measure, and the first thing shipped - an even spread of 300 -
#: left a garment up to 3.2 scene units out of place. See
#: :func:`suggest_solver_vertices` for the table.
DEFAULT_SOLVER_POINTS = 1000


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
        if loader.load_mca_rbf_retargeter_plugin():
            return True, ''
    except Exception as exc:
        return False, ('The {} plug-in could not be loaded: {}. It may not have been built '
                       'for this Maya version yet - check plugins/mcaRBFRetargeter/plug-in/.'
                       .format(PLUGIN_NAME, exc))
    return False, ('The {} plug-in could not be loaded. Check that it has been built for '
                   'this Maya version under plugins/mcaRBFRetargeter/plug-in/.'
                   .format(PLUGIN_NAME))


def _mesh_shape(node):
    """
    :param node: A transform or a mesh.
    :return: The mesh shape under it.
    :rtype: pm.nt.Mesh
    :raises ValueError: If there is no mesh there.
    """

    node = pm.PyNode(node)
    if isinstance(node, pm.nt.Mesh):
        return node
    shapes = node.getShapes(noIntermediate=True) if hasattr(node, 'getShapes') else []
    for shape in shapes:
        if isinstance(shape, pm.nt.Mesh):
            return shape
    raise ValueError('{} is not a polygon mesh.'.format(node))


def _vertex_count(node):
    """
    :param node: A transform or a mesh.
    :return: How many vertices it has.
    :rtype: int
    """

    return _mesh_shape(node).numVertices()


def selected_vertex_indices(mesh=None):
    """
    The vertices currently selected, which is what the command solves on.

    :param mesh: Restrict to this mesh. None takes every selected vertex.
    :return: Vertex indices, sorted and without repeats.
    :rtype: list(int)
    """

    wanted = _mesh_shape(mesh).name() if mesh is not None else None
    indices = set()
    for item in (cmds.ls(selection=True, flatten=True) or []):
        if '.vtx[' not in item:
            continue
        node, _, component = item.partition('.vtx[')
        if wanted is not None and _mesh_shape(node).name() != wanted:
            continue
        indices.add(int(component.rstrip(']')))
    return sorted(indices)


#: Where a new mesh gets its shading from.
#:
#: ``shape`` - whatever was on the mesh it was made from. A retargeted shirt
#: keeps the shirt's material, which is nearly always what is wanted.
#: ``target`` - whatever is on the mesh it was deformed to, which is the old
#: window's first mode and is for rebuilt correctives that should look like the
#: head they now belong to.
#: ``none`` - leave it unassigned, which is what the command does on its own.
SHADER_SOURCES = ('shape', 'target', 'none')


def _shading_assignments(shape):
    """
    Read a mesh's shading engine assignments, faces and all.

    :param str shape: The mesh shape's name.
    :return: ``[(shading engine, [components] or None)]``, whole-object
        assignments first. None means the whole object.
    :rtype: list
    """

    engines = []
    for engine in (cmds.listConnections(shape, type='shadingEngine') or []):
        if engine not in engines:
            engines.append(engine)

    transform = (cmds.listRelatives(shape, parent=True) or [None])[0]
    owners = {name.split('|')[-1] for name in (shape, transform) if name}

    whole, partial = [], []
    for engine in engines:
        components = []
        everything = False
        for member in (cmds.sets(engine, query=True) or []):
            node, _, component = member.partition('.')
            if node.split('|')[-1] not in owners:
                continue
            if component:
                components.append(component)
            else:
                everything = True
        if everything:
            whole.append((engine, None))
        elif components:
            partial.append((engine, components))
    return whole + partial


def _copy_shaders(new_shape, from_shape):
    """
    Put ``from_shape``'s shading onto ``new_shape``.

    The command leaves what it creates assigned to NOTHING - not even
    initialShadingGroup - so a retargeted garment comes out with no material at
    all and renders as nothing. The old window did this in its own code with two
    modes; it belongs in the API, where a script gets it too.

    The two meshes are copies of each other, so face indices line up and a
    per-face assignment transfers as-is. Whole-object assignments go on first so
    a per-face one written afterwards wins, which is the order Maya itself uses.

    :param str new_shape: The mesh to assign.
    :param str from_shape: The mesh to read from.
    :return: The shading engines assigned.
    :rtype: list(str)
    """

    assignments = _shading_assignments(from_shape)
    if not assignments:
        return []

    done = []
    for engine, components in assignments:
        try:
            if components is None:
                cmds.sets(new_shape, edit=True, forceElement=engine)
            else:
                cmds.sets(['{}.{}'.format(new_shape, part) for part in components],
                          edit=True, forceElement=engine)
            done.append(engine)
        except Exception:
            logger.warning('Could not assign %s to %s.', engine, new_shape,
                           exc_info=True)
    return done

def _uv_set_plugs(shape):
    """
    A mesh's UV set plugs, which is what ``uvLink`` works in terms of.

    :param str shape: The mesh shape's name.
    :return: ``[(plug, uv set name)]``.
    :rtype: list
    """

    found = []
    for index in (cmds.getAttr(shape + '.uvSet', multiIndices=True) or []):
        plug = '{}.uvSet[{}].uvSetName'.format(shape, index)
        try:
            found.append((plug, cmds.getAttr(plug)))
        except Exception:
            continue
    return found


def _copy_uv_links(new_shape, from_shape):
    """
    Carry the texture-to-UV-set links across.

    Assigning the same shading group is not enough on a mesh with more than one
    UV set. Maya links each texture to a PARTICULAR UV set per mesh, and a mesh
    that has just been created has none of those links - so every texture falls
    back to the first set. On a character with a second set for decals or
    lightmaps, the result is a correctly-shaded mesh with its textures reading
    off the wrong coordinates: not an error, just wrong, and wrong in a way that
    looks like a UV problem rather than a link problem.

    Matched by UV set NAME rather than index, because the copy's sets are in
    whatever order the copy made them.

    :param str new_shape: The mesh to link.
    :param str from_shape: The mesh to read from.
    :return: How many links were made.
    :rtype: int
    """

    source_plugs = _uv_set_plugs(from_shape)
    if len(source_plugs) < 2:
        # One set is the common case and needs nothing: with nowhere else to
        # fall back to, the default is already right.
        return 0

    destinations = {name: plug for plug, name in _uv_set_plugs(new_shape)}
    made = 0
    for plug, name in source_plugs:
        if name not in destinations:
            logger.warning('%s has no UV set called "%s" to link to.', new_shape, name)
            continue
        try:
            textures = cmds.uvLink(uvSet=plug, query=True) or []
        except Exception:
            logger.warning('Could not read the texture links on %s.', plug,
                           exc_info=True)
            continue
        for texture in textures:
            try:
                cmds.uvLink(make=True, uvSet=destinations[name], texture=texture)
                made += 1
            except Exception:
                logger.warning('Could not link %s to %s.', texture,
                               destinations[name], exc_info=True)
    return made

@_safe
def suggest_solver_vertices(source, count=DEFAULT_SOLVER_POINTS, target=None,
                            select=True, rounds=10, separation=0.45, affine=True,
                            progress=None):
    """
    Pick a good set of solver vertices for you.

    Every real use of this tool starts the same way: a body or a head has far
    more vertices than the guard allows, so someone has to pick a few hundred,
    spread out, spanning three dimensions. That is a tedious job with a right
    answer, which makes it a job for the tool.

    Two ways of doing it, and the difference is large
    -------------------------------------------------
    **Without a target** it is farthest-point sampling: start from the vertex
    furthest from the centre, then repeatedly take the vertex furthest from
    everything already picked. An even covering of the surface, which is the
    best that can be done knowing only the source.

    **With a target** it does better, because it can check its own work. Both
    meshes are known, so the error of any candidate point set is COMPUTABLE: fit
    the deformation, evaluate it at every vertex, and see where it misses. So it
    fits, looks at where it is wrong, puts the next points there, and refits.

    Even coverage is the wrong objective. It spends points evenly whether the
    deformation needs them or not - and a body's deformation is not even. It is
    concentrated at the chest, the shoulders and the armpits, which is exactly
    where the fit was visibly off.

    Measured against ground truth, `Female_Average1` to `Male_Heavy1`, error in
    scene units on a 177-unit body, and deviation of a garment carried across:

    ======================  ==========  =========  ===============
    picking                 mean        worst      garment worst
    ======================  ==========  =========  ===============
    spread, 300 points      0.733       3.693      3.225
    spread, 1000 points     0.421       3.029      1.342
    spread, 2000 points     0.339       1.658      1.230
    error-driven, 600       0.411       1.282      0.888
    error-driven, 1000      0.281       1.111      0.591
    error-driven, 1500      0.213       1.054      0.408
    ======================  ==========  =========  ===============

    Error-driven at 1000 points beats spread at 2000 on every column while
    solving a matrix a quarter the size. The worst-case column is the one that
    shows: an average of 0.4 units is invisible, a single vertex 3.2 units out
    is a dent in a shoulder.

    :param source: The mesh to pick on.
    :param int count: How many to pick. The solve grows as the cube of this.
    :param target: The mesh being deformed to. Given, the pick is error-driven
        and much better; omitted, it is an even spread.
    :param bool select: Also select them in the scene.
    :param int rounds: How many fit-look-add passes. More is slightly better and
        proportionally slower.
    :param float separation: How far apart new points must be, as a fraction of
        the current set's spacing. Stops a whole round landing in one crease.
        0 turns it off, which measurably hurts.
    :param bool affine: Match the polynomial setting the transfer will use, so
        the points are chosen for the solve that will actually run.
    :return: The chosen vertex indices.
    :rtype: list(int)
    """

    import maya.api.OpenMaya as om

    shape = _mesh_shape(source)
    total = shape.numVertices()
    count = int(count)
    if count < 4:
        # Four is the minimum that can span three dimensions, which the affine
        # term needs. Fewer is not a small mistake, it is a different answer.
        raise ValueError('Pick at least 4 vertices - fewer cannot span three '
                         'dimensions, and the solve needs them to.')
    if count >= total:
        chosen = list(range(total))
        if select:
            _select_vertices(shape, chosen)
        return chosen, ('{} has only {} vertices, so all of them are used.'
                        .format(shape, total))

    def coordinates(mesh):
        selection = om.MSelectionList()
        selection.add(mesh.name())
        points = om.MFnMesh(selection.getDagPath(0)).getPoints(om.MSpace.kObject)
        return [(p.x, p.y, p.z) for p in points]

    source_points = coordinates(shape)

    try:
        import numpy
    except ImportError:
        numpy = None

    target_points = None
    if target is not None and numpy is not None:
        target_shape = _mesh_shape(target)
        if target_shape.numVertices() != total:
            raise ValueError('{} has {} vertices and {} has {}. They must share '
                             'topology.'.format(shape, total, target_shape,
                                                target_shape.numVertices()))
        target_points = coordinates(target_shape)

    if numpy is None:
        chosen = _spread_pick_slow(source_points, count)
        note = ('Picked {} vertices spread over {}, out of {}. (numpy is not '
                'available, so the better error-driven pick could not be used.)'
                .format(len(chosen), shape.getParent() or shape, total))
    elif target_points is None:
        chosen = _spread_pick(numpy.array(source_points, dtype=float), count)
        note = ('Picked {} vertices spread over {}, out of {}. Pass the mesh you '
                'are deforming TO for a considerably better set.'
                .format(len(chosen), shape.getParent() or shape, total))
    else:
        chosen, worst = _error_driven_pick(
            numpy, numpy.array(source_points, dtype=float),
            numpy.array(target_points, dtype=float), count, rounds, separation,
            affine, progress=progress)
        note = ('Picked {} vertices on {}, chosen where the transfer to {} is '
                'hardest. Worst remaining error {:.3f} scene units.'
                .format(len(chosen), shape.getParent() or shape,
                        _mesh_shape(target).getParent() or _mesh_shape(target),
                        worst))

    chosen = sorted(int(index) for index in chosen)
    if select:
        _select_vertices(shape, chosen)
    return chosen, note


def _spread_pick(coordinates, count):
    """
    Farthest-point sampling. Even covering, knowing only the source.

    Deterministic: seeded from the point furthest from the centre, and
    ``argmax`` breaks ties on the lowest index.

    :param coordinates: (n, 3) array of points.
    :param int count: How many to take.
    :return: Indices.
    :rtype: list
    """

    import numpy
    centre = coordinates.mean(axis=0)
    best = int(numpy.argmax(((coordinates - centre) ** 2).sum(axis=1)))
    chosen = [best]
    nearest = ((coordinates - coordinates[best]) ** 2).sum(axis=1)
    for _ in range(count - 1):
        best = int(numpy.argmax(nearest))
        chosen.append(best)
        nearest = numpy.minimum(
            nearest, ((coordinates - coordinates[best]) ** 2).sum(axis=1))
    return chosen


def _spread_pick_slow(coordinates, count):
    """
    The same, without numpy. Slow on a dense mesh, but it beats refusing to work
    on a machine missing a package.

    :param list coordinates: ``[(x, y, z)]``.
    :param int count: How many to take.
    :return: Indices.
    :rtype: list
    """

    total = len(coordinates)
    cx = sum(c[0] for c in coordinates) / total
    cy = sum(c[1] for c in coordinates) / total
    cz = sum(c[2] for c in coordinates) / total
    nearest = [(c[0] - cx) ** 2 + (c[1] - cy) ** 2 + (c[2] - cz) ** 2
               for c in coordinates]
    best = nearest.index(max(nearest))
    chosen = [best]
    anchor = coordinates[best]
    nearest = [(c[0] - anchor[0]) ** 2 + (c[1] - anchor[1]) ** 2 +
               (c[2] - anchor[2]) ** 2 for c in coordinates]
    for _ in range(count - 1):
        best = nearest.index(max(nearest))
        chosen.append(best)
        anchor = coordinates[best]
        for index, c in enumerate(coordinates):
            distance = ((c[0] - anchor[0]) ** 2 + (c[1] - anchor[1]) ** 2 +
                        (c[2] - anchor[2]) ** 2)
            if distance < nearest[index]:
                nearest[index] = distance
    return chosen


def _solve_rbf(numpy, centres, destinations, affine):
    """
    The same system the C++ solver builds, in numpy.

    This is a SELECTION heuristic, not the transfer - the transfer is still done
    by the plug-in. So the two cannot disagree about the answer; the worst a
    difference here could do is choose slightly different points.

    :param centres: (n, 3) solver points on the source.
    :param destinations: (n, 3) where they go on the target.
    :param bool affine: Include the linear polynomial block.
    :return: The solution, and whether it carries an affine block.
    """

    count = len(centres)
    matrix = numpy.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=2)
    if affine:
        poly = numpy.hstack([numpy.ones((count, 1)), centres])
        system = numpy.zeros((count + 4, count + 4))
        system[:count, :count] = matrix
        system[:count, count:] = poly
        system[count:, :count] = poly.T
        right = numpy.zeros((count + 4, 3))
        right[:count] = destinations
    else:
        system = matrix
        right = destinations
    solution, _, _, _ = numpy.linalg.lstsq(system, right, rcond=None)
    return solution


def _apply_rbf(numpy, solution, centres, points, affine, chunk=2000):
    """
    Evaluate the fitted field, in chunks so a dense mesh cannot exhaust memory.

    :return: (n, 3) moved points.
    """

    count = len(centres)
    weights = solution[:count]
    polynomial = solution[count:] if affine else None
    out = numpy.empty_like(points)
    for start in range(0, len(points), chunk):
        block = points[start:start + chunk]
        distances = numpy.linalg.norm(block[:, None, :] - centres[None, :, :], axis=2)
        moved = distances @ weights
        if polynomial is not None:
            moved += polynomial[0] + block @ polynomial[1:]
        out[start:start + chunk] = moved
    return out


def _error_driven_pick(numpy, source, target, count, rounds, separation, affine,
                       progress=None):
    """
    Fit, find where the fit is wrong, put the next points there, refit.

    The residual is scored on EVERY vertex, not a sample of them. Scoring a
    4,000-vertex subsample runs four times faster and leaves the worst error
    almost unchanged in the mean while nearly doubling it at the maximum
    (1.92 against 1.05) - because a vertex that is never scored never gets a
    point put near it, and the worst error simply hides in the part that was not
    looked at. The maximum is the column that shows on a mesh.

    :param progress: Optional ``f(picked, wanted, worst)`` called once a round.
        Return False from it to stop early and keep what has been chosen. **This is
        where the waiting happens** - the C++ solve that follows is 0.18 s against
        7.49 s of picking on a 16,747-vertex body, so a progress bar driven from
        anywhere else is reporting on the wrong 2%.
    :return: ``(indices, worst remaining error)``.
    :rtype: tuple
    """

    seed = max(8, count // 7)
    chosen = list(_spread_pick(source, min(seed, count)))
    per_round = max(1, (count - len(chosen)) // max(1, rounds))
    worst = float('inf')

    while len(chosen) < count:
        centres = source[chosen]
        solution = _solve_rbf(numpy, centres, target[chosen], affine)
        moved = _apply_rbf(numpy, solution, centres, source, affine)
        error = numpy.linalg.norm(moved - target, axis=1)
        worst = float(error.max())
        error[chosen] = -1.0

        # Keep new points apart, or a whole round lands in one crease and buys
        # far less than it costs.
        spacing = numpy.linalg.norm(centres[:, None, :] - centres[None, :, :], axis=2)
        numpy.fill_diagonal(spacing, numpy.inf)
        gap = separation * float(numpy.median(spacing.min(axis=1)))

        taken = source[chosen]
        added = 0
        wanted = min(per_round, count - len(chosen))
        for candidate in numpy.argsort(-error):
            if error[candidate] <= 0 or added >= wanted:
                break
            if gap > 0.0 and float(numpy.linalg.norm(
                    taken - source[candidate], axis=1).min()) < gap:
                continue
            chosen.append(int(candidate))
            taken = numpy.vstack([taken, source[candidate]])
            added += 1
        if added == 0:
            # Nothing left far enough from what is already there.
            break

        if progress is not None and progress(len(chosen), count, worst) is False:
            # Asked to stop. What is chosen so far is a valid, if smaller, set.
            break

    return chosen, worst


def _select_vertices(shape, indices):
    """
    Select vertices by index, in chunks Maya will accept.

    :param shape: The mesh.
    :param list indices: Vertex indices.
    """

    name = shape.name()
    items = ['{}.vtx[{}]'.format(name, index) for index in indices]
    cmds.select(clear=True)
    # A single select of several thousand components can blow the command's
    # argument limit, so it goes in batches.
    for start in range(0, len(items), 500):
        cmds.select(items[start:start + 500], add=True)

@_safe
def retarget_shapes(source, target, shapes, solver_vertices=None, sphere_anchors=0,
                    regularisation=0.0, affine=True,
                    max_solver_points=DEFAULT_MAX_SOLVER_POINTS,
                    place_on_target=True, shaders='shape'):
    """
    Rebuild ``shapes`` - sculpted on ``source`` - onto ``target``.

    :param source: The mesh the shapes were sculpted on.
    :param target: The mesh to move them to. Same topology as ``source``.
    :param list shapes: The meshes to carry across - anything sitting on
        ``source``. Correctives share its topology; a garment or a prop does not
        have to, and does not need to.
    :param list solver_vertices: Source vertex indices to solve on. None uses
        whatever vertices are selected; nothing selected uses every vertex.
    :param int sphere_anchors: Extra points spread over the bounding sphere, the
        source's paired to the target's, so the solve has something outside the
        mesh to push against. 0 is off. A few hundred is the usual choice, and
        it is also the fix for solver vertices that all lie in one plane.
    :param float regularisation: Added to the matrix diagonal. 0 passes exactly
        through every solver vertex; a small value trades that for stability and
        is the way out when two of them sit on top of each other.
    :param bool affine: Add the linear polynomial term. On, a target that is
        simply the source moved, scaled or rotated is reproduced exactly; off,
        the result drifts between the solver points, which is what the tool this
        replaces did. Off is only for reproducing that behaviour.
    :param int max_solver_points: Refuse a solve above this many points. 0
        removes the guard, which is not advised - the cost is cubic.
    :param bool place_on_target: Move each result to sit on ``target``.

        The solve works in OBJECT space, as the tool this replaces did, so what
        comes out is the shape change and nothing else. When the meshes are laid
        out side by side by their TRANSFORMS - which is how a set of body
        variants is usually arranged - every result then lands back at the
        original's position, stacked on top of each other and impossible to
        look at, even though each one is correct.

        This puts each result where its target is, by carrying the
        ``shape -> source`` relationship onto ``target``. Turn it off for the
        old behaviour, which is what you want if the outputs are going straight
        into a blendShape on the original.
    :param str shaders: Where the new meshes get their shading. One of
        :data:`SHADER_SOURCES`.

        ``'shape'`` takes it from the mesh each result was made from - a
        retargeted shirt keeps the shirt's material. ``'target'`` takes it from
        the mesh it was deformed to, for correctives that should look like the
        head they now belong to. ``'none'`` leaves them unassigned, which is what
        the command does on its own: assigned to nothing at all, not even
        initialShadingGroup, so they render as nothing.
    :return: The new meshes, one per shape, in the order given.
    :rtype: list(pm.nt.Transform)
    """

    if shaders not in SHADER_SOURCES:
        raise ValueError('shaders must be one of {}, got {!r}.'
                         .format(list(SHADER_SOURCES), shaders))

    available, reason = plugin_is_available()
    if not available:
        raise RuntimeError(reason)

    if not shapes:
        raise ValueError('Give at least one shape to retarget.')

    source_shape = _mesh_shape(source)
    target_shape = _mesh_shape(target)

    # Check the topology here rather than letting the command find out halfway
    # through: this way nothing has been created when it fails.
    source_count = source_shape.numVertices()
    if target_shape.numVertices() != source_count:
        raise ValueError('{} has {} vertices and {} has {}. The two meshes have to share '
                         'topology for a transfer to mean anything.'
                         .format(source_shape, source_count, target_shape,
                                 target_shape.numVertices()))
    # NOTHING is checked about the shapes' topology, deliberately. What the
    # solve builds is a function of POSITION, so it applies to any mesh sitting
    # in the source's space whatever its vertex count. The first version of this
    # refused a mismatch, which broke the main use: one garment, fitted to a base
    # body, refitted onto each body variant.
    for shape in shapes:
        _mesh_shape(shape)

    if solver_vertices is None:
        solver_vertices = selected_vertex_indices()
    solver_vertices = sorted({int(index) for index in solver_vertices})
    for index in solver_vertices:
        if index < 0 or index >= source_count:
            raise ValueError('Vertex {} is not on a mesh with {} vertices.'
                             .format(index, source_count))

    used = len(solver_vertices) or source_count
    if max_solver_points and used > max_solver_points:
        # Say it here, in the caller's own terms, rather than letting the command
        # say it in the script editor. Same refusal either way, but a UI can put
        # this in front of someone.
        raise ValueError('That would solve on {} points. The cost grows as the cube of '
                         'the count, so select a few hundred well-spread vertices on the '
                         'source instead, or raise max_solver_points if you mean it.'
                         .format(used))

    # The command reads its solver vertices from the SELECTION - which is how an
    # artist picks them, and avoids a flag carrying thousands of integers. Restore
    # whatever was selected afterwards, because a tool that eats your selection
    # is a tool people stop using.
    previous = cmds.ls(selection=True, long=True) or []
    try:
        if solver_vertices:
            cmds.select(['{}.vtx[{}]'.format(source_shape.name(), index)
                         for index in solver_vertices], replace=True)
        else:
            cmds.select(clear=True)

        made = cmds.mcaRetargetShapes(source=source_shape.name(),
                                      target=target_shape.name(),
                                      shape=[_mesh_shape(shape).name() for shape in shapes],
                                      sphereAnchors=int(sphere_anchors),
                                      regularization=float(regularisation),
                                      affine=bool(affine),
                                      maxSolverPoints=int(max_solver_points))
    finally:
        if previous:
            cmds.select(previous, replace=True)
        else:
            cmds.select(clear=True)

    nodes = [pm.PyNode(name) for name in (made or [])]

    if place_on_target:
        _place_on_target(nodes, shapes, source_shape, target_shape)

    assigned = 0
    for node, shape in zip(nodes, shapes):
        made_shape = _mesh_shape(node).name()
        if shaders != 'none':
            origin = target_shape if shaders == 'target' else _mesh_shape(shape)
            if _copy_shaders(made_shape, origin.name()):
                assigned += 1
        # Always, whatever the shader choice: the links belong to the GEOMETRY's
        # own UV sets, and are wrong the moment there is more than one set
        # regardless of where the shading came from.
        _copy_uv_links(made_shape, _mesh_shape(shape).name())

    message = ('Rebuilt {} shape(s) on {}, solving on {} vertices.'
               .format(len(nodes), target_shape.getParent() or target_shape, used))
    if shaders != 'none' and assigned < len(nodes):
        # Say it rather than leaving someone to find black meshes at render time.
        message += ('  {} of them had no shading to copy from.'
                    .format(len(nodes) - assigned))
    return nodes, message


def _place_on_target(nodes, shapes, source_shape, target_shape):
    """
    Move each result to sit on the target.

    The solve is in object space, so a result comes back carrying its source
    shape's transform. Where the meshes are laid out side by side by their
    transforms, that puts every result back at the original's position - all of
    them, on top of each other.

    What is carried across is the shape's position RELATIVE to the source, onto
    the target: ``shape * inverse(source) * target``. With everything on
    identity, which is the common case, that is a no-op, so this cannot move
    anything that was already in the right place.

    :param list nodes: The new transforms.
    :param list shapes: The meshes they were made from, in the same order.
    :param source_shape: The 'deform from' mesh.
    :param target_shape: The 'deform to' mesh.
    """

    def world(mesh):
        parent = mesh.getParent()
        return (parent or mesh).getMatrix(worldSpace=True)

    try:
        offset = world(source_shape).inverse() * world(target_shape)
    except Exception:
        logger.warning('Could not work out where to put the results; leaving them '
                       'where the shapes were.', exc_info=True)
        return

    for node, shape in zip(nodes, shapes):
        try:
            node.setMatrix(world(_mesh_shape(shape)) * offset, worldSpace=True)
        except Exception:
            logger.warning('Could not place %s on the target.', node, exc_info=True)


@_safe
def retarget_to_many(source, targets, shapes, auto_pick=None, **kwargs):
    """
    Carry the same shapes across to several targets in one call.

    The workflow this exists for: one garment fitted to a base body, refitted
    onto every body variant. Three variants is three solves, and doing them by
    hand means setting the same shape list up three times and then working out
    which ``_retargeted`` mesh belongs to which body.

    Each target gets its own solve - the deformation from ``source`` to that
    target is a different field - and the results are named
    ``<shape>_<target>`` rather than ``<shape>_retargeted``, so a dozen outputs
    are still tellable apart.

    :param source: The mesh everything is fitted to now.
    :param list targets: The meshes to refit onto. Each must share ``source``'s
        topology.
    :param list shapes: The meshes to carry across.
    :param int auto_pick: Choose solver vertices SEPARATELY FOR EACH TARGET, this
        many of them. Only used when no ``solver_vertices`` are given.

        Worth the extra picks. The error-driven pick depends on the target - it
        puts points where the deformation to THAT body is hardest - so a set
        chosen for the heavy male is not the right set for the small female.
        Measured, carrying one garment onto three bodies, worst error in scene
        units:

        =================  ===========  ==============
        body               its own pick  heavy's pick
        =================  ===========  ==============
        Female_Small1      0.368         0.482
        Male_Average1      0.650         0.843
        Male_Heavy1        1.140         1.140
        =================  ===========  ==============

        About a quarter better on the worst vertex, for a few seconds per target.
    :param kwargs: Passed through to :func:`retarget_shapes`.
    :return: ``{target name: [new meshes]}``.
    :rtype: dict
    """

    if not targets:
        raise ValueError('Give at least one mesh to deform to.')

    source_shape = _mesh_shape(source)

    # Check the cost ONCE, here, rather than letting each target discover it.
    # The solver-point count does not depend on which target it is, so a run of
    # five bodies was reporting the same 300-word refusal five times over - a
    # wall of identical text whose one actionable sentence was buried in it.
    vertices = kwargs.get('solver_vertices')
    if vertices is None:
        vertices = selected_vertex_indices()
    per_target = bool(auto_pick) and not vertices
    used = (int(auto_pick) if per_target
            else (len(set(vertices or [])) or source_shape.numVertices()))
    limit = kwargs.get('max_solver_points', DEFAULT_MAX_SOLVER_POINTS)
    if limit and used > limit:
        raise ValueError(
            'That would solve on {:,} points, {} times over. The cost grows as the '
            'cube of the count. Use "Auto-pick" (or suggest_solver_vertices) to take '
            'a few hundred well-spread vertices off {}, or raise max_solver_points '
            'if you mean it.'.format(used, len(targets), source_shape))

    made = {}
    failures = []

    for target in targets:
        if per_target:
            # Picked against THIS target, because the error-driven pick depends
            # on where the deformation to this particular body is hardest.
            picked = suggest_solver_vertices(
                source_shape, count=int(auto_pick), target=target, select=False,
                affine=kwargs.get('affine', True))
            if not picked['ok']:
                failures.append('{}: {}'.format(target, picked['message']))
                continue
            kwargs['solver_vertices'] = picked['result']

        response = retarget_shapes(source_shape, target, shapes, **kwargs)
        if not response['ok']:
            # Carry on rather than stopping: nine good results and one named
            # failure beats one failure and no results, and the caller gets both.
            failures.append('{}: {}'.format(target, response['message']))
            continue

        target_label = _mesh_shape(target).getParent() or _mesh_shape(target)
        renamed = []
        for shape, node in zip(shapes, response['result']):
            label = _mesh_shape(shape).getParent() or _mesh_shape(shape)
            renamed.append(pm.rename(node, '{}_{}'.format(
                str(label).split('|')[-1], str(target_label).split('|')[-1])))
        made[str(target_label)] = renamed

    if failures and not made:
        raise RuntimeError('Nothing was retargeted. ' + '  '.join(failures))

    message = 'Carried {} shape(s) across to {} target(s){}.'.format(
        len(shapes), len(made),
        ', each with its own solver vertices' if per_target else '')
    if failures:
        message += '  {} failed: {}'.format(len(failures), '  '.join(failures))
    return made, message

@_safe
def read_blendshape(source, blendshape=None):
    """
    What a blendShape node actually holds: every weight, and every target under
    it including in-betweens.

    :param source: The mesh to find a blendShape on, when one is not given.
    :param blendshape: The blendShape node. None finds the one on ``source``.
    :return: ``{'blendshape', 'weights': [{'name', 'index', 'targets':
        [{'weight', 'mesh', 'item'}]}]}``.
    :rtype: dict
    """

    node, _ = _resolve_blendshape(source, blendshape)
    return {'blendshape': str(node), 'weights': _blendshape_weights(node)}, (
        '{} has {} weight(s).'.format(node, len(_blendshape_weights(node))))


def _resolve_blendshape(source, blendshape):
    """
    :return: ``(blendShape node, note)``.
    :raises ValueError: If there is nothing to work with.
    """

    source_shape = _mesh_shape(source)
    note = ''
    if blendshape is None:
        found = list(pm.listHistory(source_shape, type='blendShape'))
        if not found:
            raise ValueError('There is no blendShape on {}. Pass one, or pass the '
                             'shapes themselves to retarget_shapes.'.format(source_shape))
        blendshape = found[0]
        if len(found) > 1:
            # Say which one, rather than silently taking the first of several.
            note = ('{} has {} blendShapes; used {}. Pass the one you meant if that '
                    'is wrong.'.format(source_shape, len(found), blendshape))
    return pm.PyNode(blendshape), note


def _blendshape_weights(node):
    """
    Read every weight and every target item under it.

    **In-betweens live at their own item indices, and reading only 6000 drops
    them silently.** A blendShape stores each target under
    ``inputTargetItem[i]``, where ``i`` is ``5000 + weight * 1000`` - so the full
    target is 6000 and an in-between at 0.5 is 5500. The first version of this
    read index 6000 and nothing else, so a face rig's in-betweens came back
    missing with a cheerful success message. That is the worst shape a bug can
    take: fewer shapes than you had, and nothing saying so.

    :param node: The blendShape PyNode.
    :return: ``[{'name', 'index', 'targets': [{'weight', 'mesh', 'item'}]}]``.
    :rtype: list
    """

    name = str(node)
    weights = []
    for index in (cmds.getAttr(name + '.weight', multiIndices=True) or []):
        group = '{}.inputTarget[0].inputTargetGroup[{}]'.format(name, index)
        items = cmds.getAttr(group + '.inputTargetItem', multiIndices=True) or []
        targets = []
        for item in sorted(items):
            plug = '{}.inputTargetItem[{}].inputGeomTarget'.format(group, item)
            connected = cmds.listConnections(plug, source=True, destination=False,
                                             shapes=True) or []
            if not connected:
                continue
            targets.append({'weight': (item - 5000) / 1000.0,
                            'mesh': connected[0], 'item': item})
        if targets:
            weights.append({'name': _weight_name(name, index), 'index': index,
                            'targets': targets})
    return weights


def _weight_name(node, index):
    """
    The channel name an animator sees, which is an alias on the weight plug.

    :param str node: The blendShape node.
    :param int index: Weight index.
    :return: The alias, or the plain plug name when there is none.
    :rtype: str
    """

    try:
        alias = cmds.aliasAttr('{}.weight[{}]'.format(node, index), query=True)
        if alias:
            return alias
    except Exception:
        pass
    return 'weight[{}]'.format(index)


@_safe
def retarget_blendshape(source, target, blendshape=None, rebuild=True, **kwargs):
    """
    Rebuild a whole blendShape - every target and every in-between - on another
    mesh.

    This is the job the tool exists for at scale: a head with forty correctives
    and a second head that needs the same forty, wired up the same way, with the
    same channel names.

    What it keeps that the loose-meshes version did not
    ----------------------------------------------------
    **In-betweens.** They live at their own item indices and were being dropped
    silently - see :func:`_blendshape_weights`.

    **Channel names.** The rebuilt node's weights are aliased back to the
    original's names, so anything driving ``head.smile_L`` still drives
    ``head_big.smile_L``. Without that, a rebuilt blendShape's channels are named
    after the retargeted meshes and nothing that referenced them still works.

    **Which target is which.** The result says, per weight, which new mesh is the
    full target and which are in-betweens at what weight - a flat list of
    meshes cannot.

    :param source: The mesh the shapes were sculpted on.
    :param target: The mesh to move them to.
    :param blendshape: The blendShape node. None finds the one on ``source``.
    :param bool rebuild: Also build a blendShape on ``target`` from the results.
        Off gives just the meshes.
    :param kwargs: Passed through to :func:`retarget_shapes`.
    :return: ``{'blendshape', 'meshes', 'weights'}``.
    :rtype: dict
    """

    node, note = _resolve_blendshape(source, blendshape)
    weights = _blendshape_weights(node)
    if not weights:
        raise ValueError('{} has no live target meshes to read - its targets were '
                         'deleted after it was made. Rebuild them, or retarget the '
                         'meshes you have.'.format(node))

    # One solve for the whole set: every target of every weight, in one call, so
    # they all come from the same deformation.
    flat = [entry['mesh'] for weight in weights for entry in weight['targets']]
    response = retarget_shapes(source, target, flat, **kwargs)
    if not response['ok']:
        raise RuntimeError(response['message'])

    made = list(response['result'])
    moved = iter(made)
    for weight in weights:
        for entry in weight['targets']:
            entry['new'] = next(moved)

    built = None
    if rebuild:
        built = _rebuild_blendshape(target, weights, str(node))

    in_betweens = sum(1 for w in weights for e in w['targets'] if e['item'] != 6000)
    message = ('Rebuilt {} weight(s) with {} target(s){} on {}.'
               .format(len(weights), len(flat),
                       ' including {} in-between(s)'.format(in_betweens)
                       if in_betweens else '',
                       _mesh_shape(target).getParent() or target))
    if built:
        message += '  Built {}.'.format(built)
    if note:
        message += '  ' + note

    result = {'blendshape': built,
              'meshes': [str(mesh) for mesh in made],
              'weights': [{'name': w['name'], 'index': w['index'],
                           'targets': [{'weight': e['weight'], 'mesh': str(e['new'])}
                                       for e in w['targets']]}
                          for w in weights]}
    return result, message


def _rebuild_blendshape(target, weights, original_name):
    """
    Build a blendShape on ``target`` matching the original's shape.

    Full targets go on first, in the original's weight order, then each
    in-between is added to its own weight. The channel names are aliased back
    afterwards: Maya names a weight after the mesh that made it, so without this
    step every channel would be called ``smile_L_retargeted`` and nothing that
    referenced the original would still find it.

    :param target: The mesh to put the blendShape on.
    :param list weights: As :func:`_blendshape_weights` returns, each with a
        ``new`` mesh on every target.
    :param str original_name: Used to name the new node.
    :return: The new blendShape node's name, or None if it could not be built.
    :rtype: str or None
    """

    base = _mesh_shape(target).getParent() or _mesh_shape(target)
    full = []
    for weight in weights:
        chosen = next((e for e in weight['targets'] if e['item'] == 6000), None)
        if chosen is None:
            # No full target, only in-betweens. Maya has nowhere to hang them.
            logger.warning('Weight "%s" has no target at weight 1.0; skipped.',
                           weight['name'])
            continue
        full.append((weight, chosen))

    if not full:
        return None

    try:
        node = cmds.blendShape([str(entry['new']) for _, entry in full], str(base),
                               name='{}_{}'.format(original_name,
                                                   str(base).split('|')[-1]))[0]
    except Exception:
        logger.warning('Could not build a blendShape on %s.', base, exc_info=True)
        return None

    for position, (weight, _entry) in enumerate(full):
        for extra in weight['targets']:
            if extra['item'] == 6000:
                continue
            try:
                cmds.blendShape(node, edit=True, inBetween=True,
                                target=(str(base), position, str(extra['new']),
                                        extra['weight']))
            except Exception:
                logger.warning('Could not add the in-between at %s on "%s".',
                               extra['weight'], weight['name'], exc_info=True)

        # Put the original channel name back.
        try:
            current = cmds.aliasAttr('{}.weight[{}]'.format(node, position),
                                     query=True)
            if current != weight['name']:
                cmds.aliasAttr(weight['name'], '{}.weight[{}]'.format(node, position))
        except Exception:
            logger.warning('Could not rename the channel to "%s".', weight['name'],
                           exc_info=True)

    return node


@_safe
def estimate_cost(source, solver_vertices=None, sphere_anchors=0, affine=True):
    """
    What a solve would cost, before starting it.

    The point of this is that a UI can show the number before someone commits to
    waiting for it. The tool this replaces printed its point count to stdout,
    which on Windows goes to a console nobody has open - so a solve about to take
    ten minutes looked exactly like one about to take two seconds.

    :param source: The source mesh.
    :param list solver_vertices: Indices to solve on. None reads the selection.
    :param int sphere_anchors: Extra bounding-sphere points.
    :param bool affine: Whether the polynomial term is on - it adds four rows.
    :return: ``{'points', 'megabytes', 'refused'}``.
    :rtype: dict
    """

    source_count = _vertex_count(source)
    if solver_vertices is None:
        solver_vertices = selected_vertex_indices()
    points = (len(set(solver_vertices)) or source_count) + max(0, int(sphere_anchors))
    side = points + (4 if affine else 0)
    megabytes = side * side * 8.0 / (1024.0 * 1024.0)
    refused = points > DEFAULT_MAX_SOLVER_POINTS
    return ({'points': points, 'megabytes': megabytes, 'refused': refused},
            '{} points, a {:.1f} MB matrix{}.'
            .format(points, megabytes,
                    ' - refused at the default limit' if refused else ''))
