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
