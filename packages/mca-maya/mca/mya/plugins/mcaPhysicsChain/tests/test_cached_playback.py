"""Does this node survive Cached Playback?

**Run this from inside an open Maya.** Cached Playback fills on idle in an
interactive session; under mayapy there is nothing to fill it, so a headless run
would compare an empty cache against itself and pass without testing anything.

Why this suite is differential rather than a set of assertions about the node:
a caching bug does not crash. It gives you plausible wrong animation - a stale
frame that looks fine on its own and only shows up as a chain that pops when you
scrub back, or a sim whose result depends on how you arrived at frame 40. So the
only honest test is: record the truth with the cache off, then do the same thing
with it on, and demand they are identical.

The trap this suite is written around: if the cache never fills, every
comparison passes and the suite certifies nothing. `cache_frames()` is checked
before any comparison is believed.

Everything it builds lives under one group and is deleted on the way out, and
the evaluator settings are put back the way they were found.
"""

# --- where things are, worked out from this file ----------------------------- #
import os as _os
import sys as _sys
import tempfile as _tempfile

PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PLUGIN_NAME = _os.path.basename(PLUGIN_ROOT)
PACKAGES = _os.path.abspath(_os.path.join(PLUGIN_ROOT, *([_os.pardir] * 5)))


def _plugin_binary(version):
    return _os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                         '{}_maya{}.mll'.format(PLUGIN_NAME, version))


def _result_path(name):
    return _os.path.join(_tempfile.gettempdir(), name)


import json, traceback
import maya.cmds as cmds

RESULT = _result_path('mcaPhysicsChain_cached_playback.json')
GROUP = '__mca_cache_test'
#: Start from an empty scene. Set False to run it in whatever is already open,
#: which is noisier but leaves the scene alone.
NEW_SCENE = True
LEVELS = 5
START, END = 1, 60

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


def cache_frames():
    """
    How many frames the cache evaluator is holding.

    The first version of this parsed digits out of `cacheInfo` strings, which is
    not a flag that exists - so it always returned 0, every comparison passed
    against an empty cache, and the suite certified nothing. `cachedFrames`
    returns [[count, first, last]].

    :return: Number of cached frames.
    :rtype: int
    """

    try:
        ranges = cmds.cacheEvaluator(q=True, cachedFrames=True) or []
    except Exception:
        return 0
    # And the SECOND version summed entry[0], on the belief that it was a frame
    # count. It is not: a fully cached 1-60 comes back as [[1, 1, 60]], where the
    # 1 is the number of contiguous ranges. Summing it reported "1 frame cached"
    # for a full cache and "1" for an almost empty one, which is a number that
    # cannot tell the two apart. Count the frames the ranges actually cover.
    total = 0
    for entry in ranges:
        if not entry or len(entry) < 3:
            continue
        total += int(entry[2]) - int(entry[1]) + 1
    return total


def node_is_cached(node_type='mcaPhysicsChain'):
    """
    :return: True if a node of this type is a caching point.
    :rtype: bool

    `cachingPoints` returns node NAMES. The first version searched them for the
    TYPE name - "is 'mcaPhysicsChain' in 'chainTest_chain'" - which is never
    true unless somebody happens to name a node after its type. It returned
    False in every scene, and the suite asserted `not node_is_cached()` and
    passed, for entirely the wrong reason, while the node's caching behaviour
    went unexamined.
    """

    try:
        points = cmds.cacheEvaluator(q=True, cachingPoints=True) or []
    except Exception:
        return False
    names = {str(n).split('|')[-1] for n in (cmds.ls(type=node_type, long=False) or [])}
    if not names:
        return False
    return any(str(point).split('|')[-1] in names for point in points)


def sample(frames):
    """
    Every level's world position at each frame, walked in the given order.

    :param frames: Frames to visit, in the order to visit them.
    :return: ``{frame: [x, y, z, ...]}``
    :rtype: dict
    """

    readings = {}
    for frame in frames:
        cmds.currentTime(frame)
        cmds.refresh()
        values = []
        for level in range(LEVELS):
            values.extend(cmds.xform('{}|driver{}'.format(GROUP, level),
                                     q=True, ws=True, t=True))
        readings[frame] = values
    return readings


def worst(a, b):
    """
    :return: The largest difference between two samplings, over shared frames.
    :rtype: float
    """

    difference = 0.0
    for frame in sorted(set(a) & set(b)):
        for left, right in zip(a[frame], b[frame]):
            difference = max(difference, abs(left - right))
    return difference


restore = {}
try:
    version = cmds.about(version=True).split()[0]
    out['version'] = version
    if not cmds.pluginInfo('{}_maya{}'.format(PLUGIN_NAME, version), q=True, loaded=True):
        cmds.loadPlugin(_plugin_binary(version))
    check('the plug-in is loaded', True)

    # Put the session back exactly as found, whatever happens below.
    restore['cache'] = cmds.evaluator(q=True, en=True, name='cache')
    restore['em'] = cmds.evaluationManager(q=True, mode=True)[0]
    restore['time'] = cmds.currentTime(q=True)
    restore['min'] = cmds.playbackOptions(q=True, min=True)
    restore['max'] = cmds.playbackOptions(q=True, max=True)
    out['found'] = dict(restore)

    # A fresh scene, so nothing else is feeding the evaluation graph or the
    # cache. With other nodes in the scene a difference could always be argued
    # to have come from somewhere else.
    if NEW_SCENE:
        cmds.file(new=True, force=True)

    cmds.playbackOptions(min=START, max=END)
    cmds.evaluationManager(mode='parallel')

    # --- a chain with no rig in sight ---------------------------------------- #
    if cmds.objExists(GROUP):
        cmds.delete(GROUP)
    group = cmds.createNode('transform', name=GROUP)
    node = cmds.createNode('mcaPhysicsChain', name=GROUP + '_chain', parent=group)

    goals, drivers = [], []
    for level in range(LEVELS):
        goal = cmds.createNode('transform', name='goal{}'.format(level), parent=group)
        driver = cmds.createNode('transform', name='driver{}'.format(level), parent=group)
        cmds.setAttr(goal + '.translateY', -float(level))
        goals.append(goal)
        drivers.append(driver)
        cmds.connectAttr('{}.worldMatrix[0]'.format(goal),
                         '{}.inLevels[{}].goalMatrix'.format(node, level))
        cmds.connectAttr('{}.outLevels[{}].outTranslate'.format(node, level),
                         driver + '.translate')
        cmds.connectAttr('{}.outLevels[{}].outRotate'.format(node, level),
                         driver + '.rotate')

    cmds.connectAttr('time1.outTime', node + '.inTime')
    cmds.setAttr(node + '.enabled', True)
    cmds.setAttr(node + '.startTime', START)
    cmds.setAttr(node + '.amount', 0.6)
    cmds.setAttr(node + '.springiness', 0.7)

    # Swing the root so there is something to lag behind. A chain that never
    # moves cannot show a caching bug.
    root = goals[0]
    for frame, value in ((START, 0.0), (20, 8.0), (40, -8.0), (END, 0.0)):
        cmds.setKeyframe(root, attribute='translateX', time=frame, value=value)

    check('the test chain is built', cmds.objExists(node))

    forward = list(range(START, END + 1))

    # --- ground truth, cache off ---------------------------------------------- #
    cmds.evaluator(name='cache', enable=False)
    cmds.currentTime(START)
    truth = sample(forward)
    out['cache_frames_while_off'] = cache_frames()
    check('nothing is cached while the cache is off', out['cache_frames_while_off'] == 0,
          '{} frames'.format(out['cache_frames_while_off']))
    moved = worst({f: truth[f] for f in truth}, {f: truth[START] for f in truth})
    out['chain_travel'] = round(moved, 4)
    check('the chain actually moves, so a stale frame would show', moved > 1.0,
          'only moved {}'.format(moved))

    # --- the same thing, with Cached Playback switched on ---------------------- #
    #
    # The node IS cached now, and the cached answer has to be the right one.
    #
    # It did not used to be. Declaring kSimulationSupport - the obvious thing for
    # a simulation, and honoured by Maya - meant compute() was never called at
    # all: the cache stored ONE frame, decided it covered the whole range, and
    # served it forever while the goals moved underneath. Not set, the node
    # caches exactly. The story is in getCacheSetup().
    #
    # So these checks are now what they should always have been: does the cache
    # give the right answer.
    cmds.evaluator(name='cache', enable=True)
    cmds.currentTime(START)
    sample(forward)
    import maya.utils
    for _ in range(60):
        maya.utils.processIdleEvents()
    out['cache_frames_with_chain_present'] = cache_frames()
    out['node_is_a_caching_point'] = node_is_cached()

    # Assert the cache is actually doing something before trusting any
    # comparison against it. The first version of this suite compared against an
    # empty cache for a week and passed every time.
    check('the node is a caching point', out['node_is_a_caching_point'],
          'it is not being cached, so nothing below tests caching')
    check('and frames really are cached while it is in the scene',
          out['cache_frames_with_chain_present'] > 0,
          '{} frames cached'.format(out['cache_frames_with_chain_present']))

    with_cache_on = sample(forward)
    out['forward_difference'] = round(worst(truth, with_cache_on), 9)
    check('playing forward with Cached Playback on matches the truth exactly',
          worst(truth, with_cache_on) < 1e-9,
          'off by {}'.format(worst(truth, with_cache_on)))

    # --- an edit mid-range must invalidate everything AFTER it ----------------- #
    #
    # The reason kSimulationSupport exists, handled instead by
    # transformInvalidationRange(). This node carries its state from frame to
    # frame through its own plugs, which is a dependency the DG cannot see -
    # there is no connection saying "frame 45 depends on frame 44". Without the
    # override Maya invalidates only the frames whose inputs changed and keeps
    # the rest, so the chain after an edit is new animation mixed with stale
    # simulation. Measured then: 2.644205 out at frame 40, on a chain travelling
    # 3.496717.
    cmds.setKeyframe(root, attribute='translateX', time=30, value=14.0)
    for _ in range(60):
        maya.utils.processIdleEvents()
    edited_on = sample(forward)
    cmds.evaluator(name='cache', enable=False)
    cmds.currentTime(START)
    edited_off = sample(forward)
    cmds.evaluator(name='cache', enable=True)

    out['after_edit_difference'] = round(worst(edited_on, edited_off), 9)
    check('an edit mid-range invalidates every frame after it, not just its own',
          worst(edited_on, edited_off) < 1e-9,
          'off by {} - the cache is serving stale simulation'
          .format(worst(edited_on, edited_off)))

    # Put the animation back, so the scrub checks below run on the curve the
    # truth above was measured from.
    cmds.cutKey(root, attribute='translateX', time=(30, 30))
    cmds.currentTime(START)
    sample(forward)

    # --- scrubbing and jumping, which the cache makes BETTER than not caching - #
    #
    # This used to compare cache-on against cache-off and expect them equal,
    # because a simulation cannot be integrated backwards: scrub to frame 20
    # from the end and the solver resets rather than rewinding, so the answer
    # differs from playing straight through. That check was written when the
    # node was not cached at all, so "on" and "off" were the same code path and
    # it passed trivially.
    #
    # Now that the cache genuinely holds the forward simulation, jumping to a
    # frame reads the value that frame ACTUALLY had when played through. That is
    # not merely unaffected by caching - it is correct where cache-off is not,
    # and it is the real user-facing win here: an animator can scrub a physics
    # chain and see the true result.
    #
    # Measured on a four-level chain: reverse scrub 0.0 from the forward truth
    # with the cache on, 2.253783548 with it off. Jumping about: 0.0 on,
    # 1.848035656 off.
    def from_the_same_start(frames):
        cmds.currentTime(START)
        sample(forward)
        return sample(frames)

    jumbled = [END, START, 30, 12, 55, 2, 44, 19]
    cmds.evaluator(name='cache', enable=True)
    cmds.currentTime(START)
    sample(forward)
    for _ in range(60):
        maya.utils.processIdleEvents()
    reverse_on = sample(list(reversed(forward)))
    jumps_on = sample(jumbled)

    cmds.evaluator(name='cache', enable=False)
    reverse_off = from_the_same_start(list(reversed(forward)))
    jumps_off = from_the_same_start(jumbled)

    truth_at_jumps = {f: truth[f] for f in jumbled}
    out['reverse_on_vs_truth'] = round(worst(reverse_on, truth), 9)
    out['reverse_off_vs_truth'] = round(worst(reverse_off, truth), 9)
    out['jumps_on_vs_truth'] = round(worst(jumps_on, truth_at_jumps), 9)
    out['jumps_off_vs_truth'] = round(worst(jumps_off, truth_at_jumps), 9)

    check('scrubbing backwards with the cache on gives the forward truth exactly',
          worst(reverse_on, truth) < 1e-9,
          'off by {}'.format(worst(reverse_on, truth)))
    check('jumping about with the cache on gives the forward truth exactly',
          worst(jumps_on, truth_at_jumps) < 1e-9,
          'off by {}'.format(worst(jumps_on, truth_at_jumps)))

    # And the other half of the claim: without the cache it really is wrong, so
    # the two checks above are testing something rather than restating that a
    # simulation is deterministic.
    check('and without the cache it is NOT - which is what the cache buys',
          worst(reverse_off, truth) > 1e-6,
          'reverse scrub matched the truth with the cache off too, so the checks '
          'above prove nothing: {}'.format(worst(reverse_off, truth)))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False

# --- put the session back ------------------------------------------------------ #
try:
    if cmds.objExists(GROUP):
        cmds.delete(GROUP)
    if restore:
        cmds.evaluator(name='cache', enable=restore['cache'])
        cmds.evaluationManager(mode=restore['em'])
        cmds.playbackOptions(min=restore['min'], max=restore['max'])
        cmds.currentTime(restore['time'])
    out['session_restored'] = True
except Exception:
    out['session_restored'] = traceback.format_exc()[-600:]

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1)

print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
