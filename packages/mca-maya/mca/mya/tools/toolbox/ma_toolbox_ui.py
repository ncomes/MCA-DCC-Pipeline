"""
Maya host for the MCA Toolbox.

Each toolbox gets its own Maya workspace control (dock), so several toolboxes can be open at once, docked in
different areas, floating, or tabbed together. Every tool click is a single undo step.

Dock behaviour:

- Opening a toolbox that is already open raises its dock instead of recreating it, so it keeps its place.
- Picking another toolbox in a dock's toolbox picker opens that toolbox as a tab next to the current dock.
- Docks carry a ``uiScript``, so Maya rebuilds them where they were when a workspace loads (Maya restart, workspace
  switch). ``startup.restart()`` empties the docks on shutdown and refills them on startup, keeping their layout.

Entry points: :func:`open_toolbox`, :func:`open_startup_toolboxes`, :func:`release_toolboxes`,
:func:`close_all_toolboxes`, :func:`attach_toolbox_menu`, and the AI-facing :func:`api_open_toolbox` /
:func:`api_list_open_toolboxes`.

Requires: maya.cmds, maya.OpenMayaUI.
Side effects: creates/deletes workspaceControl UI; sets the toolbox run context to Maya undo chunks.
"""

# python imports
import contextlib
import re

# software specific imports
from maya import cmds
from maya import OpenMayaUI as omui

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore, shiboken

# MCA python imports
from mca.common import log
from mca.common.resources import resources
from mca.common.tools.toolbox import toolbox_library, toolbox_model, toolbox_runner, toolbox_widgets

logger = log.MCA_LOGGER

__all__ = ['MayaToolboxWindow', 'open_toolbox', 'restore_toolbox', 'open_startup_toolboxes', 'release_toolboxes',
           'close_all_toolboxes', 'list_open_toolboxes', 'attach_toolbox_menu', 'fill_toolbox_menu',
           'api_open_toolbox', 'api_list_open_toolboxes']

DCC_NAME = 'Maya'
# Object name prefix; Maya appends "WorkspaceControl" for the dock.
OBJECT_PREFIX = 'MCAToolbox_'
CONTROL_SUFFIX = 'WorkspaceControl'
# Where a dock can be placed. "tab" tabs it with another open toolbox, "floating" makes a floating window.
AREAS = ('left', 'right', 'top', 'bottom', 'floating', 'tab')

# Toolbox name -> live window. Rebuilt from the existing docks after a restart purges this module.
_WINDOWS = {}


@contextlib.contextmanager
def maya_undo_chunk(label):
    """
    Group everything a tool does into one undo step named after the tool.

    :param str label: Tool name shown in Maya's undo queue.
    """

    cmds.undoInfo(openChunk=True, chunkName=f'Toolbox: {label}')
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


# Every toolbox command in Maya runs inside one undo chunk.
toolbox_runner.set_run_context(maya_undo_chunk)


def _library():
    """
    :return: The Maya toolbox library.
    :rtype: toolbox_library.ToolboxLibrary
    """

    return toolbox_library.get_library(DCC_NAME)


def _object_name(toolbox_name):
    """
    :param str toolbox_name: Toolbox name.
    :return: A Maya-safe object name for that toolbox's window.
    :rtype: str
    """

    return OBJECT_PREFIX + re.sub(r'\W+', '_', toolbox_name)


def _control_name(toolbox_name):
    """
    :param str toolbox_name: Toolbox name.
    :return: The workspaceControl name Maya creates for the window.
    :rtype: str
    """

    return _object_name(toolbox_name) + CONTROL_SUFFIX


def _control_exists(control):
    """
    :param str control: workspaceControl name.
    :return: True when the control exists.
    :rtype: bool
    """

    return bool(cmds.workspaceControl(control, query=True, exists=True))


def _live_window(toolbox_name):
    """
    :param str toolbox_name: Toolbox name.
    :return: The open window for that toolbox, or None.
    :rtype: MayaToolboxWindow|None
    """

    window = _WINDOWS.get(toolbox_name)
    if window is not None and shiboken.isValid(window):
        return window
    _WINDOWS.pop(toolbox_name, None)
    return None


def _restore_script(toolbox_name):
    """
    :param str toolbox_name: Toolbox name.
    :return: Python run by Maya to rebuild the dock's contents when a workspace loads. It must never raise: when MCA
        is not initialised yet the dock stays empty and startup refills it.
    :rtype: str
    """

    return ('try:\n'
            '    from mca.mya.tools.toolbox import ma_toolbox_ui\n'
            f'    ma_toolbox_ui.restore_toolbox({toolbox_name!r})\n'
            'except ImportError:\n'
            '    pass\n'
            'except Exception as exc:\n'
            f'    print("MCA Toolbox: could not restore {toolbox_name}: %s" % exc)\n')


class MayaToolboxWindow(qtwidgets.QWidget):
    """
    The widget inside a toolbox dock. Always created as a child of its workspaceControl (see :func:`_fill_control`):
    a widget that starts top-level gets a native window, and when it is later moved into a background dock tab that
    native window never shows up (blank dock, verified 2026-09-16).
    """

    def __init__(self, toolbox_name=toolbox_model.ALL_TOOLS, parent=None):
        """
        :param str toolbox_name: Toolbox to show.
        :param qtwidgets.QWidget parent: The workspaceControl's widget.
        """

        super().__init__(parent=parent)
        self.toolbox_name = toolbox_name
        self.setObjectName(_object_name(toolbox_name))
        self.setWindowTitle(f'Toolbox - {toolbox_name}')
        try:
            self.setStyleSheet(resources.read_stylesheet('incrypt'))
        except Exception:
            logger.debug('Toolbox: MCA stylesheet unavailable, using Maya style.', exc_info=True)
        layout = qtwidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toolbox_widget = toolbox_widgets.ToolboxWidget(toolbox_name, library=_library(),
                                                            switch_handler=self._open_other, parent=self)
        layout.addWidget(self.toolbox_widget)
        self.toolbox_widget.toolbox_changed.connect(self._toolbox_changed)
        self.resize(340, 700)
        _WINDOWS[toolbox_name] = self

    @property
    def control(self):
        """
        :return: The workspaceControl this window lives in.
        :rtype: str
        """

        return self.objectName() + CONTROL_SUFFIX

    def _open_other(self, name):
        """
        The toolbox picker (or "New ... Toolbox") chose another toolbox: open (or raise) it as a tab next to this dock.

        :param str name: Toolbox name.
        """

        open_toolbox_later(name, area='tab', tab_with=self.toolbox_name)

    def _toolbox_changed(self, name):
        """
        The widget fell back to another toolbox (this toolbox was deleted). Docks are one per toolbox, so close this
        dock and show the fallback in its own dock.

        :param str name: The toolbox the widget switched to.
        """

        if name == self.toolbox_name:
            return
        control = self.control
        toolbox_name = self.toolbox_name
        open_toolbox_later(name)

        def close_this_dock():
            # Same rule as opening: never delete a dock while a click inside it is still being handled.
            app = qtwidgets.QApplication
            if app.activePopupWidget() or app.activeModalWidget() or app.mouseButtons() != qtcore.Qt.NoButton:
                qtcore.QTimer.singleShot(50, close_this_dock)
                return
            _WINDOWS.pop(toolbox_name, None)
            if _control_exists(control):
                cmds.deleteUI(control)

        qtcore.QTimer.singleShot(0, close_this_dock)


def _purge_stale_windows(toolbox_name):
    """
    Delete parentless toolbox windows left over from closed docks or a purged module. Maya (and the dock mixin) find
    windows by object name, so a leftover with the same name would be picked up instead of the new window.

    :param str toolbox_name: Toolbox name.
    """

    object_name = _object_name(toolbox_name)
    live = _WINDOWS.get(toolbox_name)
    for widget in qtwidgets.QApplication.topLevelWidgets():
        if shiboken.isValid(widget) and widget.objectName() == object_name and widget is not live:
            widget.setObjectName('')
            widget.deleteLater()


def _clear_control(control):
    """
    Remove stale toolbox widgets from a dock (left behind when this module was purged without a shutdown).

    :param str control: workspaceControl name.
    """

    pointer = omui.MQtUtil.findControl(control)
    if not pointer:
        return
    control_widget = shiboken.wrapInstance(int(pointer), qtwidgets.QWidget)
    for child in control_widget.findChildren(qtwidgets.QWidget):
        # Children already scheduled for deletion can still be listed; skip them.
        if not shiboken.isValid(child):
            continue
        if child.objectName().startswith(OBJECT_PREFIX) and not child.objectName().endswith(CONTROL_SUFFIX):
            child.setParent(None)
            child.deleteLater()


def _fill_control(toolbox_name, control, from_ui_script=False):
    """
    Build a toolbox window inside an existing (empty) dock.

    :param str toolbox_name: Toolbox name.
    :param str control: workspaceControl name.
    :param bool from_ui_script: Running inside the dock's own uiScript; don't edit the control from inside it.
    :return: The window.
    :rtype: MayaToolboxWindow
    """

    _clear_control(control)
    _WINDOWS.pop(toolbox_name, None)
    _purge_stale_windows(toolbox_name)
    control_pointer = omui.MQtUtil.findControl(control)
    if not control_pointer:
        raise RuntimeError(f'Dock {control} has no widget yet.')
    control_widget = shiboken.wrapInstance(int(control_pointer), qtwidgets.QWidget)
    # Build the window as a child of the dock from the start (never top-level), then put it in the dock's layout
    # and show it explicitly; background tabs are not shown by anyone else.
    window = MayaToolboxWindow(toolbox_name, parent=control_widget)
    layout = control_widget.layout()
    if layout is None:
        layout = qtwidgets.QVBoxLayout(control_widget)
        layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(window)
    qtwidgets.QWidget.setVisible(window, True)
    if not from_ui_script:
        cmds.workspaceControl(control, edit=True, label=window.windowTitle(), uiScript=_restore_script(toolbox_name))
    return window


def restore_toolbox(toolbox_name):
    """
    Rebuild a toolbox dock's contents. Called by Maya through the dock's ``uiScript`` when a workspace loads.

    :param str toolbox_name: Toolbox name.
    :return: The window, or None when the toolbox no longer exists.
    :rtype: MayaToolboxWindow|None
    """

    if toolbox_name not in _library().toolboxes:
        logger.warning(f'Toolbox "{toolbox_name}" no longer exists; its dock stays empty.')
        return None
    return _fill_control(toolbox_name, _control_name(toolbox_name), from_ui_script=True)


def open_toolbox(toolbox_name=toolbox_model.ALL_TOOLS, area=None, tab_with=None):
    """
    Open a toolbox in its own dock, or raise it when it is already open.

    :param str toolbox_name: Toolbox name.
    :param str area: Where a new dock goes: ``'left'``, ``'right'``, ``'top'``, ``'bottom'``, ``'floating'`` or
        ``'tab'`` (tab with ``tab_with``, else with any open toolbox). None uses where this toolbox was last opened,
        or left for the first toolbox and right when another toolbox is already docked. Ignored when already open.
    :param str tab_with: Toolbox whose dock a ``'tab'`` opens next to.
    :return: The window.
    :rtype: MayaToolboxWindow
    """

    library = _library()
    if toolbox_name not in library.toolboxes:
        logger.warning(f'Toolbox "{toolbox_name}" not found; opening {toolbox_model.ALL_TOOLS}.')
        toolbox_name = toolbox_model.ALL_TOOLS
    control = _control_name(toolbox_name)

    if _control_exists(control):
        # Already docked somewhere: keep the user's placement, just make sure it has contents and bring it forward.
        window = _live_window(toolbox_name) or _fill_control(toolbox_name, control)
        cmds.workspaceControl(control, edit=True, visible=True)
        cmds.workspaceControl(control, edit=True, restore=True)
        return window

    open_names = [x['toolbox'] for x in list_open_toolboxes()]
    if area is None:
        area = library.get_state(toolbox_name, 'area') or ('right' if open_names else 'left')
    if area not in AREAS:
        raise ValueError(f'area must be one of {", ".join(AREAS)}')
    if area == 'tab':
        tab_with = tab_with if tab_with in open_names else (open_names[0] if open_names else None)
        if not tab_with:
            area = 'left'

    # Create the dock directly where it belongs, with the restore script as its uiScript. Maya runs that script right
    # away (loadImmediately) and it builds the toolbox inside the dock - the same path as a workspace restore.
    # Never create a dock and then move it (tabToControl on an existing dock + restore): Qt has to recreate the moved
    # dock's native window and Maya 2025 crashes in QWindow::setParent (crash log 2026-09-16 21:46).
    _WINDOWS.pop(toolbox_name, None)
    _purge_stale_windows(toolbox_name)
    kwargs = {'label': f'Toolbox - {toolbox_name}', 'retain': False, 'loadImmediately': True,
              'initialWidth': 340, 'minimumWidth': 220, 'widthProperty': 'free',
              'uiScript': _restore_script(toolbox_name)}
    if area == 'floating':
        kwargs['floating'] = True
    elif area == 'tab':
        kwargs['tabToControl'] = (_control_name(tab_with), -1)
    else:
        kwargs['dockToMainWindow'] = (area, False)
    cmds.workspaceControl(control, **kwargs)

    window = _live_window(toolbox_name)
    if window is None:
        # The uiScript did not build it (e.g. an import problem it swallowed); fill the dock directly.
        window = _fill_control(toolbox_name, control)
    if area != 'tab':
        library.set_state(toolbox_name, 'area', area)
    logger.info(f'Opened Toolbox: {toolbox_name} ({area})')
    return window


def open_toolbox_later(toolbox_name, area=None, tab_with=None):
    """
    Open a toolbox once the current click has finished. Use this from any widget signal (combo box, menu action).

    Creating or tabbing a dock makes Maya re-parent existing docks. Doing that while a combo box or menu inside one of
    those docks is still handling its signal destroys the widget under Qt's feet and aborts Maya. The callback holds
    no widget references, so it is safe even if the calling window is gone by then.

    :param str toolbox_name: Toolbox name.
    :param str area: See :func:`open_toolbox`.
    :param str tab_with: See :func:`open_toolbox`.
    """

    def attempt():
        app = qtwidgets.QApplication
        if app.activePopupWidget() or app.activeModalWidget() or app.mouseButtons() != qtcore.Qt.NoButton:
            qtcore.QTimer.singleShot(50, attempt)
            return
        try:
            open_toolbox(toolbox_name, area=area, tab_with=tab_with)
        except Exception:
            logger.exception(f'Toolbox: could not open "{toolbox_name}".')

    qtcore.QTimer.singleShot(0, attempt)


def list_open_toolboxes():
    """
    :return: ``[{'toolbox', 'control', 'floating', 'visible'}]`` for every toolbox dock that exists.
    :rtype: list[dict]
    """

    names = {_control_name(name): name for name in _library().toolbox_names()}
    result = []
    for control in cmds.lsUI(type='workspaceControl') or []:
        # lsUI can still list a control deleted a moment ago; only report ones that answer queries.
        if control not in names or not _control_exists(control):
            continue
        try:
            result.append({'toolbox': names[control], 'control': control,
                           'floating': bool(cmds.workspaceControl(control, query=True, floating=True)),
                           'visible': bool(cmds.workspaceControl(control, query=True, visible=True))})
        except RuntimeError:
            continue
    return result


def release_toolboxes():
    """
    Empty every toolbox dock but keep the docks, so a framework restart can refill them in place.
    """

    for name in list(_WINDOWS):
        window = _live_window(name)
        if window is not None:
            # Clear the name first: deletion is deferred, and Maya finds windows by name.
            window.setObjectName('')
            window.setParent(None)
            window.deleteLater()
    _WINDOWS.clear()


def close_all_toolboxes():
    """
    Close every toolbox dock.
    """

    release_toolboxes()
    for control in cmds.lsUI(type='workspaceControl') or []:
        if control.startswith(OBJECT_PREFIX) and _control_exists(control):
            cmds.deleteUI(control)


def open_startup_toolboxes():
    """
    Refill toolbox docks that already exist (restored workspace or framework restart), then open the toolboxes
    flagged "Open On Startup". Failures are logged, never raised: startup must go on.
    """

    try:
        library = _library()
        existing = [x['toolbox'] for x in list_open_toolboxes()]
        names = existing + [x for x in library.startup_toolboxes() if x not in existing]
    except Exception:
        logger.exception('Toolbox: could not read startup toolboxes.')
        return
    for name in names:
        try:
            open_toolbox(name)
        except Exception:
            logger.exception(f'Toolbox: could not open "{name}" on startup.')


# --- AI / MCP ----------------------------------------------------------------------------------------------------

def api_open_toolbox(toolbox='All Tools', area=None, tab_with=None):
    """
    Open a toolbox in its own Maya dock (or raise it when already open). Several toolboxes can be open at once.

    :param str toolbox: Toolbox name.
    :param str area: 'left', 'right', 'top', 'bottom', 'floating' or 'tab'. None = last used place.
    :param str tab_with: For area='tab', the open toolbox to tab next to.
    :return: ``{'ok', 'result', 'message'}`` with the open docks as result.
    :rtype: dict
    """

    try:
        window = open_toolbox(toolbox, area=area, tab_with=tab_with)
        return {'ok': True, 'result': list_open_toolboxes(), 'message': f'Opened {window.toolbox_name}.'}
    except Exception as exc:
        return {'ok': False, 'result': None, 'message': f'{type(exc).__name__}: {exc}'}


def api_list_open_toolboxes():
    """
    List the toolbox docks open in Maya.

    :return: ``{'ok', 'result', 'message'}`` with ``[{'toolbox', 'control', 'floating', 'visible'}]``.
    :rtype: dict
    """

    try:
        result = list_open_toolboxes()
        return {'ok': True, 'result': result, 'message': f'{len(result)} toolbox dock(s) open.'}
    except Exception as exc:
        return {'ok': False, 'result': None, 'message': f'{type(exc).__name__}: {exc}'}


def api_close_toolbox(toolbox):
    """
    Close one toolbox dock.

    :param str toolbox: Toolbox name.
    :return: ``{'ok', 'result', 'message'}``.
    :rtype: dict
    """

    control = _control_name(toolbox)
    if not _control_exists(control):
        return {'ok': False, 'result': None, 'message': f'{toolbox} is not open.'}
    window = _live_window(toolbox)
    _WINDOWS.pop(toolbox, None)
    cmds.deleteUI(control)
    if window is not None and shiboken.isValid(window):
        window.setObjectName('')
        window.deleteLater()
    return {'ok': True, 'result': list_open_toolboxes(), 'message': f'Closed {toolbox}.'}


# --- Menu --------------------------------------------------------------------------------------------------------

def fill_toolbox_menu(menu):
    """
    Rebuild the toolbox menu: one entry per toolbox plus "New Personal Toolbox".

    :param qtwidgets.QMenu menu: The menu being shown.
    """

    menu.clear()
    try:
        library = _library()
        library.refresh_if_changed()
        names = library.toolbox_names()
        open_names = set(x['toolbox'] for x in list_open_toolboxes())
    except Exception as exc:
        logger.exception('Toolbox: could not load toolboxes.')
        menu.addAction(f'Toolbox unavailable: {exc}').setEnabled(False)
        return
    personal_started = False
    for name in names:
        if not library.get_toolbox(name).is_shared and not personal_started:
            menu.addSeparator()
            personal_started = True
        action = menu.addAction(name, lambda name=name: open_toolbox_later(name))
        action.setCheckable(True)
        action.setChecked(name in open_names)
    menu.addSeparator()
    menu.addAction('New Personal Toolbox...', _new_personal_toolbox)
    if open_names:
        menu.addAction('Close All Toolboxes', close_all_toolboxes)


def _new_personal_toolbox():
    """
    Ask for a name, create a personal toolbox and open it.
    """

    name, ok = qtwidgets.QInputDialog.getText(None, 'New Personal Toolbox', 'Name of your new toolbox:')
    name = (name or '').strip()
    if not ok or not name:
        return
    try:
        _library().create_toolbox(name, shared=False)
    except ValueError as exc:
        qtwidgets.QMessageBox.warning(None, 'New Personal Toolbox', str(exc))
        return
    open_toolbox_later(name)


def attach_toolbox_menu(menu):
    """
    Make a QMenu list the toolboxes, refreshed every time it opens so new toolboxes show up without a restart.

    :param qtwidgets.QMenu menu: Menu to fill (e.g. Mechanical Art > ToolBox).
    """

    menu.aboutToShow.connect(lambda menu=menu: fill_toolbox_menu(menu))
