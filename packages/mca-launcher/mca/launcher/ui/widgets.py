"""
The pieces the launcher window is made of.

**One row per DCC**, not a tile: icon, name, version, and a button whose job changes with
what is selected. The first arrangement stacked an icon over a dropdown over a label, three
of them side by side, and it read badly at a glance - the labels collided with the icons, the
versions were hard to line up against each other, and two thirds of the window was empty.

A row reads left to right in the order the questions get asked: which application, which
version, go.
"""

# python imports
import logging

# PySide6 imports
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

# mca imports
from mca.launcher.core import resources
from mca.launcher.ui import style


logger = logging.getLogger('mca-launcher')

#: Shown beside a version the machine does not have.
NOT_INSTALLED = '  (not installed)'


class DccRow(QFrame):
    """
    One application: icon, name, version, and one button.

    The button is the whole point of the design. Pick an installed version and it says
    **Launch**; pick one the machine does not have and it says **Install** - so a version
    that is supported but missing is visible and actionable in the same control, rather than
    absent with no explanation.

    Right-clicking a row offers what can be done to the version it is showing - a shortcut
    for it, its dependencies - because that is where somebody is already looking when they
    think of it.

    :signal launch_requested: (dcc name, key)
    :signal install_requested: (dcc name, key)
    :signal choice_changed: (dcc name, key)
    :signal shortcut_requested: (dcc name, key)
    :signal check_requested: (dcc name, key)
    :signal reinstall_requested: (dcc name, key)
    """

    launch_requested = Signal(str, str)
    install_requested = Signal(str, str)
    choice_changed = Signal(str, str)
    shortcut_requested = Signal(str, str)
    check_requested = Signal(str, str)
    reinstall_requested = Signal(str, str)

    def __init__(self, dcc_name, label, icon_name, parent=None):
        super().__init__(parent)

        self.dcc_name = dcc_name
        self.label = label
        self.keys = []
        self.installed = {}

        self.setObjectName('dcc_row')
        self.setFixedHeight(style.ROW_HEIGHT)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        # -- the icon, which is also the launch button ------------------- #
        self.button = QPushButton()
        self.button.setObjectName('{}_pushButton'.format(dcc_name))
        self.button.setFixedSize(style.ICON_SIZE + 12, style.ICON_SIZE + 12)
        icon = resources.icon(icon_name)
        if icon:
            self.button.setIcon(QIcon(icon))
            self.button.setIconSize(QSize(style.ICON_SIZE, style.ICON_SIZE))
        else:
            self.button.setText(label[:4])
        layout.addWidget(self.button)

        # -- name over status -------------------------------------------- #
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name_label = QLabel(label)
        self.name_label.setObjectName('dcc_name')
        names.addWidget(self.name_label)
        self.detail_label = QLabel('')
        self.detail_label.setObjectName('dcc_detail')
        names.addWidget(self.detail_label)
        layout.addLayout(names)

        layout.addStretch(1)

        # -- version ----------------------------------------------------- #
        self.versions = QComboBox()
        self.versions.setObjectName('{}_comboBox'.format(dcc_name))
        self.versions.setFixedWidth(style.VERSION_WIDTH)
        self.versions.setToolTip('Which version to start')
        layout.addWidget(self.versions)

        # -- the one button whose job changes ---------------------------- #
        self.action = QPushButton('Launch')
        self.action.setObjectName('dcc_action')
        self.action.setFixedWidth(style.ACTION_WIDTH)
        layout.addWidget(self.action)

        self.button.clicked.connect(self._primary)
        self.action.clicked.connect(self._primary)
        self.versions.currentIndexChanged.connect(self._changed)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    # ------------------------------------------------------------------ #
    # What it shows
    # ------------------------------------------------------------------ #
    def set_targets(self, targets, chosen=''):
        """
        Fill the version list.

        :param list(dict) targets: From ``api.dcc_targets`` - key, label, installed, detail.
        :param str chosen: Which key to select.
        """

        self.keys = [str(one['key']) for one in targets]
        self.installed = {str(one['key']): bool(one.get('installed', True))
                          for one in targets}

        self.versions.blockSignals(True)
        self.versions.clear()
        for one in targets:
            key = str(one['key'])
            self.versions.addItem(key if self.installed[key] else key + NOT_INSTALLED)
        if chosen and str(chosen) in self.keys:
            self.versions.setCurrentIndex(self.keys.index(str(chosen)))
        elif any(self.installed.values()):
            # Otherwise land on something that can actually be started.
            first = next(key for key in self.keys if self.installed[key])
            self.versions.setCurrentIndex(self.keys.index(first))
        self.versions.blockSignals(False)

        self.versions.setEnabled(bool(self.keys))
        self._update_action()

    def current_key(self):
        """
        :return: The selected version, without any decoration.
        :rtype: str
        """

        index = self.versions.currentIndex()
        return self.keys[index] if 0 <= index < len(self.keys) else ''

    def current_is_installed(self):
        """
        :return: Whether the selected version is on this machine.
        :rtype: bool
        """

        return bool(self.installed.get(self.current_key(), False))

    def set_detail(self, text):
        """
        :param str text: The small line under the name - where it is, or what is missing.
        """

        self.detail_label.setText(str(text))

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _update_action(self):
        key = self.current_key()
        if not key:
            self.action.setText('Launch')
            self.action.setEnabled(False)
            self.button.setEnabled(False)
            self.set_detail('not installed')
            self.action.setToolTip('{} was not found on this machine.'.format(self.label))
            return

        installed = self.current_is_installed()
        self.action.setEnabled(True)
        self.button.setEnabled(True)
        self.action.setText('Launch' if installed else 'Install')
        self.action.setProperty('mode', 'launch' if installed else 'install')
        self.action.setToolTip(
            'Start {} {}'.format(self.label, key) if installed else
            'Get {} {} - the project\'s installer if it has one, otherwise the download page'
            .format(self.label, key))
        # A property change needs a restyle to show.
        self.action.style().unpolish(self.action)
        self.action.style().polish(self.action)

    def _primary(self):
        key = self.current_key()
        if not key:
            return
        if self.current_is_installed():
            self.launch_requested.emit(self.dcc_name, key)
        else:
            self.install_requested.emit(self.dcc_name, key)

    def _changed(self):
        self._update_action()
        key = self.current_key()
        if key and self.current_is_installed():
            self.choice_changed.emit(self.dcc_name, key)

    def _context_menu(self, where):
        """
        What can be done to the version this row is showing.

        :param QPoint where: Where the click was, in this row.
        """

        key = self.current_key()
        if not key or not self.current_is_installed():
            return

        menu = QMenu(self)
        action = menu.addAction('Create Desktop Shortcut')
        action.triggered.connect(
            lambda checked=False: self.shortcut_requested.emit(self.dcc_name, key))
        menu.addSeparator()
        action = menu.addAction('Check Dependencies')
        action.triggered.connect(
            lambda checked=False: self.check_requested.emit(self.dcc_name, key))
        action = menu.addAction('Reinstall Dependencies')
        action.triggered.connect(
            lambda checked=False: self.reinstall_requested.emit(self.dcc_name, key))
        menu.exec(self.mapToGlobal(where if isinstance(where, QPoint) else QPoint(0, 0)))


class UnrealRow(DccRow):
    """
    Unreal, where the thing you pick is a project rather than a version.

    Same row, with add and remove beside the dropdown. When no engine is installed at all the
    button offers to get one, which is the only case where Unreal behaves like the others.

    :signal add_requested: when + is pressed.
    :signal remove_requested: (project path) when - is pressed.
    """

    add_requested = Signal()
    remove_requested = Signal(str)

    def __init__(self, dcc_name, label, icon_name, parent=None):
        super().__init__(dcc_name, label, icon_name, parent)

        self.paths = {}
        self.engines = []
        self.installable = []

        # Four controls have to fit where the other rows have two, so the dropdown gives up
        # what the buttons need rather than every control being squeezed into illegibility.
        self.versions.setFixedWidth(style.VERSION_WIDTH - 60)

        self.add_button = QPushButton('+')
        self.add_button.setFixedWidth(26)
        self.add_button.setToolTip('Add an Unreal project')
        self.remove_button = QPushButton('-')
        self.remove_button.setFixedWidth(26)
        self.remove_button.setToolTip('Forget the selected Unreal project')

        # Engines are not versions in the dropdown - that holds projects - so an engine the
        # project can install needs somewhere of its own to be offered. Without this, a
        # studio that deploys 5.6 with a batch file has it sitting in the installer folder
        # with nothing in the launcher that mentions it.
        self.engine_button = QPushButton('')
        self.engine_button.setObjectName('dcc_action')
        self.engine_button.setFixedWidth(style.ACTION_WIDTH - 14)
        self.engine_button.hide()

        # In front of the action button, after the dropdown.
        layout = self.layout()
        layout.insertWidget(layout.count() - 1, self.add_button)
        layout.insertWidget(layout.count() - 1, self.remove_button)
        layout.insertWidget(layout.count() - 1, self.engine_button)

        self.add_button.clicked.connect(self.add_requested.emit)
        self.remove_button.clicked.connect(self._remove_pressed)
        self.engine_button.clicked.connect(self._engine_pressed)

    def set_projects(self, entries, engines=None):
        """
        :param list(dict) entries: From ``api.unreal_projects``.
        :param list(dict) engines: From ``api.dcc_targets`` for unreal.
        """

        self.engines = engines or []
        self.paths = {}
        self.keys = []
        self.installed = {}

        self.versions.blockSignals(True)
        self.versions.clear()
        for entry in entries:
            label = entry['name'] if entry.get('exists') else '{} (missing)'.format(
                entry['name'])
            self.paths[label] = entry['path']
            self.keys.append(label)
            self.installed[label] = bool(entry.get('exists'))
            self.versions.addItem(label)
        self.versions.blockSignals(False)

        any_engine = any(one.get('installed') for one in self.engines)
        self.versions.setEnabled(bool(entries))
        self.add_button.setEnabled(True)
        self.remove_button.setEnabled(bool(entries))

        # Newest first, which is the order available() answers in.
        self.installable = [one['key'] for one in self.engines if not one.get('installed')]
        if any_engine and self.installable:
            self.engine_button.setText('Get {}'.format(self.installable[0]))
            self.engine_button.setToolTip(
                'Install Unreal Engine {} - this project has an installer for it'
                .format(self.installable[0]))
            self.engine_button.show()
        else:
            self.engine_button.hide()

        if not any_engine:
            self.action.setText('Install')
            self.action.setEnabled(True)
            self.button.setEnabled(True)
            offered = len([one for one in self.engines if not one.get('installed')])
            self.set_detail('no engine installed'
                            + (' - {} can be installed'.format(offered) if offered else ''))
        elif not entries:
            self.action.setText('Launch')
            self.action.setEnabled(False)
            self.button.setEnabled(False)
            self.set_detail('add a project with +')
        else:
            self.action.setText('Launch')
            self.action.setEnabled(True)
            self.button.setEnabled(True)
            engines = ', '.join(one['key'] for one in self.engines if one.get('installed'))
            self.set_detail('engine {}'.format(engines))

    def current_key(self):
        """
        :return: The selected project's path, or ''.
        :rtype: str
        """

        return self.paths.get(self.versions.currentText().strip(), '')

    def current_is_installed(self):
        return bool(self.current_key())

    def _update_action(self):
        # Driven by set_projects instead: what Unreal can do depends on engines and projects
        # together, not on one dropdown entry.
        pass

    def _primary(self):
        if not any(one.get('installed') for one in self.engines):
            # No version named: the API picks the newest the project can install, which is
            # the only thing this row knows it wants.
            self.install_requested.emit(self.dcc_name, '')
            return
        key = self.current_key()
        if key:
            self.launch_requested.emit(self.dcc_name, key)

    def _changed(self):
        pass

    def _engine_pressed(self):
        if self.installable:
            self.install_requested.emit(self.dcc_name, self.installable[0])

    def _remove_pressed(self):
        path = self.current_key()
        if path:
            self.remove_requested.emit(path)


class ProjectBar(QWidget):
    """
    The project row, on the plate the art was drawn for.

    ``path_box.png`` is a dark plate with a highlight along the top: the old launcher put the
    project controls on it, and without it the row floats on the background with nothing
    holding it together.

    The plate is redrawn to the bar's own width every time the bar changes size. Drawn once
    at the window's starting width instead, the buttons walk off the right-hand end of it the
    moment the window is widened - the layout stretches, a fixed pixmap does not.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedHeight(style.BAR_HEIGHT)

        image = resources.image('path_box.png')
        self.art = QPixmap(image) if image else None
        self.plate = QLabel(self)
        self.plate.lower()
        self._draw_plate()

        layout = QHBoxLayout(self)
        # The plate's art has a bevel down each side; the controls keep clear of it.
        layout.setContentsMargins(18, 4, 24, 4)
        layout.setSpacing(8)

        label = QLabel('Project')
        label.setObjectName('project_name_QLabel')
        label.setMinimumWidth(64)
        layout.addWidget(label)

        self.projects = QComboBox()
        self.projects.setObjectName('project_comboBox')
        self.projects.setMinimumWidth(210)
        self.projects.setToolTip('Which project the DCCs are started for')
        layout.addWidget(self.projects)

        layout.addStretch(1)

        self.add_button = QPushButton('Add')
        self.add_button.setObjectName('add_project_pushButton')
        self.add_button.setFixedWidth(70)
        layout.addWidget(self.add_button)

        self.edit_button = QPushButton('Edit')
        self.edit_button.setObjectName('update_project_pushButton')
        self.edit_button.setFixedWidth(70)
        layout.addWidget(self.edit_button)

        self.remove_button = QPushButton('Remove')
        self.remove_button.setObjectName('remove_project_pushButton')
        self.remove_button.setFixedWidth(80)
        layout.addWidget(self.remove_button)

    def resizeEvent(self, event):
        """
        :param event: The resize event. The plate follows the bar, whatever it becomes.
        """

        super().resizeEvent(event)
        self._draw_plate()

    def _draw_plate(self):
        """Stretch the art across whatever width the bar has now."""

        width = max(self.width(), 1)
        height = max(self.height(), 1)
        self.plate.setGeometry(0, 0, width, height)
        if self.art and not self.art.isNull():
            self.plate.setPixmap(self.art.scaled(
                width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

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


def wordmark(maximum_width=260):
    """
    The MechanicalArt wordmark, for the bottom of the window.

    :param int maximum_width: How wide to draw it.
    :return: A label carrying it, or None when the art is missing.
    :rtype: QLabel or None
    """

    path = resources.image('mca_tech_full_border_orange.png')
    if not path:
        return None
    picture = QPixmap(path)
    label = QLabel()
    label.setPixmap(picture.scaledToWidth(maximum_width,
                                          Qt.TransformationMode.SmoothTransformation))
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return label
