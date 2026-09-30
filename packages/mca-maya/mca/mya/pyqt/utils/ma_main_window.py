"""
Reaching Maya's own Qt widgets from Python.

Maya's interface *is* Qt, but it does not hand out Python objects for it: it gives out a C++
pointer, and ``shiboken`` turns that into something Python can hold. That is all this module is -
the main window, its menu bar, and the pointer-wrapping underneath.

A tool window parents itself to Maya's main window so that it behaves like part of Maya: it stays
in front of the viewport, it minimises with Maya, and it dies when Maya dies rather than leaving a
window nobody can close.

What was wrong before:

- **Wrapping a pointer looked for the class in the wrong module.** With no base class given,
  ``wrapinstance`` read the object's class name off its ``metaObject`` and then looked for it on
  ``qtgui`` - and every widget class lives in ``QtWidgets``, not ``QtGui``, and has since Qt 5. So
  the lookup never found anything and every wrapped object came back as a bare ``QWidget``,
  whatever it actually was. The same mistake as ``QAction`` in ``mca-common``, in the other
  direction.
- **Its fallback was PySide 1.** ``from PySide.shiboken import wrapInstance`` - a module that has
  not shipped since 2013. And the branch it sat beside, ``elif 'sip' in globals()``, could never
  run: ``shiboken`` is imported at the top of the module, so the ``if`` above it is always true.
- **A bare ``except: pass`` around the whole thing**, so a pointer that would not wrap answered
  ``None`` with nothing in the log to say why.
- **Nineteen of the twenty-two things in here had no caller anywhere in the pipeline** - the
  workspace controls, the time slider, the x-ray joints, the axis setup, the node editor manager,
  the isolate-panel helpers, the UI suspension class. 491 lines became a third of that. The two
  things anything calls are the main window and its menu bar.
- ``if sys.version_info >= (3,): long = int``, and ``is_enable_workspace_control`` answered
  ``int(pm.about(v=True)[:4]) > 2016`` - a version check that has been true for a decade, parsed
  out of a string that is not always a number.
"""

# python imports

# software specific imports
import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as OpenMayaUI

# mca imports
from mca.common import log
from mca.common.pyqt.pygui import qtcore, qtwidgets, shiboken


logger = log.MCA_LOGGER

#: What Maya calls its main window, for the case where the pointer cannot be had and the widget has
#: to be found by name instead.
MAIN_WINDOW_NAME = 'MayaWindow'


def get_main_window_name():
    """
    The name of Maya's main window, as MEL knows it.

    :return: The name, or '' in a batch Maya.
    :rtype: str
    """

    if cmds.about(batch=True):
        return ''
    return mel.eval('$tempVar = $gMainWindow') or ''


def wrap_instance(pointer, base=None):
    """
    A C++ pointer as something Python can hold.

    :param pointer: The address, as an int or anything that converts to one.
    :param base: The Qt class to wrap it as. Worked out from the object itself otherwise.
    :return: The wrapped object, or None.
    :rtype: qtcore.QObject or None
    """

    if pointer is None:
        return None

    try:
        pointer = int(pointer)
    except (TypeError, ValueError):
        logger.warning('%r is not a pointer.', pointer)
        return None

    try:
        if base is None:
            base = _class_for_pointer(pointer)
        return shiboken.wrapInstance(pointer, base)
    except (RuntimeError, TypeError, ValueError) as error:
        logger.warning('Could not wrap the pointer %s: %s', pointer, error)
        return None


def _class_for_pointer(pointer):
    """
    Which Qt class a pointer's object actually is.

    Read off the object's own ``metaObject``, and looked for in ``QtWidgets`` and then
    ``QtCore`` - the version this replaces looked in ``QtGui``, where no widget class has lived
    since Qt 5, so it always fell through to a bare ``QWidget``.

    :param int pointer: The address.
    :return: The class to wrap as. ``QWidget`` when the name is not one we have.
    """

    probe = shiboken.wrapInstance(pointer, qtcore.QObject)
    meta_object = probe.metaObject()
    names = [meta_object.className()]
    super_class = meta_object.superClass()
    if super_class is not None:
        names.append(super_class.className())

    for name in names:
        for module in (qtwidgets, qtcore):
            found = getattr(module, name, None)
            if found is not None:
                return found
    return qtwidgets.QWidget


def to_qt_object(maya_name, qobj=None):
    """
    A Maya interface element, by the name Maya calls it, as a Qt object.

    :param str maya_name: Maya's name for the control, layout or menu item.
    :param qobj: The Qt class to wrap it as. Worked out from the object otherwise.
    :return: The widget, or None when Maya has no such thing.
    :rtype: qtwidgets.QWidget or None
    """

    for finder in (OpenMayaUI.MQtUtil.findControl, OpenMayaUI.MQtUtil.findLayout,
                   OpenMayaUI.MQtUtil.findMenuItem):
        pointer = finder(maya_name)
        if pointer is not None:
            return wrap_instance(pointer, qobj)
    return None


def get_maya_window(window_name=None, by_pointer=True):
    """
    Maya's main window, or another of Maya's windows by name.

    :param window_name: Which window. Maya's main one otherwise. A widget passed here comes
        straight back, so a caller holding one already does not need to special-case it.
    :param bool by_pointer: Find it through the C++ pointer. False searches Qt's top-level
        widgets by name instead, which is slower and only works for a window Qt owns. The
        argument was called ``wrap_instance`` and shadowed the function of that name.
    :return: The window, or None - which is always the answer in a batch Maya, there being no
        interface at all.
    :rtype: qtwidgets.QWidget or None
    """

    if cmds.about(batch=True):
        return None

    if isinstance(window_name, qtwidgets.QWidget):
        return window_name

    if by_pointer:
        if window_name is None:
            return wrap_instance(OpenMayaUI.MQtUtil.mainWindow(), qtwidgets.QMainWindow)
        if '|' in str(window_name):
            # A path with separators in it is a control inside a window, not a window.
            found = to_qt_object(window_name)
            if found is not None:
                return found
        pointer = OpenMayaUI.MQtUtil.findControl(window_name)
        if pointer is not None:
            return wrap_instance(pointer, qtwidgets.QMainWindow)

    wanted = window_name or MAIN_WINDOW_NAME
    for widget in qtwidgets.QApplication.topLevelWidgets():
        if widget.objectName() == wanted:
            return widget
    return None


def get_main_menu_menubar():
    """
    Maya's main menu bar, which is where the pipeline hangs its own menus.

    :return: The menu bar, or None in a batch Maya.
    :rtype: qtwidgets.QMenuBar or None
    """

    window = get_maya_window()
    if window is None:
        return None

    for child in window.children():
        if isinstance(child, qtwidgets.QMenuBar):
            return child
    return None
