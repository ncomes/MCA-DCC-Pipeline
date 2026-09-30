"""
Plain data classes and YAML file IO for the MCA Toolbox.

Qt-free and DCC-agnostic so the headless API, MCP tools and tests can use it outside of any DCC.

Three kinds of file make up a toolbox set:

- **Section** (``sections/<section_id>.yaml``): a named, ordered list of items. Sections are shared by every
  toolbox that shows them, so names, commands and item order are the same everywhere.
- **Toolbox** (``toolboxes/<name>.yaml``): which sections a toolbox shows, in what order, and the colors that
  toolbox uses. Colors live here so each toolbox can have its own color scheme.
- **Overrides** (``overrides/<name>.yaml``, local only): one user's "just for me" colors on top of a toolbox.

Requires: PyYAML.
Side effects: :func:`write_yaml` creates parent folders.
"""

# python imports
import copy
import os
import re
import uuid

# third-party imports
import yaml

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

__all__ = ['ALL_TOOLS', 'SHARED', 'LOCAL', 'ToolboxItem', 'ToolboxSection', 'Toolbox', 'ColorOverrides',
           'make_id', 'normalize_color', 'read_yaml', 'write_yaml']

# The toolbox every shared section always appears in. It cannot be deleted or renamed.
ALL_TOOLS = 'All Tools'

# Where a section or toolbox is stored. Shared files are version controlled, local files are per user.
SHARED = 'shared'
LOCAL = 'local'

# Command kinds. "python" runs a code string; "callable" imports "package.module:function" and calls it.
COMMAND_PYTHON = 'python'
COMMAND_CALLABLE = 'callable'

# File format version written into every file, so later changes can migrate old data.
FORMAT_VERSION = 1


def make_id(name):
    """
    Build a readable, unique id from a display name, e.g. ``'Camera Tools'`` -> ``'camera_tools_3fa1c2'``.

    The name part only helps humans reading file names and Perforce history; the id never changes when the
    display name does.

    :param str name: Display name to base the id on.
    :return: A lowercase id that is safe to use as a file name.
    :rtype: str
    """

    slug = re.sub(r'[^a-z0-9]+', '_', (name or '').lower()).strip('_')[:32] or 'entry'
    return f'{slug}_{uuid.uuid4().hex[:6]}'


def normalize_color(value):
    """
    Convert any supported color value to ``'#rrggbb'``.

    Accepts ``'#rgb'``, ``'#rrggbb'``, ``'rrggbb'`` and ``[r, g, b]`` lists of ints or numeric strings (the legacy
    ``.tbx`` format).

    :param str|list|None value: The color to convert.
    :return: The color as a hex string, or None when the value is empty or unreadable.
    :rtype: str|None
    """

    if value in (None, '', []):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            r, g, b = [max(0, min(255, int(float(x)))) for x in value]
        except (TypeError, ValueError):
            return None
        return f'#{r:02x}{g:02x}{b:02x}'
    if isinstance(value, str):
        text = value.strip().lstrip('#')
        if re.fullmatch(r'[0-9a-fA-F]{3}', text):
            text = ''.join(c * 2 for c in text)
        if re.fullmatch(r'[0-9a-fA-F]{6}', text):
            return f'#{text.lower()}'
    logger.warning(f'Toolbox: ignoring unreadable color {value!r}')
    return None


# --- YAML IO -----------------------------------------------------------------------------------------------------

class _ToolboxDumper(yaml.SafeDumper):
    """
    SafeDumper that writes multi-line strings (commands) as literal ``|`` blocks, so code in the YAML files reads
    like code and Perforce diffs stay line based.
    """


def _represent_str(dumper, data):
    """
    Represent multi-line strings as literal blocks and everything else as plain scalars.

    :param yaml.SafeDumper dumper: The active dumper.
    :param str data: The string being written.
    :return: The YAML node for the string.
    :rtype: yaml.ScalarNode
    """

    if '\n' in data:
        # Literal blocks cannot hold trailing whitespace on a line; strip it so PyYAML does not fall back to quotes.
        data = '\n'.join(line.rstrip() for line in data.split('\n'))
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


_ToolboxDumper.add_representer(str, _represent_str)


def read_yaml(path):
    """
    Read a toolbox YAML file.

    :param str path: Absolute path of the file.
    :return: The file's mapping, or an empty dict when the file is missing, empty or unreadable.
    :rtype: dict
    """

    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = yaml.safe_load(handle)
    except Exception as exc:
        logger.error(f'Toolbox: could not read {path}: {exc}')
        return {}
    return data if isinstance(data, dict) else {}


def write_yaml(path, data):
    """
    Write a toolbox YAML file, keeping key order as given.

    Raises instead of swallowing errors so callers can tell the user a save failed (usually a read-only file that
    is not checked out).

    :param str path: Absolute path of the file.
    :param dict data: Data to write.
    """

    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = yaml.dump(data, Dumper=_ToolboxDumper, sort_keys=False, allow_unicode=True, width=120,
                     default_flow_style=False)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


# --- Data classes ------------------------------------------------------------------------------------------------

class ToolboxItem:
    """
    One widget in a section: a button, slider, embedded panel, form, etc.

    The ``item_type`` names an entry in the Qt item registry (``toolbox_items``); this class does not know how to
    draw itself so it stays usable without Qt.
    """

    def __init__(self, item_id=None, item_type='button', name='', tooltip='', command=None, settings=None,
                 tags=None):
        """
        :param str item_id: Unique id. Generated from the name when not given.
        :param str item_type: Registered item type, e.g. ``'button'``, ``'slider'``, ``'panel'``.
        :param str name: Display name.
        :param str tooltip: Tooltip text, also searched by the filter.
        :param dict command: ``{'kind': 'python', 'code': str}`` or ``{'kind': 'callable', 'target': str}``.
        :param dict settings: Type specific settings, e.g. slider min/max, form fields.
        :param list[str] tags: Extra words the filter matches.
        """

        self.id = item_id or make_id(name)
        self.type = item_type or 'button'
        self.name = name or ''
        self.tooltip = tooltip or ''
        self.command = self._normalize_command(command)
        self.settings = dict(settings or {})
        self.tags = [str(x) for x in (tags or [])]

    @staticmethod
    def _normalize_command(command):
        """
        Coerce a command value to the dict form. A bare string is treated as Python code.

        :param dict|str|None command: Command as stored or passed by a caller.
        :return: A command dict with ``kind`` and either ``code`` or ``target``.
        :rtype: dict
        """

        if isinstance(command, str):
            return {'kind': COMMAND_PYTHON, 'code': command}
        command = dict(command or {})
        if command.get('kind') == COMMAND_CALLABLE:
            return {'kind': COMMAND_CALLABLE, 'target': str(command.get('target') or '')}
        return {'kind': COMMAND_PYTHON, 'code': str(command.get('code') or '')}

    @property
    def has_command(self):
        """
        :return: True when the command has code or a target to run.
        :rtype: bool
        """

        return bool((self.command.get('code') or self.command.get('target') or '').strip())

    def search_text(self):
        """
        :return: Lowercase text the toolbox filter matches against.
        :rtype: str
        """

        return ' '.join([self.name, self.tooltip, self.type] + self.tags).lower()

    def to_dict(self):
        """
        :return: The item as a YAML-ready dict. Empty optional fields are left out to keep files short.
        :rtype: dict
        """

        data = {'id': self.id, 'type': self.type, 'name': self.name}
        if self.tooltip:
            data['tooltip'] = self.tooltip
        if self.has_command:
            data['command'] = dict(self.command)
        if self.settings:
            data['settings'] = copy.deepcopy(self.settings)
        if self.tags:
            data['tags'] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data):
        """
        :param dict data: Item data as read from YAML.
        :return: The item.
        :rtype: ToolboxItem
        """

        return cls(item_id=data.get('id'), item_type=data.get('type'), name=data.get('name'),
                   tooltip=data.get('tooltip'), command=data.get('command'), settings=data.get('settings'),
                   tags=data.get('tags'))

    def copy(self, new_id=False):
        """
        :param bool new_id: Give the copy a fresh id (for duplicating an item).
        :return: A deep copy of this item.
        :rtype: ToolboxItem
        """

        item = ToolboxItem.from_dict(copy.deepcopy(self.to_dict()))
        if new_id:
            item.id = make_id(item.name)
        return item

    def __repr__(self):
        return f'<ToolboxItem {self.type} {self.name!r} ({self.id})>'


class ToolboxSection:
    """
    A named group of items. Stored one section per file so people can edit different sections at the same time.
    """

    def __init__(self, section_id=None, name='', items=None, source=SHARED, path=None):
        """
        :param str section_id: Unique id, also the file name. Generated from the name when not given.
        :param str name: Display name.
        :param list[ToolboxItem] items: Ordered items.
        :param str source: :data:`SHARED` or :data:`LOCAL`.
        :param str path: Absolute file path, set by the library.
        """

        self.id = section_id or make_id(name)
        self.name = name or ''
        self.items = list(items or [])
        self.source = source
        self.path = path

    def get_item(self, item_id):
        """
        :param str item_id: Item id to look for.
        :return: The item, or None.
        :rtype: ToolboxItem|None
        """

        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def index_of(self, item_id):
        """
        :param str item_id: Item id to look for.
        :return: The item's index, or -1.
        :rtype: int
        """

        for index, item in enumerate(self.items):
            if item.id == item_id:
                return index
        return -1

    def to_dict(self):
        """
        :return: The section as a YAML-ready dict.
        :rtype: dict
        """

        return {'format': FORMAT_VERSION, 'id': self.id, 'name': self.name,
                'items': [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, data, source=SHARED, path=None):
        """
        :param dict data: Section data as read from YAML.
        :param str source: :data:`SHARED` or :data:`LOCAL`.
        :param str path: The file the data came from.
        :return: The section.
        :rtype: ToolboxSection
        """

        items = [ToolboxItem.from_dict(x) for x in (data.get('items') or []) if isinstance(x, dict)]
        return cls(section_id=data.get('id'), name=data.get('name'), items=items, source=source, path=path)

    def __repr__(self):
        return f'<ToolboxSection {self.name!r} ({self.id}, {len(self.items)} items)>'


class Toolbox:
    """
    A toolbox: an ordered list of section ids plus this toolbox's own colors.

    ``section_colors`` maps a section id to ``{'background': hex, 'header': hex}``; ``item_colors`` maps an item id
    to a hex color. Ids that no longer exist are ignored when drawing, so a section deleted by someone else never
    breaks a toolbox.
    """

    def __init__(self, name, sections=None, section_colors=None, item_colors=None, source=SHARED, path=None):
        """
        :param str name: Toolbox name, also the file name.
        :param list[str] sections: Ordered section ids.
        :param dict section_colors: Section id -> ``{'background': hex|None, 'header': hex|None}``.
        :param dict item_colors: Item id -> hex color.
        :param str source: :data:`SHARED` or :data:`LOCAL`.
        :param str path: Absolute file path, set by the library.
        """

        self.name = name
        self.sections = [str(x) for x in (sections or [])]
        self.section_colors = {}
        for section_id, colors in (section_colors or {}).items():
            colors = colors or {}
            cleaned = {key: normalize_color(colors.get(key)) for key in ('background', 'header')}
            cleaned = {key: value for key, value in cleaned.items() if value}
            if cleaned:
                self.section_colors[str(section_id)] = cleaned
        self.item_colors = {}
        for item_id, color in (item_colors or {}).items():
            color = normalize_color(color)
            if color:
                self.item_colors[str(item_id)] = color
        self.source = source
        self.path = path

    @property
    def is_all_tools(self):
        """
        :return: True for the shared All Tools toolbox.
        :rtype: bool
        """

        return self.source == SHARED and self.name == ALL_TOOLS

    @property
    def is_shared(self):
        """
        :return: True when the toolbox is stored in version control.
        :rtype: bool
        """

        return self.source == SHARED

    def set_section_color(self, section_id, key, color):
        """
        Set or clear one color of a section in this toolbox.

        :param str section_id: Section id.
        :param str key: ``'background'`` or ``'header'``.
        :param str|None color: Hex color, or None to clear.
        """

        colors = self.section_colors.setdefault(section_id, {})
        color = normalize_color(color)
        if color:
            colors[key] = color
        else:
            colors.pop(key, None)
        if not colors:
            self.section_colors.pop(section_id, None)

    def set_item_color(self, item_id, color):
        """
        Set or clear an item's color in this toolbox.

        :param str item_id: Item id.
        :param str|None color: Hex color, or None to clear.
        """

        color = normalize_color(color)
        if color:
            self.item_colors[item_id] = color
        else:
            self.item_colors.pop(item_id, None)

    def forget(self, section_id=None, item_ids=None):
        """
        Remove a section and/or items from this toolbox's order and colors.

        :param str section_id: Section id to remove from the order and section colors.
        :param list[str] item_ids: Item ids whose colors should be dropped.
        :return: True when anything changed.
        :rtype: bool
        """

        changed = False
        if section_id and section_id in self.sections:
            self.sections = [x for x in self.sections if x != section_id]
            changed = True
        if section_id and self.section_colors.pop(section_id, None) is not None:
            changed = True
        for item_id in item_ids or []:
            if self.item_colors.pop(item_id, None) is not None:
                changed = True
        return changed

    def to_dict(self):
        """
        :return: The toolbox as a YAML-ready dict.
        :rtype: dict
        """

        data = {'format': FORMAT_VERSION, 'name': self.name, 'sections': list(self.sections)}
        if self.section_colors:
            data['section_colors'] = copy.deepcopy(self.section_colors)
        if self.item_colors:
            data['item_colors'] = dict(self.item_colors)
        return data

    @classmethod
    def from_dict(cls, data, source=SHARED, path=None, name=None):
        """
        :param dict data: Toolbox data as read from YAML.
        :param str source: :data:`SHARED` or :data:`LOCAL`.
        :param str path: The file the data came from.
        :param str name: Fallback name (the file name) when the data has none.
        :return: The toolbox.
        :rtype: Toolbox
        """

        return cls(name=data.get('name') or name, sections=data.get('sections'),
                   section_colors=data.get('section_colors'), item_colors=data.get('item_colors'),
                   source=source, path=path)

    def __repr__(self):
        return f'<Toolbox {self.name!r} ({self.source}, {len(self.sections)} sections)>'


class ColorOverrides(Toolbox):
    """
    A user's private colors for one toolbox. Same color fields as :class:`Toolbox`, no section order, always local.
    """

    def to_dict(self):
        """
        :return: The overrides as a YAML-ready dict.
        :rtype: dict
        """

        data = super().to_dict()
        data.pop('sections', None)
        return data
