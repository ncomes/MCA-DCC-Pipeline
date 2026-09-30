"""
The IK/FK switch: one control carrying the blend between a limb's two systems.

A small flag constrained to a joint, with a 0-to-1 attribute on it. Both systems read the same
attribute - one straight, one inverted - so they cannot both be on at once, and an animator has one
thing to key.

What was wrong before: nothing, beyond the result dictionary being assembled a line at a time.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import attr_utils


logger = log.MCA_LOGGER

#: The switch control is drawn at half a limb control's size - it is a dial, not a handle.
SWITCH_SCALE = 0.5

#: The name of the attribute an animator keys.
SWITCH_ATTR = 'ikfk_switch'


def ikfk_switch(switch_joint, side, region, switch_attr_name=SWITCH_ATTR, scale=1.0):
    """
    Build an IK/FK switch control on a joint.

    :param pm.nt.Joint switch_joint: The joint the control sits on and follows.
    :param str side: Which side the limb is on, for the control's name.
    :param str region: The limb's region, for the control's name.
    :param str switch_attr_name: The name of the switch attribute.
    :param float scale: A limb control's size; the switch is drawn at half of it.
    :return: The nodes built, under ``invert_node``, ``flag`` and ``name`` - the last being the
        switch attribute's name, which the callers use to build the connections.
    :rtype: dict
    """

    switch_flag = frag_flag.Flag.create(switch_joint,
                                        label='{0}_{1}_ikfk_switch'.format(side, region),
                                        scale=scale * SWITCH_SCALE,
                                        add_align_transform=True)
    switch_flag.node.addAttr(switch_attr_name, keyable=True, at='double', min=0, max=1, dv=1)

    # One node reads the switch three ways - as itself, as one minus itself, and as a percentage -
    # so the two systems can each take the reading they need from the same attribute.
    invert_node = attr_utils.invert_attribute(switch_flag.node.attr(switch_attr_name))
    pm.rename(invert_node, '{0}_{1}_switch_invert_node'.format(side, region))

    # On the align transform, not the flag: the flag's own channels stay free for the animator.
    align_transform = switch_flag.get_align_transform()
    pm.pointConstraint(switch_joint, align_transform, weight=1, maintainOffset=True)
    pm.orientConstraint(switch_joint, align_transform, weight=1, maintainOffset=True)

    return {'invert_node': invert_node,
            'flag': switch_flag,
            'name': switch_attr_name}
