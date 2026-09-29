"""
Files: reading them, writing them, moving them, and telling you about them.

Plain file operations and nothing else. The version this replaces imported
``mca.common.p4v.perforce`` at module scope, so nothing could read a text file without
Perforce being importable - and checking a file out is not a file operation anyway. That
lives with source control now, which depends on this rather than the other way round.

What else changed, all of it found by reading:

- **Text is UTF-8, said out loud.** Nothing specified an encoding, so every read and write
  used the machine's code page - cp1252 inside Maya. A name with an accent in it wrote in
  Maya and would not read back in Unreal.
- ``get_last_modified_date`` read the **access** time, not the modified time, and padded
  single-digit seconds on the wrong side, so five seconds past the minute printed as ``:50``.
- ``write_line(append=True)`` built the line it meant to append and then wrote a different
  one: the variable was never used.
- ``replace`` deleted the original before moving the new file into place, so a failure at
  that moment lost the file. It writes beside the original and replaces it in one step now.
- ``copy_file`` joined the file name onto its destination whenever the destination existed,
  including when the destination was an existing file, which produced a path like
  ``C:/x/old.ma/new.ma``.
- ``get_file_timestamp_in_utc`` pulled in ``pytz`` for something the standard library does.
"""

# python imports
import datetime
import errno
import os
import shutil
import stat
import subprocess
import sys
import time

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: Everything the pipeline writes is UTF-8, whatever the machine's code page says.
ENCODING = 'utf-8'

#: Not allowed in a Windows file name, and a good idea to keep out of any file name.
ILLEGAL_CHARACTERS = '\\/:*?"<>|'


def safe_file_name(name, replacement='_'):
    """
    A file name with nothing in it the file system will refuse.

    :param str name: The name wanted.
    :param str replacement: What to put in place of anything illegal.
    :return: A name that can be written.
    :rtype: str
    """

    cleaned = str(name or '').strip()
    for character in ILLEGAL_CHARACTERS:
        cleaned = cleaned.replace(character, replacement)
    # Trailing dots and spaces are legal to type and impossible to open on Windows.
    return cleaned.rstrip(' .') or 'untitled'


def make_writable(path):
    """
    Clear the read-only bit, which is how every file arrives out of Perforce.

    :param str path: A file.
    :return: Whether it is now writable.
    :rtype: bool
    """

    if not os.path.isfile(path):
        return False
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        return True
    except OSError as error:
        logger.warning('Could not make %s writable: %s', path, error)
        return False


def touch_path(path, remove=False):
    """
    Make a path usable: its folder exists, and the file itself is writable.

    :param str path: A file or folder path.
    :param bool remove: Delete the file if it is there.
    :return: The path.
    :rtype: str
    """

    folder = os.path.dirname(path) or '.'
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except OSError as error:
            # Another process creating it first is not a failure.
            if error.errno != errno.EEXIST:
                raise

    if os.path.isfile(path):
        make_writable(path)
        if remove:
            os.remove(path)
            # The old version slept 2ms here. Windows really can report a deleted file as
            # still present for an instant, so the wait stays - but it waits for the fact
            # rather than for a guess at how long it takes.
            for _ in range(50):
                if not os.path.exists(path):
                    break
                time.sleep(0.002)
    return path


def explore_to_path(file_path):
    """
    Open the folder holding a path in the machine's file browser.

    :param str file_path: A file or folder.
    :return: Whether a browser was started.
    :rtype: bool
    """

    folder = file_path if os.path.isdir(file_path) else os.path.dirname(file_path)
    if not os.path.isdir(folder):
        logger.warning('There is no folder at %s to open.', folder)
        return False

    try:
        if sys.platform.startswith('win'):
            os.startfile(folder)                                     # noqa: S606
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
        return True
    except Exception as error:                                       # noqa: BLE001
        logger.warning('Could not open %s: %s', folder, error)
        return False


# ---------------------------------------------------------------------------- #
# Reading
# ---------------------------------------------------------------------------- #
def get_file_text(file_path, default=''):
    """
    The whole of a text file, as one string.

    :param str file_path: The file.
    :param str default: What to answer when it cannot be read.
    :return: Its text.
    :rtype: str
    """

    if not os.path.isfile(file_path):
        return default
    try:
        with open(file_path, 'r', encoding=ENCODING, errors='replace') as opened:
            return opened.read()
    except OSError as error:
        logger.warning('Could not read %s: %s', file_path, error)
        return default


def get_file_lines(file_path):
    """
    :param str file_path: The file.
    :return: Its lines, with no line endings on them and no trailing blank line.
    :rtype: list(str)
    """

    text = get_file_text(file_path)
    if not text:
        return []
    return text.replace('\r\n', '\n').replace('\r', '\n').split('\n')


def get_file_size(file_path, round_value=2):
    """
    :param str file_path: The file.
    :param int round_value: Decimal places.
    :return: Its size in megabytes, or 0.0 when it is not there.
    :rtype: float
    """

    if not os.path.isfile(file_path):
        return 0.0
    return round(os.path.getsize(file_path) / 1000000.0, round_value)


def get_file_timestamp_in_utc(file_path):
    """
    :param str file_path: The file.
    :return: When it was last modified, in UTC, or None when it is not there.
    :rtype: datetime.datetime or None
    """

    if not os.path.exists(file_path):
        return None
    return datetime.datetime.fromtimestamp(os.path.getmtime(file_path),
                                           tz=datetime.timezone.utc)


def get_last_modified_date(file_path, reverse_date=False):
    """
    When a file was last modified, for a person to read.

    :param str file_path: The file.
    :param bool reverse_date: Year first rather than day first.
    :return: ``'29-09-2026  14:05:07'``, or '' when the file is not there.
    :rtype: str
    """

    if not os.path.exists(file_path):
        return ''
    # getmtime, not getatime: the old version asked for the access time under this name,
    # which on a folder full of files that have merely been read is not the same date at all.
    when = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
    date = ('{:04d}-{:02d}-{:02d}' if reverse_date else '{2:02d}-{1:02d}-{0:04d}').format(
        when.year, when.month, when.day)
    return '{}  {:02d}:{:02d}:{:02d}'.format(date, when.hour, when.minute, when.second)


# ---------------------------------------------------------------------------- #
# Writing
# ---------------------------------------------------------------------------- #
def create_file(file_name, directory=None):
    """
    Make an empty file, and the folder it needs.

    :param str file_name: A name, or a whole path.
    :param str directory: The folder, when the name is only a name.
    :return: The file's path, or '' when it could not be made.
    :rtype: str
    """

    folder = directory or os.path.dirname(file_name)
    path = os.path.join(folder, safe_file_name(os.path.basename(file_name)))
    try:
        touch_path(path)
        with open(path, 'a', encoding=ENCODING):
            pass
    except OSError as error:
        logger.warning('Could not create %s: %s', path, error)
        return ''
    return os.path.normpath(path)


def write_lines(file_path, lines, append=False):
    """
    Write a list of lines, one per line.

    :param str file_path: The file.
    :param lines: A line, or a list of them.
    :param bool append: Add to the file rather than replacing it.
    :return: Whether it was written.
    :rtype: bool
    """

    if isinstance(lines, str):
        lines = [lines]
    text = '\n'.join(str(line) for line in lines)

    try:
        touch_path(file_path)
        with open(file_path, 'a' if append else 'w', encoding=ENCODING,
                  newline='\n') as opened:
            if append and opened.tell():
                opened.write('\n')
            opened.write(text)
    except OSError as error:
        logger.warning('Could not write %s: %s', file_path, error)
        return False
    return True


def write_line(file_path, line, append=False):
    """
    Write one line.

    :param str file_path: The file.
    :param str line: The line.
    :param bool append: Add to the file rather than replacing it.
    :return: Whether it was written.
    :rtype: bool
    """

    return write_lines(file_path, [line], append=append)


def replace(file_path, pattern, subst):
    """
    Replace some text throughout a file.

    Written beside the original and moved over it, so a failure leaves the original where it
    was. The version this replaces deleted the original first and moved a file in from the
    temp drive afterwards - two ways to end up with nothing.

    :param str file_path: The file.
    :param str pattern: What to look for.
    :param str subst: What to put in its place.
    :return: How many lines changed, or -1 when the file could not be read.
    :rtype: int
    """

    if not os.path.isfile(file_path):
        logger.warning('There is no file at %s to replace text in.', file_path)
        return -1

    temporary = file_path + '.mca-tmp'
    changed = 0
    try:
        with open(file_path, 'r', encoding=ENCODING, errors='replace') as old_file, \
                open(temporary, 'w', encoding=ENCODING, newline='') as new_file:
            for line in old_file:
                if pattern in line:
                    changed += 1
                    line = line.replace(pattern, subst)
                new_file.write(line)
        make_writable(file_path)
        os.replace(temporary, file_path)
    except OSError as error:
        logger.warning('Could not replace text in %s: %s', file_path, error)
        if os.path.isfile(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
        return -1
    return changed


# ---------------------------------------------------------------------------- #
# Moving things about
# ---------------------------------------------------------------------------- #
def remove_extension(file_path):
    """
    :param str file_path: A path.
    :return: It, without its extension. A folder with a dot in its name keeps it.
    :rtype: str
    """

    folder, name = os.path.split(str(file_path))
    return os.path.join(folder, name.rsplit('.', 1)[0]) if '.' in name else str(file_path)


def copy_file(file_path, file_path_destination):
    """
    Copy a file to a folder, or to a new name.

    :param str file_path: The file to copy.
    :param str file_path_destination: A folder to copy it into, or the new file's path.
    :return: Where it ended up, or '' when it could not be copied.
    :rtype: str
    """

    if not os.path.isfile(file_path):
        logger.warning('There is no file at %s to copy.', file_path)
        return ''

    destination = file_path_destination
    # Only a folder takes the file's own name. The old version did this whenever the
    # destination existed, so copying over an existing file produced C:/x/old.ma/new.ma.
    if os.path.isdir(destination):
        destination = os.path.join(destination, os.path.basename(file_path))

    try:
        touch_path(destination)
        shutil.copy2(file_path, destination)
    except (OSError, shutil.Error) as error:
        logger.warning('Could not copy %s to %s: %s', file_path, destination, error)
        return ''
    return os.path.normpath(destination)


def move_file(path1, path2):
    """
    :param str path1: The file to move.
    :param str path2: A folder to move it into, or its new path.
    :return: Where it ended up, or '' when it could not be moved.
    :rtype: str
    """

    if not os.path.exists(path1):
        logger.warning('There is nothing at %s to move.', path1)
        return ''

    destination = path2
    if os.path.isdir(destination):
        destination = os.path.join(destination, os.path.basename(path1))
    try:
        touch_path(destination)
        shutil.move(path1, destination)
    except (OSError, shutil.Error) as error:
        logger.warning('Could not move %s to %s: %s', path1, destination, error)
        return ''
    return os.path.normpath(destination)


def rename_file(name, directory, new_name):
    """
    Rename a file inside a folder.

    :param str name: The file's current name.
    :param str directory: The folder it is in.
    :param str new_name: What to call it.
    :return: Its new path, or its old one when nothing was renamed.
    :rtype: str
    """

    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        logger.warning('There is no file called %s in %s.', name, directory)
        return path

    new_path = os.path.join(directory, safe_file_name(new_name))
    if os.path.exists(new_path):
        logger.warning('A file called %s is already in %s.', new_name, directory)
        return path

    make_writable(path)
    try:
        os.rename(path, new_path)
    except OSError as error:
        logger.warning('Could not rename %s to %s: %s', name, new_name, error)
        return path
    return os.path.normpath(new_path)
