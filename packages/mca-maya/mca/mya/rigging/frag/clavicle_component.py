"""
A clavicle: one FK control on one joint, under its own class name.

Mechanically this is an :class:`~fk_component.FKComponent` over a single joint. It exists as its
own class because a clavicle has to be *recognisable* - retargeting and the engine both treat the
shoulder differently from any other FK joint, and a FRAG node carries nothing but its class name to
say what it is. So the node is built as an FK component and then retyped and renamed.

The one behavioural difference is which way round it is driven: when a clavicle is driven from
another skeleton it takes rotation only. A clavicle's position belongs to the spine above it, and
letting a skeleton push it around moves the shoulder off the chest.

What was wrong before:

- **The lookup fell back to the attribute rather than its value.** ``skel_region = skel_region or
  self.pynode.region`` - ``self.pynode.region`` is a pymel ``Attribute``, not the string on it, and
  it goes straight into a dictionary lookup, which then matches nothing. So a clavicle driven from
  a skeleton whose joints carry no ``skelRegion`` markup - an imported skeleton, which is the case
  the fallback exists for - silently drove nothing. ``FKComponent``, which this inherits from, used
  the ``side`` and ``region`` properties two lines away from the same spot. The whole block is
  ``KeyableComponent.matching_chain`` now, which reads the properties.
- **``attach_to_skeleton`` attached nothing, silently, when the rig had more controls than the
  skeleton had joints**, inherited from ``FKComponent`` along with everything else: ``if flag_list
  and len(flag_list) <= len(joint_list)``. A clavicle has one control, so this only bit a skeleton
  with no matching joints at all - which is the case above.
- **``lock_root_translate_axes`` defaults to ``['v']``** - a visibility channel passed as the list
  of *translate* axes to lock. ``FKComponent`` locks ``['v']`` anyway, so the effect is that a
  clavicle control has all three translate channels free while the parameter name says otherwise.
  Left as it is, because locking them would change every rig built from a template, and written
  down here and in the decisions list instead.
- ``node.pynode.version.set(...)`` and ``fragType.set(...)`` were written by hand where
  ``set_version`` and the type attribute's own constant exist. ``locked_vertices`` was a second
  name for ``lock_root_translate_axes``, assigned and then used once; there are no vertices
  anywhere near this.
- Retyping overwrites the whole ``buildKwargs`` block that ``FKComponent.create`` just wrote, which
  is right - this class takes a different argument list - but it means a clavicle records only the
  one argument, and ``scale`` is not among them, so a rebuilt clavicle draws a default-sized
  control. ``scale`` is a parameter now and is recorded.
"""

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import fk_component
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What a clavicle's region is called when the caller does not say.
DEFAULT_REGION = 'clav'

#: What a clavicle control is not allowed to do. The default is what the version before passed as
#: ``lock_root_translate_axes``: a visibility channel, which is not a translate axis - so a clavicle
#: control has all three translates free. See this module's docstring.
DEFAULT_LOCKED_ATTRS = ('v',)


class ClavicleComponent(fk_component.FKComponent):
    """
    One FK control on one joint, recognisable as a shoulder.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, start_joint, side, region=DEFAULT_REGION,
               lock_root_translate_axes=DEFAULT_LOCKED_ATTRS, scale=1.0, **kwargs):
        """
        Build the component over one bind joint.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint start_joint: The clavicle joint.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param lock_root_translate_axes: Channels to take away from the animator. The name says
            translate axes and the default is a visibility channel - see this module's docstring.
        :param float scale: How big to draw the control.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: ClavicleComponent
        """

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = fk_component.FKComponent.create(frag_parent, start_joint, start_joint, side=side,
                                               region=region, scale=scale,
                                               lock_root_translate_axes=lock_root_translate_axes)

        # Retyped, not rebuilt. The node is an FK component in every way that matters to Maya; what
        # makes it a clavicle is the class name it carries, which is all a FRAG node has to say what
        # it is.
        node.pynode.attr(frag_base.FRAG_TYPE_ATTR).set(ClavicleComponent.__name__)
        node.set_version(ClavicleComponent.VERSION)
        node.pynode.rename('{0}_{1}_{2}'.format(ClavicleComponent.__name__, side, region))

        # This replaces the block FKComponent.create wrote, because this class takes a different
        # argument list - so everything a rebuild needs has to be in here.
        attr_utils.set_compound_attribute_groups(
            node.pynode, frag_base.BUILD_KWARGS_ATTR,
            {'lock_root_translate_axes': list(lock_root_translate_axes), 'scale': scale})

        return ClavicleComponent(node.pynode)

    def get_start_flag(self):
        """
        The one control this component has.

        ``FKComponent.get_start_flag`` answers the *last* control, which for a one-control component
        is the same thing - but the two names are the wrong way round there and this says what it
        means rather than relying on that.

        :return: The control.
        :rtype: frag_flag.Flag
        """

        return self.get_flags()[0]

    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive this component's control from a skeleton.

        Rotation only. A clavicle's position belongs to the spine above it, so letting a skeleton
        drive it as well moves the shoulder off the chest.

        :param pm.nt.Joint attach_skeleton_root: The root of the skeleton to be driven by.
        :param bool mo: Keep the control where it is rather than snapping it to the joint.
        :return: The constraints built.
        :rtype: list
        """

        joint_list = self.matching_chain(attach_skeleton_root)
        if not joint_list:
            return []

        flag_list = self.get_flags()
        if len(flag_list) > len(joint_list):
            logger.warning('%s has %s controls and %s %s on the skeleton has only %s joints, so '
                           'the last %s are not driven.', self.pynode, len(flag_list), self.side,
                           self.region, len(joint_list), len(flag_list) - len(joint_list))

        constraint_list = []
        for flag_node, joint_node in zip(flag_list, joint_list):
            constraint_node = constraint.parent_constraint_safe(
                joint_node, flag_node, skip_translate_attrs=['x', 'y', 'z'], mo=mo)
            if constraint_node:
                constraint_list.append(constraint_node)
            for axis in attr_utils.SCALE_ATTRS:
                if flag_node.node.attr(axis).isSettable():
                    joint_node.attr(axis) >> flag_node.node.attr(axis)
        return constraint_list
