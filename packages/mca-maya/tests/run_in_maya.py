"""
Run one of these suites inside a Maya that is already open.

``run_tests.bat`` runs everything in ``mayapy``, which is a full Maya with no window - and that
covers all of this but one thing: a batch Maya starts a ``QGuiApplication`` of its own, Qt allows
one application object per process, so a ``QApplication`` cannot be made and a ``QWidget`` cannot
be built. Building one aborts the process outright. So the suites that make windows can only be
finished in a Maya with a window.

From Maya's script editor::

    import sys
    sys.path.insert(0, r'<this repository>/packages/mca-maya/tests')
    import run_in_maya
    run_in_maya.run('test_pyqt.py')

It puts this repository's packages ahead of whatever framework the Maya has loaded, forgets every
``mca`` module already imported so the repository's are the ones that answer, and catches the
suite's exit so Maya does not take it as its own.
"""

# python imports
import os
import sys
import traceback


#: This file is in ``<repository>/packages/mca-maya/tests``.
TESTS_FOLDER = os.path.dirname(os.path.abspath(__file__))
PACKAGES_FOLDER = os.path.dirname(os.path.dirname(TESTS_FOLDER))


def use_this_repository():
    """
    Put this repository's packages first, and forget anything ``mca`` already imported.

    A Maya that has started normally has a framework loaded from wherever it is installed. Without
    this, a suite run here would check that one.

    :return: The package folders that were put first.
    :rtype: list(str)
    """

    added = []
    for name in sorted(os.listdir(PACKAGES_FOLDER), reverse=True):
        folder = os.path.join(PACKAGES_FOLDER, name)
        if not os.path.isdir(os.path.join(folder, 'mca')):
            continue
        while folder in sys.path:
            sys.path.remove(folder)
        sys.path.insert(0, folder)
        added.append(folder)

    if TESTS_FOLDER not in sys.path:
        sys.path.insert(0, TESTS_FOLDER)

    for name in [one for one in list(sys.modules) if one == 'mca' or one.startswith('mca.')]:
        del sys.modules[name]
    sys.modules.pop('harness', None)
    return added


def run(suite_name):
    """
    Run one suite here, in this Maya.

    :param str suite_name: The file, such as ``'test_pyqt.py'``.
    :return: The suite's exit code - 0 when everything passed.
    :rtype: int
    """

    use_this_repository()
    path = os.path.join(TESTS_FOLDER, suite_name)
    if not os.path.isfile(path):
        print('There is no suite called {} in {}.'.format(suite_name, TESTS_FOLDER))
        return 1

    namespace = {'__name__': '__mca_suite__', '__file__': path}
    try:
        with open(path, encoding='utf-8') as opened:
            exec(compile(opened.read(), path, 'exec'), namespace)      # noqa: S102
    except SystemExit as exit_code:
        # The suites end with sys.exit, which would otherwise ask Maya to close.
        return int(exit_code.code or 0)
    except Exception:
        print(traceback.format_exc())
        return 1
    return 0


def run_all():
    """
    Run every suite here.

    :return: How many failed.
    :rtype: int
    """

    failed = 0
    for name in sorted(os.listdir(TESTS_FOLDER)):
        if not name.startswith('test_') or not name.endswith('.py'):
            continue
        print('=== {}'.format(name))
        if run(name):
            failed += 1
    print('{} suite(s) failed.'.format(failed) if failed else 'All suites passed.')
    return failed
