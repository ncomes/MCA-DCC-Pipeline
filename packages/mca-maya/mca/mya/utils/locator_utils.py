"""
Utils for working with locators
"""
# python imports
# software specific imports
import maya.cmds as cmds
import pymel.core as pm
# MCA python imports
from mca.common import log
from mca.mya.utils import naming, constraint

from mca.mya.rigging import rig_utils, frag
from mca.mya.animation import baking, time_utils

logger = log.MCA_LOGGER


def make_locator_at_objects_cmd():
    """
    Toolbox command to create locators at current selection.

    """

    for obj in pm.selected():
        make_locator_at_object(obj)


def make_locator_at_object(obj, loc_name=None):
    """
    Creates a locator at an objects position and parents it under the layout group.

    :param pm.nt.Transform obj: Object to match
    :param str loc_name: Name to give to the locator, if None use the objects name + _locator suffix
    :return: Returns the created locator.
    :rtype: pm.nt.Transform

    """

    if not loc_name:
        loc_name = f'{naming.get_basename(obj)}_locator'
    loc = rig_utils.create_locator_at_object(obj, label=loc_name)
    if not pm.objExists('loc_grp'):
        cmds.group(n='loc_grp', em=True)
    loc.setParent(pm.PyNode('loc_grp'))

    return loc


def bake_locators_to_selection_cmd():
    """
    Command for baking locators to selection.
    """

    selection = pm.selected()
    start_frame, end_frame = time_utils.get_visible_range()
    bake_locators(selection, start_frame, end_frame)


def bake_locators(object_list, start_frame, end_frame):
    """
    Bakes locators to a list of animated objects for current visible frame range.

    :param list(pm.nt.Transform) object_list: List of objects to have a baked locator created for.
    :param int start_frame: Start frame to bake.
    :param int end_frame: End frame to bake.
    :return: Returns the created locators.
    :rtype: pm.nt.Transform

    """

    locs = []
    constraints = []

    for obj in object_list:
        loc = make_locator_at_object(obj)
        loc.rename(f'{loc}_BAKED')
        locs.append(loc)
        con = constraint.parent_constraint_safe(obj, loc)
        constraints.append(con)

    baking.bake_objects(locs, bake_range=[start_frame, end_frame])
    pm.delete(constraints)
    return locs
