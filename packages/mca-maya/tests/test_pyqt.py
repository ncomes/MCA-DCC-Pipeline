"""
Qt in Maya: mca.mya.pyqt - ma_main_window, dialogs and the window classes.

A batch Maya has no interface, so the parts that reach for Maya's own widgets can only be checked
for answering None politely. The parts that are ours - the window classes, the event handling on
them, the argument handling in the dialogs - are checked properly, against a QApplication the suite
makes itself.

    mayapy tests/test_pyqt.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def qt_application():
    """
    A QApplication to build widgets against, if this Maya will give one.

    A batch Maya will not. It starts a ``QGuiApplication`` of its own - enough for fonts and
    images, not enough for widgets - and Qt allows only one application object per process, so a
    ``QApplication`` cannot be made alongside it. ``QWidget()`` then aborts the process outright:
    not an exception, a Windows fatal error, which is worth knowing before writing a suite that
    builds windows.

    :return: The application, or None when widgets cannot be made here.
    """

    try:
        from mca.common.pyqt.pygui import qtwidgets
    except ImportError:
        return None
    try:
        existing = qtwidgets.QApplication.instance()
        if existing is not None:
            # A QGuiApplication answers this too, and is not enough to build a widget on.
            return existing if isinstance(existing, qtwidgets.QApplication) else None
        return qtwidgets.QApplication([])
    except Exception:                                                   # noqa: BLE001
        return None


def check_main_window(suite, application):
    import maya.cmds as cmds
    from mca.mya.pyqt.utils import ma_main_window

    # This suite is worth running in both kinds of Maya - batch, where it checks that nothing
    # reaches for an interface that is not there, and interactive, where it checks that the same
    # calls find the real thing.
    from mca.common.pyqt.pygui import qtwidgets
    batch = cmds.about(batch=True)
    if batch:
        suite.check('a batch Maya has no main window, and says so',
                    ma_main_window.get_maya_window() is None)
        suite.check('nor a main menu bar', ma_main_window.get_main_menu_menubar() is None)
        suite.check('and no main window name', ma_main_window.get_main_window_name() == '')
    else:
        suite.check('an interactive Maya gives up its main window',
                    isinstance(ma_main_window.get_maya_window(), qtwidgets.QWidget))
        suite.check('and its menu bar',
                    isinstance(ma_main_window.get_main_menu_menubar(), qtwidgets.QMenuBar))
        suite.check('and its window name',
                    ma_main_window.get_main_window_name() == ma_main_window.MAIN_WINDOW_NAME,
                    ma_main_window.get_main_window_name())

    # A widget handed in comes straight back, so a caller holding one does not special-case it.
    if application is not None:
        from mca.common.pyqt.pygui import qtwidgets
        widget = qtwidgets.QWidget()
        try:
            suite.check('a widget passed in comes back as itself',
                        ma_main_window.get_maya_window(widget) is widget)
        finally:
            widget.deleteLater()

    suite.check('a pointer of None wraps to None', ma_main_window.wrap_instance(None) is None)
    suite.check('and something that is not a pointer answers None rather than raising',
                ma_main_window.wrap_instance('not a pointer') is None)
    suite.check('a Maya control name that is not there answers None',
                ma_main_window.to_qt_object('no_such_control_anywhere') is None)

    # The class lookup that was the bug: it read the class name off the object and looked for it in
    # QtGui, where no widget class has lived since Qt 5, so every wrapped object came back a bare
    # QWidget.
    # The code below the module docstring, which is where these have to be gone from - the
    # docstring quotes them, because it is explaining what they were.
    source = open(ma_main_window.__file__.replace('.pyc', '.py'), encoding='utf-8').read()
    code = source.split('"""', 2)[-1]
    suite.check('the class lookup searches QtWidgets', 'qtwidgets, qtcore' in code, 'not found')
    suite.check('the PySide 1 fallback is gone', 'from PySide.shiboken' not in code)
    suite.check('and the dead sip branch with it', "'sip' in globals()" not in code)

    for name in ('delete_workspace_control', 'is_enable_workspace_control', 'show_time_slider',
                 'switch_xray_joints', 'setup_axis', 'ManageNodeEditors', 'SuspendUI',
                 'get_progress_bar', 'isolate_current_panel'):
        suite.check('{} is gone - no callers'.format(name),
                    not hasattr(ma_main_window, name))


def check_dialogs(suite):
    import maya.cmds as cmds
    from mca.mya.pyqt import dialogs

    # The bug: MAYA_MAIN_WINDOW was a module-level get_maya_window() call, so every dialog's default
    # parent was whatever the main window was the first time anything imported the module.
    suite.check('the main window is asked for when it is needed, not at import',
                not hasattr(dialogs, 'MAYA_MAIN_WINDOW'))
    if cmds.about(batch=True):
        suite.check('and asking for it in a batch Maya answers None',
                    dialogs.maya_main_window() is None)
    else:
        suite.check('and asking for it in an interactive Maya finds the window',
                    dialogs.maya_main_window() is not None)

    # -- the file dialog style ------------------------------------------------------------ #
    # The bug: optionVar answers 0 for a variable nobody has written, and fileDialog2 has no style
    # 0 - so on a fresh Maya profile the dialogs asked for something that does not exist.
    had_it = cmds.optionVar(exists=dialogs.DIALOG_STYLE_OPTION_VARIABLE)
    original = cmds.optionVar(query=dialogs.DIALOG_STYLE_OPTION_VARIABLE) if had_it else None
    try:
        cmds.optionVar(remove=dialogs.DIALOG_STYLE_OPTION_VARIABLE)
        suite.check('the option variable really is unset',
                    cmds.optionVar(query=dialogs.DIALOG_STYLE_OPTION_VARIABLE) == 0)
        suite.check('and the style comes back as a style Maya has',
                    dialogs.file_dialog_style() in (dialogs.OS_NATIVE_DIALOG,
                                                    dialogs.MAYA_NATIVE_DIALOG),
                    str(dialogs.file_dialog_style()))
        cmds.optionVar(intValue=(dialogs.DIALOG_STYLE_OPTION_VARIABLE,
                                 dialogs.MAYA_NATIVE_DIALOG))
        suite.check("the user's preference is used when they have one",
                    dialogs.file_dialog_style() == dialogs.MAYA_NATIVE_DIALOG)
        suite.check('and what the caller asks for wins over it',
                    dialogs.file_dialog_style(dialogs.OS_NATIVE_DIALOG) ==
                    dialogs.OS_NATIVE_DIALOG)
        suite.check('a style that is not a style falls back rather than being passed on',
                    dialogs.file_dialog_style(99) == dialogs.MAYA_NATIVE_DIALOG)
    finally:
        cmds.optionVar(remove=dialogs.DIALOG_STYLE_OPTION_VARIABLE)
        if original is not None:
            cmds.optionVar(intValue=(dialogs.DIALOG_STYLE_OPTION_VARIABLE, original))

    # -- the in-view message --------------------------------------------------------------- #
    if cmds.about(batch=True):
        suite.check('a batch Maya has no viewport to write in, and says so',
                    dialogs.display_view_message('anything') is False)
    else:
        suite.check('an interactive Maya writes the message',
                    dialogs.display_view_message('mca-maya suite', header='Suite') is True)
    suite.check('the fade time is capped so a long message does not stay up forever',
                dialogs.MAXIMUM_FADE_TIME == 10000)
    suite.check('good and error have colours', set(dialogs.VIEW_MESSAGE_COLOURS) ==
                {'good', 'error'}, str(dialogs.VIEW_MESSAGE_COLOURS))


def check_windows(suite, application):
    import maya.cmds as cmds
    from mca.common.pyqt.pygui import qtcore
    from mca.mya.pyqt import mayawindows
    from mca.mya.utils import events

    register = events.EventsRegister()
    register.unregister_all()

    # -- the mixin on its own -------------------------------------------------------------- #
    watcher = mayawindows.MayaWindowEvents()
    # The bug: `if events_register: self.events_register = ... if events_register else None` -
    # so with False the attribute was never created at all, and the next register_event failed on
    # an AttributeError rather than making a register.
    suite.check('the register attribute exists even when one was not asked for',
                hasattr(watcher, 'events_register'))
    suite.check('and is None until it is needed', watcher.events_register is None)

    calls = []
    watcher.register_event('suite_window_selection', lambda *args: calls.append(args))
    suite.check('registering makes the register on first use',
                watcher.events_register is not None)
    suite.check('and remembers the name', watcher._callbacks == ['suite_window_selection'],
                str(watcher._callbacks))

    harness.new_scene()
    node = cmds.createNode('transform', name='clicked')
    cmds.select(node, replace=True)
    suite.check('the listener fires', len(calls) >= 1, str(calls))

    watcher.register_after_new_event('suite_window_new', lambda *args: None)
    suite.check('a second listener is remembered too', len(watcher._callbacks) == 2,
                str(watcher._callbacks))
    taken_off = watcher.unregister_all()
    suite.check('both come off together', len(taken_off) == 2, str(taken_off))
    suite.check('and the list is empty', watcher._callbacks == [])
    suite.check('taking off something that was never on answers False',
                watcher.unregister_event('never_registered') is False)

    eager = mayawindows.MayaWindowEvents(events_register=True)
    suite.check('asking for the register up front makes it now',
                eager.events_register is not None)

    # -- the window classes ----------------------------------------------------------------- #
    # The bug: MCAMayaWindow's eventFilter calls self.unregister_event on close and the class did
    # not inherit MayaWindowEvents, so it had no such method - while MCAMayaQWidget, twenty lines
    # below, did.
    suite.check('a Maya tool window can register events',
                issubclass(mayawindows.MCAMayaWindow, mayawindows.MayaWindowEvents))
    suite.check('and so can a Maya panel',
                issubclass(mayawindows.MCAMayaQWidget, mayawindows.MayaWindowEvents))
    suite.check('a tool window is a main window',
                hasattr(mayawindows.MCAMayaWindow, 'setCentralWidget'))

    # The default parent used to be a module-level get_maya_window() call, evaluated once at import.
    import inspect
    signature = inspect.signature(mayawindows.MCAMayaWindow.__init__)
    suite.check('the default parent is None, worked out when a window is made',
                signature.parameters['parent'].default is None)
    suite.check('the same for a panel',
                inspect.signature(mayawindows.MCAMayaQWidget.__init__)
                .parameters['parent'].default is None)
    suite.check('and the module no longer holds a main window worked out at import time',
                not hasattr(mayawindows, 'MAYA_MAIN_WINDOW'))

    if application is None:
        # A batch Maya starts a QGuiApplication of its own, and Qt allows one application object
        # per process - so a QApplication cannot be made and a QWidget cannot be built. The class
        # structure above is everything that can be checked without one; building a window here
        # aborts the process.
        suite.note('qt', 'a batch Maya gives a QGuiApplication, so no windows were built')
        register.unregister_all()
        return

    window = mayawindows.MCAMayaWindow(title='Suite Window', show_window=False)
    try:
        suite.check('a window is made', window is not None)
        suite.check('with the title it was given',
                    'Suite Window' in window.windowTitle(), window.windowTitle())
        suite.check('and nothing registered yet', window._callbacks == [])

        fired = []
        window.register_event('suite_real_window', lambda *args: fired.append(args))
        suite.check('a window can listen for the selection',
                    window._callbacks == ['suite_real_window'], str(window._callbacks))
        cmds.select(clear=True)
        cmds.select(node, replace=True)
        suite.check('and hears it', len(fired) >= 1, str(fired))

        # This is the crash the whole arrangement is for: closing without unregistering leaves Maya
        # calling into a destroyed Qt object. The window is shown first because Qt sends no close
        # event for a window that was never shown - which is the second half of the bug, checked
        # below.
        window.show()
        window.close()
        suite.check('closing the window takes its listeners off',
                    window._callbacks == [], str(window._callbacks))
        suite.check('and they are off the register too',
                    'suite_real_window' not in register.events, str(sorted(register.events)))
        before = len(fired)
        cmds.select(clear=True)
        suite.check('so the selection no longer reaches it', len(fired) == before)
    finally:
        window.unregister_all()
        window.deleteLater()

    # The case Qt gives no close event for at all.
    hidden = mayawindows.MCAMayaWindow(title='Never Shown', show_window=False)
    hidden.register_event('suite_never_shown', lambda *args: None)
    suite.check('a window that is never shown can still listen',
                'suite_never_shown' in register.events, str(sorted(register.events)))
    suite.check('and Qt sends it no close event, which is why close alone is not enough',
                hidden.close() is True and 'suite_never_shown' in register.events,
                str(sorted(register.events)))
    hidden.deleteLater()
    # destroyed fires when Qt gets round to it, which is on the next pass of the event loop.
    application.processEvents()
    application.sendPostedEvents(None, int(qtcore.QEvent.DeferredDelete))
    application.processEvents()
    suite.check('destroying it takes its listener off - the second net',
                'suite_never_shown' not in register.events, str(sorted(register.events)))

    panel = mayawindows.MCAMayaQWidget(show_window=False)
    try:
        suite.check('a panel is made', panel is not None)
        panel.register_after_open_event('suite_panel_open', lambda *args: None)
        suite.check('and can listen', panel._callbacks == ['suite_panel_open'])
        panel.close()
        suite.check('and stops when it closes', panel._callbacks == [])
    finally:
        panel.unregister_all()
        panel.deleteLater()

    register.unregister_all()
    suite.check('nothing is left registered in this Maya', register.events == {},
                str(register.events))


def body(suite):
    harness.add_sibling_packages()
    application = qt_application()
    check_main_window(suite, application)
    check_dialogs(suite)
    check_windows(suite, application)
    suite.note('qt_application', bool(application))
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('pyqt', body))
