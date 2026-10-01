"""
Sticking something to a surface so it rides deformation.

A rivet is a transform that follows a point on a piece of geometry rather than a transform
hierarchy, so it travels with skinning, blendshapes and anything else that moves the vertices under
it. The face rig is built on them: every face control remembers *where on the head* it belongs as a
UV coordinate, because a position in space is no use across two different heads.

Two mechanisms, for the two kinds of geometry a rig puts a rivet on:

- :func:`create_uv_pin` and :func:`connect_uv_pin` for a **polygon mesh**, through Maya's ``uvPin``
  node. This is the one the pipeline uses, and it writes to ``offsetParentMatrix``, so the pinned
  object keeps its own clean channels for an animator.
- :class:`BasicRivet` for a **NURBS surface**, through ``pointOnSurfaceInfo`` and an aim constraint.
  Nothing calls it today; it is the only thing here that can pin to a surface, and surfaces are what
  a ribbon is made of, so it stays.

What was wrong before:

- **``MatrixRivet`` is gone.** A third mechanism - two mesh edges lofted into a surface, a
  ``pointOnSurfaceInfo`` on the loft, and a four-by-four matrix built out of its normal and
  tangents. Nothing in the pipeline has ever called it, and the usage example in its own docstring
  calls ``model.get_two_edges_from_close_object``, which exists in no module anywhere, so the one
  record of how to use it does not run either. ``create_uv_pin`` does the same job on a mesh, with
  one node instead of seven. Its ``set_uv`` also carried an unexplained ``if u >= 1: u = u - 1``,
  which is the shape of a bug worked around rather than found.
- **Every rivet attached to a NURBS surface without an explicit UV was placed by coordinates read
  as UV parameters.** That fault was in ``surface.get_closest_parameter_on_surface``, which read
  ``closestPoint``'s answer as ``(uv, _, _)`` when it is ``(point, u, v)`` - so a rivet got the
  closest point's X and Y where it wanted U and V. It was fixed when ``modeling/surface.py`` was
  ported; this is the caller it was fixed for, and it needs no change beyond the note that any rig
  carrying a surface rivet built before that fix is in the wrong place.
- **``create_uv_pin`` reported a mesh with no shape through the standard library's root logger** -
  ``logging.warning``, not the pipeline's ``log.MCA_LOGGER`` - so the one thing it says went
  somewhere nobody is reading, unformatted and without saying which mesh.
- ``create_uv_pin``'s ``if not isinstance(obj, pm.nt.Transform): obj = pm.PyNode(obj)`` reads as a
  guard that the object is a transform and is not one: ``pm.PyNode`` of a shape is still a shape,
  and the next line sets ``inheritsTransform`` on it. It asks properly, and says so.
- ``connect_uv_pin`` built its pin's name by splitting the locator's name and swapping the first
  word, which gives ``uvpin_rivet`` on the first call and ``uvpin_rivet1`` on the second - but only
  when the caller passed no name, and when the caller *did* pass one the pin came out as
  ``<name>_uvpin``. Two naming schemes in one function. And it answered a one-entry dictionary of
  *strings* keyed by the locator's name, which is a shape a caller has to unpack by looking the
  nodes up again; it answers the two nodes.
- **``BasicRivet.attach_to_surface`` built an evaluation cycle on its default arguments.** It passes
  the transform it is given into the constructor, which makes that transform *the rivet* - and then,
  when ``constraint`` is true, which is the default, it builds a locator, parents the locator under
  the rivet, and parent constrains the transform to it. The transform is the rivet, so it is
  constrained to its own child. Checked in a real Maya: the transform lands nowhere near the surface
  and ``cycleCheck`` names the plugs. The ``else`` branch beside it, ``if transform !=
  rivet.rivet: pm.parent(...)``, could never be true for the same reason. The two cases are now what
  they were clearly meant to be: with a constraint, the surface drives a rivet of its own and that
  rivet drives the transform, which keeps its place in the hierarchy; without one, the transform is
  the rivet and the surface drives its channels.
- **``BasicRivet`` wired its surface reader to nothing when it was handed a transform.** It asked
  ``pm.objExists('{}.worldSpace'.format(self._surface))`` - string building to ask a question
  ``hasAttr`` answers - and ``worldSpace`` is on the *shape*, so for a surface's transform, which is
  what ``attach_to_surface`` is handed and passes straight through, both that test and the
  ``outputSurface`` one below it were False and the reader got no input. It resolves the shape
  first. Four more formatted plug names followed it, for the position and the three rotate
  connections. ``attach_to_surface`` built a locator named ``locator_<rivet>`` and parented it
  under the rivet, and the constructor's ``self._rivet = transform or None`` is ``transform``.
- Tabs for indentation, throughout.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modeling import surface
from mca.mya.modeling import vert_utils


logger = log.MCA_LOGGER

#: Marks a node as a pin this pipeline built, so tools can find them.
IS_UV_PIN_ATTR = 'isUvPin'

#: The suffix a pin's name takes.
UV_PIN_SUFFIX = 'uvpin'

#: What a locator built to ride a mesh is called when the caller does not say.
DEFAULT_RIVET_NAME = 'loc_rivet'

#: How big to draw that locator.
DEFAULT_LOCATOR_SCALE = 0.2

#: The middle of a surface, where a rivet goes when nothing says otherwise.
SURFACE_CENTRE = (0.5, 0.5)

#: ``aimConstraint`` defaults for a surface rivet: aim along the surface normal, with V as up.
RIVET_AIM_VECTOR = (0, 1, 0)
RIVET_UP_VECTOR = (0, 0, 1)


# --------------------------------------------------------------------------------------- #
# a polygon mesh
# --------------------------------------------------------------------------------------- #
def create_uv_pin(mesh, obj, uv=None, name=None):
    """
    Pin a transform to a point on a mesh's UV map.

    The pin drives the object's ``offsetParentMatrix``, not its channels, so the object's own
    translate, rotate and scale stay at their defaults and are free for an animator or for another
    constraint. They are zeroed here, because whatever was in them is now in the matrix.

    :param pm.nt.Transform mesh: The mesh to pin to, as its transform.
    :param obj: The transform to pin.
    :param uv: The UV coordinate to pin at. None measures the closest point on the mesh to where
        the object is now.
    :type uv: list(float) or None
    :param str name: A name for the pin. None leaves it the name Maya gave it.
    :return: The pin, or None when it could not be built.
    :rtype: pm.nt.UvPin or None
    """

    if not mesh.getShape():
        logger.warning('%s has no mesh shape under it, so nothing can be pinned to it.', mesh)
        return None

    obj = pm.PyNode(obj)
    if not isinstance(obj, pm.nt.Transform):
        # The version before wrote this as `if not isinstance(...): obj = pm.PyNode(obj)`, which
        # reads as a guard and is not one - a shape stays a shape through PyNode, and the next line
        # sets inheritsTransform on it.
        logger.warning('%s is not a transform, so it cannot be pinned.', obj)
        return None

    if uv is None:
        uv = vert_utils.get_uv_coordinates(obj, mesh)

    uv_pin = pm.createNode(pm.nt.UvPin)
    uv_pin.addAttr(IS_UV_PIN_ATTR, at='bool', dv=True)
    if name:
        pm.rename(uv_pin, '{0}_{1}'.format(name, UV_PIN_SUFFIX))

    obj.inheritsTransform.set(0)
    mesh.getShape().worldMesh[0] >> uv_pin.deformedGeometry
    uv_pin.outputMatrix[0] >> obj.offsetParentMatrix

    # The node defaults to 'map1'. An imported mesh often uses another set name - 'UVChannel_1' is
    # common - and a missing set makes the pin evaluate garbage positions, so it is told which set
    # the mesh is actually using.
    current_uv_set = pm.polyUVSet(mesh, q=True, currentUVSet=True)
    if current_uv_set:
        uv_pin.uvSetName.set(current_uv_set[0])

    uv_pin.coordinate[0].coordinateU.set(uv[0])
    uv_pin.coordinate[0].coordinateV.set(uv[1])

    # The matrix carries the position now, so the channels go back to their defaults.
    obj.translate.set((0, 0, 0))
    obj.rotate.set((0, 0, 0))
    obj.scale.set((1, 1, 1))

    return uv_pin


def connect_uv_pin(mesh, uv, uv_pin_name=None, locator_scale=DEFAULT_LOCATOR_SCALE):
    """
    Build a small locator and pin it to a mesh, which is a rivet.

    :param pm.nt.Transform mesh: The mesh to pin to.
    :param list(float) uv: The UV coordinate to pin at.
    :param str uv_pin_name: A name for the locator; the pin takes it with ``_uvpin`` on the end.
        None names both after :data:`DEFAULT_RIVET_NAME`.
    :param float locator_scale: How big to draw the locator.
    :return: The locator and the pin, or the locator and None when the pin could not be built. The
        version before answered ``{'<locator name>': '<pin name>'}`` - one entry, both of them
        strings - which a caller has to look both nodes up again from.
    :rtype: tuple(pm.nt.Transform, pm.nt.UvPin or None)
    """

    name = uv_pin_name or DEFAULT_RIVET_NAME
    locator = pm.spaceLocator(name=name)
    for axis in ('localScaleX', 'localScaleY', 'localScaleZ'):
        locator.attr(axis).set(locator_scale)

    # One naming scheme: the locator's own name, which Maya may have made unique, with the pin
    # suffix on the end. The version before swapped the first word of the locator's name for
    # 'uvpin' when the caller passed no name and left the caller's name alone when it did, so the
    # two cases came out as uvpin_rivet and <name>_uvpin.
    return locator, create_uv_pin(mesh, locator, uv=uv, name=str(locator))


# --------------------------------------------------------------------------------------- #
# a NURBS surface
# --------------------------------------------------------------------------------------- #
class BasicRivet(object):
    """
    A transform that follows a point on a NURBS surface.

    A ``pointOnSurfaceInfo`` node reads the position, normal and tangents at one UV parameter, and
    its position drives the rivet while an aim constraint turns the rivet to the normal with the V
    tangent as up. Build it by setting the surface and calling :meth:`create`, or in one call with
    :meth:`attach_to_surface`.
    """

    def __init__(self, transform=None):
        """
        :param transform: The transform to make into a rivet. None builds one.
        """

        self._rivet = transform
        self._surface = None
        self._uv = list(SURFACE_CENTRE)
        self._create_joint = False
        self._percent_on = True
        self._local = False
        self._point_on_surface = None
        self._aim_constraint = None

    @property
    def rivet(self):
        """
        :return: The transform that follows the surface, once :meth:`create` has run.
        :rtype: pm.nt.Transform or None
        """

        return self._rivet

    @property
    def aim_constraint(self):
        """
        :return: The constraint that turns the rivet to the surface normal.
        :rtype: pm.nt.AimConstraint or None
        """

        return self._aim_constraint

    @property
    def point_on_surface(self):
        """
        :return: The node reading the surface at this rivet's UV parameter.
        :rtype: pm.nt.PointOnSurfaceInfo or None
        """

        return self._point_on_surface

    def set_surface(self, surface_to_attach, u, v):
        """
        :param surface_to_attach: The surface to follow, as its transform or its shape.
        :param float u: The U parameter to follow.
        :param float v: The V parameter.
        """

        self._surface = surface_to_attach
        self._uv = [u, v]

    def set_create_joint(self, create_joint):
        """
        :param bool create_joint: Build a joint rather than a locator, when there is nothing to
            make into a rivet.
        """

        self._create_joint = create_joint

    def set_percent_on(self, percent_on):
        """
        :param bool percent_on: Read the UV parameters as a fraction of the surface rather than in
            the surface's own parameter range.
        """

        self._percent_on = percent_on

    def set_local(self, local):
        """
        :param bool local: Read the surface before its transform rather than after it.
        """

        self._local = local

    def create(self):
        """
        Build the nodes and wire them up.

        :return: The rivet.
        :rtype: pm.nt.Transform
        :raises ValueError: When no surface has been set. The version before built a node named
            after ``None`` and then raised from inside pymel.
        """

        if self._surface is None:
            raise ValueError('A rivet needs a surface to follow; set_surface has not been called.')

        self._create_rivet()
        self._create_point_on_surface()
        self._create_aim_constraint()
        self._connect()
        pm.parent(self._aim_constraint, self._rivet)
        return self._rivet

    @classmethod
    def attach_to_surface(cls, transform, surface_to_attach, u=None, v=None, constraint=True):
        """
        Make a transform follow a surface, in one call.

        :param pm.nt.Transform transform: The transform to attach.
        :param surface_to_attach: The surface to follow.
        :param float u: The U parameter. None measures the closest point on the surface to where
            the transform is now.
        :param float v: The V parameter.
        :param bool constraint: Build a rivet of its own and drive the transform from it through a
            constraint, which leaves the transform where it is in the hierarchy with its own
            channels. False makes the transform itself the rivet, so the surface drives its
            channels directly.
        :return: The rivet.
        :rtype: BasicRivet
        """

        uv = [u, v]
        if u is None or v is None:
            position = pm.xform(transform, query=True, worldSpace=True, translation=True)
            # This is the call that used to be handed the closest point's coordinates in place of
            # the surface's parameters; the fault was in surface.py and is fixed there.
            uv = surface.get_closest_parameter_on_surface(surface_to_attach, position)

        # None, not the transform, when a constraint is wanted: the surface then drives a rivet of
        # its own and that rivet drives the transform. The version before made the transform the
        # rivet in both cases and then, in this one, parent constrained it to a locator parented
        # under itself - an evaluation cycle, on the default argument, every time.
        rivet = cls(None if constraint else transform)
        rivet.set_surface(surface_to_attach, uv[0], uv[1])
        rivet.set_create_joint(False)
        rivet.create()

        if constraint:
            locator = pm.spaceLocator(name='locator_{0}'.format(rivet.rivet))
            pm.parent(locator, rivet.rivet)
            pm.matchTransform(locator, transform, position=True, rotation=True)
            pm.parentConstraint(locator, transform, maintainOffset=True)

        return rivet

    # ------------------------------------------------------------------------------- #
    # the pieces
    # ------------------------------------------------------------------------------- #
    def _create_rivet(self):
        """Build the transform that will follow the surface, when there is not one already."""

        if self._rivet and pm.objExists(self._rivet):
            return
        if self._create_joint:
            pm.select(clear=True)
            self._rivet = pm.joint(name='rivetJoint')
        else:
            self._rivet = pm.spaceLocator(name='rivet')

    def _create_point_on_surface(self):
        """Build the node that reads the surface at this rivet's UV parameter."""

        surface_name = self._surface.name(stripNamespace=True)
        self._point_on_surface = pm.createNode(
            'pointOnSurfaceInfo', name='pointOnSurface_{0}'.format(surface_name))
        self._point_on_surface.turnOnPercentage.set(self._percent_on)
        self._point_on_surface.parameterU.set(self._uv[0])
        self._point_on_surface.parameterV.set(self._uv[1])

    def _create_aim_constraint(self):
        """Build the constraint that turns the rivet to the surface normal."""

        surface_name = self._surface.name(stripNamespace=True)
        self._aim_constraint = pm.createNode('aimConstraint',
                                             name='aimConstraint_{0}'.format(surface_name))
        self._aim_constraint.aimVector.set(RIVET_AIM_VECTOR)
        self._aim_constraint.upVector.set(RIVET_UP_VECTOR)

    def _connect(self):
        """
        Wire the surface into the reader, and the reader into the rivet.

        A NURBS surface shape answers ``worldSpace`` and ``local``; the output of a construction
        node, such as a loft, answers ``outputSurface`` instead. Both are asked for with ``hasAttr``
        rather than by building a plug name and asking whether it exists.
        """

        # The attributes below live on the shape, not on the transform a caller is most likely to
        # hand over - so `pm.objExists('<transform>.worldSpace')`, which is how this used to ask,
        # was False for a transform and the reader was wired to nothing at all.
        source = self._surface
        if hasattr(source, 'getShapes'):
            shapes = source.getShapes()
            if shapes:
                source = shapes[0]

        space_attr = 'local' if self._local else 'worldSpace'
        if source.hasAttr(space_attr):
            source.attr(space_attr) >> self._point_on_surface.inputSurface
        elif source.hasAttr('outputSurface'):
            source.attr('outputSurface') >> self._point_on_surface.inputSurface
        else:
            logger.warning('%s has no %s or outputSurface to read, so %s follows nothing.', source,
                           space_attr, self._rivet)

        self._point_on_surface.position >> self._rivet.translate
        self._point_on_surface.normal >> self._aim_constraint.target[0].targetTranslate
        self._point_on_surface.tangentV >> self._aim_constraint.worldUpVector
        for axis in 'XYZ':
            (self._aim_constraint.attr('constraintRotate{0}'.format(axis))
             >> self._rivet.attr('rotate{0}'.format(axis)))
