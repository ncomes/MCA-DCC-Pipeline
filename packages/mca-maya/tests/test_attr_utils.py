"""
Attributes: mca.mya.utils.attr_utils.

    mayapy tests/test_attr_utils.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_asking(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('transform', name='asker')
    node.addAttr('a_label', type='string')
    node.a_label.set('written down')

    suite.check('an attribute that is there is found',
                attr_utils.has_attribute(node, 'a_label') is True)
    suite.check('a built-in attribute is found',
                attr_utils.has_attribute(node, 'translateX') is True)
    suite.check('one that is not there is not',
                attr_utils.has_attribute(node, 'no_such_attribute') is False)
    suite.check('a name works as well as a PyNode',
                attr_utils.has_attribute('asker', 'a_label') is True)
    suite.raises('a node that is not there raises', attr_utils.has_attribute,
                 'no_such_node', 'a_label')

    suite.check('a string attribute reads back',
                attr_utils.get_attribute(node, 'a_label') == 'written down')
    suite.raises('any other type is refused rather than answered wrongly',
                 attr_utils.get_attribute, node, 'translateX', 'double')

    # -- get_all_objects_with_attr ------------------------------------------------------ #
    # The bug: the search string was built as f'{ns[1:]}:*.{attr}', dropping the first
    # character of every namespace name, so 'char' was searched for as 'har'. Nothing outside
    # the root namespace was ever found.
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    root_node = pm.createNode('transform', name='in_the_root')
    root_node.addAttr('mcaMarker', type='bool')
    cmds.namespace(add='hero')
    cmds.namespace(setNamespace=':hero')
    inside = pm.createNode('transform', name='in_a_namespace')
    inside.addAttr('mcaMarker', type='bool')
    joint_inside = pm.createNode('joint', name='a_joint')
    joint_inside.addAttr('mcaMarker', type='bool')
    cmds.namespace(setNamespace=':')

    found = [str(one) for one in attr_utils.get_all_objects_with_attr('mcaMarker')]
    suite.check('a node in the root namespace is found',
                any('in_the_root' in one for one in found), str(found))
    suite.check('a node inside a namespace is found - the whole bug',
                any('in_a_namespace' in one for one in found), str(found))
    suite.check('each node once', len(found) == len(set(found)), str(found))
    typed = attr_utils.get_all_objects_with_attr('mcaMarker', of_type='joint')
    suite.check('filtering by type works',
                [str(one) for one in typed] == ['hero:a_joint'],
                str([str(one) for one in typed]))
    suite.check('names rather than PyNodes when asked',
                all(isinstance(one, str)
                    for one in attr_utils.get_all_objects_with_attr(
                        'mcaMarker', as_pynode=False)))
    suite.check('an attribute nobody has answers empty',
                attr_utils.get_all_objects_with_attr('noSuchMarker') == [])


def check_locking(suite, pm):
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('transform', name='lockable')

    attr_utils.set_attr_state([node])
    suite.check('every transform attribute locks by default',
                all(node.attr(name).isLocked() for name in attr_utils.TRANSFORM_ATTRS))
    attr_utils.set_attr_state([node], locked=False)
    suite.check('and unlocks',
                not any(node.attr(name).isLocked() for name in attr_utils.TRANSFORM_ATTRS))

    attr_utils.set_attr_state(node, attr_list=['tx'], visibility=True)
    suite.check('one attribute can be locked on its own', node.tx.isLocked())
    suite.check('and taken out of the channel box', not node.tx.isKeyable())
    suite.check('while its neighbour is left alone', not node.ty.isLocked())
    attr_utils.set_attr_state(node, locked=False, attr_list=['tx'], visibility=True)
    suite.check('and put back', node.tx.isKeyable() and not node.tx.isLocked())
    suite.check('nothing to do is not an error', attr_utils.set_attr_state([]) is None)

    # A locked parent makes its children unsettable whatever their own lock says, which is why
    # set_attr_state opens the parents first.
    node.t.lock()
    attr_utils.set_attr_state(node, locked=False, attr_list=['tx'])
    suite.check('a locked parent is opened so a child can be unlocked',
                node.tx.isSettable(), 'translate still locked')

    attr_utils.lock_and_hide_attrs(node, ['tx', 'ty'])
    suite.check('lock_and_hide_attrs locks', node.tx.isLocked() and node.ty.isLocked())
    suite.check('and hides', not node.tx.isKeyable() and not node.tx.isInChannelBox())
    attr_utils.lock_and_hide_attrs(node, 'tz')
    suite.check('one name on its own works', node.tz.isLocked())

    attr_utils.unlock_and_show_attrs([node.tx, node.ty, node.tz])
    suite.check('unlock_and_show_attrs unlocks',
                not node.tx.isLocked() and not node.tz.isLocked())
    suite.check('and shows', node.tx.isKeyable())

    node.rx.lock()
    node.ry.lock()
    was_locked = attr_utils.unlock_transform_attributes(node)
    suite.check('unlock_transform_attributes unlocks everything',
                not any(node.attr(name).isLocked() for name in attr_utils.TRANSFORM_ATTRS))
    suite.check('and says which had been locked',
                {str(one).split('.')[-1] for one in was_locked} == {'rotateX', 'rotateY'},
                str(was_locked))
    suite.check('a named subset works',
                attr_utils.unlock_transform_attributes(node, ['sx']) == [])

    # -- lock_all_keyable_attrs --------------------------------------------------------- #
    # The bug: allow_visibility did nothing. The test compared a pm.Attribute against the
    # string '<node>.v', which is never equal, so the first half of the `or` was always true.
    harness.new_scene()
    node = pm.createNode('transform', name='keyable_probe')
    attr_utils.lock_all_keyable_attrs(node)
    suite.check('every keyable attribute locks', node.tx.isLocked() and node.sz.isLocked())
    suite.check('including visibility, when it is not excused', node.v.isLocked())

    attr_utils.unlock_all_attrs(node)
    attr_utils.lock_all_keyable_attrs(node, allow_visibility=True)
    suite.check('allow_visibility leaves visibility alone - it used to do nothing',
                not node.v.isLocked())
    suite.check('and locks the rest', node.tx.isLocked())

    attr_utils.unlock_all_attrs(node, show=True)
    suite.check('unlock_all_attrs unlocks everything',
                not node.tx.isLocked() and not node.v.isLocked())
    suite.check('and makes them keyable when asked', node.tx.isKeyable())
    suite.raises('a node that is not there raises', attr_utils.unlock_all_attrs, 'nowhere')
    suite.raises('and so does lock_all_keyable_attrs',
                 attr_utils.lock_all_keyable_attrs, 'nowhere')

    attr_utils.lock_all_keyable_attrs(node, hidden=True)
    suite.check('hidden takes them out of the channel box too', not node.tx.isKeyable())

    # -- unlock_node_attributes --------------------------------------------------------- #
    harness.new_scene()
    node = pm.createNode('transform', name='unlockable')
    node.tx.lock()
    node.addAttr('a_setting', type='double')
    node.a_setting.lock()
    unlocked = attr_utils.unlock_node_attributes(node)
    suite.check('everything locked is unlocked',
                not node.tx.isLocked() and not node.a_setting.isLocked())
    suite.check('and reported', len(unlocked) == 2, str(unlocked))
    node.ty.lock()
    suite.check('a named attribute can be unlocked on its own',
                len(attr_utils.unlock_node_attributes(node, ['ty'])) == 1)
    suite.check('and one that is not locked is not reported',
                attr_utils.unlock_node_attributes(node, ['tz']) == [])

    # -- purge_user_defined_attrs ------------------------------------------------------- #
    # The bug: the `return` for "this node has nothing to purge" sat inside the loop over
    # nodes, so purging a selection stopped at the first bare node - and answered None.
    harness.new_scene()
    bare = pm.createNode('transform', name='nothing_added')
    covered = pm.createNode('transform', name='plenty_added')
    covered.addAttr('one', type='double')
    covered.addAttr('two', type='string')
    covered.addAttr('keep_me', type='bool')

    purged = attr_utils.purge_user_defined_attrs([bare, covered], skip_dialog=True)
    suite.check('the node after the bare one is still purged - the whole bug',
                not covered.hasAttr('one') and not covered.hasAttr('two'), str(purged))
    suite.check('and the answer is a list, not None', isinstance(purged, list), repr(purged))
    suite.check('the built-in attributes are left', covered.hasAttr('translateX'))

    covered.addAttr('one', type='double')
    covered.addAttr('keep_me_too', type='bool')
    attr_utils.purge_user_defined_attrs(covered, skip_list=['keep_me_too'], skip_dialog=True)
    suite.check('an attribute in the skip list survives', covered.hasAttr('keep_me_too'))
    suite.check('and the others go', not covered.hasAttr('one'))

    locked_up = pm.createNode('transform', name='locked_attrs')
    locked_up.addAttr('stuck', type='double')
    locked_up.stuck.lock()
    attr_utils.purge_user_defined_attrs(locked_up, skip_dialog=True)
    suite.check('a locked user attribute is unlocked and deleted',
                not locked_up.hasAttr('stuck'))


def check_resetting(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('transform', name='resettable')
    node.t.set(1, 2, 3)
    node.r.set(10, 20, 30)
    node.s.set(2, 2, 2)
    node.v.set(False)
    # Keyable: reset_attrs only walks keyable attributes, which is what a reset means to an
    # animator. A non-keyable setting is not something Ctrl-clicking "reset" should undo.
    node.addAttr('a_dial', type='double', defaultValue=0.5, keyable=True)
    node.a_dial.set(0.9)
    node.addAttr('a_setting', type='double', defaultValue=0.5)
    node.a_setting.set(0.9)

    was_set = attr_utils.reset_attrs(node)
    suite.check('translate goes back to zero', list(node.t.get()) == [0.0, 0.0, 0.0])
    suite.check('rotate goes back to zero',
                [round(one, 5) for one in node.r.get()] == [0.0, 0.0, 0.0])
    suite.check('scale goes back to one', list(node.s.get()) == [1.0, 1.0, 1.0])
    suite.check('visibility goes back on', node.v.get() is True)
    suite.check('a keyable user attribute goes back to its own default',
                node.a_dial.get() == 0.5)
    suite.check('a user attribute that is not keyable is left alone',
                node.a_setting.get() == 0.9)
    suite.check('and the attributes that were set are reported', len(was_set) >= 10,
                str(len(was_set)))

    node.t.set(5, 5, 5)
    node.tx.lock()
    attr_utils.reset_attrs(node)
    suite.check('a locked attribute is left where it is', node.tx.get() == 5.0)
    suite.check('and its neighbours are still reset', node.ty.get() == 0.0)
    node.tx.unlock()

    # An attribute driven by something that is not animation is skipped; one driven by an anim
    # curve is not, because replacing a key is what a reset means.
    driver = pm.createNode('transform', name='driver')
    pm.connectAttr(driver.translateZ, node.translateZ)
    node.ty.set(7)
    cmds.setKeyframe(str(node), attribute='translateY', time=1, value=7)
    attr_utils.reset_attrs(node)
    suite.check('a connected attribute is skipped rather than raising',
                pm.isConnected(driver.translateZ, node.translateZ))
    suite.check('a keyed attribute is still reset', node.ty.get() == 0.0)

    suite.raises('a node that is not there raises', attr_utils.reset_attrs, 'nowhere')


def check_setting_data(suite, pm):
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('network', name='data_holder')
    other = pm.createNode('transform', name='pointed_at')

    # The bug: MAYA_TYPE_DICT mapped int to the Python type `int` rather than to a Maya type
    # name, so addAttr(attributeType=<class 'int'>) is what a whole number produced.
    suite.check('MAYA_TYPE_DICT names a Maya type for every Python type it lists',
                all(isinstance(one, str) for one in attr_utils.MAYA_TYPE_DICT.values()),
                str(attr_utils.MAYA_TYPE_DICT))
    suite.check('and an integer is a long', attr_utils.MAYA_TYPE_DICT[int] == 'long')

    written = attr_utils.set_attribute(node, {
        'a_flag': True,
        'a_count': 7,
        'a_measure': 1.5,
        'a_label': 'hello',
        'a_link': other,
        'nothing_yet': None,
    })
    suite.check('a bool is stored', node.a_flag.get() is True)
    suite.check('a whole number is stored - it could not be, before', node.a_count.get() == 7,
                repr(node.a_count.get()) if node.hasAttr('a_count') else 'no attribute')
    suite.check('and as a long, not a bool', node.a_count.type() == 'long', node.a_count.type())
    suite.check('a float is stored', abs(node.a_measure.get() - 1.5) < 0.0001)
    suite.check('a string is stored', node.a_label.get() == 'hello')
    suite.check('a node is wired in, not set',
                node.a_link.type() == 'message' and other in node.a_link.listConnections())
    suite.check('a None makes a message attribute to fill in later',
                node.nothing_yet.type() == 'message')
    suite.check('and the names written are reported', len(written) == 5, str(written))

    node_b = pm.createNode('network', name='multi_holder')
    attr_utils.set_attribute(node_b, {'some_labels': ['one', 'two', 'three']})
    suite.check('a list becomes a multi attribute', node_b.some_labels.isMulti())
    suite.check('with every value in it',
                [node_b.some_labels[index].get() for index in range(3)] ==
                ['one', 'two', 'three'])

    attr_utils.set_attribute(node_b, {'some_labels': ['four']}, merge_values=True)
    suite.check('merging adds to what is there rather than replacing it',
                node_b.some_labels[3].get() == 'four',
                str([node_b.some_labels[index].get() for index in range(4)]))

    class Unknown(object):
        def __str__(self):
            return 'unknown thing'

    node_c = pm.createNode('network', name='odd_holder')
    attr_utils.set_attribute(node_c, {'odd': Unknown()})
    suite.check('a type the table does not cover falls back to a string',
                node_c.odd.type() == 'string')


def check_compound_data(suite, pm):
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('network', name='block_holder')
    target = pm.createNode('transform', name='block_target')

    attr_utils.set_compound_attribute_groups(node, 'markup', {
        'name': 'hero_bot',
        'count': 3,
        'ratio': 0.25,
        'is_hero': True,
        'owner': target,
        'unset': None,
        7: 'a key that is not a string',
    })

    suite.check('the block is there', node.hasAttr('markup'))
    suite.check('and is a compound', node.markup.type() == 'TdataCompound')
    suite.check('a string property is set', node.markup_name.get() == 'hero_bot')
    suite.check('a whole number property is set - it could not be, before',
                node.markup_count.get() == 3)
    suite.check('a float property is set', abs(node.markup_ratio.get() - 0.25) < 0.0001)
    suite.check('a bool property is set', node.markup_is_hero.get() is True)
    suite.check('a node property is wired in', target in node.markup_owner.listConnections())
    suite.check('a None property is a string, waiting', node.markup_unset.type() == 'string')
    suite.check('a key that is not a string is skipped', not node.hasAttr('markup_7'))

    suite.check('the channel box workaround child is there', node.hasAttr('_markup_hidden'))
    suite.check('and is not named as a property, so the exporter skips it',
                not node.hasAttr('markup__markup_hidden'))

    children = attr_utils.get_all_attributes_from_compound_attr(node, 'markup')
    names = [str(one).split('.')[-1] for one in children]
    suite.check('the block gives up its children', 'markup_name' in names, str(names))
    suite.check('and does not list itself among them', 'markup' not in names, str(names))
    suite.check('the same, given the attribute rather than the node and a name',
                [str(one) for one in
                 attr_utils.get_all_attributes_from_compound_attr(node.markup)] ==
                [str(one) for one in children])
    suite.check('a block that is not there answers None, rather than raising on a class that '
                'does not exist',
                attr_utils.get_all_attributes_from_compound_attr(node, 'no_such_block') is None)

    connected = attr_utils.get_compound_attr_connections(node, 'markup')
    suite.check('what is wired into a block is found', target in connected, str(connected))
    plugs = attr_utils.get_compound_attr_connections(node, 'markup', as_plugs=True)
    suite.check('and as plugs when asked',
                any(str(one).endswith('.message') for one in plugs), str(plugs))
    suite.check('a block that is not there answers None',
                attr_utils.get_compound_attr_connections(node, 'no_such_block') is None)

    suite.check('the compound attributes on a node can be listed',
                'markup' in attr_utils.get_compound_attr_names(node),
                str(attr_utils.get_compound_attr_names(node)))

    attr_utils.set_compound_attribute_groups(node, 'markup', {'name': 'changed'})
    suite.check('writing a block again replaces it', node.markup_name.get() == 'changed')
    suite.check('and the properties that are gone are gone', not node.hasAttr('markup_count'))

    attr_utils.set_compound_attribute_groups(node, 'empty_block', {})
    suite.check('a block with no properties is still there to be found',
                node.hasAttr('empty_block'))

    attr_utils.set_compound_attribute_groups(node, 'lists', {'labels': ['a', 'b']})
    suite.check('a list property becomes a multi', node.lists_labels.isMulti())
    suite.check('with its values', node.lists_labels[1].get() == 'b')

    attr_utils.set_compound_attribute_groups(node, 'nodes', {'targets': [target]})
    suite.check('a list of nodes is wired in',
                target in node.nodes_targets[0].listConnections(),
                str(node.nodes_targets[0].listConnections()))

    suite.check('a block can be unwired and deleted',
                attr_utils.disconnect_and_delete_compound_attr(node, 'nodes') is True)
    suite.check('and is gone', not node.hasAttr('nodes'))
    suite.check('a block that is not there answers False rather than raising',
                attr_utils.disconnect_and_delete_compound_attr(node, 'no_such_block') is False)


def check_message_and_limits(suite, pm):
    from mca.mya.utils import attr_utils

    harness.new_scene()
    source = pm.createNode('transform', name='the_source')
    target = pm.createNode('transform', name='the_target')

    suite.check('two nodes can be wired together through new message attributes',
                attr_utils.connect_nodes_with_message_attrs(
                    source, 'points_at', target, 'pointed_at_by') is True)
    suite.check('and the connection is there',
                pm.isConnected(source.points_at, target.pointed_at_by))
    suite.check('the attributes made are message attributes',
                source.points_at.type() == 'message')

    source.addAttr('not_a_message', type='double')
    suite.raises('an attribute that is there and is not a message attribute is refused',
                 attr_utils.connect_nodes_with_message_attrs,
                 source, 'not_a_message', target, 'other')
    suite.raises('something that is neither a name nor an attribute is refused',
                 attr_utils.connect_nodes_with_message_attrs, source, 37, target, 'other')

    removed = attr_utils.remove_relationship_between_nodes(source, target)
    suite.check('the relationship can be taken apart',
                not pm.isConnected(source.points_at, target.pointed_at_by))
    suite.check('and says what it disconnected', len(removed) == 1, str(removed))
    suite.check('doing it again disconnects nothing',
                attr_utils.remove_relationship_between_nodes(source, target) == [])

    # -- invert_attribute --------------------------------------------------------------- #
    # The bug: five setAttr calls named the attribute relatively - '.min' - which means
    # "whatever is selected". It worked only because createNode leaves its node selected.
    harness.new_scene()
    node = pm.createNode('transform', name='switch')
    node.addAttr('amount', type='double', min=0, max=1, keyable=True)
    decoy = pm.createNode('setRange', name='decoy_range')
    pm.select(decoy, replace=True)

    reverse_node = attr_utils.invert_attribute(node.amount)
    suite.check('a setRange node is made', isinstance(reverse_node, pm.nt.SetRange))
    suite.check('its values went onto it, not onto whatever was selected',
                list(reverse_node.min.get()) == [0.0, 1.0, 0.0], str(reverse_node.min.get()))
    suite.check('and the decoy that was selected is untouched',
                list(decoy.min.get()) == [0.0, 0.0, 0.0], str(decoy.min.get()))
    suite.check('the outputs are aliased so they read as what they are',
                reverse_node.hasAttr('inverse') and reverse_node.hasAttr('straight'))

    node.amount.set(1.0)
    suite.check('the straight output follows the attribute',
                abs(reverse_node.attr('straight').get() - 1.0) < 0.001)
    suite.check('the inverse output is one minus it',
                abs(reverse_node.attr('inverse').get() - 0.0) < 0.001)
    suite.check('and the percentage output is it out of a hundred',
                abs(reverse_node.attr('percentage').get() - 100.0) < 0.001)
    node.amount.set(0.25)
    suite.check('and again at a quarter',
                abs(reverse_node.attr('inverse').get() - 0.75) < 0.001,
                str(reverse_node.attr('inverse').get()))

    # -- set_limits --------------------------------------------------------------------- #
    # The limit recorder used to call attr.lock(True), where pymel's lock takes
    # checkReference - so the True was asking Maya to raise if the attribute belonged to a
    # referenced node, which is not what the docstring said it meant.
    harness.new_scene()
    flag = pm.createNode('transform', name='limited_flag')
    network = pm.createNode('network', name='limit_record')

    limits = attr_utils.set_limits(flag, network,
                                   limit_point=((-5, 5), (None, None), (0, 10)),
                                   limit_orient=((None, 45), (None, None), (None, None)))
    suite.check('the limits are applied without raising', limits is not None)
    suite.check('a translate limit is on the control',
                pm.transformLimits(flag, query=True, tx=True) == [-5.0, 5.0],
                str(pm.transformLimits(flag, query=True, tx=True)))
    suite.check('and it is turned on',
                pm.transformLimits(flag, query=True, etx=True) == [True, True],
                str(pm.transformLimits(flag, query=True, etx=True)))
    suite.check('an axis with one limit has only that one turned on',
                pm.transformLimits(flag, query=True, erx=True) == [False, True],
                str(pm.transformLimits(flag, query=True, erx=True)))

    suite.check('the limits are recorded on the network node',
                network.hasAttr('translateLimitX') and network.hasAttr('orientLimitZ'))
    suite.check('with the values in them',
                abs(network.translateLimitXMin.get() - -5.0) < 0.001 and
                abs(network.translateLimitXMax.get() - 5.0) < 0.001)
    suite.check('a limit that was set is left unlocked, so it can be changed',
                not network.translateLimitXMin.isLocked())
    suite.check('and one that was not is locked', network.orientLimitZMin.isLocked())

    suite.check('an axis with no limits either way is locked and hidden',
                flag.ty.isLocked() and not flag.ty.isKeyable())
    suite.check('an axis with limits is left usable',
                not flag.tx.isLocked() and flag.tx.isKeyable())
    # any((0, 10)) is True, but any((0, 0)) is False - which is how a limit of zero used to be
    # read as no limit at all.
    suite.check('an axis limited to zero in one direction is still usable',
                not flag.tz.isLocked())

    flag_alone = pm.createNode('transform', name='records_on_itself')
    attr_utils.set_limits(flag_alone, limit_point=((-1, 1), (None, None), (None, None)))
    suite.check('with no network node the limits are recorded on the control itself',
                flag_alone.hasAttr('translateLimitX'))


def check_serialize(suite, pm):
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('transform', name='serialize_me')
    node.tx.set(4.5)

    data = attr_utils.serialize_attribute(node.tx)
    suite.check('a changed attribute is written down', bool(data), str(data))
    # This is the om/ bug seen from the other end: the type used to come out None, so
    # om_type_to_pymel_type turned it into None too.
    suite.check('and its type is the string addAttr takes',
                data.get('type') == 'doubleLinear', str(data))
    suite.check('and its value is there', data.get('value') == 4.5, str(data))
    suite.check('a limit that is not set is left out when optimising', 'min' not in data,
                str(data))

    node.addAttr('a_dial', type='double', min=0.0, max=10.0, defaultValue=1.0, keyable=True)
    node.a_dial.set(3.0)
    data = attr_utils.serialize_attribute(node.a_dial)
    suite.check('a limit that is set is written down', data.get('min') == 0.0, str(data))
    suite.check('both ends', data.get('max') == 10.0, str(data))
    suite.check('and the type', data.get('type') == 'double', str(data))

    unoptimized = attr_utils.serialize_attribute(node.a_dial, optimize=False)
    suite.check('without optimising, every limit key is present even when unset',
                {'min', 'max', 'softMin', 'softMax'} <= set(unoptimized),
                str(sorted(unoptimized)))


def check_what_was_dropped(suite):
    from mca.mya.utils import attr_utils

    for name in ('get_indices', 'lock_and_hide_object_attrs', 'create_message_compound_attr',
                 'get_enum_index'):
        suite.check('{} is gone - no callers anywhere'.format(name),
                    not hasattr(attr_utils, name))
    for public, private in (('reset_attrs_safe_check', '_can_reset'),
                            ('get_compound_attr_name_as_attribute', '_compound_attribute'),
                            ('disconnect_all_compound_attr_connections', '_disconnect_compound'),
                            ('add_limits_for_transform', '_add_limit_attribute')):
        suite.check('{} is private now, as {}'.format(public, private),
                    not hasattr(attr_utils, public) and hasattr(attr_utils, private))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_asking(suite, pm)
    check_locking(suite, pm)
    check_resetting(suite, pm)
    check_setting_data(suite, pm)
    check_compound_data(suite, pm)
    check_message_and_limits(suite, pm)
    check_serialize(suite, pm)
    check_what_was_dropped(suite)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('attr_utils', body))
