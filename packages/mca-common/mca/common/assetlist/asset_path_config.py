"""
The framework's own description of an asset's folders, read from
``asset_path_templates.yaml`` beside this file.

Read only, and nothing here knows about a project: what a project actually has lives in its
own ``asset_data.config``, which :mod:`asset_paths` reads and writes. This is the shape a new
one starts from.

Fifteen functions became four. The eleven that went - ``get_category_config``,
``get_all_categories``, ``get_gear_categories``, ``get_subcategories``,
``get_required_paths``, ``get_factions``, ``get_gear_names``, ``build_asset_list_dict``,
``build_all_asset_list_dicts`` among them - read the two blocks of that YAML file that
nothing ever asked for, and had no callers anywhere in the framework.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.textio import yamlio


logger = log.MCA_LOGGER

#: The file, which ships with the framework rather than with a project.
CONFIG_FILE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            'asset_path_templates.yaml'))

#: Read once. :func:`reload` is how a change to the file is picked up.
_CONFIG = None


def get_config():
    """
    :return: The whole file, read the first time it is asked for.
    :rtype: dict
    """

    global _CONFIG
    if _CONFIG is None:
        _CONFIG = _read()

    return _CONFIG


def reload():
    """
    Read the file again.

    :return: What it says now.
    :rtype: dict
    """

    global _CONFIG
    _CONFIG = _read()

    return _CONFIG


def _read():
    """
    :return: The file, or ``{}`` when it cannot be read - which is a broken install, so it is
        said out loud, but it does not raise: a DCC must still start.
    :rtype: dict
    """

    if not os.path.isfile(CONFIG_FILE):
        logger.error('The asset path templates are missing from the framework: %s', CONFIG_FILE)
        return {}

    config = yamlio.read_yaml_file(CONFIG_FILE)
    if not isinstance(config, dict):
        logger.error('The asset path templates could not be read: %s', CONFIG_FILE)
        return {}

    return config


def folder_names():
    """
    :return: What the folders inside an asset are called, by role - ``source``, ``rigs``,
        ``models``, ``animations``, ``textures``, ``flags``.
    :rtype: dict
    """

    return dict(get_config().get('folder_names') or {})


def default_paths():
    """
    :return: ``{'required': {KEY: folder}, 'optional': {...}}`` - the folders every asset has
        unless its category says otherwise.
    :rtype: dict
    """

    paths = get_config().get('default_paths') or {}

    return {'required': dict(paths.get('required') or {}),
            'optional': dict(paths.get('optional') or {})}


def required_paths():
    """
    :return: Just the required folders, which is what a category block is seeded with.
    :rtype: dict
    """

    return default_paths()['required']


def seed_categories():
    """
    The categories a project starts with.

    :return: Category name to ``{'subcategories': [...], 'is_gear': bool, 'gear_root': str}``.
    :rtype: dict
    """

    categories = get_config().get('categories') or {}
    seeded = {}
    for name, block in categories.items():
        block = block or {}
        seeded[name] = {
            'subcategories': list(block.get('subcategories') or []),
            'is_gear': bool(block.get('is_gear', False)),
            'gear_root': str(block.get('gear_root') or ''),
        }

    return seeded
