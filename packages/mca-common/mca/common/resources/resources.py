"""
The icons, images, movies and stylesheets a tool draws with.

    from mca.common.resources import resources

    button.setIcon(resources.icon('tools/rig_builder.png'))
    window.setStyleSheet(resources.read_stylesheet('dark_theme'))

Nothing is bundled with the package: the folders come from the environment the launcher
built - ``MCA_ICONS_PATH``, ``MCA_IMAGES_PATH``, and the project's own icons beside its
shared tools - so a studio points at its own art and a clone with none still runs.

What changed:

- **Everything was built at start-up.** Registering walked every folder and constructed a
  ``QIcon`` *and* a ``QPixmap`` for all of them - 1,269 icons on the machine this came from -
  before anything had asked for one. They are found at start-up and built the first time
  they are asked for now, and kept after that.
- **Images directly in the images folder were invisible.** The icon walk added the root
  folder to the list of places to look; the image walk did not, so an image that was not in
  a subfolder could never be found.
- **Keys were built with backslashes** - ``f'{sub_dir}\\\\{name}'`` - so every caller had to
  write a Windows path, and on any other machine the same call missed. Either separator
  works now, and case does not matter.
- ``pixmap()`` searched the icon dictionary and read the pixmap out of it, which worked, and
  a third dictionary called 'pixmap' was created and never filled.
- ``read_stylesheet`` logged ``'Unable to read style sheet {stylesheet}'`` with no ``f``, so
  the one message that says what went wrong printed the braces instead of the name.
- Importing this needed Qt. It does not now; asking it for an icon without Qt answers None
  and says so once.
"""

# python imports
import os

# mca imports
from mca.common import log
from mca.common.modifiers import singleton
from mca.common.paths import path_utils, paths
from mca.common.pyqt import pygui


logger = log.MCA_LOGGER

#: What counts as an image worth registering.
IMAGE_TYPES = ('.png', '.bmp', '.svg', '.jpg', '.jpeg', '.ico')

#: Shown when something asks for an icon that is not there.
FALLBACK_ICON = 'company_logos/default_logo.png'


class ResourceTypes(object):
    """The kinds of thing this holds."""

    ICON = 'icon'
    PIXMAP = 'pixmap'
    IMAGE = 'image'


def normalise(name):
    """
    One spelling for a resource's name.

    :param str name: ``'tools/rig.png'``, ``'tools\\rig.png'``, ``'Tools/Rig.PNG'`` - all
        the same thing.
    :return: The name this library files it under.
    :rtype: str
    """

    return str(name or '').replace('\\', '/').strip('/').lower()


class Resources(singleton.SimpleSingleton):
    """
    Every resource the framework can find, and the Qt objects made from them.

    One instance, because finding them means walking folders. It can be let go of -
    ``singleton.teardown()``, which a framework restart calls - so a new project's art is
    found rather than the old project's being remembered.
    """

    def __init__(self):
        self.files = {ResourceTypes.ICON: {}, ResourceTypes.IMAGE: {}}
        self.built = {}
        self.registered_folders = []
        self.reset()

    # -- finding -------------------------------------------------------- #
    def reset(self):
        """
        Look again, from nothing.

        :return: How many files were found.
        :rtype: int
        """

        self.files = {ResourceTypes.ICON: {}, ResourceTypes.IMAGE: {}}
        self.built = {}
        self.registered_folders = []

        self.register_common_icons()
        self.register_dev_icons()
        self.register_images()
        return sum(len(one) for one in self.files.values())

    def register_folder(self, folder, kind):
        """
        Register every image in a folder and everything under it.

        :param str folder: Where to look. '' and folders that are not there are skipped.
        :param str kind: ``ResourceTypes.ICON`` or ``ResourceTypes.IMAGE``.
        :return: How many were found.
        :rtype: int
        """

        if not folder or not os.path.isdir(folder):
            return 0

        # The folder itself as well as everything under it. The image walk used to leave
        # this out, so an image that was not in a subfolder was invisible.
        places = [folder] + path_utils.get_sub_dirs(folder)
        found = 0
        for place in places:
            try:
                names = sorted(os.listdir(place))
            except OSError as error:
                logger.debug('Could not read %s: %s', place, error)
                continue

            for name in names:
                if not name.lower().endswith(IMAGE_TYPES):
                    continue
                path = os.path.join(place, name)
                if not os.path.isfile(path):
                    continue
                relative = os.path.relpath(path, folder)
                self.files[kind][normalise(relative)] = path
                found += 1

        if found:
            self.registered_folders.append(folder)
            logger.debug('Found %s %s(s) in %s.', found, kind, folder)
        return found

    def register_common_icons(self):
        """
        :return: How many of the project's own icons were found.
        :rtype: int
        """

        return self.register_folder(paths.get_common_icons_path(), ResourceTypes.ICON)

    def register_dev_icons(self):
        """
        :return: How many of the framework's icons were found.
        :rtype: int
        """

        return self.register_folder(paths.get_icons_path(), ResourceTypes.ICON)

    def register_images(self):
        """
        :return: How many images were found.
        :rtype: int
        """

        return self.register_folder(paths.get_images_path(), ResourceTypes.IMAGE)

    # -- asking for one ------------------------------------------------- #
    def path(self, name, kind=ResourceTypes.ICON):
        """
        :param str name: The resource's name, with either separator.
        :param str kind: Which kind to look among.
        :return: The file, or ''.
        :rtype: str
        """

        return self.files.get(kind, {}).get(normalise(name), '')

    def get(self, name, kind=ResourceTypes.ICON, as_type=None):
        """
        The Qt object for a resource, built the first time it is asked for.

        :param str name: The resource's name.
        :param str kind: Which kind to look among.
        :param str as_type: ``ResourceTypes.ICON`` for a QIcon, ``PIXMAP`` for a QPixmap.
            None takes the natural one for the kind.
        :return: A QIcon or QPixmap, or None.
        """

        as_type = as_type or (ResourceTypes.PIXMAP if kind == ResourceTypes.IMAGE
                              else ResourceTypes.ICON)
        key = (kind, normalise(name), as_type)
        if key in self.built:
            return self.built[key]

        path = self.path(name, kind)
        if not path:
            return None
        if not pygui.AVAILABLE:
            logger.debug('There is no Qt here, so %s cannot be built.', name)
            return None

        try:
            made = (pygui.qtgui.QIcon(path) if as_type == ResourceTypes.ICON
                    else pygui.qtgui.QPixmap(path))
        except Exception as error:                                   # noqa: BLE001
            logger.warning('Could not load %s: %s', path, error)
            return None

        self.built[key] = made
        return made


# ---------------------------------------------------------------------------- #
# What tools call
# ---------------------------------------------------------------------------- #
def register_resources():
    """
    Find everything. Called once, when the framework starts.

    :return: How many files were found.
    :rtype: int
    """

    return Resources().reset()


def update_common_resources():
    """
    Look again for the project's own icons, after they have changed on disk.

    :return: How many were found.
    :rtype: int
    """

    return Resources().register_common_icons()


def icon(image_path, typ=ResourceTypes.ICON):
    """
    :param str image_path: The icon's name, for example ``'tools/rig_builder.png'``.
    :param str typ: ``ResourceTypes.ICON`` or ``ResourceTypes.PIXMAP``.
    :return: The QIcon, the default icon when there is one, or None.
    """

    library = Resources()
    found = library.get(image_path, ResourceTypes.ICON, typ)
    if found is not None:
        return found

    if normalise(image_path) != normalise(FALLBACK_ICON):
        logger.warning('No icon called %s is registered.', image_path)
        # Only one step down, and never back to itself.
        return library.get(FALLBACK_ICON, ResourceTypes.ICON, typ)
    return None


def pixmap(image_path):
    """
    :param str image_path: The icon's name.
    :return: It as a QPixmap, or None.
    """

    return icon(image_path, typ=ResourceTypes.PIXMAP)


def image(image_path):
    """
    :param str image_path: The image's name.
    :return: It as a QPixmap, or None.
    """

    found = Resources().get(image_path, ResourceTypes.IMAGE)
    if found is None:
        logger.warning('No image called %s is registered.', image_path)
    return found


def icon_path(image_path):
    """
    :param str image_path: The icon's name.
    :return: The file it came from, or ''. For anything that wants the path rather than a
        Qt object - a stylesheet, a web page, a report.
    :rtype: str
    """

    return Resources().path(image_path, ResourceTypes.ICON)


def movie(name):
    """
    :param str name: An animation's name, with or without ``.gif``.
    :return: Its path, or '' when there is no movies folder.
    :rtype: str
    """

    folder = paths.get_movies_path()
    if not folder:
        return ''
    if not str(name).lower().endswith('.gif'):
        name = '{}.gif'.format(name)
    return os.path.normpath(os.path.join(folder, name))


def read_stylesheet(stylesheet):
    """
    :param str stylesheet: A stylesheet's name, with or without ``.css``.
    :return: Its text, or '' when there is no such file.
    :rtype: str
    """

    folder = paths.get_stylesheet_path()
    if not folder:
        logger.debug('No stylesheet folder is set, so %s cannot be read.', stylesheet)
        return ''

    name = str(stylesheet or '')
    # rsplit, not split: a stylesheet called 'dark.theme.css' kept only 'dark' before.
    if name.lower().endswith('.css'):
        name = name.rsplit('.', 1)[0]
    path = os.path.join(folder, '{}.css'.format(name))
    if not os.path.isfile(path):
        # The f was missing from this message, so the one line that says what went wrong
        # printed the braces instead of the name.
        logger.warning('There is no stylesheet at %s.', path)
        return ''

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as opened:
            return opened.read()
    except OSError as error:
        logger.warning('Could not read %s: %s', path, error)
        return ''
