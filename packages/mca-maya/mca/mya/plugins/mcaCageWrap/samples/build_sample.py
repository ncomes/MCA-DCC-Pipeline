"""
Build the mcaCageWrap sample scene.

How to run it
-------------
**From Maya's script editor**, in a Python tab, either:

    File > Open Script... this file, then hit execute. That runs the whole file,
    which ends by calling build().

or paste these two lines and run them::

    import sys; sys.path.append(r'<this folder>')
    import build_sample; build_sample.build()

A bare ``build()`` will not work - ``build`` lives in this module, so it is
``build_sample.build()`` unless you have run the whole file. If you have run it once
already, re-running needs a reload::

    import importlib, build_sample
    importlib.reload(build_sample); build_sample.build()

**From a shell**, point mayapy at it. It initialises standalone itself.

Start from an empty scene. Nothing here cleans up after a previous run, so a second run
on the same scene makes a second set of everything.

What it builds
--------------
Four setups, side by side along X. Every one has a keyed cage, so scrubbing the timeline
from frame 0 to 24 shows what it does.

1. **A bend that does not shear.** A tube in a four-ring cage, the top of the cage
   swung over. The thing to look at is the cross-section: it stays round and
   perpendicular to the bend instead of skewing into an ellipse, which is what a
   deformer built from cage positions alone would do. The tube beside it, deformed by a
   plain lattice through the same shape, is there to be compared against.
2. **What the thickness knob does, at both ends.** Two identical balls in identical
   cages, and both cages grown by 1.8. `stretch` is 0 on the left and 1 on the right.
   The right ball grows by exactly 1.8, with the cage. The left one grows by 1.5 -
   because at 0 the term that carries thickness is NOT scaled, so the ball keeps the
   thickness it was modelled with while its position still follows the cage. Measured,
   not asserted: 2.40 -> 3.59 against 2.40 -> 4.32.

   Worth being precise about, because "keeps its thickness" is easy to misread as "does
   not change size at all", and it does change size. What it does not do is inflate.
3. **A cage built by the tool.** A lumpy blob nobody modelled a cage for. The cage is
   whatever `cage_from_mesh` made, and it is symmetrical because it was asked to be.
4. **Cloth from a cage.** A dense sheet driven by a nine-point cage - the case where
   the cage is doing the animating and the mesh is far too heavy to touch.

Each cage is left as a see-through wireframe you can select and drag.

This file is also the shortest honest documentation of the API: everything goes through
:mod:`mca.mya.tools.cagewrap.cagewrap_api`, and nothing reaches into the node directly.
"""

# python imports
import math

# software specific imports
import maya.cmds as cmds

# MCA python imports
from mca.mya.tools.cagewrap import cagewrap_api

#: How far apart the setups sit.
SPACING = 14.0

#: The frame the poses land on. Frame 0 is always the rest pose.
END_FRAME = 24.0


def _report(what, response):
    """
    Print an API response the way the window would show it.

    :param str what: What was being done.
    :param dict response: The response.
    :return: Its result.
    """

    print('  {}: {}'.format(what, response['message']))
    if not response['ok']:
        raise RuntimeError('{} failed: {}'.format(what, response['message']))
    return response['result']


def _cage_shader():
    """
    A dark, see-through lambert, so a cage reads as a cage rather than as geometry.

    :return: The shading engine.
    :rtype: str
    """

    if cmds.objExists('cageWrap_cage_SG'):
        return 'cageWrap_cage_SG'
    shader = cmds.shadingNode('lambert', asShader=True, name='cageWrap_cage_lambert')
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name='cageWrap_cage_SG')
    cmds.connectAttr(shader + '.outColor', engine + '.surfaceShader')
    cmds.setAttr(shader + '.color', 0.20, 0.22, 0.26, type='double3')
    cmds.setAttr(shader + '.transparency', 0.72, 0.72, 0.72, type='double3')
    return engine


def _as_cage(mesh):
    """
    Dress a mesh up as a cage: see-through, wireframe-ish, still selectable.

    Still selectable on purpose. A cage the artist cannot click is a cage they cannot
    animate, and `overrideEnabled` with a reference display would do exactly that.

    :param str mesh: The cage transform.
    """

    cmds.sets(mesh, edit=True, forceElement=_cage_shader())
    for shape in (cmds.listRelatives(mesh, shapes=True, fullPath=True) or []):
        try:
            cmds.setAttr(shape + '.castsShadows', 0)
            cmds.setAttr(shape + '.receiveShadows', 0)
        except Exception:
            pass


def _key_points(cage, frame, mover):
    """
    Key every cage point at frame 0, move some of them, and key them again.

    Keys on the POINTS rather than the transform, because that is how a cage is
    actually used - and because it is the case that catches a deformer caching the wrong
    thing: the cage's transform never moves, so nothing but the mesh data changes.

    :param str cage: The cage transform.
    :param float frame: The frame to key the pose on.
    :param mover: Called with the cage name; moves whatever it likes.
    """

    count = cmds.polyEvaluate(cage, vertex=True)
    every = '{}.vtx[0:{}]'.format(cage, count - 1)
    cmds.currentTime(0)
    cmds.setKeyframe(every, time=0)
    cmds.currentTime(frame)
    mover(cage)
    cmds.setKeyframe(every, time=frame)
    cmds.currentTime(0)


def _tube_cage(name, height, half):
    """
    A four-ring box cage around a vertical tube.

    :param str name: Name for the cage.
    :param float height: How tall.
    :param float half: Half its width.
    :return: The cage transform.
    :rtype: str
    """

    cage = cmds.polyCube(width=half * 2.0, height=height, depth=half * 2.0,
                         subdivisionsY=3, name=name, constructionHistory=False)[0]
    return cage


def _bend_setup(index):
    """
    Setup 1: a bend that does not shear, against a lattice through the same shape.
    """

    print('setup 1 - a bend that does not shear')
    tube = cmds.polyCylinder(radius=1.0, height=8.0, subdivisionsX=24, subdivisionsY=24,
                             subdivisionsZ=1, axis=(0, 1, 0), name='bend_tube',
                             constructionHistory=False)[0]
    cage = _tube_cage('bend_cage', 9.0, 1.6)
    # The rest cage comes into the group too. It is a hidden duplicate the wrap makes, and
    # leaving it outside a group that moves is the one way to break a finished setup: the
    # group's transform then reads as the cage having moved, and the mesh follows it on top
    # of its own transform. Three of these four setups were broken exactly that way, and
    # only this one - the group at index 0, which never moves - looked right.
    rest = _report('wrapping the tube',
                   cagewrap_api.wrap(tube, cage=cage, stretch=0.0))['rest_cage']

    def swing(which):
        """Swing the top two rings over in X, and lift them a little."""
        for vertex in range(cmds.polyEvaluate(which, vertex=True)):
            x, y, z = cmds.pointPosition('{}.vtx[{}]'.format(which, vertex), world=True)
            if y > 0.1:
                lean = 3.2 * (y / 4.5) ** 2
                cmds.move(x + lean, y, z, '{}.vtx[{}]'.format(which, vertex),
                          absolute=True, worldSpace=True)

    _key_points(cage, END_FRAME, swing)
    _as_cage(cage)

    # The same shape through a lattice, to compare against. Not a criticism of lattices -
    # it is the difference the face normals make, which is easier to see than to describe.
    other = cmds.polyCylinder(radius=1.0, height=8.0, subdivisionsX=24, subdivisionsY=24,
                              subdivisionsZ=1, axis=(0, 1, 0), name='bend_tube_lattice',
                              constructionHistory=False)[0]
    cmds.move(4.0, 0, 0, other)
    lattice = cmds.lattice(other, divisions=(2, 4, 2), objectCentered=True,
                           name='bend_lattice')
    points = '{}.pt[0:1][0:3][0:1]'.format(lattice[1])
    cmds.currentTime(0)
    cmds.setKeyframe(points, time=0)
    cmds.currentTime(END_FRAME)
    for u in range(2):
        for v in range(4):
            for w in range(2):
                one = '{}.pt[{}][{}][{}]'.format(lattice[1], u, v, w)
                x, y, z = cmds.pointPosition(one, world=True)
                if y > 0.1:
                    cmds.move(x + 3.2 * (y / 4.5) ** 2, y, z, one, absolute=True,
                              worldSpace=True)
    cmds.setKeyframe(points, time=END_FRAME)
    cmds.currentTime(0)

    group = cmds.group(tube, cage, rest, other, lattice[1], lattice[2], name='setup1_bend')
    cmds.setAttr(group + '.translateX', index * SPACING)
    return group


def _stretch_setup(index):
    """
    Setup 2: the same cage growth with the thickness knob at 0 and at 1.
    """

    print('setup 2 - what the thickness knob does, at both ends')
    made = []
    for offset, stretch, label in ((-3.0, 0.0, 'keeps_its_thickness'), (3.0, 1.0, 'grows')):
        ball = cmds.polySphere(radius=1.2, subdivisionsX=24, subdivisionsY=24,
                              name='stretch_{}'.format(label), constructionHistory=False)[0]
        cmds.move(offset, 0, 0, ball)
        cage = cmds.polyCube(width=3.2, height=3.2, depth=3.2, subdivisionsY=2,
                             name='stretch_{}_cage'.format(label),
                             constructionHistory=False)[0]
        cmds.move(offset, 0, 0, cage)
        rest = _report('wrapping {}'.format(label),
                       cagewrap_api.wrap(ball, cage=cage, stretch=stretch))['rest_cage']

        def grow(which, at=offset):
            """Scale the cage up about its own centre, by 1.8."""
            for vertex in range(cmds.polyEvaluate(which, vertex=True)):
                x, y, z = cmds.pointPosition('{}.vtx[{}]'.format(which, vertex), world=True)
                cmds.move(at + (x - at) * 1.8, y * 1.8, z * 1.8,
                          '{}.vtx[{}]'.format(which, vertex), absolute=True, worldSpace=True)

        _key_points(cage, END_FRAME, grow)
        _as_cage(cage)
        made += [ball, cage, rest]

    # A uniform growth is the clearest illustration available: at 1 the ball scales by
    # exactly 1.8 with the cage, at 0 by 1.5, because the thickness term is left unscaled
    # while the position term still follows. Squash is the same knob the other way, and
    # much harder to read - the first version of this sample squashed both balls and the
    # two came out 1% apart in width, which demonstrated nothing at all.
    group = cmds.group(made, name='setup2_stretch')
    cmds.setAttr(group + '.translateX', index * SPACING)
    return group


def _built_cage_setup(index):
    """
    Setup 3: a lumpy shape nobody modelled a cage for.
    """

    print('setup 3 - a cage the tool built, symmetrical because it was asked to be')
    blob = cmds.polySphere(radius=2.0, subdivisionsX=28, subdivisionsY=28, name='blob',
                           constructionHistory=False)[0]
    # Lumps, deliberately not symmetrical, so the cage has something to be built around.
    cmds.polyMoveVertex(blob + '.vtx[120:190]', localTranslate=(0, 0, 0.8),
                        constructionHistory=False)
    cmds.polyMoveVertex(blob + '.vtx[360:400]', localTranslate=(0, 0, -0.5),
                        constructionHistory=False)

    result = _report('building a cage and wrapping in one call',
                     cagewrap_api.wrap(blob, faces=120, symmetry=True, stretch=0.4))
    cage = result['cage']
    rest = result['rest_cage']

    def twist(which):
        """Twist the cage about Y, which is the deformation that shears a lattice."""
        for vertex in range(cmds.polyEvaluate(which, vertex=True)):
            x, y, z = cmds.pointPosition('{}.vtx[{}]'.format(which, vertex), world=True)
            angle = 0.55 * y
            cmds.move(x * math.cos(angle) + z * math.sin(angle), y,
                      -x * math.sin(angle) + z * math.cos(angle),
                      '{}.vtx[{}]'.format(which, vertex), absolute=True, worldSpace=True)

    _key_points(cage, END_FRAME, twist)
    _as_cage(cage)

    group = cmds.group(blob, cage, rest, name='setup3_built_cage')
    cmds.setAttr(group + '.translateX', index * SPACING)
    return group


def _cloth_setup(index):
    """
    Setup 4: a dense sheet driven by nine points.
    """

    print('setup 4 - cloth from a nine-point cage')
    sheet = cmds.polyPlane(width=6.0, height=8.0, subdivisionsX=60, subdivisionsY=80,
                           axis=(0, 0, 1), name='cloth', constructionHistory=False)[0]
    cage = cmds.polyCube(width=7.0, height=9.0, depth=1.2, subdivisionsY=2,
                         name='cloth_cage', constructionHistory=False)[0]
    rest = _report('wrapping 4,941 points to a cage of 8',
                   cagewrap_api.wrap(sheet, cage=cage))['rest_cage']

    def billow(which):
        """Blow the middle of the cage out and let the bottom trail."""
        for vertex in range(cmds.polyEvaluate(which, vertex=True)):
            x, y, z = cmds.pointPosition('{}.vtx[{}]'.format(which, vertex), world=True)
            push = 2.4 * math.cos(y * 0.35) if abs(y) < 3.0 else 0.0
            cmds.move(x, y, z + push + (0.8 if y < -3.0 else 0.0),
                      '{}.vtx[{}]'.format(which, vertex), absolute=True, worldSpace=True)

    _key_points(cage, END_FRAME, billow)
    _as_cage(cage)

    group = cmds.group(sheet, cage, rest, name='setup4_cloth')
    cmds.setAttr(group + '.translateX', index * SPACING)
    return group


def build():
    """
    Build the whole sample scene.

    :return: The groups it made.
    :rtype: list
    """

    available, reason = cagewrap_api.plugin_is_available()
    if not available:
        raise RuntimeError(reason)

    cmds.playbackOptions(minTime=0, maxTime=END_FRAME, animationStartTime=0,
                         animationEndTime=END_FRAME)

    groups = [_bend_setup(0), _stretch_setup(1), _built_cage_setup(2), _cloth_setup(3)]

    try:
        cmds.select(clear=True)
        cmds.viewFit(all=True)
    except Exception:
        # No viewport under mayapy. Not worth failing over.
        pass

    # Say it out loud, per wrap, rather than trusting that the grouping above was right.
    # A sample scene that is quietly broken teaches the wrong thing about the tool.
    for node in cagewrap_api.find_wraps():
        measured = cagewrap_api.report(node)
        if not measured['ok']:
            raise RuntimeError(measured['message'])
        if measured['result']['parented_apart']:
            raise RuntimeError('{} has its cage and rest cage under different parents, so '
                               'this scene would fly apart as soon as a group moved: {}'
                               .format(node, measured['message']))
        print('  {}'.format(measured['message']))

    print('mcaCageWrap sample - built {}. Scrub 0 to {:g}; select a cage and drag a point.'
          .format(', '.join(groups), END_FRAME))
    return groups


if __name__ == '__main__':
    try:
        import maya.cmds as _cmds
        _cmds.about(version=True)
    except Exception:
        import maya.standalone
        maya.standalone.initialize(name='python')
    build()
