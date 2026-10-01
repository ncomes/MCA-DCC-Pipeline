"""
The two classes every FRAG rig component is built on, in a real Maya.

    mayapy tests/test_frag_components.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _test_classes(frag_base, rig_component, keyable_component):
    """
    The component classes the checks are run against, built once and handed round.

    ``FRAGRig`` stands in for the real one until ``frag_rig`` is ported: the components look for it
    by class name, because it is built on them and cannot be imported from them. Once it exists, the
    registered one is used instead - registering a second class of that name would be refused.
    """

    rig_class = frag_base.FRAGNodeRegister.__frag_node_types__.get('FRAGRig')
    if rig_class is None:
        class FRAGRig(frag_base.FRAGNode):
            """Stands in for the node at the top of a rig."""

            VERSION = 1

        rig_class = FRAGRig

    class SupportComponent(rig_component.RigComponent):
        """A component with no controls at all, like a twist helper."""

        VERSION = 1

    class ControlComponent(keyable_component.KeyableComponent):
        """A component with controls, which is most of them."""

        VERSION = 1

        def get_flags(self):
            return self.pynode.attr('theFlags').get() if self.pynode.hasAttr('theFlags') else []

    return {'FRAGRig': rig_class, 'SupportComponent': SupportComponent,
            'ControlComponent': ControlComponent}


def _build_rig(pm, frag_base):
    """A stand-in rig with the two groups a component looks for on its parent."""

    rig = frag_base.FRAGNode.create(None, 'FRAGRig', 1)
    do_not_touch = pm.group(empty=True, n='DO_NOT_TOUCH')
    flags_all = pm.group(empty=True, n='flags_all')
    rig.connect_node(do_not_touch, 'doNotTouch')
    rig.connect_node(flags_all, 'flagsAll')
    return rig, do_not_touch, flags_all


def check_creating(suite, pm, frag_base, rig_component, keyable_component, classes):
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)
    component = classes['SupportComponent'].create(rig, 'SupportComponent', 1, 'left', 'arm')

    suite.check('a component is named for its type, its side and its region',
                str(component.pynode) == 'SupportComponent_left_arm', str(component.pynode))
    suite.check('and carries the side and region as markup',
                component.side == 'left' and component.region == 'arm')

    no_touch = component.no_touch_grp
    suite.check('it has a NO_TOUCH group, named the same way',
                str(no_touch) == 'NO_TOUCH_left_arm', str(no_touch))
    suite.check('hidden, because nothing in it is for an animator',
                no_touch.visibility.get() is False)
    suite.check('with its transform locked',
                all(no_touch.attr(name).isLocked() for name in ('tx', 'ry', 'sz')))
    suite.check('the group knows which component it belongs to',
                component.pynode in no_touch.attr(frag_base.FRAG_PARENT_ATTR).listConnections())
    suite.check('and it is parented under the rig\'s own do-not-touch group',
                no_touch.getParent() == do_not_touch, str(no_touch.getParent()))

    suite.check('the five attachment attributes are there, each holding a list',
                all(component.pynode.attr(name).isMulti() for name in
                    (rig_component.CHILD_ATTACHMENTS_ATTR,) + rig_component.ATTACHMENT_ATTRS))

    # The bug: create asks the parent what type it is, and FRAGNode.create is happy with None.
    harness.new_scene()
    loose = classes['SupportComponent'].create(None, 'SupportComponent', 1, 'center', 'tail')
    suite.check('a component with nothing above it is built rather than raising', loose is not None)
    suite.check('and its group stays at the scene root',
                loose.no_touch_grp.getParent() is None)

    # -- snapped to something ----------------------------------------------------------------- #
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)
    marker = pm.spaceLocator(name='a_marker')
    marker.translate.set(5, 10, 15)
    marker.rotate.set(0, 30, 0)
    aligned = classes['SupportComponent'].create(rig, 'SupportComponent', 1, 'left', 'leg',
                                                align_component=marker)
    # align_component has never aligned anything: the group is snapped to it and then frozen, and
    # freezing an empty transform puts its matrix back to identity. The rotation goes entirely and
    # the position survives only as the pivots. Left alone on purpose - see the module docstring.
    suite.check('a group snapped to something is frozen on the next line, so its transform is '
                'identity and the snap is gone',
                aligned.no_touch_grp.getTranslation(space='world').length() < 0.001 and
                aligned.no_touch_grp.rotate.get().length() < 0.001,
                str(aligned.no_touch_grp.getTranslation(space='world')))
    suite.check('all that is left of it is the group\'s pivots',
                (aligned.no_touch_grp.rotatePivot.get() -
                 marker.getTranslation(space='world')).length() < 0.001,
                str(aligned.no_touch_grp.rotatePivot.get()))


def check_keyable_creating(suite, pm, frag_base, rig_component, keyable_component, classes):
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)

    # The bug: the side was lower-cased on the way into RigComponent, which names the NO_TOUCH
    # group, and then used as it came in to name the control group.
    component = classes['ControlComponent'].create(rig, 'ControlComponent', 1, 'Left', 'arm')
    suite.check('both of a component\'s groups spell the side the same way, whatever case the '
                'caller used',
                str(component.no_touch_grp) == 'NO_TOUCH_left_arm' and
                str(component.flag_group) == 'flags_left_arm',
                '{0} and {1}'.format(component.no_touch_grp, component.flag_group))
    suite.check('and so does the node',
                str(component.pynode) == 'ControlComponent_left_arm', str(component.pynode))
    suite.check('the markup with them', component.side == 'left')

    suite.check('the control group is parented under the rig\'s own',
                component.flag_group.getParent() == flags_all,
                str(component.flag_group.getParent()))
    suite.check('the group knows which component it belongs to',
                component.pynode in
                component.flag_group.attr(frag_base.FRAG_PARENT_ATTR).listConnections())
    suite.check('a keyable component still has its NO_TOUCH group',
                component.no_touch_grp is not None)

    harness.new_scene()
    loose = classes['ControlComponent'].create(None, 'ControlComponent', 1, 'center', 'head')
    suite.check('and one with nothing above it is built rather than raising', loose is not None)

    # -- taking one out again ------------------------------------------------------------------ #
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)
    component = classes['ControlComponent'].create(rig, 'ControlComponent', 1, 'left', 'arm')
    # As names: reading a deleted PyNode's name is what pymel is about to start refusing.
    names = [str(component.no_touch_grp), str(component.flag_group), str(component.pynode)]
    component.remove()
    suite.check('removing a component takes both its groups and its node with it',
                not any(pm.objExists(name) for name in names), str(names))


def check_attaching(suite, pm, frag_base, rig_component, keyable_component, classes):
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)

    component = classes['ControlComponent'].create(rig, 'ControlComponent', 1, 'left', 'arm')
    parent_component = classes['ControlComponent'].create(rig, 'ControlComponent', 1, 'center',
                                                          'spine')
    first_parent = pm.spaceLocator(name='first_parent')
    first_parent.translate.set(0, 20, 0)

    component.attach_component([parent_component], [first_parent])
    for group_node in (component.flag_group, component.no_touch_grp):
        suite.check('attaching a component constrains its {0} group'.format(
            'control' if group_node == component.flag_group else 'NO_TOUCH'),
            bool(pm.listRelatives(group_node, type=pm.nt.ParentConstraint)),
            str(pm.listRelatives(group_node, type=pm.nt.Constraint)))
    # With maintainOffset, attaching a component does not move it - which is the point, since a rig
    # being put together must not move. What moves it afterwards is the thing it is attached to.
    suite.check('attaching a component does not move it',
                component.flag_group.getTranslation(space='world').length() < 0.001,
                str(component.flag_group.getTranslation(space='world')))
    first_parent.translateX.set(7)
    pm.dgdirty(allPlugs=True)
    suite.check('and moving what it is attached to moves it',
                abs(component.flag_group.getTranslation(space='world')[0] - 7.0) < 0.001,
                str(component.flag_group.getTranslation(space='world')))
    first_parent.translateX.set(0)

    suite.check('the component it now hangs off is recorded, for position',
                parent_component.pynode in
                [node.pynode for node in component.attached_frag_parents])
    suite.check('and for orientation',
                parent_component.pynode in
                [node.pynode for node in component.orient_frag_parents])
    suite.check('as are the objects it is constrained to',
                component.point_object_parents == [first_parent] and
                component.orient_object_parents == [first_parent],
                str(component.point_object_parents))
    suite.check('the NO_TOUCH group is locked again once the constraints are on it',
                all(component.no_touch_grp.attr(name).isLocked() for name in ('tx', 'ry')))

    # The bug: the two component lists were cleared before being written again and the two object
    # lists never were, so they grew. A rebuild reads the object lists.
    second_parent = pm.spaceLocator(name='second_parent')
    second_parent.translate.set(10, 20, 0)
    component.attach_component([parent_component], [second_parent])
    suite.check('attaching a component again replaces what it is attached to rather than adding to '
                'it',
                component.point_object_parents == [second_parent],
                str(component.point_object_parents))
    suite.check('and leaves one set of constraints on the group, not two',
                len(set(pm.listRelatives(component.flag_group, type=pm.nt.Constraint))) == 2,
                str(pm.listRelatives(component.flag_group, type=pm.nt.Constraint)))

    # -- one half at a time -------------------------------------------------------------------- #
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)
    component = classes['ControlComponent'].create(rig, 'ControlComponent', 1, 'left', 'arm')
    parent_component = classes['ControlComponent'].create(rig, 'ControlComponent', 1, 'center',
                                                          'spine')
    target = pm.spaceLocator(name='a_target')

    component.attach_component([parent_component], [target], point=True, orient=False)
    suite.check('a component can follow a position without following an orientation',
                component.point_object_parents == [target] and
                component.orient_object_parents == [],
                str(component.orient_object_parents))
    constraint_node = pm.listRelatives(component.flag_group, type=pm.nt.ParentConstraint)[0]
    suite.check('and the constraint it gets leaves the rotate channels alone',
                not constraint_node.attr('constraintRotate').listConnections(),
                str(constraint_node.attr('constraintRotate').listConnections()))

    component.attach_component([], [target])
    suite.check('attaching to no components at all does nothing',
                component.point_object_parents == [target])
    component.attach_component([parent_component], [target], point=False, orient=False)
    suite.check('and so does attaching neither position nor orientation',
                component.point_object_parents == [target])

    # The bug: attach_component is on RigComponent, the base for components with no controls at
    # all, and it read flagGroup whether or not the component had one.
    harness.new_scene()
    rig, do_not_touch, flags_all = _build_rig(pm, frag_base)
    support = classes['SupportComponent'].create(rig, 'SupportComponent', 1, 'left', 'arm')
    target = pm.spaceLocator(name='a_target')
    suite.check('a component with no control group has only its NO_TOUCH group to attach',
                support.get_attachment_groups() == [support.no_touch_grp],
                str(support.get_attachment_groups()))
    support.attach_component([rig], [target])
    suite.check('and attaching it works rather than raising on the group it does not have',
                bool(pm.listRelatives(support.no_touch_grp, type=pm.nt.ParentConstraint)))

    suite.check('nothing in the pipeline writes a component\'s child attachments, so it has none',
                support.attached_children == [])


def check_build_kwargs(suite, pm, frag_base, rig_component, keyable_component, classes):
    from mca.mya.utils import attr_utils

    harness.new_scene()
    component = classes['SupportComponent'].create(None, 'SupportComponent', 1, 'left', 'arm')
    suite.check('a component that did not record what it was built with answers nothing',
                component.get_build_kwargs() == {}, str(component.get_build_kwargs()))

    attr_utils.set_compound_attribute_groups(component.pynode, rig_component.BUILD_KWARGS_ATTR,
                                             {'scale': 2.5, 'create_sub_flags': True,
                                              'something_hidden': 7})
    build_kwargs = component.get_build_kwargs()
    suite.check('one that did answers the arguments it was given',
                build_kwargs.get('scale') == 2.5 and build_kwargs.get('create_sub_flags') is True,
                str(build_kwargs))
    suite.check('and leaves out the ones marked as not for a rebuild',
                'something_hidden' not in build_kwargs, str(build_kwargs))


def check_the_skeleton(suite, pm, frag_base, rig_component, keyable_component, classes):
    import maya.cmds as cmds

    harness.new_scene()
    component = classes['ControlComponent'].create(None, 'ControlComponent', 1, 'left', 'arm')
    suite.check('a component that drives no joints says so rather than raising',
                component.bind_joints == [])
    suite.check('and asking what there is to bake onto a skeleton says the same',
                component.get_bakeable_skeleton_nodes() == [])
    # The bug: these two read bindJoints without asking whether the component had it, while the
    # property beside them did ask.
    component.bake_to_skeleton()
    suite.check('baking one onto a skeleton it does not have is refused rather than raising', True)

    cmds.select(clear=True)
    joints = [pm.PyNode(cmds.joint(name='b_arm_{0:02d}'.format(index),
                                   position=(index * 10, 0, 0), absolute=True))
              for index in range(3)]
    component.connect_nodes(joints, keyable_component.BIND_JOINTS_ATTR)
    suite.check('a component that drives joints answers them',
                len(component.bind_joints) == 3, str(component.bind_joints))
    suite.check('and answers the same when asked what there is to bake',
                component.get_bakeable_skeleton_nodes() == component.bind_joints)

    pm.currentTime(1)
    pm.setKeyframe(joints[1], attribute='rotateZ', value=0, time=1)
    pm.setKeyframe(joints[1], attribute='rotateZ', value=45, time=10)
    component.bake_to_skeleton(bake_range=[1, 10])
    suite.check('baking a component onto its joints leaves them keyed',
                bool(pm.keyframe(joints[1], query=True, keyframeCount=True)))


def check_bakeable_rig_nodes(suite, pm, frag_base, rig_component, keyable_component, classes):
    harness.new_scene()
    component = classes['ControlComponent'].create(None, 'ControlComponent', 1, 'left', 'arm')

    driven_by_constraint = pm.spaceLocator(name='f_driven_by_constraint')
    driven_by_attribute = pm.spaceLocator(name='f_driven_by_attribute')
    driven_by_nothing = pm.spaceLocator(name='f_driven_by_nothing')
    component.connect_nodes([driven_by_constraint, driven_by_attribute, driven_by_nothing],
                            'theFlags')

    helper = pm.spaceLocator(name='a_bake_helper')
    helper.addAttr(keyable_component.BAKE_HELPER_ATTR, at='bool', dv=True)
    plain_target = pm.spaceLocator(name='a_plain_target')
    pm.parentConstraint([helper, plain_target], driven_by_constraint, mo=False, w=1)

    driver = pm.spaceLocator(name='a_driver')
    driven_by_attribute.addAttr('followBody', at='double', keyable=True)
    driver.translateX >> driven_by_attribute.attr('followBody')
    # Exposed on the offset control as a pass-through and unkeyable there; it breaks bakeResults.
    driven_by_attribute.addAttr('toeTap', at='double', keyable=True)
    driver.translateY >> driven_by_attribute.attr('toeTap')

    bakeable, attr_list, things_to_delete = component.get_bakeable_rig_nodes()

    suite.check('a control with a constraint on it is worth baking',
                driven_by_constraint in bakeable, str(bakeable))
    suite.check('so is one with something driving an attribute of its own',
                driven_by_attribute in bakeable, str(bakeable))
    # The bug: the test was `if constraint_list or attr_list`, and attr_list is the running list of
    # every attribute found so far - so once any control had one, every control after it went in.
    suite.check('and one with nothing driving it is not, even though the control before it was',
                driven_by_nothing not in bakeable, str(bakeable))

    suite.check('the attribute driving a control comes back to be baked',
                'followBody' in attr_list, str(attr_list))
    suite.check('and the one that cannot be baked does not', 'toeTap' not in attr_list,
                str(attr_list))

    suite.check('the constraints built for the bake come back to be cleared away',
                any(isinstance(node, pm.nt.ParentConstraint) for node in things_to_delete),
                str(things_to_delete))
    suite.check('and so does anything built only to drive the control while it is baked',
                helper in things_to_delete, str(things_to_delete))
    suite.check('but not a target that is part of the rig',
                plain_target not in things_to_delete, str(things_to_delete))

    empty = classes['ControlComponent'].create(None, 'ControlComponent', 1, 'right', 'arm')
    suite.check('a component with no controls at all has nothing to bake',
                empty.get_bakeable_rig_nodes() == ([], [], []))
    suite.check('a bare keyable component cannot be driven by a skeleton, and says so with an '
                'empty list rather than by raising',
                empty.attach_to_skeleton() == [])
    empty.set_scale()
    suite.check('and has no scale to wire', True)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import keyable_component
    from mca.mya.rigging.frag import rig_component
    classes = _test_classes(frag_base, rig_component, keyable_component)
    check_creating(suite, pm, frag_base, rig_component, keyable_component, classes)
    check_keyable_creating(suite, pm, frag_base, rig_component, keyable_component, classes)
    check_attaching(suite, pm, frag_base, rig_component, keyable_component, classes)
    check_build_kwargs(suite, pm, frag_base, rig_component, keyable_component, classes)
    check_the_skeleton(suite, pm, frag_base, rig_component, keyable_component, classes)
    check_bakeable_rig_nodes(suite, pm, frag_base, rig_component, keyable_component, classes)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_components', body))
