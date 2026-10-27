"""
FRAG component that builds a quadruped "Z" leg (hip, knee, ankle, foot, toe) with IK/FK switching.

The bind chain is duplicated three times under the component's NO_TOUCH group: an ``ik`` chain driven by an RP
solver on the upper leg and an SC solver on the lower leg, a ``drv`` chain driven by a spring solver that carries the
overall leg pose and the foot lift, and an ``fk`` chain with plain FK flags. A reverse foot built from the skeleton's
``_toe`` / ``_ball`` / ``_heel`` / ``_interior`` / ``_exterior`` contact joints drives the IK foot and an ikfk_switch
flag blends the bind chain between IK and FK.
"""

import pymel.core as pm

from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup, fk_chain, ik_utils, ikfk_switch, joint_utils, reverse_foot_rig, rig_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils, constraint, dag

logger = log.MCA_LOGGER


class ZLegComponent(keyable_component.KeyableComponent):
    """
    Keyable component holding a quadruped Z leg with IK/FK switching.

    On top of the KeyableComponent groups it adds the ``ikChain`` / ``fkChain`` joint links, the ``ikFlag``,
    ``ikFlagOffset``, ``pvFlag``, ``ikToeFlag``, ``switchFlag`` and ``fkFlags`` flag links, the ``pvLine``,
    ``ikSolver``, ``clamp``, ``invertNode`` and ``unitConvNodes`` support node links and the ``switchAttrName``
    string attribute. Build arguments are stored in ``buildKwargs``.
    """

    VERSION = 1

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
               **kwargs):
        """
        Creates a z leg component.

        :param FRAGNode frag_parent: FRAG Rig FRAGNode.
        :param pm.nt.Joint start_joint: Start joint of the chain.
        :param pm.nt.Joint end_joint: End joint of the chain.
        :param str side: The side in which the component is on the body.
        :param str region: The name of the region.  EX: "Arm"
        :param float scale: Scale value for flag creation.
        :param list[float, float, float] ik_flag_orient: XYZ rotation offset applied to the IK flag shapes.
        :param list[float, float, float] ik_flag_pv_orient: XYZ rotation offset applied to the pole vector flag shape.
        :param str ik_flag_rotate_order: Change IK object's rotate order, default is xyz
        :param dict kwargs: Unused extra build arguments accepted so templates can pass a shared kwargs dict.
        :return: Returns an instance of ZLegComponent, or None if the chain is shorter than four joints.
        :rtype: ZLegComponent
        """

        # Serialize build kwargs for later reconstruction.
        kwargs_dict = {}
        kwargs_dict['scale'] = scale
        kwargs_dict['ik_flag_orient'] = ik_flag_orient
        kwargs_dict['ik_flag_pv_orient'] = ik_flag_pv_orient
        kwargs_dict['ik_flag_rotate_order'] = ik_flag_rotate_order

        # Set Namespace
        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set=f'{root_namespace}:')

        leg_chain = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)

        skel_hierarchy = chain_markup.ChainMarkup(start_joint)

        if len(leg_chain) < 4:
            logger.warning('Joint chain is insufficient length.')
            return

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                         ZLegComponent.__name__,
                                                         ZLegComponent.VERSION,
                                                         side=side,
                                                         region=region,
                                                         align_component=start_joint)

        # Store serialized kwargs onto network node for rig serialization.
        attr_utils.set_compound_attribute_groups(node.pynode, 'buildKwargs', kwargs_dict)

        # Get local level groups
        flag_grp = node.pynode.flagGroup.get()
        nt_grp = node.pynode.noTouch.get()
        nt_grp.v.unlock()
        nt_grp.v.set(True)

        # The offset group is only positioned to the leg's parent joint. Orient constraining it to the NO_TOUCH
        # parent as well made the leg behave oddly, so it is intentionally left unconstrained.
        skel_offset_grp = pm.group(n=f'{region}_{side}_joint_offset', em=True, w=True)
        skel_offset_grp.v.set(False)
        skel_offset_grp.setParent(nt_grp)
        pm.delete(constraint.parent_constraint_safe(leg_chain[0].getParent(), skel_offset_grp))

        # --- IK setup ----------------------------------------------------------------------
        ik_chain = joint_utils.duplicate_chain(leg_chain[0], leg_chain[-1], suffix='ik')
        ik_chain[0].setParent(skel_offset_grp)
        ik_drv_chain = joint_utils.duplicate_chain(leg_chain[0], leg_chain[-1], suffix='drv')
        ik_drv_chain[0].setParent(skel_offset_grp)

        # Collect rev foot contact joints.
        toe_contact_joint = skel_hierarchy.get_start(f'{region}_toe', side)
        ball_contact_joint = skel_hierarchy.get_start(f'{region}_ball', side)
        heel_contact_joint = skel_hierarchy.get_start(f'{region}_heel', side)
        interior_lean_joint = skel_hierarchy.get_start(f'{region}_interior', side)
        exterior_lean_joint = skel_hierarchy.get_start(f'{region}_exterior', side)

        # ik system flags
        ik_flag = frag_flag.Flag.create(ik_chain[3],
                                        label=f'{region}_{side}',
                                        orientation=ik_flag_orient,
                                        scale=scale)
        ik_flag.lock_and_hide_attrs(attr_utils.SCALE_ATTRS)
        ik_flag_alignment_grp = ik_flag.get_align_transform()
        ik_flag_alignment_grp.setParent(flag_grp)

        # The offset flag is drawn slightly smaller so it sits visibly inside the main IK flag.
        ik_offset_flag = frag_flag.Flag.create(ik_chain[3],
                                               label=f'{region}_{side}_offset',
                                               orientation=ik_flag_orient,
                                               scale=scale * 0.85)
        ik_offset_flag.lock_and_hide_attrs(['v'] + attr_utils.TRANSLATION_ATTRS + attr_utils.SCALE_ATTRS)
        ik_offset_flag.set_as_detail()
        ik_offset_flag_alignment_grp = ik_offset_flag.get_align_transform()
        ik_offset_flag_alignment_grp.setParent(ik_flag)

        # Maya rotateOrder enum values keyed by their axis order name.
        orient_str_val = {'xyz': 0, 'yzx': 1, 'zxy': 2, 'xzy': 3, 'yxz': 4, 'zyx': 5}

        if ik_flag_rotate_order:
            # Changing the rotate order would re-interpret the flag's existing rotation, so the orientation is
            # captured on a locator and re-applied after the swap.
            temp_loc = rig_utils.create_locator_at_object(ik_flag)
            ik_flag.rotateOrder.set(orient_str_val[ik_flag_rotate_order])
            pm.delete(constraint.orient_constraint_safe(temp_loc, ik_flag, w=True, mo=False))
            pm.delete(temp_loc)

        # build reverse foot.
        chain_rev_foot_result = reverse_foot_rig.reverse_foot_chain(ik_chain[3],
                                                                    ik_chain[-1],
                                                                    contact_joints=[toe_contact_joint,
                                                                                    ball_contact_joint,
                                                                                    exterior_lean_joint,
                                                                                    interior_lean_joint,
                                                                                    heel_contact_joint],
                                                                    side=side,
                                                                    region=region,
                                                                    ik_foot_flag=ik_flag,
                                                                    scale=scale)
        unit_conv_nodes = chain_rev_foot_result['unit_conv_nodes']
        rev_foot_chain = chain_rev_foot_result['chain']
        pm.parent(rev_foot_chain[0], nt_grp)

        rev_foot_chain = chain_rev_foot_result['reverse_chain']
        contact_alignment_grp = chain_rev_foot_result['reverse_foot_grp']
        contact_alignment_grp.v.set(False)
        contact_alignment_grp.setParent(nt_grp)

        ik_toe_flag = chain_rev_foot_result['ik_toe_flag']
        ik_toe_flag_alignment_grp = ik_toe_flag.get_align_transform()
        ik_toe_flag_alignment_grp.setParent(flag_grp)

        pm.delete(chain_rev_foot_result['alignment_constraint'])
        constraint.parent_constraint_safe(ik_offset_flag, contact_alignment_grp, mo=True)

        # add a new foot lift joint that hangs out with the driver chain and use it to drive our lift.
        foot_lift_joint = joint_utils.duplicate_joint(ik_drv_chain[2], f'{region}_{side}_foot_lift')
        foot_lift_joint.setParent(ik_drv_chain[3])
        foot_lift_joint.t.set([0, 0, 0])

        # Set up the aim constraint by finding the primary axis and offsetting the aim by one axis.
        # This means if X is the aim axis Y will be the up axis.
        primary_axis, axis_is_positive = rig_utils.find_primary_axis(ik_chain[2])
        ik_flag.addAttr('ankleLift', k=True, at='double')
        # Rotate about the axis preceding the primary one ("xyz" wraps, so a Z primary axis lifts on Y).
        ik_flag.ankleLift >> foot_lift_joint.attr(f'r{"xyz"["XYZ".index(primary_axis) - 1]}')

        # Pole Vector position
        pv_point = ik_utils.get_pole_vector_position(ik_chain[:3])

        # Find pv point before ik, in case joints move
        pv_locator = pm.spaceLocator(n=f'{region}_{side}_pv_loc')
        pv_locator.t.set(pv_point)
        pv_flag = frag_flag.Flag.create(pv_locator,
                                        label=f'{region}_{side}_pv',
                                        add_align_transform=True,
                                        orientation=ik_flag_pv_orient,
                                        scale=scale)
        pv_flag.lock_and_hide_attrs(attr_utils.SCALE_ATTRS)
        pv_flag_alignment_grp = pv_flag.get_align_transform()
        pv_flag_alignment_grp.setParent(flag_grp)
        pm.delete(pv_locator)

        pv_line = rig_utils.create_line_between(ik_chain[1], pv_flag, name=f'{side}_{region}_pv_line')
        pv_line.setParent(nt_grp)

        # Make sure the spring solver node exists in the scene before connecting to it.
        pm.mel.eval('ikSpringSolver;')

        # setup the IK handles and organize them appropriately.
        alignment_loc = pm.spaceLocator(n=f'{region}_{side}_alignment_loc')
        alignment_loc.v.set(False)
        alignment_loc.setParent(nt_grp)
        constraint.parent_constraint_safe(rev_foot_chain[0], alignment_loc)

        # The main handle is created as an RP solver and then switched to the spring solver: Maya re-poses the
        # joints when a handle is created directly as a spring solver, which would move the chain off the skeleton.
        main_ik_handle, _ = pm.ikHandle(sol='ikRPsolver', sj=ik_drv_chain[0], ee=ik_drv_chain[3])
        pm.connectAttr(pm.PyNode('ikSpringSolver.message'), main_ik_handle.ikSolver, force=True)
        main_ik_handle.rename(f'{region}_{side}_main_ik_handle')
        main_ik_handle.setParent(alignment_loc)
        main_ik_handle.twist.set(180)
        pm.poleVectorConstraint(pv_flag, main_ik_handle, w=1)

        top_ik_handle, _ = pm.ikHandle(sol='ikRPsolver', sj=ik_chain[0], ee=ik_chain[2])
        top_ik_handle.rename(f'{region}_{side}_udrv_ik_handle')
        top_ik_handle.setParent(foot_lift_joint)

        bot_ik_handle, _ = pm.ikHandle(sol='ikSCsolver', sj=ik_chain[2], ee=ik_chain[3])
        bot_ik_handle.rename(f'{region}_{side}_ldrv_ik_handle')
        bot_ik_handle.setParent(ik_drv_chain[3])

        # --- FK setup ----------------------------------------------------------------------
        fk_chain_joints = joint_utils.duplicate_chain(leg_chain[0], leg_chain[-1], suffix='fk')
        fk_chain_joints[0].setParent(nt_grp)
        fk_chain_joints[0].v.set(False)
        chain_fk_result = fk_chain.fk_joint_chain(fk_chain_joints[0],
                                                  fk_chain_joints[-1],
                                                  create_end_flag=True,
                                                  scale=scale)
        fk_flags = chain_fk_result['flags']
        fk_flag_alignment_grp = fk_flags[0].get_align_transform()
        fk_flag_alignment_grp.setParent(flag_grp)

        # --- IK/FK switch and shared constraints -------------------------------------------
        switch_joint = leg_chain[2]

        ikfk_switch_result = ikfk_switch.ikfk_switch(switch_joint, side, region, scale=scale)
        invert_node = ikfk_switch_result['invert_node']
        switch_flag = ikfk_switch_result['flag']
        switch_flag.lock_and_hide_attrs(['v'] + attr_utils.TRANSFORM_ATTRS)
        switch_flag_alignment_grp = switch_flag.get_align_transform()
        switch_flag_alignment_grp.setParent(flag_grp)
        switch_attr_name = ikfk_switch_result['name']

        # visibility switching
        invert_node.straight >> ik_flag.v
        ik_flag.lock_and_hide_attrs(['v'])
        invert_node.straight >> pv_flag.v
        invert_node.straight >> pv_line.v
        pv_flag.lock_and_hide_attrs(['v'])
        for index, fk_flag in enumerate(fk_flags):
            invert_node.inverse >> fk_flag.v
            fk_flag.v.lock()
            if index and fk_flag not in fk_flags[-2:]:
                # Middle flags (knee, ankle) are hinges and only rotate about their primary axis.
                fk_flag.lock_and_hide_attrs(['v', 'rx', 'ry'] + attr_utils.TRANSLATION_ATTRS + attr_utils.SCALE_ATTRS)
            else:
                fk_flag.lock_and_hide_attrs(['v'] + attr_utils.TRANSLATION_ATTRS + attr_utils.SCALE_ATTRS)

        for skel_joint, ik_joint, fk_joint in zip(leg_chain, ik_chain, fk_chain_joints):
            shared_constraint = constraint.parent_constraint_safe([fk_joint, ik_joint], skel_joint, w=1)

            # IK
            invert_node.straight >> shared_constraint.getWeightAliasList()[1]
            # FK
            invert_node.inverse >> shared_constraint.getWeightAliasList()[0]

        clamp_ext = chain_rev_foot_result['clamp']
        ik_sc_solver = bot_ik_handle.ikSolver.get()
        ik_spring_solver = main_ik_handle.ikSolver.get()
        unit_conv_nodes = unit_conv_nodes + ik_flag.listConnections(type=pm.nt.UnitConversion)
        # listConnections returns one entry per connection and can overlap with the conversion
        # nodes the rig results already gathered. Strip duplicates or the meta connection below
        # errors with 'already connected' on the second fragParent hookup to the same node.
        unit_conv_nodes = list(dict.fromkeys(unit_conv_nodes))
        # Meta Connections
        node.connect_nodes(ik_chain, 'ikChain', 'fragParent')
        node.connect_node(ik_flag, 'ikFlag', 'fragParent')
        node.connect_node(ik_offset_flag, 'ikFlagOffset', 'fragParent')
        node.connect_node(pv_flag, 'pvFlag', 'fragParent')
        node.connect_node(ik_toe_flag, 'ikToeFlag', 'fragParent')
        node.connect_node(pv_line, 'pvLine', 'fragParent')
        node.pynode.addAttr('switchAttrName', dt='string')
        node.pynode.attr('switchAttrName').set(switch_attr_name)
        node.connect_node(switch_flag, 'switchFlag', 'fragParent')
        node.connect_node(invert_node, 'invertNode', 'fragParent')
        node.connect_node(start_joint, 'startJoint')
        node.connect_node(end_joint, 'endJoint')
        node.connect_nodes(leg_chain, 'bindJoints')
        node.connect_nodes(fk_chain_joints, 'fkChain', 'fragParent')
        node.connect_nodes(fk_flags, 'fkFlags', 'fragParent')
        node.connect_nodes([ik_sc_solver, ik_spring_solver], 'ikSolver', 'fragParent')
        node.connect_nodes(unit_conv_nodes, 'unitConvNodes', 'fragParent')
        node.connect_node(clamp_ext, 'clamp', 'fragParent')

        return node

    def get_flags(self):
        """
        Returns all the flags connected to the component.

        :return: The FK flags followed by the IK, IK offset, pole vector, IK toe and switch flags.
        :rtype: list[frag_flag.Flag]
        """

        flags = self.pynode.fkFlags.listConnections()
        flags.append(self.pynode.ikFlag.get())
        flags.append(self.pynode.ikFlagOffset.get())
        flags.append(self.pynode.pvFlag.get())
        flags.append(self.pynode.ikToeFlag.get())
        switch_flag = self.pynode.switchFlag.get()
        if switch_flag and switch_flag not in flags:
            flags.append(switch_flag)
        return [frag_flag.Flag(x) for x in flags]

    @property
    def fk_flags(self):
        """
        Returns the FK flags of the component.

        :return: The FK flags.
        :rtype: list[frag_flag.Flag]
        """

        flags = self.pynode.fkFlags.listConnections()
        return [frag_flag.Flag(x) for x in flags]

    @property
    def ik_flags(self):
        """
        Returns the IK flags of the component.

        :return: The IK, IK offset, pole vector and IK toe flags.
        :rtype: list[frag_flag.Flag]
        """

        flags = [self.pynode.ikFlag.get(),
                 self.pynode.ikFlagOffset.get(),
                 self.pynode.pvFlag.get(),
                 self.pynode.ikToeFlag.get()]
        return [frag_flag.Flag(x) for x in flags]

    @property
    def ik_flag(self):
        """
        Returns the main IK flag.

        :return: The IK flag.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.ikFlag.get())

    @property
    def ik_flag_offset(self):
        """
        Returns the IK offset flag.

        :return: The IK offset flag.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.ikFlagOffset.get())

    @property
    def pv_flag(self):
        """
        Returns the pole vector flag.

        :return: The pole vector flag.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.pvFlag.get())

    @property
    def switch_flag(self):
        """
        Returns the IK/FK switch flag.

        :return: The switch flag.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.switchFlag.get())

    def attach_component(self, parent_component_list, parent_object_list, point=True, orient=True):
        """
        Constrain the flag and no touch groups to a list of given parent objects for point only.

        This override drops the orient constraints of the base implementation because they make the pole vector
        constraint on the spring solver fail; the orient argument is accepted but ignored.

        :param list[FRAGNode] parent_component_list: The FRAG Nodes that should be registered as parents for
            attachment.
        :param list[Transform] parent_object_list: A list of transforms this component should be constrainted between.
        :param bool point: If this FRAG component should constrain its translation.
        :param bool orient: Accepted for signature compatibility; orientation is never constrained.
        """

        # Get local level groups
        if not parent_object_list or not parent_component_list or not any([point, orient]):
            return

        if not isinstance(parent_object_list, list):
            parent_object_list = [parent_object_list]

        if not isinstance(parent_component_list, list):
            parent_component_list = [parent_component_list]

        flag_grp = self.pynode.getAttr('flagGroup')
        nt_grp = self.pynode.getAttr('noTouch')

        for align_grp in [flag_grp, nt_grp]:
            # Reset the constraints by stripping the old ones.
            pm.delete(pm.listRelatives(align_grp, type=pm.nt.Constraint))

        attr_utils.set_attr_state(nt_grp, False, attr_utils.TRANSLATION_ATTRS + attr_utils.ROTATION_ATTRS)

        if point:
            constraint.parent_constraint_safe(parent_object_list, flag_grp, mo=1, skip_rotate_attrs=['x', 'y', 'z'])
            constraint.parent_constraint_safe(parent_object_list, nt_grp, mo=1, skip_rotate_attrs=['x', 'y', 'z'])

        self.pynode.pointParentAttachments.disconnect()
        for node in parent_component_list:
            if point:
                self._connect_parent(node, self.pynode.pointParentAttachments)

        for node in parent_object_list:
            if point:
                self._connect_parent(node, self.pynode.pointParentObjects)

        attr_utils.set_attr_state(nt_grp, True, attr_utils.TRANSLATION_ATTRS + attr_utils.ROTATION_ATTRS)

    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive the component with a given skeleton.

        :param Joint attach_skeleton_root: Top level joint of the hierarchy to drive the component.
        :param bool mo: If object offsets should be maintained.
        :return: A list of all created constraints.
        :rtype: list[Constraint]
        """

        target_root_hierarchy = chain_markup.ChainMarkup(attach_skeleton_root)
        constraint_list = []

        fk_flag_list = self.fk_flags
        ik_flag_list = [self.ik_flag, self.pv_flag, self.pynode.ikToeFlag.get()]

        bind_joint_list = self.bind_joints

        skel_region = None
        skel_side = None
        if bind_joint_list:
            wrapped_node = chain_markup.JointMarkup(bind_joint_list[0])
            skel_region = wrapped_node.region
            skel_side = wrapped_node.side

        skel_region = skel_region or self.region
        skel_side = skel_side or self.side

        joint_list = target_root_hierarchy.get_full_chain(skel_region, skel_side)

        if joint_list:
            if len(fk_flag_list) < 4:
                # Older rigs did not register the ball flag on fkFlags, so it has to be found by name under the
                # last registered FK flag before the flags can be zipped against the skeleton chain.
                found_flags = pm.listRelatives(fk_flag_list[-1], ad=True, type=pm.nt.Joint)
                for flag_node in found_flags:
                    if 'ball' in flag_node.name():
                        fk_flag_list.append(flag_node)
            if fk_flag_list and len(fk_flag_list) <= len(joint_list):
                # fk constraints
                for flag_node, joint_node in list(zip(fk_flag_list, joint_list)):
                    constraint_node = constraint.parent_constraint_safe(joint_node, flag_node, mo=mo)
                    if constraint_node:
                        constraint_list.append(constraint_node)

            if ik_flag_list:
                # ik constraints
                constraint_node = constraint.parent_constraint_safe(joint_list[3], ik_flag_list[0], mo=mo)
                if constraint_node:
                    constraint_list.append(constraint_node)

                pv_locator = ik_utils.create_pole_vector_locator(joint_list[:3])
                pv_locator.setParent(joint_list[1])
                pv_locator.addAttr('bake_helper', at=bool, dv=True)
                constraint_node = constraint.parent_constraint_safe(pv_locator, ik_flag_list[1], mo=mo)
                if constraint_node:
                    constraint_list.append(constraint_node)

                constraint_node = constraint.parent_constraint_safe(joint_list[-1], ik_flag_list[-1], mo=mo)
                if constraint_node:
                    constraint_list.append(constraint_node)

        return constraint_list
