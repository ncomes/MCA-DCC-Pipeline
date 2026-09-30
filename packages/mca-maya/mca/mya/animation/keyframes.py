"""
Keys, and the one thing that has to be done to them before anything else can be.

What was wrong before:

- **The guard read as a version check and was not one.** ``if not len(anim_lyr_list) > 1: return``
  - nothing says why, and what it actually means is "there is at least one layer besides the base
  one", because Maya makes ``BaseAnimation`` as soon as anybody adds a layer. Written as what it
  means now.
- It answered nothing, so a caller had no way to know whether it had done anything.
"""

# python imports

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: Maya's own layer, which every other layer sits under.
BASE_ANIMATION_LAYER = 'BaseAnimation'


def fix_single_keyframe_layers():
    """
    Give every animation layer that holds exactly one key a second one.

    A layer with one key has no slope, and Maya's layer blending reads it as a constant over the
    whole timeline rather than as a value at a frame - so an animator's single corrective pose on a
    layer leaks across the entire shot. Worse, baking a rig with such a layer bakes that leak into
    every frame.

    The second key goes one frame after the first, with the same value, which is enough to make the
    layer read as a two-frame span and nothing else.

    :return: The layers that were fixed.
    :rtype: list(str)
    """

    layers = cmds.ls(type='animLayer') or []
    # One layer is the base layer, which Maya makes as soon as anybody adds a real one. Fewer than
    # two means nobody has added one.
    if len(layers) < 2:
        return []

    fixed = []
    for layer in layers:
        anim_curves = cmds.animLayer(layer, query=True, animCurves=True) or []
        if not anim_curves:
            # A layer with no animation on it has nothing to leak.
            continue

        keyed_frame = None
        for anim_curve in anim_curves:
            times = cmds.keyframe(anim_curve, query=True) or []
            if len(times) != 1:
                keyed_frame = None
                break
            keyed_frame = times[0]

        if keyed_frame is None:
            continue

        members = cmds.animLayer(layer, query=True, attribute=True) or []
        if not members:
            continue

        pm.copyKey(members, animLayer=layer, time=keyed_frame)
        pm.pasteKey(members, animLayer=layer, time=keyed_frame + 1)
        logger.debug('%s held one key, at frame %s, so a second was added at %s.',
                     layer, keyed_frame, keyed_frame + 1)
        fixed.append(layer)
    return fixed
