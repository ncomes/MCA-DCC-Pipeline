"""
The node that records which of a character's meshes is which, in a real Maya.

    mayapy tests/test_frag_mesh_component.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm):
    """A short chain of joints for a rig root to be built on."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    return [pm.PyNode(cmds.joint(name='root' if not index else 'b_spine_{0:02d}'.format(index),
                                 position=(0, index * 10, 0), absolute=True))
            for index in range(3)]


def _skeletal_mesh(pm, modules):
    """A rig root and a skeletal mesh node, which is what a mesh component hangs under."""

    joints = _skeleton(pm)
    root_node = modules['frag_root'].FRAGRoot.create(joints[0], 'player', 'mesh_asset')
    return modules['skeletal_mesh'].SkeletalMesh.create(root_node)


def _meshes(pm, *names):
    """One cube per name, so a category has something to point at."""

    return [pm.polyCube(name=name)[0] for name in names]


def check_creating(suite, pm, modules):
    mesh_component = modules['mesh_component']

    harness.new_scene()
    sk_mesh = _skeletal_mesh(pm, modules)
    head, mouth, card_left, card_right, source = _meshes(
        pm, 'head', 'mouth', 'lashes_left', 'lashes_right', 'head_source')

    component = mesh_component.MeshComponent.create(sk_mesh, {
        'skin_mesh': {'head_mesh': head, 'mouth_mesh': mouth,
                      'eye_cards_left': [card_left], 'eye_cards_right': [card_right]},
        'source_mesh': {'head_mesh': source}})

    suite.check('a mesh component is built', component is not None)
    suite.check('under the skeletal mesh node', component.get_frag_parent() == sk_mesh,
                str(component.get_frag_parent()))
    suite.check('with one category per entry in the dictionary',
                sorted(component.get_all_categories()) == ['skin_mesh', 'source_mesh'],
                str(component.get_all_categories()))
    suite.check('every mesh in a category is found, each once',
                sorted(str(mesh) for mesh in component.get_all_category_meshes('skin_mesh'))
                == ['head', 'lashes_left', 'lashes_right', 'mouth'],
                str(component.get_all_category_meshes('skin_mesh')))
    suite.check('a category the node does not have answers nothing rather than raising',
                component.get_all_category_meshes('no_such_category') is None)

    # -- one mesh at a time --------------------------------------------------------------- #
    suite.check('a mesh is looked up by its category and its name',
                component.get_mesh('head_mesh', 'skin_mesh') == head,
                str(component.get_mesh('head_mesh', 'skin_mesh')))
    suite.check('the same name in another category answers that category\'s mesh',
                component.get_mesh('head_mesh', 'source_mesh') == source,
                str(component.get_mesh('head_mesh', 'source_mesh')))
    suite.check('a name holding a list answers the whole list',
                component.get_mesh_list('eye_cards_left', 'skin_mesh') == [card_left],
                str(component.get_mesh_list('eye_cards_left', 'skin_mesh')))
    suite.check('and a name holding one mesh answers a list of one',
                component.get_mesh_list('head_mesh', 'skin_mesh') == [head],
                str(component.get_mesh_list('head_mesh', 'skin_mesh')))

    # The bug: both of these evaluated self.pynode.attr(category) inside the guard meant to stop
    # exactly this, so a missing category was a MayaAttributeError.
    suite.check('a category the node does not have answers nothing rather than raising',
                component.get_mesh('head_mesh', 'no_such_category') is None)
    suite.check('for the list lookup too',
                component.get_mesh_list('head_mesh', 'no_such_category') is None)
    suite.check('a name the category does not have answers nothing',
                component.get_mesh('no_such_mesh', 'skin_mesh') is None)
    suite.check('and the two answer differently for "no such name" and "nothing wired to it" - '
                'None against an empty list',
                component.get_mesh_list('no_such_mesh', 'skin_mesh') is None)

    empty_named = mesh_component.MeshComponent.create(sk_mesh, {'spare': {'nothing_yet': None}})
    suite.check('a name built with nothing on the end of it answers an empty list',
                empty_named.get_mesh_list('nothing_yet', 'spare') == [],
                str(empty_named.get_mesh_list('nothing_yet', 'spare')))
    suite.check('and the single lookup answers nothing for it',
                empty_named.get_mesh('nothing_yet', 'spare') is None)


def check_the_round_trip(suite, pm, modules):
    mesh_component = modules['mesh_component']

    harness.new_scene()
    sk_mesh = _skeletal_mesh(pm, modules)
    head, mouth, card_left, card_other, source = _meshes(
        pm, 'head', 'mouth', 'lashes_left', 'wetness_left', 'head_source')

    meshes_dict = {'skin_mesh': {'head_mesh': head, 'mouth_mesh': mouth,
                                 'eye_cards_left': [card_left, card_other]},
                   'source_mesh': {'head_mesh': source},
                   'spare_mesh': {'nothing_yet': None}}
    component = mesh_component.MeshComponent.create(sk_mesh, meshes_dict)

    # The bug: two lists paired by position, with the attribute list offset by one onto the hidden
    # bool child set_compound_attribute_groups adds. Every mesh came back under the wrong name, the
    # first of every category under the key '_hidden', and the last attribute fell off the end.
    found = component.get_connections_as_dict()
    suite.check('every category comes back',
                sorted(found) == ['skin_mesh', 'source_mesh'], str(sorted(found)))
    suite.check('a category whose names have nothing wired to them is left out, because the '
                'dictionary describes what is there',
                'spare_mesh' not in found, str(sorted(found)))
    suite.check('each mesh comes back under the name it went in under',
                found['skin_mesh']['head_mesh'] == head
                and found['skin_mesh']['mouth_mesh'] == mouth
                and found['source_mesh']['head_mesh'] == source,
                str(found))
    suite.check('a name that went in holding a list comes back holding the list, in order',
                found['skin_mesh']['eye_cards_left'] == [card_left, card_other],
                str(found['skin_mesh'].get('eye_cards_left')))
    suite.check('and the hidden bool child every compound carries is not mistaken for a mesh',
                not any(name.startswith('_') for category in found.values() for name in category),
                str(found))

    # The round trip: what it answers is what create takes.
    rebuilt = mesh_component.MeshComponent.create(sk_mesh, found)
    suite.check('handing what it answers back to create builds the same node again',
                rebuilt.get_connections_as_dict() == found,
                str(rebuilt.get_connections_as_dict()))

    suite.check('the child attributes of a category are there to be read, hidden one and all',
                len(component.get_all_attrs_from_category('skin_mesh')) == 4,
                str(component.get_all_attrs_from_category('skin_mesh')))
    suite.check('and asking about a category that is not there answers nothing',
                component.get_all_attrs_from_category('no_such_category') is None)


def check_the_blendshape_group(suite, pm, modules):
    mesh_component = modules['mesh_component']
    skeletal_mesh = modules['skeletal_mesh']

    harness.new_scene()
    sk_mesh = _skeletal_mesh(pm, modules)
    head_shapes, mouth_shapes, skinned = _meshes(pm, 'head_bs', 'mouth_bs', 'head')
    blendshape_grp = sk_mesh.get_grp_blendshapes()
    suite.check('the skeletal mesh node has a blendshape group to put them in',
                blendshape_grp is not None)

    component = mesh_component.MeshComponent.create(sk_mesh, {
        mesh_component.BLENDSHAPE_CATEGORY: {'head_mesh': head_shapes,
                                             'mouth_mesh': mouth_shapes},
        'skin_mesh': {'head_mesh': skinned}})

    suite.check('the meshes that drive a face are moved under the blendshape group',
                head_shapes.getParent() == blendshape_grp
                and mouth_shapes.getParent() == blendshape_grp,
                '{0}, {1}'.format(head_shapes.getParent(), mouth_shapes.getParent()))
    suite.check('and the skinned meshes are left where they are',
                skinned.getParent() is None, str(skinned.getParent()))
    suite.check('the category name is the one the mesh markup uses for the same meshes',
                mesh_component.BLENDSHAPE_CATEGORY == skeletal_mesh.BLENDSHAPE_MESH_REGION)

    # Moving them again is not an error, which is what lets a node be rebuilt in place.
    moved = component.move_blendshape_meshes()
    suite.check('moving them a second time is a no-op rather than an error', len(moved) == 2,
                str(moved))

    # The bug: create called get_grp_blendshapes on whatever its parent was.
    harness.new_scene()
    _meshes(pm, 'head_bs')
    plain_parent = modules['frag_base'].FRAGNode.create(None, 'FRAGRig', 1)
    orphan = mesh_component.MeshComponent.create(
        plain_parent, {mesh_component.BLENDSHAPE_CATEGORY: {'head_mesh': pm.PyNode('head_bs')}})
    suite.check('a parent with no blendshape group leaves the meshes where they are rather than '
                'raising',
                pm.PyNode('head_bs').getParent() is None)
    suite.check('and the node is still built',
                orphan.get_mesh('head_mesh', mesh_component.BLENDSHAPE_CATEGORY) is not None)

    # A rig built with no blendshapes has the group deleted, leaving the attribute pointing at
    # nothing - which is a different case from the attribute not being there.
    harness.new_scene()
    sk_mesh = _skeletal_mesh(pm, modules)
    shapes = _meshes(pm, 'head_bs')[0]
    pm.delete(sk_mesh.get_grp_blendshapes())
    gone = mesh_component.MeshComponent.create(
        sk_mesh, {mesh_component.BLENDSHAPE_CATEGORY: {'head_mesh': shapes}})
    suite.check('a rig whose blendshape group has been deleted leaves the meshes where they are',
                shapes.getParent() is None, str(shapes.getParent()))
    suite.check('and still records them',
                gone.get_mesh('head_mesh', mesh_component.BLENDSHAPE_CATEGORY) == shapes)


def check_reconnecting(suite, pm, modules):
    mesh_component = modules['mesh_component']

    harness.new_scene()
    sk_mesh = _skeletal_mesh(pm, modules)
    head, card_left, card_other = _meshes(pm, 'head', 'lashes_left', 'wetness_left')
    component = mesh_component.MeshComponent.create(sk_mesh, {
        'skin_mesh': {'head_mesh': head, 'eye_cards_left': [card_left]}})

    component.pynode.attr('skin_mesh_head_mesh').disconnect()
    suite.check('a mesh taken off a name is gone from the node',
                component.get_mesh('head_mesh', 'skin_mesh') is None)
    suite.check('and it can be put back', component.reconnect_mesh(head, 'head_mesh', 'skin_mesh'))
    suite.check('where the lookup finds it again',
                component.get_mesh('head_mesh', 'skin_mesh') == head,
                str(component.get_mesh('head_mesh', 'skin_mesh')))

    # The bug: it connected to the array attribute rather than an element of it, so the mesh showed
    # up in the connections at no index - invisible to anything walking the list, and dropped the
    # next time the category was written.
    suite.check('a mesh added to a name that holds a list is wired up',
                component.reconnect_mesh(card_other, 'eye_cards_left', 'skin_mesh'))
    cards = component.pynode.attr('skin_mesh_eye_cards_left')
    suite.check('at an index of its own, so anything walking the list sees it',
                [str(cards[index].listConnections()[0]) for index in cards.getArrayIndices()]
                == ['lashes_left', 'wetness_left'],
                str([(index, cards[index].listConnections())
                     for index in cards.getArrayIndices()]))
    suite.check('and it survives the node being rebuilt from what it answers',
                mesh_component.MeshComponent.create(
                    sk_mesh, component.get_connections_as_dict()
                ).get_mesh_list('eye_cards_left', 'skin_mesh') == [card_left, card_other])

    suite.check('reconnecting into a category that is not there says so rather than raising',
                component.reconnect_mesh(head, 'head_mesh', 'no_such_category') is False)
    suite.check('and into a name that is not there',
                component.reconnect_mesh(head, 'no_such_name', 'skin_mesh') is False)


def check_removing(suite, pm, modules):
    mesh_component = modules['mesh_component']

    harness.new_scene()
    sk_mesh = _skeletal_mesh(pm, modules)
    head, source = _meshes(pm, 'head', 'head_source')
    component = mesh_component.MeshComponent.create(sk_mesh, {
        'skin_mesh': {'head_mesh': head}, 'source_mesh': {'head_mesh': source}})

    suite.check('a category can be taken off the node', component.remove_category('source_mesh'))
    suite.check('and it is gone', component.get_all_categories() == ['skin_mesh'],
                str(component.get_all_categories()))
    suite.check('the mesh it held is still in the scene - the category is removed, not the mesh',
                pm.objExists(source))
    suite.check('removing a category that is not there says so rather than raising',
                component.remove_category('source_mesh') is False)

    # Writing a category that is already there replaces it rather than adding to it.
    component.set_categories({'skin_mesh': {'mouth_mesh': source}})
    suite.check('writing a category again replaces what was in it',
                component.get_connections_as_dict() == {'skin_mesh': {'mouth_mesh': source}},
                str(component.get_connections_as_dict()))


def check_namespaces_and_the_registry(suite, pm, modules):
    import maya.cmds as cmds
    mesh_component = modules['mesh_component']
    frag_base = modules['frag_base']

    harness.new_scene()
    if not cmds.namespace(exists='hero'):
        cmds.namespace(add='hero')
    cmds.namespace(set=':hero')
    sk_mesh = _skeletal_mesh(pm, modules)
    head = _meshes(pm, 'head')[0]
    cmds.namespace(set=':')

    component = mesh_component.MeshComponent.create(sk_mesh, {'skin_mesh': {'head_mesh': head}})
    suite.check('a component built under a rig in a namespace lands in that namespace',
                component.pynode.namespace() == 'hero:', str(component.pynode.namespace()))
    suite.check('and the active namespace is put back afterwards',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True))

    found = frag_base.FRAGNode(component.pynode)
    suite.check('a component read back out of a scene comes back as its own class',
                type(found) is mesh_component.MeshComponent, str(type(found)))
    suite.check('MeshComponent is in the registry, so a rig carrying one can be read back',
                'MeshComponent' in frag_base.FRAGNodeRegister.__frag_node_types__)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_root
    from mca.mya.rigging.frag import mesh_component
    from mca.mya.rigging.frag import skeletal_mesh

    modules = {'frag_base': frag_base, 'frag_root': frag_root,
               'mesh_component': mesh_component, 'skeletal_mesh': skeletal_mesh}

    check_creating(suite, pm, modules)
    check_the_round_trip(suite, pm, modules)
    check_the_blendshape_group(suite, pm, modules)
    check_reconnecting(suite, pm, modules)
    check_removing(suite, pm, modules)
    check_namespaces_and_the_registry(suite, pm, modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_mesh_component', body))
