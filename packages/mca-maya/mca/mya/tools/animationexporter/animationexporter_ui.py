"""
Module that contains AnimationExporter UIs.
"""

# python imports
import os
import re
# software specific imports
import pymel.core as pm
# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore, qtgui
# MCA python imports
from mca.common import log
from mca.common.assetlist import get_asset_manager
from mca.common.paths import path_utils, project_paths
from mca.common.pyqt import common_windows, messages
from mca.common.utils import strings

from mca.mya.animation import time_utils
from mca.mya.modifiers import ma_decorators
from mca.mya.pyqt import mayawindows
from mca.mya.rigging import frag
from mca.mya.tools.animationexporter import animationexporter_utils as ae_utils
from mca.mya.tools.animationexporter import animationexporter_api as ae_api
from mca.mya.utils import optionvars

logger = log.MCA_LOGGER


class MCAAnimationExporterOptionVars(optionvars.MCAOptionVars):
    """
    This stores the last path for animation browsing and background export preference.

    """
    MCALastAnimationPath = {'default_value': project_paths.get_project_path(), 'docstring': 'Branch content path.'}
    MCAExportInBackground = {'default_value': False, 'docstring': 'Export animations in background Maya process.'}


ANIMATIONEXPORTER_OPTION_VARS = MCAAnimationExporterOptionVars()
global SEQUENCE_PATH_DICT
SEQUENCE_PATH_DICT = {}


class AnimationExporter(mayawindows.MCAMayaWindow):
    VERSION = '1.0.0'

    def __init__(self):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'animationexporter_mainUI.ui')
        super().__init__(title='AnimationExporter',
                         ui_path=ui_path,
                         version=AnimationExporter.VERSION)

        self._rig_dict = {}
        self._rig_list = []
        self.vertical_spacer = None

        # Track running background export processes
        self.running_export_processes = []

        # Load saved background export preference
        self.ui.export_in_background_checkBox.setChecked(ANIMATIONEXPORTER_OPTION_VARS.MCAExportInBackground)

        self.initialize_tabs()
        self.setup_signals()

        # Note: Background processes are fully detached and don't need monitoring
        # Users should check the log files for export status

    def initialize_tabs(self):
        """
        This procedurally generates new tabs and fills them out from the found frag_rigs in the scene and all currently
        registered sequences on the FRAG Sequencer.

        """
        ae_utils.reconnect_orphaned_sequences()
        ae_utils.convert_legacy()

        # start fresh.
        self.ui.tabWidget.clear()

        self._rig_dict = {}
        self._rig_list = []

        global SEQUENCE_PATH_DICT
        for value in SEQUENCE_PATH_DICT.values():
            try:
                value.deleteLater()
            except:
                pass
        SEQUENCE_PATH_DICT = {}

        frag_root_list = frag.get_all_frag_roots()
        for frag_root in frag_root_list:
            # New tab for each rig in the scene.
            frag_rig = frag_root.get_rig()
            if not frag_rig:
                continue
            # Use .pynode as dict key since FRAGNode wrappers don't implement __hash__/__eq__
            self._rig_dict[frag_rig.pynode] = {}
            self._rig_list.append(frag_rig)

            # Tab widget and layout
            rig_tab_widget = qtwidgets.QWidget()
            rig_vertical_layout = qtwidgets.QVBoxLayout()
            rig_horizontal_layout = qtwidgets.QHBoxLayout()
            rig_vertical_layout.addLayout(rig_horizontal_layout)
            rig_tab_widget.setLayout(rig_vertical_layout)

            toggle_export_checkbox = qtwidgets.QCheckBox('Toggle Rig Export')
            toggle_export_checkbox.setChecked(True)
            self._rig_dict[frag_rig.pynode]['toggle_rig_export_checkbox'] = toggle_export_checkbox
            rig_horizontal_layout.addWidget(toggle_export_checkbox)
            add_sequence_button = qtwidgets.QPushButton('Add Sequence')
            self._rig_dict[frag_rig.pynode]['add_sequence_button'] = add_sequence_button
            rig_horizontal_layout.addWidget(add_sequence_button)

            rig_tab_index = self.ui.tabWidget.addTab(rig_tab_widget, f'{frag_root.pynode.namespace().replace(":", "")}:{frag_root.pynode.assetName.get()}')

            # Sequence widget and v Layout
            rig_tab_sequence_widget = qtwidgets.QWidget()
            rig_sequence_vertical_layout = qtwidgets.QVBoxLayout()
            self._rig_dict[frag_rig.pynode]['rig_sequence_vertical_layout'] = rig_sequence_vertical_layout
            rig_tab_sequence_widget.setLayout(rig_sequence_vertical_layout)

            scroll_area = qtwidgets.QScrollArea()
            scroll_area.setVerticalScrollBarPolicy(qtcore.Qt.ScrollBarAlwaysOn)
            scroll_area.setHorizontalScrollBarPolicy(qtcore.Qt.ScrollBarAlwaysOff)
            scroll_area.setWidgetResizable(True)
            scroll_area.setWidget(rig_tab_sequence_widget)
            rig_vertical_layout.addWidget(scroll_area)

            add_sequence_button.pressed.connect(self.add_sequence_cmd)
            toggle_export_checkbox.pressed.connect(self._toggle_local_export)

        # get_sequences() returns PyNode keys (since FRAGNode wrappers don't have __hash__/__eq__)
        # We need to find the matching FRAGRig wrapper from _rig_list for each PyNode key
        for rig_pynode, sequence_wrapper_dict in ae_utils.get_sequences().items():
            if not rig_pynode:
                continue
            # Skip if this rig isn't in our UI (might be orphaned sequence data)
            if rig_pynode not in self._rig_dict:
                continue
            # Find the FRAGRig wrapper that matches this PyNode
            frag_rig = None
            for rig in self._rig_list:
                if rig.pynode == rig_pynode:
                    frag_rig = rig
                    break
            if not frag_rig:
                continue
            # If we have preexisting sequences registered on the FRAGSequencer load those into the GUI.
            # Order the entries based on the ui_index value for each entry.
            for index, (_, sequence_wrapper) in enumerate(sorted(sequence_wrapper_dict.items(), key=lambda sequence_tuple: sequence_tuple[1].ui_index)):
                sequence_widget = self.add_sequence(frag_rig)

                sequence_widget.ui.sequence_export_path_lineEdit.setText(sequence_wrapper.sequence_path)
                sequence_widget.ui.sequence_start_frame_lineEdit.setText(str(sequence_wrapper.frame_range[0]))
                sequence_widget.ui.sequence_end_frame_lineEdit.setText(str(sequence_wrapper.frame_range[1]))
                sequence_widget.ui.sequence_notes_lineEdit.setText(sequence_wrapper.sequence_notes)
                sequence_widget.ui.root_to_origin_checkBox.setChecked(sequence_wrapper.root_to_origin)
                sequence_widget.ui.start_to_zero_checkBox.setChecked(sequence_wrapper.start_at_zero)
                sequence_widget.ui.sequence_name_lineEdit.setText(os.path.basename(sequence_wrapper.sequence_path).replace('.fbx', ''))
                sequence_widget.set_sequence()
            self._add_vertical_spacer(frag_rig)

    def _add_vertical_spacer(self, frag_rig):
        """
        This removes and then adds the vertical spacer to the end of the main v_layout.

        """
        try:
            if self.vertical_spacer:
                self._rig_dict[frag_rig.pynode]['rig_sequence_vertical_layout'].removeWidget(self.vertical_spacer.widget())
        except:
            pass

        self.vertical_spacer = qtwidgets.QSpacerItem(40, 20, qtwidgets.QSizePolicy.Minimum, qtwidgets.QSizePolicy.Expanding)
        self._rig_dict[frag_rig.pynode]['rig_sequence_vertical_layout'].addItem(self.vertical_spacer)

    def setup_signals(self):
        """
        Non-dynamic UI signal hookup.

        """

        self.ui.export_all_checkBox.pressed.connect(self._toggle_global_export)
        self.ui.export_in_background_checkBox.stateChanged.connect(self._on_background_checkbox_changed)
        self.ui.refresh_pushButton.pressed.connect(self.initialize_tabs)
        self.ui.all_rigs_export_selected_pushButton.pressed.connect(lambda: self.export_sequences())
        self.ui.all_rigs_export_all_pushButton.pressed.connect(lambda: self.export_sequences(True))

    def _toggle_global_export(self):
        """
        Toggle only all tab's sequence export checkbox.

        """
        self.toggle_export(self._rig_list, self.ui.export_all_checkBox)

    def _toggle_local_export(self):
        """
        Toggle only the current tab's sequence export checkbox.

        """
        index = self.ui.tabWidget.currentIndex()
        frag_rig = self._rig_list[index]

        self.toggle_export([frag_rig], self._rig_dict[frag_rig.pynode]['toggle_rig_export_checkbox'])

    def _on_background_checkbox_changed(self, state):
        """
        Save the background export preference when checkbox changes.

        :param int state: Qt.CheckState value.
        """
        ANIMATIONEXPORTER_OPTION_VARS.MCAExportInBackground = bool(state)

    def toggle_export(self, frag_rig_list, toggle_checkbox):
        """
        For each sequence entry belonging to the list of FRAG Rigs, toggle their export option to match the checkbox.

        :param list[FRAGRig] frag_rig_list:
        :param qtwidgets.QCheckbox toggle_checkbox: The checkbox that's currently being toggled.
        """
        global SEQUENCE_PATH_DICT
        check_val = toggle_checkbox.isChecked()

        for sequence_widget in SEQUENCE_PATH_DICT.values():
            if sequence_widget.frag_rig in frag_rig_list:
                sequence_widget.ui.export_sequence_checkBox.setChecked(not check_val)

    def add_sequence_cmd(self):
        """
        Finds the active UI tab and looks up the appropriate FRAGRig by its index.

        """
        index = self.ui.tabWidget.currentIndex()
        frag_rig = self._rig_list[index]

        self.add_sequence(frag_rig)

    def add_sequence(self, frag_rig):
        """
        Add a new sequencer UI to the active tab.

        :param FRAGRig frag_rig:
        :return: The widget that represents the new sequence that was added.
        :rtype: AnimationExporterSequence
        """
        if not frag_rig.pynode.exists():
            self.initialize_tabs()

        parent_layout = self._rig_dict[frag_rig.pynode]['rig_sequence_vertical_layout']
        sequence_frame = SequenceFrameButton(frag_rig, parent=self, parent_layout=parent_layout)
        sequence_widget = sequence_frame.sequence_widget
        parent_layout.addWidget(sequence_frame)
        self._add_vertical_spacer(frag_rig)
        return sequence_widget

    # ==============================
    # Headless Export Methods
    # ==============================

    def _find_maya_executable(self):
        """
        Find maya.exe for the current Maya version.

        :return: Path to maya.exe or None if not found.
        :rtype: str or None
        """
        maya_version = pm.about(version=True)

        possible_paths = [
            f"C:/Program Files/Autodesk/Maya{maya_version}/bin/maya.exe",
            f"C:/Program Files/Autodesk/Maya {maya_version}/bin/maya.exe",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        logger.error(f"Could not find maya.exe for Maya {maya_version}")
        return None

    def _cleanup_export_files(self, process_info):
        """
        Clean up temporary files for a process.

        :param dict process_info: Process information dictionary.
        """
        import shutil

        # Clean up params file
        if 'params_file' in process_info and os.path.exists(process_info['params_file']):
            try:
                os.remove(process_info['params_file'])
            except:
                pass

        # Clean up MEL script
        if 'mel_script' in process_info and os.path.exists(process_info['mel_script']):
            try:
                os.remove(process_info['mel_script'])
            except:
                pass

        # Keep log file for debugging - don't delete it

    def _launch_headless_export(self, rigs_to_export, sequences_to_skip):
        """
        Launch animation export in headless Maya process.

        :param list rigs_to_export: List of FRAG rigs to export.
        :param list sequences_to_skip: List of sequence paths to skip.
        """
        import subprocess
        import time
        import json
        import maya.api.OpenMaya as OpenMaya2
        from mca.common.paths import paths
        from mca.common.utils import fileio

        # Find maya.exe
        maya_path = self._find_maya_executable()
        if not maya_path:
            OpenMaya2.MGlobal.displayError("Could not find maya.exe")
            return

        # Get runner script
        runner_script = os.path.join(os.path.dirname(__file__), 'animationexporter_batch_runner.py')
        if not os.path.exists(runner_script):
            OpenMaya2.MGlobal.displayError(f"Runner script not found: {runner_script}")
            return

        # Get current scene file
        current_scene = pm.system.sceneName()
        if not current_scene:
            OpenMaya2.MGlobal.displayError("Please save your scene first")
            return

        # Get MCA Maya preferences directory for temp files (params and logs only)
        maya_prefs_dir = paths.get_dcc_prefs_folder('maya')
        anim_export_temp_dir = os.path.join(maya_prefs_dir, 'animationexporter')
        if not os.path.exists(anim_export_temp_dir):
            os.makedirs(anim_export_temp_dir)

        # Create temp files for params and log
        timestamp = str(int(time.time()))
        params_file = os.path.join(anim_export_temp_dir, f"anim_export_params_{timestamp}.json")
        log_file = os.path.join(anim_export_temp_dir, f"anim_export_log_{timestamp}.txt")

        # Checkout and save current scene in place
        try:
            OpenMaya2.MGlobal.displayInfo("Checking out and saving scene for background export...")
            fileio.touch_and_checkout(str(current_scene), checkout=True)
            pm.saveFile(force=True)
            OpenMaya2.MGlobal.displayInfo(f"Scene saved: {current_scene}")
        except Exception as e:
            OpenMaya2.MGlobal.displayError(f"Failed to save scene: {str(e)}")
            return

        # Get rig names
        rig_names = []
        for rig in rigs_to_export:
            try:
                rig_name = rig.name()
            except:
                rig_name = str(rig)
            rig_names.append(rig_name)

        # Create parameters - use current scene (not temp)
        params = {
            'scene_file': str(current_scene),
            'rig_names': rig_names,
            'sequences_to_skip': sequences_to_skip,
            'log_file': log_file
        }

        with open(params_file, 'w') as f:
            json.dump(params, f, indent=2)

        # Build Python command to run directly
        # This avoids MEL and runs Python immediately, bypassing userSetup
        runner_script_py = runner_script.replace('\\', '/')
        params_file_py = params_file.replace('\\', '/')

        python_cmd = f"import sys; sys.argv = ['{runner_script_py}', '{params_file_py}']; sys.path.insert(0, '{os.path.dirname(runner_script_py)}'); import animationexporter_batch_runner; animationexporter_batch_runner.run_batch_export()"

        # Create MEL script that just runs the Python command
        mel_script = os.path.join(anim_export_temp_dir, f"anim_export_batch_{timestamp}.mel")
        with open(mel_script, 'w') as f:
            f.write(f'python("{python_cmd}");\n')

        # Don't modify environment - let Maya use its normal environment
        # This ensures MCA modules can be imported properly
        env = os.environ.copy()

        # Launch Maya in batch mode with standalone flag
        # -batch: run in batch mode (no UI)
        # -noAutoloadPlugins: skip autoloading plugins
        # -prompt: don't show prompts (missing references, etc.)
        # -script: run this MEL script
        cmd = [maya_path, '-batch', '-noAutoloadPlugins', '-prompt', '-script', mel_script]

        try:
            # Launch detached process that continues running even if UI is closed
            # Use STARTUPINFO to hide the console window (more reliable on Windows)
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000

            # Create startupinfo to hide window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

            # Redirect output to log file instead of pipes so process is fully independent
            with open(log_file, 'w') as log_f:
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,  # Combine stderr with stdout
                    startupinfo=startupinfo,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
                )

            # Don't track the process - it's fully detached now
            # Just store metadata for cleanup
            self.running_export_processes.append({
                'params_file': params_file,
                'log_file': log_file,
                'mel_script': mel_script,
                'timestamp': timestamp
            })

            OpenMaya2.MGlobal.displayInfo(f"-> Started background export process for {len(rig_names)} rig(s)")
            OpenMaya2.MGlobal.displayInfo(f"   Process is detached and will continue even if UI is closed")
            OpenMaya2.MGlobal.displayInfo(f"   Log file: {log_file}")
            OpenMaya2.MGlobal.displayInfo(f"   Check log file for progress and results")

        except Exception as e:
            OpenMaya2.MGlobal.displayError(f"Failed to start background export process: {str(e)}")

    def closeEvent(self, event):
        """
        Handle window close event.

        Note: Background processes are detached and will continue running.

        :param QCloseEvent event: Close event.
        """
        # Detached processes continue running independently
        super().closeEvent(event)

    # ==============================
    # Export Methods
    # ==============================

    def export_sequences(self, all_rigs=False):
        """
        Batch export sequences using the clean API.

        :param bool all_rigs: If the current tab or all rig tabs should be exported.
        """
        global SEQUENCE_PATH_DICT

        # Determine which rigs to export
        if all_rigs:
            rigs_to_export = self._rig_list
        else:
            # Export only current tab's rig
            active_index = self.ui.tabWidget.currentIndex()
            rigs_to_export = [self._rig_list[active_index]]

        # Collect sequences to skip (unchecked)
        sequences_to_skip = []
        for sequence_path, sequencer_widget in SEQUENCE_PATH_DICT.items():
            if not sequencer_widget.ui.export_sequence_checkBox.isChecked():
                if sequencer_widget.frag_rig in rigs_to_export:
                    sequences_to_skip.append(sequence_path)

        # Validate rigs exist before exporting
        for frag_rig in rigs_to_export:
            if not pm.objExists(frag_rig.pynode):
                messages.info_message('Export Failure',
                                     'One or more frag rigs were unable to be located in the scene. Please ensure that the rig exists in the scene.',
                                     icon='error')
                return

        # Check if background export is enabled
        if self.ui.export_in_background_checkBox.isChecked():
            # Route to headless export
            self._launch_headless_export(rigs_to_export, sequences_to_skip)
        else:
            # Normal export using API
            export_count = ae_api.export_all_animations(rigs=rigs_to_export, skip_sequences=sequences_to_skip)

            if export_count is not None:
                logger.info(f"Batch export completed: {export_count} sequence(s) exported")
            else:
                logger.error("Batch export failed. Check Maya logs for details.")


class SequenceFrameButton(qtwidgets.QFrame):
    def __init__(self, frag_rig, parent=None, parent_layout=None):
        super().__init__(parent=parent)
        self.main_ui = parent
        self.parent_layout = parent_layout

        guid = strings.generate_guid()

        self.setContentsMargins(1, 0, 0, 1)
        self.setSizePolicy(qtwidgets.QSizePolicy.Expanding, qtwidgets.QSizePolicy.Fixed)
        self.setMinimumHeight(195)
        self.setMaximumHeight(195)

        self.tool_v_layout = qtwidgets.QVBoxLayout(self)
        self.tool_v_layout.setContentsMargins(0, 0, 0, 0)

        self.tool_button = qtwidgets.QToolButton(self)
        self.tool_button.setObjectName(f'{guid}_toolButton')
        self.tool_button.setSizePolicy(qtwidgets.QSizePolicy.Expanding, qtwidgets.QSizePolicy.Expanding)
        self.tool_button.setArrowType(qtcore.Qt.RightArrow)
        self.tool_button.setText('New Animation')
        self.tool_button.setToolButtonStyle(qtcore.Qt.ToolButtonTextBesideIcon)
        self.tool_button.setContentsMargins(2, 0, 0, 1)
        self.tool_button.setMaximumHeight(25)
        self.tool_button.setMinimumHeight(25)
        self.tool_button.setParent(self)
        self.tool_v_layout.addWidget(self.tool_button)

        self.q_frame = qtwidgets.QFrame(self)
        self.q_frame.setObjectName(f'{guid}_frame')
        self.q_frame.setContentsMargins(2, 0, 1, 0)
        self.q_frame.setMinimumHeight(25)
        self.tool_v_layout.addWidget(self.q_frame)
        self.q_frame.setVisible(0)
        self.q_frame.setSizePolicy(qtwidgets.QSizePolicy.Expanding, qtwidgets.QSizePolicy.Fixed)

        self.sequence_layout = qtwidgets.QVBoxLayout(self.q_frame)
        #self.sequence_layout.setContentsMargins(2, 0, 1, 0)
        self.sequence_layout.setObjectName(f'{guid}_layout')

        self.sequence_widget = AnimationExporterSequence(frag_rig, parent, self)
        self.sequence_layout.addWidget(self.sequence_widget.ui)

        #############
        # Signals
        #############
        self.tool_button.pressed.connect(self.button_pressed)
        self.open_button()

    def remove_frame(self):
        self.parent_layout.removeWidget(self)
        self.deleteLater()


    ##########
    # Slots
    ##########
    def button_pressed(self):
        """
        Opens or closes the QToolbarButton
        """

        if self.q_frame and not self.q_frame.isVisible():
            self.open_button()
        else:
            self.close_button()

    def open_button(self):
        """
        Opens the QToolbarButton
        """

        self.tool_button.setArrowType(qtcore.Qt.DownArrow)
        self.q_frame.setVisible(1)
        self.setMinimumHeight(195)

    def close_button(self):
        """
        Closes the QToolbarButton
        """

        self.tool_button.setArrowType(qtcore.Qt.RightArrow)
        self.q_frame.setVisible(0)
        self.setMinimumHeight(25)


class AnimationExporterSequence(common_windows.ParentableWidget):
    def __init__(self, frag_rig, parent=None, parent_frame=None):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'animationexporter_sequenceUI.ui')
        super().__init__(parent=parent,
                         ui_path=ui_path)

        self.frag_rig = frag_rig
        self.parent_frame = parent_frame
        self.sequence_path = None

        self.setup_signals()

    def setup_signals(self):
        """
        Connect most UI elements to the set_sequence function which handles updating the FRAGSequencer node.

        """
        self.ui.sequence_start_frame_lineEdit.editingFinished.connect(self.set_sequence)
        self.ui.min_frame_pushButton.clicked.connect(lambda: self.set_current_frame(self.ui.sequence_start_frame_lineEdit))
        self.ui.sequence_end_frame_lineEdit.editingFinished.connect(self.set_sequence)
        self.ui.max_frame_pushButton.clicked.connect(lambda: self.set_current_frame(self.ui.sequence_end_frame_lineEdit))

        self.ui.remove_sequence_pushButton.clicked.connect(self.remove_sequence)
        self.ui.browse_path_pushButton.clicked.connect(self._find_file)

        self.ui.move_up_pushButton.clicked.connect(lambda: self.move_sequence(positive_move=True))
        self.ui.move_down_pushButton.clicked.connect(lambda: self.move_sequence(positive_move=False))

        self.ui.root_to_origin_checkBox.clicked.connect(self.set_sequence)
        self.ui.start_to_zero_checkBox.clicked.connect(self.set_sequence)

        self.ui.sequence_export_path_lineEdit.editingFinished.connect(self.set_sequence)
        self.ui.sequence_name_lineEdit.editingFinished.connect(self._update_path)
        self.ui.sequence_notes_lineEdit.editingFinished.connect(self.set_sequence)

        self.ui.export_sequence_pushButton.clicked.connect(self.export_sequence)

        self.ui.set_timeline_pushButton.setIcon(qtgui.QIcon(":adjustTimeline.png"))
        self.ui.set_timeline_pushButton.clicked.connect(self.set_frame_range)
        self.ui.play_range_pushButton.setIcon(qtgui.QIcon(":playClip.png"))
        self.ui.play_range_pushButton.clicked.connect(self.play_frame_range)
        self.ui.playblast_sequence_pushButton.setIcon(qtgui.QIcon(":playblast.png"))
        self.ui.playblast_sequence_pushButton.clicked.connect(self.playblast_frame_range)


    def _update_path(self):
        """
        When the name field is updated if the path field is empty automatically propagate the expected path.

        """
        new_name = self.ui.sequence_name_lineEdit.text()
        if self.ui.sequence_export_path_lineEdit.text() or not new_name:
            return

        manager = get_asset_manager()
        mca_asset = manager.get_record(self.frag_rig.get_asset_id(self.frag_rig))
        animation_path = None
        if mca_asset:
            animation_path = path_utils.to_relative_path(mca_asset.animations_path)

        if animation_path:
            # Only update the UI and FRAG Sequencer if we had a valid path resolution.
            self.set_sequence(os.path.join(animation_path, f'{new_name}.fbx'))

    def _find_file(self):
        """
        Open the file browser to look for where this animation should be exported to.

        """
        # Use the current path or our option var path if the current path is empty.
        start_path = path_utils.to_full_path(self.ui.sequence_export_path_lineEdit.text())
        start_path = os.path.split(start_path)[0] if start_path else ANIMATIONEXPORTER_OPTION_VARS.MCALastAnimationPath

        found_path_list, _ = qtwidgets.QFileDialog.getSaveFileName(None, 'Select Animation', start_path, 'animation (*.fbx)')
        if not found_path_list:
            return

        found_sequence_path = path_utils.to_relative_path(found_path_list)
        self.set_sequence(found_sequence_path)

    def _get_frame_range(self):
        """
        Since the frame range line edits are string boxes fixup the values that are input and adjust them if necessary.
        Use the scene default time ranges if we're unsure.

        return: The start and end frame that is supplied by either the UI or best guess of the scene range.
        rtype: list[int, int]
        """
        frame_range = []
        for frame_element in [self.ui.sequence_start_frame_lineEdit, self.ui.sequence_end_frame_lineEdit]:
            frame_val = frame_element.text()
            frame_val = re.sub('[^-0-9]', '', frame_val)
            if frame_val == '':
                frame_val = None
            else:
                frame_val = int(frame_val)
            frame_range.append(frame_val)

        if None in frame_range:
            frame_range = time_utils.get_times()
            frame_range = [pm.currentTime(), frame_range[-1]]
        for frame_element, frame_val in zip([self.ui.sequence_start_frame_lineEdit, self.ui.sequence_end_frame_lineEdit], frame_range):
            # Don't run cycles of this as we reset the cleaned up value.
            frame_element.blockSignals(True)
            frame_element.setText(str(int(frame_val)))
            frame_element.blockSignals(False)
        return frame_range

    def remove_sequence(self):
        """
        Remove the sequence from the FRAG Sequencer, the UI and close this instance of a sequence.

        """
        self.ui.close()
        self.deleteLater()
        self.parent_frame.remove_frame()

        sequence_path = self.ui.sequence_export_path_lineEdit.text()
        ae_utils.remove_sequence(sequence_path, self.frag_rig)

        global SEQUENCE_PATH_DICT
        SEQUENCE_PATH_DICT.pop(self.sequence_path, None)

    @ma_decorators.keep_current_frame_decorator
    def set_sequence(self, found_sequence_path=None):
        """
        Register an update to this sequence UI to the FRAG Sequencer.

        :param str found_sequence_path: The relative path to a fbx file that this sequence represents.
        """
        if not self.frag_rig.pynode.exists():
            logger.warning('Refresh the main UI, The FRAG Rig associated with this sequence has been lost.')
            return

        found_sequence_path = found_sequence_path if isinstance(found_sequence_path, str) and found_sequence_path else path_utils.to_relative_path(self.ui.sequence_export_path_lineEdit.text())
        if not found_sequence_path:
            return
        global SEQUENCE_PATH_DICT

        if found_sequence_path in SEQUENCE_PATH_DICT and SEQUENCE_PATH_DICT[found_sequence_path] != self:
            logger.warning('This sequence is already registered. Select a unique animation path.')
            return

        # If we were passed a sequence path reset the UI textfield after verifying the path is valid for this sequence.
        self.ui.sequence_export_path_lineEdit.setText(found_sequence_path)
        if not found_sequence_path.lower().endswith('.fbx'):
            self.ui.sequence_export_path_lineEdit.setStyleSheet("""QLineEdit { background-color: darkred }""")
        else:
            self.ui.sequence_export_path_lineEdit.setStyleSheet("""QLineEdit { background-color: None }""")

        ANIMATIONEXPORTER_OPTION_VARS.MCALastAnimationPath = os.path.dirname(found_sequence_path)
        SEQUENCE_PATH_DICT[found_sequence_path] = self

        if self.sequence_path != found_sequence_path:
            ae_utils.remove_sequence(self.sequence_path, self.frag_rig)
            SEQUENCE_PATH_DICT.pop(self.sequence_path, None)

        frame_range = self._get_frame_range()
        ae_utils.set_sequence(found_sequence_path, self.frag_rig, frame_range=frame_range,
                              start_at_zero=self.ui.start_to_zero_checkBox.isChecked(),
                              root_to_origin=self.ui.root_to_origin_checkBox.isChecked(),
                              sequence_notes=self.ui.sequence_notes_lineEdit.text())

        self.sequence_path = path_utils.to_relative_path(self.ui.sequence_export_path_lineEdit.text())
        anim_name = os.path.basename(self.sequence_path.replace('.fbx', ''))
        self.ui.sequence_name_lineEdit.setText(anim_name)
        if self.parent_frame:
            self.parent_frame.tool_button.setText(anim_name)

    
    def set_current_frame(self, ui_element):
        """
        Sets the current frame to either the min or max frame fields.

        :param ui_element: The lineEdit to be updated with the current frame number.
        """
        current_frame = pm.currentTime()
        ui_element.setText(str(int(current_frame)))
        self.set_sequence()


    def export_sequence(self):
        """
        Export only this sequence using the clean API.

        """
        # Use the new API to export this specific sequence
        if not pm.objExists(self.frag_rig.pynode):
            logger.warning('Refresh the main UI, The FRAG Rig associated with this sequence has been lost.')
            messages.info_message('Export Failure', 'One or more frag rigs were unable to be located in the scene. Please ensure that the rig exists in the scene.', icon='error')
            return

        # Check if background export is enabled in main UI
        if hasattr(self.parent_frame, 'main_ui') and self.parent_frame.main_ui:
            if self.parent_frame.main_ui.ui.export_in_background_checkBox.isChecked():
                # Route to headless export - export only this sequence (skip all others)
                all_sequences = ae_utils.get_sequences()
                # get_sequences() uses .pynode as keys
                rig_sequences = all_sequences.get(self.frag_rig.pynode, {})
                sequences_to_skip = [path for path in rig_sequences.keys() if path != self.sequence_path]

                self.parent_frame.main_ui._launch_headless_export([self.frag_rig], sequences_to_skip)
                return

        # Normal export using API
        export_path = ae_api.export_animation(rig=self.frag_rig, sequence_path=self.sequence_path)

        if export_path:
            logger.info(f"Sequence exported successfully: {export_path}")
        else:
            logger.error("Failed to export sequence. Check Maya logs for details.")

    
    def move_sequence(self, positive_move=True):
        """
        Reorder the animation in the UI by adjusting the ui_index value.

        :param bool positive_move: If the animation should be moved up or down on the list.
        """
        if ae_utils.reorder_sequence(self.sequence_path, self.frag_rig, positive_move):
            self.parent_frame.main_ui.initialize_tabs()

    
    def set_frame_range(self):
        """
        Set the active frame range in maya to match this sequence.

        """
        frame_range = self._get_frame_range()
        time_utils.set_timeline_range(frame_range[0], frame_range[-1])
        pm.currentTime(frame_range[0])

    
    def play_frame_range(self):
        """
        Set the active frame range in maya to match this sequence. Then play that frame range.

        """

        current_state = pm.play(q=True, state=True)
        if pm.playbackOptions(query=True, animationStartTime=True) != float(self._get_frame_range()[0]):
            current_state = False

        self.set_frame_range()
        pm.play(state=not current_state)

    
    def playblast_frame_range(self):
        start_frame, end_frame = self._get_frame_range()

        #playblast.create_playblast(file_name=self.ui.sequence_name_lineEdit.text(), start_frame=start_frame, end_frame=end_frame)
