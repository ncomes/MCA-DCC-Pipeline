"""
Display layers: finding which one a node is on, and taking it off.

What was wrong before:

- **``get_display_layers`` kept only the first layer of each node and could hand back the
  same layer several times.** It appended ``layer[0]`` per object with no de-duplication, so
  a call over a rig's forty flags - which is how ``flag_utils`` and the flag tools use it -
  returned forty entries naming two or three layers. Callers then did the same work over and
  over. It answers with each layer once now.
- **Taking a node off its layers was written with pymel's ``//`` operator.**
  ``layer.drawInfo // obj.drawOverride`` does disconnect the two, but there is no reading of
  that line that suggests so, and it was doing the shape's disconnect through a second
  ``obj.getShape()`` call rather than the shape it had already looked up. Spelled with
  ``disconnectAttr`` here.
- **``remove_objects_from_layers`` said nothing about what it did or did not manage.** A
  locked or referenced node quietly stayed on its layer. It answers with the nodes it took
  off.
- Tabs for indentation, in a package that is otherwise spaces.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists


logger = log.MCA_LOGGER


def get_display_layers(objs):
    """
    The display layers the given nodes are on.

    :param objs: One node or several.
    :type objs: pm.PyNode or list(pm.PyNode)
    :return: The layers, each one once, in the order they were first met.
    :rtype: list(pm.nt.DisplayLayer)
    """

    found = []
    for node in lists.force_list(objs):
        if not node or not pm.objExists(node):
            continue
        for layer in node.listConnections(type=pm.nt.DisplayLayer) or []:
            if layer not in found:
                found.append(layer)
    return found


def remove_objects_from_layers(objs):
    """
    Take nodes off whatever display layers they are on.

    A transform and its shape can be on layers separately, so both are disconnected.

    :param objs: One node or several.
    :type objs: pm.PyNode or list(pm.PyNode)
    :return: The nodes that came off a layer. A node that was on none, or that would not
        disconnect, is not in the list - the version this replaces said nothing either way.
    :rtype: list(pm.PyNode)
    """

    removed = []
    for node in lists.force_list(objs):
        if not node or not pm.objExists(node):
            continue

        # The transform's own drawOverride, and its shape's, which are separate connections.
        attributes = [node.drawOverride]
        shape = node.getShape() if hasattr(node, 'getShape') else None
        if shape:
            attributes.append(shape.drawOverride)

        came_off = False
        for attribute in attributes:
            for layer in attribute.listConnections(type=pm.nt.DisplayLayer) or []:
                try:
                    pm.disconnectAttr(layer.drawInfo, attribute)
                    came_off = True
                except RuntimeError as error:
                    logger.warning('Could not take %s off %s: %s', node, layer, error)
        if came_off:
            removed.append(node)
    return removed


def delete_empty_display_layers():
    """
    Remove every display layer with nothing on it.

    :return: The names of the layers that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for layer in pm.ls(type='displayLayer'):
        # Maya's own defaultLayer is the one with an identification of 0, and it cannot be
        # deleted. Everything a user or a rig makes is numbered from 1 up.
        if layer.identification.get() <= 0:
            continue
        if pm.editDisplayLayerMembers(layer, query=True):
            continue
        name = str(layer)
        try:
            pm.delete(layer)
        except RuntimeError as error:
            logger.warning('Could not delete the display layer %s: %s', name, error)
            continue
        deleted.append(name)
    return deleted
