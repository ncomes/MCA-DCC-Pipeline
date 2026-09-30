"""
Animation layers: taking a layered animation off an object, and putting it back.

Maya does not store layered animation on the object. It stores it as a chain: the attribute is
driven by a blend node, the blend node's ``inputB`` is that layer's curve, its ``inputA`` is the
next blend node down, and so on until the bottom of the stack, whose ``inputA`` is the base
layer's curve. Each blend node is also wired to the ``animLayer`` node it belongs to, which is
what holds the weight, the mute and the membership.

So "copy the animation off this flag" cannot be done by copying a curve. The whole chain has to
be walked, duplicated blend node by blend node, re-pointed at either duplicated layers or the
layers that are already there, and stitched back together in the same order - and then the
reverse on the way back in. That is what this module is: two entry points,
:func:`store_object_animation` and :func:`restore_for_anim_layers`, and the twenty-odd small
pieces that walking the chain needs.

:func:`map_anim_layers` is the piece to read first. Everything else is built on the
``[[blend node, layer], ...]`` list it hands back, in stack order, top first.

What was wrong before:

- **A start frame of zero meant "no start frame".** ``restore_for_anim_layers`` and
  ``adjust_layers_timeline`` both tested ``if start_time:``, so a caller restoring an animation
  to frame 0 - the common case for a cinematic - got it restored wherever it happened to be.
- **A start frame that was not a whole number was ignored.** ``store_object_animation`` tested
  ``isinstance(start_time, int)``, which is False for ``12.0``.
- **``create_anim_layer_network`` answered ``None`` when it had nothing to do**, and its one
  caller does ``attr_curves.update(...)`` with the answer: ``TypeError: 'NoneType' object is not
  iterable``. Same for :func:`map_anim_layers`, whose answer is iterated in four places.
- **Restoring onto an attribute that already had curves could do nothing at all.** In
  ``restore_for_anim_layers``, the branch that merges into existing curves only connected the
  stored network *inside* ``if base_curves:`` - so a stored network whose base layer held no
  curve left the object with its old animation and the whole stored chain orphaned in the scene.
- **``adjust_layers_timeline`` reported the last curve's end frame**, not the latest one, so the
  end frame handed back to the caller depended on the order Maya happened to list the curves in.
- **Four places indexed a list that can be empty**: the first key of a curve with no keys, the
  first plug of an unconnected curve, the last blend node of an empty map, the first connection
  of a blend node's output.
- **``connect_layer_dagSetMembers`` added the same attribute to a layer twice.** It walked
  ``dagSetMembers`` for the first free index without first checking whether the attribute it was
  about to add was already in there, so restoring twice onto the same flag left duplicate
  membership entries behind.
- ``get_objects_in_anim_layer`` had no callers anywhere in the pipeline. Gone.
- Log messages built with ``.format`` rather than left to the logger, and a warning that read
  "There is not Base Layer in the scene."
"""

# python imports

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.animation import anim_curves
from mca.mya.animation import baking
from mca.mya.utils import attr_utils
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: ``dagSetMembers`` is a multi attribute with no natural end, so the search for a free index
#: needs a stop. A single attribute in more layers than this is a broken scene, not a deep stack.
MAX_LAYER_MEMBERS = 1000


# --------------------------------------------------------------------------------------- #
# reading the network
# --------------------------------------------------------------------------------------- #
def check_obj_for_anim_layer(obj):
    """
    Whether any of an object's attributes are driven through an animation layer.

    :param pm.nt.Transform obj: The object to check.
    :return: True when a blend node is driving it.
    :rtype: bool
    """

    return bool(obj.listConnections(type=pm.nt.AnimBlendNodeBase, scn=True))


def map_anim_layers(anim_blend_layer):
    """
    Walk a blend chain from the top down, pairing each blend node with its layer.

    The chain is followed through ``inputA``, which is the next blend node down the stack; a
    blend node whose ``inputA`` holds a curve rather than another blend node is the bottom, and
    that curve is the base layer's animation.

    :param pm.nt.AnimBlendNodeBase anim_blend_layer: The blend node at the top of the chain.
    :return: ``[[blend node, layer], ...]`` in stack order, empty when given anything else.
    :rtype: list(list)
    """

    if not isinstance(anim_blend_layer, pm.nt.AnimBlendNodeBase):
        logger.warning('Mapping must start with the animation blend node, not %s.',
                       type(anim_blend_layer).__name__)
        return []

    mapping = []
    while True:
        anim_layer = lists.get_first_in_list(list(set(
            anim_blend_layer.listConnections(type=pm.nt.AnimLayer))))
        mapping.append([anim_blend_layer, anim_layer])

        if anim_blend_layer.inputA.isCompound():
            input_a = attr_utils.get_compound_attr_connections(anim_blend_layer, 'inputA') or []
        else:
            input_a = anim_blend_layer.inputA.listConnections() or []

        next_blend = [x for x in input_a if isinstance(x, pm.nt.AnimBlendNodeBase)]
        if not next_blend:
            break
        anim_blend_layer = next_blend[0]

    return mapping


def get_all_anim_layers_in_network(anim_blend):
    """
    Every animation layer a blend chain passes through.

    :param pm.nt.AnimBlendNodeBase anim_blend: The blend node at the top of the chain.
    :return: The layers, in stack order.
    :rtype: list(pm.nt.AnimLayer)
    """

    return [layer for _, layer in map_anim_layers(anim_blend)]


def get_all_anim_blends_in_network(anim_blend):
    """
    Every blend node in a blend chain.

    :param pm.nt.AnimBlendNodeBase anim_blend: The blend node at the top of the chain.
    :return: The blend nodes, in stack order, the given one first.
    :rtype: list(pm.nt.AnimBlendNodeBase)
    """

    return [blend for blend, _ in map_anim_layers(anim_blend)]


def get_all_curves_in_layer_network(anim_blend):
    """
    Every animation curve feeding a blend chain, base layer included.

    :param pm.nt.AnimBlendNodeBase anim_blend: The blend node at the top of the chain.
    :return: The curves.
    :rtype: list(pm.nt.AnimCurve)
    """

    curves = []
    for blend, _ in map_anim_layers(anim_blend):
        curves += blend.listConnections(type=pm.nt.AnimCurve) or []
    return curves


def get_base_anim_curves(anim_blend):
    """
    The curves on the base layer, at the bottom of a blend chain.

    :param pm.nt.AnimBlendNodeBase anim_blend: The blend node at the top of the chain.
    :return: The base layer's curves, empty when the chain bottoms out on nothing.
    :rtype: list(pm.nt.AnimCurve)
    """

    blends = get_all_anim_blends_in_network(anim_blend)
    if not blends:
        return []

    bottom = blends[-1]
    if bottom.inputA.isCompound():
        base_curve = attr_utils.get_compound_attr_connections(bottom, 'inputA') or []
    else:
        base_curve = bottom.inputA.listConnections(type=pm.nt.AnimCurve) or []

    if not base_curve:
        logger.warning('No base animation curve was connected to the layer network on %s.',
                       anim_blend)
    return base_curve


# --------------------------------------------------------------------------------------- #
# connection bookkeeping
# --------------------------------------------------------------------------------------- #
def get_node_connections(node):
    """
    A node's connections as plain strings, so they survive the node being duplicated.

    The names are what matters here rather than the plugs: the point of reading them is to
    rewrite one node's name out of them and wire the result up to a duplicate.

    :param pm.nt.DependNode node: The node to read.
    :return: ``{'input': {destination: source}, 'output': {source: destination}}``.
    :rtype: dict
    """

    connections = {'input': {}, 'output': {}}
    for source, destination in (node.listConnections(plugs=True, c=True, s=True, d=False) or []):
        connections['input'][str(destination)] = str(source)
    for source, destination in (node.listConnections(plugs=True, c=True, d=True, s=False) or []):
        connections['output'][str(source)] = str(destination)
    return connections


def _rename_node_in_plug(plug_name, new_name, node_type):
    """
    Swap the node half of ``node.attribute`` for another name, when it is of the given type.

    :param str plug_name: The plug, as ``node.attribute``.
    :param str new_name: The node name to put in its place.
    :param type node_type: Only rewrite when the existing node is one of these.
    :return: The plug name, rewritten or not.
    :rtype: str
    """

    if not cmds.objExists(plug_name):
        return plug_name
    if not isinstance(pm.PyNode(plug_name).node(), node_type):
        return plug_name
    return plug_name.replace(plug_name.split('.')[0], new_name)


def update_connections_dict(blend_connections, new_name, node_type):
    """
    Rewrite one node's name through a connection dictionary, for wiring up a duplicate.

    :param dict blend_connections: The dictionary from :func:`get_node_connections`.
    :param new_name: The name the duplicate goes by.
    :param type node_type: Only plugs on a node of this type are rewritten.
    :return: A new dictionary, the same shape.
    :rtype: dict
    """

    new_name = str(new_name)
    rewritten = {}
    for side in ('input', 'output'):
        rewritten[side] = {
            _rename_node_in_plug(key, new_name, node_type):
                _rename_node_in_plug(value, new_name, node_type)
            for key, value in blend_connections[side].items()}
    return rewritten


def update_anim_blend_in_dict(blend_connections, new_anim_blend):
    """
    :func:`update_connections_dict` for the blend node half.

    :param dict blend_connections: The dictionary from :func:`get_node_connections`.
    :param new_anim_blend: The duplicated blend node.
    :return: A new dictionary, the same shape.
    :rtype: dict
    """

    return update_connections_dict(blend_connections, new_anim_blend, pm.nt.AnimBlendNodeBase)


def update_anim_layer_in_dict(blend_connections, new_anim_layer):
    """
    :func:`update_connections_dict` for the layer half.

    :param dict blend_connections: The dictionary from :func:`get_node_connections`.
    :param new_anim_layer: The layer the duplicate should belong to.
    :return: A new dictionary, the same shape.
    :rtype: dict
    """

    return update_connections_dict(blend_connections, new_anim_layer, pm.nt.AnimLayer)


# --------------------------------------------------------------------------------------- #
# duplicating a network
# --------------------------------------------------------------------------------------- #
def duplicate_anim_layer(anim_layer, new_name=None):
    """
    Duplicate an animation layer, remembering on the copy which layer it came from.

    The ``original_anim_layer`` string attribute is how :func:`check_layer_original` recognises a
    layer that has already been duplicated on an earlier pass, so a network spanning several
    layers does not end up with one copy of each layer per blend node.

    :param pm.nt.AnimLayer anim_layer: The layer to duplicate.
    :param str new_name: A name for the copy. None takes Maya's.
    :return: The duplicate.
    :rtype: pm.nt.AnimLayer
    """

    if not isinstance(anim_layer, pm.nt.AnimLayer):
        raise TypeError('duplicate_anim_layer needs an {0}, got {1}.'
                        .format(pm.nt.AnimLayer.__name__, type(anim_layer).__name__))

    # Both branches of the old if/else were byte-identical.
    dup_anim_layer = (pm.duplicate(anim_layer, n=new_name)[0] if new_name
                      else pm.duplicate(anim_layer)[0])
    dup_anim_layer.addAttr('original_anim_layer', dt='string')
    dup_anim_layer.original_anim_layer.set(str(anim_layer))
    return dup_anim_layer


def check_layer_original(anim_layer, anim_layer_list):
    """
    Find the copy of a layer, if one has already been made.

    :param pm.nt.AnimLayer anim_layer: The layer being looked for.
    :param list anim_layer_list: Layers to look through.
    :return: The copy, or None.
    :rtype: pm.nt.AnimLayer
    """

    for layer in anim_layer_list:
        if layer.hasAttr('original_anim_layer') and layer.original_anim_layer.get() == str(anim_layer):
            return layer
    return None


def duplicate_anim_layer_network(anim_layers_map, anim_layer_list=None):
    """
    Duplicate a whole blend chain, curves and layers included, and stitch the copy together.

    :param list anim_layers_map: ``[[blend node, layer], ...]`` from :func:`map_anim_layers`.
    :param list anim_layer_list: Layers that already exist and should be reused rather than
        duplicated again. None means "look at every layer in the scene".
    :return: ``[new mapping, the layers the copy uses]``.
    :rtype: list
    """

    # The caller may hand us layers that were already duplicated on a previous pass; reuse those
    # rather than duplicating again. This used to be overwritten with pm.ls() on the first loop
    # iteration, which silently threw the caller's list away.
    anim_layer_list = list(anim_layer_list) if anim_layer_list else pm.ls(type=pm.nt.AnimLayer)

    new_mapping = []
    for anim_blend, anim_layer in anim_layers_map:
        # Read the wiring before duplicating, then rewrite the original's name out of it.
        blend_connections = get_node_connections(anim_blend)
        dup_blend = pm.duplicate(anim_blend)[0]
        blend_connections = update_anim_blend_in_dict(blend_connections, dup_blend)

        duped_anim_layer = check_layer_original(anim_layer, anim_layer_list)
        if not duped_anim_layer:
            duped_anim_layer = duplicate_anim_layer(anim_layer)
            anim_layer_list.append(duped_anim_layer)

        blend_connections = update_anim_layer_in_dict(blend_connections, duped_anim_layer)

        # Everything coming in: the layer's own plugs are reconnected as they were, and each
        # curve is duplicated so the copy has animation of its own rather than sharing it.
        for source, destination in blend_connections['input'].items():
            source_node = pm.PyNode(source).node()
            if isinstance(source_node, pm.nt.AnimLayer):
                pm.connectAttr(source, destination, f=True)
            elif isinstance(source_node, pm.nt.AnimCurve):
                curve = pm.duplicate(source_node)[0]
                pm.connectAttr(curve.attr(source.split('.')[-1]), destination, f=True)

        # Everything going out: only the layer connections, because the output that drives the
        # object is the caller's to make once it knows what it is connecting to.
        for source, destination in blend_connections['output'].items():
            if isinstance(pm.PyNode(destination).node(), pm.nt.AnimLayer):
                pm.connectAttr(source, destination, f=True)

        new_mapping.append([dup_blend, duped_anim_layer])

    # Re-stack the copies: each blend node's inputA is the one below it, as in the original.
    for blend_node, next_pair in zip(new_mapping, new_mapping[1:]):
        next_blend_node = next_pair[0]
        if isinstance(blend_node[0], pm.nt.AnimBlendNodeBase) and \
                isinstance(next_blend_node, pm.nt.AnimBlendNodeBase):
            next_blend_node.output >> blend_node[0].inputA

    return [new_mapping, anim_layer_list]


def merge_anim_layer_network(anim_blend, new_anim_blend, delete_curve=True):
    """
    Put one blend chain underneath another, merging their base layer curves.

    :param pm.nt.AnimBlendNodeBase anim_blend: The chain that ends up at the bottom.
    :param pm.nt.AnimBlendNodeBase new_anim_blend: The chain that ends up on top.
    :param bool delete_curve: Delete the merged-from base curves once copied.
    :return: True when the two chains were connected.
    :rtype: bool
    """

    anim_map = get_all_anim_blends_in_network(new_anim_blend)
    if not anim_map:
        logger.warning('%s is not the top of a layer network, so nothing was merged.',
                       new_anim_blend)
        return False

    original_base_curves = get_base_anim_curves(anim_blend)
    new_base_curves = get_base_anim_curves(new_anim_blend)
    if len(new_base_curves) == len(original_base_curves):
        for new_curve, original_curve in zip(new_base_curves, original_base_curves):
            anim_curves.replace_into_curve(new_curve, original_curve, delete_curve=delete_curve)
    else:
        logger.warning('The two networks have different numbers of base curves (%s and %s), so '
                       'their base animation was left alone.',
                       len(new_base_curves), len(original_base_curves))

    last_anim_blend = anim_map[-1]
    if last_anim_blend.inputA.isCompound():
        input_attrs = last_anim_blend.inputA.getChildren()
        output_attrs = anim_blend.output.getChildren()
        for output_attr, input_attr in zip(output_attrs, input_attrs):
            pm.disconnectAttr(output_attr)
            pm.connectAttr(output_attr, input_attr, f=True)
    else:
        pm.connectAttr(anim_blend.output, last_anim_blend.inputA, f=True)
    return True


# --------------------------------------------------------------------------------------- #
# layer membership
# --------------------------------------------------------------------------------------- #
def connect_layer_dagSetMembers(obj_attr, anim_layer):
    """
    Add an object attribute to an animation layer's membership.

    ``dagSetMembers`` is a multi attribute, so this walks it for the first free index. It checks
    first whether the attribute is already in there - the version before it did not, so restoring
    the same animation onto the same flag twice left the layer holding two entries for one
    attribute, and Maya's own layer editor then showed the flag twice.

    :param pm.nt.Attribute obj_attr: The attribute to add.
    :param pm.nt.AnimLayer anim_layer: The layer to add it to.
    :return: True when the attribute was added, False when it was already a member.
    :rtype: bool
    """

    for index in range(MAX_LAYER_MEMBERS):
        connected = anim_layer.dagSetMembers[index].listConnections(plugs=True)
        if not connected:
            pm.connectAttr(obj_attr, anim_layer.dagSetMembers[index], f=True)
            return True
        if obj_attr in connected:
            return False

    logger.warning('%s has more than %s members, so %s was not added to it.',
                   anim_layer, MAX_LAYER_MEMBERS, obj_attr)
    return False


def connect_layer_to_base_layer(anim_layer):
    """
    Parent an animation layer to the scene's base layer.

    A layer that is not under the base layer is in the scene but not in the stack: it holds
    curves, it shows in the outliner, and it has no effect on anything.

    :param pm.nt.AnimLayer anim_layer: The layer to parent.
    :return: True when the layer ended up under the base layer.
    :rtype: bool
    """

    root_layer = pm.animLayer(q=True, r=True)
    if not root_layer:
        # Maya makes BaseAnimation the first time any layer is created, and only then. Making one
        # and throwing it away is how you ask for the base layer to exist.
        pm.delete(pm.animLayer())
        root_layer = pm.animLayer(q=True, r=True)
        logger.warning('There was no base animation layer in the scene, so %s was created.',
                       root_layer)

    if pm.animLayer(anim_layer, query=True, parent=True) == root_layer:
        logger.debug('%s is already under the base layer %s.', anim_layer, root_layer)
        return True

    if anim_layer not in (root_layer.childrenSolo.listConnections() or []):
        pm.connectAttr(anim_layer.solo,
                       root_layer.childrenSolo[pm.getAttr(root_layer.childrenSolo, size=True)],
                       f=True)
    if anim_layer not in (root_layer.childrenLayers.listConnections() or []):
        pm.connectAttr(anim_layer.parentLayer,
                       root_layer.childrenLayers[pm.getAttr(root_layer.childrenLayers, size=True)],
                       f=True)

    # Solo, mute and weight are inherited down the stack, so a layer that is not wired to its
    # parent for all three ignores the parent being muted or soloed.
    pm.connectAttr(root_layer.childsoloed, anim_layer.siblingSolo, f=True)
    pm.connectAttr(root_layer.outMute, anim_layer.parentMute, f=True)
    pm.connectAttr(root_layer.foregroundWeight, anim_layer.parentWeight, f=True)
    return True


# --------------------------------------------------------------------------------------- #
# storing
# --------------------------------------------------------------------------------------- #
def store_object_animation(obj,
                           keep_animation=True,
                           min_time_range=None,
                           max_time_range=None,
                           merge_layers=False,
                           start_time=None):
    """
    Take an object's animation off it, as something that can be stored on a node.

    Every attribute driven by a plain curve gives back that curve; every attribute driven through
    layers gives back a duplicated blend chain. Either way the answer is a mapping of plug name to
    the output attribute that should be reconnected to it later.

    :param pm.nt.Transform obj: The object whose animation is wanted.
    :param bool keep_animation: Work on duplicates, leaving the object animated.
    :param float min_time_range: Drop keys before this frame. None keeps them.
    :param float max_time_range: Drop keys after this frame. None keeps them.
    :param bool merge_layers: Flatten the scene's animation layers first, so the result is plain
        curves rather than a blend chain.
    :param float start_time: Move the stored animation so it begins on this frame.
    :return: ``{plug name: output attribute}``, empty when the object has no animation.
    :rtype: dict
    """

    attr_curves = {}

    if merge_layers and check_obj_for_anim_layer(obj=obj):
        baking.merge_all_animation_layers()

    curves = obj.listConnections(type=(pm.nt.AnimCurve, pm.nt.AnimBlendNodeBase), scn=True, d=False)
    if not curves:
        logger.debug('%s has no animation on it, so nothing was stored.', obj)
        return attr_curves

    for curve in list(set(curves)):
        if isinstance(curve, pm.nt.AnimCurve):
            plug, curve = create_dict_curve_connections(curve, keep_animation)
            if plug is None:
                continue

            if min_time_range is not None or max_time_range is not None:
                anim_curves.crop_time_range(node_list=curve,
                                            min_time=min_time_range,
                                            max_time=max_time_range)
                if not pm.objExists(curve):
                    # Every key fell outside the crop, so Maya deleted the curve. There is
                    # nothing to store for this plug; carry on with the rest.
                    logger.warning('%s had no keys in %s-%s, so it is not in the stored set.',
                                   plug, min_time_range, max_time_range)
                    continue

            if start_time is not None:
                # isinstance(start_time, int) was the old test, which is False for 12.0 and for
                # every start frame a cinematic tool works out as a float.
                key_times = pm.keyframe(curve, q=True) or []
                if key_times:
                    anim_curves.change_curve_start_time(node_list=curve,
                                                        shift_length=start_time - key_times[0])

            attr_curves[plug] = curve.output

        elif isinstance(curve, pm.nt.AnimBlendNodeBase):
            attr_curves.update(create_anim_layer_network(curve,
                                                         keep_animation,
                                                         min_time_range,
                                                         max_time_range))

    return attr_curves


def create_anim_layer_network(anim_blend, keep_animation=True, min_time_range=None, max_time_range=None):
    """
    Duplicate a blend chain so it can be stored, and say which plug it belongs to.

    :param pm.nt.AnimBlendNodeBase anim_blend: The blend node driving the attribute.
    :param bool keep_animation: Leave the original chain driving the object. False deletes it.
    :param float min_time_range: Drop keys before this frame. None keeps them.
    :param float max_time_range: Drop keys after this frame. None keeps them.
    :return: ``{plug name: output attribute(s)}``, empty when there was nothing to duplicate.
    :rtype: dict
    """

    attr_curves = {}
    if not anim_blend:
        logger.warning('There is no connected animation blend node, so nothing was stored.')
        return attr_curves

    if anim_blend.output.isCompound():
        obj_attrs = attr_utils.get_compound_attr_connections(anim_blend, 'output', as_plugs=True)
    else:
        obj_attrs = lists.get_first_in_list(anim_blend.output.listConnections(plugs=True) or [])
    if not obj_attrs:
        logger.warning('%s drives nothing, so there is no plug to store it under.', anim_blend)
        return attr_curves

    mapped_layers = map_anim_layers(anim_blend)
    new_mapping, _ = duplicate_anim_layer_network(mapped_layers)
    if not new_mapping:
        logger.warning('Duplicating the layer network on %s produced nothing.', anim_blend)
        return attr_curves
    new_anim_blend = pm.PyNode(new_mapping[0][0])

    if not keep_animation:
        delete_anim_blends_and_curves(anim_blend)

    curves = get_all_curves_in_layer_network(new_anim_blend)
    if curves and (min_time_range is not None or max_time_range is not None):
        anim_curves.crop_time_range(node_list=curves,
                                    min_time=min_time_range,
                                    max_time=max_time_range)

    if isinstance(obj_attrs, list):
        plug = '{0}_{1}'.format(naming.get_basename(obj_attrs[0].node()),
                                str(obj_attrs[0].parent()).split('.')[-1])
        attr_curves[plug] = new_anim_blend.output.getChildren()
    else:
        attr_curves[naming.get_basename(obj_attrs)] = new_anim_blend.output
    return attr_curves


def create_dict_curve_connections(curve, keep_animation=True):
    """
    Work out which plug a curve drives, and hand back the curve to store for it.

    Namespaces come off both names: what is stored has to match up with an object in a different
    scene, under a different namespace or none.

    :param pm.nt.AnimCurve curve: The curve to store.
    :param bool keep_animation: Store a duplicate, leaving the original driving the object.
    :return: ``(plug name, curve)``, or ``(None, curve)`` when the curve drives nothing.
    :rtype: tuple
    """

    plug = lists.get_first_in_list(curve.listConnections(plugs=True) or [])
    if plug is None:
        logger.warning('%s drives nothing, so there is no plug to store it under.', curve)
        return None, curve

    if keep_animation:
        curve = pm.duplicate(curve)[0]

    curve = pm.PyNode(curve.rename(naming.get_basename(curve)))
    return naming.get_basename(plug), curve


# --------------------------------------------------------------------------------------- #
# restoring
# --------------------------------------------------------------------------------------- #
def restore_for_anim_layers(anim_blend,
                            object_attribute,
                            keep_curves=False,
                            delete_old_curves=False,
                            start_time=None):
    """
    Put a stored blend chain back onto an object attribute.

    :param pm.nt.AnimBlendNodeBase anim_blend: The stored chain's top blend node.
    :param pm.nt.Attribute object_attribute: The attribute to drive.
    :param bool keep_curves: Restore a duplicate, leaving the stored chain where it is.
    :param bool delete_old_curves: Delete whatever is already driving the attribute.
    :param float start_time: Move the animation so it begins on this frame.
    :return: The last frame of the restored animation, or None when it was not moved.
    :rtype: float
    """

    end_time = None
    if keep_curves:
        # Duplicate the network and carry on with the COPY, so the stored curves survive being
        # applied. Discarding this return meant the duplicate was orphaned in the scene and the
        # original was connected to the target anyway - i.e. keep_curves did the opposite of
        # what it says.
        anim_blend = keep_anim_layer_curves(anim_blend)
    else:
        swap_anim_layer_curves(anim_blend=anim_blend, object_attribute=object_attribute)

    if start_time is not None:
        end_time = adjust_layers_timeline(anim_blend=anim_blend, start_time=start_time)

    if object_attribute.isCompound():
        obj_curves = list(set(attr_utils.get_compound_attr_connections(node=object_attribute,
                                                                       destination=False,
                                                                       source=True) or []))
    else:
        obj_curves = object_attribute.listConnections(d=False, s=True) or []

    if not obj_curves or delete_old_curves:
        for obj_curve in obj_curves:
            delete_all_old_curves(obj_curve)
        connect_anim_layer_curves(anim_blend, object_attribute)
        return end_time

    if isinstance(obj_curves[0], pm.nt.AnimCurve):
        base_curves = get_base_anim_curves(anim_blend)
        # Pair them up; the old loop ran to len(base_curves) while indexing obj_curves, so a
        # target with fewer existing curves than the stored network raised IndexError. Only the
        # curves that were actually copied into the stored network are deleted - the rest are
        # animation nobody has a copy of.
        merged = []
        for obj_curve, base_curve in zip(obj_curves, base_curves):
            if anim_curves.replace_into_curve(obj_curve, base_curve):
                merged.append(obj_curve)
        if len(merged) != len(obj_curves):
            logger.warning('%s of %s existing curves on %s could not be merged into the stored '
                           'network, so they were left in the scene.',
                           len(obj_curves) - len(merged), len(obj_curves), object_attribute)
        if merged:
            pm.delete(merged)
    elif isinstance(obj_curves[0], pm.nt.AnimBlendNodeBase):
        merge_anim_layer_network(obj_curves[0], anim_blend)

    # Outside the branches on purpose. This used to sit inside `if base_curves:`, so a stored
    # network whose base layer held no curve left the object with its old animation and the
    # whole stored chain orphaned in the scene.
    connect_anim_layer_curves(anim_blend, object_attribute)
    return end_time


def connect_anim_layer_curves(anim_blend, object_attribute):
    """
    Wire a blend chain's output to the attribute it should drive.

    :param pm.nt.AnimBlendNodeBase anim_blend: The chain's top blend node.
    :param pm.nt.Attribute object_attribute: The attribute to drive.
    :return: True when the connection was made.
    :rtype: bool
    """

    blend_is_compound = anim_blend.output.isCompound()
    attr_is_compound = object_attribute.isCompound()

    if not blend_is_compound and not attr_is_compound:
        # force, because the attribute may still be holding an old curve that could not be
        # merged away - the new chain wins either way.
        pm.connectAttr(anim_blend.output, object_attribute, f=True)
        return True

    if not (blend_is_compound and attr_is_compound):
        logger.warning('There is a mismatch between object attribute and animation blend. Both '
                       'need to be either a compound or a single attribute: %s, %s.',
                       anim_blend.output, object_attribute)
        return False

    blend_attrs = attr_utils.get_all_attributes_from_compound_attr(anim_blend.output) or []
    object_attrs = attr_utils.get_all_attributes_from_compound_attr(object_attribute) or []
    if len(blend_attrs) != len(object_attrs):
        logger.warning('%s has %s children and %s has %s, so they were not connected.',
                       anim_blend.output, len(blend_attrs), object_attribute, len(object_attrs))
        return False

    for blend_attr, object_attr in zip(blend_attrs, object_attrs):
        pm.connectAttr(blend_attr, object_attr, f=True)

    # A rotation blend evaluates its inputs in the object's rotate order, and a blend node
    # restored onto an object with a different one blends the wrong pair of axes together.
    for blend in get_all_anim_blends_in_network(anim_blend):
        if blend.hasAttr('rotateOrder'):
            object_attribute.node().rotateOrder >> blend.rotateOrder
    return True


def keep_anim_layer_curves(anim_blend):
    """
    Duplicate a stored blend chain, so restoring it does not consume it.

    :param pm.nt.AnimBlendNodeBase anim_blend: The stored chain's top blend node.
    :return: The duplicate's top blend node, or the original when there was nothing to duplicate.
    :rtype: pm.nt.AnimBlendNodeBase
    """

    mapped_layers = map_anim_layers(anim_blend)
    if not mapped_layers:
        logger.warning('No animation layer network found on %s; nothing to duplicate.', anim_blend)
        return anim_blend

    root_layer = pm.animLayer(q=True, r=True)
    anim_layer_list = (root_layer.childrenLayers.listConnections() or []) if root_layer else []

    # duplicate_anim_layer_network returns [mapping, layers] - unpack both. This used to bind the
    # whole two-element wrapper to new_mapping, so the loop below tried to unpack the mapping
    # list itself into two names and new_mapping[0][0] handed back a [blend, layer] pair instead
    # of a blend.
    new_mapping, _ = duplicate_anim_layer_network(mapped_layers, anim_layer_list)
    if not new_mapping:
        logger.warning('Duplicating the layer network for %s produced nothing.', anim_blend)
        return anim_blend

    for _, anim_layer in new_mapping:
        if anim_layer not in anim_layer_list:
            connect_layer_to_base_layer(anim_layer)
    return new_mapping[0][0]


def swap_anim_layer_curves(anim_blend, object_attribute):
    """
    Put a stored chain's layers into the scene's stack, and the attribute into each layer.

    :param pm.nt.AnimBlendNodeBase anim_blend: The chain's top blend node.
    :param pm.nt.Attribute object_attribute: The attribute the layers should hold.
    :return: The layers that were connected.
    :rtype: list(pm.nt.AnimLayer)
    """

    root_layer = pm.animLayer(q=True, r=True)
    root_connections = (root_layer.listConnections() or []) if root_layer else []

    layers = [layer for layer in get_all_anim_layers_in_network(anim_blend) if layer]
    for anim_layer in layers:
        if anim_layer not in root_connections:
            connect_layer_to_base_layer(anim_layer)
        connect_layer_dagSetMembers(object_attribute, anim_layer)
    return layers


def adjust_layers_timeline(anim_blend, start_time):
    """
    Shift every curve in a blend chain along the timeline.

    :param pm.nt.AnimBlendNodeBase anim_blend: The chain's top blend node.
    :param float start_time: How far to shift by.
    :return: The last frame across all of the chain's curves, or None when it has none.
    :rtype: float
    """

    if start_time is None:
        return None

    end_frame = None
    for curve in get_all_curves_in_layer_network(anim_blend):
        anim_curves.change_curve_start_time(node_list=curve, shift_length=start_time)
        key_times = pm.keyframe(curve, q=True) or []
        if not key_times:
            continue
        # The latest last key, not whichever curve Maya happened to list last.
        end_frame = key_times[-1] if end_frame is None else max(end_frame, key_times[-1])
    return end_frame


def delete_anim_blends_and_curves(anim_blend):
    """
    Delete a whole blend chain: its blend nodes and every curve feeding them.

    :param pm.nt.AnimBlendNodeBase anim_blend: The chain's top blend node.
    """

    blend_nodes = get_all_anim_blends_in_network(anim_blend)
    curves = get_all_curves_in_layer_network(anim_blend)
    if blend_nodes or curves:
        pm.delete(blend_nodes, curves)


def delete_all_old_curves(anim_obj):
    """
    Delete whatever is driving an attribute, whether that is one curve or a whole chain.

    :param anim_obj: An animation curve or a blend node.
    """

    if isinstance(anim_obj, pm.nt.AnimCurve):
        pm.delete(anim_obj)
    elif isinstance(anim_obj, pm.nt.AnimBlendNodeBase):
        delete_anim_blends_and_curves(anim_obj)
