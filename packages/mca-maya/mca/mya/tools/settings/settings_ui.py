"""
MCA Maya settings.

Maya's own settings, and a read-only view of what the framework resolved this session.

Built in code rather than from a ``.ui`` file on purpose: the form is a list of fields
generated from :data:`settings_model.MAYA_FIELDS`, so a ``.ui`` would have to be edited in
lockstep with that list, and a window whose widgets are described in two places is a window
where they disagree.

Project paths are not editable here. They are cross-DCC - MotionBuilder and Unreal read the
same preferences - so the launcher owns them, and Maya showing an editable copy would be two
writers on one file.
"""

# python imports

# software specific imports

# MCA python imports
from mca.common import log
from mca.common.pyqt import common_windows
from mca.common.pyqt.pygui import qtwidgets, qtcore
from mca.common.resources import resources
from mca.mya.tools.settings import settings_model


logger = log.MCA_LOGGER


class MCASettingsUI(common_windows.MCAMainWindow):
    """The settings window."""

    VERSION = '1.0.0'
    INITIAL_WIDTH = 560
    INITIAL_HEIGHT = 620

    def __init__(self, parent=None):
        super().__init__(title='MCA Settings',
                         version=self.VERSION,
                         parent=parent)

        self.options = settings_model.load_options()
        self.editors = {}

        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(8)

        self._build_maya_group()
        self._build_resolved_group()
        self._build_buttons()
        self.main_layout.addStretch(1)

        self._load_into_fields()

    # ------------------------------------------------------------------ #
    # Building
    # ------------------------------------------------------------------ #
    def _build_maya_group(self):
        """The editable Maya options, one row per entry in MAYA_FIELDS."""

        box = qtwidgets.QGroupBox('Maya')
        form = qtwidgets.QFormLayout(box)

        for attribute, label, kind in settings_model.MAYA_FIELDS:
            editor = self._make_editor(kind)
            self.editors[attribute] = editor
            if attribute in settings_model.RESTART_REQUIRED:
                editor.setToolTip('Read while Maya starts, so this one takes effect next '
                                  'time Maya opens.')
                label = '{}  *'.format(label)
            form.addRow(label, editor)

        note = qtwidgets.QLabel('*  takes effect next time Maya starts')
        note.setStyleSheet('color: palette(mid);')
        form.addRow('', note)
        self.main_layout.addWidget(box)

    @staticmethod
    def _make_editor(kind):
        """
        :param kind: 'bool', 'int', or a tuple of choices.
        :return: The widget for editing that.
        """

        if kind == 'bool':
            return qtwidgets.QCheckBox()
        if kind == 'int':
            spin = qtwidgets.QSpinBox()
            spin.setRange(-100000, 100000)
            return spin
        combo = qtwidgets.QComboBox()
        combo.addItems(list(kind))
        return combo

    def _build_resolved_group(self):
        """
        What the framework resolved, read-only.

        This is the panel that answers "what did it actually pick?" - the question that
        otherwise means reading a log, or asking in a script editor, and that several hours
        went into answering by hand.
        """

        box = qtwidgets.QGroupBox('Resolved this session (read-only)')
        layout = qtwidgets.QVBoxLayout(box)

        table = qtwidgets.QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Setting', 'Value'])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(qtwidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(qtwidgets.QAbstractItemView.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)

        for label, value in settings_model.resolved_values():
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, qtwidgets.QTableWidgetItem(str(label)))
            shown = str(value) if value else '(not set)'
            item = qtwidgets.QTableWidgetItem(shown)
            item.setToolTip(shown)
            if not value:
                item.setForeground(qtcore.Qt.GlobalColor.darkYellow)
            table.setItem(row, 1, item)

        table.resizeColumnsToContents()
        layout.addWidget(table)

        note = qtwidgets.QLabel(
            'These come from the project preferences the launcher writes. Change them in '
            'the launcher\'s project setup - they are shared with the other DCCs.')
        note.setWordWrap(True)
        note.setStyleSheet('color: palette(mid);')
        layout.addWidget(note)

        self.main_layout.addWidget(box)

    def _build_buttons(self):
        """Save, save-and-apply, and close."""

        row = qtwidgets.QHBoxLayout()
        self.status = qtwidgets.QLabel('')
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)

        self.save_button = qtwidgets.QPushButton('Save')
        self.save_button.setToolTip('Write the settings out without changing this Maya.')
        self.save_button.clicked.connect(lambda: self._save(apply_now=False))
        row.addWidget(self.save_button)

        self.apply_button = qtwidgets.QPushButton('Save and Apply')
        self.apply_button.setToolTip('Write them out and put them into this Maya now.')
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(lambda: self._save(apply_now=True))
        row.addWidget(self.apply_button)

        close = qtwidgets.QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(close)

        self.main_layout.addLayout(row)

    # ------------------------------------------------------------------ #
    # Values
    # ------------------------------------------------------------------ #
    def _load_into_fields(self):
        """Put the saved options into the widgets."""

        for attribute, _, kind in settings_model.MAYA_FIELDS:
            editor = self.editors[attribute]
            value = getattr(self.options, attribute, None)
            if kind == 'bool':
                editor.setChecked(bool(value))
            elif kind == 'int':
                try:
                    editor.setValue(int(value))
                except (TypeError, ValueError):
                    logger.debug('%s is %r, which is not a number; left at its default.',
                                 attribute, value)
            else:
                index = editor.findText(str(value or ''))
                if index >= 0:
                    editor.setCurrentIndex(index)

    def _read_from_fields(self):
        """Put the widgets back onto the options object."""

        for attribute, _, kind in settings_model.MAYA_FIELDS:
            editor = self.editors[attribute]
            if kind == 'bool':
                setattr(self.options, attribute, editor.isChecked())
            elif kind == 'int':
                setattr(self.options, attribute, editor.value())
            else:
                setattr(self.options, attribute, editor.currentText())

    def _save(self, apply_now=True):
        """
        :param bool apply_now: Also put them into this Maya.
        """

        self._read_from_fields()
        message = settings_model.save_options(self.options, apply_now=apply_now)
        self.status.setText(message)
        logger.info(message)


def show_settings(parent=None):
    """
    Open the settings window.

    :param parent: What to parent it to.
    :return: The window.
    :rtype: MCASettingsUI
    """

    window = MCASettingsUI(parent=parent)
    window.show()
    return window
