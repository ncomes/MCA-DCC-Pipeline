"""
Decorators the whole framework uses.

Three of the five had something wrong with them, and the first one is the sort that only
shows up when somebody reaches for it:

- ``timestamp`` read ``f.func_name`` - a Python 2 attribute - before falling back to
  ``__name__``. ``f.func_name`` does not exist on Python 3, and reading it raises, so
  **decorating anything with @timestamp broke it**, every time, on every interpreter the
  framework runs on.
- ``debug`` built a one-item list and joined it with ``' --> '``, a separator that could
  therefore never appear.
- ``repeater`` ran a function on a timer thread with nothing catching its exceptions, so a
  failure killed the thread silently and the repeating simply stopped.

``error`` is worth reading twice before using: it **swallows** the exception. That is what it
is for - report to the artist, keep the DCC alive - but it means a function wearing it
returns ``None`` when it fails, so a caller must not read ``None`` as an answer.
"""

# python imports
import functools
import os
import sys
import threading
import time

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: What ``@abstractmethod`` does when nobody overrode the method: 'raise' or 'warn'.
ABSTRACT_MODE_VARIABLE = 'ABSTRACT_METHOD_MODE'


def _describe(function, message):
    """
    :param function: The function in question.
    :param str message: What to say about it.
    :return: The message, with enough about the function to find it.
    :rtype: str
    """

    return '{} [{}.{}, line {}]'.format(
        message, getattr(function, '__module__', '?'),
        getattr(function, '__qualname__', getattr(function, '__name__', '?')),
        getattr(getattr(function, '__code__', None), 'co_firstlineno', '?'))


def timestamp(function):
    """
    Log how long a function took.

    :param function: The function to time.
    :return: The wrapped function.
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        started = time.time()
        try:
            return function(*args, **kwargs)
        finally:
            # __name__, not func_name: the Python 2 spelling raised AttributeError here
            # before the fallback beside it was ever reached.
            logger.info('<%s> took %.3f seconds.', function.__name__, time.time() - started)
    return wrapper


def debug(function):
    """
    Log at debug level how long a function took, and what it was.

    :param function: The function.
    :return: The wrapped function.
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        started = time.time()
        try:
            return function(*args, **kwargs)
        finally:
            name = getattr(function, '__qualname__', function.__name__)
            logger.debug('%s() took %.3f seconds.', name, time.time() - started)
    return wrapper


def error(function):
    """
    Catch what a function raises, log it, and show it to the artist.

    **It does not re-raise.** A decorated function answers ``None`` when it fails, which is
    the price of a DCC that stays open when a tool falls over - and a reason not to put this
    on anything whose answer is then used for something else.

    :param function: The function.
    :return: The wrapped function.
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as raised:                                  # noqa: BLE001
            kind, value, traceback = sys.exc_info()
            # Drop this decorator's own frames, so the traceback starts where the problem is.
            while traceback is not None and 'wrapper' in traceback.tb_frame.f_code.co_name:
                if traceback.tb_next is None:
                    break
                traceback = traceback.tb_next

            logger.error(_describe(function, str(raised) or kind.__name__),
                         exc_info=(kind, value, traceback))
            _show(str(raised) or kind.__name__)
            return None
    return wrapper


def _show(message):
    """
    Put an error in front of the artist, when there is a window to put it in.

    Imported here rather than at the top: this module is as low in the stack as it gets, and
    Qt must not be a condition of importing it.

    :param str message: What went wrong.
    :return: Whether a dialog was shown.
    :rtype: bool
    """

    try:
        from mca.common.pyqt import pygui

        if not pygui.AVAILABLE:
            return False
        application = pygui.qtwidgets.QApplication.instance()
        # Only from the thread that owns the windows: a dialog from a worker thread is a
        # crash in Qt, not a message.
        if not application or pygui.qtcore.QThread.currentThread() != application.thread():
            return False

        from mca.common.pyqt import messages

        messages.error_message('MCA DCC Framework', message)
        return True
    except Exception as failed:                                      # noqa: BLE001
        # Reporting a problem must never replace the problem.
        logger.debug('Could not show the error dialog: %s', failed)
        return False


def abstractmethod(function):
    """
    Mark a method a DCC-specific module is meant to override.

    :param function: The method.
    :return: The wrapped method, which refuses when nobody overrode it.
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        message = 'This has no implementation for this DCC; something was meant to override it.'
        mode = str(os.getenv(ABSTRACT_MODE_VARIABLE) or 'raise').lower()
        if mode == 'warn':
            logger.warning(_describe(function, message))
            return function(*args, **kwargs)
        raise NotImplementedError(_describe(function, message))
    return wrapper


class Repeater(object):
    """
    A function called on a timer, until it is stopped.

    Returned by :func:`repeater`, so the caller has something to stop. The thread is a
    daemon: a DCC closing does not wait for it.
    """

    def __init__(self, function, interval, limit=-1, args=(), kwargs=None):
        """
        :param function: What to call.
        :param float interval: Seconds between calls.
        :param int limit: How many times, or -1 for until stopped.
        :param tuple args: Positional arguments for it.
        :param dict kwargs: Keyword arguments for it.
        """

        self.function = function
        self.interval = float(interval)
        self.limit = int(limit)
        self.args = args
        self.kwargs = kwargs or {}
        self.calls = 0
        self.failures = 0

        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread = threading.Thread(target=self._run, name='mca-repeater')
        self._thread.daemon = True

    def start(self):
        """
        :return: This, so it can be started and kept in one line.
        :rtype: Repeater
        """

        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set() and (self.limit < 0 or self.calls < self.limit):
            if self._stop.wait(self.interval):
                break
            if self._paused.is_set():
                continue
            try:
                self.function(*self.args, **self.kwargs)
            except Exception as raised:                              # noqa: BLE001
                # Without this the thread dies here and the repeating stops with no sign
                # that it ever did.
                self.failures += 1
                logger.exception('A repeating call failed: %s', raised)
            self.calls += 1

    def pause(self):
        """Stop calling, without stopping the thread."""

        self._paused.set()

    def resume(self):
        """Start calling again."""

        self._paused.clear()

    def stop(self, wait=True):
        """
        :param bool wait: Wait for the thread to finish.
        """

        self._stop.set()
        if wait and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=self.interval + 1)

    @property
    def running(self):
        """
        :return: Whether it is still going.
        :rtype: bool
        """

        return self._thread.is_alive() and not self._stop.is_set()


def repeater(interval, limit=-1):
    """
    Call a function on a timer.

    :param float interval: Seconds between calls.
    :param int limit: How many times, or -1 for until stopped.
    :return: A decorator. The decorated function, when called, starts the timer and answers
        a :class:`Repeater` to stop it with.
    """

    def decorator(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            return Repeater(function, interval, limit, args, kwargs).start()
        return wrapper
    return decorator
