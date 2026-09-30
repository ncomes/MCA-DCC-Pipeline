"""
The small tools: the progress window, and the example tool that shows how to write one.

    python tests/test_tools.py

Offscreen, so it runs on a build machine. Everything that needs no Qt is checked either way.
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

    # ---------------------------------------------------------------- #
    # the example tool's work, which needs no window - that is the point of it
    # ---------------------------------------------------------------- #
    from mca.common.tools.example_tool import example_ui

    suite.check('the example tool\'s work is a function with no Qt in it',
                example_ui.greeting(' Comes ') == 'Hello, Comes.',
                example_ui.greeting(' Comes '))
    suite.check('and it copes with being asked for nothing',
                example_ui.greeting('') == example_ui.greeting(None))

    if not pygui.AVAILABLE:
        suite.note('skipped', 'no Qt here')
        print('SKIPPED: neither PySide6 nor PySide2 is installed for this Python.')
        return

    from mca.common.modifiers import singleton
    from mca.common.tools.progressbar import progressbar_ui

    application = pygui.qtwidgets.QApplication.instance() or pygui.qtwidgets.QApplication([])
    suite.check('Qt starts offscreen', application is not None)
    pygui.qtcore.QSettings.setDefaultFormat(pygui.qtcore.QSettings.IniFormat)
    pygui.qtcore.QCoreApplication.setOrganizationName('MechanicalArtTests')

    # ---------------------------------------------------------------- #
    # the example tool's window
    # ---------------------------------------------------------------- #
    example = example_ui.ExampleUI()
    suite.check('the example window is titled for the framework, the tool and its version',
                example.windowTitle() == 'MCA - Example 2.0.0', example.windowTitle())
    example.name_field.setText('Comes')
    example.run_button.click()
    suite.check('and pressing its button runs the work and shows the answer',
                example.answer == 'Hello, Comes.', example.answer)
    example.close()

    # ---------------------------------------------------------------- #
    # the progress window
    # ---------------------------------------------------------------- #
    singleton.clear_cls(progressbar_ui.ProgressBarStandard)
    progress = progressbar_ui.ProgressBarStandard(title='Skinning')
    suite.check('a progress window opens with one row in it',
                len(progress.rows) == 1 and progress.ui is not None)
    suite.check('asked for again from anywhere else, it is the same window',
                progressbar_ui.ProgressBarStandard() is progress)

    progress.update_status(40, 'The left arm')
    suite.check('a percentage and a message both land',
                progress.row.progress_bar.value() == 40 and
                progress.row.status_label.text() == 'The left arm',
                '{0} {1}'.format(progress.row.progress_bar.value(),
                                 progress.row.status_label.text()))

    # PySide6 refuses a float where an int is wanted, and the old version's own docstring
    # called this a float - so every progress bar in the framework raised in Maya 2025.
    suite.check('a float percentage is rounded rather than raising',
                progress.update_status(62.6, 'Still the left arm') and
                progress.row.progress_bar.value() == 63,
                str(progress.row.progress_bar.value()))
    suite.check('the bar counts from nothing to a hundred',
                progress.row.progress_bar.minimum() == 0 and
                progress.row.progress_bar.maximum() == 100)

    # -- a job inside a job ------------------------------------------- #
    tall = progress.ui.height()
    progress.add_progressbar()
    suite.check('a job that starts inside another job gets a row of its own',
                len(progress.rows) == 2 and progress.ui.height() > tall,
                '{0} rows, {1} high'.format(len(progress.rows), progress.ui.height()))
    # More than a hundred is finished, not a number for Qt to argue about.
    progress.update_status(150, 'The inner job finished')
    suite.check('and finishing it takes that row away, leaving the outer one',
                len(progress.rows) == 1 and progress.ui is not None)
    suite.check('at the height it was before, not half of it - the old version worked the '
                'height out two different ways',
                progress.ui.height() == tall,
                '{0} vs {1}'.format(progress.ui.height(), tall))
    suite.check('with the outer job\'s own progress untouched',
                progress.row.progress_bar.value() == 63,
                str(progress.row.progress_bar.value()))

    # -- reaching a hundred closes it --------------------------------- #
    suite.check('the last row reaching a hundred closes the window',
                progress.update_status(100, 'Done') is False and progress.ui is None)
    suite.check('and the next job gets a fresh window rather than the closed one',
                progressbar_ui.ProgressBarStandard() is not progress)
    singleton.clear_cls(progressbar_ui.ProgressBarStandard)

    # -- nothing raises after it has gone ----------------------------- #
    # update_label and update_value both read rows[-1], so a job reporting progress after the
    # artist closed the window raised IndexError into whatever it was doing.
    closed = progressbar_ui.ProgressBarStandard(title='Closing early')
    closed.close_window()
    suite.check('a job reporting progress after the window was closed carries on',
                closed.update_value(50) is False and closed.update_status(80, 'still going') is False)
    suite.check('and taking a row away when there are none says so rather than raising',
                closed.remove_progressbar() is False)
    suite.check('closing twice is not an error either - the window closing tells its owner, '
                'and the owner closes its window',
                closed.close_window() is None)

    # -- a value that is not a number --------------------------------- #
    singleton.clear_cls(progressbar_ui.ProgressBarStandard)
    progress = progressbar_ui.ProgressBarStandard()
    suite.check('a percentage that is not a number is complained about, not raised over',
                progress.update_value('nearly there') is True)
    suite.check('and a negative one is refused without moving the bar',
                progress.update_value(-10) is True and progress.row.progress_bar.value() == 0)
    progress.close_window()

    suite.note('qt', pygui.QT_VERSION if hasattr(pygui, 'QT_VERSION') else 'unknown')


if __name__ == '__main__':
    sys.exit(harness.run('tools', body))
