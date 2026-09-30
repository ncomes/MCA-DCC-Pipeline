"""
Reading an attribute through the API: what type it is, what it holds, and how to write that
down.

This is what flag files, rig data and the attribute copying in ``attr_utils`` are built on.
It goes through ``maya.api.OpenMaya`` rather than ``maya.cmds`` because the command layer
cannot answer some of these questions at all - whether a plug is at its default, what a
compound's children are, what an enumeration's field names are - and is far too slow for the
rest.

What was wrong before:

- **Every transform attribute serialized with ``'type': None``.** ``get_plug_type`` asked
  ``attributetypes.maya_unit_type_to_internal_type`` for the type of a unit attribute, and
  that function read the wrong table and answered ``None`` for everything (see
  :mod:`mca.mya.utils.om.attributetypes`). A transform's ``translate`` is a distance and its
  ``rotate`` is an angle - both unit attributes - so the type of the most commonly serialized
  attributes in the pipeline was missing from every flag file and every piece of rig data
  written since.
- **The ``optimize`` pass stripped four keys that were never there.** ``serialize_plug``
  popped ``min``, ``max``, ``softMin`` and ``softMax``, and nothing in the function ever set
  them: the limits are added afterwards, by ``attr_utils.serialize_attribute``, *after* this
  has returned. So the optimisation could not fire, and the limits are written whether or not
  they are set. Only ``attr_utils`` can fix that, and it is noted there.
- **``get_enum_names`` swallowed everything** with a bare ``except Exception: pass`` around
  ``fieldName``, which is the one call in it that can fail, and failed silently for a
  enumeration with a gap in its numbering.
- **``get_python_type_from_plug_value`` listed the float array twice** in its tuple of types
  to turn into a tuple, and left out the double array's neighbours. Harmless, but it is the
  kind of list that gets copied.
- **A float array is read as a double array.** ``MFnFloatArrayData`` is missing from
  ``OpenMaya`` 2.0 - it is still missing in Maya 2025, which the suite checks - so there is
  no way to read a float array as floats. The comment saying so was a ``TODO``; it is the
  answer, not a task.
"""

# python imports

# software specific imports
import maya.api.OpenMaya as OpenMaya

# mca imports
from mca.common import log
from mca.mya.utils.om import attributetypes


logger = log.MCA_LOGGER

#: The types whose value is a sequence that should be written down as a tuple.
_SEQUENCE_TYPES = (
    attributetypes.kMFnDataMatrix,
    attributetypes.kMFnDataFloatArray,
    attributetypes.kMFnDataDoubleArray,
    attributetypes.kMFnDataIntArray,
    attributetypes.kMFnDataPointArray,
    attributetypes.kMFnDataStringArray,
    attributetypes.kMFnNumeric2Double,
    attributetypes.kMFnNumeric2Float,
    attributetypes.kMFnNumeric2Int,
    attributetypes.kMFnNumeric2Long,
    attributetypes.kMFnNumeric2Short,
    attributetypes.kMFnNumeric3Double,
    attributetypes.kMFnNumeric3Float,
    attributetypes.kMFnNumeric3Int,
    attributetypes.kMFnNumeric3Long,
    attributetypes.kMFnNumeric3Short,
    attributetypes.kMFnNumeric4Double,
)

#: The three unit types, whose value is an MDistance, MAngle or MTime rather than a number.
_UNIT_TYPES = (
    attributetypes.kMFnUnitAttributeDistance,
    attributetypes.kMFnUnitAttributeAngle,
    attributetypes.kMFnUnitAttributeTime,
)


def as_mplug(attribute_full_name):
    """
    The ``MPlug`` for an attribute named the way Maya prints it.

    :param str attribute_full_name: ``'node.attribute'``, or ``'node.parent.child'``.
    :return: The plug.
    :rtype: OpenMaya.MPlug
    :raises RuntimeError: When there is no such attribute.
    """

    names = str(attribute_full_name).split('.')
    selection = OpenMaya.MSelectionList()
    try:
        selection.add(names[0])
        node = OpenMaya.MFnDependencyNode(selection.getDependNode(0))
        return node.findPlug('.'.join(names[1:]), False)
    except RuntimeError:
        # findPlug does not take a path through a compound, and a selection list does, so the
        # fall-back is the whole name handed to Maya to resolve.
        selection = OpenMaya.MSelectionList()
        selection.add(str(attribute_full_name))
        return selection.getPlug(0)


def get_plug_type(plug):
    """
    Which of :mod:`mca.mya.utils.om.attributetypes`' types a plug is.

    :param OpenMaya.MPlug plug: The plug to ask about.
    :return: One of the ``kMFn...`` constants, or None for a type this module does not name.
    :rtype: int or None
    """

    obj = plug.attribute()

    # Compound first: a compound numeric - a double3, say - answers true to both this and
    # kNumericAttribute, and it is the compound that describes it.
    if obj.hasFn(OpenMaya.MFn.kCompoundAttribute):
        return attributetypes.kMFnCompoundAttribute
    if obj.hasFn(OpenMaya.MFn.kNumericAttribute):
        return attributetypes.maya_numeric_type_to_internal_type(
            OpenMaya.MFnNumericAttribute(obj).numericType())
    if obj.hasFn(OpenMaya.MFn.kUnitAttribute):
        return attributetypes.maya_unit_type_to_internal_type(
            OpenMaya.MFnUnitAttribute(obj).unitType())
    if obj.hasFn(OpenMaya.MFn.kTypedAttribute):
        return attributetypes.maya_mfn_data_type_to_internal_type(
            OpenMaya.MFnTypedAttribute(obj).attrType())
    if obj.hasFn(OpenMaya.MFn.kEnumAttribute):
        return attributetypes.kMFnkEnumAttribute
    if obj.hasFn(OpenMaya.MFn.kMessageAttribute):
        return attributetypes.kMFnMessageAttribute
    if obj.hasFn(OpenMaya.MFn.kMatrixAttribute):
        return attributetypes.kMFnDataMatrix
    return None


def get_plug_default(plug):
    """
    What a plug is worth before anybody has set it.

    :param OpenMaya.MPlug plug: The plug to ask about.
    :return: The default, in whatever the API hands over - so an MDistance for a distance, an
        MObject for typed data. :func:`attributetypes.maya_type_to_python_type` turns that
        into something JSON can hold. None for a type with no default.
    """

    obj = plug.attribute()

    if obj.hasFn(OpenMaya.MFn.kNumericAttribute):
        attribute = OpenMaya.MFnNumericAttribute(obj)
        if attribute.numericType() == OpenMaya.MFnNumericData.kInvalid:
            return None
        return attribute.default
    if obj.hasFn(OpenMaya.MFn.kTypedAttribute):
        attribute = OpenMaya.MFnTypedAttribute(obj)
        default = attribute.default
        if default.apiType() == OpenMaya.MFn.kInvalid:
            return None
        if default.apiType() == OpenMaya.MFn.kStringData:
            return OpenMaya.MFnStringData(default).string()
        return default
    if obj.hasFn(OpenMaya.MFn.kUnitAttribute):
        return OpenMaya.MFnUnitAttribute(obj).default
    if obj.hasFn(OpenMaya.MFn.kMatrixAttribute):
        return OpenMaya.MFnMatrixAttribute(obj).default
    if obj.hasFn(OpenMaya.MFn.kEnumAttribute):
        return OpenMaya.MFnEnumAttribute(obj).default
    return None


def get_enum_names(plug):
    """
    An enumeration attribute's field names, in order.

    :param OpenMaya.MPlug plug: The plug to read.
    :return: The names. Empty for a plug that is not an enumeration.
    :rtype: list(str)
    """

    obj = plug.attribute()
    if not obj.hasFn(OpenMaya.MFn.kEnumAttribute):
        return []

    attribute = OpenMaya.MFnEnumAttribute(obj)
    names = []
    for index in range(attribute.getMin(), attribute.getMax() + 1):
        try:
            names.append(attribute.fieldName(index))
        except RuntimeError:
            # An enumeration can be numbered with gaps - 0, 1, 5 - and asking for one of the
            # missing numbers raises. The version this replaces caught every exception here
            # and said nothing, which hid the same thing happening for other reasons.
            logger.debug('%s has no enum field numbered %s.', plug.name(), index)
    return names


def get_numeric_type_and_value(plug):
    """
    A numeric plug's type and value.

    :param OpenMaya.MPlug plug: The plug to read.
    :return: The type constant and the value. ``(None, None)`` for a numeric type this does
        not handle.
    :rtype: tuple(int or None, object)
    """

    numeric_type = OpenMaya.MFnNumericAttribute(plug.attribute()).numericType()

    # The one-value types, each with the reader that gives the right Python type. A byte is
    # read as a bool because that is what Maya treats it as in practice.
    simple = {
        OpenMaya.MFnNumericData.kBoolean: (attributetypes.kMFnNumericBoolean, plug.asBool),
        OpenMaya.MFnNumericData.kByte: (attributetypes.kMFnNumericByte, plug.asBool),
        OpenMaya.MFnNumericData.kShort: (attributetypes.kMFnNumericShort, plug.asShort),
        OpenMaya.MFnNumericData.kInt: (attributetypes.kMFnNumericInt, plug.asInt),
        OpenMaya.MFnNumericData.kLong: (attributetypes.kMFnNumericLong, plug.asInt),
        OpenMaya.MFnNumericData.kDouble: (attributetypes.kMFnNumericDouble, plug.asDouble),
        OpenMaya.MFnNumericData.kFloat: (attributetypes.kMFnNumericFloat, plug.asFloat),
        OpenMaya.MFnNumericData.kAddr: (attributetypes.kMFnNumericAddr, plug.asInt),
        OpenMaya.MFnNumericData.kChar: (attributetypes.kMFnNumericChar, plug.asChar),
    }
    if numeric_type in simple:
        internal_type, reader = simple[numeric_type]
        return internal_type, reader()

    # The multi-value types - 2Double, 3Float and so on - all come out of MFnNumericData the
    # same way, so there is one branch for the lot of them rather than eleven.
    internal_type = attributetypes.maya_numeric_type_to_internal_type(numeric_type)
    if internal_type is not None:
        return internal_type, OpenMaya.MFnNumericData(plug.asMObject()).getData()
    return None, None


def get_typed_type_and_value(plug):
    """
    A typed plug's type and value - a string, a matrix, an array of something.

    :param OpenMaya.MPlug plug: The plug to read.
    :return: The type constant and the value. ``(None, None)`` for a data type this does not
        handle.
    :rtype: tuple(int or None, object)
    """

    data_type = OpenMaya.MFnTypedAttribute(plug.attribute()).attrType()

    if data_type == OpenMaya.MFnData.kInvalid:
        return None, None
    if data_type == OpenMaya.MFnData.kString:
        return attributetypes.kMFnDataString, plug.asString()
    if data_type == OpenMaya.MFnData.kNumeric:
        # A typed attribute can hold numeric data, in which case the numeric function set is
        # the one that can read it.
        return get_numeric_type_and_value(plug)
    if data_type == OpenMaya.MFnData.kMatrix:
        return (attributetypes.kMFnDataMatrix,
                OpenMaya.MFnMatrixData(plug.asMObject()).matrix())
    if data_type == OpenMaya.MFnData.kFloatArray:
        # MFnFloatArrayData does not exist in OpenMaya 2.0 - still true in Maya 2025, and the
        # suite checks it - so a float array is read as doubles. The type is reported as a
        # double array to match, because that is what a caller would have to write it back as.
        return (attributetypes.kMFnDataDoubleArray,
                OpenMaya.MFnDoubleArrayData(plug.asMObject()).array())
    if data_type == OpenMaya.MFnData.kDoubleArray:
        return (attributetypes.kMFnDataDoubleArray,
                OpenMaya.MFnDoubleArrayData(plug.asMObject()).array())
    if data_type == OpenMaya.MFnData.kIntArray:
        return (attributetypes.kMFnDataIntArray,
                OpenMaya.MFnIntArrayData(plug.asMObject()).array())
    if data_type == OpenMaya.MFnData.kPointArray:
        return (attributetypes.kMFnDataPointArray,
                OpenMaya.MFnPointArrayData(plug.asMObject()).array())
    if data_type == OpenMaya.MFnData.kVectorArray:
        return (attributetypes.kMFnDataVectorArray,
                OpenMaya.MFnVectorArrayData(plug.asMObject()).array())
    if data_type == OpenMaya.MFnData.kStringArray:
        return (attributetypes.kMFnDataStringArray,
                OpenMaya.MFnStringArrayData(plug.asMObject()).array())
    if data_type == OpenMaya.MFnData.kMatrixArray:
        return (attributetypes.kMFnDataMatrixArray,
                OpenMaya.MFnMatrixArrayData(plug.asMObject()).array())
    return None, None


def get_plug_type_and_value(plug):
    """
    A plug's type and value, whatever kind of plug it is.

    An array or a compound answers with a pair of *lists* - the types of its elements or
    children, and their values - rather than a single type and value.

    :param OpenMaya.MPlug plug: The plug to read.
    :return: The type and the value.
    :rtype: tuple(object, object)
    """

    obj = plug.attribute()

    if plug.isArray:
        return _children_types_and_values(
            [plug.elementByPhysicalIndex(index)
             for index in range(plug.evaluateNumElements())])

    if obj.hasFn(OpenMaya.MFn.kNumericAttribute):
        return get_numeric_type_and_value(plug)
    if obj.hasFn(OpenMaya.MFn.kTypedAttribute):
        return get_typed_type_and_value(plug)
    if obj.hasFn(OpenMaya.MFn.kUnitAttribute):
        unit_type = OpenMaya.MFnUnitAttribute(obj).unitType()
        if unit_type == OpenMaya.MFnUnitAttribute.kDistance:
            return attributetypes.kMFnUnitAttributeDistance, plug.asMDistance()
        if unit_type == OpenMaya.MFnUnitAttribute.kAngle:
            return attributetypes.kMFnUnitAttributeAngle, plug.asMAngle()
        if unit_type == OpenMaya.MFnUnitAttribute.kTime:
            return attributetypes.kMFnUnitAttributeTime, plug.asMTime()
    if obj.hasFn(OpenMaya.MFn.kEnumAttribute):
        return attributetypes.kMFnkEnumAttribute, plug.asInt()
    if obj.hasFn(OpenMaya.MFn.kMessageAttribute):
        # A message attribute holds nothing. Its value is whatever is wired into it.
        source = plug.source()
        return attributetypes.kMFnMessageAttribute, source.node() if source else None
    if obj.hasFn(OpenMaya.MFn.kMatrixAttribute):
        return (attributetypes.kMFnDataMatrix,
                OpenMaya.MFnMatrixData(plug.asMObject()).matrix())

    if plug.isCompound:
        return _children_types_and_values(
            [plug.child(index) for index in range(plug.numChildren())])

    return None, None


def _children_types_and_values(plugs):
    """
    The types and the values of several plugs, as two lists.

    :param plugs: The plugs to read.
    :type plugs: list(OpenMaya.MPlug)
    :return: Their types, and their values.
    :rtype: tuple(list, list)
    """

    types = []
    values = []
    for plug in plugs:
        one_type, one_value = get_plug_type_and_value(plug)
        types.append(one_type)
        values.append(one_value)
    return types, values


def get_python_type_from_plug_value(plug):
    """
    A plug's value as something Python holds and JSON can write.

    :param OpenMaya.MPlug plug: The plug to read.
    :return: The value. None for a message attribute, which holds nothing, and for a type
        this module does not name.
    """

    data_type, value = get_plug_type_and_value(plug)

    if data_type is None or data_type == attributetypes.kMFnMessageAttribute:
        return None

    # An array or a compound: data_type is a list of its children's types.
    if isinstance(data_type, (list, tuple)):
        answer = []
        for index, one_type in enumerate(data_type):
            if one_type == attributetypes.kMFnDataMatrix:
                answer.append(tuple(value[index]))
            elif one_type in _UNIT_TYPES:
                answer.append(value[index].value)
            else:
                # The version this replaces dropped anything that was neither a matrix nor a
                # unit, so a compound of three doubles serialized as an empty list.
                answer.append(attributetypes.maya_type_to_python_type(value[index]))
        return answer

    if data_type in (attributetypes.kMFnDataMatrixArray, attributetypes.kMFnDataVectorArray):
        return list(map(tuple, value))
    if data_type in _UNIT_TYPES:
        return value.value
    if data_type in _SEQUENCE_TYPES:
        return tuple(value)
    return value


def serialize_plug(plug, optimize=True, force=False):
    """
    Everything about a plug that would be needed to make it again, as a dictionary.

    :param OpenMaya.MPlug plug: The plug to write down.
    :param bool optimize: Leave out everything that is at its default, so the data holds only
        what somebody changed.
    :param bool force: Write a plug down even when it is at its default value.
    :return: The plug's description, or an empty dict for a plug there is nothing to say
        about.
    :rtype: dict
    """

    attr_type = get_plug_type(plug)
    data = {'isDynamic': plug.isDynamic}

    if not plug.isDynamic:
        # A built-in attribute at its default is not worth writing down: whatever reads this
        # back will find it already there and already right.
        if plug.isDefaultValue() and not force:
            return {}
        if plug.isCompound:
            data['children'] = [serialize_plug(plug.child(index))
                                for index in range(plug.numChildren())]
        elif plug.isArray:
            # A built-in array - worldMatrix, instObjGroups - is Maya's own bookkeeping.
            return {}
    elif attr_type != attributetypes.kMFnMessageAttribute:
        if plug.isDefaultValue() and not force:
            data['children'] = []
        elif plug.isCompound:
            if plug.isArray:
                element = plug.elementByLogicalIndex(0)
                data['children'] = [serialize_plug(element.child(index))
                                    for index in range(element.numChildren())]
            else:
                data['children'] = [serialize_plug(plug.child(index))
                                    for index in range(plug.numChildren())]
        elif plug.isArray:
            data['children'] = []

    data.update({
        'name': plug.partialName(includeNonMandatoryIndices=True, useLongNames=True,
                                 includeInstancedIndices=True),
        'channelBox': plug.isChannelBox,
        'keyable': plug.isKeyable,
        'locked': plug.isLocked,
        'isArray': plug.isArray,
        'default': attributetypes.maya_type_to_python_type(get_plug_default(plug)),
        'type': attr_type,
        'value': get_python_type_from_plug_value(plug),
        'isElement': plug.isElement,
        'isChild': plug.isChild,
    })

    if attr_type == attributetypes.kMFnkEnumAttribute:
        data['enums'] = get_enum_names(plug)

    if optimize:
        data = _without_defaults(data)
    return data


#: Key to the value that means "this is the ordinary case, leave it out".
_UNINTERESTING = {
    'channelBox': True,
    'keyable': False,
    'locked': False,
    'isArray': False,
    'isElement': False,
    'isChild': False,
    'isDynamic': True,
}


def _without_defaults(data):
    """
    Drop the keys whose value says nothing.

    The version this replaces also popped ``min``, ``max``, ``softMin`` and ``softMax`` here,
    and nothing in ``serialize_plug`` ever set them - the limits are added afterwards, by
    ``attr_utils.serialize_attribute``, after this has returned. Those four pops could not
    fire.

    :param dict data: A serialized plug.
    :return: The same data with the uninteresting keys gone.
    :rtype: dict
    """

    for key, uninteresting_value in _UNINTERESTING.items():
        if data.get(key) is uninteresting_value:
            data.pop(key, None)
    if not data.get('children'):
        data.pop('children', None)
    return data
