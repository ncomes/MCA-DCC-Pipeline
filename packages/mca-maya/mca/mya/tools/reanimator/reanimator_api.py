"""
Reanimator API - Clean interface for animation retargeting and rig management.

This module provides a simplified API for AI agents and scripts to work with
animation retargeting between rigs and skeletons. It wraps the underlying
rig_utils functions with clearer naming and better error handling.

Main operations:
    - Bake animation from skeleton to rig
    - Bake animation from rig to skeleton
    - Retarget animation from different skeleton
    - Reload/reimport rig while preserving animation

Dependencies:
    - mca.mya.rigging.rig_utils (Core rigging utilities)
    - mca.mya.rigging.frag (FRAG rigging system)

Side effects:
    - Modifies animation in Maya scene
    - May create/delete Maya nodes
    - Logs all operations to MCA_LOGGER
"""

# System imports
import pymel.core as pm

# MCA imports
from mca.common import log
from mca.common.assetlist import get_asset_manager
from mca.mya.rigging import rig_utils, frag
from mca.mya.utils import dag

logger = log.MCA_LOGGER


# --- Helper Functions --------------------------------------------------------

def get_selected_rig_and_skeleton():
    """
    Get the first FRAG rig and skeleton root from current selection.

    Searches through selected nodes to find:
    - A FRAG rig (or FRAG flag component)
    - A skeleton root joint

    :return: Tuple of (frag_rig, skel_root) or (None, None) if not found.
    :rtype: tuple[FRAGRig or None, pm.nt.Joint or None]
    """
    selection = pm.selected()
    frag_rig = None
    skel_root = None

    for selected_node in selection:
        # Look for FRAG rig
        if not frag_rig:
            frag_rig = frag.get_frag_rig(selected_node)

        # Look for skeleton root
        if not skel_root and isinstance(selected_node, pm.nt.Joint):
            skel_root = dag.get_absolute_parent(selected_node, node_type=pm.nt.Joint, inclusive=True)

        # Stop when we have both
        if frag_rig and skel_root:
            break
    if not frag_rig:
        frag_rigs = frag.get_frag_rigs()
        if frag_rigs:
            frag_rig = frag_rigs[0]
        else:
            return None, None
    if not skel_root:
        all_joints = pm.ls(type=pm.nt.Joint)
        for joint in all_joints:
            skel_root = dag.get_absolute_parent(joint, node_type=pm.nt.Joint, inclusive=True)
            if not frag.get_frag_root(skel_root):
                break

    return frag_rig, skel_root


def get_selected_rigs():
    """
    Get all FRAG rigs from current selection.

    :return: List of FRAG rigs found in selection.
    :rtype: list[FRAGRig]
    """
    selection = pm.selected()
    if not selection:
        return []

    frag_rigs = []
    for node in selection:
        frag_rig = frag.get_frag_rig(node)
        if frag_rig:
            frag_rigs.append(frag_rig)

    return frag_rigs


# --- Main API Functions ------------------------------------------------------

def bake_to_rig(frag_rig=None, skel_root=None, start_frame=None, end_frame=None,
                append=False, motion_encode=False):
    """
    Bake animation from skeleton to rig.

    Transfers animation from a skeleton to a FRAG rig by constraining the rig
    to the skeleton and baking the result. This is the primary workflow for
    applying animation to a rig.

    :param FRAGRig frag_rig: Target rig. If None, uses first rig from selection.
    :param pm.nt.Joint skel_root: Source skeleton root. If None, uses first skeleton from selection.
    :param int start_frame: Start frame for baking. If None, uses animation range.
    :param int end_frame: End frame for baking. If None, uses animation range.
    :param bool append: If True, appends animation after existing animation on rig.
    :param bool motion_encode: If True, aligns root motion when appending.
    :return: Asset ID of the rig, or None if operation failed.
    :rtype: str or None

    Example:
        >>> # With selection:
        >>> # Select rig and skeleton in viewport
        >>> bake_to_rig()

        >>> # Or specify explicitly:
        >>> my_rig = frag.get_frag_rig('Frostwind:rig')
        >>> my_skel = pm.PyNode('imported_skeleton')
        >>> bake_to_rig(my_rig, my_skel)
    """
    # Get from selection if not provided
    if not frag_rig or not skel_root:
        selected_rig, selected_skel = get_selected_rig_and_skeleton()
        frag_rig = frag_rig or selected_rig
        skel_root = skel_root or selected_skel

    # Validate inputs
    if not frag_rig:
        logger.error("No FRAG rig found. Please select a rig or provide frag_rig parameter.")
        return None

    logger.info(f"Baking animation to rig: {frag_rig}")

    # Call underlying implementation
    asset_id = rig_utils.animate_rig_from_skeleton_cmd(
        frag_rig=frag_rig,
        skel_root=skel_root,
        start_frame=start_frame,
        end_frame=end_frame,
        append=append,
        motion_encode=motion_encode
    )

    if asset_id:
        logger.info(f"Successfully baked animation to rig {asset_id}")
    else:
        logger.warning("Bake to rig operation returned no asset ID")

    return asset_id


def bake_to_rig_from_different_skeleton(frag_rig=None, source_asset_name=None,
                                        skel_root=None, start_frame=None, end_frame=None,
                                        append=False, motion_encode=False):
    """
    Retarget animation from a different character's skeleton to a rig.

    This allows transferring animation from one character to another. For example,
    taking animation from a "Dragon" skeleton and applying it to a "Frostwind" rig.
    Uses the source character's skeleton file (.skel) for retargeting.

    :param FRAGRig frag_rig: Target rig. If None, uses first rig from selection.
    :param str source_asset_name: Name of source asset to get skeleton from.
        If None and skel_root not provided, will prompt user.
    :param pm.nt.Joint skel_root: Source skeleton with animation. If None, uses selection.
    :param int start_frame: Start frame for baking. If None, uses animation range.
    :param int end_frame: End frame for baking. If None, uses animation range.
    :param bool append: If True, appends animation after existing animation on rig.
    :param bool motion_encode: If True, aligns root motion when appending.
    :return: Asset ID of the rig, or None if operation failed.
    :rtype: str or None

    Example:
        >>> # Retarget Dragon animation to Frostwind rig:
        >>> my_rig = frag.get_frag_rig('Frostwind:rig')
        >>> bake_to_rig_from_different_skeleton(my_rig, source_asset_name='Dragon')
    """
    # Get from selection if not provided
    if not frag_rig or not skel_root:
        selected_rig, selected_skel = get_selected_rig_and_skeleton()
        frag_rig = frag_rig or selected_rig
        skel_root = skel_root or selected_skel

    # Validate rig
    if not frag_rig:
        logger.error("No FRAG rig found. Please select a rig or provide frag_rig parameter.")
        return None

    # Get skeleton path from source asset
    diff_skel_path = None
    if source_asset_name:
        asset_manager = get_asset_manager()
        source_asset = asset_manager.get_record_by_name(source_asset_name)
        if not source_asset:
            source_asset = asset_manager.get_record(source_asset_name)
        if not source_asset:
            logger.error(f"Source asset '{source_asset_name}' not found in registry.")
            return None
        diff_skel_path = source_asset.skel_path
        logger.info(f"Using skeleton from asset: {source_asset_name}")

    logger.info(f"Retargeting animation to rig: {frag_rig}")

    # Call underlying implementation with diff_skel_path
    asset_id = rig_utils.animate_rig_from_skeleton_cmd(
        frag_rig=frag_rig,
        skel_root=skel_root,
        start_frame=start_frame,
        end_frame=end_frame,
        append=append,
        motion_encode=motion_encode,
        diff_skel_path=diff_skel_path
    )

    if asset_id:
        logger.info(f"Successfully retargeted animation to rig {asset_id}")
    else:
        logger.warning("Retarget operation returned no asset ID")

    return asset_id


def bake_to_skeleton(frag_rig=None, start_frame=None, end_frame=None, set_to_zero=False):
    """
    Bake animation from rig to skeleton.

    Transfers animation from a FRAG rig to its skeleton. This is typically used
    for exporting animation or preparing for retargeting to another rig.
    Creates a clean skeleton with baked animation.

    :param FRAGRig frag_rig: Source rig. If None, uses first rig from selection.
    :param int start_frame: Start frame for baking. If None, uses animation range.
    :param int end_frame: End frame for baking. If None, uses animation range.
    :param bool set_to_zero: If True, shifts animation to start at frame 0.
    :return: Asset ID of the rig, or None if operation failed.
    :rtype: str or None

    Example:
        >>> # Select rig and bake to skeleton:
        >>> bake_to_skeleton()

        >>> # Or specify rig explicitly:
        >>> my_rig = frag.get_frag_rig('Frostwind:rig')
        >>> bake_to_skeleton(my_rig, set_to_zero=True)
    """
    # Get from selection if not provided
    if not frag_rig:
        selected_rigs = get_selected_rigs()
        if selected_rigs:
            frag_rig = selected_rigs[0]

    # Validate input
    if not frag_rig:
        logger.error("No FRAG rig found. Please select a rig or provide frag_rig parameter.")
        return None

    logger.info(f"Baking rig animation to skeleton: {frag_rig}")

    # Call underlying implementation
    asset_id = rig_utils.bake_skeleton_from_rig_cmd(
        start_frame=start_frame,
        end_frame=end_frame,
        set_to_zero=set_to_zero
    )

    if asset_id:
        logger.info(f"Successfully baked skeleton from rig {asset_id}")
    else:
        logger.warning("Bake to skeleton operation returned no asset ID")

    return asset_id


def transfer_animation_to_asset(target_asset_name,
                                    source_frag_rig=None,
                                    namespace=None,
                                    preserve_layers=True):
    """
    Transfer the animation from a rig in the current scene onto a freshly-imported asset.

    Workflow:
        1. Resolve the source rig (explicit arg, or selection, or first rig in scene).
        2. Look up the target asset in the MCA asset registry.
        3. Import the target rig through the Summoner pipeline (same import call used by
           ``rig_utils.import_asset``).
        4. Stage the source animation on an ``AnimatedCurvesComponent`` and push it onto the
           new rig's flags, preserving animation layers by default.

    The source rig keeps its original animation - curves are duplicated across, not moved.
    Source and target must share the same flag naming scheme (for example two variants of
    the standard humanoid biped rig); mismatched flag names will be silently skipped on the
    target side.

    :param str target_asset_name: Registry name of the asset to import (e.g. ``'Agent_Female'``).
    :param FRAGRig source_frag_rig: Rig supplying the animation.  If None, uses the first
        selected FRAGRig, or falls back to the first FRAGRig in the scene.
    :param str namespace: Optional namespace for the imported asset.  If None, the Summoner
        import picks a default based on the asset name.
    :param bool preserve_layers: If True (default), animation layers are preserved on the
        target rig.  If False, layers are flattened to a single merged curve per attribute.
    :return: The newly imported target FRAGRig with animation applied, or None on failure.
    :rtype: FRAGRig or None

    Example:
        >>> # Select the source rig in the viewport, then:
        >>> transfer_animation_to_asset('Agent_Female')

        >>> # Explicit source rig + custom namespace:
        >>> src = frag.get_frag_rigs()[0]
        >>> transfer_animation_to_asset('Agent_Female', source_frag_rig=src, namespace='agentF')
    """

    # Resolve the source rig - prefer explicit, fall back to selection, then scene scan.
    if not source_frag_rig:
        selected_rigs = get_selected_rigs()
        if selected_rigs:
            source_frag_rig = selected_rigs[0]
        else:
            scene_rigs = frag.get_frag_rigs()
            if scene_rigs:
                source_frag_rig = scene_rigs[0]

    if not source_frag_rig:
        logger.error('No source FRAG rig found.  Select a rig or pass source_frag_rig.')
        return None

    # Look up the target asset record up front so we can fail fast before touching the scene.
    asset_manager = get_asset_manager()
    target_asset = asset_manager.get_record_by_name(target_asset_name)
    if not target_asset:
        # Name lookup is the user-friendly path; fall through to asset_id as a secondary try.
        target_asset = asset_manager.get_record(target_asset_name)
    if not target_asset:
        logger.error(f"Target asset '{target_asset_name}' not found in the registry.")
        return None

    logger.info(f"Transferring animation from {source_frag_rig} to new asset '{target_asset.name}'")

    # Import the target rig via the standard Summoner pathway.  This handles namespace
    # allocation, FRAGRoot/FRAGRig construction, and material refresh for us.
    target_frag_root = rig_utils.import_asset(asset_id=target_asset.asset_id, ns=namespace)
    if not target_frag_root:
        logger.error(f"Failed to import target asset '{target_asset.name}'.")
        return None

    target_frag_rig = target_frag_root.get_rig()
    if not target_frag_rig:
        logger.error(f"Imported asset '{target_asset.name}' has no FRAGRig to receive animation.")
        return None

    # Move the curves across.  rig_utils.transfer_animation_curves_to_rig owns the
    # AnimatedCurvesComponent lifecycle (create -> store -> restore -> remove).
    rig_utils.transfer_animation_curves_to_rig(
        source_frag_rig=source_frag_rig,
        target_frag_rig=target_frag_rig,
        preserve_layers=preserve_layers
    )

    logger.info(f"Successfully transferred animation to '{target_asset.name}'.")
    return target_frag_rig


def reload_rig(frag_rig=None):
    """
    Reload/reimport a rig while preserving animation.

    This is useful when the rig has been updated in source files and you want
    to get the latest version without losing animation. The process:
    1. Bakes animation from rig to skeleton
    2. Deletes the old rig
    3. Re-imports the rig from source
    4. Restores animation from skeleton to new rig

    :param FRAGRig frag_rig: Rig to reload. If None, reloads all selected rigs.
    :return: List of asset IDs of reloaded rigs.
    :rtype: list[str]

    Example:
        >>> # Select one or more rigs and reload:
        >>> reload_rig()

        >>> # Or specify rig explicitly:
        >>> my_rig = frag.get_frag_rig('Frostwind:rig')
        >>> reload_rig(my_rig)
    """
    if frag_rig:
        # Single rig provided
        logger.info(f"Reloading rig: {frag_rig}")
        reloaded_rig = rig_utils.reload_rig(frag_rig)
        asset_id = reloaded_rig.get_asset_id(reloaded_rig) if reloaded_rig else None
        return [asset_id] if asset_id else []
    else:
        # Use selection
        logger.info("Reloading selected rigs")
        asset_ids = rig_utils.reload_rig_cmd()
        if asset_ids:
            logger.info(f"Successfully reloaded {len(asset_ids)} rig(s)")
        return asset_ids or []


# --- Module Exports ----------------------------------------------------------

__all__ = [
    'bake_to_rig',
    'bake_to_rig_from_different_skeleton',
    'bake_to_skeleton',
    'transfer_animation_to_asset',
    'reload_rig',
    'get_selected_rig_and_skeleton',
    'get_selected_rigs',
]
