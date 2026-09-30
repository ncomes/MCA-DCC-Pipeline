"""
The dotted line a rig draws between two things, so an animator can see what is pointing at what.

A pole vector control sits out in space with nothing to say which joint it belongs to, so a rig
draws a line from the knee to it. The line is a two-point curve with a cluster on each end, each
cluster point constrained to one of the two objects, and the curve's shape set to template so it
cannot be selected or picked up by a lasso.

It lives here rather than in ``utils/`` because it is built out of clusters, and a leaf utility that
reaches into the deformation code is what ``utils/dag.py`` was cleaned of: it had a second copy of
this function, and dropping it took ``utils/dag.py``'s import of ``deformations.cluster`` with it.

What was wrong before:

- **There were two copies of this**, one in ``rig_utils`` and one in ``utils/dag.py``, identical
  except for a docstring line. All three callers used the ``rig_utils`` one.
- **Both docstrings said either argument could be a name**, and both called
  ``obj_a.getTranslation(space='world')`` on it straight away - an ``AttributeError`` on a string.
- Every caller then walked the curve's shape connections itself to find the two clusters back
  again, because the function only answered the curve. That walk is :func:`get_line_clusters` now.
- ``overrideDisplayType`` 1 and ``overrideColor`` 3 were numbers in the arithmetic, and each caller
  set ``inheritsTransform`` off a second time after the call because it is not obvious from the
  outside that this already does.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.mya.deformations import cluster
from mca.mya.utils import naming


#: Maya's override display types. Template geometry is drawn but cannot be selected.
DISPLAY_TYPE_TEMPLATE = 1

#: Maya's colour index for grey, which is what a guide line is drawn in.
COLOUR_INDEX_GREY = 3


def create_line_between(obj_a, obj_b, name=None):
    """
    Draw a live line between two objects.

    :param obj_a: One end, as a transform or its name.
    :param obj_b: The other end.
    :param str name: A name for the curve; its two clusters take it with ``_a`` and ``_b`` on the
        end. None leaves the curve with the name Maya gave it.
    :return: The curve's transform. Its clusters are parented under it, hidden, and can be found
        again with :func:`get_line_clusters`.
    :rtype: pm.nt.Transform
    """

    obj_a = pm.PyNode(obj_a)
    obj_b = pm.PyNode(obj_b)

    line = pm.curve(degree=1, point=[obj_a.getTranslation(space='world'),
                                     obj_b.getTranslation(space='world')],
                    knot=[0, 1])
    line_name = name or naming.get_basename(line)

    _, cluster_a = cluster.create_cluster_from_component_names(line.cv[0],
                                                              '{0}_a'.format(line_name))
    _, cluster_b = cluster.create_cluster_from_component_names(line.cv[1],
                                                              '{0}_b'.format(line_name))
    pm.parent([cluster_a, cluster_b], line)

    # The line is driven entirely by its clusters, and the clusters entirely by the two objects, so
    # nothing in the line's hierarchy should move any of the three - otherwise the offset is counted
    # twice and the line drifts off its own ends.
    for node in (line, cluster_a, cluster_b):
        node.inheritsTransform.set(0)
    cluster_a.hide()
    cluster_b.hide()

    pm.pointConstraint(obj_a, cluster_a, w=1, mo=1)
    pm.pointConstraint(obj_b, cluster_b, w=1, mo=1)

    line_shape = line.getShape()
    line_shape.overrideEnabled.set(1)
    line_shape.overrideDisplayType.set(DISPLAY_TYPE_TEMPLATE)
    line_shape.overrideColor.set(COLOUR_INDEX_GREY)

    # Last, rather than in pm.curve's call: renaming the curve after its clusters exist is what
    # keeps a namespace out of the middle of their names.
    if name:
        line.rename(name)
    line.getShape().rename('{0}Shape'.format(line_name))

    return line


def get_line_clusters(line):
    """
    The clusters driving a line's two ends.

    :param line: The curve :func:`create_line_between` answered, or its shape.
    :return: The clusters, without repeats. A cluster shows up once per shape it deforms.
    :rtype: list(pm.nt.Cluster)
    """

    line = pm.PyNode(line)
    shapes = [line] if isinstance(line, pm.nt.NurbsCurve) else line.listRelatives(shapes=True)

    line_clusters = []
    for shape in shapes:
        for cluster_node in shape.listConnections(type=pm.nt.Cluster):
            if cluster_node not in line_clusters:
                line_clusters.append(cluster_node)
    return line_clusters
