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

**2,343 checks in 34 suites** so far — 2,359 in an interactive Maya, where the windowing checks can run. `utils/`, `modifiers/`, `pyqt/` and `animation/` are done, bar one deferred half of `camera_utils`; `modeling/` bar the three modules that need `rigging/` and `face/` first; and `rigging/` is down to `rig_utils.py` itself, which nothing else in `rigging/` imports any more. `frag/` has started with the metadata node the whole system hangs on.

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
| `utils/groups.py` | ported, 39 checks — `create_align_transform` moved here out of `rig_utils` |
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
| `modeling/face_model.py`, `modeling/blendshape_node.py` | waiting on `face/` and `rigging/flags` |
| `rigging/matrix_nodes.py`, `rigging/ik_utils.py`, `rigging/space_switch_rig.py` | ported, 71 checks — building a space switch moved the control to its parent's origin |
| `rigging/chain_markup.py`, `rigging/joint_utils.py`, `startup/configs/ma_consts.py` | ported, 100 checks — a joint could not be marked as not-exported |
| `rigging/mesh_markup_rig.py` | ported, 51 checks — asking an untagged mesh anything raised; 510 lines to 396 |
| `rigging/flags/flag_mirror.py`, `rigging/flags/frag_flag.py` | ported, 96 checks — every imported flag came back drawn twice |
| `rigging/flags/serialize_flag.py` | **dropped** — it wrote `.flag` files nothing can read back; see below |
| `rigging/flags/flag_utils.py`, `rigging/flags/flag_api.py` | waiting on `frag/` |
| `rigging/cog_chain_rig.py`, `world_chain_rig.py`, `reverse_chain_rig.py`, `ikfk_switch.py`, `fk_chain.py`, `multi_constraint_rig.py` | ported, 70 checks — an FK chain built without align transforms raised |
| `rigging/reverse_foot_rig.py`, `rigging/spline_ik_rig.py` | ported, 61 checks — a spline IK built in a namespace raised on its constraint weights |
| `utils/locators.py` (new), `rigging/ribbon_setup.py`, `rig_aim_joint.py`, `twist_setup.py` | ported, 54 checks — the locator builders moved out of `rig_utils` |
| `rigging/rfk_chain.py`, `rigging/rfk_stretch_chain.py` | ported, 86 checks — a stretch chain too short to stretch divided by zero |
| `deformations/cluster.py`, `rigging/reference_line.py` (new), `rigging/ik_chain.py` | ported, 70 checks — a cluster built inside a namespace raised `TypeError` |
| `rigging/skel_utils.py` | ported, 67 checks — exporting over a read-only file failed, and restoring markup cleared every weight lock |
| `rigging/frag/frag_base.py`, `rigging/frag/__init__.py` | ported, 93 checks — no rig has ever been brought up to a new component version |
| `rigging/frag/rig_component.py`, `rigging/frag/keyable_component.py` | ported, 57 checks — `align_component` has never aligned anything |
| `rigging/frag/frag_root.py`, `skeletal_mesh.py`, `frag_rig.py`, `display_layers.py` | ported, 98 checks — reading a rig's scale rewired it; a rig build took other characters' geometry |
| `rigging/frag/multi_constraint.py` | ported, 31 checks — a second space switch on a control raised something unreadable |
| `rigging/frag/animated_curves.py` | ported, 51 checks — restoring animation could put curves on the wrong channels |
| `rigging/frag/ik_component.py`, `fk_component.py`, `ikfk_component.py` | ported, 93 checks — building a limb wiped the Maya joint labels off the joints it drives, and `offset_flag=True` had never worked |
| `rigging/frag/mesh_component.py` | ported, 49 checks — the one function that reads a mesh component back has never answered correctly |
| `rigging/frag/world_component.py`, `cog_component.py`, `pelvis_component.py`, `clavicle_component.py` | ported, 84 checks — a COG's fallback could never reach its last choice, and a clavicle looked its chain up with an attribute object |
| `modeling/rivets.py` | ported, 40 checks — attaching a transform to a surface built an evaluation cycle on its default arguments |
| `rigging/frag/pin_component.py` | ported, 41 checks — the three control methods every component carried a copy of raised on a component with no controls |
| `rigging/frag/attachment_component.py`, `space_switch_component.py`, `aim_component.py` | ported, 62 checks — two of the three recorded work that had not been done, and the third wiped joint labels |
| `rigging/frag/twist_fixup_component.py`, `camera_component.py`, `s_sdk_component.py` | ported, 53 checks — one is at version 2 with no step to get there, one spells its version differently from every other component, and one recorded the driving node instead of the driving attribute |
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
  three callers all used that one — dropping it takes this module's import of
  `mca.mya.deformations.cluster` with it, which is what made a leaf utility depend on the
  deformation code. The surviving copy is `rigging/reference_line.py` now, for the same reason:
  it is built out of clusters, so it is not a leaf utility.

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

## `rigging/chain_markup.py`, `rigging/joint_utils.py` — the skeleton's description of itself

A rig builder has to find "the left arm" in a skeleton it has never seen. Doing that by name would
mean every skeleton in the studio being named the same way for ever, so the description is written
onto the joints instead — `skelSide`, `skelRegion`, `chainStart`, `chainEnd`, `chainTwist`,
`hierarchyStart`, `skExport`, `animationExport` — and the builders read that. `JointMarkup` is one
joint's markup as properties; `ChainMarkup` walks a skeleton and sorts it into a region → side →
chain lookup. Everything else in `rigging/` is built on the two of them, which is why they come
before the rest.

- **A joint could not be marked as not-exported.** `is_sk_export` and `is_animation_export` stored
  "no" by *deleting* the attribute — and their getters created the attribute with a default of
  `True` whenever it was missing. So setting either to `False` removed the attribute and the next
  read put it back as `True`. Checked in a real Maya: set `False`, read back `True`. Both the
  skeleton builder and the auto-rigging tool let an artist tick a joint out of an export, and
  neither tick has ever stuck; `ChainMarkup`'s two export lists have been the whole skeleton every
  time. The flag is stored now, and absence still means yes.
- **Reading the markup wrote to the scene.** Those same two getters added an attribute as a side
  effect of being asked a question, and `ChainMarkup.parse_joints` asks both of them about every
  joint — so merely building a `ChainMarkup` to look something up added two attributes to every
  joint in the skeleton and left the file dirty. On a referenced or locked skeleton it would have
  failed outright. Reading answers the default and creates nothing.
- **A region whose chain end came from another region crashed on its own middle joints.** A wrist
  in the arm region marked `chainEnd = 'hand'` files that end under `chain_dict['hand'][side]`,
  and builds that entry as an empty dictionary with no `'joints'` key. The guard that would have
  created one is an `elif` on the side not being there yet — and it is there. So the next hand
  joint with neither a start nor an end marking hit
  `chain_dict['hand'][side]['joints'].append(...)` and raised `KeyError: 'joints'`. Reproduced
  from the real parse order: wrist, hand, palm. `setdefault` throughout now.
- **Clearing a chain marking raised on a joint that did not have it.** The setters read
  `if not hasAttr(...): if val: ...add... elif not val: ...delete...`, so a joint with no
  `chainStart` being set to `''` matched neither branch and fell through to a `set()` on an
  attribute it had just decided not to create. Checked in a real Maya. `hierarchyStart` could only
  be set once, for the same kind of reason — its setter called `addAttr` unguarded, so setting it
  `True` twice raised `RuntimeError: Found no valid items to add the attribute to`. And
  `chainStart` assumed a joint that already had the attribute also had `skelRegion`, creating the
  region only in the branch where it did not.
- **`parse_joints` did not reset everything it fills.** `_invalid_joints` and `_hierarchyStart`
  were left alone, so parsing twice appended to the first pass's invalid list and kept a hierarchy
  start that may have been removed since.
- **A chain duplicated with no suffix was named after the word "None".**
  `f'{name}_{suffix}'` with `suffix` left at its default gave `spine_01_None`, for every joint.
  And **skipping the first joint of a chain raised**: `duplicate_chain` decided where to parent
  each copy with `if index == 0`, where `index` counts the joints it was *given* rather than the
  ones it has made — so skipping the first sent the second looking for `dup_chain[-1]` in a list
  that was still empty.
- Three functions assumed `pm.listRelatives` had found something: `[root] + pm.listRelatives(...)`
  is a `TypeError` on a one-joint skeleton, `get_joint_hierarchy` iterated the same answer, and
  `get_root_joint_from_list` called `hasAttr` on a parent walk that can come back empty.
  `get_joint_hierarchy` also asked shape children whether their `type()` was `'joint'`, and put
  the node it was given at the front of the list whether or not it was one.
- `is_valid` was `not any(self._invalid_joints)` — walking a list of PyNodes testing each one's
  truthiness to answer a question about the list's length. `remove_is_start` and `remove_is_end`
  had no callers, and setting the property to `''` is the same thing now that it works. The
  circular import between the two modules is gone in one direction: `skeleton_dict` is worked out
  when it is first asked for, and imports `joint_utils` there.
- `ma_consts` opened with four quotation marks and a docstring describing "the mca decorators at a
  base python level" — the fourth module in this package to carry that line. `THRIDPARTY` was
  misspelled in the constant name (not the value), so every reader had to misspell it too.
  `PARENT_SEPARATOR` and `JOINT_TYPE_LABELS` had no readers anywhere. Gone.

**Callers to rewire when their modules are ported.** `tools/ai_rig_builder/markup_applicator.py`
reads `chain_data._invalid_joints` and `rigging/rig_utils.py` reads
`bake_hierarchy._animationJoints` in three places — both are public properties now
(`invalid_joints`, `animation_joints`). `startup/startup.py`,
`startup/configs/ma_envs.py` and `startup/headless_startup.py` read `ma_consts.THRIDPARTY`, which
is `THIRDPARTY`.

## `rigging/mesh_markup_rig.py` — which mesh is which

A character arrives as a bag of meshes — a head, two eyes, teeth, lashes, a body, a dozen blend
shape targets — and a builder has to know which is which. Names do not answer that across two
characters made by two people, so each mesh carries one string attribute holding a JSON
dictionary: what kind of mesh it is, what category it belongs to, which side and region it is on,
what it was made from.

- **Asking an untagged mesh anything raised.** Every read goes through `get_dict`, which reads
  `self.mesh.attr(MCA_MESH_MARKUP)` — and a mesh without the attribute has no such plug. So
  `MeshMarkup(mesh).region` on a mesh nobody had tagged was an `AttributeError`, and there was no
  way to ask "is this one of ours?" other than checking the attribute by hand first, which a
  caller had to know to do. An untagged mesh answers an empty dictionary now, and `is_marked_up`
  asks the question directly.
- **Markup that was not valid JSON took the whole build down.** `json.loads` on a truncated or
  hand-edited string raises, from inside a property read, half way through a rig build. It is
  caught and reported against the mesh it came from.
- **`set_dict` could not clear the markup** — `if mesh_dict:`, so writing an empty dictionary did
  nothing at all and the mesh kept whatever it had.
- **`get_mesh_markups()` with no argument wrapped the wrappers.** Its default was
  `self.mesh_list`, which is already a list of `MeshMarkup`, so calling it that way built
  `MeshMarkup(MeshMarkup(...))` — every read on which would then go looking for a Maya attribute
  on a Python object. Nothing called it that way, and the default is gone.
- **Two hundred lines of the module were the same ten lines twenty times over** — ten entries,
  each with a getter and a setter that did nothing but name the entry. They are built from a
  `MARKUP_ENTRIES` table now, which is also the only description of the schema this has ever had.
  `get_region_dict` had no callers and `get_blendshape_region_dict` was the same function with one
  `if` in it; one function with a `category` argument replaces both. `RigMeshMarkup.create` called
  `hasAttr` on the result of `getParent()`, which is `None` for a shape at the scene root.

**One caller to rewire when its module is ported.** `face/face_utils/face_build_utils.py` calls
`get_blendshape_region_dict()`; it is `get_region_dict(category=BLENDSHAPE_CATEGORY)`.

## `rigging/flags/` — the controls an animator selects

A flag is a joint drawn as nothing, carrying a NURBS curve shape and a handful of marker
attributes. A joint rather than a transform because a joint has a `jointOrient`, which is where a
control's build-time orientation can go without spending its rotate channels. The shape is not part
of the rig build: a rig is built with a placeholder cube on every control, and `swap_flags` then
replaces those from per-rig `.flag` files, which is how a rigger reshapes a control without
rebuilding anything.

- **Every flag imported from a `.flag` file came back drawn twice.** `deserialize_flag` builds the
  transform from the first shape's data — and then builds a *second* curve from that same data and
  parents its shape in alongside. For a one-shape flag, which is almost all of them, the result is
  two identical overlapping curves. Checked in a real Maya: two shapes on the rebuilt transform.
  `swap_flags` then moves both onto the rig's control, so every rig built with custom flag shapes
  has been carrying doubled curves on every control — twice the geometry to draw, and templating or
  hiding one of them leaves the other behind.
- **Re-orienting a flag's align transform reached into the artist's selection.** `Flag.create`
  builds its joint at the top of the scene, so the align group above it has no parent — and the
  `orientation` branch then called `pm.parent(None, world=True)`, twice. `pm.parent` given `None`
  falls back to whatever is selected, so that un-parented the current selection to the world; with
  nothing selected it raised `TypeError: Error retrieving default arguments`. Both checked in a real
  Maya. The branch only ever looked correct because its last line put the flag back under its align
  group.
- **Building a flag changed what the artist had selected** — `pm.select(cl=True)` to make the joint,
  and then `pm.curve`, `pm.parent` and `makeIdentity` each leaving their own node selected. A flag
  build ended with the new flag selected and whatever the artist had chosen gone. The whole of
  `Flag.create` runs inside the maintained-selection context now, which is also what stops the
  `orientation` branch from having anything to reach into.
- **`hide_align_transform` raised on a flag built without an align transform** —
  `get_align_transform` answers None for one, and the next line was `align.v.set(0)`.
- **`export_flag` gave up silently**, twice: once when the node's first shape is not a curve, once
  when there was nothing to serialize. A rigger exporting the wrong selection got no file and no
  reason.
- **The homogeneous-coordinate conversion never ran.** A comment says `getCVs()` returns 4D points
  and the code divides each by its `w`. It returns three components — checked in a real Maya — so
  the branch was dead. It is kept, because a `.flag` file written by something that *did* store four
  is still readable, but it no longer claims to be there for Maya's benefit.
- **A hundred and twenty lines of the `Flag` class were one-line forwards to the wrapped node** —
  fourteen dunder methods, each `return self.node.<the same name>(...)`. They have to exist on the
  class, because Python looks dunders up on the type and never reaches `__getattr__`, so they are
  built from a list of names now rather than typed out.
- `create_align_transform` was reached through `rig_utils`, so building a flag pulled in 1,752 lines
  of rig building — and everything in `rig_utils`, in turn, needs flags. It is three fixed arguments
  to `create_aligned_parent_group`, so it moved into `utils/groups.py` beside the function it wraps,
  and `frag_flag` now depends on nothing that depends on it. The serializer version is written into
  every file and has never been read; that is still true, and now said out loud. `Flag.create` wrote
  the same four lines four times over for the four marker attributes, and named a temporary curve
  transform after a shape it was about to throw away.

`flag_mirror.py` came over as it stands, minus an unused `import re` — it was rewritten during the
mirror calibration work. It touches no Maya at all: which flag pairs with which is a naming
question, answerable with certainty on whole underscore-separated tokens; which channels flip is a
rigging question that names cannot answer, so the module names the two conventions and the animation
library measures which one a rig obeys.

**Callers to rewire when their modules are ported.** `rig_utils.create_align_transform` is
`groups.create_align_transform` — fourteen call sites, of which only `rig_utils.py`'s own are left;
`rfk_chain.py` (5), `rfk_stretch_chain.py` (5), `spline_ik_rig.py` and `rig_aim_joint.py` are done.

## `rigging/flags/serialize_flag.py` — dropped: it wrote files nothing could read

There were two `.flag` writers in this package and they did not agree on the format. This is the
one that goes.

`frag_flag` writes YAML with the curve data under a `curve_data` key, and `frag_flag.swap_flags` —
the only thing anywhere that reads an asset's `Flags` folder — reads YAML and looks under
`curve_data`. `serialize_flag.export_flag` wrote **JSON**, with the curve data under a key called
`flag`, alongside colour and matrix entries. JSON is valid YAML, so `swap_flags` reads such a file
without complaint, finds no `curve_data`, gets an empty dictionary back, and leaves the control on
its placeholder cube. Silently. Checked end to end in a real Maya, in `test_flags.py`: a file in
that shape parses, has no `curve_data`, imports as `None`, and `swap_flags` reports that it swapped
nothing.

That matters because of who used which. The YAML writer is called from `rig_utils` and
`buildarig_ui`. The JSON writer is called from `face_staging_ui.create_flags_from_common`, which
populates an asset's `Flags` folder from the common face flags — so **every face asset whose flag
shapes came through face staging has been getting placeholder cubes back on the next rig build**,
and the folder full of `.flag` files sitting beside the rig looks like it is working.

Rather than document that and keep both, the module goes, because nothing in it survives contact:

- **Its only live entry point was `export_flag`**, with one caller in the shipping pipeline
  (`face_staging_ui`) and one in `tools/_deprecated/flags_exporter`, which is not coming over.
- **Everything it wrote that `frag_flag` does not — colour, `worldMatrix`, `matrix`, `space` — is
  never read by anything.** Its own `deserialize_flag` reads only the CVs, knots, degree and form.
  It was write-only data in a file nobody could open.
- **It saved rotated shapes.** `export_flag` duplicated the control, sent it to the world, and did
  `pm.move(dup, [0, 0, 0])` — translation only. The CVs were then read in world space, so the
  control's orientation went into the saved shape. Flags are built aligned to joints, so almost
  every flag is rotated. `frag_flag.export_flag` zeroes rotation, scale and `jointOrient` first,
  which is what a shape library wants.
- `normalize` was never passed by any caller; `space` never either. `FlagData`, the 200-line
  reader/writer class around it, had no users at all — the two places that mention `FlagData` in
  the pipeline are stale docstrings in `frag/face_edit_component.py` describing a differently named
  class in that same file. Its `export_flag` also had a `finally` branch that deleted the
  duplicate's *parent* — siblings and all — on a path that cannot be reached, and an
  `if os.path.exists(flag_path): fileio.touch_path(flag_path)` that only created the file when the
  file was already there.

**One caller to rewire when its module is ported.** `tools/face_staging/face_staging_ui.py` line
2610 calls `serialize_flag.export_flag(pm.PyNode(x), flag_path)`; it is
`frag_flag.export_flag(x, os.path.join(flag_path, '<name>.flag'))` — note that `frag_flag` takes
the file path, not the directory.

## `rigging/flags/flag_utils.py`, `rigging/flags/flag_api.py` — waiting on `frag/`

Both import `mca.mya.rigging.frag`, so they land with that package. What is already visible in
them, recorded here so it is not re-discovered:

- **"Remove animation" is broken whenever there is exactly one rig in the scene**, which is the
  common case. `flag_api.check_for_rigs` returns the rig *itself* when there is one and a *list*
  when there are several — its own docstring calls the return type inconsistent — and
  `remove_animation` does `for rig in frag_rigs:`, which iterates a single `FRAGRig`.
- **`select_all_flags` only ever leaves one rig's flags selected.** It calls `pm.select(...)` once
  per rig inside the loop, with no `add=True`, so each rig replaces the last.
- **`zero_flags` with an empty list zeroes every rig in the scene.** `if not node_list: node_list =
  frag.get_frag_rigs()` — and `cut_all_flag_animations` hands it the rig's flags, so a rig with no
  flags reaches that fallback and zeroes rigs the caller never mentioned.
- The twelve-line "resolve these nodes to FRAG rigs" block is written out three times, twice
  identically including its `logger.info('All nodes were FRAGRigs.')`, and the third copy quietly
  leaves out the fast path the other two have.
- `flag_utils` puts up a modal dialog (`dialogs.info_prompt`) from inside a function a headless
  build calls.

## The chain builders — the six that needed nothing from `rig_utils`

Fourteen small modules in `rigging/` each build one kind of control setup, and seven of them
imported `rig_utils` — for five functions, one of which (`create_align_transform`) has already moved
into `utils/groups.py` and one of which (`find_primary_axis`) is already `dag.get_primary_axis`. The
six that need none of the rest are here: the COG control, the world controls, the reverse chain, the
FK chain, the IK/FK switch and the matrix multi-constraint.

- **An FK chain built without align transforms raised.** The parenting step reads
  `flag_node.alignTransform.get()` — the attribute directly — and a flag built with
  `add_align_transform=False` does not have that attribute, so it is an `AttributeError` rather than
  the `None` the surrounding `if` is written for. Both `root_align_transform=False` and
  `children_align_transforms=False` reached it. It asks the flag now, which answers `None`.
- **`reverse_chain`'s default suffix stripped every underscore out of the control's name.** The
  label is `start_joint.nodeName().replace('_' + suffix, '')`, and `suffix` defaults to `''` — so
  the replacement is `'_'` for nothing at all, and a joint called `l_ankle` gave a control called
  `f_lankle`. Its one caller passes a suffix, which is why nobody has seen it.
- **A second multi-constraint on the same control raised.** The enum went in with an unguarded
  `addAttr`; the channel-box separator beside it *was* guarded, which is what makes the omission
  look like an oversight rather than a decision. An empty target list raised on `target_list[0]`.
- **One branch of `fk_joint_chain` could never run** — `elif create_end_flag and inc ==
  len(chain_to_rig)`, and `enumerate` never yields an index equal to the length of what it is
  walking. The end control was always built by the branch below, which is the same call with a
  different align-transform argument. Gone, leaving the two cases that exist.
- **`world_chain`'s `flags` entry left the offset control out**, though all three controls are built
  and all three are locked the same way. Its one caller does not read that entry — it wires up the
  three by name — so nothing depended on the omission, and all three are in it now.
- `reverse_chain`'s refusal read *"There can be no joints between startJoint and endJoint"*, which
  is what it requires rather than what went wrong, and was raised at the moment there *were* joints
  between them. `multi_constraint` disconnected the `multMatrix`'s inputs by handing
  `disconnectAttr` the parent of a multi rather than the elements that are connected, and connected
  world matrices by their bare array names; its three `for x in range(len(target_list))` loops are
  two, which is the fewest possible — every offset attribute has to exist before any is connected.
  An FK chain of one joint with no end control builds nothing and now says so. All six assembled
  their result dictionaries a line at a time; the magic numbers they carried — a rotate order of 2,
  a scale of 0.85, an orientation of -90 — are named.

**Still waiting on `rig_utils`.** `ik_chain` needs `create_line_between` and the two locator
builders; `rfk_chain`, `rfk_stretch_chain` and `rig_aim_joint` needed `create_locator_at_object`;
`ribbon_setup` and `twist_setup` need `find_primary_axis`, which is `dag.get_primary_axis` — note
that it answers a lower-case axis letter where `rig_utils` answered an upper-case one, so a caller
comparing against `'X'` wants changing; `spline_ik_rig` needed only `create_align_transform` and is
unblocked. `reverse_foot_rig` needs nothing from `rig_utils` and is next.

## `rigging/reverse_foot_rig.py`, `rigging/spline_ik_rig.py` — the two intricate ones

A reverse foot is the pivots that let an animator roll a foot through a step: a foot does not rotate
about the ankle when somebody walks, it rolls about the heel, then the ball, then the toe, and none
of those is where the ankle joint is. So the pivots are built as a nest of duplicated contact joints
— toe pivot, toe, ball pivot, exterior, interior, heel — with the ankle chain hanging off the
bottom, and the attributes on the foot control wired one each to those rotations.

A spline IK is Maya's solver plus the two things it does not give you: stretch, so the chain reaches
its end control instead of sliding off the end of the curve, and a retract, so a tail can disappear
into a body rather than bunching up at its base.

- **A spline IK built inside a namespace raised on its own constraint weights.** The retract wires
  the chain's orientation handover into a two-target constraint, and it addressed the two weights as
  `'{name}W0'` and `'{name}W1'` built from `naming.get_basename` — which strips the namespace that
  Maya's weight alias keeps. Referencing a rig into a scene and rebuilding it is exactly when the
  names have namespaces on them. `getWeightAliasList` is asked now. This is the third place in the
  package that built a weight alias by hand; `space_switch_rig` was the first.
- **A foot with no contact joints, or the wrong number of them, built nothing and said nothing.**
  Two early returns with a comment each. An animator gets a leg with no foot controls and no reason
  why. Both now name what was wrong and what was expected.
- **Building a reverse foot onto an existing foot control raised.** Seven attributes go on with
  unguarded `addAttr` calls, and the control is passed in by the leg components — so a second pass
  over the same leg was an error rather than a rebuild. Same for the spline IK's `retract`.
- **`do_not_touch` held the spline IK's cluster twice** — it is built from a list that already
  includes the cluster and then the cluster is appended again. Whatever a caller does to that list,
  it did twice.
- **`mid_flag` in the spline IK's result was set twice, once to the argument.**
  `mid_flag_node if mid_flag else mid_flag` answers the boolean `False` when no mid control was
  asked for rather than None, and the line below overwrote it when there was one.
- **A degenerate curve divided by zero.** The stretch ratio is the curve's length now over its
  length at build time, and nothing looked at the second number; every joint would have come out
  scaled `nan`.
- `reverse_foot_chain`'s `foot_joint, toe_joint, *_ = duplicate_chain(...)` raised `ValueError` on a
  chain of one joint, and a spline chain of fewer than two joints walked into `ikHandle` and failed
  there. `ik_toe_flag.alignTransform.get()` read the attribute rather than asking the flag, the same
  mistake that made an FK chain without align transforms raise. The spline curve's world space was
  read off the transform in one place and the shape in another; `mult_node.input1.input1X` reached a
  compound's child through its parent; `sca = 1.0` is a named constant; and the magic numbers in the
  retract — the u threshold of 6, the handover range of 3, the condition operation of 4 — are named
  and said out loud, including the one nobody can explain from the code (`RETRACT_U_THRESHOLD`),
  which is described by what it does rather than by a reason it does not give.
- Both functions were one long block; the pivot hierarchy, the reverse chain, the foot attributes,
  the stretch and the retract are each their own function now. The two reverse foot controls are
  named inconsistently — the foot control takes the full side name and the toe control its first
  letter, so `f_left_foot` sits beside `f_l_foot_toe_ik`. Left alone: rig data refers to these names.

## `utils/locators.py`, and the three setups that were waiting on it

The last thing holding most of `rigging/` behind `rig_utils` was two eight-line functions that put a
locator somewhere. They are not about rigs — a locator is the cheapest thing in Maya with a position
and an orientation — so they are in `utils/locators.py` now, and anything that wants a marker no
longer pulls 1,752 lines of rig building in behind it. The three modules that needed them, or needed
`find_primary_axis`, come with them: the ribbon, the aim setup and the twist setup.

- **`create_locator_at_object` answered a locator at the world origin when given nothing, silently.**
  It reads as a guard — `if not obj or not pm.objExists(obj)` — but what it guards is the caller being
  told. A build that asked for a marker at a node which had been deleted got one at the origin and
  carried on from there.
- **`find_primary_axis` answered an upper-case axis letter; `dag.get_primary_axis` answers a
  lower-case one.** Both `ribbon_setup` and `twist_setup` use the letter as an index into `'XYZ'`, so
  the two had to move together — `twist_setup` was already calling `.lower()` on the answer at both
  its use sites, which is what went away.
- **A ribbon along fewer than three nodes gave the plane a negative number of patches.** `patchesV`
  is `len(node_list) * 2 - 4`, which is -2 for one node and 0 for two, and Maya refuses both. Nothing
  said so.
- **The aim setup named its up locator by string surgery on another locator's name** —
  `up_loc.rename(up_loc.nodeName().replace('_loc_loc', '_up_loc'))`, which only works because
  `create_locator_at_object` appends `_loc`, so a locator made from a locator called `x_loc` comes out
  `x_loc_loc`. Anything else about either name and the replacement finds nothing and the locator keeps
  the double suffix.
- **The aim control was named after the joint's full path** (`bind_joint.name()`, namespace and all)
  and was **meta-connected to a marker that is deleted three lines later** — `Flag.create` wires a
  control to what it was built on, both ways, and here that is a temporary locator. It asks not to be
  wired now.
- **A twist chain of more than three joints was refused silently** (three is the limit because one
  `multiplyDivide` node has three channels), an empty list raised `IndexError` on `joint_list[0]`, and
  the driving joint's child was found with `parent_chain.index(parent_joint) + 1` — an `IndexError`
  when the driving joint is last in its chain and a `ValueError` when the markup does not put it in
  that chain at all. Both are markup mistakes a rigger can make, and both now name the joint and the
  region.
- `ribbon_setup` read `previous_pos` inside a branch that only runs from the second node and assigned
  it at the bottom of the loop, so it worked by the order of the lines; both running values start at
  None. The plane was called `nurbs_curve` throughout. The numbers that place the CVs — four per row,
  two and a half units apart — were in the arithmetic. `twist_setup`'s 230-line body is four
  functions, and the thing nobody would guess from reading it — that `sorted(joint_list)` sorts
  PyNodes *by name*, so the order the twist is distributed in is the order the joints happen to be
  named in — is written down. `quick_build_twist_setup` has no callers and is kept: it is the only
  place that shows how `ChainMarkup.twist_joints` is meant to be walked.

**What is left of `rig_utils`' hold on `rigging/`.** Nothing. `ik_chain` was the last module in
`rigging/` importing it, and `create_line_between` — the one thing it wanted that had not moved — is
`rigging/reference_line.py`. What is left in `rig_utils` is only used by `rig_utils` itself and by
the parts of the package that have not been ported.

## `rigging/rfk_chain.py`, `rigging/rfk_stretch_chain.py` — one chain and its stretching variant

A reverse FK chain gives a spine two controls instead of six: one at each end, and every joint
between them works its own rotation out from the two. The interesting part is that the blending is
done with *positions* rather than with a blended orientation constraint — each end control pushes a
pair of locators out along its own X and Y, a point constraint averages each pair by weight, and the
middle joint aims at the averaged X with the averaged Y as its up vector. Two orientations far apart
blend the long way round; two points cannot. The weight is a smoothstep of how far along the chain
the joint sits, worked out at build time.

`rfk_stretch_chain` is the same chain with a length on top: one free translate axis on the end
control, a node network turning it into a length factor and a volume-preserving cross-section scale,
and a no-stretch twin of the chain for the end control's align group to follow so that the
animator's translate is never downstream of what it drives. The two modules had the same ~150 lines
in them twice, differing in one line; the four builders in `rfk_chain` are public now and
`rfk_stretch_chain` calls them, passing the one node that differs as an argument.

- **A stretch chain too short to stretch divided by zero.** A chain of one joint has a rest length
  of nought, which went straight into the `multiplyDivide` that turns the control's offset into a
  length factor, and put both end controls on the same joint. A chain of two built a reverse FK
  chain with nothing in the middle to distribute to. Neither said anything. A chain whose joints all
  sit in the same place divides by zero the same way at any length, and is caught now too.
- **Both docstrings said the twist bias attributes were keyable and exposed to the animator.** They
  are added keyable and then set `keyable=False, cb=False` on the very next line, and nothing
  anywhere reads or drives them afterwards — they are the build-time weights. They go on
  non-keyable, and what they are for is written down.
- **The chain was walked without a node type**, so anything in it that is not a joint would be
  counted as a middle joint and given a control. Every other caller of `get_between_nodes` in the
  package asks for joints.
- **Renaming the sub controls threw away their wrappers.**
  `sub_end_flag = pm.rename(sub_end_flag, str(sub_end_flag) + '_sub')` rebinds the name to the
  PyNode `pm.rename` answers, so what came back in `sub_flags` was a bare node where every other
  control in the result is a `Flag`. The node is renamed through the wrapper now.
- **`rfk_stretch_chain`'s docstring said the end control "gets a single unlocked translate axis".**
  Nothing in the module locks anything: all three axes come out free, and moving the control on
  either of the other two slides it off the chain and does nothing at all. `RFKStretchComponent` is
  what locks them, from the `stretch_axis` the builder returns. That is written down accurately now,
  rather than reading as something the module does.
- The label — strip the suffix, strip the namespace — was written out six times in each module, and
  a caller passing `suffix=''` would have had every underscore stripped out of every label, the same
  fault `reverse_chain` had. The five units the aim locators are pushed out by, the 0.75 the subs are
  drawn at and the three `multiplyDivide` operation numbers were in the arithmetic. `getParent()`
  stood in for the control's align transform in both, which is only the same node while nothing has
  been reparented.

**The one thing in here that had to be checked rather than read.** `rfk_stretch_chain` builds an
`end_orient_proxy` — an empty carrying the end control's rotation — and has the middle joints' aim
systems read that instead of the control itself, with a comment saying that reading the control
closes an evaluation cycle. That is not something reading the code can settle, so the suite settles
it: it builds the rig once as written and asks Maya for a cycle check, which comes back clean, and
then builds it again with the proxy replaced by the control and asks again, which comes back with a
cycle. The reason the proxy works is worth knowing if anyone touches this: the align group it copies
its orientation from is only ever *point* constrained, so its orientation can never drift from the
one the proxy's group was built with.

## `deformations/cluster.py`, `rigging/reference_line.py`, `rigging/ik_chain.py`

A rotate-plane IK chain is the arm-and-leg workhorse: an IK handle sitting in an align group so the
rig can move the whole thing without a constraint fighting the solver, a control that places the end
of it, a smaller detail control under that which turns the end joint, and a pole vector control with
a template line drawn from the middle joint to it so an animator can see which joint it steers.

The line is two clusters on a two-point curve, which is why `deformations/cluster.py` came over with
it, and why the line is `rigging/reference_line.py` rather than a utility: a leaf utility that
reaches into the deformation code is exactly what `utils/dag.py` was cleaned of.

- **A cluster built with a namespace active raised `TypeError`.** Clusters are deliberately built in
  the root namespace and renamed into the caller's afterwards, but the rename was written
  `pm.rename('{0}{1}'.format(current_namespace, cluster))` — one argument, where `pm.rename` wants
  the node and its new name. In pymel that raises `TypeError: rename() missing 1 required positional
  argument: 'newname'`. So every cluster built inside a namespace raised, which means the IK chain's
  pole vector guide line raised, which means a referenced rig could not be rebuilt. That is the
  third place in this package where something broke only inside a namespace, alongside the spline
  IK's constraint weights and `frag_flag`'s. And the name it was building was wrong anyway:
  `namespaceInfo(absoluteName=True)` answers `:hero` with no trailing colon, so the two joined into
  `:heroin_namespace` rather than `:hero:in_namespace`.
- **A cluster asked for over no points was built anyway, deforming nothing.** `pm.cluster([])` does
  not refuse — it makes a cluster node and a handle connected to no geometry at all and says nothing.
  A guide line built that way would never follow either of its ends.
- **The pole vector control was wired to a locator that is deleted four lines later.** Where the pole
  vector goes has to be worked out before the IK handle exists, because building a handle moves the
  joints onto the solver's plane, so a temporary locator is put there for the control to be built on.
  But `Flag.create` wires a control to whatever it was built on, both ways — so every IK chain ever
  built came out with a pole vector control whose `driven_transform` attribute points at nothing.
  Same fault as `rig_aim_joint`, same fix: it asks not to be wired.
- **`end_joint` was quietly assigned over.** On a four-joint chain the IK solves over the first
  three and the fourth is left outside it, which is right — but it was done by rebinding the
  argument, so the `end_joint` the caller got back was not the joint they passed in and nothing said
  so. The IK's own end joint has its own name and its own key now.
- **The error for a chain of the wrong length named neither the joints nor the count** and said
  "end_joints"; an unrecognised rotate order raised a bare `KeyError`, part-way through the build,
  from a dictionary rebuilt inside the function on every call. Both now name what they were given,
  and the rotate order is checked before anything is created.
- The align group for the IK handle was built by hand — group, snap, reparent — under exactly the
  name `groups.create_align_transform` gives it, so the handle carries the same align markup every
  other aligned node in a rig does now. Finding the guide line's two clusters was ten lines of
  walking shape connections in each caller; that is `reference_line.get_line_clusters`. The line's
  `inheritsTransform` was switched off a second time after a call that had already done it. The
  0.75 the offset control is drawn at, the template display type and the grey colour index were
  numbers in the arithmetic, and the result dictionary was built a line at a time.

**Kept, with the reason written down.** Building the cluster in the root namespace is a workaround
for a Maya 2019 bug — `pm.cluster` raising `RuntimeError: Problems occurred with dependency graph
setup` when a namespace is active. Maya 2025 does not need it; a cluster built inside a namespace
comes out correctly named. The oldest Maya the pipeline supports is 2022, which has not been
checked, so the detour stays until it has been, and the comment says as much. Likewise the locator
the rotate-order change is measured onto: a control built by `Flag.create` has its rotation in
`jointOrient` and zeroes in `rotate`, where the rotate order makes no difference at all, so the
measurement is a no-op today — but that is a property of how the control was built rather than
something the function can rely on.

## `rigging/skel_utils.py` — writing a skeleton down, and building one back

A `.skl` file is JSON: one entry per joint, keyed by the joint's name, holding its world matrix, its
parent's name, whether it draws its label, and every user attribute on it — which is where the side
and region markup lives. That is enough to do the four things this module is for: rebuild a skeleton
somewhere else, merge one skeleton into another, put a posed skeleton back into its bind pose, and
put markup back onto a skeleton that has lost it.

- **Exporting over a read-only file failed.** Every `.skl` in this pipeline comes out of Perforce
  read-only until it is checked out, which is exactly what `fileio.touch_path` is for — but it was
  called with the path *without* its extension, so it made sure the folder existed and never touched
  the file that was about to be written.
- **Restoring markup deleted every user attribute on every joint, Maya's own included.** A bound
  joint carries `lockInfluenceWeights`, which is a user attribute and is where an artist's per-joint
  weight locks live. It was carefully left out of what gets written down and then deleted here, so
  putting a skeleton's markup back silently cleared every weight lock in the skeleton. Anything else
  another tool had put on a joint went the same way, connections and all — the purge did not look.
- **A skeleton whose root is not called `root` lost its root's markup and its root's bind pose.**
  Both readers looked the root's entry up under the literal key `'root'`, while the writer keys every
  joint, root included, by its own name. So a prop or a face skeleton rooted anywhere else got a
  warning and a skipped root. The entry is found by name now, falling back to the entry with no
  parent — which is the root by construction whatever it is called, and which also covers the case
  the literal lookup was there for: a duplicated hierarchy whose root Maya has put a number on.
- **The joint radius scale was the sum of the bounding box's maximum corner**, so it depended on
  where in the world the skeleton was standing rather than on how big it was. The same skeleton a
  thousand units along X came out with radii eight times bigger; one standing below the origin came
  out with a **negative** radius, which draws nothing at all. It is the longest side of the bounding
  box now, which is what the comment beside it always claimed. **And it never set the root joint's
  radius**, because `listRelatives(allDescendents=True)` leaves the node it starts from out.
- **Importing a skeleton renamed whatever else in the scene shared a joint's name.** A joint has to
  end up under the name it was written down as, because every other entry's `parent_node` refers to
  it by that name — so a clash does have to move. But it moved silently, and it could be anything: a
  mesh, a control, a locator. It says which node it moved and where it went now. The joint was also
  created directly under its final name, and Maya does not uniquify by adding a 1: `b_spine_01` taken
  gives **`b_spine_02`**, which is very likely the next joint in the same file, and the two then
  fight over that name. It is created unnamed and renamed.
- **A file in which every entry names a parent inside the file describes a loop, not a skeleton** —
  and it built all the joints first, then raised `Cannot parent an object to one of its children` out
  of the middle of the parenting, leaving them in the scene. The roots are worked out from the data
  before anything is created now, and a file naming a parent it does not contain is reported rather
  than raising `KeyError`.
- **`.skl` paths were trimmed with `path.replace('.skl', '')`**, five times over, which strikes
  anywhere in a path and not only the end: a file under a folder called `.skl_backups` came out
  somewhere else entirely. All five were unnecessary — `strings.append_extension` adds the extension
  only when it is not already there.
- **`import_skeleton` answered a `(None, [])` tuple when the file was missing**, and then handed it
  straight to `scale_skel_radi`, which handed it to `pm.xform` as a node.
- **`position_twist_joints` reversed the list it was given, in place**, so every joint was placed at
  the opposite end of the segment from where its own docstring says it goes. The docstring is the
  only statement of intent either way — its one caller passes a raw selection — so the reverse went
  and the docstring stands: first in the list, nearest the parent. It does not touch the caller's
  list any more either.
- **`create_skeleton_dict` was a second copy of `joint_utils.create_skeleton_dict`, and
  `get_skel_dict` a third.** The three differed only in whether they mentioned that two joints with
  one name can only be one entry in the lookup. That warning is on the surviving one now; the other
  two are gone, and `get_skel_dict` had no callers at all.
- `SkeletonData` carried `DATA_TYPE`, `NICE_NAME`, `PRIORITY`, `can_represent`, `icon` and
  `functionality` for a data-part registry that no longer exists, and reached its own methods through
  `self.functionality()['read_data']()`. `export_data` wrote the joints under a `joints` key with the
  Maya version beside them — a format no reader in the pipeline understands — and nothing called it,
  which is the same test `serialize_flag` was dropped by. What is left is a path and two methods, and
  dropping `icon` takes this module's dependency on `mca.common.resources` with it.

## `rigging/frag/frag_base.py` — the metadata node a rig is described by

A FRAG rig is a Maya rig with a second, invisible structure over it: a graph of `network` nodes, one
per piece of the rig, each carrying the *name of the Python class* that knows what to do with it.
That name — the `fragType` attribute — is all a node carries, so `FRAGNodeRegister` keeps a table of
every FRAGNode subclass by class name, and `FRAGNode(node)` turns a node found in a scene back into
an instance of the right class. The graph itself is message attributes: a child's `fragParent`
connected from its parent's `fragChildren`.

Each class also carries a `VERSION`, and each node the version it was built at. When a component
changes what it stores, its version goes up and it gains a `_update_version_<n>_to_version_<n+1>`
method, which `update()` is meant to run.

- **No rig has ever been brought up to a new component version.** `update()` builds the method name
  out of the version it reads off the node — and the version is stored on a **`double`** attribute, so
  a node at version 1 reads back as `1.0` and the method asked for is
  `_update_version_1.0_to_version_2.0`. Five components (`ikfk`, `reverse_foot`, `spline_ik`,
  `channel_float`, `ribbon` ×2) carry a `_update_version_1_to_version_2`, and every one of them has
  been unreachable: opening an old rig and updating it raises `AttributeError` instead. Versions are
  read as whole numbers now, a node built by a newer pipeline than the code reading it is left alone
  with a warning rather than walked past in silence, and a missing step names the node, the class and
  the method.
- **`get_frag_node_parents` raised as soon as a node had a parent at all.** Its first line is
  `pm.PyNode(node)`, and it passed its own answer — a `FRAGNode` — back into itself, which
  `pm.PyNode` refuses with `MayaAttributeError`. The only input it could ever answer for was a node
  with no frag parent, which answers the empty list. Nothing in the pipeline called it, so it is
  dropped; the module-level `get_frag_parent` takes a `FRAGNode` as well as a node now, which is the
  trap it fell into.
- **Reloading the package left the register pointing at the classes from before the reload.** Each
  class name is registered once. On a second import the metaclass compared the two module paths,
  found them equal — which is exactly what a reload looks like — and then did nothing, so the
  register kept the stale class and `FRAGNode(node)` handed back instances of it, with every
  `isinstance` check against the new class failing. `frag/__init__.py` drops its submodules from
  `sys.modules` and imports them again *specifically* so edited code is picked up, so this is the
  case that mattered. A class from the same module now replaces the registered one; only a clash from
  a genuinely different module is refused.
- **One FRAG node this pipeline cannot wrap stopped every walk over the scene.** `get_all_frag_nodes`
  wraps everything `is_frag_node` says yes to, and `is_frag_node` says yes to a node carrying only
  the legacy `xrigType` — which `FRAGNode` then refuses, as it does any `fragType` naming a class
  whose package is not loaded. So one legacy node, or one component from another project, and the
  call raised. The walkers report what they cannot wrap and carry on. The mismatch itself stays:
  `is_frag_node` answers "is this one of ours", and a node with no class name on it is still ours and
  still unwrappable.
- **`is_frag_node(None)` raised** `RuntimeError: Too few arguments given` out of `pm.objExists`, and
  asking about a name that is not in the scene logged a *warning* — which is a question answered, not
  a problem.
- **A `frag_type` that is not a registered class left an orphan network node behind**, because
  `create` made the node, wrote all four attributes, and only then tried to wrap it.
- **`set_frag_parent` accepted something it could not use.** It checks its argument with
  `is_frag_node`, which says yes to a raw network node, and then reaches for `.pynode` on it.
- `get_frag_root` and `get_asset_id` read the node passed to them and never touch `self`, which their
  own docstrings had to apologise for; they are `staticmethod`s now, and every existing caller — all
  of which call them on an instance — still works. `get_frag_root`'s loop recomputed the same parent
  on the iteration it found the root. The two node-unwrapping ladders in `connect_node` and
  `connect_nodes` were the same ladder twice, now one `as_pynode` — public, along with
  `wrap_frag_node`, because every module in the package wants both. `add_frag_child`, `set_attr`,
  `add_attr`, `list_attr_connections` and `list_frag_node_connections` have no callers anywhere in
  the pipeline and are gone; the forwarders that do have callers stayed.

`frag/__init__.py` came over as it stands — it is a recent rewrite, and the dynamic export is what
lets a build script write `frag.FKComponent` without knowing which module defines it. Its
`COMPONENT_MODULES` lists what has been ported rather than what there will be, the same way the
package manifest does, and entries come back as the components land.

## `rigging/frag/rig_component.py`, `rigging/frag/keyable_component.py` — what every component has

A rig is built out of components — an arm, a spine, a twist helper, a space switch — and each one is
a metadata node plus two groups: the controls the animator sees, and a `NO_TOUCH` group holding
everything that makes them work. `RigComponent` is the half every component has, with or without
controls; `KeyableComponent` adds the control group and the things that only mean anything once a
component has both controls and joints.

**`align_component` has never aligned anything, and that one needs a decision.** Both classes take an
object to snap their groups to, and both snap the group and then `makeIdentity(apply=True)` it on the
next line. Freezing an empty transform puts its matrix straight back to identity: the rotation is
discarded outright, the position survives only as the group's rotate and scale pivots, and a child
parented under the group afterwards lands at the world origin either way — all three verified in
Maya. So every component that passes `align_component` has been getting nothing from it. It is left
exactly as it is, because the freeze is what every rig in the depot was built against: making the
alignment survive would move the two groups, and everything constrained to them with an offset, on
every rig. Either the alignment was meant to survive and the components that rely on it have been
building unaligned all along, or the parameter should go — and that is a call to make deliberately,
not a thing to quietly change under two thousand checks.

- **Attaching a component twice left the objects from the first attachment registered as well.**
  `attach_component` clears the two *component* lists before writing them again and never touches the
  two *object* lists, so they grow. `buildarig` reads exactly those object lists to rebuild an
  attachment, so a component that had been reattached rebuilt against its old parents as well as its
  new ones. All four lists are cleared now.
- **`attach_component` read `flagGroup` whether or not the component had one.** It lives on
  `RigComponent`, which is the base for components with no controls at all — a twist helper, an
  attachment — and the group it reaches for is added by `KeyableComponent`. It constrains whichever
  of the two groups the component actually has now.
- **The two groups a component gets were named with different spellings of the same side.** The side
  is lower-cased on the way into `RigComponent.create`, which names the `NO_TOUCH` group, and then
  used as it came in to name the control group — so a component built for `'Left'` came out with
  `NO_TOUCH_left_arm` beside `flags_Left_arm`, and its markup said `left` while half its node names
  said `Left`.
- **`get_bakeable_rig_nodes` counted every control after the first one worth baking as worth
  baking.** It collects the keyable attributes of every control into one running list and then asks
  `if constraint_list or attr_list` — the *running* list, not this control's — so once any control in
  the component had a driven attribute, every control after it went into the bake whether or not
  anything was driving it.
- **`bake_to_skeleton` and `get_bakeable_skeleton_nodes` read `bindJoints` without asking whether the
  component has it**, while the `bind_joints` property sitting between them does ask. A component
  with no joints — a space switch, a channel holder — raised.
- **A component built with no parent raised `AttributeError`** in both classes: `create` asks the
  parent what type it is, and `FRAGNode.create` is happy to be given nothing.
- **`serialize_component` could not run.** It called `get_point_attach_component`,
  `get_orient_attach_component` and `get_scale_attach_component`, and **no class anywhere in the
  pipeline has any of the three**, so any component with a constraint on its `NO_TOUCH` group raised
  `AttributeError`. It also reset the entry it was about to fill one line above the `if not ...` that
  was meant to keep the first of several constraints, so that guard could never fire. Nothing called
  it and nothing anywhere reads the shape it produced — the only serializer the pipeline actually
  uses is `MultiConstraint`'s, which stands on its own — so it is gone rather than propped up with
  three methods invented to satisfy it. Dropping it also takes `chain_markup`, `frag_flag` and
  `lists` out of this module's imports.
- `childAttachments` is added to every component and **nothing in the pipeline has ever connected
  anything to it**, so `attached_children` has always answered an empty list. The attribute and its
  reader stay — a rig built without it would differ from every rig so far for no gain — but what they
  are is written down rather than left to be found out. `frag_base`'s `as_pynode` and
  `wrap_frag_node` are public now, because every module in the package wants both.

## `rigging/frag/frag_root.py`, `skeletal_mesh.py`, `frag_rig.py`, `display_layers.py` — a whole rig

These four are the rig itself, and they had to come over together: `frag_root` imports `frag_rig` and
`frag_rig` imports `frag_root`. A rig's **root** says which asset it is and carries the skeleton; the
**skeletal mesh** node owns the geometry and the two groups it lives in; the **rig** makes the three
groups everything hangs under and answers the questions that are about all of it at once; the
**display layers** node holds the layers that keep its viewport tidy.

- **A rig build took every mesh in the scene, not its own.** `SkeletalMesh.create` gathers the
  geometry through `get_all_meshes_from_scene`, which looks at `pm.ls(type=pm.nt.Mesh)` with no regard
  for the namespace — while `get_blendshapes_from_scene` sitting directly beside it works through the
  rig's markup and *is* namespace-aware. So building a rig in a scene that had anything else in it —
  another character, a prop, a reference — took the other thing's geometry and parented it into this
  rig's `grp_skins`.
- **The variant a rig was built for has never been recorded on the node.** `create` adds a `variant`
  attribute and never writes to it, and sets `variantVersion` to the literal `1` rather than to the
  `variant_version` it was given. The arguments do reach `buildKwargs`, so nothing is lost — but every
  rig in the depot reads variant `''` at version 1 on the two attributes meant to hold them.
- **Reading a rig's scale rebuilt part of the rig.** The `rig_scale` property, when the attribute was
  missing, called `_scale_components` — which adds the attribute, wires it to the top group, and calls
  `set_scale()` on every keyable component in the rig. A property read that changes the scene is the
  same fault `chain_markup`'s getters had. Reading it answers the scale now, off the top group when
  the attribute is absent, and `add_rig_scale()` is the thing that wires it.
- **A rig with utility controls and no detail controls left them on no layer at all.**
  `create_display_layers` puts utility controls on the detail layer, inside the `if detail_flags:`
  that builds it. Either kind is enough to build the layer now.
- **`DisplayLayers.remove_objects` ignored the layer it was given.** It looked the layer up, used it
  as nothing but a gate, and then moved the objects it was handed onto Maya's default layer whatever
  layer they were actually on — so taking a control off the detail layer took it off the skeleton
  layer too, as long as the detail layer existed.
- **`DisplayLayers.remove` never deleted the node.** Its last act is `pm.delete(self)` — the wrapper,
  not the node — which pymel refuses, inside a bare `except Exception` logged at *debug*. Removing a
  rig's display layers deleted the layers and silently left the node behind, every time.
- **Two `FRAGNode` wrappers around one node were not equal to each other**, and a set of them held
  both. Every walk over the graph builds new wrappers, so `list(set(all_frag_rigs))` in
  `get_frag_rigs` never removed a repeat and `x not in found` was always true. `FRAGNode` compares and
  hashes by the node it wraps now, and has a `__repr__` that says which node that is.
- **`color_flags` turned an override on for a side it had no colour for.** A control whose component
  says `top` is not in the colour table, so `overrideEnabled` was set and `overrideColor` was not,
  leaving the control drawn in whatever index it already had.
- **Four functions reached through a rig root without checking there was one** — `get_root_joint`,
  `get_group_skins`, `get_group_blendshapes` and `get_frag_rig` — so asking any of them about a node
  that is not in a rig raised `AttributeError` on `None`. And `get_frag_skeletal_mesh` and
  `get_frag_rig` both raised on a node whose `fragParent` exists but is connected to nothing, because
  `FRAGNode(None)` gets as far as `pm.PyNode(None)`.
- **`get_frag_skeletal_mesh` answered two different kinds of thing** — a wrapped node down one path
  and the raw `fragParent` connection down the other — and its docstring said it returns a `FRAGRig`.
- **`get_all_frag_roots` stopped on the first node it could not wrap**, so one pre-FRAG node or one
  component from another project in the scene and it raised instead of answering the roots it found.
- `get_frag_root` was the same walk as `FRAGNode.get_frag_root` written twice, differing in whether a
  root is recognised by its class or by its `isFragRoot` attribute; it does the walk once through the
  base now and then says whether what came back really is a `FRAGRoot`. `create_display_layers` and
  `create_display_layers_for_cam` were the same thirty lines twice over, differing in two things, and
  the six control queries were the same two lines six times. `_get_layer_absolute_name_from_layer`
  answered a name *without* its namespace, which is the opposite of an absolute name — it is
  `naming.get_basename`. An asset id the registry does not know became `'missing_name'` in silence.
  The layer display types, the group names and the attribute names were all bare strings and numbers.

Two things about this group are written down rather than changed. `FRAGRig.get_flags` finds every
control in the rig's *namespace*, which is right for a referenced rig and for one rig in a scene, but
two rigs sharing a namespace each answer the other's controls — and nothing on a control says which
rig it belongs to except the component above it. And `DisplayLayers`' `layers` attribute is a multi
*string* attribute with the layers' message plugs connected into it, which Maya allows; it works, but
`merge_values` cannot tell a duplicate from a new entry on it, so a layer added twice would be
connected twice. Nothing does that, because a layer is only added when the rig has none by that name.

## `rigging/frag/multi_constraint.py` — the switch that lets a control follow one thing or another

A hand should follow the arm most of the time, the chest when a character folds its arms, and the world
when it rests on a table. That is a multi constraint: the control is matrix-constrained to one of a
list of targets, an enum on it says which, and a pair of `choice` nodes swap the matrices over when the
enum changes. `multi_constraint_rig` builds the network — already ported; this is the metadata node
that remembers what was built, so the switch can be found, described and taken apart.

- **Building a second switch on a control raised something unreadable.** The builder refuses when the
  control already carries the enum — it logs why and answers a result with nothing in it — and `create`
  then connected those empty slots straight to the node, so what the caller actually saw was
  `MayaNodeError` out of `pm.PyNode(None)`. Same for a switch given no targets. It checks the build
  worked and says what happened now.
- **`remove` raised when there was nothing to put back.** It reparents whatever the control's group
  held with `pm.parent(pm.listRelatives(group), parent_group.getParent())` — and when the group is
  empty *and* the group above it sits at the world root, that is `pm.parent` with no arguments left at
  all, which falls back to the selection and raises `TypeError: Error retrieving default arguments`. A
  switch whose control has been deleted is exactly that pair of nothings.
- **`remove` raised on a node whose switch or source object had gone**, both being message
  connections that can answer nothing, and **deleted `sourceMultiConstraint` without checking it was
  there** while guarding every other attribute in the same list with `hasAttr`.
- **`get_build_kwargs` was the third copy of itself**, which its own docstring admitted and left for
  later: `RigComponent` had one, this had one, and `SkeletalMesh` writes the attribute and had no
  reader at all. It is on `FRAGNode` now, where all three inherit it.
- The separator the enum sits under was the bare string `'__'` here and `SEPARATOR_ATTR` in the module
  that puts it there; the six nodes a switch is made of were six near-identical `connect_node` lines;
  and a `# strip wrapped nodes` comment sat above a line that strips nothing.

**A correction worth recording, because it is the kind of thing that gets "tidied" wrong.** I first
read `remove`'s single `pm.delete(group, node, multiMatrix, decompMatrix)` as the fault that
`matrix_nodes.remove_matrix_constraint` had — Maya's delete following history and taking later names
with it — and split it into separate deletes. Maya disagreed: the one call is fine, and deleting those
nodes *one at a time* is what fails, because by the third delete the component's own node has gone
with them. The suite pins that down, so the next reader who finds a four-node delete ugly finds out
why it is one call before they change it.

## `rigging/frag/animated_curves.py` — animation taken off a rig so it can be put back on another

An animator's work is a set of curves hanging off a rig's controls. Lift those onto a node of their own
and you have something that can travel: saved out as a clip file, carried on a skeleton while the rig
around it is rebuilt, or handed to a different character. One compound attribute per object, holding
the curves that were on it, named so they can be found again.

- **Restoring animation could put curves on the wrong channels.** The curves and the attributes to put
  them on were worked out as two separately sorted lists and then paired **by position**. They line up
  only while both are the same length — and the curve list leaves out anything stored without a curve
  while the attribute list does not, so one such gap shifted everything after it by one: an arm's
  translateY landing on its translateZ, quietly. There is a mapping from node attribute to object
  attribute right there in the same function, so the two are paired by *name* now, which cannot drift.
  `get_stored_curve_pairs` had the same fault and the same fix; both go through one lookup.
- **The stored start frame stayed at 0 for any animation starting at or after frame 0.** `startFrame`
  begins at 0 and was only ever *lowered* — `if key_time[0] < startFrame.get()` — so an animation on
  frames 10 to 20 was recorded as starting at 0. Everything that shifts a clip to a new start frame
  works the distance out against that number, so every such clip landed however far the animation
  began from zero out of place. The first curve stored sets the range now and the rest widen it,
  tracked by a flag on the node so an older node picks it up on its next store.
- **A whole-number start frame worked and a fractional one did nothing.** Three places tested
  `isinstance(start_time, int)` before shifting, which is False for `1001.0` — while all three
  docstrings said `float`. Shifting a clip to a frame typed into a tool, which hands over a float,
  silently did not move it.
- **The shift compounded across an object's attributes.** `start_time` was turned into an offset
  *inside* the loop over the attributes and assigned back over itself, so the second attribute's
  offset was worked out from the first attribute's offset. It is worked out once, before anything
  moves.
- **Storing animation onto a skeleton in a namespace renamed the node to nonsense.** The node was
  moved with `str(node).replace(old_namespace, new_namespace)` — and when the node is in the root
  namespace the old namespace is the empty string, which `str.replace` inserts the new one **between
  every character** of. `AnimatedCurvesComponent` became `hero:Ahero:nhero:ihero:m…`.
- **`restore_from_anim_curves`' shift argument is `time_offset`, not `start_time`** — the one rewiring
  note this module owed from the animation port. It was passed by keyword, so the call raised
  `TypeError` the moment a shift was asked for. While paying that off: `anim_layers`'
  `restore_for_anim_layers` and `adjust_layers_timeline` took the same *distance* under the name
  `start_time`, which is what `anim_curves` calls `time_offset`. Two functions taking the same number
  should not disagree about what it means; both are `time_offset` now.
- **Restoring the first attribute of an object disconnected every animation layer the node held**, so
  every attribute after it had none to find. That belongs after the object is done, not inside the
  loop over its attributes.
- `_correct_attribute_names` looked for the object's name *anywhere* in a child's name rather than at
  the front, then replaced it everywhere rather than once, and dropped a child it did not find the name
  in without a word. `_get_compound_attributes` answered None where its docstring promised a list. The
  warning for a node not on a skeleton said the skeleton had no node on it, which is the opposite way
  round. `flag_count` and `obj_count` held objects, not counts.

## `rigging/frag/ik_component.py`, `fk_component.py`, `ikfk_component.py` — the three a limb is made of

An arm or a leg is one of these three: FK, which gives the animator a control per joint nested so the
shoulder carries the elbow; IK, which gives them one control for where the hand goes and one for
which way the elbow points; or both at once with an attribute that fades between them. Everything
larger in a rig — a reverse foot, a ribbon spine, a whole character template — is built out of these.
All three drive a *duplicate* of the bind chain and constrain the bind joints to the duplicate, which
is what lets a rig be torn down and rebuilt without the skeleton being touched.

Two things every component that can be driven by an external skeleton needs were written out again in
each one, so they are in `keyable_component` now: `KeyableComponent.matching_chain`, which finds the
run of joints on the other skeleton that answers to this component's region and side, and
`constrain_to_pole_vector`, which drives a pole vector control — the one control in a rig with no
joint of its own to follow.

- **Building a limb wiped the Maya joint labels off the joints it drives.** `ik_component` copied
  `side`, `type` and `otherType` from the IK offset control onto the end bind joint and from the pole
  vector control onto the middle one; `ikfk_component` did the end joint the same way. A control built
  by `Flag.create` carries the *defaults* for all three, whatever it was built on — verified in a real
  Maya: side 0, type 0, `otherType` `'jaw'`. So those joints came out labelled centre/none wherever
  they started. That is not cosmetic. `JointMarkup.side` falls back to Maya's own joint-label enum when
  a joint carries no `skelSide` markup, which is exactly what an imported skeleton is, so building a
  rig changed the side the rest of the pipeline reads off the elbow and the wrist. There is no reading
  under which copying a control's default labelling onto a joint is wanted; the nine lines are gone.
- **`offset_flag=True` on an FK component had never once worked.** `create` added `offsetFlag` by hand
  as a plain message attribute and then wired the control to it with `connect_nodes`, which hands a
  *list* to a non-multi attribute: `RuntimeError (kFailure): Object does not exist`, every time, for as
  long as the argument has existed. The pre-add is gone — `connect_node` makes the attribute it needs —
  and the single control goes through `connect_node`.
- **A rebuilt FK component silently lost its scale setting.** `create` takes `constrain_scale` and
  wrote it down under `buildKwargs` as `allow_scale`. `allow_scale` is not a parameter, so a rebuild
  handing the recorded arguments back landed it in the `**kwargs` the signature absorbs and dropped it:
  every rebuilt stretchy component came back unable to stretch. It is recorded under the name it goes
  back in through, and `set_scale` reads either name so components already built still answer. The
  suite checks the general case — that every key in `buildKwargs` is a parameter of `create` — rather
  than that one name, because this is the second component to get it wrong.
- **A rebuilt FK or IKFK component drew default-sized controls.** `scale` was never written down at all.
- **`FKComponent.set_scale` raised on a rig with no scale attribute.** It read `frag_rig.pynode.rigScale`
  without asking. That used to be hidden by `FRAGRig.rig_scale` adding the attribute as a side effect of
  being *read* — the fault recorded in `frag_rig`'s own section — and now that reading is just reading,
  the component says what is missing and leaves the group alone. `FRAGRig.add_rig_scale()` is what wires
  it, and it calls `set_scale` on every component afterwards, so the order still works out.
- **`attach_to_skeleton` attached nothing at all, silently, when the rig had more controls than the
  skeleton had joints.** `if flag_list and len(flag_list) <= len(joint_list)` — so a four-control spine
  driven from a three-joint markup chain came back with an empty list and no complaint. The controls and
  joints are paired as far as the shorter of the two goes now, and the mismatch is reported.
- **`attach_to_skeleton` raised on a short chain, in the IK components.** `joint_list[1]` and
  `joint_list[2]` were read without asking how long the chain was, and `create_pole_vector_locator`
  answers `None` for a chain of fewer than three joints — which the next line called `setParent` on.
  Both go through the shared helpers, which ask.
- **`IKFKComponent.get_flags` could hand back a list with `None` in it.** It appends six attribute reads
  and then wraps every one of them in `Flag`, so a component that has lost a control raised from inside
  the wrapper rather than saying which one was missing.
- **The chain-length guard said three and accepted four**, in both IK components, and named neither the
  joints nor the count: `RuntimeError('There can only be 3 joints between start_joint and end_joint
  inclusively')`. Three or four is `ik_chain`'s own rule — four is a leg with a ball joint — so it is
  `ik_chain.VALID_CHAIN_LENGTHS`, asked *before* anything is built rather than after the node, the
  groups and a duplicated chain are already in the scene.
- `fk_flags[1]` — the elbow or the knee — had two rotate axes locked off by bare index with nothing
  saying why. It is the middle of the three joints the IK solves over, a hinge; it is named and guarded
  now. The FK controls were read out of the result twice under two names, the duplicated chain was
  parented into the no-touch group twice, and the first control's align group was read as a raw
  attribute, which a control built without one does not have. `get_offset_flag` promised a `Flag` and
  returned the raw node. `for x in range(len(ctrls))` with `if x == 0 / elif x > 0` is `enumerate`.
- `FKComponent.set_scale` looked the divide node its rig's components share up with
  `pm.ls('<namespace>::rig_scale_multi', r=True)` — a search through every namespace, under a name with
  the colon doubled. One rig's component could find another rig's node. It asks its own namespace now.

**Two findings that came out of writing this, both worth keeping.** `IKFKComponent` locked each
control's channels as that half of the component was built, and the list it locks includes visibility —
then wired visibility to the switch afterwards. A locked plug cannot be connected to, so the version of
this file I first wrote raised `The attribute 'f_left_arm.visibility' is locked and cannot be
connected`. The original got away with it by locking everything last, which reads like tidiness and is
load-bearing; it says so now. And the blend reads a constraint's weight aliases as `[0]` and `[1]`, FK
then IK — true of a fresh constraint, because that is the order the targets are added two lines above,
but `pm.orientConstraint` on a joint that *already* has one hands back the same node with the new
targets appended, so those two indexes are then somebody else's weights. It takes the last two.

**A decision left as it is, for Nathan.** `FKComponent.get_start_flag` returns the **last** control and
`get_end_flag` the **first**. `fk_chain` builds its `flags` list root first, so the two names are the
wrong way round and always have been — but around twenty callers in the rig templates were written
against the behaviour rather than the names, and quietly swapping them would move every rig built from
those templates. The behaviour stands, the docstrings say what each one actually returns and why, and
the rename is on the list to do when the templates are in front of us.

**The first component whose version migration can actually run.** `IKFKComponent` is `VERSION = 2`, and
`_update_version_1_to_version_2` renames the four build attributes that version 1 stored in snake_case.
It is one of the five migrations in the pipeline that had never executed — `FRAGNode.update` built its
method name from a version held on a `double` attribute, so it looked for
`_update_version_1.0_to_version_2.0`, which no class has ever had. With `frag_base` rounding, the step
is reachable, and the suite drives it end to end: build a component, put its attributes back under the
old names, set the version to 1, call `update`, and check that each attribute is there under its new
name and still wired to what it was wired to.

## `rigging/frag/mesh_component.py` — which of a character's meshes is which

A rig is built over a skeleton, but a character is a pile of meshes: the body that gets skinned, the
head carrying the blendshapes, the source mesh those shapes were sculpted from, eye cards, teeth. A
tool downstream has to be able to ask for one of them by name instead of guessing at a naming
convention, so this node holds one compound attribute per *category* — `skin_mesh`,
`blendshape_mesh`, `source_mesh`, whatever the caller passes — whose children are message attributes
wired to the meshes. A child can hold one mesh or a list of them, which is how "the left eye's cards"
fits beside "the head". It hangs under the `SkeletalMesh` node, and on create it moves whatever is in
the blendshape category under the rig's blendshape group, because that group is what gets hidden and
left out of the export.

The shape the categories go in is now the shape they come back out in: `get_connections_as_dict`
answers exactly the dictionary `create` takes, so a node can be rebuilt from one that exists. That is
a round trip the suite drives, and it is also the thing that was broken.

- **`get_connections_as_dict` has never once answered correctly.** It builds two lists — the meshes
  wired to a category, and the category's child attributes — and pairs them *by position*, with the
  attribute list offset by one. They do not line up, for three separate reasons. The offset of one
  lands on the hidden bool child that `set_compound_attribute_groups` adds to every compound as a
  channel-box workaround, so the first mesh of every category came back under the key `_hidden`. The
  mesh list is de-duplicated and skips children with nothing on the end of them, while the attribute
  list skips nothing, so a single unconnected child shifts everything after it by one. And a child
  holding a *list* of meshes puts one entry in the attribute list and several in the mesh list.
  Checked in a real Maya: three meshes under `skin_mesh` came back as
  `{'_hidden': mesh_a, 'head_mesh': mesh_b, 'mouth_mesh': mesh_c}` — every mesh under the wrong name,
  and the last attribute dropped off the end. It is built from the attribute side, by name, now. This
  is the same fault with the same fix as `animated_curves` pairing curves with channels by position,
  which is twice in `frag/` now: **two lists built differently and then zipped is the shape to look
  for.**
- **`get_mesh` and `reconnect_mesh` raised on a node that does not have the category**, from inside
  the guard that is there to stop exactly that: `pm.hasAttr(self.pynode.attr(category), …)` evaluates
  `self.pynode.attr(category)` first, which is a `MayaAttributeError` when the category is missing.
  `get_mesh_list` — the same lookup with a different answer, twenty lines below — checks for the
  compound first, so two methods beside each other disagreed about whether a missing category is an
  error. All three go through one lookup now.
- **`reconnect_mesh` only half reconnected a mesh to a category that holds a list.** It connects to
  the array attribute itself rather than to an element of it. Maya allows that — checked in a real
  Maya — and the result is a mesh that appears in the attribute's connections but sits at *no index*:
  the array's indices are unchanged, so anything walking the list by index misses it and rewriting
  the category throws it away. It takes the next free element.
- `get_mesh` and `get_mesh_list` each gave the other's answer for the wrong kind of child: `get_mesh`
  on a list-holding child answered a list, and `get_mesh_list` on a single-mesh child answered a
  one-item list. They share a body, and each says what it does with the other kind. `get_mesh_list`
  also promised a list and answered None when it found nothing — the shape that makes every caller
  write `or []`. The two questions "there is no such name" and "nothing is wired to that name" have
  different answers now: None and `[]`.
- `create` asked its parent for the blendshape group without checking that the parent is a thing that
  has one. The move is its own method, so a node can be rebuilt in place without rewiring everything.

`get_connections_as_dict`, `remove_category` and `get_all_attrs_from_category` have no callers
anywhere in the pipeline. They are kept under the standing decision for an unused function that is
the only way to undo something, or the only place showing how a structure is meant to be walked —
these are both, and `get_connections_as_dict` is the round trip of `create`, which is the thing a
rebuild needs.

`face_mesh_component.py` would land here too — it is `MeshComponent` with the face's categories named
and the common meshes wrapped — but it imports `modeling/face_model.py`, which imports
`face/face_utils/`. It moves to the `face/` stage.

## Four modules could not build anything while a namespace was active

Found while writing the mesh component's suite, and worth its own note because it is one fault in four
places. `create` takes the rig's namespace off its parent and makes it current:

```python
root_namespace = frag_parent.pynode.namespace().split(':')[0]
pm.namespace(set='{0}:'.format(root_namespace))
```

`'hero:'` is a *relative* name, resolved against whatever namespace is already active. From the root
it works. From inside `:hero` — which is where a tool that has just been working on that rig leaves
it — Maya looks for `:hero:hero` and raises `RuntimeError: No namespace matches name: 'hero:'`.
`skeletal_mesh`, `multi_constraint`, `ik_component` and `ikfk_component` all had it; `fk_component`
and the depot's own `mesh_component` went to the root first and did not. All four now call
`namespace.set_namespace(root_namespace, check_existing=False)`, which is the function that exists for
this, and each of the four suites builds its node with the rig's namespace active.

## The four one-control components — `world`, `cog`, `pelvis`, `clavicle`

Each of these is one control over one joint, and between them they are the top of every rig: the world
controls that carry a character through a scene, the centre of gravity everything hangs below, the
pelvis that rocks the hips about the base of the spine, and the clavicle. They are grouped here
because they share a shape — build a duplicate, stack one control on it, constrain the bind joint to
the duplicate — and because all four carried their own copy of the twelve-line skeleton lookup that is
now `KeyableComponent.matching_chain`.

- **A COG's fallback for finding the joint to follow could never reach its last choice, and could
  hand back None.** A COG is not a joint on a skeleton, so its region and side rarely match the
  markup, and `attach_to_skeleton` is written to try three things in order: the matching chain, the
  joint marked as the start of the animatable hierarchy, then the pelvis. The second was
  `joint_list = [hierarchy_start]` followed by `if not joint_list:` — a one-item list is true whatever
  is in it, so the pelvis was never looked for, and a skeleton with no hierarchy start gave `[None]`,
  which the guard below then quietly swallowed. Each choice is asked for on its own terms now, and
  the suite drives all three plus the case where a skeleton offers none of them.
- **A clavicle looked its chain up with a pymel `Attribute` instead of a string.** `skel_region =
  skel_region or self.pynode.region` — that is the attribute object, not the value on it, and it goes
  straight into a dictionary lookup, which matches nothing. So a clavicle whose own joints carry no
  `skelRegion` markup — an imported skeleton, which is exactly the case the fallback exists for —
  silently drove nothing at all. `FKComponent`, which `ClavicleComponent` inherits from, used the
  properties two lines away from the same spot.
- **`WorldComponent.attach_to_skeleton` could answer `[None]`.** It returns `[constraint_node]` with
  no guard, and both the lookup and `parent_constraint_safe` answer None — the lookup when nothing on
  the skeleton matches, the constraint when every channel it would drive is locked. Every caller then
  iterates and deletes a list with None in it. Every other component guards that one line.
- **A pelvis built over a start and end joint that are not a chain raised `IndexError` four lines
  before the code that looks like it is guarding that.** `duplicate_chain` answers an empty list for a
  pair it cannot walk between, and the next line is `rev_chain[0].setParent(...)`. The thing that
  reads like the guard — `for base, reverse in zip(chain_between, rev_chain): …; break`, a loop whose
  last statement is `break` — comes after it and never protected anything. The question is asked
  before anything is built now, and refused the way the IK components refuse a chain of the wrong
  length.
- **A rebuilt clavicle drew a default-sized control.** `ClavicleComponent.create` calls
  `FKComponent.create` and then overwrites the whole `buildKwargs` block, which is right — it takes a
  different argument list — but `scale` was not in the replacement and is not even a parameter. It is
  both now. That is the third component to record its build arguments wrongly; the suite checks the
  general property for all four, that every `buildKwargs` key is a parameter of `create`.
- `WorldComponent.create` walked from the root joint to itself to get a one-item list and then
  `zip`ped over it to make one constraint. `CogComponent` walked between two joints and threw the
  answer away — that walk is kept, because `get_between_nodes` warns when the pair is not a chain and
  that warning is the only reason a COG takes an `end_joint` at all, and it now says so. The pelvis
  control was marked as a sub control by setting `isSub` by hand next to `Flag.set_as_sub`. The
  pelvis parented its duplicated chain into the no-touch group twice, four lines apart. The clavicle
  had `locked_vertices` as a second name for `lock_root_translate_axes`, and there are no vertices
  anywhere near it.
- `WorldComponent.get_flags` read all three controls back and wrapped each in `Flag`, so a component
  that had lost one raised from inside the wrapper rather than saying which was missing.

**Written down rather than fixed.** `ClavicleComponent`'s `lock_root_translate_axes` defaults to
`['v']` — a visibility channel handed to the parameter named for *translate* axes. `FKComponent` locks
`['v']` regardless, so the real effect is that every clavicle control ever built has all three
translate channels free while the parameter name says otherwise. Locking them would change every rig
built from a template, so the default stands, the constant is named for what it actually is, and the
suite pins the current behaviour.

**And one thing worth knowing about the shared lookup.** `JointMarkup.side` falls back to Maya's own
joint side label when a joint has no `skelSide`, and that label always has a value — zero, meaning
`center`, on a joint nothing has labelled. So in `matching_chain` the side almost never falls through
to the component's own, while the region often does: a component built for the left, over joints
carrying no markup, looks up the *centre* chain. That is in `matching_chain`'s docstring now.

## `modeling/rivets.py` and `rigging/frag/pin_component.py` — riding the geometry

Everything else in a rig is driven by a hierarchy. A rivet is driven by the geometry: a transform that
follows a point on a mesh or a surface, so it travels with the skinning and the blendshapes under it.
The face rig is built on them, because a face control has to remember *where on the head* it belongs
as a UV coordinate — a position in space is no use across two different heads. `PinComponent` is the
FRAG component around one: a control pinned to a mesh, driving one joint.

- **`BasicRivet.attach_to_surface` built an evaluation cycle on its default arguments.** It passes the
  transform it is given into the constructor, which makes that transform *the rivet* — and then, when
  `constraint` is true, which is the default, it builds a locator, parents the locator under the
  rivet, and parent constrains the transform to it. The transform is the rivet, so it is constrained
  to its own child. Checked in a real Maya: the transform lands nowhere near the surface and
  `cycleCheck` names the plugs. The `else` branch beside it, `if transform != rivet.rivet:
  pm.parent(…)`, could never be true for the same reason. The two cases are now what they were clearly
  meant to be — with a constraint the surface drives a rivet of its own and that rivet drives the
  transform, which keeps its place in the hierarchy; without one the transform *is* the rivet — and the
  suite asserts `cycleCheck` is clean for both.
- **`BasicRivet` wired its surface reader to nothing when it was handed a transform.** It asked
  `pm.objExists('{}.worldSpace'.format(self._surface))` — string building to ask what `hasAttr`
  answers — and `worldSpace` is on the *shape*. So for a surface's transform, which is what
  `attach_to_surface` is handed and passes straight through, both that test and the `outputSurface`
  one below it were False and the reader got no input at all. It resolves the shape first.
- **This is the caller the `surface.py` fix was for.** `get_closest_parameter_on_surface` read
  `closestPoint`'s answer as `(uv, _, _)` when it is `(point, u, v)`, so every rivet attached to a
  surface without an explicit UV was placed by the closest point's X and Y where it wanted U and V.
  That was fixed when `modeling/surface.py` was ported; this module needed no change for it, and the
  suite now pins the round trip. **Any rig carrying a surface rivet built before that fix is in the
  wrong place.**
- **`MatrixRivet` is gone.** A third mechanism — two mesh edges lofted into a surface, a
  `pointOnSurfaceInfo` on the loft, a four-by-four matrix built from its normal and tangents, seven
  nodes in all. Nothing in the pipeline has ever called it, and the usage example in its own docstring
  calls `model.get_two_edges_from_close_object`, which exists in no module anywhere — so the one
  record of how to use it does not run either. `create_uv_pin` does the same job on a mesh with one
  node. Its `set_uv` also carried an unexplained `if u >= 1: u = u - 1`, which is the shape of a bug
  worked around rather than found.
- `create_uv_pin` reported a mesh with no shape through the standard library's root logger —
  `logging.warning`, not `log.MCA_LOGGER` — so the one thing it ever says went somewhere nobody is
  reading, unformatted and without naming the mesh. Its `if not isinstance(obj, pm.nt.Transform): obj
  = pm.PyNode(obj)` reads as a guard that the object is a transform and is not one: a shape stays a
  shape through `PyNode`, and the next line sets `inheritsTransform` on it.
- `connect_uv_pin` had two naming schemes in one function — splitting the locator's name and swapping
  the first word for `uvpin` when the caller passed no name, and `<name>_uvpin` when it did — and
  answered a one-entry dictionary of *strings* keyed by the locator's name, which a caller has to look
  both nodes up again from. It answers the two nodes.
- **The three methods an animator's tools call on a component — `select_flags`, `key_flags`,
  `to_default_pose` — were written out character for character in component after component, and none
  of the copies guarded an empty list.** `pm.setKeyframe([])` raises `TypeError: Not enough objects
  for this command`, and `pm.select([])` *clears* the selection, which is not what asking to select a
  component's controls means. All three are on `KeyableComponent` now, built on `get_flags`, which is
  the one method a component has to answer for itself — and they guard.
- `PinComponent` wrote `bindJoints`, `pinJoint` and `flags` with `connect_nodes` and a single node
  each, making three list attributes out of three things there is exactly one of. It recorded `side`
  and `region` among its build arguments, which are already the node's markup, and recorded the mesh
  as a node, so a rebuild was tied to that mesh still existing under that name — where the thing a
  rebuild actually cannot work out for itself, the UV, was not recorded at all. It is now. And a mesh
  that cannot be pinned to left a half-built component and its two groups behind in the scene; the
  component takes itself out again.

## `attachment_component`, `space_switch_component`, `aim_component` — three small records

Three components that are mostly bookkeeping: one records that a rig is following a node on another
rig, one records a space switch, and one records a joint that points at a control. Two of the three
had the same fault in different clothes — they built their own metadata node *before* asking whether
the thing they were recording could be made, so the failure path left an orphan component in the
scene and handed the caller None.

- **`AttachmentComponent.create` left an orphan on the one path it can fail.** It makes its node and
  writes its `buildKwargs` block, and only then looks for a `FRAGRig` under the rig root it was asked
  to attach — so a root with no rig under it came back as None with an `AttachmentComponent` node and
  its attributes still in the scene. The question is asked first.
- **`SpaceSwitchComponent.create` recorded a switch that had not been built.** `space_switch_rig`
  answers an empty result — no constraints, no conditions, no group — when it is handed no spaces, or
  when the switch attribute is already on the control. `create` wrote that empty answer onto a node
  and handed back a component whose `switchAttrName` names an enum that is not there. It builds the
  switch first, and when there is nothing to record it makes no node.
- **`AimComponent` wiped the Maya joint labels off the joint it drives**, the third component in
  `frag` to do it after `ik_component` and `ikfk_component`: three lines copying `side`, `type` and
  `otherType` from a control that carries Maya's defaults for all three. For this one the joint is
  usually an eye, and `JointMarkup.side` falls back to that label on a skeleton with no `skelSide`
  markup — so building the rig changed the side the pipeline reads off the eyes.
- **`AimComponent.get_flags` answered None for a component with no control**, where every other
  component in `frag` answers an empty list. The three methods built on it — the ones a tool calls to
  select or key a component's controls — then raised `TypeError` on iteration rather than doing
  nothing.
- **`AimComponent.create` took no `**kwargs`**, which makes it the one component a rebuild cannot
  hand a shared argument list to: `get_build_kwargs` answers everything that was recorded, and
  anything the signature does not name is a `TypeError`. The suite drives that rebuild.
- **`AttachmentComponent` is named for a side and a region it never recorded.** Every other component
  in `frag` carries its side and region as markup and the tools that walk a rig read them; this was
  the one node in a rig named for a side it could not be asked about. It carries them now.
- **There was no way to undo an attachment.** The component knows the group it inserted and the
  control group it was put above, which is everything needed; `remove` puts the control group back
  where it was and deletes the group and the component.
- `t` and `r` are undocumented short spellings of `translate` and `rotate` in both of the first two,
  read out of `**kwargs`, silently winning over the named parameters. Both signatures say so now.
  `space_switch_component` also read `default_name` — which relabels the first entry of the enum, for
  when the first space is "world" rather than a node an animator would recognise — out of `**kwargs`
  and did not record it, so a rebuild lost it.
- `AimComponent` added `distance`, `aimAxis` and `upAxis` to its node with eight `addAttr` calls, two
  of them building a `float3` and its three children by hand, where `set_attribute` works the type
  out from the value. Those three numbers are a second copy of what is in `buildKwargs`; they stay,
  because tools read them, and the readers say where they come from. `get_eye_rotations` assumes an up
  and forward axis in a comment while ignoring the component's own `aimAxis` and `upAxis` — that is in
  its docstring now, because it is the thing a caller needs to know before trusting it.

**Two misspelled attribute names kept deliberately.** `AttachmentComponent` puts
`attachementComponent` on the control group it attaches and `sourceAttachement` on the component the
attachment point belongs to. Nothing in the pipeline reads either, and correcting them would make the
attachment on every rig in the depot unreadable by this code, so they stay exactly as they are — with
constants named for what they are, and a note saying why.

## `twist_fixup_component`, `camera_component`, `s_sdk_component` — three more small ones

A twist fix-up spreads a limb joint's twist across the helper joints that carry it, so a forearm does
not shear at the wrist; it is the only component in `frag` with no controls at all. A camera component
puts a camera on an FK control. A set driven key component writes down a relationship Maya keeps
nothing but the curve for.

- **`TwistFixUpComponent` is at version 2 and has no step to get there from version 1.**
  `FRAGNode.update` builds the name of the step it needs from the two version numbers, and
  `_update_version_1_to_version_2` exists nowhere in this class or any class it inherits from — so
  every twist component built by the version that wrote 1 raises `AttributeError` the moment anything
  asks it to update, and `update_all_frag_nodes` walks a whole rig. This is the sixth component found
  with a version problem, and the first where the *step* rather than the dispatch was missing. Nothing
  about the node changed between the two versions as far as the file shows, so the step is written and
  records the version and nothing else, with a docstring saying that is what happened.
- **`CameraComponent` spells its version `LATEST_VERSION`**, so `CameraComponent.VERSION` is
  `FKComponent`'s. Both are 1, which is the only reason nothing has gone wrong: the moment either
  number moves, `update` compares the node's version against the *parent* class's and either does
  nothing or looks for a step named from the wrong pair.
- **`SingleSDKComponent` recorded the driving *node* and threw away which attribute it was.** `driver`
  is set from `drive_attr.nodeName()`, and `drive_attr` is an attribute — so a component driven by
  `f_jaw.openClose` recorded `f_jaw`, and nothing in the scene says which of that control's attributes
  the curve hangs off. Remembering the relationship is the only thing this node exists for.
- **Its default driver values are `(0, 0)`** — both ends at the same driver value, so the second key
  lands on the first, the curve comes out flat, and a component built on the defaults does nothing and
  says nothing. Both ends have to be given now, and the same value at both is refused.
- **`driven_attrs` defaulted to None and was then indexed**, which is a `TypeError` rather than a word
  about the argument that is missing.
- **It took whatever was first on the driven attribute's connections as the curve.** A driven
  attribute on a real rig usually has a constraint or a blend node on it too, and that is what went
  into `animCurves`. It asks for animation curves.
- **It renamed itself from its own current name rather than from its class**:
  `rename('{0}_{1}_{2}'.format(node.pynode, side, region))`. The first one in a scene comes out right;
  the second is `SingleSDKComponent1_center_jaw`, because Maya had already uniquified the name the
  format string read.
- **A twist joint with nothing two levels above it raised before the component existed.** The
  alignment is `joint_list[0].getParent().getParent()`, the limb joint whose rotation is being spread,
  and both of those answer None near the root of a skeleton. An empty joint list raised on
  `joint_list[0]` before `twist_setup` could say what was wrong.
- **A twist setup that could not be built left a component with nothing on it.** `twist_setup` answers
  `(None, {})` for joints it cannot use — no parent joint to take the twist from, more joints than one
  `multiplyDivide` can drive — and `create` returned the component anyway, with no `bindJoints` and
  nothing connected, so a rig carried a twist component that twists nothing.
- **A camera whose control has no free channel raised.** `parent_constraint_safe` answers None when
  everything it would drive is locked, and that went straight into `connect_node`, which puts it
  through `pm.PyNode` — and `pm.PyNode(None)` raises.
- **Neither `CameraComponent.create` nor `SingleSDKComponent.create` took `**kwargs`**, so neither can
  be handed a component's recorded argument list; `CameraComponent` also left `FKComponent`'s
  `buildKwargs` block in place, most of which its own signature has no parameter for. Both take
  `**kwargs` and record their own arguments.
- `SingleSDKComponent` built its two compound attributes by hand with `addAttr(numberOfChildren=…)`,
  which is a Maya error for an empty dictionary, and wrote each value as a *string*, so the numbers it
  recorded came back as text. `set_compound_attribute_groups` does the whole block and keeps the
  types. Six of the eight things the twist component records are single nodes written with
  `connect_nodes`, which makes a list attribute out of something there is one of.

**New on `RigComponent`: `remove`.** It existed only on `KeyableComponent`, so there was no way to take
a component with no controls out of a rig — which is exactly what a component that cannot finish
building needs in order not to leave itself behind. `KeyableComponent` extends it with its control
group.
