"""

A spine, a neck, a tail: a chain whose middle takes its twist from both ends.

An FK chain makes the animator pose every joint. A reverse FK chain gives them two controls - one
at each end - and works out the middle: each middle joint takes a share of both ends' rotation,
weighted by how far along it is, so turning the chest carries the spine with it. Each middle joint
still has a control of its own on top of that, for the pose the distribution does not give.

``rfk_chain`` builds the system. This component records it, and :class:`ReverseChainComponent` -
the base class here - holds everything that is the same between it and the stretchy variant in
``rfk_stretch_component``, which used to be a hundred and thirty lines of copy.

What was wrong before:

- **``attach_to_skeleton`` required the control count and the joint count to match exactly**, and
  attached nothing at all, silently, when they did not: ``if len(flag_list) == len(joint_list)``. A
  five-control spine driven from a six-joint markup chain - one extra joint on the other skeleton,
  a head counted into the region - came back with an empty list and no complaint. This is the
  strictest of the three spellings of this bug found in ``frag``; the controls and joints are
  paired as far as the shorter of the two goes now, and the mismatch is reported.
- **A chain too short to be a reverse FK chain was a ``KeyError``.** ``rfk_chain`` answers ``{}``
  for fewer than three joints, with a warning saying why, and the next line is
  ``chain_dict['mid_flags']``. The component, its two groups and a duplicated chain were already in
  the scene by then. The length is asked for before anything is built.
- **``sub_flags`` answered None when there were none**, and answered raw nodes rather than ``Flag``
  objects - the only flag property on the class that did either. Both were in its docstring, which
  is how a caller ends up writing ``or []`` around a list.
- **``get_flags`` wrapped every attribute read in ``Flag``** with nothing asking whether the
  attributes were still wired, so a component that had lost a control raised from inside the
  wrapper.
- **``mid_flags`` sorted the controls by name.** The attribute holds them in the order they were
  built, which is the order along the chain; sorting by name gives the same answer only while the
  skeleton's joints are numbered with a leading zero. It reads them in the order they are stored.
- ``RFKStretchComponent`` was a copy of this class with a stretch layer added: ``get_flags``,
  ``start_flag``, ``end_flag``, ``mid_flags``, ``sub_flags``, ``mid_groups``, ``mid_offset_groups``
  and ``attach_to_skeleton`` were character for character the same in both, and so was the block
  that wires everything up. All of it is on :class:`ReverseChainComponent`. The two stay separate
  classes rather than one inheriting from the other, because ``cinematics/shot_utils.py`` asks a
  rig for its children ``of_type=RFKComponent`` and a stretchy spine is not one of those.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import joint_utils
from mca.mya.rigging import rfk_chain
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The suffix the duplicated chain the controls drive carries.
RFK_CHAIN_SUFFIX = 'rfk_chain'

#: What a reverse chain component keeps its pieces on.
RFK_CHAIN_ATTR = 'rfkChain'
BOTTOM_FLAG_ATTR = 'bottomFlag'
TOP_FLAG_ATTR = 'topFlag'
MID_FLAGS_ATTR = 'midFlags'
SUB_FLAGS_ATTR = 'subFlags'
MID_GROUPS_ATTR = 'midGroups'
MID_OFFSET_GROUPS_ATTR = 'midOffsetGroups'
REVERSE_NODES_ATTR = 'reverseNodes'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: What an animator is not allowed to do to a chain control. They turn; where the chain is and how
#: long it is comes from the chain itself.
LOCKED_FLAG_ATTRS = ('tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'v')


class ReverseChainComponent(keyable_component.KeyableComponent):
    """
    What a reverse FK chain component is, whether or not it stretches.

    Two end controls, a control per middle joint, optional detail controls at the ends, and the
    groups and nodes that distribute the ends' rotation down the chain. Everything here is reading:
    the building is each subclass's own, because the two build different chains.
    """

    VERSION = 1

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        Every control this component owns, in the order they sit along the chain: the bottom, the
        middles, the top, then any detail controls.

        :return: The controls. One the component has lost - an attribute reading back empty - is
            left out and reported, rather than wrapped and raising from inside the wrapper.
        :rtype: list(frag_flag.Flag)
        """

        flag_nodes = []
        bottom = self.pynode.attr(BOTTOM_FLAG_ATTR).get()
        if bottom is None:
            logger.warning('%s has nothing wired to %s.', self.pynode, BOTTOM_FLAG_ATTR)
        else:
            flag_nodes.append(bottom)

        flag_nodes += self.pynode.attr(MID_FLAGS_ATTR).listConnections()

        top = self.pynode.attr(TOP_FLAG_ATTR).get()
        if top is None:
            logger.warning('%s has nothing wired to %s.', self.pynode, TOP_FLAG_ATTR)
        else:
            flag_nodes.append(top)

        if self.pynode.hasAttr(SUB_FLAGS_ATTR):
            flag_nodes += self.pynode.attr(SUB_FLAGS_ATTR).listConnections()

        return [frag_flag.Flag(flag_node) for flag_node in flag_nodes]

    @property
    def primary_flags(self):
        """
        :return: The controls that line up one for one with the chain's joints: the bottom, the
            middles, then the top. The detail controls are not among them.
        :rtype: list(frag_flag.Flag)
        """

        return [self.start_flag] + self.mid_flags + [self.end_flag]

    @property
    def start_flag(self):
        """
        :return: The control at the bottom of the chain.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(BOTTOM_FLAG_ATTR).get())

    @property
    def end_flag(self):
        """
        :return: The control at the top of the chain.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(TOP_FLAG_ATTR).get())

    @property
    def mid_flags(self):
        """
        :return: The controls on the middle joints, in the order they sit along the chain - which is
            the order the attribute holds them in. The version before sorted them by name, which is
            the same order only while the joints are numbered with a leading zero.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(node) for node
                in self.pynode.attr(MID_FLAGS_ATTR).listConnections()]

    @property
    def sub_flags(self):
        """
        :return: The detail controls at the ends of the chain, as ``Flag`` objects, and an empty
            list when the component was built without them. The version before answered None, and
            raw nodes rather than ``Flag`` objects - the only flag property on the class that did
            either.
        :rtype: list(frag_flag.Flag)
        """

        if not self.pynode.hasAttr(SUB_FLAGS_ATTR):
            return []
        return [frag_flag.Flag(node) for node
                in self.pynode.attr(SUB_FLAGS_ATTR).listConnections()]

    # ----------------------------------------------------------------------------------- #
    # the system underneath
    # ----------------------------------------------------------------------------------- #
    @property
    def rfk_chain(self):
        """
        :return: The duplicated chain the controls drive, root first.
        :rtype: list(pm.nt.Joint)
        """

        return self.pynode.attr(RFK_CHAIN_ATTR).get() or []

    @property
    def mid_groups(self):
        """
        :return: The groups that carry each middle joint's share of the two ends' rotation.
        :rtype: list(pm.nt.Transform)
        """

        return self.pynode.attr(MID_GROUPS_ATTR).get() or []

    @property
    def mid_offset_groups(self):
        """
        :return: The groups above the middle controls that hold the difference between where the
            distribution points and where the joint actually sits.
        :rtype: list(pm.nt.Transform)
        """

        return self.pynode.attr(MID_OFFSET_GROUPS_ATTR).get() or []

    # ----------------------------------------------------------------------------------- #
    # being driven by a skeleton
    # ----------------------------------------------------------------------------------- #
    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's controls from a skeleton.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep each control where it is rather than snapping it to its joint.
        :return: The constraints built.
        :rtype: list
        """

        joint_list = self.matching_chain(attach_skeleton_root)
        if not joint_list:
            return []

        flag_list = self.primary_flags
        if len(flag_list) != len(joint_list):
            # The version before required these to be equal and attached nothing at all, silently,
            # when they were not.
            logger.warning('%s has %s controls along the chain and %s %s on the skeleton has %s '
                           'joints, so the shorter of the two is what gets driven.', self.pynode,
                           len(flag_list), self.side, self.region, len(joint_list))

        constraint_list = []
        for flag_node, joint_node in zip(flag_list, joint_list):
            constraint_node = constraint.parent_constraint_safe(joint_node, flag_node, mo=mo)
            if constraint_node:
                constraint_list.append(constraint_node)
        return constraint_list

    # ----------------------------------------------------------------------------------- #
    # what both subclasses do once the chain is built
    # ----------------------------------------------------------------------------------- #
    def connect_chain(self, built, duplicate_chain, bind_joints):
        """
        Wire up everything ``rfk_chain`` and ``rfk_stretch_chain`` both answer, parent the groups
        into this component's own, and constrain the bind joints to the duplicate.

        This was written out twice, character for character.

        :param dict built: What the chain builder answered.
        :param list(pm.nt.Joint) duplicate_chain: The chain the controls drive.
        :param list(pm.nt.Joint) bind_joints: The joints that follow it.
        """

        duplicate_chain[0].setParent(self.no_touch_grp)
        for group in built['mid_groups']:
            group.setParent(self.no_touch_grp)
        for group in built['flags_groups']:
            group.setParent(self.flag_group)

        self.connect_nodes(duplicate_chain, RFK_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['start_twist_flag'], BOTTOM_FLAG_ATTR,
                          frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['end_twist_flag'], TOP_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(built['mid_flags'], MID_FLAGS_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(built['mid_groups'], MID_GROUPS_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(built['mid_offset_groups'], MID_OFFSET_GROUPS_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(built['reverse_nodes'], REVERSE_NODES_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(bind_joints, BIND_JOINTS_ATTR)
        if built['sub_flags']:
            self.connect_nodes(built['sub_flags'], SUB_FLAGS_ATTR, frag_base.FRAG_PARENT_ATTR)

        for bind_joint, chain_joint in zip(bind_joints, duplicate_chain):
            pm.parentConstraint(chain_joint, bind_joint, w=True, mo=True)


class RFKComponent(ReverseChainComponent):
    """
    A reverse FK chain: two end controls, a control per middle joint, and no stretch.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, end_joint, side, region, scale=1.0, create_sub_flags=True,
               **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The first bind joint.
        :param pm.nt.Joint end_joint: The last one.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param float scale: How big to draw the controls.
        :param bool create_sub_flags: Build a smaller detail control under each end control.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: RFKComponent
        :raises RuntimeError: When the run of joints is too short to distribute anything along. The
            version before got as far as building the component, its groups and a duplicated chain,
            and then raised ``KeyError`` on the empty result.
        """

        bind_joints = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
        if len(bind_joints) < rfk_chain.MINIMUM_JOINTS:
            raise RuntimeError(
                'A reverse FK chain needs at least {0} joints - two ends and something between '
                'them to distribute to. {1} to {2} is {3} joints long.'.format(
                    rfk_chain.MINIMUM_JOINTS, start_joint, end_joint, len(bind_joints)))

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        RFKComponent.__name__,
                                                        version=RFKComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(
            node.pynode, frag_base.BUILD_KWARGS_ATTR,
            {'scale': scale, 'create_sub_flags': create_sub_flags})

        duplicate_chain = joint_utils.duplicate_chain(start_joint, end_joint,
                                                      suffix=RFK_CHAIN_SUFFIX)
        built = rfk_chain.rfk_chain(start_joint=duplicate_chain[0], end_joint=duplicate_chain[-1],
                                    scale=scale, side=side, region=region,
                                    create_sub_flags=create_sub_flags, suffix=RFK_CHAIN_SUFFIX)

        component = RFKComponent(node.pynode)
        component.connect_chain(built, duplicate_chain, bind_joints)

        for flag_node in component.get_flags():
            flag_node.lock_and_hide_attrs(list(LOCKED_FLAG_ATTRS))

        return component
