"""
One animation clip in the library.

A clip is a named piece of animation plus the files that carry it. It is
deliberately a thin record over a dict so it round-trips through the catalog
JSON without a serialisation layer.

Three artifacts, and the asymmetry between them matters:

``curves``
    A small ``.ma`` holding only the stored curve network - the output of
    ``AnimatedCurvesComponent.export``. This is the **master**: it keeps
    authoring intent (flag values, animation layers, IK/FK state) and it is what
    an animator applies to a rig.
``fbx``
    A baked skeleton, joints only. Portable to Blender, MotionBuilder and the
    engine, but flattened - layers and flag context are gone. **Derived**: it can
    always be rebuilt from ``curves``, so when the two disagree, ``curves`` wins.
``preview``
    A single playblast frame for the browser. Cosmetic, regenerable.
``gif``
    A looping playblast of the whole clip. Also cosmetic, also regenerable, and
    the only artifact that shows what the animation actually does - a still
    frame of a run cycle and a still frame of a walk cycle look identical.

A clip may legitimately have only some of these. ``curves`` missing means the
clip cannot be applied to a rig; ``fbx`` missing means it has not been exported
yet, not that it is broken.

:Requires: nothing - plain data.
:Side effects: none.
"""

# python imports
import os
import re


# Artifact keys, in the order a browser should prefer them when it needs "the"
# file for a clip.
ARTIFACT_KINDS = ('curves', 'fbx', 'preview', 'gif')

# How a clip says whether its root travels. An FBX consumer asks this first, and
# neither the .ma nor the .fbx states it, so the catalog has to.
ROOT_MOTION_VALUES = ('unknown', 'in_place', 'travelling')

# What kind of thing the clip is. A pose is a clip whose keys all sit on one
# frame; mechanically it is the same record and the same .ma, but animators
# reach for the two in completely different ways, so the library keeps them
# apart rather than making somebody read the frame range to tell.
CLIP_TYPES = ('animation', 'pose')

DEFAULTS = {
    'clip_id': '',
    'name': '',
    'clip_type': 'animation',
    'character': '',
    'category': 'Uncategorised',
    'tags': [],
    'description': '',
    'frame_range': [0, 0],
    'fps': 30.0,
    'root_motion': 'unknown',
    'has_layers': False,
    'flag_count': 0,
    'artifacts': {},
    'source_file': '',
    'created': '',
    'updated': '',
}


def build_clip_id(character, name):
    """
    Build the catalog key for a clip.

    Qualified by character on purpose: two characters both having a clip called
    ``Idle_01`` is normal, and an unqualified id would collide - the same
    mistake the asset list had to be migrated out of.

    :param str character: Owning character's asset id.
    :param str name: Clip display name.
    :return: A lowercase, underscore-separated id.
    :rtype: str
    """

    parts = [str(character or '').strip(), str(name or '').strip()]
    slug = '_'.join(p for p in parts if p)
    slug = re.sub(r'[^A-Za-z0-9]+', '_', slug).strip('_').lower()
    return slug


class AnimClip(object):
    """
    A single catalog entry.
    """

    def __init__(self, data=None):
        """
        :param dict data: Raw record, as stored in the catalog.
        """

        merged = {}
        for key, value in DEFAULTS.items():
            merged[key] = list(value) if isinstance(value, list) else (
                dict(value) if isinstance(value, dict) else value)
        merged.update(data or {})
        self._data = merged

    # --- Construction ------------------------------------------------------ #

    @classmethod
    def create(cls, name, character, category='Uncategorised', **fields):
        """
        Build a new clip record.

        :param str name: Display name.
        :param str character: Owning character's asset id.
        :param str category: Grouping, e.g. 'Locomotion'.
        :param fields: Any other record field.
        :return: The new clip.
        :rtype: AnimClip
        """

        data = dict(fields)
        data.update({'name': name, 'character': character, 'category': category,
                     'clip_id': fields.get('clip_id') or build_clip_id(character, name)})
        return cls(data)

    # --- Access ------------------------------------------------------------ #

    @property
    def data(self):
        """
        :return: The raw record. Mutating this mutates the clip.
        :rtype: dict
        """

        return self._data

    def get(self, key, default=None):
        """
        :param str key: Field name.
        :param default: Returned when the field is unset.
        :return: The field value.
        """

        return self._data.get(key, default)

    def __getattr__(self, item):
        # Fields read as attributes; anything not a known field is a real
        # AttributeError so typos surface instead of returning None.
        if item.startswith('_'):
            raise AttributeError(item)
        data = self.__dict__.get('_data') or {}
        if item in data:
            return data[item]
        raise AttributeError('{!r} is not a clip field. Known: {}'
                             .format(item, ', '.join(sorted(DEFAULTS))))

    def __repr__(self):
        return '<AnimClip {!r} ({})>'.format(self.clip_id, self.character or 'no character')

    def __eq__(self, other):
        return isinstance(other, AnimClip) and other.clip_id == self.clip_id

    def __hash__(self):
        return hash(self.clip_id)

    # --- Artifacts --------------------------------------------------------- #

    def artifact(self, kind):
        """
        The library-relative path of one artifact.

        :param str kind: A key from :data:`ARTIFACT_KINDS`.
        :return: Relative path, or '' when the clip has no such file.
        :rtype: str
        """

        return (self._data.get('artifacts') or {}).get(kind, '') or ''

    def set_artifact(self, kind, relative_path):
        """
        Record one artifact, or clear it.

        :param str kind: A key from :data:`ARTIFACT_KINDS`.
        :param str relative_path: Path relative to the library root. Empty clears.
        :raises ValueError: On an unknown kind.
        """

        if kind not in ARTIFACT_KINDS:
            raise ValueError('{!r} is not an artifact kind. Valid: {}.'
                             .format(kind, ', '.join(ARTIFACT_KINDS)))
        artifacts = dict(self._data.get('artifacts') or {})
        if relative_path:
            artifacts[kind] = relative_path.replace('\\', '/')
        else:
            artifacts.pop(kind, None)
        self._data['artifacts'] = artifacts

    def artifact_path(self, kind, library_root):
        """
        The absolute path of one artifact.

        :param str kind: A key from :data:`ARTIFACT_KINDS`.
        :param str library_root: The library root folder.
        :return: Absolute path, or '' when unrecorded.
        :rtype: str
        """

        relative = self.artifact(kind)
        if not relative:
            return ''
        return os.path.normpath(os.path.join(library_root, relative))

    def missing_artifacts(self, library_root):
        """
        Which recorded artifacts are not on disk.

        Only recorded ones count - an unrecorded FBX is "not exported yet",
        which is different from "the file went missing".

        :param str library_root: The library root folder.
        :return: Artifact kinds whose recorded file is absent.
        :rtype: list[str]
        """

        missing = []
        for kind in ARTIFACT_KINDS:
            path = self.artifact_path(kind, library_root)
            if path and not os.path.isfile(path):
                missing.append(kind)
        return missing

    @property
    def is_pose(self):
        """
        :return: True when the clip is a single-frame pose.
        :rtype: bool
        """

        return str(self._data.get('clip_type') or 'animation') == 'pose'

    @property
    def has_curves(self):
        """
        :return: True when the clip carries flag curves.
        :rtype: bool
        """

        return bool(self.artifact('curves'))

    @property
    def has_baked_joints(self):
        """
        :return: True when the clip carries a baked skeleton.
        :rtype: bool
        """

        return bool(self.artifact('fbx'))

    @property
    def is_applicable(self):
        """
        :return: True when the clip can be put back onto a rig at all.

            Flag curves are the direct route. A baked skeleton is the other one:
            it has to be imported and baked back through the rig, which is
            slower and loses the flag-level authoring, but it is animation and
            it does go on, so an FBX-only clip is not a dead end.
        :rtype: bool
        """

        return self.has_curves or self.has_baked_joints

    # --- Derived ----------------------------------------------------------- #

    @property
    def duration(self):
        """
        :return: Length in frames, 0 when the range is unset or malformed.
        :rtype: float
        """

        frame_range = self._data.get('frame_range') or [0, 0]
        try:
            return max(0.0, float(frame_range[1]) - float(frame_range[0]))
        except (TypeError, ValueError, IndexError):
            return 0.0

    @property
    def duration_seconds(self):
        """
        :return: Length in seconds at the clip's own fps, 0 when fps is unusable.
        :rtype: float
        """

        try:
            fps = float(self._data.get('fps') or 0)
        except (TypeError, ValueError):
            return 0.0
        return self.duration / fps if fps else 0.0

    def matches(self, query):
        """
        Free-text match against name, character, category, tags and description.

        :param str query: Search text; empty matches everything.
        :return: True on a match.
        :rtype: bool
        """

        query = str(query or '').strip().lower()
        if not query:
            return True
        haystack = ' '.join([
            str(self._data.get('name') or ''),
            str(self._data.get('character') or ''),
            str(self._data.get('category') or ''),
            str(self._data.get('description') or ''),
            ' '.join(str(t) for t in (self._data.get('tags') or [])),
        ]).lower()
        return all(term in haystack for term in query.split())
