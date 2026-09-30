"""
The Maya scene file itself, and source control.

Maya is happy to let somebody work for an hour in a file they cannot save, and only says so
when they try. This is the "check this file out before I start" the menu offers.

What was wrong before:

- **The one function in it named three different source control systems.** Its docstring said
  "Attempts to check out the file in plastic", the menu entry calling it said "SVN Check Out",
  and the icon beside that entry was ``p4v.png``. The studio uses Perforce. Source control is
  behind an interface now - :mod:`mca.common.sourcecontrol` - so there is one name for it and
  nothing here has to know which one is in use.
- ``fileio.touch_and_checkout`` does not exist any more: ``mca-common`` splits the two halves,
  because "make the file writable" and "tell source control" are different operations that
  fail for different reasons and a caller usually wants to know which one went wrong.
- The module docstring said "Module that contains the mca decorators at a base python level".
"""

# python imports

# software specific imports
import maya.cmds as cmds

# mca imports
from mca.common import log
from mca.common import sourcecontrol
from mca.common.utils import fileio


logger = log.MCA_LOGGER


def current_scene_path():
    """
    :return: The scene file's path, or '' for a scene that has never been saved.
    :rtype: str
    """

    return cmds.file(query=True, sceneName=True) or ''


def checkout_current_scene(checkout=True, remove=False):
    """
    Make the open scene writable, and tell source control it is being worked on.

    :param bool checkout: Check the file out. False only makes it writable, which is what
        somebody wants when they are about to save over a file source control does not hold.
    :param bool remove: Delete the file first. For the case where the file on disk is in a
        state Maya cannot open and is about to be replaced wholesale.
    :return: Whether the file is ready to be saved over.
    :rtype: bool
    """

    path = current_scene_path()
    if not path:
        logger.warning('This scene has never been saved, so there is no file to check out.')
        return False

    fileio.touch_path(path, remove=remove)
    if not checkout:
        return True

    result = sourcecontrol.checkout(path)
    if not result.ok:
        logger.warning('Could not check out %s: %s', path, result.message)
    return bool(result.ok)
