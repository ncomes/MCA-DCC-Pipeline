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

**707 checks in 10 suites** so far.

`mayapy` is a full Maya with no window: it opens scenes, builds nodes and evaluates
deformers. Run the suites with any other Python and they say they are skipping, and exit
zero - a machine without Maya is not a failure.

The table is the record of what happened to each piece. Below it, a section per piece says
what was wrong with the version it replaces, which is the part worth reading before touching
any of this.

| piece | state |
|---|---|
| `mca_package.yaml`, `mca/mya/__init__.py` | ported, 18 checks — every path in the manifest pointed at a folder that has never existed |
| `modifiers/` | ported, 62 checks — the contexts hold the behaviour, the decorators are one line each |
| `utils/naming.py`, `utils/namespace.py` | ported, 84 checks |
| `utils/maya_utils.py`, `utils/plugins.py`, `utils/display_layers.py`, `utils/constraint.py` | ported, 65 checks |
| `utils/optionvars.py` | ported, 43 checks — 269 lines to 235, and the metaclass is gone |
| `utils/dag.py` | ported, 58 checks — one function looped forever, another raised on any node with a shape |
| `utils/om/` | ported, 133 checks — every transform attribute serialized with `'type': None` |
| `utils/attr_utils.py` | ported, 146 checks — an integer attribute could not be created at all |
| `utils/groups.py` | ported, 30 checks |
| `utils/node_util.py`, `utils/ma_fileio.py`, `utils/textures.py` | ported, 68 checks — rebuilding a compound attribute always failed |
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
