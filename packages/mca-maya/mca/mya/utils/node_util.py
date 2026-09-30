"""
Making nodes and attributes from data, and telling whether a node is worth keeping.

The two things this is for: rebuilding an attribute from the dictionary
:func:`mca.mya.utils.attr_utils.serialize_attribute` wrote, and deciding during a scene
clean-up whether a node has anything in it.

What was wrong before:

- **Rebuilding a compound attribute always failed.** ``add_attribute`` handed the job to
  ``attr_utils.add_compound_attribute``, and there is no such function - not in ``attr_utils``,
  not anywhere in the pipeline. So ``AttributeError: module has no attribute
  'add_compound_attribute'``, every time. ``skel_utils`` rebuilds a skeleton's user attributes
  from serialized data and passes exactly what it was given, ``children`` included, so any
  skeleton carrying a compound user attribute could not be rebuilt. The compound is built here
  now.
- **A type of ``0`` was thrown away.** The type was read as ``kwargs.pop('type') or
  kwargs.pop('attrType') or kwargs.pop('attr_type')``, and ``0`` is falsy - so
  ``type=attributetypes.kMFnNumericBoolean``, which *is* ``0``, fell through to ``None`` and
  Maya made a double. Every boolean attribute rebuilt by number came back as a float.
- **A minimum or a maximum was never applied.** They were left out of the ``addAttr`` call on
  purpose and set afterwards with pymel's ``setMin`` and ``setMax``, and those do nothing at
  all on a dynamic attribute: ``setMin(0.0)`` followed by ``getMin()`` answers ``None``. The
  limits go in with the attribute now.
- **A compound's children could not be reached while it was being built.** Maya does not finish
  making a compound until it has as many children as it was promised, so ``hasAttr`` answers
  False for every child but the last. Anything that set a child up as it went - which is what
  the obvious way of writing this does - failed on the first one.
- **An enumeration's fields came back in a random order.** ``add_kwargs['enumName'] =
  list(set(enum_names))`` - a set, which has no order - so an attribute rebuilt from data had
  its choices shuffled, and every value stored against it meant something else. Enumerations are
  stored as indices.
- **``set_attribute_info_from_dict`` never set the default value it documents.** Its own code
  reads ``if default is not None: pass``, followed by eight commented-out lines. The docstring
  and the data format both describe a ``default`` key; nothing was ever done with it. It is set
  now, through ``addAttr``, which is the only way Maya will take it.
- **``is_empty``'s guard on Maya's own nodes could never fire.** ``if node in default_nodes``
  compares a PyNode against a list of *strings*, and a PyNode is never equal to a string, so
  ``initialShadingGroup``, ``defaultLightSet`` and the two configuration script nodes were not
  protected at all. ``scene_utils`` uses this function to decide what to delete during a scene
  clean-up.
- **Six functions had no callers**: ``match_translation``, ``match_rotation``,
  ``reset_transform``, ``rbf_retarget``, ``center_obj`` and ``orient_obj_to_obj`` - about two
  hundred lines. Dropping ``rbf_retarget`` also takes this module's imports of
  ``mca.mya.plugins.loader`` and ``mca.mya.utils.material_utils`` with it, and that second one
  is what made ``node_util`` and ``material_utils`` import each other.
"""

# python imports
import copy
import json

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.utils.om import attributetypes


logger = log.MCA_LOGGER

#: Maya's own nodes, which look empty and are not: deleting them breaks the scene. Compared by
#: name - the version this replaces compared a PyNode against these strings, which is never
#: equal, so none of them were protected.
DEFAULT_NODE_NAMES = ('defaultLightSet', 'defaultObjectSet', 'initialShadingGroup',
                      'uiConfigurationScriptNode', 'sceneConfigurationScriptNode')

#: Keys in a serialized attribute that describe it rather than tell ``addAttr`` anything.
_NOT_ADD_ATTR_KEYWORDS = ('locked', 'isChild', 'isDynamic', 'isElement',
                          'softMin', 'softMax', 'min', 'max')


def is_empty(node, no_user_attributes=True, no_connections=True):
    """
    Whether a node holds nothing and can be deleted.

    Empty means: not referenced, no children, none of Maya's own, and - by default - no
    attributes anybody added and nothing connected to it.

    :param pm.PyNode node: The node to judge.
    :param bool no_user_attributes: An attribute somebody added counts as content.
    :param bool no_connections: A connection counts as content.
    :return: Whether it is empty.
    :rtype: bool
    """

    if pm.referenceQuery(node, isNodeReferenced=True):
        return False

    # By name. A PyNode is never equal to a string, which is why the version this replaces did
    # not protect any of these.
    if str(node).split('|')[-1].split(':')[-1] in DEFAULT_NODE_NAMES:
        return False

    if isinstance(node, pm.nt.Transform) and pm.listRelatives(node):
        return False

    if no_user_attributes and pm.listAttr(node, userDefined=True, keyable=True):
        return False

    if no_connections:
        connections = pm.listConnections(node)
        # Every node in the scene is connected to defaultRenderGlobals; that on its own is not
        # content.
        if connections and connections != ['defaultRenderGlobals']:
            return False

    return True


def create_or_find(name, node_type):
    """
    The node of this name and type, made if it is not there.

    :param str name: What it is called.
    :param node_type: The PyNode class of the type - ``pm.nt.RemapValue``.
    :return: The node.
    :rtype: pm.PyNode
    """

    node = lists.get_first_in_list(pm.ls(name, recursive=True, type=node_type))
    if node:
        return node
    return pm.createNode(node_type, name=name)


def _first_given(kwargs, *names):
    """
    The first of these keys that was given a value, popped out of the dictionary.

    Written as a function because ``kwargs.pop('type') or kwargs.pop('attrType')`` - which is
    what the version this replaces used - loses a value of ``0``, and ``0`` is a real attribute
    type: it is ``kMFnNumericBoolean``. So ``type=attributetypes.kMFnNumericBoolean`` fell
    through to ``None`` and Maya made a double.

    :param dict kwargs: The dictionary to take from. Every named key is removed from it.
    :param names: The keys to try, in order.
    :return: The first value that was not None, or None.
    """

    answer = None
    for name in names:
        value = kwargs.pop(name, None)
        if answer is None and value is not None:
            answer = value
    return answer


def _add_attr_keywords(kwargs):
    """
    Split a serialized attribute into what ``addAttr`` takes and what has to be done after.

    :param dict kwargs: The attribute's description. Not modified.
    :return: The keywords for ``addAttr``, the value to set afterwards, whether it goes in the
        channel box, the Maya type name, and the description as it stands after a ``'complex'``
        value has been turned into JSON - which is what the rest of the set-up has to work from,
        or it writes the dictionary's Python repr over the JSON.
    :rtype: tuple(dict, object, bool, str, dict)
    """

    kwargs = dict(kwargs)
    attr_type = _first_given(kwargs, 'type', 'attrType', 'attr_type')
    if isinstance(attr_type, int) and not isinstance(attr_type, bool):
        # One of this pipeline's own type numbers, as written by serialize_plug.
        attr_type = attributetypes.om_type_to_pymel_type(attr_type)

    if attr_type == 'complex':
        # A dictionary, kept as JSON in a string attribute.
        attr_type = 'string'
        for key in ('value', 'default'):
            if isinstance(kwargs.get(key), dict):
                try:
                    kwargs[key] = json.dumps(kwargs[key])
                except (TypeError, ValueError) as error:
                    logger.warning('Could not write %r as JSON: %s', kwargs[key], error)
                    kwargs[key] = ''

    add_kwargs = dict(kwargs)
    add_kwargs['type'] = attr_type
    for key in _NOT_ADD_ATTR_KEYWORDS:
        add_kwargs.pop(key, None)

    value = add_kwargs.pop('value', None)
    connectable = add_kwargs.pop('connectable', True)
    channel_box = add_kwargs.pop('channelBox', False)
    is_array = add_kwargs.pop('isArray', False)
    default = add_kwargs.pop('default', None)
    if default is None:
        default = add_kwargs.pop('defaultValue', None)
    else:
        add_kwargs.pop('defaultValue', None)

    if 'multi' not in add_kwargs:
        add_kwargs['multi'] = is_array
    if 'writable' not in add_kwargs:
        add_kwargs['writable'] = connectable

    enums = add_kwargs.pop('enums', None)
    if enums:
        # In order, each one once. The version this replaces built this with `list(set(...))`,
        # which has no order at all - so an attribute rebuilt from data had its choices
        # shuffled, and every index stored against it then meant something else.
        enum_names = list(add_kwargs.pop('enumNames', []) or []) + list(enums)
        add_kwargs['enumName'] = ':'.join(dict.fromkeys(str(one) for one in enum_names))

    # The default, the minimum and the maximum all have to go in with the attribute. Setting
    # them afterwards through pymel's setMin and setMax does nothing at all on a dynamic
    # attribute - `setMin(0.0)` followed by `getMin()` answers None - which is how the version
    # this replaces came to write limits that were never applied.
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        add_kwargs['defaultValue'] = default
    elif default is None and isinstance(value, (int, float)) and not isinstance(value, bool):
        # No default given, but a number to hold: that number is the sensible default, which is
        # what the version this replaces was reaching for in a roundabout way.
        add_kwargs['defaultValue'] = value

    for key, maya_key in (('min', 'minValue'), ('max', 'maxValue')):
        limit = kwargs.get(key)
        if isinstance(limit, (int, float)) and not isinstance(limit, bool):
            add_kwargs[maya_key] = limit

    return add_kwargs, value, channel_box, attr_type, kwargs


def add_attribute(node, **kwargs):
    """
    Add an attribute from the dictionary :func:`attr_utils.serialize_attribute` writes.

    Which is more than ``addAttr`` can take: the keys describe the attribute's limits, its lock,
    its place in the channel box and - for a compound - its children, and ``addAttr`` wants only
    some of that and refuses the rest.

    ``type`` may be one of this pipeline's own type numbers as well as a Maya type name, and
    ``'complex'`` means a dictionary written into a string attribute as JSON.

    :param pm.PyNode node: The node to add it to.
    :param kwargs: The attribute's description. ``name`` (or ``longName``, or ``shortName``) is
        the only one required.
    :return: The attribute.
    :rtype: pm.Attribute
    :raises ValueError: When no name was given.
    :raises RuntimeError: When ``raise_exceptions`` is given and the attribute is already there.
    """

    kwargs = dict(kwargs)
    raise_exceptions = kwargs.pop('raise_exceptions', False)
    attr_name = _first_given(kwargs, 'name', 'longName', 'shortName')
    if not attr_name:
        raise ValueError('add_attribute needs a name.')

    if node.hasAttr(attr_name):
        _set_attribute_info(node.attr(attr_name), **kwargs)
        if raise_exceptions:
            raise RuntimeError('{} already has an attribute called {!r}.'
                               .format(node.longName(), attr_name))
        return node.attr(attr_name)

    children = kwargs.pop('children', None)
    if children:
        return _add_compound_attribute(node, attr_name, children, **kwargs)

    add_kwargs, value, channel_box, attr_type, settled = _add_attr_keywords(kwargs)
    node.addAttr(attr_name, **add_kwargs)
    attribute = node.attr(attr_name)

    if value is not None and attr_type == 'string':
        attribute.set(value)

    attribute.showInChannelBox(channel_box)
    _set_attribute_info(attribute, **settled)
    return attribute


def _add_compound_attribute(node, attr_name, children, **kwargs):
    """
    Build a compound attribute and its children from serialized data.

    This is the part that was missing: ``add_attribute`` called
    ``attr_utils.add_compound_attribute``, which does not exist, so every rebuild of a compound
    attribute raised ``AttributeError``.

    The children are all added before any of them is set up, because Maya does not finish
    making a compound until it has as many children as it was promised - ``node.hasAttr(child)``
    answers False for every child but the last one, so anything that reaches for a child part
    way through fails.

    :param pm.PyNode node: The node to add it to.
    :param str attr_name: The compound's name.
    :param children: One serialized description per child.
    :type children: list(dict)
    :param kwargs: The compound's own description.
    :return: The compound attribute.
    :rtype: pm.Attribute
    """

    described = [dict(child) for child in children if child]
    if not described:
        raise ValueError('{}.{} is a compound with no children described.'
                         .format(node, attr_name))

    compound_kwargs = {'numberOfChildren': len(described), 'attributeType': 'compound'}
    if kwargs.get('isArray'):
        compound_kwargs['multi'] = True
    node.addAttr(attr_name, **compound_kwargs)

    child_names = []
    for index, child in enumerate(described):
        child_name = (_first_given(child, 'name', 'longName')
                      or '{}_{}'.format(attr_name, index))
        child_names.append(child_name)
        # A child cannot be a multi, and it cannot be given children of its own here: Maya
        # wants a nested compound declared with its own numberOfChildren, which the data format
        # does not describe.
        child.pop('isArray', None)
        child.pop('children', None)
        add_kwargs, _, _, _, settled = _add_attr_keywords(child)
        add_kwargs['multi'] = False
        add_kwargs['parent'] = attr_name
        node.addAttr(child_name, **add_kwargs)
        described[index] = settled

    # Now that the compound is complete, every child can be reached and set up.
    for child_name, child in zip(child_names, described):
        _set_attribute_info(node.attr(child_name), **child)

    attribute = node.attr(attr_name)
    _set_attribute_info(attribute, children=described,
                        **{key: value for key, value in kwargs.items() if key != 'children'})
    return attribute


def _set_attribute_info(attr, **kwargs):
    """
    Apply the parts of a serialized attribute that ``addAttr`` will not take.

    Limits, lock, keyable, channel box, and the value - including for each child of a compound.

    :param pm.Attribute attr: The attribute to set up.
    :param kwargs: The attribute's description, in the form
        :func:`attr_utils.serialize_attribute` writes:

        .. code-block:: python

            {
                'type': 'double',
                'channelBox': True,
                'default': 1.0,
                'keyable': True,
                'locked': False,
                'min': 0.0,
                'max': 99999,
                'name': 'scale',
                'value': 1.0,
                'children': [{}],       # each in the same form
            }
    """

    children = kwargs.get('children') or []
    if attr.isCompound() and not attr.isArray():
        child_attributes = attr.getChildren()
        if not children:
            # No per-child description, so the parent's applies to each child - with the
            # parent's value and default split across them, one component each.
            children = [copy.deepcopy(kwargs) for _ in child_attributes]
            for index, child_info in enumerate(children):
                for key in ('value', 'default'):
                    sequence = child_info.get(key)
                    if isinstance(sequence, (list, tuple)) and index < len(sequence):
                        child_info[key] = sequence[index]
                child_info.pop('children', None)
        for index, child_info in enumerate(children):
            if not child_info or index >= len(child_attributes):
                continue
            try:
                _set_attribute_info(child_attributes[index], **child_info)
            except RuntimeError:
                logger.error('Could not set up %s from %s.',
                             child_attributes[index].name(), child_info)
                raise

    value = kwargs.get('value')
    if value is not None and not attr.isCompound() and not attr.isArray():
        try:
            attr.set(value)
        except RuntimeError as error:
            logger.warning('Could not set %s to %r: %s', attr.name(), value, error)

    # The hard limits go in with addAttr - pymel's setMin and setMax do nothing on a dynamic
    # attribute, which is why the version this replaces wrote limits that were never applied -
    # so what is left here is to turn them on for an attribute that already existed.
    for key, has_flag, value_flag in (('min', 'hasMinValue', 'minValue'),
                                      ('max', 'hasMaxValue', 'maxValue')):
        limit = kwargs.get(key)
        if limit is None:
            continue
        try:
            cmds.addAttr(attr.name(), edit=True, **{has_flag: True, value_flag: limit})
        except RuntimeError as error:
            logger.warning('Could not set the %s of %s: %s', key, attr.name(), error)

    for key, setter in (('softMin', attr.setSoftMin), ('softMax', attr.setSoftMax)):
        if kwargs.get(key) is None:
            continue
        try:
            setter(kwargs[key])
        except RuntimeError as error:
            logger.warning('Could not set %s on %s: %s', key, attr.name(), error)

    if kwargs.get('channelBox') is not None:
        attr.showInChannelBox(kwargs['channelBox'])
    if kwargs.get('keyable') is not None:
        attr.setKeyable(kwargs['keyable'])
    # Last: a locked attribute takes nothing else.
    if kwargs.get('locked') is not None:
        attr.setLocked(kwargs['locked'])
