"""
One name per Maya attribute type, and the translations between the three ways Maya spells
them.

Maya describes an attribute's type three different ways and none of them line up:

- The API splits it across function sets - ``MFnNumericAttribute`` has its own enumeration,
  ``MFnUnitAttribute`` another, ``MFnTypedAttribute`` a third - so "what type is this plug"
  takes four lookups in three different enumerations, and a float and a distance come back as
  unrelated numbers.
- ``addAttr`` wants a *string*, and a different flag depending on the type: ``attributeType``
  for a double, ``dataType`` for a string.
- Those strings are not the ones ``getAttr(type=True)`` answers with, and not all of them are
  accepted where you would expect.

This module gives each type one number of its own - the ``kMFn...`` constants - and the maps
between that and Maya's three spellings. Everything that serializes or rebuilds an attribute
goes through here.

What was wrong before:

- **``maya_unit_type_to_internal_type`` read the wrong table.** It looked its argument up in
  ``_MAYA_TYPE_FROM_TYPE``, which is keyed by *string* names, rather than in
  ``_MAYA_UNIT_TYPE_TO_INTERNAL_TYPE``, which is keyed by the unit enumeration it is given
  and which nothing ever read. So it answered ``None`` for every unit attribute - and a
  transform's ``translate`` and ``rotate`` *are* unit attributes, distance and angle. Every
  serialized transform attribute in the pipeline came out with ``'type': None``, which is
  what ``om_plug.get_plug_type`` handed on and what ``attr_utils.serialize_attribute`` wrote
  into a flag file.
- **``kMFnUnitAttributeAngle`` translated to ``'angle'``, which Maya does not accept.**
  ``addAttr`` answers "Type specified for new attribute is unknown", and pymel's ``type=``
  answers "type not supported". The string is ``'doubleAngle'``. So an angle attribute could
  be read but never rebuilt.
- **``kMFnDataFloatArray`` translated to ``'fltMatrix'``** - a float *matrix*, and an
  ``attributeType`` at that, where the attribute is an array of floats and needs a
  ``dataType``. Rebuilding one made a matrix attribute instead.
- **Nine types had no translation at all**: distance, int, and every array but the float one
  - double, int, point, vector, string and matrix arrays - so ``om_type_to_pymel_type``
  answered ``None`` and the caller passed ``None`` to ``addAttr``.
- ``maya_type_from_api_type`` was documented to take an integer and looked it up in a table
  keyed by strings, so it answered ``(None, None)`` for every call. Nothing called it, and
  nothing called ``api_type_from_pymel_type`` or used ``MAYA_NUMERIC_MULTI_TYPES`` either.
  Gone, with the two tables behind them - 60 lines.
- ``_TYPE_TO_STRING`` was a hand-written list of the constants' own names, 38 lines long and
  one edit away from disagreeing with them. It is built from them now.
- ``kMFnNumericInt64`` and ``kMFnNumericLast`` appeared in no table and had no callers.
"""

# python imports

# software specific imports
import maya.api.OpenMaya as OpenMaya


# The pipeline's own numbering. The values matter only in that they are stable: they are
# written into flag files and rig data, so they must not be renumbered.
kMFnNumericBoolean = 0
kMFnNumericShort = 1
kMFnNumericInt = 2
kMFnNumericLong = 3
kMFnNumericByte = 4
kMFnNumericFloat = 5
kMFnNumericDouble = 6
kMFnNumericAddr = 7
kMFnNumericChar = 8
kMFnUnitAttributeDistance = 9
kMFnUnitAttributeAngle = 10
kMFnUnitAttributeTime = 11
kMFnkEnumAttribute = 12
kMFnDataString = 13
kMFnDataMatrix = 14
kMFnDataFloatArray = 15
kMFnDataDoubleArray = 16
kMFnDataIntArray = 17
kMFnDataPointArray = 18
kMFnDataVectorArray = 19
kMFnDataStringArray = 20
kMFnDataMatrixArray = 21
kMFnCompoundAttribute = 22
kMFnNumeric2Double = 25
kMFnNumeric2Float = 26
kMFnNumeric2Int = 27
kMFnNumeric2Long = 28
kMFnNumeric2Short = 29
kMFnNumeric3Double = 30
kMFnNumeric3Float = 31
kMFnNumeric3Int = 32
kMFnNumeric3Long = 33
kMFnNumeric3Short = 34
kMFnNumeric4Double = 35
kMFnMessageAttribute = 36


#: Each constant's value to its own name, built from the constants rather than written out
#: again beside them.
_TYPE_TO_STRING = {value: name for name, value in sorted(list(globals().items()))
                   if name.startswith('kMFn') and isinstance(value, int)}

#: ``MFnNumericData``'s enumeration to ours.
_MAYA_NUMERIC_TYPE_TO_INTERNAL_TYPE = {
    OpenMaya.MFnNumericData.kBoolean: kMFnNumericBoolean,
    OpenMaya.MFnNumericData.kByte: kMFnNumericByte,
    OpenMaya.MFnNumericData.kShort: kMFnNumericShort,
    OpenMaya.MFnNumericData.kInt: kMFnNumericInt,
    OpenMaya.MFnNumericData.kLong: kMFnNumericLong,
    OpenMaya.MFnNumericData.kDouble: kMFnNumericDouble,
    OpenMaya.MFnNumericData.kFloat: kMFnNumericFloat,
    OpenMaya.MFnNumericData.kAddr: kMFnNumericAddr,
    OpenMaya.MFnNumericData.kChar: kMFnNumericChar,
    OpenMaya.MFnNumericData.k2Double: kMFnNumeric2Double,
    OpenMaya.MFnNumericData.k2Float: kMFnNumeric2Float,
    OpenMaya.MFnNumericData.k2Int: kMFnNumeric2Int,
    OpenMaya.MFnNumericData.k2Long: kMFnNumeric2Long,
    OpenMaya.MFnNumericData.k2Short: kMFnNumeric2Short,
    OpenMaya.MFnNumericData.k3Double: kMFnNumeric3Double,
    OpenMaya.MFnNumericData.k3Float: kMFnNumeric3Float,
    OpenMaya.MFnNumericData.k3Int: kMFnNumeric3Int,
    OpenMaya.MFnNumericData.k3Long: kMFnNumeric3Long,
    OpenMaya.MFnNumericData.k3Short: kMFnNumeric3Short,
    OpenMaya.MFnNumericData.k4Double: kMFnNumeric4Double,
}

#: ``MFnUnitAttribute``'s enumeration to ours. This is the table the broken lookup should
#: have been reading.
_MAYA_UNIT_TYPE_TO_INTERNAL_TYPE = {
    OpenMaya.MFnUnitAttribute.kDistance: kMFnUnitAttributeDistance,
    OpenMaya.MFnUnitAttribute.kAngle: kMFnUnitAttributeAngle,
    OpenMaya.MFnUnitAttribute.kTime: kMFnUnitAttributeTime,
}

#: ``MFnData``'s enumeration to ours.
_MAYA_MFNDATA_TYPE_TO_INTERNAL_TYPE = {
    OpenMaya.MFnData.kString: kMFnDataString,
    OpenMaya.MFnData.kMatrix: kMFnDataMatrix,
    OpenMaya.MFnData.kFloatArray: kMFnDataFloatArray,
    OpenMaya.MFnData.kDoubleArray: kMFnDataDoubleArray,
    OpenMaya.MFnData.kIntArray: kMFnDataIntArray,
    OpenMaya.MFnData.kPointArray: kMFnDataPointArray,
    OpenMaya.MFnData.kVectorArray: kMFnDataVectorArray,
    OpenMaya.MFnData.kStringArray: kMFnDataStringArray,
    OpenMaya.MFnData.kMatrixArray: kMFnDataMatrixArray,
}

#: Ours to the string pymel's ``addAttr(type=...)`` takes. Every entry here was checked
#: against a running Maya by creating the attribute and reading its type back; the suite does
#: the same, so a Maya that changes its mind about one of these is a failing check rather
#: than a rig that rebuilds wrong.
#:
#: Three of our types have no entry, because Maya has no name for them that ``addAttr``
#: takes: ``kMFnNumericAddr`` (a memory address - not something a rig stores),
#: ``kMFnDataMatrixArray``, and ``kMFnNumeric4Double`` - Maya stops at three components, and
#: answering ``'double3'`` for four doubles would quietly build an attribute one component
#: short. ``kMFnNumeric2Int`` and ``kMFnNumeric3Int`` answer ``'long2'`` and ``'long3'``,
#: which is the same 32-bit integer under Maya's own name for it. The float array answers
#: ``'doubleArray'``, which is what it is read back as anyway: ``MFnFloatArrayData`` is
#: missing from OpenMaya 2.0, so there is no way to read a float array as floats.
_OM_TYPE_TO_PM_TYPE = {
    kMFnNumericBoolean: 'bool',
    kMFnNumericByte: 'byte',
    kMFnNumericChar: 'char',
    kMFnNumericShort: 'short',
    kMFnNumericInt: 'long',
    kMFnNumericLong: 'long',
    kMFnNumericFloat: 'float',
    kMFnNumericDouble: 'double',
    kMFnNumeric2Short: 'short2',
    kMFnNumeric3Short: 'short3',
    kMFnNumeric2Long: 'long2',
    kMFnNumeric3Long: 'long3',
    kMFnNumeric2Int: 'long2',
    kMFnNumeric3Int: 'long3',
    kMFnNumeric2Float: 'float2',
    kMFnNumeric3Float: 'float3',
    kMFnNumeric2Double: 'double2',
    kMFnNumeric3Double: 'double3',
    kMFnUnitAttributeDistance: 'doubleLinear',
    kMFnUnitAttributeAngle: 'doubleAngle',
    kMFnUnitAttributeTime: 'time',
    kMFnkEnumAttribute: 'enum',
    kMFnDataString: 'string',
    kMFnDataMatrix: 'matrix',
    kMFnDataFloatArray: 'doubleArray',
    kMFnDataDoubleArray: 'doubleArray',
    kMFnDataIntArray: 'Int32Array',
    kMFnDataPointArray: 'pointArray',
    kMFnDataVectorArray: 'vectorArray',
    kMFnDataStringArray: 'stringArray',
    kMFnCompoundAttribute: 'compound',
    kMFnMessageAttribute: 'message',
}


def api_type_to_string(api_attribute_type):
    """
    The name of one of this module's type constants, for a log line or an error message.

    :param int api_attribute_type: One of the ``kMFn...`` constants.
    :return: Its name, or '' for a number that is not one of them.
    :rtype: str
    """

    return _TYPE_TO_STRING.get(api_attribute_type, '')


def maya_numeric_type_to_internal_type(numeric_type):
    """
    :param int numeric_type: A value from ``OpenMaya.MFnNumericData``.
    :return: The matching constant from this module, or None.
    :rtype: int or None
    """

    return _MAYA_NUMERIC_TYPE_TO_INTERNAL_TYPE.get(numeric_type)


def maya_unit_type_to_internal_type(unit_type):
    """
    :param int unit_type: A value from ``OpenMaya.MFnUnitAttribute`` - ``kDistance``,
        ``kAngle`` or ``kTime``.
    :return: The matching constant from this module, or None.
    :rtype: int or None
    """

    return _MAYA_UNIT_TYPE_TO_INTERNAL_TYPE.get(unit_type)


def maya_mfn_data_type_to_internal_type(data_type):
    """
    :param int data_type: A value from ``OpenMaya.MFnData``.
    :return: The matching constant from this module, or None.
    :rtype: int or None
    """

    return _MAYA_MFNDATA_TYPE_TO_INTERNAL_TYPE.get(data_type)


def om_type_to_pymel_type(om_type):
    """
    The string ``addAttr`` needs to build an attribute of this type.

    :param int om_type: One of this module's constants.
    :return: The type name, or None where Maya has no name for it that ``addAttr`` takes -
        a memory address, a matrix array.
    :rtype: str or None
    """

    return _OM_TYPE_TO_PM_TYPE.get(om_type)


def maya_type_to_python_type(maya_type):
    """
    An API value as something Python can hold and JSON can write.

    Distances, angles and times arrive as ``MDistance``, ``MAngle`` and ``MTime`` - each one
    a value and a unit - and matrices and vectors as their own classes. Everything else is
    already a Python value and comes back untouched.

    :param maya_type: Whatever the API handed over.
    :return: A float for a unit, a list for a matrix or vector, otherwise the argument.
    """

    if isinstance(maya_type, (OpenMaya.MDistance, OpenMaya.MTime, OpenMaya.MAngle)):
        return maya_type.value
    if isinstance(maya_type, (OpenMaya.MMatrix, OpenMaya.MVector, OpenMaya.MPoint,
                              OpenMaya.MQuaternion, OpenMaya.MEulerRotation)):
        return list(maya_type)
    return maya_type
