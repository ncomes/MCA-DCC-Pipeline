"""
The spline IK component - a tail that bends on a curve and can pull back in - in a real Maya.

    mayapy tests/test_frag_spline_ik.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=5, side='center', region='tail', namespace_name=None):
    """
    A straight chain up Y with a root above it, one leaf joint per chain joint, and the three helper
    joints a spline IK wants - each marked up so it can be found again on another skeleton.

    :param int count: How many joints in the chain.
    :param str side: The side to mark everything up as.
    :param str region: The region to mark the chain up as.
    :param str namespace_name: A namespace to build it in.
    :return: The root, the chain, the leaves and the three helpers.
    :rtype: dict
    """

    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    if namespace_name:
        if not cmds.namespace(exists=namespace_name):
            cmds.namespace(add=namespace_name)
        cmds.namespace(set=':{0}'.format(namespace_name))

    cmds.select(clear=True)
    root = pm.PyNode(cmds.joint(name='root', position=(0, 0, 0), absolute=True))
    chain = [pm.PyNode(cmds.joint(name='b_{0}_{1:02d}'.format(region, index + 1),
                                  position=(0, (index + 1) * 4, 0), absolute=True))
             for index in range(count)]

    leaves = []
    for index, chain_joint in enumerate(chain):
        cmds.select(clear=True)
        leaf = pm.PyNode(cmds.joint(name='b_{0}_leaf_{1:02d}'.format(region, index + 1),
                                    position=(1, (index + 1) * 4, 0), absolute=True))
        pm.parent(leaf, chain_joint)
        leaves.append(leaf)

    helpers = {}
    for key, position in (('start', (0, 4, 0)),
                          ('mid', (0, count * 2, 0)),
                          ('end', (0, count * 4, 0))):
        cmds.select(clear=True)
        helpers[key] = pm.PyNode(cmds.joint(name='b_{0}_{1}_helper'.format(region, key),
                                            position=position, absolute=True))
        pm.parent(helpers[key], root)
    cmds.namespace(set=':')

    for index, joint_node in enumerate(chain):
        markup = chain_markup.JointMarkup(joint_node)
        markup.side = side
        markup.region = region
        if not index:
            markup.chainStart = region
        if index == len(chain) - 1:
            markup.chainEnd = region

    for index, leaf in enumerate(leaves):
        leaf_markup = chain_markup.JointMarkup(leaf)
        leaf_markup.side = side
        leaf_markup.region = '{0}_leaf'.format(region)

    # Each helper is its own region, so attach_to_skeleton can look it up on another skeleton.
    for key, joint_node in helpers.items():
        helper_markup = chain_markup.JointMarkup(joint_node)
        helper_markup.side = side
        helper_markup.region = '{0}_{1}_helper'.format(region, key)
        helper_markup.chainStart = '{0}_{1}_helper'.format(region, key)

    return {'root': root, 'chain': chain, 'leaves': leaves, 'helpers': helpers}


def _rig(pm, modules, root_joint, asset_id='spline_asset'):
    """A rig root and a rig over a skeleton."""

    root_node = modules['frag_root'].FRAGRoot.create(root_joint, 'player', asset_id)
    return root_node, modules['frag_rig'].FRAGRig.create(root_node)


def _scene(pm, modules, **kwargs):
    """A fresh scene with a marked-up skeleton and a rig over it."""

    harness.new_scene()
    skeleton = _skeleton(pm, **kwargs)
    root_node, rig = _rig(pm, modules, skeleton['root'])
    return skeleton, rig


def _build(modules, rig, skeleton, **kwargs):
    """The component over that skeleton, with the helpers in the right arguments."""

    return modules['spline_ik_component'].SplineIKComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], skeleton['leaves'],
        skeleton['helpers']['end'], skeleton['helpers']['mid'], 'center', 'tail', **kwargs)


def check_creating(suite, pm, modules):
    spline_ik_component = modules['spline_ik_component']

    skeleton, rig = _scene(pm, modules, count=5)
    component = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'])

    suite.check('a spline IK component is built', component is not None)
    suite.check('with four controls: a start, an end, the auxiliary one and a mid',
                len(component.get_flags()) == 4, str(component.get_flags()))

    # The bug: which controls a component has was worked out from how many it had.
    suite.check('each control is recorded under its own name, so nothing has to count them',
                component.start_flag is not None and component.end_flag is not None
                and component.aux_flag is not None and component.mid_flag is not None,
                str([component.start_flag, component.end_flag, component.aux_flag,
                     component.mid_flag]))
    suite.check('and the end control is the one carrying the retract',
                component.end_flag.node.hasAttr(spline_ik_component.RETRACT_ATTR))
    suite.check('every control says which component it belongs to, the end one included',
                component.pynode in component.end_flag.node.attr(
                    modules['frag_base'].FRAG_PARENT_ATTR).listConnections(),
                str(component.end_flag.node.attr(
                    modules['frag_base'].FRAG_PARENT_ATTR).listConnections()))

    suite.check('the chain and the three helper joints are what it drives',
                component.bind_joints == skeleton['chain'] + [skeleton['helpers']['start'],
                                                              skeleton['helpers']['end'],
                                                              skeleton['helpers']['mid']],
                str(component.bind_joints))
    suite.check('the leaf joints are recorded, one per chain joint',
                component.leaf_joints == skeleton['leaves'], str(component.leaf_joints))
    suite.check('and so are the two helper joints the controls drive',
                component.end_helper_joint == skeleton['helpers']['end']
                and component.helper_joint == skeleton['helpers']['mid']
                and component.start_helper_joint == skeleton['helpers']['start'])

    # The two groups, parented once each.
    main_grp = component.pynode.attr(spline_ik_component.MAIN_FLAGS_GROUP_ATTR).get()
    mid_grp = component.pynode.attr(spline_ik_component.MID_FLAG_GROUP_ATTR).get()
    suite.check('both of the component\'s own control groups are inside its control group',
                main_grp.getParent() == component.flag_group
                and mid_grp.getParent() == component.flag_group,
                '{0}, {1}'.format(main_grp.getParent(), mid_grp.getParent()))
    suite.check('the mid control is in the mid group, because it moves with the chain',
                component.mid_flag.get_align_transform().getParent() == mid_grp,
                str(component.mid_flag.get_align_transform().getParent()))
    suite.check('and the start and end controls are in the main one',
                component.start_flag.get_align_transform().getParent() == main_grp
                and component.end_flag.get_align_transform().getParent() == main_grp)

    suite.check('a solver and the curve\'s skin cluster are recorded',
                component.pynode.attr(spline_ik_component.IK_SOLVER_ATTR).get() is not None
                and component.pynode.attr(
                    spline_ik_component.SPLINE_SKIN_CLUSTER_ATTR).get() is not None)
    suite.check('the component knows it can retract', component.can_retract is True)

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(spline_ik_component.SplineIKComponent.create)
    markup_keys = {key for key in build_kwargs if key.endswith(('_region', '_side'))}
    suite.check('every build argument a rebuild needs is a parameter of create, bar the ones that '
                'say where to look the helper joints up again',
                set(build_kwargs) - markup_keys <= parameters,
                str(sorted(set(build_kwargs) - markup_keys - parameters)))
    suite.check('and the helper joints are recorded as markup, not as nodes',
                build_kwargs.get('mid_helper_region') == 'tail_mid_helper',
                str(build_kwargs.get('mid_helper_region')))

    # -- it actually bends ------------------------------------------------------------------ #
    before = pm.xform(skeleton['chain'][2], query=True, worldSpace=True, translation=True)
    component.mid_flag.node.translateX.set(8)
    after = pm.xform(skeleton['chain'][2], query=True, worldSpace=True, translation=True)
    suite.check('moving the mid control bends the middle of the chain',
                abs(after[0] - before[0]) > 1, '{0} -> {1}'.format(before, after))
    component.mid_flag.node.translateX.set(0)

    suite.check('the mid control\'s position is stored on the mid helper joint, which is how an '
                'animator\'s work survives a bake',
                bool(skeleton['helpers']['mid'].listConnections(type=pm.nt.ParentConstraint)))

    # -- the retract ------------------------------------------------------------------------- #
    retract = component.end_flag.node.attr(spline_ik_component.RETRACT_ATTR)
    suite.check('the retract on the control drives the one on the mid helper joint',
                skeleton['helpers']['mid'].attr(spline_ik_component.RETRACT_ATTR)
                in retract.listConnections(plugs=True, source=False, destination=True),
                str(retract.listConnections(plugs=True)))

    tip_before = pm.xform(skeleton['chain'][-1], query=True, worldSpace=True, translation=True)
    retract.set(10)
    tip_after = pm.xform(skeleton['chain'][-1], query=True, worldSpace=True, translation=True)
    suite.check('pulling the retract all the way walks the end of the chain back down its curve',
                tip_after[1] < tip_before[1] - 1, '{0} -> {1}'.format(tip_before, tip_after))
    suite.check('and shrinks the leaf joints as it goes',
                skeleton['leaves'][-1].scaleY.get() < 1.0,
                str(skeleton['leaves'][-1].scaleY.get()))
    suite.check('never to zero, because the engine will not take a scale of zero',
                skeleton['leaves'][-1].scaleY.get()
                >= spline_ik_component.RETRACT_SCALE_FLOOR,
                str(skeleton['leaves'][-1].scaleY.get()))
    retract.set(0)

    suite.check('the length along the chain goes onto every leaf joint but the last, where it '
                'makes the end stretch oddly',
                bool(skeleton['leaves'][0].scaleX.listConnections(source=True, destination=False))
                and not skeleton['leaves'][-1].scaleX.listConnections(source=True,
                                                                     destination=False))


def check_what_it_refuses(suite, pm, modules):
    spline_ik_component = modules['spline_ik_component']

    # The bug: zip(driver_joints, chain_between, leaf_joint_list) truncated to the shortest, so a
    # short leaf list left the far end of the chain unscaled with nothing said.
    skeleton, rig = _scene(pm, modules, count=5)
    message = suite.raises(
        'a leaf list that is not one joint per chain joint is refused',
        spline_ik_component.SplineIKComponent.create, rig, skeleton['chain'][0],
        skeleton['chain'][-1], skeleton['leaves'][:3], skeleton['helpers']['end'],
        skeleton['helpers']['mid'], 'center', 'tail')
    suite.check('and the refusal gives both counts', '5' in message and '3' in message, message)
    suite.check('with nothing left behind in the scene',
                not pm.ls('SplineIKComponent_center_tail'),
                str(pm.ls('SplineIKComponent_center_tail')))

    # A chain too short for a spline IK: spline_ctrl answers {} and the component takes itself out.
    skeleton, rig = _scene(pm, modules, count=1)
    refused = _build(modules, rig, skeleton)
    suite.check('a chain too short for a spline IK answers nothing rather than raising',
                refused is None)
    suite.check('and takes its own node and groups back out of the scene',
                not pm.ls('SplineIKComponent_center_tail')
                and not pm.ls('NO_TOUCH_center_tail'),
                str(pm.ls('SplineIKComponent_center_tail') + pm.ls('NO_TOUCH_center_tail')))


def check_the_optional_pieces(suite, pm, modules):
    skeleton, rig = _scene(pm, modules, count=5)
    no_start = _build(modules, rig, skeleton)

    suite.check('without a start helper joint there is no control at the base',
                no_start.start_flag is None, str(no_start.start_flag))
    suite.check('and three controls instead of four', len(no_start.get_flags()) == 3,
                str(no_start.get_flags()))
    suite.check('the component says it has no start helper joint either',
                no_start.start_helper_joint is None)
    main_grp = no_start.pynode.attr(
        modules['spline_ik_component'].MAIN_FLAGS_GROUP_ATTR).get()
    made_helpers = [node for node in pm.ls(type=pm.nt.Joint)
                    if node.listConnections(type=pm.nt.ParentConstraint)
                    and main_grp in [target for constraint_node
                                     in node.listConnections(type=pm.nt.ParentConstraint)
                                     for target in constraint_node.getTargetList()]]
    suite.check('and the start helper joint it made for itself follows the main control group, '
                'which is what lets the base of the chain move with its parent',
                bool(made_helpers), str(made_helpers))

    skeleton, rig = _scene(pm, modules, count=5)
    no_mid = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'],
                    mid_flag=False)
    suite.check('without a mid control there are three controls', len(no_mid.get_flags()) == 3,
                str(no_mid.get_flags()))
    suite.check('and the mid control asks as nothing rather than being indexed out of a list',
                no_mid.mid_flag is None)

    skeleton, rig = _scene(pm, modules, count=5)
    no_retract = _build(modules, rig, skeleton, can_retract=False)
    suite.check('without a retract the component says so', no_retract.can_retract is False)
    suite.check('the end control has no retract attribute on it',
                not no_retract.end_flag.node.hasAttr(
                    modules['spline_ik_component'].RETRACT_ATTR))
    suite.check('and nothing is driving the leaf joints\' cross-section scale',
                not no_retract.leaf_joints[0].scaleY.listConnections(source=True,
                                                                    destination=False))


def check_attaching(suite, pm, modules):
    spline_ik_component = modules['spline_ik_component']
    frag_base = modules['frag_base']
    rig_component = modules['rig_component']

    skeleton, rig = _scene(pm, modules, count=5)
    component = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'])
    parent_component = frag_base.FRAGNode.create(rig, 'KeyableComponent', 1)
    first_parent = pm.spaceLocator(name='the_pelvis')
    second_parent = pm.spaceLocator(name='the_chest')

    suite.check('the groups an attachment constrains are this component\'s own main group and its '
                'no-touch group',
                [str(group) for group in component.get_attachment_groups()]
                == [str(component.pynode.attr(
                    spline_ik_component.MAIN_FLAGS_GROUP_ATTR).get()),
                    str(component.no_touch_grp)],
                str(component.get_attachment_groups()))

    component.attach_component(parent_component, first_parent)
    main_grp = component.pynode.attr(spline_ik_component.MAIN_FLAGS_GROUP_ATTR).get()
    suite.check('attaching the component constrains that group',
                bool(pm.listRelatives(main_grp, type=pm.nt.Constraint)))
    suite.check('and the mid control\'s group is pointed at the parent and the end control',
                bool(pm.listRelatives(
                    component.pynode.attr(spline_ik_component.MID_FLAG_GROUP_ATTR).get(),
                    type=pm.nt.Constraint)))

    recorded = component.pynode.attr(rig_component.POINT_PARENT_OBJECTS_ATTR).listConnections()
    suite.check('the object it is attached to is recorded once', len(recorded) == 1, str(recorded))

    # The bug the base class fixed and this component's copy did not: the object lists grew every
    # time a component was reattached, and those lists are what a rebuild reads.
    component.attach_component(parent_component, second_parent)
    recorded = component.pynode.attr(rig_component.POINT_PARENT_OBJECTS_ATTR).listConnections()
    suite.check('reattaching it replaces what is recorded rather than adding to it',
                recorded == [second_parent], str(recorded))


def check_being_driven(suite, pm, modules):
    skeleton, rig = _scene(pm, modules, count=5)
    component = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'])
    mocap = _skeleton(pm, count=5, namespace_name='mocap')
    # A baked skeleton carries the retract on its mid helper joint, which is the whole reason the
    # component writes it there in the first place.
    mocap['helpers']['mid'].addAttr(modules['spline_ik_component'].RETRACT_ATTR, dv=0, min=0,
                                    max=10, k=True)

    constraints = component.attach_to_skeleton(mocap['root'])
    # A spline IK component is not driven joint for joint: each control is driven by the helper
    # joint it drives, looked up by that joint's own markup.
    suite.check('the start, end and mid controls are each driven by their own helper joint on the '
                'other skeleton',
                len(constraints) == 3, str(constraints))
    retract_attr = modules['spline_ik_component'].RETRACT_ATTR
    suite.check('and the retract comes back off the other skeleton\'s mid helper joint, which is '
                'how an animator\'s value survives a bake',
                mocap['helpers']['mid'].attr(retract_attr)
                in component.end_flag.node.attr(retract_attr).listConnections(
                    plugs=True, source=True, destination=False),
                str(component.end_flag.node.attr(retract_attr).listConnections(plugs=True)))
    mocap['helpers']['mid'].attr(retract_attr).set(7)
    suite.check('so setting it on the skeleton sets it on the control',
                abs(component.end_flag.node.attr(retract_attr).get() - 7) < 0.001,
                str(component.end_flag.node.attr(retract_attr).get()))

    skeleton, rig = _scene(pm, modules, count=5)
    component = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'])
    elsewhere = _skeleton(pm, count=5, side='left', region='arm', namespace_name='other')
    suite.check('a skeleton with none of the helper joints on it drives nothing, without raising',
                component.attach_to_skeleton(elsewhere['root']) == [])


def check_the_migration(suite, pm, modules):
    spline_ik_component = modules['spline_ik_component']

    skeleton, rig = _scene(pm, modules, count=5)
    component = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'])

    suite.check('a component is built at its class\'s version',
                int(component.get_version())
                == int(spline_ik_component.SplineIKComponent.VERSION))

    legacy_names = spline_ik_component.SplineIKComponent.LEGACY_ATTR_NAMES
    connected = {}
    for legacy_name, attr_name in legacy_names.items():
        connected[legacy_name] = component.pynode.attr(attr_name).get()
        pm.renameAttr(component.pynode.attr(attr_name), legacy_name)
    component.set_version(1)

    suite.check('a version 1 component is recognised as out of date',
                int(component.get_version())
                < int(spline_ik_component.SplineIKComponent.VERSION))
    component.update()
    suite.check('updating it brings it to the current version',
                int(component.get_version())
                == int(spline_ik_component.SplineIKComponent.VERSION),
                str(component.get_version()))
    suite.check('the snake_case attributes are gone',
                not any(component.pynode.hasAttr(name) for name in legacy_names))
    suite.check('each is there under its camelCase name, still wired to what it was wired to',
                all(component.pynode.attr(legacy_names[legacy_name]).get() == node
                    for legacy_name, node in connected.items()), str(connected))
    suite.check('so the component can still find its end control and its mid helper joint',
                component.end_flag is not None and component.helper_joint is not None)


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
    skeleton = _skeleton(pm, count=5, namespace_name='hero')
    root_node, rig = _rig(pm, modules, skeleton['root'])
    cmds.namespace(set=':hero')
    component = _build(modules, rig, skeleton, start_helper_joint=skeleton['helpers']['start'])

    suite.check('a spline IK component builds while the active namespace is already the rig\'s',
                component is not None)
    suite.check('and it lands in that namespace',
                component.pynode.namespace() == 'hero:', str(component.pynode.namespace()))
    suite.check('with the active namespace put back afterwards',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
    cmds.namespace(set=':')

    suite.check('read back out of a scene it comes back as its own class',
                type(frag_base.FRAGNode(component.pynode))
                is modules['spline_ik_component'].SplineIKComponent,
                str(type(frag_base.FRAGNode(component.pynode))))
    suite.check('SplineIKComponent is in the registry',
                'SplineIKComponent' in frag_base.FRAGNodeRegister.__frag_node_types__)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging import chain_markup
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import rig_component
    from mca.mya.rigging.frag import spline_ik_component

    modules = {'chain_markup': chain_markup, 'frag_base': frag_base, 'frag_rig': frag_rig,
               'frag_root': frag_root, 'rig_component': rig_component,
               'spline_ik_component': spline_ik_component}

    check_creating(suite, pm, modules)
    check_what_it_refuses(suite, pm, modules)
    check_the_optional_pieces(suite, pm, modules)
    check_attaching(suite, pm, modules)
    check_being_driven(suite, pm, modules)
    check_the_migration(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_spline_ik', body))
