"""
Importing and exporting FBX.

Maya's FBX plugin has no Python interface worth the name: its settings are a hundred separate MEL
commands, one per option, each of which sets a global that the next ``FBXExport`` reads. So an
export is "set the twenty globals you care about, then export", and the globals stay set for
whatever runs next - which is why :func:`export_fbx` clears the take split again on its way out.

:func:`fbx_command` is the general door onto those commands; the ones the pipeline actually uses
have a named function each, because a call that reads ``FBXExportSkins(v=True)`` says what it
does and ``fbx_command('FBXExportSkins', v=True)`` does not.

What was wrong before:

- **``import_fbx`` raised a string.** ``raise f'File not found at: {fbx_path}'`` is
  ``TypeError: exceptions must derive from BaseException`` in Python 3 - so the one case it
  checked for reported the wrong thing, and the message it built was thrown away.
- **The MEL builder rewrote the caller's own text.** ``_FBXCmd`` turned Python's ``True`` and
  ``False`` into MEL's ``true`` and ``false`` by running ``str.replace`` over the whole
  command - arguments included - so exporting a clip named ``TrueGrit`` wrote
  ``trueGrit`` into the file. The booleans are converted where they are, now.
- **Ninety-odd one-line wrappers, three of them used.** Every FBX command in the plugin had a
  function here whether the pipeline called it or not; seventeen are called, one of those from
  outside this module. The rest are reachable through :func:`fbx_command`.
- ``load_fbx`` and ``assert_property`` checked their results with ``assert``, which Python
  removes entirely under ``-O``, and neither had a caller. Gone.
- ``from __future__ import print_function, division, absolute_import``, in a package that has
  been Python 3 only for years.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds
import maya.mel as mel
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import fileio
from mca.common.utils import lists
from mca.mya.animation import time_utils
from mca.mya.modifiers import ma_decorators
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The flags Maya's FBX commands take with no value after them.
VALUELESS_FLAGS = ('q', 'clear')


def _as_mel(value):
    """
    One Python value as the MEL literal for it.

    :param value: The value.
    :return: Its MEL spelling.
    :rtype: str
    """

    if isinstance(value, bool):
        # Converted here rather than by running str.replace over the finished command, which is
        # what the version this replaces did - and which rewrote the caller's own strings.
        return 'true' if value else 'false'
    if isinstance(value, str):
        return '"{}"'.format(value)
    return str(value)


def fbx_command(command_name, *args, **kwargs):
    """
    Call one of Maya's FBX MEL commands.

    :param str command_name: The command, such as ``'FBXExportSkins'``.
    :param args: Positional arguments, in the order the command wants them.
    :param kwargs: Flags. ``q`` and ``clear`` take no value; everything else does.
    :return: Whatever the command answered.
    """

    flags = []
    for key, value in kwargs.items():
        if key in VALUELESS_FLAGS:
            flags.append('-{}'.format(key))
        else:
            flags.append('-{} {}'.format(key, _as_mel(value)))

    positional = [_as_mel(one) for one in args]
    command = '{} {};'.format(command_name, ' '.join(flags + positional)).replace('  ', ' ')
    logger.debug('FBX: %s', command)
    return mel.eval(command)


# --------------------------------------------------------------------------------------- #
# the commands the pipeline uses
# --------------------------------------------------------------------------------------- #
def FBXImport(*args, **kwargs):                     # noqa: N802 - Maya's own spelling
    """Read an FBX file into the scene. ``f`` is the path, ``t`` the take, -1 for the last."""
    return fbx_command('FBXImport', *args, **kwargs)


def FBXExport(*args, **kwargs):                     # noqa: N802
    """Write an FBX file. ``f`` is the path, ``s`` exports the selection only."""
    return fbx_command('FBXExport', *args, **kwargs)


def FBXProperty(*args, **kwargs):                   # noqa: N802
    """Read or set one FBX property by its path, for anything with no command of its own."""
    return fbx_command('FBXProperty', *args, **kwargs)


def FBXImportMode(*args, **kwargs):                 # noqa: N802
    """``add``, ``merge`` or ``exmerge`` - what an import does with what is already there."""
    return fbx_command('FBXImportMode', *args, **kwargs)


def FBXImportShapes(*args, **kwargs):               # noqa: N802
    """Whether to bring in blend shapes."""
    return fbx_command('FBXImportShapes', *args, **kwargs)


def FBXImportSkins(*args, **kwargs):                # noqa: N802
    """Whether to bring in skin clusters."""
    return fbx_command('FBXImportSkins', *args, **kwargs)


def FBXImportCacheFile(*args, **kwargs):            # noqa: N802
    """Whether to bring in the point cache beside the file."""
    return fbx_command('FBXImportCacheFile', *args, **kwargs)


def FBXImportGenerateLog(*args, **kwargs):          # noqa: N802
    """Whether the plugin writes its own log file beside the scene."""
    return fbx_command('FBXImportGenerateLog', *args, **kwargs)


def FBXExportGenerateLog(*args, **kwargs):          # noqa: N802
    """Whether the plugin writes its own log file beside the scene."""
    return fbx_command('FBXExportGenerateLog', *args, **kwargs)


def FBXExportAnimationOnly(*args, **kwargs):        # noqa: N802
    """Whether to write the animation without the geometry it is on."""
    return fbx_command('FBXExportAnimationOnly', *args, **kwargs)


def FBXExportShapes(*args, **kwargs):               # noqa: N802
    """Whether to write blend shapes."""
    return fbx_command('FBXExportShapes', *args, **kwargs)


def FBXExportSkins(*args, **kwargs):                # noqa: N802
    """Whether to write skin weights."""
    return fbx_command('FBXExportSkins', *args, **kwargs)


def FBXExportSmoothingGroups(*args, **kwargs):      # noqa: N802
    """Whether to write the mesh's smoothing groups, which the engine needs for hard edges."""
    return fbx_command('FBXExportSmoothingGroups', *args, **kwargs)


def FBXExportTriangulate(*args, **kwargs):          # noqa: N802
    """Whether to triangulate the mesh on the way out."""
    return fbx_command('FBXExportTriangulate', *args, **kwargs)


def FBXExportSplitAnimationIntoTakes(*args, **kwargs):     # noqa: N802
    """
    Declare a named clip over a frame range, or - with ``clear=True`` - forget every clip
    declared so far.

    The declarations are a global in the plugin and outlive the export, which is why every
    exporter has to clear them on the way in and on the way out.
    """
    return fbx_command('FBXExportSplitAnimationIntoTakes', *args, **kwargs)


def FBXExportDeleteOriginalTakeOnSplitAnimation(*args, **kwargs):   # noqa: N802
    """Whether the whole-timeline take is dropped once the named clips are written."""
    return fbx_command('FBXExportDeleteOriginalTakeOnSplitAnimation', *args, **kwargs)


def FBXExportBakeComplexStart(*args, **kwargs):     # noqa: N802
    """The first frame the plugin bakes to keys on the way out."""
    return fbx_command('FBXExportBakeComplexStart', *args, **kwargs)


def FBXExportBakeComplexEnd(*args, **kwargs):       # noqa: N802
    """The last frame the plugin bakes to keys on the way out."""
    return fbx_command('FBXExportBakeComplexEnd', *args, **kwargs)


# --------------------------------------------------------------------------------------- #
# what the pipeline actually calls
# --------------------------------------------------------------------------------------- #
@ma_decorators.keep_namespace_decorator
def import_fbx(fbx_path, import_namespace=None):
    """
    Read an FBX file into the scene.

    Only the last animation clip in the file comes in: the FBX format allows several, and nothing
    in this pipeline writes more than one.

    :param str fbx_path: The file.
    :param str import_namespace: Move everything it brought in into this namespace.
    :return: The nodes that arrived.
    :rtype: list(pm.PyNode)
    :raises IOError: When the file is not there. The version this replaces raised the *message*,
        which in Python 3 is ``TypeError: exceptions must derive from BaseException``.
    """

    if not os.path.exists(fbx_path):
        raise IOError('There is no FBX file at {}.'.format(fbx_path))

    # The plugin wants forward slashes whatever the platform.
    formatted_path = os.path.normpath(fbx_path).replace('\\', '/')

    # From the root namespace, or the nodes arrive somewhere nobody asked for.
    cmds.namespace(setNamespace=':')
    before = set(pm.ls('*'))

    FBXImportMode(v='add')
    FBXImportShapes(v=True)
    FBXImportSkins(v=True)
    FBXImportCacheFile(v=True)
    FBXImportGenerateLog(v=False)
    FBXImport(f=formatted_path, t=-1)

    arrived = list(set(pm.ls('*')) - before)
    if import_namespace:
        for node in arrived:
            namespace.move_node_to_namespace(node, import_namespace)
    return arrived


def export_fbx(fbx_path, node_list, clip_name=None, start_frame=None, end_frame=None):
    """
    Write nodes out to an FBX file.

    :param str fbx_path: Where to write it. The folders are made if they are not there.
    :param node_list: What to write.
    :param str clip_name: Write the animation as a named clip. The FBX format allows several
        clips in one file; this writes one.
    :param float start_frame: The clip's first frame. :func:`time_utils.get_times` decides
        otherwise.
    :param float end_frame: The clip's last frame.
    :return: Whether the file was written.
    :rtype: bool
    """

    nodes = lists.force_list(node_list or [])
    if not nodes:
        logger.warning('There is nothing to export to %s.', fbx_path)
        return False

    fileio.touch_path(fbx_path)
    formatted_path = os.path.normpath(fbx_path).replace('\\', '/')

    FBXExportGenerateLog(v=False)
    FBXExportAnimationOnly(v=False)
    FBXExportShapes(v=True)
    FBXExportSkins(v=True)
    FBXExportSmoothingGroups(v=True)
    # Whatever a previous export left declared is not this export's business.
    FBXExportSplitAnimationIntoTakes(clear=True)
    FBXExportDeleteOriginalTakeOnSplitAnimation(v=True)

    if clip_name:
        if start_frame is None or end_frame is None:
            time_range = time_utils.get_times(node_list=nodes)
            start_frame = time_range[0] if start_frame is None else start_frame
            end_frame = time_range[1] if end_frame is None else end_frame
        FBXExportBakeComplexStart(v=start_frame)
        FBXExportBakeComplexEnd(v=end_frame)
        FBXExportSplitAnimationIntoTakes(start_frame, end_frame, v=clip_name)

    pm.select(nodes, replace=True)
    try:
        FBXExport(f=formatted_path, s=True)
    except RuntimeError as error:
        logger.error('Could not write %s: %s', formatted_path, error)
        return False
    finally:
        # The declarations are a global in the plugin; left set, they end up in whatever the next
        # exporter writes.
        FBXExportSplitAnimationIntoTakes(clear=True)

    return os.path.isfile(formatted_path)
