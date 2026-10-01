"""
The four one-control components - world, COG, pelvis and clavicle - in a real Maya.

    mayapy tests/test_frag_single_components.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=3, side='center', region='spine', namespace_name=None,
              hierarchy_start=False):
    """
    A marked-up chain of joints with a root above it.

    :param int count: How many joints below the root.
    :param str side: The side to mark the chain up as.
    :param str region: The region to mark it up as.
    :param str namespace_name: A namespace to build it in.
    :param bool hierarchy_start: Mark the first joint of the chain as the start of the animatable
        hierarchy, which is one of the places a COG looks for a joint to follow.
    :return: The root, then the chain.
    :rtype: list(pm.nt.Joint)
    """

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
        joints.append(pm.PyNode(cmds.joint(name=name, position=(0, index * 10, 0), absolute=True)))
    cmds.namespace(set=':')

    chain = joints[1:]
    for index, joint_node in enumerate(chain):
        markup = chain_markup.JointMarkup(joint_node)
        markup.side = side
        markup.region = region
        if not index:
            markup.chainStart = region
            if hierarchy_start:
                markup.hierarchyStart = True
        if index == len(chain) - 1:
            markup.chainEnd = region
    return joints


def _rig(pm, modules, joints, asset_id='single_asset'):
    """A rig root and a rig over a skeleton, which is what a component needs above it."""

    root_node = modules['frag_root'].FRAGRoot.create(joints[0], 'player', asset_id)
    return root_node, modules['frag_rig'].FRAGRig.create(root_node)


def _scene(pm, modules, **kwargs):
    """A fresh scene with a marked-up skeleton and a rig over it."""

    harness.new_scene()
    joints = _skeleton(pm, **kwargs)
    root_node, rig = _rig(pm, modules, joints)
    return joints, rig


# --------------------------------------------------------------------------------------- #
# the world component
# --------------------------------------------------------------------------------------- #
def check_world(suite, pm, modules):
    world_component = modules['world_component']

    joints, rig = _scene(pm, modules)
    component = world_component.WorldComponent.create(rig, joints[0], 'center', 'world', scale=2.0)

    suite.check('a world component is built', component is not None)
    flags = component.get_flags()
    suite.check('with three controls - world, offset and root', len(flags) == 3, str(flags))
    suite.check('the offset control is a detail control, so it hides with the rest of them',
                component.offset_flag.node.attr('isDetail').get() is True)
    suite.check('and the root control is a sub control',
                component.root_flag.node.attr('isSub').get() is True)
    offset_parent = component.offset_flag.get_align_transform().getParent()
    suite.check('they are stacked, world at the top',
                offset_parent == component.world_flag.node, str(offset_parent))
    suite.check('the stack hangs under the component\'s own control group',
                component.world_flag.get_align_transform().getParent() == component.flag_group,
                str(component.world_flag.get_align_transform().getParent()))

    suite.check('the skeleton\'s root joint is the one joint it drives',
                component.bind_joints == [joints[0]], str(component.bind_joints))
    driving = [node for node in joints[0].listConnections(type=pm.nt.ParentConstraint)]
    suite.check('and it is driven by a duplicate rather than by a control directly',
                bool(driving), str(driving))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(world_component.WorldComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    suite.check('including the control size', build_kwargs.get('scale') == 2.0,
                str(build_kwargs.get('scale')))

    # -- locking --------------------------------------------------------------------------- #
    joints, rig = _scene(pm, modules)
    locked = world_component.WorldComponent.create(rig, joints[0], 'center', 'world',
                                                   attrs_to_lock=['sx', 'sy', 'sz'])
    suite.check('the channels asked for are locked on all three controls',
                all(flag.node.attr(axis).isLocked()
                    for flag in locked.get_flags() for axis in ('sx', 'sy', 'sz')))

    # -- a control that has come off ------------------------------------------------------- #
    locked.pynode.attr(world_component.OFFSET_FLAG_ATTR).disconnect()
    suite.check('a component that has lost a control leaves it out rather than raising from inside '
                'the wrapper',
                len(locked.get_flags()) == 2, str(locked.get_flags()))

    # -- being driven by a skeleton -------------------------------------------------------- #
    joints, rig = _scene(pm, modules)
    component = world_component.WorldComponent.create(rig, joints[0], 'center', 'spine')
    mocap = _skeleton(pm, namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('the root control is driven by the matching joint on the other skeleton',
                len(constraints) == 1, str(constraints))
    suite.check('and the constraint drives the root control, not the world one',
                constraints[0].getParent() == component.root_flag.node,
                str(constraints[0].getParent()))

    # The bug: it returned [constraint_node] with no guard, so this answered [None].
    elsewhere = _skeleton(pm, side='left', region='arm', namespace_name='other')
    suite.check('a skeleton with nothing matching answers an empty list rather than a list with '
                'None in it',
                component.attach_to_skeleton(elsewhere[0]) == [])


# --------------------------------------------------------------------------------------- #
# the COG
# --------------------------------------------------------------------------------------- #
def check_cog(suite, pm, modules):
    cog_component = modules['cog_component']

    joints, rig = _scene(pm, modules)
    component = cog_component.CogComponent.create(rig, joints[1], joints[-1], 'center', 'cog',
                                                  scale=1.5)

    suite.check('a COG component is built', component is not None)
    suite.check('with one control', len(component.get_flags()) == 1,
                str(component.get_flags()))
    suite.check('over one joint - the start, whatever end joint it was handed',
                component.bind_joints == [joints[1]], str(component.bind_joints))
    suite.check('the control hangs under the component\'s own control group',
                component.cog_flag.get_align_transform().getParent() == component.flag_group,
                str(component.cog_flag.get_align_transform().getParent()))
    suite.check('a COG cannot be scaled',
                all(component.cog_flag.node.attr(axis).isLocked()
                    for axis in cog_component.COG_FLAG_LOCKED_ATTRS))
    suite.check('the duplicate it drives is one joint, in the no-touch group',
                len(component.pynode.attr(cog_component.COG_CHAIN_ATTR).get()) == 1
                and component.pynode.attr(cog_component.COG_CHAIN_ATTR).get()[0].getParent()
                == component.no_touch_grp)

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(cog_component.CogComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    suite.check('including the control size', build_kwargs.get('scale') == 1.5,
                str(build_kwargs.get('scale')))

    # -- the three places it looks for a joint to follow ----------------------------------- #
    # The lookup reads the region and side off the joint the component drives, which here is marked
    # up as the spine - a COG is not a joint, which is what the two fallbacks below are for.
    mocap = _skeleton(pm, side='center', region='spine', namespace_name='mocap')
    suite.check('the matching chain is the first choice',
                component.driving_joint(mocap[0]) == mocap[1],
                str(component.driving_joint(mocap[0])))

    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('and the control is driven by it', len(constraints) == 1, str(constraints))
    cog_flag_node = component.cog_flag.node
    suite.check('the control\'s position is driven',
                bool(cog_flag_node.translateX.listConnections(destination=False)))
    suite.check('and its rotation is not - a COG\'s rotation stays the animator\'s',
                not cog_flag_node.rotateX.listConnections(destination=False),
                str(cog_flag_node.rotateX.listConnections(destination=False)))

    # The bug: the second choice was `joint_list = [hierarchy_start]` followed by `if not
    # joint_list:` - always true, so the third choice was dead and the second could be [None].
    hierarchy = _skeleton(pm, side='left', region='arm', namespace_name='hier',
                          hierarchy_start=True)
    suite.check('with no matching chain, the joint marked as the start of the hierarchy is next',
                component.driving_joint(hierarchy[0]) == hierarchy[1],
                str(component.driving_joint(hierarchy[0])))

    pelvis_skeleton = _skeleton(pm, side='center', region='pelvis', namespace_name='pelv')
    suite.check('and with neither, the pelvis - which the version before could never reach',
                component.driving_joint(pelvis_skeleton[0]) == pelvis_skeleton[1],
                str(component.driving_joint(pelvis_skeleton[0])))

    nothing = _skeleton(pm, side='right', region='tail', namespace_name='nope')
    suite.check('a skeleton offering none of the three answers nothing rather than None in a list',
                component.driving_joint(nothing[0]) is None,
                str(component.driving_joint(nothing[0])))
    suite.check('and attaching to it builds no constraints',
                component.attach_to_skeleton(nothing[0]) == [])


# --------------------------------------------------------------------------------------- #
# the pelvis
# --------------------------------------------------------------------------------------- #
def check_pelvis(suite, pm, modules):
    pelvis_component = modules['pelvis_component']

    joints, rig = _scene(pm, modules, count=3, region='pelvis')
    component = pelvis_component.PelvisComponent.create(rig, joints[1], joints[2], 'center',
                                                        'pelvis', scale=1.25)

    suite.check('a pelvis component is built', component is not None)
    suite.check('with one control', len(component.get_flags()) == 1, str(component.get_flags()))
    suite.check('and it is a sub control',
                component.pelvis_flag.node.attr('isSub').get() is True)
    suite.check('the control hangs under the component\'s own control group',
                component.pelvis_flag.get_align_transform().getParent() == component.flag_group,
                str(component.pelvis_flag.get_align_transform().getParent()))
    suite.check('it records the start and the end joint, not the run between them - the chain '
                'below the pelvis belongs to the legs',
                component.bind_joints == [joints[1], joints[2]], str(component.bind_joints))
    suite.check('a pelvis does not travel or scale by default',
                all(component.pelvis_flag.node.attr(axis).isLocked()
                    for axis in pelvis_component.DEFAULT_LOCKED_ATTRS))

    # Only the first joint is driven, which is what the for/break was doing.
    driven = [constraint_node.getParent() for constraint_node
              in pm.ls(type=pm.nt.ParentConstraint) if constraint_node.getParent() in joints]
    suite.check('exactly one bind joint is driven by the reversed chain', driven == [joints[1]],
                str(driven))
    suite.check('and the control turns it about the joint below it, which is the whole point of a '
                'reverse chain',
                component.pynode.attr(pelvis_component.PELVIS_CHAIN_ATTR).get()[0].getParent()
                == component.no_touch_grp)

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(pelvis_component.PelvisComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    suite.check('including the control size', build_kwargs.get('scale') == 1.25,
                str(build_kwargs.get('scale')))

    # -- being driven by a skeleton -------------------------------------------------------- #
    mocap = _skeleton(pm, count=3, region='pelvis', namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('the control is driven by the first matching joint', len(constraints) == 1,
                str(constraints))

    elsewhere = _skeleton(pm, side='left', region='arm', namespace_name='other')
    suite.check('a skeleton with nothing matching drives nothing, without raising',
                component.attach_to_skeleton(elsewhere[0]) == [])

    # The for/break was quietly covering a start and end joint that are not a chain. That case is
    # now a warning and a component that drives nothing, rather than a loop that happens not to run.
    joints, rig = _scene(pm, modules, count=3, region='pelvis')
    import maya.cmds as cmds
    cmds.select(clear=True)
    stray = pm.PyNode(cmds.joint(name='b_stray', position=(50, 0, 0), absolute=True))
    nodes_before = len(pm.ls())
    message = suite.raises('a start and end joint that are not a chain is refused',
                           pelvis_component.PelvisComponent.create, rig, joints[1], stray,
                           'center', 'pelvis')
    suite.check('and the refusal names both joints',
                str(joints[1]) in message and str(stray) in message, message)
    suite.check('with nothing left behind in the scene',
                len(pm.ls()) == nodes_before, '{0} -> {1}'.format(nodes_before, len(pm.ls())))


# --------------------------------------------------------------------------------------- #
# the clavicle
# --------------------------------------------------------------------------------------- #
def check_clavicle(suite, pm, modules):
    clavicle_component = modules['clavicle_component']
    fk_component = modules['fk_component']
    frag_base = modules['frag_base']

    joints, rig = _scene(pm, modules, side='left', region='clav')
    component = clavicle_component.ClavicleComponent.create(rig, joints[1], 'left', scale=1.75)

    suite.check('a clavicle component is built', component is not None)
    suite.check('it is an FK component underneath',
                isinstance(component, fk_component.FKComponent))
    suite.check('but it carries its own class name, which is all a FRAG node has to say what it is',
                component.pynode.attr(frag_base.FRAG_TYPE_ATTR).get() == 'ClavicleComponent',
                str(component.pynode.attr(frag_base.FRAG_TYPE_ATTR).get()))
    suite.check('and is named for it',
                str(component.pynode) == 'ClavicleComponent_left_clav', str(component.pynode))
    suite.check('with one control on one joint', len(component.get_flags()) == 1,
                str(component.get_flags()))
    suite.check('get_start_flag answers that control',
                component.get_start_flag() == component.get_flags()[0])

    found = frag_base.FRAGNode(component.pynode)
    suite.check('read back out of a scene it comes back as a clavicle, not an FK component',
                type(found) is clavicle_component.ClavicleComponent, str(type(found)))

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(clavicle_component.ClavicleComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))
    # The bug: retyping replaces FKComponent's whole buildKwargs block, and scale was not in the
    # replacement, so a rebuilt clavicle drew a default-sized control.
    suite.check('including the control size, which the version before dropped on retyping',
                build_kwargs.get('scale') == 1.75, str(build_kwargs.get('scale')))

    suite.check('the default locked channel is visibility, which is what the parameter named for '
                'translate axes has always been handed',
                clavicle_component.DEFAULT_LOCKED_ATTRS == ('v',))
    suite.check('so the control\'s translate channels are free, as on every rig built so far',
                not any(component.get_flags()[0].node.attr(axis).isLocked()
                        for axis in ('tx', 'ty', 'tz')))

    # -- being driven by a skeleton -------------------------------------------------------- #
    mocap = _skeleton(pm, side='left', region='clav', namespace_name='mocap')
    constraints = component.attach_to_skeleton(mocap[0])
    suite.check('the control is driven by the matching joint', len(constraints) == 1,
                str(constraints))
    clav_flag_node = component.get_flags()[0].node
    suite.check('its rotation is driven',
                bool(clav_flag_node.rotateX.listConnections(destination=False)))
    suite.check('and its position is not - a clavicle\'s position belongs to the spine above it',
                not clav_flag_node.translateX.listConnections(destination=False),
                str(clav_flag_node.translateX.listConnections(destination=False)))

    # The bug: the fallback for a bind joint with no markup was `self.pynode.region` - the pymel
    # Attribute rather than the string on it - which then went into a dictionary lookup and matched
    # nothing. So a clavicle whose own joints carry no markup drove nothing at all.
    joints, rig = _scene(pm, modules, side='left', region='clav')
    # No skelRegion on the joint, and Maya's own side label set to left - which is what an imported
    # skeleton looks like, and the case the fallback to the component's own markup exists for.
    for joint_node in joints[1:]:
        if joint_node.hasAttr('skelRegion'):
            joint_node.deleteAttr('skelRegion')
        if joint_node.hasAttr('skelSide'):
            joint_node.deleteAttr('skelSide')
        joint_node.attr('side').set(1)
    unmarked = clavicle_component.ClavicleComponent.create(rig, joints[1], 'left', region='clav')
    suite.check('the fallback is the component\'s own region as a string, not as a pymel attribute',
                isinstance(unmarked.region, str) and isinstance(unmarked.side, str),
                '{0!r}, {1!r}'.format(unmarked.region, unmarked.side))
    mocap = _skeleton(pm, side='left', region='clav', namespace_name='bare')
    suite.check('so a component whose own joints carry no region markup still finds its chain',
                unmarked.matching_chain(mocap[0]) == mocap[1:],
                str(unmarked.matching_chain(mocap[0])))
    suite.check('and is driven by it', len(unmarked.attach_to_skeleton(mocap[0])) == 1)
    suite.check('the side, with no skelSide markup, comes from Maya\'s own joint label - which '
                'wins over the component\'s own side',
                modules['chain_markup'].JointMarkup(joints[1]).side == 'left',
                str(modules['chain_markup'].JointMarkup(joints[1]).side))


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

    builders = (('world', modules['world_component'].WorldComponent,
                 lambda rig, joints: (rig, joints[0], 'center', 'world')),
                ('COG', modules['cog_component'].CogComponent,
                 lambda rig, joints: (rig, joints[1], joints[-1], 'center', 'cog')),
                ('pelvis', modules['pelvis_component'].PelvisComponent,
                 lambda rig, joints: (rig, joints[1], joints[2], 'center', 'pelvis')),
                ('clavicle', modules['clavicle_component'].ClavicleComponent,
                 lambda rig, joints: (rig, joints[1], 'center')))

    for name, builder, arguments in builders:
        harness.new_scene()
        if not cmds.namespace(exists='hero'):
            cmds.namespace(add='hero')
        cmds.namespace(set=':hero')
        joints = _skeleton(pm)
        root_node, rig = _rig(pm, modules, joints)

        cmds.namespace(set=':hero')
        component = builder.create(*arguments(rig, joints))
        suite.check('a {0} component builds while the active namespace is already the rig\'s, '
                    'rather than raising'.format(name), component is not None)
        suite.check('and it lands in that namespace',
                    component.pynode.namespace() == 'hero:', str(component.pynode.namespace()))
        suite.check('with the active namespace put back afterwards',
                    cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                    cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
        suite.check('{0} is in the registry, so a rig carrying one can be read back'.format(name),
                    builder.__name__ in frag_base.FRAGNodeRegister.__frag_node_types__,
                    str(sorted(frag_base.FRAGNodeRegister.__frag_node_types__)))
        suite.check('and it comes back as its own class',
                    type(frag_base.FRAGNode(component.pynode)) is builder,
                    str(type(frag_base.FRAGNode(component.pynode))))
    cmds.namespace(set=':')


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging import chain_markup
    from mca.mya.rigging.frag import clavicle_component
    from mca.mya.rigging.frag import cog_component
    from mca.mya.rigging.frag import fk_component
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import pelvis_component
    from mca.mya.rigging.frag import world_component

    modules = {'chain_markup': chain_markup,
               'clavicle_component': clavicle_component, 'cog_component': cog_component,
               'fk_component': fk_component, 'frag_base': frag_base, 'frag_rig': frag_rig,
               'frag_root': frag_root, 'pelvis_component': pelvis_component,
               'world_component': world_component}

    check_world(suite, pm, modules)
    check_cog(suite, pm, modules)
    check_pelvis(suite, pm, modules)
    check_clavicle(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_single_components', body))
