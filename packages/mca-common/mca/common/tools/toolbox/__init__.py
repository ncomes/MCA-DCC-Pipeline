"""
MCA Toolbox: editable, version-controlled tool palettes for artists.

Current system (hosts: Maya ``ma_toolbox_ui``, Unreal ``ue_toolbox``, MotionBuilder ``mo_toolbox_ui``):

- ``toolbox_model``    plain data classes + YAML IO
- ``toolbox_library``  loads sections/toolboxes and performs every edit (source control through ``toolbox_vcs``)
- ``toolbox_runner``   runs item commands, static "broken tool" checks
- ``toolbox_api``      headless API for scripts, AI and MCP tools
- ``toolbox_items``    item types (button, slider, form...) and the UI builder form runtime
- ``toolbox_widgets``  the in-place editable toolbox widget
- ``toolbox_dialogs``  item / section dialogs and the UI builder
- ``toolbox_window``   standalone window host

``toolbox_migrate`` has not come across. It converted the legacy GUID-graph ``.tbx`` files into
these sections and toolboxes, it has been run - the sections are on disk in the new format and
there is not a ``.tbx`` file left in the depot - and it is 294 lines of code for a conversion
that cannot happen again. The depot's history has it, along with the legacy system it read
(``toolbox_data``, ``toolbox_ui``, ``toolbox_editor``, ``toolbox_prefs``), which was deleted once
all three hosts had moved over.
"""
