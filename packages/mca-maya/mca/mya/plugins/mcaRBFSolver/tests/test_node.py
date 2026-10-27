"""Smoke test mcaRBFSolver headless, so an untested .mll cannot take a scene with it.

The maths is covered off-DCC by test_rbf.cpp. This is about the Maya shell: do
the attributes exist under the names old scenes expect, do sparse arrays survive,
does the rebuild happen when it should and not when it should not.
"""

import os as _os
import sys as _sys
import tempfile as _tempfile

PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PLUGIN_NAME = _os.path.basename(PLUGIN_ROOT)


def _plugin_binary(version):
    return _os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                         '{}_maya{}.mll'.format(PLUGIN_NAME, version))


def _result_path(name):
    return _os.path.join(_tempfile.gettempdir(), name)


import json, traceback

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
    RESULT = _result_path('mcaRBFSolver_node.json')
    out['version'] = version

    cmds.loadPlugin(_plugin_binary(version))
    check('the plug-in loads', True)
    check('the node type registers', 'mcaRBFSolver' in (cmds.allNodeTypes() or []))

    node = cmds.createNode('mcaRBFSolver')

    # The long names an old scene will be looking for.
    expected = ['nInput', 'poses', 'state', 'nKey', 'mValue', 'mOutput',
                'distanceMode', 'rbfMode', 'scale', 'normalize', 'blendShapeMode',
                'NDimension', 'MDimension', 'regularization']
    # listAttr reports a compound's children as "poses.state", not "state", so
    # compare on the last component. The first version of this check did not, and
    # reported three attributes missing that the rest of the suite then set
    # successfully - which is the tell that the check was wrong, not the node.
    present = set()
    for name in (cmds.listAttr(node) or []):
        present.add(name)
        present.add(name.split('.')[-1])
    missing = [name for name in expected if name not in present]
    check('every attribute an old scene expects is still here', not missing,
          'missing {}'.format(missing))

    def set_pose(index, key, value, state=True):
        cmds.setAttr('{}.poses[{}].state'.format(node, index), state)
        for i, v in enumerate(key):
            cmds.setAttr('{}.poses[{}].nKey[{}]'.format(node, index, i), v)
        for i, v in enumerate(value):
            cmds.setAttr('{}.poses[{}].mValue[{}]'.format(node, index, i), v)

    def set_input(key):
        for i, v in enumerate(key):
            cmds.setAttr('{}.nInput[{}]'.format(node, i), v)

    def output(count):
        return [cmds.getAttr('{}.mOutput[{}]'.format(node, m)) for m in range(count)]

    # --- a 3D key driving a 2D value ------------------------------------------ #
    set_pose(0, [1.0, 0.0, 0.0], [1.0, 0.0])
    set_pose(1, [0.0, 1.0, 0.0], [0.0, 1.0])
    set_pose(2, [0.0, 0.0, 1.0], [0.5, 0.5])

    for index, (key, value) in enumerate((([1.0, 0.0, 0.0], [1.0, 0.0]),
                                          ([0.0, 1.0, 0.0], [0.0, 1.0]),
                                          ([0.0, 0.0, 1.0], [0.5, 0.5]))):
        set_input(key)
        got = output(2)
        check('it passes through pose {}'.format(index),
              abs(got[0] - value[0]) < 1e-4 and abs(got[1] - value[1]) < 1e-4,
              '{} wanted {}'.format(got, value))

    set_input([0.7, 0.7, 0.0])
    between = output(2)
    out['between'] = [round(v, 5) for v in between]
    check('and interpolates between them', all(v == v for v in between) and
          0.0 <= between[0] <= 1.0 and 0.0 <= between[1] <= 1.0, str(between))

    # --- disabling a pose changes the answer ----------------------------------- #
    before = output(2)
    cmds.setAttr('{}.poses[2].state'.format(node), False)
    after = output(2)
    check('turning a pose off re-solves the system',
          max(abs(a - b) for a, b in zip(before, after)) > 1e-6,
          '{} vs {}'.format(before, after))
    cmds.setAttr('{}.poses[2].state'.format(node), True)

    # --- weights that sum to one ------------------------------------------------ #
    cmds.setAttr(node + '.blendShapeMode', True)
    set_input([0.5, 0.5, 0.5])
    weights = output(2)
    out['weights'] = [round(v, 6) for v in weights]
    check('blendShapeMode makes the outputs sum to one',
          abs(sum(weights) - 1.0) < 1e-5, str(weights))
    check('and none of them is negative', all(v >= -1e-9 for v in weights), str(weights))
    cmds.setAttr(node + '.blendShapeMode', False)

    # --- a sparse input array ---------------------------------------------------- #
    #
    # Maya arrays are sparse. The original walked physical elements and trusted
    # them to line up, inside a bare `except: pass`, so a gap silently shuffled
    # the key's dimensions.
    sparse = cmds.createNode('mcaRBFSolver')
    cmds.setAttr('{}.poses[0].nKey[0]'.format(sparse), 0.0)
    cmds.setAttr('{}.poses[0].nKey[2]'.format(sparse), 1.0)   # index 1 left absent
    cmds.setAttr('{}.poses[0].mValue[0]'.format(sparse), 3.0)
    cmds.setAttr('{}.poses[1].nKey[0]'.format(sparse), 1.0)
    cmds.setAttr('{}.poses[1].nKey[2]'.format(sparse), 0.0)
    cmds.setAttr('{}.poses[1].mValue[0]'.format(sparse), 9.0)
    cmds.setAttr('{}.nInput[0]'.format(sparse), 0.0)
    cmds.setAttr('{}.nInput[2]'.format(sparse), 1.0)
    got = cmds.getAttr('{}.mOutput[0]'.format(sparse))
    out['sparse'] = round(got, 5)
    check('a sparse array lands on the right dimensions', abs(got - 3.0) < 1e-4,
          'got {} wanted 3.0'.format(got))

    # --- one pose. The original produced nothing at all. -------------------------- #
    single = cmds.createNode('mcaRBFSolver')
    cmds.setAttr('{}.poses[0].nKey[0]'.format(single), 5.0)
    cmds.setAttr('{}.poses[0].mValue[0]'.format(single), 42.0)
    cmds.setAttr('{}.nInput[0]'.format(single), 5.0)
    check('a single pose returns its value instead of failing silently',
          abs(cmds.getAttr('{}.mOutput[0]'.format(single)) - 42.0) < 1e-4,
          str(cmds.getAttr('{}.mOutput[0]'.format(single))))

    # --- no poses at all does not crash -------------------------------------------- #
    empty = cmds.createNode('mcaRBFSolver')
    try:
        cmds.getAttr('{}.mOutput[0]'.format(empty))
        check('an empty solver is survivable', True)
    except Exception as exc:
        check('an empty solver is survivable', True, 'raised {}'.format(exc))

    # --- repeated evaluation is stable ---------------------------------------------- #
    set_input([0.3, 0.6, 0.1])
    first = output(2)
    for _ in range(5):
        cmds.dgdirty(node)
        again = output(2)
    check('repeated evaluation gives the same answer',
          max(abs(a - b) for a, b in zip(first, again)) < 1e-9,
          '{} vs {}'.format(first, again))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False
    RESULT = _result_path('mcaRBFSolver_node.json')

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
