"""
The animation library, without a DCC: the clip record, the catalog, projects, folders, and
planning the extraction.

    python tests/test_animlib.py

Nothing is monkeypatched. The library root and the project list both land in the temp folder
because the environment says where they go - ``MCA_PROJECT_ROOT`` for the library and
``MCA_PREFS_ROOT`` for the project list - which is the fix this port made: the project list
was built from a hand-made Documents path, so it ignored ``MCA_PREFS_ROOT`` entirely and a
test run wrote into a real machine's Documents folder.
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import sourcecontrol  # noqa: E402
from mca.common.animlib import animlib_api, catalog as catalog_module  # noqa: E402
from mca.common.animlib import clip as clip_module, extract_plan  # noqa: E402
from mca.common.animlib import projects as projects_module  # noqa: E402
from mca.common.sourcecontrol import base as sc_base  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402


class Recording(sc_base.NoSourceControl):
    """Remembers what it was asked to check out and add, and writes nothing."""

    name = 'recording'

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


def touch(path, text='placeholder'):
    """
    :param str path: A file to make, with its folder.
    :param str text: What to put in it.
    :return: The path.
    :rtype: str
    """

    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, 'w', encoding='utf-8') as opened:
        opened.write(text)

    return path


def body(suite):
    recording = Recording()
    sourcecontrol.use(recording)

    project = os.path.join(suite.temp, 'project')
    os.makedirs(os.path.join(project, 'Tools', 'Common', 'Tools'))
    os.environ[consts.MCA_PROJECT_ROOT] = project

    # ---------------------------------------------------------------- #
    # the project list, where the environment says it goes
    # ---------------------------------------------------------------- #
    projects_file = projects_module.get_projects_file()
    suite.check('the project list lives under MCA_PREFS_ROOT, not in a hand-built path to '
                'Documents',
                projects_file.startswith(os.environ[consts.MCA_PREFS_ROOT]),
                projects_file)
    suite.check('and the library that ships with the pipeline is beside the asset list',
                projects_module.get_default_root().startswith(project) and
                projects_module.get_default_root().endswith('AnimationLibrary'),
                projects_module.get_default_root())

    animlib_api.get_catalog(force_reload=True)
    library = animlib_api.get_catalog().library_root

    rows = animlib_api.list_projects()
    suite.check('a machine that has never switched projects has one, and it is current',
                rows['ok'] and len(rows['result']) == 1 and rows['result'][0]['current'],
                str(rows))

    second = os.path.join(suite.temp, 'SecondLibrary')
    added = animlib_api.add_project('Second', second, make_current=True)
    suite.check('another library can be added and switched to before it exists on disk',
                added['ok'] and not os.path.isdir(second), added['message'])
    suite.check('and switching to it moves the library root',
                os.path.normpath(animlib_api.get_catalog().library_root) ==
                os.path.normpath(second),
                animlib_api.get_catalog().library_root)
    suite.check('two projects cannot share a name, and the refusal says which',
                animlib_api.add_project('Second', os.path.join(suite.temp, 'Third'))['ok']
                is False and 'already a project' in
                animlib_api.add_project('Second', os.path.join(suite.temp, 'Third'))['message'])
    suite.check('nor a root',
                animlib_api.add_project('Another', second)['ok'] is False)
    suite.check('switching to one that is not there is refused',
                animlib_api.set_current_project('NotThere')['ok'] is False)
    suite.check('switching back restores the root',
                animlib_api.set_current_project('Default')['ok'] and
                'AnimationLibrary' in animlib_api.get_catalog().library_root)
    removed = animlib_api.remove_project('Second')
    suite.check('a project can be forgotten, and it says the files are left alone',
                removed['ok'] and 'untouched' in removed['message'], removed['message'])
    suite.check('the last one cannot be removed - there has to be a library',
                animlib_api.remove_project('Default')['ok'] is False)
    projects_module.save(projects_module.load())
    suite.check('and the list survives a trip through disk',
                len(animlib_api.list_projects()['result']) == 1)
    suite.check('which is the file the environment named',
                os.path.isfile(projects_file), projects_file)

    # ---------------------------------------------------------------- #
    # one clip
    # ---------------------------------------------------------------- #
    entry = clip_module.AnimClip.create(name='Idle_01', character='frostwind')
    suite.check('a new clip is an animation, and cannot be applied to anything yet',
                not entry.is_pose and not entry.is_applicable)
    pose = clip_module.AnimClip.create(name='Wave', character='frostwind', clip_type='pose')
    suite.check('a pose says so, and its id carries its character',
                pose.is_pose and pose.clip_id == 'frostwind_wave', pose.clip_id)
    suite.check('so the same clip name on two characters is two clips',
                clip_module.AnimClip.create(name='Wave', character='agent_male').clip_id !=
                pose.clip_id)
    entry.set_artifact('curves', 'clips/frostwind/Poses/Wave.ma')
    suite.check('a clip with curves can be put back on a rig',
                entry.is_applicable and entry.has_curves)
    entry.set_artifact('curves', '')
    entry.set_artifact('fbx', 'clips/frostwind/Poses/Wave.fbx')
    suite.check('and so can one with only a baked skeleton, the slower way',
                entry.is_applicable and not entry.has_curves and entry.has_baked_joints)
    suite.check('an artifact kind nobody has heard of is refused',
                bool(suite.raises('an unknown artifact kind raises',
                                  entry.set_artifact, 'nonsense', 'x')))
    suite.check('a field nobody has heard of is an AttributeError, so a typo surfaces',
                bool(suite.raises('an unknown field raises', getattr, entry, 'frame_rnge')))

    timed = clip_module.AnimClip.create(name='Run', character='frostwind',
                                        frame_range=[10, 40], fps=30.0)
    suite.check('a clip knows how long it is, in frames and in seconds',
                timed.duration == 30 and timed.duration_seconds == 1.0)
    suite.check('and a malformed range is nothing rather than a raise',
                clip_module.AnimClip({'frame_range': 'not a range'}).duration == 0.0 and
                clip_module.AnimClip({'fps': 0}).duration_seconds == 0.0)
    suite.check('a search reaches its name, character, category, tags and description',
                clip_module.AnimClip.create(name='Run', character='frostwind',
                                            tags=['fast', 'loop']).matches('fast run') and
                not clip_module.AnimClip.create(name='Run', character='frostwind').matches('slow'))

    # ---------------------------------------------------------------- #
    # folders
    # ---------------------------------------------------------------- #
    animlib_api.get_catalog(force_reload=True)
    library = animlib_api.get_catalog().library_root

    made = animlib_api.create_folder('frostwind', 'Locomotion')
    suite.check('a folder can be made, and is really there',
                made['ok'] and os.path.isdir(made['result']['path']) and
                made['result']['created'], made['message'])
    again = animlib_api.create_folder('frostwind', 'Locomotion')
    suite.check('making it twice is not an error, and says it was already there',
                again['ok'] and not again['result']['created'])
    listed = animlib_api.list_folders('frostwind')
    suite.check('an empty folder still lists, with no clips in it',
                'Locomotion' in [row['category'] for row in listed['result']] and
                listed['result'][0]['clips'] == 0 and 'empty' in listed['message'],
                listed['message'])
    for bad in ('a/b', 'a\\b', '..'):
        suite.check('a folder called {0!r} is refused'.format(bad),
                    animlib_api.create_folder('frostwind', bad)['ok'] is False)
    suite.check('and a folder needs a character to belong to',
                animlib_api.create_folder('', 'Locomotion')['ok'] is False)

    gone = animlib_api.remove_folder('frostwind', 'Locomotion')
    suite.check('an empty folder can be removed',
                gone['ok'] and not os.path.isdir(
                    catalog_module.category_folder(library, 'frostwind', 'Locomotion')),
                gone['message'])
    stray = catalog_module.category_folder(library, 'frostwind', 'Scratch')
    touch(os.path.join(stray, 'notes.txt'))
    suite.check('a folder with somebody else\'s files in it is not quietly deleted',
                animlib_api.remove_folder('frostwind', 'Scratch')['ok'] is False)
    suite.check('unless the caller insists',
                animlib_api.remove_folder('frostwind', 'Scratch', force=True)['ok'])

    # ---------------------------------------------------------------- #
    # the catalog
    # ---------------------------------------------------------------- #
    animlib_api.get_catalog(force_reload=True)
    library = animlib_api.get_catalog().library_root
    recording.checked_out = []
    recording.added = []

    touch(os.path.join(library, 'clips', 'frostwind', 'Locomotion', 'Run_01.ma'))
    registered = animlib_api.register_clip(
        name='Run_01', character='frostwind', category='Locomotion',
        curves_file='clips/frostwind/Locomotion/Run_01.ma',
        frame_range=[0, 30], fps=30.0, root_motion='travelling', flag_count=42)
    suite.check('a clip can be registered, and is an animation unless it says otherwise',
                registered['ok'] and registered['result']['clip_type'] == 'animation',
                registered['message'])
    # The library sits under the common tools path, which is in source control.
    catalog_file = animlib_api.get_catalog().catalog_path
    suite.check('the catalog file is added to source control the first time it is written',
                catalog_file in recording.added, str(recording.added))

    recording.added = []
    recording.checked_out = []
    pose_file = touch(os.path.join(library, 'clips', 'frostwind', 'Poses', 'TPose.ma'))
    pose = animlib_api.register_clip(name='TPose', character='frostwind', category='Poses',
                                     curves_file='clips/frostwind/Poses/TPose.ma',
                                     frame_range=[7, 7], clip_type='pose')
    suite.check('a pose can be registered, and keeps its type',
                pose['ok'] and pose['result']['clip_type'] == 'pose', pose['message'])
    suite.check('and from then on the catalog is checked out rather than added again',
                catalog_file in recording.checked_out and catalog_file not in recording.added)

    suite.check('a clip type nobody has heard of is refused',
                animlib_api.register_clip(name='X', character='frostwind',
                                          clip_type='sketch')['ok'] is False)
    suite.check('and registering the same clip twice is refused',
                animlib_api.register_clip(name='Run_01', character='frostwind',
                                          category='Locomotion')['ok'] is False)

    suite.check('poses and animations can be listed apart, or together',
                [c['name'] for c in animlib_api.list_clips(clip_type='pose')['result']] ==
                ['TPose'] and
                [c['name'] for c in animlib_api.list_clips(clip_type='animation')['result']] ==
                ['Run_01'] and
                len(animlib_api.list_clips()['result']) == 2)
    suite.check('an unknown type to filter by is refused rather than answering nothing',
                animlib_api.list_clips(clip_type='sketch')['ok'] is False)

    held = animlib_api.remove_folder('frostwind', 'Locomotion')
    suite.check('a folder with clips in it is not removed by accident, and the refusal names '
                'them',
                held['ok'] is False and 'Run_01' in held['message'], held['message'])

    described = animlib_api.describe_library()
    suite.check('the library describes itself: which project, and how many clips',
                described['result']['project'] == 'Default' and
                described['result']['clip_count'] == 2, str(described['result'])[:160])

    # A recorded file that has gone missing is a different thing from one never exported.
    os.remove(pose_file)
    health = animlib_api.check_library()
    suite.check('a file that has gone missing is reported',
                len(health['result']['missing_files']) == 1, str(health['result'])[:200])
    suite.check('and a one-frame animation is flagged as having no length',
                'frostwind_tpose' in health['result']['zero_length'])
    touch(pose_file)
    suite.check('putting the file back clears the complaint',
                not animlib_api.check_library()['result']['missing_files'])

    updated = animlib_api.update_clip('frostwind_run_01', {'tags': ['locomotion', 'fast']})
    suite.check('a clip can be updated, and it sticks',
                updated['ok'] and
                animlib_api.get_clip('frostwind_run_01')['result']['tags'] ==
                ['locomotion', 'fast'], updated['message'])
    suite.check('an update to an unknown clip type is refused',
                animlib_api.update_clip('frostwind_run_01', {'clip_type': 'sketch'})['ok']
                is False)
    suite.check('search reaches the tags',
                [c['name'] for c in animlib_api.search_clips('fast')['result']] == ['Run_01'])
    missing = animlib_api.get_clip('frostwind_run_02')
    suite.check('a clip nobody has is refused, with something to try instead',
                missing['ok'] is False and 'Did you mean' in missing['message'],
                missing['message'])

    # -- what is actually on disk ------------------------------------- #
    suite.check('the characters and categories on disk can be found without the catalog',
                'frostwind' in catalog_module.disk_characters(library) and
                'Locomotion' in catalog_module.disk_categories(library, 'frostwind'),
                str(catalog_module.disk_characters(library)))
    suite.check('and asking about a character that is not there answers nothing',
                catalog_module.disk_categories(library, 'nobody') == [] and
                catalog_module.disk_categories(library, '') == [])
    suite.check('a clip\'s folder is where the catalog says it is',
                catalog_module.category_folder(library, 'frostwind', 'Locomotion') ==
                os.path.normpath(os.path.join(library, 'clips', 'frostwind', 'Locomotion')))

    # A hand-edited catalog with a record missing its id still loads.
    hand_edited = catalog_module.AnimCatalog(library_root=library, data={'clips': [
        {'name': 'Hand Written', 'character': 'frostwind'},
        {'name': 'Twice', 'character': 'frostwind', 'clip_id': 'frostwind_twice'},
        {'name': 'Twice Again', 'character': 'frostwind', 'clip_id': 'frostwind_twice'},
        'not a record at all',
        {'character': 'frostwind'},
    ]})
    suite.check('a hand-edited catalog loads: an id is derived where one is missing, a '
                'duplicate keeps the first, and nonsense is stepped over',
                len(hand_edited) == 2 and 'frostwind_hand_written' in hand_edited,
                str(sorted(entry.clip_id for entry in hand_edited.sorted_clips())))

    # ---------------------------------------------------------------- #
    # planning the extraction
    # ---------------------------------------------------------------- #
    characters = os.path.join(suite.temp, 'depot', 'Characters')
    for relative in (
            os.path.join('Heroes', 'Frostwind', 'Animations', 'Locomotion', 'Run_01.ma'),
            os.path.join('Heroes', 'Frostwind', 'Animations', 'POSES', 'TPose.ma'),
            os.path.join('Heroes', 'Frostwind', 'Animations', 'Loose_File.ma'),
            os.path.join('Heroes', 'Frostwind', '_Source', 'Animations', 'Abilities', 'Cast.ma'),
            # Every one of these must be left out.
            os.path.join('Heroes', 'Frostwind', 'Animations', 'incrementalSave', 'Run_01.ma'),
            os.path.join('Heroes', 'Frostwind', 'Animations', 'Locomotion', 'test_Run.ma'),
            os.path.join('Heroes', 'Frostwind', 'Animations', 'Locomotion', 'Run_01.ma.bak'),
            os.path.join('Heroes', 'Frostwind', 'Meshes', 'SK_Frostwind.ma'),
    ):
        touch(os.path.join(characters, relative), '//')

    found = extract_plan.find_animation_files(characters)
    names = sorted(os.path.basename(path) for path, _ in found)
    # The mesh is not under Animations, the .bak is not a .ma, and the incremental-save folder
    # is pruned during the walk. A scratch *name* is somebody's judgement rather than the
    # walk's, so test_Run.ma is found here and dropped when the plan is built.
    suite.check('only the animation files under an Animations folder are found',
                names == ['Cast.ma', 'Loose_File.ma', 'Run_01.ma', 'TPose.ma', 'test_Run.ma'],
                str(names))
    suite.check('and each one is found once, not once per folder deep',
                len(found) == len(set(path for path, _ in found)), str(len(found)))

    suite.check('a category comes from the first folder below Animations',
                extract_plan.derive_category(
                    os.path.join(characters, 'Heroes', 'Frostwind', 'Animations', 'Locomotion',
                                 'Run_01.ma'),
                    os.path.join(characters, 'Heroes', 'Frostwind', 'Animations')) ==
                'Locomotion')
    suite.check('a file sitting loose in Animations has no category of its own',
                extract_plan.derive_category(
                    os.path.join(characters, 'Heroes', 'Frostwind', 'Animations', 'Loose.ma'),
                    os.path.join(characters, 'Heroes', 'Frostwind', 'Animations')) ==
                'Uncategorised')
    # The depot has both Poses and POSES, and left alone they are two rows in the browser.
    suite.check('spellings that differ only in case fold together',
                extract_plan.normalise_category('POSES') ==
                extract_plan.normalise_category('poses') == 'Poses')
    suite.check('and a deliberate internal capital is left alone',
                extract_plan.normalise_category('MainLocomotion') == 'MainLocomotion')

    asset_id, folder = extract_plan.character_for_path(
        os.path.join(characters, 'Heroes', 'Frostwind', '_Source', 'Animations', 'Abilities',
                     'Cast.ma'), characters)
    suite.check('a clip under _Source/Animations still belongs to the character above it',
                folder == 'Frostwind' and asset_id == 'frostwind',
                '{0} {1}'.format(asset_id, folder))
    mapped, _ = extract_plan.character_for_path(
        os.path.join(characters, 'Heroes', 'Frostwind', 'Animations', 'Run_01.ma'), characters,
        name_to_asset_id={'frostwind': 'characters_frostwind'})
    suite.check('and a character in the asset list is named by its asset id',
                mapped == 'characters_frostwind', mapped)

    plan = extract_plan.build_plan(characters,
                                   name_to_asset_id={'frostwind': 'characters_frostwind'})
    suite.check('a plan is built without opening a single scene',
                plan['entries'] and all(entry['status'] == extract_plan.STATUS_PENDING
                                        for entry in plan['entries']),
                str(len(plan['entries'])))
    suite.check('and it says what it left out, and why',
                plan['skipped'] and all(entry.get('reason') for entry in plan['skipped']),
                str(plan['skipped'][:2]))
    suite.check('a file whose name looks like scratch is what it left out',
                any('test_Run' in str(entry) for entry in plan['skipped']) and
                not any('test_Run' in str(entry) for entry in plan['entries']),
                str(plan['skipped'])[:200])
    summary = extract_plan.summarise(plan)
    suite.check('a plan can be summarised for a person to read before it runs',
                summary and isinstance(summary, dict), str(summary)[:160])

    plan_path = extract_plan.write_plan(plan, os.path.join(suite.temp, 'plan.json'))
    suite.check('a plan goes to disk and comes back the same',
                os.path.isfile(plan_path) and
                len(extract_plan.read_plan(plan_path)['entries']) == len(plan['entries']))
    suite.check('and everything in it is pending until something does it',
                len(extract_plan.pending_entries(plan)) == len(plan['entries']))
    plan['entries'][0]['status'] = extract_plan.STATUS_DONE
    suite.check('one done is one fewer to do',
                len(extract_plan.pending_entries(plan)) == len(plan['entries']) - 1)

    sourcecontrol.reset()
    suite.note('clips in the library', len(animlib_api.get_catalog()))


if __name__ == '__main__':
    sys.exit(harness.run('animlib', body))
