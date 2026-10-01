"""
The launcher's core, checked without a DCC, without Qt and without a display.

Run it with any Python 3.9 or newer::

    python tests/test_core.py

Every check here is something that was wrong in the launcher this replaces, or something
that would be silently wrong if it broke: a path built from the wrong folder, an environment
variable set to None, a preference file that loses the artist's projects, a dependency check
that passes when the folder is a shell.
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.launcher.core import contract, dependencies, environment, fileio  # noqa: E402
from mca.launcher.core import platform_paths, prefs, projects  # noqa: E402
from mca.launcher.core import shortcuts  # noqa: E402
from mca.launcher.core.dccs import base as dcc_base  # noqa: E402


def body(suite):
    # ---------------------------------------------------------------- #
    # The contract
    # ---------------------------------------------------------------- #
    answer = contract.response(True, {'a': 1}, 'fine')
    suite.check('a response has exactly the three keys',
                set(answer) == {'ok', 'result', 'message'}, str(sorted(answer)))

    @contract.safe
    def pair():
        return 41 + 1, 'counted'

    @contract.safe
    def angry():
        raise ValueError('the cage is inside out')

    @contract.safe
    def silent():
        raise RuntimeError()

    suite.check('a (result, message) pair becomes an ok response',
                pair() == {'ok': True, 'result': 42, 'message': 'counted'}, str(pair()))
    suite.check('a raise becomes a failed response carrying its sentence',
                angry() == {'ok': False, 'result': None,
                            'message': 'the cage is inside out'}, str(angry()))
    suite.check('an exception with no message still says which kind it was',
                'RuntimeError' in silent()['message'], silent()['message'])

    @contract.safe
    def passes_through():
        return contract.failed('already a response')

    suite.check('a ready-made response is passed through untouched',
                passes_through()['message'] == 'already a response')

    # ---------------------------------------------------------------- #
    # Files
    # ---------------------------------------------------------------- #
    missing = os.path.join(suite.temp, 'not', 'there.yaml')
    suite.check('reading a file that is not there answers the default, rather than raising',
                fileio.read_yaml(missing, default={'empty': True}) == {'empty': True})

    written = fileio.write_yaml({'b': 2, 'a': 1}, os.path.join(suite.temp, 'round.yaml'))
    suite.check('a write creates the folder it needs', bool(written) and os.path.isfile(written))
    suite.check('and reads back the same data',
                fileio.read_yaml(written) == {'a': 1, 'b': 2}, str(fileio.read_yaml(written)))
    suite.check('and leaves no temporary files behind',
                not [name for name in os.listdir(os.path.dirname(written))
                     if name.endswith('.tmp')],
                str(os.listdir(os.path.dirname(written))))

    stamp = fileio.write_json({'n': 1}, os.path.join(suite.temp, 'stamp.json'))
    suite.check('json round trips too', fileio.read_json(stamp) == {'n': 1})

    # ---------------------------------------------------------------- #
    # Where things live
    # ---------------------------------------------------------------- #
    suite.check('the preferences folder honours MCA_PREFS_ROOT, so a test cannot touch the '
                'real one',
                platform_paths.preferences_folder() == os.path.normpath(
                    os.environ['MCA_PREFS_ROOT']),
                platform_paths.preferences_folder())
    suite.check('the dependencies root honours MCA_DEPS_ROOT',
                platform_paths.dependencies_root() == os.path.normpath(
                    os.environ['MCA_DEPS_ROOT']))
    suite.check('a registry read on any platform answers None rather than raising',
                platform_paths.registry_value(r'SOFTWARE\Nothing\Here', 'Nope') is None)
    suite.check('and listing a registry key that is not there answers an empty list',
                platform_paths.registry_sub_keys(r'SOFTWARE\Nothing\Here') == [])

    # ---------------------------------------------------------------- #
    # A fake framework to point things at
    # ---------------------------------------------------------------- #
    framework = os.path.join(suite.temp, 'repo', 'packages')
    common = os.path.join(framework, 'mca-common', 'mca', 'common')
    os.makedirs(os.path.join(common, 'startup', 'dependencies'))
    os.makedirs(os.path.join(common, 'startup', 'dccs', 'maya', 'Scripts'))
    requirements = os.path.join(common, 'startup', 'dependencies', 'requirements.txt')
    with open(requirements, 'w', encoding='utf-8') as opened:
        opened.write('# the list\nnumpy\nPyYAML == 6.0\nPySide6\nshiboken6\n'
                     'anytree >= 2.8.0\nbeautifulsoup4 >= 4.12.0\n-r other.txt\n\n')
    project_root = os.path.join(suite.temp, 'project')
    os.makedirs(project_root)

    # ---------------------------------------------------------------- #
    # Project validation
    # ---------------------------------------------------------------- #
    ok, message = projects.check_project_root(project_root)
    suite.check('a folder that exists is a usable project root', ok, message)
    ok, message = projects.check_project_root(os.path.join(suite.temp, 'nope'))
    suite.check('and one that does not is refused, by name', not ok, message)

    ok, message, resolved = projects.check_framework_path(framework)
    suite.check('the framework is recognised by holding mca-common, not by a marker file',
                ok and resolved == os.path.normpath(framework), message)
    ok, message, resolved = projects.check_framework_path(os.path.dirname(framework))
    suite.check('and pointing one folder above it still resolves to packages',
                ok and resolved == os.path.normpath(framework), message)
    ok, message, resolved = projects.check_framework_path(project_root)
    suite.check('a folder with no mca-common in it is refused and says what was missing',
                not ok and 'mca-common' in message, message)

    # ---------------------------------------------------------------- #
    # Preferences
    # ---------------------------------------------------------------- #
    saved = projects.save_project('SampleGame', project_root, framework,
                                  art_paths=projects.default_art_paths(
                                      os.path.join(suite.temp, 'art')))
    suite.check('a project saves', os.path.isfile(prefs.project_prefs_file('SampleGame')))
    suite.check('and is listed', [one['name'] for one in projects.list_projects()] == ['SampleGame'])
    suite.check('and is complete', not saved.missing(), str(saved.missing()))

    reloaded = prefs.ProjectPrefs.load('SampleGame')
    suite.check('reloading gives back the same framework path',
                reloaded.framework_path == os.path.normpath(framework),
                reloaded.framework_path)
    suite.check('the environment values it hands over hold nothing empty',
                all(str(value).strip() for value in reloaded.environment_values().values()),
                str(reloaded.environment_values()))

    suite.raises('a project name with a separator in it is refused',
                 projects.save_project, 'bad/name', project_root, framework)
    suite.raises('and a framework path that is not one is refused',
                 projects.save_project, 'Other', project_root, project_root)

    # -- the old index-based file --------------------------------------- #
    old = {'maya_version': 2, 'mobu_version': 1, 'unreal_version': 0,
           'unreal_paths': [os.path.join(suite.temp, 'game.uproject')],
           'unreal_saved_path': suite.temp}
    fileio.write_yaml(old, prefs.launcher_prefs_file('SampleGame', create=True))
    selections = prefs.Selections.load('SampleGame')
    suite.check('an old preferences file keeps its Unreal projects',
                selections.unreal_projects == [os.path.join(suite.temp, 'game.uproject')],
                str(selections.unreal_projects))
    suite.check('and drops the dropdown positions, which cannot be trusted',
                selections.dccs == {}, str(selections.dccs))
    suite.check('so the newest installed version is offered instead',
                selections.chosen('maya', ['2026', '2025', '2024']) == '2026')

    selections.choose('maya', '2025')
    selections.save('SampleGame')
    suite.check('a choice is remembered by name',
                prefs.Selections.load('SampleGame').dccs == {'maya': '2025'},
                str(prefs.Selections.load('SampleGame').dccs))
    suite.check('and a remembered version that is no longer installed falls back to the '
                'newest that is',
                prefs.Selections.load('SampleGame').chosen('maya', ['2026', '2024']) == '2026')

    # -- removing ------------------------------------------------------- #
    suite.raises('removing a project that does not exist is refused',
                 projects.remove_project, 'NoSuchProject')
    suite.raises('and so is removing one with no name, which used to delete the whole '
                 'preferences folder',
                 projects.remove_project, '')

    # ---------------------------------------------------------------- #
    # The dependency list
    # ---------------------------------------------------------------- #
    lines = dependencies.parse_requirements(
        dependencies.read_text(dependencies.requirements_path(framework)))
    suite.check('the requirements file is found under mca-common',
                dependencies.requirements_path(framework) == os.path.normpath(requirements))
    suite.check('comments, blanks and -r includes are dropped',
                lines == ['numpy', 'PyYAML == 6.0', 'PySide6', 'shiboken6',
                          'anytree >= 2.8.0', 'beautifulsoup4 >= 4.12.0'], str(lines))

    kept, dropped = dependencies.dcc_requirements(lines)
    suite.check('Qt is never installed into a DCC folder - every DCC ships its own',
                [dependencies.requirement_name(one) for one in dropped] ==
                ['pyside6', 'shiboken6'], str(dropped))
    suite.check('and everything else is kept', len(kept) == 4, str(kept))

    suite.check('a requirement name is read without its version',
                dependencies.requirement_name('anytree >= 2.8.0') == 'anytree')
    suite.check('and the name you import is not always the name you install',
                dependencies.import_name('PyYAML == 6.0') == 'yaml'
                and dependencies.import_name('beautifulsoup4 >= 4.12.0') == 'bs4')

    first = dependencies.fingerprint(kept)
    suite.check('reordering and reformatting the list does not change its fingerprint',
                dependencies.fingerprint(list(reversed(['  ' + one for one in kept]))) == first)
    suite.check('but adding a package does',
                dependencies.fingerprint(kept + ['psutil']) != first)

    # ---------------------------------------------------------------- #
    # Dependency folders
    # ---------------------------------------------------------------- #
    target = dependencies.target_folder('maya', '2025')
    suite.check('each DCC version gets its own folder, outside the repository',
                target == os.path.join(platform_paths.dependencies_root(), 'maya-2025'),
                target)
    suite.check('and two versions never share one',
                dependencies.target_folder('maya', '2024') != target)

    state = dependencies.status('maya', '2025', framework)
    suite.check('with nothing installed, the status says so in a sentence',
                not state['satisfied'] and 'yet' in state['reason'], state['reason'])

    os.makedirs(target)
    state = dependencies.status('maya', '2025', framework)
    suite.check('an empty folder with no stamp does not count as installed',
                not state['satisfied'] and 'no stamp' in state['reason'], state['reason'])

    fileio.write_json({'stamp_version': dependencies.STAMP_VERSION, 'verified': True,
                       'fingerprint': dependencies.fingerprint(kept),
                       'installed_at': 'today', 'interpreter': 'mayapy'},
                      dependencies.stamp_path(target))
    state = dependencies.status('maya', '2025', framework)
    suite.check('a stamp that matches the list counts as installed', state['satisfied'],
                state['reason'])

    fileio.write_json({'stamp_version': dependencies.STAMP_VERSION, 'verified': True,
                       'fingerprint': 'something else'}, dependencies.stamp_path(target))
    state = dependencies.status('maya', '2025', framework)
    suite.check('changing the requirements list makes it out of date again',
                not state['satisfied'] and 'changed' in state['reason'], state['reason'])

    fileio.write_json({'stamp_version': dependencies.STAMP_VERSION, 'verified': False,
                       'fingerprint': dependencies.fingerprint(kept)},
                      dependencies.stamp_path(target))
    state = dependencies.status('maya', '2025', framework)
    suite.check('an install that never passed its import check does not count either',
                not state['satisfied'] and 'import check' in state['reason'], state['reason'])

    # -- the guard on the delete --------------------------------------- #
    outside = os.path.join(suite.temp, 'precious')
    os.makedirs(outside)
    message = suite.raises('emptying a folder outside the dependencies root is refused',
                           dependencies._clear_target, outside)
    suite.check('and the refusal names the folder it was protecting',
                'not a dependency folder' in message, message)
    suite.check('the folder is still there', os.path.isdir(outside))
    suite.raises('and so is emptying the dependencies root itself',
                 dependencies._clear_target, platform_paths.dependencies_root())

    dependencies._clear_target(target)
    suite.check('emptying a real dependency folder works, and leaves it empty',
                os.path.isdir(target) and not os.listdir(target))

    # ---------------------------------------------------------------- #
    # The environment a DCC is handed
    # ---------------------------------------------------------------- #
    project = prefs.ProjectPrefs.load('SampleGame')
    values = environment.build(project, 'maya', '2025',
                              base={'PATH': '/usr/bin', 'PYTHONPATH': '/somebody/elses/path',
                                    'QT_PLUGIN_PATH': '/the/launchers/qt'})
    suite.check('the dependency folder the launcher just filled is what the DCC is told about',
                values['MCA_COMMON_DEPEND'] == dependencies.target_folder('maya', '2025'),
                values['MCA_COMMON_DEPEND'])
    suite.check('and the DCC-specific variable points at the same place',
                values['MCA_MAYA_DEPEND'] == values['MCA_COMMON_DEPEND'])
    suite.check('nothing is set to None or to an empty string',
                all(isinstance(value, str) and value != ''
                    for key, value in values.items() if key.startswith('MCA_')),
                str({key: value for key, value in values.items()
                     if key.startswith('MCA_') and not value}))
    parts = values['PYTHONPATH'].split(os.pathsep)
    suite.check('the bootstrap folder is on PYTHONPATH',
                environment.startup_folder(framework, 'maya') in parts, values['PYTHONPATH'])
    # Deliberately NOT inherited: a shell's PYTHONPATH reaching Maya put a second copy of
    # the mca namespace in front of the real one, and Maya died on the splash screen.
    suite.check('and whatever the launching shell carried is left behind',
                '/somebody/elses/path' not in values['PYTHONPATH'], values['PYTHONPATH'])

    # The MCP package rides along when it is a sibling, which is what lets Maya's start-up
    # open the command ports an assistant reaches it through.
    mcp_folder = environment.mcp_package_folder()
    if mcp_folder:
        suite.check('the MCP package is handed to the DCC as well, by name and on the path',
                    values.get('MCA_MCP_PATH') == mcp_folder and mcp_folder in parts,
                    str(values.get('MCA_MCP_PATH')))
    else:
        suite.check('with no sibling mca-mcp, nothing about it is added',
                    'MCA_MCP_PATH' not in values, str(values.get('MCA_MCP_PATH')))
    # A DCC started from a first-run sandbox has to stay in the sandbox: mca-common reads
    # these same names for its preferences and its logs.
    suite.check('the folders the launcher was told to use are handed to the DCC on purpose, '
                'not left to be inherited',
                values.get('MCA_PREFS_ROOT') == os.environ['MCA_PREFS_ROOT'] and
                values.get('MCA_LOGS_ROOT') == os.environ['MCA_LOGS_ROOT'],
                str({name: values.get(name) for name in environment.ROOT_VARIABLES}))
    suite.check('and one that is not set is not invented',
                'MCA_LOGGING_LEVEL' in values or not os.getenv('MCA_LOGGING_LEVEL'),
                str(values.get('MCA_LOGGING_LEVEL')))

    suite.check('the launcher\'s own Qt variables are not passed on to the DCC',
                'QT_PLUGIN_PATH' not in values, str(values.get('QT_PLUGIN_PATH')))
    suite.check('MCA_COMMON_PATH points at mca-common itself',
                values['MCA_COMMON_PATH'] == os.path.normpath(
                    os.path.join(framework, 'mca-common', 'mca', 'common')))

    twice = environment.build(project, 'maya', '2025', base=values)
    suite.check('building twice does not add the bootstrap folder twice',
                twice['PYTHONPATH'] == values['PYTHONPATH'], twice['PYTHONPATH'])

    bare = prefs.ProjectPrefs({'MCA_PROJECT_NAME': 'Nothing'})
    suite.raises('a project with no framework path cannot build an environment',
                 environment.build, bare, 'maya', '2025')

    suite.check('unreal is told which project it is opening',
                environment.build(project, 'unreal', os.path.join(suite.temp, 'g.uproject'),
                                  base={})['UE_PROJECT_PATH'].endswith('g.uproject'))

    # ---------------------------------------------------------------- #
    # Desktop shortcuts
    # ---------------------------------------------------------------- #
    suite.check('a shortcut is named the way a person would write it',
                shortcuts.shortcut_name('Maya', '2025', 'SampleGame') == 'Maya 2025 - SampleGame',
                shortcuts.shortcut_name('Maya', '2025', 'SampleGame'))
    suite.check('an Unreal one is named after the project file, not its path',
                shortcuts.shortcut_name('Unreal Engine', r'D:\Games\SampleGame.uproject',
                                        'SampleGame') == 'Unreal Engine SampleGame - SampleGame',
                shortcuts.shortcut_name('Unreal Engine', r'D:\Games\SampleGame.uproject',
                                        'SampleGame'))
    suite.check('and nothing Windows refuses to have in a file name survives',
                '/' not in shortcuts.shortcut_name('Maya', '2025', 'A/B:C') and
                ':' not in shortcuts.shortcut_name('Maya', '2025', 'A/B:C'),
                shortcuts.shortcut_name('Maya', '2025', 'A/B:C'))

    target, leading = shortcuts.runner()
    suite.check('the launcher can say what a shortcut should start', bool(target),
                '{} {}'.format(target, leading))
    suite.check('and from a source checkout that is a runner script that exists',
                not leading or os.path.isfile(leading[0]), str(leading))
    suite.check('the runner script puts the package on the path itself, because a .lnk '
                'cannot set one',
                'sys.path' in dependencies.read_text(shortcuts.runner_script())
                if shortcuts.runner_script() else True)
    suite.check('the desktop is asked for, not assumed',
                bool(shortcuts.desktop_folder()), shortcuts.desktop_folder())

    # A quote in a project name would otherwise end the PowerShell string early, and the
    # rest of it would be run as code.
    suite.check("a quote in a name is escaped rather than ending the string",
                shortcuts._powershell_literal("O'Brien") == "O''Brien",
                shortcuts._powershell_literal("O'Brien"))
    suite.check('an argument with a space in it is quoted',
                shortcuts._quote(r'C:\Two Words\x.py') == r'"C:\Two Words\x.py"',
                shortcuts._quote(r'C:\Two Words\x.py'))
    suite.check('and one without is left alone', shortcuts._quote('maya:2025') == 'maya:2025')

    if platform_paths.IS_WINDOWS:
        # The real thing, PowerShell and all. Run on Windows only, which is where a shortcut
        # means anything - and where the escaping has to actually hold.
        made = shortcuts.write(os.path.join(suite.temp, "Probe O'Brien.lnk"), sys.executable,
                               arguments=['--version', os.path.join(suite.temp, 'two words')],
                               description='a shortcut written by the suite')
        suite.check('a shortcut is really written, by PowerShell, on Windows',
                    os.path.isfile(made), made)
        suite.check('and it is a real .lnk rather than an empty file',
                    os.path.getsize(made) > 300, str(os.path.getsize(made)))
    else:
        message = suite.raises('off Windows, writing one refuses instead of pretending',
                               shortcuts.write, os.path.join(suite.temp, 'x.lnk'),
                               'python')
        suite.check('and says why', 'Windows' in message, message)

    # ---------------------------------------------------------------- #
    # A package that installs and then will not load
    # ---------------------------------------------------------------- #
    # Measured on MotionBuilder 2024: it ships python310.dll and no python3.dll, so psutil's
    # stable-ABI wheel installs and then fails with "DLL load failed ... The specified module
    # could not be found". Maya, same Python version, is fine - so this is about the
    # interpreter, not about 3.10.
    abi_target = os.path.join(suite.temp, 'abi-deps')
    os.makedirs(os.path.join(abi_target, 'psutil'))
    os.makedirs(os.path.join(abi_target, 'psutil-7.2.2.dist-info'))
    os.makedirs(os.path.join(abi_target, 'numpy'))
    with open(os.path.join(abi_target, 'psutil', '_psutil_windows.pyd'), 'w') as opened:
        opened.write('')

    dependencies.remove_distribution(abi_target, 'psutil')
    suite.check('taking a package out of a dependency folder removes its dist-info too',
                sorted(os.listdir(abi_target)) == ['numpy'], str(os.listdir(abi_target)))

    os.makedirs(os.path.join(abi_target, 'psutil'))
    said = []
    real_run, real_verify = dependencies._run, dependencies.verify
    runs = []

    def fake_run(command, progress=None, timeout=None, cwd=None):
        runs.append(command)
        return 0, 'installed'

    def fake_verify(interpreter, target, imports):
        return {'ok': True, 'imported': list(imports), 'missing': {}}

    wanted = ['psutil >= 5.9.4', 'numpy']
    try:
        dependencies._run = fake_run
        dependencies.verify = fake_verify

        # Not a DLL failure: left alone, because this is a fix for one measured cause and
        # not a general "try an older version and hope".
        recovered = dependencies.recover_stable_abi(
            sys.executable, abi_target, wanted,
            {'psutil': 'ModuleNotFoundError no module named psutil'}, said.append)
        suite.check('a package that is simply missing is not downgraded',
                    recovered == {} and not runs, str(recovered))

        recovered = dependencies.recover_stable_abi(
            sys.executable, abi_target, wanted,
            {'psutil': 'ImportError DLL load failed while importing _psutil_windows: The '
                       'specified module could not be found.'}, said.append)
        suite.check('one that installed but cannot load its extension is retried pinned',
                    recovered == {'psutil': 'psutil == 5.9.3'}, str(recovered))
        suite.check('and the pin is what was handed to pip',
                    runs and 'psutil == 5.9.3' in runs[-1], str(runs[-1] if runs else []))
        suite.check('and the old copy was taken out first, because --target never uninstalls',
                    not os.path.isdir(os.path.join(abi_target, 'psutil')),
                    str(os.listdir(abi_target)))
        suite.check('and it says why, in words that name the cause',
                    any('python3.dll' in line for line in said), str(said))

        # A package nobody has a fallback for is reported, not guessed at.
        recovered = dependencies.recover_stable_abi(
            sys.executable, abi_target, ['somethingelse'],
            {'somethingelse': 'ImportError DLL load failed while importing _core'},
            said.append)
        suite.check('a package with no known good older build is left to be reported',
                    recovered == {}, str(recovered))
    finally:
        dependencies._run, dependencies.verify = real_run, real_verify

    # ---------------------------------------------------------------- #
    # Installers: whatever the studio actually keeps, for every DCC
    # ---------------------------------------------------------------- #
    class Pretend(dcc_base.Dcc):
        """A DCC with an installer folder and nothing installed."""

        name = 'pretend'
        label = 'Pretend'
        known_versions = ('2024', '2025')
        installer_folder = 'Pretend'
        installer_name = 'Pretend_Install.exe'
        download_url = 'https://example.invalid/pretend'

        def is_installed(self, version):
            return False

    pretend = Pretend()
    installers = os.path.join(suite.temp, 'installers')

    suite.check('with no installer folder, there is no installer and nothing breaks',
                pretend.installer('2025', '') == '' and
                pretend.installer_versions('') == [])

    # A studio whose Maya arrives by batch file - which the old launcher could not express,
    # because it looked for one hard coded .exe name and nothing else.
    batch_folder = os.path.join(installers, 'Pretend', '2025')
    os.makedirs(batch_folder)
    batch = os.path.join(batch_folder, 'deploy_pretend.bat')
    with open(batch, 'w') as opened:
        opened.write('@echo off\n')

    suite.check('a .bat is an installer',
                pretend.installer('2025', installers) == os.path.normpath(batch),
                pretend.installer('2025', installers))
    suite.check('and the version it sits under is offered',
                pretend.installer_versions(installers) == ['2025'],
                str(pretend.installer_versions(installers)))

    # And when the old convention is there as well, it still wins, so an existing studio
    # layout behaves exactly as it did.
    named = os.path.join(batch_folder, 'Pretend_Install.exe')
    with open(named, 'w') as opened:
        opened.write('')
    suite.check('the name the old launcher expected is preferred when it is there',
                pretend.installer('2025', installers) == os.path.normpath(named),
                pretend.installer('2025', installers))

    # A version nobody hard coded: the folder is the whole configuration.
    unknown = os.path.join(installers, 'Pretend', '2027')
    os.makedirs(unknown)
    with open(os.path.join(unknown, 'install.ps1'), 'w') as opened:
        opened.write('exit 0\n')
    suite.check('a version only the studio knows about is offered too',
                pretend.installer_versions(installers) == ['2025', '2027'],
                str(pretend.installer_versions(installers)))
    offered = [target.key for target in pretend.available(installers)]
    suite.check('and it lands in the list, newest first, beside the ones in the code',
                offered == ['2027', '2025', '2024'], str(offered))
    # An empty folder is not a version anybody can install: offering it would turn Install
    # into a button that does nothing.
    os.makedirs(os.path.join(installers, 'Pretend', '2026'))
    suite.check('a folder with nothing runnable in it is not offered',
                '2026' not in pretend.installer_versions(installers),
                str(pretend.installer_versions(installers)))

    # What a not-installed version says about itself: where it would come from, rather than
    # only that it is missing.
    by_key = {target.key: target for target in pretend.available(installers)}
    suite.check('a version with an installer says where the installer is',
                by_key['2025'].detail == os.path.normpath(named), by_key['2025'].detail)
    suite.check('and one without says where to download it',
                by_key['2024'].detail == pretend.download_url, by_key['2024'].detail)

    # -- how each kind gets run ---------------------------------------- #
    suite.check('an .exe is run directly',
                dcc_base.installer_command(r'c:\i\setup.exe') == [r'c:\i\setup.exe'],
                str(dcc_base.installer_command(r'c:\i\setup.exe')))
    command = dcc_base.installer_command(r'c:\i\go.bat')
    suite.check('a .bat is run by the shell, as an argument rather than as a command line',
                command[1:] == ['/c', r'c:\i\go.bat'], str(command))
    suite.check('a .cmd too', dcc_base.installer_command('go.cmd')[1:] == ['/c', 'go.cmd'])
    suite.check('an .msi goes through msiexec',
                dcc_base.installer_command('m.msi') == ['msiexec', '/i', 'm.msi'],
                str(dcc_base.installer_command('m.msi')))
    suite.check('a .ps1 goes through powershell, with the policy it needs',
                dcc_base.installer_command('s.ps1')[0] == 'powershell' and
                '-ExecutionPolicy' in dcc_base.installer_command('s.ps1'),
                str(dcc_base.installer_command('s.ps1')))
    suite.check('a .py is run by this Python',
                dcc_base.installer_command('s.py') == [sys.executable, 's.py'],
                str(dcc_base.installer_command('s.py')))
    suite.check('a shortcut is started by the shell',
                'start' in dcc_base.installer_command('s.lnk'),
                str(dcc_base.installer_command('s.lnk')))

    # -- Unreal is not the exception it used to be --------------------- #
    from mca.launcher.core import dccs

    unreal = dccs.get('unreal')
    engine_folder = os.path.join(installers, 'Unreal', '5.5')
    os.makedirs(engine_folder)
    deploy = os.path.join(engine_folder, 'deploy_engine.bat')
    with open(deploy, 'w') as opened:
        opened.write('@echo off\n')
    suite.check('Unreal has an installer folder like everything else',
                unreal.installer_folder == 'Unreal', unreal.installer_folder)
    suite.check('so an engine a studio deploys with a .bat can be installed from the launcher',
                unreal.installer('5.5', installers) == os.path.normpath(deploy),
                unreal.installer('5.5', installers))
    suite.check('and that engine is offered even when this machine has no Unreal at all',
                '5.5' in [target.key for target in unreal.available(installers)],
                str([target.key for target in unreal.available(installers)]))

    # -- the installer folder a project points at ---------------------- #
    installer_project = os.path.join(suite.temp, 'proj')
    os.makedirs(installer_project)
    saved = projects.save_project('Installers', installer_project, framework,
                                 art_paths={'MCA_INSTALLERS_PATH': installers})
    suite.check('a project can say where its installers are',
                projects.installers_root(saved) == os.path.normpath(installers),
                projects.installers_root(saved))
    legacy_root = os.path.join(suite.temp, 'legacy')
    os.makedirs(os.path.join(legacy_root, 'Tools', 'DCC Launcher', 'DCCAppLaunchers'))
    legacy = projects.save_project('Legacy', legacy_root, framework)
    suite.check('and when it does not, the layout the old launcher assumed is still found',
                projects.installers_root(legacy).endswith('DCCAppLaunchers'),
                projects.installers_root(legacy))

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('core', body))
