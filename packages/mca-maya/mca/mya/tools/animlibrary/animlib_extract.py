"""
Run the extraction plan: turn the depot's rig-scene animations into library clips.

:mod:`mca.common.animlib.extract_plan` works out *what* to extract without
touching Maya. This opens each planned scene, captures the clip, and writes the
result back into the plan so the run is resumable - 865 scenes at ~28 MB each is
hours of work that will be interrupted.

Run it headless over the whole set::

    mayabatch -command "python(\\"import mca.mya.tools.animlibrary.animlib_extract as x; x.run_plan()\\")"

or from inside Maya on one character at a time::

    animlib_extract.run_plan(character='frostwind', limit=10)

Each scene is opened with a new file first, so one bad scene cannot poison the
next. A failure is recorded against its entry and the run carries on.

:Requires: mca.common.animlib, mca.mya.tools.animlibrary.animlib_maya
:Side effects: Opens scenes (discarding whatever is open), writes clip files,
    and rewrites the plan file and catalog.json as it goes.
"""

# python imports
import os
import time
import traceback

# software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log
from mca.common.animlib import animlib_api, extract_plan
from mca.mya.rigging import frag
from mca.mya.tools.animlibrary import animlib_maya

logger = log.MCA_LOGGER


def default_plan_path():
    """
    Where the plan lives by default: beside the library it feeds.

    :return: Absolute path to the plan file.
    :rtype: str
    """

    return os.path.join(animlib_api.get_catalog().library_root, extract_plan.PLAN_NAME)


def build_and_write_plan(characters_root=None, plan_path=None):
    """
    Work out what to extract and save the plan.

    No scene is opened - this is filesystem work, so it is safe and quick to run
    and review before committing to the extraction itself.

    :param str characters_root: The depot's Characters folder. None asks paths.
    :param str plan_path: Where to write the plan. None uses the default.
    :return: ``(plan, summary, plan_path)``.
    :rtype: tuple
    """

    from mca.common.assetlist import get_asset_manager
    from mca.common.paths import paths

    characters_root = characters_root or paths.get_characters_path()

    # Character folder names to real asset ids. Where two records answer to the
    # same name, prefer the one whose files actually resolve - the depot has
    # duplicate character records and only one of each pair is usable.
    name_map = {}
    for record in get_asset_manager().iter_all():
        if record.category != 'Characters':
            continue
        entry = record.source_entry
        resolves = bool(entry and (entry.resolve_file('rig') or entry.resolve_file('skin')))
        key = (record.name or '').lower()
        if key and (key not in name_map or resolves):
            name_map[key] = record.asset_id

    plan = extract_plan.build_plan(characters_root, name_to_asset_id=name_map)
    plan_path = plan_path or default_plan_path()
    extract_plan.write_plan(plan, plan_path)
    return plan, extract_plan.summarise(plan), plan_path


def previews_are_possible():
    """
    Can this Maya grab a thumbnail?

    Playblast needs a viewport. In a ``mayabatch`` run there is not one, and
    asking anyway produces either nothing or a hang - so a headless extraction
    writes clips without previews and a later interactive pass fills them in.

    :return: True when running interactively.
    :rtype: bool
    """

    try:
        return not pm.about(batch=True)
    except Exception:
        return False


def extract_one(entry, replace=False, capture_preview=None):
    """
    Open one planned scene and capture it as a clip.

    :param dict entry: A plan entry.
    :param bool replace: Overwrite a clip that already exists.
    :param bool capture_preview: Grab a thumbnail while the scene is open. None
        means "when we can" - see :func:`previews_are_possible`. Extraction is
        the cheap moment for this: the animated scene is already open, so a
        preview costs one playblast instead of a re-apply later.
    :return: ``(status, message)`` where status is a STATUS_* value.
    :rtype: tuple
    """

    if capture_preview is None:
        capture_preview = previews_are_possible()

    source = entry.get('source')
    if not source or not os.path.isfile(source):
        return extract_plan.STATUS_FAILED, 'Source file is missing: {}'.format(source)

    try:
        # A clean file first: whatever the last scene left behind must not
        # follow us into this one.
        pm.newFile(force=True)
        pm.openFile(source, force=True, loadReferenceDepth='none', prompt=False)
    except Exception as exc:
        return extract_plan.STATUS_FAILED, 'Could not open the scene: {}'.format(exc)

    rigs = frag.get_frag_rigs()
    if not rigs:
        return extract_plan.STATUS_SKIPPED, 'No FRAG rig in this scene - nothing to capture.'
    if len(rigs) > 1:
        logger.info('%s has %d rigs; capturing the first.', entry['name'], len(rigs))

    response = animlib_maya.capture_clip(
        name=entry['name'],
        frag_rig=rigs[0],
        category=entry.get('category') or 'Uncategorised',
        character=entry.get('character') or None,
        description='',
        export_fbx=True,
        capture_preview=capture_preview,
        replace=replace)

    if not response['ok']:
        return extract_plan.STATUS_FAILED, response['message']
    return extract_plan.STATUS_DONE, response['message']


def run_plan(plan_path=None, character=None, limit=0, replace=False, save_every=5,
             capture_preview=None):
    """
    Work through the plan, capturing each scene as a clip.

    Safe to stop and restart: entries are marked as they complete and only
    pending ones are retried.

    :param str plan_path: Path to the plan. None uses the default.
    :param str character: Only process this character's asset id.
    :param int limit: Stop after this many entries. 0 means all of them.
    :param bool replace: Overwrite clips that already exist.
    :param int save_every: Write the plan back to disk every N entries, so an
        interrupted run loses at most this many results.
    :param bool capture_preview: Grab a thumbnail per clip. None means "when we
        can" - on interactively, off under mayabatch.
    :return: A summary of what the run did.
    :rtype: dict
    """

    plan_path = plan_path or default_plan_path()
    plan = extract_plan.read_plan(plan_path)
    if not plan:
        raise ValueError('No extraction plan at {}. Run build_and_write_plan() first.'
                         .format(plan_path))

    pending = extract_plan.pending_entries(plan)
    if character:
        pending = [e for e in pending if (e.get('character') or '').lower() == character.lower()]
    if limit:
        pending = pending[:int(limit)]

    logger.info('Extracting %d clip(s) from %s', len(pending), plan['characters_root'])
    counts = {extract_plan.STATUS_DONE: 0, extract_plan.STATUS_FAILED: 0,
              extract_plan.STATUS_SKIPPED: 0}
    started = time.time()

    for index, entry in enumerate(pending, start=1):
        try:
            status, message = extract_one(entry, replace=replace,
                                          capture_preview=capture_preview)
        except Exception as exc:
            logger.error('Extracting %s blew up:\n%s', entry.get('name'), traceback.format_exc())
            status, message = extract_plan.STATUS_FAILED, '{}: {}'.format(type(exc).__name__, exc)

        entry['status'] = status
        entry['message'] = message
        counts[status] = counts.get(status, 0) + 1
        logger.info('[%d/%d] %s %s - %s', index, len(pending), status.upper(),
                    entry.get('name'), message)

        if save_every and index % save_every == 0:
            extract_plan.write_plan(plan, plan_path)

    extract_plan.write_plan(plan, plan_path)
    elapsed = time.time() - started
    summary = {'processed': len(pending), 'elapsed_seconds': round(elapsed, 1)}
    summary.update(counts)
    logger.info('Extraction finished: %s', summary)
    return summary


def retry_failed(plan_path=None):
    """
    Put every failed entry back to pending so the next run picks them up.

    :param str plan_path: Path to the plan. None uses the default.
    :return: How many entries were reset.
    :rtype: int
    """

    plan_path = plan_path or default_plan_path()
    plan = extract_plan.read_plan(plan_path)
    if not plan:
        raise ValueError('No extraction plan at {}.'.format(plan_path))
    reset = 0
    for entry in plan.get('entries') or []:
        if entry.get('status') == extract_plan.STATUS_FAILED:
            entry['status'] = extract_plan.STATUS_PENDING
            entry['message'] = ''
            reset += 1
    extract_plan.write_plan(plan, plan_path)
    return reset


def plan_report(plan_path=None):
    """
    Where the extraction has got to.

    :param str plan_path: Path to the plan. None uses the default.
    :return: The plan summary plus the first few failures.
    :rtype: dict
    """

    plan_path = plan_path or default_plan_path()
    plan = extract_plan.read_plan(plan_path)
    if not plan:
        return {'plan': None, 'message': 'No plan at {}.'.format(plan_path)}
    summary = extract_plan.summarise(plan)
    failures = [{'name': e['name'], 'message': e['message']}
                for e in (plan.get('entries') or [])
                if e.get('status') == extract_plan.STATUS_FAILED][:20]
    summary['failures'] = failures
    return summary
