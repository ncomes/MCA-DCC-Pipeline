"""
Animation: keyframes, baking, anim_curves and anim_layers, in a real Maya.

Animation layers cannot be faked. The whole module is about a chain of blend nodes Maya builds
for itself, so every layer check here builds a real one and reads the result back off the
attribute.

    mayapy tests/test_animation.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _keyed(name, attribute='translateX', pairs=((0, 0), (10, 10))):
    """A transform with keys on one attribute."""

    import maya.cmds as cmds
    import pymel.core as pm

    node = pm.createNode('transform', name=name)
    for time, value in pairs:
        cmds.setKeyframe('{0}.{1}'.format(name, attribute), time=time, value=value)
    return node


def _layered(name, attribute='translateX'):
    """A transform with base animation and one animation layer on top of it."""

    import maya.cmds as cmds

    node = _keyed(name, attribute, ((0, 0), (10, 10)))
    plug = '{0}.{1}'.format(name, attribute)
    layer = cmds.animLayer('{0}_layer'.format(name))
    cmds.animLayer(layer, edit=True, attribute=plug)
    cmds.setKeyframe(plug, time=0, value=0, animLayer=layer)
    cmds.setKeyframe(plug, time=10, value=5, animLayer=layer)
    return node, layer


# --------------------------------------------------------------------------------------- #
# keyframes
# --------------------------------------------------------------------------------------- #
def check_keyframes(suite, pm):
    import maya.cmds as cmds
    from mca.mya.animation import keyframes

    harness.new_scene()
    suite.check('a scene with no layers has nothing to fix',
                keyframes.fix_single_keyframe_layers() == [])

    _keyed('unlayered')
    suite.check('nor has one with keys but no layers',
                keyframes.fix_single_keyframe_layers() == [])

    # A layer with one key on it: the case the function exists for.
    harness.new_scene()
    node = _keyed('single_key')
    layer = cmds.animLayer('one_key_layer')
    cmds.animLayer(layer, edit=True, attribute='single_key.translateX')
    cmds.setKeyframe('single_key.translateX', time=4, value=3, animLayer=layer)

    fixed = keyframes.fix_single_keyframe_layers()
    suite.check('a layer holding one key is fixed', fixed == [layer], str(fixed))
    layer_curves = cmds.animLayer(layer, query=True, animCurves=True) or []
    times = sorted(cmds.keyframe(layer_curves[0], query=True) or []) if layer_curves else []
    suite.check('by giving it a second key one frame later', times == [4.0, 5.0], str(times))

    suite.check('running it again leaves the now two-key layer alone',
                keyframes.fix_single_keyframe_layers() == [])

    # A layer with real animation on it is not touched.
    harness.new_scene()
    node, layer = _layered('already_fine')
    suite.check('a layer with a real curve on it is left alone',
                keyframes.fix_single_keyframe_layers() == [])

    suite.check('the base layer name is named, not spelled out at each use',
                keyframes.BASE_ANIMATION_LAYER == 'BaseAnimation')


# --------------------------------------------------------------------------------------- #
# baking
# --------------------------------------------------------------------------------------- #
def check_baking(suite, pm):
    import maya.cmds as cmds
    from mca.mya.animation import baking

    harness.new_scene()
    suite.check('nothing to bake is not an error', baking.bake_objects(None) == [])
    suite.check('and says so', baking.bake_objects([]) == [])

    node = _keyed('nothing_asked_for')
    suite.check('no attributes asked for is not an error either',
                baking.bake_objects([node], translate=False, rotate=False, scale=False) == [])

    # -- a real bake --------------------------------------------------------------------- #
    harness.new_scene()
    driver = _keyed('driver')
    follower = pm.createNode('transform', name='follower')
    pm.parentConstraint(driver, follower, maintainOffset=False)

    baked = baking.bake_objects([follower], bake_range=[0, 10])
    suite.check('a constrained node bakes', list(baked) == [follower], str(baked))
    times = sorted(cmds.keyframe('follower.translateX', query=True) or [])
    suite.check('with a key on every frame of the range', times == [float(x) for x in range(11)],
                str(times))
    cmds.currentTime(5)
    suite.check('and the motion it was following',
                abs(pm.PyNode('follower').translateX.get() - 5.0) < 0.001,
                str(pm.PyNode('follower').translateX.get()))

    # -- the bug: baking without rotation zeroed every static rotation ------------------- #
    # The Euler filter step used to run whatever was asked for. On a node with no rotation keys
    # it made a one-key rotation curve worth zero, then cut that key, and the attribute came
    # back reading the only value it had ever evaluated to.
    harness.new_scene()
    driver = _keyed('rot_driver')
    static = pm.createNode('transform', name='static_rotation')
    static.rotateY.set(45)
    pm.parentConstraint(driver, static, maintainOffset=True, skipRotate=('x', 'y', 'z'))

    baking.bake_objects([static], translate=True, rotate=False, scale=False, bake_range=[0, 10])
    suite.check('baking translation alone leaves a static rotation where it was',
                abs(static.rotateY.get() - 45.0) < 0.001, str(static.rotateY.get()))
    suite.check('and does not invent rotation curves',
                not (cmds.keyframe('static_rotation.rotateY', query=True) or []))

    # -- the bug: the filter's anchor frame cut keys on other channels ------------------- #
    # The anchor used to be a hard-coded -1337 cut with a bare cutKey, so any real key at that
    # frame on any channel went with it. The anchor is now a frame before the earliest rotation
    # key, and only the rotation channels are cut.
    harness.new_scene()
    anchored = pm.createNode('transform', name='anchored')
    cmds.setKeyframe('anchored.rotateY', time=10, value=0)
    cmds.setKeyframe('anchored.rotateY', time=20, value=90)
    cmds.setKeyframe('anchored.translateX', time=9, value=7)

    filtered = baking.euler_filter([anchored])
    suite.check('the filter runs on a node with rotation curves', list(filtered) == [anchored])
    rot_times = sorted(cmds.keyframe('anchored.rotateY', query=True) or [])
    suite.check('and leaves the rotation keys it found', rot_times == [10.0, 20.0], str(rot_times))
    trans_times = sorted(cmds.keyframe('anchored.translateX', query=True) or [])
    suite.check('a key on another channel at the anchor frame survives',
                trans_times == [9.0], str(trans_times))

    unrotatable = pm.createNode('animCurveTL', name='not_a_transform')
    suite.check('the filter skips anything with no rotation', baking.euler_filter([]) == [])
    suite.check('and a node with no rotation keys', baking.euler_filter([_keyed('no_rot')]) == [])

    # -- merging animation layers -------------------------------------------------------- #
    harness.new_scene()
    suite.check('a scene with no layers has nothing to merge',
                baking.merge_all_animation_layers() == [])

    harness.new_scene()
    node, layer = _layered('merge_me')
    cmds.playbackOptions(edit=True, animationStartTime=0, animationEndTime=10)
    cmds.currentTime(10)
    before = node.translateX.get()
    # setKeyframe with -animLayer takes the value the object should read, and works out the
    # offset to put on the layer curve itself - so the layer was asked for 5 at frame 10.
    suite.check('the layer is driving the attribute before merging',
                abs(before - 5.0) < 0.001, str(before))

    merged = baking.merge_all_animation_layers()
    suite.check('merging reports the layers it took away',
                sorted(merged) == sorted([layer, 'BaseAnimation']), str(merged))
    suite.check('and leaves no layers in the scene', not (cmds.ls(type='animLayer') or []))
    cmds.currentTime(10)
    suite.check('with the same value on the attribute',
                abs(node.translateX.get() - before) < 0.001, str(node.translateX.get()))

    # -- the bug: a nested layer's own attributes were dropped --------------------------- #
    # The list of attributes to bake was gathered from the base layer's direct children only.
    # A layer nested under one of those, holding an attribute its parent does not hold, was
    # never baked - and was then deleted along with its parent, animation and all. Verified
    # against the old function: translateY read 9.0 before the merge and 1.0 after it.
    harness.new_scene()
    node = _keyed('nested_base')
    cmds.setKeyframe('nested_base.translateY', time=0, value=0)
    cmds.setKeyframe('nested_base.translateY', time=10, value=1)
    cmds.playbackOptions(edit=True, animationStartTime=0, animationEndTime=10)
    outer = cmds.animLayer('outer_layer')
    cmds.animLayer(outer, edit=True, attribute='nested_base.translateX')
    inner = cmds.animLayer('inner_layer', parent=outer)
    cmds.animLayer(inner, edit=True, attribute='nested_base.translateY')
    cmds.setKeyframe('nested_base.translateX', time=10, value=4, animLayer=outer)
    cmds.setKeyframe('nested_base.translateY', time=10, value=9, animLayer=inner)

    cmds.currentTime(10)
    before = (node.translateX.get(), node.translateY.get())
    merged = baking.merge_all_animation_layers()
    suite.check('a nested layer is merged away too', inner in merged, str(merged))
    suite.check('and no layers are left', not (cmds.ls(type='animLayer') or []))
    cmds.currentTime(10)
    after = (node.translateX.get(), node.translateY.get())
    suite.check("the parent layer's channel is kept", abs(after[0] - before[0]) < 0.001,
                '{0} became {1}'.format(before[0], after[0]))
    suite.check("and so is the nested layer's own channel",
                abs(after[1] - before[1]) < 0.001, '{0} became {1}'.format(before[1], after[1]))

    options = baking.MCABakeOptionVars()
    was = options.MCAEndFrame
    try:
        options.MCAEndFrame = 77
        suite.check('the bake option variables read and write',
                    options.MCAEndFrame == 77, str(options.MCAEndFrame))
    finally:
        options.MCAEndFrame = was
    suite.check('and all three are declared',
                all(hasattr(baking.MCABakeOptionVars, name) for name in
                    ('MCAFrameOverride', 'MCAStartFrame', 'MCAEndFrame')))
    source = open(baking.__file__.replace('.pyc', '.py')).read()
    suite.check("and no longer carry another project's name in a comment",
                'Helios' not in source)


# --------------------------------------------------------------------------------------- #
# anim_curves
# --------------------------------------------------------------------------------------- #
def check_anim_curves(suite, pm):
    import maya.cmds as cmds
    from mca.mya.animation import anim_curves

    harness.new_scene()
    node = _keyed('curvy', 'translateX', ((0, 0), (10, 10)))

    suite.check('nothing has no curves', anim_curves.get_anim_curves(None) == [])
    found = anim_curves.get_anim_curves(node)
    suite.check("a node gives up its curves", len(found) == 1, str(found))
    suite.check('a list of one does the same', anim_curves.get_anim_curves([node]) == found)
    suite.check('and a curve passes straight through',
                anim_curves.get_anim_curves(found[0]) == found)
    suite.check('the same curve is not listed twice',
                len(anim_curves.get_anim_curves([node, found[0]])) == 1)

    # -- cropping ------------------------------------------------------------------------ #
    harness.new_scene()
    node = _keyed('croppable', 'translateX', ((0, 0), (5, 5), (10, 10), (20, 20)))
    anim_curves.crop_time_range(5, 10, node_list=node)
    times = sorted(cmds.keyframe('croppable.translateX', query=True) or [])
    suite.check('cropping keeps the keys inside the range', times == [5.0, 10.0], str(times))

    harness.new_scene()
    node = _keyed('head_only', 'translateX', ((0, 0), (5, 5), (10, 10)))
    anim_curves.crop_time_range(None, 5, node_list=node)
    times = sorted(cmds.keyframe('head_only.translateX', query=True) or [])
    suite.check('a crop with no lower bound leaves the head alone', times == [0.0, 5.0], str(times))

    harness.new_scene()
    node = _keyed('survivor', 'translateX', ((0, 0), (10, 10)))
    anim_curves.crop_time_range(100, 200, node_list=node)
    suite.check('a crop that would take every key is refused rather than losing the curve',
                bool(cmds.keyframe('survivor.translateX', query=True)))

    # -- shifting: the bug where a shift of zero meant "work it out for me" -------------- #
    harness.new_scene()
    node = _keyed('late_start', 'translateX', ((20, 0), (30, 10)))
    moved = anim_curves.change_curve_start_time(node, shift_length=0)
    times = sorted(cmds.keyframe('late_start.translateX', query=True) or [])
    suite.check('a shift of zero shifts nothing', times == [20.0, 30.0], str(times))
    suite.check('and reports that it shifted nothing', moved == 0, str(moved))

    moved = anim_curves.change_curve_start_time(node)
    times = sorted(cmds.keyframe('late_start.translateX', query=True) or [])
    suite.check('no shift given means "put it at frame zero"', times == [0.0, 10.0], str(times))
    suite.check('and the distance is reported', moved == -20, str(moved))

    suite.check('animation already at zero is left alone',
                anim_curves.change_curve_start_time(node) == 0)
    suite.check('nothing to shift is not an error',
                anim_curves.change_curve_start_time(None) == 0)

    # -- replacing: the bug where an empty source was indexed ---------------------------- #
    harness.new_scene()
    source = _keyed('replace_src', 'translateX', ((0, 0), (10, 10)))
    target = _keyed('replace_dst', 'translateX', ((0, 100), (10, 100)))
    source_curve = anim_curves.get_anim_curves(source)[0]
    target_curve = anim_curves.get_anim_curves(target)[0]
    suite.check('a curve replaces into another',
                anim_curves.replace_into_curve(source_curve, target_curve) is True)
    cmds.currentTime(10)
    suite.check('and the destination takes its values',
                abs(target.translateX.get() - 10.0) < 0.001, str(target.translateX.get()))

    empty = pm.createNode('animCurveTL', name='no_keys_at_all')
    suite.check('an empty source is refused rather than indexed',
                anim_curves.replace_into_curve(empty, target_curve) is False)

    # -- multiplying: the bug where an unkeyed curve was iterated as None ---------------- #
    harness.new_scene()
    node = _keyed('multiply_me', 'translateX', ((0, 1), (10, 2)))
    curve = anim_curves.get_anim_curves(node)[0]
    suite.check('every key is scaled', anim_curves.multiply_curve_values(curve, 3) == 2)
    values = cmds.keyframe(str(curve), query=True, valueChange=True) or []
    suite.check('by the amount given', values == [3.0, 6.0], str(values))
    suite.check('a curve with no keys is not an error',
                anim_curves.multiply_curve_values(pm.createNode('animCurveTL')) == 0)

    # -- merging ------------------------------------------------------------------------- #
    harness.new_scene()
    a = anim_curves.get_anim_curves(_keyed('merge_a', 'translateX', ((0, 1), (5, 0))))[0]
    b = anim_curves.get_anim_curves(_keyed('merge_b', 'translateX', ((10, 9),)))[0]
    merged = anim_curves.merge_curves(a, b)
    times = sorted(cmds.keyframe(str(merged), query=True) or [])
    suite.check('a merge holds both curves keys', times == [0.0, 5.0, 10.0], str(times))
    values = cmds.keyframe(str(merged), query=True, time=(5, 5), valueChange=True) or []
    suite.check('including one worth zero', values == [0.0], str(values))

    # -- restoring ----------------------------------------------------------------------- #
    harness.new_scene()
    stored = anim_curves.get_anim_curves(_keyed('stored', 'translateX', ((0, 0), (10, 10))))[0]
    target = pm.createNode('transform', name='restore_target')
    end_frame = anim_curves.restore_from_anim_curves(stored, target.translateX)
    suite.check('a stored curve connects to a bare attribute',
                target.translateX.listConnections() == [stored])
    suite.check('and the end frame is reported even with no offset given',
                end_frame == 10.0, str(end_frame))

    harness.new_scene()
    stored = anim_curves.get_anim_curves(_keyed('stored2', 'translateX', ((20, 0), (30, 10))))[0]
    target = pm.createNode('transform', name='restore_target2')
    anim_curves.restore_from_anim_curves(stored, target.translateX, time_offset=-20)
    times = sorted(cmds.keyframe(str(stored), query=True) or [])
    suite.check('an offset moves the curve before connecting it', times == [0.0, 10.0], str(times))

    harness.new_scene()
    stored = anim_curves.get_anim_curves(_keyed('stored3', 'translateX', ((0, 5), (10, 5))))[0]
    target = _keyed('restore_target3', 'translateX', ((0, 0), (10, 0)))
    old_curve = anim_curves.get_anim_curves(target)[0]
    anim_curves.restore_from_anim_curves(stored, target.translateX, delete_old_curves=True)
    suite.check('the old curve goes when it is asked to', not pm.objExists(old_curve))
    suite.check('and the stored one is connected in its place',
                target.translateX.listConnections() == [stored])

    # -- reanimating: the bug where an end time without a start time raised -------------- #
    harness.new_scene()
    stored = anim_curves.get_anim_curves(_keyed('rea', 'translateX', ((0, 0), (5, 5), (10, 10))))[0]
    target = pm.createNode('transform', name='rea_target')
    connected = anim_curves.reanimate_from_anim_curves(stored, target.translateX, end_time=5)
    suite.check('an end time on its own trims the tail rather than raising',
                connected is not None)
    times = sorted(cmds.keyframe(str(stored), query=True) or [])
    suite.check('and the keys after it are gone', times == [0.0, 5.0], str(times))
    suite.check('with the curve connected', target.translateX.listConnections() == [stored])

    harness.new_scene()
    stored = anim_curves.get_anim_curves(_keyed('rea2', 'translateX', ((0, 0), (10, 10))))[0]
    target = _keyed('rea2_target', 'translateX', ((20, 3),))
    anim_curves.reanimate_from_anim_curves(stored, target.translateX)
    connections = target.translateX.listConnections()
    suite.check('reanimating over existing animation merges the two',
                len(connections) == 1, str(connections))
    times = sorted(cmds.keyframe(str(connections[0]), query=True) or [])
    suite.check('keeping both sets of keys', times == [0.0, 10.0, 20.0], str(times))

    suite.check('nothing to reanimate is not an error',
                anim_curves.reanimate_from_anim_curves(None, target.translateX) is None)


# --------------------------------------------------------------------------------------- #
# anim_layers
# --------------------------------------------------------------------------------------- #
def check_anim_layers(suite, pm):
    import maya.cmds as cmds
    from mca.mya.animation import anim_layers

    harness.new_scene()

    # -- the bug: these answered None, and their answers are iterated -------------------- #
    suite.check('mapping something that is not a blend node answers an empty list',
                anim_layers.map_anim_layers(None) == [])
    suite.check('and a network with no blend node stores an empty mapping',
                anim_layers.create_anim_layer_network(None) == {})
    suite.check('the layers of nothing is an empty list',
                anim_layers.get_all_anim_layers_in_network(None) == [])
    suite.check('the curves of nothing too',
                anim_layers.get_all_curves_in_layer_network(None) == [])
    suite.check('and the base curves of nothing', anim_layers.get_base_anim_curves(None) == [])

    plain = _keyed('plain')
    suite.check('a node with plain animation is not on a layer',
                anim_layers.check_obj_for_anim_layer(plain) is False)

    # -- reading a real network ---------------------------------------------------------- #
    harness.new_scene()
    node, layer = _layered('layered')
    suite.check('a node driven through a layer says so',
                anim_layers.check_obj_for_anim_layer(node) is True)

    blend = node.translateX.listConnections(type=pm.nt.AnimBlendNodeBase)[0]
    mapping = anim_layers.map_anim_layers(blend)
    suite.check('the chain maps to one blend node and one layer', len(mapping) == 1, str(mapping))
    suite.check('with the layer paired to it',
                str(mapping[0][1]) == layer, str(mapping[0][1]))
    suite.check('the blends come back on their own',
                anim_layers.get_all_anim_blends_in_network(blend) == [blend])
    curves = anim_layers.get_all_curves_in_layer_network(blend)
    suite.check('both curves are found - the base one and the layer one',
                len(curves) == 2, str(curves))
    base_curves = anim_layers.get_base_anim_curves(blend)
    suite.check('and the base one is picked out', len(base_curves) == 1, str(base_curves))

    # -- layer membership: the bug where the same attribute was added twice -------------- #
    harness.new_scene()
    node, layer = _layered('members')
    layer_node = pm.PyNode(layer)
    suite.check('an attribute already in a layer is not added again',
                anim_layers.connect_layer_dagSetMembers(node.translateX, layer_node) is False)
    other = pm.createNode('transform', name='other_member')
    suite.check('one that is not is added',
                anim_layers.connect_layer_dagSetMembers(other.translateY, layer_node) is True)
    suite.check('and then it is a member too',
                anim_layers.connect_layer_dagSetMembers(other.translateY, layer_node) is False)

    # -- duplicating --------------------------------------------------------------------- #
    harness.new_scene()
    node, layer = _layered('dupe')
    layer_node = pm.PyNode(layer)
    copy = anim_layers.duplicate_anim_layer(layer_node)
    suite.check('a duplicated layer remembers where it came from',
                copy.original_anim_layer.get() == layer, str(copy.original_anim_layer.get()))
    suite.check('and is found again by that',
                anim_layers.check_layer_original(layer_node, [copy]) == copy)
    suite.check('a layer with no copy answers None',
                anim_layers.check_layer_original(pm.PyNode('BaseAnimation'), [copy]) is None)
    suite.raises('duplicating something that is not a layer is refused',
                 anim_layers.duplicate_anim_layer, node)

    # -- store and restore, the two entry points ----------------------------------------- #
    harness.new_scene()
    node, layer = _layered('round_trip')
    cmds.playbackOptions(edit=True, animationStartTime=0, animationEndTime=10)
    cmds.currentTime(10)
    expected = node.translateX.get()

    stored = anim_layers.store_object_animation(node)
    suite.check('storing a layered object gives back one plug', len(stored) == 1, str(stored))
    plug_name = list(stored.keys())[0]
    suite.check('named after the attribute it came off',
                plug_name.endswith('translateX'), plug_name)

    target = pm.createNode('transform', name='round_trip_target')
    stored_blend = stored[plug_name].node()
    anim_layers.restore_for_anim_layers(stored_blend, target.translateX)
    cmds.currentTime(10)
    suite.check('and restoring it onto another object reproduces the value',
                abs(target.translateX.get() - expected) < 0.001,
                '{0} against {1}'.format(target.translateX.get(), expected))

    harness.new_scene()
    empty = pm.createNode('transform', name='no_animation')
    suite.check('an object with no animation stores an empty mapping',
                anim_layers.store_object_animation(empty) == {})

    # A plain, unlayered object goes through the same entry point.
    harness.new_scene()
    node = _keyed('plain_store', 'translateX', ((0, 0), (10, 10)))
    stored = anim_layers.store_object_animation(node)
    suite.check('a plain animated object stores its curve', len(stored) == 1, str(stored))

    # -- the bug: a float start frame was ignored, and zero meant "not given" ------------ #
    harness.new_scene()
    node = _keyed('float_start', 'translateX', ((20.0, 0), (30.0, 10)))
    stored = anim_layers.store_object_animation(node, start_time=0.0)
    stored_curve = list(stored.values())[0].node() if stored else None
    times = sorted(cmds.keyframe(str(stored_curve), query=True) or []) if stored_curve else []
    suite.check('a start frame of zero, as a float, is honoured', times == [0.0, 10.0], str(times))
    original = sorted(cmds.keyframe('float_start.translateX', query=True) or [])
    suite.check('and the object keeps its own animation where it was',
                original == [20.0, 30.0], str(original))

    # -- adjust_layers_timeline reports the latest end, not the last one listed ---------- #
    harness.new_scene()
    node, layer = _layered('timeline')
    blend = node.translateX.listConnections(type=pm.nt.AnimBlendNodeBase)[0]
    suite.check('no start time means no end frame',
                anim_layers.adjust_layers_timeline(blend, None) is None)
    end_frame = anim_layers.adjust_layers_timeline(blend, 5)
    suite.check('shifting the network reports its last frame', end_frame == 15.0, str(end_frame))


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_keyframes(suite, pm)
    check_baking(suite, pm)
    check_anim_curves(suite, pm)
    check_anim_layers(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('animation', body))
