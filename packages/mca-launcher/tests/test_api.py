"""
The API surface, end to end, with a pretend DCC standing in for Maya.

The point of the pretend DCC is the one behaviour that matters most and is hardest to test
for real: **a DCC is not started when its dependencies are not ready.** Here the install is
made to fail on purpose, and the check is that nothing was launched - not that a warning was
logged somewhere.

Run it with any Python 3.9 or newer::

    python tests/test_api.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.launcher import api  # noqa: E402
from mca.launcher.core import dccs, dependencies, fileio, prefs  # noqa: E402
from mca.launcher.core.dccs.base import Dcc, LaunchTarget  # noqa: E402


DUMP = '''
import json, os, sys
with open(sys.argv[1], 'w') as handle:
    json.dump({key: value for key, value in os.environ.items()
               if key.startswith(('MCA_', 'PYTHONPATH', 'UE_'))}, handle)
'''


class PretendDcc(Dcc):
    """A DCC that is this Python, and whose 'application' writes its environment to a file."""

    name = 'pretend'
    label = 'Pretend'
    icon = 'default_icon.png'
    startup_folder = 'maya'

    def __init__(self, script, output):
        self.script = script
        self.output = output

    def targets(self):
        return [LaunchTarget(self.name, '2025', 'Pretend 2025'),
                LaunchTarget(self.name, '2024', 'Pretend 2024')]

    def interpreter(self, version):
        return sys.executable

    def executable(self, version):
        return sys.executable

    def command(self, key):
        return [sys.executable, self.script, self.output]


def body(suite):
    # ---------------------------------------------------------------- #
    # Nothing set up yet
    # ---------------------------------------------------------------- #
    listing = api.list_projects()
    suite.check('with nothing set up, listing projects still answers ok',
                listing['ok'] and listing['result']['projects'] == [], listing['message'])
    suite.check('and the message says how to make one',
                'save_project' in listing['message'] or 'setup' in listing['message'],
                listing['message'])

    started = api.launch('maya')
    suite.check('launching with no project refuses, rather than raising',
                not started['ok'], started['message'])
    suite.check('and the refusal says what to do',
                'project' in started['message'].lower(), started['message'])

    unknown = api.launch('blender')
    suite.check('an unknown DCC name is refused by name, with the list of known ones',
                not unknown['ok'] and 'blender' in unknown['message'], unknown['message'])

    # ---------------------------------------------------------------- #
    # A project
    # ---------------------------------------------------------------- #
    framework = os.path.join(suite.temp, 'repo', 'packages')
    common = os.path.join(framework, 'mca-common', 'mca', 'common')
    os.makedirs(os.path.join(common, 'startup', 'dependencies'))
    os.makedirs(os.path.join(common, 'startup', 'dccs', 'maya', 'Scripts'))
    with open(os.path.join(common, 'startup', 'dependencies', 'requirements.txt'), 'w') as f:
        f.write('numpy\nPyYAML\nPySide6\n')
    project_root = os.path.join(suite.temp, 'project')
    os.makedirs(project_root)

    saved = api.save_project('Wayward', project_root, framework,
                             art_path=os.path.join(suite.temp, 'art'))
    suite.check('a project saves through the API', saved['ok'], saved['message'])
    suite.check('and the message names where it went',
                'mca_project.prefs' in saved['message'], saved['message'])

    current = api.current_project()
    suite.check('it becomes the current project',
                current['ok'] and current['result']['name'] == 'Wayward', current['message'])

    suite.check('a second project can be added',
                api.save_project('Other', project_root, framework)['ok'])
    suite.check('and switching between them works',
                api.set_current_project('Wayward')['ok'])
    suite.check('switching to one that does not exist is refused',
                not api.set_current_project('Nothing')['ok'])

    # ---------------------------------------------------------------- #
    # Unreal projects
    # ---------------------------------------------------------------- #
    uproject = os.path.join(suite.temp, 'Game.uproject')
    with open(uproject, 'w') as handle:
        handle.write('{"EngineAssociation": "5.5"}')

    added = api.add_unreal_project(uproject)
    suite.check('an Unreal project can be added', added['ok'], added['message'])
    suite.check('and the engine it asks for is read out of the file',
                added['result']['engine'] == '5.5', str(added['result']))
    suite.check('adding it twice does not duplicate it',
                len(api.unreal_projects()['result']) == 1,
                str(api.unreal_projects()['result']))
    suite.check('something that is not a .uproject is refused',
                not api.add_unreal_project(os.path.join(suite.temp, 'nope.txt'))['ok'])
    suite.check('and removing it works', api.remove_unreal_project(uproject)['result']['removed'])

    # ---------------------------------------------------------------- #
    # The pretend DCC
    # ---------------------------------------------------------------- #
    script = os.path.join(suite.temp, 'dump.py')
    with open(script, 'w') as handle:
        handle.write(DUMP)
    # Outside the suite's temp folder on purpose: the process writes this after it starts,
    # and the suite deletes its temp folder on the way out.
    import tempfile
    output = os.path.join(tempfile.gettempdir(), 'mca_api_environment.json')
    if os.path.exists(output):
        os.remove(output)
    pretend = PretendDcc(script, output)

    real_dccs, real_by_name = dccs.DCCS, dccs.BY_NAME
    dccs.DCCS = (pretend,)
    dccs.BY_NAME = {'pretend': pretend}
    real_install = dependencies.install
    try:
        listing = api.dcc_targets()
        suite.check('the DCC listing reports what is installed',
                    listing['ok'] and listing['result'][0]['targets'][0]['key'] == '2025',
                    listing['message'])
        suite.check('and with nothing remembered, the newest is chosen',
                    listing['result'][0]['chosen'] == '2025',
                    str(listing['result'][0]['chosen']))

        state = api.dependency_status('pretend', '2025')
        suite.check('dependencies start out not ready',
                    state['ok'] and not state['result']['satisfied'], state['message'])

        # -- an install that fails ------------------------------------ #
        def failing_install(dcc, version, framework_path, interpreter, progress=None):
            if progress:
                progress('pretending to install')
            return {'ok': False, 'target': dependencies.target_folder(dcc, version),
                    'skipped': [], 'missing': {'numpy': 'ModuleNotFoundError'},
                    'imported': [], 'stamp': {},
                    'message': 'numpy could not be imported afterwards.'}

        dependencies.install = failing_install
        lines = []
        started = api.launch('pretend', '2025', progress=lines.append)
        suite.check('a failed dependency install means the DCC is NOT started',
                    not started['ok'] and not os.path.exists(output), started['message'])
        suite.check('and the message says that is why',
                    'dependencies are not ready' in started['message'], started['message'])
        suite.check('and the progress was reported as it went',
                    any('install' in line for line in lines), str(lines))

        # -- an install that works ------------------------------------ #
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
                    'imported': ['numpy', 'yaml'], 'stamp': {},
                    'message': 'installed 2 package(s).'}

        dependencies.install = working_install
        started = api.launch('pretend', '2025')
        suite.check('with dependencies ready, the DCC is started', started['ok'],
                    started['message'])
        suite.check('and a process id comes back',
                    isinstance(started['result'].get('pid'), int), str(started['result']))

        # The pretend application writes its environment out; give it a moment.
        for _ in range(100):
            if os.path.exists(output):
                break
            import time
            time.sleep(0.05)
        handed = fileio.read_json(output, default={})
        suite.check('the environment really did reach the process it started',
                    handed.get('MCA_PROJECT_NAME') == 'Wayward', str(sorted(handed)))
        suite.check('including the dependency folder for that exact version',
                    handed.get('MCA_COMMON_DEPEND', '').endswith('pretend-2025'),
                    handed.get('MCA_COMMON_DEPEND', ''))
        suite.check('and the framework path',
                    handed.get('MCA_FRAMEWORK_PATH') == os.path.normpath(framework),
                    handed.get('MCA_FRAMEWORK_PATH', ''))

        suite.check('the version that was launched is remembered by name',
                    prefs.Selections.load('Wayward').dccs.get('pretend') == '2025',
                    str(prefs.Selections.load('Wayward').dccs))

        # -- the second launch is the cheap one ----------------------- #
        calls = []

        def counting_install(*args, **kwargs):
            calls.append(args)
            return working_install(*args, **kwargs)

        dependencies.install = counting_install
        again = api.launch('pretend', '2025')
        suite.check('a second launch does not reinstall anything', again['ok'] and not calls,
                    str(calls))
        suite.check('and says the dependencies were already there',
                    'installed' in again['message'] or 'has its dependencies' in
                    again['message'], again['message'])

        forced = api.ensure_dependencies('pretend', '2025', force=True)
        suite.check('but asking for a reinstall does reinstall', forced['ok'] and len(calls) == 1,
                    str(len(calls)))

        # -- changing the list invalidates it ------------------------- #
        with open(os.path.join(common, 'startup', 'dependencies', 'requirements.txt'), 'a') as f:
            f.write('psutil\n')
        state = api.dependency_status('pretend', '2025')
        suite.check('adding a package to the requirements list makes it out of date',
                    not state['result']['satisfied'] and 'changed' in state['message'],
                    state['message'])

        # -- doctor --------------------------------------------------- #
        report = api.doctor()
        suite.check('doctor reports the project, the framework and every DCC it found',
                    report['ok'] and report['result']['project'] == 'Wayward'
                    and len(report['result']['dccs']) == 2, report['message'])
        suite.check('and lists the out-of-date dependencies as a problem',
                    any('changed' in problem for problem in report['result']['problems']),
                    str(report['result']['problems']))
    finally:
        dccs.DCCS, dccs.BY_NAME = real_dccs, real_by_name
        dependencies.install = real_install

    # ---------------------------------------------------------------- #
    # Removing a project
    # ---------------------------------------------------------------- #
    removed = api.remove_project('Other')
    suite.check('a project can be removed', removed['ok'], removed['message'])
    suite.check('and the other one is still there',
                [one['name'] for one in api.list_projects()['result']['projects']] == ['Wayward'])
    suite.check('removing it twice is refused', not api.remove_project('Other')['ok'])

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('api', body))
