"""
Build the mcaRBFSolver sample scene.

How to run it
-------------
The easy way is the **Build Sample Scene** button at the bottom of the RBF Solver
window. Otherwise, in a Python tab of the script editor:

    import sys; sys.path.append(r'<this folder>')
    import build_sample; build_sample.build()

A bare ``build()`` will not work - it lives in this module - and if you have
imported it once already, Python will not re-read the file without a reload:

    import importlib, build_sample
    importlib.reload(build_sample); build_sample.build()

Start from an empty scene. Nothing here cleans up after a previous run.

What it builds
--------------
Two setups, side by side, both driven by rotating one control:

1. **Aim vector to colour.** Three poses: the control pointing down +X, +Y and
   +Z, coloured red, green and blue. Rotate the control and the sphere's colour
   blends. A 3D key driving a 3D value, using ANGULAR distance - the right
   choice for a direction, where length means nothing.

2. **Angle to blendshape weights.** The real use this tool exists for, in
   miniature: a joint's rotation drives a blendshape's weights through three
   poses. This is the shoulder case with two shapes instead of twenty.

Both are built entirely through ``rbfsolver_api``, so this file doubles as the
shortest honest documentation of how to drive the thing from script.
"""

# software specific imports
import maya.cmds as cmds

# MCA python imports
from mca.mya.tools.rbfsolver import rbfsolver_api


def _report(label, response):
    """
    :param str label: What was being built.
    :param dict response: An ``ok/result/message`` response.
    :return: The result.
    :raises RuntimeError: If the call failed.
    """

    if not response['ok']:
        raise RuntimeError('{}: {}'.format(label, response['message']))
    print('mcaRBFSolver sample - {}: {}'.format(label, response['message']))
    return response['result']


def _aim_vector(control):
    """
    The control's own X axis, in world space, as three plugs.

    This is how a rigger feeds a joint's direction into an RBF: not the joint's
    rotation channels, which are Euler and wrap, but the axis it actually points
    along. A vectorProduct in Vector Matrix Product mode does it.

    :param str control: The transform.
    :return: The three output plugs, in order.
    :rtype: list
    """

    product = cmds.createNode('vectorProduct', name=control + '_aim')
    cmds.setAttr(product + '.operation', 3)          # Vector Matrix Product
    cmds.setAttr(product + '.input1', 1, 0, 0, type='double3')
    cmds.setAttr(product + '.normalizeOutput', True)
    cmds.connectAttr(control + '.worldMatrix[0]', product + '.matrix')
    return ['{}.output{}'.format(product, axis) for axis in 'XYZ']


def _colour_setup():
    """
    Aim vector in, colour out.

    :return: The group holding it.
    :rtype: str
    """

    control = cmds.spaceLocator(name='colour_control')[0]
    cmds.setAttr(control + '.scaleX', 3.0)
    ball = cmds.polySphere(radius=1.5, name='colour_ball', ch=False)[0]

    shader = cmds.shadingNode('lambert', asShader=True, name='colour_lambert')
    engine = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                       name='colour_SG')
    cmds.connectAttr(shader + '.outColor', engine + '.surfaceShader')
    cmds.sets(ball, edit=True, forceElement=engine)

    # weights_sum_to_one keeps the three channels adding to 1, so the colour
    # stays in range instead of overshooting between poses. That flag is called
    # blendShapeMode on the node, because that is what the original called it.
    solver = _report('colour solver', rbfsolver_api.create_solver(
        name='colour_rbf', distance='angular', kernel='gaussian',
        weights_sum_to_one=True))

    _report('connecting the aim vector',
            rbfsolver_api.connect_input(solver, _aim_vector(control)))
    _report('connecting the colour',
            rbfsolver_api.connect_output(
                solver, ['{}.color{}'.format(shader, c) for c in 'RGB']))

    # Three poses: pointing along each world axis. The key is read off the rig,
    # so the control is moved into each pose before recording it.
    for rotation, colour, name in (((0, 0, 0), [1.0, 0.0, 0.0], '+X is red'),
                                   ((0, 0, 90), [0.0, 1.0, 0.0], '+Y is green'),
                                   ((0, -90, 0), [0.0, 0.0, 1.0], '+Z is blue')):
        cmds.setAttr(control + '.rotate', *rotation)
        _report(name, rbfsolver_api.add_pose(solver, value=colour))

    cmds.setAttr(control + '.rotate', 0, 0, 30)
    return cmds.group(control, ball, name='setup1_aim_to_colour')


def _blendshape_setup():
    """
    A joint's rotation in, blendshape weights out. The shoulder case in
    miniature.

    :return: The group holding it.
    :rtype: str
    """

    base = cmds.polySphere(radius=1.5, name='shape_base', ch=False)[0]

    # Two targets, made by pushing the base around. Deleted afterwards - a
    # blendShape keeps its own copy.
    bulge = cmds.duplicate(base, name='shape_bulge')[0]
    cmds.scale(1.7, 0.6, 1.7, bulge + '.vtx[*]')
    taper = cmds.duplicate(base, name='shape_taper')[0]
    cmds.scale(0.5, 1.9, 0.5, taper + '.vtx[*]')

    blend = cmds.blendShape(bulge, taper, base, name='shape_blend')[0]
    cmds.delete(bulge, taper)

    control = cmds.spaceLocator(name='shape_control')[0]
    cmds.setAttr(control + '.scaleX', 3.0)

    solver = _report('blendshape solver', rbfsolver_api.create_solver(
        name='shape_rbf', distance='euclidean', kernel='gaussian'))

    # A single-dimension key here - one rotation channel - which is the case a
    # plain driven key would also handle. What it shows is the other half: ONE
    # key driving SEVERAL weights at once, which a driven key cannot do without
    # a curve per weight.
    _report('connecting the rotation',
            rbfsolver_api.connect_input(solver, [control + '.rotateZ']))
    _report('connecting the weights',
            rbfsolver_api.connect_output(
                solver, ['{}.weight[0]'.format(blend), '{}.weight[1]'.format(blend)]))

    for angle, weights, name in ((-90.0, [1.0, 0.0], 'rotated back, fully bulged'),
                                 (0.0, [0.0, 0.0], 'at rest, neither shape'),
                                 (90.0, [0.0, 1.0], 'rotated forward, fully tapered')):
        cmds.setAttr(control + '.rotateZ', angle)
        _report(name, rbfsolver_api.add_pose(solver, value=weights))

    cmds.setAttr(control + '.rotateZ', 45.0)
    return cmds.group(control, base, name='setup2_angle_to_shapes')


def build():
    """
    Build the whole sample scene.

    :return: The group transforms.
    :rtype: list
    """

    available, reason = rbfsolver_api.plugin_is_available()
    if not available:
        raise RuntimeError(reason)

    groups = [_colour_setup(), _blendshape_setup()]
    for index, group in enumerate(groups):
        cmds.setAttr(group + '.translateX', index * 8.0)

    try:
        cmds.select(clear=True)
        cmds.viewFit(all=True)
    except Exception:
        # No viewport under mayapy. Not worth failing over.
        pass

    print('mcaRBFSolver sample - built {}. Rotate either control and watch what it '
          'drives.'.format(', '.join(groups)))
    return groups


if __name__ == '__main__':
    build()
