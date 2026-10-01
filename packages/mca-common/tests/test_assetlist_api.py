"""
The flat asset API: what a script, an MCP tool or the in-DCC AI calls.

    python tests/test_assetlist_api.py

The contract is the thing being checked: every function answers
``{'ok': bool, 'result': ..., 'message': str}`` and never raises, and a failure message tells
a caller that cannot see the data what to do instead.
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import sourcecontrol  # noqa: E402
from mca.common.assetlist import asset_manager, asset_paths, assetlist_api, unified_registry  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import jsonio, yamlio  # noqa: E402


def make_project(temp):
    """
    A project with a category manifest and an empty Characters list.

    :param str temp: A folder to build it in.
    :return: The project root.
    :rtype: str
    """

    project = os.path.join(temp, 'project')
    assetlist = os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist')
    os.makedirs(os.path.join(assetlist, 'Assetlists'), exist_ok=True)
    jsonio.write_to_json_file(
        {'version': '2.0',
         'categories': [{'name': name, 'folder': 'Assetlists'}
                        for name in ('Characters', 'Heads', 'Outfits', 'Props')]},
        os.path.join(assetlist, 'categories.json'))

    os.environ[consts.MCA_PROJECT_ROOT] = project
    asset_paths.reload()

    # Give the project a vocabulary to check values against.
    config = asset_paths.AssetDictData.load()
    characters = config.get_category_data('Characters')
    characters.subcategories = ['Heroes', 'Enemies']
    characters.factions = ['Agents', 'Gilded']
    config.global_data.skeletons = ['SampleBot']
    config.global_data.asset_types = ['SkeletalMesh', 'StaticMesh']
    config.global_data.slots = ['Hat', 'Chest']
    config.global_data.add_body_type('Humanoid', 'SampleBot')
    config.save()
    asset_paths.reload()
    asset_manager.get_asset_manager(force_reload=True)

    return project


def body(suite):
    sourcecontrol.use('none')
    project = make_project(suite.temp)

    # ---------------------------------------------------------------- #
    # what a caller is told before it writes anything
    # ---------------------------------------------------------------- #
    answer = assetlist_api.list_categories()
    suite.check('every answer is the same shape: ok, result, message',
                sorted(answer) == ['message', 'ok', 'result'] and answer['ok'] is True,
                str(sorted(answer)))
    suite.check('the categories come with how many assets each holds',
                {'Characters', 'Outfits'} <=
                {entry['name'] for entry in answer['result']},
                str([entry['name'] for entry in answer['result']]))

    described = assetlist_api.describe_category('Characters')
    suite.check('a category describes its own vocabulary',
                described['ok'] and
                described['result']['subtypes'] == ['Enemies', 'Heroes'] and
                described['result']['factions'] == ['Agents', 'Gilded'],
                str(described['result'])[:200])
    schema = assetlist_api.describe_schema()
    suite.check('and the schema says what may be written, what may not, and how to use it',
                schema['ok'] and 'name' in schema['result']['writable'] and
                'asset_id' in schema['result']['read_only'] and schema['result']['notes'],
                str(sorted(schema['result'])))

    # A caller that cannot see the data has to be told what is valid.
    wrong = assetlist_api.describe_category('Charecters')
    suite.check('a category that does not exist is refused with the valid ones listed',
                wrong['ok'] is False and 'Characters' in wrong['message'], wrong['message'])
    suite.check('and a near miss is offered as a suggestion',
                'Did you mean' in wrong['message'], wrong['message'])

    # ---------------------------------------------------------------- #
    # registering
    # ---------------------------------------------------------------- #
    made = assetlist_api.register_asset('Hero Bot', 'Characters', subtype='Heroes',
                                        faction='Agents', skeleton='SampleBot',
                                        body_type='Humanoid')
    suite.check('an asset can be registered, and comes back described',
                made['ok'] and made['result']['asset_id'] == 'characters_hero_bot',
                made['message'])
    # The category had no .alist file at all: this is the first asset in it.
    suite.check('which writes the category\'s file even though there was none',
                os.path.isfile(os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist',
                                            'Assetlists', 'Characters.alist')))
    suite.check('and the asset is there to be read back',
                assetlist_api.get_asset('characters_hero_bot')['ok'] and
                assetlist_api.get_asset('Hero Bot')['ok'])

    suite.check('registering it twice is refused, and says what to do instead',
                assetlist_api.register_asset('Hero Bot', 'Characters')['ok'] is False and
                'update_asset' in
                assetlist_api.register_asset('Hero Bot', 'Characters')['message'])
    suite.check('an asset with no name is refused',
                assetlist_api.register_asset('', 'Characters')['ok'] is False)

    # A typo in a controlled field creates a second faction that then looks real to everyone
    # else, so it is refused rather than written.
    typo = assetlist_api.register_asset('Other Bot', 'Characters', faction='Agants')
    suite.check('a value outside the category\'s vocabulary is refused',
                typo['ok'] is False and 'Agents' in typo['message'], typo['message'])

    # But the config has drifted from the data on every real project, so a value that existing
    # assets already carry has to keep working.
    registry = unified_registry.UnifiedAssetRegistry.load('Characters')
    entry = registry.get_asset_entry('characters_hero_bot')
    entry.fields['faction'] = 'Undeclared'
    registry.save()
    assetlist_api.reload()
    drifted = assetlist_api.register_asset('Third Bot', 'Characters', faction='Undeclared')
    suite.check('a value existing assets already use is allowed, and reported as unconfigured',
                drifted['ok'] and 'asset_data.config' in drifted['message'], drifted['message'])

    # ---------------------------------------------------------------- #
    # reading
    # ---------------------------------------------------------------- #
    suite.check('assets can be listed, and narrowed by category',
                assetlist_api.list_assets(category='Characters')['ok'] and
                len(assetlist_api.list_assets(category='Characters')['result']) == 2,
                str(assetlist_api.list_assets(category='Characters')['result']))
    suite.check('and searched for by name',
                'characters_hero_bot' in
                [found['asset_id'] for found in assetlist_api.search_assets('hero')['result']])
    suite.check('counted, in total and by category',
                assetlist_api.get_asset_count()['result'] == 2 and
                assetlist_api.get_asset_count('Characters')['result'] == 2,
                str(assetlist_api.get_asset_count()['result']))
    paths_answer = assetlist_api.get_asset_paths('characters_hero_bot')
    suite.check('an asset\'s folders are reported as full paths',
                paths_answer['ok'] and
                paths_answer['result']['full_path'].startswith(project),
                str(paths_answer['result'])[:160])
    suite.check('an id nobody has is refused, with something to try instead',
                assetlist_api.get_asset('charcters_hero_bot')['ok'] is False and
                'Did you mean' in assetlist_api.get_asset('charcters_hero_bot')['message'])

    # ---------------------------------------------------------------- #
    # gear, and what belongs to what
    # ---------------------------------------------------------------- #
    hat = assetlist_api.register_asset('Pirate Hat', 'Outfits', slot='Hat',
                                       built_for='Hero Bot')
    suite.check('gear can be registered against the character that wears it',
                hat['ok'], hat['message'])
    children = assetlist_api.get_asset_children('characters_hero_bot')
    suite.check('and shows up as the character\'s',
                children['ok'] and 'Pirate Hat' in
                [found['name'] for found in children['result']],
                str(children['result']))
    hierarchy = assetlist_api.get_asset_hierarchy('outfits_pirate_hat')
    suite.check('an asset can say what it hangs off, from the top down to itself',
                hierarchy['ok'] and len(hierarchy['result']) == 2 and
                hierarchy['result'][-1]['asset_id'] == 'outfits_pirate_hat',
                str([level['asset_id'] for level in hierarchy['result']]))

    # ---------------------------------------------------------------- #
    # changing an asset
    # ---------------------------------------------------------------- #
    updated = assetlist_api.update_asset('characters_hero_bot',
                                         {'description': 'The one the artists use'})
    suite.check('a field can be changed, and is in the file afterwards',
                updated['ok'] and
                assetlist_api.get_asset('characters_hero_bot',
                                        verbose=True)['result']['description'] ==
                'The one the artists use',
                updated['message'])
    suite.check('changing the category is refused, since there is a function for that',
                assetlist_api.update_asset('characters_hero_bot',
                                           {'category': 'Props'})['ok'] is False)
    suite.check('a field nobody has heard of is refused by name',
                assetlist_api.update_asset('characters_hero_bot',
                                           {'colour': 'red'})['ok'] is False)
    suite.check('and changing nothing at all is refused',
                assetlist_api.update_asset('characters_hero_bot', {})['ok'] is False)

    # ---------------------------------------------------------------- #
    # moving an asset between categories
    # ---------------------------------------------------------------- #
    moved = assetlist_api.transfer_asset('Third Bot', 'Heads')
    suite.check('an asset can be moved to another category',
                moved['ok'] and
                assetlist_api.get_asset('characters_third_bot')['result']['category'] == 'Heads',
                moved['message'])
    suite.check('moving it where it already is is refused',
                assetlist_api.transfer_asset('characters_third_bot', 'Heads')['ok'] is False)

    # The version this replaces wrote the asset into its new category, then removed it from the
    # old one, and checked neither save - so a failure on the second left one id in two
    # categories, which the manager resolves by keeping whichever it loaded first.
    real_save = unified_registry.UnifiedAssetRegistry.save
    calls = {'n': 0}

    def failing_second_save(self, folder=''):
        calls['n'] += 1
        if calls['n'] == 1:
            return real_save(self, folder=folder)
        return ''

    unified_registry.UnifiedAssetRegistry.save = failing_second_save
    try:
        half = assetlist_api.transfer_asset('characters_hero_bot', 'Props')
    finally:
        unified_registry.UnifiedAssetRegistry.save = real_save
    suite.check('a move whose second half fails is reported as a failure, not a success',
                half['ok'] is False, half['message'])
    suite.check('and the message says the asset is now listed in both, and which to fix',
                'Characters' in half['message'] and
                'Two categories' in half['message'],
                half['message'])

    # Put it back the way it was, so the rest of the suite reads a sane registry.
    props = unified_registry.UnifiedAssetRegistry.load('Props')
    if props:
        props.remove_asset_entry('characters_hero_bot')
        props.save()
    assetlist_api.reload()

    # ---------------------------------------------------------------- #
    # which files are an asset's
    # ---------------------------------------------------------------- #
    suite.check('the named files an asset can record are listed with where they live',
                assetlist_api.list_file_kinds()['ok'] and
                'rig' in [kind['kind'] for kind in
                          assetlist_api.list_file_kinds()['result']])

    record = asset_manager.get_asset_manager().get_record('characters_hero_bot')
    source_rigs = record.src_rig_path
    os.makedirs(source_rigs, exist_ok=True)
    rig_file = os.path.join(source_rigs, 'hero_bot_rig.ma')
    with open(rig_file, 'w', encoding='utf-8') as opened:
        opened.write('//')

    files_answer = assetlist_api.get_asset_files('characters_hero_bot')
    suite.check('a file found on disk but not recorded is reported as inferred',
                files_answer['ok'] and
                files_answer['result']['rig']['status'] == 'inferred',
                str(files_answer['result'].get('rig')))

    set_answer = assetlist_api.set_asset_file('characters_hero_bot', 'rig', rig_file)
    suite.check('recording it is written to the file, relative to the asset',
                set_answer['ok'] and
                assetlist_api.get_asset_files('characters_hero_bot')
                ['result']['rig']['status'] == 'recorded',
                set_answer['message'])
    suite.check('a file kind nobody has heard of is refused with the valid ones',
                assetlist_api.set_asset_file('characters_hero_bot', 'blueprint',
                                             rig_file)['ok'] is False)

    # -- repairing what has drifted ----------------------------------- #
    renamed = os.path.join(source_rigs, 'hero_bot_v2_rig.ma')
    os.rename(rig_file, renamed)
    assetlist_api.reload()
    checked = assetlist_api.check_asset_files('Characters')
    suite.check('a recorded file that has been renamed is reported as stale',
                checked['ok'] and checked['result']['stale'],
                str(checked['result'])[:200])
    repaired = assetlist_api.repair_asset_files('characters_hero_bot')
    suite.check('and repairing it re-records the one candidate that is actually there',
                repaired['ok'] and repaired['result']['repaired'] and
                assetlist_api.get_asset_files('characters_hero_bot')
                ['result']['rig']['status'] == 'recorded',
                str(repaired['result'])[:200])

    with open(os.path.join(source_rigs, 'hero_bot_spare_rig.ma'), 'w', encoding='utf-8') as opened:
        opened.write('//')
    assetlist_api.set_asset_file('characters_hero_bot', 'rig',
                                 os.path.join(source_rigs, 'gone_rig.ma'))
    assetlist_api.reload()
    ambiguous = assetlist_api.repair_asset_files('characters_hero_bot')
    suite.check('with two candidates it refuses to choose, and says so',
                ambiguous['ok'] and ambiguous['result']['skipped'] and
                'set_asset_file' in ambiguous['message'],
                ambiguous['message'])

    # ---------------------------------------------------------------- #
    # the health check
    # ---------------------------------------------------------------- #
    assetlist_api.register_asset('Twin', 'Characters')
    assetlist_api.register_asset('Twin', 'Props')
    assetlist_api.reload()
    health = assetlist_api.check_assets()
    suite.check('the health check counts the assets and reports what is wrong',
                health['ok'] and health['result']['record_count'] >= 4)
    # Two assets answering to one name: only the first can be opened by name, and nothing
    # reported it before.
    suite.check('including two assets that answer to the same name',
                'twin' in health['result']['duplicate_names'],
                str(health['result']['duplicate_names']))

    # ---------------------------------------------------------------- #
    # a category added outside the API
    # ---------------------------------------------------------------- #
    # The project's category configuration is read once and kept now, so reload has to re-read
    # it as well as the assets, or a category added elsewhere never shows up.
    # Written straight to the file, the way another session's register UI would, rather than
    # through the object this process is holding.
    config_file = asset_paths.AssetDictData.file_path()
    on_disk = yamlio.read_yaml_file(config_file)
    on_disk['Creatures'] = asset_paths.new_category_block(subcategories=['Wolves'])
    yamlio.write_to_yaml_file(on_disk, config_file)
    suite.check('a category another session added is not seen straight away, because the '
                'configuration is read once',
                'Creatures' not in
                [entry['name'] for entry in assetlist_api.list_categories()['result']])
    assetlist_api.reload()
    suite.check('and a reload picks it up - which is why reload re-reads the configuration '
                'and not only the assets',
                'Creatures' in
                [entry['name'] for entry in assetlist_api.list_categories()['result']])

    # ---------------------------------------------------------------- #
    # taking an asset away
    # ---------------------------------------------------------------- #
    removed = assetlist_api.remove_asset('characters_hero_bot')
    suite.check('an asset can be removed',
                removed['ok'] and
                assetlist_api.get_asset('characters_hero_bot')['ok'] is False,
                removed['message'])
    suite.check('and the gear that was built for it is named as now having no parent',
                'Pirate Hat' in removed['message'], removed['message'])
    suite.check('removing something that is not there is refused rather than raising',
                assetlist_api.remove_asset('nothing at all')['ok'] is False)

    # ---------------------------------------------------------------- #
    # nothing raises, whatever it is handed
    # ---------------------------------------------------------------- #
    for name, arguments in (('get_asset', (None,)), ('list_assets', ('Nope',)),
                            ('describe_category', (None,)), ('search_assets', ('',)),
                            ('update_asset', ('x', 'not a mapping')),
                            ('get_asset_files', ('',)), ('transfer_asset', ('x', 'y'))):
        answer = getattr(assetlist_api, name)(*arguments)
        suite.check('{0} answers a failed response rather than raising'.format(name),
                    isinstance(answer, dict) and answer['ok'] is False and
                    bool(answer['message']),
                    str(answer))

    sourcecontrol.reset()
    suite.note('api functions checked', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('assetlist_api', body))
