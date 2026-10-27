"""Exercise the mcaCageWrap node headless: the maths is covered off-DCC by
test_cage.cpp, so this is about everything Maya brings - which plug the cage comes
from, what space it is in, when it rebinds, paintable weights and the envelope."""

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

import json, math, traceback

import maya.standalone as _standalone  # noqa: E402  (needed before cmds)
_standalone.initialize(name='python')
import maya.cmds as _cmds  # noqa: E402
_VERSION = _cmds.about(version=True).split()[0]
MLL = _plugin_binary(_VERSION)
RESULT = _result_path('mcaCageWrap_node.json')

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))
    print('{}  {}'.format('ok  ' if condition else 'FAIL', label))


out['version'] = _VERSION
out['mll'] = MLL

try:
    import maya.cmds as cmds
    _add_framework_paths(_VERSION)

    check('the plug-in binary exists', _os.path.isfile(MLL), MLL)
    cmds.loadPlugin(MLL)
    check('it loads', 'mcaCageWrap' in (cmds.pluginInfo(_os.path.basename(MLL), q=True,
                                                        dependNode=True) or []))

    def box(name, size, at=(0.0, 0.0, 0.0)):
        """A cage: a cube, left as quads on purpose - the node triangulates it."""
        made = cmds.polyCube(width=size, height=size, depth=size, name=name)[0]
        cmds.move(at[0], at[1], at[2], made, absolute=True)
        return made

    def positions(mesh):
        flat = cmds.xform(mesh + '.vtx[*]', q=True, worldSpace=True, translation=True)
        return [tuple(flat[index:index + 3]) for index in range(0, len(flat), 3)]

    def worst(got, want):
        return max(math.dist(a, b) for a, b in zip(got, want))

    def wire(mesh, cage, rest_cage):
        """Make the deformer and connect the two cages, the way the API will."""
        node = cmds.deformer(mesh, type='mcaCageWrap')[0]
        rest_shape = cmds.listRelatives(rest_cage, shapes=True, noIntermediate=True)[0]
        cage_shape = cmds.listRelatives(cage, shapes=True, noIntermediate=True)[0]
        cmds.connectAttr(rest_shape + '.outMesh', node + '.restCage')
        cmds.connectAttr(rest_cage + '.worldMatrix[0]', node + '.restCageMatrix')
        cmds.connectAttr(cage_shape + '.outMesh', node + '.cage')
        cmds.connectAttr(cage + '.worldMatrix[0]', node + '.cageMatrix')
        return node

    # --- the basic job --------------------------------------------------------- #
    cmds.file(new=True, force=True)
    mesh = cmds.polySphere(radius=1.0, subdivisionsX=12, subdivisionsY=12, name='victim')[0]
    rest_cage = box('restCage', 3.0)
    moving = cmds.duplicate(rest_cage, name='cage')[0]
    cmds.hide(rest_cage)

    before = positions(mesh)
    node = wire(mesh, moving, rest_cage)
    check('the deformer is created and connected', cmds.objExists(node))

    cmds.dgeval(mesh + '.outMesh')
    after = positions(mesh)
    rest_move = worst(after, before)
    out['rest_move'] = rest_move
    check('with the cage at rest the mesh does not move', rest_move < 1e-5, str(rest_move))
    check('and it says how well it bound',
          cmds.getAttr(node + '.worstRestError') < 1e-5,
          str(cmds.getAttr(node + '.worstRestError')))
    check('and how many points fell outside the cage',
          cmds.getAttr(node + '.pointsOutside') == 0,
          str(cmds.getAttr(node + '.pointsOutside')))
    check('and how many weights it kept', cmds.getAttr(node + '.weightsKept') > 0,
          str(cmds.getAttr(node + '.weightsKept')))

    # --- it follows the cage -------------------------------------------------- #
    cmds.move(4.0, -1.0, 2.0, moving, relative=True)
    cmds.dgeval(mesh + '.outMesh')
    moved = positions(mesh)
    want = [(x + 4.0, y - 1.0, z + 2.0) for x, y, z in before]
    translation = worst(moved, want)
    out['translation'] = translation
    check('moving the cage moves the mesh with it', translation < 1e-5, str(translation))

    cmds.move(-4.0, 1.0, -2.0, moving, relative=True)

    # A quad cage, deliberately: the node triangulates it, so nobody has to.
    check('a cage left as quads is accepted',
          cmds.polyEvaluate(rest_cage, face=True) == 6 and
          cmds.getAttr(node + '.worstRestError') < 1e-5)

    # --- a cage vertex on its own --------------------------------------------- #
    cmds.select(clear=True)
    cmds.move(0.0, 2.0, 0.0, moving + '.vtx[2]', relative=True)
    cmds.move(0.0, 2.0, 0.0, moving + '.vtx[3]', relative=True)
    cmds.move(0.0, 2.0, 0.0, moving + '.vtx[6]', relative=True)
    cmds.move(0.0, 2.0, 0.0, moving + '.vtx[7]', relative=True)
    cmds.dgeval(mesh + '.outMesh')
    stretched = positions(mesh)
    lift = max(point[1] for point in stretched) - max(point[1] for point in before)
    out['lift'] = lift
    check('pulling the top of the cage up stretches the mesh up', lift > 0.3, str(lift))

    # --- stretch changes the thickness, and nothing else does ----------------- #
    thin = max(abs(point[0]) for point in positions(mesh))
    cmds.setAttr(node + '.stretch', 1.0)
    cmds.dgeval(mesh + '.outMesh')
    thick = max(abs(point[0]) for point in positions(mesh))
    out['width_at_no_stretch'] = thin
    out['width_at_full_stretch'] = thick
    check('stretch changes how thick the shape gets', abs(thick - thin) > 1e-4,
          '{} against {}'.format(thin, thick))
    cmds.setAttr(node + '.stretch', 0.0)

    # --- the envelope --------------------------------------------------------- #
    cmds.setAttr(node + '.envelope', 0.0)
    cmds.dgeval(mesh + '.outMesh')
    off = worst(positions(mesh), before)
    check('an envelope of zero leaves the mesh alone', off < 1e-6, str(off))

    cmds.setAttr(node + '.envelope', 0.5)
    cmds.dgeval(mesh + '.outMesh')
    half = positions(mesh)
    cmds.setAttr(node + '.envelope', 1.0)
    cmds.dgeval(mesh + '.outMesh')
    full = positions(mesh)
    halfway = max(abs(math.dist(h, b) * 2.0 - math.dist(f, b))
                  for h, f, b in zip(half, full, before))
    out['half_envelope'] = halfway
    check('half an envelope moves each point half as far', halfway < 1e-4, str(halfway))

    # --- paintable weights --------------------------------------------------- #
    cmds.setAttr(node + '.weightList[0].weights[0:5]', 0, 0, 0, 0, 0, 0)
    cmds.dgeval(mesh + '.outMesh')
    painted = positions(mesh)
    pinned = max(math.dist(painted[index], before[index]) for index in range(6))
    out['painted_weight_zero'] = pinned
    check('a painted weight of zero pins those points', pinned < 1e-6, str(pinned))
    cmds.setAttr(node + '.weightList[0].weights[0:5]', 1, 1, 1, 1, 1, 1)

    # --- editing the REST cage rebinds on its own ----------------------------- #
    #
    # The plug-in this replaces caches the rest cage on first evaluation and keeps it
    # until somebody flips a refresh attribute, so editing it afterwards deforms
    # against a cage that is no longer there. Nothing warns; it just looks wrong.
    cmds.dgeval(mesh + '.outMesh')
    cmds.setAttr(moving + '.translate', 0, 0, 0)
    cmds.xform(moving + '.vtx[0:7]', absolute=False, translation=(0, 0, 0))
    cmds.delete(mesh, constructionHistory=False)

    cmds.file(new=True, force=True)
    mesh = cmds.polySphere(radius=1.0, subdivisionsX=8, subdivisionsY=8, name='victim')[0]
    rest_cage = box('restCage', 3.0)
    moving = cmds.duplicate(rest_cage, name='cage')[0]
    node = wire(mesh, moving, rest_cage)
    cmds.dgeval(mesh + '.outMesh')
    start = positions(mesh)

    # Grow the rest cage AND the moving cage the same way: the mesh must stay put,
    # which can only happen if it rebound against the new rest cage.
    for vertex in range(8):
        for shape in (rest_cage, moving):
            point = cmds.pointPosition('{}.vtx[{}]'.format(shape, vertex), world=True)
            cmds.xform('{}.vtx[{}]'.format(shape, vertex), worldSpace=True,
                       translation=[value * 1.4 for value in point])
    cmds.dgeval(mesh + '.outMesh')
    drift = worst(positions(mesh), start)
    out['rebind_drift'] = drift
    check('editing the rest cage rebinds without being asked', drift < 1e-4, str(drift))

    # --- refusals: it passes the geometry through rather than failing --------- #
    cmds.file(new=True, force=True)
    mesh = cmds.polySphere(radius=1.0, name='victim')[0]
    before = positions(mesh)
    node = cmds.deformer(mesh, type='mcaCageWrap')[0]
    cmds.dgeval(mesh + '.outMesh')
    check('with no cage connected the mesh is passed through untouched',
          worst(positions(mesh), before) < 1e-9)

    holed = box('holedCage', 3.0)
    cmds.delete(holed + '.f[0]')
    holed_shape = cmds.listRelatives(holed, shapes=True, noIntermediate=True)[0]
    cmds.connectAttr(holed_shape + '.outMesh', node + '.restCage')
    cmds.connectAttr(holed + '.worldMatrix[0]', node + '.restCageMatrix')
    cmds.connectAttr(holed_shape + '.outMesh', node + '.cage')
    cmds.connectAttr(holed + '.worldMatrix[0]', node + '.cageMatrix')
    cmds.dgeval(mesh + '.outMesh')
    check('a cage with a hole in it leaves the mesh alone rather than exploding it',
          worst(positions(mesh), before) < 1e-9)

    out['ok'] = not out['failures']

except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1, default=str)

print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
