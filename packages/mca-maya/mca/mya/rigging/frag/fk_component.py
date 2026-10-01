"""
The component that drives a limb from its root: one control per joint, nested so that turning a
shoulder carries the elbow and the wrist with it.

The plainest component there is, and the one most of a character is made of - spines, fingers,
tails, ears. As with the IK component, the controls drive a duplicate of the bind chain and the
bind joints are constrained to the duplicate, so the rig can be rebuilt without the skeleton being
touched. What the controls are constrained to the joints *with* is the component's own choice:
translate, rotate, scale or any combination, which is what lets one component rig a spine that
stretches and another a finger that only bends.

What was wrong before:

- **A rebuilt component silently lost its scale setting.** ``create`` takes ``constrain_scale`` and
  wrote it down as ``allow_scale``, so a rebuild handing the recorded arguments back got
  ``allow_scale=True`` - which the signature has no parameter for, so it landed in the ``**kwargs``
  the signature absorbs and was dropped. Every rebuilt stretchy component came back unable to
  stretch. It is recorded under the name the parameter has; :meth:`set_scale` reads either name, so
  components built before this still answer.
- **A rebuilt component drew default-sized controls.** ``scale`` was never written down at all.
- **``offset_flag=True`` had never worked.** ``create`` added ``offsetFlag`` as a plain message
  attribute and then wired the flag to it with ``connect_nodes``, which hands a *list* to a
  non-multi attribute: ``RuntimeError (kFailure): Object does not exist``, every time, for as long
  as the argument has existed. The pre-add is gone - :meth:`FRAGNode.connect_node` makes the
  attribute it needs - and the single node goes through ``connect_node``.
- **``set_scale`` raised on a rig with no scale attribute.** It reads ``frag_rig.pynode.rigScale``
  without asking. Reading :attr:`FRAGRig.rig_scale` used to add the attribute as a side effect of
  being read, which hid this; now that it does not, the component says what is missing and leaves
  the group alone. :meth:`FRAGRig.add_rig_scale` is what wires the attribute, and it calls
  ``set_scale`` on every component afterwards.
- **``attach_to_skeleton`` attached nothing, silently, when the rig had more controls than the
  skeleton had joints.** ``if flag_list and len(flag_list) <= len(joint_list)`` - so a four-control
  spine driven by a three-joint markup chain came back with an empty list and no complaint. The
  controls and joints are paired as far as the shorter of the two goes, and the mismatch is
  reported.
- ``set_scale`` looked its shared divide node up with ``pm.ls(..., r=True)``, a search through every
  namespace, under the name ``'<namespace>::rig_scale_multi'`` with the colon doubled. One rig's
  component could find another rig's node. The lookup is the namespace's own now.
- ``get_offset_flag`` promised a :class:`Flag` and returned the raw node. ``for x in
  range(len(ctrls))`` with ``if x == 0 / elif x > 0`` is ``enumerate``.

A decision left as it was: **:meth:`get_start_flag` returns the last control and
:meth:`get_end_flag` the first.** ``fk_chain`` builds its ``flags`` list root first, so the two are
the wrong way round - but around twenty callers in the rig templates have been written against the
behaviour rather than the names, and swapping them would quietly move every one of those rigs. The
docstrings say what each one actually returns and the rename is on the list to do with the templates
in front of us.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import fk_chain
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import frag_rig
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The suffix the duplicated chain the controls drive carries.
FK_CHAIN_SUFFIX = 'fk_chain'

#: What the component keeps its pieces on.
FK_FLAGS_ATTR = 'fkFlags'
FK_CHAIN_ATTR = 'chainFk'
OFFSET_FLAG_ATTR = 'offsetFlag'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: The name of the divide node a rig's components share to hold themselves at a constant size while
#: the rig around them is scaled.
RIG_SCALE_MULTI_NAME = 'rig_scale_multi'

#: Maya's ``multiplyDivide`` operation enum for divide.
DIVIDE_OPERATION = 2

#: ``buildKwargs_allow_scale`` is what components built before the name was corrected hold the scale
#: setting under.
LEGACY_SCALE_KWARG = 'buildKwargs_allow_scale'


class FKComponent(keyable_component.KeyableComponent):
    """
    One run of joints driven by a nested chain of controls.
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
               flag_group_pivot=None,
               lock_child_rotate_axes=(),
               lock_child_translate_axes=attr_utils.TRANSLATION_ATTRS,
               lock_child_scale_axes=attr_utils.SCALE_ATTRS,
               lock_root_rotate_axes=(),
               lock_root_translate_axes=attr_utils.TRANSLATION_ATTRS,
               lock_root_scale_axes=attr_utils.SCALE_ATTRS,
               children_align_transforms=True,
               constrain_translate=True,
               constrain_rotate=True,
               constrain_scale=False,
               offset_flag=False,
               **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The first bind joint.
        :param pm.nt.Joint end_joint: The last one.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param float scale: How big to draw the controls.
        :param pm.nt.DagNode flag_group_pivot: Snap the control group to this before anything is
            parented into it.
        :param lock_child_rotate_axes: Rotate channels to lock on every control but the first.
        :param lock_child_translate_axes: Translate channels to lock on every control but the first.
        :param lock_child_scale_axes: Scale channels to lock on every control but the first.
        :param lock_root_rotate_axes: Rotate channels to lock on the first control.
        :param lock_root_translate_axes: Translate channels to lock on the first control.
        :param lock_root_scale_axes: Scale channels to lock on the first control.
        :param bool children_align_transforms: Give every control but the first a zeroed group above
            it.
        :param bool constrain_translate: Carry the controls' position onto the bind joints.
        :param bool constrain_rotate: Carry their rotation onto the bind joints.
        :param bool constrain_scale: Carry their scale onto the bind joints, and hold the component
            at a constant size as the rig is scaled.
        :param bool offset_flag: Build a second, smaller control under the last one.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: FKComponent
        """

        # What a rebuild needs to come back the same. Each key is the name of the parameter it goes
        # back in through - the scale setting went in as allow_scale, which is not a parameter, so
        # it was dropped on the way back and every rebuilt stretchy component stopped stretching.
        build_kwargs = {'scale': scale,
                        'flag_group_pivot': flag_group_pivot.name() if flag_group_pivot else None,
                        'lock_child_rotate_axes': lock_child_rotate_axes,
                        'lock_child_translate_axes': lock_child_translate_axes,
                        'lock_child_scale_axes': lock_child_scale_axes,
                        'lock_root_rotate_axes': lock_root_rotate_axes,
                        'lock_root_translate_axes': lock_root_translate_axes,
                        'lock_root_scale_axes': lock_root_scale_axes,
                        'children_align_transforms': children_align_transforms,
                        'constrain_translate': constrain_translate,
                        'constrain_rotate': constrain_rotate,
                        'constrain_scale': constrain_scale,
                        'offset_flag': offset_flag}

        lock_child_rotate_axes = list(lock_child_rotate_axes)
        lock_child_translate_axes = list(lock_child_translate_axes)
        lock_child_scale_axes = list(lock_child_scale_axes)
        lock_root_rotate_axes = list(lock_root_rotate_axes)
        lock_root_translate_axes = list(lock_root_translate_axes)
        lock_root_scale_axes = list(lock_root_scale_axes)

        chain_between = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        FKComponent.__name__,
                                                        FKComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        flag_grp = node.flag_group
        nt_grp = node.no_touch_grp

        if pm.xform(start_joint, q=True, ws=True, t=True)[0] < 0:
            # Maya resolves a multi-parent attachment oddly for a group left at the origin while the
            # joints it holds controls for are in -X; aligning the group to the joint avoids it.
            pm.delete(constraint.parent_constraint_safe(start_joint, flag_grp))
        if flag_group_pivot:
            pm.delete(pm.parentConstraint(flag_group_pivot, flag_grp, w=True, mo=False))

        # The animator drives a copy and the bind joints follow it.
        chain_fk = joint_utils.duplicate_chain(start_joint, end_joint, suffix=FK_CHAIN_SUFFIX)
        chain_fk[0].setParent(nt_grp)
        built = fk_chain.fk_joint_chain(chain_fk[0],
                                        chain_fk[-1],
                                        scale=scale,
                                        children_align_transforms=children_align_transforms,
                                        create_end_flag=True,
                                        offset_flag=offset_flag,
                                        use_scale=constrain_scale,
                                        suffix=FK_CHAIN_SUFFIX)

        flag_list = built['flags']
        new_offset_flag = built['offset_flag']
        if new_offset_flag:
            new_offset_flag.lock_and_hide_attrs(['v'] + lock_child_translate_axes
                                                + lock_child_rotate_axes + lock_child_scale_axes)
            # connect_node makes the message attribute it needs. The version before added
            # offsetFlag by hand and then wired it with connect_nodes, which hands a list to a
            # non-multi attribute - so passing offset_flag=True had never once worked.
            node.connect_node(new_offset_flag, OFFSET_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)

        root_align_transform = flag_list[0].get_align_transform()
        (root_align_transform or flag_list[0]).setParent(flag_grp)

        node.connect_nodes(flag_list, FK_FLAGS_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(chain_fk, FK_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(chain_between, BIND_JOINTS_ATTR)

        for index, flag_node in enumerate(flag_list):
            if index:
                locked_attrs = (lock_child_rotate_axes + lock_child_translate_axes
                                + lock_child_scale_axes)
            else:
                locked_attrs = (lock_root_rotate_axes + lock_root_translate_axes
                                + lock_root_scale_axes)
            flag_node.lock_and_hide_attrs(['v'] + locked_attrs)

        for driver_joint, bind_joint in zip(built['chain'], chain_between):
            if constrain_translate and constrain_rotate:
                pm.parentConstraint(driver_joint, bind_joint)
            elif constrain_translate:
                pm.pointConstraint(driver_joint, bind_joint)
            elif constrain_rotate:
                pm.orientConstraint(driver_joint, bind_joint)
            if constrain_scale:
                # A direct connection rather than a scale constraint: it handles a scaled parent,
                # which is exactly the case a stretchy component is built for.
                driver_joint.scale >> bind_joint.scale

        node.set_scale()

        return node

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        :return: This component's controls, root first.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(node) for node
                in self.pynode.attr(FK_FLAGS_ATTR).listConnections()]

    def get_start_flag(self):
        """
        The **last** control, at the far end of the chain from the root.

        The name is wrong and is kept that way on purpose: ``fk_chain`` builds its control list root
        first, so this has always answered the end of the chain, and the rig templates calling it
        were written against what it does rather than what it is called. See this module's
        docstring.

        :return: The last control.
        :rtype: frag_flag.Flag
        """

        return self.get_flags()[-1]

    def get_end_flag(self):
        """
        The **first** control, at the root of the chain.

        Wrong name, kept deliberately - see :meth:`get_start_flag`.

        :return: The first control.
        :rtype: frag_flag.Flag
        """

        return self.get_flags()[0]

    def get_offset_flag(self):
        """
        :return: The detail control under the last one, or None when the component was built without
            one. The version before promised a ``Flag`` here and handed back the raw node.
        :rtype: frag_flag.Flag or None
        """

        if not self.pynode.hasAttr(OFFSET_FLAG_ATTR):
            return None
        offset_flag_node = self.pynode.attr(OFFSET_FLAG_ATTR).get()
        if not offset_flag_node:
            return None
        return frag_flag.Flag(offset_flag_node)

    def select_flags(self):
        """
        Select every control this component owns.
        """

        pm.select(self.get_flags())

    def key_flags(self):
        """
        Set a key on every control this component owns.
        """

        pm.setKeyframe(self.get_flags())

    def to_default_pose(self):
        """
        Put every control back where it was built.
        """

        for flag_node in self.get_flags():
            attr_utils.reset_attrs(flag_node.node)

    # ----------------------------------------------------------------------------------- #
    # the rig's scale
    # ----------------------------------------------------------------------------------- #
    @ma_decorators.keep_namespace_decorator
    def set_scale(self):
        """
        Hold this component at a constant size while the rig around it is scaled.

        A component built to carry scale onto its joints has to be kept out of the rig's own scale,
        or the two multiply: so the group its driver chain lives in is scaled by one over the rig's
        scale, through a divide node the rig's components share.

        Does nothing for a component not built to carry scale, and nothing - with a warning - for a
        rig with no scale attribute to read. The version before read ``rigScale`` without asking;
        that used to be hidden by :attr:`FRAGRig.rig_scale` adding the attribute as a side effect of
        being read, which it no longer does.
        """

        constrain_scale = self.get_attr_with_legacy_name(
            '{0}_constrain_scale'.format(frag_base.BUILD_KWARGS_ATTR), LEGACY_SCALE_KWARG)
        if not constrain_scale:
            return

        rig = self.get_frag_parent()
        if rig is None or not rig.has_attribute(frag_rig.RIG_SCALE_ATTR):
            logger.warning('%s is built to carry scale, but %s has no %s to read, so its scale is '
                           'not wired. FRAGRig.add_rig_scale() is what adds it.', self.pynode,
                           rig.pynode if rig else 'the rig above it', frag_rig.RIG_SCALE_ATTR)
            return

        rig_namespace = self.pynode.namespace()
        namespace.set_namespace(rig_namespace, check_existing=False)

        # This namespace's node, not a recursive search under a name with the colon doubled - that
        # let one rig's component find another rig's divide node.
        multi_node = lists.get_first_in_list(
            pm.ls('{0}{1}'.format(rig_namespace, RIG_SCALE_MULTI_NAME), type=pm.nt.MultiplyDivide))
        if not multi_node:
            multi_node = pm.createNode(pm.nt.MultiplyDivide, n=RIG_SCALE_MULTI_NAME)

        multi_node.input1X.set(1)
        multi_node.operation.set(DIVIDE_OPERATION)
        multi_node.input2X.disconnect()
        rig.pynode.attr(frag_rig.RIG_SCALE_ATTR) >> multi_node.input2X

        nt_grp = self.no_touch_grp
        for axis in attr_utils.SCALE_ATTRS:
            nt_grp.attr(axis).disconnect()
            nt_grp.attr(axis).unlock()
            multi_node.outputX >> nt_grp.attr(axis)

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
        if not joint_list:
            return []

        flag_list = self.get_flags()
        if len(flag_list) > len(joint_list):
            # The version before attached nothing at all in this case, and said nothing about it.
            logger.warning('%s has %s controls and %s %s on the skeleton has only %s joints, so '
                           'the last %s are not driven.', self.pynode, len(flag_list), self.side,
                           self.region, len(joint_list), len(flag_list) - len(joint_list))

        constraint_list = []
        for flag_node, joint_node in zip(flag_list, joint_list):
            constraint_node = constraint.parent_constraint_safe(joint_node, flag_node, mo=mo)
            if constraint_node:
                constraint_list.append(constraint_node)
            for axis in attr_utils.SCALE_ATTRS:
                if flag_node.node.attr(axis).isSettable():
                    joint_node.attr(axis) >> flag_node.node.attr(axis)
        return constraint_list
