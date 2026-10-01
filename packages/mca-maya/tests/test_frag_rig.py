"""
A FRAG rig's root, its geometry, its groups and its display layers, in a real Maya.

    mayapy tests/test_frag_rig.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=3, namespace_name=None):
    """A short chain of joints, optionally inside a namespace."""

    import maya.cmds as cmds

    if namespace_name:
        if not cmds.namespace(exists=namespace_name):
            cmds.namespace(add=namespace_name)
        cmds.namespace(set=':{0}'.format(namespace_name))
    cmds.select(clear=True)
    joints = [pm.PyNode(cmds.joint(name='root' if not index else 'b_spine_{0:02d}'.format(index),
                                  position=(0, index * 20, 0), absolute=True))
              for index in range(count)]
    cmds.namespace(set=':')
    return joints


def _rig(pm, frag_root, skeletal_mesh, frag_rig, namespace_name=None, with_meshes=True):
    """A whole rig: a skeleton, a root, a skeletal mesh node and a rig, in that order."""

    joints = _skeleton(pm, namespace_name=namespace_name)
    if with_meshes:
        import maya.cmds as cmds
        if namespace_name:
            cmds.namespace(set=':{0}'.format(namespace_name))
        mesh = pm.polyCube(name='the_body')[0]
        cmds.namespace(set=':')
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    mesh_node = skeletal_mesh.SkeletalMesh.create(root_node, variant='summer', variant_version=3)
    rig_node = frag_rig.FRAGRig.create(root_node)
    return joints, root_node, mesh_node, rig_node


def check_the_root(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig, display_layers):
    harness.new_scene()
    joints = _skeleton(pm)
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')

    suite.check('a rig root is built', root_node is not None)
    suite.check('carrying what kind of asset it is', root_node.asset_type == 'player',
                str(root_node.asset_type))
    suite.check('and the asset id it was built for',
                root_node.asset_id == 'an_unknown_asset', str(root_node.asset_id))
    # The registry has no record of it, which is a reasonable thing to store and worth saying.
    suite.check('an asset id the registry does not know gets a name that says so',
                root_node.asset_name == frag_root.MISSING_ASSET_NAME, str(root_node.asset_name))
    suite.check('and it is marked as a rig root',
                root_node.has_attribute(frag_base.IS_FRAG_ROOT_ATTR))
    suite.check('the skeleton it was built on is on it', root_node.root_joint == joints[0])
    suite.check('and the joint knows which rig it is the root of',
                root_node.pynode in
                joints[0].attr(frag_root.FRAG_ROOT_JOINT_ATTR).listConnections())

    root_node.asset_id = 'another_asset'
    suite.check('the asset id can be changed', root_node.asset_id == 'another_asset')
    root_node.asset_id = 'an_unknown_asset'

    suite.check('a rig root knows it is one', frag_root.is_frag_root(root_node))
    suite.check('by node as well as by wrapper', frag_root.is_frag_root(root_node.pynode))
    suite.check('a transform is not one', not frag_root.is_frag_root(pm.polyCube()[0]))

    component = frag_base.FRAGNode.create(root_node, 'FRAGRig', 1)
    suite.check('a component is not a rig root', not frag_root.is_frag_root(component))
    suite.check('the root is found from something under it',
                frag_root.get_frag_root(component) == root_node)
    suite.check('and from itself', frag_root.get_frag_root(root_node) == root_node)
    suite.check('something that is not in a rig has no root',
                frag_root.get_frag_root(pm.polyCube()[0]) is None)

    suite.check('the root joint is found from anything in the rig',
                frag_root.get_root_joint(component) == joints[0])
    # AttributeError on None before.
    suite.check('and asking about something that is not in a rig answers nothing rather than '
                'raising',
                frag_root.get_root_joint(pm.polyCube()[0]) is None)

    # -- finding them in a scene --------------------------------------------------------------- #
    harness.new_scene()
    first = frag_root.FRAGRoot.create(_skeleton(pm, namespace_name='hero')[0], 'player', 'hero_id')
    second = frag_root.FRAGRoot.create(_skeleton(pm, namespace_name='villain')[0], 'player',
                                       'villain_id')
    roots = frag_root.get_all_frag_roots()
    suite.check('every rig root in the scene is found, namespaces and all', len(roots) == 2,
                str(roots))
    suite.check('one can be found by the asset it was built for',
                frag_root.get_frag_root_by_assetid('villain_id') == second)
    suite.check('and an asset that is not in the scene answers nothing',
                frag_root.get_frag_root_by_assetid('nobody') is None)

    # The bug: it wrapped everything carrying the attribute, and a node from a pre-FRAG rig or from
    # another project's packages cannot be wrapped - so one of them raised the whole walk.
    stranger = pm.createNode('network', n='someone_elses_root')
    stranger.addAttr(frag_base.IS_FRAG_ROOT_ATTR, at='bool', dv=True)
    stranger.addAttr(frag_base.FRAG_TYPE_ATTR, dt='string')
    stranger.attr(frag_base.FRAG_TYPE_ATTR).set('ARootFromAnotherProject')
    suite.check('a root this pipeline cannot wrap is left out rather than stopping the walk',
                len(frag_root.get_all_frag_roots()) == 2,
                str(frag_root.get_all_frag_roots()))
    suite.check('and looking one up by asset id steps over it too',
                frag_root.get_frag_root_by_assetid('hero_id') == first)


def check_the_geometry(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig, display_layers):
    import maya.cmds as cmds

    harness.new_scene()
    joints = _skeleton(pm)
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    suite.raises('a skeletal mesh cannot hang under anything but a rig root',
                 skeletal_mesh.SkeletalMesh.create,
                 frag_base.FRAGNode.create(root_node, 'FRAGRig', 1))

    harness.new_scene()
    joints = _skeleton(pm)
    body = pm.polyCube(name='the_body')[0]
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    mesh_node = skeletal_mesh.SkeletalMesh.create(root_node, variant='summer', variant_version=3)

    # The bug: `variant` was added and never written to, and `variantVersion` was set to a literal
    # 1.
    suite.check('the variant a rig was built for is recorded on the node',
                mesh_node.variant == 'summer', str(mesh_node.variant))
    suite.check('and the version of that variant',
                mesh_node.variant_version == 3.0, str(mesh_node.variant_version))
    suite.check('both are in the build arguments as well',
                mesh_node.get_attr('buildKwargs_variant') == 'summer')

    skins_grp = mesh_node.get_grp_skins()
    blendshapes_grp = mesh_node.get_grp_blendshapes()
    suite.check('a group is built for the skinned meshes and one for the blendshape meshes',
                str(skins_grp) == skeletal_mesh.GRP_SKINS and
                str(blendshapes_grp) == skeletal_mesh.GRP_BLENDSHAPES,
                '{0} and {1}'.format(skins_grp, blendshapes_grp))
    suite.check('each marked so it can be recognised from the outside',
                skins_grp.hasAttr(skeletal_mesh.IS_GRP_SKINS_ATTR) and
                blendshapes_grp.hasAttr(skeletal_mesh.IS_GRP_BLENDSHAPES_ATTR))
    suite.check('and neither inherits its parents\' transform, because the meshes carry their own '
                'place in the world',
                not skins_grp.inheritsTransform.get() and
                not blendshapes_grp.inheritsTransform.get())
    suite.check('the scene\'s mesh is gathered under the skins group',
                body.getParent() == skins_grp, str(body.getParent()))

    # The bug: this looked at every mesh in the scene, while the blendshape half beside it works
    # through the rig's markup and is namespace-aware - so a build took another character's
    # geometry.
    harness.new_scene()
    outsider = pm.polyCube(name='someone_elses_mesh')[0]
    joints = _skeleton(pm, namespace_name='hero')
    cmds.namespace(set=':hero')
    hero_body = pm.polyCube(name='the_body')[0]
    cmds.namespace(set=':')
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    mesh_node = skeletal_mesh.SkeletalMesh.create(root_node)
    suite.check('only the rig\'s own meshes are gathered',
                mesh_node.get_all_meshes_from_scene() == [hero_body],
                str(mesh_node.get_all_meshes_from_scene()))
    suite.check('a mesh belonging to something else in the scene is left where it was',
                outsider.getParent() is None, str(outsider.getParent()))

    # What get_meshes_w_grps answers, pinned down: the top of each hierarchy, not the mesh. A mesh
    # parented under a joint therefore brings the whole skeleton with it.
    harness.new_scene()
    joints = _skeleton(pm)
    held_mesh = pm.polyCube(name='a_held_prop')[0]
    held_mesh.setParent(joints[-1])
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    mesh_node = frag_base.FRAGNode.create(root_node, 'SkeletalMesh', 1)
    suite.check('a mesh is gathered by the top of whatever it is under, so an artist\'s groups '
                'survive',
                mesh_node.get_meshes_w_grps() == [joints[0]],
                str(mesh_node.get_meshes_w_grps()))

    # -- finding the node from anywhere -------------------------------------------------------- #
    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)
    suite.check('the skeletal mesh node is found from another of the rig\'s nodes',
                skeletal_mesh.get_frag_skeletal_mesh(rig_node.pynode) == mesh_node)
    suite.check('and from a plain node in the rig\'s hierarchy',
                skeletal_mesh.get_frag_skeletal_mesh(rig_node.all_grp) == mesh_node)
    suite.check('both answers are the node wrapped as its own class, not a raw network node',
                isinstance(skeletal_mesh.get_frag_skeletal_mesh(rig_node.all_grp),
                           skeletal_mesh.SkeletalMesh))

    # FRAGNode(None) gets as far as pm.PyNode(None), which raises.
    dangling = pm.spaceLocator(name='a_dangling_node')
    dangling.addAttr(frag_base.FRAG_PARENT_ATTR, at='message')
    suite.check('a node whose frag parent is connected to nothing answers nothing rather than '
                'raising',
                skeletal_mesh.get_frag_skeletal_mesh(dangling) is None)

    suite.check('the skins group is found from anything in the rig',
                skeletal_mesh.get_group_skins(rig_node.pynode) == mesh_node.get_grp_skins())
    # AttributeError on None before.
    suite.check('and asking about something not in a rig answers nothing',
                skeletal_mesh.get_group_skins(pm.polyCube()[0]) is None and
                skeletal_mesh.get_group_blendshapes(pm.polyCube()[0]) is None)


def check_the_rig(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig, display_layers):
    harness.new_scene()
    joints = _skeleton(pm)
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    suite.raises('a rig cannot be built under anything but a rig root',
                 frag_rig.FRAGRig.create, frag_base.FRAGNode.create(root_node, 'FRAGRig', 1))

    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)

    suite.check('a rig has a group at the top, named for the asset',
                str(rig_node.all_grp) == '{0}{1}'.format(frag_root.MISSING_ASSET_NAME,
                                                         frag_rig.ALL_GROUP_SUFFIX),
                str(rig_node.all_grp))
    suite.check('a group for the machinery and a group for the controls',
                str(rig_node.do_not_touch) == frag_rig.DO_NOT_TOUCH_GROUP and
                str(rig_node.flags_all) == frag_rig.FLAGS_ALL_GROUP,
                '{0} and {1}'.format(rig_node.do_not_touch, rig_node.flags_all))
    suite.check('both parented under the top one',
                rig_node.do_not_touch.getParent() == rig_node.all_grp and
                rig_node.flags_all.getParent() == rig_node.all_grp)
    suite.check('the skeleton with them', joints[0].getParent() == rig_node.all_grp,
                str(joints[0].getParent()))
    suite.check('and the geometry',
                mesh_node.get_grp_skins().getParent() == rig_node.all_grp,
                str(mesh_node.get_grp_skins().getParent()))
    # A rig with no blendshapes has no use for the group.
    suite.check('the blendshape group is gone, because this rig has no blendshapes',
                mesh_node.get_grp_blendshapes() is None)
    suite.check('the rig knows which root it belongs to', rig_node.get_root() == root_node)
    suite.check('and the root knows which rig it has', root_node.get_rig() == rig_node)

    # -- scale ---------------------------------------------------------------------------------- #
    suite.check('a rig is drawn at a scale of one to start with',
                abs(rig_node.rig_scale - 1.0) < 0.0001, str(rig_node.rig_scale))
    rig_node.rig_scale = 2.5
    suite.check('setting it scales the top group on every axis',
                all(abs(rig_node.all_grp.attr(name).get() - 2.5) < 0.0001
                    for name in ('sx', 'sy', 'sz')),
                str(rig_node.all_grp.scale.get()))
    suite.check('and reading it answers what was set',
                abs(rig_node.rig_scale - 2.5) < 0.0001, str(rig_node.rig_scale))
    rig_node.rig_scale = 'not a number'
    suite.check('something that is not a number is refused rather than written',
                abs(rig_node.rig_scale - 2.5) < 0.0001, str(rig_node.rig_scale))
    rig_node.rig_scale = 1.0

    # The bug: the property getter called _scale_components when the attribute was missing, which
    # added it, wired it, and called set_scale() on every component. Reading changed the scene.
    rig_node.pynode.attr(frag_rig.RIG_SCALE_ATTR).delete()
    scale = rig_node.rig_scale
    suite.check('a rig built before the scale existed answers its top group\'s scale',
                abs(scale - 1.0) < 0.0001, str(scale))
    suite.check('and reading it does not put the attribute on the rig',
                not rig_node.has_attribute(frag_rig.RIG_SCALE_ATTR))
    suite.check('wiring it is its own step, which says whether there was anything to do',
                rig_node.add_rig_scale() is True and
                rig_node.has_attribute(frag_rig.RIG_SCALE_ATTR))
    suite.check('and asking again says there was not', rig_node.add_rig_scale() is False)

    # -- finding the rig ------------------------------------------------------------------------ #
    suite.check('a rig is found from its root', frag_rig.get_frag_rig(root_node) == rig_node)
    suite.check('from one of its own nodes', frag_rig.get_frag_rig(mesh_node.pynode) == rig_node)
    suite.check('and from a plain node in its hierarchy',
                frag_rig.get_frag_rig(rig_node.do_not_touch) == rig_node)
    suite.check('something that is not in a rig has none',
                frag_rig.get_frag_rig(pm.polyCube()[0]) is None)

    # -- every rig in the scene ----------------------------------------------------------------- #
    harness.new_scene()
    _rig(pm, frag_root, skeletal_mesh, frag_rig, namespace_name='hero')
    _rig(pm, frag_root, skeletal_mesh, frag_rig, namespace_name='villain')
    # The bug: two wrappers round one node were not equal, so list(set(...)) never removed a repeat,
    # and a root with no rig under it put a None in the list.
    rootless = frag_root.FRAGRoot.create(_skeleton(pm, namespace_name='unbuilt')[0], 'player', 'x')
    rigs = frag_rig.get_frag_rigs()
    suite.check('every rig in the scene is found, once each', len(rigs) == 2, str(rigs))
    suite.check('and a root with no rig built under it yet is left out, rather than putting a None '
                'in the list',
                all(rig is not None for rig in rigs) and rootless.get_rig() is None)


def check_wrapper_equality(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig,
                           display_layers):
    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)

    # The bug: every walk builds a new wrapper, and two of them round one node were not equal.
    suite.check('two wrappers round one node are the same thing',
                root_node.get_rig() == root_node.get_rig())
    suite.check('and a set of them holds one',
                len({root_node.get_rig(), root_node.get_rig(), rig_node}) == 1)
    suite.check('wrappers round different nodes are not the same thing', root_node != rig_node)
    suite.check('a wrapper is not equal to something that is not one',
                not rig_node == rig_node.pynode)
    suite.check('and it says what it is when it is printed',
                repr(rig_node) == 'FRAGRig({0})'.format(rig_node.pynode), repr(rig_node))


def check_display_layers(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig, display_layers):
    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)

    layers_node = display_layers.DisplayLayers.create(rig_node)
    suite.check('a rig gets one display layers node', layers_node is not None)
    suite.check('and asking for it again hands back the one it has',
                display_layers.DisplayLayers.create(rig_node) == layers_node)

    first = pm.spaceLocator(name='on_the_first_layer')
    second = pm.spaceLocator(name='on_the_second_layer')
    layers_node.add_objects([first], 'first_lyr')
    layers_node.add_objects([second], 'second_lyr')

    suite.check('a layer is built for objects that are added to it',
                sorted(layers_node.list_layer_names()) == ['first_lyr', 'second_lyr'],
                str(layers_node.list_layer_names()))
    suite.check('the rig knows it has them',
                layers_node.has_layer('first_lyr') and not layers_node.has_layer('no_such_lyr'))
    suite.check('and what is on each', layers_node.get_members('first_lyr') == [first],
                str(layers_node.get_members('first_lyr')))
    suite.check('a layer that is not there has no members, which is a different answer from an '
                'empty one',
                layers_node.get_members('no_such_lyr') is None)

    # Deliberate: a control belongs to the layer the component that built it put it on.
    layers_node.add_objects([first], 'second_lyr')
    suite.check('an object already on a layer is left where it is',
                layers_node.get_members('second_lyr') == [second],
                str(layers_node.get_members('second_lyr')))

    # The bug: it looked the layer up, used it as a gate, and then moved everything it was handed
    # onto the default layer whatever layer it was actually on.
    layers_node.remove_objects([first, second], 'first_lyr')
    suite.check('taking objects off a layer only takes the ones that are on it',
                layers_node.get_members('first_lyr') == [] and
                layers_node.get_members('second_lyr') == [second],
                '{0} and {1}'.format(layers_node.get_members('first_lyr'),
                                     layers_node.get_members('second_lyr')))
    layers_node.remove_objects([second], 'no_such_lyr')
    suite.check('and asking about a layer that is not there leaves everything alone',
                layers_node.get_members('second_lyr') == [second])

    layers_node.hide_layer('second_lyr')
    suite.check('a layer can be hidden',
                layers_node.get_layer('second_lyr').visibility.get() is False)
    layers_node.show_layer('second_lyr')
    suite.check('and shown', layers_node.get_layer('second_lyr').visibility.get() is True)
    layers_node.set_layer_to_reference('second_lyr')
    suite.check('drawn so it cannot be picked',
                layers_node.get_layer('second_lyr').displayType.get() ==
                display_layers.DISPLAY_TYPE_REFERENCE)
    layers_node.set_layer_to_template('second_lyr')
    suite.check('drawn as a wireframe',
                layers_node.get_layer('second_lyr').displayType.get() ==
                display_layers.DISPLAY_TYPE_TEMPLATE)
    layers_node.remove_state_on_layer('second_lyr')
    suite.check('and back to normal',
                layers_node.get_layer('second_lyr').displayType.get() ==
                display_layers.DISPLAY_TYPE_NORMAL)
    layers_node.hide_layer('no_such_lyr')
    suite.check('asking about a layer that is not there is refused rather than raising', True)

    layers_node.remove_layer('first_lyr')
    suite.check('a layer can be deleted on its own',
                layers_node.list_layer_names() == ['second_lyr'],
                str(layers_node.list_layer_names()))

    # The bug: the last thing remove() did was pm.delete(self) - the wrapper, not the node - which
    # pymel refuses, inside a bare except logged at debug. The node was never deleted.
    layer_names = [str(layer) for layer in layers_node.get_layers()]
    node_name = str(layers_node.pynode)
    layers_node.remove()
    suite.check('removing a rig\'s display layers deletes the layers',
                not any(pm.objExists(name) for name in layer_names), str(layer_names))
    suite.check('and the node that owned them', not pm.objExists(node_name), node_name)


def check_rig_display_layers(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig,
                             display_layers):
    from mca.mya.rigging.flags import frag_flag

    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)

    primary = frag_flag.Flag.create(joints[1], label='a_primary')
    util = frag_flag.Flag.create(joints[2], label='a_util', is_util=True)
    suite.check('a rig answers the controls in its namespace',
                len(rig_node.get_flags()) == 2, str(rig_node.get_flags()))
    suite.check('told apart by what kind they are',
                rig_node.get_primary_flags() == [primary] and
                rig_node.get_util_flags() == [util],
                '{0} and {1}'.format(rig_node.get_primary_flags(), rig_node.get_util_flags()))
    suite.check('and a rig with none of a kind answers an empty list',
                rig_node.get_contact_flags() == [] and rig_node.get_detail_flags() == [])

    layers_node = rig_node.create_display_layers()
    suite.check('the skeleton goes on a layer of its own, hidden and unselectable',
                layers_node.get_layer(display_layers.SKEL_LYR).visibility.get() is False and
                layers_node.get_layer(display_layers.SKEL_LYR).displayType.get() ==
                display_layers.DISPLAY_TYPE_REFERENCE)
    suite.check('the geometry on one that cannot be picked',
                layers_node.get_layer(display_layers.SKIN_LYR).displayType.get() ==
                display_layers.DISPLAY_TYPE_REFERENCE)
    suite.check('and the controls an animator works with on a layer they can see',
                layers_node.get_layer(display_layers.FLAGS_LYR).visibility.get() is True)

    # The bug: the utility controls were added inside the `if detail_flags:` that builds the layer,
    # so a rig with utility controls and no detail controls left them on no layer at all.
    suite.check('a rig with utility controls and no detail controls still gets them on a layer',
                util.node in (layers_node.get_members(display_layers.FLAGS_DETAIL_LYR) or []),
                str(layers_node.get_members(display_layers.FLAGS_DETAIL_LYR)))
    suite.check('hidden',
                layers_node.get_layer(display_layers.FLAGS_DETAIL_LYR).visibility.get() is False)

    # -- a camera rig --------------------------------------------------------------------------- #
    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)
    frag_flag.Flag.create(joints[1], label='a_primary')
    camera = pm.camera()[0]
    layers_node = rig_node.create_display_layers_for_cam(camera)
    suite.check('a camera rig puts the camera on the layer the geometry would be on',
                camera in (layers_node.get_members(display_layers.SKIN_LYR) or []),
                str(layers_node.get_members(display_layers.SKIN_LYR)))
    suite.check('and starts with its controls hidden, because the shot cameras are what gets '
                'animated',
                layers_node.get_layer(display_layers.FLAGS_LYR).visibility.get() is False)


def check_colouring(suite, pm, frag_base, frag_root, skeletal_mesh, frag_rig, display_layers):
    from mca.mya.rigging.flags import frag_flag
    from mca.mya.rigging.frag import keyable_component

    harness.new_scene()
    joints, root_node, mesh_node, rig_node = _rig(pm, frag_root, skeletal_mesh, frag_rig)

    left_component = keyable_component.KeyableComponent.create(rig_node, 'KeyableComponent', 1,
                                                               'left', 'arm')
    odd_component = keyable_component.KeyableComponent.create(rig_node, 'KeyableComponent', 1,
                                                              'top', 'hat')
    left_flag = frag_flag.Flag.create(joints[1], label='a_left_flag')
    odd_flag = frag_flag.Flag.create(joints[2], label='an_odd_flag')
    left_component.connect_node(left_flag, 'theFlag', frag_base.FRAG_PARENT_ATTR)
    odd_component.connect_node(odd_flag, 'theFlag', frag_base.FRAG_PARENT_ATTR)
    sub_flag = frag_flag.Flag.create(joints[0], label='a_sub_flag', is_sub=True)

    rig_node.color_flags()

    suite.check('a control is coloured by the side of the body its component is on',
                all(shape.overrideColor.get() == frag_rig.FLAG_COLOR_BY_SIDE['left']
                    for shape in left_flag.node.getShapes()),
                str([shape.overrideColor.get() for shape in left_flag.node.getShapes()]))
    # The bug: overrideEnabled was switched on with no colour to put in it, leaving the control
    # drawn in whatever index it already had.
    suite.check('a control whose side has no colour is left alone rather than having an override '
                'turned on with nothing in it',
                not any(shape.overrideEnabled.get() for shape in odd_flag.node.getShapes()),
                str([shape.overrideEnabled.get() for shape in odd_flag.node.getShapes()]))
    suite.check('a sub control takes the sub colour, over the side colour it got first',
                all(shape.overrideColor.get() == frag_rig.SUB_FLAG_COLOR
                    for shape in sub_flag.node.getShapes()),
                str([shape.overrideColor.get() for shape in sub_flag.node.getShapes()]))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import display_layers
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import skeletal_mesh
    modules = (frag_base, frag_root, skeletal_mesh, frag_rig, display_layers)
    check_the_root(suite, pm, *modules)
    check_the_geometry(suite, pm, *modules)
    check_the_rig(suite, pm, *modules)
    check_wrapper_equality(suite, pm, *modules)
    check_display_layers(suite, pm, *modules)
    check_rig_display_layers(suite, pm, *modules)
    check_colouring(suite, pm, *modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_rig', body))
