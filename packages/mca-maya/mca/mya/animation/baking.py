"""
Baking: turning a rig's evaluated motion into plain keys.

``pm.bakeResults`` is not hard to call, but calling it correctly is. A locked animation layer
swallows the keys. A hidden display layer stops a node evaluating, so it bakes to nothing. A
layer holding a single key reads as a constant over the whole timeline, and baking writes that
constant into every frame. And a freshly baked rotation channel comes out with 360 degree jumps
in it unless it is filtered afterwards. :func:`bake_objects` does all of that, in that order,
around the one call that does the work.

What was wrong before:

- **Baking with ``rotate=False`` zeroed every un-animated rotation.** The Euler filter step ran
  whatever was asked for: it keyed ``rotate`` to 0 at frame -1337 on every node in the list,
  filtered, then cut the key again. On a node whose rotation was not being baked and carried no
  rotation keys, that made a single-key rotation curve worth zero, and cutting its only key left
  the attribute reading back the one value it had ever evaluated to. The rig came back with its
  rotations flattened. The filter now runs only when rotation was actually baked, and only over
  the nodes that have rotation curves to filter.
- **The anchor frame was a magic number that could land inside the animation.** -1337 is outside
  the range until somebody's shot starts at -2000, and ``preserveOutsideKeys`` means keys out
  there are kept on purpose. Worse, the key was cut with a bare ``cutKey(node_list, t=-1337)``,
  which does not name an attribute - so a real key on *any* channel at that frame was deleted
  along with the anchor. The anchor now goes one frame before the earliest key on the curves
  being filtered, which cannot collide with anything by construction, and only the anchor is cut.
- **A nested animation layer lost whatever its parent did not also hold.** The attributes to
  bake were gathered from the base layer's *direct children* only. Animation layers nest, and a
  layer under one of those, holding an attribute its parent does not hold, was never in that
  list - so it was never baked, and was then deleted along with its parent. Checked against the
  old function in a real Maya: with ``translateX`` on the outer layer and ``translateY`` on a
  layer nested under it, ``translateY`` read 9.0 before the merge and 1.0 after it. Every layer
  in the scene is collected now, nested or not.
- **``merge_all_animation_layers`` had no docstring and no return value**, and wrote its guard
  as a one-line ``if ...: return``.
- **A comment naming a different project** sat at the top of the option variables.
"""

# python imports

# software specific imports
import maya.cmds as cmds
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.animation import keyframes
from mca.mya.animation import time_utils
from mca.mya.modifiers import ma_decorators
from mca.mya.utils import attr_utils
from mca.mya.utils import optionvars


logger = log.MCA_LOGGER


class MCABakeOptionVars(optionvars.MCAOptionVars):
    """
    What the bake tools remember between sessions: whether the user has pinned a frame range
    rather than taking the scene's, and what that range is.
    """

    MCAFrameOverride = {'default_value': False,
                        'docstring': 'Whether the pinned range below is used instead of the scene range.'}
    MCAStartFrame = {'default_value': 0, 'docstring': 'First frame of the pinned bake range.'}
    MCAEndFrame = {'default_value': 100, 'docstring': 'Last frame of the pinned bake range.'}


# --------------------------------------------------------------------------------------- #
# baking
# --------------------------------------------------------------------------------------- #
@ma_decorators.make_display_layers_visible_decorator
@ma_decorators.disable_cycle_check_decorator
@ma_decorators.freeze_renderer_decorator
@ma_decorators.undo_decorator
@ma_decorators.keep_selection_decorator
@ma_decorators.unlock_animation_layers
def bake_objects(node_list,
                 translate=True,
                 rotate=True,
                 scale=True,
                 custom_attrs=None,
                 bake_range=None,
                 pok=True,
                 **kwargs):
    """
    Bake the given nodes' evaluated motion onto themselves as keys.

    The decorators above are not decoration. A locked animation layer refuses keys quietly, a
    hidden display layer stops its members evaluating, cycle warnings from a rig mid-bake fill
    the script editor with thousands of lines, and the viewport redrawing once per baked frame
    is most of the wall clock time. Each of those is a bake that silently produces the wrong
    file if it is left out.

    :param node_list: A node or list of nodes to bake.
    :param bool translate: Whether the translation channels are baked.
    :param bool rotate: Whether the rotation channels are baked.
    :param bool scale: Whether the scale channels are baked.
    :param list(str) custom_attrs: Any further attribute names to bake alongside those.
    :param list(float) bake_range: First and last frame to bake. None asks
        :func:`time_utils.get_times` which range the scene means.
    :param bool pok: Preserve keys that sit outside the baked range.
    :param dict kwargs: Passed through to ``pm.bakeResults``.
    :return: The nodes that were baked, empty when there was nothing to do.
    :rtype: list
    """

    node_list = lists.force_list(node_list)
    if not node_list:
        logger.warning('No bakable objects were passed, so nothing was baked.')
        return []

    attr_list = []
    if translate:
        attr_list += attr_utils.TRANSLATION_ATTRS
    if rotate:
        attr_list += attr_utils.ROTATION_ATTRS
    if scale:
        attr_list += attr_utils.SCALE_ATTRS
    if custom_attrs:
        attr_list += lists.force_list(custom_attrs)

    if not attr_list:
        logger.warning('No bakable attributes were asked for, so nothing was baked.')
        return []

    # A layer holding a single key has no slope, so Maya reads it as a constant across the whole
    # timeline - and the bake below would write that constant into every frame.
    keyframes.fix_single_keyframe_layers()

    time_range = bake_range if bake_range is not None else time_utils.get_times(node_list,
                                                                               ignore_selection=True)

    # simulation=True steps the scene frame by frame. Without it Maya evaluates each attribute on
    # its own, and a rig with any history behind it - a solver, a chain of constraints, a dynamic
    # node - either bakes to the wrong values or hangs.
    pm.bakeResults(node_list,
                   simulation=True,
                   at=attr_list,
                   t=time_range,
                   preserveOutsideKeys=pok,
                   **kwargs)

    if rotate:
        euler_filter(node_list)

    return node_list


def euler_filter(node_list):
    """
    Take the 360 degree jumps out of rotation curves.

    Baking samples rotation one frame at a time, and a rig that crosses a gimbal boundary hands
    back a value that is right as a pose and nonsense as a curve: 179 degrees, then -179. Maya's
    Euler filter fixes that, but it has to start from somewhere - given no earlier key it takes
    the first baked frame as its branch, which can leave a whole curve a full turn away from
    zero. A zero keyed before everything else gives it that branch, and is cut again once the
    filter has run.

    The anchor frame is one before the earliest key on the curves being filtered, so it cannot
    land on a key that is meant to be there, and only the rotation channels are cut - the
    predecessor of this function cut every channel at the anchor frame.

    :param node_list: Nodes whose rotation curves should be filtered.
    :return: The nodes that were filtered.
    :rtype: list(pm.nt.Transform)
    """

    rotatable = []
    for node in lists.force_list(node_list):
        node = pm.PyNode(node)
        if not node.hasAttr('rotate'):
            # Not everything bakeable is a transform - a blend shape weight has no rotation.
            continue
        if pm.keyframe(node.rotate, query=True, keyframeCount=True):
            rotatable.append(node)

    if not rotatable:
        return []

    key_times = pm.keyframe(rotatable, query=True, attribute=attr_utils.ROTATION_ATTRS) or []
    anchor = min(key_times) - 1

    pm.setKeyframe(rotatable, time=anchor, attribute='rotate', value=0)
    pm.filterCurve(rotatable, filter='euler')
    pm.cutKey(rotatable, time=(anchor, anchor), attribute=attr_utils.ROTATION_ATTRS)
    logger.debug('Euler filtered %s rotation curves, anchored at frame %s.', len(rotatable), anchor)
    return rotatable


# --------------------------------------------------------------------------------------- #
# animation layers
# --------------------------------------------------------------------------------------- #
@ma_decorators.make_display_layers_visible_decorator
@ma_decorators.disable_cycle_check_decorator
@ma_decorators.freeze_renderer_decorator
@ma_decorators.undo_decorator
@ma_decorators.keep_selection_decorator
def merge_all_animation_layers():
    """
    Flatten every animation layer in the scene down onto the objects themselves.

    Each layer's attributes are baked with the layers resolved out of the stack, which is to say
    baked to the values the animator can see, and the layers are then deleted. Deleting the base
    layer last hands whatever is left in it straight back to the attributes, so the scene ends
    with ordinary animation curves and no layers at all.

    The range baked is the scene's animation range, not the zoomed timeline - a merge that only
    covered what happened to be on screen would quietly truncate the shot.

    :return: The layers that were merged away, the base layer last.
    :rtype: list(str)
    """

    base_layer = cmds.animLayer(query=True, root=True)
    if not base_layer or not cmds.objExists(base_layer):
        logger.debug('The scene has no animation layers, so there was nothing to merge.')
        return []

    # Every layer in the scene bar the base one. Layers nest, and asking the base layer for its
    # children only finds the top row of them.
    layers = [layer for layer in (cmds.ls(type='animLayer') or []) if layer != base_layer]

    if layers:
        attr_list = []
        for layer in layers:
            for attribute in (cmds.animLayer(layer, query=True, attribute=True) or []):
                if attribute and attribute not in attr_list:
                    attr_list.append(attribute)

        if attr_list:
            frame_range = (cmds.playbackOptions(query=True, animationStartTime=True),
                           cmds.playbackOptions(query=True, animationEndTime=True))
            # resolveWithoutLayer asks for the value each attribute would have with those layers
            # taken out of the stack, and removeBakedAttributeFromLayer empties them as it goes.
            pm.bakeResults(attr_list,
                           simulation=True,
                           disableImplicitControl=False,
                           removeBakedAttributeFromLayer=True,
                           sampleBy=1,
                           time=frame_range,
                           resolveWithoutLayer=layers,
                           shape=False)
        pm.delete(layers)

    if cmds.objExists(base_layer):
        pm.delete(base_layer)
        layers.append(base_layer)

    logger.debug('Merged %s animation layers away.', len(layers))
    return layers
