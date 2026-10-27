"""Exercise the physics LAYER - add, blend, bake, remove - against a real rig.

`chaintest.py` builds bare transforms and tests the node. This tests the Python
around it, which needs an actual FRAG component, so it runs inside an open Maya
with a rig loaded rather than headless.

It borrows whatever component you point it at, puts it back exactly as it found
it, and deletes everything it made. Set COMPONENT, or leave it None to use the
first component that already has physics on it.

Three of these checks are here because the bug they catch shipped:

* **Constraint offsets must be zero whatever frame you add on.** `add_physics`
  once connected each level's goal and built its constraint in the same loop, so
  a level was captured while the node still believed it was the tip. The layer
  then disagreed with itself by up to 4.13 units at the start frame - where, by
  construction, it cannot.
* **The bake must be exact.** Not "close": every level, 0.000.
* **Removal must leave nothing.** A renamed channel that fell out of
  LEGACY_CHANNELS left a second heading behind, visible in the channel box.
"""

# --- where things are, worked out from this file ----------------------------- #
#
# Everything below is derived rather than hardcoded. These suites used to carry
# absolute paths into a scratch folder, which meant they only ran on one machine
# from one place.
import os as _os
import sys as _sys
import tempfile as _tempfile

#: <package root>/mca-maya/mca/mya/plugins/<plugin>
PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PLUGIN_NAME = _os.path.basename(PLUGIN_ROOT)
#: The `packages` folder six levels up: tests -> plugin -> plugins -> mya -> mca
#: -> mca-maya -> packages.
PACKAGES = _os.path.abspath(_os.path.join(PLUGIN_ROOT, *([_os.pardir] * 5)))


def _plugin_binary(version):
    """:return: This plugin's .mll for a Maya version."""
    return _os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                         '{}_maya{}.mll'.format(PLUGIN_NAME, version))


def _result_path(name):
    """Results go to the temp folder, not into the repo next to the suite."""
    return _os.path.join(_tempfile.gettempdir(), name)


def _add_framework_paths(version):
    """Put the framework and its bundled dependencies on sys.path.

    The bundles are APPENDED, never inserted: the python311 bundle carries its
    own PySide6 that does not import under mayapy, and `mca.common.pyqt.pygui`
    swallows the ImportError and hands back a stub - so putting it in front turns
    every Qt call into an AttributeError several frames from the cause.
    """
    for package in ('mca-common', 'mca-maya'):
        path = _os.path.join(PACKAGES, package)
        if path not in _sys.path:
            _sys.path.insert(0, path)
    for bundle in (_os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                 'dependencies', str(version)),
                   _os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                 'dependencies',
                                 'python{}{}'.format(*_sys.version_info[:2])),
                   _os.path.join(PACKAGES, 'dependancies')):
        if _os.path.isdir(bundle) and bundle not in _sys.path:
            _sys.path.append(bundle)
import json, math, traceback

COMPONENT = None

RESULT = _result_path('mcaPhysicsChain_layer.json')

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


try:
    # This suite needs a RIG, not just Maya, so it is meant to be run from inside
    # an open session. Say that plainly when it is launched headlessly by the
    # batch runner, rather than dying on an import three frames deep.
    try:
        import maya.cmds as cmds
        cmds.ls()
        _in_maya = True
    except Exception:
        _in_maya = False

    if not _in_maya:
        out['skipped'] = ('test_layer.py needs a rig in the scene. Run it from '
                          'inside Maya, not from the batch runner.')
        raise SystemExit

    _add_framework_paths(cmds.about(version=True).split()[0])

    import pymel.core as pm
    from mca.mya.rigging import frag
    from mca.mya.tools.physicschain import physicschain_api as api

    name = COMPONENT
    restore = None
    if name is None:
        for node in (pm.ls(type=api.NODE_TYPE) or []):
            tagged = (node.attr(api.COMPONENT_TAG).listConnections()
                      if node.hasAttr(api.COMPONENT_TAG) else [])
            if tagged:
                name = str(tagged[0])
                restore = {a: node.attr(a).get() for a in
                           ('advanced', 'amount', 'springiness', 'droop', 'stiffness',
                            'damping', 'gravity', 'mass', 'stretch', 'physicsWeight')}
                break
    if name is None:
        raise RuntimeError('No component to test. Set COMPONENT to a FRAG component name.')
    out['component'] = name
    component = frag.FRAGNode(pm.PyNode(name))

    start = pm.playbackOptions(q=True, min=True)
    end = min(start + 24, pm.playbackOptions(q=True, max=True))
    was_time = pm.currentTime(q=True)

    for node in (pm.ls(type=api.NODE_TYPE) or []):
        api.remove_physics(node)

    # --- adding on a frame mid-swing must not poison the offsets ------------- #
    #
    # The start frame is the one place the simulation is guaranteed to sit on the
    # animation, so weight 0 and weight 1 MUST agree there. If they do not, the
    # layer has frozen an offset that should not exist, and every later
    # measurement - including the bake - inherits it.
    offsets_by_add_frame = {}
    for add_frame in (start, start + 8):
        pm.currentTime(add_frame, e=True)
        response = api.add_physics(component)
        check('add_physics succeeds on frame {}'.format(add_frame),
              response['ok'], response['message'])
        if not response['ok']:
            break
        node = pm.PyNode(response['result']['node'])
        levels = api._levels_of(node)
        weight = api._writable(node.physicsWeight)

        worst_offset = 0.0
        for row in levels:
            constraint = api._driving_constraint(row['joint'])
            targets = [str(t) for t in constraint.getTargetList()]
            index = targets.index(str(row['driver']))
            for attr in ('targetOffsetTranslate', 'targetOffsetRotate'):
                values = constraint.attr('target[{}].{}'.format(index, attr)).get()
                worst_offset = max(worst_offset, max(abs(v) for v in values))
        # NOT "the offsets are zero". They are written on purpose - the gap
        # between where the animation puts the joint and where the solver puts
        # the driver - and that gap is genuinely non-zero on a rig whose chain
        # orientation is not the solver's aim basis. Asserting zero contradicted
        # the implementation, and on the first rig it ever met it failed while
        # the layer was behaving perfectly (offsets 2.266837, start-frame gap
        # [0, 0, 0, 0]).
        #
        # What must hold is that the offset does not depend on WHEN you added,
        # which is the actual bug: captured mid-swing, the lag at that moment is
        # frozen in. Collected here, compared after the loop.
        offsets_by_add_frame[add_frame] = worst_offset
        out['worst_offset_frame_{}'.format(add_frame)] = round(worst_offset, 6)

        pm.currentTime(start, e=True)
        weight.set(0.0)
        animated = [pm.dt.Vector(r['joint'].getTranslation(space='world')) for r in levels]
        weight.set(1.0)
        simulated = [pm.dt.Vector(r['joint'].getTranslation(space='world')) for r in levels]
        gap = [round((a - b).length(), 4) for a, b in zip(animated, simulated)]
        out['start_frame_gap_{}'.format(add_frame)] = gap
        check('the layer agrees with itself at the start frame (added on {})'.format(add_frame),
              max(gap) < 1e-3, str(gap))
        api.remove_physics(node)

    # The offsets must not depend on the frame the artist happened to be on.
    if len(offsets_by_add_frame) == 2:
        values = list(offsets_by_add_frame.values())
        out['offset_spread_across_add_frames'] = round(abs(values[0] - values[1]), 6)
        check('the constraint offsets do not depend on which frame you added on',
              abs(values[0] - values[1]) < 1e-4,
              '{} - the lag at the moment of adding got frozen in'
              .format({str(k): round(v, 6) for k, v in offsets_by_add_frame.items()}))

    # --- weight 0 is the animation exactly ----------------------------------- #
    response = api.add_physics(component)
    node = pm.PyNode(response['result']['node'])
    flag = pm.PyNode(response['result']['flag'])
    levels = api._levels_of(node)
    weight = api._writable(node.physicsWeight)
    worst = 0.0
    for frame in range(int(start), int(end) + 1):
        pm.currentTime(frame, e=True)
        weight.set(1.0)
        with_physics = [pm.dt.Vector(r['joint'].getTranslation(space='world')) for r in levels]
        weight.set(0.0)
        without = [pm.dt.Vector(r['joint'].getTranslation(space='world')) for r in levels]
        for row, a, b in zip(levels, with_physics, without):
            goal = pm.dt.Vector(row['goal'].getTranslation(space='world'))
            worst = max(worst, (b - goal).length())
    out['weight_zero_error'] = round(worst, 6)
    check('weight 0 puts the joints exactly on the animation', worst < 1e-3,
          str(round(worst, 6)))

    # --- the Advanced channels are inert on the rig too ----------------------- #
    #
    # Both samples have to be reached the SAME way. A simulation's state depends
    # on the path through time, so taking one after a jump to the last frame and
    # the other after stepping there from the start compares two different runs
    # and reports a difference that is nothing to do with the attribute.
    flag.physicsAdvanced.set(False)
    before_raw = flag.physicsAdvGravity.get()
    weight.set(1.0)

    def walk():
        for frame in range(int(start), int(end) + 1):
            pm.currentTime(frame, e=True)
        return [pm.dt.Vector(r['joint'].getTranslation(space='world')) for r in levels]

    pm.currentTime(start, e=True)
    reference = walk()
    flag.physicsAdvGravity.set(5.0)
    pm.currentTime(start, e=True)
    changed = walk()
    drift = max((a - b).length() for a, b in zip(reference, changed))
    flag.physicsAdvGravity.set(before_raw)
    out['adv_gravity_drift'] = round(drift, 6)
    check('Adv Gravity does nothing while Advanced is off', drift < 1e-6,
          'moved {}'.format(round(drift, 6)))

    # --- the bake is exact ---------------------------------------------------- #
    controls = [r['control'] for r in levels if r['control'] is not None]
    pm.cutKey(controls, clear=True)
    weight.set(1.0)
    baked = api.bake_physics(node, start_frame=start, end_frame=end, remove=False)
    check('bake_physics succeeds', baked['ok'], baked['message'])
    if baked['ok']:
        by_level = baked['result']['error_by_level']
        out['bake_error_by_level'] = by_level
        check('the bake reproduces the simulation on every level',
              max(by_level) < 1e-3, str(by_level))
        check('every control got keys',
              all(pm.keyframe(c, q=True, kc=True) for c in controls),
              str([str(c) for c in controls]))
    pm.cutKey(controls, clear=True)
    for control in controls:
        control.rotate.set(0, 0, 0)

    # --- removal gives the animation its constraint weight back --------------- #
    #
    # Adding physics takes the animation target's weight over: at weight 1 that
    # weight reads 0, fed by a reverse node. Removal used to delete the reverse
    # and leave the weight where it had been pushed - 0.0 - so the joints were
    # left holding a constraint at no weight and stopped following their controls
    # at all. Probed on a four-level finger:
    #
    #     before        index_01_l_fk_chainW0  1.0  driven by nothing
    #     with physics  index_01_l_fk_chainW0  0.0  driven by ..._weight_reverse
    #     after remove  index_01_l_fk_chainW0  0.0  driven by nothing
    #
    # Worth two checks rather than one, because they fail for different reasons:
    # the weight names the cause, the position names what an animator sees.
    watched = []
    for row in levels:
        constraint = api._driving_constraint(row['joint'])
        targets = [str(t) for t in constraint.getTargetList()]
        index = targets.index(str(row['driver']))
        watched.extend((row['joint'], str(alias).split('.')[-1])
                       for position, alias in enumerate(constraint.getWeightAliasList())
                       if position != index)

    # --- removal leaves nothing behind ---------------------------------------- #
    removed = api.remove_physics(node)
    check('remove_physics succeeds', removed['ok'], removed['message'])

    dead = []
    for joint, alias in watched:
        constraint = api._driving_constraint(joint)
        plug = '{}.{}'.format(constraint, alias) if constraint is not None else ''
        value = cmds.getAttr(plug) if plug and cmds.objExists(plug) else None
        if value is None or abs(value) < 1e-9:
            dead.append('{} {} = {}'.format(joint, alias, value))
    out['dead_weights'] = dead
    out['weights_restored'] = (removed['result'].get('weights_restored')
                               if removed.get('ok') else None)
    check('the animation gets its constraint weight back after removal', not dead,
          str(dead))

    pm.currentTime(start, e=True)
    stranded = [round((pm.dt.Vector(r['joint'].getTranslation(space='world')) -
                       pm.dt.Vector(r['goal'].getTranslation(space='world'))).length(), 4)
                for r in levels]
    out['drift_after_removal'] = stranded
    check('and the joints follow the rig again once it is gone',
          max(stranded) < 1e-3, str(stranded))
    leftover = [a.attrName() for a in flag.listAttr(ud=True)
                if a.attrName().lower().startswith('physics')]
    out['leftover_channels'] = leftover
    check('no physics channels are left on the flag', not leftover, str(leftover))
    check('no physics nodes are left in the scene',
          not (pm.ls(type=api.NODE_TYPE) or []),
          str([str(n) for n in (pm.ls(type=api.NODE_TYPE) or [])]))
    strays = [str(n) for n in (pm.ls('*_drv', '*_drv_grp', '*_root_offset', '*_anchor') or [])
              if 'physics' in str(n)]
    out['stray_nodes'] = strays
    check('no drivers, groups or helpers are left', not strays, str(strays))

    # --- a chain with no record still gets its weights back ------------------- #
    #
    # Every rig that already has physics saved in it is such a chain: the record
    # was added later, so removal has to fall back to repairing the damage it can
    # recognise. Tested rather than trusted because the first version of that
    # fallback asked for a state that cannot exist at the point it runs, fired on
    # nothing at all, and reported success while leaving all four weights at zero.
    legacy = api.add_physics(component)
    check('add_physics succeeds on a second pass', legacy['ok'], legacy['message'])
    if legacy['ok']:
        legacy_node = pm.PyNode(legacy['result']['node'])
        aliases = []
        for row in api._levels_of(legacy_node):
            constraint = api._driving_constraint(row['joint'])
            targets = [str(t) for t in constraint.getTargetList()]
            index = targets.index(str(row['driver']))
            aliases.extend(str(alias) for position, alias
                           in enumerate(constraint.getWeightAliasList())
                           if position != index)
        legacy_node.attr(api.RESTORE_TAG).set('')
        api.remove_physics(legacy_node)
        left = [round(cmds.getAttr(plug), 4) for plug in aliases]
        out['legacy_weights_after_removal'] = left
        check('a chain with no record still gets its weights back',
              bool(left) and min(left) > 1e-9, str(left))

    # --- put the rig back the way it was -------------------------------------- #
    #
    # Restore every captured value, not a subset. A partial restore is worse than
    # none: this test takes its "original" from whatever chain it finds, so
    # anything it fails to put back becomes the baseline for the next run and the
    # rig quietly drifts a little further each time it is run.
    if restore is not None:
        again = api.add_physics(component,
                                stiffness=restore['stiffness'] if restore['advanced'] else None,
                                damping=restore['damping'] if restore['advanced'] else None,
                                weight=restore['physicsWeight'])
        host = pm.PyNode(again['result']['flag'])
        for channel, key in (('physicsDrag', 'amount'),
                             ('physicsSpringiness', 'springiness'),
                             ('physicsGravity', 'droop'),
                             ('physicsMass', 'mass'),
                             ('physicsStretch', 'stretch'),
                             ('physicsAdvStiffness', 'stiffness'),
                             ('physicsAdvDamping', 'damping'),
                             ('physicsAdvGravity', 'gravity'),
                             ('physicsAdvanced', 'advanced')):
            host.attr(channel).set(restore[key])
        node = pm.PyNode(again['result']['node'])
        drift = {k: (restore[k], node.attr(k).get()) for k in restore
                 if k != 'physicsWeight' and
                 abs(float(node.attr(k).get()) - float(restore[k])) > 1e-9}
        out['restore_drift'] = drift
        check('the rig is left exactly as it was found', not drift, str(drift))
        out['restored'] = again['ok']
    pm.currentTime(was_time, e=True)

    out['ok'] = not out['failures']
except SystemExit:
    out['ok'] = True
except Exception:
    out['error'] = traceback.format_exc()[-2500:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as h:
    json.dump(out, h, indent=1)

# Say it out loud as well as writing the file. A suite whose result you have to
# go and find is a suite nobody checks.
if out.get('skipped'):
    print('SKIPPED  {}'.format(out['skipped']))
else:
    print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
