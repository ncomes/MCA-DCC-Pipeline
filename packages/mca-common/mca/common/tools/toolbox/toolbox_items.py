"""
Item types for the MCA Toolbox: how each kind of item is drawn and what settings it has.

Each type is one :class:`ItemType` subclass registered with :func:`register_item_type`. Adding a new widget to the
toolbox means writing one class here (or anywhere, then registering it): the item dialog builds its settings form from
``SETTINGS`` and the toolbox calls ``create_widget`` to draw it.

A type's widget talks to its toolbox through a small *host* interface (implemented by
``toolbox_widgets.ToolboxWidget``):

- ``host.run_item(item, variables=None)``: run the item's command.
- ``host.build_panel(item)``: return the embedded widget of a panel item.
- ``host.library``: the :class:`toolbox_library.ToolboxLibrary`.

This module also holds :class:`FormWidget`, the runtime half of the UI builder: it turns a list of field
definitions into a form and reports the entered values.
"""

# python imports
import os

# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore, qtgui

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

__all__ = ['SettingField', 'ItemType', 'register_item_type', 'get_item_type', 'item_types', 'FormWidget',
           'FORM_FIELD_KINDS', 'text_color_for', 'adjust_color', 'color_style']

# Qt property set on item widgets that should take the full width of a section instead of one grid cell.
FULL_WIDTH_PROPERTY = 'toolbox_full_width'
# Pixel size of button icons; fits the 26 px button height.
ICON_SIZE = 18

_ITEM_TYPES = {}


# --- Color helpers -----------------------------------------------------------------------------------------------

def text_color_for(background):
    """
    Pick black or white text for a background so labels stay readable on any color the user picks.

    :param str background: Hex background color.
    :return: ``'#101010'`` or ``'#f5f5f5'``.
    :rtype: str
    """

    color = qtgui.QColor(background)
    # Relative luminance (ITU-R BT.601 weights) is enough to decide dark vs light text.
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return '#101010' if luminance > 150 else '#f5f5f5'


def adjust_color(hex_color, factor):
    """
    :param str hex_color: Hex color.
    :param int factor: Qt lighter/darker factor. Above 100 lightens, below 100 darkens.
    :return: The adjusted hex color.
    :rtype: str
    """

    color = qtgui.QColor(hex_color)
    color = color.lighter(factor) if factor >= 100 else color.darker(int(10000 / max(factor, 1)))
    return color.name()


def color_style(widget_class, color, object_name=None, radius=3):
    """
    Build a stylesheet that colors one widget with hover/pressed states and readable text.

    :param str widget_class: Qt class name used as the selector, e.g. ``'QPushButton'``.
    :param str color: Hex background color.
    :param str object_name: Limit the rule to the widget with this object name, so children keep their own style.
    :param int radius: Corner radius in pixels.
    :return: Stylesheet text.
    :rtype: str
    """

    selector = f'{widget_class}#{object_name}' if object_name else widget_class
    text = text_color_for(color)
    return (f'{selector} {{ background-color: {color}; color: {text}; border: 1px solid {adjust_color(color, 70)};'
            f' border-radius: {radius}px; padding: 3px 6px; }}\n'
            f'{selector}:hover {{ background-color: {adjust_color(color, 120)}; }}\n'
            f'{selector}:pressed {{ background-color: {adjust_color(color, 80)}; }}\n')


# --- Settings schema ---------------------------------------------------------------------------------------------

class SettingField:
    """
    One entry in an item type's settings form.
    """

    def __init__(self, key, label, kind='str', default=None, options=None, tooltip=''):
        """
        :param str key: Key in ``item.settings``.
        :param str label: Label shown in the dialog.
        :param str kind: ``'str'``, ``'int'``, ``'float'``, ``'bool'``, ``'choice'``, ``'lines'`` (a list of strings,
            one per line) or ``'icon'`` (an icon name, edited with a preview and browse button).
        :param object default: Value used when the item has none.
        :param list[str] options: Choices for ``'choice'``.
        :param str tooltip: Help text.
        """

        self.key = key
        self.label = label
        self.kind = kind
        self.default = default
        self.options = options or []
        self.tooltip = tooltip


# --- Registry ----------------------------------------------------------------------------------------------------

def register_item_type(item_type_class):
    """
    Register an item type. Also usable as a class decorator.

    :param type item_type_class: An :class:`ItemType` subclass with a unique ``TYPE``.
    :return: The class, unchanged.
    :rtype: type
    """

    _ITEM_TYPES[item_type_class.TYPE] = item_type_class
    return item_type_class


def get_item_type(type_name):
    """
    :param str type_name: Registered type name.
    :return: The type class, or :class:`UnknownType` for types this version does not know.
    :rtype: type
    """

    return _ITEM_TYPES.get(type_name, UnknownType)


def item_types(user_creatable=True):
    """
    :param bool user_creatable: Only types offered in the "add item" dialog.
    :return: Registered type classes in registration order.
    :rtype: list[type]
    """

    return [x for x in _ITEM_TYPES.values() if x.USER_CREATABLE or not user_creatable]


class ItemType:
    """
    Base class for item types.
    """

    TYPE = ''
    LABEL = ''
    DESCRIPTION = ''
    HAS_COMMAND = True
    FULL_WIDTH = False
    USER_CREATABLE = True
    # Shown in the item dialog next to the code editor so users know what their code receives.
    VARIABLES_HELP = ''
    DEFAULT_CODE = ''
    SETTINGS = []

    @classmethod
    def setting(cls, item, key):
        """
        :param toolbox_model.ToolboxItem item: The item.
        :param str key: Setting key.
        :return: The item's value, or the field default.
        :rtype: object
        """

        if key in item.settings:
            return item.settings[key]
        for field in cls.SETTINGS:
            if field.key == key:
                return field.default
        return None

    @classmethod
    def create_widget(cls, item, host, color=None):
        """
        Build the widget that represents the item.

        :param toolbox_model.ToolboxItem item: The item.
        :param object host: The toolbox host (see module docstring).
        :param str color: Effective hex color for this toolbox, or None.
        :return: The widget.
        :rtype: qtwidgets.QWidget
        """

        raise NotImplementedError

    @classmethod
    def _colored_container(cls, item, color):
        """
        A frame used as the background of composite widgets (slider, dropdown, form) so they can be colored too.

        :param toolbox_model.ToolboxItem item: The item.
        :param str color: Hex color or None.
        :return: (frame, layout).
        :rtype: tuple
        """

        frame = qtwidgets.QFrame()
        frame.setObjectName(f'tbx_container_{item.id}')
        if color:
            frame.setStyleSheet(f'QFrame#{frame.objectName()} {{ background-color: {color}; border-radius: 3px; }}'
                                f' QFrame#{frame.objectName()} QLabel, QFrame#{frame.objectName()} QCheckBox'
                                f' {{ color: {text_color_for(color)}; background: transparent; }}')
        layout = qtwidgets.QHBoxLayout(frame)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)
        frame.setToolTip(item.tooltip)
        return frame, layout


@register_item_type
class ButtonType(ItemType):
    """
    A push button that runs its command when clicked.
    """

    TYPE = 'button'
    LABEL = 'Button'
    DESCRIPTION = 'Runs the command when clicked.'
    DEFAULT_CODE = 'print("Hello from the toolbox")\n'
    SETTINGS = [SettingField('icon', 'Icon', 'icon', '',
                             tooltip='Image shown on the button. Browse copies new images into the toolbox icons '
                                     'folder so everyone sees them.'),
                SettingField('icon_only', 'Icon only', 'bool', False,
                             tooltip='Hide the text; the name is shown in the tooltip instead.')]

    @classmethod
    def create_widget(cls, item, host, color=None):
        icon_path = host.library.resolve_icon(cls.setting(item, 'icon'))
        # Without an icon file there is nothing to show, so an icon-only button keeps its text.
        icon_only = bool(icon_path and cls.setting(item, 'icon_only'))
        button = qtwidgets.QPushButton('' if icon_only else item.name)
        button.setObjectName(f'tbx_button_{item.id}')
        if icon_only:
            button.setToolTip(f'<b>{item.name}</b><br>{item.tooltip}' if item.tooltip else item.name)
        else:
            button.setToolTip(item.tooltip)
        if icon_path:
            button.setIcon(qtgui.QIcon(icon_path))
            button.setIconSize(qtcore.QSize(ICON_SIZE, ICON_SIZE))
        elif cls.setting(item, 'icon'):
            logger.debug(f'Toolbox: icon "{cls.setting(item, "icon")}" of "{item.name}" not found.')
        button.setMinimumHeight(26)
        button.setSizePolicy(qtwidgets.QSizePolicy.Expanding, qtwidgets.QSizePolicy.Fixed)
        if color:
            button.setStyleSheet(color_style('QPushButton', color, button.objectName()))
        button.clicked.connect(lambda checked=False: host.run_item(item))
        return button


@register_item_type
class CheckboxType(ItemType):
    """
    A checkbox that runs its command with the new state.
    """

    TYPE = 'checkbox'
    LABEL = 'Checkbox'
    DESCRIPTION = 'Runs the command with value=True/False when toggled.'
    VARIABLES_HELP = 'value (bool): the new checked state.'
    DEFAULT_CODE = 'print("Checked:", value)\n'
    SETTINGS = [SettingField('default', 'Checked by default', 'bool', False),
                SettingField('run_on_start', 'Run when the toolbox opens', 'bool', False,
                             tooltip='Apply the default state as soon as the toolbox is built.')]

    @classmethod
    def create_widget(cls, item, host, color=None):
        frame, layout = cls._colored_container(item, color)
        checkbox = qtwidgets.QCheckBox(item.name)
        checkbox.setChecked(bool(cls.setting(item, 'default')))
        checkbox.toggled.connect(lambda state: host.run_item(item, {'value': bool(state)}))
        layout.addWidget(checkbox)
        if cls.setting(item, 'run_on_start'):
            qtcore.QTimer.singleShot(0, lambda: host.run_item(item, {'value': checkbox.isChecked()}))
        return frame


@register_item_type
class SliderType(ItemType):
    """
    A labelled slider with a numeric field. Runs its command with the value on release (or live while dragging).
    """

    TYPE = 'slider'
    LABEL = 'Slider'
    DESCRIPTION = 'Runs the command with value=<number> when the slider is released or the number is typed.'
    FULL_WIDTH = True
    VARIABLES_HELP = 'value (float, or int when Decimals is 0): the slider value.'
    DEFAULT_CODE = 'print("Slider:", value)\n'
    SETTINGS = [SettingField('minimum', 'Minimum', 'float', 0.0),
                SettingField('maximum', 'Maximum', 'float', 1.0),
                SettingField('default', 'Default', 'float', 0.0),
                SettingField('decimals', 'Decimals', 'int', 2),
                SettingField('live', 'Run while dragging', 'bool', False,
                             tooltip='Run on every change instead of on release. Keep the command fast.')]

    @classmethod
    def create_widget(cls, item, host, color=None):
        decimals = max(0, min(6, int(cls.setting(item, 'decimals') or 0)))
        minimum = float(cls.setting(item, 'minimum'))
        maximum = float(cls.setting(item, 'maximum'))
        if maximum <= minimum:
            maximum = minimum + 1.0
        scale = 10 ** decimals
        live = bool(cls.setting(item, 'live'))

        frame, layout = cls._colored_container(item, color)
        label = qtwidgets.QLabel(item.name)
        slider = qtwidgets.QSlider(qtcore.Qt.Horizontal)
        slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
        spin = qtwidgets.QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(1.0 / scale if decimals else 1.0)
        spin.setFixedWidth(70)
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(spin)

        def current():
            value = spin.value()
            return int(round(value)) if decimals == 0 else value

        def emit():
            host.run_item(item, {'value': current()})

        def slider_moved(position):
            # Keep the spin box in sync without it re-triggering the slider.
            spin.blockSignals(True)
            spin.setValue(position / scale)
            spin.blockSignals(False)
            if live:
                emit()

        def spin_changed(value):
            slider.blockSignals(True)
            slider.setValue(int(round(value * scale)))
            slider.blockSignals(False)
            if live:
                emit()

        default = float(cls.setting(item, 'default') or 0.0)
        spin.setValue(default)
        slider.setValue(int(round(default * scale)))
        slider.valueChanged.connect(slider_moved)
        spin.valueChanged.connect(spin_changed)
        if not live:
            slider.sliderReleased.connect(emit)
            spin.editingFinished.connect(emit)
        return frame


@register_item_type
class DropdownType(ItemType):
    """
    A labelled combo box that runs its command with the chosen option.
    """

    TYPE = 'dropdown'
    LABEL = 'Dropdown'
    DESCRIPTION = 'Runs the command with value=<option text> when the selection changes.'
    FULL_WIDTH = True
    VARIABLES_HELP = 'value (str): the selected option.'
    DEFAULT_CODE = 'print("Picked:", value)\n'
    SETTINGS = [SettingField('options', 'Options (one per line)', 'lines', ['Option A', 'Option B']),
                SettingField('default', 'Default option', 'str', '')]

    @classmethod
    def create_widget(cls, item, host, color=None):
        frame, layout = cls._colored_container(item, color)
        layout.addWidget(qtwidgets.QLabel(item.name))
        combo = qtwidgets.QComboBox()
        combo.addItems([str(x) for x in (cls.setting(item, 'options') or [])])
        default = cls.setting(item, 'default')
        if default and combo.findText(default) >= 0:
            combo.setCurrentIndex(combo.findText(default))
        combo.currentTextChanged.connect(lambda text: host.run_item(item, {'value': text}))
        layout.addWidget(combo, 1)
        return frame


@register_item_type
class LabelType(ItemType):
    """
    Plain text: a heading or a note between tools.
    """

    TYPE = 'label'
    LABEL = 'Label'
    DESCRIPTION = 'Text only. Use it for headings or short notes.'
    HAS_COMMAND = False
    FULL_WIDTH = True
    SETTINGS = [SettingField('bold', 'Bold', 'bool', True),
                SettingField('align', 'Alignment', 'choice', 'left', options=['left', 'center', 'right'])]

    @classmethod
    def create_widget(cls, item, host, color=None):
        label = qtwidgets.QLabel(item.name)
        label.setObjectName(f'tbx_label_{item.id}')
        label.setWordWrap(True)
        label.setToolTip(item.tooltip)
        align = {'center': qtcore.Qt.AlignHCenter, 'right': qtcore.Qt.AlignRight}.get(
            cls.setting(item, 'align'), qtcore.Qt.AlignLeft)
        label.setAlignment(align | qtcore.Qt.AlignVCenter)
        style = 'font-weight: bold;' if cls.setting(item, 'bold') else ''
        if color:
            style += f' color: {color};'
        label.setStyleSheet(f'QLabel#{label.objectName()} {{ {style} padding: 2px; }}')
        return label


@register_item_type
class SeparatorType(ItemType):
    """
    A horizontal line that splits a section into groups.
    """

    TYPE = 'separator'
    LABEL = 'Separator'
    DESCRIPTION = 'A horizontal line. The name is optional and shown as a small caption.'
    HAS_COMMAND = False
    FULL_WIDTH = True

    @classmethod
    def create_widget(cls, item, host, color=None):
        frame = qtwidgets.QWidget()
        layout = qtwidgets.QHBoxLayout(frame)
        layout.setContentsMargins(0, 2, 0, 2)
        lines = []
        for _ in range(2 if item.name else 1):
            line = qtwidgets.QFrame()
            line.setFrameShape(qtwidgets.QFrame.HLine)
            line.setFrameShadow(qtwidgets.QFrame.Sunken)
            if color:
                line.setStyleSheet(f'background-color: {color}; min-height: 2px; max-height: 2px; border: none;')
            lines.append(line)
        layout.addWidget(lines[0], 1)
        if item.name:
            caption = qtwidgets.QLabel(item.name)
            caption.setStyleSheet('font-size: 8pt;' + (f' color: {color};' if color else ''))
            layout.addWidget(caption)
            layout.addWidget(lines[1], 1)
        return frame


@register_item_type
class PanelType(ItemType):
    """
    An existing Qt widget embedded straight into the section (e.g. a compact tool UI).
    """

    TYPE = 'panel'
    LABEL = 'Embedded panel'
    DESCRIPTION = ('Embeds a Qt widget in the section. Code must assign the widget to "widget" (or "win"); '
                   'a function must return it.')
    FULL_WIDTH = True
    VARIABLES_HELP = 'Assign your widget: widget = MyToolWidget()'
    DEFAULT_CODE = ('from mca.common.pyqt.pygui import qtwidgets\n'
                    'widget = qtwidgets.QLabel("My panel")\n')

    @classmethod
    def create_widget(cls, item, host, color=None):
        return host.build_panel(item)


@register_item_type
class FormType(ItemType):
    """
    A small UI built with the toolbox UI builder: fields plus a run button. The command gets every field value.
    """

    TYPE = 'form'
    LABEL = 'Form (UI builder)'
    DESCRIPTION = 'Build a small UI from fields. The run button passes values={field key: value} to the command.'
    FULL_WIDTH = True
    VARIABLES_HELP = 'values (dict): field key -> value, e.g. values["count"].'
    DEFAULT_CODE = 'print("Form values:", values)\n'
    SETTINGS = [SettingField('title', 'Title', 'str', ''),
                SettingField('button_text', 'Run button text', 'str', 'Run')]

    @classmethod
    def create_widget(cls, item, host, color=None):
        frame = qtwidgets.QFrame()
        frame.setObjectName(f'tbx_form_{item.id}')
        frame.setToolTip(item.tooltip)
        border = color or '#5a5a5a'
        frame.setStyleSheet(f'QFrame#{frame.objectName()} {{ border: 1px solid {border}; border-radius: 4px; }}')
        layout = qtwidgets.QVBoxLayout(frame)
        layout.setContentsMargins(6, 4, 6, 6)
        title = cls.setting(item, 'title') or item.name
        if title:
            title_label = qtwidgets.QLabel(title)
            title_label.setStyleSheet('font-weight: bold; border: none;')
            layout.addWidget(title_label)
        form = FormWidget(item.settings.get('fields') or [])
        layout.addWidget(form)
        button = qtwidgets.QPushButton(cls.setting(item, 'button_text') or 'Run')
        button.setObjectName(f'tbx_form_button_{item.id}')
        if color:
            button.setStyleSheet(color_style('QPushButton', color, button.objectName()))
        button.clicked.connect(lambda checked=False: host.run_item(item, {'values': form.values()}))
        layout.addWidget(button)
        return frame


@register_item_type
class ReferenceType(ItemType):
    """
    A personal-toolbox pointer to a shared item: shows the shared item's live widget without copying it.
    """

    TYPE = 'reference'
    LABEL = 'Reference'
    DESCRIPTION = 'Shows a shared item in a personal toolbox.'
    HAS_COMMAND = False
    USER_CREATABLE = False

    @classmethod
    def create_widget(cls, item, host, color=None):
        target = host.library.resolve_item(item)
        if target is None:
            button = qtwidgets.QPushButton(f'{item.name} (missing)')
            button.setEnabled(False)
            button.setToolTip('The shared tool this pointed at was deleted.')
            return button
        target_type = get_item_type(target.type)
        widget = target_type.create_widget(target, host, color)
        widget.setProperty(FULL_WIDTH_PROPERTY, target_type.FULL_WIDTH)
        return widget


class UnknownType(ItemType):
    """
    Placeholder for item types added by a newer version of the toolbox.
    """

    TYPE = '_unknown'
    LABEL = 'Unknown'
    HAS_COMMAND = False
    USER_CREATABLE = False

    @classmethod
    def create_widget(cls, item, host, color=None):
        label = qtwidgets.QLabel(f'{item.name} (unknown item type "{item.type}")')
        label.setEnabled(False)
        return label


# --- UI builder runtime ------------------------------------------------------------------------------------------

# Field kinds the UI builder offers: kind -> label shown in the builder.
FORM_FIELD_KINDS = {
    'text': 'Text',
    'multiline': 'Multi-line text',
    'int': 'Whole number',
    'float': 'Decimal number',
    'slider': 'Slider',
    'checkbox': 'Checkbox',
    'dropdown': 'Dropdown',
    'file': 'File path',
    'folder': 'Folder path',
    'label': 'Label (no value)',
}


class FormWidget(qtwidgets.QWidget):
    """
    Builds a form from UI builder field definitions and reads the values back.

    A field is a dict: ``{'key', 'label', 'kind', 'default', 'minimum', 'maximum', 'decimals', 'options',
    'tooltip'}``; only ``key`` and ``kind`` are required.
    """

    def __init__(self, fields, parent=None):
        """
        :param list[dict] fields: Field definitions, in display order.
        :param qtwidgets.QWidget parent: Parent widget.
        """

        super().__init__(parent)
        self.fields = [dict(x) for x in fields or [] if isinstance(x, dict)]
        # key -> callable returning the field's current value.
        self._getters = {}
        layout = qtwidgets.QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setFieldGrowthPolicy(qtwidgets.QFormLayout.AllNonFixedFieldsGrow)
        for field in self.fields:
            self._add_field(layout, field)

    def _add_field(self, layout, field):
        """
        Create the editor for one field and remember how to read it.

        :param qtwidgets.QFormLayout layout: The form layout.
        :param dict field: Field definition.
        """

        kind = field.get('kind', 'text')
        key = field.get('key') or field.get('label') or kind
        label = field.get('label', key)
        default = field.get('default')
        tooltip = field.get('tooltip', '')

        if kind == 'label':
            text = qtwidgets.QLabel(label)
            text.setWordWrap(True)
            layout.addRow(text)
            return
        if kind == 'multiline':
            editor = qtwidgets.QPlainTextEdit(str(default or ''))
            editor.setFixedHeight(60)
            getter = editor.toPlainText
        elif kind == 'int':
            editor = qtwidgets.QSpinBox()
            editor.setRange(int(field.get('minimum', -1000000)), int(field.get('maximum', 1000000)))
            editor.setValue(int(default or 0))
            getter = editor.value
        elif kind == 'float':
            editor = qtwidgets.QDoubleSpinBox()
            editor.setDecimals(int(field.get('decimals', 3)))
            editor.setRange(float(field.get('minimum', -1000000.0)), float(field.get('maximum', 1000000.0)))
            editor.setValue(float(default or 0.0))
            getter = editor.value
        elif kind == 'slider':
            editor, getter = self._slider(field, default)
        elif kind == 'checkbox':
            editor = qtwidgets.QCheckBox()
            editor.setChecked(bool(default))
            getter = editor.isChecked
        elif kind == 'dropdown':
            editor = qtwidgets.QComboBox()
            editor.addItems([str(x) for x in field.get('options') or []])
            if default is not None and editor.findText(str(default)) >= 0:
                editor.setCurrentIndex(editor.findText(str(default)))
            getter = editor.currentText
        elif kind in ('file', 'folder'):
            editor, getter = self._path_picker(kind, default)
        else:
            editor = qtwidgets.QLineEdit(str(default or ''))
            getter = editor.text
        editor.setToolTip(tooltip)
        layout.addRow(label, editor)
        self._getters[key] = getter

    @staticmethod
    def _slider(field, default):
        """
        :param dict field: Field definition.
        :param object default: Default value.
        :return: (editor widget, value getter).
        :rtype: tuple
        """

        decimals = max(0, min(6, int(field.get('decimals', 2))))
        scale = 10 ** decimals
        minimum = float(field.get('minimum', 0.0))
        maximum = float(field.get('maximum', 1.0))
        container = qtwidgets.QWidget()
        row = qtwidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        slider = qtwidgets.QSlider(qtcore.Qt.Horizontal)
        slider.setRange(int(round(minimum * scale)), int(round(max(maximum, minimum + 1.0 / scale) * scale)))
        slider.setValue(int(round(float(default or minimum) * scale)))
        readout = qtwidgets.QLabel()
        readout.setFixedWidth(50)

        def update_readout(position):
            readout.setText(f'{position / scale:.{decimals}f}')

        slider.valueChanged.connect(update_readout)
        update_readout(slider.value())
        row.addWidget(slider, 1)
        row.addWidget(readout)

        def getter():
            value = slider.value() / scale
            return int(round(value)) if decimals == 0 else value

        return container, getter

    def _path_picker(self, kind, default):
        """
        :param str kind: ``'file'`` or ``'folder'``.
        :param object default: Default path.
        :return: (editor widget, value getter).
        :rtype: tuple
        """

        container = qtwidgets.QWidget()
        row = qtwidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        line = qtwidgets.QLineEdit(str(default or ''))
        browse = qtwidgets.QToolButton()
        browse.setText('...')

        def pick():
            start = line.text() or os.path.expanduser('~')
            if kind == 'folder':
                path = qtwidgets.QFileDialog.getExistingDirectory(self, 'Choose folder', start)
            else:
                path = qtwidgets.QFileDialog.getOpenFileName(self, 'Choose file', start)[0]
            if path:
                line.setText(path)

        browse.clicked.connect(pick)
        row.addWidget(line, 1)
        row.addWidget(browse)
        return container, line.text

    def values(self):
        """
        :return: Field key -> current value for every field that has a value.
        :rtype: dict
        """

        return {key: getter() for key, getter in self._getters.items()}
