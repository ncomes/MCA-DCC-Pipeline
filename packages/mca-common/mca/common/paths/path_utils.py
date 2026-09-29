"""
Walking folders, and turning a path into a project-relative one and back.

Four of these five functions had something wrong with them, and every one of the four was
the kind that answers *something* - so nothing ever raised and nobody found out:

- ``get_sub_dirs`` called itself for each subfolder and **threw the result away**, so a
  function documented to return a folder and all its subdirectories returned one level.
- ``all_folders_in_directory`` and ``all_files_in_directory`` matched a wanted name with
  ``in``, so asking for ``rig`` found ``rigging_old`` first, and returned a string when
  given a name and a list when not - so a caller had to know which it was going to be.
- ``to_relative_path`` and ``to_full_path`` split the path on the *last* occurrence of the
  project folder's name, so a path with the project name in it twice - ``E:/Wayward/art/
  Wayward/hero.ma``, which is exactly what an art folder named after the project looks like -
  came back as ``hero.ma``, silently missing a folder.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.paths import project_paths


logger = log.MCA_LOGGER


def get_sub_dirs(rootdir, recursive=True):
    """
    Every folder under a folder.

    :param str rootdir: Where to look.
    :param bool recursive: Walk all the way down. False answers one level, which is what the
        version this replaces actually did.
    :return: Folder paths.
    :rtype: list(str)
    """

    if not rootdir or not os.path.isdir(rootdir):
        return []

    found = []
    if not recursive:
        for name in sorted(os.listdir(rootdir)):
            path = os.path.join(rootdir, name)
            if os.path.isdir(path):
                found.append(os.path.normpath(path))
        return found

    for root, folders, _ in os.walk(rootdir):
        for name in sorted(folders):
            found.append(os.path.normpath(os.path.join(root, name)))
    return found


def all_folders_in_directory(rootdir, folder_name=None):
    """
    :param str rootdir: Where to look.
    :param str folder_name: Only folders with exactly this name.
    :return: Folder paths. Always a list, even when a name was given.
    :rtype: list(str)
    """

    if not rootdir or not os.path.isdir(rootdir):
        return []

    found = []
    for root, folders, _ in os.walk(rootdir):
        for name in sorted(folders):
            if folder_name and name != folder_name:
                continue
            found.append(os.path.normpath(os.path.join(root, name)))
    return found


def all_files_in_directory(rootdir, file_name=None):
    """
    :param str rootdir: Where to look.
    :param str file_name: Only files with exactly this name.
    :return: File paths. Always a list.
    :rtype: list(str)
    """

    if not rootdir or not os.path.isdir(rootdir):
        return []

    found = []
    for root, _, files in os.walk(rootdir):
        for name in sorted(files):
            if file_name and name != file_name:
                continue
            found.append(os.path.normpath(os.path.join(root, name)))
    return found


def all_file_types_in_directory(rootdir, file_ext):
    """
    :param str rootdir: Where to look.
    :param file_ext: An extension, or several. The leading dot is optional, and case does
        not matter - ``.MA`` on a scene from another machine is still a Maya scene.
    :return: File paths.
    :rtype: list(str)
    """

    if not rootdir or not os.path.isdir(rootdir) or not file_ext:
        return []

    wanted = [file_ext] if isinstance(file_ext, str) else list(file_ext)
    wanted = tuple('.' + one.lower().lstrip('.') for one in wanted if one)

    found = []
    for root, _, files in os.walk(rootdir):
        for name in sorted(files):
            if name.lower().endswith(wanted):
                found.append(os.path.normpath(os.path.join(root, name)))
    return found


def find_first(rootdir, name, folders=False):
    """
    The first thing called ``name`` under a folder, since that is what the two functions
    above were really being used for.

    :param str rootdir: Where to look.
    :param str name: The exact file or folder name.
    :param bool folders: Look for a folder rather than a file.
    :return: Its path, or ''.
    :rtype: str
    """

    found = (all_folders_in_directory(rootdir, name) if folders
             else all_files_in_directory(rootdir, name))
    return found[0] if found else ''


# ---------------------------------------------------------------------------- #
# Project relative
# ---------------------------------------------------------------------------- #
def to_relative_path(file_path, remove_path=None):
    """
    A path, relative to the project.

    :param str file_path: A full path.
    :param str remove_path: What it should be relative to. None uses the project root.
    :return: The relative path, or '' when there is nothing to answer. A path that is not
        under the root is answered unchanged, because silently returning its last few
        folders - which is what splitting on a name does - is worse than saying nothing
        happened.
    :rtype: str
    """

    if not file_path:
        return ''

    root = remove_path or project_paths.get_project_path()
    if not root:
        logger.debug('No project root, so %s cannot be made relative to one.', file_path)
        return os.path.normpath(file_path)

    full = os.path.normpath(file_path)
    root = os.path.normpath(root)
    try:
        # relpath, not a split on the folder's name: a project called Wayward with an art
        # folder called Wayward inside it used to lose everything up to the second one.
        relative = os.path.relpath(full, root)
    except ValueError:
        # Different drives on Windows.
        return full
    if relative.startswith(os.pardir):
        return full
    return relative


def to_full_path(file_path, added_path=None):
    """
    A project-relative path, made whole.

    :param str file_path: A relative path, or a full one.
    :param str added_path: The root to put in front. None uses the project root.
    :return: The full path, or '' when there is nothing to answer.
    :rtype: str
    """

    if not file_path:
        return ''

    root = added_path or project_paths.get_project_path()
    full = os.path.normpath(file_path)
    if not root:
        return full

    root = os.path.normpath(root)
    if os.path.isabs(full) or full.lower().startswith(root.lower()):
        return full
    return os.path.normpath(os.path.join(root, full))
