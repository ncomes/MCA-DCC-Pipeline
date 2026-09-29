"""
Finding the framework's windows, and closing them.

Used by ``startup.shutdown()``, which has to take every framework window down before the
framework goes, and by each window on the way up, to replace the one it is replacing.

**How a window is recognised changed.** The version this replaces looked for ``'MCA '`` in
the window's title, with a special case to leave ``'MCA Editor'`` alone. That is a string
match against something written for a person to read: rename a tool and its window stops
being closed; open a scene whose name starts with MCA and it gets closed instead. Windows
built by this framework now carry a Qt property saying so, which is what is looked for. The
title match is still there as a fallback, because a window built by an older tool has no
property, and until every one of those is ported it still has to be found.

And one that could never have worked: ``get_mca_window_by_name(name)`` compared a widget
against a string - ``if win == name`` - so it returned None every single time, whatever was
passed to it.
"""

# python imports
from mca.common import log
from mca.common.pyqt import pygui


logger = log.MCA_LOGGER

#: Set on every window this framework makes. Found by property rather than by title.
WINDOW_PROPERTY = 'mca_window'

#: Windows made before the property existed. Matched on the title, as before.
TITLE_PREFIX = 'MCA'

#: Not ours to close, whatever its title says.
NOT_OURS = ('MCA Editor',)


def mark(widget):
    """
    Say that a widget is one of the framework's windows.

    :param widget: Any QWidget.
    :return: The widget.
    """

    try:
        widget.setProperty(WINDOW_PROPERTY, True)
    except Exception as error:                                       # noqa: BLE001
        logger.debug('Could not mark %s: %s', widget, error)
    return widget


def is_ours(widget):
    """
    :param widget: Any QWidget.
    :return: Whether the framework made it.
    :rtype: bool
    """

    try:
        if widget.property(WINDOW_PROPERTY):
            return True
        title = widget.windowTitle() or ''
    except Exception:                                                # noqa: BLE001
        # A widget being torn down by Qt while we look at it.
        return False

    if any(one in title for one in NOT_OURS):
        return False
    return title.startswith(TITLE_PREFIX) or ' {} '.format(TITLE_PREFIX) in title


def application():
    """
    :return: The running QApplication, or None when there is not one.
    :rtype: QApplication or None
    """

    if not pygui.AVAILABLE:
        return None
    return pygui.qtwidgets.QApplication.instance()


def get_main_qt_window():
    """
    The top-level window to parent a new window to.

    ``QApplication.activeWindow()`` is what the old version used, and it answers None
    whenever the application does not have focus - so opening a tool from a shelf while
    another application was in front parented it to nothing.

    :return: The main window, or None.
    :rtype: QWidget or None
    """

    app = application()
    if app is None:
        return None

    active = app.activeWindow()
    if active is not None:
        parent = active
        while parent.parent() is not None:
            parent = parent.parent()
        return parent

    # No active window: the DCC's own main window is the top-level QMainWindow with no
    # parent, which is true in Maya, MotionBuilder and a standalone application alike.
    for widget in app.topLevelWidgets():
        try:
            if isinstance(widget, pygui.qtwidgets.QMainWindow) and widget.parent() is None:
                return widget
        except Exception:                                            # noqa: BLE001
            continue
    return None


def get_all_open_windows():
    """
    :return: Every visible top-level window. A list, always - the old version answered None
        when there were none, so a caller looping over the result crashed on an empty DCC.
    :rtype: list
    """

    app = application()
    if app is None:
        return []

    found = []
    for widget in app.topLevelWidgets():
        try:
            if widget.isWindow() and not widget.isHidden():
                found.append(widget)
        except Exception as error:                                   # noqa: BLE001
            logger.debug('Skipping a widget being torn down: %s', error)
    return found


def get_all_mca_windows():
    """
    :return: The framework's own open windows.
    :rtype: list
    """

    return [widget for widget in get_all_open_windows() if is_ours(widget)]


def get_mca_window_by_title(title):
    """
    :param str title: All or part of a window's title.
    :return: The first of the framework's windows whose title contains it, or None.
    :rtype: QWidget or None
    """

    if not title:
        return None
    for widget in get_all_mca_windows():
        try:
            if title in (widget.windowTitle() or ''):
                return widget
        except Exception:                                            # noqa: BLE001
            continue
    return None


#: The old name. It took a name and compared it to the widget itself, so it never found
#: anything; callers that used it were quietly doing nothing.
get_mca_window_by_name = get_mca_window_by_title


def close_windows(widgets):
    """
    Close widgets and let Qt delete them.

    :param widgets: What to close.
    :return: How many were closed.
    :rtype: int
    """

    closed = 0
    for widget in list(widgets or []):
        try:
            widget.close()
            widget.deleteLater()
            closed += 1
        except Exception as error:                                   # noqa: BLE001
            logger.debug('Could not close a window: %s', error)
    return closed


def close_all_mca_windows():
    """
    :return: How many of the framework's windows were closed.
    :rtype: int
    """

    closed = close_windows(get_all_mca_windows())
    if closed:
        logger.info('Closed %s framework window(s).', closed)
    return closed


def get_all_docked_windows(parent_window):
    """
    :param parent_window: A QMainWindow.
    :return: Its dock widgets.
    :rtype: list
    """

    if parent_window is None or not pygui.AVAILABLE:
        return []
    return list(parent_window.findChildren(pygui.qtwidgets.QDockWidget))


def get_all_mca_docked_windows(parent_window):
    """
    :param parent_window: A QMainWindow.
    :return: The framework's dock widgets inside it.
    :rtype: list
    """

    return [widget for widget in get_all_docked_windows(parent_window) if is_ours(widget)]


def close_all_mca_docked_windows(parent_window):
    """
    :param parent_window: A QMainWindow.
    :return: How many were closed.
    :rtype: int
    """

    return close_windows(get_all_mca_docked_windows(parent_window))


def remove_widgets_by_name(parent_window, widget_names):
    """
    :param parent_window: A QMainWindow.
    :param widget_names: Object names to find and close.
    :return: How many were closed.
    :rtype: int
    """

    if parent_window is None or not pygui.AVAILABLE:
        return 0
    if isinstance(widget_names, str):
        widget_names = [widget_names]

    found = []
    for name in widget_names or []:
        widget = parent_window.findChild(pygui.qtwidgets.QWidget, name)
        if widget:
            found.append(widget)
    return close_windows(found)
