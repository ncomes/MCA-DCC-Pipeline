# Running these

```
python tests/test_core.py      the transport, sessions and control - no Maya, no mcp needed
python tests/test_server.py    the MCP layer - needs the mcp package; skips without it
test_live.bat 2025             a real Maya, end to end
tests/probe.bat                which layer of the transport is silent, when one is
```

`test_live.bat` writes everything to `tests/last_run.log` as well as the console, so a run can
be read back afterwards - including by an assistant that has the repo folder but not the
machine.

`test_server.py` runs against whichever `mcp` SDK is installed and says which API it found.
That matters: the SDK changed shape at 2.0, and this server met 2.2.0 on a real machine after
being written against 1.x.
