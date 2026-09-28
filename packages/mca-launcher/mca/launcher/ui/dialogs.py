"""
The small windows: asking, telling, and showing a long job's progress.

Two things the old versions got wrong and these do not:

- a question returned the button's **text** ('&Yes'), which the caller then compared against
  'Yes' after patching the ampersand out. These return a bool.
- a response was shown by pulling its message out at the call site, so a failure sometimes
  became an information dialog. :func:`show_response` takes the response and picks the right
  dialog from ``ok``.
"""

# python imports
import logging

# PySide6 imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPlainTextEdit
from PySide6.QtWidgets import QProgressBar, QVBoxLayout

# mca imports
from mca.launcher.core import resources


logger = logging.getLogger('mca-launcher')


def ask(title, text, parent=None, detail=''):
    """
    Ask a yes or no question.

    :param str title: The window title, without the 'MCA' prefix.
    :param str text: The question.
    :param parent: Parent widget.
    :param str detail: Extra text, behind the Details button.
    :return: True for yes.
    :rtype: bool
    """

    box = _box(title, text, parent, detail, QMessageBox.Icon.Question)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def tell(title, text, parent=None, detail=''):
    """
    Say something that is not a problem.

    :param str title: The window title.
    :param str text: The message.
    :param parent: Parent widget.
    :param str detail: Extra text, behind the Details button.
    """

    box = _box(title, text, parent, detail, QMessageBox.Icon.Information)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def complain(title, text, parent=None, detail=''):
    """
    Say something went wrong.

    :param str title: The window title.
    :param str text: What went wrong, and what to do about it.
    :param parent: Parent widget.
    :param str detail: Extra text, behind the Details button.
    """

    logger.error('%s: %s', title, text)
    box = _box(title, text, parent, detail, QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def show_response(response, parent=None, title='', detail=''):
    """
    Show a response the right way round.

    :param dict response: A response from the API.
    :param parent: Parent widget.
    :param str title: The window title. Defaults to something sensible.
    :param str detail: Extra text, behind the Details button.
    :return: Whether it was ok, so a caller can carry on or stop.
    :rtype: bool
    """

    if response.get('ok'):
        tell(title or 'Done', response.get('message') or 'Done.', parent, detail)
        return True
    complain(title or 'That did not work', response.get('message') or 'It failed.',
             parent, detail)
    return False


def _box(title, text, parent, detail, icon):
    box = QMessageBox(parent)
    box.setWindowTitle('MCA {}'.format(title) if title else 'MCA Launcher')
    box.setIcon(icon)
    box.setText(str(text))
    if detail:
        box.setDetailedText(str(detail))
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return box


class ProgressWindow(QDialog):
    """
    A modal window for a job measured in minutes, with its output on show.

    Installing dependencies takes a few minutes on a cold cache. A spinner that says
    "please wait" for that long is indistinguishable from a hang, so pip's own output goes
    in a box the artist can read - and copy, when something goes wrong.

    It has no cancel button on purpose: stopping pip halfway leaves a folder that is neither
    the old set of packages nor the new one, which is the state this whole subsystem exists
    to avoid.
    """

    def __init__(self, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MCA {}'.format(title))
        self.setModal(True)
        self.setMinimumSize(620, 320)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        animation = resources.movie('Logo_InAndOut.gif')
        if animation:
            self.picture = QLabel()
            self.movie = QMovie(animation)
            self.picture.setMovie(self.movie)
            self.movie.start()
            layout.addWidget(self.picture)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)     # a job of unknown length
        layout.addWidget(self.bar)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(4000)
        layout.addWidget(self.output)

    def say(self, line):
        """
        Add a line of progress, and keep the window responsive.

        Called from the install code as pip produces output. Pumping events here rather than
        running the install on a thread keeps the whole subsystem single-threaded, which is
        worth more than the milliseconds a thread would save: there is no shared state to
        get wrong, and a traceback reads top to bottom.

        :param str line: The line.
        """

        self.output.appendPlainText(str(line))
        self.output.ensureCursorVisible()
        QApplication.processEvents()

    def finish(self):
        """Close the window."""

        if hasattr(self, 'movie'):
            self.movie.stop()
        self.accept()
