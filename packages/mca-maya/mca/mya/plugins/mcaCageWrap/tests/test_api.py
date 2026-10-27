"""Exercise the Python API in Maya: the cage builder, the bind, the report, baking to
a skin, and the refusals. The maths is covered off-DCC and the node by test_node.py, so
this is about the layer an artist and a script actually touch."""

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

import maya.standalone as _standalone  # noqa: E402
_standalone.initialize(name='python')
import maya.cmds as _cmds  # noqa: E402
_VERSION = _cmds.about(version=True).split()[0]
RESULT = _result_path('mcaCageWrap_api.json')

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))
    print('{}  {}'.format('ok  ' if condition else 'FAIL', label))


def contract(label, response):
    """Every public call answers in the same shape, success or not."""
    ok = (isinstance(response, dict) and set(response) == {'ok', 'result', 'message'}
          and isinstance(response['ok'], bool) and isinstance(response['message'], str))
    check('{} answers with the ok/result/message contract'.format(label), ok,
          'got {!r}'.format(type(response)))
    return response


try:
    import maya.cmds as cmds
    _add_framework_paths(_VERSION)
    from mca.mya.tools.cagewrap import cagewrap_api as api

    check('the plug-in loads', api.plugin_is_available()[0], api.plugin_is_available()[1])

    def points(mesh):
        flat = cmds.xform(mesh + '.vtx[*]', q=True, worldSpace=True, translation=True)
        return [tuple(flat[index:index + 3]) for index in range(0, len(flat), 3)]

    def worst(got, want):
        return max(math.dist(a, b) for a, b in zip(got, want))

    # --- building a cage ------------------------------------------------------- #
    cmds.file(new=True, force=True)
    blob = cmds.polySphere(radius=2.0, subdivisionsX=20, subdivisionsY=20, name='blob')[0]
    cmds.polyMoveVertex(blob + '.vtx[80:140]', localTranslate=(0, 0, 0.8),
                        constructionHistory=False)

    built = contract('cage_from_mesh', api.cage_from_mesh(blob, faces=120))
    check('a cage is built', built['ok'], built['message'])
    if built['ok']:
        made = built['result']
        out['cage'] = made
        check('it is closed', made['closed'], str(made['border_edges']))
        check('and it contains the whole mesh', made['points_outside'] == 0,
              str(made['points_outside']))

        # **Containing the mesh is not the same as being a usable cage, and for a long
        # time nothing here said so.** A sphere of radius 200 contains a man perfectly.
        # The growth loop used to assume that pushing harder always put more of the mesh
        # inside; it does not, because a uniform offset folds through itself wherever the
        # concave radius is smaller than the offset. On a human body that ran away to a
        # 92-unit push and a cage sitting a median 67 units off 38-unit-deep geometry -
        # closed, whole mesh inside, and worthless. Every check above passed on it.
        check('and it hugs the mesh rather than merely swallowing it',
              made['fit_fraction'] < api.LOOSE_CAGE_FRACTION,
              '{:.4g} units median, {:.2%} of the diagonal'.format(
                  made['fit_median'], made['fit_fraction']))
        check('and the push it chose is a fraction of the mesh, not a multiple of it',
              made['offset'] < api._diagonal(blob) * 0.1, str(made['offset']))
        check('and it is roughly the size asked for', 40 <= made['faces'] <= 400,
              str(made['faces']))
        check('and it is tagged, so a second run replaces it rather than piling up',
              cmds.attributeQuery(api.CAGE_TAG, node=made['cage'], exists=True))

        again = api.cage_from_mesh(blob, faces=120)
        check('building twice leaves one cage, not two',
              again['ok'] and len(cmds.ls('blob_cage*', transforms=True) or []) == 1,
              str(cmds.ls('blob_cage*', transforms=True)))

    # --- a BRANCHING skeleton, which is where the bone cage went wrong ---------- #
    #
    # Every bone-cage check before this used a SINGLE chain - a tapered tentacle, a prop on
    # one bone - and on a single chain "every point belongs to this chain" happens to be
    # true, so nothing noticed that `_bone_vertices` assigned the whole mesh to whichever
    # chain it was handed. On a 40-chain character every chain owned all 16,747 points and
    # every ring came out between 145 and 168 units on a body 38 units deep: forty beach
    # balls stacked on a man. The branching test that did exist asserted one cage per chain
    # and where each one starts. It never looked at a radius.
    cmds.select(clear=True)
    spine = [cmds.joint(p=(0, 0, 0)), cmds.joint(p=(0, 6, 0))]
    arms = []
    for side in (-1, 1):
        cmds.select(spine[-1])
        arms.append([cmds.joint(p=(side * 3, 7, 0)), cmds.joint(p=(side * 9, 7, 0))])
    body = cmds.polyCylinder(name='torso', radius=2.0, height=8, axis=(0, 1, 0),
                             subdivisionsX=12, subdivisionsY=8, constructionHistory=False)[0]
    cmds.move(0, 3, 0, body)
    limbs = [body]
    for side in (-1, 1):
        limb = cmds.polyCylinder(name='limb', radius=0.7, height=7, axis=(1, 0, 0),
                                 subdivisionsX=10, subdivisionsY=8,
                                 constructionHistory=False)[0]
        cmds.move(side * 5.5, 7, 0, limb)
        limbs.append(limb)
    figure = cmds.polyUnite(limbs, name='figure', constructionHistory=False)[0]
    every_joint = spine + arms[0] + arms[1]
    cmds.skinCluster(every_joint, figure, tsb=True, maximumInfluences=4)

    branched = contract('cage_from_skeleton (branching)', api.cage_from_skeleton(figure))
    check('a branching skeleton builds a cage per chain', branched['ok'], branched['message'])
    if branched['ok']:
        pieces = [c for c in (branched['result'].get('cages') or []) if isinstance(c, dict)]
        check('more than one chain means more than one cage', len(pieces) > 1, str(len(pieces)))

        # The real assertion: an ARM ring is the size of an arm, not the size of the figure.
        widest = max((c.get('radius_largest') or 0.0) for c in pieces)
        span = api._diagonal(figure)
        check('no ring is as big as the whole figure',
              widest < span * 0.35, '{:.2f} against a {:.2f} diagonal'.format(widest, span))

        # And the cause, asserted directly: a chain must not own the whole mesh.
        shape = api._mesh_shape(figure)
        total = cmds.polyEvaluate(figure, vertex=True)
        worst_share = 0.0
        for chain in api.bone_chains(every_joint):
            owned = api._bone_vertices(shape, chain, skeleton=every_joint)
            worst_share = max(worst_share, sum(len(v) for v in owned.values()) / float(total))
        check('and no chain claims every vertex in the mesh', worst_share < 0.9,
              '{:.0%} of the mesh went to one chain'.format(worst_share))
    cmds.delete(figure)
    for joint in spine:
        if cmds.objExists(joint):
            cmds.delete(joint)

    # --- the growth loop, on its own ------------------------------------------- #
    #
    # Pushed straight at the failure: a shape with a concavity tighter than the push it
    # will be offered. The old loop extrapolated from the worst point and compounded;
    # this one measures a ladder and keeps the best, so it is allowed to choose nothing.
    pinched = cmds.polySphere(name='pinch', radius=6, subdivisionsX=24, subdivisionsY=24,
                              constructionHistory=False)[0]
    cmds.select(pinched + '.vtx[200:260]', replace=True)
    cmds.polyMoveVertex(pinched + '.vtx[200:260]', localTranslate=(0, 0, -4.5),
                        constructionHistory=False)
    cmds.select(clear=True)
    shell = cmds.duplicate(pinched, name='pinch_shell', returnRootsOnly=True)[0]
    cmds.polyRetopo(shell, constructionHistory=False, targetFaceCount=120)
    was_outside, was_worst = api.points_outside(pinched, shell)
    pushed, left, worst_left, tried = api.grow_to_contain(pinched, shell,
                                                          api._diagonal(pinched) * 0.02, 3)
    check('the growth loop tries several distances rather than extrapolating from one',
          tried >= 4, str(tried))
    check('and it never leaves the cage worse than it found it',
          (left, worst_left) <= (was_outside, was_worst),
          '{} -> {} outside'.format(was_outside, left))
    check('and the distance it settles on stays near the shape',
          pushed < api._diagonal(pinched) * 0.1, str(pushed))
    cmds.delete(pinched, shell)

    # --- wrapping -------------------------------------------------------------- #
    cage = api.cage_from_mesh(blob, faces=120)['result']['cage']
    before = points(blob)
    wrapped = contract('wrap', api.wrap(blob, cage=cage))
    check('the mesh wraps to the cage', wrapped['ok'], wrapped['message'])
    if wrapped['ok']:
        result = wrapped['result']
        out['wrap'] = {key: value for key, value in result.items() if key != 'cage_built'}
        node = result['deformer']
        check('binding does not move the mesh', worst(points(blob), before) < 1e-4,
              str(worst(points(blob), before)))
        check('and it says so itself', result['worst_rest_error'] < 1e-5,
              str(result['worst_rest_error']))
        check('no point is left outside the cage', result['points_outside'] == 0,
              str(result['points_outside']))
        check('a hidden rest cage is made and tagged',
              cmds.objExists(result['rest_cage']) and
              cmds.attributeQuery(api.REST_TAG, node=result['rest_cage'], exists=True))
        check('and it is hidden, because it is bookkeeping rather than art',
              not cmds.getAttr(result['rest_cage'] + '.visibility'))

        # It follows the cage.
        cmds.move(3.0, 1.0, -2.0, cage, relative=True)
        cmds.dgeval(blob + '.outMesh')
        want = [(x + 3.0, y + 1.0, z - 2.0) for x, y, z in before]
        moved = worst(points(blob), want)
        out['translation'] = moved
        check('moving the cage moves the mesh with it', moved < 1e-4, str(moved))
        cmds.move(-3.0, -1.0, 2.0, cage, relative=True)

        # Squash it, and see that stretch changes the answer.
        cmds.scale(1.0, 0.6, 1.0, cage, relative=True)
        cmds.dgeval(blob + '.outMesh')
        squashed = points(blob)
        cmds.setAttr(node + '.stretch', 1.0)
        cmds.dgeval(blob + '.outMesh')
        thickened = points(blob)
        difference = worst(squashed, thickened)
        out['stretch_difference'] = difference
        check('stretch changes how thick the squashed shape is', difference > 1e-3,
              str(difference))
        cmds.setAttr(node + '.stretch', 0.0)
        cmds.scale(1.0, 1.0 / 0.6, 1.0, cage, relative=True)

        reported = contract('report', api.report(node))
        check('the report reads back what the bind measured',
              reported['ok'] and reported['result']['points_outside'] == 0,
              reported['message'])

        # --- grouping a finished setup for shipping ---------------------------- #
        #
        # The mistake that broke three of the four setups in our own sample scene: group
        # the mesh and the cage, leave the hidden rest cage behind at the root, and from
        # then on the group's own transform reads as the cage having moved - so the mesh
        # follows it on top of its own transform and flies off. Reported rather than
        # refused, because it is legal and occasionally deliberate.
        check('a fresh wrap has its cage and rest cage under one parent',
              not reported['result']['parented_apart'], reported['message'])

        rest_name = result['rest_cage'].split('|')[-1]
        shipped = cmds.group(blob, cage, name='shipped_without_the_rest_cage')
        apart = api.report(node)
        check('grouping the mesh and cage without the rest cage is called out',
              apart['result']['parented_apart'], apart['message'])
        check('and the message says what to do about it',
              'same parent' in apart['message'], apart['message'])
        cmds.parent(rest_name, shipped)
        together = api.report(node)
        check('bringing the rest cage into the group settles it',
              not together['result']['parented_apart'], together['message'])
        cmds.parent(blob, cage, rest_name, world=True)
        cmds.delete(shipped)

        check('find_wraps finds it', api.find_wraps(blob) == [node] or
              node in api.find_wraps(blob), str(api.find_wraps(blob)))

        # --- wrapping twice, and removing ------------------------------------- #
        rest_cages = len(cmds.ls('*_rest', transforms=True) or [])
        second = api.wrap(blob, cage=cage)
        check('wrapping again works', second['ok'], second['message'])
        check('and does not leave a second rest cage behind',
              len(cmds.ls('*_rest', transforms=True) or []) == rest_cages,
              str(cmds.ls('*_rest', transforms=True)))

        removed = contract('remove', api.remove(blob))
        check('removing takes the deformers off', removed['ok'], removed['message'])
        check('and the rest cages with them',
              not (cmds.ls('*_rest', transforms=True) or []),
              str(cmds.ls('*_rest', transforms=True)))
        check('but leaves the cage the artist has been animating', cmds.objExists(cage))
        check('and the mesh goes back to where it started',
              worst(points(blob), before) < 1e-4, str(worst(points(blob), before)))

    # --- a cage from the skeleton ---------------------------------------------- #
    #
    # The case it exists for: a chain of bones down a tapered limb. A cage built from the
    # shape has a point wherever the model has detail; this one has a ring where each joint
    # is, which is where somebody posing it looks for a handle.
    cmds.file(new=True, force=True)
    tube = cmds.polyCylinder(radius=1.0, height=12.0, subdivisionsX=20, subdivisionsY=40,
                             subdivisionsZ=1, axis=(0, 1, 0), name='tentacle',
                             constructionHistory=False)[0]
    for vertex in range(cmds.polyEvaluate(tube, vertex=True)):
        x, y, z = cmds.pointPosition('{}.vtx[{}]'.format(tube, vertex), world=True)
        taper = max(1.0 - 0.06 * (y + 6.0), 0.1)
        cmds.xform('{}.vtx[{}]'.format(tube, vertex), worldSpace=True,
                   translation=(x * taper, y, z * taper))
    chain = []
    cmds.select(clear=True)
    for index in range(6):
        chain.append(cmds.joint(position=(0, -6.0 + index * 2.4, 0),
                                name='spine_{}'.format(index)))
    cmds.skinCluster(chain, tube, toSelectedBones=True, maximumInfluences=3,
                     name='tentacleSkin')

    boned = contract('cage_from_skeleton', api.cage_from_skeleton(tube, sides=6, rings=1))
    check('a cage is built from the skeleton', boned['ok'], boned['message'])
    if boned['ok']:
        cages = boned['result']['cages']
        out['from_skeleton'] = boned['result']
        check('one cage for one chain', len(cages) == 1, str(len(cages)))
        first = cages[0]
        check('it has a ring at every joint, and one between each pair',
              first['rings'] == 11, str(first['rings']))
        check('it is closed', first['closed'], str(first['border_edges']))
        check('and it holds the whole mesh', first['points_outside'] == 0,
              str(first['points_outside']))
        check('the rings follow the taper - the far end is narrower than the near one',
              first['radius_smallest'] < first['radius_largest'] * 0.6,
              '{} against {}'.format(first['radius_smallest'], first['radius_largest']))
        check('it takes the joints from the skin, so nothing had to be named',
              len(first['chain']) == 6, str(first['chain']))

        wrapped = api.wrap(tube, cage=first['cage'])
        check('and the mesh wraps to it', wrapped['ok'], wrapped['message'])
        if wrapped['ok']:
            check('with the bind exact', wrapped['result']['worst_rest_error'] < 1e-5,
                  str(wrapped['result']['worst_rest_error']))
            api.remove(tube)

        # Building again replaces its own cages and leaves a shape-built one alone. Both
        # builders used to write the same tag, so one silently deleted the other - found on
        # a real asset, where a bone cage and a shape cage were wanted side by side.
        shaped = api.cage_from_mesh(tube, faces=80)
        again = api.cage_from_skeleton(tube, sides=6, rings=1)
        check('building from the skeleton again replaces only its own cages',
              again['ok'] and len(cmds.ls('tentacle_boneCage*', transforms=True) or []) == 1,
              str(cmds.ls('tentacle_boneCage*', transforms=True)))
        check('and leaves the cage built from the shape alone',
              shaped['ok'] and cmds.objExists(shaped['result']['cage']),
              shaped['message'])

    # A branching skeleton gives one cage per chain, each starting at the branch.
    cmds.file(new=True, force=True)
    body = cmds.polySphere(radius=3.0, subdivisionsX=16, subdivisionsY=16, name='body',
                           constructionHistory=False)[0]
    cmds.select(clear=True)
    spine = cmds.joint(position=(0, 0, 0), name='spine')
    cmds.joint(position=(2, 1, 0), name='left_1')
    cmds.joint(position=(4, 2, 0), name='left_2')
    cmds.select(spine)
    cmds.joint(position=(-2, 1, 0), name='right_1')
    cmds.joint(position=(-4, 2, 0), name='right_2')
    cmds.skinCluster([spine, 'left_1', 'left_2', 'right_1', 'right_2'], body,
                     toSelectedBones=True, name='bodySkin')

    branched = contract('cage_from_skeleton (branching)',
                        api.cage_from_skeleton(body, sides=4, rings=0))
    check('a branching skeleton gives one cage per chain', branched['ok'],
          branched['message'])
    if branched['ok']:
        cages = branched['result']['cages']
        check('two arms, two cages', len(cages) == 2, str(len(cages)))
        check('and each chain starts at the branch joint, so the tubes meet there',
              all(entry['chain'][0] == 'spine' for entry in cages),
              str([entry['chain'] for entry in cages]))
        check('both closed', all(entry['closed'] for entry in cages))

    check('chains are split at branches',
          len(api.bone_chains([spine, 'left_1', 'left_2', 'right_1', 'right_2'])) == 2)
    check('and a straight run is one chain',
          len(api.bone_chains([spine, 'left_1', 'left_2'])) == 1)

    # --- refusals -------------------------------------------------------------- #
    cmds.file(new=True, force=True)
    mesh = cmds.polySphere(radius=1.0, name='ball')[0]
    holed = cmds.polyCube(width=3.0, height=3.0, depth=3.0, name='holedCage')[0]
    cmds.delete(holed + '.f[0]')
    refused = contract('wrap (open cage)', api.wrap(mesh, cage=holed))
    check('an open cage is refused', not refused['ok'], refused['message'])
    check('and the refusal says how to fix it',
          'closed' in (refused['message'] or '') or 'border' in (refused['message'] or ''),
          refused['message'])

    refused = contract('wrap (no mesh)', api.wrap('not_a_thing'))
    check('a mesh that does not exist is refused', not refused['ok'], refused['message'])

    refused = contract('report (wrong node)', api.report(mesh))
    check('asking a mesh for a bind report is refused', not refused['ok'], refused['message'])

    refused = contract('bake_to_skin (no wrap)', api.bake_to_skin(mesh, [0.0, 1.0]))
    check('baking a mesh with no cage wrap on it is refused', not refused['ok'],
          refused['message'])

    # A "cage" as dense as the mesh. This is the one that cost real time: a retopology
    # silently failed on a production prop, the builder handed back a full-resolution
    # duplicate, and binding 13,568 points to 27,085 cage elements would have quietly
    # allocated 1.4 GB.
    #
    # The mesh has to be big enough for the PRODUCT to matter, and that is the point of the
    # guard. The first version of this check duplicated a 382-point sphere and expected a
    # refusal; 382 points on 764 cage elements is 1.2 MB, which is nothing, and refusing it
    # would have been the guard being wrong rather than right.
    heavy = cmds.polySphere(radius=1.0, subdivisionsX=90, subdivisionsY=90, name='heavy',
                            constructionHistory=False)[0]
    dense = cmds.duplicate(heavy, name='pretend_cage', returnRootsOnly=True)[0]
    refused = contract('wrap (a cage as dense as the mesh)', api.wrap(heavy, cage=dense))
    check('a cage as dense as the mesh is refused', not refused['ok'], refused['message'])
    check('and the refusal says what it would have cost',
          'MB' in (refused['message'] or ''), refused['message'])
    cmds.delete(dense, heavy)

    refused = contract('cage_from_skeleton (no skeleton)',
                       api.cage_from_skeleton(mesh))
    check('building from a skeleton that is not there is refused', not refused['ok'],
          refused['message'])
    check('and it points at the other builder',
          'cage_from_mesh' in (refused['message'] or ''), refused['message'])

    # --- baking to a skin ------------------------------------------------------ #
    #
    # The whole point of the feature: a cage deformation an engine cannot run, turned
    # into joints and weights it can.
    cmds.file(new=True, force=True)
    tube = cmds.polyCylinder(radius=1.0, height=8.0, subdivisionsX=12, subdivisionsY=16,
                             subdivisionsZ=0, axis=(0, 1, 0), name='tube')[0]
    cage = cmds.polyCube(width=3.0, height=9.0, depth=3.0, subdivisionsY=3, name='tubeCage')[0]
    wrapped = api.wrap(tube, cage=cage)
    check('the tube wraps to its cage', wrapped['ok'], wrapped['message'])

    if wrapped['ok']:
        # Bend the cage over three frames.
        cmds.currentTime(0)
        for vertex in range(cmds.polyEvaluate(cage, vertex=True)):
            cmds.setKeyframe('{}.vtx[{}]'.format(cage, vertex), t=0)
        cmds.currentTime(2)
        top = [vertex for vertex in range(cmds.polyEvaluate(cage, vertex=True))
               if cmds.pointPosition('{}.vtx[{}]'.format(cage, vertex), world=True)[1] > 2.0]
        for vertex in top:
            cmds.move(2.0, 0, 0, '{}.vtx[{}]'.format(cage, vertex), relative=True)
            cmds.setKeyframe('{}.vtx[{}]'.format(cage, vertex), t=2)

        frames = [0.0, 1.0, 2.0]
        moving, far = api.moving_frames(tube, frames)
        out['moving_frames'] = {'frames': moving, 'worst': far}
        check('the cage deformation actually moves the mesh across those frames',
              len(moving) >= 1 and far > 0.1, str((moving, far)))

        cmds.currentTime(0)
        baked = contract('bake_to_skin', api.bake_to_skin(tube, frames, count=6,
                                                          max_influences=4, iterations=2,
                                                          holdout=[]))
        check('baking to a skin works', baked['ok'], baked['message'])
        if baked['ok']:
            out['bake'] = {'message': baked['message']}
            check('and it leaves a skinCluster behind',
                  bool(cmds.ls(type='skinCluster') or []),
                  str(cmds.ls(type='skinCluster')))
            check('and joints', bool(cmds.ls(type='joint') or []))

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
