"""
Maya's start-up script.

Maya runs this once, as itself, when it opens. It is deliberately thin: work out where the
framework is, hand over to the shared bootstrap, and do both after Maya has finished opening
so nothing here delays the splash screen or runs before the scene is ready.

The version this replaces did three things it should not have:

- It read ``os.path.dirname(os.getenv('MCA_COMMON_PATH'))``, which raises TypeError when
  that variable is not set - and an exception in userSetup.py stops everything after it, so
  opening Maya without the launcher meant no framework and no message saying why.
- It pip-installed pymel into Maya's own installation, during start-up, running whichever
  ``mayapy`` happened to be on PATH. Packages are the launcher's business: it installs them
  per Maya version, into a folder of its own, and proves they import before Maya opens.
- It left a one-line selection helper and an ``importlib.reload`` in Maya's global namespace.
"""

# python imports
import os
import sys

# maya imports
import maya.api.OpenMaya as OpenMaya
import maya.cmds as cmds


#: Where this script sits relative to the packages folder, used only when the
#: environment does not say. Six levels: Scripts/<dcc>/dccs/startup/common/mca.
_LEVELS_UP = 6


def framework_path():
    """
    The folder to put on sys.path so ``import mca.common`` works.

    Asked for in two ways, in this order:

    1. ``MCA_FRAMEWORK_PATH``, which the launcher exports when it starts a DCC.
       This is the answer whenever a DCC was started the supported way, and it is
       the project's own value rather than one worked out from where a file sits.
    2. This script's own location, for a Maya opened by hand.

    Deriving it from ``__file__`` alone is what this replaces. Maya does not always
    execute userSetup.py with ``__file__`` defined - Maya 2026 does not - and the
    NameError came out of a function documented to return a path, before anything
    had loaded and with nothing saying why. ``__file__`` is now a fallback, and a
    missing one is reported rather than raised.

    :return: The folder holding the ``mca`` package (``<packages>/mca-common``),
        or '' when neither route answers.
    :rtype: str
    """

    # MCA_FRAMEWORK_PATH names the packages folder; what goes on sys.path is the
    # package inside it that holds `mca`, which is mca-common. One level lower.
    from_env = os.getenv('MCA_FRAMEWORK_PATH')
    if from_env:
        candidate = os.path.normpath(os.path.join(from_env, 'mca-common'))
        if os.path.isdir(os.path.join(candidate, 'mca')):
            return candidate

    here = globals().get('__file__')
    if not here:
        # Maya exec'd this without __file__; the Scripts folder is on sys.path
        # though, because that is how Maya found this script at all.
        for entry in sys.path:
            if entry.replace('\\', '/').rstrip('/').endswith('dccs/maya/Scripts'):
                here = os.path.join(entry, 'userSetup.py')
                break

    if not here:
        return ''

    folder = os.path.dirname(os.path.abspath(here))
    for _ in range(_LEVELS_UP):
        folder = os.path.dirname(folder)
    return os.path.normpath(folder)


def claim_namespace(root):
    """
    Make an already-imported ``mca`` package see this framework's root.

    ``mca`` is a pkgutil namespace package: every ``mca/__init__.py`` calls
    ``extend_path``, which reads ``sys.path`` at the moment that file runs and never
    again. Python then caches ``mca`` in ``sys.modules``. So whichever code imports
    ``mca`` first decides, for the rest of the session, which roots it can see - and
    a Maya plug-in that loads before userSetup can easily get there first.

    When that happens, appending this framework to ``sys.path`` is too late: ``mca``
    is already bound elsewhere and ``import mca.common`` fails with "No module named
    'mca.common'" while the folder sits plainly on disk. Appending to the live
    ``mca.__path__`` is what lets the two meet.

    This is deliberately a copy of ``bootstrap.repair_namespace``, and must stay one.
    This file cannot import from ``mca.common``: making that import work is the entire
    reason it runs. So the two are kept to the same logic by hand - case-normalised
    comparison, an ``isdir`` check before appending, and ``invalidate_caches`` after -
    and a change to one belongs in the other. ``repair_namespace`` is the one with the
    tests; it takes several roots, this takes the one root that matters here.

    :param str root: ``<packages>/mca-common``, the folder holding ``mca``.
    :return: Whether anything was added.
    :rtype: bool
    """

    module = sys.modules.get('mca')
    namespace = getattr(module, '__path__', None) if module is not None else None
    if namespace is None:
        # Not imported yet - extend_path will find us on its own.
        return False

    wanted = os.path.join(root, 'mca')
    if not os.path.isdir(wanted):
        return False
    if any(os.path.normcase(os.path.abspath(one)) == os.path.normcase(os.path.abspath(wanted))
           for one in namespace):
        return False

    namespace.append(wanted)
    import importlib
    importlib.invalidate_caches()
    return True


def namespace_report():
    """
    :return: Where an already-imported ``mca`` came from, for a failure message.
    :rtype: str
    """

    module = sys.modules.get('mca')
    if module is None:
        return 'mca had not been imported'
    where = getattr(module, '__file__', None) or '<namespace>'
    paths = list(getattr(module, '__path__', []) or [])
    return 'mca was already imported from {} with __path__={}'.format(where, paths)


def say(message):
    """
    :param str message: Something for Maya's script editor.
    """

    OpenMaya.MGlobal.displayInfo(str(message))


def start_framework():
    """Put the framework on the path and start it, deferred until Maya is up."""

    root = framework_path()
    if not root:
        OpenMaya.MGlobal.displayWarning(
            'MCA: the framework path is not known. Start this DCC from the MCA '
            'launcher, or set MCA_FRAMEWORK_PATH to the packages folder.')
        return
    if root not in sys.path:
        sys.path.append(root)
    claim_namespace(root)

    try:
        from mca.common.startup.dccs import bootstrap
    except ImportError as error:
        OpenMaya.MGlobal.displayWarning(
            'MCA: the framework was not found at {} ({}). {}. Maya will run without '
            'the pipeline tools.'.format(root, error, namespace_report()))
        return

    bootstrap.start('maya', say=say)


def start_command_ports():
    """Open the ports an assistant drives this Maya through, when mca-mcp is installed."""

    root = framework_path()
    if not root:
        return
    if root not in sys.path:
        sys.path.append(root)
    claim_namespace(root)

    try:
        from mca.common.startup.dccs import bootstrap
    except ImportError:
        return
    bootstrap.start_mcp(say=say)


if __name__ == '__main__':
    # Deferred: Maya is still building itself while userSetup runs, and anything that
    # touches the scene or the UI before it has finished is a race.
    cmds.evalDeferred(start_framework)
    cmds.evalDeferred(start_command_ports)
