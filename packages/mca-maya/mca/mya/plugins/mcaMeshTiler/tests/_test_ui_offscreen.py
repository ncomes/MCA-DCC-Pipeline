"""Drive the Mesh Tiler window offscreen, so a broken UI is found here and not by a user."""

# --- where things are, worked out from this file ----------------------------- #
#
# Everything below is derived rather than hardcoded. These suites used to carry
# absolute paths into a scratch folder, which meant they only ran on one machine
# from one place.
import os as _os
import sys as _sys
import tempfile as _tempfile

#: <package root>/mca-maya/mca/mya/plugins/<plugin>
PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PLUGIN_NAME = _os.path.basename(PLUGIN_ROOT)
#: The `packages` folder six levels up: tests -> plugin -> plugins -> mya -> mca
#: -> mca-maya -> packages.
PACKAGES = _os.path.abspath(_os.path.join(PLUGIN_ROOT, *([_os.pardir] * 5)))


def _plugin_binary(version):
    """:return: This plugin's .mll for a Maya version."""
    return _os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                         '{}_maya{}.mll'.format(PLUGIN_NAME, version))


def _result_path(name):
    """Results go to the temp folder, not into the repo next to the suite."""
    return _os.path.join(_tempfile.gettempdir(), name)


def _add_framework_paths(version):
    """Put the framework and its bundled dependencies on sys.path.

    The bundles are APPENDED, never inserted: the python311 bundle carries its
    own PySide6 that does not import under mayapy, and `mca.common.pyqt.pygui`
    swallows the ImportError and hands back a stub - so putting it in front turns
    every Qt call into an AttributeError several frames from the cause.
    """
    for package in ('mca-common', 'mca-maya'):
        path = _os.path.join(PACKAGES, package)
        if path not in _sys.path:
            _sys.path.insert(0, path)
    for bundle in (_os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                 'dependencies', str(version)),
                   _os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                 'dependencies',
                                 'python{}{}'.format(*_sys.version_info[:2])),
                   _os.path.join(PACKAGES, 'dependancies')):
        if _os.path.isdir(bundle) and bundle not in _sys.path:
            _sys.path.append(bundle)
import json, os, sys, traceback

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

RESULT = _result_path('mcaMeshTiler_ui_offscreen.json')

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


try:
    import maya.standalone
    maya.standalone.initialize(name='python')
    import maya.cmds as cmds

    version = cmds.about(version=True).split()[0]
    for bundle in (os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                'dependencies', version),
                   os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                'dependencies', 'python{}{}'.format(*sys.version_info[:2])),
                   os.path.join(PACKAGES, 'dependancies')):
        # APPEND, never insert. The framework's python311 bundle carries its own
        # PySide6 that does not import under mayapy, and pygui swallows the
        # ImportError and hands back a stub - so putting it in front turns every
        # Qt call into AttributeError several frames later.
        if os.path.isdir(bundle):
            sys.path.append(bundle)
    for package in ('mca-common', 'mca-maya'):
        sys.path.insert(0, os.path.join(PACKAGES, package))

    from mca.common.pyqt.pygui import qtwidgets
    app = qtwidgets.QApplication.instance() or qtwidgets.QApplication([])
    check('Qt starts offscreen', app is not None)

    from mca.mya.tools.meshtiler import meshtiler_ui
    check('the ui module imports', True)

    window = meshtiler_ui.MeshTilerUI()
    check('the window constructs', window is not None)
    out['status_on_open'] = window.status.text()
    check('it loads the plug-in on open', window.create_button.isEnabled(),
          window.status.text())
    check('the live half starts disabled', not window.live.isEnabled())

    # Pressing Create with nothing picked must complain, not throw.
    window._create()
    check('Create with nothing picked says so instead of throwing',
          'tile' in window.status.text().lower(), window.status.text())

    # --- the sample ---------------------------------------------------------- #
    window._build_sample()
    out['status_after_sample'] = window.status.text()
    check('Build Sample Scene works from the window',
          cmds.objExists('setup1_quads') and cmds.objExists('setup3_ngons'),
          window.status.text())
    check('the sample targets are selectable',
          not cmds.getAttr('quad_target.overrideEnabled'),
          'overrideEnabled is on, so it cannot be picked in the viewport')

    # --- the ordinary path ---------------------------------------------------- #
    tile = cmds.polyPlane(w=1, h=1, sx=1, sy=1, ch=False)[0]
    target = cmds.polyCube(sx=2, sy=2, sz=2, ch=False)[0]

    cmds.select(tile)
    window._pick_tile()
    cmds.select(target)
    window._pick_target()
    check('picking meshes from the selection works',
          window.tile_field.text() == tile and window.target_field.text() == target,
          '{} / {}'.format(window.tile_field.text(), window.target_field.text()))

    window.area_scale.setValue(0.5)
    window.height_offset.setValue(0.1)
    window._create()
    out['status_after_create'] = window.status.text()
    check('Create Tiles builds something', window.live.isEnabled(), window.status.text())
    check('and the window adopts the tiler it made', bool(window._tiler))

    tiler = window._tiler
    out['tiler'] = str(tiler)
    transform = window._output_transform()
    out['output_transform'] = str(transform)
    check('it can find the mesh its tiler drives', bool(transform))
    check('the knobs reached the node',
          abs(cmds.getAttr(tiler + '.areaScale') - 0.5) < 1e-9 and
          abs(cmds.getAttr(tiler + '.heightOffset') - 0.1) < 1e-9)

    # --- rotation ------------------------------------------------------------- #
    cmds.select(clear=True)
    window._rotate(1)
    check('rotating with no faces selected says so instead of throwing',
          'select' in window.status.text().lower(), window.status.text())

    cmds.select([target + '.f[0]', target + '.f[3]'])
    window._rotate(1)
    out['status_after_rotate'] = window.status.text()
    check('rotating selected faces works',
          cmds.getAttr(tiler + '.faceRotation[0]') == 1, window.status.text())

    window._clear_rotations()
    check('clearing rotations works',
          not (cmds.getAttr(tiler + '.faceRotation', multiIndices=True) or []),
          window.status.text())

    # --- freeze --------------------------------------------------------------- #
    faces_before = cmds.polyEvaluate(transform, face=True)
    window._freeze()
    out['status_after_freeze'] = window.status.text()
    check('Freeze bakes the geometry down',
          cmds.polyEvaluate(transform, face=True) == faces_before, window.status.text())
    check('and the tiler is gone', not cmds.objExists(str(tiler)))
    check('and the live half switches off again', not window.live.isEnabled())

    # --- remove --------------------------------------------------------------- #
    cmds.select(tile)
    window._pick_tile()
    cmds.select(target)
    window._pick_target()
    window._create()
    check('a second build works', window.live.isEnabled(), window.status.text())
    window._remove()
    out['status_after_remove'] = window.status.text()
    check('Remove takes it back out',
          not cmds.objExists(str(window._output_transform() or '')), window.status.text())

    # --- a tiler that vanished under the window --------------------------------- #
    cmds.select(tile)
    window._pick_tile()
    cmds.select(target)
    window._pick_target()
    window._create()
    stale = window._tiler
    cmds.delete(stale)
    window._clear_rotations()
    check('a tiler deleted behind the window is reported, not crashed into',
          'gone' in window.status.text().lower(), window.status.text())

    window.close()
    check('the window closes', True)

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3500:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1)

# Say it out loud as well as writing the file. A suite whose result you have to
# go and find is a suite nobody checks.
print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
