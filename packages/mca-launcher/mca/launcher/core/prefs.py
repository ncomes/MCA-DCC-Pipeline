"""
Preferences: what the artist set up, and what they picked last time.

Three files, all under ``Documents/mca_preferences`` (or ``MCA_PREFS_ROOT``)::

    mca_launcher.pref                 which project was open last
    <project>/mca_project.prefs       the project's paths - the ones the DCC needs
    <project>/mca_launcher.pref       what was picked for that project last time

The file names and the project file's keys are kept exactly as the old launcher wrote them,
so an artist who already has a project set up does not set it up again. What changed is
inside the launcher file:

**Selections are stored by name, not by combo box index.** The old file held
``maya_version: 2`` - the *position* in a dropdown. Install a new Maya, or uninstall an old
one, and the same number means a different version; remove a project and the global
``project: 1`` points at somebody else's. Names cannot drift. An old index is read and
thrown away rather than trusted, and the newest installed version is offered instead.
"""

# python imports
from __future__ import annotations

import logging
import os
from datetime import datetime

# mca imports
from mca.launcher.core import fileio, platform_paths


logger = logging.getLogger('mca-launcher')

#: The project's own paths. Same name and same keys as the old launcher.
PROJECT_PREFS_FILE = 'mca_project.prefs'

#: What was picked last time, per project, and which project globally.
LAUNCHER_PREFS_FILE = 'mca_launcher.pref'

#: Bumped when the launcher file's shape changes.
SELECTION_VERSION = 2

#: The project paths, as the DCC environment names them. The value is the default.
PROJECT_KEYS = {
    'MCA_PROJECT_NAME': '',
    'MCA_PROJECT_ROOT': '',
    'MCA_FRAMEWORK_PATH': '',
    'MCA_ART_PATH': '',
    'MCA_CHARACTERS_PATH': '',
    'MCA_PROPS_PATH': '',
    'MCA_WEAPONS_PATH': '',
    'MCA_GEAR_PATH': '',
    'MCA_ENVIRONMENT_PATH': '',
    'MCA_VEHICLE_PATH': '',
    'MCA_COMMON_TOOLS': '',
}

#: The art folders, in the order a setup window should show them, and the folder name each
#: one defaults to under the art path.
ART_DEFAULTS = (
    ('MCA_CHARACTERS_PATH', 'Characters'),
    ('MCA_PROPS_PATH', 'Props'),
    ('MCA_WEAPONS_PATH', 'Weapons'),
    ('MCA_GEAR_PATH', 'Gear'),
    ('MCA_ENVIRONMENT_PATH', 'Environments'),
    ('MCA_VEHICLE_PATH', 'Vehicles'),
)


# ---------------------------------------------------------------------------- #
# Where the files are
# ---------------------------------------------------------------------------- #
def project_folder(project_name, create=False):
    """
    :param str project_name: The project.
    :param bool create: Make the folder if it is not there.
    :return: That project's preferences folder.
    :rtype: str
    """

    folder = os.path.join(platform_paths.preferences_folder(), str(project_name))
    if create and not os.path.isdir(folder):
        os.makedirs(folder)
    return os.path.normpath(folder)


def project_prefs_file(project_name, create=False):
    """
    :param str project_name: The project.
    :param bool create: Make the folder if it is not there.
    :return: That project's paths file.
    :rtype: str
    """

    return os.path.join(project_folder(project_name, create=create), PROJECT_PREFS_FILE)


def launcher_prefs_file(project_name=None, create=False):
    """
    :param str project_name: The project, or None for the global file.
    :param bool create: Make the folder if it is not there.
    :return: The launcher selection file.
    :rtype: str
    """

    if project_name is None:
        folder = platform_paths.preferences_folder()
        if create and not os.path.isdir(folder):
            os.makedirs(folder)
        return os.path.join(os.path.normpath(folder), LAUNCHER_PREFS_FILE)
    return os.path.join(project_folder(project_name, create=create), LAUNCHER_PREFS_FILE)


def project_names():
    """
    Every project that has been set up on this machine.

    A folder counts as a project when it holds a project preferences file - not when its
    name happens to have no dot in it, which is what the old check tested.

    :return: The project names, alphabetically.
    :rtype: list(str)
    """

    folder = platform_paths.preferences_folder()
    if not os.path.isdir(folder):
        return []

    found = []
    for name in sorted(os.listdir(folder)):
        if os.path.isfile(os.path.join(folder, name, PROJECT_PREFS_FILE)):
            found.append(name)
    return found


# ---------------------------------------------------------------------------- #
# A project's paths
# ---------------------------------------------------------------------------- #
class ProjectPrefs(object):
    """
    A project's paths: where the code is, where the art is, what the project is called.

    Backed by the same dictionary the file holds, keyed by the environment variable names
    the DCC will be given. Keeping those as the keys means the file is readable next to the
    environment it produces, and that the old files load unchanged.
    """

    def __init__(self, values=None):
        self.values = dict(PROJECT_KEYS)
        self.values.update(values or {})

    # -- the ones with meaning of their own ---------------------------- #
    @property
    def project_name(self):
        return str(self.values.get('MCA_PROJECT_NAME') or '')

    @project_name.setter
    def project_name(self, value):
        self.values['MCA_PROJECT_NAME'] = str(value or '').strip()

    @property
    def project_root(self):
        return str(self.values.get('MCA_PROJECT_ROOT') or '')

    @project_root.setter
    def project_root(self, value):
        self.values['MCA_PROJECT_ROOT'] = _clean(value)

    @property
    def framework_path(self):
        """The packages folder - the one holding mca-common, mca-maya and the rest."""

        return str(self.values.get('MCA_FRAMEWORK_PATH') or '')

    @framework_path.setter
    def framework_path(self, value):
        self.values['MCA_FRAMEWORK_PATH'] = _clean(value)

    @property
    def art_path(self):
        return str(self.values.get('MCA_ART_PATH') or '')

    @art_path.setter
    def art_path(self, value):
        self.values['MCA_ART_PATH'] = _clean(value)

    # -- files ---------------------------------------------------------- #
    @classmethod
    def load(cls, project_name):
        """
        :param str project_name: The project.
        :return: Its preferences. Empty ones when the file is not there.
        :rtype: ProjectPrefs
        """

        data = fileio.read_yaml(project_prefs_file(project_name), default={})
        if not isinstance(data, dict):
            logger.warning('%s did not hold a mapping; ignoring it.',
                           project_prefs_file(project_name))
            data = {}
        prefs = cls(data)
        if not prefs.project_name:
            prefs.project_name = project_name
        return prefs

    def save(self):
        """
        Write the file.

        :return: The path written, or None.
        :rtype: str or None
        """

        if not self.project_name:
            raise ValueError('A project needs a name before its preferences can be saved.')

        now = datetime.now().isoformat(timespec='seconds')
        self.values.setdefault('_created', now)
        self.values['_last_modified'] = now
        return fileio.write_yaml(self.values, project_prefs_file(self.project_name,
                                                                create=True))

    # -- what the DCC is given ------------------------------------------ #
    def environment_values(self):
        """
        The project's own contribution to a DCC's environment.

        :return: Environment variable names and values, with nothing empty in it - an empty
            variable reads as "set to nothing", which is worse than absent.
        :rtype: dict
        """

        return {key: str(value) for key, value in self.values.items()
                if key in PROJECT_KEYS and str(value or '').strip()}

    def missing(self):
        """
        :return: The keys a project cannot work without and does not have.
        :rtype: list(str)
        """

        return [key for key in ('MCA_PROJECT_NAME', 'MCA_PROJECT_ROOT', 'MCA_FRAMEWORK_PATH')
                if not str(self.values.get(key) or '').strip()]


# ---------------------------------------------------------------------------- #
# What was picked last time
# ---------------------------------------------------------------------------- #
class Selections(object):
    """
    Which DCC version was last used, and the Unreal projects that have been added.

    Per project, and keyed by name. The old file stored dropdown indices; see the module
    docstring for why that had to change.
    """

    def __init__(self, values=None):
        self.values = {'version': SELECTION_VERSION, 'dccs': {}, 'unreal_projects': [],
                       'last_browse': ''}
        self.values.update(_migrate_selections(values or {}))

    @property
    def dccs(self):
        """:return: ``{'maya': '2025', 'mobu': '2024'}`` - what was picked, by name."""

        chosen = self.values.get('dccs')
        return dict(chosen) if isinstance(chosen, dict) else {}

    def chosen(self, dcc_name, available=None):
        """
        What to select for a DCC now.

        :param str dcc_name: The DCC.
        :param list(str) available: What is installed, newest first.
        :return: The remembered choice when it is still installed, otherwise the newest
            installed, otherwise ''.
        :rtype: str
        """

        remembered = self.dccs.get(dcc_name, '')
        if available is None:
            return remembered
        if remembered and remembered in available:
            return remembered
        return available[0] if available else ''

    def choose(self, dcc_name, key):
        """
        :param str dcc_name: The DCC.
        :param str key: The version chosen.
        """

        chosen = self.dccs
        chosen[str(dcc_name)] = str(key)
        self.values['dccs'] = chosen

    @property
    def unreal_projects(self):
        """:return: The .uproject paths that have been added."""

        paths = self.values.get('unreal_projects')
        return [str(one) for one in paths] if isinstance(paths, list) else []

    def add_unreal_project(self, path):
        """
        :param str path: A .uproject path.
        :return: Whether it was new.
        :rtype: bool
        """

        cleaned = _clean(path)
        paths = self.unreal_projects
        if cleaned in paths:
            return False
        paths.append(cleaned)
        self.values['unreal_projects'] = paths
        return True

    def remove_unreal_project(self, path):
        """
        :param str path: A .uproject path.
        :return: Whether it was there.
        :rtype: bool
        """

        cleaned = _clean(path)
        paths = self.unreal_projects
        remaining = [one for one in paths if os.path.normcase(one) != os.path.normcase(cleaned)]
        self.values['unreal_projects'] = remaining
        return len(remaining) != len(paths)

    @property
    def last_browse(self):
        return str(self.values.get('last_browse') or '')

    @last_browse.setter
    def last_browse(self, value):
        self.values['last_browse'] = _clean(value)

    @classmethod
    def load(cls, project_name):
        """
        :param str project_name: The project.
        :return: Its selections.
        :rtype: Selections
        """

        return cls(fileio.read_yaml(launcher_prefs_file(project_name), default={}))

    def save(self, project_name):
        """
        :param str project_name: The project.
        :return: The path written, or None.
        :rtype: str or None
        """

        self.values['version'] = SELECTION_VERSION
        return fileio.write_yaml(self.values, launcher_prefs_file(project_name, create=True))


class GlobalSelections(object):
    """Which project was open last. One file, beside the project folders."""

    def __init__(self, values=None):
        self.values = {'version': SELECTION_VERSION, 'project_name': ''}
        data = dict(values or {})
        # The old file stored an index in 'project' beside the name. The name is the part
        # worth keeping.
        if 'project' in data:
            data.pop('project', None)
        self.values.update({key: value for key, value in data.items()
                            if key in self.values})

    @property
    def project_name(self):
        return str(self.values.get('project_name') or '')

    @project_name.setter
    def project_name(self, value):
        self.values['project_name'] = str(value or '').strip()

    def current(self, available=None):
        """
        :param list(str) available: The projects that exist.
        :return: The remembered project when it still exists, otherwise the first one,
            otherwise ''.
        :rtype: str
        """

        if available is None:
            return self.project_name
        if self.project_name and self.project_name in available:
            return self.project_name
        return available[0] if available else ''

    @classmethod
    def load(cls):
        """
        :return: The global selections.
        :rtype: GlobalSelections
        """

        return cls(fileio.read_yaml(launcher_prefs_file(None), default={}))

    def save(self):
        """
        :return: The path written, or None.
        :rtype: str or None
        """

        self.values['version'] = SELECTION_VERSION
        return fileio.write_yaml(self.values, launcher_prefs_file(None, create=True))


# ---------------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------------- #
def _clean(value):
    """
    :param value: A path, possibly with stray spaces or the wrong slashes.
    :return: It, normalised. Empty in, empty out.
    :rtype: str
    """

    text = str(value or '').strip()
    return os.path.normpath(text) if text else ''


def _migrate_selections(data):
    """
    Read an old launcher file without believing the parts that cannot be trusted.

    ``maya_version: 2`` meant "the third item in a dropdown", which depends on what was
    installed the day it was written. It is dropped: the launcher then offers the newest
    installed version, which is both a sensible default and honest about not knowing.
    ``unreal_paths`` and ``unreal_saved_path`` are real values and are kept.

    :param dict data: Whatever the file held.
    :return: The parts worth keeping, in the current shape.
    :rtype: dict
    """

    if not isinstance(data, dict):
        return {}
    if data.get('version') == SELECTION_VERSION:
        return {key: data[key] for key in ('dccs', 'unreal_projects', 'last_browse')
                if key in data}

    kept = {}
    if isinstance(data.get('unreal_paths'), list):
        kept['unreal_projects'] = [str(one) for one in data['unreal_paths']]
    if isinstance(data.get('unreal_projects'), list):
        kept['unreal_projects'] = [str(one) for one in data['unreal_projects']]
    if data.get('unreal_saved_path'):
        kept['last_browse'] = str(data['unreal_saved_path'])

    dropped = [key for key in ('maya_version', 'mobu_version', 'unreal_version')
               if isinstance(data.get(key), int)]
    if dropped:
        logger.info('Old launcher preferences stored dropdown positions (%s). They cannot '
                    'be mapped to versions, so the newest installed version will be '
                    'offered instead.', ', '.join(dropped))
    return kept
