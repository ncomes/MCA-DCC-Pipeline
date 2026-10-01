"""
Logging, checked without a DCC.

Every check here is something the version this replaces got wrong, or something that would be
silently wrong if it broke: a second logger that gets no handler, a reload that doubles every
line, a file handler whose level makes it look like it is catching more than it is, and a
Documents folder that was guessed rather than asked for.

    python tests/test_log.py
"""

# python imports
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import log  # noqa: E402


def body(suite):
    # ---------------------------------------------------------------- #
    # Getting a logger
    # ---------------------------------------------------------------- #
    first = log.get_logger()
    suite.check('the framework logger is the one everything shares',
                first is log.MCA_LOGGER and first.name == log.LOGGER_NAME, first.name)
    suite.check('and it does not hand its lines to the root logger as well',
                not first.propagate)

    ours = [handler for handler in first.handlers if getattr(handler, log.OURS, False)]
    suite.check('it prints somewhere', len(ours) == 1, str(first.handlers))

    log.get_logger()
    log.get_logger()
    ours = [handler for handler in first.handlers if getattr(handler, log.OURS, False)]
    suite.check('asking for it again does not add a second handler - which is what a DCC '
                'reloading the framework does',
                len(ours) == 1, str(first.handlers))

    # The bug this replaces: a Singleton metaclass meant the second logger asked for was
    # handed back the first manager without __init__ running, so it got no handler and no
    # level at all.
    child = log.get_logger('MCA.tools.rigging')
    suite.check('a second logger is really set up, not silently ignored',
                child.level == first.level and child.name == 'MCA.tools.rigging',
                '{} {}'.format(child.name, child.level))
    suite.check('and it does not print twice: it reports through its parent',
                not [handler for handler in child.handlers
                     if getattr(handler, log.OURS, False)],
                str(child.handlers))

    # ---------------------------------------------------------------- #
    # The level
    # ---------------------------------------------------------------- #
    os.environ[log.LEVEL_VARIABLE] = 'DEBUG'
    suite.check('the level comes from the environment', log.level_wanted() == logging.DEBUG,
                str(log.level_wanted()))
    os.environ[log.LEVEL_VARIABLE] = 'nonsense'
    suite.check('and a value that is not a level falls back to INFO rather than raising',
                log.level_wanted() == logging.INFO, str(log.level_wanted()))
    os.environ.pop(log.LEVEL_VARIABLE, None)

    log.set_level('WARNING')
    suite.check('setting the level sets it on the handlers too, not only the logger',
                first.level == logging.WARNING and
                all(handler.level == logging.WARNING for handler in first.handlers
                    if getattr(handler, log.OURS, False)),
                str([(handler, handler.level) for handler in first.handlers]))
    log.set_level('INFO')

    # ---------------------------------------------------------------- #
    # Where the files go
    # ---------------------------------------------------------------- #
    suite.check('the Documents folder is a real path, asked for rather than guessed',
                bool(log.documents_folder()), log.documents_folder())
    suite.check('the preferences folder follows MCA_PREFS_ROOT, so a test cannot write into '
                'a real one',
                log.preferences_folder() == os.path.normpath(
                    os.environ['MCA_PREFS_ROOT']), log.preferences_folder())

    folder = log.logs_folder('SampleGame', 'maya')
    suite.check('logs are kept per project and per DCC',
                folder.endswith(os.path.join('SampleGame', 'maya')), folder)
    suite.check('and under MCA_LOGS_ROOT when the launcher set one',
                folder.startswith(os.path.normpath(os.environ['MCA_LOGS_ROOT'])), folder)
    suite.check('the file is named for the DCC and the day',
                os.path.basename(log.log_file('SampleGame', 'maya')).startswith('mca_maya_'),
                log.log_file('SampleGame', 'maya'))

    # ---------------------------------------------------------------- #
    # Writing one
    # ---------------------------------------------------------------- #
    path = log.setup_file_logging('SampleGame', 'maya')
    suite.check('setting up file logging writes a file', bool(path) and os.path.isfile(path),
                str(path))

    again = log.setup_file_logging('SampleGame', 'maya')
    files = [handler for handler in log.MCA_LOGGER.handlers
             if isinstance(handler, logging.FileHandler)]
    suite.check('doing it twice does not open a second one', len(files) == 1 and
                again == path, '{} / {}'.format(len(files), again))

    suite.check('the file handler logs at the level the logger does, rather than claiming '
                'DEBUG under an INFO logger and catching nothing extra',
                files[0].level == log.MCA_LOGGER.level,
                '{} vs {}'.format(files[0].level, log.MCA_LOGGER.level))

    log.MCA_LOGGER.warning('a line the suite wrote')
    files[0].flush()
    with open(path, 'r', encoding='utf-8') as opened:
        written = opened.read()
    suite.check('and what is logged really lands in it',
                'a line the suite wrote' in written, written[-200:])

    # ---------------------------------------------------------------- #
    # Tidying up
    # ---------------------------------------------------------------- #
    folder = os.path.dirname(path)
    old = os.path.join(folder, 'mca_maya_2020-01-01.log')
    with open(old, 'w', encoding='utf-8') as opened:
        opened.write('last year\n')
    long_ago = time.time() - (40 * 86400)
    os.utime(old, (long_ago, long_ago))
    keep = os.path.join(folder, 'keep_me.txt')
    with open(keep, 'w', encoding='utf-8') as opened:
        opened.write('not a log\n')
    os.utime(keep, (long_ago, long_ago))

    removed = log.remove_old_logs(folder, days_to_keep=30)
    suite.check('a log from before the cutoff is deleted', removed == [old], str(removed))
    suite.check('today\'s is not', os.path.isfile(path))
    suite.check('and a file that is not a log is left alone', os.path.isfile(keep))
    suite.check('tidying a folder that is not there answers nothing, rather than raising',
                log.remove_old_logs(os.path.join(suite.temp, 'nope')) == [])

    # Let the suite delete its temp folder on Windows, where an open file cannot be removed.
    log.MCA_LOGGER.removeHandler(files[0])
    files[0].close()

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('log', body))
