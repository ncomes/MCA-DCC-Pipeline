"""
Reading the boot configuration, and putting packages on ``sys.path``.

``mca_python_package.config`` says which packages each DCC loads::

    mca_directories:
      maya:
        depots: [mca-maya]
      mobu:
        depots: [mca-mobu]

A depot is a folder in the packages folder, and the module inside it is not always named
after it - ``mca-maya`` holds ``mca/mya``. The version this replaces handled that by building
two parallel lists and mapping ``'maya'`` to ``'mya'`` in a loop halfway down, which is why
its callers indexed one list with the other's position. One list of entries here, each
knowing its own folder and its own module name.

What was wrong, beyond the shape:

- **A config file that was passed in was ignored.** ``get_config_packages`` tested
  ``not isinstance(config_file, dict)`` and re-read the default whenever it was handed a
  path - which is what every caller handed it. ``startup_init(config_file=...)`` therefore
  did nothing at all.
- A DCC listed with no depots raised ``TypeError`` from iterating None, one line after the
  code checked for exactly that.
- ``remove_sys_packages`` read ``os.environ[MCA_COMMON_DEPEND]`` with brackets, so shutting
  down on a machine where the launcher had not set it raised ``KeyError``.
"""

# python imports
import os
import pkgutil
import sys

# mca imports
from mca.common import log
from mca.common.paths import project_paths
from mca.common.startup.configs import consts
from mca.common.textio import datafile


logger = log.MCA_LOGGER

#: The top-level key in the config file.
DIRECTORIES_KEY = 'mca_directories'

#: A depot folder whose module is not named after it. ``mca-maya`` holds ``mca/mya``, which
#: is a fact about the depot, not a rule - so it is written down rather than worked out with
#: a string operation at the point of use. A ``module:`` key in the config beats this.
DEPOT_MODULES = {
    'mca-maya': 'mya',
    'mca-mobu': 'mobu',
    'mca-ue': 'ue',
    'mca-ai': 'ai',
    'mca-common': 'common',
}

#: Reloaded wholesale when the framework restarts.
RELOAD_PREFIXES = ('mca', 'studioqt', 'studiolibrary', 'studiovendor')


class PackageEntry(object):
    """One package a DCC loads: where it is, and what it is called once imported."""

    def __init__(self, depot, path, module):
        """
        :param str depot: The folder name, for example 'mca-maya'.
        :param str path: Its full path in the packages folder.
        :param str module: The module under ``mca``, for example 'mya'.
        """

        self.depot = depot
        self.path = path
        self.module = module

    @property
    def exists(self):
        """
        :return: Whether the folder is really there.
        :rtype: bool
        """

        return bool(self.path) and os.path.isdir(self.path)

    def as_dict(self):
        """
        :return: The entry as plain data.
        :rtype: dict
        """

        return {'depot': self.depot, 'path': self.path, 'module': self.module,
                'exists': self.exists}

    def __repr__(self):
        return '<PackageEntry {} -> mca.{}>'.format(self.depot, self.module)


def read_config_file(config_file=None):
    """
    :param config_file: A path to the config, the config itself as a dict, or None to find it.
    :return: What it holds.
    :rtype: dict
    """

    if isinstance(config_file, dict):
        return config_file
    path = config_file or project_paths.get_package_python_config_path()
    if not path:
        return {}
    return datafile.read(path, default={})


def packages_for(dcc, config_file=None, packages_folder=None):
    """
    The packages a DCC loads, in the order the config lists them.

    :param str dcc: 'maya', 'mobu', 'ue', 'common'.
    :param config_file: A path, a dict, or None.
    :param str packages_folder: Where the depots are. None uses ``MCA_FRAMEWORK_PATH``.
    :return: The entries, whether or not their folders are there.
    :rtype: list(PackageEntry)
    """

    config = read_config_file(config_file)
    directories = config.get(DIRECTORIES_KEY) or {}
    if not directories:
        logger.warning('The boot config has no %s in it, so no packages can be loaded.',
                       DIRECTORIES_KEY)
        return []

    wanted = directories.get(str(dcc))
    if not wanted:
        logger.warning('The boot config says nothing about %s. It knows: %s.',
                       dcc, ', '.join(sorted(directories)) or 'nothing')
        return []

    folder = packages_folder or project_paths.get_mca_package_path()
    entries = []
    # A DCC listed with no depots is an empty list, not a crash one line after the check.
    for depot in (wanted.get('depots') or []):
        module = wanted.get('module') or DEPOT_MODULES.get(depot,
                                                           str(depot).split('-')[-1])
        path = os.path.normpath(os.path.join(folder, depot)) if folder else ''
        entries.append(PackageEntry(depot, path, module))
    return entries


def extend_namespace(name='mca'):
    """
    Let an already-imported ``mca`` see packages that were added to ``sys.path`` after it.

    This is load-bearing, and it used to happen by accident. ``mca`` is one namespace spread
    across several folders - ``mca-common`` holds ``mca/common``, ``mca-maya`` holds
    ``mca/mya`` - and ``pkgutil.extend_path`` works out where its pieces are **once**, when
    ``mca/__init__.py`` is first imported. By then only mca-common is on the path, because
    mca-common is what is doing the importing. Adding mca-maya to ``sys.path`` afterwards
    does not change a namespace that has already been worked out, so ``import mca.mya``
    fails.

    The version this replaces got away with it because ``reload_modules()`` ran just before
    the package start-ups and deleted ``mca`` from ``sys.modules``, so the next import
    rebuilt the namespace with the fuller path. That made a development convenience into
    something the boot sequence could not work without, silently - move the reload, or skip
    it, and every package but common stops loading.

    :param str name: The namespace package.
    :return: Where it now looks.
    :rtype: list(str)
    """

    module = sys.modules.get(name)
    if module is None or not hasattr(module, '__path__'):
        return []
    module.__path__ = pkgutil.extend_path(list(module.__path__), name)
    return list(module.__path__)


def create_sys_packages(config_file=None, dcc='maya', packages_folder=None, quiet=False):
    """
    Put a DCC's packages on ``sys.path``.

    :param config_file: A path, a dict, or None.
    :param str dcc: The DCC.
    :param str packages_folder: Where the depots are.
    :param bool quiet: Say nothing.
    :return: The paths that are now on the path.
    :rtype: list(str)
    """

    added = []
    for entry in packages_for(dcc, config_file, packages_folder):
        if not entry.exists:
            logger.warning('%s is in the boot config for %s, but there is no folder at %s.',
                           entry.depot, dcc, entry.path or '(no packages folder set)')
            continue
        if entry.path not in sys.path:
            sys.path.append(entry.path)
        added.append(entry.path)

    if added:
        # The paths are on sys.path; the mca namespace still has to be told.
        extend_namespace()
    if added and not quiet:
        logger.info('Ready to import: %s.', ', '.join(os.path.basename(one) for one in added))
    return added


def remove_sys_packages(config_file=None, dcc='maya', packages_folder=None, quiet=False):
    """
    Take a DCC's packages, and its dependency folder, back off ``sys.path``.

    :param config_file: A path, a dict, or None.
    :param str dcc: The DCC.
    :param str packages_folder: Where the depots are.
    :param bool quiet: Say nothing.
    :return: The paths that were removed.
    :rtype: list(str)
    """

    removed = []
    for entry in packages_for(dcc, config_file, packages_folder):
        while entry.path and entry.path in sys.path:
            sys.path.remove(entry.path)
            removed.append(entry.path)

    # .get, not [...]: shutting down on a machine where the launcher never set this used to
    # raise KeyError out of the middle of the shutdown.
    dependencies = os.getenv(consts.MCA_COMMON_DEPEND) or ''
    while dependencies and dependencies in sys.path:
        sys.path.remove(dependencies)
        removed.append(dependencies)

    if not quiet:
        if removed:
            logger.info('Unloaded: %s.', ', '.join(sorted(set(removed))))
        else:
            logger.info('Nothing to unload: none of those packages were on the path.')
    return removed


def remove_sys_path(path_list, quiet=False):
    """
    :param path_list: A path, or several.
    :param bool quiet: Say nothing.
    :return: What was removed.
    :rtype: list(str)
    """

    if isinstance(path_list, str):
        path_list = [path_list]

    removed = []
    for path in path_list or []:
        while path and path in sys.path:
            sys.path.remove(path)
            removed.append(path)
            if not quiet:
                logger.info('Off the path: %s', path)
    return removed


def reload_modules(prefixes=RELOAD_PREFIXES):
    """
    Forget every framework module, so the next import reads the files again.

    This is what makes "restart the framework" work inside a running DCC, where the
    alternative is closing Maya. It is deliberately blunt: a module is dropped from
    ``sys.modules``, not reloaded in place, because a partially reloaded package is worse
    than none.

    :param tuple prefixes: Module name prefixes to forget.
    :return: The names that were dropped.
    :rtype: list(str)
    """

    dropped = []
    for name in list(sys.modules):
        if name in prefixes or name.startswith(tuple(one + '.' for one in prefixes)):
            del sys.modules[name]
            dropped.append(name)
    return sorted(dropped)
