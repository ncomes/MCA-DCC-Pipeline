"""
The small wrappers the rest of the package leans on: maya_utils, plugins,
display_layers and constraint.

    mayapy tests/test_scene_basics.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_maya_utils(suite):
    import maya.cmds as cmds
    from mca.mya.utils import maya_utils

    version = maya_utils.get_version()
    suite.check('the Maya version reads as a four-digit year',
                2000 < version < 2100, str(version))
    suite.check('it agrees with cmds.about',
                str(version) in str(cmds.about(version=True)), str(version))
    suite.check('get_float_version is gone - it was here and in plugins, and unused',
                not hasattr(maya_utils, 'get_float_version'))
    suite.check('get_api_version is gone - no callers',
                not hasattr(maya_utils, 'get_api_version'))

    folder = maya_utils.maya_preferences_folder()
    suite.check('the preferences folder is made', os.path.isdir(folder), folder)
    suite.check('it is under the redirected preferences root, not the real one',
                os.environ['MCA_PREFS_ROOT'].replace('\\', '/').lower()
                in folder.replace('\\', '/').lower(), folder)
    prefs_file = maya_utils.get_default_preferences_file()
    suite.check('the defaults file sits in it',
                os.path.dirname(prefs_file) == folder, prefs_file)
    suite.check('and is named as it was', prefs_file.endswith('maya_default_options.prefs'))

    # -- delete_nodes_of_type ----------------------------------------------------------- #
    harness.new_scene()
    cmds.createNode('hyperView', name='doomed_view')
    cmds.createNode('hyperLayout', name='doomed_layout')
    deleted = maya_utils.delete_nodes_of_type('hyperView')
    suite.check('a node of the named type is deleted',
                not cmds.objExists('doomed_view'), str(deleted))
    suite.check('and reported', any('doomed_view' in one for one in deleted), str(deleted))
    suite.check('a node of another type is left', cmds.objExists('doomed_layout'))

    deleted = maya_utils.delete_nodes_of_type(['hyperLayout'])
    suite.check('a list of types works too', not cmds.objExists('doomed_layout'), str(deleted))

    # A locked node used to stop the whole pass; now it is unlocked first.
    harness.new_scene()
    node = cmds.createNode('hyperView', name='locked_view')
    cmds.lockNode(node, lock=True)
    maya_utils.delete_nodes_of_type('hyperView')
    suite.check('a locked node of the type is unlocked and deleted',
                not cmds.objExists('locked_view'))

    # The guard that could never fire: it compared a PyNode against a tuple of strings.
    harness.new_scene()
    cmds.createNode('hyperGraphLayout', name='hyperGraphLayout')
    maya_utils.delete_nodes_of_type('hyperGraphLayout')
    suite.check("Maya's own hyperGraphLayout is protected, which the old guard never managed",
                cmds.objExists('hyperGraphLayout'))
    suite.check('it is protected by name, not by identity',
                'hyperGraphLayout' in maya_utils.PROTECTED_NODE_NAMES)

    suite.check('the selection masks are still here',
                maya_utils.SelectionMasks.PolygonVertices == 31)


def check_plugins(suite):
    import maya.cmds as cmds
    from mca.mya.utils import plugins

    # objExport ships with every Maya and has no side effects worth worrying about.
    name = 'objExport'
    was_loaded = plugins.is_plugin_loaded(name)

    suite.check('a plugin Maya has never heard of answers False rather than raising',
                plugins.is_plugin_loaded('no_such_plugin_anywhere') is False)

    if was_loaded:
        plugins.unload_plugin(name)
    suite.check('loading a plugin says it worked', plugins.load_plugin(name) is True)
    suite.check('and it is loaded', plugins.is_plugin_loaded(name))
    suite.check('loading it again is fine', plugins.load_plugin(name) is True)
    suite.check('unloading says it worked', plugins.unload_plugin(name) is True)
    suite.check('and it is unloaded', not plugins.is_plugin_loaded(name))
    # The old version answered False here, so a caller could not tell "already unloaded"
    # from "would not unload".
    suite.check('unloading one that is not loaded answers True, because it is unloaded',
                plugins.unload_plugin(name) is True)
    suite.check('loading a plugin that does not exist answers False',
                plugins.load_plugin('no_such_plugin_anywhere') is False)
    if was_loaded:
        plugins.load_plugin(name)

    # -- the trusted-paths option variable ---------------------------------------------- #
    # The bug: optionVar answers 0 - the integer - for a variable never written, and the
    # next line did `path in 0`, which is a TypeError. That was every fresh Maya profile.
    #
    # Checked against a variable of our own, not SafeModeAllowedlistPaths. That one is
    # Maya's, and in a batch Maya it is read-only: it reports as existing, answers with an
    # empty list, refuses stringValueAppend and survives optionVar(remove=). So the real
    # call is a no-op in mayapy, and checking the logic against it would only ever be
    # checking that.
    real_variable = plugins.TRUSTED_PATHS_OPTION_VARIABLE
    variable = 'MCA_TEST_TRUSTED_PLUGIN_PATHS'
    plugins.TRUSTED_PATHS_OPTION_VARIABLE = variable
    try:
        cmds.optionVar(remove=variable)
        suite.check('the variable is unset to start with', not cmds.optionVar(exists=variable))
        suite.check('and Maya answers 0 for it, not an empty list - the whole bug',
                    cmds.optionVar(query=variable) == 0,
                    repr(cmds.optionVar(query=variable)))
        folder = os.path.join(os.environ['MCA_PREFS_ROOT'], 'trusted_plugins')
        suite.check('adding a trusted folder works with the variable unset',
                    plugins.add_trusted_plugin_location_path(folder) is True)
        listed = cmds.optionVar(query=variable) or []
        suite.check('and the folder is in it',
                    any(os.path.normpath(one) == os.path.normpath(folder) for one in listed),
                    str(listed))
        suite.check('adding it twice does not add it twice',
                    plugins.add_trusted_plugin_location_path(folder) is False)
        suite.check('the same folder spelled differently is still recognised',
                    plugins.add_trusted_plugin_location_path(folder + os.sep) is False)
        suite.check('there is still just the one entry',
                    len(cmds.optionVar(query=variable) or []) == 1,
                    str(cmds.optionVar(query=variable)))
        suite.check('an empty path is refused',
                    plugins.add_trusted_plugin_location_path('') is False)
    finally:
        cmds.optionVar(remove=variable)
        plugins.TRUSTED_PATHS_OPTION_VARIABLE = real_variable
    suite.check('the real variable name is the one Maya uses',
                plugins.TRUSTED_PATHS_OPTION_VARIABLE == 'SafeModeAllowedlistPaths')


def check_display_layers(suite):
    import maya.cmds as cmds
    import pymel.core as pm
    from mca.mya.utils import display_layers

    harness.new_scene()
    sphere = pm.polySphere(name='layered_sphere')[0]
    cube = pm.polyCube(name='layered_cube')[0]
    layer = pm.createDisplayLayer(name='test_layer', empty=True)
    pm.editDisplayLayerMembers(layer, sphere, cube, noRecurse=True)

    found = display_layers.get_display_layers([sphere, cube])
    suite.check('the layer is found once for two nodes on it, not twice - the old bug',
                found == [layer], str(found))
    suite.check('a node on no layer contributes nothing',
                display_layers.get_display_layers(pm.polyCone(name='free_cone')[0]) == [])
    suite.check('a single node, not in a list, works',
                display_layers.get_display_layers(sphere) == [layer])

    removed = display_layers.remove_objects_from_layers([sphere])
    suite.check('a node comes off its layer, and is reported', removed == [sphere], str(removed))
    suite.check('it is off the layer',
                sphere not in (pm.editDisplayLayerMembers(layer, query=True) or []))
    suite.check('the other node is still on it',
                display_layers.get_display_layers(cube) == [layer])
    suite.check('taking a node off no layers reports nothing',
                display_layers.remove_objects_from_layers([sphere]) == [])

    # -- delete_empty_display_layers ---------------------------------------------------- #
    harness.new_scene()
    keeper = pm.polySphere(name='kept_sphere')[0]
    full = pm.createDisplayLayer(name='full_layer', empty=True)
    pm.editDisplayLayerMembers(full, keeper, noRecurse=True)
    pm.createDisplayLayer(name='empty_layer_one', empty=True)
    pm.createDisplayLayer(name='empty_layer_two', empty=True)

    deleted = display_layers.delete_empty_display_layers()
    suite.check('both empty layers are deleted',
                not cmds.objExists('empty_layer_one') and
                not cmds.objExists('empty_layer_two'), str(deleted))
    suite.check('and reported', len(deleted) == 2, str(deleted))
    suite.check('a layer with something on it is kept', cmds.objExists('full_layer'))
    suite.check("Maya's own defaultLayer is never touched", cmds.objExists('defaultLayer'))


def check_constraint(suite):
    import maya.cmds as cmds
    import pymel.core as pm
    from mca.mya.utils import constraint

    harness.new_scene()
    driver = pm.createNode('transform', name='driver')
    driven = pm.createNode('transform', name='driven')

    free = constraint.constraint_safe_attrs(driven, 't')
    suite.check('a free transform can be driven on all three axes',
                free == ['none', 'none', 'none'], str(free))
    suite.check('the answer is always three long', len(free) == 3)

    driven.translateY.lock()
    locked = constraint.constraint_safe_attrs(driven, 't')
    suite.check('a locked axis is skipped',
                locked == ['none', 'y', 'none'], str(locked))
    driven.translateY.unlock()

    skipped = constraint.constraint_safe_attrs(driven, 't', skip_list=['x'])
    suite.check('an axis the caller named is skipped',
                skipped == ['x', 'none', 'none'], str(skipped))

    # The bug: settable, unlocked, but already driven by something that is not an anim
    # curve. The old code appended nothing, so the list came back two long and Maya read
    # the missing axis as free.
    other = pm.createNode('transform', name='other_driver')
    pm.connectAttr(other.translateZ, driven.translateZ)
    connected = constraint.constraint_safe_attrs(driven, 't')
    suite.check('an axis driven by a plain connection is skipped',
                connected == ['none', 'none', 'z'], str(connected))
    suite.check('and the answer is still three long, which is the whole point',
                len(connected) == 3, str(connected))
    pm.disconnectAttr(other.translateZ, driven.translateZ)

    # An anim curve is not a rival: a constraint is meant to replace it.
    cmds.setKeyframe(str(driven), attribute='translateX', time=1, value=0)
    keyed = constraint.constraint_safe_attrs(driven, 't')
    suite.check('a keyed axis is still free to constrain',
                keyed == ['none', 'none', 'none'], str(keyed))
    cmds.cutKey(str(driven), attribute='translateX', clear=True)

    # -- the four wrappers -------------------------------------------------------------- #
    harness.new_scene()
    driver = pm.createNode('transform', name='driver')
    driven = pm.createNode('transform', name='driven')
    made = constraint.parent_constraint_safe(driver, driven)
    suite.check('a parent constraint is made when the node is free', made is not None)
    suite.check('it is a parent constraint', isinstance(made, pm.nt.ParentConstraint))
    pm.delete(made)

    for axis in ('X', 'Y', 'Z'):
        driven.attr('translate{}'.format(axis)).lock()
        driven.attr('rotate{}'.format(axis)).lock()
    suite.check('nothing is made when every axis is locked',
                constraint.parent_constraint_safe(driver, driven) is None)
    for axis in ('X', 'Y', 'Z'):
        driven.attr('translate{}'.format(axis)).unlock()
        driven.attr('rotate{}'.format(axis)).unlock()

    suite.check('a missing source is refused',
                constraint.parent_constraint_safe(None, driven) is None)
    suite.check('a missing driven node is refused',
                constraint.parent_constraint_safe(driver, None) is None)

    for maker, kind in ((constraint.point_constraint_safe, pm.nt.PointConstraint),
                        (constraint.orient_constraint_safe, pm.nt.OrientConstraint),
                        (constraint.scale_constraint_safe, pm.nt.ScaleConstraint)):
        made = maker(driver, driven)
        suite.check('{} is made'.format(kind.__name__), isinstance(made, kind))
        pm.delete(made)

    # -- get_constraint_targets --------------------------------------------------------- #
    # The bug: joints were filtered out, and the pipeline's animation controls are joints.
    harness.new_scene()
    joint_driver = pm.createNode('joint', name='joint_driver')
    transform_driver = pm.createNode('transform', name='transform_driver')
    driven = pm.createNode('transform', name='driven')
    made = pm.parentConstraint(joint_driver, transform_driver, driven, maintainOffset=False)

    targets = constraint.get_constraint_targets(made)
    suite.check('a joint driving a constraint is found', joint_driver in targets, str(targets))
    suite.check('a transform driving it is found too', transform_driver in targets, str(targets))
    suite.check('both, and nothing else', len(targets) == 2, str(targets))
    suite.check('the constraint node itself is not listed as driving itself',
                made not in targets, str(targets))
    suite.check('in the order the constraint holds them',
                targets == [joint_driver, transform_driver], str(targets))
    # Twice, to show the order does not wander the way list(set(...)) did.
    suite.check('and the same order when asked again',
                constraint.get_constraint_targets(made) == targets)


def body(suite):
    harness.add_sibling_packages()
    check_maya_utils(suite)
    check_plugins(suite)
    check_display_layers(suite)
    check_constraint(suite)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('scene_basics', body))
