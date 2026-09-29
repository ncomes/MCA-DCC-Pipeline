"""
The DCC start-up scripts, checked without a DCC.

The three scripts are what runs before anything else in Maya, MotionBuilder and Unreal, and
they are the hardest thing in the framework to test by hand: getting it wrong costs a DCC
restart, and getting it wrong quietly costs a day. So the shared part is a module, and this
runs it.

    python tests/test_dcc_bootstrap.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.startup.dccs import bootstrap  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402


def body(suite):
    temp = suite.temp

    # ---------------------------------------------------------------- #
    # Finding the framework without being told where it is
    # ---------------------------------------------------------------- #
    root = bootstrap.package_root()
    suite.check('the package root is worked out from the file, not the environment',
                os.path.isdir(os.path.join(root, 'mca', 'common')), root)
    suite.check('and it is the folder that goes on sys.path',
                os.path.basename(root) == 'mca-common', root)

    # Every script does the same, from a folder one deeper. Same answer.
    for script in ('maya/Scripts/userSetup.py', 'mobu/Scripts/startup.py',
                   'unreal/Scripts/init_unreal.py'):
        path = os.path.join(root, 'mca', 'common', 'startup', 'dccs', *script.split('/'))
        suite.check('{} is there'.format(os.path.basename(path)), os.path.isfile(path), path)
        here = os.path.dirname(os.path.abspath(path))
        for _ in range(6):
            here = os.path.dirname(here)
        suite.check('and works out the same framework path from its own location',
                    os.path.normpath(here) == root, os.path.normpath(here))

    # ---------------------------------------------------------------- #
    # Paths, from variables that may not be set
    # ---------------------------------------------------------------- #
    # This is the one that used to kill a DCC's start-up: os.path.dirname(None).
    os.environ.pop(consts.MCA_COMMON_DEPEND, None)
    suite.check('adding paths copes with nothing at all rather than raising TypeError',
                bootstrap.add_to_path(None, '', os.getenv(consts.MCA_COMMON_DEPEND)) == [])

    real = os.path.join(temp, 'deps')
    os.makedirs(real)
    suite.check('a folder that exists is added', bootstrap.add_to_path(real) == [real])
    suite.check('and adding it twice does not put it on twice',
                bootstrap.add_to_path(real) == [] and sys.path.count(real) == 1)
    suite.check('a folder that does not exist is skipped, not added',
                bootstrap.add_to_path(os.path.join(temp, 'nope')) == [])
    sys.path.remove(real)

    # ---------------------------------------------------------------- #
    # The project name
    # ---------------------------------------------------------------- #
    os.environ.pop(consts.MCA_PROJECT_NAME, None)
    suite.check('with no project set, there is no project - not a default that quietly '
                'starts somebody else\'s', bootstrap.project_name() == '')

    said = []
    started = bootstrap.start('maya', say=said.append)
    suite.check('and the framework refuses to start rather than guessing', not started)
    suite.check('and says what is missing and what to do',
                any('MCA_PROJECT_NAME' in line for line in said) and
                any('launcher' in line for line in said), str(said))

    # ---------------------------------------------------------------- #
    # It never takes the DCC down with it
    # ---------------------------------------------------------------- #
    os.environ[consts.MCA_PROJECT_NAME] = 'Wayward'
    from mca.common.startup import startup as startup_module

    real_startup = startup_module.startup_init

    def angry(*args, **kwargs):
        raise RuntimeError('the framework is in pieces')

    said = []
    try:
        startup_module.startup_init = angry
        started = bootstrap.start('maya', say=said.append)
    finally:
        startup_module.startup_init = real_startup

    suite.check('a framework that blows up on start answers False rather than raising into '
                'the DCC, where it would stop everything after it in userSetup.py',
                started is False)
    suite.check('and the reason is printed where somebody will see it',
                any('in pieces' in line for line in said), str(said[:2]))

    # ---------------------------------------------------------------- #
    # The command ports
    # ---------------------------------------------------------------- #
    os.environ.pop('MCA_MCP_PATH', None)
    suite.check('with mca-mcp not installed, the command ports are simply not opened',
                bootstrap.start_mcp(say=said.append) is False)

    # ---------------------------------------------------------------- #
    # The requirements list the launcher reads
    # ---------------------------------------------------------------- #
    requirements = os.path.join(root, 'mca', 'common', 'startup', 'dependencies',
                                'requirements.txt')
    suite.check('mca-common ships the requirements list, where the launcher looks for it',
                os.path.isfile(requirements), requirements)
    with open(requirements, 'r', encoding='utf-8') as opened:
        text = opened.read()
    named = [line.split()[0].lower() for line in text.splitlines()
             if line.strip() and not line.startswith('#')]
    suite.check('and it names the packages the framework cannot start without',
                all(one in named for one in ('numpy', 'pyyaml', 'psutil', 'anytree')),
                str(named))
    suite.check('pymel is not in it, and nothing installs it during a DCC start-up any more',
                'pymel' not in named, str(named))

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('dcc_bootstrap', body))
