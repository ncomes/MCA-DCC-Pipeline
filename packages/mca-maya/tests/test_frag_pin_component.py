"""
The component that rides a mesh, in a real Maya.

    mayapy tests/test_frag_pin_component.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=2, side='left', region='cheek', namespace_name=None):
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
        joints.append(pm.PyNode(cmds.joint(name=name, position=(index * 2, 1, 0), absolute=True)))
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


def _scene(pm, modules, with_mesh=True):
    """A fresh scene with a skeleton, a rig and a mesh to pin to."""

    harness.new_scene()
    joints = _skeleton(pm)
    root_node = modules['frag_root'].FRAGRoot.create(joints[0], 'player', 'pin_asset')
    rig = modules['frag_rig'].FRAGRig.create(root_node)
    mesh = None
    if with_mesh:
        mesh = pm.polyPlane(name='the_face', width=10, height=10, subdivisionsX=4,
                            subdivisionsY=4, axis=(0, 0, 1))[0]
    return joints, rig, mesh


def check_creating(suite, pm, modules):
    pin_component = modules['pin_component']

    joints, rig, mesh = _scene(pm, modules)
    component = pin_component.PinComponent.create(rig, joints[1], mesh, 'left', 'cheek')

    suite.check('a pin component is built', component is not None)
    suite.check('with one control', len(component.get_flags()) == 1, str(component.get_flags()))
    suite.check('over the joint it was given',
                component.bind_joints == [joints[1]], str(component.bind_joints))
    suite.check('and a uvPin reading the mesh',
                isinstance(component.pin_node, pm.nt.UvPin), str(type(component.pin_node)))

    # The order of the stack is the thing worth pinning down.
    offset_grp = component.pin_node.outputMatrix[0].listConnections()[0]
    suite.check('the pin drives a group, not the control',
                offset_grp != component.pin_flag.node, str(offset_grp))
    suite.check('that group hangs under the component\'s own control group',
                offset_grp.getParent() == component.flag_group, str(offset_grp.getParent()))
    suite.check('and the control\'s align transform is inside it, so the mesh carries the control',
                component.pin_flag.get_align_transform().getParent() == offset_grp,
                str(component.pin_flag.get_align_transform().getParent()))
    suite.check('the control drives a duplicate of the bind joint',
                component.pynode.attr(pin_component.PIN_JOINT_ATTR).get().getParent()
                == component.no_touch_grp)
    suite.check('and the duplicate drives the bind joint',
                bool(joints[1].listConnections(type=pm.nt.ParentConstraint)))
    suite.check('the control\'s own channels are free of the pin, which is what the group is for',
                not component.pin_flag.node.offsetParentMatrix.listConnections())

    suite.check('a pinned control does not travel by default',
                all(component.pin_flag.node.attr(axis).isLocked()
                    for axis in pin_component.DEFAULT_LOCKED_ATTRS))
    suite.check('and its visibility is not the animator\'s',
                component.pin_flag.node.visibility.isLocked())

    # Where on the mesh.
    suite.check('with no UV given it is pinned at the closest point on the mesh to the joint',
                0.0 <= component.uv[0] <= 1.0 and 0.0 <= component.uv[1] <= 1.0,
                str(component.uv))

    joints, rig, mesh = _scene(pm, modules)
    placed = pin_component.PinComponent.create(rig, joints[1], mesh, 'left', 'cheek',
                                               uv=[0.25, 0.75])
    suite.check('an explicit UV is used as given', placed.uv == [0.25, 0.75], str(placed.uv))

    build_kwargs = placed.get_build_kwargs()
    parameters = _parameters_of(pin_component.PinComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    # The version before recorded side, region and the mesh node among the build arguments - the
    # first two are already the node's markup, and the third ties a rebuild to that mesh's name.
    suite.check('and the side and region are not among them, because they are the node\'s markup',
                'side' not in build_kwargs and 'region' not in build_kwargs,
                str(sorted(build_kwargs)))
    suite.check('the UV is, which is the thing a rebuild cannot work out for itself',
                list(build_kwargs.get('uv') or []) == [0.25, 0.75], str(build_kwargs.get('uv')))

    suite.check('the pin travels with the mesh, which is the whole point',
                _moves_with_mesh(pm, placed, mesh))


def _moves_with_mesh(pm, component, mesh):
    """Move the mesh and see whether the control went with it."""

    flag_node = component.pin_flag.node
    before = pm.xform(flag_node, query=True, worldSpace=True, translation=True)
    mesh.translate.set(0, 0, 25)
    after = pm.xform(flag_node, query=True, worldSpace=True, translation=True)
    mesh.translate.set(0, 0, 0)
    return abs(after[2] - before[2]) > 20


def check_what_it_refuses(suite, pm, modules):
    pin_component = modules['pin_component']

    # The mesh is the one thing this component cannot do without, and create_uv_pin answers None
    # for anything that is not one.
    joints, rig, mesh = _scene(pm, modules, with_mesh=False)
    not_a_mesh = pm.group(empty=True, name='not_a_mesh')
    nodes_before = len(pm.ls())
    component = pin_component.PinComponent.create(rig, joints[1], not_a_mesh, 'left', 'cheek')
    suite.check('a transform with no mesh under it answers nothing rather than raising',
                component is None)
    left_behind = [str(node) for node in pm.ls(type=pm.nt.Network)
                   if 'PinComponent' in str(node)]
    suite.check('and the half-built component is taken out of the scene again',
                not left_behind, str(left_behind))
    suite.check('along with its groups',
                not pm.ls('NO_TOUCH_left_cheek') and not pm.ls('flags_left_cheek'),
                str(pm.ls('NO_TOUCH_left_cheek') + pm.ls('flags_left_cheek')))


def check_the_shared_control_methods(suite, pm, modules):
    pin_component = modules['pin_component']
    keyable_component = modules['keyable_component']

    joints, rig, mesh = _scene(pm, modules)
    component = pin_component.PinComponent.create(rig, joints[1], mesh, 'left', 'cheek')

    # The three methods every component used to carry its own character-for-character copy of.
    for method_name in ('select_flags', 'key_flags', 'to_default_pose'):
        suite.check('{0} is on KeyableComponent, not on each component'.format(method_name),
                    method_name in vars(keyable_component.KeyableComponent),
                    str(sorted(vars(keyable_component.KeyableComponent))))
        suite.check('and {0} is not written out again on PinComponent'.format(method_name),
                    method_name not in vars(pin_component.PinComponent))

    component.select_flags()
    suite.check('selecting the component\'s controls selects the one it has',
                pm.selected() == [component.pin_flag.node], str(pm.selected()))

    flag_node = component.pin_flag.node
    flag_node.rotateX.set(30)
    component.key_flags()
    suite.check('keying them puts a key on it', bool(pm.keyframe(flag_node, query=True)))
    component.to_default_pose()
    suite.check('and putting it back to its default pose zeroes it',
                abs(flag_node.rotateX.get()) < 0.001, str(flag_node.rotateX.get()))

    # The bug every copy of these methods had: pm.setKeyframe([]) raises, and pm.select([]) clears
    # the user's selection, which is not what asking to select a component's controls means.
    empty = modules['frag_base'].FRAGNode.create(rig, 'KeyableComponent', 1)
    bare = keyable_component.KeyableComponent(empty.pynode)
    suite.check('a bare keyable component has no controls', bare.get_flags() == [])
    pm.select(flag_node)
    suite.check('selecting its controls leaves the selection alone rather than clearing it',
                bare.select_flags() == [] and pm.selected() == [flag_node], str(pm.selected()))
    suite.check('keying them keys nothing rather than raising', bare.key_flags() == [])
    bare.to_default_pose()
    suite.check('and putting them back to their default pose does nothing', True)


def check_being_driven(suite, pm, modules):
    pin_component = modules['pin_component']

    joints, rig, mesh = _scene(pm, modules)
    component = pin_component.PinComponent.create(rig, joints[1], mesh, 'left', 'cheek')

    mocap = _skeleton(pm, namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('the control is driven by the matching joint on the other skeleton',
                len(constraints) == 1, str(constraints))

    elsewhere = _skeleton(pm, side='right', region='tail', namespace_name='other')
    suite.check('a skeleton with nothing matching drives nothing, without raising',
                component.attach_to_skeleton(elsewhere[0]) == [])


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
    pin_component = modules['pin_component']
    frag_base = modules['frag_base']

    harness.new_scene()
    if not cmds.namespace(exists='hero'):
        cmds.namespace(add='hero')
    cmds.namespace(set=':hero')
    joints = _skeleton(pm)
    root_node = modules['frag_root'].FRAGRoot.create(joints[0], 'player', 'pin_asset')
    rig = modules['frag_rig'].FRAGRig.create(root_node)
    mesh = pm.polyPlane(name='the_face', width=10, height=10, axis=(0, 0, 1))[0]

    cmds.namespace(set=':hero')
    component = pin_component.PinComponent.create(rig, joints[1], mesh, 'left', 'cheek')
    suite.check('a pin component builds while the active namespace is already the rig\'s',
                component is not None)
    suite.check('and it lands in that namespace',
                component.pynode.namespace() == 'hero:', str(component.pynode.namespace()))
    suite.check('with the active namespace put back afterwards',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
    cmds.namespace(set=':')

    suite.check('read back out of a scene it comes back as its own class',
                type(frag_base.FRAGNode(component.pynode)) is pin_component.PinComponent,
                str(type(frag_base.FRAGNode(component.pynode))))
    suite.check('PinComponent is in the registry, so a rig carrying one can be read back',
                'PinComponent' in frag_base.FRAGNodeRegister.__frag_node_types__)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import keyable_component
    from mca.mya.rigging.frag import pin_component

    modules = {'frag_base': frag_base, 'frag_rig': frag_rig, 'frag_root': frag_root,
               'keyable_component': keyable_component, 'pin_component': pin_component}

    check_creating(suite, pm, modules)
    check_what_it_refuses(suite, pm, modules)
    check_the_shared_control_methods(suite, pm, modules)
    check_being_driven(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_pin_component', body))
