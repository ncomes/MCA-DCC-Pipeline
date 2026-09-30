"""
Animation curves: finding them, trimming them, shifting them, and moving them between attributes.

Everything here works on the curve nodes rather than on the objects, because that is the only
level at which "the animation" is a thing you can hold. :func:`get_anim_curves` is the doorway -
give it flags, joints, or curves and it hands back curves.

What was wrong before:

- **A shift of zero meant "no shift given".** ``change_curve_start_time`` tested
  ``if not shift_length``, so a caller asking for zero - and two of them compute it as
  ``0 - start_frame`` - fell through into the branch that zeroes the animation instead. Then,
  when the animation already began at frame 0 and so needed no shift, it logged *"No keyframes
  were shifted as none were found"*, which is not what happened and sent more than one person
  looking for keys that were there all along.
- **A start time of zero meant "no start time given"**, in ``restore_from_anim_curves``, the
  same way.
- **``reanimate_from_anim_curves`` raised on an end time without a start time.** It entered its
  trimming branch on ``if end_time:`` and then compared every key against ``start_time``, which
  is ``None`` by default: ``TypeError: '<' not supported between 'float' and 'NoneType'``. It
  also could not trim on a start time alone, and trimming a curve down to no keys at all makes
  Maya delete it, which the caller's next line was not expecting.
- **``replace_into_curve`` indexed an empty list.** ``key_time[0]`` on a curve with no keys.
- **``multiply_curve_values`` iterated ``None``** when handed a curve with no keys, and asked
  for a key's value with ``t=frame`` rather than a range, which is not the same query.
- **``restore_from_anim_curves`` only answered with an end frame when it had been given a time
  offset**, though its caller uses the answer to extend the stored end frame either way. It now
  always reports the curve's last key.
- ``restore_from_anim_curves``' ``start_time`` argument was never a start time. It is a distance
  to shift by - its one caller passes the output of ``get_start_time_diff`` - so it is called
  ``time_offset`` here.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.animation import time_utils
from mca.mya.modifiers import ma_decorators


logger = log.MCA_LOGGER

#: Half a frame: small enough never to catch a key that should be kept, large enough to clear one
#: sitting on a sub-frame time.
EDGE = 0.5


# --------------------------------------------------------------------------------------- #
# finding
# --------------------------------------------------------------------------------------- #
def get_anim_curves(node_list):
    """
    Resolve anything key-bearing to the animation curves behind it.

    Accepts a single node or a list, and anim curves themselves pass straight through - callers
    hold a mix of flags, joints and raw curves.

    :param node_list: Node, list of nodes, or anim curve(s).
    :return: The anim curves driving them, de-duplicated.
    :rtype: list(pm.nt.AnimCurve)
    """

    if not node_list:
        return []
    if not isinstance(node_list, (list, tuple, set)):
        node_list = [node_list]

    curves = []
    for node in node_list:
        if isinstance(node, pm.nt.AnimCurve):
            found = [node]
        else:
            found = [pm.PyNode(x) for x in (pm.keyframe(node, q=True, name=True) or [])]
        for curve in found:
            if curve not in curves:
                curves.append(curve)
    return curves


# --------------------------------------------------------------------------------------- #
# trimming and shifting
# --------------------------------------------------------------------------------------- #
@ma_decorators.keep_selection_decorator
@ma_decorators.unlock_animation_layers
def crop_time_range(min_time, max_time, node_list=None, start_to_zero=False):
    """
    Trims the animation on all or given objects to inclusively be the given time range.

    Passing no ``node_list`` crops every curve in the scene. Either bound may be None, which
    leaves that end of the range alone - a caller trimming only the tail should not have to
    invent a start frame.

    :param float min_time: New 1st frame, or None to leave the head alone.
    :param float max_time: New last frame, or None to leave the tail alone.
    :param node_list: Objects (or anim curves) to crop. None means the whole scene.
    :param bool start_to_zero: Shift the result so it begins at frame 0.
    """

    if min_time is None and max_time is None:
        logger.warning('crop_time_range needs at least one of min_time / max_time.')
        return

    # node_list holds objects, not a frame range. This used to call
    # get_keyframe_range_from_nodes, which returns (min, max) floats - those floats were then
    # handed to setKeyframe as if they were nodes, so the trim silently did nothing (or keyed
    # objects named '12.0').
    animcurve_list = get_anim_curves(node_list) if node_list else pm.ls(type=pm.nt.AnimCurve)
    if not animcurve_list:
        logger.warning('No animation curves found to crop.')
        return

    cropped = []
    for anim_curve in animcurve_list:
        if crop_one_curve(anim_curve, min_time, max_time):
            cropped.append(anim_curve)

    if start_to_zero and min_time is not None and cropped:
        change_curve_start_time(cropped, shift_length=min_time * -1)


def crop_one_curve(anim_curve, min_time, max_time):
    """
    Trim one curve, measured against its own keys.

    Each curve is cropped on its own because the bounds that matter are its first and last key,
    not the timeline's. Cutting against the timeline is how this used to hand ``cutKey`` a
    backwards range - which does not trim a curve, it empties it, and an emptied curve is deleted
    by Maya, so the caller's next line failed on a node that had silently ceased to exist.

    A crop that would take every key is refused for the same reason: losing the curve is worse
    than leaving it uncropped, and the caller gets told.

    :param pm.nt.AnimCurve anim_curve: The curve to trim.
    :param float min_time: New 1st frame, or None to leave the head alone.
    :param float max_time: New last frame, or None to leave the tail alone.
    :return: True when the curve survived.
    :rtype: bool
    """

    key_times = sorted(pm.keyframe(anim_curve, q=True) or [])
    if not key_times:
        return False
    first, last = key_times[0], key_times[-1]

    inside = [k for k in key_times
              if (min_time is None or k >= min_time) and (max_time is None or k <= max_time)]
    spans = (min_time is None or min_time <= last) and (max_time is None or max_time >= first)
    if not inside and not spans:
        logger.warning('Not cropping %s to %s-%s: it has no keys in that range and cropping '
                       'would delete the curve.', anim_curve, min_time, max_time)
        return True

    if min_time is not None and min_time > first:
        if min_time < last:
            # Key the new first frame so the crop does not change the pose there.
            pm.setKeyframe(anim_curve, t=min_time, insert=True)
        pm.cutKey(anim_curve, cl=True, t=(first - 1, min_time - EDGE))

    if max_time is not None and max_time < last:
        if max_time > first:
            pm.setKeyframe(anim_curve, t=max_time, insert=True)
        pm.cutKey(anim_curve, cl=True, t=(max_time + EDGE, last + 1))

    if not pm.objExists(anim_curve):
        logger.warning('Cropping to %s-%s emptied a curve, so Maya deleted it.',
                       min_time, max_time)
        return False
    return True


@ma_decorators.unlock_animation_layers
def change_curve_start_time(node_list, shift_length=None):
    """
    Slide every key on the given objects along the timeline.

    ``shift_length=None`` means "put the animation at frame 0", which is what most callers want;
    an explicit distance - including zero - is taken as given.

    :param node_list: An object, list of objects, or anim curves to shift.
    :param float shift_length: How far to shift, or None to move the first key to frame 0.
    :return: The distance actually shifted by.
    :rtype: float
    """

    if not node_list:
        logger.warning('A valid node list is required to shift keys from.')
        return 0

    if shift_length is None:
        if not isinstance(node_list, (list, tuple, set)):
            node_list = [node_list]
        min_frame, _ = time_utils.get_times(node_list)
        shift_length = 0 if min_frame is None else min_frame * -1

    if not shift_length:
        logger.debug('The animation already starts where it was asked to, so nothing was shifted.')
        return 0

    pm.keyframe(node_list, timeChange=shift_length, relative=True)
    return shift_length


# --------------------------------------------------------------------------------------- #
# moving animation between curves
# --------------------------------------------------------------------------------------- #
def replace_into_curve(curve_a, curve_b, delete_curve=False):
    """
    Paste one curve's keys over another's, across the span the source occupies.

    :param pm.nt.AnimCurve curve_a: The curve being copied.
    :param pm.nt.AnimCurve curve_b: The curve receiving the keys.
    :param bool delete_curve: Delete the source once it has been copied.
    :return: True when something was pasted.
    :rtype: bool
    """

    key_times = pm.keyframe(curve_a, q=True) or []
    if not key_times:
        # An empty source has nothing to paste, and pasteKey given an empty time range replaces
        # the destination's keys with nothing.
        logger.debug('%s has no keys, so nothing was pasted into %s.', curve_a, curve_b)
        return False

    pm.copyKey(curve_a)
    pm.pasteKey(curve_b, o='replace', t=[key_times[0], key_times[-1]])
    if delete_curve:
        pm.delete(curve_a)
    return True


def merge_curves(curve_a, curve_b, delete_curves=False):
    """
    Merges two animation curves.

    :param pm.nt.AnimCurve curve_a: The animation curve that is being copied.
    :param pm.nt.AnimCurve curve_b: The animation curve that is receiving the copied curves.
    :param bool delete_curves: Deletes both source curves once merged.
    :return: The merged curve.
    :rtype: pm.nt.AnimCurve
    """

    merged_curve = pm.duplicate(curve_b)[0]

    # Walk curve_a's real key times. Walking range(0, int(max)+1) instead dropped every key on a
    # negative or sub-integer frame, and the old `if value and value != 0` guard threw away every
    # key worth 0.0 - a zeroed translate channel vanished out of the merge.
    for key_time in (pm.keyframe(curve_a, q=True) or []):
        values = pm.keyframe(curve_a, q=True, t=(key_time, key_time), vc=True)
        if not values:
            continue
        pm.setKeyframe(merged_curve, t=key_time, v=values[0])

    if delete_curves:
        pm.delete(curve_a, curve_b)
    return merged_curve


def multiply_curve_values(animation_curve, multi=1.0):
    """
    Scale every key's value on a curve.

    Used to take a normalised pose curve - one that runs 0 to 1 - up to the range a particular
    flag attribute actually uses.

    :param pm.nt.AnimCurve animation_curve: The curve to change.
    :param float multi: What to multiply each key value by.
    :return: How many keys were changed.
    :rtype: int
    """

    changed = 0
    for frame in (pm.keyframe(animation_curve, q=True) or []):
        values = pm.keyframe(animation_curve, q=True, vc=True, t=(frame, frame))
        if not values:
            continue
        pm.keyframe(animation_curve, t=(frame, frame), vc=values[0] * multi)
        changed += 1
    return changed


def restore_from_anim_curves(anim_curve,
                             object_attribute,
                             keep_curves=False,
                             delete_old_curves=False,
                             time_offset=None):
    """
    Hand a stored animation curve back to the attribute it came from.

    Three cases, in order: the attribute has nothing on it, so the curve is simply connected;
    the attribute has a curve and the caller wants it gone, so it is deleted and replaced; or the
    attribute has a curve that must survive, so the keys are pasted on top of it instead.

    :param pm.nt.AnimCurve anim_curve: The stored curve.
    :param pm.nt.Attribute object_attribute: The attribute receiving the animation.
    :param bool keep_curves: Work on a duplicate, leaving the stored curve where it is.
    :param bool delete_old_curves: Delete whatever is already driving the attribute.
    :param float time_offset: Distance to shift the curve by before connecting it. This is a
        distance, not a frame - the caller works it out against its own stored start frame.
    :return: The curve's last key, or None when it has no keys.
    :rtype: float
    """

    if keep_curves:
        anim_curve = pm.duplicate(anim_curve)[0]

    if time_offset:
        change_curve_start_time(anim_curve, time_offset)

    key_times = pm.keyframe(anim_curve, q=True) or []
    end_frame = key_times[-1] if key_times else None

    obj_curve = object_attribute.listConnections(d=False, s=True)
    if not obj_curve or delete_old_curves:
        if obj_curve:
            pm.delete(obj_curve)
        anim_curve.output >> object_attribute
    elif key_times:
        pm.copyKey(anim_curve)
        # A single key is merged rather than replaced: a one frame replace over a full curve
        # would wipe everything either side of that frame.
        operation = 'merge' if len(key_times) == 1 else 'replace'
        pm.pasteKey(obj_curve, o=operation, t=[key_times[0], key_times[-1]])

    return end_frame


def reanimate_from_anim_curves(anim_curve, object_attribute, start_time=None, end_time=None):
    """
    Trim a curve to a range and put it on an attribute, merging with whatever is there.

    Unlike :func:`restore_from_anim_curves` this one always ends with the curve connected: an
    attribute that already has animation gets a curve merged out of both.

    :param pm.nt.AnimCurve anim_curve: The curve to attach.
    :param pm.nt.Attribute object_attribute: The attribute receiving the animation.
    :param float start_time: Trim keys before this frame. None leaves the head alone.
    :param float end_time: Trim keys after this frame. None leaves the tail alone.
    :return: The connected curve, or None when there was nothing to connect.
    :rtype: pm.nt.AnimCurve
    """

    if not anim_curve:
        return None

    if start_time is not None or end_time is not None:
        # crop_one_curve refuses a crop that would take every key, which is what stops Maya
        # deleting the curve out from under the connection below.
        if not crop_one_curve(anim_curve, start_time, end_time):
            logger.warning('Trimming to %s-%s left no curve to connect to %s.',
                           start_time, end_time, object_attribute)
            return None

    obj_curve = object_attribute.listConnections(d=False, s=True)
    if obj_curve:
        anim_curve = merge_curves(anim_curve, obj_curve[0], delete_curves=True)

    anim_curve.output >> object_attribute
    return anim_curve
