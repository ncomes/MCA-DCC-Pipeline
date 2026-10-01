"""

A tail, a tentacle, a tongue: a long chain bent by a curve, and able to pull back into itself.

A spline IK solver bends a chain to follow a curve, and the curve is skinned to a handful of joints
- so three or four controls can shape twenty joints. On top of that this component builds a
*retract*: one attribute that walks the chain back down its own curve, each joint travelling and
shrinking over its own slice of the range, which is how a tongue goes back in a mouth.

The scale goes onto *leaf* joints - one hanging off each chain joint - so the chain the engine
exports stays scale-free, the same arrangement the stretchy reverse FK component uses.

Three joints outside the chain do the remembering. The end and mid helper joints are driven by the
controls, so an animator's work survives being baked onto a skeleton and read back: that is what
``attach_to_skeleton`` reconnects. The start helper joint is optional, and whether there is one is
what decides whether the component has a control at the base.

What was wrong before:

- **Which controls a component has was worked out from how many it had.** ``attach_to_skeleton``
  read ``has_start_flag = len(flag_list) == 3 + int(has_mid_flag)`` and then indexed the list -
  ``flag_list[2]`` for the end control when there is a start control, ``flag_list[1]`` when there
  is not. ``spline_ik_rig`` answers each control under its own name, so the component records them
  under their own names: ``startFlag``, ``endFlag``, ``auxFlag``, ``midFlag``. Nothing is inferred
  from a count, and nothing indexes a list by a number worked out from one.
- **``attach_component`` was a copy of the base one that had drifted.** It disconnects
  ``pointParentAttachments`` and ``orientParentAttachments`` and *not* ``pointParentObjects`` or
  ``orientParentObjects``, so the two object lists grew every time a component was reattached - and
  those lists are what a rebuild reads. The base fixed that; this is the override it needs, which
  is the two extra groups this component has, through ``get_attachment_groups``.
- **``attach_to_skeleton`` required the control count and the joint count to match exactly**, and
  did nothing at all, silently, when they did not - the fourth component found with that fault. It
  also appended ``parent_constraint_safe``'s answer without asking whether there was one, so the
  list it returned could have ``None`` in it.
- **The main control group was snapped to the control group and then frozen on the next line**,
  which puts an empty transform's matrix straight back to identity - the same fault as
  ``align_component``, in a third place. The outcome is the same either way here, because the
  control group it was being snapped to is itself at identity, so the two lines are gone rather
  than written down.
- Both of the two groups this component adds were parented to the control group's *parent* and
  then, four lines later, to the control group. Four ``setParent`` calls for two groups.
- ``if leaf_joint != leaf_joint_list[-1]`` asks whether this is the last leaf joint by comparing
  nodes, so a list with the same joint twice in it skips the wrong one. It is an index.
- ``zip(driver_joints, chain_between, leaf_joint_list)`` silently truncates to the shortest, so a
  short leaf list left the far end of the chain unscaled with nothing said. The lengths are
  checked.
- ``endFlag`` was the one thing wired without a back-pointer, so the control could not say which
  component it belonged to.
- The version migration had never run, like the other four, for the ``frag_base`` reason. It is
  reachable now and the suite drives it.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup
from mca.mya.rigging import joint_utils
from mca.mya.rigging import spline_ik_rig
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.rigging.frag import rig_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The suffix the duplicated chain the solver bends carries.
SPLINE_CHAIN_SUFFIX = 'spline_ik'

#: What the component keeps its pieces on.
FLAGS_ATTR = 'flags'
START_FLAG_ATTR = 'startFlag'
END_FLAG_ATTR = 'endFlag'
AUX_FLAG_ATTR = 'auxFlag'
MID_FLAG_ATTR = 'midFlag'
MAIN_FLAGS_GROUP_ATTR = 'mainFlagsGroup'
MID_FLAG_GROUP_ATTR = 'midFlagGroup'
LEAF_JOINTS_ATTR = 'leafJoints'
HELPER_JOINT_ATTR = 'helperJoint'
END_HELPER_JOINT_ATTR = 'endHelperJoint'
START_HELPER_JOINT_ATTR = 'startHelperJoint'
SPLINE_SKIN_CLUSTER_ATTR = 'splineSkinCluster'
IK_SOLVER_ATTR = 'ikSolver'
REMAP_NODES_ATTR = 'remapNodes'
MOTION_PATH_ATTR = 'motionPath'
MULT_NODES_ATTR = 'multNodes'
CONDITION_ATTR = 'condition'
REVERSE_NODES_ATTR = 'reverseNodes'
INFO_NODE_ATTR = 'infoNode'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: The attribute a retracting component drives on its mid helper joint, so the value survives being
#: baked onto a skeleton. :meth:`SplineIKComponent.attach_to_skeleton` wires it back the other way.
RETRACT_ATTR = 'retract'
ATTACH_ATTRS = (RETRACT_ATTR,)

#: Unreal will not take a scale of zero, so the retract's output is remapped into this range.
RETRACT_SCALE_FLOOR = 0.001


class SplineIKComponent(keyable_component.KeyableComponent):
    """
    A long chain shaped by three or four controls, and able to retract into itself.
    """

    VERSION = 2

    #: What version 1 stored these attributes under, before the pipeline settled on camelCase.
    LEGACY_ATTR_NAMES = {'end_flag': END_FLAG_ATTR, 'helper_joint': HELPER_JOINT_ATTR}

    def _update_version_1_to_version_2(self):
        """
        Bring a version 1 component up to version 2 by renaming its two snake_case attributes.

        ``rename_legacy_attrs`` renames rather than rewires, so whatever was connected to each
        attribute stays connected to it.
        """

        self.rename_legacy_attrs(self.LEGACY_ATTR_NAMES)
        self.set_version(2)

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, end_joint, leaf_joint_list, end_helper_joint,
               mid_helper_joint, side, region, start_helper_joint=None, mid_flag=True,
               can_retract=True, **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The first bind joint.
        :param pm.nt.Joint end_joint: The last one.
        :param list(pm.nt.Joint) leaf_joint_list: One leaf joint per chain joint, in order. They
            take the scale, which keeps the chain the engine exports scale-free.
        :param pm.nt.Joint end_helper_joint: A joint sitting where the chain's last joint is. It
            skins the far end of the curve and is what the end control drives.
        :param pm.nt.Joint mid_helper_joint: A joint at the middle of the chain. The mid control's
            position is stored on it, which is what lets an animator's work be recovered on a
            rebuild.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param pm.nt.Joint start_helper_joint: A joint sitting where the chain's first joint is.
            None means the component has no control at the base.
        :param bool mid_flag: Build a control at the middle of the chain.
        :param bool can_retract: Build the retract.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component, or None when the chain is too short for a spline IK.
        :rtype: SplineIKComponent or None
        :raises ValueError: When there is not one leaf joint per chain joint. The version before
            zipped the two and silently left the far end of the chain unscaled.
        """

        bind_joints = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
        if len(leaf_joint_list or []) != len(bind_joints):
            raise ValueError(
                'A spline IK component needs one leaf joint per chain joint to put the scale on. '
                '{0} to {1} is {2} joints, and {3} leaf joints were given.'.format(
                    start_joint, end_joint, len(bind_joints), len(leaf_joint_list or [])))

        build_kwargs = {'mid_flag': mid_flag, 'can_retract': can_retract}
        # The helper joints are recorded as markup rather than as nodes, so a rebuild finds them
        # again by looking them up.
        for name, helper_joint in (('end_helper', end_helper_joint),
                                   ('mid_helper', mid_helper_joint),
                                   ('start_helper', start_helper_joint)):
            if helper_joint is None:
                continue
            helper_markup = chain_markup.JointMarkup(helper_joint)
            build_kwargs['{0}_region'.format(name)] = helper_markup.region
            build_kwargs['{0}_side'.format(name)] = helper_markup.side

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        SplineIKComponent.__name__,
                                                        SplineIKComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        component = SplineIKComponent(node.pynode)

        # Two more groups inside the control group: the mid control moves with the middle of the
        # chain and the others do not, so an attachment constrains them separately. Parented once -
        # the version before put each one under the control group's parent first and moved it four
        # lines later - and neither is snapped and then frozen, which is what threw the snap away.
        main_flags_grp = pm.group(empty=True, name='flags_{0}_{1}_main'.format(side, region))
        mid_flag_grp = pm.group(empty=True, name='flags_{0}_{1}_mid'.format(side, region))
        main_flags_grp.setParent(component.flag_group)
        mid_flag_grp.setParent(component.flag_group)

        duplicate_chain = joint_utils.duplicate_chain(start_joint, end_joint,
                                                      suffix=SPLINE_CHAIN_SUFFIX)
        duplicate_chain[0].setParent(component.no_touch_grp)

        built = spline_ik_rig.spline_ctrl(duplicate_chain, end_helper_joint, mid_helper_joint,
                                         region, side, start_helper_joint=start_helper_joint,
                                         mid_flag=mid_flag, can_retract=can_retract,
                                         root_align_transform=True)
        if not built:
            logger.warning('No spline IK could be built for %s %s, so %s is removed again.', side,
                           region, component.pynode)
            component.remove()
            return None

        if not start_helper_joint:
            # With no start helper joint of its own, the one spline_ik_rig made follows this
            # component's main control group - which is what lets the base of the chain move with
            # whatever the component is attached to.
            constraint.parent_constraint_safe(main_flags_grp, built['start_helper_joint'], mo=True)

        retract_remap = None
        if can_retract:
            component.wire_retract_attribute(built, mid_helper_joint)
            # Unreal will not take a scale of zero, so the end's scale is remapped off the floor.
            retract_remap = pm.createNode(
                pm.nt.RemapValue, n='{0}_{1}_spline_ik_remap_end'.format(region, side))
            retract_remap.outputMin.set(RETRACT_SCALE_FLOOR)
            built['orient_end'].scaleY >> retract_remap.inputValue
            built['remap_nodes'].append(retract_remap)

        component.parent_controls(built, main_flags_grp, mid_flag_grp)
        component.wire_joints(built, duplicate_chain, bind_joints, leaf_joint_list, retract_remap)
        component.connect_everything(built, bind_joints, leaf_joint_list, end_helper_joint,
                                     mid_helper_joint, start_helper_joint, main_flags_grp,
                                     mid_flag_grp, can_retract)
        return component

    # ----------------------------------------------------------------------------------- #
    # the pieces of the build
    # ----------------------------------------------------------------------------------- #
    def wire_retract_attribute(self, built, mid_helper_joint):
        """
        Drive the mid helper joint's ``retract`` from the end control's.

        The joint carries the value so that animation baked onto a skeleton can be read back onto a
        rebuilt rig - which is what :meth:`attach_to_skeleton` does with it.

        :param dict built: What ``spline_ik_rig.spline_ctrl`` answered.
        :param pm.nt.Joint mid_helper_joint: The joint that carries the value.
        """

        if not mid_helper_joint.hasAttr(RETRACT_ATTR):
            mid_helper_joint.addAttr(RETRACT_ATTR, dv=0, min=0, max=spline_ik_rig.RETRACT_MAX,
                                     k=True)
        # The end control, by name. The version before reached into the flag list by an index worked
        # out from whether there was a start control.
        built['end_flag'].node.attr(RETRACT_ATTR) >> mid_helper_joint.attr(RETRACT_ATTR)

    def parent_controls(self, built, main_flags_grp, mid_flag_grp):
        """
        Put each control's zeroed group into the right one of this component's two control groups.

        :param dict built: What ``spline_ik_rig.spline_ctrl`` answered.
        :param pm.nt.Transform main_flags_grp: Where the start, end and auxiliary controls go.
        :param pm.nt.Transform mid_flag_grp: Where the mid control goes, because it moves with the
            middle of the chain and the others do not.
        """

        pm.parent(built['do_not_touch'], self.no_touch_grp)

        if built['mid_flag']:
            built['mid_flag'].get_align_transform().setParent(mid_flag_grp)
        for flag_node in built['flag_nodes']:
            if flag_node in (built['aux_flag'], built['mid_flag']):
                continue
            align_transform = flag_node.get_align_transform()
            if align_transform is not None:
                align_transform.setParent(main_flags_grp)

    def wire_joints(self, built, duplicate_chain, bind_joints, leaf_joint_list, retract_remap):
        """
        Make the bind joints follow the chain the solver bends, and put the scale on the leaf
        joints.

        :param dict built: What ``spline_ik_rig.spline_ctrl`` answered.
        :param list(pm.nt.Joint) duplicate_chain: The chain the solver bends.
        :param list(pm.nt.Joint) bind_joints: The joints that follow it.
        :param list(pm.nt.Joint) leaf_joint_list: The joints that take the scale, one per chain
            joint.
        :param retract_remap: The node holding the retract's scale, or None when the component does
            not retract.
        """

        # The last driver is the node holding the chain's blended orientation, not the last joint of
        # the chain itself.
        driver_joints = duplicate_chain[:-1] + [built['orient_end']]
        last_index = len(leaf_joint_list) - 1

        for index, (driver_joint, bind_joint, leaf_joint) in enumerate(
                zip(driver_joints, bind_joints, leaf_joint_list)):
            constraint.parent_constraint_safe(driver_joint, bind_joint)
            # Length along the chain, onto the leaf joint - but not on the last one, where it makes
            # the end stretch oddly in normal use. By index: the version before asked whether this
            # leaf joint *was* the last one, which picks the wrong one if a joint appears twice.
            if index != last_index:
                driver_joint.scaleX >> leaf_joint.scaleX
            if retract_remap is not None:
                retract_remap.outValue >> leaf_joint.scaleY
                retract_remap.outValue >> leaf_joint.scaleZ

        if retract_remap is None:
            return

        # Everything hanging off the end of the chain shrinks with it, so a retracting tail goes in
        # whole rather than leaving its tip at full size.
        for child_joint in bind_joints[-1].listRelatives(allDescendents=True, type=pm.nt.Joint):
            if child_joint in leaf_joint_list:
                continue
            for axis in ('scaleX', 'scaleY', 'scaleZ'):
                retract_remap.outValue >> child_joint.attr(axis)

    def connect_everything(self, built, bind_joints, leaf_joint_list, end_helper_joint,
                           mid_helper_joint, start_helper_joint, main_flags_grp, mid_flag_grp,
                           can_retract):
        """
        Record every piece of the build on this component's node.

        Each control goes on under its own name as well as into the list, which is what makes asking
        for "the end control" a lookup rather than an index worked out from how many there are.

        :param dict built: What ``spline_ik_rig.spline_ctrl`` answered.
        :param list(pm.nt.Joint) bind_joints: The joints the chain drives.
        :param list(pm.nt.Joint) leaf_joint_list: The joints that take the scale.
        :param pm.nt.Joint end_helper_joint: The joint the end control drives.
        :param pm.nt.Joint mid_helper_joint: The joint that remembers the mid control's position.
        :param pm.nt.Joint start_helper_joint: The joint the start control drives, or None.
        :param pm.nt.Transform main_flags_grp: The group the start, end and auxiliary controls are
            in.
        :param pm.nt.Transform mid_flag_grp: The group the mid control is in.
        :param bool can_retract: Whether the retract was built.
        """

        helper_joints = [joint_node for joint_node
                         in (start_helper_joint, end_helper_joint, mid_helper_joint)
                         if joint_node is not None]
        self.connect_nodes(bind_joints + helper_joints, BIND_JOINTS_ATTR)
        self.connect_nodes(built['flag_nodes'], FLAGS_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(leaf_joint_list, LEAF_JOINTS_ATTR)

        # Each control under its own name, so nothing has to work out which is which from a count.
        for attr_name, flag_node in ((START_FLAG_ATTR, built['start_flag']),
                                     (END_FLAG_ATTR, built['end_flag']),
                                     (AUX_FLAG_ATTR, built['aux_flag']),
                                     (MID_FLAG_ATTR, built['mid_flag'])):
            if flag_node is None:
                continue
            self.connect_node(flag_node, attr_name, frag_base.FRAG_PARENT_ATTR)

        self.connect_node(mid_helper_joint, HELPER_JOINT_ATTR)
        self.connect_node(end_helper_joint, END_HELPER_JOINT_ATTR)
        if start_helper_joint is not None:
            self.connect_node(start_helper_joint, START_HELPER_JOINT_ATTR)

        self.connect_node(built['spline_skin_cluster'], SPLINE_SKIN_CLUSTER_ATTR,
                          frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['ik_solver'], IK_SOLVER_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(main_flags_grp, MAIN_FLAGS_GROUP_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(mid_flag_grp, MID_FLAG_GROUP_ATTR, frag_base.FRAG_PARENT_ATTR)

        if not can_retract:
            return
        self.connect_nodes(built['remap_nodes'], REMAP_NODES_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_nodes(built['mult_nodes'], MULT_NODES_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['motion_path'], MOTION_PATH_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['condition'], CONDITION_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['reverse_nodes'], REVERSE_NODES_ATTR, frag_base.FRAG_PARENT_ATTR)
        self.connect_node(built['info_node'], INFO_NODE_ATTR, frag_base.FRAG_PARENT_ATTR)

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        :return: Every control this component owns, in the order they were built: the start control
            when there is one, the end control, the auxiliary control, then the mid control when
            there is one.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(node) for node in self.pynode.attr(FLAGS_ATTR).listConnections()]

    def _named_flag(self, attr_name, legacy_name=None):
        """
        One control by the name it is recorded under.

        :param str attr_name: The attribute holding it.
        :param str legacy_name: What a version 1 component holds it under.
        :return: The control, or None when this component does not have one.
        :rtype: frag_flag.Flag or None
        """

        for name in (attr_name, legacy_name):
            if name and self.pynode.hasAttr(name):
                flag_node = self.pynode.attr(name).get()
                if flag_node is not None:
                    return frag_flag.Flag(flag_node)
        return None

    @property
    def start_flag(self):
        """
        :return: The control at the base of the chain, or None when the component was built without
            a start helper joint.
        :rtype: frag_flag.Flag or None
        """

        return self._named_flag(START_FLAG_ATTR)

    @property
    def end_flag(self):
        """
        :return: The control at the end of the chain, which carries the retract.
        :rtype: frag_flag.Flag or None
        """

        return self._named_flag(END_FLAG_ATTR, 'end_flag')

    @property
    def aux_flag(self):
        """
        :return: The auxiliary control that aims the end of the chain.
        :rtype: frag_flag.Flag or None
        """

        return self._named_flag(AUX_FLAG_ATTR)

    @property
    def mid_flag(self):
        """
        :return: The control at the middle of the chain, or None when the component was built
            without one.
        :rtype: frag_flag.Flag or None
        """

        return self._named_flag(MID_FLAG_ATTR)

    # ----------------------------------------------------------------------------------- #
    # the rest of the build
    # ----------------------------------------------------------------------------------- #
    @property
    def leaf_joints(self):
        """
        :return: The joints that take the scale, one per chain joint.
        :rtype: list(pm.nt.Joint)
        """

        return self.pynode.attr(LEAF_JOINTS_ATTR).get() or []

    @property
    def helper_joint(self):
        """
        :return: The joint at the middle of the chain that remembers the mid control's position.
        :rtype: pm.nt.Joint or None
        """

        value = self.get_attr_with_legacy_name(HELPER_JOINT_ATTR, 'helper_joint')
        return value

    @property
    def end_helper_joint(self):
        """
        :return: The joint sitting where the chain's last joint is.
        :rtype: pm.nt.Joint or None
        """

        return self.pynode.attr(END_HELPER_JOINT_ATTR).get()

    @property
    def start_helper_joint(self):
        """
        :return: The joint sitting where the chain's first joint is, or None when the component was
            built without one.
        :rtype: pm.nt.Joint or None
        """

        if not self.pynode.hasAttr(START_HELPER_JOINT_ATTR):
            return None
        return self.pynode.attr(START_HELPER_JOINT_ATTR).get()

    @property
    def can_retract(self):
        """
        :return: Whether this component was built with a retract.
        :rtype: bool
        """

        return bool(self.get_build_kwargs().get('can_retract'))

    # ----------------------------------------------------------------------------------- #
    # attaching
    # ----------------------------------------------------------------------------------- #
    def get_attachment_groups(self):
        """
        The groups an attachment constrains.

        This component has two more than a plain one, and the mid control's group is the odd one
        out: it moves with the middle of the chain, so it follows the end control as well as
        whatever the
        component is attached to. The base ``attach_component`` does the rest, which is what the
        version before was a drifted copy of.

        :return: The main control group and the ``NO_TOUCH`` group.
        :rtype: list(pm.nt.Transform)
        """

        groups = []
        for attr_name in (MAIN_FLAGS_GROUP_ATTR, rig_component.NO_TOUCH_ATTR):
            if not self.has_attribute(attr_name):
                continue
            group_node = self.pynode.attr(attr_name).get()
            if group_node is not None:
                groups.append(group_node)
        return groups

    def attach_component(self, parent_component_list, parent_object_list, point=True, orient=True):
        """
        Hang this component off some objects, and point the mid control's group at them too.

        :param parent_component_list: The components this one now hangs off.
        :param parent_object_list: The objects to constrain to.
        :param bool point: Follow their position.
        :param bool orient: Follow their orientation.
        """

        super(SplineIKComponent, self).attach_component(parent_component_list, parent_object_list,
                                                        point=point, orient=orient)

        mid_flag_grp = self.pynode.attr(MID_FLAG_GROUP_ATTR).get()
        end_flag = self.end_flag
        if mid_flag_grp is None or end_flag is None:
            return
        if not isinstance(parent_object_list, list):
            parent_object_list = [parent_object_list]
        if not parent_object_list:
            return

        pm.delete(pm.listRelatives(mid_flag_grp, type=pm.nt.Constraint))
        constraint.point_constraint_safe(list(parent_object_list) + [end_flag], mid_flag_grp, mo=1)

    # ----------------------------------------------------------------------------------- #
    # being driven by a skeleton
    # ----------------------------------------------------------------------------------- #
    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's controls from a skeleton, and read the retract back off it.

        A spline IK component is not driven joint for joint - its controls do not sit on the chain.
        Each control is driven by the helper joint it drives, looked up on the other skeleton by
        that joint's own markup, which is exactly what the helper joints are for.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep each control where it is rather than snapping it to its joint.
        :return: The constraints built.
        :rtype: list
        """

        hierarchy = chain_markup.ChainMarkup(attach_skeleton_root)
        constraint_list = []

        # Each control with the joint it drives, by name rather than by a position in a list worked
        # out from how many controls there are.
        for flag_node, helper_joint in ((self.start_flag, self.start_helper_joint),
                                        (self.end_flag, self.end_helper_joint),
                                        (self.mid_flag, self.helper_joint)):
            if flag_node is None or helper_joint is None:
                continue
            helper_markup = chain_markup.JointMarkup(helper_joint)
            found_joint = hierarchy.get_start(helper_markup.region, helper_markup.side)
            if found_joint is None:
                logger.warning('%s has no %s %s joint on it, so %s is not driven.',
                               attach_skeleton_root, helper_markup.side, helper_markup.region,
                               flag_node.node)
                continue
            constraint_node = constraint.parent_constraint_safe(found_joint, flag_node, mo=mo)
            if constraint_node:
                constraint_list.append(constraint_node)

        self.restore_baked_attributes(hierarchy)
        return constraint_list

    def restore_baked_attributes(self, hierarchy):
        """
        Read the attributes this component bakes onto its mid helper joint back onto the end
        control.

        The retract is a value an animator sets, and it lives on a joint as well as on the control
        so that it survives a bake. This is the half that reads it back.

        :param chain_markup.ChainMarkup hierarchy: The skeleton to read from.
        :return: The names of the attributes that were reconnected.
        :rtype: list(str)
        """

        end_flag = self.end_flag
        helper_joint = self.helper_joint
        if end_flag is None or helper_joint is None:
            return []

        helper_markup = chain_markup.JointMarkup(helper_joint)
        baked_joint = hierarchy.get_start(helper_markup.region, helper_markup.side)
        if baked_joint is None:
            return []

        restored = []
        for attr_name in ATTACH_ATTRS:
            if baked_joint.hasAttr(attr_name) and end_flag.node.hasAttr(attr_name):
                baked_joint.attr(attr_name) >> end_flag.node.attr(attr_name)
                restored.append(attr_name)
        return restored
