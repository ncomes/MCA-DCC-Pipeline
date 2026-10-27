"""
What every DCC's start-up script does, in one place.

The three scripts - Maya's ``userSetup.py``, MotionBuilder's ``startup.py``, Unreal's
``init_unreal.py`` - had the same twenty lines copied into each, and the copies had drifted:

- **MotionBuilder's called a function that does not exist.** ``startup.init(dcc='mobu')`` -
  the function is ``startup_init``, and it needs a project name. Every MotionBuilder start
  raised AttributeError, which means the framework has never once come up in MotionBuilder.
- **All three could kill the DCC's start-up on a missing variable.**
  ``os.path.dirname(os.getenv('MCA_COMMON_PATH'))`` raises TypeError when the variable is
  not set, and in Maya's ``userSetup.py`` an exception means everything after it never runs.
  Opening Maya without the launcher was enough.
- **Unreal's defaulted the project name to 'SampleGame'**, so a missing variable silently
  started the wrong project - in a file bound for an open repository.
- **Maya's installed pymel** - ``mayapy -m pip install pymel``, into Maya's own
  installation, during start-up, resolving ``mayapy`` from PATH, which need not be the Maya
  that is running. Installing packages is the launcher's job, and it does it per version
  into a folder of its own.

Each script now works out where the framework is **from its own location**, which needs no
environment at all, and this module does the rest.
"""

# python imports
import os
import sys


#: Where the framework is, relative to a DCC script: this file is at
#: ``<packages>/mca-common/mca/common/startup/dccs/bootstrap.py``.
PACKAGE_DEPTH = 5


def framework_root():
    """
    The packages folder, worked out from this file rather than from the environment.

    :return: The folder holding ``mca-common``.
    :rtype: str
    """

    root = os.path.dirname(os.path.abspath(__file__))
    for _ in range(PACKAGE_DEPTH):
        root = os.path.dirname(root)
    return os.path.normpath(root)


def package_root():
    """
    :return: The folder holding the ``mca`` package, which is what goes on ``sys.path``.
    :rtype: str
    """

    return os.path.join(framework_root(), 'mca-common')


def add_to_path(*paths):
    """
    Put folders on ``sys.path``, skipping the ones that are not there.

    :param paths: Folders, any of which may be None or empty - which is the whole point,
        because these come from environment variables that may not be set.
    :return: What was added.
    :rtype: list(str)
    """

    added = []
    for path in paths:
        if not path:
            continue
        path = os.path.abspath(str(path))
        if not os.path.isdir(path):
            continue
        if path not in sys.path:
            sys.path.append(path)
            added.append(path)
    repair_namespace(*added)
    return added


def repair_namespace(*roots):
    """
    Teach an already-imported ``mca`` package about package roots added after it.

    ``mca`` is a pkgutil namespace: each ``mca/__init__.py`` calls ``extend_path``, which
    scans ``sys.path`` **at the moment that file runs** and then never looks again. Python
    caches the result in ``sys.modules``, so whoever imports ``mca`` first decides, for the
    life of the session, which package roots it can see.

    That is fine when this framework starts first. It is not fine when something else -
    another project's environment, a DCC plug-in that loads early - imports ``mca`` from a
    different depot before this runs. ``mca`` is then bound to that other tree, our roots
    are appended to ``sys.path`` far too late to matter, and importing ``mca.common`` fails
    with "No module named 'mca.common'" while the folder sits plainly on disk.

    Appending to the live ``mca.__path__`` is what makes the two meet. The import caches
    are invalidated afterwards because a failed import of ``mca.common`` is remembered.

    This is the one implementation. ``userSetup.claim_namespace`` is a deliberate copy of
    it - that script cannot import from ``mca.common``, because making that import work is
    what it is for - so a change here belongs there too.

    :param roots: Folders just put on ``sys.path``, each of which may hold an ``mca``.
    :return: The namespace folders added.
    :rtype: list(str)
    """

    module = sys.modules.get('mca')
    if module is None:
        # Nothing has imported it yet, so extend_path will see our roots by itself.
        return []

    namespace = getattr(module, '__path__', None)
    if namespace is None:
        return []

    existing = [os.path.normcase(os.path.abspath(one)) for one in namespace]
    added = []
    for root in roots:
        candidate = os.path.join(root, 'mca')
        if not os.path.isdir(candidate):
            continue
        if os.path.normcase(os.path.abspath(candidate)) in existing:
            continue
        namespace.append(candidate)
        existing.append(os.path.normcase(os.path.abspath(candidate)))
        added.append(candidate)

    if added:
        import importlib
        importlib.invalidate_caches()
    return added


def project_name():
    """
    :return: The project this DCC was started for, or ''. No default: starting the wrong
        project quietly is worse than starting none.
    :rtype: str
    """

    return os.getenv('MCA_PROJECT_NAME') or ''


def start(dcc, say=None):
    """
    Put the framework on the path and start it.

    Never raises. In Maya's ``userSetup.py`` an exception stops everything after it from
    running, and a broken pipeline should cost the tools, not the DCC.

    :param str dcc: 'maya', 'mobu' or 'ue'.
    :param callable say: Where to report, for a DCC with its own console. Defaults to print.
    :return: Whether the framework came up.
    :rtype: bool
    """

    speak = say or (lambda message: print(message))

    try:
        add_to_path(package_root(),
                    os.getenv('MCA_COMMON_DEPEND'),
                    os.getenv('MCA_{}_DEPEND'.format(dcc.upper())))

        name = project_name()
        if not name:
            speak('MCA: no project is set (MCA_PROJECT_NAME), so the framework was not '
                  'started. Start this DCC from the MCA launcher.')
            return False

        from mca.common.startup import startup

        return startup.startup_init(project_name=name, dcc=dcc)
    except Exception as error:                                       # noqa: BLE001
        speak('MCA: the framework did not start: {}: {}'.format(type(error).__name__, error))
        import traceback
        speak(traceback.format_exc())
        return False


def start_mcp(say=None):
    """
    Open the command ports an assistant reaches this DCC through, when mca-mcp is here.

    These used to be opened by the MCA Editor's plug-in, which meant every tool that drives
    Maya from outside only worked while a code editor happened to be loaded in it.

    Never raises: a DCC that will not start because a port is busy would be a bad trade.

    :param callable say: Where to report.
    :return: Whether the ports were opened.
    :rtype: bool
    """

    speak = say or (lambda message: print(message))

    try:
        # mca-mcp sits beside mca-common in the pipeline repo. The launcher sets this when
        # it finds it; a pip-installed mca-mcp needs neither.
        add_to_path(os.getenv('MCA_MCP_PATH'))
        from mca.mcp.maya import bootstrap
    except ImportError:
        # Not installed here. The DCC works; it just cannot be driven from outside.
        return False
    except Exception as error:                                       # noqa: BLE001
        speak('MCA: could not load the command ports: {}'.format(error))
        return False

    try:
        bootstrap.start()
        return True
    except Exception as error:                                       # noqa: BLE001
        speak('MCA: could not open the command ports: {}'.format(error))
        return False
