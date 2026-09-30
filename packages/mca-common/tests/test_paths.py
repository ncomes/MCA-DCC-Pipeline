"""
Paths, checked without a DCC and without Windows.

The module this replaces could not be imported off Windows at all - ``import ctypes.wintypes``
at the top - so none of it had ever been run by a test. Every check below is either something
that was wrong, or something that would be wrong again if the environment stopped being read
afresh.

    python tests/test_paths.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.paths import path_utils, paths, project_paths  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import yamlio  # noqa: E402
from mca.common.utils import platforms  # noqa: E402


def body(suite):
    temp = suite.temp

    # ---------------------------------------------------------------- #
    # It imports anywhere
    # ---------------------------------------------------------------- #
    suite.check('the platform lookups import and answer off Windows too',
                bool(platforms.documents_folder()) and bool(platforms.home_folder()),
                platforms.documents_folder())
    suite.check('and say which machine this is', isinstance(platforms.IS_WINDOWS, bool))
    suite.check('the desktop is asked for as well', bool(platforms.desktop_folder()),
                platforms.desktop_folder())
    suite.check('and there is a name for whoever is logged in',
                bool(platforms.user_name()), platforms.user_name())

    # ---------------------------------------------------------------- #
    # Preferences
    # ---------------------------------------------------------------- #
    suite.check('the preferences root follows MCA_PREFS_ROOT, so a suite cannot read or '
                'write a real machine\'s',
                project_paths.get_preferences_root() ==
                os.path.normpath(os.environ[consts.MCA_PREFS_ROOT]),
                project_paths.get_preferences_root())

    os.environ.pop(consts.MCA_PROJECT_NAME, None)
    suite.check('with no project set, the preferences folder is the root rather than a '
                'TypeError from joining None onto it',
                project_paths.get_local_preferences_folder() ==
                project_paths.get_preferences_root(),
                project_paths.get_local_preferences_folder())

    os.environ[consts.MCA_PROJECT_NAME] = 'Wayward'
    folder = project_paths.get_local_preferences_folder()
    suite.check('with one set, it is under the root, by name',
                folder.endswith('Wayward'), folder)
    suite.check('and the file is the one the launcher writes',
                project_paths.get_preferences_file().endswith(consts.MCA_LOCAL_PREFS_FILE),
                project_paths.get_preferences_file())

    suite.check('reading preferences that are not there answers {} rather than None or a '
                'raise', project_paths.read_preferences('NoSuchProject') == {})

    # ---------------------------------------------------------------- #
    # A project, put into the environment
    # ---------------------------------------------------------------- #
    project_root = os.path.join(temp, 'Wayward')
    framework = os.path.join(temp, 'repo', 'packages')
    os.makedirs(os.path.join(framework, 'mca-common', 'mca', 'common', 'resources'))
    os.makedirs(project_root)

    saved = {consts.MCA_PROJECT_NAME: 'Wayward',
             consts.MCA_PROJECT_ROOT: project_root,
             consts.MCA_FRAMEWORK_PATH: framework,
             consts.MCA_CHARACTERS_PATH: os.path.join(temp, 'art', 'Characters'),
             consts.MCA_PROPS_PATH: ''}
    yamlio.write_to_yaml_file(saved, project_paths.get_preferences_file('Wayward'))

    envs = project_paths.ProjectEnvs('Wayward')
    suite.check('a project reads its preferences',
                envs.values.get(consts.MCA_PROJECT_ROOT) == project_root, str(envs.values))
    suite.check('and says nothing is missing when the two that matter are there',
                envs.missing() == [], str(envs.missing()))

    was_set = envs.set_project_envs()
    suite.check('setting it puts the project root into the environment',
                os.getenv(consts.MCA_PROJECT_ROOT) == project_root,
                str(os.getenv(consts.MCA_PROJECT_ROOT)))
    # The old version assigned every key it expected, so one missing from an older
    # preferences file raised TypeError halfway through and left the environment part set.
    suite.check('a value that is empty in the file is left alone rather than raising',
                consts.MCA_PROPS_PATH not in was_set, str(was_set))
    suite.check('and the resource folders follow from the framework path',
                os.getenv(consts.MCA_ICONS_PATH, '').endswith(os.path.join('resources',
                                                                           'icons')),
                str(os.getenv(consts.MCA_ICONS_PATH)))
    suite.check('mca-common is found under the packages folder',
                project_paths.get_common_path() ==
                os.path.normpath(os.path.join(framework, 'mca-common', 'mca', 'common')),
                project_paths.get_common_path())

    incomplete = project_paths.ProjectEnvs('Empty', project_dict={})
    suite.check('a project with nothing saved says what it is missing',
                incomplete.missing() == [consts.MCA_PROJECT_ROOT, consts.MCA_FRAMEWORK_PATH],
                str(incomplete.missing()))
    suite.check('and setting it changes nothing rather than raising',
                incomplete.set_project_envs() == [])

    # The point of having no module-level snapshots: this is read now, not at import.
    os.environ[consts.MCA_PROJECT_ROOT] = os.path.join(temp, 'Another')
    suite.check('changing project after import is seen, rather than a value frozen at the '
                'moment the framework first loaded',
                project_paths.get_project_path().endswith('Another'),
                project_paths.get_project_path())
    os.environ[consts.MCA_PROJECT_ROOT] = project_root

    # ---------------------------------------------------------------- #
    # Walking folders
    # ---------------------------------------------------------------- #
    tree = os.path.join(temp, 'tree')
    for folder in (os.path.join(tree, 'rigging'), os.path.join(tree, 'rigging_old'),
                   os.path.join(tree, 'anim', 'rigging')):
        os.makedirs(folder)
    for path in (os.path.join(tree, 'one.ma'), os.path.join(tree, 'rigging', 'two.MA'),
                 os.path.join(tree, 'anim', 'notes.txt'),
                 os.path.join(tree, 'anim', 'rigging', 'three.fbx')):
        with open(path, 'w', encoding='utf-8') as opened:
            opened.write('x')

    everything = path_utils.get_sub_dirs(tree)
    suite.check('every folder underneath is found, not only the top level - the old version '
                'recursed and threw the result away',
                len(everything) == 4, str(everything))
    suite.check('and one level can still be asked for',
                len(path_utils.get_sub_dirs(tree, recursive=False)) == 3,
                str(path_utils.get_sub_dirs(tree, recursive=False)))

    named = path_utils.all_folders_in_directory(tree, 'rigging')
    suite.check('asking for a folder by name matches the name, not anything containing it - '
                'rigging_old is not rigging',
                len(named) == 2 and all(one.endswith('rigging') for one in named),
                str(named))
    suite.check('and the answer is a list whether or not a name was given',
                isinstance(path_utils.all_folders_in_directory(tree), list) and
                isinstance(named, list))

    suite.check('files are found the same way',
                path_utils.all_files_in_directory(tree, 'one.ma') ==
                [os.path.normpath(os.path.join(tree, 'one.ma'))],
                str(path_utils.all_files_in_directory(tree, 'one.ma')))
    suite.check('a name nobody has answers an empty list, not None',
                path_utils.all_files_in_directory(tree, 'nope.ma') == [])

    scenes = path_utils.all_file_types_in_directory(tree, '.ma')
    suite.check('extensions are matched whatever the case - a .MA off another machine is '
                'still a Maya scene', len(scenes) == 2, str(scenes))
    suite.check('the leading dot is optional',
                path_utils.all_file_types_in_directory(tree, 'ma') == scenes)
    suite.check('and several can be asked for at once',
                len(path_utils.all_file_types_in_directory(tree, ('.ma', '.fbx'))) == 3,
                str(path_utils.all_file_types_in_directory(tree, ('.ma', '.fbx'))))
    suite.check('walking a folder that is not there answers an empty list',
                path_utils.all_files_in_directory(os.path.join(temp, 'nope')) == [])
    suite.check('and find_first answers one thing or nothing',
                path_utils.find_first(tree, 'one.ma').endswith('one.ma') and
                path_utils.find_first(tree, 'nope.ma') == '')

    # ---------------------------------------------------------------- #
    # Project relative
    # ---------------------------------------------------------------- #
    root = os.path.join(temp, 'Wayward')
    inside = os.path.join(root, 'art', 'hero.ma')
    suite.check('a path under the project comes back relative',
                path_utils.to_relative_path(inside, root) == os.path.join('art', 'hero.ma'),
                path_utils.to_relative_path(inside, root))

    # The one that used to lose folders: the project's name appearing twice in the path.
    twice = os.path.join(root, 'art', 'Wayward', 'hero.ma')
    suite.check('and so does one with the project name in it twice, which is what an art '
                'folder named after the project looks like',
                path_utils.to_relative_path(twice, root) ==
                os.path.join('art', 'Wayward', 'hero.ma'),
                path_utils.to_relative_path(twice, root))

    outside = os.path.join(temp, 'elsewhere', 'hero.ma')
    suite.check('a path that is not under the project is answered unchanged rather than '
                'quietly becoming its last few folders',
                path_utils.to_relative_path(outside, root) == os.path.normpath(outside),
                path_utils.to_relative_path(outside, root))

    suite.check('and it goes back the other way',
                path_utils.to_full_path(os.path.join('art', 'hero.ma'), root) ==
                os.path.normpath(inside), path_utils.to_full_path('art/hero.ma', root))
    suite.check('a path that is already full is left alone',
                path_utils.to_full_path(inside, root) == os.path.normpath(inside))
    suite.check('and nothing in answers nothing out',
                path_utils.to_relative_path('') == '' and path_utils.to_full_path('') == '')

    suite.note('checks_written', len(suite.checks))


    # The registry reads this file by name, so the name has to be the one on disk. It was
    # 'categories.manifest' here for one commit, and nothing in the asset registry loaded.
    suite.check('the category manifest is the file that is actually there, categories.json',
                paths.get_categories_manifest_path().endswith('categories.json'),
                paths.get_categories_manifest_path())


if __name__ == '__main__':
    sys.exit(harness.run('paths', body))
