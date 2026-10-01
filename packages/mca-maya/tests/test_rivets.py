"""
Sticking things to geometry - uvPins on a mesh, rivets on a surface - in a real Maya.

    mayapy tests/test_rivets.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_uv_pins(suite, pm, rivets, vert_utils):
    harness.new_scene()
    mesh = pm.polyPlane(name='the_mesh', width=10, height=10, subdivisionsX=4, subdivisionsY=4,
                        axis=(0, 1, 0))[0]
    locator = pm.spaceLocator(name='rider')
    locator.translate.set(2, 0, 2)

    pin = rivets.create_uv_pin(mesh, locator)
    suite.check('a transform is pinned to a mesh', pin is not None)
    suite.check('through a uvPin node', isinstance(pin, pm.nt.UvPin), str(type(pin)))
    suite.check('marked as one this pipeline built',
                pin.hasAttr(rivets.IS_UV_PIN_ATTR)
                and pin.attr(rivets.IS_UV_PIN_ATTR).get() is True)
    suite.check('the mesh drives the pin',
                mesh.getShape().worldMesh[0] in pin.deformedGeometry.listConnections(plugs=True),
                str(pin.deformedGeometry.listConnections(plugs=True)))
    suite.check('and the pin drives the object\'s offset matrix, not its channels',
                pin.outputMatrix[0] in locator.offsetParentMatrix.listConnections(plugs=True),
                str(locator.offsetParentMatrix.listConnections(plugs=True)))
    suite.check('so the object\'s own channels are back at their defaults and free for an animator',
                list(locator.translate.get()) == [0, 0, 0]
                and list(locator.rotate.get()) == [0, 0, 0]
                and list(locator.scale.get()) == [1, 1, 1],
                '{0}, {1}, {2}'.format(locator.translate.get(), locator.rotate.get(),
                                       locator.scale.get()))
    suite.check('the object stops inheriting its parent\'s transform, since the matrix is absolute',
                locator.inheritsTransform.get() is False)

    expected = vert_utils.get_uv_coordinates(locator, mesh)
    suite.check('with no UV given it is pinned at the closest point on the mesh to where it was',
                [round(pin.coordinate[0].coordinateU.get(), 4),
                 round(pin.coordinate[0].coordinateV.get(), 4)]
                == [round(value, 4) for value in expected],
                '{0} against {1}'.format([pin.coordinate[0].coordinateU.get(),
                                          pin.coordinate[0].coordinateV.get()], expected))
    suite.check('and it lands where the UV says, not where it started',
                abs(pm.xform(locator, query=True, worldSpace=True,
                             translation=True)[0] - 2.0) < 0.5,
                str(pm.xform(locator, query=True, worldSpace=True, translation=True)))

    # The UV set, which is what makes an imported mesh work.
    suite.check('the pin is told which UV set the mesh is actually using, not left on map1',
                pin.uvSetName.get() == pm.polyUVSet(mesh, q=True, currentUVSet=True)[0],
                str(pin.uvSetName.get()))

    renamed_set = pm.polyUVSet(mesh, copy=True, uvSet='map1', newUVSet='UVChannel_1')
    pm.polyUVSet(mesh, currentUVSet=True, uvSet='UVChannel_1')
    other = pm.spaceLocator(name='rider_two')
    second_pin = rivets.create_uv_pin(mesh, other, uv=[0.25, 0.75], name='cheek')
    suite.check('a mesh using another UV set gets a pin pointed at that set',
                second_pin.uvSetName.get() == 'UVChannel_1',
                '{0} (sets: {1})'.format(second_pin.uvSetName.get(), renamed_set))
    suite.check('an explicit UV is used as given',
                [second_pin.coordinate[0].coordinateU.get(),
                 second_pin.coordinate[0].coordinateV.get()] == [0.25, 0.75])
    suite.check('and a name given is the pin\'s name with the suffix on the end',
                str(second_pin) == 'cheek_{0}'.format(rivets.UV_PIN_SUFFIX), str(second_pin))

    # -- what it refuses ------------------------------------------------------------------- #
    suite.check('a transform with no mesh under it answers nothing rather than raising',
                rivets.create_uv_pin(pm.group(empty=True, name='not_a_mesh'),
                                     pm.spaceLocator(name='nobody')) is None)
    suite.check('and so does a shape handed over where a transform belongs',
                rivets.create_uv_pin(mesh, mesh.getShape()) is None)


def check_connect_uv_pin(suite, pm, rivets):
    harness.new_scene()
    mesh = pm.polyPlane(name='the_mesh', width=10, height=10, axis=(0, 1, 0))[0]

    locator, pin = rivets.connect_uv_pin(mesh, [0.5, 0.5])
    # The version before answered {'<locator name>': '<pin name>'} - one entry, both strings.
    suite.check('a locator and its pin come back as nodes rather than as a dictionary of names',
                isinstance(locator, pm.nt.Transform) and isinstance(pin, pm.nt.UvPin),
                '{0}, {1}'.format(type(locator), type(pin)))
    suite.check('the locator is named for the rivet it is',
                str(locator).startswith(rivets.DEFAULT_RIVET_NAME), str(locator))
    suite.check('and drawn small, because it is a marker rather than a control',
                locator.localScaleX.get() == rivets.DEFAULT_LOCATOR_SCALE)
    suite.check('the pin is named after the locator, with the suffix on the end',
                str(pin) == '{0}_{1}'.format(locator, rivets.UV_PIN_SUFFIX), str(pin))

    second_locator, second_pin = rivets.connect_uv_pin(mesh, [0.2, 0.2])
    suite.check('a second rivet on the same mesh gets its own names',
                str(second_locator) != str(locator) and str(second_pin) != str(pin),
                '{0}, {1}'.format(second_locator, second_pin))

    named_locator, named_pin = rivets.connect_uv_pin(mesh, [0.2, 0.2], uv_pin_name='brow_left')
    suite.check('a name given names the locator',
                str(named_locator) == 'brow_left', str(named_locator))
    suite.check('and the pin follows the same scheme as the unnamed case, which it used not to',
                str(named_pin) == 'brow_left_{0}'.format(rivets.UV_PIN_SUFFIX), str(named_pin))


def check_surface_rivets(suite, pm, rivets, surface):
    harness.new_scene()
    nurbs = pm.nurbsPlane(name='the_surface', width=10, lengthRatio=1, patchesU=4, patchesV=4,
                          axis=(0, 1, 0))[0]
    nurbs.translate.set(0, 5, 0)
    transform = pm.spaceLocator(name='rider')
    transform.translate.set(3, 5, 1)

    import maya.cmds as cmds
    position = pm.xform(transform, query=True, worldSpace=True, translation=True)
    expected = surface.get_closest_parameter_on_surface(nurbs, position)

    rivet = rivets.BasicRivet.attach_to_surface(transform, nurbs)
    suite.check('a transform is attached to a surface', rivet is not None)
    # The bug: the transform was made into the rivet and then parent constrained to a locator
    # parented under itself, which is a cycle - on the default argument, every time.
    suite.check('and the scene has no evaluation cycle in it',
                cmds.cycleCheck(all=True) is False, str(cmds.cycleCheck(all=True)))
    suite.check('because the rivet is a node of its own, not the transform it drives',
                rivet.rivet != transform, str(rivet.rivet))
    suite.check('through a node reading the surface at one parameter',
                rivet.point_on_surface is not None)

    # The bug: worldSpace is on the shape, and this used to ask pm.objExists on the transform's
    # name, so for a surface's transform - which attach_to_surface passes straight through - the
    # reader was wired to nothing at all.
    suite.check('the surface drives that reader, even though a transform was handed over',
                bool(rivet.point_on_surface.inputSurface.listConnections()),
                str(rivet.point_on_surface.inputSurface.listConnections()))
    suite.check('the reader drives the rivet\'s position',
                bool(rivet.rivet.translate.listConnections(destination=False)))
    suite.check('and an aim constraint under the rivet turns it to the surface normal',
                rivet.aim_constraint.getParent() == rivet.rivet,
                str(rivet.aim_constraint.getParent()))

    # The finding this module was waiting on: the UV came from closestPoint read as (uv, _, _).
    suite.check('the parameter it is placed at is the surface\'s own parameterisation, not the '
                'closest point\'s coordinates',
                [round(rivet.point_on_surface.parameterU.get(), 4),
                 round(rivet.point_on_surface.parameterV.get(), 4)]
                == [round(value, 4) for value in expected],
                '{0} against {1}'.format([rivet.point_on_surface.parameterU.get(),
                                          rivet.point_on_surface.parameterV.get()], expected))
    suite.check('and the rivet lands near where the transform was, which is what that means',
                abs(pm.xform(rivet.rivet, query=True, worldSpace=True,
                             translation=True)[0] - position[0]) < 1.5,
                str(pm.xform(rivet.rivet, query=True, worldSpace=True, translation=True)))

    suite.check('the transform keeps its place in the hierarchy, driven through a constraint',
                transform.getParent() is None
                and bool(pm.listConnections(transform, type=pm.nt.ParentConstraint)))

    # -- the transform as the rivet -------------------------------------------------------- #
    harness.new_scene()
    nurbs = pm.nurbsPlane(name='the_surface', width=10, axis=(0, 1, 0))[0]
    direct = pm.spaceLocator(name='direct_rider')
    direct.translate.set(2, 0, 2)
    without = rivets.BasicRivet.attach_to_surface(direct, nurbs, constraint=False)
    suite.check('without a constraint the transform itself is the rivet',
                without.rivet == direct, str(without.rivet))
    suite.check('its channels are driven by the surface',
                bool(direct.translate.listConnections(destination=False)))
    suite.check('and that is not a cycle either',
                cmds.cycleCheck(all=True) is False, str(cmds.cycleCheck(all=True)))

    # -- built by hand --------------------------------------------------------------------- #
    harness.new_scene()
    nurbs = pm.nurbsPlane(name='the_surface', width=10, axis=(0, 1, 0))[0]
    by_hand = rivets.BasicRivet()
    message = suite.raises('a rivet with no surface set refuses to build', by_hand.create)
    suite.check('and says what is missing', 'surface' in message.lower(), message)

    by_hand.set_surface(nurbs, 0.5, 0.5)
    by_hand.set_create_joint(True)
    built = by_hand.create()
    suite.check('a rivet can be built as a joint rather than a locator',
                isinstance(built, pm.nt.Joint), str(type(built)))
    suite.check('and it sits on the surface',
                abs(pm.xform(built, query=True, worldSpace=True, translation=True)[1]) < 0.001,
                str(pm.xform(built, query=True, worldSpace=True, translation=True)))

    suite.check('MatrixRivet is gone - nothing called it, and its own usage example calls a '
                'function that exists nowhere',
                not hasattr(rivets, 'MatrixRivet'))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.modeling import rivets
    from mca.mya.modeling import surface
    from mca.mya.modeling import vert_utils

    check_uv_pins(suite, pm, rivets, vert_utils)
    check_connect_uv_pin(suite, pm, rivets)
    check_surface_rivets(suite, pm, rivets, surface)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rivets', body))
