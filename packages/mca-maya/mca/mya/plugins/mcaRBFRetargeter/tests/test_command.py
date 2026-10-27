"""Smoke test mcaRetargetShapes headless, so an untested .mll cannot take a rig with it.

The maths is covered off-DCC by test_retarget.cpp. This is about the Maya shell:
do the flags parse, does a bad call say so instead of half-working, do the new
shapes come out as real transforms with the right points in them, and does undo
take them away again.

The measurement worth keeping is the affine one. Target = source moved five
units in X, and nothing else. A linear RBF with the polynomial term reproduces
that exactly; without it the answer drifts between the solver points. That drift
is the tool this replaces.

Why a cube and not a plane
--------------------------
The first version of this suite built its meshes from polyPlane and reported the
affine check failing by exactly 1.0 - the whole of the shape's displacement. The
plug-in was right and the test was wrong: every vertex of a plane has y = 0, so
the [1, x, y, z] system has a constant column, the y coefficient is not
determined by anything, and least squares quite correctly sets it to zero. A
flat solver point set cannot describe what happens off the flat. The node said
so - it raised its rank warning on the very first solve - and the check ignored
it. Solver points have to span three dimensions, so the meshes here are cubes.
"""

import os as _os
import tempfile as _tempfile

PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PLUGIN_NAME = _os.path.basename(PLUGIN_ROOT)


def _plugin_binary(version):
    return _os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                         '{}_maya{}.mll'.format(PLUGIN_NAME, version))


import json, traceback

RESULT = _os.path.join(_tempfile.gettempdir(), 'mcaRBFRetargeter_command.json')
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
    out['version'] = version

    path = _plugin_binary(version)
    cmds.loadPlugin(path)
    check('the plug-in loads', True)
    check('the command registers',
          'mcaRetargetShapes' in (cmds.pluginInfo(path, query=True, command=True) or []),
          str(cmds.pluginInfo(path, query=True, command=True)))

    cmds.undoInfo(state=True, infinity=True)

    OFFSET = 5.0
    DISPLACEMENT = 3.0

    def points(node):
        flat = cmds.xform(node + '.vtx[*]', query=True, objectSpace=True, translation=True)
        return [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]

    def build_scene():
        """Source, a target that is only the source moved, and a shape.

        A cube, not a plane: see the note at the top of this file.
        """
        cmds.file(new=True, force=True)
        cmds.loadPlugin(path, quiet=True)
        cmds.undoInfo(state=True, infinity=True)
        source = cmds.polyCube(name='src', sx=2, sy=2, sz=2, ch=False)[0]
        target = cmds.duplicate(source, name='tgt')[0]
        cmds.move(OFFSET, 0, 0, target + '.vtx[*]', objectSpace=True, relative=True)
        shape = cmds.duplicate(source, name='srcShape')[0]
        # Three units, not one. At one unit the displaced vertex lands exactly on
        # top of another cube vertex - so it sits on a solver point, every kernel
        # reproduces it, and the affine check below passed at 1e-16 whether the
        # polynomial term was on or off. A check that passes on noise is not a
        # check. The probe has to be somewhere no solver point already is, and
        # outside their hull, because that is where the two behaviours differ.
        cmds.move(0, DISPLACEMENT, 0, shape + '.vtx[0]', objectSpace=True, relative=True)
        return source, target, shape

    def corners(mesh, count=8):
        """The vertices furthest from the centre - a cube's corners.

        Chosen by measurement rather than by index, so the check does not
        quietly start solving on a face if the cube's vertex order changes.
        """
        ranked = sorted(enumerate(points(mesh)),
                        key=lambda pair: -(abs(pair[1][0]) + abs(pair[1][1]) +
                                           abs(pair[1][2])))
        return ['{}.vtx[{}]'.format(mesh, index) for index, _ in ranked[:count]]

    # --- it refuses a call it cannot honour, and says which part ---------------- #
    source, target, shape = build_scene()

    for label, kwargs in (('without -source', {'target': target, 'shape': [shape]}),
                          ('without -target', {'source': source, 'shape': [shape]}),
                          ('without -shape', {'source': source, 'target': target})):
        try:
            cmds.mcaRetargetShapes(**kwargs)
            check('a call {} is refused'.format(label), False, 'it returned instead')
        except Exception as exc:
            check('a call {} is refused'.format(label), True, str(exc))

    # --- the headline: a pure move is reproduced exactly ------------------------ #
    cmds.select(clear=True)
    made = cmds.mcaRetargetShapes(source=source, target=target, shape=[shape])
    check('it returns the name of what it made', bool(made) and len(made) == 1, str(made))

    result = made[0]
    check('and that name is a real node', cmds.objExists(result), str(result))
    # MFnMesh::copy names its result "polySurface1". Forty correctives in one
    # call would come back as polySurface1..40 in loop order, which is forty
    # shapes nobody can tell apart.
    check('the new shape is named after the shape it came from',
          result.startswith('srcShape') and result.endswith('_retargeted'), result)

    before = points(shape)
    after = points(result)
    check('the new shape has the source vertex count',
          len(after) == len(before), '{} vs {}'.format(len(after), len(before)))

    drift = max(max(abs(a[i] - (b[i] + (OFFSET if i == 0 else 0.0))) for i in range(3))
                for a, b in zip(after, before))
    out['affine_on_drift'] = drift
    check('a pure move is reproduced exactly with the affine term',
          drift < 1e-9, 'worst vertex is off by {}'.format(drift))

    # --- undo takes it away again ------------------------------------------------ #
    cmds.undo()
    check('undo removes the shape it made', not cmds.objExists(result), str(result))

    # --- without the affine term it drifts, which is the tool being replaced ----- #
    source, target, shape = build_scene()
    cmds.select(clear=True)
    made = cmds.mcaRetargetShapes(source=source, target=target, shape=[shape], affine=False)
    after = points(made[0])
    before = points(shape)
    plain = max(max(abs(a[i] - (b[i] + (OFFSET if i == 0 else 0.0))) for i in range(3))
                for a, b in zip(after, before))
    out['affine_off_drift'] = plain
    # A real number, not "bigger than the other one". Without the polynomial term
    # a linear RBF cannot describe a plain translation away from its centres, and
    # on a one-unit cube it misses by several units.
    check('turning the affine term off drifts by units, not by rounding error',
          plain > 0.5, 'with the term {}, without it {}'.format(drift, plain))

    # --- solver vertices come from the selection --------------------------------- #
    source, target, shape = build_scene()
    cmds.select(corners(source))
    made = cmds.mcaRetargetShapes(source=source, target=target, shape=[shape])
    after = points(made[0])
    before = points(shape)
    sparse = max(max(abs(a[i] - (b[i] + (OFFSET if i == 0 else 0.0))) for i in range(3))
                 for a, b in zip(after, before))
    out['eight_point_drift'] = sparse
    check('eight well-spread vertices are enough for a move', sparse < 1e-9,
          'worst vertex is off by {}'.format(sparse))

    # --- the guard refuses a solve nobody can hold, through Maya ------------------ #
    source, target, shape = build_scene()
    cmds.select(clear=True)
    try:
        cmds.mcaRetargetShapes(source=source, target=target, shape=[shape],
                               maxSolverPoints=5)
        check('the size guard refuses a solve above maxSolverPoints', False,
              'it solved anyway')
    except Exception as exc:
        check('the size guard refuses a solve above maxSolverPoints', True, str(exc))
    check('and the refused call left nothing behind',
          len(cmds.ls(type='mesh')) == 3, str(cmds.ls(type='mesh')))

    # --- a shape that does NOT share the source topology is carried anyway --------- #
    #
    # This is the rule reversed. The first version refused it, reasoning that a
    # blendshape target shares its base's topology - true for correctives, and
    # wrong for the tool. What the solve builds is a function of POSITION, so it
    # applies to any mesh sitting in the source's space. The refusal broke the
    # main thing this gets used for: one garment, fitted to a base body, refitted
    # onto each body variant, where the garment has a fraction of the body's
    # vertices. The tool this replaces had no such check.
    source, target, shape = build_scene()
    rider = cmds.polySphere(name='rider', sx=6, sy=6, ch=False)[0]
    cmds.scale(0.3, 0.3, 0.3, rider)
    cmds.makeIdentity(rider, apply=True, scale=True)
    rider_count = cmds.polyEvaluate(rider, vertex=True)
    source_count = cmds.polyEvaluate(source, vertex=True)
    check('the rider really does have different topology', rider_count != source_count,
          '{} vs {}'.format(rider_count, source_count))

    cmds.select(clear=True)
    carried = cmds.mcaRetargetShapes(source=source, target=target, shape=[rider])
    check('a mesh with a different vertex count is carried across, not refused',
          bool(carried) and len(carried) == 1, str(carried))
    check('and it keeps its own vertex count',
          cmds.polyEvaluate(carried[0], vertex=True) == rider_count,
          str(cmds.polyEvaluate(carried[0], vertex=True)))

    # It sits inside the source, so it should be moved by the same translation.
    before = points(rider)
    after = points(carried[0])
    rider_drift = max(max(abs(a[i] - (b[i] + (OFFSET if i == 0 else 0.0)))
                          for i in range(3)) for a, b in zip(after, before))
    out['rider_drift'] = rider_drift
    # 1e-5, not the 1e-9 the cube checks use, and the difference is not sloppiness.
    # A mesh stores its points as FLOATS. The cube's retargeted coordinates are
    # values like 4.5 and 5.5, which are exactly representable, so they survive
    # the round trip at 1e-17 and the tight threshold passes. A sphere's are not,
    # so they come back one float epsilon out - the first run of this check read
    # 2.235e-07, which against a coordinate of ~5.5 is 2^-24 exactly. That is the
    # mesh format, not the solve. Asserting 1e-9 here would have been a check that
    # fails for a reason having nothing to do with what it is testing.
    check('and the deformation is applied to it, to mesh precision',
          rider_drift < 1e-5, str(rider_drift))

    # --- the two meshes describing the deformation still must match ---------------- #
    source, target, shape = build_scene()
    other = cmds.polyCube(name='wrongTopology', sx=1, sy=1, sz=1, ch=False)[0]
    cmds.select(clear=True)
    try:
        cmds.mcaRetargetShapes(source=source, target=other, shape=[shape])
        check('a target with the wrong vertex count is still refused', False, 'it ran')
    except Exception as exc:
        check('a target with the wrong vertex count is still refused', True, str(exc))

    # --- several shapes in one call ------------------------------------------------ #
    source, target, shape = build_scene()
    second = cmds.duplicate(source, name='secondShape')[0]
    cmds.move(0, 0, 1, second + '.vtx[3]', objectSpace=True, relative=True)
    cmds.select(clear=True)
    made = cmds.mcaRetargetShapes(source=source, target=target, shape=[shape, second])
    check('-shape can be given more than once', len(made) == 2, str(made))
    check('and each one is named after its own source shape',
          any(name.startswith('srcShape') for name in made) and
          any(name.startswith('secondShape') for name in made), str(made))
    cmds.undo()
    check('undo removes both of them',
          not any(cmds.objExists(name) for name in made), str(made))

    # --- sphere anchors do not break a straight move -------------------------------- #
    source, target, shape = build_scene()
    cmds.select(clear=True)
    made = cmds.mcaRetargetShapes(source=source, target=target, shape=[shape],
                                  sphereAnchors=60)
    after = points(made[0])
    before = points(shape)
    with_sphere = max(max(abs(a[i] - (b[i] + (OFFSET if i == 0 else 0.0))) for i in range(3))
                      for a, b in zip(after, before))
    out['sphere_drift'] = with_sphere
    check('sphere anchors still reproduce a pure move', with_sphere < 1e-6,
          'worst vertex is off by {}'.format(with_sphere))

    # --- two vertices in the same place are reported, not silently wrong ------------ #
    source, target, shape = build_scene()
    picked = corners(source)
    cmds.move(0, 0, 0, picked[0], objectSpace=True, absolute=True)
    cmds.move(0, 0, 0, picked[1], objectSpace=True, absolute=True)
    cmds.select(picked)
    try:
        cmds.mcaRetargetShapes(source=source, target=target, shape=[shape],
                               regularization=1e-6)
        check('coincident solver vertices do not crash the command', True)
    except Exception as exc:
        check('coincident solver vertices do not crash the command', False, str(exc))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1)

print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
