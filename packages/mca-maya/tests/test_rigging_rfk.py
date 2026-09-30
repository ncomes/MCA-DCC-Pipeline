"""
The reverse FK chain and its stretching variant, in a real Maya.

    mayapy tests/test_rigging_rfk.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _spine(pm, count=5, suffix='rfk_chain'):
    """A chain of joints up Y, named as a duplicated rfk chain would be."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    return [pm.PyNode(cmds.joint(name='b_spine_{0:02d}_{1}'.format(index, suffix) if suffix
                                 else 'b_spine_{0:02d}'.format(index),
                                 position=(0, index * 6, 0), absolute=True))
            for index in range(count)]


def _stack(pm, count=4, suffix='rfk_stretch'):
    """A chain of joints all in the same place, so it has no length to stretch."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    return [pm.PyNode(cmds.joint(name='b_stack_{0:02d}_{1}'.format(index, suffix),
                                 position=(0, 0, 0), absolute=True))
            for index in range(count)]


def check_rfk_chain(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import rfk_chain
    from mca.mya.rigging.flags import frag_flag

    # -- too short ------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=2)
    suite.check('a chain of two joints has no middle to distribute to, and is turned away',
                rfk_chain.rfk_chain(joints[0], joints[-1], 'center', 'spine') == {})
    harness.new_scene()
    joints = _spine(pm, count=1)
    suite.check('and neither has a chain of one',
                rfk_chain.rfk_chain(joints[0], joints[0], 'center', 'spine') == {})

    # -- a real chain ----------------------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=5)
    result = rfk_chain.rfk_chain(joints[0], joints[-1], 'center', 'spine')

    suite.check('a reverse FK chain is built', bool(result))
    suite.check('with a control at each end',
                result['start_twist_flag'] is not None and result['end_twist_flag'] is not None)
    suite.check('named after their joints, with the chain suffix taken off',
                str(result['start_twist_flag']) == 'f_spine_00', str(result['start_twist_flag']))
    suite.check('and one control per middle joint',
                len(result['mid_flags']) == 3, str(result['mid_flags']))
    suite.check('a group each', len(result['mid_groups']) == 3 and
                len(result['mid_offset_groups']) == 3)
    suite.check('and a reverse node each', len(result['reverse_nodes']) == 3)

    # -- the bias: the bug in the docstrings ------------------------------------------------- #
    end_flag = result['end_twist_flag'].node
    bias_names = ['twist_bias_{0}'.format(index) for index in (1, 2, 3)]
    suite.check('a bias is stored per middle joint',
                all(end_flag.hasAttr(name) for name in bias_names))
    # Both docstrings said these were keyable and exposed. They are not, and nothing reads them.
    suite.check('and it is not keyable - it is a build time value, not something to animate',
                not any(end_flag.attr(name).isKeyable() for name in bias_names))
    suite.check('nor in the channel box',
                not any(end_flag.attr(name).isInChannelBox() for name in bias_names))

    biases = [end_flag.attr(name).get() for name in bias_names]
    suite.check('the biases rise along the chain, so each joint follows its nearer control',
                biases[0] < biases[1] < biases[2], str(biases))
    suite.check('the middle one splits the difference',
                abs(biases[1] - 0.5) < 0.001, str(biases[1]))
    suite.check('and they are all between nought and one',
                all(0 <= bias <= 1 for bias in biases), str(biases))

    # -- the aim systems ----------------------------------------------------------------------- #
    # type=transform: a locator's shape matches the same wildcard.
    suite.check('each middle joint has a pair of aim locators per end control',
                len(cmds.ls('start_flag_aim_x_*', type='transform') or []) == 3 and
                len(cmds.ls('end_flag_aim_x_*', type='transform') or []) == 3,
                str(cmds.ls('*_flag_aim_x_*', type='transform')))
    # The constraint nodes are parented under the locators, so they match the wildcard too.
    averaged = [str(node) for node in pm.ls('aim_?_locator_*', type='transform')
                if isinstance(node.getShape(), pm.nt.Locator)]
    suite.check('and an averaged aim and up locator of its own',
                len(averaged) == 6, str(averaged))
    suite.check('the averaging is by weight, from the bias and its reverse',
                all(bool(alias.listConnections(source=True, destination=False))
                    for constraint in pm.ls(type=pm.nt.PointConstraint)
                    for alias in constraint.getWeightAliasList()
                    if len(constraint.getWeightAliasList()) == 2),
                'some averaged constraint weight is not driven')

    # -- what the controls do ------------------------------------------------------------------- #
    before = [joint.rotateY.get() for joint in joints[1:-1]]
    result['end_twist_flag'].node.rotateY.set(60)
    pm.dgdirty(allPlugs=True)
    after = [joint.rotateY.get() for joint in joints[1:-1]]
    suite.check('turning the end control turns the middle joints',
                any(abs(now - was) > 1 for now, was in zip(after, before)), str(after))
    suite.check('the one nearest the end more than the one nearest the start',
                abs(after[-1] - before[-1]) > abs(after[0] - before[0]),
                '{0} against {1}'.format(after, before))
    result['end_twist_flag'].node.rotateY.set(0)

    # -- the sub controls ---------------------------------------------------------------------- #
    sub_start, sub_end = result['sub_flags']
    suite.check('a sub control is built at each end', sub_start is not None and sub_end is not None)
    suite.check('named with a _sub suffix',
                str(sub_end).endswith('_sub'), str(sub_end))
    # The bug: pm.rename's answer was rebound over the wrapper, so these came back as bare nodes.
    suite.check('and they come back as flags, like every other control in the result',
                hasattr(sub_start, 'node') and hasattr(sub_end, 'node'))
    suite.check('marked as detail and sub controls',
                sub_end.node.isDetail.get() is True and sub_end.node.isSub.get() is True)
    suite.check('drawn smaller than the control above them',
                sub_end.node.getShape().getCVs()[0][0] <
                result['end_twist_flag'].node.getShape().getCVs()[0][0])
    suite.check('the end joint takes its rotation from the sub control',
                sub_end.node in
                [target for constraint in
                 set(joints[-1].listConnections(type=pm.nt.OrientConstraint))
                 for target in pm.orientConstraint(constraint, query=True, targetList=True)],
                str([pm.orientConstraint(constraint, query=True, targetList=True)
                     for constraint in set(joints[-1].listConnections(
                         type=pm.nt.OrientConstraint))]))

    # -- without them ---------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=4)
    result = rfk_chain.rfk_chain(joints[0], joints[-1], 'center', 'spine', create_sub_flags=False)
    suite.check('a chain can be built without sub controls', result['sub_flags'] == [])
    suite.check('and the end joint takes its rotation straight from the end control',
                result['end_twist_flag'].node in
                [target for constraint in
                 set(joints[-1].listConnections(type=pm.nt.OrientConstraint))
                 for target in pm.orientConstraint(constraint, query=True, targetList=True)],
                str([pm.orientConstraint(constraint, query=True, targetList=True)
                     for constraint in set(joints[-1].listConnections(
                         type=pm.nt.OrientConstraint))]))
    suite.check('with a control group per flag built',
                len(result['flags_groups']) == 2 + len(result['mid_flags']),
                str(result['flags_groups']))

    # -- labels ---------------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=4, suffix='')
    result = rfk_chain.rfk_chain(joints[0], joints[-1], 'center', 'spine', suffix='')
    # The same fault reverse_chain had: '_' + '' is '_', and replacing that takes every underscore
    # out of the name.
    suite.check('an empty suffix leaves the underscores in the label',
                str(result['start_twist_flag']) == 'f_spine_00',
                str(result['start_twist_flag']))

    # -- a non-joint between the ends ---------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=4)
    # A group in the middle of the chain: the walk used to count it as a middle joint and give it a
    # control, because it asked for no node type.
    spacer = pm.group(empty=True, name='a_spacer')
    pm.parent(spacer, joints[1])
    pm.parent(joints[2], spacer)
    result = rfk_chain.rfk_chain(joints[0], joints[-1], 'center', 'spine')
    suite.check('something in the chain that is not a joint is not given a control',
                len(result['mid_flags']) == 2, str(result['mid_flags']))


def check_rfk_stretch_chain(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import rfk_stretch_chain

    # -- what it will not build on ------------------------------------------------------------ #
    harness.new_scene()
    joints = _spine(pm, count=2, suffix='rfk_stretch')
    suite.check('a chain of two joints has no middle to distribute to, and is turned away',
                rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'spine') == {})
    harness.new_scene()
    joints = _spine(pm, count=1, suffix='rfk_stretch')
    suite.check('and neither has a chain of one - its rest length is nought, which is what the '
                'length factor used to divide by',
                rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[0], 'center', 'spine') == {})
    harness.new_scene()
    joints = _stack(pm, count=4)
    suite.check('a chain whose joints all sit in the same place is turned away for the same reason',
                rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'spine') == {})

    # -- what it measures ---------------------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=5, suffix='rfk_stretch')
    axis, value = rfk_stretch_chain.get_dominant_translate_axis(joints[1])
    suite.check('a joint travels down the axis it is furthest along',
                axis == 'y' and abs(value - 6.0) < 0.0001, '{0} {1}'.format(axis, value))
    measured = rfk_stretch_chain.measure_chain(joints)
    suite.check('the chain measures the sum of its segments, and not its placement',
                abs(measured['rest_length'] - 24.0) < 0.0001, str(measured['rest_length']))
    suite.check('the stretch axis is the last segment\'s',
                measured['stretch_axis'] == 'y', measured['stretch_axis'])
    suite.check('the sign says which way along it the chain travels',
                measured['stretch_sign'] == 1.0, str(measured['stretch_sign']))
    suite.check('the first joint borrows the first real segment\'s axis, since its own '
                'translate is where the chain sits rather than a length',
                measured['joint_axes'][0] == measured['joint_axes'][1],
                str(measured['joint_axes']))

    # -- a real chain -------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=5, suffix='rfk_stretch')
    result = rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'spine')
    end_flag = result['end_twist_flag']

    suite.check('a stretching reverse FK chain is built', bool(result))
    suite.check('with a control at each end and one per middle joint',
                len(result['mid_flags']) == 3 and result['start_twist_flag'] is not None
                and end_flag is not None)
    suite.check('named after their joints, with the chain suffix taken off',
                str(result['start_twist_flag']) == 'f_spine_00', str(result['start_twist_flag']))
    suite.check('one axis letter per joint comes back for the caller to wire a scale from',
                result['joint_axes'] == ['y'] * 5, str(result['joint_axes']))

    # -- the no-stretch twin ------------------------------------------------------------------- #
    ref_chain = result['ref_chain']
    suite.check('a twin of the chain is built', len(ref_chain) == len(joints))
    suite.check('named apart from it', all('_ref' in str(node) for node in ref_chain),
                str(ref_chain))
    suite.check('it takes the live chain\'s rotations',
                all(live in ref.rotate.listConnections(source=True, destination=False)
                    for live, ref in zip(joints[:-1], ref_chain[:-1])))
    # The tip's own rotation cannot move the tip, and connecting it would put the end control's
    # orientation into the twin's world matrix - which is the cycle this module is built around.
    suite.check('but not the tip\'s, which would put the end control back into the twin',
                not ref_chain[-1].rotate.listConnections(source=True, destination=False))
    suite.check('and it keeps its rest lengths, so it is the chain unstretched',
                not ref_chain[-1].translateY.listConnections(source=True, destination=False)
                and abs(ref_chain[-1].translateY.get() - 6.0) < 0.0001)
    suite.check('where the chain sits is shared, since the stretch never touches it',
                joints[0] in ref_chain[0].translate.listConnections(source=True, destination=False))

    # -- the orientation proxy ----------------------------------------------------------------- #
    proxy = result['end_orient_proxy']
    suite.check('an orientation proxy is built for the end control', proxy is not None)
    suite.check('hidden, since it is not for the animator',
                proxy.getParent().visibility.get() is False)
    end_flag.node.rotateZ.set(35)
    pm.dgdirty(allPlugs=True)
    flag_world = end_flag.node.getRotation(space='world')
    proxy_world = proxy.getRotation(space='world')
    suite.check('and it carries the control\'s world orientation exactly',
                all(abs(one - other) < 0.001 for one, other in zip(flag_world, proxy_world)),
                '{0} against {1}'.format(flag_world, proxy_world))
    end_flag.node.rotateZ.set(0)
    pm.dgdirty(allPlugs=True)

    # -- no cycle ------------------------------------------------------------------------------ #
    # The whole shape of this module - the twin, the proxy, the align group being what follows the
    # twin - is there to keep the graph acyclic. Maya is the only thing that can say if it does.
    suite.check('the rig Maya is left with has no evaluation cycle in it',
                not cmds.cycleCheck(all=True))

    # -- where the control is free ------------------------------------------------------------- #
    align_transform = end_flag.get_align_transform()
    suite.check('the end control\'s align group follows the twin\'s tip',
                ref_chain[-1] in [target for constraint in
                                  set(align_transform.listConnections(type=pm.nt.PointConstraint))
                                  for target in pm.pointConstraint(constraint, query=True,
                                                                   targetList=True)],
                str(align_transform.listConnections(type=pm.nt.PointConstraint)))
    # rfk_chain constrains the control itself, which would leave nothing for the animator to pull.
    suite.check('and the control itself is left free to be pulled',
                not end_flag.node.translateY.listConnections(source=True, destination=False))

    # -- the attributes the animator gets ------------------------------------------------------ #
    suite.check('the end control carries a stretch and a volume attribute',
                end_flag.node.hasAttr('stretch') and end_flag.node.hasAttr('volume'))
    suite.check('both keyable, unlike the twist biases',
                end_flag.node.stretch.isKeyable() and end_flag.node.volume.isKeyable())
    suite.check('stretch is on to start with',
                abs(end_flag.node.stretch.get() - 1.0) < 0.0001)
    suite.check('and volume is half on',
                abs(end_flag.node.volume.get() - 0.5) < 0.0001)
    suite.check('the stretch axis comes back for the caller to lock the other two off',
                result['stretch_axis'] == 'y', result['stretch_axis'])

    # -- at rest ------------------------------------------------------------------------------- #
    suite.check('at rest the length factor is one',
                abs(result['stretch_factor_attr'].get() - 1.0) < 0.0001,
                str(result['stretch_factor_attr'].get()))
    suite.check('the cross-section scale is one',
                abs(result['cross_scale_attr'].get() - 1.0) < 0.0001,
                str(result['cross_scale_attr'].get()))
    suite.check('and every joint sits at its own rest length',
                all(abs(joint.translateY.get() - 6.0) < 0.0001 for joint in joints[1:]),
                str([joint.translateY.get() for joint in joints[1:]]))

    # -- pulled ------------------------------------------------------------------------------- #
    end_flag.node.translateY.set(12)
    pm.dgdirty(allPlugs=True)
    suite.check('pulling the control half the chain\'s length away gives a factor of one and '
                'a half',
                abs(result['stretch_factor_attr'].get() - 1.5) < 0.0001,
                str(result['stretch_factor_attr'].get()))
    suite.check('every segment lengthens by that much',
                all(abs(joint.translateY.get() - 9.0) < 0.0001 for joint in joints[1:]),
                str([joint.translateY.get() for joint in joints[1:]]))
    tip_world = joints[-1].getTranslation(space='world')[1]
    flag_world_y = end_flag.node.getTranslation(space='world')[1]
    suite.check('and the chain\'s tip lands exactly where the control was dragged to',
                abs(tip_world - flag_world_y) < 0.0001 and abs(tip_world - 36.0) < 0.0001,
                '{0} against {1}'.format(tip_world, flag_world_y))
    suite.check('the twin stays at the chain\'s rest length underneath it all',
                abs(ref_chain[-1].getTranslation(space='world')[1] - 24.0) < 0.0001,
                str(ref_chain[-1].getTranslation(space='world')))

    # -- volume ------------------------------------------------------------------------------- #
    suite.check('half volume thins the chain by the square root of the square root',
                abs(result['cross_scale_attr'].get() - 1.5 ** -0.25) < 0.0001,
                str(result['cross_scale_attr'].get()))
    end_flag.node.volume.set(1)
    pm.dgdirty(allPlugs=True)
    suite.check('full volume holds the chain\'s volume, thinning it by the square root',
                abs(result['cross_scale_attr'].get() - 1.5 ** -0.5) < 0.0001,
                str(result['cross_scale_attr'].get()))
    end_flag.node.volume.set(0)
    pm.dgdirty(allPlugs=True)
    suite.check('no volume leaves the cross-section alone however far the chain is stretched',
                abs(result['cross_scale_attr'].get() - 1.0) < 0.0001,
                str(result['cross_scale_attr'].get()))
    end_flag.node.volume.set(0.5)

    # -- squashed, and turned off -------------------------------------------------------------- #
    end_flag.node.translateY.set(-12)
    pm.dgdirty(allPlugs=True)
    suite.check('pushing the control in halves the chain',
                abs(result['stretch_factor_attr'].get() - 0.5) < 0.0001 and
                all(abs(joint.translateY.get() - 3.0) < 0.0001 for joint in joints[1:]),
                str(result['stretch_factor_attr'].get()))
    suite.check('and the cross-section fattens',
                result['cross_scale_attr'].get() > 1.0, str(result['cross_scale_attr'].get()))
    end_flag.node.stretch.set(0)
    pm.dgdirty(allPlugs=True)
    suite.check('turning the stretch off puts every joint back at its rest length, rather than '
                'leaving it wherever the last evaluation put it',
                abs(result['stretch_factor_attr'].get() - 1.0) < 0.0001 and
                all(abs(joint.translateY.get() - 6.0) < 0.0001 for joint in joints[1:]),
                str([joint.translateY.get() for joint in joints[1:]]))
    end_flag.node.stretch.set(1)

    # -- the clamps ---------------------------------------------------------------------------- #
    end_flag.node.translateY.set(-1000)
    pm.dgdirty(allPlugs=True)
    suite.check('a control pushed through the start of the chain clamps rather than turning the '
                'chain inside out',
                abs(result['stretch_factor_attr'].get() - rfk_stretch_chain.STRETCH_FACTOR_MIN)
                < 0.0001, str(result['stretch_factor_attr'].get()))
    end_flag.node.translateY.set(100000)
    pm.dgdirty(allPlugs=True)
    suite.check('and one dragged off into the distance clamps too',
                abs(result['stretch_factor_attr'].get() - rfk_stretch_chain.STRETCH_FACTOR_MAX)
                < 0.0001, str(result['stretch_factor_attr'].get()))
    end_flag.node.translateY.set(0)

    # -- the sub controls ---------------------------------------------------------------------- #
    sub_start, sub_end = result['sub_flags']
    suite.check('a sub control is built at each end',
                sub_start is not None and sub_end is not None)
    # The bug: pm.rename's answer was rebound over the wrapper, so these came back as bare nodes
    # where every other control in the result is a Flag.
    suite.check('and they come back as flags, like every other control in the result',
                hasattr(sub_start, 'node') and hasattr(sub_end, 'node'))
    suite.check('named with a _sub suffix', str(sub_end).endswith('_sub'), str(sub_end))
    suite.check('the subs ride the real, stretched tip rather than the twin\'s',
                joints[-1] in [target for constraint in
                               set(sub_end.get_align_transform().listConnections(
                                   type=pm.nt.PointConstraint))
                               for target in pm.pointConstraint(constraint, query=True,
                                                                targetList=True)])

    # -- a chain the other way up -------------------------------------------------------------- #
    harness.new_scene()
    cmds.select(clear=True)
    joints = [pm.PyNode(cmds.joint(name='b_tail_{0:02d}_rfk_stretch'.format(index),
                                   position=(0, index * -6, 0), absolute=True))
              for index in range(5)]
    result = rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'tail')
    end_flag = result['end_twist_flag']
    suite.check('a chain travelling down its negative axis is measured as travelling that way',
                abs(result['stretch_factor_attr'].get() - 1.0) < 0.0001)
    end_flag.node.translateY.set(-12)
    pm.dgdirty(allPlugs=True)
    suite.check('so pulling its control the way the chain runs lengthens it, rather than '
                'squashing it',
                abs(result['stretch_factor_attr'].get() - 1.5) < 0.0001,
                str(result['stretch_factor_attr'].get()))
    suite.check('and its tip still lands where the control was dragged to',
                abs(joints[-1].getTranslation(space='world')[1] + 36.0) < 0.0001,
                str(joints[-1].getTranslation(space='world')))

    # -- without sub controls ------------------------------------------------------------------ #
    harness.new_scene()
    joints = _spine(pm, count=4, suffix='rfk_stretch')
    result = rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'spine',
                                                 create_sub_flags=False)
    suite.check('a chain can be built without sub controls', result['sub_flags'] == [])
    suite.check('and the end joint takes its rotation straight from the end control',
                result['end_twist_flag'].node in
                [target for constraint in
                 set(joints[-1].listConnections(type=pm.nt.OrientConstraint))
                 for target in pm.orientConstraint(constraint, query=True, targetList=True)])
    suite.check('with no cycle either way', not cmds.cycleCheck(all=True))

    # -- a non-joint between the ends ---------------------------------------------------------- #
    harness.new_scene()
    joints = _spine(pm, count=4, suffix='rfk_stretch')
    spacer = pm.group(empty=True, name='a_spacer')
    pm.parent(spacer, joints[1])
    pm.parent(joints[2], spacer)
    result = rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'spine')
    suite.check('something in the chain that is not a joint is not given a control',
                len(result['mid_flags']) == 2, str(result['mid_flags']))

    # -- what the proxy is for ----------------------------------------------------------------- #
    # The claim in the module's docstring, put to Maya: with the aim systems reading the control
    # instead of the proxy, the graph closes on itself.
    harness.new_scene()
    joints = _spine(pm, count=5, suffix='rfk_stretch')
    original_builder = rfk_stretch_chain.build_orient_proxy
    try:
        rfk_stretch_chain.build_orient_proxy = lambda flag, side, region: (
            flag.node, pm.group(empty=True, n='no_proxy_grp_{0}_{1}'.format(side, region)))
        rfk_stretch_chain.rfk_stretch_chain(joints[0], joints[-1], 'center', 'spine')
        suite.check('reading the end control itself, rather than the proxy, closes an evaluation '
                    'cycle - which is what the proxy is there for',
                    bool(cmds.cycleCheck(all=True)))
    finally:
        rfk_stretch_chain.build_orient_proxy = original_builder
    harness.new_scene()


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_rfk_chain(suite, pm)
    check_rfk_stretch_chain(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_rfk', body))
