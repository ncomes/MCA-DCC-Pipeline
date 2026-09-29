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
| `startup/dccs/` (userSetup and friends) | to do |
| `startup/configs/common_env.py` | **dropped** — see below |
| `pyqt/` | to do |
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

## Tests

```
python tests/test_log.py
```

They need nothing but Python — no DCC, no Qt, no display.
