"""
AI Core - Actions and Tool Calling

This package contains the action system for AI-triggered tool execution.

The action system provides:
- BaseAction: Abstract base class for all executable actions
- ActionRegistry: Central registry for discovering and executing actions
- FunctionRegistry: Central registry for whitelisted Python functions
- Safety classification (SAFE / CONFIRM / DANGEROUS)
- Structured command execution framework

Classes:
    BaseAction - Abstract base class for actions
    ActionRegistry - Central registry for action lookup and execution
    FunctionRegistry - Central registry for whitelisted Python functions
    SafetyLevel - Enum for action safety classification
    MayaCmdAction - Action for executing maya.cmds operations
    PythonFunctionAction - Action for executing registered Python functions

Usage:
    from mca.ai.actions import BaseAction, ActionRegistry, SafetyLevel

    # Define a custom action
    class MyAction(BaseAction):
        name = "my_action"
        description = "Does something useful"
        safety = SafetyLevel.SAFE

        def run(self, payload, context=None):
            return {"status": "ok", "result": "done"}

    # Register and execute
    ActionRegistry.register(MyAction())
    result = ActionRegistry.run("my_action", {"param": "value"})

    # Register a Python function
    from mca.ai.actions import FunctionRegistry
    FunctionRegistry.register(
        name="my_tools.my_function",
        func=my_function,
        safety=SafetyLevel.SAFE,
        description="Does something useful"
    )
"""

from mca.ai.actions.base_action import BaseAction, SafetyLevel
from mca.ai.actions.registry import ActionRegistry
from mca.ai.actions.function_registry import FunctionRegistry
from mca.ai.actions.maya_cmd_action import MayaCmdAction
from mca.ai.actions.python_function_action import PythonFunctionAction

__all__ = [
    'BaseAction',
    'ActionRegistry',
    'FunctionRegistry',
    'SafetyLevel',
    'MayaCmdAction',
    'PythonFunctionAction',
]
