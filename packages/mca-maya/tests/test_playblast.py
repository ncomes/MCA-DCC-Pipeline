"""
Capturing what a camera sees: mca.mya.utils.playblast.

A playblast is Maya drawing the viewport into a file, and a batch Maya has no viewport - so the
capture itself cannot run here. What can be checked is everything around it: that each function
refuses politely rather than raising, and that the argument handling, which is where the bugs were,
is right.

    mayapy tests/test_playblast.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def body(suite):
    harness.add_sibling_packages()

    import maya.cmds as cmds
    import pymel.core as pm
    from mca.mya.utils import playblast

    harness.new_scene()
    # These answers are the ones a batch Maya gives. run_in_maya.run_all() runs this same
    # suite in a Maya that has a window, where capturing really can happen, so asserting
    # the batch answers there fails on the environment rather than on the code.
    batch = cmds.about(batch=True)
    if batch:
        suite.check('a batch Maya says it cannot capture', playblast.can_capture() is False)
    else:
        suite.note('capture checks', 'skipped - this Maya has a window')

    # -- the resolution ------------------------------------------------------------------ #
    suite.check('no resolution given falls back to the default',
                playblast._resolution_or_default(None) == playblast.DEFAULT_RESOLUTION)
    suite.check('a pair of numbers is used',
                playblast._resolution_or_default((640, 480)) == (640, 480))
    suite.check('a list works as well as a tuple',
                playblast._resolution_or_default([640, 480]) == (640, 480))
    suite.check('floats are rounded down to whole pixels',
                playblast._resolution_or_default((640.7, 480.2)) == (640, 480))
    suite.check('something that is not a pair falls back',
                playblast._resolution_or_default((640,)) == playblast.DEFAULT_RESOLUTION)
    suite.check('and so does nonsense',
                playblast._resolution_or_default('big') == playblast.DEFAULT_RESOLUTION)

    # -- the camera ---------------------------------------------------------------------- #
    suite.check('no camera given uses persp',
                str(playblast._camera_or_default(None)) == playblast.DEFAULT_CAMERA)
    shot_camera = pm.camera(name='shot_cam')[0]
    suite.check('a camera is used', playblast._camera_or_default(shot_camera) == shot_camera)
    not_a_camera = pm.createNode('transform', name='just_a_transform')
    suite.check('something that is not a camera falls back to persp, with a warning',
                str(playblast._camera_or_default(not_a_camera)) == playblast.DEFAULT_CAMERA)
    suite.check('and so does something that is not a node at all',
                str(playblast._camera_or_default('a string')) == playblast.DEFAULT_CAMERA)

    # -- the frames ---------------------------------------------------------------------- #
    # The bug: `all(isinstance(x, int) for x in frame_list)`, and everything that answers a frame
    # in Maya answers a float - so a caller that asked for particular frames got the current one.
    cmds.currentTime(7)
    suite.check('no frames given uses the frame the scene is on',
                playblast._frames_or_current(None) == [7.0],
                str(playblast._frames_or_current(None)))
    suite.check('one frame becomes a list of one',
                playblast._frames_or_current(12) == [12])
    suite.check('a float frame is kept, not thrown away - the whole bug',
                playblast._frames_or_current(12.0) == [12.0],
                str(playblast._frames_or_current(12.0)))
    suite.check('a list of floats is kept',
                playblast._frames_or_current([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0],
                str(playblast._frames_or_current([1.0, 2.0, 3.0])))
    suite.check('a list of ints is kept too',
                playblast._frames_or_current([1, 2]) == [1, 2])
    suite.check('anything in the list that is not a number is dropped',
                playblast._frames_or_current([1, 'two', 3]) == [1, 3],
                str(playblast._frames_or_current([1, 'two', 3])))
    suite.check('a list of nothing usable falls back to the current frame',
                playblast._frames_or_current(['a', None]) == [7.0])

    # -- the time range ------------------------------------------------------------------ #
    cmds.playbackOptions(edit=True, animationStartTime=1, animationEndTime=48,
                         minTime=1, maxTime=48)
    suite.check('a float range is used as given - the same bug',
                playblast._time_range_or_scene((1.0, 24.0)) == (1.0, 24.0),
                str(playblast._time_range_or_scene((1.0, 24.0))))
    suite.check('an int range is used', playblast._time_range_or_scene([5, 10]) == (5, 10))
    suite.check('no range given asks time_utils',
                playblast._time_range_or_scene(None) == (1.0, 48.0),
                str(playblast._time_range_or_scene(None)))
    suite.check('a range of the wrong shape asks time_utils too',
                playblast._time_range_or_scene((5,)) == (1.0, 48.0))

    # -- the background colour ----------------------------------------------------------- #
    suite.check('no colour given leaves the background alone',
                playblast.background_colour(None).wanted is None)
    suite.check('three numbers are kept as floats',
                playblast.background_colour([0, 1, 0]).wanted == (0.0, 1.0, 0.0))
    suite.raises('two numbers is refused, rather than quietly ignored',
                 playblast.background_colour, [0, 1])
    suite.raises('and so is something that is not numbers',
                 playblast.background_colour, ['red', 'green', 'blue'])

    with playblast.background_colour(None):
        suite.check('the do-nothing case still works as a context', True)

    # -- every capture refuses politely in a batch Maya ---------------------------------- #
    folder = os.path.join(suite.temp, 'captures')
    os.makedirs(folder)

    if batch:
        suite.check('no window is made in a batch Maya',
                    playblast.create_render_window() == (None, None))
        suite.check('a video capture answers empty rather than raising',
                    playblast.playblast_video(os.path.join(folder, 'a.avi')) == '')
        suite.check('a still capture answers an empty list',
                    playblast.playblast_images(folder) == [])
        suite.check('a single-frame capture answers empty',
                    playblast.playblast_single_frame(os.path.join(folder, 'a.jpg')) == '')
        suite.check('a compressed capture answers empty',
                    playblast.capture_and_compress_video(os.path.join(folder, 'a.mp4')) == '')
        suite.check('a thumbnail answers empty',
                    playblast.create_center_capture([], os.path.join(folder, 'thumb'),
                                                    'thumb') == '')
    suite.check('a compressed capture to a path that is not an mp4 is refused first of all',
                playblast.capture_and_compress_video(os.path.join(folder, 'a.mov')) == '')

    # -- clearing the previous run's stills ----------------------------------------------- #
    # The bug: `for x_file in os.listdir(folder): if os.path.isfile(x_file)` asked about a bare
    # file name relative to the current working directory, which in Maya is its own bin folder.
    # It never found anything, so old stills stayed and the return listed them with the new ones.
    stills_folder = os.path.join(suite.temp, 'stills')
    os.makedirs(stills_folder)
    for name in ('stills.0001.jpg', 'stills.0002.jpg', 'something_else.jpg'):
        with open(os.path.join(stills_folder, name), 'w') as opened:
            opened.write('x')
    # Not the folder Maya is running in, which is the whole point.
    suite.check('the working directory is not the stills folder',
                os.path.normpath(os.getcwd()) != os.path.normpath(stills_folder), os.getcwd())

    removed = playblast._clear_previous_stills(stills_folder)
    suite.check('the previous stills are found and removed', len(removed) == 2, str(removed))
    suite.check('and are gone', not os.path.isfile(os.path.join(stills_folder, 'stills.0001.jpg')))
    suite.check('while anything else in the folder is left',
                os.path.isfile(os.path.join(stills_folder, 'something_else.jpg')))
    suite.check('clearing a folder that is not there makes it rather than raising',
                playblast._clear_previous_stills(
                    os.path.join(suite.temp, 'not_yet')) == [])
    suite.check('and the folder is there afterwards',
                os.path.isdir(os.path.join(suite.temp, 'not_yet')))

    # -- what moved, and what did not ----------------------------------------------------- #
    # camera_utils held two unrelated halves. This is the one that stands on its own; the ubercam
    # half is a cinematics tool built on rigging.frag and comes over with cinematics/.
    for name in ('create_mca_ubercam', 'find_ubercam', 'get_ubercam_frag_rig',
                 'remove_ubercam_cmd', 'copy_camera'):
        suite.check('{} is not here - it belongs with the cinematics tools'.format(name),
                    not hasattr(playblast, name))
    for name in ('create_render_window', 'playblast_video', 'playblast_images',
                 'playblast_single_frame', 'capture_and_compress_video', 'create_center_capture'):
        suite.check('{} is here'.format(name), hasattr(playblast, name))

    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('playblast', body))
