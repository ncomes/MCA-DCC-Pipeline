"""Exercise rbfsolver_api - the layer, not the node.

The node is covered by test_node.py and the maths by test_rbf.cpp. This is about
the Python: does it build the right graph, does it answer with the
ok/result/message contract on the bad paths as well as the good ones.

`_safe` turns a failure into `{'ok': False}` rather than raising, so a check
written without looking at `ok` passes no matter what happens. Every call here
reads it.
"""

import os as _os
import sys as _sys
import tempfile as _tempfile

PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PACKAGES = _os.path.abspath(_os.path.join(PLUGIN_ROOT, *([_os.pardir] * 5)))


def _result_path(name):
    return _os.path.join(_tempfile.gettempdir(), name)


def _add_framework_paths(version):
    """The framework AND its bundled dependencies.

    The bundles are APPENDED, never inserted: the python311 bundle carries its
    own PySide6 that does not import under mayapy, and mca.common.pyqt.pygui
    swallows the ImportError and hands back a stub.
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


import json, traceback

RESULT = _result_path('mcaRBFSolver_api.json')
out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


def contract(label, response):
    """Every public call answers in the same shape, success or not."""
    ok = (isinstance(response, dict) and set(response) == {'ok', 'result', 'message'}
          and isinstance(response['ok'], bool) and isinstance(response['message'], str))
    check('{} answers with the ok/result/message contract'.format(label), ok,
          'got {!r}'.format(response))
    return response


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

    from mca.mya.tools.rbfsolver import rbfsolver_api as api
    check('the api module imports', True)

    available, reason = api.plugin_is_available()
    check('the loader finds and loads the plug-in', available, reason)
    if not available:
        raise RuntimeError(reason)

    before = set(cmds.ls())

    # --- the ordinary path ---------------------------------------------------- #
    built = contract('create_solver', api.create_solver(name='test_rbf', kernel='gaussian'))
    check('create_solver succeeds', built['ok'], built['message'])
    solver = built['result']

    driver = cmds.createNode('transform', name='test_driver')
    target = cmds.createNode('transform', name='test_target')

    wired = contract('connect_input', api.connect_input(
        solver, ['{}.translateX'.format(driver), '{}.translateY'.format(driver)]))
    check('connect_input succeeds', wired['ok'], wired['message'])
    check('and the key really is connected',
          bool(cmds.listConnections('{}.nInput[0]'.format(solver), source=True)))

    out_wired = contract('connect_output', api.connect_output(
        solver, ['{}.scaleX'.format(target), '{}.scaleY'.format(target)]))
    check('connect_output succeeds', out_wired['ok'], out_wired['message'])
    check('and the value really is connected',
          bool(cmds.listConnections('{}.scaleX'.format(target), source=True)))

    # --- poses ------------------------------------------------------------------ #
    cmds.setAttr(driver + '.translateX', 0.0)
    cmds.setAttr(driver + '.translateY', 0.0)
    first = contract('add_pose', api.add_pose(solver, value=[1.0, 1.0]))
    check('add_pose reads the key off the live input', first['ok'], first['message'])
    check('and reports the index it used', first['result'] == 0, str(first['result']))

    cmds.setAttr(driver + '.translateX', 10.0)
    second = contract('add_pose(second)', api.add_pose(solver, value=[2.0, 0.5]))
    check('a second pose lands at the next index', second['result'] == 1,
          str(second['result']))

    listed = contract('list_poses', api.list_poses(solver))
    check('list_poses returns both', len(listed['result']) == 2, listed['message'])
    check('with the keys it recorded',
          listed['result'][0]['key'] == [0.0, 0.0] and
          listed['result'][1]['key'] == [10.0, 0.0],
          str([row['key'] for row in listed['result']]))

    # The whole point: driving the input should move the output.
    cmds.setAttr(driver + '.translateX', 0.0)
    at_first = cmds.getAttr(target + '.scaleX')
    cmds.setAttr(driver + '.translateX', 10.0)
    at_second = cmds.getAttr(target + '.scaleX')
    out['driven'] = [round(at_first, 5), round(at_second, 5)]
    check('the solver passes through the first pose', abs(at_first - 1.0) < 1e-4,
          str(at_first))
    check('and the second', abs(at_second - 2.0) < 1e-4, str(at_second))

    disabled = contract('set_pose_enabled', api.set_pose_enabled(solver, 1, False))
    check('set_pose_enabled succeeds', disabled['ok'], disabled['message'])
    check('and turning a pose off changes the result',
          abs(cmds.getAttr(target + '.scaleX') - at_second) > 1e-6)
    api.set_pose_enabled(solver, 1, True)

    removed = contract('remove_pose', api.remove_pose(solver, 1))
    check('remove_pose succeeds', removed['ok'], removed['message'])
    check('and it is gone from the list',
          len(api.list_poses(solver)['result']) == 1)

    # --- the bad paths ------------------------------------------------------------ #
    no_value = contract('add_pose(no value)', api.add_pose(solver))
    check('a pose with no value is refused', not no_value['ok'], no_value['message'])
    check('and the message says why',
          'value' in no_value['message'].lower(), no_value['message'])

    bare = api.create_solver(name='bare_rbf')['result']
    no_key = contract('add_pose(nothing connected)', api.add_pose(bare, value=[1.0]))
    check('a pose with no key and nothing connected is refused', not no_key['ok'],
          no_key['message'])

    bad_kernel = contract('create_solver(bad kernel)',
                          api.create_solver(kernel='banana'))
    check('a bad kernel is refused', not bad_kernel['ok'], bad_kernel['message'])
    check('and the message lists the choices',
          'gaussian' in bad_kernel['message'], bad_kernel['message'])

    missing = contract('remove_pose(missing)', api.remove_pose(solver, 99))
    check('removing a pose that is not there is refused', not missing['ok'],
          missing['message'])

    found = [str(node) for node in api.find_solvers()]
    check('find_solvers finds what was built', str(solver) in found, str(found))

    gone = contract('remove_solver', api.remove_solver(solver))
    check('remove_solver succeeds', gone['ok'], gone['message'])
    check('and the target survives it', cmds.objExists(target))

    for node in (target, driver, 'bare_rbf'):
        if cmds.objExists(node):
            cmds.delete(node)
    leftovers = sorted(n for n in (set(cmds.ls()) - before) if cmds.objExists(n))
    out['leftovers'] = leftovers
    check('the scene is left as it was found', not leftovers, str(leftovers))

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
