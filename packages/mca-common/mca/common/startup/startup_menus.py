"""
The menu entries every DCC shares: the project's documentation pages, and its folder.

Each DCC's own start-up builds its menus and points the shared entries at these, so the Maya
menu and the MotionBuilder menu open the same pages.

Where the pages are comes from the ``urls`` block of the package manifest beside the code -
see :mod:`mca.common.startup.configs.package_config`. **They are blank in this repository**:
the ones this replaces pointed at a previous employer's internal wiki. A blank one is not an
error, and it is not a browser window opened at nothing either: the menu says there is no page
for that yet, which is true.

Three things about the version this replaces:

- It read the manifest through ``mca.common.textio.packages``, which is not here any more -
  ``package_config`` replaced it, and reports what is wrong with a manifest rather than
  guessing.
- It built its package manager **at module scope**, so a manifest with a problem in it took the
  DCC's whole menu down while the menu was being built.
- ``webbrowser.open('')`` is what a blank URL did: a browser window at whatever was there
  before, which reads as the tool being broken rather than the page not existing.
- ``open_plastic_folder`` was named for a source control the project stopped using, indexed
  ``[0]`` into the answer of a function that no longer exists, and ran
  ``'explorer ' + path`` - so a project path with a space in it opened the wrong folder, on
  Windows only.
"""

# python imports
import webbrowser

# MCA python imports
from mca.common import log
from mca.common.paths import paths
from mca.common.startup.configs import package_config
from mca.common.utils import fileio


logger = log.MCA_LOGGER

#: The pages a DCC menu offers, and what each one is called where a person will read it.
DOCUMENTATION_PAGES = (
    ('project', 'Project Documentation'),
    ('animation', 'Animation Documentation'),
    ('modeling', 'Modeling Documentation'),
    ('rigging', 'Rigging Documentation'),
    ('tracker', 'Issue Tracker'),
    ('setup', 'Setting Up A Machine'),
)


def documentation_urls():
    """
    Every documentation page the project names.

    :return: Page name to its address. Blank entries are left out, so a caller can ask
        ``if 'rigging' in documentation_urls()``.
    :rtype: dict
    """

    manifest = package_config.read_package(paths.get_common_path() or paths.get_common_tools_path())
    if not manifest:
        # Read when asked rather than when imported: a manifest with a problem in it must not
        # take a DCC's menu with it.
        logger.debug('No package manifest to read documentation pages from.')
        return {}

    return manifest.urls


def open_documentation(page):
    """
    Open one of the project's documentation pages.

    :param str page: A key of :data:`DOCUMENTATION_PAGES` - ``'rigging'``, ``'animation'``.
    :return: Whether a page was opened.
    :rtype: bool
    """

    url = documentation_urls().get(page, '')
    if not url:
        logger.info('This project has no %s documentation page yet. Add one to the urls block '
                    'of its mca_package.yaml.', page)
        return False

    webbrowser.open(url)

    return True


def project_url_menu():
    """
    :return: Whether the project's own page opened.
    :rtype: bool
    """

    return open_documentation('project')


def animation_url_menu():
    """
    :return: Whether the animation page opened.
    :rtype: bool
    """

    return open_documentation('animation')


def modeling_url_menu():
    """
    :return: Whether the modeling page opened.
    :rtype: bool
    """

    return open_documentation('modeling')


def rigging_url_menu():
    """
    :return: Whether the rigging page opened.
    :rtype: bool
    """

    return open_documentation('rigging')


def tracker_url_menu():
    """
    :return: Whether the issue tracker opened. This was ``jira_url_menu``; which tracker a
        studio uses is the manifest's business, not the function name's.
    :rtype: bool
    """

    return open_documentation('tracker')


def setup_url_menu():
    """
    :return: Whether the machine-setup page opened.
    :rtype: bool
    """

    return open_documentation('setup')


def open_project_folder():
    """
    Open the project's folder in the machine's file browser.

    :return: Whether a browser was opened.
    :rtype: bool
    """

    root = paths.project_root()
    if not root:
        logger.warning('There is no project, so there is no folder to open.')
        return False

    return fileio.explore_to_path(root)
