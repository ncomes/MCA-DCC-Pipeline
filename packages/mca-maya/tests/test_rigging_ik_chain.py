"""
The rotate-plane IK chain, the guide line it draws and the clusters that line is built from, in a
real Maya.

    mayapy tests/test_rigging_ik_chain.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _arm(pm, count=3):
    """A bent chain of joints along X, so its middle has a side to bend to."""

    import maya.cmds as cmds

    positions = [(0, 20, 0), (10, 20, -3), (20, 20, 0), (26, 20, 0), (32, 20, 0)]
    cmds.select(clear=True)
    return [pm.PyNode(cmds.joint(name='b_arm_{0:02d}'.format(index),
                                 position=positions[index], absolute=True))
            for index in range(count)]


def check_cluster(suite, pm):
    import maya.cmds as cmds
    from mca.mya.deformations import cluster

    harness.new_scene()
    sphere = pm.polySphere()[0]
    cluster_node, cluster_handle = cluster.create_cluster_from_component_names(
        sphere.vtx[0], 'plain_cluster')
    suite.check('a cluster is built over the points it is given',
                str(cluster_node) == 'plain_cluster', str(cluster_node))
    suite.check('with its handle beside it',
                str(cluster_handle) == 'plain_clusterHandle', str(cluster_handle))
    suite.check('at the front of the deformation chain by default',
                bool(sphere.getShape().listConnections(type=pm.nt.Cluster)))

    relative_node, _ = cluster.create_cluster_from_component_names(
        sphere.vtx[1], 'relative_cluster', relative=True)
    suite.check('relative mode reaches the node',
                relative_node.relative.get() is True)

    # -- with a namespace active --------------------------------------------------------------- #
    # The bug: the rename that moves the new nodes into the namespace was called with one argument,
    # where pm.rename wants the node and its new name, so it raised TypeError instead. Every cluster
    # built inside a namespace - which is how a referenced rig is rebuilt - went that way.
    pm.namespace(add='hero')
    pm.namespace(set='hero')
    namespaced_node, namespaced_handle = cluster.create_cluster_from_component_names(
        sphere.vtx[2], 'in_namespace')
    suite.check('a cluster built with a namespace active is built, rather than raising',
                namespaced_node is not None)
    # And the name it built was ':hero' + 'in_namespace', with no colon between them.
    suite.check('and it lands in that namespace, with the colon',
                str(namespaced_node) == 'hero:in_namespace', str(namespaced_node))
    suite.check('its handle with it',
                str(namespaced_handle) == 'hero:in_namespaceHandle', str(namespaced_handle))
    suite.check('and the namespace the caller was working in is still the one it was',
                pm.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                pm.namespaceInfo(currentNamespace=True, absoluteName=True))

    # Maya builds one anyway - a cluster node and a handle connected to no geometry at all.
    message = suite.raises('a cluster asked for over no points refuses, rather than coming back '
                           'deforming nothing',
                           cluster.create_cluster_from_component_names, [], 'empty_cluster')
    suite.check('and says which cluster it was asked for', 'empty_cluster' in message, message)
    suite.check('nothing was built', not cmds.ls('*empty_cluster*'),
                str(cmds.ls('*empty_cluster*')))
    suite.check('and the namespace is put back even then',
                pm.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                pm.namespaceInfo(currentNamespace=True, absoluteName=True))
    pm.namespace(set=':')


def check_reference_line(suite, pm):
    from mca.mya.rigging import reference_line

    harness.new_scene()
    start = pm.spaceLocator(name='line_start')
    end = pm.spaceLocator(name='line_end')
    start.translate.set(0, 0, 0)
    end.translate.set(10, 0, 0)

    line = reference_line.create_line_between(start, end, name='a_guide_line')
    suite.check('a line is drawn between two objects', line is not None)
    suite.check('named as asked', str(line) == 'a_guide_line', str(line))
    suite.check('and its shape with it',
                str(line.getShape()) == 'a_guide_lineShape', str(line.getShape()))
    cvs = line.getShape().getCVs(space='world')
    suite.check('with a point at each end',
                abs(cvs[0][0]) < 0.0001 and abs(cvs[1][0] - 10.0) < 0.0001, str(cvs))

    line_clusters = reference_line.get_line_clusters(line)
    suite.check('two clusters drive it', len(line_clusters) == 2, str(line_clusters))
    # A cluster shows up once per shape it deforms, so the walk has to go through a set.
    suite.check('and asking twice gives the same two',
                reference_line.get_line_clusters(line) == line_clusters)
    suite.check('named after the line',
                sorted(str(node) for node in line_clusters) ==
                ['a_guide_line_a', 'a_guide_line_b'],
                str(sorted(str(node) for node in line_clusters)))

    handles = [node for node in line.getChildren(type='transform')]
    suite.check('the cluster handles are parented under the line', len(handles) == 2, str(handles))
    suite.check('and hidden', not any(handle.visibility.get() for handle in handles))
    suite.check('nothing in the line inherits its parents\' transform, since the clusters already '
                'carry the objects\' positions',
                not line.inheritsTransform.get() and
                not any(handle.inheritsTransform.get() for handle in handles))

    shape = line.getShape()
    suite.check('the line is drawn as template, so it cannot be picked in the viewport',
                shape.overrideEnabled.get() is True and shape.overrideDisplayType.get() ==
                reference_line.DISPLAY_TYPE_TEMPLATE)
    suite.check('and in grey', shape.overrideColor.get() == reference_line.COLOUR_INDEX_GREY)

    end.translate.set(10, 15, 0)
    pm.dgdirty(allPlugs=True)
    moved = line.getShape().getCVs(space='world')
    suite.check('moving one end moves that end of the line, and leaves the other where it was',
                abs(moved[1][1] - 15.0) < 0.0001 and abs(moved[0][1]) < 0.0001, str(moved))

    # The docstring said either end could be a name; it called getTranslation on it straight away.
    named_line = reference_line.create_line_between('line_start', 'line_end',
                                                    name='named_guide_line')
    suite.check('either end can be given as a name rather than a node', named_line is not None)

    # The clincher for the cluster fix: this is two clusters, so it raised inside a namespace.
    pm.namespace(add='hero')
    pm.namespace(set='hero')
    namespaced_line = reference_line.create_line_between(start, end, name='ns_guide_line')
    suite.check('a line can be drawn inside a namespace - it is two clusters, and those used to '
                'raise there',
                namespaced_line is not None)
    suite.check('and its clusters come with it',
                len(reference_line.get_line_clusters(namespaced_line)) == 2)
    pm.namespace(set=':')
    suite.check('an unnamed line still gets a shape name that matches its own',
                str(reference_line.create_line_between(start, end).getShape()).endswith('Shape'))


def check_ik_chain(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import ik_chain
    from mca.mya.rigging.flags import frag_flag

    # -- what it will not build on ------------------------------------------------------------- #
    harness.new_scene()
    joints = _arm(pm, count=2)
    message = suite.raises('a chain of two joints is refused - the solver needs a bend to read a '
                           'plane from',
                           ik_chain.ik_joint_chain, joints[0], joints[-1], 'left', 'arm')
    suite.check('and the refusal says how long the chain was and which joints it walked',
                '2 joints' in message and str(joints[0]) in message and str(joints[-1]) in message,
                message)
    harness.new_scene()
    joints = _arm(pm, count=5)
    suite.raises('a chain of five is refused too',
                 ik_chain.ik_joint_chain, joints[0], joints[-1], 'left', 'arm')

    harness.new_scene()
    joints = _arm(pm, count=3)
    message = suite.raises('an unrecognised rotate order is refused',
                           ik_chain.ik_joint_chain, joints[0], joints[-1], 'left', 'arm',
                           ik_flag_rotate_order='abc')
    suite.check('and the refusal lists the six there are', 'zyx' in message, message)
    # A bare KeyError before; and it was raised part-way through the build.
    suite.check('before anything is built', not cmds.ls(type='ikHandle'))

    # -- a three joint chain ------------------------------------------------------------------- #
    harness.new_scene()
    joints = _arm(pm, count=3)
    result = ik_chain.ik_joint_chain(joints[0], joints[-1], 'left', 'arm')
    ik_handle = result['ik_handle']
    ik_flag = result['ik_flag']
    pv_flag = result['pv_flag']

    suite.check('a rotate-plane IK chain is built', bool(result))
    suite.check('with an IK handle, named for its side and region',
                str(ik_handle) == 'left_arm_ikhandle', str(ik_handle))
    suite.check('hidden, because it is not for the animator',
                ik_handle.visibility.get() is False)
    suite.check('a rotate-plane solver drives it',
                'ikRPsolver' in str(result['ik_solver']), str(result['ik_solver']))
    suite.check('and three controls come back',
                len(result['flags']) == 3 and all(flag is not None for flag in result['flags']))

    # -- the handle's align group -------------------------------------------------------------- #
    align_group = result['ik_zero']
    suite.check('the handle sits in an align group', ik_handle.getParent() == align_group)
    suite.check('named the way every other aligned node in a rig is',
                str(align_group).endswith('_align_transform'), str(align_group))
    suite.check('and carrying the markup that lets it be found again from the handle',
                ik_handle.hasAttr('alignTransform'))
    # The group is what the control drives; a constraint on the handle itself fights the solver.
    suite.check('the handle itself is not constrained',
                not ik_handle.listConnections(type=pm.nt.ParentConstraint,
                                              source=True, destination=False))
    suite.check('the IK control drives the group',
                ik_flag.node in pm.parentConstraint(result['ik_constraint'], query=True,
                                                    targetList=True))

    # -- the pole vector ----------------------------------------------------------------------- #
    suite.check('the pole vector control steers the handle',
                pv_flag.node in pm.poleVectorConstraint(result['pv_constraint'], query=True,
                                                        targetList=True))
    # The bug: the control is built on a temporary locator, and Flag.create wires a control to
    # whatever it was built on - so every pole vector control pointed at a node that had been
    # deleted by the time the build finished.
    suite.check('and it is not wired to the locator it was built on, which is deleted',
                not pv_flag.node.hasAttr('driven_transform'))
    suite.check('the locator is gone', not cmds.ls('left_arm_pv_loc'))

    # What the old wiring left behind, shown with a flag built the same way on purpose.
    throwaway = pm.spaceLocator(name='a_throwaway')
    dangling_flag = frag_flag.Flag.create(throwaway, label='dangling')
    pm.delete(throwaway)
    suite.check('a control wired to a node that is then deleted keeps the attribute and loses the '
                'connection, which is what that used to leave behind',
                dangling_flag.node.hasAttr('driven_transform') and
                not dangling_flag.node.driven_transform.listConnections())
    pm.delete(dangling_flag.get_align_transform())

    # -- the guide line ------------------------------------------------------------------------ #
    pv_line = result['pv_line']
    suite.check('a line is drawn from the middle joint to the pole vector control',
                str(pv_line) == 'left_arm_pv_line', str(pv_line))
    suite.check('and its two clusters come back with the rest of the rig, rather than every caller '
                'walking the shape connections itself',
                len(result['line_clusters']) == 2, str(result['line_clusters']))

    # -- the twist ----------------------------------------------------------------------------- #
    suite.check('the IK control carries a twist attribute, keyable',
                ik_flag.node.hasAttr('ikTwist') and ik_flag.node.ikTwist.isKeyable())
    suite.check('which reaches the handle',
                bool(ik_handle.twist.listConnections(source=True, destination=False)))
    suite.check('a locked separator sits above it in the channel box',
                ik_flag.node.attr(ik_chain.SEPARATOR_ATTR).isLocked() and
                ik_flag.node.attr(ik_chain.SEPARATOR_ATTR).isInChannelBox())
    suite.check('and whatever unit conversion the twist connection made comes back, so the rig can '
                'clean up after itself',
                set(result['unit_conv_nodes']) ==
                set(node for node in ik_flag.node.listConnections()
                    if isinstance(node, pm.nt.UnitConversion)))

    before_twist = joints[1].getTranslation(space='world')
    ik_flag.node.ikTwist.set(60)
    pm.dgdirty(allPlugs=True)
    suite.check('turning the twist rolls the chain about its own axis',
                (joints[1].getTranslation(space='world') - before_twist).length() > 0.1,
                str(joints[1].getTranslation(space='world')))
    ik_flag.node.ikTwist.set(0)

    # -- the offset control -------------------------------------------------------------------- #
    ik_flag_offset = result['ik_flag_offset']
    suite.check('the offset control hangs under the IK control',
                ik_flag_offset.get_align_transform().getParent() == ik_flag.node,
                str(ik_flag_offset.get_align_transform().getParent()))
    suite.check('drawn smaller than it',
                ik_flag_offset.node.getShape().getCVs()[0][0] <
                ik_flag.node.getShape().getCVs()[0][0])
    suite.check('marked as a detail control', ik_flag_offset.node.isDetail.get() is True)
    suite.check('and it is what orients the end of the chain',
                ik_flag_offset.node in pm.orientConstraint(result['offset_constraint'],
                                                           query=True, targetList=True))
    suite.check('each of the two controls knows the other',
                ik_flag_offset.node in ik_flag.node.offsetFlag.listConnections())

    # -- what the controls do ------------------------------------------------------------------ #
    before_end = joints[-1].getTranslation(space='world')
    ik_flag.node.translateY.set(-6)
    pm.dgdirty(allPlugs=True)
    suite.check('moving the IK control moves the end of the chain',
                (joints[-1].getTranslation(space='world') - before_end).length() > 1,
                str(joints[-1].getTranslation(space='world')))
    ik_flag.node.translateY.set(0)

    before_middle = joints[1].getTranslation(space='world')
    pv_flag.node.translateY.set(25)
    pm.dgdirty(allPlugs=True)
    suite.check('and moving the pole vector control swings the middle of it',
                (joints[1].getTranslation(space='world') - before_middle).length() > 0.5,
                str(joints[1].getTranslation(space='world')))
    pv_flag.node.translateY.set(0)

    # -- a four joint chain -------------------------------------------------------------------- #
    harness.new_scene()
    joints = _arm(pm, count=4)
    result = ik_chain.ik_joint_chain(joints[0], joints[-1], 'left', 'arm')
    suite.check('a four joint chain solves over the first three',
                result['ik_end_joint'] == joints[2], str(result['ik_end_joint']))
    # The bug: end_joint was assigned over, so the caller's joint was not what came back.
    suite.check('and the joint the caller asked for comes back as the one they asked for',
                result['end_joint'] == joints[-1], str(result['end_joint']))
    suite.check('the whole run of joints comes back too', result['chain'] == joints,
                str(result['chain']))
    suite.check('the last joint is left outside the IK',
                not joints[-1].listConnections(type=pm.nt.IkHandle))

    # -- a rotate order ------------------------------------------------------------------------ #
    harness.new_scene()
    joints = _arm(pm, count=3)
    plain = ik_chain.ik_joint_chain(joints[0], joints[-1], 'left', 'arm')
    plain_orientation = plain['ik_flag'].node.getRotation(space='world')

    harness.new_scene()
    joints = _arm(pm, count=3)
    turned = ik_chain.ik_joint_chain(joints[0], joints[-1], 'left', 'arm',
                                     ik_flag_rotate_order='zxy')
    suite.check('a rotate order asked for is the one the control gets',
                turned['ik_flag'].node.rotateOrder.get() == ik_chain.ROTATE_ORDERS['zxy'],
                str(turned['ik_flag'].node.rotateOrder.get()))
    turned_orientation = turned['ik_flag'].node.getRotation(space='world')
    suite.check('and changing it leaves the control facing the way it was',
                all(abs(one - other) < 0.001
                    for one, other in zip(plain_orientation, turned_orientation)),
                '{0} against {1}'.format(plain_orientation, turned_orientation))
    suite.check('the locator it was measured onto is gone',
                not [node for node in cmds.ls(type='transform') if node.endswith('_loc')],
                str([node for node in cmds.ls(type='transform') if node.endswith('_loc')]))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_cluster(suite, pm)
    check_reference_line(suite, pm)
    check_ik_chain(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_ik_chain', body))
