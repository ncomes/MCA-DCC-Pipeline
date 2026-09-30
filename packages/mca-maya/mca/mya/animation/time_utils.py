"""
Frame ranges: which one a tool should use, and how to set them.

Maya has four different "the range" at once - the visible timeline, the scene's own range, the
part of the timeline a user has dragged out, and whatever frames actually carry keys - and almost
every bug in a baking or exporting tool comes from picking the wrong one. :func:`get_times` is
the pipeline's answer: it asks for each in turn, most specific first, and says in the log which
one it settled on.

What was wrong before:

- **Importing this module loaded a plugin and a piece of Maya's interface.** Two lines at module
  level: ``from maya.plugin.timeSliderBookmark.timeSliderBookmark import createBookmark`` and
  ``plugins.load_plugin('timeSliderBookmark')``. Anything that imported this - and the FBX
  exporter does - paid for a plugin load, in a batch Maya as much as in an interactive one. They
  happen inside :func:`create_bookmark` now, which is the only thing that needs either.
- **``set_timeline_range`` could not be given frame 0.** It tested ``if not scene_start_time``,
  and ``0`` is falsy, so a scene meant to start at zero was given the visible range's start
  instead.
- **``get_keyframe_range_from_nodes`` answered "no keys" for a single node.** It read its keys
  only ``if isinstance(node_list, list)`` - so one PyNode, or a tuple, came back as
  ``(None, None)`` whatever keys it had.
- **Two log messages were bare string expressions.** ``'No keys found in scene'`` on a line of
  its own, twice, which builds a string and throws it away.
- Tabs for indentation, in a package that is otherwise spaces.
"""

# python imports

# software specific imports
import maya.cmds as cmds
import maya.mel as mel
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.common.utils import pymaths


logger = log.MCA_LOGGER

#: The plugin that provides timeline bookmarks. Loaded when one is asked for, not on import.
BOOKMARK_PLUGIN = 'timeSliderBookmark'

#: Where :func:`reframe_visible_range` puts the timeline when the scene has no keys at all.
DEFAULT_RANGE = (0, 100)


# --------------------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------------------- #
def get_visible_start_time():
    """
    :return: The first frame of the timeline as it is zoomed.
    :rtype: float
    """

    return cmds.playbackOptions(query=True, minTime=True)


def get_visible_end_time():
    """
    :return: The last frame of the timeline as it is zoomed.
    :rtype: float
    """

    return cmds.playbackOptions(query=True, maxTime=True)


def get_visible_range():
    """
    :return: The first and last frame of the timeline as it is zoomed.
    :rtype: tuple(float, float)
    """

    return get_visible_start_time(), get_visible_end_time()


def get_scene_start_time():
    """
    :return: The scene's own first frame, whatever the timeline is zoomed to.
    :rtype: float
    """

    return cmds.playbackOptions(query=True, animationStartTime=True)


def get_scene_end_time():
    """
    :return: The scene's own last frame.
    :rtype: float
    """

    return cmds.playbackOptions(query=True, animationEndTime=True)


def get_scene_range():
    """
    :return: The scene's own first and last frame.
    :rtype: tuple(float, float)
    """

    return get_scene_start_time(), get_scene_end_time()


def _scene_keys():
    """
    Every frame anything in the scene is keyed on.

    :return: The frames, unsorted and with repeats. Empty when nothing is keyed - which the
        version this replaces reported with a bare string expression on a line of its own, twice.
    :rtype: list(float)
    """

    curves = cmds.ls(type='animCurve')
    if not curves:
        logger.debug('There are no animation curves in the scene.')
        return []
    keys = cmds.keyframe(curves, query=True)
    if not keys:
        logger.debug('The scene has animation curves but no keys on them.')
        return []
    return keys


def get_scene_first_keyframe():
    """
    The first frame anything in the scene is keyed on.

    Read from the curves, not from the timeline: a scene can be animated well outside the range
    somebody set.

    :return: The frame, or None when nothing is keyed.
    :rtype: float or None
    """

    keys = _scene_keys()
    return min(keys) if keys else None


def get_scene_last_keyframe():
    """
    The last frame anything in the scene is keyed on.

    :return: The frame, or None when nothing is keyed.
    :rtype: float or None
    """

    keys = _scene_keys()
    return max(keys) if keys else None


def get_keyframe_range_from_scene():
    """
    :return: The first and last frame anything in the scene is keyed on, or ``(None, None)``.
    :rtype: tuple
    """

    return get_scene_first_keyframe(), get_scene_last_keyframe()


def get_keyframe_range_from_nodes(node_list):
    """
    The first and last frame these nodes are keyed on.

    :param node_list: The nodes to read. One on its own is fine - the version this replaces
        answered ``(None, None)`` for anything that was not a list.
    :return: The first and last frame, or ``(None, None)`` when none of them is keyed.
    :rtype: tuple
    """

    nodes = lists.force_list(node_list or [])
    if not nodes:
        return None, None
    keys = pm.keyframe(nodes, query=True)
    if not keys:
        return None, None
    return min(keys), max(keys)


def get_range_from_attribute_curves(attr_curve_list):
    """
    The first and last of the keys a user has selected on these curves.

    :param attr_curve_list: The animation curves.
    :return: The first and last selected frame, or ``(None, None)``.
    :rtype: tuple
    """

    selected_keys = pm.keyframe(attr_curve_list, query=True, selected=True)
    if not selected_keys:
        return None, None
    return min(selected_keys), max(selected_keys)


def get_selected_range_from_timeline():
    """
    The part of the timeline the user has dragged out, if any.

    :return: The first and last frame of the selection, or ``(None, None)`` - which is also the
        answer in a batch Maya, where there is no timeline to ask.
    :rtype: tuple
    """

    try:
        playback_slider = mel.eval('$tmpVar=$gPlayBackSlider')
        if not pm.timeControl(playback_slider, query=True, rangeVisible=True):
            return None, None
        first, last = pm.timeControl(playback_slider, query=True, rangeArray=True)
    except RuntimeError:
        # No timeline. A batch Maya has no playback slider at all.
        return None, None
    return first, last


def get_current_time():
    """
    :return: The frame the scene is on.
    :rtype: float
    """

    return cmds.currentTime(query=True)


# --------------------------------------------------------------------------------------- #
# choosing
# --------------------------------------------------------------------------------------- #
def get_times(node_list=None, min_selected_frames=1, ignore_selection=True):
    """
    The frame range a tool should work over, chosen from most specific to least.

    In order:

    1. the part of the timeline the user dragged out,
    2. the keys they selected in the graph editor, when ``ignore_selection`` is False,
    3. the keys on the nodes they were given,
    4. every key in the scene,
    5. the widest of the scene range and the zoomed timeline.

    Which one it settled on goes into the log at debug level, because "it baked the wrong range"
    is otherwise very hard to account for after the fact.

    :param node_list: Nodes to take a range from at step three.
    :param int min_selected_frames: A timeline selection shorter than this is a mis-click, not a
        range.
    :param bool ignore_selection: Skip step two. Most tools want this: a user's graph editor
        selection is rarely what they mean by "the range to export".
    :return: The first and last frame.
    :rtype: tuple(float, float)
    """

    frame_range = get_selected_range_from_timeline()
    chosen = '1. the timeline selection'

    complete = not any(one is None for one in frame_range)
    selected_frames = (frame_range[-1] - frame_range[0]) if complete else 0

    if not complete or selected_frames < min_selected_frames:
        if not ignore_selection:
            attr_curves = pm.keyframe(query=True, selected=True, name=True)
            if attr_curves:
                frame_range = get_range_from_attribute_curves(attr_curves)
                chosen = '2. the selected animation curves'

        if any(one is None for one in frame_range) and node_list:
            frame_range = get_keyframe_range_from_nodes(node_list)
            chosen = '3. the keys on the nodes given'

        if any(one is None for one in frame_range):
            frame_range = get_keyframe_range_from_scene()
            chosen = "4. every key in the scene"

        if any(one is None for one in frame_range):
            frame_range = (min(get_scene_start_time(), get_visible_start_time()),
                           max(get_scene_end_time(), get_visible_end_time()))
            chosen = '5. the scene and timeline ranges together'

    logger.debug('Frame range from %s: %s to %s.', chosen, frame_range[0], frame_range[1])
    return frame_range


# --------------------------------------------------------------------------------------- #
# setting
# --------------------------------------------------------------------------------------- #
def set_timeline_range(visible_start_time, visible_end_time, scene_start_time=None,
                       scene_end_time=None):
    """
    Set both of Maya's ranges: the scene's own, and the part of it the timeline shows.

    :param float visible_start_time: The first frame the timeline shows.
    :param float visible_end_time: The last frame it shows.
    :param float scene_start_time: The scene's own first frame. The visible one otherwise.
    :param float scene_end_time: The scene's own last frame. The visible one otherwise.
    """

    # `is None`, not `not`: frame 0 is a real frame and a falsy one, and the version this replaces
    # read a scene start of 0 as "not given".
    if scene_start_time is None:
        scene_start_time = visible_start_time
    if scene_end_time is None:
        scene_end_time = visible_end_time

    cmds.playbackOptions(edit=True, animationStartTime=scene_start_time,
                         minTime=visible_start_time, maxTime=visible_end_time,
                         animationEndTime=scene_end_time)


def reframe_visible_range():
    """
    Put the timeline around whatever the scene is actually animated over.

    :return: The range it was set to.
    :rtype: tuple(float, float)
    """

    first = get_scene_first_keyframe()
    last = get_scene_last_keyframe()
    first = round(first) if first is not None else DEFAULT_RANGE[0]
    last = round(last) if last is not None else DEFAULT_RANGE[1]
    if last <= first:
        last = first + 1
    set_timeline_range(first, last)
    return first, last


def set_padded_keys(obj_attr, frame, value):
    """
    Key a value on one frame and zero on the frames either side of it.

    For a trigger - a footstep sound, a one-frame effect - that has to be on for exactly one
    frame and off before and after, whatever the interpolation would otherwise do.

    :param pm.Attribute obj_attr: The attribute to key.
    :param float frame: The frame to put the value on.
    :param float value: The value.
    """

    obj_attr.set(value)
    pm.setKeyframe(obj_attr, time=[frame])

    keyed_frames = pm.keyframe(obj_attr, query=True) or []
    for neighbour in (frame - 1, frame + 1):
        if neighbour in keyed_frames:
            continue
        obj_attr.set(0)
        pm.setKeyframe(obj_attr, time=[neighbour])
    obj_attr.set(value)


def create_bookmark(name='timeSliderBookmark', frame_range=None, color=None):
    """
    Put a coloured marker on the timeline over a range of frames.

    :param str name: What to call it.
    :param frame_range: The frames it covers. :func:`get_times` decides otherwise. The last frame
        is not included, which is Maya's convention for these, not ours.
    :param color: Its colour, 0 to 1 per channel. A random one otherwise.
    :return: The bookmark node, or None when the plugin would not load.
    :rtype: pm.PyNode or None
    """

    # Imported and loaded here rather than at module level: this is the only function that needs
    # either, and the version this replaces made every importer of this module pay for both.
    from mca.mya.utils import plugins
    if not plugins.load_plugin(BOOKMARK_PLUGIN):
        logger.warning('The %s plugin would not load, so no bookmark was made.',
                       BOOKMARK_PLUGIN)
        return None

    try:
        from maya.plugin.timeSliderBookmark.timeSliderBookmark import createBookmark
    except ImportError as error:
        logger.warning('This Maya has no timeline bookmarks: %s', error)
        return None

    frame_range = frame_range or get_times()
    color = color or pymaths.create_random_list()
    return pm.PyNode(createBookmark(name=name, start=frame_range[0], stop=frame_range[1],
                                    color=color))
