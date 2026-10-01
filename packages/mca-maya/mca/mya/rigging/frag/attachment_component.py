"""

Hanging one rig off another: a horse and its rider, a character and the prop in its hand.

A rig's controls all live under one group, so making a whole rig follow a node on another rig is a
matter of putting one more group above that one and constraining it. This is the node that records
that it was done - which rig was attached to what, and whether it followed in translation, rotation
or both - so it can be undone or rebuilt.

It records which *component* the attachment point belongs to rather than the node itself, because a
rebuild looks the point up again from the component; the node may not survive the rig being
rebuilt.

What was wrong before:

- **It built its own node and its build arguments before asking whether the thing it was attaching
  to exists**, so a target rig root with no ``FRAGRig`` under it left an ``AttachmentComponent``
  node and a ``buildKwargs`` block in the scene and handed the caller None. The question is asked
  first.
- **``side`` and ``region`` are taken, used to name the node, and never recorded on it.** Every
  other component in ``frag`` carries its side and region as markup, and the tools that walk a rig
  read them; this one is the only node in a rig named for a side it cannot be asked about. It
  carries them now.
- **The two attributes this component puts on the nodes it points at are spelled**
  ``attachementComponent`` **and** ``sourceAttachement``. Nothing reads either of them, and
  renaming them would make the attachment on every rig in the depot unreadable by this code, so
  they stay exactly as they are - with their own constants, named for what they are, and this note.
- ``t`` and ``r`` are undocumented short spellings of ``translate`` and ``rotate``, read out of
  ``**kwargs``, which silently win over the named parameters. The signature says so.
- ``connect_nodes`` was used for ``targetFlagsAll``, a single group, which makes a list attribute
  out of something there is one of.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import frag_rig
from mca.mya.utils import attr_utils
from mca.mya.utils import groups


logger = log.MCA_LOGGER

#: The suffix of the group this component inserts above the attached rig's controls.
ATTACHMENT_GROUP_SUFFIX = 'attachment_transform'

#: What the component keeps its pieces on.
TARGET_PARENT_ATTR = 'targetParent'
TARGET_FLAGS_ALL_ATTR = 'targetFlagsAll'
SOURCE_COMPONENT_ATTR = 'sourceComponent'

#: The attribute the inserted group carries, pointing back at the control group it was put above.
ATTACHMENT_TRANSFORM_ATTR = 'attachmentTransform'

#: The attributes this component puts on the two nodes it points at, so each can say which
#: attachment it belongs to. Both are misspelled - "attachement" - and are left that way: nothing
#: reads them, and correcting them would make the attachment on every rig already built unreadable.
LEGACY_TARGET_PARENT_ATTR = 'attachementComponent'
LEGACY_SOURCE_PARENT_ATTR = 'sourceAttachement'


class AttachmentComponent(frag_base.FRAGNode):
    """
    A record that one rig is following a node on another.
    """

    VERSION = 1

    @staticmethod
    def create(frag_parent, side, region, source_component, attachment_point, target_frag_root,
               translate=True, rotate=True, snap=True, **kwargs):
        """
        Attach a rig to a node on another rig.

        :param FRAGNode frag_parent: The rig this record belongs to - the one being followed.
        :param str side: Which side of the body the attachment point is on.
        :param str region: What part of the body it is.
        :param FRAGNode source_component: The component the attachment point belongs to. Recorded
            rather than the point itself, because a rebuild looks the point up again from it.
        :param pm.nt.Transform attachment_point: The node the other rig follows.
        :param target_frag_root: The rig root being attached, as a ``FRAGNode`` or a node.
        :param bool translate: Follow the point's position.
        :param bool rotate: Follow its rotation.
        :param bool snap: Move the attached rig onto the point. False keeps it where it is and holds
            the offset.
        :param dict kwargs: ``t`` and ``r`` are older spellings of ``translate`` and ``rotate``, and
            win over them when given - which is what the version before did silently.
        :return: The component, or None when the rig being attached has no ``FRAGRig`` in it.
        :rtype: AttachmentComponent or None
        """

        follow_translate = kwargs.get('t', translate)
        follow_rotate = kwargs.get('r', rotate)

        # Asked before anything is built. The version before made its node and wrote its build
        # arguments first, so this path left an orphan component in the scene.
        target_frag_root = frag_base.FRAGNode(target_frag_root)
        target_rigs = target_frag_root.get_frag_children(of_type=frag_rig.FRAGRig)
        if not target_rigs:
            logger.warning('%s has no rig under it, so there is nothing to attach.',
                           target_frag_root.pynode)
            return None
        target_flags_all = target_rigs[0].flags_all

        node = frag_base.FRAGNode.create(frag_parent, AttachmentComponent.__name__,
                                         version=AttachmentComponent.VERSION)
        node.pynode.rename('{0}_{1}_{2}'.format(AttachmentComponent.__name__, side, region))
        # Carried as markup, as on every other component in frag. The version before named the node
        # for a side and a region and then recorded neither.
        node.side = side
        node.region = region
        attr_utils.set_compound_attribute_groups(
            node.pynode, frag_base.BUILD_KWARGS_ATTR,
            {'translate': follow_translate, 'rotate': follow_rotate, 'snap': snap})

        # One more group above the attached rig's control group, which is what gets constrained -
        # so the rig's own groups are untouched and the attachment can be removed again.
        target_parent = groups.create_aligned_parent_group(
            target_flags_all, suffix=ATTACHMENT_GROUP_SUFFIX,
            attr_name=ATTACHMENT_TRANSFORM_ATTR, obj_attr=ATTACHMENT_TRANSFORM_ATTR,
            orient_obj=None)

        if follow_translate:
            pm.pointConstraint(attachment_point, target_parent, w=True, mo=not snap)
        if follow_rotate:
            pm.orientConstraint(attachment_point, target_parent, w=True, mo=not snap)

        node.connect_node(target_parent, TARGET_PARENT_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(target_flags_all, TARGET_FLAGS_ALL_ATTR,
                          parent_attr=LEGACY_TARGET_PARENT_ATTR)
        node.connect_node(source_component, SOURCE_COMPONENT_ATTR,
                          parent_attr=LEGACY_SOURCE_PARENT_ATTR)

        return node

    @property
    def target_parent(self):
        """
        :return: The group this component inserted, which is the thing being constrained.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(TARGET_PARENT_ATTR).get()

    @property
    def target_flags_all(self):
        """
        :return: The control group of the rig that is following.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(TARGET_FLAGS_ALL_ATTR).get()

    @property
    def source_component(self):
        """
        :return: The component the attachment point belongs to.
        :rtype: FRAGNode or None
        """

        return frag_base.wrap_frag_node(self.pynode.attr(SOURCE_COMPONENT_ATTR).get())

    def remove(self):
        """
        Let the attached rig go: delete the constraints and the group this component inserted, and
        then the component itself.

        The group is deleted rather than unparented, which puts the rig's control group back where
        it was in the hierarchy. There was no way to undo an attachment before.
        """

        target_parent = self.target_parent
        if target_parent:
            flags_all = self.target_flags_all
            if flags_all:
                flags_all.setParent(target_parent.getParent())
            pm.delete(target_parent)
        pm.delete(self.pynode)
