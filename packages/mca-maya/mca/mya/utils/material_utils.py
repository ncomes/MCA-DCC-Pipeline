"""
Building the shaders the pipeline puts on an asset, from the texture maps beside it.

The studio's textures are named by what they hold - ``T_thing_D`` for diffuse, ``_N`` for
normal, ``_MRA`` for metal/rough/ambient packed into one image's three channels, ``_ORME`` for
the same three in another order, ``_RIDA`` for the four-channel mask the older assets use. Given
any one of them, :class:`DefaultMaterial` finds its siblings in the same folder and wires up a
blinn that looks close enough to what the engine will show.

It is deliberately a blinn and not a Stingray or an Arnold shader: it has to draw in Maya's own
viewport, on every artist's machine, with no plugin loaded.

What was wrong before:

- **A material with an MRA map but no diffuse crashed the build twice.** ``build`` reads
  ``use_alpha`` in the MRA branch, and that name is only ever assigned inside the diffuse and
  RIDA branches - ``UnboundLocalError``. The line after it calls
  ``create_texture(self.diffuse_path)`` with ``self.diffuse_path`` still ``None``, which is
  ``TypeError`` in ``os.path.basename``.
- **A texture folder holding only a normal map crashed as well.** Neither the diffuse nor the
  RIDA branch runs, so ``self.material_node`` is still ``None`` when the normal branch calls
  ``self.material_node.disconnectAttr('normalCamera')``.
- **``create_basic_blinn`` tested the wrong attribute.** Three checks in a row, and the third
  reads ``if not material_node.specularRollOff.connections(): material_node.diffuse.set(1.0)``
  - a copy of the second check's condition with the third's action, so ``diffuse`` was set
  according to whether ``specularRollOff`` was connected.
- **``create_basic_blinn`` with neither a name nor a diffuse path was a TypeError**:
  ``os.path.basename(None)``.
- **The deferred UV tile preview was not deferred.** ``pm.evalDeferred(pm.mel.generateUvTilePreview(name))``
  calls the MEL procedure *now* and hands its result to ``evalDeferred``, which is the opposite
  of what the comment beside it says it is for - and the comment is right, the preview does fail
  if it runs before the tiling mode has settled. It is also a procedure a batch Maya does not
  have, so it raised there.
- **``replace_material`` abandoned its own clean-up.** A ``return`` inside the loop over shading
  groups, where a ``continue`` was meant, so the ``pm.delete`` at the end never ran and the old
  material and its shading groups were left in the scene.
- **``get_object_material_face_dict``'s error path was itself an error**:
  ``logger.warning(log_string='...')`` - ``warning`` has no ``log_string`` parameter, so a
  shading engine with no surface material raised ``TypeError`` from inside the handler meant to
  report it. That function and ``assign_material`` had one caller between them,
  ``node_util.rbf_retarget``, which has no callers of its own. ``get_object_material_face_dict``
  is gone, and with it this module's imports of ``OpenMaya`` and ``om_utils``.
  ``assign_material`` is kept - it is the one way to say "put this material on this geometry",
  and ``replace_material`` carried a copy of half of it, which is now one function both use.
- ``consolidate_materials`` declared a ``things_to_delete`` list and never used it, and a remap
  node's ``outputMax`` was set twice in a row to two different values.
- ``DefaultMaterial.__init__`` reached for the hardware rendering globals node without checking
  there was one.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.paths import path_utils
from mca.common.utils import lists
from mca.mya.utils import naming
from mca.mya.utils import node_util


logger = log.MCA_LOGGER

#: The attribute a built material carries, holding the texture it was built from, so
#: ``consolidate_materials`` can find and rebuild it later.
TEXTURE_PATH_ATTR = 'texture_path'

#: The first tile number in a MARI-style UDIM set.
FIRST_UDIM_TILE = 1001

#: Maya's uvTilingMode for UDIM tiles.
UDIM_TILING_MODE = 3

#: The suffix on each map, and the attribute of :class:`DefaultMaterial` it is kept in.
MAP_SUFFIXES = (
    ('_D', 'diffuse_path'),
    ('_RIDA', 'rida_path'),
    ('_N', 'normal_path'),
    ('_MRA', 'mra_path'),
    ('_ORME', 'orme_path'),
)

#: The place2dTexture outputs that have to reach a file node for it to place its texture.
_PLACEMENT_CONNECTIONS = (
    'coverage', 'translateFrame', 'rotateFrame', 'mirrorU', 'mirrorV', 'stagger', 'wrapU',
    'wrapV', 'repeatUV', 'offset', 'rotateUV', 'noiseUV', 'vertexUvOne', 'vertexUvTwo',
    'vertexUvThree', 'vertexCameraOne',
)


def _generate_uv_tile_preview(file_node):
    """
    Ask Maya to draw the thumbnails for a UDIM set, once it is ready to.

    Deferred, because the preview fails if it runs before the tiling mode has settled - which is
    what the version this replaces meant to do and did not: it wrote
    ``pm.evalDeferred(pm.mel.generateUvTilePreview(name))``, which calls the procedure straight
    away and defers its *result*.

    :param file_node: The file node holding the tiles.
    """

    if cmds.about(batch=True):
        # generateUvTilePreview is one of Maya's interface scripts; a batch Maya has not loaded
        # it, and there is no viewport for it to draw into.
        return
    name = str(file_node)
    pm.evalDeferred(lambda: pm.mel.generateUvTilePreview(name))


def create_texture(file_path, name=None):
    """
    A file node with this texture in it, and a place2dTexture wired into it.

    Finds the pair if they are already in the scene, so a material built twice does not leave
    two copies of every texture behind.

    :param str file_path: The image.
    :param str name: What to call the pair. Taken from the file name otherwise.
    :return: The file node.
    :rtype: pm.nt.File
    """

    parts = os.path.basename(file_path).split('.')
    name = naming.make_maya_safe_name(name or parts[0])

    file_node = lists.get_first_in_list(
        pm.ls('{}_file'.format(name), recursive=True, type=pm.nt.File)) if name else None
    placement = lists.get_first_in_list(
        pm.ls('{}_place2dTexture'.format(name), recursive=True,
              type=pm.nt.Place2dTexture)) if name else None

    if not file_node:
        file_node = pm.shadingNode(pm.nt.File, asTexture=True,
                                   **({'name': '{}_file'.format(name)} if name else {}))
    if not placement:
        placement = pm.shadingNode(pm.nt.Place2dTexture, asUtility=True,
                                   **({'name': '{}_place2dTexture'.format(name)} if name else {}))
        for attribute_name in _PLACEMENT_CONNECTIONS:
            placement.attr(attribute_name) >> file_node.attr(attribute_name)
        placement.outUV >> file_node.uv
        placement.outUvFilterSize >> file_node.uvFilterSize

    file_node.fileTextureName.set(file_path)

    # A name like thing_D.1001.png is one tile of a UDIM set. Maya has to be told, or it shows
    # the one tile stretched over the whole surface.
    if len(parts) > 2:
        tile_number = None
        try:
            tile_number = int(parts[-2])
        except ValueError:
            tile_number = None
        if tile_number:
            next_tile = file_path.replace(str(tile_number), str(tile_number + 1))
            if tile_number > FIRST_UDIM_TILE or os.path.exists(next_tile):
                file_node.setAttr('uvTilingMode', UDIM_TILING_MODE)
                file_node.setAttr('uvTileProxyQuality', 1)
                _generate_uv_tile_preview(file_node)

    if not file_node.fileHasAlpha.get():
        # With no alpha channel, the brightness of the image is the alpha - which is what the
        # masks in this pipeline rely on.
        file_node.setAttr('alphaIsLuminance', True)
    return file_node


def create_normal(normal_path, name=None):
    """
    A bump2d node set up to read a normal map.

    :param str normal_path: The normal map.
    :param str name: What to call the nodes. Taken from the file name otherwise.
    :return: The bump2d node.
    :rtype: pm.nt.Bump2d
    """

    name = naming.make_maya_safe_name(
        name or os.path.basename(normal_path).split('.')[0])
    file_node = create_texture(normal_path, name=name)

    bump_node = node_util.create_or_find('{}_bump2d'.format(name), pm.nt.Bump2d)
    # 1 is "Tangent Space Normals", which is what the engine expects.
    bump_node.setAttr('bumpInterp', 1)
    bump_node.disconnectAttr('bumpValue')
    file_node.outAlpha >> bump_node.bumpValue
    return bump_node


def create_basic_blinn(diffuse_path=None, default_color=None, name=None):
    """
    A blinn, with a diffuse texture on it if there is one.

    :param str diffuse_path: The diffuse map, or None for a flat colour.
    :param default_color: The flat colour, when there is no diffuse map.
    :type default_color: list(float) or None
    :param str name: What to call it. Taken from the diffuse path otherwise.
    :return: The material.
    :rtype: pm.nt.Blinn
    :raises ValueError: When given neither a name nor a diffuse path - the version this replaces
        called ``os.path.basename(None)`` and raised TypeError from inside itself.
    """

    if not name and not diffuse_path:
        raise ValueError('create_basic_blinn needs a name or a diffuse path.')

    default_color = default_color or [0.5, 0.5, 0.5]
    base_name = name or naming.make_maya_safe_name(
        os.path.basename(diffuse_path).rpartition('_')[0] or 'basicBlinn')

    material_node = None
    if base_name != 'basicBlinn':
        material_node = lists.get_first_in_list(
            pm.ls(base_name, recursive=True, type=pm.nt.Blinn))
    if not material_node:
        material_node = pm.shadingNode(pm.nt.Blinn, asShader=True, name=base_name)

    # Each of these is left alone if something is already driving it, so rebuilding a material
    # does not throw away a connection somebody made on purpose. The version this replaces
    # tested specularRollOff twice and set diffuse on the second answer.
    if not material_node.eccentricity.connections(source=True):
        material_node.eccentricity.set(0.8)
    if not material_node.specularRollOff.connections(source=True):
        material_node.specularRollOff.set(0.5)
    if not material_node.diffuse.connections(source=True):
        material_node.diffuse.set(1.0)

    if not material_node.color.connections(source=True) and \
            not material_node.colorR.connections(source=True):
        material_node.color.set(default_color)

    if diffuse_path:
        file_node = create_texture(diffuse_path)
        material_node.disconnectAttr('color')
        file_node.outColor >> material_node.color
        _remember_texture_path(material_node, diffuse_path)
    return material_node


def _remember_texture_path(material_node, texture_path):
    """
    Write the texture a material was built from onto the material.

    This is what lets ``consolidate_materials`` find a material later and rebuild it from the
    same maps.

    :param material_node: The material.
    :param str texture_path: The map it was built from.
    """

    if not material_node.hasAttr(TEXTURE_PATH_ATTR):
        material_node.addAttr(TEXTURE_PATH_ATTR, dt='string')
    material_node.setAttr(TEXTURE_PATH_ATTR, path_utils.to_relative_path(texture_path))


def shading_group_for(material_node):
    """
    The shading group a material draws through, made if it has none.

    A material on its own shades nothing: the shading group is what geometry is a member of.

    :param material_node: The material.
    :return: Its shading group.
    :rtype: pm.nt.ShadingEngine
    """

    shading_group = lists.get_first_in_list(
        material_node.listConnections(type=pm.nt.ShadingEngine))
    if shading_group:
        return shading_group

    shading_group = pm.sets(renderable=True, noSurfaceShader=True, empty=True,
                            name='{}SG'.format(material_node.name()))
    material_node.outColor.connect(shading_group.surfaceShader, force=True)
    return shading_group


def assign_material(material_node, node_list):
    """
    Put a material on some geometry.

    :param material_node: The material.
    :param node_list: What to shade - transforms, or faces.
    :return: The shading group the geometry ended up in.
    :rtype: pm.nt.ShadingEngine
    """

    shading_group = shading_group_for(material_node)
    pm.sets(shading_group, edit=True, forceElement=node_list)
    return shading_group


def replace_material(source_material, replacement_material):
    """
    Move everything one material shades onto another, and delete the first.

    :param source_material: The material to get rid of.
    :param replacement_material: The material to use instead.
    :return: The shading group everything ended up in.
    :rtype: pm.nt.ShadingEngine
    """

    to_delete = [source_material]
    target_group = shading_group_for(replacement_material)

    for old_group in source_material.listConnections(type=pm.nt.ShadingEngine):
        # Renamed out of the way first, so the new group's name does not clash with it while
        # both are in the scene.
        old_group.rename('tempSG')
        for member in old_group.members():
            old_group.removeMember(member)
            target_group.addMember(member)
        to_delete.append(old_group)

    # The version this replaces had a `return` here rather than a `continue`, inside the loop, so
    # this delete never ran and the old material and its shading groups stayed in the scene.
    pm.delete([one for one in to_delete if pm.objExists(one)])
    return target_group


def consolidate_materials(material_node_list, rebuild=True, simple_material=False):
    """
    Rebuild a set of materials the pipeline's way, in place.

    Each material has to carry the texture it was built from, on its ``texture_path``
    attribute - which is how an imported asset's shaders are turned into ones that look right in
    Maya's viewport.

    :param material_node_list: The materials to reprocess.
    :type material_node_list: list(pm.PyNode)
    :param bool rebuild: Rebuild a material even when one of that name is already there.
    :param bool simple_material: Diffuse and alpha only, which is faster and steadier.
    :return: The materials that were rebuilt.
    :rtype: list(pm.nt.Blinn)
    """

    rebuilt = []
    for material_node in material_node_list:
        if not material_node.hasAttr(TEXTURE_PATH_ATTR):
            continue

        file_path = path_utils.to_full_path(material_node.getAttr(TEXTURE_PATH_ATTR))
        if isinstance(material_node, pm.nt.Blinn):
            # Already one of ours. Rebuilding it in place is enough; there is nothing to
            # replace.
            rebuilt.append(DefaultMaterial(file_path, simple_material=simple_material,
                                           rebuild=rebuild).material_node)
            continue

        if not os.path.exists(file_path):
            logger.warning('%s says its texture is %s, which is not there.',
                           material_node, file_path)
            continue

        # Out of the way, so the new material can take its name.
        material_node.rename('temp')
        ours = DefaultMaterial(file_path, simple_material=simple_material, rebuild=rebuild)
        if ours.material_node is None:
            logger.warning('Could not build a material from %s.', file_path)
            continue
        replace_material(material_node, ours.material_node)
        rebuilt.append(ours.material_node)
    return rebuilt


def refresh_file_nodes():
    """
    Point every file node in the scene at its texture by a path relative to the project.

    An absolute path from one machine is not a path on another, and a scene saved with them opens
    with pink shaders for everybody else.

    :return: The file nodes that were changed.
    :rtype: list(pm.nt.File)
    """

    changed = []
    for file_node in pm.ls(type=pm.nt.File):
        existing = file_node.getAttr('fileTextureName')
        if not existing:
            continue
        relative = path_utils.to_relative_path(existing)
        if relative == existing:
            continue
        file_node.fileTextureName.set(relative)
        _generate_uv_tile_preview(file_node)
        changed.append(file_node)
    return changed


class DefaultMaterial(object):
    """
    A blinn built from whichever of an asset's texture maps are on disk beside each other.

    Given the path to any one map, the rest are found in the same folder by their suffix, and the
    ones that are there are wired up: diffuse into colour, its alpha into transparency, normal
    into the bump, and the packed metal/rough/ambient map into specularity and ambient colour.
    A folder with nothing but a flat colour gets a flat grey.

    The whole thing is a viewport approximation. It is built to look close to what the engine
    shows, in Maya's own renderer, with no plugin loaded - which is why it is a blinn and why the
    specular values are clamped well down.
    """

    def __init__(self, file_path, simple_material=False, rebuild=False):
        """
        :param str file_path: Any one of the asset's maps.
        :param bool simple_material: Diffuse and alpha only. Faster, and steadier on a heavy
            scene.
        :param bool rebuild: Rebuild even when a material of this name is already in the scene.
        """

        #: Instance attributes, not class ones. The version this replaces declared all of these
        #: on the class, which means a map that is not found reads whatever the class attribute
        #: holds rather than clearly nothing.
        self.diffuse_path = None
        self.rida_path = None
        self.normal_path = None
        self.mra_path = None
        self.orme_path = None
        self.base_name = ''
        self.material_node = None

        #: Whether the diffuse or mask map has an alpha channel worth using. Set while the
        #: material is built, and read again further down - the version this replaces only ever
        #: assigned it inside two of the three branches, so the third read it unassigned and
        #: raised UnboundLocalError.
        self.use_alpha = False

        self.initialize_textures(file_path)
        self.material_node = self.build(simple_material=simple_material, rebuild=rebuild)
        self._set_viewport_transparency()

    @staticmethod
    def _set_viewport_transparency():
        """
        Ask Maya's viewport to sort transparency properly, so an alpha-cut texture reads right.

        There is no such node in a batch Maya; the version this replaces reached for the first
        one in the scene and called an attribute on it without checking there was one.
        """

        globals_node = lists.get_first_in_list(pm.ls(type=pm.nt.HardwareRenderingGlobals))
        if globals_node is None:
            return
        # 3 is "Depth Peeling", the only setting that draws overlapping cut-outs in the right
        # order.
        globals_node.transparencyAlgorithm.set(3)

    def initialize_textures(self, file_path=None):
        """
        Find the asset's other maps in the same folder, by their suffix.

        :param str file_path: Any one of the maps.
        """

        if not file_path:
            return

        base_dir = os.path.dirname(file_path)
        parts = os.path.basename(file_path).split('.')
        # A UDIM set has its tile number in the middle of the name; only files carrying the same
        # one belong to this material.
        identifier = parts[-2] if len(parts) > 2 else None
        self.base_name = os.path.basename(file_path).rpartition('_')[0]

        if not os.path.isdir(base_dir):
            logger.warning('%s is not a folder, so no maps could be looked for.', base_dir)
        else:
            for file_name in sorted(os.listdir(base_dir)):
                if identifier and identifier not in file_name:
                    continue
                for suffix, attribute_name in MAP_SUFFIXES:
                    if file_name.startswith('{}{}'.format(self.base_name, suffix)):
                        setattr(self, attribute_name, os.path.join(base_dir, file_name))

        # The studio's textures are named T_something; the material is named after the something.
        name = self.base_name[2:] if self.base_name.startswith('T_') else self.base_name
        self.base_name = naming.make_maya_safe_name(name) or 'defaultMaterial'

    def build(self, simple_material=False, rebuild=True):
        """
        Wire the maps that were found onto a blinn.

        :param bool simple_material: Diffuse and alpha only.
        :param bool rebuild: Wire the maps up again even when a material of this name was
            already in the scene. False leaves an existing material as it is, once it has been
            found - which is what an import that only wants the missing materials made asks for.
        :return: The material, or None when there was nothing to build one from.
        :rtype: pm.nt.Blinn or None
        """

        # Asked before anything is made, because create_basic_blinn finds or creates, and after
        # it has run there is no telling which it did. The version this replaces tested
        # `self.material_node`, which is None at this point on every fresh instance, so its
        # rebuild argument could only ever have an effect in the one branch that left the
        # material unbuilt - and that branch then crashed.
        already_there = bool(pm.ls(self.base_name, recursive=True, type=pm.nt.Blinn))

        if self.diffuse_path:
            self._build_from_diffuse()
        elif self.rida_path:
            self._build_from_rida()
        else:
            # Only a normal or a mask map, with nothing to take a colour from. A flat grey blinn
            # is still better than the pink Maya shows for a missing shader - and the version
            # this replaces left material_node as None here and then called a method on it.
            self.material_node = create_basic_blinn(name=self.base_name)

        if already_there and not rebuild:
            return self.material_node
        if simple_material:
            return self.material_node

        self._build_normal()
        if self.mra_path or self.orme_path:
            self._build_from_packed_map()
        elif self.rida_path:
            self._build_rida_specular()
        else:
            # Nothing to drive specularity with. Break whatever was there rather than leaving a
            # connection from a previous build pointing at a deleted node.
            self.material_node.disconnectAttr('eccentricity')
            self.material_node.disconnectAttr('specularRollOff')
        return self.material_node

    # -- the branches ------------------------------------------------------------------- #
    def _build_from_diffuse(self):
        """Colour from the diffuse map, and transparency from its alpha."""

        diffuse_file = create_texture(self.diffuse_path)
        self.material_node = create_basic_blinn(self.diffuse_path, name=self.base_name)
        self.use_alpha = bool(diffuse_file.getAttr('fileHasAlpha'))
        if not self.use_alpha:
            return

        # Blinn transparency is the opposite way round from an alpha channel: 0 is opaque.
        reverse_node = node_util.create_or_find('{}_reverse'.format(self.base_name),
                                                pm.nt.Reverse)
        reverse_node.disconnectAttr('inputX')
        diffuse_file.outAlpha >> reverse_node.inputX
        for channel in 'RGB':
            self.material_node.disconnectAttr('transparency{}'.format(channel))
            reverse_node.outputX >> self.material_node.attr('transparency{}'.format(channel))

    def _build_from_rida(self):
        """Colour, transparency and specularity from the older four-channel mask."""

        self.material_node = create_basic_blinn(name=self.base_name)
        _remember_texture_path(self.material_node, self.rida_path)

        file_node = create_texture(self.rida_path)
        colour_remap = node_util.create_or_find('{}_color_remap'.format(self.base_name),
                                                pm.nt.RemapValue)
        # One value. The version this replaces set this twice in a row, to .1 and then to .25.
        colour_remap.setAttr('outputMax', 0.25)
        colour_remap.disconnectAttr('inputValue')
        file_node.outColorG >> colour_remap.inputValue
        for channel in 'RGB':
            self.material_node.disconnectAttr('color{}'.format(channel))
            colour_remap.outValue >> self.material_node.attr('color{}'.format(channel))

        self.use_alpha = bool(file_node.getAttr('fileHasAlpha'))
        if not self.use_alpha:
            return

        reverse_node = node_util.create_or_find('{}_reverse'.format(self.base_name),
                                                pm.nt.Reverse)
        for channel in 'XYZ':
            reverse_node.disconnectAttr('input{}'.format(channel))
            file_node.outAlpha >> reverse_node.attr('input{}'.format(channel))
        self.material_node.disconnectAttr('transparency')
        reverse_node.output >> self.material_node.transparency

        # Not really specularity, but the surface reads as flat plastic without it.
        spec_remap = node_util.create_or_find('{}_spec_remap'.format(self.base_name),
                                              pm.nt.RemapValue)
        spec_remap.setAttr('outputMax', 0.25)
        spec_remap.disconnectAttr('inputValue')
        file_node.outAlpha >> spec_remap.inputValue
        self.material_node.disconnectAttr('eccentricity')
        spec_remap.outValue >> self.material_node.eccentricity

    def _build_normal(self):
        """The normal map, or nothing where there is none."""

        self.material_node.disconnectAttr('normalCamera')
        if not self.normal_path:
            return
        bump_node = create_normal(self.normal_path)
        bump_node.outNormal >> self.material_node.normalCamera

    def _build_from_packed_map(self):
        """
        Specularity and ambient occlusion from the packed metal/rough/ambient map.

        ``_MRA`` and ``_ORME`` hold the same three values in different channels, which is the only
        difference between the two branches here.
        """

        packed_path = self.mra_path or self.orme_path
        packed_file = create_texture(packed_path)
        is_mra = bool(self.mra_path)

        # Metalness, clamped well down: a fully metal blinn is a mirror, and the engine's is not.
        metal_remap = node_util.create_or_find('{}_remap'.format(self.base_name),
                                               pm.nt.RemapValue)
        metal_remap.disconnectAttr('inputValue')
        (packed_file.outColorR if is_mra else packed_file.outColorB) >> metal_remap.inputValue
        metal_remap.setAttr('outputMax', 0.25)

        # The diffuse alpha cuts the specular as well, so a cut-out edge does not shine. With no
        # diffuse map there is no alpha to read - the version this replaces called
        # create_texture(None) here and raised TypeError.
        reverse_node = node_util.create_or_find('{}_reverse'.format(self.base_name),
                                                pm.nt.Reverse)
        reverse_node.disconnectAttr('inputX')
        if self.use_alpha and self.diffuse_path:
            create_texture(self.diffuse_path).outAlpha >> reverse_node.inputX
        else:
            reverse_node.inputX.set(0)

        multiply_node = node_util.create_or_find('{}_multi'.format(self.base_name),
                                                 pm.nt.MultiplyDivide)
        for input_name in ('input1X', 'input1Y', 'input2X'):
            multiply_node.disconnectAttr(input_name)
        reverse_node.outputX >> multiply_node.input1X
        reverse_node.outputX >> multiply_node.input1Y
        metal_remap.outValue >> multiply_node.input2X

        self.material_node.disconnectAttr('eccentricity')
        multiply_node.outputX >> self.material_node.eccentricity

        # Roughness, clamped for the same reason.
        rough_remap = node_util.create_or_find('{}_R_remap'.format(self.base_name),
                                               pm.nt.RemapValue)
        rough_remap.disconnectAttr('inputValue')
        packed_file.outColorG >> rough_remap.inputValue
        rough_remap.setAttr('outputMax', 0.25)

        multiply_node.disconnectAttr('input2Y')
        rough_remap.outValue >> multiply_node.input2Y
        self.material_node.disconnectAttr('specularRollOff')
        multiply_node.outputY >> self.material_node.specularRollOff

        # Ambient occlusion into the ambient colour, which is the nearest thing a blinn has.
        ambient_attr = packed_file.outColorB if is_mra else packed_file.outColorR
        for channel in 'RGB':
            self.material_node.disconnectAttr('ambientColor{}'.format(channel))
            ambient_attr >> self.material_node.attr('ambientColor{}'.format(channel))

    def _build_rida_specular(self):
        """Specular roll-off from the mask map's blue channel."""

        rida_file = create_texture(self.rida_path)
        rida_remap = node_util.create_or_find('{}_remap_ecc'.format(self.base_name),
                                              pm.nt.RemapValue)
        rida_remap.setAttr('outputMax', 0.5)
        rida_remap.disconnectAttr('inputValue')
        rida_file.outColorB >> rida_remap.inputValue
        self.material_node.disconnectAttr('specularRollOff')
        rida_remap.outValue >> self.material_node.specularRollOff
