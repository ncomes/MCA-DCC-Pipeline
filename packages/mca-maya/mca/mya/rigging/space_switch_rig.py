"""
Space switches: letting an animator choose what a control follows.

An empty group is inserted above the control and point/orient constrained to every target at
once, with all the weights at zero except the one the ``follow`` enum is set to. A condition node
per target does the choosing: it compares the enum against its own index and outputs 1 or 0, and
that output is the constraint weight. So switching space is one keyable attribute rather than a
constraint weight per target, and the control's own channels stay free.

The control keeps its own transform: the group takes the offset, and the constraints are made
with ``maintainOffset`` after the group is zeroed, so the pose does not change when the switch is
built.

What was wrong before:

- **Building the switch snapped the control to its parent's origin.** The offset group is made
  at the control's world position, parented under the control's old parent - so its own local
  values become the control's - and the control is then parented under it, which zeroes the
  control. The two lines after that set the group's translate and rotate to zero, which throws
  that offset away and takes the control with it. Checked in a real Maya: a control at
  ``(1, 2, 3)`` is at the origin once a space switch is built on it. It has gone unnoticed
  because a flag normally sits at zero under an align group, where the two lines do nothing -
  but anything switched in place, such as a prop control or a hand-built locator, moved.
- **Building a second space switch on the same control raised.** Both ``addAttr`` calls - the
  channel box separator and the enum itself - went in unguarded, and Maya refuses an attribute
  that is already there. The separator is shared, so the second switch on a flag hit it.
- **The constraint weight was addressed by a name that is not always the alias.** The weight
  attribute was built as ``'{target}W{index}'``, which is the alias only while the target's name
  is its short name with nothing in front of it - a target in a namespace, or one whose name is
  not unique, has a different alias, and the connection raised. Maya's own
  ``getWeightAliasList`` is asked now.
- **A control with no parent raised.** ``pm.parent(switch_offset_grp, source_object.getParent())``
  with ``None`` for the parent. A control at the top of the scene is unusual but not wrong.
- Node names were built by interpolating PyNodes, so a target inside a namespace produced a name
  with a colon in it, which Maya then silently rewrote.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The locked bool that draws a line in the channel box above the switch.
SEPARATOR_ATTR = '__'

#: The default name of the enum an animator picks a space with.
SWITCH_ATTR = 'follow'


def _add_separator(switch_obj):
    """
    Put a locked bool on a node, which the channel box draws as a dividing line.

    :param pm.nt.Transform switch_obj: The node to put it on.
    """

    if switch_obj.hasAttr(SEPARATOR_ATTR):
        # Already separated - a second space switch on the same control, which used to raise.
        return
    switch_obj.addAttr(SEPARATOR_ATTR, keyable=True, at='bool')
    switch_obj.setAttr(SEPARATOR_ATTR, edit=True, channelBox=True, lock=True)


def space_switch(target_list,
                 source_object,
                 switch_obj=None,
                 translate=True,
                 rotate=True,
                 switch_attr=SWITCH_ATTR,
                 **kwargs):
    """
    Build a space switch on a control.

    :param target_list: The spaces the control can follow, in the order they appear in the enum.
    :param pm.nt.Transform source_object: The control being switched.
    :param pm.nt.Transform switch_obj: The node the enum goes on. None means the control itself.
    :param bool translate: Follow the targets in translation.
    :param bool rotate: Follow the targets in rotation.
    :param str switch_attr: The name of the enum.
    :param dict kwargs: ``t`` and ``r`` are older spellings of ``translate`` and ``rotate``;
        ``default_name`` renames the first entry in the enum, for when the first space is
        "world" or "default" rather than a node an animator would recognise.
    :return: What was made, under ``point_constraints``, ``orient_constraints``, ``conditions``
        and ``switch_offset_grp``. Empty when nothing could be built.
    :rtype: dict
    """

    result = {'point_constraints': [], 'orient_constraints': [], 'conditions': [],
              'switch_offset_grp': None}

    if not isinstance(target_list, (list, tuple)):
        target_list = [target_list]
    target_list = list(target_list)
    if not target_list:
        logger.warning('A space switch needs at least one space to follow.')
        return result

    follow_translate = kwargs.get('t', translate)
    follow_rotate = kwargs.get('r', rotate)
    default_name = kwargs.get('default_name', None)
    switch_obj = switch_obj or source_object

    if switch_obj.hasAttr(switch_attr):
        logger.warning('%s already has a %s attribute, so no space switch was built on it.',
                       switch_obj, switch_attr)
        return result

    _add_separator(switch_obj)

    enum_names = [naming.get_basename(target) for target in target_list]
    if default_name is not None:
        enum_names[0] = default_name
    switch_obj.addAttr(switch_attr, at='enum', en=':'.join(enum_names), keyable=True)

    source_name = naming.get_basename(source_object)
    switch_offset_grp = pm.group(empty=True, name='{0}_space'.format(source_name))
    pm.delete(pm.parentConstraint(source_object, switch_offset_grp, weight=True,
                                  maintainOffset=False))

    source_parent = source_object.getParent()
    if source_parent:
        pm.parent(switch_offset_grp, source_parent)
    # The group now holds the offset the control used to have, and the control's own channels
    # are zero. Zeroing the group here - which is what the version before did - would throw
    # that offset away and move the control to its parent's origin.
    pm.parent(source_object, switch_offset_grp)

    for index, target in enumerate(target_list):
        target_name = naming.get_basename(target)
        # The condition outputs 1 only while the enum is on this target's index, and that
        # output is the constraint's weight - so exactly one space is ever on.
        condition = pm.createNode(pm.nt.Condition,
                                  n='cond_{0}_space_{1}'.format(target_name, source_name))
        condition.secondTerm.set(index)
        condition.colorIfTrueR.set(1.0)
        condition.colorIfFalseR.set(0.0)
        switch_obj.attr(switch_attr) >> condition.firstTerm
        result['conditions'].append(condition)

        if follow_translate:
            constraint = pm.pointConstraint(
                target, switch_offset_grp, weight=True, maintainOffset=True,
                n='point_const_{0}_space_{1}'.format(target_name, source_name))
            result['point_constraints'].append(constraint)
            _connect_weight(condition, constraint, target)

        if follow_rotate:
            constraint = pm.orientConstraint(
                target, switch_offset_grp, weight=True, maintainOffset=True,
                n='ori_const_{0}_space_{1}'.format(target_name, source_name))
            result['orient_constraints'].append(constraint)
            _connect_weight(condition, constraint, target)

    result['switch_offset_grp'] = switch_offset_grp
    return result


def _connect_weight(condition, constraint, target):
    """
    Wire a condition's output to the weight this target holds on a constraint.

    The alias is asked for rather than spelled out. Building it as ``'{target}W{index}'`` is the
    alias only when the target's name is a plain short name, which a target in a namespace is
    not.

    :param pm.nt.Condition condition: The condition that decides the weight.
    :param constraint: The constraint to drive.
    :param target: The target whose weight this is.
    :return: True when the weight was connected.
    :rtype: bool
    """

    aliases = constraint.getWeightAliasList()
    if not aliases:
        logger.warning('%s has no weights on it, so %s was not connected.', constraint, condition)
        return False

    # The target just added is the last weight on the constraint.
    condition.outColorR >> aliases[-1]
    return True
