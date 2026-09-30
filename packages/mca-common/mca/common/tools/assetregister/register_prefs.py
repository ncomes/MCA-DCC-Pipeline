"""
The register preferences dialog.

Split out of ``unified_register`` so the register modules can share these
without importing the window. The code is unchanged.

:Requires: mca.common.pyqt
"""

# MCA python imports
from mca.common import log
from mca.common.pyqt.pygui import qtwidgets
from mca.common.tools.assetregister import register_widgets


logger = log.MCA_LOGGER


class PreferencesDialog(qtwidgets.QDialog):
    """
    Asset Register preferences dialog.

    Lets the user pick which classification "In Path" checkboxes are
    checked by default for new/cleared forms, plus the defaults for
    Auto-Submit to Perforce and Create Folders On Save. All values are
    persisted via the host window's QSettings.
    """

    def __init__(self, settings, parent=None):
        """
        :param qtcore.QSettings settings: Settings object to read/write
            preferences from. Reused from the host window so values stay
            scoped to the same per-user store as splitter geometry.
        """
        super().__init__(parent)
        self.setWindowTitle('Asset Register Preferences')
        self._settings = settings
        self._in_path_checkboxes = {}

        layout = qtwidgets.QVBoxLayout(self)

        in_path_group = qtwidgets.QGroupBox('Default "In Path" Checkboxes')
        in_path_group.setToolTip(
            'When you start a new asset (or click Clear), these are the '
            'classification fields that will be included in the auto-generated '
            'asset folder path.')
        in_path_layout = qtwidgets.QVBoxLayout(in_path_group)
        for field_key, label, factory_default in register_widgets.IN_PATH_FIELDS:
            checkbox = qtwidgets.QCheckBox(label)
            stored = settings.value(
                register_widgets.in_path_pref_key(field_key), factory_default)
            checkbox.setChecked(register_widgets.to_bool(stored, factory_default))
            in_path_layout.addWidget(checkbox)
            self._in_path_checkboxes[field_key] = checkbox
        layout.addWidget(in_path_group)

        workflow_group = qtwidgets.QGroupBox('Workflow Defaults')
        workflow_layout = qtwidgets.QVBoxLayout(workflow_group)
        self._auto_submit_checkbox = qtwidgets.QCheckBox(
            'Auto-Submit to Perforce')
        self._auto_submit_checkbox.setToolTip(
            'When checked, saving an asset automatically submits the registry '
            'file (and any pending asset_data.config edits) to Perforce.')
        self._auto_submit_checkbox.setChecked(
            register_widgets.to_bool(settings.value(register_widgets.PREF_KEY_AUTO_SUBMIT, True), True))
        workflow_layout.addWidget(self._auto_submit_checkbox)

        self._create_folders_checkbox = qtwidgets.QCheckBox(
            'Create Folders On Save')
        self._create_folders_checkbox.setToolTip(
            'When checked, saving creates the standard folder structure on disk.')
        self._create_folders_checkbox.setChecked(
            register_widgets.to_bool(settings.value(register_widgets.PREF_KEY_CREATE_FOLDERS, True), True))
        workflow_layout.addWidget(self._create_folders_checkbox)
        layout.addWidget(workflow_group)

        buttons = qtwidgets.QDialogButtonBox(
            qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        """Persist the chosen defaults to QSettings and close."""
        for field_key, checkbox in self._in_path_checkboxes.items():
            self._settings.setValue(
                register_widgets.in_path_pref_key(field_key), checkbox.isChecked())
        self._settings.setValue(
            register_widgets.PREF_KEY_AUTO_SUBMIT, self._auto_submit_checkbox.isChecked())
        self._settings.setValue(
            register_widgets.PREF_KEY_CREATE_FOLDERS,
            self._create_folders_checkbox.isChecked())
        self.accept()
