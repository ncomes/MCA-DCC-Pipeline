"""
Pairing flags across a rig's centre line, and what that does to their channels.

Two separate problems live here and it is worth keeping them apart.

**Which flag pairs with which** is a naming question, and it is answerable with certainty. The rigs
in this project name sides three ways at once - ``f_hand_l`` / ``f_hand_r``, ``f_left_arm`` /
``f_right_arm``, and ``f_l_leg_toe_ik`` / ``f_r_leg_toe_ik`` - so the match is done on whole
underscore-separated tokens rather than substrings. That matters: ``f_ring_01_l`` contains an "r"
but its side is the trailing token, and a substring rule would turn it into ``f_ling_01_l``.

**Which channels flip** is a rigging question, and it is *not* answerable from names. It depends on
how the rig's controls were oriented, and there is no single right answer across rigs. So this
module does not guess: it names the two conventions that cover almost everything, and the animation
library's mirror calibration measures which one a given rig actually obeys, by moving flags and
watching where they end up.

Nothing here touches Maya. It is arithmetic and string handling, which is why it can be read - and
checked - without a scene.

What was wrong before: nothing, other than an unused ``import re``. This module was rewritten
during the mirror calibration work and comes over as it stands.
"""

# python imports


#: Side tokens, longest first so 'left' is tried before 'l'.
SIDE_PAIRS = (('left', 'right'), ('lft', 'rgt'), ('lf', 'rt'), ('l', 'r'))

#: Mirroring across the YZ plane, for a rig whose left and right controls were built with mirrored
#: *behaviour* - the usual result of ``mirrorJoint -mirrorBehavior``. Positive rotateY on the left
#: does the same thing as negative rotateY on the right.
BEHAVIOUR_MIRROR = {'translateX': -1.0, 'rotateY': -1.0, 'rotateZ': -1.0}

#: The other common build, where the controls share a world orientation rather than a mirrored one.
ORIENTATION_MIRROR = {'translateX': -1.0, 'rotateX': -1.0}

#: The conventions by name, for reporting which one a rig turned out to obey.
CONVENTIONS = {'behaviour': BEHAVIOUR_MIRROR, 'orientation': ORIENTATION_MIRROR}

#: Channels a mirror has any opinion about at all. Anything else - a custom float, an ikfk switch,
#: visibility - crosses over unchanged, because a mirror is a statement about space and those are
#: not spatial.
SPATIAL_CHANNELS = ('translateX', 'translateY', 'translateZ',
                    'rotateX', 'rotateY', 'rotateZ',
                    'scaleX', 'scaleY', 'scaleZ')

_SHORT_TO_LONG = {
    'tx': 'translateX', 'ty': 'translateY', 'tz': 'translateZ',
    'rx': 'rotateX', 'ry': 'rotateY', 'rz': 'rotateZ',
    'sx': 'scaleX', 'sy': 'scaleY', 'sz': 'scaleZ',
}


def long_channel_name(attribute):
    """
    Normalise an attribute name so conventions can be keyed on one spelling.

    :param str attribute: ``'tx'``, ``'translateX'``, or anything else.
    :return: The long name where one is known, otherwise the input unchanged.
    :rtype: str
    """

    name = str(attribute).split('.')[-1]
    return _SHORT_TO_LONG.get(name, name)


def mirror_name(name):
    """
    The name of a flag's opposite number.

    Matches on whole underscore-separated tokens, so ``f_ring_01_l`` mirrors on its trailing ``l``
    and leaves ``ring`` alone.

    :param str name: A flag's short name, with no namespace.
    :return: The mirrored name, or ``''`` when the name has no side in it.
    :rtype: str
    """

    tokens = str(name).split('_')
    swapped = list(tokens)
    found = False
    for index, token in enumerate(tokens):
        lowered = token.lower()
        for left, right in SIDE_PAIRS:
            if lowered == left:
                swapped[index] = _match_case(token, right)
                found = True
                break
            if lowered == right:
                swapped[index] = _match_case(token, left)
                found = True
                break
        if found:
            # Only the first side token is swapped. A name with two of them is not something these
            # rigs produce, and swapping both would turn 'l_thing_r' into 'r_thing_l', which is the
            # same flag again.
            break
    return '_'.join(swapped) if found else ''


def _match_case(original, replacement):
    """
    :param str original: The token being replaced.
    :param str replacement: Its replacement, in lower case.
    :return: The replacement in the original's case.
    :rtype: str
    """

    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement.capitalize()
    return replacement


def has_side(name):
    """
    :param str name: A flag's short name.
    :return: True when the name carries a side token.
    :rtype: bool
    """

    return bool(mirror_name(name))


def build_mirror_map(names):
    """
    Pair up a set of flag names.

    A centre flag - a root, a spine, a head - maps to itself, which is correct rather than a
    special case: mirroring a spine control means putting the mirrored values back on the same
    control.

    :param names: Flag short names, with no namespaces.
    :return: ``{name: partner name}``, only for names whose partner is present.
    :rtype: dict
    """

    present = set(names)
    mapping = {}
    for name in present:
        partner = mirror_name(name)
        if not partner:
            mapping[name] = name
        elif partner in present:
            mapping[name] = partner
        # A sided flag whose partner is missing is left out entirely. Mirroring it onto itself
        # would apply left-hand values to the left hand with the signs flipped, which is not a
        # mirror, it is damage.
    return mapping


def unpaired(names):
    """
    Sided flags whose opposite number is not in the set.

    :param names: Flag short names.
    :return: The names that could not be paired, sorted.
    :rtype: list(str)
    """

    present = set(names)
    return sorted(name for name in present
                  if mirror_name(name) and mirror_name(name) not in present)


def channel_sign(attribute, convention=BEHAVIOUR_MIRROR):
    """
    What a mirror does to one channel's value.

    :param str attribute: An attribute name, long or short.
    :param dict convention: Channel name to multiplier; see :data:`CONVENTIONS`.
    :return: -1.0 when the channel flips, 1.0 when it crosses unchanged.
    :rtype: float
    """

    return float(convention.get(long_channel_name(attribute), 1.0))


def mirrored_value(attribute, value, convention=BEHAVIOUR_MIRROR, default=0.0):
    """
    A channel's value on the other side.

    Flipped around the attribute's default rather than around zero, because a channel whose rest
    value is not zero would otherwise be thrown off its rest pose by mirroring.

    :param str attribute: An attribute name, long or short.
    :param float value: The value on this side.
    :param dict convention: Channel name to multiplier.
    :param float default: The attribute's rest value.
    :return: The value for the opposite flag.
    :rtype: float
    """

    if channel_sign(attribute, convention) > 0:
        return value
    return default - (value - default)


def describe(convention=BEHAVIOUR_MIRROR):
    """
    :param dict convention: Channel name to multiplier.
    :return: A one-line summary of what the convention flips.
    :rtype: str
    """

    flipped = sorted(name for name, sign in convention.items() if sign < 0)
    return 'flips {0}'.format(', '.join(flipped)) if flipped else 'flips nothing'


def convention_name(convention):
    """
    :param dict convention: Channel name to multiplier.
    :return: The name in :data:`CONVENTIONS` it matches, or ``'custom'``.
    :rtype: str
    """

    for name, known in CONVENTIONS.items():
        if dict(known) == dict(convention):
            return name
    return 'custom'
