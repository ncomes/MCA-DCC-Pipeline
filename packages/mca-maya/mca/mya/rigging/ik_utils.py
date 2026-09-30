"""
Pole vectors: where the elbow or the knee should point.

An IK handle needs somewhere to aim its middle joint at, and that somewhere has to be off the
line between the chain's root and its end - on the side the joint already bends towards, or the
limb snaps through on the first frame. :func:`get_pole_vector_position` works that place out from
the chain's own pose: project the middle joint onto the root-to-end line, and step away from that
projection, in the direction the middle joint already lies, by the length of the chain.

What was wrong before:

- **An even-numbered chain took its middle from the wrong pair of joints.** The middle of a chain
  with no single middle joint is between the two either side of the centre - indexes 1 and 2 of
  four. The code used ``len(joint_chain) // 2`` and the one after it, which for four joints is
  indexes 2 and 3: the joint past the middle and the end joint. The pole vector came out planted
  near the end of the limb rather than out in front of its bend. Six of the seven callers pass
  three joints, so this only shows on the seventh - which passes whatever chain it was given.
- **A two-joint chain raised.** The same arithmetic gives indexes 1 and 2, and there is no index
  2. A two-joint chain has no middle and no pole vector; it is refused with a message now.
- **A chain folded flat divided by zero.** ``(line * point) / (line * line)`` where the root and
  the end are in the same place. That is a real pose - a fully folded finger - and it answered
  ``nan`` for every component, which Maya takes without complaint and which shows up much later
  as a control nobody can select. When the root and the end coincide there is no line to project
  onto, but the plane is still well defined by the middle joint, so the root is used as the
  projection instead.
- A chain with no bend at all has no discoverable direction to put a pole vector in. That still
  answers the middle joint's own position, as it always has, but it says so in the log now
  rather than quietly handing back a degenerate answer.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

def _world_vector(node):
    """
    :param node: Anything with a world position.
    :return: Its world position.
    :rtype: pm.dt.Vector
    """

    return pm.dt.Vector(pm.xform(node, worldSpace=True, query=True, translation=True))


def get_pole_vector_position(joint_chain, offset=None):
    """
    Where a pole vector for this chain should sit, in world space.

    :param list joint_chain: The joints, root first. Three or more.
    :param float offset: How far from the middle joint to place it. None means the chain's own
        length, root to middle plus middle to end.
    :return: The world position, or None when the chain cannot have one.
    :rtype: pm.dt.Vector
    """

    if not joint_chain or len(joint_chain) < 3:
        logger.warning('A pole vector needs a chain of at least three joints; %s were given.',
                       len(joint_chain or []))
        return None

    root_vector = _world_vector(joint_chain[0])
    end_vector = _world_vector(joint_chain[-1])

    if len(joint_chain) % 2:
        middle_vector = _world_vector(joint_chain[(len(joint_chain) - 1) // 2])
    else:
        # No single middle joint, so the point between the two either side of the centre. For
        # four joints that is indexes 1 and 2 - the old arithmetic gave 2 and 3.
        before = (len(joint_chain) - 1) // 2
        middle_vector = (_world_vector(joint_chain[before]) +
                         _world_vector(joint_chain[before + 1])) * 0.5

    line = end_vector - root_vector
    line_length_squared = line * line
    if line_length_squared:
        # Where the middle joint would be if the chain had no bend in it.
        point = middle_vector - root_vector
        projected = line * ((line * point) / line_length_squared) + root_vector
    else:
        # Root and end in the same place: no line to project onto, but the middle joint and the
        # root still define the direction. The old arithmetic divided by zero here.
        projected = root_vector

    bend = middle_vector - projected
    if not bend.length():
        logger.warning('The chain starting at %s is perfectly straight, so which way it bends '
                       'cannot be read from its pose - the pole vector lands on the middle '
                       'joint. Build the chain with a bend in it.', joint_chain[0])
        return middle_vector

    total_length = offset if offset is not None else (
        (middle_vector - root_vector).length() + (end_vector - middle_vector).length())
    return bend.normal() * total_length + middle_vector


def create_pole_vector_locator(joint_chain, name=None, offset=None):
    """
    Put a locator where a pole vector for this chain should sit.

    :param list joint_chain: The joints, root first.
    :param str name: A name for the locator.
    :param float offset: How far from the middle joint to place it.
    :return: The locator, or None when the chain cannot have a pole vector.
    :rtype: pm.nt.Transform
    """

    position = get_pole_vector_position(joint_chain, offset=offset)
    if position is None:
        return None

    pole_locator = pm.spaceLocator(name=name or 'poleVectorLoc')
    pole_locator.translate.set(list(position))
    return pole_locator
