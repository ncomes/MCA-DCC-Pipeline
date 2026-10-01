"""
The component that lets one control follow whichever of several things an animator picks.

A hand should follow the arm most of the time, the chest when a character folds its arms, and the
world when it rests on a table. That is a multi constraint: the control is matrix-constrained to one
of a list of targets, an enum attribute on it says which, and a pair of ``choice`` nodes swap the
matrices over when the enum changes. ``multi_constraint_rig`` builds the network; this is the
metadata node that remembers what was built, so the switch can be found, serialized and taken apart
again.

What was wrong before:

- **Building a second multi constraint on a control raised something unreadable.** The builder
refuses
  when the control already carries the switch attribute - it says so in the log and answers a result
  with nothing in it - and ``create`` then connected those empty slots straight to the node, so what
  the caller actually saw was ``MayaNodeError`` out of ``pm.PyNode(None)``. The same happened when
  it was given no targets. It checks the build worked and says what went wrong now.
- **``remove`` raised on a node whose switch or source object had gone.** Both are read off message
  attributes and both can answer nothing, and the next line asks ``hasAttr`` of it.
- **``remove`` raised when there was nothing to put back.** It reparents whatever the control's
group
  held, with ``pm.parent(pm.listRelatives(group), parent_group.getParent())`` - and when the group
  is empty *and* the group above it is at the world root, that is ``pm.parent`` with no arguments
  left, which falls back to the selection and raises ``TypeError: Error retrieving default
  arguments``. A switch whose control has been deleted is exactly that pair of nothings.
- **``remove`` deleted one attribute without checking it was there.** Every attribute in its list is
  guarded with ``hasAttr`` except ``sourceMultiConstraint``, which is deleted outright - so removing
  a multi constraint twice, or one whose control had been cleaned up by hand, raised.
- **``get_build_kwargs`` was the third copy of itself**, which its own docstring admitted and left
for
  later: ``RigComponent`` had one, this had one, and ``SkeletalMesh`` wrote the attribute with no
  reader at all. It is on ``FRAGNode`` now, where all three inherit it.
- The separator attribute the switch sits under was the bare string ``'__'`` here and
  ``SEPARATOR_ATTR`` in the module that puts it there. A ``# strip wrapped nodes`` comment sat above
  a line that strips nothing - ``connect_nodes`` does the unwrapping itself.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import matrix_nodes
from mca.mya.rigging import multi_constraint_rig
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils


logger = log.MCA_LOGGER

#: The nodes the switch is made of, and the attributes they hang off.
MULTI_MATRIX_ATTR = 'multiMatrix'
DECOMP_MATRIX_ATTR = 'decompMatrix'
CONSTRAINT_GROUP_ATTR = 'constraintGroup'
PARENT_CONSTRAINT_GROUP_ATTR = 'parentConstraintGroup'
CHOICE_OFFSET_ATTR = 'choiceOffset'
CHOICE_SPACE_ATTR = 'choiceSpace'

#: What the switch drives, what carries the enum, and what it can follow.
SOURCE_OBJECT_ATTR = 'sourceObject'
SWITCH_OBJECT_ATTR = 'switchObject'
TARGETS_ATTR = 'targets'

#: The name of the enum, kept on the node so it can be found again without guessing.
SWITCH_ATTR_NAME_ATTR = 'switchAttrName'

#: What the control itself carries, pointing back at the node that built the switch.
SOURCE_MULTI_CONSTRAINT_ATTR = 'sourceMultiConstraint'

#: What ``multi_constraint_rig`` answers, paired with the attribute each one is kept on.
_BUILT_NODE_ATTRS = (('multi_matrix', MULTI_MATRIX_ATTR),
                     ('decomp_matrix', DECOMP_MATRIX_ATTR),
                     ('constraint_group', CONSTRAINT_GROUP_ATTR),
                     ('parent_constraint_group', PARENT_CONSTRAINT_GROUP_ATTR),
                     ('choice_offset', CHOICE_OFFSET_ATTR),
                     ('choice_space', CHOICE_SPACE_ATTR))


class MultiConstraint(frag_base.FRAGNode):
    """
    One control, and the list of things it can be made to follow.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent,
               side,
               region,
               source_object,
               target_list,
               switch_obj=None,
               translate=True,
               rotate=True,
               scale=True,
               switch_attr=multi_constraint_rig.SWITCH_ATTR,
               **kwargs):
        """
        Build a switch on a control.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param str side: Which side of the body the control is on, for the node's name.
        :param str region: What part of the body it is, for the same.
        :param pm.nt.Transform source_object: The control being driven.
        :param list target_list: What it can follow, in the order the enum lists them.
        :param pm.nt.Transform switch_obj: What carries the enum. None puts it on the control
        itself. :param bool translate: Follow their position.
        :param bool rotate: Follow their orientation.
        :param bool scale: Follow their scale.
        :param str switch_attr: What to call the enum.
        :param dict kwargs: ``t``, ``r`` and ``s`` are older spellings of the three above, and
            ``default_name`` renames the first entry in the enum.
        :return: The node, or None when the switch could not be built - which is what happens when
        the
            control already carries the enum, or there is nothing for it to follow.
        :rtype: MultiConstraint or None
        """

        follow_translate = kwargs.get('t', translate)
        follow_rotate = kwargs.get('r', rotate)
        follow_scale = kwargs.get('s', scale)
        switch_obj = switch_obj or source_object

        # The network first: it is the thing that can refuse, and there is no sense in a metadata
        # node describing a switch that was not built. Connecting its empty answer is what used to
        # raise MayaNodeError out of pm.PyNode(None).
        built = multi_constraint_rig.multi_constraint(target_list=target_list,
                                                     source_object=source_object,
                                                     switch_obj=switch_obj,
                                                     translate=follow_translate,
                                                     rotate=follow_rotate,
                                                     scale=follow_scale,
                                                     switch_attr=switch_attr,
                                                     default_name=kwargs.get('default_name'))
        missing = [result_key for result_key, _ in _BUILT_NODE_ATTRS if not built.get(result_key)]
        if missing:
            logger.warning('No multi constraint was built for %s on %s, so there is nothing to '
                           'describe. %s has already said why.',
                           region, source_object, multi_constraint_rig.__name__)
            return None

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set='{0}:'.format(root_namespace))

        node = frag_base.FRAGNode.create(frag_parent, MultiConstraint.__name__,
                                        version=MultiConstraint.VERSION)
        node.pynode.rename('{0}_{1}_{2}'.format(MultiConstraint.__name__, side, region))

        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 {'translate': follow_translate,
                                                  'rotate': follow_rotate,
                                                  'scale': follow_scale,
                                                  'side': side,
                                                  'region': region,
                                                  'switch_attr': switch_attr})
        node.side = side
        node.region = region

        node.pynode.addAttr(SWITCH_ATTR_NAME_ATTR, dt='string')
        node.pynode.attr(SWITCH_ATTR_NAME_ATTR).set(switch_attr)

        for result_key, attr_name in _BUILT_NODE_ATTRS:
            node.connect_node(built[result_key], attr_name, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(source_object, SOURCE_OBJECT_ATTR,
                          parent_attr=SOURCE_MULTI_CONSTRAINT_ATTR)
        node.connect_node(switch_obj, SWITCH_OBJECT_ATTR, parent_attr=SWITCH_OBJECT_ATTR)
        node.connect_nodes(target_list, TARGETS_ATTR)

        return node

    # ----------------------------------------------------------------------------------- #
    # what it is made of
    # ----------------------------------------------------------------------------------- #
    def get_constraint_group(self):
        """
        :return: The group the control sits in, which is what the matrices drive.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(CONSTRAINT_GROUP_ATTR).get()

    def get_parent_constraint_group(self):
        """
        :return: The group above that one, which holds the switch's offset.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(PARENT_CONSTRAINT_GROUP_ATTR).get()

    def get_switch_attr(self):
        """
        :return: The name of the enum an animator picks a target with.
        :rtype: str
        """

        return self.pynode.attr(SWITCH_ATTR_NAME_ATTR).get()

    def get_targets(self):
        """
        :return: What the control can be made to follow, in the order the enum lists them.
        :rtype: list(pm.nt.Transform)
        """

        return self.pynode.attr(TARGETS_ATTR).listConnections()

    def get_source_object(self):
        """
        :return: The control being driven.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(SOURCE_OBJECT_ATTR).get()

    def get_switch_object(self):
        """
        :return: Whatever carries the enum, which is usually the control itself.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(SWITCH_OBJECT_ATTR).get()

    def get_flags(self):
        """
        :return: Nothing. A switch is built onto a control that already exists; it owns none.
        :rtype: list
        """

        return []

    def serialize_component(self):
        """
        Everything about this switch that would be needed to build it again.

        :return: Its side and region, what it drives, what it can follow, and what carries the enum.
        :rtype: dict
        """

        source_object = self.get_source_object()
        switch_object = (self.get_switch_object()
                         if self.has_attribute(SWITCH_OBJECT_ATTR) else None)
        switch_attr = (self.get_switch_attr()
                       if self.has_attribute(SWITCH_ATTR_NAME_ATTR) else None)
        return {'side': self.side,
                'region': self.region,
                'source_object': source_object.nodeName() if source_object else None,
                'targets': [target.nodeName() for target in self.get_targets()],
                'switch_object': switch_object.nodeName() if switch_object else None,
                'switch_attr': switch_attr}

    # ----------------------------------------------------------------------------------- #
    # taking it apart
    # ----------------------------------------------------------------------------------- #
    def remove(self):
        """
        Take the switch off the control: the enum and the markup, the groups, and this node.

        Whatever the control's group held is parented back where the group was, so the control stays
        where it is in the rig.
        """

        source_object = self.get_source_object()
        switch_object = self.get_switch_object()

        attr_names = [matrix_nodes.CONSTRAINT_ATTR,
                      matrix_nodes.PARENT_CONSTRAINT_ATTR,
                      matrix_nodes.PARENT_CONSTRAINT_OBJECT_ATTR,
                      SWITCH_OBJECT_ATTR,
                      SOURCE_MULTI_CONSTRAINT_ATTR,
                      multi_constraint_rig.SEPARATOR_ATTR]
        if self.has_attribute(SWITCH_ATTR_NAME_ATTR):
            attr_names.append(self.get_switch_attr())

        # Either can be gone - they are message connections - and asking None for an attribute is
        # what this used to do. sourceMultiConstraint was deleted outside the guard the rest had.
        for multi_object in (switch_object, source_object):
            if multi_object is None:
                continue
            for attr_name in attr_names:
                if not multi_object.hasAttr(attr_name):
                    continue
                multi_object.attr(attr_name).unlock()
                multi_object.deleteAttr(attr_name)

        constraint_group = self.get_constraint_group()
        parent_constraint_group = self.get_parent_constraint_group()
        constrained_children = pm.listRelatives(constraint_group) if constraint_group else []
        if constrained_children and parent_constraint_group is not None:
            # Both halves have to be asked about. `pm.parent` with nothing to move and nowhere to
            # move it to has no arguments left at all and falls back to the selection, which raises
            # `TypeError: Error retrieving default arguments` - and a switch whose control has been
            # deleted, on a group at the world root, is exactly that pair of nothings.
            group_parent = parent_constraint_group.getParent()
            if group_parent is not None:
                pm.parent(constrained_children, group_parent)
            else:
                pm.parent(constrained_children, world=True)

        # One call, deliberately. Deleting the decompose matrix takes this node with it, so deleting
        # them one at a time - which reads tidier - leaves the second delete with a name that is
        # already gone. The suite for this module pins that down.
        to_delete = [parent_constraint_group,
                     self.pynode.attr(MULTI_MATRIX_ATTR).get(),
                     self.pynode.attr(DECOMP_MATRIX_ATTR).get(),
                     self.pynode]
        pm.delete([built_node for built_node in to_delete if built_node is not None])
