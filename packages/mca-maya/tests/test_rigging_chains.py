"""
The chain builders: cog, world, reverse, fk, the ikfk switch and the multi constraint.

    mayapy tests/test_rigging_chains.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _chain(names, step=5):
    """A joint chain running up Y, one joint per name."""

    import maya.cmds as cmds
    import pymel.core as pm

    cmds.select(clear=True)
    return [pm.PyNode(cmds.joint(name=name, position=(0, index * step, 0), absolute=True))
            for index, name in enumerate(names)]


# --------------------------------------------------------------------------------------- #
# cog_chain_rig
# --------------------------------------------------------------------------------------- #
def check_cog_chain(suite, pm):
    from mca.mya.rigging import cog_chain_rig

    harness.new_scene()
    joints = _chain(['b_cog', 'b_cog_02'])
    result = cog_chain_rig.cog_chain(joints[0], joints[-1])

    suite.check('a control is built for every joint in the chain',
                len(result['flags']) == 2, str(result['flags']))
    suite.check('and a constraint for each', len(result['constraints']) == 2)
    suite.check('the chain is reported back', result['chain'] == joints, str(result['chain']))
    suite.check('the controls are named cog', all('cog' in str(flag) for flag in result['flags']),
                str(result['flags']))
    suite.check('with the rotate order that keeps the vertical axis out of the gimbal',
                all(flag.node.rotateOrder.get() == cog_chain_rig.COG_ROTATE_ORDER
                    for flag in result['flags']))

    result['flags'][0].node.translateX.set(4)
    suite.check('and moving one moves its joint',
                abs(pm.xform(joints[0], query=True, worldSpace=True, translation=True)[0] - 4) < 0.01,
                str(pm.xform(joints[0], query=True, worldSpace=True, translation=True)))

    harness.new_scene()
    one_joint = _chain(['b_only'])
    result = cog_chain_rig.cog_chain(one_joint[0], one_joint[0])
    suite.check('a chain of one joint gets one control', len(result['flags']) == 1)

    harness.new_scene()
    unrelated = _chain(['b_a'])
    other = _chain(['b_b'])
    result = cog_chain_rig.cog_chain(unrelated[0], other[0])
    suite.check('two joints in different hierarchies build nothing, with a warning',
                result['flags'] == [] and result['chain'] == [])


# --------------------------------------------------------------------------------------- #
# world_chain_rig
# --------------------------------------------------------------------------------------- #
def check_world_chain(suite, pm):
    from mca.mya.rigging import world_chain_rig

    harness.new_scene()
    root = _chain(['b_root'])[0]
    result = world_chain_rig.world_chain(root)

    world_flag = result['world_flag']
    root_flag = result['root_flag']
    offset_flag = result['offset_flag']
    suite.check('the three world controls are built',
                all(pm.objExists(flag) for flag in (world_flag, root_flag, offset_flag)))
    suite.check('named world, root and world_offset',
                (str(world_flag), str(root_flag), str(offset_flag)) ==
                ('f_world', 'f_root', 'f_world_offset'),
                '{0} {1} {2}'.format(world_flag, root_flag, offset_flag))
    suite.check('drawn at descending sizes so the nesting reads',
                world_flag.node.getShape().getCVs()[0][0] >
                root_flag.node.getShape().getCVs()[0][0] >
                offset_flag.node.getShape().getCVs()[0][0])

    suite.check('the root and offset controls hang off the world control',
                root_flag.get_align_transform().getParent() == world_flag and
                offset_flag.get_align_transform().getParent() == world_flag)
    # The root, not the world control: an animator offsets the character with root and leaves
    # world where layout put it.
    # One connection per driven channel, all from the same constraint node.
    constraints = list(set(root.listConnections(type=pm.nt.ParentConstraint)))
    suite.check('the joint is parent constrained, by one constraint',
                len(constraints) == 1, str(constraints))
    suite.check('to the root control, not the world one',
                pm.parentConstraint(constraints[0], query=True, targetList=True) ==
                [root_flag.node],
                str(pm.parentConstraint(constraints[0], query=True, targetList=True)))

    # The bug: the flags entry left the offset control out, though all three are built and locked.
    suite.check('all three controls are in the flags entry',
                sorted(str(flag) for flag in result['flags']) ==
                ['f_root', 'f_world', 'f_world_offset'], str(result['flags']))
    suite.check('their scale channels are locked - the world controls do not resize a character',
                all(flag.node.scaleX.isLocked() for flag in result['flags']))
    suite.check('the align group comes back by name rather than by parent walk',
                result['align_group'] == world_flag.get_align_transform())

    # The align group carries the -90 X the controls are built with, so the control's own Z runs
    # along world Y. What matters here is that the skeleton follows it.
    world_flag.node.translateZ.set(9)
    suite.check('moving the world control moves the skeleton',
                abs(pm.xform(root, query=True, worldSpace=True, translation=True)[1] - 9) < 0.01,
                str(pm.xform(root, query=True, worldSpace=True, translation=True)))


# --------------------------------------------------------------------------------------- #
# reverse_chain_rig
# --------------------------------------------------------------------------------------- #
def check_reverse_chain(suite, pm):
    from mca.mya.rigging import reverse_chain_rig

    harness.new_scene()
    joints = _chain(['l_ankle', 'l_ball'])
    result = reverse_chain_rig.reverse_chain(joints[0], joints[1])

    # The bug: the label is name.replace('_' + suffix, ''), and suffix defaults to '' - so the
    # replacement was '_' for nothing, and l_ankle gave f_lankle.
    suite.check('the default suffix does not strip the underscores out of the name',
                str(result['flag']) == 'f_l_ankle', str(result['flag']))

    suite.check('a hidden reversed chain is built',
                pm.objExists(result['rotate_joint']) and
                result['rotate_joint'].visibility.get() is False)
    suite.check('with no parent, so the control drives it alone',
                result['rotate_joint'].getParent() is None)
    suite.check('and an align group for the control',
                result['align_group'] == result['flag'].get_align_transform())

    result['flag'].node.rotateX.set(20)
    suite.check('turning the control turns the start joint about the end joint',
                abs(pm.xform(joints[0], query=True, worldSpace=True, rotation=True)[0]) > 1,
                str(pm.xform(joints[0], query=True, worldSpace=True, rotation=True)))

    harness.new_scene()
    joints = _chain(['l_ankle_rev_chain', 'l_ball_rev_chain'])
    result = reverse_chain_rig.reverse_chain(joints[0], joints[1], suffix='rev_chain')
    suite.check('a suffix that is there is taken off',
                str(result['flag']) == 'f_l_ankle', str(result['flag']))

    harness.new_scene()
    joints = _chain(['a', 'b', 'c'])
    message = suite.raises('a chain with a joint in the middle is refused',
                           reverse_chain_rig.reverse_chain, joints[0], joints[-1])
    suite.check('and the message says what is wrong rather than what is required',
                'between them' in message, message)


# --------------------------------------------------------------------------------------- #
# fk_chain
# --------------------------------------------------------------------------------------- #
def check_fk_chain(suite, pm):
    from mca.mya.rigging import fk_chain

    harness.new_scene()
    joints = _chain(['b_shoulder', 'b_elbow', 'b_wrist', 'b_hand_end'])
    result = fk_chain.fk_joint_chain(joints[0], joints[-1])

    suite.check('the end joint is left out by default',
                len(result['flags']) == 3, str(result['flags']))
    # The bind joint's b_ prefix comes off in Flag.create, so b_shoulder gives f_shoulder.
    suite.check('the controls are named after their joints, without the bind prefix',
                str(result['flags'][0]) == 'f_shoulder', str(result['flags'][0]))
    suite.check('each control nests under the one above it',
                result['flags'][1].get_align_transform().getParent() == result['flags'][0] and
                result['flags'][2].get_align_transform().getParent() == result['flags'][1])
    suite.check('and the first one has no control above it',
                result['flags'][0].get_align_transform().getParent() is None)
    suite.check('one constraint per control', len(result['parent_constraints']) == 3)
    suite.check('and no offset control unless one was asked for',
                result['offset_flag'] is None)

    result['flags'][0].node.rotateZ.set(15)
    suite.check('turning a control turns its joint',
                abs(pm.xform(joints[0], query=True, rotation=True)[2] - 15) < 0.01,
                str(pm.xform(joints[0], query=True, rotation=True)))
    suite.check('and carries the ones below it',
                abs(pm.xform(joints[1], query=True, worldSpace=True, translation=True)[0]) > 0.5,
                str(pm.xform(joints[1], query=True, worldSpace=True, translation=True)))

    harness.new_scene()
    joints = _chain(['b_shoulder', 'b_elbow', 'b_wrist'])
    result = fk_chain.fk_joint_chain(joints[0], joints[-1], create_end_flag=True)
    suite.check('the end joint gets a control when it is asked for',
                len(result['flags']) == 3, str(result['flags']))

    # -- the bug: no align transforms raised --------------------------------------------- #
    harness.new_scene()
    joints = _chain(['b_a', 'b_b', 'b_c'])
    result = fk_chain.fk_joint_chain(joints[0], joints[-1], root_align_transform=False,
                                    children_align_transforms=False, create_end_flag=True)
    suite.check('a chain built without align transforms works rather than raising',
                len(result['flags']) == 3, str(result['flags']))
    suite.check('and the controls nest directly',
                result['flags'][1].node.getParent() == result['flags'][0].node,
                str(result['flags'][1].node.getParent()))

    harness.new_scene()
    joints = _chain(['b_a', 'b_b'])
    result = fk_chain.fk_joint_chain(joints[0], joints[-1], root_align_transform=False,
                                    create_end_flag=True)
    suite.check('and a mixed pair works too', len(result['flags']) == 2, str(result['flags']))

    # -- the offset control ---------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain(['b_a', 'b_b', 'b_c'])
    result = fk_chain.fk_joint_chain(joints[0], joints[-1], offset_flag=True, create_end_flag=True)
    offset = result['offset_flag']
    suite.check('an offset control is built on the last rigged joint',
                offset is not None and str(offset).endswith('_offset'), str(offset))
    suite.check('marked as a detail control', offset.node.isDetail.get() is True)
    suite.check('hanging off the control it offsets',
                offset.get_align_transform().getParent() == result['flags'][-1])
    suite.check('and it is what drives the joint',
                offset.node in pm.parentConstraint(result['parent_constraints'][-1],
                                                   query=True, targetList=True),
                str(pm.parentConstraint(result['parent_constraints'][-1], query=True,
                                        targetList=True)))

    # -- scale ------------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain(['b_a', 'b_b'])
    result = fk_chain.fk_joint_chain(joints[0], joints[-1], use_scale=True, create_end_flag=True)
    # source only: Maya wires a joint's scale to its child's inverseScale by itself, so the
    # outgoing connections are not the question.
    suite.check('the controls can drive their joints scale',
                joints[0].scale.listConnections(source=True, destination=False) ==
                [result['flags'][0].node],
                str(joints[0].scale.listConnections(source=True, destination=False)))

    # -- refusals ----------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain(['b_a'])
    result = fk_chain.fk_joint_chain(joints[0], joints[0])
    suite.check('a chain of one with no end control builds nothing, and says so',
                result['flags'] == [], str(result['flags']))
    suite.raises('a start joint that is not there is refused',
                 fk_chain.fk_joint_chain, 'no_such_joint', joints[0])
    suite.raises('and an end joint that is not there',
                 fk_chain.fk_joint_chain, joints[0], 'no_such_joint')


# --------------------------------------------------------------------------------------- #
# ikfk_switch
# --------------------------------------------------------------------------------------- #
def check_ikfk_switch(suite, pm):
    from mca.mya.rigging import ikfk_switch

    harness.new_scene()
    joint_node = _chain(['b_l_wrist'])[0]
    result = ikfk_switch.ikfk_switch(joint_node, 'l', 'arm')

    switch_flag = result['flag']
    suite.check('a switch control is built', pm.objExists(switch_flag))
    suite.check('named for its side and region',
                str(switch_flag) == 'f_l_arm_ikfk_switch', str(switch_flag))
    suite.check('carrying the switch attribute',
                switch_flag.node.hasAttr(result['name']) and result['name'] == 'ikfk_switch')
    suite.check('which runs from nought to one and starts fully on',
                switch_flag.node.attr(result['name']).get() == 1.0)

    suite.check('an inverting node reads it', pm.objExists(result['invert_node']))
    suite.check('named for its side and region too',
                str(result['invert_node']) == 'l_arm_switch_invert_node',
                str(result['invert_node']))
    suite.check('and it is driven by the switch',
                switch_flag.node.attr(result['name']) in
                result['invert_node'].listConnections(source=True, destination=False, plugs=True),
                str(result['invert_node'].listConnections(source=True, destination=False,
                                                         plugs=True)))

    align_transform = switch_flag.get_align_transform()
    suite.check('the control follows the joint through its align group, not its own channels',
                bool(align_transform.translateX.listConnections()) and
                not switch_flag.node.translateX.listConnections())


# --------------------------------------------------------------------------------------- #
# multi_constraint_rig
# --------------------------------------------------------------------------------------- #
def check_multi_constraint(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import multi_constraint_rig

    harness.new_scene()
    world_space = pm.createNode('transform', name='world_space')
    hand_space = pm.createNode('transform', name='hand_space')
    control = pm.createNode('transform', name='prop_flag')
    control.translate.set((0, 1, 0))

    result = multi_constraint_rig.multi_constraint([world_space, hand_space], control)
    suite.check('the constraint is built', result['multi_matrix'] is not None)
    suite.check('with one choice node for the space and one for the offset',
                result['choice_space'] is not None and result['choice_offset'] is not None)
    suite.check('the enum is on the control',
                list(control.attr(multi_constraint_rig.SWITCH_ATTR).getEnums().keys()) ==
                ['world_space', 'hand_space'],
                str(control.attr(multi_constraint_rig.SWITCH_ATTR).getEnums()))
    suite.check('with a separator above it',
                control.hasAttr(multi_constraint_rig.SEPARATOR_ATTR))

    suite.check('both choice nodes are driven by the enum',
                control.attr(multi_constraint_rig.SWITCH_ATTR) in
                result['choice_space'].selector.listConnections(plugs=True) and
                control.attr(multi_constraint_rig.SWITCH_ATTR) in
                result['choice_offset'].selector.listConnections(plugs=True))
    suite.check('an offset is stored per target',
                all(result['parent_constraint_group'].hasAttr('{0}_offset'.format(name))
                    for name in ('world_space', 'hand_space')))

    # -- following ------------------------------------------------------------------------- #
    hand_space.translate.set((6, 0, 0))
    world_space.translate.set((0, 0, -4))
    control.attr(multi_constraint_rig.SWITCH_ATTR).set(1)
    position = pm.xform(control, query=True, worldSpace=True, translation=True)
    suite.check('the control follows the target the enum is on',
                abs(position[0] - 6) < 0.01, str(position))
    suite.check('keeping the offset it was built with', abs(position[1] - 1) < 0.01, str(position))
    suite.check('and not the target it is off', abs(position[2]) < 0.01, str(position))

    control.attr(multi_constraint_rig.SWITCH_ATTR).set(0)
    position = pm.xform(control, query=True, worldSpace=True, translation=True)
    suite.check('switching moves it into the other space',
                abs(position[2] + 4) < 0.01 and abs(position[0]) < 0.01, str(position))

    # -- the bug: a second one on the same control raised ----------------------------------- #
    again = multi_constraint_rig.multi_constraint([world_space], control)
    suite.check('asking twice is a warning rather than a raise',
                again['multi_matrix'] is None, str(again))

    # -- the bug: an empty target list raised ------------------------------------------------ #
    harness.new_scene()
    control = pm.createNode('transform', name='no_targets')
    suite.check('no targets to follow is a warning, not a crash',
                multi_constraint_rig.multi_constraint([], control)['multi_matrix'] is None)

    # -- which channels follow ----------------------------------------------------------------- #
    harness.new_scene()
    target = pm.createNode('transform', name='a_target')
    control = pm.createNode('transform', name='rot_only_flag')
    result = multi_constraint_rig.multi_constraint([target], control, translate=False, scale=False)
    suite.check('translation is left alone when it is not asked for',
                not result['decomp_matrix'].outputTranslate.listConnections())
    suite.check('nor scale', not result['decomp_matrix'].outputScale.listConnections())
    suite.check('while rotation is driven',
                bool(result['decomp_matrix'].outputRotate.listConnections()))

    # -- a first space with a name of its own --------------------------------------------------- #
    harness.new_scene()
    root = pm.createNode('transform', name='root_space')
    other = pm.createNode('transform', name='chest_space')
    control = pm.createNode('transform', name='named_flag')
    multi_constraint_rig.multi_constraint([root, other], control, default_name='world')
    suite.check('the first entry in the enum can be renamed',
                list(control.attr(multi_constraint_rig.SWITCH_ATTR).getEnums().keys()) ==
                ['world', 'chest_space'],
                str(control.attr(multi_constraint_rig.SWITCH_ATTR).getEnums()))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_cog_chain(suite, pm)
    check_world_chain(suite, pm)
    check_reverse_chain(suite, pm)
    check_fk_chain(suite, pm)
    check_ikfk_switch(suite, pm)
    check_multi_constraint(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_chains', body))
