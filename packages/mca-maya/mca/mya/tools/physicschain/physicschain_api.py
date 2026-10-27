"""
Add physics to a rig component that already exists.

A physics chain is not a component of its own. The pony tail is already an
FKComponent with flags an animator keys; this layers secondary motion on top of
that rather than replacing it. The animator keeps their flags, the joints lag
behind them, and a weight of 0 gives back exactly what they animated.

How it attaches
---------------
A FRAG component drives its bind joints with a ``parentConstraint`` from an
internal rig chain. Physics inserts itself as a *second target* on that same
constraint::

    rig chain joint  ---> mcaPhysicsChain ---> physics driver --\\
                                                                 parentConstraint -> bind joint
    rig chain joint ------------------------------------------ /

The two constraint weights are driven from one ``physicsWeight`` attribute as
``w`` and ``1 - w``, so:

* **0** is the animation, untouched and exact - not "close enough".
* **1** is the simulation.
* anything between is a blend, and it is keyable, so physics can be dialled out
  for one shot without unpicking anything.

Nothing is destroyed on the way in, which is what makes :func:`remove_physics`
able to put the rig back exactly as it was.

Where the knobs live
--------------------
Every setting the node has is mirrored onto the component's root flag as a
keyable channel that drives the node. An animator selects the control they were
already holding and tunes physics in the channel box - no hunting through the
Outliner for a node they did not create. The flag is the single source of truth:
the node's own attributes become destinations, so the two cannot disagree.

:Requires: the mcaPhysicsChain plug-in
:Side effects: Creates nodes, adds attributes to a flag, and edits constraints
    on the rig in the open scene.
"""

# python imports
import functools
import json
import math

# software specific imports
import pymel.core as pm
import maya.cmds as cmds
import maya.api.OpenMaya as om2

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

PLUGIN_NAME = 'mcaPhysicsChain'
NODE_TYPE = 'mcaPhysicsChain'

#: Tag connecting a physics node back to the component it was added to, so the
#: pairing survives a save and does not rely on naming.
COMPONENT_TAG = 'mcaPhysicsComponent'
#: Tag marking the driver transforms this module made, so removal knows exactly
#: what it owns and never deletes something a rigger put there.
DRIVER_TAG = 'mcaPhysicsDriver'
#: On a driver: the rig chain joint whose place it is standing in.
GOAL_TAG = 'mcaPhysicsGoal'
#: On a driver: the flag an animator keys to move that goal. Recorded on the way
#: in because it is what :func:`bake_physics` needs, and working it back out
#: afterwards means guessing at rig internals.
CONTROL_TAG = 'mcaPhysicsControl'
#: On a driver: the bind joint it moves. Used to measure a bake against the
#: simulation in the terms an animator sees, rather than against rig internals.
JOINT_TAG = 'mcaPhysicsJoint'
#: On a driver: which level of the chain it is. Message connections come back in
#: no particular order, so the order is stored rather than inferred.
LEVEL_TAG = 'mcaPhysicsLevel'
#: On the node: the flag carrying the channels, so removal can take them off.
HOST_TAG = 'mcaPhysicsHost'
#: On the group and utility nodes this module makes, so removal collects them.
HELPER_TAG = 'mcaPhysicsHelper'
#: On the node: JSON describing what each constraint weight this module took over
#: looked like BEFORE it took it over, so removal can hand it back. Written on the
#: node rather than worked out later because by the time removal runs, the thing
#: that would have to be worked out has already been overwritten. Stored as a
#: string attribute so it survives a save and a reload with the chain.
RESTORE_TAG = 'mcaPhysicsRestore'

ROTATE_CHANNELS = ('rotateX', 'rotateY', 'rotateZ')

#: Marks a channel-box heading rather than a value.
DIVIDER = '__divider__'

#: Channels earlier versions made, removed on the way out so a rebuilt chain does
#: not inherit them. A rig that had physics added before the headings were split
#: ends up with two rows both labelled PHYSICS otherwise - which is what happened.
#: Append to this whenever a channel is renamed; never remove an entry.
LEGACY_CHANNELS = ('physics', 'physicsAmount', 'physicsDroop', 'physicsStiffness',
                   'physicsDamping')

#: What gets mirrored onto the flag, in the order it appears in the channel box.
#: ``(node attribute, channel name, label)``. A node attribute of None means the
#: channel is made here rather than copied - that is ``physicsWeight``, which
#: belongs to this module and not to the node.
FLAG_CHANNELS = (
    (DIVIDER, 'physicsHeading', 'PHYSICS'),
    (None, 'physicsWeight', 'Weight'),
    ('enabled', 'physicsEnabled', 'Enabled'),
    ('amount', 'physicsDrag', 'Drag'),
    ('springiness', 'physicsSpringiness', 'Springiness'),
    # The node calls this one `droop` because `gravity` was already taken by the
    # raw acceleration below. What an animator reads is Gravity; what the code
    # reads is droop. Renaming the node attribute would mean a rebuild and would
    # break every scene that already has a chain in it.
    ('droop', 'physicsGravity', 'Gravity'),
    ('mass', 'physicsMass', 'Mass'),
    ('gravityDirection', 'physicsGravityDir', 'Gravity Dir'),
    ('limitAngle', 'physicsLimitAngle', 'Limit Angle'),
    ('stretch', 'physicsStretch', 'Stretch'),
    ('aimAxis', 'physicsAimAxis', 'Aim Axis'),
    ('upAxis', 'physicsUpAxis', 'Up Axis'),
    ('aimWeight', 'physicsAimWeight', 'Aim Weight'),
    ('upWeight', 'physicsUpWeight', 'Up Weight'),
    ('solveMode', 'physicsSolveMode', 'Solve Mode'),
    ('updateMode', 'physicsUpdateMode', 'Update Mode'),
    ('startTime', 'physicsStartTime', 'Start Time'),
    ('useStiffnessRamp', 'physicsStiffnessRamp', 'Stiffness Ramp'),
    ('useDampingRamp', 'physicsDampingRamp', 'Damping Ramp'),
    ('useMassRamp', 'physicsMassRamp', 'Mass Ramp'),
    ('useGravityRamp', 'physicsGravityRamp', 'Gravity Ramp'),
    ('useAimWeightRamp', 'physicsAimWeightRamp', 'Aim Wt Ramp'),

    # Everything below does nothing until Advanced is on, which is exactly the
    # kind of thing that has to be visible rather than documented. These sat
    # unprefixed in a flat list once, so a dead channel called "Gravity" was
    # three rows from a working one: setting it to 0 looked like it should stop
    # the chain hanging, and nothing happened, because the hang was the other
    # control entirely. The heading and the Adv prefix exist for that reason.
    (DIVIDER, 'physicsAdvancedHeading', 'ADVANCED ONLY'),
    ('advanced', 'physicsAdvanced', 'Advanced'),
    ('stiffness', 'physicsAdvStiffness', 'Adv Stiffness'),
    ('damping', 'physicsAdvDamping', 'Adv Damping'),
    ('gravity', 'physicsAdvGravity', 'Adv Gravity'),
)

#: ``name -> (ramp attribute, the toggle that switches it on)``.
RAMPS = {
    'stiffness': ('stiffnessRamp', 'useStiffnessRamp'),
    'damping': ('dampingRamp', 'useDampingRamp'),
    'mass': ('massRamp', 'useMassRamp'),
    'gravity': ('gravityRamp', 'useGravityRamp'),
    'aimWeight': ('aimWeightRamp', 'useAimWeightRamp'),
}
#: Ramp interpolation, as Maya numbers them.
RAMP_INTERPOLATION = {'none': 0, 'linear': 1, 'smooth': 2, 'spline': 3}

#: Starting points, keyed by NODE attribute name rather than by the label an
#: animator sees: `amount` is Drag, `droop` is Gravity. Drag is how far the chain
#: trails the animation, Springiness is how much it carries past the pose before
#: settling, and Gravity is how far it hangs toward straight down - 0 keeps the
#: animated direction, 1 hangs. All three are scale free, so the same number
#: means the same thing on a short braid and a long tail.
#: Starting points, in the animator's three numbers rather than the solver's. The two
#: curves behind them are ``stiffness = 8 * 256 ** -drag`` and
#: ``damping = 1 - 0.6 * springiness``, so a HIGHER drag is a SOFTER spring and more trail,
#: and a HIGHER springiness is LESS damping and more overshoot. ``droop`` is how hard
#: gravity pulls it down from its goal.
PRESETS = {
    'hair': {'amount': 0.62, 'springiness': 0.5, 'droop': 0.45},
    'pony_tail': {'amount': 0.5, 'springiness': 0.5, 'droop': 0.0},
    'heavy_tail': {'amount': 0.72, 'springiness': 0.25, 'droop': 0.6},
    'antenna': {'amount': 0.34, 'springiness': 0.85, 'droop': 0.0},
    'bouncy': {'amount': 0.55, 'springiness': 0.9, 'droop': 0.0},
    'lag_only': {'amount': 0.42, 'springiness': 0.0, 'droop': 0.0},

    # Hanging fabric - a loin cloth, a tabard, a short skirt panel, a belt sash.
    #
    # Set by the rigger who uses it, after a first pass that reasoned from the curves above
    # and got two of the three numbers wrong. Worth recording why, because both mistakes
    # are the kind anyone would make from the formulas alone:
    #
    # **Gravity stays off.** It reads as the obvious knob for something that hangs, and it
    # is the one to leave alone. See `add_physics`: droop 0.25 already sits about 45 degrees
    # off vertical, 0.5 about 30, 0.75 about 14. The whole useful range is squeezed into
    # roughly the first quarter of the slider, so anything that looks like a sensible
    # number drags the cloth most of the way to straight down. In practice it is turned off
    # and the hang comes from where the flags are posed.
    #
    # **Springiness stays HIGH, not low.** Fabric does lose energy quickly, which argues
    # for heavy damping - but a loin cloth that settles fast reads as rubber. 0.80 leaves
    # damping at 1 - 0.6 * 0.80 = 0.52, so it keeps swinging and bleeds off slowly, which
    # is what a panel of cloth on a moving hip actually does.
    #
    # Drag 0.80 is the one the reasoning got right: 8 * 256 ** -0.80 = 0.095, about a fifth
    # as stiff as `pony_tail`, so the cloth trails well behind the hips instead of chasing
    # them. Move it for the weight of the particular fabric - down towards 0.7 for
    # something stiff like leather, up towards 0.85 for something light.
    'loin_cloth': {'amount': 0.8, 'springiness': 0.8, 'droop': 0.0},
}
DEFAULT_PRESET = 'pony_tail'


def _response(ok, result=None, message=''):
    """
    :param bool ok: Whether the call did what was asked.
    :param result: Whatever the caller wanted back.
    :param str message: One line fit to show a person.
    :return: ``{'ok', 'result', 'message'}``.
    :rtype: dict
    """

    return {'ok': bool(ok), 'result': result, 'message': message}


def _safe(func):
    """
    Turn an exception into a response rather than a traceback in the script
    editor, so a caller can report it and carry on.

    :param func: The function to wrap.
    :return: The wrapped function.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result, message = func(*args, **kwargs)
            return _response(True, result, message)
        except Exception as exc:
            logger.warning('%s failed.', func.__name__, exc_info=True)
            return _response(False, None, '{}: {}'.format(type(exc).__name__, exc))

    return wrapper


def plugin_is_available():
    """
    Load the plug-in if it is not already up.

    Goes through ``plugins.loader`` rather than loading by bare name. The .mll
    lives under ``plugins/mcaPhysicsChain/plug-in/<maya version>/Release`` and is
    not on MAYA_PLUG_IN_PATH by default, so ``loadPlugin('mcaPhysicsChain')``
    fails on a machine that has never loaded it before - which is every machine
    except one where it was loaded by full path during development.

    :return: ``(available, reason)``.
    :rtype: tuple
    """

    from mca.mya.utils import maya_utils
    versioned = '{}_maya{}'.format(PLUGIN_NAME, maya_utils.get_version())
    for name in (versioned, PLUGIN_NAME):
        try:
            if cmds.pluginInfo(name, q=True, loaded=True):
                return True, ''
        except Exception:
            continue

    try:
        from mca.mya.plugins import loader
        if loader.load_physics_chain_plugin():
            return True, ''
    except Exception as exc:
        return False, ('The {} plug-in could not be loaded: {}. It may not have been built for '
                       'this Maya version yet - check plugins/mcaPhysicsChain/plug-in/.'
                       .format(PLUGIN_NAME, exc))
    return False, ('The {} plug-in could not be loaded. Check that it has been built for this '
                   'Maya version under plugins/mcaPhysicsChain/plug-in/.'.format(PLUGIN_NAME))


def _component_label(frag_component):
    """
    A short readable name for a component, fit to build node names from.

    ``str()`` on a FRAG component gives the Python repr, which makes node names
    like ``FKComponent_object_at_0x00000211C18A87D0_physics``. This uses the
    rig's own naming instead.

    :param frag_component: The component.
    :return: Something like ``center_pony_tail``.
    :rtype: str
    """

    side = getattr(frag_component, 'side', None)
    region = getattr(frag_component, 'region', None)
    if side and region:
        return '{}_{}'.format(side, region)
    return str(frag_component.pynode.nodeName()).split(':')[-1]


def _driving_constraint(node):
    """
    The parentConstraint driving a transform, if it has one.

    :param pm.nt.Transform node: The transform.
    :return: The constraint, or None when it is driven some other way.
    :rtype: pm.nt.ParentConstraint or None
    """

    constraints = node.listRelatives(type='parentConstraint') or []
    return constraints[0] if constraints else None


def _control_driving(goal):
    """
    The flag an animator keys to move a rig chain joint.

    The rig chain joint is itself parentConstrained from the flag, so the flag is
    that constraint's first target.

    :param pm.nt.Transform goal: A rig chain joint.
    :return: The flag, or None when nothing obvious drives it.
    :rtype: pm.nt.Transform or None
    """

    constraint = _driving_constraint(goal)
    if constraint is None:
        return None
    targets = constraint.getTargetList()
    return targets[0] if targets else None


def _decompose(matrix):
    """
    A matrix as the translate and XYZ euler degrees a constraint offset wants.

    :param pm.dt.Matrix matrix: The offset.
    :return: ``((tx, ty, tz), (rx, ry, rz))``, degrees.
    :rtype: tuple
    """

    values = [value for row in matrix.get() for value in row]
    transform = om2.MTransformationMatrix(om2.MMatrix(values))
    translate = transform.translation(om2.MSpace.kWorld)
    euler = transform.rotation(asQuaternion=False)
    return ((translate.x, translate.y, translate.z),
            (math.degrees(euler.x), math.degrees(euler.y), math.degrees(euler.z)))


def _derive_axes(goals):
    """
    Which local axis of a rig chain points at the next joint.

    Guessing this is not acceptable. A chain built down -x with the node set to
    +x aims every level backwards, and because the aim basis is what the driver's
    rotation is built from, `maintainOffset` freezes a 180 degree rotation into
    every constraint. The layer then disagrees with itself at the start frame and
    the bake comes out 125 units wrong - all from one default that happened to
    suit the first rig it was tried on.

    :param list goals: The rig chain joints, root first.
    :return: ``(aim, up)`` as the node's axis enum, or ``(None, None)`` when the
        chain is too short or degenerate to tell.
    :rtype: tuple
    """

    if len(goals) < 2:
        return None, None
    parent, child = goals[0], goals[1]
    direction = (pm.dt.Vector(child.getTranslation(space='world')) -
                 pm.dt.Vector(parent.getTranslation(space='world')))
    if direction.length() < 1e-9:
        return None, None
    direction = direction.normal()

    rows = pm.dt.Matrix(parent.worldMatrix[0].get()).get()
    axes = [pm.dt.Vector(rows[k][0], rows[k][1], rows[k][2]).normal() for k in range(3)]
    dots = [direction.dot(axis) for axis in axes]
    best = max(range(3), key=lambda k: abs(dots[k]))

    # The enum runs +x -x +y -y +z -z, so a sign costs one index.
    aim = best * 2 + (0 if dots[best] > 0.0 else 1)
    # Up has to be a different axis; anything perpendicular will do.
    up = 4 if best == 1 else 2
    return aim, up


def _writable(plug):
    """
    Where to write a value, given the node's attributes are driven from a flag.

    Once the channels are on the flag, setting the node directly fails - the plug
    is a destination. The flag channel behind it is the real home for the value,
    so this hops one connection back when there is a settable one.

    :param pm.Attribute plug: The plug that holds the value.
    :return: The plug to write to.
    :rtype: pm.Attribute
    """

    sources = plug.listConnections(source=True, destination=False, plugs=True) or []
    if sources:
        try:
            if sources[0].isSettable():
                return sources[0]
        except Exception:
            pass
    return plug


def _host_flag(physics_node):
    """
    The flag carrying a node's channels.

    :param pm.PyNode physics_node: The physics node.
    :return: The flag, or None.
    :rtype: pm.nt.Transform or None
    """

    if not physics_node.hasAttr(HOST_TAG):
        return None
    hosts = physics_node.attr(HOST_TAG).listConnections() or []
    return hosts[0] if hosts else None


def _levels_of(physics_node):
    """
    What a physics node is driving, in chain order.

    :param pm.PyNode physics_node: The physics node.
    :return: One dict per level with ``level``, ``driver``, ``goal``, ``control``
        and ``joint``.
    :rtype: list
    """

    rows = []
    for driver in (physics_node.message.listConnections() or []):
        if not driver.hasAttr(DRIVER_TAG):
            continue
        goal = driver.attr(GOAL_TAG).listConnections() if driver.hasAttr(GOAL_TAG) else []
        control = driver.attr(CONTROL_TAG).listConnections() if driver.hasAttr(CONTROL_TAG) else []
        joint = driver.attr(JOINT_TAG).listConnections() if driver.hasAttr(JOINT_TAG) else []
        if not joint:
            # An older node, from before the joint was recorded. The driver is a
            # constraint target on the joint, so it can still be found.
            joint = [each.getParent() for each in
                     (driver.listConnections(type='parentConstraint') or [])]
        rows.append({'level': driver.attr(LEVEL_TAG).get() if driver.hasAttr(LEVEL_TAG) else 0,
                     'driver': driver,
                     'goal': goal[0] if goal else None,
                     'control': control[0] if control else None,
                     'joint': joint[0] if joint else None})
    rows.sort(key=lambda row: row['level'])
    return rows


def _world_euler(matrix, node):
    """
    Pull a world rotation out of a matrix in the rotate order a node expects.

    :param pm.dt.Matrix matrix: The world matrix wanted.
    :param pm.nt.Transform node: The node the values are destined for.
    :return: Degrees, in the node's own rotate order.
    :rtype: list
    """

    values = [value for row in matrix.get() for value in row]
    transform = om2.MTransformationMatrix(om2.MMatrix(values))
    euler = transform.rotation(asQuaternion=False)
    euler.reorderIt(node.rotateOrder.get())
    return [math.degrees(euler.x), math.degrees(euler.y), math.degrees(euler.z)]


def _mirror_channel(flag, physics_node, node_attr, channel, label):
    """
    Put one of the node's settings on the flag as a keyable channel.

    The channel is made to match the node's own attribute - type, enum names,
    limits and current value - and then *drives* it. The flag becomes the single
    place the value lives, which is why the node's copy is left as a destination
    rather than being kept in step by hand.

    :param pm.nt.Transform flag: The flag to add the channel to.
    :param pm.PyNode physics_node: The node to mirror.
    :param str node_attr: The attribute on the node.
    :param str channel: The long name to use on the flag.
    :param str label: What an animator reads in the channel box.
    :return: Nothing.
    """

    node_name = str(physics_node)
    flag_name = str(flag)
    source = '{}.{}'.format(node_name, node_attr)
    target = '{}.{}'.format(flag_name, channel)
    kind = cmds.getAttr(source, type=True)

    options = {'longName': channel, 'niceName': label, 'keyable': True}
    if kind == 'enum':
        options['attributeType'] = 'enum'
        options['enumName'] = cmds.attributeQuery(node_attr, node=node_name, listEnum=True)[0]
    elif kind == 'bool':
        options['attributeType'] = 'bool'
    elif kind == 'double3':
        options['attributeType'] = 'double3'
    elif kind == 'time':
        options['attributeType'] = 'time'
    else:
        options['attributeType'] = 'double'
        for exists, key, option in (('minExists', 'minimum', 'minValue'),
                                    ('maxExists', 'maximum', 'maxValue')):
            try:
                if cmds.attributeQuery(node_attr, node=node_name, **{exists: True}):
                    options[option] = cmds.attributeQuery(node_attr, node=node_name,
                                                          **{key: True})[0]
            except Exception:
                pass

    cmds.addAttr(flag_name, **options)
    if kind == 'double3':
        # The channel box shows the children, not the parent, so naming only the
        # parent leaves three rows reading "Physics Gravity Dir X/Y/Z" under a
        # heading that says something else entirely.
        for axis in 'XYZ':
            cmds.addAttr(flag_name, longName='{}{}'.format(channel, axis),
                         niceName='{} {}'.format(label, axis), attributeType='double',
                         parent=channel, keyable=True)

    # Carry the node's current value across before handing it control, so adding
    # the channels never changes how the chain behaves.
    value = cmds.getAttr(source)
    if kind == 'double3':
        cmds.setAttr(target, value[0][0], value[0][1], value[0][2], type='double3')
    else:
        cmds.setAttr(target, value)
    cmds.connectAttr(target, source, force=True)


def _strip_channels(flag):
    """
    Take the physics channels back off a flag.

    :param pm.nt.Transform flag: The flag.
    :return: How many channels were removed.
    :rtype: int
    """

    removed = 0
    for channel in [entry[1] for entry in FLAG_CHANNELS] + list(LEGACY_CHANNELS):
        if not flag.hasAttr(channel):
            continue
        try:
            plug = flag.attr(channel)
            plug.unlock()
            pm.deleteAttr(plug)
            removed += 1
        except Exception:
            logger.debug('Could not remove %s.%s', flag, channel, exc_info=True)
    return removed



def _weight_record(alias):
    """
    What a constraint weight looks like before this module takes it over.

    :param alias: The weight alias plug.
    :return: ``{'alias', 'value', 'source'}`` - the attribute name, its value,
        and the plug feeding it if anything was.
    :rtype: dict
    """

    name = str(alias)
    incoming = cmds.listConnections(name, source=True, destination=False, plugs=True) or []
    try:
        value = float(cmds.getAttr(name))
    except Exception:
        value = 1.0
    return {'alias': name.split('.')[-1], 'value': value,
            'source': incoming[0] if incoming else ''}


def _read_restore(node):
    """
    The records :func:`add_physics` wrote, or an empty list for a chain built
    before they existed.

    :param node: The physics node.
    :return: ``[{'alias', 'value', 'source'}]``.
    :rtype: list
    """

    if not node.hasAttr(RESTORE_TAG):
        return []
    try:
        return json.loads(node.attr(RESTORE_TAG).get() or '[]') or []
    except (ValueError, TypeError):
        logger.debug('The restore record on %s could not be read.', node, exc_info=True)
        return []


def _restore_weight(constraint, record):
    """
    Put one weight back the way it was found.

    The connection goes back if the thing that fed it is still there, and the
    plain value goes back if it is not - which is the common case, because an
    unanimated constraint weight is a value and nothing else.

    :param constraint: The constraint node.
    :param dict record: One entry from :func:`_read_restore`.
    :return: Whether anything was put back.
    :rtype: bool
    """

    plug = '{}.{}'.format(constraint, record.get('alias'))
    if not cmds.objExists(plug):
        return False
    # Ours has to come off first, or setting the value fails on a connected plug
    # and reconnecting silently keeps the wrong source.
    for source in (cmds.listConnections(plug, source=True, destination=False,
                                        plugs=True) or []):
        try:
            cmds.disconnectAttr(source, plug)
        except Exception:
            logger.debug('Could not disconnect %s from %s.', source, plug, exc_info=True)
    source = record.get('source') or ''
    try:
        if source and cmds.objExists(source):
            cmds.connectAttr(source, plug, force=True)
        else:
            cmds.setAttr(plug, record.get('value', 1.0))
    except Exception:
        logger.warning('Could not put %s back to how it was found.', plug, exc_info=True)
        return False
    return True


def _restore_weights(node, constraints):
    """
    Hand the animation its constraint weights back.

    **Removing the physics layer used to leave every joint it touched driven by
    nothing at all.** Adding physics replaces the incoming connection on the
    animation target's weight with ``reverse.outputX``, so at weight 1 that
    weight reads 0.0. Delete the reverse node on the way out and the plug simply
    keeps the last value it was fed - zero - and the constraint holds the joint
    at a weight of nothing. Probed on a four-level finger:

    ====================  =====  ==========================
    state                 weight driven by
    ====================  =====  ==========================
    before                1.0    nothing
    with physics          0.0    ..._weight_reverse.outputX
    after remove (before) 0.0    nothing
    after remove (now)    1.0    nothing
    ====================  =====  ==========================

    The finger stopped following its FK controls at all, and drifted about two
    units per add/remove cycle. That drift is why every physics-chain
    measurement taken before this was found was irreproducible: the rig was a
    slightly different rig by the second run.

    :param node: The physics node being removed.
    :param list constraints: The constraints its drivers were detached from.
    :return: How many weights were put back.
    :rtype: int
    """

    records = {}
    for record in _read_restore(node):
        records.setdefault(record.get('alias'), record)

    # What this module put on those weights, so the fallback below can tell our
    # own connection from a rigger's.
    ours = {str(each) for each in (node.listConnections(type='reverse') or [])}
    ours.add(str(node))

    restored = 0
    for constraint in constraints:
        if not pm.objExists(constraint):
            continue
        try:
            aliases = constraint.getWeightAliasList()
        except Exception:
            logger.debug('Could not read the weights on %s.', constraint, exc_info=True)
            continue

        known = [alias for alias in aliases if str(alias).split('.')[-1] in records]
        for alias in known:
            if _restore_weight(constraint, records[str(alias).split('.')[-1]]):
                restored += 1
        if known:
            continue

        # A chain built before the record existed has nothing to read, and the
        # joint it leaves behind is just as dead - so every rig with physics
        # already saved in it needs this. One target left, reading zero, fed by
        # nothing but this module, is not a state anything else here produces.
        #
        # The first version of this asked for a weight "fed by nothing", which is
        # true only AFTER the reverse node is deleted - and this runs before that,
        # on purpose. So it never fired once, silently, and the weights it was
        # written to rescue stayed at 0.0 while the count said 0 and nothing
        # complained. Another check that passed on the wrong thing.
        if len(aliases) != 1:
            continue
        plug = str(aliases[0])
        sources = cmds.listConnections(plug, source=True, destination=False) or []
        if any(source not in ours for source in sources):
            continue
        try:
            if abs(cmds.getAttr(plug)) > 1e-9:
                continue
            for source in (cmds.listConnections(plug, source=True, destination=False,
                                                plugs=True) or []):
                cmds.disconnectAttr(source, plug)
            cmds.setAttr(plug, 1.0)
        except Exception:
            logger.debug('Could not repair %s.', plug, exc_info=True)
            continue
        restored += 1
        logger.info('%s was left at 0 by an older version of this tool; set back to 1.', plug)
    return restored


@_safe
def expose_on_flag(physics_node, flag):
    """
    Mirror every setting the node has onto a flag as keyable channels.

    Called by :func:`add_physics`; separate so an older chain can be brought up
    to date without being rebuilt.

    :param physics_node: The physics node or its name.
    :param flag: The flag to put the channels on.
    :return: Response listing the channels made.
    :rtype: dict
    """

    node = pm.PyNode(physics_node)
    control = pm.PyNode(flag)
    control_name = str(control)

    existing = [channel for _, channel, _ in FLAG_CHANNELS if control.hasAttr(channel)]
    if existing:
        raise ValueError('{} already carries physics channels ({}...). Remove that physics layer '
                         'first.'.format(control, existing[0]))

    made = []
    for node_attr, channel, label in FLAG_CHANNELS:
        if node_attr == DIVIDER:
            # A locked enum draws a heading in the channel box and nothing else.
            cmds.addAttr(control_name, longName=channel, niceName=label,
                         attributeType='enum', enumName='--------', keyable=False)
            cmds.setAttr('{}.{}'.format(control_name, channel), channelBox=True, lock=True)
            made.append(channel)
            continue
        if node_attr is None:
            # physicsWeight belongs to this module, not the node, so it is made
            # rather than mirrored - but it lives on the flag like the rest.
            cmds.addAttr(control_name, longName=channel, niceName=label,
                         attributeType='double', minValue=0.0, maxValue=1.0,
                         defaultValue=node.physicsWeight.get(), keyable=True)
            cmds.setAttr('{}.{}'.format(control_name, channel), node.physicsWeight.get())
            cmds.connectAttr('{}.{}'.format(control_name, channel),
                             '{}.physicsWeight'.format(node), force=True)
        else:
            _mirror_channel(control, node, node_attr, channel, label)
        made.append(channel)

    # Read every mirrored channel back and check it still matches the node.
    #
    # Adding the channels is supposed to change nothing - the value is carried
    # across before the connection is made - so any disagreement here means the
    # mirroring got it wrong. A chain was once found carrying a gravity direction
    # of (0, -1500, 0) where the node's default is (0, -1, 0); it could not be
    # reproduced on a fresh build, and a silent wrong value on a channel nobody
    # looks at is exactly the kind of thing that wastes an afternoon later.
    for node_attr, channel, _ in FLAG_CHANNELS:
        if node_attr is None or node_attr == DIVIDER:
            continue
        try:
            mirrored = cmds.getAttr('{}.{}'.format(control_name, channel))
            original = cmds.getAttr('{}.{}'.format(node, node_attr))
            if mirrored != original:
                logger.warning('%s.%s came out as %s but %s.%s is %s.',
                               control_name, channel, mirrored, node, node_attr, original)
        except Exception:
            logger.debug('Could not verify %s.', channel, exc_info=True)

    if not node.hasAttr(HOST_TAG):
        node.addAttr(HOST_TAG, at='message')
    control.message >> node.attr(HOST_TAG)

    return ({'flag': str(control), 'channels': made},
            'Put {} physics channels on {}.'.format(len(made), control))


@_safe
def add_physics(component, weight=1.0, drag=None, springiness=None, gravity=None,
                stiffness=None, damping=None, aim_axis=None, up_axis=None, name=None,
                control=None, preset=DEFAULT_PRESET, pin_root=True):
    """
    Layer a physics chain onto an existing FRAG component.

    :param component: A FRAG component, or a node belonging to one.
    :param float weight: Starting blend. 0 is the animation, 1 the simulation.
    :param float drag: How far the chain trails the animation. 0 tracks the
        flags closely, 1 hangs well back. None takes the preset's.
    :param float springiness: 0 settles without crossing the pose, 1 carries
        about 30% past it. None takes the preset's.
    :param float gravity: How far the chain hangs toward the gravity direction,
        as a fraction of the way to straight down. Roughly linear in the
        resulting angle: 0.25 sits about 45 degrees off vertical, 0.5 about 30,
        0.75 about 14, and 1.0 hangs. Scale free - the same value means the same
        hang whatever Drag is set to, and on a short braid or a long tail alike.
        Stored on the node as `droop`, because `gravity` there is the raw
        acceleration this replaces.
    :param float stiffness: Raw spring rate. Setting it switches the node to
        Advanced, where Drag, Springiness and Gravity stop applying.
    :param float damping: Raw ratio of critical damping. As above.
    :param int aim_axis: 0..5 for +x -x +y -y +z -z. None measures it from the
        chain, which is almost always what you want - the axis a rig aims down
        is a property of the rig, not something to default.
    :param int up_axis: As above.
    :param str name: Name for the physics node. Defaults to the component's.
    :param control: Flag to hang the channels on. Defaults to the flag driving
        the first level, which is the one an animator reaches for.
    :param str preset: Which of :data:`PRESETS` to start from.
    :param bool pin_root: Hold the first level on its goal, offsetting the whole
        chain to match. The solver treats every level as a free particle, so the
        root drifts off whatever the chain is attached to - a pony tail's base
        slides off the skull by a couple of units. Pinning keeps the lag and the
        shape, moves the base back where it belongs, and has the side benefit of
        making :func:`bake_physics` exact, since a flag cannot translate anyway.
    :return: Response describing what was built.
    :rtype: dict
    """

    available, reason = plugin_is_available()
    if not available:
        raise ValueError(reason)

    if preset not in PRESETS:
        raise ValueError('{} is not a preset. Choose from: {}.'
                         .format(preset, ', '.join(sorted(PRESETS))))
    settings = dict(PRESETS[preset])
    # Preset keys are node attribute names, so the public argument names and the
    # keys deliberately differ: Drag is `amount` and Gravity is `droop` inside.
    for key, value in (('amount', drag), ('springiness', springiness), ('droop', gravity)):
        if value is not None:
            settings[key] = value
    # Raw physics values are an opt out, not an override: leaving both sets live
    # at once is how a control ends up doing nothing for reasons nobody can see.
    advanced = stiffness is not None or damping is not None

    from mca.mya.rigging import frag

    frag_component = component if frag.is_frag_node(component) else frag.FRAGNode(component)
    label = _component_label(frag_component)
    bind_joints = list(frag_component.bind_joints or [])
    if not bind_joints:
        raise ValueError('{} drives no bind joints, so there is nothing for physics to move.'
                         .format(label))

    # Each bind joint is driven by a parentConstraint from the component's own
    # rig chain. That constraint's existing target is the goal: it is where the
    # animation says this joint should be.
    goals = []
    for joint in bind_joints:
        constraint = _driving_constraint(joint)
        if constraint is None:
            raise ValueError('{} is not driven by a parentConstraint, so physics cannot be '
                             'blended onto it without changing how the component works.'
                             .format(joint))
        targets = constraint.getTargetList()
        if not targets:
            raise ValueError('The constraint on {} has no targets.'.format(joint))
        goals.append(targets[0])

    node_name = name or '{}_physics'.format(label)
    physics_node = pm.createNode(NODE_TYPE, name=node_name)
    pm.connectAttr('time1.outTime', '{}.inTime'.format(physics_node))
    physics_node.startTime.set(pm.playbackOptions(q=True, min=True))
    physics_node.amount.set(settings['amount'])
    physics_node.springiness.set(settings['springiness'])
    physics_node.droop.set(settings.get('droop', 0.0))
    physics_node.mass.set(settings.get('mass', 1.0))
    physics_node.advanced.set(advanced)
    if advanced:
        physics_node.stiffness.set(stiffness if stiffness is not None else 0.5)
        physics_node.damping.set(damping if damping is not None else 0.7)
    derived_aim, derived_up = _derive_axes(goals)
    if aim_axis is None:
        aim_axis = derived_aim if derived_aim is not None else 0
    if up_axis is None:
        up_axis = derived_up if derived_up is not None else 2
    physics_node.aimAxis.set(aim_axis)
    physics_node.upAxis.set(up_axis)
    logger.debug('%s aims down axis %s, up %s.', node_name, aim_axis, up_axis)

    # One attribute drives both constraint weights, so there is a single thing to
    # key and no way for the pair to disagree.
    physics_node.addAttr('physicsWeight', at='double', min=0.0, max=1.0, dv=float(weight),
                         keyable=True)
    inverse = pm.createNode('reverse', name='{}_weight_reverse'.format(node_name))
    physics_node.physicsWeight >> inverse.inputX

    physics_node.addAttr(COMPONENT_TAG, at='message')
    try:
        frag_component.pynode.message >> physics_node.attr(COMPONENT_TAG)
    except Exception:
        logger.debug('Could not tag the component; removal will fall back to the drivers.',
                     exc_info=True)

    # Build with the solver switched off, so every driver sits exactly on the
    # goal it stands in for.
    #
    # `parentConstraint(maintainOffset=True)` freezes whatever gap exists at the
    # moment it is made. Add physics on a frame where the chain is mid-swing and
    # that gap - the simulation's own lag - is captured and applied forever, on
    # top of the simulation. It shows up as the layer disagreeing with itself:
    # at the start frame, with driver and goal in exactly the same place, the
    # bind joints were still [0, 0, 0.07, 0.16, 1.11, 1.64, 2.07, 2.81, 4.13]
    # apart between weight 0 and weight 1. That also looked exactly like a bake
    # error, and was chased as one for some time.
    was_enabled = physics_node.enabled.get()
    physics_node.enabled.set(False)

    # Connect every level's goal BEFORE building anything that measures against
    # the result.
    #
    # The node solves the chain it can see, and orientation comes from aiming
    # each level at the next - so a level is the tip until its successor is
    # connected. Wiring and constraining in one pass meant level 4's constraint
    # was captured while the node believed the chain was five levels long and
    # level 4 was the end of it, freezing a rotation that stopped being true one
    # line later. Measured: offsets of 1.11 units and 2.1 degrees on a chain
    # where driver and goal sat in exactly the same place.
    #
    # It used to cancel out by accident: the tip kept the animation's rotation,
    # so the wrong offset was the right one. Fixing the tip is what surfaced it.
    for index, goal in enumerate(goals):
        goal.worldMatrix[0] >> physics_node.attr('inLevels[{}].goalMatrix'.format(index))

    # The drivers live under one group. With the root pinned that group carries
    # the correction, so the chain keeps its shape and its lag while its base
    # stays on the thing it is attached to.
    group = pm.group(empty=True, name='{}_drv_grp'.format(node_name))
    group.addAttr(HELPER_TAG, at='message')
    physics_node.message >> group.attr(HELPER_TAG)
    helpers = [group]
    if pin_root:
        anchor = pm.createNode('decomposeMatrix', name='{}_anchor'.format(node_name))
        offset = pm.createNode('plusMinusAverage', name='{}_root_offset'.format(node_name))
        offset.operation.set(2)
        goals[0].worldMatrix[0] >> anchor.inputMatrix
        anchor.outputTranslate >> offset.input3D[0]
        physics_node.attr('outLevels[0].outTranslate') >> offset.input3D[1]
        offset.output3D >> group.translate
        for helper in (anchor, offset):
            helper.addAttr(HELPER_TAG, at='message')
            physics_node.message >> helper.attr(HELPER_TAG)
            helpers.append(helper)

    drivers = []
    controls = []
    missing_controls = []
    restore_records = []

    # Capture the offsets at the START FRAME, not at whatever frame the artist
    # happens to be sitting on.
    #
    # The offset each constraint carries is the gap between where the animation
    # puts the joint and where the solver puts the driver. That gap is only
    # meaningful at the start frame, where the simulation is pinned to the
    # animation by definition. Capture it mid-swing and the lag at that moment is
    # baked in permanently: the layer then disagrees with itself at the start
    # frame, which is the one place it cannot.
    #
    # Measured on a real rig (a four-level finger), adding at the start frame
    # against adding eight frames later:
    #
    #     added on the start frame   gap at start [0, 0, 0, 0]
    #     added eight frames later   gap at start [0, 0.1206, 0.6295, 1.112]
    #
    # Growing down the chain, because each level inherits its parent's lag. The
    # bake inherited it too - 2.1829 out at the tip.
    capture_time = pm.currentTime(q=True)
    start_frame = physics_node.startTime.get()
    if capture_time != start_frame:
        pm.currentTime(start_frame, edit=True)

    for index, (joint, goal) in enumerate(zip(bind_joints, goals)):
        driver = pm.createNode('transform', name='{}_{}_drv'.format(node_name, index + 1),
                               parent=group)
        driver.addAttr(DRIVER_TAG, at='message')
        driver.addAttr(GOAL_TAG, at='message')
        driver.addAttr(CONTROL_TAG, at='message')
        driver.addAttr(JOINT_TAG, at='message')
        driver.addAttr(LEVEL_TAG, at='long')
        physics_node.message >> driver.attr(DRIVER_TAG)
        goal.message >> driver.attr(GOAL_TAG)
        joint.message >> driver.attr(JOINT_TAG)
        driver.attr(LEVEL_TAG).set(index)

        level_control = _control_driving(goal)
        controls.append(level_control)
        if level_control is None:
            missing_controls.append(str(goal))
        else:
            level_control.message >> driver.attr(CONTROL_TAG)

        physics_node.attr('outLevels[{}].outTranslate'.format(index)) >> driver.translate
        physics_node.attr('outLevels[{}].outRotate'.format(index)) >> driver.rotate
        drivers.append(driver)
        # Pull the driver so it is where the solver says before the constraint
        # below measures the gap to it.
        driver.getTranslation(space='world')

        # Added, not replaced. The animation's own target stays on the
        # constraint, which is what lets weight 0 be exact rather than close.
        #
        # The offset is written by hand rather than left to maintainOffset.
        # Maya computes that against the BLENDED result of every target, and the
        # new one arrives at weight 1 alongside the animation's - so when the two
        # disagree in orientation, and they do, the captured offset is correct
        # for the blend and wrong at both ends of it. The driver's rotation is
        # the solver's aim basis; the rig chain's is whatever the rigger built.
        # On a chain running down -x that was a 180 degree error; with the aim
        # measured properly it was still 3.95 units of roll.
        animated = pm.dt.Matrix(joint.worldMatrix[0].get())
        pm.parentConstraint(driver, joint, maintainOffset=False)
        refreshed = _driving_constraint(joint)
        targets = [str(each) for each in refreshed.getTargetList()]
        weights = refreshed.getWeightAliasList()
        if len(weights) < 2 or len(weights) != len(targets):
            raise ValueError('Expected two constraint targets on {} after adding physics, got {}.'
                             .format(joint, len(weights)))
        # Find our own target rather than assuming it was appended last.
        if str(driver) not in targets:
            raise ValueError('The physics driver for {} is not on its constraint.'.format(joint))
        physics_index = targets.index(str(driver))

        # offset * driverWorld == where the animation had this joint.
        offset = animated * pm.dt.Matrix(driver.worldMatrix[0].get()).inverse()
        translate, rotate = _decompose(offset)
        refreshed.attr('target[{}].targetOffsetTranslate'.format(physics_index)).set(translate)
        refreshed.attr('target[{}].targetOffsetRotate'.format(physics_index)).set(rotate)

        physics_node.physicsWeight >> weights[physics_index]
        for position, alias in enumerate(weights):
            if position == physics_index:
                continue
            # Write down what this weight was before taking it over. Removal
            # cannot work it out later: by then this connection is the only thing
            # left to look at, and what it replaced is gone. See
            # :func:`_restore_weights` for what that cost.
            restore_records.append(_weight_record(alias))
            inverse.outputX >> alias

    # The records go on the node, not in a variable, so a chain that is saved,
    # reopened next week and removed then still gets its weights back.
    if not physics_node.hasAttr(RESTORE_TAG):
        physics_node.addAttr(RESTORE_TAG, dt='string', hidden=True)
    try:
        physics_node.attr(RESTORE_TAG).set(json.dumps(restore_records))
    except Exception:
        logger.warning('Could not record the original constraint weights on %s. Removing this '
                       'chain may leave its joints at weight 0.', physics_node, exc_info=True)

    # Back to where the artist was.
    if capture_time != start_frame:
        pm.currentTime(capture_time, edit=True)

    physics_node.enabled.set(was_enabled)

    if missing_controls:
        logger.warning('No flag found for %s; those levels cannot be baked onto controls.',
                       ', '.join(missing_controls))

    host = control
    if host is None:
        host = next((each for each in controls if each is not None), None)
    channels = None
    if host is None:
        logger.warning('No flag to hang the channels on; tune %s directly.', physics_node)
    else:
        exposed = expose_on_flag(physics_node, host)
        if not exposed['ok']:
            raise ValueError('The physics was built but its channels could not go on {}: {}'
                             .format(host, exposed['message']))
        channels = exposed['result']['channels']

    result = {'node': str(physics_node), 'levels': len(bind_joints),
              'drivers': [str(each) for each in drivers],
              'component': str(frag_component.pynode),
              'preset': preset,
              'pin_root': bool(pin_root),
              'group': str(group),
              'flag': str(host) if host is not None else '',
              'channels': channels or [],
              'bakeable': len(bind_joints) - len(missing_controls)}
    message = ('Added physics to {} - {} level(s), "{}" preset. {}'
               .format(label, len(bind_joints), preset,
                       'Tune it on {} in the channel box; Weight 0 is your animation, 1 is the '
                       'simulation.'.format(host) if host is not None else
                       'Tune it on {}.'.format(physics_node)))
    return result, message


@_safe
def set_weight(physics_node, weight):
    """
    Dial the simulation in or out.

    :param physics_node: The physics node or its name.
    :param float weight: 0 for the animation, 1 for the simulation.
    :return: Response.
    :rtype: dict
    """

    node = pm.PyNode(physics_node)
    plug = _writable(node.physicsWeight)
    plug.set(float(weight))
    return ({'node': str(node), 'plug': str(plug), 'weight': float(weight)},
            '{} is at {:.2f}: {}.'.format(plug, float(weight),
                                          'the animation' if float(weight) <= 0.0
                                          else 'the simulation' if float(weight) >= 1.0
                                          else 'a blend'))


@_safe
def apply_preset(physics_node, preset):
    """
    Drop a measured set of settings onto an existing chain.

    Writes Drag, Springiness and Gravity, so it has no effect while the node is
    in Advanced - which is the point of the switch.

    :param physics_node: The physics node or its name.
    :param str preset: One of :data:`PRESETS`.
    :return: Response.
    :rtype: dict
    """

    if preset not in PRESETS:
        raise ValueError('{} is not a preset. Choose from: {}.'
                         .format(preset, ', '.join(sorted(PRESETS))))
    node = pm.PyNode(physics_node)
    applied = {}
    for attribute, value in PRESETS[preset].items():
        plug = _writable(node.attr(attribute))
        plug.set(value)
        applied[attribute] = value
    return ({'node': str(node), 'preset': preset, 'settings': applied},
            'Set {} to "{}": {}.'.format(node, preset,
                                         ', '.join('{} {}'.format(key, value)
                                                   for key, value in sorted(applied.items()))))


def list_presets():
    """
    The presets and what each one does, for a menu or a docstring.

    :return: ``name -> settings``.
    :rtype: dict
    """

    return {name: dict(settings) for name, settings in PRESETS.items()}


@_safe
def set_ramp(physics_node, which, points, enable=True):
    """
    Vary one setting along the chain instead of holding it constant.

    A ramp is what makes a chain read as a chain rather than as a rod: stiffness
    falling from root to tip gives a tail that is firm where it is anchored and
    loose where it is free.

    :param physics_node: The physics node or its name.
    :param str which: One of :data:`RAMPS` - stiffness, damping, mass, gravity
        or aimWeight.
    :param list points: ``(position, value)`` or ``(position, value, interp)``,
        position running 0 at the root to 1 at the tip. Interpolation is a name
        from :data:`RAMP_INTERPOLATION` or Maya's own number.
    :param bool enable: Switch the ramp on. Setting one and leaving it off is
        almost always a mistake, so this defaults to True.
    :return: Response.
    :rtype: dict
    """

    if which not in RAMPS:
        raise ValueError('{} is not a ramp. Choose from: {}.'
                         .format(which, ', '.join(sorted(RAMPS))))
    if not points:
        raise ValueError('A ramp needs at least one point.')

    node = pm.PyNode(physics_node)
    ramp_attr, toggle = RAMPS[which]
    plug = node.attr(ramp_attr)

    for index in list(plug.getArrayIndices() or []):
        try:
            pm.removeMultiInstance(plug[index], b=True)
        except Exception:
            logger.debug('Could not clear %s[%s].', ramp_attr, index, exc_info=True)

    written = []
    for index, entry in enumerate(points):
        position, value = float(entry[0]), float(entry[1])
        interpolation = entry[2] if len(entry) > 2 else 'linear'
        if isinstance(interpolation, str):
            interpolation = RAMP_INTERPOLATION[interpolation]
        plug[index].attr('{}_Position'.format(ramp_attr)).set(position)
        plug[index].attr('{}_FloatValue'.format(ramp_attr)).set(value)
        plug[index].attr('{}_Interp'.format(ramp_attr)).set(int(interpolation))
        written.append((position, value))

    _writable(node.attr(toggle)).set(bool(enable))

    return ({'node': str(node), 'ramp': which, 'points': written, 'enabled': bool(enable)},
            '{} ramp on {}: {} point(s), {}.'.format(
                which, node, len(written), 'on' if enable else 'off (nothing will change)'))


@_safe
def get_ramp(physics_node, which):
    """
    Read a ramp back.

    :param physics_node: The physics node or its name.
    :param str which: One of :data:`RAMPS`.
    :return: Response whose result is ``(position, value, interp)`` in position
        order.
    :rtype: dict
    """

    if which not in RAMPS:
        raise ValueError('{} is not a ramp. Choose from: {}.'
                         .format(which, ', '.join(sorted(RAMPS))))
    node = pm.PyNode(physics_node)
    ramp_attr, toggle = RAMPS[which]
    plug = node.attr(ramp_attr)
    points = []
    for index in (plug.getArrayIndices() or []):
        points.append((plug[index].attr('{}_Position'.format(ramp_attr)).get(),
                       plug[index].attr('{}_FloatValue'.format(ramp_attr)).get(),
                       plug[index].attr('{}_Interp'.format(ramp_attr)).get()))
    points.sort()
    enabled = node.attr(toggle).get()
    return ({'ramp': which, 'points': points, 'enabled': enabled},
            '{} ramp: {} point(s), {}.'.format(which, len(points),
                                               'on' if enabled else 'off'))


@_safe
def remove_physics(physics_node):
    """
    Take the physics back off, leaving the component as it was.

    The animation's own constraint target is never removed on the way in, so
    this is a real undo rather than a rebuild: delete what this module made and
    the original constraint is the only thing left driving the joint. The flag
    goes back to the channels it had too.

    Left driving the joint, and driving it at the weight it had before - which
    took a second fix, because adding physics takes that weight over and
    deleting the thing that took it over does not give it back. See
    :func:`_restore_weights`.

    :param physics_node: The physics node or its name.
    :return: Response.
    :rtype: dict
    """

    node = pm.PyNode(physics_node)
    drivers = [each for each in (node.message.listConnections() or [])
               if each.hasAttr(DRIVER_TAG)]

    # Take the channels off before anything is deleted, so they are never left
    # on a flag pointing at a node that has gone.
    host = _host_flag(node)
    channels_removed = _strip_channels(host) if host is not None else 0

    # Delete the constraints that reference our drivers first, so removing the
    # driver cannot leave a constraint holding a dead target and snapping the
    # joint somewhere arbitrary.
    removed_constraints = 0
    touched = []
    for driver in drivers:
        for constraint in (driver.listConnections(type='parentConstraint') or []):
            targets = constraint.getTargetList()
            if len(targets) > 1:
                try:
                    pm.parentConstraint(driver, constraint.getParent(), edit=True, remove=True)
                    removed_constraints += 1
                except Exception:
                    logger.debug('Could not detach %s cleanly.', driver, exc_info=True)
            if constraint not in touched:
                touched.append(constraint)

    # Now that our target is off them, give the animation its weights back. This
    # runs BEFORE the reverse node is deleted, because a deleted reverse leaves
    # the weight holding the last value it pushed - zero - and nothing left to
    # say it was ever anything else.
    weights_restored = _restore_weights(node, touched)

    reverses = list(node.listConnections(type='reverse') or [])
    helpers = [each for each in (node.message.listConnections() or [])
               if each.hasAttr(HELPER_TAG)]
    pm.delete([each for each in drivers if pm.objExists(each)])
    pm.delete([each for each in helpers if pm.objExists(each)])
    pm.delete([each for each in reverses if pm.objExists(each)])
    if pm.objExists(node):
        pm.delete(node)

    return ({'drivers_removed': len(drivers), 'constraints_detached': removed_constraints,
             'helpers_removed': len(helpers), 'channels_removed': channels_removed,
             'weights_restored': weights_restored,
             'flag': str(host) if host is not None else ''},
            'Removed the physics layer. The component drives its joints the way it did before.')


@_safe
def list_physics_chains():
    """
    Every physics layer in the scene.

    :return: Response with one dict per chain.
    :rtype: dict
    """

    rows = []
    for node in (pm.ls(type=NODE_TYPE) or []):
        component = node.attr(COMPONENT_TAG).listConnections() if node.hasAttr(COMPONENT_TAG) \
            else []
        host = _host_flag(node)
        rows.append({'node': str(node),
                     'component': str(component[0]) if component else '',
                     'flag': str(host) if host is not None else '',
                     'weight': node.physicsWeight.get() if node.hasAttr('physicsWeight') else 1.0,
                     'advanced': node.advanced.get() if node.hasAttr('advanced') else False,
                     'amount': node.amount.get() if node.hasAttr('amount') else None,
                     'springiness': (node.springiness.get()
                                     if node.hasAttr('springiness') else None),
                     'droop': node.droop.get() if node.hasAttr('droop') else None,
                     'stiffness': node.stiffness.get(),
                     'damping': node.damping.get(),
                     'levels': node.attr('inLevels').numElements()})
    return rows, '{} physics chain(s) in the scene.'.format(len(rows))


@_safe
def bake_physics(physics_node, start_frame=None, end_frame=None, remove=True):
    """
    Bake the simulation onto the component's flags, then take the physics off.

    This is what an animator wants out of a sim: ordinary keys on the controls
    they already use. Baking onto the joints would hand them motion they cannot
    touch.

    It runs in two passes on purpose. The first reads where the simulation put
    every level on every frame and remembers it. Only then does the second pass
    move the flags - because moving a flag moves the rig chain the physics node
    reads its goals from, so writing while simulating would feed the sim its own
    output.

    Flags carry rotation only; their translate and scale are locked by the rig.
    For every level below the root that costs nothing, because those positions
    come from a parent's rotation and the flags are baked root to tip - each
    level lands on its already-simulated parent before its own rotation is
    solved. The root is the exception: the solver lets it drift off the thing the
    chain is attached to, and a flag that cannot translate will not follow it
    there. Measured on a nine level pony tail that drift peaked at 2.9 units.
    Worth knowing, but it is the simulation being loose rather than the bake
    being lossy - a pony tail's base belongs on the skull.

    ``error_by_level`` in the response is measured, not claimed: bind joint
    positions under the baked keys against the same joints during the sim.

    :param physics_node: The physics node or its name.
    :param float start_frame: First frame. None uses the playback range.
    :param float end_frame: Last frame. None uses the playback range.
    :param bool remove: Take the physics layer off afterwards. On by default;
        leaving it on would double the motion now the flags carry it.
    :return: Response.
    :rtype: dict
    """

    node = pm.PyNode(physics_node)
    levels = _levels_of(node)
    if not levels:
        raise ValueError('{} has no drivers, so there is no simulation to bake.'.format(node))

    without_control = [str(row['driver']) for row in levels if row['control'] is None]
    if without_control:
        raise ValueError('These levels have no flag to bake onto: {}. Remove the physics and add '
                         'it again so the flags get recorded.'.format(', '.join(without_control)))

    if start_frame is None:
        start_frame = pm.playbackOptions(q=True, min=True)
    if end_frame is None:
        end_frame = pm.playbackOptions(q=True, max=True)
    frames = list(range(int(start_frame), int(end_frame) + 1))

    drivers = [row['driver'] for row in levels]
    controls = [row['control'] for row in levels]
    joints = [row['joint'] for row in levels]
    measurable = [each for each in joints if each is not None]

    weight_plug = _writable(node.physicsWeight)
    restore_time = pm.currentTime(q=True)
    restore_weight = weight_plug.get()
    autokey = pm.autoKeyframe(q=True, state=True)
    pm.autoKeyframe(state=False)

    try:
        # A flag sits at a fixed offset from what it drives, so the rotation that
        # puts the joint where the simulation wants it is the simulated rotation
        # with that offset applied.
        #
        # Measured against the DRIVER, not the goal.
        #
        # The goal is the rig chain, and its orientation is whatever the rigger
        # built; the driver's is the solver's aim basis. They sit at the same
        # PLACE at the start frame, which is what made measuring against the goal
        # look right, but they do not share an ORIENTATION. So an offset captured
        # against the goal and then applied to the driver carries that
        # orientation mismatch into every baked frame.
        #
        # The root paid nothing, because its own position does not reveal its own
        # rotation. Its children paid all of it, rigidly and equally: every level
        # below was out by an identical 0.2411 on a four-level finger - identical
        # because each level's world rotation was baked correctly, so they all
        # inherited the same displacement from one wrong rotation above them. A
        # flat error across levels is the signature of a single bad transform
        # upstream, where accumulated lag would have grown down the chain.
        #
        # `add_physics` already measures against the driver for exactly this
        # reason. The bake now agrees with it.
        weight_plug.set(0.0)
        pm.currentTime(frames[0], edit=True)
        offsets = [pm.dt.Matrix(control.worldMatrix[0].get()) *
                   pm.dt.Matrix(driver.worldMatrix[0].get()).inverse()
                   for control, driver in zip(controls, drivers)]

        # Pass one: watch the simulation without touching anything.
        weight_plug.set(1.0)
        simulated = {}
        witnessed = {}
        for frame in frames:
            pm.currentTime(frame, edit=True)
            simulated[frame] = [pm.dt.Matrix(driver.worldMatrix[0].get()) for driver in drivers]
            witnessed[frame] = [pm.dt.Vector(each.getTranslation(space='world'))
                                for each in measurable]

        # Pass two: pose every frame and remember the local rotations, WITHOUT
        # keying yet.
        #
        # Keying as it goes looks natural and is wrong. The moment a rotate
        # channel carries a curve, a write to it is transient - the next
        # evaluation pulls from the curve again - so xform poses correctly but
        # the value read back, and the key made from it, are the old ones. The
        # staleness compounds parent to child: measured, exact at the first two
        # levels and 4.13 units out at the tip. Computing the local rotation from
        # parentInverseMatrix instead was worse still, at 64.6.
        #
        # With no curves in place the writes stick, so the pose is read back
        # truthfully. The keys go on afterwards, all at once.
        weight_plug.set(0.0)
        posed = {}
        for frame in frames:
            pm.currentTime(frame, edit=True)
            rotations = []
            for control, offset, matrix in zip(controls, offsets, simulated[frame]):
                pm.xform(control, worldSpace=True,
                         rotation=_world_euler(offset * matrix, control))
                rotations.append(list(control.rotate.get()))
            posed[frame] = rotations

        for frame in frames:
            for control, rotation in zip(controls, posed[frame]):
                for channel, value in zip(ROTATE_CHANNELS, rotation):
                    pm.setKeyframe(control, attribute=channel, time=frame, value=value)

        # Baked euler angles can flip between frames even when the rotation is
        # continuous; the filter puts them back on one branch.
        curves = []
        for control in controls:
            for channel in ROTATE_CHANNELS:
                curves.extend(control.attr(channel).listConnections(type='animCurve') or [])
        if curves:
            try:
                pm.filterCurve(curves, filter='euler')
            except Exception:
                logger.debug('Euler filter failed; the keys are still correct.', exc_info=True)

        # Measure rather than claim. With physics off the bind joints move under
        # the baked keys alone, so compare where they land now against where the
        # simulation had them - the same joints, in the same space, so the number
        # is the error an animator would see and not an artefact of offsets.
        worst = 0.0
        worst_frame = frames[0]
        by_level = [0.0] * len(measurable)
        for frame in frames:
            pm.currentTime(frame, edit=True)
            for index, (joint, point) in enumerate(zip(measurable, witnessed[frame])):
                error = (pm.dt.Vector(joint.getTranslation(space='world')) - point).length()
                by_level[index] = max(by_level[index], error)
                if error > worst:
                    worst = error
                    worst_frame = frame
    finally:
        pm.autoKeyframe(state=autokey)
        if not remove:
            weight_plug.set(restore_weight)
        pm.currentTime(restore_time, edit=True)

    removed = None
    if remove:
        removed = remove_physics(node)

    # Where the error sits matters more than how big it is, and it is never
    # spread evenly. A flag cannot translate, so whatever the root does not
    # reproduce is inherited by its child and added to down the chain. That is
    # why an unpinned root is worth caring about: the tip pays for it.
    rounded = [round(value, 4) for value in by_level]
    note = ''
    if rounded and rounded[0] > 1e-3:
        note = (' It starts at {:.3f} on the root - the sim sliding its base off the anchor,'
                ' which a rotation-only flag cannot follow - and each level inherits it.'
                ' Adding the physics with pin_root=True removes the cause.'.format(rounded[0]))

    return ({'controls': [str(each) for each in controls],
             'range': [float(start_frame), float(end_frame)],
             'worst_error': round(worst, 4),
             'worst_error_frame': worst_frame,
             'error_by_level': rounded,
             'removed': bool(remove) and removed is not None and removed['ok']},
            'Baked {} flag(s) over frames {:.0f}-{:.0f}. Worst difference from the simulation is '
            '{:.3f} units, at frame {}.{}{}'.format(
                len(controls), start_frame, end_frame, worst, worst_frame, note,
                ' Physics removed; the motion is in the curves now.' if remove else ''))
