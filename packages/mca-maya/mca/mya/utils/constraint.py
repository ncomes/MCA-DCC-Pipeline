"""
Constraints that do not fight what is already driving a node.

A rig constrains the same node from several places over its build, and a plain
``pm.parentConstraint`` on an axis that is locked, connected, or driven by something else
either fails outright or makes a cycle. These wrappers look first and constrain only the
axes that are free.

Maya's own spelling is the reason these functions read oddly: ``skipTranslate`` wants the
axes *not* to constrain, and the literal string ``'none'`` to mean "skip nothing". So the
list handed to Maya holds an axis name for each axis to leave alone and ``'none'`` for each
axis to drive - which is why :func:`constraint_safe_attrs` answers with that mixture.

What was wrong before:

- **An axis that was settable and unlocked but already connected fell out of the list
  entirely.** The check was ``if settable and not locked:`` then ``if no connection or the
  connection is an anim curve: append 'none'`` - with no ``else``. An axis driven by another
  constraint, an expression or a node matched neither branch, so nothing was appended and
  the list came back with two entries instead of three. Maya reads a short list as
  permission to constrain the missing axis, which is the cycle the function exists to
  prevent.
- **``get_constraint_targets`` dropped every joint.** It filtered with ``isinstance(x,
  pm.nt.Transform) and pm.nodeType(x) == 'transform'``. The second half was there for a real
  reason - a constraint's ``target`` array is connected back to the constraint node itself,
  which is also a transform, so it has to be left out - but it threw out the joints with it,
  because a joint's node type is ``'joint'``. The pipeline's animation controls *are* joints,
  drawn as none and carrying a curve shape, so the two callers that ask "what is driving this
  constraint" in order to find a flag or a bake helper were handed an empty list whenever the
  answer was a joint, which is most of the time. The constraint node is excluded by being a
  constraint now, which is what was meant.
- **It also scrambled the order of the targets.** ``list(set(...))`` has no order, and
  ``rig_component`` takes ``get_first_in_list`` of the result to decide what the constraint's
  primary target is - so which target that was changed between runs on the same rig.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists


logger = log.MCA_LOGGER

#: What Maya wants in a skip list to mean "do not skip this one".
DRIVE_IT = 'none'

#: The axes, in the order Maya expects them.
AXES = ('x', 'y', 'z')


def constraint_safe_attrs(node, attr_prefix, skip_list=None):
    """
    Which axes of a transform can be constrained, in the form Maya's skip flags want.

    :param pm.nt.Transform node: The node that would be driven.
    :param str attr_prefix: ``'t'``, ``'r'`` or ``'s'`` - translate, rotate or scale.
    :param skip_list: Axes to leave alone whatever their state - ``('x', 'y', 'z')``.
    :type skip_list: list(str) or tuple(str) or None
    :return: Three entries, one per axis: the axis's own name where it must be left alone,
        and ``'none'`` where it is free to be driven. Always three - see the module
        docstring for the bug that made it fewer.
    :rtype: list(str)
    """

    skip_list = skip_list or ()
    answer = []
    for axis in AXES:
        if axis in skip_list:
            answer.append(axis)
            continue

        node_attr = node.attr('{}{}'.format(attr_prefix, axis))
        if not node_attr.isSettable() or node_attr.isLocked():
            answer.append(axis)
            continue

        # An anim curve or an animation layer is not a rival driver: a constraint replaces
        # it, which is what the caller wants. Anything else - another constraint, an
        # expression, a node network - is, and constraining over it makes a cycle.
        connection = lists.get_first_in_list(node_attr.listConnections())
        if connection and not isinstance(connection, (pm.nt.AnimCurve, pm.nt.AnimLayer)):
            answer.append(axis)
            continue

        answer.append(DRIVE_IT)
    return answer


def parent_constraint_safe(source_node, driven_node, skip_rotate_attrs=None,
                           skip_translate_attrs=None, **kwargs):
    """
    Parent constrain one node to another, on the axes that are free.

    :param pm.nt.Transform source_node: The node that will drive.
    :param pm.nt.Transform driven_node: The node that will follow.
    :param skip_rotate_attrs: Rotate axes to leave alone.
    :type skip_rotate_attrs: list(str) or None
    :param skip_translate_attrs: Translate axes to leave alone.
    :type skip_translate_attrs: list(str) or None
    :return: The constraint, or None when no axis was free to drive.
    :rtype: pm.nt.ParentConstraint or None
    """

    if not source_node or not driven_node:
        return None

    translate = constraint_safe_attrs(driven_node, 't', skip_translate_attrs)
    rotate = constraint_safe_attrs(driven_node, 'r', skip_rotate_attrs)
    if DRIVE_IT not in translate and DRIVE_IT not in rotate:
        return None

    return pm.parentConstraint(source_node, driven_node, skipTranslate=translate,
                               skipRotate=rotate, **kwargs)


def point_constraint_safe(source_node, driven_node, skip_attrs=None, **kwargs):
    """
    Point constrain one node to another, on the axes that are free.

    :param pm.nt.Transform source_node: The node that will drive.
    :param pm.nt.Transform driven_node: The node that will follow.
    :param skip_attrs: Axes to leave alone.
    :type skip_attrs: list(str) or None
    :return: The constraint, or None when no axis was free to drive.
    :rtype: pm.nt.PointConstraint or None
    """

    if not source_node or not driven_node:
        return None

    translate = constraint_safe_attrs(driven_node, 't', skip_attrs)
    if DRIVE_IT not in translate:
        return None

    return pm.pointConstraint(source_node, driven_node, skip=translate, **kwargs)


def orient_constraint_safe(source_node, driven_node, skip_attrs=None, **kwargs):
    """
    Orient constrain one node to another, on the axes that are free.

    :param pm.nt.Transform source_node: The node that will drive.
    :param pm.nt.Transform driven_node: The node that will follow.
    :param skip_attrs: Axes to leave alone.
    :type skip_attrs: list(str) or None
    :return: The constraint, or None when no axis was free to drive.
    :rtype: pm.nt.OrientConstraint or None
    """

    if not source_node or not driven_node:
        return None

    rotate = constraint_safe_attrs(driven_node, 'r', skip_attrs)
    if DRIVE_IT not in rotate:
        return None

    return pm.orientConstraint(source_node, driven_node, skip=rotate, **kwargs)


def scale_constraint_safe(source_node, driven_node, skip_attrs=None, **kwargs):
    """
    Scale constrain one node to another, on the axes that are free.

    :param pm.nt.Transform source_node: The node that will drive.
    :param pm.nt.Transform driven_node: The node that will follow.
    :param skip_attrs: Axes to leave alone.
    :type skip_attrs: list(str) or None
    :return: The constraint, or None when no axis was free to drive.
    :rtype: pm.nt.ScaleConstraint or None
    """

    if not source_node or not driven_node:
        return None

    scale = constraint_safe_attrs(driven_node, 's', skip_attrs)
    if DRIVE_IT not in scale:
        return None

    return pm.scaleConstraint(source_node, driven_node, skip=scale, **kwargs)


def get_constraint_targets(constraint):
    """
    The transforms driving a constraint, in the order the constraint holds them.

    Joints included. They are transforms, and the pipeline's animation controls are joints,
    so the version this replaces - which insisted the node type be exactly ``'transform'`` -
    answered empty for most of the rigs it was asked about.

    :param pm.PyNode constraint: The constraint node.
    :return: The driving transforms, each once, in target order.
    :rtype: list(pm.PyNode)
    """

    found = []
    for node in constraint.target.listConnections(type='transform') or []:
        # The target array is wired back to the constraint node too, and a constraint is a
        # transform. It is not driving itself.
        if isinstance(node, pm.nt.Constraint):
            continue
        if isinstance(node, pm.nt.Transform) and node not in found:
            found.append(node)
    return found
