"""Exercise the pose skinner end to end, in Maya, against ground truth it builds.

The maths is covered off-DCC by test_solver.cpp. This is about everything between
the maths and the artist: sampling the scene at the right frames, in the right
space, with the right bind matrices; writing weights into a skinCluster that is
not necessarily on the mesh that was sampled; undo; and the Python layer's
refusals.

The ground truth here is Maya's own skinning. A cylinder is smooth-bound and its
joints animated, so the mesh deforms by a real skinCluster with weights Maya
chose. Solving that deformation back must return Maya's weights - not something
close, the same ones - because a linear blend skin is exactly what the solver
models. Anything less and the shell around the maths is wrong somewhere, and this
suite is the only thing that can say so.
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

    The bundles are APPENDED, never inserted: the python311 bundle carries its own
    PySide6 that does not import under mayapy, and mca.common.pyqt.pygui swallows
    the ImportError and hands back a stub - so putting it in front turns every Qt
    call into an AttributeError several frames from the cause.
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

RESULT = _result_path('mcaPoseSkinner_api.json')
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
          'got {!r}'.format(type(response)))
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
    # Undo is off by default under mayapy, and the undo checks below are the
    # point of the command being undoable at all.
    cmds.undoInfo(state=True, infinity=True)

    import maya.api.OpenMaya as om
    import pymel.core as pm
    from mca.mya.tools.poseskinner import poseskinner_api as api

    available, reason = api.plugin_is_available()
    check('the plug-in loads', available, reason)
    if not available:
        raise RuntimeError(reason)

    FRAMES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    REST = 0.0

    def points(node, frame=None):
        if frame is not None:
            cmds.currentTime(frame)
        selection = om.MSelectionList()
        selection.add(str(node))
        mesh = om.MFnMesh(selection.getDagPath(0))
        return [(p.x, p.y, p.z) for p in mesh.getPoints(om.MSpace.kWorld)]

    def worst_between(a, b):
        return max(math.sqrt(sum((x - y) ** 2 for x, y in zip(pa, pb)))
                   for pa, pb in zip(a, b))

    def build_truth(joint_count=3, subdivisions=12, height=6.0):
        """A cylinder bound to a few joints, with the joints animated.

        Maya's own skinning is the ground truth: whatever weights it chose, the
        solve has to find them again.
        """
        cmds.file(new=True, force=True)
        cylinder = cmds.polyCylinder(radius=1.0, height=height, subdivisionsX=10,
                                     subdivisionsY=subdivisions, subdivisionsZ=1,
                                     axis=(0, 1, 0), name='truth')[0]
        joints = []
        cmds.select(clear=True)
        for index in range(joint_count):
            y = -height / 2.0 + height * index / float(joint_count - 1)
            joints.append(cmds.joint(name='truthJoint{}'.format(index + 1),
                                     position=(0.0, y, 0.0)))
        cluster = cmds.skinCluster(joints, cylinder, toSelectedBones=True,
                                   maximumInfluences=3, normalizeWeights=1)[0]

        cmds.currentTime(REST)
        for joint in joints:
            cmds.setKeyframe(joint, attribute=['rotateX', 'rotateY', 'rotateZ'], value=0.0)
        for position, frame in enumerate(FRAMES):
            cmds.currentTime(frame)
            for index, joint in enumerate(joints):
                cmds.setKeyframe(joint, attribute='rotateZ',
                                 value=9.0 * (index + 1) * (position + 1) / len(FRAMES))
                cmds.setKeyframe(joint, attribute='rotateX',
                                 value=-4.0 * (index + 1) * (position % 3))
        cmds.currentTime(REST)
        return cylinder, joints, cluster

    cylinder, joints, truth_cluster = build_truth()
    shape = cmds.listRelatives(cylinder, shapes=True, noIntermediate=True)[0]
    out['vertices'] = cmds.polyEvaluate(shape, vertex=True)

    # --- the solve recovers Maya's own weights ------------------------------- #
    response = contract('solve', api.solve(cylinder, joints, FRAMES, rest_frame=REST,
                                           max_influences=3, per_vertex_error=True))
    check('solve succeeds on a skinned mesh', response['ok'], response['message'])
    solved = response['result']
    out['rms'] = solved and solved['rms']
    out['worst'] = solved and solved['worst']
    # Exactly, to within float storage: the deformation IS a linear blend skin, so
    # there is a right answer and it is reachable.
    check('the fit is exact on a deformation that is itself a skinning',
          solved['rms'] < 1e-6, str(solved['rms']))

    def maya_weights(cluster, vertex):
        values = {}
        for influence in cmds.skinCluster(cluster, q=True, influence=True):
            weight = cmds.skinPercent(cluster, '{}.vtx[{}]'.format(shape, vertex),
                                      query=True, transform=influence)
            if weight > 1e-6:
                values[cmds.ls(influence, long=True)[0]] = weight
        return values

    worst_weight = 0.0
    for vertex in range(0, out['vertices'], 7):
        theirs = maya_weights(truth_cluster, vertex)
        ours = {name: weight for name, weight in solved['weights'][vertex].items()
                if weight > 1e-6}
        for name in set(list(theirs) + list(ours)):
            worst_weight = max(worst_weight, abs(theirs.get(name, 0.0) - ours.get(name, 0.0)))
    out['worst_weight_difference'] = worst_weight
    check('and the weights it returns are the ones Maya had', worst_weight < 1e-4,
          str(worst_weight))

    check('every vertex comes back', len(solved['weights']) == out['vertices'],
          '{} of {}'.format(len(solved['weights']), out['vertices']))
    check('weights sum to one',
          all(abs(sum(entry.values()) - 1.0) < 1e-9 for entry in solved['weights'].values()))
    check('the influence limit is honoured',
          max(len(entry) for entry in solved['weights'].values()) <= 3)
    check('per-vertex error comes back for every vertex',
          len(solved['vertex_error']) == out['vertices'])
    check('per-pose error comes back for every pose',
          len(solved['pose_error']) == len(FRAMES))
    check('nothing was applied when nothing was asked to be', not solved['applied'])

    # --- held-out poses ------------------------------------------------------ #
    held = contract('solve with holdout', api.solve(cylinder, joints, FRAMES, rest_frame=REST,
                                                    max_influences=3, holdout=[3.0, 5.0]))
    check('holding poses out works', held['ok'], held['message'])
    check('and reports their error separately', held['result']['holdout_rms'] is not None)
    out['holdout_rms'] = held['result']['holdout_rms']
    # The same skinning fits every pose, so a held-out pose is no harder. This is
    # the case where overfitting cannot happen, and the number says so.
    check('a held-out pose is fitted too, when one skinning fits them all',
          held['result']['holdout_rms'] < 1e-6, str(held['result']['holdout_rms']))

    # --- solving a subset of vertices ---------------------------------------- #
    subset = [0, 1, 2, 3, 4, 5]
    part = contract('solve a subset', api.solve(cylinder, joints, FRAMES, rest_frame=REST,
                                                max_influences=3, vertices=subset))
    check('a vertex subset solves', part['ok'], part['message'])
    check('and only those vertices come back',
          sorted(part['result']['weights']) == sorted(subset),
          str(sorted(part['result']['weights'])[:8]))

    # --- writing the weights into a skinCluster, on a different mesh ---------- #
    copy = cmds.duplicate(cylinder, name='copy', returnRootsOnly=True)[0]
    cmds.delete(copy, constructionHistory=True)
    copy_shape = cmds.listRelatives(copy, shapes=True, noIntermediate=True)[0]
    cmds.currentTime(REST)
    copy_cluster = cmds.skinCluster(joints, copy, toSelectedBones=True, maximumInfluences=3,
                                    normalizeWeights=1)[0]
    # Flatten it first, so "the weights got written" cannot be true by accident.
    for vertex in range(out['vertices']):
        cmds.skinPercent(copy_cluster, '{}.vtx[{}]'.format(copy_shape, vertex),
                         transformValue=[(joints[0], 1.0)])
    before = worst_between(points(shape, FRAMES[-1]), points(copy_shape, FRAMES[-1]))
    out['before_applying'] = before
    check('the flattened copy is visibly wrong to start with', before > 0.5, str(before))

    def sample_weights(vertex=5):
        """One vertex's weights, read with a QUERY so nothing lands on the undo queue.

        This matters more than it looks. The first version of the undo check
        measured mesh positions either side of `cmds.undo()`, and measuring a
        position means moving the current time - which is itself an undoable
        command. So the undo undid a time change, the weights never moved, and the
        check reported that undo does not work while it worked perfectly. Queries
        are not recorded, so reading weights leaves the queue alone.
        """
        return [round(cmds.skinPercent(copy_cluster, '{}.vtx[{}]'.format(copy_shape, vertex),
                                       query=True, transform=joint), 5)
                for joint in joints]

    flattened = sample_weights()
    applied = contract('solve and apply', api.solve(cylinder, joints, FRAMES, rest_frame=REST,
                                                    max_influences=3,
                                                    apply_to=copy_cluster))
    check('applying to a skinCluster on another mesh works', applied['ok'], applied['message'])
    if applied['ok']:
        check('and it says it applied them', applied['result']['applied'])
        solved_weights = sample_weights()
        check('the weights on the other mesh changed',
              solved_weights != flattened, str(solved_weights))

        # --- undo ------------------------------------------------------------ #
        # The tool this replaces set skin weights outside the undo queue on
        # purpose: "I dont care about undo because the storageNode will be deleted
        # in the python undo". So this is a behaviour ours has and it does not.
        cmds.undo()
        out['after_undo'] = sample_weights()
        check('undo puts the old weights back', sample_weights() == flattened,
              '{} against {}'.format(sample_weights(), flattened))
        cmds.redo()
        check('and redo puts the solved ones back', sample_weights() == solved_weights,
              str(sample_weights()))

        after = max(worst_between(points(shape, frame), points(copy_shape, frame))
                    for frame in FRAMES)
        out['after_applying'] = after
        check('the copy now moves like the original on every pose', after < 1e-4, str(after))

    # --- skin_from_poses, the whole job -------------------------------------- #
    cmds.currentTime(REST)
    whole = contract('skin_from_poses', api.skin_from_poses(cylinder, joints, FRAMES,
                                                            rest_frame=REST,
                                                            max_influences=3,
                                                            holdout=[4.0], show=True))
    check('skin_from_poses succeeds', whole['ok'], whole['message'])
    out['skin_from_poses'] = whole['message']
    if whole['ok']:
        made = whole['result']
        check('it used the mesh in place, there being nothing else deforming it',
              made['copy'] is None, str(made['copy']))
        check('it found the skinCluster that was already there', not made['created'])
        check('the heat map was painted',
              bool(cmds.polyColorSet(shape, q=True, allColorSets=True)))
        cleared = contract('clear_error_colours', api.clear_error_colours(cylinder))
        check('and can be taken off again', cleared['ok'] and
              not (cmds.polyColorSet(shape, q=True, allColorSets=True) or []))

        # --- and the mesh is left as clean as it was found ------------------- #
        #
        # The colours coming off is not the same as the mesh being clean. Painting a
        # DEFORMED mesh needs construction history - colours written straight onto
        # the output shape are discarded the next time the skinCluster evaluates - so
        # `polyColorPerVertex` inserts a node. Clearing used to delete the colour SET
        # and add a `deleteColorSet` node to do it, leaving the dead
        # `polyColorPerVertex` in front of that: the history got one node LONGER
        # every time the heat map was cleared, and an artist looking at the
        # connections saw junk hanging off their result. Found by somebody looking at
        # the node editor, not by any of these checks - hence these checks.
        junk = [node for node in (cmds.listHistory(shape) or [])
                if cmds.nodeType(node) in ('polyColorPerVertex', 'deleteColorSet',
                                           'createColorSet')]
        check('clearing leaves no colour history behind', not junk, str(junk))

        errors = (made.get('solve') or {}).get('vertex_error')
        if errors:
            # Painting twice must not stack a second set of nodes.
            api.show_error(cylinder, errors)
            once = len(cmds.listHistory(shape) or [])
            api.show_error(cylinder, errors)
            twice = len(cmds.listHistory(shape) or [])
            check('painting twice does not stack history nodes', once == twice,
                  '{} then {}'.format(once, twice))

            # And it must not touch a colour set it did not make. The first version
            # deleted EVERY colour set on the mesh; on a test sphere there are none
            # and it looked fine, on a production head there are authored ones.
            cmds.polyColorSet(shape, create=True, clamped=False, representation='RGB',
                              colorSet='authored_by_an_artist')
            api.clear_error_colours(cylinder)
            left = cmds.polyColorSet(shape, q=True, allColorSets=True) or []
            check("an artist's own colour set survives clearing",
                  left == ['authored_by_an_artist'], str(left))
            still = [node for node in (cmds.listHistory(shape) or [])
                     if cmds.nodeType(node) in ('polyColorPerVertex', 'deleteColorSet')]
            check('and no heat-map nodes survive it either', not still, str(still))
            cmds.polyColorSet(shape, delete=True, colorSet='authored_by_an_artist')

    # --- a mesh that still has the deformer which made the poses -------------- #
    #
    # This is the case that matters on a face: skinning the mesh in place would put
    # the skin on top of the blendShape it was fitted to reproduce, and the result
    # is the deformation applied twice. It must notice and use a copy.
    cmds.file(new=True, force=True)
    base = cmds.polySphere(radius=2.0, subdivisionsX=12, subdivisionsY=12, name='face')[0]
    target = cmds.duplicate(base, name='face_smile', returnRootsOnly=True)[0]
    cmds.select(clear=True)
    for vertex in range(cmds.polyEvaluate(target, vertex=True)):
        position = cmds.pointPosition('{}.vtx[{}]'.format(target, vertex), world=True)
        if position[1] > 0.0:
            cmds.move(position[0] * 1.25, position[1] + 0.35, position[2] * 1.25,
                      '{}.vtx[{}]'.format(target, vertex), absolute=True)
    blend = cmds.blendShape(target, base, name='faceBlend')[0]
    cmds.select(clear=True)
    face_joints = [cmds.joint(name='faceRoot', position=(0.0, 0.0, 0.0))]
    cmds.select(clear=True)
    face_joints.append(cmds.joint(name='faceTop', position=(0.0, 2.0, 0.0)))
    cmds.currentTime(0)
    for joint in face_joints:
        cmds.setKeyframe(joint, attribute=['translateY', 'scaleX', 'scaleY', 'scaleZ'])
    cmds.setKeyframe(blend + '.' + cmds.aliasAttr(blend + '.weight[0]', q=True),
                     time=0, value=0.0)
    cmds.setKeyframe(blend + '.' + cmds.aliasAttr(blend + '.weight[0]', q=True),
                     time=1, value=1.0)
    cmds.currentTime(1)
    cmds.setKeyframe('faceTop.translateY', time=1, value=2.35)
    cmds.setKeyframe('faceTop.scaleX', time=1, value=1.25)
    cmds.setKeyframe('faceTop.scaleZ', time=1, value=1.25)

    cmds.currentTime(0)
    faced = contract('skin_from_poses on a blendShaped mesh',
                     api.skin_from_poses(base, face_joints, [1.0], rest_frame=0.0,
                                         max_influences=2, rigid_bones=False))
    check('a mesh that still has its blendShape gets a copy, not a skin on top',
          faced['ok'] and faced['result']['copy'] is not None,
          faced['message'])
    out['face_message'] = faced['message']

    # --- auto joints ---------------------------------------------------------- #
    try:
        import numpy  # noqa: F401
        has_numpy = True
    except ImportError:
        has_numpy = False

    if has_numpy:
        cmds.file(new=True, force=True)
        bendy = cmds.polyCylinder(radius=1.0, height=8.0, subdivisionsX=10,
                                  subdivisionsY=14, axis=(0, 1, 0), name='bendy')[0]
        bend = cmds.nonLinear(bendy, type='bend')[0]
        cmds.setAttr(bend + '.lowBound', 0)
        cmds.currentTime(0)
        cmds.setKeyframe(bend + '.curvature', time=0, value=0.0)
        cmds.setKeyframe(bend + '.curvature', time=1, value=30.0)
        cmds.setKeyframe(bend + '.curvature', time=2, value=60.0)
        cmds.setKeyframe(bend + '.curvature', time=3, value=90.0)
        cmds.currentTime(0)
        auto = contract('auto_joints', api.auto_joints(bendy, 5, [1.0, 2.0, 3.0],
                                                       rest_frame=0.0, max_influences=4,
                                                       iterations=12))
        check('auto_joints runs on a deformation with no skeleton at all', auto['ok'],
              auto['message'])
        out['auto_joints'] = auto['message']
        if auto['ok']:
            check('it made the joints asked for', len(auto['result']['joints']) == 5,
                  str(len(auto['result']['joints'])))
            check('they are keyed',
                  all(cmds.keyframe(joint, query=True, keyframeCount=True)
                      for joint in auto['result']['joints']))

            # The keys are written straight into anim curves through the API rather
            # than with 9 setKeyframe calls per joint per frame, and an angular
            # curve stores RADIANS while setKeyframe takes degrees. Getting that
            # wrong gives joints rotated by a factor of 57 and a skin that looks
            # exploded - so the check is that the joint actually ends up where the
            # solve said it should, not merely that keys exist.
            bones = auto['result']['solve'].get('bones')
            if bones:
                worst_matrix = 0.0
                for position, frame in enumerate([1.0, 2.0, 3.0]):
                    cmds.currentTime(frame)
                    for index, joint in enumerate(auto['result']['joints']):
                        actual = cmds.getAttr(joint + '.worldMatrix')
                        wanted = bones[position][index]
                        worst_matrix = max(worst_matrix,
                                           max(abs(a - b) for a, b in zip(actual, wanted)))
                out['worst_keyed_matrix_error'] = worst_matrix
                check('and each joint lands on the transform the solve gave it',
                      worst_matrix < 1e-5, str(worst_matrix))
                # Put the clock back. Leaving it on frame 3 is what found the bug
                # where add_correctives read the rest shape at the current time -
                # worth doing here anyway, since a check should not leave the scene
                # somewhere the next one does not expect.
                cmds.currentTime(0)
            solve = auto['result']['solve']
            out['auto_rms'] = solve['rms']
            out['auto_worst'] = solve['worst']
            # A bend is not a skinning, so this cannot be exact. Five joints on an
            # 8-unit cylinder bent 90 degrees should still land inside a tenth of a
            # unit on average - and the number is recorded either way.
            check('and the fit is close', solve['rms'] < 0.1, str(solve['rms']))

            # --- correctives, on a residual that genuinely exists ------------- #
            #
            # This is the case for them: a bend is not a linear blend skin, so
            # whatever the weights do there is something left over, and the
            # correctives are what hold it. On the blendshaped sphere above there
            # was nothing left over at all - two joints with scale reproduce that
            # shape exactly - and a corrective test there would have been a test of
            # nothing.
            fixed = contract('add_correctives',
                             api.add_correctives(auto['result']['skinned_mesh'], bendy,
                                                 [1.0, 2.0, 3.0]))
            check('correctives can be built', fixed['ok'], fixed['message'])
            out['correctives'] = fixed['message']
            if fixed['ok']:
                out['corrective_before'] = fixed['result']['worst_before']
                out['corrective_after'] = fixed['result']['worst_after']
                check('the skin alone leaves something to correct',
                      fixed['result']['worst_before'] > 0.01,
                      str(fixed['result']['worst_before']))
                check('and the correctives close it',
                      fixed['result']['worst_after'] <
                      max(1e-4, 0.05 * fixed['result']['worst_before']),
                      '{} -> {}'.format(fixed['result']['worst_before'],
                                        fixed['result']['worst_after']))

    # --- refusals ------------------------------------------------------------- #
    cmds.file(new=True, force=True)
    cylinder, joints, truth_cluster = build_truth()

    refused = contract('solve with no frames', api.solve(cylinder, joints, []))
    check('no frames is refused, with a reason',
          not refused['ok'] and len(refused['message']) > 20, refused['message'])

    refused = contract('solve with no joints', api.solve(cylinder, [], FRAMES))
    check('no joints is refused', not refused['ok'], refused['message'])

    refused = contract('solve on something that is not a mesh',
                       api.solve(joints[0], joints, FRAMES))
    check('a non-mesh is refused', not refused['ok'], refused['message'])

    refused = contract('holdout that is not being fitted',
                       api.solve(cylinder, joints, FRAMES, holdout=[99.0]))
    check('holding out a frame that is not in the list is refused, not ignored',
          not refused['ok'] and '99' in refused['message'], refused['message'])

    refused = contract('holding out everything',
                       api.solve(cylinder, joints, FRAMES, holdout=list(FRAMES)))
    check('holding out every frame is refused', not refused['ok'], refused['message'])

    refused = contract('influence_report', api.influence_report(cylinder, joints, FRAMES,
                                                                budgets=(1, 3),
                                                                rest_frame=REST))
    check('influence_report measures each budget', refused['ok'], refused['message'])
    if refused['ok']:
        rows = refused['result']
        out['influence_report'] = rows
        check('and a tighter budget is never better than a looser one',
              rows[0]['rms'] >= rows[1]['rms'] - 1e-9,
              str([row['rms'] for row in rows]))

    # --- laying blendShape targets out onto frames ---------------------------- #
    cmds.file(new=True, force=True)
    base = cmds.polySphere(radius=1.0, name='head')[0]
    shapes = []
    for index in range(3):
        copy = cmds.duplicate(base, name='head_shape{}'.format(index),
                              returnRootsOnly=True)[0]
        cmds.move(0.2 * (index + 1), '{}.vtx[0]'.format(copy), y=True, relative=True)
        shapes.append(copy)
    cmds.blendShape(shapes, base, name='headBlend')
    laid = contract('poses_from_blendshape', api.poses_from_blendshape(base, start_frame=0.0))
    check('a blendShape can be laid out onto frames', laid['ok'], laid['message'])
    if laid['ok']:
        check('one frame per channel', len(laid['result']['frames']) == 3,
              str(laid['result']['frames']))
        cmds.currentTime(laid['result']['frames'][1])
        values = [cmds.getAttr('headBlend.' + name) for name in laid['result']['channels']]
        check('and on each frame exactly one channel is on',
              abs(sum(values) - 1.0) < 1e-6 and abs(max(values) - 1.0) < 1e-6, str(values))

    # --- additive mode: adding joints to a skin that already exists ----------- #
    #
    # The case the feature exists for, built so the right answer is known.
    #
    # A long cylinder is bound entirely to `trunk`, which never moves. `bump` is a
    # second joint near one END of it, and the poses are made by moving `bump` with
    # hand-painted weights that fall off over a few rings. Solved additively with
    # `trunk` as the donor:
    #
    #   * `bump` must earn weight near its own end and NOTHING at the far end - the
    #     "cheek joint on the back of the head" problem, reduced to something with a
    #     yes/no answer,
    #   * every vertex must still sum to 1,
    #   * and a third influence nobody nominated must come out bit-identical.
    cmds.file(new=True, force=True)
    tube = cmds.polyCylinder(radius=1.0, height=20.0, subdivisionsX=12, subdivisionsY=24,
                             subdivisionsZ=0, axis=(0, 1, 0), name='trunkMesh')[0]
    tube_shape = cmds.listRelatives(tube, shapes=True, noIntermediate=True, fullPath=True)[0]
    verts = cmds.polyEvaluate(tube, vertex=True)

    cmds.select(clear=True)          # or cmds.joint parents the joint under the mesh
    trunk = cmds.joint(name='trunk', position=(0, -10, 0))
    cmds.select(clear=True)
    spare = cmds.joint(name='spare', position=(0, -10, 3))     # an influence to leave alone
    cmds.select(clear=True)
    bump = cmds.joint(name='bump', position=(0, 8, 0))          # the joint being added
    cmds.select(clear=True)

    base_skin = cmds.skinCluster(trunk, spare, tube, toSelectedBones=True,
                                 maximumInfluences=2, name='baseSkin')[0]
    # Give `spare` a slice of the weight at the bottom so "untouched" means something.
    for vertex in range(verts):
        y = cmds.pointPosition('{}.vtx[{}]'.format(tube, vertex), world=True)[1]
        share = 0.3 if y < -8.0 else 0.0
        cmds.skinPercent(base_skin, '{}.vtx[{}]'.format(tube, vertex),
                         transformValue=[(spare, share), (trunk, 1.0 - share)])

    before, columns = api._skin_weights(tube_shape, base_skin)
    spare_column = columns.index(cmds.ls(spare, long=True)[0])

    # The poses: move `bump` and deform the top of the tube by a known falloff.
    rest_points = [cmds.pointPosition('{}.vtx[{}]'.format(tube, v), world=True)
                   for v in range(verts)]
    truth = []
    for vertex in range(verts):
        y = rest_points[vertex][1]
        truth.append(max(0.0, min(1.0, (y - 4.0) / 6.0)))      # 0 below y=4, 1 at y=10
    ADD_FRAMES = [1.0, 2.0, 3.0, 4.0]
    cmds.currentTime(0)
    cmds.setKeyframe(bump, attribute=['translateX', 'translateY', 'translateZ'], t=0)
    for index, frame in enumerate(ADD_FRAMES):
        cmds.setKeyframe(bump, attribute='translateX', value=0.4 * (index + 1), t=frame)
        cmds.setKeyframe(bump, attribute='translateY', value=8.0, t=frame)
        cmds.setKeyframe(bump, attribute='translateZ', value=0.0, t=frame)

    # Bake the target shape into a blendShape so the mesh really is deformed at each
    # frame, the way a face's poses arrive.
    targets = []
    for index, frame in enumerate(ADD_FRAMES):
        copy = cmds.duplicate(tube, name='pose{}'.format(index))[0]
        for history in (cmds.listHistory(copy) or []):
            if cmds.nodeType(history) in ('skinCluster', 'tweak'):
                try:
                    cmds.delete(history)
                except Exception:
                    pass
        shift = 0.4 * (index + 1)
        for vertex in range(verts):
            x, y, z = rest_points[vertex]
            cmds.move(x + shift * truth[vertex], y, z,
                      '{}.vtx[{}]'.format(copy, vertex), absolute=True, worldSpace=True)
        targets.append(copy)
    blend = cmds.blendShape(targets, tube, frontOfChain=True, name='poseBlend')[0]
    for index, frame in enumerate(ADD_FRAMES):
        for other in range(len(ADD_FRAMES)):
            cmds.setKeyframe('{}.{}'.format(blend, targets[other].split('|')[-1]),
                             value=1.0 if other == index else 0.0, t=frame)
        cmds.setKeyframe('{}.{}'.format(blend, targets[index].split('|')[-1]), value=0.0, t=0)
    cmds.delete(targets)

    cmds.currentTime(0)
    added = contract('add_to_skin', api.add_to_skin(tube, [bump], ADD_FRAMES, donors=[trunk],
                                                    rest_frame=0.0, max_influences=1))
    check('add_to_skin succeeds', added['ok'], added['message'])
    out['add_to_skin'] = added['message']
    if added['ok']:
        got = added['result']
        # The default now puts the result on a COPY with the existing skinning carried
        # across, so read it back from where it actually went rather than from the
        # original's cluster - which is exactly the mistake this check caught.
        check('it went on a copy by default', got['copy'] is not None, str(got['copy']))
        check('and the original keeps its blendShape',
              bool(cmds.ls(type='blendShape')) and
              base_skin in (cmds.listHistory(tube_shape) or []),
              'original cluster gone' if base_skin not in
              (cmds.listHistory(tube_shape) or []) else '')
        result_mesh = got['skinned_mesh']
        result_cluster = got['skin_cluster']
        after, columns_after = api._skin_weights(result_mesh, result_cluster)
        bump_column = columns_after.index(cmds.ls(bump, long=True)[0])
        spare_after = columns_after.index(cmds.ls(spare, long=True)[0])

        # THE check: nothing at the far end.
        far = [v for v in range(verts) if rest_points[v][1] < 0.0]
        worst_far = max(after[v][bump_column] for v in far)
        out['additive_far_end'] = worst_far
        check('the added joint takes NO weight at the far end of the mesh',
              worst_far < 1e-9, str(worst_far))

        near = [v for v in range(verts) if rest_points[v][1] > 8.0]
        least_near = min(after[v][bump_column] for v in near)
        out['additive_near_end'] = least_near
        check('and it does take weight where it belongs', least_near > 0.5, str(least_near))

        totals = [sum(after[v]) for v in range(verts)]
        worst_total = max(abs(t - 1.0) for t in totals)
        out['additive_worst_total'] = worst_total
        check('every vertex still sums to one', worst_total < 1e-6, str(worst_total))

        # `before` is the original's weights, so this proves the keeper survived BOTH the
        # transfer onto the copy and the solve on top of it.
        moved_spare = max(abs(after[v][spare_after] - before[v][spare_column])
                          for v in range(verts))
        out['additive_spare_moved'] = moved_spare
        check('the influence nobody nominated is bit-identical', moved_spare == 0.0,
              str(moved_spare))

        check("and the API's own verification agrees", got['verified']['ok'],
              str(got['verified']))

        # Recovering the painted falloff is the accuracy claim.
        worst_weight = max(abs(after[v][bump_column] - truth[v]) for v in range(verts))
        out['additive_worst_weight'] = worst_weight
        check('the hand-painted falloff is recovered', worst_weight < 0.02, str(worst_weight))

        # Undo must put back the weights AND remove the influence it added.
        cmds.undo()
        restored = cmds.skinCluster(result_cluster, q=True, influence=True) or [] \
            if cmds.objExists(result_cluster) else []
        check('undo removes the influence it added',
              cmds.ls(bump, long=True)[0] not in
              [cmds.ls(j, long=True)[0] for j in restored], str(restored))

        # --- and it must not matter where the timeline is parked ------------- #
        #
        # Binding a skinCluster uses the joints WHERE THEY ARE NOW, so a copy bound while
        # the artist sits on a pose frame gets its bind matrices from that pose - and every
        # weight after that is measured against the wrong rest pose. The result is wrong
        # and looks plausible, which is the worst combination. `clean_copy` went to the
        # rest frame and put the time back before returning, so the transfer that follows
        # it used to bind at whatever frame was current.
        cmds.currentTime(ADD_FRAMES[-1])
        parked = contract('add_to_skin (parked on a pose frame)',
                          api.add_to_skin(tube, [bump], ADD_FRAMES, donors=[trunk],
                                          rest_frame=0.0, max_influences=1))
        check('it works the same when the timeline is parked on a pose frame',
              parked['ok'], parked['message'])
        if parked['ok']:
            check('and the answer is identical to running it at the rest frame',
                  abs(parked['result']['solve']['rms'] -
                      added['result']['solve']['rms']) < 1e-9,
                  '{} against {}'.format(parked['result']['solve']['rms'],
                                         added['result']['solve']['rms']))
            check('the time was put back afterwards',
                  cmds.currentTime(q=True) == ADD_FRAMES[-1],
                  str(cmds.currentTime(q=True)))
        cmds.currentTime(0)


    # --- run it twice: the tool must clean up after itself ---------------------- #
    #
    # Everything here is about being usable more than once. Before this, a second run
    # left another `<mesh>_skinned` beside the first, another 200 poseJoints bound to the
    # old copy, and whatever the user had selected replaced by whatever
    # `pm.copySkinWeights` needed selected. None of that is visible in a single run, which
    # is why it survived so long.
    cmds.file(new=True, force=True)
    twice = cmds.polySphere(radius=2.0, subdivisionsX=10, subdivisionsY=10, name='twice')[0]
    bulge = cmds.duplicate(twice, name='twice_bulge')[0]
    for vertex in range(cmds.polyEvaluate(bulge, vertex=True)):
        x, y, z = cmds.pointPosition('{}.vtx[{}]'.format(bulge, vertex), world=True)
        if y > 0:
            cmds.move(x * 1.3, y + 0.3, z * 1.3, '{}.vtx[{}]'.format(bulge, vertex),
                      absolute=True, worldSpace=True)
    twice_blend = cmds.blendShape(bulge, twice, name='twiceBlend')[0]
    cmds.delete(bulge)
    cmds.setKeyframe(twice_blend + '.twice_bulge', value=0.0, t=0)
    cmds.setKeyframe(twice_blend + '.twice_bulge', value=1.0, t=1)
    cmds.setKeyframe(twice_blend + '.twice_bulge', value=0.6, t=2)
    TWICE_FRAMES = [1.0, 2.0]

    marker = cmds.spaceLocator(name='what_the_user_had_selected')[0]
    cmds.select(marker, replace=True)

    cmds.currentTime(0)
    first = contract('auto_joints (1st run)',
                     api.auto_joints(twice, 6, TWICE_FRAMES, rest_frame=0.0,
                                     max_influences=3, iterations=2))
    check('the auto-joint run succeeds', first['ok'], first['message'])
    if first['ok']:
        after_one = {
            'transforms': len(cmds.ls(type='transform') or []),
            'joints': len(cmds.ls(type='joint') or []),
            'skins': len(cmds.ls(type='skinCluster') or []),
            'meshes': len(cmds.ls(type='mesh') or []),
        }
        check('the selection survived the first run',
              (cmds.ls(selection=True, long=True) or []) ==
              [cmds.ls(marker, long=True)[0]],
              str(cmds.ls(selection=True) or []))

        cmds.currentTime(0)
        cmds.select(marker, replace=True)
        second = contract('auto_joints (2nd run)',
                          api.auto_joints(twice, 6, TWICE_FRAMES, rest_frame=0.0,
                                          max_influences=3, iterations=2))
        check('and it runs a second time', second['ok'], second['message'])
        if second['ok']:
            after_two = {
                'transforms': len(cmds.ls(type='transform') or []),
                'joints': len(cmds.ls(type='joint') or []),
                'skins': len(cmds.ls(type='skinCluster') or []),
                'meshes': len(cmds.ls(type='mesh') or []),
            }
            out['run_twice'] = {'after_one': after_one, 'after_two': after_two}
            check('running twice leaves the same number of joints',
                  after_one['joints'] == after_two['joints'],
                  '{} then {}'.format(after_one['joints'], after_two['joints']))
            check('and the same number of skinClusters',
                  after_one['skins'] == after_two['skins'],
                  '{} then {}'.format(after_one['skins'], after_two['skins']))
            check('and the same number of meshes - no second copy piling up',
                  after_one['meshes'] == after_two['meshes'],
                  '{} then {}'.format(after_one['meshes'], after_two['meshes']))
            check('the selection survived the second run too',
                  (cmds.ls(selection=True, long=True) or []) ==
                  [cmds.ls(marker, long=True)[0]],
                  str(cmds.ls(selection=True) or []))

            # A mesh somebody else named the same way must NOT be swept up.
            decoy = cmds.polyCube(name='twice_skinned_by_hand')[0]
            cmds.currentTime(0)
            cmds.select(marker, replace=True)
            third = api.auto_joints(twice, 6, TWICE_FRAMES, rest_frame=0.0,
                                    max_influences=3, iterations=2)
            check("a mesh the tool did not make is left alone", cmds.objExists(decoy),
                  'the decoy was deleted' if not cmds.objExists(decoy) else '')

    # --- pinning the joints to the mesh ---------------------------------------- #
    #
    # The other half of driving a face: blendShapes on the original, joints riding on
    # its surface, skin on a copy. Built so the right answer is arithmetic - the
    # blendShape target is the WHOLE mesh moved by a known vector, so a joint that
    # follows the surface must move by exactly that vector and nothing else.
    #
    # The joints hang off a group that is rotated and moved, because
    # `offsetParentMatrix` is in PARENT space: a pin that works on a joint parented to
    # the world and not on one under a rotated group is the bug this catches.
    cmds.file(new=True, force=True)
    import maya.api.OpenMaya as _om

    SHIFT = (2.0, 3.0, -1.0)
    skin_plane = cmds.polyPlane(width=10.0, height=10.0, subdivisionsX=8, subdivisionsY=8,
                                axis=(0, 1, 0), name='pinPlane')[0]
    moved = cmds.duplicate(skin_plane, name='pinPlane_moved')[0]
    cmds.move(SHIFT[0], SHIFT[1], SHIFT[2], moved, relative=True)
    cmds.makeIdentity(moved, apply=True, translate=True, rotate=True, scale=True)
    pin_blend = cmds.blendShape(moved, skin_plane, name='pinBlend')[0]
    cmds.delete(moved)
    cmds.setKeyframe(pin_blend + '.pinPlane_moved', value=0.0, t=0)
    cmds.setKeyframe(pin_blend + '.pinPlane_moved', value=1.0, t=1)

    holder = cmds.group(empty=True, name='pinJointGroup')
    cmds.xform(holder, translation=(5.0, -2.0, 1.0), rotation=(0.0, 0.0, 30.0))
    cmds.select(clear=True)
    near = cmds.joint(name='pin_near')
    cmds.select(clear=True)
    deep = cmds.joint(name='pin_deep')
    cmds.parent(near, deep, holder)
    cmds.xform(near, worldSpace=True, translation=(1.0, 0.05, -2.0))
    cmds.xform(deep, worldSpace=True, translation=(-2.0, 3.0, 1.0))

    cmds.currentTime(0)
    def _world(node):
        return _om.MPoint(cmds.xform(node, q=True, worldSpace=True, translation=True))

    rest_near = _world(near)
    rest_deep = _world(deep)
    rest_orient = cmds.xform(near, q=True, worldSpace=True, rotation=True)

    pinned = contract('pin_joints', api.pin_joints(skin_plane, [near, deep], rest_frame=0.0))
    check('pin_joints succeeds', pinned['ok'], pinned['message'])
    if pinned['ok']:
        facts = pinned['result']
        check('it pins through the blendShape output, not the shape itself',
              'pinBlend' in facts['reads'], facts['reads'])
        check('the joints do not move when they are pinned',
              facts['worst_rest_drift'] < 1e-6, str(facts['worst_rest_drift']))
        check('and the pins land on the points they were made for',
              facts['worst_pin_mismatch'] < 1e-4, str(facts['worst_pin_mismatch']))
        check('a joint sitting well off the surface is named',
              facts['far_from_surface'] == ['pin_deep'], str(facts['far_from_surface']))
        check('pinning reports no cycles', facts['cycles'] == 0, str(facts['cycles']))

        cmds.currentTime(1)
        drift_near = _world(near) - (rest_near + _om.MVector(*SHIFT))
        drift_deep = _world(deep) - (rest_deep + _om.MVector(*SHIFT))
        out['pin'] = {'near': drift_near.length(), 'deep': drift_deep.length(),
                      'reads': facts['reads'],
                      'rest_drift': facts['worst_rest_drift']}
        check('a pinned joint follows the surface it sits on, in world space',
              drift_near.length() < 1e-4, str(drift_near.length()))
        check('and so does one under a rotated, moved parent',
              drift_deep.length() < 1e-4, str(drift_deep.length()))
        check('position-only pinning leaves the joint\'s orientation alone',
              max(abs(a - b) for a, b in
                  zip(cmds.xform(near, q=True, worldSpace=True, rotation=True),
                      rest_orient)) < 1e-6,
              str(cmds.xform(near, q=True, worldSpace=True, rotation=True)))

        # The joint's own channels have to keep working - a rigger's offsets and an
        # animator's keys both live there.
        cmds.currentTime(0)
        parent_matrix = _om.MMatrix(cmds.getAttr(holder + '.worldMatrix[0]'))
        was = cmds.getAttr(near + '.translateY')
        cmds.setAttr(near + '.translateY', was + 0.5)
        expected = rest_near + (_om.MVector(0.0, 0.5, 0.0) * parent_matrix)
        check('a pinned joint still answers to its own translate',
              (_world(near) - expected).length() < 1e-5,
              str((_world(near) - expected).length()))
        cmds.setAttr(near + '.translateY', was)

    # Pinning again replaces the network instead of stacking a second one on it.
    counts = {kind: len(cmds.ls(type=kind) or [])
              for kind in ('uvPin', 'multMatrix', 'pickMatrix')}
    again = contract('pin_joints (2nd run)',
                     api.pin_joints(skin_plane, [near, deep], rest_frame=0.0))
    check('pinning a second time works', again['ok'], again['message'])
    if again['ok']:
        check('and leaves the same number of nodes behind',
              counts == {kind: len(cmds.ls(type=kind) or [])
                         for kind in ('uvPin', 'multMatrix', 'pickMatrix')},
              '{} then {}'.format(counts, {kind: len(cmds.ls(type=kind) or [])
                                           for kind in ('uvPin', 'multMatrix',
                                                        'pickMatrix')}))
        check('and says it replaced the pins that were there',
              len(again['result']['replaced']) == 2, str(again['result']['replaced']))

    # Unpinning puts back exactly what was there, including an offset somebody else baked.
    cmds.currentTime(0)
    BAKED = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.7, 0.0, 0.0, 1.0]
    api.unpin_joints(joints=[near])
    cmds.setAttr(near + '.offsetParentMatrix', BAKED, type='matrix')
    api.pin_joints(skin_plane, [near], rest_frame=0.0)
    lifted = contract('unpin_joints', api.unpin_joints(mesh=skin_plane))
    check('unpinning works', lifted['ok'], lifted['message'])
    if lifted['ok']:
        check('and takes the pin nodes with it',
              not (cmds.ls(type='uvPin') or []) and not (cmds.ls('*_pinPick') or []),
              str((cmds.ls(type='uvPin') or []) + (cmds.ls('*_pinPick') or [])))
        check('and puts back an offsetParentMatrix that was there before',
              max(abs(a - b) for a, b in
                  zip(cmds.getAttr(near + '.offsetParentMatrix'), BAKED)) < 1e-9,
              str(cmds.getAttr(near + '.offsetParentMatrix')))
        cmds.setAttr(near + '.offsetParentMatrix',
                     [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                      0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0], type='matrix')

    # Rotation mode: still exact at the rest frame, and still follows.
    cmds.currentTime(0)
    turning = contract('pin_joints (rotate)',
                       api.pin_joints(skin_plane, [near], rotate=True, rest_frame=0.0))
    check('pinning with rotation succeeds', turning['ok'], turning['message'])
    if turning['ok']:
        check('and still does not move the joint at the rest frame',
              turning['result']['worst_rest_drift'] < 1e-6,
              str(turning['result']['worst_rest_drift']))
        cmds.currentTime(1)
        check('and still follows the surface',
              (_world(near) - (rest_near + _om.MVector(*SHIFT))).length() < 1e-4,
              str((_world(near) - (rest_near + _om.MVector(*SHIFT))).length()))
        api.unpin_joints(mesh=skin_plane)

    # Refusals.
    #
    # A skin the pinned joint drives is only a cycle when the pin would READ it. On the
    # production layout - blendShape, then a skinCluster the pinned joints deform - the
    # pin reads the blendShape's output, which nothing downstream feeds, so that has to
    # keep working. Pinning to a mesh whose only deformer is that skin must not.
    cmds.currentTime(0)
    cmds.skinCluster(near, skin_plane, toSelectedBones=True, name='pinPlaneSkin')
    allowed = contract('pin_joints (skin below the blendShape)',
                       api.pin_joints(skin_plane, [near], rest_frame=0.0))
    check('a skinCluster BELOW the blendShape the pin reads is not a cycle',
          allowed['ok'], allowed['message'])
    if allowed['ok']:
        check('and Maya agrees there is no cycle', allowed['result']['cycles'] == 0,
              str(allowed['result']['cycles']))
    api.unpin_joints(mesh=skin_plane)
    cmds.delete('pinPlaneSkin')

    bare = cmds.polyPlane(width=10.0, height=10.0, subdivisionsX=4, subdivisionsY=4,
                          axis=(0, 1, 0), name='pinPlaneBare')[0]
    cmds.skinCluster(near, bare, toSelectedBones=True, name='pinPlaneBareSkin')
    refused = contract('pin_joints (cycle)', api.pin_joints(bare, [near], rest_frame=0.0))
    check('pinning a joint to geometry whose only deformer is that joint\'s skin is refused',
          not refused['ok'], refused['message'])
    check('and the refusal says the word cycle',
          'cycle' in (refused['message'] or '').lower(), refused['message'])
    cmds.delete(bare)

    cmds.setAttr(near + '.offsetParentMatrix', BAKED, type='matrix')
    holder_mult = cmds.createNode('multMatrix', name='somebody_elses_offset')
    cmds.connectAttr(holder_mult + '.matrixSum', near + '.offsetParentMatrix')
    refused = contract('pin_joints (occupied offset)',
                       api.pin_joints(skin_plane, [near], rest_frame=0.0))
    check('an offsetParentMatrix somebody else drives is not overwritten',
          not refused['ok'], refused['message'])
    check('and it is still connected to what it was',
          (cmds.listConnections(near + '.offsetParentMatrix', source=True,
                                destination=False) or []) == [holder_mult],
          str(cmds.listConnections(near + '.offsetParentMatrix', source=True,
                                   destination=False)))

    refused = contract('pin_joints (no mesh)', api.pin_joints(holder, [near]))
    check('pinning to something that is not a mesh is refused',
          not refused['ok'], refused['message'])

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
