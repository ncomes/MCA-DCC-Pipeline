"""
The asset registry's write layer: one asset, and one category's file.

    python tests/test_asset_registry.py
"""

# python imports
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import sourcecontrol  # noqa: E402
from mca.common.assetlist import asset_paths, unified_entry, unified_registry  # noqa: E402
from mca.common.sourcecontrol import base as sc_base  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import alistio  # noqa: E402


class Recording(sc_base.NoSourceControl):
    """A backend that writes nothing anywhere and remembers what it was asked to do."""

    name = 'recording'
    placeholder_name = '.keep'

    def __init__(self):
        self.checked_out = []
        self.added = []

    def available(self):
        return True

    def checkout(self, paths, changelist=''):
        self.checked_out.extend(sc_base.as_paths(paths))
        return sc_base.Result(True)

    def add(self, paths, changelist=''):
        self.added.extend(sc_base.as_paths(paths))
        return sc_base.Result(True)


def body(suite):
    project = os.path.join(suite.temp, 'project')
    assetlists = os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist', 'Assetlists')
    os.makedirs(assetlists)
    os.environ[consts.MCA_PROJECT_ROOT] = project
    recording = Recording()
    sourcecontrol.use(recording)
    asset_paths.reload()

    # ---------------------------------------------------------------- #
    # an asset id that cannot collide
    # ---------------------------------------------------------------- #
    # Ids are unique across the whole registry, not per category, and names repeat across
    # categories - an outfit set has a Pirate body, a Pirate hat and Pirate shoes.
    suite.check('an asset id carries its category, so the same name in two categories is two '
                'assets',
                unified_entry.build_asset_id('Hats', 'Pirate') == 'hats_pirate' and
                unified_entry.build_asset_id('Shoes', 'Pirate') == 'shoes_pirate')
    # Spaces and dashes become underscores; anything else punctuation simply goes, and runs
    # of underscores collapse. Deliberate: the ids already in the registry read this way, and
    # an id is written into the Maya scenes that reference the asset, so what a new one looks
    # like is not a free choice.
    suite.check('spaces and dashes become underscores, other punctuation goes, and runs collapse',
                unified_entry.build_asset_id('Characters', 'Hero-Bot  Mk.II') ==
                'characters_hero_bot_mkii',
                unified_entry.build_asset_id('Characters', 'Hero-Bot  Mk.II'))
    suite.check('and with only one of the two there is still an id',
                unified_entry.build_asset_id('', 'Pirate') == 'pirate' and
                unified_entry.build_asset_id('Hats', '') == 'hats')

    suite.check('an entry is recognised as this format by the fields only it has',
                unified_entry.is_unified_format({'asset_type': 'SkeletalMesh'}) and
                unified_entry.is_unified_format({'slot': 'Chest'}) and
                not unified_entry.is_unified_format({'name': 'Hero'}) and
                not unified_entry.is_unified_format(None))

    # ---------------------------------------------------------------- #
    # where an asset's folder goes
    # ---------------------------------------------------------------- #
    suite.check('a parent asset\'s path is its category, its classification, then its name',
                unified_entry.build_asset_path('Characters', subtype='Heroes', faction='Agents',
                                               asset_name='Hero Bot') ==
                'Characters/Heroes/Agents/Hero Bot',
                unified_entry.build_asset_path('Characters', subtype='Heroes', faction='Agents',
                                               asset_name='Hero Bot'))
    suite.check('a subtype of Default says nothing, as it always has',
                unified_entry.build_asset_path('Props', subtype='Default', asset_name='Crate') ==
                'Props/Crate')
    suite.check('gear starts under the gear root, however many folders deep that is',
                unified_entry.build_asset_path('Hats', asset_name='Pirate', is_gear=True) ==
                'Gear/Hats/Pirate' and
                unified_entry.build_asset_path('Hats', asset_name='Pirate', is_gear=True,
                                               gear_root='Characters/Gear') ==
                'Characters/Gear/Hats/Pirate')
    suite.check('a field can be left out of the path',
                unified_entry.build_asset_path('Characters', subtype='Heroes', faction='Agents',
                                               asset_name='Hero Bot',
                                               path_flags={'include_faction': False}) ==
                'Characters/Heroes/Hero Bot')
    suite.check('and the order they appear in can be changed',
                unified_entry.build_asset_path('Characters', subtype='Heroes', faction='Agents',
                                               asset_name='Hero Bot',
                                               path_order=['faction', 'subtype']) ==
                'Characters/Agents/Heroes/Hero Bot')
    # A partial or stale order must never silently drop a field that is switched on.
    suite.check('an order that has forgotten a field still uses that field',
                unified_entry.build_asset_path('Characters', subtype='Heroes', faction='Agents',
                                               asset_name='Hero Bot',
                                               path_order=['faction']) ==
                'Characters/Agents/Heroes/Hero Bot')
    suite.check('extra types nest inside, and can be switched off with everything else',
                unified_entry.build_asset_path('Weapons', asset_name='Cutlass',
                                               additional_types=['Melee', 'OneHanded']) ==
                'Weapons/Melee/OneHanded/Cutlass')

    # -- reading the flags back out of a path that predates them ------ #
    flags, order = unified_entry.derive_path_flags_and_order(
        {'category': 'Characters', 'subtype': 'Heroes', 'faction': 'Agents',
         'path': 'Characters/Agents/Heroes/Hero Bot'})
    suite.check('an old entry\'s path says which fields it used, and in which order',
                order[:2] == ['faction', 'subtype'] and
                flags['include_faction'] and flags['include_subtype'],
                str(order))
    suite.check('and a field the path never used is still listed, switched off',
                'skeleton' in order and flags['include_skeleton'] is False)
    flags, order = unified_entry.derive_path_flags_and_order({'category': 'Characters'})
    suite.check('an entry with no path yet keeps the defaults rather than clearing everything',
                flags == unified_entry.DEFAULT_PATH_FLAGS and
                order == unified_entry.DEFAULT_PATH_ORDER)
    flags, order = unified_entry.derive_path_flags_and_order(
        {'category': 'Hats', 'subtype': 'Main', 'path': 'Characters/Gear/Hats/Main/Pirate'})
    suite.check('a gear root of any depth is stepped over on the way',
                flags['include_subtype'] and order[0] == 'subtype', str(order))

    # ---------------------------------------------------------------- #
    # the engine path that had a project's name written into it
    # ---------------------------------------------------------------- #
    was = os.environ.pop(unified_entry.ENGINE_ROOT_VARIABLE, None)
    try:
        suite.check('with nothing set, an engine path is just Unreal\'s content root',
                    unified_entry.build_engine_path('Characters/Hero') == '/Game/Characters/Hero',
                    unified_entry.build_engine_path('Characters/Hero'))
        os.environ[unified_entry.ENGINE_ROOT_VARIABLE] = 'SampleGame'
        suite.check('a project names its own folder under it, rather than editing the code',
                    unified_entry.build_engine_path('Characters/Hero') ==
                    '/Game/SampleGame/Characters/Hero',
                    unified_entry.build_engine_path('Characters/Hero'))
        os.environ[unified_entry.ENGINE_ROOT_VARIABLE] = '/Game/SampleGame/'
        suite.check('however it is written',
                    unified_entry.build_engine_path('Characters/Hero') ==
                    '/Game/SampleGame/Characters/Hero')
        suite.check('and a path that is already an engine path is left alone',
                    unified_entry.build_engine_path('/Game/somewhere/else') ==
                    '/Game/somewhere/else' and
                    unified_entry.build_engine_path('') == '')
    finally:
        os.environ.pop(unified_entry.ENGINE_ROOT_VARIABLE, None)
        if was is not None:
            os.environ[unified_entry.ENGINE_ROOT_VARIABLE] = was

    # ---------------------------------------------------------------- #
    # making an asset
    # ---------------------------------------------------------------- #
    hero = unified_entry.UnifiedAssetEntry.create('Hero Bot', 'Characters', subtype='Heroes',
                                                  faction='Agents', skeleton='SampleBot')
    suite.check('a new asset gets an id, a path and an engine path without being told any',
                hero.asset_id == 'characters_hero_bot' and
                hero.path == 'Characters/Heroes/Agents/Hero Bot' and
                hero.engine_path.endswith('Characters/Heroes/Agents/Hero Bot'),
                '{0} | {1}'.format(hero.asset_id, hero.path))
    suite.check('and the fields it was given',
                hero.name == 'Hero Bot' and hero.subtype == 'Heroes' and
                hero.faction == 'Agents' and hero.skeleton == 'SampleBot' and
                hero.asset_type == 'SkeletalMesh')
    suite.check('it is not gear, and has no parent',
                hero.is_gear is False and hero.is_parent is True and hero.built_for == '')

    # built_for is one name or several; the stored shape stays a plain string for one, so a
    # single-parent entry is byte-identical to how it has always looked.
    hat = unified_entry.UnifiedAssetEntry.create('Pirate Hat', 'Hats', slot='Hat',
                                                 built_for='Hero Bot')
    suite.check('gear worn by one character stores that one name as a string',
                hat.built_for == 'Hero Bot' and hat.built_for_all == ['Hero Bot'])
    suite.check('and it is gear because something wears it, so its path starts at the gear root',
                hat.is_gear and hat.path.startswith('Gear/'), hat.path)
    shared = unified_entry.UnifiedAssetEntry.create('Shared Cloak', 'Outfits',
                                                    built_for=['Hero Bot', 'Villain Bot'])
    suite.check('gear worn by several stores a list of them',
                shared.built_for_all == ['Hero Bot', 'Villain Bot'])
    suite.check('and one can be added or taken away',
                shared.add_built_for('Third Bot') and
                shared.remove_built_for('Villain Bot') and
                sorted(shared.built_for_all) == ['Hero Bot', 'Third Bot'],
                str(shared.built_for_all))

    # -- an entry written before the path flags existed --------------- #
    old = unified_entry.UnifiedAssetEntry({'characters_old': {
        'name': 'Old Bot', 'category': 'Characters', 'faction': 'Agents',
        'path': 'Characters/Agents/Old Bot'}})
    suite.check('an entry from before the path fields existed is given them, read from its path',
                old.path_flags['include_faction'] and old.path_order[0] == 'faction',
                str(old.path_order))
    suite.check('and they are written into the entry, so they are saved with it',
                'path_flags' in old.fields and 'path_order' in old.fields)

    # -- the dye fields backfilled ------------------------------------ #
    dyed = unified_entry.UnifiedAssetEntry({'characters_dyed': {
        'name': 'Dyed Bot', 'category': 'Characters',
        'materials': [{'index': 0, 'slot_name': 'Body'}, {'index': 1, 'slot_name': 'Trim'}],
        'dyes': [{'index': 0, 'slot_name': 'Body'}]}})
    suite.check('a material with a dye row is marked as dye-able, and one without is not',
                dyed.materials[0].get('is_dye') is True and
                dyed.materials[1].get('is_dye') is False)
    suite.check('and every dye row has a channel list to fill in',
                dyed.dyes[0].get('channels') == [])

    # ---------------------------------------------------------------- #
    # which files are an asset's
    # ---------------------------------------------------------------- #
    asset_folder = os.path.join(project, hero.path.replace('/', os.sep))
    source_rigs = os.path.join(asset_folder, '_Source', 'Rigs')
    os.makedirs(source_rigs)

    suite.check('an asset\'s folders are the ones its category says it has',
                hero.get_required_path('SRC_RIGS_PATH') == os.path.normpath(source_rigs),
                hero.get_required_path('SRC_RIGS_PATH'))
    nowhere = unified_entry.UnifiedAssetEntry({'x': {'name': 'Nowhere', 'category': 'Characters'}})
    suite.check('an asset with no path answers nothing rather than None',
                nowhere.get_required_path('SRC_RIGS_PATH') == '')
    unknown = unified_entry.UnifiedAssetEntry({'y': {'name': 'Odd', 'category': 'Unheardof',
                                                     'path': 'Unheardof/Odd'}})
    suite.check('and so does one in a category the project has never heard of',
                unknown.get_required_path('SRC_RIGS_PATH') == '')

    suite.check('a file kind nobody has heard of is refused',
                bool(suite.raises('an unknown file kind raises', hero.set_file, 'blueprint', 'x')))

    rig_file = os.path.join(source_rigs, 'hero_bot_rig.ma')
    with open(rig_file, 'w', encoding='utf-8') as opened:
        opened.write('//')
    suite.check('nothing recorded and one file on disk is a file found',
                hero.file_status('rig')[0] == unified_entry.FILE_INFERRED and
                hero.resolve_file('rig') == rig_file,
                str(hero.file_status('rig')))

    stored = hero.set_file('rig', rig_file)
    suite.check('recording a file inside the asset stores it relative to the asset, so moving '
                'the asset does not break it',
                stored == '_Source/Rigs/hero_bot_rig.ma', stored)
    suite.check('and it reads back as recorded',
                hero.file_status('rig')[0] == unified_entry.FILE_RECORDED and
                hero.resolve_file('rig') == rig_file)

    outside = os.path.join(suite.temp, 'elsewhere', 'hero_bot.fbx')
    os.makedirs(os.path.dirname(outside), exist_ok=True)
    with open(outside, 'w', encoding='utf-8') as opened:
        opened.write('')
    hero.set_file('mesh', outside)
    suite.check('a file outside the asset is kept as given rather than as ../../..',
                not hero.get_file('mesh').startswith('..'), hero.get_file('mesh'))

    second = os.path.join(source_rigs, 'hero_bot_spare_rig.ma')
    with open(second, 'w', encoding='utf-8') as opened:
        opened.write('//')
    suite.check('with two on disk and one recorded, the recorded one still wins',
                hero.resolve_file('rig') == rig_file)
    hero.remove_file('rig')
    suite.check('with two on disk and nothing recorded, it says it is guessing',
                hero.file_status('rig')[0] == unified_entry.FILE_AMBIGUOUS)
    hero.set_file('rig', os.path.join(source_rigs, 'gone_rig.ma'))
    suite.check('a recorded file that is not there any more is stale, and falls back to disk',
                hero.file_status('rig')[0] == unified_entry.FILE_STALE and
                hero.resolve_file('rig') in (rig_file, second))
    suite.check('and a kind with nothing recorded and nothing on disk is simply missing',
                hero.file_status('skel')[0] == unified_entry.FILE_MISSING and
                hero.resolve_file('skel') == '')

    # Maya's incremental save writes a folder of numbered copies; scanning into it made one
    # asset look like it had a hundred rigs, and could answer with a week-old save.
    incremental = os.path.join(source_rigs, 'incrementalSave', 'hero_bot_rig.ma')
    os.makedirs(os.path.dirname(incremental), exist_ok=True)
    with open(incremental, 'w', encoding='utf-8') as opened:
        opened.write('//')
    suite.check('the folder of incremental saves is not where an asset\'s rig is looked for',
                incremental not in hero.file_candidates('rig'),
                str(hero.file_candidates('rig')))

    suite.check('the skeleton file is the conventional name when none is recorded',
                os.path.basename(hero.skel_path) == 'hero_bot.skl', hero.skel_path)
    skel_file = os.path.join(source_rigs, 'renamed.skl')
    with open(skel_file, 'w', encoding='utf-8') as opened:
        opened.write('')
    hero.set_file('skel', skel_file)
    suite.check('and the recorded one when there is, so a renamed skeleton stays findable',
                hero.skel_path == skel_file)

    # ---------------------------------------------------------------- #
    # the folders an asset needs
    # ---------------------------------------------------------------- #
    recording.checked_out = []
    recording.added = []
    placeholders = hero.create_folders()
    suite.check('an asset\'s folders are made where the asset is',
                os.path.isdir(os.path.join(asset_folder, 'Meshes')) and
                os.path.isdir(os.path.join(asset_folder, 'Textures')),
                str(sorted(os.listdir(asset_folder))))
    suite.check('they come from the category, not a list written into the code',
                set(os.listdir(asset_folder)) >=
                {'Meshes', 'Textures', 'Animations', 'Rigs', '_Source'},
                str(sorted(os.listdir(asset_folder))))
    suite.check('source control is asked to check them out',
                bool(recording.checked_out))
    # Perforce and Git version files, not folders, so an empty folder cannot be stored.
    suite.check('and every folder still empty is given something to store',
                placeholders and all(path.endswith('.keep') for path in placeholders),
                str(placeholders))
    suite.check('which are marked for adding, since they are new files',
                set(placeholders) <= set(recording.added))
    suite.check('the folder that already had the rig in it is left without one',
                not os.path.isfile(os.path.join(source_rigs, '.keep')))

    # ---------------------------------------------------------------- #
    # one category's file
    # ---------------------------------------------------------------- #
    suite.check('a category with no file is nothing, unless the caller is making one',
                unified_registry.UnifiedAssetRegistry.load('Characters') is None and
                len(unified_registry.UnifiedAssetRegistry.load('Characters', create=True)) == 0)

    registry = unified_registry.UnifiedAssetRegistry(category_name='Characters')
    registry.add_asset_entry(hero)
    registry.add_asset_entry(old)
    recording.added = []
    recording.checked_out = []
    written = registry.save()
    suite.check('saving a category writes its file', os.path.isfile(written), written)
    with open(written, encoding='utf-8') as opened:
        suite.check('as JSON, whatever the extension suggests',
                    isinstance(json.loads(opened.read()), dict))
    # save() wrote the file and then asked whether it existed before adding it - after writing
    # it, so the answer was always no and a new registry file was never added.
    suite.check('and a file that did not exist before is added to source control',
                written in recording.added, str(recording.added))

    recording.added = []
    recording.checked_out = []
    registry.save()
    suite.check('saving it again checks the existing file out rather than adding it',
                written in recording.checked_out and written not in recording.added)

    # An empty registry file is a category with no assets yet, which is exactly what a new
    # category has - the version this replaces read it as no file at all.
    empty_file = os.path.join(assetlists, 'Empty.alist')
    alistio.write_alist_file({}, empty_file, fmt='json')
    empty = unified_registry.UnifiedAssetRegistry.load('Empty')
    suite.check('a category whose file has no assets in it is still a category',
                empty is not None and len(empty) == 0 and empty.category == 'Empty')
    suite.check('so the first asset can be put into it',
                empty.add_asset_entry(hat) and len(empty) == 1)

    loaded = unified_registry.UnifiedAssetRegistry.load('Characters')
    suite.check('a saved category reads back with its assets',
                sorted(loaded.get_all_asset_names()) == ['Hero Bot', 'Old Bot'],
                str(loaded.get_all_asset_names()))
    suite.check('and each one is found by id or by name',
                loaded.get_asset_entry('characters_hero_bot') is not None and
                loaded.get_asset_entry_by_name('Old Bot') is not None and
                loaded.get_asset_entry('nothing', skip_dialog=True) is None)

    # Every add and remove rebuilt every entry in the category, so a caller holding one was
    # left editing an object the registry no longer knew about - and save() writes what the
    # registry knows about.
    held = loaded.get_asset_entry('characters_hero_bot')
    loaded.add_asset_entry(shared)
    suite.check('adding an asset does not replace the entry objects already handed out',
                loaded.get_asset_entry('characters_hero_bot') is held)
    held.description = 'The one the artists actually edited'
    loaded.save()
    suite.check('so an edit made through a held entry is in the file afterwards',
                unified_registry.UnifiedAssetRegistry.load('Characters')
                .get_asset_entry('characters_hero_bot').description ==
                'The one the artists actually edited')

    suite.check('an asset can be taken out again',
                loaded.remove_asset_entry('characters_old') and
                loaded.remove_asset_entry('characters_old') is False and
                'Old Bot' not in loaded.get_all_asset_names())

    # -- a registry with nothing to name its file --------------------- #
    nameless = unified_registry.UnifiedAssetRegistry()
    suite.check('a registry that does not know its category refuses to save rather than '
                'writing a file called ".alist"',
                nameless.save() == '')

    # -- one broken asset does not cost the category ------------------ #
    broken_file = os.path.join(assetlists, 'Broken.alist')
    alistio.write_alist_file({'good': {'name': 'Fine', 'category': 'Broken'},
                              'bad': 'not an asset at all'}, broken_file, fmt='json')
    broken = unified_registry.UnifiedAssetRegistry.load('Broken')
    suite.check('an asset that cannot be read is stepped over, and the rest of the category '
                'still loads',
                broken is not None and broken.get_all_asset_names() == ['Fine'],
                str(broken and broken.get_all_asset_names()))

    # -- taking an asset out of its own category ---------------------- #
    suite.check('an asset can remove itself from its category\'s file',
                loaded.get_asset_entry('characters_hero_bot').remove_from_assetlist() and
                unified_registry.UnifiedAssetRegistry.load('Characters')
                .get_asset_entry('characters_hero_bot', skip_dialog=True) is None)
    suite.check('and one whose category has no file says so rather than raising',
                unknown.remove_from_assetlist() is False)

    sourcecontrol.reset()
    suite.note('entries written', len(loaded))


if __name__ == '__main__':
    sys.exit(harness.run('asset_registry', body))
