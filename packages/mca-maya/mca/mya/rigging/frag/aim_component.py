"""

A joint that points at a control: an eye, a head look-at, a turret.

The control does not drive the joint's rotation. It sits out in front of the joint, a locator aims
at it, and the joint follows that locator - so the animator moves a thing in space and the joint
turns to face it, and the control's own rotate channels stay out of the way.

What was wrong before:

- **Building the component wiped the Maya joint labels off the joint it drives.** Three lines copy
  ``side``, ``type`` and ``otherType`` from the control onto the bind joint, and a control built by
  ``Flag.create`` carries the defaults for all three - verified in a real Maya: side 0, type 0,
  ``otherType`` ``'jaw'``. So an eye joint came out labelled *centre / none*, whatever it had been.
  ``JointMarkup.side`` falls back to Maya's joint label when a joint has no ``skelSide``, which is
  what an imported skeleton is, so building the rig changed the side the pipeline reads off the
  eyes. This is the third component to do it, after ``ik_component`` and ``ikfk_component``; the
  three lines are gone.
- **``get_flags`` answered None for a component with no control**, where every other component in
  ``frag`` answers an empty list - so the three methods built on it, which a tool calls to select
  or key a component's controls, raised ``TypeError`` on iteration rather than doing nothing.
- **``create`` took no ``**kwargs``**, so it is the one component a rebuild cannot hand a shared
  argument list to: ``FRAGNode.get_build_kwargs`` answers everything that was recorded, and
  anything this signature does not name is a ``TypeError``.
- ``aim_target`` is recorded among the build arguments and used for nothing else at all, and it was
  recorded as ``aim_target if aim_target else None``, which is ``aim_target``.
- ``distance``, ``aimAxis`` and ``upAxis`` were added to the node with eight ``addAttr`` calls - a
  ``float3`` and its three children, twice - where ``attr_utils.set_attribute`` works out the type
  from the value. They are also the same three numbers that are already in ``buildKwargs``, so they
  are a second copy; they stay, because tools read them, and the readers say where they come from.
- ``select_flag``, ``key_flag`` and ``to_default_pose`` were this component's copy of the three
  methods every component carried; they are on ``KeyableComponent`` now, named for the lists they
  work on. ``get_eye_rotations`` assumed an up and forward axis in a comment and ignored the
  component's own ``aimAxis`` and ``upAxis`` attributes, which is worth knowing before trusting it.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import rig_aim_joint
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What the component keeps its pieces on.
FLAG_ATTR = 'flag'
ROTATE_OBJECT_ATTR = 'rotateObject'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: The three numbers tools read off the node. They are also in ``buildKwargs``; these are the copy
#: the rest of the pipeline reads, which is why both are kept.
DISTANCE_ATTR = 'distance'
AIM_AXIS_ATTR = 'aimAxis'
UP_AXIS_ATTR = 'upAxis'

#: Where the control sits, in units out along the aim axis, when the caller does not say.
DEFAULT_FLAG_DISTANCE = rig_aim_joint.DEFAULT_FLAG_DISTANCE

#: Which axis of the joint points at the control, and which stays up.
DEFAULT_AIM_AXIS = (1, 0, 0)
DEFAULT_UP_AXIS = (0, 0, 1)


class AimComponent(keyable_component.KeyableComponent):
    """
    One joint aiming at one control.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, bind_joint, side, region, aim_target=None,
               flag_distance=DEFAULT_FLAG_DISTANCE, aim_axis=DEFAULT_AIM_AXIS,
               up_axis=DEFAULT_UP_AXIS, proxy=False, **kwargs):
        """
        Build the component over one bind joint.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint bind_joint: The joint that ends up aiming.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param pm.nt.Transform aim_target: Recorded among the build arguments and used for nothing
            else; kept because a rebuild reads it back.
        :param float flag_distance: How far out along the aim axis to put the control.
        :param aim_axis: Which axis, in the joint's own space, points at the control.
        :param up_axis: Which axis, in the joint's own space, stays up.
        :param bool proxy: Build the setup but leave the bind joint alone, for a proxy rig that only
            has to look right rather than drive anything.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: AimComponent
        """

        build_kwargs = {'aim_target': aim_target, 'flag_distance': flag_distance,
                        'aim_axis': aim_axis, 'up_axis': up_axis, 'proxy': proxy}

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        AimComponent.__name__,
                                                        AimComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=bind_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        built = rig_aim_joint.rig_aim_joint(bind_joint=bind_joint, flag_distance=flag_distance,
                                           aim_axis=aim_axis, up_axis=up_axis, proxy=proxy)

        aim_flag = built['flag']
        rotate_loc = built['rotate_locator']
        align_group = built['rotate_loc_align_grp']

        pm.parent(align_group, node.no_touch_grp)
        pm.parent([rotate_loc, built['up_locator']], align_group)
        aim_flag.get_align_transform().setParent(node.flag_group)

        node.connect_node(aim_flag, FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(rotate_loc, ROTATE_OBJECT_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes([bind_joint], BIND_JOINTS_ATTR)

        # The same three numbers as in buildKwargs, under the names the rest of the pipeline reads
        # them by. Eight addAttr calls before, two of them building a float3 by hand.
        attr_utils.set_attribute(node.pynode, {DISTANCE_ATTR: float(flag_distance),
                                               AIM_AXIS_ATTR: list(aim_axis),
                                               UP_AXIS_ATTR: list(up_axis)})

        return node

    # ----------------------------------------------------------------------------------- #
    # the control
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        :return: The one control this component owns, or an empty list when it has lost it. The
            version before answered None, which every caller of the three methods built on this then
            tried to iterate.
        :rtype: list(frag_flag.Flag)
        """

        flag_node = lists.get_first_in_list(self.pynode.attr(FLAG_ATTR).listConnections())
        if flag_node is None:
            logger.warning('%s has no control wired to it.', self.pynode)
            return []
        return [frag_flag.Flag(flag_node)]

    def get_aim_flag(self):
        """
        :return: The control the joint points at, or None.
        :rtype: frag_flag.Flag or None
        """

        return lists.get_first_in_list(self.get_flags())

    # ----------------------------------------------------------------------------------- #
    # how it aims
    # ----------------------------------------------------------------------------------- #
    def get_rotate_object(self):
        """
        :return: The locator the joint follows, which the control aims.
        :rtype: pm.nt.Transform or None
        """

        return lists.get_first_in_list(self.pynode.attr(ROTATE_OBJECT_ATTR).listConnections())

    def get_aim_axis(self):
        """
        :return: The axis, in the joint's own space, that points at the control.
        :rtype: pm.dt.Vector
        """

        return pm.dt.Vector(self.pynode.attr(AIM_AXIS_ATTR).get())

    def get_up_axis(self):
        """
        :return: The axis, in the joint's own space, that stays up.
        :rtype: pm.dt.Vector
        """

        return pm.dt.Vector(self.pynode.attr(UP_AXIS_ATTR).get())

    def get_eye_rotations(self):
        """
        How far the joint is turned, as an animator would describe it.

        Reads the locator's rotation, and assumes the up axis is Y and the forward axis Z - it does
        *not* consult this component's own :meth:`get_aim_axis` and :meth:`get_up_axis`, so it is
        only right for a component built with the axes an eye uses. That was a comment before; it is
        in the docstring because it is the thing a caller needs to know.

        :return: Right/left and up/down, in degrees. Positive is right and up. None when the
            component has no locator.
        :rtype: list(float) or None
        """

        rotate_object = self.get_rotate_object()
        if rotate_object is None:
            logger.warning('%s has no locator on it, so how far it is aiming cannot be read.',
                           self.pynode)
            return None

        rotation = rotate_object.rotate.get()
        return [-rotation[1], -rotation[0]]
