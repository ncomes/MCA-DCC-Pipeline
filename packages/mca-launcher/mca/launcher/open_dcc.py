"""
What a desktop shortcut starts: one DCC, one project, no window - usually.

    pythonw open_dcc.py maya:2025 --project Wayward

Run directly by a ``.lnk``, so it puts the package on ``sys.path`` itself: a shortcut cannot
set an environment variable, and a script started by its own path has only its own folder
there.

"No window" has one exception, and it is the important one. The dependency check cannot be
skipped - ``api.launch`` does it, and refuses when the packages are not ready - so the first
time a shortcut is used on a machine that has never had that version set up, there are
minutes of pip ahead. Silence for minutes is indistinguishable from a broken shortcut, so
that case opens the progress window and then starts the DCC. When the packages are already
there, which is every other time, nothing is drawn at all: it checks a stamp and launches.

A failure always says so somewhere a person will see it - there is no console behind a
shortcut to print into.
"""

# python imports
import os
import sys


def _add_package_to_path():
    """Put the folder holding ``mca`` on the path, wherever this file is."""

    # mca/launcher/open_dcc.py -> launcher -> mca -> the folder holding mca
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, os.pardir, os.pardir))
    if root not in sys.path:
        sys.path.insert(0, root)


_add_package_to_path()

from mca.launcher import api                                             # noqa: E402
from mca.launcher.cli import split_target                                # noqa: E402
from mca.launcher.core import logs                                       # noqa: E402


def complain(title, message):
    """
    Say something went wrong, in whatever way this machine can.

    :param str title: The window title.
    :param str message: What happened.
    """

    print(message)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(message), 'MCA {}'.format(title), 0x10)
    except Exception:
        # No Windows, or no display. The log has it either way.
        pass


def main(argv=None):
    """
    :param list(str) argv: ``['maya:2025', '--project', 'Wayward']``, or None for sys.argv.
    :return: The exit code.
    :rtype: int
    """

    arguments = list(sys.argv[1:] if argv is None else argv)
    logs.setup(level='INFO')

    project = None
    if '--project' in arguments:
        index = arguments.index('--project')
        if index + 1 < len(arguments):
            project = arguments[index + 1]
        del arguments[index:index + 2]

    target = arguments[0] if arguments else ''
    if not target:
        complain('Shortcut', 'This shortcut does not say which DCC to start. Make it again '
                             'from the launcher.')
        return 1

    dcc, key = split_target(target)

    state = api.dependency_status(dcc, key, project=project)
    ready = state['ok'] and state['result'].get('satisfied')
    if ready:
        response = api.launch(dcc, key, project=project)
        if not response['ok']:
            complain('Launch', response['message'])
        return 0 if response['ok'] else 1

    return _launch_with_a_window(dcc, key, project)


def _launch_with_a_window(dcc, key, project):
    """
    The first-time path: show what is happening, because it takes minutes.

    :param str dcc: The DCC name.
    :param str key: The version, or an Unreal project.
    :param str project: The project name, or None.
    :return: The exit code.
    :rtype: int
    """

    try:
        from PySide6.QtWidgets import QApplication
        from mca.launcher.ui import dialogs, style
    except Exception as error:
        # No Qt: do it anyway rather than refusing. It is quiet, but it works.
        response = api.launch(dcc, key, project=project)
        if not response['ok']:
            complain('Launch', '{}\n\n(There is no PySide6 here, so this ran without a '
                               'window: {})'.format(response['message'], error))
        return 0 if response['ok'] else 1

    application = QApplication.instance() or QApplication([])
    window = dialogs.ProgressWindow(
        'Installing Dependencies',
        'Setting {} {} up for the first time. This installs the Python packages the pipeline '
        'needs, with {}\'s own interpreter, and only happens once per version.'
        .format(dcc, key or '', dcc))
    style.apply(window)
    response = window.run(
        lambda progress: api.launch(dcc, key, project=project, progress=progress))

    if not response or not response['ok']:
        dialogs.complain('{} was not started'.format(dcc),
                         (response or {}).get('message', 'Nothing came back.'), None)
        return 1
    application.processEvents()
    return 0


if __name__ == '__main__':
    sys.exit(main())
