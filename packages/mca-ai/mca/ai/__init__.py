"""
MCA AI Core Package

This is a DCC-agnostic AI brain that can be reused by Maya, Unreal, Mobu, and any other application.

It provides:
- Provider abstraction (Claude, OpenAI, etc.)
- System prompt loading and assembly
- Conversation and message routing logic
- Memory and role management
- (Future phases) action/tool protocol

This package MUST NOT depend on any DCC-specific modules (Maya, UE, etc.).
It may only import mca.common and standard libraries.

Usage:
    from mca.ai.startup import startup

    # Initialize AI Core
    state = startup.startup_init()

    # Get router for handling messages
    router = state['router']

    # Send a message
    response = router.handle_user_message("Hello, AI!")
    print(response['text'])

    # Clean shutdown
    startup.shutdown()

Version: 1.0.0
"""

__version__ = '1.0.0'
__author__ = 'Nathan Comes'

# Package root path
import os
AI_ROOT = os.path.dirname(os.path.abspath(__file__))
