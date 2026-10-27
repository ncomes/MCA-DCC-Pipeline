"""
Build the mcaMeshTiler sample scene.

How to run it
-------------
**From Maya's script editor**, in a Python tab, either:

    File > Open Script... this file, then hit the execute button. That runs the
    whole file, which ends by calling build().

or paste these two lines and run them::

    import sys; sys.path.append(r'<this folder>')
    import build_sample; build_sample.build()

Typing a bare ``build()`` will not work - ``build`` lives in this module, so it
is ``build_sample.build()`` unless you have run the whole file. If you have run
the file once already, re-running it needs a reload::

    import importlib, build_sample
    importlib.reload(build_sample); build_sample.build()

**From a shell**, point mayapy at it. It initialises standalone itself.

Start from an empty scene. Nothing here cleans up after a previous run, so a
second run on the same scene makes a second set of everything.

What it builds
--------------
Three setups, side by side along X:

1. **Scales, quad target.** A low-poly torus with a scale tile on every face.
   The tiles sit on the torus's *limit surface*, not its cage, which is why they
   curve smoothly across a mesh that is visibly faceted underneath.
2. **Scales, triangulated target.** The same torus, triangulated, with the same
   tile. Catmull-Clark makes three quads out of a triangle, so each face gets
   three tiles and the silhouette still matches setup 1. The tool this replaces
   produced an empty mesh here, with no error.
3. **Plates, n-gon target.** A cylinder - its caps are n-gons - with a thick
   plate tile lifted off the surface, and four faces turned a quarter turn each
   so you can see what `faceRotation` does.

Each target is left in the scene as a reference-display cage next to its tiles,
so you can drag a vertex and watch the tiles follow. The tile meshes themselves
are parked below the setups in ``tiles_source``.

This file is also the shortest honest documentation of the API: everything here
goes through :mod:`mca.mya.tools.meshtiler.meshtiler_api`, and nothing reaches
into the node directly.
"""

# python imports
import math

# software specific imports
import maya.cmds as cmds

# MCA python imports
from mca.mya.tools.meshtiler import meshtiler_api

#: How far apart the three setups sit.
SPACING = 16.0


def _checker_shader(name, color_a, color_b):
    """
    A lambert with a checker on it.

    The checker is the point: every tile lands on the same patch of texture, so
    if the UVs came across each tile carries the same little checkerboard. If
    they did not, you get flat colour and you can see that at a glance.

    :param str name: Base name for the nodes.
    :param tuple color_a: First checker colour.
    :param tuple color_b: Second checker colour.
    :return: The shading engine.
    :rtype: str
    """

    shader = cmds.shadingNode('lambert', asShader=True, name='{}_lambert'.format(name))
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name='{}_SG'.format(name))
    cmds.connectAttr(shader + '.outColor', engine + '.surfaceShader')

    checker = cmds.shadingNode('checker', asTexture=True, name='{}_checker'.format(name))
    placement = cmds.shadingNode('place2dTexture', asUtility=True,
                                 name='{}_place2d'.format(name))
    for attribute in ('outUV', 'outUvFilterSize'):
        target = 'uvCoord' if attribute == 'outUV' else 'uvFilterSize'
        cmds.connectAttr('{}.{}'.format(placement, attribute),
                         '{}.{}'.format(checker, target))
    cmds.connectAttr(checker + '.outColor', shader + '.color')
    cmds.setAttr(checker + '.color1', *color_a, type='double3')
    cmds.setAttr(checker + '.color2', *color_b, type='double3')
    return engine


def _cage_shader():
    """
    A dark, see-through lambert for the target cages.

    :return: The shading engine.
    :rtype: str
    """

    shader = cmds.shadingNode('lambert', asShader=True, name='cage_lambert')
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name='cage_SG')
    cmds.connectAttr(shader + '.outColor', engine + '.surfaceShader')
    cmds.setAttr(shader + '.color', 0.18, 0.18, 0.20, type='double3')
    cmds.setAttr(shader + '.transparency', 0.62, 0.62, 0.62, type='double3')
    return engine


def _scale_tile(name):
    """
    A rounded scale, authored flat in XZ with Y off the surface.

    That is the tile convention, and it is the one thing about this tool that was
    previously true but written down nowhere.

    :param str name: Name for the transform.
    :return: The tile transform.
    :rtype: str
    """

    tile = cmds.polyPlane(width=1.0, height=1.0, sx=4, sy=4, ch=False, name=name)[0]

    # Dome it, and taper the trailing edge, so the tiles overlap like scales
    # rather than tiling flat like floor tiles.
    for index in range(cmds.polyEvaluate(tile, vertex=True)):
        x, _, z = cmds.pointPosition('{}.vtx[{}]'.format(tile, index), local=True)
        across = 1.0 - min(1.0, abs(x) * 2.0)
        along = (z + 0.5)
        height = 0.14 * math.sin(math.pi * along) * across
        width = 1.0 - 0.45 * along
        cmds.xform('{}.vtx[{}]'.format(tile, index), objectSpace=True,
                   translation=(x * width, height, z))

    cmds.polySoftEdge(tile, angle=180, ch=False)
    return tile


def _plate_tile(name):
    """
    A thick plate, the same way up as the scale.

    :param str name: Name for the transform.
    :return: The tile transform.
    :rtype: str
    """

    tile = cmds.polyCube(width=0.86, height=0.22, depth=0.86, ch=False, name=name)[0]
    # Sit it on the surface rather than half sunk into it.
    cmds.xform(tile, objectSpace=True, translation=(0.0, 0.11, 0.0))
    cmds.makeIdentity(tile, apply=True, translate=True)
    cmds.polySoftEdge(tile, angle=30, ch=False)
    return tile


def _as_cage(target, engine):
    """
    Show a target as a see-through cage that you can still grab.

    The whole argument for this node is that the tiles follow the smooth surface
    the cage implies rather than the cage itself, which you cannot see unless the
    cage is visible underneath them.

    The first version of this used `overrideDisplayType` 2 (reference), which
    looks right and is **unselectable** - so the one thing the sample is for,
    dragging a vertex and watching the tiles follow, could not be done. Both
    template and reference display block selection. A transparent shader gets the
    same read and leaves the mesh in your hands.

    :param str target: The target transform.
    :param str engine: The see-through shading engine to put it in.
    """

    cmds.sets(target, edit=True, forceElement=engine)


def _report(label, response):
    """
    :param str label: What was being built.
    :param dict response: An ``ok/result/message`` response.
    :return: The result.
    :raises RuntimeError: If the call failed.
    """

    if not response['ok']:
        raise RuntimeError('{}: {}'.format(label, response['message']))
    print('mcaMeshTiler sample - {}: {}'.format(label, response['message']))
    return response['result']


def build():
    """
    Build the whole sample scene.

    :return: The three group transforms.
    :rtype: list
    """

    available, reason = meshtiler_api.plugin_is_available()
    if not available:
        raise RuntimeError(reason)

    scales = _scale_tile('scale_tile')
    plates = _plate_tile('plate_tile')
    cmds.sets(scales, edit=True, forceElement=_checker_shader(
        'scale', (0.10, 0.35, 0.28), (0.16, 0.55, 0.42)))
    cmds.sets(plates, edit=True, forceElement=_checker_shader(
        'plate', (0.38, 0.30, 0.26), (0.55, 0.45, 0.38)))

    cage = _cage_shader()
    groups = []

    # --- 1. quads ------------------------------------------------------------- #
    torus = cmds.polyTorus(radius=4.0, sectionRadius=1.6, sx=14, sy=8,
                           ch=False, name='quad_target')[0]
    built = _report('scales on a quad target',
                    meshtiler_api.tile_mesh(scales, torus, name='quad_scales',
                                            area_scale=0.6, height=1.0))
    groups.append(cmds.group(torus, str(built['transform']), name='setup1_quads'))
    _as_cage(torus, cage)

    # --- 2. triangles ---------------------------------------------------------- #
    #
    # The same torus and the same tile. The original dropped every face that did
    # not have exactly four vertices, so this produced nothing at all.
    tri_torus = cmds.polyTorus(radius=4.0, sectionRadius=1.6, sx=14, sy=8,
                               ch=False, name='triangle_target')[0]
    cmds.polyTriangulate(tri_torus, ch=False)
    built = _report('scales on a triangulated target',
                    meshtiler_api.tile_mesh(scales, tri_torus, name='triangle_scales',
                                            area_scale=0.6, height=1.0))
    groups.append(cmds.group(tri_torus, str(built['transform']), name='setup2_triangles'))
    _as_cage(tri_torus, cage)

    # --- 3. n-gons, height and rotation ----------------------------------------- #
    cylinder = cmds.polyCylinder(radius=3.0, height=6.0, sx=12, sy=3,
                                 ch=False, name='ngon_target')[0]
    built = _report('plates on an n-gon target',
                    meshtiler_api.tile_mesh(plates, cylinder, name='ngon_plates',
                                            height=1.0, height_offset=0.12,
                                            area_scale=1.0))
    tiler = built['tiler']
    # Four faces turned a quarter turn each, so the difference is visible.
    _report('turning four tiles',
            meshtiler_api.set_face_rotation(tiler, {2: 1, 3: 1, 14: 1, 15: 1}))
    groups.append(cmds.group(cylinder, str(built['transform']), name='setup3_ngons'))
    _as_cage(cylinder, cage)

    for index, group in enumerate(groups):
        cmds.setAttr(group + '.translateX', index * SPACING)

    # Park the tiles below, where they are out of the way but still editable -
    # change one and every copy of it changes.
    source = cmds.group(scales, plates, name='tiles_source')
    cmds.setAttr(source + '.translateY', -8.0)
    cmds.setAttr(source + '.translateZ', 0.0)
    cmds.setAttr(plates + '.translateX', 2.0)

    try:
        cmds.select(clear=True)
        cmds.viewFit(all=True)
    except Exception:
        # No viewport under mayapy. Not worth failing over.
        pass

    made = groups + [source]
    print('mcaMeshTiler sample - built {}. Select a target cage and drag a vertex; '
          'the tiles follow.'.format(', '.join(made)))
    return made


if __name__ == '__main__':
    build()
