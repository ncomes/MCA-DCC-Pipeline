# mca-common

What every DCC in the pipeline shares. Nothing here imports a DCC: it runs in Maya,
MotionBuilder, Unreal, a standalone Python and the test suite.

Being ported from the depot one piece at a time — read, brought over, cleaned, and checked.
Each piece lands finished rather than copied and marked for later.

| piece | state |
|---|---|
| `log.py` | ported, 22 checks |
| `textio/` | to do |
| `utils/fileio.py`, `paths/` | to do |
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

## Tests

```
python tests/test_log.py
```

They need nothing but Python — no DCC, no Qt, no display.
