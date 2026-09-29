# mca-mcp

MCP servers that let an AI assistant drive Maya — **including starting and closing it**, with
nothing else running.

## The problem this fixes

Maya's command ports used to be opened by the MCA Editor's Maya plug-in. So every tool that
drove Maya only worked while a *code editor* happened to be loaded in it. Close the editor and
the assistant goes blind, mid-session, with no explanation.

Opening those ports belongs to the pipeline, not to an editor. That is what
`mca/mcp/maya/bootstrap.py` does.

## The two halves

```
mca/mcp/maya/bootstrap.py    runs INSIDE Maya - opens the ports, writes a session file
mca/mcp/maya/server.py       runs OUTSIDE   - the MCP server that connects to them
mca/mcp/core/link.py         the socket transport: base64 in, result file out
mca/mcp/core/sessions.py     which Mayas are running, and on which ports
mca/mcp/core/control.py      launch, quit, execute - one implementation for every caller
```

### Inside Maya

One line in the pipeline's Maya `userSetup.py`:

```python
from mca.mcp.maya import bootstrap; bootstrap.start()
```

It opens MEL port 7001 and Python port 7002, writes
`%LOCALAPPDATA%\MCA\sessions\maya-<pid>.json`, never raises, and is safe to call twice.
`MCA_MAYA_COMMAND_PORTS=0` turns it off; `MCA_MAYA_MEL_PORT` moves it.

A command port is unauthenticated remote code execution, so it binds to localhost only.

### Outside Maya

```
python -m mca.mcp.maya.server
```

| tool | what it does |
|---|---|
| `maya_status` | which Mayas are running, and can they be reached |
| `maya_launch` | start one through the launcher, wait until it answers |
| `maya_quit` | close one — refuses on unsaved changes unless told otherwise |
| `maya_execute` | run Python in it and get back the result, the output, or the traceback |
| `maya_run_file` | the same, from a file on disk |
| `maya_scene_info` | what is open, is it modified, what is in it |
| `maya_open_scene` / `maya_save_scene` / `maya_new_scene` | the everyday scene operations |

## How the transport works, and why

- **base64 in, file out.** The script is base64-encoded before it goes down the socket, so
  quotes and backslashes cannot be mangled. The result comes back through a temp JSON file,
  because what a command port returns is whatever happened to be printed.
- **Deferred onto the main thread.** `maya.utils.executeDeferred` is the only correct way to
  touch a DCC from another thread, and it sidesteps Maya 2024's command-port crash as a side
  effect.
- **One file per call, cleaned up after.** No shared state between calls.

## Multiple Mayas

Each Maya writes a session file with its pid, version, ports and open scene, and stale files
are deleted on sight. With one Maya running, tools find it. With more than one, they refuse
and list them rather than guessing which scene to edit — pass `pid`.

Today all Mayas share ports 7001/7002, so the second one to start does not get them and says
so in its log. Per-instance ports are the next step; the resolver they would plug into is
`core/control.pick`.
