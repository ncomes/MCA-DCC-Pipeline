"""
Mesh markup: mca.mya.rigging.mesh_markup_rig, in a real Maya.

    mayapy tests/test_mesh_markup.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _head_rig(pm):
    """A head, two eyes and a blend shape target, tagged the way the face pipeline tags them."""

    from mca.mya.rigging import mesh_markup_rig

    head = pm.polySphere(name='head_geo')[0]
    left_eye = pm.polySphere(name='l_eye_geo')[0]
    right_eye = pm.polySphere(name='r_eye_geo')[0]
    smile = pm.polySphere(name='smile_geo')[0]
    untagged = pm.polySphere(name='just_a_prop')[0]

    mesh_markup_rig.MeshMarkup.create(head, 'head_mesh', 'skin_mesh', 'center', region='head')
    mesh_markup_rig.MeshMarkup.create(left_eye, 'left_eye_mesh', 'skin_mesh', 'left',
                                      region='left_eye')
    mesh_markup_rig.MeshMarkup.create(right_eye, 'right_eye_mesh', 'skin_mesh', 'right',
                                      region='right_eye')
    mesh_markup_rig.MeshMarkup.create(smile, 'smile', 'blendshape_mesh', 'center',
                                      region='head', source_mesh='head_geo')
    return {'head': head, 'left_eye': left_eye, 'right_eye': right_eye, 'smile': smile,
            'untagged': untagged}


# --------------------------------------------------------------------------------------- #
# MeshMarkup
# --------------------------------------------------------------------------------------- #
def check_mesh_markup(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import mesh_markup_rig

    harness.new_scene()
    mesh = pm.polySphere(name='a_mesh')[0]
    bare = pm.polySphere(name='a_bare_mesh')[0]

    # -- an untagged mesh: the bug ------------------------------------------------------- #
    # Every read went through get_dict, which read an attribute that is not there.
    markup = mesh_markup_rig.MeshMarkup(bare)
    suite.check('an untagged mesh says it is untagged', markup.is_marked_up is False)
    suite.check('and answers an empty dictionary rather than raising', markup.get_dict() == {})
    suite.check('and None for any entry it is asked about', markup.region is None)
    suite.check('and for an entry that is not in the schema at all',
                markup.get_mesh_entry('nonsense') is None)
    suite.check('clearing markup it does not have is a no, not a raise',
                markup.clear_markup() is False)
    suite.check('and so is removing it', markup.remove_markup() is False)
    suite.check('writing to it says so rather than raising', markup.set_dict({'a': 'b'}) is False)

    # -- tagging one ---------------------------------------------------------------------- #
    markup = mesh_markup_rig.MeshMarkup.create(mesh, 'head_mesh', 'skin_mesh', 'center',
                                               region='head')
    suite.check('tagging a mesh adds the attribute', mesh.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP))
    suite.check('and it says it is tagged', markup.is_marked_up is True)
    suite.check('the positional entries are stored',
                (markup.type_name, markup.category, markup.side) ==
                ('head_mesh', 'skin_mesh', 'center'), str(markup.get_dict()))
    suite.check('and so is anything passed as a keyword', markup.region == 'head')
    suite.check('the markup is the mesh it was given', markup.mesh == mesh)

    # -- every entry in the schema --------------------------------------------------------- #
    for entry, _doc in mesh_markup_rig.MARKUP_ENTRIES:
        setattr(markup, entry, 'value_for_{0}'.format(entry))
    suite.check('every entry in the schema reads back what was written to it',
                all(markup.get_mesh_entry(entry) == 'value_for_{0}'.format(entry)
                    for entry, _doc in mesh_markup_rig.MARKUP_ENTRIES),
                str(markup.get_dict()))
    suite.check('and there are ten of them', len(mesh_markup_rig.MARKUP_ENTRIES) == 10,
                str(len(mesh_markup_rig.MARKUP_ENTRIES)))
    suite.check('each one documents itself',
                all(getattr(mesh_markup_rig.MeshMarkup, entry).__doc__
                    for entry, _doc in mesh_markup_rig.MARKUP_ENTRIES))

    # -- one entry at a time ----------------------------------------------------------------- #
    harness.new_scene()
    mesh = pm.polySphere(name='updating')[0]
    markup = mesh_markup_rig.MeshMarkup.create(mesh, 'head_mesh', 'skin_mesh', 'center')
    markup.region = 'head'
    suite.check('setting one entry leaves the rest alone',
                markup.get_dict() == {'type_name': 'head_mesh', 'category': 'skin_mesh',
                                      'side': 'center', 'region': 'head'},
                str(markup.get_dict()))

    # -- the bug: an empty dictionary could not be written ------------------------------------ #
    suite.check('the markup can be emptied', markup.set_dict({}) is True)
    suite.check('and then it really is empty', markup.get_dict() == {}, str(markup.get_dict()))
    suite.check('while the mesh is still recognisably one of ours', markup.is_marked_up is True)

    # -- the bug: markup that is not valid JSON took the build down ---------------------------- #
    mesh.attr(mesh_markup_rig.MCA_MESH_MARKUP).set('{"region": "head", trunca')
    suite.check('markup that is not valid JSON reads as untagged rather than raising',
                markup.get_dict() == {})
    suite.check('and so does every entry on it', markup.region is None)

    # -- clearing and removing ------------------------------------------------------------------ #
    harness.new_scene()
    mesh = pm.polySphere(name='clearing')[0]
    markup = mesh_markup_rig.MeshMarkup.create(mesh, 'head_mesh', 'skin_mesh', 'center')
    suite.check('clearing empties the markup', markup.clear_markup() is True)
    suite.check('but leaves the attribute', mesh.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP))
    suite.check('and an empty string reads as an empty dictionary', markup.get_dict() == {})
    suite.check('removing takes the attribute off', markup.remove_markup() is True)
    suite.check('and it is gone', not mesh.hasAttr(mesh_markup_rig.MCA_MESH_MARKUP))

    # -- tagging one twice ----------------------------------------------------------------------- #
    harness.new_scene()
    mesh = pm.polySphere(name='retagged')[0]
    mesh_markup_rig.MeshMarkup.create(mesh, 'head_mesh', 'skin_mesh', 'center', region='head')
    markup = mesh_markup_rig.MeshMarkup.create(mesh, 'jaw_mesh', 'skin_mesh', 'center')
    suite.check('tagging a mesh again replaces what was there',
                markup.get_dict() == {'type_name': 'jaw_mesh', 'category': 'skin_mesh',
                                      'side': 'center'}, str(markup.get_dict()))


# --------------------------------------------------------------------------------------- #
# RigMeshMarkup
# --------------------------------------------------------------------------------------- #
def check_rig_mesh_markup(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import mesh_markup_rig

    harness.new_scene()
    meshes = _head_rig(pm)

    rig_markup = mesh_markup_rig.RigMeshMarkup.create()
    suite.check('every tagged mesh in the scene is found',
                len(rig_markup.mesh_list) == 4, str(len(rig_markup.mesh_list)))
    suite.check('and the untagged one is not',
                meshes['untagged'] not in [markup.mesh for markup in rig_markup.mesh_list])

    suite.check('nothing to gather is not an error',
                mesh_markup_rig.RigMeshMarkup([]).mesh_list == [])

    # The bug: get_mesh_markups defaulted to self.mesh_list, which is already wrapped.
    suite.raises('wrapping needs a list to wrap - there is no default to get wrong',
                 rig_markup.get_mesh_markups)
    suite.check('and the wrappers are not wrapped again',
                all(isinstance(markup.mesh, pm.nt.Transform) for markup in rig_markup.mesh_list))

    # -- by category --------------------------------------------------------------------- #
    by_category = rig_markup.get_dict()
    suite.check('the meshes come back by category then type',
                sorted(by_category) == ['blendshape_mesh', 'skin_mesh'], str(sorted(by_category)))
    suite.check('with the mesh itself at the end of it',
                by_category['skin_mesh']['head_mesh'] == meshes['head'],
                str(by_category['skin_mesh']))

    skin_meshes = rig_markup.get_mesh_list_in_category('skin_mesh')
    suite.check('a category gives up its meshes', len(skin_meshes) == 3, str(skin_meshes))
    suite.check('with the head first, because the face tools drive the rest from it',
                skin_meshes[0] == meshes['head'], str(skin_meshes))
    suite.check('and as names when they are asked for',
                rig_markup.get_mesh_list_in_category('skin_mesh', as_string=True)[0] == 'head_geo')
    suite.check('a category nobody used is empty',
                rig_markup.get_mesh_list_in_category('cloth_mesh') == [])

    # -- by region ------------------------------------------------------------------------- #
    head_meshes = rig_markup.get_mesh_list_in_region('head')
    suite.check('a region gives up its meshes', len(head_meshes) == 2, str(head_meshes))
    suite.check('whatever category they are in',
                meshes['head'] in head_meshes and meshes['smile'] in head_meshes)
    suite.check('a region nobody used is empty',
                rig_markup.get_mesh_list_in_region('tail') == [])
    suite.check('and names when asked',
                sorted(rig_markup.get_mesh_list_in_region('head', as_string=True)) ==
                ['head_geo', 'smile_geo'],
                str(rig_markup.get_mesh_list_in_region('head', as_string=True)))

    region_dict = rig_markup.get_region_dict()
    suite.check('the region lookup covers every region',
                sorted(region_dict) == ['head', 'left_eye', 'right_eye'], str(sorted(region_dict)))
    suite.check('naming each type and its category',
                region_dict['head'] == {'head_mesh': 'skin_mesh', 'smile': 'blendshape_mesh'},
                str(region_dict['head']))

    # get_blendshape_region_dict was this function with one `if` in it.
    blendshape_dict = rig_markup.get_region_dict(
        category=mesh_markup_rig.BLENDSHAPE_CATEGORY)
    suite.check('and it can be narrowed to one category',
                blendshape_dict == {'head': {'smile': 'blendshape_mesh'}}, str(blendshape_dict))
    suite.check('the function it replaces is gone',
                not hasattr(mesh_markup_rig.RigMeshMarkup, 'get_blendshape_region_dict'))

    # -- the region dictionary that changes shape --------------------------------------------- #
    dict_in_region = rig_markup.get_mesh_dict_list_in_region('head')
    suite.check('a region can be asked for its meshes against their markup',
                sorted(str(mesh) for mesh in dict_in_region) == ['head_geo', 'smile_geo'],
                str(list(dict_in_region)))
    suite.check('and the markup is there to read',
                dict_in_region[meshes['head']].type_name == 'head_mesh')
    suite.check('asking for strings changes the shape of the answer, which is how it is used',
                sorted(rig_markup.get_mesh_dict_list_in_region('head', as_string=True)) ==
                ['head_geo', 'smile_geo'])

    # -- in a namespace ------------------------------------------------------------------------ #
    harness.new_scene()
    pm.namespace(add='character')
    pm.namespace(set='character')
    meshes = _head_rig(pm)
    pm.namespace(set=':')
    loose = pm.polySphere(name='outside_geo')[0]
    mesh_markup_rig.MeshMarkup.create(loose, 'prop_mesh', 'skin_mesh', 'center', region='prop')

    rig_markup = mesh_markup_rig.RigMeshMarkup.create('character')
    suite.check('a namespace gathers only its own meshes',
                len(rig_markup.mesh_list) == 4, str([str(m.mesh) for m in rig_markup.mesh_list]))
    suite.check('and the one outside it is left alone',
                loose not in [markup.mesh for markup in rig_markup.mesh_list])


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_mesh_markup(suite, pm)
    check_rig_mesh_markup(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('mesh_markup', body))
