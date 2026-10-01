"""
The component an arm or a leg is made of: an FK chain and an IK chain over the same joints, and one
attribute that fades between them.

Both chains are duplicates of the bind chain. The bind joints are driven by a pair of weighted
constraints - one target on the FK chain, one on the IK chain - and a single switch attribute drives
both weights through a ``setRange`` node that reads it two ways at once, straight and inverted. The
same two readings drive the controls' visibility, so an animator sees the system that is in control
and not the one that is not.

This is the first component ported that has ever had more than one version, which makes it the first
test of the update path: a rig built by the version that stored its build attributes in snake_case
is brought up to the camelCase names by :meth:`IKFKComponent._update_version_1_to_version_2`. That
method has existed for as long as the class has had two versions and had never once run - the
version number is stored on a double attribute, so the method name ``FRAGNode.update`` built from it
read ``_update_version_1.0_to_version_2.0``. ``frag_base`` rounds now, so the step is reachable.

What was wrong before:

- **Building the component wiped the Maya joint labels off the end bind joint.** Three lines copied
  ``side``, ``type`` and ``otherType`` from the IK offset control onto the end joint, and a control
  built by ``Flag.create`` carries the defaults for all three - so the joint came out labelled
  *centre / none*, whatever it had been. ``JointMarkup.side`` falls back to the Maya joint label
  when a joint carries no ``skelSide`` markup, which is what an imported skeleton is, so this
  changed the side the pipeline reads off that joint. Gone, as in ``ik_component``. Three more lines
  copied the same three attributes from the IK control onto the pole vector control, which is one
  set of defaults onto another: a no-op, and gone with them.
- **The chain-length guard said three and accepted four**, and named neither the joints nor the
  count. It is ``ik_chain``'s rule, so it is ``ik_chain``'s constant, and it is asked before
  anything is built rather than after the component's node and groups are in the scene.
- **``get_flags`` could hand back a list with None in it.** It appends six attribute reads and then
  wraps every one of them in ``Flag``, so a component missing any of its controls - one half-built,
  one a tool has taken a control off - raised from inside the wrapper rather than saying what was
  missing. The empty reads are dropped and reported.
- **``attach_to_skeleton`` raised on a short chain**, in two ways: ``joint_list[2]`` and
  ``joint_list[1]`` are read without asking how long the chain is, and
  ``ik_utils.create_pole_vector_locator`` answers None for a chain of fewer than three joints, which
  the next line calls ``setParent`` on. Both the lookup and the pole vector are the shared helpers
  in ``keyable_component`` now, which ask.
- **A rebuilt component drew default-sized controls**: ``scale`` was never written down with the
  other build arguments.
- ``fk_flags[1]`` - the elbow or the knee - had two rotate axes locked off by index, with nothing
  saying why. It is the middle control of the three the IK solves over, a hinge, and it is named and
  guarded rather than indexed blind.
- The FK controls were read out of the result twice under two names, the duplicated chain was
  parented into the no-touch group twice, and the first control's align group was read as a raw
  attribute - which a control built without one does not have.
- The order of a constraint's weight aliases was relied on with nothing said about it. It follows
  the order the targets were added, which is the order of the call two lines above; that is now
  written down where the connection is made.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import fk_chain
from mca.mya.rigging import ik_chain
from mca.mya.rigging import ikfk_switch
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The suffixes the two duplicated chains carry.
FK_CHAIN_SUFFIX = 'fk_chain'
IK_CHAIN_SUFFIX = 'ik_chain'

#: What the component keeps its pieces on.
FK_FLAGS_ATTR = 'fkFlags'
FK_FLAG_OFFSET_ATTR = 'fkFlagOffset'
FK_CHAIN_ATTR = 'fkChain'
IK_FLAG_ATTR = 'ikFlag'
IK_FLAG_OFFSET_ATTR = 'ikFlagOffset'
PV_FLAG_ATTR = 'pvFlag'
PV_LINE_ATTR = 'pvLine'
IK_HANDLE_ATTR = 'ikHandle'
IK_SOLVER_ATTR = 'ikSolver'
IK_CHAIN_ATTR = 'ikChain'
SWITCH_FLAG_ATTR = 'switchFlag'
SWITCH_ATTR_NAME_ATTR = 'switchAttrName'
INVERT_NODE_ATTR = 'invertNode'
START_JOINT_ATTR = 'startJoint'
END_JOINT_ATTR = 'endJoint'
LINE_CLUSTERS_ATTR = 'lineClusters'
UNIT_CONV_NODES_ATTR = 'unitConvNodes'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: What an animator is not allowed to do to each control.
FK_ROOT_LOCKED_ATTRS = ('sx', 'sy', 'sz')
IK_FLAG_LOCKED_ATTRS = ('sx', 'sy', 'sz', 'v')
OFFSET_FLAG_LOCKED_ATTRS = ('tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'v')
PV_FLAG_LOCKED_ATTRS = ('rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v')
SWITCH_FLAG_LOCKED_ATTRS = ('tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'radius', 'v')

#: The elbow or the knee: the middle one of the three joints the IK solves over. It is a hinge, so
#: its FK control bends on one axis and the other two are taken away.
HINGE_FLAG_INDEX = 1
HINGE_LOCKED_ATTRS = ('rx', 'ry')


class IKFKComponent(keyable_component.KeyableComponent):
    """
    One limb with both an FK and an IK setup over it, and a switch to fade between them.
    """

    VERSION = 2

    #: What version 1 stored these attributes under, before the pipeline settled on camelCase.
    LEGACY_ATTR_NAMES = {'ik_handle': IK_HANDLE_ATTR,
                         'invert_node': INVERT_NODE_ATTR,
                         'start_joint': START_JOINT_ATTR,
                         'end_joint': END_JOINT_ATTR}

    def _update_version_1_to_version_2(self):
        """
        Bring a version 1 component up to version 2 by renaming its four snake_case attributes.

        ``rename_legacy_attrs`` renames rather than rewires, so whatever was connected to each
        attribute stays connected to it.
        """

        self.rename_legacy_attrs(self.LEGACY_ATTR_NAMES)
        self.set_version(2)

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent,
               start_joint,
               end_joint,
               side,
               region,
               scale=1.0,
               ik_flag_orient=None,
               ik_flag_pv_orient=None,
               ik_flag_rotate_order=None,
               lock_child_rotate_axes=(),
               lock_child_translate_axes=attr_utils.TRANSLATION_ATTRS,
               lock_root_translate_axes=attr_utils.TRANSLATION_ATTRS,
               **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The first bind joint.
        :param pm.nt.Joint end_joint: The last one.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param float scale: How big to draw the controls.
        :param list(float) ik_flag_orient: A rotation to put on the IK control as it is built.
        :param list(float) ik_flag_pv_orient: A rotation to put on the pole vector control.
        :param str ik_flag_rotate_order: A rotate order for the IK control, by name.
        :param lock_child_rotate_axes: Rotate channels to lock on every FK control but the first.
        :param lock_child_translate_axes: Translate channels to lock on every FK control but the
            first.
        :param lock_root_translate_axes: Translate channels to lock on the first FK control.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: IKFKComponent
        :raises RuntimeError: When the run of joints is not a length a rotate-plane IK can be built
            on.
        """

        chain_between = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
        # Asked before anything is built, and by ik_chain's own rule rather than a second copy.
        if len(chain_between) not in ik_chain.VALID_CHAIN_LENGTHS:
            raise RuntimeError(
                'An IKFK component is built on {0} joints. {1} to {2} is {3} joints long.'.format(
                    ' or '.join(str(length) for length in ik_chain.VALID_CHAIN_LENGTHS),
                    start_joint, end_joint, len(chain_between)))

        build_kwargs = {'scale': scale,
                        'ik_flag_orient': ik_flag_orient,
                        'ik_flag_pv_orient': ik_flag_pv_orient,
                        'ik_flag_rotate_order': ik_flag_rotate_order,
                        'lock_child_rotate_axes': lock_child_rotate_axes,
                        'lock_child_translate_axes': lock_child_translate_axes,
                        'lock_root_translate_axes': lock_root_translate_axes}

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        # set_namespace rather than pm.namespace(set=...): a bare relative name is resolved
        # against whatever namespace is active, so building this while the active namespace was
        # already the rig's raised 'No namespace matches name'. set_namespace goes to the root
        # first.
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        IKFKComponent.__name__,
                                                        IKFKComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        flag_grp = node.flag_group
        nt_grp = node.no_touch_grp

        # ------------------------------------------------------------------------------- #
        # the FK half
        # ------------------------------------------------------------------------------- #
        chain_fk = joint_utils.duplicate_chain(start_joint, end_joint, suffix=FK_CHAIN_SUFFIX)
        chain_fk[0].setParent(nt_grp)
        fk_built = fk_chain.fk_joint_chain(chain_fk[0],
                                           chain_fk[-1],
                                           scale=scale,
                                           children_align_transforms=True,
                                           create_end_flag=True,
                                           offset_flag=True,
                                           suffix=FK_CHAIN_SUFFIX)

        fk_flags = fk_built['flags']
        fk_flag_offset = fk_built['offset_flag']

        root_locked_attrs = list(FK_ROOT_LOCKED_ATTRS) + list(lock_root_translate_axes)
        child_locked_attrs = (list(FK_ROOT_LOCKED_ATTRS) + list(lock_child_rotate_axes)
                              + list(lock_child_translate_axes))
        for index, fk_flag in enumerate(fk_flags):
            # Visibility is driven by the switch below, so it is taken off the animator before the
            # connection is made rather than locked after it.
            fk_flag.node.visibility.set(keyable=False, channelBox=False)
            fk_flag.lock_and_hide_attrs(root_locked_attrs if not index else child_locked_attrs)

        if len(fk_flags) > HINGE_FLAG_INDEX:
            fk_flags[HINGE_FLAG_INDEX].lock_and_hide_attrs(list(HINGE_LOCKED_ATTRS))

        fk_root_align = fk_flags[0].get_align_transform()
        (fk_root_align or fk_flags[0]).setParent(flag_grp)

        # ------------------------------------------------------------------------------- #
        # the IK half
        # ------------------------------------------------------------------------------- #
        chain_ik = joint_utils.duplicate_chain(start_joint, end_joint, suffix=IK_CHAIN_SUFFIX)
        chain_ik[0].setParent(nt_grp)
        ik_built = ik_chain.ik_joint_chain(chain_ik[0],
                                           chain_ik[-1],
                                           side=side,
                                           region=region,
                                           scale=scale,
                                           ik_flag_orient=ik_flag_orient,
                                           ik_flag_pv_orient=ik_flag_pv_orient,
                                           ik_flag_rotate_order=ik_flag_rotate_order)

        ik_align_group = ik_built['ik_zero']
        ik_align_group.visibility.set(0)
        ik_flag = ik_built['ik_flag']
        ik_flag_offset = ik_built['ik_flag_offset']
        pv_flag = ik_built['pv_flag']
        pv_line = ik_built['pv_line']

        # The guide line is shown and hidden with the control it points at.
        pv_flag.node.visibility >> pv_line.visibility
        pv_flag.node.overrideVisibility >> pv_line.overrideVisibility
        pv_flag.node.overrideEnabled >> pv_line.overrideEnabled

        # ------------------------------------------------------------------------------- #
        # the switch
        # ------------------------------------------------------------------------------- #
        # On the last joint the IK solves over: the wrist of an arm, the ankle of a leg. A
        # four-joint chain has a joint past the end of the IK, so the switch goes one back.
        switch_joint = chain_between[2]

        switch_built = ikfk_switch.ikfk_switch(switch_joint, side, region, scale=scale)
        invert_node = switch_built['invert_node']
        switch_flag = switch_built['flag']
        switch_attr_name = switch_built['name']

        # One reading of the switch shows the IK controls, the other shows the FK ones, so exactly
        # one set is ever on screen.
        for flag_node in (ik_flag, ik_flag_offset, pv_flag):
            invert_node.straight >> flag_node.node.visibility
        for flag_node in list(fk_flags) + [fk_flag_offset]:
            invert_node.inverse >> flag_node.node.visibility
            flag_node.node.visibility.lock()

        # Locked last, after the visibility connections are made. A locked plug cannot be connected
        # to, and every one of these control locks takes visibility away - so locking as each half
        # was built, which is the order this file used to read in, made the wiring above raise.
        ik_flag.lock_and_hide_attrs(list(IK_FLAG_LOCKED_ATTRS))
        ik_flag_offset.lock_and_hide_attrs(list(OFFSET_FLAG_LOCKED_ATTRS))
        pv_flag.lock_and_hide_attrs(list(PV_FLAG_LOCKED_ATTRS))
        fk_flag_offset.lock_and_hide_attrs(list(OFFSET_FLAG_LOCKED_ATTRS))
        switch_flag.lock_and_hide_attrs(list(SWITCH_FLAG_LOCKED_ATTRS))

        # ------------------------------------------------------------------------------- #
        # putting it together
        # ------------------------------------------------------------------------------- #
        pm.parent([pv_line, ik_align_group], nt_grp)
        pm.parent([ik_flag.get_align_transform(), pv_flag.get_align_transform(),
                   switch_flag.get_align_transform()], flag_grp)

        # Both driver chains are hidden and the group holding them is not, so that the pole vector
        # line - which lives in the same group - can still be seen.
        chain_fk[0].visibility.set(0)
        chain_ik[0].visibility.set(0)
        nt_grp.visibility.unlock()
        nt_grp.visibility.set(1)
        nt_grp.visibility.lock()

        node.connect_nodes(fk_flags, FK_FLAGS_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(fk_flag_offset, FK_FLAG_OFFSET_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(chain_fk, FK_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(ik_flag, IK_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(ik_flag_offset, IK_FLAG_OFFSET_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(pv_flag, PV_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(pv_line, PV_LINE_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(ik_built['ik_handle'], IK_HANDLE_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(ik_built['ik_solver'], IK_SOLVER_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(chain_ik, IK_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(ik_built['line_clusters'], LINE_CLUSTERS_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(ik_built['unit_conv_nodes'], UNIT_CONV_NODES_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_node(switch_flag, SWITCH_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(invert_node, INVERT_NODE_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(start_joint, START_JOINT_ATTR)
        node.connect_node(end_joint, END_JOINT_ATTR)
        node.connect_nodes(chain_between, BIND_JOINTS_ATTR)
        attr_utils.set_attribute(node.pynode, {SWITCH_ATTR_NAME_ATTR: switch_attr_name})

        # ------------------------------------------------------------------------------- #
        # the blend
        # ------------------------------------------------------------------------------- #
        for fk_joint, ik_joint, bind_joint in zip(chain_fk, chain_ik, chain_between):
            orient_constraint = pm.orientConstraint(fk_joint, ik_joint, bind_joint, w=1, mo=0)
            point_constraint = pm.pointConstraint(fk_joint, ik_joint, bind_joint, w=1, mo=1)
            for constraint_node in (orient_constraint, point_constraint):
                # A constraint's weight aliases come back in the order its targets were added, and
                # the two calls above add the FK joint first - so of the pair just added, the first
                # is the FK weight and the second the IK weight. The last two rather than aliases 0
                # and 1: a joint that already had a constraint on it hands back the same node with
                # the new targets appended, and the version before would have rewired whatever was
                # there first instead.
                fk_weight, ik_weight = constraint_node.getWeightAliasList()[-2:]
                invert_node.inverse >> fk_weight
                invert_node.straight >> ik_weight

        return node

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        Every control this component owns: the FK chain, its offset control, the IK control, its
        offset, the pole vector and the switch.

        :return: The controls. A control the component has lost - an attribute reading back empty -
            is left out and reported, rather than being wrapped and raising from inside the wrapper.
        :rtype: list(frag_flag.Flag)
        """

        flag_nodes = list(self.pynode.attr(FK_FLAGS_ATTR).listConnections())
        for attr_name in (IK_FLAG_ATTR, IK_FLAG_OFFSET_ATTR, FK_FLAG_OFFSET_ATTR, PV_FLAG_ATTR,
                          SWITCH_FLAG_ATTR):
            flag_node = self.pynode.attr(attr_name).get()
            if flag_node is None:
                logger.warning('%s has nothing wired to %s, so that control is missing from its '
                               'flag list.', self.pynode, attr_name)
                continue
            if flag_node not in flag_nodes:
                flag_nodes.append(flag_node)
        return [frag_flag.Flag(flag_node) for flag_node in flag_nodes]

    @property
    def fk_flags(self):
        """
        :return: The FK controls, root first.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(node) for node
                in self.pynode.attr(FK_FLAGS_ATTR).listConnections()]

    @property
    def ik_flags(self):
        """
        :return: The IK control, its offset control and the pole vector control.
        :rtype: list(frag_flag.Flag)
        """

        return [self.ik_flag, self.ik_flag_offset, self.pv_flag]

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
    def fk_flag_offset(self):
        """
        :return: The detail control under the last FK control.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(FK_FLAG_OFFSET_ATTR).get())

    @property
    def pv_flag(self):
        """
        :return: The control that says which way the middle of the limb bends.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(PV_FLAG_ATTR).get())

    @property
    def switch_flag(self):
        """
        :return: The control carrying the attribute that fades between the two systems.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(SWITCH_FLAG_ATTR).get())

    @property
    def switch_attr_name(self):
        """
        :return: The name of the attribute on the switch control that fades between the two systems.
        :rtype: str
        """

        return self.pynode.attr(SWITCH_ATTR_NAME_ATTR).get()

    # ----------------------------------------------------------------------------------- #
    # being driven by a skeleton
    # ----------------------------------------------------------------------------------- #
    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive both halves of this component from a skeleton, so animation on the skeleton reaches
        the rig whichever system is switched on.

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

        fk_flag_list = self.fk_flags
        if len(fk_flag_list) > len(joint_list):
            logger.warning('%s has %s FK controls and %s %s on the skeleton has only %s joints, so '
                           'the last %s are not driven.', self.pynode, len(fk_flag_list), self.side,
                           self.region, len(joint_list), len(fk_flag_list) - len(joint_list))
        for flag_node, joint_node in zip(fk_flag_list, joint_list):
            constraint_node = constraint.parent_constraint_safe(joint_node, flag_node, mo=mo)
            if constraint_node:
                constraint_list.append(constraint_node)

        # The third joint is the end of what the IK solves over, whether or not there is a fourth.
        end_constraint = constraint.parent_constraint_safe(joint_list[2], self.ik_flag, mo=mo)
        if end_constraint:
            constraint_list.append(end_constraint)

        pv_constraint = keyable_component.constrain_to_pole_vector(joint_list[:3], self.pv_flag,
                                                                  mo=mo)
        if pv_constraint:
            constraint_list.append(pv_constraint)
        return constraint_list
