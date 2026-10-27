"""
Gear tree widget for the Summoner tool.

Displays gear assets in a three-level hierarchy:
  Level 0: Character name (e.g., "Hyena")
  Level 1: Slot (e.g., "Chest", "WeaponRight")
  Level 2: Gear item (e.g., "SK_Base_Breast_Plate_C")

Queries the AssetManager for records matching a gear category (Armor, Body,
Weapons, etc.) and groups them by the ``built_for`` character name and ``slot``.
"""

# System global imports
import os
from collections import defaultdict

# software specific imports
# MCA python imports
from mca.common import log
from mca.common.assetlist import get_asset_manager, unified_registry
from mca.common.pyqt.pygui import qtwidgets, qtcore
from mca.common.pyqt import common_windows, messages
from mca.common.resources import resources

from mca.common.tools.assetregister import unified_register
from mca.mya.tools.summoner import gear_api
from mca.mya.tools.summoner import summoner_utils

logger = log.MCA_LOGGER


class GearTreeWidget(common_windows.MCAMainWindow):
    """
    Widget that displays gear items for a single gear category.

    The tree is organized as Character > Slot > Gear Item.  Selecting a leaf
    item populates the description and thumbnail panels on the right.
    Double-clicking or pressing Import brings the asset into Maya.
    """

    VERSION = '1.0.0'

    def __init__(self, gear_category, parent=None):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'summoner_gear_tree.ui')
        super().__init__(title='Summoner Gear Tree',
                         ui_path=ui_path,
                         show_window=False,
                         version=self.VERSION,
                         parent=parent)

        self.gear_category = gear_category

        # Build the tree widget and inject it into the layout placeholder.
        self.gear_tree = qtwidgets.QTreeWidget(self)
        self.gear_tree.setHeaderLabels([gear_category])
        self.ui.gear_tree_layout.addWidget(self.gear_tree)

        self.selected_record = None

        self._populate_tree()

        # --- Signals -------------------------------------------------------- #
        self.gear_tree.setContextMenuPolicy(qtcore.Qt.CustomContextMenu)

        self.gear_tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.gear_tree.itemDoubleClicked.connect(self._equip_clicked)
        self.gear_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.ui.import_pushButton.clicked.connect(self._import_clicked)
        self.ui.import_pushButton.setToolTip(
            'Import the gear on its own, without putting it on a character.\n'
            'Double-click a gear item to equip it onto the character in the scene.')
        self.ui.model_checkBox.clicked.connect(self._model_chbx)
        self.ui.sk_checkBox.clicked.connect(self._sk_chbx)
        self.ui.reg_new_pushButton.clicked.connect(self._register_new_gear)
        self.ui.remove_pushButton.clicked.connect(self._remove_entry)

    # --- Checkbox mutual exclusion ------------------------------------------ #

    def _model_chbx(self):
        """Ensures only one import mode checkbox is active at a time."""

        self.ui.sk_checkBox.setChecked(False)

    def _sk_chbx(self):
        """Ensures only one import mode checkbox is active at a time."""

        self.ui.model_checkBox.setChecked(False)

    # --- Tree population ---------------------------------------------------- #

    def _populate_tree(self):
        """
        Builds the three-level tree from AssetManager gear records.

        Groups records by ``built_for`` (character) then ``slot``.
        """

        self.gear_tree.clear()
        self.selected_record = None

        gear_dict = self._get_gear_dict()
        if not gear_dict:
            return

        for character_name in sorted(gear_dict.keys()):
            slots = gear_dict[character_name]
            # Level 0: Character
            char_item = qtwidgets.QTreeWidgetItem(self.gear_tree)
            char_item.setText(0, character_name)
            char_item.setIcon(0, resources.icon(r'company_logos\default_logo.png'))
            char_item.setData(0, qtcore.Qt.UserRole, None)

            for slot_name in sorted(slots.keys()):
                records = slots[slot_name]
                # Level 1: Slot
                slot_item = qtwidgets.QTreeWidgetItem(char_item)
                slot_item.setText(0, slot_name)
                slot_item.setData(0, qtcore.Qt.UserRole, None)

                for record in records:
                    # Level 2: Gear item
                    gear_item = qtwidgets.QTreeWidgetItem(slot_item)
                    gear_item.setText(0, record.name)
                    gear_item.setIcon(0, resources.icon(r'company_logos\default_logo.png'))
                    # Store the AssetRecord on the item for easy retrieval.
                    gear_item.setData(0, qtcore.Qt.UserRole, record)

        # Select the first top-level item to populate the info panel.
        first = self.gear_tree.topLevelItem(0)
        if first:
            self.gear_tree.setCurrentItem(first)

    def _get_gear_dict(self):
        """
        Query the AssetManager and group gear records into a nested dict.

        Only records that name a parent are included; a category also holds
        plain assets (Weapons and Heads are mostly non-gear) and listing those
        here buried the actual gear under an "Unassigned" pile.

        A record can be built for several characters, so it is listed under
        each of them - that is how a shared hat shows up on both agents.
        "Unassigned" now means only one thing: gear whose ``built_for`` names a
        character the registry does not have, which is worth seeing.

        :return: ``{character_name: {slot_name: [AssetRecord, ...]}}``
        :rtype: dict
        """

        manager = get_asset_manager()
        result = defaultdict(lambda: defaultdict(list))
        folder_cache = {}

        for record in manager.iter_category(self.gear_category):
            parents = list(record.built_for_all or [])
            slot = record.slot or record.subtype or 'General'

            if not parents:
                # No parent recorded. That is usually because the record is not
                # gear at all - a category also holds plain assets - but some
                # real gear was registered without one, and hiding a piece that
                # has a Maya source file sitting on disk is what made the tree
                # disagree with the registry in the first place. So: show it,
                # under "Unassigned", where the missing parent is obvious.
                if gear_api.has_maya_source(record, folder_cache):
                    result['Unassigned'][slot].append(record)
                continue

            for character in parents:
                # A name that resolved to nothing still shows, flagged, rather
                # than vanishing from the tree.
                known = manager.get_record_by_name(character) is not None
                label = character if known else '%s (unknown)' % character
                result[label][slot].append(record)

        return dict(result)

    # --- Selection / info panel --------------------------------------------- #

    def _on_selection_changed(self):
        """
        Updates the info panel when the tree selection changes.
        """

        current = self.gear_tree.currentItem()
        if not current:
            return

        record = current.data(0, qtcore.Qt.UserRole)
        self.selected_record = record
        self._update_description(current, record)

    def _update_description(self, item, record):
        """
        Populates the description text box and clears/sets the icon.

        :param qtwidgets.QTreeWidgetItem item: Currently selected tree item.
        :param record: AssetRecord or None for non-leaf items.
        """

        if record is None:
            # Non-leaf item (character or slot heading).
            self.ui.description_textEdit.setText(item.text(0))
            self.ui.gear_icon_label.clear()
            return

        # Build a human-readable description from the record fields.
        lines = []
        lines.append(f'Name: {record.name}')
        lines.append(f'Category: {record.category}')
        if record.slot:
            lines.append(f'Slot: {record.slot}')
        if record.built_for:
            lines.append(f'Built For: {record.built_for}')
        if record.skeleton:
            lines.append(f'Skeleton: {record.skeleton}')
        if record.engine_path:
            lines.append(f'Engine Path: {record.engine_path}')
        if record.description:
            lines.append(f'\n{record.description}')
        lines.append(f'\nAsset ID: {record.asset_id}')

        self.ui.description_textEdit.setText('\n'.join(lines))

        # Clear the icon — we don't have thumbnails for gear yet.
        self.ui.gear_icon_label.clear()

    # --- Import ------------------------------------------------------------- #

    def _find_gear_fbx(self, record):
        """
        Locate the FBX file for a gear record on disk.

        Gear entries store UE engine paths, not local FBX paths.  The actual
        FBX lives in the parent character's Meshes folder.  We search there
        for files matching the gear name (with SM_ or SK_ prefix variants).

        :param AssetRecord record: The gear record to locate.
        :return: Full path to the FBX file, or None if not found.
        :rtype: str or None
        """

        manager = get_asset_manager()

        # Resolve the parent character from built_for or parent_id.
        parent = None
        if record.parent_id:
            parent = manager.get_record(record.parent_id)
        if not parent and record.built_for:
            parent = manager.get_record_by_name(record.built_for)

        if not parent or not parent.source_entry:
            return None

        parent_entry = parent.source_entry
        meshes_dir = parent_entry.models_path
        if not meshes_dir or not os.path.isdir(meshes_dir):
            return None

        gear_name = record.name

        # Check exact name first (SM_ or SK_ prefix already in name).
        for ext in ('.fbx',):
            candidate = os.path.join(meshes_dir, f'{gear_name}{ext}')
            if os.path.isfile(candidate):
                return os.path.normpath(candidate)

        # Try SM_ and SK_ prefix variants if the name doesn't already have one.
        name_lower = gear_name.lower()
        if not name_lower.startswith('sm_') and not name_lower.startswith('sk_'):
            for prefix in ('SM_', 'SK_'):
                candidate = os.path.join(meshes_dir, f'{prefix}{gear_name}.fbx')
                if os.path.isfile(candidate):
                    return os.path.normpath(candidate)

        # Fallback: scan the Meshes folder for any FBX containing the gear name.
        try:
            for filename in os.listdir(meshes_dir):
                if filename.lower().endswith('.fbx') and gear_name.lower() in filename.lower():
                    return os.path.normpath(os.path.join(meshes_dir, filename))
        except OSError:
            pass

        return None

    def _import_clicked(self):
        """
        Imports the currently selected gear item into Maya.

        Locates the FBX in the parent character's Meshes folder and imports
        it using the standard source file pipeline.
        """

        if not self.selected_record:
            logger.info('No gear item selected.')
            return

        record = self.selected_record

        fbx_path = self._find_gear_fbx(record)
        if not fbx_path:
            logger.warning(
                'Could not find FBX for gear item "%s".  '
                'Gear assets with only an engine path cannot be imported into Maya yet.',
                record.name,
            )
            return

        as_model = self.ui.model_checkBox.isChecked()

        # Import through the standard FBX pipeline.
        node_list = summoner_utils.import_source_file(fbx_path)
        if not node_list:
            logger.warning('No nodes imported from: %s', fbx_path)
            return

        # Organize imported nodes under a group.
        parentable_list, shaped_list = summoner_utils.get_imported_shape_nodes(node_list)

        import pymel.core as pm
        group = pm.group(n=record.name, em=True, w=True)
        if parentable_list:
            pm.parent(parentable_list, group)

        # Remove joints if importing as model only.
        if as_model:
            imported_joints = pm.ls(node_list, type=pm.nt.Joint)
            if imported_joints:
                pm.delete(imported_joints)

        logger.info('Imported gear asset: %s from %s', record.name, fbx_path)

    # --- Equip -------------------------------------------------------------- #

    def _equip_clicked(self, *args):
        """
        Put the selected gear on the character in the scene.

        This is the double-click behaviour: the gear is imported, its extra
        joints are merged onto the character skeleton and its skin cluster is
        moved across. Whatever already occupies the slot is swapped out.
        """

        if not self.selected_record:
            logger.info('No gear item selected.')
            return

        record = self.selected_record
        response = gear_api.equip(record.asset_id)
        if not response['ok']:
            logger.warning(response['message'])
            messages.info_message(title='Could not equip', text=response['message'])
            return

        logger.info(response['message'])

    def _unequip_clicked(self):
        """
        Take the selected gear back off the character.
        """

        if not self.selected_record:
            logger.info('No gear item selected.')
            return

        response = gear_api.unequip(asset_id=self.selected_record.asset_id)
        if not response['ok']:
            logger.warning(response['message'])
            messages.info_message(title='Could not unequip', text=response['message'])
            return

        logger.info(response['message'])

    def _show_context_menu(self, point):
        """
        Offer equip/unequip on a gear item.

        :param qtcore.QPoint point: Position the menu was asked for, in tree
            viewport coordinates.
        """

        item = self.gear_tree.itemAt(point)
        if item is None or item.data(0, qtcore.Qt.UserRole) is None:
            return

        self.gear_tree.setCurrentItem(item)
        record = self.selected_record
        if record is None:
            return

        menu = qtwidgets.QMenu(self.gear_tree)
        equip_action = menu.addAction('Equip on character')
        unequip_action = menu.addAction('Unequip')
        menu.addSeparator()
        import_action = menu.addAction('Import on its own')

        chosen = menu.exec_(self.gear_tree.viewport().mapToGlobal(point))
        if chosen == equip_action:
            self._equip_clicked()
        elif chosen == unequip_action:
            self._unequip_clicked()
        elif chosen == import_action:
            self._import_clicked()

    # --- Registration / removal --------------------------------------------- #

    def _register_new_gear(self):
        """
        Opens the unified asset registration UI for this gear category.
        """

        self._reg_window = unified_register.UnifiedRegisterUI(parent=self)
        self._reg_window.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Refresh the gear tree when the registration window closes."""

        if hasattr(self, '_reg_window') and obj is self._reg_window:
            if event.type() == qtcore.QEvent.Close:
                from mca.mya.tools.summoner.summoner_asset_tree import summoner_window
                window = summoner_window(self)
                if window is not None:
                    window.refresh_all()
                else:
                    from mca.common.assetlist import get_asset_manager
                    get_asset_manager(force_reload=True)
                    self._populate_tree()
        return super().eventFilter(obj, event)

    def _remove_entry(self):
        """
        Removes the selected gear entry from its .alist file.
        """

        if not self.selected_record:
            logger.info('No gear item selected to remove.')
            return

        record = self.selected_record
        result = messages.question_message(
            title='Remove Gear Entry',
            text=f'Remove "{record.name}" from the {self.gear_category} gear list?\n\n'
                 f'This will delete the entry from the registry.',
        )
        if result != 'Yes':
            return

        # Remove from the gear .alist file.
        gear_data = unified_registry.UnifiedAssetRegistry.load(self.gear_category)
        if gear_data:
            removed = gear_data.remove_asset_entry(record.asset_id)
            if removed:
                gear_data.save()
                # Force AssetManager reload and refresh the tree.
                get_asset_manager(force_reload=True)
                self._populate_tree()
                logger.info('Removed gear entry: %s', record.name)
            else:
                logger.warning('Could not find gear entry to remove: %s', record.asset_id)
