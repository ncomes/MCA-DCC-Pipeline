"""
The node at the top of one asset's rig.

Everything else in a rig hangs under one of these. It holds which asset the rig was built for - the
type, the registry id and the asset's name - and it is the node that carries the skeleton's root
joint, so a rig can be found from any joint in it and a joint can be found from any part of the rig.

What was wrong before:

- **``get_root_joint`` raised on anything that is not in a rig.** It finds the root and then reads
  ``root_joint`` off it without checking there was one, so asking about a loose joint gave
  ``AttributeError: 'NoneType' object has no attribute 'root_joint'``.
- **An asset id the registry does not know became the name ``'missing_name'`` in silence.** That is
a
  reasonable thing to store, and no reason not to say which id it was.
- **``get_all_frag_roots`` stopped on the first node it could not wrap.** It wraps everything with
an
  ``isFragRoot`` attribute set, and a node from a pre-FRAG rig or from a project whose packages are
  not loaded cannot be wrapped - so one of those in a scene and the walk raised rather than
  answering the roots it did find. ``get_frag_root_by_assetid`` next to it also read ``assetID`` off
  whatever it found without checking the attribute was there.
- **``get_frag_root`` was the same walk as ``FRAGNode.get_frag_root``, written twice.** The two
differ
  in how they recognise a root: this one asks whether the node is a ``FRAGRoot``, and the one on
  ``FRAGNode`` - which cannot import this module, because this module is built on it - asks whether
  it carries ``isFragRoot``. Since ``FRAGRoot`` is the only thing in the pipeline that adds that
  attribute, the two answer the same for every rig; this one does the walk once, through the base,
  and then says whether what came back really is a ``FRAGRoot``.
- Both ``get_all_frag_roots`` and ``get_frag_root_by_assetid`` walked ``pm.ls('*.isFragRoot')``
  separately; the second is the first with a filter.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import assetlist
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base
from mca.mya.rigging.frag import frag_rig
from mca.mya.rigging.frag import skeletal_mesh
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What the asset registry is asked for an asset's name at build time.
_ASSET_MANAGER = assetlist.get_asset_manager()

#: What a rig records about the asset it was built for.
ASSET_TYPE_ATTR = 'assetType'
ASSET_ID_ATTR = 'assetID'
ASSET_NAME_ATTR = 'assetName'

#: The attribute carrying the skeleton's root joint, and the one put on the joint pointing back.
ROOT_JOINT_ATTR = 'rootJoint'
FRAG_ROOT_JOINT_ATTR = 'fragRootJoint'

#: The name stored when the registry has nothing for the asset id a rig was built with.
MISSING_ASSET_NAME = 'missing_name'


class FRAGRoot(frag_base.FRAGNode):
    """
    The top of one asset's rig: which asset it is, and the skeleton it was built on.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(root_joint, asset_type, asset_id):
        """
        Build the node for a skeleton.

        :param pm.nt.Joint root_joint: The skeleton's root. Its namespace becomes the rig's.
        :param str asset_type: What kind of asset it is - ``head``, ``player``.
        :param str asset_id: The asset's id in the registry.
        :return: The node.
        :rtype: FRAGRoot
        """

        root_namespace = root_joint.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(None, FRAGRoot.__name__, FRAGRoot.VERSION)

        node.pynode.addAttr(ASSET_TYPE_ATTR, dt='string')
        node.pynode.attr(ASSET_TYPE_ATTR).set(asset_type)
        node.pynode.addAttr(ASSET_ID_ATTR, dt='string')
        node.pynode.attr(ASSET_ID_ATTR).set(asset_id)
        node.pynode.addAttr(frag_base.IS_FRAG_ROOT_ATTR, at='bool', dv=True)

        mca_asset = _ASSET_MANAGER.get_record(asset_id)
        node.pynode.addAttr(ASSET_NAME_ATTR, dt='string')
        if mca_asset:
            node.pynode.attr(ASSET_NAME_ATTR).set(mca_asset.name.lower())
        else:
            # Worth saying which id: the rig builds either way, and the name it ends up with is what
            # names the rig's top group.
            logger.warning('The asset registry has no record of %s, so this rig is named %s.',
                           asset_id, MISSING_ASSET_NAME)
            node.pynode.attr(ASSET_NAME_ATTR).set(MISSING_ASSET_NAME)

        node.connect_node(root_joint, ROOT_JOINT_ATTR, parent_attr=FRAG_ROOT_JOINT_ATTR)

        return node

    @property
    def root_joint(self):
        """
        :return: The root of the skeleton this rig was built on.
        :rtype: pm.nt.Joint
        """

        return self.pynode.attr(ROOT_JOINT_ATTR).get()

    @property
    def asset_type(self):
        """
        :return: What kind of asset this rig is for.
        :rtype: str
        """

        return self.pynode.attr(ASSET_TYPE_ATTR).get()

    @property
    def asset_name(self):
        """
        :return: The asset's name as the registry had it when the rig was built.
        :rtype: str
        """

        return self.pynode.attr(ASSET_NAME_ATTR).get()

    @property
    def asset_id(self):
        """
        :return: The asset's id in the registry.
        :rtype: str
        """

        return self.pynode.attr(ASSET_ID_ATTR).get()

    @asset_id.setter
    def asset_id(self, value):
        """
        :param str value: The asset's id in the registry.
        """

        self.pynode.attr(ASSET_ID_ATTR).set(value)

    def get_rig(self):
        """
        :return: The rig under this root, or None when one has not been built yet.
        :rtype: FRAGRig or None
        """

        return self.get_frag_child(frag_rig.FRAGRig)

    def get_skeletal_mesh(self):
        """
        :return: The node owning this rig's geometry, or None when there is not one.
        :rtype: SkeletalMesh or None
        """

        return self.get_frag_child(skeletal_mesh.SkeletalMesh)


def is_frag_root(node):
    """
    Whether something is the node at the top of a rig.

    :param node: A ``FRAGNode``, a ``PyNode`` or a name.
    :return: Whether it is.
    :rtype: bool
    """

    if not frag_base.is_frag_node(node):
        return False
    if not isinstance(node, frag_base.FRAGNode):
        node = frag_base.wrap_frag_node(node)
    return isinstance(node, FRAGRoot)


def get_frag_root(input_node):
    """
    The node at the top of the rig something belongs to.

    :param input_node: Anything in a rig: one of its metadata nodes, or a node carrying a
        ``fragParent``.
    :return: The root, or None when the node is not in a rig.
    :rtype: FRAGRoot or None
    """

    found_root = frag_base.FRAGNode.get_frag_root(input_node)
    if found_root is None:
        return None

    # The base walk recognises a root by its attribute, because it cannot know about this class.
    # They agree for every rig the pipeline builds, since this is the only thing that adds the
    # attribute - so anything else carrying it is worth a word rather than being handed back as a
    # root.
    if not isinstance(found_root, FRAGRoot):
        logger.warning('%s carries %s but is a %s rather than a FRAG root.', found_root.pynode,
                       frag_base.IS_FRAG_ROOT_ATTR, type(found_root).__name__)
        return None
    return found_root


def get_all_frag_roots():
    """
    Every rig root in the scene, referenced rigs included.

    :return: The roots. One that cannot be wrapped is reported and left out, rather than stopping
    the
        walk over the rest.
    :rtype: list(FRAGRoot)
    """

    roots = []
    for is_root_attr in pm.ls('*.{0}'.format(frag_base.IS_FRAG_ROOT_ATTR), recursive=True):
        if not isinstance(is_root_attr, pm.Attribute) or not is_root_attr.get():
            continue
        wrapped_node = frag_base.wrap_frag_node(is_root_attr.node())
        if wrapped_node is not None:
            roots.append(wrapped_node)
    return roots


def get_frag_root_by_assetid(assetid):
    """
    The rig in the scene that was built for a particular asset.

    :param str assetid: The asset's id in the registry.
    :return: The first root found for it, or None.
    :rtype: FRAGRoot or None
    """

    for root_node in get_all_frag_roots():
        if not root_node.has_attribute(ASSET_ID_ATTR):
            logger.warning('%s is a rig root with no asset id on it.', root_node.pynode)
            continue
        if root_node.asset_id == assetid:
            return root_node
    return None


def get_root_joint(rig_node):
    """
    The root of the skeleton the rig something belongs to was built on.

    :param rig_node: Anything in a rig.
    :return: The joint, or None when the node is not in a rig.
    :rtype: pm.nt.Joint or None
    """

    found_root = get_frag_root(rig_node)
    if found_root is None:
        logger.warning('%s is not in a rig, so there is no root joint to find.', rig_node)
        return None
    return found_root.root_joint
