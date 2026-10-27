"""
Base Action Class and Safety Levels

This module defines the abstract base class for all actions and the safety
classification enum.

Classes:
    SafetyLevel - Enum for action safety classification
    BaseAction - Abstract base class for all executable actions

Safety Levels:
    SAFE - Action can run without user confirmation (e.g., ls, select)
    CONFIRM - Action requires user confirmation before running (e.g., delete)
    DANGEROUS - Action is blocked by default (e.g., file, quit)

Example:
    from mca.ai.actions.base_action import BaseAction, SafetyLevel

    class SelectAction(BaseAction):
        name = "select"
        description = "Select objects in the scene"
        safety = SafetyLevel.SAFE

        def run(self, payload, context=None):
            objects = payload.get('objects', [])
            # Execute selection...
            return {"status": "ok", "selected": objects}
"""

# python imports
from enum import Enum


class SafetyLevel(Enum):
    """
    Safety classification for actions.

    Determines what level of user confirmation is required before
    an action can be executed.

    Values:
        SAFE - No confirmation needed, action is read-only or easily reversible
        CONFIRM - User must confirm before action runs (e.g., delete operations)
        DANGEROUS - Action is blocked by default (e.g., file operations, quit)
    """
    SAFE = 'safe'
    CONFIRM = 'confirm'
    DANGEROUS = 'dangerous'


class BaseAction:
    """
    Abstract base class for all executable actions.

    Subclasses must define:
    - name: Unique action identifier (string)
    - description: Human-readable description (string)
    - run(): Method that executes the action

    Optional overrides:
    - safety: Safety level (default: SAFE)
    - validate(): Pre-execution validation

    The run() method receives:
    - payload: Dict of action parameters from the AI
    - context: Optional dict with execution context (e.g., current selection)

    The run() method must return a dict with at least:
    - status: "ok", "error", or "ready" (for validation-only mode)
    - Additional fields depend on the action type
    """

    # Subclasses must override these
    name = None
    description = None

    # Default safety level
    safety = SafetyLevel.SAFE

    def __init__(self):
        """
        Initialize the action.

        Validates that required class attributes are defined.

        :raises ValueError: If name or description not defined.
        """
        if not self.name:
            raise ValueError(f'{self.__class__.__name__} must define a name attribute')
        if not self.description:
            raise ValueError(f'{self.__class__.__name__} must define a description attribute')

    def validate(self, payload, context=None):
        """
        Validate action payload before execution.

        Override this method to add custom validation logic.
        Default implementation always returns success.

        :param dict payload: Action parameters from the AI.
        :param dict context: Optional execution context.
        :return: Validation result dict with 'valid' bool and optional 'error' message.
        :rtype: dict

        Example return:
            {"valid": True}
            {"valid": False, "error": "Missing required parameter 'name'"}
        """
        return {'valid': True}

    def run(self, payload, context=None):
        """
        Execute the action.

        Subclasses must override this method to implement action logic.

        :param dict payload: Action parameters from the AI.
        :param dict context: Optional execution context.
        :return: Result dict with 'status' and action-specific fields.
        :rtype: dict
        :raises NotImplementedError: If not overridden by subclass.

        Example return:
            {"status": "ok", "result": [...], "message": "Created 3 objects"}
            {"status": "error", "error": "Command failed: ..."}
        """
        raise NotImplementedError(f'{self.__class__.__name__}.run() must be implemented')

    def get_schema(self):
        """
        Get the JSON schema for this action's payload.

        Override to provide a detailed schema for the AI to understand
        what parameters the action accepts.

        :return: JSON schema dict describing the payload format.
        :rtype: dict
        """
        return {
            'type': 'object',
            'properties': {},
            'required': [],
        }

    def to_dict(self):
        """
        Serialize action metadata to a dictionary.

        Used for exposing action info to the AI and UI.

        :return: Action metadata dict.
        :rtype: dict
        """
        return {
            'name': self.name,
            'description': self.description,
            'safety': self.safety.value,
            'schema': self.get_schema(),
        }

    def __repr__(self):
        """
        String representation for debugging.

        :return: Action name string.
        :rtype: str
        """
        return f'<{self.__class__.__name__}({self.name})>'
