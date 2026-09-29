"""
The main window: pick a project, pick a version, get a DCC with working tools.

Every button is two or three lines - resolve what was pressed, call the API, show what came
back. That is the whole design: if a button here needed to work something out for itself,
the API would be missing a function and the command line would be less capable than the
window.

The layout is **one row per application**, on the bordered plate the art was drawn for. The
first arrangement used tiles - icon over dropdown over label, three across - and it read
badly: the labels collided with the icons, versions could not be compared down a column, and
two thirds of the window was empty. A row reads left to right in the order the questions get
asked: which application, where it is, which version, go.
"""

# python imports
import logging
import os
import subprocess

# PySide6 imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow
from PySide6.QtWidgets import QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget

# mca imports
from mca.launcher import api
from mca.launcher.core import platform_paths, resources
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

        self.rows = {}
        self.setup_window = None
        self.has_projects = False

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)

        # The bordered plate everything sits on. Without it the rows float on the window's
        # background with nothing holding them together, which is what the old launcher's
        # main_frame was for.
        self.frame = QFrame()
        self.frame.setObjectName('main_frame')
        outer.addWidget(self.frame)

        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(6)

        self.project_bar = widgets.ProjectBar()
        layout.addWidget(self.project_bar)

        self.row_layout = QVBoxLayout()
        self.row_layout.setSpacing(6)
        layout.addLayout(self.row_layout)

        layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum,
                                   QSizePolicy.Policy.Expanding))

        # -- the bottom line: what just happened, Refresh, and the mark ------ #
        bottom = QHBoxLayout()
        self.status = QLabel('')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, stretch=1)

        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.setObjectName('refresh_pushButton')
        self.refresh_button.setFixedWidth(86)
        self.refresh_button.setToolTip('Read the machine again - after installing a version, '
                                      'or adding one to the project')
        bottom.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignBottom)

        mark = widgets.wordmark(200)
        if mark:
            bottom.addWidget(mark, alignment=Qt.AlignmentFlag.AlignRight |
                             Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(bottom)

        self._build_menu()
        self._build_rows()

        self.project_bar.projects.currentIndexChanged.connect(self._project_changed)
        self.project_bar.add_button.clicked.connect(self._add_project)
        self.project_bar.edit_button.clicked.connect(self._edit_project)
        self.project_bar.remove_button.clicked.connect(self._remove_project)
        self.refresh_button.clicked.connect(self.refresh)

        self.refresh()

        # A machine with nothing set up has nothing to launch, and the one thing it needs is
        # the project. Opened here rather than on every refresh, so removing the last project
        # does not shove a window in front of somebody who was tidying up. The old launcher
        # did this from a separate start-up script that decided by asking whether any prefs
        # file existed at all, which is how a half-configured project got past it.
        if not self.has_projects:
            self._say('Nothing is set up on this machine yet. Start with the project.')
            self._open_setup(None)

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #
    def _build_menu(self):
        tools = self.menuBar().addMenu('&Tools')

        action = tools.addAction('Refresh')
        action.setStatusTip('Read the machine again')
        action.triggered.connect(self.refresh)

        tools.addSeparator()

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

    def _build_rows(self):
        listing = api.dcc_targets()
        if not listing['ok']:
            self._say(listing['message'], ok=False)
            return

        for entry in listing['result']:
            if entry['dcc'] == 'unreal':
                row = widgets.UnrealRow(entry['dcc'], entry['label'], entry['icon'])
                row.add_requested.connect(self._add_unreal_project)
                row.remove_requested.connect(self._remove_unreal_project)
            else:
                row = widgets.DccRow(entry['dcc'], entry['label'], entry['icon'])
            row.launch_requested.connect(self._launch)
            row.install_requested.connect(self._install)
            row.choice_changed.connect(self._remember_choice)
            self.rows[entry['dcc']] = row
            self.row_layout.addWidget(row)

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
        self.has_projects = bool(names)
        self.project_bar.set_projects(names, listing['result']['current'])
        self._refresh_rows()

        if not names:
            self._say('No projects yet. Press Add to set one up.')
        else:
            self._say(listing['message'])

    def _refresh_rows(self):
        project = self.project_bar.current_project() or None
        listing = api.dcc_targets(project=project)
        if not listing['ok']:
            self._say(listing['message'], ok=False)
            return

        for entry in listing['result']:
            row = self.rows.get(entry['dcc'])
            if not row:
                continue
            if entry['dcc'] == 'unreal':
                projects = api.unreal_projects(project=project)
                row.set_projects(projects['result'] if projects['ok'] else [],
                                 entry['targets'])
            else:
                row.set_targets(entry['targets'], entry['chosen'])
                row.set_detail(self._detail_for(entry))

    @staticmethod
    def _detail_for(entry):
        """
        The small line under an application's name.

        :param dict entry: One entry from ``api.dcc_targets``.
        :return: What to show.
        :rtype: str
        """

        installed = [target['key'] for target in entry['targets'] if target['installed']]
        if installed:
            return 'installed: {}'.format(', '.join(installed))
        offered = len(entry['targets'])
        if offered:
            return 'none installed - {} version(s) can be installed'.format(offered)
        return 'not found on this machine'

    # ------------------------------------------------------------------ #
    # Buttons
    # ------------------------------------------------------------------ #
    def _launch(self, dcc, key):
        if not key:
            self._say('Nothing is selected for {}.'.format(dcc), ok=False)
            return

        project = self.project_bar.current_project() or None

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
            # On a worker thread: pip goes quiet for a minute at a time, and a window that
            # only redraws when output arrives is indistinguishable from a hung one.
            response = window.run(
                lambda progress: api.launch(dcc, key, project=project, progress=progress))

        if not response['ok']:
            dialogs.complain('{} was not started'.format(dcc), response['message'], self)
            self._say(response['message'], ok=False)
            return
        self._say(response['message'])

    def _install(self, dcc, key):
        """
        Get a version the machine does not have.

        The API decides where it comes from - the project's installer folder if it has one
        for that version, whatever kind of file the studio put there, and otherwise the
        vendor's download page.

        :param str dcc: The DCC name.
        :param str key: The version wanted. '' means "the newest that can be installed".
        """

        project = self.project_bar.current_project() or None
        response = api.install_dcc(dcc, key, project=project)
        if not response['ok']:
            dialogs.complain('Install', response['message'], self)
            self._say(response['message'], ok=False)
            return

        dialogs.tell('Install', response['message'], self,
                     response['result'].get('installer', '') or
                     response['result'].get('url', ''))
        self._say(response['message'])

    def _remember_choice(self, dcc, key):
        project = self.project_bar.current_project() or None
        response = api.choose(dcc, key, project=project)
        if not response['ok']:
            logger.warning(response['message'])

    def _project_changed(self):
        name = self.project_bar.current_project()
        if not name:
            return
        response = api.set_current_project(name)
        if not response['ok']:
            self._say(response['message'], ok=False)
            return
        self._refresh_rows()
        self._say('Project is {}.'.format(name))

    def _add_project(self):
        self._open_setup(None)

    def _edit_project(self):
        name = self.project_bar.current_project()
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
        name = self.project_bar.current_project()
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
        project = self.project_bar.current_project() or None
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
        self._refresh_rows()
        self._say(response['message'])

    def _remove_unreal_project(self, path):
        project = self.project_bar.current_project() or None
        if not dialogs.ask('Remove Unreal Project?',
                           'Forget this project?\n\n{}\n\nThe project itself is not '
                           'touched.'.format(path), self):
            return
        response = api.remove_unreal_project(path, project=project)
        self._refresh_rows()
        self._say(response['message'])

    # ------------------------------------------------------------------ #
    # Tools menu
    # ------------------------------------------------------------------ #
    def _selected(self):
        """
        Whichever row has an installed version selected, in the order they were built.

        Built from ``self.rows`` rather than a written-out list of DCC names: the old version
        named maya, mobu and unreal, so the Tools menu did nothing at all for any DCC added
        later - silently, because "nothing is selected" is a plausible-looking message.
        Caught by the window suite the first time it ran.

        :return: (dcc, key), or ('', '').
        :rtype: tuple(str, str)
        """

        for name, row in self.rows.items():
            if row.current_key() and row.current_is_installed():
                return name, row.current_key()
        return '', ''

    def _check_dependencies(self):
        dcc, key = self._selected()
        if not dcc:
            self._say('Nothing installed is selected to check.', ok=False)
            return
        response = api.dependency_status(dcc, key,
                                        project=self.project_bar.current_project() or None)
        detail = ''
        if response['ok']:
            result = response['result']
            detail = 'Folder: {}\nRequirements: {}\nFingerprint: {}'.format(
                result.get('target'), result.get('requirements'), result.get('fingerprint'))
        dialogs.tell('Dependencies', response['message'], self, detail)

    def _reinstall_dependencies(self):
        dcc, key = self._selected()
        if not dcc:
            self._say('Nothing installed is selected to reinstall.', ok=False)
            return
        if not dialogs.ask('Reinstall Dependencies?',
                           'Wipe and reinstall the Python packages for {} {}?\n\nThis takes '
                           'a few minutes.'.format(dcc, key), self):
            return

        window = dialogs.ProgressWindow('Installing Dependencies',
                                        'Reinstalling packages for {} {}.'.format(dcc, key),
                                        parent=self)
        project = self.project_bar.current_project() or None
        response = window.run(
            lambda progress: api.ensure_dependencies(dcc, key, project=project, force=True,
                                                     progress=progress))
        dialogs.show_response(response, self, title='Dependencies')
        self._say(response['message'], ok=response['ok'])

    def _doctor(self):
        response = api.doctor(project=self.project_bar.current_project() or None)
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

        name = self.project_bar.current_project()
        if name:
            api.set_current_project(name)
        super().closeEvent(event)
