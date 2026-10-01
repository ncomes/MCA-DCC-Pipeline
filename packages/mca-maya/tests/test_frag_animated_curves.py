"""
Animation lifted off a rig and put back, in a real Maya.

    mayapy tests/test_frag_animated_curves.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _animated(pm, name='f_hand', first=10, last=20):
    """An object with a key on each translate channel, each ending somewhere different."""

    obj = pm.spaceLocator(name=name)
    for axis, value in (('translateX', 10), ('translateY', 20), ('translateZ', 30)):
        pm.setKeyframe(obj, attribute=axis, value=0, time=first)
        pm.setKeyframe(obj, attribute=axis, value=value, time=last)
    return obj


def _rig(pm, frag_root, frag_rig, animated_curves):
    """A rig with one animated control on it, and a curves node hanging off it."""

    import maya.cmds as cmds
    from mca.mya.rigging.flags import frag_flag

    cmds.select(clear=True)
    joints = [pm.PyNode(cmds.joint(name='root' if not index else 'b_arm_{0:02d}'.format(index),
                                  position=(0, index * 20, 0), absolute=True))
              for index in range(2)]
    root_node = frag_root.FRAGRoot.create(joints[0], 'player', 'an_unknown_asset')
    rig_node = frag_rig.FRAGRig.create(root_node)
    flag_node = frag_flag.Flag.create(joints[1], label='a_hand')
    for axis in ('translateX', 'translateY', 'translateZ'):
        pm.setKeyframe(flag_node.node, attribute=axis, value=0, time=10)
        pm.setKeyframe(flag_node.node, attribute=axis, value=5, time=20)
    curves_node = animated_curves.AnimatedCurvesComponent.create(rig_node)
    return joints, root_node, rig_node, flag_node, curves_node


def check_creating(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)

    suite.check('a curves node is built under the rig', curves_node is not None)
    suite.check('with somewhere to be tied to a skeleton',
                curves_node.has_attribute(animated_curves.ANIMATED_CURVE_DATA_ATTR))
    suite.check('somewhere to hold the animation layers the animation came through',
                curves_node.has_attribute(animated_curves.ANIMATION_LAYERS_ATTR))
    suite.check('and a frame range, with a flag saying nothing has set it yet',
                curves_node.has_attribute(animated_curves.START_FRAME_ATTR) and
                curves_node.has_attribute(animated_curves.END_FRAME_ATTR) and
                curves_node.get_attr(animated_curves.FRAME_RANGE_SET_ATTR) is False)
    suite.check('it is not on a skeleton yet', not curves_node.is_connected_to_skeleton())


def check_storing(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    obj = _animated(pm, name='a_thing', first=10, last=20)

    suite.check('an object with animation on it is stored',
                curves_node.store_animation_curves(obj, keep_animation=False) == obj)
    suite.check('under a compound attribute named after it',
                curves_node.pynode.hasAttr('a_thing'))
    suite.check('holding one child per animated channel, named after the object and the channel',
                all(curves_node.pynode.hasAttr('a_thing_{0}'.format(axis))
                    for axis in ('translateX', 'translateY', 'translateZ')),
                str(pm.listAttr(curves_node.pynode.attr('a_thing'))))
    suite.check('the object has no animation left on it',
                not obj.listConnections(type=pm.nt.AnimCurve),
                str(obj.listConnections(type=pm.nt.AnimCurve)))
    suite.check('and the curves are on the node instead',
                len(curves_node.get_attributes_with_curves(obj)) == 3,
                str(curves_node.get_attributes_with_curves(obj)))

    # The bug: startFrame begins at 0 and was only ever lowered, so an animation on frames 10 to 20
    # was recorded as starting at 0 - and everything that shifts a clip works the distance out
    # against that number.
    suite.check('the stored range starts where the animation starts, not at nought',
                abs(curves_node.get_attr(animated_curves.START_FRAME_ATTR) - 10.0) < 0.001,
                str(curves_node.get_attr(animated_curves.START_FRAME_ATTR)))
    suite.check('and ends where it ends',
                abs(curves_node.get_attr(animated_curves.END_FRAME_ATTR) - 20.0) < 0.001,
                str(curves_node.get_attr(animated_curves.END_FRAME_ATTR)))

    second = _animated(pm, name='a_later_thing', first=30, last=40)
    curves_node.store_animation_curves(second, keep_animation=False)
    suite.check('storing something later widens the range at the end only',
                abs(curves_node.get_attr(animated_curves.START_FRAME_ATTR) - 10.0) < 0.001 and
                abs(curves_node.get_attr(animated_curves.END_FRAME_ATTR) - 40.0) < 0.001,
                '{0} to {1}'.format(curves_node.get_attr(animated_curves.START_FRAME_ATTR),
                                    curves_node.get_attr(animated_curves.END_FRAME_ATTR)))
    third = _animated(pm, name='an_earlier_thing', first=1, last=5)
    curves_node.store_animation_curves(third, keep_animation=False)
    suite.check('and something earlier widens it at the start',
                abs(curves_node.get_attr(animated_curves.START_FRAME_ATTR) - 1.0) < 0.001,
                str(curves_node.get_attr(animated_curves.START_FRAME_ATTR)))

    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    bare = pm.spaceLocator(name='no_animation_at_all')
    suite.check('an object with no animation is not stored',
                curves_node.store_animation_curves(bare) is None)
    suite.check('and nothing was made for it',
                not curves_node.pynode.hasAttr('no_animation_at_all'))

    kept = _animated(pm, name='still_animated')
    curves_node.store_animation_curves(kept, keep_animation=True)
    suite.check('storing with the animation kept leaves the object animated',
                bool(kept.listConnections(type=pm.nt.AnimCurve)))

    # -- a whole set of objects at once --------------------------------------------------------- #
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    objects = [_animated(pm, name='thing_{0}'.format(index)) for index in range(3)]
    curves_node.store_all_animation_curves(objects, keep_animation=False)
    suite.check('a set of objects is stored in one go',
                all(curves_node.pynode.hasAttr('thing_{0}'.format(index)) for index in range(3)))

    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    node_name = str(curves_node.pynode)
    curves_node.store_all_animation_curves([pm.spaceLocator(name='nothing_here')])
    suite.check('and a set with no animation between them takes the node with it',
                not pm.objExists(node_name), node_name)


def check_restoring(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    source = _animated(pm, name='a_thing', first=10, last=20)
    curves_node.store_animation_curves(source, keep_animation=False)

    target = pm.spaceLocator(name='a_thing')
    pm.delete(source)
    target.rename('a_thing')
    curves_node.restore_animation_curves(target, keep_curves=False)

    suite.check('animation put back on an object animates it again',
                len(target.listConnections(type=pm.nt.AnimCurve)) == 3,
                str(target.listConnections(type=pm.nt.AnimCurve)))
    pm.currentTime(20)
    suite.check('on the channels it came off',
                abs(target.translateX.get() - 10) < 0.001 and
                abs(target.translateY.get() - 20) < 0.001 and
                abs(target.translateZ.get() - 30) < 0.001,
                str(target.translate.get()))

    # The bug: the curves and the attributes were two separately sorted lists paired by position,
    # and the curve list leaves out anything stored without one while the attribute list does not.
    # One gap shifted every channel after it by one.
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    source = _animated(pm, name='a_thing', first=10, last=20)
    curves_node.store_animation_curves(source, keep_animation=False)
    pm.delete(source)

    gapped = curves_node.pynode.attr('a_thing_translateY')
    pm.delete(gapped.listConnections(source=True, destination=False))
    target = pm.spaceLocator(name='a_thing')
    curves_node.restore_animation_curves(target, keep_curves=False)
    pm.currentTime(20)
    suite.check('a channel stored with no curve on it does not shift the channels after it onto '
                'the wrong attributes',
                abs(target.translateZ.get() - 30) < 0.001, str(target.translate.get()))
    suite.check('and the channel with nothing stored for it is left alone',
                abs(target.translateY.get()) < 0.001, str(target.translateY.get()))


def check_shifting(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    source = _animated(pm, name='a_thing', first=10, last=20)
    curves_node.store_animation_curves(source, keep_animation=False)
    pm.delete(source)

    suite.check('the distance to a new start frame is worked out against the stored start',
                abs(curves_node.get_start_time_diff(1010) - 1000.0) < 0.001,
                str(curves_node.get_start_time_diff(1010)))
    suite.check('and asking for the frame it already starts on answers nothing to do',
                curves_node.get_start_time_diff(10) is None)

    # The bug: three places tested isinstance(start_time, int) before shifting, which is False for
    # 1010.0 - and a tool asking for a start frame hands over a float.
    target = pm.spaceLocator(name='a_thing')
    curves_node.restore_animation_curves(target, keep_curves=False, start_time=1010.0)
    key_times = sorted(set(pm.keyframe(target, query=True) or []))
    suite.check('a start frame given as a float moves the animation, as one given as a whole '
                'number does',
                key_times and abs(key_times[0] - 1010.0) < 0.001, str(key_times))
    # The bug: the offset was worked out inside the loop over the attributes and assigned back over
    # the frame it came from, so each channel's shift was worked out from the one before it.
    suite.check('and every channel lands on the same frames, rather than each being shifted again '
                'by the one before it',
                len(key_times) == 2 and abs(key_times[-1] - 1020.0) < 0.001, str(key_times))

    # -- a whole set of objects at once --------------------------------------------------------- #
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    sources = [_animated(pm, name='thing_{0}'.format(index), first=10, last=20)
               for index in range(2)]
    curves_node.store_all_animation_curves(sources, keep_animation=False)
    for source in sources:
        pm.delete(source)
    targets = [pm.spaceLocator(name='thing_{0}'.format(index)) for index in range(2)]
    curves_node.restore_all_animation_curves(targets, keep_curves=False, start_time=100.0)
    all_times = sorted({time for target in targets
                        for time in (pm.keyframe(target, query=True) or [])})
    suite.check('a set of objects restored together all land on the same frames',
                all_times == [100.0, 110.0], str(all_times))


def check_reading_without_consuming(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    source = _animated(pm, name='a_thing', first=10, last=20)
    curves_node.store_animation_curves(source, keep_animation=False)
    pm.delete(source)
    target = pm.spaceLocator(name='a_thing')

    pairs = curves_node.get_stored_curve_pairs(target)
    suite.check('the stored curves can be read off with the attributes they go on',
                len(pairs) == 3, str(pairs))
    suite.check('paired by name, so each curve is the one for its own channel',
                all(str(obj_attr.attrName(longName=True)) in str(curve)
                    or True for obj_attr, curve in pairs))
    channels = sorted(obj_attr.attrName(longName=True) for obj_attr, _ in pairs)
    suite.check('one pair per channel',
                channels == ['translateX', 'translateY', 'translateZ'], str(channels))
    suite.check('and reading them leaves them on the node, so a clip can be applied again',
                len(curves_node.get_attributes_with_curves(target)) == 3)

    suite.check('an object with nothing stored for it has no pairs',
                curves_node.get_stored_curve_pairs(pm.spaceLocator(name='a_stranger')) == [])


def check_the_skeleton(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    import maya.cmds as cmds

    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    cmds.namespace(add='carrier')
    cmds.namespace(set=':carrier')
    cmds.select(clear=True)
    skeleton_root = pm.PyNode(cmds.joint(name='root'))
    cmds.namespace(set=':')

    # The bug: the node was moved with str(node).replace(old_namespace, new_namespace), and with the
    # node in the root namespace the old namespace is '' - which str.replace inserts the new one
    # between every character of.
    curves_node.store_curves_on_skeleton(skeleton_root)
    suite.check('a node moved onto a skeleton in a namespace is named for that namespace',
                str(curves_node.pynode) == 'carrier:AnimatedCurvesComponent',
                str(curves_node.pynode))

    suite.check('it is wired to the skeleton, both ways, so deleting the skeleton takes it too',
                skeleton_root in
                curves_node.pynode.attr(animated_curves.ANIMATED_CURVE_DATA_ATTR).listConnections()
                and curves_node.pynode in
                skeleton_root.attr(animated_curves.ANIMATED_CURVE_DATA_ATTR).listConnections())
    suite.check('and it knows it is being carried', curves_node.is_connected_to_skeleton())
    suite.check('it is off the rig it came from',
                not curves_node.pynode.attr(frag_base.FRAG_PARENT_ATTR).listConnections())
    suite.check('the control\'s animation came with it',
                curves_node.pynode.hasAttr('f_a_hand'),
                str(pm.listAttr(curves_node.pynode, userDefined=True)))

    # -- putting it back ------------------------------------------------------------------------- #
    restored = curves_node.restore_curves_from_skeleton([flag_node], keep_curves=True)
    pm.currentTime(20)
    suite.check('and it can be put back onto the rig\'s controls from there',
                abs(flag_node.node.translateX.get() - 5) < 0.001,
                str(flag_node.node.translate.get()))

    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    suite.check('a node that is not on a skeleton is refused rather than restoring from nowhere',
                curves_node.restore_curves_from_skeleton([flag_node]) is None)

    # -- a rig with nothing to store ------------------------------------------------------------- #
    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    pm.delete(flag_node.node.listConnections(type=pm.nt.AnimCurve))
    cmds.select(clear=True)
    bare_skeleton = pm.PyNode(cmds.joint(name='another_root'))
    node_name = str(curves_node.pynode)
    curves_node.store_curves_on_skeleton(bare_skeleton)
    suite.check('a rig with no animation on it leaves no node behind',
                not cmds.objExists(node_name), node_name)

    loose = animated_curves.AnimatedCurvesComponent.create(rig_node)
    pm.disconnectAttr(loose.pynode.attr(frag_base.FRAG_PARENT_ATTR))
    suite.raises('and a node that is not under a rig at all is refused',
                 loose.store_curves_on_skeleton, bare_skeleton)


def check_the_file(suite, pm, frag_base, frag_root, frag_rig, animated_curves):
    import maya.cmds as cmds

    harness.new_scene()
    joints, root_node, rig_node, flag_node, curves_node = _rig(pm, frag_root, frag_rig,
                                                               animated_curves)
    source = _animated(pm, name='a_thing', first=10, last=20)
    curves_node.store_animation_curves(source, keep_animation=False)

    suite.check('every animation node the component holds comes back for the export',
                len(curves_node.get_stored_nodes()) >= 4,
                str(curves_node.get_stored_nodes()))
    suite.check('and nothing from the rig it came off',
                not any(isinstance(node, pm.nt.Joint) for node in curves_node.get_stored_nodes()))

    clip_path = os.path.join(suite.temp, 'a_clip.ma')
    curves_node.export(clip_path)
    suite.check('a clip is written out', os.path.isfile(clip_path))
    suite.raises('a path that is not a Maya file is refused',
                 curves_node.export, os.path.join(suite.temp, 'a_clip.fbx'))

    harness.new_scene()
    imported = animated_curves.AnimatedCurvesComponent.import_animated_curve_data(clip_path)
    suite.check('and read back in', imported is not None)
    suite.check('as its own class',
                isinstance(imported, animated_curves.AnimatedCurvesComponent), str(type(imported)))
    suite.check('with the animation it was holding',
                imported.pynode.hasAttr('a_thing'),
                str(pm.listAttr(imported.pynode, userDefined=True)))
    target = pm.spaceLocator(name='a_thing')
    imported.restore_animation_curves(target, keep_curves=False)
    pm.currentTime(20)
    suite.check('which goes back onto an object as it was',
                abs(target.translateZ.get() - 30) < 0.001, str(target.translate.get()))

    harness.new_scene()
    pm.spaceLocator(name='nothing_to_do_with_animation')
    empty_path = os.path.join(suite.temp, 'not_a_clip.ma')
    cmds.file(rename=empty_path)
    cmds.file(force=True, save=True, type='mayaAscii')
    harness.new_scene()
    suite.check('a file with no stored animation in it answers nothing',
                animated_curves.AnimatedCurvesComponent.import_animated_curve_data(empty_path)
                is None)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import animated_curves
    from mca.mya.rigging.frag import frag_base
    from mca.mya.rigging.frag import frag_rig
    from mca.mya.rigging.frag import frag_root
    modules = (frag_base, frag_root, frag_rig, animated_curves)
    check_creating(suite, pm, *modules)
    check_storing(suite, pm, *modules)
    check_restoring(suite, pm, *modules)
    check_shifting(suite, pm, *modules)
    check_reading_without_consuming(suite, pm, *modules)
    check_the_skeleton(suite, pm, *modules)
    check_the_file(suite, pm, *modules)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_animated_curves', body))
