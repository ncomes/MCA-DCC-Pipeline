"""
MotionBuilder's start-up script.

MotionBuilder runs this when it opens.

The version this replaces called ``startup.init(dcc='mobu')``. There is no ``init`` - the
function is ``startup_init`` - and it takes a project name, which was not passed either. So
every MotionBuilder start raised AttributeError inside a print-and-continue script: the
framework has never come up in MotionBuilder, and nothing said so.

It also carried three dead functions - a menubar lookup that found the menubar and returned,
a JSON reader nobody called, and a path helper nobody called - and a PySide 1 import kept for
a MotionBuilder a decade out of support.
"""

# python imports
import os
import sys


def framework_path():
    """
    :return: The folder holding the ``mca`` package, worked out from this file.
    :rtype: str
    """

    # This script is at <packages>/mca-common/mca/common/startup/dccs/<dcc>/Scripts, so six
    # folders up is mca-common itself - the folder holding the mca package. Joining
    # 'mca-common' on again is one too many, which is what the suite caught.
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        here = os.path.dirname(here)
    return os.path.normpath(here)


def start_framework():
    """Put the framework on the path and start it."""

    root = framework_path()
    if root not in sys.path:
        sys.path.append(root)

    try:
        from mca.common.startup.dccs import bootstrap
    except ImportError as error:
        print('MCA: the framework was not found at {} ({}). MotionBuilder will run without '
              'the pipeline tools.'.format(root, error))
        return

    bootstrap.start('mobu')


start_framework()
