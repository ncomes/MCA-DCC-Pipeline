"""
Which application is this code running inside.

Asked constantly - a tool that behaves one way in Maya and another in MotionBuilder, a path
with the DCC's name in it, a port number - so it is worth being exactly one answer.

It was three. ``Dccs.Maya`` is ``'maya'``, the boot config and the start-up scripts say
``'maya'``, and ``application()`` answered ``'Maya'``; MotionBuilder was ``'mobu'``,
``'mobu'`` and ``'Mobu'``; Unreal was ``'unreal'`` in one table and ``'ue'`` in the config.
Anything comparing the answer to a constant had to know which spelling it was looking at,
and a path built from it - ``Tools/Common/Tools/Maya`` - survived only because Windows does
not care about case. :func:`application` answers a :class:`Dccs` value now, and
:func:`display_name` is there for when a person is going to read it.

One real bug, too: ``is_in_blender`` was written ``except ImportError or AttributeError``,
which evaluates to ``except ImportError`` - so the AttributeError it was meant to catch went
straight up. It also answered None rather than False when Blender was not there.
"""

# python imports
import math
import os
import sys
from collections import OrderedDict

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: Where a DCC's own command port starts. Each gets one of its own.
DEFAULT_DCC_PORT = 65500


class Dccs(object):
    """Every application the framework knows, by the one name it uses for each."""

    Standalone = 'standalone'
    Maya = 'maya'
    MotionBuilder = 'mobu'
    Unreal = 'unreal'
    Houdini = 'houdini'
    Max = '3dsmax'
    Blender = 'blender'
    SubstancePainter = 'painter'

    ALL = (Maya, MotionBuilder, Unreal, Houdini, Max, Blender, SubstancePainter)

    #: What to call each one in front of a person.
    names = OrderedDict([
        (Maya, 'Maya'),
        (MotionBuilder, 'MotionBuilder'),
        (Unreal, 'Unreal'),
        (Houdini, 'Houdini'),
        (Max, '3ds Max'),
        (Blender, 'Blender'),
        (SubstancePainter, 'Substance Painter'),
        (Standalone, 'Standalone'),
    ])

    #: The module that exists only inside that application. The surest test there is: it is
    #: about what is importable rather than what the executable happens to be called, which
    #: matters for a DCC started by something that renamed it.
    packages = OrderedDict([
        ('maya', Maya),
        ('pyfbsdk', MotionBuilder),
        ('unreal', Unreal),
        ('hou', Houdini),
        ('pymxs', Max),
        ('bpy', Blender),
        ('substance_painter', SubstancePainter),
    ])

    #: How an executable's name ends, for the cases where the module is not importable yet -
    #: during start-up, or in a batch interpreter.
    executables = OrderedDict([
        (Maya, ('maya', 'maya.exe', 'maya.bin', 'mayapy', 'mayapy.exe',
                'mayabatch', 'mayabatch.exe')),
        (MotionBuilder, ('motionbuilder', 'motionbuilder.exe', 'mobupy', 'mobupy.exe')),
        (Unreal, ('unreal', 'unreal.exe', 'unrealeditor', 'unrealeditor.exe',
                  'ue4editor', 'ue4editor.exe', 'ue5editor', 'ue5editor.exe')),
        (Houdini, ('houdini', 'houdinifx', 'houdinicore', 'happrentice')),
        (Max, ('3dsmax', '3dsmax.exe')),
        (Blender, ('blender', 'blender.exe')),
        (SubstancePainter, ('painter', 'painter.exe')),
    ])

    #: A port per application, so two DCCs open at once do not fight over one.
    ports = {
        Standalone: DEFAULT_DCC_PORT,
        Maya: DEFAULT_DCC_PORT + 1,
        MotionBuilder: DEFAULT_DCC_PORT + 2,
        Houdini: DEFAULT_DCC_PORT + 3,
        Max: DEFAULT_DCC_PORT + 4,
        Blender: DEFAULT_DCC_PORT + 5,
        SubstancePainter: DEFAULT_DCC_PORT + 6,
        Unreal: 30010,          # Unreal's own remote execution port.
    }


class CallbackTypes(object):
    """The scene events a DCC can tell the framework about."""

    Shutdown = 'Shutdown'
    Tick = 'Tick'
    ScenePreCreated = 'ScenePreCreated'
    ScenePostCreated = 'ScenePostCreated'
    SceneNewRequested = 'SceneNewRequested'
    SceneNewFinished = 'SceneNewFinished'
    SceneSaveRequested = 'SceneSaveRequested'
    SceneSaveFinished = 'SceneSaveFinished'
    SceneOpenRequested = 'SceneOpenRequested'
    SceneOpenFinished = 'SceneOpenFinished'
    UserPropertyPreChanged = 'UserPropertyPreChanged'
    UserPropertyPostChanged = 'UserPropertyPostChanged'
    NodeSelect = 'NodeSelect'
    NodeAdded = 'NodeAdded'
    NodeDeleted = 'NodeDeleted'
    ReferencePreLoaded = 'ReferencePreLoaded'
    ReferencePostLoaded = 'ReferencePostLoaded'


#: Each callback, and whether it is a plain notification or one that can filter what happens.
DCC_CALLBACKS = OrderedDict([
    (CallbackTypes.Shutdown, 'simple'),
    (CallbackTypes.Tick, 'simple'),
    (CallbackTypes.ScenePreCreated, 'simple'),
    (CallbackTypes.ScenePostCreated, 'simple'),
    (CallbackTypes.SceneNewRequested, 'simple'),
    (CallbackTypes.SceneNewFinished, 'simple'),
    (CallbackTypes.SceneSaveRequested, 'simple'),
    (CallbackTypes.SceneSaveFinished, 'simple'),
    (CallbackTypes.SceneOpenRequested, 'simple'),
    (CallbackTypes.SceneOpenFinished, 'simple'),
    (CallbackTypes.UserPropertyPreChanged, 'filter'),
    (CallbackTypes.UserPropertyPostChanged, 'filter'),
    (CallbackTypes.NodeSelect, 'filter'),
    (CallbackTypes.NodeAdded, 'filter'),
    (CallbackTypes.NodeDeleted, 'filter'),
    (CallbackTypes.ReferencePreLoaded, 'simple'),
    (CallbackTypes.ReferencePostLoaded, 'simple'),
])


def callbacks():
    """
    :return: Every callback the framework knows about.
    :rtype: list(str)
    """

    return list(DCC_CALLBACKS)


# ---------------------------------------------------------------------------- #
# Which application is this
# ---------------------------------------------------------------------------- #
def _leaf(path):
    """
    The last part of a path, whichever separator it was written with.

    These are Windows paths, and ``os.path.basename`` only splits on backslashes when it is
    running on Windows - so every one of these checks answered False on any other machine,
    which is also why none of them had ever been tested anywhere else.

    :param str path: A path.
    :return: Its last part, lower case.
    :rtype: str
    """

    text = str(path or '').replace('\\', '/').rstrip('/')
    return text.rsplit('/', 1)[-1].lower()


def _executable_is(dcc, executable=None):
    """
    :param str dcc: A ``Dccs`` value.
    :param str executable: An executable path. None uses this interpreter's.
    :return: Whether that executable is that DCC's.
    :rtype: bool
    """

    return _leaf(executable or sys.executable).endswith(Dccs.executables.get(dcc, ()))


def _module_is_here(module_name):
    """
    :param str module_name: A module that exists only inside one application.
    :return: Whether it can be imported here.
    :rtype: bool
    """

    if module_name in sys.modules:
        return True
    try:
        __import__(module_name)
        return True
    except Exception:                                                # noqa: BLE001
        # ImportError when it is not there; anything else when it is there and unhappy,
        # which is still not this application. The old is_in_blender wrote
        # `except ImportError or AttributeError`, which catches only ImportError.
        return False


def application(executable=None):
    """
    Which application this is running in.

    :param str executable: An executable to judge instead of this interpreter's.
    :return: A ``Dccs`` value - lower case, and the same spelling the boot config, the
        start-up scripts and ``Dccs`` use. It used to answer 'Maya', 'Mobu' and 'Unreal',
        which matched none of them.
    :rtype: str
    """

    for dcc in Dccs.ALL:
        if _executable_is(dcc, executable):
            return dcc

    if executable is None:
        # Nothing recognisable about the executable - a DCC that embeds Python under another
        # name, or mayapy inside a wrapper. Ask what is importable.
        for module_name, dcc in Dccs.packages.items():
            if module_name in sys.modules:
                return dcc
    return Dccs.Standalone


def display_name(dcc=None):
    """
    :param str dcc: A ``Dccs`` value. None asks what this is.
    :return: What to call it in front of a person.
    :rtype: str
    """

    dcc = dcc or application()
    return Dccs.names.get(dcc, str(dcc).title())


def port(dcc=None):
    """
    :param str dcc: A ``Dccs`` value. None asks what this is.
    :return: The command port for it.
    :rtype: int
    """

    return Dccs.ports.get(dcc or application(), DEFAULT_DCC_PORT)


def is_maya(executable=None):
    """
    :param str executable: An executable to judge instead of this interpreter's.
    :return: Whether this is Maya, mayapy or Maya batch.
    :rtype: bool
    """

    return _executable_is(Dccs.Maya, executable) or (
        executable is None and 'maya' in sys.modules)


def is_mayapy(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is mayapy rather than Maya itself.
    :rtype: bool
    """

    return _leaf(executable or sys.executable).startswith('mayapy')


def is_maya_batch(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is Maya batch.
    :rtype: bool
    """

    return _leaf(executable or sys.executable).startswith('mayabatch')


def is_in_motionbuilder(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is MotionBuilder.
    :rtype: bool
    """

    return _executable_is(Dccs.MotionBuilder, executable) or (
        executable is None and 'pyfbsdk' in sys.modules)


def is_in_unreal(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is Unreal.
    :rtype: bool
    """

    return _executable_is(Dccs.Unreal, executable) or (
        executable is None and 'unreal' in sys.modules)


def is_in_houdini(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is Houdini.
    :rtype: bool
    """

    return _executable_is(Dccs.Houdini, executable) or (
        executable is None and 'hou' in sys.modules)


def is_in_3dsmax(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is 3ds Max.
    :rtype: bool
    """

    return _executable_is(Dccs.Max, executable) or (
        executable is None and 'pymxs' in sys.modules)


def is_in_blender(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is Blender.
    :rtype: bool
    """

    if _executable_is(Dccs.Blender, executable):
        return True
    if executable is not None:
        return False
    return _module_is_here('bpy')


def is_standalone(executable=None):
    """
    :param str executable: An executable to judge.
    :return: Whether this is a plain Python rather than a DCC.
    :rtype: bool
    """

    return application(executable) == Dccs.Standalone


def application_version(dcc_name=None):
    """
    Which version of the application this is, asked of the application itself.

    :param str dcc_name: A ``Dccs`` value. None asks what this is.
    :return: The version, as a string, or '' outside a DCC or when it will not say.
    :rtype: str
    """

    dcc_name = (dcc_name or application()).lower()
    try:
        if dcc_name == Dccs.Maya:
            import maya.cmds

            return str(maya.cmds.about(version=True))
        if dcc_name == Dccs.MotionBuilder:
            import pyfbsdk

            return str(int(2000 + math.ceil(pyfbsdk.FBSystem().Version / 1000.0)))
        if dcc_name == Dccs.Unreal:
            import unreal

            raw = unreal.SystemLibrary.get_engine_version()
            return '.'.join(raw.split('+++')[0].split('-')[0].split('.')[:2])
    except Exception as error:                                       # noqa: BLE001
        logger.debug('Could not ask %s for its version: %s', dcc_name, error)
    return ''
