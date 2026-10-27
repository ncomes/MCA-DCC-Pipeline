"""
Maya Command Action

This module provides the MayaCmdAction class that wraps maya.cmds operations.

The action validates command names and kwargs against the cmds documentation
index, then produces a structured execution payload that can be passed to
the Maya executor.

Note:
    This action does NOT execute Maya commands directly. It only validates
    and prepares the execution payload. Actual execution happens in the
    Maya executor (mca-maya_ai) which has access to maya.cmds.

Classes:
    MayaCmdAction - Action for executing maya.cmds operations

Example:
    from mca.ai.actions import ActionRegistry
    from mca.ai.actions.maya_cmd_action import MayaCmdAction

    # Register the action
    ActionRegistry.register(MayaCmdAction())

    # Validate and prepare a command
    result = ActionRegistry.run("maya_cmd", {
        "command": "polyCube",
        "kwargs": {"width": 2, "height": 5}
    })

    # result = {
    #     "status": "ready",
    #     "exec_type": "maya_cmd",
    #     "command": "polyCube",
    #     "kwargs": {"width": 2, "height": 5},
    #     "summary": "cmds.polyCube(width=2, height=5)"
    # }
"""

# python imports
from mca.ai.actions.base_action import BaseAction, SafetyLevel


# --- Safety Configuration ---
# Commands that are safe to execute without confirmation
SAFE_COMMANDS = {
    # Query/List commands
    'ls', 'listRelatives', 'listConnections', 'listAttr', 'listHistory',
    'objectType', 'nodeType', 'getAttr', 'attributeQuery',

    # Selection
    'select', 'selectMode', 'selectType', 'filterExpand',

    # Creation - Polygons
    'polyCube', 'polySphere', 'polyCylinder', 'polyCone', 'polyPlane',
    'polyTorus', 'polyPyramid', 'polyPipe', 'polyHelix', 'polyPrism',
    'polySuperShape', 'polyPlatonicSolid',

    # Creation - NURBS
    'circle', 'curve', 'nurbsPlane', 'nurbsCube', 'nurbsSphere',
    'nurbsCylinder', 'nurbsCone', 'nurbsTorus',

    # Creation - Other
    'joint', 'ikHandle', 'locator', 'spaceLocator', 'group',
    'createNode', 'shadingNode',

    # Transform
    'xform', 'move', 'rotate', 'scale', 'makeIdentity',
    'parent', 'unparent',

    # Attributes
    'setAttr', 'addAttr', 'connectAttr', 'disconnectAttr',

    # Modeling operations
    'polyExtrudeFacet', 'polyBevel', 'polySmooth', 'polyMergeVertex',
    'polySplit', 'polySubdivideFacet', 'polyCloseBorder',

    # Skinning
    'skinCluster', 'skinPercent',

    # Constraints
    'parentConstraint', 'pointConstraint', 'orientConstraint',
    'scaleConstraint', 'aimConstraint', 'poleVectorConstraint',

    # Animation
    'setKeyframe', 'currentTime', 'playbackOptions',

    # Utility
    'rename', 'duplicate', 'instance', 'mirror',
    'freeze', 'center', 'alignTool',
}

# Commands that require user confirmation before execution
CONFIRM_COMMANDS = {
    'delete', 'DeleteKeys', 'cutKey',
    'polyUnite', 'polyBoolOp',
    'undoInfo', 'undo', 'redo',
}

# Commands that are blocked for safety
DANGEROUS_COMMANDS = {
    # File operations
    'file', 'saveFile', 'openFile', 'newFile', 'referenceFile',

    # Application control
    'quit', 'exit',

    # UI destruction
    'deleteUI', 'deleteControl',

    # System commands
    'system', 'eval', 'python',

    # Scene destruction
    'clearCache', 'flushUndo',
}


class MayaCmdAction(BaseAction):
    """
    Action for executing maya.cmds operations.

    This action validates the command and kwargs against the cmds documentation
    index, checks safety classification, and produces a structured execution
    payload. It does NOT execute Maya commands directly.

    Payload format:
        {
            "command": str,     # Command name (e.g., "polyCube")
            "kwargs": dict,     # Keyword arguments for the command
            "args": list        # Optional positional arguments
        }

    Result format (on success):
        {
            "status": "ready",
            "exec_type": "maya_cmd",
            "command": str,
            "kwargs": dict,
            "summary": str      # Human-readable command string
        }
    """

    name = 'maya_cmd'
    description = 'Execute a maya.cmds command with validated parameters'
    safety = SafetyLevel.SAFE  # Individual commands have their own safety levels

    def __init__(self, cmds_index=None):
        """
        Initialize the action.

        :param MayaCmdsIndex cmds_index: Optional cmds documentation index.
                                         If not provided, validation is skipped.
        """
        super(MayaCmdAction, self).__init__()
        self._cmds_index = cmds_index

    def set_cmds_index(self, cmds_index):
        """
        Set the cmds documentation index.

        :param MayaCmdsIndex cmds_index: Documentation index instance.
        """
        self._cmds_index = cmds_index

    def get_command_safety(self, command):
        """
        Get the safety level for a specific command.

        :param str command: Command name.
        :return: Safety level for the command.
        :rtype: SafetyLevel
        """
        if command in DANGEROUS_COMMANDS:
            return SafetyLevel.DANGEROUS
        if command in CONFIRM_COMMANDS:
            return SafetyLevel.CONFIRM
        if command in SAFE_COMMANDS:
            return SafetyLevel.SAFE
        # Unknown commands default to CONFIRM for safety
        return SafetyLevel.CONFIRM

    def is_command_allowed(self, command):
        """
        Check if a command is allowed to execute.

        :param str command: Command name.
        :return: True if command is allowed.
        :rtype: bool
        """
        return command not in DANGEROUS_COMMANDS

    def validate(self, payload, context=None):
        """
        Validate the command payload.

        Checks:
        - Command name is provided
        - Command is not in the dangerous list
        - Command exists in the cmds index (if index available)

        :param dict payload: Action payload with 'command' and optional 'kwargs'.
        :param dict context: Optional execution context.
        :return: Validation result dict.
        :rtype: dict
        """
        command = payload.get('command')

        if not command:
            return {'valid': False, 'error': 'Missing required field: command'}

        # Check safety
        if command in DANGEROUS_COMMANDS:
            return {
                'valid': False,
                'error': f'Command "{command}" is blocked for safety reasons',
            }

        # Check if command exists in index (if available)
        if self._cmds_index:
            cmd_info = self._cmds_index.get(command)
            if not cmd_info:
                # Command not found, but might still be valid
                # Just warn, don't block
                pass

        return {'valid': True}

    def run(self, payload, context=None):
        """
        Prepare command for execution.

        This method validates the command and returns a structured execution
        payload. It does NOT execute the command - that happens in the
        Maya executor.

        :param dict payload: Action payload with 'command' and 'kwargs'.
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

        command = payload.get('command')
        kwargs = payload.get('kwargs', {})
        args = payload.get('args', [])

        # Build human-readable summary
        summary = self._build_summary(command, args, kwargs)

        # Get command safety level
        safety = self.get_command_safety(command)

        # Build execution payload
        result = {
            'status': 'ready',
            'exec_type': 'maya_cmd',
            'command': command,
            'kwargs': kwargs,
            'args': args,
            'summary': summary,
            'safety': safety.value,
        }

        # Include command info if available
        if self._cmds_index:
            cmd_info = self._cmds_index.get(command)
            if cmd_info:
                result['cmd_info'] = {
                    'description': cmd_info.get('description', ''),
                    'category': cmd_info.get('category', 'General'),
                    'url': cmd_info.get('url', ''),
                }

        return result

    def _build_summary(self, command, args, kwargs):
        """
        Build a human-readable command summary string.

        :param str command: Command name.
        :param list args: Positional arguments.
        :param dict kwargs: Keyword arguments.
        :return: Summary string like "cmds.polyCube(width=2, height=5)".
        :rtype: str
        """
        parts = []

        # Add positional args
        for arg in args:
            parts.append(repr(arg))

        # Add keyword args
        for key, value in kwargs.items():
            parts.append(f'{key}={repr(value)}')

        args_str = ', '.join(parts)
        return f'cmds.{command}({args_str})'

    def get_schema(self):
        """
        Get the JSON schema for this action's payload.

        :return: JSON schema dict.
        :rtype: dict
        """
        return {
            'type': 'object',
            'properties': {
                'command': {
                    'type': 'string',
                    'description': 'Name of the maya.cmds command to execute',
                },
                'kwargs': {
                    'type': 'object',
                    'description': 'Keyword arguments for the command',
                },
                'args': {
                    'type': 'array',
                    'description': 'Positional arguments for the command',
                    'items': {},
                },
            },
            'required': ['command'],
        }


# Module-level helper functions for checking command safety
def is_safe_command(command):
    """
    Check if a command is in the safe list.

    :param str command: Command name.
    :return: True if command is safe.
    :rtype: bool
    """
    return command in SAFE_COMMANDS


def is_dangerous_command(command):
    """
    Check if a command is in the dangerous list.

    :param str command: Command name.
    :return: True if command is dangerous.
    :rtype: bool
    """
    return command in DANGEROUS_COMMANDS


def get_safe_commands():
    """
    Get list of all safe commands.

    :return: Set of safe command names.
    :rtype: set
    """
    return SAFE_COMMANDS.copy()


def get_dangerous_commands():
    """
    Get list of all dangerous commands.

    :return: Set of dangerous command names.
    :rtype: set
    """
    return DANGEROUS_COMMANDS.copy()
