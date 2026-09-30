"""
Rebuilding attributes from data, and telling whether a node is empty:
mca.mya.utils.node_util. Plus ma_fileio and textures.

    mayapy tests/test_node_util.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_is_empty(suite, pm):
    from mca.mya.utils import node_util

    harness.new_scene()
    bare = pm.createNode('transform', name='holds_nothing')
    suite.check('a fresh transform is empty', node_util.is_empty(bare) is True)

    parent = pm.createNode('transform', name='has_a_child')
    pm.createNode('transform', name='the_child').setParent(parent)
    suite.check('a transform with a child is not empty', node_util.is_empty(parent) is False)

    marked = pm.createNode('transform', name='has_an_attribute')
    marked.addAttr('mcaSomething', type='bool', keyable=True)
    suite.check('a node with an attribute somebody added is not empty',
                node_util.is_empty(marked) is False)
    suite.check('unless the caller says attributes do not count',
                node_util.is_empty(marked, no_user_attributes=False) is True)

    wired = pm.createNode('transform', name='is_connected')
    driver = pm.createNode('transform', name='its_driver')
    pm.connectAttr(driver.translateX, wired.translateX)
    suite.check('a connected node is not empty', node_util.is_empty(wired) is False)
    suite.check('unless the caller says connections do not count',
                node_util.is_empty(wired, no_connections=False) is True)

    # The bug: `if node in default_nodes` compared a PyNode against a list of strings, which is
    # never equal, so Maya's own nodes were not protected at all - and scene_utils uses this to
    # decide what to delete.
    for name in ('initialShadingGroup', 'defaultLightSet'):
        if pm.objExists(name):
            suite.check("Maya's own {} is never empty".format(name),
                        node_util.is_empty(pm.PyNode(name)) is False)
    suite.check('the protected names are compared as names',
                'initialShadingGroup' in node_util.DEFAULT_NODE_NAMES)


def check_create_or_find(suite, pm):
    from mca.mya.utils import node_util

    harness.new_scene()
    made = node_util.create_or_find('a_remap', pm.nt.RemapValue)
    suite.check('a node that is not there is made', pm.objExists('a_remap'))
    suite.check('and is of the type asked for', isinstance(made, pm.nt.RemapValue))
    found = node_util.create_or_find('a_remap', pm.nt.RemapValue)
    suite.check('asking again finds the one that is there', found == made)
    suite.check('and does not make a second',
                len(pm.ls('a_remap', type=pm.nt.RemapValue)) == 1)
    other = node_util.create_or_find('a_remap', pm.nt.Reverse)
    suite.check('a different type of the same name is a different node', other != made)


def check_add_attribute(suite, pm):
    from mca.mya.utils import node_util
    from mca.mya.utils import attr_utils

    harness.new_scene()
    node = pm.createNode('transform', name='rebuilt')

    attribute = node_util.add_attribute(node, name='a_number', type='double', value=2.5,
                                        min=0.0, max=10.0, keyable=True, channelBox=True)
    suite.check('a double is made', node.hasAttr('a_number'))
    suite.check('with its value', attribute.get() == 2.5)
    suite.check('its lower limit', attribute.getMin() == 0.0)
    suite.check('its upper limit', attribute.getMax() == 10.0)
    suite.check('and keyable', attribute.isKeyable())

    # The bug: `if default is not None: pass`, followed by eight commented-out lines. The
    # docstring and the data format both describe a default; nothing was ever done with it.
    defaulted = node_util.add_attribute(node, name='a_dial', type='double', default=0.75,
                                        keyable=True)
    suite.check('a default is set - it used to be thrown away',
                pm.addAttr(defaulted, query=True, defaultValue=True) == 0.75,
                str(pm.addAttr(defaulted, query=True, defaultValue=True)))

    locked = node_util.add_attribute(node, name='a_locked_one', type='double', value=1.0,
                                     locked=True)
    suite.check('a locked attribute is made locked', locked.isLocked())

    node_util.add_attribute(node, name='a_label', type='string', value='written')
    suite.check('a string attribute takes its value', node.a_label.get() == 'written')

    # The type may be one of the pipeline's own numbers.
    from mca.mya.utils.om import attributetypes
    numbered = node_util.add_attribute(node, name='by_number',
                                       type=attributetypes.kMFnNumericBoolean, value=True)
    suite.check('a type given as one of our own numbers works',
                numbered.type() == 'bool', numbered.type())

    # 'complex' is a dictionary kept as JSON in a string.
    complex_attr = node_util.add_attribute(node, name='a_mapping', type='complex',
                                           value={'a': 1, 'b': [2, 3]})
    suite.check('a complex attribute is a string', complex_attr.type() == 'string')
    import json
    suite.check('holding the dictionary as JSON',
                json.loads(complex_attr.get()) == {'a': 1, 'b': [2, 3]},
                complex_attr.get())

    # The bug: enumName was built with list(set(...)), which has no order, so an attribute
    # rebuilt from data had its choices shuffled - and every index stored against it then meant
    # something else.
    choice = node_util.add_attribute(node, name='a_choice', type='enum',
                                     enums=['low', 'medium', 'high'], keyable=True)
    from mca.mya.utils.om import om_plug
    names = om_plug.get_enum_names(om_plug.as_mplug('rebuilt.a_choice'))
    suite.check('an enumeration keeps the order it was given - the whole bug',
                names == ['low', 'medium', 'high'], str(names))
    suite.check('and each name once',
                len(names) == len(set(names)), str(names))

    # Adding one that is already there sets it up rather than raising.
    again = node_util.add_attribute(node, name='a_number', type='double', value=7.0)
    suite.check('adding an attribute that is there sets it instead', again.get() == 7.0)
    suite.raises('unless the caller asked to be told', node_util.add_attribute, node,
                 name='a_number', type='double', raise_exceptions=True)
    suite.raises('an attribute with no name is refused', node_util.add_attribute, node,
                 type='double')

    # -- the compound, which could never be built --------------------------------------- #
    # The bug: add_attribute handed compounds to attr_utils.add_compound_attribute, and there
    # is no such function anywhere in the pipeline. skel_utils rebuilds a skeleton's user
    # attributes from serialized data and passes children straight through, so any skeleton
    # with a compound user attribute could not be rebuilt.
    harness.new_scene()
    node = pm.createNode('transform', name='compound_rebuild')
    compound = node_util.add_attribute(node, name='a_block', type='compound', children=[
        {'name': 'first', 'type': 'double', 'value': 1.0, 'keyable': True},
        {'name': 'second', 'type': 'double', 'value': 2.0, 'keyable': True},
        {'name': 'third', 'type': 'string', 'value': 'three'},
    ])
    suite.check('a compound attribute is built', node.hasAttr('a_block'))
    suite.check('and is a compound', compound.isCompound())
    suite.check('with the right number of children', compound.numChildren() == 3,
                str(compound.numChildren()))
    suite.check('the first child has its value', node.first.get() == 1.0)
    suite.check('the second too', node.second.get() == 2.0)
    suite.check('and a child of another type', node.third.get() == 'three')
    suite.raises('a compound described with no children at all is refused',
                 node_util.add_attribute, node, name='empty_block', type='compound',
                 children=[{}])

    # Round trip: serialize a real attribute and build it again on another node.
    harness.new_scene()
    source = pm.createNode('transform', name='the_original')
    source.addAttr('a_setting', type='double', min=-1.0, max=1.0, defaultValue=0.25,
                   keyable=True)
    source.a_setting.set(0.5)
    data = attr_utils.serialize_attribute(source.a_setting)

    target = pm.createNode('transform', name='the_copy')
    rebuilt = node_util.add_attribute(target, **data)
    suite.check('an attribute written down and built again keeps its value',
                rebuilt.get() == 0.5, str(rebuilt.get()))
    suite.check('its limits', rebuilt.getMin() == -1.0 and rebuilt.getMax() == 1.0)
    suite.check('its type', rebuilt.type() == 'double', rebuilt.type())
    suite.check('and its default',
                pm.addAttr(rebuilt, query=True, defaultValue=True) == 0.25,
                str(pm.addAttr(rebuilt, query=True, defaultValue=True)))

    for name in ('match_translation', 'match_rotation', 'reset_transform', 'rbf_retarget',
                 'center_obj', 'orient_obj_to_obj'):
        suite.check('{} is gone - no callers'.format(name), not hasattr(node_util, name))
    suite.check('set_attribute_info_from_dict is private now',
                not hasattr(node_util, 'set_attribute_info_from_dict') and
                hasattr(node_util, '_set_attribute_info'))


def check_ma_fileio(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import ma_fileio
    from mca.common import sourcecontrol

    harness.new_scene()
    suite.check('an unsaved scene has no path', ma_fileio.current_scene_path() == '')
    suite.check('and cannot be checked out, but says so rather than raising',
                ma_fileio.checkout_current_scene() is False)

    # Save into the suite's temp folder, then check it out through whichever backend is in use.
    # With no source control configured that is NoSourceControl, which succeeds and does
    # nothing - which is the right answer for a machine with no Perforce.
    scene_path = os.path.join(suite.temp, 'a_scene.ma').replace('\\', '/')
    cmds.file(rename=scene_path)
    cmds.file(save=True, type='mayaAscii')
    suite.check('a saved scene has a path',
                ma_fileio.current_scene_path().replace('\\', '/') == scene_path,
                ma_fileio.current_scene_path())

    # Pinned to the do-nothing backend. This machine has Perforce, and a file in a temp folder
    # is not in anybody's workspace, so leaving the choice to autodetection would be checking
    # what Perforce says about a path it has never heard of.
    sourcecontrol.use('none')
    try:
        suite.check('checking the scene out answers True with no source control to consult',
                    ma_fileio.checkout_current_scene() is True)
        suite.check('and the file is writable afterwards', os.access(scene_path, os.W_OK))
        suite.check('making it writable without checking out works too',
                    ma_fileio.checkout_current_scene(checkout=False) is True)
    finally:
        sourcecontrol.reset()
    harness.new_scene()


def check_textures(suite, pm):
    from mca.mya.utils import textures

    harness.new_scene()
    sphere = pm.polySphere(name='overlaid')[0]
    shader = pm.shadingNode('blinn', asShader=True, name='a_blinn')
    shading_engine = pm.sets(renderable=True, noSurfaceShader=True, empty=True,
                             name='a_blinnSG')
    shader.outColor >> shading_engine.surfaceShader
    pm.sets(shading_engine, edit=True, forceElement=sphere)
    shader.color.set((0.2, 0.4, 0.6))
    original_colour = [round(one, 3) for one in shader.color.get()]

    image = os.path.join(suite.temp, 'overlay.png').replace('\\', '/')
    open(image, 'wb').close()

    made = textures.add_overlay_textures(sphere, image)
    suite.check('an overlay is made', len(made) == 1, str(made))
    layered = made[0]
    suite.check('it is a layered texture', isinstance(layered, pm.nt.LayeredTexture))
    suite.check('and it is what drives the shader now',
                shader.color.listConnections(source=True, destination=False) == [layered])
    suite.check('it is tagged so it can be found again', layered.hasAttr(textures.OVERLAY_TAG))
    suite.check("the shader's flat colour was turned into a node behind it",
                any(one.hasAttr(textures.BASE_TAG) for one in
                    layered.attr('inputs')[textures.ORIGINAL_INPUT].color.listConnections()))
    suite.check('the empty first input is removed, so it does not render black',
                0 not in (layered.attr('inputs').getArrayIndices() or []),
                str(layered.attr('inputs').getArrayIndices()))

    suite.check('overlaying the same mesh twice does not stack a second one',
                textures.add_overlay_textures(sphere, image) == [])

    # The overlays are found through attr_utils.get_all_objects_with_attr, which used to search
    # in namespaces that do not exist - so this found nothing for any mesh in a namespace,
    # which is every referenced asset.
    removed = textures.remove_overlay_textures()
    suite.check('the overlay is removed', removed == 1, str(removed))
    suite.check('and the layered texture is gone', not pm.objExists(layered))
    suite.check("the shader's colour is back to what it was",
                [round(one, 3) for one in shader.color.get()] == original_colour,
                '{} vs {}'.format(shader.color.get(), original_colour))
    suite.check('and the stand-in node made for the flat colour is gone with it',
                not pm.ls(type='checker'), str(pm.ls(type='checker')))
    suite.check('nothing left to remove answers zero',
                textures.remove_overlay_textures() == 0)

    # A mesh in a namespace - the case that never worked.
    import maya.cmds as cmds
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='hero')
    cmds.namespace(setNamespace=':hero')
    sphere = pm.polySphere(name='in_a_namespace')[0]
    shader = pm.shadingNode('blinn', asShader=True, name='ns_blinn')
    shading_engine = pm.sets(renderable=True, noSurfaceShader=True, empty=True, name='ns_SG')
    shader.outColor >> shading_engine.surfaceShader
    pm.sets(shading_engine, edit=True, forceElement=sphere)
    cmds.namespace(setNamespace=':')

    textures.add_overlay_textures(sphere, image)
    suite.check('an overlay on a mesh in a namespace can be removed again - the whole bug',
                textures.remove_overlay_textures() == 1)

    # A mesh with nothing shading it, and one with no shape.
    harness.new_scene()
    empty_transform = pm.createNode('transform', name='no_shape')
    suite.check('a transform with no shape is skipped rather than raising',
                textures.add_overlay_textures(empty_transform, image) == [])


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_is_empty(suite, pm)
    check_create_or_find(suite, pm)
    check_add_attribute(suite, pm)
    check_ma_fileio(suite, pm)
    check_textures(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('node_util', body))
