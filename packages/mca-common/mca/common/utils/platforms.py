"""
The handful of things that depend on which operating system this is.

A leaf: it imports nothing from the framework, not even the logger, so anything may import it
without thinking about order. The version this replaces had ``import ctypes.wintypes`` at the
top of ``project_paths``, which meant that module - and everything that imported it - could
not be imported at all off Windows, and so could never be tested anywhere else.
"""

# python imports
import os
import sys


#: Whether this is Windows, asked once.
IS_WINDOWS = sys.platform.startswith('win')

#: Folder ids for SHGetFolderPathW.
CSIDL_PERSONAL = 5              # Documents
CSIDL_DESKTOP_DIRECTORY = 16    # the Desktop folder itself, not the virtual desktop
CSIDL_LOCAL_APPDATA = 28        # AppData\Local


def home_folder():
    """
    :return: The user's home folder.
    :rtype: str
    """

    return os.path.normpath(os.path.expanduser('~'))


def known_folder(folder_id, fallback):
    """
    Ask Windows where one of its folders actually is.

    Documents, Desktop and the rest are routinely redirected - to OneDrive, to a second
    drive, to a network share - so ``~/Documents`` is a guess that is wrong on a lot of
    machines, including most of the ones with a OneDrive sign-in.

    :param int folder_id: A CSIDL value.
    :param str fallback: What to answer when Windows cannot be asked.
    :return: The folder.
    :rtype: str
    """

    if not IS_WINDOWS:
        return os.path.normpath(fallback)

    try:
        import ctypes
        import ctypes.wintypes

        buffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, folder_id, None, 0, buffer)
        if buffer.value:
            return os.path.normpath(buffer.value)
    except Exception:                                                # noqa: BLE001
        # Not knowing where Documents is must never stop a DCC starting, and this module
        # has no logger to complain to on purpose.
        pass
    return os.path.normpath(fallback)


def documents_folder():
    """
    :return: The user's Documents folder.
    :rtype: str
    """

    return known_folder(CSIDL_PERSONAL, os.path.join(home_folder(), 'Documents'))


def desktop_folder():
    """
    :return: The user's Desktop folder.
    :rtype: str
    """

    return known_folder(CSIDL_DESKTOP_DIRECTORY, os.path.join(home_folder(), 'Desktop'))


def local_app_data():
    """
    :return: Where per-user, per-machine data belongs.
    :rtype: str
    """

    if IS_WINDOWS:
        folder = os.getenv('LOCALAPPDATA')
        if folder:
            return os.path.normpath(folder)
        return known_folder(CSIDL_LOCAL_APPDATA,
                            os.path.join(home_folder(), 'AppData', 'Local'))
    return os.path.normpath(os.getenv('XDG_DATA_HOME') or
                            os.path.join(home_folder(), '.local', 'share'))


def user_name():
    """
    :return: Who is logged in, by whichever way works here.
    :rtype: str
    """

    try:
        return os.getlogin()
    except OSError:
        return os.getenv('USERNAME') or os.getenv('USER') or 'unknown'
