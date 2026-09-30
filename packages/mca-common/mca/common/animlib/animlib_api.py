"""
Headless animation library API.

Every function returns ``{'ok': bool, 'result': <json>, 'message': str}`` - the
same contract as ``assetlist_api``, ``gear_api`` and ``toolbox_api`` - so the
browser UI, the in-Maya AI and the MCP tools drive one code path.

This half is DCC-agnostic: it reads and writes the catalog and knows where clip
files belong. Anything that touches a Maya scene (capturing a clip off a rig,
applying one onto a rig, exporting an FBX) lives in
``mca.mya.tools.animlibrary.animlib_maya``.

A clip carries up to three files. ``curves`` is the master - a small ``.ma`` of
the stored curve network, which keeps animation layers and flag context.
``fbx`` is derived from it and is what other DCCs read. ``preview`` is a
playblast for the browser. See :mod:`mca.common.animlib.clip`.

:Requires: mca.common.animlib.catalog
:Side effects: The write functions rewrite catalog.json.
"""

# python imports
import functools
import os
import traceback

# MCA python imports
from mca.common import log
from mca.common.animlib import catalog as catalog_module
from mca.common.animlib import clip as clip_module
from mca.common.animlib import projects as projects_module

logger = log.MCA_LOGGER

# Most rows a query returns even when asked for more, so a bad filter cannot
# dump the whole library into a chat window.
MAX_RESULTS = 500

# Characters a folder name may not contain. Both slashes are here on purpose:
# the library is read from Windows, Linux and inside other DCCs, so a name that
# is only awkward on one of them is a broken path on another.
ILLEGAL_FOLDER_CHARACTERS = '/\\:*?"<>|'

_CATALOG = None


def _response(ok, result=None, message=''):
    """
    :param bool ok: Success flag.
    :param object result: JSON-serialisable result.
    :param str message: Human readable summary.
    :return: The standard response dict.
    :rtype: dict
    """

    return {'ok': ok, 'result': result, 'message': message}


def _safe(func):
    """
    Decorator: turn exceptions into failed responses.

    :param callable func: API function returning ``(result, message)``.
    :return: Wrapped function returning a response dict.
    :rtype: callable
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result, message = func(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            return _response(False, None, str(exc).strip("'\""))
        except Exception as exc:
            logger.error('animlib_api.%s failed: %s\n%s',
                         func.__name__, exc, traceback.format_exc())
            return _response(False, None, '{}: {}'.format(type(exc).__name__, exc))
        return _response(True, result, message)

    return wrapper


def get_catalog(force_reload=False):
    """
    The shared catalog, loaded once.

    :param bool force_reload: Re-read catalog.json from disk.
    :return: The catalog.
    :rtype: catalog_module.AnimCatalog
    """

    global _CATALOG
    if _CATALOG is None or force_reload:
        _CATALOG = catalog_module.AnimCatalog.load()
    return _CATALOG


def _require_clip(clip_id):
    """
    Resolve a clip id or display name to a clip.

    :param str clip_id: Clip id or display name.
    :return: The clip.
    :rtype: clip_module.AnimClip
    :raises ValueError: When it is empty or unknown.
    """

    if not clip_id:
        raise ValueError('clip_id is required.')
    catalog = get_catalog()
    entry = catalog.get(clip_id) or catalog.get_by_name(clip_id)
    if entry is None:
        raise ValueError('No clip with id or name {!r} in the library.{}'
                         .format(clip_id, _did_you_mean(clip_id, list(
                             c.clip_id for c in catalog.sorted_clips()))))
    return entry


def _did_you_mean(value, options, limit=3):
    """
    Suggest close matches for a value that was not found.

    :param str value: What the caller asked for.
    :param list options: Valid values.
    :param int limit: Most suggestions to offer.
    :return: ' Did you mean: a, b?' or ''.
    :rtype: str
    """

    import difflib
    close = difflib.get_close_matches(str(value), [str(o) for o in options], n=limit, cutoff=0.5)
    return ' Did you mean: {}?'.format(', '.join(close)) if close else ''


def _clip_to_dict(entry, verbose=False):
    """
    Convert a clip to a JSON-safe dict.

    :param clip_module.AnimClip entry: The clip.
    :param bool verbose: Include artifacts, source and timestamps.
    :return: The clip data.
    :rtype: dict
    """

    data = {
        'clip_id': entry.clip_id,
        'name': entry.name,
        'clip_type': entry.get('clip_type') or 'animation',
        'character': entry.character,
        'category': entry.category,
        'tags': list(entry.tags or []),
        'frame_range': list(entry.frame_range or []),
        'fps': entry.fps,
        'duration': entry.duration,
        'root_motion': entry.root_motion,
        'has_layers': entry.has_layers,
        'applicable': entry.is_applicable,
        # Which of the two apply routes this clip can actually take. The UI uses
        # these to decide what to offer rather than guessing from 'artifacts',
        # which is only filled in on a verbose read.
        'has_curves': entry.has_curves,
        'has_baked_joints': entry.has_baked_joints,
    }
    if entry.description:
        data['description'] = entry.description
    if verbose:
        data['artifacts'] = dict(entry.artifacts or {})
        data['source_file'] = entry.source_file
        data['flag_count'] = entry.flag_count
        data['created'] = entry.created
        data['updated'] = entry.updated
    return data


def _cap(items, limit):
    """
    Apply the caller's limit and the hard cap.

    :param list items: Items to trim.
    :param int limit: Requested limit; 0 or None means MAX_RESULTS.
    :return: ``(trimmed, total, truncated)``.
    :rtype: tuple
    """

    total = len(items)
    ceiling = min(int(limit) if limit else MAX_RESULTS, MAX_RESULTS)
    return items[:ceiling], total, total > ceiling


# --- Discovery ----------------------------------------------------------------------------------------------------

@_safe
def describe_library():
    """
    Where the library is and what is in it.

    Call this first: it says whether the library exists yet, and a caller that
    gets zero clips back from a search can tell an empty library from a bad filter.

    :return: Response with root, counts and health.
    :rtype: dict
    """

    catalog = get_catalog()
    exists = os.path.isfile(catalog.catalog_path)
    health = catalog.check()
    result = {
        'project': projects_module.current()['name'],
        'library_root': catalog.library_root,
        'catalog_path': catalog.catalog_path,
        'catalog_exists': exists,
        'clip_count': len(catalog),
        'character_count': len(catalog.characters()),
        'applicable_count': sum(1 for c in catalog.sorted_clips() if c.is_applicable),
        'missing_files': len(health['missing_files']),
    }
    if not exists:
        return result, ('No animation library at {} yet. Capture a clip, or run the extractor '
                        'over the existing animation files, to create one.'
                        .format(catalog.library_root))
    return result, ('{} clip(s) across {} character(s); {} can be applied to a rig.'
                    .format(result['clip_count'], result['character_count'],
                            result['applicable_count']))


@_safe
def list_characters():
    """
    Characters that own clips, with counts.

    :return: Response with ``[{'character', 'clips'}]``.
    :rtype: dict
    """

    rows = [{'character': name or '(unassigned)', 'clips': count}
            for name, count in get_catalog().characters()]
    if not rows:
        return rows, 'The library has no clips yet.'
    return rows, '{} character(s) with clips.'.format(len(rows))


@_safe
def list_categories(character=None):
    """
    Categories in use, with counts.

    :param str character: Restrict to one character's asset id.
    :return: Response with ``[{'category', 'clips'}]``.
    :rtype: dict
    """

    rows = [{'category': name, 'clips': count}
            for name, count in get_catalog().categories(character)]
    who = ' for {}'.format(character) if character else ''
    if not rows:
        return rows, 'No categories in use{}.'.format(who)
    return rows, '{} categor(y/ies){}.'.format(len(rows), who)


@_safe
def list_clips(character=None, category=None, applicable_only=False, clip_type=None, limit=0):
    """
    List clips, optionally filtered.

    :param str character: Restrict to one character's asset id.
    :param str category: Restrict to one category.
    :param bool applicable_only: Only clips that have a curve file.
    :param str clip_type: 'animation' or 'pose'. None returns both.
    :param int limit: Most rows to return.
    :return: Response with a list of clip dicts.
    :rtype: dict
    """

    if clip_type and clip_type not in clip_module.CLIP_TYPES:
        raise ValueError('clip_type must be one of: {}.'
                         .format(', '.join(clip_module.CLIP_TYPES)))
    found = get_catalog().search(character=character, category=category,
                                 applicable_only=applicable_only)
    if clip_type:
        found = [c for c in found if (c.get('clip_type') or 'animation') == clip_type]
    rows, total, truncated = _cap([_clip_to_dict(c) for c in found], limit)
    filters = ', '.join(x for x in [
        'character={}'.format(character) if character else '',
        'category={}'.format(category) if category else '',
        '{}s only'.format(clip_type) if clip_type else '',
        'applicable only' if applicable_only else ''] if x)
    message = '{} clip(s){}.'.format(total, ' matching {}'.format(filters) if filters else '')
    if truncated:
        message += ' Showing the first {}.'.format(len(rows))
    return rows, message


@_safe
def search_clips(query, limit=0):
    """
    Free-text search over name, character, category, tags and description.

    :param str query: Search text. All terms must match.
    :param int limit: Most rows to return.
    :return: Response with a list of clip dicts.
    :rtype: dict
    """

    found = get_catalog().search(query=query)
    rows, total, truncated = _cap([_clip_to_dict(c) for c in found], limit)
    if not total:
        return rows, 'Nothing matches {!r}. Try list_categories to see what is in the library.'.format(query)
    message = '{} clip(s) match {!r}.'.format(total, query)
    if truncated:
        message += ' Showing the first {}.'.format(len(rows))
    return rows, message


@_safe
def get_clip(clip_id, verbose=True):
    """
    One clip by id or display name.

    :param str clip_id: Clip id or display name.
    :param bool verbose: Include artifacts, source file and timestamps.
    :return: Response with the clip dict.
    :rtype: dict
    """

    entry = _require_clip(clip_id)
    return _clip_to_dict(entry, verbose=verbose), 'Clip {} ({}).'.format(entry.name, entry.clip_id)


@_safe
def get_clip_files(clip_id):
    """
    The absolute path and on-disk state of each of a clip's artifacts.

    :param str clip_id: Clip id or display name.
    :return: Response with ``{kind: {'path', 'recorded', 'exists'}}``.
    :rtype: dict
    """

    entry = _require_clip(clip_id)
    root = get_catalog().library_root
    result = {}
    for kind in clip_module.ARTIFACT_KINDS:
        relative = entry.artifact(kind)
        absolute = entry.artifact_path(kind, root)
        result[kind] = {'recorded': relative,
                        'path': absolute,
                        'exists': bool(absolute) and os.path.isfile(absolute)}
    present = [k for k, v in result.items() if v['exists']]
    return result, ('{} has: {}.'.format(entry.name, ', '.join(present)) if present
                    else '{} has no files on disk.'.format(entry.name))


@_safe
def check_library():
    """
    Report clips with missing files or no curve file.

    :return: Response with the health report.
    :rtype: dict
    """

    report = get_catalog().check()
    problems = sum(len(v) for v in report.values())
    if not problems:
        return report, 'Every clip checks out.'
    parts = []
    if report['missing_files']:
        parts.append('{} missing file(s)'.format(len(report['missing_files'])))
    if report['no_curves']:
        parts.append('{} with no curves'.format(len(report['no_curves'])))
    if report['no_character']:
        parts.append('{} with no character'.format(len(report['no_character'])))
    if report['zero_length']:
        parts.append('{} whose keys are all on one frame'.format(len(report['zero_length'])))
    return report, '; '.join(parts) + '.'


@_safe
def reload():
    """
    Re-read catalog.json from disk.

    :return: Response with the clip count.
    :rtype: dict
    """

    catalog = get_catalog(force_reload=True)
    return {'clip_count': len(catalog)}, 'Reloaded {} clip(s).'.format(len(catalog))


# --- Writes -------------------------------------------------------------------------------------------------------

@_safe
def register_clip(name, character, category='Uncategorised', curves_file='', fbx_file='',
                  preview_file='', gif_file='', frame_range=None, fps=30.0,
                  root_motion='unknown', tags=None, description='', source_file='',
                  has_layers=False, flag_count=0, clip_type='animation', replace=False):
    """
    Add a clip to the catalog.

    This records an entry; it does not move or create any files. The Maya side
    writes the files and then calls this.

    :param str name: Display name.
    :param str character: Owning character's asset id.
    :param str category: Grouping, e.g. 'Locomotion'.
    :param str curves_file: Library-relative path to the curve .ma.
    :param str fbx_file: Library-relative path to the baked FBX.
    :param str preview_file: Library-relative path to the preview still.
    :param str gif_file: Library-relative path to the looping preview.
    :param list frame_range: ``[start, end]``.
    :param float fps: Frames per second the clip was authored at.
    :param str root_motion: One of clip.ROOT_MOTION_VALUES.
    :param list tags: Free-text tags.
    :param str description: Free text.
    :param str source_file: Where the clip came from, for provenance.
    :param bool has_layers: Whether the curve file carries animation layers.
    :param int flag_count: How many flags the clip animates.
    :param str clip_type: 'animation' or 'pose'.
    :param bool replace: Overwrite an existing clip with the same id.
    :return: Response with the registered clip.
    :rtype: dict
    """

    if not name:
        raise ValueError('name is required.')
    if root_motion not in clip_module.ROOT_MOTION_VALUES:
        raise ValueError('root_motion must be one of: {}.'
                         .format(', '.join(clip_module.ROOT_MOTION_VALUES)))
    if clip_type not in clip_module.CLIP_TYPES:
        raise ValueError('clip_type must be one of: {}.'
                         .format(', '.join(clip_module.CLIP_TYPES)))

    entry = clip_module.AnimClip.create(
        name=name, character=character, category=category,
        frame_range=list(frame_range or [0, 0]), fps=float(fps), root_motion=root_motion,
        tags=list(tags or []), description=description, source_file=source_file,
        has_layers=bool(has_layers), flag_count=int(flag_count or 0), clip_type=clip_type)
    for kind, path in (('curves', curves_file), ('fbx', fbx_file),
                       ('preview', preview_file), ('gif', gif_file)):
        if path:
            entry.set_artifact(kind, path)

    catalog = get_catalog()
    catalog.add(entry, replace=replace)
    catalog.save()
    note = '' if entry.is_applicable else (' It has neither curves nor a baked skeleton, so it '
                                           'cannot be applied to a rig yet.')
    return _clip_to_dict(entry, verbose=True), 'Registered {} as {!r}.{}'.format(
        entry.name, entry.clip_id, note)


@_safe
def update_clip(clip_id, fields):
    """
    Change fields on a clip.

    :param str clip_id: Clip id or display name.
    :param dict fields: Field name to new value; see describe_schema.
    :return: Response with the updated clip.
    :rtype: dict
    """

    entry = _require_clip(clip_id)
    if not fields:
        raise ValueError('fields is required: pass at least one field to change.')
    if not isinstance(fields, dict):
        raise ValueError('fields must be a mapping of field name to new value.')
    if 'root_motion' in fields and fields['root_motion'] not in clip_module.ROOT_MOTION_VALUES:
        raise ValueError('root_motion must be one of: {}.'
                         .format(', '.join(clip_module.ROOT_MOTION_VALUES)))
    if 'clip_type' in fields and fields['clip_type'] not in clip_module.CLIP_TYPES:
        raise ValueError('clip_type must be one of: {}.'
                         .format(', '.join(clip_module.CLIP_TYPES)))

    catalog = get_catalog()
    catalog.update(entry.clip_id, fields)
    catalog.save()
    return (_clip_to_dict(entry, verbose=True),
            'Updated {} on {}.'.format(', '.join(sorted(fields)), entry.name))


@_safe
def set_clip_file(clip_id, kind, file_path):
    """
    Point a clip at one of its files.

    :param str clip_id: Clip id or display name.
    :param str kind: 'curves', 'fbx' or 'preview'.
    :param str file_path: Absolute path, or one relative to the library root.
        Empty clears the reference.
    :return: Response with the clip's files.
    :rtype: dict
    """

    entry = _require_clip(clip_id)
    catalog = get_catalog()

    relative = ''
    if file_path:
        absolute = os.path.normpath(file_path)
        if not os.path.isabs(absolute):
            absolute = os.path.normpath(os.path.join(catalog.library_root, absolute))
        if not os.path.isfile(absolute):
            raise ValueError('No file at {}.'.format(absolute))
        try:
            relative = os.path.relpath(absolute, catalog.library_root).replace('\\', '/')
        except ValueError:
            raise ValueError('{} is not inside the library root ({}). Clip files have to live '
                             'in the library so it stays self-contained.'
                             .format(absolute, catalog.library_root))
        if relative.startswith('..'):
            raise ValueError('{} is outside the library root ({}).'
                             .format(absolute, catalog.library_root))

    entry.set_artifact(kind, relative)
    entry.data['updated'] = catalog_module.utc_stamp()
    catalog.save()
    action = 'now points at {}'.format(relative) if relative else 'no longer has a {}'.format(kind)
    return get_clip_files(entry.clip_id)['result'], '{} {}.'.format(entry.name, action)


@_safe
def remove_clip(clip_id, delete_files=False):
    """
    Remove a clip from the catalog.

    :param str clip_id: Clip id or display name.
    :param bool delete_files: Also delete its files from disk. Off by default:
        losing an index entry is recoverable, losing the animation is not.
    :return: Response with what was removed.
    :rtype: dict
    """

    entry = _require_clip(clip_id)
    catalog = get_catalog()
    deleted = []
    stuck = []
    if delete_files:
        for kind in clip_module.ARTIFACT_KINDS:
            path = entry.artifact_path(kind, catalog.library_root)
            if not path or not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                deleted.append(kind)
            except OSError as exc:
                # A file another program has open - a preview still playing, a
                # DCC with it loaded - must not take the whole removal down with
                # it. Say which one and carry on: half-deleting a clip and then
                # raising would leave the catalog describing files that are gone.
                logger.warning('Could not delete %s: %s', path, exc)
                stuck.append(kind)
    catalog.remove(entry.clip_id)
    catalog.save()
    message = 'Removed {} from the library.'.format(entry.name)
    if deleted:
        message += ' Deleted its {}.'.format(', '.join(deleted))
    if stuck:
        message += (' Could not delete its {} - something else has the file open.'
                    .format(', '.join(stuck)))
    elif not delete_files:
        message += ' Its files were left on disk.'
    return ({'clip_id': entry.clip_id, 'name': entry.name,
             'deleted_files': deleted, 'undeleted_files': stuck}, message)


@_safe
def describe_schema():
    """
    Every field a clip carries, and the controlled values.

    :return: Response with ``{'fields', 'artifact_kinds', 'root_motion_values', 'notes'}``.
    :rtype: dict
    """

    result = {
        'fields': sorted(clip_module.DEFAULTS),
        'artifact_kinds': list(clip_module.ARTIFACT_KINDS),
        'root_motion_values': list(clip_module.ROOT_MOTION_VALUES),
        'clip_types': list(clip_module.CLIP_TYPES),
        'notes': [
            'clip_id is derived from character + name and cannot be changed; remove and '
            're-register to rename.',
            'curves is the master artifact - a small .ma of the stored curve network, which '
            'keeps animation layers. fbx is derived from it for other DCCs and can always be '
            'rebuilt; when the two disagree, curves wins.',
            'root_motion is recorded here because neither the .ma nor the .fbx states it, and '
            'it is the first thing an FBX consumer needs to know.',
            'Clip files must live inside the library root so the library stays self-contained.',
            'clip_type separates poses from animations. A pose is mechanically the same record '
            'with its keys on one frame; the split exists because animators reach for the two '
            'differently.',
        ],
    }
    return result, '{} clip fields, {} artifact kinds.'.format(
        len(result['fields']), len(result['artifact_kinds']))


# --- Projects -----------------------------------------------------------------------------------------------------

@_safe
def list_projects():
    """
    Every library root the user has named, and which one is current.

    :return: Response with ``[{'name', 'root', 'current', 'exists'}]``.
    :rtype: dict
    """

    rows = projects_module.all_projects()
    current = next((r['name'] for r in rows if r['current']), '')
    missing = [r['name'] for r in rows if not r['exists']]
    message = '{} project(s); {!r} is current.'.format(len(rows), current)
    if missing:
        message += ' No folder yet for: {}.'.format(', '.join(missing))
    return rows, message


@_safe
def current_project():
    """
    The project the library is reading from right now.

    :return: Response with ``{'name', 'root', 'exists'}``.
    :rtype: dict
    """

    project = projects_module.current()
    project['exists'] = os.path.isdir(project['root'])
    return project, 'Current project is {!r} at {}.'.format(project['name'], project['root'])


@_safe
def add_project(name, root, make_current=True):
    """
    Remember a library root under a name.

    The folder need not exist yet - pointing at a library you are about to fill
    is normal, and the first capture creates it.

    :param str name: What to call it.
    :param str root: The library root folder.
    :param bool make_current: Switch to it once added.
    :return: Response with the stored project.
    :rtype: dict
    """

    project = projects_module.add(name, root, make_current=make_current)
    if make_current:
        get_catalog(force_reload=True)
    return project, 'Added project {!r} at {}.{}'.format(
        project['name'], project['root'], ' Switched to it.' if make_current else '')


@_safe
def remove_project(name):
    """
    Forget a project. The library on disk is left alone.

    :param str name: Project name.
    :return: Response with the removed project.
    :rtype: dict
    """

    removed = projects_module.remove(name)
    get_catalog(force_reload=True)
    return removed, ('Removed project {!r} from the list. Its library at {} is untouched.'
                     .format(removed['name'], removed['root']))


@_safe
def set_current_project(name):
    """
    Switch which library the browser and the tools read.

    :param str name: Project name.
    :return: Response with the now-current project and its clip count.
    :rtype: dict
    """

    project = projects_module.set_current(name)
    catalog = get_catalog(force_reload=True)
    project['clip_count'] = len(catalog)
    return project, 'Switched to {!r} - {} clip(s) at {}.'.format(
        project['name'], len(catalog), project['root'])


# --- Folders ------------------------------------------------------------------------------------------------------

@_safe
def list_folders(character=None):
    """
    The category folders in the library.

    Merges what the catalog knows (categories that have clips) with what is on
    disk (folders somebody has made and not filled yet). A folder created a
    moment ago and still empty is an ordinary state, and leaving it out would
    make creating one look like it did nothing.

    :param str character: Restrict to one character's asset id. None walks them all.
    :return: Response with ``[{'character', 'category', 'clips', 'on_disk', 'path'}]``.
    :rtype: dict
    """

    catalog = get_catalog()
    characters = [character] if character else sorted(
        set([c.character for c in catalog.sorted_clips() if c.character]
            + catalog_module.disk_characters(catalog.library_root)))

    rows = []
    for who in characters:
        counts = dict(catalog.categories(who))
        on_disk = catalog_module.disk_categories(catalog.library_root, who)
        for name in sorted(set(list(counts) + on_disk), key=lambda x: x.lower()):
            path = catalog_module.category_folder(catalog.library_root, who, name)
            rows.append({'character': who,
                         'category': name,
                         'clips': counts.get(name, 0),
                         'on_disk': name in on_disk,
                         'path': path})
    empty = [r for r in rows if not r['clips']]
    message = '{} folder(s){}.'.format(len(rows), ' for {}'.format(character) if character else '')
    if empty:
        message += ' {} of them are empty.'.format(len(empty))
    return rows, message


@_safe
def create_folder(character, category=''):
    """
    Make a folder in the library.

    :param str character: Owning character's asset id.
    :param str category: Grouping, e.g. 'Locomotion'. Empty makes the character
        folder only.
    :return: Response with the path created.
    :rtype: dict
    """

    character = str(character or '').strip()
    category = str(category or '').strip()
    if not character:
        raise ValueError('A folder belongs to a character; pass character.')
    for part, label in ((character, 'character'), (category, 'category')):
        if not part:
            continue
        # Checked against a fixed set rather than os.path.sep, because the
        # library is read on whatever machine opens it and a name that is merely
        # awkward here is a broken path there.
        bad = sorted(set(part) & set(ILLEGAL_FOLDER_CHARACTERS))
        if bad:
            raise ValueError('A {} folder name cannot contain {}. Got {!r}.'
                             .format(label, ' '.join(repr(c) for c in bad), part))
        if part in ('.', '..') or part.endswith('.') or part.endswith(' '):
            raise ValueError('{!r} is not a usable {} folder name.'.format(part, label))

    catalog = get_catalog()
    if category:
        path = catalog_module.category_folder(catalog.library_root, character, category)
    else:
        path = os.path.normpath(os.path.join(catalog.library_root,
                                             catalog_module.CLIPS_FOLDER, character))
    existed = os.path.isdir(path)
    if not existed:
        os.makedirs(path)
    return ({'path': path, 'character': character, 'category': category, 'created': not existed},
            '{} {}.'.format('Already there:' if existed else 'Created', path))


@_safe
def remove_folder(character, category, force=False):
    """
    Remove a category folder.

    Refuses while the folder still holds clips, because "tidy up an empty
    folder" and "throw away thirty animations" are different intentions and only
    one of them should happen by accident. ``force`` does the second: it drops
    those clips from the catalog and deletes the folder and everything in it.

    :param str character: Owning character's asset id.
    :param str category: The category to remove.
    :param bool force: Delete the folder's clips and files as well.
    :return: Response with what was removed.
    :rtype: dict
    """

    character = str(character or '').strip()
    category = str(category or '').strip()
    if not character or not category:
        raise ValueError('Pass both character and category.')

    catalog = get_catalog()
    path = catalog_module.category_folder(catalog.library_root, character, category)
    held = [c for c in catalog.search(character=character, category=category)]

    if held and not force:
        raise ValueError('{}/{} still holds {} clip(s): {}. Move them first, or pass force=True '
                         'to delete the folder and everything in it.'
                         .format(character, category, len(held),
                                 ', '.join(c.name for c in held[:5])
                                 + (', ...' if len(held) > 5 else '')))

    removed_clips = []
    if force:
        for entry in held:
            catalog.remove(entry.clip_id)
            removed_clips.append(entry.clip_id)
        if removed_clips:
            catalog.save()

    deleted = False
    stuck = []
    if os.path.isdir(path):
        import shutil
        if force:
            # Collect what will not go rather than raising half way through. The
            # catalog entries are already gone by this point, so an exception
            # here would leave the library describing files nobody can find.
            shutil.rmtree(path, onerror=lambda _f, name, _e: stuck.append(name))
            deleted = not os.path.isdir(path)
        elif not os.listdir(path):
            os.rmdir(path)
            deleted = True
        else:
            # Without force the folder is only removed when it is genuinely
            # empty; a stray file in there is somebody's, not ours to bin.
            raise ValueError('{} has files in it that the catalog does not know about. Pass '
                             'force=True to delete the folder and its contents.'.format(path))

    message = 'Removed {}/{}.'.format(character, category)
    if removed_clips:
        message += ' Dropped {} clip(s).'.format(len(removed_clips))
    if stuck:
        message += (' {} file(s) could not be deleted - something else has them open, so the '
                    'folder is still on disk.'.format(len(set(stuck))))
    return ({'path': path, 'deleted': deleted, 'removed_clips': removed_clips,
             'undeleted': sorted(set(stuck))}, message)
