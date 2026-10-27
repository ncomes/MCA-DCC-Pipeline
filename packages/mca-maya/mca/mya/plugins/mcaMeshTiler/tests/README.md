# mcaMeshTiler tests

| file | needs | covers |
|---|---|---|
| `test_tiling.cpp` | cl.exe, **no Maya** | 51 — tile parameterisation, area scale, face-rotation wrapping, the topology hash |
| `test_node.py` | mayapy, any version | 31 — the node itself: one tile per face, the `tilesU`/`tilesV` grid, triangles and n-gons, UV sets, height, evaluation stability, topology rebuild |
| `test_api.py` | mayapy **or** an open Maya | 49 — `meshtiler_api`: the `ok/result/message` contract on every path, shader and UV transfer, the result being movable, pinned mode, rotation round trip, freeze, removal |
| `test_ui_import.py` | mayapy (needs pymel) | 8 — the window imports, `open_tool` is callable, every method a button connects to exists |
| `test_ui_attributes.py` | mayapy, any version | 7 — the widget→attribute table lifted out of the UI source and checked against a real node |
| `_test_ui_offscreen.py` | **does not run** | the full offscreen UI drive. Kept because it is correct; see below |

## Running them

```
run_tests.bat                 the C++ suite
run_python_tests.bat 2025     every test_*.py under one Maya version
```

Results go to `%TEMP%` and a summary is printed, so nothing lands in the repo.

Each suite also runs on its own: `mayapy test_node.py`. Paths are worked out from
the file's own location, so the tree can move without breaking them.

## Why `_test_ui_offscreen.py` does not run

Constructing a `QApplication` under `mayapy` hard-crashes the process
(0xC0000409). Maya's standalone init loads Qt WebEngine, which wants
`AA_ShareOpenGLContexts` and an OpenGL context the `offscreen` platform plugin
cannot provide — setting the attribute first only changes the error to "This
plugin does not support createPlatformOpenGLContext". The suite is correct; the
host is the problem. It is kept in case a later Maya or a different platform
plugin makes it runnable, and it is named with a leading underscore so the
runner skips it.

## Which Maya versions can actually run these

Uneven, for reasons that are all environment rather than code:

- **2025** — everything.
- **2026** — pure `cmds` suites only (`test_node.py`, `test_ui_attributes.py`).
  Its pymel wants Maya 2026 docs that are not installed locally.
- **2024** — mayapy crashes during startup plug-in load on a broken Bifrost
  install.
- **2022** — no Python 3.7 dependency bundle, so no `yaml` and the framework
  will not import.

The plug-in itself builds and loads on all four.

## Gotchas these suites were written around

**Append the framework's dependency bundles to `sys.path`, never insert them.**
`mca-common/.../startup/dependencies/python311` carries its own PySide6 that does
not import under mayapy, and `mca.common.pyqt.pygui` catches the `ImportError`
and hands back a stub — so every Qt call then fails as
`AttributeError: QApplication` several frames from the cause.

**An open Maya locks the `.mll` it has loaded**, so a rebuild fails with
`LNK1104`. And a plug-in cannot be unloaded while nodes of its type exist in the
scene, so `remove_tiling` or a new scene comes first.
