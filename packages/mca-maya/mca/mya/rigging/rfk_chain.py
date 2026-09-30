"""
A reverse FK chain: two controls at the ends of a chain, and the middle works itself out.

A spine has half a dozen joints in it and an animator does not want half a dozen controls. What they
want is to place the hips and the chest and have the joints between them distribute the difference -
which is what this builds. There is a control at each end, and each middle joint gets an aim system
that points it somewhere between the two.

The aiming is done with locators rather than with a blended orientation constraint, because
orientation constraints between two very different rotations go the long way round. So each end
control drives a pair of locators pushed out along its own X and Y; a point constraint averages each
pair by weight; and the middle joint's aimer aims at the averaged X locator with the averaged Y
locator as its up vector. Two positions cannot go the long way round, so the result is smooth.

The weight is a smoothstep of how far along the chain the joint sits, so the ends of the chain
follow their nearest control closely and the middle splits the difference. It is stored per joint,
at build time, and hidden.

The four builders below - ``flag_label``, ``build_aim_pair``, ``build_mid_system`` and
``build_sub_flag`` - are public because ``rfk_stretch_chain`` is the same chain with a stretch layer
on top and builds its controls out of them. It differs in one thing only, which is the node the
middle joints read the end of the chain's orientation from, so ``build_mid_system`` takes that as an
argument.

What was wrong before:

- **Both docstrings said the twist bias attributes are keyable and exposed to the animator.** They
  are added keyable and then immediately set ``keyable=False, cb=False`` on the next line, which
  hides them - and nothing anywhere reads or drives them afterwards. They are build-time values
  worked out from each joint's position along the chain. They go on non-keyable now, and what they
  are is written down.
- **The chain was walked without a node type**, so anything that is not a joint sitting between the
  two ends would be counted as a middle joint and given a control. Every other caller of
  ``get_between_nodes`` in the package asks for joints.
- **A chain of one or two joints built two controls and no middle at all**, in the one-joint case
  both on the same joint, and said nothing.
- **Renaming the sub controls threw away their wrappers.**
  ``sub_end_flag = pm.rename(sub_end_flag, str(sub_end_flag) + '_sub')`` rebinds the name to the
  PyNode ``pm.rename`` answers, so what came back in ``sub_flags`` was a bare node where every other
  flag in the result is a ``Flag``. The node is renamed through the wrapper now, and the wrapper is
  what comes back.
- The label - strip the suffix, then strip the namespace - was written out six times; it is one
  function. A caller passing ``suffix=''`` would have had every underscore stripped out of every
  label, the same fault ``reverse_chain`` had. The two end aim systems were the same twelve lines
  twice over. The five units the aim locators are pushed out by, and the 0.75 the sub controls are
  drawn at, were in the arithmetic.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import dag
from mca.mya.utils import groups
from mca.mya.utils import locators
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: How far out the aim and up locators are pushed from the control that drives them. Far enough that
#: the direction between two of them is stable; the distance itself does not matter.
AIM_OFFSET = 5

#: How much smaller a sub control is drawn than the control it sits under.
SUB_FLAG_SCALE = 0.75

#: The fewest joints worth building on: two ends and something in between for them to distribute to.
MINIMUM_JOINTS = 3


def rfk_chain(start_joint, end_joint, side, region, scale=1.0, create_sub_flags=True,
              suffix='rfk_chain'):
    """
    Build a reverse FK chain over a run of joints.

    :param pm.nt.Joint start_joint: The first joint.
    :param pm.nt.Joint end_joint: The last one.
    :param str side: Which side the chain is on, for node names.
    :param str region: The region's name, for node names.
    :param float scale: How big to draw the controls.
    :param bool create_sub_flags: Build a smaller detail control under each end control.
    :param str suffix: A suffix to take off the control labels, usually the one the source chain was
        duplicated with.
    :return: The nodes built, under ``start_joint``, ``end_joint``, ``mid_flags``, ``flags_groups``,
        ``mid_groups``, ``mid_offset_groups``, ``start_twist_flag``, ``end_twist_flag``,
        ``sub_flags`` and ``reverse_nodes``. Empty when the chain is too short.
    :rtype: dict
    """

    start_joint = pm.PyNode(start_joint)
    end_joint = pm.PyNode(end_joint)

    # With joints asked for: anything else between the two ends is not a joint this rigs.
    rfk_chain_joints = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
    if len(rfk_chain_joints) < MINIMUM_JOINTS:
        logger.warning('A reverse FK chain needs at least %s joints - two ends and something '
                       'between them to distribute to. %s and %s give %s.',
                       MINIMUM_JOINTS, start_joint, end_joint, len(rfk_chain_joints))
        return {}

    flags_groups = []
    start_rotate_flag = frag_flag.Flag.create_ratio(
        object_to_match=rfk_chain_joints[0], scale=scale,
        label=flag_label(rfk_chain_joints[0], suffix))
    flags_groups.append(start_rotate_flag.get_align_transform())

    end_rotate_flag = frag_flag.Flag.create_ratio(
        object_to_match=rfk_chain_joints[-1], scale=scale,
        label=flag_label(rfk_chain_joints[-1], suffix))
    flags_groups.append(end_rotate_flag.get_align_transform())

    mid_groups = []
    mid_offset_groups = []
    mid_flags = []
    weight_reverse_nodes = []
    middle_joints = rfk_chain_joints[1:-1]
    for index, mid_joint in enumerate(middle_joints):
        built = build_mid_system(mid_joint, index, len(middle_joints), start_rotate_flag,
                                 end_rotate_flag, side, region, scale, suffix)
        mid_groups.append(built['mid_group'])
        mid_offset_groups.append(built['offset_group'])
        mid_flags.append(built['mid_flag'])
        weight_reverse_nodes.append(built['weight_reverse'])
        flags_groups.append(built['mid_flag'].get_align_transform())

    sub_start_flag = None
    sub_end_flag = None
    sub_start_align = None
    sub_end_align = None
    if create_sub_flags:
        sub_end_flag, sub_end_align = build_sub_flag(rfk_chain_joints[-1], scale, suffix)
        sub_start_flag, sub_start_align = build_sub_flag(rfk_chain_joints[0], scale, suffix)
        flags_groups.append(sub_end_align)
        flags_groups.append(sub_start_align)

    # The end controls follow the joints' positions and drive their rotations - the chain's place
    # comes from whatever is above it, and what this component supplies is the twist.
    pm.pointConstraint(rfk_chain_joints[-1], end_rotate_flag, mo=False, w=1)
    pm.pointConstraint(rfk_chain_joints[0], start_rotate_flag, mo=False, w=1)

    if create_sub_flags:
        # With sub controls in the way, the joint takes its rotation from the sub and the sub takes
        # its own from the control above it, so an animator can offset an end without losing it.
        pm.pointConstraint(rfk_chain_joints[-1], sub_end_align, mo=False, w=1)
        pm.pointConstraint(rfk_chain_joints[0], sub_start_align, mo=False, w=1)
        pm.orientConstraint(sub_end_flag, rfk_chain_joints[-1], mo=False, w=1)
        pm.orientConstraint(sub_start_flag, rfk_chain_joints[0], mo=False, w=1)
        pm.orientConstraint(end_rotate_flag, sub_end_align, mo=False, w=1)
        pm.orientConstraint(start_rotate_flag, sub_start_align, mo=False, w=1)
    else:
        pm.orientConstraint(end_rotate_flag, rfk_chain_joints[-1], mo=False, w=1)
        pm.orientConstraint(start_rotate_flag, rfk_chain_joints[0], mo=False, w=1)

    return {'start_joint': start_joint,
            'end_joint': end_joint,
            'mid_flags': mid_flags,
            'flags_groups': flags_groups,
            'mid_groups': mid_groups,
            'mid_offset_groups': mid_offset_groups,
            'start_twist_flag': start_rotate_flag,
            'end_twist_flag': end_rotate_flag,
            'sub_flags': [sub_start_flag, sub_end_flag] if create_sub_flags else [],
            'reverse_nodes': weight_reverse_nodes}


def flag_label(joint_node, suffix):
    """
    A control's label, taken from the joint it is built on.

    :param pm.nt.Joint joint_node: The joint.
    :param str suffix: A suffix to take off, usually the one a duplicated chain carries. An empty
        suffix takes nothing off - stripping ``'_' + ''`` takes every underscore out of the name.
    :return: The label.
    :rtype: str
    """

    label = naming.get_basename(joint_node)
    if suffix:
        label = label.replace('_' + suffix, '')
    return label


def build_aim_pair(flag_node, mid_joint, name_prefix, index, orient_source=None):
    """
    The locators one end control contributes to a middle joint's aim.

    Three locators: one that takes the control's orientation, and two pushed out along its X and Y
    for the aim and the up vector. They are positioned at the middle joint, so the direction from
    the joint to each of them is what the control's rotation means *there*.

    :param flag_node: The end control. The locators are built where it sits.
    :param pm.nt.Joint mid_joint: The middle joint this pair is for.
    :param str name_prefix: ``start`` or ``end``, for the node names.
    :param int index: Which middle joint, for the node names.
    :param orient_source: Something other than ``flag_node`` to read the orientation from, for a
        caller that cannot read the control's world orientation without closing an evaluation
        cycle - see ``rfk_stretch_chain``. It must carry the same world orientation as the control.
        Defaults to the control itself.
    :return: The orientation locator, its align group, and the X and Y locators.
    :rtype: dict
    """

    orient_loc = locators.create_locator_at_object(
        flag_node, label='{0}_flag_aims_orient_{1}'.format(name_prefix, index))
    orient_align = groups.create_align_transform(orient_loc)

    x_loc = locators.create_locator_at_object(
        flag_node, label='{0}_flag_aim_x_{1}'.format(name_prefix, index))
    y_loc = locators.create_locator_at_object(
        flag_node, label='{0}_flag_aim_y_{1}'.format(name_prefix, index))
    x_loc.setParent(orient_loc)
    y_loc.setParent(orient_loc)

    # At the joint, not at the control: the whole point is what the control's rotation does here.
    pm.delete(pm.pointConstraint(mid_joint, orient_align, w=True, mo=False))
    pm.move(x_loc, [AIM_OFFSET, 0, 0], r=1, os=1)
    pm.move(y_loc, [0, AIM_OFFSET, 0], r=1, os=1)
    pm.orientConstraint(orient_source or flag_node, orient_loc, w=1, mo=False)

    return {'orient_loc': orient_loc, 'align': orient_align, 'x_loc': x_loc, 'y_loc': y_loc}


def build_mid_system(mid_joint, index, mid_count, start_rotate_flag, end_rotate_flag, side, region,
                     scale, suffix, end_orient_node=None):
    """
    Everything one middle joint needs to take its rotation from the two end controls.

    :param pm.nt.Joint mid_joint: The joint.
    :param int index: Which middle joint this is, counting from the start.
    :param int mid_count: How many there are.
    :param start_rotate_flag: The control at the start of the chain.
    :param end_rotate_flag: The control at the end.
    :param str side: Which side the chain is on, for node names.
    :param str region: The region's name, for node names.
    :param float scale: How big to draw the control.
    :param str suffix: A suffix to take off the control's label.
    :param end_orient_node: Something other than ``end_rotate_flag`` to read the end of the chain's
        orientation from; see ``build_aim_pair``. Defaults to the end control.
    :return: The nodes built.
    :rtype: dict
    """

    mid_group = pm.group(empty=True, n='rfk_mid_group_{0}'.format(index))
    pm.delete(pm.parentConstraint(mid_joint, mid_group, w=True, mo=False))

    start_pair = build_aim_pair(start_rotate_flag, mid_joint, 'start', index)
    end_pair = build_aim_pair(end_rotate_flag, mid_joint, 'end', index,
                              orient_source=end_orient_node)

    # A smoothstep of how far along the chain this joint sits: the ends follow their nearest control
    # closely and the middle splits the difference, rather than the weight running linearly.
    end_weight = pm.util.smoothstep(0, 1, (index + 1.0) / (mid_count + 1.0))

    # Worked out at build time from the joint's position and hidden. It is not keyable and nothing
    # reads it afterwards, which is what both docstrings used to say it was.
    bias_name = 'twist_bias_{0}'.format(index + 1)
    end_rotate_flag.node.addAttr(bias_name, dv=end_weight, min=0, max=1, keyable=False)
    bias_attr = end_rotate_flag.node.attr(bias_name)

    weight_reverse = pm.createNode('reverse', n='bias_{0}_reverse'.format(index + 1))
    bias_attr >> weight_reverse.inputX

    # Two positions averaged by weight, rather than two orientations blended - two rotations far
    # apart blend the long way round, and two points cannot.
    x_aim_loc = pm.spaceLocator(n='aim_x_locator_{0}'.format(index))
    x_const = pm.pointConstraint([start_pair['x_loc'], end_pair['x_loc']], x_aim_loc,
                                 w=1.0, mo=False)
    y_aim_loc = pm.spaceLocator(n='aim_y_locator_{0}'.format(index))
    y_const = pm.pointConstraint([start_pair['y_loc'], end_pair['y_loc']], y_aim_loc,
                                 w=1.0, mo=False)

    for point_constraint in (x_const, y_const):
        aliases = point_constraint.getWeightAliasList()
        weight_reverse.outputX >> aliases[0]
        bias_attr >> aliases[1]

    mid_control = pm.spaceLocator(n='mid_{0}_aimer'.format(index))
    mid_control.rotateOrder.set(mid_joint.rotateOrder.get())
    mid_control_align = groups.create_align_transform(mid_control)
    pm.delete(pm.pointConstraint(mid_joint, mid_control_align, w=True, mo=False))

    start_pair['align'].setParent(mid_control_align)
    end_pair['align'].setParent(mid_control_align)
    pm.aimConstraint(x_aim_loc, mid_control, w=1, offset=[0, 0, 0], mo=False,
                     aimVector=[1, 0, 0], upVector=[0, 1, 0],
                     worldUpType='object', worldUpObject=y_aim_loc)

    # The offset group carries the difference between where the aimer ends up pointing and where the
    # joint actually sits, so the control on the joint reads zero at rest.
    offset_group = pm.group(empty=True,
                            n='mid_{0}_offset_group_{1}_{2}'.format(index, side, region))
    offset_group.rotateOrder.set(mid_joint.rotateOrder.get())
    pm.delete(pm.parentConstraint(mid_control, offset_group, w=True, mo=False))
    offset_group.setParent(mid_control)
    pm.delete(pm.parentConstraint(mid_joint, offset_group, w=True, mo=False))

    mid_flag = frag_flag.Flag.create(mid_joint, scale=scale,
                                     label=flag_label(mid_joint, suffix), is_sub=True)
    mid_flag_align = mid_flag.get_align_transform()
    pm.orientConstraint(offset_group, mid_flag_align, w=1, mo=False)
    # Position from the joint, rotation to the joint: the chain's place comes from above, and what
    # this supplies is the twist.
    pm.pointConstraint(mid_joint, mid_flag, w=1)
    pm.pointConstraint(mid_joint, mid_control_align, mo=False, w=1)
    pm.orientConstraint(mid_flag, mid_joint, mo=False, w=1)

    mid_control_align.setParent(mid_group)
    y_aim_loc.setParent(mid_group)
    x_aim_loc.setParent(mid_group)

    return {'mid_group': mid_group,
            'offset_group': offset_group,
            'mid_flag': mid_flag,
            'weight_reverse': weight_reverse,
            'mid_control': mid_control}


def build_sub_flag(joint_node, scale, suffix):
    """
    A smaller detail control under one of the chain's end controls.

    Built without an align group and given one afterwards, so the group takes its name from the
    control's final name rather than the one it was born with.

    :param pm.nt.Joint joint_node: The joint at that end of the chain.
    :param float scale: The end control's size; the sub is drawn smaller.
    :param str suffix: A suffix to take off the label.
    :return: The control and its align group.
    :rtype: tuple
    """

    sub_flag = frag_flag.Flag.create_ratio(object_to_match=joint_node,
                                          label=flag_label(joint_node, suffix),
                                          scale=scale * SUB_FLAG_SCALE,
                                          add_align_transform=False,
                                          is_detail=True,
                                          is_sub=True)
    # Through the wrapper. Rebinding the name to what pm.rename answers - which is what this did -
    # turned the Flag back into a bare node for the caller.
    sub_flag.node.rename(str(sub_flag.node) + '_sub')
    return sub_flag, groups.create_align_transform(sub_flag.node)
