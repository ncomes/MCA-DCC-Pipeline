"""
Action Registry

This module provides the central registry for discovering and executing actions.

The ActionRegistry is a singleton that stores all registered actions and
provides methods for lookup and execution.

Classes:
    ActionRegistry - Central registry for action management

Usage:
    from mca.ai.actions import ActionRegistry, BaseAction

    # Register an action
    ActionRegistry.register(MyAction())

    # Get action by name
    action = ActionRegistry.get("my_action")

    # Execute action
    result = ActionRegistry.run("my_action", {"param": "value"})

    # List all actions
    actions = ActionRegistry.list_actions()
"""

# python imports
from mca.ai.actions.base_action import BaseAction, SafetyLevel


class ActionRegistry:
    """
    Central registry for action management.

    This is a singleton class - all methods are class methods that operate
    on shared state. Actions are registered once at startup and available
    throughout the application lifetime.

    Thread Safety:
        The registry is not thread-safe. Actions should be registered
        during application startup before any concurrent access.
    """

    # Shared state - all registered actions
    _actions = {}

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
    def register(cls, action):
        """
        Register an action with the registry.

        :param BaseAction action: Action instance to register.
        :raises TypeError: If action is not a BaseAction subclass.
        :raises ValueError: If action with same name already registered.

        Example:
            ActionRegistry.register(SelectAction())
        """
        if not isinstance(action, BaseAction):
            raise TypeError(f'Action must be a BaseAction subclass, got {type(action)}')

        name = action.name

        if name in cls._actions:
            if cls._logger:
                cls._logger.warning(f'Overwriting existing action: {name}')

        cls._actions[name] = action

        if cls._logger:
            cls._logger.debug(f'Registered action: {name}')

    @classmethod
    def unregister(cls, name):
        """
        Remove an action from the registry.

        :param str name: Name of the action to remove.
        :return: True if action was removed, False if not found.
        :rtype: bool
        """
        if name in cls._actions:
            del cls._actions[name]
            if cls._logger:
                cls._logger.debug(f'Unregistered action: {name}')
            return True
        return False

    @classmethod
    def get(cls, name):
        """
        Get an action by name.

        :param str name: Action name.
        :return: Action instance or None if not found.
        :rtype: BaseAction or None
        """
        return cls._actions.get(name)

    @classmethod
    def run(cls, name, payload, context=None, dry_run=False):
        """
        Execute an action by name.

        :param str name: Action name.
        :param dict payload: Action parameters.
        :param dict context: Optional execution context.
        :param bool dry_run: If True, validate but don't execute.
        :return: Result dict with status and action-specific fields.
        :rtype: dict

        Returns error dict if:
        - Action not found
        - Validation fails
        - Execution fails
        - Action is blocked by safety level

        Example:
            result = ActionRegistry.run("select", {"objects": ["pCube1"]})
            if result["status"] == "ok":
                print("Selected:", result["selected"])
        """
        action = cls.get(name)

        if not action:
            return {
                'status': 'error',
                'error': f'Unknown action: {name}',
            }

        # Check safety level
        if action.safety == SafetyLevel.DANGEROUS:
            return {
                'status': 'blocked',
                'error': f'Action "{name}" is blocked for safety reasons',
                'safety': 'dangerous',
            }

        # Validate payload
        validation = action.validate(payload, context)
        if not validation.get('valid', True):
            return {
                'status': 'error',
                'error': validation.get('error', 'Validation failed'),
            }

        # Dry run mode - return ready status without executing
        if dry_run:
            return {
                'status': 'ready',
                'action': name,
                'payload': payload,
                'summary': f'{name}({payload})',
            }

        # Execute action
        try:
            result = action.run(payload, context)
            return result

        except Exception as e:
            if cls._logger:
                cls._logger.error(f'Action "{name}" failed: {e}')

            return {
                'status': 'error',
                'error': str(e),
            }

    @classmethod
    def list_actions(cls, safety=None):
        """
        List all registered actions.

        :param SafetyLevel safety: Optional filter by safety level.
        :return: List of action metadata dicts.
        :rtype: list[dict]
        """
        result = []
        for action in cls._actions.values():
            if safety is not None and action.safety != safety:
                continue
            result.append(action.to_dict())
        return result

    @classmethod
    def list_names(cls):
        """
        Get list of all registered action names.

        :return: List of action names.
        :rtype: list[str]
        """
        return list(cls._actions.keys())

    @classmethod
    def clear(cls):
        """
        Remove all registered actions.

        Primarily used for testing.
        """
        cls._actions.clear()
        if cls._logger:
            cls._logger.debug('Cleared all actions from registry')

    @classmethod
    def get_count(cls):
        """
        Get number of registered actions.

        :return: Action count.
        :rtype: int
        """
        return len(cls._actions)
