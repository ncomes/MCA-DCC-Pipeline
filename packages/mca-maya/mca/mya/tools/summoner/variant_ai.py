"""
Exposes the variant system to AI: :mod:`mca.mya.tools.summoner.variant_api`.

Mirrors :mod:`gear_ai`, and reuses the same generator so the surfaces cannot drift:

- :func:`register_all` registers the functions with the in-Maya AI ``FunctionRegistry``.
- :func:`generate_mcp_tools` writes one typed wrapper file per function into ``mcp_tools/``
  for the MCAMayaMCP server. Regenerate after changing the spec::

    cd packages
    python -c "import sys; sys.path[:0]=['mca-common','mca-maya']; from mca.mya.tools.summoner import variant_ai; variant_ai.generate_mcp_tools()"

Requires: nothing at import time.
Side effects: :func:`generate_mcp_tools` overwrites the ``variant_*.py`` files in ``mcp_tools/``.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.mya.tools.assetregister import assetlist_ai

logger = log.MCA_LOGGER

API_MODULE = 'mca.mya.tools.summoner.variant_api'

# (tool name, module, function, confirm before running, {parameter: type}).
SPEC = [
    ('variant_list', API_MODULE, 'list_variants', False, {'character': 'str'}),
    ('variant_current', API_MODULE, 'current_variant', False, {'character': 'str'}),
    ('variant_apply', API_MODULE, 'apply_variant', True,
     {'asset_id': 'str', 'character': 'str'}),
    ('variant_revert', API_MODULE, 'revert_variant', True, {'character': 'str'}),
]

MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_tools')

_NO_SCENE_CHANGES = {'variant_list', 'variant_current'}

_SCENE_NOTE = (' Changes the open Maya scene: deletes the character body that was there, '
               'imports the new one and rebinds it to the existing skeleton. Equipped gear '
               'is unaffected. Not undoable - call variant_revert to go back.')


def register_all():
    """
    Register every variant function with the in-Maya AI FunctionRegistry.

    :return: Number of functions registered.
    :rtype: int
    """

    return assetlist_ai.register_all(SPEC)


def generate_mcp_tools(out_dir=MCP_DIR):
    """
    Write one MCP wrapper file per variant function (and remove stale ``variant_*.py`` files).

    :param str out_dir: Folder to write into.
    :return: Paths written.
    :rtype: list[str]
    """

    return assetlist_ai.generate_mcp_tools(out_dir=out_dir, spec=SPEC, prefix='variant_',
                                           no_side_effects=_NO_SCENE_CHANGES,
                                           side_effect_note=_SCENE_NOTE)
