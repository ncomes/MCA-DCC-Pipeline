"""
What every piece of a rig has in common.

A rig is built out of components - an arm, a spine, a twist helper, a space switch - and each one is
a metadata node plus two groups: the controls the animator sees, and a ``NO_TOUCH`` group holding
everything that makes them work. :class:`RigComponent` is the half of that every component has,
whether or not it has controls: the ``NO_TOUCH`` group, the side and region markup, and the record
of what the component is attached to.

Attaching is the interesting part. A component's groups are parent constrained to whatever holds it
up - usually a control on another component - and the component remembers both the *components* it
hangs off and the *objects* it is constrained to, separately and for translation and rotation
separately. That is what lets a rig be taken apart and put back together, and what
``buildarig`` reads to rebuild an attachment.

A component that cannot finish building has to be able to take itself back out of the scene, and
there was no way to do that for a component with no controls: ``remove`` existed only on
``KeyableComponent``. It is here, and ``KeyableComponent`` extends it with its control group.

What was wrong before:

- **Attaching a component twice left the objects from the first attachment registered as well.**
  ``attach_component`` disconnects the two *component* lists before writing them again and never
  touches the two *object* lists, so they grow. ``buildarig`` reads those object lists to rebuild an
  attachment, so a component that had been reattached rebuilt against its old parents as well as its
  new ones. All four lists are cleared now.
- **``attach_component`` read ``flagGroup`` whether or not the component had one.** It is on
  :class:`RigComponent`, which is the base for components with no controls at all - a twist helper,
  an attachment - and the group it reaches for is added by ``KeyableComponent``. It constrains
  whichever of the two groups the component actually has now.
- **``align_component`` has never aligned anything.** The group is snapped to it and then frozen on
  the next line, and freezing an empty transform puts its matrix back to identity - the position
  survives only as the group's rotate and scale pivots, and the rotation is discarded outright. A
  child parented under the group afterwards lands at the world origin either way. This is left alone
  rather than fixed, because the freeze is what every rig in the depot was built against: making the
  alignment survive would move the groups, and everything constrained to them with an offset, on
  every rig. What it does and does not do is written down instead, and the parameter wants a
  decision rather than a quiet change.
- **A component built with no parent raised ``AttributeError``.** ``create`` asks the parent what
  type it is to decide whether to put the groups under the rig's own, and ``FRAGNode.create`` is
  happy to be given nothing.
- **``serialize_component`` could not run.** It called ``get_point_attach_component``,
  ``get_orient_attach_component`` and ``get_scale_attach_component``, and no class anywhere in the
  pipeline has any of the three, so any component with a constraint on its ``NO_TOUCH`` group raised
  ``AttributeError``. It also reset the entry it was about to fill one line above the
  ``if not ...`` that was meant to keep the first of several constraints, so that guard could never
  fire. Nothing called it and nothing reads the shape it produced - the only serializer the pipeline
  uses is ``MultiConstraint``'s, which stands on its own - so it is gone rather than propped up with
  three methods invented to satisfy it.
- ``childAttachments`` is added to every component and **nothing in the pipeline has ever connected
  anything to it**, so :attr:`attached_children` has always answered an empty list. The attribute
  and its reader stay, because a rig built without it would differ from every rig so far for no
  gain, but what they are is written down rather than left to be discovered.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The class name of the node at the top of a rig. Compared as a string rather than with
#: ``isinstance`` because ``frag_rig`` is built on this module and cannot be imported from it.
FRAG_RIG_TYPE = 'FRAGRig'

#: The group holding everything about a component that is not for the animator to touch.
NO_TOUCH_ATTR = 'noTouch'

#: The group holding a component's controls. Added by ``KeyableComponent``; a component with no
#: controls has no such group, which is why anything here that wants it asks first.
FLAG_GROUP_ATTR = 'flagGroup'

#: The components hung off this one. Nothing in the pipeline writes this; see the module docstring.
CHILD_ATTACHMENTS_ATTR = 'childAttachments'

#: The components and the objects this one is attached to, for position and for orientation.
POINT_PARENT_ATTACHMENTS_ATTR = 'pointParentAttachments'
POINT_PARENT_OBJECTS_ATTR = 'pointParentObjects'
ORIENT_PARENT_ATTACHMENTS_ATTR = 'orientParentAttachments'
ORIENT_PARENT_OBJECTS_ATTR = 'orientParentObjects'

#: All four of the above, which is what an attachment clears before writing itself.
ATTACHMENT_ATTRS = (POINT_PARENT_ATTACHMENTS_ATTR, POINT_PARENT_OBJECTS_ATTR,
                    ORIENT_PARENT_ATTACHMENTS_ATTR, ORIENT_PARENT_OBJECTS_ATTR)

class RigComponent(frag_base.FRAGNode):
    """
    One piece of a rig: its ``NO_TOUCH`` group, its markup, and what it is attached to.

    Every component is one of these, including the ones with no controls - a twist helper, an
    attachment point. :class:`KeyableComponent` is the one that adds controls on top.
    """

    @staticmethod
    def create(frag_parent, frag_type, version, side, region, align_component=None):
        """
        Build a component's metadata node and its ``NO_TOUCH`` group.

        :param FRAGNode frag_parent: The rig, or the component, this one hangs off. None builds a
            component with nothing above it, which leaves its group at the scene root.
        :param str frag_type: The name of the class being built.
        :param float version: The version of that class.
        :param str side: Which side of the body it is on, for the node and group names.
        :param str region: What part of the body it is, for the same.
        :param pm.nt.Transform align_component: Something to snap the ``NO_TOUCH`` group to before
            its transform is frozen. The freeze undoes the snap - see the module docstring - so this
            only leaves the group's pivots where that object was.
        :return: The component.
        :rtype: RigComponent
        """

        node = frag_base.FRAGNode.create(frag_parent, frag_type, version)
        pm.rename(node.pynode, '{0}_{1}_{2}'.format(naming.get_basename(node.pynode), side, region))

        no_touch_group = pm.group(empty=True, n='NO_TOUCH_{0}_{1}'.format(side, region))
        if align_component:
            pm.delete(pm.parentConstraint(pm.PyNode(align_component), no_touch_group,
                                          w=True, mo=False))
        # Frozen, hidden and locked. Note that the freeze puts an empty transform's matrix back to
        # identity, so it undoes the snap above and leaves only the pivots behind it.

        pm.makeIdentity(no_touch_group, apply=True, t=True, r=True, s=True)
        no_touch_group.visibility.set(0)
        attr_utils.lock_all_keyable_attrs(no_touch_group)

        # None is a component with nothing above it, which FRAGNode.create allows; asking it what
        # type it is raised.
        if frag_parent is not None and frag_parent.get_type() == FRAG_RIG_TYPE:
            no_touch_group.setParent(frag_parent.pynode.attr('doNotTouch').get())

        node.connect_node(no_touch_group, NO_TOUCH_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.side = side
        node.region = region

        # Multi message attributes rather than a compound: a compound would let something be stored
        # alongside each link, and nothing needs to be.
        for attr_name in (CHILD_ATTACHMENTS_ATTR,) + ATTACHMENT_ATTRS:
            node.pynode.addAttr(attr_name, at='message', m=True)

        return node

    # ----------------------------------------------------------------------------------- #
    # the groups
    # ----------------------------------------------------------------------------------- #
    @property
    def no_touch_grp(self):
        """
        :return: The group holding everything about this component that is not for the animator.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(NO_TOUCH_ATTR).get()

    def remove(self):
        """
        Take this component out of the rig: its group, everything in it, and its node.

        ``KeyableComponent`` overrides this to take its control group as well. There was no way to
        remove a component with no controls at all before, which is what a component that cannot
        finish building needs in order not to leave itself behind.
        """

        pm.delete([self.no_touch_grp, self.pynode])

    def get_attachment_groups(self):
        """
        The groups an attachment constrains, which is however many of the two this component has.

        :return: The control group first when there is one, then the ``NO_TOUCH`` group.
        :rtype: list(pm.nt.Transform)
        """

        groups = []
        for attr_name in (FLAG_GROUP_ATTR, NO_TOUCH_ATTR):
            if not self.has_attribute(attr_name):
                continue
            group_node = self.pynode.attr(attr_name).get()
            if group_node is not None:
                groups.append(group_node)
        return groups

    # ----------------------------------------------------------------------------------- #
    # attaching
    # ----------------------------------------------------------------------------------- #
    def _connect_parent(self, node, attach_attr):
        """
        Wire a node into the next free slot of a multi message attribute.

        :param node: What to record, as a ``FRAGNode``, a ``PyNode`` or a name.
        :param pm.Attribute attach_attr: The multi message attribute to record it on.
        """

        next_index = 0
        for existing in attach_attr.iterDescendants(1):
            next_index = existing.index() + 1
        frag_base.as_pynode(node).message >> attach_attr[next_index]

    def attach_component(self, parent_component_list, parent_object_list, point=True, orient=True):
        """
        Hang this component off some objects, and remember what it was hung off.

        Position and orientation are constrained separately, so a component can follow one and not
        the other. With both asked for that is two constraints on each group where one would do; it
        is left that way because every rig built so far has them.

        :param parent_component_list: The components this one now hangs off, as a list or one on its
            own. Recorded rather than used: what the constraints are made against is the objects.
        :param parent_object_list: The objects to constrain to, as a list or one on its own.
        :param bool point: Follow their position.
        :param bool orient: Follow their orientation.
        """

        if not parent_object_list or not parent_component_list or not (point or orient):
            logger.debug('%s was asked to attach to nothing, or to attach neither position nor '
                         'orientation, so it was left as it was.', self.pynode)
            return

        if not isinstance(parent_object_list, list):
            parent_object_list = [parent_object_list]
        if not isinstance(parent_component_list, list):
            parent_component_list = [parent_component_list]

        # However many of the two groups this component has: RigComponent is also the base for
        # components with no controls, and reading flagGroup on one of those raised.
        attachment_groups = self.get_attachment_groups()
        no_touch_group = self.no_touch_grp

        for group_node in attachment_groups:
            pm.delete(pm.listRelatives(group_node, type=pm.nt.Constraint))

        locked_attrs = attr_utils.TRANSLATION_ATTRS + attr_utils.ROTATION_ATTRS
        attr_utils.set_attr_state(no_touch_group, False, locked_attrs)

        for group_node in attachment_groups:
            if point:
                constraint.parent_constraint_safe(parent_object_list, group_node, mo=1,
                                                  skip_rotate_attrs=['x', 'y', 'z'])
            if orient:
                constraint.parent_constraint_safe(parent_object_list, group_node, mo=1,
                                                  skip_translate_attrs=['x', 'y', 'z'])

        # All four, not just the two component lists: leaving the object lists alone meant they grew
        # every time a component was reattached, and they are what a rebuild reads.
        for attr_name in ATTACHMENT_ATTRS:
            self.pynode.attr(attr_name).disconnect()

        for node in parent_component_list:
            if point:
                self._connect_parent(node, self.pynode.attr(POINT_PARENT_ATTACHMENTS_ATTR))
            if orient:
                self._connect_parent(node, self.pynode.attr(ORIENT_PARENT_ATTACHMENTS_ATTR))

        for node in parent_object_list:
            if point:
                self._connect_parent(node, self.pynode.attr(POINT_PARENT_OBJECTS_ATTR))
            if orient:
                self._connect_parent(node, self.pynode.attr(ORIENT_PARENT_OBJECTS_ATTR))

        attr_utils.set_attr_state(no_touch_group, True, locked_attrs)

    # ----------------------------------------------------------------------------------- #
    # what it is attached to
    # ----------------------------------------------------------------------------------- #
    def _attached_components(self, attr_name):
        """
        The components recorded on one of the attachment attributes.

        :param str attr_name: Which attribute to read.
        :return: The components, wrapped. One that cannot be wrapped is reported and left out.
        :rtype: list(FRAGNode)
        """

        wrapped = [frag_base.wrap_frag_node(node)
                   for node in self.pynode.attr(attr_name).get()]
        return [node for node in wrapped if node is not None]

    @property
    def attached_children(self):
        """
        :return: The components hung off this one. Always empty: nothing in the pipeline writes
            ``childAttachments``. See the module docstring.
        :rtype: list(FRAGNode)
        """

        return self._attached_components(CHILD_ATTACHMENTS_ATTR)

    @property
    def attached_frag_parents(self):
        """
        :return: The components this one follows the position of.
        :rtype: list(FRAGNode)
        """

        return self._attached_components(POINT_PARENT_ATTACHMENTS_ATTR)

    @property
    def orient_frag_parents(self):
        """
        :return: The components this one follows the orientation of.
        :rtype: list(FRAGNode)
        """

        return self._attached_components(ORIENT_PARENT_ATTACHMENTS_ATTR)

    @property
    def point_object_parents(self):
        """
        :return: The objects this one is constrained to for position.
        :rtype: list(pm.nt.Transform)
        """

        return self.pynode.attr(POINT_PARENT_OBJECTS_ATTR).get()

    @property
    def orient_object_parents(self):
        """
        :return: The objects this one is constrained to for orientation.
        :rtype: list(pm.nt.Transform)
        """

        return self.pynode.attr(ORIENT_PARENT_OBJECTS_ATTR).get()
