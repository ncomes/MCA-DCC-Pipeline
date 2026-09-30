"""
Follicles: sticking something to a point on a surface.

A follicle reads a UV coordinate on a surface and writes out the position and orientation of
that point, which is how a ribbon rig's controls stay on the ribbon while it bends. The
plumbing is fiddly - the shape holds the parameters and the outputs, the transform is what
gets driven, and the transform must not inherit its parent's transform or the surface's motion
is applied twice - so it is worth having in one place.

What was wrong before:

- **``create_follicle_constraint`` could not work.** It called
  ``pm.parentConstraint(follicle_transform[0], node)``, and ``follicle_transform`` is already
  the transform. Indexing a PyNode indexes its *name*, so the first argument was the single
  character ``'f'`` - checked in a real Maya - and the constraint was made against a node of
  that name or, far more often, failed. It had no callers, and nor did
  ``create_follicle_constraint_from_selection``, which was its only way in. Both gone, and with
  them ``create_mesh_follicle``, whose only caller was the broken one.
- The module imported ``naming`` and never used it.
- ``create_empty_follicle`` set ``parameterU`` and ``parameterV`` through the transform rather
  than the shape. Maya forwards that to the shape, so it worked, but it reads as though the
  parameters live on the transform, which is the misunderstanding the rest of the bugs here
  come from. They are set on the shape now.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log


logger = log.MCA_LOGGER


def create_empty_follicle(name=None, uv=None, hide_follicle=True):
    """
    Make a follicle attached to nothing.

    :param str name: A name for the transform.
    :param list uv: Where on the surface it sits. Defaults to the corner.
    :param bool hide_follicle: Hide the shape, which is the usual thing - the follicle is
        plumbing, and an artist selecting it instead of the control it drives is a support call.
    :return: The follicle's transform.
    :rtype: pm.nt.Transform
    """

    uv = uv if uv is not None else [0, 0]
    follicle_shape = pm.createNode('follicle')
    if hide_follicle:
        pm.hide(follicle_shape)

    follicle = follicle_shape.getParent()
    # The follicle writes a world position into its own translate. Inheriting the parent's
    # transform on top of that applies the surface's motion twice.
    follicle.inheritsTransform.set(False)
    follicle.rename(name or 'follicle')

    follicle_shape.parameterU.set(uv[0])
    follicle_shape.parameterV.set(uv[1])
    return follicle


def create_surface_follicle(surface, name=None, uv=None, hide_follicle=True):
    """
    Make a follicle on a NURBS surface, wired up and driving its own transform.

    :param surface: The surface to attach to, as its transform or its shape.
    :param str name: A name for the follicle's transform.
    :param list uv: Where on the surface it sits.
    :param bool hide_follicle: Hide the shape.
    :return: The follicle's transform and its shape.
    :rtype: tuple(pm.nt.Transform, pm.nt.Follicle)
    """

    follicle = create_empty_follicle(name, uv, hide_follicle=hide_follicle)
    shape = follicle.getShape()

    pm.connectAttr('{0}.local'.format(surface), '{0}.inputSurface'.format(shape), force=True)
    pm.connectAttr('{0}.worldMatrix[0]'.format(surface), '{0}.inputWorldMatrix'.format(shape),
                   force=True)
    shape.outTranslate >> follicle.translate
    shape.outRotate >> follicle.rotate
    return follicle, shape
