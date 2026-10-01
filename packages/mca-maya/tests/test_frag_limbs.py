"""
The three components a limb is built from - FK, IK and the blend between them - in a real Maya.

    mayapy tests/test_frag_limbs.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _parameters_of(function):
    """
    The names a function takes, through whatever decorators are wrapped round it.

    :param function: The function to ask.
    :return: Its parameter names.
    :rtype: set(str)
    """

    import inspect

    return set(inspect.signature(function).parameters)


def _skeleton(pm, count=3, side='left', region='arm', namespace_name=None, labelled=False):
    """
    A marked-up chain of joints with a bend in it, so a pole vector can be read from it.

    :param int count: How many joints below the root.
    :param str side: The side to mark the chain up as.
    :param str region: The region to mark it up as.
    :param str namespace_name: A namespace to build it in.
    :param bool labelled: Give the joints Maya joint labels too, so that a component wiping them
        can be seen.
    :return: The root, then the chain.
    :rtype: list(pm.nt.Joint)
    """

    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    if namespace_name:
        if not cmds.namespace(exists=namespace_name):
            cmds.namespace(add=namespace_name)
        cmds.namespace(set=':{0}'.format(namespace_name))

    # Straight along Y with the middle joints pushed out in Z: a bend, which the pole vector needs.
    positions = [(0, 0, 0)]
    for index in range(count):
        positions.append((0, (index + 1) * 10, 5 if 0 < index < count - 1 else 0))

    cmds.select(clear=True)
    joints = []
    for index, position in enumerate(positions):
        name = 'root' if not index else 'b_{0}_{1}_{2:02d}'.format(side, region, index)
        joints.append(pm.PyNode(cmds.joint(name=name, position=position, absolute=True)))
    cmds.namespace(set=':')

    chain = joints[1:]
    for index, joint_node in enumerate(chain):
        markup = chain_markup.JointMarkup(joint_node)
        markup.side = side
        markup.region = region
        if not index:
            markup.chainStart = region
        if index == len(chain) - 1:
            markup.chainEnd = region
        if labelled:
            # Maya's own joint label: side 1 is left, type 18 is 'other' with a name on it.
            joint_node.attr('side').set(1)
            joint_node.attr('type').set(18)
            joint_node.attr('otherType').set('{0}_{1}_{2}'.format(side, region, index))
    return joints


def _rig(pm, frag_root, frag_rig, joints, asset_id='limb_asset'):
    """A rig root and a rig over a skeleton, which is what a component needs above it."""

    root_node = frag_root.FRAGRoot.create(joints[0], 'player', asset_id)
    return root_node, frag_rig.FRAGRig.create(root_node)


# --------------------------------------------------------------------------------------- #
# the shared helpers
# --------------------------------------------------------------------------------------- #
def check_the_shared_helpers(suite, pm, modules):
    keyable_component = modules['keyable_component']
    fk_component = modules['fk_component']
    chain_markup = modules['chain_markup']

    harness.new_scene()
    joints = _skeleton(pm)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')

    other = _skeleton(pm, side='left', region='arm', namespace_name='mocap')
    found = component.matching_chain(other[0])
    suite.check('a component finds the run of joints on another skeleton that it belongs over',
                found == other[1:], str(found))

    # The region and side come off the joints, not off the component: a component built as one side
    # over joints marked up as another follows the joints.
    for joint_node in other[1:]:
        chain_markup.JointMarkup(joint_node).region = 'arm'
    wrong_side = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'right', 'arm')
    suite.check('and reads which chain to look for off the joints it drives rather than off its '
                'own markup',
                wrong_side.matching_chain(other[0]) == other[1:],
                str(wrong_side.matching_chain(other[0])))

    empty = modules['frag_base'].FRAGNode.create(rig, 'KeyableComponent', 1)
    suite.check('a skeleton with nothing matching answers an empty list rather than None',
                keyable_component.KeyableComponent(empty.pynode).matching_chain(other[0]) == [],
                str(keyable_component.KeyableComponent(empty.pynode).matching_chain(other[0])))

    # -- the pole vector ------------------------------------------------------------------- #
    flag = modules['frag_flag'].Flag.create(other[2], label='a_pv')
    constraint_node = keyable_component.constrain_to_pole_vector(other[1:4], flag)
    suite.check('a pole vector control is driven by a locator put where the bend says it should be',
                constraint_node is not None)
    locator = constraint_node.getTargetList()[0]
    suite.check('the locator travels with the middle joint of the three',
                locator.getParent() == other[2], str(locator.getParent()))
    suite.check('and is marked as a bake helper, so the bake can clear it away afterwards',
                locator.hasAttr(keyable_component.BAKE_HELPER_ATTR)
                and locator.attr(keyable_component.BAKE_HELPER_ATTR).get() is True)

    # The bug: create_pole_vector_locator answers None for a chain of fewer than three joints, and
    # the next line called setParent on it.
    before = len(pm.ls(type=pm.nt.ParentConstraint))
    suite.check('a chain too short for a pole vector answers nothing rather than raising',
                keyable_component.constrain_to_pole_vector(other[1:3], flag) is None)
    suite.check('and builds no constraint on the way',
                len(pm.ls(type=pm.nt.ParentConstraint)) == before)


# --------------------------------------------------------------------------------------- #
# FK
# --------------------------------------------------------------------------------------- #
def check_fk(suite, pm, modules):
    fk_component = modules['fk_component']
    frag_base = modules['frag_base']

    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm',
                                                scale=2.5)

    suite.check('an FK component is built', component is not None)
    flags = component.get_flags()
    suite.check('with one control per joint it drives', len(flags) == 4, str(flags))
    suite.check('the controls are nested, so turning the first carries the rest',
                flags[1].get_align_transform().getParent() == flags[0].node,
                str(flags[1].get_align_transform().getParent()))
    suite.check('the first control hangs under the component\'s own control group',
                flags[0].get_align_transform().getParent() == component.flag_group,
                str(flags[0].get_align_transform().getParent()))
    suite.check('the joints it drives are on it', component.bind_joints == joints[1:],
                str(component.bind_joints))
    suite.check('and it drives a duplicate of them rather than them directly',
                all(constraint_node.getTargetList()[0] not in joints
                    for constraint_node in pm.ls(type=pm.nt.ParentConstraint)
                    if constraint_node.getParent() in joints))

    # -- what a rebuild gets back ---------------------------------------------------------- #
    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(fk_component.FKComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters,
                str(sorted(set(build_kwargs) - parameters)))
    # The bug: constrain_scale was written down as allow_scale, which is not a parameter - so a
    # rebuild passed it into **kwargs and dropped it, and the component came back unable to scale.
    suite.check('the scale setting is recorded under the name it goes back in through',
                'constrain_scale' in build_kwargs, str(sorted(build_kwargs)))
    suite.check('and the control size is recorded at all', build_kwargs.get('scale') == 2.5,
                str(build_kwargs.get('scale')))

    # -- the offset control ---------------------------------------------------------------- #
    suite.check('a component built without an offset control has none',
                component.get_offset_flag() is None)

    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    # The bug: this raised 'RuntimeError (kFailure): Object does not exist' every time, because
    # offsetFlag was pre-added as a non-multi and then wired with connect_nodes, which hands a list.
    with_offset = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm',
                                                  offset_flag=True)
    offset_flag = with_offset.get_offset_flag()
    suite.check('building with an offset control now works at all', offset_flag is not None)
    suite.check('and it comes back as a Flag rather than a raw node',
                hasattr(offset_flag, 'lock_and_hide_attrs'), str(type(offset_flag)))

    # -- locking --------------------------------------------------------------------------- #
    flags = with_offset.get_flags()
    suite.check('the root control has its translate locked by default',
                all(flags[0].node.attr(axis).isLocked() for axis in ('tx', 'ty', 'tz')))
    suite.check('and so does every control under it',
                all(flags[-1].node.attr(axis).isLocked() for axis in ('tx', 'ty', 'tz')))
    suite.check('visibility is taken off every control',
                all(not flag.node.visibility.isInChannelBox() for flag in flags))

    # -- the scale wiring ------------------------------------------------------------------ #
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    plain = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')
    suite.check('a component not built to carry scale leaves its group\'s scale alone',
                not plain.no_touch_grp.scaleX.listConnections())

    scaling = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'right', 'arm',
                                              constrain_scale=True,
                                              lock_child_scale_axes=())
    multi = scaling.no_touch_grp.scaleX.listConnections()
    suite.check('a component built to carry scale is held at a constant size by a divide node',
                len(multi) == 1 and isinstance(multi[0], pm.nt.MultiplyDivide), str(multi))
    suite.check('reading the rig\'s scale, so the two do not multiply',
                multi[0].input2X.listConnections(plugs=True)[0]
                == rig.pynode.attr(modules['frag_rig'].RIG_SCALE_ATTR),
                str(multi[0].input2X.listConnections(plugs=True)))
    suite.check('and the component\'s scale is carried onto the joints it drives',
                joints[2].scale.listConnections(destination=False))

    other_scaling = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'center', 'arm',
                                                   constrain_scale=True)
    suite.check('a second component in the same rig shares the one divide node',
                other_scaling.no_touch_grp.scaleX.listConnections() == multi,
                str(other_scaling.no_touch_grp.scaleX.listConnections()))

    # The bug: set_scale read frag_rig.pynode.rigScale without asking, which used to be hidden by
    # reading FRAGRig.rig_scale adding the attribute as a side effect.
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    rig.pynode.deleteAttr(modules['frag_rig'].RIG_SCALE_ATTR)
    unwired = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm',
                                              constrain_scale=True)
    suite.check('a rig with no scale attribute leaves the component unwired rather than raising',
                not unwired.no_touch_grp.scaleX.listConnections())
    rig.add_rig_scale()
    unwired.set_scale()
    suite.check('and adding the attribute afterwards wires it',
                len(unwired.no_touch_grp.scaleX.listConnections()) == 1)

    # A component built before the name was corrected still answers.
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    legacy = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')
    pm.renameAttr(legacy.pynode.attr('{0}_constrain_scale'.format(frag_base.BUILD_KWARGS_ATTR)),
                  fk_component.LEGACY_SCALE_KWARG)
    legacy.pynode.attr(fk_component.LEGACY_SCALE_KWARG).set(True)
    legacy.set_scale()
    suite.check('a component built under the old attribute name still has its scale wired',
                len(legacy.no_touch_grp.scaleX.listConnections()) == 1)

    # -- the two swapped names ------------------------------------------------------------- #
    ordered = legacy.get_flags()
    suite.check('the controls come back root first',
                ordered[0].get_align_transform().getParent() == legacy.flag_group,
                str(ordered[0].get_align_transform().getParent()))
    suite.check('get_start_flag still answers the last control, as the templates expect',
                legacy.get_start_flag() == ordered[-1])
    suite.check('and get_end_flag the first', legacy.get_end_flag() == ordered[0])

    # -- being driven by a skeleton -------------------------------------------------------- #
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm',
                                                lock_child_scale_axes=(),
                                                lock_root_scale_axes=())
    mocap = _skeleton(pm, count=4, namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('every control is driven by the matching joint on the other skeleton',
                len(constraints) == 4, str(constraints))
    suite.check('and each control\'s scale follows its joint\'s',
                component.get_flags()[0].node.scaleX.listConnections() == [mocap[1]],
                str(component.get_flags()[0].node.scaleX.listConnections()))

    elsewhere = _skeleton(pm, count=3, side='center', region='tail', namespace_name='other')
    suite.check('a skeleton with nothing matching drives nothing, without raising',
                component.attach_to_skeleton(elsewhere[0]) == [])

    # The bug: `if flag_list and len(flag_list) <= len(joint_list)` attached nothing, silently,
    # when the rig had more controls than the skeleton had joints.
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    long_component = fk_component.FKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')
    short = _skeleton(pm, count=2, namespace_name='short')
    constraints = long_component.attach_to_skeleton(short[0])
    suite.check('a rig with more controls than the skeleton has joints drives as many as it can '
                'rather than none',
                len(constraints) == 2, str(constraints))


# --------------------------------------------------------------------------------------- #
# IK
# --------------------------------------------------------------------------------------- #
def check_ik(suite, pm, modules):
    ik_component = modules['ik_component']
    ik_chain = modules['ik_chain']

    harness.new_scene()
    joints = _skeleton(pm, count=3, labelled=True)
    labels_before = [(joint_node.attr('side').get(), joint_node.attr('type').get(),
                      joint_node.attr('otherType').get()) for joint_node in joints[1:]]
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = ik_component.IKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')

    suite.check('an IK component is built', component is not None)
    suite.check('with a control for the end of the limb', component.ik_flag is not None)
    suite.check('a detail control under it', component.ik_flag_offset is not None)
    suite.check('and one for which way the middle bends', component.pv_flag is not None)
    suite.check('all three come back as its controls', len(component.get_flags()) == 3,
                str(component.get_flags()))
    suite.check('the joints it drives are on it', component.bind_joints == joints[1:],
                str(component.bind_joints))

    # The bug: six lines copied the controls' default joint labels onto the middle and end joints.
    labels_after = [(joint_node.attr('side').get(), joint_node.attr('type').get(),
                     joint_node.attr('otherType').get()) for joint_node in joints[1:]]
    suite.check('building it leaves the bind joints\' Maya labels alone',
                labels_after == labels_before, '{0} -> {1}'.format(labels_before, labels_after))

    suite.check('the pole vector line is shown and hidden with the control it points at',
                component.pynode.attr(ik_component.PV_LINE_ATTR).get().visibility
                in component.pv_flag.node.visibility.listConnections(plugs=True))
    suite.check('the handle\'s align group is hidden, so the animator cannot grab it',
                not component.pynode.attr(ik_component.IK_HANDLE_ATTR).get()
                .getParent().visibility.get())
    suite.check('the IK control cannot be scaled',
                all(component.ik_flag.node.attr(axis).isLocked()
                    for axis in ik_component.IK_FLAG_LOCKED_ATTRS))
    suite.check('and the pole vector control cannot be turned',
                all(component.pv_flag.node.attr(axis).isLocked()
                    for axis in ik_component.PV_FLAG_LOCKED_ATTRS))

    # -- the chain length guard ------------------------------------------------------------ #
    harness.new_scene()
    joints = _skeleton(pm, count=5)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    nodes_before = len(pm.ls())
    message = suite.raises('a chain of the wrong length is refused',
                           ik_component.IKComponent.create, rig, joints[1], joints[-1], 'left',
                           'arm')
    suite.check('and the refusal names the joints and the count it got',
                str(joints[1]) in message and '5' in message, message)
    suite.check('nothing is left behind in the scene when it refuses',
                len(pm.ls()) == nodes_before, '{0} -> {1}'.format(nodes_before, len(pm.ls())))

    # -- a four joint chain ---------------------------------------------------------------- #
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    four = ik_component.IKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')
    suite.check('a four joint chain is built on too, which is a leg with a ball joint',
                four is not None)
    driven = [constraint_node.getParent() for constraint_node
              in pm.ls(type=pm.nt.ParentConstraint)
              if constraint_node.getParent() in joints]
    suite.check('and only the three the IK solves over are constrained to it',
                sorted(set(driven), key=joints.index) == joints[1:4], str(driven))

    # -- being driven by a skeleton -------------------------------------------------------- #
    mocap = _skeleton(pm, count=4, namespace_name='mocap')
    constraints = four.attach_to_skeleton(mocap[0])
    suite.check('the end control and the pole vector are both driven', len(constraints) == 2,
                str(constraints))

    # The bug: attach_to_skeleton read joint_list[1] without asking how long the chain was.
    harness.new_scene()
    joints = _skeleton(pm, count=3)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    short = _skeleton(pm, count=2, namespace_name='short')
    short_component = ik_component.IKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')
    suite.check('a skeleton too short to read a pole vector from drives nothing rather than '
                'raising',
                short_component.attach_to_skeleton(short[0]) == [])
    suite.check('and the length it asks for is ik_chain\'s own minimum',
                ik_chain.VALID_CHAIN_LENGTHS[0] == 3)


# --------------------------------------------------------------------------------------- #
# IK/FK
# --------------------------------------------------------------------------------------- #
def check_ikfk(suite, pm, modules):
    ikfk_component = modules['ikfk_component']

    harness.new_scene()
    joints = _skeleton(pm, count=3, labelled=True)
    labels_before = [(joint_node.attr('side').get(), joint_node.attr('type').get(),
                      joint_node.attr('otherType').get()) for joint_node in joints[1:]]
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = ikfk_component.IKFKComponent.create(rig, joints[1], joints[-1], 'left', 'arm',
                                                    scale=1.5)

    suite.check('an IKFK component is built', component is not None)
    suite.check('with an FK control per joint', len(component.fk_flags) == 3,
                str(component.fk_flags))
    suite.check('an IK control, its offset and a pole vector', len(component.ik_flags) == 3,
                str(component.ik_flags))
    suite.check('and a switch control to fade between them', component.switch_flag is not None)
    suite.check('every one of them comes back as a control', len(component.get_flags()) == 8,
                str(component.get_flags()))
    suite.check('the name of the switch attribute is written down',
                component.switch_flag.node.hasAttr(component.switch_attr_name),
                str(component.switch_attr_name))

    # The bug: three lines copied the IK offset control's default joint labels onto the end joint.
    labels_after = [(joint_node.attr('side').get(), joint_node.attr('type').get(),
                     joint_node.attr('otherType').get()) for joint_node in joints[1:]]
    suite.check('building it leaves the bind joints\' Maya labels alone',
                labels_after == labels_before, '{0} -> {1}'.format(labels_before, labels_after))

    # -- the blend ------------------------------------------------------------------------- #
    invert_node = component.pynode.attr(ikfk_component.INVERT_NODE_ATTR).get()
    switch_attr = component.switch_flag.node.attr(component.switch_attr_name)
    suite.check('the switch attribute drives the node both readings come from',
                invert_node in switch_attr.listConnections())

    orient_constraints = [constraint_node for constraint_node
                          in pm.ls(type=pm.nt.OrientConstraint)
                          if constraint_node.getParent() in joints]
    suite.check('each bind joint is blended between the two chains', len(orient_constraints) == 3,
                str(orient_constraints))
    weights = orient_constraints[0].getWeightAliasList()
    suite.check('the FK weight is driven by the inverted reading of the switch',
                invert_node.inverse in weights[0].listConnections(plugs=True),
                str(weights[0].listConnections(plugs=True)))
    suite.check('and the IK weight by the straight one',
                invert_node.straight in weights[1].listConnections(plugs=True),
                str(weights[1].listConnections(plugs=True)))

    switch_attr.set(1)
    suite.check('with the switch all the way over, the IK weight is on and the FK weight off',
                weights[1].get() == 1 and weights[0].get() == 0,
                '{0}, {1}'.format(weights[1].get(), weights[0].get()))
    switch_attr.set(0)
    suite.check('and the other way round at zero',
                weights[0].get() == 1 and weights[1].get() == 0,
                '{0}, {1}'.format(weights[0].get(), weights[1].get()))

    suite.check('exactly one set of controls is visible at a time',
                invert_node.straight in
                component.ik_flag.node.visibility.listConnections(plugs=True)
                and invert_node.inverse in
                component.fk_flags[0].node.visibility.listConnections(plugs=True))
    suite.check('the hinge control bends on one axis only',
                all(component.fk_flags[ikfk_component.HINGE_FLAG_INDEX].node.attr(axis).isLocked()
                    for axis in ikfk_component.HINGE_LOCKED_ATTRS))
    suite.check('the group holding the two driver chains is visible, so the pole vector line can '
                'be seen',
                component.no_touch_grp.visibility.get() is True)
    suite.check('while the chains themselves are not',
                not component.pynode.attr(ikfk_component.FK_CHAIN_ATTR).get()[0].visibility.get())

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(ikfk_component.IKFKComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters,
                str(sorted(set(build_kwargs) - parameters)))
    # The bug: the control size was never written down, so a rebuild drew default-sized controls.
    suite.check('and the control size is recorded', build_kwargs.get('scale') == 1.5,
                str(build_kwargs.get('scale')))

    # -- get_flags with a control missing -------------------------------------------------- #
    # The bug: it wrapped every one of six attribute reads in Flag, including the empty ones.
    component.pynode.attr(ikfk_component.PV_FLAG_ATTR).disconnect()
    suite.check('a component that has lost a control leaves it out rather than raising from '
                'inside the wrapper',
                len(component.get_flags()) == 7, str(component.get_flags()))

    # -- the chain length guard ------------------------------------------------------------ #
    harness.new_scene()
    joints = _skeleton(pm, count=5)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    nodes_before = len(pm.ls())
    message = suite.raises('a chain of the wrong length is refused',
                           ikfk_component.IKFKComponent.create, rig, joints[1], joints[-1],
                           'left', 'arm')
    suite.check('and the refusal names the joints and the count it got',
                str(joints[1]) in message and '5' in message, message)
    suite.check('nothing is left behind in the scene when it refuses',
                len(pm.ls()) == nodes_before, '{0} -> {1}'.format(nodes_before, len(pm.ls())))

    # -- being driven by a skeleton -------------------------------------------------------- #
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = ikfk_component.IKFKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')
    mocap = _skeleton(pm, count=4, namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('both halves are driven: four FK controls, the IK control and the pole vector',
                len(constraints) == 6, str(constraints))

    harness.new_scene()
    joints = _skeleton(pm, count=3)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    short = _skeleton(pm, count=2, namespace_name='short')
    short_component = ikfk_component.IKFKComponent.create(rig, joints[1], joints[-1], 'left',
                                                          'arm')
    suite.check('a skeleton too short for the IK half drives nothing rather than raising on '
                'joint_list[2]',
                short_component.attach_to_skeleton(short[0]) == [])


# --------------------------------------------------------------------------------------- #
# the update path
# --------------------------------------------------------------------------------------- #
def check_the_migration(suite, pm, modules):
    ikfk_component = modules['ikfk_component']

    harness.new_scene()
    joints = _skeleton(pm, count=3)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    component = ikfk_component.IKFKComponent.create(rig, joints[1], joints[-1], 'left', 'arm')

    suite.check('a component is built at its class\'s version',
                component.get_version() == ikfk_component.IKFKComponent.VERSION,
                str(component.get_version()))

    # Put it back the way version 1 left it: four attributes under their snake_case names, and the
    # version on the node as the double 1.0 a real version 1 rig carries.
    connected = {}
    for legacy_name, attr_name in ikfk_component.IKFKComponent.LEGACY_ATTR_NAMES.items():
        connected[legacy_name] = component.pynode.attr(attr_name).get()
        pm.renameAttr(component.pynode.attr(attr_name), legacy_name)
    component.set_version(1)

    suite.check('a version 1 component is recognised as out of date',
                int(component.get_version()) < int(ikfk_component.IKFKComponent.VERSION))
    component.update()

    suite.check('updating it brings it to the current version',
                int(component.get_version()) == int(ikfk_component.IKFKComponent.VERSION),
                str(component.get_version()))
    suite.check('every snake_case attribute is gone',
                not any(component.pynode.hasAttr(name) for name
                        in ikfk_component.IKFKComponent.LEGACY_ATTR_NAMES))
    suite.check('each one is there under its camelCase name',
                all(component.pynode.hasAttr(name) for name
                    in ikfk_component.IKFKComponent.LEGACY_ATTR_NAMES.values()))
    suite.check('and still wired to what it was wired to - the step renames rather than rewires',
                all(component.pynode.attr(
                    ikfk_component.IKFKComponent.LEGACY_ATTR_NAMES[legacy_name]).get() == node
                    for legacy_name, node in connected.items()),
                str(connected))

    # Running it a second time is a no-op rather than an error.
    component.update()
    suite.check('updating an up-to-date component does nothing',
                int(component.get_version()) == int(ikfk_component.IKFKComponent.VERSION))


# --------------------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------------------- #
def check_the_registry(suite, pm, modules):
    frag_base = modules['frag_base']

    harness.new_scene()
    joints = _skeleton(pm, count=3)
    root_node, rig = _rig(pm, modules['frag_root'], modules['frag_rig'], joints)
    built = modules['ikfk_component'].IKFKComponent.create(rig, joints[1], joints[-1], 'left',
                                                           'arm')
    found = frag_base.FRAGNode(built.pynode)
    suite.check('a component read back out of a scene comes back as its own class',
                type(found) is modules['ikfk_component'].IKFKComponent, str(type(found)))

    for class_name in ('FKComponent', 'IKComponent', 'IKFKComponent'):
        suite.check('{0} is in the registry, so a rig carrying one can be read back'.format(
            class_name),
            class_name in frag_base.FRAGNodeRegister.__frag_node_types__,
            str(sorted(frag_base.FRAGNodeRegister.__frag_node_types__)))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging import chain_markup
    from mca.mya.rigging import ik_chain
    from mca.mya.rigging.flags import frag_flag
    from mca.mya.rigging.frag import fk_component
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import ik_component
    from mca.mya.rigging.frag import ikfk_component
    from mca.mya.rigging.frag import keyable_component

    modules = {'chain_markup': chain_markup, 'ik_chain': ik_chain, 'frag_flag': frag_flag,
               'fk_component': fk_component, 'frag_base': frag_base, 'frag_rig': frag_rig,
               'frag_root': frag_root, 'ik_component': ik_component,
               'ikfk_component': ikfk_component, 'keyable_component': keyable_component}

    check_the_shared_helpers(suite, pm, modules)
    check_fk(suite, pm, modules)
    check_ik(suite, pm, modules)
    check_ikfk(suite, pm, modules)
    check_the_migration(suite, pm, modules)
    check_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_limbs', body))
