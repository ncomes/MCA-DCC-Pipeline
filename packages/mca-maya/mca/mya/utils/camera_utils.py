"""
Modules that contains useful functions related to cameras and play blasting.
"""
# System global imports
import os
# software specific imports
import pymel.core as pm


# MCA python imports
from mca.common import log

from mca.common.utils import fileio, video_utils
from mca.common.resources import resources
from mca.mya.utils import attr_utils, namespace
from mca.mya.animation import time_utils, baking
from mca.mya.rigging.templates import cinematic_camera_template
from mca.mya.rigging import frag, rig_utils
from mca.mya.rigging.frag import frag_rig, display_layers
from mca.mya.utils import constraint
from mca.mya.modifiers import ma_decorators
from mca.mya.pyqt import dialogs

logger = log.MCA_LOGGER

# Camera shape attributes the ubercam **statically copies** from the first shot's
# camera at create / refresh time — NO DG connections, just one-shot value copy.
# Verified live 2026-05-08: any Maya 2025 cache-evaluator-incompatible connection on
# the ubercam shape attrs (choice nodes, anim curves, clip-plane wires of any kind)
# crashes the renderer through shiboken6 the moment a shot camera is moved under
# cached playback. Static set at creation is the only pattern the cache tolerates.
# If animators need per-shot lens variation later, drive it via a ``timeChanged``
# scriptJob in Python that sets these attrs imperatively — never via a DG connection.
UBERCAM_MIRRORED_SHAPE_ATTRS = (
    'focalLength',
    'horizontalFilmAperture',
    'verticalFilmAperture',
    'lensSqueezeRatio',
    'nearClipPlane',
    'farClipPlane',
)


def create_render_window(camera_node=None, resolution=None, render_style='smoothShaded', lighting_style='default', display_textures=True, display_hud=False):
    """
    Create a new model panel and resize the window to account for our resolution settings.

    :param Transform camera_node: The transform of a given camera. Defaults to 'persp'
    :param list[int, int] resolution: Two ints representing the width and height of the final model panel.
    :param str, None render_style: The render style of the model panel. Defaults to "smoothShaded"
    :param str, None lighting_style: The render style for the lighting in the scene, default is 'default'
        'all'
        'active'
        'default'
        'none'
    :param bool display_textures: If textures should be rendered.
    :param bool display_hud: If the Maya HUD should be visible during the render.
    :return: The Window and ModelEditor renderer.
    :rtype: window, modelEditor
    """
    camera_node = camera_node if camera_node and isinstance(camera_node.getShape(), pm.nt.Camera) else pm.PyNode('persp')
    resolution = resolution if resolution and len(resolution) == 2 and all(isinstance(x, int) for x in resolution) else [1920, 1080]

    my_window = pm.window()
    # Slight buffer here for some reason the playblast features don't capture at exact resolution.
    my_window.setWidth(resolution[0] + 2)
    my_window.setHeight(resolution[-1])
    form = pm.formLayout()
    model_editor = pm.modelEditor()
    column = pm.columnLayout('true')
    pm.formLayout(form,
                  edit=True,
                  attachForm=[(column, 'top', 0), (column, 'left', 0), (model_editor, 'top', 0), (model_editor, 'bottom', 0), (model_editor, 'right', 0)],
                  attachNone=[(column, 'bottom'), (column, 'right')],
                  attachControl=(model_editor, 'left', 0, column))
    pm.modelEditor(model_editor,
                   e=True,
                   displayAppearance=render_style,
                   displayTextures=display_textures,
                   displayLights=lighting_style,
                   th=True,
                   camera=camera_node,
                   activeView=True,
                   hud=display_hud,
                   grid=False,
                   allObjects=True)
    pm.modelEditor(model_editor,
                   e=True,
                   nc=False,
                   j=False,
                   df=False,
                   ca=False,
                   lt=False,
                   ikh=False,
                   lc=False,
                   pv=False)
    pm.showWindow(my_window)
    return my_window, model_editor


def playblast_video(file_path, camera_node=None, time_range=None, resolution=None, bg_color=None, display_hud=False, lighting_style='default'):
    """
    Capture a quick video using Maya's internal playblast feature.

    :param str file_path: File path to where the video should be saved. expected extension of ".avi"
    :param Transform camera_node: The transform of a given camera. Defaults to 'persp'
    :param list[int, int], None time_range: The inclusive time range that the video should be captured from. Current frame is the default for None.
    :param list[int, int], None resolution: Two ints representing the width and height of the capture. 1080 is the default for None
    :param list[float, float, float], None bg_color: RGB float values for the background of the captures.
    :param bool display_hud: If the Maya HUD should be visible during the render.
    :param str lighting_style: The render style for the lighting in the scene, default is 'default'
        'all'
        'active'
        'default'
        'none'
    :return: The resulting file path.
    :rtype: str
    """
    if not time_range or not all(isinstance(x, int) for x in time_range):
        time_range = time_utils.get_times()

    original_bg_color = None
    if bg_color:
        if isinstance(bg_color, list) and len(bg_color) == 3:
            original_bg_color = pm.displayRGBColor('background', q=True)
            pm.displayRGBColor('background', *bg_color)
        else:
            raise ValueError('Background color values are not a list of 3 floats: {0}'.format(bg_color))

    my_window, model_editor = create_render_window(camera_node, resolution, display_hud=display_hud, lighting_style=lighting_style)

    if not file_path.endswith('.avi'):
        file_path = f'{file_path}.avi'

    pm.select(None)
    pm.refresh()
    # Avi export doesn't work with arg "completeFilename", instead using "filename" which effectively works the same.
    fileio.touch_path(file_path, True)
    pm.playblast(percent=100,
                 startTime=time_range[0],
                 endTime=time_range[1],
                 filename=file_path,
                 format='avi',
                 viewer=False,
                 editorPanelName=model_editor,
                 forceOverwrite=True,
                 showOrnaments=True,
                 useTraxSounds=False,
                 sound=None)

    if original_bg_color:
        pm.displayRGBColor('background', *original_bg_color)

    my_window.delete()
    return file_path


def playblast_images(file_path, camera_node=None, frame_list=None, resolution=None, bg_color=None, hud=False, lighting_style='default'):
    """
    Capture images at frames using Maya's internal playblast feature.

    :param str file_path: A single path, or a directory to save multiple captures.
    :param Transform camera_node: The transform of a given camera.
    :param list[int], None frame_list: A list of frames to capture at. Or none to capture just the current frame.
    :param list[int, int] resolution: Two ints representing the width and height of the capture.
    :param list[float, float, float], None bg_color: RGB float values for the background of the captures.
    :param bool hud: If the Maya HUD should be visible during the render.
    :param str lighting_style: The render style for the lighting in the scene, default is 'default'
        'all'
        'active'
        'default'
        'none'
    :return: A list of all captured files.
    :rtype: list[str]
    """
    if isinstance(frame_list, int):
        frame_list = [frame_list]

    if not frame_list or not all(isinstance(x, int) for x in frame_list):
        # If our frame range is bad just use the current frame.
        frame_list = [pm.currentTime()]

    my_window, model_editor = create_render_window(camera_node, resolution, display_hud=hud, lighting_style=lighting_style)

    original_bg_color = None
    if bg_color:
        if isinstance(bg_color, list) and len(bg_color) == 3:
            original_bg_color = pm.displayRGBColor('background', q=True)
            pm.displayRGBColor('background', *bg_color)
        else:
            raise ValueError('Background color values are not a list of 3 floats: {0}'.format(bg_color))

    pm.select(None)
    pm.refresh()
    if file_path.endswith('.jpg'):
        # Single frame playblast.
        fileio.touch_path(file_path, True)
        pm.playblast(percent=100,
                     frame=frame_list[0],
                     format="image",
                     compression='jpg',
                     viewer=False,
                     editorPanelName=model_editor,
                     forceOverwrite=True,
                     showOrnaments=False,
                     completeFilename=file_path)
    else:
        # Multi frame playblast.
        for x_file in os.listdir(file_path):
            if os.path.isfile(x_file) and 'still' in os.path.basename(x_file):
                fileio.touch_path(os.path.join(file_path, x_file), True)
        pm.playblast(percent=100,
                     filename=os.path.join(file_path, 'stills'),
                     frame=frame_list,
                     format="image",
                     compression='jpg',
                     viewer=False,
                     editorPanelName=model_editor,
                     forceOverwrite=True,
                     showOrnaments=False)

    if original_bg_color:
        pm.displayRGBColor('background', *original_bg_color)

    my_window.delete()
    return file_path if file_path.endswith('.jpg') else [os.path.join(file_path, x) for x in os.listdir(file_path) if 'stills.' in x]


def playblast_single_frame(file_path, image_name=None, camera_node=None, frame=None, resolution=None, bg_color=None, hud=False, lighting_style='default'):
    """
    
    :param str file_path: A single path.
    :param str image_name: name of the image file to capture.
    :param Transform camera_node: The transform of a given camera.
    :param int, None frame: A list of frames to capture at. Or none to capture just the current frame.
    :param list[int, int] resolution: Two ints representing the width and height of the capture.
    :param list[float, float, float], None bg_color: RGB float values for the background of the captures.
    :param bool hud: If the Maya HUD should be visible during the render.
    :param str lighting_style: The render style for the lighting in the scene, default is 'default'
        'all'
        'active'
        'default'
        'none'
    :return: A list of all captured files.
    :rtype: list[str]
    """
    
    image = playblast_images(file_path=file_path, 
                             camera_node=camera_node, 
                             frame_list=[frame], 
                             resolution=resolution,
                             bg_color=bg_color,
                             hud=hud,
                             lighting_style=lighting_style)
    
    if not image:
        logger.warning('Something went wrong when trying to capture an image.  No Image was captured!')
        return
    image = image[0]
    
    name = os.path.basename(image)
    directory = os.path.dirname(image)
    new_name = image_name
    if not new_name:
        return image
    
    new_name = f'{new_name.lower()}.jpg'
    full_path_name = os.path.join(directory, new_name)
    if os.path.exists(full_path_name):
        fileio.touch_path(full_path_name, remove=True)
    new_image_name = fileio.rename_file(name=name, directory=directory, new_name=new_name.lower())
    return new_image_name


def capture_and_compress_video(file_path, camera_node=None, time_range=None, resolution=None, delete_uncompressed=True, background=None, hud=False, lighting_style='default'):
    """
    Capture a quick video using Maya's internal playblast feature.

    :param str file_path: File path to where the video should be saved with an expected extension of .mp4.
    :param Transform camera_node: The transform of a given camera. Defaults to 'persp'
    :param list[int, int] time_range: The inclusive time range that the video should be captured from.
    :param list[int, int] resolution: Two ints representing the width and height of the capture.
    :param bool delete_uncompressed: If the original raw playblast avi should be deleted.
    :param list[float, float, float], None background: RGB float values for the background of the captures.
    :param bool hud: If the Maya HUD should be visible during the render.
    :param str lighting_style: The render style for the lighting in the scene, default is 'default'
        'all'
        'active'
        'default'
        'none'
    :return: The resulting file path.
    :rtype: str
    """
    if not file_path.endswith('.mp4'):
        logger.warning(f'{file_path}: File path must be to a valid .mp4')
        return

    fileio.touch_path(file_path)
    avi_path = file_path.replace('.mp4', '.avi')

    # Send the file path without extension we'll always get an .avi in return.
    temp_file_path = playblast_video(os.path.join(os.path.dirname(file_path), 'temp.avi'),
                                     camera_node=camera_node,
                                     time_range=time_range,
                                     resolution=resolution,
                                     bg_color=background,
                                     display_hud=hud,
                                     lighting_style=lighting_style)
    fileio.touch_path(avi_path, True)
    os.rename(temp_file_path, avi_path)

    # Run MP4 conversion.
    return_file_path = video_utils.ffmpeg_convert_to_mp4(avi_path)

    if return_file_path and os.path.exists(return_file_path) and delete_uncompressed:
        fileio.touch_path(avi_path, remove=True)

    return return_file_path


def create_mca_ubercam(shot_node_list, asset_id=None):
    """
    Legacy entry point for callers (currently ``shot_utils``) that just want a built
    ubercam from a shot list. Delegates to the same import-based flow as
    ``create_mca_ubercam_cmd``: imports the published ubercam rig, tags the camera, and
    wires the per-shot drivers. The old per-attribute kwargs (film aperture, clip planes,
    etc.) are gone — those values now come from the rig file itself, which is the whole
    point of importing a published rig instead of building one in code.

    :param list(pm.nt.Shot) shot_node_list: Shots whose cameras drive the ubercam.
    :param str asset_id: Cameras-category asset id whose rig to import. None falls back
        to the CinematicCameraTemplate default.
    :return: Returns the imported ubercam transform.
    :rtype: pm.nt.Transform

    """

    uc_transform, ubercam_shape = _import_ubercam_rig(asset_id=asset_id)
    sorted_shots = sorted(shot_node_list, key=lambda s: s.startFrame.get())
    _attach_shots_to_ubercam(uc_transform, ubercam_shape, sorted_shots)
    return uc_transform


def _import_ubercam_rig(asset_id=None):
    """
    Imports the registered ubercam rig (the published ``*_rig.ma`` under the asset's
    source-rigs folder) and returns the rig's camera transform/shape pair. The imported
    file ships a real FRAGRoot with a CameraComponent — we don't build the rig procedurally
    here. We just tag the rig's camera with the ``MCAUberCam`` bool attr (so
    ``find_ubercam`` keeps working) and park the rig's ``all_grp`` under the scene's
    ``cameraGrp`` if one exists.

    :param str asset_id: Cameras-category asset id whose rig should be imported. Falls
        back to the CinematicCameraTemplate default when None.
    :return: A (transform, shape) tuple for the imported ubercam.
    :rtype: tuple[pm.nt.Transform, pm.nt.Camera]

    """

    resolved_asset_id = asset_id or cinematic_camera_template.DEFAULT_UBERCAM_ASSET_ID
    # Force the MCAUberCam namespace so remove_ubercam_cmd's namespace purge still tears
    # the rig down cleanly. rig_utils.import_asset handles purging the existing namespace
    # and resetting after the import via @keep_namespace_decorator.
    if 'MCAUberCam' in namespace.get_all_namespaces():
        namespace.purge_namespace('MCAUberCam')

    frag_root = rig_utils.import_asset(asset_id=resolved_asset_id, ns='MCAUberCam')
    if frag_root is None:
        raise RuntimeError(
            f'Failed to import ubercam rig for asset {resolved_asset_id!r}. '
            f'Make sure ubercam_rig.ma exists under the asset\'s _Source/Rigs folder.'
        )

    frag_rig_node = frag_root.get_rig()
    if frag_rig_node is None:
        raise RuntimeError('Imported ubercam asset has no FRAGRig.')

    cam_components = frag_rig_node.get_frag_children(of_type=frag.CameraComponent)
    if not cam_components:
        raise RuntimeError('Imported ubercam rig has no CameraComponent.')

    uc_transform = cam_components[0].get_cam()
    if uc_transform is None:
        raise RuntimeError('Ubercam CameraComponent did not return a camera transform.')

    # Tag for find_ubercam(). Rig file may already carry the attr; addAttr would error.
    if not uc_transform.hasAttr('MCAUberCam'):
        uc_transform.addAttr('MCAUberCam', at='bool')

    if pm.animLayer("BaseAnimation", q=True, exists=True):
        pm.animLayer("BaseAnimation", edit=True, lock=False)
        pm.animLayer("BaseAnimation", edit=True, selected=True)
        pm.animLayer("BaseAnimation", edit=True, preferred=True)

    uc_transform.v.set(0)
    pm.lookThru(uc_transform)

    cameras_grp = next((x for x in pm.ls(type=pm.nt.Transform) if x.hasAttr('cameraGrp')), None)
    if cameras_grp:
        try:
            frag_rig_node.all_grp.setParent(cameras_grp)
        except Exception as exc:
            logger.warning(f'Could not parent ubercam rig under cameraGrp: {exc}')

    # Animators drive the rig through the per-shot reference cams; the ubercam's own
    # flag controls shouldn't clutter the viewport. Hide the flags layer on import — the
    # rig file usually ships with it visible. Toggleable from the layer editor if needed.
    _hide_ubercam_flag_layers(frag_rig_node)

    ubercam_shape = uc_transform.getShape()

    # Suppress the ubercam shape's draw-gate / overlay flags. The shape lives in
    # ``skins_lyr`` (displayType=2 'reference') so anything it draws absorbs clicks
    # without selecting — and ``displayGateMask`` ships ON in the rig file, which
    # paints a fill rectangle over the entire frame outside the resolution gate
    # whenever the artist looks through the ubercam. The result is invisible-but-
    # pickable geometry that swallows clicks on shot cameras and rig-adjacent props.
    # Killing these flags keeps the camera fully functional but pick-transparent.
    for attr_name in ('displayFilmGate', 'displayResolution', 'displayGateMask',
                       'displayFieldChart', 'displaySafeAction', 'displaySafeTitle',
                       'displayFilmPivot', 'displayFilmOrigin'):
        if ubercam_shape.hasAttr(attr_name):
            try:
                ubercam_shape.attr(attr_name).set(False)
            except Exception:
                # Locked or otherwise un-settable — best-effort, not worth aborting
                # the whole import over a single overlay flag.
                pass

    return uc_transform, ubercam_shape


def _hide_ubercam_flag_layers(frag_rig_node):
    """
    Hides the rig's flag display layers so the ubercam controls are invisible by default.
    The rig file ships with serialized DisplayLayers; we just flip the visibility on the
    flag-related ones. Best-effort — if the rig doesn't have a DisplayLayers component,
    we log and move on rather than failing the whole import.

    :param frag.FRAGRig frag_rig_node: The imported ubercam FRAGRig.

    """

    try:
        dl_children = frag_rig_node.get_frag_children(of_type=display_layers.DisplayLayers)
    except Exception as exc:
        logger.warning(f'Could not query display-layers component on ubercam rig: {exc}')
        return
    if not dl_children:
        # Rig file pre-dates the DisplayLayers component. Fall back to hiding any layer
        # whose name matches the FLAGS_LYR convention so older rigs still hide cleanly.
        for layer in pm.ls(type=pm.nt.DisplayLayer):
            base_name = layer.nodeName().split(':')[-1]
            if base_name in (display_layers.FLAGS_LYR,
                             display_layers.FLAGS_CONTACT_LYR,
                             display_layers.FLAGS_DETAIL_LYR):
                layer.v.set(0)
        return
    dl_node = dl_children[0]
    for layer_name in (display_layers.FLAGS_LYR,
                       display_layers.FLAGS_CONTACT_LYR,
                       display_layers.FLAGS_DETAIL_LYR):
        try:
            dl_node.hide_layer(layer_name)
        except Exception as exc:
            logger.warning(f'Could not hide layer {layer_name!r} on ubercam rig: {exc}')


def _attach_shots_to_ubercam(uc_transform, ubercam, shot_node_list):
    """
    Wires the per-shot drivers on the ubercam. The shot cameras drive the rig's f_cam flag
    via a single ``choice`` node connected to ``f_cam.offsetParentMatrix`` (each shot's
    ``worldMatrix[0]`` becomes one of the choice's inputs, time-keyed by shot start
    frame); the f_cam flag drives the cam joint via the rig's standard FK behavior; and
    the ubercam transform is parent-constrained to the cam joint by
    ``_ensure_camera_follows_cam_joint``. The result is shot_cam → f_cam (via choice on
    offsetParentMatrix) → cam_joint (via FK) → camera (static constraint).

    The choice-on-offsetParentMatrix design replaced an earlier parent-constraint-on-
    f_cam with time-varying weights, which kept hard-crashing Maya 2025's cache evaluator
    through ``shiboken6.abi3.dll``. The cache cannot tolerate time-keyed constraint
    weight curves on the cinematic data path. Pure connection switching via choice nodes
    works under cached playback because there are no constraint nodes in the dirty
    propagation graph between shot cams and the ubercam.

    Per shot we also add one ``choice`` node per shape attribute in
    ``UBERCAM_MIRRORED_SHAPE_ATTRS`` (focalLength, apertures, lens squeeze) so the
    ubercam shape adopts the active shot camera's lens/framing settings. **Do not** add
    nearClipPlane / farClipPlane to that list — those crash the cache evaluator too
    (separate from the constraint issue).

    :param pm.nt.Transform uc_transform: The ubercam transform.
    :param pm.nt.Camera ubercam: The ubercam shape.
    :param list[pm.nt.Shot] shot_node_list: Shots to attach (will be sorted by start frame).

    """

    # Reroute the camera through the cam joint before wiring per-shot drivers — without
    # this the rig template's f_cam→camera constraint would fight the shot-following
    # constraints we're about to put on f_cam.
    _ensure_camera_follows_cam_joint(uc_transform)

    cam_flag = get_ubercam_cam_flag()
    drive_target = cam_flag.node if cam_flag is not None else uc_transform

    # Belt-and-suspenders sweep: delete any parent constraint already under f_cam,
    # whether from the legacy constraint-based code path or from a partial previous
    # build. The crash on 2026-05-08 traced to a stale ``f_cam_parentConstraint1``
    # surviving alongside the new offsetParentMatrix wiring — Maya 2025's cache
    # evaluator can't tolerate two drivers on the same transform plugs and dies.
    # ``_clear_ubercam_drivers`` runs this on refresh, but first-time-create skipped
    # it; doing it here means both code paths land at the same clean baseline.
    stale_pcs = list(set(pm.listRelatives(drive_target, type='parentConstraint', children=True) or []))
    if stale_pcs:
        logger.info(f'Removing stale parent constraints on {drive_target}: {stale_pcs}')
        pm.delete(stale_pcs)
    # Also disconnect any upstream offsetParentMatrix driver — same node could collide
    # with the choice we're about to create.
    existing_opm = drive_target.offsetParentMatrix.listConnections(source=True, destination=False) or []
    existing_opm = list({n for n in existing_opm if isinstance(n, pm.nt.Choice)})
    if existing_opm:
        logger.info(f'Removing stale offsetParentMatrix choice nodes on {drive_target}: {existing_opm}')
        pm.delete(existing_opm)

    sorted_shots = sorted(shot_node_list, key=lambda s: s.startFrame.get())
    for i, shot in enumerate(sorted_shots):
        try:
            _attach_one_shot_to_ubercam(uc_transform=uc_transform,
                                        ubercam=ubercam,
                                        drive_target=drive_target,
                                        shot=shot,
                                        shot_index=i,
                                        sorted_shots=sorted_shots)
        except Exception as exc:
            # Shot-level failures used to abort the whole rebuild halfway through, leaving
            # a half-wired ubercam in the scene. Log and move on — better to have N-1
            # shots wired than a corrupt rig.
            logger.error(f'Failed wiring shot {shot} into ubercam: {exc}', exc_info=True)

    # Static one-shot copy of the lens attrs from the first shot's camera. No DG
    # connection — just plain value assignment, which the cache evaluator tolerates.
    _copy_static_lens_attrs_from_first_shot(ubercam, sorted_shots)


def _copy_static_lens_attrs_from_first_shot(ubercam, sorted_shots):
    """
    Copy the lens attribute values listed in ``UBERCAM_MIRRORED_SHAPE_ATTRS`` from the
    first shot's camera shape onto the ubercam shape. **No DG connection** — just a
    value assignment via ``setAttr``. Maya 2025's cache evaluator crashes on any DG
    connection feeding the ubercam shape attrs, so we accept the trade-off: lens
    settings stay constant across the whole cinematic rather than switching per shot.
    Animators who need per-shot variation can either edit the ubercam shape directly
    or wire a ``timeChanged`` scriptJob in Python that sets the values imperatively.

    :param pm.nt.Camera ubercam: The ubercam shape.
    :param list[pm.nt.Shot] sorted_shots: Shots sorted by start frame; we copy from the
        first one. Empty list is a no-op.

    """

    if not sorted_shots:
        return
    first_shot = sorted_shots[0]
    cam_xform = first_shot.currentCamera.get()
    if cam_xform is None:
        return
    cam_shape = cam_xform.getShape() if isinstance(cam_xform, pm.nt.Transform) else cam_xform
    if not isinstance(cam_shape, pm.nt.Camera):
        logger.warning(f'First shot {first_shot} camera has no Camera shape; skipping lens-attr copy.')
        return
    for attr_name in UBERCAM_MIRRORED_SHAPE_ATTRS:
        try:
            value = cam_shape.attr(attr_name).get()
            ubercam.attr(attr_name).set(value)
        except Exception as exc:
            logger.warning(f'Could not copy {attr_name} from {cam_shape} to ubercam: {exc}')


def _attach_one_shot_to_ubercam(uc_transform, ubercam, drive_target, shot, shot_index, sorted_shots):
    """
    Wires a single shot into the accumulating ubercam driver network. Split out from
    ``_attach_shots_to_ubercam`` so per-shot failures can be caught without losing the
    rest of the rebuild — and so the per-shot logic is small enough to read at a glance.

    :param pm.nt.Transform uc_transform: The ubercam transform.
    :param pm.nt.Camera ubercam: The ubercam shape.
    :param pm.nt.Transform drive_target: f_cam flag (when rigged) or uc_transform (fallback).
    :param pm.nt.Shot shot: The shot to wire.
    :param int shot_index: Index of ``shot`` within ``sorted_shots``.
    :param list[pm.nt.Shot] sorted_shots: All shots, sorted by start frame.

    """

    cam_xform = shot.currentCamera.get()
    if not cam_xform:
        return
    # Self-reference guard: a shot pointing at the ubercam would build a feedback cycle.
    if cam_xform == uc_transform:
        logger.warning(f'Shot {shot} points at the ubercam itself; skipping to avoid a feedback cycle.')
        return

    # Shape-attribute reads come from the camera shape, not the transform.
    cam_shape = cam_xform.getShape() if isinstance(cam_xform, pm.nt.Transform) else None
    if not isinstance(cam_shape, pm.nt.Camera):
        logger.warning(f'Shot {shot} camera {cam_xform} has no camera shape; skipping shape-attr wiring.')
        cam_shape = None

    maya_start_frame = int(round(shot.startFrame.get()))
    maya_end_frame = int(round(shot.endFrame.get()))

    # World transform driver for f_cam — single choice node feeding f_cam.offsetParentMatrix.
    # Each shot's worldMatrix[0] becomes one input on the choice; the choice's time-keyed
    # selector picks which one is active at any frame. This replaces an earlier parent
    # constraint with time-varying weight keys; the constraint pattern hard-crashed Maya
    # 2025's cache evaluator through shiboken6 on every camera move. Pure connection
    # switching has no constraint nodes in the dirty path, which the cache tolerates.
    matrix_choice_inputs = pm.choice(drive_target,
                                     n='ubercam_worldMatrix_choice',
                                     at='offsetParentMatrix',
                                     t=[maya_start_frame, maya_end_frame],
                                     index=shot_index)
    cam_xform.worldMatrix[0] >> matrix_choice_inputs[0]

    # Lens attributes are NOT wired here — the cache evaluator crashes on any DG
    # connection feeding the ubercam shape attrs. Per-shot lens settings get a one-
    # shot static copy at the end of ``_attach_shots_to_ubercam`` instead, sourced
    # from the first shot's camera. See ``_copy_static_lens_attrs_from_first_shot``.


def find_ubercam():
    """
    Locates the existing MCAUberCam in the scene, if any.

    :return: A (transform, shape) tuple, or (None, None) if no ubercam exists.
    :rtype: tuple[pm.nt.Transform | None, pm.nt.Camera | None]

    """

    for cam_shape in pm.ls(type=pm.nt.Camera):
        cam_xform = cam_shape.getTransform()
        if cam_xform and cam_xform.hasAttr('MCAUberCam'):
            return cam_xform, cam_shape
    return None, None


def _clear_ubercam_drivers(uc_transform, ubercam_shape):
    """
    Wipes the per-shot drivers (parent constraints on f_cam, choice nodes for every
    mirrored shape attribute, and any anim curves left on those attrs) off an existing
    ubercam so they can be rebuilt against the current shot set. Leaves the ubercam
    transform, its rig, and the MCAUberCam_grp in place. The cam_joint → camera constraint
    added by ``_ensure_camera_follows_cam_joint`` is preserved; in the unrigged fallback we
    clear constraints from the camera transform directly.

    Also clears legacy per-shot constraints from the world offset_flag in case we're
    refreshing a scene that was built with the older offset_flag-driven design.

    :param pm.nt.Transform uc_transform: The ubercam transform.
    :param pm.nt.Camera ubercam_shape: The ubercam shape.

    """

    cam_flag = get_ubercam_cam_flag()
    drive_target = cam_flag.node if cam_flag is not None else uc_transform

    # Clear legacy parent constraints on f_cam from the older constraint-driven design.
    # Current builds use ubercam_worldMatrix_choice → f_cam.offsetParentMatrix instead;
    # but a refresh on a scene built with the previous code may still have constraints
    # parented under the drive target.
    pcs = list(set(pm.listRelatives(drive_target, type='parentConstraint', children=True) or []))
    if pcs:
        pm.delete(pcs)

    # Source-based cleanup: walk back from each driven attribute and delete any Choice
    # / AnimCurve that's feeding it. Namespace-agnostic, so it catches the rig file's
    # serialized choice nodes (e.g. 'MCAUberCam:ubercam_fl_choice') along with our own.
    sources_to_clean = [drive_target.offsetParentMatrix]
    for attr_name in UBERCAM_MIRRORED_SHAPE_ATTRS:
        sources_to_clean.append(ubercam_shape.attr(attr_name))
    for plug in sources_to_clean:
        upstream = plug.listConnections(source=True, destination=False) or []
        upstream = list({n for n in upstream if isinstance(n, (pm.nt.Choice, pm.nt.AnimCurve))})
        if upstream:
            pm.delete(upstream)


def get_ubercam_frag_rig():
    """
    Returns the FRAGRig wrapping the ubercam, or None if no rig is present.

    Resolves the rig via the camera's ``fragParent`` message connection (wired by
    ``CameraComponent.create``) rather than walking the DAG — the ubercam transform
    lives under ``MCAUberCam_grp``/``cameraGrp``, not under the rig's ``all_grp``,
    so a DAG walk would miss the rig and we'd silently fall back to driving the
    camera transform directly (which nukes the rig's cam_flag→camera constraint
    on refresh and re-routes shot following around the offset_flag).

    :return: The FRAGRig wrapping the ubercam, or None.
    :rtype: frag.FRAGRig | None

    """

    uc_transform, _ = find_ubercam()
    if uc_transform is None or not uc_transform.hasAttr('fragParent'):
        return None
    try:
        cam_component_nodes = uc_transform.fragParent.listConnections() or []
        if not cam_component_nodes:
            return None
        cam_component = frag.FRAGNode(cam_component_nodes[0])
        found_root = frag.get_frag_root(cam_component)
        if not found_root:
            return None
        return found_root.get_rig()
    except Exception:
        return None


def get_ubercam_cam_flag():
    """
    Returns the f_cam flag of the ubercam rig's CameraComponent — the controller that the
    per-shot parent constraints should drive. Animation lives on f_cam, propagates through
    the cam joint via the rig's standard FK behavior, and the camera follows the joint via
    the constraint set up by ``_ensure_camera_follows_cam_joint``.

    :return: The f_cam Flag, or None if the ubercam isn't rigged or has no CameraComponent.
    :rtype: frag_flag.Flag | None

    """

    uc_rig = get_ubercam_frag_rig()
    if uc_rig is None:
        return None
    cam_components = uc_rig.get_frag_children(of_type=frag.CameraComponent)
    if not cam_components:
        return None
    return cam_components[0].get_cam_flag()


def get_ubercam_cam_joint():
    """
    Returns the bind cam joint of the ubercam rig's CameraComponent. The joint is the
    direct driver of the ubercam transform (see ``_ensure_camera_follows_cam_joint``),
    sitting between f_cam (which animators drive) and the camera (which follows).

    :return: The cam joint, or None if the ubercam isn't rigged or has no CameraComponent.
    :rtype: pm.nt.Joint | None

    """

    uc_rig = get_ubercam_frag_rig()
    if uc_rig is None:
        return None
    cam_components = uc_rig.get_frag_children(of_type=frag.CameraComponent)
    if not cam_components:
        return None
    bind_joints = cam_components[0].bind_joints
    if not bind_joints:
        return None
    return bind_joints[0]


def _ensure_camera_follows_cam_joint(uc_transform):
    """
    Ensures the ubercam transform is parent-constrained to the rig's cam joint rather than
    to f_cam. The rig template wires f_cam → camera by default, but we want f_cam to be
    free to receive per-shot parent constraints from the shot cameras. By rerouting the
    camera through the cam joint we get a clean chain — shot_cam → f_cam → cam_joint →
    camera — where animation lives on f_cam (clean export target) and the camera follows
    passively through the rig.

    Idempotent: a cam_joint → camera constraint already in place is left alone; otherwise
    any existing parent constraints on the camera transform (typically the template's
    f_cam → camera one) are deleted and replaced.

    :param pm.nt.Transform uc_transform: The ubercam transform.

    """

    cam_joint = get_ubercam_cam_joint()
    if cam_joint is None:
        return
    # Parent constraints default to being parented under the constrained transform, so
    # listRelatives finds them reliably regardless of which message-connection direction
    # PyMEL would surface for a given Maya version. listConnections with directional
    # filters has bitten us here before — it missed the rig file's flag→cam constraint
    # and left it intact while pm.parentConstraint(cam_joint, uc, mo=True) silently added
    # cam_joint as a *second target* on the same constraint, producing a 50/50 blend
    # between the rig flag (origin) and the cam joint. Hence the camera lagging behind.
    existing = list(set(pm.listRelatives(uc_transform, type='parentConstraint', children=True) or []))
    for pc in existing:
        targets = pc.getTargetList()
        if cam_joint in targets and len(targets) == 1:
            return
    if existing:
        pm.delete(existing)
    constraint.parent_constraint_safe(cam_joint, uc_transform, mo=True)


def create_mca_ubercam_cmd(asset_id=None):
    """
    Idempotent ubercam command. On first call this imports the published ubercam rig
    (``ubercam_rig.ma`` under the registered Cameras-category asset's source-rigs folder),
    tags the rig's camera as MCAUberCam, parks the rig under ``cameraGrp``, and wires the
    per-shot drivers. On subsequent calls the imported rig is reused — only the per-shot
    drivers are wiped and rebuilt against the current shot list. Persistence matters
    because the FRAGRig is what Animation Exporter binds anim sequences to; tearing it
    down would orphan every registered sequence.

    :param str asset_id: Cameras-category asset id whose rig should be imported on the
        first call. Ignored on subsequent calls since the existing rig is reused as-is.
        When None the CinematicCameraTemplate default is used.

    """

    shot_node_list = pm.ls(type=pm.nt.Shot)
    if not shot_node_list:
        return None

    uc_transform, ubercam_shape = find_ubercam()
    if uc_transform is not None:
        sorted_shots = sorted(shot_node_list, key=lambda s: s.startFrame.get())
        _clear_ubercam_drivers(uc_transform, ubercam_shape)
        _attach_shots_to_ubercam(uc_transform, ubercam_shape, sorted_shots)
        logger.info('Refreshed ubercam shot drivers.')
        return uc_transform

    new_uc_transform, ubercam_shape = _import_ubercam_rig(asset_id=asset_id)
    sorted_shots = sorted(shot_node_list, key=lambda s: s.startFrame.get())
    _attach_shots_to_ubercam(new_uc_transform, ubercam_shape, sorted_shots)
    logger.info(f'Imported ubercam rig: {new_uc_transform.name()} (asset: {asset_id or "<default>"})')
    return new_uc_transform



def rig_cinematic_camera_cmd():
    """
    Command to rig selected camera.

    """

    selection_list = pm.selected()
    for camera_xform in selection_list:
        if camera_xform.hasAttr('focalLength'):
            temp_loc = None
            cam_trans = 0.0
            cam_rot = 0.0
            start_time, end_time = time_utils.get_keyframe_range_from_nodes([camera_xform])
            if not end_time:
                cam_trans = camera_xform.getTranslation()
                cam_rot = camera_xform.getRotation()
            else:
                anim_curve_list = camera_xform.listConnections(type=pm.nt.AnimCurve)
                temp_loc = rig_utils.create_locator_at_object(camera_xform)
                temp_con = constraint.parent_constraint_safe(camera_xform, temp_loc, mo=False)
                baking.bake_objects([temp_loc], bake_range=[start_time, end_time])
                pm.delete(temp_con)
                pm.delete(anim_curve_list)

            for attr in attr_utils.TRANSLATION_ATTRS + attr_utils.ROTATION_ATTRS:
                camera_xform.setAttr(attr, 0)

            cam_rig = cinematic_camera_template.CinematicCameraTemplate().build(**{'cam': camera_xform})

            frag_children = [frag.FRAGNode(x) for x in cam_rig.fragChildren.listConnections()]
            cam_comp = [x for x in frag_children if isinstance(x, frag.CameraComponent)][0]
            cam_flag = cam_comp.get_flags()[0]

            if temp_loc:
                temp_con = constraint.parent_constraint_safe(temp_loc, cam_flag, mo=False)
                baking.bake_objects([cam_flag], bake_range=[start_time, end_time])
                pm.delete(temp_con)
                pm.delete(temp_loc)
            else:
                cam_flag.setRotation(cam_rot)
                cam_flag.setTranslation(cam_trans)

            camera_grp = None
            for node in pm.ls(type=pm.nt.Transform):
                if node.hasAttr('cameraGrp'):
                    camera_grp = node
                    break
            if camera_grp:
                cam_rig.all_grp.setParent(camera_grp)



def remove_ubercam_cmd():
    """
    Purges ubercam namespace then looks to see if any of the ubercam objects exist in case they were not in NS.

    """

    ubercam_namespace = 'MCAUberCam'
    ubercam_objects = ['MCAUberCam']

    if ubercam_namespace in namespace.get_all_namespaces():
        namespace.purge_namespace(ubercam_namespace)
    for uc_obj in ubercam_objects:
        if pm.objExists(uc_obj):
            pm.delete(uc_obj)
    # Choice nodes are created in the root namespace (after the namespace decorator
    # exits) and there's one per shot per mirrored attribute, so sweep them by glob.
    # Includes the legacy 'ubercam_fl_choice*' name from before the multi-attr refactor.
    legacy_globs = ['ubercam_fl_choice*']
    attr_globs = [f'ubercam_{attr_name}_choice*' for attr_name in UBERCAM_MIRRORED_SHAPE_ATTRS]
    for glob in legacy_globs + attr_globs:
        for choice_node in pm.ls(glob, type=pm.nt.Choice):
            pm.delete(choice_node)


def camera_is_rigged(camera_xform):
    """
    Checks if a given camera is rigged.

    :param pm.nt.Transform camera_xform: Camera to check for rigged status of.
    :return: Returns True if the camera is rigged, False otherwise.
    :rtype: bool

    """

    found_rig = False
    if camera_xform.hasAttr('fragParent'):
        frag_parent = camera_xform.fragParent.listConnections()
        if frag_parent:
            found_rig = True
    return found_rig


def get_camera_flag_from_camera(camera_xform):
    """
    Finds the camera flag for a given camera.

    :param pm.nt.Transform camera_xform: Camera to find flag for
    :return: Returns the flag or None if no flag found.
    :rtype: pm.nt.Transform or None
    """
    cam_flag = None
    if camera_xform.hasAttr('fragParent'):
        frag_parent = camera_xform.fragParent.listConnections()
        if frag_parent:
            camera_component = frag.FRAGNode(frag_parent[0])
            cam_flag = camera_component.get_cam_flag()
    return cam_flag


def get_camera_from_flag(flag_node):
    """
    Finds the constrained camera from a flag node on a camera rig.

    :param pm.nt.Transform flag_node: Flag node on the camera rig.
    :return: Returns the camera or None if no camera is found.
    :rtype: pm.nt.Transform or None

    """
    frag_rig_node = frag_rig.get_frag_rig(flag_node)
    if not frag_rig_node:
        logger.warning(f'{flag_node} is not part of a FRAG rig.')
        return None
    camera_component = frag_rig_node.get_frag_children(of_type=frag.CameraComponent)

    if not camera_component:
        logger.warning(f'Could not find camera component for {flag_node}.')
        return None

    cam = camera_component[0].get_cam()
    return cam



def select_camera_from_flag_cmd():
    """
    Command to select the camera from a flag node on a camera rig.

    """

    selected_objs = pm.selected()
    if selected_objs:
        flag_node = selected_objs[0]
        cam = get_camera_from_flag(flag_node)
        if cam:
            pm.select(cam, r=True)
    else:
        logger.warning('Please select a camera rig.')



def copy_camera_cmd():
    """
    Command to copy settings between selected cameras

    """

    selection_list = pm.selected()
    camera_list = []
    for obj in selection_list:
        if isinstance(obj, pm.nt.Camera):
            camera_xform = obj.getTransform()
            camera_list.append(camera_xform)
        elif isinstance(obj, pm.nt.Transform):
            obj_shape = obj.getShape()
            if isinstance(obj_shape, pm.nt.Camera):
                camera_list.append(obj)
            else:
                cam_from_flag = get_camera_from_flag(obj)
                if cam_from_flag:
                    camera_list.append(cam_from_flag)
    if len(camera_list) > 1:
        copy_camera(camera_list)
    else:
        dialogs.info_prompt('Copy Camera Error', 'Please select at least two cameras or camera rigs.', icon='error')


def copy_camera(camera_list):
    """
    Copies focal length settings and matches position of two cameras.

    """

    if not len(camera_list) > 1:
        return
    copy_from_cam = camera_list[0]
    copy_to_cams = camera_list[1:]
    for copy_to_cam in copy_to_cams:
        copy_to_cam.focalLength.setLocked(False)
        focal_length = copy_from_cam.focalLength.get()
        copy_to_cam.focalLength.set(focal_length)
        if copy_to_cam.listConnections(type=pm.nt.Constraint):
            if camera_is_rigged(copy_to_cam):
                camera_obj = get_camera_flag_from_camera(copy_to_cam)
            else:
                logger.warning(f'{copy_to_cam} is constrained but not to a rig.')
                continue
        else:
            camera_obj = copy_to_cam
        con = constraint.parent_constraint_safe(copy_from_cam, camera_obj, mo=False)
        if con:
            if pm.keyframe(camera_obj, q=True, kc=True):
                pm.setKeyframe(camera_obj)
            pm.delete(con)
        logger.info(f'Camera settings copied from {copy_from_cam.name()} to {copy_to_cam.name()}.')


def create_center_capture(focus_objects, file_path, image_name, resolution=(75, 100), focal_length=90, auto_capture=True):
    """
    
    :param focus_objects: 
    :param str file_path: A single path.
    :param str image_name: name of the image file to capture.
    :param list/tuple[int, int] resolution: Two ints representing the width and height of the capture.
    :param int focal_length: sets how close the object looks.
    :return: A captured file.
    :rtype: str
    """
    
    uc_transform, ubercam = pm.camera(name='capture_camera')
    persp_camera = pm.PyNode('persp')
    if auto_capture:
        persp_camera.translate.set(0,0,0)
        persp_camera.rotate.set(0,0,0)
        pm.viewFit(focus_objects)
    uc_transform.translate.set(persp_camera.translate.get())
    uc_transform.rotate.set(persp_camera.rotate.get())
    uc_transform.focalLength.set(focal_length)

    image = playblast_single_frame(file_path=file_path, image_name=image_name, camera_node=uc_transform, resolution=resolution)
    pm.delete(uc_transform)
    return image
    
    