"""
Action Type Definitions

This module contains type definitions and schemas for the action system.

The main types are defined in base_action.py and registry.py.
This module provides additional type aliases and constants.

Constants:
    ACTION_STATUS_OK - Success status string
    ACTION_STATUS_ERROR - Error status string
    ACTION_STATUS_READY - Validation-only ready status string
    ACTION_STATUS_BLOCKED - Safety blocked status string
"""

# Status constants for action results
ACTION_STATUS_OK = 'ok'
ACTION_STATUS_ERROR = 'error'
ACTION_STATUS_READY = 'ready'
ACTION_STATUS_BLOCKED = 'blocked'

__all__ = [
    'ACTION_STATUS_OK',
    'ACTION_STATUS_ERROR',
    'ACTION_STATUS_READY',
    'ACTION_STATUS_BLOCKED',
]
