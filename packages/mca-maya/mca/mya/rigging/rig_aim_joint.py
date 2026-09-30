"""
An aim setup: a control out in front of a joint that the joint looks at.

For an eye, a head, a gun barrel - anything an animator points rather than rotates. The control sits
out along the joint's aim axis, a locator at the joint is aim constrained to it, and the joint
follows that locator. The locator in between is what lets the control keep its own rotation channels
locked and useless to the animator, which is the point: pointing something is a translation, and
giving an animator rotation as well is giving them two ways to do one thing and a way to fight
themselves.

What was wrong before:

- **The up locator was named by string surgery on another locator's name.**
  ``up_loc.rename(up_loc.nodeName().replace('_loc_loc', '_up_loc'))`` - which only works because
  ``create_locator_at_object`` appends ``_loc``, so a locator made from a locator called ``x_loc``
  comes out ``x_loc_loc``. Anything else about either name and the replacement finds nothing and the
  locator keeps the double suffix. It is named outright now.
- **The control was named after the joint's full path.** ``bind_joint.name()`` keeps the namespace
  and, for a non-unique name, the whole DAG path, so a joint in a namespace gave a control with a
  colon in its label for Maya to rewrite.
- **The control was meta-connected to a locator that is deleted three lines later.** ``Flag.create``
  wires the control to what it was built on, both ways, and the thing it was built on here is a
  temporary marker. The connection is asked not to be made now.
- The docstring had ``aim_axis`` and ``up_axis`` described the other way round.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.rigging.flags import frag_flag
from mca.mya.utils import groups
from mca.mya.utils import locators
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: How far out in front of the joint the control is built, before the caller scales it.
DEFAULT_FLAG_DISTANCE = 20

#: An aim control points; it does not turn or scale, and it does not get hidden by hand.
LOCKED_CHANNELS = ('rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v')


def rig_aim_joint(bind_joint,
                  flag_distance=DEFAULT_FLAG_DISTANCE,
                  aim_axis=(1, 0, 0),
                  up_axis=(0, 0, 1),
                  proxy=False):
    """
    Build an aim control for one joint.

    :param pm.nt.Joint bind_joint: The joint that ends up aiming.
    :param float flag_distance: How far out along the aim axis to put the control.
    :param aim_axis: Which axis, in the joint's own space, points at the control.
    :param up_axis: Which axis, in the joint's own space, stays up.
    :param bool proxy: Build the setup but leave the bind joint alone, for a proxy rig that only has
        to look right rather than drive anything.
    :return: The nodes built, under ``bind_joint``, ``flag``, ``rotate_locator``,
        ``rotate_loc_align_grp`` and ``up_locator``.
    :rtype: dict
    """

    joint_name = naming.get_basename(bind_joint)

    # The locator the joint actually follows. The control turns it through an aim constraint, which
    # is what keeps the control's own rotate channels out of the animator's way.
    rotate_loc = locators.create_locator_at_object(bind_joint,
                                                  label='{0}_aim_loc'.format(joint_name))
    up_loc = locators.create_locator_at_object(rotate_loc,
                                              label='{0}_up_loc'.format(joint_name))
    pm.move(up_loc, [value * flag_distance for value in up_axis], objectSpace=True, relative=True)

    rotate_loc_align_grp = groups.create_align_transform(rotate_loc)

    # A marker pushed out along the aim axis, only so the control is built out in front of the joint
    # rather than on top of it. meta_connect is off: it is deleted on the next line, and wiring the
    # control to a node that is about to go leaves the control pointing at nothing.
    object_to_match = locators.create_locator_at_object(bind_joint,
                                                       label='{0}_aim_target'.format(joint_name))
    pm.move(object_to_match, [value * flag_distance for value in aim_axis],
            objectSpace=True, relative=True)
    aim_flag = frag_flag.Flag.create(object_to_match, label='{0}_aim'.format(joint_name),
                                    meta_connect=False)
    pm.delete(object_to_match)

    pm.aimConstraint(aim_flag, rotate_loc, maintainOffset=False, aimVector=aim_axis,
                     upVector=up_axis, worldUpType='object', worldUpObject=up_loc)
    aim_flag.lock_and_hide_attrs(list(LOCKED_CHANNELS))

    if not proxy:
        pm.parentConstraint(rotate_loc, bind_joint, maintainOffset=False)

    return {'bind_joint': bind_joint,
            'flag': aim_flag,
            'rotate_locator': rotate_loc,
            'rotate_loc_align_grp': rotate_loc_align_grp,
            'up_locator': up_loc}
