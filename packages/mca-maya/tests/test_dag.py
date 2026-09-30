"""
Walking the DAG: mca.mya.utils.dag.

    mayapy tests/test_dag.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def build_chain(pm, names, parent=None, node_type='joint'):
    """A straight chain of nodes, each a child of the one before."""

    made = []
    previous = parent
    for index, name in enumerate(names):
        node = pm.createNode(node_type, name=name)
        node.t.set(index and 5 or 0, 0, 0)
        if previous is not None:
            node.setParent(previous)
        made.append(node)
        previous = node
    return made


def check_between(suite, pm):
    from mca.mya.utils import dag

    harness.new_scene()
    root, middle, tip = build_chain(pm, ['root_jnt', 'middle_jnt', 'tip_jnt'])

    found = dag.get_between_nodes(root, tip)
    suite.check('the nodes between two ends come back, both ends included',
                found == [root, middle, tip], str(found))
    suite.check('the top of the walk is first', found[0] == root)
    suite.check('a node and itself is just that node',
                dag.get_between_nodes(middle, middle) == [middle])
    suite.check('names work as well as PyNodes',
                dag.get_between_nodes('root_jnt', 'tip_jnt') == [root, middle, tip])

    group = pm.createNode('transform', name='in_the_way')
    middle.setParent(group)
    group.setParent(root)
    suite.check('a node_type filter drops what is not of that type',
                dag.get_between_nodes(root, tip, node_type=pm.nt.Joint) == [root, middle, tip])
    suite.check('and without the filter the group is in there',
                group in dag.get_between_nodes(root, tip))

    # The bug: two nodes in different hierarchies made this loop forever, appending None to
    # a list until Maya ran out of memory. Twenty-one places in the pipeline call it.
    stranger = pm.createNode('joint', name='stranger_jnt')
    suite.check('two nodes in different hierarchies answer empty instead of hanging',
                dag.get_between_nodes(stranger, tip) == [])
    suite.check('and the other way round too',
                dag.get_between_nodes(tip, stranger) == [])
    suite.check('a child asked for the nodes down to its own parent answers empty',
                dag.get_between_nodes(tip, root) == [])


def check_parents(suite, pm):
    from mca.mya.utils import dag

    harness.new_scene()
    group = pm.createNode('transform', name='skeleton_grp')
    root, middle, tip = build_chain(pm, ['root_jnt', 'middle_jnt', 'tip_jnt'], parent=group)

    suite.check('every parent up to the scene root',
                dag.get_all_parents(tip) == [middle, root, group], str(dag.get_all_parents(tip)))
    suite.check('closest first', dag.get_all_parents(tip)[0] == middle)
    suite.check('a node at the top has no parents', dag.get_all_parents(group) == [])
    suite.check('filtering for joints stops at the group',
                dag.get_all_parents(tip, node_type=pm.nt.Joint) == [middle, root],
                str(dag.get_all_parents(tip, node_type=pm.nt.Joint)))

    suite.check('the top of the hierarchy', dag.get_absolute_parent(tip) == group)
    suite.check('the top joint of the hierarchy',
                dag.get_absolute_parent(tip, node_type=pm.nt.Joint) == root)
    suite.check('a node with no parent answers itself when inclusive',
                dag.get_absolute_parent(group) == group)
    suite.check('and None when not',
                dag.get_absolute_parent(group, inclusive=False) is None)
    suite.check('something that is not a transform answers None',
                dag.get_absolute_parent('not a node at all') is None)


def check_children(suite, pm):
    from mca.mya.utils import dag

    harness.new_scene()
    root, middle, tip = build_chain(pm, ['root_jnt', 'middle_jnt', 'tip_jnt'])

    suite.check('the deepest child of a chain is its tip', dag.get_absolute_child(root) == tip)
    suite.check('the deepest joint, when filtering for joints',
                dag.get_absolute_child(root, node_type=pm.nt.Joint) == tip)
    suite.check('a node with nothing below it answers itself when inclusive',
                dag.get_absolute_child(tip) == tip)
    suite.check('and None when not',
                dag.get_absolute_child(tip, inclusive=False) is None)

    # The bug: getChildren() with no filter hands back the node's own shape, the guard
    # returned a bare None rather than the pair the caller unpacks, and the whole thing
    # raised TypeError. Any joint with a shape hung off it - which is every animation
    # control in the pipeline - hit this.
    circle = pm.circle(name='shape_holder', constructionHistory=False)[0]
    circle.setParent(tip)
    suite.check('a transform with a shape does not raise',
                dag.get_absolute_child(root) == circle,
                str(dag.get_absolute_child(root)))
    shape = circle.getShape()
    suite.check('and the shape itself is not the answer',
                dag.get_absolute_child(root) != shape)
    suite.check('filtering for joints still finds the tip joint, not the curve',
                dag.get_absolute_child(root, node_type=pm.nt.Joint) == tip)

    # -- get_children_in_order ---------------------------------------------------------- #
    harness.new_scene()
    root = pm.createNode('joint', name='spine_01')
    spine_02 = pm.createNode('joint', name='spine_02')
    spine_02.setParent(root)
    left = pm.createNode('joint', name='l_arm')
    right = pm.createNode('joint', name='r_arm')
    left.setParent(spine_02)
    right.setParent(spine_02)
    hand = pm.createNode('joint', name='l_hand')
    hand.setParent(left)

    ordered = dag.get_children_in_order(root, pm.nt.Joint)
    suite.check('the root comes first', ordered[0] == root, str(ordered))
    suite.check('every joint is in there once',
                sorted(str(one) for one in ordered) ==
                sorted(['spine_01', 'spine_02', 'l_arm', 'r_arm', 'l_hand']), str(ordered))
    suite.check('a parent always comes before its child',
                ordered.index(spine_02) < ordered.index(left) < ordered.index(hand),
                str(ordered))
    suite.check('both branches are there before the deeper one',
                ordered.index(right) < ordered.index(hand), str(ordered))
    suite.check('the root is left out when asked',
                root not in dag.get_children_in_order(root, pm.nt.Joint, start=False))
    suite.check('something that is not a transform answers an empty list, not None',
                dag.get_children_in_order('nothing here') == [])

    suite.check('get_ordered_hierarchy is gone - it answered the same question',
                not hasattr(dag, 'get_ordered_hierarchy'))
    suite.check('create_line_between is gone - rig_utils has the one the callers use',
                not hasattr(dag, 'create_line_between'))


def check_primary_axis(suite, pm):
    from mca.mya.utils import dag

    harness.new_scene()
    root = pm.createNode('joint', name='bone_root')
    child = pm.createNode('joint', name='bone_child')
    child.setParent(root)

    child.t.set(10, 1, 0)
    suite.check('the axis the bone runs down is read from the child',
                dag.get_primary_axis(root) == ('x', True), str(dag.get_primary_axis(root)))
    child.t.set(-10, 1, 0)
    suite.check('and its sign', dag.get_primary_axis(root) == ('x', False))
    child.t.set(1, -10, 0)
    suite.check('y works', dag.get_primary_axis(root) == ('y', False))
    child.t.set(1, 2, 10)
    suite.check('z works', dag.get_primary_axis(root) == ('z', True))

    lonely = pm.createNode('joint', name='lonely')
    lonely.t.set(0, 7, 0)
    suite.check('a node with no child is read from its own translation',
                dag.get_primary_axis(lonely) == ('y', True))
    lonely.t.set(0, 0, 0)
    suite.check('a node with no offset at all answers x, there being nothing to read',
                dag.get_primary_axis(lonely) == ('x', True))


def check_shapes(suite, pm):
    from mca.mya.utils import dag

    harness.new_scene()
    curve = pm.circle(name='new_curve', constructionHistory=False)[0]
    control = pm.createNode('transform', name='the_control')
    old_shape = pm.circle(name='old_curve', constructionHistory=False)[0]
    pm.parent(old_shape.getShape(), control, add=True, shape=True)
    pm.delete(old_shape)

    moved = dag.parent_shape_node(curve, control)
    suite.check('a shape lands on the destination', moved is not None)
    suite.check('the destination has exactly one shape', len(control.getShapes()) == 1,
                str(control.getShapes()))
    suite.check('the source transform is gone', not pm.objExists('new_curve'))
    suite.check('the shape is named after the destination it replaced',
                'old_curve' in str(control.getShapes()[0]), str(control.getShapes()[0]))

    # Two shapes onto one transform, keeping the existing one.
    harness.new_scene()
    control = pm.createNode('transform', name='two_shape_control')
    first = pm.circle(name='first_curve', constructionHistory=False)[0]
    second = pm.circle(name='second_curve', constructionHistory=False)[0]
    dag.parent_shape_node([first, second], control, replace=False, swap_names=False)
    suite.check('two shapes can land on one transform', len(control.getShapes()) == 2,
                str(control.getShapes()))
    names = [str(one).split('|')[-1] for one in control.getShapes()]
    suite.check('and are numbered rather than clashing',
                len(set(names)) == 2, str(names))

    suite.check('nothing to move answers None',
                dag.parent_shape_node([], control) is None)
    suite.check('no destination answers None',
                dag.parent_shape_node(pm.createNode('transform'), None) is None)

    # -- colours ------------------------------------------------------------------------ #
    harness.new_scene()
    curve = pm.circle(name='coloured', constructionHistory=False)[0]
    shape = curve.getShape()

    data = dag.get_node_color_data(shape)
    suite.check('a node with no override reports the override off',
                data['overrideEnabled'] is False, str(data))
    suite.check('and black rather than whatever was in the unused attribute',
                data['overrideColorRGB'] == [0.0, 0.0, 0.0], str(data))

    dag.set_node_color(shape, 13)
    data = dag.get_node_color_data(shape)
    suite.check('an index colour turns the override on and is read back',
                data['overrideEnabled'] and data['overrideColor'] == 13, str(data))
    suite.check('and does not switch the node into RGB mode',
                data['overrideRGBColors'] is False, str(data))

    dag.set_node_color(shape, (0.4, 0.07, 0.07))
    data = dag.get_node_color_data(shape)
    suite.check('an RGB colour switches the node into RGB mode',
                data['overrideRGBColors'] is True, str(data))
    suite.check('and is read back', all(
        abs(got - wanted) < 0.001 for got, wanted
        in zip(data['overrideColorRGB'], (0.4, 0.07, 0.07))), str(data['overrideColorRGB']))

    # The bug: this used to raise in a batch Maya. It set the colours it was asked for and
    # then called a MEL procedure from the attribute editor scripts, which a headless Maya
    # never loads, so every batch build or export that coloured an outliner entry stopped
    # here with "Cannot find procedure".
    dag.set_node_color(shape, (1.0, 1.0, 1.0), outliner_color=(0.0, 1.0, 0.0),
                       use_outliner_color=True)
    suite.check('setting an outliner colour does not raise in a batch Maya', True)
    data = dag.get_node_color_data(shape)
    suite.check('the outliner colour is set', data['useOutlinerColor'] is True, str(data))
    suite.check('and read back', all(
        abs(got - wanted) < 0.001 for got, wanted
        in zip(data['outlinerColor'], (0.0, 1.0, 0.0))), str(data['outlinerColor']))

    # True is an int in Python, and would have been read as colour index 1.
    other = pm.circle(name='bool_colour', constructionHistory=False)[0].getShape()
    dag.set_node_color(other, (1.0, 0.0, 0.0))
    suite.check('an RGB colour is never mistaken for a colour index',
                dag.get_node_color_data(other)['overrideRGBColors'] is True)

    suite.check('a list of nodes can be coloured at once',
                dag.set_node_color([shape, other], 17) is None and
                dag.get_node_color_data(other)['overrideColor'] == 17)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_between(suite, pm)
    check_parents(suite, pm)
    check_children(suite, pm)
    check_primary_axis(suite, pm)
    check_shapes(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('dag', body))
