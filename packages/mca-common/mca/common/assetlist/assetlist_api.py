"""
Headless API for the MCA asset list, for scripts, the in-DCC AI and MCP tools.

Every function takes plain values, never raises, and returns
``{'ok': bool, 'result': <json>, 'message': str}``. Writes go through the same
:class:`unified_registry.UnifiedAssetRegistry` the register UI uses, so an open
register window sees the change after a reload.

Written for a caller that cannot see the data
---------------------------------------------
The failure messages are part of the API. An unknown category lists the valid
ones; an unknown asset id offers near matches; a value outside a controlled
vocabulary names what is allowed. A caller that reads the message can correct
itself without another round trip.

The intended order for registering something is:

1. :func:`list_categories` - what exists, and how many assets each holds.
2. :func:`describe_category` - the vocabulary for that category: sub-categories,
   factions, slots, skeletons, body types, asset types, and whether it is gear.
3. :func:`describe_schema` - every field, its type, and whether it is controlled.
4. :func:`register_asset` - create it.

Conventions
-----------
- ``asset_id`` is the lowercase key in the ``.alist`` file. ``name`` is the
  display name. Most lookups accept either.
- Lists are capped at :data:`MAX_RESULTS`; the message says when a cap was hit.
- Paths are derived from the classification. Pass ``path`` only to override.
- ``register_asset``, ``update_asset``, ``remove_asset`` and ``transfer_asset``
  write to disk. The rest are read-only.

What changed in the port
------------------------
- ``transfer_asset`` wrote the asset into its new category, then removed it from the old one,
  and **checked neither save**. A failure on the second left the same asset id in two
  categories - which the manager resolves by keeping whichever it loaded first, with a debug
  message. It checks both now, and says plainly when a move has only half happened.
- ``check_assets`` reports the duplicate display names the validation report gained, since two
  assets answering to one name is exactly the kind of thing a caller who cannot see the data
  needs told.
- ``reload`` re-reads the categories as well as the assets: the project's category
  configuration is read once and kept now, so a category added elsewhere would not have shown
  up.
- Registering the first asset in a category with no file yet says so
  (``load(category, create=True)``) rather than relying on ``load`` answering None.

:Requires: mca.common.assetlist.asset_manager, unified_entry, unified_registry
:Side effects: The four write functions rewrite one category's .alist file.
"""

# python imports
import difflib
import functools
import os
import traceback

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_manager, asset_paths, unified_entry, unified_registry

logger = log.MCA_LOGGER

# Lists returned to AI callers are capped so a large registry cannot flood a response.
MAX_RESULTS = 200

# Fields a caller may set through register_asset / update_asset, with the type
# each one holds. Anything outside this set is rejected by name so a caller that
# guesses a field gets told, rather than having it silently ignored.
WRITABLE_FIELDS = {
    'name': 'str',
    'category': 'str',
    'subtype': 'str',
    'faction': 'str',
    'gender': 'str',
    'skeleton': 'str',
    'body_type': 'str',
    'asset_type': 'str',
    'additional_types': 'list',
    'slot': 'str',
    'built_for': 'list',
    'variant_of': 'str',
    'path': 'str',
    'engine_path': 'str',
    'description': 'str',
    'image': 'str',
    'materials': 'list',
    'textures': 'list',
    'engine_textures': 'list',
    'decals': 'list',
    'dyes': 'list',
    'dye_overrides': 'dict',
    'attach_sockets': 'list',
    'files': 'dict',
}

# Fields whose values come from asset_data.config rather than free text. The
# value is the describe_category / describe_schema key that lists the options.
CONTROLLED_FIELDS = {
    'category': 'categories',
    'subtype': 'subtypes',
    'faction': 'factions',
    'slot': 'slots',
    'skeleton': 'skeletons',
    'body_type': 'body_types',
    'asset_type': 'asset_types',
}


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
    Decorator: turn exceptions into failed responses instead of raising.

    The wrapped function returns ``(result, message)``; the wrapper wraps that
    in the response dict. ``functools.wraps`` keeps the name and docstring,
    which the AI registry and the MCP generator read for signatures.

    :param callable func: API function returning ``(result, message)``.
    :return: Wrapped function returning a response dict.
    :rtype: callable
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result, message = func(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            # Raised deliberately by the helpers below; the text is the guidance.
            return _response(False, None, str(exc).strip("'\""))
        except Exception as exc:
            logger.error('assetlist_api.%s failed: %s\n%s',
                         func.__name__, exc, traceback.format_exc())
            return _response(False, None, f'{type(exc).__name__}: {exc}')
        return _response(True, result, message)

    return wrapper


def _manager(force_reload=False):
    """
    :param bool force_reload: Re-read the .alist files from disk first.
    :return: The shared asset manager.
    :rtype: asset_manager.AssetManager
    """

    return asset_manager.get_asset_manager(force_reload=force_reload)


def _config():
    """
    :return: The category and global configuration from asset_data.config. Read once and kept;
        :func:`reload` is what re-reads it.
    :rtype: asset_paths.AssetDictData
    """

    return asset_paths.AssetDictData.load()


def _did_you_mean(value, options, limit=5):
    """
    Build a ' Did you mean ...' suffix for an unrecognised value.

    :param str value: What the caller supplied.
    :param list options: Valid values.
    :param int limit: Maximum suggestions.
    :return: A suffix string, empty when nothing is close.
    :rtype: str
    """

    if not value or not options:
        return ''
    close = difflib.get_close_matches(str(value).lower(),
                                      [str(o).lower() for o in options], n=limit, cutoff=0.6)
    if not close:
        return ''
    return ' Did you mean: {}?'.format(', '.join(repr(c) for c in close))


def _require_record(asset_id):
    """
    Resolve an asset id to a record, or raise with guidance.

    :param str asset_id: The asset id (or display name) to look up.
    :return: The matching record.
    :rtype: asset_manager.AssetRecord
    :raises ValueError: When the id is empty or unknown.
    """

    if not asset_id:
        raise ValueError('asset_id is required.')

    manager = _manager()
    record = manager.get_record(asset_id) or manager.get_record_by_name(asset_id)
    if record:
        return record

    all_ids = [r.asset_id for r in manager.iter_all()]
    raise ValueError(f'No asset with id or name {asset_id!r}.'
                     f'{_did_you_mean(asset_id, all_ids)}'
                     ' Use search_assets or list_assets to find it.')


def _require_category(category):
    """
    Check a category exists, or raise listing the valid ones.

    :param str category: Category name.
    :return: The category name as configured (correct casing).
    :rtype: str
    :raises ValueError: When the category is empty or unknown.
    """

    if not category:
        raise ValueError('category is required. Call list_categories to see the options.')

    known = _config().categories_names or []
    for name in known:
        if str(name).lower() == str(category).lower():
            return name

    raise ValueError(f'Unknown category {category!r}. Valid: {", ".join(sorted(known))}.'
                     f'{_did_you_mean(category, known)}')


def _vocabulary(category):
    """
    Collect every controlled vocabulary that applies to a category.

    :param str category: Category name.
    :return: Mapping of vocabulary name to its list of values.
    :rtype: dict
    """

    config = _config()
    global_data = config.global_data
    category_data = config.get_category_data(category)

    return {
        'categories': list(config.categories_names or []),
        'subtypes': list(getattr(category_data, 'subcategories', None) or []),
        'factions': list(getattr(category_data, 'factions', None) or []),
        'slots': list(getattr(global_data, 'slots', None) or []),
        'skeletons': list(getattr(global_data, 'skeletons', None) or []),
        'body_types': list((getattr(global_data, 'body_types', None) or {}).keys()),
        'asset_types': list(getattr(global_data, 'asset_types', None) or []),
        'attach_sockets': list(getattr(global_data, 'attach_sockets', None) or []),
    }


# Record attribute that backs each controlled field, for reading values in use.
_FIELD_ATTRIBUTE = {
    'subtype': 'subtype',
    'faction': 'faction',
    'slot': 'slot',
    'skeleton': 'skeleton',
    'body_type': 'body_type',
    'asset_type': 'asset_type',
}


def _values_in_use(field, category):
    """
    Collect the values existing assets actually carry for a field.

    asset_data.config has drifted from the data: assets use slots and
    sub-categories the config never declared. Rejecting those would block work
    on assets that already exist, so they count as valid and are reported as
    unconfigured instead.

    :param str field: Field name from CONTROLLED_FIELDS.
    :param str category: Category to scan, or '' for every category.
    :return: The values in use.
    :rtype: set
    """

    attribute = _FIELD_ATTRIBUTE.get(field)
    if not attribute:
        return set()

    values = set()
    for record in _manager().iter_all():
        # Category-scoped fields only count within their own category; the
        # global ones (slot, skeleton, body_type, asset_type) count everywhere.
        if category and field in ('subtype', 'faction') and record.category != category:
            continue
        value = getattr(record, attribute, None)
        if value:
            values.add(value)
    return values


def _check_controlled(field, value, category):
    """
    Validate a value against its controlled vocabulary.

    Accepted when the value is configured, or already carried by an existing
    asset. Anything else is refused, because a typo here creates a second
    sub-category or faction that then looks real to everyone else.

    :param str field: Field name from CONTROLLED_FIELDS.
    :param str value: Proposed value.
    :param str category: Category the asset belongs to.
    :return: A note when the value is valid only because it is already in use,
        otherwise an empty string.
    :rtype: str
    :raises ValueError: When the value is in neither set.
    """

    if not value:
        return ''

    configured = _vocabulary(category).get(CONTROLLED_FIELDS[field]) or []
    in_use = _values_in_use(field, category)
    if not configured and not in_use:
        # Nothing to check against; free text is all there is.
        return ''

    lowered = str(value).lower()
    if lowered in {str(o).lower() for o in configured}:
        return ''
    if lowered in {str(o).lower() for o in in_use}:
        return (f'{field}={value!r} is used by existing assets but is not in '
                f'asset_data.config; consider adding it there.')

    options = sorted(set(configured) | in_use)
    raise ValueError(
        f'{field}={value!r} is not a known value for category {category!r}. '
        f'Valid: {", ".join(str(o) for o in options)}.'
        f'{_did_you_mean(value, options)} '
        f'Add it in the register UI first if it is genuinely new.')


def _record_to_dict(record, verbose=False):
    """
    Convert a record to a JSON-safe dict.

    The compact form carries what a caller needs to identify an asset and ask
    for more. ``verbose`` adds the heavy list fields.

    :param asset_manager.AssetRecord record: The record.
    :param bool verbose: Include materials, dyes, decals, textures and sockets.
    :return: JSON-serialisable asset data.
    :rtype: dict
    """

    data = {
        'asset_id': record.asset_id,
        'name': record.name,
        'category': record.category,
        'subtype': record.subtype,
        'faction': record.faction,
        'asset_type': record.asset_type,
        'skeleton': record.skeleton,
        'body_type': record.body_type,
        'slot': record.slot,
        'built_for': list(record.built_for_all) or None,
        'parent_id': record.parent_id,
        'variant_of': record.variant_of,
        'path': record.relative_path,
        'engine_path': record.engine_path,
        'description': record.description,
    }
    if verbose:
        raw = dict(record.raw or {})
        for field in ('materials', 'dyes', 'decals', 'textures', 'engine_textures',
                      'attach_sockets', 'additional_types', 'dye_overrides', 'image',
                      'gender'):
            data[field] = raw.get(field)
    return {key: value for key, value in data.items() if value not in (None, '')}


def _cap(items, limit):
    """
    Apply the caller's limit and the hard cap.

    :param list items: Items to trim.
    :param int limit: Caller's requested limit; 0 or None means MAX_RESULTS.
    :return: ``(trimmed, total, truncated)``.
    :rtype: tuple
    """

    total = len(items)
    limit = min(int(limit) if limit else MAX_RESULTS, MAX_RESULTS)
    return items[:limit], total, total > limit


# --- Discovery ---------------------------------------------------------------------------------------------------

@_safe
def list_categories():
    """
    List every asset category with how many assets it holds.

    Start here: the category drives which sub-categories, factions and folder
    layout apply to an asset.

    :return: Response with ``[{'name', 'asset_count', 'is_gear', 'gear_root'}]``.
    :rtype: dict
    """

    manager = _manager()
    config = _config()
    counts = {}
    for record in manager.iter_all():
        counts[record.category] = counts.get(record.category, 0) + 1

    result = []
    for name in sorted(config.categories_names or []):
        category_data = config.get_category_data(name)
        result.append({
            'name': name,
            'asset_count': counts.get(name, 0),
            'is_gear': bool(getattr(category_data, 'is_gear', False)),
            'gear_root': getattr(category_data, 'gear_root', '') or '',
        })
    return result, f'{len(result)} categories, {sum(counts.values())} assets.'


@_safe
def describe_category(category):
    """
    Describe one category: its controlled vocabularies and folder layout.

    Call this before register_asset. Every value it returns is accepted by
    register_asset for the matching field; anything else is rejected.

    :param str category: Category name, e.g. 'Characters' or 'Armor'.
    :return: Response with the vocabularies, gear flag and folder layout.
    :rtype: dict
    """

    name = _require_category(category)
    config = _config()
    category_data = config.get_category_data(name)

    folders = {}
    for key in ('RIGS_PATH', 'MODELS_PATH', 'ANIMATIONS_PATH', 'TEXTURES_PATH',
                'SRC_RIGS_PATH', 'SRC_MODELS_PATH', 'FLAGS_PATH'):
        try:
            folder = category_data.get_required_path(key)
        except Exception:
            folder = None
        if folder:
            folders[key] = folder

    result = dict(_vocabulary(name))
    result.pop('categories', None)

    # Values existing assets carry that asset_data.config never declared. They
    # are accepted on write; listing them here is what keeps a caller from
    # inventing a third spelling of something that already has two.
    unconfigured = {}
    for field, vocabulary in CONTROLLED_FIELDS.items():
        if field == 'category':
            continue
        extra = sorted(_values_in_use(field, name)
                       - {str(o) for o in (result.get(vocabulary) or [])})
        if extra:
            unconfigured[vocabulary] = extra

    result.update({
        'name': name,
        'is_gear': bool(getattr(category_data, 'is_gear', False)),
        'gear_root': getattr(category_data, 'gear_root', '') or '',
        'asset_count': sum(1 for r in _manager().iter_all() if r.category == name),
        'folders': folders,
        'unconfigured_values_in_use': unconfigured,
    })
    message = (f'{name}: {result["asset_count"]} assets, '
               f'{len(result["subtypes"])} sub-categories, '
               f'{len(result["factions"])} factions.')
    if unconfigured:
        message += (' Some values in use are missing from asset_data.config; see '
                    'unconfigured_values_in_use before inventing a new one.')
    return result, message


@_safe
def describe_schema():
    """
    Describe every field an asset entry can carry.

    Tells a caller which fields it may write, what type each holds, and which
    ones are restricted to a vocabulary (and where to read that vocabulary).

    :return: Response with ``{'writable', 'read_only', 'notes'}``.
    :rtype: dict
    """

    writable = {}
    for field, kind in sorted(WRITABLE_FIELDS.items()):
        entry = {'type': kind}
        if field in CONTROLLED_FIELDS:
            entry['controlled_by'] = CONTROLLED_FIELDS[field]
            entry['read_options_from'] = ('list_categories' if field == 'category'
                                          else 'describe_category')
        writable[field] = entry

    notes = [
        'asset_id is derived from name when registering and cannot be changed afterwards; '
        'use transfer_asset to move an asset between categories.',
        'path and engine_path are derived from the classification. Only pass them to override.',
        'built_for names the parent character(s) by display name. Pass one name or a '
        'list of them - gear can be worn by more than one character, and it shows under '
        'each. The folder path does not depend on which parents they are.',
        'variant_of makes a character a restyle of another - a different body on the same '
        'skeleton, which apply_variant swaps in while equipped gear stays on. It names the '
        'base by ASSET ID, not display name, because character names are not unique. '
        'Leave it empty for a character that is a base in its own right.',
        'materials, dyes, decals and attach_sockets are structured lists edited in the register UI; '
        'pass them through unchanged unless you know the shape.',
    ]
    return ({'writable': writable, 'read_only': ['asset_id', 'parent_id'], 'notes': notes},
            f'{len(writable)} writable fields, {len(CONTROLLED_FIELDS)} controlled.')


# --- Queries -----------------------------------------------------------------------------------------------------

@_safe
def get_asset(asset_id, verbose=False):
    """
    Get one asset by id or display name.

    :param str asset_id: Asset id or display name; both are accepted.
    :param bool verbose: Include materials, dyes, decals, textures and sockets.
    :return: Response with the asset dict.
    :rtype: dict
    """

    record = _require_record(asset_id)
    return _record_to_dict(record, verbose=verbose), f'{record.name} ({record.asset_id}).'


@_safe
def list_assets(category='', subtype='', faction='', built_for='', limit=50):
    """
    List assets, optionally filtered.

    :param str category: Restrict to this category.
    :param str subtype: Restrict to this sub-category.
    :param str faction: Restrict to this faction.
    :param str built_for: Restrict to gear built for this character, matching
        any of its parents.
    :param int limit: Maximum returned, capped at 200.
    :return: Response with a list of compact asset dicts.
    :rtype: dict
    """

    if category:
        category = _require_category(category)

    records = []
    for record in _manager().iter_all():
        if category and record.category != category:
            continue
        if subtype and (record.subtype or '').lower() != subtype.lower():
            continue
        if faction and (record.faction or '').lower() != faction.lower():
            continue
        if built_for and built_for.lower() not in {
                str(p).lower() for p in (record.built_for_all or ())}:
            continue
        records.append(record)

    records.sort(key=lambda r: (r.category or '', (r.name or '').lower()))
    shown, total, truncated = _cap(records, limit)
    message = f'{len(shown)} of {total} asset(s).'
    if truncated:
        message += ' Narrow the filters or raise limit to see the rest.'
    if not total:
        message = 'No assets matched. Use list_categories to see what exists.'
    return [_record_to_dict(r) for r in shown], message


@_safe
def search_assets(query, limit=20):
    """
    Search assets by id, name or description.

    :param str query: Text to look for; case-insensitive substring match.
    :param int limit: Maximum returned, capped at 200.
    :return: Response with a list of compact asset dicts.
    :rtype: dict
    """

    if not query:
        raise ValueError('query is required.')

    text = query.lower()
    matches = []
    for record in _manager().iter_all():
        haystack = ' '.join(filter(None, (record.asset_id, record.name, record.description)))
        if text in haystack.lower():
            matches.append(record)

    matches.sort(key=lambda r: (text not in (r.name or '').lower(), (r.name or '').lower()))
    shown, total, truncated = _cap(matches, limit)
    if not total:
        all_names = [r.name for r in _manager().iter_all() if r.name]
        return [], f'Nothing matched {query!r}.{_did_you_mean(query, all_names)}'
    message = f'{len(shown)} of {total} match(es) for {query!r}.'
    if truncated:
        message += ' Raise limit to see the rest.'
    return [_record_to_dict(r) for r in shown], message


@_safe
def get_asset_paths(asset_id):
    """
    Get every resolved filesystem path for an asset.

    :param str asset_id: Asset id or display name.
    :return: Response with the resolved paths; unresolved entries are omitted
        and named in the message.
    :rtype: dict
    """

    record = _require_record(asset_id)
    found = {
        'asset_id': record.asset_id,
        'full_path': getattr(record, 'full_path', None),
        'relative_path': record.relative_path,
        'engine_path': record.engine_path,
        'rigs_path': record.rigs_path,
        'animations_path': record.animations_path,
        'models_path': record.models_path,
        'textures_path': record.textures_path,
        'skin_data_path': record.skin_data_path,
    }
    resolved = {k: v for k, v in found.items() if v}
    missing = sorted(set(found) - set(resolved))
    message = f'{len(resolved) - 1} path(s) for {record.name}.'
    if missing:
        message += (f' Unresolved: {", ".join(missing)}.'
                    ' A missing folder usually means asset_data.config has no entry'
                    f' for category {record.category!r}.')
    return resolved, message


@_safe
def get_asset_hierarchy(asset_id):
    """
    Get an asset's parent chain, root first.

    :param str asset_id: Asset id or display name.
    :return: Response with a list of compact asset dicts ending in the asset.
    :rtype: dict
    """

    record = _require_record(asset_id)
    chain = _manager().get_parent_chain(record.asset_id)
    result = [_record_to_dict(r) for r in chain]
    if not result or result[-1].get('asset_id') != record.asset_id:
        result.append(_record_to_dict(record))
    return result, f'{len(result)} level(s) for {record.name}.'


@_safe
def get_asset_children(asset_id, include_descendants=False, limit=50):
    """
    Get the gear and variants built for an asset.

    :param str asset_id: Asset id or display name.
    :param bool include_descendants: Walk the whole subtree, not just direct children.
    :param int limit: Maximum returned, capped at 200.
    :return: Response with a list of compact asset dicts.
    :rtype: dict
    """

    record = _require_record(asset_id)
    manager = _manager()
    children = list(manager.iter_descendants(record.asset_id) if include_descendants
                    else manager.iter_children(record.asset_id))
    children.sort(key=lambda r: ((r.slot or ''), (r.name or '').lower()))
    shown, total, truncated = _cap(children, limit)
    message = f'{len(shown)} of {total} child asset(s) for {record.name}.'
    if not total:
        message = f'{record.name} has no gear or variants built for it.'
    elif truncated:
        message += ' Raise limit to see the rest.'
    return [_record_to_dict(r) for r in shown], message


@_safe
def list_variants(asset_id):
    """
    List the other looks a character can be swapped to.

    A variant is a whole-character restyle - a different body riding the same
    skeleton - as opposed to gear, which goes on top. Pass the base or any of
    its variants: the answer is the same family either way, which is what a
    "swap this character" picker needs.

    :param str asset_id: Any member of the family - a base or a variant.
    :return: Response with ``{'base', 'variants', 'current_is_variant'}``.
    :rtype: dict
    """

    record = _require_record(asset_id)
    family = _manager().get_variant_family(record.asset_id)
    if not family:
        return ({'base': None, 'variants': [], 'current_is_variant': False},
                f'{record.name} has no variants and is not one.')

    base = family[0]
    variants = [_record_to_dict(r) for r in family[1:]]
    result = {'base': _record_to_dict(base),
              'variants': variants,
              'current_is_variant': bool(record.variant_of)}
    if not variants:
        return result, f'{base.name} is a base character with no variants registered.'
    names = ', '.join(r['name'] for r in variants)
    return result, f'{base.name} has {len(variants)} variant(s): {names}.'


@_safe
def set_variant_base(asset_id, base_asset_id):
    """
    Make a character a variant of another, or clear that.

    Convenience over ``update_asset(asset_id, {'variant_of': ...})``, and the
    same validation applies: the base has to exist, be a character, and not be
    a variant itself.

    :param str asset_id: The variant's asset id or display name.
    :param str base_asset_id: The base character's asset id. Empty clears it,
        making this character a base in its own right.
    :return: Response with the updated asset dict.
    :rtype: dict
    """

    record = _require_record(asset_id)
    inner = update_asset(record.asset_id, {'variant_of': base_asset_id or ''})
    if not inner['ok']:
        raise ValueError(inner['message'])
    if base_asset_id:
        base = _manager().get_record(record.variant_of or base_asset_id)
        base_name = base.name if base else base_asset_id
        return inner['result'], f'{record.name} is now a variant of {base_name}.'
    return inner['result'], f'{record.name} is no longer a variant of anything.'


@_safe
def get_asset_count(category=''):
    """
    Count registered assets, optionally in one category.

    :param str category: Restrict the count to this category.
    :return: Response with the integer count.
    :rtype: dict
    """

    if category:
        category = _require_category(category)
        count = sum(1 for r in _manager().iter_all() if r.category == category)
        return count, f'{count} asset(s) in {category}.'
    count = sum(1 for _ in _manager().iter_all())
    return count, f'{count} asset(s) registered.'


@_safe
def check_assets():
    """
    Run the registry health check.

    Reports records missing required fields, gear pointing at a parent that does
    not exist, duplicate namespaces, and dependency cycles. An empty result is a
    clean registry.

    :return: Response with the validation report and the record count.
    :rtype: dict
    """

    manager = _manager(force_reload=True)
    report = manager.validation_report
    if report is None:
        return {'record_count': sum(1 for _ in manager.iter_all())}, 'Validation did not run.'

    result = {
        'record_count': sum(1 for _ in manager.iter_all()),
        'missing_required_fields': {k: sorted(v) for k, v in
                                    list(report.missing_required_fields.items())[:MAX_RESULTS]},
        'dangling_parents': dict(list(report.dangling_parents.items())[:MAX_RESULTS]),
        'duplicate_namespaces': {k: sorted(v) for k, v in
                                 list(report.duplicate_namespaces.items())[:MAX_RESULTS]},
        # Two assets answering to one name: only the first can be opened by name, so a caller
        # that cannot see the data needs telling.
        'duplicate_names': {k: sorted(v) for k, v in
                            list(report.duplicate_names.items())[:MAX_RESULTS]},
        'cyclic_dependencies': list(report.cyclic_dependencies)[:MAX_RESULTS],
    }
    problems = (len(result['missing_required_fields']) + len(result['dangling_parents'])
                + len(result['duplicate_namespaces']) + len(result['duplicate_names'])
                + len(result['cyclic_dependencies']))
    message = (f'{result["record_count"]} assets, no problems found.' if not problems
               else f'{result["record_count"]} assets, {problems} problem(s) found.')
    return result, message


@_safe
def reload():
    """
    Re-read the registry from disk: every .alist file, and the project's category
    configuration.

    Call this after editing any of them outside the API. The configuration is read once and
    kept, so a category added elsewhere does not appear until this runs.

    :return: Response with the record count.
    :rtype: dict
    """

    asset_paths.reload()
    count = sum(1 for _ in _manager(force_reload=True).iter_all())
    return count, f'Reloaded {count} asset(s) and the category configuration.'


# --- Explicit file references ------------------------------------------------------------------------------------

@_safe
def list_file_kinds():
    """
    List the named files an asset can record, and where each normally lives.

    :return: Response with ``[{'kind', 'label', 'folder_key', 'extension'}]``.
    :rtype: dict
    """

    result = [{'kind': kind, 'label': spec['label'],
               'folder_key': spec['folder_key'], 'extension': spec['extension']}
              for kind, spec in sorted(unified_entry.ASSET_FILE_KINDS.items())]
    return result, f'{len(result)} file kind(s): {", ".join(k["kind"] for k in result)}.'


@_safe
def get_asset_files(asset_id):
    """
    Report every named file for an asset, and whether the record still matches disk.

    Status per kind: ``recorded`` (named and present), ``stale`` (named but gone),
    ``inferred`` (nothing named, one candidate found), ``ambiguous`` (nothing named,
    several found) or ``missing`` (nothing named, nothing found).

    :param str asset_id: Asset id or display name.
    :return: Response with ``{kind: {'status', 'path', 'recorded', 'detail'}}``.
    :rtype: dict
    """

    record = _require_record(asset_id)
    entry = record.source_entry
    if entry is None:
        raise ValueError(f'{record.asset_id!r} has no backing entry to read files from.')

    result = {}
    for kind in sorted(unified_entry.ASSET_FILE_KINDS):
        status, path, detail = entry.file_status(kind)
        result[kind] = {'status': status, 'path': path,
                        'recorded': entry.get_file(kind), 'detail': detail}

    problems = [k for k, v in result.items()
                if v['status'] in (unified_entry.FILE_STALE, unified_entry.FILE_AMBIGUOUS)]
    message = f'{len(result)} file kind(s) for {record.name}.'
    if problems:
        message += (f' Needs attention: {", ".join(problems)}.'
                    ' Call repair_asset_files to re-record them from disk.')
    return result, message


@_safe
def set_asset_file(asset_id, kind, file_path):
    """
    Record which file backs one kind for an asset.

    **Call this from any tool that saves or renames one of these files.** That is
    what keeps the registry in step; without it a recorded path goes stale and
    lookups quietly fall back to scanning the folder.

    :param str asset_id: Asset id or display name.
    :param str kind: File kind; see list_file_kinds.
    :param str file_path: Absolute or asset-relative path. Empty clears the record.
    :return: Response with the stored relative path.
    :rtype: dict
    """

    record = _require_record(asset_id)
    if kind not in unified_entry.ASSET_FILE_KINDS:
        raise ValueError(
            f'Unknown file kind {kind!r}. '
            f'Valid: {", ".join(sorted(unified_entry.ASSET_FILE_KINDS))}.'
            f'{_did_you_mean(kind, list(unified_entry.ASSET_FILE_KINDS))}')

    registry = unified_registry.UnifiedAssetRegistry.load(record.category)
    if registry is None:
        raise ValueError(f'No registry file for category {record.category!r}.')
    entry = registry.get_asset_entry(record.asset_id, skip_dialog=True)
    if entry is None:
        raise ValueError(f'{record.asset_id!r} is not in the {record.category} registry file.')

    stored = entry.set_file(kind, file_path)
    registry.update_registry_dict()
    registry.save()
    _manager(force_reload=True)

    if not stored:
        return {'asset_id': record.asset_id, 'kind': kind, 'path': ''}, \
               f'Cleared the {kind} file for {record.name}.'
    return ({'asset_id': record.asset_id, 'kind': kind, 'path': stored},
            f'Recorded {kind} for {record.name}: {stored}')


@_safe
def check_asset_files(category=''):
    """
    Find assets whose recorded files no longer match what is on disk.

    Run this after a batch rename or a big move. ``stale`` means a recorded file
    has gone; ``ambiguous`` means nothing is recorded and the folder holds more
    than one candidate, so tooling is picking one arbitrarily.

    :param str category: Restrict the scan to one category.
    :return: Response with ``{'stale': [...], 'ambiguous': [...], 'checked': int}``.
    :rtype: dict
    """

    if category:
        category = _require_category(category)

    stale, ambiguous, checked = [], [], 0
    for record in _manager().iter_all():
        if category and record.category != category:
            continue
        entry = record.source_entry
        if entry is None:
            continue
        checked += 1
        for kind in sorted(unified_entry.ASSET_FILE_KINDS):
            status, path, detail = entry.file_status(kind)
            item = {'asset_id': record.asset_id, 'name': record.name,
                    'category': record.category, 'kind': kind,
                    'recorded': entry.get_file(kind), 'found': path, 'detail': detail}
            if status == unified_entry.FILE_STALE:
                stale.append(item)
            elif status == unified_entry.FILE_AMBIGUOUS:
                ambiguous.append(item)

    result = {'checked': checked,
              'stale': stale[:MAX_RESULTS], 'ambiguous': ambiguous[:MAX_RESULTS]}
    if not stale and not ambiguous:
        return result, f'{checked} asset(s) checked, every file reference is current.'
    return result, (f'{checked} asset(s) checked: {len(stale)} stale, '
                    f'{len(ambiguous)} ambiguous. repair_asset_files fixes the '
                    'unambiguous ones.')


@_safe
def repair_asset_files(asset_id='', category=''):
    """
    Re-record file references from what is actually on disk.

    Only touches cases with exactly one candidate, so it never guesses between
    two files. Ambiguous ones are returned for a human to settle with
    set_asset_file. Pass an asset id, a category, or neither for everything.

    :param str asset_id: Repair a single asset.
    :param str category: Repair one category.
    :return: Response with ``{'repaired': [...], 'skipped': [...]}``.
    :rtype: dict
    """

    if asset_id:
        targets = [_require_record(asset_id)]
    else:
        if category:
            category = _require_category(category)
        targets = [r for r in _manager().iter_all()
                   if not category or r.category == category]

    repaired, skipped, dirty = [], [], {}
    for record in targets:
        entry = record.source_entry
        if entry is None:
            continue
        for kind in sorted(unified_entry.ASSET_FILE_KINDS):
            status, path, detail = entry.file_status(kind)
            if status in (unified_entry.FILE_RECORDED, unified_entry.FILE_MISSING):
                continue
            # Never choose between two files, whatever the status: a stale
            # record with several candidates is exactly when guessing does harm.
            candidates = entry.file_candidates(kind)
            if not path or len(candidates) > 1:
                skipped.append({'asset_id': record.asset_id, 'kind': kind,
                                'status': status, 'detail': detail,
                                'candidates': [os.path.basename(c) for c in candidates[:10]]})
                continue

            registry = dirty.get(record.category)
            if registry is None:
                registry = unified_registry.UnifiedAssetRegistry.load(record.category)
                if registry is None:
                    continue
                dirty[record.category] = registry
            live = registry.get_asset_entry(record.asset_id, skip_dialog=True)
            if live is None:
                continue
            stored = live.set_file(kind, path)
            repaired.append({'asset_id': record.asset_id, 'kind': kind,
                             'path': stored, 'was': status})

    for registry in dirty.values():
        registry.update_registry_dict()
        registry.save()
    if dirty:
        _manager(force_reload=True)

    result = {'repaired': repaired[:MAX_RESULTS], 'skipped': skipped[:MAX_RESULTS]}
    message = f'Re-recorded {len(repaired)} file reference(s).'
    if skipped:
        message += (f' {len(skipped)} left alone because more than one candidate '
                    'matched; use set_asset_file to pick one.')
    return result, message


# --- Writes ------------------------------------------------------------------------------------------------------

def _normalize_parents(value):
    """
    Accept the several shapes a caller may use for ``built_for``.

    A list comes through as-is. A string may name one parent or several
    separated by commas, which is what a text-only caller (MCP, the AI
    registry) can express without JSON quoting.

    :param value: Name, comma-separated names, or a list of names.
    :return: A single name, a list when there are several, or '' for none.
    :rtype: str or list[str]
    """

    if isinstance(value, (list, tuple)):
        names = [str(v).strip() for v in value if str(v).strip()]
    else:
        names = [part.strip() for part in str(value or '').split(',') if part.strip()]

    # De-duplicate case-insensitively, keeping the caller's order and spelling.
    seen = set()
    unique = []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            unique.append(name)

    if not unique:
        return ''
    return unique[0] if len(unique) == 1 else unique


def _check_variant_base(value, own_asset_id=''):
    """
    Validate a ``variant_of`` value and return it normalised.

    A variant points at a base character by asset id. Three things make that
    wrong and each is caught here rather than written: a base that does not
    exist, a base that is not a character, and a chain (a variant of a variant),
    which would leave ``revert_variant`` unable to say what the original body was.

    :param str value: The base character's asset id, or empty.
    :param str own_asset_id: The id of the asset being written, to catch self-reference.
    :return: The validated asset id, or ''.
    :rtype: str
    :raises ValueError: When the base is unusable.
    """

    base_id = str(value or '').strip()
    if not base_id:
        return ''

    if own_asset_id and base_id.lower() == str(own_asset_id).strip().lower():
        raise ValueError('An asset cannot be a variant of itself.')

    manager = _manager()
    base = manager.get_record(base_id)
    if base is None:
        by_name = manager.get_record_by_name(base_id)
        if by_name is not None:
            raise ValueError(
                f'variant_of takes an asset id, not a display name. Did you mean '
                f'{by_name.asset_id!r}? Character names are not unique, which is why '
                'this field holds an id.')
        known = [r.asset_id for r in manager.iter_category('Characters')]
        raise ValueError(f'No asset with id {base_id!r} to be a variant of.'
                         f'{_did_you_mean(base_id, known)}')

    if base.category != 'Characters':
        raise ValueError(f'{base.asset_id!r} is in {base.category}, not Characters. '
                         'A variant restyles a whole character; gear uses built_for instead.')

    if base.variant_of:
        raise ValueError(f'{base.asset_id!r} is itself a variant of {base.variant_of!r}. '
                         'Point at the base character instead, so reverting knows what the '
                         'original body was.')

    return base.asset_id


def _validate_fields(fields, category):
    """
    Reject unknown field names and values outside a controlled vocabulary.

    :param dict fields: Field name to value.
    :param str category: Category the asset belongs to.
    :return: Notes worth appending to the response message, e.g. a value that
        is valid only because existing assets already use it.
    :rtype: list[str]
    :raises ValueError: On an unknown field or an invalid controlled value.
    """

    unknown = sorted(set(fields) - set(WRITABLE_FIELDS))
    if unknown:
        raise ValueError(
            f'Unknown field(s): {", ".join(unknown)}.'
            f'{_did_you_mean(unknown[0], list(WRITABLE_FIELDS))}'
            ' Call describe_schema for the writable fields.')

    notes = []
    for field in CONTROLLED_FIELDS:
        if field in fields and field != 'category':
            note = _check_controlled(field, fields[field], category)
            if note:
                notes.append(note)
    return notes


@_safe
def register_asset(name, category, subtype='', faction='', skeleton='', body_type='',
                   asset_type='SkeletalMesh', built_for='', slot='', description='',
                   path='', engine_path='', asset_id='', variant_of=''):
    """
    Register a new asset and save it to its category's .alist file.

    Call describe_category first: subtype, faction, slot, skeleton, body_type and
    asset_type are checked against that category's vocabulary and a value outside
    it is rejected rather than written.

    :param str name: Display name, e.g. 'Clockwork'.
    :param str category: Category name; see list_categories.
    :param str subtype: Sub-category; see describe_category.
    :param str faction: Faction; see describe_category.
    :param str skeleton: Skeleton reference, e.g. 'SampleBot'.
    :param str body_type: Body type, e.g. 'Humanoid'.
    :param str asset_type: SkeletalMesh, StaticMesh or Material.
    :param str built_for: Parent character display name for gear; separate several
        with commas when more than one character can wear it.
    :param str slot: Equipment slot, for gear.
    :param str description: Free text description.
    :param str path: Override the derived DCC path. Leave empty to derive it.
    :param str engine_path: Override the derived Unreal path. Leave empty to derive it.
    :param str asset_id: Override the id derived from the name.
    :param str variant_of: For a character that is a restyle of another, the base
        character's asset id. See describe_schema.
    :return: Response with the created asset dict.
    :rtype: dict
    """

    if not name:
        raise ValueError('name is required.')
    category = _require_category(category)
    built_for = _normalize_parents(built_for)
    variant_of = _check_variant_base(variant_of, asset_id or '')

    fields = {'subtype': subtype, 'faction': faction, 'skeleton': skeleton,
              'body_type': body_type, 'asset_type': asset_type, 'slot': slot}
    notes = _validate_fields({k: v for k, v in fields.items() if v}, category)

    # create=True: a category with no file yet is where the first asset goes.
    registry = unified_registry.UnifiedAssetRegistry.load(category, create=True)

    entry = unified_entry.UnifiedAssetEntry.create(
        asset_name=name, category=category, subtype=subtype, faction=faction,
        skeleton=skeleton, body_type=body_type, asset_type=asset_type,
        built_for=built_for, slot=slot, description=description,
        path=path, engine_path=engine_path, asset_id=asset_id or None,
        variant_of=variant_of)

    if registry.get_asset_entry(entry.asset_id, skip_dialog=True):
        raise ValueError(f'An asset with id {entry.asset_id!r} already exists in {category}. '
                         'Use update_asset to change it, or pick another name.')

    registry.add_asset_entry(entry)
    registry.save()

    record = _manager(force_reload=True).get_record(entry.asset_id)
    result = _record_to_dict(record) if record else {'asset_id': entry.asset_id, 'name': name}
    message = f'Registered {name} as {entry.asset_id!r} in {category}.'
    return result, ' '.join([message] + notes)


@_safe
def update_asset(asset_id, fields):
    """
    Change fields on an existing asset and save the category file.

    Only the fields passed are touched. Call describe_schema for the writable
    field names; controlled values are validated before anything is written.

    :param str asset_id: Asset id or display name.
    :param dict fields: Field name to new value, e.g. ``{'description': '...'}``.
    :return: Response with the updated asset dict.
    :rtype: dict
    """

    record = _require_record(asset_id)
    if not fields:
        raise ValueError('fields is required: pass at least one field to change. '
                         'Call describe_schema for the writable fields.')
    if not isinstance(fields, dict):
        raise ValueError('fields must be a mapping of field name to new value.')

    if 'category' in fields:
        raise ValueError('Use transfer_asset to move an asset to another category.')

    if 'variant_of' in fields:
        fields = dict(fields)
        fields['variant_of'] = _check_variant_base(fields['variant_of'], record.asset_id)
    if 'built_for' in fields:
        fields = dict(fields)
        fields['built_for'] = _normalize_parents(fields['built_for'])
    notes = _validate_fields(fields, record.category)

    registry = unified_registry.UnifiedAssetRegistry.load(record.category)
    if registry is None:
        raise ValueError(f'No registry file for category {record.category!r}.')

    entry = registry.get_asset_entry(record.asset_id, skip_dialog=True)
    if entry is None:
        raise ValueError(f'{record.asset_id!r} is not in the {record.category} registry file. '
                         'The manager may be stale; call reload.')

    for field, value in fields.items():
        entry.fields[field] = value
    registry.update_registry_dict()
    registry.save()

    updated = _manager(force_reload=True).get_record(record.asset_id)
    changed = ', '.join(sorted(fields))
    message = f'Updated {changed} on {record.name} ({record.asset_id}).'
    return _record_to_dict(updated) if updated else None, ' '.join([message] + notes)


@_safe
def remove_asset(asset_id):
    """
    Remove an asset from its category's .alist file.

    This deletes the registry entry. It does not touch files on disk or in
    Unreal, and anything built for the asset is left pointing at nothing.

    :param str asset_id: Asset id or display name.
    :return: Response with the removed asset's id and name.
    :rtype: dict
    """

    record = _require_record(asset_id)
    children = list(_manager().iter_children(record.asset_id))
    registry = unified_registry.UnifiedAssetRegistry.load(record.category)
    if registry is None:
        raise ValueError(f'No registry file for category {record.category!r}.')

    if not registry.remove_asset_entry(record.asset_id):
        raise ValueError(f'{record.asset_id!r} is not in the {record.category} registry file.')
    registry.save()
    _manager(force_reload=True)

    message = f'Removed {record.name} ({record.asset_id}) from {record.category}.'
    if children:
        names = ', '.join(c.name for c in children[:10])
        message += (f' Warning: {len(children)} asset(s) were built for it and now have no '
                    f'parent: {names}.')
    return {'asset_id': record.asset_id, 'name': record.name}, message


@_safe
def transfer_asset(asset_id, category):
    """
    Move an asset to a different category.

    Removes the entry from its current .alist file and adds it to the target,
    keeping the id. Paths are not re-derived; update them afterwards if the new
    category has a different folder layout.

    :param str asset_id: Asset id or display name.
    :param str category: Target category name.
    :return: Response with the moved asset dict.
    :rtype: dict
    """

    record = _require_record(asset_id)
    target = _require_category(category)
    if target == record.category:
        raise ValueError(f'{record.name} is already in {target}.')

    source_registry = unified_registry.UnifiedAssetRegistry.load(record.category)
    entry = (source_registry.get_asset_entry(record.asset_id, skip_dialog=True)
             if source_registry else None)
    if entry is None:
        raise ValueError(f'{record.asset_id!r} is not in the {record.category} registry file.')

    target_registry = unified_registry.UnifiedAssetRegistry.load(target, create=True)
    if target_registry.get_asset_entry(record.asset_id, skip_dialog=True):
        raise ValueError(f'{target} already holds an asset with id {record.asset_id!r}.')

    entry.fields['category'] = target
    target_registry.add_asset_entry(entry)
    if not target_registry.save():
        raise ValueError(f'{target} could not be written, so nothing was moved.')

    # Both halves are checked. The version this replaces checked neither, so a failure here
    # left the same asset id in two categories - which the manager resolves by keeping
    # whichever it happened to load first, and mentioning it at debug level.
    source_registry.remove_asset_entry(record.asset_id)
    if not source_registry.save():
        _manager(force_reload=True)
        raise ValueError(
            f'{record.name} was written into {target}, but {record.category} could not be '
            f'written, so it is still listed there too. Two categories now claim the id '
            f'{record.asset_id!r}: take it out of {record.category} before anything reads '
            'the registry again.')

    moved = _manager(force_reload=True).get_record(record.asset_id)
    return (_record_to_dict(moved) if moved else None,
            f'Moved {record.name} from {record.category} to {target}. '
            'Paths were not re-derived; check them if the folder layout differs.')
