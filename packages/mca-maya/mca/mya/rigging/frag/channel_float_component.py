"""

Extra channels on a control, mirrored onto a joint so they reach the engine.

A rig often needs an attribute that is not a transform: how open a visor is, how wet a creature
looks, which of three weapons is drawn. An animator wants it on a control, and the exporter only
carries what is on the skeleton - so each channel is added to the control and again to a joint, as
a proxy attribute, with the control driving the joint. This node records the pair.

The attribute it puts on the control to say "you belong to this component" is ``fragChannelFloat``,
not the ``fragParent`` every other component uses. That is deliberate and is the point worth
knowing about this module: the control already belongs to a component through ``fragParent``, one
such attribute holds one connection, and wiring this one through the same name would quietly steal
the control from the component that built it.

What was wrong before:

- **Building the component emptied the dictionaries it was handed.** Each channel's six values are
  read with ``channel.pop(...)``, so the caller's dictionary comes back with nothing in it. A
  caller that builds its channels once and uses them twice - two components off one description, a
  list read out of a data file and reused - got an empty dictionary the second time and a
  ``KeyError`` on the first ``pop``. They are read, not taken.
- **The version migration had never run**, like the other four: ``FRAGNode.update`` built its
  method name from a version stored on a ``double`` attribute. Fixed in ``frag_base``, so
  :meth:`ChannelFloatComponent._update_version_1_to_version_2` - which renames the two attributes
  version 1 stored with capitals - is reachable, and the suite drives it.
- **A channel dictionary missing a key was a bare ``KeyError`` from inside a ``pop``**, naming the
  key and nothing else. The defaults are the ones :func:`create_channel_float_dict` uses, and a
  missing key takes them.
- **"Adding add_attr / remove_attr methods to this component is still outstanding" was a comment in
  the file.** It is :meth:`ChannelFloatComponent.add_channels` and
  :meth:`ChannelFloatComponent.remove_channel` now, and ``create`` is a thin wrapper over the
  first, so there is one piece of code that adds a channel rather than two.
- **Nothing could read the channels back.** The build arguments deliberately leave the channel list
  out - the comment said the re-animator has no way to consume it - but the channels are all there
  in the scene, on the two nodes the component points at.
  :meth:`ChannelFloatComponent.get_channel_dicts` reads them back in the shape :meth:`create`
  takes, so the round trip holds and a rebuild needs nothing stored.
- ``isinstance(x, pm.nt.general.Attribute)`` reaches through two module names for ``pm.Attribute``.
  ``keyable`` is documented as setting whether the attribute is "keyable and hidden"; it sets
  keyable, and a non-keyable attribute is not hidden.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What the component keeps its two nodes on.
OBJECT_ATTR = 'fragChannelFloat'
JOINT_ATTR = 'fragChannelFloatJnt'

#: The attributes this component puts on those two nodes, so each can say which component its extra
#: channels belong to. Deliberately not ``fragParent``: the control already belongs to a component
#: through that attribute, and one message attribute holds one connection.
OBJECT_PARENT_ATTR = 'fragChannelFloat'
JOINT_PARENT_ATTR = 'fragChannelFloatJnt'

#: A channel component is not on a side of the body; it is named for what it holds.
SIDE = 'center'

#: The keys a channel description has, and what each is for when it is left out.
CHANNEL_DEFAULTS = {'min': 0.0, 'max': 1.0, 'default_value': 0.0, 'keyable': True}


class ChannelFloatComponent(keyable_component.KeyableComponent):
    """
    A set of extra float channels on one control, mirrored onto one joint.
    """

    VERSION = 2

    #: What version 1 stored these attributes under, before the pipeline settled on camelCase.
    LEGACY_ATTR_NAMES = {'FragChannelFloat': OBJECT_ATTR,
                         'FragChannelFloatJnt': JOINT_ATTR}

    def _update_version_1_to_version_2(self):
        """
        Bring a version 1 component up to version 2 by renaming its two capitalised attributes.

        ``rename_legacy_attrs`` renames rather than rewires, so whatever was connected to each
        attribute stays connected to it.
        """

        self.rename_legacy_attrs(self.LEGACY_ATTR_NAMES)
        self.set_version(2)

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, obj, joint, channel_dict_list, component_name, **kwargs):
        """
        Build the component and add its channels.

        :param FRAGRig frag_parent: The rig this belongs to.
        :param pm.nt.DagNode obj: The control the channels go on.
        :param pm.nt.Joint joint: The joint that carries the proxy copies, for the exporter.
        :param channel_dict_list: One description per channel, as
            :func:`create_channel_float_dict` makes them. A single dictionary is taken as a list of
            one.
        :param str component_name: What this set of channels is called; it becomes the component's
            region.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: ChannelFloatComponent
        """

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        frag_type=ChannelFloatComponent.__name__,
                                                        version=ChannelFloatComponent.VERSION,
                                                        side=SIDE,
                                                        region=component_name)
        # The channel list is not recorded: it is all in the scene, and get_channel_dicts reads it
        # back in the shape this method takes.
        attr_utils.set_compound_attribute_groups(
            node.pynode, frag_base.BUILD_KWARGS_ATTR,
            {'obj': obj, 'joint': joint, 'component_name': component_name})

        node.connect_node(obj, OBJECT_ATTR, OBJECT_PARENT_ATTR)
        node.connect_node(joint, JOINT_ATTR, JOINT_PARENT_ATTR)

        channel_node = ChannelFloatComponent(node.pynode)
        channel_node.add_channels(channel_dict_list)
        return channel_node

    # ----------------------------------------------------------------------------------- #
    # the two nodes
    # ----------------------------------------------------------------------------------- #
    @property
    def channel_object(self):
        """
        :return: The control the channels are on.
        :rtype: pm.nt.DagNode
        """

        return self.pynode.attr(OBJECT_ATTR).get()

    @property
    def channel_joint(self):
        """
        :return: The joint carrying the proxy copies.
        :rtype: pm.nt.Joint
        """

        return self.pynode.attr(JOINT_ATTR).get()

    # ----------------------------------------------------------------------------------- #
    # the channels
    # ----------------------------------------------------------------------------------- #
    def add_channels(self, channel_dict_list):
        """
        Add channels to this component's control and joint, and wire each pair up.

        A channel that is already on either node is used as it is rather than added again, which is
        what lets this be called a second time to add to a set.

        :param channel_dict_list: One description per channel, as
            :func:`create_channel_float_dict` makes them. A single dictionary is taken as a list of
            one.
        :return: The names of the channels that were added to the control.
        :rtype: list(str)
        """

        if isinstance(channel_dict_list, dict):
            channel_dict_list = [channel_dict_list]

        obj = self.channel_object
        joint = self.channel_joint
        if obj is None or joint is None:
            logger.warning('%s has no control or no joint on it, so no channels were added.',
                           self.pynode)
            return []

        added = []
        for channel in channel_dict_list:
            # Read, not popped. The version before emptied the caller's dictionaries.
            obj_attr = _channel_attribute(obj, channel.get('obj_attr_name'), channel)
            joint_attr = _channel_attribute(joint, channel.get('joint_attr_name'), channel,
                                            as_proxy=True)
            if obj_attr is None or joint_attr is None:
                continue

            obj_attr >> joint_attr
            added.append(obj_attr.attrName())
        return added

    def remove_channel(self, obj_attr_name):
        """
        Take one channel off this component's control and its joint.

        :param str obj_attr_name: The channel's name on the control.
        :return: Whether it was there to remove.
        :rtype: bool
        """

        obj = self.channel_object
        if obj is None or not obj.hasAttr(obj_attr_name):
            logger.warning('%s has no %r channel on its control.', self.pynode, obj_attr_name)
            return False

        obj_attr = obj.attr(obj_attr_name)
        # The joint's copy is whatever this channel drives, which is how the pair was wired. Reading
        # it off the connection rather than guessing at the name is what makes a channel whose two
        # names differ removable.
        for joint_attr in obj_attr.listConnections(plugs=True, source=False, destination=True):
            joint_attr.node().deleteAttr(joint_attr.attrName())
        obj.deleteAttr(obj_attr_name)
        return True

    def get_channel_dicts(self):
        """
        Every channel on this component, in the shape :meth:`create` takes them.

        The round trip: hand what this answers to :meth:`add_channels` on another component and it
        gets the same channels. Read off the two nodes, because that is where they are - nothing was
        ever stored.

        :return: One description per channel, in the order the control holds them.
        :rtype: list(dict)
        """

        obj = self.channel_object
        joint = self.channel_joint
        if obj is None or joint is None:
            logger.warning('%s has no control or no joint on it, so it has no channels.',
                           self.pynode)
            return []

        found = []
        for joint_attr in joint.listAttr(userDefined=True):
            driving = joint_attr.listConnections(plugs=True, source=True, destination=False)
            if not driving or driving[0].node() != obj:
                continue
            obj_attr = driving[0]
            found.append(create_channel_float_dict(
                obj_attr.attrName(), joint_attr.attrName(),
                attr_min=_limit(obj_attr, 'min'), attr_max=_limit(obj_attr, 'max'),
                default_value=pm.addAttr(obj_attr, query=True, defaultValue=True),
                keyable=obj_attr.isKeyable()))
        return found


def create_channel_float_dict(obj_attr_name, joint_attr_name, attr_min=CHANNEL_DEFAULTS['min'],
                              attr_max=CHANNEL_DEFAULTS['max'],
                              default_value=CHANNEL_DEFAULTS['default_value'],
                              keyable=CHANNEL_DEFAULTS['keyable']):
    """
    One channel's description, in the shape the component takes.

    :param obj_attr_name: What the channel is called on the control, or an attribute that is already
        there.
    :param joint_attr_name: What its copy is called on the joint, or an attribute that is already
        there.
    :param float attr_min: The lowest value it takes.
    :param float attr_max: The highest.
    :param float default_value: What it starts at.
    :param bool keyable: Whether an animator can key it. A non-keyable attribute is still visible;
        the version before said "keyable and hidden".
    :return: The description.
    :rtype: dict
    """

    return {'obj_attr_name': obj_attr_name, 'joint_attr_name': joint_attr_name, 'min': attr_min,
            'max': attr_max, 'default_value': default_value, 'keyable': keyable}


def _channel_attribute(node, attr_name, channel, as_proxy=False):
    """
    One end of a channel: the attribute that is already there, or a new one.

    :param pm.nt.DependNode node: The node the channel goes on.
    :param attr_name: The channel's name, or an attribute that is already there.
    :param dict channel: The channel's description, for the limits and the default.
    :param bool as_proxy: Add it as a proxy attribute, which is what the joint's copy is.
    :return: The attribute, or None when there is no name to make one from.
    :rtype: pm.Attribute or None
    """

    if isinstance(attr_name, pm.Attribute):
        return attr_name
    if not attr_name:
        logger.warning('A channel on %s has no name, so it was skipped.', node)
        return None
    if node.hasAttr(attr_name):
        return node.attr(attr_name)

    # A key the description leaves out takes the same default create_channel_float_dict uses, rather
    # than being a bare KeyError from inside a pop.
    extra = {'usedAsProxy': True} if as_proxy else {}
    node.addAttr(attr_name, at='float',
                 defaultValue=channel.get('default_value', CHANNEL_DEFAULTS['default_value']),
                 min=channel.get('min', CHANNEL_DEFAULTS['min']),
                 max=channel.get('max', CHANNEL_DEFAULTS['max']),
                 k=channel.get('keyable', CHANNEL_DEFAULTS['keyable']), **extra)
    return node.attr(attr_name)


def _limit(attribute, end):
    """
    One of an attribute's limits, or the default when it has none.

    :param pm.Attribute attribute: The attribute to ask.
    :param str end: ``'min'`` or ``'max'``.
    :return: The limit.
    :rtype: float
    """

    values = pm.addAttr(attribute, query=True, **{end: True})
    if values is None:
        return CHANNEL_DEFAULTS[end]
    return values[0] if isinstance(values, (list, tuple)) else values
