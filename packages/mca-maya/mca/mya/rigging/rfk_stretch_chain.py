"""
A reverse FK chain that can be stretched by pulling its end control away from its start.

This is ``rfk_chain`` with a squash and stretch layer on top. The controls, the aim systems and the
weighting are all the same and are built by the same functions; what this adds is:

- One free translate axis on the end control - the axis the chain runs down. Pulling the control
  away from the start lengthens the chain, pushing it in compresses it. ``RFKStretchComponent`` is
  what locks the other two axes off; this module leaves the control's channels alone.
- A no-stretch reference twin of the chain, which takes the live chain's rotations but keeps its
  rest translates. The end control's align group follows the twin's tip rather than the live
  chain's, so the animator's translate - the input to the stretch - never sits downstream of the
  stretch's own output. The live tip then lands exactly where the control was dragged to.
- A node network turning that translate into a length factor, and the length factor into a
  volume-preserving cross-section scale. ``stretch`` fades the whole thing off and ``volume`` sets
  how much the chain thins as it lengthens; both are keyable, on the end control.

Nothing here moves at rest. A factor of 1.0 writes each joint's own rest translate back to it, and a
cross-section scale of 1.0 writes nothing at all.

The one subtle piece is ``end_orient_proxy``. The end control's align group follows the reference
tip, so the align group's world matrix depends on the chain - and anything that reads the
*control's* world orientation reads its align group's world matrix with it, which closes an
evaluation cycle back through the middle joints. The aim system only ever needs the control's
rotation, so the control's local rotate channels are mirrored onto an empty sitting under a static
group built with the align group's orientation. Reading that empty gives the identical world
orientation with no cycle. It works because the align group is only ever point constrained, never
oriented, so its orientation cannot drift from the one the proxy's group was built with.

What was wrong before:

- **A chain of fewer than three joints built a divide by zero.** One joint gives a rest length of
  zero, which goes straight into the ``MultiplyDivide`` that turns an offset into a factor, and two
  controls on the same joint. Two joints build a reverse FK chain with nothing in the middle to
  distribute to. Both went through silently. A chain whose joints all sit on top of each other
  divides by zero the same way at any length, and is now caught too.
- **The chain was walked without a node type**, so anything that is not a joint sitting between the
  two ends would be counted as a middle joint and given a control.
- **The twist bias attributes were added keyable and hidden on the next line.** Nothing reads them;
  they are the build-time weights. They go on non-keyable now.
- **Renaming the sub controls threw away their wrappers**, so ``sub_flags`` came back as bare nodes
  where every other flag in the result is a ``Flag``.
- The module docstring said the end control "gets a single unlocked translate axis". Nothing in this
  module locks anything - ``RFKStretchComponent`` does the locking, from the ``stretch_axis`` this
  returns. That is written down accurately now.
- The middle-joint loop and the sub control block were the same ~150 lines as ``rfk_chain``'s,
  copied and edited in two places. They are ``rfk_chain``'s functions now. The label pattern was
  written out six times; the five units the aim locators are pushed out by and the 0.75 the subs
  are drawn at were in the arithmetic; and ``getParent()`` stood in for the align transform.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging import joint_utils
from mca.mya.rigging import rfk_chain
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import dag


logger = log.MCA_LOGGER

#: The smallest length factor the chain is allowed to reach. Unreal will not take a zero or negative
#: scale, and a chain squashed through zero turns itself inside out.
STRETCH_FACTOR_MIN = 0.05

#: The largest length factor the chain is allowed to reach, so a control dragged a long way by
#: accident does not throw the chain across the scene.
STRETCH_FACTOR_MAX = 20.0

#: The exponent the length factor is raised to at full volume. ``factor ** -0.5`` holds a
#: cylinder's volume constant, which is close enough to a limb or a spine.
VOLUME_EXPONENT = -0.5

#: Maya's ``MultiplyDivide`` operations, by what they do.
_DIVIDE = 2
_POWER = 3


def get_dominant_translate_axis(joint_node):
    """
    Which of a joint's own axes it travels down from its parent.

    :param pm.nt.Joint joint_node: The joint to look at.
    :return: The axis letter - ``x``, ``y`` or ``z`` - and the signed translate on that axis.
    :rtype: tuple(str, float)
    """

    translate_values = joint_node.translate.get()
    axis_values = {'x': translate_values[0], 'y': translate_values[1], 'z': translate_values[2]}
    # The largest offset wins. On a chain oriented the way the pipeline expects, the other two are
    # within rounding of zero.
    dominant_axis = max(axis_values, key=lambda axis_name: abs(axis_values[axis_name]))
    return dominant_axis, axis_values[dominant_axis]


def measure_chain(chain_joints):
    """
    The axes and rest lengths the stretch network scales back up from.

    Read before anything is connected, so the numbers are the chain as it was authored.

    :param list(pm.nt.Joint) chain_joints: The chain, in order.
    :return: One axis letter and one signed rest translate per joint, the total rest length of the
        chain, the axis the chain runs down and which way along it the chain travels.
    :rtype: dict
    """

    joint_axes = []
    rest_values = []
    for chain_joint in chain_joints:
        dominant_axis, rest_value = get_dominant_translate_axis(chain_joint)
        joint_axes.append(dominant_axis)
        rest_values.append(rest_value)

    # The first joint's translate is where the chain sits, not a segment of it, so whichever axis it
    # happens to be biggest on means nothing. Callers wire a per-joint scale from these axes, so
    # give it the first real segment's axis instead of a meaningless one.
    if len(joint_axes) > 1:
        joint_axes[0] = joint_axes[1]

    # Every segment but the first joint's placement.
    rest_length = sum([abs(rest_value) for rest_value in rest_values[1:]])

    return {'joint_axes': joint_axes,
            'rest_values': rest_values,
            'rest_length': rest_length,
            # The last segment's axis: the end control is oriented to the end joint, so this is the
            # axis the animator pulls on.
            'stretch_axis': joint_axes[-1],
            # Which way is longer. A mirrored chain travels down its negative axis.
            'stretch_sign': 1.0 if rest_values[-1] >= 0 else -1.0}


def build_reference_chain(chain_joints, suffix):
    """
    A twin of the chain that rotates with it but never stretches.

    It is what the end control's align group follows, so the control's translate - the input to the
    stretch - is upstream of everything the stretch drives.

    :param list(pm.nt.Joint) chain_joints: The live chain, in order.
    :param str suffix: The live chain's suffix; the twin's is this with ``_ref`` on the end.
    :return: The twin, in order.
    :rtype: list(pm.nt.Joint)
    """

    ref_chain = joint_utils.duplicate_chain(chain_joints[0], chain_joints[-1],
                                            suffix='{0}_ref'.format(suffix))

    # The tip's own rotation cannot move the tip, so leaving it unconnected costs nothing and keeps
    # the twin tip's world matrix clear of the live tip's orientation - which the end control
    # drives, and which would therefore be a cycle.
    for live_joint, ref_joint in zip(chain_joints[:-1], ref_chain[:-1]):
        live_joint.rotate >> ref_joint.rotate

    # The first joint's translate is where the chain sits rather than a segment, and the stretch
    # never touches it, so the twin can just follow it.
    chain_joints[0].translate >> ref_chain[0].translate

    return ref_chain


def build_orient_proxy(end_rotate_flag, side, region):
    """
    An empty carrying the end control's world orientation, without its align group's world matrix.

    See the note in this module's docstring: the end control's align group follows the chain, so
    reading the control itself closes a cycle. This mirrors the control's local rotate onto an empty
    under a static group built with the align group's orientation, which comes to the same world
    orientation by a route that does not touch the chain.

    :param end_rotate_flag: The control at the end of the chain.
    :param str side: Which side the chain is on, for node names.
    :param str region: The region's name, for node names.
    :return: The proxy and the group holding it. The group belongs wherever the control's align
        group goes, so the two stay in step if the rig as a whole is moved.
    :rtype: tuple
    """

    align_transform = end_rotate_flag.get_align_transform()

    proxy_group = pm.group(empty=True, n='end_orient_proxy_grp_{0}_{1}'.format(side, region))
    pm.delete(pm.parentConstraint(align_transform, proxy_group, w=True, mo=False))

    proxy = pm.group(empty=True, n='end_orient_proxy_{0}_{1}'.format(side, region))
    proxy.setParent(proxy_group, relative=True)
    proxy.rotateOrder.set(end_rotate_flag.node.rotateOrder.get())
    end_rotate_flag.node.rotate >> proxy.rotate

    proxy_group.visibility.set(False)

    return proxy, proxy_group


def build_stretch_network(end_rotate_flag, chain_joints, measurements, side, region):
    """
    The nodes turning the end control's translate into a length and a cross-section scale.

    ``factor = clamp((rest_length + pulled) / rest_length)``, blended against 1.0 by the ``stretch``
    attribute, and then multiplied into each joint's own rest translate. The cross-section scale is
    ``factor ** (VOLUME_EXPONENT * volume)``, which the caller connects to whatever it should thin:
    at ``volume`` 0 the exponent is 0 and the scale is 1, and at 1 the chain holds its volume.

    Each joint's translate is driven rather than its scale, so the chain itself stays scale free -
    which is what the engine wants, and what lets the caller drive scale from somewhere else.

    :param end_rotate_flag: The control at the end of the chain; the attributes go on it.
    :param list(pm.nt.Joint) chain_joints: The chain, in order.
    :param dict measurements: What ``measure_chain`` answered.
    :param str side: Which side the chain is on, for node names.
    :param str region: The region's name, for node names.
    :return: The nodes built, the length factor attribute and the cross-section scale attribute.
    :rtype: dict
    """

    rest_length = measurements['rest_length']
    stretch_axis = measurements['stretch_axis']
    stretch_nodes = []

    end_rotate_flag.node.addAttr('stretch', dv=1.0, min=0, max=1, keyable=True)
    end_rotate_flag.node.addAttr('volume', dv=0.5, min=0, max=1, keyable=True)

    # How far the control was pulled *along* the chain. A chain running down its negative axis is
    # lengthened by a negative translate, which is what the sign is for.
    offset_mult = pm.createNode(pm.nt.MultDoubleLinear,
                                n='stretch_offset_{0}_{1}'.format(side, region))
    end_rotate_flag.node.attr('t{0}'.format(stretch_axis)) >> offset_mult.input1
    offset_mult.input2.set(measurements['stretch_sign'])
    stretch_nodes.append(offset_mult)

    length_add = pm.createNode(pm.nt.AddDoubleLinear,
                               n='stretch_length_{0}_{1}'.format(side, region))
    offset_mult.output >> length_add.input1
    length_add.input2.set(rest_length)
    stretch_nodes.append(length_add)

    factor_div = pm.createNode(pm.nt.MultiplyDivide,
                               n='stretch_factor_{0}_{1}'.format(side, region))
    factor_div.operation.set(_DIVIDE)
    length_add.output >> factor_div.input1X
    factor_div.input2X.set(rest_length)
    stretch_nodes.append(factor_div)

    factor_clamp = pm.createNode(pm.nt.Clamp, n='stretch_clamp_{0}_{1}'.format(side, region))
    factor_clamp.minR.set(STRETCH_FACTOR_MIN)
    factor_clamp.maxR.set(STRETCH_FACTOR_MAX)
    factor_div.outputX >> factor_clamp.inputR
    stretch_nodes.append(factor_clamp)

    # Against a constant 1.0, so turning stretch off writes each joint's rest translate back rather
    # than leaving it wherever the last evaluation put it.
    stretch_blend = pm.createNode(pm.nt.BlendTwoAttr,
                                  n='stretch_blend_{0}_{1}'.format(side, region))
    stretch_blend.input[0].set(1.0)
    factor_clamp.outputR >> stretch_blend.input[1]
    end_rotate_flag.node.stretch >> stretch_blend.attributesBlender
    stretch_nodes.append(stretch_blend)

    segment_data = zip(chain_joints[1:], measurements['joint_axes'][1:],
                       measurements['rest_values'][1:])
    for chain_joint, joint_axis, rest_value in segment_data:
        segment_mult = pm.createNode(
            pm.nt.MultDoubleLinear,
            n='stretch_segment_{0}'.format(chain_joint.nodeName().split(':')[-1]))
        segment_mult.input1.set(rest_value)
        stretch_blend.output >> segment_mult.input2
        segment_mult.output >> chain_joint.attr('t{0}'.format(joint_axis))
        stretch_nodes.append(segment_mult)

    volume_mult = pm.createNode(pm.nt.MultDoubleLinear,
                                n='volume_exponent_{0}_{1}'.format(side, region))
    end_rotate_flag.node.volume >> volume_mult.input1
    volume_mult.input2.set(VOLUME_EXPONENT)
    stretch_nodes.append(volume_mult)

    volume_pow = pm.createNode(pm.nt.MultiplyDivide, n='volume_power_{0}_{1}'.format(side, region))
    volume_pow.operation.set(_POWER)
    stretch_blend.output >> volume_pow.input1X
    volume_mult.output >> volume_pow.input2X
    stretch_nodes.append(volume_pow)

    return {'stretch_nodes': stretch_nodes,
            'stretch_factor_attr': stretch_blend.output,
            'cross_scale_attr': volume_pow.outputX}


def rfk_stretch_chain(start_joint, end_joint, side, region, scale=1.0, create_sub_flags=True,
                      suffix='rfk_stretch'):
    """
    Build a reverse FK chain with squash and stretch over a run of joints.

    The chain passed in should be a throwaway duplicate; the caller constrains the bind skeleton to
    it afterwards. ``RFKStretchComponent`` is the caller in the pipeline, and it is also what locks
    the control channels off - including the two translate axes on the end control that do nothing,
    which it works out from the ``stretch_axis`` this returns.

    :param pm.nt.Joint start_joint: The first joint.
    :param pm.nt.Joint end_joint: The last one.
    :param str side: Which side the chain is on, for node names.
    :param str region: The region's name, for node names.
    :param float scale: How big to draw the controls.
    :param bool create_sub_flags: Build a smaller detail control under each end control.
    :param str suffix: A suffix to take off the control labels, usually the one the source chain was
        duplicated with.
    :return: ``rfk_chain``'s result, plus ``ref_chain`` (the no-stretch twin), ``end_orient_proxy``,
        ``stretch_nodes``, ``stretch_factor_attr`` (the length multiplier), ``cross_scale_attr``
        (the volume-preserving cross-section scale), ``stretch_axis`` and ``joint_axes`` (one axis
        letter per joint, in order). Empty when the chain cannot carry a stretch.
    :rtype: dict
    """

    start_joint = pm.PyNode(start_joint)
    end_joint = pm.PyNode(end_joint)

    # With joints asked for: anything else between the two ends is not a joint this rigs.
    chain_joints = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
    if len(chain_joints) < rfk_chain.MINIMUM_JOINTS:
        logger.warning('A reverse FK stretch chain needs at least %s joints - two ends and '
                       'something between them to distribute to. %s and %s give %s.',
                       rfk_chain.MINIMUM_JOINTS, start_joint, end_joint, len(chain_joints))
        return {}

    # Read before anything is connected: these are the lengths the stretch scales back up from.
    measurements = measure_chain(chain_joints)
    if not measurements['rest_length']:
        logger.warning('%s to %s has no length to stretch - every joint in it sits in the same '
                       'place, and the length factor would be a division by zero.',
                       start_joint, end_joint)
        return {}

    # Before the controls, so their align groups have something to follow.
    ref_chain = build_reference_chain(chain_joints, suffix)

    flags_groups = []
    start_rotate_flag = frag_flag.Flag.create_ratio(
        object_to_match=chain_joints[0], scale=scale,
        label=rfk_chain.flag_label(chain_joints[0], suffix))
    flags_groups.append(start_rotate_flag.get_align_transform())

    end_rotate_flag = frag_flag.Flag.create_ratio(
        object_to_match=chain_joints[-1], scale=scale,
        label=rfk_chain.flag_label(chain_joints[-1], suffix))
    flags_groups.append(end_rotate_flag.get_align_transform())

    # Everything downstream reads the end of the chain's orientation from here rather than from the
    # control, because the control's align group follows the chain. See this module's docstring.
    end_orient_proxy, end_orient_proxy_group = build_orient_proxy(end_rotate_flag, side, region)
    flags_groups.append(end_orient_proxy_group)

    mid_groups = []
    mid_offset_groups = []
    mid_flags = []
    weight_reverse_nodes = []
    middle_joints = chain_joints[1:-1]
    for index, mid_joint in enumerate(middle_joints):
        built = rfk_chain.build_mid_system(mid_joint, index, len(middle_joints), start_rotate_flag,
                                           end_rotate_flag, side, region, scale, suffix,
                                           end_orient_node=end_orient_proxy)
        mid_groups.append(built['mid_group'])
        mid_offset_groups.append(built['offset_group'])
        mid_flags.append(built['mid_flag'])
        weight_reverse_nodes.append(built['weight_reverse'])
        flags_groups.append(built['mid_flag'].get_align_transform())

    sub_start_flag = None
    sub_end_flag = None
    sub_start_align = None
    sub_end_align = None
    if create_sub_flags:
        sub_end_flag, sub_end_align = rfk_chain.build_sub_flag(chain_joints[-1], scale, suffix)
        sub_start_flag, sub_start_align = rfk_chain.build_sub_flag(chain_joints[0], scale, suffix)
        flags_groups.append(sub_end_align)
        flags_groups.append(sub_start_align)

    # The end control's *align group* follows the no-stretch twin's tip, where ``rfk_chain``
    # constrains the control itself. That leaves the control's own translate free for the animator
    # to pull on, and keeps that translate upstream of everything the stretch drives.
    pm.pointConstraint(ref_chain[-1], end_rotate_flag.get_align_transform(), mo=False, w=1)
    pm.pointConstraint(chain_joints[0], start_rotate_flag, mo=False, w=1)

    if create_sub_flags:
        # The subs are detail controls and ride the real, stretched tip rather than the twin's.
        pm.pointConstraint(chain_joints[-1], sub_end_align, mo=False, w=1)
        pm.pointConstraint(chain_joints[0], sub_start_align, mo=False, w=1)
        pm.orientConstraint(sub_end_flag, chain_joints[-1], mo=False, w=1)
        pm.orientConstraint(sub_start_flag, chain_joints[0], mo=False, w=1)
        pm.orientConstraint(end_orient_proxy, sub_end_align, mo=False, w=1)
        pm.orientConstraint(start_rotate_flag, sub_start_align, mo=False, w=1)
    else:
        pm.orientConstraint(end_rotate_flag, chain_joints[-1], mo=False, w=1)
        pm.orientConstraint(start_rotate_flag, chain_joints[0], mo=False, w=1)

    # Last, so everything above was snapped together with the chain at its rest length.
    stretch = build_stretch_network(end_rotate_flag, chain_joints, measurements, side, region)

    return {'start_joint': start_joint,
            'end_joint': end_joint,
            'mid_flags': mid_flags,
            'flags_groups': flags_groups,
            'mid_groups': mid_groups,
            'mid_offset_groups': mid_offset_groups,
            'start_twist_flag': start_rotate_flag,
            'end_twist_flag': end_rotate_flag,
            'sub_flags': [sub_start_flag, sub_end_flag] if create_sub_flags else [],
            'reverse_nodes': weight_reverse_nodes,
            'ref_chain': ref_chain,
            'end_orient_proxy': end_orient_proxy,
            'stretch_nodes': stretch['stretch_nodes'],
            'stretch_factor_attr': stretch['stretch_factor_attr'],
            'cross_scale_attr': stretch['cross_scale_attr'],
            'stretch_axis': measurements['stretch_axis'],
            'joint_axes': measurements['joint_axes']}
