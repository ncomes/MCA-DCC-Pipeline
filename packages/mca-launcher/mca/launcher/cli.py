"""
The command line, and the entry point a shortcut or an agent uses.

``mca-launcher`` with no arguments opens the window. Everything else is the same set of
operations without one, which is what makes this usable from a script, a build step, or an
agent that has been asked why Maya will not start::

    mca-launcher --doctor
    mca-launcher --projects
    mca-launcher --dccs
    mca-launcher --deps maya:2025
    mca-launcher --install-deps maya:2025
    mca-launcher --launch maya:2025
    mca-launcher --launch maya --project SampleGame --json
    mca-launcher --shortcut maya:2025 --project SampleGame

``--json`` prints the response as it comes back from the API, which is the form an agent
should read. Without it, the message is printed for a person. The exit code is 0 for ok and
1 for not, so a script can branch on it.
"""

# python imports
from __future__ import annotations

import argparse
import json
import sys

# mca imports
from mca import launcher
from mca.launcher import api
from mca.launcher.core import logs


def build_parser():
    """
    :return: The argument parser.
    :rtype: argparse.ArgumentParser
    """

    parser = argparse.ArgumentParser(
        prog='mca-launcher',
        description='Start a DCC with the MCA pipeline on its path. No arguments opens the '
                    'window.')
    parser.add_argument('--version', action='store_true', help='print the launcher version')
    parser.add_argument('--doctor', action='store_true',
                        help='everything worth knowing when something is wrong')
    parser.add_argument('--projects', action='store_true', help='list the projects set up here')
    parser.add_argument('--dccs', action='store_true', help='list what is installed')
    parser.add_argument('--deps', metavar='DCC[:VERSION]',
                        help='report whether that DCC version has its dependencies')
    parser.add_argument('--install-deps', metavar='DCC[:VERSION]',
                        help='install them if they are missing')
    parser.add_argument('--reinstall-deps', metavar='DCC[:VERSION]',
                        help='install them even if they look fine')
    parser.add_argument('--launch', metavar='DCC[:VERSION]', help='start a DCC')
    parser.add_argument('--shortcut', metavar='DCC[:VERSION]',
                        help='put a desktop shortcut for it, for one project, on the desktop')
    parser.add_argument('--shortcut-folder', metavar='FOLDER',
                        help='write the shortcut here instead of on the desktop')
    parser.add_argument('--project', metavar='NAME',
                        help='which project to use; the current one by default')
    parser.add_argument('--json', action='store_true', dest='as_json',
                        help='print the whole response as JSON')
    parser.add_argument('--quiet', action='store_true', help='log warnings and worse only')
    return parser


def split_target(text):
    """
    Split ``maya:2025`` into its parts.

    :param str text: The argument.
    :return: (dcc, key) where key may be None.
    :rtype: tuple(str, str or None)
    """

    if ':' in str(text):
        name, _, key = str(text).partition(':')
        return name.strip(), key.strip() or None
    return str(text).strip(), None


def report(response, as_json):
    """
    Print a response and turn it into an exit code.

    :param dict response: A response from the API.
    :param bool as_json: Print the whole thing as JSON.
    :return: The exit code.
    :rtype: int
    """

    if as_json:
        print(json.dumps(response, indent=2, default=str))
    else:
        print(response['message'] or ('ok' if response['ok'] else 'failed'))
        result = response.get('result')
        if response['ok'] and isinstance(result, dict) and result.get('problems'):
            for problem in result['problems']:
                print('  - {}'.format(problem))
    return 0 if response['ok'] else 1


def main(argv=None):
    """
    :param list(str) argv: Arguments, or None for sys.argv.
    :return: The exit code.
    :rtype: int
    """

    parser = build_parser()
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    logs.setup(level='WARNING' if arguments.quiet else 'INFO')

    def progress(line):
        if not arguments.as_json:
            print(line)

    if arguments.version:
        print(launcher.__version__)
        return 0

    if arguments.doctor:
        return report(api.doctor(project=arguments.project), arguments.as_json)
    if arguments.projects:
        return report(api.list_projects(), arguments.as_json)
    if arguments.dccs:
        return report(api.dcc_targets(project=arguments.project), arguments.as_json)

    if arguments.deps:
        dcc, key = split_target(arguments.deps)
        return report(api.dependency_status(dcc, key, project=arguments.project),
                      arguments.as_json)
    for option, force in ((arguments.install_deps, False), (arguments.reinstall_deps, True)):
        if option:
            dcc, key = split_target(option)
            return report(api.ensure_dependencies(dcc, key, project=arguments.project,
                                                 force=force, progress=progress),
                          arguments.as_json)

    if arguments.shortcut:
        dcc, key = split_target(arguments.shortcut)
        return report(api.create_shortcut(dcc, key, project=arguments.project,
                                         folder=arguments.shortcut_folder or ''),
                      arguments.as_json)

    if arguments.launch:
        dcc, key = split_target(arguments.launch)
        return report(api.launch(dcc, key, project=arguments.project, progress=progress),
                      arguments.as_json)

    return main_gui()


def main_gui():
    """
    Open the window.

    Imported here rather than at module scope so that every command above runs on a machine
    with no display and no PySide6 - which is what a build step or an agent has.

    :return: The exit code.
    :rtype: int
    """

    from mca.launcher.ui import application
    return application.run()


if __name__ == '__main__':
    sys.exit(main())
