"""
Unreal's start-up script.

Unreal runs this when the editor opens, because the launcher puts this folder on
``UE_PYTHONPATH``.

The version this replaces defaulted the project name to ``'Wayward'``, so a missing
``MCA_PROJECT_NAME`` silently started somebody else's project - in a file headed for an open
repository. There is no default now: with no project set, the framework says so and does not
start.
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
        print('MCA: the framework was not found at {} ({}). Unreal will run without the '
              'pipeline tools.'.format(root, error))
        return

    bootstrap.start('ue')


start_framework()
