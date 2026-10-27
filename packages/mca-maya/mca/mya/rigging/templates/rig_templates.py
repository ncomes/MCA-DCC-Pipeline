"""
Base class for FRAG rig templates.

A rig template is the build script for one family of assets. Subclasses implement ``build`` (create the FRAG
hierarchy and components for the skeleton in the current scene) and the base class wraps it with the shared
bookkeeping: timing, twist component setup, template stamping and finalization.

Requires: pymel, the MCA asset manager (for flag paths) and a skeleton already in the scene.
"""

import time

import pymel.core as pm

from mca.common import log
from mca.common.assetlist import asset_manager
from mca.mya.rigging import rig_utils

logger = log.MCA_LOGGER


class RigTemplates(object):
    """
    Base class every rig template derives from.

    Subclasses set ``ASSET_ID`` / ``ASSET_TYPE`` defaults, bump ``VERSION`` when the build changes in a way that
    existing rigs should be rebuilt for, and implement ``build``. Callers normally run ``rig`` rather than
    ``build`` directly so the twist components and timing log are handled in one place.
    """

    VERSION = 1
    ASSET_ID = ''
    ASSET_TYPE = ''

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for. Drives the flag path lookup.
        :param str asset_type: Asset category stored on the FRAG root (player, enemies, weapon...).
        """

        self._asset_id = asset_id or self.ASSET_ID
        self._asset_type = asset_type or self.ASSET_TYPE
        self._elapsed_time = 0.0

    # --- Properties -------------------------------------------------------------------------------------------

    @property
    def asset_id(self):
        """
        :return: The asset id this template builds for.
        :rtype: str
        """

        return self._asset_id

    @asset_id.setter
    def asset_id(self, value):
        """
        :param str value: New asset id.
        """

        self._asset_id = value

    @property
    def asset_type(self):
        """
        :return: The asset category written to the FRAG root.
        :rtype: str
        """

        return self._asset_type

    @asset_type.setter
    def asset_type(self, value):
        """
        :param str value: New asset type.
        """

        self._asset_type = value

    @property
    def elapsed_time(self):
        """
        :return: Seconds the last ``rig`` call took.
        :rtype: float
        """

        return self._elapsed_time

    # --- Abstract ---------------------------------------------------------------------------------------------

    def build(self, finalize=True):
        """
        Create the rig for the skeleton in the current scene. Subclasses must override this.

        :param bool finalize: If the rig should be finalized (display layers, flag shape swap, colours). Pass
            False when a subclass or tool intends to add more components before finalizing.
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        raise NotImplementedError('{0} does not implement build().'.format(type(self).__name__))

    # --- Entry point ------------------------------------------------------------------------------------------

    def rig(self, asset_id=None):
        """
        Build the rig, then set up the twist helper components. This is the entry point tools should call.

        :param str asset_id: Optional asset id override for this build.
        :return: The FRAG rig that was built, or None if the build produced nothing.
        :rtype: FRAGRig or None
        """

        if asset_id:
            self._asset_id = asset_id

        start_time = time.time()
        logger.info('Building rig "{0}" with {1}.'.format(self.asset_id, type(self).__name__))

        frag_rig = self.build()
        if frag_rig:
            # Twist components read the finished skeleton attachments, so they are always built last.
            rig_utils.setup_twist_components(frag_rig)

        pm.select(clear=True)
        self._elapsed_time = time.time() - start_time
        logger.info('Built rig "{0}" in {1:.2f} seconds.'.format(self.asset_id, self._elapsed_time))
        return frag_rig

    # --- Helpers for subclasses -------------------------------------------------------------------------------

    def get_version(self):
        """
        :return: The template version.
        :rtype: int
        """

        return self.VERSION

    def get_flags_path(self):
        """
        Return the directory holding the custom flag shapes for this asset.

        :return: Absolute directory path, or None when the asset is not registered.
        :rtype: str or None
        """

        mca_asset = asset_manager.get_asset_manager().get_record(self._asset_id)
        if mca_asset:
            return mca_asset.flags_path
        logger.warning('Asset "{0}" is not registered; the rig keeps its placeholder flags.'.format(self._asset_id))
        return None

    def finalize_rig(self, frag_rig, finalize=True):
        """
        Stamp the template name on the rig and, when requested, run the rig finalization.

        The template name is always written so tools can tell which build script produced a rig, even when the
        caller holds off on finalization to add more components.

        :param FRAGRig frag_rig: The rig to finalize.
        :param bool finalize: If the display layers, flag swap and colouring should run now.
        :return: The same rig, for chaining.
        :rtype: FRAGRig
        """

        frag_rig.pynode.rigTemplate.set(type(self).__name__)
        if finalize:
            frag_rig.finalize_rig(self.get_flags_path())
        return frag_rig
