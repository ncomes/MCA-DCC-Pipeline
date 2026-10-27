"""
Rig templates for digitigrade (Z-leg) characters.

Same biped as the player, with ``ZLegComponent`` legs instead of a reverse foot and an optional jaw flag. The
hyena adds ears and hip cloth on top.
"""

from mca.common import log
from mca.mya.rigging import frag
from mca.mya.rigging.templates import biped_template

logger = log.MCA_LOGGER


class BaseZLegTemplate(biped_template.BipedTemplate):
    """
    Player biped with Z-leg legs and a jaw flag when the skeleton carries a jaw joint.
    """

    VERSION = 1
    ASSET_ID = ''
    ASSET_TYPE = 'player'

    LEG_COMPONENT = frag.ZLegComponent

    def extend(self):
        """
        Add the jaw flag under the head when the skeleton has a jaw joint.
        """

        jaw_joint = self.chain.get_start('jaw', 'center')
        if not jaw_joint:
            return
        jaw_component = self._fk_flag(self.frag_rig, jaw_joint, jaw_joint, 'center', 'jaw',
                                      scale=biped_template.SMALL_FLAG_SCALE, lock_root_translate_axes=[])
        jaw_component.attach_component(self.neck_component, self.neck_chain[1])


class HyenaTemplate(BaseZLegTemplate):
    """
    Hyena: the Z-leg biped plus FK ears on the head and cloth strips on the hips.
    """

    VERSION = 1
    ASSET_ID = 'hyena'
    ASSET_TYPE = 'enemies'

    def extend(self):
        """
        Add the ears and the cloth strips.
        """

        super().extend()
        ear_regions = [(side, 'ear') for side in biped_template.SIDES]
        self._build_fk_chains(ear_regions, self.neck_component, self.neck_chain[1], scale=1.0)

        cloth_regions = [(side, region) for side in biped_template.SIDES for region in ('fnt_cloth', 'bk_cloth')]
        self._build_fk_chains(cloth_regions, [self.pelvis_component], self.pelvis_joint, mark='detail',
                              lock_root_translate_axes=['v'])
