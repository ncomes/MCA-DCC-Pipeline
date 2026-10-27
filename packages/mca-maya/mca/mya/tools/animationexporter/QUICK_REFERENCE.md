# Animation Exporter - Background Export Quick Reference

## What Was Added

A **"Export in Background"** checkbox that exports animations in a hidden, detached Maya process.

## For Users

### How to Use
1. Open Animation Exporter
2. Check "Export in Background" (state saved between sessions)
3. Click "Export Selected" or "Export All"
4. Export runs silently in background
5. Check log file for results: `C:\Users\<you>\Documents\mca_preferences\<Project>\prefs\maya\animationexporter\anim_export_log_*.txt`

### After Export
Reconcile FBX files with Perforce:
```bash
p4 reconcile <your depot>\Characters\**\*.fbx
```

## For Developers

### Files to Review

**Core Implementation**:
- `animationexporter_ui.py` - UI launcher and process management
- `animationexporter_batch_runner.py` - Batch export script (NEW)
- `headless_startup.py` - Batch-safe MCA init (NEW)

**Supporting Changes**:
- `animationexporter_utils.py` - Skip P4 in batch mode
- `ma_main_window.py` - Added batch mode guards
- `animationexporter_mainUI.ui` - Added checkbox

**Documentation**:
- `BACKGROUND_EXPORT_NOTES.md` - Feature documentation
- `SESSION_SUMMARY_BACKGROUND_EXPORT.md` - Implementation details
- `HEADLESS_STARTUP_README.md` - Headless framework docs
- `QUICK_REFERENCE.md` - This file

### Key Concepts

**Headless Startup** (`headless_startup.py`):
```python
from mca.mya.startup import headless_startup
headless_startup.init()  # Batch-safe, no Qt/GUI
```

**Batch Mode Detection**:
```python
import pymel.core as pm
if pm.about(batch=True):
    return None  # Skip GUI operations
```

**Detached Process**:
```python
subprocess.Popen(
    ['maya.exe', '-batch', '-script', script],
    stdout=log_file,
    startupinfo=startupinfo,  # Hide window
    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
)
```

### Testing
✅ Tested and working:
- Export completes successfully
- No console window visible
- Process continues if UI closes
- Maya quits automatically
- Temp files cleaned up

### Known Limitations
- No real-time progress (check log file)
- No Perforce auto-checkout (reconcile manually)
- No cancellation (must kill via Task Manager)

## Quick Answers

**Q**: Where are log files?
**A**: `C:\Users\<you>\Documents\mca_preferences\<Project>\prefs\maya\animationexporter\`

**Q**: Why no auto P4 checkout?
**A**: Detached processes can't spawn subprocesses. Reconcile manually after.

**Q**: Can I use this for other tools?
**A**: Yes! Use `headless_startup.py` for any batch Maya operation.

**Q**: How do I debug?
**A**: Check log file. Temporarily remove `CREATE_NO_WINDOW` flag to see console.

**Q**: Will this work on other OS?
**A**: Process hiding is Windows-specific. Core functionality should work on Mac/Linux.

## For Future AI Sessions

Read these files first:
1. `SESSION_SUMMARY_BACKGROUND_EXPORT.md` - Full implementation story
2. `BACKGROUND_EXPORT_NOTES.md` - Feature documentation
3. `animationexporter_batch_runner.py` - Reference implementation

Key patterns established:
- Headless startup module (reusable)
- Detached process launching (proven)
- Batch mode guards (required for Qt code)

## Perforce Commands

```bash
# See what was changed
p4 opened

# Add new files
p4 add <file>

# Revert if needed
p4 revert <file>

# Submit changes
p4 submit

# Check file status
p4 fstat <file>
```