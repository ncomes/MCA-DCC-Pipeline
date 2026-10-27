"""
Rig template for the generic human skeleton.

An older biped layout: FK clavicles, a separate top-spine FK section between the spine and the neck, and IK
arms that can follow the other hand's IK flag. Kept for the ``basehuman`` skeleton; new characters use
``PlayerMaleTemplate``.
"""

from mca.common import log
from mca.mya.rigging import frag
from mca.mya.rigging.templates import biped_template

logger = log.MCA_LOGGER


class BaseHumanTemplate(biped_template.BipedTemplate):
    """
    Generic human biped with a top-spine section that the neck and clavicles hang from.
    """

    VERSION = 1
    ASSET_ID = 'basehuman'
    ASSET_TYPE = 'heroes'

    CLAVICLE_COMPONENT = frag.FKComponent
    BUILD_ATTACH = False
    BUILD_EQUIP_FLAGS = False
    ARMS_DEFAULT_TO_IK = False
    SPLIT_RIGHT_WEAPON_FOLLOW = False

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)
        self.top_spine_component = None
        self.top_spine_flag = None

    def _build_spine(self):
        """
        Build the RFK spine, then the top-spine FK section the upper body hangs from.
        """

        super()._build_spine()
        top_spine_chain = self.chain.get_chain('top_spine', 'center')
        self.top_spine_component = self._fk_flag(self.frag_rig, top_spine_chain[0], top_spine_chain[1],
                                                 'center', 'top_spine')
        self.top_spine_component.attach_component(self.spine_component, self.spine_chain[1])
        self.top_spine_flag = self.top_spine_component.get_flags()[0]
        self.top_spine_flag.set_as_detail()
        # The neck, clavicles and arm follow spaces use the top spine rather than the spine's sub flag.
        self.upper_torso_flag = self.top_spine_flag
        self.upper_torso_parent = (self.top_spine_component, top_spine_chain[1])

    def _ik_arm_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Follow targets for the IK hand; the other hand's IK flag replaces its joint.
        :rtype: list
        """

        other_arm = self.arm_components[biped_template.other_side(side)]
        return [self.offset_flag, self.clav_flags[side], other_arm.ik_flag, self.cog_flag, self.upper_torso_flag]
