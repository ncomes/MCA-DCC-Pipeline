"""
The asset registry's read layer: every asset, indexed, and what is wrong with them.

    python tests/test_asset_manager.py
"""

# python imports
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import sourcecontrol  # noqa: E402
from mca.common.assetlist import asset_manager, asset_paths, validate_assets  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import alistio, jsonio  # noqa: E402


def write_project(temp, categories, manifest_version='2.0', gear_categories=()):
    """
    Build a project on disk with a category manifest and one .alist per category.

    :param str temp: A folder to build it in.
    :param dict categories: Category name to ``{asset_id: fields}``.
    :param str manifest_version: What categories.json should claim to be.
    :param gear_categories: Categories to flag as gear in the project's config.
    :return: The project root.
    :rtype: str
    """

    project = os.path.join(temp, 'project')
    assetlist = os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist')
    assetlists = os.path.join(assetlist, 'Assetlists')
    # Each scenario starts from nothing. The manager loads a category that is in the project's
    # config but not in its manifest, so a leftover .alist from the scenario before would be
    # picked up by the one after.
    if os.path.isdir(assetlist):
        shutil.rmtree(assetlist)
    os.makedirs(assetlists)

    jsonio.write_to_json_file(
        {'version': manifest_version,
         'categories': [{'name': name, 'folder': 'Assetlists'} for name in categories]},
        os.path.join(assetlist, 'categories.json'))

    for name, assets in categories.items():
        alistio.write_alist_file(assets, os.path.join(assetlists, '{0}.alist'.format(name)),
                                 fmt='json')

    os.environ[consts.MCA_PROJECT_ROOT] = project
    asset_paths.reload()

    if gear_categories:
        config = asset_paths.AssetDictData.load()
        for name in categories:
            if name not in config.categories_names:
                config.add_category(name, is_gear=name in gear_categories)
            else:
                category = config.get_category_data(name)
                category.is_gear = name in gear_categories
        config.save()
        asset_paths.reload()

    return project


def asset(name, category, **fields):
    """
    :param str name: The asset's name.
    :param str category: Its category.
    :return: Its fields, with the ones every asset needs filled in.
    :rtype: dict
    """

    data = {'name': name, 'category': category, 'asset_type': 'SkeletalMesh',
            'path': '{0}/{1}'.format(category, name.replace(' ', '_'))}
    data.update(fields)
    return data


def body(suite):
    sourcecontrol.use('none')

    # ---------------------------------------------------------------- #
    # a project with characters and the gear they wear
    # ---------------------------------------------------------------- #
    write_project(suite.temp, {
        'Characters': {
            'characters_hero_bot': asset('Hero Bot', 'Characters', subtype='Heroes',
                                         namespace='hero', skeleton='SampleBot'),
            'characters_villain_bot': asset('Villain Bot', 'Characters', subtype='Enemies',
                                            namespace='villain'),
        },
        'Hats': {
            'hats_pirate': asset('Pirate Hat', 'Hats', slot='Hat', built_for='Hero Bot'),
            'hats_shared': asset('Shared Hat', 'Hats', slot='Hat',
                                 built_for=['Hero Bot', 'Villain Bot']),
        },
    }, gear_categories=('Hats',))

    manager = asset_manager.get_asset_manager(force_reload=True)
    suite.check('every asset in every category the manifest declares is loaded',
                len(list(manager.iter_all())) == 4, str(len(list(manager.iter_all()))))
    suite.check('and each one is found by its id',
                manager.get_record('characters_hero_bot') is not None and
                manager.get_record('nothing at all') is None)
    suite.check('by its name, whatever case it is asked in',
                manager.get_record_by_name('hero bot') is not None and
                manager.get_record_by_name('HERO BOT') is not None)
    suite.check('and by its id through the name lookup, for callers that store one',
                manager.get_record_by_name('characters_hero_bot') is not None and
                manager.get_record_by_name('') is None)
    suite.check('a category can be walked, and narrowed to a subtype',
                len(list(manager.iter_category('Characters'))) == 2 and
                [record.name for record in manager.iter_category('Characters', 'Heroes')] ==
                ['Hero Bot'] and
                list(manager.iter_category('Nothing')) == [])

    # -- gear finds its character by name ----------------------------- #
    hat = manager.get_record('hats_pirate')
    suite.check('gear names the character it is for, and that becomes its parent',
                hat.parent_id == 'characters_hero_bot', str(hat.parent_id))
    suite.check('so the character\'s children are the gear made for it',
                'Pirate Hat' in [record.name for record in
                                 manager.iter_children('characters_hero_bot')])
    shared = manager.get_record('hats_shared')
    suite.check('gear worn by two characters keeps both, and the first is its parent',
                sorted(shared.parent_ids) == ['characters_hero_bot', 'characters_villain_bot'] and
                shared.parent_id in shared.parent_ids,
                str(shared.parent_ids))
    suite.check('and it shows up under both of them',
                'Shared Hat' in [record.name for record in
                                 manager.iter_children('characters_villain_bot')] and
                'Shared Hat' in [record.name for record in
                                 manager.iter_children('characters_hero_bot')])
    suite.check('the characters are the roots, and the gear is not',
                sorted(record.name for record in manager.get_roots()) ==
                ['Hero Bot', 'Villain Bot'],
                str(sorted(record.name for record in manager.get_roots())))
    suite.check('and a root can be asked for by category',
                [record.name for record in manager.get_roots('Hats')] == [])
    suite.check('a chain of parents reads from the asset upwards',
                [record.asset_id for record in manager.get_parent_chain('hats_pirate')] ==
                ['characters_hero_bot'])
    suite.check('and everything below an asset can be walked in one go',
                {record.asset_id for record in manager.iter_descendants('characters_hero_bot')} ==
                {'hats_pirate', 'hats_shared'})

    # -- what a record answers ---------------------------------------- #
    hero = manager.get_record('characters_hero_bot')
    suite.check('a record carries the fields the registry holds',
                hero.name == 'Hero Bot' and hero.category == 'Characters' and
                hero.subtype == 'Heroes' and hero.skeleton == 'SampleBot')
    suite.check('its folders come from its category',
                hero.src_rig_path.endswith(os.path.join('_Source', 'Rigs')) and
                hero.models_path.endswith('Meshes'),
                '{0} | {1}'.format(hero.src_rig_path, hero.models_path))
    suite.check('and the skin data folder sits inside the source rigs',
                hero.skin_data_path.endswith(os.path.join('Rigs', 'Skin_Data')),
                hero.skin_data_path)
    suite.check('a record is frozen, so nothing can change the registry through one',
                bool(suite.raises('changing a record raises', setattr, hero, 'name', 'Other')))
    suite.check('anything it does not have of its own it asks its entry for',
                callable(hero.get_rig_list) and
                bool(suite.raises('and a name neither has still raises',
                                  getattr, hero, 'not_a_thing_at_all')))
    suite.check('it can be handed back as plain values',
                hero.to_serializable()['name'] == 'Hero Bot' and
                manager.to_json_serializable()['Characters']['characters_hero_bot']['name'] ==
                'Hero Bot')

    # -- an asset with no path --------------------------------------- #
    write_project(suite.temp, {'Characters': {
        'characters_pathless': {'name': 'Pathless', 'category': 'Characters',
                                'asset_type': 'SkeletalMesh'}}})
    manager = asset_manager.get_asset_manager(force_reload=True)
    pathless = manager.get_record('characters_pathless')
    suite.check('an asset with no path answers nothing for its folders, rather than None',
                pathless.src_rig_path == '' and pathless.models_path == '' and
                pathless.skin_data_path == '' and pathless.skin_path == '',
                repr(pathless.src_rig_path))

    # ---------------------------------------------------------------- #
    # what is wrong with the registry
    # ---------------------------------------------------------------- #
    write_project(suite.temp, {
        'Characters': {
            # Two assets, each the other's parent. Neither is a root, so the version this
            # replaces - which only walked down from the roots - never visited either, and
            # the cycle went unreported.
            'characters_ouroboros_a': asset('A Bot', 'Characters',
                                            parent='characters_ouroboros_b'),
            'characters_ouroboros_b': asset('B Bot', 'Characters',
                                            parent='characters_ouroboros_a'),
            # Two assets answering to one name: only the first is reachable by name.
            'characters_twin_one': asset('Twin', 'Characters', namespace='shared_space'),
            'characters_twin_two': asset('Twin', 'Characters', namespace='shared_space'),
            # A parent that is not in the registry at all.
            'characters_orphan': asset('Orphan', 'Characters', parent='characters_nobody'),
            # In this format - it has an asset_type - but missing the fields every asset
            # needs. An entry with none of the format's own fields is skipped at load
            # instead, and is checked further down.
            'characters_empty': {'name': 'Empty', 'asset_type': 'SkeletalMesh'},
        },
    })
    manager = asset_manager.get_asset_manager(force_reload=True)
    report = manager.validation_report

    suite.check('a registry with problems in it is not sound', not report.is_valid())
    suite.check('an asset missing the fields it needs is reported',
                'characters_empty' in report.missing_required_fields and
                {'category', 'path'} <= report.missing_required_fields['characters_empty'],
                str(report.missing_required_fields))
    suite.check('an asset whose parent is not in the registry is reported',
                report.dangling_parents.get('characters_orphan') == 'characters_nobody')
    suite.check('two assets sharing a namespace are reported',
                'shared_space' in report.duplicate_namespaces)
    # get_record_by_name answers the first one loaded, so the other is an asset an artist can
    # see in a list and cannot open. Nothing reported it.
    suite.check('and two assets answering to one name are reported now',
                'twin' in report.duplicate_names and
                len(report.duplicate_names['twin']) == 2,
                str(report.duplicate_names))
    cycles = {tuple(sorted(set(cycle))) for cycle in report.cyclic_dependencies}
    suite.check('a cycle no root can reach is found, which is the only kind that matters',
                ('characters_ouroboros_a', 'characters_ouroboros_b') in cycles,
                str(report.cyclic_dependencies))
    suite.check('and the whole thing is reported as unsound because of it',
                bool(report.cyclic_dependencies))

    # ---------------------------------------------------------------- #
    # a registry this cannot read
    # ---------------------------------------------------------------- #
    write_project(suite.temp, {'Characters': {'a': asset('A', 'Characters')}},
                  manifest_version='1.0')
    manager = asset_manager.get_asset_manager(force_reload=True)
    suite.check('a manifest from before the formats were merged loads nothing, rather than '
                'reading half the data with the wrong precedence',
                list(manager.iter_all()) == [])

    project = write_project(suite.temp, {'Characters': {
        'good': asset('Good', 'Characters'),
        'old': {'name': 'Old Shape', 'category': 'Characters', 'path': 'Characters/Old'}}})
    manager = asset_manager.get_asset_manager(force_reload=True)
    suite.check('an asset in the old shape is stepped over and the rest still load',
                [record.name for record in manager.iter_all()] == ['Good'],
                str([record.name for record in manager.iter_all()]))

    os.remove(os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist', 'categories.json'))
    manager = asset_manager.get_asset_manager(force_reload=True)
    suite.check('and a project with no manifest at all loads nothing rather than raising',
                list(manager.iter_all()) == [])

    # ---------------------------------------------------------------- #
    # the same manager everywhere
    # ---------------------------------------------------------------- #
    suite.check('the manager is shared, so twenty tools reading the registry read it once',
                asset_manager.get_asset_manager() is asset_manager.get_asset_manager())

    # ---------------------------------------------------------------- #
    # the command line check
    # ---------------------------------------------------------------- #
    write_project(suite.temp, {'Characters': {'characters_fine': asset('Fine', 'Characters')}})
    suite.check('a sound registry answers 0 from the command line',
                validate_assets.main([]) == 0)

    project = write_project(suite.temp, {
        'Characters': {'characters_fine': asset('Fine', 'Characters')},
        'Hats': {'hats_broken': {'name': 'Broken Hat', 'category': 'Hats', 'slot': 'Hat'}},
    }, gear_categories=('Hats',))
    suite.check('and one with a problem answers 1', validate_assets.main([]) == 1)

    # --skip-gear collected the ids to ignore with iter_category('Gear'), and 'Gear' is not a
    # category - gear lives in categories of its own, each flagged as gear - so the set was
    # always empty and every gear problem was reported anyway.
    suite.check('skipping gear actually skips the gear now',
                validate_assets.main(['--skip-gear']) == 0)

    out = io.StringIO()
    real_stdout, sys.stdout = sys.stdout, out
    try:
        code = validate_assets.main(['--json'])
    finally:
        sys.stdout = real_stdout
    payload = json.loads(out.getvalue())
    suite.check('the JSON report says whether it passed and what it found',
                code == 1 and payload['success'] is False and
                'hats_broken' in payload['report']['missing_required_fields'],
                out.getvalue()[:200])
    suite.check('and it carries the duplicate names the old report had no room for',
                'duplicate_names' in payload['report'])

    # A different project can be checked without the environment already naming it.
    other = write_project(suite.temp, {'Characters': {'characters_fine': asset('Fine', 'Characters')}})
    os.environ.pop(consts.MCA_PROJECT_ROOT)
    suite.check('a project named on the command line is the one that gets checked',
                validate_assets.main(['--project-root', other]) == 0)

    sourcecontrol.reset()
    suite.note('assets checked', len(list(asset_manager.get_asset_manager().iter_all())))


if __name__ == '__main__':
    sys.exit(harness.run('asset_manager', body))
