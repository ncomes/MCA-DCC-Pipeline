"""
Named animation libraries, and which one is current.

A "project" here is just a library root with a name on it. The library itself
already knows how to live at any folder - :class:`~mca.common.animlib.catalog.AnimCatalog`
takes a root - so switching projects is only a matter of remembering the roots
somebody uses and which one they picked last.

Why this is not a QSettings value: the browser UI, the MCP tools and anything
scripted all have to agree on which library they are looking at, and only one of
those three is a Qt application. The list lives in a small JSON file instead.

Where it lives is deliberately *outside* the per-depot preferences folder. A
project in this sense is often a different depot entirely, and a list that
disappeared when you switched depots would be useless for the one job it has.

Removing a project forgets the path. It never deletes a library - somebody
pointing the browser at a folder is not them asking to lose what is in it.

:Requires: mca.common.paths, mca.common.textio
:Side effects: :func:`save` writes the projects file.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.textio import jsonio

logger = log.MCA_LOGGER

PROJECTS_FILE_NAME = 'animlibrary_projects.json'
PROJECTS_VERSION = 1

# Name given to the project that is created from the depot's own library folder
# the first time anybody asks, so a fresh install has something to be current.
DEFAULT_PROJECT_NAME = 'Default'


def get_projects_file():
    """
    Where the project list is stored.

    :return: Absolute path to the projects JSON.
    :rtype: str
    """

    from mca.common.paths import project_paths

    # project_paths.get_preferences_root() rather than Documents plus the folder name: it is
    # the same folder, and it is the one MCA_PREFS_ROOT moves. The version this replaces built
    # the path by hand, so the launcher's first-run sandbox did not contain this file and a
    # test run wrote into a real machine's Documents folder.
    return os.path.normpath(os.path.join(project_paths.get_preferences_root(),
                                         PROJECTS_FILE_NAME))


def get_default_root():
    """
    The library root the pipeline ships with.

    This is the folder beside Assetlist under the common tools path - where the
    library lives when nobody has gone looking for another one.

    :return: Absolute path to the default library root.
    :rtype: str
    """

    from mca.common.paths import paths
    return os.path.normpath(os.path.join(paths.get_common_tools_path(), 'AnimationLibrary'))


def _normalise(root):
    """
    :param str root: A library root.
    :return: The path in the one spelling comparisons use.
    :rtype: str
    """

    return os.path.normpath(os.path.abspath(str(root or '').strip()))


def load():
    """
    Read the project list, seeding it with the default project when absent.

    A missing file is not an error - it is what a machine that has never
    switched projects looks like.

    :return: ``{'version', 'current', 'projects': [{'name', 'root'}]}``
    :rtype: dict
    """

    path = get_projects_file()
    data = {}
    if os.path.isfile(path):
        data = jsonio.read_json_file(path) or {}
        if not isinstance(data, dict):
            logger.warning('The animation library projects file at %s is not a mapping; '
                           'starting from the default.', path)
            data = {}

    projects = [p for p in (data.get('projects') or [])
                if isinstance(p, dict) and p.get('name') and p.get('root')]
    if not projects:
        projects = [{'name': DEFAULT_PROJECT_NAME, 'root': get_default_root()}]

    current = data.get('current')
    if current not in [p['name'] for p in projects]:
        current = projects[0]['name']

    return {'version': PROJECTS_VERSION, 'current': current, 'projects': projects}


def save(data):
    """
    Write the project list.

    :param dict data: As returned by :func:`load`.
    :return: The path written.
    :rtype: str
    """

    path = get_projects_file()
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    payload = {'version': PROJECTS_VERSION,
               'current': data.get('current') or '',
               'projects': [{'name': p['name'], 'root': p['root']}
                            for p in (data.get('projects') or [])]}
    jsonio.write_to_json_file(payload, path)
    logger.debug('Wrote %d animation library project(s) to %s', len(payload['projects']), path)
    return path


def all_projects():
    """
    :return: Every known project as ``{'name', 'root', 'current', 'exists'}``.
    :rtype: list[dict]
    """

    data = load()
    rows = []
    for project in data['projects']:
        root = project['root']
        rows.append({'name': project['name'],
                     'root': root,
                     'current': project['name'] == data['current'],
                     'exists': os.path.isdir(root)})
    return rows


def current():
    """
    :return: The current project as ``{'name', 'root'}``.
    :rtype: dict
    """

    data = load()
    for project in data['projects']:
        if project['name'] == data['current']:
            return dict(project)
    return {'name': DEFAULT_PROJECT_NAME, 'root': get_default_root()}


def current_root():
    """
    :return: The current project's library root.
    :rtype: str
    """

    return current()['root']


def find(name):
    """
    :param str name: Project name, matched without regard to case.
    :return: The project, or None.
    :rtype: dict or None
    """

    wanted = str(name or '').strip().lower()
    for project in load()['projects']:
        if project['name'].lower() == wanted:
            return dict(project)
    return None


def add(name, root, make_current=True):
    """
    Remember a library root under a name.

    The folder does not have to exist yet: pointing at a library you are about
    to fill is a normal thing to want, and the first capture creates it.

    :param str name: What to call it.
    :param str root: The library root folder.
    :param bool make_current: Switch to it once added.
    :return: The stored project.
    :rtype: dict
    :raises ValueError: On an empty name or root, or a name already in use.
    """

    name = str(name or '').strip()
    root = _normalise(root)
    if not name:
        raise ValueError('A project needs a name.')
    if not root or root == '.':
        raise ValueError('A project needs a library root folder.')

    data = load()
    for project in data['projects']:
        if project['name'].lower() == name.lower():
            raise ValueError('There is already a project called {!r}, pointing at {}. Remove it '
                             'first, or pick another name.'.format(project['name'], project['root']))
        if _normalise(project['root']) == root:
            raise ValueError('{} is already in the list as {!r}.'.format(root, project['name']))

    stored = {'name': name, 'root': root}
    data['projects'].append(stored)
    if make_current:
        data['current'] = name
    save(data)
    return dict(stored)


def remove(name):
    """
    Forget a project. Its library on disk is left alone.

    :param str name: Project name.
    :return: The removed project.
    :rtype: dict
    :raises ValueError: When it is unknown, or it is the only one left.
    """

    data = load()
    wanted = str(name or '').strip().lower()
    match = [p for p in data['projects'] if p['name'].lower() == wanted]
    if not match:
        raise ValueError('No animation library project called {!r}. Known: {}.'
                         .format(name, ', '.join(p['name'] for p in data['projects'])))
    if len(data['projects']) == 1:
        raise ValueError('{!r} is the only project; add another before removing this one, or the '
                         'browser would have no library to open.'.format(match[0]['name']))

    data['projects'] = [p for p in data['projects'] if p['name'].lower() != wanted]
    if data['current'].lower() == wanted:
        data['current'] = data['projects'][0]['name']
    save(data)
    return dict(match[0])


def set_current(name):
    """
    Switch to a project.

    :param str name: Project name.
    :return: The now-current project.
    :rtype: dict
    :raises ValueError: When it is unknown.
    """

    data = load()
    wanted = str(name or '').strip().lower()
    for project in data['projects']:
        if project['name'].lower() == wanted:
            data['current'] = project['name']
            save(data)
            return dict(project)
    raise ValueError('No animation library project called {!r}. Known: {}.'
                     .format(name, ', '.join(p['name'] for p in data['projects'])))
