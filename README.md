# MCA DCC Pipeline

A rigging and animation pipeline for games, built around Maya, MotionBuilder and Unreal
Engine. Six Maya plug-ins written from the published maths, a framework of tools on top of
them, and a launcher that puts the whole thing on an artist's machine.

MIT licensed. See `LICENSE`.

## What is in here

```
packages/
  mca-launcher/     Picks a DCC, builds its environment, installs what it needs, starts it
  mca-common/       Shared layer: config, logging, Qt helpers, file and path utilities
  mca-maya/         Maya tools and the six native plug-ins
  mca-mobu/         MotionBuilder tools
  mca-ue/           Unreal Engine tools
```

Packages arrive here one at a time, each one cleaned up and tested as it lands, rather than
in one move. `mca-launcher` is first, because it is what a new machine runs before anything
else exists.

## Where dependencies live

Not in this repository. They are installed **per DCC version, with that DCC's own Python
interpreter**, into:

```
%LOCALAPPDATA%\MCA\deps\<dcc>-<version>\
```

Maya 2022 ships Python 3.7, 2024 ships 3.10, 2025 and 2026 ship 3.11, and MotionBuilder and
Unreal have their own. A wheel built for one of those does not load in another, so a single
shared folder is wrong by construction. Each folder is wiped before it is installed into, so
versions cannot stack up, and each carries a stamp recording the requirements hash and the
interpreter that filled it.

`mca-common` owns the requirements list. The launcher reads it and installs it; it never
keeps its own copy.

## Status

Under active restructuring, one package at a time. Not yet published.
