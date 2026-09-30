"""
An FK chain: a control per joint, each parented under the one above it.

The plainest thing a rig has. One flag per joint, nested so that turning a shoulder carries the
elbow and the wrist with it, and each flag parent constraining the joint it was built on.

The end joint is left out by default. The last joint of a chain is usually a leaf carrying the
chain's length and nothing else, and a control there drives nothing an animator can see.

What was wrong before:

- **A chain built without align transforms raised.** The parenting step reads
  ``flag_node.alignTransform.get()`` - the attribute directly - and a flag built with
  ``add_align_transform=False`` does not have that attribute, so it is an ``AttributeError`` rather
  than the None the surrounding ``if`` is written for. Both ``root_align_transform=False`` and
  ``children_align_transforms=False`` reached it. It asks the flag now, which answers None.
- **One branch of the three could never run.** ``elif create_end_flag and inc == len(chain_to_rig)``
  - ``enumerate`` never yields an index equal to the length of what it is walking. The end flag was
  always built by the branch below it, which is the same call with a different align-transform
  argument. Gone, leaving the two cases that exist: the first joint, and the rest.
- A chain of one joint with ``create_end_flag`` off builds nothing at all and used to say nothing
  about it.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import dag
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: How much smaller an offset control is drawn than the control it sits under.
OFFSET_SCALE = 0.75


def fk_joint_chain(start_joint,
                   end_joint,
                   scale=1.0,
                   root_align_transform=True,
                   children_align_transforms=True,
                   create_end_flag=False,
                   offset_flag=False,
                   use_scale=False,
                   suffix='fk_chain'):
    """
    Build an FK control chain over the joints between two joints.

    :param pm.nt.Joint start_joint: The first joint of the chain.
    :param pm.nt.Joint end_joint: The last one.
    :param float scale: How big to draw the controls.
    :param bool root_align_transform: Give the first control a zeroed group above it.
    :param bool children_align_transforms: Give the rest of them one.
    :param bool create_end_flag: Build a control on the end joint too, rather than stopping one
        short of it.
    :param bool offset_flag: Give the last rigged joint a second, smaller detail control which
        drives the joint in place of the main one.
    :param bool use_scale: Wire each control's scale straight through to its joint.
    :param str suffix: A suffix to take off each control's name, usually the one the source chain
        was duplicated with.
    :return: The nodes built, under ``chain``, ``start_joint``, ``end_joint``, ``flags``,
        ``parent_constraints`` and ``offset_flag``.
    :rtype: dict
    """

    if not start_joint or not pm.objExists(start_joint):
        raise pm.MayaNodeError(
            'The start joint given, {0}, does not exist.'.format(start_joint))
    if not end_joint or not pm.objExists(end_joint):
        raise pm.MayaNodeError('The end joint given, {0}, does not exist.'.format(end_joint))

    start_joint = pm.PyNode(start_joint)
    end_joint = pm.PyNode(end_joint)
    chain = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)

    chain_to_rig = chain if create_end_flag else chain[:-1]
    if not chain_to_rig:
        logger.warning('There is nothing to rig between %s and %s%s.', start_joint, end_joint,
                       '' if create_end_flag else
                       ' once the end joint is left out - pass create_end_flag to include it')

    flags = []
    parent_consts = []
    new_offset_flag = None
    last = None
    for index, joint_node in enumerate(chain_to_rig):
        label = naming.get_basename(joint_node)
        if suffix:
            label = label.replace('_' + suffix, '')

        # create_ratio is create with the shape offset kept. The first joint takes its own
        # align-transform setting; everything below it takes the children's.
        flag_node = frag_flag.Flag.create_ratio(
            joint_node,
            label=label,
            add_align_transform=root_align_transform if not index else children_align_transforms,
            scale=scale)

        # Nest under the control above, by its align group where it has one. Reading the attribute
        # directly - which is what this did - is an AttributeError on a flag built without one.
        align_transform = flag_node.get_align_transform()
        (align_transform or flag_node).setParent(last)

        if offset_flag and joint_node == chain_to_rig[-1]:
            new_offset_flag = frag_flag.Flag.create(joint_node,
                                                    scale=scale * OFFSET_SCALE,
                                                    label=label + '_offset',
                                                    add_align_transform=True,
                                                    is_detail=True)
            pm.parent(new_offset_flag.get_align_transform(), flag_node)
            # The offset control drives the joint, so an animator can key a small correction on
            # top of the main control's pose.
            driver = new_offset_flag
        else:
            driver = flag_node

        parent_consts.append(pm.parentConstraint(driver, joint_node, weight=1,
                                                maintainOffset=True))
        if use_scale:
            flag_node.node.scale >> joint_node.scale

        last = flag_node
        flags.append(flag_node)

    return {'chain': chain,
            'start_joint': start_joint,
            'end_joint': end_joint,
            'flags': flags,
            'parent_constraints': parent_consts,
            'offset_flag': new_offset_flag}
