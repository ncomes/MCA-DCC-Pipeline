"""
Blend shape nodes: what is on one, and how to make a clean mesh to put on one.

The face rig is a stack of blend shapes, and almost everything here is a question asked of a
blend node - which targets are on it, what index is each one at, which node on this mesh is the
one that matters - plus the two functions that make a target in the first place: duplicate a
mesh, strip the rig's attributes off the copy, and hand it back.

What was wrong before:

- **``get_blendnode_shapes`` walked the history to find the node it had already been given,
  and raised when it could not.** ``pm.ls(pm.listHistory(blendnode), type='blendShape')[0]``:
  ``listHistory`` puts the node itself first, so on a blend node those three lines resolve to
  the argument - checked in a real Maya on a two-node stack - and on anything that is not one,
  such as the mesh callers reasonably pass, they are an ``IndexError``. It reads the node it is
  given now, and resolves a mesh through :func:`get_first_blendnode`.
- ``set_blendshape_weights_from_mesh`` and ``set_blendshape_weights`` were the same four lines
  twice over, differing only in which end they started from. The first had no callers; the
  second takes a mesh or a blend node now, which is what the pair of them amounted to.
- ``get_active_attribute`` (no callers) and ``get_blendnode_index`` (a one-line wrapper around
  ``weightIndexList`` with one caller, in this module) are gone.
- ``delete_blendshapes`` ran ``pm.delete`` inside a list comprehension for its side effect.
- ``set_blendshape_weight_symmetry`` said "turn reflection on, unless the pose is not on the
  centre, in which case off; and if symmetry is off, off" in a nested if/else. It is one line.
- Tabs for indentation.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.utils import attr_utils


logger = log.MCA_LOGGER

#: The string attribute the pipeline puts on its own blend nodes, so one of ours can be told
#: apart from one Maya or an import made.
BLEND_NODE_TYPE_ATTR = 'blendNodeType'


# --------------------------------------------------------------------------------------- #
# finding a blend node
# --------------------------------------------------------------------------------------- #
def get_all_blendnodes(mesh):
    """
    Every blend node on a mesh that the pipeline put there.

    A node without :data:`BLEND_NODE_TYPE_ATTR` is not one of ours, so its own blend node
    connections are followed one step to see whether it is sitting in front of one that is.

    :param pm.nt.Transform mesh: The mesh to look at.
    :return: The blend nodes.
    :rtype: list(pm.nt.BlendShape)
    """

    shapes = mesh.getShapes() if hasattr(mesh, 'getShapes') else [mesh]
    blendnodes = lists.flatten_list([shape.listConnections(type=pm.nt.BlendShape)
                                     for shape in shapes])

    all_blendnodes = []
    for blendnode in set(blendnodes):
        if blendnode.hasAttr(BLEND_NODE_TYPE_ATTR):
            all_blendnodes.append(blendnode)
            continue
        for other in (blendnode.listConnections(type=pm.nt.BlendShape) or []):
            if other.hasAttr(BLEND_NODE_TYPE_ATTR):
                all_blendnodes.append(other)
    return all_blendnodes


def get_first_blendnode(mesh):
    """
    The blend node a caller means when it says "the blend node on this mesh".

    A blend node passes straight through, so callers holding either can use one code path.

    :param mesh: A mesh, or a blend node.
    :return: The blend node, or None when the mesh has none.
    :rtype: pm.nt.BlendShape
    """

    if isinstance(mesh, pm.nt.BlendShape):
        return mesh

    blendnode = lists.get_first_in_list(get_all_blendnodes(mesh))
    if not blendnode:
        logger.warning('No blend node was found connected to %s.', mesh)
    return blendnode


# --------------------------------------------------------------------------------------- #
# what is on one
# --------------------------------------------------------------------------------------- #
def get_blendnode_shapes(blendnode):
    """
    The target names on a blend node, in weight order.

    :param blendnode: The blend node, or a mesh with one on it.
    :return: The target names.
    :rtype: list(str)
    """

    blendnode = get_first_blendnode(blendnode)
    if not blendnode:
        return []
    return pm.listAttr('{0}.w'.format(blendnode), multi=True) or []


def get_blendnode_index_as_dict(blendnode):
    """
    The target names on a blend node against the weight index each one sits at.

    The indexes are not the positions in the list: deleting a target leaves a hole, and the
    caller needs the real index to address ``inputTargetGroup``.

    :param blendnode: The blend node, or a mesh with one on it.
    :return: ``{target name without its namespace: index}``.
    :rtype: dict
    """

    blendnode = get_first_blendnode(blendnode)
    if not blendnode:
        return {}
    shapes = get_blendnode_shapes(blendnode)
    return dict(zip([name.split(':')[-1] for name in shapes], blendnode.weightIndexList()))


# --------------------------------------------------------------------------------------- #
# changing one
# --------------------------------------------------------------------------------------- #
def delete_blendshapes(blendnode):
    """
    Delete the target meshes a blend node was built from.

    The targets are named after the meshes, which is why this can find them at all - and why a
    target whose mesh has already gone is skipped rather than raising.

    :param blendnode: The blend node, or a mesh with one on it.
    :return: The names of the meshes that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for shape in get_blendnode_shapes(blendnode):
        if pm.objExists(shape):
            pm.delete(shape)
            deleted.append(shape)
    return deleted


def set_blendshape_weights(blendnode, weight=0):
    """
    Set the per-vertex weight of a blend node's first target across the whole mesh.

    This is the paint weight, not the target's own weight: it is what decides how much of the
    target each vertex takes. Setting it to zero everywhere is how a pose is temporarily taken
    out of the way without deleting it.

    :param blendnode: The blend node, or a mesh with one on it.
    :param float weight: The weight to set on every vertex.
    :return: How many vertices were set.
    :rtype: int
    """

    blendnode = get_first_blendnode(blendnode)
    if not blendnode:
        return 0

    mesh = lists.get_first_in_list(blendnode.outputGeometry[0].listConnections())
    if not mesh:
        logger.warning('%s drives no mesh, so no weights were set.', blendnode)
        return 0

    vertex_count = pm.polyEvaluate(mesh, vertex=True)
    target_weights = blendnode.inputTarget[0].inputTargetGroup[0].targetWeights
    for index in range(vertex_count):
        target_weights[index].set(weight)
    return vertex_count


def create_parallel_blendnode(diff_mesh, pose_mesh, last_mesh, name='parallel_blendshape'):
    """
    Build a parallel blend node, which is how a pose is edited on top of what is already there.

    Two targets, both fully on: the difference between the neutral and where the mesh is now,
    and the pose being worked on. A parallel node evaluates beside the main one rather than
    after it, so editing through it does not feed back into the shapes it is reading.

    :param pm.nt.Transform diff_mesh: The neutral mesh.
    :param pm.nt.Transform pose_mesh: The pose being edited.
    :param pm.nt.Transform last_mesh: The mesh the node is built on.
    :param str name: A name for the node.
    :return: The parallel blend node.
    :rtype: pm.nt.BlendShape
    """

    parallel_node = lists.get_first_in_list(
        pm.blendShape(diff_mesh, pose_mesh, last_mesh, parallel=True, n=name))
    parallel_node.weight[0].set(1)
    parallel_node.weight[1].set(1)
    return parallel_node


def set_blendshape_weight_symmetry(side=None, symmetry=True):
    """
    Turn the blend shape paint tool's reflection on, but only for a pose on the centre.

    The same rule as :func:`vert_utils.set_vertex_symmetry`, and for the same reason: a pose on
    one side is painted on that side and mirrored afterwards.

    :param str side: Which side the pose is on.
    :param bool symmetry: Whether reflection is wanted at all.
    :return: Whether reflection ended up on.
    :rtype: bool
    """

    wanted = bool(symmetry) and side == 'center'
    pm.artAttrCtx('artAttrBlendShapeContext', edit=True, reflection=wanted)
    return wanted


# --------------------------------------------------------------------------------------- #
# making a target
# --------------------------------------------------------------------------------------- #
def duplicate_mesh(mesh, label=None, remove_attrs=(), remove_user_attrs=False):
    """
    Duplicate a mesh into something that can be used as a blend shape target.

    The copy comes off a rigged mesh, so it arrives with locked attributes and whatever the rig
    put on it. Both have to go: a locked channel cannot be sculpted, and a leftover rig
    attribute is what makes two supposedly identical targets compare as different.

    :param pm.nt.Transform mesh: The mesh to duplicate.
    :param str label: A name for the copy. None keeps the original's.
    :param tuple remove_attrs: Named attributes to delete off the copy.
    :param bool remove_user_attrs: Delete every attribute a user or the rig added.
    :return: The copy.
    :rtype: pm.nt.Transform
    """

    dup_mesh = pm.duplicate(mesh, name=label or str(mesh))[0]
    attr_utils.unlock_all_attrs(dup_mesh)
    if remove_user_attrs:
        attr_utils.purge_user_defined_attrs([dup_mesh])

    for attr_name in remove_attrs:
        if dup_mesh.hasAttr(attr_name):
            dup_mesh.deleteAttr(attr_name)
    return dup_mesh


def dup_and_delete_mesh(mesh, label=None, remove_attrs=(), remove_user_attrs=False):
    """
    Replace a mesh with a clean duplicate of itself, under the same name.

    The original is renamed out of the way first so the copy can take its name, and deleted
    once the copy exists.

    :param pm.nt.Transform mesh: The mesh to replace.
    :param str label: A name for the copy. None keeps the original's.
    :param tuple remove_attrs: Named attributes to delete off the copy.
    :param bool remove_user_attrs: Delete every attribute a user or the rig added.
    :return: The copy.
    :rtype: pm.nt.Transform
    """

    label = label or str(mesh)
    pm.rename(mesh, 'temp_mesh_DELETE')
    dup_mesh = duplicate_mesh(mesh=mesh, label=label, remove_attrs=remove_attrs,
                              remove_user_attrs=remove_user_attrs)
    pm.delete(mesh)
    return dup_mesh
