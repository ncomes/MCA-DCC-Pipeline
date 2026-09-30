"""
The small amount of machinery the suites share.

Deliberately not pytest. These suites run under whatever Python is to hand - a DCC's
interpreter, a system python, a build step - and adding a dependency to the thing that
checks the dependency installer would be a poor joke. Each suite prints a line per check,
writes its results as JSON beside the temp folder, and exits non-zero when anything failed.
"""

# python imports
import json
import os
import shutil
import sys
import tempfile
import traceback


#: The dependency root as it was before any suite redirected it. The launcher installs
#: each DCC's third-party packages there, and a bare ``mayapy`` needs them on sys.path to
#: get as far as reading a yaml file.
_INSTALLED_DEPENDENCIES_ROOT = os.getenv('MCA_DEPS_ROOT') or os.path.join(
    os.getenv('LOCALAPPDATA') or os.path.expanduser('~/.local/share'), 'MCA', 'deps')


class Suite(object):
    """One test suite: a name, a count, and a list of what failed."""

    def __init__(self, name):
        self.name = name
        self.checks = []
        self.failures = []
        self.notes = {}
        self.temp = tempfile.mkdtemp(prefix='mca-{}-'.format(name))

        # Everything the launcher writes goes under the temp folder, so a test run cannot
        # touch the machine's real preferences or its installed dependencies.
        os.environ['MCA_PREFS_ROOT'] = os.path.join(self.temp, 'prefs')
        os.environ['MCA_DEPS_ROOT'] = os.path.join(self.temp, 'deps')
        os.environ['MCA_LOGS_ROOT'] = os.path.join(self.temp, 'logs')

    # -- checking ------------------------------------------------------- #
    def check(self, label, condition, detail=''):
        """
        :param str label: What is being checked, as a sentence.
        :param condition: Truthy passes.
        :param detail: Printed when it fails.
        :return: Whether it passed.
        :rtype: bool
        """

        passed = bool(condition)
        self.checks.append(label)
        if not passed:
            self.failures.append('{}  |  {}'.format(label, detail))
        print('{}  {}'.format('ok  ' if passed else 'FAIL', label))
        if not passed and detail:
            print('      {}'.format(detail))
        return passed

    def raises(self, label, function, *args, **kwargs):
        """
        Check that something refuses, rather than doing the wrong thing quietly.

        :param str label: What is being checked.
        :param function: What to call.
        :return: The exception's message, or ''.
        :rtype: str
        """

        try:
            function(*args, **kwargs)
        except Exception as error:
            self.check(label, True)
            return str(error)
        self.check(label, False, 'it did not raise')
        return ''

    def note(self, key, value):
        """
        :param str key: A name for a measurement worth keeping in the results file.
        :param value: The measurement.
        """

        self.notes[key] = value

    # -- finishing ------------------------------------------------------ #
    def finish(self, error=None, keep_temp=False):
        """
        Write the results, say how it went, and give back an exit code.

        :param str error: A traceback, when the suite itself blew up.
        :param bool keep_temp: Leave the temp folder for inspection.
        :return: The exit code.
        :rtype: int
        """

        results = {
            'suite': self.name,
            'total': len(self.checks),
            'passed': len(self.checks) - len(self.failures),
            'failures': self.failures,
            'notes': self.notes,
            'error': error,
            'ok': not self.failures and not error,
        }
        path = os.path.join(tempfile.gettempdir(),
                        'mca_{}_{}.json'.format(package_name(), self.name))
        try:
            with open(path, 'w', encoding='utf-8') as opened:
                json.dump(results, opened, indent=1, default=str)
        except Exception as write_error:
            print('could not write results: {}'.format(write_error))

        if error:
            print(error)
        print('')
        print('{}: {}/{} passed{}'.format(self.name, results['passed'], results['total'],
                                          ' - AND THEN THE SUITE ITSELF BLEW UP' if error else ''))
        for failure in self.failures:
            print('  FAILED  {}'.format(failure))
        print('  details: {}'.format(path))

        if not keep_temp:
            shutil.rmtree(self.temp, ignore_errors=True)
        else:
            print('  temp kept: {}'.format(self.temp))

        return 0 if results['ok'] else 1


def package_name():
    """
    :return: Which package these suites belong to, worked out from where they are - so the
        results file of one does not overwrite the other's.
    :rtype: str
    """

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.basename(root).replace('-', '_') or 'mca'


def add_package_to_path():
    """
    Put the package on sys.path, worked out from this file.

    :return: The package root that was added.
    :rtype: str
    """

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def run(name, body, keep_temp=False):
    """
    Run a suite's body with the boilerplate around it.

    :param str name: The suite name.
    :param callable body: Called with the Suite.
    :param bool keep_temp: Leave the temp folder behind.
    :return: The exit code.
    :rtype: int
    """

    add_package_to_path()
    add_sibling_packages()
    add_installed_dependencies()
    suite = Suite(name)
    error = None
    try:
        body(suite)
    except Exception:
        error = traceback.format_exc()
    return suite.finish(error=error, keep_temp=keep_temp)


# --------------------------------------------------------------------------------------- #
# Maya
# --------------------------------------------------------------------------------------- #
# These suites need a real Maya. Nothing here fakes one: a stub that answers the way we
# expect is a test of our expectations, and the whole point of this package is the part
# where Maya does not behave the way we expect. So a suite either gets Maya or says it is
# skipping, the same way mca-common's drawing suites treat PySide.
#
# The usual way to run them is Maya's own interpreter:
#
#     tests\run_tests.bat "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
#
# which is a full Maya with no window - it opens scenes, builds nodes, evaluates
# deformers, and exits. It can also be run from inside a running Maya, where it uses the
# session that is already up.

def add_sibling_packages():
    """
    Put the other packages in this repository on sys.path, ahead of anything else.

    ``mca.mya`` imports ``mca.common``, and the machine running these suites very likely
    has another copy of ``mca-common`` installed - the one the studio's DCCs load. These
    suites are here to check *this* repository, so its packages go in at position zero.

    :return: The package folders that were added.
    :rtype: list(str)
    """

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    packages_root = os.path.dirname(here)
    added = []
    for name in sorted(os.listdir(packages_root)):
        folder = os.path.join(packages_root, name)
        if not os.path.isdir(folder) or not os.path.isdir(os.path.join(folder, 'mca')):
            continue
        if folder in sys.path:
            sys.path.remove(folder)
        sys.path.insert(0, folder)
        added.append(folder)
    return added


#: Set when :func:`maya_available` has answered once, so repeated calls are cheap.
_MAYA_STATE = None


def maya_available(quiet=False):
    """
    Get a Maya that a suite can build nodes in, starting one if this is ``mayapy``.

    :param bool quiet: Do not print the skip notice.
    :return: Whether Maya is usable.
    :rtype: bool
    """

    global _MAYA_STATE
    if _MAYA_STATE is not None:
        return _MAYA_STATE

    # A running Maya's own userSetup.py would load whichever framework that machine has
    # installed, which is exactly the code these suites are here to replace. The suites put
    # this repository on sys.path themselves.
    os.environ.setdefault('MAYA_SKIP_USERSETUP_PY', '1')

    try:
        import maya.cmds as cmds
    except ImportError:
        _MAYA_STATE = False
        if not quiet:
            print('SKIP  no Maya - run this with mayapy, or from inside Maya')
        return False

    try:
        # about() answers in a running Maya and raises in a bare mayapy, which is the
        # cheapest way to tell which one we are in.
        cmds.about(version=True)
    except Exception:
        try:
            import maya.standalone
            maya.standalone.initialize(name='python')
            import maya.cmds as cmds
            cmds.about(version=True)
        except Exception as error:
            _MAYA_STATE = False
            if not quiet:
                print('SKIP  Maya would not start: {}'.format(error))
            return False

    _MAYA_STATE = True
    return True


def maya_version():
    """
    :return: The Maya version as an int, or 0 without Maya.
    :rtype: int
    """

    if not maya_available(quiet=True):
        return 0
    import maya.cmds as cmds
    try:
        return int(cmds.about(apiVersion=True) / 10000)
    except Exception:
        return 0


def add_installed_dependencies(dcc='maya'):
    """
    Put the launcher's installed dependencies for this DCC on sys.path.

    ``mayapy`` ships no PyYAML, and ``mca-common`` reads its data files with it, so without
    this a suite run in a bare ``mayapy`` fails at the first import rather than at a check.
    The launcher installs one folder per DCC version - this finds the one matching the Maya
    that is running, and quietly does nothing when there is none, so the suite goes on to
    say what is actually missing.

    :param str dcc: The DCC's short name, as the launcher spells its folders.
    :return: The folder that was added, or ''.
    :rtype: str
    """

    version = maya_version() if dcc == 'maya' else 0
    if not version:
        return ''
    folder = os.path.join(_INSTALLED_DEPENDENCIES_ROOT, '{}-{}'.format(dcc, version))
    if not os.path.isdir(folder):
        return ''
    if folder not in sys.path:
        sys.path.append(folder)
    return folder


def new_scene():
    """
    Start from an empty scene.

    Every suite calls this first, and again between scenarios that must not see each
    other's nodes. It is also what keeps a suite run out of the way when someone runs it
    from inside a Maya they were working in - which they should not, but do.
    """

    import maya.cmds as cmds
    cmds.file(new=True, force=True)


def run_in_maya(name, body, keep_temp=False):
    """
    Run a suite that needs Maya, skipping cleanly when there is none.

    :param str name: The suite name.
    :param callable body: Called with the Suite, in an empty scene.
    :param bool keep_temp: Leave the temp folder behind.
    :return: The exit code. Zero when skipped - a machine without Maya is not a failure.
    :rtype: int
    """

    add_package_to_path()
    add_sibling_packages()
    if not maya_available():
        print('{}: skipped - no Maya'.format(name))
        return 0

    add_installed_dependencies()
    new_scene()
    suite = Suite(name)
    error = None
    try:
        body(suite)
    except Exception:
        error = traceback.format_exc()
    code = suite.finish(error=error, keep_temp=keep_temp)
    try:
        new_scene()
    except Exception:
        pass
    return code
