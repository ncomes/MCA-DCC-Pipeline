# mcaCageWrap samples

Four setups side by side, built entirely through
`mca.mya.tools.cagewrap.cagewrap_api`. Every one has a **keyed cage**, so scrubbing
frame 0 to 24 is the whole demonstration.

| | shows |
|---|---|
| **1. Bend** | A tube in a four-ring cage, swung over. The cross-section stays round and square to the bend instead of skewing - which is what carrying the cage's face normals buys. Beside it, the same shape through a plain **lattice**, to compare against. |
| **2. Thickness** | Two identical balls in identical cages, both cages grown by 1.8. `stretch` is 0 on the left and 1 on the right. The right ball scales by exactly 1.8 with the cage; the left by 1.5, because at 0 the term that carries thickness is not scaled while the position term still follows. Measured: 2.400 → 3.592 against 2.400 → 4.320. "Keeps its thickness" does not mean "does not change size" — it means it does not inflate. |
| **3. A cage the tool built** | A lumpy blob nobody modelled a cage for. `wrap` was called with no cage at all, so `cage_from_mesh` retopologised one, mirrored it to make it symmetrical, and pushed it out until the whole mesh was inside. Then the cage is twisted. |
| **4. Cloth** | A 4,941-point sheet driven by an 8-point cage - the case where the cage does the animating because the mesh is far too heavy to touch. |

Each cage is a see-through dark wireframe and is **still selectable**: click it, drag a
point, and the mesh follows. A cage the artist cannot click is a cage they cannot animate,
which is why nothing here is set to reference display.

## Running it

**`build_sample.py` is the sample.** It works in any Maya the plug-in has been built for
(2022, 2024, 2025, 2026) and doubles as the shortest honest documentation of the API:
everything in it goes through `cagewrap_api` and nothing reaches into the node directly.

Start from an empty scene. Nothing here cleans up after a previous run, so a second run
makes a second set of everything.

**Easiest:** in Maya, `File > Open Script...` this file into a **Python** tab of the script
editor and execute it. That runs the whole file, which ends by calling `build()`.

**Or** paste two lines:

```python
import sys; sys.path.append(r'<this folder>')
import build_sample; build_sample.build()
```

A bare `build()` will not work — it lives in the module. If you have run the file once
already, re-running needs a reload:

```python
import importlib, build_sample
importlib.reload(build_sample); build_sample.build()
```

**From a shell**, point `mayapy` at it; it initialises standalone itself.

## Why each group holds four things, not three

Every setup is grouped, and the group holds the mesh, the cage **and the cage's hidden
`_rest` duplicate**. That third one matters: the rest cage is the pose the bind was measured
against, so if a group moves and the rest cage is left behind at the root, the group's own
transform reads as the cage having moved - the mesh follows it on top of its own transform
and flies off.

The first saved version of this scene did exactly that in three of its four setups, and only
setup 1 looked right, because its group sits at X = 0 and never moves. `build()` now ends by
reporting every wrap and **raising** if any of them is parented apart, and `report` says so
in words if it ever happens again.

## The saved scene

`mcaCageWrap_sample_maya2025.ma` is the built result, saved from 2025. It is there so the
setups can be looked at without running anything, and so a change to the deformer can be
checked against a scene that was known good. Open it, scrub, and every number the window
reports should match what is in `claude/cage-wrap.md`.

## What to look at, if you only look at one thing

Setup 1, from the top, at frame 24. The cage's top ring has swung a long way over. Look at
the tube's cross-section where the bend is sharpest: it is still a circle, square to the
direction the tube now runs. Then look at the lattice version beside it, where the same
circle has become an ellipse leaning the way the cage leaned.

That difference is the entire reason this plug-in carries the cage's face normals as well
as its vertex positions, and it is worth 3,900 times less skew on a sheared cage - measured
in `tests/test_cage.cpp`, not estimated.
