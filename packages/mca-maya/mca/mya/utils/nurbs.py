"""
Module that contains Maya Animation Flag functions
"""

# python imports
# software specific imports
# MCA python imports


def get_curve_data(shape_node):
    """
    Internal function that retrieves the curve data from the given shape node.

    :param pm.Shape shape_node: flag curve shape node.
    :return: dictionary containing all the curve shape data.
    :rtype: dict
    """

    curve_data = {'knots': tuple(shape_node.getKnots()),
                  'cvs': tuple(map(tuple, shape_node.getCVs('world'))),
                  'degree': shape_node.degree(),
                  'form': int(shape_node.form())}

    return curve_data

