"""Build the sample scene headless and check it actually does something.

A sample that only proves it does not raise is worth very little. These checks
drive each control and assert the thing it is supposed to drive moved - which is
also the most realistic end-to-end test of the node there is, since the sample
wires it the way a rigger would.
"""

import os as _os
import sys as _sys
import tempfile as _tempfile

PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PACKAGES = _os.path.abspath(_os.path.join(PLUGIN_ROOT, *([_os.pardir] * 5)))


def _result_path(name):
    return _os.path.join(_tempfile.gettempdir(), name)


def _add_framework_paths(version):
    for package in ('mca-common', 'mca-maya'):
        path = _os.path.join(PACKAGES, package)
        if path not in _sys.path:
            _sys.path.insert(0, path)
    # Appended, never inserted: the python311 bundle's own PySide6 does not
    # import under mayapy and pygui hands back a stub if it wins.
    for bundle in (_os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                 'dependencies', str(version)),
                   _os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                 'dependencies',
                                 'python{}{}'.format(*_sys.version_info[:2])),
                   _os.path.join(PACKAGES, 'dependancies')):
        if _os.path.isdir(bundle) and bundle not in _sys.path:
            _sys.path.append(bundle)


import json, traceback

RESULT = _result_path('mcaRBFSolver_sample.json')
out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


try:
    import maya.cmds as cmds
    try:
        cmds.ls()
        out['context'] = 'inside an open Maya'
    except Exception:
        import maya.standalone
        maya.standalone.initialize(name='python')
        import maya.cmds as cmds
        out['context'] = 'mayapy standalone'

    _add_framework_paths(cmds.about(version=True).split()[0])
    _sys.path.append(_os.path.join(PLUGIN_ROOT, 'samples'))

    import build_sample
    check('the sample module imports', callable(build_sample.build))

    made = build_sample.build()
    out['groups'] = list(made)
    check('it builds both setups',
          cmds.objExists('setup1_aim_to_colour') and
          cmds.objExists('setup2_angle_to_shapes'), str(made))

    # --- aim vector to colour --------------------------------------------------- #
    def colour():
        return [round(cmds.getAttr('colour_lambert.color{}'.format(c)), 4)
                for c in 'RGB']

    cmds.setAttr('colour_control.rotate', 0, 0, 0)
    red = colour()
    cmds.setAttr('colour_control.rotate', 0, 0, 90)
    green = colour()
    cmds.setAttr('colour_control.rotate', 0, -90, 0)
    blue = colour()
    out['colours'] = {'x': red, 'y': green, 'z': blue}

    check('pointing down +X gives red',
          red[0] > 0.9 and red[1] < 0.1 and red[2] < 0.1, str(red))
    check('pointing down +Y gives green',
          green[1] > 0.9 and green[0] < 0.1 and green[2] < 0.1, str(green))
    check('pointing down +Z gives blue',
          blue[2] > 0.9 and blue[0] < 0.1 and blue[1] < 0.1, str(blue))

    cmds.setAttr('colour_control.rotate', 0, 0, 45)
    between = colour()
    out['colour_between'] = between
    check('halfway between two poses blends rather than snapping',
          between[0] > 0.05 and between[1] > 0.05, str(between))
    check('and weights_sum_to_one keeps it in range',
          abs(sum(between) - 1.0) < 1e-3, 'sums to {}'.format(sum(between)))

    # --- angle to blendshape weights ---------------------------------------------- #
    def weights():
        return [round(cmds.getAttr('shape_blend.weight[{}]'.format(i)), 4)
                for i in range(2)]

    cmds.setAttr('shape_control.rotateZ', -90.0)
    back = weights()
    cmds.setAttr('shape_control.rotateZ', 0.0)
    rest = weights()
    cmds.setAttr('shape_control.rotateZ', 90.0)
    forward = weights()
    out['weights'] = {'back': back, 'rest': rest, 'forward': forward}

    check('rotated back drives the first shape only',
          back[0] > 0.9 and back[1] < 0.1, str(back))
    check('at rest neither shape is on',
          abs(rest[0]) < 0.05 and abs(rest[1]) < 0.05, str(rest))
    check('rotated forward drives the second shape only',
          forward[1] > 0.9 and forward[0] < 0.1, str(forward))

    # One key driving two weights at once is the thing a plain driven key cannot
    # do without a curve each - worth asserting it really is one solver.
    solvers = [str(s) for s in cmds.ls(type='mcaRBFSolver')]
    out['solvers'] = solvers
    check('the sample made exactly two solvers', len(solvers) == 2, str(solvers))
    check('and the blendshape weights come from one of them',
          len(set(cmds.listConnections('shape_blend.weight[0]', source=True) or []) &
              set(cmds.listConnections('shape_blend.weight[1]', source=True) or [])) == 1)

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
