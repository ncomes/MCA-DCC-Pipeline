"""
Vertices: naming them, finding their opposite numbers, and mirroring them.

Most of this exists for the face. A face mesh is mirrored by a stored map - a dictionary of
vertex number to vertex number, worked out once and saved - because finding the opposite vertex
by geometry every time is slow and gets it wrong wherever the mesh is not perfectly symmetrical.
:func:`get_opposite_vertices` is how that map is built; :func:`mirror_vertices` and
:func:`mirror_mesh` are how it is used.

What was wrong before:

- **Mirroring in world space read world coordinates and wrote local ones.** ``mirror_vertex``
  asked for the source position with ``ws=world`` and then set the target with a plain
  ``pm.xform(target, t=...)``, which is object space whatever ``world`` was. The middle-vertex
  loop in ``mirror_mesh`` did the same to itself. So every world-space mirror moved vertices by
  the difference between the mesh's transform and the origin - correct only for a mesh sitting
  at the origin with no rotation or scale, which is the one case anybody tested.
- **A mirror map with whole numbers in it raised.** ``mesh_name + '.vtx[' + inverse_index + ']'``
  concatenates, so a map whose values are integers - which is what ``json`` gives back for
  anything written as a number - is a ``TypeError``. Both sides are put through ``str`` now.
- **``mirror_mesh`` indexed the right-hand list with the left-hand list's index** and nothing
  checked they were the same length, so a half-built map raised ``IndexError`` partway through,
  leaving the mesh half mirrored.
- **``convert_to_vertices`` passed the built-in ``object``** to ``filterExpand`` on its NURBS
  branch, and the branch below it put ``selectionMask`` inside the ``.format()`` call rather
  than the command, so no mask was passed at all - and its format string was missing the dot
  before ``cv``. Three faults in nine lines, and no callers. Gone, with
  ``get_inverse_vertex_selection`` (no callers, and it replaced the user's selection without
  putting it back) and ``fix_mesh_components_selection_visualization`` (no callers).
- ``get_closest_vertex_to_object`` said it answered a vertex name; it answers an index.
- Tabs for indentation, in a package that is otherwise spaces.
"""

# python imports

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import strings
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The default mirror: negate X, leave Y and Z. A tuple per axis rather than an axis name,
#: because a caller mirroring a blend shape sometimes wants two axes at once.
MIRROR_X = (-1, 1, 1)


def get_vertices_as_numbers(vertices, as_string=False):
    """
    Strip everything off a vertex but its number.

    ``'head_mesh.vtx[412]'`` answers ``412``. Anything already a bare number passes through.

    :param vertices: A vertex, or a list of them, named or numbered.
    :param bool as_string: Answer with the numbers as text.
    :return: One number per vertex given.
    :rtype: list(int) or list(str)
    """

    if not isinstance(vertices, (list, tuple, set)):
        vertices = [vertices]

    numbers = []
    for vert in vertices:
        # str first: callers pass a mix of names, pm.MeshVertex components and plain ints.
        vert = str(vert)
        if '.' in vert:
            vert = vert.split('.')[-1]
        found = strings.get_numbers_from_string(vert, as_string=True)
        if not found:
            logger.warning('%s has no vertex number in it, so it was skipped.', vert)
            continue
        numbers.append(found[0] if as_string else int(found[0]))
    return numbers


def get_closest_vertex_to_object(mesh, obj):
    """
    The index of the vertex on a mesh nearest an object.

    :param pm.nt.Transform mesh: The mesh to look on.
    :param obj: Anything with a world position.
    :return: The vertex's index, not its name.
    :rtype: int
    """

    mesh_shape = mesh.getShape()
    closest_node = pm.createNode('closestPointOnMesh',
                                 name=naming.make_maya_safe_name('{0}_closest_point'.format(obj)))
    try:
        mesh_shape.outMesh >> closest_node.inMesh
        mesh_shape.worldMatrix[0] >> closest_node.inputMatrix
        closest_node.inPosition.set(pm.xform(obj, query=True, worldSpace=True, translation=True))
        return closest_node.closestVertexIndex.get()
    finally:
        pm.delete(closest_node)


def get_opposite_vertices(vertex_list):
    """
    For each vertex, the index of the vertex nearest its reflection across X.

    This is how a mirror map is built in the first place. It is measured in world space with a
    locator, so the mesh wants to be at the origin while it runs - which is the state the face
    pipeline builds in.

    :param list vertex_list: The vertices to find opposites for.
    :return: One index per vertex given.
    :rtype: list(int)
    """

    if not vertex_list:
        return []

    opposite_list = []
    temp_locator = pm.spaceLocator()
    try:
        for vert in vertex_list:
            position = pm.xform(vert, query=True, worldSpace=True, translation=True)
            temp_locator.translate.set((position[0] * -1, position[1], position[2]))
            mesh = pm.ls(vert, objectsOnly=True)[0].getParent()
            opposite_list.append(get_closest_vertex_to_object(mesh, temp_locator))
    finally:
        pm.delete(temp_locator)
    return opposite_list


def mirror_vertex(vertex, opposite_vertex, axis=MIRROR_X, world=False):
    """
    Move one vertex to the mirror of another's position.

    :param str vertex: The vertex to read the position from.
    :param str opposite_vertex: The vertex to move.
    :param tuple axis: What to multiply each of X, Y and Z by.
    :param bool world: Work in world space rather than the mesh's own.
    """

    position = pm.xform(vertex, query=True, translation=True, worldSpace=world)
    # worldSpace on both halves. Reading in world and writing in object space was the bug.
    pm.xform(opposite_vertex,
             translation=[value * axis[index] for index, value in enumerate(position)],
             worldSpace=world)


def mirror_vertices(mesh, vertex_mapping, vertices=None, axis=MIRROR_X, world=False):
    """
    Mirror some of a mesh's vertices onto their opposite numbers, through a stored map.

    The map is ``{vertex number: opposite vertex number}``, both sides as text, and it holds
    both directions - left to right and right to left - so mirroring "the vertices I have
    selected" works whichever side they are on.

    :param mesh: The mesh they belong to.
    :param dict vertex_mapping: The stored map.
    :param list vertices: Which vertices to mirror, named or numbered. None means all of them.
    :param tuple axis: What to multiply each of X, Y and Z by.
    :param bool world: Work in world space rather than the mesh's own.
    :return: How many vertices were moved.
    :rtype: int
    """

    if not vertex_mapping or not isinstance(vertex_mapping, dict):
        logger.warning('Mirroring needs a dictionary mapping vertex numbers to their opposites.')
        return 0

    mesh_name = str(mesh)
    if vertices is None:
        vertices = list(vertex_mapping.keys())
    else:
        vertices = get_vertices_as_numbers(vertices, as_string=True)

    moved = 0
    for vert in vertices:
        vert = str(vert)
        if vert not in vertex_mapping:
            continue
        # str on both: a map read back from JSON has whole numbers on one side often enough,
        # and the old version concatenated them straight into a name.
        mirror_vertex('{0}.vtx[{1}]'.format(mesh_name, vert),
                      '{0}.vtx[{1}]'.format(mesh_name, vertex_mapping[vert]),
                      axis=axis, world=world)
        moved += 1
    return moved


def mirror_mesh(left_vertices, right_vertices, middle_vertices, mesh_name, axis=MIRROR_X, world=False):
    """
    Mirror a whole mesh: swap each left/right pair over, and fold each middle vertex onto itself.

    The two side lists are read in step, so entry *n* of one is the opposite number of entry *n*
    of the other. They have to be the same length; a shorter right-hand list used to raise
    partway through, leaving half a mirrored mesh behind.

    :param list left_vertices: One side, named or numbered.
    :param list right_vertices: The other side, in the same order.
    :param list middle_vertices: The vertices on the seam.
    :param mesh_name: The mesh they belong to.
    :param tuple axis: What to multiply each of X, Y and Z by.
    :param bool world: Work in world space rather than the mesh's own.
    :return: How many vertices were moved.
    :rtype: int
    """

    mesh_name = str(mesh_name)
    left_vertices = get_vertices_as_numbers(left_vertices or [], as_string=True)
    right_vertices = get_vertices_as_numbers(right_vertices or [], as_string=True)
    middle_vertices = get_vertices_as_numbers(middle_vertices or [], as_string=True)

    if len(left_vertices) != len(right_vertices):
        logger.warning('The two sides do not match - %s vertices on the left and %s on the '
                       'right - so the mesh was not mirrored.',
                       len(left_vertices), len(right_vertices))
        return 0

    moved = 0
    for left, right in zip(left_vertices, right_vertices):
        left_vertex = '{0}.vtx[{1}]'.format(mesh_name, left)
        right_vertex = '{0}.vtx[{1}]'.format(mesh_name, right)

        # Both positions are read before either is written, because this is a swap.
        left_position = cmds.xform(left_vertex, query=True, translation=True, worldSpace=world)
        right_position = cmds.xform(right_vertex, query=True, translation=True, worldSpace=world)
        pm.xform(left_vertex,
                 translation=[value * axis[index] for index, value in enumerate(right_position)],
                 worldSpace=world)
        pm.xform(right_vertex,
                 translation=[value * axis[index] for index, value in enumerate(left_position)],
                 worldSpace=world)
        moved += 2

    for vert in middle_vertices:
        vertex = '{0}.vtx[{1}]'.format(mesh_name, vert)
        position = pm.xform(vertex, query=True, translation=True, worldSpace=world)
        pm.xform(vertex,
                 translation=[value * axis[index] for index, value in enumerate(position)],
                 worldSpace=world)
        moved += 1
    return moved


def get_uv_coordinates(obj, mesh):
    """
    The UV coordinate of the point on a mesh nearest an object.

    This is how a face flag remembers where on the head it belongs: the position is no use
    across two different heads, the UV is.

    :param obj: Anything with a world position.
    :param pm.nt.Transform mesh: The mesh to measure against.
    :return: U and V.
    :rtype: list(float)
    """

    closest_node = pm.createNode('closestPointOnMesh',
                                 name=naming.make_maya_safe_name('cpm_{0}'.format(obj)))
    try:
        mesh.getShape().outMesh >> closest_node.inMesh
        mesh.getShape().worldMatrix[0] >> closest_node.inputMatrix
        closest_node.inPosition.set(pm.xform(obj, query=True, worldSpace=True, translation=True))
        return [closest_node.parameterU.get(), closest_node.parameterV.get()]
    finally:
        pm.delete(closest_node)


def set_vertex_symmetry(side=None, symmetry=True):
    """
    Turn Maya's symmetric modelling on, but only for a pose on the centre.

    A pose that lives on one side is sculpted on that side and mirrored afterwards through the
    stored map; symmetry would fight that. Only a centre pose - a jaw drop, a brow raise - is
    sculpted symmetrically, so that is the only case this turns it on for. The version before
    said the same thing in a nested if/else that read as though it might do something else.

    :param str side: Which side the pose is on.
    :param bool symmetry: Whether symmetry is wanted at all.
    :return: Whether symmetry ended up on.
    :rtype: bool
    """

    wanted = bool(symmetry) and side == 'center'
    pm.symmetricModelling(symmetry=wanted)
    return wanted
