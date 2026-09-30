"""
Source control: the interface, the nothing-installed backend, and Perforce driven against a
stand-in for ``p4``.

    python tests/test_sourcecontrol.py

The stand-in is ``fake_p4.py``, which records the exact argument list it was handed. That is
what proves the thing this port was for: a path with a space in it reaching p4 as one
argument rather than two.
"""

# python imports
import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import sourcecontrol  # noqa: E402
from mca.common.sourcecontrol import base, perforce  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.utils import platforms  # noqa: E402


def install_fake_p4(temp):
    """
    Put a stand-in for ``p4`` on PATH.

    :param str temp: A folder to build it in.
    :return: The folder it went in, and the file its calls are recorded to.
    :rtype: (str, str)
    """

    folder = os.path.join(temp, 'bin')
    os.makedirs(folder, exist_ok=True)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fake_p4.py')
    log = os.path.join(temp, 'p4_calls.log')

    if platforms.IS_WINDOWS:
        launcher = os.path.join(folder, 'p4.bat')
        with open(launcher, 'w', encoding='utf-8', newline='\r\n') as opened:
            opened.write('@echo off\r\n"{0}" "{1}" %*\r\n'.format(sys.executable, script))
    else:
        launcher = os.path.join(folder, 'p4')
        with open(launcher, 'w', encoding='utf-8') as opened:
            opened.write('#!{0}\n'.format(sys.executable))
            opened.write('import runpy, sys\n')
            opened.write('sys.argv[0] = {0!r}\n'.format(script))
            opened.write('runpy.run_path({0!r}, run_name="__main__")\n'.format(script))
        os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    os.environ['PATH'] = folder + os.pathsep + os.environ.get('PATH', '')
    os.environ['MCA_FAKE_P4_LOG'] = log

    return folder, log


def calls(log):
    """
    :param str log: Where the stand-in recorded its calls.
    :return: One argument list per call.
    :rtype: list[list[str]]
    """

    if not os.path.isfile(log):
        return []
    with open(log, encoding='utf-8') as opened:
        return [json.loads(line) for line in opened if line.strip()]


def body(suite):
    # ---------------------------------------------------------------- #
    # the small things the interface is built on
    # ---------------------------------------------------------------- #
    suite.check('a result knows whether it worked, and reads as a truth value',
                bool(base.Result(True)) and not bool(base.Result(False, 'no')) and
                base.Result(False, 'why').message == 'why')
    suite.check('one path, several paths, a tuple or a generator all become a list of paths',
                base.as_paths('a/b') == [os.path.normpath('a/b')] and
                base.as_paths(('a', 'b')) == [os.path.normpath('a'), os.path.normpath('b')] and
                base.as_paths(p for p in ['a']) == [os.path.normpath('a')])
    suite.check('and nothing at all is an empty list, not a list holding None',
                base.as_paths(None) == [] and base.as_paths([]) == [] and base.as_paths(['', None]) == [])

    # ---------------------------------------------------------------- #
    # no source control: a laptop, a build agent, somebody reading the repo
    # ---------------------------------------------------------------- #
    nothing = base.NoSourceControl()
    suite.check('with no source control, every operation succeeds and says it did nothing',
                all(bool(operation(['x'])) for operation in
                    (nothing.checkout, nothing.add, nothing.delete, nothing.revert,
                     nothing.sync, nothing.submit)))
    suite.check('and it does not pretend to be set up',
                nothing.available() is False and nothing.info() == {})

    # ---------------------------------------------------------------- #
    # an empty folder that has to be stored anyway
    # ---------------------------------------------------------------- #
    # Perforce and Git version files, not folders, so a freshly made empty folder cannot be
    # submitted. The version this replaces had this in fileio, calling Perforce from a file
    # helper.
    empty = os.path.join(suite.temp, 'Meshes')
    has_something = os.path.join(suite.temp, 'Rigs')
    os.makedirs(empty, exist_ok=True)
    os.makedirs(has_something, exist_ok=True)
    with open(os.path.join(has_something, 'hero_rig.ma'), 'w', encoding='utf-8') as opened:
        opened.write('//')

    suite.check('with no source control, an empty folder needs no placeholder',
                nothing.add_placeholders([empty, has_something]) == [])

    class Marked(base.NoSourceControl):
        """A backend that does version files rather than folders."""

        placeholder_name = '.keep'

        def __init__(self):
            self.added = []

        def add(self, paths, changelist=''):
            self.added.extend(base.as_paths(paths))
            return base.Result(True)

    marked = Marked()
    written = marked.add_placeholders([empty, has_something, os.path.join(suite.temp, 'nope')])
    suite.check('an empty folder gets one, a folder with something in it does not, and a '
                'folder that is not there is stepped over',
                len(written) == 1 and written[0] == os.path.join(empty, '.keep'),
                str(written))
    suite.check('and the placeholder is marked for adding, since that is the point of it',
                marked.added == written, str(marked.added))
    suite.check('doing it twice does not rewrite the one already there',
                marked.add_placeholders(empty) == written)

    # ---------------------------------------------------------------- #
    # which backend answers
    # ---------------------------------------------------------------- #
    was_variable = os.environ.get(sourcecontrol.VARIABLE)
    try:
        os.environ[sourcecontrol.VARIABLE] = 'none'
        sourcecontrol.reset()
        suite.check('MCA_SOURCE_CONTROL=none turns it off',
                    sourcecontrol.name() == 'none' and sourcecontrol.available() is False)

        os.environ[sourcecontrol.VARIABLE] = 'subversion'
        sourcecontrol.reset()
        suite.check('a name the framework does not know falls back to none rather than raising',
                    sourcecontrol.name() == 'none')

        os.environ[sourcecontrol.VARIABLE] = 'perforce'
        sourcecontrol.reset()
        suite.check('and naming perforce gets perforce, set up or not, so it can say why not',
                    sourcecontrol.name() == 'perforce')
    finally:
        if was_variable is None:
            os.environ.pop(sourcecontrol.VARIABLE, None)
        else:
            os.environ[sourcecontrol.VARIABLE] = was_variable
        sourcecontrol.reset()

    suite.check('a tool can be handed a backend directly, for a test or a special case',
                sourcecontrol.use(nothing) is nothing and sourcecontrol.name() == 'none')
    sourcecontrol.reset()

    # ---------------------------------------------------------------- #
    # Perforce, against a stand-in for p4
    # ---------------------------------------------------------------- #
    folder, log = install_fake_p4(suite.temp)
    workspace_root = os.path.join(suite.temp, 'depot')
    os.makedirs(workspace_root, exist_ok=True)
    with open(os.path.join(workspace_root, consts.MCA_PROJECT_CONFIG_NAME), 'w',
              encoding='utf-8') as opened:
        opened.write('{}')
    os.environ['MCA_FAKE_P4_ROOT'] = workspace_root
    os.environ['P4USER'] = 'ncomes'
    os.environ['P4PORT'] = 'ssl:perforce.example.com:1666'
    os.environ.pop('P4CLIENT', None)

    p4 = perforce.Perforce()
    suite.check('p4 is found on PATH', bool(p4.executable), p4.executable)
    suite.check('the user and port are read from the environment',
                p4.user == 'ncomes' and p4.port.endswith(':1666'), '{0} {1}'.format(p4.user, p4.port))
    suite.check('and the workspace is the one whose root holds the project config',
                p4.workspace == 'ws_project', p4.workspace)
    suite.check('so it reports itself as set up',
                p4.available() and p4.info().get('workspace') == 'ws_project')
    suite.check('and it can list every workspace the user has',
                p4.workspaces() == ['ws_other', 'ws_project'], str(p4.workspaces()))

    # -- the headline: a path with a space in it ---------------------- #
    # The version this replaces built 'P4 -p {port} -c {ws} edit -c {cl} {path}' and ran it
    # through shell=True, so 'hero rig v2.ma' arrived as three separate paths.
    scene = os.path.join(workspace_root, 'Characters', 'hero rig v2.ma')
    os.makedirs(os.path.dirname(scene), exist_ok=True)
    with open(scene, 'w', encoding='utf-8') as opened:
        opened.write('not really a scene')

    open(log, 'w').close()
    suite.check('checking out a path with spaces in it works', bool(p4.checkout(scene)))
    recorded = calls(log)
    suite.check('and p4 was handed that path as exactly one argument',
                recorded and recorded[-1][-1] == scene,
                str(recorded[-1] if recorded else None))
    suite.check('with the port and workspace in front of the command',
                '-p' in recorded[-1] and '-c' in recorded[-1] and 'reconcile' in recorded[-1],
                str(recorded[-1]))

    open(log, 'w').close()
    p4.checkout([scene, scene], changelist='4011')
    recorded = calls(log)
    suite.check('a changelist is passed as its own argument',
                recorded[-1][recorded[-1].index('-c', recorded[-1].index('reconcile')) + 1] == '4011',
                str(recorded[-1]))
    suite.check('and two files are two calls, so one failing does not hide the other',
                len(recorded) == 2, str(len(recorded)))

    # -- the other operations ---------------------------------------- #
    open(log, 'w').close()
    p4.add(scene)
    p4.delete(scene)
    p4.revert(scene)
    p4.revert(scene, unchanged_only=False)
    recorded = calls(log)
    suite.check('add, delete and revert each run their own p4 command',
                ['add', 'delete', 'revert', 'revert'] ==
                [next(a for a in arguments if not a.startswith('-') and
                      a not in (p4.port, p4.workspace) and not os.path.isabs(a))
                 for arguments in recorded],
                str([arguments[:6] for arguments in recorded]))
    suite.check('a safe revert asks for the unchanged files only, and leaves the file on disk',
                '-a' in recorded[2] and '-k' in recorded[2] and '-a' not in recorded[3],
                '{0} / {1}'.format(recorded[2], recorded[3]))

    open(log, 'w').close()
    p4.sync(scene, force=True)
    recorded = calls(log)
    suite.check('a forced sync gives the file back first, then takes the latest',
                'revert' in recorded[0] and 'sync' in recorded[-1] and '-f' in recorded[-1],
                str([arguments[3:6] for arguments in recorded]))

    # -- changelists -------------------------------------------------- #
    suite.check('pending changelists are read by field name, not by counting lines',
                p4.pending() == {'4011': 'rig: hero, arm fixes', '4012': 'mca: auto-submit'},
                str(p4.pending()))
    suite.check('a changelist with the description already wanted is reused rather than piled up',
                p4.create_changelist('rig: hero, arm fixes') == '4011')

    open(log, 'w').close()
    suite.check('and a new description makes a new one, without a shell pipe',
                p4.create_changelist('rig: hero, hand fixes') == '4099')
    recorded = calls(log)
    suite.check('by reading the form and handing it back on standard input',
                any('-o' in arguments for arguments in recorded) and
                any('-i' in arguments for arguments in recorded),
                str([arguments[-3:] for arguments in recorded]))

    # -- submitting --------------------------------------------------- #
    suite.check('submitting files that are not on disk is refused before anything runs',
                not p4.submit(os.path.join(workspace_root, 'not there.ma')))
    open(log, 'w').close()
    result = p4.submit(scene, 'rig: hero, arm fixes')
    suite.check('submitting a real file works', bool(result), result.message)
    recorded = calls(log)
    suite.check('and the submit names the changelist the files were put in',
                'submit' in recorded[-1] and '4011' in recorded[-1], str(recorded[-1]))

    # -- when p4 says no ---------------------------------------------- #
    os.environ['MCA_FAKE_P4_FAIL'] = 'hero rig v2'
    try:
        result = p4.checkout(scene)
        suite.check('p4 answering non-zero is a failure, carrying what p4 said',
                    not result and 'no such file' in result.message, result.message)
        suite.check('and nothing raises out of it',
                    isinstance(result, base.Result))
    finally:
        os.environ.pop('MCA_FAKE_P4_FAIL', None)

    # -- and when there is no p4 at all ------------------------------- #
    os.environ['PATH'] = os.environ['PATH'].replace(folder + os.pathsep, '')
    bare = perforce.Perforce()
    suite.check('with no p4 installed, perforce says it is not set up',
                not bare.available() and bare.info() == {})
    result = bare.checkout(scene)
    suite.check('and every operation answers a plain failure rather than running "p4 -p None"',
                not result and 'not installed' in result.message, result.message)

    suite.note('perforce on this machine', bool(perforce.shutil.which('p4')))


if __name__ == '__main__':
    sys.exit(harness.run('sourcecontrol', body))
