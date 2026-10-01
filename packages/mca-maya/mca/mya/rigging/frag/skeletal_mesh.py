"""
The node that owns a rig's meshes.

One of these sits directly under the rig's root. It builds the two groups a rig's geometry lives in
(``grp_skins`` for the skinned meshes and ``grp_blendshapes`` for the shapes that drive a face),
gathers the rig's meshes under them, and records which variant of the asset's geometry it was built
for.

What was wrong before:

- **The variant a rig was built for has never been recorded on the node.** ``create`` adds a
  ``variant`` attribute and never writes to it, and sets ``variantVersion`` to the literal ``1``
  rather than to the ``variant_version`` it was given. Both arguments go into ``buildKwargs``
  correctly, so the information is not lost - but every rig in the depot reads variant ``''`` at
  version 1 on the attributes meant to hold them, and anything asking the node which variant it is
  gets nothing.
- **Building a rig gathered every mesh in the scene, not the rig's own.**
  ``get_all_meshes_from_scene`` looks at ``pm.ls(type=pm.nt.Mesh)`` with no regard for the
  namespace, while ``get_blendshapes_from_scene`` sitting beside it works through the rig's markup
  and is namespace-aware. So building a rig in a scene that had anything else in it - another
  character, a prop, a reference - took the other thing's geometry and parented it into this rig's
  ``grp_skins``. The meshes are the rig's namespace's now, and the function that answers them says
  so.
- **``get_frag_skeletal_mesh`` answered two different kinds of thing.** Down one path it wraps the
  node it found and down the other it hands back the raw ``fragParent`` connection, so a caller
  could not know whether it had a ``SkeletalMesh`` or a network node. Its docstring also said it
  returns a ``FRAGRig``. It raised, too, on a node whose ``fragParent`` exists but is connected to
  nothing - ``FRAGNode(None)`` gets as far as ``pm.PyNode(None)``.
- **``get_group_skins`` and ``get_group_blendshapes`` reached into the rig root without checking
  there was one**, so asking either about a node that is not in a rig raised ``AttributeError``
  rather than answering nothing.
- ``get_grp_skins`` assigned ``has_attribute('grpSkins')`` - a bool - to a variable called
  ``skins_grp`` and then ignored it. The ``'SkeletalMesh'`` in ``get_frag_skeletal_mesh``'s hunt for
  the group was a bare string in the middle of a comprehension.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import mesh_markup_rig
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import frag_root
from mca.mya.utils import attr_utils
from mca.mya.utils import dag
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The group the rig's skinned meshes are parented under, and the attribute pointing at it.
GRP_SKINS = 'grp_skins'
GRP_SKINS_ATTR = 'grpSkins'

#: The group the meshes that drive a face are parented under, and the attribute pointing at it.
GRP_BLENDSHAPES = 'grp_blendshapes'
GRP_BLENDSHAPES_ATTR = 'grpBlendshapes'

#: What each group carries to say which of the two it is, for anything looking from the outside.
IS_GRP_SKINS_ATTR = 'isGrpSkins'
IS_GRP_BLENDSHAPES_ATTR = 'isGrpBlendshapes'

#: Which variant of the asset's geometry the rig was built for, and its version.
VARIANT_ATTR = 'variant'
VARIANT_VERSION_ATTR = 'variantVersion'

#: The category in the rig's mesh markup that holds the shapes driving a face.
BLENDSHAPE_MESH_REGION = 'blendshape_mesh'


def _in_namespace(node, node_namespace):
    """
    Whether a node sits in a particular namespace.

    :param pm.PyNode node: The node to ask about.
    :param str node_namespace: The namespace, as ``PyNode.namespace()`` answers it - with its
    trailing
        colon, or empty for the scene's own.
    :return: Whether it does.
    :rtype: bool
    """

    return node.namespace() == node_namespace


class SkeletalMesh(frag_base.FRAGNode):
    """
    The node holding a rig's geometry: the two groups it lives in, and which variant it is.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, variant='default', variant_version=1):
        """
        Build the node and gather the rig's meshes under its two groups.

        :param FRAGNode frag_parent: The rig's root, which this hangs under.
        :param str variant: Which variant of the asset's geometry the rig is being built for.
        :param int variant_version: The version of that variant.
        :return: The node.
        :rtype: SkeletalMesh
        :raises AttributeError: When the parent is not the rig's root.
        """

        if not frag_parent.pynode.hasAttr(frag_base.IS_FRAG_ROOT_ATTR):
            raise AttributeError('{0} is not a FRAG root, so a skeletal mesh cannot hang under '
                                 'it.'.format(frag_parent))

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        # set_namespace rather than pm.namespace(set=...): a bare relative name is resolved
        # against whatever namespace is active, so building this while the active namespace was
        # already the rig's raised 'No namespace matches name'. set_namespace goes to the root
        # first.
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(frag_parent, SkeletalMesh.__name__, SkeletalMesh.VERSION)

        # What it was built with, for a rebuild to read back.
        attr_utils.set_compound_attribute_groups(node.pynode, 'buildKwargs',
                                                 {'variant': variant,
                                                  'variant_version': variant_version})

        node.pynode.addAttr(GRP_SKINS_ATTR, at='message')
        node.pynode.addAttr(GRP_BLENDSHAPES_ATTR, at='message')
        # The arguments, on the attributes meant to hold them. The version before added `variant`
        # and never wrote to it, and set `variantVersion` to a literal 1.
        node.pynode.addAttr(VARIANT_ATTR, dt='string')
        node.pynode.attr(VARIANT_ATTR).set(variant)
        node.pynode.addAttr(VARIANT_VERSION_ATTR, at='double')
        node.pynode.attr(VARIANT_VERSION_ATTR).set(variant_version)

        for group_name, group_attr, marker_attr in (
                (GRP_SKINS, GRP_SKINS_ATTR, IS_GRP_SKINS_ATTR),
                (GRP_BLENDSHAPES, GRP_BLENDSHAPES_ATTR, IS_GRP_BLENDSHAPES_ATTR)):
            group_node = pm.group(empty=True, n=group_name)
            # The meshes carry their own place in the world; the group is only a place to put them.
            group_node.inheritsTransform.set(0)
            group_node.addAttr(marker_attr, at='bool', dv=True)
            node.connect_node(group_node, group_attr, frag_base.FRAG_PARENT_ATTR)

        meshes = node.get_meshes_w_grps()
        if meshes:
            pm.parent(meshes, node.get_grp_skins())

        blendshape_meshes = node.get_blendshapes_from_scene()
        if blendshape_meshes:
            pm.parent(blendshape_meshes, node.get_grp_blendshapes())

        return node

    # ----------------------------------------------------------------------------------- #
    # the groups
    # ----------------------------------------------------------------------------------- #
    def get_grp_skins(self):
        """
        :return: The group the rig's skinned meshes are under, or None when it has none.
        :rtype: pm.nt.Transform or None
        """

        if not self.has_attribute(GRP_SKINS_ATTR):
            logger.warning('%s has no skins group connected to it.', self.pynode)
            return None
        return self.pynode.attr(GRP_SKINS_ATTR).get()

    def get_grp_blendshapes(self):
        """
        :return: The group the meshes that drive a face are under, or None when it has none. A rig
            built with no blendshapes has this group deleted by ``FRAGRig.create``, so the attribute
            can be there with nothing on the end of it.
        :rtype: pm.nt.Transform or None
        """

        if not self.has_attribute(GRP_BLENDSHAPES_ATTR):
            logger.warning('%s has no blendshape group connected to it.', self.pynode)
            return None
        return self.pynode.attr(GRP_BLENDSHAPES_ATTR).get()

    # ----------------------------------------------------------------------------------- #
    # which variant
    # ----------------------------------------------------------------------------------- #
    @property
    def variant(self):
        """
        :return: Which variant of the asset's geometry the rig was built for.
        :rtype: str
        """

        return self.pynode.attr(VARIANT_ATTR).get()

    @property
    def variant_version(self):
        """
        :return: The version of that variant.
        :rtype: float
        """

        return self.pynode.attr(VARIANT_VERSION_ATTR).get()

    # ----------------------------------------------------------------------------------- #
    # finding the meshes
    # ----------------------------------------------------------------------------------- #
    def get_all_meshes_from_scene(self):
        """
        Every mesh in this rig's namespace.

        The namespace matters: a build that took every mesh in the scene took another character's
        geometry with it, which is what this did.

        :return: The transforms holding them, joints left out.
        :rtype: list(pm.nt.Transform)
        """

        node_namespace = self.pynode.namespace()
        transforms = set()
        for mesh_shape in pm.ls(type=pm.nt.Mesh):
            mesh_transform = mesh_shape.getParent()
            if mesh_transform is None:
                continue
            if not isinstance(mesh_transform, pm.nt.Transform) or isinstance(mesh_transform,
                                                                            pm.nt.Joint):
                continue
            if not _in_namespace(mesh_transform, node_namespace):
                continue
            transforms.add(mesh_transform)
        return list(transforms)

    def get_blendshapes_from_scene(self):
        """
        The meshes this rig's markup calls blendshape meshes.

        :return: The meshes.
        :rtype: list(pm.nt.Transform)
        """

        markups = mesh_markup_rig.RigMeshMarkup.create(self.pynode.namespace())
        return markups.get_mesh_list_in_region(BLENDSHAPE_MESH_REGION)

    def get_meshes_w_grps(self):
        """
        The top of each hierarchy that holds one of this rig's meshes.

        Not the meshes themselves: whatever a mesh is under comes with it, so the groups an artist
        built around their geometry survive the gathering. A mesh parented under a joint therefore
        brings the whole skeleton, which is what the suite for this module pins down.

        :return: The topmost parent of each mesh, or the mesh itself when it has no parent.
        :rtype: list(pm.nt.Transform)
        """

        tops = set()
        for mesh_transform in self.get_all_meshes_from_scene():
            all_parents = mesh_transform.getAllParents()
            tops.add(all_parents[-1] if all_parents else mesh_transform)
        return list(tops)


def get_frag_skeletal_mesh(node):
    """
    The skeletal mesh node of the rig something belongs to.

    :param node: Anything in a rig: one of its metadata nodes, or any node in its hierarchy.
    :return: The skeletal mesh node, wrapped, or None when there is not one to find. The version
        before answered a wrapped node down one path and a raw network node down the other.
    :rtype: SkeletalMesh or None
    """

    node = frag_base.as_pynode(node)

    if node.hasAttr(frag_base.FRAG_PARENT_ATTR):
        frag_parent = node.attr(frag_base.FRAG_PARENT_ATTR).get()
        if frag_parent is None:
            logger.warning('%s has a %s attribute with nothing on the end of it.',
                           node, frag_base.FRAG_PARENT_ATTR)
            return None
        root_node = frag_root.get_frag_root(frag_parent)
        return root_node.get_skeletal_mesh() if root_node else None

    # Not one of the metadata nodes, so climb the hierarchy to the top and look for the group that
    # says which skeletal mesh node owns it.
    all_grp = dag.get_absolute_parent(node)
    for child_node in all_grp.getChildren():
        if not child_node.hasAttr(IS_GRP_SKINS_ATTR):
            continue
        skeletal_mesh_node = child_node.attr(frag_base.FRAG_PARENT_ATTR).get()
        if skeletal_mesh_node is not None:
            return frag_base.wrap_frag_node(skeletal_mesh_node)

    logger.warning('Nothing above %s connects it to a FRAG skeletal mesh node.', node)
    return None


def get_group_skins(node):
    """
    The group the skinned meshes of the rig something belongs to are under.

    :param node: Anything in a rig.
    :return: The group, or None when the node is not in a rig or the rig has no skeletal mesh node.
    :rtype: pm.nt.Transform or None
    """

    root_node = frag_root.get_frag_root(node)
    if root_node is None:
        logger.warning('%s is not in a rig, so there is no skins group to find.', node)
        return None

    skeletal_mesh_node = root_node.get_skeletal_mesh()
    return skeletal_mesh_node.get_grp_skins() if skeletal_mesh_node else None


def get_group_blendshapes(node):
    """
    The group the blendshape meshes of the rig something belongs to are under.

    :param node: Anything in a rig.
    :return: The group, or None when the node is not in a rig or the rig has no skeletal mesh node.
    :rtype: pm.nt.Transform or None
    """

    root_node = frag_root.get_frag_root(node)
    if root_node is None:
        logger.warning('%s is not in a rig, so there is no blendshape group to find.', node)
        return None

    skeletal_mesh_node = root_node.get_skeletal_mesh()
    return skeletal_mesh_node.get_grp_blendshapes() if skeletal_mesh_node else None
