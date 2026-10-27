"""
FRAG node that stores a cinematic sequence's metadata in the scene.

Holds the sequence name, stage, scene name, version, parent cinematic and ubercam asset id as string attributes and
links the Maya shot nodes that belong to the sequence through the ``shots`` message attribute.
"""

import pymel.core as pm

from mca.common import log
from mca.mya.rigging.frag import frag_base

logger = log.MCA_LOGGER


class CineSequenceComponent(frag_base.FRAGNode):
    """
    Network node that lives in the scene and holds the cinematic sequence information the CineShotEditor reads.
    """

    VERSION = 1

    @staticmethod
    def create(seq_data):
        """
        Creates a new CineSequenceComponent node and returns it.

        :param dict seq_data: Dictionary with data about the cinematic sequence. Should use CineSequenceData.data
        :return: Returns the created FRAGNode
        :rtype: CineSequenceComponent
        """

        seq_name = seq_data.get('seq_name')
        stage = seq_data.get('stage')
        scene_name = seq_data.get('scene_name')
        version_num = seq_data.get('version_num')
        shots = seq_data.get('shots')
        cinematic_name = seq_data.get('cinematic_name', '')
        ubercam_asset_id = seq_data.get('ubercam_asset_id', '')

        node = frag_base.FRAGNode.create(frag_parent=None,
                                         frag_type=CineSequenceComponent.__name__,
                                         version=CineSequenceComponent.VERSION)
        maya_node = node.pynode

        maya_node.addAttr('sequenceName', dt='string')
        maya_node.sequenceName.set(seq_name)
        maya_node.addAttr('stage', dt='string')
        maya_node.stage.set(stage)
        maya_node.addAttr('sceneName', dt='string')
        maya_node.sceneName.set(scene_name)
        maya_node.addAttr('versionNumber', dt='string')
        maya_node.versionNumber.set(str(version_num))
        # cinematicName names the parent cinematic this sequence belongs to. Drives the
        # on-disk folder structure (Cinematics/Sequences/<cinematic>/<seq>/...) and the
        # export path the Animation Exporter writes to. Stored on the node so reopening the
        # scene rehydrates the field in the CineShotEditor without artist input.
        maya_node.addAttr('cinematicName', dt='string')
        maya_node.cinematicName.set(cinematic_name or '')
        # ubercamAssetId is the registry id of the Cameras-category asset used to build
        # this sequence's ubercam. Persisting it lets the CineShotEditor re-select the
        # right entry in its camera dropdown on scene reopen, and lets refresh paths
        # (re-import etc.) skip having to ask the artist again.
        maya_node.addAttr('ubercamAssetId', dt='string')
        maya_node.ubercamAssetId.set(ubercam_asset_id or '')
        maya_node.addAttr('shots', at='message')
        if shots:
            for shot_num, shot_data in shots.items():
                shot_name = shot_data.get('shot_name')
                shot_pynode = [x for x in pm.ls(type=pm.nt.Shot) if x.shotName.get() == shot_name]
                if shot_pynode:
                    shot_pynode = shot_pynode[0]
                    shot_pynode.setLocked(False)
                else:
                    continue
                if not shot_pynode.hasAttr('sequenceNode'):
                    shot_pynode.addAttr('sequenceNode', at='message')
                maya_node.shots >> shot_pynode.sequenceNode

        frag_node = CineSequenceComponent(maya_node)
        return frag_node

    def seq_name(self):
        """
        Returns the sequence name.

        :return: Sequence name.
        :rtype: str
        """

        return self.pynode.sequenceName.get()

    def cinematic_name(self):
        """
        Returns the parent cinematic's name. Older nodes pre-date the cinematicName attr, so a missing attr is
        tolerated and reported as an empty string rather than erroring; this keeps legacy scenes openable in the
        CineShotEditor.

        :return: Cinematic name, or '' if not set / attr missing.
        :rtype: str
        """

        if not self.pynode.hasAttr('cinematicName'):
            return ''
        return self.pynode.cinematicName.get() or ''

    def set_cinematic_name(self, value):
        """
        Sets the parent cinematic name on the node. Adds the attr lazily for legacy nodes that don't already have it.

        :param str value: New cinematic name. Treated as '' when None.
        """

        if not self.pynode.hasAttr('cinematicName'):
            self.pynode.addAttr('cinematicName', dt='string')
        self.pynode.cinematicName.set(value or '')

    def ubercam_asset_id(self):
        """
        Returns the registry id of the Cameras-category asset used to build the ubercam for this sequence, or '' if
        not set / attr missing (legacy nodes).

        :return: Asset id string, or '' when unset.
        :rtype: str
        """

        if not self.pynode.hasAttr('ubercamAssetId'):
            return ''
        return self.pynode.ubercamAssetId.get() or ''

    def set_ubercam_asset_id(self, value):
        """
        Persists the Cameras-category asset id used for this sequence's ubercam. Lazy-adds the attr for legacy nodes.

        :param str value: New asset id. Treated as '' when None.
        """

        if not self.pynode.hasAttr('ubercamAssetId'):
            self.pynode.addAttr('ubercamAssetId', dt='string')
        self.pynode.ubercamAssetId.set(value or '')

    def scene_name(self):
        """
        Returns the scene name stored on the node.

        :return: Scene name.
        :rtype: str
        """

        return self.pynode.sceneName.get()

    def version_num(self):
        """
        Returns the sequence version number.

        :return: Version number as stored (string).
        :rtype: str
        """

        return self.pynode.versionNumber.get()

    def stage(self):
        """
        Returns the sequence stage.

        :return: Stage name.
        :rtype: str
        """

        return self.pynode.stage.get()

    def shots(self):
        """
        Returns the shot nodes linked to this sequence.

        :return: Connected shot nodes.
        :rtype: list[pm.nt.Shot]
        """

        return self.pynode.shots.listConnections()

    def add_shot(self, shot):
        """
        Links a shot node to this sequence.

        :param pm.nt.Shot shot: Shot node to link; a ``sequenceNode`` message attr is added if missing.
        """

        if not shot.hasAttr('sequenceNode'):
            shot.addAttr('sequenceNode', at='message')
        self.pynode.shots >> shot.sequenceNode

    def remove_shot(self, shot):
        """
        Unlinks a shot node from this sequence.

        :param pm.nt.Shot shot: Shot node to unlink.
        """

        if shot.hasAttr('sequenceNode'):
            self.pynode.shots // shot.sequenceNode


def find_cine_seq_component():
    """
    Finds the CineSequenceComponent in the scene.

    :return: The first CineSequenceComponent found, or None when the scene has none.
    :rtype: CineSequenceComponent or None
    """

    scene_network_nodes = pm.ls(type=pm.nt.Network)
    for network_node in scene_network_nodes:
        try:
            frag_node = frag_base.FRAGNode(network_node)
            if isinstance(frag_node, CineSequenceComponent):
                return frag_node
        except Exception:
            # Plain network nodes without a fragType raise when wrapped; they are simply not sequence nodes.
            logger.info(f'{network_node} cannot be a FRAGNode')
    return None
