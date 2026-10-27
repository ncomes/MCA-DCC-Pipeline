"""
The capture dialog and its small siblings: everything a save needs, in one place.

The dialog asks for as little as it can get away with. It does **not** ask which
rig - a flag selected in the viewport already says that, and the FRAG node gets
from there to every other flag or to a baked skeleton on its own. It does not ask
for an asset id either, because nobody memorises those; it reads it off the rig.
And it does not guess a folder: the one selected in the browser is the one that
is saved to, which is the only answer that is never a surprise.

Two shapes, one dialog. A pose has no frame range, no FBX and no GIF - a
one-frame skeleton bake is not something any other DCC wants and a one-frame GIF
is a still - so those controls are absent rather than present and ignored.

:Requires: mca.common.animlib, mca.common.pyqt
:Side effects: None. The dialog only collects choices; the caller runs them.
"""

# python imports
import os

# software specific imports
import pymel.core as pm

# MCA python imports
from mca.common import log
from mca.common.animlib import animlib_api, clip as clip_module
from mca.common.pyqt.pygui import qtwidgets, qtcore
from mca.mya.animation import time_utils
from mca.mya.tools.animlibrary import animlib_maya

logger = log.MCA_LOGGER

# What gets written. The wording is the animator's, not the pipeline's: "flag
# animations" is what goes back onto a rig, "baked joints" is what leaves Maya.
SAVE_CHOICES = (
    ('both', 'Flag Animations + Baked Joints',
     'The flag animation, which can be applied back onto a rig, and a baked\n'
     'joints-only FBX for Blender, MotionBuilder and the engine.'),
    ('curves', 'Flag Animations',
     'Just the flag animation. Keeps animation layers and flag context, and is\n'
     'what you apply back onto a rig. No FBX, so nothing leaves Maya.'),
    ('fbx', 'Baked Joints',
     'Just the baked skeleton. Portable, but flattened - it cannot be applied\n'
     'back onto a rig, so the library will list it as not applicable.'),
)


def to_bool(value, default=False):
    """
    Read a QSettings value as a bool.

    QSettings on Windows stores booleans as the strings 'true' and 'false', and
    both of those are truthy in Python - so the naive read turns every remembered
    checkbox on.

    :param value: Whatever came back from QSettings.
    :param bool default: Used when the value is missing.
    :return: The boolean.
    :rtype: bool
    """

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('true', '1', 'yes')


def to_int(value, default=0):
    """
    Read a QSettings value as an int.

    Not ``int(value or default)``: a stored 0 is falsy, so that idiom quietly
    swaps every legitimate zero for the default - which is how the first radio
    button in a group stops being restorable.

    :param value: Whatever came back from QSettings.
    :param int default: Used when the value is missing or unreadable.
    :return: The integer.
    :rtype: int
    """

    if value is None or value == '':
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def describe_selected_rig():
    """
    Work out which rig a capture would act on, from the selection.

    :return: ``{'ok', 'rig', 'asset_id', 'namespace', 'flags', 'selected_flags',
        'message'}``. ``ok`` is False when there is nothing to capture.
    :rtype: dict
    """

    try:
        rig = animlib_maya.resolve_rig()
    except Exception as exc:
        return {'ok': False, 'rig': None, 'asset_id': '', 'namespace': '',
                'flags': 0, 'selected_flags': 0, 'message': str(exc)}

    asset_id = animlib_maya.rig_asset_id(rig)
    namespace = animlib_maya.rig_namespace(rig)
    try:
        flags = rig.get_flags()
    except Exception:
        flags = []
    try:
        selected = animlib_maya.target_flags(rig, selected_only=True)
    except Exception:
        selected = []

    label = asset_id or '(no asset id)'
    if namespace:
        label += '  ({})'.format(namespace)
    label += '  -  {} flags'.format(len(flags))
    if selected:
        label += ', {} selected'.format(len(selected))

    return {'ok': True, 'rig': rig, 'asset_id': asset_id, 'namespace': namespace,
            'flags': len(flags), 'selected_flags': len(selected), 'message': label}


class CaptureDialog(qtwidgets.QDialog):
    """
    Collect everything a capture needs before anything is written.
    """

    def __init__(self, clip_type='animation', character='', category='', parent=None,
                 settings=None):
        """
        :param str clip_type: 'animation' or 'pose'.
        :param str character: Character of the folder selected in the browser.
        :param str category: Folder selected in the browser.
        :param parent: Parent widget.
        :param settings: The browser's QSettings, so the dialog opens the way it
            was last left. None turns the memory off rather than guessing at a
            settings location of its own.
        """

        super().__init__(parent)
        self.settings = settings if settings is not None else getattr(parent, 'settings', None)
        self.clip_type = clip_type if clip_type in clip_module.CLIP_TYPES else 'animation'
        self.is_pose = self.clip_type == 'pose'
        self.setWindowTitle('Capture Pose' if self.is_pose else 'Capture Animation')
        self.setMinimumWidth(440)

        self.folder_character = str(character or '')
        self.folder_category = str(category or '')
        self.rig_info = describe_selected_rig()

        self._build()
        self._fill_from_scene()
        self._restore_choices()

    # --- Construction ------------------------------------------------------ #

    def _build(self):
        """
        Lay the form out.
        """

        layout = qtwidgets.QVBoxLayout(self)
        form = qtwidgets.QFormLayout()
        form.setFieldGrowthPolicy(qtwidgets.QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        # Read-only, because both of these are answers the scene and the browser
        # already gave. Asking again is how they end up disagreeing.
        self.rig_label = qtwidgets.QLabel('')
        self.rig_label.setToolTip(
            'Taken from your selection. Select a flag on the rig you mean;\n'
            'the rig knows about the rest of its flags and its skeleton.')
        form.addRow('Rig:', self.rig_label)

        self.folder_label = qtwidgets.QLabel('')
        self.folder_label.setToolTip('The folder selected in the browser.')
        form.addRow('Save to:', self.folder_label)

        self.name_lineEdit = qtwidgets.QLineEdit()
        self.name_lineEdit.setPlaceholderText('FW_Idle_Combat_01')
        form.addRow('Name:', self.name_lineEdit)

        if self.is_pose:
            self.frame_spinBox = qtwidgets.QSpinBox()
            self.frame_spinBox.setRange(-100000, 100000)
            self.frame_spinBox.setToolTip('The frame to read the pose at.')
            form.addRow('Frame:', self.frame_spinBox)
        else:
            range_row = qtwidgets.QHBoxLayout()
            self.start_spinBox = qtwidgets.QSpinBox()
            self.start_spinBox.setRange(-100000, 100000)
            self.end_spinBox = qtwidgets.QSpinBox()
            self.end_spinBox.setRange(-100000, 100000)
            range_row.addWidget(self.start_spinBox)
            range_row.addWidget(self.end_spinBox)
            self.range_source_comboBox = qtwidgets.QComboBox()
            self.range_source_comboBox.addItems(['From keys', 'Timeline', 'Custom'])
            self.range_source_comboBox.setToolTip(
                'From keys: the first and last key on the rig.\n'
                'Timeline: the visible frame range.\n'
                'Custom: whatever you type.')
            range_row.addWidget(self.range_source_comboBox)
            form.addRow('Frames:', range_row)

            self.save_option_comboBox = qtwidgets.QComboBox()
            for _key, label, tip in SAVE_CHOICES:
                self.save_option_comboBox.addItem(label)
                self.save_option_comboBox.setItemData(
                    self.save_option_comboBox.count() - 1, tip, qtcore.Qt.ToolTipRole)
            form.addRow('Save Option:', self.save_option_comboBox)

        self.selected_checkBox = qtwidgets.QCheckBox('Selected flags only')
        self.selected_checkBox.setToolTip(
            'Store only the flags you have selected, rather than everything on the rig.\n'
            'Off, the selection is only used to work out which rig you mean.')
        form.addRow('', self.selected_checkBox)

        self.preview_checkBox = qtwidgets.QCheckBox('Grab a thumbnail')
        self.preview_checkBox.setChecked(True)
        form.addRow('', self.preview_checkBox)

        if not self.is_pose:
            self.gif_checkBox = qtwidgets.QCheckBox('Capture a GIF')
            self.gif_checkBox.setChecked(True)
            self.gif_checkBox.setToolTip(
                'Play the range down to a looping GIF for the browser.\n'
                'A still frame cannot tell a run cycle from a walk cycle; this can.\n'
                'It costs a playblast of every frame.')
            possible, reason = animlib_maya.gifs_are_possible()
            if not possible:
                self.gif_checkBox.setChecked(False)
                self.gif_checkBox.setEnabled(False)
                self.gif_checkBox.setToolTip(reason)
            form.addRow('', self.gif_checkBox)

        self.flatten_checkBox = qtwidgets.QCheckBox('Flatten animation layers')
        layered = animlib_maya.scene_has_layers()
        self.flatten_checkBox.setEnabled(layered)
        self.flatten_checkBox.setToolTip(
            'Collapse the layers into one curve per channel as the clip is written.\n'
            'Off, the layers are kept, which is the default - a flattened clip\n'
            'cannot be un-flattened, and the rig in the scene is untouched either way.\n\n'
            'Worth knowing: only "replace all" over the whole clip can put layers\n'
            'back intact, so a layered clip is one you cannot mirror or blend.'
            if layered else 'This scene has no animation layers.')
        form.addRow('', self.flatten_checkBox)

        self.replace_checkBox = qtwidgets.QCheckBox('Overwrite if it already exists')
        form.addRow('', self.replace_checkBox)

        self.tags_lineEdit = qtwidgets.QLineEdit()
        self.tags_lineEdit.setPlaceholderText('comma, separated, tags')
        form.addRow('Tags:', self.tags_lineEdit)

        self.description_textEdit = qtwidgets.QPlainTextEdit()
        self.description_textEdit.setMaximumHeight(60)
        form.addRow('Notes:', self.description_textEdit)

        self.warning_label = qtwidgets.QLabel('')
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        self.buttons = qtwidgets.QDialogButtonBox(
            qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        self.buttons.button(qtwidgets.QDialogButtonBox.Ok).setText(
            'Capture Pose' if self.is_pose else 'Capture')
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if not self.is_pose:
            self.range_source_comboBox.currentIndexChanged.connect(self._on_range_source_changed)
            self.selected_checkBox.toggled.connect(self._on_range_source_changed)

    # --- Scene ------------------------------------------------------------- #

    def _fill_from_scene(self):
        """
        Fill in what the scene and the browser already decided.
        """

        self.rig_label.setText(self.rig_info['message'])

        target = self.target_character()
        self.folder_label.setText('{} / {}'.format(target or '?', self.folder_category or '?'))

        notes = []
        if not self.rig_info['ok']:
            notes.append('Select a flag on the rig you want to capture.')
        elif not self.rig_info['asset_id']:
            notes.append('This rig carries no asset id, so the clip would have no owner.')
        if not self.folder_category:
            notes.append('Pick a folder in the browser first - the clip is saved into the '
                         'folder that is selected.')
        elif (self.folder_character and target
                and self.folder_character.lower() != target.lower()):
            notes.append('The selected folder is under {}, but the rig is {}. Saving to '
                         '{} / {}.'.format(self.folder_character, target,
                                           target, self.folder_category))
        self.warning_label.setText('\n'.join(notes))
        self.buttons.button(qtwidgets.QDialogButtonBox.Ok).setEnabled(
            bool(self.rig_info['ok'] and self.rig_info['asset_id'] and self.folder_category))

        if self.is_pose:
            self.frame_spinBox.setValue(int(round(pm.currentTime(q=True))))
        else:
            self._on_range_source_changed()

    def target_character(self):
        """
        Whose clip this is.

        The rig answers, not the folder: the rig is the thing being captured, and
        an animator who selected a Frostwind flag while a different character's
        folder happened to be highlighted meant Frostwind.

        :return: The character's asset id.
        :rtype: str
        """

        return self.rig_info['asset_id'] or self.folder_character

    def _on_range_source_changed(self, *args):
        """
        Fill the frame range from keys or the timeline, and lock it unless custom.
        """

        choice = self.range_source_comboBox.currentText()
        editable = choice == 'Custom'
        self.start_spinBox.setReadOnly(not editable)
        self.end_spinBox.setReadOnly(not editable)
        if editable:
            return

        start = end = None
        if choice == 'Timeline':
            start, end = time_utils.get_visible_range()
        elif self.rig_info['ok']:
            try:
                flags = animlib_maya.keyed_flags(animlib_maya.target_flags(
                    self.rig_info['rig'], self.selected_checkBox.isChecked()))
                if flags:
                    start, end = time_utils.get_keyframe_range_from_nodes(flags)
            except Exception:
                logger.debug('Could not read a keyframe range off the rig.', exc_info=True)

        if start is None:
            start, end = time_utils.get_visible_range()
        self.start_spinBox.setValue(int(round(start)))
        self.end_spinBox.setValue(int(round(end)))

    # --- Result ------------------------------------------------------------ #

    def _restore_choices(self):
        """
        Open the way the dialog was last left.

        Only the choices that describe *how* to capture. The name, tags and notes
        belong to one clip and coming back pre-filled with the last one's is how
        a clip ends up mis-described. The frame range is filled from the scene
        for the same reason - it is a fact about what is in front of you, not a
        preference - but where it is read *from* is a preference, so that comes
        back.
        """

        if self.settings is None:
            return
        get = self.settings.value
        self.selected_checkBox.setChecked(to_bool(get('capture/selected_only', False)))
        self.preview_checkBox.setChecked(to_bool(get('capture/preview', True), True))
        self.replace_checkBox.setChecked(to_bool(get('capture/replace', False)))
        if self.flatten_checkBox.isEnabled():
            self.flatten_checkBox.setChecked(to_bool(get('capture/flatten_layers', False)))
        if self.is_pose:
            return
        index = to_int(get('capture/save_option', 0), 0)
        if 0 <= index < self.save_option_comboBox.count():
            self.save_option_comboBox.setCurrentIndex(index)
        index = to_int(get('capture/range_source', 0), 0)
        if 0 <= index < self.range_source_comboBox.count():
            self.range_source_comboBox.setCurrentIndex(index)
        if self.gif_checkBox.isEnabled():
            self.gif_checkBox.setChecked(to_bool(get('capture/gif', True), True))

    def _remember_choices(self):
        """
        Keep those choices for next time.

        Written on accept rather than on close, because a cancelled dialog is
        somebody changing their mind, not somebody setting a preference.
        """

        if self.settings is None:
            return
        put = self.settings.setValue
        put('capture/selected_only', self.selected_checkBox.isChecked())
        put('capture/preview', self.preview_checkBox.isChecked())
        put('capture/replace', self.replace_checkBox.isChecked())
        if self.flatten_checkBox.isEnabled():
            put('capture/flatten_layers', self.flatten_checkBox.isChecked())
        if self.is_pose:
            return
        put('capture/save_option', self.save_option_comboBox.currentIndex())
        put('capture/range_source', self.range_source_comboBox.currentIndex())
        if self.gif_checkBox.isEnabled():
            put('capture/gif', self.gif_checkBox.isChecked())

    def _on_accept(self):
        """
        Validate, then close.
        """

        if not self.name_lineEdit.text().strip():
            self.warning_label.setText('Give the clip a name.')
            return
        if not self.rig_info['ok']:
            self.warning_label.setText(self.rig_info['message'])
            return
        if not self.folder_category:
            self.warning_label.setText('Pick a folder in the browser first.')
            return
        if not self.is_pose and self.end_spinBox.value() < self.start_spinBox.value():
            self.warning_label.setText('The frame range ends before it starts.')
            return
        self._remember_choices()
        self.accept()

    def values(self):
        """
        What the animator chose.

        :return: Keyword arguments for :func:`animlib_maya.capture_clip` or
            :func:`animlib_maya.capture_pose`.
        :rtype: dict
        """

        tags = [t.strip() for t in self.tags_lineEdit.text().split(',') if t.strip()]
        common = {
            'name': self.name_lineEdit.text().strip(),
            'character': self.target_character() or None,
            'category': self.folder_category or 'Uncategorised',
            'namespace': self.rig_info['namespace'] or None,
            'tags': tags,
            'description': self.description_textEdit.toPlainText().strip(),
            'selected_only': self.selected_checkBox.isChecked(),
            'capture_preview': self.preview_checkBox.isChecked(),
            'replace': self.replace_checkBox.isChecked(),
            'flatten_layers': self.flatten_checkBox.isChecked(),
        }
        if self.is_pose:
            common['frame'] = float(self.frame_spinBox.value())
            return common

        saves = SAVE_CHOICES[self.save_option_comboBox.currentIndex()][0]
        common['export_curves'] = saves in ('both', 'curves')
        common['export_fbx'] = saves in ('both', 'fbx')
        common['capture_gif_preview'] = self.gif_checkBox.isChecked()
        common['clip_type'] = 'animation'
        common['frame_range'] = [float(self.start_spinBox.value()),
                                 float(self.end_spinBox.value())]
        return common


class NewFolderDialog(qtwidgets.QDialog):
    """
    Ask for a character and a folder name.
    """

    def __init__(self, character='', parent=None):
        """
        :param str character: Pre-selected character asset id.
        :param parent: Parent widget.
        """

        super().__init__(parent)
        self.setWindowTitle('New Folder')
        self.setMinimumWidth(360)

        layout = qtwidgets.QVBoxLayout(self)
        form = qtwidgets.QFormLayout()
        form.setFieldGrowthPolicy(qtwidgets.QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.character_comboBox = qtwidgets.QComboBox()
        self.character_comboBox.setEditable(True)
        known = animlib_api.list_characters()
        names = [r['character'] for r in (known['result'] or [])
                 if r['character'] != '(unassigned)']
        # A rig in the scene is the likeliest owner of a folder being made now,
        # so it goes to the top of the list.
        rig_info = describe_selected_rig()
        if rig_info['ok'] and rig_info['asset_id'] and rig_info['asset_id'] not in names:
            names.insert(0, rig_info['asset_id'])
        self.character_comboBox.addItems(sorted(set(names), key=lambda x: x.lower()))
        self.character_comboBox.setEditText(character or rig_info.get('asset_id') or '')
        form.addRow('Character:', self.character_comboBox)

        self.name_lineEdit = qtwidgets.QLineEdit()
        self.name_lineEdit.setPlaceholderText('Locomotion')
        form.addRow('Folder:', self.name_lineEdit)

        note = qtwidgets.QLabel('The folder is made on disk straight away. An empty one is fine '
                                '- it shows in the tree until you put something in it.')
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = qtwidgets.QDialogButtonBox(
            qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        """
        :return: ``(character, category)``.
        :rtype: tuple
        """

        return (self.character_comboBox.currentText().strip(),
                self.name_lineEdit.text().strip())


class ProjectDialog(qtwidgets.QDialog):
    """
    Ask for a project name and the folder its library lives in.
    """

    def __init__(self, parent=None):
        """
        :param parent: Parent widget.
        """

        super().__init__(parent)
        self.setWindowTitle('Add Library Project')
        self.setMinimumWidth(460)

        layout = qtwidgets.QVBoxLayout(self)
        form = qtwidgets.QFormLayout()
        form.setFieldGrowthPolicy(qtwidgets.QFormLayout.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        self.name_lineEdit = qtwidgets.QLineEdit()
        # The running project, so the hint matches what the user is in.
        self.name_lineEdit.setPlaceholderText(
            os.getenv('MCA_PROJECT_NAME') or 'Project')
        form.addRow('Name:', self.name_lineEdit)

        root_row = qtwidgets.QHBoxLayout()
        self.root_lineEdit = qtwidgets.QLineEdit()
        self.root_lineEdit.setPlaceholderText(r'E:\...\AnimationLibrary')
        root_row.addWidget(self.root_lineEdit, 1)
        self.browse_pushButton = qtwidgets.QPushButton('Browse...')
        root_row.addWidget(self.browse_pushButton)
        form.addRow('Library folder:', root_row)

        note = qtwidgets.QLabel('The folder does not have to exist yet - the first capture makes '
                                'it. Removing a project later only forgets the path; nothing on '
                                'disk is deleted.')
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = qtwidgets.QDialogButtonBox(
            qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.browse_pushButton.clicked.connect(self._on_browse)

    def _on_browse(self):
        """
        Pick the library folder.
        """

        start = self.root_lineEdit.text().strip() or os.path.expanduser('~')
        chosen = qtwidgets.QFileDialog.getExistingDirectory(self, 'Library folder', start)
        if chosen:
            self.root_lineEdit.setText(os.path.normpath(chosen))
            if not self.name_lineEdit.text().strip():
                self.name_lineEdit.setText(os.path.basename(os.path.normpath(chosen)))

    def values(self):
        """
        :return: ``(name, root)``.
        :rtype: tuple
        """

        return self.name_lineEdit.text().strip(), self.root_lineEdit.text().strip()
