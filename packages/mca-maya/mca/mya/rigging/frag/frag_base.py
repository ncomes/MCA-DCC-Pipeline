"""
The metadata node every FRAG rig is described by.

A FRAG rig is a Maya rig with a second, invisible structure over it: a graph of ``network`` nodes,
each one standing for a piece of the rig - the rig itself, a limb, a set of controls - and each
carrying the name of the Python class that knows what to do with it. That name is the ``fragType``
attribute, and :class:`FRAGNodeRegister` is what turns it back into a class, so ``FRAGNode(node)``
on any of those nodes hands back an instance of the right subclass without the caller knowing which.

The graph is message attributes: a child's ``fragParent`` is connected from its parent's
``fragChildren``, so a rig can be walked up from any component and down from the root. Everything
else a node holds - which joints it drives, which controls belong to it - is another message
attribute, wired with :meth:`FRAGNode.connect_node` and :meth:`FRAGNode.connect_nodes`.

Each class also carries a ``VERSION``, and each node the version it was built at. When a component
changes what it stores, its class version goes up and it gains a
``_update_version_<n>_to_version_<n+1>`` method; :meth:`FRAGNode.update` runs those in turn to bring
an old rig up to date.

What was wrong before:

- **No rig has ever been brought up to date.** ``update`` built the method name out of the version
  it read off the node, and the version is stored on a ``double`` attribute - so a node at version 1
  asked for ``_update_version_1.0_to_version_2.0`` and got ``AttributeError``. Five components carry
  a ``_update_version_1_to_version_2`` and every one of them has been unreachable. Versions are read
  as whole numbers now, a node built by a newer pipeline than the code reading it is left alone
  rather than walked past in silence, and a missing step says which node, class and method.
- **``get_frag_node_parents`` raised as soon as a node had a parent at all.** Its first line is
  ``pm.PyNode(node)``, and it passed its own result - a ``FRAGNode`` - back into itself, which
  ``pm.PyNode`` refuses with ``MayaAttributeError``. It could only ever answer for a node with no
  frag parent, which is to say the empty list. Nothing called it; it is gone, and the module level
  ``get_frag_parent`` takes a ``FRAGNode`` as well as a node now, which is the trap it fell into.
- **Reloading the package left the register pointing at the classes from before the reload.** Every
  class name is registered once; on the second import the metaclass compared the module paths, found
  them equal - which is the whole point of a reload - and then did nothing, so the register kept the
  stale class and ``FRAGNode(node)`` handed back instances of it. Since ``frag/__init__.py`` drops
  its submodules from ``sys.modules`` and imports them again precisely so that edited code is picked
  up, this is the case that mattered. A class from the same module replaces the one registered; only
  a clash from a *different* module is refused.
- **A scene holding one FRAG node this pipeline cannot wrap could not be walked at all.**
  ``get_all_frag_nodes`` wraps everything ``is_frag_node`` says yes to, and ``is_frag_node`` says
  yes to a node carrying only the legacy ``xrigType``, which ``FRAGNode`` then refuses - as it does
  any ``fragType`` naming a class this project has not loaded. One such node in a scene and the
  call raised. The walkers report what they cannot wrap and carry on.
- **``is_frag_node(None)`` raised** ``RuntimeError: Too few arguments given`` out of
  ``pm.objExists``, and asking about a name that is not in the scene logged a warning - which is a
  question answered, not a problem.
- **A ``frag_type`` that is not a registered class left an orphan network node behind**, because
  ``create`` made the node, wrote the attributes and only then tried to wrap it.
- **``set_frag_parent`` accepted something it could not use**: it checks with ``is_frag_node``,
  which says yes to a raw network node, and then reaches for ``.pynode``.
- **Two of these wrapping one node were not equal to each other**, and a set of them held both.
  Every walk over the graph builds new wrappers, so ``list(set(rigs))`` never removed a repeat and
  ``x not in found`` was always true. They compare and hash by the node they wrap now.
- ``get_frag_root`` and ``get_asset_id`` read the node passed to them and never touch ``self``,
  which their own docstrings had to explain; they are static now, and every existing caller - all
  of which call them on an instance - still works. The two node-unwrapping ladders in
  ``connect_node`` and ``connect_nodes`` were the same ladder twice, and are one ``as_pynode`` now.
  ``add_frag_child``, ``set_attr``, ``add_attr``, ``list_attr_connections`` and
  ``list_frag_node_connections`` had no callers anywhere in the pipeline and are gone.
"""

# python imports
import importlib

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.startup.configs import ma_consts
from mca.mya.utils import attr_utils


logger = log.MCA_LOGGER

#: The string attribute holding the name of the Python class that knows what a node is.
FRAG_TYPE_ATTR = 'fragType'

#: What that attribute was called before FRAG was called FRAG. A node carrying only this is still
#: one of ours, but there is no class name on it to look up, so :class:`FRAGNode` cannot wrap it.
LEGACY_FRAG_TYPE_ATTR = 'xrigType'

#: The attribute holding the version a node was built at.
VERSION_ATTR = 'version'

#: The message attributes that make the graph: a child's parent, and a parent's children.
FRAG_PARENT_ATTR = 'fragParent'
FRAG_CHILDREN_ATTR = 'fragChildren'

#: What marks the node at the top of one asset's rig. ``frag_root`` is what puts it there.
IS_FRAG_ROOT_ATTR = 'isFragRoot'

#: The two pieces of markup any node can carry, so a caller can ask for the left arm's components.
SIDE_ATTR = 'side'
REGION_ATTR = 'region'

#: The compound attribute a node records the arguments it was built with in.
BUILD_KWARGS_ATTR = 'buildKwargs'

#: A build argument whose name ends in this is not one to hand back to a rebuild.
HIDDEN_KWARG_SUFFIX = '_hidden'


def as_pynode(node):
    """
    Whatever a caller has handed over, as the Maya node underneath it.

    A ``FRAGNode`` keeps its node on ``pynode`` and a ``Flag`` keeps its on ``node``; both turn up
    wherever a node is wanted, and a name does too.

    :param node: A ``FRAGNode``, a ``Flag``, a ``PyNode`` or a name.
    :return: The node.
    :rtype: pm.PyNode
    """

    if isinstance(node, pm.PyNode):
        return node
    for wrapper_attribute in ('pynode', 'node'):
        wrapped = getattr(node, wrapper_attribute, None)
        if isinstance(wrapped, pm.PyNode):
            return wrapped
    return pm.PyNode(node)


def is_frag_node(node):
    """
    Whether something is one of the rig's metadata nodes.

    :param node: A ``FRAGNode``, a ``PyNode`` or a name. Anything that is not in the scene answers
        False rather than raising, which is what asking a question should do.
    :return: Whether it is.
    :rtype: bool
    """

    if isinstance(node, FRAGNode):
        return True
    if node is None:
        return False

    if not isinstance(node, pm.PyNode):
        # pm.objExists(None) raises rather than answering, which is why None is seen to above.
        if not pm.objExists(node):
            logger.debug('There is no %s in the scene, so it is not a FRAG node.', node)
            return False
        node = pm.PyNode(node)

    if not isinstance(node, pm.nt.Network):
        return False
    return (attr_utils.has_attribute(node, FRAG_TYPE_ATTR) or
            attr_utils.has_attribute(node, LEGACY_FRAG_TYPE_ATTR))


def wrap_frag_node(node):
    """
    A node as its own FRAGNode subclass, or None with a line in the log saying why not.

    A network node can say it is ours and still be one this pipeline cannot do anything with: it may
    carry only the legacy type attribute, or name a class belonging to a project whose packages are
    not loaded. That is a thing to report and step over rather than to raise on, because it only
    takes one of them in a scene to stop a walk over all of them.

    :param node: The node to wrap.
    :return: The wrapped node, or None.
    :rtype: FRAGNode or None
    """

    try:
        return FRAGNode(node)
    except TypeError as error:
        logger.warning('%s looks like a FRAG node but cannot be wrapped as one: %s', node, error)
        return None


def get_frag_parent(node):
    """
    The metadata node above another one.

    :param node: A ``FRAGNode``, a ``PyNode`` or a name. Anything carrying a ``fragParent`` will do;
        it does not have to be a metadata node itself.
    :return: The parent, wrapped, or None when there is nothing above it.
    :rtype: FRAGNode or None
    """

    node = as_pynode(node)
    if not attr_utils.has_attribute(node, FRAG_PARENT_ATTR):
        return None

    parents = node.attr(FRAG_PARENT_ATTR).listConnections()
    if not parents:
        return None
    return wrap_frag_node(parents[0])


def _find_external_frag_node_class(frag_node_type):
    """
    Look for a FRAGNode class in the packages a project registered at startup.

    Importing one of those packages is what registers the classes in it, so this both finds the
    class and is the reason it becomes findable.

    :param str frag_node_type: The class name off a node's ``fragType``.
    :return: The class, or None when no registered package has it.
    :rtype: type or None
    """

    for node_package_path in ma_consts.FRAG_NODE_PACKAGE_PATHS:
        # This package's own classes are registered by importing it, so if the class lived here it
        # would have been found already.
        if __package__ == node_package_path:
            continue

        try:
            package = importlib.import_module(node_package_path)
        except ImportError:
            logger.warning('%s is registered as a FRAG node package but cannot be imported.',
                           node_package_path)
            continue

        frag_class = getattr(package, frag_node_type, None)
        if isinstance(frag_class, type) and issubclass(frag_class, FRAGNode):
            return frag_class

    return None


class FRAGNodeRegister(type):
    """
    What makes a ``fragType`` string into the class that goes with it.

    Every subclass of :class:`FRAGNode` is filed here as it is created, under its own name, which is
    what :meth:`FRAGNode.__new__` looks a node's ``fragType`` up in. Class names have to be unique
    across every package a project loads, because the name is all a node carries.
    """

    __frag_node_types__ = {}

    def __init__(cls, *args, **kwargs):
        """
        File the class being created.

        :param tuple args: What ``type()`` was called with - name, bases, namespace.
        :param dict kwargs: The rest of what ``type()`` was called with.
        :raises LookupError: When a different module has already filed a class of this name.
        """

        super(FRAGNodeRegister, cls).__init__(*args, **kwargs)

        existing_class = cls.__frag_node_types__.get(cls.__name__)
        if existing_class is not None and existing_class is not cls:
            new_path = '{0}.{1}'.format(cls.__module__, cls.__name__)
            existing_path = '{0}.{1}'.format(existing_class.__module__, existing_class.__name__)
            if new_path != existing_path:
                raise LookupError(
                    'The FRAG node {0} has the same class name as {1}, and the name is all a node '
                    'in a scene carries.'.format(new_path, existing_path))
            # The same class name from the same module: the module has been imported again, which is
            # what frag/__init__.py does on purpose so that edited code is picked up. The class just
            # built is the one to hand back from now on - keeping the old one is what left every
            # reload answering with classes from before it.
            logger.debug('%s was registered again from %s; the newer class is the one in use.',
                         cls.__name__, cls.__module__)

        cls.__frag_node_types__[cls.__name__] = cls


class FRAGNode(metaclass=FRAGNodeRegister):
    """
    One ``network`` node in a rig's metadata graph.

    ``FRAGNode(node)`` on a node built by any subclass hands back an instance of that subclass, so a
    caller that has found a node in a scene does not have to know what kind it is. The node itself
    is on ``pynode``.
    """

    VERSION = 1

    def __new__(cls, node=None):
        """
        Make an instance of whichever subclass the node says it is.

        :param node: The node to wrap, as a ``FRAGNode``, a ``PyNode`` or a name. None makes a bare
            instance of ``cls``, which is what subclass constructors go through.
        :return: An instance of the registered subclass, not yet initialised.
        :rtype: FRAGNode
        :raises TypeError: When the node is not a network node, carries no ``fragType``, or names a
            class no loaded package has.
        """

        if not node:
            return super(FRAGNode, cls).__new__(cls)

        node = as_pynode(node)
        if not isinstance(node, pm.nt.Network):
            raise TypeError('{0} is a {1} rather than a network node, so it cannot be a FRAG '
                            'node.'.format(node, node.nodeType()))
        if not attr_utils.has_attribute(node, FRAG_TYPE_ATTR):
            legacy = attr_utils.has_attribute(node, LEGACY_FRAG_TYPE_ATTR)
            raise TypeError(
                '{0} has no {1} attribute naming the class that goes with it, so there is nothing '
                'to wrap it as.{2}'.format(
                    node, FRAG_TYPE_ATTR,
                    ' It carries the older {0} instead.'.format(LEGACY_FRAG_TYPE_ATTR)
                    if legacy else ''))

        class_string = attr_utils.get_attribute(node, FRAG_TYPE_ATTR, attr_type='string')
        frag_class = (cls.__frag_node_types__.get(class_string) or
                      _find_external_frag_node_class(class_string))
        if frag_class is None:
            raise TypeError('{0} says it is a {1}, and no package this pipeline has loaded has a '
                            'FRAG node class by that name.'.format(node, class_string))
        return frag_class.__new__(frag_class)

    def __init__(self, node):
        """
        :param node: The node to wrap, as a ``FRAGNode``, a ``PyNode`` or a name.
        """

        self.pynode = as_pynode(node)

    def __eq__(self, other):
        """
        Two of these are the same when they wrap the same node.

        Every walk over the graph builds new wrappers, so without this a node found twice came back
        as two things that were not equal to each other - which is what made ``list(set(rigs))`` in
        ``frag_rig.get_frag_rigs`` a no-op, and ``x not in found`` always true.

        :param other: What to compare against.
        :return: Whether it wraps the same node. ``NotImplemented`` for anything that is not one of
            these, so Python falls back to its own answer.
        :rtype: bool
        """

        if not isinstance(other, FRAGNode):
            return NotImplemented
        return self.pynode == other.pynode

    def __ne__(self, other):
        """
        :param other: What to compare against.
        :return: Whether it wraps a different node.
        :rtype: bool
        """

        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        """
        :return: The wrapped node's hash, so a set of these holds one entry per node.
        :rtype: int
        """

        return hash(self.pynode)

    def __repr__(self):
        """
        :return: The class and the node it wraps, for a log line or a failing check.
        :rtype: str
        """

        return '{0}({1})'.format(type(self).__name__, self.pynode)

    @staticmethod
    def create(frag_parent, frag_type, version):
        """
        Build a new metadata node.

        :param FRAGNode frag_parent: What to hang it under, or None for a node at the top.
        :param str frag_type: The name of the class that goes with it, which has to be a registered
            FRAGNode class - it is all the node will carry to say what it is.
        :param float version: The version of that class the node is being built at.
        :return: The new node, wrapped as its own class.
        :rtype: FRAGNode
        :raises TypeError: When ``frag_type`` is not a registered class.
        """

        # Before the node exists: writing the attributes and only then finding out that nothing can
        # wrap it left the network node behind in the scene.
        if (frag_type not in FRAGNodeRegister.__frag_node_types__ and
                _find_external_frag_node_class(frag_type) is None):
            raise TypeError('There is no FRAG node class called {0}, so a node claiming to be one '
                            'could not be read back.'.format(frag_type))

        if frag_parent:
            frag_parent = FRAGNode(frag_parent)

        node = pm.createNode('network', n=str(frag_type))
        node.addAttr(VERSION_ATTR, at='double')
        node.attr(VERSION_ATTR).set(version)
        node.addAttr(FRAG_TYPE_ATTR, dt='string')
        node.attr(FRAG_TYPE_ATTR).set(frag_type)
        node.addAttr(FRAG_CHILDREN_ATTR, at='message')
        node.addAttr(FRAG_PARENT_ATTR, at='message')

        frag_node = FRAGNode(node)
        if frag_parent:
            frag_node.set_frag_parent(frag_parent)
        return frag_node

    # ----------------------------------------------------------------------------------- #
    # wiring things to the node
    # ----------------------------------------------------------------------------------- #
    def connect_node(self, node, attr, parent_attr=None):
        """
        Wire one node to this one.

        :param node: What to wire, as a ``FRAGNode``, a ``Flag``, a ``PyNode`` or a name.
        :param str attr: The attribute on this node that holds it.
        :param str parent_attr: A message attribute to put on the *other* node and connect from,
            rather than connecting from the node itself. That is what lets a control say which
            component it belongs to as well as the other way round.
        """

        node_to_connect = as_pynode(node)
        if parent_attr:
            if not node_to_connect.hasAttr(parent_attr):
                node_to_connect.addAttr(parent_attr, at='message')
            node_to_connect = node_to_connect.attr(parent_attr)
        attr_utils.set_attribute(self.pynode, {attr: node_to_connect})

    def connect_nodes(self, connect_nodes, attr, parent_attr=None, merge_values=False):
        """
        Wire several nodes to this one.

        :param connect_nodes: What to wire, as a list or one thing on its own.
        :param str attr: The attribute on this node that holds them.
        :param str parent_attr: A message attribute to put on each of the other nodes and connect
            from. Note that one such attribute holds one connection, so the last node wired through
            it is the one that answers.
        :param bool merge_values: Keep whatever is already wired to ``attr`` as well.
        """

        if not isinstance(connect_nodes, (list, tuple)):
            connect_nodes = [connect_nodes]
        nodes_to_connect = [as_pynode(node) for node in connect_nodes]

        if parent_attr:
            attributes = []
            for node in nodes_to_connect:
                if not node.hasAttr(parent_attr):
                    node.addAttr(parent_attr, at='message')
                attributes.append(node.attr(parent_attr))
            nodes_to_connect = attributes

        attr_utils.set_attribute(self.pynode, {attr: nodes_to_connect},
                                 merge_values=merge_values)

    # ----------------------------------------------------------------------------------- #
    # the graph
    # ----------------------------------------------------------------------------------- #
    def get_frag_parent(self):
        """
        :return: The node above this one, or None when it is at the top.
        :rtype: FRAGNode or None
        """

        return get_frag_parent(self.pynode)

    def set_frag_parent(self, frag_parent):
        """
        Hang this node under another one.

        :param frag_parent: The node to hang it under, as a ``FRAGNode``, a ``PyNode`` or a name.
        :raises TypeError: When it is not a metadata node, or is one this pipeline cannot wrap - the
            version before took ``is_frag_node``'s word for it and then reached for ``.pynode``.
        """

        if not is_frag_node(frag_parent):
            raise TypeError('{0} is not a FRAG node, so nothing can be hung under '
                            'it.'.format(frag_parent))
        if not isinstance(frag_parent, FRAGNode):
            frag_parent = FRAGNode(frag_parent)

        frag_parent.pynode.attr(FRAG_CHILDREN_ATTR) >> self.pynode.attr(FRAG_PARENT_ATTR)

    def get_frag_children(self, of_type=None, side=None, region=None):
        """
        The nodes hung under this one.

        :param of_type: A FRAGNode class to keep to.
        :param str side: A side to keep to.
        :param str region: A region to keep to.
        :return: The children that match, in the order they are wired.
        :rtype: list(FRAGNode)
        """

        if not self.has_attribute(FRAG_CHILDREN_ATTR):
            return []

        children = []
        for child_node in self.pynode.attr(FRAG_CHILDREN_ATTR).listConnections():
            wrapped_node = wrap_frag_node(child_node)
            if wrapped_node is None:
                continue
            if side and wrapped_node.side != side:
                continue
            if region and wrapped_node.region != region:
                continue
            if of_type and not isinstance(wrapped_node, of_type):
                continue
            children.append(wrapped_node)
        return children

    def get_frag_child(self, of_type=None):
        """
        :param of_type: A FRAGNode class to keep to.
        :return: The first child that matches, or None.
        :rtype: FRAGNode or None
        """

        return lists.get_first_in_list(self.get_frag_children(of_type=of_type))

    @staticmethod
    def get_frag_root(input_node):
        """
        The node at the top of one asset's rig, from anywhere inside it.

        This reads the node it is given and not ``self``; it is on the class because that is where
        every caller looks for it.

        :param input_node: Where to start, as a ``FRAGNode`` or a node.
        :return: The root, or None when the node is not in a rig.
        :rtype: FRAGNode or None
        """

        if not is_frag_node(input_node):
            return None
        if not isinstance(input_node, FRAGNode):
            input_node = FRAGNode(input_node)

        while input_node is not None:
            if input_node.has_attribute(IS_FRAG_ROOT_ATTR):
                return input_node
            input_node = input_node.get_frag_parent()
        return None

    @staticmethod
    def get_asset_id(input_node):
        """
        The asset the rig a node belongs to was built for.

        Reads the node it is given rather than ``self``, like :meth:`get_frag_root`.

        :param input_node: Where to start, as a ``FRAGNode`` or a node.
        :return: The asset id, or None when the node is not in a rig.
        :rtype: str or None
        """

        root = FRAGNode.get_frag_root(input_node)
        if not root:
            logger.warning('%s is not under a FRAG root, so there is no asset id to read.',
                           input_node)
            return None
        return root.asset_id

    # ----------------------------------------------------------------------------------- #
    # what the node says about itself
    # ----------------------------------------------------------------------------------- #
    def get_type(self):
        """
        :return: The name of the class that goes with this node, or None.
        :rtype: str or None
        """

        if not self.has_attribute(FRAG_TYPE_ATTR):
            return None
        return attr_utils.get_attribute(self.pynode, FRAG_TYPE_ATTR, attr_type='string')

    def get_pynode(self):
        """
        :return: The node itself, which is also on ``pynode``.
        :rtype: pm.nt.Network
        """

        return self.pynode

    def get_version(self):
        """
        :return: The version this node was built at.
        :rtype: float
        """

        return self.pynode.attr(VERSION_ATTR).get()

    def set_version(self, version):
        """
        :param float version: The version to record on the node.
        """

        self.pynode.attr(VERSION_ATTR).set(version)

    def get_flags(self):
        """
        :return: The controls this node owns. A bare FRAGNode owns none; the components override it.
        :rtype: list
        """

        return []

    @property
    def side(self):
        """
        :return: Which side of the body this node is for, or an empty string.
        :rtype: str
        """

        if self.pynode.hasAttr(SIDE_ATTR):
            return self.pynode.attr(SIDE_ATTR).get()
        return ''

    @side.setter
    def side(self, value):
        """
        :param str value: Which side of the body this node is for.
        """

        if not self.pynode.hasAttr(SIDE_ATTR):
            self.pynode.addAttr(SIDE_ATTR, dt='string')
        self.pynode.attr(SIDE_ATTR).set(value)

    @property
    def region(self):
        """
        :return: What part of the body this node is for, or an empty string.
        :rtype: str
        """

        if self.pynode.hasAttr(REGION_ATTR):
            return self.pynode.attr(REGION_ATTR).get()
        return ''

    @region.setter
    def region(self, value):
        """
        :param str value: What part of the body this node is for.
        """

        if not self.pynode.hasAttr(REGION_ATTR):
            self.pynode.addAttr(REGION_ATTR, dt='string')
        self.pynode.attr(REGION_ATTR).set(value)

    def has_attribute(self, attr_name):
        """
        :param str attr_name: The attribute to look for.
        :return: Whether the node has it.
        :rtype: bool
        """

        return attr_utils.has_attribute(self.pynode, attr_name)

    def get_attr(self, attr_name):
        """
        :param str attr_name: The attribute to read.
        :return: Its value.
        """

        return self.pynode.attr(attr_name).get()

    def get_build_kwargs(self):
        """
        The arguments this node was built with, as far as it recorded them.

        Three classes wanted this and two of them had their own copy of it - ``RigComponent`` and
        ``MultiConstraint``, which cannot inherit from each other - while ``SkeletalMesh`` wrote the
        attribute and had no reader at all. It is here because anything that records how it was
        built records it the same way.

        :return: ``{argument name: value}``, without the ones marked as not for a rebuild.
        :rtype: dict
        """

        if not self.pynode.hasAttr(BUILD_KWARGS_ATTR):
            return {}

        build_kwargs = {}
        for attribute in self.pynode.attr(BUILD_KWARGS_ATTR).children():
            attr_name = attribute.attrName()
            if attr_name.endswith(HIDDEN_KWARG_SUFFIX):
                continue
            build_kwargs[attr_name.replace('{0}_'.format(BUILD_KWARGS_ATTR), '')] = attribute.get()
        return build_kwargs

    def get_namespace(self):
        """
        :return: The namespace the node is in, with its trailing colon, or an empty string.
        :rtype: str
        """

        return self.pynode.namespace()

    def name(self):
        """
        :return: The node's name.
        :rtype: str
        """

        return str(self.pynode)

    # ----------------------------------------------------------------------------------- #
    # bringing an old node up to date
    # ----------------------------------------------------------------------------------- #
    def get_attr_with_legacy_name(self, attr_name, legacy_name):
        """
        Read an attribute a node built by an older version of this class holds under another name.

        :param str attr_name: What it is called now.
        :param str legacy_name: What it was called then.
        :return: The value, or None when the node has neither.
        """

        for name in (attr_name, legacy_name):
            if self.pynode.hasAttr(name):
                return self.pynode.attr(name).get()
        return None

    def rename_legacy_attrs(self, rename_map):
        """
        Rename the attributes an older version of this class stored under other names, keeping
        whatever is connected to them. This is what an update method is usually made of.

        :param dict rename_map: ``{what it was called: what it is called now}``.
        """

        for legacy_name, attr_name in rename_map.items():
            if self.pynode.hasAttr(legacy_name) and not self.pynode.hasAttr(attr_name):
                pm.renameAttr(self.pynode.attr(legacy_name), attr_name)

    def update(self):
        """
        Run the update steps in turn until the node is at its class's version.

        :raises AttributeError: When a step between the node's version and the class's is missing.
        :raises RuntimeError: When a step does not record the version it brings the node up to,
            which would otherwise be an endless loop.
        """

        stored_version = self.get_version()
        # Whole numbers: the version is on a double attribute, so a node at version 1 reads back as
        # 1.0 - and the method name built from that was `_update_version_1.0_to_version_2.0`, which
        # no component has ever had. This is why no rig was ever updated.
        current_version = int(stored_version)
        latest_version = int(self.VERSION)
        if stored_version != current_version or self.VERSION != latest_version:
            logger.warning('%s is at version %s and %s is on version %s. FRAG node versions are '
                           'whole numbers; the fractions are being ignored.',
                           self.pynode, stored_version, type(self).__name__, self.VERSION)

        if current_version > latest_version:
            logger.warning('%s was built at version %s by a newer pipeline than this one, which '
                           'knows %s up to version %s. It is left as it is.',
                           self.pynode, current_version, type(self).__name__, latest_version)
            return

        while current_version < latest_version:
            method_name = '_update_version_{0}_to_version_{1}'.format(current_version,
                                                                      current_version + 1)
            update_method = getattr(self, method_name, None)
            if update_method is None:
                raise AttributeError(
                    '{0} is at version {1} and {2} is on version {3}, but {2} has no {4} to bring '
                    'it up.'.format(self.pynode, current_version, type(self).__name__,
                                    latest_version, method_name))

            update_method()
            later_version = int(self.get_version())
            if later_version <= current_version:
                raise RuntimeError(
                    '{0} left {1} at version {2}. An update method has to record the version it '
                    'brings the node up to, or this would never end.'.format(
                        method_name, self.pynode, later_version))
            current_version = later_version


def get_frag_node_descendants(node, of_type=FRAGNode):
    """
    Every metadata node under one, however far down.

    :param node: Where to start, as a ``FRAGNode`` or a node.
    :param of_type: A FRAGNode class to keep to.
    :return: The matching children, and then each child's matching descendants.
    :rtype: list(FRAGNode)
    """

    if not is_frag_node(node):
        return []
    if not isinstance(node, FRAGNode):
        node = FRAGNode(node)

    children = node.get_frag_children()
    descendants = [child for child in children if isinstance(child, of_type)]
    for child in children:
        descendants += get_frag_node_descendants(child, of_type=of_type)
    return descendants


def get_all_frag_nodes(of_type=FRAGNode):
    """
    Every metadata node in the scene.

    :param of_type: A FRAGNode class to keep to.
    :return: The nodes that match. One this pipeline cannot wrap is reported and left out, rather
        than stopping the walk - which is what a single legacy node in a scene used to do.
    :rtype: list(FRAGNode)
    """

    frag_nodes = []
    for node in (cmds.ls(type='network') or []):
        if not is_frag_node(node):
            continue
        wrapped_node = wrap_frag_node(node)
        if wrapped_node is not None and isinstance(wrapped_node, of_type):
            frag_nodes.append(wrapped_node)
    return frag_nodes


def update_all_frag_nodes():
    """
    Bring every metadata node in the scene up to its class's version.

    :return: The nodes that could not be brought up to date, with the reason. One node missing an
        update step used to stop every node after it.
    :rtype: list(tuple)
    """

    failures = []
    for frag_node in get_all_frag_nodes():
        try:
            frag_node.update()
        except (AttributeError, RuntimeError) as error:
            logger.warning('%s could not be brought up to date: %s', frag_node.pynode, error)
            failures.append((frag_node, error))
    return failures
