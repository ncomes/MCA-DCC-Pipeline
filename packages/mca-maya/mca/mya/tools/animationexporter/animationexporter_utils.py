"""
Module that contains misc utils for use within the animation export system.
"""

# python imports
import os
from typing import List

# software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log

from mca.common.assetlist import get_asset_manager
from mca.common.paths import path_utils
from mca.common.pyqt import messages
from mca.common.utils import pymaths, fileio

from mca.mya.animation import anim_curves, time_utils
from mca.mya.rigging import frag, rig_utils
from mca.mya.utils import fbx_utils, namespace as namespace_utils, scene_utils

logger = log.MCA_LOGGER


def is_metahuman_head(root: str) -> bool:
    """
    Detect if the given root is associated with a MetaHuman head/face rig.

    This function checks if:
    1. A FRAG MetaHuman component instance is attached to the root
    2. The component has a "head/face" rig scope

    Args:
        root: The root node name or rig to check

    Returns:
        True if this is a MetaHuman head/face rig, False otherwise
    """
    try:
        # Import here to avoid circular dependencies
        from mca.mya.rigging.frag import meta_human_component

        # Get the FRAG rig from the root
        frag_rig = frag.get_frag_rig(root)
        if not frag_rig:
            logger.debug(f"No FRAG rig found for root: {root}")
            return False

        # Look for MetaHuman components in the rig
        # Get all components connected to the rig using get_frag_children
        components = frag_rig.get_frag_children()
        for component in components:
            # Check if this is a MetaHuman component by checking the class name
            if hasattr(component, '__class__') and 'MetaHuman' in component.__class__.__name__:
                # Check if this component has face/head region
                region = getattr(component, 'region', '').lower()
                if 'face' in region or 'head' in region:
                    logger.info(f"MetaHuman head detected for root: {root}")
                    return True

                # Alternative check: see if the component has facial regions
                try:
                    available_regions = component.get_available_regions()
                    face_regions = {'eyes', 'mouth', 'jaw', 'tongue', 'nose', 'brows', 'cheeks'}
                    if any(region in available_regions for region in face_regions):
                        logger.info(f"MetaHuman head detected via facial regions for root: {root}")
                        return True
                except Exception as e:
                    logger.debug(f"Could not check facial regions: {e}")

        # Alternative heuristic approach: check for MetaHuman face control patterns
        # Look for characteristic MetaHuman face controls in the namespace
        frag_root = frag_rig.get_frag_parent()
        if frag_root:
            namespace_name = frag_root.pynode.namespace()
            metahuman_face_controls = [
                'CTRL_C_mouth_',
                'CTRL_L_eye_',
                'CTRL_R_eye_',
                'CTRL_C_jaw_',
                'CTRL_L_brow_',
                'CTRL_R_brow_'
            ]

            # Check if any characteristic MetaHuman face controls exist
            for control_pattern in metahuman_face_controls:
                if namespace_name:
                    search_pattern = f"{namespace_name}:*{control_pattern}*"
                else:
                    search_pattern = f"*{control_pattern}*"

                matching_controls = pm.ls(search_pattern)
                if matching_controls:
                    logger.info(f"MetaHuman head detected via control pattern {control_pattern} for root: {root}")
                    return True

        logger.debug(f"No MetaHuman head detected for root: {root}")
        return False

    except Exception as e:
        logger.warning(f"Error checking if {root} is MetaHuman head: {e}")
        return False


def get_metahuman_face_flags(frag_rig) -> List[pm.PyNode]:
    """
    Get all MetaHuman face flags/controls from a FRAG rig.

    Args:
        frag_rig: The FRAG rig to get face controls from

    Returns:
        List of MetaHuman face control PyNodes
    """
    face_flags = []

    try:
        # Import here to avoid circular dependencies
        from mca.mya.rigging.frag import meta_human_component

        # Look for MetaHuman components in the rig
        components = frag_rig.get_frag_children()
        for component in components:
            # Check if this is a MetaHuman component by checking the class name
            if hasattr(component, '__class__') and 'MetaHuman' in component.__class__.__name__:
                # Get all flags from the MetaHuman component
                all_flags = component.get_flags()
                face_flags.extend([flag.node for flag in all_flags])
                logger.info(f"Found {len(all_flags)} MetaHuman face flags")
                break

    except Exception as e:
        logger.warning(f"Error getting MetaHuman face flags: {e}")

    return face_flags


class AnimSequence(object):
    """
    Class wrapper for the animation sequencer attributes, just to make these a little easier to work with.

    """

    def __init__(self, sequencer_attr):
        self.pynode = sequencer_attr

    @property
    def rig(self):
        found_connection = self.pynode.rig.get()
        if found_connection:
            try:
                return frag.FRAGNode(found_connection)
            except:
                logger.warning('Rig connection is missing or not a valid FRAGRig')
                return None

    @rig.setter
    def rig(self, frag_rig):
        pm.disconnectAttr(self.pynode.rig)
        if frag_rig:
            frag_rig.pynode.message >> self.pynode.rig
            asset_id = frag_rig.get_asset_id(frag_rig)
            self.asset_id = asset_id

    @property
    def asset_id(self):
        return self.pynode.asset_id.get()

    @asset_id.setter
    def asset_id(self, val):
        if isinstance(val, str):
            self.pynode.asset_id.set(val)

    @property
    def bookmark(self):
        found_connection = self.pynode.bookmark.get()
        if found_connection:
            return found_connection

    @bookmark.setter
    def bookmark(self, timeslider_bookmark):
        pm.disconnectAttr(self.pynode.bookmark)
        timeslider_bookmark.message >> self.pynode.bookmark

    @property
    def sequence_path(self):
        return self.pynode.sequence_path.get()

    @sequence_path.setter
    def sequence_path(self, val):
        if isinstance(val, str):
            self.pynode.sequence_path.set(val)

    @property
    def frame_range(self):
        return self.pynode.start_frame.get(), self.pynode.end_frame.get()

    @frame_range.setter
    def frame_range(self, frame_range):
        self.pynode.start_frame.set(frame_range[0])
        self.pynode.end_frame.set(frame_range[-1])
        bookmark_node = self.bookmark
        if bookmark_node:
            bookmark_node.timeRangeStart.set(frame_range[0])
            bookmark_node.timeRangeStop.set(frame_range[-1])
        else:
            timeslider_bookmark = time_utils.create_bookmark(self.name, [frame_range[0], frame_range[-1]])
            self.bookmark = timeslider_bookmark

    @property
    def start_at_zero(self):
        return self.pynode.start_at_zero.get()

    @start_at_zero.setter
    def start_at_zero(self, val):
        self.pynode.start_at_zero.set(val)

    @property
    def root_to_origin(self):
        return self.pynode.root_to_origin.get()

    @root_to_origin.setter
    def root_to_origin(self, val):
        self.pynode.root_to_origin.set(val)

    @property
    def sequence_notes(self):
        return self.pynode.sequence_notes.get()

    @sequence_notes.setter
    def sequence_notes(self, val):
        if isinstance(val, str):
            self.pynode.sequence_notes.set(val)

    @property
    def ui_index(self):
        if self.pynode.node().hasAttr('ui_index'):
            return self.pynode.ui_index.get()
        return 0

    @ui_index.setter
    def ui_index(self, val):
        if isinstance(val, int):
            self.pynode.ui_index.set(val)

    # Helper properties.
    @property
    def name(self):
        return '.'.join(os.path.split(self.sequence_path)[-1].split('.')[:-1])

    def get_data(self):
        return_dict = {'frag_rig': self.rig}
        return_dict['sequence_path'] = self.sequence_path
        return_dict['frame_range'] = self.frame_range
        return_dict['start_at_zero'] = self.start_at_zero
        return_dict['root_to_origin'] = self.root_to_origin
        return_dict['sequence_notes'] = self.sequence_notes
        return_dict['ui_index'] = self.ui_index
        return return_dict

    def set_data(self, data_dict):
        self.rig = data_dict.get('frag_rig', None)
        self.sequence_path = data_dict.get('sequence_path', '')
        self.frame_range = data_dict.get('frame_range', [0, 100])
        self.start_at_zero = data_dict.get('start_at_zero', True)
        self.root_to_origin = data_dict.get('root_to_origin', False)
        self.sequence_notes = data_dict.get('sequence_notes', '')
        self.ui_index = data_dict.get('ui_index', 0)


def _get_sequences():
    """
    From the FragSequencer return all registered sequences.

    :return: A dictionary of FRAGRigs to sequence_paths to AnimSequencer, the FRAGSequencer node, and the current index.
    :rtype: dict, FRAGSequencer, int
    """
    frag_sequencer = frag.get_frag_sequencer()
    entry_dict = {}
    current_index = 0
    for sequence_entry in frag_sequencer.pynode.sequence_list.iterDescendants(1):
        current_index = sequence_entry.index() + 1
        sequence_wrapper = AnimSequence(sequence_entry)
        sequence_frag_rig = sequence_wrapper.rig or sequence_wrapper.pynode.rig.get()
        # Use .pynode as dict key since FRAGNode wrappers don't implement __hash__/__eq__
        rig_key = sequence_frag_rig.pynode if hasattr(sequence_frag_rig, 'pynode') else sequence_frag_rig
        if rig_key not in entry_dict:
            # None entries are okay.
            entry_dict[rig_key] = {}
        entry_dict[rig_key][sequence_wrapper.sequence_path] = sequence_wrapper
    return entry_dict, frag_sequencer, current_index


def get_sequences():
    """
    Wrapper function that returns only the sequencer's data dict.

    :return: A dictionary of FRAGRigs to sequence_paths to AnimSequencer
    :rtype dict
    """
    entry_dict, _, __ = _get_sequences()
    return entry_dict


def set_sequence(sequence_path, frag_rig, frame_range, start_at_zero=True, root_to_origin=True, sequence_notes=None):
    """
    Set a new sequence on the FragSequencer.

    :param str sequence_path: The unique identifying fbx path for this rig's sequence.
    :param FRAGRig frag_rig: The FRAGRig related to the sequence entry.
    :param list[int, int] frame_range: A list containing the starting and ending frames of the sequence.
    :param bool start_at_zero: Stored value if the animation should be set to frame 0 before exporting.
    :param bool root_to_origin: Stored value if the animation should move the root node to origin before exporting.
    :param str sequence_notes: Any notes about this particular sequence.
    :return: The newly set AnimSequence wrapper class.
    :rtype: AnimSequence
    """
    entry_dict, frag_sequencer, current_index = _get_sequences()

    sequence_path = path_utils.to_relative_path(sequence_path)

    # Use .pynode as dict key since FRAGNode wrappers don't implement __hash__/__eq__
    rig_key = frag_rig.pynode
    sequence_wrapper = None
    if rig_key in entry_dict:
        if sequence_path in entry_dict[rig_key]:
            sequence_wrapper = entry_dict[rig_key][sequence_path]

    if not sequence_wrapper:
        sequence_wrapper = AnimSequence(frag_sequencer.pynode.sequence_list[current_index])
        ui_index = len(entry_dict.get(rig_key, {}))
    else:
        ui_index = sequence_wrapper.ui_index

    sequence_wrapper.set_data({'frag_rig': frag_rig,
                               'sequence_path': sequence_path,
                               'frame_range': frame_range,
                               'start_at_zero': start_at_zero,
                               'root_to_origin': root_to_origin,
                               'sequence_notes': sequence_notes,
                               'ui_index': ui_index})

    if not sequence_wrapper.bookmark:
        timeslider_bookmark = time_utils.create_bookmark(sequence_wrapper.name, [frame_range[0], frame_range[-1]])
        sequence_wrapper.bookmark = timeslider_bookmark
        # $BUG FSchorsch the timeslider cannot have incoming connections to its start/stop ranges it won't update.
        #sequence_wrapper.pynode.start_frame >> timeslider_bookmark.timeRangeStart
        #sequence_wrapper.pynode.end_frame >> timeslider_bookmark.timeRangeStop
    else:
        sequence_wrapper.bookmark.timeRangeStart.set(frame_range[0])
        sequence_wrapper.bookmark.timeRangeStop.set(frame_range[-1])

    return sequence_wrapper


def remove_sequence(sequence_path, frag_rig):
    """
    Remove an entry in the FRAGSequencer based on the path and frag rig.

    :param str sequence_path: The unique identifying fbx path for this rig's sequence.
    :param FRAGRig frag_rig: The FRAGRig related to the sequence entry.
    """
    entry_dict, frag_sequencer, current_index = _get_sequences()
    sequence_path = path_utils.to_relative_path(sequence_path)
    # Use .pynode as dict key since FRAGNode wrappers don't implement __hash__/__eq__
    rig_key = frag_rig.pynode
    sequence_wrapper = None
    if rig_key in entry_dict:
        if sequence_path in entry_dict[rig_key]:
            sequence_wrapper = entry_dict[rig_key][sequence_path]
    if sequence_wrapper:
        pm.delete(sequence_wrapper.bookmark)
        sequence_wrapper.pynode.remove(b=True)
        refresh_ui_index()


def reorder_sequence(sequence_path, frag_rig, positive_move):
    """
    Adjust the ui_index value for an entry based on the frag_rig and sequence_path

    :param str sequence_path: The unique identifying fbx path for this rig's sequence.
    :param FRAGRig frag_rig: The FRAGRig related to the sequence entry.
    :param bool positive_move: If the entry's ui_index should be moved towards the head of the list or further down.
        True = lower index position, False = higher index position.
    :return:
    """
    entry_dict, _, _ = _get_sequences()
    # Use .pynode as dict key since FRAGNode wrappers don't implement __hash__/__eq__
    entry_dict = entry_dict.get(frag_rig.pynode)
    if entry_dict:
        sequence_wrapper = entry_dict.get(sequence_path)
        if sequence_wrapper:
            sorted_entry_list = sorted(entry_dict.values(), key=lambda sequence_wrapper: sequence_wrapper.ui_index)
            entry_index = sorted_entry_list.index(sequence_wrapper)

            replacement_entry = None
            if positive_move and entry_index > 0:
                replacement_entry = sorted_entry_list[entry_index-1]
            elif not positive_move and entry_index < len(sorted_entry_list)-1:
                replacement_entry = sorted_entry_list[entry_index + 1]

            if replacement_entry:
                sequence_wrapper.ui_index = replacement_entry.ui_index
                replacement_entry.ui_index = entry_index
                return True


def refresh_ui_index():
    """
    Iterate through all our sequences and reset the ui_index positions to compensate for gaps or duplicates.

    """
    entry_dict, frag_sequencer, current_index = _get_sequences()

    for frag_rig, sequence_dict in entry_dict.items():
        ui_index_dict = {}
        for _, sequence_wrapper in sequence_dict.items():
            ui_index = sequence_wrapper.ui_index

            while ui_index in ui_index_dict:
                # negate duplicate ui_index values
                ui_index += 1
            ui_index_dict[ui_index] = sequence_wrapper

        for index, (_, sequence_wrapper) in enumerate(sorted(ui_index_dict.items(), key=lambda entry_tuple: entry_tuple[0])):
            sequence_wrapper.ui_index = index


def convert_legacy():
    """
    Convert legacy .notes attribute markup to new entries on the FRAG sequencer node.

    """
    for notes_attr in pm.ls('*.notes', r=True):
        notes_str = notes_attr.get()
        # Split notes str on new line and formatting characters.
        split_notes = '::'.join(notes_str.split('\n')[1:]).split('::')
        # Organize them into groups of 8 which includes all the sequence data.
        sequence_str_list = [split_notes[(0 + n) * 9:n * 9 + 9][:-1] for n in range(int(len(split_notes) / 9))]
        # Collect our FRAG rig from the objects the notes attr is on.
        frag_rig = frag.get_frag_rig(notes_attr.node()) or notes_attr.node()
        for sequence_str in sequence_str_list:
            if sequence_str[0]:
                sequence_path, start_frame, end_frame, _, __, sequence_notes, root_to_origin, start_at_zero = sequence_str # sequence_path, start_frame, end_frame, exportable, frame_rate, sequence_notes, root_to_origin, start_at_origin
                set_sequence(os.path.normpath(sequence_path), frag_rig, [int(start_frame), int(end_frame)], bool(start_at_zero), bool(root_to_origin), sequence_notes)
        # Remove notes attr so we don't leave this laying around.
        # Node can be locked, so just unlock first then purge.
        notes_attr.unlock()
        notes_attr.node().unlock()
        notes_attr.delete()

    frag_sequencer = frag.get_frag_sequencer()
    frag_sequence_data_dict = {}
    if not frag_sequencer.pynode.hasAttr('ui_index'):
        frag_sequence_dict = get_sequences()
        for frag_rig, sequence_dict in frag_sequence_dict.items():
            frag_sequence_data_dict[frag_rig] = []
            for sequence_path, sequence_wrapper in sequence_dict.items():
                frag_sequence_data_dict[frag_rig].append(sequence_wrapper.get_data())
        pm.delete(frag_sequencer)

    for x in pm.ls(type=pm.nt.TimeSliderBookmark):
        # Cleanup old TimeSliderBookmarks
        if not x.message.listConnections():
            pm.delete(x)

    for frag_rig, entries_list in frag_sequence_data_dict.items():
        for entry in entries_list:
            entry.pop('ui_index', None)
            set_sequence(**entry)


def reconnect_orphaned_sequences():
    """
    For all entries on the FRAGSequencer that no longer have a FRAGRig connection see if there is a matching rig left in the scene.

    """
    sequence_dict = get_sequences()
    if None in sequence_dict:
        frag_root_dict = {frag_root.asset_id: frag_root.get_rig() for frag_root in frag.get_all_frag_roots()}
        manager = get_asset_manager()
        for _, sequence_wrapper in sequence_dict[None].items():
            asset_id = sequence_wrapper.asset_id
            frag_rig = frag_root_dict.get(asset_id, None)
            mca_asset = manager.get_record(asset_id)
            if mca_asset and mca_asset.name.lower() == asset_id:
                # Match by asset_id or asset_name.
                frag_rig = frag_root_dict.get(mca_asset.asset_id, None) or frag_root_dict.get(mca_asset.name.lower(), None)

            if frag_rig:
                sequence_wrapper.rig = frag_rig


def export_metahuman_face_sequence(sequence_wrapper):
    """
    Export MetaHuman face controls directly without baking.

    Args:
        sequence_wrapper: AnimSequence wrapper for the MetaHuman face sequence
    """
    logger.info(f"Exporting MetaHuman face sequence: {sequence_wrapper.sequence_path}")

    export_path = path_utils.to_full_path(sequence_wrapper.sequence_path)
    frame_range = sequence_wrapper.frame_range

    # Get MetaHuman face controls from the rig
    face_flags = get_metahuman_face_flags(sequence_wrapper.rig)

    if not face_flags:
        logger.warning(f"No MetaHuman face flags found for rig: {sequence_wrapper.rig}")
        return

    logger.info(f"Exporting {len(face_flags)} MetaHuman face controls")

    export_frame_range = frame_range[:]

    # Handle start_at_zero option for MetaHuman face controls
    if start_at_zero and frame_range[0] != 0:
        offset_keys = 0 - frame_range[0]
        anim_curves.change_curve_start_time(face_flags, shift_length=offset_keys)
        export_frame_range = [x + offset_keys for x in export_frame_range]

    # Export FBX with face controls (no baking)
    # Use clip name for the sequence
    clip_name = sequence_wrapper.name
    fbx_utils.export_fbx(export_path, face_flags, clip_name, export_frame_range[0], export_frame_range[1])

    # Skip Perforce checkout in batch mode (detached processes can't spawn subprocesses)
    # Files can be reconciled later: p4 reconcile <path>
    if not pm.about(batch=True):
        fileio.touch_and_checkout(export_path)

    # Restore original keyframe positions if we shifted them
    if start_at_zero and frame_range[0] != 0:
        anim_curves.change_curve_start_time(face_flags, shift_length=offset_keys * -1)


def export_frag_sequences(frag_rig_list=None, sequences_to_skip=None):
    """
    From the FRAG Sequencer export all registered animations filtering by inclusive frag rig list, or exclusively by sequence path.

    :param list(FRAGRig) frag_rig_list: A list of FRAGRigs to export. This is done to facilitate selection based rig exporting.
    :param list(str) sequences_to_skip: A list of sequences that should be skipped. This is done so the UI can send a list of sequences to skip.
    """
    scene_utils.backup_scene('animation_exporter')

    namespace_utils.set_namespace('')
    convert_legacy()

    if sequences_to_skip is None:
        sequences_to_skip = []
    else:
        # In case full paths are passed to the fnc.
        sequences_to_skip = [path_utils.to_relative_path(sequence_path) for sequence_path in sequences_to_skip]

    for rig_pynode, sequence_dict_list in get_sequences().items():
        # get_sequences() returns PyNode keys, wrap back to FRAGRig for API access
        frag_rig = frag.FRAGRig(rig_pynode) if rig_pynode else None
        if frag_rig:
            current_scale = frag_rig.rig_scale
            if current_scale != 1.0:
                frag_rig.rig_scale = 1.0

        # Compare using .pynode since frag_rig_list contains FRAGRig wrappers
        if frag_rig_list and (not frag_rig or frag_rig.pynode not in [r.pynode for r in frag_rig_list]):
            # If this frag rig in the sequencer should be skipped
            logger.warning(f'FRAGRig: {frag_rig} is not on the whitelist for export.')
            continue

        # Check if this is a MetaHuman head rig
        is_metahuman = is_metahuman_head(frag_rig)
        if is_metahuman:
            logger.info(f"MetaHuman head detected - skipping baking for {frag_rig}")

        sequences_to_export = []
        for sequence_path, sequence_wrapper in sequence_dict_list.items():
            if path_utils.to_relative_path(sequence_path) in sequences_to_skip:
                continue
            if sequence_wrapper.sequence_path.lower().endswith('.fbx'):
                sequences_to_export.append(sequence_wrapper)

        if not sequences_to_export:
            # If every sequence in this rig's sequence are skipped.
            logger.warning(f'All sequences are skipped for {frag_rig}.')
            continue

        # Handle MetaHuman face exports separately (no baking)
        if is_metahuman:
            for wrapped_sequence in sequences_to_export:
                export_metahuman_face_sequence(wrapped_sequence)
            # Restore scale and continue to next rig
            if current_scale != 1.0:
                frag_rig.rig_scale = current_scale
            continue

        if len(sequences_to_export) == 1 or len(sequences_to_export) >= .25 * len(sequence_dict_list):
            # if we only have one sequence OR the total number of sequences we're exporting is greater than 25% of the possible sequences.
            if len(sequences_to_export) == 1:
                # Bake selectively
                start_frame, end_frame = sequences_to_export[0].frame_range
                export_root = rig_utils.bake_skeleton_from_rig(frag_rig, start_frame, end_frame, False)
            else:
                start_frame, end_frame = time_utils.get_keyframe_range_from_nodes(frag_rig.get_flags())
                if start_frame is None or end_frame is None:
                    logger.warning(f'There are no keyframes on this rig {frag_rig}.')
                    continue
                # We don't want to shift the keys here our sequences are all coded based on the scene range.
                export_root = rig_utils.bake_skeleton_from_rig(frag_rig, start_frame, end_frame, False)

            if not export_root:
                logger.warning('Skeleton was not baked, verify .skl file, aborting export.')
                return

            export_hierarchy = trim_export_hierarchy(export_root)
            for wrapped_sequence in sequences_to_export:
                _export_baked_skeleton(export_hierarchy, wrapped_sequence)
            pm.delete(export_root)
        else:
            # if we have less than 25% of sequences do them individually.
            for wrapped_sequence in sequences_to_export:
                start_frame, end_frame = wrapped_sequence.frame_range
                export_root = rig_utils.bake_skeleton_from_rig(frag_rig, start_frame, end_frame, False)

                if not export_root:
                    logger.warning('Skeleton was not baked, verify .skl file, aborting export.')
                    return

                export_hierarchy = trim_export_hierarchy(export_root)
                _export_baked_skeleton(export_hierarchy, wrapped_sequence)
                pm.delete(export_root)

        if current_scale != 1.0:
            frag_rig.rig_scale = current_scale


def export_frag_sequences_cmd(frag_rig_list=None, sequences_to_skip=None):
    """
    UI wrapper for the export frag sequences fnc. This will abort if the frame rate isn't set as expected.

    :param list(FRAGRig) frag_rig_list: A list of FRAGRigs to export. This is done to facilitate selection based rig exporting.
    :param list(str) sequences_to_skip: A list of sequences that should be skipped. This is done so the UI can send a list of sequences to skip.
    """
    frame_rate = pm.currentUnit(q=True, time=True)
    if frame_rate != 'ntsc':
        if messages.question_message('Continue Export?', 'Your frame rate is not set to NTSC 30 FPS. It\'s recommended to have your frame rate set to 30 FPS.') != 'Yes':
            return

    export_frag_sequences(frag_rig_list, sequences_to_skip)


def trim_export_hierarchy(export_root):
    """
    Clean the given hierarchy in preperation for export, removing all joints not marked for animationExport

    :param Joint export_root: The root of the export skeleton.
    :return: A list of all the exportable joints
    :rtype: list(Joint)
    """
    if export_root.name() not in ['root', '|root']:
        existing_root = pm.PyNode('root')
        if existing_root:
            existing_root.rename('root1')
        export_root.rename('root')
    baked_hierarchy = pm.listRelatives(export_root, ad=True) + [export_root]
    joints_to_delete = []
    for joint_node in baked_hierarchy:
        # Trim hierarchy to only animatable joints.
        if not isinstance(joint_node, pm.nt.Joint) or not joint_node.getAttr('animationExport'):
            joints_to_delete.append(joint_node)
    pm.delete(joints_to_delete)
    # Repull hierarchy don't trust the for loop, if we have any odd skeletal markup we could have deleted a joint that
    # is not animation exportable, but has a child that is.
    export_hierarchy = pm.listRelatives(export_root, ad=True, type=pm.nt.Joint)+[export_root]
    return export_hierarchy


def _export_baked_skeleton(export_hierarchy, sequence_wrapper):
    """
    From a baked skeleton and a sequence wrapper export the animation to its destination.

    :param list(Joint) export_hierarchy: A list of all exportable joints.
    :param AnimSequence sequence_wrapper: A wrapped sequence entry representing this export.
    """
    export_baked_hierarchy(export_hierarchy,
                           export_path=path_utils.to_full_path(sequence_wrapper.sequence_path),
                           frame_range=sequence_wrapper.frame_range,
                           clip_name=sequence_wrapper.name,
                           start_at_zero=sequence_wrapper.start_at_zero,
                           root_to_origin=sequence_wrapper.root_to_origin)


def export_baked_hierarchy(export_hierarchy, export_path, frame_range, clip_name,
                           start_at_zero=True, root_to_origin=True):
    """
    Write a baked export hierarchy out to FBX.

    The body of :func:`_export_baked_skeleton`, taking plain values instead of a
    sequence wrapper, so callers that are not driven by the FRAG Sequencer - the
    animation library, for one - get the same export rather than a near-copy of
    it. The two things that are easy to get wrong and are handled here: shifting
    the clip to start at zero, and zeroing the root at the first frame so the
    animation does not arrive in engine offset by wherever the shot happened to
    be. Both are restored afterwards, so the scene is left as it was found.

    :param list(Joint) export_hierarchy: Exportable joints, root last.
    :param str export_path: Absolute path to the FBX to write.
    :param list frame_range: ``[start, end]``.
    :param str clip_name: Name of the take inside the FBX.
    :param bool start_at_zero: Shift the animation to begin at frame 0.
    :param bool root_to_origin: Move the root to the origin for the export.
    """

    export_root = export_hierarchy[-1]

    export_frame_range = frame_range[:]
    if start_at_zero and frame_range[0] != 0:
        # Shift Keys so the animation starts at zero.
        offset_keys = 0 - frame_range[0]
        anim_curves.change_curve_start_time(export_hierarchy, shift_length=offset_keys)

        export_frame_range = [x + offset_keys for x in export_frame_range]

    if root_to_origin:
        root_pos = export_root.getAttr('translate', time=export_frame_range[0])
        root_rot = export_root.getAttr('rotate', time=export_frame_range[0])
        if root_pos != pm.dt.Vector([0, 0, 0]):
            for axis, val in zip('XYZ', pymaths.scale_vector(list(root_pos), -1)):
                pm.keyframe(export_root, e=True, iub=True, r=True, at=f'translate{axis}', vc=val)
        if root_rot != pm.dt.Vector([0, 0, 0]):
            for axis, val in zip('XYZ', pymaths.scale_vector(list(root_rot), -1)):
                pm.keyframe(export_root, e=True, iub=True, r=True, at=f'rotate{axis}', vc=val)

    fbx_utils.export_fbx(export_path, export_hierarchy, clip_name,
                         export_frame_range[0], export_frame_range[1])

    # Skip Perforce checkout in batch mode (detached processes can't spawn subprocesses)
    # Files can be reconciled later: p4 reconcile <path>
    if not pm.about(batch=True):
        fileio.touch_and_checkout(export_path)

    if root_to_origin:
        if root_pos != pm.dt.Vector([0, 0, 0]):
            for axis, val in zip('XYZ', root_pos):
                pm.keyframe(export_root, e=True, iub=True, r=True, at=f'translate{axis}', vc=val)
        if root_rot != pm.dt.Vector([0, 0, 0]):
            for axis, val in zip('XYZ', root_rot):
                pm.keyframe(export_root, e=True, iub=True, r=True, at=f'rotate{axis}', vc=val)

    if start_at_zero and frame_range[0] != 0:
        # Move keys back if we shifted them so we're starting fresh for the next sequence.
        anim_curves.change_curve_start_time(export_hierarchy, shift_length=offset_keys * -1)



def quick_export_frag_sequences_cmd():
    """
    Wrapper command to convert a selection into a list of FRAGRigs, then export all sequences associated with those rigs.

    """
    selection = pm.selected()
    if not selection:
        logger.warning('Please select a rig to continue.')
        return

    frame_rate = pm.currentUnit(q=True, time=True)
    if frame_rate != 'ntsc':
        if messages.question_message('Continue Export?', 'Your frame rate is not set to NTSC 30 FPS. It\'s recommended to have your frame rate set to 30 FPS.') != 'Yes':
            return

    frag_rig_list = set([frag.get_frag_rig(x) for x in selection])
    export_frag_sequences_cmd(frag_rig_list)
