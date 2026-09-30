# mca-maya

The Maya half of the pipeline. Everything here needs a running Maya; nothing in
`mca-common` does, and that is the line between the two packages.

**Being ported.** Each piece is read, brought over, cleaned and checked before the next one
starts, so what is here is finished rather than copied and marked for later. The suites run
in a real Maya - there are no fakes, because a stub that answers the way we expect is a test
of our expectations, and most of what was wrong with this code was Maya not behaving the way
the code expected.

```
tests\run_tests.bat "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
```

**1,349 checks in 20 suites** so far — 1,365 in an interactive Maya, where the windowing checks can run. `utils/`, `modifiers/`, `pyqt/` and `animation/` are done, bar one deferred half of `camera_utils`; `modeling/` bar the three modules that need `rigging/` and `face/` first; and `rigging/` has started with its leaves.

`mayapy` is a full Maya with no window: it opens scenes, builds nodes and evaluates
deformers. Run the suites with any other Python and they say they are skipping, and exit
zero — a machine without Maya is not a failure.

One thing `mayapy` cannot do is make a window. A batch Maya starts a `QGuiApplication` of its own,
Qt allows one application object per process, so a `QApplication` cannot be made and a `QWidget`
cannot be built — and building one aborts the process outright rather than raising. The suites that
make windows check everything they can without one and say so; to finish them, run them inside a
Maya that has a window:

```python
import sys
sys.path.insert(0, r'<this repository>/packages/mca-maya/tests')
import run_in_maya
run_in_maya.run('test_pyqt.py')      # or run_in_maya.run_all()
```

That puts this repository's packages ahead of whatever framework the Maya has loaded, forgets every
`mca` module already imported, and catches the suite's exit so Maya does not take it as its own.

The table is the record of what happened to each piece. Below it, a section per piece says
what was wrong with the version it replaces, which is the part worth reading before touching
any of this.

| piece | state |
|---|---|
| `mca_package.yaml`, `mca/mya/__init__.py` | ported, 19 checks — every path in the manifest pointed at a folder that has never existed |
| `modifiers/` | ported, 62 checks — the contexts hold the behaviour, the decorators are one line each |
| `utils/naming.py`, `utils/namespace.py` | ported, 84 checks |
| `utils/maya_utils.py`, `utils/plugins.py`, `utils/display_layers.py`, `utils/constraint.py` | ported, 65 checks |
| `utils/optionvars.py` | ported, 43 checks — 269 lines to 235, and the metaclass is gone |
| `utils/dag.py` | ported, 58 checks — one function looped forever, another raised on any node with a shape |
| `utils/om/` | ported, 133 checks — every transform attribute serialized with `'type': None` |
| `utils/attr_utils.py` | ported, 146 checks — an integer attribute could not be created at all |
| `utils/groups.py` | ported, 30 checks |
| `utils/node_util.py`, `utils/ma_fileio.py`, `utils/textures.py` | ported, 68 checks — rebuilding a compound attribute always failed |
| `utils/material_utils.py` | ported, 61 checks — three ways to crash the shader build |
| `utils/scene_utils.py` | ported, 49 checks — backups went to a hard-coded `C:\export_backup` |
| `animation/time_utils.py`, `utils/fbx_utils.py` | ported, 57 checks — a real FBX round trip; 506 lines to 289 |
| `utils/uvpin_utils.py` | ported, 56 checks — `is_pin_valid` always answered True |
| `utils/events.py` | ported, 55 checks — 661 lines to 427; pausing any of thirteen events was a TypeError |
| `utils/camera_utils.py` → `utils/playblast.py` | half ported, 51 checks — the ubercam half is a cinematics tool, see below |
| `pyqt/` | ported, 60 checks — the window class had its event handling written and none of it connected |
| `animation/` — `keyframes.py`, `baking.py`, `anim_curves.py`, `anim_layers.py` | ported, 93 checks — baking without rotation zeroed every static rotation |
| `modeling/` — `vert_utils.py`, `surface.py`, `geometry.py`, `follicle.py`, `blendshape_model.py` | ported, 104 checks — the closest point on a surface was answered with a position, not a parameter |
| `modeling/rivets.py`, `modeling/face_model.py`, `modeling/blendshape_node.py` | waiting on `rigging/` and `face/` |
| `rigging/matrix_nodes.py`, `rigging/ik_utils.py`, `rigging/space_switch_rig.py` | ported, 71 checks — building a space switch moved the control to its parent's origin |
| `utils/ma_maths.py` | **dropped** — see below |
| `utils/locator_utils.py`, `utils/nurbs.py` | **dropped** — see below |
| `tools/_deprecated/`, `cinematics/tools/_deprecated/` | **dropped** — see below |
| `cinematics/CinematicsArchive/` | **dropped** — see below |

## The package manifest

Every path `mca_package.yaml` set pointed at `{self}/mca.mya/...` — with a dot where the
folder separator belongs. There has never been a folder called `mca.mya`, so
`MCA_MAYA_BASE_PATH`, `MCA_MAYA_CONFIGS_PATH`, `MCA_MAYA_TOOLS_PATH` and every entry in
`MCA_MAYA_PATHS` named somewhere that was not there, in every Maya session, for as long as
the file has existed. Nothing reported it. The manifest reader in `mca-common` now checks
each entry against the disk and says which ones are missing, which is how this surfaced.

`mca/mya/__init__.py` had the same shape of problem in miniature: it declared `MAYA_PATH`
and `MAYA_TOP_ROOT` as *the same value*, and the start-up code used them as though they
meant different folders. `MAYA_MCA_PACKAGE` joined `'../../mca_package.yaml'` without
normalising. One name each now, spelled once.

## `modifiers/` — borrow a piece of scene state, give it back

```python
from mca.mya.modifiers import contexts, ma_decorators

with contexts.maintained_selection_context():
    ...

@ma_decorators.undo_decorator
def build_something():
    ...
```

`contexts.py` holds the behaviour. `ma_decorators.py` is the same list spelled as
decorators, each one a single line that enters the matching context — so there is one
implementation of each piece of save-and-restore instead of two that drift apart.

What was wrong:

- **`unlock_node_context` raised a string.** `raise ('Unable to unlock a referenced node:
  ...')` is `TypeError: exceptions must derive from BaseException` in Python 3. The one case
  the function existed to report was the one case it could not report. Nothing called it;
  it is gone.
- **Setup outside the `try`.** Half the contexts and decorators changed the scene *before*
  entering the block that would change it back, so a failure part way through the setup left
  it changed. The display-layer and animation-layer versions did this while looping over
  nodes, which is exactly where a failure is likely.
- **`keep_namespace_decorator` restored the wrong namespace.** It read
  `namespaceInfo(cur=True)`, which answers `'rig'` for `':char:rig'`, and worked around it by
  setting `':'` first — which only helps when the original was a direct child of the root.
  From anywhere deeper it either landed in the wrong namespace or failed. It reads the
  absolute name now, and there is a check for the nested case.
- **`undo_decorator` threw the exception away.** It caught the failure and re-raised
  `Exception(traceback.format_exc())`, replacing the real exception type with a bare
  `Exception` carrying the traceback as its *message*. Callers could no longer catch what
  they meant to catch, and the traceback the user saw pointed at the decorator rather than at
  the failure. Two checks pin this.
- **`try: ... except Exception: raise` everywhere.** Every decorator was wrapped in it, some
  of them three times, nested. It does nothing at all, and it was roughly a third of the
  file.
- **Dead entries.** `repeat_static_command_decorator` built the MEL for Maya's "repeat last"
  by appending each argument *twice* — once bare, once quoted — so the command it registered
  was a syntax error; nothing called it. `ignore_prompts_decorator` and `viewport_off` had no
  callers either, and `viewport_off` branched on `getApplicationVersionAsFloat() >= 2016`,
  true of every Maya the pipeline supports for a decade. `no_panel_refresh_context`,
  `namespace_context`, `unlock_attribute_context` and `disable_undo_context`'s original form
  had no callers. Gone, except `disable_undo_context`, which now backs
  `not_undoable_decorator`.

591 lines became 370.

One thing the suite cannot check in `mayapy`: batch Maya pins cycle-check evaluation off and
will not turn it on, so `disable_cycle_check_warnings_context` is checked against the
contract — off inside, and whatever it was on the way out — rather than against a particular
value.

## What was dropped

- **`utils/ma_maths.py`** (519 lines). Nothing in the pipeline imports it — not one module.
  It was a copy of a matrix-to-euler block that exists in several open rigging libraries,
  and it had been mis-wired in the copying: the flat-matrix `to_euler_*` functions called
  `pymaths.is_equal(value, 1.0, 2)`, where the third argument used to mean "round to two
  decimals" and now means a *tolerance of 2.0* — which would make every gimbal test true.
  Maya's own `MTransformationMatrix.rotation()` does this correctly, in C++.
- **`utils/locator_utils.py`** (83 lines) and **`utils/nurbs.py`** (25). No importers
  anywhere.
- **`tools/_deprecated/`** (7,498 lines, 26 files), **`cinematics/tools/_deprecated/`** (441,
  1 file) and **`cinematics/CinematicsArchive/`** (3,450, 35 files). Nothing imports any of
  them, and the folder names say what they are.

## `utils/naming.py` — taking a node name apart

A Maya node name is three things joined together: a DAG path, a namespace and a base name.
Most of the pipeline's bugs with names come from a function that handles one of the three
being handed all three, so these say which part they answer for.

What was wrong:

- **`remove_illegal_characters` returned an empty string for any name with a leading or
  trailing space.** It recursed to strip the space and then threw the recursion's result
  away, falling through to a bare `return ''`. `make_maya_safe_name` is built on it, so
  `' head_geo'` became `''` and the caller named a node after nothing.
- **It also removed no illegal characters at all.** Despite its name and its docstring, it
  only ever handled the space. A dash, a dot or a slash went through untouched, and Maya
  either rejected the name or silently changed it.
- **`get_node_name_parts` joined the DAG path with nothing.** `'|'.join` was written
  `''.join`, so `'grpA|grpB|pSphere1'` came back with a long prefix of `'grpAgrpB'`. Its own
  docstring showed the right answer two lines above the line that got it wrong.
- **`get_unique_dagname` lost the padding.** It stripped every trailing digit and appended a
  count, so `arm_01` became `arm_2`, and `spine_02_ctrl` — digits in the middle — became a
  mess. It counts from the trailing number now and keeps its width.

## `utils/namespace.py` — keeping two copies of a rig apart

- **Every listing answered relative to wherever the caller was standing.**
  `cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True)` lists what is under the
  *current* namespace, and answers `None` when there is nothing, so `get_all_namespaces()`
  and `delete_empty_namespaces()` gave a different answer depending on which namespace
  happened to be current. `camera_utils` asks `'MCAUberCam' in namespace.get_all_namespaces()`
  before cleaning up its temporary camera namespace — that was False, and the clean-up
  skipped, any time the scene was left standing inside a namespace. Both ask the root
  explicitly now.
- **`get_all_namespaces` edited the caller's list.** Given an `exclude_list` it called
  `exclude_list.extend(DEFAULT_NAMESPACES)` on the list it was handed, so a caller keeping
  its exclusions in a constant got a longer constant on every call.
- **`get_namespace` could not do what its arguments said.** It appended `':'` to the node
  name and asked whether *that* was an existing namespace, so `check_node=True` checked a
  namespace rather than a node and answered `''` for any real node name. Every caller in the
  pipeline passes `check_node=False`, the only setting that worked. The argument is gone.
- **Three functions had a bare `except:`.** `purge_namespace` reported every failure as
  "namespace does not exist", whatever had gone wrong, and `move_node_to_namespace`'s
  `except: pass` meant a rename that failed — locked node, referenced node, name clash —
  looked exactly like one that worked. Callers drive it through `map()` over whole
  skeletons, so a partial move went unnoticed. Both answer with a bool now.

## `utils/maya_utils.py`, `utils/plugins.py`

- **`add_trusted_plugin_location_path` raised on a fresh Maya profile.**
  `optionVar(query='SafeModeAllowedlistPaths')` answers `0` — the integer — for a variable
  that has never been written, and the next line did `path in 0`: `TypeError: argument of
  type 'int' is not iterable`. The plugin loader calls this before every plugin it loads.
- `get_version` was `int(pm.about(version=True))`, and Maya's version string is not always a
  number: a preview release answers `'2025 Preview'` and a service pack `'2019.3'`. It reads
  the API version, which is an integer by definition.
- **`delete_nodes_of_type` had a guard that could never fire.** It meant to protect
  `hyperGraphLayout` with `if n in ('hyperGraphLayout',)`, where `n` is a PyNode and the
  tuple holds a string — never equal — so the node it meant to protect was deleted like any
  other.
- `unload_plugin` answered False for a plugin that was not loaded, which is the state the
  caller asked for, and `load_plugin` logged the reason it failed only when `quiet` was
  False — and `quiet` defaults to True.
- `get_float_version` existed in both modules, `mel.eval('getApplicationVersionAsFloat')`
  each time, and nothing called either. Dropping them takes `maya.mel` out of both.

One thing the suite cannot check in `mayapy`: `SafeModeAllowedlistPaths` is read-only in a
batch Maya — it reports as existing, answers with an empty list, refuses
`stringValueAppend` and survives `optionVar(remove=)`. The logic is checked against a
variable of our own, and the real call is a no-op in batch.

## `utils/display_layers.py`, `utils/constraint.py`

- **`get_constraint_targets` dropped every joint.** It filtered with `isinstance(x,
  pm.nt.Transform) and pm.nodeType(x) == 'transform'`. The second half was there for a real
  reason — a constraint's `target` array is wired back to the constraint node, which is also
  a transform — but it threw out the joints with it, and the pipeline's animation controls
  *are* joints. The two callers that ask "what is driving this constraint" in order to find a
  flag or a bake helper got an empty list whenever the answer was a joint, which is most of
  the time.
- **It also scrambled the order.** `list(set(...))` has no order, and `rig_component` takes
  `get_first_in_list` of the result to decide the constraint's primary target — so which
  target that was changed between runs on the same rig.
- **An axis that was settable, unlocked, but already driven fell out of the skip list
  entirely.** `constraint_safe_attrs` had no `else` for that case, so it returned two entries
  instead of three, and Maya reads a short skip list as permission to constrain the missing
  axis. That is the cycle the function exists to prevent.
- `get_display_layers` kept only the first layer per node and could return the same layer
  many times: a call over a rig's forty flags returned forty entries naming two or three
  layers. `remove_objects_from_layers` was written with pymel's `//` operator and said
  nothing about the nodes it failed to move.

## `utils/optionvars.py` — what Maya remembers between sessions

- **`load_from_file` was Python 2.** `json_data.iteritems()` raises `AttributeError` in
  every Maya the pipeline supports. Nothing called it; it is gone with `save_to_file`.
- **The duplicate-name check could never find a duplicate.** `inspect_all` built its set
  with `all_registered_variable_names.union(set(used))` and threw the result away — `union`
  returns a new set. The set stayed empty, so the check that existed to catch two tools
  sharing an option variable name reported success every time.
- **The defaults were shared between subclasses.** `_option_var_defaults` and friends were
  mutable class attributes on the base, so every subclass wrote into the same dictionary
  keyed by the bare attribute name, and two tools with a same-named option variable got each
  other's default. The properties are built per subclass, at class definition, instead of by
  rewriting the class on every instantiation.
- **A list came back wrapped in a tuple.** `pm.optionVar[name] = ['one', 'two']` stores
  something that reads back as `[('one', 'two')]`, so the second element of any list-valued
  option variable was unreachable.
- **A bool came back as `1`.** Maya has no boolean option variable. Values now come back as
  the type of the declared default.
- The registry had no callers at all — not `reset_all`, not `inspect_all`, not
  `register_mca_option_var` — and its `__getattr__` recursed without end if anything reached
  it before `__init__` had run. Gone, and with it the metaclass and
  `decorators.add_metaclass`, which no longer exists in `mca-common`.

A note for when the callers are ported: `namespace.get_namespace` no longer takes
`check_node`, and five modules pass it. `camera_utils`, `cine_file_utils`, `shot_utils`,
`scene_manager_tool` and `rig_utils` each need the argument dropped.

## `utils/dag.py` — walking the hierarchy

- **`get_between_nodes` looped forever** when the two nodes were not in the same hierarchy.
  It walked up from `last` looking for `first`; when it ran off the top of the DAG
  `current_node` became `None`, the loop condition `first != current_node` stayed true, and
  the body kept appending `None`. It logged a warning and then hung, growing a list of `None`
  until Maya ran out of memory. Twenty-one places in the pipeline call it.
- **`_get_deepest_child` raised on any node with a shape.** Its guard was a bare `return` —
  `None`, not the two values its caller unpacks — and it recursed into `getChildren()` with no
  filter, so a transform's own shape node went in and `child_node, child_depth = ...` failed
  with `TypeError: cannot unpack non-sequence NoneType`. The function exists to find the end
  of a joint chain, and the pipeline's animation controls are joints with curve shapes on
  them, so this was most calls.
- **`set_node_color` raised in a batch Maya** whenever it was given an outliner colour. It
  finished the colouring and then called `mel.eval('AEdagNodeCommonRefreshOutliners();')`
  unconditionally, and that procedure belongs to Maya's attribute editor scripts, which a
  headless Maya never loads. Every batch build or export that coloured an outliner entry
  stopped there.
- `get_ordered_hierarchy` and `get_children_in_order` were two functions for one question,
  with different argument names and different answers about the root; nothing called the
  first. `create_line_between` was a second copy of `rig_utils.create_line_between`, and the
  three callers all use that one — dropping it takes this module's import of
  `mca.mya.deformations.cluster` with it, which is what made a leaf utility depend on the
  deformation code.

`set_node_color` is kept even though nothing calls it: `frag_rig` and four other modules set
`overrideEnabled` and the colour attributes by hand, and should be rewired to it when they are
ported.

## `utils/om/` — the API layer

Maya describes an attribute's type three incompatible ways: the API splits it across
`MFnNumericAttribute`, `MFnUnitAttribute` and `MFnTypedAttribute`, each with its own
enumeration; `addAttr` wants a string and a different flag depending on which; and those
strings are not what `getAttr(type=True)` answers with. `attributetypes.py` gives each type one
number of its own and holds the maps between them. It is the foundation under flag files and
rig data, and it was wrong in a way that shows up in every file the pipeline has written.

- **Every transform attribute serialized with `'type': None`.**
  `maya_unit_type_to_internal_type` looked its argument up in `_MAYA_TYPE_FROM_TYPE`, keyed by
  *string* names, rather than in `_MAYA_UNIT_TYPE_TO_INTERNAL_TYPE`, keyed by the unit
  enumeration it is handed — a table that existed and that nothing ever read. A transform's
  `translate` is a distance and its `rotate` is an angle, both unit attributes, so the type of
  the most commonly serialized attributes in the pipeline was missing from every flag file and
  every piece of rig data written since.
- **An angle translated to `'angle'`, which Maya does not accept.** `addAttr` answers "Type
  specified for new attribute is unknown" and pymel's `type=` answers "type not supported".
  The string is `'doubleAngle'`. An angle attribute could be read but never rebuilt.
- **A float array translated to `'fltMatrix'`** — a float *matrix*, and an `attributeType`
  where the attribute needs a `dataType`. Rebuilding one made a matrix attribute.
- **Nine types had no translation at all**: distance, int, and every array but the float one,
  so `om_type_to_pymel_type` answered `None` and the caller passed `None` to `addAttr`.
- The mapping now has a check per entry that builds the attribute in a real Maya and confirms
  Maya takes the name — which is how the three wrong ones and the nine missing ones were
  found. Three types are deliberately left with no name, because Maya has none that `addAttr`
  takes: a memory address, a matrix array, and four doubles (Maya stops at three components,
  and answering `'double3'` would quietly build an attribute one component short).
- `maya_type_from_api_type` was documented to take an integer and looked it up in a table
  keyed by strings, so it answered `(None, None)` for every call. Nothing called it, nor
  `api_type_from_pymel_type`, nor used `MAYA_NUMERIC_MULTI_TYPES`. Gone with the two tables
  behind them. `_TYPE_TO_STRING` was a hand-written list of the constants' own names, 38 lines
  and one edit from disagreeing with them; it is built from them.
- **`om2_change_curve_start_time` could not do what it documented.** Called with no offset —
  "if no shift length is given it will zero the animation" — it reached `if offset > 0` with
  `offset` still `None`: `TypeError` in Python 3. The whole body sat inside a bare `except:`,
  so the call returned quietly having moved nothing. It also built an `om2.MDGContext(mtime)`
  and threw it away. **`get_om2_keyframe_range_from_scene` read only rotation curves** —
  `kAnimCurveTimeToAngular` and nothing else — so a scene animated in translation reported no
  animation. Those two, `get_om2_keyframes_from_pynode_list` (which answered a tuple where it
  documented a list) and `pynode_list_to_om2_selection_list` had no callers; they are gone,
  and with them `om_utils`' imports of `OpenMayaAnim` and `ma_decorators`.
- `serialize_plug`'s `optimize` pass popped `min`, `max`, `softMin` and `softMax`, none of
  which it ever sets — `attr_utils.serialize_attribute` adds the limits *after* this returns,
  so those four pops could not fire and the limits are written whether set or not. That is for
  `attr_utils` to fix, and is noted there.
- `get_enum_names` had a bare `except Exception: pass` around the one call in it that can
  fail, so an enumeration numbered with a gap silently lost its names.
- `MFnFloatArrayData` is still missing from OpenMaya 2.0 in Maya 2025, so a float array is
  read as doubles. The comment saying so was a `TODO`; it is the answer, not a task, and there
  is a check that will tell us if a future Maya adds it.

## `utils/attr_utils.py` — locking, unlocking, and putting data on a node

The last of those is how the pipeline stores almost everything it knows about a rig: a FRAG
node is a network node covered in attributes, and `set_compound_attribute_groups` is what puts
them there. So the type guessing in this module decides the shape of the data on every rig in
the project.

- **An integer attribute could not be created at all.** `MAYA_TYPE_DICT` mapped `int` to the
  Python type `int` rather than to a Maya type name — every other entry is a string — so
  `addAttr(attributeType=<class 'int'>)` is what a whole number produced. Any property whose
  value was a whole number failed.
- **Six log messages were written as bare string expressions.** `'An incoming data type does
  not have a register in the MAYA_TYPE_DICT...'.format(...)` on a line of its own builds a
  string and throws it away. So both places that noticed an unknown data type, the one that
  noticed a non-string dictionary key, and the two that noticed a node with no message
  attribute all reported nothing — and the data quietly came out wrong.
- **`purge_user_defined_attrs` stopped at the first node that had nothing to purge.** The
  `return` for that case sat inside the loop over nodes, so purging a selection usually purged
  one node of it, and answered `None` rather than a list.
- **`lock_all_keyable_attrs`' `allow_visibility` did nothing.** The test compared a
  `pm.Attribute` against the string `'<node>.v'`, which is never equal, so the first half of
  the `or` was always true and visibility was locked whatever the caller asked.
- **`get_all_objects_with_attr` searched in namespaces that do not exist.** Its search string
  was `f'{ns[1:]}:*.{attr_name}'` — dropping the first character of every namespace name, so
  `char` was searched for as `har`. It never found anything outside the root namespace.
- **`invert_attribute` wrote to whatever was selected.** Five of its `setAttr` calls named the
  attribute relatively — `pm.setAttr('.min', ...)`, with no node, which means "the current
  selection". It worked only because `createNode` leaves its node selected, and would have
  written its values onto the wrong node the moment anything touched the selection first.
- **`get_compound_attr_name_as_attribute` returned a class on failure** — the literal
  `pm.nt.General.Attribute`, which is not a name that exists, so the failure path raised
  `AttributeError` instead of reporting the missing attribute.
- **`set_limits` treated a limit of zero as no limit.** It decided whether to lock an axis with
  `if not any(limit_point[0])`, and `any((0, 0))` is False, so an axis deliberately pinned at
  zero was locked and hidden as though no limit had been asked for.
- **`set_compound_attribute_groups`' list branch tested the wrong variable.** Inside the loop
  over a list's values it asked `isinstance(property_value, pm.Attribute)` — the whole list —
  which is never an Attribute, so that branch never ran.
- **`get_enum_index` raised for any enumeration whose names are not lower case.** It tested
  membership with the string it was given and then looked up the index of
  `enum_string.lower()`, so `'Blue'` passed the test and then failed with `ValueError`. No
  callers; gone, with `get_indices`, `lock_and_hide_object_attrs` and
  `create_message_compound_attr` — the last of which also had an inverted test that meant its
  alias was never set.
- `add_limits_for_transform`'s two parameters were named `..._loc` and documented as
  `..._lock`, and it called `attr.lock(True)`, where pymel's `lock` takes `checkReference` —
  so the True was asking Maya to raise if the attribute belonged to a referenced node, which
  is not what the docstring says it does.
- Four helpers only this module calls are private now: the reset safety check, the
  compound-attribute lookup, the compound disconnect, and the limit-attribute builder. The
  type-guessing block that `set_attribute` and `set_compound_attribute_groups` each carried a
  copy of is one function.

One thing this cannot fix on its own: `serialize_attribute` adds `min`, `max`, `softMin` and
`softMax` *after* `om_plug.serialize_plug` has returned, which is why that function's
`optimize` pass could never drop them. They are dropped here instead when they are not set, so
`optimize` now means what it says — but data written before this change has all four keys
present and holding `None`.

## `utils/groups.py` — the transform that holds a control's offset

A rig control has to be in the right place in the world and read zero in the channel box, and
those are only compatible if something above it holds the offset.

- **`create_aligned_parent_group`'s docstring promised a check it did not have.** "If an align
  transform already exists for the object then return it" — there was no such check anywhere in
  the function. It made a new group every time, so calling it twice on one control left two
  groups stacked with the second holding nothing.
- **`transform_scale` divided by the numbers it was handed** without looking, so a scale of
  zero on any axis was a `ZeroDivisionError` from inside a rig build.
- `create_aligned_child_group` had no docstring and no callers.

## `utils/node_util.py` — rebuilding an attribute from data

This is the other half of `attr_utils.serialize_attribute`: the part that takes the dictionary
and makes the attribute again. `skel_utils` uses it to rebuild a skeleton's user attributes, so
what it cannot rebuild is data that cannot come back.

- **Rebuilding a compound attribute always failed.** `add_attribute` handed the job to
  `attr_utils.add_compound_attribute`, and there is no such function — not in `attr_utils`, not
  anywhere in the pipeline. `AttributeError`, every time. Any skeleton carrying a compound user
  attribute could not be rebuilt. The compound is built here now, with its children added
  before any of them is set up, because Maya does not finish making a compound until it has as
  many children as it was promised: `hasAttr` answers False for every child but the last.
- **A type of `0` was thrown away.** The type was read as `kwargs.pop('type') or
  kwargs.pop('attrType') or kwargs.pop('attr_type')`, and `0` is falsy — so
  `type=attributetypes.kMFnNumericBoolean`, which *is* `0`, fell through to `None` and Maya made
  a double. Every boolean attribute rebuilt by number came back as a float.
- **A minimum or maximum was never applied.** They were deliberately left out of the `addAttr`
  call and set afterwards with pymel's `setMin` and `setMax` — and those do nothing at all on a
  dynamic attribute: `setMin(0.0)` followed by `getMin()` answers `None`. The limits go in with
  the attribute now.
- **The default value was never set.** `set_attribute_info_from_dict`'s own code reads `if
  default is not None: pass`, followed by eight commented-out lines. The docstring and the data
  format both describe a `default` key; nothing was ever done with it.
- **An enumeration's fields came back in a random order.** `enumName` was built with
  `list(set(...))`, which has no order, so an attribute rebuilt from data had its choices
  shuffled — and every index stored against it then meant something else.
- **`is_empty`'s guard on Maya's own nodes could never fire.** `if node in default_nodes`
  compares a PyNode against a list of strings, so `initialShadingGroup`, `defaultLightSet` and
  the two configuration script nodes were not protected at all — and `scene_utils` uses this
  function to decide what to delete during a scene clean-up.
- Six functions had no callers: `match_translation`, `match_rotation`, `reset_transform`,
  `rbf_retarget`, `center_obj` and `orient_obj_to_obj`, about two hundred lines. Dropping
  `rbf_retarget` also takes this module's imports of `mca.mya.plugins.loader` and
  `mca.mya.utils.material_utils` with it — and that second one is what made `node_util` and
  `material_utils` import each other.

## `utils/ma_fileio.py`, `utils/textures.py`

- **One function named three different source control systems.** `touch_and_checkout_cmd`'s
  docstring said "Attempts to check out the file in plastic", the menu entry calling it said
  "SVN Check Out", and the icon beside that entry was `p4v.png`. The studio uses Perforce.
  Source control is behind `mca.common.sourcecontrol` now, so there is one name for it and
  nothing here has to know which one is in use.
- **`remove_overlay_textures` could not find the overlays it had made** in any scene where the
  meshes were in a namespace — which is every referenced or imported asset — because it searches
  with `attr_utils.get_all_objects_with_attr`, and that was looking in namespaces that do not
  exist. It also indexed the layered texture's input without checking there was one, so an
  overlay whose original colour node had since been deleted raised `IndexError` part way
  through and left every overlay after it in place.
- **Taking an overlay off a shader with a plain colour lost the colour.** The overlay needs a
  node to layer over, so a flat colour is turned into a checker with both colours the same; when
  the overlay came off, that stand-in was deleted — and Maya leaves an attribute at its
  *default* when the node driving it is deleted, not at the value it held before it was
  connected. A shader that had been 0.2, 0.4, 0.6 came back mid-grey.

## `utils/material_utils.py` — the viewport shader built from an asset's maps

Given any one of an asset's texture maps, the rest are found in the same folder by their suffix
and wired onto a blinn. It is deliberately a blinn: it has to draw in Maya's own viewport, on
every artist's machine, with no plugin loaded.

- **A material with a packed metal/rough/ambient map and no diffuse crashed twice.** `build`
  reads `use_alpha` in the packed-map branch, and that name is only ever assigned inside the
  diffuse and mask branches — `UnboundLocalError`. The line after it calls
  `create_texture(self.diffuse_path)` with that path still `None`, which is a `TypeError` in
  `os.path.basename`.
- **A texture folder holding only a normal map crashed as well**: neither branch runs, so
  `self.material_node` is still `None` when the normal branch calls
  `self.material_node.disconnectAttr('normalCamera')`.
- **`create_basic_blinn` tested the wrong attribute.** Three checks in a row, and the third reads
  `if not material_node.specularRollOff.connections(): material_node.diffuse.set(1.0)` — the
  second check's condition with the third's action, so `diffuse` was set according to whether
  `specularRollOff` was connected.
- **The deferred UV tile preview was not deferred.**
  `pm.evalDeferred(pm.mel.generateUvTilePreview(name))` calls the MEL procedure *now* and hands
  its result to `evalDeferred` — the opposite of what the comment beside it says it is for, and
  the comment is right. It is also a procedure a batch Maya does not have, so it raised there.
- **`replace_material` abandoned its own clean-up**: a `return` inside the loop over shading
  groups where a `continue` was meant, so the `pm.delete` at the end never ran and the old
  material and its shading groups stayed in the scene.
- **`get_object_material_face_dict`'s error path was itself an error**:
  `logger.warning(log_string='...')` — `warning` has no `log_string` parameter, so a shading
  engine with no surface material raised `TypeError` from inside the handler meant to report it.
  It had one caller, `node_util.rbf_retarget`, which has none of its own; both are gone, and with
  them this module's imports of `OpenMaya` and `om_utils`.
- `consolidate_materials` declared a `things_to_delete` list and never used it; a remap node's
  `outputMax` was set twice in a row to two different values; `DefaultMaterial` kept its found
  maps on the *class* rather than the instance, and reached for the hardware rendering globals
  node without checking there was one.

## `utils/scene_utils.py` — clearing the rubbish out of a scene

- **`backup_scene` wrote to a hard-coded `C:\export_backup`.** Not under the project, not under
  the user's preferences, not configurable, and not a path that exists on a machine that is not
  Windows.
- **`backup_scene` cleaned the scene before saving it.** A function called "backup" that modifies
  the thing it is backing up is a poor trade: the file on disk is a *cleaned* copy, and the scene
  the artist is looking at has had nodes deleted out from under it. That is a separate argument
  now, off by default.
- **`clean_imported_nodes` broke every name it answered with.** `node.replace('|', '')` strips
  the separators out of a DAG path, so `grpA|grpB|pSphere1` came back as `grpAgrpBpSphere1` — a
  name for nothing. It also used the *old* Maya API, `maya.OpenMaya`, alone among the modules in
  this package, and its index bookkeeping assumed one name added to a selection list is one entry
  in it.
- **`delete_garbage`'s skip list could never match**: `connection_node in
  ['characterPartition']` compares a PyNode against a string, so the one node it meant to protect
  was deleted like any other. Its Maya-version check was dead, and inside it was a second dead
  check — `if 'hyperGraphLayout' in straight_delete_types: remove(...)` — on a list built two
  lines above from two literals, neither of which is that.
- **Two functions were second copies of other modules' work.** `delete_empty_namespaces` and
  `delete_empty_display_layers` did the same jobs as the ones in `utils/namespace.py` and
  `utils/display_layers.py`, differently. They call those now.
- `delete_unused_shader_nodes` drives a Hypershade menu item through MEL, which a batch Maya has
  not loaded — it says so and returns rather than raising.

## `animation/time_utils.py`, `utils/fbx_utils.py`

Maya has four different "the range" at once — the visible timeline, the scene's own range, the
part a user dragged out, and whatever frames carry keys — and almost every bug in a baking or
exporting tool comes from picking the wrong one. `get_times` asks for each in turn, most specific
first, and now says in the log which one it settled on, because "it baked the wrong range" is
otherwise very hard to account for after the fact.

- **Importing `time_utils` loaded a plugin and a piece of Maya's interface.** Two lines at module
  level: `from maya.plugin.timeSliderBookmark.timeSliderBookmark import createBookmark` and
  `plugins.load_plugin('timeSliderBookmark')`. Anything that imported it — and the FBX exporter
  does — paid for a plugin load, in a batch Maya as much as an interactive one.
- **`set_timeline_range` could not be given frame 0.** `if not scene_start_time`, and `0` is
  falsy, so a scene meant to start at zero got the visible range's start instead.
- **`get_keyframe_range_from_nodes` answered "no keys" for a single node**, reading its keys only
  `if isinstance(node_list, list)`.
- **`import_fbx` raised a string.** `raise f'File not found at: {fbx_path}'` is `TypeError:
  exceptions must derive from BaseException` — so the one case it checked for reported the wrong
  thing and threw its own message away.
- **The MEL builder rewrote the caller's own text.** Maya's FBX plugin has no Python interface, so
  every call goes out as MEL, and `_FBXCmd` converted Python's `True`/`False` to MEL's by running
  `str.replace` over the whole finished command — arguments included. Exporting a clip named
  `TrueGrit` wrote `trueGrit` into the file. There is a check for exactly that.
- **Ninety-odd one-line wrappers, three of them used.** Every command in the FBX plugin had a
  function here whether the pipeline called it or not. Seventeen are called, one of those from
  outside the module; the rest are reachable through `fbx_command`, which is the same mechanism
  under a name that says so.
- `load_fbx` and `assert_property` checked their results with `assert`, which Python removes
  entirely under `-O`, and neither had a caller.

The FBX half of the suite is a real round trip: a mesh and an animated transform written out
through Maya's own plugin, read back into an empty scene, and checked for their positions, their
keys and their namespace.

## `utils/uvpin_utils.py`

This one came over almost as it was. It is recent work — its constants are named, its side effects
are written down, and its pin coordinates are restored in `finally` — and there was little to find
by reading. What the suite found is another matter:

- **`is_pin_valid` always answered True**, and every sampling function in the module is built on
  it. It looked for an all-zero output matrix, on the stated grounds that "a coordinate outside
  every UV shell makes the pin output an all zero matrix, so the first row collapses to zero
  length". Maya does not do that: it answers with the **identity**, whose first row is `(1, 0, 0)`
  — and that passed the "is this row longer than nothing" test as readily as a real normal. So
  `find_uv_extent` walked to the 0 or 1 limit whatever the shell actually was,
  `get_uv_shell_extents` reported the whole map, and `get_uv_shell_rect` never shrank anything. The
  suite proves this with a plane whose UVs are squashed into a quarter of the map: the walk now
  stops at the shell edge.
- `create_planar_uv_set` raised `pm.MayaNodeError` when no face around the given point could be
  projected. That exception is Maya's for "there is no such node", and a caller catching it to
  handle a missing mesh would have swallowed this instead.
- `get_visible_region_faces` tested its `radius` for truth rather than for `None`, so a radius of
  `0` — the seed face and nothing else — was read as no radius at all and the region grew over the
  whole mesh.
- The occlusion test read `hit[3]`, the hit *triangle*, where the face index is `hit[2]`. It came
  to the same answer, but it was checking a number it did not mean.

Two modules read pins through this — `rigging/frag/uv_slide_component.py` and
`rigging/templates/familiar_template.py` — and both were being told every shell is the whole UV
map. Worth looking at what they do with the real answer when they are ported.

## `utils/events.py` — listening for Maya's events without crashing Maya

Maya holds a callback as a raw C function pointer with no Python reference behind it, so a callback
that outlives what it belongs to does not raise: it crashes the process. Most of this module exists
because of that, and the comments explaining it are the most valuable thing in it — they are kept
in full, including the note about a monkey-patch that made things very much worse and the date of
the crashes that came from it.

- **Every event but two was stored in a shape the pause and resume methods could not read.**
  `register_scene_event` and `register_selection_changed_event` filed a record — callback id,
  arguments, how to register again — and the other thirteen filed the bare callback id.
  `pause_event` opens with `self.events[unique_id]['message_type']`, which is `TypeError: 'int'
  object is not subscriptable` for all thirteen. Everything is filed the same way now.
- **Three log lines did not say what they were meant to.** Two were
  `logger.info('Registering {unique_id}')` — no `f` — so they logged the braces. The third was
  `logger.info(f'Registering {0}'.format(unique_id))`: an f-string *and* a `.format()`, where the
  f-string turns `{0}` into the number zero and the `format` then has nothing left to fill. It
  logged "Registering 0".
- **`register_tool_changed_event` registered the callback unwrapped**, alone among the fifteen — so
  the one kind of callback most likely to belong to a tool window had no dead-receiver guard at all.
- **The `parent_id` property read an attribute that is never set.** `__init__` does not create
  `_parent_id`, so the getter is an `AttributeError` waiting for its first caller.
- **Every event fire logged twice at info level** — "Event Starting" and "Event Complete", on every
  selection change, in a log artists read.
- **It was the last module in the package on Maya's old API.** `maya.OpenMaya` answers a
  `PyCapsule` for a callback id where `maya.api.OpenMaya` answers an integer — and when the whole
  point of a module is holding on to callbacks properly, being on the API that does that matters.
- Fifteen of the nineteen registration methods had no caller anywhere: the user events, the DAG and
  DG families, the node and animation families, `pause_event` and `resume_event`. What is left is
  what is called, plus the two general doors those were built on — `register_scene_event` for
  anything in Maya's scene-message list and `register_event_callback` for anything in its named
  event list. 661 lines became 427, most of that comments.

The suite registers real callbacks in a real Maya, sets them off, pauses and resumes them, and
leaves none behind — a callback left registered in a Maya the suite did not start is the crash this
module exists to prevent.

## `utils/camera_utils.py` → `utils/playblast.py`, and one half deferred

`camera_utils` held two unrelated things. One was the playblast and still capture: a camera, a path
and a resolution, needing nothing but Maya. The other was the "ubercam" — a cinematic camera rig
built on `rigging.frag`, `rigging.templates`, `rigging.rig_utils`, `animation.baking` and
`pyqt.dialogs`. That second half is not a utility at all; it is why a module in `utils/` sat at the
bottom of a dependency chain five packages deep, and it cannot be ported before `rigging/frag`.

The capture half is here as `utils/playblast.py`. The ubercam half comes over with `cinematics/`.
**Two things in it must not be lost in the move**, so they are written down here:

- `UBERCAM_MIRRORED_SHAPE_ATTRS` and the comment above it. The ubercam copies `focalLength`,
  the film apertures, the lens squeeze and the clip planes from the first shot's camera as *values*,
  once, with no DG connection — because (verified live, 2026-05-08) any connection on those
  attributes that Maya 2025's cache evaluator does not understand — a choice node, an anim curve, a
  clip-plane wire of any kind — crashes the renderer through shiboken6 the moment a shot camera is
  moved under cached playback. If per-shot lens variation is ever needed, it has to be a
  `timeChanged` script job setting the values imperatively, never a connection.
- Five modules call the capture half through `camera_utils` and will need rewiring to `playblast`:
  `cinematics/cine_file_utils.py`, `cinematics/shot_utils.py`, `tools/summoner/summoner_asset_tree.py`,
  `tools/cineshoteditor/cine_shot_editor_tool.py`, and whatever else reaches
  `create_center_capture`.

What was wrong with the capture half:

- **A frame range given as floats was silently thrown away.** `playblast_video` checked
  `all(isinstance(x, int) for x in time_range)` before believing the range it was handed — and
  `time_utils.get_times()`, the obvious thing to pass, answers *floats*, because that is what
  `playbackOptions` answers. So a caller that asked for frames 1 to 24 got whatever `get_times` said
  instead. `playblast_images` did the same to its frame list.
- **`playblast_single_frame` could return a single character.** `playblast_images` answered a list of
  paths for a folder and a bare string for a `.jpg` path; `playblast_single_frame` does `image =
  playblast_images(...)` and then `image[0]`, which for the string case is its first letter.
- **The step that clears the previous run's stills looked in the wrong folder.** `for x_file in
  os.listdir(file_path): if os.path.isfile(x_file)` — `x_file` is a bare file name, so `isfile` asked
  about it relative to the current working directory, which in Maya is its own `bin` folder. It never
  found anything, so old stills were left behind and the multi-frame return then listed them along
  with the new ones. There is a check that runs from a directory that is *not* the stills folder,
  which is what makes it a real check.
- `create_center_capture` moved the artist's `persp` camera to the origin to frame its subject and
  left it there. It puts it back now.
- A batch Maya has no viewport, so none of this can run there. Each function says so and answers
  empty rather than raising, which is what a build step wants; and the suite checks that, since it is
  all a batch Maya can check.

## `pyqt/` — Qt in Maya

Maya's interface *is* Qt, but it does not hand out Python objects for it. These three modules are
the bridge: Maya's main window and menu bar, the dialogs, and the two window classes every Maya
tool in the pipeline is built on.

- **`MCAMayaWindow` had its event handling written and none of it connected.** Its `eventFilter`
  calls `self.unregister_event(callback)` on close, and the class does not inherit
  `MayaWindowEvents`, so it has no such method — while `MCAMayaQWidget`, twenty lines below, does.
  The loop only stayed quiet because nothing could ever put anything in `self._callbacks`: the
  methods that fill it are on the mixin the class was missing. The one window class most tools use
  looked as though it cleaned up after itself and did not.
- **A window that was never shown never cleaned up at all.** Qt sends no close event for one:
  `QMainWindow.close()` on a hidden window answers True and sends nothing, where a plain `QWidget`
  does send one — which is why the panel class appeared to work and the window class did not. A
  tool that builds its window with `show_window=False`, registers a listener and throws the window
  away left Maya calling into a destroyed Qt object on the artist's next click. There is a second
  net on `destroyed` now, and a check for exactly that case. The `eventFilter` is gone; a
  `closeEvent` override does the same job in a way a reader can follow.
- **`self.events_register` was often never created.** `if events_register: self.events_register =
  ... if events_register else None` — the inner conditional cannot be false inside the `if`, and
  when the argument is False the attribute is simply not set, so the next `register_event` fails on
  `if not self.events_register` with an `AttributeError` rather than making one.
- **The default parent was worked out when the module was imported.** `parent=MAYA_MAIN_WINDOW` as
  a default argument, where `MAYA_MAIN_WINDOW = ma_main_window.get_maya_window()` runs at import —
  so every window ever made was parented to whatever Maya's main window was the first time anything
  imported the module. `None` in a batch Maya; `None` in an interactive one too if the import
  happened during start-up. `dialogs.py` did the same for every dialog's parent.
- **Wrapping a C++ pointer looked for the class in the wrong module.** With no base class given,
  `wrapinstance` read the object's class name off its `metaObject` and looked for it on `qtgui` —
  and every widget class lives in `QtWidgets`, and has since Qt 5. The lookup never found anything,
  so every wrapped object came back a bare `QWidget` whatever it was. Its fallback was
  `from PySide.shiboken import wrapInstance`, a module that has not shipped since 2013, and the
  branch beside it (`elif 'sip' in globals()`) could never run because `shiboken` is imported at the
  top of the file. The whole thing sat inside a bare `except: pass`.
- **A file dialog's style came from an option variable that is often unset.**
  `optionVar(query='FileDialogStyle')` answers `0` for a variable nobody has written, and
  `fileDialog2(dialogStyle=0)` is not a style Maya has — so on a fresh Maya profile the file dialogs
  asked for something that does not exist.
- **Nineteen of the twenty-two things in `ma_main_window` had no caller anywhere** — the workspace
  controls, the time slider, the x-ray joints, the axis setup, the node editor manager, the
  isolate-panel helpers, the UI suspension class. 491 lines became 192. The two things anything
  calls are the main window and its menu bar.
- `MCAMayaWindow` showed itself twice, passing `show_window` down to the base class and then calling
  `show()` again. `register_import_event` was the only one of four not named after the event it
  registers. Both remaining module docstrings described something else entirely — "Helper functions
  for Blend nodes and shapes" and, for the third time in this package, "Module that contains the mca
  decorators at a base python level".

One fix to the harness came out of this: `Suite` redirects `MCA_PREFS_ROOT`, `MCA_DEPS_ROOT` and
`MCA_LOGS_ROOT` into its temp folder, and now puts them back when it finishes. A suite run inside a
live Maya used to leave that Maya pointed at a temp folder that was about to be deleted — and every
process it started afterwards inherited it, which is how a later `mayapy` run came to be unable to
find PyYAML.

## `animation/` — keys, baking, curves and layers

Four modules, and the third and fourth are where the pipeline's animation actually lives:
`anim_curves.py` moves keys between curves, and `anim_layers.py` takes a layered animation off an
object and puts it back. Maya stores layered animation as a chain of blend nodes rather than as
anything you can copy, so "store this flag's animation" means walking that chain, duplicating it
node by node, and stitching the copy back together — which is what most of `anim_layers` is.

- **Baking without rotation zeroed every static rotation.** `bake_objects` finishes with an Euler
  filter, and the filter step ran whatever the caller had asked for: it keyed `rotate` to 0 at
  frame -1337 on every node in the list, filtered, then cut the key again. On a node whose rotation
  was *not* being baked and carried no rotation keys, that made a one-key rotation curve worth
  zero, and cutting its only key left the attribute reading back the only value it had ever
  evaluated to. Checked in a real Maya: a transform sitting at `rotateY = 45`, baked with
  `rotate=False`, comes back at `0.0`. Eighteen call sites bake; the ones that pass `rotate=False`
  were flattening rotations every time. The filter now runs only when rotation was baked, and only
  over nodes that have rotation curves.
- **The filter's anchor frame cut keys on other channels.** -1337 is outside the range until
  somebody's shot starts at -2000 — and `preserveOutsideKeys`, which is the default, means keys out
  there are kept on purpose. The anchor was then removed with a bare `cutKey(node_list, t=-1337)`,
  which names no attribute, so a real key at that frame on *any* channel went with it. Checked the
  same way: a `translateX` key at -1337 is gone after a bake. The anchor now goes one frame before
  the earliest key on the curves being filtered — which cannot collide by construction — and only
  the rotation channels are cut.
- **A nested animation layer lost whatever its parent did not also hold.**
  `merge_all_animation_layers` gathered the attributes to bake from the base layer's *direct
  children*. Animation layers nest, and a layer under one of those, holding an attribute its parent
  does not hold, was never in that list — so it was never baked, and was then deleted along with
  its parent. Checked against the old function: with `translateX` on the outer layer and
  `translateY` on a layer nested under it, `translateY` read 9.0 before the merge and 1.0 after.
  Every layer in the scene is collected now.
- **A shift of zero meant "work it out for me".** `change_curve_start_time` tested
  `if not shift_length`, so a caller asking for no shift — and two of them compute it as
  `0 - start_frame` — fell into the branch that moves the animation to frame 0 instead. Then, when
  the animation already began at zero and so needed no shift, it logged *"No keyframes were shifted
  as none were found"*, which is not what happened.
- **A start frame of zero meant "no start frame"**, in `restore_for_anim_layers` and
  `adjust_layers_timeline`, both of which tested `if start_time:` — so restoring an animation to
  frame 0, which is the common case for a cinematic, put it back wherever it happened to be. And a
  start frame that was not a whole number was ignored outright: `store_object_animation` tested
  `isinstance(start_time, int)`, which is False for `12.0`.
- **`reanimate_from_anim_curves` raised on an end time given without a start time.** It entered its
  trimming branch on `if end_time:` and then compared every key against `start_time`, which is
  `None` by default: `TypeError: '<' not supported between 'float' and 'NoneType'`. It could not
  trim on a start time alone either. It shares `crop_one_curve` with `crop_time_range` now, which
  also means it inherits that function's refusal to crop a curve down to nothing — Maya deletes an
  emptied curve, and the next line here connects it.
- **Restoring onto an attribute that already had curves could do nothing at all.** In
  `restore_for_anim_layers`, the branch that merges into existing animation only connected the
  stored network *inside* `if base_curves:` — so a stored network whose base layer held no curve
  left the object with its old animation and the whole stored chain orphaned in the scene. And only
  the existing curves that were actually merged into the stored network are deleted now; the rest
  are animation nobody else has a copy of.
- **Two functions answered `None`, and their answers are iterated.** `map_anim_layers` returns
  `None` when handed anything that is not a blend node, and it is iterated in four places;
  `create_anim_layer_network` returns `None` when there is nothing to duplicate, and its one caller
  does `attr_curves.update(...)` with the answer.
- **`adjust_layers_timeline` reported the last curve's end frame**, not the latest one, so the end
  frame handed back depended on the order Maya happened to list the curves in.
- **`connect_layer_dagSetMembers` added the same attribute to a layer twice.** It walked
  `dagSetMembers` looking for a free index without first checking whether what it was about to add
  was already in there, so restoring twice onto the same flag left the layer holding two entries
  for one attribute. Its `while` loop also had no bound at all.
- **Four places indexed a list that can be empty**: the first key of a curve with no keys
  (`change_curve_start_time`, `restore_from_anim_curves`, `store_object_animation`), the first plug
  of a curve that drives nothing, the last blend node of an empty map, and `key_time[0]` in
  `replace_into_curve`.
- `restore_from_anim_curves` only answered with an end frame when it had been given an offset,
  though its caller uses the answer either way; it now always reports the curve's last key. Its
  `start_time` argument was never a start time — its one caller passes the output of
  `get_start_time_diff` — so it is called `time_offset`, which is what it does.
- `get_objects_in_anim_layer` had no callers anywhere in the pipeline. Gone. It is the only dead
  function in `anim_layers`: twenty-six of its twenty-seven are reachable from the two entry points,
  which is unusual for this codebase and worth saying.
- `multiply_curve_values` iterated `None` on a curve with no keys, and asked for a key's value with
  `t=frame` rather than a time range. `update_connections_dict` had its two halves written out
  twice, byte for byte. Several log messages were built with `.format` rather than left to the
  logger, and one of them read "There is not Base Layer in the scene."

**One caller to rewire when its module is ported.** `rigging/frag/animated_curves.py` calls
`restore_from_anim_curves(..., start_time=...)`; the argument is `time_offset` now.

## `modeling/` — vertices, surfaces, follicles and blend shape targets

Five of the nine modules. The other four wait on packages that are not here yet: `rivets.py` and
`face_model.py` need `rigging/` and `face/`, and `blendshape_node.py` needs `rigging/flags`. What
is here is the part the face pipeline is built on — mirroring a mesh through a stored map, making
a blend shape target out of a rigged mesh, and sticking things to surfaces.

- **The closest point on a surface was answered with a position, not a parameter.**
  `pm.nt.NurbsSurface.closestPoint` answers `(point, u, v)`, and the line reading it was
  `uv, _, _ = surface_shape.closestPoint(...)` — so `uv` was the point, and the function handed
  back the closest point's X and Y coordinates under the name of a UV parameter. Its one caller,
  `rivets.attach_to_surface`, feeds those two numbers straight into a rivet's U and V, so every
  rivet attached to a surface without an explicit UV has been placed by coordinates that have
  nothing to do with the surface's parameterisation. Checked against a `closestPointOnSurface`
  node in a real Maya: a point at x=3 on a surface 10 wide is u=0.8, and the old function said
  0.0000000000000001. The default space was `preTransform` as well, while the caller measures its
  position in world space, so a surface that had been moved was measured against its
  untransformed self.
- **Mirroring in world space read world coordinates and wrote local ones.** `mirror_vertex` asked
  for the source position with `ws=world` and then set the target with a plain
  `pm.xform(target, t=...)`, which is object space whatever `world` was; the middle-vertex loop in
  `mirror_mesh` did the same to itself. Every world-space mirror moved vertices by the difference
  between the mesh's transform and the origin — correct only for a mesh at the origin with no
  rotation or scale, which is the one case anybody tested.
- **A mirror map with whole numbers in it raised.** `mesh_name + '.vtx[' + inverse_index + ']'`
  concatenates, and `json` gives a number back as an `int`. `mirror_mesh` also indexed the
  right-hand list with the left-hand list's index with nothing checking they were the same length,
  so a half-built map raised `IndexError` partway through and left the mesh half mirrored.
- **The reference pin's shape name was executed as code.** `eval(f'pm.poly{obj_shape}()[0]')`,
  where `obj_shape` comes out of a data file — a typo in the table was a `NameError` from inside
  an `eval`, and anything else in that field ran. Two named shapes now, and a third answers a
  warning. Setup data missing `region_rotations` or `ignore_types` crashed on the next line
  (`.keys()` on `None`); `make_pins` left the namespace at the root rather than putting back the
  one the caller was in; and the group it built to hold the pins was thrown away, so the caller
  got nothing back when the pins were not merged.
- **`create_follicle_constraint` could not work.** It called
  `pm.parentConstraint(follicle_transform[0], node)`, and `follicle_transform` is already the
  transform — indexing a PyNode indexes its *name*, so the first argument was the single character
  `'f'`. Checked in a real Maya. No callers, and nor had its only entry point
  `create_follicle_constraint_from_selection`; both gone, with `create_mesh_follicle`, whose only
  caller was the broken one.
- **`get_blendnode_shapes` walked the history to find the node it had already been given.**
  `pm.ls(pm.listHistory(blendnode), type='blendShape')[0]` — `listHistory` puts the node itself
  first, so on a blend node those three lines resolve to the argument, and on anything that is not
  one, such as the mesh callers reasonably pass, they are an `IndexError`.
- `set_blendshape_weights_from_mesh` and `set_blendshape_weights` were the same four lines twice
  over, differing only in which end they started from; the first had no callers. Dropped with
  `get_active_attribute`, `get_blendnode_index`, `convert_to_vertices` (which passed the built-in
  `object` to `filterExpand`, and put `selectionMask` inside a `.format()` call rather than the
  command, and was missing the dot before `cv` — three faults in nine lines),
  `get_inverse_vertex_selection` (replaced the user's selection without putting it back) and
  `fix_mesh_components_selection_visualization` and `apply_cube_trick`. None had callers.
- `set_vertex_symmetry` and `set_blendshape_weight_symmetry` each said "on, unless the pose is not
  on the centre, in which case off; and if symmetry is off, off" in a nested if/else. One line
  each. `delete_blendshapes` ran `pm.delete` inside a list comprehension for its side effect.
  `follicle.py` imported `naming` and never used it. Tabs for indentation, in three of the five.

`pyqt` went back into `MCA_MAYA_PATHS` in the manifest with this piece — the original listed it,
and it has been ported since; the manifest had not caught up.

**One caller to rewire when its module is ported.** `modeling/rivets.py` calls
`get_closest_parameter_on_surface` with a world position and no space; the default is `world` now,
so it wants no change — but it has been placing rivets by the wrong numbers, and every rig that
uses one should be looked at once `rivets.py` lands.

## `rigging/` — the leaves first

`rigging/` is the biggest folder in the package and everything else in it depends on `flags/`,
`chain_markup` and `joint_utils`, which depend on each other. So it starts at the three modules
that depend on nothing: the matrix constraint, the pole vector maths, and the space switch.

- **Building a space switch moved the control to its parent's origin.** The offset group is made
  at the control's world position, parented under the control's old parent — so its own local
  values become the control's — and the control is then parented under it, which zeroes the
  control's channels. The two lines after that set the group's translate and rotate to zero,
  which throws the offset away and takes the control with it. Checked in a real Maya: a control
  at `(1, 2, 3)` is at the origin once a space switch has been built on it. It has gone unnoticed
  because a flag normally sits at zero under an align group, where those two lines do nothing —
  but anything switched in place moved, silently, at build time.
- **An even-numbered joint chain took its pole vector from the wrong pair of joints.** The middle
  of a chain with no single middle joint is between the two either side of the centre — indexes 1
  and 2 of four. The code used `len(joint_chain) // 2` and the one after it, which for four
  joints is indexes 2 and 3: the joint past the middle, and the end joint. The pole vector came
  out planted near the end of the limb rather than in front of its bend. Six of the seven callers
  pass three joints, so it only shows on the seventh, which passes whatever chain it was handed.
  A two-joint chain raised `IndexError` on the same arithmetic, and a chain folded flat — root
  and end in the same place, which is a real pose for a curled finger — divided by zero and
  answered `nan` for every component, which Maya accepts and which turns up much later as a
  control nobody can select.
- **A space switch's constraint weight was addressed by a name that is not always the alias.**
  The weight was built as `'{target}W{index}'`, which is the alias only while the target's name
  is a plain short name — a target inside a namespace has a different alias, and the connection
  raised. Maya's own `getWeightAliasList` is asked now. Building a second switch on a control
  also raised, because both `addAttr` calls went in unguarded and the channel box separator is
  shared between switches; and a control with no parent raised on
  `pm.parent(group, None)`.
- **`remove_matrix_constraint` left half the constraint behind.** It deleted the two groups and
  stopped there: the two attributes that mark an object as constrained stayed on it, so anything
  asking afterwards was told there was still a constraint; and where Maya's delete did not follow
  history — with `t`, `r` and `s` all off, nothing connects the matrix nodes to a transform — the
  `multMatrix` and `decomposeMatrix` stayed in the scene reading the parent's world matrix. It
  also raised on an object that had never been constrained, and cleared the artist's selection on
  the way out. It had no callers, but it is the only way to undo `matrix_constraint`, so it is
  kept, fixed, and checked: constrain, remove, and the object is back under its original parent,
  in the pose the constraint was holding it in, with nothing of the constraint left in the scene.
- **Constraining an object twice left the first constraint running.**
  `create_aligned_parent_group` hands back the groups that are already there, so a second
  `matrix_constraint` on the same object built a second pair of matrix nodes whose outputs
  quietly replaced the first pair's connections — and the first pair stayed in the scene, still
  evaluating, driving nothing. Re-constraining takes the old one off first now, so pointing an
  object at a different parent is a thing you can just do.
- `matrix_nodes` also re-fetched a node from the scene immediately after renaming it, which does
  nothing, and connected array attributes by their bare names (`worldMatrix` rather than
  `worldMatrix[0]`), which works only because Maya picks element zero for you.
