"""
MCP servers for the MCA pipeline, and the Maya-side code they talk to.

The point of this package, stated as the problem it fixes: **an AI assistant should be able
to open Maya, work in it, and close it, with nothing else running.**

Before this, Maya's command ports were opened by the MCA Editor's plug-in - so the MCP
server could only reach a Maya that happened to have a code editor loaded in it. Close the
editor and the AI went blind, which is what happened in the middle of a session and is why
this exists.

Two halves::

    mca/mcp/maya/bootstrap.py   runs INSIDE Maya. Opens the ports, writes a session file.
    mca/mcp/maya/server.py      runs OUTSIDE. The MCP server that connects to them.

The half inside Maya is loaded by the pipeline's own Maya startup, so every Maya the
launcher starts is reachable, whatever else is or is not loaded.
"""

__version__ = '1.0.0'
