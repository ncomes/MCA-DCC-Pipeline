"""
Headless API for the MCA Toolbox, for scripts, the in-DCC AI and MCP tools.

Every function takes plain values, never raises, and returns ``{'ok': bool, 'result': <json>, 'message': str}``.
Edits go through the same :class:`toolbox_library.ToolboxLibrary` as the UI, so open toolbox windows refresh and
shared files are checked out in Perforce (never submitted).

Conventions:

- ``toolbox`` is a toolbox name (``'All Tools'``, ``'Animation'``, a personal toolbox name).
- Colors are ``'#rrggbb'``. For color arguments ``None`` leaves the color unchanged and ``''`` clears it.
- A command is either ``code`` (Python) or ``target`` (``'package.module:function'``); give one.
- Items receive ``value`` (checkbox, slider, dropdown) or ``values`` (form) when run.
"""

# python imports
import functools
import traceback

# MCA python imports
from mca.common import log
from mca.common.tools.toolbox import toolbox_library, toolbox_model, toolbox_runner

logger = log.MCA_LOGGER

# Lists returned to AI callers are capped so a huge toolbox cannot flood a response.
MAX_RESULTS = 200

_LIBRARY_OVERRIDE = None


def set_library(library):
    """
    Use a specific library (tests, or a DCC other than the running one). None restores the default.

    :param toolbox_library.ToolboxLibrary library: Library to use.
    """

    global _LIBRARY_OVERRIDE
    _LIBRARY_OVERRIDE = library


def _library():
    """
    :return: The library the API works on.
    :rtype: toolbox_library.ToolboxLibrary
    """

    return _LIBRARY_OVERRIDE or toolbox_library.get_library()


def _response(ok, result=None, message=''):
    """
    :param bool ok: Success flag.
    :param object result: JSON-serialisable result.
    :param str message: Human readable summary.
    :return: The standard response dict.
    :rtype: dict
    """

    return {'ok': ok, 'result': result, 'message': message}


def _safe(func):
    """
    Decorator: turn exceptions into failed responses and append library warnings (e.g. Perforce notes).

    :param callable func: API function returning (result, message).
    :return: Wrapped function returning a response dict.
    :rtype: callable
    """

    # functools.wraps keeps the name/docstring and sets __wrapped__, which the AI registry reads for the signature.
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result, message = func(*args, **kwargs)
        except (ValueError, KeyError) as exc:
            return _response(False, None, str(exc).strip("'\""))
        except Exception as exc:
            logger.error(f'toolbox_api.{func.__name__} failed: {exc}\n{traceback.format_exc()}')
            return _response(False, None, f'{type(exc).__name__}: {exc}')
        warnings = list(_library().warnings)
        if warnings:
            message = f'{message} Warnings: {" ".join(warnings)}'.strip()
        return _response(True, result, message)

    return wrapper


def _color_arg(value):
    """
    :param str|None value: API color argument.
    :return: KEEP for None, None (clear) for '', else the value.
    :rtype: object
    """

    if value is None:
        return toolbox_library.KEEP
    return value or None


def _item_summary(library, toolbox_name, section, item):
    """
    :param toolbox_library.ToolboxLibrary library: The library.
    :param str toolbox_name: Toolbox the colors are read from, or None.
    :param toolbox_model.ToolboxSection section: The item's section.
    :param toolbox_model.ToolboxItem item: The item.
    :return: A compact JSON description of the item.
    :rtype: dict
    """

    data = {'id': item.id, 'type': item.type, 'name': item.name, 'section_id': section.id,
            'section': section.name, 'command_kind': item.command.get('kind') if item.has_command else None}
    if item.tooltip:
        data['tooltip'] = item.tooltip
    if item.settings.get('icon'):
        data['icon'] = item.settings['icon']
    if toolbox_name:
        data['color'] = library.item_color(toolbox_name, item.id)
    if item.type == 'reference':
        data['reference_to'] = item.settings.get('item_id')
    return data


# --- Queries -----------------------------------------------------------------------------------------------------

@_safe
def list_toolboxes():
    """
    List every toolbox: All Tools, shared toolboxes, then the user's personal toolboxes.

    :return: Response with ``[{'name', 'shared', 'section_count'}]``.
    :rtype: dict
    """

    library = _library()
    result = [{'name': name, 'shared': library.get_toolbox(name).is_shared,
               'section_count': len(library.sections_in(name))} for name in library.toolbox_names()]
    return result, f'{len(result)} toolbox(es).'


@_safe
def get_toolbox(toolbox='All Tools', include_items=True):
    """
    Describe a toolbox: its sections in order, their colors, and optionally their items.

    :param str toolbox: Toolbox name.
    :param bool include_items: Include item summaries.
    :return: Response with ``{'name', 'shared', 'sections': [...]}``.
    :rtype: dict
    """

    library = _library()
    box = library.get_toolbox(toolbox)
    sections = []
    for section in library.sections_in(toolbox):
        entry = {'id': section.id, 'name': section.name, 'source': section.source,
                 'colors': library.section_colors(toolbox, section.id), 'item_count': len(section.items)}
        if include_items:
            entry['items'] = [_item_summary(library, toolbox, section, x) for x in section.items[:MAX_RESULTS]]
        sections.append(entry)
    return {'name': box.name, 'shared': box.is_shared, 'sections': sections}, f'{len(sections)} section(s).'


@_safe
def find_items(text, toolbox=None):
    """
    Find items whose name, tooltip, tags or section name contain every word of ``text``.

    :param str text: Words to match (case-insensitive). ``-word`` excludes.
    :param str toolbox: Only search sections shown in this toolbox. None searches everything.
    :return: Response with matching item summaries.
    :rtype: dict
    """

    library = _library()
    words = (text or '').lower().split()
    include = [x for x in words if not x.startswith('-')]
    exclude = [x[1:] for x in words if x.startswith('-') and len(x) > 1]
    sections = library.sections_in(toolbox) if toolbox else list(library.sections.values())
    matches = []
    for section in sections:
        for item in section.items:
            haystack = f'{section.name.lower()} {item.search_text()}'
            if all(x in haystack for x in include) and not any(x in haystack for x in exclude):
                matches.append(_item_summary(library, toolbox, section, item))
    return matches[:MAX_RESULTS], f'{len(matches)} match(es).'


@_safe
def get_item(item_id):
    """
    Full data of one item, including its command and settings.

    :param str item_id: Item id.
    :return: Response with the item dict plus ``section_id`` / ``section``.
    :rtype: dict
    """

    section, item = _library().find_item(item_id)
    if not item:
        raise KeyError(f'No item with id "{item_id}".')
    data = item.to_dict()
    data.update({'section_id': section.id, 'section': section.name})
    return data, item.name


@_safe
def list_item_types():
    """
    List the item types that can be created, with what their commands receive.

    :return: Response with ``[{'type', 'label', 'description', 'has_command', 'variables', 'settings'}]``.
    :rtype: dict
    """

    # Imported here: item types need Qt, the rest of the API does not.
    from mca.common.tools.toolbox import toolbox_items
    result = []
    for type_class in toolbox_items.item_types():
        result.append({'type': type_class.TYPE, 'label': type_class.LABEL, 'description': type_class.DESCRIPTION,
                       'has_command': type_class.HAS_COMMAND, 'variables': type_class.VARIABLES_HELP,
                       'settings': [{'key': f.key, 'label': f.label, 'kind': f.kind, 'default': f.default}
                                    for f in type_class.SETTINGS]})
    return result, f'{len(result)} item type(s).'


# --- Toolboxes and sections --------------------------------------------------------------------------------------

@_safe
def create_toolbox(name, shared=False):
    """
    Create an empty toolbox.

    :param str name: Toolbox name.
    :param bool shared: True for a Perforce-tracked toolbox everyone sees; False for a personal toolbox.
    :return: Response with the toolbox name.
    :rtype: dict
    """

    box = _library().create_toolbox(name, shared=shared)
    return box.name, f'Created {"shared" if shared else "personal"} toolbox "{box.name}".'


@_safe
def delete_toolbox(name):
    """
    Delete a toolbox. Shared sections stay in All Tools; a personal toolbox's own sections are deleted.

    :param str name: Toolbox name (not All Tools).
    :return: Response.
    :rtype: dict
    """

    _library().delete_toolbox(name)
    return name, f'Deleted toolbox "{name}".'


@_safe
def add_section(toolbox, name, background=None, header=None, before_section_id=None, personal_colors=False):
    """
    Create a section in a toolbox. Sections made in shared toolboxes also appear in All Tools.

    :param str toolbox: Toolbox name.
    :param str name: Section name.
    :param str background: Background color in this toolbox.
    :param str header: Header color in this toolbox.
    :param str before_section_id: Insert before this section. None appends.
    :param bool personal_colors: Keep the colors private to this user.
    :return: Response with the new section id.
    :rtype: dict
    """

    section = _library().add_section(toolbox, name, before_id=before_section_id, background=background or None,
                                     header=header or None, personal_colors=personal_colors)
    return section.id, f'Added section "{name}" to {toolbox}.'


@_safe
def show_section_in_toolbox(toolbox, section_id, before_section_id=None):
    """
    Show an existing section in a toolbox, or move it within that toolbox.

    :param str toolbox: Toolbox name.
    :param str section_id: Section id.
    :param str before_section_id: Place before this section. None appends.
    :return: Response.
    :rtype: dict
    """

    _library().add_existing_section(toolbox, section_id, before_id=before_section_id)
    return section_id, f'Section shown in {toolbox}.'


@_safe
def remove_section_from_toolbox(toolbox, section_id):
    """
    Hide a section in one toolbox without deleting it (not possible in All Tools).

    :param str toolbox: Toolbox name.
    :param str section_id: Section id.
    :return: Response.
    :rtype: dict
    """

    _library().remove_section_from_toolbox(toolbox, section_id)
    return section_id, f'Section removed from {toolbox}.'


@_safe
def delete_section(section_id):
    """
    Delete a section and its items from every toolbox (shared deletes go into the pending changelist).

    :param str section_id: Section id.
    :return: Response.
    :rtype: dict
    """

    name = _library().get_section(section_id).name
    _library().delete_section(section_id)
    return section_id, f'Deleted section "{name}".'


@_safe
def rename_section(section_id, name):
    """
    Rename a section (the name is the same in every toolbox).

    :param str section_id: Section id.
    :param str name: New name.
    :return: Response.
    :rtype: dict
    """

    _library().rename_section(section_id, name)
    return section_id, f'Renamed section to "{name}".'


@_safe
def set_section_colors(toolbox, section_id, background=None, header=None, personal=False):
    """
    Set the colors a section uses in one toolbox.

    :param str toolbox: Toolbox name.
    :param str section_id: Section id.
    :param str background: ``'#rrggbb'``; ``''`` clears; None leaves unchanged.
    :param str header: ``'#rrggbb'``; ``''`` clears; None leaves unchanged.
    :param bool personal: Private to this user instead of stored in the toolbox.
    :return: Response.
    :rtype: dict
    """

    library = _library()
    library.set_section_colors(toolbox, section_id, background=_color_arg(background), header=_color_arg(header),
                               personal=personal)
    return library.section_colors(toolbox, section_id), 'Section colors updated.'


# --- Items -------------------------------------------------------------------------------------------------------

def _command(code, target):
    """
    :param str code: Python code.
    :param str target: ``'package.module:function'``.
    :return: A command dict, or None when neither is given.
    :rtype: dict|None
    """

    if target:
        return {'kind': toolbox_model.COMMAND_CALLABLE, 'target': target}
    if code is not None:
        return {'kind': toolbox_model.COMMAND_PYTHON, 'code': code}
    return None


@_safe
def add_item(section_id, name, item_type='button', code=None, target=None, tooltip='', settings=None, tags=None,
             toolbox=None, color=None, before_item_id=None):
    """
    Add an item (button, slider, form...) to a section.

    :param str section_id: Section id.
    :param str name: Display name.
    :param str item_type: See :func:`list_item_types`.
    :param str code: Python code to run.
    :param str target: ``'package.module:function'`` to call instead of code.
    :param str tooltip: Tooltip.
    :param dict settings: Type settings, e.g. ``{'minimum': 0, 'maximum': 10}`` or form ``{'fields': [...]}``.
    :param list[str] tags: Extra filter words.
    :param str toolbox: Toolbox to store ``color`` in.
    :param str color: Item color in ``toolbox``.
    :param str before_item_id: Insert before this item. None appends.
    :return: Response with the new item id and any problems found in the command.
    :rtype: dict
    """

    command = _command(code, target)
    item = toolbox_model.ToolboxItem(item_type=item_type, name=name, tooltip=tooltip, command=command,
                                     settings=settings, tags=tags)
    problems = toolbox_runner.check_command(item.command) if item.has_command else []
    _library().add_item(section_id, item, before_id=before_item_id, toolbox_name=toolbox, color=color or None)
    message = f'Added {item_type} "{name}".'
    if problems:
        message += f' Command problems: {"; ".join(problems)}'
    return {'item_id': item.id, 'problems': problems}, message


@_safe
def update_item(item_id, name=None, code=None, target=None, tooltip=None, settings=None, tags=None, item_type=None):
    """
    Change an item. Arguments left as None are unchanged. Giving ``code`` or ``target`` replaces the command.

    :param str item_id: Item id.
    :param str name: Display name.
    :param str code: New Python code.
    :param str target: New ``'package.module:function'``.
    :param str tooltip: Tooltip.
    :param dict settings: Replaces all type settings.
    :param list[str] tags: Filter tags.
    :param str item_type: New item type.
    :return: Response with any problems found in the command.
    :rtype: dict
    """

    keep = toolbox_library.KEEP
    command = _command(code, target)
    problems = toolbox_runner.check_command(command) if command else []
    item = _library().update_item(item_id, name=keep if name is None else name,
                                  tooltip=keep if tooltip is None else tooltip,
                                  command=keep if command is None else command,
                                  settings=keep if settings is None else settings,
                                  tags=keep if tags is None else tags,
                                  item_type=keep if item_type is None else item_type)
    message = f'Updated "{item.name}".'
    if problems:
        message += f' Command problems: {"; ".join(problems)}'
    return {'item_id': item.id, 'problems': problems}, message


@_safe
def delete_item(item_id):
    """
    Delete an item from its section (every toolbox showing the section loses it).

    :param str item_id: Item id.
    :return: Response.
    :rtype: dict
    """

    _library().delete_item(item_id)
    return item_id, 'Item deleted.'


@_safe
def move_item(item_id, section_id, before_item_id=None):
    """
    Move an item within or between sections. Moving a shared item into a personal section adds a reference.

    :param str item_id: Item id.
    :param str section_id: Destination section id.
    :param str before_item_id: Place before this item. None appends.
    :return: Response with the id of the item now in the destination.
    :rtype: dict
    """

    item = _library().move_item(item_id, section_id, before_id=before_item_id)
    return item.id, f'Moved "{item.name}".'


@_safe
def duplicate_item(item_id):
    """
    Copy an item next to the original.

    :param str item_id: Item id.
    :return: Response with the copy's id.
    :rtype: dict
    """

    item = _library().duplicate_item(item_id)
    return item.id, f'Created "{item.name}".'


@_safe
def set_item_color(toolbox, item_id, color, personal=False):
    """
    Set the color an item uses in one toolbox.

    :param str toolbox: Toolbox name.
    :param str item_id: Item id.
    :param str color: ``'#rrggbb'``, or ``''`` to clear.
    :param bool personal: Private to this user instead of stored in the toolbox.
    :return: Response.
    :rtype: dict
    """

    library = _library()
    library.set_item_color(toolbox, item_id, color or None, personal=personal)
    return library.item_color(toolbox, item_id), 'Item color updated.'


@_safe
def list_icons(text=None):
    """
    List icon images buttons can use (toolbox icons folder first, then the MCA icon libraries).

    :param str text: Only icons whose name contains this text, e.g. ``'skin'``. None lists all.
    :return: Response with ``[{'icon', 'path'}]``; pass ``icon`` to set_item_icon.
    :rtype: dict
    """

    icons = _library().list_icons(text)
    return icons[:MAX_RESULTS], f'{len(icons)} icon(s).'


@_safe
def import_icon(file_path, shared=True):
    """
    Copy an image file into the toolbox icons folder so everyone can use it (shared icons are added to Perforce).

    :param str file_path: Absolute path of a .png, .svg, .jpg, .bmp or .ico file.
    :param bool shared: Shared icons folder (checked in). False keeps it in the user's local folder.
    :return: Response with the icon name to pass to set_item_icon.
    :rtype: dict
    """

    name = _library().import_icon(file_path, shared=shared)
    return name, f'Icon available as "{name}".'


@_safe
def set_item_icon(item_id, icon='', icon_only=None):
    """
    Set or remove a button's icon. Other settings are kept.

    :param str item_id: Item id of a button.
    :param str icon: Icon name from list_icons / import_icon, or '' to remove the icon.
    :param bool icon_only: True hides the button text, False shows it, None leaves it unchanged.
    :return: Response.
    :rtype: dict
    """

    item = _library().set_item_icon(item_id, icon=icon or None,
                                    icon_only=toolbox_library.KEEP if icon_only is None else icon_only)
    return item.settings.get('icon'), f'Icon of "{item.name}" ' + ('set.' if icon else 'removed.')


@_safe
def run_item(item_id, value=None, values=None):
    """
    Run an item's command as if clicked.

    :param str item_id: Item id (references run the shared item).
    :param object value: ``value`` for checkbox / slider / dropdown commands.
    :param dict values: ``values`` for form commands.
    :return: Response; ``ok`` is False when the command raised.
    :rtype: dict
    """

    library = _library()
    _, item = library.find_item(item_id)
    if not item:
        raise KeyError(f'No item with id "{item_id}".')
    item = library.resolve_item(item)
    if item is None:
        raise KeyError('The shared item this reference points at was deleted.')
    variables = {}
    if value is not None:
        variables['value'] = value
    if values is not None:
        variables['values'] = values
    result = toolbox_runner.run_command(item.command, item.name, variables, keep_alive_key=item.id)
    if not result.ok:
        raise RuntimeError(result.error)
    return item.id, f'Ran "{item.name}".'


@_safe
def check_items(toolbox=None):
    """
    Find items whose commands import modules or call functions that no longer exist, and broken references.

    :param str toolbox: Only check this toolbox. None checks every section.
    :return: Response with ``[{'item_id', 'name', 'section', 'problems'}]``.
    :rtype: dict
    """

    library = _library()
    sections = library.sections_in(toolbox) if toolbox else list(library.sections.values())
    broken = []
    for section in sections:
        for item in section.items:
            problems = []
            if item.type == 'reference':
                if library.resolve_item(item) is None:
                    problems = ['shared item was deleted']
            elif item.has_command:
                problems = toolbox_runner.check_command(item.command)
            if problems:
                broken.append({'item_id': item.id, 'name': item.name, 'section': section.name,
                               'problems': problems})
    return broken, f'{len(broken)} broken item(s).'


@_safe
def reload():
    """
    Re-read all toolbox files from disk.

    :return: Response.
    :rtype: dict
    """

    _library().reload()
    return None, 'Reloaded.'
