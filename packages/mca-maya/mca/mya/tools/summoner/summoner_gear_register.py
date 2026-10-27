"""
Registration dialog for adding new gear entries to the asset list.

Allows artists to register gear items (armor, weapons, body parts, etc.)
by selecting a character from the tree, choosing a slot, and typing a name.
The engine path and content path auto-generate from these fields, matching
the layout of the existing Model Shop Register Asset dialog.

Requires: mca.common.assetlist, mca.common.pyqt
"""

# System global imports
import os

# MCA python imports
from mca.common import log
from mca.common.pyqt.pygui import qtwidgets, qtcore, qtgui
from mca.common.pyqt import common_windows, messages
from mca.common.assetlist import get_asset_manager, unified_entry, unified_registry
from mca.common.startup.configs import consts
from mca.common.utils import strings

logger = log.MCA_LOGGER

#: Where gear lands in the engine's content tree, under AutoGen.
#:
#: Built from the project rather than written down: the engine content root is
#: per-project, so a name in the source is wrong for every project but one. Set
#: MCA_ENGINE_PATH_ROOT to override it outright.
def _engine_path_root():
    """
    :return: The engine content root for this project's gear.
    :rtype: str
    """

    override = os.getenv('MCA_ENGINE_PATH_ROOT')
    if override:
        return override.rstrip('/')
    project = os.getenv(consts.MCA_PROJECT_NAME) or 'Game'
    return '/Game/{}/Characters/AutoGen'.format(project)


ENGINE_PATH_ROOT = _engine_path_root()


class NewGearRegister(common_windows.MCAMainWindow):
    """
    Dialog for registering a new gear asset entry.

    Two-panel layout mirroring the Model Shop Register Asset dialog:
    left panel shows a character tree for selecting which character the gear
    is built for, right panel has the gear fields with an auto-generated
    engine path at the bottom.
    """

    VERSION = '1.1.0'

    # Signal emitted after a successful save so the parent tree can refresh.
    gear_registered = qtcore.Signal()

    def __init__(self, gear_category, parent=None):
        super().__init__(title='Register New Gear',
                         ui_path=None,
                         show_window=True,
                         version=self.VERSION,
                         parent=parent)

        self.gear_category = gear_category
        self.selected_character = None

        # Whether the artist has manually overridden the engine path.
        self._path_override = False

        self.setMinimumSize(720, 480)

        self._build_ui()
        self._populate_fields()

        # --- Signals -------------------------------------------------------- #
        self.ui_save_btn.clicked.connect(self._save_gear)
        self.ui_cancel_btn.clicked.connect(self.close)
        self.ui_name_edit.textChanged.connect(self._on_fields_changed)
        self.ui_slot_combo.currentIndexChanged.connect(self._on_fields_changed)
        self.ui_clear_btn.clicked.connect(self._clear_character)
        self.ui_set_path_btn.clicked.connect(self._set_path_override)
        self.char_tree.itemSelectionChanged.connect(self._on_character_selected)

    # --- UI construction ---------------------------------------------------- #

    def _build_ui(self):
        """
        Builds the two-panel registration layout programmatically.

        Left panel: character tree for selecting the built_for character.
        Right panel: gear fields with auto-generated engine path at bottom.
        """

        # Top-level horizontal splitter: tree | fields.
        h_layout = qtwidgets.QHBoxLayout()

        # ----- Left panel: Character tree ----------------------------------- #
        left_frame = qtwidgets.QFrame()
        left_frame.setFrameShape(qtwidgets.QFrame.StyledPanel)
        left_frame.setMinimumWidth(200)
        left_layout = qtwidgets.QVBoxLayout(left_frame)

        left_label = qtwidgets.QLabel('Built For:')
        left_label.setMaximumHeight(20)
        left_layout.addWidget(left_label)

        self.char_tree = qtwidgets.QTreeWidget()
        self.char_tree.setHeaderLabels(['Characters'])
        left_layout.addWidget(self.char_tree)

        self.ui_clear_btn = qtwidgets.QPushButton('Clear Selection')
        left_layout.addWidget(self.ui_clear_btn)

        h_layout.addWidget(left_frame)

        # ----- Right panel: fields ------------------------------------------ #
        right_frame = qtwidgets.QFrame()
        right_frame.setMinimumWidth(400)
        right_layout = qtwidgets.QVBoxLayout(right_frame)

        # Row helper — creates a label + widget row matching the Model Shop style.
        def add_row(label_text, widget, extra_widget=None):
            """Adds a horizontal row with a fixed-width label and a widget."""
            row = qtwidgets.QHBoxLayout()
            row.setContentsMargins(2, 2, 2, 2)
            lbl = qtwidgets.QLabel(label_text)
            lbl.setMinimumWidth(90)
            row.addWidget(lbl)
            row.addWidget(widget)
            if extra_widget:
                row.addWidget(extra_widget)
            right_layout.addLayout(row)

        # Category (locked — already determined by the gear tab).
        self.ui_category_edit = qtwidgets.QLineEdit(self.gear_category)
        self.ui_category_edit.setReadOnly(True)
        self.ui_category_edit.setStyleSheet('color: gray;')
        add_row(' Category:', self.ui_category_edit)

        # Slot dropdown.
        self.ui_slot_combo = qtwidgets.QComboBox()
        self.ui_slot_combo.setEditable(True)
        add_row(' Slot:', self.ui_slot_combo)

        # Faction (auto-filled from character, editable override).
        self.ui_faction_edit = qtwidgets.QLineEdit()
        self.ui_faction_edit.setPlaceholderText('(auto-filled from character)')
        add_row(' Faction:', self.ui_faction_edit)

        # Gear Name.
        self.ui_name_edit = qtwidgets.QLineEdit()
        self.ui_name_edit.setPlaceholderText('e.g. SK_Fancy_Chest_Plate')
        add_row(' Gear Name:', self.ui_name_edit)

        # Skeleton (auto-filled from character, editable override).
        self.ui_skeleton_edit = qtwidgets.QLineEdit()
        self.ui_skeleton_edit.setPlaceholderText('(auto-filled from character)')
        add_row(' Skeleton:', self.ui_skeleton_edit)

        # Description (optional, small).
        self.ui_desc_edit = qtwidgets.QTextEdit()
        self.ui_desc_edit.setMaximumHeight(60)
        self.ui_desc_edit.setPlaceholderText('Description (optional)')
        add_row(' Description:', self.ui_desc_edit)

        # Sockets — only visible for Weapons category.
        self.ui_sockets_edit = qtwidgets.QLineEdit()
        self.ui_sockets_edit.setPlaceholderText('e.g. weapon_r, spine_04 (comma-separated)')
        self._sockets_label = qtwidgets.QLabel(' Sockets:')
        self._sockets_label.setMinimumWidth(90)
        self._sockets_row = qtwidgets.QHBoxLayout()
        self._sockets_row.setContentsMargins(2, 2, 2, 2)
        self._sockets_row.addWidget(self._sockets_label)
        self._sockets_row.addWidget(self.ui_sockets_edit)
        right_layout.addLayout(self._sockets_row)

        # Only show sockets row for Weapons.
        is_weapons = self.gear_category == 'Weapons'
        self._sockets_label.setVisible(is_weapons)
        self.ui_sockets_edit.setVisible(is_weapons)

        # ----- Engine Path box (framed, like the Model Shop Asset Path) ----- #
        path_frame = qtwidgets.QFrame()
        path_frame.setFrameShape(qtwidgets.QFrame.StyledPanel)
        path_inner = qtwidgets.QVBoxLayout(path_frame)
        path_inner.setContentsMargins(4, 4, 4, 4)

        path_label = qtwidgets.QLabel(' Engine Path:')
        path_inner.addWidget(path_label)

        path_edit_row = qtwidgets.QHBoxLayout()
        self.ui_engine_path_edit = qtwidgets.QLineEdit()
        self.ui_engine_path_edit.setReadOnly(True)
        self.ui_set_path_btn = qtwidgets.QPushButton(' Set Path ')
        path_edit_row.addWidget(self.ui_engine_path_edit)
        path_edit_row.addWidget(self.ui_set_path_btn)
        path_inner.addLayout(path_edit_row)

        right_layout.addWidget(path_frame)

        # Spacer to push buttons to the bottom.
        right_layout.addStretch()

        # ----- Save / Cancel buttons ---------------------------------------- #
        btn_layout = qtwidgets.QHBoxLayout()
        self.ui_save_btn = qtwidgets.QPushButton('Save New Gear')
        self.ui_save_btn.setSizePolicy(qtwidgets.QSizePolicy.Expanding,
                                       qtwidgets.QSizePolicy.Fixed)
        self.ui_cancel_btn = qtwidgets.QPushButton('Cancel')
        self.ui_cancel_btn.setSizePolicy(qtwidgets.QSizePolicy.Expanding,
                                         qtwidgets.QSizePolicy.Fixed)
        btn_layout.addWidget(self.ui_save_btn)
        btn_layout.addWidget(self.ui_cancel_btn)
        right_layout.addLayout(btn_layout)

        h_layout.addWidget(right_frame)
        self.main_layout.addLayout(h_layout)

    # --- Population --------------------------------------------------------- #

    def _populate_fields(self):
        """
        Pre-populate the character tree and slot combobox with known data.
        """

        self._populate_character_tree()
        self._populate_slots()

    def _populate_character_tree(self):
        """
        Fills the left tree with all registered characters.

        Uses the primary asset registry (Characters category) so the
        list stays in sync with the Model Shop.
        """

        self.char_tree.clear()

        # The asset manager is the single source of truth post-migration; it
        # reads the same unified files this dialog writes to.
        manager = get_asset_manager()
        records = sorted(manager.iter_category('Characters'),
                         key=lambda r: (r.name or '').lower())

        for record in records:
            item = qtwidgets.QTreeWidgetItem(self.char_tree)
            item.setText(0, record.name)
            # Store the record so we can read faction, skeleton, etc.
            item.setData(0, qtcore.Qt.UserRole, record)

    def _populate_slots(self):
        """
        Pre-populate the slot combobox with known slots from existing gear
        entries plus sensible defaults for this gear category.
        """

        known_slots = set()
        manager = get_asset_manager()
        for record in manager.iter_category(self.gear_category):
            if record.slot:
                known_slots.add(record.slot)

        # Add sensible defaults based on gear category.
        default_slots = {
            'Armor': ['Chest', 'Belt', 'Pauldrons', 'LoinCloth', 'BackPack', 'Shield'],
            'Body': ['Body', 'Head', 'Hair'],
            'Weapons': ['WeaponRight', 'WeaponLeft'],
            'Heads': ['Default'],
            'Faces': ['Decals'],
        }
        category_defaults = default_slots.get(self.gear_category, ['Default'])
        all_slots = sorted(known_slots | set(category_defaults))
        self.ui_slot_combo.addItems(all_slots)

    # --- Character selection ------------------------------------------------ #

    def _on_character_selected(self):
        """
        Fires when the artist clicks a character in the tree.

        Auto-fills Faction, Skeleton, and rebuilds the engine path.
        """

        current = self.char_tree.currentItem()
        if not current:
            return

        asset_entry = current.data(0, qtcore.Qt.UserRole)
        if not asset_entry:
            return

        self.selected_character = asset_entry

        # Auto-fill faction from the character entry.
        faction = asset_entry.faction or ''
        if faction and faction != 'None':
            self.ui_faction_edit.setText(faction)

        # Auto-fill skeleton — check gear Characters.alist first for a skeleton
        # value, then fall back to the character's archetype field.
        self._auto_fill_skeleton(asset_entry)

        # Rebuild the engine path from the new character selection.
        self._update_engine_path()

    def _auto_fill_skeleton(self, asset_entry):
        """
        Attempts to find the skeleton name for the selected character.

        Checks the gear Characters.alist data first (which stores an explicit
        skeleton field), then falls back to the primary registry archetype.

        :param AssetEntry asset_entry: The selected character entry.
        """

        manager = get_asset_manager()

        # The gear Characters.alist may have an explicit skeleton field.
        char_record = manager.get_record_by_name(asset_entry.name)
        if char_record and char_record.skeleton:
            self.ui_skeleton_edit.setText(char_record.skeleton)
            return

        # Fall back to archetype from the primary registry.
        archetype = asset_entry.archetype
        if archetype:
            self.ui_skeleton_edit.setText(archetype)
            return

        # No skeleton info found — leave the field for manual entry.
        self.ui_skeleton_edit.setPlaceholderText('Enter skeleton name')

    def _clear_character(self):
        """
        Clears the character selection and resets auto-filled fields.
        """

        self.char_tree.clearSelection()
        self.selected_character = None
        self.ui_faction_edit.clear()
        self.ui_skeleton_edit.clear()
        self._update_engine_path()

    # --- Engine path auto-generation ---------------------------------------- #

    def _on_fields_changed(self, *args):
        """
        Called when name or slot changes.  Rebuilds the engine path unless
        the artist has manually overridden it.
        """

        if not self._path_override:
            self._update_engine_path()

    def _update_engine_path(self):
        """
        Builds the engine path from the current field values.

        Pattern: <ENGINE_PATH_ROOT>/{Character}/{Category}/{Name}

        If no character is selected, the character segment is omitted so the
        artist still sees a partial preview.
        """

        character_name = ''
        if self.selected_character:
            character_name = self.selected_character.name

        gear_name = self.ui_name_edit.text().strip()

        # Build segments, filtering out empty parts.
        segments = [ENGINE_PATH_ROOT]
        if character_name:
            segments.append(character_name)
        segments.append(self.gear_category)
        if gear_name:
            segments.append(gear_name)

        path = '/'.join(segments)
        self.ui_engine_path_edit.setText(path)

    def _set_path_override(self):
        """
        Unlocks the engine path field so the artist can type a custom path.

        Once clicked, auto-generation is disabled until the dialog is reopened.
        """

        self._path_override = True
        self.ui_engine_path_edit.setReadOnly(False)
        self.ui_engine_path_edit.setFocus()
        logger.info('Engine path unlocked for manual editing.')

    # --- Save --------------------------------------------------------------- #

    def _save_gear(self):
        """
        Validates input and saves the new gear entry to the .alist file.
        """

        asset_name = self.ui_name_edit.text().strip()
        if not asset_name:
            messages.info_message(title='Missing Name', text='Please enter a gear name.')
            return

        # Sanitize the name and generate the asset ID.
        asset_name = strings.remove_chars(asset_name, chars='[^a-zA-Z0-9_]+')
        asset_id = asset_name.lower()
        if not asset_id:
            return

        # Check for duplicates in the gear registry.
        gear_data = unified_registry.UnifiedAssetRegistry.load(self.gear_category)
        if gear_data and gear_data.get_asset_entry(asset_id, skip_dialog=True):
            messages.info_message(
                title='Already Exists',
                text=f'"{asset_name}" already exists in {self.gear_category}!\n'
                     f'Please choose another name.',
            )
            return

        # Build a confirmation summary for the artist.
        built_for = self.selected_character.name if self.selected_character else ''
        slot_text = self.ui_slot_combo.currentText()
        engine_path = self.ui_engine_path_edit.text()

        result = messages.question_message(
            title='Register New Gear',
            text=f'Register new gear asset?\n\n'
                 f'Name: {asset_name}\n'
                 f'Category: {self.gear_category}\n'
                 f'Slot: {slot_text}\n'
                 f'Built For: {built_for}\n'
                 f'Engine Path: {engine_path}',
        )
        if result != 'Yes':
            return

        # Parse comma-separated sockets (Weapons only).
        sockets_text = self.ui_sockets_edit.text().strip()
        attach_sockets = None
        if sockets_text:
            attach_sockets = [s.strip() for s in sockets_text.split(',') if s.strip()]

        # Content path mirrors engine path without the leading slash.
        content_path = engine_path.lstrip('/')

        # Create the gear entry with all collected fields.
        new_entry = unified_entry.UnifiedAssetEntry.create(
            asset_name=asset_name,
            category=self.gear_category,
            slot=slot_text,
            subtype=slot_text,
            built_for=built_for,
            faction=self.ui_faction_edit.text().strip(),
            path=content_path,
            engine_path=engine_path,
            skeleton=self.ui_skeleton_edit.text().strip(),
            description=self.ui_desc_edit.toPlainText().strip(),
            asset_id=asset_id,
            attach_sockets=attach_sockets,
        )

        # Save to the gear .alist file.
        if not gear_data:
            # First entry in this category — create a new registry.
            gear_data = unified_registry.UnifiedAssetRegistry({}, category_name=self.gear_category)

        gear_data.add_asset_entry(new_entry)
        gear_data.save()

        # Force AssetManager reload so the new entry shows up immediately.
        get_asset_manager(force_reload=True)

        logger.info('Registered new gear asset: "%s" in %s', asset_name, self.gear_category)
        self.gear_registered.emit()
        self.close()
