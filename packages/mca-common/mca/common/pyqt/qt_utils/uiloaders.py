"""
Loading a Qt Designer file.

One loader, in :mod:`mca.common.pyqt.common_windows`, which this calls. The version this
replaces opened the file without checking that it opened, so a path that was wrong by a
letter handed the loader a closed file and answered None, with nothing saying why.
"""

# mca imports
from mca.common.pyqt import common_windows


def ui_importer(ui_path, parent=None):
    """
    :param str ui_path: The .ui file.
    :param parent: What to parent the result to.
    :return: The widget it describes, or None - and a line in the log saying which file.
    """

    return common_windows.load_ui_file(ui_path, parent)
