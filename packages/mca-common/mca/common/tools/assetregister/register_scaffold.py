"""
Builds the window layout: every widget, tab and menu the register owns.

Part of the Unified Asset Register, split out of ``unified_register`` so each
area of the window is readable on its own. The methods are unchanged; they run
on :class:`unified_register.UnifiedRegisterUI`, which mixes this class in, and
rely on the attributes that class builds.

:Requires: mca.common.pyqt, mca.common.assetlist
"""

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_paths, unified_entry
from mca.common.pyqt.pygui import qtcore, qtwidgets
from mca.common.pyqt.qt_utils import qt_menus
from mca.common.tools.assetregister import register_widgets


logger = log.MCA_LOGGER


class ScaffoldMixin:
    """
    Builds the window layout: every widget, tab and menu the register owns.

    Mixed into :class:`unified_register.UnifiedRegisterUI`; never instantiated
    on its own.
    """

    # --- UI scaffold (replaces unified_register.ui) ------------------------ #

    def _build_ui_scaffold(self):
        """
        Build the entire form scaffold in Python code.

        Layout: Tree on LEFT with preview info below, form groups on RIGHT
        top, detail tabs on RIGHT bottom. QUiLoader is not used because it
        freezes in Unreal Engine 5.5+.

        All self.ui.xxx widget names are preserved for downstream compatibility
        (e.g. ue_asset_register.py UE wrapper).
        """

        self.ui = register_widgets.UiNamespace()

        # --- Central widget ------------------------------------------------ #
        central = qtwidgets.QWidget()
        main_layout = qtwidgets.QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)
        self.setCentralWidget(central)

        # --- Main horizontal splitter (tree left / form+tabs right) -------- #
        self.ui.main_splitter = qtwidgets.QSplitter(qtcore.Qt.Horizontal)
        main_layout.addWidget(self.ui.main_splitter)

        # ================================================================== #
        #  LEFT SIDE: Asset Tree + Preview Info Panel (resizable splitter)
        # ================================================================== #
        left_panel = qtwidgets.QWidget()
        left_panel.setMinimumWidth(320)
        left_vlayout = qtwidgets.QVBoxLayout(left_panel)
        left_vlayout.setContentsMargins(0, 0, 0, 0)
        self.ui.main_splitter.addWidget(left_panel)

        # Vertical splitter: tree area (top) / preview panel (bottom)
        self.ui.left_splitter = qtwidgets.QSplitter(qtcore.Qt.Vertical)
        left_vlayout.addWidget(self.ui.left_splitter)

        # -- Top: tree header + filter + tree widget ------------------------ #
        tree_container = qtwidgets.QWidget()
        tree_vlayout = qtwidgets.QVBoxLayout(tree_container)
        tree_vlayout.setContentsMargins(4, 4, 4, 0)
        self.ui.left_splitter.addWidget(tree_container)

        # --- Browse controls -------------------------------------------- #
        # The category lives here rather than in the asset form because it
        # decides which registry the tree shows; the form only displays it.
        # Keeping "what am I looking at" apart from "what am I editing" is
        # what stops a category switch from reading as an edit to the asset.
        browse_group = qtwidgets.QGroupBox('Browse')
        browse_form = qtwidgets.QFormLayout(browse_group)
        browse_form.setFieldGrowthPolicy(qtwidgets.QFormLayout.ExpandingFieldsGrow)
        tree_vlayout.addWidget(browse_group)

        # Category: picks which .alist the tree shows and drives every cascade.
        # Paired with a "+" button to let users register a new category on the fly,
        # which also bootstraps an empty .alist file for it.
        cat_row = qtwidgets.QHBoxLayout()
        self.ui.category_comboBox = qtwidgets.QComboBox()
        self.ui.category_comboBox.setToolTip('Primary asset category (e.g. Characters, Armor, Weapons, Props).')
        self.ui.category_comboBox.setMinimumWidth(150)
        cat_row.addWidget(self.ui.category_comboBox)
        self.ui.add_category_pushButton = qtwidgets.QPushButton('+')
        self.ui.add_category_pushButton.setToolTip(
            'Add a new asset category (creates a new .alist file)')
        self.ui.add_category_pushButton.setMaximumSize(24, 24)
        cat_row.addWidget(self.ui.add_category_pushButton)
        browse_form.addRow('Category:', cat_row)
        # Is Gear flag for the selected category. Stored on the category
        # itself (not per-asset), so toggling here mutates the shared config
        # and affects every asset in that category. Gear categories inject
        # a top-level "Gear/" segment into generated asset paths.
        self.ui.is_gear_checkBox = qtwidgets.QCheckBox('Is Gear')
        self.ui.is_gear_checkBox.setToolTip(
            'Mark the selected category as part of the gear system. '
            'Gear categories prefix all asset paths with the gear root folder.')

        # Gear root override. Fills in with the category's start folder when
        # "Is Gear" is checked so the user can see, and change, where gear
        # paths begin. Relative to the asset list root, e.g. 'Gear' or
        # 'Characters/Gear'. Persisted on the category like the flag itself.
        self.ui.gear_root_lineEdit = qtwidgets.QLineEdit()
        self.ui.gear_root_lineEdit.setPlaceholderText(asset_paths.DEFAULT_GEAR_ROOT)
        self.ui.gear_root_lineEdit.setToolTip(
            'Relative folder gear paths for this category start under. Filled in when '
            '"Is Gear" is checked; edit to override (e.g. "Characters/Gear"). '
            'Saved on the category, so it applies to every asset in it.')
        self.ui.gear_root_lineEdit.setEnabled(False)
        # Folder picker so the root does not have to be typed. The chosen folder
        # is stored relative to the project root, matching the text field.
        self.ui.gear_root_browse_pushButton = qtwidgets.QPushButton('...')
        self.ui.gear_root_browse_pushButton.setToolTip(
            'Browse for the folder gear paths start under (stored relative to the project root)')
        self.ui.gear_root_browse_pushButton.setFixedWidth(30)
        self.ui.gear_root_browse_pushButton.setEnabled(False)
        gear_row = qtwidgets.QHBoxLayout()
        gear_row.addWidget(self.ui.is_gear_checkBox)
        gear_row.addWidget(self.ui.gear_root_lineEdit, 1)
        gear_row.addWidget(self.ui.gear_root_browse_pushButton)
        browse_form.addRow('', gear_row)

        tree_vlayout.addWidget(qtwidgets.QLabel('Asset Tree'))

        filter_row = qtwidgets.QHBoxLayout()
        filter_row.addWidget(qtwidgets.QLabel('Filter:'))
        self.ui.tree_filter_lineEdit = qtwidgets.QLineEdit()
        self.ui.tree_filter_lineEdit.setToolTip('Type to filter the asset tree by name.')
        self.ui.tree_filter_lineEdit.setPlaceholderText('Search assets...')
        filter_row.addWidget(self.ui.tree_filter_lineEdit, 1)
        # "shown of total" so a filtered view is never mistaken for an empty category.
        self.ui.tree_count_label = qtwidgets.QLabel('')
        self.ui.tree_count_label.setToolTip('Assets shown / assets in this category.')
        filter_row.addWidget(self.ui.tree_count_label)
        tree_vlayout.addLayout(filter_row)

        # Sub-category / faction filters. They only hide tree rows and never
        # touch the asset form. Options come from the loaded entries, so the
        # lists offer only values that exist in this category, and the
        # faction list narrows to what the chosen sub-category contains.
        filter_combo_row = qtwidgets.QHBoxLayout()
        filter_combo_row.addWidget(qtwidgets.QLabel('Sub:'))
        self.ui.tree_subcategory_comboBox = qtwidgets.QComboBox()
        self.ui.tree_subcategory_comboBox.setToolTip('Show only assets with this sub-category.')
        self.ui.tree_subcategory_comboBox.addItem(register_widgets.TREE_FILTER_ALL)
        filter_combo_row.addWidget(self.ui.tree_subcategory_comboBox, 1)
        filter_combo_row.addWidget(qtwidgets.QLabel('Faction:'))
        self.ui.tree_faction_comboBox = qtwidgets.QComboBox()
        self.ui.tree_faction_comboBox.setToolTip(
            'Show only assets with this faction. Narrows to the factions present in the selected sub-category.')
        self.ui.tree_faction_comboBox.addItem(register_widgets.TREE_FILTER_ALL)
        filter_combo_row.addWidget(self.ui.tree_faction_comboBox, 1)
        tree_vlayout.addLayout(filter_combo_row)

        # Placeholder layout for the QTreeWidget (built in _build_asset_tree)
        self.ui.tree_content_layout = qtwidgets.QVBoxLayout()
        tree_vlayout.addLayout(self.ui.tree_content_layout, 1)

        # -- Bottom: preview panel container ----------------------------------- #
        preview_container = qtwidgets.QWidget()
        preview_container_layout = qtwidgets.QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)
        preview_container_layout.setSpacing(4)
        self.ui.left_splitter.addWidget(preview_container)

        # Horizontal splitter inside: thumbnail (left) | info labels (right)
        self.ui.preview_splitter = qtwidgets.QSplitter(qtcore.Qt.Horizontal)
        self.ui.preview_splitter.setMinimumHeight(80)
        preview_container_layout.addWidget(self.ui.preview_splitter, 1)

        # Thumbnail on the left
        self.ui.info_thumbnail_label = qtwidgets.QLabel('No Image')
        self.ui.info_thumbnail_label.setMinimumSize(80, 80)
        self.ui.info_thumbnail_label.setAlignment(qtcore.Qt.AlignCenter)
        self.ui.info_thumbnail_label.setFrameShape(qtwidgets.QFrame.StyledPanel)
        self.ui.preview_splitter.addWidget(self.ui.info_thumbnail_label)

        # Info labels on the right
        info_labels_widget = qtwidgets.QWidget()
        info_labels_layout = qtwidgets.QVBoxLayout(info_labels_widget)
        info_labels_layout.setContentsMargins(4, 4, 4, 4)
        info_labels_layout.setSpacing(2)

        self.ui.info_name_label = qtwidgets.QLabel('Asset Name:')
        self.ui.info_category_label = qtwidgets.QLabel('Asset Category:')
        # Reports variant_of - whether this character is a restyle of another.
        # It used to report bool(built_for), which is the test for *gear*, so a
        # hat read "Is a Variant: True". Variants are a real and separate thing
        # now, and this line says which one this is.
        self.ui.info_variant_label = qtwidgets.QLabel('Variant Of:')
        self.ui.info_path_label = qtwidgets.QLabel('Asset Path:')
        self.ui.info_id_label = qtwidgets.QLabel('Asset Id:')

        for lbl in (self.ui.info_name_label, self.ui.info_category_label,
                     self.ui.info_variant_label, self.ui.info_path_label,
                     self.ui.info_id_label):
            lbl.setWordWrap(True)
            info_labels_layout.addWidget(lbl)

        info_labels_layout.addStretch()
        self.ui.preview_splitter.addWidget(info_labels_widget)

        # Default: thumbnail gets ~1/3, labels get ~2/3
        self.ui.preview_splitter.setSizes([120, 200])

        # Capture Image button (below the preview splitter)
        self.ui.capture_image_pushButton = qtwidgets.QPushButton('Capture Image')
        self.ui.capture_image_pushButton.setToolTip(
            'Capture a viewport screenshot and save it as the asset icon.')
        preview_container_layout.addWidget(self.ui.capture_image_pushButton)

        # Give tree most of the space, preview gets a reasonable default
        self.ui.left_splitter.setSizes([400, 180])

        # ================================================================== #
        #  RIGHT SIDE: Vertical splitter (form top / tabs bottom)
        # ================================================================== #
        self.ui.vertical_splitter = qtwidgets.QSplitter(qtcore.Qt.Vertical)
        self.ui.main_splitter.addWidget(self.ui.vertical_splitter)

        # --- Scrollable Form Area ------------------------------------------ #
        form_scroll = qtwidgets.QScrollArea()
        form_scroll.setWidgetResizable(True)
        self.ui.vertical_splitter.addWidget(form_scroll)

        form_contents = qtwidgets.QWidget()
        form_layout = qtwidgets.QVBoxLayout(form_contents)
        form_layout.setSpacing(6)
        form_scroll.setWidget(form_contents)

        # --- Identity group ------------------------------------------------ #
        identity_group = qtwidgets.QGroupBox('Identity')
        identity_group.setToolTip('Core identity fields for the asset')
        identity_form = qtwidgets.QFormLayout(identity_group)
        identity_form.setFieldGrowthPolicy(qtwidgets.QFormLayout.ExpandingFieldsGrow)
        form_layout.addWidget(identity_group)

        # Category is chosen in the Browse panel on the left; the form only
        # shows which category the asset belongs to. Moving an asset between
        # categories goes through the Transfer action.
        self.ui.category_display_lineEdit = qtwidgets.QLineEdit()
        self.ui.category_display_lineEdit.setReadOnly(True)
        self.ui.category_display_lineEdit.setToolTip(
            'Category the asset belongs to. Pick the category in the Browse panel on '
            'the left; use Transfer to move an asset to another category.')
        identity_form.addRow('Category:', self.ui.category_display_lineEdit)

        # Name
        self.ui.name_lineEdit = qtwidgets.QLineEdit()
        self.ui.name_lineEdit.setToolTip(
            'Display name for the asset. Use underscores between words '
            '(e.g. Hyena_Helmet). The Asset ID and paths are auto-generated.')
        self.ui.name_lineEdit.setPlaceholderText('e.g. Hyena_Helmet')
        identity_form.addRow('Asset Name:', self.ui.name_lineEdit)

        # ID (read-only)
        self.ui.id_lineEdit = qtwidgets.QLineEdit()
        self.ui.id_lineEdit.setToolTip('Unique identifier auto-generated from the Asset Name.')
        self.ui.id_lineEdit.setReadOnly(True)
        self.ui.id_lineEdit.setPlaceholderText('Auto-generated')
        identity_form.addRow('Asset ID:', self.ui.id_lineEdit)

        # Description
        desc_label = qtwidgets.QLabel('Description:')
        desc_label.setAlignment(qtcore.Qt.AlignLeading | qtcore.Qt.AlignLeft | qtcore.Qt.AlignTop)
        self.ui.description_textEdit = qtwidgets.QTextEdit()
        self.ui.description_textEdit.setToolTip('Detailed description of the asset.')
        self.ui.description_textEdit.setMinimumHeight(60)
        sp = self.ui.description_textEdit.sizePolicy()
        sp.setVerticalStretch(1)
        self.ui.description_textEdit.setSizePolicy(sp)
        identity_form.addRow(desc_label, self.ui.description_textEdit)

        # Image path + browse
        image_row = qtwidgets.QHBoxLayout()
        self.ui.image_lineEdit = qtwidgets.QLineEdit()
        self.ui.image_lineEdit.setToolTip('Relative path to the asset icon/thumbnail image.')
        self.ui.image_lineEdit.setPlaceholderText('Icons/Category/asset.jpg')
        image_row.addWidget(self.ui.image_lineEdit)
        self.ui.image_browse_pushButton = qtwidgets.QPushButton('...')
        self.ui.image_browse_pushButton.setToolTip('Browse for an image file')
        self.ui.image_browse_pushButton.setMaximumWidth(30)
        image_row.addWidget(self.ui.image_browse_pushButton)
        identity_form.addRow('Image:', image_row)

        # --- Sub-tabs: Classification / Hierarchy / Paths ------------------ #
        self.ui.form_tabWidget = qtwidgets.QTabWidget()
        form_layout.addWidget(self.ui.form_tabWidget)

        # -- Classification tab --------------------------------------------- #
        # Classification fields live in a drag-reorderable QListWidget so the
        # user can control both WHICH fields appear in the asset folder path
        # (per-row "In Path" checkbox) AND the ORDER they appear in (drag
        # rows up/down). The field widgets themselves (comboboxes and the
        # "+" add buttons) are stored on ``self.ui`` so the rest of the code
        # can reference them unchanged.
        class_tab = qtwidgets.QWidget()
        class_v = qtwidgets.QVBoxLayout(class_tab)
        class_v.setContentsMargins(6, 6, 6, 6)
        class_v.setSpacing(4)
        self.ui.form_tabWidget.addTab(class_tab, 'Classification')

        # The list widget hosts one row per orderable classification field.
        # Uses a custom subclass that signals reorder requests instead of
        # letting Qt perform a destructive InternalMove on rows whose widgets
        # are installed via setItemWidget (which crashes Qt6's post-drop
        # layout; see register_widgets.ReorderableClassificationList docstring).
        self.ui.classification_listWidget = register_widgets.ReorderableClassificationList()
        self.ui.classification_listWidget.setDragDropMode(
            qtwidgets.QAbstractItemView.InternalMove)
        self.ui.classification_listWidget.setDefaultDropAction(qtcore.Qt.MoveAction)
        self.ui.classification_listWidget.setSelectionMode(
            qtwidgets.QAbstractItemView.SingleSelection)
        self.ui.classification_listWidget.setSpacing(2)
        self.ui.classification_listWidget.setFocusPolicy(qtcore.Qt.NoFocus)
        self.ui.classification_listWidget.setMinimumHeight(210)
        self.ui.classification_listWidget.setToolTip(
            'Drag rows to reorder. Classification fields appear in the asset '
            'path in the order shown here.')
        # Map from field_key -> row widget, used to rebuild the list in a
        # particular order without destroying the input widgets.
        self._classification_rows = {}

        # --- Sub Category ---
        self.ui.sub_category_comboBox = qtwidgets.QComboBox()
        self.ui.sub_category_comboBox.setToolTip('Sub-grouping within the category.')
        self.ui.sub_category_comboBox.setMinimumWidth(150)
        self.ui.add_sub_category_pushButton = qtwidgets.QPushButton('+')
        self.ui.add_sub_category_pushButton.setToolTip('Add a new sub-category')
        self.ui.add_sub_category_pushButton.setMaximumSize(24, 24)
        self.ui.subtype_in_path_checkBox = qtwidgets.QCheckBox('In Path')
        self.ui.subtype_in_path_checkBox.setToolTip(
            'Include sub-category in the asset folder path.')
        self.ui.subtype_in_path_checkBox.setChecked(True)
        self._classification_rows['subtype'] = self._build_classification_row(
            field_key='subtype',
            label='Sub Category',
            input_widget=self.ui.sub_category_comboBox,
            add_button=self.ui.add_sub_category_pushButton,
            in_path_checkbox=self.ui.subtype_in_path_checkBox,
        )

        # --- Faction ---
        self.ui.faction_comboBox = qtwidgets.QComboBox()
        self.ui.faction_comboBox.setToolTip('Faction or group the asset belongs to.')
        self.ui.faction_comboBox.setMinimumWidth(150)
        self.ui.add_faction_pushButton = qtwidgets.QPushButton('+')
        self.ui.add_faction_pushButton.setToolTip('Add a new faction')
        self.ui.add_faction_pushButton.setMaximumSize(24, 24)
        self.ui.faction_in_path_checkBox = qtwidgets.QCheckBox('In Path')
        self.ui.faction_in_path_checkBox.setToolTip(
            'Include faction in the asset folder path.')
        self.ui.faction_in_path_checkBox.setChecked(True)
        self._classification_rows['faction'] = self._build_classification_row(
            field_key='faction',
            label='Faction',
            input_widget=self.ui.faction_comboBox,
            add_button=self.ui.add_faction_pushButton,
            in_path_checkbox=self.ui.faction_in_path_checkBox,
        )

        # --- Gender ---
        self.ui.gender_comboBox = qtwidgets.QComboBox()
        self.ui.gender_comboBox.setToolTip(
            'Gender tag (optional; toggle "In Path" to include in folder structure).')
        self.ui.gender_comboBox.setMinimumWidth(150)
        # Fixed list; empty string is the "None / unset" choice
        self.ui.gender_comboBox.addItems(['', 'Male', 'Female', 'Neutral'])
        self.ui.gender_in_path_checkBox = qtwidgets.QCheckBox('In Path')
        self.ui.gender_in_path_checkBox.setToolTip(
            'Include gender in the asset folder path.')
        self.ui.gender_in_path_checkBox.setChecked(False)
        self._classification_rows['gender'] = self._build_classification_row(
            field_key='gender',
            label='Gender',
            input_widget=self.ui.gender_comboBox,
            in_path_checkbox=self.ui.gender_in_path_checkBox,
        )

        # --- Asset Type ---
        self.ui.asset_type_comboBox = qtwidgets.QComboBox()
        self.ui.asset_type_comboBox.setToolTip('Mesh type: SkeletalMesh, StaticMesh, or Material.')
        self.ui.asset_type_comboBox.setMinimumWidth(150)
        self.ui.asset_type_in_path_checkBox = qtwidgets.QCheckBox('In Path')
        self.ui.asset_type_in_path_checkBox.setToolTip(
            'Include asset type in the asset folder path.')
        self.ui.asset_type_in_path_checkBox.setChecked(False)
        self._classification_rows['asset_type'] = self._build_classification_row(
            field_key='asset_type',
            label='Asset Type',
            input_widget=self.ui.asset_type_comboBox,
            in_path_checkbox=self.ui.asset_type_in_path_checkBox,
        )

        # --- Skeleton ---
        self.ui.skeleton_comboBox = qtwidgets.QComboBox()
        self.ui.skeleton_comboBox.setToolTip('Skeleton this asset is rigged to.')
        self.ui.skeleton_comboBox.setMinimumWidth(150)
        self.ui.add_skeleton_pushButton = qtwidgets.QPushButton('+')
        self.ui.add_skeleton_pushButton.setToolTip('Add a new skeleton')
        self.ui.add_skeleton_pushButton.setMaximumSize(24, 24)
        self.ui.skeleton_in_path_checkBox = qtwidgets.QCheckBox('In Path')
        self.ui.skeleton_in_path_checkBox.setToolTip(
            'Include skeleton in the asset folder path.')
        self.ui.skeleton_in_path_checkBox.setChecked(False)
        self._classification_rows['skeleton'] = self._build_classification_row(
            field_key='skeleton',
            label='Skeleton',
            input_widget=self.ui.skeleton_comboBox,
            add_button=self.ui.add_skeleton_pushButton,
            in_path_checkbox=self.ui.skeleton_in_path_checkBox,
        )

        # --- Body Type ---
        self.ui.body_type_comboBox = qtwidgets.QComboBox()
        self.ui.body_type_comboBox.setToolTip('Body type determines the skeleton variant.')
        self.ui.body_type_comboBox.setMinimumWidth(150)
        self.ui.add_body_type_pushButton = qtwidgets.QPushButton('+')
        self.ui.add_body_type_pushButton.setToolTip('Add a new body type')
        self.ui.add_body_type_pushButton.setMaximumSize(24, 24)
        self.ui.body_type_in_path_checkBox = qtwidgets.QCheckBox('In Path')
        self.ui.body_type_in_path_checkBox.setToolTip(
            'Include body type in the asset folder path.')
        self.ui.body_type_in_path_checkBox.setChecked(False)
        self._classification_rows['body_type'] = self._build_classification_row(
            field_key='body_type',
            label='Body Type',
            input_widget=self.ui.body_type_comboBox,
            add_button=self.ui.add_body_type_pushButton,
            in_path_checkbox=self.ui.body_type_in_path_checkBox,
        )

        # Populate the list in the default (legacy) order. Per-asset loads
        # will re-apply a stored order via ``_rebuild_classification_order``.
        self._rebuild_classification_order(list(unified_entry.DEFAULT_PATH_ORDER))
        class_v.addWidget(self.ui.classification_listWidget)

        # --- Additional Types ---
        # Kept outside the drag list since these are user-typed tags rather
        # than a single classification value. They always emit after every
        # classification field in the path.
        add_types_form = qtwidgets.QFormLayout()
        add_types_form.setFieldGrowthPolicy(qtwidgets.QFormLayout.ExpandingFieldsGrow)
        add_types_label = qtwidgets.QLabel('Additional Types:')
        add_types_label.setAlignment(
            qtcore.Qt.AlignLeading | qtcore.Qt.AlignLeft | qtcore.Qt.AlignTop)
        self.ui.additional_types_frame = qtwidgets.QFrame()
        self.ui.additional_types_frame.setToolTip(
            'Extra type tags that add nested folders in the asset path.')
        self.ui.additional_types_frame.setMaximumHeight(100)
        self.ui.additional_types_frame.setFrameShape(qtwidgets.QFrame.NoFrame)
        add_types_form.addRow(add_types_label, self.ui.additional_types_frame)

        # Single toggle for the whole additional_types list since they share
        # a path segment group — either all nest as folders or none do.
        self.ui.additional_types_in_path_checkBox = qtwidgets.QCheckBox(
            'Include Additional Types in Path')
        self.ui.additional_types_in_path_checkBox.setToolTip(
            'When checked, each additional type is appended as a nested folder.')
        self.ui.additional_types_in_path_checkBox.setChecked(True)
        add_types_form.addRow('', self.ui.additional_types_in_path_checkBox)
        class_v.addLayout(add_types_form)

        # -- Hierarchy tab -------------------------------------------------- #
        hier_tab = qtwidgets.QWidget()
        hier_form = qtwidgets.QFormLayout(hier_tab)
        hier_form.setFieldGrowthPolicy(qtwidgets.QFormLayout.ExpandingFieldsGrow)
        self.ui.form_tabWidget.addTab(hier_tab, 'Parent Asset')

        # Built For. One list, not a combobox plus a second list: a piece of
        # gear either is or is not made for a given character, and splitting
        # that across two widgets made the first parent look special when it is
        # only the first name in the list. MultiSelection means a plain click
        # toggles one row on or off without ctrl-clicking, and selecting
        # nothing means "this is a parent asset, not gear".
        #
        # The folder path does not depend on which characters these are: gear
        # derives under the category's gear root either way.
        self.ui.built_for_list = qtwidgets.QListWidget()
        self.ui.built_for_list.setSelectionMode(
            qtwidgets.QAbstractItemView.MultiSelection)
        self.ui.built_for_list.setToolTip(
            'The characters this gear was made for. Click to select, click again to\n'
            'deselect; pick as many as can wear it. The asset appears under every\n'
            'character you pick in the Summoner.\n'
            'Select nothing for a parent asset - a character, prop or weapon that is\n'
            'not worn by anything.')
        # Capped, not expanding: the form grows fields to fill, and an
        # uncapped list ate the whole tab and pushed Variant Of out of sight.
        self.ui.built_for_list.setMinimumHeight(90)
        self.ui.built_for_list.setMaximumHeight(120)
        hier_form.addRow('Built For:', self.ui.built_for_list)

        # Variant of: the character-sized counterpart of Built For. Gear goes ON
        # a character; a variant IS one - a different body on the same skeleton,
        # which the Summoner swaps in while equipped gear stays put. Only
        # meaningful for Characters, so the row hides itself for other
        # categories (see _on_category_changed).
        self.ui.variant_of_comboBox = qtwidgets.QComboBox()
        self.ui.variant_of_comboBox.setToolTip(
            'Make this character a restyle of another: a different body riding the same\n'
            'skeleton. Leave as None for a character that is a base in its own right.\n'
            'A variant cannot itself have variants.')
        self.ui.variant_of_comboBox.setMinimumWidth(150)
        self.ui.variant_of_label = qtwidgets.QLabel('Variant Of:')
        hier_form.addRow(self.ui.variant_of_label, self.ui.variant_of_comboBox)

        # Slot row: combobox + add (+) / remove (−) buttons. Slots are
        # stored on the global config (asset_paths.GlobalData.slots), so
        # add/remove mutate shared state and flag asset_data.config dirty
        # for the next p4 submit.
        slot_row = qtwidgets.QHBoxLayout()
        self.ui.slot_label = qtwidgets.QLabel('Slot:')
        self.ui.slot_comboBox = qtwidgets.QComboBox()
        self.ui.slot_comboBox.setToolTip('Equipment slot where this gear attaches.')
        self.ui.slot_comboBox.setMinimumWidth(150)
        slot_row.addWidget(self.ui.slot_comboBox)
        self.ui.add_slot_pushButton = qtwidgets.QPushButton('+')
        self.ui.add_slot_pushButton.setToolTip('Add a new gear slot')
        self.ui.add_slot_pushButton.setMaximumSize(24, 24)
        slot_row.addWidget(self.ui.add_slot_pushButton)
        self.ui.remove_slot_pushButton = qtwidgets.QPushButton('-')
        self.ui.remove_slot_pushButton.setToolTip(
            'Remove the currently selected gear slot from the global list')
        self.ui.remove_slot_pushButton.setMaximumSize(24, 24)
        slot_row.addWidget(self.ui.remove_slot_pushButton)
        hier_form.addRow(self.ui.slot_label, slot_row)

        # -- Paths tab ------------------------------------------------------ #
        paths_tab = qtwidgets.QWidget()
        paths_form = qtwidgets.QFormLayout(paths_tab)
        paths_form.setFieldGrowthPolicy(qtwidgets.QFormLayout.ExpandingFieldsGrow)
        self.ui.form_tabWidget.addTab(paths_tab, 'Paths')

        # DCC Path row: line edit + Set (hidden) + Go (hidden) + Browse
        dcc_row = qtwidgets.QHBoxLayout()
        self.ui.dcc_path_lineEdit = qtwidgets.QLineEdit()
        self.ui.dcc_path_lineEdit.setToolTip('DCC-relative folder path (Maya/source side).')
        self.ui.dcc_path_lineEdit.setPlaceholderText('Auto-generated (editable)')
        dcc_row.addWidget(self.ui.dcc_path_lineEdit)

        self.ui.dcc_path_set_pushButton = qtwidgets.QPushButton('Set')
        self.ui.dcc_path_set_pushButton.setFixedWidth(36)
        self.ui.dcc_path_set_pushButton.setToolTip('Set from editor selection')
        self.ui.dcc_path_set_pushButton.setVisible(False)
        dcc_row.addWidget(self.ui.dcc_path_set_pushButton)

        self.ui.dcc_path_goto_pushButton = qtwidgets.QPushButton('Go')
        self.ui.dcc_path_goto_pushButton.setFixedWidth(30)
        self.ui.dcc_path_goto_pushButton.setToolTip('Navigate to this path in the editor')
        self.ui.dcc_path_goto_pushButton.setVisible(False)
        dcc_row.addWidget(self.ui.dcc_path_goto_pushButton)

        self.ui.dcc_path_browse_pushButton = qtwidgets.QPushButton('...')
        self.ui.dcc_path_browse_pushButton.setToolTip('Browse for the DCC source folder')
        self.ui.dcc_path_browse_pushButton.setFixedWidth(30)
        dcc_row.addWidget(self.ui.dcc_path_browse_pushButton)
        paths_form.addRow('DCC Path:', dcc_row)

        # Engine Path row: line edit + Set (hidden) + Go (hidden) + Browse
        engine_row = qtwidgets.QHBoxLayout()
        self.ui.engine_path_lineEdit = qtwidgets.QLineEdit()
        self.ui.engine_path_lineEdit.setToolTip('Unreal Engine content path.')
        self.ui.engine_path_lineEdit.setPlaceholderText('Auto-generated (editable)')
        engine_row.addWidget(self.ui.engine_path_lineEdit)

        self.ui.engine_path_set_pushButton = qtwidgets.QPushButton('Set')
        self.ui.engine_path_set_pushButton.setFixedWidth(36)
        self.ui.engine_path_set_pushButton.setToolTip('Set from editor selection')
        self.ui.engine_path_set_pushButton.setVisible(False)
        engine_row.addWidget(self.ui.engine_path_set_pushButton)

        self.ui.engine_path_goto_pushButton = qtwidgets.QPushButton('Go')
        self.ui.engine_path_goto_pushButton.setFixedWidth(30)
        self.ui.engine_path_goto_pushButton.setToolTip('Navigate to this path in the editor')
        self.ui.engine_path_goto_pushButton.setVisible(False)
        engine_row.addWidget(self.ui.engine_path_goto_pushButton)

        self.ui.engine_path_browse_pushButton = qtwidgets.QPushButton('...')
        self.ui.engine_path_browse_pushButton.setToolTip('Browse for the Engine content folder')
        self.ui.engine_path_browse_pushButton.setFixedWidth(30)
        engine_row.addWidget(self.ui.engine_path_browse_pushButton)
        paths_form.addRow('Engine Path:', engine_row)

        # Auto-Populate button: uses the engine path to fill materials, etc.
        self.ui.auto_populate_pushButton = qtwidgets.QPushButton('Auto-Populate from Engine Path')
        self.ui.auto_populate_pushButton.setToolTip(
            'Use the engine path to auto-fill material slots and textures.')
        self.ui.auto_populate_pushButton.setVisible(False)
        paths_form.addRow('', self.ui.auto_populate_pushButton)

        # Create Folders checkbox
        self.ui.create_folders_checkBox = qtwidgets.QCheckBox('Create Folders On Save')
        self.ui.create_folders_checkBox.setToolTip(
            'When checked, saving creates the standard folder structure on disk.')
        self.ui.create_folders_checkBox.setChecked(True)
        paths_form.addRow('', self.ui.create_folders_checkBox)

        # Auto-submit to Perforce after save. No-ops gracefully if Perforce
        # is unavailable - see sourcecontrol.submit.
        self.ui.p4_submit_checkBox = qtwidgets.QCheckBox('Auto-Submit to Perforce')
        self.ui.p4_submit_checkBox.setToolTip(
            'When checked, saving will submit the registry file to Perforce '
            'under a new changelist with a short description.')
        self.ui.p4_submit_checkBox.setChecked(True)
        paths_form.addRow('', self.ui.p4_submit_checkBox)

        # Force-create folder buttons, independent of the save flow.
        # The Engine button is hidden unless a DCC wrapper (Unreal) makes it
        # visible, since creating engine folders only makes sense inside UE.
        force_row = qtwidgets.QHBoxLayout()
        self.ui.create_dcc_folders_now_pushButton = qtwidgets.QPushButton('Create DCC Folders Now')
        self.ui.create_dcc_folders_now_pushButton.setToolTip(
            'Create the standard DCC folder structure under the current DCC Path right now.')
        force_row.addWidget(self.ui.create_dcc_folders_now_pushButton)
        self.ui.create_engine_folders_now_pushButton = qtwidgets.QPushButton('Create Engine Folders Now')
        self.ui.create_engine_folders_now_pushButton.setToolTip(
            'Create the engine content folder for the current Engine Path (Unreal only).')
        self.ui.create_engine_folders_now_pushButton.setVisible(False)
        force_row.addWidget(self.ui.create_engine_folders_now_pushButton)
        paths_form.addRow('', force_row)

        # Let DCC wrappers show/connect the path Set and Go buttons
        self._setup_path_dcc_buttons()

        # Vertical spacer at bottom of form
        form_layout.addStretch()

        # ================================================================== #
        #  DETAIL TABS (below form in the vertical splitter)
        # ================================================================== #
        self.ui.detail_tabWidget = qtwidgets.QTabWidget()
        self.ui.detail_tabWidget.setToolTip('Detailed asset data: materials, dyes, decals, textures, sockets.')
        self.ui.detail_tabWidget.setMinimumHeight(80)
        self.ui.vertical_splitter.addWidget(self.ui.detail_tabWidget)

        # Materials tab
        materials_tab = qtwidgets.QWidget()
        materials_tab.setToolTip('Material slots and their swappable options.')
        self.ui.materials_tab_layout = qtwidgets.QVBoxLayout(materials_tab)
        self.ui.detail_tabWidget.addTab(materials_tab, 'Materials')

        # Dyes tab
        dyes_tab = qtwidgets.QWidget()
        dyes_tab.setToolTip('Dye material slots whose color can change dynamically in-game.')
        self.ui.dyes_tab_layout = qtwidgets.QVBoxLayout(dyes_tab)
        self.ui.detail_tabWidget.addTab(dyes_tab, 'Dyes')

        # Dye Overrides tab (gear variants only)
        dye_overrides_tab = qtwidgets.QWidget()
        dye_overrides_tab.setToolTip(
            'Per-variant dye channel values. Reads the parent asset\'s '
            'dye schema and lets you tint each channel for this gear piece.')
        self.ui.dye_overrides_tab_layout = qtwidgets.QVBoxLayout(dye_overrides_tab)
        self.ui.detail_tabWidget.addTab(dye_overrides_tab, 'Dye Overrides')
        self._dye_overrides_tab_widget = dye_overrides_tab

        # Decals tab
        decals_tab = qtwidgets.QWidget()
        decals_tab.setToolTip('Decal definitions that overlay on top of the base mesh.')
        self.ui.decals_tab_layout = qtwidgets.QVBoxLayout(decals_tab)
        self.ui.detail_tabWidget.addTab(decals_tab, 'Decals')

        # Textures tab
        textures_tab = qtwidgets.QWidget()
        textures_tab.setToolTip('DCC-side and Engine-side texture paths.')
        self.ui.textures_tab_layout = qtwidgets.QVBoxLayout(textures_tab)
        self.ui.detail_tabWidget.addTab(textures_tab, 'Textures')

        # Attach Sockets tab
        sockets_tab = qtwidgets.QWidget()
        sockets_tab.setToolTip('Skeleton joints or sockets where this asset attaches.')
        self.ui.sockets_tab_layout = qtwidgets.QVBoxLayout(sockets_tab)
        self.ui.detail_tabWidget.addTab(sockets_tab, 'Attach Sockets')

        # ================================================================== #
        #  BUTTON BAR
        # ================================================================== #
        button_frame = qtwidgets.QFrame()
        button_frame.setMaximumHeight(50)
        button_frame.setFrameShape(qtwidgets.QFrame.NoFrame)
        button_layout = qtwidgets.QHBoxLayout(button_frame)
        main_layout.addWidget(button_frame)

        self.ui.save_pushButton = qtwidgets.QPushButton('Save New')
        self.ui.save_pushButton.setToolTip('Save as a new asset entry in the registry.')
        button_layout.addWidget(self.ui.save_pushButton)

        self.ui.update_pushButton = qtwidgets.QPushButton('Update')
        self.ui.update_pushButton.setToolTip('Update the currently selected asset.')
        button_layout.addWidget(self.ui.update_pushButton)

        self.ui.remove_pushButton = qtwidgets.QPushButton('Remove')
        self.ui.remove_pushButton.setToolTip('Remove the currently selected asset.')
        button_layout.addWidget(self.ui.remove_pushButton)

        self.ui.transfer_pushButton = qtwidgets.QPushButton('Transfer...')
        self.ui.transfer_pushButton.setToolTip(
            'Move the currently selected asset to a different category.')
        button_layout.addWidget(self.ui.transfer_pushButton)

        self.ui.clear_pushButton = qtwidgets.QPushButton('Clear Form')
        self.ui.clear_pushButton.setToolTip('Reset all form fields.')
        button_layout.addWidget(self.ui.clear_pushButton)

        button_layout.addStretch()

        self.ui.modify_data_pushButton = qtwidgets.QPushButton('Modify Data...')
        self.ui.modify_data_pushButton.setToolTip('Open the Modify Asset Data dialog.')
        button_layout.addWidget(self.ui.modify_data_pushButton)

    # --- Dynamic widget construction --------------------------------------- #

    def _build_additional_types_widget(self):
        """
        Build the additional types list with add/remove controls.
        Injected into the additional_types_frame placeholder from the .ui.
        """

        frame = self.ui.additional_types_frame
        layout = qtwidgets.QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._additional_types_list = qtwidgets.QListWidget()
        self._additional_types_list.setMaximumHeight(60)
        layout.addWidget(self._additional_types_list)

        btn_layout = qtwidgets.QHBoxLayout()
        self._add_type_lineEdit = qtwidgets.QLineEdit()
        self._add_type_lineEdit.setPlaceholderText('Type name...')
        btn_layout.addWidget(self._add_type_lineEdit)

        self._add_type_btn = qtwidgets.QPushButton('+')
        self._add_type_btn.setMaximumWidth(30)
        btn_layout.addWidget(self._add_type_btn)

        self._remove_type_btn = qtwidgets.QPushButton('-')
        self._remove_type_btn.setMaximumWidth(30)
        btn_layout.addWidget(self._remove_type_btn)

        layout.addLayout(btn_layout)

    def _build_asset_tree(self):
        """
        Build the QTreeWidget for browsing existing assets.
        Injected into the tree_content_layout placeholder from the .ui.
        """

        self._asset_tree = qtwidgets.QTreeWidget()
        self._asset_tree.setHeaderLabels(['Name', 'Subtype', 'Faction', 'Variant Of'])
        self._asset_tree.setColumnWidth(0, 160)
        self._asset_tree.setAlternatingRowColors(True)
        self.ui.tree_content_layout.addWidget(self._asset_tree)

    def _build_materials_tab(self):
        """Build the materials row area inside the Materials tab."""

        self._materials_scroll, self._materials_rows_layout = self._create_slot_row_area(
            parent_layout=self.ui.materials_tab_layout,
            slot_kind='material',
        )

    def _build_dyes_tab(self):
        """Build the dyes row area inside the Dyes tab."""

        self._dyes_scroll, self._dyes_rows_layout = self._create_slot_row_area(
            parent_layout=self.ui.dyes_tab_layout,
            slot_kind='dye',
        )

    def _build_decals_tab(self):
        """Build the decals row area inside the Decals tab."""

        self._decals_scroll, self._decals_rows_layout = self._create_slot_row_area(
            parent_layout=self.ui.decals_tab_layout,
            slot_kind='decal',
        )

    def _build_dye_overrides_tab(self):
        """
        Build the empty container for the Dye Overrides tab.

        The actual per-channel widgets are rebuilt every time an entry
        loads, since the schema lives on the parent asset and changes
        when the user picks a different ``built_for``. The tab body is
        intentionally minimal here: a hint label (shown when the schema
        is unavailable) and a scroll area whose contents are repopulated
        by ``_populate_dye_overrides_tab``.
        """

        layout = self.ui.dye_overrides_tab_layout

        self._dye_overrides_hint = qtwidgets.QLabel('')
        self._dye_overrides_hint.setWordWrap(True)
        self._dye_overrides_hint.setStyleSheet('color: #888; padding: 6px;')
        self._dye_overrides_hint.setVisible(False)
        layout.addWidget(self._dye_overrides_hint)

        scroll = qtwidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = qtwidgets.QWidget()
        self._dye_overrides_rows_layout = qtwidgets.QVBoxLayout(scroll_widget)
        self._dye_overrides_rows_layout.setSpacing(6)
        self._dye_overrides_rows_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Editor descriptors collected per rebuild. Each entry is
        # ``(slot_name, channel_name, channel_type, override_check, getter)``
        # so _collect_dye_overrides can read every active override
        # without re-scanning widget trees.
        self._dye_override_editors = []
        # Cache the most recently resolved parent entry so two
        # successive saves don't re-read the registry from disk.
        self._parent_entry_cache = {}

    def _build_textures_tab(self):
        """Build the textures row areas inside the Textures tab."""

        layout = self.ui.textures_tab_layout

        h_layout = qtwidgets.QHBoxLayout()

        # DCC Textures group with scroll rows
        dcc_group = qtwidgets.QGroupBox('DCC Textures')
        dcc_vlayout = qtwidgets.QVBoxLayout(dcc_group)
        self._dcc_tex_scroll, self._dcc_tex_rows_layout = self._create_texture_row_area(dcc_vlayout)
        h_layout.addWidget(dcc_group)

        # Engine Textures group with scroll rows
        engine_group = qtwidgets.QGroupBox('Engine Textures')
        engine_vlayout = qtwidgets.QVBoxLayout(engine_group)
        self._engine_tex_scroll, self._engine_tex_rows_layout = self._create_texture_row_area(engine_vlayout)
        h_layout.addWidget(engine_group)

        layout.addLayout(h_layout)

    def _build_sockets_tab(self):
        """Build the attach sockets row area inside the Attach Sockets tab."""

        layout = self.ui.sockets_tab_layout

        # Scroll area for socket rows
        scroll = qtwidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = qtwidgets.QWidget()
        self._sockets_rows_layout = qtwidgets.QVBoxLayout(scroll_widget)
        self._sockets_rows_layout.setSpacing(2)
        self._sockets_rows_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Add row: combo (editable) + add button + remove button
        btn_layout = qtwidgets.QHBoxLayout()
        self._socket_comboBox = qtwidgets.QComboBox()
        self._socket_comboBox.setEditable(True)
        self._socket_comboBox.setToolTip(
            'Select a known socket or type a new name to add it.')
        self._socket_comboBox.lineEdit().setPlaceholderText('Socket name...')
        btn_layout.addWidget(self._socket_comboBox)
        self._add_socket_btn = qtwidgets.QPushButton('Add')
        btn_layout.addWidget(self._add_socket_btn)
        self._remove_socket_btn = qtwidgets.QPushButton('Remove')
        btn_layout.addWidget(self._remove_socket_btn)
        layout.addLayout(btn_layout)

    # --- Row frame factories ------------------------------------------------- #

    def _create_slot_row_area(self, parent_layout, slot_kind='material'):
        """
        Create a scrollable row area with add/remove buttons for slot tabs.

        ``slot_kind`` selects the row variant: ``material`` rows show an
        Is Dye checkbox, ``dye`` rows show a channels editor, ``decal``
        rows show a mesh-type field. Tag the layout with its kind so
        downstream helpers (sync, populate, collect) can branch without
        carrying the parameter through every call site.

        :param QVBoxLayout parent_layout: Layout to add the area into.
        :param str slot_kind: One of ``material``, ``dye``, ``decal``.
        :return: Tuple of (QScrollArea, QVBoxLayout for rows).
        :rtype: tuple
        """

        scroll = qtwidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = qtwidgets.QWidget()
        rows_layout = qtwidgets.QVBoxLayout(scroll_widget)
        rows_layout.setSpacing(2)
        rows_layout.addStretch()
        scroll.setWidget(scroll_widget)
        parent_layout.addWidget(scroll)
        # Tag so _add_slot_row / sync helpers can recover the kind from
        # just a layout reference.
        rows_layout.setProperty('slot_kind', slot_kind)

        btn_layout = qtwidgets.QHBoxLayout()
        add_btn = qtwidgets.QPushButton('Add Row')
        remove_btn = qtwidgets.QPushButton('Remove Row')
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)

        # Connect add/remove
        add_btn.clicked.connect(lambda: self._add_slot_row(rows_layout, slot_kind))
        remove_btn.clicked.connect(lambda: self._remove_slot_row(rows_layout))

        return scroll, rows_layout

    def _create_texture_row_area(self, parent_layout):
        """
        Create a scrollable row area for texture paths.

        Each row is a horizontal frame with a QLineEdit (path) and remove button.

        :param QVBoxLayout parent_layout: Layout to add the area into.
        :return: Tuple of (QScrollArea, QVBoxLayout for rows).
        :rtype: tuple
        """

        scroll = qtwidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = qtwidgets.QWidget()
        rows_layout = qtwidgets.QVBoxLayout(scroll_widget)
        rows_layout.setSpacing(2)
        rows_layout.addStretch()
        scroll.setWidget(scroll_widget)
        parent_layout.addWidget(scroll)

        btn_layout = qtwidgets.QHBoxLayout()
        add_btn = qtwidgets.QPushButton('Add')
        remove_btn = qtwidgets.QPushButton('Remove')
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        parent_layout.addLayout(btn_layout)

        add_btn.clicked.connect(lambda: self._add_texture_row(rows_layout))
        remove_btn.clicked.connect(lambda: self._remove_slot_row(rows_layout))

        return scroll, rows_layout

    # --- Menu bar + preferences -------------------------------------------- #

    def _build_menu_bar(self):
        """
        Build the top-of-window menu bar.

        Adds a Settings menu with a Preferences entry that opens
        ``register_prefs.PreferencesDialog``. Free of charge from the QMainWindow base.
        """

        menu_bar = self.menuBar()
        settings_menu = menu_bar.addMenu('Settings')
        prefs_action = qt_menus.action_class()('Preferences...', self)
        prefs_action.setToolTip(
            'Configure default In Path checkboxes and workflow defaults.')
        prefs_action.triggered.connect(self._open_preferences_dialog)
        settings_menu.addAction(prefs_action)
