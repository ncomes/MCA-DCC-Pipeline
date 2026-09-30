"""
Source control, from the register's point of view: fetching the latest before an edit, sending
the change in after one.

Part of the Unified Asset Register, split out of ``unified_register`` so each area of the
window is readable on its own. It runs on :class:`unified_register.UnifiedRegisterUI`, which
mixes this class in and builds the attributes it uses.

It said Perforce throughout - in the class docstring, the dialog titles, the log lines and the
method names - and called ``mca.common.p4v.perforce`` directly. It asks
:mod:`mca.common.sourcecontrol` now, so a studio on something else gets the same window, and a
machine with nothing set up gets a register that saves to disk and says so rather than one that
fails on every save.
"""

# python imports
import os

# MCA python imports
from mca.common import log, sourcecontrol
from mca.common.assetlist import asset_paths, unified_entry
from mca.common.paths import paths
from mca.common.pyqt import messages
from mca.common.pyqt.pygui import qtwidgets
from mca.common.tools.assetregister import register_submit


logger = log.MCA_LOGGER


class SubmitMixin:
    """
    Perforce: syncing before an edit, submitting after one, and creating asset folders.

    Mixed into :class:`unified_register.UnifiedRegisterUI`; never instantiated
    on its own.
    """

    # --- Actions ----------------------------------------------------------- #

    def _sync_registry_to_head(self, category):
        """
        Force-sync the registry ``.alist`` file for ``category`` to head
        before we edit it, so concurrent changes from other users don't
        get overwritten by our save.

        Does nothing when the file is not there yet - a category with no assets in it - or
        when this machine has no source control.

        :param str category: Registry category being edited.
        """

        assetlists = paths.get_asset_lists_path()
        if not assetlists:
            return

        file_name = os.path.join(assetlists, '{0}.alist'.format(category))
        if not os.path.isfile(file_name):
            return

        result = sourcecontrol.sync(file_name, force=True)
        if result:
            logger.info('Fetched the latest %s before editing it.', file_name)
        else:
            logger.warning('Could not fetch the latest %s: %s', file_name, result.message)

    def _asset_data_config_path(self):
        """
        :return: The shared ``asset_data.config``, or ``''`` when there is no project.
        :rtype: str
        """

        assetlist = paths.get_asset_list_path()
        if not assetlist:
            return ''

        return os.path.join(assetlist, asset_paths.ASSET_DATA_FILE)

    def _maybe_p4_submit(self, category, entry, action='Register', extra_files=None):
        """
        If the auto-submit checkbox is on, prompt for a short changelist
        description (pre-filled with a sensible default) and submit the
        registry ``.alist`` file for this category to Perforce.

        When ``self._asset_data_dirty`` is set, the shared
        ``asset_data.config`` is bundled into the same changelist so it
        doesn't sit checked-out indefinitely. The submit runs on a worker
        thread behind a modal progress dialog so the UI stays responsive.

        Silently no-ops when the checkbox is off, when Perforce isn't
        reachable, or when the user cancels the prompt.

        :param str category: Registry category being saved.
        :param entry: The asset entry that was saved (for the default
            description); may be None for bulk saves.
        :param str action: Short verb for the default description
            (e.g. ``Register``, ``Update``).
        :param list(str) extra_files: Additional files created alongside the
            entry (e.g. folder placeholder files) to submit in the same CL.
        """

        if not self.ui.p4_submit_checkBox.isChecked():
            return

        asset_lists_dir = paths.get_asset_lists_path()
        file_name = os.path.join(asset_lists_dir, f'{category}.alist')
        if not os.path.exists(file_name):
            logger.warning(f'Registry file not found for submit: {file_name}')
            return

        # Bundle asset_data.config when it has pending edits so shared
        # category/faction/skeleton state ships with the same CL.
        file_paths = [file_name]
        bundle_asset_data = False
        if self._asset_data_dirty:
            cfg_path = self._asset_data_config_path()
            if cfg_path and os.path.exists(cfg_path):
                file_paths.append(cfg_path)
                bundle_asset_data = True

        # Folder placeholders ride along so the new asset folders land in the
        # depot together with the entry that references them.
        extra_files = [p for p in (extra_files or []) if p and os.path.exists(p)]
        file_paths += extra_files

        asset_label = getattr(entry, 'name', '') or category
        default_desc = f'AssetRegister: {action} {asset_label} ({category})'
        if bundle_asset_data:
            default_desc += ' + asset_data.config'
        if extra_files:
            default_desc += ' + folders'
        desc, ok = qtwidgets.QInputDialog.getText(
            self,
            'Perforce Submit',
            'Changelist description:',
            qtwidgets.QLineEdit.Normal,
            default_desc,
        )
        if not ok:
            logger.info('Perforce submit cancelled by user.')
            return
        desc = (desc or '').strip() or default_desc

        success = self._run_threaded_p4_submit(file_paths, desc)
        if success and bundle_asset_data:
            # Only clear the dirty flag once the bundled submit actually
            # succeeded — otherwise the safety net at close still has a
            # chance to retry.
            self._asset_data_dirty = False

    def _run_threaded_p4_submit(self, file_paths, description):
        """
        Send the files in on a worker thread, with the progress dialog up while it happens.

        Returns the boolean success result reported by the worker. The
        local event loop pattern (``dialog.exec_()`` waiting on the
        worker's ``finished`` signal) keeps the call site synchronous from
        the caller's perspective without freezing the UI thread.

        :param list(str) file_paths: Absolute paths to submit.
        :param str description: Changelist description.
        :return: True on a successful submit, False on failure / exception.
        :rtype: bool
        """

        dialog = register_submit.SubmitProgressDialog(parent=self)
        worker = register_submit.SubmitWorker(file_paths, description, parent=self)
        # Auto-close the dialog when the submit thread reports done; the
        # exec_() call below blocks until the dialog accepts.
        worker.finished.connect(dialog.accept)
        worker.start()
        try:
            dialog.exec_()
        finally:
            # Make sure the worker has truly exited before we destroy it
            # (start() returns immediately; finished only fires when run()
            # returns). Without this, deleting the QThread mid-run can
            # crash on shutdown.
            worker.wait()
            worker.deleteLater()
            dialog.deleteLater()
        return bool(worker.success)

    def _maybe_p4_submit_transfer(self, source_category, target_category, entry):
        """
        If auto-submit is on, submit BOTH ``.alist`` files touched by a
        transfer in a single changelist.

        Mirrors ``_maybe_p4_submit`` but bundles the source and target
        registries together so a transfer never lands as two half
        changelists. ``asset_data.config`` is bundled as well when it has
        pending edits.

        Silently no-ops when the checkbox is off, when neither registry
        file exists, or when the user cancels the prompt.

        :param str source_category: Category the asset moved out of.
        :param str target_category: Category the asset moved into.
        :param entry: The transferred asset entry (for the default
            description).
        """

        if not self.ui.p4_submit_checkBox.isChecked():
            return

        asset_lists_dir = paths.get_asset_lists_path()
        file_paths = []
        for category in (source_category, target_category):
            file_name = os.path.join(asset_lists_dir, f'{category}.alist')
            if os.path.exists(file_name):
                file_paths.append(file_name)
            else:
                logger.warning(f'Registry file not found for submit: {file_name}')
        if not file_paths:
            return

        # Bundle asset_data.config when it has pending edits so shared
        # category/faction/skeleton state ships with the same CL.
        bundle_asset_data = False
        if self._asset_data_dirty:
            cfg_path = self._asset_data_config_path()
            if cfg_path and os.path.exists(cfg_path):
                file_paths.append(cfg_path)
                bundle_asset_data = True

        asset_label = getattr(entry, 'name', '') or entry.asset_id
        default_desc = (f'AssetRegister: Transfer {asset_label} '
                        f'({source_category} -> {target_category})')
        if bundle_asset_data:
            default_desc += ' + asset_data.config'
        desc, ok = qtwidgets.QInputDialog.getText(
            self,
            'Perforce Submit',
            'Changelist description:',
            qtwidgets.QLineEdit.Normal,
            default_desc,
        )
        if not ok:
            logger.info('Perforce submit cancelled by user.')
            return
        desc = (desc or '').strip() or default_desc

        success = self._run_threaded_p4_submit(file_paths, desc)
        if success and bundle_asset_data:
            # Only clear the dirty flag once the bundled submit actually
            # succeeded — the safety net at close still gets a chance to retry.
            self._asset_data_dirty = False

    # --- Force-create folder actions --------------------------------------- #

    def _create_dcc_folders_now(self):
        """
        Create the standard DCC folder structure for the current form
        without requiring a Save.

        Reuses the selected entry if one is loaded; otherwise builds a
        transient entry from the form so new-asset workflows can still
        materialize folders before the first Save.
        """

        if self._current_entry is not None:
            entry = self._current_entry
        else:
            data = self._collect_form_data()
            if not data.get('asset_name') or not data.get('category'):
                messages.info_message(
                    'Missing Info',
                    'Fill in Category and Asset Name before creating folders.')
                return
            entry = unified_entry.UnifiedAssetEntry.create(**data)

        if not entry.full_path:
            messages.info_message(
                'No Path',
                'The asset has no resolvable path. Check Category and Asset Name.')
            return

        try:
            placeholder_files = entry.create_folders() or []
        except Exception as err:
            logger.exception('Failed to create DCC folders')
            messages.info_message('Error', f'Could not create folders: {err}')
            return
        messages.info_message(
            'Folders Created',
            f'Created DCC folder structure for "{entry.name}".')
        self._submit_placeholder_files(placeholder_files, entry)

    def _submit_placeholder_files(self, placeholder_files, entry):
        """
        Submit folder placeholder files on their own when auto-submit is on.

        The register/update flows bundle placeholders into the registry
        changelist; the "create folders now" buttons run outside those
        flows, so this gives their placeholders a changelist of their own.
        No-op when auto-submit is off or nothing was created.

        :param list(str) placeholder_files: Placeholder files returned by the folder creation.
        :param entry: The asset the folders belong to (for the description); may be None.
        """

        placeholder_files = [p for p in (placeholder_files or []) if p and os.path.exists(p)]
        if not placeholder_files or not self.ui.p4_submit_checkBox.isChecked():
            return
        asset_label = getattr(entry, 'name', '') or 'asset'
        self._run_threaded_p4_submit(
            placeholder_files, f'AssetRegister: Folder placeholders for {asset_label}')

    def _create_engine_folders_now(self):
        """
        Hook for DCC wrappers to create engine-side folders on demand.

        Base implementation is a no-op outside Unreal — the Unreal wrapper
        overrides this to call the editor asset API and show the button.
        """

        messages.info_message(
            'Unreal Only',
            'Creating engine folders is only available from Unreal.')
