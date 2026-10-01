"""
The component that lets a control follow whichever of several things an animator picks.

    mayapy tests/test_frag_multi_constraint.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _switch(pm, frag_base, multi_constraint, region='hand'):
    """A control, three things it can follow, and the switch between them."""

    parent_node = frag_base.FRAGNode.create(None, 'FRAGNode', 1)
    control = pm.spaceLocator(name='f_{0}'.format(region))
    control.translate.set(0, 10, 0)
    targets = []
    for index, (name, position) in enumerate((('the_arm', (10, 10, 0)),
                                              ('the_chest', (0, 20, 0)),
                                              ('the_world', (0, 0, 0)))):
        target = pm.spaceLocator(name=name)
        target.translate.set(position)
        targets.append(target)
    switch_node = multi_constraint.MultiConstraint.create(parent_node, 'left', region, control,
                                                         targets)
    return parent_node, control, targets, switch_node


def check_creating(suite, pm, frag_base, multi_constraint, multi_constraint_rig):
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)

    suite.check('a switch is built', switch_node is not None)
    suite.check('named for what it is and where',
                str(switch_node.pynode) == 'MultiConstraint_left_hand', str(switch_node.pynode))
    suite.check('with the side and region as markup',
                switch_node.side == 'left' and switch_node.region == 'hand')
    suite.check('and the arguments it was built with, read through the one copy of that reader '
                'there is now',
                switch_node.get_build_kwargs().get('switch_attr') ==
                multi_constraint_rig.SWITCH_ATTR,
                str(switch_node.get_build_kwargs()))

    suite.check('the control carries the enum an animator picks with',
                control.hasAttr(multi_constraint_rig.SWITCH_ATTR))
    suite.check('and the node records what that enum is called',
                switch_node.get_switch_attr() == multi_constraint_rig.SWITCH_ATTR,
                str(switch_node.get_switch_attr()))
    suite.check('the enum lists what the control can follow',
                pm.attributeQuery(multi_constraint_rig.SWITCH_ATTR, node=control,
                                  listEnum=True) == ['the_arm:the_chest:the_world'],
                str(pm.attributeQuery(multi_constraint_rig.SWITCH_ATTR, node=control,
                                      listEnum=True)))

    suite.check('every node the switch is made of is on the component',
                all(switch_node.pynode.attr(attr_name).get() is not None for attr_name in
                    (multi_constraint.MULTI_MATRIX_ATTR, multi_constraint.DECOMP_MATRIX_ATTR,
                     multi_constraint.CONSTRAINT_GROUP_ATTR,
                     multi_constraint.PARENT_CONSTRAINT_GROUP_ATTR,
                     multi_constraint.CHOICE_OFFSET_ATTR, multi_constraint.CHOICE_SPACE_ATTR)))
    suite.check('the control it drives is on it', switch_node.get_source_object() == control)
    suite.check('and the control points back at the component that built the switch',
                switch_node.pynode in
                control.attr(multi_constraint.SOURCE_MULTI_CONSTRAINT_ATTR).listConnections())
    suite.check('what carries the enum is on it too, which here is the control itself',
                switch_node.get_switch_object() == control)
    suite.check('and what it can follow, in the order the enum lists them',
                switch_node.get_targets() == targets, str(switch_node.get_targets()))
    suite.check('a switch owns no controls of its own', switch_node.get_flags() == [])

    # -- what it will not build ---------------------------------------------------------------- #
    # The builder refuses and says why; create then connected its empty answer to the node, and what
    # the caller saw was MayaNodeError out of pm.PyNode(None).
    second = multi_constraint.MultiConstraint.create(parent_node, 'left', 'hand_again', control,
                                                     targets)
    suite.check('a second switch on a control that already has one answers nothing, rather than '
                'raising something unreadable',
                second is None)
    suite.check('and nothing was built for it', not pm.ls('MultiConstraint_left_hand_again'),
                str(pm.ls('MultiConstraint_left_hand_again')))

    bare_control = pm.spaceLocator(name='f_nothing_to_follow')
    suite.check('and a switch with nothing to follow answers nothing too',
                multi_constraint.MultiConstraint.create(parent_node, 'left', 'empty', bare_control,
                                                        []) is None)


def check_switching(suite, pm, frag_base, multi_constraint, multi_constraint_rig):
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)

    control.attr(multi_constraint_rig.SWITCH_ATTR).set(0)
    pm.dgdirty(allPlugs=True)
    first_position = control.getTranslation(space='world')
    targets[0].translateX.set(100)
    pm.dgdirty(allPlugs=True)
    suite.check('a control follows the target its enum is set to',
                (control.getTranslation(space='world') - first_position).length() > 1,
                str(control.getTranslation(space='world')))
    targets[0].translateX.set(10)

    control.attr(multi_constraint_rig.SWITCH_ATTR).set(2)
    pm.dgdirty(allPlugs=True)
    before = control.getTranslation(space='world')
    targets[0].translateX.set(100)
    pm.dgdirty(allPlugs=True)
    suite.check('and once the enum is moved on, the one it used to follow no longer moves it',
                (control.getTranslation(space='world') - before).length() < 0.001,
                str(control.getTranslation(space='world')))
    targets[2].translateZ.set(50)
    pm.dgdirty(allPlugs=True)
    suite.check('while the one it points at now does',
                (control.getTranslation(space='world') - before).length() > 1,
                str(control.getTranslation(space='world')))


def check_serializing(suite, pm, frag_base, multi_constraint, multi_constraint_rig):
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)

    data = switch_node.serialize_component()
    suite.check('a switch describes itself by where it is',
                data['side'] == 'left' and data['region'] == 'hand', str(data))
    suite.check('what it drives', data['source_object'] == 'f_hand', str(data['source_object']))
    suite.check('what it can follow',
                data['targets'] == ['the_arm', 'the_chest', 'the_world'], str(data['targets']))
    suite.check('and which attribute picks between them',
                data['switch_attr'] == multi_constraint_rig.SWITCH_ATTR and
                data['switch_object'] == 'f_hand', str(data))


def check_removing(suite, pm, frag_base, multi_constraint, multi_constraint_rig):
    import maya.cmds as cmds

    # Why remove() deletes everything in one call rather than one node at a time, which would read
    # tidier: deleting the decompose matrix takes the component's own node with it, so the tidier
    # version is left with a name that has already gone.
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)
    node_name = str(switch_node.pynode)
    built_nodes = [switch_node.get_parent_constraint_group(),
                   switch_node.pynode.attr(multi_constraint.MULTI_MATRIX_ATTR).get(),
                   switch_node.pynode.attr(multi_constraint.DECOMP_MATRIX_ATTR).get()]
    for built_node in built_nodes:
        pm.delete(built_node)
    suite.check('deleting a switch\'s groups and matrix nodes one at a time takes the component\'s '
                'own node with them, which is why remove deletes the lot in one call',
                not cmds.objExists(node_name), node_name)

    # -- taking a switch off properly ----------------------------------------------------------- #
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)
    before = control.getTranslation(space='world')
    group_name = str(switch_node.get_parent_constraint_group())
    node_name = str(switch_node.pynode)

    switch_node.remove()
    suite.check('taking a switch off a control leaves nothing of it behind',
                not cmds.objExists(group_name) and not cmds.objExists(node_name),
                '{0} and {1}'.format(group_name, node_name))
    suite.check('the control is still there, where it was',
                cmds.objExists('f_hand') and
                (pm.PyNode('f_hand').getTranslation(space='world') - before).length() < 0.001,
                str(pm.PyNode('f_hand').getTranslation(space='world')))
    suite.check('and the enum is gone from it',
                not pm.PyNode('f_hand').hasAttr(multi_constraint_rig.SWITCH_ATTR))
    suite.check('along with everything else the switch put on it',
                not pm.PyNode('f_hand').hasAttr(multi_constraint.SOURCE_MULTI_CONSTRAINT_ATTR))

    # The bug: every attribute in the list is guarded with hasAttr except sourceMultiConstraint,
    # which was deleted outright.
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)
    control.attr(multi_constraint.SOURCE_MULTI_CONSTRAINT_ATTR).unlock()
    control.deleteAttr(multi_constraint.SOURCE_MULTI_CONSTRAINT_ATTR)
    node_name = str(switch_node.pynode)
    switch_node.remove()
    suite.check('a switch whose control has already been tidied up by hand comes off anyway',
                not cmds.objExists(node_name), node_name)

    # The bug: both objects are read off message attributes, either can answer nothing, and the next
    # line asked hasAttr of it.
    harness.new_scene()
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)
    pm.delete(control)
    suite.check('the control it drove having gone leaves nothing to read it off',
                switch_node.get_source_object() is None)
    node_name = str(switch_node.pynode)
    switch_node.remove()
    suite.check('and the switch still comes off, rather than raising on it',
                not cmds.objExists(node_name), node_name)


def check_namespaces(suite, pm, frag_base, multi_constraint, multi_constraint_rig):
    import maya.cmds as cmds

    harness.new_scene()
    if not cmds.namespace(exists='hero'):
        cmds.namespace(add='hero')
    cmds.namespace(set=':hero')

    # The bug: `pm.namespace(set='hero:')` is a relative name, resolved against whatever namespace
    # is active - so building a switch while the active namespace was already the rig's own looked
    # for ':hero:hero' and raised 'No namespace matches name'. Four modules had it.
    parent_node, control, targets, switch_node = _switch(pm, frag_base, multi_constraint)
    suite.check('a switch builds while the active namespace is already the rig\'s, rather than '
                'raising', switch_node is not None)
    suite.check('and the active namespace is put back afterwards',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
    cmds.namespace(set=':')


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging import multi_constraint_rig
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import multi_constraint
    check_creating(suite, pm, frag_base, multi_constraint, multi_constraint_rig)
    check_switching(suite, pm, frag_base, multi_constraint, multi_constraint_rig)
    check_serializing(suite, pm, frag_base, multi_constraint, multi_constraint_rig)
    check_removing(suite, pm, frag_base, multi_constraint, multi_constraint_rig)
    check_namespaces(suite, pm, frag_base, multi_constraint, multi_constraint_rig)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_multi_constraint', body))
