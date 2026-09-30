"""
Rigging, the leaf pieces: matrix_nodes, ik_utils and space_switch_rig, in a real Maya.

    mayapy tests/test_rigging_base.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _chain(positions, prefix='j'):
    """A joint chain through the given world positions, root first."""

    import maya.cmds as cmds
    import pymel.core as pm

    cmds.select(clear=True)
    joints = []
    for index, position in enumerate(positions):
        joints.append(pm.PyNode(cmds.joint(name='{0}{1}'.format(prefix, index),
                                           position=position, absolute=True)))
    return joints


# --------------------------------------------------------------------------------------- #
# matrix_nodes
# --------------------------------------------------------------------------------------- #
def check_matrix_nodes(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import matrix_nodes

    harness.new_scene()
    driver = pm.createNode('transform', name='driver')
    driven = pm.createNode('transform', name='driven')
    driven.translate.set((0, 3, 0))

    made = matrix_nodes.matrix_constraint(driver, driven)
    suite.check('the network comes back under names a caller can read',
                sorted(made) == ['constraint_group', 'decomp_matrix', 'multi_matrix',
                                 'parent_constraint_group'], str(sorted(made)))
    suite.check('both matrix nodes are tagged',
                made['multi_matrix'].hasAttr(matrix_nodes.MATRIX_CONSTRAINT_TAG) and
                made['decomp_matrix'].hasAttr(matrix_nodes.MATRIX_CONSTRAINT_TAG))
    suite.check('the outer group is named after the object it drives',
                str(made['parent_constraint_group']) == 'driven_constraint_parent_grp',
                str(made['parent_constraint_group']))
    suite.check('the driven object points back at it',
                driven.attr(matrix_nodes.PARENT_CONSTRAINT_ATTR).get() ==
                made['parent_constraint_group'])
    suite.check('by name as well as by message',
                driven.attr(matrix_nodes.PARENT_CONSTRAINT_OBJECT_ATTR).get() ==
                str(made['parent_constraint_group']))
    suite.check('and the object itself is still where it was',
                abs(pm.xform(driven, query=True, worldSpace=True, translation=True)[1] - 3) < 0.001)

    driver.translate.set((5, 0, 0))
    position = pm.xform(driven, query=True, worldSpace=True, translation=True)
    suite.check('moving the parent moves the child', abs(position[0] - 5) < 0.001, str(position))
    suite.check('and the offset between them is kept', abs(position[1] - 3) < 0.001, str(position))

    driver.rotateY.set(90)
    suite.check('turning the parent turns the child',
                abs(pm.xform(driven, query=True, worldSpace=True, rotation=True)[1] - 90) < 0.01,
                str(pm.xform(driven, query=True, worldSpace=True, rotation=True)))

    # -- which channels follow -------------------------------------------------------------- #
    harness.new_scene()
    driver = pm.createNode('transform', name='driver')
    driven = pm.createNode('transform', name='driven')
    made = matrix_nodes.matrix_constraint(driver, driven, r=False, s=False)
    group = made['constraint_group']
    suite.check('translation is connected when it is asked for',
                bool(group.translate.listConnections()))
    suite.check('and rotation is not when it is not',
                not group.rotate.listConnections())
    suite.check('nor scale', not group.scale.listConnections())

    harness.new_scene()
    driver = pm.createNode('transform', name='driver')
    driven = pm.createNode('transform', name='driven')
    driven.translate.set((0, 4, 0))
    matrix_nodes.matrix_constraint(driver, driven, mo=False)
    position = pm.xform(driven, query=True, worldSpace=True, translation=True)
    suite.check('without maintain offset the child snaps onto the parent',
                abs(position[1]) < 0.001, str(position))

    suite.check('remove_matrix_constraint had no callers and is gone',
                not hasattr(matrix_nodes, 'remove_matrix_constraint'))


# --------------------------------------------------------------------------------------- #
# ik_utils
# --------------------------------------------------------------------------------------- #
def check_ik_utils(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import ik_utils

    harness.new_scene()
    # A three joint chain bent towards +X.
    joints = _chain([(0, 0, 0), (2, 5, 0), (0, 10, 0)])
    position = ik_utils.get_pole_vector_position(joints)
    suite.check('a bent chain has a pole vector', position is not None)
    suite.check('out in front of the bend, on the side it bends towards',
                position[0] > 2, str(position))
    suite.check('level with the middle joint',
                abs(position[1] - 5) < 0.001, str(position))
    suite.check('and in the chain plane', abs(position[2]) < 0.001, str(position))

    close = ik_utils.get_pole_vector_position(joints, offset=1)
    suite.check('an explicit offset is the distance from the middle joint',
                abs(close[0] - 3) < 0.001, str(close))

    # -- the bug: an even chain took its middle from the wrong pair ----------------------- #
    # Correct is the midpoint of joints 1 and 2, which is level with y=6. The old arithmetic
    # used joints 2 and 3, which is level with y=10.
    harness.new_scene()
    joints = _chain([(0, 0, 0), (4, 4, 0), (4, 8, 0), (0, 12, 0)])
    position = ik_utils.get_pole_vector_position(joints)
    suite.check('a four joint chain takes its middle from the two either side of the centre',
                abs(position[1] - 6) < 0.001, str(position))
    suite.check('and the pole vector is out on the bend side', position[0] > 4, str(position))

    # -- the bug: a two joint chain raised ------------------------------------------------ #
    harness.new_scene()
    joints = _chain([(0, 0, 0), (0, 5, 0)])
    suite.check('a chain too short for a pole vector is refused rather than raising',
                ik_utils.get_pole_vector_position(joints) is None)
    suite.check('and so is nothing at all', ik_utils.get_pole_vector_position(None) is None)
    suite.check('the locator is not made either',
                ik_utils.create_pole_vector_locator(joints) is None)

    # -- the bug: root and end in the same place divided by zero -------------------------- #
    harness.new_scene()
    joints = _chain([(0, 0, 0), (0, 5, 0), (0, 0, 0)])
    position = ik_utils.get_pole_vector_position(joints)
    suite.check('a chain folded back on itself still answers', position is not None)
    suite.check('with real numbers rather than nan',
                all(value == value for value in position), str(position))
    suite.check('pointing the way the middle joint went',
                position[1] > 5, str(position))

    # A chain with no bend at all: the direction cannot be known, and it says so.
    harness.new_scene()
    joints = _chain([(0, 0, 0), (0, 5, 0), (0, 10, 0)])
    position = ik_utils.get_pole_vector_position(joints)
    suite.check('a perfectly straight chain answers the middle joint, as it always has',
                position is not None and abs(position[1] - 5) < 0.001, str(position))

    # -- the locator ----------------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain([(0, 0, 0), (2, 5, 0), (0, 10, 0)])
    locator = ik_utils.create_pole_vector_locator(joints, name='elbow_pv')
    suite.check('the locator is made', locator is not None and pm.objExists(locator))
    suite.check('under the name it was given', str(locator) == 'elbow_pv', str(locator))
    expected = ik_utils.get_pole_vector_position(joints)
    suite.check('which is where the locator is',
                abs(locator.translateX.get() - expected[0]) < 0.001, str(locator.translate.get()))


# --------------------------------------------------------------------------------------- #
# space_switch_rig
# --------------------------------------------------------------------------------------- #
def check_space_switch(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import space_switch_rig

    harness.new_scene()
    world_space = pm.createNode('transform', name='world_space')
    hand_space = pm.createNode('transform', name='hand_space')
    parent = pm.createNode('transform', name='rig_grp')
    control = pm.createNode('transform', name='prop_flag')
    pm.parent(control, parent)

    control.translate.set((1, 2, 3))
    before = pm.xform(control, query=True, worldSpace=True, translation=True)

    made = space_switch_rig.space_switch([world_space, hand_space], control)
    suite.check('building the switch does not move the control',
                all(abs(now - was) < 0.001 for now, was in
                    zip(pm.xform(control, query=True, worldSpace=True, translation=True), before)),
                '{0} became {1}'.format(before,
                                        pm.xform(control, query=True, worldSpace=True,
                                                 translation=True)))
    suite.check('a space switch answers what it built',
                sorted(made) == ['conditions', 'orient_constraints', 'point_constraints',
                                 'switch_offset_grp'], str(sorted(made)))
    suite.check('with one condition per space', len(made['conditions']) == 2)
    suite.check('the control has the enum on it',
                control.hasAttr(space_switch_rig.SWITCH_ATTR))
    suite.check('named after the spaces',
                control.attr(space_switch_rig.SWITCH_ATTR).getEnums().keys() ==
                ['world_space', 'hand_space'],
                str(control.attr(space_switch_rig.SWITCH_ATTR).getEnums()))
    suite.check('and a separator above it in the channel box',
                control.hasAttr(space_switch_rig.SEPARATOR_ATTR))
    suite.check('the offset group sits between the control and its parent',
                control.getParent() == made['switch_offset_grp'] and
                made['switch_offset_grp'].getParent() == parent)

    # -- following ------------------------------------------------------------------------- #
    # The control started at (1, 2, 3) and the constraints keep that offset, so it lands
    # wherever the space it follows has moved to, plus those three numbers.
    control.attr(space_switch_rig.SWITCH_ATTR).set(1)
    hand_space.translate.set((7, 0, 0))
    position = pm.xform(control, query=True, worldSpace=True, translation=True)
    suite.check('the control follows the space the enum is on',
                abs(position[0] - 8) < 0.001, str(position))

    world_space.translate.set((0, 0, -9))
    position = pm.xform(control, query=True, worldSpace=True, translation=True)
    suite.check('and not the one it is off', abs(position[2] - 3) < 0.001, str(position))

    control.attr(space_switch_rig.SWITCH_ATTR).set(0)
    position = pm.xform(control, query=True, worldSpace=True, translation=True)
    suite.check('switching moves it into the other space',
                abs(position[2] + 6) < 0.001 and abs(position[0] - 1) < 0.001, str(position))

    # -- the bug: a second switch on the same control raised ------------------------------- #
    again = space_switch_rig.space_switch([world_space], control)
    suite.check('asking twice is a warning rather than a raise',
                again['switch_offset_grp'] is None, str(again))

    # -- the bug: a control with no parent raised ------------------------------------------ #
    harness.new_scene()
    target = pm.createNode('transform', name='target')
    lonely = pm.createNode('transform', name='lonely_flag')
    made = space_switch_rig.space_switch([target], lonely)
    suite.check('a control at the top of the scene can be switched too',
                made['switch_offset_grp'] is not None)
    suite.check('and its offset group has no parent either',
                made['switch_offset_grp'].getParent() is None)

    # -- the bug: the weight alias was spelled out rather than asked for ------------------- #
    harness.new_scene()
    pm.namespace(add='rig_ns')
    pm.namespace(set='rig_ns')
    namespaced_target = pm.createNode('transform', name='ns_target')
    pm.namespace(set=':')
    control = pm.createNode('transform', name='ns_flag')
    made = space_switch_rig.space_switch([namespaced_target], control)
    suite.check('a target inside a namespace is connected rather than raising',
                len(made['conditions']) == 1, str(made))
    condition = made['conditions'][0]
    suite.check('its condition drives a constraint weight',
                bool(condition.outColorR.listConnections()),
                str(condition.outColorR.listConnections(plugs=True)))

    # -- a first space with a name of its own ---------------------------------------------- #
    harness.new_scene()
    root = pm.createNode('transform', name='root_space')
    other = pm.createNode('transform', name='chest_space')
    control = pm.createNode('transform', name='named_flag')
    space_switch_rig.space_switch([root, other], control, default_name='world')
    suite.check('the first entry in the enum can be renamed',
                control.attr(space_switch_rig.SWITCH_ATTR).getEnums().keys() ==
                ['world', 'chest_space'],
                str(control.attr(space_switch_rig.SWITCH_ATTR).getEnums()))

    harness.new_scene()
    control = pm.createNode('transform', name='no_spaces')
    suite.check('no spaces to follow is a warning, not a crash',
                space_switch_rig.space_switch([], control)['switch_offset_grp'] is None)

    # -- rotation only ---------------------------------------------------------------------- #
    harness.new_scene()
    target = pm.createNode('transform', name='rot_target')
    control = pm.createNode('transform', name='rot_flag')
    made = space_switch_rig.space_switch([target], control, translate=False)
    suite.check('a rotation-only switch makes no point constraints',
                not made['point_constraints'] and len(made['orient_constraints']) == 1)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_matrix_nodes(suite, pm)
    check_ik_utils(suite, pm)
    check_space_switch(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_base', body))
