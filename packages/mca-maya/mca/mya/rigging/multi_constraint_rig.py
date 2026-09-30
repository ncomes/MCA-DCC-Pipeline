"""
A multi-target constraint: one control that can follow any of several parents.

The matrix version of a space switch. Where :mod:`space_switch_rig` builds a point and an orient
constraint per target and picks between their weights, this builds one matrix constraint and swaps
what feeds it: a ``choice`` node picks the target's world matrix, a second ``choice`` node picks the
offset that was baked for that target, and both are driven by the same enum. So the number of nodes
does not grow with the number of targets, and the switch is exact rather than a weighted blend.

What was wrong before:

- **A second multi-constraint on the same control raised.** The enum went in with an unguarded
  ``addAttr``, and Maya refuses an attribute that is already there. The channel-box separator
  beside it *was* guarded, which is what makes the omission look like an oversight rather than a
  decision.
- **An empty target list raised on ``target_list[0]``** with nothing said about it.
- **The multMatrix's inputs were disconnected by handing ``disconnectAttr`` the parent of a multi**
  rather than the two elements that are actually connected. The elements are named now, so what is
  being taken apart is on the page.
- The world matrices were connected by their bare array names - ``target.worldMatrix`` rather than
  ``worldMatrix[0]``. Maya picks element zero, so it worked, but a reader has to know that.
- Three separate ``for x in range(len(target_list))`` loops walked the same list; two of them had to
  be separate, because every offset attribute has to exist before any of them is connected, and the
  third folded into the second.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging import matrix_nodes
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The locked bool that draws a line in the channel box above the switch.
SEPARATOR_ATTR = '__'

#: The default name of the enum an animator picks a space with.
SWITCH_ATTR = 'follow'


def multi_constraint(target_list,
                     source_object,
                     switch_obj=None,
                     translate=True,
                     rotate=True,
                     scale=True,
                     switch_attr=SWITCH_ATTR,
                     **kwargs):
    """
    Build a matrix multi-target constraint on a control.

    :param target_list: The parents the control can follow, in the order they appear in the enum.
    :param pm.nt.Transform source_object: The control being constrained.
    :param pm.nt.Transform switch_obj: The node the enum goes on. None means the control itself.
    :param bool translate: Drive translation.
    :param bool rotate: Drive rotation.
    :param bool scale: Drive scale.
    :param str switch_attr: The name of the enum.
    :param dict kwargs: ``t``, ``r`` and ``s`` are older spellings of the three above;
        ``default_name`` renames the first entry in the enum.
    :return: The nodes built, under ``multi_matrix``, ``decomp_matrix``, ``constraint_group``,
        ``parent_constraint_group``, ``choice_offset`` and ``choice_space``. Empty when nothing
        could be built.
    :rtype: dict
    """

    result = {'multi_matrix': None, 'decomp_matrix': None, 'constraint_group': None,
              'parent_constraint_group': None, 'choice_offset': None, 'choice_space': None}

    if not isinstance(target_list, (list, tuple)):
        target_list = [target_list]
    target_list = list(target_list)
    if not target_list:
        logger.warning('A multi constraint needs at least one target to follow.')
        return result

    follow_translate = kwargs.get('t', translate)
    follow_rotate = kwargs.get('r', rotate)
    follow_scale = kwargs.get('s', scale)
    default_name = kwargs.get('default_name', None)
    switch_obj = switch_obj or source_object

    if switch_obj.hasAttr(switch_attr):
        logger.warning('%s already has a %s attribute, so no multi constraint was built on it.',
                       switch_obj, switch_attr)
        return result

    if not switch_obj.hasAttr(SEPARATOR_ATTR):
        switch_obj.addAttr(SEPARATOR_ATTR, keyable=True, at='bool')
        switch_obj.setAttr(SEPARATOR_ATTR, edit=True, channelBox=True, lock=True)

    enum_names = [naming.get_basename(target) for target in target_list]
    if default_name is not None:
        enum_names[0] = default_name
    switch_obj.addAttr(switch_attr, at='enum', en=':'.join(enum_names), keyable=True)

    # Built against the first target; the choice nodes below then swap in whichever the enum picks.
    m_constraint = matrix_nodes.matrix_constraint(target_list[0], source_object, mo=True)
    parent_grp = m_constraint['parent_constraint_group']
    source_grp = m_constraint['constraint_group']
    m_matrix = m_constraint['multi_matrix']
    d_matrix = m_constraint['decomp_matrix']

    source_object_name = naming.get_basename(source_object)
    choice_offset = pm.createNode(pm.nt.Choice, n='choice_{0}_offset'.format(source_object_name))
    choice_space = pm.createNode(pm.nt.Choice, n='choice_{0}_space'.format(source_object_name))
    switch_obj.attr(switch_attr) >> choice_offset.selector
    switch_obj.attr(switch_attr) >> choice_space.selector

    offset_attr_names = ['{0}_offset'.format(naming.get_basename(target)) for target in target_list]

    # Every offset attribute has to exist before any is connected: the choice node's inputs are
    # indexed, and the index has to match the enum's order.
    for attr_name in offset_attr_names:
        if not parent_grp.hasAttr(attr_name):
            parent_grp.addAttr(attr_name, at='matrix')

    for index, target in enumerate(target_list):
        target.worldMatrix[0] >> choice_space.input[index]

        # A throwaway multMatrix works out where the control sits relative to this target right
        # now, and that offset is stored so switching to the target does not move it.
        temp_matrix = pm.createNode(pm.nt.MultMatrix)
        source_grp.worldMatrix[0] >> temp_matrix.matrixIn[0]
        target.worldInverseMatrix[0] >> temp_matrix.matrixIn[1]
        parent_grp.attr(offset_attr_names[index]).set(temp_matrix.matrixSum.get())
        pm.delete(temp_matrix)

        parent_grp.attr(offset_attr_names[index]) >> choice_offset.input[index]

    # Take the fixed wiring matrix_constraint made apart by naming its elements, and put the two
    # choice nodes in its place.
    for element in m_matrix.matrixIn:
        if element.listConnections():
            pm.disconnectAttr(element.listConnections(plugs=True)[0], element)
    choice_offset.output >> m_matrix.matrixIn[0]
    choice_space.output >> m_matrix.matrixIn[1]
    parent_grp.worldInverseMatrix[0] >> m_matrix.matrixIn[2]

    if not follow_translate:
        pm.disconnectAttr(d_matrix.outputTranslate)
    if not follow_rotate:
        pm.disconnectAttr(d_matrix.outputRotate)
    if not follow_scale:
        pm.disconnectAttr(d_matrix.outputScale)

    result.update({'multi_matrix': m_matrix,
                   'decomp_matrix': d_matrix,
                   'constraint_group': source_grp,
                   'parent_constraint_group': parent_grp,
                   'choice_offset': choice_offset,
                   'choice_space': choice_space})
    return result
