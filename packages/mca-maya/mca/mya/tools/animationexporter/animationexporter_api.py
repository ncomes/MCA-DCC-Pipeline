"""
Animation Exporter API - Clean interface for AI agents and tools.

This module provides a clean, user-friendly API for exporting animations from Maya rigs.
All functions are designed to work with Maya selection by default, making them easy to
call from AI agents, scripts, or other tools without requiring explicit parameters.

Key Features:
    - Selection-based defaults (no required parameters)
    - Fuzzy sequence name matching
    - Comprehensive error handling
    - Support for batch operations
    - MetaHuman face animation support

Dependencies:
    - Requires Maya with pymel
    - Requires FRAG rig system
    - Uses mca.common and mca.mya utilities

Example Usage:
    # Export animation for selected rig
    export_animation()

    # Export all animations for selected rigs
    export_all_animations()

    # Add a new sequence
    add_sequence(name="walk_cycle", frame_range=[0, 30])

    # List all sequences
    sequences = list_sequences()

Author: MCA Team
Date: 2025-01-28
"""

# Python imports
import os
import difflib

# Software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log
from mca.common.assetlist.asset_prefixes import ANIM as ANIM_PREFIX
from mca.common.paths import path_utils
from mca.mya.rigging import frag
from mca.mya.animation import time_utils
from mca.mya.tools.animationexporter import animationexporter_utils as ae_utils

logger = log.MCA_LOGGER


# ============================================================================
# EXPORT OPERATIONS
# ============================================================================

def export_animation(rig=None, sequence_name=None, sequence_path=None, frame_range=None,
                     start_at_zero=True, root_to_origin=True):
    """
    Export a single animation sequence to FBX.

    This is the main export function for single animations. It can export by sequence
    name or path, and defaults to exporting the first sequence found for the selected rig.

    :param FRAGRig rig: The FRAG rig to export. If None, uses selected rig.
    :param str sequence_name: Name of the sequence to export (supports fuzzy matching).
    :param str sequence_path: Full path to sequence. Takes priority over sequence_name.
    :param list frame_range: [start_frame, end_frame]. If None, uses sequence's stored range.
    :param bool start_at_zero: Whether to shift animation to start at frame 0.
    :param bool root_to_origin: Whether to move root to origin during export.
    :return: The exported file path on success, None on failure.
    :rtype: str or None

    Example:
        # Export animation for selected rig (first sequence)
        export_animation()

        # Export specific sequence by name
        export_animation(sequence_name="walk_cycle")

        # Export with custom frame range
        export_animation(sequence_name="idle", frame_range=[10, 50])
    """
    # Get rig from selection if not provided
    if rig is None:
        rig = get_selected_rig()
        if not rig:
            logger.error("No rig provided and no FRAG rig found in selection.")
            return None

    # Validate rig exists in scene
    if not pm.objExists(rig.pynode):
        logger.error(f"Rig no longer exists in scene: {rig}")
        return None

    # Get all sequences for this rig (get_sequences() uses .pynode as keys)
    all_sequences = ae_utils.get_sequences()
    rig_sequences = all_sequences.get(rig.pynode, {})

    if not rig_sequences:
        logger.warning(f"No sequences registered for rig: {rig}")
        return None

    # Find the sequence to export
    target_sequence = None
    target_path = None

    if sequence_path:
        # User provided explicit path
        target_path = path_utils.to_relative_path(sequence_path)
        target_sequence = rig_sequences.get(target_path)
    elif sequence_name:
        # User provided sequence name - try to find it
        target_sequence, target_path = find_sequence_by_name(sequence_name, rig=rig, fuzzy=True)
    else:
        # No sequence specified - export first one
        if rig_sequences:
            target_path = list(rig_sequences.keys())[0]
            target_sequence = rig_sequences[target_path]
            logger.info(f"No sequence specified, exporting first sequence: {target_path}")

    if not target_sequence or not target_path:
        logger.error(f"Could not find sequence to export for rig {rig}")
        return None

    # Build list of sequences to skip (all except target)
    sequences_to_skip = [path for path in rig_sequences.keys() if path != target_path]

    logger.info(f"Exporting animation: {target_path}")

    # Export using existing utility function
    try:
        ae_utils.export_frag_sequences_cmd(frag_rig_list=[rig], sequences_to_skip=sequences_to_skip)
        export_path = path_utils.to_full_path(target_path)
        logger.info(f"Animation exported successfully: {export_path}")
        return export_path
    except Exception as e:
        logger.error(f"Failed to export animation: {e}")
        return None


def export_all_animations(rigs=None, skip_sequences=None):
    """
    Export all registered animation sequences for specified rigs.

    This function performs a batch export of all sequences. It's useful for
    exporting an entire character's animation library at once.

    :param list rigs: List of FRAG rigs to export. If None, uses selected rigs.
    :param list skip_sequences: List of sequence paths/names to skip during export.
    :return: Number of sequences exported on success, None on failure.
    :rtype: int or None

    Example:
        # Export all animations for selected rigs
        export_all_animations()

        # Export all except specific sequences
        export_all_animations(skip_sequences=["test_anim", "old_walk"])
    """
    # Get rigs from selection if not provided
    if rigs is None:
        rigs = get_selected_rigs()
        if not rigs:
            logger.error("No rigs provided and no FRAG rigs found in selection.")
            return None

    # Ensure rigs is a list
    if not isinstance(rigs, list):
        rigs = [rigs]

    # Validate all rigs exist
    valid_rigs = []
    for rig in rigs:
        if pm.objExists(rig.pynode):
            valid_rigs.append(rig)
        else:
            logger.warning(f"Rig no longer exists in scene, skipping: {rig}")

    if not valid_rigs:
        logger.error("No valid rigs to export.")
        return None

    # Process skip list - convert names to paths if needed
    sequences_to_skip = []
    if skip_sequences:
        all_sequences = ae_utils.get_sequences()
        for skip_item in skip_sequences:
            # Check if it's already a path
            if skip_item.endswith('.fbx'):
                sequences_to_skip.append(path_utils.to_relative_path(skip_item))
            else:
                # Try to find sequence by name
                for rig in valid_rigs:
                    # get_sequences() uses .pynode as keys
                    rig_sequences = all_sequences.get(rig.pynode, {})
                    found_seq, found_path = find_sequence_by_name(skip_item, rig=rig, fuzzy=True)
                    if found_path:
                        sequences_to_skip.append(found_path)

    # Count sequences before export
    all_sequences = ae_utils.get_sequences()
    # get_sequences() uses .pynode as keys
    total_sequences = sum(len(all_sequences.get(rig.pynode, {})) for rig in valid_rigs)
    export_count = total_sequences - len(sequences_to_skip)

    logger.info(f"Batch exporting {export_count} sequences from {len(valid_rigs)} rig(s)")

    # Export using existing utility function
    try:
        ae_utils.export_frag_sequences_cmd(frag_rig_list=valid_rigs, sequences_to_skip=sequences_to_skip)
        logger.info(f"Batch export completed: {export_count} sequences exported")
        return export_count
    except Exception as e:
        logger.error(f"Failed to batch export animations: {e}")
        return None


def export_selected_rig_animations():
    """
    Quick export all animations for selected rigs.

    This is a convenience function that combines rig selection and export in one call.
    Useful for quick operations from shelf buttons or hotkeys.

    :return: Number of sequences exported on success, None on failure.
    :rtype: int or None

    Example:
        # Select rig in Maya, then run
        export_selected_rig_animations()
    """
    logger.info("Quick export: Exporting all animations for selected rigs")
    return export_all_animations()


# ============================================================================
# SEQUENCE MANAGEMENT
# ============================================================================

def add_sequence(rig=None, name=None, output_path=None, frame_range=None,
                start_at_zero=True, root_to_origin=True, notes=None):
    """
    Register a new animation sequence for export.

    This function adds a sequence to the FRAG Sequencer system. The sequence will be
    remembered and can be batch exported later. Multiple sequences can be registered
    per rig to manage an entire animation library.

    :param FRAGRig rig: The FRAG rig this sequence belongs to. If None, uses selected rig.
    :param str name: Name of the sequence (e.g. "walk_cycle"). Used to generate path if output_path not provided.
    :param str output_path: Full output path for FBX file. If None, auto-generates from name and rig.
    :param list frame_range: [start_frame, end_frame]. If None, uses current timeline range.
    :param bool start_at_zero: Whether animation should start at frame 0 when exported.
    :param bool root_to_origin: Whether root should be moved to origin when exported.
    :param str notes: Optional notes about this sequence.
    :return: The AnimSequence wrapper for the new sequence, None on failure.
    :rtype: AnimSequence or None

    Example:
        # Add sequence with current timeline range
        add_sequence(name="walk_cycle")

        # Add sequence with specific frame range
        add_sequence(name="idle", frame_range=[0, 120], notes="Default idle animation")

        # Add sequence with custom output path
        add_sequence(name="jump", output_path="//project/animations/character_jump.fbx")
    """
    # Get rig from selection if not provided
    if rig is None:
        rig = get_selected_rig()
        if not rig:
            logger.error("No rig provided and no FRAG rig found in selection.")
            return None

    # Validate rig exists
    if not pm.objExists(rig.pynode):
        logger.error(f"Rig no longer exists in scene: {rig}")
        return None

    # Get frame range from timeline if not provided
    if frame_range is None:
        frame_range = get_current_frame_range()
        logger.info(f"Using current timeline range: {frame_range}")

    # Generate output path if not provided
    if output_path is None:
        if name is None:
            logger.error("Either 'name' or 'output_path' must be provided")
            return None

        # Get asset info to build proper path
        from mca.common.assetlist import get_asset_manager
        manager = get_asset_manager()
        asset_id = rig.get_asset_id(rig)
        mca_asset = manager.get_record(asset_id)

        if mca_asset and mca_asset.animations_path:
            # Use asset's animation path
            animations_dir = path_utils.to_relative_path(mca_asset.animations_path)
            output_path = os.path.join(animations_dir, f"{name}.fbx")
        else:
            logger.error(f"Could not determine animation path for asset: {asset_id}")
            return None
    else:
        # Ensure path is relative and has .fbx extension
        output_path = path_utils.to_relative_path(output_path)
        if not output_path.lower().endswith('.fbx'):
            output_path += '.fbx'

    logger.info(f"Adding sequence: {name or os.path.basename(output_path)} -> {output_path}")

    # Register sequence using existing utility function
    try:
        sequence_wrapper = ae_utils.set_sequence(
            sequence_path=output_path,
            frag_rig=rig,
            frame_range=frame_range,
            start_at_zero=start_at_zero,
            root_to_origin=root_to_origin,
            sequence_notes=notes or ""
        )
        logger.info(f"Sequence registered successfully: {output_path}")
        return sequence_wrapper
    except Exception as e:
        logger.error(f"Failed to add sequence: {e}")
        return None


def update_sequence(rig=None, sequence_name=None, sequence_path=None, **kwargs):
    """
    Update an existing sequence's properties.

    This function allows modifying sequence properties like frame range, export options,
    or notes without recreating the sequence.

    :param FRAGRig rig: The FRAG rig owning the sequence. If None, uses selected rig.
    :param str sequence_name: Name of sequence to update (supports fuzzy matching).
    :param str sequence_path: Path of sequence to update. Takes priority over sequence_name.
    :param kwargs: Properties to update (frame_range, start_at_zero, root_to_origin, notes).
    :return: Updated AnimSequence wrapper on success, None on failure.
    :rtype: AnimSequence or None

    Example:
        # Update frame range
        update_sequence(sequence_name="walk", frame_range=[5, 35])

        # Update export options
        update_sequence(sequence_name="idle", start_at_zero=False, notes="Updated range")
    """
    # Get rig from selection if not provided
    if rig is None:
        rig = get_selected_rig()
        if not rig:
            logger.error("No rig provided and no FRAG rig found in selection.")
            return None

    # Find the sequence
    target_sequence = None
    target_path = None

    if sequence_path:
        # User provided explicit path
        target_path = path_utils.to_relative_path(sequence_path)
        all_sequences = ae_utils.get_sequences()
        # get_sequences() uses .pynode as keys
        rig_sequences = all_sequences.get(rig.pynode, {})
        target_sequence = rig_sequences.get(target_path)
    elif sequence_name:
        # User provided name - find it
        target_sequence, target_path = find_sequence_by_name(sequence_name, rig=rig, fuzzy=True)
    else:
        logger.error("Either 'sequence_name' or 'sequence_path' must be provided")
        return None

    if not target_sequence:
        logger.error(f"Sequence not found: {sequence_name or sequence_path}")
        return None

    logger.info(f"Updating sequence: {target_path}")

    # Get current data and merge with updates
    current_data = target_sequence.get_data()

    # Apply updates from kwargs
    if 'frame_range' in kwargs:
        current_data['frame_range'] = kwargs['frame_range']
    if 'start_at_zero' in kwargs:
        current_data['start_at_zero'] = kwargs['start_at_zero']
    if 'root_to_origin' in kwargs:
        current_data['root_to_origin'] = kwargs['root_to_origin']
    if 'notes' in kwargs:
        current_data['sequence_notes'] = kwargs['notes']

    # Re-register the sequence with updated data
    try:
        sequence_wrapper = ae_utils.set_sequence(
            sequence_path=target_path,
            frag_rig=rig,
            frame_range=current_data['frame_range'],
            start_at_zero=current_data['start_at_zero'],
            root_to_origin=current_data['root_to_origin'],
            sequence_notes=current_data['sequence_notes']
        )
        logger.info(f"Sequence updated successfully: {target_path}")
        return sequence_wrapper
    except Exception as e:
        logger.error(f"Failed to update sequence: {e}")
        return None


def remove_sequence(rig=None, sequence_name=None, sequence_path=None):
    """
    Remove a sequence from the FRAG Sequencer.

    This unregisters the sequence from the export system. The FBX file on disk is not
    affected - only the sequence metadata is removed from the scene.

    :param FRAGRig rig: The FRAG rig owning the sequence. If None, uses selected rig.
    :param str sequence_name: Name of sequence to remove (supports fuzzy matching).
    :param str sequence_path: Path of sequence to remove. Takes priority over sequence_name.
    :return: True on success, False on failure.
    :rtype: bool

    Example:
        # Remove sequence by name
        remove_sequence(sequence_name="old_walk")

        # Remove sequence by path
        remove_sequence(sequence_path="//project/animations/test.fbx")
    """
    # Get rig from selection if not provided
    if rig is None:
        rig = get_selected_rig()
        if not rig:
            logger.error("No rig provided and no FRAG rig found in selection.")
            return False

    # Find the sequence
    target_path = None

    if sequence_path:
        # User provided explicit path
        target_path = path_utils.to_relative_path(sequence_path)
    elif sequence_name:
        # User provided name - find it
        target_sequence, target_path = find_sequence_by_name(sequence_name, rig=rig, fuzzy=True)
    else:
        logger.error("Either 'sequence_name' or 'sequence_path' must be provided")
        return False

    if not target_path:
        logger.error(f"Sequence not found: {sequence_name or sequence_path}")
        return False

    logger.info(f"Removing sequence: {target_path}")

    # Remove using existing utility function
    try:
        ae_utils.remove_sequence(target_path, rig)
        logger.info(f"Sequence removed successfully: {target_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to remove sequence: {e}")
        return False


# ============================================================================
# QUERY & DISCOVERY
# ============================================================================

def list_sequences(rig=None):
    """
    Get all registered animation sequences for a rig.

    This function returns sequence information in a clean, easy-to-read format
    suitable for displaying to users or AI agents.

    :param FRAGRig rig: The FRAG rig to query. If None, lists sequences for all rigs.
    :return: Dictionary of rig to list of sequence info dicts.
    :rtype: dict

    Example:
        # List all sequences in scene
        all_sequences = list_sequences()

        # List sequences for selected rig
        rig_sequences = list_sequences(rig=get_selected_rig())
    """
    all_sequences = ae_utils.get_sequences()

    result = {}

    if rig is None:
        # List sequences for all rigs (keys are PyNodes from get_sequences())
        for rig_pynode, sequence_dict in all_sequences.items():
            if not rig_pynode:
                continue
            rig_name = rig_pynode.name() if hasattr(rig_pynode, 'name') else str(rig_pynode)
            result[rig_name] = _format_sequence_list(sequence_dict)
    else:
        # List sequences for specific rig (get_sequences() uses .pynode as keys)
        sequence_dict = all_sequences.get(rig.pynode, {})
        rig_name = rig.name() if hasattr(rig, 'name') else str(rig)
        result[rig_name] = _format_sequence_list(sequence_dict)

    return result


def get_sequence_info(rig=None, sequence_name=None, sequence_path=None):
    """
    Get detailed information about a specific sequence.

    Returns all metadata for a sequence including frame range, export options,
    file path, and notes.

    :param FRAGRig rig: The FRAG rig owning the sequence. If None, uses selected rig.
    :param str sequence_name: Name of sequence to query (supports fuzzy matching).
    :param str sequence_path: Path of sequence to query. Takes priority over sequence_name.
    :return: Dictionary with sequence information, None if not found.
    :rtype: dict or None

    Example:
        # Get info for specific sequence
        info = get_sequence_info(sequence_name="walk_cycle")
        print(f"Frame range: {info['frame_range']}")
        print(f"Export path: {info['path']}")
    """
    # Get rig from selection if not provided
    if rig is None:
        rig = get_selected_rig()
        if not rig:
            logger.error("No rig provided and no FRAG rig found in selection.")
            return None

    # Find the sequence
    target_sequence = None
    target_path = None

    if sequence_path:
        # User provided explicit path
        target_path = path_utils.to_relative_path(sequence_path)
        all_sequences = ae_utils.get_sequences()
        # get_sequences() uses .pynode as keys
        rig_sequences = all_sequences.get(rig.pynode, {})
        target_sequence = rig_sequences.get(target_path)
    elif sequence_name:
        # User provided name - find it
        target_sequence, target_path = find_sequence_by_name(sequence_name, rig=rig, fuzzy=True)
    else:
        logger.error("Either 'sequence_name' or 'sequence_path' must be provided")
        return None

    if not target_sequence:
        logger.error(f"Sequence not found: {sequence_name or sequence_path}")
        return None

    # Format sequence information
    return {
        'name': target_sequence.name,
        'path': target_path,
        'full_path': path_utils.to_full_path(target_path),
        'frame_range': list(target_sequence.frame_range),
        'start_at_zero': target_sequence.start_at_zero,
        'root_to_origin': target_sequence.root_to_origin,
        'notes': target_sequence.sequence_notes,
        'rig': rig.name() if hasattr(rig, 'name') else str(rig)
    }


def find_sequence_by_name(name, rig=None, fuzzy=True):
    """
    Find a sequence by name with optional fuzzy matching.

    This function helps locate sequences when the exact name isn't known. It supports
    fuzzy matching using similarity scoring, useful for handling typos or partial names.

    :param str name: Sequence name to search for.
    :param FRAGRig rig: The FRAG rig to search within. If None, searches all rigs.
    :param bool fuzzy: Whether to use fuzzy matching (default True).
    :return: Tuple of (AnimSequence wrapper, sequence_path) or (None, None) if not found.
    :rtype: tuple

    Example:
        # Exact match
        seq, path = find_sequence_by_name("walk_cycle", fuzzy=False)

        # Fuzzy match - finds "walk_cycle" even if user typed "walk"
        seq, path = find_sequence_by_name("walk", fuzzy=True)
    """
    all_sequences = ae_utils.get_sequences()

    # Determine which rigs to search (get_sequences() uses .pynode as keys)
    rigs_to_search = []
    if rig is None:
        # Search all rigs - keys are already PyNodes
        rigs_to_search = list(all_sequences.keys())
    else:
        # Search specific rig - use .pynode for lookup
        rigs_to_search = [rig.pynode]

    # Search for exact match first
    name_lower = name.lower()
    for search_rig in rigs_to_search:
        if not search_rig:
            continue
        sequence_dict = all_sequences.get(search_rig, {})
        for seq_path, seq_wrapper in sequence_dict.items():
            seq_name = seq_wrapper.name.lower()
            if seq_name == name_lower:
                logger.info(f"Found exact match: {seq_name}")
                return seq_wrapper, seq_path

    # If fuzzy matching enabled, try similarity matching
    if fuzzy:
        best_match = None
        best_match_path = None
        best_ratio = 0.6  # Minimum similarity threshold

        for search_rig in rigs_to_search:
            if not search_rig:
                continue
            sequence_dict = all_sequences.get(search_rig, {})
            for seq_path, seq_wrapper in sequence_dict.items():
                seq_name = seq_wrapper.name.lower()
                # Calculate similarity ratio
                ratio = difflib.SequenceMatcher(None, name_lower, seq_name).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = seq_wrapper
                    best_match_path = seq_path

        if best_match:
            logger.info(f"Found fuzzy match: {best_match.name} (similarity: {best_ratio:.2f})")
            return best_match, best_match_path

    logger.warning(f"No sequence found matching: {name}")
    return None, None


# ============================================================================
# SELECTION HELPERS
# ============================================================================

def get_selected_rigs():
    """
    Get all FRAG rigs from the current Maya selection.

    This function examines the selection and extracts any FRAG rigs found,
    either directly selected or connected to selected objects.

    :return: List of FRAG rigs found in selection.
    :rtype: list

    Example:
        # Get rigs from selection
        rigs = get_selected_rigs()
        for rig in rigs:
            print(f"Found rig: {rig.name()}")
    """
    selection = pm.selected()
    if not selection:
        logger.debug("No objects selected")
        return []

    # Extract unique FRAG rigs from selection
    rig_set = set()
    for obj in selection:
        try:
            rig = frag.get_frag_rig(obj)
            if rig:
                rig_set.add(rig)
        except Exception as e:
            logger.debug(f"Could not get FRAG rig from {obj}: {e}")
            continue

    rig_list = list(rig_set)
    logger.info(f"Found {len(rig_list)} FRAG rig(s) in selection")
    return rig_list


def get_selected_rig():
    """
    Get a single FRAG rig from the current Maya selection.

    Convenience function for operations that work on one rig at a time.
    If multiple rigs are selected, returns the first one.

    :return: Single FRAG rig or None if no rig found.
    :rtype: FRAGRig or None

    Example:
        # Get single rig
        rig = get_selected_rig()
        if rig:
            print(f"Working with rig: {rig.name()}")
    """
    rigs = get_selected_rigs()
    if not rigs:
        return None

    if len(rigs) > 1:
        logger.warning(f"Multiple rigs selected ({len(rigs)}), using first: {rigs[0].name()}")

    return rigs[0]


def get_current_frame_range():
    """
    Get the current timeline frame range in Maya.

    Returns the playback start and end frames as configured in Maya's timeline.
    Useful for capturing the current animation range when adding sequences.

    :return: [start_frame, end_frame]
    :rtype: list

    Example:
        # Get current range
        frame_range = get_current_frame_range()
        print(f"Timeline: {frame_range[0]} to {frame_range[1]}")
    """
    start_frame = int(pm.playbackOptions(query=True, minTime=True))
    end_frame = int(pm.playbackOptions(query=True, maxTime=True))
    return [start_frame, end_frame]


def get_selected_rig_and_sequence():
    """
    Smart detection of rig and sequence from selection and timeline.

    This function tries to intelligently determine what the user wants to work with
    based on their selection and timeline bookmark. Useful for quick operations.

    :return: Tuple of (rig, sequence_name, frame_range) or (None, None, None).
    :rtype: tuple

    Example:
        # Detect context
        rig, seq_name, frame_range = get_selected_rig_and_sequence()
        if rig:
            print(f"Detected rig: {rig.name()}")
            print(f"Sequence: {seq_name}")
            print(f"Range: {frame_range}")
    """
    # Get rig from selection
    rig = get_selected_rig()
    if not rig:
        return None, None, None

    # Try to find active timeline bookmark
    sequence_name = None
    frame_range = get_current_frame_range()

    # Check if current timeline matches any registered sequence
    all_sequences = ae_utils.get_sequences()
    # get_sequences() uses .pynode as keys
    rig_sequences = all_sequences.get(rig.pynode, {})

    for seq_path, seq_wrapper in rig_sequences.items():
        seq_range = seq_wrapper.frame_range
        if seq_range[0] == frame_range[0] and seq_range[1] == frame_range[1]:
            # Timeline matches this sequence
            sequence_name = seq_wrapper.name
            logger.info(f"Detected active sequence from timeline: {sequence_name}")
            break

    return rig, sequence_name, frame_range


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _format_sequence_list(sequence_dict):
    """
    Format sequence dictionary into clean list of info dicts.

    Internal helper to convert raw sequence data into user-friendly format.

    :param dict sequence_dict: Dictionary of sequence paths to AnimSequence wrappers.
    :return: List of sequence info dictionaries.
    :rtype: list
    """
    result = []
    for seq_path, seq_wrapper in sequence_dict.items():
        result.append({
            'name': seq_wrapper.name,
            'path': seq_path,
            'frame_range': list(seq_wrapper.frame_range),
            'start_at_zero': seq_wrapper.start_at_zero,
            'root_to_origin': seq_wrapper.root_to_origin,
            'notes': seq_wrapper.sequence_notes
        })

    # Sort by UI index if available
    result.sort(key=lambda x: x.get('ui_index', 0))
    return result


# ============================================================================
# SMART EXPORT (AI-FRIENDLY)
# ============================================================================

def get_scene_rigs():
    """
    Get all FRAG rigs in the current Maya scene.

    This function wraps frag.get_frag_rigs() with additional info formatting
    for AI agents. Returns structured data about each rig including whether
    it has animation sequences registered.

    :return: List of rig info dicts with name, asset_id, has_sequences, and rig object.
    :rtype: list

    Example:
        # Get all rigs in scene
        rigs = get_scene_rigs()
        for rig_info in rigs:
            print(f"Rig: {rig_info['name']}, Has sequences: {rig_info['has_sequences']}")
    """
    # Use existing frag.get_frag_rigs() to find all rigs in scene
    all_rigs = frag.get_frag_rigs()

    if not all_rigs:
        logger.info("No FRAG rigs found in scene")
        return []

    # Get all sequences once for efficiency
    all_sequences = ae_utils.get_sequences()

    result = []
    for rig in all_rigs:
        if not rig:
            continue

        # Get rig name
        rig_name = rig.name() if hasattr(rig, 'name') else str(rig)

        # Get asset ID if available
        asset_id = None
        try:
            asset_id = rig.get_asset_id(rig) if hasattr(rig, 'get_asset_id') else None
        except Exception:
            pass

        # Check if rig has sequences (get_sequences() uses .pynode as keys)
        rig_sequences = all_sequences.get(rig.pynode, {})

        rig_info = {
            'name': rig_name,
            'asset_id': asset_id,
            'has_sequences': bool(rig_sequences),
            'sequence_count': len(rig_sequences),
            'rig': rig  # Include actual rig object for internal use
        }
        result.append(rig_info)

    logger.info(f"Found {len(result)} FRAG rig(s) in scene")
    return result


def _compute_export_path_from_scene(scene_path, sequence_name, rig):
    """
    Compute the export path for an animation based on scene location.

    Export path logic:
    1. If scene is in _Source/Animations/... → Export to same path minus _Source
       Example: .../Conduit/_Source/Animations/MainLocomotion/CD_Run_Fwd.ma
                → .../Conduit/Animations/MainLocomotion/ANIM_CD_Run_Fwd.fbx

    2. If scene is outside the codebase → Default to asset's Animations folder
       Example: C:/temp/test.ma → .../Conduit/Animations/ANIM_test.fbx

    :param str scene_path: Full path to the Maya scene file.
    :param str sequence_name: Name of the sequence (with ANIM_ prefix).
    :param FRAGRig rig: The FRAG rig (used to get asset path as fallback).
    :return: Full export path for the FBX file.
    :rtype: str or None
    """
    scene_path_str = str(scene_path).replace('\\', '/')
    scene_dir = os.path.dirname(scene_path_str)

    # Check if scene is in _Source/Animations structure
    # Look for pattern: .../_Source/Animations/...
    source_animations_marker = '_Source/Animations'

    if source_animations_marker in scene_dir:
        # Scene is in _Source/Animations - export to same structure minus _Source
        # Split at _Source and rebuild path
        parts = scene_dir.split('_Source/')
        if len(parts) == 2:
            base_path = parts[0]  # Everything before _Source/
            sub_path = parts[1]   # Animations/SubFolder/...

            # Build export path: base + sub_path (without _Source)
            export_dir = os.path.join(base_path, sub_path)
            export_path = os.path.join(export_dir, f"{sequence_name}.fbx")

            logger.info(f"Export path derived from scene location: {export_path}")
            return export_path

    # Scene is outside codebase or not in standard structure
    # Fall back to asset's Animations folder
    logger.info("Scene not in _Source/Animations structure, using asset's default Animations folder")

    try:
        from mca.common.assetlist import get_asset_manager
        manager = get_asset_manager()
        asset_id = rig.get_asset_id(rig)
        mca_asset = manager.get_record(asset_id)

        if mca_asset and mca_asset.animations_path:
            export_path = os.path.join(mca_asset.animations_path, f"{sequence_name}.fbx")
            logger.info(f"Export path from asset registry: {export_path}")
            return export_path
        else:
            logger.warning(f"Could not determine animations path for asset: {asset_id}")
            return None

    except Exception as e:
        logger.error(f"Failed to get asset animations path: {e}")
        return None


def create_sequence_from_scene(rig, sequence_name=None):
    """
    Auto-create an animation sequence using scene filename and timeline range.

    This function derives the sequence name from the Maya scene filename and uses
    the current timeline range. The sequence name is prefixed with 'ANIM_' following
    the project naming convention.

    Export path logic:
    - If scene is in _Source/Animations/... → Exports to same path minus _Source
    - Otherwise → Exports to asset's default Animations folder

    :param FRAGRig rig: The FRAG rig to create the sequence for.
    :param str sequence_name: Optional name override. If None, derives from scene filename.
    :return: Created AnimSequence wrapper on success, None on failure.
    :rtype: AnimSequence or None

    Example:
        # Auto-create sequence from scene "CD_Run_Fwd.ma" in _Source/Animations/MainLocomotion/
        # Results in sequence "ANIM_CD_Run_Fwd" exported to Animations/MainLocomotion/
        seq = create_sequence_from_scene(rig)

        # Override the sequence name
        seq = create_sequence_from_scene(rig, sequence_name="ANIM_idle")
    """
    if not rig:
        logger.error("No rig provided for sequence creation")
        return None

    # Validate rig exists in scene
    if not pm.objExists(rig.pynode):
        logger.error(f"Rig no longer exists in scene: {rig}")
        return None

    # Get scene path
    scene_path = pm.sceneName()
    if not scene_path:
        logger.error("Scene has not been saved. Cannot derive sequence name or export path.")
        return None

    # Determine sequence name from scene filename
    if sequence_name is None:
        # Extract base name without extension
        scene_basename = os.path.basename(str(scene_path))
        scene_name_no_ext = os.path.splitext(scene_basename)[0]

        # Use the full scene name (preserving asset prefix like CD_)
        # Just add ANIM_ prefix if not already present
        if not scene_name_no_ext.upper().startswith(ANIM_PREFIX):
            sequence_name = f"{ANIM_PREFIX}{scene_name_no_ext}"
        else:
            sequence_name = scene_name_no_ext

        logger.info(f"Derived sequence name from scene: {sequence_name}")
    else:
        # Ensure provided name has ANIM_ prefix
        if not sequence_name.upper().startswith(ANIM_PREFIX):
            sequence_name = f"{ANIM_PREFIX}{sequence_name}"

    # Compute export path based on scene location
    export_path = _compute_export_path_from_scene(scene_path, sequence_name, rig)
    if not export_path:
        logger.error("Could not determine export path for animation")
        return None

    # Get current timeline range
    frame_range = get_current_frame_range()
    logger.info(f"Using timeline range: {frame_range[0]} to {frame_range[1]}")

    # Create the sequence using existing add_sequence function with explicit output_path
    try:
        new_sequence = add_sequence(
            rig=rig,
            name=sequence_name,
            output_path=export_path,
            frame_range=frame_range,
            start_at_zero=True,
            root_to_origin=True,
            notes="Auto-created by smart_export"
        )

        if new_sequence:
            logger.info(f"Created sequence: {sequence_name} -> {export_path}")
        return new_sequence

    except Exception as e:
        logger.error(f"Failed to create sequence: {e}")
        return None


def smart_export(rigs=None, sequence_name=None, force_create_sequence=False):
    """
    AI-friendly animation export that handles all setup automatically.

    This is the ultimate "just export it" function designed for AI agents. It will:
    1. Find rigs (from selection or scene search)
    2. Create sequences if none exist (using timeline + scene filename with ANIM_ prefix)
    3. Export all animations

    The function returns a structured dict that AI agents can use to provide
    informative feedback to users.

    :param list rigs: Optional list of FRAGRigs or rig names. If None, uses selection
        or searches the scene.
    :param str sequence_name: Optional override for auto-created sequence name.
        Will be prefixed with 'ANIM_' if not already.
    :param bool force_create_sequence: If True, creates a new sequence even if
        sequences already exist.
    :return: Export result summary dict with keys:
        - success (bool): Whether export completed successfully
        - rigs_exported (list): Names of rigs that were exported
        - sequences_exported (list): Info about exported sequences
        - sequences_created (list): Info about any auto-created sequences
        - warnings (list): Any warnings encountered
        - error (str or None): Error message if failed
        - needs_input (bool): If True, user input needed (e.g., which rig to use)
        - available_rigs (list): Rigs available when needs_input is True
    :rtype: dict

    Example:
        # Simple export - finds rig automatically
        result = smart_export()
        if result['success']:
            print(f"Exported {len(result['sequences_exported'])} animations")

        # Export with specific sequence name
        result = smart_export(sequence_name="ANIM_walk_cycle")

        # Handle multiple rigs case
        result = smart_export()
        if result.get('needs_input'):
            print("Multiple rigs found:", result['available_rigs'])
    """
    result = {
        'success': False,
        'rigs_exported': [],
        'sequences_exported': [],
        'sequences_created': [],
        'warnings': [],
        'error': None,
        'needs_input': False,
        'available_rigs': []
    }

    # Step 1: Determine which rigs to export
    export_rigs = []

    if rigs is not None:
        # User provided specific rigs
        if not isinstance(rigs, list):
            rigs = [rigs]

        for rig in rigs:
            # Handle rig names (strings) vs rig objects
            if isinstance(rig, str):
                # Try to find rig by name
                scene_rigs = get_scene_rigs()
                for rig_info in scene_rigs:
                    if rig_info['name'] == rig or rig in rig_info['name']:
                        export_rigs.append(rig_info['rig'])
                        break
            else:
                export_rigs.append(rig)
    else:
        # Try to get from selection first
        selected_rigs = get_selected_rigs()

        if selected_rigs:
            export_rigs = selected_rigs
            logger.info(f"Using {len(export_rigs)} rig(s) from selection")
        else:
            # No selection - search scene
            scene_rigs = get_scene_rigs()

            if not scene_rigs:
                result['error'] = "No FRAG rigs found in scene"
                logger.error(result['error'])
                return result

            if len(scene_rigs) == 1:
                # Single rig - use it
                export_rigs = [scene_rigs[0]['rig']]
                logger.info(f"Using single rig from scene: {scene_rigs[0]['name']}")
            else:
                # Multiple rigs - need user input
                result['needs_input'] = True
                result['available_rigs'] = [
                    {
                        'name': r['name'],
                        'asset_id': r['asset_id'],
                        'has_sequences': r['has_sequences'],
                        'sequence_count': r['sequence_count']
                    }
                    for r in scene_rigs
                ]
                result['error'] = f"Multiple rigs found ({len(scene_rigs)}). Please select which rig(s) to export."
                logger.warning(result['error'])
                return result

    # Validate we have rigs to export
    if not export_rigs:
        result['error'] = "No valid rigs to export"
        logger.error(result['error'])
        return result

    # Validate all rigs exist in scene
    valid_rigs = []
    for rig in export_rigs:
        if pm.objExists(rig.pynode):
            valid_rigs.append(rig)
        else:
            result['warnings'].append(f"Rig no longer exists in scene: {rig}")

    if not valid_rigs:
        result['error'] = "No valid rigs remain after validation"
        logger.error(result['error'])
        return result

    # Step 2: Ensure sequences exist for each rig
    all_sequences = ae_utils.get_sequences()

    for rig in valid_rigs:
        # get_sequences() uses .pynode as keys
        rig_sequences = all_sequences.get(rig.pynode, {})
        rig_name = rig.name() if hasattr(rig, 'name') else str(rig)

        if not rig_sequences or force_create_sequence:
            # No sequences - create one automatically
            logger.info(f"No sequences found for rig '{rig_name}', creating one...")

            new_sequence = create_sequence_from_scene(rig, sequence_name)

            if new_sequence:
                result['sequences_created'].append({
                    'name': new_sequence.name,
                    'rig': rig_name,
                    'frame_range': list(new_sequence.frame_range)
                })
            else:
                result['warnings'].append(f"Failed to create sequence for rig: {rig_name}")
        else:
            logger.info(f"Rig '{rig_name}' has {len(rig_sequences)} existing sequence(s)")

    # Step 3: Export animations
    try:
        export_count = export_all_animations(rigs=valid_rigs)

        if export_count is not None and export_count > 0:
            result['success'] = True
            result['rigs_exported'] = [
                rig.name() if hasattr(rig, 'name') else str(rig)
                for rig in valid_rigs
            ]

            # Get exported sequence info
            updated_sequences = ae_utils.get_sequences()
            for rig in valid_rigs:
                rig_name = rig.name() if hasattr(rig, 'name') else str(rig)
                # get_sequences() uses .pynode as keys
                rig_seqs = updated_sequences.get(rig.pynode, {})
                for seq_path, seq_wrapper in rig_seqs.items():
                    result['sequences_exported'].append({
                        'name': seq_wrapper.name,
                        'rig': rig_name,
                        'path': path_utils.to_full_path(seq_path),
                        'frame_range': list(seq_wrapper.frame_range)
                    })

            logger.info(f"Successfully exported {export_count} animation(s)")
        else:
            result['error'] = "Export completed but no animations were exported"
            logger.warning(result['error'])

    except Exception as e:
        result['error'] = f"Export failed: {str(e)}"
        logger.error(result['error'])

    return result