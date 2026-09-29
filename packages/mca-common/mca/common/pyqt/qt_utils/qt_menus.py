"""
Putting the framework's menus into a DCC's own menu bar.

    menu = qt_menus.MainWindowsMenus.create('MCA', maya_window)
    menu.add_action('Rig Builder', open_rig_builder, icon=icon_path)

What changed:

- **Removing an action only ever worked on the first one.** ``remove_action`` had its
  ``return False`` inside the loop, so it looked at the first QAction child, and if that was
  not the one being asked for it answered False and stopped - every action after the first
  was unremovable.
- **It logged to a logger of its own.** ``logging.getLogger('mca_common')`` rather than the
  framework's, so its messages went somewhere else and ignored ``MCA_LOGGING_LEVEL``.
- **A DCC with no menu bar crashed it.** ``main_window.findChild(QMenuBar)`` can answer
  None, and the next line called ``.children()`` on it.
- ``add_action`` said nothing about whether it worked, and the bare ``except:`` around the
  QAction import swallowed anything at all.
"""

# mca imports
from mca.common import log
from mca.common.pyqt import pygui


logger = log.MCA_LOGGER


def _action_class():
    """
    :return: QAction, which is in QtWidgets in PySide2 and QtGui in PySide6.
    """

    if not pygui.AVAILABLE:
        return None
    return getattr(pygui.qtwidgets, 'QAction', None) or getattr(pygui.qtgui, 'QAction', None)


def get_main_menu_menubar(main_window):
    """
    :param main_window: A QMainWindow.
    :return: Its menu bar, or None. Asking ``menuBar()`` crashes MotionBuilder, which is why
        this looks through the children instead.
    :rtype: QMenuBar or None
    """

    if main_window is None or not pygui.AVAILABLE:
        return None
    for child in main_window.children():
        if isinstance(child, pygui.qtwidgets.QMenuBar):
            return child
    return main_window.findChild(pygui.qtwidgets.QMenuBar)


class MainWindowsMenus(object):
    """One of the framework's menus, in a DCC's menu bar."""

    def __init__(self, menu_inst, main_window):
        """
        :param menu_inst: The QMenu or QMenuBar this works on.
        :param main_window: The window it belongs to.
        """

        self.menu = menu_inst
        self.main_window = main_window

    @classmethod
    def create(cls, menu_name, main_window, icon=None, quiet=True):
        """
        Find the framework's menu in a window, or add it.

        :param str menu_name: The menu's object name.
        :param main_window: A QMainWindow.
        :param icon: An icon, or a path to one.
        :param bool quiet: Say nothing when it was already there.
        :return: The menu, or None when the window has no menu bar to put it in.
        :rtype: MainWindowsMenus or None
        """

        menubar = get_main_menu_menubar(main_window)
        if menubar is None:
            # This used to be an AttributeError from .children() on None.
            logger.warning('That window has no menu bar, so %s cannot be added to it.',
                           menu_name)
            return None

        for child in menubar.children():
            if child.objectName() == menu_name:
                if not quiet:
                    logger.info('The %s menu is already there.', menu_name)
                return cls(child, main_window)

        holder = cls(menubar, main_window)
        return cls(holder.add_menu(menu_name, icon=icon), main_window)

    def add_menu(self, menu_name, icon=None, tear_off=True, change_menu=True):
        """
        Add a submenu.

        :param str menu_name: Its name, used as its title and its object name.
        :param icon: An icon, or a path to one.
        :param bool tear_off: Let the artist tear it off into its own window.
        :param bool change_menu: Work on the new menu from here on.
        :return: The menu.
        """

        menu = pygui.qtwidgets.QMenu(parent=self.menu)
        menu.setTitle(menu_name)
        menu.setObjectName(menu_name)
        menu.setTearOffEnabled(tear_off)
        menu.setAttribute(pygui.qtcore.Qt.WA_TranslucentBackground, False)
        self.menu.addMenu(menu)

        found = self.to_qicon(icon)
        if found is not None:
            menu.setIcon(found)

        if change_menu:
            self.menu = menu
        return menu

    def add_action(self, action_name, fn, menu=None, icon=None, tooltip=None):
        """
        Add something to click.

        :param str action_name: What it says.
        :param callable fn: What it does.
        :param menu: Which menu to put it in. None uses this one.
        :param icon: An icon, or a path to one.
        :param str tooltip: What it says on hover.
        :return: The action, or None when there is no Qt.
        """

        action_class = _action_class()
        if action_class is None:
            return None

        menu = menu or self.menu
        action = action_class(action_name, menu)
        action.setObjectName(action_name)
        action.triggered.connect(fn)

        found = self.to_qicon(icon)
        if found is not None:
            action.setIcon(found)
        if tooltip:
            action.setToolTip(tooltip)

        menu.addAction(action)
        return action

    def add_separator(self, menu=None):
        """
        :param menu: Which menu. None uses this one.
        """

        (menu or self.menu).addSeparator()

    @staticmethod
    def to_qicon(icon):
        """
        :param icon: A QIcon, a path to an image, or None.
        :return: A QIcon, or None.
        """

        if icon is None or not pygui.AVAILABLE:
            return None
        if isinstance(icon, pygui.qtgui.QIcon):
            return icon

        made = pygui.qtgui.QIcon()
        made.addFile(str(icon), pygui.qtcore.QSize(),
                     pygui.qtgui.QIcon.Normal, pygui.qtgui.QIcon.Off)
        return made

    # Kept: the old name for the same thing.
    convert_to_qicon = to_qicon

    def remove_action(self, action_name, menu=None):
        """
        Take something out of a menu.

        :param str action_name: What it says, or its object name.
        :param menu: Which menu. None uses this one.
        :return: Whether it was found and removed.
        :rtype: bool
        """

        menu = menu or self.menu
        action_class = _action_class()
        if menu is None or action_class is None:
            return False

        # actions(), not children(), and the answer comes after the whole loop - the version
        # this replaces returned False inside it, so only the first action could ever be
        # removed.
        for action in list(menu.actions()):
            if action.text() == action_name or action.objectName() == action_name:
                menu.removeAction(action)
                action.deleteLater()
                return True
        return False

    def remove_menu(self, menu=None):
        """
        Take a menu out of the menu bar.

        :param menu: Which menu. None uses this one.
        :return: Whether anything was removed.
        :rtype: bool
        """

        menu = menu or self.menu
        if menu is None:
            return False

        parent = menu.parent()
        action = getattr(menu, 'menuAction', None)
        if parent is not None and callable(action) and hasattr(parent, 'removeAction'):
            # deleteLater alone leaves the empty title in the menu bar until Qt gets round
            # to it, which an artist sees.
            parent.removeAction(action())
        menu.deleteLater()
        return True
