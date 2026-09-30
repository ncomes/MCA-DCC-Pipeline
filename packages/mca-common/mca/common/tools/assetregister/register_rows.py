"""
The repeating rows inside the detail tabs: materials, dyes, decals, textures, sockets.

Part of the Unified Asset Register, split out of ``unified_register`` so each
area of the window is readable on its own. The methods are unchanged; they run
on :class:`unified_register.UnifiedRegisterUI`, which mixes this class in, and
rely on the attributes that class builds.

:Requires: mca.common.pyqt, mca.common.assetlist
"""

# MCA python imports
from mca.common import log
from mca.common.pyqt.pygui import qtcore, qtgui, qtwidgets
from mca.common.tools.assetregister import register_widgets


logger = log.MCA_LOGGER


class RowsMixin:
    """
    The repeating rows inside the detail tabs: materials, dyes, decals, textures, sockets.

    Mixed into :class:`unified_register.UnifiedRegisterUI`; never instantiated
    on its own.
    """

    def _create_slot_row(self, rows_layout, index=0, name='', slot_name='',
                         options='', mesh_type=None, slot_kind=None,
                         is_dye=False, channels=None):
        """
        Create a frame for a material/dye/decal slot.

        Row 1: "Name:" label + name edit + options edit
               (+ "Is Dye" checkbox on material rows) + "x" remove button.
        Row 2: "Slot #:" label + index spinbox + "Slot Name:" label +
               slot name edit + [set from selection] + [goto material] +
               browse button.
        Row 3 (dye rows only): channels editor (one sub-row per channel
               with name / type / default fields, plus add and discover
               buttons).

        ``slot_kind`` defaults to ``decal`` when ``mesh_type`` is supplied
        and ``material`` otherwise, so legacy callers that omit it still
        get the original behavior.

        Widget references are stored directly on the frame for collection:
        ``row_frame.index_spin``, ``row_frame.name_edit``,
        ``row_frame.options_edit``, ``row_frame.slot_name_edit``,
        ``row_frame.mesh_edit``, ``row_frame.is_dye_check``,
        ``row_frame.channels_layout``, ``row_frame.discover_btn``,
        ``row_frame.set_btn``, ``row_frame.goto_btn``, ``row_frame.browse_btn``.

        :param QVBoxLayout rows_layout: Parent layout to insert row into.
        :param int index: Slot index value.
        :param str name: Display name (e.g. material instance name).
        :param str slot_name: Engine slot name (e.g. "MI_Metal").
        :param str options: Options text (comma-separated material paths).
        :param str mesh_type: Mesh type text (decals only, None to omit).
        :param str slot_kind: One of ``material``, ``dye``, ``decal``.
            Inferred from ``mesh_type`` when None.
        :param bool is_dye: Initial state of the Is Dye checkbox
            (material rows only).
        :param list channels: Initial channel definitions for dye rows;
            each is ``{name, type, default}``.
        :return: The created row frame.
        :rtype: QFrame
        """

        if slot_kind is None:
            slot_kind = 'decal' if mesh_type is not None else 'material'

        row_frame = qtwidgets.QFrame()
        row_frame.setFrameShape(qtwidgets.QFrame.StyledPanel)
        frame_layout = qtwidgets.QVBoxLayout(row_frame)
        frame_layout.setContentsMargins(2, 2, 2, 2)
        frame_layout.setSpacing(2)

        # --- Row 1: Name + options + remove -------------------------------- #
        row1 = qtwidgets.QHBoxLayout()
        row1.setSpacing(4)

        name_label = qtwidgets.QLabel('Name:')
        name_label.setFixedWidth(42)
        row1.addWidget(name_label)

        # Name line edit (material / dye / decal display name)
        name_edit = qtwidgets.QLineEdit(name)
        name_edit.setPlaceholderText('Material Name')
        name_edit.setToolTip('Display name (e.g. material instance name)')
        row1.addWidget(name_edit)

        # Options / material path line edit
        options_edit = qtwidgets.QLineEdit(options)
        options_edit.setPlaceholderText('Options (comma-separated)')
        options_edit.setToolTip('Comma-separated material option paths')
        row1.addWidget(options_edit)

        # Optional mesh type for decals
        mesh_edit = None
        if slot_kind == 'decal':
            mesh_edit = qtwidgets.QLineEdit(mesh_type or '')
            mesh_edit.setPlaceholderText('Mesh Type')
            mesh_edit.setToolTip('Decal mesh type')
            row1.addWidget(mesh_edit)

        # Is Dye checkbox (material rows only). Toggling promotes/demotes a
        # mirrored row in the Dyes tab keyed by ``slot_name`` so the two
        # tabs stay in sync without needing a save round-trip.
        is_dye_check = None
        if slot_kind == 'material':
            is_dye_check = qtwidgets.QCheckBox('Is Dye')
            is_dye_check.setToolTip(
                'Mark this material as a dye. A matching row appears in '
                'the Dyes tab where its tint channels are configured.')
            is_dye_check.setChecked(bool(is_dye))
            row1.addWidget(is_dye_check)

        # Remove button
        remove_btn = qtwidgets.QPushButton('x')
        remove_btn.setFixedSize(24, 24)
        remove_btn.setToolTip('Remove this row')
        remove_btn.clicked.connect(lambda: self._remove_specific_row(rows_layout, row_frame))
        row1.addWidget(remove_btn)

        frame_layout.addLayout(row1)

        # --- Row 2: Slot # + slot name + DCC buttons + browse -------------- #
        row2 = qtwidgets.QHBoxLayout()
        row2.setSpacing(4)

        slot_label = qtwidgets.QLabel('Slot #:')
        slot_label.setFixedWidth(42)
        row2.addWidget(slot_label)

        # Index spinbox
        index_spin = qtwidgets.QSpinBox()
        index_spin.setFixedWidth(50)
        index_spin.setRange(0, 999)
        index_spin.setValue(index)
        index_spin.setToolTip('Slot index')
        row2.addWidget(index_spin)

        slot_name_label = qtwidgets.QLabel('Slot Name:')
        slot_name_label.setFixedWidth(68)
        row2.addWidget(slot_name_label)

        # Slot name (engine slot name, e.g. "M_Body")
        slot_name_edit = qtwidgets.QLineEdit(slot_name)
        slot_name_edit.setPlaceholderText('Slot Name')
        slot_name_edit.setToolTip('Engine material slot name')
        row2.addWidget(slot_name_edit)

        # DCC-specific: set material from selection (hidden by default)
        set_btn = qtwidgets.QPushButton('Set')
        set_btn.setFixedWidth(36)
        set_btn.setToolTip('Set from editor selection')
        set_btn.setVisible(False)
        row2.addWidget(set_btn)

        # DCC-specific: goto material in editor (hidden by default)
        goto_btn = qtwidgets.QPushButton('Go')
        goto_btn.setFixedWidth(30)
        goto_btn.setToolTip('Navigate to this material in the editor')
        goto_btn.setVisible(False)
        row2.addWidget(goto_btn)

        # Browse button (common to all DCCs)
        browse_btn = qtwidgets.QPushButton('...')
        browse_btn.setFixedWidth(30)
        browse_btn.setToolTip('Browse for material')
        browse_btn.clicked.connect(
            lambda: self._browse_material_slot(row_frame))
        row2.addWidget(browse_btn)

        frame_layout.addLayout(row2)

        # --- Row 3: Channels editor (dye rows only) ------------------------ #
        channels_layout = None
        discover_btn = None
        if slot_kind == 'dye':
            channels_group = qtwidgets.QGroupBox('Channels')
            channels_group.setToolTip(
                'Tint and scalar parameters this dye exposes. Names must '
                'match the parent material parameters in UE exactly.')
            channels_outer = qtwidgets.QVBoxLayout(channels_group)
            channels_outer.setContentsMargins(4, 4, 4, 4)
            channels_outer.setSpacing(2)

            channels_layout = qtwidgets.QVBoxLayout()
            channels_layout.setSpacing(2)
            channels_outer.addLayout(channels_layout)

            ch_btn_row = qtwidgets.QHBoxLayout()
            add_ch_btn = qtwidgets.QPushButton('Add Channel')
            add_ch_btn.setToolTip('Add a new dye channel row')
            add_ch_btn.clicked.connect(
                lambda: self._create_channel_row(channels_layout))
            ch_btn_row.addWidget(add_ch_btn)

            # DCC wrappers (UE) wire this to query the parent material's
            # parameter list. Hidden by default outside UE.
            discover_btn = qtwidgets.QPushButton('Discover Channels')
            discover_btn.setToolTip(
                'Populate channels from the parent material in the editor.')
            discover_btn.setVisible(False)
            ch_btn_row.addWidget(discover_btn)
            ch_btn_row.addStretch()
            channels_outer.addLayout(ch_btn_row)

            frame_layout.addWidget(channels_group)

            # Pre-populate channel sub-rows from initial data.
            for ch in (channels or []):
                self._create_channel_row(
                    channels_layout,
                    name=ch.get('name', ''),
                    ch_type=ch.get('type', 'linear_color'),
                    default=ch.get('default'),
                    display_name=ch.get('display_name', '') or '',
                    description=ch.get('description', '') or '',
                )

        # --- Store widget refs on the frame for collection ----------------- #
        row_frame.slot_kind = slot_kind
        row_frame.index_spin = index_spin
        row_frame.name_edit = name_edit
        row_frame.options_edit = options_edit
        row_frame.slot_name_edit = slot_name_edit
        row_frame.mesh_edit = mesh_edit
        row_frame.is_dye_check = is_dye_check
        row_frame.channels_layout = channels_layout
        row_frame.discover_btn = discover_btn
        row_frame.set_btn = set_btn
        row_frame.goto_btn = goto_btn
        row_frame.browse_btn = browse_btn

        # Wire Is Dye toggle to mirror the row into the Dyes tab.
        if is_dye_check is not None:
            is_dye_check.toggled.connect(
                lambda checked, rf=row_frame: self._on_is_dye_toggled(rf, checked))

        # Let DCC wrappers show/connect editor-specific buttons.
        self._setup_slot_row_dcc_buttons(row_frame)
        if slot_kind == 'dye':
            self._setup_dye_row_dcc_buttons(row_frame)

        # Insert before the stretch item at the end of the layout
        stretch_index = rows_layout.count() - 1
        rows_layout.insertWidget(stretch_index, row_frame)

        return row_frame

    def _setup_slot_row_dcc_buttons(self, row_frame):
        """
        Hook for DCC wrappers to show and connect the Set and Go buttons
        on a material slot row frame.

        The base implementation does nothing; buttons remain hidden.
        Override in DCC subclasses to make ``row_frame.set_btn`` and
        ``row_frame.goto_btn`` visible and wired to editor actions.

        :param QFrame row_frame: The slot row frame with stored widget refs.
        """

        pass

    def _setup_dye_row_dcc_buttons(self, row_frame):
        """
        Hook for DCC wrappers to wire the dye row's Discover Channels
        button to editor-specific channel population logic.

        Base implementation does nothing; the Discover button stays
        hidden. UE override queries the parent material's parameter list
        and fills the channels editor.

        :param QFrame row_frame: The dye slot row frame.
        """

        pass

    def _create_channel_row(self, channels_layout, name='', ch_type='linear_color',
                            default=None, display_name='', description=''):
        """
        Create a single channel sub-row inside a dye row's channels editor.

        Each sub-row is a two-line block:

        - Top line: friendly Name, exact UE param name, type combo,
          default-value line edit, remove button.
        - Bottom line: free-form Description.

        The default field accepts free-form text; it is parsed at collect
        time based on the selected type (4 floats for ``linear_color``,
        1 float for ``scalar``).

        :param QVBoxLayout channels_layout: Parent layout for channel rows.
        :param str name: Initial UE parameter name (e.g. ``PrimaryColor``).
        :param str ch_type: Initial type, one of ``DYE_CHANNEL_TYPES``.
        :param default: Initial default value (list/float/str). Stringified
            for the line edit.
        :param str display_name: Artist-facing label (e.g. ``Tie Red``).
        :param str description: Optional short description shown beneath
            the channel inputs.
        :return: The created channel sub-row frame.
        :rtype: QFrame
        """

        row = qtwidgets.QFrame()
        row.setFrameShape(qtwidgets.QFrame.NoFrame)
        # Outer vertical layout so the description sits below the inputs.
        outer = qtwidgets.QVBoxLayout(row)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(2)

        # Top line: [Name] [Param] [Type] [Default] [x]
        top = qtwidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)

        display_name_edit = qtwidgets.QLineEdit(display_name)
        display_name_edit.setPlaceholderText('Name (e.g. Tie Red)')
        display_name_edit.setToolTip(
            'Artist-facing label for this channel. Shown in the Dye '
            'Overrides tab.')
        top.addWidget(display_name_edit, 2)

        name_edit = qtwidgets.QLineEdit(name)
        name_edit.setPlaceholderText('Param name (e.g. PrimaryColor)')
        name_edit.setToolTip('Exact UE material parameter name')
        top.addWidget(name_edit, 2)

        type_combo = qtwidgets.QComboBox()
        type_combo.addItems(['linear_color', 'scalar'])
        idx = type_combo.findText(ch_type or 'linear_color')
        if idx >= 0:
            type_combo.setCurrentIndex(idx)
        type_combo.setToolTip(
            'linear_color = Vector parameter (RGBA); scalar = float parameter')
        top.addWidget(type_combo, 1)

        default_edit = qtwidgets.QLineEdit(register_widgets.format_channel_default(default, ch_type))
        default_edit.setPlaceholderText('Default (e.g. 1,0,0,1 or 0.5)')
        default_edit.setToolTip(
            'Default value. Comma-separated R,G,B,A for linear_color; '
            'single float for scalar.')
        top.addWidget(default_edit, 2)

        remove_btn = qtwidgets.QPushButton('x')
        remove_btn.setFixedSize(24, 22)
        remove_btn.setToolTip('Remove this channel')
        remove_btn.clicked.connect(
            lambda: self._remove_specific_row(channels_layout, row))
        top.addWidget(remove_btn)

        outer.addLayout(top)

        # Bottom line: Description label + free-form line edit.
        desc_row = qtwidgets.QHBoxLayout()
        desc_row.setContentsMargins(16, 0, 0, 0)
        desc_row.setSpacing(4)
        desc_label = qtwidgets.QLabel('Description:')
        desc_label.setStyleSheet('color: #888;')
        desc_row.addWidget(desc_label)
        description_edit = qtwidgets.QLineEdit(description)
        description_edit.setPlaceholderText('Short description (optional)')
        description_edit.setToolTip(
            'Optional notes describing what this channel tints. Surfaces '
            'as a tooltip on the Dye Overrides editor.')
        desc_row.addWidget(description_edit, 1)
        outer.addLayout(desc_row)

        row.display_name_edit = display_name_edit
        row.name_edit = name_edit
        row.type_combo = type_combo
        row.default_edit = default_edit
        row.description_edit = description_edit

        channels_layout.addWidget(row)
        return row

    def _collect_channel_rows(self, channels_layout):
        """
        Collect channel definitions from a dye row's channels editor.

        :param QVBoxLayout channels_layout: Channels sub-layout on a dye row.
        :return: List of dicts ``{name, type, default}`` with ``default``
            parsed to a list of floats (linear_color) or float (scalar)
            when possible, else the raw string.
        :rtype: list[dict]
        """

        result = []
        if channels_layout is None:
            return result
        for i in range(channels_layout.count()):
            item = channels_layout.itemAt(i)
            if not item or not item.widget():
                continue
            sub = item.widget()
            name = sub.name_edit.text().strip()
            ch_type = sub.type_combo.currentText()
            default = register_widgets.parse_channel_default(sub.default_edit.text(), ch_type)
            if not name:
                continue
            # ``getattr`` keeps this resilient if a future caller builds
            # a row without the new fields; production rows always have
            # both edits attached.
            display_name = ''
            description = ''
            if getattr(sub, 'display_name_edit', None) is not None:
                display_name = sub.display_name_edit.text().strip()
            if getattr(sub, 'description_edit', None) is not None:
                description = sub.description_edit.text().strip()
            result.append({
                'name': name,
                'display_name': display_name,
                'description': description,
                'type': ch_type,
                'default': default,
            })
        return result

    def _on_is_dye_toggled(self, material_row, checked):
        """
        Mirror an Is Dye toggle into the Dyes tab.

        When checked, ensure a dye row exists with the same ``slot_name``
        as ``material_row``; create one mirroring the material's
        index/name/options if missing. When unchecked, remove any dye row
        that matches by ``slot_name``.

        Slot name is the sync key. If the material has no slot name yet,
        fall back to the display name so a dye row still appears.

        :param QFrame material_row: The material row whose checkbox toggled.
        :param bool checked: New checkbox state.
        """

        dyes_layout = getattr(self, '_dyes_rows_layout', None)
        if dyes_layout is None:
            return
        slot_name = material_row.slot_name_edit.text().strip()
        match_key = slot_name or material_row.name_edit.text().strip()
        if not match_key:
            return

        existing = self._find_dye_row_by_key(match_key)
        if checked and existing is None:
            new_row = self._create_slot_row(
                dyes_layout,
                index=material_row.index_spin.value(),
                name=material_row.name_edit.text(),
                slot_name=slot_name,
                options=material_row.options_edit.text(),
                slot_kind='dye',
            )
            # Auto-fire channel discovery when the DCC wrapper has wired
            # one up (UE). Use ``isHidden()`` rather than ``isVisible()``:
            # the row was created this tick so it has not been painted
            # yet and ``isVisible()`` returns False even after the UE
            # override called ``setVisible(True)``. ``isHidden()`` tracks
            # explicit hide-state instead, so it reflects whether the
            # wrapper unhid the button.
            discover_btn = getattr(new_row, 'discover_btn', None)
            if discover_btn is not None and not discover_btn.isHidden():
                discover_btn.click()
        elif not checked and existing is not None:
            self._remove_specific_row(dyes_layout, existing)

    def _find_dye_row_by_key(self, key):
        """
        Find a dye row whose ``slot_name`` (or fallback ``name``) matches.

        :param str key: Slot name or display name to match.
        :return: The matching dye row frame, or None.
        :rtype: QFrame or None
        """

        dyes_layout = getattr(self, '_dyes_rows_layout', None)
        if dyes_layout is None or not key:
            return None
        for i in range(dyes_layout.count()):
            item = dyes_layout.itemAt(i)
            w = item.widget() if item else None
            if not isinstance(w, qtwidgets.QFrame):
                continue
            slot = getattr(w, 'slot_name_edit', None)
            slot_text = slot.text().strip() if slot else ''
            name = getattr(w, 'name_edit', None)
            name_text = name.text().strip() if name else ''
            if slot_text == key or (not slot_text and name_text == key):
                return w
        return None

    def _setup_path_dcc_buttons(self):
        """
        Hook for DCC wrappers to show and connect the Set and Go buttons
        on the DCC Path and Engine Path rows, and the Auto-Populate button.

        The base implementation does nothing; buttons remain hidden.
        Override in DCC subclasses to make
        ``self.ui.dcc_path_set_pushButton``,
        ``self.ui.engine_path_set_pushButton``, etc. visible and wired
        to editor-specific actions.
        """

        pass

    def _browse_material_slot(self, row_frame):
        """
        Open a file dialog to browse for a material path and set it in
        the options line edit for the given row frame.

        :param QFrame row_frame: The slot row frame with stored widget refs.
        """

        file_path, _ = qtwidgets.QFileDialog.getOpenFileName(
            self, 'Select Material', '', 'All Files (*)')
        if file_path:
            row_frame.options_edit.setText(file_path)

    def _create_texture_row(self, rows_layout, path_text=''):
        """
        Create one horizontal row frame for a texture path.

        :param QVBoxLayout rows_layout: Parent layout to insert row into.
        :param str path_text: Initial texture path text.
        :return: The created row frame.
        :rtype: QFrame
        """

        row_frame = qtwidgets.QFrame()
        row_frame.setFrameShape(qtwidgets.QFrame.StyledPanel)
        row_layout = qtwidgets.QHBoxLayout(row_frame)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(4)

        path_edit = qtwidgets.QLineEdit(path_text)
        path_edit.setPlaceholderText('Texture path...')
        path_edit.setToolTip('Path to texture file')
        row_layout.addWidget(path_edit)

        remove_btn = qtwidgets.QPushButton('x')
        remove_btn.setFixedSize(24, 24)
        remove_btn.setToolTip('Remove this row')
        remove_btn.clicked.connect(lambda: self._remove_specific_row(rows_layout, row_frame))
        row_layout.addWidget(remove_btn)

        stretch_index = rows_layout.count() - 1
        rows_layout.insertWidget(stretch_index, row_frame)

        return row_frame

    def _create_socket_row(self, rows_layout, socket_name=''):
        """
        Create one horizontal row frame for an attach socket.

        :param QVBoxLayout rows_layout: Parent layout to insert row into.
        :param str socket_name: Socket name text.
        :return: The created row frame.
        :rtype: QFrame
        """

        row_frame = qtwidgets.QFrame()
        row_frame.setFrameShape(qtwidgets.QFrame.StyledPanel)
        row_layout = qtwidgets.QHBoxLayout(row_frame)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(4)

        socket_edit = qtwidgets.QLineEdit(socket_name)
        socket_edit.setPlaceholderText('Socket name...')
        socket_edit.setToolTip('Skeleton socket name')

        # Auto-complete from known sockets
        if self._global_data:
            completer = qtwidgets.QCompleter(self._global_data.attach_sockets)
            completer.setCaseSensitivity(qtcore.Qt.CaseInsensitive)
            socket_edit.setCompleter(completer)

        row_layout.addWidget(socket_edit)

        remove_btn = qtwidgets.QPushButton('x')
        remove_btn.setFixedSize(24, 24)
        remove_btn.setToolTip('Remove this row')
        remove_btn.clicked.connect(lambda: self._remove_specific_row(rows_layout, row_frame))
        row_layout.addWidget(remove_btn)

        stretch_index = rows_layout.count() - 1
        rows_layout.insertWidget(stretch_index, row_frame)

        return row_frame

    def _populate_slot_rows(self, rows_layout, slot_data, has_mesh_type=False):
        """
        Fill a materials/dyes/decals row area from entry data.

        ``has_mesh_type`` is retained for compatibility but the row kind
        is now read from the layout's ``slot_kind`` property when set.

        :param QVBoxLayout rows_layout: The rows layout to populate.
        :param list slot_data: List of slot dicts with index, slot_name, options.
        :param bool has_mesh_type: True if rows have a mesh_type field (decals).
        """

        slot_kind = rows_layout.property('slot_kind')
        if not slot_kind:
            slot_kind = 'decal' if has_mesh_type else 'material'

        self._clear_row_layout(rows_layout)
        if not slot_data:
            return

        for row_data in slot_data:
            options = row_data.get('options', [])
            options_text = ', '.join(options) if isinstance(options, list) else str(options)
            mesh_type = row_data.get('mesh_type', '') if slot_kind == 'decal' else None
            self._create_slot_row(
                rows_layout,
                index=row_data.get('index', 0),
                name=row_data.get('name', ''),
                slot_name=row_data.get('slot_name', ''),
                options=options_text,
                mesh_type=mesh_type,
                slot_kind=slot_kind,
                is_dye=bool(row_data.get('is_dye', False)),
                channels=row_data.get('channels') or [],
            )

    def _populate_texture_rows(self, rows_layout, texture_list):
        """
        Fill a texture row area from entry data.

        :param QVBoxLayout rows_layout: The rows layout to populate.
        :param list texture_list: List of texture path strings.
        """

        self._clear_row_layout(rows_layout)
        if not texture_list:
            return

        for tex_path in texture_list:
            self._create_texture_row(rows_layout, path_text=tex_path)

    def _populate_dye_overrides_tab(self, entry):
        """
        Rebuild the Dye Overrides tab from an entry's parent schema.

        The parent asset (looked up by ``entry.built_for``) defines the
        channel set; this entry's ``dye_overrides`` provides current
        values. Each channel gets an Override checkbox plus a typed
        editor (color swatch for ``linear_color``, double spinbox for
        ``scalar``). Unchecking an override drops it from the saved data
        so the runtime applier falls back to the channel default.

        Skips entirely on parent assets (``is_gear == False``); shows a
        contextual hint when there is no schema to render.

        :param entry: The current ``UnifiedAssetEntry`` whose form is
            being populated.
        """

        # Reset prior rebuild state.
        self._clear_row_layout(self._dye_overrides_rows_layout)
        self._dye_override_editors = []

        if entry is None or not entry.is_gear:
            self._dye_overrides_hint.setText(
                'Dye overrides only apply to gear variants. Set Built For '
                'on the Parent Asset tab to a parent that defines dye '
                'channels, then return here to tint them.')
            self._dye_overrides_hint.setVisible(True)
            return

        parent = self._resolve_parent_entry(entry)
        # Variants whose parent is missing or undeclared can still store
        # overrides, but only if the variant declares its own dyes
        # schema (uncommon — usually the parent owns the schema).
        schema_source = parent if (parent and parent.dyes) else entry
        slots_with_channels = [
            d for d in schema_source.dyes
            if d.get('slot_name') and (d.get('channels') or [])
        ]
        if not slots_with_channels:
            if parent is None and entry.built_for:
                msg = (f'Could not find parent asset "{entry.built_for}" '
                       f'in the {entry.category} registry.')
            elif parent is not None and not parent.dyes:
                msg = (f'Parent asset "{parent.name}" has no dye channels. '
                       'Add channels on the parent\'s Dyes tab first.')
            else:
                msg = ('No dye channels declared. Add them on the parent '
                       'asset\'s Dyes tab (or this entry\'s Dyes tab).')
            self._dye_overrides_hint.setText(msg)
            self._dye_overrides_hint.setVisible(True)
            return

        self._dye_overrides_hint.setVisible(False)

        overrides = entry.dye_overrides
        for dye in slots_with_channels:
            self._build_dye_override_slot(
                slot_name=dye.get('slot_name', ''),
                slot_display=dye.get('name', '') or dye.get('slot_name', ''),
                channels=dye.get('channels') or [],
                slot_overrides=overrides.get(dye.get('slot_name', '')) or {},
            )

    def _build_dye_override_slot(self, slot_name, slot_display, channels,
                                 slot_overrides):
        """
        Build one slot group (a QGroupBox per material slot) inside the
        Dye Overrides tab.

        Each channel inside the group gets its own typed editor row.
        Editor descriptors are appended to ``self._dye_override_editors``
        so collection later does not need to walk widget trees.

        :param str slot_name: Material slot name (sync key).
        :param str slot_display: Pretty title (falls back to slot_name).
        :param list channels: Channel schema list from the parent's dyes.
        :param dict slot_overrides: Existing per-channel values for this
            slot on the variant.
        """

        title = slot_display
        if slot_display and slot_name and slot_display != slot_name:
            title = f'{slot_display}  ({slot_name})'
        group = qtwidgets.QGroupBox(title)
        group.setToolTip(f'Channels exposed by slot "{slot_name}".')
        gv = qtwidgets.QVBoxLayout(group)
        gv.setContentsMargins(6, 6, 6, 6)
        gv.setSpacing(2)

        for ch in channels:
            ch_name = ch.get('name', '')
            ch_type = ch.get('type', '') or 'linear_color'
            if not ch_name:
                continue
            has_override = ch_name in slot_overrides
            current_value = slot_overrides.get(ch_name, ch.get('default'))
            editor_row, getter = self._build_channel_editor(
                ch_name, ch_type, current_value, has_override,
                display_name=ch.get('display_name', '') or '',
                description=ch.get('description', '') or '')
            gv.addWidget(editor_row)
            self._dye_override_editors.append(
                (slot_name, ch_name, ch_type, editor_row.override_check, getter))

        # Insert before the trailing stretch so groups stack from the top.
        stretch_index = self._dye_overrides_rows_layout.count() - 1
        self._dye_overrides_rows_layout.insertWidget(stretch_index, group)

    def _build_channel_editor(self, ch_name, ch_type, current_value, has_override,
                              display_name='', description=''):
        """
        Build a single channel editor row with an Override checkbox plus
        a typed value widget.

        Returns the row frame (with ``override_check`` attached) and a
        zero-arg getter that yields the current value (or ``None`` when
        the override is off).

        :param str ch_name: Channel/parameter name (UE binding).
        :param str ch_type: ``linear_color`` or ``scalar``.
        :param current_value: Initial value (override if set, else default).
        :param bool has_override: Whether the override checkbox starts checked.
        :param str display_name: Friendly label authored on the parent's
            channel; falls back to ``ch_name`` when empty.
        :param str description: Optional channel notes; surfaces as a
            tooltip on the row label.
        :return: Tuple ``(row_frame, getter)``.
        :rtype: tuple
        """

        row = qtwidgets.QFrame()
        row.setFrameShape(qtwidgets.QFrame.NoFrame)
        h = qtwidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        override_check = qtwidgets.QCheckBox()
        override_check.setToolTip(
            'Override this channel for this variant. When unchecked, the '
            'parent asset\'s default applies at runtime.')
        override_check.setChecked(has_override)
        h.addWidget(override_check)

        # Show the friendly name when the parent's channel author set
        # one; the UE param name comes second in parens so artists still
        # see exactly what binding the override targets.
        if display_name and display_name != ch_name:
            label_text = f'{display_name}  ({ch_name})'
        else:
            label_text = ch_name
        name_label = qtwidgets.QLabel(label_text)
        name_label.setMinimumWidth(160)
        if description:
            name_label.setToolTip(description)
        h.addWidget(name_label, 2)

        type_label = qtwidgets.QLabel(f'[{ch_type}]')
        type_label.setStyleSheet('color: #888;')
        h.addWidget(type_label)

        if ch_type == 'linear_color':
            editor, getter = self._build_color_channel_editor(current_value)
        elif ch_type == 'scalar':
            editor, getter = self._build_scalar_channel_editor(current_value)
        else:
            # Unknown type: surface the raw value as text so nothing
            # silently disappears from the registry.
            editor = qtwidgets.QLineEdit(str(current_value or ''))
            editor.setToolTip(f'Unknown channel type "{ch_type}"; stored as string.')
            getter = (lambda e=editor: e.text())
        h.addWidget(editor, 3)

        # Disable editor when override is off; flip on toggle so the user
        # gets visual feedback that the value isn't being saved.
        editor.setEnabled(has_override)
        override_check.toggled.connect(editor.setEnabled)

        row.override_check = override_check
        return row, getter

    def _build_color_channel_editor(self, current_value):
        """
        Build a swatch-button + alpha-spinbox pair for ``linear_color``.

        The swatch shows the current RGB and opens a QColorDialog on
        click. Alpha lives in its own spinbox so users can edit it
        without going through the color dialog.

        :param current_value: Initial 4-element list (RGBA), or None.
        :return: Tuple ``(editor_widget, getter)``.
        :rtype: tuple
        """

        rgba = register_widgets.coerce_rgba(current_value)
        container = qtwidgets.QWidget()
        c_layout = qtwidgets.QHBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(4)

        swatch = qtwidgets.QPushButton()
        swatch.setFixedSize(64, 22)
        swatch.setToolTip('Click to pick RGB. Alpha edits via the next field.')

        # Mutable holder so the lambda closures can mutate the displayed
        # value without rebinding the variable in this scope.
        state = {'rgba': list(rgba)}

        def _refresh_swatch():
            r = max(0, min(255, int(round(state['rgba'][0] * 255))))
            g = max(0, min(255, int(round(state['rgba'][1] * 255))))
            b = max(0, min(255, int(round(state['rgba'][2] * 255))))
            swatch.setStyleSheet(
                f'QPushButton {{ background-color: rgb({r},{g},{b}); '
                f'border: 1px solid #444; }}')

        def _pick_color():
            dlg = qtwidgets.QColorDialog(self)
            dlg.setOption(qtwidgets.QColorDialog.ShowAlphaChannel, False)
            r, g, b = state['rgba'][0], state['rgba'][1], state['rgba'][2]
            initial = qtgui.QColor.fromRgbF(
                max(0.0, min(1.0, r)),
                max(0.0, min(1.0, g)),
                max(0.0, min(1.0, b)))
            dlg.setCurrentColor(initial)
            if dlg.exec_() == qtwidgets.QDialog.Accepted:
                picked = dlg.currentColor()
                state['rgba'][0] = picked.redF()
                state['rgba'][1] = picked.greenF()
                state['rgba'][2] = picked.blueF()
                _refresh_swatch()

        swatch.clicked.connect(_pick_color)
        c_layout.addWidget(swatch)

        alpha_spin = qtwidgets.QDoubleSpinBox()
        alpha_spin.setRange(0.0, 1.0)
        alpha_spin.setSingleStep(0.05)
        alpha_spin.setDecimals(3)
        alpha_spin.setValue(state['rgba'][3])
        alpha_spin.setToolTip('Alpha component (0..1).')
        alpha_spin.setFixedWidth(72)

        def _on_alpha_changed(v):
            state['rgba'][3] = float(v)

        alpha_spin.valueChanged.connect(_on_alpha_changed)
        c_layout.addWidget(qtwidgets.QLabel('A'))
        c_layout.addWidget(alpha_spin)

        _refresh_swatch()

        getter = lambda: list(state['rgba'])
        return container, getter

    def _build_scalar_channel_editor(self, current_value):
        """
        Build a QDoubleSpinBox for ``scalar`` channels.

        Range is intentionally wide (-1e6..1e6) so unusual scalar params
        (e.g. tiling, offsets) aren't clamped; tighten on a per-asset
        basis later if it becomes a footgun.

        :param current_value: Initial value (float / int / None).
        :return: Tuple ``(spinbox, getter)``.
        :rtype: tuple
        """

        spin = qtwidgets.QDoubleSpinBox()
        spin.setRange(-1e6, 1e6)
        spin.setDecimals(4)
        spin.setSingleStep(0.05)
        try:
            spin.setValue(float(current_value) if current_value is not None else 0.0)
        except (TypeError, ValueError):
            spin.setValue(0.0)
        getter = (lambda s=spin: float(s.value()))
        return spin, getter

    def _collect_dye_overrides(self):
        """
        Read the Dye Overrides tab into a ``dye_overrides`` dict.

        Only channels whose Override checkbox is checked are emitted;
        unchecked channels round-trip as the parent default at runtime.

        :return: ``{slot_name: {channel_name: value}}``.
        :rtype: dict
        """

        result = {}
        for slot_name, ch_name, ch_type, override_check, getter in self._dye_override_editors:
            if not override_check.isChecked():
                continue
            try:
                value = getter()
            except Exception as exc:
                logger.warning(
                    f'Dye override "{slot_name}.{ch_name}" read failed: {exc}')
                continue
            result.setdefault(slot_name, {})[ch_name] = value
        return result

    def _populate_socket_rows(self, rows_layout, socket_list):
        """
        Fill a socket row area from entry data.

        :param QVBoxLayout rows_layout: The rows layout to populate.
        :param list socket_list: List of socket name strings.
        """

        self._clear_row_layout(rows_layout)
        if not socket_list:
            return

        for socket_name in socket_list:
            self._create_socket_row(rows_layout, socket_name=socket_name)

    def _collect_slot_rows(self, rows_layout, has_mesh_type=False):
        """
        Collect material/dye/decal data from row frames.

        Reads widget values via stored references on each frame
        (``row_frame.index_spin``, ``row_frame.name_edit``, etc.).

        :param QVBoxLayout rows_layout: Layout containing row frames.
        :param bool has_mesh_type: True if rows have a mesh_type field.
        :return: List of slot dicts.
        :rtype: list[dict]
        """

        result = []
        for i in range(rows_layout.count()):
            item = rows_layout.itemAt(i)
            if not item or not item.widget():
                continue
            row_frame = item.widget()
            if not isinstance(row_frame, qtwidgets.QFrame):
                continue

            # Read values from stored widget references
            index_val = getattr(row_frame, 'index_spin', None)
            index_val = index_val.value() if index_val else 0

            name_edit = getattr(row_frame, 'name_edit', None)
            display_name = name_edit.text() if name_edit else ''

            slot_name_edit = getattr(row_frame, 'slot_name_edit', None)
            slot_name = slot_name_edit.text() if slot_name_edit else ''

            options_edit = getattr(row_frame, 'options_edit', None)
            options_text = options_edit.text() if options_edit else ''
            options = [o.strip() for o in options_text.split(',') if o.strip()]

            entry_dict = {
                'index': index_val,
                'name': display_name,
                'slot_name': slot_name,
                'options': options,
            }

            row_kind = getattr(row_frame, 'slot_kind', None)

            if has_mesh_type or row_kind == 'decal':
                mesh_edit = getattr(row_frame, 'mesh_edit', None)
                entry_dict['mesh_type'] = mesh_edit.text() if mesh_edit else ''

            # Material rows persist their is_dye flag so the Materials tab
            # can render the correct checkbox state on next load.
            is_dye_check = getattr(row_frame, 'is_dye_check', None)
            if is_dye_check is not None:
                entry_dict['is_dye'] = bool(is_dye_check.isChecked())

            # Dye rows persist their channels list.
            channels_layout = getattr(row_frame, 'channels_layout', None)
            if channels_layout is not None:
                entry_dict['channels'] = self._collect_channel_rows(channels_layout)

            result.append(entry_dict)

        return result

    def _collect_texture_rows(self, rows_layout):
        """
        Collect texture paths from row frames.

        :param QVBoxLayout rows_layout: Layout containing texture row frames.
        :return: List of texture path strings.
        :rtype: list[str]
        """

        result = []
        for i in range(rows_layout.count()):
            item = rows_layout.itemAt(i)
            if not item or not item.widget():
                continue
            row_frame = item.widget()
            if not isinstance(row_frame, qtwidgets.QFrame):
                continue

            row_layout = row_frame.layout()
            if not row_layout:
                continue

            for j in range(row_layout.count()):
                w = row_layout.itemAt(j).widget()
                if isinstance(w, qtwidgets.QLineEdit):
                    text = w.text().strip()
                    if text:
                        result.append(text)
                    break

        return result

    def _collect_socket_rows(self, rows_layout):
        """
        Collect socket names from row frames.

        :param QVBoxLayout rows_layout: Layout containing socket row frames.
        :return: List of socket name strings.
        :rtype: list[str]
        """

        result = []
        for i in range(rows_layout.count()):
            item = rows_layout.itemAt(i)
            if not item or not item.widget():
                continue
            row_frame = item.widget()
            if not isinstance(row_frame, qtwidgets.QFrame):
                continue

            row_layout = row_frame.layout()
            if not row_layout:
                continue

            for j in range(row_layout.count()):
                w = row_layout.itemAt(j).widget()
                if isinstance(w, qtwidgets.QLineEdit):
                    text = w.text().strip()
                    if text:
                        result.append(text)
                    break

        return result

    def _add_socket(self):
        """
        Add the selected or typed socket name to the sockets row area.

        If the user typed a new name that is not in the dropdown, it is
        added to the combobox so it remains available during this session.
        """

        socket = self._socket_comboBox.currentText().strip()
        if not socket:
            return

        # Avoid duplicates in the row list
        existing = self._collect_socket_rows(self._sockets_rows_layout)
        if socket not in existing:
            self._create_socket_row(self._sockets_rows_layout, socket_name=socket)

        # If user typed a new name, add it to the dropdown for this session
        if self._socket_comboBox.findText(socket) < 0:
            self._socket_comboBox.addItem(socket)

    def _add_slot_row(self, rows_layout, slot_kind='material'):
        """
        Add an empty slot row to a rows layout.

        Accepts the legacy ``has_mesh_type`` boolean for backward
        compatibility (True is treated as decal kind).

        :param QVBoxLayout rows_layout: Target row layout.
        :param slot_kind: ``material``, ``dye``, or ``decal``. ``True`` is
            also accepted as a legacy alias for ``decal``.
        """

        if slot_kind is True:
            slot_kind = 'decal'
        elif slot_kind is False or slot_kind is None:
            slot_kind = rows_layout.property('slot_kind') or 'material'

        # Count existing row frames for auto-index
        count = self._count_row_frames(rows_layout)
        mesh_type = '' if slot_kind == 'decal' else None
        self._create_slot_row(rows_layout, index=count, mesh_type=mesh_type,
                              slot_kind=slot_kind)

    def _add_texture_row(self, rows_layout):
        """
        Add an empty texture path row to a rows layout.

        :param QVBoxLayout rows_layout: Target row layout.
        """

        self._create_texture_row(rows_layout)

    def _remove_slot_row(self, rows_layout):
        """
        Remove the last row frame from a rows layout.

        :param QVBoxLayout rows_layout: Target row layout.
        """

        # Find the last QFrame in the layout (before the stretch)
        last_frame = None
        last_index = -1
        for i in range(rows_layout.count()):
            item = rows_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), qtwidgets.QFrame):
                last_frame = item.widget()
                last_index = i

        if last_frame and last_index >= 0:
            rows_layout.takeAt(last_index)
            last_frame.deleteLater()

    def _remove_specific_row(self, rows_layout, row_frame):
        """
        Remove a specific row frame from its layout.

        :param QVBoxLayout rows_layout: Parent layout.
        :param QFrame row_frame: The row frame to remove.
        """

        index = rows_layout.indexOf(row_frame)
        if index >= 0:
            rows_layout.takeAt(index)
            row_frame.deleteLater()

    def _clear_row_layout(self, rows_layout):
        """
        Remove all row frame widgets from a rows layout, preserving the
        trailing stretch item.

        :param QVBoxLayout rows_layout: Layout to clear.
        """

        frames_to_remove = []
        for i in range(rows_layout.count()):
            item = rows_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), qtwidgets.QFrame):
                frames_to_remove.append(i)

        # Remove in reverse order so indices stay valid
        for i in reversed(frames_to_remove):
            widget = rows_layout.itemAt(i).widget()
            rows_layout.takeAt(i)
            widget.deleteLater()

    def _count_row_frames(self, rows_layout):
        """
        Count the number of QFrame row widgets in a rows layout.

        :param QVBoxLayout rows_layout: Layout to inspect.
        :return: Number of row frames.
        :rtype: int
        """

        count = 0
        for i in range(rows_layout.count()):
            item = rows_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), qtwidgets.QFrame):
                count += 1
        return count
