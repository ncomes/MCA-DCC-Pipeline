"""
Exposes the animation library to AI: the catalog API and the Maya operations.

Same arrangement as ``gear_ai`` and ``variant_ai``, and it reuses that
generator so the surfaces cannot drift:

- :func:`register_all` registers the functions with the in-Maya AI ``FunctionRegistry``.
- :func:`generate_mcp_tools` writes one typed wrapper per function into ``mcp_tools/``
  for the MCAMayaMCP server. Regenerate after changing the spec::

    cd packages
    python -c "import sys; sys.path[:0]=['mca-common','mca-maya']; from mca.mya.tools.animlibrary import animlib_ai; animlib_ai.generate_mcp_tools()"

The catalog half is DCC-agnostic and works outside Maya; the four Maya tools
need an open scene with a rig.

Requires: nothing at import time.
Side effects: :func:`generate_mcp_tools` overwrites the ``anim_*.py`` files in ``mcp_tools/``.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.mya.tools.assetregister import assetlist_ai

logger = log.MCA_LOGGER

CATALOG_MODULE = 'mca.common.animlib.animlib_api'
MAYA_MODULE = 'mca.mya.tools.animlibrary.animlib_maya'

# (tool name, module, function, confirm before running, {parameter: type}).
SPEC = [
    # Discovery: what is in the library at all.
    ('anim_describe_library', CATALOG_MODULE, 'describe_library', False, {}),
    ('anim_describe_schema', CATALOG_MODULE, 'describe_schema', False, {}),
    ('anim_list_characters', CATALOG_MODULE, 'list_characters', False, {}),
    ('anim_list_categories', CATALOG_MODULE, 'list_categories', False, {'character': 'str'}),
    # Queries.
    ('anim_list_clips', CATALOG_MODULE, 'list_clips', False,
     {'character': 'str', 'category': 'str', 'applicable_only': 'bool', 'clip_type': 'str',
      'limit': 'int'}),
    ('anim_search_clips', CATALOG_MODULE, 'search_clips', False,
     {'query': 'str', 'limit': 'int'}),
    ('anim_get_clip', CATALOG_MODULE, 'get_clip', False,
     {'clip_id': 'str', 'verbose': 'bool'}),
    ('anim_get_clip_files', CATALOG_MODULE, 'get_clip_files', False, {'clip_id': 'str'}),
    ('anim_check_library', CATALOG_MODULE, 'check_library', False, {}),
    ('anim_reload', CATALOG_MODULE, 'reload', False, {}),
    # Projects: which library root everything else reads.
    ('anim_list_projects', CATALOG_MODULE, 'list_projects', False, {}),
    ('anim_current_project', CATALOG_MODULE, 'current_project', False, {}),
    ('anim_add_project', CATALOG_MODULE, 'add_project', True,
     {'name': 'str', 'root': 'str', 'make_current': 'bool'}),
    ('anim_remove_project', CATALOG_MODULE, 'remove_project', True, {'name': 'str'}),
    ('anim_set_project', CATALOG_MODULE, 'set_current_project', True, {'name': 'str'}),
    # Folders.
    ('anim_list_folders', CATALOG_MODULE, 'list_folders', False, {'character': 'str'}),
    ('anim_create_folder', CATALOG_MODULE, 'create_folder', True,
     {'character': 'str', 'category': 'str'}),
    ('anim_remove_folder', CATALOG_MODULE, 'remove_folder', True,
     {'character': 'str', 'category': 'str', 'force': 'bool'}),
    # Catalog writes.
    ('anim_update_clip', CATALOG_MODULE, 'update_clip', True,
     {'clip_id': 'str', 'fields': 'dict'}),
    ('anim_remove_clip', CATALOG_MODULE, 'remove_clip', True,
     {'clip_id': 'str', 'delete_files': 'bool'}),
    # Scene operations.
    ('anim_list_scene_rigs', MAYA_MODULE, 'list_scene_rigs', False, {}),
    ('anim_apply_clip', MAYA_MODULE, 'apply_clip', True,
     {'clip_id': 'str', 'start_time': 'float', 'option': 'str', 'source_range': 'json',
      'selected_only': 'bool', 'namespace': 'str', 'mirror': 'bool', 'additive': 'bool',
      'amount': 'float'}),
    ('anim_capture_clip', MAYA_MODULE, 'capture_clip', True,
     {'name': 'str', 'category': 'str', 'character': 'str', 'frame_range': 'json',
      'tags': 'json', 'description': 'str', 'export_curves': 'bool', 'export_fbx': 'bool',
      'capture_preview': 'bool', 'capture_gif_preview': 'bool', 'clip_type': 'str',
      'selected_only': 'bool', 'namespace': 'str', 'replace': 'bool'}),
    ('anim_capture_pose', MAYA_MODULE, 'capture_pose', True,
     {'name': 'str', 'category': 'str', 'character': 'str', 'frame': 'float',
      'tags': 'json', 'description': 'str', 'selected_only': 'bool', 'namespace': 'str',
      'capture_preview': 'bool', 'replace': 'bool'}),
    ('anim_rebuild_fbx', MAYA_MODULE, 'rebuild_clip_fbx', True, {'clip_id': 'str'}),
    # Poses are placed, not keyed where they were captured, so they get their own
    # verb rather than sharing apply_clip's frame-shaped options.
    ('anim_apply_pose', MAYA_MODULE, 'apply_pose', True,
     {'clip_id': 'str', 'percent': 'float', 'namespace': 'str', 'selected_only': 'bool',
      'set_key': 'bool', 'mirror': 'bool', 'additive': 'bool'}),
    ('anim_calibrate_mirror', MAYA_MODULE, 'calibrate_mirror', True, {'namespace': 'str'}),
    ('anim_rebuild_gif', MAYA_MODULE, 'rebuild_clip_gif', True,
     {'clip_id': 'str', 'namespace': 'str'}),
    ('anim_backfill_gifs', MAYA_MODULE, 'backfill_gifs', True,
     {'character': 'str', 'namespace': 'str', 'replace': 'bool', 'limit': 'int'}),
]

MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_tools')

# Tools that only read.
_NO_SIDE_EFFECTS = {'anim_describe_library', 'anim_describe_schema', 'anim_list_characters',
                    'anim_list_categories', 'anim_list_clips', 'anim_search_clips',
                    'anim_get_clip', 'anim_get_clip_files', 'anim_check_library', 'anim_reload',
                    'anim_list_projects', 'anim_current_project', 'anim_list_folders',
                    'anim_list_scene_rigs'}

_SIDE_EFFECT_NOTE = (' Writes to the library catalog, and the scene operations also change '
                     'animation in the open Maya scene. Applying a clip never modifies the '
                     'clip file, so the same clip can be applied repeatedly.')


def register_all():
    """
    Register every library function with the in-Maya AI FunctionRegistry.

    :return: Number of functions registered.
    :rtype: int
    """

    return assetlist_ai.register_all(SPEC)


def generate_mcp_tools(out_dir=MCP_DIR):
    """
    Write one MCP wrapper file per library function (and remove stale ``anim_*.py`` files).

    :param str out_dir: Folder to write into.
    :return: Paths written.
    :rtype: list[str]
    """

    return assetlist_ai.generate_mcp_tools(out_dir=out_dir, spec=SPEC, prefix='anim_',
                                           no_side_effects=_NO_SIDE_EFFECTS,
                                           side_effect_note=_SIDE_EFFECT_NOTE)
