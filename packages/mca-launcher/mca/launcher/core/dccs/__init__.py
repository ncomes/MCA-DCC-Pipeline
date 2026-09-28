"""
One module per DCC, and a registry so the rest of the launcher never names them.

Everything a DCC-specific question needs is behind this: which versions are installed,
where the executable is, which Python belongs to it, and how to start it. Adding Blender or
Houdini means adding a module here and nothing else.
"""

# mca imports
from mca.launcher.core.dccs.base import Dcc, LaunchTarget
from mca.launcher.core.dccs import maya as maya_dcc
from mca.launcher.core.dccs import mobu as mobu_dcc
from mca.launcher.core.dccs import unreal as unreal_dcc


#: Every DCC the launcher knows, in the order the window shows them.
DCCS = (maya_dcc.Maya(), mobu_dcc.MotionBuilder(), unreal_dcc.Unreal())

#: Keyed by name, for callers that were handed a string.
BY_NAME = {dcc.name: dcc for dcc in DCCS}


def get(name):
    """
    :param str name: A DCC name, for example 'maya'. Case is ignored.
    :return: The DCC.
    :rtype: Dcc
    :raises ValueError: When nothing by that name is known - with the list of what is.
    """

    key = str(name or '').strip().lower()
    if key in BY_NAME:
        return BY_NAME[key]
    raise ValueError('There is no DCC called {!r}. The launcher knows: {}.'
                     .format(name, ', '.join(sorted(BY_NAME))))


def names():
    """
    :return: Every known DCC name.
    :rtype: list(str)
    """

    return [dcc.name for dcc in DCCS]
