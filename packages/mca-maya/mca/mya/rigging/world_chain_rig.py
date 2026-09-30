"""
The world controls: the three nested flags at the bottom of every rig.

``world`` is the outermost - moving it moves the character and everything on it. ``root`` sits
inside it and is the one the skeleton's root joint actually follows, so an animator can offset the
character within a shot without disturbing the world control a layout artist has placed. And
``world_offset`` sits inside that again, as a detail control for a second offset that does not
touch either of the other two.

They are drawn at descending sizes so the nesting is visible in the viewport.

What was wrong before:

- **The ``flags`` entry in the result left out the offset flag**, though all three are built and all
  three are locked the same way. Its one caller does not read that entry - it wires up the three
  flags it asked for by name - so nothing depended on the omission, and all three are in it now.
- The align group was fetched as ``world_flag.getParent()`` rather than through
  ``get_align_transform()``, which is the same node by a name that says what it is.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import dag


logger = log.MCA_LOGGER

#: How much smaller each nested control is drawn than the world control.
ROOT_SCALE = 0.85
OFFSET_SCALE = 0.65

#: The flags are turned by this much so a flat control drawn in XZ reads as horizontal.
DEFAULT_ORIENTATION = (-90, 0, 0)

#: The world controls do not scale the character, so their scale channels are taken away.
LOCKED_CHANNELS = ('sx', 'sy', 'sz')


def world_chain(joint, scale=1.0, orientation=DEFAULT_ORIENTATION):
    """
    Build the world, root and world offset controls on a rig's root joint.

    :param pm.nt.Joint joint: The root joint the controls are built on and which follows ``root``.
    :param float scale: How big to draw the world control; the other two are drawn smaller.
    :param orientation: A rotation for each control's zero pose.
    :return: The nodes built, under ``chain``, ``joint``, ``align_group``, ``flags``,
        ``world_flag``, ``root_flag`` and ``offset_flag``.
    :rtype: dict
    """

    chain = dag.get_between_nodes(joint, joint, pm.nt.Joint)

    world_flag = frag_flag.Flag.create(joint, label='world', scale=scale, orientation=orientation)
    root_flag = frag_flag.Flag.create(joint, label='root', scale=scale * ROOT_SCALE,
                                      orientation=orientation)
    offset_flag = frag_flag.Flag.create(joint, label='world_offset', scale=scale * OFFSET_SCALE,
                                       orientation=orientation)

    # Both nested controls hang off the world control, so it carries all three.
    pm.parent(offset_flag.get_align_transform(), world_flag)
    pm.parent(root_flag.get_align_transform(), world_flag)

    # The root, not the world control: an animator offsets the character with root and leaves
    # world where layout put it.
    pm.parentConstraint(root_flag, joint, weight=1, maintainOffset=True)

    flags = [world_flag, root_flag, offset_flag]
    for flag_node in flags:
        flag_node.lock_and_hide_attrs(list(LOCKED_CHANNELS))

    return {'chain': chain,
            'joint': joint,
            'align_group': world_flag.get_align_transform(),
            'flags': flags,
            'world_flag': world_flag,
            'root_flag': root_flag,
            'offset_flag': offset_flag}
