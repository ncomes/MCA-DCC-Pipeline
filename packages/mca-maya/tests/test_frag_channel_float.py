"""
Extra channels on a control, mirrored onto a joint for the exporter - in a real Maya.

    mayapy tests/test_frag_channel_float.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _scene(pm, modules, namespace_name=None):
    """A fresh scene with a skeleton, a rig, a control and a joint to mirror onto."""

    import maya.cmds as cmds

    harness.new_scene()
    if namespace_name:
        if not cmds.namespace(exists=namespace_name):
            cmds.namespace(add=namespace_name)
        cmds.namespace(set=':{0}'.format(namespace_name))
    cmds.select(clear=True)
    joints = [pm.PyNode(cmds.joint(name=name, position=(index * 5, 0, 0), absolute=True))
              for index, name in enumerate(['root', 'b_visor'])]
    control = pm.spaceLocator(name='f_visor')
    cmds.namespace(set=':')

    root_node = modules['frag_root'].FRAGRoot.create(joints[0], 'player', 'channel_asset')
    rig = modules['frag_rig'].FRAGRig.create(root_node)
    return joints, rig, control


def _channels(modules):
    """Two channel descriptions, one of them non-default in every field."""

    create_dict = modules['channel_float_component'].create_channel_float_dict
    return [create_dict('openClose', 'openClose', attr_min=0.0, attr_max=4.0, default_value=0.25),
            create_dict('wetness', 'wetnessProxy', attr_min=-1.0, attr_max=1.0,
                        default_value=0.0, keyable=False)]


def check_creating(suite, pm, modules):
    channel_float_component = modules['channel_float_component']

    joints, rig, control = _scene(pm, modules)
    channel_dicts = _channels(modules)
    component = channel_float_component.ChannelFloatComponent.create(
        rig, control, joints[1], channel_dicts, 'visor')

    suite.check('a channel component is built', component is not None)
    suite.check('named for what it holds rather than for a side of the body',
                str(component.pynode).endswith('ChannelFloatComponent_center_visor'),
                str(component.pynode))
    suite.check('it remembers the control the channels are on',
                component.channel_object == control, str(component.channel_object))
    suite.check('and the joint carrying the copies the exporter reads',
                component.channel_joint == joints[1], str(component.channel_joint))

    suite.check('each channel is on the control', control.hasAttr('openClose')
                and control.hasAttr('wetness'))
    suite.check('with the limits and default it was given',
                pm.addAttr(control.attr('openClose'), q=True, min=True) == 0.0
                and pm.addAttr(control.attr('openClose'), q=True, max=True) == 4.0
                and pm.addAttr(control.attr('openClose'), q=True, defaultValue=True) == 0.25,
                str([pm.addAttr(control.attr('openClose'), q=True, min=True),
                     pm.addAttr(control.attr('openClose'), q=True, max=True),
                     pm.addAttr(control.attr('openClose'), q=True, defaultValue=True)]))
    suite.check('and keyable only where it was asked for',
                control.attr('openClose').isKeyable()
                and not control.attr('wetness').isKeyable())

    suite.check('each channel has a copy on the joint, under the name it was given',
                joints[1].hasAttr('openClose') and joints[1].hasAttr('wetnessProxy'))
    suite.check('the copy is a proxy attribute, which is what makes the exporter carry it',
                pm.addAttr(joints[1].attr('openClose'), q=True, usedAsProxy=True) is True,
                str(pm.addAttr(joints[1].attr('openClose'), q=True, usedAsProxy=True)))
    suite.check('and the control drives it',
                control.attr('openClose') in joints[1].attr('openClose').listConnections(
                    plugs=True, source=True, destination=False))
    control.attr('openClose').set(3.0)
    suite.check('so setting the channel on the control sets it on the joint',
                abs(joints[1].attr('openClose').get() - 3.0) < 0.001,
                str(joints[1].attr('openClose').get()))

    # The attribute the control carries to say which component its channels belong to.
    suite.check('the control is wired to the component through its own attribute, not fragParent - '
                'which already points at the component that built the control',
                component.pynode in control.attr(
                    channel_float_component.OBJECT_PARENT_ATTR).listConnections(),
                str(control.attr(channel_float_component.OBJECT_PARENT_ATTR).listConnections()))
    suite.check('and that attribute is not fragParent',
                channel_float_component.OBJECT_PARENT_ATTR
                != modules['frag_base'].FRAG_PARENT_ATTR)

    # The bug: each value was read with channel.pop(), so the caller's dictionaries came back empty.
    suite.check('the channel descriptions it was handed are still intact afterwards',
                all(len(channel) == 6 for channel in channel_dicts),
                str(channel_dicts))
    suite.check('so the same descriptions can be used again',
                channel_float_component.ChannelFloatComponent.create(
                    rig, pm.spaceLocator(name='f_visor_two'), joints[1], channel_dicts,
                    'visor_two') is not None)

    build_kwargs = component.get_build_kwargs()
    parameters = _parameters_of(channel_float_component.ChannelFloatComponent.create)
    suite.check('every build argument a rebuild needs is a parameter of create',
                set(build_kwargs) <= parameters, str(sorted(set(build_kwargs) - parameters)))


def check_the_round_trip(suite, pm, modules):
    channel_float_component = modules['channel_float_component']

    joints, rig, control = _scene(pm, modules)
    channel_dicts = _channels(modules)
    component = channel_float_component.ChannelFloatComponent.create(
        rig, control, joints[1], channel_dicts, 'visor')

    # The bug: the channel list is deliberately not recorded, and nothing could read it back - so a
    # rebuild had nothing to go on. The channels are all in the scene.
    found = component.get_channel_dicts()
    suite.check('every channel comes back', len(found) == 2, str(found))
    suite.check('in the shape create takes them',
                sorted(found[0]) == sorted(channel_dicts[0]), str(sorted(found[0])))
    by_name = {channel['obj_attr_name']: channel for channel in found}
    suite.check('with the name on the control and the name on the joint',
                by_name['wetness']['joint_attr_name'] == 'wetnessProxy', str(by_name['wetness']))
    suite.check('the limits',
                by_name['openClose']['min'] == 0.0 and by_name['openClose']['max'] == 4.0,
                str(by_name['openClose']))
    suite.check('the default', by_name['openClose']['default_value'] == 0.25,
                str(by_name['openClose']['default_value']))
    suite.check('and whether it is keyable',
                by_name['openClose']['keyable'] is True
                and by_name['wetness']['keyable'] is False, str(by_name))

    # The round trip: what it answers builds the same channels somewhere else.
    other_control = pm.spaceLocator(name='f_visor_two')
    import maya.cmds as cmds
    cmds.select(clear=True)
    other_joint = pm.PyNode(cmds.joint(name='b_visor_two'))
    rebuilt = channel_float_component.ChannelFloatComponent.create(
        rig, other_control, other_joint, found, 'visor_two')
    suite.check('handing what it answers back to create builds the same channels again',
                {channel['obj_attr_name']: channel['max']
                 for channel in rebuilt.get_channel_dicts()}
                == {channel['obj_attr_name']: channel['max'] for channel in found},
                str(rebuilt.get_channel_dicts()))


def check_adding_and_removing(suite, pm, modules):
    channel_float_component = modules['channel_float_component']
    create_dict = channel_float_component.create_channel_float_dict

    joints, rig, control = _scene(pm, modules)
    component = channel_float_component.ChannelFloatComponent.create(
        rig, control, joints[1], _channels(modules), 'visor')

    # The file carried a comment saying these were still outstanding.
    added = component.add_channels(create_dict('glow', 'glow', attr_max=10.0))
    suite.check('a channel can be added to a component that already exists', added == ['glow'],
                str(added))
    suite.check('it is on both nodes', control.hasAttr('glow') and joints[1].hasAttr('glow'))
    suite.check('and the component now has three', len(component.get_channel_dicts()) == 3,
                str(component.get_channel_dicts()))

    suite.check('adding a channel that is already there uses it rather than failing',
                component.add_channels(create_dict('glow', 'glow')) == ['glow'])
    suite.check('and does not add a second copy', len(component.get_channel_dicts()) == 3,
                str(component.get_channel_dicts()))

    suite.check('a channel can be removed', component.remove_channel('wetness'))
    suite.check('off the control', not control.hasAttr('wetness'))
    # Removed by following the connection, which is what makes a channel whose two names differ
    # removable at all.
    suite.check('and off the joint, under whatever name its copy had',
                not joints[1].hasAttr('wetnessProxy'))
    suite.check('leaving the others alone', len(component.get_channel_dicts()) == 2,
                str(component.get_channel_dicts()))
    suite.check('removing one that is not there says so rather than raising',
                component.remove_channel('wetness') is False)

    # A description with keys missing takes the same defaults create_channel_float_dict uses,
    # rather than being a bare KeyError from inside a pop.
    suite.check('a channel description with only its two names works',
                component.add_channels({'obj_attr_name': 'sparse',
                                        'joint_attr_name': 'sparse'}) == ['sparse'])
    sparse = [channel for channel in component.get_channel_dicts()
              if channel['obj_attr_name'] == 'sparse'][0]
    suite.check('and takes the documented defaults',
                sparse['min'] == channel_float_component.CHANNEL_DEFAULTS['min']
                and sparse['max'] == channel_float_component.CHANNEL_DEFAULTS['max'],
                str(sparse))
    suite.check('a channel description with no name at all is skipped rather than raising',
                component.add_channels({'obj_attr_name': '', 'joint_attr_name': ''}) == [])

    # An attribute that is already on the node can be handed over instead of a name.
    control.addAttr('already', at='float', k=True)
    joints[1].addAttr('already', at='float', k=True)
    suite.check('an attribute that already exists can be handed over in place of a name',
                component.add_channels(create_dict(control.attr('already'),
                                                   joints[1].attr('already'))) == ['already'])
    suite.check('and it is wired up',
                control.attr('already') in joints[1].attr('already').listConnections(
                    plugs=True, source=True, destination=False))


def check_the_migration(suite, pm, modules):
    channel_float_component = modules['channel_float_component']

    joints, rig, control = _scene(pm, modules)
    component = channel_float_component.ChannelFloatComponent.create(
        rig, control, joints[1], _channels(modules), 'visor')

    suite.check('a component is built at its class\'s version',
                int(component.get_version())
                == int(channel_float_component.ChannelFloatComponent.VERSION))

    # Put it back the way version 1 left it: the two attributes under their capitalised names.
    connected = {}
    legacy_names = channel_float_component.ChannelFloatComponent.LEGACY_ATTR_NAMES
    for legacy_name, attr_name in legacy_names.items():
        connected[legacy_name] = component.pynode.attr(attr_name).get()
        pm.renameAttr(component.pynode.attr(attr_name), legacy_name)
    component.set_version(1)

    suite.check('a version 1 component is recognised as out of date',
                int(component.get_version())
                < int(channel_float_component.ChannelFloatComponent.VERSION))
    component.update()

    suite.check('updating it brings it to the current version',
                int(component.get_version())
                == int(channel_float_component.ChannelFloatComponent.VERSION),
                str(component.get_version()))
    suite.check('the capitalised attributes are gone',
                not any(component.pynode.hasAttr(name) for name in legacy_names))
    suite.check('each one is there under its camelCase name',
                all(component.pynode.hasAttr(name) for name in legacy_names.values()))
    suite.check('and still wired to what it was wired to - the step renames rather than rewires',
                all(component.pynode.attr(legacy_names[legacy_name]).get() == node
                    for legacy_name, node in connected.items()),
                str(connected))
    suite.check('so the component can still find its control and its joint',
                component.channel_object == control and component.channel_joint == joints[1])

    component.update()
    suite.check('updating an up-to-date component does nothing',
                int(component.get_version())
                == int(channel_float_component.ChannelFloatComponent.VERSION))


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
    channel_float_component = modules['channel_float_component']
    frag_base = modules['frag_base']

    joints, rig, control = _scene(pm, modules, namespace_name='hero')
    cmds.namespace(set=':hero')
    component = channel_float_component.ChannelFloatComponent.create(
        rig, control, joints[1], _channels(modules), 'visor')
    suite.check('a channel component builds while the active namespace is already the rig\'s',
                component is not None)
    suite.check('and it lands in that namespace',
                component.pynode.namespace() == 'hero:', str(component.pynode.namespace()))
    suite.check('with the active namespace put back afterwards',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':hero',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True))
    cmds.namespace(set=':')

    suite.check('read back out of a scene it comes back as its own class',
                type(frag_base.FRAGNode(component.pynode))
                is channel_float_component.ChannelFloatComponent,
                str(type(frag_base.FRAGNode(component.pynode))))
    suite.check('ChannelFloatComponent is in the registry',
                'ChannelFloatComponent' in frag_base.FRAGNodeRegister.__frag_node_types__)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import channel_float_component
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root

    modules = {'channel_float_component': channel_float_component, 'frag_base': frag_base,
               'frag_rig': frag_rig, 'frag_root': frag_root}

    check_creating(suite, pm, modules)
    check_the_round_trip(suite, pm, modules)
    check_adding_and_removing(suite, pm, modules)
    check_the_migration(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_channel_float', body))
