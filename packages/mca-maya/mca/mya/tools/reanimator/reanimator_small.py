"""
Module that contains the mca decorators at a base python level
"""

# System global imports
import os
# software specific imports
import pymel.core as pm
# Qt imports
from mca.common.pyqt.pygui import qtcore
# MCA python imports
from mca.common import log
from mca.common.resources import resources
from mca.mya.utils import optionvars, dag
from mca.mya.rigging import rig_utils
from mca.mya.animation import time_utils, baking
from mca.mya.modifiers import ma_decorators
from mca.mya.tools.reanimator import reanimator
from mca.mya.pyqt import mayawindows, dialogs
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging import frag

logger = log.MCA_LOGGER

resources.register_resources()

BAKE_OPTION_VARS = baking.MCABakeOptionVars()


class MCAReanimatorOptionVars(optionvars.MCAOptionVars):
    MCAReanimBakeToRig = {'default_value': 0, 'docstring': 'Sets the Bake to Rig comboBox.'}
    MCAReanimSmallStartToZero = {'default_value': False, 'docstring': 'When baking the rig to a skeleton if the animation should be shifted to start at frame 0.'}
    MCAReanimUseFrameRange = {'default_value': False, 'docstring': 'Use Frame range when baking.'}


class ReanimatorSmall(mayawindows.MCAMayaWindow):
    VERSION = '1.0.0'

    def __init__(self):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'Reanimator_tb.ui')
        super().__init__(title='Reanimator Compact',
                         ui_path=ui_path,
                         version=ReanimatorSmall.VERSION)
        
        self.optionvars = MCAReanimatorOptionVars()
        
        self.setMinimumHeight(250)
        self.setMaximumHeight(250)
        self.ui.to_rig_pushButton.setIcon(resources.icon(r'tools\player_run_pose_long.png'))
        self.ui.to_rig_pushButton.setIconSize(qtcore.QSize(300, 40))
        self.ui.to_skel_pushButton.setIcon(resources.icon(r'tools\player_run_pose2_long.png'))
        self.ui.to_skel_pushButton.setIconSize(qtcore.QSize(300, 40))
        
        # Optionvar Settings
        self.ui.to_rig_comboBox.setCurrentIndex(self.optionvars.MCAReanimBakeToRig)
        self.ui.start_frame_spinBox.setValue(BAKE_OPTION_VARS.MCAStartFrame)
        self.ui.end_frame_spinBox.setValue(BAKE_OPTION_VARS.MCAEndFrame)
        self.ui.start_at_zero_checkBox.setChecked(self.optionvars.MCAReanimSmallStartToZero)
        self.ui.use_frame_range_checkBox.setChecked(self.optionvars.MCAReanimUseFrameRange)

        
        #########################################
        # Signals
        #########################################
        self.ui.use_frame_range_checkBox.clicked.connect(self._update_option_vars)
        self.ui.start_frame_spinBox.valueChanged.connect(self._update_option_vars)
        self.ui.end_frame_spinBox.valueChanged.connect(self._update_option_vars)
        self.ui.start_at_zero_checkBox.clicked.connect(self._update_option_vars)
        self.ui.to_rig_comboBox.currentIndexChanged.connect(self._update_option_vars)
        self.ui.reload_rig_pushButton.clicked.connect(self.reload_rig)
        self.ui.to_rig_pushButton.clicked.connect(self._on_bake_to_rig_clicked)
        self.ui.to_skel_pushButton.clicked.connect(self._on_bake_to_skeleton_clicked)
        
        self.ui.pop_pushButton.clicked.connect(self.open_reanimator)
    
    ####################################
    # Slots
    ####################################
    
    def open_reanimator(self):
        reanimator.Reanimator()
    
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
    def _on_bake_to_rig_clicked(self):
        motion_encode = False
        append_motion = False
        if self.ui.to_rig_comboBox.currentIndex() == 2 or self.ui.to_rig_comboBox.currentIndex() == 3:
            motion_encode = True
        
        if self.ui.to_rig_comboBox.currentIndex() == 1 or self.ui.to_rig_comboBox.currentIndex() == 3:
            append_motion = True
        
        frag_rig, skel_root = self._get_frag_rig_and_skel_root()
        logger.warning('Baking animation to rig.')
        
        if not frag_rig:
            # failed to find required nodes for processing animation.
            logger.warning(f'Please select a rig')
            dialogs.info_prompt(title=f'Select a rig', text=f'Please select a rig')
            return
        
        start_frame, end_frame = self._get_ui_time_range()

        rig_utils.animate_rig_from_skeleton_cmd(frag_rig=frag_rig,
                                                skel_root=skel_root,
                                                start_frame=start_frame,
                                                end_frame=end_frame,
                                                append=append_motion,
                                                motion_encode=motion_encode)

        time_utils.reframe_visible_range()        

    @ma_decorators.keep_selection_decorator
    @ma_decorators.undo_decorator
    @ma_decorators.keep_autokey_decorator
    @ma_decorators.keep_current_frame_decorator
    def _on_bake_to_skeleton_clicked(self):
        logger.warning('Baking rig to skeleton')
        asset_id = rig_utils.bake_skeleton_from_rig_cmd(set_to_zero=self.ui.start_at_zero_checkBox.isChecked())
    
    def _update_option_vars(self):
        self.optionvars.MCAReanimUseFrameRange = bool(self.ui.use_frame_range_checkBox.isChecked())
        BAKE_OPTION_VARS.MCAStartFrame = float(self.ui.start_frame_spinBox.text())
        BAKE_OPTION_VARS.MCAEndFrame = float(self.ui.end_frame_spinBox.text())
        self.optionvars.MCAReanimBakeToRig = int(self.ui.to_rig_comboBox.currentIndex())
        self.optionvars.MCAReanimSmallStartToZero = bool(self.ui.start_at_zero_checkBox.isChecked())
        
    def reload_rig(self):
        """
        Reloads the rig.  Imports a new rig and re-animates in in place.
        """
        result = dialogs.question_prompt(title='Reload Rig?', text='Reload selected rig/rigs?')
        if result != 'Yes':
            return
        rig_utils.reload_rig_cmd()

    
    