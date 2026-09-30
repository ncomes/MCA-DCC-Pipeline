"""
Path derivation, the classification order that drives it, gear root and images.

Part of the Unified Asset Register, split out of ``unified_register`` so each
area of the window is readable on its own. The methods are unchanged; they run
on :class:`unified_register.UnifiedRegisterUI`, which mixes this class in, and
rely on the attributes that class builds.

:Requires: mca.common.pyqt, mca.common.assetlist
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_paths, unified_entry, unified_registry
from mca.common.paths import paths, project_paths
from mca.common.pyqt import messages
from mca.common.pyqt.pygui import qtcore, qtgui, qtwidgets, shiboken
from mca.common.resources import resources
from mca.common.tools.assetregister import register_widgets


logger = log.MCA_LOGGER


class PathsMixin:
    """
    Path derivation, the classification order that drives it, gear root and images.

    Mixed into :class:`unified_register.UnifiedRegisterUI`; never instantiated
    on its own.
    """

    def _update_auto_paths(self):
        """
        Regenerate the DCC and engine paths from the current form values.

        Reads every classification combobox plus the per-field "In Path"
        checkboxes, and hands both to ``build_asset_path`` so the preview
        reflects exactly what will be stored on save.
        """

        name = self.ui.name_lineEdit.text().strip()
        category = self.ui.category_comboBox.currentText()
        subtype = self.ui.sub_category_comboBox.currentText()
        faction = self.ui.faction_comboBox.currentText()
        gender = self.ui.gender_comboBox.currentText()
        asset_type = self.ui.asset_type_comboBox.currentText()
        skeleton = self.ui.skeleton_comboBox.currentText()
        body_type = self.ui.body_type_comboBox.currentText()
        # Any parent at all makes this gear; which ones does not affect the path.
        built_for = 'gear' if self.ui.built_for_list.selectedItems() else ''

        # Gather additional types from the list widget
        additional_types = []
        for i in range(self._additional_types_list.count()):
            additional_types.append(self._additional_types_list.item(i).text())

        path_flags = self._collect_path_flags()
        path_order = self._collect_classification_order()

        # Gear path prefix triggers in two cases:
        #   1. The asset has a built_for parent (child/variant gear).
        #   2. The selected category is flagged IS_GEAR in the config.
        # Either case puts the asset under the category's gear root.
        is_gear = bool(built_for) or self.ui.is_gear_checkBox.isChecked()
        dcc_path = unified_entry.build_asset_path(
            category=category,
            subtype=subtype,
            faction=faction,
            additional_types=additional_types,
            asset_name=name,
            is_gear=is_gear,
            gear_root=self._current_gear_root(),
            gender=gender,
            asset_type=asset_type,
            skeleton=skeleton,
            body_type=body_type,
            path_flags=path_flags,
            path_order=path_order,
        )
        engine_path = unified_entry.build_engine_path(dcc_path)
        engine_path = self._decorate_engine_path(engine_path, name, asset_type)

        self.ui.dcc_path_lineEdit.setText(dcc_path)
        self.ui.engine_path_lineEdit.setText(engine_path)

    def _decorate_engine_path(self, engine_path, asset_name, asset_type):
        """
        Hook for DCC wrappers to post-process the auto-generated engine path.

        The common base returns ``engine_path`` unchanged. The Unreal
        wrapper overrides this to append the mesh/material subfolder and
        the prefixed asset filename (e.g. ``.../Meshes/SK_Afro``) so the
        engine-path field points at the actual asset file.

        :param str engine_path: The auto-generated engine directory path.
        :param str asset_name: Current asset name from the form.
        :param str asset_type: SkeletalMesh, StaticMesh, or Material.
        :return: The engine path to display in the field.
        :rtype: str
        """

        return engine_path

    def _collect_path_flags(self):
        """
        Read the "In Path" checkboxes into a ``path_flags`` dict.

        :return: Dict matching ``unified_entry.DEFAULT_PATH_FLAGS`` keys.
        :rtype: dict
        """

        return {
            'include_subtype': self.ui.subtype_in_path_checkBox.isChecked(),
            'include_faction': self.ui.faction_in_path_checkBox.isChecked(),
            'include_gender': self.ui.gender_in_path_checkBox.isChecked(),
            'include_asset_type': self.ui.asset_type_in_path_checkBox.isChecked(),
            'include_skeleton': self.ui.skeleton_in_path_checkBox.isChecked(),
            'include_body_type': self.ui.body_type_in_path_checkBox.isChecked(),
            'include_additional_types': self.ui.additional_types_in_path_checkBox.isChecked(),
        }

    def _collect_classification_order(self):
        """
        Read the current visual order of classification rows.

        Walks the list widget top-to-bottom and collects each row's
        ``field_key`` so the order matches whatever the user has dragged
        rows into. Unknown/corrupt items are ignored.

        :return: List of field keys from ``unified_entry.ORDERABLE_FIELDS``.
        :rtype: list[str]
        """

        lw = self.ui.classification_listWidget
        order = []
        for i in range(lw.count()):
            item = lw.item(i)
            w = lw.itemWidget(item)
            if w is not None and getattr(w, 'field_key', ''):
                order.append(w.field_key)
        return order

    def _build_classification_row(self, field_key, label, input_widget,
                                  add_button=None, in_path_checkbox=None):
        """
        Build a composite row widget for the classification list.

        Each row stacks [drag handle][label][input][add button?][checkbox]
        horizontally. The widget stores ``field_key`` / ``in_path_checkbox``
        attributes so the list can be re-ordered and queried without
        re-scanning Qt's internal state.

        :param str field_key: Field identifier (one of ``ORDERABLE_FIELDS``).
        :param str label: Display label text.
        :param QWidget input_widget: Combo or line edit for the field value.
        :param QPushButton add_button: Optional "+" add-new button.
        :param QCheckBox in_path_checkbox: The "In Path" toggle.
        :return: The row container widget, ready for ``setItemWidget``.
        :rtype: register_widgets.ClassificationRow
        """

        # Use register_widgets.ClassificationRow (not plain QWidget) so Qt's mandatory
        # setIndexWidget deleteLater cannot destroy row widgets that the
        # host wants to reuse across _rebuild_classification_order calls.
        row = register_widgets.ClassificationRow()
        h = qtwidgets.QHBoxLayout(row)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(6)
        # Unicode list/hamburger glyph doubles as a visual drag affordance.
        handle = qtwidgets.QLabel('☰')
        handle.setFixedWidth(14)
        handle.setAlignment(qtcore.Qt.AlignCenter)
        handle.setToolTip('Drag row to reorder how this field appears in the path.')
        handle.setStyleSheet('color: #888;')
        h.addWidget(handle)
        lbl = qtwidgets.QLabel(label + ':')
        lbl.setFixedWidth(90)
        lbl.setAlignment(qtcore.Qt.AlignRight | qtcore.Qt.AlignVCenter)
        h.addWidget(lbl)
        h.addWidget(input_widget, 1)
        if add_button is not None:
            h.addWidget(add_button)
        if in_path_checkbox is not None:
            h.addWidget(in_path_checkbox)
        # Attributes consumed by _collect_classification_order and form-load code.
        row.field_key = field_key
        row.in_path_checkbox = in_path_checkbox
        return row

    def _on_classification_reorder(self, source_row, target_row):
        """
        Apply a drag-reorder request from the classification list.

        Walks the current field-key order, moves the dragged key to its new
        position, then hands the new order to ``_rebuild_classification_order``
        which rebuilds the list with the row widgets intact. Finally refreshes
        the path preview.

        :param int source_row: Row the user picked up.
        :param int target_row: Destination row (already adjusted for source
            removal; safe to use with ``list.pop`` + ``list.insert``).
        """

        current = self._collect_classification_order()
        if not (0 <= source_row < len(current)):
            return
        if not (0 <= target_row <= len(current)):
            return
        moved = current.pop(source_row)
        current.insert(target_row, moved)
        self._rebuild_classification_order(current)
        self._update_auto_paths()

    def _rebuild_classification_order(self, order):
        """
        Rebuild the classification list widget so rows appear in ``order``.

        Row widgets are reused across every call — they survive ``clear()``
        because ``register_widgets.ClassificationRow`` swallows the ``DeferredDelete``
        event that ``setIndexWidget`` queues when its row is removed (see
        the ``register_widgets.ClassificationRow`` docstring for the crash this avoids).

        Any fields missing from ``order`` are appended in
        ``DEFAULT_PATH_ORDER`` position so the UI always shows every field.

        :param list order: Desired list of field keys.
        """

        lw = self.ui.classification_listWidget
        # Block model/view signals so clear() + re-add does not emit
        # spurious rowsMoved / selection notifications mid-rebuild.
        was_blocked = lw.signalsBlocked()
        lw.blockSignals(True)
        try:
            lw.clear()
        finally:
            lw.blockSignals(was_blocked)

        # Only accept known field keys; append any missing field so a stale
        # stored order never silently drops a row.
        final_order = [f for f in order if f in self._classification_rows]
        for f in unified_entry.DEFAULT_PATH_ORDER:
            if f in self._classification_rows and f not in final_order:
                final_order.append(f)

        for field_key in final_order:
            row = self._classification_rows[field_key]
            item = qtwidgets.QListWidgetItem(lw)
            item.setSizeHint(row.sizeHint())
            # Items need ItemIsEnabled/Selectable/DragEnabled (the defaults)
            # to participate in InternalMove drag-drop; no flag changes needed.
            lw.addItem(item)
            lw.setItemWidget(item, row)
            row.show()

    def _teardown_classification_list(self):
        """
        Safely detach classification row widgets before the list view is
        destroyed.

        Mirrors the reparent-then-clear pattern used in
        ``_rebuild_classification_order``: reparent every row widget back to
        the host window so its Qt parent is no longer the list view, then
        clear the list. The view's index-widget map is drained before Qt's
        dtor cascade runs, which prevents a queued
        ``QAbstractItemView::doItemsLayout`` timer from dereferencing freed
        row widgets (the exact stack in
        ``MayaCrashLog260421.1323.log``/``.1423.log``).

        Idempotent. Uses ``shiboken.isValid`` to no-op cleanly when the
        underlying C++ widgets have already been destroyed (Maya shutdown,
        module unload, etc.).
        """

        lw = getattr(self.ui, 'classification_listWidget', None)
        if lw is not None and shiboken.isValid(lw):
            # Drain the list before Qt's dtor cascade runs. The rows
            # themselves survive this because register_widgets.ClassificationRow swallows
            # the DeferredDelete events that setIndexWidget queues.
            was_blocked = lw.signalsBlocked()
            lw.blockSignals(True)
            try:
                lw.clear()
            finally:
                lw.blockSignals(was_blocked)
        # register_widgets.ClassificationRow swallows deleteLater, so destroy the rows
        # explicitly here — this is the one place we actually want them
        # gone. Using shiboken.delete bypasses the swallowed event.
        for row in list(self._classification_rows.values()):
            if shiboken.isValid(row):
                shiboken.delete(row)
        self._classification_rows = {}

    def _on_is_gear_toggled(self, checked):
        """
        Persist the "Is Gear" flag onto the current category and refresh
        the path preview.

        :param bool checked: New checkbox state.
        """

        category = self.ui.category_comboBox.currentText()
        if not category or not self._asset_paths_data:
            return
        category_data = self._asset_paths_data.get_category_data(category)
        if not category_data:
            return
        if category_data.is_gear != bool(checked):
            category_data.is_gear = bool(checked)
            self._asset_paths_data.save()
            self._asset_data_dirty = True
            logger.info(
                f'Set IS_GEAR={bool(checked)} on category "{category}".')
        # Show the start folder as soon as the box is ticked, hide it when not.
        self._sync_gear_root_field(category_data)
        self._update_auto_paths()

    def _sync_gear_root_field(self, category_data):
        """
        Fill the gear root field from the category and enable it only while
        the category is flagged as gear.

        setText does not emit editingFinished, so this never round-trips into
        _on_gear_root_edited.

        :param asset_paths.CategoryData category_data: Current category wrapper, or None.
        """

        is_gear_cat = bool(category_data and category_data.is_gear)
        self.ui.gear_root_lineEdit.setEnabled(is_gear_cat)
        self.ui.gear_root_browse_pushButton.setEnabled(is_gear_cat)
        self.ui.gear_root_lineEdit.setText(category_data.gear_root if is_gear_cat else '')

    def _on_gear_root_edited(self):
        """
        Persist an edited gear root onto the current category and refresh
        the path preview.
        """

        category = self.ui.category_comboBox.currentText()
        if not category or not self._asset_paths_data:
            return
        category_data = self._asset_paths_data.get_category_data(category)
        if not category_data or not category_data.is_gear:
            return
        new_root = asset_paths.normalize_gear_root(self.ui.gear_root_lineEdit.text())
        new_root = new_root or asset_paths.DEFAULT_GEAR_ROOT
        # Echo the cleaned value so what the user sees matches what is saved.
        self.ui.gear_root_lineEdit.setText(new_root)
        if category_data.gear_root != new_root:
            category_data.gear_root = new_root
            self._asset_paths_data.save()
            self._asset_data_dirty = True
            logger.info(f'Set GEAR_ROOT="{new_root}" on category "{category}".')
        self._update_auto_paths()

    def _browse_gear_root(self):
        """
        Pick the gear start folder with a folder browser.

        The dialog opens on the current root (or the project root when that
        folder does not exist yet). The selection is stored relative to the
        project root, the same form the text field expects, and persisted on
        the category through _on_gear_root_edited.
        """

        project_root = project_paths.get_project_path()
        if not project_root:
            messages.info_message("Gear Root", "MCA_PROJECT_ROOT is not set; cannot browse relative to the project.")
            return
        project_root = os.path.normpath(project_root)
        current = asset_paths.normalize_gear_root(self.ui.gear_root_lineEdit.text())
        start_dir = os.path.join(project_root, current or asset_paths.DEFAULT_GEAR_ROOT)
        if not os.path.isdir(start_dir):
            start_dir = project_root
        folder = qtwidgets.QFileDialog.getExistingDirectory(
            self, 'Select Gear Root Folder', start_dir)
        if not folder:
            return

        # Only folders inside the project can be expressed as a relative root.
        try:
            relative = os.path.relpath(os.path.normpath(folder), project_root)
        except ValueError:
            # Different drive on Windows.
            relative = None
        if relative is None or relative == '.' or relative.startswith('..'):
            messages.info_message(
                'Gear Root',
                f'Pick a folder inside the project root:\n{project_root}')
            return

        self.ui.gear_root_lineEdit.setText(relative.replace('\\', '/'))
        self._on_gear_root_edited()

    def _current_gear_root(self):
        """
        Returns the gear root to prefix generated paths with.

        Uses the text field when it holds a value (the live override),
        otherwise the category's stored root, so child gear in a category
        that is not itself flagged as gear still lands under that
        category's root.

        :return: Forward-slash relative path such as 'Gear'.
        :rtype: str
        """

        text = asset_paths.normalize_gear_root(self.ui.gear_root_lineEdit.text())
        if text:
            return text
        category = self.ui.category_comboBox.currentText()
        category_data = None
        if category and self._asset_paths_data:
            category_data = self._asset_paths_data.get_category_data(category)
        return category_data.gear_root if category_data else asset_paths.DEFAULT_GEAR_ROOT

    def _browse_image(self):
        """Open a file browser for the asset image/icon."""

        start_dir = paths.get_common_icons_path()
        file_path, _ = qtwidgets.QFileDialog.getOpenFileName(
            self, 'Select Asset Image', start_dir,
            'Images (*.jpg *.jpeg *.png *.tga);;All Files (*)')
        if file_path:
            # Store as relative path from the common tools root when possible.
            tools_root = os.path.dirname(paths.get_asset_list_path())
            resources_root = paths.get_common_resources_path()
            for base in (tools_root, resources_root):
                normed = os.path.normpath(file_path)
                normed_base = os.path.normpath(base)
                if normed.lower().startswith(normed_base.lower()):
                    rel = os.path.relpath(normed, normed_base)
                    self.ui.image_lineEdit.setText(rel.replace('\\', '/'))
                    return
            self.ui.image_lineEdit.setText(file_path.replace('\\', '/'))

    def _browse_dcc_path(self):
        """Open a folder browser for the DCC source path."""

        start_dir = self.ui.dcc_path_lineEdit.text() or ''
        folder = qtwidgets.QFileDialog.getExistingDirectory(
            self, 'Select DCC Source Folder', start_dir)
        if folder:
            self.ui.dcc_path_lineEdit.setText(folder.replace('\\', '/'))

    def _browse_engine_path(self):
        """Open a folder browser for the Unreal Engine content path."""

        start_dir = self.ui.engine_path_lineEdit.text() or ''
        folder = qtwidgets.QFileDialog.getExistingDirectory(
            self, 'Select Engine Content Folder', start_dir)
        if folder:
            self.ui.engine_path_lineEdit.setText(folder.replace('\\', '/'))

    def _capture_asset_image(self):
        """
        Capture an image of the current asset from the DCC viewport.

        Base implementation shows an info message. DCC-specific subclasses
        (e.g. UnrealUnifiedRegister) override this to capture a viewport
        screenshot and save it as the asset icon.
        """

        messages.info_message(
            'Not Available',
            'Capture Image is only available in a DCC application '
            '(Maya via Summoner, or Unreal Engine).',
        )

    def _update_image_preview(self):
        """
        Load and display the image in the info panel thumbnail below the tree.

        Resolution order:
        1. Explicit image path from the Image field (absolute or relative).
        2. Auto-discover from Icons/{Category}/{name_lower}.jpg on disk.
        """

        image_path = self.ui.image_lineEdit.text().strip()
        preview = self.ui.info_thumbnail_label

        full_path = self._resolve_image_path(image_path)

        # If no explicit image, try auto-discovering from the Icons directory.
        if not full_path:
            full_path = self._auto_discover_image()

        if full_path and os.path.isfile(full_path):
            pixmap = qtgui.QPixmap(full_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    preview.size(),
                    qtcore.Qt.KeepAspectRatio,
                    qtcore.Qt.SmoothTransformation,
                )
                preview.setPixmap(scaled)
                return

        preview.setText('No Image')
        preview.setPixmap(qtgui.QPixmap())

    @staticmethod
    def _variant_summary(entry):
        """
        One line saying whether this character is a restyle of another.

        :param UnifiedAssetEntry entry: The entry being previewed.
        :return: Text for the info panel's variant row.
        :rtype: str
        """

        base_id = getattr(entry, 'variant_of', '')
        if not base_id:
            return 'Variant Of: -'

        registry = unified_registry.UnifiedAssetRegistry.load('Characters', create=True)
        base = registry.get_asset_entry(base_id, skip_dialog=True) if registry else None
        base_name = base.name if base is not None else base_id
        return 'Variant Of: {} ({})'.format(base_name, base_id)

    def _resolve_image_path(self, image_path):
        """
        Resolve an image path string to an absolute file path.

        Tries the path as-is (absolute), then relative to the common tools
        directory, then relative to the Resources directory.

        :param str image_path: Raw image path from the form.
        :return: Absolute path if found on disk, or None.
        :rtype: str or None
        """

        if not image_path:
            return None

        # Absolute path
        if os.path.isabs(image_path) and os.path.isfile(image_path):
            return image_path

        # Relative to common tools root (e.g. "Icons/Characters/hyena.jpg")
        base = os.path.dirname(paths.get_asset_list_path())
        candidate = os.path.normpath(os.path.join(base, image_path))
        if os.path.isfile(candidate):
            return candidate

        # Relative to Resources directory
        resources = paths.get_common_resources_path()
        candidate = os.path.normpath(os.path.join(resources, image_path))
        if os.path.isfile(candidate):
            return candidate

        return None

    def _auto_discover_image(self):
        """
        Try to find an icon for the current entry in the Icons directory.

        Searches Icons/{Category}/{name}.jpg using the asset name from
        the form field. Falls back to lowercase variants.

        :return: Absolute path to the image if found, or None.
        :rtype: str or None
        """

        name = self.ui.name_lineEdit.text().strip()
        category = self.ui.category_comboBox.currentText()
        if not name or not category:
            return None

        icons_dir = paths.get_common_icons_path()
        category_dir = os.path.join(icons_dir, category)
        if not os.path.isdir(category_dir):
            return None

        # Try exact name, then lowercase, for common image extensions.
        candidates = [name, name.lower(), name.replace(' ', '_').lower()]
        for candidate_name in candidates:
            for ext in ('.jpg', '.png', '.tga'):
                candidate = os.path.join(category_dir, f'{candidate_name}{ext}')
                if os.path.isfile(candidate):
                    return os.path.normpath(candidate)

        return None

    # --- Preview info panel ------------------------------------------------ #

    def _update_preview_panel(self, entry):
        """
        Update the preview info panel below the tree with data from an entry.

        Shows the thumbnail, asset name, category, variant status, path, and ID.

        :param UnifiedAssetEntry entry: The entry to display, or None to clear.
        """

        if not entry:
            self.ui.info_thumbnail_label.setText('No Image')
            self.ui.info_thumbnail_label.setPixmap(qtgui.QPixmap())
            self.ui.info_name_label.setText('Asset Name:')
            self.ui.info_category_label.setText('Asset Category:')
            self.ui.info_variant_label.setText('Variant Of:')
            self.ui.info_path_label.setText('Asset Path:')
            self.ui.info_id_label.setText('Asset Id:')
            return

        # Info labels
        self.ui.info_name_label.setText(f'Name: {entry.name}')
        self.ui.info_category_label.setText(f'Category: {entry.category}')
        self.ui.info_variant_label.setText(self._variant_summary(entry))
        self.ui.info_path_label.setText(f'Path: {entry.path}')
        self.ui.info_id_label.setText(f'Id: {entry.asset_id}')

        # Thumbnail - use same resolution logic as the form preview
        image_path = entry.image
        full_path = self._resolve_image_path(image_path)

        if not full_path:
            # Auto-discover from Icons directory
            name = entry.name
            category = entry.category
            if name and category:
                icons_dir = paths.get_common_icons_path()
                category_dir = os.path.join(icons_dir, category)
                if os.path.isdir(category_dir):
                    candidates = [name, name.lower(), name.replace(' ', '_').lower()]
                    for candidate_name in candidates:
                        for ext in ('.jpg', '.png', '.tga'):
                            candidate = os.path.join(category_dir, f'{candidate_name}{ext}')
                            if os.path.isfile(candidate):
                                full_path = os.path.normpath(candidate)
                                break
                        if full_path:
                            break

        thumb_label = self.ui.info_thumbnail_label
        if full_path and os.path.isfile(full_path):
            pixmap = qtgui.QPixmap(full_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    thumb_label.size(),
                    qtcore.Qt.KeepAspectRatio,
                    qtcore.Qt.SmoothTransformation,
                )
                thumb_label.setPixmap(scaled)
                return

        thumb_label.setText('No Image')
        thumb_label.setPixmap(qtgui.QPixmap())
