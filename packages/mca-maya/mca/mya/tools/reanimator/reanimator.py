"""
Module that contains Test tool implementation.

"""

# System global imports
import os
# Software specific imports
import pymel.all as pm
# MCA python imports
from mca.common import log
from mca.common.assetlist import get_asset_manager

from mca.mya.utils import optionvars, dag
from mca.mya.animation import time_utils, baking
from mca.mya.modifiers import ma_decorators
from mca.mya.pyqt import mayawindows, dialogs
from mca.mya.rigging import frag
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging import rig_utils
from mca.mya.tools.reanimator import reanimator_get_skel

logger = log.MCA_LOGGER

BAKE_OPTION_VARS = baking.MCABakeOptionVars()


class MCAReanimatorOptionVars(optionvars.MCAOptionVars):
    # Helios Misc
    MCAReanimatorTX = {'default_value': True, 'docstring': 'Overdiver should constrain translate X.'}
    MCAReanimatorTY = {'default_value': True, 'docstring': 'Overdiver should constrain translate Y.'}
    MCAReanimatorTZ = {'default_value': True, 'docstring': 'Overdiver should constrain translate Z.'}
    MCAReanimatorRX = {'default_value': True, 'docstring': 'Overdiver should constrain rotate X.'}
    MCAReanimatorRY = {'default_value': True, 'docstring': 'Overdiver should constrain rotate Y.'}
    MCAReanimatorRZ = {'default_value': True, 'docstring': 'Overdiver should constrain rotate Z.'}
    MCAReanimatorAppend = {'default_value': False, 'docstring': 'When baking animation to the rig if the animation should be baked in place, or appended after the last animated frame.'}
    MCAReanimatorMotionEncode = {'default_value': False, 'docstring': 'When baking animation to the rig if the animation should try and match root motion before being applied.'}
    MCAReanimatorStartToZero = {'default_value': False, 'docstring': 'When baking the rig to a skeleton if the animation should be shifted to start at frame 0.'}
    MCAReanimatorOrientPoint = {'default_value': False, 'docstring': 'When baking the rig to a skeleton if the animation should be shifted to start at frame 0.'}
    MCAReanimatorParent = {'default_value': False, 'docstring': 'When baking the rig to a skeleton if the animation should be shifted to start at frame 0.'}
    

REANIMATOR_OPTION_VARS = MCAReanimatorOptionVars()


class Reanimator(mayawindows.MCAMayaWindow):
    VERSION = '1.0.0'

    def __init__(self):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'ReanimatorUI.ui')
        super().__init__(title='Reanimator',
                         ui_path=ui_path,
                         version=Reanimator.VERSION)

        self._asset_manager = get_asset_manager()


        self.ui.use_frame_range_checkBox.setChecked(BAKE_OPTION_VARS.MCAFrameOverride)
        self.ui.start_frame_spinBox.setValue(BAKE_OPTION_VARS.MCAStartFrame)
        self.ui.end_frame_spinBox.setValue(BAKE_OPTION_VARS.MCAEndFrame)

        self.ui.translate_x_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorTX)
        self.ui.translate_y_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorTY)
        self.ui.translate_z_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorTZ)
        self.ui.rotate_x_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorRX)
        self.ui.rotate_y_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorRY)
        self.ui.rotate_z_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorRZ)

        self.ui.append_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorAppend)
        self.ui.motion_encode_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorMotionEncode)

        self.ui.start_at_zero_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorStartToZero)
        
        self.ui.ori_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorOrientPoint)
        self.ui.ori_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorOrientPoint)
        self.ui.par_checkBox.setChecked(REANIMATOR_OPTION_VARS.MCAReanimatorParent)
        
        # ==============================
        # Signals
        # ==============================
        self.ui.start_frame_spinBox.valueChanged.connect(self._update_option_vars)
        self.ui.end_frame_spinBox.valueChanged.connect(self._update_option_vars)
        self.ui.use_frame_range_checkBox.stateChanged.connect(self._update_option_vars)
        self.ui.bake_selected_pushButton.clicked.connect(self._on_bake_selected_clicked)

        self.ui.mirror_rig_pushButton.clicked.connect(self._on_mirror_rig_clicked)

        self.ui.attach_rigs_pushButton.clicked.connect(self._on_attach_selected_rigs_clicked)
        self.ui.detach_rig_pushButton.clicked.connect(self._on_detach_selected_rig_clicked)
        self.ui.bake_and_detach_pushButton.clicked.connect(self._on_bake_and_detach_selected_rig_clicked)

        self.ui.add_overdriver_pushButton.clicked.connect(self._on_add_overdriver_clicked)
        self.ui.remove_overdriver_pushButton.clicked.connect(self._on_remove_overdriver_clicked)
        self.ui.bake_and_remover_overdriver_pushButton.clicked.connect(self._on_remove_and_bake_overdriver_clicked)

        self.ui.bake_to_rig_pushButton.clicked.connect(self._on_bake_to_rig_clicked)
        self.ui.bake_to_skeleton_pushButton.clicked.connect(self._on_bake_to_skeleton_clicked)
        
        self.ui.ori_checkBox.clicked.connect(self.orient_point_checkbox_clicked)
        self.ui.par_checkBox.clicked.connect(self.parent_checkbox_clicked)
        self.ui.diff_skel_pushButton.clicked.connect(self._on_bake_from_different_to_rig_clicked)
    
    # ==============================
    # Slots
    # ==============================
    
    def _update_option_vars(self):
        BAKE_OPTION_VARS.MCAFrameOverride = bool(self.ui.use_frame_range_checkBox.isChecked())
        BAKE_OPTION_VARS.MCAStartFrame = int(self.ui.start_frame_spinBox.text())
        BAKE_OPTION_VARS.MCAEndFrame = int(self.ui.end_frame_spinBox.text())

        REANIMATOR_OPTION_VARS.MCAReanimatorTX = bool(self.ui.translate_x_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorTY = bool(self.ui.translate_y_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorTZ = bool(self.ui.translate_z_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorRX = bool(self.ui.rotate_x_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorRY = bool(self.ui.rotate_y_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorRZ = bool(self.ui.rotate_z_checkBox.isChecked())

        REANIMATOR_OPTION_VARS.MCAReanimatorAppend = bool(self.ui.append_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorMotionEncode = bool(self.ui.motion_encode_checkBox.isChecked())

        REANIMATOR_OPTION_VARS.MCAReanimatorStartToZero = bool(self.ui.start_at_zero_checkBox.isChecked())
        
        REANIMATOR_OPTION_VARS.MCAReanimatorOrientPoint = bool(self.ui.ori_checkBox.isChecked())
        REANIMATOR_OPTION_VARS.MCAReanimatorParent = bool(self.ui.par_checkBox.isChecked())
        
    def orient_point_checkbox_clicked(self):
        self.ui.par_checkBox.setChecked(not self.ui.ori_checkBox.isChecked())
        self._update_option_vars()
        
    def parent_checkbox_clicked(self):
        self.ui.ori_checkBox.setChecked(not self.ui.par_checkBox.isChecked())
        self._update_option_vars()
    
    def _get_ui_time_range(self):
        """
        If "use frame" range is selected lets peal the frame range from the UI

        :return:
        """

        self._update_option_vars()

        if BAKE_OPTION_VARS.MCAFrameOverride:
            start_frame = BAKE_OPTION_VARS.MCAStartFrame
            end_frame = BAKE_OPTION_VARS.MCAEndFrame
            if end_frame < start_frame:
                # trying to be clever here? reverse the orders.
                logger.warning("End frame is less than start frame, we'll reverse the order and continue.")
            return (end_frame, start_frame) if end_frame < start_frame else (start_frame, end_frame)
        return None, None

    @ma_decorators.keep_selection_decorator
    @ma_decorators.undo_decorator
    @ma_decorators.keep_autokey_decorator
    @ma_decorators.keep_current_frame_decorator
    
    def _on_bake_selected_clicked(self):
        selection = pm.selected()
        if not selection:
            return

        custom_attrs = []
        for x in selection:
            custom_attrs += x.listAttr(ud=True, k=True)

        start_frame, end_frame = self._get_ui_time_range()
        bake_range = [start_frame, end_frame] if start_frame else None
        baking.bake_objects(selection, custom_attrs=custom_attrs, bake_range=bake_range)

    def _on_attach_selected_rigs_clicked(self):
        rig_utils.attach_rigs_cmd()

    def _on_detach_selected_rig_clicked(self):
        rig_utils.detach_rig_cmd()

    @ma_decorators.keep_selection_decorator
    @ma_decorators.undo_decorator
    @ma_decorators.keep_autokey_decorator
    @ma_decorators.keep_current_frame_decorator
    def _on_bake_and_detach_selected_rig_clicked(self):
        logger.warning('Baking animation to rig.')
        start_frame, end_frame = self._get_ui_time_range()

        rig_utils.detach_rig_cmd(True, start_frame, end_frame)

    def _on_add_overdriver_clicked(self):

        skip_rotate_attrs = []
        if not self.ui.rotate_x_checkBox.isChecked(): skip_rotate_attrs.append('x')
        if not self.ui.rotate_y_checkBox.isChecked(): skip_rotate_attrs.append('y')
        if not self.ui.rotate_z_checkBox.isChecked(): skip_rotate_attrs.append('z')

        skip_translate_attrs = []
        if not self.ui.translate_x_checkBox.isChecked(): skip_translate_attrs.append('x')
        if not self.ui.translate_y_checkBox.isChecked(): skip_translate_attrs.append('y')
        if not self.ui.translate_z_checkBox.isChecked(): skip_translate_attrs.append('z')

        asset_id = rig_utils.create_overdriver_cmd(skip_rotate_attrs, skip_translate_attrs, point_orient=self.ui.ori_checkBox.isChecked())
    
    def _on_remove_overdriver_clicked(self):
        rig_utils.bake_overdriver_cmd(False)

    def _get_frag_rig_and_skel_root(self):
        selection = pm.selected()
        frag_rig = None
        skel_root = None
        for selected_node in selection:
            # search through our selection to find a valid frag root and a valid skeleton, grab the first of each.
            frag_rig = frag.get_frag_rig(selected_node)
            if not frag_rig and frag_flag.is_flag_node(selected_node):
                wrapped_node = frag_flag.Flag(selected_node)
                rig_component = frag.FRAGNode(wrapped_node.getAttr('fragParent'))
                frag_rig = rig_component.get_frag_parent()
            elif not skel_root and not frag_flag.is_flag_node(selected_node) and isinstance(selected_node, pm.nt.Joint):
                skel_root = dag.get_absolute_parent(selected_node, node_type=pm.nt.Joint, inclusive=True)
            
            if frag_rig and skel_root:
                break
        return frag_rig, skel_root
    
    def _on_remove_and_bake_overdriver_clicked(self):
        start_frame, end_frame = self._get_ui_time_range()
        rig_utils.bake_overdriver_cmd(True, start_frame, end_frame)

    @ma_decorators.keep_selection_decorator
    @ma_decorators.undo_decorator
    @ma_decorators.keep_autokey_decorator
    @ma_decorators.keep_current_frame_decorator
    def _on_bake_to_rig_clicked(self):
        logger.debug('Baking animation to rig.')
        
        frag_rig, skel_root = self._get_frag_rig_and_skel_root()
        
        if not frag_rig:
            # failed to find required nodes for processing animation.
            logger.warning(f'Please select a rig')
            dialogs.info_prompt(title=f'Select a rig', text=f'Please select a rig')
            return
        
        start_frame, end_frame = self._get_ui_time_range()
        asset_id = rig_utils.animate_rig_from_skeleton_cmd(frag_rig=frag_rig, 
                                                            skel_root=skel_root, 
                                                            start_frame=start_frame, 
                                                            end_frame=end_frame,
                                                            append=self.ui.append_checkBox.isChecked(),
                                                            motion_encode=self.ui.motion_encode_checkBox.isChecked())

        time_utils.reframe_visible_range()
        
    def _on_bake_from_different_to_rig_clicked(self):
        # diff_skel_pushButton
        frag_rig, skel_root = self._get_frag_rig_and_skel_root()
        if not frag_rig:
            # failed to find required nodes for processing animation.
            logger.warning(f'Please select a rig')
            dialogs.info_prompt(title=f'Select a rig', text=f'Please select a rig')
            return
        
        frag_root = frag_rig.get_root()
        asset_id = frag_root.asset_id
        if not asset_id:
            logger.warning('There is no asset id associated with the rig!')
            pm.error('No Asset ID associated with the rig!  The rig must be a FRAG rig!')
        asset_entry = self._asset_manager.get_record(asset_id)
        if not asset_entry:
            logger.warning(f'Could not locate asset entry for id "{asset_id}".')
            dialogs.info_prompt(title='Missing Asset', text=f'Asset "{asset_id}" is not registered.')
            return
        category = asset_entry.category
        
        reanimator_get_skel.SkelAssetSelection(frag_rig=frag_rig, skel_root=skel_root, reanimate_window=self, category=category)
    
    @ma_decorators.keep_selection_decorator
    @ma_decorators.undo_decorator
    @ma_decorators.keep_autokey_decorator
    @ma_decorators.keep_current_frame_decorator
    def _on_bake_to_skeleton_clicked(self):
        logger.debug('Baking rig to skeleton')
        start_frame, end_frame = self._get_ui_time_range()
        asset_id = rig_utils.bake_skeleton_from_rig_cmd(start_frame=start_frame, end_frame=end_frame,
                                               set_to_zero=self.ui.start_at_zero_checkBox.isChecked())

    @ma_decorators.keep_selection_decorator
    @ma_decorators.undo_decorator
    @ma_decorators.keep_autokey_decorator
    @ma_decorators.keep_current_frame_decorator
    def _on_mirror_rig_clicked(self):
        logger.debug('Baking rig to skeleton')
        start_frame, end_frame = self._get_ui_time_range()
        asset_ids = rig_utils.mirror_rig_cmd(start_frame=start_frame, end_frame=end_frame)
