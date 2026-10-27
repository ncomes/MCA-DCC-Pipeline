"""
Improved Save Skinning Tool - Version 2.0
Allows saving and applying skin weights with better asset management integration.
Uses a .ui file for the interface.
"""

# System global imports
import os
# Software specific imports
import pymel.core as pm
# MCA python imports
from mca.common import log
from mca.common.paths import project_paths, path_utils
from mca.common.assetlist import get_asset_manager
from mca.common.utils import fileio
from mca.mya.deformations import skin_utils
from mca.mya.pyqt import mayawindows
from mca.mya.utils import optionvars
from mca.common.pyqt.pygui import qtwidgets, qtcore


logger = log.MCA_LOGGER


class SaveSkinningOptionVars(optionvars.MCAOptionVars):
    """
    Option vars for Save Skinning tool.
    """
    MCASaveSkinSelectedCategory = {'default_value': 'All', 'docstring': 'Last selected asset category for Save Skinning tool'}


SAVE_SKINNING_OPTION_VARS = SaveSkinningOptionVars()


class SaveSkinningV2(mayawindows.MCAMayaWindow):
    """
    Improved skin weight save/apply tool with asset registry integration.
    This version loads the UI from a .ui file.
    """
    VERSION = '2.0.0'

    def __init__(self):
        # Get the UI file path
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'save_skinning_v2.ui')

        super().__init__(title='Save/Apply Skinning V2',
                         ui_path=ui_path,
                         version=SaveSkinningV2.VERSION)

        self._current_asset = None
        self._custom_path_mode = False
        self._all_assets = []  # Store all loaded assets
        self._categories = set()  # Store all categories
        self._asset_manager = None

        # Set window size
        self.resize(600, 500)

        # Setup connections
        self._setup_connections()

        # Populate asset list
        self._populate_asset_list()

        # Auto-detect asset from scene
        self._auto_detect_asset()

    def _setup_connections(self):
        """
        Connect UI signals to slots.
        All widget names match those defined in the .ui file.
        """
        # Category combo
        self.ui.category_combo.currentTextChanged.connect(self._on_category_changed)

        # Search field
        self.ui.search_field.textChanged.connect(self._on_search_changed)

        # Asset list
        self.ui.asset_list.itemSelectionChanged.connect(self._on_asset_selected)

        # Browse button
        self.ui.browse_button.clicked.connect(self._on_browse_clicked)

        # Custom path checkbox
        self.ui.custom_path_checkbox.stateChanged.connect(self._on_custom_path_toggled)

        # Action buttons
        self.ui.save_button.clicked.connect(self._on_save_clicked)
        self.ui.apply_button.clicked.connect(self._on_apply_clicked)

    def _populate_asset_list(self):
        """
        Populate the asset list with all registered characters.
        If registry is unavailable, tool will work in manual mode.
        """
        try:
            self._asset_manager = get_asset_manager()
            self._all_assets = list(self._asset_manager.iter_all())

            logger.info(f"Found {len(self._all_assets)} total assets")

            # Collect all categories
            self._categories = set()
            for asset_entry in self._all_assets:
                if asset_entry.category:
                    self._categories.add(asset_entry.category)

            # Populate category combobox
            self.ui.category_combo.blockSignals(True)  # Prevent triggering filter during population
            self.ui.category_combo.clear()
            self.ui.category_combo.addItem("All")
            for category in sorted(self._categories):
                self.ui.category_combo.addItem(category)

            # Restore last selected category from option vars
            saved_category = SAVE_SKINNING_OPTION_VARS.MCASaveSkinSelectedCategory
            index = self.ui.category_combo.findText(saved_category)
            if index >= 0:
                self.ui.category_combo.setCurrentIndex(index)
            self.ui.category_combo.blockSignals(False)

            # Filter and display assets
            self._filter_assets()

        except Exception as e:
            import traceback
            logger.warning(f"Could not load assets: {e}")
            logger.warning(traceback.format_exc())
            self._set_status("Asset list unavailable - use Custom Path mode to browse for skin data folder", error=False)
            # Enable custom path mode automatically
            self.ui.custom_path_checkbox.setChecked(True)
            self._custom_path_mode = True

    def _filter_assets(self):
        """
        Filter assets based on selected category and search text.
        """
        self.ui.asset_list.clear()

        selected_category = self.ui.category_combo.currentText()
        search_text = self.ui.search_field.text().lower()

        filtered_count = 0
        for asset_entry in self._all_assets:
            # Category filter
            if selected_category != "All" and asset_entry.category != selected_category:
                continue

            # Search text filter
            item_text = f"{asset_entry.name} ({asset_entry.asset_id})"
            if search_text and search_text not in item_text.lower():
                continue

            # Add to list
            item = qtwidgets.QListWidgetItem(item_text)
            item.setData(qtcore.Qt.UserRole, asset_entry)
            self.ui.asset_list.addItem(item)
            filtered_count += 1

        logger.info(f"Filtered to {filtered_count} assets (category: {selected_category})")

        if self.ui.asset_list.count() == 0:
            self._set_status(f"No assets found in category '{selected_category}'", error=False)
        else:
            self._set_status(f"Loaded {self.ui.asset_list.count()} assets", error=False)

    def _on_category_changed(self, category):
        """
        Called when category selection changes.

        :param str category: Selected category
        """
        # Save selection to option vars
        SAVE_SKINNING_OPTION_VARS.MCASaveSkinSelectedCategory = category
        logger.info(f"Category changed to: {category}")

        # Re-filter assets
        self._filter_assets()

    def _on_search_changed(self, text):
        """
        Filter asset list based on search text.
        """
        self._filter_assets()

    def _on_asset_selected(self):
        """
        Called when an asset is selected from the list.
        """
        selected_items = self.ui.asset_list.selectedItems()
        if not selected_items:
            self._current_asset = None
            self.ui.asset_info_label.setText("<None>")
            self.ui.path_field.clear()
            self.ui.save_button.setEnabled(False)
            self.ui.apply_button.setEnabled(False)
            return

        item = selected_items[0]
        self._current_asset = item.data(qtcore.Qt.UserRole)

        # Update UI
        self.ui.asset_info_label.setText(self._current_asset.name)

        # Update path if not in custom mode
        if not self._custom_path_mode:
            self._update_default_path()

        self.ui.save_button.setEnabled(True)
        self._set_status(f"Selected: {self._current_asset.name}")

    def _update_default_path(self):
        """
        Update the path field with the default skin data path for the selected asset.
        """
        if not self._current_asset:
            return

        # Get the full path from asset (this is the asset's model folder)
        model_path = self._current_asset.full_path
        if not model_path:
            self._set_status("Warning: Asset has no path defined", error=True)
            self.ui.path_field.clear()
            return

        # Construct default skin data path: {model_path}/_Source/Rigs/Skin_Data
        skin_data_path = os.path.join(model_path, '_Source', 'Rigs', 'Skin_Data')

        # Convert to relative if possible
        display_path = path_utils.to_relative_path(skin_data_path)
        if not display_path:
            display_path = skin_data_path

        self.ui.path_field.setText(display_path)
        self._update_path_status(skin_data_path)

    def _update_path_status(self, full_path):
        """
        Update the path status indicator.

        :param str full_path: Full path to check
        """
        if os.path.exists(full_path):
            self.ui.path_status_label.setText(f"✓ Path exists")
            self.ui.path_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.ui.apply_button.setEnabled(True)
        else:
            self.ui.path_status_label.setText(f"⚠ Path does not exist (will be created on save)")
            self.ui.path_status_label.setStyleSheet("color: #FF9800; font-weight: bold;")
            self.ui.apply_button.setEnabled(False)

    def _on_browse_clicked(self):
        """
        Browse for a custom skin data path.
        """
        start_dir = project_paths.get_project_path()
        if self._current_asset and self._current_asset.full_path:
            start_dir = self._current_asset.full_path

        sel_dir = qtwidgets.QFileDialog.getExistingDirectory(
            self,
            'Select Skin Data Directory:',
            start_dir,
            qtwidgets.QFileDialog.ShowDirsOnly
        )

        if not sel_dir:
            return

        # Convert to relative if possible
        display_path = path_utils.to_relative_path(sel_dir)
        if not display_path:
            display_path = sel_dir

        self.ui.path_field.setText(display_path)
        self._update_path_status(sel_dir)
        self._custom_path_mode = True
        self.ui.custom_path_checkbox.setChecked(True)

        # Enable save button when we have a valid path
        self.ui.save_button.setEnabled(True)

    def _on_custom_path_toggled(self, state):
        """
        Toggle between custom path and default path.
        """
        self._custom_path_mode = bool(state)
        self.ui.path_field.setReadOnly(not self._custom_path_mode)

        if not self._custom_path_mode and self._current_asset:
            # Revert to default path
            self._update_default_path()

    def _auto_detect_asset(self):
        """
        Auto-detect the asset from the root joint in the scene and select it in the list.
        """
        # Try to find root joint
        if not pm.objExists('root'):
            logger.info("No root joint found in scene - manual selection required")
            return

        try:
            root_joint = pm.PyNode('root')

            # Check if root joint has asset_id attribute
            if not root_joint.hasAttr('asset_id'):
                logger.info("Root joint has no asset_id attribute")
                return

            asset_id = pm.getAttr(root_joint.asset_id)
            if not asset_id:
                logger.info("Root joint asset_id is empty")
                return

            if not self._asset_manager:
                self._asset_manager = get_asset_manager()

            # Find and select the asset in the list
            for i in range(self.ui.asset_list.count()):
                item = self.ui.asset_list.item(i)
                asset_entry = item.data(qtcore.Qt.UserRole)
                if asset_entry.asset_id == asset_id:
                    self.ui.asset_list.setCurrentItem(item)
                    self._set_status(f"Auto-detected asset from scene: {asset_entry.name}")
                    logger.info(f"Auto-detected asset: {asset_entry.name} ({asset_id})")
                    return

            logger.warning(f"Asset ID '{asset_id}' from root joint not found in registry")
            self._set_status(f"Asset '{asset_id}' from scene not found in registry", error=True)

        except Exception as e:
            logger.error(f"Failed to auto-detect asset from scene: {e}")
            # Don't show error to user - just log it

    def _on_save_clicked(self):
        """
        Save skin weights for selected meshes.
        """
        # Get full path
        path_text = self.ui.path_field.text()
        if not path_text:
            self._set_status("No path specified", error=True)
            return

        # An unset project root must not match: '' is a substring of every
        # string, which would treat any typed text as an absolute path.
        project_root = project_paths.get_project_path()
        if project_root and project_root in path_text:
            skin_data_path = path_text
        else:
            skin_data_path = path_utils.to_full_path(path_text)

        if not skin_data_path:
            self._set_status("Invalid path", error=True)
            return

        # Create directory and checkout in Perforce if it doesn't exist
        if not os.path.exists(skin_data_path):
            try:
                fileio.touch_and_checkout(skin_data_path)
                logger.info(f"Created directory and checked out in Perforce: {skin_data_path}")
            except Exception as e:
                self._set_status(f"Failed to create directory: {e}", error=True)
                logger.error(f"Failed to create skin data directory: {e}")
                return

        # Save weights (this will also trigger Perforce checkout for the files)
        try:
            skin_utils.save_skin_weights_cmd(skin_data_path)
            self._set_status(f"✓ Saved skin weights to: {path_text}")
            self._update_path_status(skin_data_path)
            logger.info(f"Successfully saved skin weights to: {skin_data_path}")
        except Exception as e:
            self._set_status(f"Error saving weights: {e}", error=True)
            logger.error(f"Failed to save skin weights: {e}")

    def _on_apply_clicked(self):
        """
        Apply saved skin weights to selected meshes.
        """
        # Get full path
        path_text = self.ui.path_field.text()
        if not path_text:
            self._set_status("No path specified", error=True)
            return

        # An unset project root must not match: '' is a substring of every
        # string, which would treat any typed text as an absolute path.
        project_root = project_paths.get_project_path()
        if project_root and project_root in path_text:
            skin_data_path = path_text
        else:
            skin_data_path = path_utils.to_full_path(path_text)

        if not skin_data_path or not os.path.exists(skin_data_path):
            self._set_status("Path does not exist", error=True)
            return

        # Apply weights
        try:
            skin_utils.apply_skin_weights_cmd(skin_data_path)
            self._set_status(f"✓ Applied skin weights from: {path_text}")
            logger.info(f"Successfully applied skin weights from: {skin_data_path}")
        except Exception as e:
            self._set_status(f"Error applying weights: {e}", error=True)
            logger.error(f"Failed to apply skin weights: {e}")

    def _set_status(self, message, error=False):
        """
        Update the status label.

        :param str message: Status message
        :param bool error: Whether this is an error message
        """
        self.ui.status_label.setText(message)
        if error:
            self.ui.status_label.setStyleSheet("padding: 5px; background-color: #ffebee; color: #c62828; border-radius: 3px;")
        else:
            self.ui.status_label.setStyleSheet("padding: 5px; background-color: #e8f5e9; color: #2e7d32; border-radius: 3px;")
