"""
Sending files to source control without the window freezing, and the dialog shown while it
happens.

Split out of ``unified_register`` so the register's own modules can share it without importing
the window.

It was ``register_p4``, and everything in it was named for Perforce: the class, the dialog's
title, its message. Which source control this is, if any, is
:mod:`mca.common.sourcecontrol`'s business - so the worker asks the interface, and the dialog
says the name of whatever answered.
"""

# MCA python imports
from mca.common import log, sourcecontrol
from mca.common.pyqt import movies
from mca.common.pyqt.pygui import qtcore, qtwidgets
from mca.common.tools.assetregister import register_widgets


logger = log.MCA_LOGGER


class SubmitWorker(qtcore.QThread):
    """
    Send files in, on a thread of its own, so the window keeps repainting while the source
    control client does its work.

    How it went is left on :attr:`success` and :attr:`message` rather than carried by a signal
    of its own, so a caller can read them once the built-in ``finished`` signal has fired.

    :ivar bool success: Whether the files went in.
    :ivar str message: What source control said, for showing the artist when they did not.
    """

    def __init__(self, file_paths, description, parent=None):
        """
        :param list(str) file_paths: The files to send.
        :param str description: What changed, for the history.
        """

        super().__init__(parent)
        self._file_paths = list(file_paths)
        self._description = description
        self.success = False
        self.message = ''

    def run(self):
        """
        Hand the files to whichever source control this machine has.
        """

        try:
            result = sourcecontrol.submit(self._file_paths, description=self._description)
            self.success = bool(result)
            self.message = result.message
        except Exception as error:                                   # noqa: BLE001
            # A thread's target has nothing above it to catch anything, and the window is
            # waiting on this one finishing.
            logger.exception('Submitting raised on the worker thread: %s', error)
            self.success = False
            self.message = str(error)


class SubmitProgressDialog(qtwidgets.QDialog):
    """
    What the artist looks at while the files are going in.

    A GIF where there is one, and a line of text. No buttons: closing it would not stop the
    submit, so it closes itself when the worker is done.
    """

    def __init__(self, message='', parent=None):
        """
        :param str message: What to say. Names whichever source control this is by default.
        :param parent: The window it belongs to.
        """

        super().__init__(parent)
        self.setWindowTitle(sourcecontrol.name().title())
        message = message or 'Submitting to {0}...'.format(sourcecontrol.name())
        self.setModal(True)
        # Hide the title bar's close button so users can't dismiss the
        # dialog mid-submit (closing the dialog wouldn't actually cancel
        # the underlying p4 subprocess).
        self.setWindowFlags(
            qtcore.Qt.Dialog | qtcore.Qt.CustomizeWindowHint
            | qtcore.Qt.WindowTitleHint)

        layout = qtwidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        gif_path = register_widgets.waggle_gif()
        if gif_path:
            self._movie_label = movies.MovieLabel(gif_path, parent=self)
            self._movie_label.setFixedSize(120, 120)
            self._movie_label.setScaledContents(True)
            self._movie_label.setAlignment(qtcore.Qt.AlignCenter)
            layout.addWidget(self._movie_label, 0, qtcore.Qt.AlignHCenter)

        self._status_label = qtwidgets.QLabel(message)
        self._status_label.setAlignment(qtcore.Qt.AlignCenter)
        layout.addWidget(self._status_label)

    def set_message(self, message):
        """Update the status text shown below the GIF."""
        self._status_label.setText(message)
