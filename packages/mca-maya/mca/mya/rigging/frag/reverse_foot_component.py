"""
FRAG component that builds an IK/FK switching leg with a reverse foot.

The bind chain (hip, knee, ankle, ball, toe) is duplicated into an ``fk_chain`` and an ``ik_chain`` under the
component's NO_TOUCH group. The FK chain gets flags down to the ankle plus a separate ball flag; the IK chain gets an
RP solver, pole vector and offset flag and its ankle / toe are driven by reverse_foot_rig using the ``_toe``, ``_ball``,
``_heel``, ``_interior`` and ``_exterior`` contact joints of the skeleton. An ikfk_switch flag blends the bind chain
between the two.
"""

import pymel.core as pm

from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup, fk_chain, ik_chain, ik_utils, ikfk_switch, joint_utils, reverse_foot_rig
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils, constraint, dag


class ReverseFootComponent(keyable_component.KeyableComponent):
    """
    Keyable component holding an IK/FK leg with a reverse foot.

    On top of the KeyableComponent groups it adds the ``ikChain`` / ``fkChain`` joint links, the ``ikFlag``,
    ``ikFlagOffset``, ``fkFlagOffset``, ``pvFlag``, ``ikToeFlag``, ``switchFlag`` and ``fkFlags`` flag links, the
    ``pvLine``, ``ikHandle``, ``lineClusters``, ``clamp``, ``ik_solver``, ``invertNode`` and ``unitConvNodes`` support
    node links and the ``switchAttrName`` string attribute. Build arguments are stored in ``buildKwargs``.
    """

    VERSION = 2
    # Names version 1 rigs stored these attributes under; _update_version_1_to_version_2 renames them.
    LEGACY_ATTR_NAMES = {'ik_solver': 'ikSolver'}

    def _update_version_1_to_version_2(self):
        """
        Rename the build attributes a version 1 rig stored in snake_case to their camelCase names.
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
               lock_child_translate_axes=('tx', 'ty', 'tz'),
               lock_root_translate_axes=('tx', 'ty', 'tz'),
               ankle_as_primary=True,
               **kwargs):
        """
        Creates a reverse foot component.

        :param FRAGNode frag_parent: FRAG Rig FRAGNode.
        :param pm.nt.Joint start_joint: Start joint of the chain.
        :param pm.nt.Joint end_joint: End joint of the chain.
        :param str side: The side in which the component is on the body.
        :param str region: The name of the region.  EX: "Arm"
        :param float scale: Scale value for flag creation.
        :param list[float, float, float] ik_flag_orient: XYZ rotation offset applied to the IK flag shape.
        :param list[float, float, float] ik_flag_pv_orient: XYZ rotation offset applied to the pole vector flag shape.
        :param str ik_flag_rotate_order: Rotate order for the IK flag, default is xyz.
        :param list[str] lock_child_rotate_axes: Rotate attrs to lock on every FK flag but the first.
        :param list[str] lock_child_translate_axes: Translate attrs to lock on every FK flag but the first.
        :param list[str] lock_root_translate_axes: Translate attrs to lock on the first FK flag.
        :param bool ankle_as_primary: If True the IK flag sits on the ankle; if False it sits on the ball and the
            ankle follows through the reverse foot.
        :param dict kwargs: Unused extra build arguments accepted so templates can pass a shared kwargs dict.
        :return: Returns an instance of ReverseFootComponent.
        :rtype: ReverseFootComponent
        """

        # Serialize build kwargs for later reconstruction.
        kwargs_dict = {}
        kwargs_dict['scale'] = scale
        kwargs_dict['ik_flag_orient'] = ik_flag_orient
        kwargs_dict['ik_flag_pv_orient'] = ik_flag_pv_orient
        kwargs_dict['ik_flag_rotate_order'] = ik_flag_rotate_order
        kwargs_dict['lock_child_rotate_axes'] = lock_child_rotate_axes
        kwargs_dict['lock_child_translate_axes'] = lock_child_translate_axes
        kwargs_dict['lock_root_translate_axes'] = lock_root_translate_axes
        kwargs_dict['ankle_as_primary'] = ankle_as_primary

        # Set Namespace
        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set=f'{root_namespace}:')

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                         ReverseFootComponent.__name__,
                                                         ReverseFootComponent.VERSION,
                                                         side=side,
                                                         region=region,
                                                         align_component=start_joint)

        # Store serialized kwargs onto network node for rig serialization.
        attr_utils.set_compound_attribute_groups(node.pynode, 'buildKwargs', kwargs_dict)

        # Get local level groups
        flag_grp = node.pynode.flagGroup.get()
        nt_grp = node.pynode.noTouch.get()

        chain_between = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)

        # --- FK chain ----------------------------------------------------------------------
        chain_fk = joint_utils.duplicate_chain(start_joint, end_joint, suffix='fk_chain')
        chain_fk[0].setParent(nt_grp)
        chain_fk_result = fk_chain.fk_joint_chain(chain_fk[0],
                                                  chain_fk[2],
                                                  scale=scale,
                                                  children_align_transforms=True,
                                                  create_end_flag=True,
                                                  offset_flag=True)

        # Lock Attributes. fk_flags and flags are the same list object as chain_fk_result['flags'], so the ball
        # flag appended to fk_flags below also shows up in the visibility loop that reads chain_fk_result.
        fk_flags = chain_fk_result['flags']
        flags = chain_fk_result['flags']
        fk_flag_offset = chain_fk_result['offset_flag']

        for x in flags:
            x.v.set(keyable=False, channelBox=False)

        attrs_to_lock = ['sx', 'sy', 'sz'] + list(lock_root_translate_axes)
        flags[0].lock_and_hide_attrs(attrs_to_lock)

        # Create the FK toe flag
        ball_joint = chain_fk[3]
        label = ball_joint.replace('_fk_chain', '')
        fk_ball_flag = frag_flag.Flag.create_ratio(ball_joint,
                                                   scale=scale,
                                                   label=label,
                                                   add_align_transform=True)
        fk_ball_align = fk_ball_flag.get_align_transform()
        fk_ball_flag.lock_and_hide_attrs(['tx', 'ty', 'tz', 'sx', 'sy', 'sz'])
        pm.parentConstraint(fk_ball_flag, ball_joint, w=True, mo=False)

        attrs_to_lock = attrs_to_lock + list(lock_child_rotate_axes) + list(lock_child_translate_axes)
        for x in flags:
            if x != flags[0]:
                x.lock_and_hide_attrs(attrs_to_lock)

        # Organize groups
        start_flag = fk_flags[0]
        flag_align_grp = start_flag.alignTransform.get()
        flag_align_grp.setParent(flag_grp)
        chain_fk[0].setParent(nt_grp)
        end_flag = fk_flags[-1]
        pm.parent(fk_ball_align, end_flag)
        if fk_flag_offset:
            pm.parentConstraint(fk_flag_offset, fk_ball_align, w=True, mo=True)
        fk_flags.append(fk_ball_flag)

        # --- IK chain ----------------------------------------------------------------------
        # Duplicate chain and set up the ik chain
        chain_ik = joint_utils.duplicate_chain(start_joint, end_joint, suffix='ik_chain')
        chain_ik[0].setParent(nt_grp)
        chain_ik_result = ik_chain.ik_joint_chain(chain_ik[0],
                                                  chain_ik[2],
                                                  scale=scale,
                                                  side=side,
                                                  region=region,
                                                  ik_flag_orient=ik_flag_orient,
                                                  ik_flag_pv_orient=ik_flag_pv_orient,
                                                  ik_flag_rotate_order=ik_flag_rotate_order)

        # Edit results
        ik = chain_ik_result['ik_handle']
        pm.delete(chain_ik_result['offset_constraint'])
        ik_align_group = chain_ik_result['ik_zero']
        ik_align_group.visibility.set(0)

        pv_flag = chain_ik_result['pv_flag']
        ik_flag = chain_ik_result['ik_flag']
        if not ankle_as_primary:
            ik_constraint = chain_ik_result['ik_constraint']
            pm.delete(ik_constraint)
            ik_align_transform = ik_flag.alignTransform.get()
            pm.delete(constraint.point_constraint_safe(chain_ik[3], ik_align_transform))
            constraint.parent_constraint_safe(ik_flag, ik_align_group, w=True, mo=True)
        ik_flag_offset = chain_ik_result['ik_flag_offset']
        pv_line = chain_ik_result['pv_line']
        line_clusters = chain_ik_result['line_clusters']
        ik_solver = chain_ik_result['ik_solver']
        unit_conv_nodes = chain_ik_result['unit_conv_nodes']

        pv_flag.visibility >> pv_line.visibility
        pv_flag.overrideVisibility >> pv_line.overrideVisibility
        pv_flag.overrideEnabled >> pv_line.overrideEnabled

        # --- Reverse foot ------------------------------------------------------------------
        skel_hierarchy = chain_markup.ChainMarkup(start_joint)

        wrapped_joint = chain_markup.JointMarkup(start_joint)
        region_markup = wrapped_joint.region

        toe_contact_joint = skel_hierarchy.get_start(f'{region_markup}_toe', side)
        ball_contact_joint = skel_hierarchy.get_start(f'{region_markup}_ball', side)
        heel_contact_joint = skel_hierarchy.get_start(f'{region_markup}_heel', side)
        interior_lean_joint = skel_hierarchy.get_start(f'{region_markup}_interior', side)
        exterior_lean_joint = skel_hierarchy.get_start(f'{region_markup}_exterior', side)

        # Validate all required contact joints are present
        contact_joints = [toe_contact_joint,
                          ball_contact_joint,
                          exterior_lean_joint,
                          interior_lean_joint,
                          heel_contact_joint]
        missing_joints = []
        joint_names = [f'{region_markup}_toe',
                       f'{region_markup}_ball',
                       f'{region_markup}_exterior',
                       f'{region_markup}_interior',
                       f'{region_markup}_heel']
        for jnt, name in zip(contact_joints, joint_names):
            if jnt is None:
                missing_joints.append(f'{name}_{side}')
        if missing_joints:
            raise ValueError('ReverseFootComponent requires contact joints that are missing from skeleton: '
                             f'{missing_joints}')

        chain_rev_foot_result = reverse_foot_rig.reverse_foot_chain(chain_ik[2],
                                                                    chain_ik[-1],
                                                                    scale=scale,
                                                                    contact_joints=[toe_contact_joint,
                                                                                    ball_contact_joint,
                                                                                    exterior_lean_joint,
                                                                                    interior_lean_joint,
                                                                                    heel_contact_joint],
                                                                    side=side,
                                                                    region=region,
                                                                    ik_foot_flag=ik_flag)
        rev_foot_chain = chain_rev_foot_result['chain']
        pm.parent(rev_foot_chain[0], nt_grp)
        reverse_foot_grp = chain_rev_foot_result['reverse_foot_grp']
        rev_foot_chain = chain_rev_foot_result['reverse_chain']
        ik_toe_flag = chain_rev_foot_result['ik_toe_flag']
        clamp = chain_rev_foot_result['clamp']
        unit_conv_nodes = unit_conv_nodes + chain_rev_foot_result['unit_conv_nodes']
        # If we have an offset flag reset the constraints to handle the IK main vs offset flag.
        pm.delete(chain_rev_foot_result['alignment_constraint'])
        constraint.parent_constraint_safe(ik_flag_offset, reverse_foot_grp, mo=True)

        # Parent to IK and Organize
        pm.parent(ik, rev_foot_chain[0])
        pm.parent(reverse_foot_grp, nt_grp)
        reverse_foot_grp.v.set(0)

        # --- IK/FK switch ------------------------------------------------------------------
        switch_joint = chain_between[2]

        ikfk_switch_result = ikfk_switch.ikfk_switch(switch_joint, side, region, scale=scale)
        invert_node = ikfk_switch_result['invert_node']
        switch_flag = ikfk_switch_result['flag']
        switch_attr_name = ikfk_switch_result['name']

        # visibility switching
        invert_node.straight >> ik_flag.v
        invert_node.straight >> pv_flag.v
        for fk_flag in chain_fk_result['flags']:
            invert_node.inverse >> fk_flag.v
            fk_flag.v.lock()
        invert_node.inverse >> fk_flag_offset.v

        # Organize the groups
        ik_align_grp = ik_flag.alignTransform.get()
        toe_align_grp = ik_toe_flag.alignTransform.get()
        pv_align_grp = pv_flag.alignTransform.get()
        switch_align_grp = switch_flag.alignTransform.get()

        pm.parent([pv_line, ik_align_group], nt_grp)
        pm.parent([ik_align_grp, toe_align_grp, pv_align_grp, switch_align_grp], flag_grp)

        # visibility setting, allows pv line to be seen
        chain_fk[0].v.set(0)
        chain_ik[0].v.set(0)
        nt_grp.v.unlock()
        nt_grp.v.set(1)
        nt_grp.v.lock()

        # lock attributes
        ik_flag.lock_and_hide_attrs(['sx', 'sy', 'sz', 'v'])
        ik_flag_offset.lock_and_hide_attrs(['tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'v'])
        fk_flag_offset.lock_and_hide_attrs(['tx', 'ty', 'tz', 'sx', 'sy', 'sz', 'v'])
        pv_flag.lock_and_hide_attrs(['rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v'])
        switch_flag.lock_and_hide_attrs(['tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'radius', 'v'])
        fk_flags[1].lock_and_hide_attrs(['rx', 'ry'])
        flag_unit_conv_nodes = [x for x in ik_flag.listConnections() if isinstance(x, pm.nt.UnitConversion)]
        unit_conv_nodes = flag_unit_conv_nodes + unit_conv_nodes
        # listConnections returns one entry per connection and can overlap with the conversion
        # nodes the rig results already gathered. Strip duplicates or the meta connection below
        # errors with 'already connected' on the second fragParent hookup to the same node.
        unit_conv_nodes = list(dict.fromkeys(unit_conv_nodes))

        # Meta Connections
        node.connect_nodes(chain_ik, 'ikChain', 'fragParent')
        node.connect_node(ik_flag, 'ikFlag', 'fragParent')
        node.connect_node(ik_flag_offset, 'ikFlagOffset', 'fragParent')
        node.connect_node(fk_flag_offset, 'fkFlagOffset', 'fragParent')
        node.connect_node(pv_flag, 'pvFlag', 'fragParent')
        node.connect_node(ik_toe_flag, 'ikToeFlag', 'fragParent')
        node.connect_node(pv_line, 'pvLine', 'fragParent')
        node.connect_node(ik, 'ikHandle', 'fragParent')
        node.connect_nodes(line_clusters, 'lineClusters', 'fragParent')
        node.pynode.addAttr('switchAttrName', dt='string')
        node.pynode.attr('switchAttrName').set(switch_attr_name)
        node.connect_node(switch_flag, 'switchFlag', 'fragParent')
        node.connect_node(invert_node, 'invertNode', 'fragParent')
        node.connect_node(start_joint, 'startJoint')
        node.connect_node(end_joint, 'endJoint')
        node.connect_nodes(chain_between, 'bindJoints')
        node.connect_nodes(chain_fk, 'fkChain', 'fragParent')
        node.connect_nodes(fk_flags, 'fkFlags', 'fragParent')
        node.connect_node(clamp, 'clamp', 'fragParent')
        node.connect_node(ik_solver, 'ikSolver', 'fragParent')
        node.connect_nodes(unit_conv_nodes, 'unitConvNodes', 'fragParent')

        # Make the ik joints and fk joints control the base joints
        for x in range(len(chain_between)):
            orient_constraint = pm.orientConstraint(chain_fk[x], chain_ik[x], chain_between[x], w=1, mo=0)
            point_constraint = pm.pointConstraint(chain_fk[x], chain_ik[x], chain_between[x], w=1, mo=1)

            # IK
            invert_node.straight >> orient_constraint.getWeightAliasList()[1]
            invert_node.straight >> point_constraint.getWeightAliasList()[1]
            # FK
            invert_node.inverse >> orient_constraint.getWeightAliasList()[0]
            invert_node.inverse >> point_constraint.getWeightAliasList()[0]

        return node

    def get_flags(self):
        """
        Returns all the flags connected to the component.

        :return: The FK flags followed by the IK, IK offset, FK offset, pole vector, IK toe and switch flags.
        :rtype: list[frag_flag.Flag]
        """

        flags = self.pynode.fkFlags.listConnections()
        flags.append(self.pynode.ikFlag.get())
        flags.append(self.pynode.ikFlagOffset.get())
        flags.append(self.pynode.fkFlagOffset.get())
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

        :return: The FK flags, including the ball flag.
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
    def fk_flag_offset(self):
        """
        Returns the FK offset flag.

        :return: The FK offset flag.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.fkFlagOffset.get())

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
                constraint_node = constraint.parent_constraint_safe(joint_list[2], ik_flag_list[0], mo=mo)
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
