"""
The three controls at the top of every rig: world, offset and root.

World moves the character through the scene. Root, a sub control under it, is what the bind skeleton
actually follows, so animation on the skeleton and animation on the world control stay separable.
Offset sits between them as a detail control, for the small corrections nobody wants on the world
control's curves.

One joint - the skeleton's root - duplicated, the three controls stacked over the duplicate, and the
real root joint constrained to it.

What was wrong before:

- **``attach_to_skeleton`` could answer ``[None]``.** It builds its constraint and returns
  ``[constraint_node]`` with no guard, and both the joint lookup and
  ``constraint.parent_constraint_safe`` answer None - the lookup when the skeleton has no matching
  markup, the constraint when every channel it would drive is locked. Every caller then has a
  list with None in it to iterate over and delete. Every other component in ``frag`` guards this
  one line.
- ``create`` walked between the root joint and itself to get a one-item list, then looped over
  that list with ``zip`` to make one constraint. It is one joint; it says so.
- ``attach_to_skeleton`` had its own copy of the twelve-line lookup every component that can be
  driven by a skeleton used to carry; that is ``KeyableComponent.matching_chain``.
- The three controls are read back with ``self.pynode.flags.get()`` and each wrapped in ``Flag``,
  which raises from inside the wrapper if any of the three has come off. It says which is missing.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import joint_utils
from mca.mya.rigging import world_chain_rig
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The suffix the duplicated root joint carries.
WORLD_CHAIN_SUFFIX = 'world_chain'

#: What the component keeps its pieces on.
FLAGS_ATTR = 'flags'
WORLD_CHAIN_ATTR = 'worldChain'
WORLD_FLAG_ATTR = 'worldFlag'
ROOT_FLAG_ATTR = 'rootFlag'
OFFSET_FLAG_ATTR = 'offsetFlag'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR


class WorldComponent(keyable_component.KeyableComponent):
    """
    The world, offset and root controls, and the one joint they drive.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, side, region, attrs_to_lock=(), scale=1.0,
               orientation=world_chain_rig.DEFAULT_ORIENTATION, **kwargs):
        """
        Build the component over a skeleton's root joint.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The skeleton's root joint.
        :param str side: Which side of the body it is on - ``center``, for these.
        :param str region: What part of the body it is.
        :param attrs_to_lock: Channels to take away from the animator, on all three controls.
        :param float scale: How big to draw the world control; the other two are drawn smaller.
        :param orientation: A rotation for each control's zero pose.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: WorldComponent
        """

        build_kwargs = {'attrs_to_lock': attrs_to_lock, 'scale': scale, 'orientation': orientation}

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        WorldComponent.__name__,
                                                        WorldComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        # One joint. The version before walked from the root joint to itself for a one-item list and
        # then looped over it.
        world_joint = joint_utils.duplicate_chain(start_joint, start_joint,
                                                  suffix=WORLD_CHAIN_SUFFIX)[0]
        world_joint.setParent(node.no_touch_grp)
        built = world_chain_rig.world_chain(world_joint, scale=scale, orientation=orientation)

        world_flag = built['world_flag']
        offset_flag = built['offset_flag']
        root_flag = built['root_flag']
        offset_flag.set_as_detail()
        root_flag.set_as_sub()
        built['align_group'].setParent(node.flag_group)

        node.connect_nodes([world_flag, offset_flag, root_flag], FLAGS_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes([world_joint], WORLD_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(world_flag, WORLD_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(root_flag, ROOT_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(offset_flag, OFFSET_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes([start_joint], BIND_JOINTS_ATTR)

        if attrs_to_lock:
            for flag_node in (world_flag, offset_flag, root_flag):
                flag_node.lock_and_hide_attrs(list(attrs_to_lock))

        # The one constraint the component makes: the duplicate drives the real root joint.
        pm.parentConstraint(world_joint, start_joint, w=1)

        return node

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        :return: The three controls, world first. One that has come off the node is left out and
            reported rather than wrapped and raising from inside the wrapper.
        :rtype: list(frag_flag.Flag)
        """

        found = []
        for attr_name in (WORLD_FLAG_ATTR, OFFSET_FLAG_ATTR, ROOT_FLAG_ATTR):
            flag_node = self.pynode.attr(attr_name).get()
            if flag_node is None:
                logger.warning('%s has nothing wired to %s, so that control is missing from its '
                               'flag list.', self.pynode, attr_name)
                continue
            found.append(frag_flag.Flag(flag_node))
        return found

    @property
    def world_flag(self):
        """
        :return: The control that moves the character through the scene.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(WORLD_FLAG_ATTR).get())

    @property
    def offset_flag(self):
        """
        :return: The detail control between the world and the root.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(OFFSET_FLAG_ATTR).get())

    @property
    def root_flag(self):
        """
        :return: The sub control the bind skeleton follows.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(ROOT_FLAG_ATTR).get())

    # ----------------------------------------------------------------------------------- #
    # being driven by a skeleton
    # ----------------------------------------------------------------------------------- #
    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive the root control from a skeleton, which carries the whole rig with it.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep the control where it is rather than snapping it to the joint.
        :return: The constraint built, in a list, or an empty list. The version before returned
            ``[constraint_node]`` with no guard, so a skeleton with no matching markup - or a
            control with every channel locked - handed every caller a list with None in it.
        :rtype: list
        """

        joint_list = self.matching_chain(attach_skeleton_root)
        if not joint_list:
            return []

        constraint_node = constraint.parent_constraint_safe(joint_list[0], self.root_flag, mo=mo)
        return [constraint_node] if constraint_node else []
