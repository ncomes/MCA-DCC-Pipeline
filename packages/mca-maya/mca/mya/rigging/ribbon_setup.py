"""
A ribbon: a NURBS plane laid along a row of joints, for a rig to slide controls on.

A ribbon rig drives its joints from follicles riding a surface rather than from a chain of
constraints, which is what lets a spine or a limb bend smoothly and keep its volume. The surface has
to follow the joints it is replacing, and it has to be laid out so that each joint and each midpoint
between joints has a row of control points of its own - otherwise the surface cannot be shaped to
the skeleton it came from.

So this builds a plane with one CV row per joint plus one per midpoint, and places each row by hand:
a row is four CVs spread along the axis across the chain, worked out from each joint's own matrix
rather than from a world axis, so a chain that runs diagonally still gets a ribbon that lies flat
along it.

What was wrong before:

- **``find_primary_axis`` answered an upper-case axis letter and is now ``dag.get_primary_axis``,
  which answers a lower-case one.** The letter is used as an index into ``'XYZ'``, so it had to move
  with it. (The old function also read a node's first child whatever type it was, which is a crash on
  a joint with a shape under it; that was fixed when `dag` was ported.)
- **Fewer than three nodes gave the plane a negative number of patches.** ``patchesV`` is set to
  ``len(node_list) * 2 - 4``, which is -2 for one node and 0 for two, and Maya refuses both. Nothing
  said so.
- ``previous_pos`` was read inside a branch that only runs from the second node onwards and assigned
  at the bottom of the loop, so it worked by the order of the lines rather than by anything written
  down. Both running values start at None now.
- The plane was called ``nurbs_curve`` throughout, and the numbers that place the CVs - four per row,
  two and a half units apart - were in the arithmetic.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import pymaths
from mca.mya.utils import dag


logger = log.MCA_LOGGER

#: A default NURBS plane already has this many CV rows, which is why the patch count is short by it.
DEFAULT_CV_ROWS = 4

#: How many CVs make up one row across the ribbon, and how far apart they sit. Four rows two and a
#: half units apart puts them at -3.75, -1.25, 1.25 and 3.75 either side of the joint.
CVS_PER_ROW = 4
CV_SPACING = 2.5

#: The fewest joints a ribbon can be laid along: two rows per joint less the four a plane starts
#: with means three joints is the first count that asks for any patches at all.
MINIMUM_NODES = 3


def create_ribbon_along_nodes(node_list, name='ribbon'):
    """
    Build a NURBS plane laid along a row of nodes.

    :param list node_list: The nodes to lay it along, in order. Three or more.
    :param str name: A name for the plane.
    :return: The plane's transform, or None when there were too few nodes.
    :rtype: pm.nt.Transform or None
    """

    if not node_list or len(node_list) < MINIMUM_NODES:
        logger.warning('A ribbon needs at least %s nodes to lay along; %s were given.',
                       MINIMUM_NODES, len(node_list or []))
        return None

    ribbon, make_nurbs_node = pm.nurbsPlane(n=name)
    # One row per node and one per midpoint, less the rows a plane is born with.
    make_nurbs_node.patchesV.set(len(node_list) * 2 - DEFAULT_CV_ROWS)

    across_axis = None
    previous_vector = None
    previous_pos = None
    for index, node in enumerate(node_list):
        if across_axis is None:
            # The axis the chain runs down, from the first node; the ribbon's width runs across it.
            # dag.get_primary_axis answers a lower-case letter where rig_utils answered upper case.
            primary_axis, _ = dag.get_primary_axis(node)
            # Two steps on from the primary axis: x gives z, y gives x, z gives y.
            offset_index = ('xyz'.index(primary_axis) + 2) % 3
            across_axis = pm.dt.Vector([1 if axis == offset_index else 0 for axis in range(3)])

        current_pos = pm.xform(node, q=True, ws=True, t=True)

        # A point one unit across the chain in this node's own space, brought back to the world:
        # the direction a row of CVs should spread along here.
        node_matrix = pm.dt.TransformationMatrix(node.getMatrix(ws=True))
        node_matrix.addTranslation(across_axis, 'preTransform')
        offset_pos = node_matrix.getTranslation('world')
        across_vector = pymaths.normalize_vector(pymaths.sub_vectors(offset_pos, current_pos))

        if previous_vector is not None:
            # The midpoint row, averaged between this node's direction and the last one's, so the
            # ribbon turns smoothly through a bend rather than creasing at each joint.
            midpoint = pymaths.get_midpoint_between_points(previous_pos, current_pos)
            _place_cv_row(ribbon, index * 2 - 1, midpoint,
                          pymaths.average_vectors([across_vector, previous_vector]))

        _place_cv_row(ribbon, index * 2, current_pos, across_vector)
        previous_vector = across_vector[:]
        previous_pos = current_pos[:]

    return ribbon


def _place_cv_row(ribbon, row_index, centre, across_vector):
    """
    Put one row of CVs across a point.

    :param pm.nt.Transform ribbon: The plane being shaped.
    :param int row_index: Which row.
    :param centre: The world position the row is centred on.
    :param across_vector: The direction the row spreads along, normalised.
    """

    for cv_index in range(CVS_PER_ROW):
        # Centred on the point: for four CVs the offsets are -1.5, -0.5, 0.5 and 1.5 spacings.
        offset = (cv_index - (CVS_PER_ROW - 1) / 2.0) * CV_SPACING
        pm.move(ribbon.cv[cv_index][row_index],
                pymaths.add_vectors(centre, pymaths.scale_vector(across_vector, offset)))
