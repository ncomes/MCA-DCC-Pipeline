"""
Align groups: mca.mya.utils.groups.

    mayapy tests/test_groups.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def body(suite):
    harness.add_sibling_packages()

    import pymel.core as pm
    from mca.mya.utils import groups

    # -- create_aligned_parent_group ---------------------------------------------------- #
    harness.new_scene()
    control = pm.createNode('transform', name='hand_ctrl')
    control.t.set(3, 4, 5)
    control.r.set(0, 45, 0)

    group = groups.create_aligned_parent_group(control)
    suite.check('a group is made', group is not None)
    suite.check('the control is now under it', control.getParent() == group)
    suite.check('the control reads zero in translate',
                [round(one, 5) for one in control.t.get()] == [0.0, 0.0, 0.0],
                str(control.t.get()))
    suite.check('and zero in rotate',
                [round(one, 5) for one in control.r.get()] == [0.0, 0.0, 0.0],
                str(control.r.get()))
    suite.check('while the group holds the position',
                [round(one, 3) for one in group.getTranslation(space='world')] == [3.0, 4.0, 5.0],
                str(group.getTranslation(space='world')))
    suite.check('and the rotation',
                round(group.getRotation().y, 3) == 45.0, str(group.getRotation()))
    suite.check('the control still ends up in the same place in the world',
                [round(one, 3) for one in control.getTranslation(space='world')] ==
                [3.0, 4.0, 5.0], str(control.getTranslation(space='world')))

    suite.check('the control points at its group',
                groups.get_aligned_parent_group(control) == group)
    suite.check('through a message attribute',
                control.attr(groups.ALIGN_TRANSFORM_ATTR).type() == 'message')
    suite.check('and the group points back at the control',
                group.hasAttr(groups.ALIGN_OBJECT_ATTR))

    # The bug: the docstring said an existing group would be returned, and there was no such
    # check - so calling this twice stacked a second, empty group on top.
    again = groups.create_aligned_parent_group(control)
    suite.check('calling it again gives back the group that is already there - the whole bug',
                again == group)
    suite.check('and does not stack a second one above it',
                control.getParent() == group and group.getParent() is None)

    suite.check('a control with no group answers None',
                groups.get_aligned_parent_group(pm.createNode('transform', name='bare')) is None)

    # -- the suffix, and keeping the control's own parent -------------------------------- #
    harness.new_scene()
    rig_group = pm.createNode('transform', name='rig_grp')
    control = pm.createNode('transform', name='foot_ctrl')
    control.setParent(rig_group)
    control.t.set(0, 1, 0)

    group = groups.create_aligned_parent_group(control, suffix='align')
    suite.check('the suffix is used in the name',
                str(group).split('|')[-1] == 'foot_ctrl_align', str(group))
    suite.check("the group takes the control's place under its old parent",
                group.getParent() == rig_group)
    suite.check('and the control is under the group', control.getParent() == group)

    # -- a joint's jointOrient ---------------------------------------------------------- #
    harness.new_scene()
    joint = pm.createNode('joint', name='elbow_jnt')
    joint.t.set(2, 0, 0)
    joint.jointOrient.set([0, 30, 0])
    group = groups.create_aligned_parent_group(joint)
    suite.check('a joint is zeroed in rotate',
                [round(one, 5) for one in joint.r.get()] == [0.0, 0.0, 0.0], str(joint.r.get()))
    suite.check('and its jointOrient is zeroed too, which is the other place an offset hides',
                [round(one, 5) for one in joint.jointOrient.get()] == [0.0, 0.0, 0.0],
                str(joint.jointOrient.get()))

    # -- orienting from somewhere else --------------------------------------------------- #
    harness.new_scene()
    control = pm.createNode('transform', name='oriented_ctrl')
    control.t.set(1, 0, 0)
    control.r.set(0, 0, 0)
    guide = pm.createNode('transform', name='orient_guide')
    guide.r.set(0, 0, 90)
    group = groups.create_aligned_parent_group(control, orient_obj=guide)
    suite.check("the group's orientation comes from the node it was told to use",
                round(group.getRotation().z, 3) == 90.0, str(group.getRotation()))
    suite.check('and its position still comes from the control',
                [round(one, 3) for one in group.getTranslation(space='world')] == [1.0, 0.0, 0.0],
                str(group.getTranslation(space='world')))

    # -- transform_scale ---------------------------------------------------------------- #
    harness.new_scene()
    align_grp = pm.createNode('transform', name='face_align')
    flag = pm.createNode('transform', name='face_flag')
    flag.setParent(align_grp)

    groups.transform_scale(align_grp, flag, translate_scale=(10, 10, 10))
    suite.check('the group is scaled down',
                [round(one, 5) for one in align_grp.s.get()] == [0.1, 0.1, 0.1],
                str(align_grp.s.get()))
    suite.check('and the control up by the same amount',
                [round(one, 5) for one in flag.s.get()] == [10.0, 10.0, 10.0], str(flag.s.get()))
    suite.check("so the control's size in the world is unchanged",
                round(flag.getScale()[0] * align_grp.getScale()[0], 5) == 1.0)
    suite.check("the control's scale is locked afterwards - it holds a ratio, not a size",
                flag.sx.isLocked() and flag.sy.isLocked() and flag.sz.isLocked())
    suite.check('and is out of the channel box', not flag.sx.isKeyable())

    # Different amounts per axis.
    align_two = pm.createNode('transform', name='other_align')
    flag_two = pm.createNode('transform', name='other_flag')
    flag_two.setParent(align_two)
    groups.transform_scale(align_two, flag_two, translate_scale=(2, 4, 5))
    suite.check('each axis is scaled on its own',
                [round(one, 5) for one in align_two.s.get()] == [0.5, 0.25, 0.2],
                str(align_two.s.get()))

    # The bug: it divided by these numbers without looking at them.
    align_three = pm.createNode('transform', name='third_align')
    flag_three = pm.createNode('transform', name='third_flag')
    flag_three.setParent(align_three)
    message = suite.raises('a scale of zero is refused rather than dividing by it',
                           groups.transform_scale, align_three, flag_three, (1, 0, 1))
    suite.check('and the message says what was wrong',
                'zero' in message.lower(), message)
    suite.raises('the wrong number of axes is refused',
                 groups.transform_scale, align_three, flag_three, (1, 1))

    suite.check('create_aligned_child_group is gone - no callers, and no docstring either',
                not hasattr(groups, 'create_aligned_child_group'))
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('groups', body))
