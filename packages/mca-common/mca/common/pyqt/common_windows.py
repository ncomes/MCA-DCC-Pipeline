"""
The windows every tool in the framework is built from.

    class RigBuilder(common_windows.MCAMainWindow):
        def __init__(self, parent=None):
            super().__init__('Rig Builder', version='2.0.0', parent=parent)
            self.main_layout.addWidget(...)

Three classes used to carry the same forty lines each - title, icon, stylesheet, remembered
geometry, closing the one already open - copied and then drifted apart: one guarded its
stylesheet against the resources being missing and another did not, one saved its geometry on
close and another had that commented out. The forty lines are :class:`WindowBehaviour` now,
and the classes are what is different about them.

What else changed:

- **A window knew it was the framework's by its title.** Replacing the window already open
  meant matching ``'MCA - Rig Builder'`` inside every open window's title, so renaming a
  tool left two of it open. They carry a Qt property, which is also what ``shutdown()``
  looks for.
- **Settings were stored under the user's name as the organisation.**
  ``QSettings(os.getlogin(), title)`` - which writes to ``HKCU\\Software\\<username>\\MCA -
  Tool``, a key per machine account rather than per application, and ``os.getlogin()``
  raises in a process with no controlling terminal. One organisation now, and the user name
  comes from the platform module that has a fallback.
- ``get_area`` asked ``isinstance(value, qtcore.Qt)``, which is not a class, so passing a
  Qt enum - the documented way to use it - raised TypeError.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.pyqt import pygui
from mca.common.pyqt.qt_utils import windows
from mca.common.resources import resources
from mca.common.utils import platforms


logger = log.MCA_LOGGER

#: Every window in the framework starts with this, so an artist can see whose it is.
TITLE_PREFIX = 'MCA'

#: Where remembered geometry is kept. One organisation, not one per user name.
SETTINGS_ORGANISATION = 'MechanicalArt'

#: The stylesheet a window uses when it does not ask for one.
DEFAULT_STYLE = 'dark_theme'

#: The icon a window uses when it does not ask for one.
DEFAULT_ICON = 'company_logos/default_logo.png'


class WindowBehaviour(object):
    """
    What every window in the framework does, whatever kind of widget it is.

    A mixin rather than a base class: the three windows inherit from three different Qt
    classes, and this is the part they share.
    """

    def setup_window(self, title, version='1.0.0', style=None, icon=None,
                     single_instance=True):
        """
        :param str title: The tool's name, without the MCA prefix.
        :param str version: Its version, shown in the title bar.
        :param str style: A stylesheet name. None uses the framework's.
        :param str icon: An icon name. None uses the framework's.
        :param bool single_instance: Close the one already open first.
        :return: The full window title.
        :rtype: str
        """

        self.title = '{} - {}'.format(TITLE_PREFIX, title)
        self.tool_name = title
        self.version = version

        # Marked, not named: this is how shutdown() and the single-instance check find it.
        windows.mark(self)

        if single_instance:
            self.close_existing()

        self.setWindowTitle('{} {}'.format(self.title, version) if version else self.title)
        self.apply_icon(icon)
        self.apply_style(style)
        self.settings = self.read_settings()
        return self.title

    def apply_icon(self, icon=None):
        """
        :param str icon: An icon name. None uses the framework's.
        :return: Whether one was set.
        :rtype: bool
        """

        found = resources.icon(icon or DEFAULT_ICON)
        if found is None:
            return False
        self.setWindowIcon(found)
        return True

    def apply_style(self, style=None):
        """
        :param str style: A stylesheet name, or 'custom' to leave the window alone.
        :return: Whether one was applied.
        :rtype: bool
        """

        if style == 'custom':
            return False
        sheet = resources.read_stylesheet(style or DEFAULT_STYLE)
        if not sheet:
            return False
        self.setStyleSheet(sheet)
        return True

    def read_settings(self):
        """
        :return: Where this window's geometry is remembered, and its geometry restored.
        :rtype: QSettings
        """

        settings = pygui.qtcore.QSettings(SETTINGS_ORGANISATION, self.title)
        geometry = settings.value('geometry')
        if geometry:
            try:
                self.restoreGeometry(geometry)
            except Exception as error:                               # noqa: BLE001
                # Geometry saved by another Qt, or a screen that is no longer there.
                logger.debug('Could not restore the geometry of %s: %s', self.title, error)
        return settings

    def save_settings(self):
        """Remember where this window is, for next time."""

        try:
            self.settings.setValue('geometry', self.saveGeometry())
        except Exception as error:                                   # noqa: BLE001
            logger.debug('Could not save the geometry of %s: %s', self.title, error)

    def close_existing(self):
        """
        Close the window this one replaces.

        :return: How many were closed.
        :rtype: int
        """

        open_already = [window for window in windows.get_all_mca_windows()
                        if window is not self and
                        getattr(window, 'tool_name', None) == getattr(self, 'tool_name', '')]
        return windows.close_windows(open_already)

    def closeEvent(self, event):
        """
        :param event: The close event.
        """

        self.save_settings()
        super(WindowBehaviour, self).closeEvent(event)


class MCAMainWindow(WindowBehaviour,
                    pygui.qtwidgets.QMainWindow if pygui.AVAILABLE else object):
    """A tool's own window."""

    INITIAL_WIDTH = 400
    INITIAL_HEIGHT = 300

    def __init__(self, title, ui_path=None, version='1.0.0', style=None, icon=None,
                 parent=None, show_window=True, single_instance=True):
        """
        :param str title: The tool's name.
        :param str ui_path: A .ui file to load as the window's contents.
        :param str version: The tool's version.
        :param str style: A stylesheet name.
        :param str icon: An icon name.
        :param parent: The parent window. None parents to the DCC's main window.
        :param bool show_window: Show it straight away.
        :param bool single_instance: Close the one already open first.
        """

        super(MCAMainWindow, self).__init__(parent=parent or windows.get_main_qt_window())

        self.ui = None
        self.main_layout = None
        self.setup_window(title, version, style, icon, single_instance)

        self.setMinimumSize(self.INITIAL_WIDTH, self.INITIAL_HEIGHT)
        self.setContentsMargins(0, 0, 0, 0)

        # Loaded with no parent, then handed to setCentralWidget, which does the
        # parenting itself. Passing ``self`` here instead makes QUiLoader add the
        # loaded widget to this QMainWindow's own layout, which QMainWindowLayout
        # does not accept - the widget ends up parented but never laid out, so it
        # sits at its default 100x30 inside a full-size window and the tool looks
        # like an empty grey panel.
        self.ui = load_ui_file(ui_path, None) if ui_path else None
        if self.ui is not None:
            self.setCentralWidget(self.ui)
        else:
            central = pygui.qtwidgets.QWidget(self)
            self.main_layout = pygui.qtwidgets.QVBoxLayout(central)
            self.main_layout.setContentsMargins(0, 0, 0, 0)
            self.setCentralWidget(central)

        if show_window:
            self.show()


class MCADockableWindow(WindowBehaviour,
                        pygui.qtwidgets.QDockWidget if pygui.AVAILABLE else object):
    """A tool docked into the DCC's own window."""

    AREAS = {'left': 'LeftDockWidgetArea', 'right': 'RightDockWidgetArea',
             'top': 'TopDockWidgetArea', 'bottom': 'BottomDockWidgetArea'}

    def __init__(self, title, ui_path=None, version='1.0.0', style=None, icon=None,
                 is_floating=False, area='left', single_instance=True, parent=None):
        """
        :param str title: The tool's name.
        :param str ui_path: A .ui file to load as the contents.
        :param str version: The tool's version.
        :param str style: A stylesheet name.
        :param str icon: An icon name.
        :param bool is_floating: Start floating rather than docked.
        :param area: Which side to dock to - 'left', 'right', or a Qt area.
        :param bool single_instance: Close the one already open first.
        :param parent: The window to dock into. None finds the DCC's.
        """

        parent = parent or windows.get_main_qt_window()
        super(MCADockableWindow, self).__init__(parent=parent)

        self.setAttribute(pygui.qtcore.Qt.WA_DeleteOnClose)
        self.setup_window(title, version, style, icon, single_instance)

        self.setAllowedAreas(pygui.qtcore.Qt.LeftDockWidgetArea |
                             pygui.qtcore.Qt.RightDockWidgetArea)
        self.setContentsMargins(0, 2, 0, 0)

        self.main_frame = pygui.qtwidgets.QFrame(self)
        self.main_layout = pygui.qtwidgets.QVBoxLayout(self.main_frame)
        self.main_layout.setContentsMargins(0, 2, 0, 0)
        self.setWidget(self.main_frame)

        self.ui = load_ui_file(ui_path, self) if ui_path else None
        if self.ui is not None:
            self.main_layout.addWidget(self.ui)

        if parent is not None and hasattr(parent, 'addDockWidget'):
            parent.addDockWidget(self.get_area(area), self)
            # Tab with whatever is already docked, rather than squeezing beside it.
            siblings = [one for one in parent.findChildren(MCADockableWindow)
                        if one is not self]
            if siblings:
                parent.tabifyDockWidget(siblings[0], self)
                self.raise_()

        if is_floating:
            self.setFloating(True)
        self.show()

    def get_area(self, value):
        """
        :param value: 'left', 'right', 'top', 'bottom', or a Qt dock area.
        :return: A Qt dock area.
        """

        # A string, or something Qt already understands. The version this replaced asked
        # isinstance(value, qtcore.Qt) first, and Qt is not a class, so passing the enum -
        # the documented way - raised TypeError before it reached the strings.
        if isinstance(value, str):
            name = self.AREAS.get(value.lower(), 'LeftDockWidgetArea')
            return getattr(pygui.qtcore.Qt, name)
        return value if value is not None else pygui.qtcore.Qt.LeftDockWidgetArea


class ParentableWidget(WindowBehaviour,
                       pygui.qtwidgets.QWidget if pygui.AVAILABLE else object):
    """A panel meant to be put inside something else."""

    def __init__(self, title=None, ui_path=None, style=None, parent=None):
        """
        :param str title: The panel's name.
        :param str ui_path: A .ui file to load as the contents.
        :param str style: A stylesheet name.
        :param parent: The widget to live in.
        """

        super(ParentableWidget, self).__init__(parent=parent)

        self.ui = None
        self.main_layout = None
        self.setup_window(title or 'Panel', version='', style=style, single_instance=False)

        self.ui = load_ui_file(ui_path, self) if ui_path else None
        if self.ui is None:
            self.main_layout = pygui.qtwidgets.QVBoxLayout(self)
            self.main_layout.setContentsMargins(0, 0, 0, 0)


class ProgressBarWindow(MCAMainWindow):
    """
    A window for a job with a progress bar in it.

    Its geometry is saved and restored like every other window's. The version this replaces
    had that commented out, along with its single-instance check, so two of them could be
    open at once and neither remembered where it was.
    """

    INITIAL_WIDTH = 435
    INITIAL_HEIGHT = 200

    def __init__(self, title, version='1.0.0', progress_instance=None, style=None,
                 parent=None):
        """
        :param str title: The job's name.
        :param str version: The tool's version.
        :param progress_instance: Whatever owns the progress, told when this closes.
        :param str style: A stylesheet name.
        :param parent: The parent window.
        """

        self.progress_instance = progress_instance
        super(ProgressBarWindow, self).__init__(title, version=version, style=style,
                                                parent=parent)

    def closeEvent(self, event):
        """
        :param event: The close event.
        """

        closing = getattr(self.progress_instance, 'close_window', None)
        if callable(closing):
            try:
                closing()
            except Exception as error:                               # noqa: BLE001
                logger.debug('The progress owner did not close cleanly: %s', error)
        super(ProgressBarWindow, self).closeEvent(event)


def load_ui_file(ui_path, parent=None):
    """
    Load a Qt Designer file.

    :param str ui_path: The .ui file.
    :param parent: What to parent the result to.
    :return: The widget it describes, or None.
    """

    if not ui_path or not os.path.isfile(ui_path):
        if ui_path:
            logger.warning('There is no .ui file at %s.', ui_path)
        return None

    loader = pygui.qtuitools.QUiLoader()
    handle = pygui.qtcore.QFile(os.path.abspath(ui_path))
    if not handle.open(pygui.qtcore.QFile.ReadOnly):
        logger.warning('Could not open %s.', ui_path)
        return None
    try:
        return loader.load(handle, parent)
    finally:
        handle.close()


def current_user():
    """
    :return: Who is logged in. Used for the settings the windows remember.
    :rtype: str
    """

    return platforms.user_name()
