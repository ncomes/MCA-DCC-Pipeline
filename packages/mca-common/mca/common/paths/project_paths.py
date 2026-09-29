"""
Where a project's things are.

Every answer is a function call. The version this replaces also kept three module-level
snapshots - ``ROOT_PATH``, ``MCA_PROJECT_ROOT``, ``MCA_UNREAL_ROOT`` - taken from the
environment *at import time*. Inside a DCC that is the moment the framework first loads, so
switching project, or the launcher setting a variable a moment later, left them pointing at
the old project for the rest of the session while ``get_project_path()`` answered correctly.
Two truths, one of them stale, and the one that was used depended on which line a tool
happened to call.

They are gone. Nothing here caches: reading an environment variable costs nothing, and being
right costs nothing either.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.startup.configs import consts
from mca.common.textio import yamlio
from mca.common.utils import platforms


logger = log.MCA_LOGGER


# ---------------------------------------------------------------------------- #
# The machine
# ---------------------------------------------------------------------------- #
def get_documents_folder(absolute=True):
    """
    :param bool absolute: Kept for the callers that pass it; the answer is absolute either
        way, because a relative Documents folder is not a thing.
    :return: The user's Documents folder, asked of Windows rather than guessed.
    :rtype: str
    """

    return platforms.documents_folder()


def get_preferences_root():
    """
    The folder holding one subfolder of preferences per project.

    ``MCA_PREFS_ROOT`` wins when it is set, which is how the launcher's first-run sandbox and
    the test suites keep away from a real machine's preferences. Without it, Documents.

    :return: The folder.
    :rtype: str
    """

    override = os.getenv(consts.MCA_PREFS_ROOT)
    if override:
        return os.path.normpath(override)
    return os.path.join(platforms.documents_folder(), consts.MCA_LOCAL_PREFS)


def get_local_preferences_folder(project_name=None):
    """
    :param str project_name: The project. None uses ``MCA_PROJECT_NAME``.
    :return: That project's preferences folder, or the root when there is no project yet.
    :rtype: str
    """

    name = project_name or os.getenv(consts.MCA_PROJECT_NAME) or ''
    root = get_preferences_root()
    # The old version joined the name straight on, so a machine with no project set raised
    # TypeError from os.path.join(root, None) rather than answering anything.
    return os.path.normpath(os.path.join(root, name) if name else root)


def get_preferences_file(project_name=None):
    """
    :param str project_name: The project. None uses ``MCA_PROJECT_NAME``.
    :return: The project preferences file the launcher writes.
    :rtype: str
    """

    return os.path.normpath(os.path.join(get_local_preferences_folder(project_name),
                                         consts.MCA_LOCAL_PREFS_FILE))


def read_preferences(project_name=None):
    """
    :param str project_name: The project. None uses ``MCA_PROJECT_NAME``.
    :return: What the launcher saved for it, or {} when there is nothing to read.
    :rtype: dict
    """

    path = get_preferences_file(project_name)
    values = yamlio.read_yaml_file(path, default={})
    if not isinstance(values, dict):
        logger.warning('%s does not hold a project: %s', path, type(values).__name__)
        return {}
    return values


# ---------------------------------------------------------------------------- #
# The project, from the environment the launcher built
# ---------------------------------------------------------------------------- #
def get_project_name():
    """
    :return: The project this DCC was started for, or ''.
    :rtype: str
    """

    return os.getenv(consts.MCA_PROJECT_NAME) or ''


def get_project_path():
    """
    :return: The project root, or ''.
    :rtype: str
    """

    return os.getenv(consts.MCA_PROJECT_ROOT) or ''


#: The old name for :func:`get_project_path`. Both existed and did the same thing.
get_mca_root_path = get_project_path


def get_mca_package_path():
    """
    :return: The packages folder - the one holding mca-common - or ''.
    :rtype: str
    """

    return os.getenv(consts.MCA_FRAMEWORK_PATH) or ''


def get_common_path():
    """
    :return: mca-common's ``mca/common`` folder, or '' when the framework path is not set.
    :rtype: str
    """

    framework = get_mca_package_path()
    if not framework:
        return ''
    return os.path.normpath(os.path.join(framework, consts.MCA_DEFAULT_COMMON_PATH))


def get_package_python_config_path():
    """
    :return: The framework's config file, or '' when it is not there.
    :rtype: str
    """

    framework = get_mca_package_path()
    if not framework:
        logger.warning('%s is not set, so the framework config cannot be found.',
                       consts.MCA_FRAMEWORK_PATH)
        return ''
    path = os.path.normpath(os.path.join(framework, consts.MCA_PACKAGE_BOOTS))
    if not os.path.exists(path):
        logger.warning('There is no framework config at %s.', path)
        return ''
    return path


def get_art_path(which=consts.MCA_ART_PATH):
    """
    :param str which: One of ``consts.ART_PATHS``.
    :return: That art folder, or ''.
    :rtype: str
    """

    return os.getenv(which) or ''


# ---------------------------------------------------------------------------- #
# Putting a project into the environment
# ---------------------------------------------------------------------------- #
class ProjectEnvs(object):
    """
    A project's preferences, and the environment they become.

    Used when something other than the launcher has to set a project up - a standalone
    script, a farm job, a DCC opened by hand.
    """

    def __init__(self, project_name, project_dict=None):
        """
        :param str project_name: The project.
        :param dict project_dict: Its values, when they are already in hand. None reads them.
        """

        self.project_name = project_name
        self._project_dict = project_dict if project_dict is not None else None
        if self._project_dict is None:
            self.get_preferences()

    @property
    def values(self):
        """
        :return: The project's values.
        :rtype: dict
        """

        return dict(self._project_dict or {})

    def get_preferences(self):
        """
        Read the project's preferences file.

        :return: What it holds.
        :rtype: dict
        """

        self._project_dict = read_preferences(self.project_name)
        if not self._project_dict:
            logger.warning('There is nothing saved for the project %s at %s.',
                           self.project_name, get_preferences_file(self.project_name))
        return self._project_dict

    def missing(self):
        """
        :return: The values this project needs and does not have.
        :rtype: list(str)
        """

        needed = (consts.MCA_PROJECT_ROOT, consts.MCA_FRAMEWORK_PATH)
        return [name for name in needed if not str(self.values.get(name) or '').strip()]

    def set_project_envs(self):
        """
        Put this project into the environment.

        Only what the file actually holds. The version this replaces assigned every key it
        expected, so one absent from an older preferences file raised ``TypeError: str
        expected, not NoneType`` - halfway through, leaving the environment part set.

        :return: The names that were set.
        :rtype: list(str)
        """

        values = self.values
        if not values:
            logger.warning('No preferences for %s, so nothing was set.', self.project_name)
            return []

        was_set = []
        for name, value in values.items():
            text = str(value or '').strip()
            if not text:
                logger.debug('%s is empty in %s, so it was left alone.',
                             name, self.project_name)
                continue
            os.environ[name] = text
            was_set.append(name)

        os.environ.setdefault(consts.MCA_PROJECT_NAME, str(self.project_name))
        was_set.extend(set_common_envs())
        return sorted(set(was_set))


def set_common_envs():
    """
    Set the variables that follow from the framework path: mca-common, and its resources.

    :return: The names that were set.
    :rtype: list(str)
    """

    common = get_common_path()
    if not common:
        logger.warning('%s is not set, so the resource folders cannot be worked out.',
                       consts.MCA_FRAMEWORK_PATH)
        return []

    os.environ[consts.MCA_COMMON_PATH] = common
    resources = os.path.normpath(os.path.join(common, 'resources'))
    os.environ[consts.MCA_RESOURCES_PATH] = resources

    was_set = [consts.MCA_COMMON_PATH, consts.MCA_RESOURCES_PATH]
    for folder, variable in consts.RESOURCE_FOLDERS:
        os.environ[variable] = os.path.normpath(os.path.join(resources, folder))
        was_set.append(variable)
    return was_set
