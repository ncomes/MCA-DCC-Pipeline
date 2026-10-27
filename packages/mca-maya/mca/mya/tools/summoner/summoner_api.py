"""
Summoner Public API

Clean, AI-accessible API for importing and exporting game assets.

This module provides a simplified interface to Summoner's core functionality,
designed for programmatic access by scripts, tools, and AI agents.

Example Usage:
    from mca.mya.tools.summoner.summoner_api import import_asset, export_asset

    # Import a character rig
    import_asset('Frostwind', import_mode='rig')

    # Import just the skeletal mesh
    import_asset('DragonEnemy', import_mode='skeletal_mesh')

    # Export with skinning
    export_asset(node, asset_entry, update_skinning=True)
"""

from mca.common import log
from mca.common.assetlist import get_asset_manager
from mca.mya.tools.summoner import summoner_utils
from mca.mya.rigging import rig_utils, skel_utils

logger = log.MCA_LOGGER
# Module-level cache removed - we now get fresh references to avoid stale data


__all__ = [
    'import_asset',
    'import_rig',
    'import_static_mesh',
    'import_skeletal_mesh',
    'import_full_skeleton',
    'export_asset',
    'create_organization_group',
    'get_organization_group',
    'get_all_organization_groups',
    'find_asset_by_name',
]


def find_asset_by_name(asset_name):
    """
    Find an asset entry in the registry by name.

    :param str asset_name: Name of the asset to find
    :return: Asset entry if found, None otherwise
    :rtype: AssetEntry or None

    Example:
        asset = find_asset_by_name('Frostwind')
        if asset:
            print(f"Found: {asset.name} ({asset.category})")
    """
    # Use AssetManager's built-in name lookup (case-insensitive)
    # Get fresh manager reference to avoid stale data
    return get_asset_manager().get_record_by_name(asset_name)


def import_asset(asset_name, import_mode='rig', namespace=None):
    """
    Import an asset from the registry by name.

    This is the main entry point for importing assets. Automatically looks up
    the asset in the registry and imports based on the specified mode.

    :param str asset_name: Name of the asset in the registry (e.g., 'Frostwind')
    :param str import_mode: Import mode - 'rig', 'skeletal_mesh', 'static_mesh', or 'full_skeleton'
    :param str namespace: Optional namespace for the imported asset. If None, uses asset name.
    :return: True if import successful
    :rtype: bool

    Example:
        # Import character rig
        import_asset('Frostwind', import_mode='rig')

        # Import just skeletal mesh
        import_asset('DragonProp', import_mode='skeletal_mesh')

        # Import with custom namespace
        import_asset('PlayerCharacter', import_mode='rig', namespace='Player01')
    """
    asset_entry = find_asset_by_name(asset_name)
    if not asset_entry:
        logger.error(f"Asset '{asset_name}' not found in registry")
        return False

    if import_mode == 'rig':
        return import_rig(asset_entry, namespace=namespace)
    elif import_mode == 'skeletal_mesh':
        return import_skeletal_mesh(asset_entry, namespace=namespace)
    elif import_mode == 'static_mesh':
        return import_static_mesh(asset_entry, namespace=namespace)
    elif import_mode == 'full_skeleton':
        return import_full_skeleton(asset_entry, namespace=namespace)
    else:
        logger.error(f"Unknown import mode: {import_mode}")
        return False


def import_rig(asset_entry, namespace=None):
    """
    Import an asset's rig (Maya .ma rig file with controls).

    This imports the actual Maya rig file, not the FBX.

    :param AssetEntry asset_entry: Asset entry from the registry
    :param str namespace: Optional namespace. If None, uses asset name.
    :return: True if import successful
    :rtype: bool

    Example:
        asset = find_asset_by_name('Frostwind')
        import_rig(asset)
    """
    try:
        # Import the Maya .ma rig file (not FBX)
        frag_root = rig_utils.import_asset(
            asset_id=asset_entry.asset_id,
            ns=namespace
        )

        if frag_root:
            logger.info(f"Successfully imported rig: {asset_entry.name}")
            return True
        else:
            logger.error(f"Failed to import rig {asset_entry.name}: No rig file found")
            return False
    except Exception as e:
        logger.error(f"Failed to import rig {asset_entry.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def import_skeletal_mesh(asset_entry, namespace=None):
    """
    Import only the skeletal mesh (no rig controls).

    :param AssetEntry asset_entry: Asset entry from the registry
    :param str namespace: Optional namespace. If None, uses asset name.
    :return: True if import successful
    :rtype: bool

    Example:
        asset = find_asset_by_name('Dragon')
        import_skeletal_mesh(asset)
    """
    try:
        # Import with skeleton (as_model=False keeps joints)
        result = summoner_utils.import_asset(
            asset_entry=asset_entry,
            as_model=False
        )

        if result is None:
            logger.error(f"Failed to import skeletal mesh {asset_entry.name}: import_asset returned None")
            return False

        org_grp, skel_root_dict = result

        # Handle namespace renaming if requested
        if namespace and namespace != asset_entry.name:
            import pymel.core as pm
            org_grp.rename(namespace)

        logger.info(f"Successfully imported skeletal mesh: {asset_entry.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to import skeletal mesh {asset_entry.name}: {e}")
        return False


def import_static_mesh(asset_entry, namespace=None):
    """
    Import only the static mesh (no skeleton or rig).

    :param AssetEntry asset_entry: Asset entry from the registry
    :param str namespace: Optional namespace. If None, uses asset name.
    :return: True if import successful
    :rtype: bool

    Example:
        asset = find_asset_by_name('RockProp')
        import_static_mesh(asset)
    """
    try:
        # Import without skeleton (as_model=True deletes joints)
        org_grp, skel_root_dict = summoner_utils.import_asset(
            asset_entry=asset_entry,
            as_model=True
        )

        # Handle namespace renaming if requested
        if namespace and namespace != asset_entry.name:
            import pymel.core as pm
            org_grp.rename(namespace)

        logger.info(f"Successfully imported static mesh: {asset_entry.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to import static mesh {asset_entry.name}: {e}")
        return False


def import_full_skeleton(asset_entry, namespace=None):
    """
    Import the full skeleton with all joints (skeletal mesh + merged .skl joints).

    This imports the SK (skeletal mesh FBX with subset of joints) and then merges
    additional joints from the .skl file to create the complete skeleton.

    :param AssetEntry asset_entry: Asset entry from the registry
    :param str namespace: Optional namespace. If None, uses asset name.
    :return: True if import successful
    :rtype: bool

    Example:
        asset = find_asset_by_name('Humanoid')
        import_full_skeleton(asset)
    """
    try:
        # Import SK with skeleton (as_model=False keeps joints)
        org_grp, skel_root_dict = summoner_utils.import_asset(
            asset_entry=asset_entry,
            as_model=False
        )

        # Merge additional joints from .skl file to create full skeleton
        bind_root = skel_root_dict.get(asset_entry.skel_path)
        if not bind_root:
            bind_root = skel_root_dict.get('default')

        if bind_root and asset_entry.skel_path:
            skel_utils.import_merge_skeleton(asset_entry.skel_path, bind_root)
            logger.info(f"Merged skeleton from .skl file for: {asset_entry.name}")

        # Handle namespace renaming if requested
        if namespace and namespace != asset_entry.name:
            import pymel.core as pm
            org_grp.rename(namespace)

        logger.info(f"Successfully imported full skeleton: {asset_entry.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to import full skeleton {asset_entry.name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def export_asset(node, asset_entry, update_skinning=False, save_source=False, export_skeleton=False):
    """
    Export an asset (SM/SK) from the scene with optional skinning and skeleton export.

    The node must be part of an organization group (created via create_organization_group).

    :param Transform node: A transform node in the export hierarchy
    :param AssetEntry asset_entry: Asset entry from the registry
    :param bool update_skinning: If True, export and update .skn skinning file
    :param bool save_source: If True, save the Maya source .ma file
    :param bool export_skeleton: If True, export and update .skel skeleton file
    :return: True if export successful
    :rtype: bool

    Example:
        import pymel.core as pm
        asset = find_asset_by_name('MyCharacter')
        node = pm.PyNode('MyCharacter_org_grp')
        export_asset(node, asset, update_skinning=True, save_source=True)
    """
    try:
        summoner_utils.export_asset(
            node=node,
            asset_entry=asset_entry,
            update_skn=update_skinning,
            save_source=save_source,
            full_skeleton=export_skeleton
        )
        logger.info(f"Successfully exported asset: {asset_entry.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to export asset {asset_entry.name}: {e}")
        return False


def create_organization_group(asset_entry, delete_existing=False):
    """
    Create an organization group for managing asset export.

    Organization groups help organize assets in the scene for export workflows.
    They use custom attributes to track which asset registry entry they belong to.

    :param AssetEntry asset_entry: Asset entry from the registry
    :param bool delete_existing: If True, delete any existing org group for this asset first
    :return: The created organization group transform node
    :rtype: pm.nt.Transform

    Example:
        asset = find_asset_by_name('Frostwind')
        org_grp = create_organization_group(asset)
        # Parent your asset geometry under org_grp
    """
    return summoner_utils.create_asset_org_grp(
        asset_entry=asset_entry,
        attr_name='modelshop',  # Keep for backward compatibility
        delete_exiting=delete_existing
    )


def get_organization_group(asset_entry):
    """
    Get the existing organization group for an asset, if it exists.

    :param AssetEntry asset_entry: Asset entry from the registry
    :return: Organization group if found, None otherwise
    :rtype: pm.nt.Transform or None

    Example:
        asset = find_asset_by_name('Frostwind')
        org_grp = get_organization_group(asset)
        if org_grp:
            print(f"Found org group: {org_grp}")
    """
    return summoner_utils.get_org_group(
        asset_entry=asset_entry,
        attr_name='modelshop'  # Keep for backward compatibility
    )


def get_all_organization_groups():
    """
    Get all organization groups in the current scene.

    :return: List of all organization group transform nodes
    :rtype: list of pm.nt.Transform

    Example:
        org_groups = get_all_organization_groups()
        print(f"Found {len(org_groups)} organization groups")
    """
    return summoner_utils.get_all_org_groups(
        attr_name='modelshop'  # Keep for backward compatibility
    )
