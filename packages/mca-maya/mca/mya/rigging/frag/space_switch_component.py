"""
Letting a control choose what it follows: an enum, and a constraint per choice.

A hand should be able to follow the arm, the chest, or nothing at all, and an animator should be
able to change which one mid-shot. ``space_switch_rig`` builds that out of one point and one orient
constraint per space, a condition node per space that turns its pair of weights on when the enum
matches, and the enum itself on a control. This is the metadata node around it, which is what lets
a rig be taken apart and put back together with its spaces intact.

It is the second of two of these. :class:`~multi_constraint.MultiConstraint` does the same job with
a matrix network and a group above the control, and is the one the rig templates use;
``space_switch_rig`` is the constraint-based one, and both are kept because a rig in the depot may
carry either. Which is which is written down in ``multi_constraint``'s module docstring.

What was wrong before:

- **A switch that could not be built was recorded as though it had been.** ``space_switch_rig``
  answers an empty result - no constraints, no conditions, no group - when it is handed no spaces,
  or when the switch attribute is already on the control. ``create`` wrote that empty answer onto
  the node and handed back a component with a ``switchAttrName`` naming an enum that is not there.
  It asks, and refuses.
- **``switchAttrName`` was added by hand with a guard and then set through the attribute.** The
  guard is what ``attr_utils.set_attribute`` does, and the name of the attribute was a bare string
  in three places.
- ``t`` and ``r`` are undocumented short spellings of ``translate`` and ``rotate``, read out of
  ``**kwargs``, which silently win over the named parameters. They are passed through to
  ``space_switch_rig``, which documents them as the older spellings, and the component's own
  signature says so rather than reading them back out of a dictionary.
- ``default_name`` - which renames the first entry of the enum, for when the first space is "world"
  rather than a node - was read out of ``**kwargs`` and not recorded among the build arguments, so
  a rebuild lost it.
- The six properties read their attributes as bare strings, and ``node.rename`` was called on the
  wrapper rather than on the node, which works only because ``FRAGNode`` forwards it.
"""

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import space_switch_rig
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What the component keeps its pieces on.
SWITCH_GROUP_ATTR = 'switchGroup'
SOURCE_OBJECT_ATTR = 'sourceObject'
SWITCH_OBJECT_ATTR = 'switchObject'
POINT_CONSTRAINTS_ATTR = 'pointConstraints'
ORIENT_CONSTRAINTS_ATTR = 'orientConstraints'
CONDITIONS_ATTR = 'conditions'
SWITCH_ATTR_NAME_ATTR = 'switchAttrName'

#: The attributes this component puts on the two nodes it points at, so each of them can say which
#: switch it belongs to.
SOURCE_PARENT_ATTR = 'sourceSpaceConstraint'
SWITCH_PARENT_ATTR = 'switchObject'


class SpaceSwitchComponent(frag_base.FRAGNode):
    """
    One control, several spaces it can follow, and the enum that chooses between them.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, side, region, source_object, target_list, switch_obj=None,
               translate=True, rotate=True, switch_attr=space_switch_rig.SWITCH_ATTR,
               default_name=None, **kwargs):
        """
        Build the switch and the node that records it.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param str side: Which side of the body it is on, for the node's name.
        :param str region: What part of the body it is, for the node's name.
        :param pm.nt.Transform source_object: The control being switched.
        :param target_list: The spaces it can follow, in the order they appear in the enum.
        :param pm.nt.Transform switch_obj: The node the enum goes on. None means the control itself.
        :param bool translate: Follow the spaces in translation.
        :param bool rotate: Follow them in rotation.
        :param str switch_attr: The name of the enum.
        :param str default_name: A name for the first entry of the enum, for when the first space is
            "world" or "default" rather than a node an animator would recognise.
        :param dict kwargs: ``t`` and ``r`` are older spellings of ``translate`` and ``rotate``, and
            win over them when given - which is what the version before did silently.
        :return: The component, or None when the switch could not be built.
        :rtype: SpaceSwitchComponent or None
        """

        follow_translate = kwargs.get('t', translate)
        follow_rotate = kwargs.get('r', rotate)
        switch_obj = switch_obj or source_object

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        # Built before the node, so a switch that cannot be built leaves nothing behind. The version
        # before wrote an empty result onto a node and handed back a component whose switchAttrName
        # named an enum that was not there.
        built = space_switch_rig.space_switch(target_list=target_list,
                                             source_object=source_object,
                                             switch_obj=switch_obj,
                                             translate=follow_translate,
                                             rotate=follow_rotate,
                                             switch_attr=switch_attr,
                                             default_name=default_name)
        if not built['conditions']:
            logger.warning('No space switch was built on %s, so no component was made for it.',
                           source_object)
            return None

        node = frag_base.FRAGNode.create(frag_parent, SpaceSwitchComponent.__name__,
                                         version=SpaceSwitchComponent.VERSION)
        node.pynode.rename('{0}_{1}_{2}'.format(SpaceSwitchComponent.__name__, side, region))
        attr_utils.set_compound_attribute_groups(
            node.pynode, frag_base.BUILD_KWARGS_ATTR,
            {'translate': follow_translate, 'rotate': follow_rotate, 'switch_attr': switch_attr,
             'default_name': default_name})

        node.connect_node(built['switch_offset_grp'], SWITCH_GROUP_ATTR,
                          frag_base.FRAG_PARENT_ATTR)
        node.connect_node(source_object, SOURCE_OBJECT_ATTR, parent_attr=SOURCE_PARENT_ATTR)
        node.connect_node(switch_obj, SWITCH_OBJECT_ATTR, parent_attr=SWITCH_PARENT_ATTR)
        node.connect_nodes(built['point_constraints'], POINT_CONSTRAINTS_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(built['orient_constraints'], ORIENT_CONSTRAINTS_ATTR,
                           frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(built['conditions'], CONDITIONS_ATTR, frag_base.FRAG_PARENT_ATTR)
        attr_utils.set_attribute(node.pynode, {SWITCH_ATTR_NAME_ATTR: switch_attr})

        return node

    @property
    def source_object(self):
        """
        :return: The control being switched.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(SOURCE_OBJECT_ATTR).get()

    @property
    def switch_object(self):
        """
        :return: The node carrying the enum, which may or may not be the control.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(SWITCH_OBJECT_ATTR).get()

    @property
    def switch_attr(self):
        """
        :return: The name of the enum on that node.
        :rtype: str
        """

        return self.pynode.attr(SWITCH_ATTR_NAME_ATTR).get()

    @property
    def point_constraints(self):
        """
        :return: The constraints carrying each space's position.
        :rtype: list(pm.nt.PointConstraint)
        """

        return self.pynode.attr(POINT_CONSTRAINTS_ATTR).get() or []

    @property
    def orient_constraints(self):
        """
        :return: The constraints carrying each space's rotation.
        :rtype: list(pm.nt.OrientConstraint)
        """

        return self.pynode.attr(ORIENT_CONSTRAINTS_ATTR).get() or []

    @property
    def conditions(self):
        """
        :return: The nodes that turn each space's weights on when the enum matches.
        :rtype: list(pm.nt.Condition)
        """

        return self.pynode.attr(CONDITIONS_ATTR).get() or []

    @property
    def switch_group(self):
        """
        :return: The group above the control that the constraints drive.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(SWITCH_GROUP_ATTR).get()
