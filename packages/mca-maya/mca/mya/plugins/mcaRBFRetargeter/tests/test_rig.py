"""Run the whole workflow against a REAL rig, not a cube.

Every other suite here builds its own geometry, which means every other suite
tests a mesh with no history, no namespace, one material and no UV set worth the
name. A production mesh is none of those things: it is skinned, it sits under a
skinCluster and a tweak, its material is a real shading group and its UV set is
called something like "DiffuseUV".

This suite is the only one that touches an actual asset, so it is the only one
that can catch a rig-shaped assumption. It **skips cleanly when the asset is not
there**, because the asset is studio content and will not exist in an open-source
checkout - a suite that fails on a clean clone teaches people to ignore failures.

Point it somewhere else with MCA_RIG_TEST_SCENE.
"""

import json
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
PACKAGES = os.path.abspath(os.path.join(PLUGIN_ROOT, *([os.pardir] * 5)))

#: The rig to test against. There is no default: a path to somebody's own
#: checkout is no use to anyone else, and the run skips cleanly without one.
SCENE = os.environ.get('MCA_RIG_TEST_SCENE', '')
#: A skinned mesh in that scene, and something of DIFFERENT topology sitting on
#: it. The garment is the point: a body and its costume never share topology.
BODY = os.environ.get('MCA_RIG_TEST_BODY', 'Female_Body')
GARMENT = os.environ.get('MCA_RIG_TEST_GARMENT', 'SM_ZipperBunny_Costume')

RESULT = os.path.join(tempfile.gettempdir(), 'mcaRBFRetargeter_rig.json')
out = {'checks': [], 'failures': [], 'scene': SCENE}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


def _add_framework_paths(version):
    for package in ('mca-common', 'mca-maya'):
        path = os.path.join(PACKAGES, package)
        if path not in sys.path:
            sys.path.insert(0, path)
    for bundle in (os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                'dependencies', str(version)),
                   os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                'dependencies',
                                'python{}{}'.format(*sys.version_info[:2])),
                   os.path.join(PACKAGES, 'dependancies')):
        if os.path.isdir(bundle) and bundle not in sys.path:
            sys.path.append(bundle)


if not os.path.isfile(SCENE):
    out['skipped'] = 'No rig at {}. Set MCA_RIG_TEST_SCENE to run this.'.format(SCENE)
    out['ok'] = True
    out['passed'] = out['total'] = 0
    with open(RESULT, 'w') as handle:
        json.dump(out, handle, indent=1)
    print('skipped: no rig scene available')
    print('  details: {}'.format(RESULT))
    sys.exit(0)

try:
    import maya.standalone
    maya.standalone.initialize(name='python')
    import maya.cmds as cmds
    import maya.api.OpenMaya as om

    _add_framework_paths(cmds.about(version=True).split()[0])
    cmds.file(SCENE, open=True, force=True, ignoreVersion=True, prompt=False)

    from mca.mya.tools.rbfretargeter import rbfretargeter_api as api

    def shape_of(node):
        found = cmds.listRelatives(node, shapes=True, ni=True, type='mesh') or []
        return found[0] if found else None

    check('the body mesh is in the scene', bool(shape_of(BODY)), BODY)
    check('the garment is too', bool(shape_of(GARMENT)), GARMENT)
    if not (shape_of(BODY) and shape_of(GARMENT)):
        raise RuntimeError('The named meshes are not in this scene.')

    history = [cmds.nodeType(n) for n in (cmds.listHistory(shape_of(BODY)) or [])]
    out['source_history'] = history[:8]
    # The whole reason this suite exists. A cube has none of this.
    check('the source is skinned, with live history above it',
          'skinCluster' in history, str(history[:8]))

    counts = {'body': cmds.polyEvaluate(shape_of(BODY), vertex=True),
              'garment': cmds.polyEvaluate(shape_of(GARMENT), vertex=True)}
    out['counts'] = counts
    check('the garment does NOT share the body\'s topology, which is the real case',
          counts['garment'] != counts['body'], str(counts))

    # A body variant. History stripped, so it is a plain target like a real one.
    variant = cmds.duplicate(BODY, name='rig_test_variant')[0]
    cmds.delete(variant, constructionHistory=True)
    cmds.scale(1.18, 1.0, 1.22, variant + '.vtx[*]', objectSpace=True, relative=True)

    picked = api.suggest_solver_vertices(BODY, count=400, target=variant, select=False)
    check('auto-pick runs on a skinned mesh', picked['ok'], picked['message'])

    cmds.select(clear=True)
    done = api.retarget_shapes(BODY, variant, [GARMENT],
                               solver_vertices=picked['result'], max_solver_points=0)
    check('the transfer succeeds against a rig', done['ok'], done['message'])
    out['message'] = done.get('message')

    if done['ok']:
        made = done['result'][0].name()
        made_shape = shape_of(made)
        out['made'] = made

        check('the result keeps the garment\'s vertex count',
              cmds.polyEvaluate(made_shape, vertex=True) == counts['garment'])

        original_engines = sorted(set(
            cmds.listConnections(shape_of(GARMENT), type='shadingEngine') or []))
        new_engines = sorted(set(
            cmds.listConnections(made_shape, type='shadingEngine') or []))
        out['shading'] = {'original': original_engines, 'new': new_engines}
        check('a real shading group comes across', new_engines == original_engines,
              '{} vs {}'.format(new_engines, original_engines))

        original_uvs = cmds.polyUVSet(shape_of(GARMENT), q=True, allUVSets=True)
        new_uvs = cmds.polyUVSet(made_shape, q=True, allUVSets=True)
        out['uv_sets'] = {'original': original_uvs, 'new': new_uvs}
        # A production UV set is not called "map1".
        check('and a real UV set, whatever it is called', new_uvs == original_uvs,
              '{} vs {}'.format(new_uvs, original_uvs))

        made_history = [cmds.nodeType(n) for n in (cmds.listHistory(made_shape) or [])]
        out['result_history'] = made_history[:6]
        # Copying from a skinned shape must not drag the deformer along, or the
        # result is driven by the original's joints.
        check('and the result carries no deformer history from the skinned source',
              'skinCluster' not in made_history and 'tweak' not in made_history,
              str(made_history[:6]))

        def points(shape):
            selection = om.MSelectionList()
            selection.add(shape)
            return [(p.x, p.y, p.z) for p in
                    om.MFnMesh(selection.getDagPath(0)).getPoints(om.MSpace.kObject)]

        before, after = points(shape_of(GARMENT)), points(made_shape)
        moved = max(max(abs(a - b) for a, b in zip(p, q))
                    for p, q in zip(before, after))
        out['garment_moved_by'] = moved
        check('and the garment is actually reshaped, not merely copied', moved > 0.1,
              str(moved))

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
