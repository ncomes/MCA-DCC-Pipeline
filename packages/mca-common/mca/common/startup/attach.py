"""
Attaching to a project from outside a DCC.

A DCC the launcher started needs none of this: the launcher put that project's start-up
folder on the path, so the script that runs is already the right project's and finds its
framework from its own location.

Everything else has to answer "which project?" first - the editor, a farm job, a standalone
script, an MCP server. There are only three honest answers, and this is all three, in order:

1. what the caller says,
2. ``MCA_PROJECT_NAME``, when something has already prepared the environment,
3. the launcher's own preferences - the file it writes when the artist changes project.

Nothing here guesses, and nothing hardcodes a path. A machine with no project set up gets a
sentence saying so rather than a traceback from somewhere further in.

    from mca.common.startup import attach

    report = attach.attach()                 # the current project
    report = attach.attach('Wayward')        # a particular one
    report = attach.attach(start=True)       # and start the framework too

The one subtlety is that there can be two mca-commons: a pip-installed one - which is
probably what imported this module - and the project's own checkout. They are not
necessarily the same version. The report says when that has happened and which one is in
use, because a framework quietly running from the wrong copy is a day of confusion.
"""

# python imports
import os
import sys

# mca imports
from mca.common import log
from mca.common.paths import project_paths
from mca.common.startup.configs import config, consts
from mca.common.textio import datafile


logger = log.MCA_LOGGER


def current_project_name():
    """
    Which project the launcher has open, read from the file it writes.

    :return: The project name, or ''.
    :rtype: str
    """

    path = os.path.join(project_paths.get_preferences_root(),
                        consts.MCA_LAUNCHER_PREFS_FILE)
    values = datafile.read(path, default={})
    if not isinstance(values, dict):
        return ''
    return str(values.get(consts.CURRENT_PROJECT_KEY) or '')


def resolve_project(project=None):
    """
    :param str project: A project name, or None to work it out.
    :return: The project to use, or ''.
    :rtype: str
    """

    return (str(project or '').strip()
            or os.getenv(consts.MCA_PROJECT_NAME, '').strip()
            or current_project_name())


def framework_for(project):
    """
    :param str project: The project.
    :return: Its packages folder - the one holding mca-common - or ''.
    :rtype: str
    """

    values = project_paths.read_preferences(project)
    return str(values.get(consts.MCA_FRAMEWORK_PATH) or '').strip()


def imported_from():
    """
    :return: The folder the ``mca`` package that is already imported lives in, or ''.
    :rtype: str
    """

    module = sys.modules.get('mca')
    paths = list(getattr(module, '__path__', []) or []) if module else []
    return os.path.normpath(os.path.dirname(paths[0])) if paths else ''


def attach(project=None, dcc=consts.STANDALONE, set_environment=True, start=False,
           replace=False):
    """
    Put a project's framework on the path, and optionally start it.

    :param str project: The project. None works it out - the environment, then the
        launcher's current project.
    :param str dcc: Which DCC's packages to add as well. 'standalone' adds only mca-common.
    :param bool set_environment: Also set the project's environment variables.
    :param bool start: Also run the framework's start-up.
    :param bool replace: Forget any ``mca`` modules that are already imported, so the
        project's copy is the one that answers from here on. Off by default: dropping
        modules out from under running code is not something to do without being asked.
    :return: What happened - ``ok``, ``project``, ``framework``, ``added``, ``message``, and
        ``shadowed`` when an ``mca`` from somewhere else was already imported.
    :rtype: dict
    """

    report = {'ok': False, 'project': '', 'framework': '', 'added': [], 'shadowed': '',
              'message': ''}

    name = resolve_project(project)
    if not name:
        report['message'] = (
            'No project was given, MCA_PROJECT_NAME is not set, and the launcher has no '
            'current project in {}. Open the launcher and pick a project, or pass one.'
            .format(os.path.join(project_paths.get_preferences_root(),
                                 consts.MCA_LAUNCHER_PREFS_FILE)))
        logger.warning(report['message'])
        return report
    report['project'] = name

    framework = framework_for(name)
    if not framework:
        report['message'] = (
            'The project {} does not say where the framework is. Its preferences are at {} '
            'and they need {}.'.format(name, project_paths.get_preferences_file(name),
                                       consts.MCA_FRAMEWORK_PATH))
        logger.warning(report['message'])
        return report

    framework = os.path.normpath(framework)
    if not os.path.isdir(framework):
        report['message'] = ('The project {} points at {}, and there is no folder there.'
                             .format(name, framework))
        logger.warning(report['message'])
        return report
    report['framework'] = framework

    # An mca that is already imported from somewhere else - a pip install, another project -
    # keeps answering unless it is dropped, whatever goes on sys.path now.
    already = imported_from()
    package_root = os.path.join(framework, 'mca-common')
    if already and os.path.normcase(already) != os.path.normcase(package_root):
        report['shadowed'] = already
        if replace:
            config.reload_modules()
            logger.info('Forgot the mca modules imported from %s.', already)

    # The project's own copy goes in front, so it wins for anything imported after this.
    wanted = [package_root]
    if dcc and dcc != consts.STANDALONE:
        # This framework's boot config, named explicitly: reading "the" config would read
        # whichever framework the current environment points at, which is the one being
        # replaced.
        boot = os.path.join(framework, consts.MCA_PACKAGE_BOOTS)
        wanted.extend(entry.path for entry in
                      config.packages_for(dcc, config_file=boot, packages_folder=framework)
                      if entry.exists)

    added = []
    for path in wanted:
        if not path or not os.path.isdir(path):
            continue
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
        added.append(path)
    config.extend_namespace()
    report['added'] = added

    if set_environment:
        os.environ[consts.MCA_PROJECT_NAME] = name
        os.environ[consts.MCA_FRAMEWORK_PATH] = framework
        project_paths.ProjectEnvs(name).set_project_envs()

    report['ok'] = True
    report['message'] = 'Attached to {} at {}.'.format(name, framework)

    if start:
        from mca.common.startup import startup

        report['started'] = startup.startup_init(name, dcc if dcc else consts.STANDALONE)
        if not report['started']:
            report['message'] += ' The framework itself did not start; see the log.'

    if report['shadowed'] and not replace:
        report['message'] += (
            ' Note: an mca package imported from {} is already loaded, so modules imported '
            'before now still come from there. Pass replace=True to drop them.'
            .format(report['shadowed']))

    logger.info(report['message'])
    return report
