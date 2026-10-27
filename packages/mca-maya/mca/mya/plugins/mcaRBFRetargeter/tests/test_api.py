"""Exercise rbfretargeter_api - the layer, not the command.

The command is covered by test_command.py and the maths by test_retarget.cpp.
This is about the Python: does it refuse the bad calls before anything has been
created, does it answer with the ok/result/message contract either way, and does
it leave the artist's selection as it found it.

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

RESULT = _result_path('mcaRBFRetargeter_api.json')
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

    from mca.mya.tools.rbfretargeter import rbfretargeter_api as api
    check('the api module imports', True)

    available, reason = api.plugin_is_available()
    check('the loader finds and loads the plug-in', available, reason)
    if not available:
        raise RuntimeError(reason)

    import pymel.core as pm

    OFFSET = 5.0

    def build_scene():
        """Source, a target that is only the source moved, and a shape.

        A cube rather than a plane: a flat solver point set cannot describe
        motion off the flat. test_command.py has the long version.
        """
        cmds.file(new=True, force=True)
        source = cmds.polyCube(name='src', sx=2, sy=2, sz=2, ch=False)[0]
        target = cmds.duplicate(source, name='tgt')[0]
        cmds.move(OFFSET, 0, 0, target + '.vtx[*]', objectSpace=True, relative=True)
        shape = cmds.duplicate(source, name='srcShape')[0]
        cmds.move(0, 3, 0, shape + '.vtx[0]', objectSpace=True, relative=True)
        return source, target, shape

    def points(node):
        flat = cmds.xform(node + '.vtx[*]', query=True, objectSpace=True, translation=True)
        return [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]

    # --- the ordinary path ------------------------------------------------------ #
    source, target, shape = build_scene()
    done = contract('retarget_shapes', api.retarget_shapes(source, target, [shape]))
    check('retarget_shapes succeeds', done['ok'], done['message'])
    check('and hands back one new mesh per shape', len(done['result']) == 1,
          str(done['result']))

    made = done['result'][0]
    before = points(shape)
    after = points(made.name())
    drift = max(max(abs(a[i] - (b[i] + (OFFSET if i == 0 else 0.0))) for i in range(3))
                for a, b in zip(after, before))
    out['drift'] = drift
    check('the transfer is exact on a pure move', drift < 1e-9, str(drift))

    # --- it gives the selection back -------------------------------------------- #
    #
    # The command reads its solver vertices from the selection, so the api has to
    # set one. A tool that eats your selection is a tool people stop using.
    source, target, shape = build_scene()
    cmds.select([source, target])
    kept = cmds.ls(selection=True, long=True)
    api.retarget_shapes(source, target, [shape], solver_vertices=[0, 1, 2, 3, 4, 5, 6, 7])
    check('the selection is put back afterwards',
          cmds.ls(selection=True, long=True) == kept,
          '{} vs {}'.format(cmds.ls(selection=True, long=True), kept))

    # --- the bad paths refuse BEFORE anything is created ------------------------- #
    source, target, shape = build_scene()
    wrong = cmds.polyCube(name='wrongTopology', sx=1, sy=1, sz=1, ch=False)[0]
    existing = set(cmds.ls(type='mesh'))

    for label, call in (
            ('a target with the wrong vertex count',
             lambda: api.retarget_shapes(source, wrong, [shape])),
            ('no shapes at all',
             lambda: api.retarget_shapes(source, target, [])),
            ('a vertex index off the end of the mesh',
             lambda: api.retarget_shapes(source, target, [shape], solver_vertices=[9999])),
            ('more solver points than the guard allows',
             lambda: api.retarget_shapes(source, target, [shape], max_solver_points=4)),
            ('something that is not a mesh',
             lambda: api.retarget_shapes(cmds.createNode('transform'), target, [shape]))):
        response = contract(label, call())
        check('{} is refused'.format(label), not response['ok'], str(response))
        check('and {} leaves the scene as it found it'.format(label),
              set(cmds.ls(type='mesh')) == existing,
              str(set(cmds.ls(type='mesh')) - existing))

    # --- a rider with different topology is carried, not refused ------------------ #
    #
    # The rule reversed: the solve is a function of position, so anything sitting
    # in the source's space comes along whatever its vertex count. Refusing the
    # mismatch broke one garment onto many body variants, which is the main use.
    source, target, shape = build_scene()
    rider = cmds.polySphere(name='rider', sx=6, sy=6, ch=False)[0]
    cmds.scale(0.3, 0.3, 0.3, rider)
    cmds.makeIdentity(rider, apply=True, scale=True)
    rider_count = cmds.polyEvaluate(rider, vertex=True)
    check('the rider has different topology from the source',
          rider_count != cmds.polyEvaluate(source, vertex=True), str(rider_count))

    carried = contract('retarget_shapes with a rider',
                       api.retarget_shapes(source, target, [rider]))
    check('a differently-topologised mesh is carried across', carried['ok'],
          carried['message'])
    check('and keeps its own vertex count',
          carried['ok'] and
          cmds.polyEvaluate(carried['result'][0].name(), vertex=True) == rider_count)

    # --- several targets in one call ----------------------------------------------- #
    #
    # The real job: one garment, one base body, several body variants. Doing it
    # by hand is the same shape list set up N times and then working out which
    # "_retargeted" mesh belongs to which body.
    cmds.file(new=True, force=True)
    base = cmds.polyCube(name='base', sx=2, sy=2, sz=2, ch=False)[0]
    variants = []
    for index, distance in enumerate((6.0, 12.0, 18.0)):
        variant = cmds.duplicate(base, name='variant{}'.format(index))[0]
        cmds.move(distance, 0, 0, variant + '.vtx[*]', objectSpace=True, relative=True)
        variants.append(variant)
    garment = cmds.polySphere(name='garment', sx=6, sy=6, ch=False)[0]
    cmds.scale(0.3, 0.3, 0.3, garment)
    cmds.makeIdentity(garment, apply=True, scale=True)

    cmds.select(clear=True)
    many = contract('retarget_to_many',
                    api.retarget_to_many(base, variants, [garment]))
    check('retarget_to_many succeeds', many['ok'], many['message'])
    check('and makes one result per target',
          many['ok'] and len(many['result']) == 3, str(many.get('result')))

    # Named after both, or a dozen outputs are indistinguishable.
    names = [str(node) for group in (many['result'] or {}).values() for node in group]
    check('and each result is named after the mesh AND the target it went to',
          all(name.startswith('garment_') for name in names) and
          len({name for name in names}) == 3, str(names))
    check('and each one landed on its own variant',
          all(any(v in name for v in ('variant0', 'variant1', 'variant2'))
              for name in names), str(names))

    check('an empty target list is refused',
          not api.retarget_to_many(base, [], [garment])['ok'])

    # --- auto-picking solver vertices ----------------------------------------------- #
    #
    # This is the step every real use starts with: a 16,747-vertex body is 300x
    # over the guard, so someone has to pick a few hundred spread out. The tool
    # was asking for that work without offering it.
    cmds.file(new=True, force=True)
    dense = cmds.polySphere(name='dense', sx=40, sy=40, ch=False)[0]
    total = cmds.polyEvaluate(dense, vertex=True)
    out['dense_vertices'] = total

    picked = contract('suggest_solver_vertices',
                      api.suggest_solver_vertices(dense, count=120, select=False))
    check('suggest_solver_vertices succeeds', picked['ok'], picked['message'])
    chosen = picked['result'] or []
    check('and returns the number asked for', len(chosen) == 120, str(len(chosen)))
    check('with no repeats', len(set(chosen)) == len(chosen))
    check('and every index is on the mesh',
          all(0 <= index < total for index in chosen))

    # The point of farthest-point sampling over a random draw. A random 120 of a
    # sphere's vertices clusters; these should reach every extreme of it.
    flat = cmds.xform(dense + '.vtx[*]', query=True, objectSpace=True, translation=True)
    all_points = [tuple(flat[i:i + 3]) for i in range(0, len(flat), 3)]
    picked_points = [all_points[i] for i in chosen]
    for axis, label in enumerate('xyz'):
        full = max(p[axis] for p in all_points) - min(p[axis] for p in all_points)
        got = (max(p[axis] for p in picked_points) -
               min(p[axis] for p in picked_points))
        check('the picks span the mesh in {}'.format(label), got > full * 0.95,
              '{} of {}'.format(got, full))

    # Four is the minimum that can span three dimensions, which the affine term
    # needs. Fewer is a different answer, not a small mistake.
    check('fewer than four is refused',
          not api.suggest_solver_vertices(dense, count=2)['ok'])

    # Same mesh, same count, same answer - or a result cannot be reproduced.
    again = api.suggest_solver_vertices(dense, count=120, select=False)
    check('the pick is deterministic', again['result'] == chosen)

    # Asking for more than there are is not an error, it is everything.
    everything = api.suggest_solver_vertices(dense, count=total + 50, select=False)
    check('asking for more vertices than exist gives all of them',
          everything['ok'] and len(everything['result']) == total,
          str(everything['message']))

    # And it actually solves the problem it exists for.
    cmds.file(new=True, force=True)
    # Dense enough to actually exceed the guard. The first version of this used
    # sx=40 sy=40, which is 1,562 vertices - comfortably UNDER the 5,000 limit,
    # so the "it is refused to begin with" check was asserting a refusal that
    # never came, and the auto-pick below was solving a problem the scene did not
    # have. The count is asserted against the limit now rather than assumed.
    big = cmds.polySphere(name='big', sx=100, sy=100, ch=False)[0]
    big_count = cmds.polyEvaluate(big, vertex=True)
    out['big_vertices'] = big_count
    check('the test mesh really is over the default guard',
          big_count > api.DEFAULT_MAX_SOLVER_POINTS,
          '{} vs {}'.format(big_count, api.DEFAULT_MAX_SOLVER_POINTS))

    variant = cmds.duplicate(big, name='big_variant')[0]
    cmds.move(4, 0, 0, variant + '.vtx[*]', objectSpace=True, relative=True)
    rider = cmds.polyCube(name='rider', sx=1, sy=1, sz=1, ch=False)[0]
    cmds.select(clear=True)

    refused = api.retarget_shapes(big, variant, [rider])
    check('the dense mesh is over the guard to begin with', not refused['ok'],
          refused['message'])

    suggested = api.suggest_solver_vertices(big, count=200, select=False)
    solved = contract('retarget after auto-pick',
                      api.retarget_shapes(big, variant, [rider],
                                          solver_vertices=suggested['result']))
    check('and auto-picked vertices make it solvable', solved['ok'],
          solved['message'])

    # --- results land on the target when it is moved by its TRANSFORM ------------- #
    #
    # The solve is in object space, as the original's was, so what comes out is
    # the shape change and nothing else. Every check above moves VERTICES, where
    # that distinction never shows. A set of body variants is laid out by their
    # transforms instead - and then every result came back at the original's
    # position, three of them stacked on each other, each correct and none of
    # them possible to look at.
    cmds.file(new=True, force=True)
    base = cmds.polyCube(name='base', sx=2, sy=2, sz=2, ch=False)[0]
    moved = cmds.duplicate(base, name='moved')[0]
    cmds.setAttr(moved + '.translateX', 40)          # the TRANSFORM, not the points
    cmds.scale(1.4, 1.4, 1.4, moved + '.vtx[*]', objectSpace=True, relative=True)
    worn = cmds.polySphere(name='worn', sx=8, sy=8, ch=False)[0]
    cmds.scale(0.3, 0.3, 0.3, worn)
    cmds.makeIdentity(worn, apply=True, scale=True)
    cmds.select(clear=True)

    placed = contract('retarget_shapes with placement',
                      api.retarget_shapes(base, moved, [worn], place_on_target=True))
    check('placement succeeds', placed['ok'], placed['message'])
    if placed['ok']:
        box = cmds.exactWorldBoundingBox(placed['result'][0].name())
        middle = (box[0] + box[3]) / 2.0
        out['placed_centre_x'] = round(middle, 3)
        check('the result lands on the target, not back at the source',
              abs(middle - 40.0) < 2.0, 'centre x is {}'.format(middle))

    left = contract('retarget_shapes without placement',
                    api.retarget_shapes(base, moved, [worn], place_on_target=False))
    if left['ok']:
        box = cmds.exactWorldBoundingBox(left['result'][0].name())
        middle = (box[0] + box[3]) / 2.0
        out['unplaced_centre_x'] = round(middle, 3)
        check('and turning it off leaves it where the shape was',
              abs(middle) < 2.0, 'centre x is {}'.format(middle))

    # Everything on identity is the common case, and placement must be a no-op
    # there or it would move results that were already right.
    cmds.file(new=True, force=True)
    plain = cmds.polyCube(name='plain', sx=2, sy=2, sz=2, ch=False)[0]
    plain_variant = cmds.duplicate(plain, name='plain_variant')[0]
    cmds.move(3, 0, 0, plain_variant + '.vtx[*]', objectSpace=True, relative=True)
    plain_worn = cmds.polyCube(name='plain_worn', sx=1, sy=1, sz=1, ch=False)[0]
    cmds.select(clear=True)
    on = api.retarget_shapes(plain, plain_variant, [plain_worn], place_on_target=True)
    off = api.retarget_shapes(plain, plain_variant, [plain_worn], place_on_target=False)
    check('with identity transforms, placement changes nothing',
          on['ok'] and off['ok'] and
          max(abs(a - b) for a, b in
              zip(cmds.exactWorldBoundingBox(on['result'][0].name()),
                  cmds.exactWorldBoundingBox(off['result'][0].name()))) < 1e-6)

    # --- UVs and shaders on what comes out ------------------------------------------ #
    #
    # The command's results came out assigned to NO shading group at all - not
    # even initialShadingGroup - so a retargeted garment rendered as nothing. UVs
    # were fine, but nothing checked them, which is the same exposure.
    import maya.api.OpenMaya as om

    def uv_data(shape_name):
        sel = om.MSelectionList()
        sel.add(shape_name)
        mesh = om.MFnMesh(sel.getDagPath(0))
        data = {}
        for uv_set in mesh.getUVSetNames():
            u, v = mesh.getUVs(uv_set)
            counts, ids = mesh.getAssignedUVs(uv_set)
            data[uv_set] = (list(u), list(v), list(counts), list(ids))
        return data

    def engines_on(node):
        shape = cmds.listRelatives(node, shapes=True, ni=True, type='mesh')[0]
        return sorted(set(cmds.listConnections(shape, type='shadingEngine') or []))

    cmds.file(new=True, force=True)
    body = cmds.polyCube(name='body', sx=2, sy=2, sz=2, ch=False)[0]
    body_variant = cmds.duplicate(body, name='body_variant')[0]
    cmds.move(4, 0, 0, body_variant + '.vtx[*]', objectSpace=True, relative=True)

    garment = cmds.polySphere(name='garment', sx=8, sy=8, ch=False)[0]
    cmds.scale(0.4, 0.4, 0.4, garment)
    cmds.makeIdentity(garment, apply=True, scale=True)
    # A second UV set, because a mesh that has one is the case that breaks - the
    # mesh tiler lost exactly this and looked fine, because set one rode in on
    # the default map1.
    garment_shape = cmds.listRelatives(garment, shapes=True, ni=True)[0]
    cmds.polyUVSet(garment_shape, create=True, uvSet='secondary')
    cmds.polyUVSet(garment_shape, currentUVSet=True, uvSet='secondary')
    # No uvSetName flag on this command - it works on whatever the CURRENT UV set
    # is, which is why it was switched above.
    cmds.polyPlanarProjection(garment + '.f[*]', md='y', ch=False)
    cmds.polyUVSet(garment_shape, currentUVSet=True, uvSet='map1')

    garment_shader = cmds.shadingNode('lambert', asShader=True, name='garment_mat')
    garment_set = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                            name='garment_matSG')
    cmds.connectAttr(garment_shader + '.outColor', garment_set + '.surfaceShader')
    cmds.sets(garment, edit=True, forceElement=garment_set)

    body_shader = cmds.shadingNode('lambert', asShader=True, name='body_mat')
    body_set = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                         name='body_matSG')
    cmds.connectAttr(body_shader + '.outColor', body_set + '.surfaceShader')
    cmds.sets(body_variant, edit=True, forceElement=body_set)

    cmds.select(clear=True)
    dressed = contract('retarget_shapes with shading',
                       api.retarget_shapes(body, body_variant, [garment]))
    check('it succeeds', dressed['ok'], dressed['message'])

    result = dressed['result'][0].name()
    result_shape = cmds.listRelatives(result, shapes=True, ni=True, type='mesh')[0]

    # --- UVs -------------------------------------------------------------------- #
    before_uv = uv_data(garment_shape)
    after_uv = uv_data(result_shape)
    check('every UV set comes across',
          sorted(after_uv) == sorted(before_uv),
          '{} vs {}'.format(sorted(after_uv), sorted(before_uv)))
    check('including the second one, which is the one that gets lost',
          'secondary' in after_uv, str(sorted(after_uv)))

    worst = 0.0
    identical_mapping = True
    for uv_set, (u, v, counts, ids) in before_uv.items():
        if uv_set not in after_uv:
            identical_mapping = False
            continue
        gu, gv, gcounts, gids = after_uv[uv_set]
        if len(gu) != len(u) or gcounts != counts or gids != ids:
            identical_mapping = False
            continue
        worst = max([worst] + [abs(a - b) for a, b in zip(u, gu)]
                    + [abs(a - b) for a, b in zip(v, gv)])
    out['worst_uv_difference'] = worst
    check('the UV coordinates are unchanged', worst == 0.0, str(worst))
    check('and so is which UV each face-vertex uses', identical_mapping)

    # --- shaders ------------------------------------------------------------------ #
    check('the result is shaded, not left on nothing at all',
          engines_on(result), str(engines_on(result)))
    check('and by default takes the shader of the mesh it was made from',
          engines_on(result) == [garment_set], str(engines_on(result)))

    from_target = api.retarget_shapes(body, body_variant, [garment], shaders='target')
    check('shaders="target" takes the deformed-to mesh\'s instead',
          from_target['ok'] and
          engines_on(from_target['result'][0].name()) == [body_set],
          str(engines_on(from_target['result'][0].name())))

    unassigned = api.retarget_shapes(body, body_variant, [garment], shaders='none')
    check('shaders="none" leaves it alone',
          unassigned['ok'] and not engines_on(unassigned['result'][0].name()))

    check('a shaders value that is not a real choice is refused',
          not api.retarget_shapes(body, body_variant, [garment],
                                  shaders='whatever')['ok'])

    # --- texture-to-UV-set links ------------------------------------------------------ #
    #
    # Assigning the same shading group is NOT enough on a mesh with more than one
    # UV set. Maya links each texture to a particular UV set per mesh, and a mesh
    # that has just been created has none of those links, so every texture falls
    # back to the first set. The result is a correctly-shaded mesh reading its
    # textures off the wrong coordinates - not an error, just wrong, and wrong in
    # a way that looks like a UV problem rather than a link problem.
    decal = cmds.shadingNode('file', asTexture=True, name='decal_tex')
    cmds.connectAttr(decal + '.outColor', garment_shader + '.color', force=True)

    garment_plugs = {cmds.getAttr('{}.uvSet[{}].uvSetName'.format(garment_shape, i)):
                     '{}.uvSet[{}].uvSetName'.format(garment_shape, i)
                     for i in (cmds.getAttr(garment_shape + '.uvSet',
                                            multiIndices=True) or [])}
    check('the test garment really does have two UV sets',
          len(garment_plugs) == 2, str(sorted(garment_plugs)))

    cmds.uvLink(make=True, uvSet=garment_plugs['secondary'], texture=decal)
    linked_on_original = cmds.uvLink(uvSet=garment_plugs['secondary'],
                                     query=True) or []
    check('and the decal is linked to its second set, not its first',
          decal in cmds.ls(linked_on_original), str(linked_on_original))

    cmds.select(clear=True)
    linked = api.retarget_shapes(body, body_variant, [garment])
    check('retargeting a mesh with linked textures succeeds', linked['ok'],
          linked['message'])

    if linked['ok']:
        made_shape = cmds.listRelatives(linked['result'][0].name(), shapes=True,
                                        ni=True, type='mesh')[0]
        made_plugs = {cmds.getAttr('{}.uvSet[{}].uvSetName'.format(made_shape, i)):
                      '{}.uvSet[{}].uvSetName'.format(made_shape, i)
                      for i in (cmds.getAttr(made_shape + '.uvSet',
                                             multiIndices=True) or [])}
        check('the new mesh has both UV sets by name',
              sorted(made_plugs) == sorted(garment_plugs),
              '{} vs {}'.format(sorted(made_plugs), sorted(garment_plugs)))

        if 'secondary' in made_plugs:
            carried = cmds.ls(cmds.uvLink(uvSet=made_plugs['secondary'],
                                          query=True) or [])
            out['uv_links_carried'] = carried
            check('and the decal is linked to the SECOND set there too, '
                  'not the first',
                  decal in carried, str(carried))

    # --- per-face assignment -------------------------------------------------------- #
    #
    # A garment with a trim material on some faces. The two meshes are copies, so
    # face indices line up and the split has to survive.
    trim = cmds.shadingNode('lambert', asShader=True, name='trim_mat')
    trim_set = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                         name='trim_matSG')
    cmds.connectAttr(trim + '.outColor', trim_set + '.surfaceShader')
    face_count = cmds.polyEvaluate(garment, face=True)
    trim_faces = '{}.f[0:{}]'.format(garment, face_count // 4)
    cmds.sets(trim_faces, edit=True, forceElement=trim_set)

    # Count BEFORE the retarget. The first version of this counted afterwards and
    # filtered the set's members by 'garment' being in the node name - which also
    # matches "garment_retargeted", so it counted both meshes' faces on one side
    # of the comparison and one mesh's on the other, and reported 17 vs 34 for a
    # transfer that was exactly right.
    def _owners(node):
        """A mesh's transform AND shape short names.

        Maya writes shading set members under the TRANSFORM name
        ("garment.f[0:16]"), not the shape - so a helper that matched only the
        shape found nothing, and the check reported the original had no second
        material at all. The api's own _shading_assignments accepts either, and
        so must anything testing it.
        """
        names = {node.split('|')[-1]}
        for relative in ((cmds.listRelatives(node, shapes=True, ni=True,
                                             type='mesh') or []) +
                         (cmds.listRelatives(node, parent=True) or [])):
            names.add(relative.split('|')[-1])
        return names

    def trim_members_on(node):
        owners = _owners(node)
        return [member for member in
                (cmds.ls(cmds.sets(trim_set, query=True) or [], flatten=True) or [])
                if member.split('.')[0].split('|')[-1] in owners]

    original_trim_count = len(trim_members_on(garment))
    check('the original really does have a second material on some faces',
          original_trim_count > 0, str(original_trim_count))

    cmds.select(clear=True)
    split = api.retarget_shapes(body, body_variant, [garment])
    check('a mesh with two materials keeps both', split['ok'] and
          sorted(engines_on(split['result'][0].name())) == sorted([garment_set,
                                                                   trim_set]),
          str(engines_on(split['result'][0].name())))

    if split['ok']:
        new_shape = cmds.listRelatives(split['result'][0].name(), shapes=True,
                                       ni=True, type='mesh')[0]
        copied = len(trim_members_on(new_shape))
        out['trim_faces'] = [original_trim_count, copied]
        check('and the same number of faces carries the second material',
              copied == original_trim_count,
              '{} faces vs {}'.format(copied, original_trim_count))

        # Same COUNT is not the same FACES. The two meshes are copies, so the
        # indices must line up exactly or a trim lands somewhere else entirely.
        def face_indices(node):
            return {int(member.partition('.')[2].strip('f[]'))
                    for member in trim_members_on(node)}

        check('and they are the same face indices, not just the same count',
              face_indices(new_shape) == face_indices(garment),
              '{} vs {}'.format(sorted(face_indices(new_shape))[:5],
                                sorted(face_indices(garment))[:5]))

    # --- the pick is chosen for the deformation, not just spread out -------------- #
    #
    # This is the accuracy fix, and it is the one thing here worth pinning with a
    # number. Both meshes are known, so the TRUE answer is known for every vertex:
    # fit on a subset, evaluate everywhere, compare. An even spread wastes points
    # where nothing moves; an error-driven pick puts them where the fit is wrong.
    #
    # What was shipped first - an even spread of 300 - left a garment up to 3.2
    # scene units out of place on a 177-unit body, which is what "the chest is
    # off and the arms do not conform" looked like.
    cmds.file(new=True, force=True)
    base = cmds.polySphere(name='pick_base', sx=40, sy=40, ch=False)[0]
    moved = cmds.duplicate(base, name='pick_moved')[0]
    # A deformation that is deliberately UNEVEN: most of the mesh barely moves,
    # one band moves a lot. An even spread cannot know that; the error-driven
    # pick is supposed to find it.
    flat = cmds.xform(moved + '.vtx[*]', query=True, objectSpace=True, translation=True)
    for index in range(len(flat) // 3):
        y = flat[index * 3 + 1]
        if y > 0.3:
            cmds.move(0, 0, 0.45 * (y - 0.3), '{}.vtx[{}]'.format(moved, index),
                      objectSpace=True, relative=True)

    import maya.api.OpenMaya as om

    def object_points(node):
        shape = cmds.listRelatives(node, shapes=True, ni=True, type='mesh')[0]
        sel = om.MSelectionList(); sel.add(shape)
        return [(p.x, p.y, p.z) for p in
                om.MFnMesh(sel.getDagPath(0)).getPoints(om.MSpace.kObject)]

    truth = object_points(moved)

    def worst_error(ids):
        probe = cmds.duplicate(base, name='probe')[0]
        done = api.retarget_shapes(base, moved, [probe], solver_vertices=ids,
                                   place_on_target=False, shaders='none',
                                   max_solver_points=0)
        if not done['ok']:
            cmds.delete(probe)
            return None
        got = object_points(done['result'][0].name())
        held = set(ids)
        errors = [max(abs(a[i] - b[i]) for i in range(3))
                  for index, (a, b) in enumerate(zip(got, truth))
                  if index not in held]
        cmds.delete(probe)
        for node in done['result']:
            if cmds.objExists(str(node)):
                cmds.delete(str(node))
        return max(errors)

    spread = api.suggest_solver_vertices(base, count=120, select=False)
    driven = api.suggest_solver_vertices(base, count=120, target=moved, select=False)
    check('an error-driven pick succeeds', driven['ok'], driven['message'])
    check('and says what it is doing',
          'hardest' in driven['message'], driven['message'])
    check('and picks a different set from the even spread',
          set(driven['result']) != set(spread['result']))

    spread_worst = worst_error(spread['result'])
    driven_worst = worst_error(driven['result'])
    out['worst_spread'] = spread_worst
    out['worst_error_driven'] = driven_worst
    check('and it fits measurably better than an even spread of the same size',
          driven_worst is not None and spread_worst is not None
          and driven_worst < spread_worst * 0.8,
          'error-driven {} vs spread {}'.format(driven_worst, spread_worst))

    check('without a target it falls back to a spread, and says so',
          'spread' in spread['message'], spread['message'])
    check('and both are deterministic',
          api.suggest_solver_vertices(base, count=120, target=moved,
                                      select=False)['result'] == driven['result'])

    # --- one pick per target ------------------------------------------------------- #
    second = cmds.duplicate(base, name='pick_second')[0]
    cmds.scale(1.3, 1.0, 1.0, second + '.vtx[*]', objectSpace=True, relative=True)
    cmds.select(clear=True)
    many = contract('retarget_to_many with auto_pick',
                    api.retarget_to_many(base, [moved, second], [base],
                                         auto_pick=60, max_solver_points=0,
                                         place_on_target=False, shaders='none'))
    check('auto_pick picks separately for each target', many['ok'], many['message'])
    check('and says so', many['ok'] and 'its own solver vertices' in many['message'],
          many.get('message'))
    check('and still produces one result per target',
          many['ok'] and len(many['result']) == 2, str(many.get('result')))

    # --- the cost is answerable before the wait ---------------------------------- #
    source, target, shape = build_scene()
    cost = contract('estimate_cost', api.estimate_cost(source, solver_vertices=[0, 1, 2, 3]))
    check('estimate_cost succeeds', cost['ok'], cost['message'])
    check('and reports points and megabytes',
          cost['result']['points'] == 4 and cost['result']['megabytes'] > 0.0,
          str(cost['result']))
    big = api.estimate_cost(source, solver_vertices=list(range(20000)))
    check('and says when a solve would be refused', big['result']['refused'],
          str(big['result']))
    out['twenty_thousand_megabytes'] = round(big['result']['megabytes'], 1)

    # --- the selection is the default source of solver vertices ------------------- #
    source, target, shape = build_scene()
    cmds.select([source + '.vtx[0]', source + '.vtx[7]'])
    picked = api.selected_vertex_indices()
    check('selected_vertex_indices reads the selection', picked == [0, 7], str(picked))
    check('and filtering by mesh keeps them', api.selected_vertex_indices(source) == [0, 7],
          str(api.selected_vertex_indices(source)))

    # --- a whole blendshape, in-betweens and all ------------------------------------ #
    #
    # A blendShape stores each target under inputTargetItem[i] where i is
    # 5000 + weight * 1000: the full target at 6000, an in-between at 0.5 at 5500.
    # The first version read index 6000 and nothing else, so a face rig's
    # in-betweens came back MISSING with a cheerful success message - the worst
    # shape a bug can take, since the only symptom is fewer shapes than you had.
    source, target, shape = build_scene()
    half = cmds.duplicate(source, name='halfWay')[0]
    cmds.move(0, 0.9, 0, half + '.vtx[0]', objectSpace=True, relative=True)
    second = cmds.duplicate(source, name='secondShape')[0]
    cmds.move(0, 0, 2, second + '.vtx[5]', objectSpace=True, relative=True)
    blend = cmds.blendShape([shape, second], source, name='test_blend')[0]
    cmds.blendShape(blend, edit=True, inBetween=True, target=(source, 0, half, 0.5))
    cmds.aliasAttr('smile_L', blend + '.weight[0]')

    reading = contract('read_blendshape', api.read_blendshape(source, blend))
    check('read_blendshape succeeds', reading['ok'], reading['message'])
    weights = reading['ok'] and reading['result']['weights'] or []
    check('it finds both weights', len(weights) == 2, str(weights))
    first = weights[0] if weights else {}
    check('and keeps the channel name, not the mesh name',
          first.get('name') == 'smile_L', str(first.get('name')))
    check('and finds the in-between as well as the full target',
          len(first.get('targets', [])) == 2, str(first.get('targets')))
    check('and reports the in-between at the weight it sits on',
          any(abs(t['weight'] - 0.5) < 1e-9 for t in first.get('targets', [])),
          str(first.get('targets')))

    cmds.select(clear=True)
    whole = contract('retarget_blendshape',
                     api.retarget_blendshape(source, target, blend))
    check('retarget_blendshape rebuilds every target', whole['ok'], whole['message'])
    made = whole['result'] if whole['ok'] else {}
    check('and carries THREE meshes, not two - the in-between is not dropped',
          len(made.get('meshes', [])) == 3, str(made.get('meshes')))
    check('and says so in the message',
          'in-between' in whole['message'], whole['message'])

    node = made.get('blendshape')
    check('and builds a blendShape on the target', bool(node) and cmds.objExists(node),
          str(node))
    if node:
        out['rebuilt_blendshape'] = node
        channels = cmds.listAttr(node + '.weight', multi=True) or []
        # Without aliasing, every channel would be called after the retargeted
        # mesh - "smile_L_retargeted" - and nothing that drove the original
        # would still find it.
        check('with the ORIGINAL channel names, not the retargeted mesh names',
              'smile_L' in channels, str(channels))
        items = cmds.getAttr(
            '{}.inputTarget[0].inputTargetGroup[0].inputTargetItem'.format(node),
            multiIndices=True) or []
        check('and the in-between really is on the node at its own item index',
              5500 in items and 6000 in items, str(items))

        # The test that matters: does it deform, and does the in-between bend the
        # curve rather than sitting on the straight line between 0 and 1?
        def height():
            return cmds.xform(target + '.vtx[0]', query=True, objectSpace=True,
                              translation=True)[1]
        cmds.setAttr(node + '.smile_L', 0.0)
        rest = height()
        cmds.setAttr(node + '.smile_L', 1.0)
        full_on = height()
        cmds.setAttr(node + '.smile_L', 0.5)
        midway = height()
        cmds.setAttr(node + '.smile_L', 0.0)
        out['inbetween_curve'] = [round(rest, 4), round(midway, 4), round(full_on, 4)]
        check('the rebuilt channel actually deforms the target',
              abs(full_on - rest) > 1e-4, str(out['inbetween_curve']))
        check('and the in-between bends the curve instead of interpolating straight',
              abs(midway - (rest + full_on) / 2.0) > 1e-3, str(out['inbetween_curve']))

    # A blendShape whose targets were deleted has nothing to read, and should say
    # so rather than quietly returning nothing.
    source, target, shape = build_scene()
    lone = cmds.duplicate(source, name='lonely')[0]
    dead = cmds.blendShape([lone], source, name='dead_blend')[0]
    cmds.delete(lone)
    check('a blendShape whose targets were deleted is refused with a reason',
          not api.retarget_blendshape(source, target, dead)['ok'])

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
