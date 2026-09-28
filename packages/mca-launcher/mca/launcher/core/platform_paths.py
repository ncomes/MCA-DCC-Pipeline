"""
Everything that knows which operating system this is.

The old launcher imported ``winreg`` and ``ctypes.wintypes`` at module scope in its path
module, so the package could not be imported at all off Windows: no CI, no test that runs
anywhere but an artist's machine. Windows is still the only platform this ships on. The
difference is that the knowledge lives in one module, with a fallback, so everything else
is importable and testable everywhere.

Three environment variables override the locations, which is what lets a test run without
going anywhere near the real folders:

    MCA_PREFS_ROOT   where project preferences live  (default: Documents/mca_preferences)
    MCA_DEPS_ROOT    where DCC dependencies live     (default: %LOCALAPPDATA%/MCA/deps)
    MCA_LOGS_ROOT    where launcher logs go          (default: <prefs root>/logs)
"""

# python imports
import logging
import os
import sys


logger = logging.getLogger('mca-launcher')

#: The only place the platform is decided.
IS_WINDOWS = sys.platform.startswith('win')

#: Folder name used under the user's Documents folder.
PREFERENCES_FOLDER_NAME = 'mca_preferences'

#: Folder name used under the user's local application data.
APPLICATION_FOLDER_NAME = 'MCA'


def home_folder():
    """
    :return: The user's home folder.
    :rtype: str
    """

    return os.path.normpath(os.path.expanduser('~'))


def documents_folder():
    """
    The user's Documents folder, asked of Windows rather than assumed.

    ``~/Documents`` is a guess that is wrong on any machine where Documents has been
    redirected - to OneDrive, or to a second drive, both of which are common. Windows
    knows the answer, so it gets asked.

    :return: The Documents folder.
    :rtype: str
    """

    if IS_WINDOWS:
        try:
            import ctypes
            import ctypes.wintypes

            csidl_personal = 5          # My Documents
            shgfp_type_current = 0      # the current value, not the default one

            buffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(
                None, csidl_personal, None, shgfp_type_current, buffer)
            if buffer.value:
                return os.path.normpath(buffer.value)
            logger.warning('Windows returned an empty Documents path; falling back.')
        except Exception as error:
            logger.warning('Could not ask Windows for the Documents folder: %s', error)

    return os.path.normpath(os.path.join(home_folder(), 'Documents'))


def local_app_data():
    """
    Where per-machine, per-user data belongs - installed dependencies, in our case.

    :return: The local application data folder.
    :rtype: str
    """

    if IS_WINDOWS:
        folder = os.getenv('LOCALAPPDATA')
        if folder:
            return os.path.normpath(folder)
        return os.path.normpath(os.path.join(home_folder(), 'AppData', 'Local'))

    return os.path.normpath(os.getenv('XDG_DATA_HOME')
                            or os.path.join(home_folder(), '.local', 'share'))


def preferences_folder():
    """
    :return: The folder holding one subfolder of preferences per project.
    :rtype: str
    """

    override = os.getenv('MCA_PREFS_ROOT')
    if override:
        return os.path.normpath(override)
    return os.path.normpath(os.path.join(documents_folder(), PREFERENCES_FOLDER_NAME))


def dependencies_root():
    """
    Where dependencies are installed, one folder per DCC version.

    Deliberately outside the repository and outside the project. They are machine state,
    not source: built for one interpreter's ABI, wrong for another, and worth nothing to
    anybody who clones the code.

    :return: The dependencies root.
    :rtype: str
    """

    override = os.getenv('MCA_DEPS_ROOT')
    if override:
        return os.path.normpath(override)
    return os.path.normpath(os.path.join(local_app_data(), APPLICATION_FOLDER_NAME, 'deps'))


def logs_folder():
    """
    :return: Where launcher logs go. Created by the logging setup, not here.
    :rtype: str
    """

    override = os.getenv('MCA_LOGS_ROOT')
    if override:
        return os.path.normpath(override)
    return os.path.normpath(os.path.join(preferences_folder(), 'logs'))


def registry_value(sub_key, name, from_user=False):
    """
    Read one value from the Windows registry.

    :param str sub_key: The key, for example ``SOFTWARE\\Autodesk\\Maya\\2025``.
    :param str name: The value's name.
    :param bool from_user: Read HKEY_CURRENT_USER instead of HKEY_LOCAL_MACHINE.
    :return: The value, or None when it is not there or this is not Windows.
    :rtype: str or None
    """

    if not IS_WINDOWS:
        return None

    import winreg

    root = winreg.HKEY_CURRENT_USER if from_user else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(root, sub_key, 0, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        # Missing keys are the normal case - it is how "that version is not installed"
        # looks - so this is not worth a warning.
        return None
    except Exception as error:
        logger.warning('Could not read registry %s (%s): %s', sub_key, name, error)
        return None


def registry_sub_keys(sub_key, from_user=False):
    """
    List the child keys of a registry key.

    :param str sub_key: The parent key.
    :param bool from_user: Read HKEY_CURRENT_USER instead of HKEY_LOCAL_MACHINE.
    :return: The child key names, in registry order.
    :rtype: list(str)
    """

    if not IS_WINDOWS:
        return []

    import winreg

    root = winreg.HKEY_CURRENT_USER if from_user else winreg.HKEY_LOCAL_MACHINE
    names = []
    try:
        with winreg.OpenKey(root, sub_key, 0, winreg.KEY_READ) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
    except OSError:
        return []
    except Exception as error:
        logger.warning('Could not list registry %s: %s', sub_key, error)
        return []

    return names
