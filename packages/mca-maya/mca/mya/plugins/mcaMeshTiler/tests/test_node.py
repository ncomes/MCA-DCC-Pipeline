"""Smoke test mcaMeshTiler headless, so an untested .mll cannot take a scene with it."""

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

# Version comes from the interpreter, so this can be pointed at whichever Maya is
# free. The 2025 binary cannot be relinked while an open Maya holds it loaded.
import maya.standalone as _standalone  # noqa: E402  (needed before cmds)
_standalone.initialize(name='python')
import maya.cmds as _cmds  # noqa: E402
_VERSION = _cmds.about(version=True).split()[0]
MLL = _plugin_binary(_VERSION)
RESULT = _result_path('mcaMeshTiler_node.json')

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


out['version'] = _VERSION
out['mll'] = MLL

try:
    import maya.cmds as cmds

    cmds.loadPlugin(MLL)
    check('the plug-in loads', cmds.pluginInfo(MLL, q=True, loaded=True))
    check('the node type registers', 'mcaMeshTiler' in (cmds.allNodeTypes() or []))

    def build(target_maker, label):
        """Wire a tile and a target into a tiler and return the output mesh."""
        tile = cmds.polyPlane(w=1, h=1, sx=1, sy=1, ch=False)[0]
        target = target_maker()
        tiler = cmds.createNode('mcaMeshTiler')
        out_transform = cmds.createNode('transform', name='tiled_' + label)
        out_mesh = cmds.createNode('mesh', parent=out_transform)

        cmds.connectAttr(tile + '.outMesh', tiler + '.tileMesh')
        cmds.connectAttr(target + '.outMesh', tiler + '.targetMesh')
        cmds.connectAttr(tiler + '.outMesh', out_mesh + '.inMesh')
        return tile, target, tiler, out_mesh

    # --- a quad target -------------------------------------------------------- #
    tile, target, tiler, out_mesh = build(
        lambda: cmds.polyCube(sx=1, sy=1, sz=1, ch=False)[0], 'cube')

    faces = cmds.polyEvaluate(target, face=True)
    tile_faces = cmds.polyEvaluate(tile, face=True)
    tile_verts = cmds.polyEvaluate(tile, vertex=True)
    out['cube'] = {'target_faces': faces, 'tile_faces': tile_faces,
                   'tile_vertices': tile_verts}

    cmds.dgeval(out_mesh + '.outMesh')
    out_faces = cmds.polyEvaluate(out_mesh, face=True)
    out_verts = cmds.polyEvaluate(out_mesh, vertex=True)
    out['cube']['out_faces'] = out_faces
    out['cube']['out_vertices'] = out_verts

    check('a quad target produces one tile per face',
          out_faces == faces * tile_faces,
          '{} faces, expected {}'.format(out_faces, faces * tile_faces))
    check('vertex count matches the tiles',
          out_verts == faces * tile_verts,
          '{} vertices, expected {}'.format(out_verts, faces * tile_verts))

    points = cmds.xform(out_mesh + '.vtx[*]', q=True, ws=True, t=True)
    check('the output has real positions', any(abs(v) > 1e-9 for v in points))
    check('no NaNs in the output', all(v == v for v in points))

    # Height should push tiles off the surface.
    flat = cmds.xform(out_mesh + '.vtx[*]', q=True, ws=True, t=True)
    cmds.setAttr(tiler + '.heightOffset', 0.5)
    cmds.dgeval(out_mesh + '.outMesh')
    lifted = cmds.xform(out_mesh + '.vtx[*]', q=True, ws=True, t=True)
    # Distance, not per-axis difference. A cube corner's normal points along
    # (1,1,1)/sqrt(3), so moving 0.5 along it is only 0.289 on each axis - which
    # is what this check first measured, and it made a correct result look wrong.
    def distances(a, b):
        return [math.sqrt(sum((a[i + k] - b[i + k]) ** 2 for k in range(3)))
                for i in range(0, len(a), 3)]

    steps = distances(flat, lifted)
    moved = max(steps)
    closest = min(steps)
    out['cube']['height_offset_moved'] = round(moved, 4)
    out['cube']['height_offset_min'] = round(closest, 4)
    check('heightOffset lifts every tile by the offset', abs(moved - 0.5) < 1e-3,
          'furthest moved {}'.format(moved))
    check('it lifts them all by the same amount, whatever the curvature',
          abs(moved - closest) < 1e-3,
          'ranged {} to {}'.format(closest, moved))
    cmds.setAttr(tiler + '.heightOffset', 0.0)

    # --- UVs ------------------------------------------------------------------- #
    #
    # The tool this replaces copied no UVs at all: every tile came out unmapped
    # and you re-projected a few thousand of them by hand.
    tile_uvs = cmds.polyEvaluate(tile, uvcoord=True)
    out_uvs = cmds.polyEvaluate(out_mesh, uvcoord=True)
    out['cube']['tile_uvs'] = tile_uvs
    out['cube']['out_uvs'] = out_uvs
    check('the tile\'s UVs are stamped onto every tile',
          out_uvs == tile_uvs * faces,
          '{} UVs, expected {}'.format(out_uvs, tile_uvs * faces))
    check('the tile\'s UV set name survives',
          'map1' in (cmds.polyUVSet(out_mesh, q=True, allUVSets=True) or []),
          'sets: {}'.format(cmds.polyUVSet(out_mesh, q=True, allUVSets=True)))

    # Every tile lands on the same patch of texture - that is the whole point of
    # one scale texture and ten thousand scales.
    first = cmds.polyEditUV(out_mesh + '.map[0:{}]'.format(tile_uvs - 1), q=True)
    last_start = (faces - 1) * tile_uvs
    last = cmds.polyEditUV(
        out_mesh + '.map[{}:{}]'.format(last_start, last_start + tile_uvs - 1), q=True)
    check('every tile lands on the same patch of texture',
          all(abs(a - b) < 1e-6 for a, b in zip(first, last)),
          '{} vs {}'.format(first, last))

    # A second UV set on the tile should come across too, and toggling copyUVs
    # off should take them all away again without touching the geometry.
    cmds.polyUVSet(tile, create=True, uvSet='secondary')
    cmds.polyUVSet(tile, currentUVSet=True, uvSet='secondary')
    cmds.polyProjection(tile + '.f[*]', type='planar', md='y', ch=False)
    cmds.polyUVSet(tile, currentUVSet=True, uvSet='map1')
    cmds.dgeval(out_mesh + '.outMesh')
    sets = cmds.polyUVSet(out_mesh, q=True, allUVSets=True) or []
    out['cube']['out_uv_sets'] = sets
    check('a second UV set comes across as well', 'secondary' in sets,
          'sets: {}'.format(sets))

    cmds.setAttr(tiler + '.copyUVs', False)
    cmds.dgeval(out_mesh + '.outMesh')
    check('turning copyUVs off takes the UVs away',
          (cmds.polyEvaluate(out_mesh, uvcoord=True) or 0) == 0,
          '{} UVs left'.format(cmds.polyEvaluate(out_mesh, uvcoord=True)))
    check('turning copyUVs off leaves the geometry alone',
          cmds.polyEvaluate(out_mesh, face=True) == out['cube']['out_faces'])
    cmds.setAttr(tiler + '.copyUVs', True)
    cmds.dgeval(out_mesh + '.outMesh')
    check('turning it back on brings them back',
          cmds.polyEvaluate(out_mesh, uvcoord=True) == tile_uvs * faces,
          '{} UVs'.format(cmds.polyEvaluate(out_mesh, uvcoord=True)))

    # --- filling a face rather than stretching one tile over it ----------------- #
    #
    # One tile per face is all the tool this replaces could do, so a big face got
    # a big tile and re-meshing the target was the only way to change it.
    for across, down in ((2, 1), (2, 3), (4, 4)):
        cmds.setAttr(tiler + '.tilesU', across)
        cmds.setAttr(tiler + '.tilesV', down)
        cmds.dgeval(out_mesh + '.outMesh')
        expected = faces * tile_faces * across * down
        got = cmds.polyEvaluate(out_mesh, face=True)
        check('a {}x{} grid puts {} tiles on every face'.format(across, down, across * down),
              got == expected, '{} faces, expected {}'.format(got, expected))

    cmds.setAttr(tiler + '.tilesU', 3)
    cmds.setAttr(tiler + '.tilesV', 3)
    cmds.dgeval(out_mesh + '.outMesh')
    filled = cmds.xform(out_mesh + '.vtx[*]', q=True, ws=True, t=True)
    check('the filled tiles have no NaNs', all(v == v for v in filled))

    # The grid must stay inside the face it belongs to. A cube is 2 units across,
    # so nothing may stray outside that.
    check('the tiles stay within the target',
          max(abs(v) for v in filled) <= 1.0 + 1e-6,
          'furthest {}'.format(max(abs(v) for v in filled)))

    # Every cell should be a different place on the surface - if the parameters
    # were not remapped per cell, all nine would land on top of each other.
    tile_starts = set()
    step = tile_verts * 3
    for start in range(0, step * 9, step):
        tile_starts.add(tuple(round(v, 4) for v in filled[start:start + 3]))
    out['cube']['distinct_tile_origins_of_9'] = len(tile_starts)
    check('each cell of the grid lands somewhere different', len(tile_starts) == 9,
          'only {} distinct of 9'.format(len(tile_starts)))

    # UVs have to keep up with the extra tiles.
    check('the UVs follow the grid',
          cmds.polyEvaluate(out_mesh, uvcoord=True) == tile_uvs * faces * 9,
          '{} UVs'.format(cmds.polyEvaluate(out_mesh, uvcoord=True)))

    cmds.setAttr(tiler + '.tilesU', 1)
    cmds.setAttr(tiler + '.tilesV', 1)
    cmds.dgeval(out_mesh + '.outMesh')
    check('going back to 1x1 restores one tile per face',
          cmds.polyEvaluate(out_mesh, face=True) == out['cube']['out_faces'])

    # --- a triangulated target ------------------------------------------------- #
    #
    # The tool this replaces collected faces with exactly four vertices and
    # silently dropped everything else, so this produced an empty mesh and no
    # message.
    def triangulated():
        sphere = cmds.polySphere(sx=6, sy=6, ch=False)[0]
        cmds.polyTriangulate(sphere, ch=False)
        return sphere

    tile2, target2, tiler2, out_mesh2 = build(triangulated, 'tris')
    tri_faces = cmds.polyEvaluate(target2, face=True)
    cmds.dgeval(out_mesh2 + '.outMesh')
    tri_out_faces = cmds.polyEvaluate(out_mesh2, face=True)
    out['triangulated'] = {'target_faces': tri_faces, 'out_faces': tri_out_faces}

    check('a triangulated target still tiles', bool(tri_out_faces) and tri_out_faces > 0,
          'got {}'.format(tri_out_faces))
    # Catmull-Clark makes n quads from an n-gon, so a triangle yields three tiles.
    check('a triangle yields three tiles', tri_out_faces == tri_faces * 3,
          '{} faces from {} triangles'.format(tri_out_faces, tri_faces))

    tri_points = cmds.xform(out_mesh2 + '.vtx[*]', q=True, ws=True, t=True)
    check('the triangulated output has no NaNs', all(v == v for v in tri_points))

    # Filling works on non-quads too, which is the part that would have been
    # awkward in the original: a ptex face is a unit square whatever polygon it
    # came from, so a triangle fills exactly like a quad.
    cmds.setAttr(tiler2 + '.tilesU', 2)
    cmds.setAttr(tiler2 + '.tilesV', 2)
    cmds.dgeval(out_mesh2 + '.outMesh')
    tri_filled = cmds.polyEvaluate(out_mesh2, face=True)
    out['triangulated']['filled_2x2_faces'] = tri_filled
    check('a triangulated target fills as well as a quad one',
          tri_filled == tri_out_faces * 4,
          '{} faces, expected {}'.format(tri_filled, tri_out_faces * 4))
    check('and still has no NaNs',
          all(v == v for v in cmds.xform(out_mesh2 + '.vtx[*]', q=True, ws=True, t=True)))

    # --- an n-gon target -------------------------------------------------------- #
    def ngons():
        cylinder = cmds.polyCylinder(sx=8, sy=1, sz=0, ch=False)[0]
        return cylinder

    tile3, target3, tiler3, out_mesh3 = build(ngons, 'ngon')
    cmds.dgeval(out_mesh3 + '.outMesh')
    ngon_out = cmds.polyEvaluate(out_mesh3, face=True)
    out['ngon'] = {'out_faces': ngon_out}
    check('an n-gon target still tiles', bool(ngon_out) and ngon_out > 0,
          'got {}'.format(ngon_out))

    # --- rebuilding is stable ---------------------------------------------------- #
    for _ in range(3):
        cmds.setAttr(tiler + '.height', 2.0)
        cmds.dgeval(out_mesh + '.outMesh')
        cmds.setAttr(tiler + '.height', 1.0)
        cmds.dgeval(out_mesh + '.outMesh')
    check('repeated evaluation is stable',
          cmds.polyEvaluate(out_mesh, face=True) == out['cube']['out_faces'])

    # Changing topology should rebuild rather than crash or go stale.
    cmds.polySmooth(target, dv=1, ch=False)
    cmds.dgeval(out_mesh + '.outMesh')
    smoothed_faces = cmds.polyEvaluate(target, face=True)
    rebuilt = cmds.polyEvaluate(out_mesh, face=True)
    out['cube']['after_topology_change'] = {'target_faces': smoothed_faces,
                                            'out_faces': rebuilt}
    check('a topology change rebuilds the tiles',
          rebuilt == smoothed_faces * tile_faces,
          '{} faces, expected {}'.format(rebuilt, smoothed_faces * tile_faces))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3000:]
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
