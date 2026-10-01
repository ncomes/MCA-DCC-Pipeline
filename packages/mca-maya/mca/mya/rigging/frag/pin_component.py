"""
A control that rides a mesh: one joint pinned to a surface, wherever that surface ends up.

Everything else in a rig is driven by a hierarchy. This one is driven by the geometry: a uvPin reads
a UV coordinate on a mesh and writes the matrix there, so the control - and the joint it drives -
travels with the skinning and the blendshapes under it. That is what a cheek control, an eyelid
card or a piece of cloth tacked to a chest needs.

The order matters and is not obvious. The pin drives a group, the control's align transform sits
inside that group, and the control drives a duplicate of the bind joint, which drives the bind
joint. So the pin carries the whole lot, while the control's own channels stay zeroed and free for
an animator.

What was wrong before:

- **``bindJoints``, ``pinJoint`` and ``flags`` were each written with ``connect_nodes`` and a single
  node.** That works - the method wraps anything that is not a list - but it makes three multi
  attributes out of three things there is exactly one of, so ``bind_joints`` answers a one-item list
  where every other single-joint component in ``frag`` answers one joint, and ``get_flags`` reads a
  list of one. The one-of-a-kind ones go through ``connect_node``, and ``bindJoints`` stays a list
  because that is the attribute every other component shares.
- **``get_flags`` is the fourth copy of the same five methods.** ``select_flags``, ``key_flags`` and
  ``to_default_pose`` are character for character what ``FKComponent`` has, which is what
  ``WorldComponent`` has, which is what ``PinComponent`` has. They are on ``KeyableComponent`` now,
  which is the class all four inherit from, and each component is left with the one method that is
  actually its own: which attribute its controls hang off.
- **``attach_to_skeleton`` had its own copy of the twelve-line lookup** every component that can be
  driven by a skeleton used to carry; that is ``KeyableComponent.matching_chain``. It also asked
  ``ChainMarkup.get_start`` rather than walking the whole chain, which is right for a one-control
  component and is what it says now.
- ``lock_root_translate_axes=None`` meaning "all three translate channels" was written as a mutable
  default worked out inside the function; it is a module constant, and the parameter says what it
  locks. ``kwargs_dict`` recorded ``side`` and ``region`` among the build arguments, which are
  already on the node as its markup - and recorded ``pin_mesh`` as a node, so a rebuild is tied to
  that mesh still existing under that name.
- The control was built by wrapping ``fk_chain``'s answer in ``Flag`` again, and ``fk_chain``
  already answers ``Flag`` objects.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modeling import rivets
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import fk_chain
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import namespace
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The suffix the duplicated joint the control drives carries.
PIN_JOINT_SUFFIX = 'pin'

#: The suffix of the group the pin drives, which everything else in the component hangs under.
PIN_OFFSET_GROUP_SUFFIX = 'pin_offset_grp'

#: What the component keeps its pieces on.
PIN_FLAG_ATTR = 'pinFlag'
PIN_JOINT_ATTR = 'pinJoint'
PIN_NODE_ATTR = 'pinNode'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: What an animator is not allowed to do to the control by default. A pinned control is for turning
#: whatever rides the mesh; where it sits on the mesh is the rigger's decision, not the animator's.
DEFAULT_LOCKED_ATTRS = tuple(attr_utils.TRANSLATION_ATTRS)


class PinComponent(keyable_component.KeyableComponent):
    """
    One control pinned to a point on a mesh, driving one joint.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, bind_joint, pin_mesh, side, region,
               lock_root_translate_axes=DEFAULT_LOCKED_ATTRS, uv=None, **kwargs):
        """
        Build the component over one bind joint.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint bind_joint: The joint the control drives.
        :param pm.nt.Transform pin_mesh: The mesh the control rides.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param lock_root_translate_axes: Channels to take away from the animator, on top of
            visibility.
        :param uv: Where on the mesh to pin. None measures the closest point on the mesh to where
            the joint is.
        :type uv: list(float) or None
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component, or None when the mesh could not be pinned to.
        :rtype: PinComponent or None
        """

        build_kwargs = {'lock_root_translate_axes': lock_root_translate_axes, 'uv': uv}

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                       PinComponent.__name__,
                                                       PinComponent.VERSION,
                                                       side=side,
                                                       region=region,
                                                       align_component=bind_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        # The animator drives a copy and the bind joint follows it, as everywhere else in frag.
        pin_joint = joint_utils.duplicate_joint(
            bind_joint, '{0}_{1}'.format(naming.get_basename(bind_joint), PIN_JOINT_SUFFIX))
        pin_joint.setParent(node.no_touch_grp)
        constraint.parent_constraint_safe(pin_joint, bind_joint)

        built = fk_chain.fk_joint_chain(pin_joint, pin_joint, create_end_flag=True)
        pin_flag = built['flags'][0]
        pin_flag.lock_and_hide_attrs(['v'] + list(lock_root_translate_axes))

        # The pin drives this group, the control's align transform goes inside it, and the control
        # drives the joint - so the mesh carries the whole component while the control's own
        # channels stay zeroed.
        pin_offset_grp = pm.group(empty=True, world=True,
                                  name='{0}_{1}_{2}'.format(side, region,
                                                            PIN_OFFSET_GROUP_SUFFIX))
        pin_offset_grp.setParent(node.flag_group)
        pm.delete(constraint.parent_constraint_safe(pin_joint, pin_offset_grp))

        pin_node = rivets.create_uv_pin(pin_mesh, pin_offset_grp, uv=uv)
        if pin_node is None:
            logger.warning('%s could not be pinned to %s, so %s is removed again.', pin_offset_grp,
                           pin_mesh, node.pynode)
            node.remove()
            return None

        pin_flag.get_align_transform().setParent(pin_offset_grp)

        node.connect_node(pin_flag, PIN_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(pin_joint, PIN_JOINT_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(pin_node, PIN_NODE_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes([bind_joint], BIND_JOINTS_ATTR)

        return node

    def get_flags(self):
        """
        :return: The one control this component owns.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(self.pynode.attr(PIN_FLAG_ATTR).get())]

    @property
    def pin_flag(self):
        """
        :return: The control that rides the mesh.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(PIN_FLAG_ATTR).get())

    @property
    def pin_node(self):
        """
        :return: The uvPin reading the mesh.
        :rtype: pm.nt.UvPin
        """

        return self.pynode.attr(PIN_NODE_ATTR).get()

    @property
    def uv(self):
        """
        :return: Where on the mesh this component is pinned, as U and V.
        :rtype: list(float)
        """

        coordinate = self.pin_node.coordinate[0]
        return [coordinate.coordinateU.get(), coordinate.coordinateV.get()]

    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's control from a skeleton.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep the control where it is rather than snapping it to the joint.
        :return: The constraint built, in a list, or an empty list.
        :rtype: list
        """

        joint_list = self.matching_chain(attach_skeleton_root)
        if not joint_list:
            return []

        constraint_node = constraint.parent_constraint_safe(joint_list[0], self.pin_flag, mo=mo)
        return [constraint_node] if constraint_node else []
