"""
Node names and namespaces: mca.mya.utils.naming and mca.mya.utils.namespace.

    mayapy tests/test_naming.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_naming(suite):
    import maya.cmds as cmds
    from mca.mya.utils import naming

    # -- get_basename ------------------------------------------------------------------- #
    suite.check('a plain name is its own base name', naming.get_basename('arm') == 'arm')
    suite.check('a DAG path gives its last part',
                naming.get_basename('grpA|grpB|pSphere1') == 'pSphere1')
    suite.check('the namespace comes off by default',
                naming.get_basename('char:rig:arm') == 'arm')
    suite.check('the namespace stays when asked',
                naming.get_basename('char:rig:arm', remove_namespace=False) == 'char:rig:arm')
    suite.check('an attribute stays by default',
                naming.get_basename('arm.translateX') == 'arm.translateX')
    suite.check('an attribute comes off when asked',
                naming.get_basename('arm.translateX', remove_attribute=True) == 'arm')
    suite.check('both at once',
                naming.get_basename('a|b|char:arm.tx', remove_attribute=True) == 'arm')

    # A PyNode, and the FRAG-style wrapper that has its Maya node on .pynode. The old code
    # raised AttributeError on the second one.
    import pymel.core as pm
    harness.new_scene()
    node = pm.createNode('transform', name='basename_probe')

    class Wrapper(object):
        def __init__(self, pynode):
            self.pynode = pynode

    suite.check('a PyNode works', naming.get_basename(node) == 'basename_probe')
    suite.check('a wrapper with .pynode works',
                naming.get_basename(Wrapper(node)) == 'basename_probe')

    # -- get_node_name_parts ------------------------------------------------------------ #
    # The bug: ''.join instead of '|'.join, so the DAG prefix came back with its separators
    # deleted. The docstring showed the right answer directly above the line that got it
    # wrong.
    prefix, namespace, base = naming.get_node_name_parts('a:a:grpA|a:a:grpB|a:b:pSphere1')
    suite.check('the DAG prefix keeps its separators', prefix == 'a:a:grpA|a:a:grpB', prefix)
    suite.check('the namespace is the whole namespace path', namespace == 'a:b', namespace)
    suite.check('the base name is the base name', base == 'pSphere1', base)

    suite.check('a bare name has no prefix and no namespace',
                naming.get_node_name_parts('arm') == ('', '', 'arm'))
    suite.check('a namespaced bare name',
                naming.get_node_name_parts('char:arm') == ('', 'char', 'arm'))
    suite.check('a path with no namespaces',
                naming.get_node_name_parts('a|b|c') == ('a|b', '', 'c'))

    # -- remove_illegal_characters ------------------------------------------------------ #
    # The bug: a leading or trailing space made it recurse, throw the recursion's result
    # away, and fall through to `return ''`. Every one of these used to be ''.
    suite.check('a leading space is stripped, not turned into an empty name',
                naming.remove_illegal_characters(' head_geo') == 'head_geo',
                naming.remove_illegal_characters(' head_geo'))
    suite.check('a trailing space too',
                naming.remove_illegal_characters('head_geo ') == 'head_geo')
    suite.check('both',
                naming.remove_illegal_characters('  head_geo  ') == 'head_geo')
    suite.check('an inner space becomes an underscore',
                naming.remove_illegal_characters('head geo') == 'head_geo')
    # And the part it never did at all, despite its name.
    suite.check('a dash becomes an underscore',
                naming.remove_illegal_characters('head-geo') == 'head_geo')
    suite.check('a dot becomes an underscore',
                naming.remove_illegal_characters('head.geo') == 'head_geo')
    suite.check('a slash becomes an underscore',
                naming.remove_illegal_characters('head/geo') == 'head_geo')
    suite.check('a run of illegal characters becomes one underscore',
                naming.remove_illegal_characters('head - geo') == 'head_geo',
                naming.remove_illegal_characters('head - geo'))
    suite.check('a legal name is left alone',
                naming.remove_illegal_characters('L_arm_01_ctrl') == 'L_arm_01_ctrl')
    suite.check('nothing usable gives nothing', naming.remove_illegal_characters('   ') == '')
    suite.check('all illegal gives nothing', naming.remove_illegal_characters('---') == '')
    suite.check('an empty string gives an empty string',
                naming.remove_illegal_characters('') == '')
    suite.check('None gives an empty string rather than raising',
                naming.remove_illegal_characters(None) == '')

    # -- make_maya_safe_name ------------------------------------------------------------ #
    suite.check('a name starting with a digit gets a letter in front',
                naming.make_maya_safe_name('01_arm') == 'a01_arm')
    suite.check('the number the caller chose is still visible',
                '01' in naming.make_maya_safe_name('01_arm'))
    suite.check('spaces and dashes are handled',
                naming.make_maya_safe_name(' my cool-node ') == 'my_cool_node',
                naming.make_maya_safe_name(' my cool-node '))
    suite.check('nothing usable gives nothing', naming.make_maya_safe_name('  ') == '')

    harness.new_scene()
    cmds.createNode('transform', name='taken')
    suite.check('make_unique leaves a free name alone',
                naming.make_maya_safe_name('free', make_unique=True) == 'free')
    suite.check('make_unique numbers a taken name',
                naming.make_maya_safe_name('taken', make_unique=True) == 'taken1')

    # -- get_unique_dagname ------------------------------------------------------------- #
    harness.new_scene()
    suite.check('a free name comes back as it is', naming.get_unique_dagname('spine') == 'spine')
    cmds.createNode('transform', name='spine')
    suite.check('a taken name gets a 1', naming.get_unique_dagname('spine') == 'spine1')
    cmds.createNode('transform', name='spine1')
    suite.check('and then a 2', naming.get_unique_dagname('spine') == 'spine2')

    # The padding bug: the old version stripped every trailing digit and appended the
    # count, so arm_01 became arm_2.
    cmds.createNode('transform', name='arm_01')
    suite.check('padding is kept - arm_01 goes to arm_02',
                naming.get_unique_dagname('arm_01') == 'arm_02',
                naming.get_unique_dagname('arm_01'))
    cmds.createNode('transform', name='arm_02')
    suite.check('and on to arm_03', naming.get_unique_dagname('arm_01') == 'arm_03')

    # And the one the old rstrip made a mess of: digits in the middle.
    cmds.createNode('transform', name='spine_02_ctrl')
    suite.check('digits in the middle of a name are left where they are',
                naming.get_unique_dagname('spine_02_ctrl') == 'spine_02_ctrl1',
                naming.get_unique_dagname('spine_02_ctrl'))
    suite.raises('an empty name is refused', naming.get_unique_dagname, '')


def check_namespace(suite):
    import maya.cmds as cmds
    from mca.mya.utils import namespace

    # -- all_namespaces, and the bug it exists for -------------------------------------- #
    # cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) lists what is under the
    # *current* namespace. Everything built on it answered differently depending on where
    # the caller was standing.
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='MCAUberCam')
    cmds.namespace(add='char')
    cmds.namespace(setNamespace=':char')
    cmds.namespace(add='rig')
    cmds.namespace(setNamespace=':')

    from_root = namespace.get_all_namespaces()
    suite.check('the scene namespaces are listed from the root',
                'MCAUberCam' in from_root and 'char' in from_root, str(from_root))
    suite.check('nested ones are listed too', 'char:rig' in from_root, str(from_root))
    suite.check("Maya's own are left out",
                'UI' not in from_root and 'shared' not in from_root, str(from_root))

    cmds.namespace(setNamespace=':char:rig')
    from_inside = namespace.get_all_namespaces()
    suite.check('the same answer from inside a namespace - the bug this replaces',
                from_inside == from_root, '{} vs {}'.format(from_inside, from_root))
    cmds.namespace(setNamespace=':')

    # exclude_list is not modified. The old version extended the caller's list.
    exclusions = ['char']
    namespace.get_all_namespaces(exclusions)
    namespace.get_all_namespaces(exclusions)
    suite.check("the caller's exclusion list is left as it was",
                exclusions == ['char'], str(exclusions))
    suite.check('exclusions are honoured',
                'char' not in namespace.get_all_namespaces(['char']))
    suite.check('an exclusion works with a leading colon too',
                'char' not in namespace.get_all_namespaces([':char']))

    # -- get_namespace ------------------------------------------------------------------ #
    suite.check('the top namespace of a node name',
                namespace.get_namespace('char:rig:arm') == 'char')
    suite.check('the whole namespace path when asked',
                namespace.get_namespace('char:rig:arm', top_only=False) == 'char:rig')
    suite.check('a name with no namespace answers empty',
                namespace.get_namespace('arm') == '')
    suite.check('a DAG path is handled',
                namespace.get_namespace('a|b|char:rig:arm', top_only=False) == 'char:rig')
    suite.check('check_node is gone - it never worked, and every caller turned it off',
                'check_node' not in namespace.get_namespace.__doc__)

    # -- set_namespace and find_unique_namespace ---------------------------------------- #
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    suite.check('setting a new namespace makes it and moves there',
                namespace.set_namespace('hero') == ':hero')
    cmds.namespace(setNamespace=':')
    suite.check('setting an existing one again numbers it, so two imports cannot collide',
                namespace.set_namespace('hero') == ':hero01')
    cmds.namespace(setNamespace=':')
    suite.check('check_existing False joins the namespace that is there',
                namespace.set_namespace('hero', check_existing=False) == ':hero')
    suite.check('the root is reachable', namespace.set_namespace(':') == ':')
    suite.check('an empty name means the root', namespace.set_namespace('') == ':')
    current = cmds.namespaceInfo(currentNamespace=True, absoluteName=True)
    suite.check('a name that is not a string is refused rather than half-applied',
                namespace.set_namespace(37) == current)

    suite.check('find_unique_namespace leaves a free name alone',
                namespace.find_unique_namespace('nobody_here') == 'nobody_here')
    suite.check('and numbers a taken one',
                namespace.find_unique_namespace('hero') == 'hero02',
                namespace.find_unique_namespace('hero'))

    # -- nodes in a namespace ----------------------------------------------------------- #
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='box')
    cmds.namespace(setNamespace=':box')
    cmds.createNode('transform', name='inside')
    cmds.namespace(add='deeper')
    cmds.namespace(setNamespace=':box:deeper')
    cmds.createNode('transform', name='further_in')
    cmds.namespace(setNamespace=':')

    shallow = [str(one) for one in namespace.get_all_nodes_in_namespace('box')]
    suite.check('the nodes in a namespace are found',
                any('inside' in one for one in shallow), str(shallow))
    suite.check('a child namespace is not included by default',
                not any('further_in' in one for one in shallow), str(shallow))
    deep = [str(one) for one in namespace.get_all_nodes_in_namespace('box', recursive=True)]
    suite.check('recursive reaches the child namespace',
                any('further_in' in one for one in deep), str(deep))
    suite.check('a namespace that is not there answers empty rather than raising',
                namespace.get_all_nodes_in_namespace('no_such_namespace') == [])

    # -- move_node_to_namespace --------------------------------------------------------- #
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='dest')
    moved = cmds.createNode('transform', name='wanderer')
    suite.check('a node moves into a namespace, and says so',
                namespace.move_node_to_namespace(moved, 'dest') is True)
    suite.check('and is there afterwards', cmds.objExists('dest:wanderer'))
    suite.check('it moves back to the root',
                namespace.move_node_to_namespace('dest:wanderer', '') is True)
    suite.check('and is there', cmds.objExists('wanderer'))

    # The bug: `except: pass`, so a rename that could not happen looked like one that did.
    # Callers drive this through map() over whole skeletons.
    locked = cmds.createNode('transform', name='locked_one')
    cmds.lockNode(locked, lock=True)
    suite.check('a rename that cannot happen answers False instead of pretending',
                namespace.move_node_to_namespace(locked, 'dest') is False)
    cmds.lockNode(locked, lock=False)

    # -- delete_empty_namespaces -------------------------------------------------------- #
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='empty_outer')
    cmds.namespace(setNamespace=':empty_outer')
    cmds.namespace(add='empty_inner')
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='has_something')
    cmds.createNode('transform', name='has_something:kept')

    removed = namespace.delete_empty_namespaces()
    suite.check('an empty nested namespace is removed',
                'empty_outer:empty_inner' in removed, str(removed))
    suite.check('and its now-empty parent with it, in the same pass',
                'empty_outer' in removed, str(removed))
    suite.check('a namespace with something in it is left alone',
                cmds.namespace(exists=':has_something'))
    suite.check("Maya's own namespaces are not touched",
                cmds.namespace(exists=':UI') and cmds.namespace(exists=':shared'))

    # And it must not depend on where the caller is standing either.
    cmds.namespace(add='another_empty')
    cmds.namespace(setNamespace=':has_something')
    removed = namespace.delete_empty_namespaces()
    suite.check('it works from inside a namespace too',
                'another_empty' in removed, str(removed))
    cmds.namespace(setNamespace=':')

    # -- purge_namespace ---------------------------------------------------------------- #
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='doomed')
    cmds.createNode('transform', name='doomed:one')
    cmds.namespace(setNamespace=':doomed')
    cmds.namespace(add='child')
    cmds.namespace(setNamespace=':')
    cmds.createNode('transform', name='doomed:child:two')

    suite.check('purging a namespace says it worked',
                namespace.purge_namespace('doomed') is True)
    suite.check('the namespace is gone', not cmds.namespace(exists=':doomed'))
    suite.check('its nodes are gone', not cmds.objExists('doomed:one'))
    suite.check('the child namespace is gone too', not cmds.namespace(exists=':doomed:child'))

    suite.check('the root is refused', namespace.purge_namespace(':') is False)
    suite.check('an empty name is refused', namespace.purge_namespace('') is False)
    suite.check('a namespace that is not there answers False, not an exception',
                namespace.purge_namespace('never_existed') is False)

    # A locked node inside used to make the whole purge fail.
    cmds.namespace(add='locked_up')
    node = cmds.createNode('transform', name='locked_up:stuck')
    cmds.lockNode(node, lock=True)
    suite.check('a locked node inside is unlocked and removed with the rest',
                namespace.purge_namespace('locked_up') is True)
    suite.check('and the namespace is gone', not cmds.namespace(exists=':locked_up'))


def body(suite):
    harness.add_sibling_packages()
    check_naming(suite)
    check_namespace(suite)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('naming', body))
