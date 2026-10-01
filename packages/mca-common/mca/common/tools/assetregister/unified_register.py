"""
Unified Asset Registration UI for the MCA asset system.

Provides a comprehensive form for creating and editing assets in the unified
JSON format. The UI scaffold is built entirely in Python code (no QUiLoader)
for compatibility with all host environments including Unreal Engine 5.5+
where QUiLoader is not available.

Supports both parent and child/gear assets. Category changes cascade into
subcategory, faction, skeleton, body type, and built-for dropdowns. The
asset name auto-generates the asset_id, DCC path, and engine path.

:Requires: mca.common.pyqt, mca.common.assetlist, mca.common.paths
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_manager, asset_paths, unified_entry, unified_registry
from mca.common.pyqt import common_windows, messages
from mca.common.pyqt.pygui import qtgui, qtwidgets
from mca.common.tools.assetregister import (
    modify_asset_data,
    register_paths,
    register_prefs,
    register_rows,
    register_scaffold,
    register_tree,
    register_vcs,
    register_widgets)
from mca.common.utils import strings


logger = log.MCA_LOGGER

VERSION = '1.0.0'

# Re-exported so this module's public surface is unchanged by the split; the
# value itself now lives with the widgets that use it.
TREE_FILTER_ALL = register_widgets.TREE_FILTER_ALL


# --- Submit progress + preferences helpers ----------------------------------- #


class UnifiedRegisterUI(register_scaffold.ScaffoldMixin, register_rows.RowsMixin, register_tree.TreeMixin, register_paths.PathsMixin, register_vcs.SubmitMixin,
                        common_windows.MCAMainWindow):
    """
    Main window for unified asset registration.

    Builds the full UI scaffold in Python code, then adds dynamic widgets
    on top: additional types list, asset tree, and detail tab content
    (materials, dyes, decals, textures, attach sockets tables).
    """

    VERSION = VERSION

    def __init__(self, parent=None):
        # No ui_path - we build the scaffold in code to avoid QUiLoader,
        # which freezes in Unreal Engine 5.5+.
        super().__init__(
            title='Unified Asset Registration',
            ui_path=None,
            version=VERSION,
            show_window=False,
            parent=parent,
        )

        # Build the static scaffold (replaces the .ui file)
        self._build_ui_scaffold()
        # Settings menu lives on the QMainWindow's menu bar (free thanks to
        # MCAMainWindow's QMainWindow base) and is built after the scaffold so
        # the central widget is in place.
        self._build_menu_bar()

        # Current editing state
        self._current_entry = None
        self._asset_paths_data = None
        self._global_data = None
        # Tracks whether the shared asset_data.config has pending edits this
        # session. Set True on every save() of _asset_paths_data; piggy-backed
        # onto the next .alist p4_submit so the config doesn't sit checked-out
        # forever, and submitted on close as a safety net if no asset save
        # ever fired.
        self._asset_data_dirty = False

        # Baseline snapshot of _collect_form_data() at the moment the form
        # was last populated/cleared/saved. _is_form_dirty() compares the
        # live form against this; switching assets or closing the window
        # prompts to Save / Discard / Cancel when they differ.
        # ``None`` means "no baseline captured yet" — equivalent to clean
        # so the very first __init__ cascades don't trip the dirty check.
        self._form_baseline = None

        # Category the tree/form currently sit on. _on_category_combo_changed
        # compares against it to spot real switches and to fall back to it
        # when the user cancels the unsaved-changes prompt.
        self._current_category = None
        # Entries behind the current tree, kept for the filter dropdowns.
        self._tree_entries = []

        # Build dynamic UI elements
        self._build_additional_types_widget()
        self._build_asset_tree()
        self._build_materials_tab()
        self._build_dyes_tab()
        self._build_dye_overrides_tab()
        self._build_decals_tab()
        self._build_textures_tab()
        self._build_sockets_tab()

        # Load config data and populate initial dropdowns
        self._load_config_data()
        self._populate_categories()
        self._populate_global_dropdowns()

        # Apply user preferences over the hardcoded defaults so checkbox
        # state matches what the user picked in Settings -> Preferences.
        self._apply_pref_defaults()

        # Connect signals
        self._connect_signals()

        # Default splitter sizes (overridden by saved settings below)
        self.ui.vertical_splitter.setSizes([600, 200])

        # Restore saved layout settings (splitters, slider, geometry)
        self._restore_settings()

        # Initial cascade from current category
        self._on_category_changed()

        # Show now that all widgets and data are ready.
        self.show()


    # --- Config loading ---------------------------------------------------- #

    def _load_config_data(self):
        """Load asset_data.config for dropdown population."""

        self._asset_paths_data = asset_paths.AssetDictData.load()
        if self._asset_paths_data:
            self._global_data = self._asset_paths_data.global_data

    def _populate_categories(self):
        """Populate the category combobox from the config.

        After populating, restore the last-selected category from
        QSettings if it still exists in the config. Selection happens
        with signals blocked so the cascade fires once via the explicit
        ``_on_category_changed`` call in ``__init__`` rather than twice.
        """

        self._block_signals(True)
        self.ui.category_comboBox.clear()

        if self._asset_paths_data:
            categories = self._asset_paths_data.categories_names
            self.ui.category_comboBox.addItems(sorted(categories))

        # Re-select the user's previous working category if we have one
        # and it still exists in the populated combobox. Falls back to
        # the default first item otherwise.
        last_category = self.settings.value(register_widgets.PREF_KEY_LAST_CATEGORY)
        if last_category:
            idx = self.ui.category_comboBox.findText(str(last_category))
            if idx >= 0:
                self.ui.category_comboBox.setCurrentIndex(idx)

        self._block_signals(False)

    def _populate_global_dropdowns(self):
        """Populate dropdowns that come from the _Global config section."""

        if not self._global_data:
            return

        self._block_signals(True)

        # Asset types
        self.ui.asset_type_comboBox.clear()
        self.ui.asset_type_comboBox.addItems(self._global_data.asset_types)

        # Skeletons
        self.ui.skeleton_comboBox.clear()
        self.ui.skeleton_comboBox.addItem('')
        self.ui.skeleton_comboBox.addItems(self._global_data.skeletons)

        # Body types
        self.ui.body_type_comboBox.clear()
        self.ui.body_type_comboBox.addItem('')
        body_types = self._global_data.body_types
        if body_types:
            self.ui.body_type_comboBox.addItems(sorted(body_types.keys()))

        # Slots
        self.ui.slot_comboBox.clear()
        self.ui.slot_comboBox.addItem('None')
        self.ui.slot_comboBox.addItems(self._global_data.slots)

        # Attach sockets for the sockets tab
        self._socket_comboBox.clear()
        self._socket_comboBox.addItems(self._global_data.attach_sockets)

        self._block_signals(False)

    # --- Signal connections ------------------------------------------------ #

    def _connect_signals(self):
        """Wire up all signal/slot connections."""

        # Classification cascade
        # User-driven category changes clear the form to prevent stale
        # data from leaking across categories. Programmatic callers that
        # must preserve form data (e.g. entry load) call the method with
        # clear_form=False directly.
        self.ui.category_comboBox.currentIndexChanged.connect(self._on_category_combo_changed)
        self.ui.is_gear_checkBox.toggled.connect(self._on_is_gear_toggled)
        self.ui.gear_root_lineEdit.editingFinished.connect(self._on_gear_root_edited)
        self.ui.gear_root_browse_pushButton.clicked.connect(self._browse_gear_root)
        self.ui.sub_category_comboBox.currentIndexChanged.connect(self._update_auto_paths)
        self.ui.faction_comboBox.currentIndexChanged.connect(self._update_auto_paths)
        self.ui.body_type_comboBox.currentIndexChanged.connect(self._on_body_type_changed)
        self.ui.asset_type_comboBox.currentIndexChanged.connect(self._on_asset_type_changed)

        # Name change auto-generates ID and paths
        self.ui.name_lineEdit.textChanged.connect(self._on_name_changed)

        # Image path change updates preview
        self.ui.image_lineEdit.textChanged.connect(self._update_image_preview)

        # Built-for change toggles slot visibility
        self.ui.built_for_list.itemSelectionChanged.connect(self._on_built_for_changed)

        # Add-new buttons for classification dropdowns
        self.ui.add_category_pushButton.clicked.connect(self._add_new_category)
        self.ui.add_sub_category_pushButton.clicked.connect(self._add_new_sub_category)
        self.ui.add_faction_pushButton.clicked.connect(self._add_new_faction)
        self.ui.add_skeleton_pushButton.clicked.connect(self._add_new_skeleton)
        self.ui.add_body_type_pushButton.clicked.connect(self._add_new_body_type)
        self.ui.add_slot_pushButton.clicked.connect(self._add_new_slot)
        self.ui.remove_slot_pushButton.clicked.connect(self._remove_current_slot)

        # Path-inclusion toggles regenerate the auto DCC/engine path preview
        # live so the user can see the impact of each checkbox immediately.
        self.ui.subtype_in_path_checkBox.stateChanged.connect(self._update_auto_paths)
        self.ui.faction_in_path_checkBox.stateChanged.connect(self._update_auto_paths)
        self.ui.gender_in_path_checkBox.stateChanged.connect(self._update_auto_paths)
        self.ui.asset_type_in_path_checkBox.stateChanged.connect(self._update_auto_paths)
        self.ui.skeleton_in_path_checkBox.stateChanged.connect(self._update_auto_paths)
        self.ui.body_type_in_path_checkBox.stateChanged.connect(self._update_auto_paths)
        self.ui.additional_types_in_path_checkBox.stateChanged.connect(self._update_auto_paths)

        # Classification dropdowns that can now appear in paths need to update
        # the preview when they change (skeleton/body_type/asset_type already
        # have other handlers; add a direct path refresh for completeness).
        self.ui.gender_comboBox.currentIndexChanged.connect(self._update_auto_paths)
        self.ui.skeleton_comboBox.currentIndexChanged.connect(self._update_auto_paths)

        # Force-create folder buttons
        self.ui.create_dcc_folders_now_pushButton.clicked.connect(self._create_dcc_folders_now)
        self.ui.create_engine_folders_now_pushButton.clicked.connect(self._create_engine_folders_now)

        # Dragging a classification row fires reorder_requested (from the
        # custom list subclass). We rebuild the row order ourselves via the
        # safe _rebuild_classification_order path; Qt's destructive
        # InternalMove is bypassed inside the subclass's dropEvent.
        self.ui.classification_listWidget.reorder_requested.connect(
            self._on_classification_reorder)

        # Additional types
        self._add_type_btn.clicked.connect(self._add_additional_type)
        self._remove_type_btn.clicked.connect(self._remove_additional_type)

        # Tree selection
        self._asset_tree.itemClicked.connect(self._on_tree_item_clicked)
        self.ui.tree_filter_lineEdit.textChanged.connect(self._filter_tree)
        self.ui.tree_subcategory_comboBox.currentIndexChanged.connect(self._on_tree_subcategory_changed)
        self.ui.tree_faction_comboBox.currentIndexChanged.connect(self._on_tree_faction_changed)

        # Sockets
        self._add_socket_btn.clicked.connect(self._add_socket)
        self._remove_socket_btn.clicked.connect(
            lambda: self._remove_slot_row(self._sockets_rows_layout))

        # Browse buttons
        self.ui.image_browse_pushButton.clicked.connect(self._browse_image)
        self.ui.capture_image_pushButton.clicked.connect(self._capture_asset_image)

        # Path browse buttons
        self.ui.dcc_path_browse_pushButton.clicked.connect(self._browse_dcc_path)
        self.ui.engine_path_browse_pushButton.clicked.connect(self._browse_engine_path)

        # Button bar
        self.ui.save_pushButton.clicked.connect(self._save_new_asset)
        self.ui.update_pushButton.clicked.connect(self._update_asset)
        self.ui.remove_pushButton.clicked.connect(self._remove_asset)
        self.ui.transfer_pushButton.clicked.connect(self._transfer_asset)
        self.ui.clear_pushButton.clicked.connect(self._clear_form)
        self.ui.modify_data_pushButton.clicked.connect(self._open_modify_data)

    # --- Cascade logic ----------------------------------------------------- #

    def _on_category_changed(self, clear_form=False):
        """
        Called when the category combobox changes.
        Cascades into subcategory, faction, and built_for dropdowns.
        Refreshes the tree. Syncs the "Is Gear" checkbox from the
        category's stored flag.

        :param bool clear_form: When True, reset every other form field so
            switching categories via the UI does not leak stale data from
            the previous category. Entry-load callers pass False to
            preserve the data they are about to populate.
        """

        category = self.ui.category_comboBox.currentText()
        if not category or not self._asset_paths_data:
            return

        self._block_signals(True)

        category_data = self._asset_paths_data.get_category_data(category)
        self.ui.category_display_lineEdit.setText(category)

        # Sync "Is Gear" flag from category config. Signals are blocked so
        # this does not round-trip back into _on_is_gear_toggled.
        is_gear_cat = bool(category_data and category_data.is_gear)
        self.ui.is_gear_checkBox.setChecked(is_gear_cat)
        self._sync_gear_root_field(category_data)

        # Sub categories
        self.ui.sub_category_comboBox.clear()
        self.ui.sub_category_comboBox.addItem('')
        if category_data:
            subcats = category_data.subcategories or []
            self.ui.sub_category_comboBox.addItems(sorted(subcats))

        # Factions
        self.ui.faction_comboBox.clear()
        self.ui.faction_comboBox.addItem('')
        if category_data:
            factions = category_data.factions or []
            self.ui.faction_comboBox.addItems(sorted(factions))

        # Built-for: every character name, each listed once. No 'None' row -
        # an empty selection is what says "parent asset".
        #
        # De-duplicated deliberately. Several characters have two registry
        # records (see the Game/SampleGame path problem), so the raw list repeats
        # 'Agent_Male' and 'Base_Female'. built_for stores a NAME, so two rows
        # spelling the same name offer a distinction the data cannot record -
        # and selecting one would silently select both.
        char_registry = unified_registry.UnifiedAssetRegistry.load('Characters', create=True)
        names = char_registry.get_all_asset_names() if char_registry else []
        seen = set()
        unique_names = []
        for name in names:
            if name and name.lower() not in seen:
                seen.add(name.lower())
                unique_names.append(name)
        self.ui.built_for_list.clear()
        self.ui.built_for_list.addItems(unique_names)

        self._populate_variant_of()

        # Reset the rest of the form when the user initiated the change.
        # Signals remain blocked so this does not fire a recursive cascade.
        if clear_form:
            self._clear_form(preserve_category=True)

        self._block_signals(False)

        # The id now depends on the category as well as the name, so switching category has to
        # work it out again for an asset that has not been saved yet.
        self._refresh_generated_id()
        self._update_auto_paths()
        self._refresh_tree()
        self._current_category = category

        if clear_form:
            # The regenerated paths and the filter prefill just changed the
            # cleared form, so snapshot again: a category switch on its own
            # must never read as unsaved edits (this was the phantom prompt).
            self._prefill_form_from_filters()
            self._capture_form_baseline()

    def _on_category_combo_changed(self, *_):
        """
        The user picked a category in the Browse panel.

        A dirty form gets one Save / Discard / Cancel prompt while the
        combobox is parked back on the previous category, so a "Save" lands
        in the registry the asset actually belongs to. Cancel leaves the
        old category selected. Otherwise the form resets to a clean
        new-asset state for the chosen category and the tree reloads.
        """

        new_category = self.ui.category_comboBox.currentText()
        if not new_category or new_category == self._current_category:
            return

        if self._current_category and self._is_form_dirty():
            self._block_signals(True)
            self._set_combobox_text(self.ui.category_comboBox, self._current_category)
            self._block_signals(False)
            action = self._prompt_save_if_dirty('switching categories')
            if action == 'cancel':
                return
            self._block_signals(True)
            self._set_combobox_text(self.ui.category_comboBox, new_category)
            self._block_signals(False)

        self._on_category_changed(clear_form=True)


    def _on_body_type_changed(self):
        """
        When body type changes, auto-set the matching skeleton.
        Body types map to specific skeletons via the _Global config.
        """

        body_type = self.ui.body_type_comboBox.currentText()
        if not body_type or not self._global_data:
            return

        body_types = self._global_data.body_types or {}
        skeleton = body_types.get(body_type, '')
        if skeleton:
            # Find and select the matching skeleton
            idx = self.ui.skeleton_comboBox.findText(skeleton)
            if idx >= 0:
                self.ui.skeleton_comboBox.setCurrentIndex(idx)

    def _on_asset_type_changed(self):
        """
        When asset type changes, clear the skeleton if the type does not
        use one (e.g. StaticMesh, Material).
        """

        asset_type = self.ui.asset_type_comboBox.currentText()
        if asset_type and asset_type != 'SkeletalMesh':
            self.ui.skeleton_comboBox.setCurrentIndex(0)
            self.ui.body_type_comboBox.setCurrentIndex(0)

    def _on_built_for_changed(self):
        """
        When built_for changes, toggle slot visibility and update paths.
        Nothing selected means a parent asset, so the slot row hides.
        """

        is_gear = bool(self.ui.built_for_list.selectedItems())

        self.ui.slot_label.setVisible(is_gear)
        self.ui.slot_comboBox.setVisible(is_gear)

        self._update_auto_paths()

        # Refresh the Dye Overrides tab — its schema source is the new
        # parent so any previously rendered editors are stale. Guard the
        # call: this signal also fires before the form is fully built
        # during __init__, when the dye-overrides tab does not yet exist.
        if hasattr(self, '_dye_overrides_rows_layout') and self._current_entry is not None:
            self._populate_dye_overrides_tab(self._current_entry)

    def _refresh_generated_id(self):
        """
        Work out the asset id for a new asset, from its category and its name.

        Only for a new one. An existing asset's id is immutable: it is written into the Maya
        scenes that reference the asset, so renaming the asset must not rewrite it.

        **This is where the duplicate ids came from.** The version this replaces built the id
        as ``strings.remove_chars(name, chars='[^a-zA-Z0-9]+').lower()`` - no category, and no
        underscores - so "Hero Bot" in Characters became ``herobot`` while
        ``unified_entry.build_asset_id``, which everything else uses, makes
        ``characters_hero_bot``. Every asset registered through this window since the id scheme
        changed got the old kind, which is why the registry holds pairs like
        ``pirateshoes`` and ``shoes_pirate``, ``teddy_hat`` and ``hats_teddy``,
        ``agentmale`` and ``agent_male``: the same asset, registered once through the window
        and once through anything else. One function makes an id now.
        """

        if self._current_entry is not None:
            return

        name = self.ui.name_lineEdit.text().strip()
        if not name:
            self.ui.id_lineEdit.clear()
            return

        category = self.ui.category_comboBox.currentText()
        self.ui.id_lineEdit.setText(unified_entry.build_asset_id(category, name))

    def _on_name_changed(self):
        """
        The name was typed in: work out the id and the paths again.
        """

        self._refresh_generated_id()
        self._update_auto_paths()


    # --- Form population from entry ---------------------------------------- #

    def _populate_form_from_entry(self, entry):
        """
        Fill the form with data from a UnifiedAssetEntry.

        :param UnifiedAssetEntry entry: The entry to display.
        """

        self._block_signals(True)

        # Identity
        self.ui.name_lineEdit.setText(entry.name)
        self.ui.id_lineEdit.setText(entry.asset_id)
        self.ui.description_textEdit.setPlainText(entry.description)
        self.ui.image_lineEdit.setText(entry.image)

        # Classification
        self._set_combobox_text(self.ui.category_comboBox, entry.category)
        # Cascade subcategories and factions for the selected category
        self._on_category_changed()
        self._set_combobox_text(self.ui.sub_category_comboBox, entry.subtype)
        self._set_combobox_text(self.ui.faction_comboBox, entry.faction)
        self._set_combobox_text(self.ui.gender_comboBox, entry.gender)
        self._set_combobox_text(self.ui.asset_type_comboBox, entry.asset_type)
        self._set_combobox_text(self.ui.skeleton_comboBox, entry.skeleton)
        self._set_combobox_text(self.ui.body_type_comboBox, entry.body_type)

        # Additional types
        self._additional_types_list.clear()
        for atype in (entry.additional_types or []):
            self._additional_types_list.addItem(atype)

        # Hierarchy
        parents = list(getattr(entry, 'built_for_all', None) or
                       ([entry.built_for] if entry.built_for else []))
        self._select_built_for(parents)
        self._select_variant_of(getattr(entry, 'variant_of', ''))
        self._set_combobox_text(self.ui.slot_comboBox, entry.slot)

        # Path inclusion flags + ordering: restore the checkbox state and
        # row order so the user sees the same toggles and sequence that
        # were persisted (or derived from the stored path for legacy
        # entries — see UnifiedAssetEntry.__init__).
        flags = entry.path_flags
        self.ui.subtype_in_path_checkBox.setChecked(bool(flags.get('include_subtype')))
        self.ui.faction_in_path_checkBox.setChecked(bool(flags.get('include_faction')))
        self.ui.gender_in_path_checkBox.setChecked(bool(flags.get('include_gender')))
        self.ui.asset_type_in_path_checkBox.setChecked(bool(flags.get('include_asset_type')))
        self.ui.skeleton_in_path_checkBox.setChecked(bool(flags.get('include_skeleton')))
        self.ui.body_type_in_path_checkBox.setChecked(bool(flags.get('include_body_type')))
        self.ui.additional_types_in_path_checkBox.setChecked(bool(flags.get('include_additional_types')))
        self._rebuild_classification_order(entry.path_order)

        # Paths
        self.ui.dcc_path_lineEdit.setText(entry.path)
        self.ui.engine_path_lineEdit.setText(entry.engine_path)

        # Materials tab
        self._populate_slot_rows(self._materials_rows_layout, entry.materials)

        # Dyes tab
        self._populate_slot_rows(self._dyes_rows_layout, entry.dyes)

        # Dye Overrides tab — depends on parent schema so rebuild every load.
        self._populate_dye_overrides_tab(entry)

        # Decals tab
        self._populate_slot_rows(self._decals_rows_layout, entry.decals, has_mesh_type=True)

        # Textures tab
        self._populate_texture_rows(self._dcc_tex_rows_layout, entry.textures)
        self._populate_texture_rows(self._engine_tex_rows_layout, entry.engine_textures)

        # Attach sockets tab
        self._populate_socket_rows(self._sockets_rows_layout, entry.attach_sockets)

        self._block_signals(False)

        # Form is now in its "as-loaded" state — capture this as the
        # clean baseline so subsequent edits flip the dirty flag.
        self._capture_form_baseline()

        # Force image preview refresh (textChanged may not fire if value unchanged).
        self._update_image_preview()


    def _resolve_parent_entry(self, entry):
        """
        Look up a variant's parent asset entry, with a small cache.

        Cache is keyed by ``(category, built_for)`` and lives for the
        lifetime of this form. Cleared via ``_invalidate_parent_cache``
        when needed (e.g. after the user opens Save on a different
        category).

        :param entry: The current variant entry.
        :return: The parent ``UnifiedAssetEntry``, or None.
        :rtype: UnifiedAssetEntry or None
        """

        if entry is None or not entry.is_gear:
            return None
        key = (entry.category, entry.built_for)
        if not key[0] or not key[1]:
            return None
        cached = self._parent_entry_cache.get(key)
        if cached is not None:
            return cached
        registry = unified_registry.UnifiedAssetRegistry.load(entry.category)
        if registry is None:
            return None
        parent = registry.get_asset_entry_by_name(
            entry.built_for, skip_dialog=True)
        if parent is not None:
            self._parent_entry_cache[key] = parent
        return parent

    def _invalidate_parent_cache(self):
        """Clear the parent-entry cache after registry mutations."""

        self._parent_entry_cache = {}


    # --- Collect form data ------------------------------------------------- #

    def _capture_form_baseline(self):
        """
        Snapshot the current form state as the clean baseline.

        Call after every populate / clear / successful save so the next
        edit cycle is measured against the right starting point. Failures
        to collect (form not fully built yet) leave the previous baseline
        in place; ``None`` is treated as "clean" by ``_is_form_dirty``.
        """

        try:
            self._form_baseline = self._collect_form_data()
        except Exception as err:
            logger.debug(f'Form baseline capture skipped: {err}')

    def _is_form_dirty(self):
        """
        Return True when the live form differs from the captured baseline.

        Comparing the canonical ``_collect_form_data`` dict means any
        future field added to that dict participates in the dirty check
        for free — no per-widget signal wiring needed.

        :return: True if the user has unsaved edits.
        :rtype: bool
        """

        if self._form_baseline is None:
            return False
        try:
            current = self._collect_form_data()
        except Exception as err:
            logger.debug(f'Dirty check skipped: {err}')
            return False
        return current != self._form_baseline

    def _prompt_save_if_dirty(self, context_label='continuing'):
        """
        If the form has unsaved edits, prompt Save / Discard / Cancel.

        Uses the existing tri-option question dialog (Yes / No / Cancel)
        and re-labels the meaning in the body text so it reads naturally
        regardless of QMessageBox's default labels.

        :param str context_label: Short phrase describing what the user
            is about to do (e.g. "switching assets", "closing the
            window"). Surfaces in the prompt body.
        :return: ``'clean'`` when nothing was dirty, ``'save'`` when the
            save attempt succeeded, ``'discard'`` when the user chose to
            drop changes, ``'cancel'`` when the user backed out (or when
            Save was attempted but failed validation and the form is
            still dirty).
        :rtype: str
        """

        if not self._is_form_dirty():
            return 'clean'

        result = messages.question_message(
            'Unsaved Changes',
            'The current asset form has unsaved changes.\n\n'
            f'Save before {context_label}?\n\n'
            '  Yes = Save changes\n'
            '  No  = Discard changes\n'
            '  Cancel = Stay on this asset',
            tri_option=True,
            parent=self,
        )

        if result == 'Cancel':
            return 'cancel'
        if result == 'Yes':
            # Dispatch to the right save path. Existing-asset edits go
            # through _update_asset; otherwise treat as a new asset.
            if self._current_entry is not None:
                self._update_asset()
            else:
                self._save_new_asset()
            # _update_asset / _save_new_asset capture a fresh baseline
            # on success; if validation failed they show their own popup
            # and leave the form dirty. Treat still-dirty as Cancel so
            # we don't lose work.
            if self._is_form_dirty():
                return 'cancel'
            return 'save'
        # 'No' or any other return falls through to Discard.
        return 'discard'

    def _collect_form_data(self):
        """
        Collect all form values into a dictionary suitable for
        UnifiedAssetEntry.create().

        :return: Dict of keyword arguments for UnifiedAssetEntry.create().
        :rtype: dict
        """

        # Additional types
        additional_types = []
        for i in range(self._additional_types_list.count()):
            additional_types.append(self._additional_types_list.item(i).text())

        data = {
            'asset_name': self.ui.name_lineEdit.text().strip(),
            'category': self.ui.category_comboBox.currentText(),
            'subtype': self.ui.sub_category_comboBox.currentText(),
            'faction': self.ui.faction_comboBox.currentText(),
            'gender': self.ui.gender_comboBox.currentText(),
            'skeleton': self.ui.skeleton_comboBox.currentText(),
            'body_type': self.ui.body_type_comboBox.currentText(),
            'asset_type': self.ui.asset_type_comboBox.currentText(),
            'additional_types': additional_types,
            'built_for': self._collect_built_for(),
            'variant_of': self._collect_variant_of(),
            'slot': '' if self.ui.slot_comboBox.currentText() == 'None'
                    else self.ui.slot_comboBox.currentText(),
            'path': self.ui.dcc_path_lineEdit.text(),
            'engine_path': self.ui.engine_path_lineEdit.text(),
            'description': self.ui.description_textEdit.toPlainText(),
            'image': self.ui.image_lineEdit.text(),
            'materials': self._collect_slot_rows(self._materials_rows_layout),
            'dyes': self._collect_slot_rows(self._dyes_rows_layout),
            'decals': self._collect_slot_rows(self._decals_rows_layout, has_mesh_type=True),
            'textures': self._collect_texture_rows(self._dcc_tex_rows_layout),
            'engine_textures': self._collect_texture_rows(self._engine_tex_rows_layout),
            'attach_sockets': self._collect_socket_rows(self._sockets_rows_layout),
            'dye_overrides': self._collect_dye_overrides(),
            'path_flags': self._collect_path_flags(),
            'path_order': self._collect_classification_order(),
        }

        # Gear placement is passed explicitly so UnifiedAssetEntry.create()
        # regenerates a blank path under the same root the UI previewed.
        data['is_gear'] = bool(data['built_for']) or self.ui.is_gear_checkBox.isChecked()
        data['gear_root'] = self._current_gear_root()

        return data


    def _save_new_asset(self):
        """Save a new asset entry to the registry."""

        data = self._collect_form_data()

        if not data['asset_name']:
            messages.info_message('Validation', 'Please enter an asset name.')
            return

        if not data['category']:
            messages.info_message('Validation', 'Please select a category.')
            return

        # Create the unified entry
        entry = unified_entry.UnifiedAssetEntry.create(**data)

        # Pull head revision before loading so we don't overwrite another
        # user's registry edits.
        self._sync_registry_to_head(data['category'])

        # create=True: this may well be the first asset in a category, which is what the
        # register is for.
        registry = unified_registry.UnifiedAssetRegistry.load(data['category'], create=True)

        # Check for duplicate
        existing = registry.get_asset_entry(entry.asset_id, skip_dialog=True)
        if existing:
            result = messages.question_message(
                'Duplicate Asset',
                f'An asset with ID "{entry.asset_id}" already exists.\n'
                'Do you want to overwrite it?',
            )
            if result != 'Yes':
                return

        registry.add_asset_entry(entry)
        registry.save()

        # Create folder structure if requested. The placeholder files it
        # drops into the empty folders ride along in the registration CL.
        placeholder_files = []
        if self.ui.create_folders_checkBox.isChecked():
            placeholder_files = entry.create_folders() or []

        logger.info(f'Saved new asset: {entry.name} ({entry.asset_id})')
        self._maybe_p4_submit(data['category'], entry, action='Register',
                              extra_files=placeholder_files)
        self._refresh_tree()
        self._current_entry = entry
        # Form now matches what's on disk; refresh baseline so the
        # next dirty check measures from this saved state.
        self._capture_form_baseline()

    def _update_asset(self):
        """Update the currently selected asset entry.

        Asset IDs are immutable once assigned — the original ID is always
        reused regardless of any changes to the Name field. This avoids
        silently orphaning references when the user renames an asset.
        """

        if not self._current_entry:
            messages.info_message('No Selection', 'Select an asset from the tree first.')
            return

        data = self._collect_form_data()
        category = data['category']

        # Pull head revision before loading so we don't overwrite another
        # user's registry edits.
        self._sync_registry_to_head(category)

        # Load the registry
        registry = unified_registry.UnifiedAssetRegistry.load(category)
        if not registry:
            messages.info_message('Error', f'No registry found for category: {category}')
            return

        # Preserve the original ID so rename-on-update doesn't rewrite the key.
        original_id = self._current_entry.asset_id
        data['asset_id'] = original_id
        entry = unified_entry.UnifiedAssetEntry.create(**data)
        registry.add_asset_entry(entry)
        registry.save()

        logger.info(f'Updated asset: {entry.name} ({entry.asset_id})')
        self._maybe_p4_submit(category, entry, action='Update')
        self._refresh_tree()
        self._current_entry = entry
        # Form now matches what's on disk; refresh baseline so the
        # next dirty check measures from this saved state.
        self._capture_form_baseline()


    def _remove_asset(self):
        """Remove the currently selected asset from its registry."""

        if not self._current_entry:
            messages.info_message('No Selection', 'Select an asset from the tree first.')
            return

        result = messages.question_message(
            'Confirm Removal',
            f'Remove asset "{self._current_entry.name}"?\n'
            'This cannot be undone.',
        )
        if result != 'Yes':
            return

        category = self._current_entry.category
        removed_entry = self._current_entry

        # Pull head revision before loading so we don't overwrite another
        # user's registry edits.
        self._sync_registry_to_head(category)

        registry = unified_registry.UnifiedAssetRegistry.load(category)
        if registry:
            registry.remove_asset_entry(self._current_entry.asset_id)
            registry.save()

        logger.info(f'Removed asset: {removed_entry.name}')
        self._maybe_p4_submit(category, removed_entry, action='Remove')
        self._current_entry = None
        self._clear_form()
        self._refresh_tree()

    def _transfer_asset(self):
        """Move the currently selected asset entry to a different category.

        Re-files the registry record only: the entry's ``asset_id`` is
        removed from the source category's ``.alist`` and written into the
        target category's ``.alist``. The asset's ``category`` field is
        updated and its ``path`` / ``engine_path`` are regenerated for the
        new category. Asset files on disk are NOT moved — this mirrors the
        registry-only behavior of Save / Update / Remove.

        The asset_id is immutable and is preserved across the transfer so
        existing references are not orphaned.
        """

        if not self._current_entry:
            messages.info_message('No Selection', 'Select an asset from the tree first.')
            return

        source_category = self._current_entry.category

        # Offer every category currently in the combobox except the one the
        # asset already lives in.
        categories = []
        for i in range(self.ui.category_comboBox.count()):
            cat = self.ui.category_comboBox.itemText(i)
            if cat and cat != source_category:
                categories.append(cat)
        if not categories:
            messages.info_message(
                'Transfer Asset',
                'No other categories are available to transfer into.')
            return

        target_category, ok = qtwidgets.QInputDialog.getItem(
            self,
            'Transfer Asset',
            f'Move "{self._current_entry.name}" from "{source_category}" to:',
            categories,
            0,
            False,  # not editable - must pick an existing category
        )
        if not ok or not target_category:
            return

        # Capture current form state, then retarget it. Clearing path /
        # engine_path forces UnifiedAssetEntry.create() to regenerate them
        # from the new category via build_asset_path(). The original
        # asset_id is reused so references survive the move.
        data = self._collect_form_data()
        data['category'] = target_category
        data['path'] = ''
        data['engine_path'] = ''
        # Let the target category's own gear flag/root decide the new path
        # rather than the source category's UI state.
        data['is_gear'] = None
        data['gear_root'] = None
        data['asset_id'] = self._current_entry.asset_id
        entry = unified_entry.UnifiedAssetEntry.create(**data)

        # Check the destination for an id collision BEFORE removing anything
        # from the source, so a cancelled overwrite leaves both files intact.
        self._sync_registry_to_head(target_category)
        target_registry = unified_registry.UnifiedAssetRegistry.load(target_category,
                                                                    create=True)
        if target_registry.get_asset_entry(entry.asset_id, skip_dialog=True):
            result = messages.question_message(
                'Duplicate Asset',
                f'Category "{target_category}" already has an asset with ID '
                f'"{entry.asset_id}".\nDo you want to overwrite it?',
            )
            if result != 'Yes':
                return

        # The destination is written first, and only then is the asset taken out of where it
        # came from. Either order can be interrupted; this is the order where the failure is
        # recoverable. Taking it out first and then failing to write it loses the entry
        # altogether - the files stay on disk but nothing in the registry points at them -
        # whereas writing it first and then failing leaves it listed twice, which somebody can
        # see and delete. The version this replaces did it the other way round, with a comment
        # explaining that it must never be listed twice; assetlist_api.transfer_asset chose
        # this way round with a comment explaining that it must never be lost. They are the
        # same operation and they now agree.
        self._sync_registry_to_head(source_category)
        source_registry = unified_registry.UnifiedAssetRegistry.load(source_category)

        target_registry.add_asset_entry(entry)
        if not target_registry.save():
            messages.error_message(
                'Move',
                'The {0} asset list could not be written, so nothing was moved.'.format(
                    target_category))
            return

        if source_registry:
            source_registry.remove_asset_entry(self._current_entry.asset_id)
            if not source_registry.save():
                # Both halves are checked, which neither this nor the API did. Say what state
                # the registry is actually in: an artist who is told "moved" and finds it in
                # both places has no way of knowing which one to trust.
                messages.error_message(
                    'Move',
                    '{0} was written into {1}, but {2} could not be written, so it is still '
                    'listed there as well. Remove it from {2} before anything reads the '
                    'registry again.'.format(entry.name, target_category, source_category))
                self._refresh_tree()
                return

        logger.info(
            f'Transferred asset "{entry.name}" ({entry.asset_id}) '
            f'from "{source_category}" to "{target_category}".')

        self._maybe_p4_submit_transfer(source_category, target_category, entry)

        # Switch the UI over to the destination category and re-select the
        # moved asset. _populate_form_from_entry cascades into
        # _on_category_changed (rebuilding the tree) and re-captures the
        # form baseline, matching the _on_tree_item_clicked flow.
        self._current_entry = entry
        self._populate_form_from_entry(entry)
        self._update_preview_panel(entry)


    def _clear_form(self, preserve_category=False):
        """Reset all form fields to their default empty state.

        :param bool preserve_category: When True, leave the Category
            combobox and its "Is Gear" flag alone. Used when the form is
            being cleared in response to a category change — the category
            itself is the trigger, not something to reset.
        """

        # Clearing drops any selected entry so the next edits are treated as
        # a new asset (re-enabling asset_id auto-generation from the name).
        self._current_entry = None

        self.ui.name_lineEdit.clear()
        self.ui.id_lineEdit.clear()
        self.ui.description_textEdit.clear()
        self.ui.image_lineEdit.clear()

        self.ui.sub_category_comboBox.setCurrentIndex(0)
        self.ui.faction_comboBox.setCurrentIndex(0)
        self.ui.gender_comboBox.setCurrentIndex(0)
        self.ui.asset_type_comboBox.setCurrentIndex(0)
        self.ui.skeleton_comboBox.setCurrentIndex(0)
        self.ui.body_type_comboBox.setCurrentIndex(0)
        self.ui.built_for_list.clearSelection()
        self.ui.variant_of_comboBox.setCurrentIndex(0)
        self.ui.slot_comboBox.setCurrentIndex(0)

        # Reset the path-inclusion checkboxes to the user's configured
        # defaults (Settings -> Preferences). The factory defaults declared
        # in register_widgets.IN_PATH_FIELDS act as the fallback for first-time users.
        self._apply_pref_defaults()
        self._rebuild_classification_order(list(unified_entry.DEFAULT_PATH_ORDER))

        self._additional_types_list.clear()
        self.ui.dcc_path_lineEdit.clear()
        self.ui.engine_path_lineEdit.clear()

        self._clear_row_layout(self._materials_rows_layout)
        self._clear_row_layout(self._dyes_rows_layout)
        self._clear_row_layout(self._decals_rows_layout)
        self._clear_row_layout(self._dcc_tex_rows_layout)
        self._clear_row_layout(self._engine_tex_rows_layout)
        self._clear_row_layout(self._sockets_rows_layout)

        # Reset preview info panel
        self.ui.info_thumbnail_label.setText('No Image')
        self.ui.info_thumbnail_label.setPixmap(qtgui.QPixmap())
        self.ui.info_name_label.setText('Asset Name:')
        self.ui.info_category_label.setText('Asset Category:')
        self.ui.info_variant_label.setText('Variant Of:')
        self.ui.info_path_label.setText('Asset Path:')
        self.ui.info_id_label.setText('Asset Id:')

        # Cleared form is now the new clean baseline so freshly typed
        # input on a brand-new asset still flips the dirty flag.
        self._capture_form_baseline()

    def _open_modify_data(self):
        """
        Open the Modify Asset Data dialog for the category being browsed.

        The dialog edits one category's sub-category and faction lists, so it
        needs a category to work on. Falls back to the combobox text when
        ``_current_category`` has not been set yet, which is the case until the
        user picks something after the window opens.
        """

        from mca.common.tools.assetregister import modify_asset_data

        category = self._current_category or self.ui.category_comboBox.currentText()
        if not category:
            messages.info_message('Modify Asset Data',
                                  'Pick a category before modifying its data.')
            return

        try:
            # Held on self so the window is not garbage collected the moment
            # this method returns.
            self._modify_data_window = modify_asset_data.ModifyAssetPathsUI(
                category, parent=self)
        except ValueError as exc:
            logger.warning('Could not open Modify Asset Data: %s', exc)
            messages.error_message('Modify Asset Data', str(exc))

    # --- Helper actions ---------------------------------------------------- #

    def _add_additional_type(self):
        """Add a type from the line edit to the additional types list."""

        text = self._add_type_lineEdit.text().strip()
        if text:
            self._additional_types_list.addItem(text)
            self._add_type_lineEdit.clear()
            self._update_auto_paths()

    def _remove_additional_type(self):
        """Remove the selected type from the additional types list."""

        row = self._additional_types_list.currentRow()
        if row >= 0:
            self._additional_types_list.takeItem(row)
            self._update_auto_paths()

    def _add_new_sub_category(self):
        """Prompt for a new sub-category and add to combobox + config."""

        category = self.ui.category_comboBox.currentText()
        if not category:
            return
        text, ok = qtwidgets.QInputDialog.getText(self, 'Add Sub Category', 'New sub-category name:')
        if not ok or not text.strip():
            return
        text = text.strip()
        if self._asset_paths_data:
            cat_data = self._asset_paths_data.get_category_data(category)
            if cat_data:
                cat_data.add_subcategory(text)
                self._asset_paths_data.save()
                self._asset_data_dirty = True
        # Add to the combobox and select it
        if self.ui.sub_category_comboBox.findText(text) < 0:
            self.ui.sub_category_comboBox.addItem(text)
        self.ui.sub_category_comboBox.setCurrentText(text)

    def _add_new_faction(self):
        """Prompt for a new faction and add to combobox + config."""

        category = self.ui.category_comboBox.currentText()
        if not category:
            return
        text, ok = qtwidgets.QInputDialog.getText(self, 'Add Faction', 'New faction name:')
        if not ok or not text.strip():
            return
        text = text.strip()
        if self._asset_paths_data:
            cat_data = self._asset_paths_data.get_category_data(category)
            if cat_data:
                cat_data.add_faction(text)
                self._asset_paths_data.save()
                self._asset_data_dirty = True
        if self.ui.faction_comboBox.findText(text) < 0:
            self.ui.faction_comboBox.addItem(text)
        self.ui.faction_comboBox.setCurrentText(text)

    def _add_new_skeleton(self):
        """Prompt for a new skeleton and add to combobox + global config."""

        text, ok = qtwidgets.QInputDialog.getText(self, 'Add Skeleton', 'New skeleton name:')
        if not ok or not text.strip():
            return
        text = text.strip()
        if self._global_data:
            self._global_data.add_skeleton(text)
            self._asset_paths_data.save()
            self._asset_data_dirty = True
        if self.ui.skeleton_comboBox.findText(text) < 0:
            self.ui.skeleton_comboBox.addItem(text)
        self.ui.skeleton_comboBox.setCurrentText(text)

    def _add_new_body_type(self):
        """Prompt for a new body type + skeleton mapping and add to config."""

        text, ok = qtwidgets.QInputDialog.getText(
            self, 'Add Body Type', 'New body type name:')
        if not ok or not text.strip():
            return
        text = text.strip()

        # Ask which skeleton this body type uses
        skeleton, ok2 = qtwidgets.QInputDialog.getItem(
            self, 'Body Type Skeleton',
            f'Which skeleton does "{text}" use?',
            self._global_data.skeletons if self._global_data else [],
            editable=True,
        )
        if not ok2:
            return

        if self._global_data:
            self._global_data.add_body_type(text, skeleton)
            self._asset_paths_data.save()
            self._asset_data_dirty = True
        if self.ui.body_type_comboBox.findText(text) < 0:
            self.ui.body_type_comboBox.addItem(text)
        self.ui.body_type_comboBox.setCurrentText(text)

    def _add_new_slot(self):
        """Prompt for a new gear slot and add to combobox + global config."""

        text, ok = qtwidgets.QInputDialog.getText(
            self, 'Add Slot', 'New slot name:')
        if not ok or not text.strip():
            return
        text = text.strip()
        if self._global_data:
            self._global_data.add_slot(text)
            self._asset_paths_data.save()
            self._asset_data_dirty = True
        if self.ui.slot_comboBox.findText(text) < 0:
            self.ui.slot_comboBox.addItem(text)
        self.ui.slot_comboBox.setCurrentText(text)

    def _remove_current_slot(self):
        """
        Remove the currently selected slot from the global config.

        The "None" sentinel item is the unset value, not a slot — refuse
        to remove it. Confirms with the user since this affects shared
        config visible to every other artist.
        """

        slot = self.ui.slot_comboBox.currentText()
        if not slot or slot == 'None':
            messages.info_message(
                'Remove Slot',
                'Select a slot (other than "None") to remove.')
            return

        result = messages.question_message(
            'Remove Slot',
            f'Remove slot "{slot}" from the global slot list?\n'
            'This affects every artist using this config.')
        if result != 'Yes':
            return

        if self._global_data:
            self._global_data.remove_slot(slot)
            self._asset_paths_data.save()
            self._asset_data_dirty = True
        idx = self.ui.slot_comboBox.findText(slot)
        if idx >= 0:
            self.ui.slot_comboBox.removeItem(idx)
        self.ui.slot_comboBox.setCurrentIndex(0)

    def _add_new_category(self):
        """
        Prompt for a new top-level category and bootstrap its registry.

        Writes an empty category stub to ``asset_data.config`` and creates
        an empty ``.alist`` registry file on disk so the new category can be
        populated with assets right away. The prompt includes an "Is Gear"
        checkbox so new gear-system categories start correctly flagged.
        """

        # Custom dialog with a name field + "Is Gear" checkbox. QInputDialog
        # only supports a single line edit, so we build a small dialog.
        dialog = qtwidgets.QDialog(self)
        dialog.setWindowTitle('Add Category')
        layout = qtwidgets.QVBoxLayout(dialog)

        layout.addWidget(qtwidgets.QLabel('New category name:'))
        name_edit = qtwidgets.QLineEdit()
        layout.addWidget(name_edit)

        is_gear_check = qtwidgets.QCheckBox('Is Gear')
        is_gear_check.setToolTip(
            'Mark this category as part of the gear system. '
            'Gear categories prefix all asset paths with "Gear/".')
        layout.addWidget(is_gear_check)

        buttons = qtwidgets.QDialogButtonBox(
            qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != qtwidgets.QDialog.Accepted:
            return
        text = name_edit.text().strip()
        if not text:
            return
        is_gear = is_gear_check.isChecked()

        if not self._asset_paths_data:
            messages.info_message('Error', 'Asset data is not loaded.')
            return
        if text in self._asset_paths_data.categories_names:
            messages.info_message(
                'Duplicate Category',
                f'Category "{text}" already exists.')
            return

        # Seed the category stub and persist it so later sessions see it.
        added = self._asset_paths_data.add_category(text, is_gear=is_gear)
        if not added:
            messages.info_message('Error', f'Could not add category "{text}".')
            return
        self._asset_paths_data.save()
        self._asset_data_dirty = True

        # And declare it in the project's categories.json, which is what every tool reads the
        # registry through. Nothing in the framework wrote that file - the migration did, once -
        # so a category added here existed in asset_data.config and nowhere else, and every
        # asset registered into it was written to disk and then loaded by nothing at all.
        asset_manager.declare_category(text)

        # An empty .alist as well, so the tree has a file to read rather than a gap.
        new_registry = unified_registry.UnifiedAssetRegistry({}, category_name=text)
        new_registry.save()

        # Refresh the category combobox and select the new entry.
        self._populate_categories()
        idx = self.ui.category_comboBox.findText(text)
        if idx >= 0:
            self.ui.category_comboBox.setCurrentIndex(idx)
        logger.info(f'Added new asset category: {text}')


    # --- Utility ----------------------------------------------------------- #


    def _open_preferences_dialog(self):
        """Show the preferences dialog and re-apply defaults on accept."""

        dialog = register_prefs.PreferencesDialog(self.settings, parent=self)
        if dialog.exec_() == qtwidgets.QDialog.Accepted:
            # Re-read every pref-driven checkbox so the change shows up
            # immediately on the open form (rather than only on the next
            # Clear / new asset).
            self._apply_pref_defaults()

    def _apply_pref_defaults(self):
        """
        Apply user-configured default checkbox states to the form.

        Reads every entry in ``register_widgets.IN_PATH_FIELDS`` plus the workflow
        defaults out of QSettings (with the original hardcoded values as
        the fallback) and writes them onto the live form widgets. Safe
        to call multiple times — each invocation is idempotent.
        """

        # Map field_key -> the corresponding live "In Path" checkbox on
        # the form. The additional_types case lives outside
        # _classification_rows because it isn't a draggable row, so it's
        # handled by directly referencing the widget.
        widget_map = {
            'subtype': self.ui.subtype_in_path_checkBox,
            'faction': self.ui.faction_in_path_checkBox,
            'gender': self.ui.gender_in_path_checkBox,
            'asset_type': self.ui.asset_type_in_path_checkBox,
            'skeleton': self.ui.skeleton_in_path_checkBox,
            'body_type': self.ui.body_type_in_path_checkBox,
            'additional_types': self.ui.additional_types_in_path_checkBox,
        }
        for field_key, _label, factory_default in register_widgets.IN_PATH_FIELDS:
            checkbox = widget_map.get(field_key)
            if checkbox is None:
                continue
            stored = self.settings.value(
                register_widgets.in_path_pref_key(field_key), factory_default)
            checkbox.setChecked(register_widgets.to_bool(stored, factory_default))

        self.ui.p4_submit_checkBox.setChecked(
            register_widgets.to_bool(
                self.settings.value(register_widgets.PREF_KEY_AUTO_SUBMIT, True), True))
        self.ui.create_folders_checkBox.setChecked(
            register_widgets.to_bool(
                self.settings.value(register_widgets.PREF_KEY_CREATE_FOLDERS, True), True))

    # --- Settings persistence ---------------------------------------------- #

    def _save_settings(self):
        """Save splitter positions and geometry to QSettings."""

        self.settings.setValue('main_splitter', self.ui.main_splitter.saveState())
        self.settings.setValue('left_splitter', self.ui.left_splitter.saveState())
        self.settings.setValue('vertical_splitter', self.ui.vertical_splitter.saveState())
        self.settings.setValue('preview_splitter', self.ui.preview_splitter.saveState())
        # Remember the last-selected category so the next launch lands on
        # the user's working area instead of the alphabetical first entry.
        category = self.ui.category_comboBox.currentText()
        if category:
            self.settings.setValue(register_widgets.PREF_KEY_LAST_CATEGORY, category)

    def _restore_settings(self):
        """Restore splitter positions and geometry from QSettings."""

        state = self.settings.value('main_splitter')
        if state:
            self.ui.main_splitter.restoreState(state)

        state = self.settings.value('left_splitter')
        if state:
            self.ui.left_splitter.restoreState(state)

        state = self.settings.value('vertical_splitter')
        if state:
            self.ui.vertical_splitter.restoreState(state)

        state = self.settings.value('preview_splitter')
        if state:
            self.ui.preview_splitter.restoreState(state)

    def closeEvent(self, event):
        """Save all layout settings before closing.

        Prompts to save unsaved form edits first; Cancel aborts the
        close so the user keeps their work. After the prompt resolves,
        layout settings get persisted and any pending asset_data.config
        edits flush as a safety net so the file doesn't sit
        checked-out in the user's workspace indefinitely.
        """

        action = self._prompt_save_if_dirty('closing the window')
        if action == 'cancel':
            event.ignore()
            return

        self._save_settings()
        if self._asset_data_dirty:
            cfg_path = self._asset_data_config_path()
            if cfg_path and os.path.exists(cfg_path):
                try:
                    self._run_threaded_p4_submit(
                        [cfg_path],
                        'AssetRegister: asset_data.config update')
                    self._asset_data_dirty = False
                except Exception as err:
                    logger.exception(
                        f'asset_data.config submit on close failed: {err}')
        self._teardown_classification_list()
        super().closeEvent(event)


    def _block_signals(self, block):
        """
        Block or unblock signals on all comboboxes to prevent cascade loops.

        :param bool block: True to block, False to unblock.
        """

        self.ui.category_comboBox.blockSignals(block)
        self.ui.sub_category_comboBox.blockSignals(block)
        self.ui.faction_comboBox.blockSignals(block)
        self.ui.gender_comboBox.blockSignals(block)
        self.ui.asset_type_comboBox.blockSignals(block)
        self.ui.skeleton_comboBox.blockSignals(block)
        self.ui.body_type_comboBox.blockSignals(block)
        self.ui.built_for_list.blockSignals(block)
        self.ui.variant_of_comboBox.blockSignals(block)
        self.ui.slot_comboBox.blockSignals(block)
        self.ui.name_lineEdit.blockSignals(block)
        self.ui.gear_root_lineEdit.blockSignals(block)

    def _populate_variant_of(self):
        """
        Fill the Variant Of picker with the characters that can be a base, and
        show the row only for Characters.

        Two characters are excluded: this one, which cannot be its own base, and
        any character that is already a variant, because a chain would leave the
        Summoner unable to say what the original body was.

        Entries are labelled by display name but carry the asset id, which is
        what gets stored - character names are not unique in this depot, and a
        variant resolving to the wrong base would swap in the wrong body.
        """

        widget = self.ui.variant_of_comboBox
        is_character = self.ui.category_comboBox.currentText() == 'Characters'
        widget.setVisible(is_character)
        self.ui.variant_of_label.setVisible(is_character)
        if not is_character:
            return

        was_blocked = widget.signalsBlocked()
        widget.blockSignals(True)
        try:
            current = widget.currentData()
            widget.clear()
            widget.addItem('None', '')
            own_id = (self._current_entry.asset_id if getattr(self, '_current_entry', None)
                      else '')
            registry = unified_registry.UnifiedAssetRegistry.load('Characters', create=True)
            entries = sorted(registry.get_asset_entries() if registry else [],
                             key=lambda e: (e.name or '').lower())
            for entry in entries:
                if entry.asset_id == own_id or getattr(entry, 'variant_of', ''):
                    continue
                widget.addItem('{} ({})'.format(entry.name, entry.asset_id), entry.asset_id)
            if current:
                index = widget.findData(current)
                widget.setCurrentIndex(index if index >= 0 else 0)
        finally:
            widget.blockSignals(was_blocked)

    def _select_variant_of(self, asset_id):
        """
        Point the Variant Of picker at a base character.

        :param str asset_id: The base character's asset id, or '' for none.
        """

        widget = self.ui.variant_of_comboBox
        index = widget.findData(str(asset_id or ''))
        widget.setCurrentIndex(index if index >= 0 else 0)

    def _collect_variant_of(self):
        """
        Read the base character the form names.

        :return: The base character's asset id, or '' for a base character.
        :rtype: str
        """

        if self.ui.category_comboBox.currentText() != 'Characters':
            return ''
        return self.ui.variant_of_comboBox.currentData() or ''

    def _collect_built_for(self):
        """
        Read the parent or parents the form names.

        Returns a plain string for a single parent so entries keep the shape
        they have always had, and a list only when the gear is genuinely worn
        by more than one character. Nothing selected means a parent asset.

        Order follows the list, not the order the user clicked: the stored
        ``built_for`` is a set of parents, and the first one is only ever read
        as "any parent", never as a privileged one.

        :return: Parent character name, list of names, or '' for a parent asset.
        :rtype: str or list[str]
        """

        widget = self.ui.built_for_list
        names = [widget.item(row).text() for row in range(widget.count())
                 if widget.item(row).isSelected() and widget.item(row).text()]
        if not names:
            return ''
        return names[0] if len(names) == 1 else names

    def _select_built_for(self, names):
        """
        Select the parent rows matching the given names.

        :param list[str] names: Character display names to select.
        """

        wanted = {str(n).lower() for n in (names or [])}
        widget = self.ui.built_for_list
        was_blocked = widget.signalsBlocked()
        widget.blockSignals(True)
        try:
            widget.clearSelection()
            for row in range(widget.count()):
                item = widget.item(row)
                if item.text().lower() in wanted:
                    item.setSelected(True)
        finally:
            widget.blockSignals(was_blocked)
        self._on_built_for_changed()

    def _set_combobox_text(self, combobox, text):
        """
        Set a combobox to a specific text value, adding it if needed.

        :param QComboBox combobox: The combobox to update.
        :param str text: The text to select.
        """

        if not text:
            combobox.setCurrentIndex(0)
            return

        idx = combobox.findText(text)
        if idx >= 0:
            combobox.setCurrentIndex(idx)
        else:
            # Add the value if it doesn't exist (handles legacy data)
            combobox.addItem(text)
            combobox.setCurrentIndex(combobox.count() - 1)
