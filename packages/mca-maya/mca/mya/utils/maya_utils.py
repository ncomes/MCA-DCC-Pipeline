"""
Which Maya this is, where its preferences live, and two odds and ends.

What was wrong before:

- **``get_version`` was ``int(pm.about(version=True))``.** Maya's version string is not
  always a number: a preview release answers ``'2025 Preview'`` and a service pack can
  answer ``'2019.3'``, and ``int()`` raises on both. The API version is an integer by
  definition, so that is what this reads.
- **``get_float_version`` existed twice**, here and in ``utils/plugins.py``, both of them
  ``mel.eval('getApplicationVersionAsFloat')``, and nothing in the pipeline called either.
  Dropping them takes ``maya.mel`` out of both modules.
- **``get_api_version`` had no callers.**
- **``delete_nodes_of_type`` had a guard that could never fire.** It skipped
  ``hyperGraphLayout`` with ``if n in ('hyperGraphLayout',)``, where ``n`` is a PyNode and
  the tuple holds a string - a PyNode never compares equal to a string, so the node it meant
  to protect was deleted like any other. The guard is a name comparison now.
"""

# python imports
import os

# software specific imports
import maya.cmds as cmds

# mca imports
from mca.common import log
from mca.common.paths import paths
from mca.common.utils import lists


logger = log.MCA_LOGGER

#: Node types that are Maya's own bookkeeping and must survive a scene clean-up, whatever
#: they are asked for.
PROTECTED_NODE_NAMES = ('hyperGraphLayout',)


def get_version():
    """
    Which Maya this is.

    :return: The version, such as 2025, or 0 when Maya will not say.
    :rtype: int
    """

    try:
        return int(cmds.about(apiVersion=True) // 10000)
    except Exception:
        logger.debug('Maya would not say which version it is.', exc_info=True)
        return 0


def maya_preferences_folder():
    """
    Where this machine keeps the pipeline's Maya preferences, made if it is not there.

    :return: The folder.
    :rtype: str
    """

    folder = os.path.join(paths.get_dcc_prefs_folder('maya'), 'default_options')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return os.path.normpath(folder)


def get_default_preferences_file():
    """
    The file holding the Maya options the pipeline sets for everybody.

    :return: The file's path. It does not have to exist yet.
    :rtype: str
    """

    return os.path.normpath(os.path.join(maya_preferences_folder(),
                                         'maya_default_options.prefs'))


def delete_nodes_of_type(node_type):
    """
    Delete every node of the given type, unlocking first.

    :param node_type: One type name, or several - ``hyperView``, ``script``, and so on.
    :type node_type: str or list(str)
    :return: The names of the nodes that were deleted.
    :rtype: list(str)
    """

    deleted = []
    for one_type in lists.force_list(node_type):
        for node in cmds.ls(type=one_type) or []:
            # A name comparison, not a PyNode-to-string one: the version this replaces
            # compared a PyNode against a tuple of strings, which is never equal, so the
            # node it meant to protect was deleted anyway.
            if node.split('|')[-1].split(':')[-1] in PROTECTED_NODE_NAMES:
                continue
            if not cmds.objExists(node):
                continue
            try:
                cmds.lockNode(node, lock=False)
                cmds.delete(node)
            except RuntimeError as error:
                logger.debug('Could not delete %s: %s', node, error)
                continue
            deleted.append(node)
    return deleted


class SelectionMasks(object):
    """
    The numbers ``filterExpand`` takes for its ``selectionMask``.

    Maya's documentation gives them as a numbered list with no names, so a call reading
    ``filterExpand(selection, selectionMask=31)`` says nothing about what it is filtering
    for. See the ``filterExpand`` page in Maya's Python command reference.
    """

    Handle = 0
    NurbsCurves = 9
    NurbsSurfaces = 10
    NurbsCurvesOnSurface = 11
    Polygon = 12
    LocatorXYZ = 22
    OrientationLocator = 23
    LocatorUV = 24
    ControlVertices = 28
    CVs = 28
    EditPoints = 30
    PolygonVertices = 31
    PolygonEdges = 32
    PolygonFace = 34
    PolygonUVs = 35
    SubdivisionMeshPoints = 36
    SubdivisionMeshEdges = 37
    SubdivisionMeshFaces = 38
    CurveParameterPoints = 39
    CurveKnot = 40
    SurfaceParameterPoints = 41
    SurfaceKnot = 42
    SurfaceRange = 43
    TrimSurfaceEdge = 44
    SurfaceIsoparms = 45
    LatticePoints = 46
    Particles = 47
    ScalePivots = 49
    RotatePivots = 50
    SelectHandles = 51
    SubdivisionSurface = 68
    PolygonVertexFace = 70
    NurbsSurfaceFace = 72
    SubdivisionMeshUVs = 73
