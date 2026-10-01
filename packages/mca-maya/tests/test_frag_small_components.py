"""
Three small components - the twist fix-up, the camera and the set driven key - in a real Maya.

    mayapy tests/test_frag_small_components.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _chain(pm, names, step=10):
    """A chain of joints along X."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    return [pm.PyNode(cmds.joint(name=name, position=(index * step, 0, 0), absolute=True))
            for index, name in enumerate(names)]


def _twist_skeleton(pm, twist_count=2):
    """An arm with a marked-up forearm segment and twist joints hanging off the elbow."""

    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    root, shoulder, elbow, wrist = _chain(pm, ['b_root', 'b_l_shoulder', 'b_l_elbow', 'b_l_wrist'])
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


def _rig(pm, modules, root_joint, asset_id='small_asset'):
    """A rig root and a rig over a skeleton."""

    root_node = modules['frag_root'].FRAGRoot.create(root_joint, 'player', asset_id)
    return root_node, modules['frag_rig'].FRAGRig.create(root_node)


# --------------------------------------------------------------------------------------- #
# the twist fix-up
# --------------------------------------------------------------------------------------- #
def check_twist(suite, pm, modules):
    twist_fixup_component = modules['twist_fixup_component']

    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=2)
    root_node, rig = _rig(pm, modules, skeleton['root'])
    component = twist_fixup_component.TwistFixUpComponent.create(rig, skeleton['twists'], 'left',
                                                                 'forearm')

    suite.check('a twist component is built', component is not None)
    suite.check('it has no controls, because an animator never touches it',
                not hasattr(component, 'flag_group'))
    suite.check('the joints it drives are on it',
                component.bind_joints == skeleton['twists'], str(component.bind_joints))
    suite.check('the setup is in its no-touch group',
                component.twist_group.getParent() == component.no_touch_grp,
                str(component.twist_group.getParent()))
    suite.check('and each twist joint is driven by a channel of the one multiply node',
                all(component.multi_node in twist.rotateX.listConnections(source=True,
                                                                         destination=False)
                    or component.multi_node in
                    pm.listHistory(twist.rotateX.listConnections(source=True, destination=False))
                    for twist in skeleton['twists']),
                str([twist.rotateX.listConnections() for twist in skeleton['twists']]))
    suite.check('the single nodes it records are single attributes, not lists of one',
                not component.pynode.attr(twist_fixup_component.MULTI_NODE_ATTR).isMulti()
                and not component.pynode.attr(twist_fixup_component.IK_HANDLE_ATTR).isMulti())
    suite.check('while the chains stay lists',
                component.pynode.attr(twist_fixup_component.MIRROR_CHAIN_ATTR).isMulti()
                and component.pynode.attr(twist_fixup_component.IK_CHAIN_ATTR).isMulti())

    # -- the version migration that was never written -------------------------------------- #
    suite.check('the component is built at its class\'s version',
                int(component.get_version()) == int(twist_fixup_component
                                                    .TwistFixUpComponent.VERSION))
    component.set_version(1)
    # The bug: VERSION is 2 and there was no _update_version_1_to_version_2 anywhere in the class
    # or its parents, so updating any twist component raised AttributeError - and
    # update_all_frag_nodes walks a whole rig.
    component.update()
    suite.check('a version 1 twist component can be brought up to date, which it could not before',
                int(component.get_version()) == 2, str(component.get_version()))

    # -- what it refuses ------------------------------------------------------------------- #
    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=2)
    root_node, rig = _rig(pm, modules, skeleton['root'])
    suite.check('no joints to drive answers nothing rather than raising on joint_list[0]',
                twist_fixup_component.TwistFixUpComponent.create(rig, [], 'left',
                                                                 'forearm') is None)
    suite.check('and builds no component node at all',
                not pm.ls('TwistFixUpComponent_left_forearm'),
                str(pm.ls('TwistFixUpComponent_left_forearm')))

    # The bug: a setup that could not be built left a component with nothing on it.
    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=4)
    root_node, rig = _rig(pm, modules, skeleton['root'])
    suite.check('more twist joints than one multiplyDivide can drive answers nothing rather than a '
                'component recording a setup that is not there',
                twist_fixup_component.TwistFixUpComponent.create(rig, skeleton['twists'], 'left',
                                                                 'forearm') is None)
    suite.check('and takes its own node and group back out of the scene',
                not pm.ls('TwistFixUpComponent_left_forearm')
                and not pm.ls('NO_TOUCH_left_forearm'),
                str(pm.ls('TwistFixUpComponent_left_forearm')
                    + pm.ls('NO_TOUCH_left_forearm')))

    # The bug: the alignment is joint_list[0].getParent().getParent(), two unguarded reads.
    harness.new_scene()
    joints = _chain(pm, ['b_root', 'b_lonely'])
    root_node, rig = _rig(pm, modules, joints[0])
    suite.check('a twist joint with nothing two levels above it does not raise while the component '
                'is being aligned',
                twist_fixup_component.TwistFixUpComponent.create(rig, [joints[1]], 'left',
                                                                 'forearm') is None)

    # RigComponent can be removed now, which is what a component that cannot finish needs.
    harness.new_scene()
    skeleton = _twist_skeleton(pm, twist_count=2)
    root_node, rig = _rig(pm, modules, skeleton['root'])
    component = twist_fixup_component.TwistFixUpComponent.create(rig, skeleton['twists'], 'left',
                                                                 'forearm')
    node_name = str(component.pynode)
    group_name = str(component.no_touch_grp)
    component.remove()
    suite.check('a component with no controls can be removed, which it could not before',
                not pm.objExists(node_name) and not pm.objExists(group_name),
                '{0}, {1}'.format(node_name, group_name))


# --------------------------------------------------------------------------------------- #
# the camera
# --------------------------------------------------------------------------------------- #
def check_camera(suite, pm, modules):
    camera_component = modules['camera_component']
    fk_component = modules['fk_component']
    frag_base = modules['frag_base']

    harness.new_scene()
    joints = _chain(pm, ['b_root', 'b_cam'])
    root_node, rig = _rig(pm, modules, joints[0])
    camera = pm.camera(name='the_camera')[0]

    component = camera_component.CameraComponent.create(rig, joints[1], 'center', 'shot', camera,
                                                        scale=3.0)

    suite.check('a camera component is built', component is not None)
    suite.check('it is an FK component underneath',
                isinstance(component, fk_component.FKComponent))
    suite.check('carrying its own class name', component.pynode.attr(
        frag_base.FRAG_TYPE_ATTR).get() == 'CameraComponent',
        str(component.pynode.attr(frag_base.FRAG_TYPE_ATTR).get()))
    suite.check('and named for it',
                str(component.pynode) == 'CameraComponent_center_shot', str(component.pynode))

    # The bug: the class spelled its version LATEST_VERSION, so CameraComponent.VERSION was
    # FKComponent's. Both are 1, which is the only reason nothing has gone wrong yet.
    suite.check('the version is spelled VERSION, as on every other component',
                'VERSION' in vars(camera_component.CameraComponent),
                str(sorted(vars(camera_component.CameraComponent))))
    suite.check('and the node is built at it',
                int(component.get_version()) == int(camera_component.CameraComponent.VERSION))

    suite.check('the camera is on the component', component.get_cam() == camera,
                str(component.get_cam()))
    suite.check('driven by the component\'s control',
                bool(camera.listConnections(type=pm.nt.ParentConstraint)))
    flag_node = component.get_cam_flag().node
    suite.check('a camera control keeps its translate channels, because a camera moves',
                not any(flag_node.attr(axis).isLocked() for axis in ('tx', 'ty', 'tz')))
    suite.check('and moving it moves the camera', _follows(pm, flag_node, camera))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(camera_component.CameraComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    suite.check('including the control size', build_kwargs.get('scale') == 3.0,
                str(build_kwargs.get('scale')))
    # The bug: create took no **kwargs, so a rebuild handing over a recorded argument list - which
    # was FKComponent's, since this class did not replace the block - was a TypeError.
    rebuilt = camera_component.CameraComponent.create(rig, joints[1], 'center', 'shot_two', camera,
                                                      **dict(build_kwargs, something_else=True))
    suite.check('and a rebuild can hand over a whole argument list, extra entries and all',
                rebuilt is not None)

    suite.check('read back out of a scene it comes back as a camera component',
                type(frag_base.FRAGNode(component.pynode))
                is camera_component.CameraComponent,
                str(type(frag_base.FRAGNode(component.pynode))))

    # The bug: parent_constraint_safe answers None when every channel is locked, and that went
    # straight into connect_node, which puts it through pm.PyNode - and pm.PyNode(None) raises.
    harness.new_scene()
    joints = _chain(pm, ['b_root', 'b_cam'])
    root_node, rig = _rig(pm, modules, joints[0])
    camera = pm.camera(name='the_camera')[0]
    for axis in ('tx', 'ty', 'tz', 'rx', 'ry', 'rz'):
        camera.attr(axis).lock()
    locked = camera_component.CameraComponent.create(rig, joints[1], 'center', 'shot', camera)
    suite.check('a camera with no channel free to be driven says so rather than raising',
                locked is not None)
    suite.check('and the component is still built, with the camera on it',
                locked.get_cam() == camera, str(locked.get_cam()))


def _follows(pm, driver, driven):
    """Move the driver and see whether the driven node went with it."""

    before = pm.xform(driven, query=True, worldSpace=True, translation=True)
    driver.translate.set(driver.translate.get() + pm.dt.Vector(0, 30, 0))
    after = pm.xform(driven, query=True, worldSpace=True, translation=True)
    driver.translate.set(driver.translate.get() - pm.dt.Vector(0, 30, 0))
    return abs(after[1] - before[1]) > 25


# --------------------------------------------------------------------------------------- #
# the set driven key
# --------------------------------------------------------------------------------------- #
def check_sdk(suite, pm, modules):
    s_sdk_component = modules['s_sdk_component']
    frag_base = modules['frag_base']

    harness.new_scene()
    joints = _chain(pm, ['b_root', 'b_jaw'])
    root_node, rig = _rig(pm, modules, joints[0])

    driver = pm.spaceLocator(name='f_jaw')
    driver.addAttr('openClose', at='double', min=0, max=10, dv=0, keyable=True)
    driven = pm.spaceLocator(name='the_tongue')

    component = s_sdk_component.SingleSDKComponent.create(
        rig, driver.attr('openClose'), driven, 'center', 'jaw',
        driven_attrs={'start': {'translateY': 0.0, 'rotateX': 0.0},
                      'end': {'translateY': 5.0, 'rotateX': -30.0}},
        drive_attr_values=(0, 10))

    suite.check('a set driven key component is built', component is not None)
    # The bug: it renamed from its own current name, so the second one in a scene came out as
    # SingleSDKComponent1_<side>_<region>.
    suite.check('named from its class, its side and its region',
                str(component.pynode) == 'SingleSDKComponent_center_jaw', str(component.pynode))
    suite.check('and carrying its side and region as markup',
                component.side == 'center' and component.region == 'jaw',
                '{0!r}, {1!r}'.format(component.side, component.region))

    # The bug: it recorded drive_attr.nodeName(), the node, so nothing said which attribute drives.
    suite.check('it records the driving attribute, not just the node it is on',
                component.driver == 'f_jaw.openClose', str(component.driver))
    suite.check('and the object being driven', component.driven == driven, str(component.driven))

    # The bug: the values went in as strings through a hand-built compound.
    start = component.get_driven_values(s_sdk_component.START)
    end = component.get_driven_values(s_sdk_component.END)
    suite.check('the values each end sets come back as numbers',
                start == {'translateY': 0.0, 'rotateX': 0.0}, str(start))
    suite.check('for both ends', end == {'translateY': 5.0, 'rotateX': -30.0}, str(end))
    suite.check('an end the component records nothing for answers an empty dictionary',
                component.get_driven_values('middle') == {})

    # The bug: it took the first of all the driven attribute's connections, which on a rig is
    # usually a constraint or a blend node.
    suite.check('the curves it records are animation curves',
                component.anim_curves
                and all(isinstance(curve, pm.nt.AnimCurve) for curve in component.anim_curves),
                str(component.anim_curves))
    suite.check('one per driven attribute', len(component.anim_curves) == 2,
                str(component.anim_curves))

    suite.check('the driver is put back where it was, so building does not leave the rig posed',
                driver.attr('openClose').get() == 0, str(driver.attr('openClose').get()))

    # -- the relationship actually driving -------------------------------------------------- #
    driver.attr('openClose').set(10)
    suite.check('with the driver at one end the driven attributes are at that end\'s values',
                abs(driven.translateY.get() - 5.0) < 0.001
                and abs(driven.rotateX.get() + 30.0) < 0.001,
                '{0}, {1}'.format(driven.translateY.get(), driven.rotateX.get()))
    driver.attr('openClose').set(0)
    suite.check('and at the other end, at the other end\'s',
                abs(driven.translateY.get()) < 0.001 and abs(driven.rotateX.get()) < 0.001,
                '{0}, {1}'.format(driven.translateY.get(), driven.rotateX.get()))
    driver.attr('openClose').set(5)
    suite.check('halfway between, halfway between',
                0.0 < driven.translateY.get() < 5.0, str(driven.translateY.get()))
    driver.attr('openClose').set(0)

    suite.check('read back out of a scene it comes back as its own class',
                type(frag_base.FRAGNode(component.pynode))
                is s_sdk_component.SingleSDKComponent,
                str(type(frag_base.FRAGNode(component.pynode))))

    # -- what it refuses ------------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain(pm, ['b_root', 'b_jaw'])
    root_node, rig = _rig(pm, modules, joints[0])
    driver = pm.spaceLocator(name='f_jaw')
    driver.addAttr('openClose', at='double', min=0, max=10, dv=0, keyable=True)
    driven = pm.spaceLocator(name='the_tongue')

    # The bug: the default was (0, 0) - both ends at the same driver value, so the second key lands
    # on the first and the curve is flat.
    suite.check('the same driver value at both ends is refused rather than quietly building a flat '
                'curve',
                s_sdk_component.SingleSDKComponent.create(
                    rig, driver.attr('openClose'), driven, 'center', 'jaw',
                    driven_attrs={'start': {'translateY': 0.0}, 'end': {'translateY': 5.0}},
                    drive_attr_values=(0, 0)) is None)
    # The bug: driven_attrs defaulted to None and was then indexed.
    suite.check('and so is nothing to drive, rather than a TypeError from indexing None',
                s_sdk_component.SingleSDKComponent.create(
                    rig, driver.attr('openClose'), driven, 'center', 'jaw',
                    driven_attrs=None, drive_attr_values=(0, 10)) is None)
    suite.check('leaving no component node behind either way',
                not pm.ls('SingleSDKComponent_center_jaw'),
                str(pm.ls('SingleSDKComponent_center_jaw')))
    suite.check('and the driver still where it was',
                driver.attr('openClose').get() == 0, str(driver.attr('openClose').get()))


def _parameters_of(function):
    """
    The names a function takes, through whatever decorators are wrapped round it.

    :param function: The function to ask.
    :return: Its parameter names.
    :rtype: set(str)
    """

    import inspect

    return set(inspect.signature(function).parameters)


def check_the_registry(suite, pm, modules):
    frag_base = modules['frag_base']

    for name in ('TwistFixUpComponent', 'CameraComponent', 'SingleSDKComponent'):
        suite.check('{0} is in the registry, so a rig carrying one can be read back'.format(name),
                    name in frag_base.FRAGNodeRegister.__frag_node_types__,
                    str(sorted(frag_base.FRAGNodeRegister.__frag_node_types__)))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import camera_component
    from mca.mya.rigging.frag import fk_component
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import s_sdk_component
    from mca.mya.rigging.frag import twist_fixup_component

    modules = {'camera_component': camera_component, 'fk_component': fk_component,
               'frag_base': frag_base, 'frag_rig': frag_rig, 'frag_root': frag_root,
               's_sdk_component': s_sdk_component,
               'twist_fixup_component': twist_fixup_component}

    check_twist(suite, pm, modules)
    check_camera(suite, pm, modules)
    check_sdk(suite, pm, modules)
    check_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_small_components', body))
