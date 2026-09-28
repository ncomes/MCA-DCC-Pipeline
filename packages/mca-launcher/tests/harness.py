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
        path = os.path.join(tempfile.gettempdir(), 'mca_launcher_{}.json'.format(self.name))
        try:
            with open(path, 'w', encoding='utf-8') as opened:
                json.dump(results, opened, indent=1, default=str)
        except Exception as write_error:
            print('could not write results: {}'.format(write_error))

        if error:
            print(error)
        print('')
        print('{}: {}/{} passed'.format(self.name, results['passed'], results['total']))
        for failure in self.failures:
            print('  FAILED  {}'.format(failure))
        print('  details: {}'.format(path))

        if not keep_temp:
            shutil.rmtree(self.temp, ignore_errors=True)
        else:
            print('  temp kept: {}'.format(self.temp))

        return 0 if results['ok'] else 1


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
    suite = Suite(name)
    error = None
    try:
        body(suite)
    except Exception:
        error = traceback.format_exc()
    return suite.finish(error=error, keep_temp=keep_temp)
