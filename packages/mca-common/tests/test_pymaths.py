"""
The arithmetic: float comparison, ranges, and vectors as lists of numbers.

    python tests/test_pymaths.py
"""

# python imports
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.utils import pymaths  # noqa: E402


def body(suite):
    # ---------------------------------------------------------------- #
    # is_equal: the tolerance that was not a tolerance
    # ---------------------------------------------------------------- #
    # fabs(x - y) < epsilon * fabs(x + y) * tolerance multiplies the caller's tolerance into
    # an epsilon-sized number. Every call site passes one, and every one got exact equality.
    suite.check('two numbers a tenth apart are equal within a fifth',
                pymaths.is_equal(0.9, 1.0, 0.2))
    suite.check('and are not equal within a twentieth',
                not pymaths.is_equal(0.9, 1.0, 0.05))
    old_answer = (math.fabs(0.9 - 1.0) < sys.float_info.epsilon * math.fabs(0.9 + 1.0) * 0.2
                  or math.fabs(0.9 - 1.0) < sys.float_info.epsilon)
    suite.check('which is the answer the old formula could not give',
                old_answer is False)
    suite.check('the same number is equal to itself, tolerance or no tolerance',
                pymaths.is_equal(1.0, 1.0) and pymaths.is_equal(0.0, 0.0))
    suite.check('a float that arrived by arithmetic is equal to the number it should be',
                pymaths.is_equal(0.1 + 0.2, 0.3))
    suite.check('and something a whole unit away is not',
                not pymaths.is_equal(1.0, 2.0))

    # ---------------------------------------------------------------- #
    # ranges
    # ---------------------------------------------------------------- #
    suite.check('clamp holds a number inside its range',
                pymaths.clamp(1.5) == 1.0 and pymaths.clamp(-2) == 0.0 and
                pymaths.clamp(5, 1, 10) == 5)
    suite.check('lerp walks from one number to the other',
                pymaths.lerp(0, 10, 0.25) == 2.5 and pymaths.lerp(10, 20, 1) == 20)
    suite.check('remap moves a value between two ranges',
                pymaths.remap_value(0.5, 0, 1, 0, 50) == 25)
    suite.check('and an empty old range answers the new bottom rather than raising',
                pymaths.remap_value(5, 3, 3, 100, 200) == 100)
    suite.check('sign is -1, 0 or 1, and always an integer',
                (pymaths.sign(-0.2), pymaths.sign(0.0), pymaths.sign(12)) == (-1, 0, 1) and
                all(isinstance(pymaths.sign(v), int) for v in (-0.2, 0.0, 12)))

    # ---------------------------------------------------------------- #
    # the rounding that measured a small vector as nothing
    # ---------------------------------------------------------------- #
    # get_vector_length rounded the sum of the squares to five places before the square root,
    # so anything shorter than about 0.0022 units came back as exactly zero - and normalising
    # it then divided by that zero.
    suite.check('a vector a thousandth of a unit long has a length',
                pymaths.is_equal(pymaths.get_vector_length([0.001, 0.0, 0.0]), 0.001),
                str(pymaths.get_vector_length([0.001, 0.0, 0.0])))
    suite.check('which the old rounding turned into nothing at all',
                math.sqrt(round(sum(x * x for x in [0.001, 0.0, 0.0]), 5)) == 0.0)
    suite.check('and normalising it answers a unit vector rather than dividing by zero',
                pymaths.is_equal(pymaths.get_vector_length(
                    pymaths.normalize_vector([0.001, 0.0, 0.0])), 1.0))
    suite.check('a three-four-five triangle measures five',
                pymaths.get_vector_length([3, 4, 0]) == 5.0)
    suite.check('and nothing is rounded on the way through a sum',
                pymaths.add_vectors([1e-7, 0, 0], [0, 0, 0]) == [1e-7, 0, 0],
                str(pymaths.add_vectors([1e-7, 0, 0], [0, 0, 0])))

    # ---------------------------------------------------------------- #
    # vectors
    # ---------------------------------------------------------------- #
    suite.check('vectors add, subtract and scale',
                pymaths.add_vectors([1, 2, 3], [4, 5, 6]) == [5, 7, 9] and
                pymaths.sub_vectors([4, 5, 6], [1, 2, 3]) == [3, 3, 3] and
                pymaths.scale_vector([1, 2, 3], 2) == [2, 4, 6])
    suite.check('two vectors of different lengths are refused, not quietly truncated',
                'different lengths' in suite.raises('adding a 3d to a 2d raises',
                                                    pymaths.add_vectors, [1, 2, 3], [1, 2]))
    suite.check('a zero-length vector normalises to zeros rather than raising',
                pymaths.normalize_vector([0, 0, 0]) == [0.0, 0.0, 0.0])
    suite.check('averaging vectors averages each component',
                pymaths.average_vectors([[0, 0, 0], [2, 4, 6]]) == [1, 2, 3])
    suite.check('and averaging none of them answers nothing, not IndexError',
                pymaths.average_vectors([]) == [])
    suite.check('the dot product says how much two vectors agree',
                pymaths.get_dot_product([1, 0, 0], [1, 0, 0]) == 1 and
                pymaths.get_dot_product([1, 0, 0], [0, 1, 0]) == 0)
    suite.check('the cross product is right-handed',
                pymaths.get_cross_product([1, 0, 0], [0, 1, 0]) == [0, 0, 1])
    suite.check('and is refused for anything that is not two 3d vectors',
                '3d' in suite.raises('a 2d cross product raises',
                                     pymaths.get_cross_product, [1, 0], [0, 1]))

    # ---------------------------------------------------------------- #
    # points: the undocumented direction
    # ---------------------------------------------------------------- #
    # get_midpoint_between_points measured its scale from pt2 back towards pt1, which its
    # docstring did not mention because the parameter was not documented.
    suite.check('halfway between two points is halfway, as it always was',
                pymaths.get_midpoint_between_points([0, 0, 0], [10, 0, 0]) == [5, 0, 0])
    suite.check('a quarter of the way counts from the first point now',
                pymaths.get_midpoint_between_points([0, 0, 0], [10, 0, 0], 0.25) == [2.5, 0, 0],
                str(pymaths.get_midpoint_between_points([0, 0, 0], [10, 0, 0], 0.25)))
    suite.check('so 0 is the first point and 1 is the second',
                pymaths.get_midpoint_between_points([1, 2, 3], [9, 9, 9], 0) == [1, 2, 3] and
                pymaths.get_midpoint_between_points([1, 2, 3], [9, 9, 9], 1) == [9, 9, 9])
    suite.check('the distance between two points is the length of the line',
                pymaths.get_distance_between_points([0, 0, 0], [0, 3, 4]) == 5.0)
    suite.check('and it does not care which way round they are',
                pymaths.get_distance_between_points([0, 3, 4], [0, 0, 0]) == 5.0)

    # ---------------------------------------------------------------- #
    # the plane a limb bends on
    # ---------------------------------------------------------------- #
    shoulder, elbow, wrist = [10.0, 100.0, 0.0], [10.0, 80.0, 5.0], [10.0, 60.0, 0.0]
    up = pymaths.get_planar_up(shoulder, elbow, wrist)
    suite.check('a limb\'s up vector is one unit long',
                pymaths.is_equal(pymaths.get_vector_length(up), 1.0), str(up))
    suite.check('and at right angles to the limb itself',
                pymaths.is_equal(pymaths.get_dot_product(up, pymaths.sub_vectors(wrist, elbow)),
                                 0.0, 1e-6),
                str(pymaths.get_dot_product(up, pymaths.sub_vectors(wrist, elbow))))
    mirrored = pymaths.get_planar_up([-10.0, 100.0, 0.0], [-10.0, 80.0, 5.0], [-10.0, 60.0, 0.0])
    suite.check('a chain on the other side of the grid answers the other way, as the rigs '
                'were built to expect',
                all(pymaths.is_equal(a, -b, 1e-6) for a, b in zip(up, mirrored)),
                '{0} vs {1}'.format(up, mirrored))

    # ---------------------------------------------------------------- #
    # random numbers: int_only had never run
    # ---------------------------------------------------------------- #
    # random.randint([low, high]) is one argument where two go, so it raised TypeError every
    # time it was asked for whole numbers.
    whole = pymaths.create_random_list((0, 10), 5, int_only=True)
    suite.check('asking for whole numbers gives whole numbers, rather than TypeError',
                len(whole) == 5 and all(isinstance(v, int) for v in whole), str(whole))
    suite.check('and they are inside the range asked for',
                all(0 <= v <= 10 for v in whole), str(whole))
    floats = pymaths.create_random_list()
    suite.check('the default is three numbers between zero and one',
                len(floats) == 3 and all(0.0 <= v <= 1.0 for v in floats), str(floats))
    suite.check('and a length of one is one number',
                len(pymaths.create_random_list(length=1)) == 1)


if __name__ == '__main__':
    sys.exit(harness.run('pymaths', body))
