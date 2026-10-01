"""
The control a whole character is moved by: its centre of gravity.

One control over one joint. It is the component an animator reaches for first - shifting weight,
taking a whole body through an arc - so everything else in a rig hangs below it, and it drives a
duplicate of the root of the spine rather than the joint itself.

What was wrong before:

- **The fallback for finding the joint to be driven by could never reach its second choice, and
  could hand back None.** A COG is not a joint on a skeleton, so its region and side rarely match
  the markup, and ``attach_to_skeleton`` has three choices in order: the matching chain, the joint
  marked as the start of the animatable hierarchy, then the pelvis. The second was written as
  ``joint_list = [hierarchy_start]`` followed by ``if not joint_list:`` - a one-item list is true
  whatever is in it, so the pelvis was never looked for, and when the skeleton had no hierarchy
  start the list was ``[None]``. The guard below then quietly did nothing. Each choice is asked for
  on its own terms now, and the one that answers is used.
- The component's own region and side were used as the fallback for the lookup while the comment
  beside them explained that they would not match - which is the case the hierarchy start is there
  for.
- ``end_joint`` is taken and not used, because a COG only ever drives one joint. The walk between
  the two joints was kept with a comment saying the result was unused; it is kept, because walking
  is what warns a rigger who passed a pair that is not a chain, and the comment says that instead.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup
from mca.mya.rigging import cog_chain_rig
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import dag
from mca.mya.utils import namespace
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The prefix the duplicated joint the control drives carries.
COG_CHAIN_PREFIX = 'cog_chain'

#: What the component keeps its pieces on.
COG_FLAG_ATTR = 'cogFlag'
COG_CHAIN_ATTR = 'cogChain'
BIND_JOINTS_ATTR = keyable_component.BIND_JOINTS_ATTR

#: What an animator is not allowed to do to the control. A COG is moved and turned, never scaled.
COG_FLAG_LOCKED_ATTRS = ('sx', 'sy', 'sz', 'v')

#: Where to look for a joint to be driven by, when the component's own region and side do not match
#: the skeleton's markup - which for a COG is usual, because a COG is not a joint.
FALLBACK_REGION = 'pelvis'
FALLBACK_SIDE = 'center'


class CogComponent(keyable_component.KeyableComponent):
    """
    The centre of gravity: one control, one joint, everything else below it.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, end_joint, side, region, scale=1.0,
               orientation=cog_chain_rig.DEFAULT_ORIENTATION, **kwargs):
        """
        Build the component over one bind joint.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The joint the control drives - the only one it ever drives.
        :param pm.nt.Joint end_joint: The end of the run this component was described over. Taken so
            a template can hand over one argument list for every component; a COG uses only the
            start.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param float scale: How big to draw the control.
        :param orientation: A rotation for the control's zero pose.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: CogComponent
        """

        build_kwargs = {'scale': scale, 'orientation': orientation}

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                        CogComponent.__name__,
                                                        CogComponent.VERSION,
                                                        side=side,
                                                        region=region,
                                                        align_component=start_joint)
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 build_kwargs)

        # Nothing is done with the answer. Walking between the two joints is what warns a rigger who
        # has passed a pair that is not a chain, and that warning is the whole reason end_joint is
        # taken at all.
        dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)

        # One joint, because a COG is one joint. The animator drives the copy and the bind joint
        # follows it, as everywhere else in frag.
        cog_joint = joint_utils.duplicate_joint(
            start_joint, '{0}_{1}'.format(COG_CHAIN_PREFIX, naming.get_basename(start_joint)))
        built = cog_chain_rig.cog_chain(cog_joint, cog_joint, scale=scale, orientation=orientation)

        cog_flag = built['flags'][0]
        cog_flag.get_align_transform().setParent(node.flag_group)
        cog_joint.setParent(node.no_touch_grp)

        node.connect_node(cog_flag, COG_FLAG_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes([cog_joint], COG_CHAIN_ATTR, frag_base.FRAG_PARENT_ATTR)
        node.connect_nodes([start_joint], BIND_JOINTS_ATTR)

        cog_flag.lock_and_hide_attrs(list(COG_FLAG_LOCKED_ATTRS))

        return node

    def get_flags(self):
        """
        :return: The one control this component owns.
        :rtype: list(frag_flag.Flag)
        """

        return [frag_flag.Flag(self.pynode.attr(COG_FLAG_ATTR).get())]

    @property
    def cog_flag(self):
        """
        :return: The centre of gravity control.
        :rtype: frag_flag.Flag
        """

        return frag_flag.Flag(self.pynode.attr(COG_FLAG_ATTR).get())

    def driving_joint(self, attach_skeleton_root):
        """
        The joint on another skeleton this component should follow.

        A COG is not a joint, so its region and side usually match nothing on a skeleton. There are
        three places to look, in order: the chain that matches this component's markup, the joint
        marked as the start of the animatable hierarchy, and the pelvis. The version before could
        never reach the third and could answer None from the second.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to look in.
        :return: The joint, or None when the skeleton offers none of the three.
        :rtype: pm.nt.Joint or None
        """

        matching = self.matching_chain(attach_skeleton_root)
        if matching:
            return matching[0]

        hierarchy = chain_markup.ChainMarkup(attach_skeleton_root)
        if hierarchy.hierarchyStart:
            return hierarchy.hierarchyStart

        pelvis = hierarchy.get_full_chain(FALLBACK_REGION, FALLBACK_SIDE)
        if pelvis:
            return pelvis[0]

        logger.warning('%s found nothing on %s to be driven by: no %s %s chain, no joint marked as '
                       'the start of the hierarchy, and no %s %s.', self.pynode,
                       attach_skeleton_root, self.side, self.region, FALLBACK_SIDE, FALLBACK_REGION)
        return None

    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's control from a skeleton.

        Translation only. A COG's rotation is the animator's, even when its position is being driven
        from somewhere else.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep the control where it is rather than snapping it to the joint.
        :return: The constraint built, in a list, or an empty list.
        :rtype: list
        """

        joint_node = self.driving_joint(attach_skeleton_root)
        if joint_node is None:
            return []

        constraint_node = constraint.parent_constraint_safe(joint_node, self.cog_flag,
                                                           skip_rotate_attrs=['x', 'y', 'z'],
                                                           mo=mo)
        return [constraint_node] if constraint_node else []
