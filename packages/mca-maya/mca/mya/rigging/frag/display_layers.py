"""
The node that owns a rig's display layers.

Maya's display layers are how a rig keeps its own viewport tidy: the skeleton referenced and hidden,
the geometry referenced so it cannot be picked, the controls on a layer of their own, and the detail
and contact controls hidden until an animator asks for them. One of these nodes holds the layers a
rig built, so they can be found, shown, hidden and cleaned up as a set.

What was wrong before:

- **``remove_objects`` ignored the layer it was given.** It looked the layer up, used it as nothing
  but a gate, and then moved the objects it was handed onto Maya's default layer whatever layer they
  were actually on. So taking a control off the detail layer took it off the skeleton layer too, as
  long as the detail layer happened to exist - and asking for a layer that did not exist did nothing
  at all, whatever the objects were on.
- **``remove`` never deleted the node.** The last thing it does is ``pm.delete(self)`` - the
wrapper,
  not the node - which pymel refuses, inside a bare ``except Exception`` logged at debug level. So
  removing a rig's display layers deleted the layers and left the node behind, silently, every time.
- **``add_objects`` cannot move an object from one layer to another**, and says nothing when it
  declines to. It skips anything whose ``drawOverride`` is already connected, which is true of
  everything already on a layer. That is deliberate - a control should not be pulled off the layer
  it belongs to by a later component - but it is worth knowing, so it is written down and the
  objects that were skipped are reported.
- ``_get_layer_absolute_name_from_layer`` answered a layer's name *without* its namespace, which is
  the opposite of an absolute name; it is ``naming.get_basename``, which is what the rest of the
  package uses for the same question. The layer state numbers - 0, 1 and 2 for normal, template and
  reference - were in the arithmetic, and ``get_layer`` looked its layer up twice.

One thing to know about the ``layers`` attribute: it is a multi *string* attribute that the layers'
message plugs are connected into, which Maya allows. It works, but ``merge_values`` cannot tell a
duplicate from a new entry on it - the values it compares are strings and the things being added are
nodes - so a layer added twice is connected twice. Nothing does that, because a layer is only ever
added when the rig does not already have one by that name.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import namespace
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The attribute the layers are connected to.
LAYERS_ATTR = 'layers'

#: The layers a rig builds. ``FRAGRig.create_display_layers`` is what puts them there.
SKEL_LYR = 'skel_lyr'
SKIN_LYR = 'skins_lyr'
FLAGS_LYR = 'flags_lyr'
FLAGS_CONTACT_LYR = 'flags_contact_lyr'
FLAGS_DETAIL_LYR = 'flags_detail_lyr'

#: Maya's display types for a layer: drawn and selectable, drawn and unselectable, or drawn as a
#: wireframe that cannot be selected.
DISPLAY_TYPE_NORMAL = 0
DISPLAY_TYPE_TEMPLATE = 1
DISPLAY_TYPE_REFERENCE = 2

#: Maya's own layer, which is where an object goes when it is taken off one of the rig's.
DEFAULT_LAYER = 'defaultLayer'


class DisplayLayers(frag_base.FRAGNode):
    """
    The display layers one rig built, as a set.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent):
        """
        Build the node, or hand back the one the rig already has.

        :param FRAGNode frag_parent: The rig this belongs to.
        :return: The node.
        :rtype: DisplayLayers
        """

        existing = frag_parent.get_frag_children(of_type=DisplayLayers)
        if existing:
            return existing[0]

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(frag_parent, DisplayLayers.__name__,
                                        DisplayLayers.VERSION)
        # A multi string attribute with message plugs connected into it; see the module docstring.
        node.pynode.addAttr(LAYERS_ATTR, dt='string', m=True)
        return node

    # ----------------------------------------------------------------------------------- #
    # the layers
    # ----------------------------------------------------------------------------------- #
    def get_layers(self):
        """
        :return: Every layer this node owns.
        :rtype: list(pm.nt.DisplayLayer)
        """

        return self.pynode.attr(LAYERS_ATTR).listConnections()

    def list_layer_names(self):
        """
        :return: The name of each layer this node owns, without its namespace.
        :rtype: list(str)
        """

        return [naming.get_basename(layer) for layer in self.get_layers()]

    def has_layer(self, layer_name):
        """
        :param str layer_name: A layer's name, without its namespace.
        :return: Whether this node owns a layer by that name.
        :rtype: bool
        """

        return self.get_layer(layer_name) is not None

    def get_layer(self, layer_name):
        """
        :param str layer_name: A layer's name, without its namespace.
        :return: The layer, or None when this node does not own one by that name.
        :rtype: pm.nt.DisplayLayer or None
        """

        for layer in self.get_layers():
            if naming.get_basename(layer) == layer_name:
                return layer
        return None

    def remove_layer(self, layer_name):
        """
        Delete one of this node's layers. Whatever was on it goes back to Maya's own layer.

        :param str layer_name: A layer's name, without its namespace.
        """

        layer = self.get_layer(layer_name)
        if layer is not None:
            pm.delete(layer)

    def remove(self):
        """
        Delete this node and every layer it owns.

        A layer, or the node, may already be gone - deleted with a referenced rig, say - so each
        delete is taken on its own and a failure says which one rather than stopping the rest.
        """

        for layer in self.get_layers():
            try:
                pm.delete(layer)
            except Exception as error:
                logger.warning('%s could not be deleted: %s', layer, error)

        # pm.delete(self) - the wrapper rather than the node - is what this used to do, which pymel
        # refuses; inside a bare except that logged at debug, so the node was never deleted at all.
        try:
            pm.delete(self.pynode)
        except Exception as error:
            logger.warning('%s could not be deleted: %s', self.pynode, error)

    # ----------------------------------------------------------------------------------- #
    # what is on them
    # ----------------------------------------------------------------------------------- #
    @ma_decorators.keep_namespace_decorator
    def add_objects(self, obj_list, layer_name):
        """
        Put some objects on one of this node's layers, building the layer if it is not there yet.

        An object that is already on a layer is left where it is: a control belongs to the layer the
        component that built it put it on, and a later component asking for it should not take it.
        To move one, take it off its layer with :meth:`remove_objects` first.

        :param list obj_list: The objects, as nodes or names.
        :param str layer_name: What the layer is called, without a namespace.
        :return: The layer.
        :rtype: pm.nt.DisplayLayer
        """

        root_namespace = self.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        obj_list = [pm.PyNode(node) for node in obj_list]

        layer = self.get_layer(layer_name)
        if layer is None:
            pm.select(clear=True)
            layer = pm.createDisplayLayer(empty=True, name=layer_name)
            self.connect_nodes([layer], LAYERS_ATTR, merge_values=True)

        already_on_a_layer = []
        for obj_node in obj_list:
            if obj_node.drawOverride.listConnections():
                already_on_a_layer.append(obj_node)
                continue
            layer.addMembers(obj_node)

        if already_on_a_layer:
            logger.debug('%s were already on a display layer, so %s was left without them.',
                         already_on_a_layer, layer_name)
        return layer

    def remove_objects(self, obj_list, layer_name):
        """
        Take some objects off one of this node's layers, back onto Maya's own.

        Only the ones actually on that layer: the version before moved everything it was handed off
        whatever layer it happened to be on, as long as the layer it was asked about existed.

        :param list obj_list: The objects, as nodes or names.
        :param str layer_name: What the layer is called, without a namespace.
        """

        layer = self.get_layer(layer_name)
        if layer is None:
            logger.warning('%s owns no layer called %s, so nothing was taken off it.',
                           self.pynode, layer_name)
            return

        members = layer.listMembers()
        to_remove = [pm.PyNode(node) for node in obj_list]
        to_remove = [node for node in to_remove if node in members]
        if not to_remove:
            return
        pm.editDisplayLayerMembers(DEFAULT_LAYER, to_remove, noRecurse=True)

    def get_members(self, layer_name):
        """
        :param str layer_name: What the layer is called, without a namespace.
        :return: What is on that layer, or None when this node owns no such layer - which is a
            different answer from an empty layer.
        :rtype: list or None
        """

        layer = self.get_layer(layer_name)
        if layer is None:
            return None
        return layer.listMembers()

    # ----------------------------------------------------------------------------------- #
    # how they are drawn
    # ----------------------------------------------------------------------------------- #
    def _set_layer_visibility(self, layer_name, visible):
        """
        :param str layer_name: What the layer is called, without a namespace.
        :param bool visible: Whether to show it.
        """

        layer = self.get_layer(layer_name)
        if layer is None:
            logger.warning('%s owns no layer called %s.', self.pynode, layer_name)
            return
        layer.visibility.set(visible)

    def show_layer(self, layer_name):
        """
        :param str layer_name: The layer to show.
        """

        self._set_layer_visibility(layer_name, True)

    def hide_layer(self, layer_name):
        """
        :param str layer_name: The layer to hide.
        """

        self._set_layer_visibility(layer_name, False)

    def _set_layer_display_type(self, layer_name, display_type):
        """
        :param str layer_name: What the layer is called, without a namespace.
        :param int display_type: One of the ``DISPLAY_TYPE_`` values.
        """

        layer = self.get_layer(layer_name)
        if layer is None:
            logger.warning('%s owns no layer called %s.', self.pynode, layer_name)
            return
        layer.displayType.set(display_type)

    def set_layer_to_template(self, layer_name):
        """
        Draw a layer as an unselectable wireframe.

        :param str layer_name: The layer.
        """

        self._set_layer_display_type(layer_name, DISPLAY_TYPE_TEMPLATE)

    def set_layer_to_reference(self, layer_name):
        """
        Draw a layer normally but make it unselectable, which is how a rig's geometry is shown.

        :param str layer_name: The layer.
        """

        self._set_layer_display_type(layer_name, DISPLAY_TYPE_REFERENCE)

    def remove_state_on_layer(self, layer_name):
        """
        Draw a layer normally and make it selectable again.

        :param str layer_name: The layer.
        """

        self._set_layer_display_type(layer_name, DISPLAY_TYPE_NORMAL)
