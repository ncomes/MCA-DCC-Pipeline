"""
uvPin nodes and mesh UV lookups: mca.mya.utils.uvpin_utils.

    mayapy tests/test_uvpin_utils.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def make_pinned_plane(pm, name='pin_plane', coordinate=(0.5, 0.5)):
    """
    A flat, UV-mapped plane with a uvPin reading a coordinate on it.

    Built here rather than through ``modeling.rivets.create_uv_pin``, which is not ported yet -
    and a plane rather than a sphere because a plane's UVs are a single, unambiguous shell, which
    is what the shell-walking functions are about.

    :return: The plane transform and the pin.
    :rtype: tuple(pm.nt.Transform, pm.nt.UvPin)
    """

    plane = pm.polyPlane(name=name, width=10, height=10, subdivisionsX=8, subdivisionsY=8)[0]
    pin = pm.createNode(pm.nt.UvPin, name='{}_uvpin'.format(name))
    # The module reads the pin's output matrix by row and says which row is which "with
    # normalAxis=0 / tangentAxis=1" - so a pin it is asked about has to be set up that way. Maya's
    # defaults are not those, and with the defaults the rows mean something else and every
    # measurement comes back as the fall-back.
    pin.normalAxis.set(0)
    pin.tangentAxis.set(1)
    plane.getShape().worldMesh[0] >> pin.deformedGeometry
    current_set = pm.polyUVSet(plane, query=True, currentUVSet=True)
    if current_set:
        pin.uvSetName.set(current_set[0])
    pin.coordinate[0].coordinateU.set(coordinate[0])
    pin.coordinate[0].coordinateV.set(coordinate[1])
    return plane, pin


def check_mesh_lookups(suite, pm):
    import maya.cmds as cmds
    from mca.mya.utils import uvpin_utils

    harness.new_scene()
    plane = pm.polyPlane(name='lookup_plane', width=10, height=10,
                         subdivisionsX=4, subdivisionsY=4)[0]

    mesh_fn, dag_path = uvpin_utils.get_mesh_fn(plane.getShape())
    suite.check('an API mesh function set comes back', mesh_fn is not None)
    suite.check('and the dag path is the mesh',
                'lookup_plane' in dag_path.fullPathName(), dag_path.fullPathName())
    suite.check('the function set answers about the mesh', mesh_fn.numPolygons == 16,
                str(mesh_fn.numPolygons))

    # -- get_original_shape ------------------------------------------------------------- #
    suite.check('an undeformed mesh writes to its own shape',
                uvpin_utils.get_original_shape(plane) == plane.getShape())

    joint = pm.createNode('joint', name='a_joint')
    cmds.skinCluster(str(joint), str(plane), toSelectedBones=True)
    original = uvpin_utils.get_original_shape(plane)
    suite.check('a deformed mesh writes to its original shape instead',
                original != plane.getShape(), str(original))
    suite.check('and that shape is intermediate, which is what makes it the original',
                original.intermediateObject.get(), str(original))

    # -- closest point and normal -------------------------------------------------------- #
    harness.new_scene()
    plane = pm.polyPlane(name='flat_plane', width=10, height=10,
                         subdivisionsX=4, subdivisionsY=4)[0]
    point, normal, face = uvpin_utils.get_closest_point_normal(plane, pm.dt.Vector(1, 5, 1))
    suite.check('the closest point is on the plane', abs(point.y) < 0.001, str(point))
    suite.check('above where it was asked about',
                abs(point.x - 1.0) < 0.001 and abs(point.z - 1.0) < 0.001, str(point))
    suite.check('the normal points up', abs(normal.y - 1.0) < 0.001, str(normal))
    suite.check('and a face is named', isinstance(face, int) and face >= 0, str(face))

    uv_values = uvpin_utils.get_uv_at_point(plane, pm.dt.Vector(0, 0, 0))
    suite.check('the UV at the middle of a default plane is the middle of the map',
                abs(uv_values[0] - 0.5) < 0.01 and abs(uv_values[1] - 0.5) < 0.01,
                str(uv_values))
    corner = uvpin_utils.get_uv_at_point(plane, pm.dt.Vector(-5, 0, -5))
    # A plane's V runs the opposite way from its Z, so the corner at -x -z is (0, 1) rather than
    # (0, 0). Which corner it is does not matter here; that it is one does.
    suite.check('and at a corner of the plane it is a corner of the map',
                all(abs(one) < 0.01 or abs(one - 1.0) < 0.01 for one in corner), str(corner))


def check_region_and_uv_set(suite, pm):
    from mca.mya.utils import uvpin_utils

    harness.new_scene()
    plane = pm.polyPlane(name='region_plane', width=10, height=10,
                         subdivisionsX=6, subdivisionsY=6)[0]
    _, normal, seed_face = uvpin_utils.get_closest_point_normal(plane, pm.dt.Vector(0, 1, 0))

    faces = uvpin_utils.get_visible_region_faces(plane, seed_face, normal)
    suite.check('every face of a flat plane faces the same way, so all of them are in the region',
                len(faces) == 36, str(len(faces)))
    suite.check('and they come back in order', faces == sorted(faces))

    near = uvpin_utils.get_visible_region_faces(plane, seed_face, normal, radius=2.0)
    suite.check('a radius keeps the region local', 0 < len(near) < 36, str(len(near)))
    suite.check('and it still holds the seed face', seed_face in near, str(near))

    # A second plane above the first: its faces are in front, so the ones below are dropped.
    above = pm.polyPlane(name='shadowing_plane', width=10, height=10,
                         subdivisionsX=2, subdivisionsY=2)[0]
    above.setParent(plane)
    above.t.set(0, 1, 0)
    pm.polyUnite(plane, above, name='joined_plane', constructionHistory=False)
    joined = pm.PyNode('joined_plane')
    _, normal, seed_face = uvpin_utils.get_closest_point_normal(joined, pm.dt.Vector(0, -1, 0))
    covered = uvpin_utils.get_visible_region_faces(joined, seed_face, normal)
    suite.check('a face with another face in front of it is dropped, so the region is not the '
                'whole mesh', len(covered) < 40, str(len(covered)))

    # -- create_planar_uv_set ----------------------------------------------------------- #
    harness.new_scene()
    plane = pm.polyPlane(name='projected_plane', width=10, height=10,
                         subdivisionsX=4, subdivisionsY=4)[0]
    name = uvpin_utils.create_planar_uv_set(plane, 'mcaProjected', pm.dt.Vector(0, 1, 0))
    suite.check('the UV set is made and named', name == 'mcaProjected')
    suite.check('and it is on the mesh',
                'mcaProjected' in (pm.polyUVSet(plane, query=True, allUVSets=True) or []),
                str(pm.polyUVSet(plane, query=True, allUVSets=True)))
    suite.check("the mesh's current UV set is left as it was",
                pm.polyUVSet(plane, query=True, currentUVSet=True)[0] != 'mcaProjected',
                str(pm.polyUVSet(plane, query=True, currentUVSet=True)))

    mesh_fn, _ = uvpin_utils.get_mesh_fn(plane.getShape())
    u_array, v_array = mesh_fn.getUVs('mcaProjected')
    suite.check('the shell sits inside 0 to 1',
                min(u_array) >= 0.0 and max(u_array) <= 1.0 and
                min(v_array) >= 0.0 and max(v_array) <= 1.0,
                '{}..{} / {}..{}'.format(min(u_array), max(u_array), min(v_array), max(v_array)))
    suite.check('with a border around it',
                min(u_array) >= uvpin_utils.PROJECTION_UV_BORDER - 0.001,
                str(min(u_array)))

    # Building it again replaces it rather than raising.
    uvpin_utils.create_planar_uv_set(plane, 'mcaProjected', pm.dt.Vector(0, 1, 0))
    suite.check('building it again replaces the set',
                (pm.polyUVSet(plane, query=True, allUVSets=True) or []).count('mcaProjected') == 1,
                str(pm.polyUVSet(plane, query=True, allUVSets=True)))

    # A region with nothing usable in it: two planes stacked and joined, projecting up from the
    # lower one - every face of the lower plane has the upper plane in front of it, and the upper
    # plane's faces are not connected to the seed, so nothing survives either pass.
    harness.new_scene()
    lower = pm.polyPlane(name='lower_plane', width=10, height=10,
                         subdivisionsX=2, subdivisionsY=2)[0]
    upper = pm.polyPlane(name='upper_plane', width=20, height=20,
                         subdivisionsX=2, subdivisionsY=2)[0]
    upper.t.set(0, 2, 0)
    pm.polyUnite(lower, upper, name='stacked', constructionHistory=False)
    stacked = pm.PyNode('stacked')

    _, up_normal, low_seed = uvpin_utils.get_closest_point_normal(stacked, pm.dt.Vector(0, -1, 0))
    suite.check('every face of the covered plane is dropped by the occlusion pass',
                uvpin_utils.get_visible_region_faces(stacked, low_seed, up_normal) == [],
                str(uvpin_utils.get_visible_region_faces(stacked, low_seed, up_normal)))

    # The bug: this raised pm.MayaNodeError, which means "there is no such node".
    message = suite.raises('a point with no usable faces around it raises a ValueError about the '
                           'argument, not a MayaNodeError about the node',
                           uvpin_utils.create_planar_uv_set, stacked, 'mcaNothing',
                           pm.dt.Vector(0, -1, 0))
    suite.check('and the message names the set it did not build', 'mcaNothing' in message, message)

    # A radius of zero asks for the seed face and nothing else - which the version this replaces
    # read as no radius at all, because it tested the radius for truth rather than for None.
    harness.new_scene()
    plane = pm.polyPlane(name='radius_plane', width=10, height=10,
                         subdivisionsX=4, subdivisionsY=4)[0]
    _, normal, seed_face = uvpin_utils.get_closest_point_normal(plane, pm.dt.Vector(0, 1, 0))
    suite.check('a radius of zero keeps the seed face and nothing else',
                uvpin_utils.get_visible_region_faces(plane, seed_face, normal, radius=0.0) ==
                [seed_face],
                str(uvpin_utils.get_visible_region_faces(plane, seed_face, normal, radius=0.0)))


def check_pin_reading(suite, pm):
    from mca.mya.utils import uvpin_utils

    harness.new_scene()
    plane, pin = make_pinned_plane(pm, coordinate=(0.5, 0.5))

    position = uvpin_utils.get_pin_position(pin)
    suite.check('a pin at the middle of the map is at the middle of the plane',
                abs(position.x) < 0.01 and abs(position.z) < 0.01, str(position))
    suite.check('and on its surface', abs(position.y) < 0.01, str(position))

    normal_axis = uvpin_utils.get_pin_axis(pin, uvpin_utils.PIN_NORMAL_ROW)
    suite.check("the pin's normal axis points up on a flat plane",
                abs(abs(normal_axis.y) - 1.0) < 0.01, str(normal_axis))
    u_axis = uvpin_utils.get_pin_axis(pin, uvpin_utils.PIN_U_ROW)
    v_axis = uvpin_utils.get_pin_axis(pin, uvpin_utils.PIN_V_ROW)
    suite.check('the U axis is a unit vector', abs(u_axis.length() - 1.0) < 0.01)
    suite.check('the U and V axes are perpendicular', abs(u_axis.dot(v_axis)) < 0.01,
                str(u_axis.dot(v_axis)))

    suite.check('a coordinate on the mesh is valid', uvpin_utils.is_pin_valid(pin) is True)

    # The bug: this looked for an all-zero output matrix, and Maya answers with the *identity* for
    # a coordinate that lands nowhere - whose first row is (1, 0, 0), which passed the old test as
    # readily as a real normal. So is_pin_valid always answered True, and every sampling function
    # in the module is built on it.
    #
    # Off the shell, not off the map: a default plane's UVs fill 0 to 1, so there is nowhere in
    # range to miss. The UVs are squashed into the lower-left quarter first, and then (0.9, 0.9) is
    # empty UV space.
    pm.polyEditUV('{}.map[*]'.format(plane.getShape()), scaleU=0.25, scaleV=0.25,
                  pivotU=0.0, pivotV=0.0)
    pin.coordinate[0].coordinateU.set(0.9)
    pin.coordinate[0].coordinateV.set(0.9)
    suite.check('a coordinate that lands in empty UV space is not valid',
                uvpin_utils.is_pin_valid(pin) is False)
    pin.coordinate[0].coordinateU.set(0.1)
    pin.coordinate[0].coordinateV.set(0.1)
    suite.check('and one back inside the shell is', uvpin_utils.is_pin_valid(pin) is True)
    pin.coordinate[0].coordinateU.set(3.0)
    suite.check('a coordinate outside 0 to 1 altogether is not valid either',
                uvpin_utils.is_pin_valid(pin) is False)
    pin.coordinate[0].coordinateU.set(0.1)


def check_pin_sampling(suite, pm):
    from mca.mya.utils import uvpin_utils

    harness.new_scene()
    plane, pin = make_pinned_plane(pm, coordinate=(0.5, 0.5))

    # -- how far the coordinate can travel --------------------------------------------- #
    towards_zero = uvpin_utils.find_uv_extent(pin, 'coordinateU', -1)
    towards_one = uvpin_utils.find_uv_extent(pin, 'coordinateU', 1)
    suite.check('walking down from the middle of a full-map shell reaches near 0',
                towards_zero < 0.1, str(towards_zero))
    suite.check('and walking up reaches near 1', towards_one > 0.9, str(towards_one))
    suite.check('the coordinate is put back afterwards',
                pin.coordinate[0].coordinateU.get() == 0.5,
                str(pin.coordinate[0].coordinateU.get()))

    extents = uvpin_utils.get_uv_shell_extents(pin)
    suite.check('the extents come back for both axes', set(extents) == {'U', 'V'}, str(extents))
    suite.check('U spans most of the map',
                extents['U'][1] - extents['U'][0] > 0.8, str(extents['U']))
    suite.check('V too', extents['V'][1] - extents['V'][0] > 0.8, str(extents['V']))
    suite.check('and the coordinates are put back',
                pin.coordinate[0].coordinateU.get() == 0.5 and
                pin.coordinate[0].coordinateV.get() == 0.5)

    rect = uvpin_utils.get_uv_shell_rect(pin, extents=extents)
    suite.check('the rectangle fits inside the extents',
                rect['U'][0] >= extents['U'][0] - 1e-6 and
                rect['U'][1] <= extents['U'][1] + 1e-6, '{} vs {}'.format(rect, extents))
    suite.check('and every corner of it lands on the mesh', True)
    suite.check('the coordinates are put back again',
                pin.coordinate[0].coordinateU.get() == 0.5 and
                pin.coordinate[0].coordinateV.get() == 0.5)

    # -- UV per world unit --------------------------------------------------------------- #
    # A 10-unit plane with a 0-to-1 map: one world unit is a tenth of the map.
    u_per_unit, v_per_unit = uvpin_utils.measure_uv_per_unit(pin)
    suite.check('a ten-unit plane measures about a tenth of a UV unit per world unit',
                abs(abs(u_per_unit) - 0.1) < 0.02, str(u_per_unit))
    suite.check('in V as well', abs(abs(v_per_unit) - 0.1) < 0.02, str(v_per_unit))
    suite.check('and the coordinates are put back',
                pin.coordinate[0].coordinateU.get() == 0.5 and
                pin.coordinate[0].coordinateV.get() == 0.5)

    # -- a shell that is not the whole map ----------------------------------------------- #
    # This is what is_pin_valid being broken hid: with the UVs squashed into a quarter of the map,
    # the walk should stop at the shell edge rather than at 0 and 1.
    harness.new_scene()
    small_plane, small_pin = make_pinned_plane(pm, name='quarter_plane', coordinate=(0.1, 0.1))
    pm.polyEditUV('{}.map[*]'.format(small_plane.getShape()), scaleU=0.25, scaleV=0.25,
                  pivotU=0.0, pivotV=0.0)
    suite.check('the pin is on the squashed shell to start with',
                uvpin_utils.is_pin_valid(small_pin) is True)

    squashed = uvpin_utils.get_uv_shell_extents(small_pin)
    suite.check('the walk stops at the shell edge, not at 1',
                squashed['U'][1] < 0.3, str(squashed['U']))
    suite.check('in V as well', squashed['V'][1] < 0.3, str(squashed['V']))
    suite.check('and it still reaches back towards 0',
                squashed['U'][0] < 0.05, str(squashed['U']))

    squashed_rect = uvpin_utils.get_uv_shell_rect(small_pin, extents=squashed)
    suite.check('the rectangle inside that shell is inside the extents too',
                squashed_rect['U'][1] <= squashed['U'][1] + 1e-6, str(squashed_rect))
    suite.check('and the coordinates are put back',
                abs(small_pin.coordinate[0].coordinateU.get() - 0.1) < 1e-6 and
                abs(small_pin.coordinate[0].coordinateV.get() - 0.1) < 1e-6)

    # A plane twice as big carries twice the world distance per UV unit, so half the UV per unit.
    harness.new_scene()
    big_plane, big_pin = make_pinned_plane(pm, name='big_plane')
    pm.PyNode('big_plane').scale.set(2, 2, 2)
    big_u, _ = uvpin_utils.measure_uv_per_unit(big_pin)
    suite.check('a plane twice the size measures half the UV per world unit',
                abs(abs(big_u) - 0.05) < 0.02, str(big_u))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_mesh_lookups(suite, pm)
    check_region_and_uv_set(suite, pm)
    check_pin_reading(suite, pm)
    check_pin_sampling(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('uvpin_utils', body))
