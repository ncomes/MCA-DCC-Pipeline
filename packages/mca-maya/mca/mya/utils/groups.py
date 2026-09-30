"""
The empty transform that sits above a control so the control can start at zero.

A rig control has to be at the right place in the world and read ``0, 0, 0`` in the channel
box, and those two things are only compatible if something above it is holding the offset.
That something is an "align group": an empty transform at the control's position, with the
control parented under it.

The pair is wired together with message attributes, so either one can find the other later -
an exporter asking "what is this group for", a rebuild asking "where does this control's
offset live".

What was wrong before:

- **``create_aligned_parent_group``'s docstring promised something it never did.** "If an
  align transform already exists for the object then return it" - there was no such check
  anywhere in the function; it made a new group every time, and calling it twice on the same
  control left two groups stacked up with the second one holding nothing. It does the check
  now, which is what the callers were told they were getting.
- **``create_aligned_child_group`` had no docstring and no callers.** Gone.
- **``transform_scale`` divided by the numbers it was handed** without looking at them, so a
  scale of zero on any axis was ``ZeroDivisionError``.
- The module docstring said "Parameter data for working with the facial rigs", copied from
  ``naming.py``, and the file was indented with tabs in a package that is otherwise spaces.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.utils import attr_utils
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The attribute the control carries, pointing up at its align group.
ALIGN_TRANSFORM_ATTR = 'alignTransform'

#: The attribute the align group carries, pointing back down at its control.
ALIGN_OBJECT_ATTR = 'alignObject'

#: The suffix an align group's name gets, so it can be recognised in an outliner.
ALIGN_TRANSFORM_SUFFIX = 'align_transform'


def get_aligned_parent_group(obj, attr_name=ALIGN_TRANSFORM_ATTR):
    """
    The align group a control already has, if it has one.

    :param obj: The control.
    :type obj: pm.nt.Transform or str
    :param str attr_name: The attribute on the control that points at its group.
    :return: The group, or None.
    :rtype: pm.nt.Transform or None
    """

    obj = pm.PyNode(obj)
    if not obj.hasAttr(attr_name):
        return None
    connections = obj.attr(attr_name).listConnections(source=True, destination=False)
    return connections[0] if connections else None


def create_aligned_parent_group(obj, suffix='', attr_name=ALIGN_TRANSFORM_ATTR,
                                obj_attr=ALIGN_OBJECT_ATTR, orient_obj=None):
    """
    Put an empty transform at a control's position and parent the control under it.

    The control's own translate and rotate come out at zero, because the offset is now the
    group's. A joint's ``jointOrient`` is zeroed too, for the same reason: it is a second place
    an offset can hide.

    :param obj: The control to zero out.
    :type obj: pm.nt.Transform or str
    :param str suffix: Added to the group's name, after an underscore.
    :param str attr_name: The attribute to put on the control, pointing at the group.
    :param str obj_attr: The attribute to put on the group, pointing at the control.
    :param orient_obj: Take the group's orientation from this node instead of from the control.
    :type orient_obj: pm.nt.Transform or None
    :return: The group. The one that is already there, when the control has one - which is
        what the version this replaces said it did and did not do.
    :rtype: pm.nt.Transform
    """

    obj = pm.PyNode(obj)

    existing = get_aligned_parent_group(obj, attr_name=attr_name)
    if existing is not None:
        return existing

    group_name = naming.get_basename(obj) + ('_{}'.format(suffix) if suffix else '')
    transform = pm.group(empty=True, name=group_name)

    # The rotate order has to match, or matching the rotation will not match the values.
    if obj.hasAttr('rotateOrder'):
        transform.rotateOrder.set(obj.rotateOrder.get())

    # A constraint that is deleted immediately is the shortest way to say "put this exactly
    # where that is", including the parent's transform in the sum.
    pm.delete(pm.parentConstraint(obj, transform, weight=1, maintainOffset=False))
    if orient_obj:
        pm.delete(pm.orientConstraint(orient_obj, transform, weight=1, maintainOffset=False))

    object_parent = obj.getParent()
    if object_parent:
        transform.setParent(object_parent)
    obj.setParent(transform)

    if isinstance(obj, pm.nodetypes.Joint):
        # A joint's orientation lives in jointOrient as well as in rotate, and a control that
        # reads zero while jointOrient holds an angle is not zeroed at all.
        obj.jointOrient.set([0, 0, 0])

    if not obj.hasAttr(attr_name):
        obj.addAttr(attr_name, at='message')
    if not transform.hasAttr(obj_attr):
        transform.addAttr(obj_attr, dt='string')
    transform.attr(obj_attr) >> obj.attr(attr_name)

    return transform


def transform_scale(align_grp, flag_node, translate_scale=(1, 1, 1)):
    """
    Scale how far a control's movement carries, without scaling the control.

    The group above the control is scaled down and the control scaled up by the same amount, so
    the control looks the same size but a unit of movement in the channel box travels further -
    which is how a face control with a one-centimetre range is given numbers an animator can
    read. The control's scale is then locked, because it is holding a ratio, not a size.

    :param pm.nt.Transform align_grp: The group above the control.
    :param flag_node: The control.
    :param translate_scale: How much further movement should carry, per axis.
    :type translate_scale: tuple(float, float, float)
    :raises ValueError: When any axis is zero. The version this replaces divided by these
        numbers without looking, so a zero was a ZeroDivisionError from inside the rig build.
    """

    if len(translate_scale) != 3:
        raise ValueError('transform_scale wants three numbers; it was given {!r}.'
                         .format(translate_scale))
    if any(not one for one in translate_scale):
        raise ValueError('transform_scale cannot scale by zero: {!r}.'.format(translate_scale))

    attr_utils.unlock_and_show_attrs(flag_node.scale.children())

    for axis, amount in zip('XYZ', translate_scale):
        align_grp.attr('scale{}'.format(axis)).set(1.0 / amount)
        flag_node.attr('scale{}'.format(axis)).set(amount)

    for axis in 'XYZ':
        attribute = flag_node.attr('scale{}'.format(axis))
        attribute.lock()
        attribute.set(keyable=False, channelBox=False)


def create_align_transform(obj, orient_obj=None):
    """
    The align group a rig control gets, under the name the rig uses for it.

    :func:`create_aligned_parent_group` with the suffix and the attribute names the rigging code
    has always used. It lived in ``rig_utils`` before, which meant that importing a flag pulled in
    1,752 lines of rig building - and everything in ``rig_utils``, in turn, needs flags. It is
    three arguments and a name; it belongs here with the group it makes.

    :param obj: The control to zero out.
    :param orient_obj: Take the group's orientation from this node instead of from the control.
    :return: The group. The one that is already there, when the control has one.
    :rtype: pm.nt.Transform
    """

    return create_aligned_parent_group(obj,
                                       suffix=ALIGN_TRANSFORM_SUFFIX,
                                       attr_name=ALIGN_TRANSFORM_ATTR,
                                       obj_attr=ALIGN_OBJECT_ATTR,
                                       orient_obj=orient_obj)
