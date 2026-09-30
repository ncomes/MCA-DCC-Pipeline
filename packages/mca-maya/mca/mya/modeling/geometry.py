"""
Reference pins: the little shapes a modeller lines a mesh up against.

A skeleton on its own is hard to model to - a joint is a point, and what a modeller needs to
see is roughly how thick the limb is there and which way it bends. So the skeleton is turned
into a row of cylinders and spheres, one per joint, sized from a table, and handed over as a
reference mesh.

What was wrong before:

- **The shape name was executed as code.** ``eval(f'pm.poly{obj_shape}()[0]')``, where
  ``obj_shape`` comes out of a data file. A typo in the table was a ``NameError`` from inside
  an ``eval`` with no context, and anything else in that field ran. The two shapes it can be
  are named now, and a third answers a warning.
- **A missing table was a crash rather than a message.** ``data_dict.get('region_rotations')``
  answers None for a file without that key, and the next line calls ``.keys()`` on it;
  ``ignore_types`` the same, one line further down.
- **The namespace was left at the root rather than put back.** ``make_pins`` sets the
  ``skel_ref`` namespace and ends with ``set_namespace('')``, so a caller that was working
  inside a namespace came back out of it.
- ``pins_grp`` was built and thrown away - the group that holds the pins was not returned, so
  the caller had no handle on it. ``final_pins`` is the group now when the pins are not merged.
- ``apply_cube_trick`` - combine a cube with a mesh, then delete the cube's six faces, to force
  Maya to rebuild the mesh - had no callers anywhere. Gone.
- An f-string with nothing in it: ``n=f'skel_ref_pins'``.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import contexts
from mca.mya.utils import namespace
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The primitives a pin can be, by the name the setup data uses.
PIN_SHAPES = {'Cylinder': pm.polyCylinder, 'Sphere': pm.polySphere}

#: What a joint with no entry in the table gets.
DEFAULT_ROTATE_AXIS = 'rotateZ'
DEFAULT_SIZE = 2
DEFAULT_SHAPE = 'Cylinder'

#: A cylinder is scaled along its length only; its girth is fixed, or a long bone comes out as
#: a barrel.
CYLINDER_GIRTH = 0.15

#: The namespace the reference pins are built in, so they can be found and removed in one go.
PIN_NAMESPACE = 'skel_ref'


def make_pins(joint_list, size_multiplier, data_dict, delete_joint_list=True, merge_pins=False):
    """
    Build a reference pin for each joint in a skeleton.

    :param list joint_list: The joints to build pins for.
    :param float size_multiplier: Scales every pin, so one rig's pins can be made to suit a
        character who is twice the size of the last one.
    :param dict data_dict: The setup data: ``region_rotations`` maps a joint name to
        ``(rotate axis, size, shape)``, and ``ignore_types`` is a list of substrings whose
        joints get no pin.
    :param bool delete_joint_list: Delete the joints once their pins exist.
    :param bool merge_pins: Combine the pins into one mesh rather than grouping them.
    :return: The combined mesh, or the group holding the separate pins.
    :rtype: pm.nt.Transform
    """

    setup_info = data_dict.get('region_rotations') or {}
    ignore_types = data_dict.get('ignore_types') or []
    if not setup_info:
        logger.warning('The setup data has no region_rotations in it, so every pin will be a '
                       'default %s.', DEFAULT_SHAPE)

    created_pins = []
    with contexts.maintain_namespace_context():
        if not merge_pins:
            # Merged pins end up as one mesh with one name, so they need no namespace; separate
            # ones do, to keep a second pass from colliding with the first.
            namespace.set_namespace(PIN_NAMESPACE)

        for each_joint in joint_list:
            joint_name = naming.get_basename(each_joint)
            if any(ignore in joint_name for ignore in ignore_types):
                continue

            rotate_axis, size, obj_shape = setup_info.get(
                joint_name, (DEFAULT_ROTATE_AXIS, DEFAULT_SIZE, DEFAULT_SHAPE))

            # The duplicate is only there to carry the 90 degree turn the table asks for, so
            # the pin can be constrained to it and it can be thrown away.
            dup_bone = pm.duplicate(each_joint, parentOnly=True,
                                    name='{0}_aim'.format(joint_name))[0]
            dup_bone.attr(rotate_axis).set(90)

            pin = create_reference_obj(size, size_multiplier, obj_shape, rotate_axis, joint_name)
            if pin is None:
                pm.delete(dup_bone)
                continue

            pm.delete(pm.parentConstraint(dup_bone, pin, weight=True, maintainOffset=False))
            pm.delete(dup_bone)

            pin.translate.lock()
            created_pins.append(pin)

    if not created_pins:
        logger.warning('No pins were made - every joint given was in ignore_types, or there '
                       'were none.')
        return None

    if merge_pins:
        final_pins = pm.polyUnite(created_pins, name='skel_ref_pins')[0]
        pm.delete(final_pins, constructionHistory=True)
        final_pins.addAttr('ref_pins', at='bool')
    else:
        final_pins = pm.group(created_pins, name='ref_pins_grp')

    if delete_joint_list:
        pm.delete(joint_list)
    return final_pins


def create_reference_obj(size, size_multiplier, obj_shape, rotate_axis, matched_joint_name):
    """
    Build one reference pin, carrying on it everything needed to rebuild it later.

    The four attributes are not decoration: the pin tool reads them back off a mesh a modeller
    has been working on, to know which joint each pin belongs to and how it was made.

    :param float size: The pin's length before the multiplier.
    :param float size_multiplier: Scales the whole pin.
    :param str obj_shape: Which primitive, as named in :data:`PIN_SHAPES`.
    :param str rotate_axis: The axis the joint was turned on, kept for the round trip.
    :param str matched_joint_name: The joint this pin stands for.
    :return: The pin, or None when the shape is not one this knows how to make.
    :rtype: pm.nt.Transform
    """

    if obj_shape not in PIN_SHAPES:
        logger.warning('%s is not a pin shape - it has to be one of %s - so %s got no pin.',
                       obj_shape, sorted(PIN_SHAPES), matched_joint_name)
        return None

    pin = PIN_SHAPES[obj_shape]()[0]
    pin.rename('{0}_ref_pin'.format(matched_joint_name))

    girth = CYLINDER_GIRTH if obj_shape == 'Cylinder' else size * size_multiplier
    pin.scaleX.set(girth)
    pin.scaleY.set(size * size_multiplier)
    pin.scaleZ.set(girth)

    for attr_name, value in (('matchedJoint', matched_joint_name), ('rotatedAxis', rotate_axis),
                             ('objShape', obj_shape)):
        pin.addAttr(attr_name, dt='string')
        pin.attr(attr_name).set(value)
    pin.addAttr('ref_pin', at='bool')
    pin.addAttr('pinSize', at='double')
    pin.pinSize.set(size)
    return pin
