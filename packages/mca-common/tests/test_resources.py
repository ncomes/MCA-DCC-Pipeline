"""
The resource library, checked with a folder of files the suite makes.

Runs with or without Qt: without it the files are still found, and asking for a QIcon
answers None rather than raising.

    python tests/test_resources.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from mca.common.modifiers import singleton  # noqa: E402
from mca.common.pyqt import pygui  # noqa: E402
from mca.common.resources import resources  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402


ONE_PIXEL_PNG = bytes(bytearray([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44,
    0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F,
    0x15, 0xC4, 0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00,
    0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49,
    0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82]))


def write_png(path):
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, 'wb') as opened:
        opened.write(ONE_PIXEL_PNG)


def body(suite):
    temp = suite.temp

    icons = os.path.join(temp, 'resources', 'icons')
    images = os.path.join(temp, 'resources', 'images')
    styles = os.path.join(temp, 'resources', 'styles')
    movies = os.path.join(temp, 'resources', 'movies')
    project_icons = os.path.join(temp, 'project', 'Tools', 'Common', 'Tools',
                                 'Resources', 'Icons')

    write_png(os.path.join(icons, 'toolbar.png'))                   # at the root
    write_png(os.path.join(icons, 'tools', 'rig_builder.png'))      # in a subfolder
    write_png(os.path.join(icons, 'company_logos', 'default_logo.png'))
    write_png(os.path.join(images, 'splash.png'))                   # at the root: invisible
    write_png(os.path.join(images, 'banners', 'wide.png'))          # before
    write_png(os.path.join(project_icons, 'studio', 'hero.png'))
    os.makedirs(styles)
    with open(os.path.join(styles, 'dark_theme.css'), 'w', encoding='utf-8') as opened:
        opened.write('QWidget { color: white; }\n')
    os.makedirs(movies)

    os.environ[consts.MCA_ICONS_PATH] = icons
    os.environ[consts.MCA_IMAGES_PATH] = images
    os.environ[consts.MCA_STYLES_PATH] = styles
    os.environ[consts.MCA_MOVIES_PATH] = movies
    os.environ[consts.MCA_PROJECT_ROOT] = os.path.join(temp, 'project')

    singleton.teardown()
    found = resources.register_resources()
    suite.check('everything in the folders is found', found == 6, str(found))

    # ---------------------------------------------------------------- #
    # Names
    # ---------------------------------------------------------------- #
    suite.check('an icon in a subfolder is found by either separator',
                resources.icon_path('tools/rig_builder.png') ==
                resources.icon_path(r'tools\rig_builder.png') != '',
                resources.icon_path('tools/rig_builder.png'))
    suite.check('and case does not matter',
                resources.icon_path('Tools/Rig_Builder.PNG') != '',
                resources.icon_path('Tools/Rig_Builder.PNG'))
    suite.check('an icon at the top of the folder is found too',
                resources.icon_path('toolbar.png') != '')
    suite.check('the project\'s own icons are registered beside the framework\'s',
                resources.icon_path('studio/hero.png') != '',
                resources.icon_path('studio/hero.png'))

    # The image walk left out the root folder, so this one could never be found.
    library = resources.Resources()
    suite.check('an image at the top of the images folder is found - the image walk used '
                'to look only in subfolders',
                library.path('splash.png', resources.ResourceTypes.IMAGE) != '',
                library.path('splash.png', resources.ResourceTypes.IMAGE))
    suite.check('and one in a subfolder as well',
                library.path('banners/wide.png', resources.ResourceTypes.IMAGE) != '')

    suite.check('asking for something nobody registered answers empty',
                resources.icon_path('nothing/at/all.png') == '')

    # ---------------------------------------------------------------- #
    # Qt objects, built when they are asked for
    # ---------------------------------------------------------------- #
    if pygui.AVAILABLE:
        application = pygui.qtwidgets.QApplication.instance() or \
            pygui.qtwidgets.QApplication([])
        suite.check('Qt is here', application is not None)

        suite.check('nothing is built until something asks',
                    library.built == {}, str(list(library.built)))

        made = resources.icon('tools/rig_builder.png')
        suite.check('asking for an icon builds one', made is not None)
        suite.check('and asking again answers the same object rather than building it twice',
                    resources.icon('tools/rig_builder.png') is made)
        suite.check('a pixmap can be had from the same icon',
                    resources.pixmap('tools/rig_builder.png') is not None)
        suite.check('and an image is a pixmap', resources.image('splash.png') is not None)

        suite.check('an icon nobody registered falls back to the default one, once, '
                    'without calling itself in circles',
                    resources.icon('not/there.png') is not None)
        suite.check('and an image nobody registered answers None',
                    resources.image('not/there.png') is None)
    else:
        suite.check('without Qt the files are still found',
                    resources.icon_path('toolbar.png') != '')
        suite.check('and asking for a QIcon answers None rather than raising',
                    resources.icon('toolbar.png') is None)

    # ---------------------------------------------------------------- #
    # Stylesheets
    # ---------------------------------------------------------------- #
    suite.check('a stylesheet is read by name',
                'QWidget' in resources.read_stylesheet('dark_theme'),
                resources.read_stylesheet('dark_theme'))
    suite.check('with or without its extension',
                resources.read_stylesheet('dark_theme.css') ==
                resources.read_stylesheet('dark_theme'))
    suite.check('one that is not there answers empty rather than None, so a caller can '
                'setStyleSheet() it either way',
                resources.read_stylesheet('no_such_theme') == '')

    # ---------------------------------------------------------------- #
    # Movies
    # ---------------------------------------------------------------- #
    suite.check('a movie path is built with or without .gif',
                resources.movie('spinner') == resources.movie('spinner.gif') != '',
                resources.movie('spinner'))
    os.environ.pop(consts.MCA_MOVIES_PATH, None)
    suite.check('and with no movies folder it answers empty rather than a path to nowhere',
                resources.movie('spinner') == '')
    os.environ[consts.MCA_MOVIES_PATH] = movies

    # ---------------------------------------------------------------- #
    # Letting go
    # ---------------------------------------------------------------- #
    # The library is a singleton, and until the singleton was fixed it was one of the ones
    # that could not be cleared at all - so a framework restart kept the old project's art.
    before = resources.Resources()
    singleton.teardown()
    suite.check('a restart lets go of the library, so the next project\'s art is found '
                'rather than the last one\'s remembered',
                resources.Resources() is not before)

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('resources', body))
