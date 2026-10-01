"""
The control that tips a character's hips without moving the spine above them.

A pelvis is a reverse chain: the control turns the start joint *about* the joint below it, so the
hips rock around the base of the spine rather than around their own pivot. That is what
``reverse_chain_rig`` builds, and this is the component that wraps it - one sub control over a
duplicate of the two bind joints, with only the first of them driven, because everything below the
pelvis belongs to the legs and everything above it to the spine.

What was wrong before:

- ``create`` parented the duplicated chain into the no-touch group twice, four lines apart.
- **The one constraint the component makes was written as a loop with ``break`` as its last
  statement**, which is a ``for`` that runs once: ``for base, reverse in zip(chain_between,
  rev_chain): pm.parentConstraint(reverse, base, w=1); break``. Only the first pair is meant to be
  constrained, which is right, and it says so directly now. The loop reads as though it is guarding
  something, and it is not: a start and end joint that are not a chain blow up three lines above it
  on ``rev_chain[0]``, because ``duplicate_chain`` answers an empty list for a pair it cannot walk
  between. That question is asked before anything is built now, and refused the way the IK
  components refuse a chain of the wrong length.
- The control was marked as a sub control by setting ``isSub`` on it by hand, next to
  ``Flag.set_as_sub``, which is the method for it.
- ``attach_to_skeleton`` had its own copy of the twelve-line lookup every component that can be
  driven by a skeleton used to carry; that is ``KeyableComponent.matching_chain``.
- ``bindJoints`` holds the start and end joints rather than the run between them, which is
  deliberate - the pelvis drives one joint and the chain below it is another component's - but
  nothing said so, and a bake of this component therefore covers two joints it does not both drive.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import joint_utils
from mca.mya.rigging import reverse_chain_rig
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag
from mca.mya.utils import namespace


#: The suffix the duplicated chain the control drives carries.
REVERSE_CHAIN_SUFFIX = 'rev_chain'

#: What the component keeps its pieces on.
PELVIS_FLAG_ATTR = 'pelvisFlag'
PELVIS_CHAIN_ATTR = 'pelvisChain'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: What an animator is not allowed to do to the control by default. A pelvis rocks; it does not
#: travel or scale - the body above it is what moves.
DEFAULT_LOCKED_ATTRS = tuple(attr_utils.TRANSLATION_ATTRS + attr_utils.SCALE_ATTRS)


class PelvisComponent(keyable_component.KeyableComponent):
    """
    One sub control turning the hips about the base of the spine.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, end_joint, side, region,
               attrs_to_lock=DEFAULT_LOCKED_ATTRS, scale=1.0,
               orientation=reverse_chain_rig.DEFAULT_ORIENTATION, **kwargs):
        """
        Build the component over a run of bind joints.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The joint the control drives - the only one it drives.
        :param pm.nt.Joint end_joint: The joint below it, which the control turns about.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param attrs_to_lock: Channels to take away from the animator. Empty leaves them all.
        :param float scale: How big to draw the control.
        :param orientation: A rotation for the control's zero pose.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: PelvisComponent
        :raises RuntimeError: When the end joint is not below the start joint. The version before
            got as far as duplicating the chain and raised ``IndexError`` on the empty list that
            came back.
        """

        chain_between = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
        if not chain_between:
            raise RuntimeError(
                'A pelvis component turns one joint about the joint below it. {0} is not above '
                '{1}.'.format(start_joint, end_joint))

        build_kwargs = {'attrs_to_lock': attrs_to_lock, 'scale': scale, 'orientation': orientation}

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        PelvisComponent.__name__,
                                                        PelvisComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        reverse_chain = joint_utils.duplicate_chain(start_joint, end_joint,
                                                    suffix=REVERSE_CHAIN_SUFFIX)
        reverse_chain[0].setParent(node.no_touch_grp)
        built = reverse_chain_rig.reverse_chain(reverse_chain[0], reverse_chain[-1],
                                               suffix=REVERSE_CHAIN_SUFFIX, scale=scale,
                                               orientation=orientation)

        pelvis_flag = built['flag']
        pelvis_flag.set_as_sub()
        built['align_group'].setParent(node.flag_group)
        built['rotate_joint'].setParent(node.no_touch_grp)

        node.connect_node(pelvis_flag, PELVIS_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes(reverse_chain, PELVIS_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        # The start and the end, not the run between them: the pelvis drives the start joint and the
        # chain below it belongs to the legs. Those two are what a bake of this component covers.
        node.connect_nodes([start_joint, end_joint], BIND_JOINTS_ATTR)

        if attrs_to_lock:
            pelvis_flag.lock_and_hide_attrs(list(attrs_to_lock))

        # The first pair only, and only the first: the chain below the pelvis is the legs'. This
        # was a for loop over both chains whose last statement was `break`.
        pm.parentConstraint(reverse_chain[0], chain_between[0], w=1)

        return node

    def get_flags(self):
        """
        :return: The one control this component owns.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(self.pynode.attr(PELVIS_FLAG_ATTR).get())]

    @property
    def pelvis_flag(self):
        """
        :return: The control that turns the hips.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(PELVIS_FLAG_ATTR).get())

    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's control from a skeleton.

        Rotation only. A pelvis control does not travel - whatever is above it in the rig is what
        carries the character through space - so driving its position from a skeleton would fight
        the component above it.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep the control where it is rather than snapping it to the joint.
        :return: The constraint built, in a list, or an empty list.
        :rtype: list
        """

        joint_list = self.matching_chain(attach_skeleton_root)
        if not joint_list:
            return []

        constraint_node = constraint.parent_constraint_safe(joint_list[0], self.pelvis_flag,
                                                           skip_translate_attrs=['x', 'y', 'z'],
                                                           mo=mo)
        return [constraint_node] if constraint_node else []
