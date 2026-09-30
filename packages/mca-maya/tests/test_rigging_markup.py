"""
Skeleton markup: ma_consts, chain_markup and joint_utils, in a real Maya.

    mayapy tests/test_rigging_markup.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _chain(names_and_positions, prefix=''):
    """A joint chain, root first, each joint a child of the one before."""

    import maya.cmds as cmds
    import pymel.core as pm

    cmds.select(clear=True)
    joints = []
    for name, position in names_and_positions:
        joints.append(pm.PyNode(cmds.joint(name=prefix + name, position=position, absolute=True)))
    return joints


def _arm_skeleton(pm):
    """
    A root, an arm that ends at the wrist, and a hand under it.

    The wrist is the case the chain lookup used to crash on: it belongs to the arm and names the
    hand as the region it ends.
    """

    from mca.mya.rigging import chain_markup

    root, shoulder, elbow, wrist, hand, palm, finger = _chain([
        ('root', (0, 0, 0)), ('shoulder', (2, 10, 0)), ('elbow', (5, 10, 0)),
        ('wrist', (8, 10, 0)), ('hand', (9, 10, 0)), ('palm', (10, 10, 0)),
        ('finger', (11, 10, 0))])

    for joint_node, side, region in ((root, 'center', 'root'),
                                     (shoulder, 'left', 'arm'), (elbow, 'left', 'arm'),
                                     (wrist, 'left', 'arm'), (hand, 'left', 'hand'),
                                     (palm, 'left', 'hand'), (finger, 'left', 'hand')):
        markup = chain_markup.JointMarkup(joint_node)
        markup.side = side
        markup.region = region

    chain_markup.JointMarkup(shoulder).chainStart = 'arm'
    chain_markup.JointMarkup(shoulder).hierarchyStart = True
    # The wrist belongs to the arm and is marked as ending the hand chain, which is the case the
    # cross-region branch of the parse exists for - and the case it used to crash on, because the
    # hand's own joints are walked after the wrist.
    chain_markup.JointMarkup(wrist).chainEnd = 'hand'
    chain_markup.JointMarkup(hand).chainStart = 'hand'
    return {'root': root, 'shoulder': shoulder, 'elbow': elbow, 'wrist': wrist,
            'hand': hand, 'palm': palm, 'finger': finger}


# --------------------------------------------------------------------------------------- #
# ma_consts
# --------------------------------------------------------------------------------------- #
def check_ma_consts(suite, pm):
    from mca.mya.startup.configs import ma_consts

    suite.check("Maya's side enum is in Maya's order",
                ma_consts.SIDE_LABELS == ['Center', 'Left', 'Right', 'None'],
                str(ma_consts.SIDE_LABELS))
    suite.check('the third-party constant is spelled properly now',
                hasattr(ma_consts, 'THIRDPARTY') and not hasattr(ma_consts, 'THRIDPARTY'))
    suite.check('and names the same environment variable as before',
                ma_consts.THIRDPARTY == 'MCA_THIRDPARTY_PATH', ma_consts.THIRDPARTY)
    suite.check('the two constants nothing read are gone',
                not hasattr(ma_consts, 'PARENT_SEPARATOR') and
                not hasattr(ma_consts, 'JOINT_TYPE_LABELS'))
    suite.check('the docstring is about this module',
                (ma_consts.__doc__ or '').strip().startswith('Names and tables'),
                (ma_consts.__doc__ or '').strip()[:60])


# --------------------------------------------------------------------------------------- #
# JointMarkup
# --------------------------------------------------------------------------------------- #
def check_joint_markup(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    harness.new_scene()
    joint_node = pm.joint(name='a_joint')
    markup = chain_markup.JointMarkup(joint_node)

    # -- side --------------------------------------------------------------------------- #
    suite.check("an unmarked joint falls back to Maya's own side enum",
                markup.side == 'center', markup.side)
    joint_node.side.set(1)
    suite.check('which follows what Maya says', markup.side == 'left', markup.side)

    markup.side = 'Right'
    suite.check('a side written by name comes back in lower case',
                markup.side == 'right', markup.side)
    suite.check('and is stored as markup', joint_node.hasAttr(chain_markup.SIDE_ATTR))
    markup.side = 2
    suite.check('a side written as an index reads off the same table',
                markup.side == 'right', markup.side)
    markup.side = None
    suite.check('anything else is refused and the side is left alone',
                markup.side == 'right', markup.side)

    # -- region ------------------------------------------------------------------------- #
    suite.check('an unmarked joint has no region', markup.region is None, str(markup.region))
    markup.region = 'spine'
    suite.check('a region comes back as written', markup.region == 'spine')

    harness.new_scene()
    markup = chain_markup.JointMarkup(pm.joint(name='chain_named'))
    markup.chainTwist = 'forearm_twist'
    suite.check('a joint with no region takes one from its chain markup',
                markup.region == 'forearm_twist', str(markup.region))

    # -- chain markings ------------------------------------------------------------------ #
    harness.new_scene()
    joint_node = pm.joint(name='chain_joint')
    markup = chain_markup.JointMarkup(joint_node)

    suite.check('an unmarked joint starts no chain', markup.chainStart is False)
    suite.check('and ends none', markup.chainEnd is False)
    suite.check('and twists none', markup.chainTwist is False)

    markup.chainStart = 'arm'
    suite.check('marking a chain start records the region it starts',
                markup.chainStart == 'arm')
    suite.check('and names the joint region with it', markup.region == 'arm')

    # The bug: clearing a marking on a joint that has it went through Attribute.delete(), and on
    # a joint that does not have it fell through to setting an attribute it had just decided not
    # to create - AttributeError.
    markup.chainStart = ''
    suite.check('clearing a chain start takes the attribute off',
                not joint_node.hasAttr(chain_markup.CHAIN_START_ATTR))
    suite.check('and leaves the region behind, which is still true', markup.region == 'arm')
    markup.chainStart = ''
    suite.check('and clearing it again is not an error either', markup.chainStart is False)

    harness.new_scene()
    bare = chain_markup.JointMarkup(pm.joint(name='bare_joint'))
    bare.chainStart = ''
    suite.check('clearing a chain start that was never there does nothing, quietly',
                bare.chainStart is False)
    bare.chainEnd = ''
    suite.check('and the same for a chain end', bare.chainEnd is False)
    bare.chainTwist = ''
    suite.check('and a twist', bare.chainTwist is False)

    # The bug: skelRegion was only created in the branch where chainStart was missing.
    harness.new_scene()
    joint_node = pm.joint(name='half_marked')
    joint_node.addAttr(chain_markup.CHAIN_START_ATTR, dt='string')
    joint_node.attr(chain_markup.CHAIN_START_ATTR).set('leg')
    markup = chain_markup.JointMarkup(joint_node)
    markup.chainStart = 'leg'
    suite.check('a joint marked as a chain start but missing its region gets one',
                markup.region == 'leg', str(markup.region))

    # -- export flags: the bug ------------------------------------------------------------ #
    harness.new_scene()
    joint_node = pm.joint(name='export_joint')
    markup = chain_markup.JointMarkup(joint_node)

    suite.check('a joint nobody has marked is exported', markup.is_sk_export is True)
    suite.check('and animated', markup.is_animation_export is True)
    # Reading used to add the attribute as a side effect of the question.
    suite.check('and reading that did not write anything to the scene',
                not joint_node.hasAttr(chain_markup.SK_EXPORT_ATTR) and
                not joint_node.hasAttr(chain_markup.ANIMATION_EXPORT_ATTR))

    markup.is_sk_export = False
    suite.check('a joint ticked out of the skeletal mesh export stays out',
                markup.is_sk_export is False)
    suite.check('because the answer is stored rather than deleted',
                joint_node.hasAttr(chain_markup.SK_EXPORT_ATTR))
    markup.is_animation_export = False
    suite.check('and the same for the animation export', markup.is_animation_export is False)

    markup.is_sk_export = True
    suite.check('and it can be put back', markup.is_sk_export is True)

    # -- hierarchy start ------------------------------------------------------------------ #
    harness.new_scene()
    joint_node = pm.joint(name='hierarchy_joint')
    markup = chain_markup.JointMarkup(joint_node)
    suite.check('a joint is not the hierarchy start unless it says so',
                markup.hierarchyStart is False)
    markup.hierarchyStart = True
    suite.check('marking it works', markup.hierarchyStart is True)
    # The bug: addAttr went in unguarded, so this raised.
    markup.hierarchyStart = True
    suite.check('and marking it twice is not an error', markup.hierarchyStart is True)
    markup.hierarchyStart = False
    suite.check('unmarking it takes the attribute off',
                markup.hierarchyStart is False and
                not joint_node.hasAttr(chain_markup.HIERARCHY_START_ATTR))

    # -- reading the joint ----------------------------------------------------------------- #
    harness.new_scene()
    pm.namespace(add='rig_ns')
    pm.namespace(set='rig_ns')
    parent_joint = pm.joint(name='parent_joint')
    child_joint = pm.joint(name='child_joint', position=(0, 5, 0), absolute=True)
    pm.namespace(set=':')
    markup = chain_markup.JointMarkup(child_joint)

    suite.check('the name comes back without its namespace',
                markup.name == 'child_joint', markup.name)
    suite.check('the world matrix is sixteen numbers', len(markup.get_world_matrix()) == 16)
    suite.check('the parent comes back wrapped when it is a joint',
                isinstance(markup.getParent(), chain_markup.JointMarkup))
    suite.check('pointing at the right joint', markup.getParent().joint == parent_joint)
    suite.check('the children come back wrapped',
                [wrapped.joint for wrapped in chain_markup.JointMarkup(parent_joint).getChildren()]
                == [child_joint])

    group = pm.group(empty=True, name='a_group')
    pm.parent(parent_joint, group)
    suite.check('a parent that is not a joint comes back raw',
                chain_markup.JointMarkup(parent_joint).getParent() == group)

    for gone in ('remove_is_start', 'remove_is_end'):
        suite.check('{0} had no callers and is gone'.format(gone),
                    not hasattr(chain_markup.JointMarkup, gone))


# --------------------------------------------------------------------------------------- #
# ChainMarkup
# --------------------------------------------------------------------------------------- #
def check_chain_markup(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup

    harness.new_scene()
    skeleton = _arm_skeleton(pm)

    # The bug: a wrist in the arm region with chainEnd='hand' files its end under the hand,
    # building that entry with no 'joints' key - and the next hand joint with neither marking
    # then raised KeyError: 'joints'. Reproduced from this exact order: wrist, hand, palm.
    chain_data = chain_markup.ChainMarkup(skeleton['root'])
    suite.check('a chain end belonging to the next region does not break the parse',
                chain_data.chain.get('hand', {}).get('left') is not None,
                str(list(chain_data.chain)))
    suite.check('the hand keeps its middle joints',
                chain_data.chain['hand']['left']['joints'] ==
                [skeleton['palm'], skeleton['finger']],
                str(chain_data.chain['hand']['left']))

    suite.check('the arm chain starts at the shoulder',
                chain_data.get_start('arm', 'left') == skeleton['shoulder'])
    suite.check('the hand chain is ended by the wrist, which is an arm joint',
                chain_data.get_end('hand', 'left') == skeleton['wrist'])
    suite.check('a chain comes back as a pair',
                chain_data.get_chain('hand', 'left') == (skeleton['hand'], skeleton['wrist']),
                str(chain_data.get_chain('hand', 'left')))
    suite.check('a region nobody marked up answers None',
                chain_data.get_chain('tail', 'left') is None)
    suite.check('the full hand chain is start, middles, end',
                chain_data.get_full_chain('hand', 'left') ==
                [skeleton['hand'], skeleton['palm'], skeleton['finger'], skeleton['wrist']],
                str(chain_data.get_full_chain('hand', 'left')))
    suite.check('and a lookup that matches nothing is an empty list with a warning',
                chain_data.get_full_chain('tail', 'left') == [])

    suite.check('the hierarchy start is found',
                chain_data.hierarchyStart == skeleton['shoulder'])
    suite.check('every joint is walked, the root included',
                len(chain_data.joints) == 7, str(len(chain_data.joints)))
    suite.check('the root is what it was given', chain_data.root == skeleton['root'])

    # -- the bug: reading the markup wrote to the scene ------------------------------------ #
    suite.check('building a ChainMarkup adds no attributes to the skeleton',
                not any(joint.hasAttr(chain_markup.SK_EXPORT_ATTR) or
                        joint.hasAttr(chain_markup.ANIMATION_EXPORT_ATTR)
                        for joint in chain_data.joints))

    # -- the export lists ------------------------------------------------------------------- #
    suite.check('with nothing ticked out, the export lists are the whole skeleton',
                len(chain_data.sk_joints) == 7 and len(chain_data.animation_joints) == 7,
                '{0} and {1}'.format(len(chain_data.sk_joints), len(chain_data.animation_joints)))

    chain_markup.JointMarkup(skeleton['palm']).is_sk_export = False
    chain_data = chain_markup.ChainMarkup(skeleton['root'])
    # The bug: a joint ticked out came back in, because storing False deleted the attribute and
    # reading it created it again as True. These lists were the whole skeleton, every time.
    suite.check('a joint ticked out of the skeletal mesh export stays out of the list',
                skeleton['palm'] not in chain_data.sk_joints, str(chain_data.sk_joints))
    suite.check('but is still in the hierarchy', skeleton['palm'] in chain_data.joints)
    suite.check('and still in the animation export, which was not touched',
                skeleton['palm'] in chain_data.animation_joints)

    # -- validity ---------------------------------------------------------------------------- #
    harness.new_scene()
    skeleton = _arm_skeleton(pm)
    stray = pm.joint(name='unmarked_joint', position=(20, 0, 0), absolute=True)
    pm.parent(stray, skeleton['root'])
    chain_data = chain_markup.ChainMarkup(skeleton['root'])
    suite.check('a joint with no region makes the skeleton invalid', chain_data.is_valid is False)
    suite.check('and it is named, so it can be fixed',
                chain_data.invalid_joints == [stray], str(chain_data.invalid_joints))

    # The bug: _invalid_joints was never cleared, so parsing again appended to the first pass.
    chain_data.parse_joints()
    suite.check('parsing twice gives the same answer as parsing once',
                chain_data.invalid_joints == [stray], str(chain_data.invalid_joints))

    harness.new_scene()
    skeleton = _arm_skeleton(pm)
    chain_data = chain_markup.ChainMarkup(skeleton['root'])
    suite.check('a fully marked up skeleton is valid', chain_data.is_valid is True)

    # -- twist joints --------------------------------------------------------------------- #
    harness.new_scene()
    skeleton = _arm_skeleton(pm)
    twist = pm.joint(name='forearm_twist_01', position=(6, 10, 0), absolute=True)
    pm.parent(twist, skeleton['elbow'])
    twist_markup = chain_markup.JointMarkup(twist)
    twist_markup.side = 'left'
    twist_markup.chainTwist = 'forearm'
    chain_data = chain_markup.ChainMarkup(skeleton['root'])
    suite.check('a twist joint is filed under its side and chain',
                chain_data.twist_joints['left']['forearm']['joints'] == [twist],
                str(chain_data.twist_joints))
    suite.check('with the joint it hangs off',
                chain_data.twist_joints['left']['forearm']['parent'] == skeleton['elbow'])

    # -- the skeleton lookup ---------------------------------------------------------------- #
    suite.check('the skeleton dictionary files the root under a fixed key',
                chain_data.skeleton_dict['root'] == skeleton['root'])
    suite.check('and every other joint under its own name',
                chain_data.skeleton_dict['wrist'] == skeleton['wrist'])
    suite.check('asking again gives the same dictionary',
                chain_data.skeleton_dict is chain_data.skeleton_dict)


# --------------------------------------------------------------------------------------- #
# joint_utils
# --------------------------------------------------------------------------------------- #
def check_joint_utils(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import chain_markup
    from mca.mya.rigging import joint_utils

    harness.new_scene()
    joints = _chain([('a', (0, 0, 0)), ('b', (0, 5, 0)), ('c', (0, 10, 0))])

    suite.check('the end of a chain is its deepest joint',
                joint_utils.get_end_joint(joints[0]) == joints[-1])
    suite.check('and anything that is not a joint has no end',
                joint_utils.get_end_joint(pm.createNode('transform')) is None)

    # -- duplicating one joint ------------------------------------------------------------- #
    copy = joint_utils.duplicate_joint(joints[1])
    suite.check('a duplicate is made', copy is not None and pm.objExists(copy))
    suite.check('named after the joint it came from', str(copy) == 'b_dup', str(copy))
    suite.check('with its channels unlocked', not copy.translateX.isLocked())
    second = joint_utils.duplicate_joint(joints[1])
    suite.check('a second duplicate does not take a name Maya has to change',
                str(second) == 'b_dup1', str(second))
    suite.check('and something that is not a joint is refused',
                joint_utils.duplicate_joint(pm.createNode('transform')) is None)

    # -- duplicating a chain ---------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain([('a', (0, 0, 0)), ('b', (0, 5, 0)), ('c', (0, 10, 0))])
    dup_chain = joint_utils.duplicate_chain(joints[0], suffix='ik')
    suite.check('a chain duplicates whole', len(dup_chain) == 3, str(dup_chain))
    suite.check('with the suffix asked for', str(dup_chain[0]) == 'a_ik', str(dup_chain[0]))
    suite.check('re-parented into a chain of its own',
                dup_chain[1].getParent() == dup_chain[0] and
                dup_chain[2].getParent() == dup_chain[1])
    suite.check('and its root at the scene root', dup_chain[0].getParent() is None)

    # The bug: '{name}_{suffix}' with suffix left at its default named every joint '..._None'.
    harness.new_scene()
    joints = _chain([('a', (0, 0, 0)), ('b', (0, 5, 0))])
    dup_chain = joint_utils.duplicate_chain(joints[0])
    suite.check('no suffix means no suffix, not the word None',
                str(dup_chain[0]) == 'a1', str(dup_chain[0]))

    # The bug: the parenting test was on the index into the source list, so skipping the first
    # joint sent the second looking for a predecessor that had never been made - IndexError.
    harness.new_scene()
    joints = _chain([('a', (0, 0, 0)), ('b', (0, 5, 0)), ('c', (0, 10, 0))])
    dup_chain = joint_utils.duplicate_chain(joints[0], skip_joints=[joints[0]], suffix='fk')
    suite.check('skipping the first joint of a chain works', len(dup_chain) == 2, str(dup_chain))
    suite.check('and the first copy made goes where the chain root would have',
                dup_chain[0].getParent() is None, str(dup_chain[0].getParent()))

    harness.new_scene()
    joints = _chain([('a', (0, 0, 0)), ('b', (0, 5, 0))])
    group = pm.group(empty=True, name='rig_grp')
    dup_chain = joint_utils.duplicate_chain(joints[0], parent=group, suffix='bind')
    suite.check('a chain can be duplicated under a parent',
                dup_chain[0].getParent() == group)
    suite.check('a parent that is not a transform is refused',
                joint_utils.duplicate_chain(joints[0], parent=pm.createNode('multMatrix')) == [])
    suite.check('and a start joint that is not there', joint_utils.duplicate_chain(None) == [])

    # -- the skeleton dictionary -------------------------------------------------------------- #
    harness.new_scene()
    lonely = pm.joint(name='lonely_root')
    # The bug: [root] + pm.listRelatives(...) is a TypeError when listRelatives answers None.
    skel_dict = joint_utils.create_skeleton_dict(lonely)
    suite.check('a skeleton of one joint is still a skeleton',
                skel_dict == {joint_utils.ROOT_KEY: lonely}, str(skel_dict))

    harness.new_scene()
    joints = _chain([('root', (0, 0, 0)), ('spine', (0, 5, 0))])
    skel_dict = joint_utils.create_skeleton_dict(joints[0])
    suite.check('the root is filed under a fixed key whatever it is called',
                skel_dict[joint_utils.ROOT_KEY] == joints[0])
    suite.check('and the rest under their own names', skel_dict['spine'] == joints[1])

    # -- finding an asset root ------------------------------------------------------------------ #
    harness.new_scene()
    joints = _chain([('root', (0, 0, 0)), ('spine', (0, 5, 0))])
    suite.check('a skeleton with no asset id is not an asset',
                joint_utils.get_root_joint_from_list([joints[1]]) is None)
    joints[0].addAttr('asset_id', dt='string')
    suite.check('one with an asset id answers its root',
                joint_utils.get_root_joint_from_list([joints[1]]) == joints[0])
    suite.check('a list with no joints in it answers nothing',
                joint_utils.get_root_joint_from_list([pm.createNode('transform')]) is None)

    # -- the hierarchy --------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _chain([('root', (0, 0, 0)), ('spine', (0, 5, 0)), ('chest', (0, 10, 0))])
    # A child that is not a joint, which the leaf test used to ask for its type() anyway.
    pm.parent(pm.group(empty=True, name='a_child_group'), joints[0])
    hierarchy = joint_utils.get_joint_hierarchy(joints[0])
    suite.check('the hierarchy leaves the leaf joint out',
                hierarchy == joints[:2], str(hierarchy))
    suite.check('and keeps it when asked',
                joint_utils.get_joint_hierarchy(joints[0], include_leaf_joints=True) == joints,
                str(joint_utils.get_joint_hierarchy(joints[0], include_leaf_joints=True)))

    harness.new_scene()
    lonely = pm.joint(name='lonely')
    suite.check('a joint with nothing under it is a hierarchy of one',
                joint_utils.get_joint_hierarchy(lonely, include_leaf_joints=True) == [lonely],
                str(joint_utils.get_joint_hierarchy(lonely, include_leaf_joints=True)))

    # -- inherited markup ------------------------------------------------------------------------ #
    harness.new_scene()
    source = pm.joint(name='source_joint')
    source_markup = chain_markup.JointMarkup(source)
    source_markup.side = 'left'
    source_markup.region = 'arm'
    target = pm.createNode('transform', name='stand_in')

    copied = joint_utils.inherit_joint_labelling(source, target)
    suite.check('the side and region follow a stand-in node',
                sorted(copied) == sorted(joint_utils.INHERITED_MARKUP_ATTRS), str(copied))
    suite.check('and read back the same',
                target.attr(chain_markup.REGION_ATTR).get() == 'arm' and
                target.attr(chain_markup.SIDE_ATTR).get() == 'left')
    suite.check('copying twice is not an error',
                joint_utils.inherit_joint_labelling(source, target) == copied)
    suite.check('a source with no markup copies nothing',
                joint_utils.inherit_joint_labelling(pm.createNode('transform'), target) == [])


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_ma_consts(suite, pm)
    check_joint_markup(suite, pm)
    check_chain_markup(suite, pm)
    check_joint_utils(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_markup', body))
