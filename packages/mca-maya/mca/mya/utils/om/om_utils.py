"""
Getting at Maya's API from pymel, and the two mesh questions that need it.

``maya.api.OpenMaya`` is the fast path: a loop over ten thousand vertices through
``maya.cmds`` takes minutes, and through the API it takes a moment. What it needs first is an
``MDagPath`` or an ``MObject``, which is what the pipeline's PyNodes are not, so these do that
conversion.

What was wrong before:

- **``om2_change_curve_start_time`` could not do the thing it documented.** Called with no
  offset - "if no shift length is given it will zero the animation" - it reached
  ``if offset > 0`` with ``offset`` still ``None``, which in Python 3 is ``TypeError: '>' not
  supported between instances of 'NoneType' and 'int'``. The whole body sat inside a bare
  ``except:``, so the call returned quietly having moved nothing. It also built an
  ``om2.MDGContext(mtime)`` and threw it away, and computed the same offset twice, once
  before the loop and once inside it.
- **``get_om2_keyframe_range_from_scene`` read only rotation curves.** It iterated
  ``om2.MFn.kAnimCurveTimeToAngular`` and nothing else, so a scene animated in translation
  only - a camera move, a prop slide - reported no animation at all.
- **``get_om2_keyframes_from_pynode_list`` answered a tuple where it documented a list**:
  ``(None, None)`` when it found nothing, so a caller iterating the result got two Nones
  instead of no frames.
- Those three, and ``pynode_list_to_om2_selection_list``, had no callers anywhere in the
  pipeline. They are gone, and with them this module's imports of ``OpenMayaAnim`` and
  ``ma_decorators`` - the second of which made an API utility depend on the decorator layer.
"""

# python imports

# software specific imports
import maya.api.OpenMaya as om2
import pymel.core as pm

# mca imports
from mca.common import log


logger = log.MCA_LOGGER


def pynode_to_om2_mobject_mdag_path(node):
    """
    The API's handles for a PyNode: its path in the DAG, and the node itself.

    :param pm.nt.DagNode node: The node to convert. It has to be a DAG node - a node with a
        place in the scene hierarchy. A dependency node has no path.
    :return: The DAG path and the MObject, in that order, or ``(None, None)`` when the node
        is not a DAG node.
    :rtype: tuple(om2.MDagPath, om2.MObject)
    """

    if not isinstance(node, pm.nt.DagNode):
        logger.error('%s is a %s, not a DAG node, so it has no DAG path.',
                     node, type(node).__name__)
        return None, None

    selection = om2.MSelectionList()
    selection.add(node.longName())
    return selection.getComponent(0)


def get_closest_joint_to_vertex(vertex, mesh_name, joint_list):
    """
    Which of a set of joints is nearest to one vertex.

    Used when transferring weights: a vertex whose influence has gone away is given to
    whichever joint is closest to where it actually is.

    Both the vertex and the joints are read in world space, so this is the distance an
    animator would measure, not the distance in the mesh's local space.

    .. note:: The joint positions are read on every call. A caller walking thousands of
        vertices against the same joints is doing that work each time - which is what
        ``skin_utils`` does, and is worth hoisting if it ever becomes the slow part.

    :param int vertex: The vertex's index.
    :param str mesh_name: The mesh holding it.
    :param joint_list: The joints to choose between, by name.
    :type joint_list: list(str)
    :return: The name of the nearest joint, or None when there were no joints to choose from.
    :rtype: str or None
    """

    if not joint_list:
        return None

    selection = om2.MSelectionList()
    selection.add(mesh_name)
    mesh = om2.MFnMesh(selection.getDagPath(0))
    vertex_position = om2.MVector(mesh.getPoint(vertex, space=om2.MSpace.kWorld))

    closest_joint = None
    closest_distance = float('inf')
    for joint_name in joint_list:
        selection.clear()
        selection.add(joint_name)
        joint_position = om2.MFnTransform(selection.getDagPath(0)).translation(om2.MSpace.kWorld)
        distance = (vertex_position - joint_position).length()
        if distance < closest_distance:
            closest_distance = distance
            closest_joint = joint_name
    return closest_joint


def get_adjacent_vertices(vertex):
    """
    The vertices sharing an edge with one vertex.

    :param str vertex: The vertex, as Maya names a component - ``'headShape.vtx[12]'``.
    :return: The indices of the vertices around it.
    :rtype: list(int)
    """

    selection = om2.MSelectionList()
    selection.add(vertex)
    dag_path, component = selection.getComponent(0)

    # The iterator walks whatever the component holds. Given one vertex that is one step;
    # given a set of them it is each in turn, which is why the result is extended rather
    # than assigned.
    vertex_iterator = om2.MItMeshVertex(dag_path, component)
    adjacent = []
    while not vertex_iterator.isDone():
        adjacent.extend(vertex_iterator.getConnectedVertices())
        vertex_iterator.next()
    return adjacent
