"""
Building clusters.

A cluster is Maya's simplest deformer: a set of points and a handle that moves them. Rigging uses
them for the small live setups a rig needs - the guide line between a knee and its pole vector
control, for one - where what is wanted is a shape that follows two things about.

What was wrong before:

- **Building a cluster with a namespace active raised ``TypeError``.** Clusters are built in the
  root namespace here on purpose, and then renamed into the namespace that was active - but the
  rename was written ``pm.rename('{0}{1}'.format(current_namespace, cluster))``, one argument where
  ``pm.rename`` wants the node and its new name. It raises rather than renaming anything. So
  anything that built a cluster inside a namespace - which is how a referenced rig is rebuilt -
  raised on the way, and the IK chain's pole vector guide line is built out of two of them.
- **And the name it was building was wrong.** ``namespaceInfo(absoluteName=True)`` answers ``:ns``
  with no trailing colon, so joining it to the node name gave ``:nsmy_cluster`` rather than
  ``:ns:my_cluster``.
- **A cluster asked for over no points was built anyway, deforming nothing.** ``pm.cluster([])``
  does not refuse: it makes a cluster node and a handle that are connected to no geometry at all and
  says nothing about it. A guide line built that way would never follow either of its ends. Asking
  for one now refuses.
- The two ``pm.cluster`` calls were the same line twice, differing in one keyword.
- The module docstring said "Parameter data for working with the facial rigs", which is neither what
  this is nor what it does, and it imported ``mca.mya.utils.namespace`` without using it.
"""

# python imports

# software specific imports
import pymel.core as pm


#: The namespace a cluster is built in, whatever namespace the caller is working in.
ROOT_NAMESPACE = ':'


def create_cluster_from_component_names(points, name, relative=False, front_of_chain=True,
                                        exclusive=False):
    """
    Build a cluster over some CVs or vertices.

    :param points: The points to deform, as components or their names.
    :param str name: A name for the cluster.
    :param bool relative: Move the points by the handle's own transform only, ignoring everything
        above it.
    :param bool front_of_chain: Put the cluster at the front of the shape's deformation chain.
    :param bool exclusive: Put the cluster's set in a partition, so a point can only be deformed by
        one cluster. Left off by default, and not passed to Maya at all when it is off: Maya 2019
        turned exclusivity on whenever the flag was present, whatever it was set to.
    :return: The cluster node and its handle.
    :rtype: tuple(pm.nt.Cluster, pm.nt.Transform)
    :raises ValueError: When there are no points to build over.
    """

    # An empty list is not refused by Maya: it builds a cluster and a handle connected to no
    # geometry at all, and says nothing. Whatever asked for it wanted points.
    if points is None or (isinstance(points, (list, tuple, set)) and not points):
        raise ValueError(
            'There are no points to build the cluster {0} over.'.format(name))

    # Maya 2019 and older raise `RuntimeError: Problems occurred with dependency graph setup` from
    # pm.cluster when a namespace is active, so a cluster is built in the root namespace and renamed
    # into the caller's afterwards. Maya 2025 does not need this - a cluster built inside a
    # namespace comes out correctly named - but the oldest Maya the pipeline supports is 2022, which
    # has not been checked, so the detour stays until it has been.
    current_namespace = pm.namespaceInfo(currentNamespace=True, absoluteName=True)
    build_in_root = current_namespace != ROOT_NAMESPACE

    if build_in_root:
        pm.namespace(setNamespace=ROOT_NAMESPACE)

    cluster_kwargs = {'n': name, 'relative': relative, 'frontOfChain': front_of_chain}
    if exclusive:
        cluster_kwargs['exclusive'] = True

    try:
        cluster_node, cluster_handle = pm.cluster(points, **cluster_kwargs)
    finally:
        if build_in_root:
            pm.namespace(setNamespace=current_namespace)

    if build_in_root:
        # With the node and the new name, and with the colon the absolute namespace name does not
        # carry. One argument, which is how this was written, raises.
        for node in (cluster_node, cluster_handle):
            pm.rename(node, '{0}:{1}'.format(current_namespace.rstrip(':'), node.nodeName()))

    return cluster_node, cluster_handle
