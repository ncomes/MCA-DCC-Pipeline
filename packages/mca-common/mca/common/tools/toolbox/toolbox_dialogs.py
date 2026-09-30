"""
Dialogs for editing the MCA Toolbox in place: item settings, section settings and the UI builder.

The dialogs only collect values; the caller (``toolbox_widgets.ToolboxWidget``) applies them through the library so
version control and refreshes stay in one place. UI is built in code (no ``.ui`` files) so the same dialogs work in
every DCC, including Unreal where QUiLoader freezes the editor.
"""

# python imports
import keyword
import re

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore, qtgui

# MCA python imports
from mca.common import log
from mca.common.tools.toolbox import toolbox_items, toolbox_library, toolbox_model, toolbox_runner, toolbox_vcs

logger = log.MCA_LOGGER

__all__ = ['ColorButton', 'CodeEditor', 'ItemDialog', 'SectionDialog', 'FormBuilderDialog', 'exec_dialog']


def exec_dialog(dialog):
    """
    Run a dialog modally on PySide2 or PySide6.

    :param qtwidgets.QDialog dialog: The dialog.
    :return: True when accepted.
    :rtype: bool
    """

    runner = getattr(dialog, 'exec', None) or getattr(dialog, 'exec_')
    return runner() == qtwidgets.QDialog.Accepted


# --- Small widgets -----------------------------------------------------------------------------------------------

class ColorButton(qtwidgets.QPushButton):
    """
    Shows a color swatch; click to pick, the clear button next to it resets to "no color".
    """

    color_changed = qtcore.Signal(object)

    def __init__(self, color=None, parent=None):
        """
        :param str color: Starting hex color, or None.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        self._color = toolbox_model.normalize_color(color)
        self.setFixedHeight(24)
        self.setMinimumWidth(90)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self):
        """
        :return: The hex color, or None.
        :rtype: str|None
        """

        return self._color

    def set_color(self, color):
        """
        :param str|None color: Hex color, or None to clear.
        """

        self._color = toolbox_model.normalize_color(color)
        self._refresh()
        self.color_changed.emit(self._color)

    def _refresh(self):
        """
        Redraw the swatch.
        """

        if self._color:
            self.setText(self._color)
            self.setStyleSheet(toolbox_items.color_style('QPushButton', self._color))
        else:
            self.setText('No color')
            self.setStyleSheet('')

    def _pick(self):
        """
        Open the color picker.
        """

        start = qtgui.QColor(self._color) if self._color else qtgui.QColor('#4a6fa5')
        color = qtwidgets.QColorDialog.getColor(start, self, 'Pick a color')
        if color.isValid():
            self.set_color(color.name())

    def with_clear_button(self):
        """
        :return: A widget holding this button and a clear button.
        :rtype: qtwidgets.QWidget
        """

        container = qtwidgets.QWidget()
        row = qtwidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self, 1)
        clear = qtwidgets.QToolButton()
        clear.setText('Clear')
        clear.clicked.connect(lambda: self.set_color(None))
        row.addWidget(clear)
        return container


class PythonHighlighter(qtgui.QSyntaxHighlighter):
    """
    Minimal Python highlighting: keywords, strings, comments, numbers. Enough to make short tool scripts readable.
    """

    def __init__(self, document):
        """
        :param qtgui.QTextDocument document: The document to highlight.
        """

        super().__init__(document)

        def fmt(color, bold=False, italic=False):
            text_format = qtgui.QTextCharFormat()
            text_format.setForeground(qtgui.QColor(color))
            if bold:
                text_format.setFontWeight(qtgui.QFont.Bold)
            text_format.setFontItalic(italic)
            return text_format

        self._rules = [
            (re.compile(r'\b(' + '|'.join(keyword.kwlist) + r')\b'), fmt('#cc7832', bold=True)),
            (re.compile(r'\b(self|True|False|None)\b'), fmt('#9876aa')),
            (re.compile(r'\b[0-9]+(\.[0-9]+)?\b'), fmt('#6897bb')),
            (re.compile(r'\bdef\s+(\w+)|\bclass\s+(\w+)'), fmt('#ffc66d')),
            (re.compile(r'"[^"\\]*(\\.[^"\\]*)*"|\'[^\'\\]*(\\.[^\'\\]*)*\''), fmt('#6a8759')),
            (re.compile(r'#[^\n]*'), fmt('#808080', italic=True)),
        ]

    def highlightBlock(self, text):
        """
        :param str text: One line of the document.
        """

        for pattern, text_format in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), text_format)


class CodeEditor(qtwidgets.QPlainTextEdit):
    """
    Monospace Python editor: tab inserts four spaces, Enter keeps the current indent.
    """

    def __init__(self, text='', parent=None):
        """
        :param str text: Starting code.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        font = qtgui.QFontDatabase.systemFont(qtgui.QFontDatabase.FixedFont)
        font.setPointSize(9)
        self.setFont(font)
        self.setLineWrapMode(qtwidgets.QPlainTextEdit.NoWrap)
        self.setTabStopDistance(qtgui.QFontMetricsF(font).horizontalAdvance(' ') * 4)
        self.setPlainText(text)
        self._highlighter = PythonHighlighter(self.document())

    def keyPressEvent(self, event):
        """
        :param qtgui.QKeyEvent event: The key event.
        """

        if event.key() == qtcore.Qt.Key_Tab:
            self.insertPlainText('    ')
            return
        if event.key() in (qtcore.Qt.Key_Return, qtcore.Qt.Key_Enter):
            line = self.textCursor().block().text()
            indent = line[:len(line) - len(line.lstrip())]
            if line.rstrip().endswith(':'):
                indent += '    '
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(event)


def _icon_editor(value, library, shared, parent=None):
    """
    Icon setting editor: name field, live preview and a Browse button that imports new images into the toolbox icons
    folder (so the icon works for everyone, not just on this machine).

    :param str value: Current icon name.
    :param toolbox_library.ToolboxLibrary library: Resolves and imports icons. None disables preview and import.
    :param bool shared: Import into the shared (Perforce) icons folder instead of the local one.
    :param qtwidgets.QWidget parent: Parent for the file and message dialogs.
    :return: (widget, getter).
    :rtype: tuple
    """

    container = qtwidgets.QWidget()
    row = qtwidgets.QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    preview = qtwidgets.QLabel()
    preview.setFixedSize(24, 24)
    preview.setAlignment(qtcore.Qt.AlignCenter)
    line = qtwidgets.QLineEdit(str(value or ''))
    line.setPlaceholderText('No icon')
    browse = qtwidgets.QToolButton()
    browse.setText('Browse...')
    browse.setEnabled(library is not None)
    row.addWidget(preview)
    row.addWidget(line, 1)
    row.addWidget(browse)

    def update_preview(*args):
        text = line.text().strip()
        path = library.resolve_icon(text) if (library and text) else None
        if path:
            preview.setPixmap(qtgui.QIcon(path).pixmap(20, 20))
            preview.setToolTip(path)
        else:
            preview.clear()
            preview.setText('?' if text else '')
            preview.setToolTip('Icon not found.' if text else '')

    def pick():
        folders = library.icon_folders()
        start = folders[0] if folders else ''
        path = qtwidgets.QFileDialog.getOpenFileName(
            parent, 'Choose icon', start,
            'Images (' + ' '.join(f'*{x}' for x in toolbox_library.ICON_EXTENSIONS) + ')')[0]
        if not path:
            return
        try:
            line.setText(library.import_icon(path, shared=shared))
        except (ValueError, OSError, toolbox_vcs.ToolboxWriteError) as exc:
            qtwidgets.QMessageBox.warning(parent, 'Toolbox', f'Could not use that icon:\n{exc}')

    line.textChanged.connect(update_preview)
    browse.clicked.connect(pick)
    update_preview()
    return container, lambda: line.text().strip()


def _settings_editor(field, value, library=None, shared=True, parent=None):
    """
    Build the editor for one :class:`toolbox_items.SettingField`.

    :param toolbox_items.SettingField field: The field.
    :param object value: Current value.
    :param toolbox_library.ToolboxLibrary library: Needed by ``'icon'`` fields.
    :param bool shared: ``'icon'`` fields import into the shared icons folder.
    :param qtwidgets.QWidget parent: Parent for dialogs the editor opens.
    :return: (widget, getter).
    :rtype: tuple
    """

    value = field.default if value is None else value
    if field.kind == 'icon':
        editor, getter = _icon_editor(value, library, shared, parent)
    elif field.kind == 'bool':
        editor = qtwidgets.QCheckBox()
        editor.setChecked(bool(value))
        getter = editor.isChecked
    elif field.kind == 'int':
        editor = qtwidgets.QSpinBox()
        editor.setRange(-1000000, 1000000)
        editor.setValue(int(value or 0))
        getter = editor.value
    elif field.kind == 'float':
        editor = qtwidgets.QDoubleSpinBox()
        editor.setDecimals(4)
        editor.setRange(-1000000.0, 1000000.0)
        editor.setValue(float(value or 0.0))
        getter = editor.value
    elif field.kind == 'choice':
        editor = qtwidgets.QComboBox()
        editor.addItems(field.options)
        if value in field.options:
            editor.setCurrentIndex(field.options.index(value))
        getter = editor.currentText
    elif field.kind == 'lines':
        editor = qtwidgets.QPlainTextEdit('\n'.join(str(x) for x in (value or [])))
        editor.setFixedHeight(70)
        getter = lambda: [x.strip() for x in editor.toPlainText().splitlines() if x.strip()]
    else:
        editor = qtwidgets.QLineEdit(str(value or ''))
        getter = editor.text
    editor.setToolTip(field.tooltip)
    return editor, getter


# --- Item dialog -------------------------------------------------------------------------------------------------

class ItemDialog(qtwidgets.QDialog):
    """
    Add or edit an item: name, type, tooltip, color, command and type settings.

    After :func:`exec_dialog` returns True, read :meth:`result_data`.
    """

    def __init__(self, item=None, color=None, shared_toolbox=True, run_callback=None, library=None,
                 shared_section=True, parent=None):
        """
        :param toolbox_model.ToolboxItem item: Item to edit. None creates a new button.
        :param str color: The item's current color in this toolbox.
        :param bool shared_toolbox: Offer "only for me" colors (pointless in a personal toolbox).
        :param callable run_callback: ``run_callback(item, variables)`` used by the Test Run button.
        :param toolbox_library.ToolboxLibrary library: Used to preview and import icons.
        :param bool shared_section: The item lives in a shared section, so imported icons go to the shared folder.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        self.is_new = item is None
        self.item = item.copy() if item else toolbox_model.ToolboxItem(item_type='button')
        self._run_callback = run_callback
        self._library = library
        self._shared_section = shared_section
        self._settings_getters = {}
        self._form_fields = list(self.item.settings.get('fields') or [])
        self.setWindowTitle('Add Toolbox Item' if self.is_new else f'Edit "{self.item.name}"')
        self.resize(620, 640)

        layout = qtwidgets.QVBoxLayout(self)
        form = qtwidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = qtwidgets.QLineEdit(self.item.name)
        self.name_edit.setPlaceholderText('Display name')
        form.addRow('Name', self.name_edit)

        self.type_combo = qtwidgets.QComboBox()
        for type_class in toolbox_items.item_types():
            self.type_combo.addItem(type_class.LABEL, type_class.TYPE)
        index = self.type_combo.findData(self.item.type)
        self.type_combo.setCurrentIndex(max(index, 0))
        form.addRow('Type', self.type_combo)
        self.type_help = qtwidgets.QLabel()
        self.type_help.setWordWrap(True)
        self.type_help.setStyleSheet('color: #9a9a9a;')
        form.addRow('', self.type_help)

        self.tooltip_edit = qtwidgets.QLineEdit(self.item.tooltip)
        form.addRow('Tooltip', self.tooltip_edit)
        self.tags_edit = qtwidgets.QLineEdit(', '.join(self.item.tags))
        self.tags_edit.setPlaceholderText('Extra words for the filter, comma separated')
        form.addRow('Tags', self.tags_edit)

        self.color_button = ColorButton(color)
        form.addRow('Color', self.color_button.with_clear_button())
        self.personal_check = qtwidgets.QCheckBox('Only for me (not checked in)')
        self.personal_check.setVisible(shared_toolbox)
        form.addRow('', self.personal_check)

        # Type specific settings are rebuilt whenever the type changes.
        self.settings_group = qtwidgets.QGroupBox('Settings')
        self.settings_layout = qtwidgets.QFormLayout(self.settings_group)
        layout.addWidget(self.settings_group)

        self.command_group = qtwidgets.QGroupBox('Command')
        command_layout = qtwidgets.QVBoxLayout(self.command_group)
        kind_row = qtwidgets.QHBoxLayout()
        self.python_radio = qtwidgets.QRadioButton('Python code')
        self.callable_radio = qtwidgets.QRadioButton('Function')
        self.callable_radio.setToolTip('package.module:function - preferred for tools that ship with the pipeline.')
        kind_row.addWidget(self.python_radio)
        kind_row.addWidget(self.callable_radio)
        kind_row.addStretch()
        self.test_button = qtwidgets.QPushButton('Test Run')
        self.test_button.setVisible(run_callback is not None)
        kind_row.addWidget(self.test_button)
        command_layout.addLayout(kind_row)
        self.variables_label = qtwidgets.QLabel()
        self.variables_label.setStyleSheet('color: #9a9a9a;')
        command_layout.addWidget(self.variables_label)
        self.code_edit = CodeEditor(self.item.command.get('code', ''))
        command_layout.addWidget(self.code_edit, 1)
        self.target_edit = qtwidgets.QLineEdit(self.item.command.get('target', ''))
        self.target_edit.setPlaceholderText('mca.mya.tools.summoner.summoner:SummonerUI')
        command_layout.addWidget(self.target_edit)
        layout.addWidget(self.command_group, 1)

        buttons = qtwidgets.QDialogButtonBox(qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        is_callable = self.item.command.get('kind') == toolbox_model.COMMAND_CALLABLE
        self.callable_radio.setChecked(is_callable)
        self.python_radio.setChecked(not is_callable)
        self.python_radio.toggled.connect(self._update_command_kind)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.test_button.clicked.connect(self._test_run)
        self._type_changed(initial=True)
        self._update_command_kind()

    def _type_class(self):
        """
        :return: The selected item type class.
        :rtype: type
        """

        return toolbox_items.get_item_type(self.type_combo.currentData())

    def _type_changed(self, *args, initial=False):
        """
        Rebuild the settings form and show/hide the command editor for the selected type.

        :param bool initial: True on first build, so the item's existing code is kept.
        """

        type_class = self._type_class()
        self.type_help.setText(type_class.DESCRIPTION)
        self.command_group.setVisible(type_class.HAS_COMMAND)
        self.variables_label.setText(type_class.VARIABLES_HELP)
        self.variables_label.setVisible(bool(type_class.VARIABLES_HELP))
        if not initial and type_class.DEFAULT_CODE and not self.code_edit.toPlainText().strip():
            self.code_edit.setPlainText(type_class.DEFAULT_CODE)
        elif initial and self.is_new and not self.code_edit.toPlainText().strip():
            self.code_edit.setPlainText(type_class.DEFAULT_CODE)

        while self.settings_layout.rowCount():
            self.settings_layout.removeRow(0)
        self._settings_getters = {}
        for field in type_class.SETTINGS:
            editor, getter = _settings_editor(field, self.item.settings.get(field.key), library=self._library,
                                              shared=self._shared_section, parent=self)
            self.settings_layout.addRow(field.label, editor)
            self._settings_getters[field.key] = getter
        if type_class.TYPE == 'form':
            builder_button = qtwidgets.QPushButton('Open UI Builder...')
            builder_button.clicked.connect(self._open_builder)
            self.fields_summary = qtwidgets.QLabel()
            self.settings_layout.addRow(builder_button, self.fields_summary)
            self._update_fields_summary()
        self.settings_group.setVisible(self.settings_layout.rowCount() > 0)

    def _update_command_kind(self):
        """
        Show the code editor or the function field.
        """

        python = self.python_radio.isChecked()
        self.code_edit.setVisible(python)
        self.target_edit.setVisible(not python)

    def _update_fields_summary(self):
        """
        Show how many fields the form has.
        """

        names = [x.get('label') or x.get('key') for x in self._form_fields]
        self.fields_summary.setText(f'{len(names)} field(s): {", ".join(names)}' if names else 'No fields yet')

    def _open_builder(self):
        """
        Edit the form fields in the UI builder.
        """

        dialog = FormBuilderDialog(self._form_fields, title=self.name_edit.text(), parent=self)
        if exec_dialog(dialog):
            self._form_fields = dialog.fields()
            self._update_fields_summary()

    def _command(self):
        """
        :return: The command dict from the editor.
        :rtype: dict
        """

        if self.callable_radio.isChecked():
            return {'kind': toolbox_model.COMMAND_CALLABLE, 'target': self.target_edit.text().strip()}
        return {'kind': toolbox_model.COMMAND_PYTHON, 'code': self.code_edit.toPlainText()}

    def _build_item(self):
        """
        :return: A copy of the item with the dialog's values applied.
        :rtype: toolbox_model.ToolboxItem
        """

        item = self.item.copy()
        item.name = self.name_edit.text().strip()
        item.type = self.type_combo.currentData()
        item.tooltip = self.tooltip_edit.text().strip()
        item.tags = [x.strip() for x in self.tags_edit.text().split(',') if x.strip()]
        type_class = self._type_class()
        item.command = self._command() if type_class.HAS_COMMAND else {'kind': toolbox_model.COMMAND_PYTHON,
                                                                        'code': ''}
        # Settings left at their default are not stored, so section files only list what was actually changed.
        defaults = {field.key: field.default for field in type_class.SETTINGS}
        settings = {key: getter() for key, getter in self._settings_getters.items()}
        settings = {key: value for key, value in settings.items() if key not in defaults or value != defaults[key]}
        if item.type == 'form':
            settings['fields'] = self._form_fields
        item.settings = settings
        return item

    def _test_run(self):
        """
        Run the command as it is in the editor, without saving.
        """

        item = self._build_item()
        variables = {}
        if item.type == 'form':
            variables = {'values': toolbox_items.FormWidget(item.settings.get('fields')).values()}
        elif item.type in ('checkbox', 'slider', 'dropdown'):
            variables = {'value': item.settings.get('default')}
        self._run_callback(item, variables)

    def _accept(self):
        """
        Validate, then close.
        """

        item = self._build_item()
        if not item.name and item.type != 'separator':
            qtwidgets.QMessageBox.warning(self, 'Toolbox', 'Please give the item a name.')
            return
        type_class = self._type_class()
        if type_class.HAS_COMMAND:
            problems = toolbox_runner.check_command(item.command)
            if problems and item.command.get('kind') == toolbox_model.COMMAND_PYTHON and \
                    any(x.startswith('syntax error') for x in problems):
                qtwidgets.QMessageBox.warning(self, 'Toolbox', 'The code has a syntax error:\n' + problems[0])
                return
            if problems:
                answer = qtwidgets.QMessageBox.question(
                    self, 'Toolbox', 'The command looks broken:\n\n' + '\n'.join(problems) + '\n\nSave anyway?')
                if answer != qtwidgets.QMessageBox.Yes:
                    return
        self._result = item
        self.accept()

    def result_data(self):
        """
        :return: ``{'item': ToolboxItem, 'color': hex|None, 'personal': bool}``.
        :rtype: dict
        """

        return {'item': self._result, 'color': self.color_button.color(),
                'personal': self.personal_check.isVisible() and self.personal_check.isChecked()}


# --- Section dialog ----------------------------------------------------------------------------------------------

class SectionDialog(qtwidgets.QDialog):
    """
    Add or edit a section: name and this toolbox's background and header colors.
    """

    def __init__(self, name='', background=None, header=None, shared_toolbox=True, title='Section', parent=None):
        """
        :param str name: Current section name.
        :param str background: Current background color.
        :param str header: Current header color.
        :param bool shared_toolbox: Offer "only for me" colors.
        :param str title: Window title.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        layout = qtwidgets.QVBoxLayout(self)
        form = qtwidgets.QFormLayout()
        layout.addLayout(form)
        self.name_edit = qtwidgets.QLineEdit(name)
        form.addRow('Name', self.name_edit)
        self.background_button = ColorButton(background)
        form.addRow('Background', self.background_button.with_clear_button())
        self.header_button = ColorButton(header)
        form.addRow('Header', self.header_button.with_clear_button())
        self.personal_check = qtwidgets.QCheckBox('Colors only for me (not checked in)')
        self.personal_check.setVisible(shared_toolbox)
        form.addRow('', self.personal_check)
        note = qtwidgets.QLabel('The name is the same in every toolbox. Colors only apply to this toolbox.')
        note.setWordWrap(True)
        note.setStyleSheet('color: #9a9a9a;')
        layout.addWidget(note)
        buttons = qtwidgets.QDialogButtonBox(qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        """
        Validate, then close.
        """

        if not self.name_edit.text().strip():
            qtwidgets.QMessageBox.warning(self, 'Toolbox', 'Please give the section a name.')
            return
        self.accept()

    def result_data(self):
        """
        :return: ``{'name', 'background', 'header', 'personal'}``.
        :rtype: dict
        """

        return {'name': self.name_edit.text().strip(), 'background': self.background_button.color(),
                'header': self.header_button.color(),
                'personal': self.personal_check.isVisible() and self.personal_check.isChecked()}


# --- UI builder --------------------------------------------------------------------------------------------------

class FormBuilderDialog(qtwidgets.QDialog):
    """
    The toolbox UI builder: add, order and configure form fields with a live preview.
    """

    def __init__(self, fields=None, title='', parent=None):
        """
        :param list[dict] fields: Existing field definitions.
        :param str title: Form title for the preview.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        self.setWindowTitle('Toolbox UI Builder')
        self.resize(760, 480)
        self._fields = [dict(x) for x in fields or []]
        self._title = title
        self._loading = False

        layout = qtwidgets.QHBoxLayout(self)

        # Left: field list with add/remove/move.
        left = qtwidgets.QVBoxLayout()
        layout.addLayout(left, 1)
        self.field_list = qtwidgets.QListWidget()
        left.addWidget(self.field_list, 1)
        row = qtwidgets.QHBoxLayout()
        self.add_button = qtwidgets.QToolButton()
        self.add_button.setText('Add Field')
        self.add_button.setPopupMode(qtwidgets.QToolButton.InstantPopup)
        add_menu = qtwidgets.QMenu(self.add_button)
        for kind, label in toolbox_items.FORM_FIELD_KINDS.items():
            add_menu.addAction(label, lambda kind=kind: self._add_field(kind))
        self.add_button.setMenu(add_menu)
        row.addWidget(self.add_button)
        for text, callback in (('Up', lambda: self._move(-1)), ('Down', lambda: self._move(1)),
                               ('Remove', self._remove)):
            button = qtwidgets.QToolButton()
            button.setText(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        left.addLayout(row)

        # Middle: editor for the selected field.
        self.editor_group = qtwidgets.QGroupBox('Field')
        editor_column = qtwidgets.QVBoxLayout(self.editor_group)
        editor = qtwidgets.QFormLayout()
        editor_column.addLayout(editor)
        # Keep the rows packed at the top instead of spread over the group's height.
        editor_column.addStretch(1)
        self.kind_label = qtwidgets.QLabel()
        editor.addRow('Kind', self.kind_label)
        self.label_edit = qtwidgets.QLineEdit()
        editor.addRow('Label', self.label_edit)
        self.key_edit = qtwidgets.QLineEdit()
        self.key_edit.setToolTip('Name used in code: values["key"]')
        editor.addRow('Key', self.key_edit)
        self.default_edit = qtwidgets.QLineEdit()
        editor.addRow('Default', self.default_edit)
        self.min_spin = qtwidgets.QDoubleSpinBox()
        self.max_spin = qtwidgets.QDoubleSpinBox()
        for spin in (self.min_spin, self.max_spin):
            spin.setRange(-1000000.0, 1000000.0)
            spin.setDecimals(3)
        editor.addRow('Minimum', self.min_spin)
        editor.addRow('Maximum', self.max_spin)
        self.decimals_spin = qtwidgets.QSpinBox()
        self.decimals_spin.setRange(0, 6)
        editor.addRow('Decimals', self.decimals_spin)
        self.options_edit = qtwidgets.QPlainTextEdit()
        self.options_edit.setFixedHeight(70)
        editor.addRow('Options (one per line)', self.options_edit)
        self.tooltip_edit = qtwidgets.QLineEdit()
        editor.addRow('Tooltip', self.tooltip_edit)
        layout.addWidget(self.editor_group, 1)

        # Right: live preview and OK/Cancel.
        right = qtwidgets.QVBoxLayout()
        layout.addLayout(right, 1)
        preview_group = qtwidgets.QGroupBox('Preview')
        self.preview_layout = qtwidgets.QVBoxLayout(preview_group)
        right.addWidget(preview_group, 1)
        buttons = qtwidgets.QDialogButtonBox(qtwidgets.QDialogButtonBox.Ok | qtwidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)

        self.field_list.currentRowChanged.connect(self._load_field)
        for widget in (self.label_edit, self.key_edit, self.default_edit, self.tooltip_edit):
            widget.textEdited.connect(self._store_field)
        for spin in (self.min_spin, self.max_spin, self.decimals_spin):
            spin.valueChanged.connect(self._store_field)
        self.options_edit.textChanged.connect(self._store_field)

        self._refresh_list()
        self.field_list.setCurrentRow(0 if self._fields else -1)
        self._load_field(self.field_list.currentRow())

    def fields(self):
        """
        :return: The edited field definitions.
        :rtype: list[dict]
        """

        return [dict(x) for x in self._fields]

    def _refresh_list(self):
        """
        Redraw the field list and the preview, keeping the selection.
        """

        row = self.field_list.currentRow()
        self.field_list.blockSignals(True)
        self.field_list.clear()
        for field in self._fields:
            kind_label = toolbox_items.FORM_FIELD_KINDS.get(field.get('kind'), field.get('kind'))
            self.field_list.addItem(f'{field.get("label") or field.get("key")}  [{kind_label}]')
        self.field_list.setCurrentRow(min(row, len(self._fields) - 1))
        self.field_list.blockSignals(False)
        self._refresh_preview()

    def _refresh_preview(self):
        """
        Rebuild the preview form from the current fields.
        """

        while self.preview_layout.count():
            widget = self.preview_layout.takeAt(0).widget()
            if widget:
                # Hide right away: deleteLater only runs on a later event loop pass, and the old form would
                # otherwise paint underneath the new one until then.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if self._title:
            title = qtwidgets.QLabel(self._title)
            title.setStyleSheet('font-weight: bold;')
            self.preview_layout.addWidget(title)
        self.preview_layout.addWidget(toolbox_items.FormWidget(self._fields))
        self.preview_layout.addStretch()

    def _add_field(self, kind):
        """
        :param str kind: A :data:`toolbox_items.FORM_FIELD_KINDS` key.
        """

        existing = set(x.get('key') for x in self._fields)
        index = 1
        while f'{kind}{index}' in existing:
            index += 1
        field = {'kind': kind, 'key': f'{kind}{index}', 'label': toolbox_items.FORM_FIELD_KINDS[kind]}
        if kind in ('slider', 'float'):
            field.update({'minimum': 0.0, 'maximum': 1.0, 'decimals': 2})
        elif kind == 'int':
            field.update({'minimum': 0, 'maximum': 100})
        elif kind == 'dropdown':
            field['options'] = ['Option A', 'Option B']
        self._fields.append(field)
        self._refresh_list()
        self.field_list.setCurrentRow(len(self._fields) - 1)

    def _remove(self):
        """
        Remove the selected field.
        """

        row = self.field_list.currentRow()
        if 0 <= row < len(self._fields):
            self._fields.pop(row)
            self._refresh_list()
            self._load_field(self.field_list.currentRow())

    def _move(self, offset):
        """
        :param int offset: -1 moves the selected field up, 1 down.
        """

        row = self.field_list.currentRow()
        target = row + offset
        if 0 <= row < len(self._fields) and 0 <= target < len(self._fields):
            self._fields[row], self._fields[target] = self._fields[target], self._fields[row]
            self.field_list.setCurrentRow(target)
            self._refresh_list()

    def _load_field(self, row):
        """
        Show the selected field in the editor, enabling only the options that apply to its kind.

        :param int row: Selected row.
        """

        valid = 0 <= row < len(self._fields)
        self.editor_group.setEnabled(valid)
        if not valid:
            return
        field = self._fields[row]
        kind = field.get('kind', 'text')
        self._loading = True
        self.kind_label.setText(toolbox_items.FORM_FIELD_KINDS.get(kind, kind))
        self.label_edit.setText(str(field.get('label', '')))
        self.key_edit.setText(str(field.get('key', '')))
        self.default_edit.setText('' if field.get('default') is None else str(field.get('default')))
        self.min_spin.setValue(float(field.get('minimum', 0.0)))
        self.max_spin.setValue(float(field.get('maximum', 1.0)))
        self.decimals_spin.setValue(int(field.get('decimals', 2)))
        self.options_edit.setPlainText('\n'.join(str(x) for x in field.get('options') or []))
        self.tooltip_edit.setText(str(field.get('tooltip', '')))
        numeric = kind in ('int', 'float', 'slider')
        for widget in (self.min_spin, self.max_spin):
            widget.setEnabled(numeric)
        self.decimals_spin.setEnabled(kind in ('float', 'slider'))
        self.options_edit.setEnabled(kind == 'dropdown')
        self.default_edit.setEnabled(kind != 'label')
        self.key_edit.setEnabled(kind != 'label')
        self._loading = False

    def _store_field(self, *args):
        """
        Copy the editor values into the selected field and refresh the preview.
        """

        row = self.field_list.currentRow()
        if self._loading or not 0 <= row < len(self._fields):
            return
        field = self._fields[row]
        kind = field.get('kind', 'text')
        field['label'] = self.label_edit.text()
        field['key'] = re.sub(r'\W+', '_', self.key_edit.text().strip()) or field.get('key')
        field['tooltip'] = self.tooltip_edit.text()
        default_text = self.default_edit.text()
        field['default'] = self._convert_default(kind, default_text)
        if kind in ('int', 'float', 'slider'):
            field['minimum'] = self.min_spin.value()
            field['maximum'] = self.max_spin.value()
        if kind in ('float', 'slider'):
            field['decimals'] = self.decimals_spin.value()
        if kind == 'dropdown':
            field['options'] = [x.strip() for x in self.options_edit.toPlainText().splitlines() if x.strip()]
        self.field_list.item(row).setText(
            f'{field.get("label") or field.get("key")}  [{toolbox_items.FORM_FIELD_KINDS.get(kind, kind)}]')
        self._refresh_preview()

    @staticmethod
    def _convert_default(kind, text):
        """
        :param str kind: Field kind.
        :param str text: Default as typed.
        :return: The default converted to the field's value type (None when empty or invalid).
        :rtype: object
        """

        if text == '':
            return None
        try:
            if kind == 'int':
                return int(float(text))
            if kind in ('float', 'slider'):
                return float(text)
        except ValueError:
            return None
        if kind == 'checkbox':
            return text.strip().lower() in ('1', 'true', 'yes', 'on', 'checked')
        return text
