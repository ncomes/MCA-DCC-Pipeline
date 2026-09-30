"""
The FRAG metadata node, in a real Maya.

    mayapy tests/test_frag_base.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def _test_classes(frag_base):
    """
    The FRAGNode subclasses the checks are run against.

    Built once and handed round: defining a class registers it, and the register is the thing half
    of these checks are about.
    """

    class Basic(frag_base.FRAGNode):
        """A component with nothing special about it."""

        VERSION = 1

    class Other(frag_base.FRAGNode):
        """A second one, so the of_type filters have something to leave out."""

        VERSION = 1

    class FakeRoot(frag_base.FRAGNode):
        """Stands in for FRAGRoot: the node at the top of one asset's rig."""

        VERSION = 1

        @classmethod
        def create(cls, asset_id):
            frag_node = frag_base.FRAGNode.create(None, cls.__name__, cls.VERSION)
            frag_node.pynode.addAttr(frag_base.IS_FRAG_ROOT_ATTR, at='bool', dv=True)
            frag_node.pynode.addAttr('assetId', dt='string')
            frag_node.pynode.attr('assetId').set(asset_id)
            return frag_node

        @property
        def asset_id(self):
            return self.pynode.attr('assetId').get()

    class Updatable(frag_base.FRAGNode):
        """Two versions behind, with the steps to catch up."""

        VERSION = 3

        def _update_version_1_to_version_2(self):
            self.pynode.addAttr('cameFromVersion1', at='bool', dv=True)
            self.set_version(2)

        def _update_version_2_to_version_3(self):
            self.pynode.addAttr('cameFromVersion2', at='bool', dv=True)
            self.set_version(3)

    class MissingStep(frag_base.FRAGNode):
        """A version behind with no way to catch up, which is a mistake in the component."""

        VERSION = 2

    class Forgetful(frag_base.FRAGNode):
        """An update step that does not record the version it reached."""

        VERSION = 2

        def _update_version_1_to_version_2(self):
            self.pynode.addAttr('ranAtLeastOnce', at='bool', dv=True)

    return {'Basic': Basic, 'Other': Other, 'FakeRoot': FakeRoot, 'Updatable': Updatable,
            'MissingStep': MissingStep, 'Forgetful': Forgetful}


def check_is_frag_node(suite, pm, frag_base, classes):
    harness.new_scene()

    node = frag_base.FRAGNode.create(None, 'Basic', 1)
    suite.check('a node built as a FRAG node is one', frag_base.is_frag_node(node.pynode))
    suite.check('and so is the wrapper round it', frag_base.is_frag_node(node))
    suite.check('a transform is not', not frag_base.is_frag_node(pm.polyCube()[0]))
    suite.check('a plain network node is not', not frag_base.is_frag_node(pm.createNode('network')))
    suite.check('a name that is not in the scene is not, and does not raise',
                not frag_base.is_frag_node('no_such_node'))
    # pm.objExists(None) raises `RuntimeError: Too few arguments given` rather than answering.
    suite.check('and neither is nothing at all, which used to raise out of pm.objExists',
                not frag_base.is_frag_node(None))

    legacy = pm.createNode('network', n='an_old_rig_node')
    legacy.addAttr(frag_base.LEGACY_FRAG_TYPE_ATTR, dt='string')
    legacy.attr(frag_base.LEGACY_FRAG_TYPE_ATTR).set('SomeOldThing')
    suite.check('a node carrying only the name the attribute had before FRAG was called FRAG is '
                'still one of ours',
                frag_base.is_frag_node(legacy))
    # ...but there is no class name on it to look up, which is the mismatch the walkers have to
    # cope with rather than raise on.
    suite.raises('even though nothing can wrap it as a class', frag_base.FRAGNode, legacy)


def check_the_register(suite, pm, frag_base, classes):
    register = frag_base.FRAGNodeRegister.__frag_node_types__

    suite.check('a FRAGNode subclass is filed under its own class name',
                register.get('Basic') is classes['Basic'])
    suite.check('the base class too', register.get('FRAGNode') is frag_base.FRAGNode)

    # The name is all a node in a scene carries, so two classes cannot share one.
    frag_base.FRAGNodeRegister('Clashing', (frag_base.FRAGNode,), {'__module__': 'one.module'})
    message = suite.raises(
        'a second class of the same name from a different module is refused',
        frag_base.FRAGNodeRegister, 'Clashing', (frag_base.FRAGNode,),
        {'__module__': 'other.module'})
    suite.check('and the refusal names both of them',
                'one.module.Clashing' in message and 'other.module.Clashing' in message, message)

    # The bug: the same name from the same module is a module that has been imported again, which is
    # what frag/__init__.py does on purpose. The metaclass compared the paths, found them equal, and
    # then kept the class from before the reload.
    first = frag_base.FRAGNodeRegister('Reloaded', (frag_base.FRAGNode,),
                                       {'__module__': 'a.module'})
    suite.check('the first import of a class files it', register.get('Reloaded') is first)
    second = frag_base.FRAGNodeRegister('Reloaded', (frag_base.FRAGNode,),
                                        {'__module__': 'a.module'})
    suite.check('importing the same module again files the class it has just built, rather than '
                'keeping the one from before the reload',
                register.get('Reloaded') is second and second is not first)

    harness.new_scene()
    reloaded_node = frag_base.FRAGNode.create(None, 'Reloaded', 1)
    suite.check('so a node in the scene comes back as the newer class',
                type(frag_base.FRAGNode(reloaded_node.pynode)) is second)


def check_creating(suite, pm, frag_base, classes):
    import maya.cmds as cmds

    harness.new_scene()
    node = frag_base.FRAGNode.create(None, 'Basic', 1)

    suite.check('a new node is a network node', isinstance(node.pynode, pm.nt.Network))
    suite.check('named after the class that goes with it', str(node.pynode) == 'Basic',
                str(node.pynode))
    suite.check('and it comes back as that class, not as the base',
                isinstance(node, classes['Basic']))
    suite.check('carrying the class name, so it can be read back',
                node.get_type() == 'Basic', str(node.get_type()))
    suite.check('the version it was built at', node.get_version() == 1.0, str(node.get_version()))
    suite.check('and the two attributes the graph is made of',
                node.has_attribute(frag_base.FRAG_PARENT_ATTR) and
                node.has_attribute(frag_base.FRAG_CHILDREN_ATTR))

    suite.check('wrapping the node again gives the same class',
                isinstance(frag_base.FRAGNode(node.pynode), classes['Basic']))
    suite.check('wrapping the wrapper works too',
                isinstance(frag_base.FRAGNode(node), classes['Basic']))
    suite.check('and so does wrapping it by name',
                isinstance(frag_base.FRAGNode('Basic'), classes['Basic']))

    # The bug: the node was created and its attributes written before anything checked that the type
    # could be read back, so a typo left a network node in the scene.
    before = len(cmds.ls(type='network'))
    message = suite.raises('a type no class answers to is refused',
                           frag_base.FRAGNode.create, None, 'NotAComponent', 1)
    suite.check('the refusal names the type it was given', 'NotAComponent' in message, message)
    suite.check('and no node was left behind', len(cmds.ls(type='network')) == before,
                str(cmds.ls(type='network')))

    message = suite.raises('a transform cannot be a FRAG node',
                           frag_base.FRAGNode, pm.polyCube()[0])
    suite.check('and the refusal says what it is instead', 'transform' in message, message)

    bare = pm.createNode('network', n='not_a_frag_node')
    suite.raises('nor can a network node with nothing on it saying what it is',
                 frag_base.FRAGNode, bare)
    bare.addAttr(frag_base.FRAG_TYPE_ATTR, dt='string')
    bare.attr(frag_base.FRAG_TYPE_ATTR).set('AClassFromAnotherProject')
    message = suite.raises('nor one naming a class no loaded package has',
                           frag_base.FRAGNode, bare)
    suite.check('and that refusal names the class it was looking for',
                'AClassFromAnotherProject' in message, message)


def check_the_graph(suite, pm, frag_base, classes):
    harness.new_scene()

    root = classes['FakeRoot'].create('hero_001')
    rig = frag_base.FRAGNode.create(root, 'Basic', 1)
    arm = frag_base.FRAGNode.create(rig, 'Basic', 1)
    arm.side = 'left'
    arm.region = 'arm'
    leg = frag_base.FRAGNode.create(rig, 'Other', 1)
    leg.side = 'right'
    leg.region = 'leg'

    suite.check('a node built under another is wired to it',
                rig.get_frag_parent().pynode == root.pynode)
    suite.check('and comes back as its own class',
                isinstance(arm.get_frag_parent(), classes['Basic']))
    suite.check('a node built with no parent has none', root.get_frag_parent() is None)

    # The trap get_frag_node_parents fell into: its first line was pm.PyNode(node), and it handed
    # its own answer - a FRAGNode - back to itself, which pm.PyNode refuses.
    suite.check('the module level version takes a wrapper as well as a node',
                frag_base.get_frag_parent(rig).pynode == root.pynode)
    suite.check('and a name', frag_base.get_frag_parent(str(rig.pynode)).pynode == root.pynode)
    suite.check('something with no fragParent at all has no parent',
                frag_base.get_frag_parent(pm.polyCube()[0]) is None)

    children = rig.get_frag_children()
    suite.check('the children of a node are the nodes built under it', len(children) == 2,
                str(children))
    suite.check('filtered by class',
                len(rig.get_frag_children(of_type=classes['Other'])) == 1)
    suite.check('by side', len(rig.get_frag_children(side='left')) == 1)
    suite.check('by region', len(rig.get_frag_children(region='leg')) == 1)
    suite.check('and by all three at once',
                len(rig.get_frag_children(of_type=classes['Basic'], side='left',
                                          region='arm')) == 1)
    suite.check('the first child is the first of them',
                rig.get_frag_child().pynode in [child.pynode for child in children])
    suite.check('a node with nothing under it has no children', arm.get_frag_children() == [])

    # The bug: set_frag_parent checks with is_frag_node, which says yes to a raw network node, and
    # then reaches for .pynode on it.
    loose = frag_base.FRAGNode.create(None, 'Basic', 1)
    loose.set_frag_parent(rig.pynode)
    suite.check('a node can be hung under a parent given as a plain node, which is what '
                'is_frag_node accepts',
                loose.get_frag_parent().pynode == rig.pynode)
    suite.raises('and something that is not a FRAG node at all is refused',
                 loose.set_frag_parent, pm.polyCube()[0])

    loose.set_frag_parent(root)
    suite.check('hanging a node under a new parent moves it', loose.get_frag_parent().pynode ==
                root.pynode)
    suite.check('and it is no longer a child of the old one', len(rig.get_frag_children()) == 2,
                str(rig.get_frag_children()))

    # -- the root, from anywhere inside ------------------------------------------------------- #
    suite.check('the root of a rig is found from a node two levels down',
                frag_base.FRAGNode.get_frag_root(arm).pynode == root.pynode)
    suite.check('from the root itself',
                frag_base.FRAGNode.get_frag_root(root).pynode == root.pynode)
    suite.check('from a plain node', frag_base.FRAGNode.get_frag_root(arm.pynode).pynode ==
                root.pynode)
    suite.check('and it is static now, so calling it on the class works as well as on an instance',
                arm.get_frag_root(arm).pynode == root.pynode)
    harness.new_scene()
    orphan = frag_base.FRAGNode.create(None, 'Basic', 1)
    suite.check('a node that is not under a root has none',
                frag_base.FRAGNode.get_frag_root(orphan) is None)
    suite.check('and something that is not a FRAG node has none either',
                frag_base.FRAGNode.get_frag_root(pm.polyCube()[0]) is None)

    harness.new_scene()
    root = classes['FakeRoot'].create('hero_001')
    arm = frag_base.FRAGNode.create(root, 'Basic', 1)
    suite.check('the asset a rig was built for is read off its root, from anywhere inside it',
                frag_base.FRAGNode.get_asset_id(arm) == 'hero_001',
                str(frag_base.FRAGNode.get_asset_id(arm)))
    suite.check('and a node with no root above it has no asset',
                frag_base.FRAGNode.get_asset_id(frag_base.FRAGNode.create(None, 'Basic', 1))
                is None)


def check_walking(suite, pm, frag_base, classes):
    harness.new_scene()

    root = classes['FakeRoot'].create('hero_001')
    rig = frag_base.FRAGNode.create(root, 'Basic', 1)
    arm = frag_base.FRAGNode.create(rig, 'Basic', 1)
    hand = frag_base.FRAGNode.create(arm, 'Other', 1)

    descendants = frag_base.get_frag_node_descendants(root)
    suite.check('every node under one is found, however far down', len(descendants) == 3,
                str(descendants))
    suite.check('filtered by class',
                len(frag_base.get_frag_node_descendants(root, of_type=classes['Other'])) == 1)
    suite.check('a node with nothing under it has no descendants',
                frag_base.get_frag_node_descendants(hand) == [])
    suite.check('and neither has something that is not a FRAG node',
                frag_base.get_frag_node_descendants(pm.polyCube()[0]) == [])

    suite.check('every FRAG node in the scene is found', len(frag_base.get_all_frag_nodes()) == 4,
                str(frag_base.get_all_frag_nodes()))
    suite.check('filtered by class',
                len(frag_base.get_all_frag_nodes(of_type=classes['Other'])) == 1)

    # The bug: is_frag_node says yes to a node carrying only the legacy attribute, and to a fragType
    # naming a class this project has not loaded - and then FRAGNode refuses both. One of either
    # in a scene and the whole walk raised.
    legacy = pm.createNode('network', n='an_old_rig_node')
    legacy.addAttr(frag_base.LEGACY_FRAG_TYPE_ATTR, dt='string')
    unknown = pm.createNode('network', n='someone_elses_component')
    unknown.addAttr(frag_base.FRAG_TYPE_ATTR, dt='string')
    unknown.attr(frag_base.FRAG_TYPE_ATTR).set('AClassFromAnotherProject')
    suite.check('a node this pipeline cannot wrap is left out rather than stopping the walk over '
                'all of them',
                len(frag_base.get_all_frag_nodes()) == 4,
                str(frag_base.get_all_frag_nodes()))


def check_versions(suite, pm, frag_base, classes):
    harness.new_scene()

    node = frag_base.FRAGNode.create(None, 'Basic', 1)
    node.set_version(4)
    suite.check('the version a node records can be read back', node.get_version() == 4.0)
    node.set_version(1)

    # The bug: the version lives on a double attribute, so a node at version 1 reads back as 1.0 -
    # and the method name built from it was `_update_version_1.0_to_version_2.0`, which no component
    # has ever had. Five of them carry a _update_version_1_to_version_2 that could never run.
    harness.new_scene()
    behind = frag_base.FRAGNode.create(None, 'Updatable', 1)
    behind.update()
    suite.check('a node two versions behind is brought up to date',
                behind.get_version() == 3.0, str(behind.get_version()))
    suite.check('by running each step in turn',
                behind.has_attribute('cameFromVersion1') and
                behind.has_attribute('cameFromVersion2'))

    up_to_date = frag_base.FRAGNode.create(None, 'Updatable', 3)
    up_to_date.update()
    suite.check('a node already at the current version is left alone',
                not up_to_date.has_attribute('cameFromVersion1'))

    # A rig saved by a newer pipeline than the one reading it.
    from_the_future = frag_base.FRAGNode.create(None, 'Updatable', 9)
    from_the_future.update()
    suite.check('a node built by a newer pipeline is left at the version it was built at',
                from_the_future.get_version() == 9.0, str(from_the_future.get_version()))

    stuck = frag_base.FRAGNode.create(None, 'MissingStep', 1)
    message = suite.raises('a node with no step to bring it up is refused', stuck.update)
    suite.check('and the refusal names the node, the class and the method that is missing',
                str(stuck.pynode) in message and 'MissingStep' in message and
                '_update_version_1_to_version_2' in message, message)

    forgetful = frag_base.FRAGNode.create(None, 'Forgetful', 1)
    message = suite.raises('a step that does not record the version it reached is refused, rather '
                           'than looping for ever', forgetful.update)
    suite.check('and it ran before that was noticed', forgetful.has_attribute('ranAtLeastOnce'))

    # The bug: update_all_frag_nodes stopped at the first node it could not bring up, so one
    # component with a missing step left every other node in the scene at its old version.
    harness.new_scene()
    frag_base.FRAGNode.create(None, 'MissingStep', 1)
    to_update = frag_base.FRAGNode.create(None, 'Updatable', 1)
    failures = frag_base.update_all_frag_nodes()
    suite.check('updating a whole scene carries on past a node it cannot bring up',
                to_update.get_version() == 3.0, str(to_update.get_version()))
    suite.check('and says which ones it could not', len(failures) == 1, str(failures))


def check_the_node_itself(suite, pm, frag_base, classes):
    harness.new_scene()

    node = frag_base.FRAGNode.create(None, 'Basic', 1)
    suite.check('a node has no side or region until it is given one',
                node.side == '' and node.region == '')
    node.side = 'left'
    node.region = 'arm'
    suite.check('and both read back once it has', node.side == 'left' and node.region == 'arm')
    node.side = 'right'
    suite.check('setting one again writes over it rather than failing on the attribute it made',
                node.side == 'right')

    suite.check('the node itself is there under two names',
                node.get_pynode() == node.pynode)
    suite.check('its name is a string', node.name() == str(node.pynode), node.name())
    suite.check('a node at the scene root has no namespace', node.get_namespace() == '',
                repr(node.get_namespace()))
    suite.check('an attribute can be read by name', node.get_attr('version') == 1.0)
    suite.check('a bare FRAG node owns no controls', node.get_flags() == [])

    # -- attributes an older version of a component held under other names ------------------- #
    node.pynode.addAttr('oldName', at='double')
    node.pynode.attr('oldName').set(7)
    suite.check('an attribute is read under the name it has now if it has it',
                node.get_attr_with_legacy_name('version', 'oldName') == 1.0)
    suite.check('and under the name it used to have if it does not',
                node.get_attr_with_legacy_name('newName', 'oldName') == 7.0)
    suite.check('neither name being there answers nothing',
                node.get_attr_with_legacy_name('newName', 'olderName') is None)

    driver = pm.spaceLocator(name='a_driver')
    driver.translateX >> node.pynode.attr('oldName')
    node.rename_legacy_attrs({'oldName': 'newName'})
    suite.check('renaming an old attribute keeps whatever is driving it',
                node.pynode.hasAttr('newName') and not node.pynode.hasAttr('oldName') and
                driver in node.pynode.attr('newName').listConnections())

    # -- wiring things to a node -------------------------------------------------------------- #
    harness.new_scene()
    node = frag_base.FRAGNode.create(None, 'Basic', 1)
    other = frag_base.FRAGNode.create(None, 'Other', 1)
    cube = pm.polyCube(name='a_mesh')[0]

    node.connect_node(cube, 'theMesh')
    suite.check('a plain node can be wired to a FRAG node',
                cube in node.pynode.attr('theMesh').listConnections())
    node.connect_node(other, 'theOther')
    suite.check('and so can another FRAG node, through its wrapper',
                other.pynode in node.pynode.attr('theOther').listConnections())
    node.connect_node('a_mesh', 'byName')
    suite.check('and so can a name', cube in node.pynode.attr('byName').listConnections())

    second_cube = pm.polyCube(name='another_mesh')[0]
    node.connect_nodes([cube, second_cube], 'theMeshes')
    suite.check('several nodes can be wired at once',
                len(node.pynode.attr('theMeshes').listConnections()) == 2,
                str(node.pynode.attr('theMeshes').listConnections()))
    node.connect_nodes(cube, 'oneInAList')
    suite.check('one on its own does not have to be in a list',
                cube in node.pynode.attr('oneInAList').listConnections())

    node.connect_nodes([cube, second_cube], 'ownedMeshes', parent_attr='ownedBy')
    suite.check('wiring through an attribute on the other node puts that attribute there, so a '
                'mesh can say which component owns it',
                cube.hasAttr('ownedBy') and
                node.pynode in cube.attr('ownedBy').listConnections())


def body(suite):
    harness.add_sibling_packages()
    import pymel.core as pm
    from mca.mya.rigging.frag import frag_base
    classes = _test_classes(frag_base)
    check_is_frag_node(suite, pm, frag_base, classes)
    check_the_register(suite, pm, frag_base, classes)
    check_creating(suite, pm, frag_base, classes)
    check_the_graph(suite, pm, frag_base, classes)
    check_walking(suite, pm, frag_base, classes)
    check_versions(suite, pm, frag_base, classes)
    check_the_node_itself(suite, pm, frag_base, classes)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('frag_base', body))
