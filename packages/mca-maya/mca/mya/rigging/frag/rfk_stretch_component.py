"""
A reverse FK chain that can be pulled longer, and gets thinner as it goes.

Everything :class:`~rfk_component.RFKComponent` is, plus a stretch: the control at the top of the
chain keeps the one translate channel that runs along it, and pulling on it lengthens the chain
while squashing its cross-section to keep the volume. ``stretch`` and ``volume`` on that control
say how much of each to apply.

The cross-section scale goes onto *leaf* joints when the caller has them - one hanging off each
chain joint - so the chain the engine exports stays scale-free, the same arrangement the spline IK
component uses. Without leaf joints it goes straight onto the bind joints. Either way the
animator's own scale on each control is multiplied into the same joint, so scaling ``f_spine_01``
scales what ``f_spine_01`` drives, on top of whatever the stretch is doing.

Everything that is only about reading a reverse chain back - its controls, its groups, being driven
by another skeleton - is on :class:`~rfk_component.ReverseChainComponent`, which this and
``RFKComponent`` share. It used to be a hundred and thirty lines written out twice; see
``rfk_component``'s module docstring for the list.

What was wrong before:

- **It is at version 2 and has no step to get there from version 1**, like
  ``twist_fixup_component``. ``FRAGNode.update`` builds the name of the step from the two version
  numbers, so a stretchy spine built by the version that wrote 1 raises ``AttributeError`` the
  moment anything asks it to update - and ``update_all_frag_nodes`` walks a whole rig. The step is
  written and records the version, which is the honest version of what happened: the number was
  raised and the step was not written.
- **A chain too short to stretch was a ``KeyError``.** ``rfk_stretch_chain`` answers ``{}`` for
  fewer than three joints, and the next line is ``chain_dict['mid_flags']`` - by which point the
  component, its groups and two duplicated chains are in the scene. Asked before anything is built.
- **``attach_to_skeleton`` required the control count and the joint count to match exactly** and
  attached nothing, silently, when they did not - the same fault as ``RFKComponent``, in the same
  words, and fixed in the one place both now read it from.
- The leaf-joint recovery - which rebuilds the leaf list by walking each chain joint's children
  when the markup has resolved badly - reported through ``logger.info`` with a pre-formatted
  string, said "extras will be skipped" in the failure case while the code goes on to use the list
  anyway, and left ``None`` in the list it built. It is its own function, it says what it found,
  and a list it cannot complete is refused rather than used with holes in it.
- ``get_flag_lock_list`` tested ``flag_node not in scale_flags`` on a list of ``Flag`` wrappers,
  which works only because ``Flag`` forwards ``__eq__`` to its node. It is clearer as the question
  it is asking: does this control drive a joint's scale.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup
from mca.mya.rigging import joint_utils
from mca.mya.rigging import rfk_chain
from mca.mya.rigging import rfk_stretch_chain
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.rigging.frag import rfk_component
from mca.mya.utils import attr_utils
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The suffix the two duplicated chains carry.
RFK_STRETCH_SUFFIX = 'rfk_stretch'

#: What this component keeps on top of what a reverse chain component keeps.
REF_CHAIN_ATTR = 'refChain'
STRETCH_NODES_ATTR = 'stretchNodes'
JOINT_SCALE_NODES_ATTR = 'jointScaleNodes'
LEAF_JOINTS_ATTR = 'leafJoints'

#: What an animator is not allowed to do to a chain control, before scale is considered. Scale is
#: decided per control: the ones that drive a joint's scale keep theirs.
BASE_LOCKED_ATTRS = ('tx', 'ty', 'tz', 'v')
SCALE_ATTRS = ('sx', 'sy', 'sz')

#: Maya's ``multiplyDivide`` operation enum for multiply.
MULTIPLY_OPERATION = 1


class RFKStretchComponent(rfk_component.ReverseChainComponent):
    """
    A reverse FK chain with squash and stretch on it.
    """

    VERSION = 2

    def _update_version_1_to_version_2(self):
        """
        Bring a version 1 component up to version 2.

        There is nothing to do. The class's version was raised to 2 and the step was never written,
        so every stretchy chain built before that raised ``AttributeError`` the moment anything
        asked it
        to update. This records the version and says why it does nothing.
        """

        self.set_version(2)

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, end_joint, side, region, scale=1.0,
               create_sub_flags=True, leaf_joint_list=None, **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The first bind joint.
        :param pm.nt.Joint end_joint: The last one.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param float scale: How big to draw the controls.
        :param bool create_sub_flags: Build a smaller detail control under each end control.
        :param leaf_joint_list: One leaf joint hanging off each chain joint, in order. The scale
            goes onto these rather than onto the bind joints, which keeps the chain the engine
            exports scale-free. None puts it on the bind joints.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: RFKStretchComponent
        :raises RuntimeError: When the run of joints is too short to distribute anything along. The
            version before got as far as building the component, its groups and two duplicated
            chains, and then raised ``KeyError`` on the empty result.
        """

        bind_joints = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
        if len(bind_joints) < rfk_chain.MINIMUM_JOINTS:
            raise RuntimeError(
                'A reverse FK stretch chain needs at least {0} joints - two ends and something '
                'between them to distribute to. {1} to {2} is {3} joints long.'.format(
                    rfk_chain.MINIMUM_JOINTS, start_joint, end_joint, len(bind_joints)))

        leaf_joint_list = resolve_leaf_joints(leaf_joint_list, bind_joints, side, region)

        build_kwargs = {'scale': scale, 'create_sub_flags': create_sub_flags}
        if leaf_joint_list:
            # The markup, not the nodes: a rebuild finds the leaf chain again by looking it up.
            leaf_markup = chain_markup.JointMarkup(leaf_joint_list[0])
            build_kwargs['leaf_region'] = leaf_markup.region
            build_kwargs['leaf_side'] = leaf_markup.side

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(
            frag_parent, RFKStretchComponent.__name__, version=RFKStretchComponent.VERSION,
            side=side, region=region, align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        duplicate_chain = joint_utils.duplicate_chain(start_joint, end_joint,
                                                      suffix=RFK_STRETCH_SUFFIX)
        built = rfk_stretch_chain.rfk_stretch_chain(
            start_joint=duplicate_chain[0], end_joint=duplicate_chain[-1], scale=scale, side=side,
            region=region, create_sub_flags=create_sub_flags, suffix=RFK_STRETCH_SUFFIX)

        component = RFKStretchComponent(node.pynode)
        component.connect_chain(built, duplicate_chain, bind_joints)

        built['ref_chain'][0].setParent(component.no_touch_grp)
        component.connect_nodes(built['ref_chain'], REF_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        component.connect_nodes(built['stretch_nodes'], STRETCH_NODES_ATTR,
                                frag_base.FRAG_PARENT_ATTR)
        if leaf_joint_list:
            component.connect_nodes(leaf_joint_list, LEAF_JOINTS_ATTR)

        scale_flags = component.wire_joint_scale(built, leaf_joint_list or bind_joints)
        component.lock_flags(built['stretch_axis'], scale_flags)

        return component

    # ----------------------------------------------------------------------------------- #
    # the stretch
    # ----------------------------------------------------------------------------------- #
    def wire_joint_scale(self, built, scale_targets):
        """
        Drive each target joint's scale from the control above it and the cross-section scale.

        Each joint's scale is the product of two things: the control's own scale channels, so an
        animator can scale one joint of a spine by hand, and the volume-preserving cross-section
        scale on the two axes across the chain. The axis *along* the chain is left at one, because
        its length comes from the stretched joint translations themselves.

        :param dict built: What ``rfk_stretch_chain`` answered.
        :param list(pm.nt.Joint) scale_targets: The joints to scale, in chain order.
        :return: The controls whose own scale is now wired to a joint, which are the ones that keep
            their scale channels.
        :rtype: list
        """

        scale_nodes = []
        scale_flags = []
        for flag_node, target_joint, joint_axis in zip(self.primary_flags, scale_targets,
                                                       built['joint_axes']):
            if not target_joint:
                continue
            scale_multiply = pm.createNode(
                pm.nt.MultiplyDivide,
                n='joint_scale_{0}'.format(target_joint.nodeName().split(':')[-1]))
            scale_multiply.operation.set(MULTIPLY_OPERATION)
            flag_node.node.scale >> scale_multiply.input1
            for axis_name in 'xyz':
                if axis_name != joint_axis:
                    built['cross_scale_attr'] >> scale_multiply.attr(
                        'input2{0}'.format(axis_name.upper()))
            scale_multiply.output >> target_joint.scale
            scale_nodes.append(scale_multiply)
            scale_flags.append(flag_node)

        if scale_nodes:
            self.connect_nodes(scale_nodes, JOINT_SCALE_NODES_ATTR, frag_base.FRAG_PARENT_ATTR)
        return scale_flags

    def lock_flags(self, stretch_axis, scale_flags):
        """
        Take away everything the animator should not touch.

        Two channels are deliberately left: the one translate axis on the top control that runs
        along the chain, which is the stretch input, and the scale on every control that drives a
        joint's
        scale.

        :param str stretch_axis: The axis letter the chain runs along.
        :param list scale_flags: The controls that drive a joint's scale.
        """

        scale_driving_nodes = [flag_node.node for flag_node in scale_flags]
        end_flag_node = self.end_flag

        for flag_node in self.get_flags():
            locked = list(BASE_LOCKED_ATTRS)
            if flag_node == end_flag_node:
                # Every translate axis except the one the chain runs along.
                locked = ['t{0}'.format(axis) for axis in 'xyz' if axis != stretch_axis] + ['v']
            if flag_node.node not in scale_driving_nodes:
                locked += list(SCALE_ATTRS)
            flag_node.lock_and_hide_attrs(locked)

    # ----------------------------------------------------------------------------------- #
    # what it keeps on top of a plain reverse chain
    # ----------------------------------------------------------------------------------- #
    @property
    def ref_chain(self):
        """
        :return: The twin of the chain that rotates with it but never stretches, which is what the
            top control's align group follows.
        :rtype: list(pm.nt.Joint)
        """

        return self.pynode.attr(REF_CHAIN_ATTR).get() or []

    @property
    def leaf_joints(self):
        """
        :return: The joints the scale is on, when the component was built with leaf joints, and an
            empty list when it puts the scale on the bind joints instead.
        :rtype: list(pm.nt.Joint)
        """

        if not self.pynode.hasAttr(LEAF_JOINTS_ATTR):
            return []
        return self.pynode.attr(LEAF_JOINTS_ATTR).get() or []

    @property
    def scale_targets(self):
        """
        :return: The joints this component scales - its leaf joints when it has them, otherwise the
            joints it drives.
        :rtype: list(pm.nt.Joint)
        """

        return self.leaf_joints or self.bind_joints

    def remove(self):
        """
        Take this component out of the rig, and put back the scale on the joints it was driving.

        The stretch network and the scale multiply nodes live outside this component's groups, so
        the base removal would leave them behind with their inputs gone - and a ``multiplyDivide``
        whose
        ``input1`` has been deleted reads zero, which would collapse every joint it drives to
        nothing. Each joint is disconnected and set back to one before anything is deleted.
        """

        for target_joint in self.scale_targets:
            if not target_joint or not pm.objExists(target_joint):
                continue
            # The compound and the three axes: this build connects the compound, and an older one
            # connected the axes one at a time.
            for attr_name in ('scale',) + SCALE_ATTRS:
                scale_attr = target_joint.attr(attr_name)
                for source in scale_attr.listConnections(source=True, destination=False,
                                                         plugs=True):
                    pm.disconnectAttr(source, scale_attr)
            target_joint.scale.set(1.0, 1.0, 1.0)

        utility_nodes = []
        for attr_name in (JOINT_SCALE_NODES_ATTR, STRETCH_NODES_ATTR):
            if self.pynode.hasAttr(attr_name):
                utility_nodes += self.pynode.attr(attr_name).listConnections()
        utility_nodes = [node for node in set(utility_nodes) if pm.objExists(node)]
        if utility_nodes:
            pm.delete(utility_nodes)

        super(RFKStretchComponent, self).remove()


def resolve_leaf_joints(leaf_joint_list, bind_joints, side, region):
    """
    One leaf joint per chain joint, recovered from the chain when the markup has not given a clean
    list.

    Marking leaf joints up one at a time gives every one of them ``chainStart`` *and* ``chainEnd``,
    which collapses the region to a single joint in ``ChainMarkup`` - so the caller's lookup comes
    back short or with duplicates in it. The chain itself still knows: each chain joint has the leaf
    hanging off it as a child. This walks that and says what it found.

    :param leaf_joint_list: What the caller found, which may be short. None means the caller is not
        using leaf joints.
    :param list(pm.nt.Joint) bind_joints: The chain joints, in order.
    :param str side: The component's side, for the message.
    :param str region: The component's region, for the message.
    :return: One leaf joint per chain joint, the caller's list when it was already right, or None
        when a complete list cannot be made - which the version before used anyway, with ``None`` in
        the holes.
    :rtype: list(pm.nt.Joint) or None
    """

    if not leaf_joint_list:
        return None
    if len(leaf_joint_list) == len(bind_joints):
        return leaf_joint_list

    leaf_markup = chain_markup.JointMarkup(leaf_joint_list[0])
    leaf_region = leaf_markup.region
    leaf_side = leaf_markup.side

    recovered = []
    for chain_joint in bind_joints:
        found = None
        for child_joint in chain_joint.getChildren(type=pm.nt.Joint):
            child_markup = chain_markup.JointMarkup(child_joint)
            if child_markup.region == leaf_region and child_markup.side == leaf_side:
                found = child_joint
                break
        recovered.append(found)

    if all(recovered):
        logger.info('%s %s: the leaf markup resolved %s of %s joints, and the full list was '
                    'recovered from the chain joints\' children. Fix the skeleton markup by '
                    'selecting every leaf joint in order and applying the markup once.',
                    side, region, len(leaf_joint_list), len(bind_joints))
        return recovered

    missing = [str(bind_joints[index]) for index, leaf in enumerate(recovered) if leaf is None]
    logger.warning('%s %s: %s of %s chain joints have no %s %s leaf under them (%s), so the scale '
                   'goes on the bind joints instead of on leaves.', side, region, len(missing),
                   len(bind_joints), leaf_side, leaf_region, ', '.join(missing))
    return None
