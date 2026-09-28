"""
The look, and the small helpers that apply it.

The stylesheet itself is the one the launcher has always used, kept in
``resources/stylesheets`` so a change to the colours is not a change to the code.
"""

# python imports
import logging

# mca imports
from mca.launcher.resources.stylesheets import mca_stylesheet


logger = logging.getLogger('mca-launcher')

#: Panel and window sizes, in one place rather than sprinkled through the windows as
#: setFixedSize calls.
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 560
TILE_WIDTH = 132
TILE_HEIGHT = 172
ICON_SIZE = 84


def apply(widget):
    """
    Put the launcher's stylesheet on a widget.

    :param widget: Any QWidget.
    """

    try:
        widget.setStyleSheet(mca_stylesheet.LAUNCHER_STYLE)
    except Exception as error:
        # A launcher that will not open because a stylesheet has a typo in it would be a
        # poor trade.
        logger.warning('Could not apply the stylesheet: %s', error)
