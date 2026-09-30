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
- ``remove_matrix_constraint`` had no callers anywhere in the pipeline, and left the two message
  attributes behind on the object it unpicked while clearing the artist's selection on its way
  out. Gone; deleting the constraint group by hand does the same thing.
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
