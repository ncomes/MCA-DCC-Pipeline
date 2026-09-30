"""
Generic helpers for working with uvPin nodes and mesh UV lookups.

Nothing in here knows about rigs or flags; it is the tooling a uvPin based setup needs:

- Reading a pin: the world position and frame axes of a coordinate, and whether the coordinate
  lands on the mesh at all.
- Sampling a pin: UV change per world unit along the tangents, and how far a coordinate can
  travel inside its UV shell before falling off the mesh.
- Mesh UV lookups through the API: closest point and normal, the UV at a world point in any UV
  set, and the original (pre-deformer) shape to write UV edits to.
- Building a planar projected UV set for a connected, non-overlapping region of faces around a
  world point, written straight to the original shape so a deformed mesh gains no construction
  history.

Creating the pin itself lives in ``mca.mya.modeling.rivets.create_uv_pin``.

Side effects: the sampling functions temporarily set pin coordinates and restore them;
``create_planar_uv_set`` adds or replaces a UV set on the mesh's original shape.

This module came over almost as it was. It is recent work - it has its constants named, its
side effects written down and its pin coordinates restored in ``finally`` - and there was little
to find. What there was:

- ``create_planar_uv_set`` raised ``pm.MayaNodeError`` when no face around the given point could
  be projected. That exception is Maya's for "there is no such node", and a caller catching it to
  handle a missing mesh would swallow this instead. It is a ``ValueError`` now: the argument is
  what is wrong.
- The occlusion test read ``hit[3]``, the hit *triangle*, where the face index is ``hit[2]``. It
  came to the same answer, since ``closestIntersection`` answers None when nothing is hit at all,
  but it was checking a number it did not mean.
- ``get_visible_region_faces`` tested its ``radius`` for truth rather than for ``None``, so a
  radius of ``0`` - a request for the seed face and nothing else - was read as no radius at all
  and the region grew over the whole mesh.
- **``is_pin_valid`` always answered True**, which is the one real bug in here and it is a large
  one, because every sampling function in the module is built on it. It looked for an all-zero
  output matrix; Maya answers with the *identity* for a coordinate that lands nowhere, and the
  identity's first row is ``(1, 0, 0)``, which passed the "is this row longer than nothing" test as
  readily as a real normal. So ``find_uv_extent`` walked to the 0 or 1 limit whatever the shell
  actually was, ``get_uv_shell_extents`` reported the whole map, and ``get_uv_shell_rect`` never
  shrank anything. See that function for the detail.
"""

# python imports
import math

# software specific imports
import maya.api.OpenMaya as om
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

# UV offset used when sampling a pin to work out how far one UV unit travels in world space.
UV_SAMPLE_DELTA = 0.01
# Step and safety margin (in UV units) used when walking outward to find the edge of a pin's UV
# shell.
UV_SHELL_STEP = 0.005
UV_SHELL_MARGIN = 0.01
# Faces whose normal is within this angle (degrees) of the projection direction are candidates for a
# planar
# projected UV set. Faces steeper than this are close to edge-on and give stretched UVs.
PROJECTION_ANGLE_LIMIT = 80.0
# Border (in UV units) kept around a planar projected set so the shell sits inside 0..1.
PROJECTION_UV_BORDER = 0.02
# uvPin output matrix rows: X normal (row 0), U tangent (row 1), V tangent (row 2) when normalAxis=0
# / tangentAxis=1.
PIN_NORMAL_ROW = 0
PIN_U_ROW = 1
PIN_V_ROW = 2
# Which entry of MFnMesh.closestIntersection's answer holds the face that was hit.
HIT_FACE_INDEX = 2
# What a uvPin outputs for a coordinate that lands nowhere: the identity, flat.
IDENTITY_MATRIX = (1.0, 0.0, 0.0, 0.0,
                   0.0, 1.0, 0.0, 0.0,
                   0.0, 0.0, 1.0, 0.0,
                   0.0, 0.0, 0.0, 1.0)
# How far from the identity a matrix has to be before the pin counts as resolved.
PIN_IDENTITY_TOLERANCE = 1e-6


# --- Mesh lookups
# ------------------------------------------------------------------------------------------

def get_mesh_fn(shape):
    """
    Returns an API mesh function set and dag path for a mesh shape.

    :param pm.nt.Mesh shape: The mesh shape node.
    :return: Function set and dag path.
    :rtype: tuple(om.MFnMesh, om.MDagPath)
    """

    selection = om.MSelectionList()
    selection.add(shape.name())
    dag_path = selection.getDagPath(0)
    return om.MFnMesh(dag_path), dag_path


def get_original_shape(mesh):
    """
    Returns the shape UV edits should be written to: the original (pre-deformer) shape when the mesh
    is deformed, otherwise the mesh shape itself. Deformers pass UV sets through from their input,
    so editing the original shape keeps the skin and blend shape stack untouched and adds no
    construction history.

    :param pm.nt.Transform mesh: The shaped mesh transform.
    :return: The shape to write UVs to.
    :rtype: pm.nt.Mesh
    """

    shape = mesh.getShape()
    original_plugs = cmds.deformableShape(shape.name(), originalGeometry=True) or []
    if original_plugs and original_plugs[0]:
        return pm.PyNode(original_plugs[0].split('.')[0])
    return shape


def get_closest_point_normal(mesh, position):
    """
    Returns the closest surface point, world normal and face index of a mesh for a world position.

    :param pm.nt.Transform mesh: The shaped mesh transform to sample.
    :param pm.dt.Vector position: World position to find the closest point for.
    :return: Closest world point on the mesh, the unit normal there, and the face it lies on.
    :rtype: tuple(pm.dt.Vector, pm.dt.Vector, int)
    """

    mesh_fn, _ = get_mesh_fn(mesh.getShape())
    closest_point, normal, face_index = mesh_fn.getClosestPointAndNormal(
        om.MPoint(position.x, position.y, position.z), om.MSpace.kWorld)
    return (pm.dt.Vector(closest_point.x, closest_point.y, closest_point.z),
            pm.dt.Vector(normal.x, normal.y, normal.z).normal(),
            face_index)


def get_uv_at_point(mesh, position, uv_set=None):
    """
    Returns the UV of the closest surface point to a world position, in a given UV set.

    :param pm.nt.Transform mesh: The shaped mesh transform to sample.
    :param pm.dt.Vector position: World position.
    :param str uv_set: UV set to read. Defaults to the mesh's current set.
    :return: U, V.
    :rtype: list[float]
    """

    mesh_fn, _ = get_mesh_fn(mesh.getShape())
    if not uv_set:
        uv_set = mesh_fn.currentUVSetName()
    u_value, v_value, _ = mesh_fn.getUVAtPoint(
        om.MPoint(position.x, position.y, position.z), om.MSpace.kWorld, uv_set)
    return [u_value, v_value]


# --- Planar projected UV sets
# ----------------------------------------------------------------------------------

def get_visible_region_faces(mesh, seed_face, direction, angle_limit=PROJECTION_ANGLE_LIMIT,
                            radius=None):
    """
    Collects a connected region of faces around a seed face that can be planar projected without
    overlaps: the region grows over faces facing the projection direction, optionally capped by a
    distance from the seed, and every face hidden behind another along the direction is dropped.

    :param pm.nt.Transform mesh: The shaped mesh transform to scan.
    :param int seed_face: Face index the region grows from.
    :param pm.dt.Vector direction: World projection direction (typically the surface normal at the
        seed).
    :param float angle_limit: Max angle in degrees between a face normal and the direction.
    :param float radius: Optional max world distance from the seed face centre for a face to be
        included.
    :return: Face indices of the region.
    :rtype: list[int]
    """

    mesh_fn, dag_path = get_mesh_fn(mesh.getShape())
    direction_vector = om.MVector(direction.x, direction.y, direction.z).normal()
    min_dot = math.cos(math.radians(angle_limit))
    face_iter = om.MItMeshPolygon(dag_path)

    # Pass 1: flood fill over facing faces, so unconnected geometry that happens to face the same
    # way is skipped.
    face_iter.setIndex(seed_face)
    seed_center = face_iter.center(om.MSpace.kWorld)
    region = set()
    pending = [seed_face]
    while pending:
        face_index = pending.pop()
        if face_index in region:
            continue
        face_iter.setIndex(face_index)
        if face_iter.getNormal(om.MSpace.kWorld) * direction_vector < min_dot:
            continue
        # `is not None`, not a truth test: a radius of 0 is a request for nothing but the seed
        # face, and the version this replaces read it as no radius at all.
        if radius is not None and \
                (face_iter.center(om.MSpace.kWorld) - seed_center).length() > radius:
            continue
        region.add(face_index)
        pending.extend(int(x) for x in face_iter.getConnectedFaces())

    # Pass 2: occlusion. A face with another face in front of it along the projection direction
    # would share UV space with that face, so drop it. The ray starts just off the face so it does
    # not hit the face it started from.
    accel = mesh_fn.autoUniformGridParams()
    visible = []
    for face_index in region:
        face_iter.setIndex(face_index)
        center = face_iter.center(om.MSpace.kWorld)
        ray_source = om.MFloatPoint(center + direction_vector * 0.01)
        hit = mesh_fn.closestIntersection(ray_source, om.MFloatVector(direction_vector),
                                          om.MSpace.kWorld, 1e6, False, accelParams=accel)
        # closestIntersection answers None when the ray hits nothing. hit[2] is the face it hit -
        # the version this replaces read hit[3], the triangle, which came to the same answer but
        # was not the number it meant.
        if hit and hit[HIT_FACE_INDEX] != -1:
            continue
        visible.append(face_index)
    return sorted(visible)


def create_planar_uv_set(mesh, uv_set_name, position, angle_limit=PROJECTION_ANGLE_LIMIT,
                         radius=None, border=PROJECTION_UV_BORDER):
    """
    Builds a UV set holding a single seam free shell: the connected, non overlapping region of faces
    around a world point is planar projected along the surface normal there and uniformly fitted
    into 0..1.

    UVs are written straight to the original shape through the API, so a skinned mesh gains no
    construction history and its other UV sets are untouched. Faces outside the region carry no UVs
    in this set. An existing set of the same name is replaced.

    :param pm.nt.Transform mesh: The shaped mesh transform that gets the new set.
    :param str uv_set_name: Name of the UV set to (re)create.
    :param pm.dt.Vector position: World position the region grows from; the surface normal here is
        the projection direction.
    :param float angle_limit: Max angle in degrees between a face normal and the projection
        direction.
    :param float radius: Optional max world distance from the position for faces to be included.
    :param float border: UV border kept around the shell inside 0..1.
    :return: The UV set name.
    :rtype: str
    """

    surface_point, normal, seed_face = get_closest_point_normal(mesh, position)
    face_list = get_visible_region_faces(mesh, seed_face, normal, angle_limit, radius)
    if not face_list:
        # A ValueError, not pm.MayaNodeError: the node is fine, the point given is not. Maya's
        # own exception means "there is no such node", and a caller catching that to handle a
        # missing mesh would have swallowed this.
        raise ValueError('No usable faces around {} on {}, so the UV set {} was not built.'
                         .format(position, mesh, uv_set_name))

    # Projection frame: X is the normal, Y becomes the U direction, Z the V direction. Any
    # perpendicular pair
    # works; world up gives a predictable layout unless the normal is (nearly) vertical.
    world_up = pm.dt.Vector(0, 1, 0)
    up = world_up if abs(normal.dot(world_up)) < 0.9 else pm.dt.Vector(0, 0, 1)
    u_axis = up.cross(normal).normal()
    v_axis = normal.cross(u_axis).normal()

    # Project every face vertex of the region onto the frame.
    mesh_fn, dag_path = get_mesh_fn(mesh.getShape())
    face_iter = om.MItMeshPolygon(dag_path)
    face_uvs = {}
    for face_index in face_list:
        face_iter.setIndex(face_index)
        points = face_iter.getPoints(om.MSpace.kWorld)
        offsets = [pm.dt.Vector(point.x, point.y, point.z) - surface_point for point in points]
        face_uvs[face_index] = [(offset.dot(u_axis), offset.dot(v_axis)) for offset in offsets]

    # Uniform fit into 0..1 (with a border) so U and V keep the same density and shell searches have
    # a range.
    all_u = [uv[0] for uvs in face_uvs.values() for uv in uvs]
    all_v = [uv[1] for uvs in face_uvs.values() for uv in uvs]
    span = max(max(all_u) - min(all_u), max(all_v) - min(all_v)) or 1.0
    scale = (1.0 - 2 * border) / span
    u_offset = border - min(all_u) * scale
    v_offset = border - min(all_v) * scale

    u_array = om.MFloatArray()
    v_array = om.MFloatArray()
    uv_counts = om.MIntArray([0] * mesh_fn.numPolygons)
    uv_ids = om.MIntArray()
    for face_index in face_list:
        for u_value, v_value in face_uvs[face_index]:
            uv_ids.append(len(u_array))
            u_array.append(u_value * scale + u_offset)
            v_array.append(v_value * scale + v_offset)
        uv_counts[face_index] = len(face_uvs[face_index])

    # Write to the original shape so deformers carry the set downstream without any history nodes.
    # Creating
    # a set can make it current, so the current set of both the original and the visible shape is
    # restored.
    target_shape = get_original_shape(mesh)
    target_fn, _ = get_mesh_fn(target_shape)
    target_current_set = target_fn.currentUVSetName()
    mesh_current_set = mesh_fn.currentUVSetName()
    if uv_set_name in target_fn.getUVSetNames():
        target_fn.deleteUVSet(uv_set_name)
    target_fn.createUVSet(uv_set_name)
    target_fn.setUVs(u_array, v_array, uv_set_name)
    target_fn.assignUVs(uv_counts, uv_ids, uv_set_name)
    target_fn.updateSurface()
    for shape_fn, current_set in ((target_fn, target_current_set), (mesh_fn, mesh_current_set)):
        if current_set and current_set != uv_set_name and current_set in shape_fn.getUVSetNames():
            shape_fn.setCurrentUVSetName(current_set)

    logger.info('Built the planar UV set %s on %s (%s) from %s faces.',
                uv_set_name, mesh, target_shape, len(face_list))
    return uv_set_name


# --- Reading a pin
# -------------------------------------------------------------------------------------------

def get_pin_position(uv_pin, index=0):
    """
    Returns the world position of a uvPin coordinate.

    :param pm.nt.UvPin uv_pin: The pin node to read.
    :param int index: The coordinate index on the pin.
    :return: World space position of the pinned point.
    :rtype: pm.dt.Vector
    """

    matrix_values = cmds.getAttr('{0}.outputMatrix[{1}]'.format(uv_pin, index))
    return pm.dt.Vector(matrix_values[12], matrix_values[13], matrix_values[14])


def get_pin_axis(uv_pin, row, index=0):
    """
    Returns one of the unit axes of a uvPin coordinate's output frame.

    :param pm.nt.UvPin uv_pin: The pin node to read.
    :param int row: Matrix row to read. With normalAxis=0 / tangentAxis=1: 0 is the normal, 1 the U
        tangent, 2 the V tangent (PIN_NORMAL_ROW / PIN_U_ROW / PIN_V_ROW).
    :param int index: The coordinate index on the pin.
    :return: Normalized axis vector in world space.
    :rtype: pm.dt.Vector
    """

    matrix_values = cmds.getAttr('{0}.outputMatrix[{1}]'.format(uv_pin, index))
    first = row * 4
    axis = pm.dt.Vector(matrix_values[first], matrix_values[first + 1],
                        matrix_values[first + 2])
    return axis.normal()


def is_pin_valid(uv_pin, index=0):
    """
    Checks whether a uvPin coordinate currently lands on the mesh.

    A coordinate that falls in empty UV space - outside every shell, or outside 0 to 1 - makes the
    pin output the *identity* matrix: no rotation, sitting at the world origin. That is what this
    looks for.

    The version this replaced looked for an all-zero matrix, on the stated grounds that "a
    coordinate outside every UV shell makes the pin output an all zero matrix, so the first row
    collapses to zero length". Maya does not do that. The first row of the identity is
    ``(1, 0, 0)``, whose length is 1, so the test ``abs(m[0]) + abs(m[1]) + abs(m[2]) > 0.1`` was
    true for an invalid pin exactly as for a valid one: **the function always answered True**. Every
    sampling function in this module is built on it, so ``find_uv_extent`` always walked to the 0 or
    1 limit whatever the shell actually was, and ``get_uv_shell_rect`` never shrank anything.

    .. note:: A pin that genuinely resolves to the world origin with no rotation reads as invalid.
        That is a mesh vertex at the origin with its normal along +X and its tangent along +Y, and
        no rig in this pipeline has one; the alternative is a matrix Maya does not distinguish.

    :param pm.nt.UvPin uv_pin: The pin node to read.
    :param int index: The coordinate index on the pin.
    :return: True when the pin resolves to a real surface point.
    :rtype: bool
    """

    matrix_values = cmds.getAttr('{0}.outputMatrix[{1}]'.format(uv_pin, index))
    return any(abs(value - identity) > PIN_IDENTITY_TOLERANCE
               for value, identity in zip(matrix_values, IDENTITY_MATRIX))


# --- Sampling a pin
# ------------------------------------------------------------------------------------------

def find_uv_extent(uv_pin, coord_name, direction, index=0, step=UV_SHELL_STEP,
                   margin=UV_SHELL_MARGIN):
    """
    Walks a pin coordinate in one direction until it leaves the UV shell (or hits 0 or 1) and
    returns the last coordinate value that still lands on the mesh, pulled back by a small margin.

    The pin coordinate is restored before returning. The coordinate must not have an incoming
    connection.

    :param pm.nt.UvPin uv_pin: The pin node to sample.
    :param str coord_name: 'coordinateU' or 'coordinateV'.
    :param int direction: +1 or -1.
    :param int index: The coordinate index on the pin.
    :param float step: UV increment per sample.
    :param float margin: How far inside the shell edge the extent is reported.
    :return: The furthest valid coordinate value in that direction.
    :rtype: float
    """

    coordinate = uv_pin.coordinate[index].attr(coord_name)
    base_value = coordinate.get()
    last_valid = base_value
    value = base_value
    try:
        while True:
            value += direction * step
            if value < 0.0 or value > 1.0:
                break
            coordinate.set(value)
            if not is_pin_valid(uv_pin, index):
                break
            last_valid = value
    finally:
        coordinate.set(base_value)

    if last_valid != base_value:
        # Stay a touch inside the edge so a diagonal move does not fall off the shell at the border.
        last_valid -= direction * min(margin, abs(last_valid - base_value))
    return last_valid


def get_uv_shell_extents(uv_pin, index=0, step=UV_SHELL_STEP, margin=UV_SHELL_MARGIN):
    """
    Returns how far a pin coordinate can move in U and V, both ways, before leaving its UV shell.

    :param pm.nt.UvPin uv_pin: The pin node to sample.
    :param int index: The coordinate index on the pin.
    :param float step: UV increment per sample.
    :param float margin: How far inside the shell edge the extents are reported.
    :return: {'U': (min_u, max_u), 'V': (min_v, max_v)}
    :rtype: dict[str, tuple(float, float)]
    """

    extents = {}
    for coord_name in ('U', 'V'):
        coord_attr_name = 'coordinate{0}'.format(coord_name)
        extents[coord_name] = (find_uv_extent(uv_pin, coord_attr_name, -1, index, step, margin),
                               find_uv_extent(uv_pin, coord_attr_name, 1, index, step, margin))
    return extents


def get_uv_shell_rect(uv_pin, extents=None, index=0, shrink=0.1, max_iterations=60):
    """
    Shrinks the U / V extents of a pin into a rectangle that lies fully inside the UV shell.

    get_uv_shell_extents only walks along the base U and V lines, so on a non rectangular shell the
    corners of that box can sit off the shell (the pin snaps to the origin there). This samples the
    corners and edge midpoints of the box and pulls the offending sides toward the base coordinate
    until every sample lands on the mesh. Concave notches between samples are not detected; keep the
    shells simple.

    The pin coordinate is restored before returning. The coordinates must not have incoming
    connections.

    :param pm.nt.UvPin uv_pin: The pin node to sample.
    :param dict extents: {'U': (min, max), 'V': (min, max)} to start from. Defaults to
        get_uv_shell_extents.
    :param int index: The coordinate index on the pin.
    :param float shrink: Fraction of the distance to the base coordinate a side is pulled in per
        iteration.
    :param int max_iterations: Safety cap on shrink passes.
    :return: {'U': (min_u, max_u), 'V': (min_v, max_v)} with all box corners on the shell.
    :rtype: dict[str, tuple(float, float)]
    """

    if extents is None:
        extents = get_uv_shell_extents(uv_pin, index)
    coordinate = uv_pin.coordinate[index]
    base_u = coordinate.coordinateU.get()
    base_v = coordinate.coordinateV.get()
    bounds = {'u_min': extents['U'][0], 'u_max': extents['U'][1],
              'v_min': extents['V'][0], 'v_max': extents['V'][1]}
    base = {'u_min': base_u, 'u_max': base_u, 'v_min': base_v, 'v_max': base_v}

    def sample_is_valid(u_value, v_value):
        coordinate.coordinateU.set(u_value)
        coordinate.coordinateV.set(v_value)
        return is_pin_valid(uv_pin, index)

    try:
        for _ in range(max_iterations):
            u_mid = (bounds['u_min'] + bounds['u_max']) * 0.5
            v_mid = (bounds['v_min'] + bounds['v_max']) * 0.5
            # Each sample names the sides it sits on, so a miss knows which bounds to pull in.
            samples = [(bounds['u_min'], bounds['v_min'], ('u_min', 'v_min')),
                       (bounds['u_max'], bounds['v_min'], ('u_max', 'v_min')),
                       (bounds['u_min'], bounds['v_max'], ('u_min', 'v_max')),
                       (bounds['u_max'], bounds['v_max'], ('u_max', 'v_max')),
                       (u_mid, bounds['v_min'], ('v_min',)),
                       (u_mid, bounds['v_max'], ('v_max',)),
                       (bounds['u_min'], v_mid, ('u_min',)),
                       (bounds['u_max'], v_mid, ('u_max',))]
            failed_sides = set()
            for u_value, v_value, sides in samples:
                if not sample_is_valid(u_value, v_value):
                    failed_sides.update(sides)
            if not failed_sides:
                break
            for side_name in failed_sides:
                bounds[side_name] += (base[side_name] - bounds[side_name]) * shrink
        else:
            logger.warning('%s: the shell rectangle did not converge, so the last bounds are '
                           'being used.', uv_pin)
    finally:
        coordinate.coordinateU.set(base_u)
        coordinate.coordinateV.set(base_v)

    return {'U': (bounds['u_min'], bounds['u_max']), 'V': (bounds['v_min'], bounds['v_max'])}


def measure_uv_per_unit(uv_pin, index=0, delta=UV_SAMPLE_DELTA):
    """
    Measures how much U and V change per world unit of travel along the pin's tangent axes.

    The pin coordinate is nudged by a small delta in U then V, the resulting world offset is
    projected onto the matching tangent axis, and the coordinate is restored. The sign of each
    result matches the pin's own tangent direction so a positive translate along +Y / +Z of the pin
    frame maps to +U / +V. Expects normalAxis=0 and tangentAxis=1 on the pin. The coordinates must
    not have incoming connections.

    :param pm.nt.UvPin uv_pin: The pin node to sample.
    :param int index: The coordinate index on the pin.
    :param float delta: UV offset used for the sample.
    :return: Signed U per world unit, signed V per world unit.
    :rtype: tuple(float, float)
    """

    coordinate = uv_pin.coordinate[index]
    base_u = coordinate.coordinateU.get()
    base_v = coordinate.coordinateV.get()
    base_position = get_pin_position(uv_pin, index)

    results = []
    for coord_name, row, base_value in (('coordinateU', PIN_U_ROW, base_u),
                                        ('coordinateV', PIN_V_ROW, base_v)):
        axis = get_pin_axis(uv_pin, row, index)
        coordinate.attr(coord_name).set(base_value + delta)
        offset = get_pin_position(uv_pin, index) - base_position
        coordinate.attr(coord_name).set(base_value)

        travel = offset.dot(axis)
        if abs(travel) < 1e-6:
            # Degenerate UVs (or a zero area sample). Fall back to a 1:1 mapping rather than divide
            # by zero.
            logger.warning('Could not measure the %s density on %s, so 1.0 is being used.',
                           coord_name, uv_pin)
            results.append(1.0)
            continue
        results.append(delta / travel)
    return results[0], results[1]
