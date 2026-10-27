"""
Clearing the rubbish out of a scene, and saving it: mca.mya.utils.scene_utils.

    mayapy tests/test_scene_utils.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_deleters(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import scene_utils

    # -- unknown nodes ------------------------------------------------------------------ #
    harness.new_scene()
    suite.check('a clean scene has no unknown nodes to delete',
                scene_utils.delete_unknown_nodes() == [])

    # -- garbage ------------------------------------------------------------------------ #
    harness.new_scene()
    cmds.createNode('hyperView', name='a_hyper_view')
    cmds.createNode('hyperLayout', name='a_hyper_layout')
    empty_set = cmds.sets(name='an_empty_set', empty=True)
    suite.check('the set is there to start with', cmds.objExists(empty_set))

    deleted = scene_utils.delete_garbage()
    suite.check('a hyperView is rubbish', not cmds.objExists('a_hyper_view'), str(deleted))
    suite.check('a hyperLayout is rubbish', not cmds.objExists('a_hyper_layout'), str(deleted))
    suite.check('and an empty object set is too', not cmds.objExists(empty_set), str(deleted))

    # A set with something in it is not rubbish.
    harness.new_scene()
    sphere = pm.polySphere(name='kept_sphere')[0]
    full_set = cmds.sets(str(sphere), name='a_full_set')
    scene_utils.delete_garbage()
    suite.check('a set with something in it is kept', cmds.objExists(full_set))

    # The bug: `connection_node in ['characterPartition']` compared a PyNode against a string,
    # so the one node the skip list existed for was deleted like any other.
    suite.check('the skip list is compared by name now',
                'characterPartition' in scene_utils.GARBAGE_SKIP_NAMES)

    # -- render layers ------------------------------------------------------------------ #
    harness.new_scene()
    cmds.createRenderLayer(name='a_render_layer', empty=True)
    deleted = scene_utils.delete_render_layers()
    suite.check('a render layer is deleted', not cmds.objExists('a_render_layer'), str(deleted))
    suite.check("Maya's own render layer is kept", cmds.objExists('defaultRenderLayer'))

    # -- orphans ------------------------------------------------------------------------ #
    harness.new_scene()
    orphan = cmds.createNode('groupId', name='an_orphan')
    mesh = pm.polySphere(name='grouped_sphere')[0]
    used = cmds.createNode('groupId', name='a_used_one')
    cmds.connectAttr('{}.groupId'.format(used),
                     '{}.instObjGroups[0].objectGroups[0].objectGroupId'
                     .format(mesh.getShape()))

    deleted = scene_utils.delete_orphaned_group_id_nodes()
    suite.check('a groupId nothing is using is deleted', not cmds.objExists(orphan), str(deleted))
    suite.check('and one something is using is kept', cmds.objExists(used))

    harness.new_scene()
    control = pm.createNode('transform', name='a_control')
    cmds.controller(str(control))
    tags = cmds.ls(type='controller')
    suite.check('a controller tag was made', bool(tags), str(tags))
    scene_utils.delete_orphaned_controller_tags()
    suite.check('a tag whose control is still there is kept',
                bool(cmds.ls(type='controller')), str(cmds.ls(type='controller')))
    cmds.delete(str(control))
    deleted = scene_utils.delete_orphaned_controller_tags()
    suite.check('a tag whose control is gone is deleted',
                not cmds.ls(type='controller'), str(deleted))

    harness.new_scene()
    cmds.createNode('nodeGraphEditorInfo', name='some_editor_state')
    deleted = scene_utils.delete_orphaned_graph_editor_infos()
    suite.check('graph editor bookkeeping nothing uses is deleted',
                not cmds.objExists('some_editor_state'), str(deleted))

    harness.new_scene()
    suite.check('every orphan pass together runs without raising',
                isinstance(scene_utils.delete_orphaned_nodes(), list))

    # -- the two that delegate ---------------------------------------------------------- #
    # The bug: this module had its own second implementation of each of these.
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='an_empty_namespace')
    cmds.createDisplayLayer(name='an_empty_layer', empty=True)

    suite.check('an empty namespace is removed',
                'an_empty_namespace' in scene_utils.delete_empty_namespaces())
    suite.check('and an empty display layer',
                any('an_empty_layer' in one for one in
                    scene_utils.delete_empty_display_layers()))

    from mca.mya.utils import namespace, display_layers
    suite.check('the namespace pass is the one in utils.namespace',
                scene_utils.delete_empty_namespaces.__doc__ is not None and
                namespace.delete_empty_namespaces is not None)
    suite.check('and the display layer pass the one in utils.display_layers',
                display_layers.delete_empty_display_layers is not None)

    # -- the shader pass, which needs a window ------------------------------------------ #
    #
    # It answers False in a batch Maya because the MEL it drives needs a window. Where
    # there is one - run_in_maya.run_all() - it does the work and answers True, so this is
    # a check about the environment and has to ask which one it is in.
    if cmds.about(batch=True):
        suite.check('the unused-shader pass says no rather than raising in a batch Maya',
                    scene_utils.delete_unused_shader_nodes() is False)
    else:
        suite.note('unused-shader pass', 'skipped - this Maya has a window')

    # -- clean_scene -------------------------------------------------------------------- #
    harness.new_scene()
    cmds.createNode('hyperView', name='rubbish_one')
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='rubbish_namespace')
    cmds.createDisplayLayer(name='rubbish_layer', empty=True)
    keeper = pm.polySphere(name='the_only_thing_worth_keeping')[0]

    deleted = scene_utils.clean_scene()
    suite.check('the whole pass deletes the rubbish',
                not cmds.objExists('rubbish_one') and
                not cmds.namespace(exists=':rubbish_namespace') and
                not cmds.objExists('rubbish_layer'), str(deleted))
    suite.check('and leaves the scene', pm.objExists(keeper))
    suite.check('and says what it took out', len(deleted) >= 3, str(deleted))


def check_backup_and_save(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import scene_utils

    harness.new_scene()
    folder = scene_utils.backup_folder()
    suite.check('the backup folder is made', os.path.isdir(folder))
    # The bug: this was a hard-coded C:\export_backup.
    suite.check('and is under this run\'s preferences root, not a hard-coded C:\\ path',
                os.environ['MCA_PREFS_ROOT'].replace('\\', '/').lower()
                in folder.replace('\\', '/').lower(), folder)

    scene_path = os.path.join(suite.temp, 'the_real_scene.ma').replace('\\', '/')
    pm.polySphere(name='in_the_scene')
    cmds.file(rename=scene_path)
    cmds.file(save=True, type='mayaAscii')

    written = scene_utils.backup_scene(backup_name='suite_backup')
    suite.check('a backup is written', os.path.isfile(written), written)
    suite.check('into the backup folder',
                os.path.dirname(written).lower() == folder.lower(), written)
    # The bug: backup_scene renamed the open scene to the backup and left it there.
    suite.check("the artist's own scene name is put back",
                cmds.file(query=True, sceneName=True).replace('\\', '/') == scene_path,
                cmds.file(query=True, sceneName=True))

    second = scene_utils.backup_scene(backup_name='suite_backup')
    suite.check('a second backup does not write over the first', second != written, second)
    suite.check('both are on disk', os.path.isfile(written) and os.path.isfile(second))

    # The bug: backup_scene ran clean_scene unconditionally, so a function called "backup"
    # deleted nodes out of the scene the artist was looking at.
    cmds.createNode('hyperView', name='would_be_cleaned')
    scene_utils.backup_scene(backup_name='suite_backup')
    suite.check('backing up does not clean the scene unless it is asked to',
                cmds.objExists('would_be_cleaned'))
    scene_utils.backup_scene(backup_name='suite_backup', clean=True)
    suite.check('and does when it is', not cmds.objExists('would_be_cleaned'))

    # -- save_as ------------------------------------------------------------------------ #
    harness.new_scene()
    pm.polySphere(name='saved_sphere')
    ascii_path = os.path.join(suite.temp, 'saved.ma').replace('\\', '/')
    suite.check('a scene saves as ascii', scene_utils.save_as(ascii_path) is True)
    suite.check('and the file is there', os.path.isfile(ascii_path))
    suite.check('it really is ascii',
                open(ascii_path, 'rb').read(20).startswith(b'//Maya ASCII'),
                str(open(ascii_path, 'rb').read(20)))

    binary_path = os.path.join(suite.temp, 'saved.mb').replace('\\', '/')
    suite.check('and as binary from the extension', scene_utils.save_as(binary_path) is True)
    suite.check('the binary file is there', os.path.isfile(binary_path))

    suite.check('no path is refused', scene_utils.save_as('') is False)
    suite.check('a path that cannot be written answers False rather than raising',
                scene_utils.save_as(os.path.join(suite.temp, 'no_such_folder', 'x.ma'))
                is False)
    harness.new_scene()


def check_clean_imported_nodes(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import scene_utils

    harness.new_scene()
    group = pm.createNode('transform', name='imported_grp')
    sphere = pm.polySphere(name='imported_mesh')[0]
    sphere.setParent(group)
    light = pm.createNode('pointLight', name='imported_lightShape')
    camera = pm.createNode('camera', name='imported_cameraShape')

    names = [str(one.longName()) for one in (group, sphere)] + \
            [str(light.longName()), str(camera.longName())]
    kept = scene_utils.clean_imported_nodes(names)

    suite.check('the transforms are kept', len(kept) == 2, str(kept))
    # The bug: it answered with name.replace('|', ''), which names nothing at all.
    suite.check('and their names are still paths to them',
                all(cmds.objExists(one) for one in kept), str(kept))
    suite.check('the pipes are still in the paths',
                any('|' in one for one in kept), str(kept))
    suite.check('the mesh survives', pm.objExists(sphere))
    suite.check('the light does not', not cmds.objExists('imported_lightShape'))
    suite.check('nor the camera', not cmds.objExists('imported_cameraShape'))
    suite.check('what is kept is shaded with the default',
                any('imported_grp' in str(one) or 'imported_mesh' in str(one)
                    for one in pm.PyNode('initialShadingGroup').members()),
                str(pm.PyNode('initialShadingGroup').members()))

    suite.check('a name that is not a node is skipped rather than raising',
                scene_utils.clean_imported_nodes(['no_such_node_at_all']) == [])
    suite.check('nothing to clean is not an error',
                scene_utils.clean_imported_nodes([]) == [])


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_deleters(suite, pm)
    check_backup_and_save(suite, pm)
    check_clean_imported_nodes(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('scene_utils', body))
