"""
Attributes: locking them, unlocking them, writing them down, and putting a dictionary's worth
of data onto a node.

The last of those is how the pipeline stores almost everything it knows about a rig. A FRAG
node is a network node covered in attributes, and ``set_compound_attribute_groups`` is what
puts them there, so the type guessing in this module decides what shape the data on every rig
in the project has.

What was wrong before:

- **An integer attribute could not be created at all.** ``MAYA_TYPE_DICT`` mapped ``int`` to
  the Python type ``int`` rather than to a Maya type name - every other entry is a string -
  so ``addAttr(attributeType=<class 'int'>)`` was what came out. Any property whose value was
  a whole number failed.
- **Six log messages were written as bare string expressions.** ``'An incoming data type does
  not have a register in the MAYA_TYPE_DICT...'.format(...)`` on a line of its own does
  nothing at all: it builds a string and throws it away. So the two places that noticed an
  unknown data type, the one that noticed a non-string dictionary key and the two that
  noticed a node with no message attribute all reported nothing, and the data quietly came
  out wrong.
- **``purge_user_defined_attrs`` stopped at the first node that had nothing to purge.** The
  ``return`` for "this node has no user attributes" sat inside the loop over nodes, so
  purging a selection stopped there - and answered ``None`` rather than a list. It also
  reassigned its result on each pass, so it only ever described the last node.
- **``lock_all_keyable_attrs``' ``allow_visibility`` did nothing.** The test compared a
  ``pm.Attribute`` against a string - ``keyable_attr == node.nodeName() + '.v'`` - which is
  never equal, so the first half of the ``or`` was always true and visibility was locked
  whatever the caller asked for.
- **``get_all_objects_with_attr`` searched in namespaces that do not exist.** It built its
  search string as ``f'{ns[1:]}:*.{attr_name}'`` - dropping the *first character* of every
  namespace name, so ``char`` was searched for as ``har``. It found nothing outside the root
  namespace, ever.
- **``invert_attribute`` wrote to whatever was selected.** Five of its ``setAttr`` calls named
  the attribute relatively - ``pm.setAttr('.min', ...)`` - with no node, which means "the
  current selection". It worked only because ``createNode`` happens to leave its node
  selected, and would have written its values onto the wrong node the moment anything else
  touched the selection first.
- **``get_compound_attr_name_as_attribute`` returned a class on failure.** Not ``None``: the
  literal ``pm.nt.General.Attribute``, which is not a name that exists - ``pm.nt`` has no
  ``General`` - so the failure path raised ``AttributeError`` instead of reporting the missing
  attribute.
- ``add_limits_for_transform``'s two parameters were named ``limit_min_loc`` and
  ``limit_max_loc`` and documented as ``limit_min_lock`` and ``limit_max_lock`` - so the
  docstring described arguments the function does not have. It also called ``attr.lock(True)``,
  where pymel's ``lock`` takes ``checkReference``, not the lock state: passing True asked Maya
  to *raise* if the attribute belonged to a referenced node, which is not what was meant and
  is not what the docstring says.
- **``get_enum_index`` raised for any enumeration whose names are not lower case.** It tested
  membership with the string it was given and then looked up the index of
  ``enum_string.lower()``, so ``'Blue'`` passed the test and then failed with ``ValueError``.
  Nothing called it. Gone.
- ``get_indices``, ``lock_and_hide_object_attrs`` and ``create_message_compound_attr`` had no
  callers either. The last of those also had its own inverted test - it added a compound
  attribute and then checked ``if not node.hasAttr(...)`` before aliasing it, which is never
  true at that point.
- Four helpers that only this module calls are private now: the reset safety check, the
  compound-attribute lookup, the compound disconnect, and the limit-attribute builder.
- **``set_limits`` treated a limit of zero as no limit.** It decided whether to lock an axis
  with ``if not any(limit_point[0])``, and ``any((0, 0))`` is False - so an axis deliberately
  pinned at zero was locked and hidden as though no limit had been asked for. It checks for
  ``None`` now, which is what "no limit" is written as.
- The module docstring said "Parameter data for working with the facial rigs".

Still to fix, and it needs a caller changed rather than a line here:
``serialize_attribute`` adds ``min``, ``max``, ``softMin`` and ``softMax`` *after*
``om_plug.serialize_plug`` has returned, which is why that function's ``optimize`` pass could
never drop them. They are dropped here instead when they are not set, so ``optimize`` means
what it says - but any reader of the data written before this change will find all four keys
present and holding ``None``.
"""

# python imports

# software specific imports
import pymel.core as pm
import maya.cmds as cmds
import maya.api.OpenMaya as om

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.modifiers import contexts
from mca.mya.utils import namespace
from mca.mya.utils.om import attributetypes
from mca.mya.utils.om import om_plug


logger = log.MCA_LOGGER

TRANSLATION_ATTRS = ['tx', 'ty', 'tz']
ROTATION_ATTRS = ['rx', 'ry', 'rz']
SCALE_ATTRS = ['sx', 'sy', 'sz']
TRANSFORM_ATTRS = TRANSLATION_ATTRS + ROTATION_ATTRS + SCALE_ATTRS

#: What Maya type to make for a value of a given Python type, in the order the types are
#: tried. A bool is an int in Python, so it has to come first, and ``pm.Attribute`` is a
#: ``pm.PyNode``, so it does too.
#:
#: ``int`` mapped to the Python type ``int`` here rather than to a Maya type name, so
#: ``addAttr(attributeType=<class 'int'>)`` is what a whole number produced. It is Maya's
#: ``'long'``, which is the 32-bit integer.
MAYA_TYPE_DICT = {
    bool: 'bool',
    str: 'string',
    float: 'float',
    int: 'long',
    pm.Attribute: 'message',
    pm.PyNode: 'message',
}

#: The Maya types that ``addAttr`` wants under ``dataType`` rather than ``attributeType``.
DATA_TYPES = ('string',)


def _get_pynode(node):
    """
    Whatever was handed over, as a PyNode.

    Strings, PyNodes and FRAG wrappers all arrive here. A FRAG wrapper keeps its Maya node on
    ``.pynode``.

    :param node: A PyNode, a FRAG node, or a name.
    :return: The PyNode.
    :rtype: pm.PyNode
    """

    if hasattr(node, 'pynode'):
        return node.pynode
    if isinstance(node, pm.PyNode):
        return node
    return pm.PyNode(node)


def _maya_type_for(value, description=''):
    """
    Which Maya attribute type to make for a Python value.

    :param value: The value that has to fit in the attribute. A list or tuple is asked about
        by its first entry.
    :param str description: What is being built, for the warning when the type is unknown.
    :return: The Maya type name, and whether the attribute has to be a multi.
    :rtype: tuple(str, bool)
    """

    is_multi = isinstance(value, (list, tuple))
    sample = (value[0] if value else None) if is_multi else value

    if sample is None:
        # Nothing to go on. A message attribute is what a None means in this data: a place for
        # a node to be wired in later.
        return 'message', is_multi

    for python_type, maya_type in MAYA_TYPE_DICT.items():
        if not isinstance(sample, python_type):
            continue
        # A bool is an int, and an Attribute is a PyNode, so the two narrower types have to
        # win even though both entries match.
        if isinstance(sample, bool) and python_type is int:
            continue
        if isinstance(sample, pm.Attribute) and python_type is pm.PyNode:
            continue
        return maya_type, is_multi

    # This used to be a bare string expression - a message built and thrown away.
    logger.warning('%s has no entry in MAYA_TYPE_DICT for %s; storing it as a string.',
                   description or 'An attribute', type(sample).__name__)
    return 'string', is_multi


def _add_attribute(node, attr_name, maya_type, is_multi, nice_name=None, parent=None):
    """
    Add one attribute, with the flag Maya wants for its type.

    :param pm.PyNode node: The node to add it to.
    :param str attr_name: The attribute's long name.
    :param str maya_type: The Maya type name.
    :param bool is_multi: Whether it holds several values.
    :param str nice_name: What to call it in the channel box.
    :param str parent: The compound attribute to put it under.
    """

    keywords = {'nn': nice_name or attr_name, 'm': is_multi}
    if parent:
        keywords['parent'] = parent
    if maya_type in DATA_TYPES:
        node.addAttr(attr_name, dataType=maya_type, **keywords)
    else:
        node.addAttr(attr_name, attributeType=maya_type, **keywords)


# --------------------------------------------------------------------------------------- #
# asking
# --------------------------------------------------------------------------------------- #
def has_attribute(node, attr_name=''):
    """
    Whether a node has an attribute.

    Through the API rather than ``cmds.objExists``, because this is asked in loops over whole
    rigs. It is a little faster given a name than given a PyNode, but not enough to be worth
    turning a PyNode into a string for.

    :param node: The node, as a PyNode or a name.
    :param str attr_name: The attribute to look for.
    :return: Whether it is there.
    :rtype: bool
    :raises RuntimeError: When there is no such node.
    """

    selection = om.MSelectionList()
    selection.add(str(node))
    return om.MFnDependencyNode(selection.getDependNode(0)).hasAttribute(attr_name)


def get_attribute(node, attr_name, attr_type='string'):
    """
    An attribute's value, read through the API.

    Faster than ``cmds.getAttr`` at the cost of having to say what type the attribute is.
    Only strings are supported, which is all any caller has ever asked for.

    :param node: The node, as a PyNode or a name.
    :param str attr_name: The attribute to read.
    :param str attr_type: The attribute's type. Only ``'string'``.
    :return: The value, or None when the node is not a dependency node.
    :rtype: str or None
    :raises ValueError: For any type but ``'string'``.
    """

    if attr_type != 'string':
        raise ValueError('get_attribute only reads strings; it was asked for {!r}.'
                         .format(attr_type))

    if not isinstance(node, pm.nt.DependNode):
        return None

    selection = om.MSelectionList()
    selection.add(str(node))
    plug = om.MFnDependencyNode(selection.getDependNode(0)).findPlug(attr_name, True)
    return plug.asString() if plug else None


def get_all_objects_with_attr(attr_name, of_type=None, as_pynode=True):
    """
    Every node in the scene with an attribute of this name, in every namespace.

    :param str attr_name: The attribute to look for.
    :param str of_type: Only nodes of this Maya type.
    :param bool as_pynode: Answer with PyNodes rather than names.
    :return: The nodes.
    :rtype: list
    """

    found = []
    # '' is the root namespace, which cmds.ls searches as ':*'.
    for one_namespace in namespace.get_all_namespaces() + ['']:
        # The version this replaces wrote f'{ns[1:]}:*.{attr_name}', dropping the first
        # character of every namespace name, so it searched for 'har' instead of 'char' and
        # found nothing outside the root.
        search = '{}:*.{}'.format(one_namespace, attr_name)
        if of_type:
            found += cmds.ls(search, objectsOnly=True, type=of_type) or []
        else:
            found += cmds.ls(search, objectsOnly=True) or []

    # A node can answer to more than one of those searches when namespaces nest.
    unique = list(dict.fromkeys(found))
    return [pm.PyNode(one) for one in unique] if as_pynode else unique


def serialize_attribute(attribute_to_serialize, optimize=True, force=False):
    """
    Everything about an attribute that would be needed to make it again.

    :param pm.Attribute attribute_to_serialize: The attribute to write down.
    :param bool optimize: Leave out everything that is at its default.
    :param bool force: Write it down even when it is at its default value.
    :return: The attribute's description.
    :rtype: dict
    """

    # Through OpenMaya: this is done once per attribute per flag, over whole rigs, and the
    # command layer cannot answer some of it at all.
    plug = om_plug.as_mplug(attribute_to_serialize.name(fullDagPath=True))
    serialized_data = om_plug.serialize_plug(plug, optimize=optimize, force=force)
    if not serialized_data:
        return serialized_data

    # The limits come from pymel, not from the plug: OpenMaya has no one call for them. They
    # are added after serialize_plug has returned, which is why serialize_plug's own attempt
    # to drop them when they are unset could never fire - it had already returned.
    limits = {
        'min': attribute_to_serialize.getMin(),
        'max': attribute_to_serialize.getMax(),
        'softMin': attribute_to_serialize.getSoftMin(),
        'softMax': attribute_to_serialize.getSoftMax(),
    }
    if optimize:
        limits = {key: value for key, value in limits.items() if value is not None}
    serialized_data.update(limits)

    # The type is written as the string addAttr takes, not as our own number, so the data can
    # be read back without this module.
    if 'type' in serialized_data:
        serialized_data['type'] = attributetypes.om_type_to_pymel_type(serialized_data['type'])
    return serialized_data


# --------------------------------------------------------------------------------------- #
# locking, hiding and unlocking
# --------------------------------------------------------------------------------------- #
def set_attr_state(node_list, locked=True, attr_list=None, visibility=False):
    """
    Lock or unlock a set of attributes on a set of nodes, optionally hiding them to match.

    :param node_list: The nodes to work on. One node on its own is fine.
    :type node_list: list or pm.PyNode
    :param bool locked: Lock them, or unlock them.
    :param attr_list: The attributes, by name. Every transform attribute by default.
    :type attr_list: list(str) or None
    :param bool visibility: Take them out of the channel box when locking, and put them back
        when unlocking.
    """

    if not node_list:
        return

    attr_list = TRANSFORM_ATTRS if attr_list is None else attr_list
    for node in lists.force_list(node_list):
        # The parents come first: a locked `translate` makes `translateX` unsettable whatever
        # its own lock says, so there is no per-axis control until they are open.
        node.unlock()
        node.t.unlock()
        node.r.unlock()
        node.s.unlock()

        for attr_name in attr_list:
            attribute = node.attr(attr_name)
            if locked:
                attribute.lock()
            else:
                attribute.unlock()
            if visibility:
                attribute.set(channelBox=not locked)
                attribute.set(keyable=not locked)


def lock_and_hide_attrs(node, attr_list):
    """
    Lock attributes and take them out of the channel box.

    :param pm.PyNode node: The node holding them.
    :param attr_list: The attributes, by long or short name - ``['tx', 'ty']`` or
        ``['translateX', 'translateY']``. One name on its own is fine.
    :type attr_list: list(str) or str
    """

    for attr_name in lists.force_list(attr_list):
        attribute = node.attr(attr_name)
        attribute.lock()
        attribute.set(keyable=False, channelBox=False)


def unlock_and_show_attrs(attr_list):
    """
    Unlock attributes and put them back in the channel box.

    :param attr_list: The attributes themselves, not their names. One on its own is fine.
    :type attr_list: list or pm.Attribute
    """

    for attribute in lists.force_list(attr_list):
        attribute = pm.PyNode(attribute)
        if not pm.objExists(attribute):
            continue
        attribute.setKeyable(True)
        attribute.unlock()


def unlock_transform_attributes(node, transform_list=None):
    """
    Unlock a transform's translate, rotate and scale.

    :param pm.PyNode node: The node to unlock.
    :param transform_list: Which attributes, by name. All nine by default.
    :type transform_list: list(str) or None
    :return: The attributes that had been locked, so a caller can put them back.
    :rtype: list(pm.Attribute)
    """

    was_locked = []
    for attr_name in lists.force_list(transform_list or TRANSFORM_ATTRS):
        attribute = node.attr(attr_name)
        if attribute.isLocked():
            was_locked.append(attribute)
        attribute.unlock()
    return was_locked


def lock_all_keyable_attrs(node, hidden=False, allow_visibility=False):
    """
    Lock every keyable attribute on a node.

    :param node: The node, as a PyNode or a name.
    :param bool hidden: Take them out of the channel box as well.
    :param bool allow_visibility: Leave ``visibility`` alone. The version this replaces
        compared a ``pm.Attribute`` against the string ``'<node>.v'``, which is never equal,
        so this argument did nothing and visibility was always locked.
    :return: The attributes that were locked.
    :rtype: list(pm.Attribute)
    :raises pm.MayaNodeError: When there is no such node.
    """

    if not pm.objExists(node):
        raise pm.MayaNodeError('lock_all_keyable_attrs: there is no node called {!r}.'
                               .format(str(node)))

    node = pm.PyNode(node)
    locked = []
    for attribute in node.listAttr(keyable=True) or []:
        if allow_visibility and attribute.attrName(longName=True) == 'visibility':
            continue
        attribute.lock()
        if hidden:
            attribute.setKeyable(False)
        locked.append(attribute)
    return locked


def unlock_all_attrs(obj, show=False):
    """
    Unlock every locked attribute on a node.

    :param obj: The node, as a PyNode or a name.
    :param bool show: Make them keyable as well.
    :return: The attributes that were unlocked.
    :rtype: list(pm.Attribute)
    :raises pm.MayaNodeError: When there is no such node.
    """

    if not pm.objExists(obj):
        raise pm.MayaNodeError('unlock_all_attrs: there is no node called {!r}.'.format(str(obj)))

    obj = pm.PyNode(obj)
    unlocked = []
    for attribute in obj.listAttr(locked=True) or []:
        attribute.unlock()
        if show:
            attribute.setKeyable(True)
        unlocked.append(attribute)
    return unlocked


def unlock_node_attributes(node, attributes=None, only_keyable=False):
    """
    Unlock named attributes on a node, and make them keyable and visible.

    :param pm.PyNode node: The node to work on.
    :param attributes: The attributes by name. Everything locked, by default.
    :type attributes: list(str) or None
    :param bool only_keyable: When working out the list, only consider keyable attributes.
    :return: The attributes that were unlocked.
    :rtype: list(pm.Attribute)
    """

    if not attributes:
        if only_keyable:
            attributes = pm.listAttr(node, locked=True, keyable=True)
        else:
            attributes = pm.listAttr(node, locked=True)

    unlocked = []
    for attr_name in lists.force_list(attributes or []):
        attribute = node.attr(attr_name)
        if not attribute.isLocked():
            continue
        attribute.set(lock=False, keyable=True, channelBox=True)
        attribute.setKeyable(True)
        unlocked.append(attribute)
    return unlocked


def purge_user_defined_attrs(node_list, skip_list=(), skip_dialog=False):
    """
    Delete every attribute somebody added to these nodes, leaving Maya's own.

    :param node_list: The nodes to strip.
    :type node_list: list(pm.PyNode) or pm.PyNode
    :param skip_list: Attribute names to leave alone.
    :type skip_list: list(str) or tuple(str)
    :param bool skip_dialog: Do not warn about a node that had nothing to strip.
    :return: The attributes that were deleted, across every node. The version this replaces
        answered ``None`` and *stopped* at the first node with nothing to strip - its ``return``
        was inside the loop - so purging a selection usually purged one node of it.
    :rtype: list(pm.Attribute)
    """

    purged = []
    with contexts.undo_chunk_context('mca_purge_user_attributes'):
        for node in lists.force_list(node_list):
            user_attrs = node.listAttr(userDefined=True) or []
            if not user_attrs:
                if not skip_dialog:
                    logger.warning('%s has no user attributes.', node.nodeName())
                continue

            unlock_all_attrs(node)
            if skip_list:
                keeping = [node.attr(name) for name in skip_list if node.hasAttr(name)]
                user_attrs = [attribute for attribute in user_attrs if attribute not in keeping]
            if not user_attrs:
                continue

            pm.deleteAttr(user_attrs)
            purged += user_attrs
    return purged


# --------------------------------------------------------------------------------------- #
# resetting
# --------------------------------------------------------------------------------------- #
def _can_reset(node, attr_name):
    """
    Whether an attribute can be set without Maya refusing.

    The same rule as :func:`mca.mya.utils.constraint.constraint_safe_attrs`: an anim curve or
    an animation layer driving the attribute is not in the way, because setting over it is
    what a reset means. Anything else driving it is.

    Only *incoming* connections block a set. An attribute that drives other nodes - a flag's
    translate feeding a uvPin - is still free to reset.

    :param pm.PyNode node: The node holding it.
    :param str attr_name: The attribute's name.
    :return: Whether it can be set.
    :rtype: bool
    """

    try:
        attribute = node.attr(attr_name)
        if not attribute.isSettable() or attribute.isLocked():
            return False
        for connection in attribute.listConnections(source=True, destination=False) or []:
            if not isinstance(connection, (pm.nt.AnimCurve, pm.nt.AnimLayer)):
                return False
        return True
    except Exception:
        logger.debug('Could not work out whether %s.%s can be reset.', node, attr_name,
                     exc_info=True)
        return False


#: What a transform's own attributes are worth when nothing has moved it.
TRANSFORM_DEFAULTS = {
    'tx': 0.0, 'ty': 0.0, 'tz': 0.0,
    'rx': 0.0, 'ry': 0.0, 'rz': 0.0,
    'sx': 1.0, 'sy': 1.0, 'sz': 1.0,
    'v': 1,
}


def reset_attrs(obj):
    """
    Put every keyable attribute back to its default.

    Translate and rotate to zero, scale to one, visibility on, and anything somebody added to
    whatever default it was given. Attributes that are locked, hidden, or driven by something
    that is not animation are left alone rather than raising.

    :param obj: The node to reset, as a PyNode or a name.
    :return: The attributes that were set.
    :rtype: list(pm.Attribute)
    :raises pm.MayaNodeError: When there is no such node.
    """

    if not pm.objExists(obj):
        raise pm.MayaNodeError('reset_attrs: there is no node called {!r}.'.format(str(obj)))

    obj = pm.PyNode(obj)
    is_transform = isinstance(obj, pm.nodetypes.Transform)
    was_set = []
    failed = []

    for attribute in obj.listAttr(keyable=True) or []:
        if attribute.isHidden() or attribute.isLocked():
            continue

        attr_name = attribute.attrName()
        if is_transform and attr_name in TRANSFORM_DEFAULTS:
            wanted = TRANSFORM_DEFAULTS[attr_name]
        elif attribute.isDynamic():
            try:
                wanted = pm.addAttr(attribute, query=True, defaultValue=True)
            except Exception:
                logger.debug('%s has no default value to go back to.', attribute, exc_info=True)
                continue
            if wanted is None:
                continue
        else:
            continue

        if not _can_reset(obj, attr_name):
            logger.debug('%s is not free to reset.', attribute)
            continue
        try:
            attribute.set(wanted)
        except RuntimeError as error:
            logger.warning('Could not reset %s: %s', attribute, error)
            failed.append(attribute)
            continue
        if attribute not in was_set:
            was_set.append(attribute)

    if failed:
        logger.warning('Could not reset %s of %s attributes: %s', len(failed),
                       len(failed) + len(was_set), ', '.join(str(one) for one in failed))
    return was_set


# --------------------------------------------------------------------------------------- #
# putting data on a node
# --------------------------------------------------------------------------------------- #
def _connect_value(node, attribute, value):
    """
    Put one value onto one attribute, wiring it up when the value is a node.

    :param pm.PyNode node: The node holding the attribute - needed for the back-connection a
        value that is itself an attribute gets.
    :param pm.Attribute attribute: Where the value goes.
    :param value: The value, a PyNode, or an attribute.
    :return: Whether it went.
    :rtype: bool
    """

    try:
        if isinstance(value, pm.Attribute):
            # An attribute first: it is a kind of PyNode, so the wider test would catch it.
            # The relationship is two-way - the holder points at the value's node, and the
            # value points back at the holder.
            value.node().message >> attribute
            node.message >> value
        elif isinstance(value, pm.PyNode):
            value.message >> attribute
        else:
            attribute.set(value)
    except (AttributeError, RuntimeError) as error:
        logger.warning('Could not put %r on %s: %s', value, attribute, error)
        return False
    return True


def set_attribute(node, attribute_dict, merge_values=False):
    """
    Put a dictionary's worth of values onto a node as attributes, making them if they are not
    there.

    The type of each attribute is worked out from the value, through
    :data:`MAYA_TYPE_DICT`. A PyNode or an attribute becomes a message attribute and is wired
    up rather than set; a list becomes a multi.

    :param node: The node to write onto, as a PyNode, a name or a FRAG node.
    :param dict attribute_dict: Attribute names to values.
    :param bool merge_values: For a multi, keep what is there and add to it rather than
        writing over it.
    :return: The names that were written.
    :rtype: list(str)
    """

    node = _get_pynode(node)
    written = []

    for attr_name, attr_value in attribute_dict.items():
        if not node.hasAttr(attr_name):
            maya_type, is_multi = _maya_type_for(
                attr_value, '{}.{}'.format(node.nodeName(), attr_name))
            _add_attribute(node, attr_name, maya_type, is_multi)

        if attr_value is None:
            continue

        attribute = node.attr(attr_name)
        if isinstance(attr_value, (list, tuple)):
            original_values = []
            start_index = 0
            if merge_values:
                original_values = attribute.get() or []
                existing_indices = node.getAttr(attr_name, multiIndices=True)
                start_index = max(existing_indices) + 1 if existing_indices else 0
            for index, one_value in enumerate(attr_value):
                if merge_values and one_value in original_values:
                    continue
                _connect_value(node, attribute[index + start_index], one_value)
        else:
            _connect_value(node, attribute, attr_value)
        written.append(attr_name)
    return written


def set_compound_attribute_groups(node, compound_attr_name, attribute_dict):
    """
    Put a dictionary's worth of values onto a node as one compound attribute.

    This is how the pipeline stores a block of properties - a rig component's settings, an
    asset's markup - so that they read as one rollout in the channel box and travel with the
    node. Each child is named ``<compound>_<property>``, because Maya registers every
    attribute on the node itself and two blocks would otherwise collide over a shared property
    name.

    Writing a block that is already there replaces it: the compound is deleted and rebuilt, so
    the number of children matches the dictionary. To change one value, set that value.

    :param node: The node to write onto, as a PyNode, a name or a FRAG node.
    :param str compound_attr_name: What the block is called.
    :param dict attribute_dict: Property names to values. A key that is not a string is
        skipped.
    """

    node = _get_pynode(node)
    properties = {name: value for name, value in attribute_dict.items()
                  if isinstance(name, str)}
    for name in attribute_dict:
        if not isinstance(name, str):
            # A bare string expression stood here, which reported nothing.
            logger.warning('%s: the key %r is not a string, so it is skipped.',
                           compound_attr_name, name)

    if node.hasAttr(compound_attr_name):
        node.deleteAttr(compound_attr_name)

    if not properties:
        # A block with no properties in it. The type is neither here nor there - it exists to
        # be found, not read.
        node.addAttr(compound_attr_name, attributeType='bool')
    else:
        # The extra bool child is a workaround: the channel box rollout does not always work
        # when every child of a compound is the same non-bool type. It is hidden, and it is
        # deliberately not named '<compound>_something', so the exporter skips it.
        node.addAttr(compound_attr_name, numberOfChildren=len(properties) + 1,
                     attributeType='compound')
        node.addAttr('_{}_hidden'.format(compound_attr_name), attributeType='bool',
                     parent=compound_attr_name, h=True)

    # Every child is added before any value is set: Maya will not take a value for a compound
    # whose children are still arriving.
    for property_name, property_value in properties.items():
        child_name = '{}_{}'.format(compound_attr_name, property_name)
        if node.hasAttr(child_name):
            continue
        if property_value is None:
            # A None here means "a place to write something later", and a string holds
            # anything.
            maya_type, is_multi = 'string', False
        else:
            maya_type, is_multi = _maya_type_for(
                property_value, '{}.{}'.format(compound_attr_name, property_name))
        _add_attribute(node, child_name, maya_type, is_multi, nice_name=property_name,
                       parent=compound_attr_name)

    for property_name, property_value in properties.items():
        child = node.attr('{}_{}'.format(compound_attr_name, property_name))

        if isinstance(property_value, pm.Attribute):
            property_value.disconnect()
            property_value >> child
        elif isinstance(property_value, pm.PyNode):
            if pm.attributeQuery('message', node=property_value, exists=True):
                property_value.message >> child
            else:
                logger.warning('%s has no message attribute, so it could not be connected '
                               'to %s.', property_value, child)
        elif isinstance(property_value, (list, tuple)):
            for index, one_value in enumerate(property_value):
                if one_value is None:
                    continue
                if isinstance(one_value, pm.Attribute):
                    # The version this replaces tested `property_value` here - the whole list -
                    # which is never an Attribute, so this branch never ran.
                    one_value.disconnect()
                    one_value >> child[index]
                elif isinstance(one_value, pm.PyNode):
                    if pm.attributeQuery('message', node=one_value, exists=True):
                        one_value.message >> child[index]
                    else:
                        logger.warning('%s has no message attribute, so it could not be '
                                       'connected to %s.', one_value, child)
                else:
                    child[index].set(one_value)
        elif property_value is not None:
            child.set(property_value)


def _compound_attribute(node, compound_attr_name):
    """
    A compound attribute by name.

    :param node: The node holding it.
    :param str compound_attr_name: The compound's name.
    :return: The attribute, or None. The version this replaces answered with the *class*
        ``pm.nt.General.Attribute`` - a name that does not exist, so the failure path raised
        AttributeError rather than reporting the missing attribute.
    :rtype: pm.Attribute or None
    """

    node = _get_pynode(node)
    if node.hasAttr(compound_attr_name):
        return node.attr(compound_attr_name)
    logger.warning('%s has no compound attribute called %r.', node, compound_attr_name)
    return None


def get_all_attributes_from_compound_attr(node, compound_attr_name=None):
    """
    The child attributes of a compound.

    :param node: The node holding it, or the compound attribute itself.
    :param str compound_attr_name: The compound's name, when a node was given.
    :return: The children, or None when there is no such compound.
    :rtype: list(pm.Attribute) or None
    """

    if isinstance(node, pm.Attribute):
        compound_attr = node
        node = compound_attr.node()
    else:
        node = _get_pynode(node)
        compound_attr = _compound_attribute(node, compound_attr_name)
        if compound_attr is None:
            return None

    # listAttr on a compound answers with the compound itself and then its children. The
    # version this replaces filtered with `str(x) not in compound_name` - a substring test,
    # which happens to come to the same thing because every child is named with the compound's
    # name as a prefix, but only by accident.
    compound_name = str(compound_attr).split('.')[-1]
    return [node.attr(name) for name in pm.listAttr(compound_attr) or []
            if name != compound_name]


def get_compound_attr_connections(node, compound_attr_name=None, as_plugs=False,
                                  destination=True, source=True):
    """
    Everything wired into or out of a compound attribute's children.

    :param node: The node holding it, or the compound attribute itself.
    :param str compound_attr_name: The compound's name, when a node was given.
    :param bool as_plugs: Answer with the attributes on the other end rather than their nodes.
    :param bool destination: Follow connections going out.
    :param bool source: Follow connections coming in.
    :return: What is connected, or None when there is no such compound.
    :rtype: list(pm.PyNode) or None
    """

    if isinstance(node, pm.Attribute):
        compound_attr = node
        node = compound_attr.node()
    else:
        node = _get_pynode(node)
        compound_attr = _compound_attribute(node, compound_attr_name)
        if compound_attr is None:
            return None

    found = []
    for child_name in pm.listAttr(compound_attr, connectable=True) or []:
        child = node.attr(child_name)
        for one in child.listConnections(plugs=as_plugs, destination=destination,
                                         source=source) or []:
            if one not in found:
                found.append(one)
    return found


def get_compound_attr_names(node):
    """
    The names of every compound attribute on a node.

    :param pm.PyNode node: The node to look at.
    :return: The compound attributes' short names.
    :rtype: list(str)
    """

    found = []
    for attribute in node.listAttr() or []:
        if not pm.objExists(attribute):
            continue
        # TdataCompound is what Maya calls a compound attribute's type.
        if attribute.type() == 'TdataCompound':
            found.append(str(attribute).split('.')[-1])
    return found


def _disconnect_compound(node, compound_attr_name):
    """
    Take everything off a compound attribute's children.

    :param node: The node holding it.
    :param str compound_attr_name: The compound's name.
    """

    for child in get_all_attributes_from_compound_attr(node, compound_attr_name) or []:
        if child.isArray():
            for index in child.getArrayIndices() or []:
                for plug in child[index].listConnections(plugs=True) or []:
                    pm.disconnectAttr(plug, child[index])
            continue
        for plug in child.listConnections(plugs=True) or []:
            pm.disconnectAttr(plug, child)


def disconnect_and_delete_compound_attr(node, compound_attr_name):
    """
    Unwire a compound attribute and delete it.

    Unwiring first: Maya refuses to delete an attribute something is connected to.

    :param node: The node holding it.
    :param str compound_attr_name: The compound's name.
    :return: Whether it is gone.
    :rtype: bool
    """

    node = _get_pynode(node)
    if not node.hasAttr(compound_attr_name):
        logger.warning('%s has no compound attribute called %r.', node, compound_attr_name)
        return False

    _disconnect_compound(node, compound_attr_name)
    pm.deleteAttr(node.attr(compound_attr_name))
    return True


def connect_nodes_with_message_attrs(source_node, source_attr, target_node, target_attr):
    """
    Wire two nodes together through message attributes, making them if they are not there.

    A message attribute holds nothing; it exists so that one node can point at another and be
    followed back. It is how a rig keeps track of what belongs to what.

    :param source_node: The node the connection comes from.
    :param source_attr: Its attribute, by name or itself.
    :type source_attr: str or pm.Attribute
    :param target_node: The node it goes to.
    :param target_attr: Its attribute, by name or itself.
    :type target_attr: str or pm.Attribute
    :return: Whether the connection was made.
    :rtype: bool
    :raises AttributeError: When a named attribute is already there and is not a message
        attribute.
    """

    source_node = _get_pynode(source_node)
    target_node = _get_pynode(target_node)

    def message_attribute(node, attribute):
        if isinstance(attribute, pm.Attribute):
            if attribute.type() != 'message':
                raise AttributeError('{} is not a message attribute.'.format(attribute))
            return attribute
        if not isinstance(attribute, str):
            raise AttributeError('{!r} is neither a name nor an attribute.'.format(attribute))
        if node.hasAttr(attribute):
            existing = node.attr(attribute)
            if existing.type() != 'message':
                raise AttributeError('{}.{} is not a message attribute, so it was not '
                                     'connected.'.format(node, attribute))
            return existing
        node.addAttr(attribute, at='message')
        return node.attr(attribute)

    source = message_attribute(source_node, source_attr)
    target = message_attribute(target_node, target_attr)

    try:
        source >> target
    except RuntimeError as error:
        # The version this replaces swallowed this with a bare `except Exception: pass`, so a
        # rig built with a connection missing looked exactly like one built correctly.
        logger.warning('Could not connect %s to %s: %s', source, target, error)
        return False
    return True


def remove_relationship_between_nodes(source_node, destination_node):
    """
    Disconnect everything one node drives on another.

    :param pm.PyNode source_node: The driving node.
    :param pm.PyNode destination_node: The driven node.
    :return: The attributes that were disconnected.
    :rtype: list(pm.Attribute)
    """

    disconnected = []
    for attribute in destination_node.listAttr() or []:
        if not attribute.isDestination():
            continue
        for plug in pm.listConnections(attribute, source=True, plugs=True) or []:
            if plug.node() != source_node:
                continue
            pm.disconnectAttr(plug, attribute)
            disconnected.append(attribute)
    return disconnected


def invert_attribute(attr):
    """
    A node that gives back the reverse of an attribute, and two other readings of it.

    One ``setRange`` node with three outputs, aliased so they read as what they are:
    ``straight`` follows the attribute, ``inverse`` is one minus it, and ``percentage`` is it
    as a number from 0 to 100. A visibility switch and its opposite come off the same node.

    :param attr: The attribute to read, by name or itself. It is expected to run from 0 to 1.
    :type attr: str or pm.Attribute
    :return: The ``setRange`` node.
    :rtype: pm.nt.SetRange
    """

    attribute = pm.PyNode(attr)
    node_name = attribute.nodeName().split(':')[-1].replace('.', '_')
    reverse_node = pm.createNode('setRange', name='{}_inverseAttr'.format(node_name))

    # Named against the node. The version this replaces wrote pm.setAttr('.min', ...) - a
    # relative name, which means "whatever is selected" - and worked only because createNode
    # leaves its node selected. Anything that touched the selection first sent these values to
    # the wrong node.
    for attribute_name, values in (('min', [0, 1, 0]),
                                   ('max', [1, 0, 100]),
                                   ('oldMin', [0, 0, 0]),
                                   ('oldMax', [1, 1, 1])):
        reverse_node.attr(attribute_name).set(values)
        reverse_node.attr(attribute_name).set(keyable=False, lock=True)

    pm.aliasAttr('straight', '{}.outValueX'.format(reverse_node),
                 'inverse', '{}.outValueY'.format(reverse_node),
                 'percentage', '{}.outValueZ'.format(reverse_node))
    for axis in 'XYZ':
        pm.connectAttr(attribute, '{}.value{}'.format(reverse_node, axis), force=True)
    return reverse_node


# --------------------------------------------------------------------------------------- #
# transform limits
# --------------------------------------------------------------------------------------- #
def _add_limit_attribute(node, limit_name, limit_min=0.0, limit_max=0.0,
                         lock_min=True, lock_max=True):
    """
    Record one axis's limits on a node, as a two-float compound.

    The limits live on the rig's network node as well as on the control, so a rebuild can put
    them back without anybody having to remember what they were.

    :param node: The node to record them on.
    :param str limit_name: What to call the pair - ``'translateLimitX'``.
    :param float limit_min: The lower limit.
    :param float limit_max: The upper limit.
    :param bool lock_min: Lock the lower one. The version this replaces called
        ``attr.lock(True)``, where pymel's ``lock`` takes ``checkReference`` - so the True was
        asking Maya to raise if the attribute belonged to a referenced node, rather than saying
        anything about the lock.
    :param bool lock_max: Lock the upper one.
    :return: The compound attribute.
    :rtype: pm.Attribute
    """

    node = _get_pynode(node)
    minimum_name = limit_name + 'Min'
    maximum_name = limit_name + 'Max'

    node.addAttr(limit_name, at='float2')
    node.addAttr(minimum_name, at='float', parent=limit_name)
    node.addAttr(maximum_name, at='float', parent=limit_name)
    node.attr(minimum_name).set(limit_min)
    node.attr(maximum_name).set(limit_max)
    if lock_min:
        node.attr(minimum_name).lock()
    if lock_max:
        node.attr(maximum_name).lock()
    return node.attr(limit_name)


#: The six axes limits are set on, with the flags ``transformLimits`` wants for each and the
#: name the pair is recorded under.
_LIMIT_AXES = (
    ('translateLimitX', 'tx', 'etx'),
    ('translateLimitY', 'ty', 'ety'),
    ('translateLimitZ', 'tz', 'etz'),
    ('orientLimitX', 'rx', 'erx'),
    ('orientLimitY', 'ry', 'ery'),
    ('orientLimitZ', 'rz', 'erz'),
)


def set_limits(rig_flag, rig_node=None,
               limit_point=((None, None), (None, None), (None, None)),
               limit_orient=((None, None), (None, None), (None, None))):
    """
    Limit how far a control can be moved and turned, and record the limits.

    An axis given no limits at all is locked and taken out of the channel box: a control that
    cannot move in x should not offer to.

    :param rig_flag: The control to limit.
    :param rig_node: The node to record the limits on. The control itself by default.
    :param limit_point: Three ``(minimum, maximum)`` pairs, for translate x, y and z. ``None``
        in either place means "no limit that way".
    :param limit_orient: The same three pairs for rotate.
    :return: The limits as they were applied, as ``(minimum, maximum, minimum_set,
        maximum_set)`` per axis.
    :rtype: list(tuple)
    """

    rig_node = rig_node if rig_node is not None else rig_flag

    limits = []
    for limit_min, limit_max in tuple(limit_point) + tuple(limit_orient):
        limits.append((limit_min if limit_min is not None else 0,
                       limit_max if limit_max is not None else 0,
                       limit_min is not None,
                       limit_max is not None))

    for (limit_attr_name, axis_flag, enable_flag), one_limit in zip(_LIMIT_AXES, limits):
        minimum, maximum, minimum_set, maximum_set = one_limit
        pm.transformLimits(rig_flag, **{axis_flag: (minimum, maximum),
                                        enable_flag: (minimum_set, maximum_set)})
        _add_limit_attribute(rig_node, limit_attr_name, limit_min=minimum, limit_max=maximum,
                             lock_min=not minimum_set, lock_max=not maximum_set)

    # An axis with no limit in either direction is not meant to be touched.
    for axis_name, pair in zip(TRANSLATION_ATTRS + ROTATION_ATTRS,
                               tuple(limit_point) + tuple(limit_orient)):
        if any(one is not None for one in pair):
            continue
        attribute = rig_flag.attr(axis_name)
        attribute.lock()
        attribute.set(keyable=False, channelBox=False)

    return limits
