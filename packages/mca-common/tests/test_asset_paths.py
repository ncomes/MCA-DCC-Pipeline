"""
The asset registry's foundation: the framework's templates, a project's category file, and
what every asset record has.

    python tests/test_asset_paths.py

Needs no Qt, which is the point of one of the fixes: the version this replaces imported
``common_windows`` at the top of ``asset_paths`` and never used it, so the registry could not
be read at all without PySide.
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.assetlist import asset_list, asset_path_config, asset_paths, asset_prefixes  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import yamlio  # noqa: E402


class Entry(asset_list.AssetBaseEntry):
    """The smallest concrete record: folders come from the asset's own path."""

    FOLDERS = {
        'RIGS_PATH': 'Rigs',
        'MODELS_PATH': 'Meshes',
        'TEXTURES_PATH': 'Textures',
        'SRC_RIGS_PATH': os.path.join('_Source', 'Rigs'),
        'SRC_MODELS_PATH': os.path.join('_Source', 'Meshes'),
        'SRC_ANIMATIONS_PATH': os.path.join('_Source', 'Animations'),
    }

    def get_required_path(self, path_name):
        folder = self.FOLDERS.get(path_name, '')
        if not folder or not self.path:
            return ''
        return os.path.normpath(os.path.join(self.path, folder))

    def remove_from_assetlist(self):
        return True


def body(suite):
    # ---------------------------------------------------------------- #
    # the framework's own templates
    # ---------------------------------------------------------------- #
    suite.check('the folder names come out of the templates file',
                asset_path_config.folder_names().get('source') == '_Source' and
                asset_paths.MODELS_FOLDER == 'Meshes' and
                asset_paths.FLAGS_FOLDER == 'Flags')
    required = asset_path_config.required_paths()
    suite.check('and so do the folders every asset has',
                sorted(required) == ['ANIMATIONS_PATH', 'FLAGS_PATH', 'MODELS_PATH', 'RIGS_PATH',
                                     'SRC_ANIMATIONS_PATH', 'SRC_MODELS_PATH', 'SRC_RIGS_PATH',
                                     'TEXTURES_PATH'],
                str(sorted(required)))

    seeded = asset_path_config.seed_categories()
    # The old seeding code listed seven categories in Python while the same YAML file declared
    # eight, so a fresh checkout came up with no Faces category - which every real project has.
    suite.check('a new project is seeded with Faces, which the old seed left out',
                'Faces' in seeded, str(sorted(seeded)))
    suite.check('and the gear categories are marked as gear in the one place that says so',
                seeded.get('Outfits', {}).get('is_gear') is True)
    suite.check('reading the templates again is allowed and answers the same thing',
                asset_path_config.reload().get('version') == asset_path_config.get_config().get('version'))

    # ---------------------------------------------------------------- #
    # a typed gear root
    # ---------------------------------------------------------------- #
    suite.check('a gear root is tidied however it was typed',
                asset_paths.normalize_gear_root('Gear\\') == 'Gear' and
                asset_paths.normalize_gear_root(' /Gear/ ') == 'Gear' and
                asset_paths.normalize_gear_root('Characters\\Gear') == 'Characters/Gear' and
                asset_paths.normalize_gear_root('./') == '' and
                asset_paths.normalize_gear_root(None) == '')

    # ---------------------------------------------------------------- #
    # one category
    # ---------------------------------------------------------------- #
    category = asset_paths.CategoryData({'Characters': asset_paths.new_category_block(
        subcategories=['NPCs', 'Heroes'])})
    suite.check('a category knows its own name without looking it up again every time',
                category.category == 'Characters')
    suite.check('its subcategories come back sorted',
                category.subcategories == ['Heroes', 'NPCs'], str(category.subcategories))
    suite.check('it is not gear, and still answers where gear would go',
                category.is_gear is False and category.gear_root == 'Gear')

    # add_faction read the list and called .append on the list the file holds - past the
    # setter that sorts - and on a category with no FACTIONS key at all it appended to a
    # throwaway list, so the faction was silently lost.
    bare = asset_paths.CategoryData({'Creatures': {}})
    suite.check('adding a faction to a category that has none keeps it',
                bare.add_faction('Gilded') and bare.factions == ['Gilded'],
                str(bare.factions))
    suite.check('and it lands in the dictionary the file holds, not a copy',
                bare.category_dict['Creatures'][asset_paths.FACTIONS_KEY] == ['Gilded'])
    suite.check('adding it twice is not an error and does not duplicate it',
                bare.add_faction('Gilded') is False and bare.factions == ['Gilded'])
    suite.check('they stay sorted as they go in',
                bare.add_faction('Agents') and bare.factions == ['Agents', 'Gilded'],
                str(bare.factions))
    suite.check('and one can be taken away again',
                bare.remove_faction('Agents') and bare.factions == ['Gilded'] and
                bare.remove_faction('Agents') is False)
    suite.check('subcategories and additional types work the same way',
                bare.add_subcategory('Wolves') and bare.subcategories == ['Wolves'] and
                bare.add_additional_type('Material') and bare.additional_types == ['Material'])

    # ---------------------------------------------------------------- #
    # the substring match that could resolve every rig to the source folder
    # ---------------------------------------------------------------- #
    # get_required_path answered the first key that *contained* what was asked for, in
    # whatever order the file listed them. It gave the right answer for RIGS_PATH only
    # because RIGS_PATH happens to be written before SRC_RIGS_PATH.
    reordered = asset_paths.CategoryData({'Characters': {asset_paths.REQUIRED_KEY: {
        'SRC_RIGS_PATH': '_Source/Rigs',
        'RIGS_PATH': 'Rigs',
    }}})
    suite.check('asking for the rigs folder answers the rigs folder, whatever order the file '
                'lists the keys in',
                reordered.get_required_path('RIGS_PATH') == 'Rigs',
                reordered.get_required_path('RIGS_PATH'))
    suite.check('and asking for the source rigs folder still answers that',
                reordered.get_required_path('SRC_RIGS_PATH') == '_Source/Rigs')
    suite.check('a partial name is still answered, for the tools that ask that way',
                reordered.get_required_path('MODELS') == '' and
                asset_paths.CategoryData({'C': {asset_paths.REQUIRED_KEY: {
                    'MODELS_PATH': 'Meshes'}}}).get_required_path('MODELS') == 'Meshes')
    suite.check('and a category with no folders at all answers nothing rather than raising '
                'KeyError',
                asset_paths.CategoryData({'Empty': {}}).get_required_path('RIGS_PATH') == '')

    category.rig_folder = 'BuiltRigs'
    suite.check('a folder can be moved, and reads back where it was moved to',
                category.rig_folder == 'BuiltRigs' and
                category.required_paths['RIGS_PATH'] == 'BuiltRigs')
    suite.check('and the rest of them round-trip too',
                all(getattr(category, name) for name in
                    ('mesh_folder', 'textures_folder', 'animations_folder', 'src_mesh_folder',
                     'src_animations_folder')))

    # ---------------------------------------------------------------- #
    # what every category shares
    # ---------------------------------------------------------------- #
    globals_block = asset_paths.GlobalData()
    suite.check('a skeleton can be registered, and they come back sorted',
                globals_block.add_skeleton('WaywardBot') and globals_block.add_skeleton('SKEL_Props') and
                globals_block.skeletons == ['SKEL_Props', 'WaywardBot'],
                str(globals_block.skeletons))
    suite.check('a body type names a skeleton, and registers it if it is new',
                globals_block.add_body_type('ZLeg', 'SKEL_ZLeg') and
                globals_block.body_types == {'ZLeg': 'SKEL_ZLeg'} and
                'SKEL_ZLeg' in globals_block.skeletons)
    suite.check('and taking the skeleton away takes the body types that used it',
                globals_block.remove_skeleton('SKEL_ZLeg') and globals_block.body_types == {})
    suite.check('slots, sockets and asset types are lists like any other',
                globals_block.add_slot('Head') and globals_block.add_attach_socket('weapon_r') and
                globals_block.add_asset_type('SkeletalMesh') and
                globals_block.slots == ['Head'] and globals_block.attach_sockets == ['weapon_r'] and
                globals_block.asset_types == ['SkeletalMesh'])

    # ---------------------------------------------------------------- #
    # the project's file
    # ---------------------------------------------------------------- #
    project = os.path.join(suite.temp, 'project')
    assetlist_folder = os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist')
    os.makedirs(assetlist_folder)
    os.environ[consts.MCA_PROJECT_ROOT] = project
    os.environ[sys.modules['mca.common.sourcecontrol'].VARIABLE] = 'none'
    sys.modules['mca.common.sourcecontrol'].reset()

    # The constructor popped '_Global' out of the dictionary it was handed, so the caller's
    # own copy of the file quietly lost its global block.
    handed = {'_Global': {'SLOTS': ['Head']}, 'Characters': asset_paths.new_category_block()}
    data = asset_paths.AssetDictData(handed)
    suite.check('reading the file does not take the global block out of the caller\'s copy',
                '_Global' in handed, str(sorted(handed)))
    suite.check('and the categories are what is left',
                data.categories_names == ['Characters'] and data.global_data.slots == ['Head'])

    live = data.get_category_data('Characters')
    live.add_subcategory('Heroes')
    suite.check('a category handed out is the one in the file, so changing it changes the file',
                data.asset_dict['Characters'][asset_paths.SUBCATEGORIES_KEY] == ['Heroes'])
    suite.check('a category that is not there answers None',
                data.get_category_data('Nothing') is None)

    # update_category rebuilt the whole dictionary from a list it had built earlier, so any
    # category added since was dropped on the floor.
    data.add_category('Creatures', subcategories=['Wolves'])
    suite.check('a category can be added', 'Creatures' in data.categories_names)
    suite.check('and adding it twice is refused rather than wiping the first',
                data.add_category('Creatures') is False)
    data.update_category(live)
    suite.check('putting one category back keeps the others',
                sorted(data.categories_names) == ['Characters', 'Creatures'],
                str(data.categories_names))
    suite.check('a category can be taken away again',
                data.remove_category('Creatures') and 'Creatures' not in data.categories_names)

    # -- on disk ------------------------------------------------------ #
    asset_paths.reload()
    loaded = asset_paths.AssetDictData.load()
    written = asset_paths.AssetDictData.file_path()
    suite.check('a project with no category file gets one, seeded from the framework',
                os.path.isfile(written), written)
    suite.check('with every seeded category in it, Faces included',
                'Faces' in loaded.categories_names, str(sorted(loaded.categories_names)))
    suite.check('and the global block written beside them',
                '_Global' in (yamlio.read_yaml_file(written) or {}))

    # unified_entry asks for this while working out one asset's folder, so the old version
    # parsed the whole YAML once per asset - hundreds of times to build a registry.
    suite.check('asking again answers the same object rather than reading the file again',
                asset_paths.AssetDictData.load() is loaded)

    on_disk = yamlio.read_yaml_file(written)
    on_disk['Characters'][asset_paths.FACTIONS_KEY] = ['EditedByHand']
    yamlio.write_to_yaml_file(on_disk, written)
    suite.check('so an edit made outside is not picked up until it is asked for',
                asset_paths.AssetDictData.load().get_category_data('Characters').factions == [])
    suite.check('and reloading picks it up',
                asset_paths.reload().get_category_data('Characters').factions == ['EditedByHand'])

    # A category added to the framework after a project's file was written has to be put into
    # it, or it only ever shows up on a fresh checkout.
    trimmed = yamlio.read_yaml_file(written)
    trimmed.pop('Faces')
    yamlio.write_to_yaml_file(trimmed, written)
    suite.check('a category the project has not got yet is added to its file',
                'Faces' in asset_paths.reload().categories_names)
    suite.check('and what was already there is left exactly as the artists edited it',
                asset_paths.AssetDictData.load().get_category_data('Characters').factions ==
                ['EditedByHand'])

    with open(written, 'w', encoding='utf-8') as opened:
        opened.write('this is not: yaml: at all: ]\n')
    suite.check('a file that cannot be read falls back to the framework\'s categories rather '
                'than raising into whatever asked',
                'Characters' in asset_paths.reload().categories_names)

    os.environ.pop(consts.MCA_PROJECT_ROOT)
    asset_paths.reload()
    suite.check('and with no project at all there is still something to answer with',
                asset_paths.AssetDictData.load().categories_names and
                asset_paths.AssetDictData.load().save() is False)
    os.environ[consts.MCA_PROJECT_ROOT] = project
    asset_paths.reload()

    # ---------------------------------------------------------------- #
    # one asset's record
    # ---------------------------------------------------------------- #
    suite.check('a record with no id at all is refused',
                bool(suite.raises('an empty entry raises', Entry, {})))
    suite.check('and the abstract methods are abstract now, so a half-written entry type '
                'cannot be built',
                bool(suite.raises('the base class cannot be built', asset_list.AssetBaseEntry,
                                  {'id': {}})))

    entry = Entry({'a19f': {'name': 'Hero Bot', 'category': 'Characters',
                            'path': os.path.join('Characters', 'hero_bot')}})
    suite.check('a record knows its id, and does not go looking for it again',
                entry.asset_id == 'a19f' and entry.asset_dict['a19f'] is entry.fields)
    suite.check('a name becomes a file name the same way everywhere',
                entry.file_name == 'hero_bot')
    suite.check('its folders are built from where it lives',
                entry.models_path.endswith(os.path.join('hero_bot', 'Meshes')) and
                entry.flags_path.endswith(os.path.join('_Source', 'Rigs', 'Flags')),
                '{0} | {1}'.format(entry.models_path, entry.flags_path))

    # path and full_path answered None out of two properties documented to answer a string.
    nameless = Entry({'b20': {}})
    suite.check('an asset with no path answers nothing rather than None',
                nameless.path == '' and nameless.full_path == '' and nameless.models_path == '')
    suite.check('and one with no name has an empty file name rather than raising',
                nameless.file_name == '' and nameless.name == '')

    suite.check('its static and skeletal meshes are named by the convention',
                os.path.basename(entry.sm_path) == '{0}Hero Bot.fbx'.format(asset_prefixes.SM) and
                os.path.basename(entry.sk_path) == '{0}Hero Bot.fbx'.format(asset_prefixes.SK),
                entry.sm_path)

    # Both setters stored the value somewhere the getter never read.
    entry.sm_path = os.path.join(project, 'Characters', 'hero_bot', 'Meshes', 'SM_custom.fbx')
    suite.check('a mesh path that is set reads back as what it was set to',
                os.path.basename(entry.sm_path) == 'SM_custom.fbx', entry.sm_path)
    entry.sk_path = os.path.join(project, 'Characters', 'hero_bot', 'Meshes', 'SK_custom.fbx')
    suite.check('and so does the skeletal one',
                os.path.basename(entry.sk_path) == 'SK_custom.fbx', entry.sk_path)
    suite.check('the skinning file sits beside the static mesh',
                entry.skin_path.endswith('SM_custom_skn.fbx'), entry.skin_path)
    suite.check('and a mesh with nowhere to live answers nothing, not a broken path',
                nameless.sm_path == '' and nameless.sm_fullpath == '' and nameless.skin_path == '')

    # -- the folders it needs ----------------------------------------- #
    made = entry.create_folders()
    suite.check('making an asset\'s folders makes them where the asset is, not where the '
                'working directory happens to be',
                made and all(os.path.isdir(folder) for folder in made) and
                all(folder.startswith(project) for folder in made),
                str(made))
    suite.check('and making them again is not an error',
                len(entry.create_folders()) == len(made))
    suite.check('an asset with no path makes nothing rather than making it in the wrong place',
                nameless.create_folders() == [])

    # -- its rigs ----------------------------------------------------- #
    rigs_folder = entry.src_rig_path
    os.makedirs(rigs_folder, exist_ok=True)
    for name in ('hero_bot_rig.ma', 'hero_bot_notes.ma', 'other_thing_rig.ma'):
        with open(os.path.join(rigs_folder, name), 'w', encoding='utf-8') as opened:
            opened.write('//')
    found = entry.get_rig_list()
    suite.check('an asset\'s rigs are the rig files named after it',
                [os.path.basename(path) for path in found] == ['hero_bot_rig.ma'], str(found))

    suite.note('categories seeded', len(asset_path_config.seed_categories()))


if __name__ == '__main__':
    sys.exit(harness.run('asset_paths', body))
