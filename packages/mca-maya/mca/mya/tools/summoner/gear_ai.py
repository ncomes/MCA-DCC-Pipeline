"""
Exposes the gear system to AI: :mod:`mca.mya.tools.summoner.gear_api`.

Same arrangement as :mod:`mca.mya.tools.assetregister.assetlist_ai`, and it reuses that
module's generator so the two surfaces cannot drift:

- :func:`register_all` registers the functions with the in-Maya AI ``FunctionRegistry``
  (MCA Wizard / Orange Slice).
- :func:`generate_mcp_tools` writes one typed wrapper file per function into ``mcp_tools/``
  for the MCAMayaMCP server (add that folder with ``--tool-dir``). Regenerate after changing
  the spec::

    cd packages
    python -c "import sys; sys.path[:0]=['mca-common','mca-maya']; from mca.mya.tools.summoner import gear_ai; gear_ai.generate_mcp_tools()"

Unlike the asset list these are Maya-only: every one of them reads or changes the open scene.

Requires: nothing at import time (the API module is imported inside the generated wrappers).
Side effects: :func:`generate_mcp_tools` overwrites the ``gear_*.py`` files in ``mcp_tools/``.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.mya.tools.assetregister import assetlist_ai

logger = log.MCA_LOGGER

API_MODULE = 'mca.mya.tools.summoner.gear_api'

# (tool name, module, function, confirm before running, {parameter: type}).
SPEC = [
    # Discovery: what is in the scene, and what could go on it.
    ('gear_list_characters', API_MODULE, 'list_characters', False, {}),
    ('gear_list', API_MODULE, 'list_gear', False,
     {'character': 'str', 'category': 'str', 'limit': 'int'}),
    ('gear_list_equipped', API_MODULE, 'list_equipped', False, {'character': 'str'}),
    # Scene changes.
    ('gear_equip', API_MODULE, 'equip', True,
     {'asset_id': 'str', 'character': 'str', 'replace': 'bool'}),
    ('gear_unequip', API_MODULE, 'unequip', True,
     {'asset_id': 'str', 'slot': 'str', 'character': 'str'}),
    ('gear_clear_slot', API_MODULE, 'clear_slot', True, {'slot': 'str', 'character': 'str'}),
]

MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_tools')

# Tools that only read the scene.
_NO_SCENE_CHANGES = {'gear_list_characters', 'gear_list', 'gear_list_equipped'}

_SCENE_NOTE = (' Changes the open Maya scene: imports geometry, merges joints onto the '
               'character skeleton and rewrites skin clusters. Undoable as one step.')


def register_all():
    """
    Register every gear function with the in-Maya AI FunctionRegistry.

    :return: Number of functions registered.
    :rtype: int
    """

    return assetlist_ai.register_all(SPEC)


def generate_mcp_tools(out_dir=MCP_DIR):
    """
    Write one MCP wrapper file per gear function (and remove stale ``gear_*.py`` files).

    :param str out_dir: Folder to write into.
    :return: Paths written.
    :rtype: list[str]
    """

    return assetlist_ai.generate_mcp_tools(out_dir=out_dir, spec=SPEC, prefix='gear_',
                                           no_side_effects=_NO_SCENE_CHANGES,
                                           side_effect_note=_SCENE_NOTE)
