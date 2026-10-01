"""
The component that drives a limb from its end: an IK handle, a control to place the end, and one to
say which way the middle bends.

The chain the animator sees is not the one the skeleton uses. This duplicates the bind joints,
builds the IK on the copy with ``ik_chain.ik_joint_chain``, and parent constrains the bind joints to
it - so the rig can be taken apart without the skeleton noticing.

What was wrong before:

- **Building the component wiped the Maya joint labels off the bind joints it drives.** Six lines
  copied ``side``, ``type`` and ``otherType`` from the controls onto the middle and end joints - and
  a control built by ``Flag.create`` carries the defaults for all three, whatever it was built on.
  So the middle joint's label became *centre / none*, and the end joint's with it. That is not
  cosmetic: ``JointMarkup.side`` falls back to Maya's joint label when a joint has no ``skelSide``
  markup, which is what an imported skeleton is, so it changed the side the pipeline reads off those
  joints. There is no reading under which copying a control's default labelling onto a joint is
  wanted; the six lines are gone.
- **The chain-length guard said three and accepted four**, and named neither the joints nor the
  count: ``RuntimeError('There can only be 3 joints between start_joint and end_joint
  inclusively')``. It is ``ik_chain``'s own rule, so it is ``ik_chain``'s own constant, and the
  message says what it got. It is also asked before the chain is duplicated, rather than after -
  the version before left a duplicated chain and two groups behind when it raised.
- **``attach_to_skeleton`` raised on a short chain.** It reaches ``joint_list[1]`` without asking
  how long the chain is, and ``ik_utils.create_pole_vector_locator`` answers None for a chain of
  fewer than three joints, which the next line calls ``setParent`` on. Both the lookup and the
  pole vector are now the shared helpers in ``keyable_component``, which ask.
- ``if flag_list:`` guarded a list built two lines above out of two attributes, so it was always
  true. The build arguments written down for a rebuild were an empty dictionary, which is the same
  answer ``get_build_kwargs`` gives for a node with nothing written on it - so the write is gone,
  and the signature says what it does with the ``**kwargs`` it absorbs rather than calling it
  "serialization compatibility".
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import ik_chain
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import constraint
from mca.mya.utils import dag


logger = log.MCA_LOGGER

#: The suffix the duplicated chain the IK is built on carries.
IK_CHAIN_SUFFIX = 'ik_chain'

#: What the component keeps its pieces on.
IK_FLAG_ATTR = 'ikFlag'
IK_FLAG_OFFSET_ATTR = 'ikFlagOffset'
PV_FLAG_ATTR = 'pvFlag'
PV_LINE_ATTR = 'pvLine'
IK_HANDLE_ATTR = 'ikHandle'
IK_SOLVER_ATTR = 'ikSolver'
IK_CHAIN_ATTR = 'ikChain'
FLAGS_ATTR = 'flags'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR
UNIT_CONV_NODES_ATTR = 'unitConvNodes'

#: What an animator is not allowed to do to each control.
IK_FLAG_LOCKED_ATTRS = ('sx', 'sy', 'sz', 'v')
PV_FLAG_LOCKED_ATTRS = ('rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v')


class IKComponent(keyable_component.KeyableComponent):
    """
    One limb driven from its end, with a pole vector control for the bend.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, end_joint, side, region, **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The first bind joint.
        :param pm.nt.Joint end_joint: The last one.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: IKComponent
        :raises RuntimeError: When the run of joints is not a length a rotate-plane IK can be built
            on.
        """

        chain_between = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
        # Asked before anything is built, and by ik_chain's own rule rather than a second copy
        # of it.
        if len(chain_between) not in ik_chain.VALID_CHAIN_LENGTHS:
            raise RuntimeError(
                'An IK component is built on {0} joints. {1} to {2} is {3} joints long.'.format(
                    ' or '.join(str(length) for length in ik_chain.VALID_CHAIN_LENGTHS),
                    start_joint, end_joint, len(chain_between)))

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set='{0}:'.format(root_namespace))

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        IKComponent.__name__,
                                                        IKComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)

        flag_grp = node.flag_group
        nt_grp = node.no_touch_grp

        # The animator drives a copy and the bind joints follow it. That is what lets the rig be
        # rebuilt without the skeleton being touched.
        chain_ik = joint_utils.duplicate_chain(start_joint, end_joint, suffix=IK_CHAIN_SUFFIX)
        chain_ik[0].setParent(nt_grp)
        built = ik_chain.ik_joint_chain(chain_ik[0], chain_ik[-1], side=side, region=region)

        ik_align_group = built['ik_zero']
        ik_align_group.visibility.set(0)
        ik_flag = built['ik_flag']
        ik_flag_offset = built['ik_flag_offset']
        pv_flag = built['pv_flag']
        pv_line = built['pv_line']

        # The guide line is shown and hidden with the control it points at.
        pv_flag.node.visibility >> pv_line.visibility
        pv_flag.node.overrideVisibility >> pv_line.overrideVisibility

        pm.parent([pv_line, ik_align_group], nt_grp)
        pm.parent([ik_flag.get_align_transform(), pv_flag.get_align_transform()], flag_grp)

        node.connect_node(ik_flag, IK_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(ik_flag_offset, IK_FLAG_OFFSET_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(pv_flag, PV_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(pv_line, PV_LINE_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(built['ik_handle'], IK_HANDLE_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(built['ik_solver'], IK_SOLVER_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(chain_ik, IK_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(built['flags'], FLAGS_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(built['unit_conv_nodes'], UNIT_CONV_NODES_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(chain_between, BIND_JOINTS_ATTR)

        ik_flag.lock_and_hide_attrs(list(IK_FLAG_LOCKED_ATTRS))
        pv_flag.lock_and_hide_attrs(list(PV_FLAG_LOCKED_ATTRS))

        # The three joints the IK solves over. A fourth, where there is one, hangs off the end
        # of the IK and follows its parent rather than being driven in its own right.
        for ik_joint, bind_joint in zip(chain_ik[:3], chain_between[:3]):
            pm.parentConstraint(ik_joint, bind_joint, w=1, mo=1)

        return node

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        :return: Every control this component owns.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(node) for node in self.pynode.attr(FLAGS_ATTR).listConnections()]

    @property
    def ik_flag(self):
        """
        :return: The control that places the end of the limb.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(IK_FLAG_ATTR).get())

    @property
    def ik_flag_offset(self):
        """
        :return: The detail control under it, for turning the end without moving it.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(IK_FLAG_OFFSET_ATTR).get())

    @property
    def pv_flag(self):
        """
        :return: The control that says which way the middle of the limb bends.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(PV_FLAG_ATTR).get())

    # ----------------------------------------------------------------------------------- #
    # being driven by a skeleton
    # ----------------------------------------------------------------------------------- #
    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's controls from a skeleton, so animation on the skeleton reaches the
        rig.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep each control where it is rather than snapping it to its joint.
        :return: The constraints built.
        :rtype: list
        """

        joint_list = self.matching_chain(attach_skeleton_root)
        if len(joint_list) < ik_chain.VALID_CHAIN_LENGTHS[0]:
            logger.warning('%s needs at least %s joints marked up as %s %s to be driven by, and '
                           'found %s.', self.pynode, ik_chain.VALID_CHAIN_LENGTHS[0], self.side,
                           self.region, len(joint_list))
            return []

        constraint_list = []
        end_constraint = constraint.parent_constraint_safe(joint_list[-1], self.ik_flag, mo=mo)
        if end_constraint:
            constraint_list.append(end_constraint)

        pv_constraint = keyable_component.constrain_to_pole_vector(joint_list[:3], self.pv_flag,
                                                                  mo=mo)
        if pv_constraint:
            constraint_list.append(pv_constraint)
        return constraint_list
