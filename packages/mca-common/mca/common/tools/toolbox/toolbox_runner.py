"""
Runs toolbox item commands and checks them for dead imports.

A command is either Python code (run with ``exec``) or a ``'package.module:function'`` target (imported and called).
Every run is wrapped in a run context supplied by the DCC layer (Maya opens one undo chunk per click) and never
raises: failures are logged with the item name and returned as a :class:`RunResult`.

Variables passed to a run are visible to Python code as globals and passed to callables as keyword arguments:

- ``value``: the new value of a checkbox, slider or dropdown.
- ``values``: a dict of field values from a form (UI builder) item.

Side effects: executes user supplied code.
"""

# python imports
import ast
import contextlib
import importlib
import inspect
import os
import sys
import traceback

# MCA python imports
from mca.common import log
from mca.common.tools.toolbox import toolbox_model

logger = log.MCA_LOGGER

__all__ = ['RunResult', 'set_run_context', 'run_command', 'build_panel', 'check_command']

# Factory returning a context manager for one run: ``factory(label)``. The DCC layer swaps this out.
_RUN_CONTEXT_FACTORY = None

# Last namespace / return value per item. Code like ``win = MyWindow()`` relies on the variable to keep an unparented
# window alive, so the namespace must outlive the exec call.
_KEEP_ALIVE = {}

# Names Python code in a panel item can assign its widget to. ``win`` is what the legacy toolbox used.
PANEL_VARIABLES = ('widget', 'win', 'window', 'ui')


class RunResult:
    """
    Outcome of running a command.
    """

    def __init__(self, ok, value=None, error=''):
        """
        :param bool ok: True when the command ran without raising.
        :param object value: Callable return value, or the exec namespace for Python code.
        :param str error: One line error summary when ``ok`` is False.
        """

        self.ok = ok
        self.value = value
        self.error = error

    def __bool__(self):
        return self.ok


def set_run_context(factory):
    """
    Set the context manager every command runs inside.

    :param callable factory: ``factory(label)`` returning a context manager, or None for no wrapping.
    """

    global _RUN_CONTEXT_FACTORY
    _RUN_CONTEXT_FACTORY = factory


def _run_context(label):
    """
    :param str label: Name of what is running (undo chunk name in Maya).
    :return: The active run context manager.
    :rtype: contextlib.AbstractContextManager
    """

    if _RUN_CONTEXT_FACTORY:
        try:
            return _RUN_CONTEXT_FACTORY(label)
        except Exception:
            logger.exception('Toolbox: run context factory failed; running without it.')
    return contextlib.nullcontext()


def resolve_target(target):
    """
    Import and return the object named by a callable target.

    Accepts ``'package.module:attr'`` and ``'package.module.attr'``; the colon form is preferred because it is
    unambiguous. Nested attributes (``'module:Class.method'``) are supported.

    :param str target: The target string.
    :return: The resolved object.
    :rtype: object
    """

    target = (target or '').strip()
    if ':' in target:
        module_name, _, attr_path = target.partition(':')
    else:
        module_name, _, attr_path = target.rpartition('.')
    if not module_name or not attr_path:
        raise ValueError(f'"{target}" is not a valid target. Use "package.module:function".')
    obj = importlib.import_module(module_name)
    for part in attr_path.split('.'):
        obj = getattr(obj, part)
    return obj


def _call_with_variables(func, variables):
    """
    Call a function, passing only the variables its signature accepts.

    :param callable func: Function to call.
    :param dict variables: Candidate keyword arguments.
    :return: The function's return value.
    :rtype: object
    """

    if not variables:
        return func()
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(**variables)
    params = signature.parameters.values()
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
        return func(**variables)
    accepted = {key: value for key, value in variables.items() if key in signature.parameters}
    return func(**accepted)


def run_command(command, label='Toolbox', variables=None, keep_alive_key=None):
    """
    Run a command dict.

    :param dict command: ``{'kind': 'python', 'code': str}`` or ``{'kind': 'callable', 'target': str}``.
    :param str label: Item name, used for the undo chunk, the code's file name in tracebacks, and log lines.
    :param dict variables: ``value`` / ``values`` to expose to the command.
    :param str keep_alive_key: When given, the result is held until the next run with the same key.
    :return: The run result. Never raises.
    :rtype: RunResult
    """

    command = command or {}
    variables = dict(variables or {})
    try:
        with _run_context(label):
            if command.get('kind') == toolbox_model.COMMAND_CALLABLE:
                value = _call_with_variables(resolve_target(command.get('target')), variables)
            else:
                code = command.get('code') or ''
                namespace = {'__name__': '__toolbox__', '__builtins__': __builtins__}
                namespace.update(variables)
                exec(compile(code, f'<toolbox: {label}>', 'exec'), namespace)
                value = namespace
    except Exception as exc:
        logger.error(f'Toolbox "{label}" failed: {exc}\n{traceback.format_exc()}')
        return RunResult(False, error=f'{type(exc).__name__}: {exc}')
    if keep_alive_key:
        _KEEP_ALIVE[keep_alive_key] = value
    return RunResult(True, value=value)


def build_panel(command, label='Toolbox'):
    """
    Run a panel item's command and return the widget it creates.

    Python code must assign the widget to one of :data:`PANEL_VARIABLES`; a callable must return it.
    Panels are built outside the undo context: building UI is not a scene change.

    :param dict command: The panel item's command.
    :param str label: Item name for errors.
    :return: (widget or None, error text).
    :rtype: tuple[object, str]
    """

    command = command or {}
    try:
        if command.get('kind') == toolbox_model.COMMAND_CALLABLE:
            widget = resolve_target(command.get('target'))()
        else:
            namespace = {'__name__': '__toolbox__', '__builtins__': __builtins__}
            exec(compile(command.get('code') or '', f'<toolbox panel: {label}>', 'exec'), namespace)
            widget = next((namespace[x] for x in PANEL_VARIABLES if namespace.get(x) is not None), None)
            if widget is None:
                return None, f'Panel code must assign its widget to one of: {", ".join(PANEL_VARIABLES)}.'
    except Exception as exc:
        logger.error(f'Toolbox panel "{label}" failed: {exc}\n{traceback.format_exc()}')
        return None, f'{type(exc).__name__}: {exc}'
    return widget, ''


# --- Static checks -----------------------------------------------------------------------------------------------

def _find_module_file(module_name):
    """
    Locate a module's source file on ``sys.path`` without importing it (importing Maya tools outside Maya fails).

    :param str module_name: Dotted module name.
    :return: The ``.py`` / ``__init__.py`` path, ``''`` for a namespace package or extension module, None when not
        found.
    :rtype: str|None
    """

    parts = module_name.split('.')
    for root in sys.path:
        # An empty entry means the current directory, which is how the framework is on the path
        # for every `python -m` run from the packages folder and for every test run. The version
        # this replaces skipped it, so the check reported *every* mca module as missing whenever
        # the package was reached that way - and the toolbox shows that to an artist as a broken
        # tool.
        root = root or os.getcwd()
        if not os.path.isdir(root):
            continue
        base = os.path.join(root, *parts)
        if os.path.isfile(base + '.py'):
            return base + '.py'
        if os.path.isfile(os.path.join(base, '__init__.py')):
            return os.path.join(base, '__init__.py')
        if os.path.isdir(base):
            return ''
        folder = os.path.dirname(base)
        if os.path.isdir(folder) and any(x.startswith(parts[-1] + '.') and x.endswith(('.pyd', '.so'))
                                         for x in os.listdir(folder)):
            return ''
    return None


def _top_level_names(path):
    """
    :param str path: Python source file.
    :return: Names defined or imported at module level, or None when the file cannot be parsed (or uses ``*``
        imports, which makes the check unreliable).
    :rtype: set[str]|None
    """

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            source = handle.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return None
    if 'globals()[' in source or 'def __getattr__' in source or 'setattr(sys.modules' in source:
        # Names are added at import time (e.g. frag/__init__.py re-exports its component modules): can't check.
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == '*':
                    return None
                names.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, (ast.Try, ast.If)):
            # Conditional imports/definitions: collect everything one level down.
            for child in ast.walk(node):
                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                    names.add(child.name)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        names.add((alias.asname or alias.name).split('.')[0])
                elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    names.add(child.id)
    return names


def _check_attribute(module_name, attr, problems):
    """
    Check that ``module_name`` defines ``attr`` (or has a submodule of that name).

    :param str module_name: Dotted module name.
    :param str attr: Attribute to look for.
    :param list[str] problems: Problems found are appended here.
    :return: The submodule name when ``attr`` is a submodule, else None.
    :rtype: str|None
    """

    submodule = f'{module_name}.{attr}'
    if _find_module_file(submodule) is not None:
        return submodule
    path = _find_module_file(module_name)
    if path:
        names = _top_level_names(path)
        if names is not None and attr not in names:
            problems.append(f'{module_name} has no "{attr}"')
    return None


def check_command(command, only_prefixes=('mca.',)):
    """
    Statically check a command for imports and attribute calls that no longer exist.

    Only modules under ``only_prefixes`` are checked; third-party modules often live on paths the DCC adds at
    startup, so their absence outside the DCC says nothing. The check never imports anything.

    :param dict command: The command dict.
    :param tuple[str] only_prefixes: Module name prefixes to check.
    :return: Human readable problems. Empty means nothing was found wrong.
    :rtype: list[str]
    """

    problems = []
    command = command or {}

    def wanted(module_name):
        return any(module_name == p.rstrip('.') or module_name.startswith(p) for p in only_prefixes)

    if command.get('kind') == toolbox_model.COMMAND_CALLABLE:
        target = command.get('target') or ''
        module_name, _, attr_path = target.partition(':') if ':' in target else target.rpartition('.')
        if not module_name or not attr_path:
            return [f'"{target}" is not a valid target']
        if wanted(module_name):
            if _find_module_file(module_name) is None:
                problems.append(f'module {module_name} not found')
            else:
                _check_attribute(module_name, attr_path.split('.')[0], problems)
        return problems

    try:
        tree = ast.parse(command.get('code') or '')
    except SyntaxError as exc:
        return [f'syntax error on line {exc.lineno}: {exc.msg}']

    # Map local names to the module they refer to, so "alias.func()" calls can be checked too.
    module_aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not wanted(alias.name):
                    continue
                if _find_module_file(alias.name) is None:
                    problems.append(f'module {alias.name} not found')
                elif alias.asname:
                    module_aliases[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0 and wanted(node.module):
            if _find_module_file(node.module) is None:
                problems.append(f'module {node.module} not found')
                continue
            for alias in node.names:
                submodule = _check_attribute(node.module, alias.name, problems)
                if submodule:
                    module_aliases[alias.asname or alias.name] = submodule

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in module_aliases:
            module_name = module_aliases[node.value.id]
            path = _find_module_file(module_name)
            if path:
                names = _top_level_names(path)
                if names is not None and node.attr not in names and \
                        _find_module_file(f'{module_name}.{node.attr}') is None:
                    message = f'{module_name} has no "{node.attr}"'
                    if message not in problems:
                        problems.append(message)
    return problems
