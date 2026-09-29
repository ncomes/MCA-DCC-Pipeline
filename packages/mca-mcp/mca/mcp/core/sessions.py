"""
Which Mayas are running, and how to reach them.

Every Maya that loads the bootstrap writes a small file here::

    %LOCALAPPDATA%\\MCA\\sessions\\maya-<pid>.json

holding its process id, version, command ports and the scene it has open. A file whose
process is gone is stale and is cleaned up on sight, because a session file that outlives
its Maya is worse than no file: it sends the next caller to a port nobody is listening on.

Stale files are the normal case, not an error - Maya is usually closed by being closed, not
by anything that gets a chance to tidy up.
"""

# python imports
import json
import logging
import os
import time


logger = logging.getLogger('mca-mcp')

#: Folder name under the application data folder.
SESSIONS_FOLDER = 'sessions'


def sessions_folder():
    """
    :return: Where session files live. Created on demand by whoever writes one.
    :rtype: str
    """

    override = os.getenv('MCA_SESSIONS_ROOT')
    if override:
        return os.path.normpath(override)

    if os.name == 'nt':
        base = os.getenv('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData',
                                                         'Local')
    else:
        base = os.getenv('XDG_RUNTIME_DIR') or os.path.join(os.path.expanduser('~'), '.local',
                                                            'share')
    return os.path.normpath(os.path.join(base, 'MCA', SESSIONS_FOLDER))


def session_file(pid):
    """
    :param int pid: A process id.
    :return: That process's session file.
    :rtype: str
    """

    return os.path.join(sessions_folder(), 'maya-{}.json'.format(int(pid)))


def is_alive(pid):
    """
    Is a process still running.

    :param int pid: The process id.
    :return: Whether it is alive.
    :rtype: bool
    """

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    if os.name == 'nt':
        import ctypes

        process_query_limited = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                still_active = 259
                return code.value == still_active
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write(session):
    """
    Write a session file. Called from inside Maya.

    :param dict session: What the session knows about itself.
    :return: The path written.
    :rtype: str
    """

    folder = sessions_folder()
    if not os.path.isdir(folder):
        os.makedirs(folder)

    path = session_file(session['pid'])
    session = dict(session)
    session['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(session, handle, indent=2, sort_keys=True, default=str)
    return path


def read(path):
    """
    :param str path: A session file.
    :return: What it holds, or None when it cannot be read.
    :rtype: dict or None
    """

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception as error:
        logger.debug('Could not read %s: %s', path, error)
        return None


def forget(pid):
    """
    Remove a session file.

    :param int pid: The process id.
    :return: Whether a file was removed.
    :rtype: bool
    """

    path = session_file(pid)
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def live_sessions():
    """
    Every Maya that is running and has told us about itself.

    Stale files - a session whose process has gone - are deleted here rather than reported,
    which keeps the list honest without anybody having to run a cleanup.

    :return: The live sessions, most recently started first.
    :rtype: list(dict)
    """

    folder = sessions_folder()
    if not os.path.isdir(folder):
        return []

    found = []
    for name in sorted(os.listdir(folder)):
        if not name.startswith('maya-') or not name.endswith('.json'):
            continue
        path = os.path.join(folder, name)
        session = read(path)
        if not session or not is_alive(session.get('pid')):
            try:
                os.remove(path)
                logger.debug('Removed stale session file %s', path)
            except OSError:
                pass
            continue
        session['file'] = path
        found.append(session)

    found.sort(key=lambda one: one.get('started', ''), reverse=True)
    return found
