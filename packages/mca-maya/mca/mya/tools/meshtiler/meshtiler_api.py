"""
Repeat one mesh across the surface of another.

Scales on a fish, feathers on a wing, plates on armour, bricks in a wall. A
*tile* mesh is copied onto every face of a *target* mesh and conformed to the
target's subdivision limit surface, so the tiles follow the smooth shape the
target implies rather than faceting along its cage. Move the target - or let a
rig move it - and every tile follows, live.

The work is done by the ``mcaMeshTiler`` node. This module is the layer that
builds one, wires it up, and puts the result somewhere an artist can use it.

What it does that the tool it replaces did not
----------------------------------------------
* **Any topology.** The original collected faces with exactly four vertices and
  silently dropped the rest, so a triangulated target produced an empty mesh and
  no message. Triangles and n-gons now tile.
* **UVs come across.** The original copied none, so every tile came out unmapped.
* **The shader comes across too**, so the result looks right the moment it
  appears rather than default grey.
* **The tile's orientation is stated rather than assumed.** ``up_axis`` defaults
  to Y, which is what the original hard-coded and documented nowhere.
* **A face can be filled rather than stretched.** The original put exactly one
  tile on each face and scaled it to fit, so a big face got a big tile and the
  only way to change that was to re-mesh the target. ``tiles_u`` and ``tiles_v``
  fill each face with a grid instead.
* **The result is an ordinary object.** The original always conformed the output
  back into the output transform's own space, which cancels out every move you
  make - so the tiled mesh silently could not be moved, parented or constrained,
  and nothing said why. That is now opt-in: see ``pin_to_target``.

:Requires: the mcaMeshTiler plug-in
:Side effects: Creates nodes in the open scene. Nothing that already exists is
    modified, so :func:`remove_tiling` can take it all back out again.
"""

# python imports
import functools

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# MCA python imports
from mca.common import log

logger = log.MCA_LOGGER

PLUGIN_NAME = 'mcaMeshTiler'
NODE_TYPE = 'mcaMeshTiler'

#: On the tiler: the tile and target it was built from, so a later call can find
#: its way back without relying on connections that an artist may have rewired.
TILE_TAG = 'mcaTilerTile'
TARGET_TAG = 'mcaTilerTarget'
#: On the output transform: the tiler that drives it.
TILER_TAG = 'mcaTilerNode'

#: Which tile axis points away from the surface.
UP_AXES = {'x': 0, 'y': 1, 'z': 2}
#: Where a tile's normal comes from. ``face`` is flat per face; ``surface``
#: interpolates the limit surface normal, which is what you want almost always;
#: ``derivative`` takes it from the surface derivatives, which is more faithful
#: on a heavily creased target and slower.
NORMAL_MODES = {'face': 0, 'surface': 1, 'derivative': 2}
#: How the limit surface behaves where the target has an open edge.
BOUNDARY_MODES = {'edge': 0, 'edge_and_corner': 1}


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

    Goes through ``plugins.loader`` rather than loading by bare name. The .mll
    lives under ``plugins/mcaMeshTiler/plug-in/<maya version>/Release`` and is not
    on MAYA_PLUG_IN_PATH by default, so ``loadPlugin('mcaMeshTiler')`` fails on a
    machine that has never loaded it before.

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
        if loader.load_mesh_tiler_plugin():
            return True, ''
    except Exception as exc:
        return False, ('The {} plug-in could not be loaded: {}. It may not have been built for '
                       'this Maya version yet - check plugins/mcaMeshTiler/plug-in/.'
                       .format(PLUGIN_NAME, exc))
    return False, ('The {} plug-in could not be loaded. Check that it has been built for this '
                   'Maya version under plugins/mcaMeshTiler/plug-in/.'.format(PLUGIN_NAME))


def _shape(node):
    """
    The mesh shape under a transform, or the shape itself if that is what came in.

    :param node: A transform or a mesh shape.
    :return: The mesh shape.
    :rtype: pm.nt.Mesh
    :raises ValueError: If there is no mesh there.
    """

    node = pm.PyNode(node)
    if isinstance(node, pm.nt.Mesh):
        return node
    shapes = node.getShapes(noIntermediate=True) if hasattr(node, 'getShapes') else []
    for shape in shapes:
        if isinstance(shape, pm.nt.Mesh):
            return shape
    raise ValueError('{} is not a mesh and has no mesh shape under it.'.format(node))


def _shading_engine(shape):
    """
    The shading engine a mesh is assigned to, if any.

    :param pm.nt.Mesh shape: The mesh.
    :return: The shading engine, or None.
    :rtype: pm.nt.ShadingEngine
    """

    for engine in shape.outputs(type='shadingEngine'):
        return engine
    return None


def _enum_value(table, value, label):
    """
    Accept either a name or a raw index for an enum attribute.

    Callers should be able to say ``up_axis='y'`` without memorising that Y is 1,
    but a tool passing the index straight through should still work.

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
def tile_mesh(tile, target, name=None, up_axis='y', height=1.0, height_offset=0.0,
              area_scale=0.0, normal_mode='surface', boundary='edge_and_corner',
              use_mesh_creases=True, crease=0.0, corner=0.0, copy_uvs=True,
              refine_non_quads=True, inherit_shader=True, pin_to_target=False,
              tiles_u=1, tiles_v=1):
    """
    Repeat ``tile`` across every face of ``target``.

    The result is a live mesh: the tiler stays in the graph, so moving,
    deforming or animating the target moves the tiles with it. Bake it down with
    :func:`freeze_tiling` when you are happy.

    :param tile: The mesh to repeat. Transform or shape.
    :param target: The surface to repeat it across. Transform or shape.
    :param str name: Name for the output transform. Defaults to
        ``<target>_tiled``.
    :param up_axis: Which tile axis points away from the surface - ``'x'``,
        ``'y'`` or ``'z'``. Y is the usual one and is what the tool this replaces
        assumed without saying so.
    :param float height: Multiplies how far the tile stands off the surface.
    :param float height_offset: Added to how far it stands off, in world units,
        the same amount everywhere regardless of how curved the surface is.
    :param float area_scale: 0 leaves every tile the same size; 1 scales each one
        by the square root of its face's area, so tiles on a stretched face grow
        to match. In between blends.
    :param normal_mode: ``'face'``, ``'surface'`` or ``'derivative'``.
    :param boundary: ``'edge'`` or ``'edge_and_corner'`` - how the limit surface
        behaves where the target has an open edge.
    :param bool use_mesh_creases: Honour creases authored on the target.
    :param float crease: One sharpness applied to every edge, on top of the
        authored ones.
    :param float corner: One sharpness applied to every vertex.
    :param bool copy_uvs: Copy the tile's UV sets onto the result. Every tile
        lands on the same patch of texture, which is the point.
    :param bool refine_non_quads: Tile triangles and n-gons as well as quads. Off
        means a non-quad target is refused rather than quietly half-tiled.
    :param bool inherit_shader: Assign the tile's shader to the result, so it
        looks right immediately instead of default grey.
    :param int tiles_u: How many tiles fit across each face.
    :param int tiles_v: How many fit down it. 1 x 1 stretches a single tile over
        the whole face, which is all the tool this replaces could do - so a big
        face got a big tile and re-meshing the target was the only way to change
        it. Anything higher fills the face with a grid instead. The counts are
        fixed rather than worked out from face area, because sizing tiles in
        world units would make the tile count depend on the target's geometry,
        and a deforming rig would then change the output mesh's topology
        mid-animation.
    :param bool pin_to_target: Weld the tiles to the target so they stay on it
        wherever the output transform goes. **This makes the output transform
        inert** - the node solves in world space and then cancels out whatever
        the transform does, so moving, rotating or parenting the result appears
        to do nothing at all. Off by default, which leaves the result an ordinary
        object you can move, parent, constrain and animate like any other mesh.
    :return: ``{'tiler', 'transform', 'shape'}`` as PyNodes.
    :rtype: dict
    """

    available, reason = plugin_is_available()
    if not available:
        raise RuntimeError(reason)

    tile_shape = _shape(tile)
    target_shape = _shape(target)
    if tile_shape == target_shape:
        raise ValueError('The tile and the target are the same mesh.')
    if not tile_shape.numVertices():
        raise ValueError('{} has no geometry to repeat.'.format(tile_shape))
    if not target_shape.numVertices():
        raise ValueError('{} has no faces to repeat it across.'.format(target_shape))

    target_name = str(target_shape.getParent().nodeName()).split(':')[-1]
    output_name = name or '{}_tiled'.format(target_name)

    tiler = pm.createNode(NODE_TYPE, name='{}_tiler'.format(output_name))
    transform = pm.createNode('transform', name=output_name)
    shape = pm.createNode('mesh', name='{}Shape'.format(output_name), parent=transform)

    tile_shape.attr('outMesh') >> tiler.attr('tileMesh')
    target_shape.attr('worldMesh[0]') >> tiler.attr('targetMesh')
    tiler.attr('outMesh') >> shape.attr('inMesh')
    if pin_to_target:
        # Bring the world-space result back into whatever space the output
        # transform is in. The tiles then sit on the target no matter where the
        # transform is - and, because the geometry cancels out every move, the
        # transform stops doing anything at all. See the note on pin_to_target.
        transform.attr('worldInverseMatrix[0]') >> tiler.attr('worldToOutput')

    tiler.attr('tileUpAxis').set(_enum_value(UP_AXES, up_axis, 'up_axis'))
    tiler.attr('height').set(height)
    tiler.attr('heightOffset').set(height_offset)
    tiler.attr('areaScale').set(area_scale)
    tiler.attr('normalMode').set(_enum_value(NORMAL_MODES, normal_mode, 'normal_mode'))
    tiler.attr('boundaryInterpolation').set(_enum_value(BOUNDARY_MODES, boundary, 'boundary'))
    tiler.attr('useMeshCreases').set(bool(use_mesh_creases))
    tiler.attr('creaseSharpness').set(crease)
    tiler.attr('cornerSharpness').set(corner)
    tiler.attr('tilesU').set(max(1, int(tiles_u)))
    tiler.attr('tilesV').set(max(1, int(tiles_v)))
    tiler.attr('copyUVs').set(bool(copy_uvs))
    tiler.attr('refineNonQuads').set(bool(refine_non_quads))

    # Tag the pairing rather than inferring it later from connections an artist
    # may have rewired.
    for node, attribute, other in ((tiler, TILE_TAG, tile_shape),
                                   (tiler, TARGET_TAG, target_shape),
                                   (transform, TILER_TAG, tiler)):
        cmds.addAttr(str(node), longName=attribute, attributeType='message')
        other.attr('message') >> node.attr(attribute)

    if inherit_shader:
        engine = _shading_engine(tile_shape)
        if engine:
            pm.sets(engine, forceElement=shape, edit=True)

    # Touch the output so a failure shows up here, where it can be reported,
    # rather than the first time somebody looks at the viewport.
    pm.dgdirty(shape)
    faces = target_shape.numFaces()
    tiles = shape.numFaces() // max(1, tile_shape.numFaces())

    if not tiles:
        # An empty result reported as a success is the exact failure the tool
        # this replaces had: a triangulated target produced nothing, said
        # nothing, and left you looking for the mistake in your own scene. The
        # node writes a warning to the script editor; nobody reads the script
        # editor. Take the half-built graph back out and say why.
        pm.delete(transform)
        if pm.objExists(tiler):
            pm.delete(tiler)
        quads = all(face.numVertices() == 4 for face in target_shape.faces)
        if not quads and not refine_non_quads:
            raise RuntimeError(
                '{} has faces that are not quads, and refine_non_quads is off, so '
                'nothing was tiled. Turn refine_non_quads on, or quadrangulate the '
                'target.'.format(target_shape))
        raise RuntimeError('Tiling {} across {} produced no geometry.'
                           .format(tile_shape, target_shape))

    per_face = max(1, int(tiles_u)) * max(1, int(tiles_v))
    message = '{} tiles from {} faces.'.format(tiles, faces)
    if per_face > 1:
        message += ' {} x {} per face.'.format(int(tiles_u), int(tiles_v))
    if tiles > faces * per_face:
        # Catmull-Clark makes n quads from an n-gon, so a triangulated target
        # yields three tiles per face. Say so rather than letting it look wrong.
        message += (' The target is not all quads, so each non-quad face became '
                    'several tiles.')
    return {'tiler': tiler, 'transform': transform, 'shape': shape}, message


@_safe
def set_face_rotation(tiler, rotations):
    """
    Turn the tiles on particular faces.

    Tiles inherit their orientation from the face they sit on, and on a hand-made
    target that is not always the way round you want. Each step is one quarter
    turn for a quad, one n-th of a turn for an n-gon.

    :param tiler: The tiler node.
    :param dict rotations: Face index to number of steps. Negative turns the
        other way.
    :return: How many faces were set.
    :rtype: int
    """

    tiler = pm.PyNode(tiler)
    for index, steps in rotations.items():
        tiler.attr('faceRotation[{}]'.format(int(index))).set(int(steps))
    return len(rotations), 'Rotated {} faces.'.format(len(rotations))


@_safe
def rotate_selected_faces(tiler, steps=1):
    """
    Turn the tiles on whichever target faces are selected.

    The way this actually gets used: an artist selects the few faces whose scales
    are lying the wrong way and nudges them round.

    :param tiler: The tiler node.
    :param int steps: Quarter turns to add. Negative turns the other way.
    :return: The face indices that were changed.
    :rtype: list
    """

    tiler = pm.PyNode(tiler)
    indices = []
    for component in cmds.filterExpand(cmds.ls(selection=True, flatten=True) or [],
                                       selectionMask=34) or []:
        indices.append(int(component.rsplit('[', 1)[1].rstrip(']')))
    if not indices:
        raise ValueError('Select some faces on the target mesh first.')

    for index in indices:
        plug = tiler.attr('faceRotation[{}]'.format(index))
        plug.set(plug.get() + int(steps))
    return indices, 'Rotated {} faces by {}.'.format(len(indices), steps)


@_safe
def clear_face_rotations(tiler):
    """
    Put every tile back to the orientation its face gives it.

    :param tiler: The tiler node.
    :return: How many entries were removed.
    :rtype: int
    """

    tiler = pm.PyNode(tiler)
    indices = tiler.attr('faceRotation').getArrayIndices()
    for index in indices:
        pm.removeMultiInstance(tiler.attr('faceRotation[{}]'.format(index)), b=True)
    return len(indices), 'Cleared {} rotations.'.format(len(indices))


@_safe
def freeze_tiling(transform):
    """
    Bake the tiles down to a plain mesh.

    Deletes the tiler and everything that fed it, leaving geometry. Do this when
    the target has stopped changing and you want to hand the result to someone
    who does not have the plug-in.

    :param transform: The output transform :func:`tile_mesh` made.
    :return: The transform, now driven by nothing.
    :rtype: pm.nt.Transform
    """

    transform = pm.PyNode(transform)
    shape = _shape(transform)
    tilers = shape.listHistory(type=NODE_TYPE)
    pm.delete(transform, constructionHistory=True)

    # `delete -ch` does not always take the tiler with it. With pin_to_target on,
    # worldToOutput reads the output transform's own matrix, so the node is not
    # purely upstream of the shape and history deletion steps around it. The
    # geometry has already been baked into the shape by this point, so taking the
    # node out by name is safe - but check the face count afterwards rather than
    # before, because getting this wrong leaves an empty mesh that still looks
    # like a mesh in the Outliner.
    for tiler in tilers:
        if pm.objExists(tiler):
            pm.delete(tiler)

    faces = shape.numFaces()
    if not faces:
        raise RuntimeError('Freezing left an empty mesh. Nothing was baked.')
    return transform, 'Baked {} faces. The tiler is gone.'.format(faces)


@_safe
def remove_tiling(transform):
    """
    Take the whole thing back out.

    Nothing the tiler touched was modified on the way in - the tile and the
    target are only ever read - so this leaves the scene as it was found.

    :param transform: The output transform :func:`tile_mesh` made.
    :return: True.
    :rtype: bool
    """

    transform = pm.PyNode(transform)
    tilers = [node for node in transform.listHistory(type=NODE_TYPE)]
    pm.delete(transform)
    for tiler in tilers:
        if pm.objExists(tiler):
            pm.delete(tiler)
    return True, 'Removed the tiling.'


def find_tilers():
    """
    Every tiler in the open scene.

    Safe to call when the plug-in is not loaded - ``ls`` on an unregistered node
    type raises, so it is checked first and an empty list comes back.

    :return: The tiler nodes.
    :rtype: list
    """

    try:
        if NODE_TYPE not in (cmds.allNodeTypes() or []):
            return []
    except Exception:
        return []
    return pm.ls(type=NODE_TYPE)
