"""
Finding and closing the framework's windows, offscreen.

``startup.shutdown()`` calls this to take every framework window down, and every window calls
it on the way up to replace the one it replaces - so getting it wrong means either windows
that survive a shutdown or windows that close when they should not. Neither is visible until
it happens to somebody.

Runs under any Python with PySide6 or PySide2, and skips cleanly where there is neither::

    python tests/test_qt_windows.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def body(suite):
    from mca.common.pyqt import pygui

    if not pygui.AVAILABLE:
        suite.note('skipped', 'no Qt here')
        print('SKIPPED: neither PySide6 nor PySide2 is installed for this Python.')

        # The part that does not need Qt: asking a missing binding for something must say
        # what is actually wrong rather than raising AttributeError far from the cause.
        message = suite.raises('without Qt, using it explains itself',
                               getattr, pygui.qtwidgets, 'QWidget')
        suite.check('and names both bindings it looked for',
                    'PySide6' in message and 'PySide2' in message, message)
        return

    from mca.common.pyqt.qt_utils import windows

    application = pygui.qtwidgets.QApplication.instance() or \
        pygui.qtwidgets.QApplication([])
    suite.check('Qt starts offscreen', application is not None)
    suite.check('and the binding is named', pygui.BINDING in ('PySide6', 'PySide2'),
                pygui.BINDING)

    # ---------------------------------------------------------------- #
    # What counts as one of ours
    # ---------------------------------------------------------------- #
    marked = pygui.qtwidgets.QMainWindow()
    marked.setWindowTitle('Rig Builder 2.0')      # a title with no MCA in it at all
    windows.mark(marked)
    marked.show()

    legacy = pygui.qtwidgets.QMainWindow()
    legacy.setWindowTitle('MCA - Pose Skinner 1.0.0')   # an older tool, no property
    legacy.show()

    editor = pygui.qtwidgets.QMainWindow()
    editor.setWindowTitle('MCA Editor')
    editor.show()

    stranger = pygui.qtwidgets.QMainWindow()
    stranger.setWindowTitle('Maya')
    stranger.show()

    hidden = pygui.qtwidgets.QMainWindow()
    hidden.setWindowTitle('MCA - Not Shown')
    windows.mark(hidden)

    application.processEvents()

    suite.check('a window the framework marked is ours whatever its title says',
                windows.is_ours(marked))
    suite.check('a window from before the marker is still found by its title',
                windows.is_ours(legacy))
    suite.check('the editor is left alone', not windows.is_ours(editor))
    suite.check('and somebody else\'s window is not ours', not windows.is_ours(stranger))

    ours = windows.get_all_mca_windows()
    suite.check('both of ours are found, and nothing else',
                sorted(one.windowTitle() for one in ours) ==
                ['MCA - Pose Skinner 1.0.0', 'Rig Builder 2.0'],
                str([one.windowTitle() for one in ours]))
    suite.check('a window that was never shown is not in the list',
                hidden not in ours)

    # ---------------------------------------------------------------- #
    # The one that could never work
    # ---------------------------------------------------------------- #
    # get_mca_window_by_name compared the widget to the string - `if win == name` - so it
    # answered None every time, whatever was passed in.
    found = windows.get_mca_window_by_name('Pose Skinner')
    suite.check('looking a window up by name finds it', found is legacy,
                str(found and found.windowTitle()))
    suite.check('and one that is not open answers None',
                windows.get_mca_window_by_name('Nothing Like This') is None)
    suite.check('asking for nothing answers None', windows.get_mca_window_by_name('') is None)

    # ---------------------------------------------------------------- #
    # Docked windows
    # ---------------------------------------------------------------- #
    host = pygui.qtwidgets.QMainWindow()
    host.setWindowTitle('Maya')
    dock = pygui.qtwidgets.QDockWidget('MCA - Shelf', host)
    windows.mark(dock)
    other_dock = pygui.qtwidgets.QDockWidget('Attribute Editor', host)
    host.addDockWidget(pygui.qtcore.Qt.LeftDockWidgetArea, dock)
    host.addDockWidget(pygui.qtcore.Qt.RightDockWidgetArea, other_dock)
    host.show()
    application.processEvents()

    suite.check('every dock in a window is found', len(windows.get_all_docked_windows(host)) == 2)
    suite.check('and only ours among them',
                [one.windowTitle() for one in windows.get_all_mca_docked_windows(host)] ==
                ['MCA - Shelf'],
                str([one.windowTitle() for one in windows.get_all_mca_docked_windows(host)]))
    suite.check('asking about no window answers an empty list rather than raising',
                windows.get_all_docked_windows(None) == [])

    suite.check('closing ours closes one of the two',
                windows.close_all_mca_docked_windows(host) == 1)

    # ---------------------------------------------------------------- #
    # Closing
    # ---------------------------------------------------------------- #
    named = pygui.qtwidgets.QWidget(host)
    named.setObjectName('mca_progress')
    suite.check('a widget can be closed by its object name',
                windows.remove_widgets_by_name(host, 'mca_progress') == 1)
    suite.check('and a name nobody has closes nothing',
                windows.remove_widgets_by_name(host, 'not_here') == 0)

    closed = windows.close_all_mca_windows()
    application.processEvents()
    suite.check('closing the framework\'s windows closes both of them', closed == 2, str(closed))
    suite.check('and leaves the editor and the DCC alone',
                editor.isVisible() and stranger.isVisible())
    suite.check('and says nothing is left to close the second time',
                windows.close_all_mca_windows() == 0)

    # ---------------------------------------------------------------- #
    # The main window
    # ---------------------------------------------------------------- #
    main = windows.get_main_qt_window()
    suite.check('a top level window is found to parent to, even with nothing focused - the '
                'old version asked for the active window and answered None whenever the '
                'application was in the background',
                main is not None, str(main))

    for widget in (editor, stranger, host, hidden):
        widget.close()
        widget.deleteLater()
    application.processEvents()

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('qt_windows', body))
