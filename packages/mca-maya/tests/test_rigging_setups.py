"""
Locators, the ribbon, the aim setup and the twist setup, in a real Maya.

    mayapy tests/test_rigging_setups.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _chain(names, axis='y', step=5):
    """A joint chain running down one axis."""

    import maya.cmds as cmds
    import pymel.core as pm

    cmds.select(clear=True)
    joints = []
    for index, name in enumerate(names):
        offset = index * step
        position = {'x': (offset, 0, 0), 'y': (0, offset, 0), 'z': (0, 0, offset)}[axis]
        joints.append(pm.PyNode(cmds.joint(name=name, position=position, absolute=True)))
    return joints


# --------------------------------------------------------------------------------------- #
# locators
# --------------------------------------------------------------------------------------- #
def check_locators(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import locators

    harness.new_scene()
    node = pm.createNode('transform', name='a_thing')
    node.translate.set((1, 2, 3))
    node.rotate.set((0, 45, 0))
    node.rotateOrder.set(3)

    locator = locators.create_locator_at_object(node)
    suite.check('a locator is made', pm.objExists(locator))
    suite.check('named after the node it was placed at',
                str(locator) == 'a_thing_loc', str(locator))
    suite.check('at the same position',
                all(abs(now - was) < 0.001 for now, was in
                    zip(pm.xform(locator, query=True, worldSpace=True, translation=True),
                        pm.xform(node, query=True, worldSpace=True, translation=True))))
    suite.check('facing the same way',
                abs(pm.xform(locator, query=True, worldSpace=True, rotation=True)[1] - 45) < 0.01,
                str(pm.xform(locator, query=True, worldSpace=True, rotation=True)))
    suite.check('with a matching rotate order, or the values would not match',
                locator.rotateOrder.get() == 3)
    suite.check('and no constraint left behind',
                not (cmds.ls(type='parentConstraint') or []))

    suite.check('a label overrides the name',
                str(locators.create_locator_at_object(node, label='named_by_hand')) ==
                'named_by_hand')

    # The bug: this answered a locator at the origin, silently.
    missing = locators.create_locator_at_object('no_such_node')
    suite.check('a node that is not there still answers a locator', pm.objExists(missing))
    suite.check('at the origin, which is now said in the log',
                all(abs(value) < 0.001 for value in
                    pm.xform(missing, query=True, worldSpace=True, translation=True)))
    suite.check('and nothing at all is the same', pm.objExists(locators.create_locator_at_object(None)))

    at_point = locators.create_locator_at_point((4, 5, 6), name='at_a_point')
    suite.check('a locator can be put at a bare position',
                [round(value, 3) for value in at_point.translate.get()] == [4.0, 5.0, 6.0],
                str(at_point.translate.get()))
    suite.check('under the name it was given', str(at_point) == 'at_a_point')
    suite.check('and a pm.dt.Point works as well as three numbers',
                [round(value, 3) for value in
                 locators.create_locator_at_point(pm.dt.Point(1, 1, 1)).translate.get()] ==
                [1.0, 1.0, 1.0])


# --------------------------------------------------------------------------------------- #
# ribbon_setup
# --------------------------------------------------------------------------------------- #
def check_ribbon(suite, pm):
    from mca.mya.rigging import ribbon_setup

    harness.new_scene()
    # The bug: patchesV is len * 2 - 4, which Maya refuses at -2 and 0.
    suite.check('one node is too few to lay a ribbon along',
                ribbon_setup.create_ribbon_along_nodes(_chain(['a'])) is None)
    harness.new_scene()
    suite.check('and so are two',
                ribbon_setup.create_ribbon_along_nodes(_chain(['a', 'b'])) is None)
    suite.check('and nothing at all', ribbon_setup.create_ribbon_along_nodes(None) is None)

    harness.new_scene()
    joints = _chain(['b_spine_01', 'b_spine_02', 'b_spine_03', 'b_spine_04'])
    ribbon = ribbon_setup.create_ribbon_along_nodes(joints, name='spine_ribbon')
    suite.check('a ribbon is built', ribbon is not None and pm.objExists(ribbon))
    suite.check('under the name it was given', str(ribbon) == 'spine_ribbon', str(ribbon))

    cvs = ribbon.getShape().getCVs()
    suite.check('with four CVs across it',
                len(ribbon.getShape().getCVs(space='world')) ==
                ribbon_setup.CVS_PER_ROW * (len(joints) * 2 - 1),
                str(len(ribbon.getShape().getCVs(space='world'))))

    # A row per joint and a row per midpoint: the row at index 0 sits on the first joint.
    row_zero = [pm.pointPosition(ribbon.cv[index][0], world=True)
                for index in range(ribbon_setup.CVS_PER_ROW)]
    suite.check('the first row of CVs sits on the first joint',
                all(abs(position[1]) < 0.01 for position in row_zero), str(row_zero))
    suite.check('spread across the chain rather than along it',
                abs(row_zero[0][0] - row_zero[-1][0]) > 1 or
                abs(row_zero[0][2] - row_zero[-1][2]) > 1, str(row_zero))

    last_row = (len(joints) - 1) * 2
    row_last = [pm.pointPosition(ribbon.cv[index][last_row], world=True)
                for index in range(ribbon_setup.CVS_PER_ROW)]
    suite.check('and the last row sits on the last joint',
                all(abs(position[1] - 15) < 0.01 for position in row_last), str(row_last))

    midpoint_row = [pm.pointPosition(ribbon.cv[index][1], world=True)
                    for index in range(ribbon_setup.CVS_PER_ROW)]
    suite.check('with a row at the midpoint between the first two joints',
                all(abs(position[1] - 2.5) < 0.01 for position in midpoint_row),
                str(midpoint_row))

    # dag.get_primary_axis answers a lower-case letter; rig_utils answered an upper-case one, and
    # the letter is used as an index into 'xyz'.
    harness.new_scene()
    joints = _chain(['b_a', 'b_b', 'b_c'], axis='x')
    suite.check('a chain running down another axis lays a ribbon just as well',
                ribbon_setup.create_ribbon_along_nodes(joints) is not None)


# --------------------------------------------------------------------------------------- #
# rig_aim_joint
# --------------------------------------------------------------------------------------- #
def check_aim_joint(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import rig_aim_joint

    harness.new_scene()
    pm.namespace(add='rig_ns')
    pm.namespace(set='rig_ns')
    joint_node = _chain(['b_l_eye'])[0]
    pm.namespace(set=':')

    result = rig_aim_joint.rig_aim_joint(joint_node)
    suite.check('an aim setup is built', result['flag'] is not None)
    # The bug: the label came from bind_joint.name(), which keeps the namespace - so a joint in a
    # namespace gave a control with a colon in its label for Maya to rewrite. (Flag.create then
    # takes the bind joint's b_ prefix off, which is why the name is f_l_eye_aim.)
    suite.check('the control is named after the joint without its namespace',
                str(result['flag']) == 'f_l_eye_aim', str(result['flag']))
    suite.check('the rotate locator is made', pm.objExists(result['rotate_locator']))
    # The bug: the up locator was named by replacing '_loc_loc' in another locator's name.
    suite.check('and the up locator is named outright rather than by string surgery',
                str(result['up_locator']) == 'b_l_eye_up_loc', str(result['up_locator']))
    suite.check('the rotate locator has an align group',
                result['rotate_loc_align_grp'] is not None and
                result['rotate_locator'].getParent() == result['rotate_loc_align_grp'])

    suite.check('the control is out in front of the joint, along the aim axis',
                abs(pm.xform(result['flag'], query=True, worldSpace=True, translation=True)[0] -
                    rig_aim_joint.DEFAULT_FLAG_DISTANCE) < 0.01,
                str(pm.xform(result['flag'], query=True, worldSpace=True, translation=True)))
    # The bug: the marker the control was built on is deleted three lines later, and Flag.create
    # wires the control to what it was built on.
    suite.check('the temporary marker it was built on is gone',
                not pm.objExists('b_l_eye_aim_target'))
    suite.check('and the control was not wired to it',
                not result['flag'].node.hasAttr('driven_transform'))

    suite.check('the control only translates',
                all(result['flag'].node.attr(name).isLocked()
                    for name in rig_aim_joint.LOCKED_CHANNELS))

    aim_constraints = list(set(result['rotate_locator'].listConnections(type=pm.nt.AimConstraint)))
    suite.check('the rotate locator is aim constrained', len(aim_constraints) == 1)
    suite.check('at the control',
                pm.aimConstraint(aim_constraints[0], query=True, targetList=True) ==
                [result['flag'].node],
                str(pm.aimConstraint(aim_constraints[0], query=True, targetList=True)))
    suite.check('and the joint follows the locator',
                bool(set(joint_node.listConnections(type=pm.nt.ParentConstraint))))

    before = pm.xform(joint_node, query=True, worldSpace=True, rotation=True)
    result['flag'].node.translateY.set(20)
    suite.check('moving the control turns the joint',
                any(abs(now - was) > 1 for now, was in
                    zip(pm.xform(joint_node, query=True, worldSpace=True, rotation=True), before)),
                str(pm.xform(joint_node, query=True, worldSpace=True, rotation=True)))

    harness.new_scene()
    joint_node = _chain(['b_proxy_eye'])[0]
    result = rig_aim_joint.rig_aim_joint(joint_node, proxy=True)
    suite.check('a proxy setup leaves the bind joint alone',
                not set(joint_node.listConnections(type=pm.nt.ParentConstraint)))


# --------------------------------------------------------------------------------------- #
# twist_setup
# --------------------------------------------------------------------------------------- #
def _twist_skeleton(pm, twist_count=2):
    """An arm with a marked-up forearm segment and twist joints hanging off the elbow."""

    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    joints = _chain(['b_root', 'b_l_shoulder', 'b_l_elbow', 'b_l_wrist'], axis='x', step=10)
    root, shoulder, elbow, wrist = joints

    for joint_node, region in ((root, 'root'), (shoulder, 'arm'), (elbow, 'arm'), (wrist, 'arm')):
        markup = chain_markup.JointMarkup(joint_node)
        markup.side = 'left' if joint_node is not root else 'center'
        markup.region = region
    chain_markup.JointMarkup(shoulder).chainStart = 'arm'
    chain_markup.JointMarkup(wrist).chainEnd = 'arm'

    twists = []
    for index in range(twist_count):
        cmds.select(clear=True)
        twist = pm.PyNode(cmds.joint(name='b_l_forearm_twist_{0:02d}'.format(index),
                                     position=(20 + (index + 1) * 3, 0, 0), absolute=True))
        pm.parent(twist, elbow)
        twist_markup = chain_markup.JointMarkup(twist)
        twist_markup.side = 'left'
        twist_markup.chainTwist = 'forearm'
        twists.append(twist)
    return {'root': root, 'elbow': elbow, 'wrist': wrist, 'twists': twists}


def check_twist_setup(suite, pm):
    from mca.mya.rigging import twist_setup

    harness.new_scene()
    suite.check('no twist joints is a warning and no setup',
                twist_setup.twist_setup([]) == (None, {}))

    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=4)
    # The bug: this was refused silently. One multiplyDivide has three channels.
    suite.check('more twist joints than a multiplyDivide can drive is refused',
                twist_setup.twist_setup(skeleton['twists']) == (None, {}))

    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=2)
    twist_grp, build_dict = twist_setup.twist_setup(skeleton['twists'])
    suite.check('a twist setup is built', twist_grp is not None and pm.objExists(twist_grp))
    suite.check('named for its side and chain',
                str(twist_grp) == 'left_forearm_twist_grp', str(twist_grp))
    suite.check('with a mirror chain', len(build_dict['mirror_chain']) == 2)
    suite.check('an IK chain', len(build_dict['ik_chain']) == 2)
    suite.check('and an IK handle with its pole vector zeroed',
                all(build_dict['ik_handle'].attr('poleVector{0}'.format(axis)).get() == 0
                    for axis in 'XYZ'))
    suite.check('a locator holding the extracted twist', pm.objExists(build_dict['offset_loc']))
    suite.check('and one multiply node handing it out', pm.objExists(build_dict['multi_node']))

    suite.check('each twist joint is driven by one of its channels',
                all(bool(twist.rotateX.listConnections(source=True, destination=False))
                    for twist in skeleton['twists']),
                str([twist.rotateX.listConnections() for twist in skeleton['twists']]))
    suite.check('by a different amount each, the far one getting most',
                abs(build_dict['multi_node'].input2Y.get()) >
                abs(build_dict['multi_node'].input2X.get()),
                '{0} and {1}'.format(build_dict['multi_node'].input2X.get(),
                                     build_dict['multi_node'].input2Y.get()))

    # The twist joints sit nearer the elbow than the wrist, so the setup extracts the roll at the
    # elbow end - which is what rolling the elbow produces. Rolling a joint does not move the joint
    # below it, so the IK chain's solve does not change and what is left over is the roll.
    before = [twist.rotateX.get() for twist in skeleton['twists']]
    skeleton['elbow'].rotateX.set(60)
    pm.dgdirty(allPlugs=True)
    suite.check('rolling the driving joint twists the helper joints',
                any(abs(twist.rotateX.get() - was) > 0.5
                    for twist, was in zip(skeleton['twists'], before)),
                str([twist.rotateX.get() for twist in skeleton['twists']]))

    # -- markup mistakes, which used to raise ------------------------------------------------ #
    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=1)
    from mca.mya.rigging import chain_markup
    # The elbow says it is in a region the chain markup does not put it in.
    chain_markup.JointMarkup(skeleton['elbow']).region = 'nowhere'
    suite.check('a driving joint outside the chain its markup names is refused, not an IndexError',
                twist_setup.twist_setup(skeleton['twists']) == (None, {}))

    harness.new_scene()
    orphan = _chain(['b_lonely_twist'])[0]
    suite.check('a twist joint with no parent joint is refused',
                twist_setup.twist_setup([orphan]) == (None, {}))

    # -- the whole-skeleton pass ---------------------------------------------------------------- #
    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=2)
    macro_grp = twist_setup.quick_build_twist_setup(skeleton['root'])
    suite.check('every twist setup on a skeleton can be built in one pass',
                macro_grp is not None and len(macro_grp.getChildren()) == 1,
                str(macro_grp.getChildren() if macro_grp else None))
    suite.check('into a hidden group', macro_grp.visibility.get() is False)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_locators(suite, pm)
    check_ribbon(suite, pm)
    check_aim_joint(suite, pm)
    check_twist_setup(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_setups', body))
