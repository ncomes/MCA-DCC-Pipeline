"""
Walking Maya's DAG: parents, children, and the colours drawn on a node.

The DAG is a tree, and almost every rigging operation starts by asking it a question -
which joints lie between these two, what is the top of this hierarchy, what are this
chain's children in order. These are those questions.

What was wrong before:

- **``get_between_nodes`` looped forever** when the two nodes were not in the same
  hierarchy. It walked up from ``last`` looking for ``first``; when it ran off the top of
  the DAG ``current_node`` became ``None``, and the loop condition ``first != current_node``
  stayed true while the body kept appending ``None`` to the list. It logged a warning and
  then hung, growing a list of ``None`` until Maya ran out of memory. Twenty-one places in
  the pipeline call this.
- **``_get_deepest_child`` raised on any node with a shape.** Its guard was a bare
  ``return`` - which is ``None``, not the two values the caller unpacks - and the children it
  recursed into came from ``getChildren()`` with no filter, so a transform's own shape node
  went in and ``child_node, child_depth = _get_deepest_child(...)`` failed with ``TypeError:
  cannot unpack non-sequence NoneType``. Since the function exists to find the end of a
  joint chain, and joints in a rig have shapes hung off them, this was most calls.
- **``get_ordered_hierarchy`` and ``get_children_in_order`` were two functions for one
  question**, with different argument names and different answers about whether the root is
  included. Nothing called the first one. It is gone.
- **``create_line_between`` was a second copy of ``rig_utils.create_line_between``**, and the
  three callers all use that one. Dropping it takes this module's import of
  ``mca.mya.deformations.cluster`` with it, which is what made a leaf utility depend on the
  deformation code.
- **``set_node_color`` raised in a batch Maya** whenever it was given an outliner colour.
  It finished the colouring and then called ``mel.eval('AEdagNodeCommonRefreshOutliners();')``
  unconditionally, and that procedure belongs to Maya's attribute editor scripts, which a
  headless Maya never loads: ``RuntimeError: Cannot find procedure``. Every batch build or
  export that coloured an outliner entry stopped there.
- The module docstring said "Parameter data for working with the facial rigs", and
  ``get_node_color_data``'s docstring held a dict literal that does not parse.
"""

# python imports

# software specific imports
import pymel.core as pm
import maya.cmds as cmds
import maya.mel as mel

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.utils import naming


logger = log.MCA_LOGGER


def get_between_nodes(first, last, node_type=None):
    """
    Every node from ``first`` down to ``last``, both ends included.

    :param first: The node higher up the hierarchy.
    :type first: pm.nt.DagNode or str
    :param last: The node below it.
    :type last: pm.nt.DagNode or str
    :param node_type: A PyNode class to keep only nodes of that type - ``pm.nt.Joint``.
    :return: The nodes, ``first`` at the front. Empty when ``first`` is not above ``last``:
        the version this replaces logged a warning and then looped forever appending None.
    :rtype: list(pm.nt.DagNode)
    """

    if not isinstance(first, pm.nt.DagNode):
        first = pm.PyNode(first)
    if not isinstance(last, pm.nt.DagNode):
        last = pm.PyNode(last)

    walked = [last]
    current = last
    while current != first:
        current = current.getParent()
        if not current:
            logger.warning('%s is not in the hierarchy above %s.', first, last)
            return []
        walked.append(current)

    walked.reverse()
    if node_type:
        walked = [node for node in walked if isinstance(node, node_type)]
    return walked


def get_all_parents(obj, node_type=None):
    """
    Every parent of a node, from its own parent up to the scene root.

    With a ``node_type``, the walk stops at the first parent that is not of that type - so
    for a joint inside a group, filtering for ``pm.nt.Joint`` gives the joints up to the root
    of the skeleton and not the group holding it.

    :param obj: The node to start from.
    :type obj: pm.nt.DagNode or str
    :param node_type: A PyNode class to stop at.
    :return: The parents, closest first.
    :rtype: list(pm.nt.DagNode)
    """

    found = []
    current = pm.PyNode(obj).getParent()
    while current:
        if node_type and not isinstance(current, node_type):
            break
        found.append(current)
        current = current.getParent()
    return found


def get_absolute_parent(obj_node, node_type=None, inclusive=True):
    """
    The top of a node's hierarchy.

    :param pm.nt.Transform obj_node: The node to start from.
    :param node_type: A PyNode class to stop at, so the answer is the top node of that type
        rather than the top of the whole DAG.
    :param bool inclusive: When the node has no parent, answer with the node itself. False
        answers None.
    :return: The topmost parent.
    :rtype: pm.nt.Transform or None
    """

    if not isinstance(obj_node, pm.nt.Transform):
        return None

    last_parent = obj_node if inclusive else None
    found_parent = obj_node.getParent()
    while found_parent:
        if node_type and not isinstance(found_parent, node_type):
            break
        last_parent = found_parent
        found_parent = found_parent.getParent()
    return last_parent


def get_absolute_child(start_node, node_type=None, inclusive=True):
    """
    The deepest child below a node - the end of a chain.

    :param pm.nt.Transform start_node: The node to start from.
    :param node_type: A PyNode class to keep to, so the answer is the deepest node of that
        type - ``pm.nt.Joint`` for the tip of a joint chain.
    :param bool inclusive: When nothing is below the node, answer with the node itself.
        False answers None.
    :return: The deepest child.
    :rtype: pm.nt.Transform or None
    """

    deepest_child, _ = _get_deepest_child(start_node, node_type=node_type)
    if not inclusive and deepest_child == start_node:
        return None
    return deepest_child


def _get_deepest_child(start_node, depth=0, node_type=None):
    """
    The deepest node below one, and how far down it is.

    :param pm.nt.Transform start_node: The node to look below.
    :param int depth: How far down this call already is.
    :param node_type: A PyNode class to keep to.
    :return: The deepest node and its depth. Always a pair - the version this replaces
        answered a bare ``None`` for anything that was not a transform, and its caller
        unpacked the result, so a transform with a shape hung off it raised TypeError.
    :rtype: tuple(pm.nt.Transform, int)
    """

    if not isinstance(start_node, pm.nt.Transform):
        return start_node, depth

    deepest_child = start_node
    deepest_depth = depth
    # Transforms only: getChildren() with no filter hands back the node's own shape, which
    # is what the old version recursed into and then choked on.
    for child_node in start_node.getChildren(type=pm.nt.Transform):
        if node_type and not isinstance(child_node, node_type):
            continue
        child_node, child_depth = _get_deepest_child(child_node, depth=depth + 1,
                                                     node_type=node_type)
        if child_depth > deepest_depth:
            deepest_child = child_node
            deepest_depth = child_depth
    return deepest_child, deepest_depth


def get_children_in_order(start_node, node_type=None, start=True):
    """
    Every node below one, in the order the DAG holds them.

    Order matters: a joint chain read out of order builds a rig with its segments swapped,
    and Maya's own ``listRelatives(allDescendents=True)`` answers deepest-first.

    :param pm.nt.Transform start_node: The node to read from.
    :param node_type: A PyNode class to keep to - ``pm.nt.Joint``.
    :param bool start: Include ``start_node`` itself at the front. The recursion passes
        False; callers leave it alone.
    :return: The nodes, in DAG order. Empty when ``start_node`` is not a transform - the
        version this replaces answered None there, and its own recursion then failed adding
        None to a list.
    :rtype: list(pm.nt.Transform)
    """

    if not isinstance(start_node, pm.nt.Transform):
        logger.warning('%s is not a transform.', start_node)
        return []

    found_children = start_node.getChildren(type=node_type or pm.nt.Transform)
    ordered = ([start_node] + list(found_children)) if start else list(found_children)
    for child_node in found_children:
        ordered += get_children_in_order(child_node, node_type, False)
    return ordered


def get_primary_axis(node):
    """
    Which axis a node points down, and whether it points the positive way.

    Read from the node's first child's translation where it has one, because a joint sits at
    its own origin and it is the *next* joint's offset that says which way the bone runs.

    :param pm.nt.Transform node: The node to read.
    :return: The axis - ``'x'``, ``'y'`` or ``'z'`` - and whether it is positive. A node with
        no offset at all answers ``('x', True)``, there being nothing to read.
    :rtype: tuple(str, bool)
    """

    child_node = lists.get_first_in_list(node.getChildren(type=pm.nt.Transform))
    target_node = child_node or node

    largest = 0.0
    primary_axis = 'x'
    axis_is_positive = True
    for axis_name, value in zip('xyz', target_node.t.get()):
        if abs(value) > largest:
            largest = abs(value)
            primary_axis = axis_name
            axis_is_positive = value > 0
    return primary_axis, axis_is_positive


def parent_shape_node(from_objs, to_obj, maintain_offset=False, replace=True,
                      freeze_transform=True, delete_original=True, swap_names=True):
    """
    Move the shapes off one or more transforms onto another.

    This is how a control gets its curve: the curve is drawn as its own transform, then its
    shape is moved under the control and the empty transform thrown away.

    :param from_objs: The transforms whose shapes are moving.
    :type from_objs: pm.nt.Transform or list(pm.nt.Transform)
    :param pm.nt.Transform to_obj: The transform the shapes move onto.
    :param bool maintain_offset: Keep each shape where it is in the world, rather than
        letting it move with the new parent's transform.
    :param bool replace: Delete whatever shapes ``to_obj`` already had.
    :param bool freeze_transform: Bake each source transform's translate and rotate into its
        shape first, so the shape does not jump.
    :param bool delete_original: Delete the now-empty source transforms.
    :param bool swap_names: Name the incoming shapes after the shape ``to_obj`` already had.
    :return: The last shape that was moved, or None when there was nothing to move.
    :rtype: pm.nt.Shape or None
    """

    from_objs = lists.force_list(from_objs)
    if not from_objs or not to_obj:
        return None

    if freeze_transform:
        for obj in from_objs:
            pm.makeIdentity(obj, apply=True, translate=True, rotate=True, scale=False)

    if maintain_offset:
        for obj in from_objs:
            # Parent in, freeze, and parent back out: that bakes the destination's transform
            # into the shape, so the shape does not move when it lands.
            pm.parent(obj, to_obj)
            pm.makeIdentity(obj, apply=True, translate=True, rotate=True, scale=False)
            pm.parent(obj, world=True)

    existing_shapes = to_obj.getShapes()
    if swap_names and existing_shapes:
        wanted_name = naming.get_basename(str(existing_shapes[0]))
        for obj in from_objs:
            shapes = obj.getShapes()
            if shapes:
                shapes[0].rename(wanted_name)

    if replace and existing_shapes:
        pm.delete(existing_shapes)

    new_shape = None
    for obj in from_objs:
        shapes = obj.getShapes()
        if not shapes:
            continue
        new_shape = pm.parent(shapes, to_obj, add=True, shape=True)[0]

    # Rename once, at the end, rather than inside the loop: the basename call is there to get
    # around a shape ending up with its namespace twice in its name.
    landed = to_obj.getShapes()
    if landed:
        shape_name = naming.get_basename(landed[0])
        for index, shape in enumerate(landed):
            shape.rename(shape_name if index == 0 else '{}{}'.format(shape_name, index + 1))

    if delete_original:
        pm.delete(from_objs)
    return new_shape


def get_node_color_data(node):
    """
    Everything Maya knows about how a node is coloured.

    :param node: The node or shape to read.
    :type node: pm.PyNode or str
    :return: The override colour as an index and as RGB, whether the override and the RGB
        mode are on, and the outliner colour. Colours are floats from 0.0 to 1.0.
    :rtype: dict

    Example::

        >>> get_node_color_data('nurbsCircleShape1')
        {'overrideColor': 0,
         'overrideEnabled': True,
         'overrideColorRGB': [0.4, 0.07, 0.07],
         'overrideRGBColors': True,
         'useOutlinerColor': False,
         'outlinerColor': [0.0, 0.0, 0.0]}
    """

    node = pm.PyNode(node)
    override_rgb_colors = node.attr('overrideRGBColors').get()
    return {
        'overrideColor': node.attr('overrideColor').get(),
        'overrideEnabled': node.attr('overrideEnabled').get(),
        'overrideColorRGB': node.attr('overrideColorRGB').get() if override_rgb_colors
        else [0.0, 0.0, 0.0],
        'overrideRGBColors': override_rgb_colors,
        'useOutlinerColor': node.attr('useOutlinerColor').get(),
        'outlinerColor': node.attr('outlinerColor').get(),
    }


def set_node_color(node, color, outliner_color=None, use_outliner_color=False):
    """
    Colour a node or a shape.

    :param node: The node or nodes to colour.
    :type node: pm.PyNode or str or list
    :param color: One of Maya's colour indices, or an RGB triple from 0.0 to 1.0.
    :type color: int or tuple(float, float, float)
    :param outliner_color: An RGB triple for the outliner entry, or None to leave it.
    :type outliner_color: tuple(float, float, float) or None
    :param bool use_outliner_color: Turn the outliner colour on as well as setting it.
    """

    nodes = [pm.PyNode(one) for one in lists.force_list(node)]

    for one in nodes:
        enabled = one.attr('overrideEnabled')
        if not enabled.get():
            enabled.set(True)

        # A bool is an int in Python, and True would be read as colour index 1. Anything that
        # is not a plain int is treated as RGB.
        if isinstance(color, int) and not isinstance(color, bool):
            one.attr('overrideColor').set(color)
        else:
            rgb_mode = one.attr('overrideRGBColors')
            if not rgb_mode.get():
                rgb_mode.set(True)
            one.attr('overrideColorRGB').set(color)

        if outliner_color:
            if use_outliner_color:
                one.attr('useOutlinerColor').set(True)
            one.attr('outlinerColor').set(outliner_color)

    if outliner_color:
        _refresh_outliners()


def _refresh_outliners():
    """
    Make the outliner notice a colour change.

    It does not notice on its own. The procedure that tells it to is part of Maya's
    attribute editor scripts, which a batch Maya never loads - so the version this replaces
    raised ``RuntimeError: Cannot find procedure "AEdagNodeCommonRefreshOutliners"`` for any
    headless build or export that set an outliner colour, having already done the colouring
    it was asked for.
    """

    if cmds.about(batch=True):
        return
    try:
        mel.eval('AEdagNodeCommonRefreshOutliners();')
    except RuntimeError:
        logger.debug('The outliner would not refresh.', exc_info=True)
