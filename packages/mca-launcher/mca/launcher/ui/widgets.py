"""
The pieces the launcher window is made of.

One tile per DCC: a big icon to press, and a dropdown of what is installed. A tile knows
nothing about launching - it emits what was pressed and the window calls the API.
"""

# python imports
import logging

# PySide6 imports
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

# mca imports
from mca.launcher.core import resources
from mca.launcher.ui import style


logger = logging.getLogger('mca-launcher')


class DccTile(QWidget):
    """
    One DCC: an icon to press, and the versions installed beneath it.

    :signal launch_requested: (dcc name, key) when the icon is pressed.
    :signal choice_changed: (dcc name, key) when the dropdown changes.
    """

    launch_requested = Signal(str, str)
    choice_changed = Signal(str, str)

    def __init__(self, dcc_name, label, icon_name, parent=None):
        super().__init__(parent)

        self.dcc_name = dcc_name
        self.setFixedSize(style.TILE_WIDTH, style.TILE_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.button = QPushButton()
        self.button.setObjectName('{}_pushButton'.format(dcc_name))
        self.button.setFixedSize(style.ICON_SIZE + 6, style.ICON_SIZE + 6)
        path = resources.icon(icon_name)
        if path:
            self.button.setIcon(QIcon(path))
            self.button.setIconSize(QSize(style.ICON_SIZE, style.ICON_SIZE))
        else:
            self.button.setText(label)
        self.button.setToolTip('Start {}'.format(label))
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.versions = QComboBox()
        self.versions.setObjectName('{}_comboBox'.format(dcc_name))
        self.versions.setToolTip('Which version to start')
        layout.addWidget(self.versions)

        self.name_label = QLabel(label)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.name_label)

        self.button.clicked.connect(self._pressed)
        self.versions.currentIndexChanged.connect(self._changed)

    # -- what it shows -------------------------------------------------- #
    def set_targets(self, keys, chosen=''):
        """
        Fill the dropdown.

        :param list(str) keys: The versions installed, newest first.
        :param str chosen: Which one to select.
        """

        self.versions.blockSignals(True)
        self.versions.clear()
        self.versions.addItems([str(key) for key in keys])
        if chosen and str(chosen) in [str(key) for key in keys]:
            self.versions.setCurrentIndex([str(key) for key in keys].index(str(chosen)))
        self.versions.blockSignals(False)

        installed = bool(keys)
        self.button.setEnabled(installed)
        self.versions.setEnabled(installed)
        if not installed:
            # Say why the button does nothing, rather than leaving a dead icon.
            self.button.setToolTip('{} is not installed on this machine.'
                                   .format(self.name_label.text()))
            self.name_label.setText('{}  (not installed)'.format(self.dcc_name.title()))

    def current_key(self):
        """
        :return: The selected version, or ''.
        :rtype: str
        """

        return self.versions.currentText().strip()

    # -- signals -------------------------------------------------------- #
    def _pressed(self):
        self.launch_requested.emit(self.dcc_name, self.current_key())

    def _changed(self):
        key = self.current_key()
        if key:
            self.choice_changed.emit(self.dcc_name, key)


class UnrealTile(DccTile):
    """
    Unreal, where what you pick is a project rather than a version.

    Same tile, with a plus and a minus under the dropdown.

    :signal add_requested: when + is pressed.
    :signal remove_requested: (project path) when - is pressed.
    """

    add_requested = Signal()
    remove_requested = Signal(str)

    def __init__(self, dcc_name, label, icon_name, parent=None):
        super().__init__(dcc_name, label, icon_name, parent)
        self.setFixedHeight(style.TILE_HEIGHT + 30)

        self.paths = {}

        row = QHBoxLayout()
        self.add_button = QPushButton('+')
        self.add_button.setToolTip('Add an Unreal project')
        self.remove_button = QPushButton('-')
        self.remove_button.setToolTip('Forget the selected Unreal project')
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        self.layout().addLayout(row)

        self.add_button.clicked.connect(self.add_requested.emit)
        self.remove_button.clicked.connect(self._remove_pressed)

    def set_projects(self, entries):
        """
        :param list(dict) entries: From ``api.unreal_projects`` - path, name, exists, engine.
        """

        self.paths = {}
        labels = []
        for entry in entries:
            label = entry['name'] if entry.get('exists') else '{} (missing)'.format(entry['name'])
            self.paths[label] = entry['path']
            labels.append(label)

        self.versions.blockSignals(True)
        self.versions.clear()
        self.versions.addItems(labels)
        self.versions.blockSignals(False)

        has_any = bool(labels)
        self.button.setEnabled(has_any)
        self.versions.setEnabled(has_any)
        self.remove_button.setEnabled(has_any)
        self.button.setToolTip('Start the selected Unreal project' if has_any
                               else 'Add an Unreal project with + first')

    def current_key(self):
        """
        :return: The selected project's path, or ''.
        :rtype: str
        """

        return self.paths.get(self.versions.currentText().strip(), '')

    def _remove_pressed(self):
        path = self.current_key()
        if path:
            self.remove_requested.emit(path)


class Banner(QFrame):
    """The project row at the top: which project, and the buttons that manage them."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        label = QLabel(' Project: ')
        label.setObjectName('project_name_QLabel')
        label.setFixedHeight(26)
        layout.addWidget(label)

        self.projects = QComboBox()
        self.projects.setObjectName('project_comboBox')
        self.projects.setMinimumWidth(200)
        self.projects.setToolTip('Which project the DCCs are started for')
        layout.addWidget(self.projects)

        self.add_button = QPushButton('Add Project')
        self.add_button.setObjectName('add_project_pushButton')
        layout.addWidget(self.add_button)

        self.edit_button = QPushButton('Edit Project')
        self.edit_button.setObjectName('update_project_pushButton')
        layout.addWidget(self.edit_button)

        self.remove_button = QPushButton('Remove Project')
        self.remove_button.setObjectName('remove_project_pushButton')
        layout.addWidget(self.remove_button)

        layout.addItem(_stretch())

    def set_projects(self, names, current=''):
        """
        :param list(str) names: The project names.
        :param str current: Which to select.
        """

        self.projects.blockSignals(True)
        self.projects.clear()
        self.projects.addItems(names)
        if current and current in names:
            self.projects.setCurrentIndex(names.index(current))
        self.projects.blockSignals(False)

        self.remove_button.setEnabled(bool(names))
        self.edit_button.setEnabled(bool(names))

    def current_project(self):
        """
        :return: The selected project name, or ''.
        :rtype: str
        """

        return self.projects.currentText().strip()


def _stretch():
    from PySide6.QtWidgets import QSpacerItem
    return QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
