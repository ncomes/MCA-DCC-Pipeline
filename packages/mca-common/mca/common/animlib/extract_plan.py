"""
Plan the one-off pass that turns the depot's rig-scene animations into library clips.

The depot holds ~1,100 ``.ma`` animation files averaging 28 MB, because each one
is a complete rig scene - hundreds of nurbs curves, joints, constraints and IK
handles - with the animation riding along inside it. The library only needs the
curves, which are a few hundred KB. Extracting them is what makes the library
browsable instead of a list of links to 28 MB files.

Planning is deliberately split from extracting. Working out *what* to extract is
pure filesystem work: it needs no Maya, runs in seconds instead of hours, and can
be reviewed before anything is opened. Only :mod:`mca.mya.tools.animlibrary.animlib_extract`
opens scenes, and it just consumes the plan this module writes.

The plan is also the resume point. Extraction over 30 GB will be interrupted -
by a crash, a bad file, or someone needing the machine - so each entry carries a
status the runner updates as it goes.

:Requires: nothing beyond the standard library.
:Side effects: :func:`write_plan` writes a JSON file.
"""

# python imports
import os
import re

# MCA python imports
from mca.common import log
from mca.common.textio import jsonio

logger = log.MCA_LOGGER

PLAN_VERSION = 1
PLAN_NAME = 'extraction_plan.json'

# Folders under a character that hold animation. '_Source' holds the authoring
# scenes; the sibling 'Animations' folder is mostly engine-bound exports.
SOURCE_MARKERS = ('_Source', 'Animations')

# Never treat these as a category or a clip - they are working detritus.
SKIP_FOLDERS = {'incrementalsave', 'incrementalsaves', '.mayaswatches', 'rawfbxs',
                'retarget_source', '_to_delete', 'archive'}

# Files that are not clips regardless of where they sit.
SKIP_NAME_PATTERNS = (
    re.compile(r'(^|[_\-])test([_\-]|$)', re.I),
    re.compile(r'\.(bak|tmp)$', re.I),
)

STATUS_PENDING = 'pending'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_SKIPPED = 'skipped'


def _is_skippable(path):
    """
    Should this file be left out of the plan?

    :param str path: Absolute path to a candidate file.
    :return: ``(skip, reason)``.
    :rtype: tuple
    """

    parts = [p.lower() for p in os.path.normpath(path).split(os.sep)]
    for part in parts:
        if part in SKIP_FOLDERS:
            return True, 'in a {} folder'.format(part)

    stem = os.path.splitext(os.path.basename(path))[0]
    for pattern in SKIP_NAME_PATTERNS:
        if pattern.search(stem):
            return True, 'name looks like scratch'
    return False, ''


def derive_category(scene_path, animations_root):
    """
    The category a clip belongs to, from where it sits under Animations.

    The first folder below ``Animations`` is the category the team already uses -
    Locomotion, Traversal, Abilities, Poses. A file sitting directly in
    ``Animations`` has no category of its own.

    :param str scene_path: Absolute path to the animation file.
    :param str animations_root: The ``Animations`` folder it was found under.
    :return: Category name.
    :rtype: str
    """

    relative = os.path.relpath(os.path.dirname(scene_path), animations_root)
    if relative in ('.', ''):
        return 'Uncategorised'
    first = relative.replace('\\', '/').split('/')[0]
    return normalise_category(first)


def normalise_category(name):
    """
    Fold category spellings that differ only by case.

    The depot has both ``Poses`` and ``POSES``; left alone they become two rows
    in the browser's tree, which is a bug the animator has to work around.

    :param str name: Folder name as found on disk.
    :return: A canonical category name.
    :rtype: str
    """

    name = str(name or '').strip()
    if not name:
        return 'Uncategorised'
    # Leave deliberate internal capitals alone (MainLocomotion, RawFBXs); only
    # fold the all-caps and all-lowercase spellings.
    if name.isupper() or name.islower():
        return '_'.join(part.capitalize() for part in name.split('_'))
    return name


def find_animation_files(characters_root, extensions=('.ma',)):
    """
    Walk the characters tree for animation files.

    :param str characters_root: The depot's Characters folder.
    :param tuple extensions: File extensions to collect, lowercase.
    :return: ``[(scene_path, animations_root)]``.
    :rtype: list[tuple]
    """

    found = []
    for folder, dirnames, filenames in os.walk(characters_root):
        dirnames[:] = [name for name in dirnames if name.lower() not in SKIP_FOLDERS]
        if os.path.basename(folder).lower() != 'animations':
            continue

        # Everything under this folder belongs to it, so walk it here and then stop the outer
        # walk from going in. The version this replaces left the outer walk to descend as
        # well, so every folder inside an Animations tree started another walk of its own
        # subtree - the same files found over and over, once per folder deep.
        for sub_folder, sub_dirnames, sub_filenames in os.walk(folder):
            sub_dirnames[:] = [name for name in sub_dirnames
                               if name.lower() not in SKIP_FOLDERS]
            for filename in sub_filenames:
                if os.path.splitext(filename)[1].lower() not in extensions:
                    continue
                found.append((os.path.join(sub_folder, filename), folder))
        dirnames[:] = []

    return found


def character_for_path(scene_path, characters_root, name_to_asset_id=None):
    """
    Which character an animation file belongs to.

    Walks up from the file to the folder that directly contains an ``Animations``
    or ``_Source`` folder - that is the character's own folder, whatever depth
    the faction nesting puts it at.

    :param str scene_path: Absolute path to the animation file.
    :param str characters_root: The depot's Characters folder.
    :param dict name_to_asset_id: Lowercase character folder name to asset id.
        Unmapped names fall back to a slug of the folder name.
    :return: ``(asset_id, folder_name)``.
    :rtype: tuple
    """

    current = os.path.dirname(os.path.normpath(scene_path))
    root = os.path.normpath(characters_root)
    folder_name = ''
    while current.startswith(root) and current != root:
        parent = os.path.dirname(current)
        base = os.path.basename(current)
        if base.lower() in ('animations', '_source'):
            folder_name = os.path.basename(parent)
            if base.lower() == 'animations' and os.path.basename(parent).lower() == '_source':
                folder_name = os.path.basename(os.path.dirname(parent))
            break
        current = parent

    if not folder_name:
        folder_name = os.path.basename(os.path.dirname(scene_path))

    lookup = name_to_asset_id or {}
    asset_id = lookup.get(folder_name.lower())
    if not asset_id:
        asset_id = re.sub(r'[^a-z0-9]+', '', folder_name.lower())
    return asset_id, folder_name


def build_plan(characters_root, name_to_asset_id=None, extensions=('.ma',)):
    """
    Work out every clip the extractor should produce.

    :param str characters_root: The depot's Characters folder.
    :param dict name_to_asset_id: Lowercase character folder name to asset id.
    :param tuple extensions: Which source files to consider.
    :return: ``{'version', 'characters_root', 'entries': [...], 'skipped': [...]}``
    :rtype: dict
    """

    entries = []
    skipped = []
    seen_ids = {}

    def _priority(pair):
        # Authoring scenes beat engine-bound exports when both spell the same
        # clip: _Source holds what an animator would want to open.
        path = pair[0]
        return (0 if '_source' in path.lower().split(os.sep) else 1, path)

    for scene_path, animations_root in sorted(find_animation_files(characters_root, extensions),
                                              key=_priority):
        skip, reason = _is_skippable(scene_path)
        if skip:
            skipped.append({'source': scene_path, 'reason': reason})
            continue

        asset_id, folder_name = character_for_path(scene_path, characters_root, name_to_asset_id)
        category = derive_category(scene_path, animations_root)
        name = os.path.splitext(os.path.basename(scene_path))[0]

        from mca.common.animlib import clip as clip_module
        clip_id = clip_module.build_clip_id(asset_id, name)

        # Two files can slug to the same id - the same clip saved under both
        # Animations/ and _Source/Animations/, say. Keep the first and record
        # the collision rather than silently overwriting a clip.
        if clip_id in seen_ids:
            skipped.append({'source': scene_path,
                            'reason': 'duplicate of {}'.format(clip_id),
                            'kept': seen_ids[clip_id]})
            continue
        seen_ids[clip_id] = scene_path

        try:
            size = os.path.getsize(scene_path)
        except OSError:
            size = 0

        entries.append({
            'clip_id': clip_id,
            'name': name,
            'character': asset_id,
            'character_folder': folder_name,
            'category': category,
            'source': scene_path,
            'source_bytes': size,
            'status': STATUS_PENDING,
            'message': '',
        })

    return {
        'version': PLAN_VERSION,
        'characters_root': os.path.normpath(characters_root),
        'entries': entries,
        'skipped': skipped,
    }


def summarise(plan):
    """
    A human-readable summary of a plan.

    :param dict plan: A plan from :func:`build_plan`.
    :return: Counts by status, character and category, plus byte totals.
    :rtype: dict
    """

    entries = plan.get('entries') or []
    by_status = {}
    by_character = {}
    by_category = {}
    total_bytes = 0
    for entry in entries:
        by_status[entry['status']] = by_status.get(entry['status'], 0) + 1
        by_character[entry['character']] = by_character.get(entry['character'], 0) + 1
        by_category[entry['category']] = by_category.get(entry['category'], 0) + 1
        total_bytes += entry.get('source_bytes') or 0
    return {
        'clips': len(entries),
        'skipped': len(plan.get('skipped') or []),
        'by_status': by_status,
        'characters': len(by_character),
        'by_character': dict(sorted(by_character.items(), key=lambda kv: -kv[1])),
        'by_category': dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        'source_bytes': total_bytes,
        'source_gb': round(total_bytes / float(1024 ** 3), 2),
    }


def write_plan(plan, plan_path):
    """
    Save a plan.

    :param dict plan: A plan from :func:`build_plan`.
    :param str plan_path: Where to write it.
    :return: The path written.
    :rtype: str
    """

    folder = os.path.dirname(plan_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    jsonio.write_to_json_file(plan, plan_path)
    return plan_path


def read_plan(plan_path):
    """
    Load a plan.

    :param str plan_path: Path to the plan file.
    :return: The plan, or None when it is missing or unreadable.
    :rtype: dict or None
    """

    if not os.path.isfile(plan_path):
        return None
    return jsonio.read_json_file(plan_path) or None


def pending_entries(plan):
    """
    The entries an extraction run still has to do.

    :param dict plan: A plan.
    :return: Entries whose status is pending.
    :rtype: list[dict]
    """

    return [e for e in (plan.get('entries') or []) if e.get('status') == STATUS_PENDING]
