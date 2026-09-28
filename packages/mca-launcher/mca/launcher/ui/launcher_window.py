"""
The main window: pick a project, press a DCC, get a DCC with working tools.

Every button is two or three lines - resolve what was pressed, call the API, show what came
back. That is the whole design: if a button here needed to work something out for itself,
the API would be missing a function and the command line would be less capable than the
window.
"""

# python imports
import logging
import os
import subprocess

# PySide6 imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMainWindow, QSizePolicy
from PySide6.QtWidgets import QSpacerItem, QVBoxLayout, QWidget

# mca imports
from mca.launcher import api
from mca.launcher.core import logs, platform_paths, resources
from mca.launcher.ui import dialogs, style, widgets


logger = logging.getLogger('mca-launcher')


class LauncherWindow(QMainWindow):
    """The launcher."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle('Mechanical Art DCC Launcher')
        icon = resources.icon('default_icon.png')
        if icon:
            self.setWindowIcon(QIcon(icon))
        self.setMinimumSize(style.WINDOW_WIDTH, style.WINDOW_HEIGHT)
        style.apply(self)

        self.tiles = {}
        self.setup_window = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.banner = widgets.Banner()
        layout.addWidget(self.banner)

        self.tile_row = QHBoxLayout()
        layout.addLayout(self.tile_row)

        layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum,
                                   QSizePolicy.Policy.Expanding))

        bottom = QHBoxLayout()
        self.status = QLabel('')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, stretch=1)
        logo = resources.icon('corner_logo.png')
        if logo:
            picture = QLabel()
            picture.setPixmap(QPixmap(logo))
            bottom.addWidget(picture, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(bottom)

        self._build_menu()
        self._build_tiles()

        self.banner.projects.currentIndexChanged.connect(self._project_changed)
        self.banner.add_button.clicked.connect(self._add_project)
        self.banner.edit_button.clicked.connect(self._edit_project)
        self.banner.remove_button.clicked.connect(self._remove_project)

        self.refresh()

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #
    def _build_menu(self):
        tools = self.menuBar().addMenu('&Tools')

        action = tools.addAction('Check Dependencies')
        action.setStatusTip('Report whether the selected DCC has what the framework needs')
        action.triggered.connect(self._check_dependencies)

        action = tools.addAction('Reinstall Dependencies')
        action.setStatusTip('Wipe and reinstall the selected DCC version\'s packages')
        action.triggered.connect(self._reinstall_dependencies)

        tools.addSeparator()

        action = tools.addAction('Diagnose (Doctor)')
        action.setStatusTip('Everything worth knowing when something will not start')
        action.triggered.connect(self._doctor)

        action = tools.addAction('Open Log Folder')
        action.triggered.connect(self._open_logs)

        action = tools.addAction('Open Dependencies Folder')
        action.triggered.connect(self._open_dependencies)

    def _build_tiles(self):
        listing = api.dcc_targets()
        if not listing['ok']:
            self._say(listing['message'], ok=False)
            return

        for entry in listing['result']:
            if entry['dcc'] == 'unreal':
                tile = widgets.UnrealTile(entry['dcc'], entry['label'], entry['icon'])
                tile.add_requested.connect(self._add_unreal_project)
                tile.remove_requested.connect(self._remove_unreal_project)
            else:
                tile = widgets.DccTile(entry['dcc'], entry['label'], entry['icon'])
            tile.launch_requested.connect(self._launch)
            tile.choice_changed.connect(self._remember_choice)
            self.tiles[entry['dcc']] = tile
            self.tile_row.addWidget(tile)

        self.tile_row.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Minimum))

    # ------------------------------------------------------------------ #
    # Showing what is there
    # ------------------------------------------------------------------ #
    def refresh(self):
        """Read everything from the API and show it."""

        listing = api.list_projects()
        if not listing['ok']:
            self._say(listing['message'], ok=False)
            return

        names = [one['name'] for one in listing['result']['projects']]
        self.banner.set_projects(names, listing['result']['current'])
        self._refresh_tiles()

        if not names:
            self._say('No projects yet. Press Add Project to set one up.')
        else:
            self._say(listing['message'])

    def _refresh_tiles(self):
        project = self.banner.current_project() or None
        listing = api.dcc_targets(project=project)
        if not listing['ok']:
            self._say(listing['message'], ok=False)
            return

        for entry in listing['result']:
            tile = self.tiles.get(entry['dcc'])
            if not tile:
                continue
            if entry['dcc'] == 'unreal':
                projects = api.unreal_projects(project=project)
                tile.set_projects(projects['result'] if projects['ok'] else [])
            else:
                tile.set_targets([target['key'] for target in entry['targets']],
                                 entry['chosen'])

    # ------------------------------------------------------------------ #
    # Buttons
    # ------------------------------------------------------------------ #
    def _launch(self, dcc, key):
        if not key:
            self._say('Nothing is selected for {}.'.format(dcc), ok=False)
            return

        project = self.banner.current_project() or None

        # The dependency check happens inside api.launch, so it cannot be skipped. The
        # window's only job is to give it somewhere to report progress, because a first run
        # installs packages and that takes minutes.
        state = api.dependency_status(dcc, key, project=project)
        if state['ok'] and state['result'].get('satisfied'):
            response = api.launch(dcc, key, project=project, progress=self._say)
        else:
            window = dialogs.ProgressWindow(
                'Installing Dependencies',
                'Setting {} {} up for the first time. This installs the Python packages the '
                'pipeline needs, with {}\'s own interpreter, and only happens once per '
                'version.'.format(dcc, key, dcc), parent=self)
            window.show()
            try:
                response = api.launch(dcc, key, project=project, progress=window.say)
            finally:
                window.finish()

        if not response['ok']:
            dialogs.complain('{} was not started'.format(dcc), response['message'], self)
            self._say(response['message'], ok=False)
            return
        self._say(response['message'])

    def _remember_choice(self, dcc, key):
        project = self.banner.current_project() or None
        response = api.choose(dcc, key, project=project)
        if not response['ok']:
            logger.warning(response['message'])

    def _project_changed(self):
        name = self.banner.current_project()
        if not name:
            return
        response = api.set_current_project(name)
        if not response['ok']:
            self._say(response['message'], ok=False)
            return
        self._refresh_tiles()
        self._say('Project is {}.'.format(name))

    def _add_project(self):
        self._open_setup(None)

    def _edit_project(self):
        name = self.banner.current_project()
        if not name:
            self._say('There is no project to edit.', ok=False)
            return
        self._open_setup(name)

    def _open_setup(self, name):
        from mca.launcher.ui import setup_window

        window = setup_window.SetupWindow(project_name=name, parent=self)
        window.saved.connect(self._setup_saved)
        window.show()
        # Held on the instance because a window with no reference is collected and vanishes.
        self.setup_window = window

    def _setup_saved(self, name):
        self.refresh()
        self._say('Saved {}.'.format(name))

    def _remove_project(self):
        name = self.banner.current_project()
        if not name:
            return
        if not dialogs.ask('Remove Project?',
                           'Forget the project "{}"?\n\nOnly the launcher\'s preferences for '
                           'it are deleted. No art and no code is touched.'.format(name),
                           self):
            return
        response = api.remove_project(name)
        dialogs.show_response(response, self, title='Remove Project')
        self.refresh()

    # ------------------------------------------------------------------ #
    # Unreal
    # ------------------------------------------------------------------ #
    def _add_unreal_project(self):
        project = self.banner.current_project() or None
        start_in = ''
        listing = api.unreal_projects(project=project)
        if listing['ok'] and listing['result']:
            start_in = os.path.dirname(listing['result'][-1]['path'])

        path, _ = QFileDialog.getOpenFileName(self, 'Select an Unreal project', start_in,
                                              'Unreal Projects (*.uproject)')
        if not path:
            return
        response = api.add_unreal_project(path, project=project)
        if not response['ok']:
            dialogs.complain('Add Unreal Project', response['message'], self)
            return
        self._refresh_tiles()
        self._say(response['message'])

    def _remove_unreal_project(self, path):
        project = self.banner.current_project() or None
        if not dialogs.ask('Remove Unreal Project?',
                           'Forget this project?\n\n{}\n\nThe project itself is not '
                           'touched.'.format(path), self):
            return
        response = api.remove_unreal_project(path, project=project)
        self._refresh_tiles()
        self._say(response['message'])

    # ------------------------------------------------------------------ #
    # Tools menu
    # ------------------------------------------------------------------ #
    def _selected(self):
        """
        Whichever tile has something selected, in the order the tiles were built.

        Built from ``self.tiles`` rather than a written-out list of DCC names: the old
        version named maya, mobu and unreal, so the Tools menu did nothing at all for any
        DCC added later - silently, because "nothing is selected" is a plausible-looking
        message. Caught by the window suite the first time it ran.

        :return: (dcc, key), or ('', '').
        :rtype: tuple(str, str)
        """

        for name, tile in self.tiles.items():
            if tile.current_key():
                return name, tile.current_key()
        return '', ''

    def _check_dependencies(self):
        dcc, key = self._selected()
        if not dcc:
            self._say('Nothing is selected to check.', ok=False)
            return
        response = api.dependency_status(dcc, key, project=self.banner.current_project() or None)
        detail = ''
        if response['ok']:
            result = response['result']
            detail = 'Folder: {}\nRequirements: {}\nFingerprint: {}'.format(
                result.get('target'), result.get('requirements'), result.get('fingerprint'))
        dialogs.tell('Dependencies', response['message'], self, detail)

    def _reinstall_dependencies(self):
        dcc, key = self._selected()
        if not dcc:
            self._say('Nothing is selected to reinstall.', ok=False)
            return
        if not dialogs.ask('Reinstall Dependencies?',
                           'Wipe and reinstall the Python packages for {} {}?\n\nThis takes '
                           'a few minutes.'.format(dcc, key), self):
            return

        window = dialogs.ProgressWindow('Installing Dependencies',
                                        'Reinstalling packages for {} {}.'.format(dcc, key),
                                        parent=self)
        window.show()
        try:
            response = api.ensure_dependencies(dcc, key,
                                              project=self.banner.current_project() or None,
                                              force=True, progress=window.say)
        finally:
            window.finish()
        dialogs.show_response(response, self, title='Dependencies')
        self._say(response['message'], ok=response['ok'])

    def _doctor(self):
        response = api.doctor(project=self.banner.current_project() or None)
        if not response['ok']:
            dialogs.complain('Diagnose', response['message'], self)
            return

        report = response['result']
        lines = ['Launcher {}'.format(report['launcher_version']),
                 'Preferences: {}'.format(report['preferences_folder']),
                 'Dependencies: {}'.format(report['dependencies_root']),
                 'Project: {}'.format(report['project'] or 'none'),
                 'Framework: {}'.format(report['framework_path'] or 'not set'),
                 'Requirements: {}'.format(report['requirements'] or 'not found'), '']
        for entry in report['dccs']:
            lines.append('{} {}: dependencies {}'.format(entry['label'], entry['key'],
                                                         entry['dependencies']))
            if entry.get('reason'):
                lines.append('    {}'.format(entry['reason']))
        if report['problems']:
            lines.append('')
            lines.append('Problems:')
            lines.extend('  - {}'.format(problem) for problem in report['problems'])

        dialogs.tell('Diagnose', response['message'], self, '\n'.join(lines))

    def _open_logs(self):
        self._open_folder(platform_paths.logs_folder())

    def _open_dependencies(self):
        self._open_folder(platform_paths.dependencies_root())

    def _open_folder(self, folder):
        if not os.path.isdir(folder):
            self._say('{} does not exist yet.'.format(folder), ok=False)
            return
        try:
            if platform_paths.IS_WINDOWS:
                os.startfile(folder)                                  # noqa: S606
            else:
                subprocess.Popen(['xdg-open', folder])
        except Exception as error:
            self._say('Could not open {}: {}'.format(folder, error), ok=False)

    # ------------------------------------------------------------------ #
    # Status line
    # ------------------------------------------------------------------ #
    def _say(self, message, ok=True):
        """
        :param str message: What to show along the bottom.
        :param bool ok: False colours it as a problem.
        """

        self.status.setText(str(message))
        self.status.setStyleSheet('color: white;' if ok else 'color: rgb(235,120,90);')
        logger.log(logging.INFO if ok else logging.WARNING, message)

    # ------------------------------------------------------------------ #
    # Closing
    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        """
        Remember the project on the way out.

        The selections themselves are saved when they change, not here: the old launcher
        saved on close only, so a crash lost whatever had been picked - and it did it from an
        event filter that swallowed every other event on the way past.

        :param event: The close event.
        """

        name = self.banner.current_project()
        if name:
            api.set_current_project(name)
        super().closeEvent(event)
