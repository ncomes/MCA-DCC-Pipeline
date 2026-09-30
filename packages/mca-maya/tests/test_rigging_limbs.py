"""
The reverse foot and the spline IK, in a real Maya.

    mayapy tests/test_rigging_limbs.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _foot_skeleton(pm):
    """An ankle and a toe, plus the five contact joints a modeller places around the foot."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    ankle = pm.PyNode(cmds.joint(name='b_l_ankle', position=(2, 6, 0), absolute=True))
    toe = pm.PyNode(cmds.joint(name='b_l_toe', position=(2, 1, 4), absolute=True))

    contacts = []
    for name, position in (('b_l_toe_contact', (2, 0, 6)),
                           ('b_l_ball_contact', (2, 0, 3)),
                           ('b_l_ext_contact', (3, 0, 1)),
                           ('b_l_int_contact', (1, 0, 1)),
                           ('b_l_heel_contact', (2, 0, -2))):
        cmds.select(clear=True)
        contacts.append(pm.PyNode(cmds.joint(name=name, position=position, absolute=True)))
    return ankle, toe, contacts


def _spline_skeleton(pm, count=5):
    """A straight chain up Y, plus the three helper joints a spline IK wants."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    chain = [pm.PyNode(cmds.joint(name='b_tail_{0:02d}'.format(index),
                                  position=(0, index * 4, 0), absolute=True))
             for index in range(count)]

    helpers = {}
    for key, position in (('start', (0, 0, 0)),
                          ('mid', (0, (count - 1) * 2, 0)),
                          ('end', (0, (count - 1) * 4, 0))):
        cmds.select(clear=True)
        helpers[key] = pm.PyNode(cmds.joint(name='b_tail_{0}_helper'.format(key),
                                            position=position, absolute=True))
    return chain, helpers


# --------------------------------------------------------------------------------------- #
# reverse_foot_rig
# --------------------------------------------------------------------------------------- #
def check_reverse_foot(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import reverse_foot_rig
    from mca.mya.rigging.flags import frag_flag

    # -- the refusals, which used to be silent -------------------------------------------- #
    harness.new_scene()
    ankle, toe, contacts = _foot_skeleton(pm)
    suite.check('no contact joints is a warning and no foot, not a silent nothing',
                reverse_foot_rig.reverse_foot_chain(ankle, toe, 'left', 'foot') is None)
    suite.check('and a contact joint that is None',
                reverse_foot_rig.reverse_foot_chain(ankle, toe, 'left', 'foot',
                                                    contact_joints=contacts[:4] + [None]) is None)
    suite.check('and the wrong number of them',
                reverse_foot_rig.reverse_foot_chain(ankle, toe, 'left', 'foot',
                                                    contact_joints=contacts[:3]) is None)

    # -- a real foot ----------------------------------------------------------------------- #
    harness.new_scene()
    ankle, toe, contacts = _foot_skeleton(pm)
    result = reverse_foot_rig.reverse_foot_chain(ankle, toe, 'left', 'foot',
                                                contact_joints=contacts)
    suite.check('a foot is built', result is not None)
    suite.check('with six pivots in it',
                len(result['reverse_contact_joints']) == 6,
                str(result['reverse_contact_joints']))
    suite.check('and a two joint reverse chain', len(result['reverse_chain']) == 2)
    suite.check('the duplicated ankle chain is hidden - it is machinery',
                result['chain'][0].visibility.get() is False)
    suite.check('a toe control is made',
                pm.objExists(result['ik_toe_flag']) and
                str(result['ik_toe_flag']) == 'f_l_foot_toe_ik', str(result['ik_toe_flag']))
    suite.check('which only turns', result['ik_toe_flag'].node.translateX.isLocked())

    # The pivots nest in the order the foot rolls through them.
    heel, interior, exterior, ball_pivot, toe_contact, toe_pivot = result['reverse_contact_joints']
    suite.check('the pivots nest toe pivot, toe, ball, exterior, interior, heel',
                [toe_contact.getParent(), ball_pivot.getParent(), exterior.getParent(),
                 interior.getParent(), heel.getParent()] ==
                [toe_pivot, toe_contact, ball_pivot, exterior, interior],
                str([toe_pivot, toe_contact, ball_pivot, exterior, interior, heel]))
    suite.check('with the group above them all',
                toe_pivot.getParent() == result['reverse_foot_grp'])
    suite.check('and the reverse chain hanging off the heel',
                result['reverse_chain'][1].getParent() == heel)

    # -- the attributes an animator uses ---------------------------------------------------- #
    foot_flag = [flag for flag in pm.ls(type=pm.nt.Joint)
                 if frag_flag.is_flag_node(flag) and str(flag) == 'f_left_foot'][0]
    for attr_name in ('ballLift', 'ballPivot', 'toeLift', 'toePivot', 'heelLift', 'footLean'):
        suite.check('the foot control carries {0}'.format(attr_name),
                    foot_flag.hasAttr(attr_name))
    suite.check('and a separator above them',
                foot_flag.hasAttr(reverse_foot_rig.SEPARATOR_ATTR))

    suite.check('heelLift turns the heel pivot',
                bool(heel.rotateZ.listConnections(source=True, destination=False)))
    suite.check('toePivot turns the toe pivot',
                bool(toe_pivot.rotateY.listConnections(source=True, destination=False)))

    # The reverse foot hands the skeleton an orientation, not a position - the ankle's place comes
    # from the leg's IK handle. So what moves is the duplicated chain, and what the original ankle
    # takes from it is its rotation.
    ankle_rotation = pm.xform(ankle, query=True, worldSpace=True, rotation=True)
    duplicated_ankle_position = pm.xform(result['chain'][0], query=True, worldSpace=True,
                                         translation=True)
    cmds.setAttr('{0}.heelLift'.format(foot_flag), 30)
    suite.check('lifting the heel moves the duplicated ankle chain',
                any(abs(now - was) > 0.1 for now, was in
                    zip(pm.xform(result['chain'][0], query=True, worldSpace=True,
                                 translation=True), duplicated_ankle_position)),
                str(pm.xform(result['chain'][0], query=True, worldSpace=True, translation=True)))
    suite.check('and turns the real ankle with it',
                any(abs(now - was) > 0.1 for now, was in
                    zip(pm.xform(ankle, query=True, worldSpace=True, rotation=True),
                        ankle_rotation)),
                str(pm.xform(ankle, query=True, worldSpace=True, rotation=True)))
    cmds.setAttr('{0}.heelLift'.format(foot_flag), 0)

    # -- the lean, split in two by one clamp -------------------------------------------------- #
    suite.check('a clamp splits the lean', result['clamp'] is not None)
    suite.check('negative one way', result['clamp'].minR.get() == -reverse_foot_rig.LEAN_LIMIT)
    suite.check('positive the other', result['clamp'].maxG.get() == reverse_foot_rig.LEAN_LIMIT)
    suite.check('onto the outside of the foot',
                bool(exterior.rotateX.listConnections(source=True, destination=False)))
    suite.check('and the inside',
                bool(interior.rotateX.listConnections(source=True, destination=False)))

    cmds.setAttr('{0}.footLean'.format(foot_flag), 20)
    suite.check('leaning one way turns only the inside joint',
                abs(interior.rotateX.get()) > 1 and abs(exterior.rotateX.get()) < 0.001,
                '{0} and {1}'.format(interior.rotateX.get(), exterior.rotateX.get()))
    cmds.setAttr('{0}.footLean'.format(foot_flag), -20)
    suite.check('and the other way only the outside one',
                abs(exterior.rotateX.get()) > 1 and abs(interior.rotateX.get()) < 0.001,
                '{0} and {1}'.format(exterior.rotateX.get(), interior.rotateX.get()))

    # -- the bug: a second pass over the same control raised ---------------------------------- #
    harness.new_scene()
    ankle, toe, contacts = _foot_skeleton(pm)
    existing = frag_flag.Flag.create(ankle, label='left_foot', add_align_transform=True)
    first = reverse_foot_rig.reverse_foot_chain(ankle, toe, 'left', 'foot',
                                              contact_joints=contacts, ik_foot_flag=existing)
    suite.check('a foot can be built onto a control that already exists', first is not None)
    second = reverse_foot_rig.reverse_foot_chain(ankle, toe, 'left', 'foot',
                                               contact_joints=contacts, ik_foot_flag=existing)
    suite.check('and again onto the same control, without raising on its attributes',
                second is not None)


# --------------------------------------------------------------------------------------- #
# spline_ik_rig
# --------------------------------------------------------------------------------------- #
def check_spline_ik(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import spline_ik_rig

    harness.new_scene()
    suite.check('a chain too short for a spline IK is turned away',
                spline_ik_rig.spline_ctrl([], None, None, 'tail', 'center') == {})

    harness.new_scene()
    chain, helpers = _spline_skeleton(pm)
    result = spline_ik_rig.spline_ctrl(chain, helpers['end'], helpers['mid'], 'tail', 'center',
                                      start_helper_joint=helpers['start'])

    suite.check('a spline IK is built', bool(result))
    suite.check('with a solver on it', result['ik_solver'] is not None)
    suite.check('a curve', pm.objExists(result['curve']))
    suite.check('and five CVs on it, from two spans',
                len(result['curve'].getShape().getCVs()) == 5,
                str(len(result['curve'].getShape().getCVs())))
    suite.check('the curve is skinned to the two end helpers',
                sorted(str(joint) for joint in
                       pm.skinCluster(result['spline_skin_cluster'], query=True, influence=True)) ==
                ['b_tail_end_helper', 'b_tail_start_helper'],
                str(pm.skinCluster(result['spline_skin_cluster'], query=True, influence=True)))

    suite.check('four controls are built - start, end, aux and mid',
                len(result['flag_nodes']) == 4, str(result['flag_nodes']))
    suite.check('the aux control hangs off the end control',
                result['aux_flag'].get_align_transform().getParent() == result['end_flag'])
    suite.check('and the mid control is reported',
                result['mid_flag'] is not None and 'mid' in str(result['mid_flag']))

    # The bug: the cluster was in do_not_touch twice.
    suite.check('nothing is in do_not_touch twice',
                len(result['do_not_touch']) == len(set(result['do_not_touch'])),
                str(result['do_not_touch']))

    # -- stretch --------------------------------------------------------------------------- #
    suite.check('a curveInfo measures the curve', result['info_node'] is not None)
    suite.check('and drives every joint scaleX',
                all(bool(joint.scaleX.listConnections(source=True, destination=False))
                    for joint in chain))

    rest_length = result['info_node'].arcLength.get()
    suite.check('the stretch is measured against the length at build time',
                any(abs(node.input2X.get() - rest_length) < 0.01
                    for node in result['mult_nodes'] if node.hasAttr('input2X')),
                str([node.input2X.get() for node in result['mult_nodes']]))

    result['end_flag'].node.translateY.set(10)
    pm.dgdirty(allPlugs=True)
    suite.check('pulling the end control stretches the chain',
                chain[1].scaleX.get() > 1.0, str(chain[1].scaleX.get()))
    result['end_flag'].node.translateY.set(0)

    # -- retract -------------------------------------------------------------------------------- #
    suite.check('the retract attribute is on the end control',
                result['end_flag'].node.hasAttr('retract'))
    suite.check('running from nought to ten',
                result['end_flag'].node.retract.getMax() == spline_ik_rig.RETRACT_MAX)
    suite.check('with a motion path reading the chain along the curve',
                result['motion_path'] is not None)
    suite.check('a condition holding the end helper at size until it comes in',
                result['condition'] is not None and
                result['condition'].secondTerm.get() == spline_ik_rig.RETRACT_U_THRESHOLD)
    suite.check('and a remap node per joint, plus the handover',
                len(result['remap_nodes']) == len(chain) * 2,
                str(len(result['remap_nodes'])))

    # The bug: the two weights were addressed as '{basename}W0' and '{basename}W1', and
    # get_basename strips the namespace Maya's alias keeps.
    aux_constraint = [node for node in result['parent_cons']
                      if node is not None and
                      isinstance(node, pm.nt.ParentConstraint) and
                      len(node.getWeightAliasList()) == 2]
    suite.check('the two target orientation constraint is found', len(aux_constraint) == 1,
                str(aux_constraint))
    aliases = aux_constraint[0].getWeightAliasList()
    suite.check('both of its weights are driven by the retract',
                all(bool(alias.listConnections(source=True, destination=False))
                    for alias in aliases),
                str([(alias, alias.listConnections()) for alias in aliases]))

    result['end_flag'].node.retract.set(spline_ik_rig.RETRACT_MAX)
    pm.dgdirty(allPlugs=True)
    suite.check('a full retract shrinks the last joint away',
                chain[-1].scaleY.get() < 0.01, str(chain[-1].scaleY.get()))
    suite.check('and pulls it in towards its parent',
                abs(chain[-1].translateX.get()) < 0.01, str(chain[-1].translateX.get()))
    result['end_flag'].node.retract.set(0)

    # -- the optional pieces ------------------------------------------------------------------- #
    harness.new_scene()
    chain, helpers = _spline_skeleton(pm)
    result = spline_ik_rig.spline_ctrl(chain, helpers['end'], helpers['mid'], 'tail', 'center',
                                      mid_flag=False, can_retract=False)
    suite.check('a spline IK can be built without a mid control',
                result['mid_flag'] is None, str(result['mid_flag']))
    suite.check('and without a retract',
                not result['end_flag'].node.hasAttr('retract'))
    suite.check('which leaves those keys out of the result',
                'motion_path' not in result and 'remap_nodes' not in result, str(sorted(result)))
    suite.check('no start control means no start flag',
                result['start_flag'] is None)
    suite.check('but a helper joint is made to skin the curve to',
                result['start_helper_joint'] is not None and
                result['start_helper_joint'] in result['do_not_touch'])

    # -- the bug: asking for a retract twice raised ---------------------------------------------- #
    harness.new_scene()
    chain, helpers = _spline_skeleton(pm)
    result = spline_ik_rig.spline_ctrl(chain, helpers['end'], helpers['mid'], 'tail', 'center')
    second = spline_ik_rig._build_retract(chain, result['end_flag'], None, helpers['end'],
                                         result['curve'].getShape(), 'tail_center_spline_ik')
    suite.check('asking for a second retract on the same control is a warning, not a raise',
                second['motion_path'] is None, str(second))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_reverse_foot(suite, pm)
    check_spline_ik(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_limbs', body))
