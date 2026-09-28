"""
Reading and writing the launcher's own small files.

Two rules here, both learned from preference files that went missing:

- **A read never raises for a file that is not there.** "No preferences yet" is the normal
  state on a new machine, not an error, and the old ``os.stat`` before the existence check
  turned it into a traceback.
- **A write is atomic.** Preferences are written on window close, and a crash or a power
  cut halfway through a ``yaml.dump`` leaves a truncated file that reads back as garbage
  and loses every project the artist had set up. Writing a temporary file beside the real
  one and renaming it means the file is either the old one or the new one.
"""

# python imports
import json
import logging
import os
import tempfile

# third party imports
import yaml


logger = logging.getLogger('mca-launcher')


def _atomic_write(path, text):
    """
    Write text to a path, atomically.

    :param str path: The file to write.
    :param str text: Its whole contents.
    :return: The path written.
    :rtype: str
    """

    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    handle, temporary = tempfile.mkstemp(dir=folder or None, prefix='.mca-', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as opened:
            opened.write(text)
        os.replace(temporary, path)     # atomic on Windows and POSIX alike
    except Exception:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
        raise

    return path


def read_yaml(path, default=None):
    """
    Read a YAML file.

    :param str path: The file.
    :param default: What to answer when the file is missing, empty or unreadable.
    :return: The data, or the default.
    """

    if not path or not os.path.isfile(path):
        return default

    try:
        with open(path, 'r', encoding='utf-8') as opened:
            data = yaml.safe_load(opened)
    except Exception as error:
        logger.warning('Could not read %s: %s', path, error)
        return default

    return default if data is None else data


def write_yaml(data, path):
    """
    Write a YAML file.

    :param data: What to write.
    :param str path: Where to write it.
    :return: The path, or None when it could not be written.
    :rtype: str or None
    """

    try:
        text = yaml.safe_dump(data, default_flow_style=False, width=200, sort_keys=True)
    except yaml.YAMLError as error:
        logger.error('Could not turn the data into YAML for %s: %s', path, error)
        return None

    try:
        return _atomic_write(path, text)
    except Exception as error:
        logger.error('Could not write %s: %s', path, error)
        return None


def read_json(path, default=None):
    """
    Read a JSON file. Used for machine-written state, where key order and comments are
    beside the point and a strict parser is a feature.

    :param str path: The file.
    :param default: What to answer when the file is missing or unreadable.
    :return: The data, or the default.
    """

    if not path or not os.path.isfile(path):
        return default

    try:
        with open(path, 'r', encoding='utf-8') as opened:
            return json.load(opened)
    except Exception as error:
        logger.warning('Could not read %s: %s', path, error)
        return default


def write_json(data, path):
    """
    Write a JSON file.

    :param data: What to write.
    :param str path: Where to write it.
    :return: The path, or None when it could not be written.
    :rtype: str or None
    """

    try:
        text = json.dumps(data, indent=2, sort_keys=True) + '\n'
    except (TypeError, ValueError) as error:
        logger.error('Could not turn the data into JSON for %s: %s', path, error)
        return None

    try:
        return _atomic_write(path, text)
    except Exception as error:
        logger.error('Could not write %s: %s', path, error)
        return None
