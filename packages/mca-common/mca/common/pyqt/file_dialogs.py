"""
Asking the artist for a file or a folder.

``open_file_dialog(start_dir=paths.project_root())`` - the default was evaluated when the
module was imported, which inside a DCC is once, when the framework loads. Switching project
afterwards left every file dialog in the framework opening in the old project's folder. The
defaults are worked out when the dialog is opened now.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.paths import paths
from mca.common.pyqt import pygui


logger = log.MCA_LOGGER

#: What a dialog shows when nobody says otherwise.
ALL_FILES = 'All Files (*.*)'


def _starting_folder(start_dir=None):
    """
    :param str start_dir: Where to start. None uses the project root.
    :return: A folder that exists, or ''.
    :rtype: str
    """

    folder = start_dir or paths.project_root()
    return folder if folder and os.path.isdir(folder) else ''


def open_file_dialog(start_dir=None, filters=ALL_FILES, parent=None, single=False):
    """
    Ask for one or more files.

    :param str start_dir: Where to start. None uses the project root, read now rather than
        when this module was imported.
    :param str filters: ``'All Files (*.*);;Images (*.tga *.png)'``.
    :param parent: The parent widget.
    :param bool single: Ask for one file rather than several.
    :return: The files chosen, which is empty when the artist cancelled.
    :rtype: list(str)
    """

    dialog = pygui.qtwidgets.QFileDialog(parent)
    folder = _starting_folder(start_dir)
    if folder:
        dialog.setDirectory(folder)

    modes = getattr(pygui.qtwidgets.QFileDialog, 'FileMode', pygui.qtwidgets.QFileDialog)
    dialog.setFileMode(modes.ExistingFile if single else modes.ExistingFiles)
    if filters:
        dialog.setNameFilter(filters)

    if not pygui.exec_dialog(dialog):
        return []
    return list(dialog.selectedFiles())


def open_folder_dialog(start_dir=None, caption='Select a folder', parent=None):
    """
    Ask for a folder.

    :param str start_dir: Where to start. None uses the project root.
    :param str caption: The dialog's title.
    :param parent: The parent widget.
    :return: The folder chosen, or '' when the artist cancelled.
    :rtype: str
    """

    options = getattr(pygui.qtwidgets.QFileDialog, 'Option', pygui.qtwidgets.QFileDialog)
    chosen = pygui.qtwidgets.QFileDialog.getExistingDirectory(
        parent, caption, _starting_folder(start_dir), options.ShowDirsOnly)
    return chosen or ''


def save_file_dialog(start_dir=None, filters=ALL_FILES, caption='Save', parent=None):
    """
    Ask where to save something.

    :param str start_dir: Where to start.
    :param str filters: File filters.
    :param str caption: The dialog's title.
    :param parent: The parent widget.
    :return: The path chosen, or ''.
    :rtype: str
    """

    chosen, _ = pygui.qtwidgets.QFileDialog.getSaveFileName(
        parent, caption, _starting_folder(start_dir), filters)
    return chosen or ''


def open_files_and_folders(caption='Select files and folders', start_dir=None,
                           filters=ALL_FILES, parent=None):
    """
    Ask for files and folders together, which Qt has no dialog for.

    Qt's file dialog opens a folder when you double-click it rather than choosing it, so
    this uses the non-native dialog and overrides accept.

    :param str caption: The dialog's title.
    :param str start_dir: Where to start.
    :param str filters: File filters.
    :param parent: The parent widget.
    :return: What was chosen.
    :rtype: list(str)
    """

    dialog = pygui.qtwidgets.QFileDialog(parent, windowTitle=caption)
    modes = getattr(pygui.qtwidgets.QFileDialog, 'FileMode', pygui.qtwidgets.QFileDialog)
    options = getattr(pygui.qtwidgets.QFileDialog, 'Option', pygui.qtwidgets.QFileDialog)
    dialog.setFileMode(modes.ExistingFiles)
    dialog.setOption(options.DontUseNativeDialog, True)

    folder = _starting_folder(start_dir)
    if folder:
        dialog.setDirectory(folder)
    if filters:
        dialog.setNameFilter(filters)

    # Accept what is selected instead of opening it.
    dialog.accept = lambda: pygui.qtwidgets.QDialog.accept(dialog)

    field = dialog.findChild(pygui.qtwidgets.QLineEdit)
    stack = dialog.findChild(pygui.qtwidgets.QStackedWidget)
    view = stack.findChild(pygui.qtwidgets.QListView) if stack else None
    if view is not None and field is not None:
        def update_text():
            names = ['"{}"'.format(index.data())
                     for index in view.selectionModel().selectedRows()]
            field.setText(' '.join(names))

        view.selectionModel().selectionChanged.connect(update_text)
        dialog.directoryEntered.connect(lambda: field.setText(''))

    if not pygui.exec_dialog(dialog):
        return []
    return list(dialog.selectedFiles())
