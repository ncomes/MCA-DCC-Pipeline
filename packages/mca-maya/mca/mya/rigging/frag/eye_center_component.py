"""
Eye center component: a single aim flag that a group of eye components follow.

Builds one ``<side>_<region>_aim`` flag at the averaged position / orientation of the child eye components' flags,
reparents those flags under it and deletes the child components' own flag groups. The first child's bind joint gets
hidden ``centerFlagTx`` / ``centerFlagTy`` / ``centerFlagTz`` attributes driven by the center flag so the flag
translate travels with the exported skeleton and can be reanimated back onto the rig.

Requires: pymel
Side effects: deletes the flag groups of the child eye components; adds attributes to the tracking eye joint.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.animation import anim_curves
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils

logger = log.MCA_LOGGER


class EyeCenterComponent(keyable_component.KeyableComponent):
    """
    Keyable component that parents the flags of several eye components under one center aim flag.

    Creates the ``centerFlag``, ``otherComponent``, ``otherComponentFlags`` and ``trackingJoint`` message
    attributes on the network node and tags it with ``isFragFace``.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent,
               side,
               region,
               components,
               attrs_to_lock_hide=attr_utils.SCALE_ATTRS + ['v']):
        """
        Creates a center eye component and parents the other eye components' flags under it.

        :param FRAGNode frag_parent: FRAG Rig FRAGNode.
        :param str side: component side.
        :param str region: component region.
        :param list(frag_base.FRAGNode) components: List of eye components to follow the center component.
        :param list(str) attrs_to_lock_hide: Attributes to lock and hide on the center flag.
        :return: Returns an instance of the EyeCenterComponent
        :rtype: EyeCenterComponent
        """

        # Set Namespace
        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set=f'{root_namespace}:')

        kwargs_dict = {}
        kwargs_dict['attrs_to_lock_hide'] = attrs_to_lock_hide

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                         EyeCenterComponent.__name__,
                                                         EyeCenterComponent.VERSION,
                                                         side=side,
                                                         region=region)

        # set serialized kwargs onto our network node we'll use this for serializing the exact build params.
        attr_utils.set_compound_attribute_groups(node.pynode, 'buildKwargs', kwargs_dict)

        node.pynode.addAttr('isFragFace', at='bool', dv=True)

        flag_grp = node.pynode.flagGroup.get()

        # Get flags from the frag
        component_flags = []
        for component in components:
            component_flag = component.get_flags()
            if component_flag:
                component_flags.append(component_flag)
        component_flags = list(set(lists.flatten_list(component_flags)))

        # The center flag sits at the average of the child flags; a throwaway locator gives Flag.create a match.
        object_to_match = pm.spaceLocator(p=[0, 0, 0], name='c_{0}_aim'.format(region))
        pm.delete(pm.pointConstraint(component_flags, object_to_match, mo=False, w=True))
        pm.delete(pm.orientConstraint(component_flags, object_to_match, mo=False, w=True))
        center_flag = frag_flag.Flag.create(object_to_match, label=f'{side}_{region}_aim')
        pm.delete(object_to_match)

        # Set groupings
        center_flag_align_grp = center_flag.get_align_transform()
        pm.parent(center_flag_align_grp, flag_grp)

        for component_flag in component_flags:
            align_transform = component_flag.get_align_transform()
            align_transform.setParent(center_flag)

        for comp in components:
            flag_grp = comp.pynode.flagGroup.get()
            pm.delete(flag_grp)

        # We will use the 1st joint to track the eye translates
        eye_joint = components[0].bind_joints
        if not isinstance(eye_joint, pm.nt.Joint):
            eye_joint = pm.PyNode(eye_joint)
        # Hidden keyable attributes on the joint carry the center flag translate so it exports with the skeleton.
        for axis in ('x', 'y', 'z'):
            attr_name = f'centerFlagT{axis}'
            if not eye_joint.hasAttr(attr_name):
                eye_joint.addAttr(attr_name, at='float', k=True, h=True)
        for axis in ('x', 'y', 'z'):
            getattr(center_flag, f't{axis}') >> eye_joint.attr(f'centerFlagT{axis}')

        # Lock and hide attributes.
        center_flag.lock_and_hide_attrs(attrs_to_lock_hide)

        # Make Connections
        components = [x.pynode for x in components]
        node.connect_nodes(components, 'otherComponent', 'fragChildren')
        node.connect_nodes(component_flags, 'otherComponentFlags')
        node.connect_node(center_flag, 'centerFlag', 'fragParent')
        node.connect_node(eye_joint, 'trackingJoint', 'trackingJoint')

        return node

    def get_flags(self):
        """
        Returns the connected flags.

        :return: Returns the connected flags.
        :rtype: list(flag.Flag)
        """

        flags = self.pynode.centerFlag.listConnections()
        if not flags:
            logger.warning(f'{self.pynode}: Does not have any flags')
            return
        flags = [frag_flag.Flag(x) for x in flags]
        return flags

    def get_start_flag(self):
        """
        Returns the first flag connected to the component.

        :return: Returns the first flag connected to the component.
        :rtype: flag.Flag
        """

        flags = self.get_flags()
        return flags[0]

    @property
    def center_flag(self):
        """
        Returns the center flag.

        :return: Returns the center flag.
        :rtype: flag.Flag
        """

        return self.pynode.centerFlag.get()

    @property
    def tracking_joint(self):
        """
        Returns the eye joint that carries the ``centerFlagT*`` tracking attributes.

        :return: Returns the tracking joint.
        :rtype: pm.nt.Joint
        """

        return self.pynode.trackingJoint.get()

    def select_flags(self):
        """
        Selected all the flags.
        """

        pm.select(self.get_flags())

    def key_flags(self):
        """
        Sets a keyframe on all the flags in the scene
        """

        flags = self.get_flags()
        pm.setKeyframe(flags)

    def to_default_pose(self):
        """
        Sets all the flags to there default position.
        """

        flags = self.get_flags()
        for _flag in flags:
            attr_utils.reset_attrs(_flag)

    @property
    def other_component_flags(self):
        """
        Returns the other component connected flags.

        :return: Returns the other component connected flags.
        :rtype: list(flag.Flag)
        """

        flags = self.pynode.otherComponentFlags.listConnections()
        if not flags:
            logger.warning(f'{self.pynode}: Does not other component flags connected.')
            return
        flags = [frag_flag.Flag(x) for x in flags]
        return flags

    def keyframe_flags_max_values(self):
        """
        Placeholder so the component satisfies the face component interface. The center flag has no poses of
        its own, so this currently does nothing and returns None.
        """

        return None

    def attach_to_skeleton(self, attach_skeleton_root=None, mo=True):
        """
        Drive the component with a given skeleton.

        :param Joint attach_skeleton_root: Top level joint of the hierarchy to drive the component.
        :param bool mo: If object offsets should be maintained.
        :return: A list of all created constraints.
        :rtype: list[Constraint]
        """

        logger.warning(f'{self}: Face components currently do not support attaching to skeleton.')
        return []

    def reanimate(self, other_root, start_time=None, end_time=None):
        """
        Transfers animation from a skeleton back onto a face rig.

        :param pm.nt.Joint other_root: The root joint that has all the animation curves
        :param float start_time: First frame to transfer. None uses the full curve.
        :param float end_time: Last frame to transfer. None uses the full curve.
        """

        current_eye_joint = self.tracking_joint
        side = current_eye_joint.skelSide.get()
        # get eye_joint from the root
        markup = chain_markup.ChainMarkup(other_root)
        eye_joint = markup.get_start('eye', side)

        # Get Eye Curves
        tx_curve = eye_joint.attr('centerFlagTx').listConnections(type=pm.nt.AnimCurve)
        ty_curve = eye_joint.attr('centerFlagTy').listConnections(type=pm.nt.AnimCurve)
        tz_curve = eye_joint.attr('centerFlagTz').listConnections(type=pm.nt.AnimCurve)

        curves = {}
        if tx_curve:
            curves['tx'] = tx_curve[0]
        if ty_curve:
            curves['ty'] = ty_curve[0]
        if tz_curve:
            curves['tz'] = tz_curve[0]

        if not curves:
            return

        # Get flags
        flag = self.get_flag()

        # Transfer Anim Curves
        # Attach or merge anim curve to flag attribute
        for flag_attr, curve in curves.items():
            anim_curves.reanimate_from_anim_curves(anim_curve=curve,
                                                   object_attribute=flag.attr(flag_attr),
                                                   start_time=start_time,
                                                   end_time=end_time)

    def get_flag(self):
        """
        Returns the first flag connected to the component.

        :return: Returns the first flag connected to the component.
        :rtype: flag.Flag
        """

        return self.get_start_flag()
