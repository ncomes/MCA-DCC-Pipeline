"""
Attaching one rig to another, switching spaces, and aiming a joint - in a real Maya.

    mayapy tests/test_frag_attach_and_aim.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=2, side='left', region='eye', namespace_name=None):
    """A short marked-up chain with a root above it."""

    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    if namespace_name:
        if not cmds.namespace(exists=namespace_name):
            cmds.namespace(add=namespace_name)
        cmds.namespace(set=':{0}'.format(namespace_name))

    cmds.select(clear=True)
    joints = []
    for index in range(count + 1):
        name = 'root' if not index else 'b_{0}_{1}_{2:02d}'.format(side, region, index)
        joints.append(pm.PyNode(cmds.joint(name=name, position=(0, index * 5, 0), absolute=True)))
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
    return joints


def _rig(pm, modules, asset_id='attach_asset', namespace_name=None, **kwargs):
    """A skeleton, a rig root and a rig."""

    joints = _skeleton(pm, namespace_name=namespace_name, **kwargs)
    root_node = modules['frag_root'].FRAGRoot.create(joints[0], 'player', asset_id)
    return joints, root_node, modules['frag_rig'].FRAGRig.create(root_node)


# --------------------------------------------------------------------------------------- #
# attaching one rig to another
# --------------------------------------------------------------------------------------- #
def check_attachment(suite, pm, modules):
    attachment_component = modules['attachment_component']
    frag_base = modules['frag_base']

    harness.new_scene()
    joints, horse_root, horse_rig = _rig(pm, modules, asset_id='horse',
                                         namespace_name='horse')
    rider_joints, rider_root, rider_rig = _rig(pm, modules, asset_id='rider',
                                               namespace_name='rider')
    saddle = pm.spaceLocator(name='the_saddle')
    saddle.translate.set(0, 12, 3)
    source_component = frag_base.FRAGNode.create(horse_rig, 'KeyableComponent', 1)

    component = attachment_component.AttachmentComponent.create(
        horse_rig, 'center', 'saddle', source_component, saddle, rider_root)

    suite.check('an attachment is built', component is not None)
    suite.check('named for the side and region it is at',
                str(component.pynode).endswith('AttachmentComponent_center_saddle'),
                str(component.pynode))
    # The bug: side and region named the node and were then never recorded on it, so this was the
    # one node in a rig named for a side it could not be asked about.
    suite.check('and it carries them as markup, as every other component does',
                component.side == 'center' and component.region == 'saddle',
                '{0!r}, {1!r}'.format(component.side, component.region))

    rider_flags_all = rider_rig.flags_all
    suite.check('a group is inserted above the attached rig\'s control group',
                rider_flags_all.getParent() == component.target_parent,
                str(rider_flags_all.getParent()))
    suite.check('and that group is what follows the attachment point',
                bool(component.target_parent.listConnections(type=pm.nt.PointConstraint))
                and bool(component.target_parent.listConnections(type=pm.nt.OrientConstraint)))
    suite.check('the component remembers which rig is following',
                component.target_flags_all == rider_flags_all,
                str(component.target_flags_all))
    suite.check('and which component the attachment point belongs to',
                component.source_component == source_component,
                str(component.source_component))

    suite.check('the attached rig has been snapped onto the point',
                abs(pm.xform(rider_flags_all, query=True, worldSpace=True,
                             translation=True)[1] - 12) < 0.001,
                str(pm.xform(rider_flags_all, query=True, worldSpace=True, translation=True)))
    suite.check('and moving the point carries it',
                _follows(pm, saddle, rider_flags_all))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(attachment_component.AttachmentComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))

    # -- undoing it ------------------------------------------------------------------------ #
    was_above = component.target_parent.getParent()
    inserted = str(component.target_parent)
    component.remove()
    suite.check('removing the attachment deletes the group it inserted',
                not pm.objExists(inserted), inserted)
    suite.check('and puts the attached rig\'s control group back where it was',
                rider_flags_all.getParent() == was_above, str(rider_flags_all.getParent()))
    left_behind = [str(node) for node in pm.ls(type=pm.nt.Network)
                   if 'AttachmentComponent' in str(node)]
    suite.check('and the component with it', not left_behind, str(left_behind))
    suite.check('the attached rig no longer follows the point',
                not _follows(pm, saddle, rider_flags_all))

    # -- what it refuses ------------------------------------------------------------------- #
    harness.new_scene()
    joints, horse_root, horse_rig = _rig(pm, modules, asset_id='horse')
    bare_joints = _skeleton(pm, namespace_name='bare')
    bare_root = modules['frag_root'].FRAGRoot.create(bare_joints[0], 'player', 'bare')
    saddle = pm.spaceLocator(name='the_saddle')
    nodes_before = len(pm.ls())

    # The bug: it built its node and its buildKwargs before asking, so this left an orphan.
    refused = attachment_component.AttachmentComponent.create(
        horse_rig, 'center', 'saddle', horse_rig, saddle, bare_root)
    suite.check('a rig root with no rig under it answers nothing rather than raising',
                refused is None)
    suite.check('and leaves nothing behind in the scene',
                len(pm.ls()) == nodes_before, '{0} -> {1}'.format(nodes_before, len(pm.ls())))

    suite.check('the two misspelled attributes are kept exactly as they were, because nothing '
                'reads them and renaming them would break every rig already built',
                attachment_component.LEGACY_TARGET_PARENT_ATTR == 'attachementComponent'
                and attachment_component.LEGACY_SOURCE_PARENT_ATTR == 'sourceAttachement')


def _follows(pm, driver, driven):
    """Move the driver and see whether the driven node went with it."""

    before = pm.xform(driven, query=True, worldSpace=True, translation=True)
    driver.translate.set(driver.translate.get() + pm.dt.Vector(0, 30, 0))
    after = pm.xform(driven, query=True, worldSpace=True, translation=True)
    driver.translate.set(driver.translate.get() - pm.dt.Vector(0, 30, 0))
    return abs(after[1] - before[1]) > 25


# --------------------------------------------------------------------------------------- #
# switching spaces
# --------------------------------------------------------------------------------------- #
def check_space_switch(suite, pm, modules):
    space_switch_component = modules['space_switch_component']

    harness.new_scene()
    joints, root_node, rig = _rig(pm, modules)
    control = pm.spaceLocator(name='f_hand')
    control.translate.set(0, 10, 0)
    targets = []
    for name, position in (('the_arm', (10, 10, 0)), ('the_chest', (0, 20, 0))):
        target = pm.spaceLocator(name=name)
        target.translate.set(position)
        targets.append(target)

    component = space_switch_component.SpaceSwitchComponent.create(rig, 'left', 'hand', control,
                                                                  targets)

    suite.check('a space switch is built', component is not None)
    suite.check('named for where it is',
                str(component.pynode).endswith('SpaceSwitchComponent_left_hand'),
                str(component.pynode))
    suite.check('the control carries the enum',
                control.hasAttr(component.switch_attr), str(component.switch_attr))
    suite.check('one point constraint per space', len(component.point_constraints) == 2,
                str(component.point_constraints))
    suite.check('one orient constraint per space', len(component.orient_constraints) == 2,
                str(component.orient_constraints))
    suite.check('and one condition per space to turn its weights on',
                len(component.conditions) == 2, str(component.conditions))
    suite.check('the component remembers the control being switched',
                component.source_object == control, str(component.source_object))
    suite.check('and the node the enum went on, which defaults to the control',
                component.switch_object == control, str(component.switch_object))
    suite.check('the constraints drive a group above the control, not the control itself',
                component.switch_group is not None
                and component.switch_group != control, str(component.switch_group))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(space_switch_component.SpaceSwitchComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    # The bug: default_name was read out of **kwargs and never recorded, so a rebuild lost it.
    suite.check('including the name of the first entry of the enum',
                'default_name' in build_kwargs, str(sorted(build_kwargs)))

    # -- what it refuses ------------------------------------------------------------------- #
    # The bug: space_switch answers an empty result when there is nothing to build, and create
    # wrote that onto a node and handed back a component naming an enum that was not there.
    nodes_before = len(pm.ls())
    refused = space_switch_component.SpaceSwitchComponent.create(rig, 'left', 'hand', control,
                                                                targets)
    suite.check('a control that already has the enum on it answers nothing rather than a component '
                'recording a switch that was not built',
                refused is None)
    suite.check('and leaves nothing behind in the scene',
                len(pm.ls()) == nodes_before, '{0} -> {1}'.format(nodes_before, len(pm.ls())))

    spaceless = pm.spaceLocator(name='f_foot')
    nodes_before = len(pm.ls())
    suite.check('and so does a switch with no spaces to follow',
                space_switch_component.SpaceSwitchComponent.create(rig, 'left', 'foot', spaceless,
                                                                   []) is None)
    suite.check('leaving nothing behind either',
                len(pm.ls()) == nodes_before, '{0} -> {1}'.format(nodes_before, len(pm.ls())))

    # -- the switch actually switching ----------------------------------------------------- #
    harness.new_scene()
    joints, root_node, rig = _rig(pm, modules)
    control = pm.spaceLocator(name='f_hand')
    control.translate.set(0, 10, 0)
    arm = pm.spaceLocator(name='the_arm')
    arm.translate.set(10, 10, 0)
    chest = pm.spaceLocator(name='the_chest')
    chest.translate.set(0, 20, 0)
    component = space_switch_component.SpaceSwitchComponent.create(rig, 'left', 'hand', control,
                                                                   [arm, chest])
    switch = control.attr(component.switch_attr)
    suite.check('the enum has one entry per space, named for it',
                pm.attributeQuery(component.switch_attr, node=control,
                                  listEnum=True) == ['the_arm:the_chest'],
                str(pm.attributeQuery(component.switch_attr, node=control, listEnum=True)))

    switch.set(0)
    suite.check('with the enum on the first space, moving that space moves the control',
                _follows(pm, arm, control))
    suite.check('and the second does not', not _follows(pm, chest, control))
    switch.set(1)
    suite.check('with it on the second, the second space moves it',
                _follows(pm, chest, control))
    suite.check('while the first no longer does', not _follows(pm, arm, control))

    # default_name renames the first entry of the enum; it does not add one. A caller passes the
    # world or default node as the first space and relabels it for the animator.
    other = pm.spaceLocator(name='f_foot')
    other.translate.set(0, 2, 0)
    renamed = space_switch_component.SpaceSwitchComponent.create(rig, 'left', 'foot', other,
                                                                 [arm, chest],
                                                                 default_name='world')
    suite.check('the first entry of the enum can be relabelled',
                pm.attributeQuery(renamed.switch_attr, node=other,
                                  listEnum=True) == ['world:the_chest'],
                str(pm.attributeQuery(renamed.switch_attr, node=other, listEnum=True)))
    suite.check('and the relabelling is recorded, so a rebuild keeps it',
                renamed.get_build_kwargs().get('default_name') == 'world',
                str(renamed.get_build_kwargs().get('default_name')))


# --------------------------------------------------------------------------------------- #
# aiming a joint
# --------------------------------------------------------------------------------------- #
def check_aim(suite, pm, modules):
    aim_component = modules['aim_component']

    harness.new_scene()
    joints, root_node, rig = _rig(pm, modules, side='left', region='eye')
    eye_joint = joints[1]
    # Maya's own joint labels, so a component wiping them can be seen.
    eye_joint.attr('side').set(1)
    eye_joint.attr('type').set(18)
    eye_joint.attr('otherType').set('eye_left')
    labels_before = (eye_joint.attr('side').get(), eye_joint.attr('type').get(),
                     eye_joint.attr('otherType').get())

    component = aim_component.AimComponent.create(rig, eye_joint, 'left', 'eye', flag_distance=15)

    suite.check('an aim component is built', component is not None)
    suite.check('with one control', len(component.get_flags()) == 1, str(component.get_flags()))
    suite.check('over the joint it was given', component.bind_joints == [eye_joint],
                str(component.bind_joints))
    suite.check('the control hangs under the component\'s own control group',
                component.get_aim_flag().get_align_transform().getParent()
                == component.flag_group,
                str(component.get_aim_flag().get_align_transform().getParent()))
    suite.check('and the locator the joint follows is in the no-touch group',
                component.get_rotate_object().getParent().getParent()
                == component.no_touch_grp,
                str(component.get_rotate_object().getParent()))

    # The bug, for the third time in frag: three lines copied the control's default joint labels
    # onto the joint.
    labels_after = (eye_joint.attr('side').get(), eye_joint.attr('type').get(),
                    eye_joint.attr('otherType').get())
    suite.check('building it leaves the bind joint\'s Maya labels alone',
                labels_after == labels_before,
                '{0} -> {1}'.format(labels_before, labels_after))

    suite.check('the axes it was built with are on the node for tools to read',
                list(component.get_aim_axis()) == list(aim_component.DEFAULT_AIM_AXIS)
                and list(component.get_up_axis()) == list(aim_component.DEFAULT_UP_AXIS),
                '{0}, {1}'.format(component.get_aim_axis(), component.get_up_axis()))
    suite.check('and so is the distance the control sits at',
                abs(component.pynode.attr(aim_component.DISTANCE_ATTR).get() - 15) < 0.001,
                str(component.pynode.attr(aim_component.DISTANCE_ATTR).get()))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(aim_component.AimComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    # The bug: create took no **kwargs, so it is the one component a rebuild cannot hand a shared
    # argument list to.
    rebuilt = aim_component.AimComponent.create(rig, joints[2], 'left', 'eye_two',
                                                **dict(build_kwargs, something_else=True))
    suite.check('and a rebuild can hand over a whole argument list, extra entries and all',
                rebuilt is not None)

    # -- the joint actually aiming --------------------------------------------------------- #
    flag_node = component.get_aim_flag().node
    before = eye_joint.getRotation(space='world')
    flag_node.translate.set(flag_node.translate.get() + pm.dt.Vector(0, 10, 0))
    after = eye_joint.getRotation(space='world')
    suite.check('moving the control turns the joint',
                any(abs(after[index] - before[index]) > 1 for index in range(3)),
                '{0} -> {1}'.format(before, after))

    rotations = component.get_eye_rotations()
    suite.check('and how far it is turned can be read back', rotations is not None
                and len(rotations) == 2, str(rotations))

    # The bug: get_flags answered None for a component with no control, which the three methods
    # built on it then tried to iterate.
    component.pynode.attr(aim_component.FLAG_ATTR).disconnect()
    suite.check('a component that has lost its control answers an empty list, not None',
                component.get_flags() == [], str(component.get_flags()))
    suite.check('and the methods built on it do nothing rather than raising',
                component.select_flags() == [] and component.key_flags() == [])
    component.to_default_pose()
    suite.check('including putting it back to its default pose', True)

    suite.check('a component with no locator says so rather than raising',
                _no_locator_answers_none(component, aim_component))


def _no_locator_answers_none(component, aim_component):
    """Take the locator off and check that reading the rotation answers nothing."""

    component.pynode.attr(aim_component.ROTATE_OBJECT_ATTR).disconnect()
    return component.get_rotate_object() is None and component.get_eye_rotations() is None


def _parameters_of(function):
    """
    The names a function takes, through whatever decorators are wrapped round it.

    :param function: The function to ask.
    :return: Its parameter names.
    :rtype: set(str)
    """

    import inspect

    return set(inspect.signature(function).parameters)


def check_namespaces_and_the_registry(suite, pm, modules):
    import maya.cmds as cmds
    frag_base = modules['frag_base']

    harness.new_scene()
    if not cmds.namespace(exists='hero'):
        cmds.namespace(add='hero')
    cmds.namespace(set=':hero')
    joints, root_node, rig = _rig(pm, modules)
    control = pm.spaceLocator(name='f_hand')
    target = pm.spaceLocator(name='the_chest')
    cmds.namespace(set=':hero')

    aim = modules['aim_component'].AimComponent.create(rig, joints[1], 'left', 'eye')
    switch = modules['space_switch_component'].SpaceSwitchComponent.create(
        rig, 'left', 'hand', control, [target])
    suite.check('an aim component builds while the active namespace is already the rig\'s',
                aim is not None and aim.pynode.namespace() == 'hero:',
                str(aim.pynode.namespace()) if aim else 'None')
    suite.check('and so does a space switch',
                switch is not None and switch.pynode.namespace() == 'hero:',
                str(switch.pynode.namespace()) if switch else 'None')
    suite.check('with the active namespace put back afterwards',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
    cmds.namespace(set=':')

    for name in ('AimComponent', 'SpaceSwitchComponent', 'AttachmentComponent'):
        suite.check('{0} is in the registry, so a rig carrying one can be read back'.format(name),
                    name in frag_base.FRAGNodeRegister.__frag_node_types__,
                    str(sorted(frag_base.FRAGNodeRegister.__frag_node_types__)))
    suite.check('and an aim component read back out of a scene comes back as one',
                type(frag_base.FRAGNode(aim.pynode)) is modules['aim_component'].AimComponent,
                str(type(frag_base.FRAGNode(aim.pynode))))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import aim_component
    from mca.mya.rigging.frag import attachment_component
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import space_switch_component

    modules = {'aim_component': aim_component, 'attachment_component': attachment_component,
               'frag_base': frag_base, 'frag_rig': frag_rig, 'frag_root': frag_root,
               'space_switch_component': space_switch_component}

    check_attachment(suite, pm, modules)
    check_space_switch(suite, pm, modules)
    check_aim(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_attach_and_aim', body))
