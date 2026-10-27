"""
Setting a project up: the first window a new machine sees.

It asks for two paths that matter and a handful that do not much, checks them as they are
typed rather than when Save is pressed, and - because this is the moment a machine becomes
ready - offers to install the dependencies for every DCC it found straight away.

That offer is a convenience, not the guarantee. The guarantee is in ``api.launch``, which
checks every time. This just means the first Maya press is instant instead of a five minute
wait.
"""

# python imports
import logging
import os

# PySide6 imports
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout
from PySide6.QtWidgets import QLabel, QLineEdit, QMainWindow, QPushButton, QVBoxLayout, QWidget

# mca imports
from mca.launcher import api
from mca.launcher.core import prefs, projects, resources
from mca.launcher.ui import dialogs, style


logger = logging.getLogger('mca-launcher')

#: The art folders, with the label each one gets.
ART_ROWS = (
    ('MCA_CHARACTERS_PATH', 'Characters'),
    ('MCA_PROPS_PATH', 'Props'),
    ('MCA_WEAPONS_PATH', 'Weapons'),
    ('MCA_GEAR_PATH', 'Gear'),
    ('MCA_ENVIRONMENT_PATH', 'Environments'),
    ('MCA_VEHICLE_PATH', 'Vehicles'),
)


class PathRow(QWidget):
    """A line edit with a Browse button, and room for a verdict beneath it."""

    def __init__(self, placeholder='', parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(360)
        layout.addWidget(self.edit)

        self.browse = QPushButton('Browse')
        self.browse.setFixedWidth(70)
        layout.addWidget(self.browse)

        self.browse.clicked.connect(self._browse)

    def text(self):
        return self.edit.text().strip()

    def set_text(self, value):
        self.edit.setText(str(value or ''))

    def _browse(self):
        start = self.text() or os.path.expanduser('~')
        folder = QFileDialog.getExistingDirectory(self, 'Choose a folder', start)
        if folder:
            self.edit.setText(os.path.normpath(folder))


class SetupWindow(QMainWindow):
    """
    Project setup.

    :signal saved: (project name) once the preferences are written.
    """

    saved = Signal(str)

    def __init__(self, project_name=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle('MCA Project Setup')
        self.setObjectName('setup_window')
        self.setMinimumWidth(640)
        style.apply(self)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        intro = QLabel(
            'The launcher needs two things: where the project lives, and where the pipeline '
            'code lives. Everything below that is optional and can be filled in later.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        required = QGroupBox('The two that matter')
        form = QFormLayout(required)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('a short name, for example SampleGame')
        form.addRow('Project name', self.name_edit)
        self.root_row = PathRow('the project root folder')
        form.addRow('Project root', self.root_row)
        self.framework_row = PathRow('the packages folder, holding mca-common')
        form.addRow('Pipeline packages', self.framework_row)
        self.verdict = QLabel('')
        self.verdict.setWordWrap(True)
        form.addRow('', self.verdict)
        layout.addWidget(required)

        art = QGroupBox('Art folders (optional)')
        art_form = QFormLayout(art)
        self.art_row = PathRow('the art root; the folders below are filled in from it')
        art_form.addRow('Art root', self.art_row)
        self.art_rows = {}
        for key, label in ART_ROWS:
            row = PathRow()
            self.art_rows[key] = row
            art_form.addRow(label, row)
        self.tools_row = PathRow('a shared tools folder, if there is one')
        art_form.addRow('Common tools', self.tools_row)
        layout.addWidget(art)

        # Source control is declared here rather than detected inside each DCC. Detection
        # reads one machine-wide Perforce registry key, so a workspace set up for another
        # project announces itself on this one and every tool that asks source control a
        # question waits for a server that is not there.
        source = QGroupBox('Source control (optional)')
        source_form = QFormLayout(source)
        self.source_combo = QComboBox()
        for choice in prefs.SOURCE_CONTROL_CHOICES:
            self.source_combo.addItem(choice)
        self.source_combo.setToolTip(
            'Which source control this project uses. "none" means tools will not try to '
            'check files out at all - which is what you want when there is no server to '
            'reach.')
        source_form.addRow('Backend', self.source_combo)

        self.p4_rows = {}
        for key, label in prefs.P4_FIELDS:
            edit = QLineEdit()
            self.p4_rows[key] = edit
            source_form.addRow(label, edit)
        self.p4_rows['MCA_P4_WORKSPACE'].setToolTip(
            'Your own workspace for this project. It is per-user, which is why it lives in '
            'your mca_preferences and is never checked in.')

        self.detect_p4 = QPushButton('Detect from this machine')
        self.detect_p4.setToolTip(
            'Fill these in from the Perforce client installed here. Offered, not assumed.')
        self.detect_p4.clicked.connect(self._detect_perforce)
        source_form.addRow('', self.detect_p4)

        self.source_combo.currentTextChanged.connect(self._sync_source_fields)
        layout.addWidget(source)

        self.make_folders = QCheckBox('Create any art folders that do not exist yet')
        layout.addWidget(self.make_folders)

        self.install_now = QCheckBox(
            'Install the Python packages for every DCC found on this machine now')
        self.install_now.setChecked(True)
        self.install_now.setToolTip(
            'Takes a few minutes per DCC version. If this is left off, they are installed '
            'the first time that DCC is started instead - the launcher never starts one '
            'without them.')
        layout.addWidget(self.install_now)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton('Save')
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton('Cancel')
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # -- signals ---------------------------------------------------- #
        self.root_row.edit.textChanged.connect(self._check)
        self.framework_row.edit.textChanged.connect(self._check)
        self.art_row.edit.textChanged.connect(self._fill_art)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.close)

        if project_name:
            self._load(project_name)
        self._check()

    # ------------------------------------------------------------------ #
    # Filling in
    # ------------------------------------------------------------------ #
    def _load(self, project_name):
        """
        :param str project_name: An existing project to edit.
        """

        project = prefs.ProjectPrefs.load(project_name)
        self.name_edit.setText(project.project_name)
        self.name_edit.setReadOnly(True)        # renaming is a move, not an edit
        self.root_row.set_text(project.project_root)
        self.framework_row.set_text(project.framework_path)
        self.art_row.set_text(project.art_path)
        for key, row in self.art_rows.items():
            row.set_text(project.values.get(key, ''))
        self.tools_row.set_text(project.values.get('MCA_COMMON_TOOLS', ''))

        backend = str(project.values.get('MCA_SOURCE_CONTROL') or 'none').strip().lower()
        index = self.source_combo.findText(backend)
        self.source_combo.setCurrentIndex(index if index >= 0 else 0)
        for key, edit in self.p4_rows.items():
            edit.setText(str(project.values.get(key) or ''))
        self._sync_source_fields(self.source_combo.currentText())
        self.install_now.setChecked(False)
        self.setWindowTitle('MCA Project Setup - {}'.format(project.project_name))

    def _fill_art(self):
        """Fill the art folders from the art root, without overwriting anything typed."""

        defaults = projects.default_art_paths(self.art_row.text())
        for key, row in self.art_rows.items():
            if not row.text():
                row.set_text(defaults.get(key, ''))

    # ------------------------------------------------------------------ #
    # Checking as it is typed
    # ------------------------------------------------------------------ #
    def _check(self):
        """
        Say whether the two paths will do, now rather than on Save.

        :return: Whether both are good.
        :rtype: bool
        """

        messages = []
        root_ok, root_message = projects.check_project_root(self.root_row.text())
        if self.root_row.text():
            messages.append(('' if root_ok else 'Project root: ') + root_message)

        framework_ok, framework_message, _ = projects.check_framework_path(
            self.framework_row.text())
        if self.framework_row.text():
            messages.append(('' if framework_ok else 'Packages: ') + framework_message)

        good = root_ok and framework_ok and bool(self.name_edit.text().strip())
        self.verdict.setText('\n'.join(messages))
        self.verdict.setStyleSheet('color: rgb(150,220,150);' if good
                                   else 'color: rgb(235,180,120);')
        self.save_button.setEnabled(good)
        return good

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def _save(self):
        if not self._check():
            return

        art_paths = {key: row.text() for key, row in self.art_rows.items() if row.text()}

        # Carried in the same dict: save_project takes anything in prefs.PROJECT_KEYS, and
        # environment_values() exports anything in it that is not empty.
        backend = self.source_combo.currentText().strip() or 'none'
        art_paths['MCA_SOURCE_CONTROL'] = backend
        for key, edit in self.p4_rows.items():
            art_paths[key] = edit.text().strip() if backend == 'perforce' else ''
        if self.make_folders.isChecked():
            self._create_folders([self.art_row.text()] + list(art_paths.values()))

        response = api.save_project(self.name_edit.text().strip(),
                                    self.root_row.text(),
                                    self.framework_row.text(),
                                    art_path=self.art_row.text(),
                                    art_paths=art_paths,
                                    common_tools=self.tools_row.text())
        if not response['ok']:
            dialogs.complain('Project Setup', response['message'], self)
            return

        name = response['result']['name']
        self.status.setText(response['message'])

        if self.install_now.isChecked():
            self._install_everything(name)

        self.saved.emit(name)
        self.close()

    # ------------------------------------------------------------------ #
    # Source control
    # ------------------------------------------------------------------ #
    def _sync_source_fields(self, backend):
        """
        Enable the Perforce fields only while Perforce is the chosen backend.

        :param str backend: The name now selected.
        """

        wanted = str(backend).strip().lower() == 'perforce'
        for edit in self.p4_rows.values():
            edit.setEnabled(wanted)
        self.detect_p4.setEnabled(wanted)

    def _detect_perforce(self):
        """
        Fill the Perforce fields in from the client installed on this machine.

        Offered behind a button rather than done automatically, which is the whole point of
        this group: the machine's Perforce registry key holds one connection for every
        project on the machine, so reading it without being asked is how a workspace set up
        for one studio ends up in use on an unrelated project.
        """

        try:
            from mca.common.sourcecontrol import perforce as p4_backend
        except ImportError as error:
            dialogs.complain('Project Setup',
                             'Could not read the Perforce client from here: {}'.format(error),
                             self)
            return

        client = p4_backend.Perforce()
        if not client.executable:
            dialogs.complain('Project Setup',
                             'No p4 client is installed on this machine, so there is '
                             'nothing to read.', self)
            return

        found = {'MCA_P4_PORT': client.port,
                 'MCA_P4_USER': client.user,
                 'MCA_P4_WORKSPACE': client.workspace}
        for key, value in found.items():
            if value:
                self.p4_rows[key].setText(str(value))

        if not any(found.values()):
            self.status.setText('The Perforce client here has no connection set up.')
        else:
            self.status.setText(
                'Read from {}. Check the workspace is the one for this project.'
                .format(getattr(client, 'source', 'this machine')))

    def _create_folders(self, paths):
        """
        :param list(str) paths: Folders to create if they are not there.
        """

        for path in paths:
            if not path:
                continue
            try:
                if not os.path.isdir(path):
                    os.makedirs(path)
                    logger.info('Created %s', path)
            except Exception as error:
                # Worth saying, not worth stopping a save for.
                logger.warning('Could not create %s: %s', path, error)
                self.status.setText('Could not create {}: {}'.format(path, error))

    def _install_everything(self, project_name):
        """
        Install dependencies for every DCC version found, one after another.

        :param str project_name: The project just saved.
        """

        listing = api.dcc_targets(project=project_name)
        if not listing['ok']:
            dialogs.complain('Dependencies', listing['message'], self)
            return

        jobs = []
        for entry in listing['result']:
            if entry['dcc'] == 'unreal':
                # Unreal's packages belong to an engine, and an engine is only known once a
                # project has been added. Left until then.
                continue
            for target in entry['targets']:
                # Only what is actually on this machine. The listing includes versions that
                # can be installed, and a dependency install needs that version's own
                # interpreter - which a version nobody has installed does not have.
                if target.get('installed'):
                    jobs.append((entry['dcc'], target['key'], target['label']))

        if not jobs:
            self.status.setText('No installed DCC was found, so there is nothing to install '
                                'for yet.')
            return

        window = dialogs.ProgressWindow(
            'Installing Dependencies',
            'Installing the pipeline\'s Python packages for {} version(s). Each one is '
            'installed with that version\'s own interpreter, so this is a few minutes '
            'each.'.format(len(jobs)), parent=self)

        def install_everything(progress):
            """
            Every job, one after another, on the worker thread.

            :param callable progress: Where to report, line by line.
            :return: What failed, as sentences.
            :rtype: list(str)
            """

            failed_jobs = []
            for dcc, key, label in jobs:
                progress('')
                progress('=== {} ==='.format(label))
                response = api.ensure_dependencies(dcc, key, project=project_name,
                                                  progress=progress)
                progress(response['message'])
                if not response['ok']:
                    failed_jobs.append('{}: {}'.format(label, response['message']))
            return failed_jobs

        # The whole run goes on one worker thread, so the window keeps moving through all of
        # it rather than only when pip happens to print.
        failures = window.run(install_everything) or []

        if failures:
            dialogs.complain('Dependencies',
                             '{} of {} did not install. They will be tried again when that '
                             'DCC is started, and it will not start until they succeed.'
                             .format(len(failures), len(jobs)), self, '\n\n'.join(failures))
        else:
            self.status.setText('Dependencies installed for {} version(s).'.format(len(jobs)))
