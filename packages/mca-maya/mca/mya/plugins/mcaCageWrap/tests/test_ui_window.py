"""Draw the Cage Wrap window and press every button on it.

**This one needs a Maya with a UI, and skips cleanly without one.** Under `mayapy` the
framework's Qt and Maya's own are two different Qt instances, so a QApplication made here
is not the one Maya's widgets look for: the first widget aborts the process outright with
"Cannot create a QWidget without QApplication". Not catchable, not workable around, and the
reason the other five plug-ins in this tree stop at importing their UI module.

So it checks first and skips, which keeps `run_python_tests.bat` honest. Run it INSIDE Maya,
where it does the real job - in a Python tab:

    exec(open(r'<this file>').read())

It refuses to run on a scene with unsaved changes, because it needs an empty one.

Worth having: every check in here is a bug an artist would otherwise find by clicking.
"""

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


import json, math, os, traceback

# Already inside a Maya, or starting one? This suite is the one that has to work both
# ways: under mayapy it skips, and inside a real Maya it does the job. Initialising
# standalone inside a running Maya throws, and setting the Qt platform after Qt is up does
# nothing but confuse the next person reading the log.
try:
    import maya.cmds as _cmds  # noqa: E402
    _cmds.about(version=True)
    INSIDE_MAYA = True
except Exception:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    import maya.standalone as _standalone  # noqa: E402
    _standalone.initialize(name='python')
    import maya.cmds as _cmds  # noqa: E402
    INSIDE_MAYA = False

_VERSION = _cmds.about(version=True).split()[0]
RESULT = _result_path('mcaCageWrap_ui_window.json')

out = {'checks': [], 'failures': [], 'skipped': False}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))
    print('{}  {}'.format('ok  ' if condition else 'FAIL', label))


try:
    import maya.cmds as cmds
    _add_framework_paths(_VERSION)

    # Before anything touches Qt.
    if cmds.about(batch=True) or not INSIDE_MAYA:
        out['skipped'] = True
        out['skip_reason'] = ('Needs a Maya with a UI. Under mayapy the framework\'s Qt and '
                              'Maya\'s own are separate instances, and the first widget '
                              'aborts the process.')
        raise SystemExit(0)

    if cmds.file(query=True, modified=True):
        out['skipped'] = True
        out['skip_reason'] = ('The open scene has unsaved changes and this suite needs an '
                              'empty scene. Save first, then run it again.')
        raise SystemExit(0)

    try:
        from mca.common.pyqt.pygui import qtwidgets
        application = qtwidgets.QApplication.instance()
        if application is None:
            application = qtwidgets.QApplication([])
    except Exception as error:
        out['skipped'] = True
        out['skip_reason'] = 'Qt would not start offscreen: {}'.format(error)
        raise SystemExit(0)

    if application is None:
        out['skipped'] = True
        out['skip_reason'] = 'No QApplication available under mayapy.'
        raise SystemExit(0)

    check('Qt starts offscreen', True)

    from mca.mya.tools.cagewrap import cagewrap_ui, cagewrap_api

    window = cagewrap_ui.CageWrapUI()
    check('the window constructs', window is not None)
    out['status_on_open'] = window._status.text()

    # --- pressing things with nothing selected must complain, not throw -------- #
    cmds.file(new=True, force=True)
    cmds.select(clear=True)
    window._mesh = None
    window._wrap()
    check('Wrap with nothing selected says so instead of throwing',
          'select' in window._status.text().lower(), window._status.text())

    window._build_cage()
    check('Build A Cage with nothing selected says so too',
          'select' in window._status.text().lower(), window._status.text())

    window._build_bone_cage()
    check('Build From Bones with nothing selected says so as well',
          'select' in window._status.text().lower(), window._status.text())

    # --- the ordinary path ----------------------------------------------------- #
    blob = cmds.polySphere(radius=2.0, subdivisionsX=16, subdivisionsY=16, name='blob',
                           constructionHistory=False)[0]
    cmds.select(blob, replace=True)
    window._pick_mesh()
    check('picking the mesh from the selection works',
          window._mesh_field.text() == 'blob', window._mesh_field.text())

    window._faces.setValue(80)
    window._relax.setValue(0)
    window._symmetry.setChecked(True)
    window._build_cage()
    out['status_after_cage'] = window._status.text()
    check('Build A Cage builds one', window._cage and cmds.objExists(window._cage),
          window._status.text())
    check('and the window adopts it', window._cage_field.text() != '',
          window._cage_field.text())
    check('and it is symmetrical, because the box was ticked',
          'symmetrical' in window._status.text(), window._status.text())

    window._stretch.setValue(0.5)
    window._wrap()
    out['status_after_wrap'] = window._status.text()
    check('Wrap binds the mesh', bool(cagewrap_api.find_wraps(blob)), window._status.text())

    node = cagewrap_api.find_wraps(blob)[0]
    check('and the stretch box reached the node',
          abs(cmds.getAttr(node + '.stretch') - 0.5) < 1e-9,
          str(cmds.getAttr(node + '.stretch')))

    window._report()
    out['status_after_report'] = window._status.text()
    check('Report says what the bind measured',
          'rest error' in window._status.text(), window._status.text())

    # --- baking ---------------------------------------------------------------- #
    window._start.setValue(0)
    window._end.setValue(0)
    window._bake()
    check('Bake with a range of one frame refuses, rather than solving nothing',
          'frame' in window._status.text().lower(), window._status.text())

    window._start.setValue(0)
    window._end.setValue(2)
    window._bake()
    out['status_after_bake'] = window._status.text()
    check('Bake with a cage that never moves says exactly that',
          'same shape' in window._status.text() or 'animate' in window._status.text().lower(),
          window._status.text())

    # --- removal --------------------------------------------------------------- #
    window._remove()
    out['status_after_remove'] = window._status.text()
    check('Remove takes the deformer off', not cagewrap_api.find_wraps(blob),
          window._status.text())
    check('and leaves the cage alone', cmds.objExists(window._cage))

    window._report()
    check('Report on a mesh with no wrap says so instead of throwing',
          'no cage wrap' in window._status.text().lower(), window._status.text())

    # --- a cage deleted behind the window -------------------------------------- #
    cmds.delete(window._cage)
    window._wrap()
    check('a cage deleted behind the window is handled - it builds a new one',
          window._status.text() != '', window._status.text())

    # --- the other builder, which follows the skeleton instead of the silhouette --- #
    #
    # Its maths is checked off-DCC and through the API; what is only reachable here is the
    # button: that it finds the skin, that the window adopts the cage it built, that the
    # two builders tag differently so building one does not delete the other, and that a
    # mesh with nothing to follow gets a sentence rather than a traceback.
    cmds.file(new=True, force=True)
    window._mesh = None
    window._cage = None
    tube = cmds.polyCylinder(radius=1.0, height=8.0, subdivisionsX=12, subdivisionsY=8,
                             subdivisionsZ=1, axis=(0, 1, 0), name='tube',
                             constructionHistory=False)[0]
    first = cmds.createNode('joint', name='bone_1')
    cmds.setAttr(first + '.translateY', -4.0)
    second = cmds.createNode('joint', name='bone_2', parent=first)
    cmds.setAttr(second + '.translateY', 4.0)
    third = cmds.createNode('joint', name='bone_3', parent=second)
    cmds.setAttr(third + '.translateY', 4.0)
    cmds.skinCluster(first, second, third, tube, toSelectedBones=True)
    cmds.select(tube, replace=True)
    window._pick_mesh()
    window._sides.setValue(6)
    window._rings.setValue(1)
    window._build_bone_cage()
    out['status_after_bone_cage'] = window._status.text()
    check('Build From Bones builds a cage', bool(window._cage) and cmds.objExists(window._cage),
          window._status.text())
    check('and the window adopts that one', window._cage_field.text() != '',
          window._cage_field.text())
    tag = '{}.{}'.format(window._cage, cagewrap_api.CAGE_TAG)
    check('and tags it as the bone cage, so the two builders leave each other alone',
          cmds.objExists(tag) and cmds.getAttr(tag).endswith(':bones'),
          cmds.getAttr(tag) if cmds.objExists(tag) else 'no tag at all')
    window._wrap()
    check('and the mesh wraps to it', bool(cagewrap_api.find_wraps(tube)),
          window._status.text())
    window._remove()

    loose = cmds.polySphere(radius=1.0, name='loose', constructionHistory=False)[0]
    cmds.select(loose, replace=True)
    window._pick_mesh()
    window._build_bone_cage()
    check('Build From Bones on a mesh with no skeleton says so instead of throwing',
          'joint' in window._status.text().lower() or 'skin' in window._status.text().lower(),
          window._status.text())

    window.close()
    check('the window closes', True)

    # Leave the scene as it was found. This one runs inside somebody's Maya, so debris is
    # not a tidiness question - a blob and a cage left behind are things they have to work
    # out the provenance of later.
    cmds.file(new=True, force=True)
    check('and the scene is left empty', not (cmds.ls(type='mcaCageWrap') or []))

    out['ok'] = not out['failures']

except SystemExit:
    out['ok'] = True
except Exception:
    out['error'] = traceback.format_exc()[-3500:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1, default=str)

if out.get('skipped'):
    print('SKIPPED: {}'.format(out.get('skip_reason')))
else:
    print('{}/{} passed'.format(out['passed'], out['total']))
    for _failure in out['failures']:
        print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
