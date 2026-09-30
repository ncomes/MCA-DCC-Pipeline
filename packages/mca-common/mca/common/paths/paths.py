"""
Where a project keeps its things.

Thirty-odd functions, each of which was some arrangement of
``os.path.normpath(os.path.join(os.getenv(SOMETHING), 'Folder'))``. Two things were wrong
with all of them at once:

- **A variable that is not set raised.** ``os.getenv`` answers None, and both
  ``os.path.join(None, ...)`` and ``os.path.normpath(None)`` raise TypeError - so on a
  machine where the project is not fully set up, or in Unreal, which is handed fewer of
  these than Maya is, asking for the icons folder raised out of a function documented to
  return a path. Every one of them answers '' now, and says once, at debug level, which
  variable was empty.
- **Two of them read a snapshot.** ``project_root()`` and ``get_cine_path()`` used
  ``project_paths.MCA_PROJECT_ROOT``, read at import time, while
  ``get_common_tools_path()`` two functions above carried a comment explaining why that is
  wrong and read the environment instead. The bug was known, fixed in one place, and left
  in the other two.

The docstrings were copied along with the code: eight of these said "Returns the path to the
face data folder" while returning icons, images, movies or stylesheets.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.paths import path_utils, project_paths
from mca.common.startup.configs import consts
from mca.common.utils import dcc_util


logger = log.MCA_LOGGER

# NOTE: mca.common.assetlist is deliberately not imported here. The asset manager imports
# this module, so a module-level import either way round is circular. The asset functions
# below import it when they are called.


def from_env(variable, *parts):
    """
    A path built from an environment variable, or '' when it is not set.

    :param str variable: The variable's name.
    :param parts: Folders to add to it.
    :return: The path, normalised, or ''.
    :rtype: str
    """

    root = os.getenv(variable)
    if not root:
        logger.debug('%s is not set, so there is no path to answer.', variable)
        return ''
    return os.path.normpath(os.path.join(root, *[str(part) for part in parts if part]))


def under(root, *parts):
    """
    A path under another one, or '' when there is no other one.

    :param str root: The folder to build on. '' answers ''.
    :param parts: Folders to add.
    :return: The path, or ''.
    :rtype: str
    """

    if not root:
        return ''
    return os.path.normpath(os.path.join(root, *[str(part) for part in parts if part]))


# ---------------------------------------------------------------------------- #
# The project
# ---------------------------------------------------------------------------- #
def project_root():
    """
    :return: The project root, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_PROJECT_ROOT)


def get_common_tools_path():
    """
    :return: The project's shared tools folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_PROJECT_ROOT, 'Tools', 'Common', 'Tools')


def get_common_path():
    """
    :return: The shared tools folder the project's preferences name, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_COMMON_TOOLS)


def get_characters_path():
    """
    :return: The characters folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_CHARACTERS_PATH)


def get_gear_path():
    """
    :return: The gear asset lists folder, or ''.
    :rtype: str
    """

    return under(get_asset_lists_path(), 'Gear')


def get_dcc_tools_path(dcc=None):
    """
    :param str dcc: A DCC name. None asks which one this is.
    :return: The shared tools folder for that DCC, or ''.
    :rtype: str
    """

    return under(get_common_tools_path(), dcc_util.display_name(dcc))


# ---------------------------------------------------------------------------- #
# Preferences
# ---------------------------------------------------------------------------- #
def get_local_preferences_folder():
    """
    :return: This project's preferences folder.
    :rtype: str
    """

    return project_paths.get_local_preferences_folder()


def get_dcc_prefs_folder(dcc):
    """
    :param str dcc: A DCC name.
    :return: Where that DCC's preferences live.
    :rtype: str
    """

    return under(get_local_preferences_folder(), 'prefs', dcc)


def get_local_tools_prefs_folder(dcc, tool_name, create=True):
    """
    Where one tool keeps its preferences.

    :param str dcc: A DCC name.
    :param str tool_name: The tool's folder name.
    :param bool create: Make the folder. True by default, because that is what this did and
        what its callers expect - a "get" with a side effect, said out loud.
    :return: The folder, or '' when there is nowhere to put it.
    :rtype: str
    """

    folder = under(get_dcc_prefs_folder(dcc), tool_name)
    if folder and create and not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except OSError as error:
            logger.warning('Could not create %s: %s', folder, error)
            return ''
    return folder


# ---------------------------------------------------------------------------- #
# Asset lists
# ---------------------------------------------------------------------------- #
def get_asset_list_path():
    """
    :return: The asset list folder, or ''.
    :rtype: str
    """

    return under(get_common_tools_path(), 'Assetlist')


def get_asset_lists_path():
    """
    :return: The folder holding the individual asset lists, or ''.
    :rtype: str
    """

    return under(get_asset_list_path(), 'Assetlists')


def get_categories_manifest_path():
    """
    :return: The file listing the project's asset categories, or ''. It is the name the file
        on disk actually has - ``categories.json`` - which this answered as
        ``categories.manifest`` for one commit, so nothing in the registry loaded at all.
    :rtype: str
    """

    return under(get_asset_list_path(), 'categories.json')


def get_asset_list_file_path():
    """
    :return: The asset list file, or ''.
    :rtype: str
    """

    return under(get_asset_lists_path(), 'assetlist.alist')


# ---------------------------------------------------------------------------- #
# Shared art
# ---------------------------------------------------------------------------- #
def get_common_face():
    """
    :return: The shared face folder, or ''.
    :rtype: str
    """

    return under(get_common_path(), 'Face')


def get_common_source_heads():
    """
    :return: The shared source heads folder, or ''.
    :rtype: str
    """

    return under(get_common_face(), 'SourceHeads')


def get_common_skinning():
    """
    :return: The shared skinning folder, or ''.
    :rtype: str
    """

    return under(get_common_path(), 'Skinning')


def get_common_sounds():
    """
    :return: The shared sounds folder, or ''.
    :rtype: str
    """

    return under(get_common_path(), 'Sounds')


def get_common_skeletons():
    """
    :return: The shared skeletons folder, or ''.
    :rtype: str
    """

    return under(get_common_path(), 'Skeletons')


def get_common_face_skeletons():
    """
    :return: The shared face skeletons folder, or ''.
    :rtype: str
    """

    return under(get_common_skeletons(), 'Face')


# ---------------------------------------------------------------------------- #
# Resources that ship with the framework
# ---------------------------------------------------------------------------- #
def get_resources_path():
    """
    :return: The framework's resources folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_RESOURCES_PATH)


def get_icons_path():
    """
    :return: The framework's icons folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_ICONS_PATH)


def get_images_path():
    """
    :return: The framework's images folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_IMAGES_PATH)


def get_movies_path():
    """
    :return: The framework's animations folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_MOVIES_PATH)


def get_stylesheet_path():
    """
    :return: The framework's stylesheets folder, or ''.
    :rtype: str
    """

    return from_env(consts.MCA_STYLES_PATH)


def get_common_resources_path():
    """
    :return: The project's own resources folder, beside its shared tools, or ''.
    :rtype: str
    """

    return under(get_common_tools_path(), 'Resources')


def get_common_icons_path():
    """
    :return: The project's own icons folder, or ''.
    :rtype: str
    """

    return under(get_common_resources_path(), 'Icons')


# ---------------------------------------------------------------------------- #
# Cinematics
# ---------------------------------------------------------------------------- #
def get_cine_path():
    """
    :return: The project's cinematics folder, or ''.
    :rtype: str
    """

    # from_env, not the module-level snapshot this used to read: switching project left it
    # pointing at the old one for the rest of the session.
    return from_env(consts.MCA_PROJECT_ROOT, 'Cinematics')


def get_cine_seq_path():
    """
    :return: The cinematic sequences folder, or ''.
    :rtype: str
    """

    return under(get_cine_path(), 'Sequences')


def get_cine_seq_dir(seq_name, cinematic_name=None):
    """
    One sequence's folder.

    :param str seq_name: The sequence, for example 'INTRO_A1'.
    :param str cinematic_name: The cinematic it belongs to, when there is one. Without it,
        the older layout - sequences directly under Sequences - is kept, so callers that do
        not thread the name through still work.
    :return: The folder, or ''.
    :rtype: str
    """

    base = get_cine_seq_path()
    if cinematic_name and str(cinematic_name).strip():
        return under(base, str(cinematic_name).strip(), seq_name)
    return under(base, seq_name)


# ---------------------------------------------------------------------------- #
# One asset
# ---------------------------------------------------------------------------- #
def _get_asset_record(asset_id):
    """
    Look an asset up through the asset manager.

    Imported here rather than at the top: the asset manager imports this module, so either
    module-level import would be circular.

    :param str asset_id: The asset's id.
    :return: The record, or None when the id is unknown or the asset list is not available.
    """

    try:
        from mca.common.assetlist import asset_manager
    except ImportError as error:
        logger.debug('The asset list is not available here: %s', error)
        return None

    try:
        return asset_manager.get_asset_manager().get_record(asset_id)
    except Exception as error:                                       # noqa: BLE001
        logger.warning('Could not look up the asset %s: %s', asset_id, error)
        return None


def get_asset_path(asset_id, full_path=False):
    """
    :param str asset_id: The asset's id.
    :param bool full_path: The whole path rather than one relative to the project.
    :return: The asset's folder, or ''.
    :rtype: str
    """

    record = _get_asset_record(asset_id)
    path = getattr(record, 'full_path', '') if record else ''
    if not path:
        return ''
    return path if full_path else path_utils.to_relative_path(path)


def get_asset_rig_path(asset_id):
    """
    :param str asset_id: The asset's id.
    :return: Its rigs folder, or ''.
    :rtype: str
    """

    record = _get_asset_record(asset_id)
    return getattr(record, 'rigs_path', '') or '' if record else ''


def get_asset_animations_path(asset_id):
    """
    :param str asset_id: The asset's id.
    :return: Its animations folder, or ''.
    :rtype: str
    """

    record = _get_asset_record(asset_id)
    return getattr(record, 'animations_path', '') or '' if record else ''


def get_asset_skin_data_path(asset_id):
    """
    :param str asset_id: The asset's id.
    :return: Its skinning data folder, or ''.
    :rtype: str
    """

    record = _get_asset_record(asset_id)
    return getattr(record, 'skin_data_path', '') or '' if record else ''


def get_face_data_path(asset_id):
    """
    :param str asset_id: The asset's id.
    :return: Its face data folder, or ''.
    :rtype: str
    """

    return under(get_asset_rig_path(asset_id), 'Face_Data')


def get_face_blendshape_path(asset_id):
    """
    :param str asset_id: The asset's id.
    :return: Its blendshape folder, or ''.
    :rtype: str
    """

    return under(get_face_data_path(asset_id), 'Blendshapes')


def get_asset_maya_rig_file_path(asset_id):
    """
    The asset's rig scene.

    What the record says, when it says anything; otherwise the newest ``*_rig.ma`` in its
    rigs folder.

    :param str asset_id: The asset's id.
    :return: The file, or ''.
    :rtype: str
    """

    record = _get_asset_record(asset_id)
    if not record:
        return ''

    resolve = getattr(record, 'resolve_file', None)
    if callable(resolve):
        try:
            recorded = resolve('rig')
        except Exception as error:                                   # noqa: BLE001
            logger.debug('The asset %s could not resolve its rig file: %s', asset_id, error)
            recorded = ''
        if recorded:
            return recorded

    rigs = get_asset_rig_path(asset_id)
    if not rigs:
        return ''
    found = [one for one in path_utils.all_file_types_in_directory(rigs, '.ma')
             if one.lower().endswith('_rig.ma')]
    return found[0] if found else ''
