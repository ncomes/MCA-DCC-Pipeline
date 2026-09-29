"""
Logging, for every DCC the pipeline runs in.

``from mca.common import log`` then ``log.MCA_LOGGER.info(...)``, which is what the rest of
the framework does and what this keeps working.

What changed on the way over, and why:

- **A second logger got nothing.** ``get_logger`` handed its logger to a ``LogsManager``
  wearing a Singleton metaclass, and a singleton's ``__call__`` returns the first instance
  without running ``__init__`` again. So the first call set up the ``MCA`` logger and every
  call after it - ``get_logger('mca.maya')``, any tool asking for its own - silently did
  nothing: no handler, no level. Here each logger is set up once, by name, and a repeat call
  is a no-op rather than a duplicate handler.
- **The file handler's level was a lie.** It was set to DEBUG "so the file gets everything",
  under a logger set to INFO - and the logger's level gates first, so DEBUG never reached the
  file. The level is set in one place now, and it is the same for both.
- **Logs went to a guessed Documents folder.** ``~/Documents`` is wrong on any machine where
  Documents is redirected to OneDrive, which is common. Windows is asked. ``MCA_LOGS_ROOT``
  and ``MCA_PREFS_ROOT`` are honoured, so a DCC started by the launcher writes where the
  launcher says, and a test run writes into its own temp folder.
- The Python 2 metaclass shim and three unused format strings are gone.
"""

# python imports
import glob
import logging
import os
import sys
import time


#: The framework's logger. Everything else is a child of it.
LOGGER_NAME = 'MCA'

#: Set this to DEBUG, INFO, WARNING... to change what is logged, without changing code.
LEVEL_VARIABLE = 'MCA_LOGGING_LEVEL'

#: Where logs go, and where preferences live. The launcher sets both; a test run overrides
#: them so nothing it does can touch a real machine's files.
LOGS_ROOT_VARIABLE = 'MCA_LOGS_ROOT'
PREFS_ROOT_VARIABLE = 'MCA_PREFS_ROOT'

#: How long log files are kept.
DAYS_TO_KEEP = 30

#: Marks the handlers this module added, so setting a logger up twice does not double every
#: line - which is what happens when a DCC reloads the framework.
OURS = '_mca_handler'

#: Ordinary lines say where they came from; a warning or worse says it in full, because that
#: is the line somebody is about to go and look at.
SHELL_FORMAT = ('[%(name)s - %(module)s:%(lineno)d - %(funcName)s] %(levelname)s: '
                '%(message)s')
DETAIL_FORMAT = ('[%(name)s - %(pathname)s:%(lineno)d - %(funcName)s]\n'
                 '%(levelname)s: %(message)s\n')


class LevelFormatter(logging.Formatter):
    """
    One formatter that says more when the news is worse.

    The sub-formatters are built once, here, rather than a new one per record - the old
    version constructed a ``logging.Formatter`` on every single line it printed.
    """

    def __init__(self, shell_format=SHELL_FORMAT, detail_format=DETAIL_FORMAT):
        """
        :param str shell_format: Used for DEBUG and INFO.
        :param str detail_format: Used for WARNING and worse.
        """

        super(LevelFormatter, self).__init__(shell_format)
        self.plain = logging.Formatter(shell_format)
        self.detailed = logging.Formatter(detail_format)

    def format(self, record):
        """
        :param logging.LogRecord record: The line being logged.
        :return: It, formatted.
        :rtype: str
        """

        formatter = self.detailed if record.levelno >= logging.WARNING else self.plain
        return formatter.format(record)


def level_wanted():
    """
    :return: The level to log at, from the environment, or INFO.
    :rtype: int
    """

    wanted = str(os.getenv(LEVEL_VARIABLE) or '').strip().upper()
    if not wanted:
        return logging.INFO
    if wanted.isdigit():
        return int(wanted)
    return getattr(logging, wanted, logging.INFO)


def get_logger(name=None, level=None):
    """
    The logger to use, set up once however many times this is called.

    :param str name: A logger name. None is the framework's own, ``MCA``.
    :param level: A level, or None to take it from ``MCA_LOGGING_LEVEL``.
    :return: The logger.
    :rtype: logging.Logger
    """

    logger = logging.getLogger(name or LOGGER_NAME)
    logger.setLevel(level if level is not None else level_wanted())

    # The framework's own logger prints for itself; a child of it must not also hand its
    # lines to the root logger, or a DCC that has configured logging prints everything twice.
    if logger.name == LOGGER_NAME:
        logger.propagate = False

    if not any(getattr(handler, OURS, False) for handler in logger.handlers):
        if logger.name == LOGGER_NAME or not logger.parent or not logger.propagate:
            handler = logging.StreamHandler(stream=sys.stdout)
            handler.setFormatter(LevelFormatter())
            setattr(handler, OURS, True)
            logger.addHandler(handler)

    return logger


def set_level(level, name=None):
    """
    Change what is logged, everywhere, now.

    :param level: A level name or number.
    :param str name: Which logger. None is the framework's own.
    """

    logger = logging.getLogger(name or LOGGER_NAME)
    if isinstance(level, str):
        level = getattr(logging, level.strip().upper(), logging.INFO)
    logger.setLevel(level)
    for handler in logger.handlers:
        if getattr(handler, OURS, False):
            handler.setLevel(level)


# ---------------------------------------------------------------------------- #
# Where the files go
# ---------------------------------------------------------------------------- #
def documents_folder():
    """
    The user's Documents folder, asked of Windows rather than assumed.

    ``~/Documents`` is a guess, and it is wrong on any machine where Documents has been
    redirected - to OneDrive, or to a second drive.

    :return: The Documents folder.
    :rtype: str
    """

    if sys.platform.startswith('win'):
        try:
            import ctypes
            import ctypes.wintypes

            csidl_personal = 5          # My Documents
            shgfp_type_current = 0

            buffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(
                None, csidl_personal, None, shgfp_type_current, buffer)
            if buffer.value:
                return os.path.normpath(buffer.value)
        except Exception as error:                                  # noqa: BLE001
            # Logged rather than raised: not knowing where Documents is should not stop a
            # DCC from starting.
            MCA_LOGGER.warning('Could not ask Windows for the Documents folder: %s', error)

    return os.path.normpath(os.path.join(os.path.expanduser('~'), 'Documents'))


def preferences_folder():
    """
    :return: The folder holding the framework's preferences, the launcher's included.
    :rtype: str
    """

    override = os.getenv(PREFS_ROOT_VARIABLE)
    if override:
        return os.path.normpath(override)
    return os.path.join(documents_folder(), 'mca_preferences')


def logs_folder(project_name='', dcc_name=''):
    """
    Where log files belong, agreeing with the launcher.

    :param str project_name: The project, when there is one.
    :param str dcc_name: The DCC, so Maya's log is not MotionBuilder's.
    :return: The folder. It is not created here.
    :rtype: str
    """

    override = os.getenv(LOGS_ROOT_VARIABLE)
    root = os.path.normpath(override) if override else os.path.join(preferences_folder(),
                                                                    'logs')
    parts = [root]
    if project_name:
        parts.append(str(project_name))
    if dcc_name:
        parts.append(str(dcc_name))
    return os.path.normpath(os.path.join(*parts))


def log_file(project_name='', dcc_name='common', when=None):
    """
    :param str project_name: The project.
    :param str dcc_name: The DCC.
    :param when: A ``time.struct_time``, or None for now.
    :return: The file today's lines go in.
    :rtype: str
    """

    day = time.strftime('%Y-%m-%d', when or time.localtime())
    return os.path.join(logs_folder(project_name, dcc_name),
                        'mca_{}_{}.log'.format(dcc_name or 'common', day))


def setup_file_logging(project_name='', dcc_name='common', days_to_keep=DAYS_TO_KEEP):
    """
    Also write the log to a file, one per day, and tidy up the old ones.

    Safe to call twice: a second call finds the handler it added and does nothing.

    :param str project_name: The project, for the folder.
    :param str dcc_name: The DCC, for the folder and the file name.
    :param int days_to_keep: How long to keep files. 0 keeps them forever.
    :return: The file being written, or '' when it could not be opened.
    :rtype: str
    """

    path = log_file(project_name, dcc_name)
    for handler in MCA_LOGGER.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, OURS, False):
            return getattr(handler, 'baseFilename', path)

    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        handler = logging.FileHandler(path, encoding='utf-8')
    except OSError as error:
        # A read-only or missing folder is not a reason to stop a DCC starting.
        MCA_LOGGER.warning('Could not open the log file %s: %s', path, error)
        return ''

    handler.setFormatter(LevelFormatter())
    # Deliberately the logger's level, not DEBUG: the logger gates first, so a DEBUG file
    # handler under an INFO logger writes nothing extra and only looks like it does.
    handler.setLevel(MCA_LOGGER.level)
    setattr(handler, OURS, True)
    MCA_LOGGER.addHandler(handler)
    MCA_LOGGER.info('Logging to %s', path)

    if days_to_keep:
        remove_old_logs(os.path.dirname(path), days_to_keep)
    return path


def remove_old_logs(folder, days_to_keep=DAYS_TO_KEEP):
    """
    Delete log files older than a number of days.

    :param str folder: Where the logs are.
    :param int days_to_keep: How many days to keep.
    :return: What was deleted.
    :rtype: list(str)
    """

    if not folder or not os.path.isdir(folder) or not days_to_keep:
        return []

    cutoff = time.time() - (float(days_to_keep) * 86400)
    removed = []
    for path in sorted(glob.glob(os.path.join(folder, 'mca_*.log'))):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed.append(path)
        except OSError as error:
            # Being unable to delete yesterday's log - open in an editor, say - is not worth
            # a word to the artist, but it is worth a line in the log.
            MCA_LOGGER.debug('Could not remove the old log %s: %s', path, error)
    return removed


#: The framework's logger. Import this, do not build your own.
MCA_LOGGER = get_logger()
