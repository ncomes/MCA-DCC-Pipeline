"""
Both windows, built and driven, with no display and nobody clicking.

This is the suite the Maya plug-ins cannot have: under ``mayapy`` their framework's Qt and
Maya's own are two instances and the first widget aborts the process. The launcher is a
standalone Qt application, so it has no such problem - it runs offscreen under any Python
with PySide6, including ``mayapy``::

    mayapy tests/test_ui_window.py
    python tests/test_ui_window.py

Modal dialogs are replaced for the duration, because a message box waiting for a person is a
hang. What they *were asked to show* is recorded and checked, which is the part worth
testing anyway: that a failure is reported as a failure.
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

# Before Qt is imported by anything.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def body(suite):
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as error:
        suite.note('skipped', 'PySide6 is not available here: {}'.format(error))
        print('SKIPPED: PySide6 is not installed for this Python ({}).'.format(error))
        return

    application = QApplication.instance() or QApplication([])
    suite.check('Qt starts offscreen', application is not None)

    from mca.launcher import api
    from mca.launcher.core import dccs, dependencies, fileio, prefs
    from mca.launcher.core.dccs.base import Dcc, LaunchTarget
    from mca.launcher.ui import dialogs, launcher_window, setup_window

    # ---------------------------------------------------------------- #
    # No dialog may block, and every one is recorded
    # ---------------------------------------------------------------- #
    shown = {'ask': [], 'tell': [], 'complain': []}
    answers = {'ask': True}

    dialogs.ask = lambda title, text, parent=None, detail='': (
        shown['ask'].append((title, text)) or answers['ask'])
    dialogs.tell = lambda title, text, parent=None, detail='': shown['tell'].append((title, text))
    dialogs.complain = lambda title, text, parent=None, detail='': shown['complain'].append(
        (title, text))
    launcher_window.dialogs = dialogs
    setup_window.dialogs = dialogs

    class QuietProgress(object):
        """Stands in for the progress window, and remembers what it was told."""

        lines = []

        def __init__(self, *args, **kwargs):
            QuietProgress.lines = []

        def show(self):
            pass

        def say(self, line):
            QuietProgress.lines.append(line)

        def finish(self):
            pass

    dialogs.ProgressWindow = QuietProgress

    # ---------------------------------------------------------------- #
    # A framework to point at
    # ---------------------------------------------------------------- #
    framework = os.path.join(suite.temp, 'repo', 'packages')
    common = os.path.join(framework, 'mca-common', 'mca', 'common')
    os.makedirs(os.path.join(common, 'startup', 'dependencies'))
    os.makedirs(os.path.join(common, 'startup', 'dccs', 'maya', 'Scripts'))
    with open(os.path.join(common, 'startup', 'dependencies', 'requirements.txt'), 'w') as f:
        f.write('numpy\nPyYAML\n')
    project_root = os.path.join(suite.temp, 'project')
    os.makedirs(project_root)

    # ---------------------------------------------------------------- #
    # Setup window
    # ---------------------------------------------------------------- #
    window = setup_window.SetupWindow()
    suite.check('the setup window builds', window is not None)
    suite.check('and Save is off until it has something to save',
                not window.save_button.isEnabled())

    window.name_edit.setText('Wayward')
    window.root_row.set_text(project_root)
    window.framework_row.set_text(project_root)   # exists, but holds no mca-common
    suite.check('a framework path that is not one keeps Save off',
                not window.save_button.isEnabled(), window.verdict.text())
    suite.check('and says why, before anything is pressed',
                'mca-common' in window.verdict.text(),
                window.verdict.text().replace(chr(10), ' / '))
    window.framework_row.set_text(os.path.join(suite.temp, 'not-there-at-all'))
    suite.check('and a folder that does not exist says that instead',
                'no folder' in window.verdict.text(),
                window.verdict.text().replace(chr(10), ' / '))

    window.framework_row.set_text(framework)
    suite.check('a real one turns Save on', window.save_button.isEnabled(),
                window.verdict.text())

    window.art_row.set_text(os.path.join(suite.temp, 'art'))
    suite.check('typing the art root fills in the art folders',
                window.art_rows['MCA_CHARACTERS_PATH'].text().endswith('Characters'),
                window.art_rows['MCA_CHARACTERS_PATH'].text())

    window.install_now.setChecked(False)
    window.make_folders.setChecked(True)
    saved = []
    window.saved.connect(saved.append)
    window._save()
    suite.check('saving writes the project', os.path.isfile(prefs.project_prefs_file('Wayward')))
    suite.check('and tells whoever is listening', saved == ['Wayward'], str(saved))
    suite.check('and created the art folders it was asked to',
                os.path.isdir(os.path.join(suite.temp, 'art', 'Characters')))
    suite.check('and nothing was complained about', not shown['complain'], str(shown['complain']))
    window.close()

    # ---------------------------------------------------------------- #
    # Main window, with a pretend DCC
    # ---------------------------------------------------------------- #
    class PretendDcc(Dcc):
        name = 'pretend'
        label = 'Pretend'
        icon = 'default_icon.png'
        startup_folder = 'maya'
        # 2026 is supported and not on this machine, which is the case the row has to show
        # rather than hide: it appears in the dropdown, marked, and the button offers to get
        # it.
        known_versions = ('2024', '2025', '2026')
        installer_folder = 'Pretend'
        download_url = 'https://example.invalid/pretend'
        here = ('2024', '2025')
        launched = []

        def is_installed(self, version):
            return str(version) in PretendDcc.here

        def targets(self):
            return [LaunchTarget(self.name, version, 'Pretend {}'.format(version))
                    for version in reversed(PretendDcc.here)]

        def interpreter(self, version):
            return sys.executable if self.is_installed(version) else ''

        def executable(self, version):
            return sys.executable if self.is_installed(version) else ''

        def launch(self, key, environment):
            PretendDcc.launched.append(key)
            return 4242

    pretend = PretendDcc()
    real_dccs, real_by_name = dccs.DCCS, dccs.BY_NAME
    real_install = dependencies.install
    dccs.DCCS = (pretend,)
    dccs.BY_NAME = {'pretend': pretend}

    try:
        main = launcher_window.LauncherWindow()
        suite.check('the main window builds', main is not None)
        suite.check('and has a row for the DCC that is installed', 'pretend' in main.rows)
        suite.check('with the newest version selected',
                    main.rows['pretend'].current_key() == '2025',
                    main.rows['pretend'].current_key())
        suite.check('and the project in the project bar', main.project_bar.current_project() == 'Wayward',
                    main.project_bar.current_project())

        # -- pressing launch when the install fails -------------------- #
        def failing_install(dcc, version, framework_path, interpreter, progress=None):
            if progress:
                progress('pip said no')
            return {'ok': False, 'target': '', 'skipped': [], 'imported': [],
                    'missing': {'numpy': 'ModuleNotFoundError'}, 'stamp': {},
                    'message': 'numpy could not be imported afterwards.'}

        dependencies.install = failing_install
        main.rows['pretend'].button.click()
        suite.check('pressing a DCC whose dependencies will not install does not start it',
                    not PretendDcc.launched, str(PretendDcc.launched))
        suite.check('and complains, rather than leaving the artist guessing',
                    bool(shown['complain']), str(shown['complain']))
        suite.check('and the status line says it too',
                    'not ready' in main.status.text() or 'not started' in main.status.text(),
                    main.status.text())
        suite.check('and pip\'s own output went to the progress window',
                    'pip said no' in QuietProgress.lines, str(QuietProgress.lines))

        # -- pressing launch when it works ---------------------------- #
        def working_install(dcc, version, framework_path, interpreter, progress=None):
            target = dependencies.target_folder(dcc, version)
            if not os.path.isdir(target):
                os.makedirs(target)
            wanted, _ = dependencies.dcc_requirements(dependencies.parse_requirements(
                dependencies.read_text(dependencies.requirements_path(framework_path))))
            fileio.write_json({'stamp_version': dependencies.STAMP_VERSION, 'verified': True,
                               'fingerprint': dependencies.fingerprint(wanted),
                               'installed_at': 'now', 'interpreter': interpreter,
                               'skipped': []},
                              dependencies.stamp_path(target))
            return {'ok': True, 'target': target, 'skipped': [], 'missing': {},
                    'imported': ['numpy'], 'stamp': {}, 'message': 'installed.'}

        dependencies.install = working_install
        shown['complain'] = []
        main.rows['pretend'].button.click()
        suite.check('with the install working, pressing it starts the DCC',
                    PretendDcc.launched == ['2025'], str(PretendDcc.launched))
        suite.check('and nothing is complained about', not shown['complain'],
                    str(shown['complain']))

        # -- the version dropdown ------------------------------------- #
        row = main.rows['pretend']
        suite.check('the dropdown offers the version that is not installed too',
                    [key for key in row.keys] == ['2026', '2025', '2024'], str(row.keys))
        suite.check('and marks it, so nobody wonders why it will not start',
                    'not installed' in row.versions.itemText(0),
                    row.versions.itemText(0))
        suite.check('and the row says what is here',
                    '2025' in row.detail_label.text(), row.detail_label.text())

        row.versions.setCurrentIndex(2)
        suite.check('changing to another installed version remembers it',
                    prefs.Selections.load('Wayward').dccs.get('pretend') == '2024',
                    str(prefs.Selections.load('Wayward').dccs))

        # -- the button's job changes with what is selected ------------- #
        asked = []
        real_install_dcc = api.install_dcc
        api.install_dcc = lambda dcc, key=None, project=None: (
            asked.append((dcc, key)) or {'ok': True, 'result': {'url': 'x'},
                                         'message': 'opened the download page.'})
        try:
            row.versions.setCurrentIndex(0)
            suite.check('selecting a version that is not here turns Launch into Install',
                        row.action.text() == 'Install', row.action.text())
            before = list(PretendDcc.launched)
            row.action.click()
            suite.check('and pressing it installs rather than launching',
                        asked == [('pretend', '2026')] and PretendDcc.launched == before,
                        '{} / {}'.format(asked, PretendDcc.launched))
            suite.check('selecting one that is here turns it back into Launch',
                        (row.versions.setCurrentIndex(1) or row.action.text()) == 'Launch',
                        row.action.text())

            # A version nobody chose: the row asks for '' and the API picks.
            PretendDcc.here = ()
            main.refresh()
            asked[:] = []
            suite.check('with nothing installed the row still offers to install',
                        main.rows['pretend'].action.text() == 'Install',
                        main.rows['pretend'].action.text())
        finally:
            api.install_dcc = real_install_dcc
            PretendDcc.here = ('2024', '2025')
            main.refresh()

        # -- the menu ------------------------------------------------- #
        shown['tell'] = []
        main._check_dependencies()
        suite.check('Check Dependencies reports without doing anything',
                    bool(shown['tell']), str(shown['tell']))

        main._doctor()
        suite.check('Diagnose reports too', len(shown['tell']) == 2, str(shown['tell']))

        answers['ask'] = False
        calls = []
        dependencies.install = lambda *args, **kwargs: calls.append(args) or working_install(
            *args, **kwargs)
        main._reinstall_dependencies()
        suite.check('answering no to a reinstall does not reinstall', not calls, str(calls))
        answers['ask'] = True
        main._reinstall_dependencies()
        suite.check('and answering yes does', len(calls) == 1, str(len(calls)))

        # -- removing the project ------------------------------------- #
        answers['ask'] = True
        main._remove_project()
        suite.check('Remove Project removes it', not prefs.project_names(),
                    str(prefs.project_names()))
        suite.check('and the window redraws with nothing in it',
                    main.project_bar.current_project() == '', main.project_bar.current_project())

        main.close()
    finally:
        dccs.DCCS, dccs.BY_NAME = real_dccs, real_by_name
        dependencies.install = real_install

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('ui_window', body))
