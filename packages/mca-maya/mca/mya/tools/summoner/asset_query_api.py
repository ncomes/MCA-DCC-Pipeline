"""
Asset Query API for Summoner

Provides asset discovery and search functions for the AI dispatcher.
"""

from mca.common.assetlist import get_asset_manager

# Module-level cache removed - we now get fresh references to avoid stale data


def find_asset_by_name(name, category=None, fuzzy=True):
    """
    Find an asset by name with optional fuzzy matching.

    :param str name: Asset name or partial name
    :param str category: Optional category filter
    :param bool fuzzy: Enable fuzzy matching (ignored for now - uses exact match)
    :return: Asset entry if found, None otherwise
    :rtype: AssetEntry or None
    """
    # Get fresh manager reference
    manager = get_asset_manager()

    # Try exact name match first (case-insensitive)
    record = manager.get_record_by_name(name)
    if record and (not category or record.category == category):
        return record

    # If no exact match and fuzzy enabled, try partial match
    if fuzzy:
        name_lower = name.lower()
        for asset in manager.iter_all():
            # Check category filter
            if category and asset.category != category:
                continue
            # Check partial name match
            if name_lower in asset.name.lower():
                return asset

    return None


def list_assets(category=None, sort_by='name'):
    """
    List all assets in a category or the entire registry.

    :param str category: Optional category filter
    :param str sort_by: Sort field (default: 'name')
    :return: List of asset entries
    :rtype: list
    """
    assets = []
    # Get fresh manager reference
    manager = get_asset_manager()

    for asset in manager.iter_all():
        if category and asset.category != category:
            continue
        assets.append(asset)

    # Sort by name
    if sort_by == 'name':
        assets.sort(key=lambda a: a.name)

    return assets


def search_assets(search_term, limit=20):
    """
    Search for assets matching a term.

    :param str search_term: Text to search for
    :param int limit: Maximum results
    :return: List of matching asset entries
    :rtype: list
    """
    search_lower = search_term.lower()
    matches = []
    # Get fresh manager reference
    manager = get_asset_manager()

    for asset in manager.iter_all():
        if search_lower in asset.name.lower():
            matches.append(asset)
            if len(matches) >= limit:
                break

    return matches


def get_asset_summary_for_ai(asset_id):
    """
    Get a concise summary of an asset for AI.

    :param str asset_id: Asset ID or name
    :return: Human-readable summary
    :rtype: str or None
    """
    # Get fresh manager reference
    manager = get_asset_manager()

    # Try to get by ID first
    asset = manager.get_record(asset_id)

    # If not found, try by name
    if not asset:
        asset = manager.get_record_by_name(asset_id)

    if asset:
        return f"{asset.name} ({asset.category})"

    return None


def get_assets_by_category_summary():
    """
    Get asset counts by category.

    :return: Dictionary of category names to counts
    :rtype: dict
    """
    counts = {}
    # Get fresh manager reference
    manager = get_asset_manager()

    for asset in manager.iter_all():
        category = asset.category
        counts[category] = counts.get(category, 0) + 1

    return counts


def parse_natural_import_query(query_text):
    """
    Parse a natural language import query into structured parameters.

    :param str query_text: Natural language query
    :return: Dictionary with asset_name, import_type, category
    :rtype: dict
    """
    import string

    # Strip punctuation and normalize
    normalized = query_text.lower().strip()
    # Remove punctuation from the string
    normalized = normalized.translate(str.maketrans('', '', string.punctuation))

    # Determine import type (check most specific patterns first!)
    import_type = 'rig'  # Default
    if 'full skeleton' in normalized or 'complete skeleton' in normalized:
        import_type = 'full_skeleton'
    elif 'skeletal mesh' in normalized or ' sk ' in normalized or normalized.endswith(' sk'):
        import_type = 'skeletal_mesh'
    elif 'static mesh' in normalized or ' sm ' in normalized or normalized.endswith(' sm'):
        import_type = 'static_mesh'

    # Determine category
    category = None
    if 'character' in normalized:
        category = 'Characters'
    elif 'prop' in normalized:
        category = 'Props'
    elif 'vehicle' in normalized:
        category = 'Vehicles'
    elif 'weapon' in normalized:
        category = 'Weapons'
    elif 'head' in normalized:
        category = 'Heads'

    # Extract asset name (remove common words)
    words_to_remove = [
        'import', 'load', 'bring', 'in', 'the', 'a', 'an',
        'rig', 'skeletal', 'mesh', 'static', 'full', 'skeleton',
        'sk', 'sm',  # Skeletal Mesh / Static Mesh abbreviations
        'character', 'prop', 'vehicle', 'weapon', 'head',
        'can', 'you', 'please', 'as', 'with', 'of', 'for'
    ]

    words = normalized.split()
    asset_words = [w for w in words if w not in words_to_remove]
    asset_name = ' '.join(asset_words) if asset_words else None

    return {
        'asset_name': asset_name,
        'import_type': import_type,
        'category': category
    }


__all__ = [
    'find_asset_by_name',
    'list_assets',
    'search_assets',
    'get_asset_summary_for_ai',
    'get_assets_by_category_summary',
    'parse_natural_import_query',
]
