"""
The progress window a long job talks to.

```python
from mca.common.tools.progressbar import progressbar_ui

progress = progressbar_ui.ProgressBarStandard()
progress.update_status(40, 'Skinning the left arm')
progress.update_status(100, 'Done')          # 100 closes it
```

One window, wherever it is asked for - it is a singleton, so a rig build and the skinning it
calls both talk to the same one, and a job that runs inside another job adds a second bar
rather than fighting over the first.

It builds its widgets in code. The version this replaces loaded
``progressbar/ui/progressbar_widget.ui`` through Qt Designer for a label and a progress bar,
which is two widgets and a layout.
"""

# python imports

# MCA python imports
from mca.common import log
from mca.common.modifiers import singleton
from mca.common.pyqt import common_windows
from mca.common.pyqt.pygui import qtcore, qtwidgets


logger = log.MCA_LOGGER

#: How tall one bar's row is, and so how much taller a second bar makes the window.
ROW_HEIGHT = 90

#: How wide the window is. It does not resize: the text in it does.
WIDTH = 435


class ProgressRow(qtwidgets.QFrame):
    """
    One job's line: what it is doing, and how far along it is.
    """

    def __init__(self, parent=None):
        """
        :param parent: The window it goes in.
        """

        super(ProgressRow, self).__init__(parent=parent)

        self.setFrameShape(qtwidgets.QFrame.StyledPanel)
        self.setSizePolicy(qtwidgets.QSizePolicy.Expanding, qtwidgets.QSizePolicy.Fixed)
        self.setMinimumHeight(ROW_HEIGHT - 10)

        self.status_label = qtwidgets.QLabel('Working...', parent=self)
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(qtcore.Qt.AlignLeft | qtcore.Qt.AlignVCenter)

        self.progress_bar = qtwidgets.QProgressBar(parent=self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        layout = qtwidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)


class ProgressBarStandard(singleton.SimpleSingleton):
    """
    The one progress window, and the rows in it.

    Every method is safe to call when there is no window and no row - a job that reports
    progress after the artist has closed the window carries on rather than raising into
    whatever it was doing.
    """

    VERSION = '2.0.0'

    def __init__(self, title='Progress', style=None, parent=None):
        """
        :param str title: What the window is called. Only the first caller's title is used,
            since there is only one window; :meth:`set_title` changes it afterwards.
        :param str style: A stylesheet name.
        :param parent: The parent window.
        """

        self.title = title
        self.style = style
        self.parent = parent
        self.ui = None
        self.rows = []
        self._closing = False
        self.open_window()

    # -- the window ----------------------------------------------------- #
    def open_window(self):
        """
        Show the window, with one row in it, unless it is already up.

        :return: The window, or None where there is no Qt to build one with.
        """

        if self.ui is not None:
            return self.ui

        self.ui = common_windows.ProgressBarWindow(
            title=self.title,
            version=ProgressBarStandard.VERSION,
            progress_instance=self,
            style=self.style,
            parent=self.parent)
        self.ui.setSizePolicy(qtwidgets.QSizePolicy.Fixed, qtwidgets.QSizePolicy.Fixed)
        self.ui.setFixedWidth(WIDTH)
        self.add_progressbar()
        self.ui.show()

        return self.ui

    def set_title(self, title):
        """
        :param str title: What the window should say now.
        """

        self.title = title
        if self.ui is not None:
            self.ui.setWindowTitle(title)

    def _fit(self):
        """
        Make the window as tall as the rows in it.

        The version this replaces worked this out as ``len(rows) * 200`` when adding a row
        and ``len(rows) * 100`` when removing one, so taking a row away left the window half
        the height it should have been - and with one row left, half the height it started.
        """

        if self.ui is None:
            return

        self.ui.setFixedHeight(max(1, len(self.rows)) * ROW_HEIGHT + 30)

    # -- the rows ------------------------------------------------------- #
    def add_progressbar(self):
        """
        Add a row - for a job that has started inside the job already running.

        :return: The row.
        :rtype: ProgressRow or None
        """

        if self.ui is None:
            return None

        row = ProgressRow(parent=self.ui)
        self.ui.main_layout.addWidget(row)
        self.rows.append(row)
        self._fit()

        return row

    def remove_progressbar(self):
        """
        Take the newest row away.

        :return: Whether there was one to take. The version this replaces raised IndexError
            on an empty list, from a function whose job is tidying up.
        :rtype: bool
        """

        if not self.rows:
            return False

        row = self.rows.pop()
        row.setParent(None)
        row.deleteLater()
        self._fit()

        return True

    @property
    def row(self):
        """
        :return: The row being worked on, or None.
        :rtype: ProgressRow or None
        """

        return self.rows[-1] if self.rows else None

    # -- reporting ------------------------------------------------------ #
    def update_label(self, value):
        """
        Say what is happening.

        :param str value: A few words for the artist.
        """

        if self.row is not None:
            self.row.status_label.setText(str(value))

    def update_value(self, value):
        """
        Say how far along it is.

        :param value: A percentage, 0 to 100. A float is fine.
        :return: Whether the window is still open afterwards.
        :rtype: bool

        Two things here. The old version passed the value straight to ``setValue``, and its
        own docstring called it a float - which PySide2 quietly truncated and **PySide6
        refuses**, so every progress bar in the framework would have raised inside Maya 2025
        and 2026. And at 100 it called ``time.sleep(0.5)`` on the user interface thread, so
        the whole DCC stopped for half a second at the end of every job, to let the artist
        admire a full bar.
        """

        if value is None or self.row is None:
            return self.ui is not None

        try:
            percentage = int(round(float(value)))
        except (TypeError, ValueError):
            logger.warning('A progress value has to be a number, not %r.', value)
            return True

        if percentage < 0:
            logger.warning('A progress value below zero (%s) was reported.', percentage)
            return True

        percentage = min(percentage, 100)
        if percentage != self.row.progress_bar.value():
            self.row.progress_bar.setValue(percentage)
            # A long job blocks the event loop, so the window only repaints if we ask. It is
            # asked once per percent rather than once per call: the old version asked on
            # every update, and a skinning loop reports thousands of times.
            application = qtwidgets.QApplication.instance()
            if application:
                application.processEvents()

        if percentage >= 100:
            if len(self.rows) > 1:
                self.remove_progressbar()
            else:
                self.close_window()
                return False

        return True

    def update_status(self, value, message):
        """
        Both at once, which is what most callers want.

        :param value: A percentage, 0 to 100.
        :param str message: A few words for the artist.
        :return: Whether the window is still open afterwards.
        :rtype: bool
        """

        self.update_label(message)

        return self.update_value(value)

    # -- finishing ------------------------------------------------------ #
    def close_window(self):
        """
        Close the window and forget this instance, so the next job gets a fresh one.

        The window tells its owner when it closes and the owner closes its window, so this
        guards against being called twice - once by the artist clicking the corner, once by
        the job finishing.
        """

        if self._closing:
            return
        self._closing = True
        try:
            self.rows = []
            if self.ui is not None:
                window, self.ui = self.ui, None
                window.close()
                window.deleteLater()
        finally:
            self._closing = False
            singleton.clear_cls(self)
