"""Exercise mcaPhysicsChain as an actual chain.

Runs either under mayapy (it will initialise standalone itself) or pasted into an
open Maya, because a suite that can only run one way is a suite that stops being
run. Everything it creates is deleted on the way out, so it is safe in a working
scene.

Two things this suite learned the hard way, both worth keeping in mind when
adding to it:

**Set `advanced` when tuning with stiffness/damping/gravity.** Those three are
ignored unless it is on. The suite spent a while quietly testing default settings
while appearing to test specific ones, and five checks failed for reasons that
had nothing to do with the node.

**An assertion can pass on an artefact.** The original "lag grows strictly down
the chain" check was written to catch a chain that slid as a rigid body. It did -
but the gradient it measured came from the chain SQUASHING by a third. Once
segment lengths were held, the same physically-correct chain saturated instead,
and the check failed. Both behaviours are right; the assertion has to say which
mode it is talking about.
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


RESULT = _result_path('mcaPhysicsChain_node.json')

out = {'checks': [], 'failures': []}
MADE = []


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


try:
    import maya.cmds as cmds
    try:
        cmds.ls()
        out['context'] = 'inside an open Maya'
    except Exception:
        import maya.standalone
        maya.standalone.initialize(name='python')
        import maya.cmds as cmds
        out['context'] = 'mayapy standalone'

    # Worked out here rather than at import time, because the version is only
    # knowable once Maya is up - and this suite runs under mayapy or inside an
    # already-open Maya, which is the whole point of the block above.
    MLL = _plugin_binary(cmds.about(version=True).split()[0])
    out['mll'] = MLL

    def plugin_loaded():
        for name in ('mcaPhysicsChain', 'mcaPhysicsChain_maya2025'):
            try:
                if cmds.pluginInfo(name, q=True, loaded=True):
                    return True
            except Exception:
                continue
        return False

    if not plugin_loaded():
        cmds.loadPlugin(MLL)

    LEVELS = 6
    SPACING = 5.0

    def build(**attrs):
        """A chain hanging off a root transform, each level SPACING apart in x.

        `advanced` defaults on, because every caller here tunes with the raw
        physics values and those do nothing otherwise.
        """
        node = cmds.createNode('mcaPhysicsChain')
        root = cmds.createNode('transform')
        MADE.extend([node, root])
        drivers = []
        parent = root
        for i in range(LEVELS):
            d = cmds.createNode('transform', parent=parent)
            cmds.setAttr(d + '.translateX', 0 if i == 0 else SPACING)
            cmds.connectAttr(d + '.worldMatrix[0]', '{}.inLevels[{}].goalMatrix'.format(node, i))
            drivers.append(d)
            parent = d
        MADE.append(drivers[0])
        cmds.setAttr(node + '.startTime', 0)
        cmds.setAttr(node + '.advanced', attrs.pop('advanced', 1))
        for name, value in attrs.items():
            cmds.setAttr(node + '.' + name, value)
        return node, root, drivers

    def positions(node):
        return [cmds.getAttr('{}.outLevels[{}].outTranslate'.format(node, i))[0]
                for i in range(LEVELS)]

    def seed(node, root, x=0.0, z=0.0):
        """Park the chain on its goal at the start frame."""
        cmds.setAttr(root + '.translateX', x)
        cmds.setAttr(root + '.translateZ', z)
        cmds.setAttr(node + '.inTime', 0)
        cmds.getAttr(node + '.outLevels[0].outTranslate')

    def advance(node, frames, start=1):
        """Step time FORWARD. dt <= 0 is a reset, so holding time proves nothing."""
        for f in range(start, start + frames):
            cmds.setAttr(node + '.inTime', f)
            cmds.getAttr(node + '.outLevels[0].outTranslate')
        return positions(node)

    def settle(node, root, x, frames, start=1):
        cmds.setAttr(root + '.translateX', x)
        return advance(node, frames, start)

    def segments(pts):
        return [math.sqrt(sum((b[k] - a[k]) ** 2 for k in range(3)))
                for a, b in zip(pts, pts[1:])]

    def angle_between(a, b):
        na = math.sqrt(sum(v * v for v in a))
        nb = math.sqrt(sum(v * v for v in b))
        if na < 1e-9 or nb < 1e-9:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b)) / (na * nb)
        return math.degrees(math.acos(max(-1.0, min(1.0, dot))))

    goal_after = [40.0 + i * SPACING for i in range(LEVELS)]

    # --- it resets to the animation before the start frame ------------------ #
    node, root, drivers = build(stiffness=0.4, damping=0.3)
    cmds.setAttr(node + '.inTime', 0)
    rest = positions(node)
    expected = [i * SPACING for i in range(LEVELS)]
    check('at the start frame every level sits on its goal',
          all(abs(rest[i][0] - expected[i]) < 1e-6 for i in range(LEVELS)),
          str([round(p[0], 3) for p in rest]))
    out['rest'] = [round(p[0], 3) for p in rest]

    # --- the chain lags ------------------------------------------------------ #
    seed(node, root)
    cmds.setAttr(root + '.translateX', 40.0)
    after_one = advance(node, 1)
    lag = [goal_after[i] - after_one[i][0] for i in range(LEVELS)]
    out['lag_after_one_frame'] = [round(v, 3) for v in lag]
    check('every level lags behind the goal', all(v > 0.1 for v in lag), str(lag))
    check('the tip lags at least as much as the root',
          lag[-1] >= lag[0] - 1e-6, '{} vs {}'.format(lag[-1], lag[0]))
    check('the tip lags markedly more than the root',
          lag[-1] > lag[0] * 1.2, '{} vs {}'.format(lag[-1], lag[0]))

    # --- and it catches up ---------------------------------------------------- #
    final = settle(node, root, 40.0, 400, start=2)
    err = [abs(final[i][0] - goal_after[i]) for i in range(LEVELS)]
    out['settle_error'] = [round(v, 4) for v in err]
    check('the whole chain settles on its goal', max(err) < 0.02, str(err))

    # --- orientation aims down the chain --------------------------------------- #
    m = cmds.getAttr('{}.outLevels[0].outMatrix'.format(node))
    aim = (m[0], m[1], m[2])
    check('the root aims down +x at rest', abs(aim[0] - 1.0) < 1e-3, str(aim))
    for i in range(LEVELS):
        rot = cmds.getAttr('{}.outLevels[{}].outRotate'.format(node, i))[0]
        check('level {} rotation is finite'.format(i),
              all(not math.isnan(v) and abs(v) < 1e6 for v in rot), str(rot))

    # --- lag saturates when lengths are held, and grows when they are not ------- #
    #
    # The distinction the original assertion missed. An inextensible chain
    # translated at the root MUST saturate: every level below the first is
    # carried rigidly, so they all lag identically. The progressive gradient only
    # appears when the chain is allowed to squash.
    for stretch, label in ((0.0, 'held'), (1.0, 'free')):
        n, r, _ = build(stiffness=0.5, damping=0.3, stretch=stretch)
        seed(n, r)
        cmds.setAttr(r + '.translateX', 50.0)
        pts = advance(n, 1)
        goals = [50.0 + i * SPACING for i in range(LEVELS)]
        l = [round(goals[i] - pts[i][0], 3) for i in range(LEVELS)]
        segs = [round(v, 3) for v in segments(pts)]
        out['lag_lengths_' + label] = l
        out['segments_' + label] = segs
        if stretch == 0.0:
            check('with lengths held, segments keep their rest length',
                  all(abs(v - SPACING) < 1e-3 for v in segs), str(segs))
            check('with lengths held, lag saturates below the first level',
                  all(abs(v - l[1]) < 1e-3 for v in l[1:]), str(l))
            check('with lengths held, the tip still lags more than the root',
                  l[-1] > l[0] + 1e-3, str(l))
        else:
            check('with lengths free, lag grows strictly down the chain',
                  all(l[i] > l[i - 1] + 1e-4 for i in range(1, LEVELS)), str(l))
            check('with lengths free, segments actually compress',
                  min(segs) < SPACING * 0.95, str(segs))

    # --- the tip is not left on the animation ------------------------------------ #
    #
    # The last level has nothing below it to aim at, and once kept the goal's
    # orientation - so the final flag never moved, however hard the chain swung.
    n, r, _ = build(stiffness=0.3, damping=0.4)
    seed(n, r)
    cmds.setAttr(r + '.translateZ', 60.0)
    advance(n, 6)
    # Compare aim DIRECTIONS, not euler triples: the same orientation has several
    # euler spellings, so componentwise comparison is a coin toss near gimbal.
    pts = positions(n)
    tip_mat = cmds.getAttr('{}.outLevels[{}].outMatrix'.format(n, LEVELS - 1))
    tip_aim = (tip_mat[0], tip_mat[1], tip_mat[2])
    last_segment = [pts[-1][k] - pts[-2][k] for k in range(3)]
    swung = angle_between(last_segment, (1, 0, 0))
    out['tip_aim_vs_segment'] = round(angle_between(tip_aim, last_segment), 3)
    out['tip_swing_from_rest'] = round(swung, 3)
    check('the test actually swung the chain off its rest direction', swung > 5.0,
          '{} degrees'.format(round(swung, 3)))
    check('the tip takes the direction of the segment arriving at it',
          angle_between(tip_aim, last_segment) < 1.0,
          '{} degrees off'.format(out['tip_aim_vs_segment']))
    check('the tip is not left on the animated direction',
          angle_between(tip_aim, (1, 0, 0)) > 5.0,
          '{} degrees'.format(round(angle_between(tip_aim, (1, 0, 0)), 3)))

    # --- up weight changes roll, not whether the chain aims ---------------------- #
    #
    # These were once multiplied together, so turning Up Weight down switched the
    # aim off entirely.
    for up in (0.0, 1.0):
        n, r, _ = build(stiffness=0.3, damping=0.4, upWeight=up)
        seed(n, r)
        cmds.setAttr(r + '.translateZ', 60.0)
        advance(n, 6)
        pts = positions(n)
        worst = 0.0
        for i in range(LEVELS - 1):
            mat = cmds.getAttr('{}.outLevels[{}].outMatrix'.format(n, i))
            to_child = [pts[i + 1][k] - pts[i][k] for k in range(3)]
            worst = max(worst, angle_between((mat[0], mat[1], mat[2]), to_child))
        out['aim_error_upweight_{}'.format(up)] = round(worst, 3)
        check('up weight {} still aims each level at the next'.format(up),
              worst < 1.0, '{} degrees off'.format(round(worst, 3)))

    # --- Drag is monotonic in lag -------------------------------------------------- #
    # Measured at the ROOT, not the tip. Drag maps to stiffness, and the root is
    # the only level whose displacement is purely the spring - everything below
    # it is also being carried by the length constraint and by its parent, so a
    # tip measurement mixes three effects and comes out non-monotonic even when
    # the mapping is perfect. Measured at the tip this read [9.6, 42.5, 23.5].
    drag_lag = []
    for drag in (0.2, 0.5, 0.8):
        n, r, _ = build(advanced=0, amount=drag, springiness=0.5)
        seed(n, r)
        cmds.setAttr(r + '.translateX', 40.0)
        worst = 0.0
        for f in range(1, 25):
            cmds.setAttr(n + '.inTime', f)
            worst = max(worst, 40.0 - positions(n)[0][0])
        drag_lag.append(round(worst, 3))
    out['drag_lag_at_root'] = drag_lag
    check('more Drag means more lag, always',
          all(drag_lag[i] > drag_lag[i - 1] for i in range(1, len(drag_lag))), str(drag_lag))

    # --- Springiness is monotonic in overshoot ------------------------------------- #
    # At the root, for the same reason as Drag. Non-decreasing rather than
    # strictly increasing: the bottom of the range is critically damped, so two
    # low settings can both be legitimately zero, and demanding a strict increase
    # would fail on correct behaviour.
    overshoot = []
    for springiness in (0.0, 0.5, 1.0):
        n, r, _ = build(advanced=0, amount=0.5, springiness=springiness)
        seed(n, r)
        cmds.setAttr(r + '.translateX', 40.0)
        worst = 0.0
        for f in range(1, 80):
            cmds.setAttr(n + '.inTime', f)
            # Past the pose, not merely near it.
            worst = max(worst, positions(n)[0][0] - 40.0)
        overshoot.append(round(worst, 3))
    out['overshoot_at_root'] = overshoot
    check('more Springiness never means less overshoot',
          all(overshoot[i] >= overshoot[i - 1] - 1e-6 for i in range(1, len(overshoot))),
          str(overshoot))
    check('Springiness 1 clearly carries past the pose', overshoot[-1] > 0.05, str(overshoot))
    check('Springiness 0 does not cross the pose', overshoot[0] < 0.05, str(overshoot[0]))

    # --- Gravity reaches vertical --------------------------------------------------- #
    #
    # It once topped out halfway, because the displacement it asked for was
    # linear while the angle it produces is not.
    hang = []
    for gravity in (0.0, 0.5, 1.0):
        n, r, _ = build(advanced=0, amount=0.5, springiness=0.5, droop=gravity)
        seed(n, r)
        advance(n, 160)
        pts = positions(n)
        angles = [angle_between([pts[i + 1][k] - pts[i][k] for k in range(3)], (0, -1, 0))
                  for i in range(LEVELS - 1)]
        hang.append(round(sum(angles) / len(angles), 2))
    out['hang_angle_from_down'] = hang
    check('Gravity 0 leaves the chain on its animated direction', hang[0] > 85.0, str(hang))
    check('Gravity is monotonic toward vertical',
          hang[0] > hang[1] > hang[2], str(hang))
    check('Gravity 1 hangs within 6 degrees of straight down', hang[2] < 6.0, str(hang))

    # --- the Advanced channels are inert while Advanced is off ----------------------- #
    inert = []
    for raw in (0.0, 5.0):
        n, r, _ = build(advanced=0, amount=0.5, springiness=0.5, gravity=raw)
        seed(n, r)
        cmds.setAttr(r + '.translateX', 40.0)
        inert.append([round(v, 6) for v in advance(n, 20)[-1]])
    out['advanced_off'] = inert
    check('raw gravity does nothing while Advanced is off', inert[0] == inert[1], str(inert))

    # --- a stiffness ramp makes the tip looser than the root -------------------- #
    node2, root2, _ = build(stiffness=1.0, damping=0.3, stretch=1.0, useStiffnessRamp=1)
    for index, (pos, value) in enumerate(((0.0, 1.0), (1.0, 0.1))):
        cmds.setAttr('{}.stiffnessRamp[{}].stiffnessRamp_Position'.format(node2, index), pos)
        cmds.setAttr('{}.stiffnessRamp[{}].stiffnessRamp_FloatValue'.format(node2, index), value)
        cmds.setAttr('{}.stiffnessRamp[{}].stiffnessRamp_Interp'.format(node2, index), 1)
    seed(node2, root2)
    cmds.setAttr(root2 + '.translateX', 40.0)
    ramped = advance(node2, 5)
    ramp_lag = [goal_after[i] - ramped[i][0] for i in range(LEVELS)]
    out['ramped_lag'] = [round(v, 3) for v in ramp_lag]
    check('a falling stiffness ramp makes the tip lag more than the root',
          ramp_lag[-1] > ramp_lag[0] + 0.5, str(ramp_lag))

    # --- gravity pulls down ------------------------------------------------------ #
    node3, root3, _ = build(stiffness=0.3, damping=0.9, gravity=2.0, stretch=1.0)
    seed(node3, root3)
    sagged = advance(node3, 80)
    out['sag_y'] = [round(p[1], 3) for p in sagged]
    check('gravity drags the chain down', sagged[-1][1] < -0.5, str(sagged[-1]))
    check('and sags progressively toward the tip',
          all(sagged[i][1] < sagged[i - 1][1] - 1e-4 for i in range(1, LEVELS)),
          str([round(p[1], 3) for p in sagged]))

    # --- limits hold the swing in ------------------------------------------------- #
    node4, root4, _ = build(stiffness=0.15, damping=0.2, limitAngle=10.0)
    seed(node4, root4)
    cmds.setAttr(root4 + '.translateZ', 60.0)
    worst = 0.0
    for f in range(1, 40):
        cmds.setAttr(node4 + '.inTime', f)
        p = positions(node4)
        for i in range(1, LEVELS):
            delta = [p[i][k] - p[i - 1][k] for k in range(3)]
            worst = max(worst, angle_between(delta, (1, 0, 0)))
    out['worst_limit_angle'] = round(worst, 2)
    # A limit test that never swings passes for the wrong reason.
    check('the limit test actually produced a swing', worst > 1.0,
          'only reached {} degrees'.format(worst))
    check('a 10 degree limit is respected', worst <= 10.5, '{} degrees'.format(worst))

    # --- disabled passes the animation straight through ---------------------------- #
    node5, root5, _ = build(stiffness=0.3, enabled=0)
    cmds.setAttr(root5 + '.translateX', 25.0)
    cmds.setAttr(node5 + '.inTime', 30)
    passthrough = positions(node5)
    check('disabled passes the goal through untouched',
          all(abs(passthrough[i][0] - (25.0 + i * SPACING)) < 1e-6 for i in range(LEVELS)),
          str([round(p[0], 3) for p in passthrough]))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-2500:]
    out['ok'] = False
finally:
    try:
        import maya.cmds as cmds
        for n in MADE:
            try:
                if cmds.objExists(n):
                    cmds.delete(n)
            except Exception:
                pass
        out['left_behind'] = [n for n in MADE if cmds.objExists(n)]
    except Exception:
        pass

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as h:
    json.dump(out, h, indent=1)

# Say it out loud as well as writing the file. A suite whose result you have to
# go and find is a suite nobody checks.
print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
