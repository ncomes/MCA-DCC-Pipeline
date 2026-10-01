"""

Spreading a limb's twist across the helper joints that carry it.

A forearm that rotates 90 degrees at the wrist shears the skin unless the twist is handed out along
the way, so a skeleton carries extra joints between the elbow and the wrist whose only job is to
take a share of it. ``twist_setup`` builds the system that measures the driving joint's rotation
and distributes it; this is the component that records it. It has no controls of its own - an
animator never touches it - which is why it is a :class:`~rig_component.RigComponent` rather than a
keyable one.

What was wrong before:

- **It is at version 2 and has no step to get there from version 1.** ``FRAGNode.update`` builds
  the name of the step it needs from the two versions, and a twist component built by the version
  that wrote 1 therefore raises ``AttributeError`` saying ``_update_version_1_to_version_2`` does
  not exist - which it does not, in this class or any class it inherits from. Nothing about the
  node changed between the two versions as far as this file shows, so the step is written and does
  nothing but record the version. That is the honest version of what happened: the number was
  raised and the step was not written.
- **A twist joint at the top of a hierarchy raised while the component was being aligned.** The
  alignment is ``joint_list[0].getParent().getParent()`` - the limb joint whose rotation is being
  spread - and both of those calls answer None for a joint near the root, so the second is an
  ``AttributeError`` before the component exists. It asks, and falls back to the joint itself.
- **An empty joint list raised on ``joint_list[0]``**, before the warning ``twist_setup`` would
  have given.
- **A setup that could not be built left a component with nothing on it.** ``twist_setup`` answers
  ``(None, {})`` for joints it cannot use - no parent joint to take the twist from, more joints
  than one ``multiplyDivide`` can drive - and ``create`` returned the component anyway, with no
  ``bindJoints`` and nothing connected, so a rig carried a twist component that twists nothing and
  said so nowhere. It refuses, and takes its own node back out of the scene.
- Six of the eight things it records are single nodes written with ``connect_nodes``, which makes a
  list attribute out of something there is one of. The two that are lists stay lists.
"""

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import twist_setup
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import rig_component
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What the component keeps its pieces on.
BIND_JOINTS_ATTR = 'bindJoints'
MIRROR_CHAIN_ATTR = 'mirrorChain'
IK_CHAIN_ATTR = 'ikChain'
IK_HANDLE_ATTR = 'ikHandle'
MULTI_NODE_ATTR = 'multiNode'
OFFSET_LOC_ATTR = 'offsetLoc'
UNIT_CONV_NODES_ATTR = 'unitConvNodes'
TWIST_GROUP_ATTR = 'twistGroups'


class TwistFixUpComponent(rig_component.RigComponent):
    """
    The system that spreads one limb joint's twist across its helper joints. No controls.
    """

    VERSION = 2

    def _update_version_1_to_version_2(self):
        """
        Bring a version 1 component up to version 2.

        There is nothing to do. The class's version was raised to 2 and the step was never written,
        so every twist component built before that raised ``AttributeError`` the moment anything
        asked it to update - and ``update_all_frag_nodes`` walks a whole rig. This records the
        version and says why it does nothing, which is better than the number being wrong in the
        other direction.
        """

        self.set_version(2)

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, joint_list, side, region, **kwargs):
        """
        Build the component over a segment's twist joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param list(pm.nt.Joint) joint_list: The twist joints on one segment.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component, or None when there are no joints to drive or the setup could not be
            built. The version before answered a component with nothing on it.
        :rtype: TwistFixUpComponent or None
        """

        if not joint_list:
            logger.warning('No twist joints were given, so no twist component was built for %s %s.',
                           side, region)
            return None

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = rig_component.RigComponent.create(frag_parent,
                                                TwistFixUpComponent.__name__,
                                                TwistFixUpComponent.VERSION,
                                                side=side,
                                                region=region,
                                                align_component=_driving_joint(joint_list[0]))

        twist_grp, built = twist_setup.twist_setup(joint_list)
        if not twist_grp:
            # twist_setup has already said why. A component recording a setup that is not there is
            # worse than no component, which is what the version before left behind.
            logger.warning('No twist setup could be built for %s %s, so %s is removed again.',
                           side, region, node.pynode)
            node.remove()
            return None

        twist_grp.setParent(node.no_touch_grp)

        node.connect_nodes(joint_list, BIND_JOINTS_ATTR)
        node.connect_nodes(built['mirror_chain'], MIRROR_CHAIN_ATTR)
        node.connect_nodes(built['ik_chain'], IK_CHAIN_ATTR)
        node.connect_node(built['ik_handle'], IK_HANDLE_ATTR)
        node.connect_node(built['multi_node'], MULTI_NODE_ATTR)
        node.connect_node(built['offset_loc'], OFFSET_LOC_ATTR)
        node.connect_nodes(built['unit_conv_nodes'], UNIT_CONV_NODES_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_node(twist_grp, TWIST_GROUP_ATTR, frag_base.FRAG_PARENT_ATTR)

        return node

    @property
    def bind_joints(self):
        """
        :return: The twist joints this component drives.
        :rtype: list(pm.nt.Joint)
        """

        if not self.pynode.hasAttr(BIND_JOINTS_ATTR):
            return []
        return self.pynode.attr(BIND_JOINTS_ATTR).get() or []

    @property
    def twist_group(self):
        """
        :return: The group holding the setup.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(TWIST_GROUP_ATTR).get()

    @property
    def multi_node(self):
        """
        :return: The node that gives each twist joint its share of the rotation.
        :rtype: pm.nt.MultiplyDivide
        """

        return self.pynode.attr(MULTI_NODE_ATTR).get()


def _driving_joint(twist_joint):
    """
    The limb joint whose rotation a twist joint's segment is spreading.

    Two levels up: the twist joints hang off the joint below the one that turns. Both reads answer
    None for a joint near the root of a skeleton, and the version before chained them without
    asking, so a twist joint high in a hierarchy was an ``AttributeError`` before the component
    existed.

    :param pm.nt.Joint twist_joint: The first twist joint of the segment.
    :return: The joint to align the component to, which is the twist joint itself when there is
        nothing two levels above it.
    :rtype: pm.nt.Joint
    """

    parent = twist_joint.getParent()
    grandparent = parent.getParent() if parent else None
    if grandparent is None:
        logger.warning('%s has nothing two levels above it, so %s is aligned to the joint itself.',
                       twist_joint, twist_joint)
        return twist_joint
    return grandparent
