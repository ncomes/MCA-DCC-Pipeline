"""
What every piece of a rig an animator touches has in common.

A keyable component is a :class:`~rig_component.RigComponent` with controls: it adds the
``flags_<side>_<region>`` group those controls live in, and the handful of things that only mean
anything once a component has both controls and joints - baking the controls onto the skeleton,
being driven by a skeleton, and working out what there is to bake.

Two pieces of being driven by a skeleton are the same in every component that can be: finding the
run of joints on the other skeleton that answers to this component's region and side, which is
:meth:`KeyableComponent.matching_chain`, and driving a pole vector control, which has no joint of
its own to follow, which is :func:`constrain_to_pole_vector`. Both were written out again in each
component that needed them.

What was wrong before:

- **The two groups a component gets were named with different spellings of the same side.** The side
  is lower-cased on the way into ``RigComponent.create``, which names the ``NO_TOUCH`` group, and
  then used as it came in to name the control group - so a component built for ``'Left'`` came out
  with ``NO_TOUCH_left_arm`` beside ``flags_Left_arm``, and its markup said ``left`` while half its
  node names said ``Left``. The side is lower-cased once, before either group is named.
- **``get_bakeable_rig_nodes`` counted every control after the first one worth baking as worth
  baking.** It collects the keyable attributes of every control into one running list and then asks
  ``if constraint_list or attr_list`` - the *running* list, not this control's - so once any control
  in the component had a keyable attribute, every control after it went into the bake whether it had
  anything or not. It asks about the control in front of it now.
- **``bake_to_skeleton`` and ``get_bakeable_skeleton_nodes`` read ``bindJoints`` without asking
  whether the component has it**, while the :attr:`bind_joints` property beside them does ask. A
  component with no joints - a space switch, a channel holder - raised. Both go through it now.
- **A component built with no parent raised ``AttributeError``**, the same way ``RigComponent`` did:
  ``create`` asks the parent what type it is.
- ``remove`` deleted the two groups and the node in one call, which is the pattern that bit
  ``matrix_nodes.remove_matrix_constraint``: Maya's delete takes a node's history with it, so a
  second name in the same call can already be gone by the time it is reached. These three cannot
  contain one another, so it holds - and it says so, rather than leaving the next reader to work it
  out.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.animation import baking
from mca.mya.rigging import chain_markup
from mca.mya.rigging import ik_utils
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import rig_component
from mca.mya.utils import constraint


logger = log.MCA_LOGGER

#: The attribute holding the group a component's controls live in.
FLAG_GROUP_ATTR = rig_component.FLAG_GROUP_ATTR

#: The attribute holding the joints a component drives.
BIND_JOINTS_ATTR = 'bindJoints'

#: Controls carry this to say a helper was built to bake them, so it can be cleaned up after.
BAKE_HELPER_ATTR = 'bake_helper'

#: Attributes to leave out of a bake whatever else is true of them. ``toeTap`` is exposed on the
#: offset control as a pass-through, cannot be keyed there, and makes ``bakeResults`` fail further
#: down the pipeline.
UNBAKEABLE_ATTRS = ('toeTap',)


class KeyableComponent(rig_component.RigComponent):
    """
    One piece of a rig with controls on it - an arm, a spine, a foot.
    """

    @staticmethod
    def create(frag_parent, frag_type, version, side, region, align_component=None):
        """
        Build a component's metadata node, its ``NO_TOUCH`` group and its control group.

        :param FRAGNode frag_parent: The rig, or the component, this one hangs off. None builds a
            component with nothing above it, which leaves its groups at the scene root.
        :param str frag_type: The name of the class being built.
        :param float version: The version of that class.
        :param str side: Which side of the body it is on. Lower-cased once, before anything is
            named with it - the version before lower-cased it for one group's name, not the other's.
        :param str region: What part of the body it is.
        :param pm.nt.DagNode align_component: Something to snap both groups to before their
            transforms are frozen, which undoes the snap - see ``rig_component``'s module docstring.
        :return: The component.
        :rtype: KeyableComponent
        """

        side = side.lower()
        node = rig_component.RigComponent.create(frag_parent, frag_type, version, side=side,
                                                 region=region, align_component=align_component)

        flag_group = pm.group(empty=True, n='flags_{0}_{1}'.format(side, region))
        if align_component:
            pm.delete(pm.parentConstraint(pm.PyNode(align_component), flag_group,
                                          w=True, mo=False))
        pm.makeIdentity(flag_group, apply=True, t=True, r=True, s=True)

        node.connect_node(flag_group, FLAG_GROUP_ATTR, frag_base.FRAG_PARENT_ATTR)
        if frag_parent is not None and frag_parent.get_type() == rig_component.FRAG_RIG_TYPE:
            flag_group.setParent(frag_parent.pynode.attr('flagsAll').get())

        return node

    @property
    def flag_group(self):
        """
        :return: The group this component's controls live in.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(FLAG_GROUP_ATTR).get()

    @property
    def bind_joints(self):
        """
        :return: The joints this component drives, or an empty list when it drives none.
        :rtype: list(pm.nt.Joint)
        """

        if not self.pynode.hasAttr(BIND_JOINTS_ATTR):
            return []
        return self.pynode.attr(BIND_JOINTS_ATTR).get() or []

    def remove(self):
        """
        Take this component out of the rig: both its groups, everything in them, and its node.

        The three are deleted in one call, which is only safe because none of them is in another's
        history - Maya's delete follows history, and a second name in the same call can be gone
        already by the time it is reached.
        """

        pm.delete([self.no_touch_grp, self.flag_group, self.pynode])

    # ----------------------------------------------------------------------------------- #
    # the skeleton
    # ----------------------------------------------------------------------------------- #
    def matching_chain(self, attach_skeleton_root):
        """
        The run of joints on another skeleton that this component belongs over.

        A component is driven by a skeleton other than its own - a mocap skeleton, a skeleton
        carrying animation from another character - by looking up the same region and side on it.
        Which region and side to look up is read off the first joint this component drives, because
        the markup on the joints is what the lookup is against; the component's own ``side`` and
        ``region`` are the fallback for a component whose joints carry no markup, and for one that
        drives no joints at all.

        Every component that can be driven by a skeleton started with its own copy of these twelve
        lines. They are here once.

        One thing worth knowing about the fallback: ``JointMarkup.side`` falls back to Maya's own
        joint side label when a joint has no ``skelSide``, and that label always has a value - zero,
        meaning ``center``, on a joint nothing has labelled. So the side almost never falls through
        to the component's own, while the region often does. A component built for the left over
        joints carrying no markup looks up the *centre* chain.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to look in.
        :return: The joints, root first, or an empty list when nothing on that skeleton matches.
        :rtype: list(pm.nt.Joint)
        """

        bind_joint_list = self.bind_joints
        region = None
        side = None
        if bind_joint_list:
            markup = chain_markup.JointMarkup(bind_joint_list[0])
            region = markup.region
            side = markup.side

        region = region or self.region
        side = side or self.side

        return chain_markup.ChainMarkup(attach_skeleton_root).get_full_chain(region, side)

    def attach_to_skeleton(self, *args, **kwargs):
        """
        Drive this component from a skeleton. A bare keyable component cannot; the ones that can
        override this.

        :param tuple args: Whatever the override takes.
        :param dict kwargs: Whatever the override takes.
        :return: The constraints built, which for this one is none.
        :rtype: list
        """

        return []

    def set_scale(self):
        """
        Wire this component's scale. A bare keyable component has none to wire; the ones that do
        override this.
        """

    def bake_to_skeleton(self, bake_range=None, **kwargs):
        """
        Bake what this component is doing onto the joints it drives.

        :param bake_range: The first and last frame to bake between. None bakes the whole range.
        :type bake_range: list(int) or None
        :param dict kwargs: Whatever else ``baking.bake_objects`` takes.
        """

        bind_joint_list = self.bind_joints
        if not bind_joint_list:
            logger.warning('%s drives no joints, so there is nothing to bake it onto.', self.pynode)
            return

        # A joint can carry keyable attributes of its own that the rig drives, and a bake leaving
        # them out leaves the skeleton reading differently from the rig.
        custom_attrs = []
        for bind_joint in bind_joint_list:
            custom_attrs += bind_joint.listAttr(userDefined=True, keyable=True)

        baking.bake_objects(bind_joint_list, bake_range=bake_range, custom_attrs=custom_attrs,
                            **kwargs)

    def get_bakeable_skeleton_nodes(self):
        """
        :return: The joints this component drives.
        :rtype: list(pm.nt.Joint)
        """

        return self.bind_joints

    def get_bakeable_rig_nodes(self):
        """
        What there is to bake on this component's controls, and what to clear away afterwards.

        A control is worth baking when something is driving it: a constraint, or an incoming
        connection on one of its own keyable attributes. Anything built purely to drive it during
        the bake - a helper, and the constraints to it - comes back to be deleted afterwards.

        :return: The controls worth baking, the names of the attributes to bake on them, and the
            nodes to delete afterwards.
        :rtype: tuple(list, list(str), list)
        """

        bakeable_flags = []
        attr_list = []
        things_to_delete = []

        for flag_node in self.get_flags():
            constraint_list = flag_node.getChildren(type=pm.nt.ParentConstraint)
            for constraint_node in constraint_list:
                things_to_delete += [target for target
                                     in constraint.get_constraint_targets(constraint_node)
                                     if hasattr(target, BAKE_HELPER_ATTR)]
            things_to_delete += constraint_list

            driven_attrs = [attribute.attrName() for attribute
                            in flag_node.listAttr(userDefined=True, keyable=True, settable=True)
                            if attribute.listConnections(destination=False)
                            and attribute.attrName() not in UNBAKEABLE_ATTRS]
            attr_list += driven_attrs

            # This control's own attributes, not every attribute found so far: asking the running
            # list put every control after the first interesting one into the bake.
            if constraint_list or driven_attrs:
                bakeable_flags.append(flag_node)

        return bakeable_flags, attr_list, things_to_delete


def constrain_to_pole_vector(joint_list, pv_flag, mo=True):
    """
    Drive a pole vector control from a skeleton.

    A pole vector control has no joint of its own to follow. Where it belongs is read off the pose
    of the three joints it steers, so a locator is put at that position, parented to the middle
    joint so that it travels with the limb, and the control is constrained to it. The locator is
    marked as a bake helper, which is what lets
    :meth:`KeyableComponent.get_bakeable_rig_nodes` find it and clear it away once the bake is
    done.

    The three components that have a pole vector each had their own copy of this, and none of them
    asked whether there was a pole vector to be had.

    :param list(pm.nt.Joint) joint_list: The joints the pole vector steers, root first. Three or
        more; a longer list is read the same way ``ik_utils.get_pole_vector_position`` reads it.
    :param pv_flag: The pole vector control to drive.
    :param bool mo: Keep the control where it is rather than snapping it to the locator.
    :return: The constraint, or None when no pole vector position can be read from the chain - which
        is what a chain of fewer than three joints answers, and what the version before called
        ``setParent`` on.
    :rtype: pm.nt.ParentConstraint or None
    """

    pv_locator = ik_utils.create_pole_vector_locator(joint_list)
    if pv_locator is None:
        logger.warning('No pole vector position can be read from %s, so %s is not driven by it.',
                       joint_list, pv_flag)
        return None

    pv_locator.setParent(joint_list[1])
    pv_locator.addAttr(BAKE_HELPER_ATTR, at=bool, dv=True)
    return constraint.parent_constraint_safe(pv_locator, pv_flag, mo=mo)
