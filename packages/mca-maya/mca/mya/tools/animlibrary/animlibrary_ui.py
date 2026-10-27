"""
The animation library browser.

Laid out the way Studio Library reads, because that is the shape animators
already know: a project bar across the top, a source tree (character, then
folder) on the left, a thumbnail grid in the middle, and the selected clip's
detail and controls on the right.

Everything the window does goes through :mod:`animlib_api` and
:mod:`animlib_maya`, so the UI holds no logic of its own - the same calls drive
the AI tools and anything scripted.

What the window is opinionated about
------------------------------------
*Projects* sit at the top because which library you are in changes the meaning of
everything below it, and finding that out from the clip list is too late.

*Poses and animations get different controls.* They are not two flavours of the
same thing: an animation is put onto a stretch of time and has to reckon with
what is already there, while a pose is a place the rig is moved to, right now, by
however much you ask for. So the panel swaps rather than greying half of itself
out.

*Applying an animation* is not one button's worth of behaviour. Putting a clip
onto a rig that already has animation is four different questions - replace these
frames, replace the lot, push everything along, or lay it over the top - and the
Option dropdown is where the animator answers it.

*The rig comes from the selection*, never from a dropdown here. A flag selected
in the viewport already says which rig; the FRAG node gets from there to the rest.

*Folders are real folders.* Making one makes it on disk, empty, and it shows in
the tree before anything is in it - otherwise creating a folder looks like it did
nothing.

Double-click a clip to apply it with whatever options are set.

:Requires: mca.common.animlib, mca.mya.tools.animlibrary.animlib_maya
:Side effects: Applying, blending and capturing change the open Maya scene.
    Adding and removing folders and projects writes to disk.
"""

# python imports
import os

# software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log
from mca.common.animlib import animlib_api
from mca.common.pyqt.pygui import qtwidgets, qtcore, qtgui
from mca.common.resources import resources
from mca.mya.pyqt import mayawindows, dialogs
from mca.mya.tools.animlibrary import animlib_dialogs, animlib_maya

logger = log.MCA_LOGGER

# Grid tile size. Wide enough that clip names stay distinguishable - these are
# named like FW_Abilities_IceShards_Master_02, and at 132px three of those
# truncate to the same stub - but not so wide that a character with 160 clips
# needs endless scrolling.
TILE_WIDTH = 190
TILE_HEIGHT = 138
# Breathing room above the first row. A tile sitting hard against the top edge
# reads as cut off: the eye cannot tell "this row starts here" from "this row is
# clipped and the view will not scroll up any further".
GRID_TOP_MARGIN = 12
ICON_WIDTH = 150
ICON_HEIGHT = 84

# The clip-type filter's first entry, which filters nothing.
ALL_TYPES = 'All'

MIRROR_TOOLTIP = (
    'Put the clip on the other way round - left flags onto right ones.\n\n'
    'Which channels have to flip is a property of how the rig was built, not\n'
    'something that can be read off the names, so it is measured on the rig the\n'
    'first time you mirror. That takes a few seconds; the answer is kept.')

ADDITIVE_TOOLTIP = (
    'Lay the clip over what the rig is already doing, as an offset from its\n'
    'rest pose, instead of replacing it.')

# Tile badge colours. Poses and animations are told apart on the image itself,
# because that is where the eye already is when scanning a folder that holds both.
BADGE_COLOURS = {'pose': (104, 164, 224), 'animation': (206, 160, 92)}
BADGE_TEXT = {'pose': 'POSE', 'animation': 'ANIM'}
UNAPPLICABLE_COLOUR = (150, 150, 150)


# One copy of each, in the module that also needs them. QSettings hands back
# 'false' as a string and a stored 0 as a falsy int, and both of those have cost
# a bug here already.
_to_bool = animlib_dialogs.to_bool
_to_int = animlib_dialogs.to_int


def badge_pixmap(pixmap, clip_type):
    """
    Stamp a clip's kind onto its thumbnail.

    :param qtgui.QPixmap pixmap: The thumbnail.
    :param str clip_type: 'animation' or 'pose'.
    :return: A copy carrying the badge.
    :rtype: qtgui.QPixmap
    """

    text = BADGE_TEXT.get(clip_type, BADGE_TEXT['animation'])
    colour = BADGE_COLOURS.get(clip_type, BADGE_COLOURS['animation'])

    stamped = qtgui.QPixmap(pixmap)
    painter = qtgui.QPainter(stamped)
    try:
        painter.setRenderHint(qtgui.QPainter.Antialiasing, True)
        font = painter.font()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)

        metrics = qtgui.QFontMetrics(font)
        try:
            text_width = metrics.horizontalAdvance(text)
        except AttributeError:
            text_width = metrics.width(text)
        width = text_width + 10
        height = metrics.height() + 2
        rect = qtcore.QRect(4, stamped.height() - height - 4, width, height)

        painter.setPen(qtcore.Qt.NoPen)
        painter.setBrush(qtgui.QColor(*colour))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(qtgui.QColor(25, 25, 25))
        painter.drawText(rect, qtcore.Qt.AlignCenter, text)
    finally:
        painter.end()
    return stamped


class AnimationLibrary(mayawindows.MCAMayaWindow):
    """
    Browse, apply and capture animation clips and poses.
    """

    VERSION = '3.0.0'

    def __init__(self, **kwargs):
        # No parent kwarg forwarded: MCAMayaWindow defaults it to Maya's main
        # window, and passing None explicitly would float the tool free of it.
        super().__init__(title='Animation Library',
                         version=AnimationLibrary.VERSION,
                         show_window=False,
                         **kwargs)

        self._clips = []
        self._selected = None
        self._loading = False
        self._movie = None
        self._blending = False
        # Which clip the preview slot is currently showing, and whether it is
        # moving. Hovering changes both without changing the selection, so they
        # have to be tracked apart from it.
        self._previewing = None
        self._animating = False

        self._build_ui()
        self._connect()
        self._restore_options()
        self._refresh_apply_labels()
        self.refresh()
        self._restore_selection()
        self.show()

    # --- Construction ------------------------------------------------------ #

    def _build_ui(self):
        """
        Assemble the window.
        """

        # MCAMainWindow already made a central widget and layout for us when it
        # was given no .ui file; build into that rather than replacing it, so
        # the window keeps the house stylesheet and margins.
        outer = self.main_layout
        # MCAMainWindow hands over a layout with no margins at all, which puts
        # the tree's frame flush against the window edge and shaves it.
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        outer.addLayout(self._build_project_bar())
        outer.addLayout(self._build_search_bar())

        self.splitter = qtwidgets.QSplitter(qtcore.Qt.Horizontal)
        outer.addWidget(self.splitter, 1)
        self.splitter.addWidget(self._build_tree_panel())
        self.splitter.addWidget(self._build_grid())
        self.splitter.addWidget(self._build_detail_panel())
        self.splitter.setSizes([210, 500, 350])

        self.status_label = qtwidgets.QLabel('')
        outer.addWidget(self.status_label)

        self.resize(1200, 820)

    def _build_project_bar(self):
        """
        :return: The project row.
        :rtype: qtwidgets.QHBoxLayout
        """

        row = qtwidgets.QHBoxLayout()
        row.addWidget(qtwidgets.QLabel('Project:'))

        self.project_comboBox = qtwidgets.QComboBox()
        self.project_comboBox.setMinimumWidth(160)
        self.project_comboBox.setToolTip(
            'Which animation library everything below is reading from.\n'
            'A project is just a named library folder.')
        row.addWidget(self.project_comboBox)

        self.add_project_pushButton = qtwidgets.QPushButton('+')
        self.add_project_pushButton.setFixedWidth(26)
        self.add_project_pushButton.setToolTip('Point at another library folder.')
        row.addWidget(self.add_project_pushButton)

        self.remove_project_pushButton = qtwidgets.QPushButton('-')
        self.remove_project_pushButton.setFixedWidth(26)
        self.remove_project_pushButton.setToolTip(
            'Forget this project. The library on disk is left alone.')
        row.addWidget(self.remove_project_pushButton)

        self.root_label = qtwidgets.QLabel('')
        self.root_label.setTextInteractionFlags(qtcore.Qt.TextSelectableByMouse)
        row.addWidget(self.root_label, 1)
        return row

    def _build_search_bar(self):
        """
        :return: The search and filter row.
        :rtype: qtwidgets.QHBoxLayout
        """

        row = qtwidgets.QHBoxLayout()
        self.search_lineEdit = qtwidgets.QLineEdit()
        self.search_lineEdit.setPlaceholderText('Search clips...')
        self.search_lineEdit.setClearButtonEnabled(True)
        row.addWidget(self.search_lineEdit, 1)

        self.type_comboBox = qtwidgets.QComboBox()
        self.type_comboBox.addItems([ALL_TYPES, 'Animations', 'Poses'])
        self.type_comboBox.setToolTip('Show animations, poses, or both.')
        row.addWidget(self.type_comboBox)

        self.applicable_checkBox = qtwidgets.QCheckBox('Applicable only')
        self.applicable_checkBox.setToolTip(
            'Show only clips that have a curve file, which are the ones that can\n'
            'be put onto a rig. A clip with an FBX but no curves is export-only.')
        row.addWidget(self.applicable_checkBox)

        self.refresh_pushButton = qtwidgets.QPushButton('Refresh')
        row.addWidget(self.refresh_pushButton)
        return row

    def _build_tree_panel(self):
        """
        :return: The source tree with its folder buttons.
        :rtype: qtwidgets.QWidget
        """

        panel = qtwidgets.QWidget()
        layout = qtwidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.source_tree = qtwidgets.QTreeWidget()
        self.source_tree.setHeaderLabels(['Library'])
        self.source_tree.setMinimumWidth(190)
        self.source_tree.setContextMenuPolicy(qtcore.Qt.CustomContextMenu)
        layout.addWidget(self.source_tree, 1)

        row = qtwidgets.QHBoxLayout()
        self.new_folder_pushButton = qtwidgets.QPushButton('New Folder')
        self.new_folder_pushButton.setToolTip('Make a folder in the library.')
        row.addWidget(self.new_folder_pushButton)
        self.remove_folder_pushButton = qtwidgets.QPushButton('Remove Folder')
        self.remove_folder_pushButton.setToolTip(
            'Remove the selected folder. It has to be empty, unless you confirm otherwise.')
        row.addWidget(self.remove_folder_pushButton)
        layout.addLayout(row)
        return panel

    def _build_grid(self):
        """
        The thumbnail grid, with a gutter above it.

        The gutter is a layout margin on a wrapper rather than a margin on the
        list's own viewport, and that is not a stylistic choice: QListView calls
        ``setViewportMargins`` itself inside ``updateGeometries``, so anything
        set there survives construction, looks right in a screenshot taken
        immediately, and is gone by the time the widget has been laid out once.
        Measured: 14 px after ``__init__``, 2 px after the first resize.

        Putting the space outside the scroll area also makes it behave the way it
        reads - nothing is ever drawn in it, at any scroll position, so a row
        scrolled up to the edge stops at the gutter instead of running into the
        search bar.

        :return: The grid, wrapped.
        :rtype: qtwidgets.QWidget
        """

        self.clip_list = qtwidgets.QListWidget()
        self.clip_list.setViewMode(qtwidgets.QListView.IconMode)
        self.clip_list.setResizeMode(qtwidgets.QListView.Adjust)
        self.clip_list.setMovement(qtwidgets.QListView.Static)
        self.clip_list.setIconSize(qtcore.QSize(ICON_WIDTH, ICON_HEIGHT))
        self.clip_list.setGridSize(qtcore.QSize(TILE_WIDTH, TILE_HEIGHT))
        self.clip_list.setTextElideMode(qtcore.Qt.ElideMiddle)
        self.clip_list.setSpacing(4)
        self.clip_list.setWordWrap(True)
        # Per pixel, not per item: a row is 190 px tall, so item scrolling jumps
        # a whole tile at a time and a part-visible row can never be brought
        # fully into view. That is the other half of why the grid felt stuck.
        self.clip_list.setVerticalScrollMode(qtwidgets.QAbstractItemView.ScrollPerPixel)
        self.clip_list.setContextMenuPolicy(qtcore.Qt.CustomContextMenu)
        # Hovering a tile plays that clip in the preview slot, which is the only
        # way a grid of stills can answer "what does this one actually do".
        self.clip_list.setMouseTracking(True)
        self.clip_list.viewport().setMouseTracking(True)
        self.clip_list.viewport().installEventFilter(self)

        wrapper = qtwidgets.QWidget()
        layout = qtwidgets.QVBoxLayout(wrapper)
        layout.setContentsMargins(0, GRID_TOP_MARGIN, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.clip_list)
        return wrapper

    def _build_detail_panel(self):
        """
        :return: The detail, apply and capture panel.
        :rtype: qtwidgets.QWidget
        """

        panel = qtwidgets.QWidget()
        layout = qtwidgets.QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)

        self.preview_label = qtwidgets.QLabel('No clip selected')
        self.preview_label.setAlignment(qtcore.Qt.AlignCenter)
        self.preview_label.setFixedHeight(130)
        self.preview_label.setFrameShape(qtwidgets.QFrame.StyledPanel)
        layout.addWidget(self.preview_label)

        self.detail_textEdit = qtwidgets.QTextEdit()
        self.detail_textEdit.setReadOnly(True)
        # Low minimum, high stretch: the detail scrolls, so it is the thing that
        # should give way when the window is short. The controls below it do not
        # scroll, and a clipped Apply button is the one failure that makes the
        # panel unusable.
        self.detail_textEdit.setMinimumHeight(60)
        layout.addWidget(self.detail_textEdit, 1)

        # The group boxes below draw their titles straddling their own top
        # border, so they need clear air or the detail box sits on the word.
        layout.addSpacing(10)
        layout.addWidget(self._build_namespace_group(), 0)

        self.apply_stack = qtwidgets.QStackedWidget()
        self.apply_stack.addWidget(self._build_animation_page())
        self.apply_stack.addWidget(self._build_pose_page())
        layout.addWidget(self.apply_stack, 0)

        layout.addLayout(self._build_capture_row())
        return panel

    def _build_namespace_group(self):
        """
        Which rig in the scene the clip goes onto.

        :return: The Namespace group box.
        :rtype: qtwidgets.QGroupBox
        """

        group = qtwidgets.QGroupBox('Namespace')
        layout = qtwidgets.QVBoxLayout(group)
        layout.setContentsMargins(6, 16, 6, 6)
        layout.setSpacing(2)

        self.namespace_group = qtwidgets.QButtonGroup(self)
        self.namespace_none_radioButton = qtwidgets.QRadioButton('None')
        self.namespace_none_radioButton.setToolTip(
            'The rig with no namespace - one that was opened rather than referenced.')
        self.namespace_selection_radioButton = qtwidgets.QRadioButton('From selection')
        self.namespace_selection_radioButton.setToolTip(
            'Whatever rig your selection belongs to. The usual answer.')
        self.namespace_custom_radioButton = qtwidgets.QRadioButton('Use custom')
        self.namespace_custom_radioButton.setToolTip(
            'A namespace you pick or type. With two of the same character referenced\n'
            'into one scene, this is the only thing that tells them apart.')

        for index, button in enumerate((self.namespace_none_radioButton,
                                        self.namespace_selection_radioButton,
                                        self.namespace_custom_radioButton)):
            self.namespace_group.addButton(button, index)
            layout.addWidget(button)
        self.namespace_selection_radioButton.setChecked(True)

        self.namespace_comboBox = qtwidgets.QComboBox()
        self.namespace_comboBox.setEditable(True)
        self.namespace_comboBox.setEnabled(False)
        self.namespace_comboBox.setToolTip(
            'Namespaces of the rigs in the scene. You can also type one.')
        layout.addWidget(self.namespace_comboBox)
        return group

    def _build_animation_page(self):
        """
        :return: The controls for applying an animation.
        :rtype: qtwidgets.QGroupBox
        """

        group = qtwidgets.QGroupBox('Animation')
        form = qtwidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(qtwidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setContentsMargins(6, 16, 6, 6)

        self.source_group = qtwidgets.QButtonGroup(self)
        self.curves_radioButton = qtwidgets.QRadioButton('Flag Animations')
        self.curves_radioButton.setToolTip(
            'The curves the animator authored. Keeps animation layers and\n'
            'IK/FK state, and applies instantly.')
        self.baked_radioButton = qtwidgets.QRadioButton('Baked Joints')
        self.baked_radioButton.setToolTip(
            'The joints-only FBX, imported and baked back through the rig.\n'
            'Takes a few seconds and flattens layers - but it does not care\n'
            'what the flags are called, so it still works on a rebuilt rig,\n'
            'on another character, and on a clip whose curves were never saved.\n\n'
            'Retargeting is worked out from the clip and the rig; there is\n'
            'nothing to choose.')
        self.source_group.addButton(self.curves_radioButton, 0)
        self.source_group.addButton(self.baked_radioButton, 1)
        self.curves_radioButton.setChecked(True)
        form.addRow('Use:', self._row(self.curves_radioButton, self.baked_radioButton))

        self.current_time_checkBox = qtwidgets.QCheckBox('Current Time')
        self.current_time_checkBox.setToolTip(
            'Start the clip at the current frame.\n'
            'Unchecked, it lands on the frames it was authored on.')
        form.addRow('', self.current_time_checkBox)

        source_row = qtwidgets.QHBoxLayout()
        self.source_start_spinBox = qtwidgets.QSpinBox()
        self.source_start_spinBox.setRange(-100000, 100000)
        self.source_end_spinBox = qtwidgets.QSpinBox()
        self.source_end_spinBox.setRange(-100000, 100000)
        for widget in (self.source_start_spinBox, self.source_end_spinBox):
            widget.setToolTip(
                'How much of the clip to take. Defaults to all of it;\n'
                'narrow it to paste only part.')
            source_row.addWidget(widget)
        self.reset_source_pushButton = qtwidgets.QPushButton('All')
        self.reset_source_pushButton.setFixedWidth(38)
        self.reset_source_pushButton.setToolTip("Back to the clip's whole range.")
        source_row.addWidget(self.reset_source_pushButton)
        form.addRow('source:', source_row)

        self.option_comboBox = qtwidgets.QComboBox()
        for key in animlib_maya.PASTE_OPTION_ORDER:
            self.option_comboBox.addItem(key.replace('_', ' '), key)
        self.option_comboBox.setCurrentIndex(
            list(animlib_maya.PASTE_OPTION_ORDER).index('replace_all'))
        self.option_comboBox.setToolTip(
            'What happens to animation the rig already has.\n\n'
            'replace      - wipe the frames the clip covers, keep the rest\n'
            'replace all  - throw away everything on those flags first\n'
            'insert       - push existing keys later and slot the clip in\n'
            'merge        - lay the clip over what is there')
        form.addRow('Option:', self.option_comboBox)

        amount_row = qtwidgets.QHBoxLayout()
        self.amount_slider = qtwidgets.QSlider(qtcore.Qt.Horizontal)
        self.amount_slider.setRange(0, 100)
        self.amount_slider.setValue(100)
        self.amount_slider.setToolTip(
            'How much of the clip to take.\n'
            '100 is the clip; 50 lands the rig half way between what it was\n'
            'doing and what the clip says.')
        amount_row.addWidget(self.amount_slider, 1)
        self.amount_spinBox = qtwidgets.QSpinBox()
        self.amount_spinBox.setRange(0, 100)
        self.amount_spinBox.setValue(100)
        self.amount_spinBox.setSuffix('%')
        self.amount_spinBox.setFixedWidth(64)
        amount_row.addWidget(self.amount_spinBox)
        form.addRow('Amount:', amount_row)

        self.apply_selected_checkBox = qtwidgets.QCheckBox('Selected flags only')
        self.apply_selected_checkBox.setToolTip(
            'Only animate the flags you have selected on the rig.')
        form.addRow('', self.apply_selected_checkBox)

        self.mirror_checkBox = qtwidgets.QCheckBox('Mirror')
        self.mirror_checkBox.setToolTip(MIRROR_TOOLTIP)
        self.additive_checkBox = qtwidgets.QCheckBox('Additive')
        self.additive_checkBox.setToolTip(ADDITIVE_TOOLTIP)
        form.addRow('', self._row(self.mirror_checkBox, self.additive_checkBox))

        self.apply_pushButton = qtwidgets.QPushButton('Apply Animation')
        self.apply_pushButton.setToolTip(
            'Put this clip onto the rig.\n'
            'The clip file is not modified, so it can be applied as often as you like.')
        self.apply_pushButton.setEnabled(False)
        form.addRow(self.apply_pushButton)
        return group

    def _build_pose_page(self):
        """
        :return: The controls for applying a pose.
        :rtype: qtwidgets.QGroupBox
        """

        group = qtwidgets.QGroupBox('Pose')
        form = qtwidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(qtwidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setContentsMargins(6, 16, 6, 6)

        blend_row = qtwidgets.QHBoxLayout()
        self.blend_slider = qtwidgets.QSlider(qtcore.Qt.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(100)
        self.blend_slider.setToolTip(
            'How much of the pose to take.\n'
            'Drag to see it happen on the rig; let go to keep it.')
        blend_row.addWidget(self.blend_slider, 1)
        self.blend_spinBox = qtwidgets.QSpinBox()
        self.blend_spinBox.setRange(0, 100)
        self.blend_spinBox.setValue(100)
        self.blend_spinBox.setSuffix('%')
        self.blend_spinBox.setFixedWidth(64)
        blend_row.addWidget(self.blend_spinBox)
        form.addRow('Blend:', blend_row)

        self.pose_selected_checkBox = qtwidgets.QCheckBox('Selected flags only')
        self.pose_selected_checkBox.setToolTip(
            'Only pose the flags you have selected on the rig.')
        form.addRow('', self.pose_selected_checkBox)

        # A three-state checkbox was the obvious control here and the wrong one:
        # half-checked and unchecked look near enough identical that nobody could
        # tell "follow auto-key" from "never key". Three named choices can only be
        # read one way.
        self.pose_key_comboBox = qtwidgets.QComboBox()
        self.pose_key_comboBox.addItem('Follow auto-key', None)
        self.pose_key_comboBox.addItem('Always', True)
        self.pose_key_comboBox.addItem('Never', False)
        self.pose_key_comboBox.setToolTip(
            "Whether to key the pose once it is applied.\n"
            "Follow auto-key uses Maya's own setting, which is the answer you\n"
            "already configured.")
        form.addRow('Set key:', self.pose_key_comboBox)

        self.pose_mirror_checkBox = qtwidgets.QCheckBox('Mirror')
        self.pose_mirror_checkBox.setToolTip(MIRROR_TOOLTIP)
        self.pose_additive_checkBox = qtwidgets.QCheckBox('Additive')
        self.pose_additive_checkBox.setToolTip(ADDITIVE_TOOLTIP)
        form.addRow('', self._row(self.pose_mirror_checkBox, self.pose_additive_checkBox))

        self.apply_pose_pushButton = qtwidgets.QPushButton('Apply Pose')
        self.apply_pose_pushButton.setToolTip(
            'Put this pose onto the rig at the blend amount above.')
        self.apply_pose_pushButton.setEnabled(False)
        form.addRow(self.apply_pose_pushButton)
        return group

    @staticmethod
    def _row(*widgets):
        """
        Put some widgets on one line.

        :param widgets: The widgets, left to right.
        :return: A container for them.
        :rtype: qtwidgets.QWidget
        """

        container = qtwidgets.QWidget()
        row = qtwidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return container

    def _build_capture_row(self):
        """
        :return: The capture buttons.
        :rtype: qtwidgets.QHBoxLayout
        """

        row = qtwidgets.QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)

        self.new_animation_pushButton = qtwidgets.QPushButton('New Animation')
        self.new_animation_pushButton.setToolTip(
            "Save the selected rig's animation into the selected folder.")
        row.addWidget(self.new_animation_pushButton)

        self.new_pose_pushButton = qtwidgets.QPushButton('New Pose')
        self.new_pose_pushButton.setToolTip(
            'Save the rig as it stands right now. It does not need to be keyed.')
        row.addWidget(self.new_pose_pushButton)
        return row

    def _connect(self):
        """
        Wire the signals.
        """

        self.project_comboBox.currentIndexChanged.connect(self._on_project_changed)
        self.add_project_pushButton.clicked.connect(self._on_add_project)
        self.remove_project_pushButton.clicked.connect(self._on_remove_project)

        self.search_lineEdit.textChanged.connect(self._refresh_clip_list)
        self.type_comboBox.currentIndexChanged.connect(self._refresh_clip_list)
        self.applicable_checkBox.toggled.connect(self._refresh_clip_list)
        self.refresh_pushButton.clicked.connect(self.refresh)

        self.source_tree.itemSelectionChanged.connect(self._refresh_clip_list)
        self.source_tree.customContextMenuRequested.connect(self._show_tree_menu)
        self.new_folder_pushButton.clicked.connect(self._on_new_folder)
        self.remove_folder_pushButton.clicked.connect(self._on_remove_folder)

        self.clip_list.itemSelectionChanged.connect(self._on_clip_selected)
        self.clip_list.itemEntered.connect(self._on_item_hovered)
        self.clip_list.itemDoubleClicked.connect(self._on_apply_clicked)
        self.clip_list.customContextMenuRequested.connect(self._show_clip_menu)

        self.namespace_group.buttonClicked.connect(self._on_namespace_mode_changed)
        self.reset_source_pushButton.clicked.connect(self._reset_source_range)
        self.apply_pushButton.clicked.connect(self._on_apply_clicked)

        self.blend_slider.sliderPressed.connect(self._on_blend_started)
        self.blend_slider.valueChanged.connect(self._on_blend_changed)
        self.blend_slider.sliderReleased.connect(self._on_blend_finished)
        self.blend_spinBox.valueChanged.connect(self._on_blend_spin_changed)
        self.apply_pose_pushButton.clicked.connect(self._on_apply_pose_clicked)

        self.amount_slider.valueChanged.connect(self.amount_spinBox.setValue)
        self.amount_spinBox.valueChanged.connect(self.amount_slider.setValue)
        self.amount_slider.valueChanged.connect(self._refresh_apply_labels)
        self.blend_slider.valueChanged.connect(self._refresh_apply_labels)
        self.baked_radioButton.toggled.connect(self._refresh_apply_labels)
        self.mirror_checkBox.toggled.connect(self._refresh_apply_labels)
        self.additive_checkBox.toggled.connect(self._refresh_apply_labels)
        self.pose_mirror_checkBox.toggled.connect(self._refresh_apply_labels)
        self.pose_additive_checkBox.toggled.connect(self._refresh_apply_labels)

        self.new_animation_pushButton.clicked.connect(
            lambda: self._on_capture_clicked('animation'))
        self.new_pose_pushButton.clicked.connect(
            lambda: self._on_capture_clicked('pose'))

    def _refresh_apply_labels(self, *args):
        """
        Spell out on the buttons what pressing them will actually do.

        A partial Amount produces a pose half way between what the rig was doing
        and what the clip says - which is a perfectly good tool and looks exactly
        like a broken rig. The slider sits right above the button, so it is easy
        to nudge on the way past; saying "61%" on the button itself is the one
        place it cannot be missed.
        """

        for button, base, amount, mirror, additive in (
                (self.apply_pushButton, 'Apply Animation', self.amount_slider.value(),
                 self.mirror_checkBox.isChecked(), self.additive_checkBox.isChecked()),
                (self.apply_pose_pushButton, 'Apply Pose', self.blend_slider.value(),
                 self.pose_mirror_checkBox.isChecked(),
                 self.pose_additive_checkBox.isChecked())):
            notes = []
            if button is self.apply_pushButton and self.baked_radioButton.isChecked():
                notes.append('baked')
            if mirror:
                notes.append('mirrored')
            if additive:
                notes.append('additive')
            if amount != 100:
                notes.append('{}%'.format(amount))
            button.setText('{} ({})'.format(base, ', '.join(notes)) if notes else base)

    # --- Population -------------------------------------------------------- #

    def refresh(self, keep_place=True, select_clip=None):
        """
        Re-read the catalog and rebuild every panel.

        Rebuilding is how anything new shows up, so it happens after a capture, a
        folder change and a removal - all of which are things done *from* a
        folder, while looking at it. Throwing the selection back to All Clips
        each time means the animator has to find their way back to where they
        already were, and the tell that it happened is the grid emptying.

        :param bool keep_place: Put the tree and grid selection back afterwards.
            False is for switching library: the folder you were standing in
            belongs to the project you just left.
        :param str select_clip: Land on this clip rather than the one that was
            selected. Capture passes the clip it just made.
        """

        character, category = self._current_filter() if keep_place else (None, None)
        clip_id = select_clip or ''
        if keep_place and not clip_id:
            clip_id = (self._selected or {}).get('clip_id', '')

        animlib_api.get_catalog(force_reload=True)
        self._refresh_projects()
        described = animlib_api.describe_library()
        self.root_label.setText((described['result'] or {}).get('library_root', ''))
        self._refresh_namespaces()
        self._refresh_source_tree(character, category)
        self._refresh_clip_list()
        if clip_id:
            self._select_clip(clip_id)
        self.status_label.setText(described['message'])

    def _refresh_projects(self):
        """
        Rebuild the project dropdown from the stored project list.
        """

        self._loading = True
        try:
            response = animlib_api.list_projects()
            rows = response['result'] or []
            self.project_comboBox.clear()
            current_index = 0
            for index, row in enumerate(rows):
                label = row['name'] if row['exists'] else '{} (no folder yet)'.format(row['name'])
                self.project_comboBox.addItem(label, row['name'])
                self.project_comboBox.setItemData(index, row['root'], qtcore.Qt.ToolTipRole)
                if row['current']:
                    current_index = index
            self.project_comboBox.setCurrentIndex(current_index)
            self.remove_project_pushButton.setEnabled(len(rows) > 1)
        finally:
            self._loading = False

    def _refresh_namespaces(self):
        """
        Rebuild the namespace dropdown from the rigs in the open scene.
        """

        previous = self.namespace_comboBox.currentText().strip()
        self.namespace_comboBox.clear()
        response = animlib_maya.list_scene_rigs()
        for row in (response['result'] or []):
            if not row['namespace']:
                continue
            label = row['namespace']
            if row['asset_id']:
                label += '  -  {}'.format(row['asset_id'])
            self.namespace_comboBox.addItem(label, row['namespace'])
        if previous:
            index = self.namespace_comboBox.findText(previous)
            if index >= 0:
                self.namespace_comboBox.setCurrentIndex(index)
            else:
                self.namespace_comboBox.setEditText(previous)

    def _refresh_source_tree(self, character=None, category=None):
        """
        Rebuild the character / folder tree.

        Folders come from :func:`animlib_api.list_folders` rather than from the
        clips, so one made a moment ago and still empty is in the tree where the
        animator expects it.

        Selecting here rather than afterwards matters: signals are blocked while
        the tree is rebuilt, so the grid is filtered once, by the folder that
        ends up selected, instead of once for All Clips and again for the real
        answer.

        :param str character: Land the selection on this character.
        :param str category: ... and on this folder of it. Falls back to the
            character when the folder is gone, and to All Clips when both are.
        """

        self.source_tree.blockSignals(True)
        try:
            self.source_tree.clear()
            everything = qtwidgets.QTreeWidgetItem(self.source_tree)
            everything.setText(0, 'All Clips')
            everything.setData(0, qtcore.Qt.UserRole, (None, None))

            counts = {row['character']: row['clips']
                      for row in (animlib_api.list_characters()['result'] or [])}
            folders = animlib_api.list_folders()['result'] or []

            by_character = {}
            for row in folders:
                by_character.setdefault(row['character'], []).append(row)

            # Not `character` - that is the one we have been asked to land on,
            # and letting the loop overwrite it means the tree always ends up on
            # whichever character happened to be built last.
            for char_name in sorted(by_character, key=lambda x: x.lower()):
                char_item = qtwidgets.QTreeWidgetItem(self.source_tree)
                char_item.setText(0, '{}  ({})'.format(char_name, counts.get(char_name, 0)))
                char_item.setData(0, qtcore.Qt.UserRole, (char_name, None))
                for row in sorted(by_character[char_name], key=lambda r: r['category'].lower()):
                    cat_item = qtwidgets.QTreeWidgetItem(char_item)
                    cat_item.setText(0, '{}  ({})'.format(row['category'], row['clips']))
                    cat_item.setData(0, qtcore.Qt.UserRole, (char_name, row['category']))
                    cat_item.setToolTip(0, row['path'])
                    if not row['clips']:
                        cat_item.setForeground(
                            0, qtgui.QBrush(qtgui.QColor(*UNAPPLICABLE_COLOUR)))

            # Expanded by default: the folders are the point of the panel, and a
            # library with a handful of characters reads better open than as a
            # column of things to click.
            self.source_tree.expandAll()
            if not (character and self._select_folder(character, category)):
                self.source_tree.setCurrentItem(everything)
        finally:
            self.source_tree.blockSignals(False)

    def _current_filter(self):
        """
        :return: ``(character, category)`` from the tree selection.
        :rtype: tuple
        """

        item = self.source_tree.currentItem()
        if item is None:
            return None, None
        data = item.data(0, qtcore.Qt.UserRole)
        return data if data else (None, None)

    def _current_clip_type(self):
        """
        :return: 'animation', 'pose' or None for both.
        :rtype: str or None
        """

        return {'Animations': 'animation', 'Poses': 'pose'}.get(self.type_comboBox.currentText())

    def _refresh_clip_list(self):
        """
        Rebuild the thumbnail grid from the current filter and search text.
        """

        character, category = self._current_filter()
        query = self.search_lineEdit.text().strip()
        clip_type = self._current_clip_type()

        if query:
            response = animlib_api.search_clips(query, limit=0)
            rows = response['result'] or []
            if character:
                rows = [r for r in rows if r.get('character') == character]
            if category:
                rows = [r for r in rows if r.get('category') == category]
            if self.applicable_checkBox.isChecked():
                rows = [r for r in rows if r.get('applicable')]
            if clip_type:
                rows = [r for r in rows if (r.get('clip_type') or 'animation') == clip_type]
        else:
            response = animlib_api.list_clips(
                character=character, category=category, clip_type=clip_type,
                applicable_only=self.applicable_checkBox.isChecked(), limit=0)
            rows = response['result'] or []

        self._clips = rows
        self.clip_list.clear()
        for row in rows:
            # Middle elision keeps the tail, which is what tells
            # ..._IceShards_Master from ..._IceShards_Master_02 apart.
            item = qtwidgets.QListWidgetItem(row['name'])
            item.setTextAlignment(qtcore.Qt.AlignHCenter | qtcore.Qt.AlignTop)
            item.setData(qtcore.Qt.UserRole, row['clip_id'])
            item.setToolTip(self._tooltip_for(row))
            icon = self._thumbnail_for(row)
            if icon is not None:
                item.setIcon(icon)
            if not row.get('applicable'):
                item.setForeground(qtgui.QBrush(qtgui.QColor(*UNAPPLICABLE_COLOUR)))
            self.clip_list.addItem(item)

        poses = sum(1 for r in rows if (r.get('clip_type') or 'animation') == 'pose')
        summary = '{} clip(s) shown.'.format(len(rows))
        if poses:
            summary = '{} shown - {} animation(s), {} pose(s).'.format(
                len(rows), len(rows) - poses, poses)
        self.status_label.setText(summary)

    def _thumbnail_for(self, row):
        """
        The grid icon for a clip, badged with its kind.

        :param dict row: A clip dict.
        :return: An icon, or None when the clip's files could not be read.
        :rtype: qtgui.QIcon or None
        """

        files = animlib_api.get_clip_files(row['clip_id'])
        if not files['ok']:
            return None

        pixmap = None
        # The GIF's first frame is a perfectly good still, so a clip that has one
        # and no jpg is not left with a placeholder.
        for kind in ('preview', 'gif'):
            info = files['result'].get(kind) or {}
            if not info.get('exists'):
                continue
            candidate = qtgui.QPixmap(info['path'])
            if not candidate.isNull():
                pixmap = candidate
                break
        if pixmap is None:
            pixmap = resources.icon(r'company_logos\default_logo.png').pixmap(
                ICON_WIDTH, ICON_HEIGHT)
        if pixmap.isNull():
            return None
        return qtgui.QIcon(badge_pixmap(pixmap, row.get('clip_type') or 'animation'))

    @staticmethod
    def _tooltip_for(row):
        """
        :param dict row: A clip dict.
        :return: Hover text for a grid tile.
        :rtype: str
        """

        lines = ['{} ({})'.format(row['name'], row['clip_id']),
                 'Type: {}'.format(row.get('clip_type') or 'animation'),
                 'Character: {}'.format(row.get('character') or '-'),
                 'Folder: {}'.format(row.get('category') or '-'),
                 'Frames: {:.0f} ({} fps)'.format(row.get('duration') or 0, row.get('fps') or '?'),
                 'Root motion: {}'.format(row.get('root_motion') or 'unknown')]
        if row.get('has_layers'):
            lines.append('Has animation layers - apply with "replace all"')
        if not row.get('applicable'):
            lines.append('No curve file - cannot be applied to a rig')
        return '\n'.join(lines)

    # --- Selection --------------------------------------------------------- #

    def _stop_movie(self):
        """
        Let go of any GIF the preview was playing, and of the file behind it.

        Stopping a QMovie is not enough: it holds the file open until it is
        pointed somewhere else, and on Windows that is a lock. Having merely
        *looked* at a clip would then stop it being deleted or overwritten, which
        is a baffling thing for a browser to do.
        """

        if self._movie is None:
            return
        self._movie.stop()
        self.preview_label.setMovie(None)
        self._movie.setFileName('')
        self._movie.deleteLater()
        self._movie = None
        self._animating = False

    def _on_clip_selected(self):
        """
        Fill the detail panel and swap in the controls for the clip's kind.
        """

        item = self.clip_list.currentItem()
        if item is None:
            self._selected = None
            self.apply_pushButton.setEnabled(False)
            self.apply_pose_pushButton.setEnabled(False)
            self.detail_textEdit.clear()
            self._stop_movie()
            self._previewing = None
            self._animating = False
            self.preview_label.setPixmap(qtgui.QPixmap())
            self.preview_label.setText('No clip selected')
            return

        clip_id = item.data(qtcore.Qt.UserRole)
        response = animlib_api.get_clip(clip_id, verbose=True)
        if not response['ok']:
            self.detail_textEdit.setText(response['message'])
            return

        clip = response['result']
        self._selected = clip
        is_pose = (clip.get('clip_type') or 'animation') == 'pose'
        self.apply_stack.setCurrentIndex(1 if is_pose else 0)
        self.apply_pushButton.setEnabled(bool(clip.get('applicable')) and not is_pose)
        self.apply_pose_pushButton.setEnabled(bool(clip.get('applicable')) and is_pose)
        self._refresh_source_choice(clip)
        self._reset_source_range()

        files = animlib_api.get_clip_files(clip_id)['result'] or {}
        self.detail_textEdit.setText(self._detail_text(clip, files))
        self._show_preview(files, clip_id)

    @staticmethod
    def _detail_text(clip, files):
        """
        :param dict clip: The clip record.
        :param dict files: Its files as get_clip_files returns them.
        :return: The detail panel's text.
        :rtype: str
        """

        lines = [
            'Name:        {}'.format(clip['name']),
            'Type:        {}'.format(clip.get('clip_type') or 'animation'),
            'Id:          {}'.format(clip['clip_id']),
            'Character:   {}'.format(clip.get('character') or '-'),
            'Folder:      {}'.format(clip.get('category') or '-'),
            'Frames:      {} - {}'.format(*(clip.get('frame_range') or [0, 0])),
            'Duration:    {:.0f} frames @ {} fps'.format(clip.get('duration') or 0,
                                                         clip.get('fps') or '?'),
            'Root motion: {}'.format(clip.get('root_motion') or 'unknown'),
            'Layers:      {}'.format('yes' if clip.get('has_layers') else 'no'),
            'Flags:       {}'.format(clip.get('flag_count') or 0),
            '',
            'Files:',
        ]
        for kind in ('curves', 'fbx', 'preview', 'gif'):
            info = files.get(kind) or {}
            if info.get('recorded'):
                mark = 'ok' if info.get('exists') else 'MISSING'
                lines.append('  {:<8} {}  [{}]'.format(kind, info['recorded'], mark))
            else:
                lines.append('  {:<8} -'.format(kind))
        if clip.get('has_layers'):
            lines += ['', 'This clip carries animation layers. Only "replace all" over the '
                          'whole clip puts those back intact.']
        if clip.get('tags'):
            lines += ['', 'Tags: {}'.format(', '.join(clip['tags']))]
        if clip.get('description'):
            lines += ['', clip['description']]
        if clip.get('source_file'):
            lines += ['', 'Captured from: {}'.format(clip['source_file'])]
        return '\n'.join(lines)

    def _show_preview(self, files, clip_id=None, animate=False):
        """
        Show the clip in the preview slot, moving or still.

        Only a hovered clip animates. A GIF looping away on its own while you
        read the detail panel is a distraction, and something moving in the
        corner of the eye reads as "this is happening now" when nothing is.

        :param dict files: The clip's files as get_clip_files returns them.
        :param str clip_id: What is being shown, so hovering can tell whether the
            slot already holds the right clip.
        :param bool animate: Play the GIF rather than showing a still of it.
        """

        self._stop_movie()
        self._previewing = clip_id
        self._animating = bool(animate)
        gif = files.get('gif') or {}
        if animate and gif.get('exists'):
            movie = qtgui.QMovie(gif['path'])
            if movie.isValid():
                # Scaled once, and to the label's own box, so a wide clip does
                # not spill over the detail text.
                box = qtcore.QSize(self.preview_label.width() - 4,
                                   self.preview_label.height() - 4)
                movie.setCacheMode(qtgui.QMovie.CacheAll)
                movie.setScaledSize(self._fit(movie, box))
                self.preview_label.setPixmap(qtgui.QPixmap())
                self.preview_label.setMovie(movie)
                movie.start()
                self._movie = movie
                return

        # A still: the thumbnail, or failing that the GIF's first frame, which
        # QPixmap reads happily.
        for kind in ('preview', 'gif'):
            info = files.get(kind) or {}
            if not info.get('exists'):
                continue
            pixmap = qtgui.QPixmap(info['path'])
            if not pixmap.isNull():
                self.preview_label.setPixmap(pixmap.scaled(
                    self.preview_label.width(), self.preview_label.height(),
                    qtcore.Qt.KeepAspectRatio, qtcore.Qt.SmoothTransformation))
                return

        self.preview_label.setPixmap(qtgui.QPixmap())
        self.preview_label.setText('No preview')

    @staticmethod
    def _fit(movie, box):
        """
        The size a movie should be scaled to so it fits a box without distortion.

        :param qtgui.QMovie movie: The movie.
        :param qtcore.QSize box: The space available.
        :return: The scaled size.
        :rtype: qtcore.QSize
        """

        movie.jumpToFrame(0)
        native = movie.currentPixmap().size()
        if native.width() <= 0 or native.height() <= 0:
            return box
        scale = min(box.width() / float(native.width()),
                    box.height() / float(native.height()))
        return qtcore.QSize(max(1, int(native.width() * scale)),
                            max(1, int(native.height() * scale)))

    def _reset_source_range(self):
        """
        Put the source spin boxes back to the selected clip's whole range.
        """

        frame_range = (self._selected or {}).get('frame_range') or [0, 0]
        self.source_start_spinBox.setValue(int(round(float(frame_range[0]))))
        self.source_end_spinBox.setValue(int(round(float(frame_range[1]))))

    # --- Namespace --------------------------------------------------------- #

    def _on_namespace_mode_changed(self, *args):
        """
        Enable the namespace field only when it is being used.
        """

        self.namespace_comboBox.setEnabled(self.namespace_custom_radioButton.isChecked())

    def _chosen_namespace(self):
        """
        The namespace to apply into.

        :return: A namespace, ':' for the root namespace, or None to work it out
            from the selection.
        :rtype: str or None
        """

        if self.namespace_none_radioButton.isChecked():
            return animlib_maya.ROOT_NAMESPACE
        if not self.namespace_custom_radioButton.isChecked():
            return None

        text = self.namespace_comboBox.currentText().strip()
        index = self.namespace_comboBox.findText(text)
        if index >= 0:
            return self.namespace_comboBox.itemData(index) or text.strip(':') or None
        return text.strip(':') or None

    # --- Projects ---------------------------------------------------------- #

    def _on_project_changed(self, *args):
        """
        Switch libraries.
        """

        if self._loading:
            return
        name = self.project_comboBox.currentData()
        if not name:
            return
        response = animlib_api.set_current_project(name)
        if not response['ok']:
            dialogs.info_prompt(title='Could not switch project', text=response['message'])
            return
        self.refresh(keep_place=False)
        self.status_label.setText(response['message'])

    def _on_add_project(self):
        """
        Add a library folder to the project list and switch to it.
        """

        dialog = animlib_dialogs.ProjectDialog(parent=self)
        if not dialog.exec_():
            return
        name, root = dialog.values()
        response = animlib_api.add_project(name, root, make_current=True)
        if not response['ok']:
            dialogs.info_prompt(title='Could not add the project', text=response['message'])
            return
        self.refresh(keep_place=False)
        self.status_label.setText(response['message'])

    def _on_remove_project(self):
        """
        Forget the current project. Its library on disk is untouched.
        """

        name = self.project_comboBox.currentData()
        if not name:
            return
        confirm = dialogs.question_prompt(
            title='Remove Project',
            text='Remove {!r} from the project list?\n\n'
                 'Its library folder and everything in it stays on disk.'.format(name))
        if confirm not in ('Yes', True):
            return
        response = animlib_api.remove_project(name)
        if not response['ok']:
            dialogs.info_prompt(title='Could not remove the project', text=response['message'])
            return
        self.refresh(keep_place=False)
        self.status_label.setText(response['message'])

    # --- Folders ----------------------------------------------------------- #

    def _on_new_folder(self):
        """
        Make a folder in the library.
        """

        character, _category = self._current_filter()
        dialog = animlib_dialogs.NewFolderDialog(character=character or '', parent=self)
        if not dialog.exec_():
            return
        character, category = dialog.values()
        if not character or not category:
            dialogs.info_prompt(title='New Folder',
                                text='A folder needs both a character and a name.')
            return
        response = animlib_api.create_folder(character, category)
        if not response['ok']:
            dialogs.info_prompt(title='Could not make the folder', text=response['message'])
            return
        self._refresh_source_tree(character, category)
        self._refresh_clip_list()
        self.status_label.setText(response['message'])

    def _on_remove_folder(self):
        """
        Remove the selected folder, asking first if it still holds clips.
        """

        character, category = self._current_filter()
        if not character or not category:
            dialogs.info_prompt(title='Remove Folder',
                                text='Pick a folder in the tree first.')
            return

        response = animlib_api.remove_folder(character, category, force=False)
        if not response['ok']:
            confirm = dialogs.question_prompt(
                title='Remove Folder',
                text='{}\n\nDelete the folder and everything in it anyway?'
                     .format(response['message']))
            if confirm not in ('Yes', True):
                return
            response = animlib_api.remove_folder(character, category, force=True)
            if not response['ok']:
                dialogs.info_prompt(title='Could not remove the folder',
                                    text=response['message'])
                return
        self.refresh()
        self.status_label.setText(response['message'])

    def _show_tree_menu(self, point):
        """
        Right-click actions on the source tree.

        :param qtcore.QPoint point: Where the menu was asked for.
        """

        item = self.source_tree.itemAt(point)
        if item is not None:
            self.source_tree.setCurrentItem(item)
        character, category = self._current_filter()

        menu = qtwidgets.QMenu(self.source_tree)
        new_action = menu.addAction('New Folder...')
        remove_action = menu.addAction('Remove Folder')
        remove_action.setEnabled(bool(character and category))
        menu.addSeparator()
        show_action = menu.addAction('Show Folder')
        show_action.setEnabled(bool(character and category))

        chosen = menu.exec_(self.source_tree.viewport().mapToGlobal(point))
        if chosen == new_action:
            self._on_new_folder()
        elif chosen == remove_action:
            self._on_remove_folder()
        elif chosen == show_action:
            rows = animlib_api.list_folders(character)['result'] or []
            match = [r for r in rows if r['category'] == category]
            if match:
                self._open_in_explorer(match[0]['path'])

    @staticmethod
    def _open_in_explorer(path):
        """
        :param str path: A folder to show the user.
        """

        if not path or not os.path.isdir(path):
            return
        try:
            os.startfile(path)
        except Exception:
            logger.debug('Could not open %s', path, exc_info=True)

    # --- Applying an animation --------------------------------------------- #

    def _refresh_source_choice(self, clip):
        """
        Offer only the halves this clip actually has.

        A capture can write flag curves, baked joints or both, so which routes
        exist is a property of the clip in front of you rather than a setting.
        Greying out the one that is missing says that; leaving it clickable and
        failing afterwards does not.

        Landing on a half the previous clip had and this one does not would
        apply the wrong thing on the next click, so the choice falls back to
        whichever route exists.

        :param dict clip: The selected clip.
        """

        has_curves = bool(clip.get('has_curves'))
        has_baked = bool(clip.get('has_baked_joints'))
        self.curves_radioButton.setEnabled(has_curves)
        self.baked_radioButton.setEnabled(has_baked)
        if self.baked_radioButton.isChecked() and not has_baked:
            self.curves_radioButton.setChecked(True)
        elif self.curves_radioButton.isChecked() and not has_curves:
            self.baked_radioButton.setChecked(has_baked)
        self._refresh_apply_labels()

    def _apply_kwargs(self):
        """
        The animation apply options as the API wants them.

        The source range is passed only when it has actually been narrowed. Left
        at the clip's own range it is None, which lets the fast restore path run
        and keeps animation layers intact.

        :return: Keyword arguments for :func:`animlib_maya.apply_clip`.
        :rtype: dict
        """

        clip_range = (self._selected or {}).get('frame_range') or [0, 0]
        source = [float(self.source_start_spinBox.value()),
                  float(self.source_end_spinBox.value())]
        whole = source == [float(clip_range[0]), float(clip_range[1])]

        return {
            'option': self.option_comboBox.currentData(),
            'source_range': None if whole else source,
            'start_time': float(pm.currentTime(q=True))
                          if self.current_time_checkBox.isChecked() else None,
            'selected_only': self.apply_selected_checkBox.isChecked(),
            'namespace': self._chosen_namespace(),
            'mirror': self.mirror_checkBox.isChecked(),
            'additive': self.additive_checkBox.isChecked(),
            'amount': float(self.amount_slider.value()),
            'source': 'baked' if self.baked_radioButton.isChecked() else 'curves',
        }

    def _on_apply_clicked(self, *args):
        """
        Apply the selected clip with the chosen options.

        Double-clicking a pose lands here too, and applying a pose is a different
        call, so this forwards rather than making the grid know the difference.
        """

        if not self._selected:
            return
        if (self._selected.get('clip_type') or 'animation') == 'pose':
            self._on_apply_pose_clicked()
            return

        response = animlib_maya.apply_clip(self._selected['clip_id'], **self._apply_kwargs())
        self._report(response, 'Could not apply clip')

    # --- Applying a pose --------------------------------------------------- #

    def _pose_kwargs(self):
        """
        :return: Keyword arguments shared by the pose blend calls.
        :rtype: dict
        """

        return {'namespace': self._chosen_namespace(),
                'selected_only': self.pose_selected_checkBox.isChecked(),
                'mirror': self.pose_mirror_checkBox.isChecked(),
                'additive': self.pose_additive_checkBox.isChecked()}

    def _pose_set_key(self):
        """
        :return: True, False, or None to follow Maya's auto-key state.
        :rtype: bool or None
        """

        return self.pose_key_comboBox.currentData()

    def _on_blend_started(self):
        """
        Begin a live blend when the slider is grabbed.

        Reading the pose once here is what makes the drag cheap - the updates
        that follow are attribute writes and nothing else.
        """

        if not self._selected or (self._selected.get('clip_type') or '') != 'pose':
            return
        response = animlib_maya.start_pose_blend(self._selected['clip_id'], **self._pose_kwargs())
        if not response['ok']:
            self.status_label.setText(response['message'])
            return
        self._blending = True
        animlib_maya.update_pose_blend(self.blend_slider.value())

    def _on_blend_changed(self, value):
        """
        Follow the slider, on the rig and in the number beside it.

        :param int value: The slider's new value.
        """

        if self.blend_spinBox.value() != value:
            self.blend_spinBox.blockSignals(True)
            self.blend_spinBox.setValue(value)
            self.blend_spinBox.blockSignals(False)
        if self._blending:
            animlib_maya.update_pose_blend(value)

    def _on_blend_spin_changed(self, value):
        """
        :param int value: The spin box's new value.
        """

        if self.blend_slider.value() != value:
            self.blend_slider.setValue(value)

    def _on_blend_finished(self):
        """
        Keep what the drag left on the rig.
        """

        if not self._blending:
            return
        self._blending = False
        response = animlib_maya.finish_pose_blend(percent=self.blend_slider.value(),
                                                  set_key=self._pose_set_key())
        self.status_label.setText(response['message'])

    def _on_apply_pose_clicked(self, *args):
        """
        Put the selected pose on at the blend amount, in one go.
        """

        if not self._selected:
            return
        response = animlib_maya.apply_pose(self._selected['clip_id'],
                                           percent=float(self.blend_slider.value()),
                                           set_key=self._pose_set_key(),
                                           **self._pose_kwargs())
        self._report(response, 'Could not apply pose')

    # --- Capture ----------------------------------------------------------- #

    def _on_capture_clicked(self, clip_type):
        """
        Capture a new clip or pose off the rig in the scene.

        :param str clip_type: 'animation' or 'pose'.
        """

        character, category = self._current_filter()
        if not category:
            dialogs.info_prompt(
                title='Pick a folder first',
                text='Clips are saved into the folder selected in the browser, so pick one '
                     'on the left.\n\nUse New Folder if the one you want does not exist yet.')
            return

        dialog = animlib_dialogs.CaptureDialog(
            clip_type=clip_type, character=character or '', category=category, parent=self,
            settings=self.settings)
        if not dialog.exec_():
            return

        values = dialog.values()
        if clip_type == 'pose':
            response = animlib_maya.capture_pose(**values)
        else:
            response = animlib_maya.capture_clip(**values)

        self._report(response, 'Could not capture')
        if response['ok']:
            self.refresh(select_clip=(response['result'] or {}).get('clip_id', ''))

    def _report(self, response, failure_title):
        """
        Put a response on the status bar, and in front of the user when it failed.

        :param dict response: An ok/result/message response.
        :param str failure_title: Dialog title to use when it did not work.
        """

        self.status_label.setText(response['message'])
        if response['ok']:
            logger.info(response['message'])
            return
        logger.warning(response['message'])
        dialogs.info_prompt(title=failure_title, text=response['message'])

    # --- Hover ------------------------------------------------------------- #

    def _on_item_hovered(self, item):
        """
        Play the hovered clip in the preview slot.

        The selection is left alone on purpose: scrubbing the grid to find the
        right clip should not keep re-arming the Apply button against whatever
        the mouse last crossed.

        :param qtwidgets.QListWidgetItem item: The tile under the cursor.
        """

        if item is None:
            return
        clip_id = item.data(qtcore.Qt.UserRole)
        if clip_id == self._previewing:
            return
        files = animlib_api.get_clip_files(clip_id)
        if files['ok']:
            self._show_preview(files['result'] or {}, clip_id, animate=True)

    def _restore_selected_preview(self):
        """
        Put the preview back to the selected clip once the mouse leaves the grid.
        """

        if not self._selected:
            if self._previewing is not None:
                self._stop_movie()
                self.preview_label.setPixmap(qtgui.QPixmap())
                self.preview_label.setText('No clip selected')
                self._previewing = None
            return
        if self._previewing == self._selected['clip_id'] and not self._animating:
            return
        files = animlib_api.get_clip_files(self._selected['clip_id'])
        if files['ok']:
            self._show_preview(files['result'] or {}, self._selected['clip_id'])

    def eventFilter(self, watched, event):
        """
        Catch the mouse leaving the grid, so the preview goes back to the selection.

        :param watched: The widget the event is for.
        :param event: The event.
        :return: Whether the event was consumed.
        :rtype: bool
        """

        if watched is self.clip_list.viewport() and event.type() == qtcore.QEvent.Leave:
            self._restore_selected_preview()
        return super().eventFilter(watched, event)

    # --- Remembering ------------------------------------------------------- #

    def _restore_options(self):
        """
        Put the filters and apply options back the way they were left.

        Done before the first refresh so the tree and grid are built once, with
        the right filters, instead of being rebuilt as each one is restored.
        """

        settings = self.settings
        self._loading = True
        try:
            self.search_lineEdit.setText(settings.value('browser/search', '') or '')
            clip_type = settings.value('browser/clip_type', ALL_TYPES) or ALL_TYPES
            index = self.type_comboBox.findText(clip_type)
            if index >= 0:
                self.type_comboBox.setCurrentIndex(index)
            self.applicable_checkBox.setChecked(
                _to_bool(settings.value('browser/applicable_only', False)))

            option = settings.value('apply/option', 'replace_all') or 'replace_all'
            index = self.option_comboBox.findData(option)
            if index >= 0:
                self.option_comboBox.setCurrentIndex(index)
            self.current_time_checkBox.setChecked(
                _to_bool(settings.value('apply/current_time', False)))
            self.apply_selected_checkBox.setChecked(
                _to_bool(settings.value('apply/selected_only', False)))
            source_button = self.source_group.button(_to_int(settings.value('apply/source', 0), 0))
            if source_button is not None:
                source_button.setChecked(True)
            self.mirror_checkBox.setChecked(_to_bool(settings.value('apply/mirror', False)))
            self.additive_checkBox.setChecked(_to_bool(settings.value('apply/additive', False)))
            self.pose_mirror_checkBox.setChecked(_to_bool(settings.value('pose/mirror', False)))
            self.pose_additive_checkBox.setChecked(
                _to_bool(settings.value('pose/additive', False)))
            # Amount and Blend deliberately do NOT come back. They are modifiers
            # on one action, not settings, and a remembered 61% is invisible
            # until it has already produced a pose that looks like a broken rig.
            self.amount_slider.setValue(100)
            self.blend_slider.setValue(100)

            self.pose_selected_checkBox.setChecked(
                _to_bool(settings.value('pose/selected_only', False)))
            key_index = _to_int(settings.value('pose/set_key_index', 0), 0)
            if 0 <= key_index < self.pose_key_comboBox.count():
                self.pose_key_comboBox.setCurrentIndex(key_index)

            mode = _to_int(settings.value('namespace/mode', 1), 1)
            button = self.namespace_group.button(mode)
            if button is not None:
                button.setChecked(True)
            self._on_namespace_mode_changed()
            custom = settings.value('namespace/custom', '') or ''
            if custom:
                self.namespace_comboBox.setEditText(custom)

            geometry = settings.value('window/geometry')
            if geometry:
                self.restoreGeometry(geometry)
            sizes = settings.value('window/splitter')
            if sizes:
                try:
                    self.splitter.setSizes([int(s) for s in sizes])
                except (TypeError, ValueError):
                    logger.debug('Stored splitter sizes were unusable: %r', sizes)
        finally:
            self._loading = False

    def _restore_selection(self):
        """
        Reselect the folder and clip that were open last time.

        Folder first: selecting it rebuilds the grid, and the clip has to be
        looked for in that grid rather than the one the refresh happened to leave.
        """

        settings = self.settings
        character = settings.value('browser/character', '') or ''
        category = settings.value('browser/category', '') or ''
        if character:
            self._select_folder(character, category)
        clip_id = settings.value('browser/clip_id', '') or ''
        if clip_id:
            self._select_clip(clip_id)

    def _select_folder(self, character, category):
        """
        Put the tree selection on a character, or one of its folders.

        :param str character: The character's asset id.
        :param str category: The folder, or '' for the character itself.
        :return: True when it was found.
        :rtype: bool
        """

        for index in range(self.source_tree.topLevelItemCount()):
            top = self.source_tree.topLevelItem(index)
            data = top.data(0, qtcore.Qt.UserRole) or (None, None)
            if data[0] != character:
                continue
            if not category:
                self.source_tree.setCurrentItem(top)
                return True
            for child_index in range(top.childCount()):
                child = top.child(child_index)
                child_data = child.data(0, qtcore.Qt.UserRole) or (None, None)
                if child_data[1] == category:
                    self.source_tree.setCurrentItem(child)
                    return True
            # The folder is gone - somebody deleted it, or this is another
            # project. The character is still the better answer than nothing.
            self.source_tree.setCurrentItem(top)
            return True
        return False

    def _select_clip(self, clip_id):
        """
        Put the grid selection on a clip.

        :param str clip_id: The clip's id.
        :return: True when it was found.
        :rtype: bool
        """

        for row in range(self.clip_list.count()):
            item = self.clip_list.item(row)
            if item.data(qtcore.Qt.UserRole) == clip_id:
                self.clip_list.setCurrentItem(item)
                self.clip_list.scrollToItem(item)
                return True
        return False

    def _save_state(self):
        """
        Remember where the browser was, so reopening lands back there.
        """

        settings = self.settings
        character, category = self._current_filter()
        settings.setValue('browser/character', character or '')
        settings.setValue('browser/category', category or '')
        settings.setValue('browser/clip_id',
                          (self._selected or {}).get('clip_id', ''))
        settings.setValue('browser/search', self.search_lineEdit.text())
        settings.setValue('browser/clip_type', self.type_comboBox.currentText())
        settings.setValue('browser/applicable_only', self.applicable_checkBox.isChecked())

        settings.setValue('apply/option', self.option_comboBox.currentData())
        settings.setValue('apply/current_time', self.current_time_checkBox.isChecked())
        settings.setValue('apply/selected_only', self.apply_selected_checkBox.isChecked())
        settings.setValue('apply/source', self.source_group.checkedId())
        settings.setValue('apply/mirror', self.mirror_checkBox.isChecked())
        settings.setValue('apply/additive', self.additive_checkBox.isChecked())
        # Amount and Blend are not saved; see _restore_options.
        settings.setValue('pose/mirror', self.pose_mirror_checkBox.isChecked())
        settings.setValue('pose/additive', self.pose_additive_checkBox.isChecked())

        settings.setValue('pose/selected_only', self.pose_selected_checkBox.isChecked())

        settings.setValue('pose/set_key_index', self.pose_key_comboBox.currentIndex())

        settings.setValue('namespace/mode', self.namespace_group.checkedId())
        settings.setValue('namespace/custom', self.namespace_comboBox.currentText())

        settings.setValue('window/geometry', self.saveGeometry())
        settings.setValue('window/splitter', self.splitter.sizes())

    def _show_clip_menu(self, point):
        """
        Right-click actions on a clip tile.

        :param qtcore.QPoint point: Where the menu was asked for.
        """

        item = self.clip_list.itemAt(point)
        if item is None:
            return
        self.clip_list.setCurrentItem(item)
        clip_id = item.data(qtcore.Qt.UserRole)
        is_pose = (self._selected or {}).get('clip_type') == 'pose'

        menu = qtwidgets.QMenu(self.clip_list)
        apply_action = menu.addAction('Apply Pose' if is_pose else 'Apply to Rig')
        apply_action.setEnabled(bool(self._selected and self._selected.get('applicable')))
        rebuild_action = menu.addAction('Rebuild FBX from Curves')
        rebuild_action.setEnabled(not is_pose)
        menu.addSeparator()
        folder_action = menu.addAction('Show Files')
        remove_action = menu.addAction('Remove from Library')

        chosen = menu.exec_(self.clip_list.viewport().mapToGlobal(point))
        if chosen == apply_action:
            self._on_apply_clicked()
        elif chosen == rebuild_action:
            response = animlib_maya.rebuild_clip_fbx(clip_id)
            self._report(response, 'Could not rebuild the FBX')
        elif chosen == folder_action:
            files = animlib_api.get_clip_files(clip_id)
            self.detail_textEdit.setText(
                '\n'.join('{:<8} {}'.format(k, v.get('path') or '-')
                          for k, v in sorted((files['result'] or {}).items())))
        elif chosen == remove_action:
            confirm = dialogs.question_prompt(
                title='Remove Clip',
                text='Remove {} from the library?\n\nIts files are left on disk.'
                     .format(item.text()))
            if confirm in ('Yes', True):
                response = animlib_api.remove_clip(clip_id)
                self.status_label.setText(response['message'])
                self.refresh()

    def closeEvent(self, event):
        """
        Stop the preview and let go of any blend still in progress.

        :param event: The close event.
        """

        try:
            self._save_state()
        except Exception:
            # Losing the remembered folder is a nuisance; failing to close is
            # worse, and a stylesheet or settings problem should not trap the
            # window open.
            logger.warning('Could not save the browser state.', exc_info=True)
        self._stop_movie()
        if self._blending:
            self._blending = False
            animlib_maya.finish_pose_blend(cancel=True)
        super().closeEvent(event)
