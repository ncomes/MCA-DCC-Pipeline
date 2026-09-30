"""
A reverse foot: the pivots that let an animator roll a foot through a step.

A foot does not rotate about the ankle when somebody walks. It rolls: the heel lands and the foot
pivots about the heel, then it flattens, then it lifts and pivots about the ball, then about the
toe. Each of those is a different pivot point, and none of them is where the ankle joint is.

So the pivots are built as a chain of their own, out of duplicates of the contact joints a modeller
placed at the heel, ball, toe and the two sides of the foot, nested in the order the roll happens:

    toe pivot > toe > ball pivot > exterior > interior > heel > the reversed ankle chain

Turning any one of them turns everything below it, and the ankle hangs off the bottom - so rotating
the heel joint rolls the whole foot about the heel, which is the motion. The attributes on the IK
foot control are wired straight to those rotations, one each, with the axes given by the caller
because which axis is "lift" depends on how the skeleton was built.

What was wrong before:

- **A foot with no contact joints, or the wrong number of them, built nothing and said nothing.**
  Two early returns with a comment each. An animator gets a leg with no foot controls on it and no
  reason why; the two checks now name what was wrong.
- **Building onto an existing IK foot control raised.** The seven attributes go on with unguarded
  ``addAttr`` calls, and the control can be passed in - which is what the leg components do, so a
  second pass over the same leg was an error rather than a rebuild.
- ``ik_toe_flag.alignTransform.get()`` read the attribute directly rather than asking the flag,
  which is the same mistake that made an FK chain without align transforms raise.
- The chain unpack ``foot_joint, toe_joint, *_ = duplicate_chain(...)`` raised ``ValueError`` on a
  chain of one joint.
- The two controls are named inconsistently - the foot control takes the full side name and the toe
  control takes its first letter (``f_left_foot`` beside ``f_l_foot_toe_ik``). Left alone: rig data
  refers to these names.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import constraint
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The contact joints, in the order the caller passes them.
CONTACT_ORDER = ('toe', 'ball', 'exterior', 'interior', 'heel')

#: Suffixes on the duplicated joints: a pivot to rotate about, a contact point that rolls, the
#: reversed ankle chain, and the joint the toe control drives directly.
PIVOT_SUFFIX = 'piv'
CONTACT_SUFFIX = 'cnt'
REVERSE_SUFFIX = 'rev'
TOE_CONTROL_SUFFIX = 'can'

#: The locked bool that draws a line in the channel box above the foot attributes.
SEPARATOR_ATTR = '_______'

#: A single lean value is split in two by a clamp: negative rolls onto the outside of the foot,
#: positive onto the inside.
LEAN_LIMIT = 180


def reverse_foot_chain(start_joint,
                       end_joint,
                       side,
                       region,
                       scale=1.0,
                       contact_joints=None,
                       ik_foot_flag=None,
                       ball_lift_axis='z',
                       toe_lift_axis='z',
                       toe_pivot_axis='y',
                       heel_lift_axis='z',
                       foot_lean_axis='x',
                       ball_pivot_axis='y'):
    """
    Build the pivot hierarchy and the controls for a reverse foot.

    :param pm.nt.Joint start_joint: The ankle.
    :param pm.nt.Joint end_joint: The toe.
    :param str side: Which side the foot is on.
    :param str region: A name for the region, usually ``foot``.
    :param float scale: How big to draw the controls.
    :param list contact_joints: Five joints, in the order :data:`CONTACT_ORDER`.
    :param ik_foot_flag: An existing IK foot control to build onto. None makes one.
    :param str ball_lift_axis: Which axis lifts the ball.
    :param str toe_lift_axis: Which axis lifts the toe.
    :param str toe_pivot_axis: Which axis pivots about the toe.
    :param str heel_lift_axis: Which axis lifts the heel.
    :param str foot_lean_axis: Which axis leans the foot onto its sides.
    :param str ball_pivot_axis: Which axis pivots about the ball.
    :return: The nodes built, or None when the contact joints are not usable.
    :rtype: dict or None
    """

    if not contact_joints or None in contact_joints:
        logger.warning('%s %s has no contact joints, so no reverse foot was built. It needs five, '
                        'in the order %s.', side, region, ', '.join(CONTACT_ORDER))
        return None

    if len(contact_joints) != len(CONTACT_ORDER):
        logger.warning('%s %s was given %s contact joints, not %s. They go in the order %s.',
                        side, region, len(contact_joints), len(CONTACT_ORDER),
                        ', '.join(CONTACT_ORDER))
        return None

    duplicated = joint_utils.duplicate_chain(start_joint, end_joint, suffix='dup')
    if len(duplicated) < 2:
        logger.warning('%s is not above %s, so there is no ankle-to-toe chain to build a reverse '
                        'foot on.', start_joint, end_joint)
        return None

    side_prefix = side[:1].lower()
    foot_joint, toe_joint = duplicated[0], duplicated[1]
    # The duplicated chain is machinery, not something an animator selects.
    foot_joint.visibility.set(False)

    if not ik_foot_flag:
        ik_foot_flag = frag_flag.Flag.create(start_joint, scale=scale,
                                            label='{0}_{1}'.format(side, region),
                                            add_align_transform=True)
    ik_toe_flag = frag_flag.Flag.create(toe_joint, scale=scale,
                                       label='{0}_{1}_toe_ik'.format(side_prefix, region),
                                       add_align_transform=True)
    ik_foot_flag.node.visibility >> ik_toe_flag.node.visibility
    # The toe control only turns: it sits on the foot and has nowhere to go.
    ik_toe_flag.lock_and_hide_attrs(['tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'v'])

    pivots = _build_pivot_hierarchy(contact_joints, side, region)
    reverse_chain = _build_reverse_chain(foot_joint, toe_joint, pivots['heel'])

    # Every duplicate carries the rotation of the joint it came from; freezing it puts that into
    # jointOrient so the attributes below start from zero.
    pm.makeIdentity(pm.listRelatives(pivots['group'], allDescendents=True) or [],
                    t=True, r=True, s=True, n=False, pn=True, apply=True)

    constraint.parent_constraint_safe(reverse_chain['foot'], foot_joint, mo=True)
    constraint.parent_constraint_safe(reverse_chain['toe_control_joint'], toe_joint, mo=True)
    constraint.orient_constraint_safe(foot_joint, start_joint, mo=True)
    constraint.orient_constraint_safe(toe_joint, end_joint, mo=True)

    alignment_constraint = constraint.parent_constraint_safe(ik_foot_flag, pivots['group'], mo=True)
    constraint.parent_constraint_safe(pivots['heel'], ik_toe_flag.get_align_transform(), mo=True)
    constraint.parent_constraint_safe(ik_toe_flag, reverse_chain['toe_control_joint'])

    clamp_node, unit_conv_nodes = _add_foot_attributes(
        ik_foot_flag, side_prefix, region, pivots, reverse_chain['ball'],
        {'ballLift': ('ball', ball_lift_axis),
         'ballPivot': ('ball_pivot', ball_pivot_axis),
         'toeLift': ('toe', toe_lift_axis),
         'toePivot': ('toe_pivot', toe_pivot_axis),
         'heelLift': ('heel', heel_lift_axis)},
        foot_lean_axis)

    return {'chain': [foot_joint, toe_joint],
            'start_joint': start_joint,
            'end_joint': end_joint,
            'reverse_contact_joints': [pivots['heel'], pivots['interior'], pivots['exterior'],
                                       pivots['ball_pivot'], pivots['toe'], pivots['toe_pivot']],
            'reverse_chain': [reverse_chain['foot'], reverse_chain['ball']],
            'reverse_foot_grp': pivots['group'],
            'ik_toe_flag': ik_toe_flag,
            'alignment_constraint': alignment_constraint,
            'clamp': clamp_node,
            'unit_conv_nodes': unit_conv_nodes}


def _build_pivot_hierarchy(contact_joints, side, region):
    """
    The nest of pivot joints the foot rolls through.

    Each one is a duplicate of a contact joint the modeller placed, parented under the previous, so
    turning one turns every pivot below it and the ankle chain with them.

    :param list contact_joints: Five joints in the order :data:`CONTACT_ORDER`.
    :param str side: Which side the foot is on, for the group's name.
    :param str region: The region name, for the group's name.
    :return: The joints, by the part of the foot they are, plus the ``group`` above them all.
    :rtype: dict
    """

    toe, ball, exterior, interior, heel = contact_joints

    def duplicate(source, suffix):
        return joint_utils.duplicate_joint(
            source, duplicate_name='{0}_{1}'.format(naming.get_basename(source), suffix))

    group = pm.group(empty=True, world=True, name='{0}_{1}_cnt_grp'.format(side, region))

    # The group is put where the toe pivot is, so the whole nest can be driven from the foot
    # control by one constraint on the group.
    toe_pivot_joint = duplicate(toe, PIVOT_SUFFIX)
    pm.delete(constraint.parent_constraint_safe(toe_pivot_joint, group))
    toe_pivot_joint.setParent(group)

    toe_contact_joint = duplicate(toe, CONTACT_SUFFIX)
    toe_contact_joint.setParent(toe_pivot_joint)
    ball_pivot_joint = duplicate(ball, PIVOT_SUFFIX)
    ball_pivot_joint.setParent(toe_contact_joint)
    ext_contact_joint = duplicate(exterior, CONTACT_SUFFIX)
    ext_contact_joint.setParent(ball_pivot_joint)
    int_contact_joint = duplicate(interior, CONTACT_SUFFIX)
    int_contact_joint.setParent(ext_contact_joint)
    heel_contact_joint = duplicate(heel, CONTACT_SUFFIX)
    heel_contact_joint.setParent(int_contact_joint)

    return {'group': group,
            'toe_pivot': toe_pivot_joint,
            'toe': toe_contact_joint,
            'ball_pivot': ball_pivot_joint,
            'exterior': ext_contact_joint,
            'interior': int_contact_joint,
            'heel': heel_contact_joint}


def _build_reverse_chain(foot_joint, toe_joint, heel_joint):
    """
    The ankle chain, rebuilt hanging off the bottom of the pivots.

    Two joints from the duplicated ankle chain plus one more at the toe for the toe control to
    drive, so the toe can be turned without moving anything the roll depends on.

    :param pm.nt.Joint foot_joint: The duplicated ankle.
    :param pm.nt.Joint toe_joint: The duplicated toe.
    :param pm.nt.Joint heel_joint: The last pivot, which the chain hangs from.
    :return: The reversed ankle, the reversed ball, and the toe control's joint.
    :rtype: dict
    """

    def duplicate(source, suffix):
        return joint_utils.duplicate_joint(
            source, duplicate_name='{0}_{1}'.format(naming.get_basename(source), suffix))

    foot_rev_joint = duplicate(foot_joint, REVERSE_SUFFIX)
    ball_rev_joint = duplicate(toe_joint, REVERSE_SUFFIX)
    toe_control_joint = duplicate(toe_joint, TOE_CONTROL_SUFFIX)

    ball_rev_joint.setParent(heel_joint)
    toe_control_joint.setParent(heel_joint)
    foot_rev_joint.setParent(ball_rev_joint)

    return {'foot': foot_rev_joint,
            'ball': ball_rev_joint,
            'toe_control_joint': toe_control_joint}


def _add_foot_attributes(ik_foot_flag, side_prefix, region, pivots, ball_rev_joint, wiring,
                         foot_lean_axis):
    """
    Put the roll attributes on the foot control and wire each to the pivot it turns.

    :param ik_foot_flag: The control the animator uses.
    :param str side_prefix: The side's first letter, for node names.
    :param str region: The region name, for node names.
    :param dict pivots: What :func:`_build_pivot_hierarchy` made.
    :param pm.nt.Joint ball_rev_joint: The reversed ball joint, which ``ballLift`` turns.
    :param dict wiring: ``{attribute name: (pivot key, axis letter)}``.
    :param str foot_lean_axis: Which axis leans the foot onto its sides.
    :return: The clamp that splits the lean, and the unit conversion nodes Maya made.
    :rtype: tuple(pm.nt.Clamp, list)
    """

    flag_node = ik_foot_flag.node if hasattr(ik_foot_flag, 'node') else ik_foot_flag

    # Guarded: the control can be handed in, and these attributes may already be on it. The old
    # version added them unguarded, so a second pass over the same leg raised.
    if not flag_node.hasAttr(SEPARATOR_ATTR):
        flag_node.addAttr(SEPARATOR_ATTR, keyable=True, at='bool')
        flag_node.setAttr(SEPARATOR_ATTR, edit=True, channelBox=True, lock=True)

    targets = dict(pivots)
    targets['ball'] = ball_rev_joint
    for attr_name, (pivot_key, axis) in wiring.items():
        if not flag_node.hasAttr(attr_name):
            flag_node.addAttr(attr_name, keyable=True, at='double')
        flag_node.attr(attr_name) >> targets[pivot_key].attr('r{0}'.format(axis))

    if not flag_node.hasAttr('footLean'):
        flag_node.addAttr('footLean', keyable=True, at='double')

    # One value, two joints: the clamp's red channel keeps the negative half and its green channel
    # the positive half, so leaning one way rolls onto the outside of the foot and the other way
    # onto the inside.
    clamp_node = pm.createNode(pm.nt.Clamp,
                               n='{0}_{1}_roll_clamp'.format(side_prefix, region))
    clamp_node.minR.set(-LEAN_LIMIT)
    clamp_node.maxG.set(LEAN_LIMIT)
    flag_node.footLean >> clamp_node.inputR
    flag_node.footLean >> clamp_node.inputG
    clamp_node.outputR >> pivots['exterior'].attr('r{0}'.format(foot_lean_axis))
    clamp_node.outputG >> pivots['interior'].attr('r{0}'.format(foot_lean_axis))

    unit_conv_nodes = [node for node in clamp_node.listConnections()
                       if isinstance(node, pm.nt.UnitConversion)]
    return clamp_node, unit_conv_nodes
