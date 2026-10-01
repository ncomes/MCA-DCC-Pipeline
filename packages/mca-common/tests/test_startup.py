"""
The framework's start-up, checked with no DCC and no packages but the ones the suite builds.

The point of this suite is the two things that used to go wrong silently: starting twice
really started twice, and a package failing to start took the DCC's whole start-up with it
while saying nothing about which package it was.

    python tests/test_startup.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.paths import project_paths  # noqa: E402
from mca.common.startup import startup  # noqa: E402
from mca.common.startup.configs import config, consts  # noqa: E402
from mca.common.textio import datafile, yamlio  # noqa: E402


def build_fake_packages(temp):
    """
    A packages folder with two depots in it: one that starts, and one that raises.

    :param str temp: The suite's temp folder.
    :return: (packages folder, boot config path)
    :rtype: tuple(str, str)
    """

    packages = os.path.join(temp, 'repo', 'packages')

    # mca-common itself, so the paths module finds it.
    os.makedirs(os.path.join(packages, 'mca-common', 'mca', 'common'))

    for depot, module, body in (
            ('mca-good', 'good', 'STARTED = []\n\n'
                                 'def startup_init():\n'
                                 '    STARTED.append("up")\n\n'
                                 'def shutdown():\n'
                                 '    STARTED.append("down")\n'),
            ('mca-angry', 'angry', 'def startup_init():\n'
                                   '    raise RuntimeError("this package is broken")\n'),
            ('mca-quiet', 'quiet', '')):
        folder = os.path.join(packages, depot, 'mca', module, 'startup')
        os.makedirs(folder)
        for part in (os.path.join(packages, depot, 'mca'),
                     os.path.join(packages, depot, 'mca', module), folder):
            with open(os.path.join(part, '__init__.py'), 'w', encoding='utf-8') as opened:
                if part.endswith('mca'):
                    opened.write("__path__ = __import__('pkgutil').extend_path("
                                 "__path__, __name__)\n")
        with open(os.path.join(folder, 'startup.py'), 'w', encoding='utf-8') as opened:
            opened.write(body)

    config_path = os.path.join(packages, consts.MCA_PACKAGE_BOOTS)
    datafile.write({'mca_directories': {
        'maya': {'depots': ['mca-good', 'mca-angry', 'mca-quiet'], 'module': None},
        'mobu': {'depots': []},
        'common': {'depots': ['all']},
    }}, config_path, fmt='yaml')
    return packages, config_path


def body(suite):
    temp = suite.temp
    packages, config_path = build_fake_packages(temp)

    # The depot-to-module names the suite's fake packages use.
    config.DEPOT_MODULES.update({'mca-good': 'good', 'mca-angry': 'angry',
                                 'mca-quiet': 'quiet'})

    project_root = os.path.join(temp, 'SampleGame')
    os.makedirs(project_root)
    yamlio.write_to_yaml_file(
        {consts.MCA_PROJECT_NAME: 'SampleGame',
         consts.MCA_PROJECT_ROOT: project_root,
         consts.MCA_FRAMEWORK_PATH: packages},
        project_paths.get_preferences_file('SampleGame'))
    os.environ[consts.MCA_FRAMEWORK_PATH] = packages

    # ---------------------------------------------------------------- #
    # Reading the boot config
    # ---------------------------------------------------------------- #
    entries = config.packages_for('maya', config_path, packages_folder=packages)
    suite.check('the packages for a DCC come back in the order the config lists them',
                [one.depot for one in entries] == ['mca-good', 'mca-angry', 'mca-quiet'],
                str(entries))
    suite.check('each one knows the module inside it, which is not always its own name',
                [one.module for one in entries] == ['good', 'angry', 'quiet'], str(entries))

    suite.check('a DCC listed with no depots answers nothing, rather than raising on None',
                config.packages_for('mobu', config_path, packages_folder=packages) == [])
    suite.check('a DCC the config says nothing about answers nothing and says so',
                config.packages_for('houdini', config_path, packages_folder=packages) == [])

    # The bug: a config file handed in was thrown away, because it was not a dict.
    other = os.path.join(temp, 'other.config')
    datafile.write({'mca_directories': {'maya': {'depots': ['mca-only-here']}}}, other,
                   fmt='yaml')
    suite.check('a config file that is passed in is the one that is read - the old version '
                'tested it was not a dict and re-read the default instead',
                [one.depot for one in config.packages_for('maya', other,
                                                          packages_folder=packages)] ==
                ['mca-only-here'],
                str(config.packages_for('maya', other, packages_folder=packages)))

    # ---------------------------------------------------------------- #
    # sys.path
    # ---------------------------------------------------------------- #
    before = list(sys.path)
    added = config.create_sys_packages(config_path, dcc='maya', packages_folder=packages)
    suite.check('the packages that exist go on the path', len(added) == 3, str(added))
    suite.check('and they are really on it', all(one in sys.path for one in added))

    os.environ[consts.MCA_COMMON_DEPEND] = os.path.join(temp, 'deps')
    os.makedirs(os.environ[consts.MCA_COMMON_DEPEND])
    sys.path.append(os.environ[consts.MCA_COMMON_DEPEND])
    removed = config.remove_sys_packages(config_path, dcc='maya', packages_folder=packages)
    suite.check('taking them off takes the dependency folder with them',
                os.environ[consts.MCA_COMMON_DEPEND] in removed, str(removed))
    suite.check('and the path is back as it was', sys.path == before, str(sys.path[:5]))

    # The old version read os.environ[MCA_COMMON_DEPEND] with brackets.
    os.environ.pop(consts.MCA_COMMON_DEPEND, None)
    suite.check('shutting down with no dependency folder set does not raise KeyError',
                config.remove_sys_packages(config_path, dcc='maya',
                                           packages_folder=packages) == [])

    # ---------------------------------------------------------------- #
    # Starting
    # ---------------------------------------------------------------- #
    startup.STATE.update({'loaded': False, 'project': '', 'dcc': '', 'config_file': ''})
    ok = startup.startup_init('SampleGame', 'maya', config_file=config_path, quiet=True)
    suite.check('the framework starts', ok and startup.STATE['loaded'], str(startup.STATE))

    import mca.good.startup.startup as good_startup  # noqa: E402
    suite.check('a package with a start-up runs it',
                good_startup.STARTED == ['up'], str(good_startup.STARTED))

    # The one that raises must not take the others with it, and must be named.
    suite.check('a package that raises on start-up does not stop the framework coming up',
                startup.STATE['loaded'])

    # The bug: the early return sat inside "if not quiet", so a quiet caller ran the whole
    # start-up again on an already-started framework.
    good_startup.STARTED[:] = []
    again = startup.startup_init('SampleGame', 'maya', config_file=config_path, quiet=True)
    suite.check('starting again when it is already up does nothing, even when quiet',
                again and good_startup.STARTED == [], str(good_startup.STARTED))
    suite.check('unless it is asked to',
                startup.startup_init('SampleGame', 'maya', config_file=config_path, quiet=True,
                                     force=True) and good_startup.STARTED == ['up'],
                str(good_startup.STARTED))

    ok = startup.startup_init('', 'maya', quiet=True)
    suite.check('starting with no project refuses', not ok)
    ok = startup.startup_init('SampleGame', '', quiet=True)
    suite.check('and so does starting with no DCC', not ok)

    missing_config = startup.startup_init('SampleGame', 'maya',
                                          config_file=os.path.join(temp, 'nope.config'),
                                          quiet=True, force=True)
    suite.check('a boot config that is not there is refused, rather than half a start-up',
                not missing_config)

    # ---------------------------------------------------------------- #
    # Stopping
    # ---------------------------------------------------------------- #
    startup.startup_init('SampleGame', 'maya', config_file=config_path, quiet=True, force=True)
    good_startup.STARTED[:] = []
    os.environ['MCA_SOMETHING_TEMPORARY'] = 'x'
    stopped = startup.shutdown(quiet=True)
    suite.check('shutting down runs each package\'s shutdown', stopped, str(stopped))
    suite.check('and the framework variables are cleared',
                'MCA_SOMETHING_TEMPORARY' not in os.environ)
    suite.check('but the launcher\'s roots are kept, so a restart inside a sandbox stays in '
                'the sandbox rather than reaching for the real preferences',
                consts.MCA_PREFS_ROOT in os.environ and consts.MCA_LOGS_ROOT in os.environ)
    suite.check('and it knows it is down', not startup.STATE['loaded'])
    suite.check('shutting down twice says so rather than raising',
                not startup.shutdown(quiet=True))

    # ---------------------------------------------------------------- #
    # Dependencies
    # ---------------------------------------------------------------- #
    ready, absent = startup.check_dependencies(quiet=True)
    suite.check('the dependency check reports by importing, not by counting files in a '
                'folder', isinstance(ready, bool) and isinstance(absent, list), str(absent))
    suite.check('and what it checks is what the launcher installs',
                startup.CORE_IMPORTS[:3] == ('yaml', 'numpy', 'psutil'),
                str(startup.CORE_IMPORTS))

    # ---------------------------------------------------------------- #
    # Reloading
    # ---------------------------------------------------------------- #
    import mca.common.log  # noqa: E402,F401  (something to forget)

    dropped = config.reload_modules(prefixes=('mca',))
    suite.check('reloading forgets the framework modules so the next import reads the files',
                any(name.startswith('mca') for name in dropped), str(dropped[:5]))
    suite.check('and the namespace can be extended again afterwards, which is what lets a '
                'package added to sys.path after mca was imported be found at all',
                isinstance(config.extend_namespace('mca'), list))

    suite.note('checks_written', len(suite.checks))


    # ---------------------------------------------------------------- #
    # the menu entries every DCC shares
    # ---------------------------------------------------------------- #
    from mca.common.startup import startup_menus

    # It read the manifest through textio.packages - replaced by package_config - and built its
    # package manager at module scope, so a manifest with a problem in it took a DCC's whole
    # menu down while the menu was being built.
    suite.check('the documentation pages are read when asked for, not when imported',
                isinstance(startup_menus.documentation_urls(), dict))
    # A blank url used to mean webbrowser.open(''): a browser window at whatever was there
    # before, which reads as the tool being broken rather than the page not existing.
    suite.check('a page the project has not got yet is not opened, and says so',
                startup_menus.open_documentation('rigging') is False and
                startup_menus.rigging_url_menu() is False)
    suite.check('every menu entry a DCC offers has a function behind it',
                all(hasattr(startup_menus, '{0}_url_menu'.format(page))
                    for page, _ in startup_menus.DOCUMENTATION_PAGES))
    suite.check('and opening the project folder with no project says so rather than running '
                '"explorer " plus nothing',
                startup_menus.open_project_folder() is False)

if __name__ == '__main__':
    sys.exit(harness.run('startup', body))
