"""
The browse panel: the asset tree, its filters and selection handling.

Part of the Unified Asset Register, split out of ``unified_register`` so each
area of the window is readable on its own. The methods are unchanged; they run
on :class:`unified_register.UnifiedRegisterUI`, which mixes this class in, and
rely on the attributes that class builds.

:Requires: mca.common.pyqt, mca.common.assetlist
"""

# MCA python imports
from mca.common import log
from mca.common.assetlist import unified_registry
from mca.common.pyqt.pygui import qtcore, qtwidgets
from mca.common.tools.assetregister import register_widgets


logger = log.MCA_LOGGER


class TreeMixin:
    """
    The browse panel: the asset tree, its filters and selection handling.

    Mixed into :class:`unified_register.UnifiedRegisterUI`; never instantiated
    on its own.
    """

    # --- Tree management --------------------------------------------------- #

    def _refresh_tree(self):
        """Reload the asset tree for the current category.

        Preserves the user's current selection across the rebuild. Clicking
        an asset triggers ``_populate_form_from_entry`` which cascades into
        ``_on_category_changed`` and back into this method — without
        re-selecting we would clear the visible highlight on every click
        even though ``_current_entry`` is still set.
        """

        # Anchor selection on the entry itself (survives the clear/rebuild),
        # not the QTreeWidgetItem pointer (destroyed by clear).
        selected_entry = self._current_entry

        self._asset_tree.clear()
        category = self.ui.category_comboBox.currentText()
        if not category:
            return

        # create=True: a category with no assets yet is an empty tree, not a problem worth
        # a warning in the log every time the window refreshes.
        registry = unified_registry.UnifiedAssetRegistry.load(category, create=True)
        if not registry:
            self._populate_tree_filters([])
            return

        entries = registry.get_asset_entries()
        self._populate_tree_filters(entries)

        # Group entries: parents first, then gear under their built_for parent.
        # A variant is a parent by the built_for test - it is worn by nobody -
        # but it belongs under the character it restyles, so it is pulled out
        # here and nested below.
        by_id = {entry.asset_id: entry for entry in entries}
        parents = {}
        gear_entries = []
        variant_entries = []

        for entry in entries:
            base_id = getattr(entry, 'variant_of', '')
            if base_id and base_id in by_id:
                variant_entries.append(entry)
            elif entry.is_parent:
                parents[entry.name] = entry
            else:
                gear_entries.append(entry)

        # Add parent items to the tree
        parent_items = {}
        items_by_id = {}
        for name in sorted(parents.keys()):
            entry = parents[name]
            item = qtwidgets.QTreeWidgetItem(self._asset_tree)
            item.setText(0, entry.name)
            item.setText(1, entry.subtype)
            item.setText(2, entry.faction)
            item.setData(0, qtcore.Qt.UserRole, entry)
            parent_items[name] = item
            items_by_id[entry.asset_id] = item

        # Variants nest under the character they restyle. Keyed by asset id,
        # not name: character display names are not unique in this depot, and
        # nesting by name would put a variant under whichever twin happened to
        # be built last.
        for entry in sorted(variant_entries, key=lambda e: (e.name or '').lower()):
            base = by_id.get(entry.variant_of)
            base_item = items_by_id.get(entry.variant_of)
            child = (qtwidgets.QTreeWidgetItem(base_item) if base_item
                     else qtwidgets.QTreeWidgetItem(self._asset_tree))
            child.setText(0, entry.name)
            child.setText(1, entry.subtype)
            child.setText(2, entry.faction)
            child.setText(3, base.name if base else entry.variant_of)
            child.setData(0, qtcore.Qt.UserRole, entry)
            items_by_id[entry.asset_id] = child

        # Add gear items under their parent
        for entry in sorted(gear_entries, key=lambda e: e.name):
            parent_name = entry.built_for
            parent_item = parent_items.get(parent_name)
            if parent_item:
                child = qtwidgets.QTreeWidgetItem(parent_item)
            else:
                # Orphaned gear - add to root
                child = qtwidgets.QTreeWidgetItem(self._asset_tree)
            child.setText(0, entry.name)
            child.setText(1, entry.subtype)
            child.setText(2, entry.faction)
            child.setData(0, qtcore.Qt.UserRole, entry)

        self._asset_tree.expandAll()

        # Restore selection to the entry the user was editing. Match by
        # name + category (entry objects are recreated on every reload so
        # identity comparison would always miss).
        #
        # Deliberately walks topLevelItem/child indices rather than using
        # QTreeWidgetItemIterator: iterators register with the tree's
        # internal QTreeModel and must be destructed before any subsequent
        # item mutation, or Qt crashes inside
        # QTreeWidgetItemIterator::operator-- when it tries to invalidate
        # a stale iterator (see MayaCrashLog260421.1512.log). Shiboken
        # cleanup of the iterator's Python wrapper is not timely enough
        # to rely on.
        if selected_entry is not None:
            target_name = getattr(selected_entry, 'name', None)
            target_category = getattr(selected_entry, 'category', None)
            if target_name and target_category == category:
                match = self._find_tree_item_by_name(target_name)
                if match is not None:
                    self._asset_tree.setCurrentItem(match)
                    self._asset_tree.scrollToItem(match)

        # Rebuilt rows start visible; re-apply the search and dropdown filters.
        self._filter_tree()

    def _find_tree_item_by_name(self, name):
        """
        Locate a tree item by its entry's ``name`` attribute.

        Uses plain topLevelItem/child indexing so no Qt iterator is
        registered with the tree model — see the comment in
        ``_refresh_tree`` for why that matters.

        :param str name: Entry name to match.
        :return: The matching ``QTreeWidgetItem`` or ``None``.
        :rtype: QTreeWidgetItem or None
        """

        for i in range(self._asset_tree.topLevelItemCount()):
            top = self._asset_tree.topLevelItem(i)
            entry = top.data(0, qtcore.Qt.UserRole)
            if entry is not None and getattr(entry, 'name', None) == name:
                return top
            for j in range(top.childCount()):
                child = top.child(j)
                entry = child.data(0, qtcore.Qt.UserRole)
                if entry is not None and getattr(entry, 'name', None) == name:
                    return child
        return None

    def _populate_tree_filters(self, entries):
        """
        Rebuild the sub-category filter options from the loaded entries.

        Keeps the current pick when it still exists so a tree refresh after a
        save does not reset the user's view. The faction list is rebuilt
        afterwards because it depends on the sub-category pick.

        :param list entries: UnifiedAssetEntry objects behind the tree.
        """

        self._tree_entries = list(entries)
        current = self.ui.tree_subcategory_comboBox.currentText()
        subtypes = sorted({entry.subtype for entry in self._tree_entries if entry.subtype})

        self.ui.tree_subcategory_comboBox.blockSignals(True)
        self.ui.tree_subcategory_comboBox.clear()
        self.ui.tree_subcategory_comboBox.addItem(register_widgets.TREE_FILTER_ALL)
        self.ui.tree_subcategory_comboBox.addItems(subtypes)
        idx = self.ui.tree_subcategory_comboBox.findText(current)
        self.ui.tree_subcategory_comboBox.setCurrentIndex(idx if idx >= 0 else 0)
        self.ui.tree_subcategory_comboBox.blockSignals(False)

        self._populate_tree_faction_filter()

    def _populate_tree_faction_filter(self):
        """
        Rebuild the faction filter from the entries that pass the sub-category filter.

        Keeps the current pick when it is still offered, otherwise falls back
        to "All" so the tree never filters on a faction that cannot match.
        """

        subtype = self.ui.tree_subcategory_comboBox.currentText()
        current = self.ui.tree_faction_comboBox.currentText()
        factions = sorted({
            entry.faction for entry in self._tree_entries
            if entry.faction and (subtype == register_widgets.TREE_FILTER_ALL or entry.subtype == subtype)
        })

        self.ui.tree_faction_comboBox.blockSignals(True)
        self.ui.tree_faction_comboBox.clear()
        self.ui.tree_faction_comboBox.addItem(register_widgets.TREE_FILTER_ALL)
        self.ui.tree_faction_comboBox.addItems(factions)
        idx = self.ui.tree_faction_comboBox.findText(current)
        self.ui.tree_faction_comboBox.setCurrentIndex(idx if idx >= 0 else 0)
        self.ui.tree_faction_comboBox.blockSignals(False)

    def _on_tree_subcategory_changed(self, *_):
        """Sub-category filter changed: narrow the faction list, refilter, prefill a blank form."""

        self._populate_tree_faction_filter()
        self._filter_tree()
        self._prefill_form_from_filters()
        self._capture_form_baseline()

    def _on_tree_faction_changed(self, *_):
        """Faction filter changed: refilter and prefill a blank form."""

        self._filter_tree()
        self._prefill_form_from_filters()
        self._capture_form_baseline()

    def _filter_tree(self, *_):
        """
        Show/hide tree items from the search text and the sub-category /
        faction dropdowns, then update the "shown of total" count.

        A row is shown when it passes every active filter; ancestors of a
        shown row stay visible so gear never loses its parent. Accepts and
        ignores the signal argument so it can sit on textChanged directly.

        Uses topLevelItem/child indexing (not QTreeWidgetItemIterator) —
        see ``_refresh_tree`` for why iterators are unsafe to leave around
        in this widget: they register with the tree's internal model and
        can crash during any subsequent item destruction if the Python
        wrapper has not yet been GC'd.
        """

        text = self.ui.tree_filter_lineEdit.text().lower()
        subtype = self.ui.tree_subcategory_comboBox.currentText()
        faction = self.ui.tree_faction_comboBox.currentText()
        counts = {'shown': 0, 'total': 0}

        def matches(item):
            entry = item.data(0, qtcore.Qt.UserRole)
            if text and text not in item.text(0).lower():
                return False
            if subtype != register_widgets.TREE_FILTER_ALL and (entry is None or entry.subtype != subtype):
                return False
            if faction != register_widgets.TREE_FILTER_ALL and (entry is None or entry.faction != faction):
                return False
            return True

        def visit(item):
            counts['total'] += 1
            if matches(item):
                counts['shown'] += 1
                item.setHidden(False)
                parent = item.parent()
                while parent is not None:
                    parent.setHidden(False)
                    parent = parent.parent()
            else:
                item.setHidden(True)
            for i in range(item.childCount()):
                visit(item.child(i))

        for i in range(self._asset_tree.topLevelItemCount()):
            visit(self._asset_tree.topLevelItem(i))

        self.ui.tree_count_label.setText('{0} of {1}'.format(counts['shown'], counts['total']))

    def _on_tree_item_clicked(self, item, column):
        """
        Populate the form from a tree selection for editing.

        Prompts to save unsaved edits before swapping the form to the
        newly clicked asset. Cancelling leaves the previous selection
        in place.

        :param QTreeWidgetItem item: The clicked tree item.
        :param int column: The clicked column index.
        """

        entry = item.data(0, qtcore.Qt.UserRole)
        if not entry:
            return

        # No-op when the user clicks the asset that's already loaded —
        # avoids a pointless prompt if they re-click the current row.
        if self._current_entry is not None and entry is self._current_entry:
            return

        action = self._prompt_save_if_dirty('switching assets')
        if action == 'cancel':
            return

        self._current_entry = entry
        self._populate_form_from_entry(entry)
        self._update_preview_panel(entry)

    def _prefill_form_from_filters(self):
        """
        Seed a blank form's sub-category and faction from the tree filters.

        Only runs when no asset is loaded and no name has been typed, i.e.
        the user is about to add into what they are looking at. Values are
        applied only when the form combobox already offers them, so a
        filter value that is not in the category config never leaks in.
        Callers re-snapshot the baseline afterwards.
        """

        if self._current_entry is not None or self.ui.name_lineEdit.text().strip():
            return

        for filter_combo, form_combo in ((self.ui.tree_subcategory_comboBox, self.ui.sub_category_comboBox),
                                         (self.ui.tree_faction_comboBox, self.ui.faction_comboBox)):
            value = filter_combo.currentText()
            if value == register_widgets.TREE_FILTER_ALL:
                form_combo.setCurrentIndex(0)
                continue
            idx = form_combo.findText(value)
            form_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._update_auto_paths()
