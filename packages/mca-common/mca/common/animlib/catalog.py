"""
The animation library catalog: one JSON index over every clip.

The catalog lives at ``<library root>/catalog.json`` and the clip files live in
``<library root>/clips/<character>/<category>/``. Nothing in the depot's existing
``Characters/.../Animations`` folders is moved or touched - the library builds
its own small curve files beside its own index, and records where each one came
from in the clip's ``source_file``.

Why a central index rather than per-character files: cross-character search is
the thing a browser does constantly ("every roll animation we have"), and
stitching thirty files together on every keystroke to answer it is the wrong
trade. One file is also one thing to check in.

:Requires: mca.common.textio
:Side effects: :meth:`AnimCatalog.save` writes catalog.json.
"""

# python imports
import os
import datetime

# MCA python imports
from mca.common import log
from mca.common import sourcecontrol
from mca.common.animlib import clip as clip_module
from mca.common.textio import jsonio
from mca.common.utils import fileio

logger = log.MCA_LOGGER

CATALOG_NAME = 'catalog.json'
CLIPS_FOLDER = 'clips'
CATALOG_VERSION = 1


def utc_stamp():
    """
    :return: An ISO-8601 UTC timestamp for created/updated fields.
    :rtype: str
    """

    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def get_library_root():
    """
    The current project's library root folder.

    Out of the box this is the folder beside Assetlist under the common tools
    path, so the library travels with the rest of the pipeline data rather than
    living somewhere a new machine has to be told about. Once somebody has added
    a second library and switched to it, this follows them - see
    :mod:`mca.common.animlib.projects`.

    :return: Absolute path to the library root.
    :rtype: str
    """

    from mca.common.animlib import projects
    try:
        return os.path.normpath(projects.current_root())
    except Exception:
        # A corrupt or unreadable projects file must not make the library
        # unopenable; the shipped root is always a valid answer.
        logger.warning('Could not read the animation library project list; using the default '
                       'library root.', exc_info=True)
        return projects.get_default_root()


def category_folder(library_root, character, category):
    """
    The absolute folder a character's category lives in.

    :param str library_root: The library root.
    :param str character: Owning character's asset id.
    :param str category: Grouping, e.g. 'Locomotion'.
    :return: Absolute path. The folder need not exist.
    :rtype: str
    """

    return os.path.normpath(os.path.join(library_root,
                                         clip_relative_dir(character, category)))


def disk_categories(library_root, character):
    """
    Category folders present on disk for a character.

    The catalog knows the categories that have clips in them; this knows the
    ones somebody has made room for. A folder created and not yet filled is a
    perfectly ordinary state and the browser has to show it, or making a folder
    would look like it did nothing.

    :param str library_root: The library root.
    :param str character: Owning character's asset id.
    :return: Folder names, sorted.
    :rtype: list[str]
    """

    if not character:
        return []
    parent = os.path.normpath(os.path.join(library_root, CLIPS_FOLDER, str(character)))
    if not os.path.isdir(parent):
        return []
    return sorted(name for name in os.listdir(parent)
                  if os.path.isdir(os.path.join(parent, name)))


def disk_characters(library_root):
    """
    Character folders present on disk.

    :param str library_root: The library root.
    :return: Folder names, sorted.
    :rtype: list[str]
    """

    parent = os.path.normpath(os.path.join(library_root, CLIPS_FOLDER))
    if not os.path.isdir(parent):
        return []
    return sorted(name for name in os.listdir(parent)
                  if os.path.isdir(os.path.join(parent, name)))


def clip_relative_dir(character, category):
    """
    Where a clip's files belong inside the library, relative to the root.

    :param str character: Owning character's asset id.
    :param str category: Grouping, e.g. 'Locomotion'.
    :return: Relative folder, forward-slashed.
    :rtype: str
    """

    parts = [CLIPS_FOLDER, str(character or 'unassigned'), str(category or 'Uncategorised')]
    return '/'.join(p.strip('/\\') for p in parts if p)


class AnimCatalog(object):
    """
    Load, query and save the clip index.
    """

    def __init__(self, library_root=None, data=None):
        """
        :param str library_root: Library root folder. Defaults to :func:`get_library_root`.
        :param dict data: Pre-loaded catalog dict, mostly for tests.
        """

        self.library_root = os.path.normpath(library_root or get_library_root())
        self._clips = {}
        if data:
            self._ingest(data)

    # --- Loading / saving -------------------------------------------------- #

    @property
    def catalog_path(self):
        """
        :return: Absolute path to catalog.json.
        :rtype: str
        """

        return os.path.join(self.library_root, CATALOG_NAME)

    def _ingest(self, data):
        """
        Replace the in-memory clips from a raw catalog dict.

        A record without a ``clip_id`` is keyed by one derived from its character and name
        rather than dropped, so a hand-edited catalog still loads. A record with no name at
        all is dropped: ``build_clip_id`` answers the character on its own for one, so the
        version this replaces kept it under the character's own name as a clip id - where it
        would collide with the next nameless record for that character, and read in a browser
        as a clip with no name.

        :param dict data: Raw catalog contents.
        """

        self._clips = {}
        for record in (data.get('clips') or []):
            if not isinstance(record, dict):
                logger.warning('Skipping a catalog entry that is not a record: %r', record)
                continue
            entry = clip_module.AnimClip(record)
            clip_id = entry.clip_id
            if not clip_id and entry.name:
                clip_id = clip_module.build_clip_id(entry.character, entry.name)
            if not clip_id:
                logger.warning('Skipping a catalog entry with no id and no name: %r', record)
                continue
            entry.data['clip_id'] = clip_id
            if clip_id in self._clips:
                logger.warning('Duplicate clip id %r in the catalog; keeping the first.', clip_id)
                continue
            self._clips[clip_id] = entry

    @classmethod
    def load(cls, library_root=None):
        """
        Read the catalog from disk, or return an empty one.

        A missing catalog is not an error - it is what a library that has never
        been populated looks like.

        :param str library_root: Library root folder.
        :return: The catalog.
        :rtype: AnimCatalog
        """

        catalog = cls(library_root=library_root)
        if not os.path.isfile(catalog.catalog_path):
            logger.debug('No catalog at %s yet.', catalog.catalog_path)
            return catalog
        data = jsonio.read_json_file(catalog.catalog_path)
        if not data:
            logger.warning('Catalog at %s could not be read or was empty.', catalog.catalog_path)
            return catalog
        catalog._ingest(data)
        return catalog

    def save(self):
        """
        Write the catalog to disk, creating the library root if needed.

        :return: The path written.
        :rtype: str
        """

        if not os.path.isdir(self.library_root):
            os.makedirs(self.library_root, exist_ok=True)

        payload = {
            'version': CATALOG_VERSION,
            'updated': utc_stamp(),
            'clips': [entry.data for entry in self.sorted_clips()],
        }

        # The library usually lives under the common tools path, which is in source control,
        # so the catalog is a versioned file like any other: the second save would otherwise
        # be writing to a read-only file, and the first one would never be added. Where the
        # library is somewhere source control has never heard of, this says so at debug level
        # and the write goes ahead regardless.
        existed = os.path.isfile(self.catalog_path)
        fileio.touch_path(self.catalog_path)
        if existed:
            sourcecontrol.checkout(self.catalog_path)

        jsonio.write_to_json_file(payload, self.catalog_path)
        if not existed:
            sourcecontrol.add(self.catalog_path)

        logger.debug('Wrote %d clip(s) to %s', len(self._clips), self.catalog_path)

        return self.catalog_path

    # --- Queries ----------------------------------------------------------- #

    def __len__(self):
        return len(self._clips)

    def __contains__(self, clip_id):
        return clip_id in self._clips

    def sorted_clips(self):
        """
        :return: Every clip, ordered by character then category then name.
        :rtype: list[clip_module.AnimClip]
        """

        return sorted(self._clips.values(),
                      key=lambda c: ((c.character or '').lower(),
                                     (c.category or '').lower(),
                                     (c.name or '').lower()))

    def get(self, clip_id):
        """
        :param str clip_id: The clip's id.
        :return: The clip, or None.
        :rtype: clip_module.AnimClip or None
        """

        return self._clips.get(clip_id)

    def get_by_name(self, name, character=None):
        """
        Find a clip by display name, optionally within one character.

        :param str name: Display name.
        :param str character: Restrict to this character's asset id.
        :return: The first match, or None.
        :rtype: clip_module.AnimClip or None
        """

        wanted = str(name or '').strip().lower()
        for entry in self.sorted_clips():
            if (entry.name or '').lower() != wanted:
                continue
            if character and (entry.character or '').lower() != str(character).lower():
                continue
            return entry
        return None

    def search(self, query='', character=None, category=None, applicable_only=False):
        """
        Filter the catalog.

        :param str query: Free text matched against name, tags and description.
        :param str character: Restrict to one character's asset id.
        :param str category: Restrict to one category.
        :param bool applicable_only: Only clips that have a curve file.
        :return: Matching clips, in catalog order.
        :rtype: list[clip_module.AnimClip]
        """

        results = []
        for entry in self.sorted_clips():
            if character and (entry.character or '').lower() != str(character).lower():
                continue
            if category and (entry.category or '').lower() != str(category).lower():
                continue
            if applicable_only and not entry.is_applicable:
                continue
            if not entry.matches(query):
                continue
            results.append(entry)
        return results

    def characters(self):
        """
        :return: Every character asset id that owns a clip, with its clip count.
        :rtype: list[tuple]
        """

        counts = {}
        for entry in self._clips.values():
            key = entry.character or ''
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items())

    def categories(self, character=None):
        """
        :param str character: Restrict to one character's asset id.
        :return: Every category in use, with its clip count.
        :rtype: list[tuple]
        """

        counts = {}
        for entry in self._clips.values():
            if character and (entry.character or '').lower() != str(character).lower():
                continue
            key = entry.category or 'Uncategorised'
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items())

    # --- Mutation ---------------------------------------------------------- #

    def add(self, entry, replace=False):
        """
        Put a clip into the catalog.

        :param clip_module.AnimClip entry: The clip.
        :param bool replace: Overwrite an existing clip with the same id.
        :return: The stored clip.
        :rtype: clip_module.AnimClip
        :raises ValueError: On a duplicate id when replace is False.
        """

        clip_id = entry.clip_id or clip_module.build_clip_id(entry.character, entry.name)
        if not clip_id:
            raise ValueError('A clip needs a name before it can be added.')
        entry.data['clip_id'] = clip_id
        if clip_id in self._clips and not replace:
            raise ValueError('A clip with id {!r} is already in the library. Pass replace=True '
                             'to overwrite it, or give this one another name.'.format(clip_id))
        stamp = utc_stamp()
        # Not setdefault: AnimClip fills every field from DEFAULTS, so 'created'
        # is already present as '' by the time it gets here.
        if clip_id in self._clips:
            entry.data['created'] = self._clips[clip_id].get('created') or stamp
        elif not entry.data.get('created'):
            entry.data['created'] = stamp
        entry.data['updated'] = stamp
        self._clips[clip_id] = entry
        return entry

    def update(self, clip_id, fields):
        """
        Change fields on an existing clip.

        :param str clip_id: The clip's id.
        :param dict fields: Field name to new value.
        :return: The updated clip.
        :rtype: clip_module.AnimClip
        :raises ValueError: When the clip is unknown, or a field is not a clip field.
        """

        entry = self._clips.get(clip_id)
        if entry is None:
            raise ValueError('No clip with id {!r} in the library.'.format(clip_id))
        unknown = sorted(set(fields) - set(clip_module.DEFAULTS))
        if unknown:
            raise ValueError('Unknown clip field(s): {}. Known: {}.'
                             .format(', '.join(unknown), ', '.join(sorted(clip_module.DEFAULTS))))
        if 'clip_id' in fields and fields['clip_id'] != clip_id:
            raise ValueError('A clip id cannot be changed; remove the clip and add it again.')
        entry.data.update(fields)
        entry.data['updated'] = utc_stamp()
        return entry

    def remove(self, clip_id):
        """
        Drop a clip from the catalog. Files on disk are left alone.

        :param str clip_id: The clip's id.
        :return: The removed clip.
        :rtype: clip_module.AnimClip
        :raises ValueError: When the clip is unknown.
        """

        entry = self._clips.pop(clip_id, None)
        if entry is None:
            raise ValueError('No clip with id {!r} in the library.'.format(clip_id))
        return entry

    # --- Health ------------------------------------------------------------ #

    def check(self):
        """
        Report clips whose recorded files are missing or that cannot be applied.

        ``zero_length`` is the interesting one: a clip whose keys all sit on a
        single frame. That is usually a pose file that wandered into an
        animation folder, or a scene somebody saved mid-edit. It is legitimate
        data and the clip still applies, so it is reported rather than rejected -
        but silently shelving a 0-frame "animation" is how a library starts
        losing people's trust.

        :return: ``{'missing_files', 'no_curves', 'no_character', 'zero_length'}``
        :rtype: dict
        """

        report = {'missing_files': [], 'no_curves': [], 'no_character': [], 'zero_length': []}
        for entry in self.sorted_clips():
            missing = entry.missing_artifacts(self.library_root)
            if missing:
                report['missing_files'].append({'clip_id': entry.clip_id, 'missing': missing})
            if not entry.is_applicable:
                report['no_curves'].append(entry.clip_id)
            if not entry.character:
                report['no_character'].append(entry.clip_id)
            if entry.is_applicable and not entry.duration:
                report['zero_length'].append(entry.clip_id)
        return report
