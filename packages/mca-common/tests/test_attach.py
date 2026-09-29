"""
Attaching to a project from outside a DCC.

This is what the editor, a farm job or a standalone script uses to answer "which project?"
without being told, and the answer has to agree with what the launcher wrote - so the suite
builds the launcher's files by hand, exactly as the launcher writes them, and reads them
back.

    python tests/test_attach.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.paths import project_paths  # noqa: E402
from mca.common.startup import attach  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import datafile, yamlio  # noqa: E402


def body(suite):
    temp = suite.temp
    prefs_root = project_paths.get_preferences_root()

    # ---------------------------------------------------------------- #
    # Nothing set up at all
    # ---------------------------------------------------------------- #
    os.environ.pop(consts.MCA_PROJECT_NAME, None)
    suite.check('with no project anywhere, there is no current project',
                attach.current_project_name() == '')

    report = attach.attach()
    suite.check('and attaching refuses rather than guessing', not report['ok'])
    suite.check('and the refusal says where it looked and what to do',
                consts.MCA_LAUNCHER_PREFS_FILE in report['message'] and
                'launcher' in report['message'], report['message'])

    # ---------------------------------------------------------------- #
    # A project, written the way the launcher writes it
    # ---------------------------------------------------------------- #
    framework = os.path.join(temp, 'depot', 'packages')
    os.makedirs(os.path.join(framework, 'mca-common', 'mca', 'common'))
    os.makedirs(os.path.join(framework, 'mca-maya', 'mca', 'mya'))
    project_root = os.path.join(temp, 'Wayward')
    os.makedirs(project_root)

    yamlio.write_to_yaml_file(
        {consts.MCA_PROJECT_NAME: 'Wayward',
         consts.MCA_PROJECT_ROOT: project_root,
         consts.MCA_FRAMEWORK_PATH: framework,
         consts.MCA_CHARACTERS_PATH: os.path.join(temp, 'art', 'Characters')},
        project_paths.get_preferences_file('Wayward'))

    datafile.write({'mca_directories': {'maya': {'depots': ['mca-maya']}}},
                   os.path.join(framework, consts.MCA_PACKAGE_BOOTS), fmt='yaml')

    # The launcher's own file: which project was open last.
    datafile.write({'version': 2, consts.CURRENT_PROJECT_KEY: 'Wayward'},
                   os.path.join(prefs_root, consts.MCA_LAUNCHER_PREFS_FILE), fmt='yaml')

    suite.check('the current project is read from the file the launcher writes',
                attach.current_project_name() == 'Wayward',
                attach.current_project_name())
    suite.check('and the framework path comes from that project\'s preferences',
                attach.framework_for('Wayward') == framework,
                attach.framework_for('Wayward'))

    # ---------------------------------------------------------------- #
    # Attaching
    # ---------------------------------------------------------------- #
    before = list(sys.path)
    report = attach.attach()
    suite.check('attaching works out the project by itself', report['ok'] and
                report['project'] == 'Wayward', report['message'])
    suite.check('and puts that project\'s mca-common in front, so it is the copy that '
                'answers from here on',
                sys.path[0] == os.path.join(framework, 'mca-common'), sys.path[0])
    suite.check('and sets the project environment',
                os.getenv(consts.MCA_PROJECT_NAME) == 'Wayward' and
                os.getenv(consts.MCA_CHARACTERS_PATH, '').endswith('Characters'),
                str(os.getenv(consts.MCA_CHARACTERS_PATH)))

    # The editor's case: it already has an mca-common, probably pip-installed, and the
    # project's checkout is a different one.
    suite.check('it says when another mca was already imported from somewhere else',
                bool(report['shadowed']), str(report['shadowed']))
    suite.check('and the message explains what that means rather than leaving it to be '
                'discovered', 'still come from there' in report['message'],
                report['message'])

    sys.path[:] = before

    # ---------------------------------------------------------------- #
    # A named project, and a DCC's packages
    # ---------------------------------------------------------------- #
    report = attach.attach('Wayward', dcc='maya', set_environment=False)
    suite.check('a DCC can be named, and its packages come too',
                any(one.endswith('mca-maya') for one in report['added']),
                str(report['added']))
    sys.path[:] = before

    report = attach.attach('NoSuchProject')
    suite.check('a project that is not set up is refused', not report['ok'])
    suite.check('and the refusal names the file it wanted',
                consts.MCA_LOCAL_PREFS_FILE in report['message'] or
                'preferences' in report['message'], report['message'])

    # ---------------------------------------------------------------- #
    # A project that points somewhere that is not there
    # ---------------------------------------------------------------- #
    yamlio.write_to_yaml_file(
        {consts.MCA_PROJECT_NAME: 'Gone',
         consts.MCA_FRAMEWORK_PATH: os.path.join(temp, 'deleted', 'packages')},
        project_paths.get_preferences_file('Gone'))
    report = attach.attach('Gone')
    suite.check('a framework path that does not exist is refused, rather than half an '
                'attach', not report['ok'] and 'no folder there' in report['message'],
                report['message'])

    # ---------------------------------------------------------------- #
    # The environment wins over the launcher's file, when something set it
    # ---------------------------------------------------------------- #
    os.environ[consts.MCA_PROJECT_NAME] = 'Gone'
    suite.check('a prepared environment is believed before the launcher\'s last choice',
                attach.resolve_project() == 'Gone', attach.resolve_project())
    suite.check('and an explicit name beats both',
                attach.resolve_project('Wayward') == 'Wayward')
    os.environ[consts.MCA_PROJECT_NAME] = 'Wayward'

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('attach', body))
