"""
Modeling: vert_utils, surface, geometry, follicle and blendshape_model, in a real Maya.

    mayapy tests/test_modeling.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _plane(name, width=2, height=2, subdivisions=1):
    """A poly plane lying in XZ, with its vertices where we can reason about them."""

    import pymel.core as pm
    return pm.polyPlane(name=name, width=width, height=height,
                        subdivisionsX=subdivisions, subdivisionsY=subdivisions)[0]


# --------------------------------------------------------------------------------------- #
# vert_utils
# --------------------------------------------------------------------------------------- #
def check_vert_utils(suite, pm):
    import maya.cmds as cmds
    from mca.mya.modeling import vert_utils

    harness.new_scene()

    suite.check('a named vertex gives up its number',
                vert_utils.get_vertices_as_numbers('head.vtx[412]') == [412])
    suite.check('as text when asked',
                vert_utils.get_vertices_as_numbers('head.vtx[412]', as_string=True) == ['412'])
    suite.check('a list gives one number each',
                vert_utils.get_vertices_as_numbers(['a.vtx[1]', 'a.vtx[2]']) == [1, 2])
    suite.check('a tuple works too - the old test was isinstance(x, list)',
                vert_utils.get_vertices_as_numbers(('a.vtx[1]', 'a.vtx[2]')) == [1, 2])
    suite.check('a bare number passes through', vert_utils.get_vertices_as_numbers(7) == [7])
    suite.check('and a name with no number in it is skipped rather than raising',
                vert_utils.get_vertices_as_numbers(['no_digits_here']) == [])

    plane = _plane('numbered', subdivisions=1)
    suite.check('a real vertex component gives up its number',
                vert_utils.get_vertices_as_numbers(plane.vtx[2]) == [2])

    # -- closest vertex and opposites ----------------------------------------------------- #
    harness.new_scene()
    plane = _plane('closest', width=2, height=2, subdivisions=1)
    locator = pm.spaceLocator()
    locator.translate.set((1.1, 0, 1.1))
    closest = vert_utils.get_closest_vertex_to_object(plane, locator)
    suite.check('the closest vertex is found, as an index', isinstance(closest, int), str(closest))
    position = pm.pointPosition(plane.vtx[closest], world=True)
    suite.check('and it is the corner the locator is beside',
                abs(position[0] - 1) < 0.001 and abs(position[2] - 1) < 0.001, str(position))

    suite.check('nothing has no opposites', vert_utils.get_opposite_vertices([]) == [])
    opposites = vert_utils.get_opposite_vertices([plane.vtx[closest]])
    suite.check('a vertex has one opposite', len(opposites) == 1, str(opposites))
    mirrored = pm.pointPosition(plane.vtx[opposites[0]], world=True)
    suite.check('across X from where it started',
                abs(mirrored[0] + position[0]) < 0.001 and abs(mirrored[2] - position[2]) < 0.001,
                str(mirrored))
    suite.check('and the temporary locator it used is gone - only ours is left',
                len(cmds.ls(type='locator') or []) == 1, str(cmds.ls(type='locator')))

    # -- the bug: a world-space mirror wrote local coordinates ---------------------------- #
    harness.new_scene()
    plane = _plane('offset_plane', width=2, height=2, subdivisions=1)
    plane.translateX.set(10)
    source, target = plane.vtx[0], plane.vtx[3]
    source_world = pm.pointPosition(source, world=True)
    vert_utils.mirror_vertex(source, target, world=True)
    target_world = pm.pointPosition(target, world=True)
    suite.check('a world-space mirror lands on the mirrored world position',
                abs(target_world[0] + source_world[0]) < 0.001,
                '{0} against {1}'.format(target_world[0], source_world[0]))

    # -- mirroring through a stored map --------------------------------------------------- #
    harness.new_scene()
    plane = _plane('mapped', width=2, height=2, subdivisions=1)
    # A 1x1 plane's corners: 0 is -X-Z, 1 is +X-Z, 2 is -X+Z, 3 is +X+Z.
    mapping = {'0': '1', '1': '0', '2': '3', '3': '2'}
    pm.xform(plane.vtx[0], translation=(-1, 5, -1))
    suite.check('mirroring through a map moves what the map names',
                vert_utils.mirror_vertices(plane, mapping, vertices=[0]) == 1)
    suite.check('onto its opposite number',
                abs(pm.pointPosition(plane.vtx[1], world=True)[1] - 5) < 0.001,
                str(pm.pointPosition(plane.vtx[1], world=True)))

    # The bug: JSON gives whole numbers back as ints, and the old version concatenated them.
    int_mapping = {'0': 1, '1': 0}
    pm.xform(plane.vtx[0], translation=(-1, 9, -1))
    suite.check('a map holding whole numbers rather than text is not a TypeError',
                vert_utils.mirror_vertices(plane, int_mapping, vertices=['mapped.vtx[0]']) == 1)
    suite.check('and it mirrors the same way',
                abs(pm.pointPosition(plane.vtx[1], world=True)[1] - 9) < 0.001)

    suite.check('a map that is not a dictionary is refused',
                vert_utils.mirror_vertices(plane, None) == 0)

    # -- mirroring a whole mesh ----------------------------------------------------------- #
    harness.new_scene()
    plane = _plane('whole', width=2, height=2, subdivisions=1)
    pm.xform(plane.vtx[0], translation=(-1, 4, -1))
    moved = vert_utils.mirror_mesh([0], [1], [], 'whole')
    suite.check('a mesh mirror swaps each pair over', moved == 2, str(moved))
    suite.check('so the height moves to the other side',
                abs(pm.pointPosition(plane.vtx[1], world=True)[1] - 4) < 0.001 and
                abs(pm.pointPosition(plane.vtx[0], world=True)[1]) < 0.001)

    # The bug: right_vertices was indexed with left's index and nothing checked the lengths.
    suite.check('two sides of different lengths are refused rather than raising partway',
                vert_utils.mirror_mesh([0, 2], [1], [], 'whole') == 0)

    harness.new_scene()
    plane = _plane('middles', width=2, height=2, subdivisions=2)
    middle = 4
    pm.xform(plane.vtx[middle], translation=(0.5, 0, 0))
    vert_utils.mirror_mesh([], [], [middle], 'middles')
    suite.check('a middle vertex is folded onto itself',
                abs(pm.pointPosition(plane.vtx[middle], world=True)[0] + 0.5) < 0.001,
                str(pm.pointPosition(plane.vtx[middle], world=True)))

    # -- uv coordinates ------------------------------------------------------------------- #
    harness.new_scene()
    plane = _plane('uv_plane', width=2, height=2, subdivisions=1)
    locator = pm.spaceLocator()
    locator.translate.set((0, 0, 0))
    uv = vert_utils.get_uv_coordinates(locator, plane)
    suite.check('the centre of a plane is the middle of its UV square',
                abs(uv[0] - 0.5) < 0.01 and abs(uv[1] - 0.5) < 0.01, str(uv))
    suite.check('and the node it used is gone',
                not (cmds.ls(type='closestPointOnMesh') or []))

    # -- symmetry ------------------------------------------------------------------------- #
    suite.check('symmetry goes on for a centre pose',
                vert_utils.set_vertex_symmetry('center', True) is True)
    suite.check('and Maya agrees', bool(pm.symmetricModelling(query=True, symmetry=True)))
    suite.check('a side pose is sculpted without it',
                vert_utils.set_vertex_symmetry('left', True) is False)
    suite.check('and symmetry off is off whatever the side',
                vert_utils.set_vertex_symmetry('center', False) is False)

    for gone in ('convert_to_vertices', 'get_inverse_vertex_selection',
                 'fix_mesh_components_selection_visualization'):
        suite.check('{0} had no callers and is gone'.format(gone),
                    not hasattr(vert_utils, gone))


# --------------------------------------------------------------------------------------- #
# surface
# --------------------------------------------------------------------------------------- #
def check_surface(suite, pm):
    from mca.mya.modeling import surface as surface_utils

    harness.new_scene()
    # axis explicitly: without it the plane is made along whatever the scene's up axis is,
    # which is not the same in a batch Maya as in the one the checks were written in.
    surface = pm.nurbsPlane(name='ribbon', width=10, lengthRatio=0.1, patchesU=4,
                            axis=(0, 1, 0))[0]

    uv = surface_utils.get_closest_parameter_on_surface(surface, (0, 0, 0))
    suite.check('the middle of a surface is the middle of its parameter range',
                abs(uv[0] - 0.5) < 0.01 and abs(uv[1] - 0.5) < 0.01, str(uv))

    # The bug: it read closestPoint's answer as (uv, _, _) when it is (point, u, v), so what
    # came back was the closest point's X and Y under the name of a parameter - and it was
    # handed a plain list, which closestPoint ignores, so the point was always the origin's.
    # Both are visible here: the surface is 10 wide, so x=3 is u=0.8 and x=-4 is u=0.1.
    off_centre = surface_utils.get_closest_parameter_on_surface(surface, (3, 0, 0))
    suite.check('a position along the surface gives a parameter along it',
                abs(off_centre[0] - 0.8) < 0.01, str(off_centre))
    other_side = surface_utils.get_closest_parameter_on_surface(surface, (-4, 0, 0))
    suite.check('and a different position gives a different one',
                abs(other_side[0] - 0.1) < 0.01, str(other_side))
    suite.check('a pm.dt.Point works as well as three numbers',
                surface_utils.get_closest_parameter_on_surface(surface, pm.dt.Point(3, 0, 0))
                == off_centre)
    suite.check('and the answer is a parameter pair, not a position',
                len(off_centre) == 2, str(off_centre))

    # The bug: getShapes() was called unguarded, so passing the shape - which the docstring
    # says is allowed - was an AttributeError.
    shape_uv = surface_utils.get_closest_parameter_on_surface(surface.getShape(), (3, 0, 0))
    suite.check('the shape may be given instead of the transform', shape_uv == off_centre,
                str(shape_uv))

    edge_uv = surface_utils.get_closest_parameter_on_surface(surface, (-100, 0, -100))
    suite.check('a parameter of zero is nudged off the seam',
                edge_uv[0] == surface_utils.EDGE_NUDGE, str(edge_uv))
    suite.check('and neither parameter comes back as a flat zero',
                edge_uv[0] != 0 and edge_uv[1] != 0, str(edge_uv))

    surface.translateX.set(20)
    moved_uv = surface_utils.get_closest_parameter_on_surface(surface, (23, 0, 0))
    suite.check('the default space is world, which is what the caller measures in',
                abs(moved_uv[0] - 0.8) < 0.01, str(moved_uv))


# --------------------------------------------------------------------------------------- #
# follicle
# --------------------------------------------------------------------------------------- #
def check_follicle(suite, pm):
    import maya.cmds as cmds
    from mca.mya.modeling import follicle

    harness.new_scene()
    empty = follicle.create_empty_follicle('lonely', uv=[0.25, 0.75])
    shape = empty.getShape()
    suite.check('an empty follicle is made', pm.objExists(empty))
    suite.check('named what it was asked to be', str(empty) == 'lonely', str(empty))
    suite.check('it does not inherit its parent transform', empty.inheritsTransform.get() is False)
    suite.check('the uv is on the shape, where it belongs',
                abs(shape.parameterU.get() - 0.25) < 0.001 and
                abs(shape.parameterV.get() - 0.75) < 0.001)
    suite.check('and the shape is hidden by default', shape.visibility.get() is False)

    visible = follicle.create_empty_follicle('seen', hide_follicle=False)
    suite.check('unless it is asked to be seen', visible.getShape().visibility.get() is True)

    # -- on a surface --------------------------------------------------------------------- #
    harness.new_scene()
    surface = pm.nurbsPlane(name='ribbon', width=10, lengthRatio=0.1, patchesU=4,
                            axis=(0, 1, 0))[0]
    transform, shape = follicle.create_surface_follicle(surface, name='rider', uv=[0.5, 0.5])
    suite.check('a surface follicle answers its transform and its shape',
                transform.getShape() == shape)
    suite.check('the surface drives it',
                shape.inputSurface.listConnections() == [surface])
    suite.check('through the world matrix as well',
                bool(shape.inputWorldMatrix.listConnections()))
    # listConnections answers the transform for a connection made from its shape, so the plugs
    # are what says which node the connection really comes from.
    suite.check('and the shape drives the transform',
                transform.translate.listConnections(plugs=True) == [shape.outTranslate] and
                transform.rotate.listConnections(plugs=True) == [shape.outRotate],
                str(transform.translate.listConnections(plugs=True)))

    surface.translateY.set(7)
    pm.refresh()
    suite.check('so moving the surface moves the follicle',
                abs(transform.translateY.get() - 7) < 0.01, str(transform.translateY.get()))

    for gone in ('create_mesh_follicle', 'create_follicle_constraint',
                 'create_follicle_constraint_from_selection'):
        suite.check('{0} is gone - it could not work and had no callers'.format(gone),
                    not hasattr(follicle, gone))


# --------------------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------------------- #
def check_geometry(suite, pm):
    import maya.cmds as cmds
    from mca.mya.modeling import geometry
    from mca.mya.utils import namespace

    harness.new_scene()

    pin = geometry.create_reference_obj(2, 1, 'Cylinder', 'rotateZ', 'l_upperarm')
    suite.check('a cylinder pin is made', pm.objExists(pin))
    suite.check('named after its joint', str(pin).endswith('l_upperarm_ref_pin'), str(pin))
    suite.check('a cylinder keeps its girth', abs(pin.scaleX.get() - geometry.CYLINDER_GIRTH) < 0.001)
    suite.check('and is scaled along its length only', abs(pin.scaleY.get() - 2) < 0.001)
    suite.check('it remembers which joint it stands for',
                pin.matchedJoint.get() == 'l_upperarm')
    suite.check('which axis was turned', pin.rotatedAxis.get() == 'rotateZ')
    suite.check('what shape it is', pin.objShape.get() == 'Cylinder')
    suite.check('that it is a pin at all', pin.hasAttr('ref_pin'))
    suite.check('and how big it was asked to be', abs(pin.pinSize.get() - 2) < 0.001)

    sphere_pin = geometry.create_reference_obj(3, 2, 'Sphere', 'rotateX', 'head')
    suite.check('a sphere is scaled evenly',
                abs(sphere_pin.scaleX.get() - 6) < 0.001 and abs(sphere_pin.scaleZ.get() - 6) < 0.001)

    # The bug: this was eval('pm.poly' + whatever_the_data_said + '()[0]').
    suite.check('a shape name that is not a shape answers None rather than running',
                geometry.create_reference_obj(1, 1, 'Cube; import os', 'rotateZ', 'x') is None)

    # -- a skeleton's worth ---------------------------------------------------------------- #
    harness.new_scene()
    root = pm.joint(name='root', position=(0, 0, 0))
    upper = pm.joint(name='l_upperarm', position=(0, 5, 0))
    lower = pm.joint(name='l_lowerarm', position=(0, 10, 0))
    end = pm.joint(name='l_hand_end', position=(0, 15, 0))
    joints = [root, upper, lower, end]

    namespace.set_namespace('')
    data = {'region_rotations': {'l_upperarm': ('rotateZ', 3, 'Cylinder')},
            'ignore_types': ['_end']}
    group = geometry.make_pins(joints, 1, data, delete_joint_list=False)
    suite.check('a group of pins comes back', pm.objExists(group))
    children = group.getChildren()
    suite.check('one per joint, bar the ones in ignore_types', len(children) == 3, str(children))
    suite.check('and the namespace is put back rather than left at the root',
                pm.namespaceInfo(currentNamespace=True) == ':',
                pm.namespaceInfo(currentNamespace=True))
    suite.check('the pins are built in their own namespace',
                any(geometry.PIN_NAMESPACE in str(child) for child in children), str(children))
    suite.check('the joints are still there when it is told to keep them',
                all(pm.objExists(joint) for joint in joints))

    harness.new_scene()
    joints = [pm.joint(name='j0', position=(0, 0, 0)), pm.joint(name='j1', position=(0, 5, 0))]
    merged = geometry.make_pins(joints, 1, {'region_rotations': {}, 'ignore_types': []},
                                merge_pins=True)
    suite.check('merged pins come back as one mesh', pm.objExists(merged))
    suite.check('tagged as the reference pins', merged.hasAttr('ref_pins'))
    suite.check('and the joints are gone by default', not any(pm.objExists(j) for j in joints))

    # The bug: a data file with neither key in it crashed on .keys().
    harness.new_scene()
    joints = [pm.joint(name='k0', position=(0, 0, 0))]
    suite.check('setup data with nothing in it is a warning, not a crash',
                geometry.make_pins(joints, 1, {}, delete_joint_list=False) is not None)

    suite.check('apply_cube_trick had no callers and is gone',
                not hasattr(geometry, 'apply_cube_trick'))


# --------------------------------------------------------------------------------------- #
# blendshape_model
# --------------------------------------------------------------------------------------- #
def _blend_setup(pm, tagged=True):
    """A mesh with a tagged blend node and two targets on it."""

    base = pm.polySphere(name='base_mesh')[0]
    smile = pm.polySphere(name='smile')[0]
    frown = pm.polySphere(name='frown')[0]
    blendnode = pm.blendShape(smile, frown, base, name='base_blendnode')[0]
    if tagged:
        blendnode.addAttr('blendNodeType', dt='string')
        blendnode.blendNodeType.set('main')
    return base, blendnode, [smile, frown]


def check_blendshape_model(suite, pm):
    import maya.cmds as cmds
    from mca.mya.modeling import blendshape_model

    harness.new_scene()
    base, blendnode, targets = _blend_setup(pm)

    suite.check('the blend node on a mesh is found',
                blendshape_model.get_all_blendnodes(base) == [blendnode])
    suite.check('and the first of them', blendshape_model.get_first_blendnode(base) == blendnode)
    suite.check('a blend node passes straight through',
                blendshape_model.get_first_blendnode(blendnode) == blendnode)

    shapes = blendshape_model.get_blendnode_shapes(blendnode)
    suite.check('its targets are named', sorted(shapes) == ['frown', 'smile'], str(shapes))
    suite.check('a mesh can be asked instead of the node',
                blendshape_model.get_blendnode_shapes(base) == shapes)

    indexes = blendshape_model.get_blendnode_index_as_dict(blendnode)
    suite.check('each target has its weight index', sorted(indexes) == ['frown', 'smile'],
                str(indexes))
    suite.check('and the indexes are the real ones',
                sorted(indexes.values()) == [0, 1], str(indexes))

    # The bug: pm.ls(pm.listHistory(x), type='blendShape')[0] on anything that is not a blend
    # node - a mesh with none on it, say - is an IndexError.
    harness.new_scene()
    bare = pm.polySphere(name='no_blends')[0]
    suite.check('a mesh with no blend node answers an empty list rather than raising',
                blendshape_model.get_blendnode_shapes(bare) == [])
    suite.check('and an empty mapping', blendshape_model.get_blendnode_index_as_dict(bare) == {})
    suite.check('and no blend nodes', blendshape_model.get_all_blendnodes(bare) == [])
    suite.check('and nothing to delete', blendshape_model.delete_blendshapes(bare) == [])

    # -- an untagged node in front of a tagged one ----------------------------------------- #
    harness.new_scene()
    base, blendnode, targets = _blend_setup(pm)
    extra_target = pm.polySphere(name='extra')[0]
    untagged = pm.blendShape(extra_target, base, name='untagged_blendnode',
                             frontOfChain=True)[0]
    found = blendshape_model.get_all_blendnodes(base)
    suite.check('an untagged blend node is not mistaken for one of ours',
                blendnode in found and untagged not in found, str(found))

    # -- per-vertex weights ----------------------------------------------------------------- #
    harness.new_scene()
    base, blendnode, targets = _blend_setup(pm)
    vertex_count = pm.polyEvaluate(base, vertex=True)
    suite.check('every vertex of the first target is set',
                blendshape_model.set_blendshape_weights(blendnode, 0) == vertex_count)
    suite.check('to what it was asked for',
                blendnode.inputTarget[0].inputTargetGroup[0].targetWeights[0].get() == 0)
    suite.check('a mesh can be given instead of the node',
                blendshape_model.set_blendshape_weights(base, 1) == vertex_count)

    suite.check('set_blendshape_weights_from_mesh was the same function twice and is gone',
                not hasattr(blendshape_model, 'set_blendshape_weights_from_mesh'))
    suite.check('get_active_attribute had no callers and is gone',
                not hasattr(blendshape_model, 'get_active_attribute'))

    # -- deleting targets -------------------------------------------------------------------- #
    harness.new_scene()
    base, blendnode, targets = _blend_setup(pm)
    deleted = blendshape_model.delete_blendshapes(blendnode)
    suite.check('the target meshes are deleted', sorted(deleted) == ['frown', 'smile'], str(deleted))
    suite.check('and are gone from the scene', not any(pm.objExists(t) for t in targets))
    suite.check('running it again is not an error',
                blendshape_model.delete_blendshapes(blendnode) == [])

    # -- duplicating a mesh ------------------------------------------------------------------ #
    harness.new_scene()
    mesh = pm.polySphere(name='rigged_mesh')[0]
    mesh.addAttr('rig_marker', dt='string')
    mesh.translateX.lock()
    copy = blendshape_model.duplicate_mesh(mesh, label='pose_copy')
    suite.check('the copy is made', pm.objExists(copy) and str(copy) == 'pose_copy', str(copy))
    suite.check('and its channels are unlocked, so it can be sculpted',
                not copy.translateX.isLocked())
    suite.check('a named attribute can be taken off it',
                not blendshape_model.duplicate_mesh(mesh, label='no_marker',
                                                    remove_attrs=('rig_marker',))
                .hasAttr('rig_marker'))
    suite.check("and everything the rig added, when that's what is wanted",
                not blendshape_model.duplicate_mesh(mesh, label='clean',
                                                    remove_user_attrs=True).hasAttr('rig_marker'))

    harness.new_scene()
    mesh = pm.polySphere(name='replace_me')[0]
    replaced = blendshape_model.dup_and_delete_mesh(mesh)
    suite.check('replacing a mesh keeps its name', str(replaced) == 'replace_me', str(replaced))
    suite.check('and the original is gone', not pm.objExists(mesh))

    # -- a parallel node ---------------------------------------------------------------------- #
    harness.new_scene()
    neutral = pm.polySphere(name='neutral')[0]
    pose = pm.polySphere(name='pose')[0]
    live = pm.polySphere(name='live')[0]
    parallel = blendshape_model.create_parallel_blendnode(neutral, pose, live)
    suite.check('a parallel node is made', pm.objExists(parallel))
    suite.check('with both of its targets fully on',
                parallel.weight[0].get() == 1 and parallel.weight[1].get() == 1)

    # -- symmetry ------------------------------------------------------------------------------ #
    if cmds.contextInfo('artAttrBlendShapeContext', exists=True):
        suite.check('reflection goes on for a centre pose',
                    blendshape_model.set_blendshape_weight_symmetry('center', True) is True)
        suite.check('and off for a side one',
                    blendshape_model.set_blendshape_weight_symmetry('left', True) is False)
    else:
        suite.note('artAttrBlendShapeContext', 'not available in this Maya')


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_vert_utils(suite, pm)
    check_surface(suite, pm)
    check_follicle(suite, pm)
    check_geometry(suite, pm)
    check_blendshape_model(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('modeling', body))
