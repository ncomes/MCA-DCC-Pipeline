"""
The animation library: a catalog of clips, and where each clip's files live.

```python
from mca.common.animlib import animlib_api

animlib_api.list_clips(character='frostwind')
```

This half knows nothing about a DCC: it reads and writes the catalog, knows where a clip's
files belong, and answers questions about them. Everything that touches a Maya scene -
capturing a clip off a rig, applying one onto a rig, baking an FBX - is in
``mca.mya.tools.animlibrary``.

The pieces:

``clip``
    One clip as a record: its name, its character, its category, and up to three files.
``catalog``
    The index over every clip, one JSON file at the library root.
``projects``
    Named libraries, and which one is current.
``extract_plan``
    Planning the one-off pass that turns the depot's rig scenes into library clips. Pure
    filesystem work, so it runs in seconds and can be read before anything is opened.
``animlib_api``
    The flat API, answering ``{'ok', 'result', 'message'}`` like the asset list's.

Import the module rather than its contents.
"""
