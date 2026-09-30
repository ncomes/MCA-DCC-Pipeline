"""
Laying a texture over whatever a mesh is already shaded with, and taking it off again.

This is for review: a wireframe, a UV grid or a set of reference marks put on top of an
existing look without disturbing it, so it can be turned off and leave the shading as it was.
The overlay is a ``layeredTexture`` inserted between the shader's colour and whatever was
driving it, and the nodes it makes are tagged so ``remove_overlay_textures`` can find them
again.

What was wrong before:

- **``remove_overlay_textures`` could not find the overlays it had made**, in any scene where
  the meshes were in a namespace - which is every referenced or imported asset. It searches with
  ``attr_utils.get_all_objects_with_attr``, and that function built its search string by
  dropping the first character of every namespace name, so it looked in namespaces that do not
  exist and found nothing. Fixed in ``attr_utils``; this module is why it matters.
- ``remove_overlay_textures`` indexed the first connection of the layered texture's input
  without checking there was one, so an overlay whose original colour node had since been
  deleted raised ``IndexError`` part way through, leaving the rest of the scene's overlays in
  place.
- **Taking an overlay off a shader with a plain colour lost the colour.** The overlay needs a
  node to layer over, so a flat colour is turned into a checker with both of its colours the
  same; when the overlay came off, that stand-in was deleted - and Maya leaves an attribute at
  its *default* when the node driving it is deleted, not at the value it held before it was
  connected. So a shader that had been 0.2, 0.4, 0.6 came back mid-grey. The colour is written
  back by hand now.
- The module docstring said "utilities for getting the time ranges of a scene and its
  animation", which is another module's job, and ``add_overlay_textures`` documented an ``obj``
  parameter it does not have.
- Tabs for indentation.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.utils import attr_utils


logger = log.MCA_LOGGER

#: Marks the checker node that stands in for a plain colour, so it can be deleted with the
#: overlay rather than left behind.
BASE_TAG = 'isOverlayBase'

#: Marks the layeredTexture that holds an overlay. This is what finds them again.
OVERLAY_TAG = 'isOverlayLayeredTexture'

#: Which input of the layered texture holds what. Input 0 is removed: Maya makes one by
#: default and an empty input renders black over everything.
ORIGINAL_INPUT = 1
OVERLAY_INPUT = 2

#: How much of the original shows through under the overlay.
ORIGINAL_ALPHA = 0.75


def add_overlay_textures(obj_list, overlay_texture_path):
    """
    Put a texture on top of whatever these meshes are already shaded with.

    :param obj_list: The meshes, as PyNodes or names.
    :type obj_list: list or pm.nt.Transform or str
    :param str overlay_texture_path: The image to lay over them.
    :return: The layered textures that were made.
    :rtype: list(pm.nt.LayeredTexture)
    """

    made = []
    for obj in lists.force_list(obj_list):
        obj = pm.PyNode(obj) if isinstance(obj, str) else obj
        shape = obj.getShape()
        if not shape:
            logger.warning('%s has no shape to shade.', obj)
            continue

        shading_engines = [one for one in shape.listConnections(source=True, destination=True)
                           if isinstance(one, pm.nt.ShadingEngine)]
        if not shading_engines:
            logger.warning('%s is not shaded by anything.', obj)
            continue

        for shading_engine in shading_engines:
            for shader in shading_engine.surfaceShader.listConnections(source=True,
                                                                      destination=False):
                colour_node = _colour_source(shader)
                if colour_node is None:
                    continue
                if colour_node.hasAttr(OVERLAY_TAG):
                    # Already overlaid. Laying a second one on would bury the first.
                    continue
                made.append(_insert_overlay(shader, colour_node, overlay_texture_path))
    return made


def _colour_source(shader):
    """
    Whatever is driving a shader's colour, made into a node if it is only a value.

    The overlay is a layered texture, and a layered texture takes connections, not values - so
    a shader with a plain colour set on it needs that colour turned into a node first. A checker
    with both of its colours the same looks exactly like the flat colour it replaces.

    :param shader: The shader to read.
    :return: The node driving its colour, or None when the shader has no colour at all.
    :rtype: pm.PyNode or None
    """

    if not shader.hasAttr('color'):
        logger.warning('%s has no colour attribute.', shader)
        return None

    existing = shader.color.listConnections(source=True, destination=False)
    if existing:
        return existing[0]

    colour = shader.color.get()
    stand_in = pm.createNode('checker')
    stand_in.addAttr(BASE_TAG, at='bool')
    stand_in.color1.set(colour)
    stand_in.color2.set(colour)
    stand_in.outColor >> shader.color
    return stand_in


def _insert_overlay(shader, colour_node, overlay_texture_path):
    """
    Put a layered texture between a shader's colour and what was driving it.

    :param shader: The shader.
    :param colour_node: What is driving its colour now.
    :param str overlay_texture_path: The image to lay on top.
    :return: The layered texture.
    :rtype: pm.nt.LayeredTexture
    """

    layered_texture = pm.createNode('layeredTexture')
    layered_texture.addAttr(OVERLAY_TAG, at='bool')

    texture_node = pm.createNode('file')
    texture_node.fileTextureName.set(overlay_texture_path)

    colour_node.outColor >> layered_texture.attr('inputs')[ORIGINAL_INPUT].color
    texture_node.outColor >> layered_texture.attr('inputs')[OVERLAY_INPUT].color
    # Maya makes input 0 with the node, and an input with nothing connected renders black over
    # everything below it.
    pm.removeMultiInstance(layered_texture.attr('inputs')[0])
    layered_texture.attr('inputs')[ORIGINAL_INPUT].alpha.set(ORIGINAL_ALPHA)
    layered_texture.outColor >> shader.color
    return layered_texture


def remove_overlay_textures():
    """
    Take every overlay in the scene off again, putting the original shading back.

    :return: How many overlays were removed.
    :rtype: int
    """

    removed = 0
    for layered_texture in attr_utils.get_all_objects_with_attr(OVERLAY_TAG):
        shader_attrs = layered_texture.outColor.listConnections(source=False, destination=True,
                                                                plugs=True)
        original = layered_texture.attr('inputs')[ORIGINAL_INPUT].color.listConnections(
            source=True, destination=False, plugs=True)
        overlay_texture = layered_texture.attr('inputs')[OVERLAY_INPUT].color.listConnections(
            source=True, destination=False)

        if not original:
            # The node that was driving the colour has been deleted since. There is nothing to
            # put back, but the overlay still has to come off - the version this replaces
            # indexed this list without checking and raised IndexError here, leaving every
            # overlay after it in place.
            logger.warning('%s has nothing behind it to put back.', layered_texture)
        else:
            original_attr = original[0]
            for shader_attr in shader_attrs:
                original_attr >> shader_attr

            if original_attr.node().hasAttr(BASE_TAG):
                # It was a stand-in for a flat colour, not something the artist made, so it goes
                # with the overlay. The colour has to be written back by hand: Maya leaves an
                # attribute at its *default* when the node driving it is deleted, not at the
                # value it held before it was connected - so a shader whose colour was 0.2, 0.4,
                # 0.6 came back mid-grey. The version this replaces deleted the stand-in the
                # same way and lost the colour with it.
                flat_colour = original_attr.node().color1.get()
                pm.delete(original_attr.node())
                for shader_attr in shader_attrs:
                    if pm.objExists(shader_attr):
                        shader_attr.set(flat_colour)

        pm.delete([one for one in overlay_texture + [layered_texture] if pm.objExists(one)])
        removed += 1
    return removed
