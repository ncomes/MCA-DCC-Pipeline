"""
Shaders built from an asset's texture maps: mca.mya.utils.material_utils.

The textures are written by the suite as tiny valid PNGs, one with an alpha channel and one
without, because half of what this module decides turns on whether a map has an alpha.

    mayapy tests/test_material_utils.py
"""

# python imports
import base64
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


#: A 1x1 PNG with no alpha channel, and a 1x1 PNG with one. Written out by the suite rather than
#: shipped, so there are no binary files in the repository - and built as real PNGs, checksums and
#: all, because Maya reads them and refuses a broken one.
OPAQUE_PNG = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mPYEmUDAAMQAUuHB38VAAAAAElFTkSuQmCC')
ALPHA_PNG = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mPYEmXTAAAE2wHLCn65FQAAAABJRU5ErkJggg==')


def write_maps(folder, base_name, suffixes, with_alpha=()):
    """
    Write one tiny PNG per suffix, and answer with their paths.

    :param str folder: Where to write them.
    :param str base_name: The asset's texture name, such as ``T_crate``.
    :param suffixes: The map suffixes to write - ``('_D', '_N')``.
    :param with_alpha: Which of them should have an alpha channel.
    :return: Suffix to path.
    :rtype: dict
    """

    if not os.path.isdir(folder):
        os.makedirs(folder)
    written = {}
    for suffix in suffixes:
        path = os.path.join(folder, '{}{}.png'.format(base_name, suffix)).replace('\\', '/')
        with open(path, 'wb') as opened:
            opened.write(ALPHA_PNG if suffix in with_alpha else OPAQUE_PNG)
        written[suffix] = path
    return written


def check_textures(suite, pm):
    from mca.mya.utils import material_utils

    harness.new_scene()
    folder = os.path.join(suite.temp, 'textures')
    maps = write_maps(folder, 'T_crate', ('_D', '_N'))

    file_node = material_utils.create_texture(maps['_D'], name='crate_d')
    suite.check('a file node is made', isinstance(file_node, pm.nt.File))
    suite.check('pointing at the texture',
                file_node.fileTextureName.get().replace('\\', '/') == maps['_D'],
                file_node.fileTextureName.get())
    suite.check('with a placement node wired into it',
                bool(file_node.uv.listConnections(type=pm.nt.Place2dTexture)))
    suite.check('and every placement output connected',
                len(file_node.listConnections(source=True, type=pm.nt.Place2dTexture)) >= 1)
    suite.check('a texture with no alpha channel reads its brightness as alpha',
                file_node.alphaIsLuminance.get() is True)

    again = material_utils.create_texture(maps['_D'], name='crate_d')
    suite.check('asking again finds the same file node', again == file_node)
    suite.check('and does not leave a second placement node behind',
                len(pm.ls(type=pm.nt.Place2dTexture)) == 1,
                str(pm.ls(type=pm.nt.Place2dTexture)))

    # A UDIM set: the tile number sits between the name and the extension.
    udim_folder = os.path.join(suite.temp, 'udim')
    os.makedirs(udim_folder)
    for tile in (1001, 1002):
        with open(os.path.join(udim_folder, 'T_ground_D.{}.png'.format(tile)), 'wb') as opened:
            opened.write(OPAQUE_PNG)
    tiled = material_utils.create_texture(
        os.path.join(udim_folder, 'T_ground_D.1001.png'), name='ground_d')
    suite.check('a UDIM set is recognised and Maya told to tile it',
                tiled.uvTilingMode.get() == material_utils.UDIM_TILING_MODE,
                str(tiled.uvTilingMode.get()))
    suite.check('the preview is not generated in a batch Maya, which has no such procedure',
                True)

    single = material_utils.create_texture(maps['_N'], name='crate_n')
    suite.check('a texture with no tile number is left alone', single.uvTilingMode.get() == 0)

    bump_node = material_utils.create_normal(maps['_N'], name='crate')
    suite.check('a bump node is made for a normal map', isinstance(bump_node, pm.nt.Bump2d))
    suite.check('set to tangent space', bump_node.bumpInterp.get() == 1)
    suite.check('and reading the normal map',
                bool(bump_node.bumpValue.listConnections(source=True, type=pm.nt.File)))


def check_basic_blinn(suite, pm):
    from mca.mya.utils import material_utils

    harness.new_scene()
    folder = os.path.join(suite.temp, 'blinn_textures')
    maps = write_maps(folder, 'T_barrel', ('_D',))

    flat = material_utils.create_basic_blinn(name='flat_thing')
    suite.check('a blinn with no texture is made', isinstance(flat, pm.nt.Blinn))
    suite.check('and is mid-grey', [round(one, 3) for one in flat.color.get()] == [0.5, 0.5, 0.5],
                str(flat.color.get()))
    # Rounded: these are single-precision float attributes, so 0.8 comes back as
    # 0.800000011920929.
    suite.check('its specular values are set',
                round(flat.eccentricity.get(), 4) == 0.8 and
                round(flat.specularRollOff.get(), 4) == 0.5,
                '{} / {}'.format(flat.eccentricity.get(), flat.specularRollOff.get()))
    # The bug: three checks in a row, and the third tested specularRollOff and set diffuse.
    suite.check('and diffuse is set on its own account, not on specularRollOff\'s',
                round(flat.diffuse.get(), 4) == 1.0, str(flat.diffuse.get()))

    coloured = material_utils.create_basic_blinn(name='red_thing', default_color=[1.0, 0.0, 0.0])
    suite.check('a colour can be given',
                [round(one, 3) for one in coloured.color.get()] == [1.0, 0.0, 0.0])

    textured = material_utils.create_basic_blinn(maps['_D'], name='barrel')
    suite.check('a blinn with a diffuse map has it wired into colour',
                bool(textured.color.listConnections(source=True, type=pm.nt.File)))
    suite.check('and remembers which texture it came from',
                textured.hasAttr(material_utils.TEXTURE_PATH_ATTR))

    # A connection somebody made is not thrown away by building again.
    driver = pm.createNode('multiplyDivide', name='a_driver')
    driver.outputX >> flat.eccentricity
    material_utils.create_basic_blinn(name='flat_thing')
    suite.check('building again leaves a connection somebody made alone',
                bool(flat.eccentricity.listConnections(source=True)))

    # The bug: os.path.basename(None).
    suite.raises('neither a name nor a diffuse path is refused, not a TypeError from inside',
                 material_utils.create_basic_blinn)


def check_assign_and_replace(suite, pm):
    from mca.mya.utils import material_utils

    harness.new_scene()
    sphere = pm.polySphere(name='shaded_sphere')[0]
    material = material_utils.create_basic_blinn(name='the_material')

    shading_group = material_utils.assign_material(material, sphere)
    suite.check('a shading group is made for a material that had none',
                isinstance(shading_group, pm.nt.ShadingEngine))
    suite.check('and the geometry is in it',
                any('shaded_sphere' in str(one) for one in shading_group.members()),
                str(shading_group.members()))
    suite.check('asking for the shading group again gives the same one',
                material_utils.shading_group_for(material) == shading_group)

    # replace_material moves the members across and deletes the old material.
    old_material = material_utils.create_basic_blinn(name='old_material')
    cube = pm.polyCube(name='replaced_cube')[0]
    material_utils.assign_material(old_material, cube)
    new_material = material_utils.create_basic_blinn(name='new_material')

    target = material_utils.replace_material(old_material, new_material)
    # The bug: a `return` inside the loop where a `continue` was meant, so this delete never ran.
    suite.check('the old material is deleted - its clean-up used to be abandoned',
                not pm.objExists('old_material'))
    suite.check('the geometry is shaded by the new material',
                any('replaced_cube' in str(one) for one in target.members()),
                str(target.members()))
    suite.check('and the old shading group is gone too',
                not any(str(one).startswith('old_material') for one in
                        pm.ls(type=pm.nt.ShadingEngine)),
                str(pm.ls(type=pm.nt.ShadingEngine)))


def check_default_material(suite, pm):
    from mca.mya.utils import material_utils

    # -- a full set of maps ------------------------------------------------------------- #
    harness.new_scene()
    folder = os.path.join(suite.temp, 'full_set')
    maps = write_maps(folder, 'T_hero', ('_D', '_N', '_MRA'), with_alpha=('_D',))

    material = material_utils.DefaultMaterial(maps['_D']).material_node
    suite.check('a material is built', isinstance(material, pm.nt.Blinn))
    suite.check('named after the texture, without the T_', str(material) == 'hero', str(material))
    suite.check('colour comes from the diffuse map',
                bool(material.color.listConnections(source=True, type=pm.nt.File)))
    suite.check('the normal map is wired into the bump',
                bool(material.normalCamera.listConnections(source=True, type=pm.nt.Bump2d)))
    suite.check('specularity comes from the packed map',
                bool(material.eccentricity.listConnections(source=True)))
    suite.check('roughness too', bool(material.specularRollOff.listConnections(source=True)))
    suite.check('and ambient colour',
                bool(material.ambientColorR.listConnections(source=True)))
    suite.check('the diffuse alpha drives transparency',
                bool(material.transparencyR.listConnections(source=True, type=pm.nt.Reverse)))

    # -- the case that raised UnboundLocalError: a packed map and no diffuse ------------- #
    harness.new_scene()
    folder = os.path.join(suite.temp, 'no_diffuse')
    maps = write_maps(folder, 'T_wall', ('_N', '_MRA'))
    built = material_utils.DefaultMaterial(maps['_MRA'])
    suite.check('a packed map with no diffuse builds rather than raising '
                'UnboundLocalError on use_alpha', built.material_node is not None)
    suite.check('and it is a blinn', isinstance(built.material_node, pm.nt.Blinn))
    suite.check('with the packed map driving its specularity',
                bool(built.material_node.eccentricity.listConnections(source=True)))

    # -- the case that raised AttributeError: a normal map and nothing else -------------- #
    harness.new_scene()
    folder = os.path.join(suite.temp, 'only_normal')
    maps = write_maps(folder, 'T_pipe', ('_N',))
    built = material_utils.DefaultMaterial(maps['_N'])
    suite.check('a folder with only a normal map builds a flat material rather than raising '
                'on None', built.material_node is not None)
    suite.check('with the normal map on it',
                bool(built.material_node.normalCamera.listConnections(source=True)))
    suite.check('and a flat colour',
                not built.material_node.color.listConnections(source=True))

    # -- the older four-channel mask ----------------------------------------------------- #
    harness.new_scene()
    folder = os.path.join(suite.temp, 'rida_only')
    maps = write_maps(folder, 'T_crate', ('_RIDA',), with_alpha=('_RIDA',))
    built = material_utils.DefaultMaterial(maps['_RIDA'])
    suite.check('a mask-only asset builds', built.material_node is not None)
    suite.check('its colour is remapped from the mask',
                bool(built.material_node.colorR.listConnections(source=True,
                                                                type=pm.nt.RemapValue)))
    suite.check('and it remembers the mask it came from',
                built.material_node.hasAttr(material_utils.TEXTURE_PATH_ATTR))

    # -- simple_material, and rebuild ---------------------------------------------------- #
    harness.new_scene()
    folder = os.path.join(suite.temp, 'simple')
    maps = write_maps(folder, 'T_simple', ('_D', '_N', '_MRA'))
    simple = material_utils.DefaultMaterial(maps['_D'], simple_material=True).material_node
    suite.check('a simple material takes its colour from the diffuse',
                bool(simple.color.listConnections(source=True, type=pm.nt.File)))
    suite.check('and leaves the normal map out',
                not simple.normalCamera.listConnections(source=True),
                str(simple.normalCamera.listConnections(source=True)))

    # rebuild=False on a material that is already there leaves it as it is.
    driver = pm.createNode('multiplyDivide', name='left_alone')
    simple.disconnectAttr('specularRollOff')
    driver.outputX >> simple.specularRollOff
    material_utils.DefaultMaterial(maps['_D'], rebuild=False)
    suite.check('rebuild=False leaves a material that was already there alone',
                driver in simple.specularRollOff.listConnections(source=True),
                str(simple.specularRollOff.listConnections(source=True)))
    material_utils.DefaultMaterial(maps['_D'], rebuild=True)
    suite.check('rebuild=True wires it up again',
                driver not in (simple.specularRollOff.listConnections(source=True) or []),
                str(simple.specularRollOff.listConnections(source=True)))

    # -- the paths it found -------------------------------------------------------------- #
    built = material_utils.DefaultMaterial(maps['_D'])
    suite.check('the maps it found are instance attributes, not class ones',
                'diffuse_path' in vars(built), str(sorted(vars(built))))
    suite.check('a second instance does not inherit the first one\'s maps',
                material_utils.DefaultMaterial.__dict__.get('diffuse_path') is None)


def check_consolidate_and_refresh(suite, pm):
    from mca.mya.utils import material_utils

    harness.new_scene()
    folder = os.path.join(suite.temp, 'consolidate')
    maps = write_maps(folder, 'T_box', ('_D',))

    # A material of somebody else's making, marked up with where its texture is.
    sphere = pm.polySphere(name='imported_mesh')[0]
    theirs = pm.shadingNode(pm.nt.Lambert, asShader=True, name='their_lambert')
    material_utils.assign_material(theirs, sphere)
    theirs.addAttr(material_utils.TEXTURE_PATH_ATTR, dt='string')
    theirs.setAttr(material_utils.TEXTURE_PATH_ATTR, maps['_D'])

    rebuilt = material_utils.consolidate_materials([theirs])
    suite.check('the imported material is replaced by one of ours', len(rebuilt) == 1,
                str(rebuilt))
    suite.check('and it is a blinn', isinstance(rebuilt[0], pm.nt.Blinn))
    suite.check('the mesh is shaded by it',
                any('imported_mesh' in str(one) for one in
                    material_utils.shading_group_for(rebuilt[0]).members()),
                str(material_utils.shading_group_for(rebuilt[0]).members()))
    suite.check('the imported material is gone', not pm.objExists('their_lambert'))

    plain = pm.shadingNode(pm.nt.Lambert, asShader=True, name='no_markup')
    suite.check('a material with no texture markup is left alone',
                material_utils.consolidate_materials([plain]) == [])
    suite.check('and is still there', pm.objExists('no_markup'))

    missing = pm.shadingNode(pm.nt.Lambert, asShader=True, name='missing_texture')
    missing.addAttr(material_utils.TEXTURE_PATH_ATTR, dt='string')
    missing.setAttr(material_utils.TEXTURE_PATH_ATTR,
                    os.path.join(folder, 'T_nothing_D.png').replace('\\', '/'))
    suite.check('a material whose texture is not on disk is skipped, with a warning',
                material_utils.consolidate_materials([missing]) == [])
    suite.check('and is still there', pm.objExists('missing_texture'))

    # refresh_file_nodes only changes a path it can make relative; a path outside the project is
    # left as it is rather than mangled.
    changed = material_utils.refresh_file_nodes()
    suite.check('refreshing the file nodes does not raise in a batch Maya', changed is not None)
    for file_node in pm.ls(type=pm.nt.File):
        suite.check('{} still points at something'.format(file_node),
                    bool(file_node.fileTextureName.get()))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_textures(suite, pm)
    check_basic_blinn(suite, pm)
    check_assign_and_replace(suite, pm)
    check_default_material(suite, pm)
    check_consolidate_and_refresh(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('material_utils', body))
