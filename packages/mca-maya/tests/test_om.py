"""
The API layer: mca.mya.utils.om - attributetypes, om_plug, om_utils.

    mayapy tests/test_om.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def check_attribute_types(suite):
    import maya.api.OpenMaya as OpenMaya
    from mca.mya.utils.om import attributetypes as types

    suite.check('a type constant reads back as its own name',
                types.api_type_to_string(types.kMFnDataMatrix) == 'kMFnDataMatrix')
    suite.check('and a number that is not one of them answers empty',
                types.api_type_to_string(9999) == '')
    suite.check('the name table is built from the constants, not written out again',
                len({types.api_type_to_string(value) for value in
                     range(0, 40)} - {''}) >= 33)

    # The bug: this read a table keyed by string names, so it answered None for every unit
    # type - and a transform's translate and rotate are unit attributes.
    suite.check('a distance is recognised',
                types.maya_unit_type_to_internal_type(OpenMaya.MFnUnitAttribute.kDistance)
                == types.kMFnUnitAttributeDistance)
    suite.check('an angle is recognised',
                types.maya_unit_type_to_internal_type(OpenMaya.MFnUnitAttribute.kAngle)
                == types.kMFnUnitAttributeAngle)
    suite.check('a time is recognised',
                types.maya_unit_type_to_internal_type(OpenMaya.MFnUnitAttribute.kTime)
                == types.kMFnUnitAttributeTime)

    suite.check('a numeric type is recognised',
                types.maya_numeric_type_to_internal_type(OpenMaya.MFnNumericData.kDouble)
                == types.kMFnNumericDouble)
    suite.check('a data type is recognised',
                types.maya_mfn_data_type_to_internal_type(OpenMaya.MFnData.kStringArray)
                == types.kMFnDataStringArray)
    suite.check('a type nobody knows answers None',
                types.maya_numeric_type_to_internal_type(-7) is None)

    # A unit value is a value and a unit; JSON wants the number.
    suite.check('a distance becomes a float',
                types.maya_type_to_python_type(OpenMaya.MDistance(2.5)) == 2.5)
    suite.check('an angle becomes a float',
                types.maya_type_to_python_type(OpenMaya.MAngle(1.0)) == 1.0)
    suite.check('a vector becomes a list',
                types.maya_type_to_python_type(OpenMaya.MVector(1, 2, 3)) == [1.0, 2.0, 3.0])
    suite.check('a matrix becomes a list of sixteen',
                len(types.maya_type_to_python_type(OpenMaya.MMatrix())) == 16)
    suite.check('anything else is left alone',
                types.maya_type_to_python_type('a string') == 'a string')

    suite.check('the dead lookups are gone',
                not hasattr(types, 'maya_type_from_api_type') and
                not hasattr(types, 'api_type_from_pymel_type') and
                not hasattr(types, 'MAYA_NUMERIC_MULTI_TYPES'))


def check_type_names_against_maya(suite):
    """
    Every name in the translation table, checked by building the attribute with it.

    This is the check the mapping never had. Three of its entries were wrong: an angle
    translated to 'angle', which Maya does not accept at all; a float array to 'fltMatrix',
    which is a float matrix and an attributeType where the attribute needs a dataType; and
    nine types had no entry, so the caller passed None to addAttr.
    """

    import pymel.core as pm
    from mca.mya.utils.om import attributetypes as types

    harness.new_scene()
    node = pm.createNode('transform', name='type_probe')

    # Every constant this module names, and whether it should translate to something.
    no_maya_name = {types.kMFnNumericAddr, types.kMFnDataMatrixArray,
                    types.kMFnNumeric4Double}
    all_types = [value for name, value in sorted(vars(types).items())
                 if name.startswith('kMFn') and isinstance(value, int)]

    for internal_type in all_types:
        name = types.api_type_to_string(internal_type)
        translated = types.om_type_to_pymel_type(internal_type)
        if internal_type in no_maya_name:
            suite.check('{} has no Maya name, and says so'.format(name), translated is None,
                        repr(translated))
            continue
        if not suite.check('{} translates to something'.format(name), bool(translated)):
            continue

        attribute_name = 'probe_{}'.format(internal_type)
        try:
            if translated == 'enum':
                node.addAttr(attribute_name, type=translated, enumName='first:second')
            elif translated == 'compound':
                node.addAttr(attribute_name, type=translated, numberOfChildren=1)
                node.addAttr(attribute_name + '_child', type='double', parent=attribute_name)
            else:
                node.addAttr(attribute_name, type=translated)
            made = node.hasAttr(attribute_name)
        except Exception as error:
            made = False
            suite.note('failed_{}'.format(name), str(error).splitlines()[0])
        suite.check("{} -> '{}' is a type Maya accepts".format(name, translated), made)


def check_om_plug(suite):
    import pymel.core as pm
    import maya.api.OpenMaya as OpenMaya
    from mca.mya.utils.om import attributetypes as types
    from mca.mya.utils.om import om_plug

    harness.new_scene()
    node = pm.createNode('transform', name='plug_probe')

    plug = om_plug.as_mplug('plug_probe.translateX')
    suite.check('a plug can be found by name', plug is not None)
    suite.check('and it is the right one', plug.partialName(useLongNames=True) == 'translateX')
    plug_through_compound = om_plug.as_mplug('plug_probe.translate.translateX')
    suite.check('a path through a compound works too',
                plug_through_compound.partialName(useLongNames=True) == 'translateX')
    suite.raises('an attribute that is not there raises',
                 om_plug.as_mplug, 'plug_probe.noSuchAttribute')

    # -- the bug: unit attributes had no type ------------------------------------------- #
    suite.check('translateX is a distance, not None',
                om_plug.get_plug_type(om_plug.as_mplug('plug_probe.translateX'))
                == types.kMFnUnitAttributeDistance)
    suite.check('rotateX is an angle, not None',
                om_plug.get_plug_type(om_plug.as_mplug('plug_probe.rotateX'))
                == types.kMFnUnitAttributeAngle)
    suite.check('scaleX is a double',
                om_plug.get_plug_type(om_plug.as_mplug('plug_probe.scaleX'))
                == types.kMFnNumericDouble)
    suite.check('visibility is a bool',
                om_plug.get_plug_type(om_plug.as_mplug('plug_probe.visibility'))
                == types.kMFnNumericBoolean)
    suite.check('translate is a compound',
                om_plug.get_plug_type(om_plug.as_mplug('plug_probe.translate'))
                == types.kMFnCompoundAttribute)
    suite.check('worldMatrix is a matrix',
                om_plug.get_plug_type(om_plug.as_mplug('plug_probe.worldMatrix'))
                == types.kMFnDataMatrix)

    # -- values ------------------------------------------------------------------------ #
    node.translateX.set(4.5)
    node.rotateY.set(90)
    node.addAttr('a_string', type='string')
    node.a_string.set('hello')
    node.addAttr('a_flag', type='bool', defaultValue=False)
    node.a_flag.set(True)
    node.addAttr('a_choice', type='enum', enumName='low:medium:high')
    node.a_choice.set(2)
    node.addAttr('some_numbers', type='doubleArray')
    node.some_numbers.set([1.0, 2.0, 3.0])
    # pymel's type='double3' makes the three children itself - adding them by hand is
    # "Too many children on this compound".
    node.addAttr('a_triple', type='double3')
    node.a_triple.set((1.0, 2.0, 3.0))
    node.addAttr('a_link', type='message')

    def value_of(attribute):
        return om_plug.get_python_type_from_plug_value(
            om_plug.as_mplug('plug_probe.{}'.format(attribute)))

    suite.check('a distance reads back as a number, not an MDistance',
                value_of('translateX') == 4.5, repr(value_of('translateX')))
    suite.check('an angle reads back as a number in radians',
                abs(value_of('rotateY') - 1.5708) < 0.001, repr(value_of('rotateY')))
    suite.check('a string reads back', value_of('a_string') == 'hello')
    suite.check('a bool reads back', value_of('a_flag') is True)
    suite.check('an enum reads back as its index', value_of('a_choice') == 2)
    suite.check('a double array reads back', tuple(value_of('some_numbers')) == (1.0, 2.0, 3.0),
                repr(value_of('some_numbers')))
    # worldMatrix is an array attribute - worldMatrix[0] - so its value is a list holding one
    # matrix, not a matrix.
    world_matrix = value_of('worldMatrix')
    suite.check('an array of matrices reads back as a list of one',
                len(world_matrix) == 1, repr(world_matrix))
    suite.check('and that one is sixteen numbers',
                len(world_matrix[0]) == 16, repr(world_matrix))
    suite.check('a message attribute with nothing wired in reads as None',
                value_of('a_link') is None)

    # The version this replaces dropped anything in a compound that was neither a matrix nor
    # a unit, so a compound of three doubles serialized as an empty list.
    triple = value_of('a_triple')
    suite.check('a compound of three doubles reads back with its three numbers in it',
                list(triple) == [1.0, 2.0, 3.0], repr(triple))
    translate = value_of('translate')
    suite.check('and a compound of three distances gives three numbers',
                [round(one, 3) for one in translate] == [4.5, 0.0, 0.0], repr(translate))

    # -- defaults ---------------------------------------------------------------------- #
    suite.check('a bool default reads back',
                om_plug.get_plug_default(om_plug.as_mplug('plug_probe.a_flag')) is False)
    # A string attribute added with no default has no default object at all - its apiType is
    # kInvalid - which is not the same as a default of ''.
    suite.check('a string attribute with no default says so',
                om_plug.get_plug_default(om_plug.as_mplug('plug_probe.a_string')) is None)
    suite.check('a message attribute has no default',
                om_plug.get_plug_default(om_plug.as_mplug('plug_probe.a_link')) is None)

    # -- enum names -------------------------------------------------------------------- #
    names = om_plug.get_enum_names(om_plug.as_mplug('plug_probe.a_choice'))
    suite.check('an enumeration gives up its field names',
                names == ['low', 'medium', 'high'], str(names))
    suite.check('something that is not an enumeration gives none',
                om_plug.get_enum_names(om_plug.as_mplug('plug_probe.translateX')) == [])

    # -- serialize_plug ---------------------------------------------------------------- #
    data = om_plug.serialize_plug(om_plug.as_mplug('plug_probe.translateX'))
    suite.check('a changed built-in attribute is worth writing down', bool(data), str(data))
    suite.check('and it knows what type it is - the whole bug',
                data.get('type') == types.kMFnUnitAttributeDistance, str(data))
    suite.check('and what it holds', data.get('value') == 4.5, str(data))
    suite.check('a built-in attribute at its default is not written down at all',
                om_plug.serialize_plug(om_plug.as_mplug('plug_probe.translateZ')) == {})
    suite.check('unless forced',
                bool(om_plug.serialize_plug(om_plug.as_mplug('plug_probe.translateZ'),
                                            force=True)))

    data = om_plug.serialize_plug(om_plug.as_mplug('plug_probe.a_choice'))
    suite.check('an enumeration is written down with its field names',
                data.get('enums') == ['low', 'medium', 'high'], str(data))
    suite.check('a dynamic attribute does not carry isDynamic - it is the ordinary case',
                'isDynamic' not in data, str(data))
    suite.check('nor locked, when it is not locked', 'locked' not in data, str(data))

    node.a_flag.lock()
    data = om_plug.serialize_plug(om_plug.as_mplug('plug_probe.a_flag'))
    suite.check('a locked attribute says so', data.get('locked') is True, str(data))
    node.a_flag.unlock()

    unoptimized = om_plug.serialize_plug(om_plug.as_mplug('plug_probe.a_choice'),
                                         optimize=False)
    suite.check('without optimising, every key is there',
                {'isDynamic', 'locked', 'isArray', 'isChild'} <= set(unoptimized),
                str(sorted(unoptimized)))

    # -- what OpenMaya 2.0 still does not have ----------------------------------------- #
    # The float-array reader is a double-array reader because of this. If a future Maya adds
    # it, this check is how we find out.
    suite.check('MFnFloatArrayData is still missing from OpenMaya 2.0, which is why a float '
                'array is read as doubles', not hasattr(OpenMaya, 'MFnFloatArrayData'))


def check_om_utils(suite):
    import pymel.core as pm
    from mca.mya.utils.om import om_utils

    harness.new_scene()
    sphere = pm.polySphere(name='om_sphere', subdivisionsX=8, subdivisionsY=8)[0]

    dag_path, component = om_utils.pynode_to_om2_mobject_mdag_path(sphere)
    suite.check('a DAG node gives up its path', dag_path is not None)
    suite.check('and its object', component is not None)
    suite.check('and the path is the right node',
                'om_sphere' in dag_path.fullPathName(), dag_path.fullPathName())

    not_a_dag_node = pm.createNode('multiplyDivide', name='not_in_the_dag')
    suite.check('a dependency node has no DAG path, and answers a pair of Nones rather '
                'than raising',
                om_utils.pynode_to_om2_mobject_mdag_path(not_a_dag_node) == (None, None))

    # -- closest joint ------------------------------------------------------------------ #
    near = pm.createNode('joint', name='near_joint')
    near.t.set(1, 0, 0)
    far = pm.createNode('joint', name='far_joint')
    far.t.set(-50, 0, 0)

    # Vertex 0 of a default sphere is on the +x side of it, so the near joint wins.
    closest = om_utils.get_closest_joint_to_vertex(0, 'om_sphereShape',
                                                  ['near_joint', 'far_joint'])
    suite.check('the nearer joint is the answer', closest in ('near_joint', 'far_joint'),
                str(closest))
    # Whichever vertex 0 happens to be, moving one joint on top of it must decide it.
    position = pm.pointPosition('om_sphere.vtx[0]', world=True)
    near.t.set(position)
    suite.check('a joint sitting on the vertex is the closest joint',
                om_utils.get_closest_joint_to_vertex(
                    0, 'om_sphereShape', ['near_joint', 'far_joint']) == 'near_joint')
    suite.check('no joints to choose from answers None',
                om_utils.get_closest_joint_to_vertex(0, 'om_sphereShape', []) is None)

    # -- adjacent vertices -------------------------------------------------------------- #
    adjacent = om_utils.get_adjacent_vertices('om_sphereShape.vtx[10]')
    suite.check('a vertex has neighbours', len(adjacent) >= 3, str(adjacent))
    suite.check('and is not its own neighbour', 10 not in adjacent, str(adjacent))
    suite.check('they are indices', all(isinstance(one, int) for one in adjacent))

    for name in ('pynode_list_to_om2_selection_list', 'get_om2_keyframes_from_pynode_list',
                 'get_om2_keyframe_range_from_scene', 'om2_change_curve_start_time'):
        suite.check('{} is gone'.format(name), not hasattr(om_utils, name))


def body(suite):
    harness.add_sibling_packages()
    check_attribute_types(suite)
    check_type_names_against_maya(suite)
    check_om_plug(suite)
    check_om_utils(suite)
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('om', body))
