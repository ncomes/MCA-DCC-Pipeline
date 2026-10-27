"""
Exposes the asset list to AI: the headless API (``mca.common.assetlist.assetlist_api``).

One spec drives both surfaces so they never drift:

- :func:`register_all` registers the functions with the in-Maya AI ``FunctionRegistry``
  (MCA Wizard / Orange Slice).
- :func:`generate_mcp_tools` writes one typed wrapper file per function into ``mcp_tools/``
  for the MCAMayaMCP server (add that folder with ``--tool-dir``). Signatures are read from
  source, so generation works outside Maya. Regenerate after changing the spec::

    cd packages
    python -c "import sys; sys.path[:0]=['mca-common','mca-maya']; from mca.mya.tools.assetregister import assetlist_ai; assetlist_ai.generate_mcp_tools()"

The asset list is DCC-agnostic, so every tool here works in Maya, Unreal and standalone.

Requires: nothing at import time (the registry and API modules are imported inside the functions).
Side effects: :func:`generate_mcp_tools` overwrites the ``asset_*.py`` files in ``mcp_tools/``.
"""

# python imports
import ast
import glob
import importlib
import os

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

API_MODULE = 'mca.common.assetlist.assetlist_api'

# (tool name, module, function, confirm before running, {parameter: type}).
# Types: str, bool, int, dict, list, and json (any JSON value, passed as text by MCP and decoded
# in the wrapper).
SPEC = [
    # Discovery: the order a caller should follow before writing anything.
    ('asset_list_categories', API_MODULE, 'list_categories', False, {}),
    ('asset_describe_category', API_MODULE, 'describe_category', False, {'category': 'str'}),
    ('asset_describe_schema', API_MODULE, 'describe_schema', False, {}),
    # Queries.
    ('asset_get', API_MODULE, 'get_asset', False, {'asset_id': 'str', 'verbose': 'bool'}),
    ('asset_list', API_MODULE, 'list_assets', False,
     {'category': 'str', 'subtype': 'str', 'faction': 'str', 'built_for': 'str', 'limit': 'int'}),
    ('asset_search', API_MODULE, 'search_assets', False, {'query': 'str', 'limit': 'int'}),
    ('asset_get_paths', API_MODULE, 'get_asset_paths', False, {'asset_id': 'str'}),
    ('asset_get_hierarchy', API_MODULE, 'get_asset_hierarchy', False, {'asset_id': 'str'}),
    ('asset_get_children', API_MODULE, 'get_asset_children', False,
     {'asset_id': 'str', 'include_descendants': 'bool', 'limit': 'int'}),
    ('asset_count', API_MODULE, 'get_asset_count', False, {'category': 'str'}),
    ('asset_list_variants', API_MODULE, 'list_variants', False, {'asset_id': 'str'}),
    ('asset_check', API_MODULE, 'check_assets', False, {}),
    ('asset_reload', API_MODULE, 'reload', False, {}),
    # Explicit file references: which file on disk backs the rig / skeleton / mesh.
    ('asset_list_file_kinds', API_MODULE, 'list_file_kinds', False, {}),
    ('asset_get_files', API_MODULE, 'get_asset_files', False, {'asset_id': 'str'}),
    ('asset_check_files', API_MODULE, 'check_asset_files', False, {'category': 'str'}),
    # Writes.
    ('asset_register', API_MODULE, 'register_asset', True,
     {'name': 'str', 'category': 'str', 'subtype': 'str', 'faction': 'str', 'skeleton': 'str',
      'body_type': 'str', 'asset_type': 'str', 'built_for': 'str', 'slot': 'str',
      'description': 'str', 'path': 'str', 'engine_path': 'str', 'asset_id': 'str'}),
    ('asset_update', API_MODULE, 'update_asset', True, {'asset_id': 'str', 'fields': 'dict'}),
    ('asset_remove', API_MODULE, 'remove_asset', True, {'asset_id': 'str'}),
    ('asset_set_variant_base', API_MODULE, 'set_variant_base', True,
     {'asset_id': 'str', 'base_asset_id': 'str'}),
    ('asset_transfer', API_MODULE, 'transfer_asset', True,
     {'asset_id': 'str', 'category': 'str'}),
    ('asset_set_file', API_MODULE, 'set_asset_file', True,
     {'asset_id': 'str', 'kind': 'str', 'file_path': 'str'}),
    ('asset_repair_files', API_MODULE, 'repair_asset_files', True,
     {'asset_id': 'str', 'category': 'str'}),
]

MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_tools')

# Tools that only read. The rest get a line in their docstring saying they rewrite a .alist file.
_NO_FILE_CHANGES = {'asset_list_categories', 'asset_describe_category', 'asset_describe_schema',
                    'asset_get', 'asset_list', 'asset_search', 'asset_get_paths',
                    'asset_get_hierarchy', 'asset_get_children', 'asset_count', 'asset_check',
                    'asset_reload', 'asset_list_file_kinds', 'asset_get_files',
                    'asset_check_files', 'asset_list_variants'}

_SCHEMA_TYPES = {'str': 'string', 'int': 'integer', 'float': 'number', 'bool': 'boolean',
                 'list': 'array', 'dict': 'object', 'json': 'string'}
_PY_TYPES = {'str': 'str', 'int': 'int', 'float': 'float', 'bool': 'bool', 'list': 'list',
             'dict': 'dict', 'json': 'str'}


def _module_file(module_name):
    """
    Find a module's source file without importing it.

    :param str module_name: Dotted module name.
    :return: Absolute path to the .py file, or None.
    :rtype: str or None
    """

    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None
    return spec.origin if spec and spec.origin and spec.origin.endswith('.py') else None


def _function_info(module_name, func_name):
    """
    Read a function's parameters and docstring from its source file without importing it.

    :param str module_name: Dotted module name.
    :param str func_name: Function name.
    :return: ``{'params': [(name, has_default, default)], 'summary': str,
        'descriptions': {name: str}}``.
    :rtype: dict
    """

    path = _module_file(module_name)
    if not path:
        raise ImportError(f'Cannot find source for {module_name}')
    with open(path, 'r', encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    node = next((x for x in tree.body
                 if isinstance(x, ast.FunctionDef) and x.name == func_name), None)
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


def register_all(spec=None):
    """
    Register every spec function with the in-Maya AI FunctionRegistry.

    :param list spec: Spec rows to register. Defaults to this module's SPEC;
        another tool's AI module passes its own.
    :return: Number of functions registered.
    :rtype: int
    """

    from mca.ai.actions import FunctionRegistry
    from mca.ai.actions.base_action import SafetyLevel

    count = 0
    for tool_name, module_name, func_name, confirm, types in (spec or SPEC):
        try:
            func = getattr(importlib.import_module(module_name), func_name)
            info = _function_info(module_name, func_name)
        except Exception as exc:
            logger.warning('Assetlist AI: skipping %s: %s', tool_name, exc)
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
    logger.info('Registered %d functions with the AI FunctionRegistry', count)
    return count


def generate_mcp_tools(out_dir=MCP_DIR, spec=None, prefix='asset_', no_side_effects=None,
                      side_effect_note=' Rewrites one category .alist file.'):
    """
    Write one MCP wrapper file per spec function (and remove stale wrapper files).

    Each file holds a single typed function named like the file, which the MCP server turns
    into a tool schema and runs inside the DCC.

    The generator is not specific to the asset list; another tool's AI module passes its own
    spec, folder and prefix rather than copying this.

    :param str out_dir: Folder to write into.
    :param list spec: Spec rows. Defaults to this module's SPEC.
    :param str prefix: Shared prefix of the generated file names, used to find stale ones.
    :param set no_side_effects: Tool names that only read. Defaults to this module's set.
    :param str side_effect_note: Sentence appended to the docstring of every other tool.
    :return: Paths written.
    :rtype: list[str]
    """

    spec = spec or SPEC
    no_side_effects = _NO_FILE_CHANGES if no_side_effects is None else no_side_effects

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for tool_name, module_name, func_name, confirm, types in spec:
        info = _function_info(module_name, func_name)
        args = []
        call_args = []
        decode_lines = []
        descriptions = dict(info['descriptions'])
        for name, has_default, default in info['params']:
            py_type = _PY_TYPES.get(types.get(name, 'str'), 'str')
            args.append(f'{name}: {py_type} = {default!r}' if has_default
                        else f'{name}: {py_type}')
            call_args.append(f'{name}={name}')
            if types.get(name) == 'json':
                decode_lines.append(
                    f'    {name} = json.loads({name}) if isinstance({name}, str) and {name} '
                    f'else {name}')
                descriptions[name] = (f'{descriptions.get(name, "")} Pass as JSON text, '
                                      'e.g. "0.5", "true", "\\"World\\"".')
        package, _, module_short = module_name.rpartition('.')
        body = ['"""',
                f'MCP tool: {tool_name} - wrapper over {module_name}.{func_name}.',
                'Auto-generated by mca.mya.tools.assetregister.assetlist_ai; edit the source '
                'function / SPEC, not this file.',
                '"""', '', '',
                f'def {tool_name}({", ".join(args)}) -> dict:',
                '    """',
                f'    {info["summary"]}']
        if info['params']:
            body.append('')
            body.extend(f'    {name}: {descriptions.get(name, "")}'
                        for name, _, _ in info['params'])
        body.append('')
        body.append("    Returns {'ok': bool, 'result': ..., 'message': str}. On failure the "
                    "message names the valid values, so read it before retrying." +
                    ('' if tool_name in no_side_effects else side_effect_note))
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
    for path in glob.glob(os.path.join(out_dir, '{}*.py'.format(prefix))):
        if os.path.normcase(path) not in expected:
            os.remove(path)
    return written
