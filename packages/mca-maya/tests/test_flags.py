"""
Flags: mca.mya.rigging.flags.flag_mirror and frag_flag, in a real Maya.

    mayapy tests/test_flags.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


# --------------------------------------------------------------------------------------- #
# flag_mirror
# --------------------------------------------------------------------------------------- #
def check_flag_mirror(suite, pm):
    from mca.mya.rigging.flags import flag_mirror

    # -- pairing by name ------------------------------------------------------------------ #
    suite.check('a trailing side token mirrors',
                flag_mirror.mirror_name('f_hand_l') == 'f_hand_r')
    suite.check('and back the other way',
                flag_mirror.mirror_name('f_hand_r') == 'f_hand_l')
    suite.check('a spelt-out side works too',
                flag_mirror.mirror_name('f_left_arm') == 'f_right_arm')
    suite.check('and a leading single letter',
                flag_mirror.mirror_name('f_l_leg_toe_ik') == 'f_r_leg_toe_ik')

    # The reason the match is on whole tokens: a substring rule turns this into f_ling_01_l.
    suite.check('a name containing an r in a word is not mangled',
                flag_mirror.mirror_name('f_ring_01_l') == 'f_ring_01_r',
                flag_mirror.mirror_name('f_ring_01_l'))
    suite.check('the case of the token is kept',
                flag_mirror.mirror_name('F_Hand_L') == 'F_Hand_R',
                flag_mirror.mirror_name('F_Hand_L'))
    suite.check('a centre flag has no opposite number',
                flag_mirror.mirror_name('f_spine_01') == '')
    suite.check('and says so', flag_mirror.has_side('f_spine_01') is False)
    suite.check('while a sided one does', flag_mirror.has_side('f_hand_l') is True)

    # -- pairing a set --------------------------------------------------------------------- #
    mapping = flag_mirror.build_mirror_map(['f_hand_l', 'f_hand_r', 'f_spine_01', 'f_foot_l'])
    suite.check('a pair maps to each other',
                mapping['f_hand_l'] == 'f_hand_r' and mapping['f_hand_r'] == 'f_hand_l')
    suite.check('a centre flag maps to itself, which is what mirroring it means',
                mapping['f_spine_01'] == 'f_spine_01')
    # Mirroring a lone left foot onto itself would put left values on the left foot with the
    # signs flipped, which is not a mirror.
    suite.check('a sided flag whose partner is missing is left out',
                'f_foot_l' not in mapping, str(mapping))
    suite.check('and is named, so somebody can go and look',
                flag_mirror.unpaired(['f_hand_l', 'f_hand_r', 'f_foot_l']) == ['f_foot_l'])

    # -- channels ----------------------------------------------------------------------------- #
    suite.check('a short channel name is normalised',
                flag_mirror.long_channel_name('tx') == 'translateX')
    suite.check('a plug name loses its node',
                flag_mirror.long_channel_name('f_hand_l.rotateY') == 'rotateY')
    suite.check('a name nobody knows is left alone',
                flag_mirror.long_channel_name('ikfk_switch') == 'ikfk_switch')

    suite.check('the behaviour convention flips translateX',
                flag_mirror.channel_sign('tx') == -1.0)
    suite.check('and rotateY', flag_mirror.channel_sign('rotateY') == -1.0)
    suite.check('but not translateY', flag_mirror.channel_sign('ty') == 1.0)
    suite.check('and not a custom attribute, which is not spatial',
                flag_mirror.channel_sign('ikfk_switch') == 1.0)
    suite.check('the orientation convention flips a different set',
                flag_mirror.channel_sign('rotateX', flag_mirror.ORIENTATION_MIRROR) == -1.0 and
                flag_mirror.channel_sign('rotateY', flag_mirror.ORIENTATION_MIRROR) == 1.0)

    suite.check('a value on an unflipped channel crosses unchanged',
                flag_mirror.mirrored_value('ty', 5.0) == 5.0)
    suite.check('and a flipped one is negated', flag_mirror.mirrored_value('tx', 5.0) == -5.0)
    # Around the rest value, not around zero: a channel that rests at 1 would otherwise be
    # thrown off its rest pose by being mirrored.
    suite.check('around the rest value rather than around zero',
                flag_mirror.mirrored_value('tx', 3.0, default=1.0) == -1.0,
                str(flag_mirror.mirrored_value('tx', 3.0, default=1.0)))
    suite.check('so a channel sitting at rest stays at rest',
                flag_mirror.mirrored_value('tx', 1.0, default=1.0) == 1.0)

    suite.check('a convention can say what it does',
                flag_mirror.describe() == 'flips rotateY, rotateZ, translateX',
                flag_mirror.describe())
    suite.check('and be recognised by name',
                flag_mirror.convention_name(flag_mirror.BEHAVIOUR_MIRROR) == 'behaviour')
    suite.check('including one that is neither',
                flag_mirror.convention_name({'translateZ': -1.0}) == 'custom')
    suite.check('nothing flipped says so', flag_mirror.describe({}) == 'flips nothing')


# --------------------------------------------------------------------------------------- #
# frag_flag
# --------------------------------------------------------------------------------------- #
def check_flag_creation(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging.flags import frag_flag
    from mca.mya.utils import groups

    harness.new_scene()
    joint_node = pm.joint(name='b_l_hand')
    joint_node.rotateOrder.set(3)

    marker = pm.createNode('transform', name='keep_me_selected')
    pm.select(marker)

    flag = frag_flag.Flag.create(joint_node)
    suite.check('a flag is built', pm.objExists(flag.node))
    suite.check('as a joint, so its build orientation can live in jointOrient',
                isinstance(flag.node, pm.nt.Joint))
    suite.check('drawn as nothing, so the bone does not show',
                flag.node.drawStyle.get() == frag_flag.JOINT_DRAW_STYLE_NONE)
    suite.check('with a curve shape on it',
                isinstance(flag.node.getShape(), pm.nt.NurbsCurve))
    suite.check('marked as a flag', frag_flag.is_flag_node(flag.node) is True)
    suite.check("named after what it drives, with the bind joint's prefix taken off",
                flag.name == 'f_l_hand', flag.name)
    suite.check('sharing its rotate order', flag.node.rotateOrder.get() == 3)

    # The version before made its joint from an empty selection and never put the old one back.
    suite.check("building a flag leaves the artist's selection alone",
                pm.selected() == [marker], str(pm.selected()))

    suite.check('none of the four markers are set unless they are asked for',
                not any(flag.node.attr(name).get() for name in frag_flag.FLAG_TYPES),
                str([(name, flag.node.attr(name).get()) for name in frag_flag.FLAG_TYPES]))
    suite.check('and all four are there',
                all(flag.node.hasAttr(name) for name in frag_flag.FLAG_TYPES))
    suite.check('the display layer hook is there too',
                flag.node.hasAttr(frag_flag.FLAG_LAYER_ATTR))

    suite.check('it is wired to what it drives',
                flag.node.driven_transform.listConnections() == [joint_node])
    suite.check('and back the other way',
                joint_node.driver_flag.listConnections() == [flag.node])

    align = flag.get_align_transform()
    suite.check('an align transform is made', align is not None and pm.objExists(align))
    suite.check('with the flag under it', flag.node.getParent() == align)
    suite.check('so the flag itself reads zero',
                all(abs(value) < 0.001 for value in flag.node.translate.get()))

    # -- markers ---------------------------------------------------------------------------- #
    harness.new_scene()
    joint_node = pm.joint(name='b_spine')
    flag = frag_flag.Flag.create(joint_node, is_detail=True, is_util=True)
    suite.check('the markers asked for are set',
                flag.node.isDetail.get() is True and flag.node.isUtil.get() is True)
    suite.check('and the others are not',
                flag.node.isSub.get() is False and flag.node.isContact.get() is False)

    flag.set_as_sub()
    flag.set_as_contact()
    suite.check('and they can be set afterwards',
                flag.node.isSub.get() is True and flag.node.isContact.get() is True)

    # -- no align transform: the bug ---------------------------------------------------------- #
    harness.new_scene()
    joint_node = pm.joint(name='b_bare')
    flag = frag_flag.Flag.create(joint_node, add_align_transform=False)
    suite.check('a flag can be built without an align transform',
                flag.get_align_transform() is None)
    # The old hide_align_transform did align.v.set(0) on that None.
    suite.check('and hiding it is a no rather than a raise',
                flag.hide_align_transform() is False)

    harness.new_scene()
    joint_node = pm.joint(name='b_hidden')
    flag = frag_flag.Flag.create(joint_node)
    suite.check('hiding a flag that has one works',
                flag.hide_align_transform() is True)
    suite.check('and turns the group off',
                flag.get_align_transform().visibility.get() is False)

    # -- re-orienting the align transform: the bug ---------------------------------------------- #
    harness.new_scene()
    joint_node = pm.joint(name='b_turned')
    # Nothing above the flag, so the align group has no parent - which is what used to raise.
    flag = frag_flag.Flag.create(joint_node, orientation=[0, 90, 0])
    suite.check('a flag at the top of the scene can have its zero pose turned',
                flag.get_align_transform() is not None)
    suite.check('and the turn is on the group',
                abs(flag.get_align_transform().rotateY.get() - 90) < 0.01,
                str(flag.get_align_transform().rotate.get()))
    suite.check("with the flag's own joint orient cleared",
                all(abs(value) < 0.001 for value in flag.node.jointOrient.get()))

    # The bug in full: the branch called pm.parent(None, world=True), because a fresh flag's
    # align group has no parent - and pm.parent given None falls back to the selection. So
    # whatever the artist had selected was un-parented to the world. Both checked in a real Maya.
    harness.new_scene()
    parent_grp = pm.group(empty=True, name='rig_grp')
    bystander = pm.createNode('transform', name='innocent_bystander')
    pm.parent(bystander, parent_grp)
    joint_node = pm.joint(name='b_turned_too')
    pm.select(bystander)

    flag = frag_flag.Flag.create(joint_node, orientation=[0, 45, 0])
    suite.check('a node that happened to be selected is not un-parented to the world',
                bystander.getParent() == parent_grp, str(bystander.getParent()))
    suite.check('and the flag still gets its turn',
                abs(flag.get_align_transform().rotateY.get() - 45) < 0.01,
                str(flag.get_align_transform().rotate.get()))
    suite.check('a fresh flag is built at the top of the scene, so its align group has no parent',
                flag.get_align_transform().getParent() is None,
                str(flag.get_align_transform().getParent()))

    # -- refusals -------------------------------------------------------------------------------- #
    harness.new_scene()
    suite.raises('building a flag for something that is not there is refused',
                 frag_flag.Flag.create, 'no_such_node')
    suite.raises('and create_ratio refuses anything that is not a transform',
                 frag_flag.Flag.create_ratio, pm.createNode('multMatrix'))

    harness.new_scene()
    joint_node = pm.joint(name='b_ratio')
    suite.check('create_ratio builds a flag', frag_flag.Flag.create_ratio(joint_node) is not None)

    # -- what is and is not a flag ----------------------------------------------------------------- #
    harness.new_scene()
    plain = pm.createNode('transform', name='not_a_flag')
    suite.check('a plain transform is not a flag', frag_flag.is_flag_node(plain) is False)
    suite.check('nor is a node that is not a transform',
                frag_flag.is_flag_node(pm.createNode('multMatrix')) is False)
    suite.check('nor is nothing at all', frag_flag.is_flag_node(None) is False)


def check_flag_forwarding(suite, pm):
    from mca.mya.rigging.flags import frag_flag

    harness.new_scene()
    joint_node = pm.joint(name='b_forward')
    flag = frag_flag.Flag.create(joint_node)

    suite.check('a flag prints as the node it wraps',
                str(flag) == str(flag.node), '{0} against {1}'.format(flag, flag.node))
    suite.check('and compares equal to it', flag == flag.node)
    suite.check('and hashes the same', hash(flag) == hash(flag.node))
    suite.check('and is truthy', bool(flag) is True)
    suite.check('its repr is the node\'s', repr(flag) == repr(flag.node))
    suite.check('anything else is forwarded as well',
                flag.hasAttr(frag_flag.IS_FLAG_ATTR) is True)
    suite.check('including methods that take arguments',
                flag.attr('isDetail').get() is False)
    suite.check('and it can be used where a node is expected',
                pm.objExists(flag) and pm.PyNode(str(flag)) == flag.node)


def check_flag_shapes(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging.flags import frag_flag

    harness.new_scene()
    joint_node = pm.joint(name='b_shaped')
    flag = frag_flag.Flag.create(joint_node)

    data = frag_flag.serialize_flag(flag.node)
    suite.check('a flag serializes to one entry per shape', len(data) == 1, str(list(data)))
    curve_data = list(data.values())[0]
    suite.check('with its knots, points, degree and form',
                sorted(curve_data) == ['cvs', 'degree', 'form', 'knots'], str(sorted(curve_data)))
    suite.check('and the placeholder cube has seventeen points',
                len(curve_data['cvs']) == 17, str(len(curve_data['cvs'])))

    # -- a round trip through a file ---------------------------------------------------------- #
    flag_path = os.path.join(suite.temp, 'f_l_hand.flag').replace('\\', '/')
    suite.check('a flag exports', frag_flag.export_flag(flag.node, flag_path) is True)
    suite.check('and writes a file', os.path.isfile(flag_path))

    harness.new_scene()
    rebuilt = frag_flag.import_flag(flag_path)
    suite.check('and imports again', rebuilt is not None and pm.objExists(rebuilt))
    # The bug: deserialize_flag built the transform from the first shape and then built a second
    # copy of that same shape and parented it in alongside. Every imported flag came back drawn
    # twice, and swap_flags then moved both onto the rig's control.
    suite.check('with its shape once, not twice',
                len(rebuilt.getShapes()) == 1, str(rebuilt.getShapes()))
    suite.check('and the same number of points it went in with',
                len(rebuilt.getShape().getCVs()) == 17, str(len(rebuilt.getShape().getCVs())))

    # -- more than one shape --------------------------------------------------------------------- #
    harness.new_scene()
    first = pm.curve(degree=1, point=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 0, 0)], knot=[0, 1, 2, 3])
    second = pm.curve(degree=1, point=[(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 0, 0)], knot=[0, 1, 2, 3])
    from mca.mya.utils import dag
    dag.parent_shape_node(second, first, replace=False, swap_names=False)
    suite.check('a two-shape control is set up', len(first.getShapes()) == 2,
                str(first.getShapes()))

    two_shape_path = os.path.join(suite.temp, 'two_shapes.flag').replace('\\', '/')
    frag_flag.export_flag(first, two_shape_path)
    harness.new_scene()
    rebuilt = frag_flag.import_flag(two_shape_path)
    suite.check('a control with two shapes comes back with two',
                rebuilt is not None and len(rebuilt.getShapes()) == 2,
                str(rebuilt.getShapes() if rebuilt else None))

    # -- refusals ----------------------------------------------------------------------------------- #
    harness.new_scene()
    plain = pm.createNode('transform', name='no_shape')
    # Both of these used to return None without saying anything.
    suite.check('exporting something with no curve on it says so rather than failing quietly',
                frag_flag.export_flag(plain, os.path.join(suite.temp, 'nope.flag')) is False)
    suite.check('and writes no file',
                not os.path.isfile(os.path.join(suite.temp, 'nope.flag')))
    suite.check('importing a file that is not there answers nothing',
                frag_flag.import_flag(os.path.join(suite.temp, 'missing.flag')) is None)
    suite.check('and so does deserializing nothing', frag_flag.deserialize_flag({}) is None)

    # -- swapping a rig's shapes in ------------------------------------------------------------------- #
    harness.new_scene()
    joint_node = pm.joint(name='b_swap')
    flag = frag_flag.Flag.create(joint_node, label='l_hand')
    suite.check('the flag starts with the placeholder',
                len(flag.node.getShape().getCVs()) == 17)

    swapped = frag_flag.swap_flags([flag.node], suite.temp)
    suite.check('a saved shape is swapped in', swapped == [flag.node], str(swapped))
    suite.check('and the control is drawn with it, once',
                len(flag.node.getShapes()) == 1, str(flag.node.getShapes()))

    harness.new_scene()
    joint_node = pm.joint(name='b_unsaved')
    flag = frag_flag.Flag.create(joint_node, label='nothing_saved')
    suite.check('a control with no saved shape keeps its placeholder',
                frag_flag.swap_flags([flag.node], suite.temp) == [])
    suite.check('and is still drawn', flag.node.getShape() is not None)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_flag_mirror(suite, pm)
    check_flag_creation(suite, pm)
    check_flag_forwarding(suite, pm)
    check_flag_shapes(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('flags', body))
