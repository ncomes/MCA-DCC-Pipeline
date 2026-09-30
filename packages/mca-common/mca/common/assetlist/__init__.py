"""
The asset registry: what the project's assets are, and where each one's files live.

Being ported a layer at a time. What is here so far is the foundation - the framework's own
folder templates, a project's category file, and what every asset record has. The read layer
(``asset_manager``), the write layer (``unified_entry`` / ``unified_registry``) and the flat
API for scripts and MCP tools (``assetlist_api``) follow.

Import the module rather than its contents::

    from mca.common.assetlist import asset_paths

    categories = asset_paths.AssetDictData.load()
"""
