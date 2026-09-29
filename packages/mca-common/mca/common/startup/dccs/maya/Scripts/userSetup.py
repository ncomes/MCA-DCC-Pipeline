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


def framework_path():
    """
    :return: The folder holding the ``mca`` package, worked out from this file: this script
        is at ``<packages>/mca-common/mca/common/startup/dccs/maya/Scripts``.
    :rtype: str
    """

    # This script is at <packages>/mca-common/mca/common/startup/dccs/<dcc>/Scripts, so six
    # folders up is mca-common itself - the folder holding the mca package. Joining
    # 'mca-common' on again is one too many, which is what the suite caught.
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        here = os.path.dirname(here)
    return os.path.normpath(here)


def say(message):
    """
    :param str message: Something for Maya's script editor.
    """

    OpenMaya.MGlobal.displayInfo(str(message))


def start_framework():
    """Put the framework on the path and start it, deferred until Maya is up."""

    root = framework_path()
    if root not in sys.path:
        sys.path.append(root)

    try:
        from mca.common.startup.dccs import bootstrap
    except ImportError as error:
        OpenMaya.MGlobal.displayWarning(
            'MCA: the framework was not found at {} ({}). Maya will run without the '
            'pipeline tools.'.format(root, error))
        return

    bootstrap.start('maya', say=say)


def start_command_ports():
    """Open the ports an assistant drives this Maya through, when mca-mcp is installed."""

    root = framework_path()
    if root not in sys.path:
        sys.path.append(root)

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
