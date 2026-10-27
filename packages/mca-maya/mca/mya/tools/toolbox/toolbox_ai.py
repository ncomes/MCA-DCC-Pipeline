"""
Exposes the toolbox to AI: the headless data API (``mca.common.tools.toolbox.toolbox_api``) and the Maya dock
functions (``mca.mya.tools.toolbox.ma_toolbox_ui.api_*``: open several toolboxes, dock/tab them, list open docks).

One spec drives both surfaces so they never drift:

- :func:`register_all` registers the functions with the in-Maya AI ``FunctionRegistry`` (MCA Wizard / Orange Slice).
- :func:`generate_mcp_tools` writes one typed wrapper file per function into ``mcp_tools/`` for the MCAMayaMCP
  server (add that folder with ``--tool-dir``). Signatures are read from source, so generation works outside Maya.
  Regenerate after changing the spec::

    cd packages
    python -c "import sys; sys.path[:0]=['mca-common','mca-maya']; from mca.mya.tools.toolbox import toolbox_ai; toolbox_ai.generate_mcp_tools()"

Requires: nothing at import time (the registry and API modules are imported inside the functions).
Side effects: :func:`generate_mcp_tools` overwrites the ``toolbox_*.py`` files in ``mcp_tools/``.
"""

# python imports
import ast
import glob
import importlib
import os

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

API_MODULE = 'mca.common.tools.toolbox.toolbox_api'
DOCK_MODULE = 'mca.mya.tools.toolbox.ma_toolbox_ui'

# (tool name, module, function, confirm before running, {parameter: type}).
# Types: str, bool, int, dict, list, and json (any JSON value, passed as text by MCP and decoded in the wrapper).
SPEC = [
    ('toolbox_list_toolboxes', API_MODULE, 'list_toolboxes', False, {}),
    ('toolbox_get_toolbox', API_MODULE, 'get_toolbox', False, {'toolbox': 'str', 'include_items': 'bool'}),
    ('toolbox_find_items', API_MODULE, 'find_items', False, {'text': 'str', 'toolbox': 'str'}),
    ('toolbox_get_item', API_MODULE, 'get_item', False, {'item_id': 'str'}),
    ('toolbox_list_item_types', API_MODULE, 'list_item_types', False, {}),
    ('toolbox_check_items', API_MODULE, 'check_items', False, {'toolbox': 'str'}),
    ('toolbox_create_toolbox', API_MODULE, 'create_toolbox', False, {'name': 'str', 'shared': 'bool'}),
    ('toolbox_delete_toolbox', API_MODULE, 'delete_toolbox', True, {'name': 'str'}),
    ('toolbox_add_section', API_MODULE, 'add_section', False,
     {'toolbox': 'str', 'name': 'str', 'background': 'str', 'header': 'str', 'before_section_id': 'str',
      'personal_colors': 'bool'}),
    ('toolbox_show_section_in_toolbox', API_MODULE, 'show_section_in_toolbox', False,
     {'toolbox': 'str', 'section_id': 'str', 'before_section_id': 'str'}),
    ('toolbox_remove_section_from_toolbox', API_MODULE, 'remove_section_from_toolbox', False,
     {'toolbox': 'str', 'section_id': 'str'}),
    ('toolbox_delete_section', API_MODULE, 'delete_section', True, {'section_id': 'str'}),
    ('toolbox_rename_section', API_MODULE, 'rename_section', False, {'section_id': 'str', 'name': 'str'}),
    ('toolbox_set_section_colors', API_MODULE, 'set_section_colors', False,
     {'toolbox': 'str', 'section_id': 'str', 'background': 'str', 'header': 'str', 'personal': 'bool'}),
    ('toolbox_add_item', API_MODULE, 'add_item', False,
     {'section_id': 'str', 'name': 'str', 'item_type': 'str', 'code': 'str', 'target': 'str', 'tooltip': 'str',
      'settings': 'dict', 'tags': 'list', 'toolbox': 'str', 'color': 'str', 'before_item_id': 'str'}),
    ('toolbox_update_item', API_MODULE, 'update_item', False,
     {'item_id': 'str', 'name': 'str', 'code': 'str', 'target': 'str', 'tooltip': 'str', 'settings': 'dict',
      'tags': 'list', 'item_type': 'str'}),
    ('toolbox_delete_item', API_MODULE, 'delete_item', True, {'item_id': 'str'}),
    ('toolbox_move_item', API_MODULE, 'move_item', False,
     {'item_id': 'str', 'section_id': 'str', 'before_item_id': 'str'}),
    ('toolbox_duplicate_item', API_MODULE, 'duplicate_item', False, {'item_id': 'str'}),
    ('toolbox_set_item_color', API_MODULE, 'set_item_color', False,
     {'toolbox': 'str', 'item_id': 'str', 'color': 'str', 'personal': 'bool'}),
    ('toolbox_list_icons', API_MODULE, 'list_icons', False, {'text': 'str'}),
    ('toolbox_import_icon', API_MODULE, 'import_icon', False, {'file_path': 'str', 'shared': 'bool'}),
    ('toolbox_set_item_icon', API_MODULE, 'set_item_icon', False,
     {'item_id': 'str', 'icon': 'str', 'icon_only': 'bool'}),
    ('toolbox_run_item', API_MODULE, 'run_item', True, {'item_id': 'str', 'value': 'json', 'values': 'dict'}),
    ('toolbox_reload', API_MODULE, 'reload', False, {}),
    # Maya docks: several toolboxes open at once, docked in different areas or tabbed.
    ('toolbox_open', DOCK_MODULE, 'api_open_toolbox', False, {'toolbox': 'str', 'area': 'str', 'tab_with': 'str'}),
    ('toolbox_list_open', DOCK_MODULE, 'api_list_open_toolboxes', False, {}),
    ('toolbox_close', DOCK_MODULE, 'api_close_toolbox', False, {'toolbox': 'str'}),
]

MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_tools')

# Tools that neither change toolbox files nor docks (no Perforce note in their description).
_NO_FILE_CHANGES = {'toolbox_list_toolboxes', 'toolbox_get_toolbox', 'toolbox_find_items', 'toolbox_get_item',
                    'toolbox_list_item_types', 'toolbox_check_items', 'toolbox_run_item', 'toolbox_reload',
                    'toolbox_list_icons',
                    'toolbox_open', 'toolbox_list_open', 'toolbox_close'}

_SCHEMA_TYPES = {'str': 'string', 'int': 'integer', 'float': 'number', 'bool': 'boolean', 'list': 'array',
                 'dict': 'object', 'json': 'string'}
_PY_TYPES = {'str': 'str', 'int': 'int', 'float': 'float', 'bool': 'bool', 'list': 'list', 'dict': 'dict',
             'json': 'str'}


def _function_info(module_name, func_name):
    """
    Read a function's parameters and docstring from its source file without importing it (the dock module needs
    Maya).

    :param str module_name: Dotted module name.
    :param str func_name: Function name.
    :return: ``{'params': [(name, has_default, default)], 'summary': str, 'descriptions': {name: str}}``.
    :rtype: dict
    """

    from mca.common.tools.toolbox import toolbox_runner
    path = toolbox_runner._find_module_file(module_name)
    if not path:
        raise ImportError(f'Cannot find source for {module_name}')
    with open(path, 'r', encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    node = next((x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == func_name), None)
    if node is None:
        raise AttributeError(f'{module_name} has no function {func_name}')

    args = node.args.args
    defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
    params = []
    for arg, default in zip(args, defaults):
        if default is None:
            params.append((arg.arg, False, None))
        else:
            params.append((arg.arg, True, ast.literal_eval(default)))

    doc = ast.get_docstring(node) or ''
    descriptions = {}
    for line in doc.splitlines():
        line = line.strip()
        if line.startswith(':param '):
            head, _, text = line.partition(':')[2].partition(':')
            name = head.split()[-1] if head.split() else ''
            descriptions[name] = text.strip()
    summary = doc.split('\n\n')[0].replace('\n', ' ').strip()
    return {'params': params, 'summary': summary, 'descriptions': descriptions}


def register_all():
    """
    Register every spec function with the in-Maya AI FunctionRegistry.

    :return: Number of functions registered.
    :rtype: int
    """

    from mca.ai.actions import FunctionRegistry
    from mca.ai.actions.base_action import SafetyLevel

    count = 0
    for tool_name, module_name, func_name, confirm, types in SPEC:
        try:
            func = getattr(importlib.import_module(module_name), func_name)
            info = _function_info(module_name, func_name)
        except Exception as exc:
            logger.warning(f'Toolbox AI: skipping {tool_name}: {exc}')
            continue
        parameters = {}
        for name, has_default, default in info['params']:
            entry = {'type': _SCHEMA_TYPES.get(types.get(name, 'str'), 'string'),
                     'description': info['descriptions'].get(name, '')}
            if has_default:
                entry['default'] = default
            parameters[name] = entry
        try:
            FunctionRegistry.register(name=tool_name, func=func,
                                      safety=SafetyLevel.CONFIRM if confirm else SafetyLevel.SAFE,
                                      description=info['summary'], parameters=parameters)
            count += 1
        except ValueError:
            # Already registered (restart / reload).
            continue
    logger.info(f'Registered {count} toolbox functions with the AI FunctionRegistry')
    return count


def generate_mcp_tools(out_dir=MCP_DIR):
    """
    Write one MCP wrapper file per spec function (and remove stale ``toolbox_*.py`` files). Each file holds a single
    typed function named like the file, which the MCP server turns into a tool schema and runs inside Maya.

    :param str out_dir: Folder to write into.
    :return: Paths written.
    :rtype: list[str]
    """

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for tool_name, module_name, func_name, confirm, types in SPEC:
        info = _function_info(module_name, func_name)
        args = []
        call_args = []
        decode_lines = []
        descriptions = dict(info['descriptions'])
        for name, has_default, default in info['params']:
            py_type = _PY_TYPES.get(types.get(name, 'str'), 'str')
            args.append(f'{name}: {py_type} = {default!r}' if has_default else f'{name}: {py_type}')
            call_args.append(f'{name}={name}')
            if types.get(name) == 'json':
                decode_lines.append(f'    {name} = json.loads({name}) if isinstance({name}, str) and {name} else '
                                    f'{name}')
                descriptions[name] = f'{descriptions.get(name, "")} Pass as JSON text, e.g. "0.5", "true", ' \
                                     '"\\"World\\"".'
        package, _, module_short = module_name.rpartition('.')
        body = ['"""',
                f'MCP tool: {tool_name} - wrapper over {module_name}.{func_name}.',
                'Auto-generated by mca.mya.tools.toolbox.toolbox_ai; edit the source function / SPEC, not this file.',
                '"""', '', '',
                f'def {tool_name}({", ".join(args)}) -> dict:',
                '    """',
                f'    {info["summary"]}']
        if info['params']:
            body.append('')
            body.extend(f'    {name}: {descriptions.get(name, "")}' for name, _, _ in info['params'])
        body.append('')
        body.append("    Returns {'ok': bool, 'result': ..., 'message': str}." +
                    ('' if tool_name in _NO_FILE_CHANGES else
                     ' Shared toolbox files it changes are checked out in Perforce, never submitted.'))
        body.append('    """')
        if decode_lines:
            body.append('    import json')
            body.extend(decode_lines)
        body.append(f'    from {package} import {module_short}')
        body.append(f'    return {module_short}.{func_name}({", ".join(call_args)})')
        path = os.path.join(out_dir, f'{tool_name}.py')
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write('\n'.join(body) + '\n')
        written.append(path)

    # Drop wrappers for tools that left the spec.
    expected = set(os.path.normcase(x) for x in written)
    for path in glob.glob(os.path.join(out_dir, 'toolbox_*.py')):
        if os.path.normcase(path) not in expected:
            os.remove(path)
    return written
