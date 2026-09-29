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
| `paths/` | to do |
| `startup/` | to do |
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

## Tests

```
python tests/test_log.py
```

They need nothing but Python — no DCC, no Qt, no display.
