"""
Logging setup.

One logger, ``mca-launcher``, with a console handler and a file handler. The file is the
reason it exists: a pip install that fails does so in a subprocess, on somebody else's
machine, and the only useful answer to "it did not work" is a log with pip's own output in
it.
"""

# python imports
import logging
import os
from datetime import datetime

# mca imports
from mca.launcher.core import platform_paths


LOGGER_NAME = 'mca-launcher'

FORMAT = '%(asctime)s  %(levelname)-7s  %(name)s  %(filename)s:%(lineno)d  %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup(level='INFO', to_file=True):
    """
    Set the launcher's logging up. Safe to call more than once.

    :param str level: The console level.
    :param bool to_file: Also write a file, which always gets DEBUG.
    :return: The logger.
    :rtype: logging.Logger
    """

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    console.setFormatter(formatter)
    logger.addHandler(console)

    if to_file:
        path = log_file()
        if path:
            try:
                handler = logging.FileHandler(path, encoding='utf-8')
                handler.setLevel(logging.DEBUG)
                handler.setFormatter(formatter)
                logger.addHandler(handler)
                logger.debug('Logging to %s', path)
            except Exception as error:
                # A launcher that will not start because it cannot open its log file would
                # be a poor trade.
                logger.warning('Could not open the log file %s: %s', path, error)

    return logger


def log_file():
    """
    :return: Today's log file, with its folder made, or '' when that is not possible.
    :rtype: str
    """

    folder = platform_paths.logs_folder()
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except Exception:
        return ''
    return os.path.join(folder, 'mca_launcher_{}.log'.format(datetime.now().strftime('%Y%m%d')))
