"""
Writing a skeleton down and building it back, in a real Maya.

    mayapy tests/test_rigging_skel.py
"""

# python imports
import os
import stat
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _skeleton(pm, count=4, root_name='root'):
    """A chain of joints up Y, with a name that is not a joint name at the top."""

    import maya.cmds as cmds

    cmds.select(clear=True)
    joints = []
    for index in range(count):
        name = root_name if not index else 'b_spine_{0:02d}'.format(index)
        joints.append(pm.PyNode(cmds.joint(name=name, position=(0, index * 30, 0), absolute=True)))
    return joints


def _mark_up(joints):
    """Put a couple of user attributes on a skeleton, standing in for its markup."""

    for index, joint_node in enumerate(joints):
        joint_node.addAttr('mcaRegion', dt='string')
        joint_node.attr('mcaRegion').set('spine')
        joint_node.addAttr('mcaIndex', at='long', keyable=True)
        joint_node.attr('mcaIndex').set(index)


def check_serializing(suite, pm):
    from mca.mya.rigging import skel_utils

    harness.new_scene()
    suite.check('something that is not a joint has no skeleton to write down',
                skel_utils.serialize_skeleton(pm.polyCube()[0]) is None)
    suite.check('and nor has nothing at all', skel_utils.serialize_skeleton(None) is None)

    harness.new_scene()
    lone = _skeleton(pm, count=1)[0]
    suite.check('a joint with nothing under it is not a skeleton either',
                skel_utils.serialize_skeleton(lone) is None)

    harness.new_scene()
    joints = _skeleton(pm, count=4)
    _mark_up(joints)
    data = skel_utils.serialize_skeleton(joints[0])

    suite.check('a skeleton is written down with one entry per joint',
                len(data) == 4, str(sorted(data)))
    suite.check('keyed by each joint\'s own name, the root included',
                sorted(data) == ['b_spine_01', 'b_spine_02', 'b_spine_03', 'root'],
                str(sorted(data)))
    suite.check('the root is the entry with no parent',
                data['root']['parent_node'] is None, str(data['root']['parent_node']))
    suite.check('and every other entry names its parent',
                data['b_spine_02']['parent_node'] == 'b_spine_01',
                str(data['b_spine_02']['parent_node']))
    suite.check('each entry holds a world matrix, as sixteen numbers',
                len(data['b_spine_01']['world_matrix']) == 16,
                str(data['b_spine_01']['world_matrix']))
    suite.check('and the radius the joint is drawn at',
                'radius' in data['b_spine_01'], str(sorted(data['b_spine_01'])))
    suite.check('the markup is written down with it',
                sorted(attribute.get('name') or attribute.get('longName')
                       for attribute in data['b_spine_02']['attributes']) ==
                ['mcaIndex', 'mcaRegion'],
                str(data['b_spine_02']['attributes']))

    # Maya's own user attribute on a bound joint. It is not markup, and it holds an artist's
    # per-joint weight locks.
    mesh = pm.polyCube()[0]
    pm.skinCluster(joints, mesh)
    suite.check('a bound joint carries lockInfluenceWeights',
                'lockInfluenceWeights' in pm.listAttr(joints[1], userDefined=True))
    bound_data = skel_utils.serialize_skeleton(joints[0])
    suite.check('which is not written down as part of the markup',
                'lockInfluenceWeights' not in
                [attribute.get('name') or attribute.get('longName')
                 for attribute in bound_data['b_spine_01'].get('attributes', [])],
                str(bound_data['b_spine_01'].get('attributes')))


def check_the_file(suite, pm):
    from mca.mya.rigging import skel_utils

    harness.new_scene()
    joints = _skeleton(pm, count=4)
    _mark_up(joints)

    skl_path = os.path.join(suite.temp, 'hero')
    suite.check('a skeleton is written to a .skl file',
                skel_utils.export_skeleton(skl_path, joints[0]) is True)
    suite.check('the extension is added when the path is given without one',
                os.path.isfile(skl_path + '.skl'))
    suite.check('and giving it with one does not add a second',
                skel_utils.export_skeleton(skl_path + '.skl', joints[0]) is True and
                not os.path.exists(skl_path + '.skl.skl'))

    # Every .skl in this pipeline comes out of Perforce read-only until it is checked out. That is
    # what fileio.touch_path is for, and it was being handed the path without its extension - so it
    # made the folder and never touched the file about to be written.
    os.chmod(skl_path + '.skl', stat.S_IREAD)
    suite.check('a skeleton can be written over a read-only file, which is how they come out of '
                'source control',
                skel_utils.export_skeleton(skl_path, joints[0]) is True)

    # The path was trimmed with path.replace('.skl', ''), which strikes anywhere in a path.
    backup_folder = os.path.join(suite.temp, '.skl_backups')
    os.makedirs(backup_folder)
    backup_path = os.path.join(backup_folder, 'hero.skl')
    suite.check('a path with .skl somewhere in the middle of it is left alone',
                skel_utils.export_skeleton(backup_path, joints[0]) is True and
                os.path.isfile(backup_path),
                backup_path)

    suite.check('reading a file that is not there gives nothing, rather than raising',
                skel_utils.SkeletonData(os.path.join(suite.temp, 'nothing')).read_data() == {})
    suite.check('a skeleton cannot be saved without a path',
                skel_utils.SkeletonData('').save_data({'a': 1}) is False)

    # -- the round trip -------------------------------------------------------------------------- #
    harness.new_scene()
    rebuilt = skel_utils.import_skeleton(skl_path)
    suite.check('a skeleton is built back from its file', rebuilt is not None)
    suite.check('under its own root name', str(rebuilt) == 'root', str(rebuilt))
    rebuilt_joints = [rebuilt] + pm.listRelatives(rebuilt, allDescendents=True, type=pm.nt.Joint)
    suite.check('with every joint in it', len(rebuilt_joints) == 4, str(rebuilt_joints))
    suite.check('parented the way they were',
                str(pm.PyNode('b_spine_02').getParent()) == 'b_spine_01',
                str(pm.PyNode('b_spine_02').getParent()))
    suite.check('standing where they were',
                abs(pm.PyNode('b_spine_03').getTranslation(space='world')[1] - 90.0) < 0.001,
                str(pm.PyNode('b_spine_03').getTranslation(space='world')))
    suite.check('and with their markup on them',
                pm.PyNode('b_spine_02').mcaRegion.get() == 'spine' and
                pm.PyNode('b_spine_02').mcaIndex.get() == 2,
                str(pm.PyNode('b_spine_02').mcaRegion.get()))

    harness.new_scene()
    # The version before answered (None, []) here, and its caller handed that tuple to pm.xform.
    suite.check('importing a file that is not there gives nothing, rather than a tuple that the '
                'next line treats as a skeleton',
                skel_utils.import_skeleton(os.path.join(suite.temp, 'nothing')) is None)
    suite.check('and merging from one does the same',
                skel_utils.import_merge_skeleton(os.path.join(suite.temp, 'nothing'), None) is None)


def check_building_from_data(suite, pm):
    import maya.cmds as cmds
    from mca.mya.rigging import skel_utils

    harness.new_scene()
    joints = _skeleton(pm, count=4)
    data = skel_utils.serialize_skeleton(joints[0])

    # -- a parent the file does not contain ------------------------------------------------------ #
    harness.new_scene()
    orphaned = dict((name, dict(entry)) for name, entry in data.items())
    orphaned['b_spine_02']['parent_node'] = 'a_joint_that_is_not_here'
    # A KeyError before.
    built = skel_utils.create_skeleton_from_data(orphaned)
    suite.check('a joint whose parent is not in the file is left at the world root, rather than '
                'raising',
                built is not None and pm.PyNode('b_spine_02').getParent() is None)

    # -- no root, and two of them ---------------------------------------------------------------- #
    harness.new_scene()
    rootless = dict((name, dict(entry)) for name, entry in data.items())
    rootless['root']['parent_node'] = 'b_spine_03'
    # Every entry having a parent inside the file means a loop, not a skeleton. Building first and
    # finding out during the parenting left the joints in the scene and raised out of the middle of
    # it: `Cannot parent an object to one of its children`.
    suite.check('a file in which every joint has a parent inside it describes a loop, and is '
                'refused',
                skel_utils.create_skeleton_from_data(rootless) is None)
    suite.check('and nothing was built before that was noticed', not cmds.ls(type='joint'),
                str(cmds.ls(type='joint')))

    harness.new_scene()
    two_roots = dict((name, dict(entry)) for name, entry in data.items())
    two_roots['b_spine_02']['parent_node'] = None
    suite.check('a file with two roots in it builds, and one of them comes back',
                skel_utils.create_skeleton_from_data(two_roots) is not None)

    # -- a name something else in the scene already has ------------------------------------------ #
    harness.new_scene()
    cube = pm.polyCube(name='b_spine_01')[0]
    built = skel_utils.create_skeleton_from_data(data)
    suite.check('a joint whose name is taken by something else still gets its name, because every '
                'other entry in the file refers to it by that name',
                bool(cmds.ls('b_spine_01', type='joint')), str(cmds.ls('b_spine_01*')))
    suite.check('and the thing that had it is moved aside under a name that says where it went',
                str(cube).startswith('b_spine_01_was_here'), str(cube))
    # Asking Maya for a name that is taken does not give the name with a 1 on the end: b_spine_01
    # taken gives b_spine_02, which is the next joint in this very file.
    suite.check('the joint after it in the file keeps its own name',
                bool(cmds.ls('b_spine_02', type='joint')) and
                str(pm.PyNode('b_spine_02').getParent()) == 'b_spine_01',
                str(cmds.ls('b_spine_0*', type='joint')))
    suite.check('and the skeleton is whole', len(cmds.ls(type='joint')) == 4,
                str(cmds.ls(type='joint')))

    # -- merging ------------------------------------------------------------------------------- #
    harness.new_scene()
    existing = _skeleton(pm, count=2)
    merged = skel_utils.create_and_merge_skeletons_from_data(existing[0], data)
    suite.check('merging adds only the joints that are not there already',
                len(cmds.ls(type='joint')) == 4, str(cmds.ls(type='joint')))
    suite.check('the root that was there is the root that comes back', merged == existing[0])
    suite.check('and the new joints are parented onto the ones that were',
                str(pm.PyNode('b_spine_02').getParent()) == 'b_spine_01',
                str(pm.PyNode('b_spine_02').getParent()))

    harness.new_scene()
    suite.check('merging into nothing builds the whole skeleton instead',
                skel_utils.create_and_merge_skeletons_from_data(None, data) is not None and
                len(cmds.ls(type='joint')) == 4)


def check_restoring(suite, pm):
    from mca.mya.rigging import skel_utils

    # -- markup ---------------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    _mark_up(joints)
    data = skel_utils.serialize_skeleton(joints[0])

    for joint_node in joints:
        joint_node.attr('mcaRegion').set('wrong')
    skel_utils.restore_skeleton_markup_from_data(joints[0], data)
    suite.check('markup is put back onto a skeleton that has lost it',
                all(joint_node.mcaRegion.get() == 'spine' for joint_node in joints),
                str([joint_node.mcaRegion.get() for joint_node in joints]))
    suite.check('the root\'s with it',
                joints[0].hasAttr('mcaRegion') and joints[0].mcaRegion.get() == 'spine')

    joints[2].addAttr('leftoverJunk', at='long')
    skel_utils.restore_skeleton_markup_from_data(joints[0], data)
    suite.check('an attribute the file does not know about is cleared out',
                not joints[2].hasAttr('leftoverJunk'))

    # The bug: the purge deleted every user attribute, and lockInfluenceWeights is one. Restoring a
    # skeleton's markup silently cleared every per-joint weight lock in it.
    mesh = pm.polyCube()[0]
    pm.skinCluster(joints, mesh)
    joints[1].attr('lockInfluenceWeights').set(True)
    skel_utils.restore_skeleton_markup_from_data(joints[0], data)
    suite.check('Maya\'s own lockInfluenceWeights is left alone, so an artist\'s weight locks '
                'survive having markup put back',
                joints[1].hasAttr('lockInfluenceWeights') and
                joints[1].attr('lockInfluenceWeights').get() is True)

    driver = pm.spaceLocator(name='a_driver')
    joints[3].addAttr('drivenBySomething', at='double', keyable=True)
    driver.translateX >> joints[3].attr('drivenBySomething')
    skel_utils.restore_skeleton_markup_from_data(joints[0], data)
    suite.check('and an attribute something is driving is reported rather than deleted out from '
                'under whatever is driving it',
                joints[3].hasAttr('drivenBySomething'))

    # -- a root that is not called root ---------------------------------------------------------- #
    # Both readers looked the root up under the literal key 'root', while the writer keys every
    # joint by its own name - so a skeleton rooted anywhere else lost its root's markup and pose.
    harness.new_scene()
    odd_joints = _skeleton(pm, count=3, root_name='b_prop_base')
    _mark_up(odd_joints)
    odd_data = skel_utils.serialize_skeleton(odd_joints[0])
    odd_joints[0].attr('mcaRegion').set('wrong')
    skel_utils.restore_skeleton_markup_from_data(odd_joints[0], odd_data)
    suite.check('a skeleton whose root is not called root gets its root\'s markup back too',
                odd_joints[0].mcaRegion.get() == 'spine', odd_joints[0].mcaRegion.get())

    odd_joints[0].translate.set(11, 22, 33)
    skel_utils.return_skeleton_to_bind_pose_from_data(odd_joints[0], odd_data)
    suite.check('and its root\'s bind pose',
                odd_joints[0].getTranslation(space='world').length() < 0.001,
                str(odd_joints[0].getTranslation(space='world')))

    # A duplicated hierarchy, where Maya has put a number on the root's name: the fall back to the
    # file's own parentless entry is what the literal 'root' lookup was there for.
    duplicated = pm.duplicate(odd_joints[0])[0]
    duplicated.translate.set(5, 5, 5)
    skel_utils.return_skeleton_to_bind_pose_from_data(duplicated, odd_data)
    suite.check('a duplicated skeleton, whose root Maya has renamed, is still put back',
                duplicated.getTranslation(space='world').length() < 0.001,
                '{0} {1}'.format(duplicated, duplicated.getTranslation(space='world')))

    # -- the bind pose --------------------------------------------------------------------------- #
    harness.new_scene()
    joints = _skeleton(pm, count=4)
    skl_path = os.path.join(suite.temp, 'posed')
    skel_utils.export_skeleton(skl_path, joints[0])

    joints[1].rotateZ.set(45)
    joints[0].translate.set(100, 0, 0)
    skel_utils.restore_skeleton_bindpose(skl_path, joints[0])
    suite.check('a posed skeleton is put back to the pose in its file',
                all(abs(joint_node.getTranslation(space='world')[1] - index * 30) < 0.001
                    for index, joint_node in enumerate(joints)),
                str([joint_node.getTranslation(space='world') for joint_node in joints]))

    for joint_node in joints:
        if joint_node.hasAttr('mcaRegion'):
            joint_node.attr('mcaRegion').delete()
    skel_utils.restore_skeleton_markup(skl_path, joints[0])
    suite.check('and its markup is put back from the same file', True)


def check_radii(suite, pm):
    from mca.mya.rigging import skel_utils

    harness.new_scene()
    joints = _skeleton(pm, count=4)
    for joint_node in joints:
        joint_node.radius.set(1.0)
    skel_utils.scale_skel_radi(joints[0])

    radii = [joint_node.radius.get() for joint_node in joints]
    # The walk it used leaves the node it starts from out, so the root kept whatever it had.
    suite.check('the root\'s radius is set along with the rest',
                abs(radii[0] - 1.0) > 0.001, str(radii))
    suite.check('every radius is a positive number',
                all(radius > 0 for radius in radii), str(radii))
    suite.check('and each level down the hierarchy is drawn a little smaller',
                radii[0] > radii[1] > radii[2] > radii[3], str(radii))

    harness.new_scene()
    deep = _skeleton(pm, count=20)
    skel_utils.scale_skel_radi(deep[0])
    deep_radii = [joint_node.radius.get() for joint_node in deep]
    suite.check('the shrinking stops at a floor, so a long chain does not end in nothing',
                abs(deep_radii[-1] - deep_radii[-2]) < 0.000001 and
                deep_radii[-1] > deep_radii[0] * 0.39,
                str(deep_radii[-3:]))

    # The bug: the size was the sum of the bounding box's maximum corner, so it followed the
    # skeleton around the world. The same skeleton a thousand units along X came out eight times
    # bigger, and one below the origin came out negative - which draws nothing at all.
    harness.new_scene()
    here = _skeleton(pm, count=4)
    skel_utils.scale_skel_radi(here[0])
    at_origin = [joint_node.radius.get() for joint_node in here]
    here[0].translate.set(1000, 0, 0)
    skel_utils.scale_skel_radi(here[0])
    moved = [joint_node.radius.get() for joint_node in here]
    suite.check('moving a skeleton across the world does not change how big its joints are drawn',
                all(abs(one - other) < one * 0.05 for one, other in zip(at_origin, moved)),
                '{0} against {1}'.format(at_origin, moved))

    here[0].translate.set(0, -300, 0)
    skel_utils.scale_skel_radi(here[0])
    below = [joint_node.radius.get() for joint_node in here]
    suite.check('and a skeleton standing below the origin does not get a negative one',
                all(radius > 0 for radius in below), str(below))

    harness.new_scene()
    invisible = _skeleton(pm, count=1)[0]
    invisible.radius.set(0)
    skel_utils.scale_skel_radi(invisible)
    suite.check('a skeleton with no size at all is refused rather than divided by',
                invisible.radius.get() == 0, str(invisible.radius.get()))


def check_placement(suite, pm):
    from mca.mya.rigging import skel_utils

    # -- a planar chain ------------------------------------------------------------------------ #
    harness.new_scene()
    suite.check('a planar chain is made from exactly three nodes, and says so when it is not',
                skel_utils.make_planar_chain([]) == [])
    harness.new_scene()
    sources = _skeleton(pm, count=3)
    pm.PyNode('b_spine_01').translateZ.set(7)
    pm.PyNode('b_spine_02').translateX.set(4)

    chain = skel_utils.make_planar_chain(sources)
    suite.check('three joints come back', len(chain) == 3, str(chain))
    suite.check('parented into a chain of their own',
                chain[1].getParent() == chain[0] and chain[2].getParent() == chain[1])
    suite.check('each standing where the joint it was copied from stands',
                all((new.getTranslation(space='world') -
                     old.getTranslation(space='world')).length() < 0.001
                    for new, old in zip(chain, sources)),
                str([new.getTranslation(space='world') for new in chain]))
    # Both aimed joints share one up target, on the plane's normal, which is what puts them on one
    # plane rather than each finding its own.
    up_axes = [pm.dt.Vector(0, 0, 1).rotateBy(
        joint_node.getRotation(space='world', quaternion=True)) for joint_node in chain[:2]]
    suite.check('and the two that are aimed share an up direction, so they lie on one plane',
                abs(up_axes[0].dot(up_axes[1]) - 1.0) < 0.001,
                '{0} {1}'.format(up_axes[0], up_axes[1]))
    suite.check('the locator the plane was measured from is gone',
                not pm.ls('planar_chain_up_loc'))

    # -- twist joints -------------------------------------------------------------------------- #
    harness.new_scene()
    parent_joint = pm.PyNode(pm.joint(name='b_upperarm', position=(0, 0, 0), absolute=True))
    pm.select(clear=True)
    child_joint = pm.PyNode(pm.joint(name='b_lowerarm', position=(40, 0, 0), absolute=True))
    pm.select(clear=True)
    twists = []
    for index in range(3):
        pm.select(clear=True)
        twists.append(pm.PyNode(pm.joint(name='b_upperarm_twist_{0:02d}'.format(index + 1))))
    given_order = list(twists)

    skel_utils.position_twist_joints(twists, parent_joint, child_joint)
    placed = [joint_node.getTranslation(space='world')[0] for joint_node in given_order]
    suite.check('twist joints are spaced evenly along the segment, with neither end on a joint',
                all(abs(now - wanted) < 0.001 for now, wanted in zip(placed, [10.0, 20.0, 30.0])),
                str(placed))
    # The bug: the list was reversed in place, so each joint went to the opposite end of the segment
    # from where the docstring said it belonged.
    suite.check('the first in the list goes nearest the parent, which is what its docstring says',
                placed[0] < placed[-1], str(placed))
    suite.check('and the caller\'s list is not reversed out from under them', twists == given_order)
    suite.check('each joint is left with no orientation of its own',
                all(joint_node.jointOrient.get().length() < 0.001 for joint_node in twists))

    skel_utils.position_twist_joints([], parent_joint, child_joint)
    suite.check('being given no twist joints is refused rather than silently doing nothing', True)


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    check_serializing(suite, pm)
    check_the_file(suite, pm)
    check_building_from_data(suite, pm)
    check_restoring(suite, pm)
    check_radii(suite, pm)
    check_placement(suite, pm)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('rigging_skel', body))
