"""
Animated gifs, in a label and in a button.

Unchanged in behaviour. The gif is loaded when the widget is built, and a hover button keeps
it still until the mouse is over it.
"""

# mca imports
from mca.common import log
from mca.common.pyqt import pygui


logger = log.MCA_LOGGER


class MovieLabel(pygui.qtwidgets.QLabel if pygui.AVAILABLE else object):
    """A gif playing in a label."""

    def __init__(self, gif_file, speed=100, parent=None, play=True):
        """
        :param str gif_file: The .gif.
        :param int speed: Percent of its natural speed.
        :param parent: The parent widget.
        :param bool play: Start it straight away.
        """

        super(MovieLabel, self).__init__(parent)
        self.setMouseTracking(True)

        self.movie = pygui.qtgui.QMovie(gif_file, pygui.qtcore.QByteArray(), self)
        self.movie.setCacheMode(pygui.qtgui.QMovie.CacheAll)
        self.movie.setSpeed(speed)
        self.setMovie(self.movie)
        if play:
            self.movie.start()


class GifToolButton(pygui.qtwidgets.QToolButton if pygui.AVAILABLE else object):
    """A gif playing on a button."""

    def __init__(self, file_name, size=(100, 100), parent=None, play=True):
        """
        :param str file_name: The .gif.
        :param tuple size: How big to draw it, in pixels.
        :param parent: The parent widget.
        :param bool play: Start it straight away.
        """

        super(GifToolButton, self).__init__(parent)
        self.icon_size = pygui.qtcore.QSize(int(size[0]), int(size[1]))

        self.movie = pygui.qtgui.QMovie(file_name, pygui.qtcore.QByteArray(), self)
        self.movie.setCacheMode(pygui.qtgui.QMovie.CacheAll)
        self.movie.setSpeed(100)
        self.movie.frameChanged.connect(self.update_movie_icon)

        self.setText('')
        self.setMinimumSize(self.icon_size)
        self.setIconSize(self.icon_size)
        if play:
            self.movie.start()

    def update_movie_icon(self):
        """Put the current frame on the button."""

        self.setIcon(pygui.qtgui.QIcon(self.movie.currentPixmap()))


class GifHoverToolButton(GifToolButton):
    """The same button, still until the mouse is over it."""

    def __init__(self, file_name, size=(100, 100), parent=None):
        """
        :param str file_name: The .gif.
        :param tuple size: How big to draw it.
        :param parent: The parent widget.
        """

        super(GifHoverToolButton, self).__init__(file_name, size=size, parent=parent,
                                                 play=False)
        # One frame, so the button is not empty before anybody hovers over it.
        self.movie.jumpToFrame(0)
        self.update_movie_icon()

    def enterEvent(self, event):
        """
        :param event: The enter event.
        """

        self.movie.start()
        super(GifHoverToolButton, self).enterEvent(event)

    def leaveEvent(self, event):
        """
        :param event: The leave event.
        """

        self.movie.stop()
        super(GifHoverToolButton, self).leaveEvent(event)
