"""
One asset in the registry: what it is, where it lives, and which files are its.

```python
from mca.common.assetlist import unified_entry

entry = unified_entry.UnifiedAssetEntry.create('Hero Bot', 'Characters', subtype='Heroes')
entry.path                      # 'Characters/Heroes/Hero Bot'
entry.resolve_file('rig')       # the rig file on disk, recorded or found
```

One class for every kind of asset. It replaced two - a parent asset in YAML and a gear asset
in JSON, each with its own fields - and the fields they had between them are all here:
identity, skeleton, classification, where it sits in the hierarchy, its paths, its materials,
dyes, decals, textures and attach sockets.

The substance of this module came across as it was: it is the most carefully written part of
the registry, and its comments record real investigations - why an asset id carries its
category, why a scan skips Maya's incremental-save folders, why a stored ``built_for`` stays
a plain string when there is only one. What changed:

- **An asset's folder answered None.** ``get_required_path`` swallowed every exception with a
  bare ``except Exception: pass`` and then answered None, out of a function every folder
  property joins onto - so a category with a problem in its config produced a ``TypeError``
  somewhere else entirely. It answers ``''``, and the one thing that could go wrong there no
  longer can: reading the category config does not raise.
- **``create_folders`` made a folder layout of its own.** It built six hardcoded folders -
  ``_Source/Meshes``, ``Meshes`` and so on - rather than the ones the asset's category says it
  has, so a category that had moved its meshes folder got both. It asks the category now.
- **It reached into Perforce twice**, through ``fileio.touch_and_checkout`` and
  ``fileio.add_p4_placeholders``. Which source control this is, if any, is the interface's
  business: see :mod:`mca.common.sourcecontrol`. The placeholder a folder needs to be storable
  at all is that interface's too, since Git wants one just as much as Perforce does.
- **The engine path had a project's name written into it.** ``build_engine_path`` prefixed
  ``/Game/Wayward/``. It reads :data:`ENGINE_ROOT_VARIABLE` from the environment now, so
  another project is another variable rather than another edit.
- Every one of its ninety-odd properties read ``self._fields``, which
  re-derived the asset id from the dictionary's keys on each access. The record knows its own
  fields now - see :class:`mca.common.assetlist.asset_list.AssetBaseEntry`.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common import sourcecontrol
from mca.common.assetlist import asset_list, asset_paths
from mca.common.utils import strings


logger = log.MCA_LOGGER


def is_unified_format(asset_data):
    """
    Check whether an asset data dictionary uses the unified format.

    The unified format is identified by the presence of fields that only
    exist in the new schema: 'asset_type' or 'body_type'. Falls back to
    checking for the gear format fields 'built_for' or 'slot' for
    backwards compatibility with existing JSON gear entries.

    :param dict asset_data: The inner asset data dictionary (not the wrapper).
    :return: True if the data uses the unified or new gear format.
    :rtype: bool
    """

    if not asset_data or not isinstance(asset_data, dict):
        return False
    # Unified-specific fields first
    if 'asset_type' in asset_data or 'body_type' in asset_data:
        return True
    # Fall back to existing gear format detection
    if 'built_for' in asset_data or 'slot' in asset_data:
        return True
    return False


# Ordered list of classification fields that can be reordered via the UI.
# The order in this list defines the default emission order in
# ``build_asset_path``. Each value is the inner asset_dict field name.
ORDERABLE_FIELDS = [
    'subtype',
    'faction',
    'gender',
    'asset_type',
    'skeleton',
    'body_type',
]

# Default path ordering matches the legacy hardcoded order so new assets
# behave the same as before until the user drags anything.
DEFAULT_PATH_ORDER = list(ORDERABLE_FIELDS)

# Default inclusion flags match the legacy path-building behavior:
# subtype and faction in the path, additional_types appended, and the
# newer classification fields (gender/asset_type/skeleton/body_type) excluded.
DEFAULT_PATH_FLAGS = {
    'include_subtype': True,
    'include_faction': True,
    'include_gender': False,
    'include_asset_type': False,
    'include_skeleton': False,
    'include_body_type': False,
    'include_additional_types': True,
}


def _normalize_field_value(field_key, raw_value):
    """Return the effective classification value or '' if it should not emit a path segment.

    Subtype treats 'Default' as unset to match the legacy path behavior.

    :param str field_key: One of ``ORDERABLE_FIELDS``.
    :param str raw_value: Raw value from the asset dict.
    :return: The emittable value or '' when the value should be skipped.
    :rtype: str
    """

    if not raw_value:
        return ''
    if raw_value in ('None', ''):
        return ''
    if field_key == 'subtype' and raw_value == 'Default':
        return ''
    return raw_value


def get_category_gear_settings(category):
    """
    Looks up the gear flag and gear root stored on a category in the asset config.

    Used when a path has to be regenerated without the register UI in the loop
    (API registrations, category transfers) so the result lands under the same
    folder the UI would preview. Any config problem falls back to "not gear"
    under the default root rather than failing the registration.

    :param str category: Category name, e.g. 'Armor'.
    :return: Tuple of (is_gear, gear_root).
    :rtype: tuple(bool, str)
    """

    if not category:
        return False, asset_paths.DEFAULT_GEAR_ROOT

    category_data = asset_paths.AssetDictData.load().get_category_data(category)
    if not category_data:
        logger.debug('The category "%s" is not in the project\'s asset config, so it is being '
                     'treated as not gear.', category)
        return False, asset_paths.DEFAULT_GEAR_ROOT

    return bool(category_data.is_gear), category_data.gear_root


def build_asset_id(category, asset_name):
    """
    Build the registry key for an asset: ``<category>_<name>``, lowercased.

    Asset ids are unique across the **whole** registry, not per category -
    ``AssetManager`` indexes by id globally, so two assets sharing one id means
    only the first ever loads. Names legitimately repeat across categories (an
    outfit set has a Pirate body, a Pirate hat and Pirate shoes), so the
    category is folded into the id rather than the name being refused.

    Ids created before this are bare names and are deliberately left alone:
    they are written into Maya scenes (``frag_root.assetID``, the ``asset_id``
    attribute on root joints), so changing one orphans every rig referencing it.

    :param str category: Category name.
    :param str asset_name: Display name.
    :return: The generated asset id, e.g. 'hats_pirate'.
    :rtype: str
    """

    # Underscores are kept: the existing ids use them ('sk_base_belt',
    # 'agent_cap'), so stripping them would make generated ids read differently
    # from every id already in the registry. Spaces become underscores rather
    # than disappearing, for the same reason.
    def _clean(value):
        value = str(value or '').strip().replace(' ', '_').replace('-', '_')
        value = strings.remove_chars(value, chars='[^a-zA-Z0-9_]+').lower()
        # Collapse runs of underscores left by punctuation.
        while '__' in value:
            value = value.replace('__', '_')
        return value.strip('_')

    clean_name = _clean(asset_name)
    clean_category = _clean(category)
    if not clean_category:
        return clean_name
    if not clean_name:
        return clean_category
    return f'{clean_category}_{clean_name}'


# --- Explicit file references --------------------------------------------- #

# Named files an asset can record, so tooling stops guessing which file inside
# the asset folder is "the" rig or skeleton. Each kind names the folder it
# normally lives in and how to recognise it when nothing is recorded yet.
#
#   folder_key : a get_required_path() key, resolved per category
#   extension  : file extension used by the fallback scan
#   suffix     : optional filename ending the fallback requires
ASSET_FILE_KINDS = {
    'rig': {'folder_key': 'SRC_RIGS_PATH', 'extension': '.ma', 'suffix': '_rig.ma',
            'label': 'Maya rig file'},
    # Gear and skinned meshes use a '_skn.ma' file rather than a rig. It is the
    # more common convention in the depot (47 top-level _skn against 28 _rig),
    # and it is what the gear system imports to get a mesh plus its skinning.
    'skin': {'folder_key': 'SRC_RIGS_PATH', 'extension': '.ma', 'suffix': '_skn.ma',
             'label': 'Skinned source file'},
    'skel': {'folder_key': 'SRC_RIGS_PATH', 'extension': '.skl', 'suffix': '',
             'label': 'Skeleton definition'},
    'mesh': {'folder_key': 'SRC_MODELS_PATH', 'extension': '.fbx', 'suffix': '',
             'label': 'Source mesh'},
}

# Subfolders that hold copies rather than the authoritative file. Maya's
# incremental save writes a folder per file with dozens of numbered versions;
# scanning into it made hulk look like it had 104 rig files (102 of them
# incremental) and could return a week-old save as "the" rig.
NON_AUTHORITATIVE_FOLDERS = ('incrementalsave', 'incrementalsaves', '.mayaswatches')

# Values file_status() can return.
FILE_RECORDED = 'recorded'    # the entry names a file and it is on disk
FILE_STALE = 'stale'          # the entry names a file that is not there any more
FILE_INFERRED = 'inferred'    # nothing recorded, exactly one candidate found
FILE_AMBIGUOUS = 'ambiguous'  # nothing recorded, several candidates found
FILE_MISSING = 'missing'      # nothing recorded and nothing found


def build_asset_path(category, subtype='', faction='', additional_types=None,
                     asset_name='', is_gear=False, gender='', asset_type='',
                     skeleton='', body_type='', path_flags=None, path_order=None,
                     gear_root=None):
    """
    Build a folder path from the asset's classification fields.

    Parent assets:  Category/<ordered classification fields>/AdditionalTypes.../AssetName
    Gear/child assets: same, prefixed with the gear root (``gear_root``, default 'Gear/').

    ``path_order`` is a list of field keys from ``ORDERABLE_FIELDS`` that
    determines the order in which classification fields are appended to
    the path. When ``None``, ``DEFAULT_PATH_ORDER`` is used. Any fields
    missing from a provided order are appended at the end in default order
    so the function always handles every classification field.

    ``path_flags`` is a dict of include_* booleans controlling which fields
    actually emit a segment (see ``DEFAULT_PATH_FLAGS``).

    :param str category: Primary category name.
    :param str subtype: Sub-category name.
    :param str faction: Faction name.
    :param list additional_types: Extra type folders to nest.
    :param str asset_name: Display name of the asset.
    :param bool is_gear: True if this is a child/gear asset.
    :param str gender: Gender tag (optional in path).
    :param str asset_type: Asset type (optional in path).
    :param str skeleton: Skeleton name (optional in path).
    :param str body_type: Body type name (optional in path).
    :param dict path_flags: Per-field inclusion flags; legacy defaults if None.
    :param list path_order: Per-asset classification order; defaults to
        ``DEFAULT_PATH_ORDER`` when None.
    :param str gear_root: Relative folder gear paths start under, only used
        when ``is_gear`` is True. May contain several segments
        ('Characters/Gear'). Defaults to ``asset_paths.DEFAULT_GEAR_ROOT``.
    :return: Forward-slash separated relative path.
    :rtype: str
    """

    if additional_types is None:
        additional_types = []
    # Merge caller flags over defaults so partial dicts still work.
    flags = dict(DEFAULT_PATH_FLAGS)
    if path_flags:
        flags.update(path_flags)
    # Normalize order: honor caller's order, then append any missing fields
    # so a partial/stale order never silently drops a classification segment.
    order = [f for f in (path_order or []) if f in ORDERABLE_FIELDS]
    for f in DEFAULT_PATH_ORDER:
        if f not in order:
            order.append(f)

    values = {
        'subtype': _normalize_field_value('subtype', subtype),
        'faction': _normalize_field_value('faction', faction),
        'gender': _normalize_field_value('gender', gender),
        'asset_type': _normalize_field_value('asset_type', asset_type),
        'skeleton': _normalize_field_value('skeleton', skeleton),
        'body_type': _normalize_field_value('body_type', body_type),
    }

    parts = []
    if is_gear:
        # The root may be several folders deep; each becomes its own segment.
        root = asset_paths.normalize_gear_root(gear_root) or asset_paths.DEFAULT_GEAR_ROOT
        parts.extend(root.split('/'))
    if category:
        parts.append(category)
    for field in order:
        if not flags.get(f'include_{field}', False):
            continue
        val = values.get(field, '')
        if val:
            parts.append(val)
    if flags['include_additional_types']:
        for atype in additional_types:
            if atype:
                parts.append(atype)
    if asset_name:
        parts.append(asset_name)

    return '/'.join(parts)


def derive_path_flags_and_order(asset_dict):
    """
    Infer path-inclusion flags AND field ordering from an asset's stored path.

    For entries that predate ``path_flags`` / ``path_order``, this walks the
    stored ``path`` left-to-right and matches each segment against the
    classification field values on the entry. The resulting order mirrors
    what the user originally saw, and the flags mirror which fields
    actually contributed segments. Fields that do not appear in the path
    are appended to ``order`` in ``DEFAULT_PATH_ORDER`` position so the
    returned order always covers every field.

    :param dict asset_dict: The entry's inner data dict (values, not wrapper).
    :return: Tuple ``(flags, order)``: flags matches ``DEFAULT_PATH_FLAGS``
        keys; order is a list of field keys from ``ORDERABLE_FIELDS``.
    :rtype: tuple(dict, list)
    """

    flags = dict(DEFAULT_PATH_FLAGS)
    # Start every orderable field as excluded; include only what we actually
    # see in the stored path below.
    for field in ORDERABLE_FIELDS:
        flags[f'include_{field}'] = False

    path = asset_dict.get('path', '') or ''
    if not path:
        # No path yet — keep legacy defaults so the UI doesn't clear all
        # checkboxes on a freshly created (but unsaved) entry.
        return dict(DEFAULT_PATH_FLAGS), list(DEFAULT_PATH_ORDER)

    # Strip the gear root (any depth), the category, and the trailing asset_name
    # so ``segments`` holds only classification and additional_type entries.
    # The category segment is the reliable anchor because a configured gear
    # root can be several folders deep; the legacy single 'Gear' marker is only
    # assumed when the category is missing from the stored path.
    raw_parts = [p for p in path.split('/') if p]
    category = asset_dict.get('category', '') or ''
    if category and category in raw_parts:
        segments = raw_parts[raw_parts.index(category) + 1:]
    else:
        segments = raw_parts[1:] if raw_parts and raw_parts[0] == 'Gear' else list(raw_parts)
        if segments:
            segments = segments[1:]
    if segments:
        segments = segments[:-1]

    field_values = {
        field: _normalize_field_value(field, asset_dict.get(field, ''))
        for field in ORDERABLE_FIELDS
    }

    # Walk segments in stored order so the derived ``order`` matches the
    # sequence the user originally saw on disk.
    order = []
    matched = set()
    segment_set = set(segments)
    for seg in segments:
        for field in ORDERABLE_FIELDS:
            if field in matched:
                continue
            if field_values[field] and field_values[field] == seg:
                order.append(field)
                matched.add(field)
                flags[f'include_{field}'] = True
                break

    # Any field not present in the stored path still needs a slot in the
    # returned order (defaults to "included=False", position at the end)
    # so the UI can show every field regardless of history.
    for field in ORDERABLE_FIELDS:
        if field not in order:
            order.append(field)

    additional_types = asset_dict.get('additional_types', []) or []
    if additional_types:
        flags['include_additional_types'] = any(
            atype and atype in segment_set for atype in additional_types
        )
    else:
        # No additional_types to check; default True matches legacy behavior.
        flags['include_additional_types'] = True

    return flags, order


#: Where in the engine's content a project's assets live. ``/Game/`` is Unreal's own content
#: root; what follows it is the project's own folder, which the version this replaces had
#: written into the code as ``Wayward``.
ENGINE_ROOT_VARIABLE = 'MCA_ENGINE_CONTENT_ROOT'

#: Used when that variable is not set: Unreal's content root, with nothing added.
DEFAULT_ENGINE_ROOT = '/Game'


def engine_root():
    """
    :return: The engine content folder the project's assets go under, always starting and
        ending without a stray slash - ``'/Game/Wayward'``, ``'/Game'``.
    :rtype: str
    """

    root = (os.environ.get(ENGINE_ROOT_VARIABLE) or DEFAULT_ENGINE_ROOT).strip()
    root = root.replace('\\', '/').strip('/')
    if not root:
        return DEFAULT_ENGINE_ROOT
    if not root.startswith('Game'):
        root = 'Game/' + root

    return '/' + root


def build_engine_path(dcc_path):
    """
    Where an asset sits in the engine's content, from where it sits on disk.

    :param str dcc_path: The asset's path, relative to the project.
    :return: The engine path, or ``''``.
    :rtype: str

    The version this replaces prefixed ``/Game/Wayward/``, with the project's name in the
    code. :data:`ENGINE_ROOT_VARIABLE` says it now.
    """

    if not dcc_path:
        return ''

    clean = str(dcc_path).replace('\\', '/').strip('/')
    if not clean:
        return ''

    # Already an engine path.
    if clean.startswith('Game/') or clean == 'Game':
        return '/' + clean

    return '{0}/{1}'.format(engine_root(), clean)


# Channel data types accepted on dye entries. ``linear_color`` maps to UE
# Vector parameters (RGBA, e.g. tint colors). ``scalar`` maps to UE Scalar
# parameters (Roughness, Metallic, mask strengths, etc.).
DYE_CHANNEL_TYPES = ('linear_color', 'scalar')

# Parent material parameter group that defines dye channels in Wayward.
# Auto-discovery on the UE side filters parameters to only this group.
DYE_PARAM_GROUP = 'Color Tinting'


def _migrate_dye_schema(inner):
    """
    Backfill ``is_dye`` on material entries and ``channels`` on dye entries
    for assets saved before the dye-channel schema existed.

    A material is flagged ``is_dye=True`` when its ``slot_name`` matches a
    dye row's ``slot_name``, so the UI checkbox state stays in sync with
    the existing dye entries on first load. Dye rows missing ``channels``
    receive an empty list; channel population happens in the UI (manual
    entry or UE auto-discovery), not here.

    :param dict inner: The inner asset data dict (values, not wrapper).
    """

    materials = inner.get('materials') or []
    dyes = inner.get('dyes') or []
    dye_slots = {d.get('slot_name', '') for d in dyes if d.get('slot_name')}
    for mat in materials:
        if 'is_dye' not in mat:
            slot = mat.get('slot_name', '')
            mat['is_dye'] = bool(slot and slot in dye_slots)
    for dye in dyes:
        if 'channels' not in dye:
            dye['channels'] = []
        # Backfill the friendly-name and description fields on every
        # channel so legacy entries round-trip through the new editor
        # without losing data. Param ``name`` (the UE binding) is left
        # untouched; ``display_name`` is what the artist types and is
        # what shows up in the Dye Overrides tab.
        for ch in dye.get('channels') or []:
            if 'display_name' not in ch:
                ch['display_name'] = ''
            if 'description' not in ch:
                ch['description'] = ''


class UnifiedAssetEntry(asset_list.AssetBaseEntry):
    """
    Unified entry class for all asset types (parent and child/gear).

    Uses a single rich JSON schema with fields covering identity, skeleton,
    classification, hierarchy, paths, materials, dyes, decals, textures,
    and attach sockets. This replaces both AssetEntry (legacy YAML) and
    GearEntry (new JSON gear) with one consistent format.

    The internal data is stored as a dictionary keyed by asset_id:
    ``{asset_id: {name, category, subtype, ...}}``
    """

    def __init__(self, asset_dict):
        super().__init__(asset_dict)
        # Backfill path_flags / path_order for entries that predate these
        # fields so existing assets load with the correct inclusion toggles
        # and classification ordering derived from their stored path.
        # New entries created via create() already have both set and this
        # is a no-op for them.
        inner = self._fields
        if inner and ('path_flags' not in inner or 'path_order' not in inner):
            flags, order = derive_path_flags_and_order(inner)
            if 'path_flags' not in inner:
                inner['path_flags'] = flags
            if 'path_order' not in inner:
                inner['path_order'] = order

        # Backfill dye-related fields on materials/dyes for legacy entries.
        # ``is_dye`` is inferred from a matching dye row by slot_name so the
        # Materials tab can show the correct checkbox state on first load.
        # ``channels`` defaults to an empty list; UE auto-discovery fills it.
        if inner:
            _migrate_dye_schema(inner)

    @classmethod
    def create(cls,
               asset_name,
               category,
               subtype='',
               faction='',
               gender='',
               skeleton='',
               body_type='',
               additional_types=None,
               slot='',
               built_for='',
               asset_type='SkeletalMesh',
               path='',
               engine_path='',
               description='',
               image='',
               asset_id=None,
               materials=None,
               textures=None,
               engine_textures=None,
               decals=None,
               dyes=None,
               attach_sockets=None,
               dye_overrides=None,
               path_flags=None,
               path_order=None,
               is_gear=None,
               gear_root=None):
        """
        Create a new UnifiedAssetEntry with the full unified schema.

        Auto-generates asset_id from asset_name if not provided.
        Auto-generates path and engine_path if not provided.

        :param str asset_name: Display name of the asset.
        :param str category: Primary category (Characters, Armor, Weapons, etc.).
        :param str subtype: Sub-category for grouping.
        :param str faction: Faction identifier.
        :param str gender: Gender tag ('Male', 'Female', 'Neutral', or ''). Classification-only; does not affect folder structure.
        :param str skeleton: Skeleton reference name (e.g. WaywardBot, SKEL_ZLeg).
        :param str body_type: Body type name (e.g. Humanoid, ZLeg).
        :param list additional_types: Extra descriptive types that add nested folders.
        :param str slot: Equipment slot for gear (e.g. Chest, WeaponRight). Empty for parents.
        :param built_for: Character name this gear targets, or a list of names when
        several characters can wear it. Empty for parent assets. The derived path
        does not depend on it beyond marking the asset as gear.
    :type built_for: str or list[str]
        :param str asset_type: SkeletalMesh, StaticMesh, or Material.
        :param str path: DCC-relative asset path. Auto-generated if empty.
        :param str engine_path: UE content path. Auto-generated if empty.
        :param str description: Detailed description of the asset.
        :param str image: Icon or thumbnail image path.
        :param str asset_id: Unique identifier. Auto-generated from name if omitted.
        :param list materials: Material slot definitions
            ``[{index, slot_name, name, options, is_dye}]``. ``is_dye`` flags
            the material as dye-eligible; a matching ``dyes`` entry holds
            its per-channel definitions.
        :param list textures: DCC-side texture paths.
        :param list engine_textures: UE-side texture paths.
        :param list decals: Decal definitions [{index, slot_name, options, mesh_type}].
        :param list dyes: Dye definitions
            ``[{index, slot_name, name, options, channels}]``. ``channels``
            is a list of
            ``{name, display_name, description, type, default}`` where
            ``type`` is one of ``DYE_CHANNEL_TYPES`` (``linear_color`` or
            ``scalar``). The channel ``name`` must match the parent
            material's parameter name exactly so values can be set
            programmatically in UE; ``display_name`` is the artist-facing
            label shown in the Dye Overrides tab and ``description`` is
            optional free-form notes.
        :param list attach_sockets: Socket names for gear attachment.
        :param dict dye_overrides: Per-variant channel value overrides
            keyed by ``slot_name`` then ``channel_name``. Empty / None on
            parent assets; gear variants populate this to retint shared
            materials at runtime. Channel types come from the parent
            asset's ``dyes`` schema; values here are the raw value to
            push (list[float] for ``linear_color``, float for ``scalar``).
        :param bool is_gear: Force gear placement (path under the gear root).
            None derives it: a ``built_for`` parent or a category flagged
            IS_GEAR in the asset config both count as gear.
        :param str gear_root: Relative folder gear paths start under. None
            reads the category's GEAR_ROOT from the config (default 'Gear').
        :return: A new UnifiedAssetEntry instance.
        :rtype: UnifiedAssetEntry
        """

        if additional_types is None:
            additional_types = []

        # Auto-generate the asset_id. Qualified with the category so two assets
        # that share a name in different categories cannot collide; see
        # build_asset_id. An explicit asset_id from the caller always wins.
        if not asset_id:
            asset_id = build_asset_id(category, asset_name)

        # Determine if this is a gear/child asset. The register UI passes both
        # values explicitly; API callers and category transfers leave them None
        # so the category config decides, which keeps regenerated paths under
        # the same root the UI previews for that category.
        # built_for may be a single name or a list of them (gear worn by more
        # than one character). Normalise once; the stored shape stays a plain
        # string when there is exactly one, so single-parent entries are
        # byte-identical to how they always looked.
        if isinstance(built_for, (list, tuple)):
            built_for_names = [str(v).strip() for v in built_for if str(v).strip()]
        else:
            _single = str(built_for or '').strip()
            built_for_names = [_single] if _single else []
        built_for = built_for_names[0] if len(built_for_names) == 1 else built_for_names

        if is_gear is None or not gear_root:
            category_is_gear, category_gear_root = get_category_gear_settings(category)
            if is_gear is None:
                is_gear = bool(built_for_names) or category_is_gear
            if not gear_root:
                gear_root = category_gear_root

        # Resolve path_flags / path_order so the generated path matches
        # what will be stored, and so callers that omit either still get
        # legacy behavior.
        effective_flags = dict(DEFAULT_PATH_FLAGS)
        if path_flags:
            effective_flags.update(path_flags)
        effective_order = [f for f in (path_order or []) if f in ORDERABLE_FIELDS]
        for f in DEFAULT_PATH_ORDER:
            if f not in effective_order:
                effective_order.append(f)

        # Auto-generate path if not provided
        if not path:
            path = build_asset_path(
                category=category,
                subtype=subtype,
                faction=faction,
                additional_types=additional_types,
                asset_name=asset_name,
                is_gear=is_gear,
                gender=gender,
                asset_type=asset_type,
                skeleton=skeleton,
                body_type=body_type,
                path_flags=effective_flags,
                path_order=effective_order,
                gear_root=gear_root,
            )

        # Auto-generate engine_path if not provided
        if not engine_path:
            engine_path = build_engine_path(path)

        asset_dict = {
            asset_id: {
                'name': asset_name,
                'category': category,
                'subtype': subtype or 'Default',
                'faction': faction,
                'gender': gender,
                'skeleton': skeleton,
                'body_type': body_type,
                'asset_type': asset_type,
                'additional_types': additional_types,
                'slot': slot,
                'built_for': built_for,
                'path': path,
                'engine_path': engine_path,
                'description': description,
                'image': image,
                'textures': textures or [],
                'engine_textures': engine_textures or [],
                'materials': materials or [],
                'decals': decals or [],
                'dyes': dyes or [],
                'attach_sockets': attach_sockets or [],
                'dye_overrides': dye_overrides or {},
                'path_flags': effective_flags,
                'path_order': effective_order,
            }
        }

        return cls(asset_dict)

    # --- Core identity ----------------------------------------------------- #

    @property
    def subtype(self):
        """
        Returns the asset sub-category (e.g. Players, Enemies, Chest, Sword).

        :return: The subtype name.
        :rtype: str
        """

        return self._fields.get('subtype', '')

    @subtype.setter
    def subtype(self, value):
        """
        Sets the asset sub-category.

        :param str value: Subtype name.
        """

        self._fields['subtype'] = value

    # --- Skeleton and body ------------------------------------------------- #

    @property
    def skeleton(self):
        """
        Returns the skeleton reference name (e.g. WaywardBot, SKEL_ZLeg).

        :return: Skeleton name, or empty string if unset.
        :rtype: str
        """

        return self._fields.get('skeleton', '')

    @skeleton.setter
    def skeleton(self, value):
        """
        Sets the skeleton reference.

        :param str value: Skeleton name.
        """

        self._fields['skeleton'] = value

    @property
    def body_type(self):
        """
        Returns the body type name.
        Body types use a specific skeleton where core joint positions match
        but leaf and physics joints can differ.

        :return: Body type name, or empty string if unset.
        :rtype: str
        """

        return self._fields.get('body_type', '')

    @body_type.setter
    def body_type(self, value):
        """
        Sets the body type.

        :param str value: Body type name.
        """

        self._fields['body_type'] = value

    # --- Classification ---------------------------------------------------- #

    @property
    def asset_type(self):
        """
        Returns the asset type (SkeletalMesh, StaticMesh, or Material).

        :return: The asset type string.
        :rtype: str
        """

        return self._fields.get('asset_type', 'SkeletalMesh')

    @asset_type.setter
    def asset_type(self, value):
        """
        Sets the asset type.

        :param str value: SkeletalMesh, StaticMesh, or Material.
        """

        self._fields['asset_type'] = value

    @property
    def additional_types(self):
        """
        Returns the list of additional descriptive types.
        These add extra nested folders in the asset path hierarchy.

        :return: List of additional type names.
        :rtype: list[str]
        """

        return self._fields.get('additional_types', [])

    @additional_types.setter
    def additional_types(self, value):
        """
        Sets the additional types list.

        :param list value: List of additional type names.
        """

        self._fields['additional_types'] = value or []

    @property
    def path_flags(self):
        """
        Returns the per-classification path inclusion flags.

        Controls which classification fields (subtype, faction, gender,
        asset_type, skeleton, body_type, additional_types) are folded
        into the generated folder path. Missing flags fall back to
        ``DEFAULT_PATH_FLAGS``.

        :return: Dict of include_* booleans.
        :rtype: dict
        """

        stored = self._fields.get('path_flags') or {}
        merged = dict(DEFAULT_PATH_FLAGS)
        merged.update(stored)
        return merged

    @path_flags.setter
    def path_flags(self, value):
        """
        Sets the path inclusion flags dict.

        :param dict value: Dict of include_* booleans. Missing keys fall
            back to ``DEFAULT_PATH_FLAGS`` at read time.
        """

        self._fields['path_flags'] = dict(value or {})

    @property
    def path_order(self):
        """
        Returns the classification field ordering for this asset's path.

        Any fields missing from the stored order are appended in default
        order so callers always get the full set of ``ORDERABLE_FIELDS``.

        :return: List of field keys from ``ORDERABLE_FIELDS``.
        :rtype: list[str]
        """

        stored = self._fields.get('path_order') or []
        order = [f for f in stored if f in ORDERABLE_FIELDS]
        for f in DEFAULT_PATH_ORDER:
            if f not in order:
                order.append(f)
        return order

    @path_order.setter
    def path_order(self, value):
        """
        Sets the classification path ordering.

        :param list value: List of field keys from ``ORDERABLE_FIELDS``.
        """

        self._fields['path_order'] = [
            f for f in (value or []) if f in ORDERABLE_FIELDS
        ]

    # --- Hierarchy --------------------------------------------------------- #

    @property
    def built_for(self):
        """
        Returns the first parent character name this asset was built for.

        Kept as a plain string for the many callers that predate multi-parent
        gear; use :attr:`built_for_all` when every parent matters.

        :return: Character display name, or empty string for parent assets.
        :rtype: str
        """

        names = self.built_for_all
        return names[0] if names else ''

    @property
    def built_for_all(self):
        """
        Returns every parent character this asset was built for.

        A piece of gear can be worn by more than one character, so ``built_for``
        holds either a single name (the original shape, still written by older
        tools) or a list of them. Both normalize to a list here.

        Note the derived folder path does not depend on which characters these
        are - gear derives under the category's gear root - so extra parents
        never move the asset on disk.

        :return: Character display names, in order; empty for parent assets.
        :rtype: list[str]
        """

        value = self._fields.get('built_for', '')
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        value = str(value).strip()
        return [value] if value else []

    @built_for.setter
    def built_for(self, value):
        """
        Sets the parent character name or names.

        A single name is stored as a string and several as a list, so an entry
        with one parent looks exactly as it always did.

        :param value: Character display name, or a list of them. Empty clears it.
        :type value: str or list[str]
        """

        if isinstance(value, (list, tuple)):
            names = [str(v).strip() for v in value if str(v).strip()]
        else:
            name = str(value or '').strip()
            names = [name] if name else []

        if len(names) == 1:
            self._fields['built_for'] = names[0]
        else:
            self._fields['built_for'] = names

    @property
    def variant_of(self):
        """
        Returns the asset id of the character this one is a variant of.

        A variant is a whole-character restyle - a different body that rides the
        same skeleton - as opposed to gear, which is worn on top of one. Empty
        means this character is a base in its own right.

        Held as an asset id rather than a display name, unlike
        :attr:`built_for`: character display names are not unique in the depot
        (two separate records are both called 'Base_Female'), and a variant that
        resolved to the wrong base would swap in the wrong body.

        :return: Base character asset id, or empty string.
        :rtype: str
        """

        return str(self._fields.get('variant_of', '') or '').strip()

    @variant_of.setter
    def variant_of(self, value):
        """
        Sets the base character this one is a variant of.

        :param str value: Base character asset id. Empty clears it.
        """

        self._fields['variant_of'] = str(value or '').strip()

    @property
    def is_variant(self):
        """
        Is this character a variant of another?

        :return: True when :attr:`variant_of` names a base.
        :rtype: bool
        """

        return bool(self.variant_of)

    def add_built_for(self, name):
        """
        Add another parent character, keeping the existing ones.

        :param str name: Character display name.
        :return: True when it was added, False when already present or empty.
        :rtype: bool
        """

        name = str(name or '').strip()
        if not name:
            return False
        names = self.built_for_all
        if name.lower() in {n.lower() for n in names}:
            return False
        names.append(name)
        self.built_for = names
        return True

    def remove_built_for(self, name):
        """
        Remove one parent character.

        :param str name: Character display name.
        :return: True when it was removed.
        :rtype: bool
        """

        name = str(name or '').strip().lower()
        names = [n for n in self.built_for_all if n.lower() != name]
        if len(names) == len(self.built_for_all):
            return False
        self.built_for = names
        return True

    @property
    def slot(self):
        """
        Returns the equipment slot for gear assets (e.g. Chest, WeaponRight).
        Describes where the asset connects to a parent asset.

        :return: Slot name, or empty string if not a gear asset.
        :rtype: str
        """

        return self._fields.get('slot', '')

    @slot.setter
    def slot(self, value):
        """
        Sets the equipment slot.

        :param str value: Slot name.
        """

        self._fields['slot'] = value

    @property
    def is_parent(self):
        """
        Returns True if this is a parent/root asset (not gear).
        A parent asset has no built_for value set.

        :return: True if parent asset.
        :rtype: bool
        """

        return not self.built_for_all

    @property
    def is_gear(self):
        """
        Returns True if this is a child/gear asset.
        A gear asset has at least one built_for value pointing at a parent.

        :return: True if gear/child asset.
        :rtype: bool
        """

        return bool(self.built_for_all)

    # --- Paths ------------------------------------------------------------- #

    @property
    def engine_path(self):
        """
        Returns the Unreal Engine content path (e.g. /Game/Wayward/...).

        :return: UE content path, or empty string if unset.
        :rtype: str
        """

        return self._fields.get('engine_path', '')

    @engine_path.setter
    def engine_path(self, value):
        """
        Sets the Unreal Engine content path.

        :param str value: UE content path.
        """

        self._fields['engine_path'] = value

    @property
    def skel_path(self):
        """
        Returns the full path to the skeleton (.skl) file.

        The skeleton lives in the asset's _Source/Rigs folder and is named
        after the asset's file_name (lowercase, underscores). Callers should
        check existence before reading; summoner, for example, falls back to
        the SK fbx when the .skl is missing (typical for gear assets that
        share their parent's skeleton).

        :return: Full path to the .skl file, or empty string if src_rig_path
            cannot be resolved.
        :rtype: str
        """

        # An explicitly recorded skeleton wins, so a renamed file stays findable.
        recorded = self.resolve_file('skel')
        if recorded:
            return os.path.normpath(recorded)

        src_rigs = self.src_rig_path
        if not src_rigs:
            return ''
        # Nothing recorded and nothing on disk: return the conventional name so
        # callers writing a new skeleton still get the right destination.
        return os.path.normpath(os.path.join(src_rigs, f'{self.file_name}.skl'))

    # --- Explicit file references ------------------------------------------ #

    @property
    def files(self):
        """
        Returns the asset's recorded file references.

        Keys come from :data:`ASSET_FILE_KINDS`; values are paths relative to
        the asset folder, so moving the asset does not invalidate them.

        :return: Mapping of kind to relative path.
        :rtype: dict
        """

        return dict(self._fields.get('files', {}) or {})

    @files.setter
    def files(self, value):
        """
        Replaces the whole file reference block.

        :param dict value: Mapping of kind to relative path.
        """

        self._fields['files'] = dict(value or {})

    def get_file(self, kind):
        """
        Returns the recorded relative path for one kind, without checking disk.

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :return: Relative path, or '' when nothing is recorded.
        :rtype: str
        """

        return self.files.get(kind, '') or ''

    def set_file(self, kind, file_path):
        """
        Record which file backs one kind for this asset.

        This is what other tools call after saving or renaming a file, so the
        registry keeps up instead of drifting. An absolute path inside the asset
        folder is stored relative to it; anything already relative is kept.

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :param str file_path: Absolute or asset-relative path. Empty clears it.
        :return: The stored relative path, or '' when cleared.
        :rtype: str
        :raises ValueError: If ``kind`` is not a known file kind.
        """

        if kind not in ASSET_FILE_KINDS:
            raise ValueError(
                f'Unknown file kind {kind!r}. Valid: {", ".join(sorted(ASSET_FILE_KINDS))}.')

        if not file_path:
            self.remove_file(kind)
            return ''

        relative = str(file_path).replace('\\', '/')
        if os.path.isabs(file_path):
            root = self.full_path
            if root:
                try:
                    relative = os.path.relpath(file_path, root).replace('\\', '/')
                except ValueError:
                    # Different drive on Windows; keep the absolute path rather
                    # than inventing a relative one that cannot resolve.
                    relative = str(file_path).replace('\\', '/')
                if relative.startswith('..'):
                    logger.warning(
                        "File %s for asset '%s' is outside the asset folder; storing it as given.",
                        file_path, self.asset_id)
                    relative = str(file_path).replace('\\', '/')

        block = self.files
        block[kind] = relative
        self.files = block
        return relative

    def remove_file(self, kind):
        """
        Forget the recorded file for one kind.

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :return: True when something was removed.
        :rtype: bool
        """

        block = self.files
        if kind not in block:
            return False
        block.pop(kind)
        self.files = block
        return True

    def _scan_for_file(self, kind):
        """
        Find candidate files for one kind by scanning the folder it lives in.

        The fallback for an asset with nothing recorded. Files directly in the
        folder win; nested ones are only considered when the top level is empty,
        and folders of saved copies (see NON_AUTHORITATIVE_FOLDERS) are skipped
        entirely.

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :return: Absolute paths of candidates, in scan order.
        :rtype: list[str]
        """

        spec = ASSET_FILE_KINDS.get(kind)
        if not spec:
            return []
        folder = self.get_required_path(spec['folder_key'])
        if not folder:
            return []
        # asset_data.config stores folders with Windows separators ('_Source\\Rigs').
        # Normalise so the scan works wherever this runs, not just on Windows.
        folder = os.path.normpath(folder.replace('\\', os.sep).replace('/', os.sep))
        if not os.path.isdir(folder):
            return []

        suffix = (spec.get('suffix') or spec['extension']).lower()

        def _matches(names):
            return sorted(n for n in names if n.lower().endswith(suffix))

        # Files sitting directly in the folder are the authoritative ones. Only
        # walk deeper when the top level has nothing, and never into a folder of
        # saved copies.
        try:
            top_level = [f for f in os.listdir(folder)
                         if os.path.isfile(os.path.join(folder, f))]
        except OSError:
            return []

        matched = _matches(top_level)
        if matched:
            return [os.path.join(folder, name) for name in matched]

        nested = []
        for dir_path, dir_names, file_names in os.walk(folder):
            dir_names[:] = [d for d in dir_names
                            if d.lower() not in NON_AUTHORITATIVE_FOLDERS]
            for name in _matches(file_names):
                nested.append(os.path.join(dir_path, name))
        return sorted(nested)

    def file_candidates(self, kind):
        """
        Return every file on disk that could back one kind.

        Useful when a record has gone stale and something has to choose, or to
        offer the options in a UI rather than guessing.

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :return: Absolute paths, in scan order.
        :rtype: list[str]
        """

        return self._scan_for_file(kind)

    def file_status(self, kind):
        """
        Report how well the recorded file for one kind matches what is on disk.

        Read-only: it never repairs the entry. Writing during a lookup would
        check files out of Perforce as a side effect of reading, so repair is an
        explicit action (see ``assetlist_api.repair_asset_files``).

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :return: ``(status, absolute_path, detail)``. Status is one of
            FILE_RECORDED, FILE_STALE, FILE_INFERRED, FILE_AMBIGUOUS, FILE_MISSING.
            ``absolute_path`` is '' when nothing usable was found.
        :rtype: tuple
        """

        recorded = self.get_file(kind)
        root = self.full_path

        if recorded:
            absolute = recorded if os.path.isabs(recorded) else (
                os.path.normpath(os.path.join(root, recorded)) if root else '')
            if absolute and os.path.isfile(absolute):
                return FILE_RECORDED, absolute, ''
            candidates = self._scan_for_file(kind)
            detail = f'recorded file is missing: {recorded}'
            if len(candidates) == 1:
                return FILE_STALE, candidates[0], detail
            if len(candidates) > 1:
                return FILE_STALE, candidates[0], (
                    f'{detail}; {len(candidates)} candidates on disk')
            return FILE_STALE, '', detail

        candidates = self._scan_for_file(kind)
        if len(candidates) == 1:
            return FILE_INFERRED, candidates[0], 'nothing recorded; one candidate found'
        if len(candidates) > 1:
            return FILE_AMBIGUOUS, candidates[0], (
                f'nothing recorded; {len(candidates)} candidates, using the first: '
                + ', '.join(os.path.basename(c) for c in candidates[:5]))
        return FILE_MISSING, '', 'nothing recorded and nothing found on disk'

    def resolve_file(self, kind):
        """
        Resolve one named file to an absolute path.

        Prefers what the entry records, verifies it is still there, and falls
        back to scanning when it is not - so an out-of-date entry degrades to
        the old guess rather than breaking, and says so in the log.

        :param str kind: A key from :data:`ASSET_FILE_KINDS`.
        :return: Absolute path, or '' when nothing could be found.
        :rtype: str
        """

        status, absolute, detail = self.file_status(kind)
        if status == FILE_STALE:
            logger.warning("Asset '%s' %s reference is out of date (%s). "
                           "Run repair_asset_files or re-record it.",
                           self.asset_id, kind, detail)
        elif status == FILE_AMBIGUOUS:
            logger.warning("Asset '%s' has no recorded %s file and %s",
                           self.asset_id, kind, detail)
        return absolute

    # --- Metadata ---------------------------------------------------------- #

    @property
    def description(self):
        """
        Returns the detailed asset description.
        Should tell a story about the asset.

        :return: Description text, or empty string if unset.
        :rtype: str
        """

        return self._fields.get('description', '')

    @description.setter
    def description(self, value):
        """
        Sets the asset description.

        :param str value: Description text.
        """

        self._fields['description'] = value

    @property
    def image(self):
        """
        Returns the icon or thumbnail image path.

        :return: Image path, or empty string if unset.
        :rtype: str
        """

        return self._fields.get('image', '')

    @image.setter
    def image(self, value):
        """
        Sets the image path.

        :param str value: Image path.
        """

        self._fields['image'] = value

    # --- Materials, Dyes, Decals ------------------------------------------- #

    @property
    def materials(self):
        """
        Returns the material slot definitions.
        Each entry is a dict with ``index``, ``slot_name``, ``name``,
        ``options`` (list of paths), and ``is_dye`` (bool). The slot_name
        should match the material name in both Maya and engine. When
        ``is_dye`` is True, a corresponding entry in ``dyes`` (matched by
        ``slot_name``) carries the channel definitions.

        :return: List of material definitions.
        :rtype: list[dict]
        """

        return self._fields.get('materials', [])

    @materials.setter
    def materials(self, value):
        """
        Sets the material slot definitions.

        :param list value: List of material dicts.
        """

        self._fields['materials'] = value or []

    @property
    def dyes(self):
        """
        Returns the dye material definitions.
        Dyes are materials whose channels (RGBA tints, scalar params) can
        be overridden per-variant in-game. Each entry has the same shape
        as a material row plus a ``channels`` list:
        ``{index, slot_name, name, options, channels}`` where each channel
        is ``{name, display_name, description, type, default}`` and
        ``type`` is one of ``DYE_CHANNEL_TYPES`` (``linear_color`` or
        ``scalar``). ``name`` is the UE parameter binding; ``display_name``
        is the artist-facing label; ``description`` is optional free-form
        notes. Dye rows are matched to material rows by ``slot_name``.

        :return: List of dye definitions.
        :rtype: list[dict]
        """

        return self._fields.get('dyes', [])

    @dyes.setter
    def dyes(self, value):
        """
        Sets the dye material definitions.

        :param list value: List of dye dicts.
        """

        self._fields['dyes'] = value or []

    @property
    def decals(self):
        """
        Returns the decal definitions.
        Decals can be materials or meshes (skeletal or static) applied on top.
        Each entry has {index, slot_name, options[], mesh_type}.

        :return: List of decal definitions.
        :rtype: list[dict]
        """

        return self._fields.get('decals', [])

    @decals.setter
    def decals(self, value):
        """
        Sets the decal definitions.

        :param list value: List of decal dicts.
        """

        self._fields['decals'] = value or []

    # --- Textures ---------------------------------------------------------- #

    @property
    def textures(self):
        """
        Returns DCC-side texture paths.

        :return: List of texture file paths.
        :rtype: list[str]
        """

        return self._fields.get('textures', [])

    @textures.setter
    def textures(self, value):
        """
        Sets the DCC-side texture paths.

        :param list value: List of texture file paths.
        """

        self._fields['textures'] = value or []

    @property
    def engine_textures(self):
        """
        Returns UE-side texture paths.

        :return: List of engine texture paths.
        :rtype: list[str]
        """

        return self._fields.get('engine_textures', [])

    @engine_textures.setter
    def engine_textures(self, value):
        """
        Sets the UE-side texture paths.

        :param list value: List of engine texture paths.
        """

        self._fields['engine_textures'] = value or []

    # --- Attach Sockets ---------------------------------------------------- #

    @property
    def attach_sockets(self):
        """
        Returns the attach socket names.
        These are the joints, virtual bones, or in-game sockets where this
        asset gets attached to its parent.

        :return: List of socket names.
        :rtype: list[str]
        """

        return self._fields.get('attach_sockets', [])

    @attach_sockets.setter
    def attach_sockets(self, value):
        """
        Sets the attach socket names.

        :param list value: List of socket names.
        """

        self._fields['attach_sockets'] = value or []

    # --- Dye Overrides ----------------------------------------------------- #

    @property
    def dye_overrides(self):
        """
        Returns the per-variant dye channel overrides.

        Shape is ``{slot_name: {channel_name: value}}`` where the value
        type is dictated by the parent asset's ``dyes`` schema —
        ``linear_color`` channels store a 4-element ``[r,g,b,a]`` list,
        ``scalar`` channels store a float.

        Empty dict on parent assets and unconfigured variants. Lookups
        through this property are safe even when the underlying dict
        was not stored on disk (legacy entries).

        :return: Mapping of slot name to channel-value dict.
        :rtype: dict
        """

        return self._fields.get('dye_overrides', {}) or {}

    @dye_overrides.setter
    def dye_overrides(self, value):
        """
        Sets the per-variant dye channel overrides.

        :param dict value: ``{slot_name: {channel_name: value}}``.
        """

        self._fields['dye_overrides'] = dict(value or {})

    def set_dye_override(self, slot_name, channel_name, value):
        """
        Set a single channel override on this variant.

        Writes through to ``dye_overrides`` so callers don't have to
        manage nested-dict creation. Empty ``slot_name`` or
        ``channel_name`` is silently ignored.

        :param str slot_name: Material slot name (matches a dye row).
        :param str channel_name: UE parameter name on that material.
        :param value: ``list[float]`` for linear_color, ``float`` for scalar.
        """

        if not slot_name or not channel_name:
            return
        overrides = self._fields.setdefault('dye_overrides', {})
        slot = overrides.setdefault(slot_name, {})
        slot[channel_name] = value

    def get_dye_override(self, slot_name, channel_name, default=None):
        """
        Read a single channel override, falling back to ``default``.

        :param str slot_name: Material slot name.
        :param str channel_name: Channel name.
        :param default: Value returned when the override is unset.
        :return: The stored value or ``default``.
        """

        return (self.dye_overrides.get(slot_name) or {}).get(channel_name, default)

    def get_dye_channel_type(self, slot_name, channel_name):
        """
        Look up a channel's type from this entry's ``dyes`` schema.

        Used by appliers that need to know whether a value should be
        pushed through ``SetVectorParameterValue`` or
        ``SetScalarParameterValue``. Returns ``''`` when the slot or
        channel is not declared on this entry.

        :param str slot_name: Material slot name.
        :param str channel_name: Channel name.
        :return: ``'linear_color'``, ``'scalar'``, or ``''``.
        :rtype: str
        """

        for dye in self.dyes:
            if dye.get('slot_name') != slot_name:
                continue
            for ch in dye.get('channels', []) or []:
                if ch.get('name') == channel_name:
                    return ch.get('type', '') or ''
            return ''
        return ''

    # --- Path resolution --------------------------------------------------- #

    def get_required_path(self, path_name):
        """
        Where one of this asset's folders is, on this machine.

        :param str path_name: A key - ``'RIGS_PATH'``, ``'SRC_MODELS_PATH'``.
        :return: The full path, or ``''`` when the asset has no path or its category does not
            name that folder.
        :rtype: str

        The version this replaces wrapped this in ``except Exception: pass`` and then answered
        None - out of a function that every folder property joins onto, so a category with a
        problem in its config produced a TypeError somewhere else entirely. The one thing that
        could raise here was reading the category config, and that answers the framework's
        defaults instead of raising now.
        """

        asset_path = self.full_path
        if not asset_path:
            return ''

        category_data = asset_paths.AssetDictData.load().get_category_data(self.category)
        if not category_data:
            logger.debug('The asset "%s" is in the category "%s", which the project\'s asset '
                         'config does not have.', self.asset_id, self.category)
            return ''

        folder = category_data.get_required_path(path_name)
        if not folder:
            return ''

        # A category's folders are stored as they were typed, which on Windows means
        # '_Source\\Rigs'. Normalise so this works wherever it runs.
        folder = folder.replace('\\', os.sep).replace('/', os.sep)

        return os.path.normpath(os.path.join(asset_path, folder))

    def create_folders(self):
        """
        Make the folders this asset's category says it has.

        :return: The placeholder files written into the ones that are still empty, so a caller
            can submit them. Empty when source control needs none.
        :rtype: list[str]

        The version this replaces built a list of six folders in the code - ``_Source/Meshes``,
        ``_Source/Rigs``, ``_Source/Animations``, ``Meshes``, ``Animations``, ``Textures`` -
        rather than asking the category, so a category that had moved one of them got both the
        folder it asked for and the folder this thought it should have. It also appended
        ``os.sep`` to each path to make a file helper treat it as a folder, and reached into
        Perforce twice.
        """

        base_path = self.full_path
        if not base_path:
            logger.warning('The asset "%s" has no path, so no folders were made.', self.name)
            return []

        category_data = asset_paths.AssetDictData.load().get_category_data(self.category)
        if category_data:
            wanted = [folder for folder in category_data.required_paths.values() if folder]
        else:
            # A category the project does not have: make what every asset has, from the
            # framework's own templates, rather than nothing at all.
            from mca.common.assetlist import asset_path_config

            wanted = [folder for folder in asset_path_config.required_paths().values() if folder]

        made = []
        for folder in wanted:
            folder = os.path.normpath(os.path.join(
                base_path, folder.replace('\\', os.sep).replace('/', os.sep)))
            if not os.path.isdir(folder):
                try:
                    os.makedirs(folder)
                except OSError as error:
                    logger.warning('Could not make %s: %s', folder, error)
                    continue
            made.append(folder)

        if not made:
            return []

        sourcecontrol.checkout(made)
        # Source control versions files, not folders, so a folder with nothing in it cannot be
        # stored at all until something is.
        placeholders = sourcecontrol.add_placeholders(made)

        logger.info('Made %s folders for "%s" under %s.', len(made), self.name, base_path)

        return placeholders

    def remove_from_assetlist(self):
        """
        Take this asset out of its category's file.

        :return: Whether it was there and the file was written.
        :rtype: bool
        """

        # Imported here: the registry imports this module.
        from mca.common.assetlist import unified_registry

        registry = unified_registry.UnifiedAssetRegistry.load(self.category)
        if not registry:
            logger.warning('The asset "%s" says it is in the category "%s", which has no asset '
                           'list, so there was nothing to remove it from.',
                           self.asset_id, self.category)
            return False

        if not registry.remove_asset_entry(self.asset_id):
            return False

        return bool(registry.save())
