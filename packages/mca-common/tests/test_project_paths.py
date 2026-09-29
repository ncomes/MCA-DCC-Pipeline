"""
The project's folders, and which application this is.

Every path function here used to raise TypeError when its environment variable was not set -
os.getenv answers None and os.path.normpath(None) raises - so on a half-set-up machine, or
in Unreal, which is handed fewer of these than Maya is, asking for a folder raised out of a
function documented to return one. That is most of what this suite is about.

    python tests/test_project_paths.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.paths import paths  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.utils import dcc_util  # noqa: E402


#: Every function that answers a path from the environment alone, with no arguments.
NO_ARGUMENT_PATHS = (
    'project_root', 'get_common_tools_path', 'get_common_path', 'get_characters_path',
    'get_gear_path', 'get_dcc_tools_path', 'get_local_preferences_folder',
    'get_asset_list_path', 'get_asset_lists_path', 'get_categories_manifest_path',
    'get_asset_list_file_path', 'get_common_face', 'get_common_source_heads',
    'get_common_skinning', 'get_common_sounds', 'get_common_skeletons',
    'get_common_face_skeletons', 'get_resources_path', 'get_icons_path', 'get_images_path',
    'get_movies_path', 'get_stylesheet_path', 'get_common_resources_path',
    'get_common_icons_path', 'get_cine_path', 'get_cine_seq_path',
)


def body(suite):
    temp = suite.temp

    # ---------------------------------------------------------------- #
    # Nothing set at all
    # ---------------------------------------------------------------- #
    for name in list(vars(consts)):
        value = getattr(consts, name)
        if isinstance(value, str) and value.startswith('MCA_') and name.isupper():
            if value not in (consts.MCA_PREFS_ROOT, consts.MCA_LOGS_ROOT):
                os.environ.pop(value, None)

    answered = {}
    for name in NO_ARGUMENT_PATHS:
        function = getattr(paths, name)
        try:
            answered[name] = function()
        except Exception as error:                                   # noqa: BLE001
            answered[name] = 'RAISED {}: {}'.format(type(error).__name__, error)

    raised = {name: value for name, value in answered.items() if str(value).startswith('RAISED')}
    suite.check('with no project environment at all, not one of the {} path functions '
                'raises - every one of them used to'.format(len(NO_ARGUMENT_PATHS)),
                not raised, str(raised))

    empty = [name for name, value in answered.items()
             if value != '' and name != 'get_local_preferences_folder']
    suite.check('and they answer an empty string, which a caller can test',
                not empty, str(empty))

    suite.check('a path that takes an asset id answers empty too, rather than looking one up '
                'in an asset list that is not there',
                paths.get_asset_path('nothing') == '' and
                paths.get_face_data_path('nothing') == '')

    # ---------------------------------------------------------------- #
    # A project
    # ---------------------------------------------------------------- #
    project_root = os.path.join(temp, 'Wayward')
    os.environ[consts.MCA_PROJECT_ROOT] = project_root
    os.environ[consts.MCA_COMMON_TOOLS] = os.path.join(project_root, 'Tools', 'Common', 'Tools')
    os.environ[consts.MCA_CHARACTERS_PATH] = os.path.join(temp, 'art', 'Characters')
    os.environ[consts.MCA_ICONS_PATH] = os.path.join(temp, 'resources', 'icons')

    suite.check('the project root is read now, not remembered from when the module was '
                'imported', paths.project_root() == os.path.normpath(project_root),
                paths.project_root())
    suite.check('the shared tools folder hangs off it',
                paths.get_common_tools_path() ==
                os.path.normpath(os.path.join(project_root, 'Tools', 'Common', 'Tools')),
                paths.get_common_tools_path())
    suite.check('and so do the asset lists',
                paths.get_asset_list_file_path().endswith(
                    os.path.join('Assetlist', 'Assetlists', 'assetlist.alist')),
                paths.get_asset_list_file_path())
    suite.check('the characters folder is what the project said',
                paths.get_characters_path() ==
                os.path.normpath(os.path.join(temp, 'art', 'Characters')),
                paths.get_characters_path())

    # This one read the import-time snapshot, in a module whose own comment two functions
    # above explained why that was wrong.
    os.environ[consts.MCA_PROJECT_ROOT] = os.path.join(temp, 'Another')
    suite.check('changing project is seen by the cinematics folder as well',
                paths.get_cine_path().endswith(os.path.join('Another', 'Cinematics')),
                paths.get_cine_path())
    os.environ[consts.MCA_PROJECT_ROOT] = project_root

    suite.check('a sequence folder can be asked for with or without its cinematic',
                paths.get_cine_seq_dir('INTRO_A1').endswith(
                    os.path.join('Sequences', 'INTRO_A1')) and
                paths.get_cine_seq_dir('INTRO_A1', 'Opening').endswith(
                    os.path.join('Sequences', 'Opening', 'INTRO_A1')),
                paths.get_cine_seq_dir('INTRO_A1', 'Opening'))
    suite.check('and one with no project answers empty rather than a path to nowhere',
                (os.environ.pop(consts.MCA_PROJECT_ROOT, None) or True) and
                paths.get_cine_seq_dir('INTRO_A1') == '')
    os.environ[consts.MCA_PROJECT_ROOT] = project_root

    # ---------------------------------------------------------------- #
    # A tool's preferences folder, which is a get that makes a folder
    # ---------------------------------------------------------------- #
    folder = paths.get_local_tools_prefs_folder('maya', 'toolbox')
    suite.check('asking for a tool\'s preferences folder creates it, as it always did',
                folder and os.path.isdir(folder), str(folder))
    suite.check('and it can be asked for without creating anything',
                paths.get_local_tools_prefs_folder('maya', 'not_made', create=False) and
                not os.path.isdir(paths.get_local_tools_prefs_folder(
                    'maya', 'not_made', create=False)))

    # ---------------------------------------------------------------- #
    # Which application is this
    # ---------------------------------------------------------------- #
    suite.check('a plain Python is standalone', dcc_util.application() == dcc_util.Dccs.Standalone,
                dcc_util.application())

    # The spelling: application() answered 'Maya' and 'Mobu' while every constant, the boot
    # config and the start-up scripts said 'maya' and 'mobu'.
    suite.check('Maya is recognised by its executable, and called what everything else '
                'calls it',
                dcc_util.application(r'C:\Program Files\Autodesk\Maya2025\bin\maya.exe') ==
                dcc_util.Dccs.Maya,
                dcc_util.application(r'C:\Program Files\Autodesk\Maya2025\bin\maya.exe'))
    suite.check('mayapy counts as Maya',
                dcc_util.application(r'C:\Maya2025\bin\mayapy.exe') == dcc_util.Dccs.Maya and
                dcc_util.is_mayapy(r'C:\Maya2025\bin\mayapy.exe'))
    suite.check('and so does Maya batch',
                dcc_util.is_maya_batch(r'C:\Maya2025\bin\mayabatch.exe'))
    suite.check('MotionBuilder is mobu, the same word the boot config uses',
                dcc_util.application(r'C:\MotionBuilder 2024\bin\x64\motionbuilder.exe') ==
                dcc_util.Dccs.MotionBuilder)
    suite.check('mobupy counts as MotionBuilder',
                dcc_util.application(r'C:\MotionBuilder 2024\bin\x64\mobupy.exe') ==
                dcc_util.Dccs.MotionBuilder)
    suite.check('UnrealEditor.exe is Unreal - the table named UE4Editor.exe, which no '
                'machine has run for years',
                dcc_util.application(r'C:\UE_5.5\Engine\Binaries\Win64\UnrealEditor.exe') ==
                dcc_util.Dccs.Unreal)
    suite.check('and something unrecognisable is standalone rather than a guess',
                dcc_util.application(r'C:\Python310\python.exe') == dcc_util.Dccs.Standalone)

    suite.check('there is a name for a person to read',
                dcc_util.display_name(dcc_util.Dccs.MotionBuilder) == 'MotionBuilder',
                dcc_util.display_name(dcc_util.Dccs.MotionBuilder))
    suite.check('every DCC has a port of its own, so two open at once do not fight',
                len(set(dcc_util.Dccs.ports.values())) == len(dcc_util.Dccs.ports))
    suite.check('asking a DCC that is not here for its version answers empty rather than '
                'raising', dcc_util.application_version(dcc_util.Dccs.Maya) == '')

    # is_in_blender was written `except ImportError or AttributeError`, which catches only
    # ImportError - and answered None rather than False.
    suite.check('the Blender check answers a bool, either way',
                dcc_util.is_in_blender() is False and
                dcc_util.is_in_blender(r'C:\Blender\blender.exe') is True)

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('project_paths', body))
