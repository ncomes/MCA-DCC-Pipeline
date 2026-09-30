"""
Standalone window for the MCA Toolbox.

DCCs with their own docking (Maya) wrap :class:`toolbox_widgets.ToolboxWidget` themselves; this window is for plain
Python sessions, quick testing, and DCCs that just need a floating window.
"""

# MCA python imports
from mca.common.pyqt import common_windows
from mca.common.tools.toolbox import toolbox_model, toolbox_widgets

__all__ = ['ToolboxWindow']


class ToolboxWindow(common_windows.MCAMainWindow):
    """
    A main window hosting one toolbox widget. The title follows the toolbox shown.
    """

    VERSION = '2.0.0'

    def __init__(self, toolbox_name=toolbox_model.ALL_TOOLS, library=None, parent=None, show_window=True):
        """
        :param str toolbox_name: Toolbox to open.
        :param toolbox_library.ToolboxLibrary library: Library to use; defaults to the running DCC's library.
        :param qtwidgets.QWidget parent: Parent window.
        :param bool show_window: Show immediately.
        """

        super().__init__(title=f'Toolbox - {toolbox_name}', version=self.VERSION, parent=parent, show_window=False)
        self.toolbox_widget = toolbox_widgets.ToolboxWidget(toolbox_name, library=library, parent=self)
        self.main_layout.addWidget(self.toolbox_widget)
        self.toolbox_widget.toolbox_changed.connect(self._update_title)
        self.resize(360, 720)
        if show_window:
            self.show()

    def _update_title(self, name):
        """
        :param str name: The toolbox now shown.
        """

        self.setWindowTitle(f'MCA - Toolbox - {name} {self.VERSION}')
