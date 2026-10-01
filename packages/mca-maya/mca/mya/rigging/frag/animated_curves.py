"""
Animation taken off a rig and kept on a node, so it can be put back onto another one.

An animator's work is a set of animation curves hanging off a rig's controls. Lift those curves onto
a node of their own and you have something that can travel: saved to a file as a clip, carried on a
skeleton while the rig around it is rebuilt, or handed to a different character altogether. That is
what this is - one compound attribute per object, holding the curves that were on it, named so they
can be found again.

It is a fast path and it knows it: a clip that has to survive every possible scene is a much bigger
piece of machinery than this.

What was wrong before:

- **Restoring animation could put curves on the wrong channels.** The curves and the attributes to
  put them on were worked out as two separately sorted lists and then paired *by position*. They
  line up only while both are the same length - and the curve list leaves out anything stored
  without a curve while the attribute list does not, so one such gap shifted everything after it by
  one. An arm's translateY landed on its translateZ, quietly. There is a mapping from node attribute
  to object attribute right there in the same function, so the two are paired by name now, which
  cannot drift. ``get_stored_curve_pairs`` had the same fault and the same fix; both go through one
  lookup.
- **A whole-number start frame worked and a fractional one did nothing.** Three places tested
  ``isinstance(start_time, int)`` before shifting the animation, which is False for ``1001.0`` - and
  the docstrings all said ``float``. Shifting a clip to a frame typed into a tool, which hands over
  a float, silently did not move it.
- **The shift compounded across an object's attributes.** ``start_time`` was turned into an offset
  *inside* the loop over the attributes and assigned back over itself, so the second attribute had
  its offset worked out from the first attribute's offset, and so on. The offset is worked out once
  now, before anything moves.
- **The stored start frame stayed at 0 for any animation that starts at or after frame 0.**
  ``startFrame`` begins at 0 and was only ever lowered - ``if key_time[0] < startFrame.get()`` - so
  an animation on frames 10 to 20 was recorded as starting at 0. Everything that shifts a clip to a
  new start frame works out the distance against that number, so every such clip landed in the wrong
  place by however far the animation began from zero. The first curve stored now sets the range and
  the rest widen it, which is tracked by a flag on the node so an old node picks it up too.
- **Storing animation onto a skeleton in a namespace renamed the node to nonsense.** The node was
  moved by ``str(node).replace(old_namespace, new_namespace)``, and when the node is in the root
  namespace the old namespace is the empty string - which ``str.replace`` inserts the new one
  *between every character* of. A node called ``AnimatedCurvesComponent`` became
  ``hero:Ahero:nhero:ihero:m...``. The name is built rather than patched now.
- **``restore_from_anim_curves``' shift argument is ``time_offset``, not ``start_time``** - the one
  rewiring note this module owed from the animation port. It was being passed by keyword, so the
  call raised ``TypeError`` as soon as a shift was asked for.
- **Restoring the first attribute of an object disconnected every animation layer the node held**,
so
  the attributes after it had none to find. That disconnection belongs after the object is done, not
  inside the loop over its attributes.
- ``_correct_attribute_names`` found the object's name anywhere in an attribute's name rather than
at
  the front of it, and then replaced it everywhere rather than once; an attribute it did not find
  the name in at all was dropped without a word. ``_get_compound_attributes`` answered None where
  its docstring promised a list. The warning for a node not connected to a skeleton said the
  skeleton had no node connected to it, which is the opposite way round. ``flag_count`` and
  ``obj_count`` held objects rather than counts.
"""

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.animation import anim_curves
from mca.mya.animation import anim_layers
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils
from mca.mya.utils import namespace
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: What ties this node to the skeleton carrying it, on both of them.
ANIMATED_CURVE_DATA_ATTR = 'animatedCurveData'

#: The animation layers the stored animation came through.
ANIMATION_LAYERS_ATTR = 'animationLayers'

#: What a layer carries to say it was one of the originals, rather than one made while storing.
ORIGINAL_ANIM_LAYER_ATTR = 'original_anim_layer'

#: The range the stored animation covers, and whether anything has been stored to set it from. The
#: flag is what tells a first store from a later one: the two frames start at zero, which is a real
#: frame, so there is no value either of them could hold that means "nothing yet".
START_FRAME_ATTR = 'startFrame'
END_FRAME_ATTR = 'endFrame'
FRAME_RANGE_SET_ATTR = 'hasStoredFrameRange'

#: The child of an object's compound attribute holding which component the object belonged to. It is
#: not an attribute name, so the restore has to know not to look for it on the object.
COMPONENT_KEY = 'component'


class AnimatedCurvesComponent(frag_base.FRAGNode):
    """
    Animation lifted off a rig's objects and kept where it can be moved about.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent):
        """
        Build the node.

        :param FRAGNode frag_parent: The rig the animation is being taken from.
        :return: The node.
        :rtype: AnimatedCurvesComponent
        """

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(frag_parent,
                                        frag_type=AnimatedCurvesComponent.__name__,
                                        version=AnimatedCurvesComponent.VERSION)

        node.pynode.addAttr(ANIMATED_CURVE_DATA_ATTR, at='message')
        node.pynode.addAttr(ANIMATION_LAYERS_ATTR, dt='string')
        node.pynode.addAttr(START_FRAME_ATTR, at='float', dv=0.0)
        node.pynode.addAttr(END_FRAME_ATTR, at='float', dv=0.0)
        node.pynode.addAttr(FRAME_RANGE_SET_ATTR, at='bool', dv=False)

        return node

    # ----------------------------------------------------------------------------------- #
    # what is stored, and for what
    # ----------------------------------------------------------------------------------- #
    def _get_compound_attributes(self, obj):
        """
        The children of the compound attribute holding one object's stored animation.

        :param pm.nt.Transform obj: The object.
        :return: The children's names, without the compound itself or the hidden ones. Empty when
            nothing is stored for the object - the version before answered None.
        :rtype: list(str)
        """

        obj_name = naming.get_basename(obj)
        if not self.pynode.hasAttr(obj_name):
            return []

        compound_attr = self.pynode.attr(obj_name)
        children = [str(attr_name) for attr_name in pm.listAttr(compound_attr)
                    if not str(attr_name).endswith(frag_base.HIDDEN_KWARG_SUFFIX)]
        return [attr_name for attr_name in children if attr_name != obj_name]

    def _correct_attribute_names(self, obj_name, attributes):
        """
        What each stored child is called on the object it came from.

        A compound's children are named after the object as well as the attribute - every attribute
        on a node has to be unique on that node - so ``f_nose_null_translateX`` is ``translateX`` on
        ``f_nose_null``.

        :param str obj_name: The object's name.
        :param list(str) attributes: The compound's children.
        :return: ``{child's name: the attribute's name on the object}``.
        :rtype: dict
        """

        prefix = '{0}_'.format(obj_name)
        attribute_names = {}
        for attr_name in attributes:
            # At the front, and once. A substring test let through a child that merely mentioned the
            # object's name, and a bare replace took the name out wherever it appeared.
            if not attr_name.startswith(prefix):
                logger.debug('%s is stored for %s but is not named after it, so there is no '
                             'attribute on it to put back.', attr_name, obj_name)
                continue
            attribute_names[attr_name] = attr_name[len(prefix):]
        return attribute_names

    def _stored_curves(self, obj):
        """
        What is stored for an object, paired to the attributes it goes back on.

        This is the one lookup the restore and the read-only version of it both go through, and the
        pairing is by name. Two separately sorted lists paired by position is what put an arm's
        translateY onto its translateZ when anything was missing from either.

        :param pm.nt.Transform obj: The object.
        :return: ``[(object attribute, the node's attribute holding it, what is on that
        attribute)]``,
            in the order the compound holds them. An attribute the object does not have, or that has
            nothing stored on it, is left out.
        :rtype: list(tuple)
        """

        sub_attr_names = self._correct_attribute_names(naming.get_basename(obj),
                                                       self._get_compound_attributes(obj))

        stored = []
        for node_attr_name, obj_attr_name in sorted(sub_attr_names.items()):
            if obj_attr_name == COMPONENT_KEY or not obj.hasAttr(obj_attr_name):
                continue
            node_attr = self.pynode.attr(node_attr_name)
            connections = node_attr.listConnections(source=True, destination=False)
            if not connections:
                continue
            stored_node = lists.get_first_in_list(list(set(connections)))
            if not isinstance(stored_node, (pm.nt.AnimCurve, pm.nt.AnimBlendNodeBase)):
                continue
            stored.append((obj.attr(obj_attr_name), node_attr, stored_node))
        return stored

    def get_attributes_with_curves(self, obj, sub_attr_names=None):
        """
        The node's own attributes holding animation for an object.

        :param pm.nt.Transform obj: The object.
        :param dict sub_attr_names: Taken for compatibility with existing callers and unused; the
            mapping is worked out from the node either way.
        :return: The attributes.
        :rtype: list(pm.Attribute)
        """

        return [node_attr for _, node_attr, _ in self._stored_curves(obj)]

    def get_stored_curve_pairs(self, obj):
        """
        An object's attributes paired with the curves stored for them, without consuming them.

        The same lookup a restore does, stopped one step short: it hands back the pairs instead of
        reconnecting them, for a caller that wants to paste keys on top of what is already there and
        keep the stored curve where it is so the clip can be applied again.

        Only plain curves. An attribute stored through animation layers holds a blend node, which
        has no keys of its own to copy; those are left out, and a caller that cares can ask
        :meth:`get_attributes_with_curves` or do a full restore.

        :param pm.nt.Transform obj: The object.
        :return: ``[(object attribute, curve)]``, empty when nothing is stored for it.
        :rtype: list(tuple)
        """

        return [(obj_attr, stored_node) for obj_attr, _, stored_node in self._stored_curves(obj)
                if isinstance(stored_node, pm.nt.AnimCurve)]

    # ----------------------------------------------------------------------------------- #
    # the frame range
    # ----------------------------------------------------------------------------------- #
    def _frame_range_is_set(self):
        """
        :return: Whether anything has been stored on this node to take a frame range from.
        :rtype: bool
        """

        if not self.pynode.hasAttr(FRAME_RANGE_SET_ATTR):
            return False
        return bool(self.pynode.attr(FRAME_RANGE_SET_ATTR).get())

    def _mark_frame_range_set(self):
        """
        Say that this node now has a frame range, adding the flag to a node built before it existed.
        """

        if not self.pynode.hasAttr(FRAME_RANGE_SET_ATTR):
            self.pynode.addAttr(FRAME_RANGE_SET_ATTR, at='bool', dv=False)
        self.pynode.attr(FRAME_RANGE_SET_ATTR).set(True)

    def set_start_frame(self, anim_curve, min_time_range=None):
        """
        Widen the stored range to take in a curve's first key.

        The first curve stored sets the range rather than lowering it. Both frames start at zero and
        zero is a real frame, so only lowering meant an animation on frames 10 to 20 was recorded as
        starting at 0 - and everything that shifts a clip to a new start works the distance out
        against that number.

        :param pm.nt.AnimCurve anim_curve: The curve.
        :param float min_time_range: The earliest frame the caller kept. A range recorded below it
        is
            taken as stale and replaced.
        :return: The curve's first key, or None when it has none.
        :rtype: float or None
        """

        key_times = pm.keyframe(anim_curve, query=True)
        if not key_times:
            return None

        stored_start = self.pynode.attr(START_FRAME_ATTR).get()
        if (not self._frame_range_is_set()
                or key_times[0] < stored_start
                or (min_time_range is not None and stored_start < min_time_range)):
            self.pynode.attr(START_FRAME_ATTR).set(key_times[0])
        self._mark_frame_range_set()
        return key_times[0]

    def set_end_frame(self, anim_curve):
        """
        Widen the stored range to take in a curve's last key.

        :param pm.nt.AnimCurve anim_curve: The curve.
        :return: The curve's last key, or None when it has none.
        :rtype: float or None
        """

        key_times = pm.keyframe(anim_curve, query=True)
        if not key_times:
            return None

        if not self._frame_range_is_set() or key_times[-1] > self.pynode.attr(END_FRAME_ATTR).get():
            self.pynode.attr(END_FRAME_ATTR).set(key_times[-1])
        self._mark_frame_range_set()
        return key_times[-1]

    def get_start_time_diff(self, start_time):
        """
        How far the stored animation has to move to begin on a given frame.

        :param float start_time: The frame it should begin on.
        :return: The distance, or None when it already begins there.
        :rtype: float or None
        """

        stored_start = self.pynode.attr(START_FRAME_ATTR).get()
        if float(stored_start) == float(start_time):
            logger.debug('The stored animation already starts at %s, so there is nothing to move.',
                         start_time)
            return None
        return start_time - stored_start

    # ----------------------------------------------------------------------------------- #
    # putting animation back
    # ----------------------------------------------------------------------------------- #
    def restore_curves_from_skeleton(self, flags,
                                     force_unlock=True,
                                     keep_curves=True,
                                     delete_old_curves=True,
                                     start_time=None):
        """
        Put animation this node is carrying on a skeleton back onto a rig's controls.

        :param flags: The controls to put it on, as a list or one on its own.
        :param bool force_unlock: Unlock and show an attribute before connecting to it.
        :param bool keep_curves: Work on duplicates, leaving this node's own curves where they are.
        :param bool delete_old_curves: Delete whatever is already animating the controls.
        :param float start_time: The frame the animation should begin on. None leaves it where it
        is. """

        if not self.is_connected_to_skeleton():
            logger.warning('%s is not connected to a skeleton, so there is no animation on one to '
                           'put back.', self.pynode)
            return

        if not isinstance(flags, list):
            flags = [flags]

        self.restore_all_animation_curves(obj_list=flags,
                                          force_unlock=force_unlock,
                                          keep_curves=keep_curves,
                                          delete_old_curves=delete_old_curves,
                                          start_time=start_time)

    def restore_all_animation_curves(self, obj_list,
                                     force_unlock=True,
                                     keep_curves=False,
                                     delete_old_curves=True,
                                     start_time=None):
        """
        Put the stored animation back onto a set of objects.

        :param obj_list: The objects, as a list or one on its own.
        :param bool force_unlock: Unlock and show an attribute before connecting to it.
        :param bool keep_curves: Work on duplicates, leaving this node's own curves where they are.
        :param bool delete_old_curves: Delete whatever is already animating the objects.
        :param float start_time: The frame the animation should begin on. None leaves it where it
        is. """

        if not isinstance(obj_list, list):
            obj_list = [obj_list]

        # Once, before anything moves. Working it out per attribute and assigning it back over the
        # frame it came from is what made each attribute's shift the previous one's shift again.
        time_offset = self._time_offset_for(start_time)

        for obj in obj_list:
            self._restore_object(obj,
                                 force_unlock=force_unlock,
                                 keep_curves=keep_curves,
                                 delete_old_curves=delete_old_curves,
                                 time_offset=time_offset)

        if _is_a_number(start_time) and start_time != self.pynode.attr(START_FRAME_ATTR).get():
            self.pynode.attr(START_FRAME_ATTR).set(start_time)

    def restore_animation_curves(self, obj,
                                 force_unlock=True,
                                 keep_curves=False,
                                 delete_old_curves=True,
                                 start_time=None):
        """
        Put the stored animation back onto one object.

        :param pm.nt.Transform obj: The object.
        :param bool force_unlock: Unlock and show an attribute before connecting to it.
        :param bool keep_curves: Work on a duplicate, leaving this node's own curve where it is.
        :param bool delete_old_curves: Delete whatever is already animating the object.
        :param float start_time: The frame the animation should begin on. None leaves it where it
        is. """

        self._restore_object(obj,
                             force_unlock=force_unlock,
                             keep_curves=keep_curves,
                             delete_old_curves=delete_old_curves,
                             time_offset=self._time_offset_for(start_time))

    def _time_offset_for(self, start_time):
        """
        How far to move the stored animation so it begins on a frame.

        :param start_time: The frame it should begin on, or None to leave it alone.
        :return: The distance, or None.
        :rtype: float or None
        """

        # Any number. isinstance(start_time, int) was the test, which is False for 1001.0 - and a
        # tool asking for a start frame hands over a float.
        if not _is_a_number(start_time):
            return None
        return self.get_start_time_diff(start_time=start_time)

    def _restore_object(self, obj, force_unlock, keep_curves, delete_old_curves, time_offset):
        """
        Put the stored animation back onto one object, with the shift already worked out.

        :param pm.nt.Transform obj: The object.
        :param bool force_unlock: Unlock and show an attribute before connecting to it.
        :param bool keep_curves: Work on a duplicate, leaving this node's own curve where it is.
        :param bool delete_old_curves: Delete whatever is already animating the object.
        :param time_offset: How far to move the animation, or None to leave it where it is.
        """

        stored = self._stored_curves(obj)
        if not stored:
            logger.debug('%s has nothing stored for it on %s.', obj, self.pynode)
            return

        if force_unlock:
            attr_utils.unlock_and_show_attrs([obj_attr for obj_attr, _, _ in stored])

        restored_through_layers = False
        for obj_attr, node_attr, stored_node in stored:
            if isinstance(stored_node, pm.nt.AnimCurve):
                # time_offset, not start_time: the animation port renamed it, because what it takes
                # is a distance rather than a frame.
                end_frame = anim_curves.restore_from_anim_curves(
                    anim_curve=stored_node,
                    object_attribute=obj_attr,
                    keep_curves=keep_curves,
                    delete_old_curves=delete_old_curves,
                    time_offset=time_offset)
                if not keep_curves:
                    pm.disconnectAttr(node_attr)
            else:
                end_frame = anim_layers.restore_for_anim_layers(
                    anim_blend=stored_node,
                    object_attribute=obj_attr,
                    keep_curves=keep_curves,
                    delete_old_curves=delete_old_curves,
                    time_offset=time_offset)
                restored_through_layers = True
                pm.disconnectAttr(node_attr)

            if end_frame and end_frame > self.pynode.attr(END_FRAME_ATTR).get():
                self.pynode.attr(END_FRAME_ATTR).set(end_frame)

        # Once the object is done, not inside the loop over its attributes: letting go of the layers
        # on the first attribute left every attribute after it with none to find.
        if restored_through_layers:
            for anim_layer in self.pynode.attr(ANIMATION_LAYERS_ATTR).listConnections():
                if anim_layer.hasAttr(ANIMATED_CURVE_DATA_ATTR):
                    pm.disconnectAttr(anim_layer.attr(ANIMATED_CURVE_DATA_ATTR))

    # ----------------------------------------------------------------------------------- #
    # taking animation off
    # ----------------------------------------------------------------------------------- #
    @ma_decorators.undo_decorator
    def store_curves_on_skeleton(self, skeleton_root, keep_animation=True):
        """
        Take a rig's animation off it and hang this node on a skeleton instead.

        The node is wired to the skeleton root both ways, so deleting the skeleton takes the
        animation with it rather than leaving it behind for the next thing that walks the scene.

        :param pm.nt.Joint skeleton_root: The skeleton to carry the animation.
        :param bool keep_animation: Work on duplicates, leaving the rig animated.
        """

        control_rig = frag_base.get_frag_parent(self)
        if not control_rig:
            raise RuntimeError('{0} is not connected to a rig, so there is no animation to '
                               'take off one.'.format(self.pynode))

        skeleton_root = pm.PyNode(skeleton_root)
        # Built rather than patched. str(node).replace(old, new) with the node in the root namespace
        # means replacing the empty string, which puts the new namespace between every character of
        # the name: `AnimatedCurvesComponent` became `hero:Ahero:nhero:i...`.
        pm.rename(self.pynode, '{0}{1}'.format(skeleton_root.namespace(),
                                               naming.get_basename(self.pynode)))

        stored_anything = False
        for flag_node in control_rig.get_flags():
            if self.store_animation_curves(flag_node, keep_animation):
                stored_anything = True

        if not stored_anything:
            logger.debug('%s had no animation on it, so there is nothing to carry.', control_rig)
            self.remove()
            return

        for node in (skeleton_root, self.pynode):
            if not node.hasAttr(ANIMATED_CURVE_DATA_ATTR):
                node.addAttr(ANIMATED_CURVE_DATA_ATTR, at='message')

        # Off the rig and onto the skeleton. Both ways round, so deleting the skeleton deletes this
        # node with it and the re-animator does not take it for something still in use.
        pm.disconnectAttr(self.pynode.attr(ANIMATED_CURVE_DATA_ATTR))
        pm.disconnectAttr(self.pynode.attr(frag_base.FRAG_PARENT_ATTR))
        self.pynode.attr(ANIMATED_CURVE_DATA_ATTR) >> skeleton_root.attr(ANIMATED_CURVE_DATA_ATTR)
        skeleton_root.attr(ANIMATED_CURVE_DATA_ATTR) >> self.pynode.attr(ANIMATED_CURVE_DATA_ATTR)

    @ma_decorators.undo_decorator
    def store_all_animation_curves(self, obj_list,
                                   keep_animation=True,
                                   min_time_range=None,
                                   max_time_range=None,
                                   merge_layers=False,
                                   start_time=None):
        """
        Take the animation off a set of objects.

        :param list obj_list: The objects.
        :param bool keep_animation: Work on duplicates, leaving the objects animated.
        :param float min_time_range: Drop keys before this frame.
        :param float max_time_range: Drop keys after this frame.
        :param bool merge_layers: Flatten the scene's animation layers first.
        :param float start_time: Move the stored animation so it begins on this frame.
        """

        stored_anything = False
        for obj in obj_list:
            if self.store_animation_curves(obj=obj,
                                           keep_animation=keep_animation,
                                           min_time_range=min_time_range,
                                           max_time_range=max_time_range,
                                           merge_layers=merge_layers,
                                           start_time=start_time):
                stored_anything = True

        if not stored_anything:
            logger.debug('None of those objects had animation on them, so %s has nothing to hold.',
                         self.pynode)
            self.remove()

    def store_animation_curves(self,
                               obj,
                               keep_animation=True,
                               min_time_range=None,
                               max_time_range=None,
                               merge_layers=False,
                               start_time=None):
        """
        Take the animation off one object and hold it on this node.

        :param pm.nt.Transform obj: The object.
        :param bool keep_animation: Work on duplicates, leaving the object animated.
        :param float min_time_range: Drop keys before this frame.
        :param float max_time_range: Drop keys after this frame.
        :param bool merge_layers: Flatten the scene's animation layers first.
        :param float start_time: Move the stored animation so it begins on this frame.
        :return: The object, or None when it had no animation to take.
        :rtype: pm.nt.Transform or None
        """

        obj_name = naming.get_basename(obj)
        component = frag_base.get_frag_parent(obj)

        attr_curves = anim_layers.store_object_animation(obj,
                                                         keep_animation=keep_animation,
                                                         min_time_range=min_time_range,
                                                         max_time_range=max_time_range,
                                                         merge_layers=merge_layers,
                                                         start_time=start_time)
        if not attr_curves:
            return None

        self._hold_animation_layers()

        # A plug name has a dot in it and an attribute name cannot, so the dot becomes an underscore
        # - which is what _correct_attribute_names undoes on the way back.
        stored_curves = {plug_name.replace('.', '_'): output_attr
                         for plug_name, output_attr in attr_curves.items()}

        for output_attr in stored_curves.values():
            for one_attr in (output_attr if isinstance(output_attr, list) else [output_attr]):
                self.set_start_frame(one_attr.node(), min_time_range)
                self.set_end_frame(one_attr.node())

        if component:
            stored_curves[COMPONENT_KEY] = naming.get_basename(component)

        attr_utils.set_compound_attribute_groups(self, obj_name, stored_curves)
        return obj

    def _hold_animation_layers(self):
        """
        Keep a reference to the animation layers the stored animation came through, so they survive
        being taken off whatever they were driving.
        """

        already_held = self.pynode.attr(ANIMATION_LAYERS_ATTR).listConnections()
        for anim_layer in pm.ls(type=pm.nt.AnimLayer):
            if not anim_layer.hasAttr(ORIGINAL_ANIM_LAYER_ATTR) or anim_layer in already_held:
                continue
            if not anim_layer.hasAttr(ANIMATED_CURVE_DATA_ATTR):
                anim_layer.addAttr(ANIMATED_CURVE_DATA_ATTR, at='message')
            self.pynode.attr(ANIMATION_LAYERS_ATTR) >> anim_layer.attr(ANIMATED_CURVE_DATA_ATTR)

    # ----------------------------------------------------------------------------------- #
    # where it lives
    # ----------------------------------------------------------------------------------- #
    def is_connected_to_skeleton(self):
        """
        :return: Whether this node is being carried by a skeleton.
        :rtype: bool
        """

        return bool(self.pynode.attr(ANIMATED_CURVE_DATA_ATTR).listConnections())

    def remove(self):
        """
        Delete this node and the animation it holds.
        """

        pm.delete(self.pynode)

    @classmethod
    def import_animated_curve_data(cls, full_path):
        """
        Bring a clip file in and find the node holding its animation.

        :param str full_path: The file.
        :return: The node, or None when the file holds none.
        :rtype: AnimatedCurvesComponent or None
        """

        imported = pm.importFile(full_path, returnNewNodes=True)
        curve_data = [node for node in imported
                      if isinstance(node, pm.nt.Network) and node.hasAttr(ANIMATED_CURVE_DATA_ATTR)]
        if not curve_data:
            logger.warning('%s holds no stored animation.', full_path)
            return None
        return cls(curve_data[0])

    def get_stored_nodes(self):
        """
        Every animation node ``exportSelected`` will pull in with this component.

        The walk is deliberately confined to animation node types. Following every connection out of
        the component would climb straight into the rig it was taken from, and the whole point of a
        clip file is that the rig is not in it.

        :return: The component plus its curves, blend nodes and animation layers.
        :rtype: list(pm.PyNode)
        """

        wanted = (pm.nt.AnimCurve, pm.nt.AnimBlendNodeBase, pm.nt.AnimLayer)
        found = {str(self.pynode): self.pynode}
        frontier = [self.pynode]
        while frontier:
            node = frontier.pop()
            for other in (pm.listConnections(node, source=True, destination=True,
                                             skipConversionNodes=True) or []):
                key = str(other)
                if key in found or not isinstance(other, wanted):
                    continue
                found[key] = other
                frontier.append(other)
        return list(found.values())

    def strip_namespaces(self):
        """
        Move everything this component holds into the root namespace.

        A clip is meant to be rig-agnostic, so a namespace baked into the file is a lie about where
        it came from - and importing one drags that namespace into whatever scene applies the clip.

        In practice the curves usually arrive here unnamespaced already, because ``keep_animation``
        duplicates them and Maya puts duplicates of referenced nodes in the root namespace. That is
        luck, not a guarantee: it does not hold for a component stored without duplication, and it
        is not something the file format should depend on.

        :return: The nodes that were renamed.
        :rtype: list(pm.PyNode)
        """

        renamed = []
        for node in self.get_stored_nodes():
            name = str(node)
            if ':' not in name:
                continue
            try:
                # A basename already taken in the root namespace gets numbered by Maya, which is
                # harmless: a restore matches on this node's attribute names, never on curve names.
                pm.rename(node, naming.get_basename(node))
                renamed.append(node)
            except Exception:
                logger.warning('Could not take the namespace off %s; it will be in the exported '
                               'file.', name, exc_info=True)
        return renamed

    def export(self, full_path):
        """
        Write this component and the animation it holds out as a clip file.

        :param str full_path: Where to write it. A ``.ma`` or a ``.mb``.
        :raises ValueError: When the path is neither.
        """

        if not full_path.endswith('.ma') and not full_path.endswith('.mb'):
            raise ValueError('A clip is a .ma or a .mb; {0} is neither.'.format(full_path))

        # Namespace off the component and everything it holds, so the file carries no trace of the
        # rig it was captured from.
        self.strip_namespaces()
        if self.pynode.attr(frag_base.FRAG_PARENT_ATTR).listConnections():
            pm.disconnectAttr(self.pynode.attr(frag_base.FRAG_PARENT_ATTR))

        scene_name = pm.sceneName()
        # self is the wrapper, not the node - passing it straight to pm.select raises
        # `Object ... is invalid`, which is why this method had never run to the end.
        pm.select(self.pynode, replace=True)
        cmds.file(rename=full_path)
        cmds.file(force=True, exportSelected=True,
                  type='mayaAscii' if full_path.endswith('.ma') else 'mayaBinary')
        cmds.file(rename=scene_name)


def _is_a_number(value):
    """
    Whether something is a frame or a distance rather than nothing at all.

    :param value: What to look at.
    :return: Whether it is a number. A bool is not: it is a number to Python and an answer to a
        question to everyone else.
    :rtype: bool
    """

    return isinstance(value, (int, float)) and not isinstance(value, bool)
