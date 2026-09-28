"""
Finding the icons, images and stylesheets that ship with the package.

Derived from this file's own location, which is the fix for the old launcher's version: it
walked from the project root through ``Tools/Python/standalone/mcalauncher/mca-launcher/mca/
launcher`` - six folder names that had to stay exactly where they were, and which the move
to a new directory breaks. A package should know where it is.

PyInstaller is handled here too: a frozen build unpacks its data to ``sys._MEIPASS``, and
that is the only thing that changes.
"""

# python imports
import logging
import os
import sys


logger = logging.getLogger('mca-launcher')


def package_folder():
    """
    :return: The folder holding the launcher package's own files.
    :rtype: str
    """

    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            return os.path.normpath(meipass)
        return os.path.normpath(os.path.dirname(sys.executable))

    # core/resources.py -> core -> launcher
    return os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resources_folder():
    """
    :return: The resources folder.
    :rtype: str
    """

    return os.path.join(package_folder(), 'resources')


def icons_folder():
    """:return: Where the icons are."""

    return os.path.join(resources_folder(), 'icons')


def images_folder():
    """:return: Where the images are."""

    return os.path.join(resources_folder(), 'images')


def movies_folder():
    """:return: Where the animations are."""

    return os.path.join(resources_folder(), 'movies')


def icon(name):
    """
    :param str name: An icon file name.
    :return: Its path, or '' when it is not there - so a missing icon is a button without a
        picture rather than an exception on start-up.
    :rtype: str
    """

    return _find(icons_folder(), name)


def image(name):
    """
    :param str name: An image file name.
    :return: Its path, or ''.
    :rtype: str
    """

    return _find(images_folder(), name)


def movie(name):
    """
    :param str name: An animation file name.
    :return: Its path, or ''.
    :rtype: str
    """

    return _find(movies_folder(), name)


def _find(folder, name):
    path = os.path.join(folder, name)
    if os.path.isfile(path):
        return path
    logger.debug('Resource not found: %s', path)
    return ''
