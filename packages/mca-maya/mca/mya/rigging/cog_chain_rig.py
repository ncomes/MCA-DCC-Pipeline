"""
The centre-of-gravity control: the one an animator moves to move the whole character.

One flag per joint from the start of the chain to the end, each parent constraining its joint. In
practice the chain is one or two joints - the COG is a single control at the character's hips - but
it is built as a chain because a quadruped or a vehicle wants more than one.

What was wrong before: nothing, beyond the result dictionary being assembled a line at a time.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import dag


logger = log.MCA_LOGGER

#: Maya's ``zxy`` rotate order. A COG control is turned about the vertical axis far more often than
#: the other two, and putting that axis last keeps it out of the gimbal.
COG_ROTATE_ORDER = 2

#: The flags are turned by this much so a flat control drawn in XZ reads as horizontal.
DEFAULT_ORIENTATION = (-90, 0, 0)


def cog_chain(start_joint, end_joint, scale=1.0, orientation=DEFAULT_ORIENTATION):
    """
    Build a COG control for every joint in a chain.

    :param pm.nt.Joint start_joint: The first joint of the chain.
    :param pm.nt.Joint end_joint: The last one.
    :param float scale: How big to draw the controls.
    :param orientation: A rotation for each control's zero pose.
    :return: The chain, its ends, the flags and the constraints, under ``chain``, ``start_joint``,
        ``end_joint``, ``flags`` and ``constraints``.
    :rtype: dict
    """

    chain = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
    if not chain:
        logger.warning('%s is not above %s, so no COG chain was built.', start_joint, end_joint)

    flags = []
    constraints = []
    for joint_node in chain:
        flag_node = frag_flag.Flag.create(joint_node, label='cog', orientation=orientation,
                                         scale=scale)
        flag_node.node.rotateOrder.set(COG_ROTATE_ORDER)
        constraints.append(pm.parentConstraint(flag_node, joint_node, weight=1,
                                              maintainOffset=True))
        flags.append(flag_node)

    return {'chain': chain,
            'start_joint': start_joint,
            'end_joint': end_joint,
            'flags': flags,
            'constraints': constraints}
