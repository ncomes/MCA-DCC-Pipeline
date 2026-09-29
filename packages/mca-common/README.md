# mca-common

What every DCC in the pipeline shares. Nothing here imports a DCC: it runs in Maya,
MotionBuilder, Unreal, a standalone Python and the test suite.

Being ported from the depot one piece at a time — read, brought over, cleaned, and checked.
Each piece lands finished rather than copied and marked for later.

| piece | state |
|---|---|
| `log.py` | ported, 22 checks |
| `textio/` | ported, 27 checks — one engine, three doors |
| `utils/fileio.py` | ported, 33 checks |
| `paths/` | ported, 35 checks |
| `startup/` | ported, 27 checks — `startup.py`, `configs/config.py`, `consts.py` |
| `startup/configs/package_config.py` | ported, 19 checks — replaces the broken `textio/packages.py` |
| `startup/dccs/` | ported, 21 checks — one bootstrap, three thin scripts |
| `startup/dependencies/requirements.txt` | ported — the list the launcher installs |
| `startup/attach.py` | new, 16 checks — how anything outside a DCC finds a project |
| `startup/configs/common_env.py` | **dropped** — see below |
| `pyqt/pygui.py`, `pyqt/qt_utils/windows.py` | ported, 21 checks |
| `pyqt/` (the window classes, dialogs, helpers) | to do — needs `resources/` first |
| `modifiers/` | ported, 25 checks |
| `paths/paths.py`, `utils/dcc_util.py` | ported, 24 checks |
| `resources/` | ported, 22 checks — the art itself stays out, see `resources/README.md` |
| `pyqt/common_windows.py`, `messages.py`, `file_dialogs.py` | ported, 26 checks |
| `pyqt/` (menus, movies, highlighter, widget helpers) | ported, 29 checks — **pyqt done** |
| `utils/` (lists, dicts, strings, methods, pyutils, timedate) | ported, 51 checks |
| `utils/` (folders, process, prefvars, project, pymaths, sounds, video) | next |
| source control (`p4v`, `plasticscm`) | to do — behind one interface |
| `tools/` | to do |
| `animlib`, `assetlist`, `modifiers` | to do |

## Logging

```python
from mca.common import log

log.MCA_LOGGER.info('what happened')
log.setup_file_logging('Wayward', 'maya')
```

`MCA_LOGGING_LEVEL` sets the level. `MCA_LOGS_ROOT` and `MCA_PREFS_ROOT` say where files go,
which is how the launcher points a DCC at the right folders and how a test run writes nowhere
near a real machine's.

## Data files

```python
from mca.common.textio import yamlio, jsonio, alistio

yamlio.write_to_yaml_file(data, path)     # atomic: the old file, or the new one, never neither
data = jsonio.read_json_file(path)        # None when it is not there, rather than a raise
```

YAML, JSON and `.alist` were three modules doing the same job three times. They still have
the names the framework imports, and they all go through `textio/datafile.py`, which writes
beside the file and moves it over, names UTF-8 out loud, and reads a format by extension or
by looking at it.

## Files

```python
from mca.common.utils import fileio
```

Plain file operations. It does not import source control: the version this replaces imported
`mca.common.p4v.perforce` at module scope, so nothing could read a text file on a machine
without Perforce. Checking a file out belongs with source control, which will depend on this
rather than the other way round.

## Paths

```python
from mca.common.paths import project_paths, path_utils
```

Every answer is a function call. The version this replaces also kept module-level snapshots
of the environment taken *at import time* — inside a DCC, the moment the framework first
loads — so switching project left them pointing at the old one for the rest of the session
while the functions beside them answered correctly.

`MCA_PREFS_ROOT` moves where preferences are read from, so the launcher's first-run sandbox
and the suites never touch a real machine's.

## Starting the framework

```python
from mca.common.startup import startup

startup.startup_init('Wayward', 'maya')   # once, from the DCC's own start-up script
startup.restart()                          # pick up a code change without closing the DCC
```

The launcher has already installed this DCC version's Python packages and proved they
import; this puts the framework on `sys.path` and lets each package run its own start-up.

`config.extend_namespace()` is the part worth knowing about. `mca` is one namespace spread
across folders — `mca-common` holds `mca/common`, `mca-maya` holds `mca/mya` — and
`pkgutil.extend_path` works out where its pieces are **once**, when `mca/__init__.py` is
first imported, at which point only mca-common is on the path. Adding mca-maya afterwards
does not change a namespace that is already worked out. The version this replaces got away
with it because `reload_modules()` ran just before the package start-ups and deleted `mca`
from `sys.modules`, so the next import rebuilt it — which made a development convenience
load-bearing, silently.

`common_env.py` is not coming across. Of its five functions, one called `ProjectEnvs()` with
no arguments against a constructor that requires one, one set `MCA_COMMON_CONFIG` to a folder
that does not exist, one only logged a variable it did not set, and one logged the framework
path under the project root's name. What they were meant to do is in `project_paths` and
`startup`.

## What a package says about itself

Each package ships an `mca_package.yaml` beside its code — its name, its version, and the
environment variables it wants, written against `{self}`, the folder the file is in.

`package_config.read_package(folder)` reads it, and **reports what is wrong with it**, which
nothing did before. All three manifests in the depot are broken: mca-ue sets `MCA_MAYA_*`
variables copied from the Maya one, mca-maya points at `mca.mya` with a dot where the folder
is `mca/mya`, and mca-common listed a `dependecies` folder that never existed. A list value
was also formatted into the environment as a Python list — `"['a', 'b']"`, brackets and all —
rather than joined with the platform separator.

The `urls` block is blank on purpose: the ones it replaces pointed at a previous employer's
internal wiki.

## What a DCC runs on start-up

```
startup/dccs/maya/Scripts/userSetup.py
startup/dccs/mobu/Scripts/startup.py
startup/dccs/unreal/Scripts/init_unreal.py
```

Each works out where the framework is **from its own location** — no environment needed — and
hands over to `startup/dccs/bootstrap.py`. They never raise: in Maya's `userSetup.py` an
exception stops everything after it, so a broken pipeline costs the tools, not the DCC.

The three used to be the same twenty lines copied about, and the copies had drifted.
MotionBuilder's called `startup.init(dcc='mobu')` — no such function, and no project name —
so the framework has never once come up in MotionBuilder. Maya's pip-installed pymel into
Maya's own installation during start-up. Unreal's defaulted the project to `'Wayward'`.

## Attaching from outside a DCC

A DCC the launcher started needs nothing: the launcher put that project's start-up folder on
its path, so the script that runs is already the right project's and finds the framework from
its own location. Anything else — the editor, a farm job, a standalone script, an MCP server —
has to answer "which project?" first:

```python
from mca.common.startup import attach

attach.attach()                  # the launcher's current project
attach.attach('Wayward')         # a named one
attach.attach(dcc='maya', start=True)
```

In order: what the caller says, then `MCA_PROJECT_NAME`, then the launcher's own
`mca_launcher.pref`. No guessing and no hardcoded paths — a machine with nothing set up gets
a sentence saying so.

It also reports when a *different* `mca` is already imported — a pip-installed mca-common in
an editor's venv, say — because a framework quietly running from the wrong copy is a day of
confusion. `replace=True` drops those modules so the project's copy wins.

## Qt

`pyqt/pygui.py` is the one place that knows which Qt this DCC has — PySide6 in Maya 2025 and
2026, PySide2 in 2022, 2024 and MotionBuilder. Everything that draws imports from there.
Without either, it says so (`AVAILABLE` is False and using it raises a sentence) rather than
handing back a stub that raises `AttributeError: QWidget` somewhere far away.

`pyqt/qt_utils/windows.py` finds and closes the framework's windows — what `shutdown()` uses.
A window the framework makes is **marked with a Qt property** now; the old version matched
`'MCA '` in the window title, with a special case to spare `'MCA Editor'`, so renaming a tool
stopped its window being closed and a scene called MCA-anything got closed instead. The title
match stays as a fallback for windows built by tools that have not been ported yet.

`get_mca_window_by_name` compared a widget to a string — `if win == name` — so it returned
None every time it was ever called. It works now.

## Decorators and the singleton

`@timestamp` **broke every function it decorated**: it read `f.func_name`, a Python 2
attribute, before the `__name__` fallback beside it, so it raised on every interpreter the
framework runs on. `@repeater` ran its function on a timer thread with nothing catching
exceptions, so one failure killed the thread and the repeating stopped silently.

`@error` swallows what it catches — that is its job, keeping the DCC open — which means a
function wearing it answers `None` when it fails. Worth knowing before putting it on
anything whose answer is used for something else.

The singleton had **two implementations with two registries**, and `clear_cls()` and
`teardown()` only emptied one. Everything inheriting `SimpleSingleton` — the resource library
among them — could not be cleared by anything, ever, so a framework restart kept the old
project's paths. One registry now, and `shutdown()` empties it.

## The project's folders

```python
from mca.common.paths import paths

paths.get_characters_path()      # '' when the project has not said, never a raise
```

Thirty-odd functions, each some arrangement of
`os.path.normpath(os.path.join(os.getenv(X), 'Folder'))`. **Every one raised `TypeError`
when its variable was not set** — `os.getenv` answers None and `normpath(None)` raises — so
on a half-set-up machine, or in Unreal, which is handed fewer of these than Maya is, asking
for a folder raised out of a function documented to return one. They answer `''` now.

Two of them also read the import-time snapshot of the project root, in a module whose own
comment two functions above explained why that was wrong.

## Which application is this

`utils/dcc_util.application()` answers a `Dccs` value — `'maya'`, `'mobu'`, `'unreal'` — the
same spelling the boot config, the start-up scripts and the constants use. It used to answer
`'Maya'`, `'Mobu'` and `'Unreal'`, matching none of them, and a path built from it
(`Tools/Common/Tools/Maya`) worked only because Windows ignores case. `display_name()` is
there for when a person will read it.

## Resources

```python
from mca.common.resources import resources

button.setIcon(resources.icon('tools/rig_builder.png'))
window.setStyleSheet(resources.read_stylesheet('dark_theme'))
```

**No art is bundled.** The folders come from the environment the launcher builds, so a studio
points at its own and a clone with none still runs. `resources/README.md` says why the set
this framework was using — 1,269 icons and 21 stylesheets with no licence file, several
carrying the names of commercial packs — has not come across.

Resources are found at start-up and **built when something asks for one**. Registering used
to construct a `QIcon` *and* a `QPixmap` for every file it found before anything had asked
for either.

## Windows and dialogs

```python
class RigBuilder(common_windows.MCAMainWindow):
    def __init__(self, parent=None):
        super().__init__('Rig Builder', version='2.0.0', parent=parent)
```

Three window classes carried the same forty lines each — title, icon, stylesheet, remembered
geometry, replacing the one already open — copied and then drifted: one guarded its
stylesheet against missing resources and another did not, one saved its geometry and another
had that commented out. Those forty lines are one mixin now.

Settings were kept under `QSettings(os.getlogin(), title)` — the *user name* as the
organisation, and `os.getlogin()` raises in a process with no controlling terminal.

In the dialogs, the one that loses work: **`text_prompt_message` returned the typed text when
the artist pressed Cancel**, because it compared the result to `'Cancel'` while the button's
label is `'&Cancel'`. An error box also offered Yes and Cancel, and every message box's
stylesheet was overwritten by two one-line rules applied straight after it.

## The rest of pyqt

`syntax_highlighter.py` came across almost unchanged — it is the most careful module in the
package — with one line that had to move: `color_format(color: Sequence[int] | str, ...)`.
`X | Y` in an annotation is Python 3.10 and later, and an annotation is evaluated when the
function is defined, so **that module could not be imported in Maya 2022 at all**.
`from __future__ import annotations` fixes it back to 3.7 and leaves the annotations as
written.

In `qt_menus`, `remove_action` had its `return False` **inside** the loop, so it looked at
the first action, and if that was not the one being asked for it gave up — every action after
the first was unremovable. It also logged to a logger of its own (`'mca_common'`, not the
framework's), so its messages went somewhere else and ignored `MCA_LOGGING_LEVEL`, and a
window with no menu bar crashed it.

## The data helpers

```python
from mca.common.utils import lists, dict_utils, strings, pyutils, timedate
```

Small functions the whole framework leans on, which is why the bugs in them were worth
finding:

`lists.get_index_in_list` guarded a negative index with `len(seq) > abs(index)`, so
`get_last_in_list(['hero'])` — one item, index `-1` — answered the default instead of
`'hero'`. The last item of a one-item list could not be read, by any of the four functions
built on it.

`methods.get_properties` had its `append` **inside** `if filter_out:`, so the ordinary call —
no filter, which is how everything calls it — always answered an empty list.

`pyutils.ObjectDict` gives dictionary values attribute access, and for a nested dictionary it
built a **new** `ObjectDict` and returned that, leaving the original untouched: every write to
a nested value went into a temporary and was lost. It wraps in place now, so the nesting is
real.

`strings.clean_file_string` promised to make a string safe for a file name and replaced
backslashes only — `/`, `:`, `*` and the rest went straight through.
`get_numbers_from_string` answered a `map` object (truthy even when empty, and consumed by
whoever looked at it first) of *single digits*, so `'spine_012'` gave `[0, 1, 2]` rather than
`12`. `debug_object_string` read `obj.im_class`, which is Python 2.

`timedate` padded a single-digit second on the wrong side — `second += '0'`, making `:50` out
of `:05` — in two places, the third and fourth time that same line has turned up in this port.
`get_time_zone` tested `if not time:` against the imported *module*, which is never falsy, so
its `else` branch had never run. It uses the standard library's `zoneinfo` now and falls back
to `pytz` only where `zoneinfo` is missing (Python 3.7, which is Maya 2022) — the old version
imported `pytz` at module scope, a package nothing installs.

## Tests

```
python tests/test_log.py
```

They need nothing but Python — no DCC, no Qt, no display.
