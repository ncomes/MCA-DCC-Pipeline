"""
A spline IK with a few more moving parts than Maya's: stretch, and a retract.

Maya's spline IK solver bends a joint chain along a curve. That on its own gives an animator one
control per curve CV and no way to make the chain longer or shorter, which is not enough for a tail,
a tentacle or a cable. So this wraps it:

- The curve is skinned to two helper joints, one at each end, and its middle CV is driven by a
  cluster. So there are three controls - start, end and mid - rather than one per CV.
- **Stretch**: a ``curveInfo`` node measures the curve, and the ratio between its length now and its
  length at build time drives every joint's ``scaleX``. Pull the end control away and the chain
  stretches to reach it instead of sliding off the end of the curve.
- **Retract**: one attribute on the end control that walks the joints back down the curve and shrinks
  them as it goes, each joint owning a slice of the attribute's 0-to-10 range. That is how a tail
  disappears into a body rather than bunching up at the base.
- An auxiliary control on top of the end control, whose orientation the chain's last joint blends
  towards. Two targets on one constraint, because Maya will not interpolate an orientation
  constraint that has one.

What was wrong before:

- **The constraint weights were addressed by a name that is not always the alias.** The retract
  wiring built them as ``'{name}W0'`` and ``'{name}W1'`` from ``naming.get_basename`` - and
  ``get_basename`` strips the namespace, while Maya's alias keeps it. A rig built inside a
  namespace, which is how a rig is built when it is referenced into a scene, raised
  ``AttributeError`` on that line. Maya's own ``getWeightAliasList`` is asked now.
- **``do_not_touch`` held the cluster twice.** It is built from a list that already includes the
  cluster, and then the cluster is appended again a few lines later. Whatever a caller does to that
  list, it did twice to the cluster.
- **``mid_flag`` in the result was set twice, and once to the argument.**
  ``mid_flag_node if mid_flag else mid_flag`` answers the boolean ``False`` when no mid control was
  asked for, rather than None; the line below then overwrote it when there was one. One assignment
  now, and None when there is no control.
- **Asking for a retract twice raised.** ``end_flag.addAttr('retract', ...)`` unguarded.
- **A degenerate curve divided by zero.** The stretch ratio is the curve's length now over its
  length at build time, and nothing looked at the second number.
- The curve's world space was read off the transform in one place and off the shape in another - the
  transform form works only because Maya forwards a shape's attributes through it. The flag scale
  was a bare local called ``sca``. ``mult_node.input1.input1X`` reached a compound's child through
  its parent for no reason. A chain of fewer than two joints walked into ``ikHandle`` and failed
  there rather than being turned away.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging import joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import groups
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: Added to every node this builds, so a spline IK's parts can be told apart in an outliner.
SUFFIX = 'spline_ik'

#: How big the controls are drawn. The auxiliary and mid controls are fractions of it. There is no
#: scale argument - the version this replaces had a bare local called ``sca`` set to 1.0.
FLAG_SCALE = 1.0
AUX_FLAG_SCALE = 0.75
MID_FLAG_SCALE = 0.5

#: Maya's ``multiplyDivide`` operations.
MULTIPLY = 1
DIVIDE = 2

#: Maya's ``condition`` operation for "less than".
CONDITION_LESS_THAN = 4

#: The curve is built with two spans, which gives five CVs - and CV 2 is the middle one, the one the
#: mid control drives through a cluster.
CURVE_SPANS = 2
MIDDLE_CV = 2

#: The retract attribute's range. Each joint owns one slice of it.
RETRACT_MAX = 10

#: The ``uValue`` along the curve past which the end helper joint starts scaling down as the chain
#: retracts, and the number the retract's own ratio is taken against.
RETRACT_U_THRESHOLD = 6

#: How far into the retract range the auxiliary control hands the chain's orientation over to the
#: end control.
AUX_HANDOVER_RANGE = 3.0


def spline_ctrl(spline_joint_chain, end_helper_joint, mid_helper_joint, region, side,
                start_helper_joint=None, mid_flag=True, can_retract=True,
                root_align_transform=True):
    """
    Build a spline IK with stretch, an optional retract, and three or four controls.

    :param list spline_joint_chain: The joints the solver bends, in order, root first.
    :param pm.nt.Joint end_helper_joint: A joint sitting where the chain's last joint is. It skins
        the curve's far end and is what the end control drives.
    :param pm.nt.Joint mid_helper_joint: A joint at the midpoint of the chain. The mid control's
        position is stored on it, which is what lets an animator's work be recovered on a rebuild.
    :param str region: A name for the region.
    :param str side: Which side it is on.
    :param pm.nt.Joint start_helper_joint: A joint co-located with the chain's first joint. None
        makes one, without a control on it.
    :param bool mid_flag: Build the mid control.
    :param bool can_retract: Build the retract.
    :param bool root_align_transform: Give the start and end controls a zeroed group above them.
    :return: The nodes built. Empty when the chain was not usable.
    :rtype: dict
    """

    if not spline_joint_chain or len(spline_joint_chain) < 2:
        logger.warning('A spline IK needs a chain of at least two joints; %s were given.',
                        len(spline_joint_chain or []))
        return {}

    name_prefix = '{0}_{1}_{2}'.format(region, side, SUFFIX)
    constraint_list = []
    flag_list = []

    # The chain's last joint blends between the auxiliary control's orientation and its own, and
    # Maya cannot interpolate an orientation constraint with one target - so there is a third node
    # holding the chain's own orientation for it to blend against.
    orient_end = joint_utils.duplicate_joint(end_helper_joint, '{0}_orient_end'.format(name_prefix))
    orient_end.setParent(None)
    constraint_list.append(constraint.scale_constraint_safe(spline_joint_chain[-1], orient_end))

    start_flag = None
    if start_helper_joint:
        start_flag = frag_flag.Flag.create(start_helper_joint,
                                          label='{0}_start'.format(name_prefix),
                                          add_align_transform=root_align_transform,
                                          is_sub=True)
        start_flag.lock_and_hide_attrs(attr_utils.SCALE_ATTRS)
        start_flag.set_as_detail()
        constraint_list.append(constraint.parent_constraint_safe(start_flag, start_helper_joint))
        flag_list.append(start_flag)
    else:
        # No control at the start, but the curve still needs something to skin its near end to.
        start_helper_joint = joint_utils.duplicate_joint(
            spline_joint_chain[0], '{0}_start_align'.format(name_prefix))
        start_helper_joint.setParent(None)

    end_flag = frag_flag.Flag.create(end_helper_joint, label='{0}_end'.format(name_prefix),
                                     scale=FLAG_SCALE, add_align_transform=root_align_transform)
    end_flag.lock_and_hide_attrs(attr_utils.SCALE_ATTRS)
    # Position and rotation both: the end of a spline IK follows its control completely.
    constraint_list.append(constraint.parent_constraint_safe(end_flag, end_helper_joint))

    end_aux_flag = frag_flag.Flag.create(end_helper_joint,
                                        label='{0}_end_aux'.format(name_prefix),
                                        scale=FLAG_SCALE * AUX_FLAG_SCALE,
                                        add_align_transform=True, is_sub=True)
    end_aux_flag.get_align_transform().setParent(end_flag)
    end_aux_flag.lock_and_hide_attrs(attr_utils.SCALE_ATTRS + attr_utils.TRANSLATION_ATTRS)
    end_aux_flag.set_as_sub()
    end_aux_constraint = constraint.parent_constraint_safe(
        [end_aux_flag, spline_joint_chain[-1]], orient_end)
    constraint_list.append(end_aux_constraint)
    # In reverse order, so the list lines up with the bind joints FRAG holds.
    flag_list.append(end_aux_flag)
    flag_list.append(end_flag)

    spline_ik_handle, spline_ik_eff, spline_ik_curve = pm.ikHandle(
        sol='ikSplineSolver', n='{0}_ikHandle'.format(name_prefix), ccv=True,
        numSpans=CURVE_SPANS, startJoint=spline_joint_chain[0],
        endEffector=spline_joint_chain[-1])
    spline_ik_curve.rename('{0}_curve'.format(name_prefix))
    curve_shape = spline_ik_curve.getShape()
    ik_solver = spline_ik_handle.ikSolver.get()

    chain_grp = groups.create_align_transform(spline_joint_chain[0])
    if start_flag:
        constraint_list.append(constraint.parent_constraint_safe(start_flag, chain_grp, mo=True))

    # Two influences only. The middle of the curve is the cluster's job, not a joint's.
    skin_cluster = pm.skinCluster([start_helper_joint, end_helper_joint], spline_ik_curve,
                                  n='{0}_skinCluster'.format(name_prefix),
                                  toSelectedBones=True, bindMethod=0, skinMethod=0,
                                  normalizeWeights=1)

    cluster_handle = None
    mid_flag_node = None
    if mid_flag:
        cluster_handle = pm.cluster(spline_ik_curve.cv[MIDDLE_CV],
                                    n='{0}_cluster'.format(name_prefix))[1]
        cluster_handle.visibility.set(False)

        mid_flag_node = frag_flag.Flag.create(cluster_handle,
                                             label='{0}_mid'.format(name_prefix),
                                             scale=FLAG_SCALE * MID_FLAG_SCALE,
                                             add_align_transform=True, is_sub=True)
        mid_flag_node.lock_and_hide_attrs(attr_utils.SCALE_ATTRS + attr_utils.ROTATION_ATTRS)
        flag_list.append(mid_flag_node)
        constraint_list.append(constraint.parent_constraint_safe(mid_flag_node, mid_helper_joint))
        # Connected rather than constrained: a constraint on a cluster handle gives odd results.
        mid_flag_node.node.translate >> cluster_handle.translate
        mid_flag_node.node.rotate >> cluster_handle.rotate

    stretch = _build_stretch(spline_joint_chain, curve_shape, name_prefix)

    retract = {}
    if can_retract:
        retract = _build_retract(spline_joint_chain, end_flag, end_aux_constraint, end_helper_joint,
                                 curve_shape, name_prefix)

    do_not_touch = [node for node in (orient_end, spline_ik_handle, spline_ik_curve,
                                      cluster_handle) if node]
    if not start_flag:
        do_not_touch.append(start_helper_joint)

    result = {'flag_nodes': flag_list,
              'start_flag': start_flag,
              'mid_flag': mid_flag_node,
              'end_flag': end_flag,
              'aux_flag': end_aux_flag,
              'orient_end': orient_end,
              'parent_cons': constraint_list,
              'curve': spline_ik_curve,
              'handle': spline_ik_handle,
              'do_not_touch': do_not_touch,
              'start_helper_joint': start_helper_joint,
              'spline_skin_cluster': skin_cluster,
              'mult_nodes': stretch['mult_nodes'] + retract.get('mult_nodes', []),
              'info_node': stretch['info_node'],
              'ik_solver': ik_solver}

    if can_retract:
        result['remap_nodes'] = retract['remap_nodes']
        result['motion_path'] = retract['motion_path']
        result['condition'] = retract['condition']
        result['reverse_nodes'] = retract['reverse_node']
    return result


def _build_stretch(spline_joint_chain, curve_shape, name_prefix):
    """
    Make every joint's length follow the curve's.

    The ratio of the curve's length now to its length at build time, straight onto ``scaleX`` - so
    the chain reaches the end control instead of sliding off the end of the curve.

    :param list spline_joint_chain: The joints.
    :param pm.nt.NurbsCurve curve_shape: The solver's curve.
    :param str name_prefix: What to call the nodes.
    :return: The nodes built, under ``mult_nodes`` and ``info_node``.
    :rtype: dict
    """

    info_node = pm.createNode('curveInfo', n='{0}_curve_info'.format(name_prefix))
    curve_shape.worldSpace >> info_node.inputCurve

    rest_length = info_node.arcLength.get()
    mult_node = pm.createNode('multiplyDivide', n='{0}_multi_stretch'.format(name_prefix))
    info_node.arcLength >> mult_node.input1X
    mult_node.operation.set(DIVIDE)

    if not rest_length:
        # Nothing looked at this before, and dividing by it gives every joint a scale of nan.
        logger.warning('The spline curve for %s has no length, so the stretch would divide by '
                        'zero. Every joint is left at scale 1.', name_prefix)
        mult_node.input2X.set(1)
    else:
        mult_node.input2X.set(rest_length)
        for joint_node in spline_joint_chain:
            mult_node.outputX >> joint_node.scaleX

    return {'mult_nodes': [mult_node], 'info_node': info_node}


def _build_retract(spline_joint_chain, end_flag, end_aux_constraint, end_helper_joint, curve_shape,
                   name_prefix):
    """
    Walk the chain back down its curve and shrink it as it goes.

    One attribute, 0 to 10, sliced up so that each joint travels and shrinks over its own part of
    the range - the last joint first. As it goes the chain also hands its orientation from the
    auxiliary control back to the end control, because an auxiliary control aiming a joint that has
    retracted into its parent has nothing useful to aim.

    :param list spline_joint_chain: The joints.
    :param end_flag: The control the attribute goes on.
    :param end_aux_constraint: The two-target orientation constraint to blend.
    :param pm.nt.Joint end_helper_joint: The joint that skins the curve's far end.
    :param pm.nt.NurbsCurve curve_shape: The solver's curve.
    :param str name_prefix: What to call the nodes.
    :return: The nodes built.
    :rtype: dict
    """

    flag_node = end_flag.node
    if flag_node.hasAttr('retract'):
        logger.warning('%s already has a retract attribute, so no retract was built.', flag_node)
        return {'remap_nodes': [], 'mult_nodes': [], 'motion_path': None, 'condition': None,
                'reverse_node': None}

    flag_node.addAttr('retract', dv=0, min=0, max=RETRACT_MAX, k=True)

    # Where the chain's last joint has got to along the curve, as a number the nodes below can read.
    motion_path = pm.createNode('motionPath', n='{0}_mp'.format(name_prefix))
    spline_joint_chain[-1].translateX >> motion_path.uValue
    curve_shape.worldSpace >> motion_path.geometryPath

    mult_node = pm.createNode('multiplyDivide', n='{0}_multi_retract'.format(name_prefix))
    mult_node.operation.set(DIVIDE)
    motion_path.uValue >> mult_node.input1X
    mult_node.input2X.set(RETRACT_U_THRESHOLD)

    # Only shrink the end helper once the chain has come in past the threshold; before that it
    # stays at full size.
    condition = pm.createNode('condition', n='{0}_condition'.format(name_prefix))
    motion_path.uValue >> condition.firstTerm
    mult_node.outputX >> condition.colorIfTrueR
    condition.secondTerm.set(RETRACT_U_THRESHOLD)
    condition.operation.set(CONDITION_LESS_THAN)
    condition.outColorR >> end_helper_joint.scaleY
    condition.outColorR >> end_helper_joint.scaleZ

    # Hand the chain's orientation from the auxiliary control to the end control over the first
    # part of the retract.
    remap_nodes = []
    aux_con_remap = pm.createNode('remapValue', n='{0}_constraint_remap'.format(name_prefix))
    remap_nodes.append(aux_con_remap)
    aux_con_remap.inputMin.set(0.0)
    aux_con_remap.inputMax.set(AUX_HANDOVER_RANGE)
    aux_con_remap.outputMin.set(1.0)
    # Not quite zero: a constraint with every weight at zero has no opinion at all, and the joint
    # snaps to whatever its own transform says.
    aux_con_remap.outputMax.set(0.01)

    reverse_node = pm.createNode('reverse', n='{0}_constraint_reverse'.format(name_prefix))
    aux_con_remap.outValue >> reverse_node.inputX
    flag_node.retract >> aux_con_remap.inputValue

    # Asked for rather than spelled out. Building the alias as '{basename}W0' is wrong for a
    # target in a namespace, because get_basename strips what Maya's alias keeps.
    weight_aliases = end_aux_constraint.getWeightAliasList() if end_aux_constraint else []
    if len(weight_aliases) >= 2:
        aux_con_remap.outValue >> weight_aliases[0]
        reverse_node.outputX >> weight_aliases[1]
    else:
        logger.warning('The orientation constraint on the end of %s does not have two targets, so '
                        'the retract cannot hand the orientation over.', name_prefix)

    # Each joint owns one slice of the range, so they come in one after another rather than all at
    # once.
    increment_value = float(RETRACT_MAX) / len(spline_joint_chain)
    for index, chain_joint in enumerate(spline_joint_chain):
        if index:
            # The joint sits at its own length until the retract reaches its slice, then shortens.
            remap_tx = pm.createNode(
                'remapValue',
                n='{0}_{1}_remap_tx'.format(naming.get_basename(chain_joint), SUFFIX))
            remap_nodes.append(remap_tx)
            flag_node.retract >> remap_tx.inputValue
            remap_tx.outputMin.set(chain_joint.translateX.get())
            remap_tx.outputMax.set(0.001)
            remap_tx.inputMin.set((index - 1.0) * increment_value)
            remap_tx.inputMax.set(index * increment_value)
            remap_tx.outValue >> chain_joint.translateX

        remap_sca = pm.createNode(
            'remapValue',
            n='{0}_{1}_remap_scale'.format(naming.get_basename(chain_joint), SUFFIX))
        remap_nodes.append(remap_sca)
        flag_node.retract >> remap_sca.inputValue
        remap_sca.outputMin.set(1)
        remap_sca.outputMax.set(0)
        # The scale slices start one joint later than the translation ones and are capped short of
        # the end of the range, so the last joints have finished shrinking before retract hits 10.
        remap_sca.inputMin.set(min((index + 1) * increment_value,
                                   RETRACT_MAX - increment_value * 1.25))
        remap_sca.inputMax.set(min((index + 2) * increment_value,
                                   RETRACT_MAX - increment_value * 0.75))
        remap_sca.outValue >> chain_joint.scaleY
        remap_sca.outValue >> chain_joint.scaleZ

    return {'remap_nodes': remap_nodes,
            'mult_nodes': [mult_node],
            'motion_path': motion_path,
            'condition': condition,
            'reverse_node': reverse_node}
