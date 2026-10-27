# mcaMeshTiler samples

Three setups side by side, built entirely through
`mca.mya.tools.meshtiler.meshtiler_api`:

| | target | shows |
|---|---|---|
| **1. Quads** | low-poly torus | one tile per face, conformed to the limit surface rather than the cage |
| **2. Triangles** | the same torus, triangulated | three tiles per triangle — the case the tool this replaces produced nothing for |
| **3. N-gons** | 12-sided cylinder | n-gon caps, `heightOffset` standing the plates off the surface, and four faces turned with `faceRotation` |

Each target is left in the scene as a dark see-through cage under its tiles, so
you can select it, drag a vertex, and watch the tiles follow. The tile meshes are parked
below in `tiles_source` — edit one and every copy of it changes.

The tiles carry a checker texture on purpose. Every tile lands on the same patch
of texture, so if the UVs came across each one shows the same little
checkerboard; if they did not, you get flat colour and can see that at a glance.

## Running it

**`build_sample.py` is the sample.** It works in any Maya version the plug-in has
been built for, and it doubles as the shortest honest documentation of the API —
everything in it goes through `meshtiler_api` and nothing reaches into the node
directly.

Start from an empty scene. Nothing here cleans up after a previous run, so a
second run makes a second set of everything.

**Easiest:** in Maya, `File > Open Script...` this file into a **Python** tab of
the script editor, then hit execute. That runs the whole file, which ends by
calling `build()`.

**Or, two lines pasted into a Python tab:**

```python
import sys; sys.path.append(r'<the folder this file is in>')
import build_sample; build_sample.build()
```

A bare `build()` will not work — `build` lives inside the module, so it is
`build_sample.build()` unless you ran the whole file. And if you have already
imported it once, Python will not re-read the file:

```python
import importlib, build_sample
importlib.reload(build_sample); build_sample.build()
```

Watch the script editor's output pane. Every step prints what it made
(`scales on a quad target: 112 tiles from 112 faces.`), and any failure comes
back as a message rather than a traceback, because the API is on the
`ok/result/message` contract.

## The saved scene

`mcaMeshTiler_sample_maya2025.ma` is the result of running that script, saved so
you can look without running anything.

**It is version-locked.** Maya writes the plug-in it needs into the file:

```
requires -nodeType "mcaMeshTiler" "mcaMeshTiler_maya2025" "1.0";
```

The plug-ins are version-suffixed, so that line names Maya 2025 specifically.
Open it in another version and you get "plug-in not found" and an unrecognised
node type — the same wall you hit opening `cloneToQuad/samples/sample.ma` today.

To make one for your version, run `build_sample.py` under it and save. The scene
is small and the script rebuilds it in a couple of seconds, which is why there is
one saved file rather than four.
