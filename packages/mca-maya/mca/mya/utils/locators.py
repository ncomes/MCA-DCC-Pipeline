"""
Locators: the throwaway markers a rig build leans on.

A locator is the cheapest thing in Maya that has a position and an orientation and can be seen, so
rig code uses them constantly - to hold a place while something else is built, to give an aim
constraint something to point at, to stand in for a control that does not exist yet.

These two builders were in ``rig_utils``, which meant that anything wanting to put a marker
somewhere pulled in 1,752 lines of rig building behind it - and much of ``rig_utils`` needs the
things that wanted the marker. They are small and they are not about rigs; they are here.

What was wrong before:

- **``create_locator_at_object`` answered a locator at the origin when given nothing**, silently. It
  reads as a guard - ``if not obj or not pm.objExists(obj)`` - but what it guards is the caller
  being told. A build that asked for a marker at a node that had been deleted got one at the world
  origin and carried on.
- Both functions are documented as answering a ``pm.nt.Locator``; they answer the locator's
  transform, which is what every caller then moves and parents.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: Added to a locator named after the node it was placed at.
LOCATOR_SUFFIX = '_loc'


def create_locator_at_object(obj, label=None):
    """
    A locator sitting exactly where something else does, facing the same way.

    :param obj: The node to match. The locator lands at the world origin when this is missing,
        which is said in the log rather than left for the caller to notice.
    :param str label: A name for the locator. None names it after ``obj``.
    :return: The locator's transform.
    :rtype: pm.nt.Transform
    """

    locator = pm.spaceLocator(position=[0, 0, 0])

    if not obj or not pm.objExists(obj):
        logger.warning('There is no %s to put a locator at, so %s was left at the origin.',
                       obj, locator)
        if label:
            locator.rename(label)
        return locator

    obj = pm.PyNode(obj)
    locator.rename(label or (naming.get_basename(obj) + LOCATOR_SUFFIX))

    # The rotate order has to match, or matching the rotation will not match the values.
    if obj.hasAttr('rotateOrder'):
        locator.rotateOrder.set(obj.rotateOrder.get())

    # A constraint deleted immediately is the shortest way to say "put this exactly where that is",
    # including everything the node's parents contribute.
    pm.delete(pm.parentConstraint(obj, locator, weight=True, maintainOffset=False))
    return locator


def create_locator_at_point(point, name=None):
    """
    A locator at a position, with no orientation to match.

    :param point: Where to put it, as three numbers or a ``pm.dt.Point``.
    :param str name: A name for the locator.
    :return: The locator's transform.
    :rtype: pm.nt.Transform
    """

    locator = pm.spaceLocator(position=[0, 0, 0])
    if name:
        locator.rename(name)
    locator.translate.set(pm.dt.Point(point))
    return locator
