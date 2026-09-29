"""
The windows every tool is built from, and the dialogs, offscreen.

    python tests/test_common_windows.py
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

        # The part that needs no Qt: the one that used to return the typed text when the
        # artist pressed Cancel.
        from mca.common.pyqt import messages

        suite.check('a button label is read without its keyboard mnemonic',
                    messages.clean_label('&Cancel') == 'Cancel' and
                    messages.clean_label('&Yes') == 'Yes')
        return

    from mca.common.pyqt import common_windows, file_dialogs, messages
    from mca.common.pyqt.qt_utils import windows
    from mca.common.startup.configs import consts

    application = pygui.qtwidgets.QApplication.instance() or pygui.qtwidgets.QApplication([])
    suite.check('Qt starts offscreen', application is not None)

    # Keep the suite's settings out of the machine's.
    pygui.qtcore.QSettings.setDefaultFormat(pygui.qtcore.QSettings.IniFormat)
    pygui.qtcore.QCoreApplication.setOrganizationName('MechanicalArtTests')

    # ---------------------------------------------------------------- #
    # A window
    # ---------------------------------------------------------------- #
    window = common_windows.MCAMainWindow('Rig Builder', version='2.0.0', show_window=True)
    suite.check('a window is titled for its tool and its version',
                window.windowTitle() == 'MCA - Rig Builder 2.0.0', window.windowTitle())
    suite.check('and the framework knows it is one of its own by more than that title',
                windows.is_ours(window) and window.property(windows.WINDOW_PROPERTY))
    suite.check('it has a layout to put things in',
                window.main_layout is not None and window.centralWidget() is not None)

    # The single-instance check used to match the title inside every open window, so
    # renaming a tool left two of it open. It matches the tool, not the words.
    second = common_windows.MCAMainWindow('Rig Builder', version='2.0.0')
    application.processEvents()
    still_open = [one for one in windows.get_all_mca_windows()
                  if getattr(one, 'tool_name', '') == 'Rig Builder']
    suite.check('opening a tool twice leaves one of it', len(still_open) == 1,
                str(len(still_open)))
    suite.check('and it is the new one', still_open[0] is second)

    # Even when the title is different, which is what a version bump does.
    third = common_windows.MCAMainWindow('Rig Builder', version='3.0.0')
    application.processEvents()
    still_open = [one for one in windows.get_all_mca_windows()
                  if getattr(one, 'tool_name', '') == 'Rig Builder']
    suite.check('and a new version of the same tool replaces the old one rather than '
                'opening beside it', len(still_open) == 1 and still_open[0] is third,
                str([one.windowTitle() for one in still_open]))

    another = common_windows.MCAMainWindow('Pose Skinner')
    application.processEvents()
    suite.check('a different tool is left alone', another.isVisible() and third.isVisible())

    # ---------------------------------------------------------------- #
    # Geometry
    # ---------------------------------------------------------------- #
    # os.getlogin() raises in a process with no controlling terminal, and it was the
    # organisation name for every window's settings.
    suite.check('the settings are kept under one organisation, not under the user name',
                third.settings.organizationName() ==
                common_windows.SETTINGS_ORGANISATION,
                third.settings.organizationName())
    suite.check('and there is a user name for anything that wants one, with a fallback',
                bool(common_windows.current_user()))

    third.resize(640, 480)
    third.close()
    application.processEvents()
    reopened = common_windows.MCAMainWindow('Rig Builder', version='3.0.0')
    suite.check('a window remembers where it was',
                reopened.size().width() == 640, str(reopened.size()))

    # ---------------------------------------------------------------- #
    # A dockable window
    # ---------------------------------------------------------------- #
    host = pygui.qtwidgets.QMainWindow()
    host.setWindowTitle('Maya')
    host.show()

    dock = common_windows.MCADockableWindow('Shelf', parent=host)
    suite.check('a dockable window docks into the window it was given',
                dock in host.findChildren(common_windows.MCADockableWindow))
    suite.check('and it is one of ours too', windows.is_ours(dock))

    # isinstance(value, qtcore.Qt) - Qt is not a class, so the documented way of passing an
    # area raised TypeError before it reached the strings.
    suite.check('a dock area can be given as a word',
                dock.get_area('right') == pygui.qtcore.Qt.RightDockWidgetArea)
    suite.check('or as the Qt value itself, which used to raise',
                dock.get_area(pygui.qtcore.Qt.TopDockWidgetArea) ==
                pygui.qtcore.Qt.TopDockWidgetArea)
    suite.check('and anything else falls back to the left rather than failing',
                dock.get_area('sideways') == pygui.qtcore.Qt.LeftDockWidgetArea)

    # ---------------------------------------------------------------- #
    # A panel, and a progress window
    # ---------------------------------------------------------------- #
    panel = common_windows.ParentableWidget('Options', parent=host)
    suite.check('a panel has a layout and no window of its own',
                panel.main_layout is not None and panel.parent() is host)

    class Owner(object):
        closed = False

        def close_window(self):
            Owner.closed = True

    progress = common_windows.ProgressBarWindow('Exporting', progress_instance=Owner())
    progress.close()
    application.processEvents()
    suite.check('a progress window tells whatever owns it when it closes - which was '
                'commented out before', Owner.closed)

    # ---------------------------------------------------------------- #
    # A .ui file that is not there
    # ---------------------------------------------------------------- #
    suite.check('asking for a .ui file that does not exist answers None rather than '
                'raising', common_windows.load_ui_file(os.path.join(suite.temp, 'no.ui'))
                is None)
    suite.check('and a window asked for one still builds, with a layout',
                common_windows.MCAMainWindow(
                    'No Designer File', ui_path=os.path.join(suite.temp, 'no.ui'),
                    show_window=False).main_layout is not None)

    # ---------------------------------------------------------------- #
    # Dialogs
    # ---------------------------------------------------------------- #
    suite.check('a button label is read without its keyboard mnemonic',
                messages.clean_label('&Cancel') == 'Cancel')

    box = messages.MCAMessageBox('Test', 'Does this work?')
    suite.check('a message box is titled for the framework',
                box.windowTitle() == 'MCA Test', box.windowTitle())
    # The stylesheet was read, applied, and then overwritten twice by one-line rules.
    suite.check('and its stylesheet is not thrown away by the rules applied after it',
                'min-width' in box.styleSheet(), box.styleSheet()[-60:])
    box.deleteLater()

    suite.check('the message button constants can still be asked for by name',
                messages.M_YES == pygui.qtwidgets.QMessageBox.Yes,
                str(messages.M_YES))

    # file dialogs: the default start folder was evaluated at import time, so it was
    # whatever the project root was when the framework loaded.
    os.environ[consts.MCA_PROJECT_ROOT] = suite.temp
    suite.check('a file dialog starts in the project that is open now',
                file_dialogs._starting_folder() == suite.temp,
                file_dialogs._starting_folder())
    os.environ[consts.MCA_PROJECT_ROOT] = os.path.join(suite.temp, 'not-there')
    suite.check('and a project folder that is not there starts it nowhere rather than '
                'somewhere wrong', file_dialogs._starting_folder() == '')

    for widget in (window, second, third, reopened, another, dock, panel, host):
        try:
            widget.close()
            widget.deleteLater()
        except Exception:                                            # noqa: BLE001
            pass
    application.processEvents()

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('common_windows', body))
