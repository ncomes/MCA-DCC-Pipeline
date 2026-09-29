"""
Small Python helpers that did not fit anywhere else.

``get_user_display_name`` called ``ctypes.windll`` with no check and no fallback, so it
raised ``AttributeError`` on anything that is not Windows - including the test suite, which
is why it had never been run.

``ObjectDict`` had a trap in it: reading a nested dictionary answered a **copy**, so

    settings.window.width = 800

set a value on a temporary object and threw it away. It answers a view onto the same data
now, so writing through it writes.
"""

# python imports
import os

# mca imports
from mca.common.utils import platforms


def get_user_display_name():
    """
    :return: The user's full name from Windows, or their account name anywhere else.
    :rtype: str
    """

    if platforms.IS_WINDOWS:
        try:
            import ctypes

            name_display = 3
            size = ctypes.pointer(ctypes.c_ulong(0))
            ctypes.windll.secur32.GetUserNameExW(name_display, None, size)
            buffer = ctypes.create_unicode_buffer(size.contents.value)
            ctypes.windll.secur32.GetUserNameExW(name_display, buffer, size)
            if buffer.value:
                return buffer.value
        except Exception:                                            # noqa: BLE001
            pass
    return platforms.user_name()


def split_path(path):
    """
    :param str path: A path.
    :return: Its folder, its name without the extension, and the extension.
    :rtype: tuple(str, str, str)
    """

    normalised = os.path.normpath(str(path or ''))
    without_extension, extension = os.path.splitext(normalised)
    return os.path.dirname(without_extension), os.path.basename(without_extension), extension


def append_path_env_var(name, value, skip_if_exists=True):
    """
    Add a path to the end of an environment variable.

    :param str name: The variable.
    :param str value: The path to add.
    :param bool skip_if_exists: Do nothing when it is already in there.
    :return: The variable's new value.
    :rtype: str
    """

    value = str(value or '')
    if not value:
        return os.environ.get(name, '')

    current = os.environ.get(name) or ''
    if not current:
        os.environ[name] = value
        return value

    if skip_if_exists and value in current.split(os.pathsep):
        return current

    current = '{}{}{}'.format(current, os.pathsep, value)
    os.environ[name] = current
    return current


def prepend_path_env_var(name, value, skip_if_exists=True):
    """
    Add a path to the front of an environment variable, where it wins.

    :param str name: The variable.
    :param str value: The path to add.
    :param bool skip_if_exists: Do nothing when it is already in there.
    :return: The variable's new value.
    :rtype: str
    """

    value = str(value or '')
    if not value:
        return os.environ.get(name, '')

    parts = [one for one in (os.environ.get(name) or '').split(os.pathsep) if one]
    if value in parts:
        if skip_if_exists:
            return os.pathsep.join(parts)
        parts.remove(value)

    parts.insert(0, value)
    joined = os.pathsep.join(parts)
    os.environ[name] = joined
    return joined


class ObjectDict(dict):
    """
    A dictionary whose keys can be read and written as attributes.

        settings = ObjectDict({'window': {'width': 800}})
        settings.window.width = 1024      # really changes it

    The version this replaces answered a new ObjectDict for a nested dictionary, so that
    last line wrote to something nobody kept.
    """

    def __getattr__(self, item):
        try:
            value = self[item]
        except KeyError:
            raise AttributeError(item)

        if isinstance(value, dict) and not isinstance(value, ObjectDict):
            # Wrap in place and put it back, so this is a view of the same data rather than
            # a copy of it.
            value = ObjectDict(value)
            self[item] = value
        return value

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, item):
        try:
            del self[item]
        except KeyError:
            raise AttributeError(item)
