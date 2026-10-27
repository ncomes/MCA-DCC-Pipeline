"""
Function Registry

This module provides a central registry for whitelisted Python functions
that can be called by the AI.

The registry stores:
- Function references (callable objects)
- Safety levels (SAFE/CONFIRM/DANGEROUS)
- Descriptions for system prompt
- Parameter schemas for validation

Functions must be explicitly registered to be callable by the AI.
This provides a hard whitelist approach - no dynamic imports or eval.

Classes:
    FunctionRegistry - Central registry for whitelisted functions

Usage:
    from mca.ai.actions.function_registry import FunctionRegistry
    from mca.ai.actions.base_action import SafetyLevel

    # Register a function
    FunctionRegistry.register(
        name="selection_tools.get_selected",
        func=get_selected_nodes,
        safety=SafetyLevel.SAFE,
        description="Get currently selected nodes",
        parameters={}
    )

    # Get function info
    func_info = FunctionRegistry.get("selection_tools.get_selected")

    # List all functions
    all_funcs = FunctionRegistry.list_functions()
"""

# python imports
from mca.ai.actions.base_action import SafetyLevel


class FunctionRegistry:
    """
    Central registry of whitelisted Python functions.

    This is a singleton class - all methods are class methods that operate
    on shared state. Functions are registered at startup and available
    throughout the application lifetime.

    Functions are registered with:
    - name: Unique identifier (e.g., "selection_tools.get_selected")
    - func: Callable reference
    - safety: SafetyLevel (SAFE/CONFIRM/DANGEROUS)
    - description: Human-readable description for AI
    - parameters: Dict describing expected kwargs

    Thread Safety:
        The registry is not thread-safe. Functions should be registered
        during application startup before any concurrent access.
    """

    # Shared state - all registered functions
    _functions = {}

    # Logger instance (set during startup)
    _logger = None

    @classmethod
    def set_logger(cls, logger):
        """
        Set the logger instance for the registry.

        :param logger: Logger instance (e.g., MCA_LOGGER).
        """
        cls._logger = logger

    @classmethod
    def register(cls, name, func, safety, description, parameters=None):
        """
        Register a Python function with the registry.

        :param str name: Unique function identifier (e.g., "selection_tools.get_selected")
        :param callable func: The function to register
        :param SafetyLevel safety: Safety level for the function
        :param str description: Human-readable description
        :param dict parameters: Optional parameter schema
            Format: {"param_name": {"type": "string", "description": "...", "default": None}}
        :raises TypeError: If func is not callable
        :raises ValueError: If function with same name already registered

        Example:
            FunctionRegistry.register(
                name="transform_tools.freeze_transforms",
                func=freeze_transforms,
                safety=SafetyLevel.CONFIRM,
                description="Freeze transforms on selected objects",
                parameters={
                    "nodes": {"type": "list", "description": "Nodes to freeze (or selection if None)"}
                }
            )
        """
        if not callable(func):
            raise TypeError(f'Function must be callable, got {type(func)}')

        if name in cls._functions:
            if cls._logger:
                cls._logger.warning(f'Overwriting existing function: {name}')

        cls._functions[name] = {
            'name': name,
            'func': func,
            'safety': safety,
            'description': description,
            'parameters': parameters or {},
        }

        if cls._logger:
            cls._logger.debug(f'Registered function: {name} (safety: {safety.value})')

    @classmethod
    def unregister(cls, name):
        """
        Remove a function from the registry.

        :param str name: Name of the function to remove.
        :return: True if function was removed, False if not found.
        :rtype: bool
        """
        if name in cls._functions:
            del cls._functions[name]
            if cls._logger:
                cls._logger.debug(f'Unregistered function: {name}')
            return True
        return False

    @classmethod
    def get(cls, name):
        """
        Get a function by name.

        :param str name: Function name.
        :return: Function info dict or None if not found.
        :rtype: dict or None

        Returns dict with:
            - name: Function name
            - func: Callable reference
            - safety: SafetyLevel
            - description: Description string
            - parameters: Parameter schema
        """
        return cls._functions.get(name)

    @classmethod
    def get_callable(cls, name):
        """
        Get just the callable for a function.

        :param str name: Function name.
        :return: Callable or None if not found.
        :rtype: callable or None
        """
        func_info = cls._functions.get(name)
        if func_info:
            return func_info['func']
        return None

    @classmethod
    def get_safety(cls, name):
        """
        Get the safety level for a function.

        :param str name: Function name.
        :return: SafetyLevel or None if not found.
        :rtype: SafetyLevel or None
        """
        func_info = cls._functions.get(name)
        if func_info:
            return func_info['safety']
        return None

    @classmethod
    def is_registered(cls, name):
        """
        Check if a function is registered.

        :param str name: Function name.
        :return: True if registered.
        :rtype: bool
        """
        return name in cls._functions

    @classmethod
    def list_functions(cls, safety=None):
        """
        List all registered functions.

        :param SafetyLevel safety: Optional filter by safety level.
        :return: List of function info dicts.
        :rtype: list[dict]
        """
        result = []
        for func_info in cls._functions.values():
            if safety is not None and func_info['safety'] != safety:
                continue
            # Return copy without callable (for serialization)
            result.append({
                'name': func_info['name'],
                'safety': func_info['safety'].value,
                'description': func_info['description'],
                'parameters': func_info['parameters'],
            })
        return result

    @classmethod
    def list_names(cls):
        """
        Get list of all registered function names.

        :return: List of function names.
        :rtype: list[str]
        """
        return list(cls._functions.keys())

    @classmethod
    def get_for_prompt(cls):
        """
        Format all registered functions for the system prompt.

        Returns a formatted string describing all available functions
        that can be included in the AI's system prompt.

        :return: Formatted string of available functions.
        :rtype: str
        """
        if not cls._functions:
            return ""

        lines = ["**Available Python Functions:**", ""]

        # Group by category (first part of name before .)
        categories = {}
        for name, info in cls._functions.items():
            # Skip DANGEROUS functions in prompt
            if info['safety'] == SafetyLevel.DANGEROUS:
                continue

            parts = name.split('.')
            category = parts[0] if len(parts) > 1 else 'general'
            if category not in categories:
                categories[category] = []
            categories[category].append(info)

        # Format each category
        for category, funcs in sorted(categories.items()):
            # Convert category to title case
            cat_title = category.replace('_', ' ').title()
            lines.append(f"**{cat_title}:**")

            for info in sorted(funcs, key=lambda x: x['name']):
                # Build parameter list
                params = info.get('parameters', {})
                param_strs = []
                for pname, pinfo in params.items():
                    if pinfo.get('default') is not None:
                        param_strs.append(f"{pname}={pinfo['default']!r}")
                    else:
                        param_strs.append(pname)
                param_str = ', '.join(param_strs)

                # Add safety indicator for CONFIRM
                safety_marker = " [requires confirmation]" if info['safety'] == SafetyLevel.CONFIRM else ""

                lines.append(f"- `{info['name']}({param_str})` - {info['description']}{safety_marker}")

            lines.append("")

        return '\n'.join(lines)

    @classmethod
    def clear(cls):
        """
        Remove all registered functions.

        Primarily used for testing.
        """
        cls._functions.clear()
        if cls._logger:
            cls._logger.debug('Cleared all functions from registry')

    @classmethod
    def get_count(cls):
        """
        Get number of registered functions.

        :return: Function count.
        :rtype: int
        """
        return len(cls._functions)
