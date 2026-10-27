"""
Camera rig for use in cinematic scenes.

``CinematicCameraTemplate`` builds a small FRAG rig (root -> world -> camera component) around a camera it creates.
The skeleton and flag shapes come from a registered Cameras-category asset rather than a hard-coded folder, and
that asset also supplies the ``asset_id`` / ``asset_type`` baked into the ``FRAGRoot`` so downstream tooling
(Animation Exporter, asset queries...) sees the ubercam rig like any other registered asset.

Requires: pymel, the MCA asset manager and ``camera_skel.skl`` under the asset's ``_Source/Rigs`` folder.
"""

import os

import pymel.core as pm

from mca.common import log
from mca.common.assetlist import asset_manager
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging import skel_utils
from mca.mya.rigging.templates import rig_templates
from mca.mya.utils import namespace

logger = log.MCA_LOGGER

# Asset registry id of the Cameras > Ubercam asset (the entry seeded in Cameras.alist). It is the template's default
# asset and camera_utils imports it too, which is why it stays a module constant.
DEFAULT_UBERCAM_ASSET_ID = 'ubercam'


class CinematicCameraTemplate(rig_templates.RigTemplates):
    """
    Template for the cinematic ubercam rig.

    Imports the camera skeleton of the registered asset into its own namespace, creates the FRAG root and rig, a
    world component on the skeleton root and a ``CameraComponent`` on the ``cam`` joint that drives a new Maya
    camera. There is no skeletal mesh, so no ``SkeletalMesh`` node is created.
    """

    VERSION = 1
    ASSET_ID = DEFAULT_UBERCAM_ASSET_ID
    ASSET_TYPE = 'camera'

    def __init__(self, asset_id=None):
        """
        :param str asset_id: Asset registry id of the Cameras-category asset to build from. None uses ``ASSET_ID``
            so legacy callers that invoke the template with no arguments still work; the entry must exist in
            ``Cameras.alist`` for the build to succeed.
        """

        resolved_id = asset_id or self.ASSET_ID
        # A missing asset is only reported in build() so instantiating the class never raises before Maya and the
        # scene are ready.
        self._mca_asset = self._lookup_asset(resolved_id)
        super().__init__(asset_id=resolved_id, asset_type=self.ASSET_TYPE)

    @staticmethod
    def _lookup_asset(asset_id):
        """
        Resolve an asset record by id.

        Returns None instead of raising when the asset manager is not available or the id is not registered; the
        caller is responsible for surfacing the missing asset.

        :param str asset_id: Asset id to look up.
        :return: The resolved asset record, or None.
        :rtype: AssetRecord or None
        """

        try:
            return asset_manager.get_asset_manager().get_record(asset_id)
        except Exception as exc:
            logger.warning(f'Could not look up cinematic camera asset {asset_id!r}: {exc}')
            return None

    @ma_decorators.keep_namespace_decorator
    def build(self, finalize=True, **kwargs):
        """
        Build the camera rig from the registered camera asset.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :param kwargs: Ignored. Older callers pass ``cam``; the template always creates its own camera.
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        if self._mca_asset is None:
            raise RuntimeError(f'CinematicCameraTemplate could not resolve asset {self.asset_id!r}. '
                               f'Make sure the entry exists in Cameras.alist before importing.')

        # The skeleton lives under the asset's standard source rigs folder. full_path resolves the registered
        # relative path against MCA_PROJECT_ROOT.
        asset_full_path = self._mca_asset.full_path
        if not asset_full_path or not os.path.isdir(asset_full_path):
            raise RuntimeError(f'CinematicCameraTemplate: asset folder not found on disk at {asset_full_path!r}.')

        camera_skel_path = os.path.join(asset_full_path, '_Source', 'Rigs', 'camera_skel.skl')
        if not os.path.isfile(camera_skel_path):
            raise RuntimeError(f'CinematicCameraTemplate: missing camera_skel.skl at {camera_skel_path!r}.')

        root = skel_utils.import_skeleton(camera_skel_path)
        chain = chain_markup.ChainMarkup(root)
        cam_joint = chain.get_start('cam', 'center')
        namespace.set_namespace(root, check_existing=False)

        # asset_type / asset_id come from the registered asset, so the FRAGRoot (and everything walking fragParent
        # off the camera) sees real values.
        frag_root = frag.FRAGRoot.create(root, self.asset_type, self.asset_id)
        frag_rig = frag.FRAGRig.create(frag_root)

        world_component = frag.WorldComponent.create(frag_rig,
                                                     root,
                                                     'center',
                                                     'world',
                                                     orientation=[-90, 0, 0])  # Flat on the ground plane.
        root_flag = world_component.root_flag
        root_flag.set_as_sub()
        offset_flag = world_component.offset_flag
        offset_flag.set_as_detail()

        # Default cine camera: 35mm full aperture film back (inches) and a 144 degree shutter.
        cam = pm.camera(centerOfInterest=5,
                        focalLength=35,
                        lensSqueezeRatio=1,
                        cameraScale=1,
                        horizontalFilmAperture=1.41732,
                        horizontalFilmOffset=0,
                        verticalFilmAperture=0.94488,
                        verticalFilmOffset=0,
                        filmFit='Fill',
                        overscan=1,
                        motionBlur=0,
                        shutterAngle=144,
                        nearClipPlane=0.1,
                        farClipPlane=10000,
                        orthographic=0,
                        orthographicWidth=30,
                        horizontalPan=0,
                        verticalPan=0,
                        panZoomEnabled=0,
                        zoom=1)

        cam_component = frag.CameraComponent.create(frag_rig,
                                                    cam_joint,
                                                    'center',
                                                    'cam',
                                                    cam)
        cam_component.attach_component([world_component], [offset_flag])

        # The camera rig has no skeletal mesh, so there is nothing to add to the skins group before finalizing.
        return self.finalize_rig(frag_rig, finalize)
