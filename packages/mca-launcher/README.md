# mca-launcher

Starts a DCC with the MCA pipeline on its path — and makes sure that DCC has the Python
packages the pipeline needs **before** it starts, every time.

```
mca-launcher                         open the window
mca-launcher --doctor                why will this not start
mca-launcher --dccs                  what is installed on this machine
mca-launcher --deps maya:2025        are its dependencies ready
mca-launcher --install-deps maya:2025
mca-launcher --launch maya:2025 --project Wayward
mca-launcher --launch maya --json    the same, as data
```

## How it is put together

```
mca/launcher/
  core/        no Qt, no DCC, no module-level state - testable with plain python
    contract.py        the ok/result/message answer shape
    platform_paths.py  the only module that knows this is Windows
    fileio.py          atomic writes, forgiving reads
    prefs.py           projects and selections, keyed by name
    projects.py        setting a project up, and validating one
    dependencies.py    the bootstrap: install, prove, stamp
    environment.py     what a DCC is handed, as a pure function
    dccs/              maya, mobu, unreal - versions, executables, interpreters
  api.py       every operation, each answering ok/result/message
  cli.py       the command line and the shortcut entry point
  ui/          PySide6 windows that call api and nothing else
tests/         run with any python; the window suite runs offscreen
```

**The rule:** the UI holds no logic the API does not have. Anything an artist can do by
clicking, a script, a build step or an agent can do by calling. That is what makes the
dependency guarantee possible — `api.launch` is the only way in, and it checks first.

## Dependencies

Installed **per DCC version, with that DCC's own interpreter**, into
`%LOCALAPPDATA%\MCA\deps\<dcc>-<version>\`.

Measured on one machine: Maya 2022 is Python 3.7.7, Maya 2024 is 3.10.8, Maya 2025 is 3.11.4,
Maya 2026 is 3.11.9, MotionBuilder 2024 is 3.10.8. A wheel built for one does not load in
another, so one shared folder cannot be right.

- The folder is **wiped before it is filled**, because `pip install --target` does not
  uninstall — which is how the old shared folder ended up holding PySide6 6.7.2, 6.10.0 *and*
  6.10.1 at once.
- **Qt is never installed into it.** Every supported DCC ships its own (PySide2 5.15 in 2022,
  2024 and MotionBuilder; PySide6 6.5.3 in 2025 and 2026), and a second Qt on `sys.path` is
  how you get an abort with no traceback.
- Being installed is proved **by importing the packages in that interpreter**, not by a
  folder existing. A half-finished install leaves the folders behind.
- What was installed is recorded in `.mca-deps.json`: the requirements hash, the interpreter,
  what imported, what was skipped. A later launch compares the hash and costs one file read.
- A package with no version for that Python is **skipped and named** rather than taking the
  whole list down with it — which is how Maya 2022's Python 3.7 keeps working without the AI
  packages.
- **If the packages are not ready, the DCC does not start.** A DCC without them looks like
  working software with broken tools, which is the most expensive kind of failure to
  diagnose.

`mca-common` owns the requirements list. This package reads it and installs it; it never
keeps a copy.

## Preferences

Under `Documents\mca_preferences`, and compatible with what the previous launcher wrote:

```
mca_launcher.pref                 which project was open last
<project>\mca_project.prefs       the project's paths
<project>\mca_launcher.pref       what was picked for it last time
```

Selections are stored **by name** (`{'maya': '2025'}`), not by dropdown position. An old file's
positions are read and discarded — install or uninstall a version and the same number means a
different thing — and the newest installed version is offered instead.

Three environment variables move everything, which is what lets the suites run without going
near a real machine's files: `MCA_PREFS_ROOT`, `MCA_DEPS_ROOT`, `MCA_LOGS_ROOT`.

## Tests

```
tests\run_tests.bat                                   or  ./run_tests.sh
tests\run_tests.bat "C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"
```

`test_core.py` and `test_api.py` need nothing but Python. `test_ui_window.py` builds both
windows offscreen and presses their buttons — including the case that matters most: a
dependency install that fails means **nothing is launched**. It skips cleanly where PySide6 is
not installed.
