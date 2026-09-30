"""
What else is running on this machine, and running something off the main thread.

Two small jobs that the framework needs from the operating system. ``psutil`` does the
looking; the launcher installs it for every DCC, but it is asked for politely, because a
machine where it failed to install should still start.
"""

# python imports
import threading

# MCA python imports
from mca.common import log


logger = log.MCA_LOGGER

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:                                                  # pragma: no cover
    psutil = None
    PSUTIL_AVAILABLE = False

#: The errors psutil raises while a process list is being read, all of them ordinary:
#: a process can exit between being listed and being asked its name, and Windows refuses
#: to talk about system processes at all.
_TRANSIENT = ()
if PSUTIL_AVAILABLE:
    _TRANSIENT = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)


def available():
    """
    :return: Whether this machine can be asked about its processes at all.
    :rtype: bool
    """

    return PSUTIL_AVAILABLE


def find_by_name(process_name, exact=True):
    """
    Every running process whose name matches.

    :param str process_name: A process name, with or without its extension - ``'cm.exe'``,
        ``'maya'``. Case does not matter.
    :param bool exact: True wants the whole name to match, False accepts the name appearing
        anywhere in it.
    :return: The processes found, newest first is not promised - the order is the operating
        system's. Empty when there are none, and empty when psutil is missing.
    :rtype: list
    """

    if not PSUTIL_AVAILABLE:
        logger.warning('Cannot look for the process "%s": psutil is not installed.', process_name)
        return []

    wanted = (process_name or '').lower()
    if not wanted:
        return []

    found = []
    for process in psutil.process_iter(['name']):
        try:
            name = (process.info.get('name') or '').lower()
        except _TRANSIENT:                                           # pragma: no cover
            continue
        if not name:
            continue
        if name == wanted if exact else wanted in name:
            found.append(process)

    return found


def is_running(process_name, exact=True):
    """
    Whether anything by that name is running.

    :param str process_name: A process name. Case does not matter.
    :param bool exact: See :func:`find_by_name`.
    :return: True when at least one is.
    :rtype: bool
    """

    return bool(find_by_name(process_name, exact=exact))


def run_on_thread(function, name='', daemon=True):
    """
    Run something on a thread of its own, and say so when it fails.

    :param callable function: What to run. It is called with no arguments.
    :param str name: A name for the thread, which is what shows up in a traceback or a
        debugger. The function's own name by default.
    :param bool daemon: True lets the application close without waiting for it.
    :return: The thread, already started, so a caller who cares can ``join()`` it.
    :rtype: threading.Thread
    """

    label = name or getattr(function, '__name__', 'thread')

    def guarded():
        try:
            function()
        except Exception:                                             # noqa: BLE001
            # Nothing above a thread's target catches anything: without this the exception
            # is printed to a stream nobody is reading and the work simply did not happen.
            logger.exception('The background job "%s" failed.', label)

    thread = threading.Thread(target=guarded, name=label, daemon=daemon)
    thread.start()

    return thread
