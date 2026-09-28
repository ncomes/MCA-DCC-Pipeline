"""
The MCA DCC Launcher.

In one line: work out which DCC the artist wants, make sure that DCC's Python
dependencies are installed for that exact version, build the environment the framework
needs, and start it.

The layering, and the reason for it::

    core/       No Qt, no DCC, no module-level state. Testable with plain python.
    api.py      Every operation the launcher can do, each answering ok/result/message.
    cli.py      The command line, and the entry point a desktop shortcut uses.
    ui/         PySide6 windows. They call api and nothing else.

The rule that keeps it honest: **the UI may not hold logic the API does not have.**
Anything an artist can do by clicking, a script, a test or an AI agent can do by calling -
which is also why the dependency bootstrap has exactly one implementation, reached from
every path that starts a DCC.
"""

__version__ = '3.0.0'
