"""
Interpolate an N-dimensional key to an M-dimensional value.

A driven key with more than one dimension on each side. A regular driven key
maps one float to one float; this maps a whole vector to a whole vector and
blends smoothly between the poses you give it - a shoulder's blendshape weights
from the arm's aim vector, a colour from a position, a set of correctives from
several joints at once.

The workflow this is built around
---------------------------------
1. Make a solver.
2. Connect the things that drive it (:func:`connect_input`) and the things it
   drives (:func:`connect_output`).
3. Pose the rig, set the values you want at that pose, and :func:`add_pose`.
   Repeat.

:Requires: the mcaRBFSolver plug-in
:Side effects: Creates a node and makes connections in the open scene.
"""

# python imports
import functools

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

PLUGIN_NAME = 'mcaRBFSolver'
NODE_TYPE = 'mcaRBFSolver'

#: How the distance between two keys is measured. `p_norm` is the behaviour the
#: tool this replaces called Euclidean and was not - see the module docs in
#: mca_rbf.h. It is kept so an old setup can be reproduced.
DISTANCES = {'euclidean': 0, 'angular': 1, 'p_norm': 2}
#: The radial basis function.
KERNELS = {'linear': 0, 'gaussian': 1, 'multiquadric': 2, 'inverse_quadratic': 3,
           'inverse_multiquadric': 4, 'cubic': 5, 'thin_plate': 6}


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
        if loader.load_rbf_solver_plugin():
            return True, ''
    except Exception as exc:
        return False, ('The {} plug-in could not be loaded: {}. It may not have been built '
                       'for this Maya version yet - check plugins/mcaRBFSolver/plug-in/.'
                       .format(PLUGIN_NAME, exc))
    return False, ('The {} plug-in could not be loaded. Check that it has been built for '
                   'this Maya version under plugins/mcaRBFSolver/plug-in/.'
                   .format(PLUGIN_NAME))


def _enum_value(table, value, label):
    """
    Accept either a name or a raw index for an enum attribute.

    :param dict table: Name to index.
    :param value: A key of ``table``, or an index.
    :param str label: What to call it if it is wrong.
    :return: The index.
    :rtype: int
    :raises ValueError: If the value is neither.
    """

    if isinstance(value, int) and not isinstance(value, bool):
        if value in table.values():
            return value
        raise ValueError('{} must be one of {}, got {}.'
                         .format(label, sorted(table.values()), value))
    key = str(value).strip().lower().replace(' ', '_').replace('-', '_')
    if key in table:
        return table[key]
    raise ValueError('{} must be one of {}, got {!r}.'
                     .format(label, sorted(table), value))


@_safe
def create_solver(name=None, distance='euclidean', kernel='gaussian', scale=1.0,
                  normalise=True, regularisation=0.0, weights_sum_to_one=False):
    """
    Make a solver.

    :param str name: Node name. Defaults to Maya's.
    :param distance: ``'euclidean'``, ``'angular'`` or ``'p_norm'``.
    :param kernel: One of :data:`KERNELS`.
    :param float scale: Multiplies every distance before the kernel sees it -
        how far a pose's influence reaches.
    :param bool normalise: Divide distances by the widest gap between poses, so
        the same scale means the same thing whatever the keys are measured in.
    :param float regularisation: Added to the matrix diagonal. 0 passes exactly
        through every pose; a small value trades that for stability and is what
        makes two poses at the same key solvable.
    :param bool weights_sum_to_one: Make the outputs non-negative and sum to 1.
        The node calls this ``blendShapeMode``, which is what the original
        called it.
    :return: The solver node.
    :rtype: pm.nt.DependNode
    """

    available, reason = plugin_is_available()
    if not available:
        raise RuntimeError(reason)

    # Work the enums out BEFORE making anything. Validating after the node exists
    # leaves an orphan behind every time a name is mistyped - which is what the
    # first version of this did, and what the suite caught by checking the scene
    # was left as it was found.
    distance_value = _enum_value(DISTANCES, distance, 'distance')
    kernel_value = _enum_value(KERNELS, kernel, 'kernel')

    solver = pm.createNode(NODE_TYPE, name=name or 'rbf_solver')
    solver.attr('distanceMode').set(distance_value)
    solver.attr('rbfMode').set(kernel_value)
    solver.attr('scale').set(scale)
    solver.attr('normalize').set(bool(normalise))
    solver.attr('regularization').set(max(0.0, regularisation))
    solver.attr('blendShapeMode').set(bool(weights_sum_to_one))
    return solver, 'Made {}.'.format(solver)


@_safe
def connect_input(solver, plugs):
    """
    Wire the things that drive the solver into its key.

    :param solver: The solver node.
    :param list plugs: Attributes, in order. Each becomes one dimension of the
        key, so the order has to match the order used in every pose.
    :return: How many dimensions were connected.
    :rtype: int
    """

    solver = pm.PyNode(solver)
    for index, plug in enumerate(plugs):
        pm.PyNode(plug) >> solver.attr('nInput[{}]'.format(index))
    return len(plugs), 'Connected a {}-dimensional key.'.format(len(plugs))


@_safe
def connect_output(solver, plugs):
    """
    Wire the solver's output to the things it drives.

    :param solver: The solver node.
    :param list plugs: Attributes, in order. Each takes one dimension of the
        value.
    :return: How many dimensions were connected.
    :rtype: int
    """

    solver = pm.PyNode(solver)
    for index, plug in enumerate(plugs):
        solver.attr('mOutput[{}]'.format(index)) >> pm.PyNode(plug)
    return len(plugs), 'Connected a {}-dimensional value.'.format(len(plugs))


def _next_pose_index(solver):
    """
    :param solver: The solver node.
    :return: The first unused index in the poses array.
    :rtype: int
    """

    used = solver.attr('poses').getArrayIndices()
    return (max(used) + 1) if used else 0


def _input_values(solver):
    """
    What the key is reading right now.

    :param solver: The solver node.
    :return: One value per dimension.
    :rtype: list
    """

    indices = solver.attr('nInput').getArrayIndices()
    if not indices:
        return []
    return [solver.attr('nInput[{}]'.format(i)).get() for i in range(max(indices) + 1)]


@_safe
def add_pose(solver, key=None, value=None, enabled=True):
    """
    Record a pose.

    With no ``key``, the solver's current input is used - so the way this is
    meant to be driven is: put the rig where you want it, work out the values
    that belong there, and call this.

    :param solver: The solver node.
    :param list key: The key. Defaults to whatever the input reads now.
    :param list value: The value that key should produce. Required, because
        reading it back off the output would just record what the solver
        already does.
    :param bool enabled: Whether the pose takes part.
    :return: The index the pose was stored at.
    :rtype: int
    """

    solver = pm.PyNode(solver)
    if key is None:
        key = _input_values(solver)
    if not key:
        raise ValueError('No key given, and nothing is connected to nInput to read one '
                         'from. Connect the driver first, or pass a key.')
    if not value:
        raise ValueError('A pose needs the value it should produce.')

    index = _next_pose_index(solver)
    solver.attr('poses[{}].state'.format(index)).set(bool(enabled))
    for dimension, component in enumerate(key):
        solver.attr('poses[{}].nKey[{}]'.format(index, dimension)).set(component)
    for dimension, component in enumerate(value):
        solver.attr('poses[{}].mValue[{}]'.format(index, dimension)).set(component)

    return index, 'Added pose {} - a {}D key driving a {}D value.'.format(
        index, len(key), len(value))


@_safe
def list_poses(solver):
    """
    Every pose on a solver.

    :param solver: The solver node.
    :return: One dict per pose, with its index, key, value and whether it is on.
    :rtype: list
    """

    solver = pm.PyNode(solver)
    rows = []
    for index in solver.attr('poses').getArrayIndices():
        key_indices = solver.attr('poses[{}].nKey'.format(index)).getArrayIndices()
        value_indices = solver.attr('poses[{}].mValue'.format(index)).getArrayIndices()
        rows.append({
            'index': index,
            'enabled': solver.attr('poses[{}].state'.format(index)).get(),
            'key': [solver.attr('poses[{}].nKey[{}]'.format(index, i)).get()
                    for i in range(max(key_indices) + 1)] if key_indices else [],
            'value': [solver.attr('poses[{}].mValue[{}]'.format(index, i)).get()
                      for i in range(max(value_indices) + 1)] if value_indices else [],
        })
    return rows, '{} pose(s).'.format(len(rows))


@_safe
def set_pose_enabled(solver, index, enabled):
    """
    Turn one pose on or off without losing it.

    :param solver: The solver node.
    :param int index: Which pose.
    :param bool enabled: Whether it takes part.
    :return: The index.
    :rtype: int
    """

    solver = pm.PyNode(solver)
    solver.attr('poses[{}].state'.format(index)).set(bool(enabled))
    return index, 'Pose {} is now {}.'.format(index, 'on' if enabled else 'off')


@_safe
def remove_pose(solver, index):
    """
    Delete a pose outright.

    :param solver: The solver node.
    :param int index: Which pose.
    :return: The index.
    :rtype: int
    """

    solver = pm.PyNode(solver)
    if index not in solver.attr('poses').getArrayIndices():
        raise ValueError('There is no pose {} on {}.'.format(index, solver))
    pm.removeMultiInstance(solver.attr('poses[{}]'.format(index)), b=True)
    return index, 'Removed pose {}.'.format(index)


@_safe
def remove_solver(solver):
    """
    Delete the solver. What it drove is left where it stands.

    :param solver: The solver node.
    :return: True.
    :rtype: bool
    """

    pm.delete(pm.PyNode(solver))
    return True, 'Removed the solver.'


def find_solvers():
    """
    Every solver in the open scene.

    Safe to call when the plug-in is not loaded - ``ls`` on an unregistered node
    type raises, so it is checked first.

    :return: The solver nodes.
    :rtype: list
    """

    try:
        if NODE_TYPE not in (cmds.allNodeTypes() or []):
            return []
    except Exception:
        return []
    return pm.ls(type=NODE_TYPE)
