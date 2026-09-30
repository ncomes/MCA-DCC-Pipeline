"""
NURBS surfaces.

One function, kept in its own module because the callers that want it - ribbon rigs, rivets -
want it on its own and not the whole of :mod:`geometry`.

What was wrong before:

- **It answered a position, not a parameter.** ``pm.nt.NurbsSurface.closestPoint`` answers
  ``(point, u, v)``, and the line reading it was ``uv, _, _ = surface_shape.closestPoint(...)``
  - so ``uv`` was the *point*, and what came back was the closest point's X and Y coordinates
  under the name of a UV parameter. Its one caller, ``rivets.attach_to_surface``, feeds the two
  numbers straight into a rivet's U and V, so every rivet attached to a surface without an
  explicit UV has been placed by coordinates that have nothing to do with the surface's
  parameterisation. Checked in a real Maya against a ``closestPointOnSurface`` node.
- **The default space did not match the caller.** ``rivets`` measures a world position and this
  defaulted to ``preTransform``, so a surface that had been moved answered against its
  untransformed self. The default is ``world``, which is what the only caller means.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: A follicle or rivet sitting at exactly 0 sits on the surface's seam, where the normal is
#: undefined and anything attached to it flips. Nudging off the edge costs nothing visible and
#: takes the flip away.
EDGE_NUDGE = 0.001


def get_closest_parameter_on_surface(surface, vector, space='world'):
    """
    The UV parameter of the point on a surface closest to a position.

    :param pm.PyNode surface: The surface, as its transform or its shape.
    :param vector: The position to measure from, as three numbers or a ``pm.dt.Point``.
    :param str space: The space the position is given in, as ``closestPoint`` takes it.
    :return: The U and V parameters, nudged off zero. See :data:`EDGE_NUDGE`.
    :rtype: list(float)
    """

    surface_shape = surface
    if hasattr(surface, 'getShapes'):
        # A transform was given. The old version called getShapes() unguarded, which is an
        # AttributeError on the shape it also claims to accept.
        shapes = surface.getShapes()
        surface_shape = shapes[0] if shapes else surface

    # closestPoint answers the point first, then the two parameters. Reading it as (uv, _, _)
    # was the bug.
    _, parameter_u, parameter_v = surface_shape.closestPoint(vector, space=space)
    return [parameter_u or EDGE_NUDGE, parameter_v or EDGE_NUDGE]
