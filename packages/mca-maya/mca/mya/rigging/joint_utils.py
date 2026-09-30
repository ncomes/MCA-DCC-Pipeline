"""
Joints: walking a chain, copying one, and mapping one skeleton onto another.

The rigging tools build almost everything out of duplicated joint chains - an IK chain, an FK
chain and a bind chain that all start life as copies of the same skeleton - so duplicating a
chain cleanly, with names nobody has taken and channels nothing has locked, is the piece of this
that matters most.

What was wrong before:

- **A chain duplicated with no suffix was named after the word "None".**
  ``f'{wrapped_joint.name}_{suffix}'`` with ``suffix`` left at its default gave ``spine_01_None``,
  for every joint in the chain.
- **Skipping the first joint of a chain raised.** ``duplicate_chain`` decided where to parent each
  duplicate with ``if index == 0``, where ``index`` counts the joints it was *given* rather than
  the ones it has made. Skip the first joint through ``skip_joints`` and the second one takes the
  ``else`` branch, which parents it under ``dup_chain[-1]`` - and ``dup_chain`` is still empty:
  ``IndexError``.
- **Three functions assumed ``pm.listRelatives`` had found something.**
  ``[root_joint] + pm.listRelatives(...)`` is a ``TypeError`` when the root has no children, which
  is a one-joint skeleton; ``get_joint_hierarchy`` iterated the same answer; and
  ``get_root_joint_from_list`` called ``hasAttr`` on the result of a parent walk that can come
  back empty.
- ``get_joint_hierarchy`` asked every child ``child.type() == 'joint'`` including shape children,
  and then put the node it was given at the front of the list whether or not it was a joint.
"""

# python imports

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging import chain_markup
from mca.mya.utils import attr_utils
from mca.mya.utils import dag
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The key the root joint is filed under in a skeleton dictionary, whatever it is called. Two
#: skeletons are mapped onto each other through these names, and their roots rarely match.
ROOT_KEY = 'root'

#: What a duplicate gets unlocked, so it can be moved and rebuilt.
DUPLICATE_UNLOCK_ATTRS = attr_utils.TRANSFORM_ATTRS + ['radius', 'v']

#: The markup that follows a joint when one joint stands in for another.
INHERITED_MARKUP_ATTRS = (chain_markup.SIDE_ATTR, chain_markup.REGION_ATTR)


# --------------------------------------------------------------------------------------- #
# walking
# --------------------------------------------------------------------------------------- #
def get_end_joint(start_joint):
    """
    The deepest joint below the given one.

    :param pm.nt.Joint start_joint: The joint to walk down from.
    :return: The end of the chain, or None when it was not given a joint.
    :rtype: pm.nt.Joint or None
    """

    if not isinstance(start_joint, pm.nt.Joint):
        return None
    return dag.get_absolute_child(start_joint, node_type=pm.nt.Joint)


def get_joint_hierarchy(node, include_leaf_joints=False):
    """
    A joint and every joint under it, top down.

    Leaf joints are left out by default: a leaf is the tip of a finger or the end of a chain,
    which carries the chain's length and nothing else, and a builder driving each joint in turn
    has nothing to drive there.

    :param pm.PyNode node: The joint to start from.
    :param bool include_leaf_joints: Keep the joints that have no joint children.
    :return: The joints, the given one first.
    :rtype: list(pm.nt.Joint)
    """

    descendants = pm.listRelatives(node, allDescendents=True, type='joint') or []
    # listRelatives walks depth first from the bottom up, so reversing it gives a top down order.
    descendants = list(reversed(descendants))

    if not include_leaf_joints:
        # type=joint on the children as well; the old test asked every child, shapes included,
        # whether its type() was 'joint'.
        descendants = [joint for joint in descendants
                       if joint.getChildren(type=pm.nt.Joint)]

    hierarchy = list(descendants)
    if isinstance(node, pm.nt.Joint):
        hierarchy.insert(0, node)
    return hierarchy


def get_root_joint_from_list(node_list):
    """
    The asset root joint that the first joint in a list belongs to.

    :param list node_list: Nodes to look through. Anything that is not a joint is ignored.
    :return: The top joint of the hierarchy when it carries an ``asset_id``, otherwise None.
    :rtype: pm.nt.Joint or None
    """

    joint_list = pm.ls(node_list, type=pm.nt.Joint)
    if not joint_list:
        return None

    # node_type stops the walk at the top joint rather than carrying on into whatever group the
    # skeleton is parented under.
    root_joint = dag.get_absolute_parent(joint_list[0], node_type=pm.nt.Joint)
    if root_joint is None:
        return None
    if not root_joint.hasAttr('asset_id'):
        # A skeleton with no asset id is somebody's working file, not an asset.
        return None
    return root_joint


def create_skeleton_dict(root_joint):
    """
    A skeleton as a name to joint lookup, for mapping one skeleton onto another.

    The root is filed under :data:`ROOT_KEY` whatever it is called, because two skeletons being
    mapped onto each other almost never agree about their roots' names.

    :param pm.nt.Joint root_joint: The skeleton's root.
    :return: ``{joint name without its namespace: joint}``.
    :rtype: dict
    """

    skel_dict = {ROOT_KEY: root_joint}
    for joint_node in (pm.listRelatives(root_joint, allDescendents=True, type=pm.nt.Joint) or []):
        skel_dict[naming.get_basename(joint_node)] = joint_node
    return skel_dict


# --------------------------------------------------------------------------------------- #
# duplicating
# --------------------------------------------------------------------------------------- #
def duplicate_joint(joint_node, duplicate_name=None):
    """
    Duplicate one joint, on its own, under a name nothing has taken.

    Maya would rename a duplicate for you if the name were taken, which is how a rig ends up with
    a joint called ``l_elbow_ik1`` that everything downstream looks for as ``l_elbow_ik``. The
    name is made free first instead.

    :param pm.nt.Joint joint_node: The joint to duplicate.
    :param str duplicate_name: What to call the copy. None appends ``_dup``.
    :return: The copy, or None when it was not given a joint.
    :rtype: pm.nt.Joint or None
    """

    if not isinstance(joint_node, pm.nt.Joint):
        logger.warning('%s is not a joint, so nothing was duplicated.', joint_node)
        return None

    duplicate_name = duplicate_name or '{0}_dup'.format(chain_markup.JointMarkup(joint_node).name)
    unique_name = duplicate_name
    index = 0
    while cmds.objExists(unique_name):
        index += 1
        unique_name = '{0}{1}'.format(duplicate_name, index)

    new_joint_node = pm.duplicate(joint_node, parentOnly=True)[0]
    pm.rename(new_joint_node, unique_name)
    attr_utils.unlock_node_attributes(new_joint_node, attributes=DUPLICATE_UNLOCK_ATTRS)
    return new_joint_node


def duplicate_chain(start_joint, end_joint=None, parent=None, skip_joints=None, suffix=None):
    """
    Duplicate a run of joints, re-parenting the copies into a chain of their own.

    :param pm.nt.Joint start_joint: The first joint to copy.
    :param pm.nt.Joint end_joint: The last one. None walks to the end of the chain.
    :param pm.nt.Transform parent: Where to put the new chain. None puts it at the scene root.
    :param list skip_joints: Joints in the run to leave out of the copy.
    :param str suffix: Added to each copy's name, after an underscore.
    :return: The copies, in order.
    :rtype: list(pm.nt.Joint)
    """

    if not start_joint or not pm.objExists(start_joint):
        logger.warning('The start joint %s does not exist, so nothing was duplicated.',
                       start_joint)
        return []
    if end_joint and not pm.objExists(end_joint):
        logger.warning('The end joint %s does not exist, so nothing was duplicated.', end_joint)
        return []
    if parent is not None:
        if not pm.objExists(parent):
            logger.warning('The parent %s does not exist, so nothing was duplicated.', parent)
            return []
        if not isinstance(parent, pm.nt.Transform):
            logger.warning('%s is not a transform, so it cannot be a parent.', parent)
            return []

    if not end_joint:
        end_joint = get_end_joint(start_joint=start_joint)
    if start_joint == end_joint:
        joint_list = [start_joint]
    else:
        joint_list = dag.get_between_nodes(start_joint, end_joint, pm.nt.Joint)

    skip_joints = skip_joints or []

    dup_chain = []
    for joint_node in joint_list:
        if joint_node in skip_joints:
            continue

        joint_name = chain_markup.JointMarkup(joint_node).name
        duplicate_name = '{0}_{1}'.format(joint_name, suffix) if suffix else joint_name
        duplicate_node = duplicate_joint(joint_node, duplicate_name)
        if duplicate_node is None:
            continue

        if dup_chain:
            duplicate_node.setParent(dup_chain[-1])
        else:
            # The first copy made, which is not always the first joint given - the old test was
            # on the index into the source list, so skipping the first joint sent the second one
            # looking for a predecessor that had never been made.
            duplicate_node.setParent(parent)

        dup_chain.append(duplicate_node)

    return dup_chain


def inherit_joint_labelling(from_node, to_node):
    """
    Copy a joint's side and region markup onto another node.

    Used where one node stands in for a joint - a helper, a duplicate in a rig - and has to be
    found by the same lookups.

    :param from_node: The node to copy from.
    :param to_node: The node to copy to.
    :return: The attributes that were copied.
    :rtype: list(str)
    """

    from_node = pm.PyNode(from_node)
    to_node = pm.PyNode(to_node)

    copied = []
    for attr_name in INHERITED_MARKUP_ATTRS:
        if not from_node.hasAttr(attr_name):
            continue
        if not to_node.hasAttr(attr_name):
            to_node.addAttr(attr_name, dt='string')
        to_node.attr(attr_name).set(from_node.attr(attr_name).get())
        copied.append(attr_name)
    return copied
