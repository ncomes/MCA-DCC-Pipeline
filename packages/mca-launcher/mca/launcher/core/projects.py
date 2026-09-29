"""
Setting a project up, and checking that what was typed in is actually a project.

The old launcher validated by looking for two marker files, ``root.mca`` and
``framework.mca``. Those exist because somebody put them in a Perforce depot years ago;
they say nothing about whether the folder holds a working framework, and a fresh clone of
the repository has neither. So validation is structural here: a framework folder is one
that holds mca-common, because that is what the DCC is about to import. The marker files
are still accepted when present, since existing setups have them.
"""

# python imports
import logging
import os

# mca imports
from mca.launcher.core import prefs


logger = logging.getLogger('mca-launcher')

#: Accepted, not required. A project set up years ago has one of these at its root.
LEGACY_PROJECT_MARKER = 'root.mca'
LEGACY_FRAMEWORK_MARKER = 'framework.mca'

#: What proves a folder is the packages folder.
FRAMEWORK_EVIDENCE = os.path.join('mca-common', 'mca', 'common')


def check_project_root(path):
    """
    Is this a project root.

    :param str path: The folder the artist chose.
    :return: (ok, a sentence saying what is wrong, or what was found)
    :rtype: tuple(bool, str)
    """

    if not str(path or '').strip():
        return False, 'No project folder was given.'
    folder = os.path.normpath(str(path).strip())
    if not os.path.isdir(folder):
        return False, 'There is no folder at {}.'.format(folder)
    if os.path.isfile(os.path.join(folder, LEGACY_PROJECT_MARKER)):
        return True, '{} holds {}.'.format(folder, LEGACY_PROJECT_MARKER)
    return True, '{} will be used as the project root.'.format(folder)


def check_framework_path(path):
    """
    Is this the packages folder - the one a DCC will import the framework from.

    :param str path: The folder the artist chose. Either the packages folder itself or the
        folder holding it is accepted, because both are natural things to pick.
    :return: (ok, a sentence, the resolved packages folder)
    :rtype: tuple(bool, str, str)
    """

    if not str(path or '').strip():
        return False, 'No framework folder was given.', ''

    folder = os.path.normpath(str(path).strip())
    if not os.path.isdir(folder):
        return False, 'There is no folder at {}.'.format(folder), ''

    for candidate in (folder, os.path.join(folder, 'packages')):
        if os.path.isdir(os.path.join(candidate, FRAMEWORK_EVIDENCE)):
            return True, '{} holds mca-common.'.format(candidate), os.path.normpath(candidate)

    if os.path.isfile(os.path.join(folder, LEGACY_FRAMEWORK_MARKER)):
        # An old setup pointing at the framework folder rather than its packages folder.
        packages = os.path.join(folder, 'packages')
        if os.path.isdir(packages):
            return True, '{} holds {}.'.format(folder, LEGACY_FRAMEWORK_MARKER), \
                os.path.normpath(packages)

    return (False,
            '{} does not look like the framework: nothing at {}{}mca-common. Point this at '
            'the packages folder.'.format(folder, folder, os.sep),
            '')


def list_projects():
    """
    :return: The projects set up on this machine, with what each one points at.
    :rtype: list(dict)
    """

    found = []
    for name in prefs.project_names():
        project = prefs.ProjectPrefs.load(name)
        found.append({
            'name': name,
            'project_root': project.project_root,
            'framework_path': project.framework_path,
            'complete': not project.missing(),
            'missing': project.missing(),
        })
    return found


def save_project(name, project_root, framework_path, art_paths=None, common_tools=''):
    """
    Write a project's preferences, after checking the two paths that matter.

    :param str name: The project name.
    :param str project_root: The project root.
    :param str framework_path: The packages folder, or the folder holding it.
    :param dict art_paths: Any of the MCA_*_PATH values, by environment name.
    :param str common_tools: The shared tools folder, if there is one.
    :return: The saved preferences.
    :rtype: prefs.ProjectPrefs
    :raises ValueError: When the name or either path will not do.
    """

    clean_name = str(name or '').strip()
    if not clean_name:
        raise ValueError('A project needs a name.')
    if os.sep in clean_name or (os.altsep and os.altsep in clean_name):
        raise ValueError('A project name cannot contain a path separator: {!r}'.format(name))

    ok, reason = check_project_root(project_root)
    if not ok:
        raise ValueError(reason)

    ok, reason, packages = check_framework_path(framework_path)
    if not ok:
        raise ValueError(reason)

    project = prefs.ProjectPrefs.load(clean_name)
    project.project_name = clean_name
    project.project_root = project_root
    project.framework_path = packages
    for key, value in (art_paths or {}).items():
        if key in prefs.PROJECT_KEYS:
            project.values[key] = str(value or '').strip()
        else:
            logger.warning('Ignoring unknown project key %s.', key)
    if common_tools:
        project.values['MCA_COMMON_TOOLS'] = str(common_tools).strip()

    project.save()
    return project


def default_art_paths(art_path):
    """
    The art folders a new project starts with.

    :param str art_path: The art root. Empty gives empty defaults rather than folder names
        floating with no parent.
    :return: Environment name to path.
    :rtype: dict
    """

    root = str(art_path or '').strip()
    if not root:
        return {key: '' for key, _ in prefs.ART_DEFAULTS}
    return {key: os.path.normpath(os.path.join(root, folder))
            for key, folder in prefs.ART_DEFAULTS}


def installers_root(project_prefs):
    """
    Where this project keeps DCC installers, if it keeps any.

    Checked in order: what the project says, then the layout the old launcher assumed
    (``<project root>/Tools/DCC Launcher/DCCAppLaunchers``) so an existing studio setup keeps
    working without being told about it again.

    :param prefs.ProjectPrefs project_prefs: The project.
    :return: The folder, or '' when there is not one.
    :rtype: str
    """

    stated = str(project_prefs.values.get('MCA_INSTALLERS_PATH') or '').strip()
    if stated and os.path.isdir(stated):
        return os.path.normpath(stated)

    root = project_prefs.project_root
    if root:
        legacy = os.path.join(root, 'Tools', 'DCC Launcher', 'DCCAppLaunchers')
        if os.path.isdir(legacy):
            return os.path.normpath(legacy)
    return ''


def remove_project(name):
    """
    Forget a project. Deletes its preferences folder and nothing else - no art, no code.

    :param str name: The project name.
    :return: What was deleted.
    :rtype: str
    :raises ValueError: When there is no such project, or the name is not a plain name.
    """

    import shutil

    clean_name = str(name or '').strip()
    if not clean_name:
        raise ValueError('Which project? No name was given.')
    if clean_name not in prefs.project_names():
        raise ValueError('There is no project called {!r}. There is: {}.'
                         .format(clean_name, ', '.join(prefs.project_names()) or 'nothing'))

    folder = prefs.project_folder(clean_name)
    root = os.path.normpath(os.path.dirname(folder))
    # The old launcher built this path from an environment variable and handed it straight
    # to rmtree. If that variable was empty the path became the whole preferences folder.
    if os.path.normcase(folder) == os.path.normcase(root) or not os.path.isdir(folder):
        raise ValueError('Refusing to delete {}, which is not a project folder.'.format(folder))

    shutil.rmtree(folder)
    return folder
