"""
Starting the application: one QApplication, and the right first window.

Which window comes first is a question for the API - is there a project that is actually
finished - rather than a scan of the preferences folder. The old launcher answered it by
looking for the first folder holding a file, so a half-finished project sent an artist to
the main window with nothing that worked in it.
"""

# python imports
import logging
import sys

# mca imports
from mca.launcher import api
from mca.launcher.core import logs


logger = logging.getLogger('mca-launcher')

#: Windows that must not be garbage collected while they are on screen.
_windows = []


def first_window(parent=None):
    """
    Decide which window to open, and build it.

    :param parent: Parent widget, if any.
    :return: The window, shown by the caller.
    """

    from mca.launcher.ui import launcher_window, setup_window

    listing = api.list_projects()
    complete = []
    if listing['ok']:
        complete = [one for one in listing['result']['projects'] if one['complete']]

    if complete:
        return launcher_window.LauncherWindow(parent=parent)

    logger.info('No finished project found; opening setup.')
    window = setup_window.SetupWindow(parent=parent)
    return window


def run(argv=None):
    """
    Run the launcher.

    :param list(str) argv: Arguments for QApplication.
    :return: The exit code.
    :rtype: int
    """

    from PySide6.QtWidgets import QApplication

    logs.setup()
    logger.info('MCA Launcher starting on %s', sys.version.split()[0])

    application = QApplication.instance()
    owns_application = application is None
    if owns_application:
        application = QApplication(list(sys.argv if argv is None else argv))

    window = first_window()
    window.show()
    _windows.append(window)

    # When setup is what opened, the main window follows once it saves. Both are held in
    # _windows: a Qt window with no reference left in Python is collected, and collecting a
    # visible window makes it disappear with no error anywhere.
    if isinstance(window, _setup_type()):
        window.saved.connect(_open_main_window)

    if not owns_application:
        # Somebody else owns the event loop - a DCC, or a test.
        return 0
    return application.exec()


def _setup_type():
    """
    :return: The setup window class, imported late so this module stays importable without Qt.
    """

    from mca.launcher.ui import setup_window
    return setup_window.SetupWindow


def _open_main_window(_project_name=None):
    """
    Open the main window after setup has saved.

    :param str _project_name: The project that was saved. Not needed - the window reads the
        current project itself - but the signal carries it.
    """

    from mca.launcher.ui import launcher_window

    window = launcher_window.LauncherWindow()
    window.show()
    _windows.append(window)
    return window
