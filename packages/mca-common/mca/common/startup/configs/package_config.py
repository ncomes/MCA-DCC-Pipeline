"""
What a package says about itself: ``mca_package.yaml``.

Each package ships one beside its code - its name, its version, and the environment
variables it wants set, written against ``{self}``, the folder the file is in, so a package
can describe its own layout without knowing where it was installed.

This replaces ``textio/packages.py``, which could not run at all: it called
``consts.PROJECT_CONFIG_NAME``, ``consts.BASE_PATH`` and ``consts.PKG_NAME``, and none of
those three names exist - the module raised ``AttributeError`` the moment any of its
functions was called. It was also the only file in the package indented with tabs, which is
a fair sign of how much it had been run.

The manifests themselves were no better, and nothing ever said so - which is why this reads
them with :meth:`PackageManifest.problems`:

- **mca-ue's manifest sets Maya's variables.** ``MCA_MAYA_BASE_PATH``,
  ``MCA_MAYA_CONFIGS_PATH``, ``MCA_MAYA_TOOLS_PATH``, ``MCA_MAYA_PATHS`` - copied from the
  Maya one and never renamed, so loading Unreal quietly repointed Maya's paths at Unreal's
  folders.
- **mca-maya's paths point at a folder that does not exist**: ``{self}/mca.mya/configs``,
  with a dot, where the folder is ``mca/mya``.
- mca-common's listed a ``dependecies`` folder - spelled that way - which was never there.

And one behaviour: a variable whose value is a list was set by formatting the Python list
into the string, so ``MCA_COMMON_PATHS`` came out as ``"['a', 'b']"``, brackets and quotes
and all, rather than paths joined the way the platform joins paths.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.startup.configs import consts
from mca.common.textio import datafile


logger = log.MCA_LOGGER

#: What the file is called, in every package.
PACKAGE_FILE = consts.MCA_PACKAGE_FILE

#: The token a package uses to mean "the folder I am in".
SELF = '{self}'


def find_package_file(folder):
    """
    :param str folder: A package folder, or a folder inside one.
    :return: The ``mca_package.yaml`` at or above it, or ''.
    :rtype: str
    """

    current = os.path.normpath(folder or '')
    while current and os.path.isdir(current):
        candidate = os.path.join(current, PACKAGE_FILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return ''


def expand(value, root):
    """
    Put a package's own folder in place of ``{self}``.

    :param value: A string, or a list of them.
    :param str root: The package's folder.
    :return: The same shape, expanded and normalised.
    :rtype: str or list(str)
    """

    if isinstance(value, (list, tuple)):
        return [expand(one, root) for one in value]
    text = str(value if value is not None else '')
    if SELF in text:
        text = text.replace(SELF, root)
    return os.path.normpath(text) if text else ''


class PackageManifest(object):
    """One package's ``mca_package.yaml``, and the environment it asks for."""

    def __init__(self, path, values=None):
        """
        :param str path: The manifest file.
        :param dict values: Its contents, when they are already in hand.
        """

        self.path = os.path.normpath(path) if path else ''
        self.root = os.path.dirname(self.path)
        self.values = values if values is not None else datafile.read(self.path, default={})
        if not isinstance(self.values, dict):
            logger.warning('%s does not hold a package description.', self.path)
            self.values = {}

    # -- what it says about itself -------------------------------------- #
    @property
    def name(self):
        """:return: The package's name."""

        return str(self.values.get('name') or '')

    @property
    def display_name(self):
        """:return: What to call it in a window."""

        return str(self.values.get('displayName') or self.name)

    @property
    def depot_name(self):
        """:return: The short name the boot config uses, such as 'maya'."""

        return str(self.values.get('depotName') or '')

    @property
    def version(self):
        """:return: Its version."""

        return str(self.values.get('version') or '')

    @property
    def required(self):
        """:return: Whether the framework needs it."""

        return bool(self.values.get('required'))

    @property
    def urls(self):
        """
        :return: The documentation links, by name. Empty ones are dropped, so a caller can
            ask ``if urls.get('rigging')`` rather than checking for an empty string.
        :rtype: dict
        """

        urls = self.values.get('urls') or {}
        if not isinstance(urls, dict):
            return {}
        return {key: str(value) for key, value in urls.items() if str(value or '').strip()}

    # -- the environment it asks for ------------------------------------ #
    def environment(self):
        """
        The variables this package wants, expanded against its own folder.

        :return: Name to value. A list becomes paths joined with the platform's separator -
            the version this replaces formatted the Python list into the string, so the
            value arrived as ``"['a', 'b']"``.
        :rtype: dict
        """

        declared = self.values.get('environment') or {}
        if not isinstance(declared, dict):
            logger.warning('%s has an environment block that is not a mapping.', self.path)
            return {}

        built = {}
        for name, value in declared.items():
            expanded = expand(value, self.root)
            if isinstance(expanded, list):
                expanded = os.pathsep.join(one for one in expanded if one)
            built[str(name)] = expanded
        return built

    def apply(self, overwrite=True):
        """
        Put this package's variables into the environment.

        :param bool overwrite: False leaves a variable that is already set alone, which is
            what a package loaded after the launcher has spoken should do.
        :return: The names that were set.
        :rtype: list(str)
        """

        was_set = []
        for name, value in sorted(self.environment().items()):
            if not value:
                continue
            if not overwrite and os.getenv(name):
                continue
            os.environ[name] = value
            was_set.append(name)
        if was_set:
            logger.debug('%s set %s.', self.name or self.path, ', '.join(was_set))
        return was_set

    # -- whether it makes sense ----------------------------------------- #
    def problems(self):
        """
        Everything wrong with this manifest, in sentences.

        Nothing checked these before, which is how mca-ue came to set Maya's variables and
        mca-maya came to point at a folder spelled with a dot.

        :return: What is wrong. Empty is a good manifest.
        :rtype: list(str)
        """

        found = []
        if not self.values:
            return ['{} is empty or could not be read.'.format(self.path or 'No manifest')]

        for key in ('name', 'version', 'depotName'):
            if not str(self.values.get(key) or '').strip():
                found.append('{} does not say its {}.'.format(PACKAGE_FILE, key))

        for name, value in sorted(self.environment().items()):
            for one in str(value).split(os.pathsep):
                if one and not os.path.exists(one):
                    found.append('{} points at {}, which is not there.'.format(name, one))

        # A package whose variables are named for another DCC is the mca-ue mistake: copied
        # from the Maya manifest and never renamed.
        depot = self.depot_name.upper()
        if depot:
            others = [name for name in self.environment()
                      if name.startswith('MCA_') and
                      name.split('_')[1] in ('MAYA', 'MOBU', 'UE', 'UNREAL') and
                      name.split('_')[1] != depot.replace('UNREAL', 'UE')]
            for name in sorted(others):
                found.append('{} is named for another DCC, in the {} package.'
                             .format(name, self.depot_name))
        return found


def read_package(folder, apply_environment=False):
    """
    Read a package's manifest.

    :param str folder: The package folder, or anything inside it.
    :param bool apply_environment: Also set the variables it asks for.
    :return: The manifest, or None when there is no file to read.
    :rtype: PackageManifest or None
    """

    path = find_package_file(folder)
    if not path:
        logger.debug('No %s at or above %s.', PACKAGE_FILE, folder)
        return None

    manifest = PackageManifest(path)
    for problem in manifest.problems():
        logger.warning('%s: %s', os.path.basename(os.path.dirname(path)), problem)
    if apply_environment:
        manifest.apply()
    return manifest
