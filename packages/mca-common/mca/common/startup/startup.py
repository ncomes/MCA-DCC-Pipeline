"""
Starting the framework inside a DCC, and stopping it again.

    from mca.common.startup import startup

    startup.startup_init('Wayward', 'maya')
    startup.restart()
    startup.shutdown('maya')

The launcher has already done its half before this runs: it installed the Python packages
this DCC version needs, proved they import, and set the environment. This puts the framework
on ``sys.path`` and lets each package run its own start-up.

What changed on the way over:

- **Starting twice really started twice.** The guard read ``if PACKAGE_LOADED: if not
  skip_dialog: return True`` - the return was inside the message, so a caller passing
  ``skip_dialog=True`` fell through and ran the whole start-up again on an already-loaded
  framework. It returns either way now, and says so only when it is talking.
- **Packages were started by exec'ing a string.** ``exec('from mca.mya.startup import
  startup as stup; stup.startup_init()')`` - built from config data, with no idea which
  package failed when one did, and binding a name inside a function where the next line
  cannot see it. They are imported and called by name, one try each, and a package that
  raises is named and skipped rather than taking the DCC's whole start-up down with it.
- **The dependency check looked in the wrong place.** It counted files in a vendored
  ``startup/dependencies/python311`` folder and called five or more a success. That folder
  is not how dependencies work any more: the launcher installs them per DCC version and
  names the folder in ``MCA_COMMON_DEPEND``. The check asks whether the packages the
  framework cannot start without will actually import.
- ``shutdown`` imported Qt at module scope, so importing the start-up at all needed Qt -
  which a standalone or a farm job does not have.
"""

# python imports
import importlib
import os
import sys

# mca imports
from mca.common import log
from mca.common.paths import project_paths
from mca.common.startup.configs import config, consts


logger = log.MCA_LOGGER

#: What the framework cannot start without. The same list the launcher installs and proves,
#: so the two agree about what "ready" means.
CORE_IMPORTS = ('yaml', 'numpy', 'psutil', 'requests', 'pytz', 'bs4', 'anytree')

#: What has been started, so starting again is a no-op rather than a second start.
STATE = {'loaded': False, 'project': '', 'dcc': '', 'config_file': ''}


def startup_init(project_name, dcc, config_file=None, quiet=False, force=False):
    """
    Put the framework on the path for a project and a DCC.

    :param str project_name: The project, for example 'Wayward'.
    :param str dcc: 'maya', 'mobu', 'ue' or 'common'.
    :param str config_file: The boot config. None finds it under the framework path.
    :param bool quiet: Say nothing unless something is wrong.
    :param bool force: Start again even if it is already started.
    :return: Whether the framework is now up.
    :rtype: bool
    """

    if not project_name:
        logger.error('Starting the framework needs a project name.')
        return False
    if not dcc:
        logger.error('Starting the framework needs a DCC name, such as "maya".')
        return False

    if STATE['loaded'] and not force:
        if not quiet:
            logger.info('The framework is already up for %s in %s.',
                        STATE['project'], STATE['dcc'])
        return True

    if not quiet:
        logger.info('Starting the MCA framework for %s in %s.', project_name, dcc)

    # The project's own variables, from the preferences the launcher wrote. When the launcher
    # started this DCC they are already in the environment and this changes nothing; when
    # somebody opened Maya by hand, this is what sets them.
    environment = project_paths.ProjectEnvs(project_name)
    missing = environment.missing()
    if missing:
        logger.warning('The project %s is missing %s. Some tools will not find their files.',
                       project_name, ', '.join(missing))
    environment.set_project_envs()

    ready, absent = check_dependencies(quiet=quiet)
    if not ready:
        # Not fatal here: the launcher refuses to start a DCC without them, so reaching this
        # means somebody started the DCC another way. Say exactly what is missing.
        logger.warning('These packages the framework needs did not import: %s. Start this '
                       'DCC from the MCA launcher and they will be installed.',
                       ', '.join(absent))

    try:
        log.setup_file_logging(project_name=project_name, dcc_name=dcc)
    except Exception as error:                                       # noqa: BLE001
        logger.warning('Could not set up file logging: %s', error)

    config_file = config_file or project_paths.get_package_python_config_path()
    if not config_file or not os.path.isfile(str(config_file)):
        logger.error('There is no boot config at %s, so no packages can be loaded.',
                     config_file or '(nowhere - MCA_FRAMEWORK_PATH is not set)')
        return False

    config.create_sys_packages(config_file=config_file, dcc=dcc, quiet=quiet)
    run_package_startups(config_file=config_file, dcc=dcc, quiet=quiet)

    STATE.update({'loaded': True, 'project': project_name, 'dcc': dcc,
                  'config_file': config_file})
    if not quiet:
        logger.info('The MCA framework is up for %s in %s.', project_name, dcc)
    return True


def shutdown(dcc=None, config_file=None, quiet=False):
    """
    Take the framework back out of a running DCC.

    :param str dcc: The DCC. None uses whatever was started.
    :param str config_file: The boot config. None uses whatever was started with.
    :param bool quiet: Say nothing.
    :return: Whether anything was shut down.
    :rtype: bool
    """

    dcc = dcc or STATE['dcc']
    config_file = config_file or STATE['config_file']
    if not dcc:
        logger.warning('Nothing has been started, so there is nothing to shut down.')
        return False

    close_all_windows()
    run_package_startups(config_file=config_file, dcc=dcc, do_shutdown=True, quiet=quiet)
    config.remove_sys_packages(config_file=config_file, dcc=dcc, quiet=quiet)
    remove_framework_envs()
    config.reload_modules()

    STATE.update({'loaded': False, 'project': '', 'dcc': '', 'config_file': ''})
    if not quiet:
        logger.info('The MCA framework has been shut down.')
    return True


def restart(project_name=None, dcc=None, config_file=None, quiet=False):
    """
    Shut down and start again, which is how a change to the framework is picked up without
    closing the DCC.

    :param str project_name: The project. None uses what was started.
    :param str dcc: The DCC. None uses what was started.
    :param str config_file: The boot config. None uses what was started with.
    :param bool quiet: Say nothing.
    :return: Whether it came back up.
    :rtype: bool
    """

    project_name = project_name or STATE['project']
    dcc = dcc or STATE['dcc']
    config_file = config_file or STATE['config_file']

    if not project_name or not dcc:
        logger.error('Cannot restart: nothing has been started yet, and no project and DCC '
                     'were given.')
        return False

    if STATE['loaded']:
        shutdown(dcc=dcc, config_file=config_file, quiet=quiet)
    return startup_init(project_name, dcc, config_file=config_file, quiet=quiet, force=True)


def run_package_startups(config_file=None, dcc='maya', do_shutdown=False, quiet=False):
    """
    Let each package start itself, or stop itself.

    :param config_file: The boot config.
    :param str dcc: The DCC.
    :param bool do_shutdown: Call ``shutdown`` rather than ``startup_init``.
    :param bool quiet: Say nothing.
    :return: The packages that ran, by module name.
    :rtype: list(str)
    """

    wanted = 'shutdown' if do_shutdown else 'startup_init'
    ran = []

    for entry in config.packages_for(dcc, config_file):
        if entry.module in ('common', ''):
            # mca-common is what is running this.
            continue
        if not entry.exists:
            continue

        name = 'mca.{}.startup.startup'.format(entry.module)
        try:
            module = importlib.import_module(name)
        except ImportError as error:
            # A package listed in the config with no start-up of its own is normal.
            logger.debug('%s has no start-up module (%s).', entry.depot, error)
            continue

        function = getattr(module, wanted, None)
        if not callable(function):
            logger.debug('%s has no %s().', name, wanted)
            continue

        try:
            function()
            ran.append(entry.module)
            if not quiet:
                logger.info('%s %s.', entry.depot, 'shut down' if do_shutdown else 'started')
        except Exception as error:                                   # noqa: BLE001
            # One package failing must not take the DCC's whole start-up with it - and the
            # exec'd string this replaces could not even say which package it was.
            logger.exception('%s.%s() failed: %s', name, wanted, error)

    return ran


def check_dependencies(quiet=False):
    """
    Are the packages the framework needs actually importable here.

    The launcher installs them per DCC version and names the folder in ``MCA_COMMON_DEPEND``.
    The question worth asking is not whether that folder has files in it - the version this
    replaces counted them and called five a success - but whether the imports work.

    :param bool quiet: Say nothing.
    :return: (everything imported, the ones that did not)
    :rtype: tuple(bool, list(str))
    """

    folder = os.getenv(consts.MCA_COMMON_DEPEND) or ''
    if folder and os.path.isdir(folder) and folder not in sys.path:
        sys.path.append(folder)
        if not quiet:
            logger.info('Dependencies: %s', folder)
    elif not folder and not quiet:
        logger.debug('%s is not set; the DCC\'s own packages are all there is.',
                     consts.MCA_COMMON_DEPEND)

    absent = []
    for name in CORE_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as error:                                   # noqa: BLE001
            absent.append('{} ({})'.format(name, type(error).__name__))
    return (not absent), absent


def close_all_windows():
    """
    Close the framework's windows, when there are windows to close.

    Imported here rather than at the top: the version this replaces imported Qt at module
    scope, so importing the start-up at all needed Qt, which a standalone script or a farm
    job does not have.

    :return: Whether anything was closed.
    :rtype: bool
    """

    try:
        from mca.common.pyqt.qt_utils import windows
    except Exception as error:                                       # noqa: BLE001
        logger.debug('No Qt here, so there are no windows to close (%s).', error)
        return False

    try:
        windows.close_all_mca_windows()
        return True
    except Exception as error:                                       # noqa: BLE001
        logger.warning('Could not close the framework windows: %s', error)
        return False


def remove_framework_envs(keep=(consts.MCA_PREFS_ROOT, consts.MCA_LOGS_ROOT,
                                consts.MCA_LOGGING_LEVEL)):
    """
    Clear the framework's environment variables.

    :param tuple keep: Names to leave alone. The roots are kept by default: they are the
        launcher's, not the framework's, and dropping them on shutdown would send a
        restarted framework back to the real preferences folder from inside a first-run
        sandbox or a test.
    :return: The names that were removed.
    :rtype: list(str)
    """

    removed = []
    for name in sorted(os.environ):
        if name.startswith('MCA_') and name not in keep:
            del os.environ[name]
            removed.append(name)
    return removed
