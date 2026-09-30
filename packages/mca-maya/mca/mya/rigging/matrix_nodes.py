"""
Matrix constraints: following a parent without a constraint node.

A ``multMatrix`` fed with the parent's world matrix and the driven group's inverse world matrix
gives the parent's motion in the group's space; a ``decomposeMatrix`` turns that into translate,
rotate and scale. Two groups are inserted above the driven object - one to receive the decomposed
values, one to sit above it and provide the inverse matrix - so the object's own channels stay
free for an animator.

This is used in place of ``pm.parentConstraint`` where the driven object is something an animator
also has to be able to move, and where the constraint node itself would be one more thing in the
outliner for them to select by accident.

What was wrong before:

- ``matrix_parent_grp`` was re-fetched from the scene straight after being renamed, which does
  nothing - ``pm.rename`` updates the PyNode in place.
- The array attributes were connected by their bare names: ``parent_obj.worldMatrix`` rather than
  ``worldMatrix[0]``. Maya picks element zero, so it worked, but a reader has to know that.
- **``remove_matrix_constraint`` left half the constraint behind.** It deleted the two groups and
  stopped there: the ``multMatrix`` and the ``decomposeMatrix`` stayed in the scene, still
  reading the parent's world matrix, and the two attributes that say "this object is
  constrained" stayed on the object - so a second ``matrix_constraint`` on it found markup for a
  constraint that no longer existed. It also raised on an object that had never been
  constrained, and cleared the artist's selection on its way out.
- **Constraining an object twice left the first constraint running.** ``create_aligned_parent_group``
  hands back the groups that are already there, so the second call built a second pair of matrix
  nodes whose outputs replaced the first pair's connections - and the first pair stayed in the
  scene, still evaluating, driving nothing. Re-constraining now takes the old one off first, so
  pointing an object at a different parent is a thing you can just do.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.utils import groups
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: Put on both matrix nodes, so a cleanup pass can tell them from any other matrix maths.
MATRIX_CONSTRAINT_TAG = 'isMatrixConstraint'

#: The attributes that tie the driven object to the groups above it.
CONSTRAINT_ATTR = 'matrixConstraint'
CONSTRAINT_OBJECT_ATTR = 'matrixConstraintObject'
PARENT_CONSTRAINT_ATTR = 'parentMatrixConstraint'
PARENT_CONSTRAINT_OBJECT_ATTR = 'parentConstraintObject'


def _create_matrix_constraint_base():
    """
    The two nodes every matrix constraint is made of, wired to each other and tagged.

    :return: The ``multMatrix`` and the ``decomposeMatrix``.
    :rtype: list(pm.nt.MultMatrix, pm.nt.DecomposeMatrix)
    """

    m_matrix = pm.createNode(pm.nt.MultMatrix)
    d_matrix = pm.createNode(pm.nt.DecomposeMatrix)

    m_matrix.addAttr(MATRIX_CONSTRAINT_TAG, at='bool', dv=True)
    d_matrix.addAttr(MATRIX_CONSTRAINT_TAG, at='bool', dv=True)

    m_matrix.matrixSum >> d_matrix.inputMatrix
    return [m_matrix, d_matrix]


def get_matrix_constraint_group(child_obj):
    """
    The outer group of the matrix constraint on an object, if it has one.

    :param pm.nt.Transform child_obj: The object to ask about.
    :return: The group, or None when the object is not matrix constrained.
    :rtype: pm.nt.Transform
    """

    if not child_obj.hasAttr(PARENT_CONSTRAINT_ATTR):
        return None
    group = child_obj.attr(PARENT_CONSTRAINT_ATTR).get()
    if group is None or not pm.objExists(group):
        # The markup outlived the constraint - a group deleted by hand, say.
        return None
    return group


def matrix_constraint(parent_obj, child_obj, mo=True, t=True, r=True, s=True):
    """
    Drive a child from a parent through a matrix network rather than a constraint node.

    :param pm.nt.Transform parent_obj: The object to follow.
    :param pm.nt.Transform child_obj: The object that follows it.
    :param bool mo: Keep the offset the two are at now.
    :param bool t: Follow in translation.
    :param bool r: Follow in rotation.
    :param bool s: Follow in scale.
    :return: The nodes that were made, under ``multi_matrix``, ``decomp_matrix``,
        ``constraint_group`` and ``parent_constraint_group``.
    :rtype: dict
    """

    if get_matrix_constraint_group(child_obj) is not None:
        # The groups would be reused and the new matrix nodes would quietly replace the old
        # pair's connections, leaving them in the scene driving nothing.
        logger.debug('%s already had a matrix constraint on it; it was removed before the new '
                     'one was built.', child_obj)
        remove_matrix_constraint(child_obj)

    # The inner group takes the decomposed motion; the outer one is what the network measures
    # against, so the inner group's values stay readable rather than including its own result.
    matrix_grp = groups.create_aligned_parent_group(child_obj,
                                                    suffix='matrix_constraint',
                                                    attr_name=CONSTRAINT_ATTR,
                                                    obj_attr=CONSTRAINT_OBJECT_ATTR)
    matrix_parent_grp = groups.create_aligned_parent_group(matrix_grp,
                                                           suffix='matrix_constraint',
                                                           attr_name=CONSTRAINT_ATTR,
                                                           obj_attr=CONSTRAINT_OBJECT_ATTR)
    child_name = naming.get_basename(child_obj)
    pm.rename(matrix_parent_grp, '{0}_constraint_parent_grp'.format(child_name))

    m_matrix, d_matrix = _create_matrix_constraint_base()
    parent_name = naming.get_basename(parent_obj)
    m_matrix.rename('{0}_multi_matrix'.format(parent_name))
    d_matrix.rename('{0}_decomp_matrix'.format(parent_name))

    # matrixIn[0] is left for the offset set below. The product is then the parent's world
    # matrix brought into the outer group's space.
    parent_obj.worldMatrix[0] >> m_matrix.matrixIn[1]
    matrix_parent_grp.worldInverseMatrix[0] >> m_matrix.matrixIn[2]

    if mo:
        # A throwaway multMatrix works out where the child sits relative to the parent right
        # now, and that offset is baked in as a static value.
        temp_matrix = pm.createNode(pm.nt.MultMatrix)
        matrix_grp.worldMatrix[0] >> temp_matrix.matrixIn[0]
        parent_obj.worldInverseMatrix[0] >> temp_matrix.matrixIn[1]
        m_matrix.matrixIn[0].set(temp_matrix.matrixSum.get())
        pm.delete(temp_matrix)

    if t:
        d_matrix.outputTranslate >> matrix_grp.translate
    if r:
        d_matrix.outputRotate >> matrix_grp.rotate
    if s:
        d_matrix.outputScale >> matrix_grp.scale

    if not child_obj.hasAttr(PARENT_CONSTRAINT_ATTR):
        child_obj.addAttr(PARENT_CONSTRAINT_ATTR, at='message')
    if not child_obj.hasAttr(PARENT_CONSTRAINT_OBJECT_ATTR):
        child_obj.addAttr(PARENT_CONSTRAINT_OBJECT_ATTR, dt='string')

    matrix_parent_grp.attr(CONSTRAINT_OBJECT_ATTR) >> child_obj.attr(PARENT_CONSTRAINT_ATTR)
    child_obj.attr(PARENT_CONSTRAINT_OBJECT_ATTR).set(str(matrix_parent_grp))

    return {'multi_matrix': m_matrix,
            'decomp_matrix': d_matrix,
            'constraint_group': matrix_grp,
            'parent_constraint_group': matrix_parent_grp}

def _connected_matrix_nodes(*nodes):
    """
    Every tagged matrix node reachable from the given nodes through other tagged matrix nodes.

    The walk only ever steps onto a ``multMatrix`` or a ``decomposeMatrix`` carrying
    :data:`MATRIX_CONSTRAINT_TAG`, so it cannot wander out into the rig through the parent the
    constraint is reading.

    :param nodes: Where to start - the constraint's groups.
    :return: The matrix nodes, in the order they were found.
    :rtype: list(pm.PyNode)
    """

    found = []
    seen = set()
    to_walk = [node for node in nodes if node is not None and pm.objExists(node)]
    while to_walk:
        node = to_walk.pop()
        for other in (node.listConnections(type=(pm.nt.MultMatrix, pm.nt.DecomposeMatrix)) or []):
            if other in seen:
                continue
            seen.add(other)
            if other.hasAttr(MATRIX_CONSTRAINT_TAG):
                found.append(other)
                to_walk.append(other)
    return found


def remove_matrix_constraint(child_obj):
    """
    Take a matrix constraint off an object and leave nothing of it behind.

    The object keeps the pose it is in: it is parented back to whatever was above the
    constraint's outer group, which bakes the offset it was being held at into its own channels.
    Both groups go, both matrix nodes go, and the two attributes that marked the object as
    constrained go with them.

    :param pm.nt.Transform child_obj: The object that is being driven.
    :return: True when a constraint was found and removed.
    :rtype: bool
    """

    constraint_grp = get_matrix_constraint_group(child_obj)
    if constraint_grp is None:
        # Still worth clearing any markup left over from a group somebody deleted by hand.
        removed_markup = _remove_constraint_markup(child_obj)
        logger.debug('%s has no matrix constraint on it%s.', child_obj,
                     ', but it was still marked as having one' if removed_markup else '')
        return False

    # Collected before anything is deleted: once the groups go, so do the connections that
    # lead to the matrix nodes.
    matrix_node_list = _connected_matrix_nodes(constraint_grp, child_obj.getParent())

    original_parent = constraint_grp.getParent()
    if original_parent:
        pm.parent(child_obj, original_parent)
    else:
        pm.parent(child_obj, world=True)

    # Deleting the outer group takes the inner one with it, and usually the matrix nodes too -
    # they are the inner group's history, and Maya's delete follows history. Usually, not
    # always: with t, r and s all off, nothing connects them to a transform. So whatever is
    # still standing afterwards is deleted by name.
    pm.delete(constraint_grp)
    left_over = [node for node in matrix_node_list if pm.objExists(node)]
    if left_over:
        pm.delete(left_over)

    _remove_constraint_markup(child_obj)
    return True


def _remove_constraint_markup(child_obj):
    """
    Take the two "this object is matrix constrained" attributes off an object.

    :param pm.nt.Transform child_obj: The object to clean.
    :return: True when there was something to take off.
    :rtype: bool
    """

    removed = False
    for attr_name in (PARENT_CONSTRAINT_ATTR, PARENT_CONSTRAINT_OBJECT_ATTR):
        if child_obj.hasAttr(attr_name):
            child_obj.attr(attr_name).unlock()
            child_obj.deleteAttr(attr_name)
            removed = True
    return removed
