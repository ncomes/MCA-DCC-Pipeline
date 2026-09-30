# mca-common

What every DCC in the pipeline shares. Nothing here imports a DCC: it runs in Maya,
MotionBuilder, Unreal, a standalone Python and the test suite.

**Ported.** Every piece was read, brought over, cleaned and checked, one at a time, each landing
finished rather than copied and marked for later. 34,249 lines of depot became 31,092, with
**940 checks in 27 suites** — run them with `tests/run_tests.bat` on Windows or
`tests/run_tests.sh` anywhere. The suites need nothing but Python; the ones that draw need
PySide and skip politely without it.

The table below is the record of what happened to each piece. Below it, a section per piece says
what was wrong with the version it replaces — which is the part worth reading if you are about to
touch any of this.

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
| `startup/startup_menus.py` | ported, 4 checks |
| `startup/configs/common_env.py` | **dropped** — see below |
| `pyqt/pygui.py`, `pyqt/qt_utils/windows.py` | ported, 21 checks |
| `pyqt/` (the window classes, dialogs, helpers) | to do — needs `resources/` first |
| `modifiers/` | ported, 25 checks |
| `paths/paths.py`, `utils/dcc_util.py` | ported, 24 checks |
| `resources/` | ported, 22 checks — the art itself stays out, see `resources/README.md` |
| `pyqt/common_windows.py`, `messages.py`, `file_dialogs.py` | ported, 26 checks |
| `pyqt/` (menus, movies, highlighter, widget helpers) | ported, 29 checks — **pyqt done** |
| `utils/` (lists, dicts, strings, methods, pyutils, timedate) | ported, 51 checks |
| `utils/` (process, sounds, video) | ported, 41 checks |
| `utils/folders.py`, `project.py`, `prefvars.py` | **dropped** — see below |
| `utils/pymaths.py` | ported, 38 checks — half of it dropped |
| `sourcecontrol/` | ported, 33 checks — one interface, Perforce behind it |
| `plasticscm/`, `utils/plastic.py` | **dropped** — see below |
| `tools/progressbar`, `tools/example_tool` | ported, 21 checks |
| `tools/dcctracking`, `tools/python_editor` | **dropped** — see below |
| `assetlist/` (templates, categories, the base record) | ported, 61 checks |
| `assetlist/` (unified entry and registry) | ported, 68 checks |
| `assetlist/` (asset manager, validate_assets) | ported, 39 checks |
| `assetlist/assetlist_api.py` | ported, 50 checks — **assetlist done** |
| `assetlist/migrate_to_unified.py`, `migrate_asset_ids.py` | **dropped** — see below |
| `animlib/` | ported, 71 checks |
| `tools/assetregister` (11 modules) | ported, 27 checks |
| `tools/doccrawler` → `tools/docgen` | ported, 38 checks — the scraping half **dropped** |
| `tools/toolbox` | ported, 46 checks — **mca-common done** |
| `tools/toolbox/toolbox_migrate.py` | **dropped** — see below |

## Logging

```python
from mca.common import log

log.MCA_LOGGER.info('what happened')
log.setup_file_logging('Wayward', 'maya')
```

`MCA_LOGGING_LEVEL` sets the level. `MCA_LOGS_ROOT` and `MCA_PREFS_ROOT` say where files go,
which is how the launcher points a DCC at the right folders and how a test run writes nowhere
near a real machine's.

## The menu entries every DCC shares

`startup/startup_menus.py` is what a DCC's own menu points its documentation entries at, so the
Maya menu and the MotionBuilder menu open the same pages. Where those pages are comes from the
`urls` block of the package manifest — **blank in this repository**, since the ones it replaces
pointed at a previous employer's wiki.

A blank one used to mean `webbrowser.open('')`: a browser window at whatever was there before,
which reads as the tool being broken rather than the page not existing. It says there is no page
yet. It also read the manifest through `textio.packages`, the module `package_config` replaced,
and built its package manager **at module scope** — so a manifest with a problem in it took the
DCC's whole menu down while the menu was being built. And `open_plastic_folder` was named for a
source control the project stopped using, indexed `[0]` into a function that no longer exists,
and ran `'explorer ' + path`, so a project path with a space in it opened the wrong folder, on
Windows only.

This one was missed on the first pass through `startup/` and found by surveying mca-maya, which
imports it from two DCCs.

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

## The machine: processes, sounds and video

```python
from mca.common.utils import process, sounds, video_utils

process.is_running('cm.exe')
process.run_on_thread(send_the_tracking_event)
sounds.warning()
video_utils.ffmpeg_convert_to_mp4(playblast)
```

`process` answered `False` from two functions documented to answer a list, on the no-psutil
path the guard existed to protect — so `for p in get_processes_by_name(...)` raised
`TypeError` there. Worse, the one function anything actually called was the one with no
`AccessDenied` guard, although the function directly above it had one: enumerating processes
on Windows raises about system processes as a matter of course. The two also disagreed about
what "by name" means — one compared for equality, the other for a substring — so
`find_by_name` now says which it is doing.

`cpu_threading` started a **non-daemon** thread with nothing catching exceptions and returned
nothing: a failure printed to a stream nobody reads, the caller could not wait for the work or
know it had happened, and the thread held the process open at exit. `run_on_thread` logs what
went wrong, hands the thread back, and does not keep Maya from closing.

`sounds` **no longer ships or needs any sound files.** It played eight `.wav`s out of a depot
folder, six of them Windows' own system sounds copied in — `Windows Error.wav`,
`Windows Critical Stop.wav`, `Windows Battery Low.wav` — which is the icons' licence problem
again, and for those six unnecessary: `MessageBeep` plays the user's own sound scheme, and
stays quiet when they have muted it. It also handed the file name to `PlaySound` without
`SND_FILENAME`, so Windows looked it up as a *registry sound alias* first and only then as a
file, and with the sounds folder unset it was passed a bare name — what an artist heard
depended on the machine. A project that wants its own sound still passes a file name;
a missing file is silence, because no tool should fail for want of a noise.

`video_utils` formatted one long string and ran it with `shell=True`, so **a path with a space
in it broke every conversion** — `shot 01 playblast.mov`, or anything under `My Documents`,
reached ffmpeg as several arguments. It also ignored ffmpeg's exit code, so the only report of
a failure was `FileNotFoundError` about the output file, saying nothing about the cause. It
passes an argument list now, logs what ffmpeg said, uses `-y` rather than deleting the old
file first, and asks Windows not to flash a console window up in front of Maya.

ffmpeg itself is not bundled — it is GPL — and is found from `MCA_FFMPEG_EXE`, then a
project copy, then `PATH`.

## Arithmetic

```python
from mca.common.utils import pymaths

pymaths.is_equal(rotation, 1.0, 0.001)
pymaths.get_planar_up(shoulder, elbow, wrist)
```

A leaf: standard library only, so a DCC, a farm job and the suite get the same answers.
695 lines became 300, and three of the things it did were wrong.

**`is_equal`'s tolerance did nothing.** It read
`fabs(x - y) < epsilon * fabs(x + y) * tolerance or fabs(x - y) < epsilon`, which multiplies
the caller's tolerance into an epsilon-sized number: with `tolerance=2`, two values still had
to be within 4.4e-16 of each other. Every call site in the framework passes a tolerance, and
every one of them has been getting exact equality — including `ma_maths`, which asks
`is_equal(sin_half_theta, 0.0, 2)` while decomposing a matrix, so its gimbal-lock branch has
never once been taken. It is `math.isclose` now, with the tolerance as an absolute distance;
the three `ma_maths` call sites pass `2`, which was never a distance in any reading, and need
a number chosen when that module is ported.

**A small vector measured as nothing.** `get_vector_length` rounded the *sum of the squares*
to five decimal places before taking the square root, so any vector shorter than about 0.0022
units came back as exactly zero — and `normalize_vector` then divided by that zero. Face rigs
work at that scale. Nothing rounds any more: the old module rounded every vector it produced
to five places, which reads as tidiness and is a display concern.

**`create_random_list(int_only=True)` had never run**: it called
`random.randint([low, high])`, one list where two numbers go, so it raised `TypeError` every
time.

Also: `add_vectors` and friends used `zip`, so adding a 3d point to a 2d one answered a 2d
point and said nothing — they refuse now; `get_cross_product` ran modulo arithmetic over
whatever length it was given and answered confident nonsense for anything but 3d;
`average_vectors([])` raised `IndexError` on its first line; `remap_value` raised
`ZeroDivisionError` on an empty input range.

`get_midpoint_between_points` measured its `scale` from the **second** point back towards the
first, which its docstring did not mention because the parameter was not documented at all. It
counts from the first point now. At the default 0.5 the two agree, so the only caller affected
is `skel_utils.position_twist_joints`, which must swap its two points when it is ported.

Two names to fix at their call sites, not here: `buildarig` calls
`pymaths.find_distance_between_points` twice, a function that has never existed under that
name — so working out a rig's scale from its skeleton's bounding box has always raised
`AttributeError`.

### What was dropped

Four `fade_*` and ten `ease_*` functions, copied from a C easing cheat sheet and used by
nothing. One of them shows why they were not worth keeping: `ease_out_back` reads
`1 + (--percent_value) * ...`, and `--x` in Python is not a pre-decrement, it is minus minus
x, which is x. `fade_sigmoid` jumps from 0 to 0.168 the moment its input leaves zero. Qt has
easing curves for anything that needs to animate.

`smooth_step` normalised with `value / range_val` and never subtracted `range_start`, so any
range not starting at zero was wrong. `distribute_value` answered two values when asked for
one. `average_position` was `get_midpoint_between_points` with the arguments spelled
differently. `get_pole_vector_pos` is a second implementation of `ik_utils.get_pole_vector_position`,
which is the one the rigging code calls. `inverse_distance_weight_1d`, `snap_value`,
`roundup`, `get_range_percentage`, `map_range_clamped`, `map_range_unclamped`, `AXIS`, `PI` and
`MAX_INT`: no callers.

## Source control

```python
from mca.common import sourcecontrol

sourcecontrol.checkout(scene_path)
if not sourcecontrol.submit(files, 'rig: hero, arm fixes'):
    ...
```

One interface, so that no tool names Perforce. Which backend answers is the studio's, set by
`MCA_SOURCE_CONTROL` — `perforce`, `none`, or unset to work it out. A machine with nothing set
up gets `NoSourceControl`, where **every operation succeeds and does nothing**: a tool's job is
to save the artist's file, and "there is no Perforce here" is not a reason to stop. Adding Git
or Plastic means one class and one line in `BACKENDS`.

Nothing raises. An operation answers a `Result`, which is falsy when it failed and carries what
the tool said, so a UI has something to show.

Two things were wrong with the Perforce it replaces, and both are the kind that only bite on a
real machine:

**Every command was a shell string.**

```python
p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} edit -c {cl_val} {file_path}'
subprocess.run(p4_cmd, shell=True, ...)
```

A path with a space in it — `Characters/hero rig v2.ma`, anything under `My Documents` — went
to p4 as two paths. Commands are argument lists now, and the suite checks the exact argument
list p4 was handed, which is the only way to prove it.

**Every guard was dead.** Each operation began `p4_info = P4Info()` / `if not p4_info: return`,
and `P4Info` is an object with no `__bool__` — always truthy. So on a machine without Perforce,
where the constructor gave up and left `user`, `workspace` and `port` as None, every command
ran as `P4 -p None -c None edit ...`. `available()` is a real question now, and the backend
answers a plain failure instead of shelling out.

Smaller ones: `P4Info` kept `all_workspaces = []` as a mutable class attribute of a singleton
and appended to it without clearing, so the list grew every time anything asked;
`find_workspace` put its `break` in the inner of two loops, so the *last* matching workspace won
rather than the first; `p4 clients` output was split on `'\r'`, which leaves every line but the
first starting with a newline; reading pending changelists ran `p4 describe` once per changelist
and read the description out of the third line of a report meant for a person, where `-ztag`
names its fields; and a missing registry key was logged as `CRITICAL ERROR: Install perforce` at
error level, which is every machine that does not use Perforce.

`shutdown()` calls `sourcecontrol.reset()`, because the workspace is found by looking for the
project's config file in each workspace root — so switching project has to ask again.

## The progress window

```python
from mca.common.tools.progressbar import progressbar_ui

progress = progressbar_ui.ProgressBarStandard()
progress.update_status(40, 'Skinning the left arm')
progress.update_status(100, 'Done')          # 100 closes it
```

One window wherever it is asked for, so a rig build and the skinning it calls talk to the same
one, and a job running inside another job adds a second row instead of fighting over the first.
Six modules in mca-maya use it.

**It would have raised in Maya 2025.** `update_value`'s own docstring called its argument a
float — `:param float value: Progress bar percentage.` — and handed it to
`QProgressBar.setValue`. PySide2 truncated a float quietly; PySide6, which is what Maya 2025
and 2026 have, refuses it. It rounds now.

It also **stopped the DCC for half a second at the end of every job**: on reaching 100 it called
`time.sleep(0.5)` on the user interface thread, to let the artist admire a full bar.

`update_label` and `update_value` both read `rows[-1]`, so a job still reporting progress after
the artist closed the window raised `IndexError` into the middle of whatever it was doing, and
`remove_progressbar` raised the same on an empty list — from a function whose only job is
tidying up. Every method copes with there being no window now.

The window's height was worked out as `len(rows) * 200` when adding a row and
`len(rows) * 100` when removing one, so finishing an inner job left the window half the height
it should be. And `QApplication.processEvents()` ran on every single update — thousands of times
in a skinning loop, each one re-entering the event loop — where it now runs when the displayed
percentage actually changes.

The widgets are built in code. The version this replaces loaded a Qt Designer file for a label
and a progress bar.

## The example tool

`tools/example_tool` is the smallest tool in the framework and is kept deliberately: it is the
one to copy. It shows what `MCAMainWindow` gives you for nothing — the framework's title, the
project's stylesheet, a remembered size and position, closing the copy already open — and the
two habits worth having: build the widgets in code, and put the work in a function with no Qt
in it, so a farm job, an MCP server or a test can call it.

The version it replaces loaded its layout from `example_tool/ui/testui.ui` in the common tools
folder, which an open clone does not have — so the example nobody could run was the one meant
to show how — and its button called `print`, in a framework with a logger.

## The asset registry

```python
from mca.common.assetlist import asset_paths

categories = asset_paths.AssetDictData.load()
characters = categories.get_category_data('Characters')
```

The foundation first: the framework's own folder templates
(`asset_path_templates.yaml` + `asset_path_config.py`), the project's category file
(`asset_paths.py` reading and writing `asset_data.config`), and what every asset record has
(`asset_list.py`).

**It could not be used without Qt.** `asset_paths` began
`from mca.common.pyqt import common_windows` and never used it — so reading the asset registry
from a farm job, an MCP server, Unreal's Python or a test needed PySide to import first. One
line.

**It read the project's category file once per asset.** `AssetDictData.load()` parses the YAML,
and `unified_entry` calls it while working out a single asset's folder — so building a registry
of several hundred assets parsed the same file several hundred times. Read once now, with
`asset_paths.reload()` for a change made elsewhere.

**A folder was looked up by substring.** `get_required_path('RIGS_PATH')` walked the category's
folder keys and answered the first one that *contained* what was asked for, in whatever order
the file listed them — so it gave the right answer only because `RIGS_PATH` happens to be
written above `SRC_RIGS_PATH`. Write the file the other way round and every rig in the project
resolves into the source folder. It is an exact lookup now, with the substring match kept
behind it for the tools that ask for `'MODELS'`, where it can no longer shadow a real key.

**Every `add_faction`, `add_subcategory` and `add_skeleton` went round the back.** They read the
list and called `.append` on the list the file holds, past the setter that sorts it — and on a
category that had no such key at all they appended to a throwaway list, so what the artist added
was silently lost.

**The same file was described three times.** The templates YAML had a `categories:` block, a
`gear_categories:` block and a `category_summary:` block, all describing the project's
categories in different shapes. Only the last was read, and it was the stale one: `NPCs` where
the others said `NPC`, `Handguns` where they said `Handgun`, `PickUps` missing altogether. It
also declared a `Faces` category that the Python seeding code did not list, so **a fresh
checkout came up with no Faces category** while every real project has one. One description now,
and the seeding reads it.

In the records (`asset_list.AssetBaseEntry`): an entry is stored as `{asset_id: fields}`, and
every one of its thirty-odd properties re-derived the id by listing the dictionary's keys and
taking the first — on every read of every attribute. `path` and `full_path` answered **None**
out of properties documented to answer a string, so a caller joining onto one got a `TypeError`
a long way from the asset with no path. `sm_path` and `sk_path` each had a setter that stored
the value somewhere the getter never read, so setting one and reading it back gave the old
value. `@abc.abstractmethod` was used on a class that is not an ABC, where it does nothing, so
`AssetBaseEntry` could be built directly and `get_required_path` answered None — which every
folder property then joined onto. And `create_folders` built its paths with a literal `'\\'`
appended, called `fileio.touch_and_checkout` — Perforce, from a file helper — and used the
folders' *relative* paths, so on any machine whose working directory was not the project root it
made the asset's folders somewhere else entirely.

### The write layer

```python
from mca.common.assetlist import unified_entry, unified_registry

entry = unified_entry.UnifiedAssetEntry.create('Hero Bot', 'Characters', subtype='Heroes')
registry = unified_registry.UnifiedAssetRegistry.load('Characters', create=True)
registry.add_asset_entry(entry)
registry.save()
```

`unified_entry` is the most carefully written part of the registry and most of it came across
as it was — its comments record real investigations, like why an asset id carries its category
(ids are unique across the whole registry, and an outfit set has a Pirate body, a Pirate hat
and Pirate shoes) and why a file scan skips Maya's incremental-save folders (one asset looked
like it had 104 rigs, 102 of them incremental saves, and the "rig" it answered with could be a
week old). What changed:

- **A new category's file was never added to source control.** `UnifiedAssetRegistry.save`
  wrote the file and *then* asked `if not os.path.exists(file_name)` before adding it — after
  writing it, so the answer was always no. Every registry file created since has been sitting
  on disk unadded.
- **An empty registry file read as no file at all.** `load` answered None for a category with
  no assets in it, which is exactly what a new category has — so the first asset could never be
  added to one. It also answered None for a category with no file yet; `load(..., create=True)`
  is how registering the first asset in a new category says so.
- **Every add and remove rebuilt every entry in the category, and threw away the entry objects
  callers were holding.** Fetch an entry, add another, and your entry is no longer the one the
  registry knows about — and `save` writes what the registry knows about, so the edits go
  nowhere. Adding assets one at a time also cost the square of their number, since each rebuild
  re-derived every entry's path flags and dye schema. Entries are built once and kept.
- **`get_required_path` answered None** behind a bare `except Exception: pass`, out of the
  function every folder property joins onto, so a problem in the category config surfaced as a
  `TypeError` somewhere else entirely.
- **`create_folders` had a folder layout of its own** — six paths written into the code — rather
  than the ones the asset's category says it has, so a category that had moved its meshes folder
  got both. It asks the category now, and the placeholder an empty folder needs to be storable
  at all goes through the source control interface, which is where Perforce's `.p4keep` and
  Git's `.gitkeep` are the same idea.
- **The engine path had a project's name written into it**: `build_engine_path` prefixed
  `/Game/Wayward/`. `MCA_ENGINE_CONTENT_ROOT` says it now, so another project is another
  variable rather than another edit.

### The read layer

```python
from mca.common.assetlist import asset_manager

manager = asset_manager.get_asset_manager()
hero = manager.get_record_by_name('Hero Bot')
for gear in manager.iter_children(hero.asset_id):
    ...
```

Every asset, read once and indexed — by id, by name, by category, and by what belongs to what.
A record is frozen, so nothing can change the registry by reading it.

**Cycles were only looked for from the roots.** `_validate` walked down from every root asset,
so a cycle that no root reaches — A's parent is B and B's parent is A, where neither is a root —
was never visited. The cycles that can hang a rig build were exactly the ones nothing could
find. Every record is a starting point now.

**Two assets sharing a display name went unreported.** `get_record_by_name` answers the first
one loaded, so the other is an asset an artist can see in a list and cannot open. The report
says so now, beside the duplicate namespaces it already reported.

`--skip-gear` on the command-line check **did nothing**: it collected the ids to ignore with
`iter_category('Gear')`, and `Gear` is not a category — gear lives in categories of its own,
Hats and Armor and Shirts, each flagged as gear in the project's config. The set was always
empty and every gear problem was reported anyway.

And one of mine: `paths.get_categories_manifest_path()` answered `categories.manifest` for one
commit, where the file on disk is `categories.json`, so **nothing in the registry would have
loaded at all**. This suite is what found it; `tests/test_paths.py` now checks the name.

### The flat API

```python
from mca.common.assetlist import assetlist_api

assetlist_api.list_categories()
assetlist_api.register_asset('Frostwind', 'Characters', subtype='Heroes', faction='Agents')
```

What a script, an MCP tool or the in-DCC AI calls. Every function answers
`{'ok': bool, 'result': ..., 'message': str}` and never raises, and the failure messages are
part of the API: an unknown category lists the valid ones, an unknown id offers near matches, a
value outside a controlled vocabulary names what is allowed. A caller that reads the message can
correct itself without another round trip. That design came across untouched — it is the best
thing in the package.

What changed:

- **`transfer_asset` checked neither of its two saves.** It wrote the asset into its new
  category, then removed it from the old one — and a failure on the second left one asset id in
  two categories, which the manager resolves by keeping whichever it loaded first and mentioning
  it at debug level. Both are checked now, and a half-finished move says which category to take
  the asset out of.
- **`reload` re-reads the category configuration too.** The configuration is read once and kept
  now, so a category another session added would never have appeared.
- `check_assets` reports the duplicate display names the validation report gained.

## The animation library

```python
from mca.common.animlib import animlib_api

animlib_api.list_clips(character='frostwind')
```

A catalog of clips, and where each clip's files live: the DCC-agnostic half, so a browser, an
MCP tool and a script all drive one code path. Anything that touches a Maya scene is in
`mca.mya.tools.animlibrary`.

This is the newest code in the package and most of it came across as it stands, tests included
— the depot's own `tests/animlib/test_animlib_core.py` is now `tests/test_animlib.py`, on the
same harness as everything else and with the extraction planner covered, which it was not.
Four things changed:

- **The project list ignored `MCA_PREFS_ROOT`.** `get_projects_file()` built
  `<Documents>/mca_preferences/anim_library_projects.json` by hand, so the launcher's first-run
  sandbox did not contain it and a test run wrote into a real machine's Documents folder. It
  asks `project_paths.get_preferences_root()`, which is the same folder and is the one that
  variable moves. The suite needs no monkeypatching now, which is the proof.
- **The catalog was written outside source control.** The library normally lives under the
  common tools path, which is versioned, so the first save never added `catalog.json` and every
  save after that was writing to a read-only file. It goes through the interface now — checkout
  on a file that was there, add on one that was not.
- **`find_animation_files` scanned each subtree once per folder deep.** It walked for folders
  called `Animations`, then walked each one's whole subtree — and let the outer walk descend
  into that subtree too, so every folder inside it started another full walk. The depot has
  ~1,100 animation files in deep trees.
- **A catalog record with no name became a clip called nothing.** `_ingest` derived a missing
  id from character and name, and `build_clip_id` answers the character on its own when there
  is no name — so a nameless record was kept under the character's own id, where it would
  collide with the next one.

## The asset register

```python
from mca.common.tools.assetregister import unified_register

unified_register.UnifiedRegisterUI().show()
```

The window artists create and edit assets in: eleven modules, 6,050 lines, split out of one
window so each area reads on its own. The split was done mechanically — every file says "the
code is unchanged" — and it copied the same block of imports into all eleven, whether they used
them or not. **Seven of the eleven imported `mca.common.p4v.perforce` and none of those seven
used it**, so the register pulled Perforce in seven times over and could not be imported on a
machine without it. The whole register's real Perforce surface was two calls, both in
`register_vcs`. They go through `mca.common.sourcecontrol` now, `register_p4` is
`register_submit`, and the progress dialog is titled for whichever source control answered.

Three things were broken.

**The register could not register anything.** `_save_new_asset` hands the whole form to
`UnifiedAssetEntry.create(**data)`, and the form includes `variant_of`, which `create` did not
take — so saving a new asset raised `TypeError: unexpected keyword argument 'variant_of'`.
`create` takes it now, which also lets `assetlist_api` stop setting it by hand afterwards.

**The register generated the wrong kind of asset id, and that is where the duplicates in the
real registry come from.** It built the id as
`strings.remove_chars(name, chars='[^a-zA-Z0-9]+').lower()` — no category, no underscores — so
"Hero Bot" in Characters became `herobot`, while `unified_entry.build_asset_id`, which
everything else uses, makes `characters_hero_bot`. Every asset registered through this window
since the id scheme changed got the old kind. That is exactly the shape of the 29 duplicate
display names in the live registry: `pirateshoes` beside `shoes_pirate`, `teddy_hat` beside
`hats_teddy`, `agentmale` beside `agent_male` — the same asset, once through the window and once
through anything else. One function makes an id now, and it follows the category as well as the
name.

**A category added through the register was invisible to everything that reads assets.**
`AssetManager` loads the categories `categories.json` declares, and **nothing in the framework
ever wrote that file** — the migration did, once, and it has been run. The register's `+` button
wrote `asset_data.config` and stopped there, so a new category was declared nowhere and every
asset registered into it was written to its `.alist` and then loaded by nothing.
`asset_manager.declare_category()` writes the manifest now, the register calls it, and the
manager also loads any category the project's config has and the manifest does not — which
picks up the ones added before this was fixed.

Also: a move between categories wrote the destination first and only then removed the asset from
where it came from, checking neither save; `assetlist_api.transfer_asset` did it the other way
round, also checking neither, each with a comment explaining why its own order was the safe one.
They agree now, on the order whose failure is recoverable — listed twice, which somebody can see
and fix, rather than lost, which nobody can. And fourteen names with a leading underscore that
four sibling modules imported are public, `waggle_gif` among them (spelled
`_resolve_taillwaggle_gif`, with the doubled l), which now asks the resources module rather than
looking for the animation inside the package's own folder, where this repository keeps no art at
all.

## Documentation for the packages underneath

```
python -m mca.common.tools.docgen --version 2025 --output D:/AIDocs
```

It imports PyMel, walks its core submodules, and writes a JSON file and a Markdown file per
function plus one index — so the in-DCC AI and the MCP tools can answer a question about a PyMel
command from the docstrings of the version that is actually installed.

It was `doccrawler`, 2,247 lines, and most of it **downloaded Autodesk's documentation website
and parsed the HTML**: a crawler (197 lines), an HTML parser (342), and a second crawler for
`maya.cmds` (476). Its own README called that the less reliable half next to introspection, and
it is — a page can be restyled, a URL can move, and what comes back is the documentation for
whichever version is on the internet rather than the one installed here. That half has not come
across, and the name went with it: a package called `doccrawler` that does not crawl is a lie in
the import line.

Nor have the paths. Two module-level constants held a previous employer's depot — where the docs
would be written and where PyMel was to be found. `MCA_AI_DOCS_PATH` says the first now.

**The docstring parser had to be rewritten, and it is the reason the output was worth little.**
It read a Sphinx line —

```
:param str path: where to save it
```

— by splitting on `:` and taking the second piece as the parameter's name, so every parameter in
every file was called `param str path`. A bullet line fared worse: `- path: where to save` gave
the *description* as the name. Parameter names are most of what these files are for. It reads
Sphinx, Google and numpy shapes now, and the suite checks each.

The index is written once. It used to be read, scanned linearly and rewritten in full for every
single function — two thousand reads and two thousand writes of a file that grew as it went, and
quadratic on top of that.

`maya.cmds` is not covered. The honest way to document it is `cmds.help(command)` from inside
Maya, which is introspection rather than scraping, and it can be added beside this when
something needs it.

## The toolbox

```python
from mca.common.tools.toolbox import toolbox_api

toolbox_api.add_item(section_id, 'Build A Rig', target='mca.mya.tools.buildarig:run')
```

The artists' tool palettes: editable in place, stored as YAML, shared through source control, with
a headless API over the same library the window uses so a script, the in-DCC AI and the MCP tools
all take one path. It is the best-kept subsystem in the package — not one unused import in 6,475
lines — and most of it came across untouched.

Two things were wrong.

**Every edit to a shared toolbox failed on a machine without Perforce.** `ToolboxLibrary`
defaulted its shared backend to `P4Backend()` outright, so `p4 fstat` came back "the p4 command
line client is not installed", `prepare_edit` read that as a file it could not check out, and
raised `ToolboxWriteError` into an error box — on a contractor's laptop, a build agent, or a
studio that uses anything else. `toolbox_vcs.shared_backend()` asks
`mca.common.sourcecontrol` now: Perforce where Perforce is set up, plain disk writes where it is
not.

**The broken-tool check called every tool broken.** `check_command` finds a module's file by
walking `sys.path` without importing it — and skipped the empty entry, which is the current
directory, and which is how the framework is on the path for every `python -m` run from the
packages folder and every test run. So `mca.common.log` read as "module not found", and the
toolbox showed the artist every tool as broken. Inside Maya the path is absolute, so it worked
there and nowhere else.

The toolbox keeps its own small backends rather than using the source control interface directly,
and that is deliberate: what it needs is a file-writing lifecycle — prepare this file, tell me
who else has it open, mark this deletion — where the interface does checkout, add and submit over
a list of paths. It takes the connection details from the interface and leaves the rest alone.

`toolbox_migrate.py` has not come across: 294 lines converting the legacy GUID-graph `.tbx` files
into these sections and toolboxes. It has been run — the sections are on disk in the new format
and there is not a `.tbx` file left in the depot — and it cannot happen twice.

## What is not coming across

`folders.py` held one function, `get_files`, which nothing in the framework imports — and its
two branches disagreed: the recursive one walked with `os.walk` and returned files, the flat
one filtered `os.listdir` and returned **directories too**, from a function called `get_files`.

`project.py` was ten lines of section comments and no code.

The two asset registry migrations, `migrate_to_unified.py` and `migrate_asset_ids.py`, are
860 lines of one-off script for a conversion that has already been run: the registry on disk is
the unified format. They stay in the depot's history, where a project still on the old format can
find them.

`tools/dcctracking` is not coming across, and would not have come across in any case:

- It posts to a **Google spreadsheet whose id is hardcoded in the module**, belonging to a
  previous employer.
- `dcc_user_tracking_data.yaml` beside it holds the **full names, work email addresses, job
  titles, teams and locations of that employer's staff**, keyed by a hash of their user name.
  That cannot go into a public repository, and it is not ours to publish.
- It could not run anyway: it opens with `from mca.common.googlesheets import google_sheets`,
  and there is no `googlesheets` package anywhere in the framework — so importing the module
  raises `ImportError`. Two of the names it calls on `mca.common` do not exist either.
- `ddc_tool_entry_thead`, the version meant to keep tracking off the main thread, reads
  `process.cpu_threading(ddc_tool_entry(fn, **kwargs))` — which **calls** the tracking, on the
  main thread, and then starts a thread to run its return value, `None`.

If MCA wants to know which tools artists use, that is a small opt-in module with its
destination in configuration and no personal data in the repository. It is not this.

`tools/python_editor` is 28 lines that subclass `mca.mya.pyqt.mayawindows` — a Maya module,
imported from inside mca-common, which is the one direction the framework's layering does not
allow, and it is why nothing could import it outside Maya. The editor artists actually use is
its own application (`MCAEditor`), with the MCP server this pipeline talks to.

`plasticscm/` is 1,824 lines — a REST client, two model layers and a set of Qt dialogs for
Plastic SCM — and **nothing imports any of it**, anywhere in the framework. The studio moved to
Perforce and left the words behind: `fileio`, `ma_fileio` and the scene manager all still say
"Attempts to check out the file in plastic" above code that calls `perforce`. It can come back
as a backend behind the interface above, from Plastic's own current API, when a project needs
it.

`utils/plastic.py` went with it. Sixty lines, and worth reading once: its module docstring says
"Module starts Maya"; `is_plastic_server_running()` **kills the server** it was asked to ask
about, printing `Killing Plastic Server` as it goes; `run_plastic_server` has its
`if not server_running:` commented out, so it starts another one every time; and the `_REST`
class it opens with has methods with no `self` and a decorator nothing ever applied.

`prefvars.py` was a 217-line preference-variable system with a singleton registry, JSON
save/load and a docstring explaining how to subclass it. Nothing subclasses it and nothing
imports it, anywhere in the framework, and it had never worked: the defaults and names were
kept on **class** attributes of the base, so every subclass would have shared one dictionary;
`reset()` looked defaults up by attribute name while they were stored under the declared
`name`, a `KeyError` for any var that renamed itself; and the duplicate check called
`set.union` and threw the result away, so it could never find a duplicate. Preferences are
the launcher's `.pref` files and `QSettings` now.

## Tests

```
python tests/test_log.py
```

They need nothing but Python — no DCC, no Qt, no display.
