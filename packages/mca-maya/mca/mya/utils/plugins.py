"""
Loading and unloading Maya plugins, and telling Maya a folder's plugins are trusted.

What was wrong before:

- **``add_trusted_plugin_location_path`` raised when the option variable was not set yet.**
  ``pm.optionVar(query='SafeModeAllowedlistPaths')`` answers ``0`` - the integer - for an
  option variable that has never been written, and the next line did ``allowed_path in
  allowed_paths``, which is ``TypeError: argument of type 'int' is not iterable``. On a fresh
  Maya profile, the first call failed. The plugin loader calls it before every plugin it
  loads.
- **It also refused to do anything below Maya 2022** via
  ``mel.eval('getApplicationVersionAsFloat')``. 2022 is the oldest Maya the pipeline
  supports, so the check could only ever be true, and it was the only reason this module
  imported ``maya.mel``.
- **``get_float_version`` was a second copy** of the one in ``utils/maya_utils.py``, and
  nothing called either.
- **``unload_plugin`` answered False for a plugin that was not loaded**, which is the state
  the caller asked for. Callers could not tell "it is not loaded" from "it would not
  unload".
- **``load_plugin`` swallowed the reason it failed.** It logged only when ``quiet`` was
  False, and ``quiet`` defaults to True, so a plugin that would not load left nothing behind
  to say why. It logs at debug either way now, and the caller still gets its False.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: The option variable holding the folders Maya's safe mode will load plugins from.
TRUSTED_PATHS_OPTION_VARIABLE = 'SafeModeAllowedlistPaths'


def is_plugin_loaded(plugin_name):
    """
    :param str plugin_name: The plugin's name or path.
    :return: Whether it is loaded. False for a plugin Maya has never heard of, rather than
        an exception.
    :rtype: bool
    """

    try:
        return bool(cmds.pluginInfo(plugin_name, query=True, loaded=True))
    except RuntimeError:
        return False


def load_plugin(plugin_name, quiet=True):
    """
    Load a plugin, unless it is already loaded.

    :param str plugin_name: The plugin's name, or the full path to it.
    :param bool quiet: Keep Maya from writing its own notice to the script editor. It no
        longer decides whether the pipeline logs the failure - that always happens.
    :return: Whether the plugin is loaded now.
    :rtype: bool
    """

    if is_plugin_loaded(plugin_name):
        return True

    try:
        cmds.loadPlugin(plugin_name, quiet=quiet)
    except RuntimeError as error:
        # Always leave the reason behind. The version this replaces logged only when quiet
        # was False, which is not the default, so a failed load was silent.
        logger.warning('Could not load the plugin %s: %s', plugin_name, error)
        return False
    return True


def unload_plugin(plugin_name):
    """
    Unload a plugin.

    :param str plugin_name: The plugin's name. Maya wants the name here, not a path, which
        is why callers pass ``os.path.basename`` of what they loaded.
    :return: Whether the plugin is unloaded now - which is True for one that was never
        loaded. The version this replaces answered False for that, so callers could not tell
        it from a plugin that refused to unload.
    :rtype: bool
    """

    if not is_plugin_loaded(plugin_name):
        return True

    try:
        cmds.unloadPlugin(plugin_name)
    except RuntimeError as error:
        logger.warning('Could not unload the plugin %s: %s', plugin_name, error)
        return False
    return True


def add_trusted_plugin_location_path(allowed_path):
    """
    Tell Maya's safe mode that the plugins in a folder can be loaded.

    Without this, a Maya started in safe mode - which is what a machine does after Maya has
    crashed - refuses the pipeline's own compiled plugins, and the rigs that need them open
    broken.

    :param str allowed_path: The folder to trust.
    :return: True when the folder was added, False when it was already there or there was
        nothing to add.
    :rtype: bool
    """

    if not allowed_path:
        return False

    allowed_path = os.path.normpath(allowed_path)

    # optionVar answers 0 - the integer - for a variable that has never been written, and
    # `path in 0` is a TypeError. That is what happened on any fresh Maya profile.
    existing = cmds.optionVar(query=TRUSTED_PATHS_OPTION_VARIABLE)
    if not isinstance(existing, (list, tuple)):
        existing = []

    if allowed_path in [os.path.normpath(one) for one in existing]:
        return False

    cmds.optionVar(stringValueAppend=(TRUSTED_PATHS_OPTION_VARIABLE, allowed_path))
    return True
