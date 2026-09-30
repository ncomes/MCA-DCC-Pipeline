"""
Frame ranges and FBX: mca.mya.animation.time_utils and mca.mya.utils.fbx_utils.

The FBX half does a real round trip through Maya's FBX plugin - written, read back, checked.

    mayapy tests/test_fbx_and_time.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_time_utils(suite, pm):
    import maya.cmds as cmds
    from mca.mya.animation import time_utils

    harness.new_scene()
    cmds.playbackOptions(edit=True, animationStartTime=1, animationEndTime=48,
                         minTime=5, maxTime=20)

    suite.check('the visible range reads back', time_utils.get_visible_range() == (5.0, 20.0),
                str(time_utils.get_visible_range()))
    suite.check("the scene's own range reads back",
                time_utils.get_scene_range() == (1.0, 48.0), str(time_utils.get_scene_range()))
    suite.check('the current frame reads back',
                time_utils.get_current_time() == cmds.currentTime(query=True))

    # -- keys ---------------------------------------------------------------------------- #
    suite.check('a scene with no keys has no first keyframe',
                time_utils.get_scene_first_keyframe() is None)
    suite.check('and no last one', time_utils.get_scene_last_keyframe() is None)
    suite.check('and no keyframe range',
                time_utils.get_keyframe_range_from_scene() == (None, None))

    node = pm.createNode('transform', name='keyed_thing')
    cmds.setKeyframe(str(node), attribute='translateX', time=12, value=0)
    cmds.setKeyframe(str(node), attribute='translateX', time=36, value=10)
    suite.check('the first keyframe is found', time_utils.get_scene_first_keyframe() == 12.0)
    suite.check('the last one too', time_utils.get_scene_last_keyframe() == 36.0)
    suite.check('and the range together',
                time_utils.get_keyframe_range_from_scene() == (12.0, 36.0))

    # The bug: this read its keys only `if isinstance(node_list, list)`, so one node came back as
    # (None, None) whatever keys it had.
    suite.check('a single node, not in a list, gives up its keys',
                time_utils.get_keyframe_range_from_nodes(node) == (12.0, 36.0),
                str(time_utils.get_keyframe_range_from_nodes(node)))
    suite.check('a list works too',
                time_utils.get_keyframe_range_from_nodes([node]) == (12.0, 36.0))
    suite.check('a tuple as well',
                time_utils.get_keyframe_range_from_nodes((node,)) == (12.0, 36.0))
    unkeyed = pm.createNode('transform', name='not_keyed')
    suite.check('a node with no keys answers a pair of Nones',
                time_utils.get_keyframe_range_from_nodes(unkeyed) == (None, None))
    suite.check('and nothing at all does too',
                time_utils.get_keyframe_range_from_nodes(None) == (None, None))

    # -- get_times ----------------------------------------------------------------------- #
    # In a batch Maya there is no timeline to drag, so step 1 never answers and this falls
    # through to the keys.
    suite.check('no timeline selection in a batch Maya',
                time_utils.get_selected_range_from_timeline() == (None, None))
    suite.check("the range comes from the scene's keys",
                time_utils.get_times() == (12.0, 36.0), str(time_utils.get_times()))
    suite.check('or from the nodes given, when they are the ones with keys',
                time_utils.get_times(node_list=[node]) == (12.0, 36.0))

    cmds.cutKey(str(node), attribute='translateX', clear=True)
    widest = time_utils.get_times()
    suite.check('with no keys at all it falls back to the widest of the two ranges',
                widest == (1.0, 48.0), str(widest))

    # -- setting -------------------------------------------------------------------------- #
    time_utils.set_timeline_range(10, 30)
    suite.check('setting the visible range sets it',
                time_utils.get_visible_range() == (10.0, 30.0))
    suite.check("and the scene's range follows when it is not given separately",
                time_utils.get_scene_range() == (10.0, 30.0))

    # The bug: `if not scene_start_time`, and 0 is falsy, so a scene meant to start at zero got
    # the visible range's start instead.
    time_utils.set_timeline_range(5, 30, scene_start_time=0, scene_end_time=40)
    suite.check('a scene start of zero is honoured rather than read as "not given"',
                time_utils.get_scene_start_time() == 0.0,
                str(time_utils.get_scene_start_time()))
    suite.check('and the rest with it',
                time_utils.get_scene_end_time() == 40.0 and
                time_utils.get_visible_range() == (5.0, 30.0))

    # -- reframe -------------------------------------------------------------------------- #
    harness.new_scene()
    reframed = time_utils.reframe_visible_range()
    suite.check('a scene with no keys is reframed to the default range',
                reframed == time_utils.DEFAULT_RANGE, str(reframed))
    node = pm.createNode('transform', name='reframe_me')
    cmds.setKeyframe(str(node), attribute='translateY', time=7, value=0)
    cmds.setKeyframe(str(node), attribute='translateY', time=19, value=1)
    reframed = time_utils.reframe_visible_range()
    suite.check('a keyed scene is reframed to its keys', reframed == (7, 19), str(reframed))
    suite.check('and the timeline follows',
                time_utils.get_visible_range() == (7.0, 19.0))

    # -- set_padded_keys ------------------------------------------------------------------ #
    harness.new_scene()
    node = pm.createNode('transform', name='triggered')
    node.addAttr('a_trigger', type='double', keyable=True)
    time_utils.set_padded_keys(node.a_trigger, 20, 1.0)
    keyed = sorted(pm.keyframe(node.a_trigger, query=True) or [])
    suite.check('a padded key is keyed on three frames', keyed == [19.0, 20.0, 21.0], str(keyed))
    cmds.currentTime(20)
    suite.check('the value is on the frame asked for', node.a_trigger.get() == 1.0)
    cmds.currentTime(19)
    suite.check('and zero the frame before', node.a_trigger.get() == 0.0)
    cmds.currentTime(21)
    suite.check('and the frame after', node.a_trigger.get() == 0.0)

    # -- the module imports nothing it does not need ------------------------------------- #
    # The bug: two lines at module level loaded a plugin and imported a piece of Maya's
    # interface, so every importer of this module paid for both.
    source = open(time_utils.__file__.replace('.pyc', '.py'), encoding='utf-8').read()
    top_level = [line for line in source.splitlines()
                 if line and not line.startswith((' ', '\t', '#', '"'))]
    suite.check('the bookmark plugin is not loaded when this module is imported',
                not any('load_plugin' in line for line in top_level), str(top_level[:40]))
    suite.check("and Maya's bookmark interface is not imported at module level",
                not any('timeSliderBookmark import' in line for line in top_level))


def check_fbx(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import fbx_utils, plugins

    if not plugins.load_plugin('fbxmaya'):
        suite.note('fbx', 'the fbxmaya plugin would not load')
        suite.check('the fbxmaya plugin is needed for the rest of this suite', False,
                    'it would not load')
        return

    suite.check('the fbxmaya plugin is loaded', plugins.is_plugin_loaded('fbxmaya'))

    # -- the MEL builder ----------------------------------------------------------------- #
    # The bug: booleans were converted by running str.replace over the whole finished command,
    # arguments included, so a clip named TrueGrit was written as trueGrit.
    suite.check('a bool becomes MEL true', fbx_utils._as_mel(True) == 'true')
    suite.check('and false', fbx_utils._as_mel(False) == 'false')
    suite.check('a string is quoted', fbx_utils._as_mel('hello') == '"hello"')
    suite.check("a string holding 'True' is left alone - the whole bug",
                fbx_utils._as_mel('TrueGrit') == '"TrueGrit"', fbx_utils._as_mel('TrueGrit'))
    suite.check('a number is itself', fbx_utils._as_mel(12) == '12')

    # -- a real round trip ---------------------------------------------------------------- #
    harness.new_scene()
    sphere = pm.polySphere(name='exported_sphere')[0]
    sphere.t.set(1, 2, 3)
    fbx_path = os.path.join(suite.temp, 'round_trip.fbx').replace('\\', '/')

    suite.check('a mesh exports', fbx_utils.export_fbx(fbx_path, [sphere]) is True)
    suite.check('and the file is on disk', os.path.isfile(fbx_path))
    suite.check('nothing to export answers False rather than writing an empty file',
                fbx_utils.export_fbx(os.path.join(suite.temp, 'empty.fbx'), []) is False)

    harness.new_scene()
    arrived = fbx_utils.import_fbx(fbx_path)
    suite.check('the file reads back', bool(arrived), str(arrived))
    suite.check('and the mesh is in the scene', cmds.objExists('exported_sphere'))
    suite.check('where it was',
                [round(one, 3) for one in pm.PyNode('exported_sphere').t.get()] == [1.0, 2.0, 3.0],
                str(pm.PyNode('exported_sphere').t.get()))

    # Into a namespace.
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    arrived = fbx_utils.import_fbx(fbx_path, import_namespace='incoming')
    suite.check('an import can be put in a namespace',
                cmds.objExists('incoming:exported_sphere'),
                str([str(one) for one in arrived]))
    suite.check('and the namespace it was called from is restored',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':')

    # The bug: raise <string>.
    message = suite.raises('a file that is not there raises a real exception',
                           fbx_utils.import_fbx, os.path.join(suite.temp, 'no_such.fbx'))
    suite.check('and the message says which file', 'no_such.fbx' in message, message)

    # -- an animated export, with a named clip -------------------------------------------- #
    harness.new_scene()
    node = pm.createNode('transform', name='animated_thing')
    cmds.setKeyframe(str(node), attribute='translateX', time=1, value=0)
    cmds.setKeyframe(str(node), attribute='translateX', time=24, value=10)
    clip_path = os.path.join(suite.temp, 'a_clip.fbx').replace('\\', '/')

    suite.check('an animated export with a named clip works',
                fbx_utils.export_fbx(clip_path, [node], clip_name='TrueGrit',
                                     start_frame=1, end_frame=24) is True)
    suite.check('and the file is there', os.path.isfile(clip_path))

    harness.new_scene()
    fbx_utils.import_fbx(clip_path)
    suite.check('the animation comes back', cmds.objExists('animated_thing'))
    keys = cmds.keyframe('animated_thing.translateX', query=True) or []
    suite.check('with its keys on it', bool(keys), str(keys))
    cmds.currentTime(24)
    suite.check('and the values',
                abs(pm.PyNode('animated_thing').translateX.get() - 10.0) < 0.01,
                str(pm.PyNode('animated_thing').translateX.get()))

    # A clip with no frames given takes them from get_times.
    harness.new_scene()
    node = pm.createNode('transform', name='guessed_range')
    cmds.setKeyframe(str(node), attribute='translateZ', time=5, value=0)
    cmds.setKeyframe(str(node), attribute='translateZ', time=15, value=5)
    guessed_path = os.path.join(suite.temp, 'guessed.fbx').replace('\\', '/')
    suite.check('a clip with no frame range given works it out',
                fbx_utils.export_fbx(guessed_path, [node], clip_name='guessed') is True)
    suite.check('and writes a file', os.path.isfile(guessed_path))

    # -- the escape hatch ----------------------------------------------------------------- #
    suite.check('any FBX command can be reached by name',
                fbx_utils.fbx_command('FBXExportFileVersion', q=True) is not None)
    suite.check('the named wrappers that are left are the ones the pipeline calls',
                hasattr(fbx_utils, 'FBXExportTriangulate') and
                not hasattr(fbx_utils, 'FBXExportColladaFrameRate'))
    suite.check('load_fbx and assert_property are gone - they used assert, and had no callers',
                not hasattr(fbx_utils, 'load_fbx') and
                not hasattr(fbx_utils, 'assert_property'))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_time_utils(suite, pm)
    check_fbx(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('fbx_and_time', body))
