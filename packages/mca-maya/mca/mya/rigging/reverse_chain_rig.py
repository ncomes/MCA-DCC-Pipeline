"""
A reverse chain: pivoting a joint about its own child.

A pelvis is the usual case. The hips joint is above the spine, so rotating it swings the whole
torso - but an animator wants to rotate the hips *about* the base of the spine, leaving the spine
where it is. The way to get that is a second, hidden two-joint chain parented the other way round,
with the control on its root: rotating the control turns the hidden chain, and the visible start
joint follows the hidden chain's child.

What was wrong before:

- **The default suffix stripped every underscore out of the control's name.** The label is
  ``start_joint.nodeName().replace('_' + suffix, '')``, and ``suffix`` defaults to ``''`` - so the
  replacement is ``'_'`` for nothing at all, and a joint called ``l_ankle`` gave a flag called
  ``f_lankle``. Its one caller passes a suffix, which is why nobody has seen it. The strip only
  happens when there is something to strip now.
- The refusal read *"There can be no joints between startJoint and endJoint"*, which is what it
  requires rather than what went wrong, raised at the moment there *were* joints between them.
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

#: The flag is turned by this much so a flat control drawn in XZ reads as horizontal.
DEFAULT_ORIENTATION = (-90, 0, 0)


def reverse_chain(start_joint, end_joint, suffix='', scale=1.0, orientation=DEFAULT_ORIENTATION):
    """
    Build a control that pivots the start joint about the end joint.

    :param pm.nt.Joint start_joint: The joint that ends up following the reversed chain.
    :param pm.nt.Joint end_joint: Its child, which becomes the pivot.
    :param str suffix: A suffix to take off the control's name, usually the one the source chain
        was duplicated with.
    :param float scale: How big to draw the control.
    :param orientation: A rotation for the control's zero pose.
    :return: The nodes built, under ``chain``, ``start_joint``, ``end_joint``, ``rotate_joint``,
        ``align_group`` and ``flag``.
    :rtype: dict
    """

    chain = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)
    if len(chain) != 2:
        raise RuntimeError(
            'A reverse chain is built from a joint and its immediate child. {0} and {1} have {2} '
            'joints between them.'.format(start_joint, end_joint, max(len(chain) - 2, 0)))

    # The hidden chain, parented the other way round: the end joint becomes the root, so turning
    # it swings the start joint about it.
    rotate_joint = pm.duplicate(end_joint, parentOnly=True)[0]
    end_rotate_joint = pm.duplicate(start_joint, parentOnly=True)[0]
    end_rotate_joint.setParent(rotate_joint)
    rotate_joint.setParent(None)
    rotate_joint.visibility.set(0)

    label = naming.get_basename(start_joint)
    if suffix:
        # Only when there is a suffix: '_' + '' is '_', and replacing that with nothing takes
        # every underscore out of the name.
        label = label.replace('_' + suffix, '')

    rotate_flag = frag_flag.Flag.create(rotate_joint, label=label, scale=scale,
                                        orientation=orientation)
    pm.parentConstraint(rotate_flag, rotate_joint, weight=1, maintainOffset=True)
    pm.parentConstraint(end_rotate_joint, start_joint, weight=1, maintainOffset=True)

    return {'chain': chain,
            'start_joint': start_joint,
            'end_joint': end_joint,
            'rotate_joint': rotate_joint,
            'align_group': rotate_flag.get_align_transform(),
            'flag': rotate_flag}
