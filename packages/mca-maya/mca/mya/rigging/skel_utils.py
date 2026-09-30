"""
Writing a skeleton down, and building one back.

A ``.skl`` file is JSON: one entry per joint, keyed by the joint's name, holding its world matrix,
its parent's name, whether it draws its label, and every user attribute on it - which is where the
side and region markup lives. That is enough to rebuild the skeleton somewhere else, to merge one
skeleton into another, to put a skeleton that has been posed back into its bind pose, and to put
markup back onto a skeleton that has lost it. Those four things are what this module does.

What was wrong before:

- **Exporting over a read-only file failed.** ``.skl`` files come out of Perforce read-only until
  they are checked out, which is what ``fileio.touch_path`` is for - but it was called with the
  path *without* its extension, so it made the folder and never touched the file that was about to
  be written.
- **The joint radius scale was the sum of the bounding box's maximum corner**, so it depended on
  where in the world the skeleton was standing rather than on how big it was. The same skeleton
  moved a thousand units along X came out with radii eight times bigger, and one standing below the
  origin came out with a **negative** radius, which draws nothing at all. It is the longest side of
  the bounding box now, which is what the comment beside it always said it was.
- **And it never set the root joint's radius**, because the walk it used leaves the node it starts
  from out.
- **Restoring markup deleted every user attribute on every joint, including Maya's own.** A bound
  joint carries ``lockInfluenceWeights``, which is a user attribute; it was serialized around and
  then deleted here, so restoring a skeleton's markup silently cleared every per-joint weight lock
  in the skeleton. Anything else another tool had put on a joint went the same way, connections and
  all. The attributes this never writes down are the attributes it leaves alone now, and a
  connected attribute is reported rather than deleted.
- **A skeleton whose root is not called ``root`` lost its root's markup and its root's bind pose.**
  Both readers looked the root's entry up under the literal key ``'root'`` while the writer keys
  every joint, root included, by its own name. The root's entry is found by name now, falling back
  to the entry that has no parent - which is the root by construction, whatever it is called, and
  which also covers the case the literal lookup was there for: a duplicated hierarchy whose root
  Maya has renamed.
- **Importing a skeleton renamed whatever else in the scene happened to share a joint's name.** A
  joint has to be built under the name it was written down as, so a clash has to be moved aside -
  but it was moved aside silently, and it could be anything: a mesh, a control, a locator. It says
  which node it moved and what it moved it to now. The joint was also created under its final name
  directly, so Maya's own uniquifying could rename it into the *next* joint in the file -
  ``b_spine_01`` taken gives ``b_spine_02``, not ``b_spine_011`` - and the two would then fight over
  that name. It is created unnamed and renamed.
- **``create_skeleton_from_data`` raised ``KeyError`` on a file naming a parent it does not
  contain**, and said nothing at all when the file had no root in it, or more than one.
- **``.skl`` paths were trimmed with ``path.replace('.skl', '')``**, five times over, which strikes
  anywhere in the path and not just the end - a file under a folder called ``.skl_backups`` came out
  somewhere else entirely. All five were pointless: ``strings.append_extension`` adds the extension
  only when it is not already there.
- **``create_skeleton_dict`` was a second copy of ``joint_utils.create_skeleton_dict``** and
  ``get_skel_dict`` a third, which differed only in warning about a repeated name. The warning is in
  ``joint_utils`` now and both copies are gone.
- **``position_twist_joints`` reversed the list it was given**, in place, so each joint was placed
  at the opposite end of the segment from where its docstring said it belonged. The docstring is the
  only statement of intent either way, so the reverse went and the docstring stands: the first joint
  in the list is placed nearest the parent. It does not touch the caller's list any more.
- ``SkeletonData`` carried ``DATA_TYPE``, ``NICE_NAME``, ``PRIORITY``, ``can_represent``, ``icon``
  and ``functionality`` for a data-part registry that no longer exists, and called its own methods
  through ``self.functionality()['read_data']()``. ``export_data`` wrote the joints under a
  ``joints`` key with the Maya version beside them, which no reader in the pipeline understands, and
  nothing called it - the same fault ``serialize_flag`` was dropped for. What is left is a path and
  two methods.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.textio import jsonio
from mca.common.utils import fileio
from mca.common.utils import pymaths
from mca.common.utils import strings
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup
from mca.mya.rigging import joint_utils
from mca.mya.utils import attr_utils
from mca.mya.utils import dag
from mca.mya.utils import naming
from mca.mya.utils import node_util


logger = log.MCA_LOGGER

#: The extension a skeleton file carries.
SKELETON_EXTENSION = '.skl'

#: User attributes Maya adds on its own. They are not the skeleton's markup, so they are neither
#: written down nor deleted when markup is put back - ``lockInfluenceWeights`` holds an artist's
#: per-joint weight locks, and ``filmboxTypeID`` is left behind by an FBX round trip.
SKIP_USER_ATTRIBUTES = ['lockInfluenceWeights', 'filmboxTypeID']

#: A 4x4 identity as the flat sixteen numbers ``pm.xform`` wants, for an entry with no matrix.
IDENTITY_MATRIX = [1.0, 0.0, 0.0, 0.0,
                   0.0, 1.0, 0.0, 0.0,
                   0.0, 0.0, 1.0, 0.0,
                   0.0, 0.0, 0.0, 1.0]

#: The skeleton this pipeline draws at a joint radius of 1.0 is about this tall. A bigger or smaller
#: one is scaled from it.
REFERENCE_SKELETON_SIZE = 125.0

#: How much smaller each level down the hierarchy is drawn, so a finger does not read like a hip.
RADIUS_FALLOFF_PER_LEVEL = 0.05

#: How small that falloff is allowed to make a joint, as a fraction of the skeleton's own radius.
RADIUS_FALLOFF_FLOOR = 0.4


# --------------------------------------------------------------------------------------------- #
# the file
# --------------------------------------------------------------------------------------------- #
class SkeletonData(object):
    """
    A ``.skl`` file on disk: its path, and reading and writing the dictionary in it.

    This was a data part in a registry that no longer exists, and most of what it carried was for
    that registry. What is left is the two things five callers across the package use it for.
    """

    def __init__(self, identifier):
        """
        :param str identifier: The file's path, with or without its extension.
        """

        self._id = identifier

    @classmethod
    def extension(cls):
        """
        :return: The extension a skeleton file carries.
        :rtype: str
        """

        return SKELETON_EXTENSION

    @property
    def file_path(self):
        """
        :return: The path with its extension, whether or not it was given with one.
        :rtype: str
        """

        return strings.append_extension(self._id, self.extension())

    def read_data(self):
        """
        :return: The dictionary in the file, or an empty one when there is no file.
        :rtype: dict
        """

        file_path = self.file_path
        if not os.path.exists(file_path):
            logger.warning('There is no skeleton file at %s to read.', file_path)
            return {}

        logger.debug('Reading skeleton data from %s.', file_path)
        return jsonio.read_json_file(file_path)

    def save_data(self, skeleton_data):
        """
        :param dict skeleton_data: What to write.
        :return: Whether it was written.
        :rtype: bool
        """

        if not self._id:
            logger.warning('A skeleton cannot be saved without a path to save it to.')
            return False

        jsonio.write_to_json_file(skeleton_data, self.file_path)
        return True


# --------------------------------------------------------------------------------------------- #
# writing a skeleton down
# --------------------------------------------------------------------------------------------- #
def serialize_skeleton(root_joint):
    """
    Everything about a skeleton that is needed to build it again.

    :param pm.nt.Joint root_joint: The skeleton's root.
    :return: ``{joint name: {'world_matrix', 'parent_node', 'draw_label', 'attributes'}}``, keyed by
        each joint's own name, the root included. None when the root is not a joint or has nothing
        under it.
    :rtype: dict or None
    """

    if not root_joint or not isinstance(root_joint, pm.nt.Joint):
        logger.warning('%s is not a joint, so there is no skeleton to write down.', root_joint)
        return None

    child_joints = pm.listRelatives(root_joint, allDescendents=True, fullPath=True,
                                    type=pm.nt.Joint) or []
    if not child_joints:
        logger.warning('%s has no joints under it, so there is no skeleton to write down.',
                       root_joint)
        return None

    skeleton_data_dict = {}
    for joint_node in [root_joint] + child_joints:
        wrapped_joint = chain_markup.JointMarkup(joint_node)
        parent_node = wrapped_joint.getParent()
        is_joint_parent = isinstance(parent_node, (pm.nt.Joint, chain_markup.JointMarkup))

        joint_data_dict = {'world_matrix': wrapped_joint.get_world_matrix(),
                           'parent_node': parent_node.name if is_joint_parent else None,
                           'draw_label': joint_node.drawLabel.get(),
                           'radius': joint_node.radius.get()}

        attributes = []
        for attribute_name in (pm.listAttr(joint_node, userDefined=True) or []):
            if attribute_name in SKIP_USER_ATTRIBUTES:
                continue
            attributes.append(attr_utils.serialize_attribute(joint_node.attr(attribute_name)))
        if attributes:
            joint_data_dict['attributes'] = attributes

        skeleton_data_dict[wrapped_joint.name] = joint_data_dict

    return skeleton_data_dict


def export_skeleton(skl_path, root_joint):
    """
    Write a skeleton to a ``.skl`` file.

    :param str skl_path: Where to write it, with or without the extension.
    :param pm.nt.Joint root_joint: The skeleton's root.
    :return: Whether it was written.
    :rtype: bool
    """

    skeleton_file = SkeletonData(skl_path)
    skeleton_data_dict = serialize_skeleton(root_joint)
    if not skeleton_data_dict:
        return False

    # With the extension: these come out of source control read-only, and this is what makes the
    # file writable. Without it, the folder was made and the file was left as it was.
    fileio.touch_path(skeleton_file.file_path)
    return skeleton_file.save_data(skeleton_data_dict)


# --------------------------------------------------------------------------------------------- #
# building one back
# --------------------------------------------------------------------------------------------- #
def _create_serialized_joint(joint_name, joint_data_dict):
    """
    One joint, from its entry in a skeleton file.

    :param str joint_name: The name it was written down as, which is the name it has to end up with:
        every other entry's ``parent_node`` refers to it by that name.
    :param dict joint_data_dict: The entry.
    :return: The joint, at the world matrix in the entry and not yet parented.
    :rtype: pm.nt.Joint
    """

    cmds.select(None)
    # Unnamed, then renamed. Asking Maya for a name that is taken does not give the name with a 1 on
    # the end - `b_spine_01` taken gives `b_spine_02`, which is very likely the next joint in the
    # same file, and the two then fight over it.
    new_joint = pm.joint()
    target_name = '{0}{1}'.format(new_joint.namespace(), joint_name)

    clashing_nodes = [node for node in pm.ls(target_name) if node != new_joint]
    for clashing_node in clashing_nodes:
        # The joint has to have this name, so whatever is sitting on it moves - but which node moved
        # and where it went is worth knowing, because it can be anything: a mesh, a control.
        moved_to = clashing_node.rename('{0}_was_here'.format(clashing_node.nodeName()))
        logger.warning('%s already had the name %s, which the skeleton being built needs, so it '
                       'was renamed to %s.', clashing_node.nodeType(), joint_name, moved_to)

    new_joint.rename(target_name)
    if naming.get_basename(new_joint) != joint_name:
        logger.warning('The joint meant to be called %s came out as %s.', joint_name, new_joint)

    new_joint.drawLabel.set(joint_data_dict.get('draw_label', False))
    new_joint.radius.set(joint_data_dict.get('radius', 1.0))
    pm.xform(new_joint, matrix=joint_data_dict.get('world_matrix', IDENTITY_MATRIX),
             worldSpace=True)
    new_joint.scale.set([1, 1, 1])

    for attribute_data in joint_data_dict.get('attributes', []):
        node_util.add_attribute(new_joint, **attribute_data)

    return new_joint


def _root_names(skeleton_data_dict):
    """
    Which entries in a skeleton file end up at the world root.

    :param dict skeleton_data_dict: ``{joint name: entry}``.
    :return: The names, in the file's own order: the entries with no parent, and then the ones
        naming a parent the file does not contain.
    :rtype: list(str)
    """

    parentless = []
    orphaned = []
    for joint_name, joint_data_dict in skeleton_data_dict.items():
        parent_name = joint_data_dict.get('parent_node')
        if not parent_name:
            parentless.append(joint_name)
        elif parent_name not in skeleton_data_dict:
            # A KeyError, when the parenting loop reached it.
            logger.warning('%s is written down as a child of %s, which the file does not contain, '
                           'so it stays at the world root.', joint_name, parent_name)
            orphaned.append(joint_name)
    return parentless + orphaned


@ma_decorators.keep_selection_decorator
def create_skeleton_from_data(skeleton_data_dict):
    """
    Build a whole skeleton from a skeleton file's dictionary.

    :param dict skeleton_data_dict: ``{joint name: entry}``, as :func:`serialize_skeleton` writes.
    :return: The skeleton's root, or None when the data names no root.
    :rtype: pm.nt.Joint or None
    """

    # Before anything is built: a file in which every entry has a parent inside the file describes
    # a loop rather than a skeleton, and building it first left the joints in the scene and then
    # raised `Cannot parent an object to one of its children` out of the middle of the parenting.
    root_names = _root_names(skeleton_data_dict)
    if not root_names:
        logger.warning('Every joint in this skeleton file names a parent inside the file, so it '
                       'has no root and describes a loop. Nothing was built.')
        return None
    if len(root_names) > 1:
        logger.warning('This skeleton file has more than one root in it: %s. The first is the one '
                       'that comes back.', ', '.join(root_names))

    skeleton_dict = {joint_name: _create_serialized_joint(joint_name, joint_data_dict)
                     for joint_name, joint_data_dict in skeleton_data_dict.items()}

    for joint_name, joint_node in skeleton_dict.items():
        parent_name = skeleton_data_dict.get(joint_name, {}).get('parent_node', None)
        if not parent_name or parent_name not in skeleton_dict:
            continue
        try:
            joint_node.setParent(skeleton_dict[parent_name])
        except RuntimeError as error:
            logger.warning('%s could not be parented to %s, which the skeleton file says is its '
                           'parent: %s', joint_name, parent_name, error)

    root_joint = skeleton_dict[root_names[0]]
    pm.makeIdentity(root_joint, apply=True, t=True, r=True, s=True, n=False, pn=True)
    return root_joint


def create_and_merge_skeletons_from_data(root_joint, skeleton_data_dict):
    """
    Add whatever a skeleton file holds that a skeleton in the scene does not already have.

    Joints already there by name are left alone, so this is how a piece of gear's joints or a
    variant's extra joints are brought into a skeleton that is already built.

    :param pm.nt.Joint root_joint: The root of the skeleton in the scene. None builds the whole
        thing from the file instead.
    :param dict skeleton_data_dict: ``{joint name: entry}``.
    :return: The root of the merged skeleton.
    :rtype: pm.nt.Joint or None
    """

    if not root_joint or not isinstance(root_joint, pm.nt.Joint):
        logger.info('There is no skeleton to merge into, so all of it is built from the file.')
        return create_skeleton_from_data(skeleton_data_dict)

    existing_hierarchy = chain_markup.ChainMarkup(root_joint)
    hierarchy_start = existing_hierarchy.hierarchyStart
    existing_joints = existing_hierarchy.skeleton_dict

    new_joints = {joint_name: _create_serialized_joint(joint_name, joint_data_dict)
                  for joint_name, joint_data_dict in skeleton_data_dict.items()
                  if joint_name not in existing_joints}

    for joint_name, joint_node in new_joints.items():
        parent_name = skeleton_data_dict.get(joint_name, {}).get('parent_node', None)
        # The parent in neither skeleton means the joint hangs off the top of the animatable
        # hierarchy rather than being left loose at the world root.
        parent_node = new_joints.get(parent_name,
                                     existing_joints.get(parent_name,
                                                         hierarchy_start or root_joint))
        try:
            joint_node.setParent(parent_node)
        except RuntimeError as error:
            logger.warning('%s could not be parented to %s: %s', joint_name, parent_node, error)

    return root_joint


def import_skeleton(skl_path, set_radius=True):
    """
    Build a skeleton from a ``.skl`` file.

    :param str skl_path: The file, with or without its extension.
    :param bool set_radius: Draw the joints at a size that suits the skeleton.
    :return: The skeleton's root, or None when there was nothing to build.
    :rtype: pm.nt.Joint or None
    """

    skeleton_data_dict = SkeletonData(skl_path).read_data()
    if not skeleton_data_dict:
        # The version before answered a (None, []) tuple here, which its caller then handed to
        # pm.xform as a node.
        return None

    skel_root = create_skeleton_from_data(skeleton_data_dict)
    if skel_root and set_radius:
        scale_skel_radi(skel_root)
    return skel_root


def import_merge_skeleton(skl_path, root_joint, set_radius=True):
    """
    Add whatever a ``.skl`` file holds that the skeleton in the scene does not already have.

    :param str skl_path: The file, with or without its extension.
    :param pm.nt.Joint root_joint: The root of the skeleton in the scene. None builds the whole
        thing from the file.
    :param bool set_radius: Draw the joints at a size that suits the skeleton.
    :return: The root of the merged skeleton, or None when there was nothing to merge.
    :rtype: pm.nt.Joint or None
    """

    skeleton_data_dict = SkeletonData(skl_path).read_data()
    if not skeleton_data_dict:
        return None

    skel_root = create_and_merge_skeletons_from_data(root_joint, skeleton_data_dict)
    if skel_root and set_radius:
        scale_skel_radi(skel_root)
    return skel_root


# --------------------------------------------------------------------------------------------- #
# putting a skeleton that is already there back the way it was
# --------------------------------------------------------------------------------------------- #
def _get_root_entry(skeleton_data_dict, root_joint):
    """
    The entry in a skeleton file that belongs to a skeleton's root joint.

    By name first. Failing that, the entry with no parent, which is the root by construction
    whatever it is called - and which is what covers a duplicated hierarchy, where Maya has put a
    number on the end of the root's name and the name match cannot work.

    :param dict skeleton_data_dict: ``{joint name: entry}``.
    :param pm.nt.Joint root_joint: The skeleton's root.
    :return: The entry, or an empty dict when the file has nothing that can be it.
    :rtype: dict
    """

    root_name = naming.get_basename(root_joint)
    if root_name in skeleton_data_dict:
        return skeleton_data_dict[root_name]

    parentless = [joint_name for joint_name, joint_data_dict in skeleton_data_dict.items()
                  if not joint_data_dict.get('parent_node')]
    if len(parentless) == 1:
        logger.debug('%s is not in the skeleton file by name, so the file\'s own root %s was taken '
                     'as its entry.', root_name, parentless[0])
        return skeleton_data_dict[parentless[0]]

    logger.warning('%s has no entry in the skeleton file, and the file does not have one root '
                   'in it to fall back on.', root_name)
    return {}


def _skeleton_entries(root_joint, skeleton_data_dict):
    """
    Every joint in a skeleton, paired with its entry in a skeleton file.

    :param pm.nt.Joint root_joint: The skeleton's root.
    :param dict skeleton_data_dict: ``{joint name: entry}``.
    :return: ``[(joint, entry)]``, parents before their children. A joint the file has nothing
        for is reported and left out.
    :rtype: list(tuple)
    """

    paired = []
    for joint_node in dag.get_children_in_order(root_joint, pm.nt.Joint):
        if joint_node == root_joint:
            joint_data_dict = _get_root_entry(skeleton_data_dict, root_joint)
        else:
            joint_data_dict = skeleton_data_dict.get(naming.get_basename(joint_node), {})

        if not joint_data_dict:
            logger.warning('The skeleton file has nothing for %s.', naming.get_basename(joint_node))
            continue
        paired.append((joint_node, joint_data_dict))
    return paired


def restore_skeleton_markup_from_data(root_joint, skeleton_data_dict):
    """
    Put a skeleton's markup back from a skeleton file's dictionary.

    Every joint's own attributes are cleared first, because a skeleton that has been through a few
    tools collects attributes that are no longer anything - but not the ones this never writes down,
    and not one something else is driving.

    :param pm.nt.Joint root_joint: The skeleton's root.
    :param dict skeleton_data_dict: ``{joint name: entry}``.
    """

    for joint_node, joint_data_dict in _skeleton_entries(root_joint, skeleton_data_dict):
        joint_node.drawLabel.set(joint_data_dict.get('draw_label', False))
        joint_node.radius.set(joint_data_dict.get('radius', 1.0))

        for attribute in joint_node.listAttr(userDefined=True):
            if not attribute.exists():
                # A compound's children go with their parent, so the list can name one twice.
                continue
            if attribute.attrName(longName=True) in SKIP_USER_ATTRIBUTES:
                continue
            if attribute.listConnections():
                logger.warning('%s is connected to something, so it was left alone rather than '
                               'deleted with the rest of the markup.', attribute)
                continue
            attribute.delete()

        for attribute_data in joint_data_dict.get('attributes', []):
            node_util.add_attribute(joint_node, **attribute_data)


def return_skeleton_to_bind_pose_from_data(root_joint, skeleton_data_dict):
    """
    Put every joint in a skeleton back to the world matrix it was written down at.

    :param pm.nt.Joint root_joint: The skeleton's root.
    :param dict skeleton_data_dict: ``{joint name: entry}``.
    """

    for joint_node, joint_data_dict in _skeleton_entries(root_joint, skeleton_data_dict):
        pm.xform(joint_node, matrix=joint_data_dict.get('world_matrix', IDENTITY_MATRIX),
                 worldSpace=True)


def restore_skeleton_markup(skl_path, root_joint):
    """
    Put a skeleton's markup back from a ``.skl`` file.

    :param str skl_path: The file, with or without its extension.
    :param pm.nt.Joint root_joint: The skeleton's root.
    """

    restore_skeleton_markup_from_data(root_joint, SkeletonData(skl_path).read_data())


def restore_skeleton_bindpose(skl_path, root_joint):
    """
    Put every joint in a skeleton back to the pose in a ``.skl`` file.

    :param str skl_path: The file, with or without its extension.
    :param pm.nt.Joint root_joint: The skeleton's root.
    """

    return_skeleton_to_bind_pose_from_data(root_joint, SkeletonData(skl_path).read_data())


# --------------------------------------------------------------------------------------------- #
# placing joints
# --------------------------------------------------------------------------------------------- #
def scale_skel_radi(skel_root):
    """
    Draw a skeleton's joints at a size that suits how big the skeleton is.

    The size is the longest side of the skeleton's bounding box, which is the same number wherever
    in the world the skeleton is standing. Each level down the hierarchy is drawn a little smaller,
    to a floor, so a finger does not read like a hip.

    :param pm.nt.Joint skel_root: The skeleton's root.
    """

    bounding_box = pm.xform(skel_root, query=True, boundingBox=True)
    skel_size = max(maximum - minimum
                    for minimum, maximum in zip(bounding_box[:3], bounding_box[3:]))
    if not skel_size:
        logger.warning('%s and everything under it sit in the same place, so there is no size to '
                       'draw the joints from.', skel_root)
        return

    skel_scale = skel_size / REFERENCE_SKELETON_SIZE

    # The root included: the walk this used leaves the node it starts from out, so the root kept
    # whatever radius it happened to have.
    for joint_node in dag.get_children_in_order(skel_root, pm.nt.Joint):
        depth = len(dag.get_all_parents(joint_node, node_type=pm.nt.Joint))
        falloff = max(1.0 - (RADIUS_FALLOFF_PER_LEVEL * depth), RADIUS_FALLOFF_FLOOR)
        joint_node.radius.set(skel_scale * falloff)


def make_planar_chain(node_list):
    """
    Copy three joints into a chain that lies flat on the plane the three of them describe.

    Three points always describe a plane; three joints almost never sit on one, and an IK chain
    whose joints do not is a chain whose solver has to guess. This aims each joint at the next with
    the plane's own normal as the up vector, so all three end up on it.

    :param list(pm.nt.Transform) node_list: Exactly three nodes, root first.
    :return: The three new joints, root first. Empty when three nodes were not given.
    :rtype: list(pm.nt.Joint)
    """

    if len(node_list) != 3:
        logger.warning('A planar chain is made from exactly three nodes; %s were given.',
                       len(node_list))
        return []

    primary_axis, is_positive = dag.get_primary_axis(node_list[0])
    aim_vector = tuple((1.0 if is_positive else -1.0) if axis == primary_axis else 0.0
                       for axis in 'xyz')

    points = [pm.xform(node, query=True, worldSpace=True, translation=True) for node in node_list]

    # The up target sits out along the plane's normal from the middle point, so every aim constraint
    # below shares one plane rather than each finding its own.
    up_point = pymaths.add_vectors(points[1], pymaths.get_planar_up(*points))
    up_locator = pm.spaceLocator(name='planar_chain_up_loc')
    up_locator.translate.set(up_point)

    new_joints = []
    for node in node_list:
        cmds.select(None)
        new_joint = joint_utils.duplicate_joint(node, 'chain01')
        if new_joints:
            pm.delete(pm.aimConstraint(new_joint, new_joints[-1], aim=aim_vector,
                                       upVector=(0.0, 0.0, 1.0), worldUpObject=up_locator,
                                       worldUpType='object'))
            new_joint.setParent(new_joints[-1])
            pm.makeIdentity(new_joints[-1], apply=True, t=True, r=True, s=True, n=False, pn=True)
        new_joints.append(new_joint)

    pm.delete(up_locator)
    return new_joints


@ma_decorators.undo_decorator
def position_twist_joints(twist_joint_list, parent_joint, child_joint):
    """
    Space twist joints evenly along the segment between two joints.

    :param list(pm.nt.Joint) twist_joint_list: The twist joints, the one that belongs nearest
        ``parent_joint`` first. The version before reversed this list in place, which put every
        joint at the opposite end of the segment from where this line says it goes.
    :param pm.nt.Joint parent_joint: The joint at the start of the segment.
    :param pm.nt.Joint child_joint: The joint at the end of it.
    """

    if not twist_joint_list:
        logger.warning('There are no twist joints to place between %s and %s.',
                       parent_joint, child_joint)
        return

    parent_point = pm.xform(parent_joint, query=True, worldSpace=True, translation=True)
    child_point = pm.xform(child_joint, query=True, worldSpace=True, translation=True)

    # Evenly, and with neither end landing on a joint: four twists between two joints sit at a
    # fifth, two fifths, three fifths and four fifths of the way along.
    step = 1.0 / (len(twist_joint_list) + 1)
    for index, joint_node in enumerate(twist_joint_list):
        point = pymaths.get_midpoint_between_points(parent_point, child_point, step * (index + 1))
        pm.xform(joint_node, worldSpace=True, translation=point)
        joint_node.jointOrient.set(0, 0, 0)
