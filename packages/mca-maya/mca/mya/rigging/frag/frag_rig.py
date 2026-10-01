"""
The rig itself: the groups an animator sees, and what is known about all of them at once.

A rig's root says which asset it is; this node is the rig built on it. It makes the three groups
every rig has - ``<asset>_all`` at the top, ``DO_NOT_TOUCH`` for the machinery and ``flags_all`` for
the controls - parents the skeleton and the geometry under them, carries the rig's scale, and
answers the questions that are about the whole rig rather than one component: which controls it has,
which display layers, what colour each control is drawn.

What was wrong before:

- **Reading the rig's scale rebuilt part of the rig.** The ``rig_scale`` property, when the
attribute
  was not there, called ``_scale_components`` - which adds the attribute, wires it to the top group
  and calls ``set_scale()`` on every keyable component in the rig. A property read that changes the
  scene is the same fault ``chain_markup``'s getters had. Reading it answers the scale now, from the
  top group when the attribute is missing; :meth:`FRAGRig.add_rig_scale` is the thing that wires it,
  for a caller that means to.
- **A rig with util controls and no detail controls left its util controls on no layer at all.**
  ``create_display_layers`` puts them on the detail layer, inside the ``if detail_flags:`` that
  builds it. Every rig that has one and not the other has been missing them.
- **``list(set(...))`` in ``get_frag_rigs`` never removed a duplicate.** Two ``FRAGNode`` wrappers
  around one node were not equal to each other, so a set of them kept both; see ``frag_base``, where
  that is fixed. A root with no rig also put a ``None`` in the list.
- **``color_flags`` turned an override on for a side it had no colour for.** A control whose
component
  says ``top`` is not in the table, so ``overrideEnabled`` was set and ``overrideColor`` was not,
  leaving the control drawn in whatever index it already had. The side is reported now and the
  override is left alone.
- **``get_frag_rig`` raised on a node whose ``fragParent`` is connected to nothing**, and on a node
  that is not under a rig root - ``FRAGNode(None)`` gets as far as ``pm.PyNode(None)``, and
  ``.get_rig()`` was read off a root that might not be there.
- **``get_meshes`` reached into the skins group without checking there was one** and answered a
mixture
  of transforms and mesh shapes, because one half of it lists a group's descendants and the other
  asks for ``type='mesh'``. It answers transforms throughout now.
- ``create_display_layers`` and ``create_display_layers_for_cam`` were the same thirty lines twice
over,
  differing in what goes on the geometry layer and whether the control layer starts hidden. The six
  flag queries were the same two lines six times. ``addAttr(..., type='float')`` works - pymel takes
  ``type`` as a spelling of ``at`` - but the rest of the package says ``at``.

``get_flags`` finds every control in the rig's *namespace*, which is right for a referenced rig and
right for one rig in a scene. Two rigs sharing a namespace - two imported with no namespace, say -
will each answer the other's controls as well as their own, and there is nothing on a control that
says which rig it belongs to other than the component above it.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import display_layers
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import frag_root
from mca.mya.rigging.frag import keyable_component
from mca.mya.rigging.frag import skeletal_mesh
from mca.mya.utils import attr_utils
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The three groups every rig has, and the attributes pointing at them.
ALL_GROUP_SUFFIX = '_all'
ALL_ATTR = 'all'
DO_NOT_TOUCH_GROUP = 'DO_NOT_TOUCH'
DO_NOT_TOUCH_ATTR = 'doNotTouch'
FLAGS_ALL_GROUP = 'flags_all'
FLAGS_ALL_ATTR = 'flagsAll'

#: What the rig records about itself.
RIG_VERSION_ATTR = 'rigVersion'
RIG_TEMPLATE_ATTR = 'rigTemplate'
RIG_SCALE_ATTR = 'rigScale'

#: Maya's colour indices for a primary control, by the side of the body its component is on.
FLAG_COLOR_BY_SIDE = {'left': 6,     # blue
                      'right': 13,   # red
                      'center': 17,  # yellow
                      'front': 20,
                      'back': 19}

#: Maya's colour indices for the other kinds of control, which are coloured by kind rather than
# side.
SUB_FLAG_COLOR = 18
DETAIL_FLAG_COLOR = 9
CONTACT_FLAG_COLOR = 14
UTIL_FLAG_COLOR = 19


class FRAGRig(frag_base.FRAGNode):
    """
    One rig: its groups, its scale, and what is true of all its controls at once.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent):
        """
        Build the rig's node and the three groups everything in it hangs under.

        :param FRAGRoot frag_parent: The rig's root, which says which asset this is.
        :return: The rig.
        :rtype: FRAGRig
        :raises AttributeError: When the parent is not a rig root.
        """

        if not frag_parent.pynode.hasAttr(frag_base.IS_FRAG_ROOT_ATTR):
            raise AttributeError('{0} is not a FRAG root, so a rig cannot be built under '
                                 'it.'.format(frag_parent))

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(frag_parent, FRAGRig.__name__, FRAGRig.VERSION)

        asset_name = frag_parent.pynode.attr(frag_root.ASSET_NAME_ATTR).get()
        root_joint = frag_parent.pynode.attr(frag_root.ROOT_JOINT_ATTR).get()

        node.pynode.addAttr(ALL_ATTR, at='message')
        node.pynode.addAttr(DO_NOT_TOUCH_ATTR, at='message')
        node.pynode.addAttr(FLAGS_ALL_ATTR, at='message')
        node.pynode.addAttr(RIG_VERSION_ATTR, at='double', dv=0)
        node.pynode.addAttr(RIG_TEMPLATE_ATTR, dt='string')

        all_grp = pm.group(empty=True, name='{0}{1}'.format(asset_name, ALL_GROUP_SUFFIX))
        do_not_touch_grp = pm.group(empty=True, name=DO_NOT_TOUCH_GROUP)
        flags_all_grp = pm.group(empty=True, name=FLAGS_ALL_GROUP)

        node.connect_node(all_grp, ALL_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(do_not_touch_grp, DO_NOT_TOUCH_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_node(flags_all_grp, FLAGS_ALL_ATTR, frag_base.FRAG_PARENT_ATTR)

        node.add_rig_scale()
        pm.parent([do_not_touch_grp, flags_all_grp, root_joint], all_grp)

        skeletal_mesh_node = frag_parent.get_skeletal_mesh()
        if skeletal_mesh_node:
            skins_grp = skeletal_mesh_node.get_grp_skins()
            if skins_grp:
                skins_grp.setParent(all_grp)

            blendshape_grp = skeletal_mesh_node.get_grp_blendshapes()
            if blendshape_grp:
                blendshape_grp.setParent(all_grp)
                # A rig with no blendshapes has no use for the group; what is left behind is the
                # attribute pointing at nothing, which is what get_grp_blendshapes then answers.
                if not blendshape_grp.getChildren():
                    pm.delete(blendshape_grp)

        return node

    # ----------------------------------------------------------------------------------- #
    # the groups
    # ----------------------------------------------------------------------------------- #
    @property
    def all_grp(self):
        """
        :return: The group at the top of the rig.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(ALL_ATTR).get()

    @property
    def do_not_touch(self):
        """
        :return: The group holding everything in the rig that is not for an animator.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(DO_NOT_TOUCH_ATTR).get()

    @property
    def flags_all(self):
        """
        :return: The group holding every control group in the rig.
        :rtype: pm.nt.Transform
        """

        return self.pynode.attr(FLAGS_ALL_ATTR).get()

    @property
    def rig_template(self):
        """
        :return: The name of the template class that built this rig.
        :rtype: str
        """

        return self.pynode.attr(RIG_TEMPLATE_ATTR).get()

    def get_root(self):
        """
        :return: The rig's root.
        :rtype: FRAGRoot
        """

        return self.get_frag_parent()

    # ----------------------------------------------------------------------------------- #
    # scale
    # ----------------------------------------------------------------------------------- #
    def add_rig_scale(self):
        """
        Wire the rig's scale, and tell every component that cares to wire its own.

        A rig built before the scale existed has none, which is what this is for. It used to happen
        inside a read of :attr:`rig_scale`, so asking a rig how big it was rewired it.

        :return: Whether anything was wired, which is to say whether the rig was missing it.
        :rtype: bool
        """

        if self.has_attribute(RIG_SCALE_ATTR):
            return False

        self.pynode.addAttr(RIG_SCALE_ATTR, at='float', dv=1.0)
        self.all_grp.scaleX >> self.pynode.attr(RIG_SCALE_ATTR)
        for rig_component in self.get_frag_children(of_type=keyable_component.KeyableComponent):
            rig_component.set_scale()
        return True

    @property
    def rig_scale(self):
        """
        :return: How big the rig is drawn, which is the scale of its top group. Read off the group
            itself on a rig built before the attribute existed - reading this used to add it.
        :rtype: float
        """

        if not self.has_attribute(RIG_SCALE_ATTR):
            return self.all_grp.scaleX.get()
        return self.pynode.attr(RIG_SCALE_ATTR).get()

    @rig_scale.setter
    def rig_scale(self, value):
        """
        :param float value: How big to draw the rig. Anything that is not a number is ignored.
        """

        if not isinstance(value, (int, float)):
            logger.warning('A rig scale is a number; %s is a %s.', value, type(value).__name__)
            return
        for attr_name in attr_utils.SCALE_ATTRS:
            self.all_grp.attr(attr_name).set(value)

    # ----------------------------------------------------------------------------------- #
    # the controls
    # ----------------------------------------------------------------------------------- #
    def get_flags(self):
        """
        Every control in the rig's namespace.

        :return: The controls. See the module docstring on what the namespace does and does not
            separate.
        :rtype: list(frag_flag.Flag)
        """

        pattern = '{0}*.{1}'.format(self.pynode.namespace(), frag_flag.IS_FLAG_ATTR)
        return [frag_flag.Flag(node) for node in pm.ls(pattern, objectsOnly=True)]

    def _get_flags_marked(self, marker_attr):
        """
        :param str marker_attr: Which of a control's kind markers to keep to.
        :return: The controls carrying it.
        :rtype: list(frag_flag.Flag)
        """

        return [flag_node for flag_node in self.get_flags()
                if flag_node.node.attr(marker_attr).get()]

    def get_primary_flags(self):
        """
        :return: The controls an animator works with first: everything that is not a detail, contact
            or utility control. A sub control is one of these as well as a sub.
        :rtype: list(frag_flag.Flag)
        """

        return [flag_node for flag_node in self.get_flags()
                if not flag_node.node.isDetail.get()
                and not flag_node.node.isContact.get()
                and not flag_node.node.isUtil.get()]

    def get_sub_flags(self):
        """
        :return: The controls marked as subs.
        :rtype: list(frag_flag.Flag)
        """

        return self._get_flags_marked('isSub')

    def get_detail_flags(self):
        """
        :return: The controls marked as detail controls.
        :rtype: list(frag_flag.Flag)
        """

        return self._get_flags_marked('isDetail')

    def get_contact_flags(self):
        """
        :return: The controls marked as contact controls.
        :rtype: list(frag_flag.Flag)
        """

        return self._get_flags_marked('isContact')

    def get_util_flags(self):
        """
        :return: The controls marked as utility controls.
        :rtype: list(frag_flag.Flag)
        """

        return self._get_flags_marked('isUtil')

    # ----------------------------------------------------------------------------------- #
    # the geometry
    # ----------------------------------------------------------------------------------- #
    def get_meshes(self):
        """
        Every mesh the rig drives: what is under the skins group, what is parented into the
        skeleton, and the shapes that drive a face.

        :return: The transforms holding them.
        :rtype: list(pm.nt.Transform)
        """

        meshes = []
        for group_node in (skeletal_mesh.get_group_skins(self.pynode),
                           skeletal_mesh.get_group_blendshapes(self.pynode)):
            if group_node is None:
                continue
            meshes += [mesh_shape.getParent() for mesh_shape
                       in group_node.listRelatives(allDescendents=True, type='mesh')]

        root_joint = frag_root.get_root_joint(self.pynode)
        if root_joint is not None:
            meshes += [mesh_shape.getParent() for mesh_shape
                       in (pm.listRelatives(root_joint, allDescendents=True, type='mesh') or [])]

        # Transforms, not a mixture of transforms and shapes, and each one once.
        return list({mesh_transform for mesh_transform in meshes if mesh_transform is not None})

    # ----------------------------------------------------------------------------------- #
    # finishing a rig
    # ----------------------------------------------------------------------------------- #
    def create_display_layers(self):
        """
        Build the rig's display layers: the skeleton referenced and hidden, the geometry referenced,
        the controls on their own layer, and the contact and detail controls hidden.

        :return: The node owning them.
        :rtype: display_layers.DisplayLayers
        """

        return self._create_display_layers(self.get_meshes(), hide_flags_layer=False)

    def create_display_layers_for_cam(self, cam):
        """
        The same layers as :meth:`create_display_layers`, for a camera rig: the camera takes the
        geometry's place, and the control layer starts hidden.

        A cinematic camera rig is animated through the per-shot cameras, so an animator should be
        moving the shot camera rather than this rig's controls - but the layer is there to be turned
        back on by anyone who does need to touch the rig itself.

        :param pm.nt.Transform cam: The camera this rig drives.
        :return: The node owning the layers.
        :rtype: display_layers.DisplayLayers
        """

        return self._create_display_layers([cam], hide_flags_layer=True)

    def _create_display_layers(self, skin_layer_objects, hide_flags_layer):
        """
        The body both of the above share.

        :param list skin_layer_objects: What goes on the geometry layer.
        :param bool hide_flags_layer: Whether the layer holding the primary controls starts hidden.
        :return: The node owning the layers.
        :rtype: display_layers.DisplayLayers
        """

        display_node = display_layers.DisplayLayers.create(self)

        root_joint = frag_root.get_root_joint(self.pynode)
        joints = []
        if root_joint is not None:
            joints = (pm.listRelatives(root_joint, allDescendents=True, pa=True, type='joint')
                      or []) + [root_joint]

        display_node.add_objects(joints, display_layers.SKEL_LYR)
        display_node.add_objects(skin_layer_objects, display_layers.SKIN_LYR)
        display_node.add_objects(self.get_primary_flags(), display_layers.FLAGS_LYR)

        display_node.set_layer_to_reference(display_layers.SKEL_LYR)
        display_node.hide_layer(display_layers.SKEL_LYR)
        display_node.set_layer_to_reference(display_layers.SKIN_LYR)
        if hide_flags_layer:
            display_node.hide_layer(display_layers.FLAGS_LYR)

        contact_flags = self.get_contact_flags()
        if contact_flags:
            display_node.add_objects(contact_flags, display_layers.FLAGS_CONTACT_LYR)
            display_node.hide_layer(display_layers.FLAGS_CONTACT_LYR)

        # Detail and utility controls share a layer, and either on its own is enough to build it.
        # The version before added the utility controls inside the `if` that asked about the detail
        # ones, so a rig with utility controls and no detail controls left them on no layer at all.
        hidden_flags = self.get_detail_flags() + self.get_util_flags()
        if hidden_flags:
            display_node.add_objects(hidden_flags, display_layers.FLAGS_DETAIL_LYR)
            display_node.hide_layer(display_layers.FLAGS_DETAIL_LYR)

        return display_node

    def finalize_rig(self, path=None):
        """
        Finish a rig off: build its display layers, put the artist-authored control shapes on, and
        colour everything.

        :param str path: The folder holding the rig's control shapes. None leaves the placeholder
            shapes as they are.
        """

        self.create_display_layers()
        if path:
            frag_flag.swap_flags(self.get_flags(), path)
        self.color_flags()

    def color_flags(self):
        """
        Colour every control: the primary ones by the side of the body their component is on, and
        the rest by what kind of control they are.

        The order matters where a control is more than one kind of thing: a sub control is a primary
        control too, so it takes the side colour first and the sub colour over it.
        """

        for flag_node in self.get_primary_flags():
            self._color_primary_flag(flag_node)

        for flag_list, color_index in ((self.get_sub_flags(), SUB_FLAG_COLOR),
                                       (self.get_detail_flags(), DETAIL_FLAG_COLOR),
                                       (self.get_contact_flags(), CONTACT_FLAG_COLOR),
                                       (self.get_util_flags(), UTIL_FLAG_COLOR)):
            shapes = lists.flatten_list([flag_node.node.getShapes() for flag_node in flag_list])
            for shape_node in shapes:
                shape_node.overrideEnabled.set(1)
                shape_node.overrideColor.set(color_index)

    def _color_primary_flag(self, flag_node):
        """
        Colour one primary control by the side of the body its component is on.

        The component's markup rather than the joint's: a control built on a joint with no side, or
        the wrong one, should still be the colour of the limb it drives.

        :param flag_node: The control.
        """

        if not flag_node.node.hasAttr(frag_base.FRAG_PARENT_ATTR):
            return
        rig_component = flag_node.node.attr(frag_base.FRAG_PARENT_ATTR).get()
        if not rig_component:
            return

        wrapped_component = frag_base.wrap_frag_node(rig_component)
        if wrapped_component is None or not wrapped_component.side:
            return

        color_index = FLAG_COLOR_BY_SIDE.get(wrapped_component.side)
        if color_index is None:
            # Turning the override on without a colour to put in it leaves the control drawn in
            # whatever index it already had, which is what this used to do.
            logger.warning('%s is on the %s side, which has no colour, so %s was left as it was.',
                           wrapped_component.pynode, wrapped_component.side, flag_node)
            return

        for shape_node in flag_node.node.getShapes():
            shape_node.overrideEnabled.set(1)
            shape_node.overrideColor.set(color_index)


def get_frag_rig(node):
    """
    The rig something belongs to.

    :param node: Anything in a rig: its root, one of its metadata nodes, or any node in its
    hierarchy. :return: The rig, or None when there is not one to find.
    :rtype: FRAGRig or None
    """

    node = frag_base.as_pynode(node)

    if frag_root.is_frag_root(node):
        return frag_base.FRAGNode(node).get_rig()

    if node.hasAttr(frag_base.FRAG_PARENT_ATTR):
        frag_parent = node.attr(frag_base.FRAG_PARENT_ATTR).get()
        if frag_parent is None:
            logger.warning('%s has a %s attribute with nothing on the end of it.',
                           node, frag_base.FRAG_PARENT_ATTR)
            return None
        root_node = frag_root.get_frag_root(frag_parent)
        return root_node.get_rig() if root_node else None

    # A plain node in the hierarchy: climb to the top group, which knows which rig it belongs to.
    all_grp = dag.get_absolute_parent(node)
    if all_grp is not None and all_grp.hasAttr(frag_base.FRAG_PARENT_ATTR):
        return frag_base.wrap_frag_node(all_grp.attr(frag_base.FRAG_PARENT_ATTR).get())

    logger.warning('Nothing above %s connects it to a FRAG rig.', node)
    return None


def get_frag_rigs():
    """
    Every rig in the scene.

    :return: The rigs, without repeats. A root that has no rig built under it yet is left out - the
        version before put a None in the list for it.
    :rtype: list(FRAGRig)
    """

    rigs = []
    for root_node in frag_root.get_all_frag_roots():
        rig_node = root_node.get_rig()
        if rig_node is not None and rig_node not in rigs:
            rigs.append(rig_node)
    return rigs
