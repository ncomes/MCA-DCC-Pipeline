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
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPlainTextEdit
from PySide6.QtWidgets import QProgressBar, QVBoxLayout

# mca imports
from mca.launcher.core import resources
from mca.launcher.core.contract import failed


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


#: How tall the logo is drawn in the progress window.
LOGO_HEIGHT = 96


class Job(QThread):
    """
    One long call, run off the main thread so the window it reports to stays alive.

    The work itself - pip, an interpreter starting, a DCC launching - is in ``core`` and
    ``api``, which know nothing about Qt. That is what makes this safe: the thread touches no
    widget. It emits lines, and Qt delivers them to the window on the main thread, because a
    signal across threads is queued.

    :signal line: a line of progress.
    :signal answered: the return value, whatever it is.
    """

    line = Signal(str)
    answered = Signal(object)

    def __init__(self, function, parent=None):
        """
        :param callable function: Called with one argument, a progress callback.
        """

        super().__init__(parent)
        self.function = function

    def run(self):
        """Run it, and answer whatever comes back - including a failure."""

        try:
            answer = self.function(self.line.emit)
        except Exception as error:
            # A raise here would end the thread with nobody listening and the window would
            # sit there forever. It becomes a failed response like any other.
            logger.exception('the background job raised')
            answer = failed(str(error) or type(error).__name__)
        self.answered.emit(answer)


class ProgressWindow(QDialog):
    """
    A modal window for a job measured in minutes, with its output on show.

    Installing dependencies takes a few minutes on a cold cache. A spinner that says
    "please wait" for that long is indistinguishable from a hang, so pip's own output goes
    in a box the artist can read - and copy, when something goes wrong.

    It has no cancel button on purpose: stopping pip halfway leaves a folder that is neither
    the old set of packages nor the new one, which is the state this whole subsystem exists
    to avoid.

    :meth:`run` is how it should be used. The first version pumped events from :meth:`say`,
    so the window only came back to life when pip printed something - and pip is silent for
    a minute at a time while it downloads a wheel or while the import check runs. The logo
    froze, the bar stopped, and a working install looked exactly like a hang.
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
            self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.movie = QMovie(animation)
            # At its own size the logo fills the window and pushes pip's output - the thing
            # somebody actually watches during a first install - off the bottom.
            self.movie.jumpToFrame(0)
            natural = self.movie.currentPixmap().size()
            if natural.height() > 0:
                scale = LOGO_HEIGHT / float(natural.height())
                self.movie.setScaledSize(QSize(int(natural.width() * scale), LOGO_HEIGHT))
            self.picture.setMovie(self.movie)
            self.picture.setFixedHeight(LOGO_HEIGHT)
            self.movie.start()
            layout.addWidget(self.picture)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)     # a job of unknown length
        layout.addWidget(self.bar)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(4000)
        layout.addWidget(self.output)

        self.job = None
        self.answer = None

    def run(self, function):
        """
        Run a long call on a worker thread, with this window up and moving, and answer it.

        :param callable function: Called with one argument, a progress callback it may call
            from the worker thread as often as it likes.
        :return: Whatever the function returned - or a failed response when it raised.
        """

        self.answer = None
        self.job = Job(function, parent=self)
        self.job.line.connect(self.say)
        self.job.answered.connect(self._answered)

        self.show()
        self.job.start()
        # A modal loop, so the movie animates and the bar sweeps while the work happens. The
        # answered signal is queued, so it can only arrive inside this loop - it cannot close
        # the window before the loop starts.
        self.exec()
        self.job.wait()
        return self.answer

    def _answered(self, answer):
        """
        :param answer: What the job returned.
        """

        self.answer = answer
        self.finish()

    def say(self, line):
        """
        Add a line of progress.

        Always called on the main thread: the worker emits, Qt queues, this runs here. No
        events are pumped - the event loop is running on its own now, which is the whole
        point of the thread.

        :param str line: The line.
        """

        self.output.appendPlainText(str(line))
        self.output.ensureCursorVisible()

    def finish(self):
        """Close the window."""

        if hasattr(self, 'movie'):
            self.movie.stop()
        self.accept()

    def closeEvent(self, event):
        """
        Refuse to go while the job is still running.

        There is no cancel, and the window closing out from under a running install would
        leave its output going nowhere.

        :param event: The close event.
        """

        if self.job is not None and self.job.isRunning() and self.answer is None:
            event.ignore()
            return
        super().closeEvent(event)
