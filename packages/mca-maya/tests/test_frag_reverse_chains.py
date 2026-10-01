"""
The reverse FK chain components - a spine, and a spine that stretches - in a real Maya.

    mayapy tests/test_frag_reverse_chains.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=5, side='center', region='spine', namespace_name=None, leaves=False):
    """
    A marked-up chain up Y with a root above it, and optionally one leaf joint per chain joint.

    :param int count: How many joints in the chain below the root.
    :param str side: The side to mark the chain up as.
    :param str region: The region to mark it up as.
    :param str namespace_name: A namespace to build it in.
    :param bool leaves: Hang one marked-up leaf joint off each chain joint.
    :return: The root, the chain, and the leaves.
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
    chain = []
    for index in range(count):
        chain.append(pm.PyNode(cmds.joint(name='b_{0}_{1}_{2:02d}'.format(side, region, index + 1),
                                          position=(0, (index + 1) * 10, 0), absolute=True)))

    leaf_joints = []
    if leaves:
        for index, chain_joint in enumerate(chain):
            cmds.select(clear=True)
            leaf = pm.PyNode(cmds.joint(name='b_{0}_leaf_{1:02d}'.format(side, index + 1),
                                        position=(2, (index + 1) * 10, 0), absolute=True))
            pm.parent(leaf, chain_joint)
            leaf_markup = chain_markup.JointMarkup(leaf)
            leaf_markup.side = side
            leaf_markup.region = 'leaf'
            leaf_joints.append(leaf)
    cmds.namespace(set=':')

    for index, joint_node in enumerate(chain):
        markup = chain_markup.JointMarkup(joint_node)
        markup.side = side
        markup.region = region
        if not index:
            markup.chainStart = region
        if index == len(chain) - 1:
            markup.chainEnd = region
    return {'root': root, 'chain': chain, 'leaves': leaf_joints}


def _rig(pm, modules, root_joint, asset_id='reverse_asset'):
    """A rig root and a rig over a skeleton."""

    root_node = modules['frag_root'].FRAGRoot.create(root_joint, 'player', asset_id)
    return root_node, modules['frag_rig'].FRAGRig.create(root_node)


def _scene(pm, modules, **kwargs):
    """A fresh scene with a marked-up skeleton and a rig over it."""

    harness.new_scene()
    skeleton = _skeleton(pm, **kwargs)
    root_node, rig = _rig(pm, modules, skeleton['root'])
    return skeleton, rig


# --------------------------------------------------------------------------------------- #
# the plain reverse chain
# --------------------------------------------------------------------------------------- #
def check_rfk(suite, pm, modules):
    rfk_component = modules['rfk_component']

    skeleton, rig = _scene(pm, modules, count=5)
    component = rfk_component.RFKComponent.create(rig, skeleton['chain'][0],
                                                  skeleton['chain'][-1], 'center', 'spine',
                                                  scale=2.0)

    suite.check('a reverse FK component is built', component is not None)
    suite.check('with a control at each end and one per middle joint',
                len(component.primary_flags) == 5, str(component.primary_flags))
    suite.check('and a detail control at each end on top of those',
                len(component.sub_flags) == 2, str(component.sub_flags))
    suite.check('every control comes back from get_flags', len(component.get_flags()) == 7,
                str(component.get_flags()))
    suite.check('the joints it drives are on it',
                component.bind_joints == skeleton['chain'], str(component.bind_joints))
    suite.check('it drives a duplicate of them rather than them directly',
                len(component.rfk_chain) == 5
                and component.rfk_chain[0] not in skeleton['chain'],
                str(component.rfk_chain))
    suite.check('whose root is in the no-touch group',
                component.rfk_chain[0].getParent() == component.no_touch_grp,
                str(component.rfk_chain[0].getParent()))
    suite.check('and each bind joint follows it',
                all(bool(joint_node.listConnections(type=pm.nt.ParentConstraint))
                    for joint_node in skeleton['chain']))

    # The middle controls have to come back in chain order, not name order.
    suite.check('the middle controls come back in the order they sit along the chain',
                [str(flag_node.node) for flag_node in component.mid_flags]
                == [str(flag_node.node) for flag_node
                    in sorted(component.mid_flags, key=lambda flag: str(flag.node))],
                str([str(flag_node.node) for flag_node in component.mid_flags]))
    suite.check('the primary controls run bottom, middles, top',
                component.primary_flags[0] == component.start_flag
                and component.primary_flags[-1] == component.end_flag)

    suite.check('a chain control only turns - where the chain is comes from the chain',
                all(flag_node.node.attr(axis).isLocked()
                    for flag_node in component.get_flags()
                    for axis in rfk_component.LOCKED_FLAG_ATTRS))

    # The distribution: turning one end carries the middle.
    middle_before = component.rfk_chain[2].getRotation(space='world')
    component.end_flag.node.rotateY.set(60)
    middle_after = component.rfk_chain[2].getRotation(space='world')
    suite.check('turning the control at the top carries the middle of the chain with it',
                abs(middle_after[1] - middle_before[1]) > 1,
                '{0} -> {1}'.format(middle_before, middle_after))
    suite.check('by less than the end itself turned, which is what distributing means',
                abs(middle_after[1] - middle_before[1]) < 60,
                str(middle_after[1] - middle_before[1]))
    component.end_flag.node.rotateY.set(0)

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(rfk_component.RFKComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    suite.check('including the control size', build_kwargs.get('scale') == 2.0,
                str(build_kwargs.get('scale')))

    # -- built without detail controls ------------------------------------------------------ #
    skeleton, rig = _scene(pm, modules, count=4)
    plain = rfk_component.RFKComponent.create(rig, skeleton['chain'][0], skeleton['chain'][-1],
                                              'center', 'spine', create_sub_flags=False)
    # The bug: sub_flags answered None, and raw nodes rather than Flag objects.
    suite.check('a component built without detail controls answers an empty list, not None',
                plain.sub_flags == [], str(plain.sub_flags))
    suite.check('and its controls are the primary ones only', len(plain.get_flags()) == 4,
                str(plain.get_flags()))

    # The bug: get_flags wrapped every read in Flag with nothing asking whether it was still wired.
    plain.pynode.attr(rfk_component.TOP_FLAG_ATTR).disconnect()
    suite.check('a component that has lost a control leaves it out rather than raising from inside '
                'the wrapper',
                len(plain.get_flags()) == 3, str(plain.get_flags()))

    # -- the chain length guard ------------------------------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=2)
    # The bug: rfk_chain answers {} for a chain this short, and the next line was
    # chain_dict['mid_flags'] - with the component, its groups and a duplicated chain already built.
    message = suite.raises('a chain too short to distribute anything along is refused',
                           rfk_component.RFKComponent.create, rig, skeleton['chain'][0],
                           skeleton['chain'][-1], 'center', 'spine')
    suite.check('and the refusal names the joints and the count it got',
                str(skeleton['chain'][0]) in message and '2' in message, message)
    suite.check('with nothing left behind in the scene',
                not pm.ls('RFKComponent_center_spine') and not pm.ls('NO_TOUCH_center_spine'),
                str(pm.ls('RFKComponent_center_spine') + pm.ls('NO_TOUCH_center_spine')))

    # -- being driven by a skeleton --------------------------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=5)
    component = rfk_component.RFKComponent.create(rig, skeleton['chain'][0],
                                                  skeleton['chain'][-1], 'center', 'spine')
    mocap = _skeleton(pm, count=5, namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap['root'])
    suite.check('every control along the chain is driven by the matching joint',
                len(constraints) == 5, str(constraints))

    # The bug: this required len(flags) == len(joints) and attached nothing, silently, otherwise.
    elsewhere = _skeleton(pm, side='left', region='arm', namespace_name='other')
    suite.check('a component already driven by one skeleton is not driven by a second, because '
                'nothing can drive a channel twice',
                component.attach_to_skeleton(mocap['root']) == [])

    # The bug: this required len(flags) == len(joints) and attached nothing, silently, otherwise.
    # Its own scene, because a control that is already driven cannot be driven again.
    skeleton, rig = _scene(pm, modules, count=5)
    component = rfk_component.RFKComponent.create(rig, skeleton['chain'][0],
                                                  skeleton['chain'][-1], 'center', 'spine')
    longer = _skeleton(pm, count=6, namespace_name='longer')
    found = component.matching_chain(longer['root'])
    suite.check('a skeleton with one more joint than the rig has controls is found whole',
                len(found) == 6, str(found))
    longer_constraints = component.attach_to_skeleton(longer['root'])
    suite.check('and as many controls as there are get driven, rather than none',
                len(longer_constraints) == 5, str(longer_constraints))

    skeleton, rig = _scene(pm, modules, count=5)
    component = rfk_component.RFKComponent.create(rig, skeleton['chain'][0],
                                                  skeleton['chain'][-1], 'center', 'spine')
    elsewhere = _skeleton(pm, side='left', region='arm', namespace_name='other')
    suite.check('a skeleton with nothing matching drives nothing, without raising',
                component.attach_to_skeleton(elsewhere['root']) == [])


# --------------------------------------------------------------------------------------- #
# the stretchy one
# --------------------------------------------------------------------------------------- #
def check_rfk_stretch(suite, pm, modules):
    rfk_stretch_component = modules['rfk_stretch_component']
    rfk_component = modules['rfk_component']

    skeleton, rig = _scene(pm, modules, count=5, leaves=True)
    component = rfk_stretch_component.RFKStretchComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine',
        leaf_joint_list=skeleton['leaves'])

    suite.check('a stretchy reverse FK component is built', component is not None)
    suite.check('it is a reverse chain component', isinstance(component,
                                                              rfk_component.ReverseChainComponent))
    # The two stay separate classes: cinematics asks a rig for its children of_type=RFKComponent.
    suite.check('but it is not an RFKComponent, which a rig is asked for by type',
                not isinstance(component, rfk_component.RFKComponent))

    suite.check('with the same control layout as a plain reverse chain',
                len(component.primary_flags) == 5 and len(component.sub_flags) == 2,
                str(component.get_flags()))
    suite.check('a twin chain that rotates but never stretches',
                len(component.ref_chain) == 5, str(component.ref_chain))
    suite.check('parented into the no-touch group',
                component.ref_chain[0].getParent() == component.no_touch_grp,
                str(component.ref_chain[0].getParent()))
    suite.check('and the leaf joints it scales rather than the bind joints',
                component.leaf_joints == skeleton['leaves'], str(component.leaf_joints))
    suite.check('which is what scale_targets answers',
                component.scale_targets == skeleton['leaves'], str(component.scale_targets))

    stretch_axis = 'y'
    top_flag = component.end_flag.node
    suite.check('the top control keeps the one translate channel that runs along the chain',
                not top_flag.attr('t{0}'.format(stretch_axis)).isLocked(),
                str(stretch_axis))
    suite.check('and loses the other two',
                all(top_flag.attr('t{0}'.format(axis)).isLocked()
                    for axis in 'xyz' if axis != stretch_axis))
    suite.check('every control that drives a joint\'s scale keeps its scale channels',
                not any(flag_node.node.attr(axis).isLocked()
                        for flag_node in component.primary_flags
                        for axis in rfk_stretch_component.SCALE_ATTRS))
    suite.check('while the detail controls, which drive no joint, lose theirs',
                all(flag_node.node.attr(axis).isLocked() for flag_node in component.sub_flags
                    for axis in rfk_stretch_component.SCALE_ATTRS))

    # -- it actually stretches -------------------------------------------------------------- #
    before = pm.xform(component.rfk_chain[-1], query=True, worldSpace=True, translation=True)
    top_flag.attr('t{0}'.format(stretch_axis)).set(20)
    after = pm.xform(component.rfk_chain[-1], query=True, worldSpace=True, translation=True)
    suite.check('pulling on the top control lengthens the chain',
                after[1] - before[1] > 5, '{0} -> {1}'.format(before, after))
    leaf_scale = skeleton['leaves'][2].scaleX.get()
    suite.check('and the middle gets thinner, which is the volume being kept',
                leaf_scale < 1.0, str(leaf_scale))
    top_flag.attr('t{0}'.format(stretch_axis)).set(0)

    suite.check('an animator\'s own scale on a control multiplies into the joint it drives',
                _hand_scale_reaches_joint(pm, component, skeleton['leaves'][0]))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(rfk_stretch_component.RFKStretchComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create, bar the two that '
                'say where to look the leaf chain up again',
                set(build_kwargs) - {'leaf_region', 'leaf_side'} <= parameters,
                str(sorted(set(build_kwargs) - {'leaf_region', 'leaf_side'} - parameters)))
    suite.check('and the leaf chain is recorded as markup, not as nodes, so a rebuild can find it',
                build_kwargs.get('leaf_region') == 'leaf'
                and build_kwargs.get('leaf_side') == 'center',
                str([build_kwargs.get('leaf_region'), build_kwargs.get('leaf_side')]))

    # -- no leaf joints --------------------------------------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=5)
    no_leaves = rfk_stretch_component.RFKStretchComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine')
    suite.check('without leaf joints the scale goes on the bind joints',
                no_leaves.leaf_joints == [] and no_leaves.scale_targets == skeleton['chain'],
                str(no_leaves.scale_targets))

    # -- the short leaf list it recovers ----------------------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=5, leaves=True)
    recovered = rfk_stretch_component.RFKStretchComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine',
        leaf_joint_list=skeleton['leaves'][:2])
    suite.check('a short leaf list - which is what bad markup gives - is recovered from the chain '
                'joints\' children',
                recovered.leaf_joints == skeleton['leaves'], str(recovered.leaf_joints))

    # A list that cannot be completed is refused rather than used with holes in it.
    skeleton, rig = _scene(pm, modules, count=5, leaves=True)
    pm.delete(skeleton['leaves'][3])
    holey = rfk_stretch_component.RFKStretchComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine',
        leaf_joint_list=skeleton['leaves'][:2])
    suite.check('a leaf list that cannot be completed falls back to the bind joints rather than '
                'being used with None in it',
                holey.leaf_joints == [] and holey.scale_targets == skeleton['chain'],
                str(holey.scale_targets))

    # -- the version migration that was never written ---------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=5)
    component = rfk_stretch_component.RFKStretchComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine')
    suite.check('the component is built at its class\'s version',
                int(component.get_version())
                == int(rfk_stretch_component.RFKStretchComponent.VERSION))
    component.set_version(1)
    # The bug: VERSION is 2 and there was no _update_version_1_to_version_2 anywhere in the class
    # or its parents, so updating any stretchy spine raised AttributeError.
    component.update()
    suite.check('a version 1 component can be brought up to date, which it could not before',
                int(component.get_version()) == 2, str(component.get_version()))

    # -- removing it ------------------------------------------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=5, leaves=True)
    component = rfk_stretch_component.RFKStretchComponent.create(
        rig, skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine',
        leaf_joint_list=skeleton['leaves'])
    scale_node_names = [str(node) for node
                        in component.pynode.attr(
                            rfk_stretch_component.JOINT_SCALE_NODES_ATTR).listConnections()]
    component.remove()
    suite.check('removing the component deletes the scale nodes that live outside its groups',
                not any(pm.objExists(name) for name in scale_node_names), str(scale_node_names))
    suite.check('and puts the joints it was scaling back to one, rather than leaving them at zero '
                'with a deleted input',
                all(list(leaf.scale.get()) == [1.0, 1.0, 1.0] for leaf in skeleton['leaves']),
                str([list(leaf.scale.get()) for leaf in skeleton['leaves']]))

    # -- the chain length guard -------------------------------------------------------------- #
    skeleton, rig = _scene(pm, modules, count=2)
    message = suite.raises('a chain too short to stretch is refused',
                           rfk_stretch_component.RFKStretchComponent.create, rig,
                           skeleton['chain'][0], skeleton['chain'][-1], 'center', 'spine')
    suite.check('and the refusal names the joints and the count it got',
                str(skeleton['chain'][0]) in message and '2' in message, message)
    suite.check('with nothing left behind in the scene',
                not pm.ls('RFKStretchComponent_center_spine'),
                str(pm.ls('RFKStretchComponent_center_spine')))


def _hand_scale_reaches_joint(pm, component, target_joint):
    """Scale the bottom control by hand and see whether the joint it drives follows."""

    flag_node = component.start_flag.node
    before = target_joint.scaleX.get()
    flag_node.scaleX.set(2.0)
    after = target_joint.scaleX.get()
    flag_node.scaleX.set(1.0)
    return after > before * 1.5


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

    builders = (('reverse FK', modules['rfk_component'].RFKComponent),
                ('stretchy reverse FK', modules['rfk_stretch_component'].RFKStretchComponent))

    for name, builder in builders:
        harness.new_scene()
        skeleton = _skeleton(pm, count=5, namespace_name='hero')
        root_node, rig = _rig(pm, modules, skeleton['root'])
        cmds.namespace(set=':hero')
        component = builder.create(rig, skeleton['chain'][0], skeleton['chain'][-1], 'center',
                                   'spine')
        suite.check('a {0} component builds while the active namespace is already the rig\'s, '
                    'rather than raising'.format(name), component is not None)
        suite.check('and it lands in that namespace',
                    component.pynode.namespace() == 'hero:', str(component.pynode.namespace()))
        suite.check('with the active namespace put back afterwards',
                    cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                    cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
        suite.check('{0} comes back as its own class out of a scene'.format(name),
                    type(frag_base.FRAGNode(component.pynode)) is builder,
                    str(type(frag_base.FRAGNode(component.pynode))))
    cmds.namespace(set=':')

    for name in ('RFKComponent', 'RFKStretchComponent', 'ReverseChainComponent'):
        suite.check('{0} is in the registry'.format(name),
                    name in frag_base.FRAGNodeRegister.__frag_node_types__,
                    str(sorted(frag_base.FRAGNodeRegister.__frag_node_types__)))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import rfk_component
    from mca.mya.rigging.frag import rfk_stretch_component

    modules = {'frag_base': frag_base, 'frag_rig': frag_rig, 'frag_root': frag_root,
               'rfk_component': rfk_component, 'rfk_stretch_component': rfk_stretch_component}

    check_rfk(suite, pm, modules)
    check_rfk_stretch(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_reverse_chains', body))
