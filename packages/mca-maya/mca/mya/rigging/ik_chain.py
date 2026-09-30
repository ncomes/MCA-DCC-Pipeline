"""
A rotate-plane IK chain: an IK handle in an align group, a control to place the end of it, a smaller
offset control under that, and a pole vector control with a line drawn to the joint it steers.

The rotate-plane solver needs two things from a rig: where the end of the chain is, and which way
the middle of it bends. The end comes from the IK control, through the align group the handle sits
in - the handle itself is never constrained, so a rig can move the whole thing without fighting the
solver. The bend comes from the pole vector control, and because a control out in space with nothing
around it tells an animator nothing, a template line is drawn from the middle joint to it.

The offset control is a detail control parented under the IK control, orienting the end joint. It is
what lets an animator turn a foot or a hand without moving the IK control it hangs from.

What was wrong before:

- **The pole vector control was wired to a locator that is deleted four lines later.** The control
  has to be built somewhere, and the pole vector's position is worked out before the IK handle
  exists, so a temporary locator is put there for the control to be built on. But ``Flag.create``
  wires a control to whatever it was built on, both ways - so every IK chain ever built came out
  with a pole vector control whose ``driven_transform`` message attribute points at nothing. It asks
  not to be wired now, which is the same fix ``rig_aim_joint`` needed.
- **The error for a chain of the wrong length named neither the joints nor the count**, and said
  "end_joints". A rigger who hits it is told what the rule is and nothing about what they gave it.
- **``end_joint`` was quietly rebound.** On a four-joint chain the IK runs from the first joint to
  the *third*, and the fourth is outside it - which is right, but it was done by assigning over the
  argument, so the ``end_joint`` in the result was not the joint the caller asked for and nothing
  said so. The IK's own end joint has its own name and its own key now, and the caller's joint comes
  back untouched.
- **An unrecognised rotate order raised a bare ``KeyError``** on a dictionary rebuilt inside the
  function on every call. It is a module constant, and the error says which orders there are.
- The align group for the IK handle was built by hand - group, snap, reparent - under exactly the
  name ``groups.create_align_transform`` gives it, so the handle now carries the same markup every
  other aligned node in a rig does. Finding the guide line's two clusters was ten lines of walking
  shape connections here; that is ``reference_line.get_line_clusters``. The line's
  ``inheritsTransform`` was switched off a second time after the call, which
  ``create_line_between`` had already done. The result dictionary was built a line at a time, and
  the 0.75 the offset control is drawn at was in the arithmetic.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging import ik_utils
from mca.mya.rigging import reference_line
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import dag
from mca.mya.utils import groups
from mca.mya.utils import locators


logger = log.MCA_LOGGER

#: How much smaller the offset control is drawn than the IK control it sits under.
OFFSET_FLAG_SCALE = 0.75

#: Maya's ``rotateOrder`` enum, by the name a caller uses for it.
ROTATE_ORDERS = {'xyz': 0, 'yzx': 1, 'zxy': 2, 'xzy': 3, 'yxz': 4, 'zyx': 5}

#: A locked, unkeyable bool that draws a line in the channel box above the twist attribute.
SEPARATOR_ATTR = '___'

#: The lengths of chain a rotate-plane IK can be built on here. Three is the solver's own minimum -
#: it needs a bend to read a plane from. Four puts the last joint outside the IK, which is how a leg
#: with a ball joint or an arm with a wrist end is rigged.
VALID_CHAIN_LENGTHS = (3, 4)


def ik_joint_chain(start_joint,
                   end_joint,
                   side,
                   region,
                   scale=1.0,
                   ik_flag_orient=None,
                   ik_flag_pv_orient=None,
                   ik_flag_rotate_order=None):
    """
    Build a rotate-plane IK chain over three or four joints.

    :param pm.nt.Joint start_joint: The first joint.
    :param pm.nt.Joint end_joint: The last one. On a four-joint chain the IK stops at the third and
        this one is left outside it; ``ik_end_joint`` in the result says which joint the IK ends on.
    :param str side: Which side the chain is on, for node names.
    :param str region: The region's name, for node names.
    :param float scale: How big to draw the controls. The offset control is drawn at 75% of it.
    :param ik_flag_orient: A rotation for the IK control's align group, so its zero pose is turned.
    :param ik_flag_pv_orient: The same for the pole vector control.
    :param str ik_flag_rotate_order: A rotate order for the IK control, as one of the six axis
        orders - ``'xyz'``, ``'yzx'``, ``'zxy'``, ``'xzy'``, ``'yxz'``, ``'zyx'``.
    :return: The nodes built.
    :rtype: dict
    :raises RuntimeError: When the run of joints is not three or four long.
    :raises ValueError: When ``ik_flag_rotate_order`` is not one of the six orders.
    """

    start_joint = pm.PyNode(start_joint)
    end_joint = pm.PyNode(end_joint)

    if ik_flag_rotate_order and ik_flag_rotate_order not in ROTATE_ORDERS:
        raise ValueError(
            '{0} is not a rotate order. It is one of {1}.'.format(
                ik_flag_rotate_order, ', '.join(sorted(ROTATE_ORDERS))))

    chain = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
    if len(chain) not in VALID_CHAIN_LENGTHS:
        raise RuntimeError(
            'A rotate-plane IK chain is built on {0} joints. {1} to {2} is {3} joints long: '
            '{4}.'.format(' or '.join(str(length) for length in VALID_CHAIN_LENGTHS),
                          start_joint, end_joint, len(chain),
                          ', '.join(str(joint) for joint in chain)))

    middle_joint = chain[1]
    # A four-joint chain solves over the first three; the fourth hangs off the end of the IK, which
    # is how a foot's ball or a hand's fingers are left free of it.
    ik_end_joint = chain[2]

    # Read before the IK handle exists: building one moves the joints onto the solver's plane, and
    # the pole vector's place has to be worked out from the pose the rigger built.
    pole_locator = ik_utils.create_pole_vector_locator(
        [start_joint, middle_joint, ik_end_joint],
        name='{0}_{1}_pv_loc'.format(side, region))
    if pole_locator is None:
        raise RuntimeError(
            '{0} to {1} has no pole vector position to build on.'.format(start_joint, ik_end_joint))

    ik_handle_node, ik_effector = pm.ikHandle(solver='ikRPsolver', startJoint=start_joint,
                                              endEffector=ik_end_joint)
    ik_handle_node.rename('{0}_{1}_ikhandle'.format(side, region))
    ik_handle_node.visibility.set(0)
    ik_solver = ik_handle_node.ikSolver.get()

    ik_flag = frag_flag.Flag.create(ik_end_joint,
                                    scale=scale,
                                    label='{0}_{1}'.format(side, region),
                                    add_align_transform=True,
                                    orientation=ik_flag_orient)

    ik_flag_offset = frag_flag.Flag.create(ik_end_joint,
                                           scale=scale * OFFSET_FLAG_SCALE,
                                           label='{0}_{1}_offset'.format(side, region),
                                           add_align_transform=True,
                                           orientation=ik_flag_orient,
                                           is_detail=True)

    # meta_connect off: the locator this is built on is deleted below, and wiring a control to
    # a node that is about to go is what left every pole vector control pointing at nothing.
    pv_flag = frag_flag.Flag.create(pole_locator,
                                    scale=scale,
                                    label='{0}_{1}_pv'.format(side, region),
                                    add_align_transform=True,
                                    orientation=ik_flag_pv_orient,
                                    meta_connect=False)

    pv_line = reference_line.create_line_between(middle_joint, pv_flag.node,
                                                 name='{0}_{1}_pv_line'.format(side, region))
    line_clusters = reference_line.get_line_clusters(pv_line)

    # The handle goes in an align group and the group is what the IK control drives, so the rig can
    # move the whole chain about without a constraint on the handle fighting the solver.
    ik_align_group = groups.create_align_transform(ik_handle_node)

    ik_flag.node.addAttr(SEPARATOR_ATTR, keyable=True, at='bool')
    ik_flag.node.setAttr(SEPARATOR_ATTR, edit=True, channelBox=True, lock=True)
    ik_flag.node.addAttr('ikTwist', keyable=True, at='double')
    ik_flag.node.ikTwist >> ik_handle_node.twist

    pv_constraint = pm.poleVectorConstraint(pv_flag, ik_handle_node, w=1)
    ik_constraint = pm.parentConstraint(ik_flag, ik_align_group, w=1, mo=1)
    pm.delete(pole_locator)

    if ik_flag_rotate_order:
        _set_rotate_order(ik_flag, ik_flag_rotate_order)

    pm.parent(ik_flag_offset.get_align_transform(), ik_flag)
    offset_constraint = pm.orientConstraint(ik_flag_offset, ik_end_joint, mo=1, w=1)

    # Each control knows the other, so a tool given one can find the pair.
    ik_flag.node.addAttr('offsetFlag', at='message')
    ik_flag_offset.node.addAttr('offsetFlag', at='message')
    ik_flag.node.offsetFlag >> ik_flag_offset.node.offsetFlag

    # The twist connection makes one of these, and the rig owns it so it can clean up after itself.
    unit_conv_nodes = [node for node in ik_flag.node.listConnections()
                       if isinstance(node, pm.nt.UnitConversion)]

    return {'chain': chain,
            'start_joint': start_joint,
            'end_joint': end_joint,
            'ik_end_joint': ik_end_joint,
            'middle_joint': middle_joint,
            'ik_handle': ik_handle_node,
            'ik_zero': ik_align_group,
            'ik_effector': ik_effector,
            'ik_flag': ik_flag,
            'ik_flag_offset': ik_flag_offset,
            'pv_flag': pv_flag,
            'pv_constraint': pv_constraint,
            'ik_constraint': ik_constraint,
            'offset_constraint': offset_constraint,
            'pv_line': pv_line,
            'flags': [ik_flag, ik_flag_offset, pv_flag],
            'line_clusters': line_clusters,
            'ik_solver': ik_solver,
            'unit_conv_nodes': unit_conv_nodes}


def _set_rotate_order(flag_node, rotate_order):
    """
    Change a control's rotate order without moving it.

    A rotate order is the order the three rotate channels are applied in, so changing it changes
    what the numbers already in those channels mean. A control built by ``Flag.create`` has its
    rotation in ``jointOrient`` and zeroes in ``rotate``, where the order makes no difference - but
    that is a property of how it was built rather than something this can rely on, so the
    orientation is measured onto a locator first and put back afterwards.

    :param flag_node: The control.
    :param str rotate_order: One of the six axis orders.
    """

    witness = locators.create_locator_at_object(flag_node.node)
    flag_node.node.rotateOrder.set(ROTATE_ORDERS[rotate_order])
    pm.delete(pm.orientConstraint(witness, flag_node.node, w=True, mo=False))
    pm.delete(witness)
