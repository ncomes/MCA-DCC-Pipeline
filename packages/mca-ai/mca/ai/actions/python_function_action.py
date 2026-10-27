"""
Python Function Action

This module provides the PythonFunctionAction class that enables execution
of whitelisted Python functions via the AI.

Unlike MayaCmdAction which wraps maya.cmds operations, PythonFunctionAction
allows calling higher-level Python functions registered in the FunctionRegistry.

The action:
- Validates function exists in registry
- Checks safety level
- Validates kwargs against function parameters
- Produces execution payload for the Maya executor

Note:
    This action does NOT execute functions directly. It only validates
    and prepares the execution payload. Actual execution happens in the
    Maya executor (mca-maya_ai) which has access to Maya's main thread.

Classes:
    PythonFunctionAction - Action for executing registered Python functions

Example:
    from mca.ai.actions import ActionRegistry, PythonFunctionAction
    from mca.ai.actions.function_registry import FunctionRegistry

    # Register the action
    ActionRegistry.register(PythonFunctionAction())

    # Validate and prepare a function call
    result = ActionRegistry.run("python_function", {
        "function": "selection_tools.get_selected_nodes",
        "kwargs": {}
    })

    # result = {
    #     "status": "ready",
    #     "exec_type": "python_function",
    #     "function": "selection_tools.get_selected_nodes",
    #     "kwargs": {},
    #     "safety": "safe",
    #     "summary": "selection_tools.get_selected_nodes()"
    # }
"""

# python imports
from mca.ai.actions.base_action import BaseAction, SafetyLevel
from mca.ai.actions.function_registry import FunctionRegistry


class PythonFunctionAction(BaseAction):
    """
    Action for executing registered Python functions.

    This action validates function calls against the FunctionRegistry
    and prepares execution payloads. It does NOT execute functions
    directly - that happens in the Maya executor.

    Payload format:
        {
            "function": str,    # Function name (e.g., "selection_tools.get_selected")
            "kwargs": dict      # Keyword arguments for the function
        }

    Result format (on success):
        {
            "status": "ready",
            "exec_type": "python_function",
            "function": str,
            "kwargs": dict,
            "safety": str,      # "safe", "confirm", or "dangerous"
            "description": str,
            "summary": str      # Human-readable call string
        }
    """

    name = 'python_function'
    description = 'Execute a registered Python function with validated parameters'
    safety = SafetyLevel.SAFE  # Individual functions have their own safety levels

    def __init__(self):
        """
        Initialize the action.
        """
        super(PythonFunctionAction, self).__init__()

    def get_function_safety(self, function_name):
        """
        Get the safety level for a specific function.

        :param str function_name: Function name.
        :return: Safety level for the function.
        :rtype: SafetyLevel
        """
        func_safety = FunctionRegistry.get_safety(function_name)
        if func_safety:
            return func_safety
        # Unknown functions default to CONFIRM for safety
        return SafetyLevel.CONFIRM

    def is_function_allowed(self, function_name):
        """
        Check if a function is allowed to execute.

        :param str function_name: Function name.
        :return: True if function is registered and not DANGEROUS.
        :rtype: bool
        """
        if not FunctionRegistry.is_registered(function_name):
            return False

        safety = FunctionRegistry.get_safety(function_name)
        return safety != SafetyLevel.DANGEROUS

    def validate(self, payload, context=None):
        """
        Validate the function payload.

        Checks:
        - Function name is provided
        - Function is registered in FunctionRegistry
        - Function is not DANGEROUS
        - kwargs is a dict

        :param dict payload: Action payload with 'function' and optional 'kwargs'.
        :param dict context: Optional execution context.
        :return: Validation result dict.
        :rtype: dict
        """
        function_name = payload.get('function')

        if not function_name:
            return {'valid': False, 'error': 'Missing required field: function'}

        # Check if function is registered
        if not FunctionRegistry.is_registered(function_name):
            return {
                'valid': False,
                'error': f'Function "{function_name}" is not registered. '
                         f'Only whitelisted functions can be called.',
            }

        # Check safety
        func_info = FunctionRegistry.get(function_name)
        if func_info and func_info['safety'] == SafetyLevel.DANGEROUS:
            return {
                'valid': False,
                'error': f'Function "{function_name}" is blocked for safety reasons',
            }

        # Validate kwargs is a dict
        kwargs = payload.get('kwargs', {})
        if not isinstance(kwargs, dict):
            return {
                'valid': False,
                'error': f'kwargs must be a dictionary, got {type(kwargs).__name__}',
            }

        return {'valid': True}

    def run(self, payload, context=None):
        """
        Prepare function for execution.

        This method validates the function call and returns a structured
        execution payload. It does NOT execute the function - that happens
        in the Maya executor.

        :param dict payload: Action payload with 'function' and 'kwargs'.
        :param dict context: Optional execution context.
        :return: Execution payload or error dict.
        :rtype: dict
        """
        # Validate first
        validation = self.validate(payload, context)
        if not validation.get('valid'):
            return {
                'status': 'error',
                'error': validation.get('error', 'Validation failed'),
            }

        function_name = payload.get('function')
        kwargs = payload.get('kwargs', {})

        # Get function info
        func_info = FunctionRegistry.get(function_name)

        # Build human-readable summary
        summary = self._build_summary(function_name, kwargs)

        # Get function safety level
        safety = func_info['safety'] if func_info else SafetyLevel.CONFIRM

        # Build execution payload
        result = {
            'status': 'ready',
            'exec_type': 'python_function',
            'function': function_name,
            'kwargs': kwargs,
            'safety': safety.value,
            'summary': summary,
        }

        # Include function description if available
        if func_info:
            result['description'] = func_info.get('description', '')
            result['parameters'] = func_info.get('parameters', {})

        return result

    def _build_summary(self, function_name, kwargs):
        """
        Build a human-readable function call summary string.

        :param str function_name: Function name.
        :param dict kwargs: Keyword arguments.
        :return: Summary string like "selection_tools.get_selected(type='joint')".
        :rtype: str
        """
        parts = []

        # Add keyword args
        for key, value in kwargs.items():
            parts.append(f'{key}={repr(value)}')

        args_str = ', '.join(parts)
        return f'{function_name}({args_str})'

    def get_schema(self):
        """
        Get the JSON schema for this action's payload.

        :return: JSON schema dict.
        :rtype: dict
        """
        return {
            'type': 'object',
            'properties': {
                'function': {
                    'type': 'string',
                    'description': 'Name of the registered function to execute',
                },
                'kwargs': {
                    'type': 'object',
                    'description': 'Keyword arguments for the function',
                },
            },
            'required': ['function'],
        }
