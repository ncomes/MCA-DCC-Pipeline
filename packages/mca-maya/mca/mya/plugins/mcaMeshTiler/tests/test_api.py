"""Exercise meshtiler_api - the layer, not the node.

The node itself is covered by tilersmoke.py, which talks to it directly. This
suite is about the Python around it: does it build the right graph, does it hand
back the ok/result/message contract on the bad paths as well as the good ones,
and does removal leave the scene as it was found.

Runs either under mayapy or pasted into an open Maya, because a suite that can
only run one way is a suite that stops being run. Everything it creates is
deleted on the way out.

One thing worth knowing before adding to it: `tile_mesh` is wrapped in `_safe`,
so a failure comes back as `{'ok': False}` rather than raising. A check written
as `api.tile_mesh(...)` with no look at `['ok']` passes no matter what happens.
Every call here reads `ok`.
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
import json, os, sys, traceback


RESULT = _result_path('mcaMeshTiler_api.json')

out = {'checks': [], 'failures': []}
MADE = []


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


def contract(label, response):
    """Every public call has to answer in the same shape, success or not."""
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

    # The framework AND its bundled dependencies: importing mca.common pulls in
    # yaml, which lives in the python<version> bundle rather than beside the
    # packages. Adding only the packages gets you a ModuleNotFoundError three
    # imports deep.
    _add_framework_paths(cmds.about(version=True).split()[0])

    from mca.mya.tools.meshtiler import meshtiler_api as api
    check('the api module imports', True)

    available, reason = api.plugin_is_available()
    check('the loader finds and loads the plug-in', available, reason)
    if not available:
        raise RuntimeError(reason)

    before = set(cmds.ls())

    # --- the ordinary path ---------------------------------------------------- #
    tile = cmds.polyPlane(w=1, h=1, sx=1, sy=1, ch=False)[0]
    target = cmds.polyCube(sx=2, sy=2, sz=2, ch=False)[0]
    MADE += [tile, target]

    shader = cmds.shadingNode('lambert', asShader=True)
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True)
    cmds.connectAttr(shader + '.outColor', engine + '.surfaceShader')
    cmds.sets(tile, edit=True, forceElement=engine)
    MADE += [shader, engine]

    built = contract('tile_mesh', api.tile_mesh(tile, target, name='test_tiled'))
    check('tile_mesh succeeds on a quad target', built['ok'], built['message'])
    result = built['result'] or {}
    check('it hands back the tiler, the transform and the shape',
          set(result) == {'tiler', 'transform', 'shape'}, 'got {}'.format(sorted(result)))

    tiler, transform, shape = result['tiler'], result['transform'], result['shape']
    MADE.append(str(transform))
    target_faces = cmds.polyEvaluate(target, face=True)
    out_faces = cmds.polyEvaluate(str(shape), face=True)
    out['quad'] = {'target_faces': target_faces, 'out_faces': out_faces,
                   'message': built['message']}
    check('one tile per face on an all-quad target', out_faces == target_faces,
          '{} faces from {}'.format(out_faces, target_faces))
    check('the message says how many tiles came out',
          str(target_faces) in built['message'], built['message'])

    check('the UVs came across',
          cmds.polyEvaluate(str(shape), uvcoord=True) ==
          cmds.polyEvaluate(tile, uvcoord=True) * target_faces)

    assigned = cmds.listConnections(str(shape), type='shadingEngine') or []
    check('the tile\'s shader came across too, so it is not default grey',
          engine in assigned, 'assigned to {}'.format(assigned))

    # The result has to behave like an ordinary object. The first version of this
    # always connected worldToOutput, which conforms the tiles back into the
    # output transform's own space - so the solve cancelled out every move and the
    # tiled mesh silently could not be moved, parented or constrained. The check
    # below was written the wrong way round and PASSED on that, which is how it
    # shipped: it asserted the tiles stayed put, and called that correct.
    flat = cmds.xform(str(shape) + '.vtx[*]', q=True, ws=True, t=True)
    cmds.setAttr(str(transform) + '.translateY', 10.0)
    cmds.dgeval(str(shape) + '.outMesh')
    moved = cmds.xform(str(shape) + '.vtx[*]', q=True, ws=True, t=True)
    lift = min(b - a for a, b in zip(flat[1::3], moved[1::3]))
    sideways = max(abs(a - b) for a, b in
                   zip(flat[0::3] + flat[2::3], moved[0::3] + moved[2::3]))
    out['quad']['lift_on_moving_the_output'] = round(lift, 6)
    check('moving the output transform moves the tiles with it',
          abs(lift - 10.0) < 1e-6, 'moved {} instead of 10'.format(lift))
    check('and only in the direction it was moved', sideways < 1e-6,
          'drifted {} sideways'.format(sideways))
    cmds.setAttr(str(transform) + '.translateY', 0.0)
    cmds.dgeval(str(shape) + '.outMesh')

    # ...and pin_to_target has to still do the old thing, on purpose this time.
    pinned = contract('tile_mesh(pinned)',
                      api.tile_mesh(tile, target, name='pinned_tiled', pin_to_target=True))
    check('pin_to_target builds', pinned['ok'], pinned['message'])
    if pinned['ok']:
        pinned_transform = pinned['result']['transform']
        pinned_shape = pinned['result']['shape']
        MADE.append(str(pinned_transform))
        before_move = cmds.xform(str(pinned_shape) + '.vtx[*]', q=True, ws=True, t=True)
        cmds.setAttr(str(pinned_transform) + '.translateY', 10.0)
        cmds.dgeval(str(pinned_shape) + '.outMesh')
        after_move = cmds.xform(str(pinned_shape) + '.vtx[*]', q=True, ws=True, t=True)
        pinned_drift = max(abs(a - b) for a, b in zip(before_move, after_move))
        out['quad']['pinned_drift'] = round(pinned_drift, 9)
        check('pinned tiles stay welded to the target when the output is moved',
              pinned_drift < 1e-6, 'drifted {}'.format(pinned_drift))

    # --- face rotation --------------------------------------------------------- #
    rest = cmds.xform(str(shape) + '.vtx[*]', q=True, ws=True, t=True)
    rotated = contract('set_face_rotation', api.set_face_rotation(tiler, {0: 1, 3: 2}))
    check('set_face_rotation succeeds', rotated['ok'], rotated['message'])
    cmds.dgeval(str(shape) + '.outMesh')
    turned = cmds.xform(str(shape) + '.vtx[*]', q=True, ws=True, t=True)
    check('rotating a face actually turns its tile',
          max(abs(a - b) for a, b in zip(rest, turned)) > 1e-6)

    cleared = contract('clear_face_rotations', api.clear_face_rotations(tiler))
    check('clear_face_rotations succeeds', cleared['ok'], cleared['message'])
    cmds.dgeval(str(shape) + '.outMesh')
    back = cmds.xform(str(shape) + '.vtx[*]', q=True, ws=True, t=True)
    restored = max(abs(a - b) for a, b in zip(rest, back))
    out['quad']['restored_after_clearing'] = round(restored, 9)
    check('clearing puts every tile back exactly where it was', restored < 1e-9,
          'off by {}'.format(restored))

    cmds.select(clear=True)
    nothing = contract('rotate_selected_faces', api.rotate_selected_faces(tiler))
    check('rotating with nothing selected fails rather than doing nothing quietly',
          not nothing['ok'] and 'select' in nothing['message'].lower(),
          nothing['message'])

    # --- the bad paths ---------------------------------------------------------- #
    same = contract('tile_mesh(same mesh)', api.tile_mesh(target, target))
    check('tiling a mesh across itself is refused', not same['ok'], same['message'])

    bad_axis = contract('tile_mesh(bad axis)', api.tile_mesh(tile, target, up_axis='banana'))
    check('a bad up_axis is refused', not bad_axis['ok'], bad_axis['message'])
    check('and the message says what the choices are',
          all(axis in bad_axis['message'] for axis in ('x', 'y', 'z')),
          bad_axis['message'])

    indexed = contract('tile_mesh(axis by index)',
                       api.tile_mesh(tile, target, name='indexed_tiled', up_axis=2))
    check('an axis given as an index still works', indexed['ok'], indexed['message'])
    if indexed['ok']:
        check('and it is the axis that was asked for',
              indexed['result']['tiler'].attr('tileUpAxis').get() == 2)
        MADE.append(str(indexed['result']['transform']))

    empty = cmds.createNode('transform')
    MADE.append(empty)
    no_mesh = contract('tile_mesh(no mesh)', api.tile_mesh(empty, target))
    check('a transform with no mesh under it is refused', not no_mesh['ok'],
          no_mesh['message'])

    # --- a non-quad target ------------------------------------------------------- #
    tris = cmds.polySphere(sx=6, sy=6, ch=False)[0]
    cmds.polyTriangulate(tris, ch=False)
    MADE.append(tris)
    tri_built = contract('tile_mesh(triangulated)',
                         api.tile_mesh(tile, tris, name='tris_tiled'))
    check('a triangulated target tiles rather than coming out empty', tri_built['ok'],
          tri_built['message'])
    if tri_built['ok']:
        MADE.append(str(tri_built['result']['transform']))
        tri_faces = cmds.polyEvaluate(tris, face=True)
        tri_out = cmds.polyEvaluate(str(tri_built['result']['shape']), face=True)
        out['triangulated'] = {'target_faces': tri_faces, 'out_faces': tri_out,
                               'message': tri_built['message']}
        check('a triangle yields three tiles', tri_out == tri_faces * 3,
              '{} from {}'.format(tri_out, tri_faces))
        # The original dropped non-quads silently. Saying so is the fix.
        check('and the message says the target was not all quads',
              'quad' in tri_built['message'].lower(), tri_built['message'])

    refused = contract('tile_mesh(refineNonQuads off)',
                       api.tile_mesh(tile, tris, name='refused_tiled',
                                     refine_non_quads=False))
    out['refine_off'] = {'ok': refused['ok'], 'message': refused['message']}
    if refused['ok']:
        MADE.append(str(refused['result']['transform']))
    # An empty result reported as a success is the original's exact failure mode:
    # nothing came out, nothing was said, and you went looking for the mistake in
    # your own scene. This is the check that catches it coming back.
    check('refineNonQuads off on a non-quad target is refused, not silently empty',
          not refused['ok'], refused['message'])
    check('and the message says which setting to change',
          'refine_non_quads' in refused['message'], refused['message'])
    check('and it leaves no half-built graph behind',
          not cmds.objExists('refused_tiled'))

    # --- find, freeze, remove ------------------------------------------------------ #
    found = [str(node) for node in api.find_tilers()]
    check('find_tilers finds what was built', str(tiler) in found,
          'found {}'.format(found))

    frozen = contract('freeze_tiling', api.freeze_tiling(transform))
    check('freeze_tiling succeeds', frozen['ok'], frozen['message'])
    check('freezing leaves the geometry behind',
          cmds.polyEvaluate(str(transform), face=True) == out_faces)
    check('and takes the tiler with it', not cmds.objExists(str(tiler)))

    # Removal has to leave the scene as it was found. Everything else in this
    # suite can be tidied up afterwards; this one is the point.
    tidy = cmds.polyCube(ch=False)[0]
    MADE.append(tidy)
    snapshot = set(cmds.ls())
    removable = api.tile_mesh(tile, tidy, name='removable_tiled')
    check('a tiler to remove was built', removable['ok'], removable['message'])
    removed = contract('remove_tiling', api.remove_tiling(removable['result']['transform']))
    check('remove_tiling succeeds', removed['ok'], removed['message'])
    leftovers = sorted(set(cmds.ls()) - snapshot)
    out['leftovers'] = leftovers
    check('removal leaves the scene exactly as it was found', not leftovers,
          'left behind {}'.format(leftovers))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False

try:
    import maya.cmds as cmds
    for node in MADE:
        if cmds.objExists(node):
            try:
                cmds.delete(node)
            except Exception:
                pass
except Exception:
    pass

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
