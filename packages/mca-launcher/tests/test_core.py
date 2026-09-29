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
    saved = projects.save_project('Wayward', project_root, framework,
                                  art_paths=projects.default_art_paths(
                                      os.path.join(suite.temp, 'art')))
    suite.check('a project saves', os.path.isfile(prefs.project_prefs_file('Wayward')))
    suite.check('and is listed', [one['name'] for one in projects.list_projects()] == ['Wayward'])
    suite.check('and is complete', not saved.missing(), str(saved.missing()))

    reloaded = prefs.ProjectPrefs.load('Wayward')
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
    fileio.write_yaml(old, prefs.launcher_prefs_file('Wayward', create=True))
    selections = prefs.Selections.load('Wayward')
    suite.check('an old preferences file keeps its Unreal projects',
                selections.unreal_projects == [os.path.join(suite.temp, 'game.uproject')],
                str(selections.unreal_projects))
    suite.check('and drops the dropdown positions, which cannot be trusted',
                selections.dccs == {}, str(selections.dccs))
    suite.check('so the newest installed version is offered instead',
                selections.chosen('maya', ['2026', '2025', '2024']) == '2026')

    selections.choose('maya', '2025')
    selections.save('Wayward')
    suite.check('a choice is remembered by name',
                prefs.Selections.load('Wayward').dccs == {'maya': '2025'},
                str(prefs.Selections.load('Wayward').dccs))
    suite.check('and a remembered version that is no longer installed falls back to the '
                'newest that is',
                prefs.Selections.load('Wayward').chosen('maya', ['2026', '2024']) == '2026')

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
    project = prefs.ProjectPrefs.load('Wayward')
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
    suite.check('PYTHONPATH keeps what the machine already had',
                '/somebody/elses/path' in values['PYTHONPATH'], values['PYTHONPATH'])
    parts = values['PYTHONPATH'].split(os.pathsep)
    suite.check('and the bootstrap folder is in front of it',
                environment.startup_folder(framework, 'maya') in parts
                and parts.index(environment.startup_folder(framework, 'maya'))
                < parts.index('/somebody/elses/path'), values['PYTHONPATH'])

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

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('core', body))
