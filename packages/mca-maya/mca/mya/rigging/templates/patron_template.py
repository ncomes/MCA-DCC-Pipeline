"""
Rig templates for the patron characters.

Patrons are the player biped with small additions: Gork carries a pair of antlers, Feldspar is the plain body.
"""

from mca.common import log
from mca.mya.rigging.templates import biped_template
from mca.mya.rigging.templates import player_male_template

logger = log.MCA_LOGGER


class GorkTemplate(player_male_template.PlayerMaleTemplate):
    """
    Gork: the player body plus two antler flags on the head.
    """

    VERSION = 1
    ASSET_ID = 'gork'
    ASSET_TYPE = 'patron'

    def extend(self):
        """
        Add the antlers. They are marked up as back hair on the skeleton.
        """

        head_joint = self.neck_chain[-1]
        for side in biped_template.SIDES:
            antler_joint = self.chain.get_start('bk_hair', side)
            antler_component = self._fk_flag(self.frag_rig, antler_joint, antler_joint, side, 'bk_hair',
                                             scale=biped_template.SMALL_FLAG_SCALE, lock_root_translate_axes=[])
            antler_component.attach_component(self.neck_component, head_joint)
            antler_component.get_flags()[0].set_as_sub()


class FeldsparTemplate(player_male_template.PlayerMaleTemplate):
    """
    Feldspar: the plain player body. Kept as its own template so the asset stamps its own name on the rig.
    """

    VERSION = 1
    ASSET_ID = 'feldspar'
    ASSET_TYPE = 'patron'
