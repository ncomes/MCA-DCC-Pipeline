"""
Capturing what a camera sees: playblasts, stills, and the compressed video that comes out.

Everything here needs an interactive Maya. A playblast is Maya drawing the viewport into a file,
and a batch Maya has no viewport to draw - so each of these says so and gives back nothing rather
than raising, which is what a build step calling one of them wants.

The capture goes into a window of its own rather than the artist's viewport: that is the only way
to get a known resolution, and it means the capture does not depend on how they have their panels
arranged.

Where this came from, and what was wrong with it:

``utils/camera_utils.py`` held two unrelated halves. One was this - the playblast and still
capture, which needs nothing but Maya, a path and a camera. The other was the "ubercam": a
cinematic camera rig built from ``mca.mya.rigging.frag``, ``rigging.templates``,
``rigging.rig_utils``, ``animation.baking`` and ``pyqt.dialogs``. That half is not a utility at
all, it is a cinematics tool, and it is why a module in ``utils/`` sat at the bottom of a
dependency chain five packages deep. It comes over with ``cinematics/``, once ``rigging/frag`` is
ported; this is the half that can stand on its own.

What was wrong:

- **A frame range given as floats was silently thrown away.** ``playblast_video`` checked
  ``all(isinstance(x, int) for x in time_range)`` before believing the range it was handed - and
  ``time_utils.get_times()``, the obvious thing to pass, answers *floats*, because that is what
  ``playbackOptions`` answers. So a caller that asked for frames 1 to 24 got whatever
  ``get_times`` said instead. ``playblast_images`` did the same to its frame list.
- **``playblast_single_frame`` could return a single character.**
  ``playblast_images`` answers a list of paths for a folder and a bare string for a ``.jpg`` path;
  ``playblast_single_frame`` does ``image = playblast_images(...)`` and then ``image[0]``, which for
  the string case is its first letter. Both now answer a list, always.
- **The step that clears the previous run's stills looked in the wrong folder.** ``for x_file in
  os.listdir(file_path): if os.path.isfile(x_file)`` - ``x_file`` is a bare file name, so
  ``isfile`` asked about it relative to the current working directory, which in Maya is its own
  ``bin`` folder. It never found anything, so old stills were left behind, and the multi-frame
  return then listed them along with the new ones.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import fileio
from mca.common.utils import video_utils
from mca.mya.animation import time_utils


logger = log.MCA_LOGGER

#: What to capture at when the caller does not say.
DEFAULT_RESOLUTION = (1920, 1080)

#: The camera to use when the caller does not name one.
DEFAULT_CAMERA = 'persp'

#: What the multi-frame still capture calls its files.
STILLS_NAME = 'stills'

#: Panel elements turned off for a capture: none of them belong in a review video.
HIDDEN_IN_CAPTURE = {
    'nurbsCurves': False,
    'joints': False,
    'deformers': False,
    'cameras': False,
    'lights': False,
    'locators': False,
    'pivots': False,
}


def can_capture():
    """
    Whether this Maya can draw a playblast at all.

    :return: False in a batch Maya, which has no viewport.
    :rtype: bool
    """

    return not cmds.about(batch=True)


def _resolution_or_default(resolution):
    """
    :param resolution: A width and a height, or None.
    :return: Two whole numbers.
    :rtype: tuple(int, int)
    """

    try:
        width, height = resolution
        return int(width), int(height)
    except (TypeError, ValueError):
        return DEFAULT_RESOLUTION


def _camera_or_default(camera_node):
    """
    :param camera_node: A transform with a camera shape, or None.
    :return: A camera transform.
    :rtype: pm.nt.Transform
    """

    if camera_node is not None:
        try:
            if isinstance(camera_node.getShape(), pm.nt.Camera):
                return camera_node
        except AttributeError:
            pass
        logger.warning('%s is not a camera, so %s is being used instead.', camera_node,
                       DEFAULT_CAMERA)
    return pm.PyNode(DEFAULT_CAMERA)


def _frames_or_current(frame_list):
    """
    The frames to capture at.

    Numbers, not integers: ``playbackOptions`` and ``time_utils`` answer floats, and the version
    this replaces threw away anything that was not an ``int`` - which is everything those answer.

    :param frame_list: One frame, several, or None for the frame the scene is on.
    :return: The frames.
    :rtype: list(float)
    """

    if isinstance(frame_list, (int, float)):
        frame_list = [frame_list]
    frames = [one for one in (frame_list or []) if isinstance(one, (int, float))]
    return frames or [cmds.currentTime(query=True)]


def _time_range_or_scene(time_range):
    """
    The range to capture over.

    :param time_range: A first and last frame, or None to let
        :func:`mca.mya.animation.time_utils.get_times` decide.
    :return: The first and last frame.
    :rtype: tuple(float, float)
    """

    try:
        first, last = time_range
        if isinstance(first, (int, float)) and isinstance(last, (int, float)):
            return first, last
    except (TypeError, ValueError):
        pass
    return time_utils.get_times()


class background_colour(object):
    """
    Set the viewport background for a capture, and put it back afterwards.

    :param bg_color: Three floats, or None to leave the background alone.
    """

    def __init__(self, bg_color):
        self.wanted = self._checked(bg_color)
        self.original = None

    @staticmethod
    def _checked(bg_color):
        """
        :param bg_color: What the caller passed.
        :return: Three floats, or None.
        :raises ValueError: When it is something else - a background of the wrong shape is a
            mistake worth hearing about rather than ignoring.
        """

        if bg_color is None:
            return None
        if len(bg_color) != 3 or not all(isinstance(one, (int, float)) for one in bg_color):
            raise ValueError('A background colour is three numbers; this was {!r}.'
                             .format(bg_color))
        return tuple(float(one) for one in bg_color)

    def __enter__(self):
        if self.wanted is None:
            return self
        self.original = cmds.displayRGBColor('background', query=True)
        cmds.displayRGBColor('background', *self.wanted)
        return self

    def __exit__(self, exception_type, exception, traceback):
        if self.original is not None:
            cmds.displayRGBColor('background', *self.original)
        return False


def create_render_window(camera_node=None, resolution=None, render_style='smoothShaded',
                         lighting_style='default', display_textures=True, display_hud=False):
    """
    A window of its own, holding one panel looking through a camera, at a known size.

    The capture goes here rather than into the artist's viewport, so the result does not depend on
    how they have their panels arranged.

    :param pm.nt.Transform camera_node: The camera to look through. ``persp`` otherwise.
    :param resolution: The width and height of the panel. 1920 by 1080 otherwise.
    :param str render_style: How the panel draws - ``'smoothShaded'``, ``'wireframe'``,
        ``'flatShaded'``, ``'boundingBox'``.
    :param str lighting_style: Which lights the panel uses - ``'default'``, ``'all'``,
        ``'active'``, ``'none'``.
    :param bool display_textures: Draw textures.
    :param bool display_hud: Draw Maya's heads-up display.
    :return: The window and the panel, or ``(None, None)`` in a batch Maya.
    :rtype: tuple
    """

    if not can_capture():
        logger.warning('A batch Maya has no viewport, so no capture window was made.')
        return None, None

    camera_node = _camera_or_default(camera_node)
    width, height = _resolution_or_default(resolution)

    window = pm.window()
    # Two pixels wider than asked for: the playblast comes out that much narrower otherwise.
    window.setWidth(width + 2)
    window.setHeight(height)
    form = pm.formLayout()
    model_editor = pm.modelEditor()
    column = pm.columnLayout('true')
    pm.formLayout(form, edit=True,
                  attachForm=[(column, 'top', 0), (column, 'left', 0),
                              (model_editor, 'top', 0), (model_editor, 'bottom', 0),
                              (model_editor, 'right', 0)],
                  attachNone=[(column, 'bottom'), (column, 'right')],
                  attachControl=(model_editor, 'left', 0, column))
    pm.modelEditor(model_editor, edit=True,
                   displayAppearance=render_style,
                   displayTextures=display_textures,
                   displayLights=lighting_style,
                   twoSidedLighting=True,
                   camera=camera_node,
                   activeView=True,
                   hud=display_hud,
                   grid=False,
                   allObjects=True)
    pm.modelEditor(model_editor, edit=True, **HIDDEN_IN_CAPTURE)
    pm.showWindow(window)
    return window, model_editor


def playblast_video(file_path, camera_node=None, time_range=None, resolution=None, bg_color=None,
                    display_hud=False, lighting_style='default'):
    """
    Capture a range of frames as an AVI.

    :param str file_path: Where to write it. ``.avi`` is added if it is not there.
    :param pm.nt.Transform camera_node: The camera to look through.
    :param time_range: The first and last frame. :func:`time_utils.get_times` decides otherwise.
    :param resolution: The width and height.
    :param bg_color: Three floats for the background, or None to leave it.
    :param bool display_hud: Draw Maya's heads-up display.
    :param str lighting_style: Which lights the panel uses.
    :return: The file that was written, or '' when nothing was.
    :rtype: str
    """

    if not can_capture():
        logger.warning('A batch Maya cannot playblast, so %s was not written.', file_path)
        return ''

    first, last = _time_range_or_scene(time_range)
    if not file_path.endswith('.avi'):
        file_path = '{}.avi'.format(file_path)

    with background_colour(bg_color):
        window, model_editor = create_render_window(camera_node, resolution,
                                                    display_hud=display_hud,
                                                    lighting_style=lighting_style)
        try:
            cmds.select(clear=True)
            cmds.refresh()
            fileio.touch_path(file_path, True)
            # An AVI ignores completeFilename, so filename is what names the file here.
            pm.playblast(percent=100, startTime=first, endTime=last, filename=file_path,
                         format='avi', viewer=False, editorPanelName=model_editor,
                         forceOverwrite=True, showOrnaments=True, useTraxSounds=False,
                         sound=None)
        finally:
            if window is not None:
                window.delete()

    return file_path if os.path.isfile(file_path) else ''


def playblast_images(file_path, camera_node=None, frame_list=None, resolution=None, bg_color=None,
                     hud=False, lighting_style='default'):
    """
    Capture one or more frames as JPEGs.

    :param str file_path: A ``.jpg`` file for a single frame, or a folder for several.
    :param pm.nt.Transform camera_node: The camera to look through.
    :param frame_list: The frames to capture. The current one otherwise.
    :param resolution: The width and height.
    :param bg_color: Three floats for the background, or None to leave it.
    :param bool hud: Draw Maya's heads-up display.
    :param str lighting_style: Which lights the panel uses.
    :return: The files that were written. Always a list - the version this replaces answered a bare
        string for the single-frame case, and its own caller then took the first *character* of it.
    :rtype: list(str)
    """

    if not can_capture():
        logger.warning('A batch Maya cannot playblast, so nothing was written to %s.', file_path)
        return []

    frames = _frames_or_current(frame_list)
    single_file = file_path.endswith('.jpg')

    with background_colour(bg_color):
        window, model_editor = create_render_window(camera_node, resolution, display_hud=hud,
                                                    lighting_style=lighting_style)
        try:
            cmds.select(clear=True)
            cmds.refresh()
            if single_file:
                fileio.touch_path(file_path, True)
                pm.playblast(percent=100, frame=frames[0], format='image', compression='jpg',
                             viewer=False, editorPanelName=model_editor, forceOverwrite=True,
                             showOrnaments=False, completeFilename=file_path)
            else:
                _clear_previous_stills(file_path)
                pm.playblast(percent=100, filename=os.path.join(file_path, STILLS_NAME),
                             frame=frames, format='image', compression='jpg', viewer=False,
                             editorPanelName=model_editor, forceOverwrite=True,
                             showOrnaments=False)
        finally:
            if window is not None:
                window.delete()

    if single_file:
        return [file_path] if os.path.isfile(file_path) else []
    return sorted(os.path.join(file_path, name) for name in os.listdir(file_path)
                  if name.startswith('{}.'.format(STILLS_NAME)))


def _clear_previous_stills(folder):
    """
    Delete the stills a previous capture left in this folder.

    The version this replaces wrote ``for x_file in os.listdir(folder): if
    os.path.isfile(x_file)`` - a bare file name, so ``isfile`` asked about it relative to the
    current working directory, which in Maya is its own ``bin`` folder. It never found anything, so
    old stills stayed and the return then listed them among the new ones.

    :param str folder: The folder to clear.
    :return: The files that were removed.
    :rtype: list(str)
    """

    fileio.touch_path(os.path.join(folder, ''))
    removed = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or not name.startswith(STILLS_NAME):
            continue
        fileio.touch_path(path, remove=True)
        removed.append(path)
    return removed


def playblast_single_frame(file_path, image_name=None, camera_node=None, frame=None,
                           resolution=None, bg_color=None, hud=False, lighting_style='default'):
    """
    Capture one frame, optionally under a name of the caller's choosing.

    :param str file_path: A ``.jpg`` file, or a folder to write into.
    :param str image_name: What to call the image. Its captured name otherwise.
    :param pm.nt.Transform camera_node: The camera to look through.
    :param frame: The frame to capture. The current one otherwise.
    :param resolution: The width and height.
    :param bg_color: Three floats for the background, or None to leave it.
    :param bool hud: Draw Maya's heads-up display.
    :param str lighting_style: Which lights the panel uses.
    :return: The file that was written, or '' when nothing was.
    :rtype: str
    """

    captured = playblast_images(file_path, camera_node=camera_node, frame_list=frame,
                               resolution=resolution, bg_color=bg_color, hud=hud,
                               lighting_style=lighting_style)
    if not captured:
        logger.warning('Nothing was captured to %s.', file_path)
        return ''

    image = captured[0]
    if not image_name:
        return image

    directory = os.path.dirname(image)
    wanted_name = '{}.jpg'.format(image_name.lower())
    wanted_path = os.path.join(directory, wanted_name)
    if os.path.exists(wanted_path):
        fileio.touch_path(wanted_path, remove=True)
    return fileio.rename_file(name=os.path.basename(image), directory=directory,
                              new_name=wanted_name)


def capture_and_compress_video(file_path, camera_node=None, time_range=None, resolution=None,
                               delete_uncompressed=True, background=None, hud=False,
                               lighting_style='default'):
    """
    Capture a range of frames and hand back an MP4.

    Maya only writes AVI, and an AVI of a few hundred frames is far too large to put in a review
    tool, so the capture goes through ffmpeg.

    :param str file_path: Where the MP4 goes. It has to end in ``.mp4``.
    :param pm.nt.Transform camera_node: The camera to look through.
    :param time_range: The first and last frame.
    :param resolution: The width and height.
    :param bool delete_uncompressed: Delete the AVI once the MP4 is written.
    :param background: Three floats for the background, or None to leave it.
    :param bool hud: Draw Maya's heads-up display.
    :param str lighting_style: Which lights the panel uses.
    :return: The MP4, or '' when it was not written.
    :rtype: str
    """

    if not file_path.endswith('.mp4'):
        logger.warning('%s: the path for a compressed capture has to end in .mp4.', file_path)
        return ''
    if not can_capture():
        logger.warning('A batch Maya cannot playblast, so %s was not written.', file_path)
        return ''

    fileio.touch_path(file_path)
    avi_path = file_path[:-len('.mp4')] + '.avi'

    captured = playblast_video(os.path.join(os.path.dirname(file_path), 'temp.avi'),
                               camera_node=camera_node, time_range=time_range,
                               resolution=resolution, bg_color=background, display_hud=hud,
                               lighting_style=lighting_style)
    if not captured:
        return ''

    fileio.touch_path(avi_path, True)
    os.rename(captured, avi_path)

    compressed = video_utils.ffmpeg_convert_to_mp4(avi_path)
    if compressed and os.path.exists(compressed) and delete_uncompressed:
        fileio.touch_path(avi_path, remove=True)
    return compressed or ''


def create_center_capture(focus_objects, file_path, image_name, resolution=(75, 100),
                          focal_length=90, auto_capture=True):
    """
    Frame some objects and capture one image of them - a thumbnail for an asset.

    A camera of its own is made and thrown away, so the artist's ``persp`` is not left pointing
    somewhere they did not put it.

    :param focus_objects: What to frame.
    :param str file_path: Where to write the image.
    :param str image_name: What to call it.
    :param resolution: The width and height.
    :param float focal_length: How close the objects look. Higher is closer.
    :param bool auto_capture: Frame the objects by moving ``persp`` and using ``viewFit``. False
        uses ``persp`` wherever it happens to be.
    :return: The file that was written, or '' when nothing was.
    :rtype: str
    """

    if not can_capture():
        logger.warning('A batch Maya cannot playblast, so no thumbnail was made for %s.',
                       file_path)
        return ''

    persp_camera = pm.PyNode(DEFAULT_CAMERA)
    original_translate = persp_camera.translate.get()
    original_rotate = persp_camera.rotate.get()

    capture_transform = pm.camera(name='capture_camera')[0]
    try:
        if auto_capture:
            persp_camera.translate.set(0, 0, 0)
            persp_camera.rotate.set(0, 0, 0)
            pm.viewFit(focus_objects)
        capture_transform.translate.set(persp_camera.translate.get())
        capture_transform.rotate.set(persp_camera.rotate.get())
        capture_transform.focalLength.set(focal_length)
        return playblast_single_frame(file_path=file_path, image_name=image_name,
                                     camera_node=capture_transform, resolution=resolution)
    finally:
        pm.delete(capture_transform)
        # The artist's own camera is put back. The version this replaces moved persp to the origin
        # and left it there.
        persp_camera.translate.set(original_translate)
        persp_camera.rotate.set(original_rotate)
