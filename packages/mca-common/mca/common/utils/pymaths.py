"""
Plain arithmetic: comparing floats, ranges, and small vectors as tuples of numbers.

A leaf - it imports nothing but the standard library, so a DCC, a test and a farm job all get
the same answers. A vector here is any sequence of numbers, and every function answers a new
list rather than changing what it was given.

Nothing rounds. The version this replaces rounded every vector it produced to five decimal
places, which read as tidiness and cost accuracy - and in one place cost it entirely:
``get_vector_length`` rounded the *sum of the squares* before taking the square root, so any
vector shorter than about 0.0022 units measured as exactly zero, and normalising it divided by
that zero. Face rigs work at that scale.
"""

# python imports
import math
import random


#: How close two floats have to be, absolutely, before :func:`is_equal` calls them equal.
#: About a millionth of a millimetre in Maya's centimetres - closer than any rig cares about.
TOLERANCE = 1e-9


# =====================================================================================================================
# SCALAR
# =====================================================================================================================

def is_equal(x, y, tolerance=TOLERANCE):
    """
    Whether two floats are close enough to be treated as the same number.

    :param float x: One value.
    :param float y: The other.
    :param float tolerance: How far apart they may be. An absolute distance: ``0.01`` means a
        hundredth, which is what everyone who calls this has always assumed.
    :return: True when they are within the tolerance of each other.
    :rtype: bool

    The version this replaces read::

        fabs(x - y) < sys.float_info.epsilon * fabs(x + y) * tolerance or fabs(x - y) < epsilon

    which multiplies the tolerance *into* an epsilon-sized number, so the tolerance argument
    did nothing a caller would recognise: with ``tolerance=2`` the two values still had to be
    within 4.4e-16 of each other. Every call site in the framework passes a tolerance, and
    every one of them has been getting exact equality.
    """

    return math.isclose(x, y, rel_tol=1e-9, abs_tol=abs(tolerance))


def clamp(number, min_value=0.0, max_value=1.0):
    """
    Hold a number inside a range.

    :param float number: The value.
    :param float min_value: The lowest it may be.
    :param float max_value: The highest it may be.
    :return: The value, brought inside the range.
    :rtype: float
    """

    return max(min(number, max_value), min_value)


def lerp(start, end, alpha):
    """
    Walk from one value to another.

    :param float start: Where ``alpha`` 0 lands.
    :param float end: Where ``alpha`` 1 lands.
    :param float alpha: How far along, 0 to 1. Outside that range it keeps going.
    :return: The value there.
    :rtype: float
    """

    return start + alpha * (end - start)


def remap_value(value, old_min, old_max, new_min, new_max):
    """
    Move a value from one range into another.

    :param float value: The value, measured in the old range.
    :param float old_min: The old range's bottom.
    :param float old_max: The old range's top.
    :param float new_min: The new range's bottom.
    :param float new_max: The new range's top.
    :return: The value in the new range. When the old range is empty - the two ends the same
        number - the answer is ``new_min``, where the old version raised ZeroDivisionError.
    :rtype: float
    """

    span = old_max - old_min
    if not span:
        return new_min

    return new_min + ((value - old_min) * (new_max - new_min)) / span


def sign(value):
    """
    Which way a number points.

    :param float value: The value.
    :return: -1, 0 or 1, always an integer - the old version answered ``0.0`` for ``0.0``
        and ``0`` for ``0``, so ``sign(x) is 0`` depended on the caller's type.
    :rtype: int
    """

    if value > 0:
        return 1
    if value < 0:
        return -1

    return 0


# =====================================================================================================================
# VECTORS AND POINTS
# =====================================================================================================================

def add_vectors(v1, v2):
    """
    :param v1: A vector.
    :param v2: Another, of the same length.
    :return: Their sum.
    :rtype: list[float]
    """

    _same_length(v1, v2)

    return [a + b for a, b in zip(v1, v2)]


def sub_vectors(v1, v2):
    """
    :param v1: A vector.
    :param v2: Another, of the same length.
    :return: ``v1`` less ``v2``.
    :rtype: list[float]
    """

    _same_length(v1, v2)

    return [a - b for a, b in zip(v1, v2)]


def scale_vector(v1, scale):
    """
    :param v1: A vector.
    :param float scale: What to multiply every component by.
    :return: The scaled vector.
    :rtype: list[float]
    """

    return [component * scale for component in v1]


def average_vectors(vector_list):
    """
    :param vector_list: Vectors, all the same length.
    :return: Their average, component by component. ``[]`` for no vectors at all, where the
        old version raised IndexError on the first line.
    :rtype: list[float]
    """

    if not vector_list:
        return []

    total = list(vector_list[0])
    for vector in vector_list[1:]:
        total = add_vectors(total, vector)

    return scale_vector(total, 1.0 / len(vector_list))


def get_vector_length(v1):
    """
    :param v1: A vector.
    :return: How long it is.
    :rtype: float
    """

    return math.sqrt(sum(component * component for component in v1))


def normalize_vector(v1):
    """
    :param v1: A vector.
    :return: The same direction, one unit long. A zero-length vector answers itself - all
        zeros - rather than raising ZeroDivisionError halfway through a rig build.
    :rtype: list[float]
    """

    length = get_vector_length(v1)
    if not length:
        return [0.0 for _ in v1]

    return [component / length for component in v1]


def get_dot_product(v1, v2):
    """
    :param v1: A vector.
    :param v2: Another, of the same length.
    :return: Their dot product: how much they point the same way.
    :rtype: float
    """

    _same_length(v1, v2)

    return sum(a * b for a, b in zip(v1, v2))


def get_cross_product(v1, v2):
    """
    :param v1: A 3d vector.
    :param v2: Another.
    :return: A vector at right angles to both.
    :rtype: list[float]
    :raises ValueError: For anything but two three-component vectors. The old version ran its
        modulo arithmetic over whatever length it was handed and answered confident nonsense.
    """

    if len(v1) != 3 or len(v2) != 3:
        raise ValueError('A cross product needs two 3d vectors, not {0} and {1} components.'.format(
            len(v1), len(v2)))

    return [v1[1] * v2[2] - v1[2] * v2[1],
            v1[2] * v2[0] - v1[0] * v2[2],
            v1[0] * v2[1] - v1[1] * v2[0]]


def get_midpoint_between_points(pt1, pt2, scale=0.5):
    """
    A point on the line between two points.

    :param pt1: Where ``scale`` 0 lands.
    :param pt2: Where ``scale`` 1 lands.
    :param float scale: How far from ``pt1`` towards ``pt2``. Halfway by default, which is
        what the name says and what almost every caller wants.
    :return: The point.
    :rtype: list[float]

    The version this replaces measured ``scale`` from ``pt2`` back towards ``pt1``, which
    nothing in its docstring mentioned - the parameter was not documented at all. At the
    default 0.5 the two agree, so only a caller passing a scale is affected:
    ``skel_utils.position_twist_joints`` is the one, and it has to swap its two points when
    it is ported.
    """

    return add_vectors(pt1, scale_vector(sub_vectors(pt2, pt1), scale))


def get_distance_between_points(pt1, pt2):
    """
    :param pt1: A point.
    :param pt2: Another.
    :return: How far apart they are.
    :rtype: float

    Two places in ``buildarig`` call this ``find_distance_between_points``, which has never
    existed under that name - so working out a rig's scale from its skeleton's bounding box
    has always raised AttributeError. Those call sites get the real name when buildarig is
    ported.
    """

    return get_vector_length(sub_vectors(pt2, pt1))


def get_planar_up(pt1, pt2, pt3):
    """
    An up vector for the plane three points sit on - a limb's, usually.

    :param pt1: First point in the chain.
    :param pt2: Second, the one the plane bends at.
    :param pt3: Third.
    :return: A unit vector at right angles to the plane.
    :rtype: list[float]

    Which side the answer comes out on is chosen from the midpoint's world position, so a
    chain on the left of the grid and the same chain on the right answer opposite ways. That
    is what the rigs were built against - it is marked ``$HACK`` in the original, and it
    stays until there is a rig to test a better rule on.
    """

    pt_mid = get_midpoint_between_points(pt1, pt3)

    mid_is_right = pt_mid[0] > 0
    mid_is_behind = pt_mid[2] > pt2[2]
    if mid_is_right == mid_is_behind:
        v_to_center = sub_vectors(pt_mid, pt2)
    else:
        v_to_center = sub_vectors(pt2, pt_mid)

    v_center_to_end = sub_vectors(pt3, pt2)

    return normalize_vector(get_cross_product(v_to_center, v_center_to_end))


def create_random_list(min_max=(0.0, 1.0), length=3, int_only=False):
    """
    A list of random numbers, for a colour or a jitter.

    :param min_max: The range, low then high.
    :param int length: How many.
    :param bool int_only: Whole numbers.
    :return: The numbers.
    :rtype: list

    ``int_only=True`` called ``random.randint([low, high])`` - one list where two numbers go -
    so it raised TypeError every time, which is to say it has never once run.
    """

    low, high = min_max if min_max else (0.0, 1.0)
    length = length if length is not None else 3

    if int_only:
        return [random.randint(int(round(low)), int(round(high))) for _ in range(length)]

    return [random.uniform(low, high) for _ in range(length)]


def _same_length(v1, v2):
    """
    Refuse two vectors that are not the same size.

    :param v1: A vector.
    :param v2: Another.
    :raises ValueError: When they differ. ``zip`` stops at the shorter one, so adding a 3d
        point to a 2d one used to answer a 2d point and say nothing.
    """

    if len(v1) != len(v2):
        raise ValueError('These vectors are different lengths: {0} and {1}.'.format(len(v1), len(v2)))
