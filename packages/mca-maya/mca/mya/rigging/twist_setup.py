"""
Twist joints: spreading a wrist's or an ankle's twist back up the limb.

A forearm has one joint in the skeleton and two bones in the arm. When a hand turns over, the skin
between the elbow and the wrist has to turn with it - gradually, more towards the wrist than the
elbow - and a single joint cannot do that. So the skeleton carries helper joints along the segment,
and this is what drives them.

The twist has to be *extracted* first, because the driving joint's rotation is not only twist: it
also bends. Two duplicated chains do that. One follows the real joints; the other is an IK chain with
its pole vector zeroed, which makes it take the bend and leave the twist behind. A locator orient
constrained to both averages them, and what comes out on the aim axis is the twist on its own. One
``multiplyDivide`` node then hands each helper joint a share of it - the nearest to the wrist getting
most, the nearest to the elbow least.

Three helper joints is the limit, because one ``multiplyDivide`` node has three channels.

What was wrong before:

- **``find_primary_axis`` answered an upper-case axis letter and is now ``dag.get_primary_axis``,
  which answers a lower-case one.** This module already lower-cased the answer at both use sites, so
  the two calls to ``.lower()`` are what went away.
- **A chain of more than three twist joints was refused silently**, and an empty list raised
  ``IndexError`` on ``joint_list[0]`` rather than being refused at all.
- **The driving joint's own child was found by ``parent_chain.index(parent_joint) + 1``**, which is
  an ``IndexError`` when the driving joint is the last in its chain and a ``ValueError`` when the
  markup does not put it in that chain at all. Both are markup mistakes a rigger can make, and both
  now say which joint and which region.
- The joints are put in order with ``sorted(joint_list)``, which sorts PyNodes by name — so the
  order the twist is distributed in is the order the joints happen to be named in. That is how the
  skeletons are built and it is what the callers expect; it is written down now rather than left to
  be discovered.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import pymaths
from mca.mya.rigging import chain_markup
from mca.mya.rigging import joint_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag


logger = log.MCA_LOGGER

#: One multiplyDivide node has three channels, and one node drives the whole chain.
MAX_TWIST_JOINTS = 3

#: The locator is orient constrained to both the mirror joint and the IK joint, which averages their
#: rotation and so halves the twist that comes out. This puts it back.
AVERAGING_COMPENSATION = 2.0


def quick_build_twist_setup(skel_root):
    """
    Build every twist setup a skeleton's markup describes, in one hidden group.

    Nothing in the pipeline calls this. It is kept because it is the only place that shows how
    :attr:`chain_markup.ChainMarkup.twist_joints` is meant to be walked - side, then twist chain -
    and it is what a rigger runs from a shelf on a raw skeleton.

    :param pm.nt.Joint skel_root: The skeleton's root joint.
    :return: The group holding every twist setup that was built.
    :rtype: pm.nt.Transform
    """

    skel_hierarchy = chain_markup.ChainMarkup(skel_root)
    macro_grp = pm.group(n='twist_grp', em=True, w=True)
    macro_grp.visibility.set(False)

    for side_dict in skel_hierarchy.twist_joints.values():
        for data_dict in side_dict.values():
            twist_grp, _ = twist_setup(data_dict['joints'])
            if twist_grp:
                twist_grp.setParent(macro_grp)
    return macro_grp


def twist_setup(joint_list):
    """
    Build the system that drives one segment's twist joints.

    :param list joint_list: The twist joints on one segment, up to :data:`MAX_TWIST_JOINTS`. They
        are put in name order, which is the order the twist is distributed along.
    :return: The group holding the setup, and the nodes inside it. ``(None, {})`` when the joints or
        the markup around them cannot be used.
    :rtype: tuple(pm.nt.Transform, dict)
    """

    if not joint_list:
        logger.warning('No twist joints were given, so no twist setup was built.')
        return None, {}
    if len(joint_list) > MAX_TWIST_JOINTS:
        logger.warning('%s twist joints were given and %s is the most one multiplyDivide node can '
                        'drive, so no twist setup was built for %s.',
                        len(joint_list), MAX_TWIST_JOINTS, joint_list[0])
        return None, {}

    # Name order. The skeletons are built so that this is the order along the segment.
    joint_list = sorted(joint_list)
    first_twist = joint_list[0]
    parent_joint = first_twist.getParent()
    if not parent_joint:
        logger.warning('%s has no parent joint to take its twist from.', first_twist)
        return None, {}

    skel_root = dag.get_absolute_parent(first_twist, node_type=pm.nt.Joint)
    skel_hierarchy = chain_markup.ChainMarkup(skel_root)
    wrapped_parent_joint = chain_markup.JointMarkup(parent_joint)
    wrapped_twist_joint = chain_markup.JointMarkup(first_twist)
    side = wrapped_parent_joint.side
    skel_region = wrapped_parent_joint.region
    twist_chain = wrapped_twist_joint.region

    child_joint = _next_in_chain(skel_hierarchy, parent_joint, skel_region, side)
    if child_joint is None:
        return None, {}

    build_dict = {}
    reverse = _is_reversed(first_twist, parent_joint, child_joint)

    twist_grp = pm.group(n='{0}_{1}_twist_grp'.format(side, twist_chain), em=True, w=True)
    pm.delete(constraint.parent_constraint_safe(parent_joint, twist_grp))
    constraint.parent_constraint_safe(parent_joint.getParent(), twist_grp)

    # The chain that follows the real joints, bend and twist together.
    mirror_chain = joint_utils.duplicate_chain(parent_joint, child_joint, suffix='mirror_chain')
    build_dict['mirror_chain'] = mirror_chain
    mirror_chain[0].setParent(twist_grp)
    constraint.parent_constraint_safe(parent_joint, mirror_chain[0])
    constraint.parent_constraint_safe(child_joint, mirror_chain[1])

    # The chain that takes the bend and leaves the twist: an IK chain whose pole vector is zeroed,
    # so the solver has no plane to favour and the roll does not reach it.
    ik_chain = joint_utils.duplicate_chain(parent_joint, child_joint, suffix='ik')
    build_dict['ik_chain'] = ik_chain
    ik_chain[0].setParent(twist_grp)

    ik_handle_node, _effector = pm.ikHandle(sol='ikRPsolver', sj=ik_chain[0], ee=ik_chain[1])
    ik_handle_node.rename('{0}_{1}_ikhandle'.format(side, twist_chain))
    build_dict['ik_handle'] = ik_handle_node
    ik_handle_node.setParent(mirror_chain[-1])
    for axis in 'XYZ':
        ik_handle_node.attr('poleVector{0}'.format(axis)).set(0)

    # The difference between the two chains, on one node: this is the twist.
    offset_loc = pm.spaceLocator(n='{0}_{1}_offset_loc'.format(side, twist_chain))
    build_dict['offset_loc'] = offset_loc
    offset_loc.setParent(mirror_chain[1] if reverse else mirror_chain[0])
    offset_loc.translate.set([0, 0, 0])
    offset_loc.rotate.set([0, 0, 0])
    orient_targets = [mirror_chain[1], ik_chain[1]] if reverse else [mirror_chain[0], ik_chain[0]]
    constraint.orient_constraint_safe(orient_targets, offset_loc)

    twist_multi = pm.createNode(pm.nt.MultiplyDivide,
                                n='{0}_{1}_multi'.format(side, twist_chain))
    build_dict['multi_node'] = twist_multi

    primary_axis, _ = dag.get_primary_axis(parent_joint)
    twist_attr = 'r{0}'.format(primary_axis)
    # Each joint gets a share, the one nearest the driving joint the smallest. The compensation is
    # for the averaging the orient constraint above does.
    rot_multiplier = 1.0 / len(joint_list) * AVERAGING_COMPENSATION
    if reverse:
        rot_multiplier = rot_multiplier * -1.0

    for index, twist_joint in enumerate(reversed(joint_list)):
        channel = 'XYZ'[index]
        offset_loc.attr(twist_attr) >> twist_multi.attr('input1{0}'.format(channel))
        twist_multi.attr('input2{0}'.format(channel)).set(rot_multiplier * (index + 1))
        twist_multi.attr('output{0}'.format(channel)) >> twist_joint.attr(twist_attr)

    build_dict['unit_conv_nodes'] = [node for node in twist_multi.listConnections()
                                     if isinstance(node, pm.nt.UnitConversion)]
    return twist_grp, build_dict


def _next_in_chain(skel_hierarchy, parent_joint, skel_region, side):
    """
    The joint after the driving joint in its own marked-up chain.

    :param chain_markup.ChainMarkup skel_hierarchy: The skeleton's markup.
    :param pm.nt.Joint parent_joint: The driving joint.
    :param str skel_region: The region it belongs to.
    :param str side: The side it is on.
    :return: The next joint along, or None when the markup cannot answer.
    :rtype: pm.nt.Joint or None
    """

    parent_chain = skel_hierarchy.get_full_chain(skel_region, side)
    if parent_joint not in parent_chain:
        logger.warning('%s is not in the %s %s chain its own markup names, so its twist joints '
                        'cannot be set up.', parent_joint, side, skel_region)
        return None

    index = parent_chain.index(parent_joint)
    if index + 1 >= len(parent_chain):
        logger.warning('%s is the last joint of the %s %s chain, so there is nothing below it to '
                        'take a twist from.', parent_joint, side, skel_region)
        return None
    return parent_chain[index + 1]


def _is_reversed(first_twist, parent_joint, child_joint):
    """
    Whether the twist joints run back up the segment rather than down it.

    A twist chain is sometimes authored from the far end. Which end it starts at decides which of the
    two duplicated chains the extracting locator hangs off, and the sign of the share each joint
    gets - so it is measured rather than assumed, by asking which end of the segment the first twist
    joint is nearer to.

    :param pm.nt.Joint first_twist: The first twist joint in name order.
    :param pm.nt.Joint parent_joint: The driving joint at the near end of the segment.
    :param pm.nt.Joint child_joint: The joint at the far end.
    :return: True when the chain runs back towards the driving joint.
    :rtype: bool
    """

    start_pos = pm.xform(first_twist, q=True, ws=True, t=True)
    parent_pos = pm.xform(parent_joint, q=True, ws=True, t=True)
    child_pos = pm.xform(child_joint, q=True, ws=True, t=True)

    to_parent = pymaths.get_vector_length(pymaths.sub_vectors(start_pos, parent_pos))
    to_child = pymaths.get_vector_length(pymaths.sub_vectors(start_pos, child_pos))
    return to_child <= to_parent
