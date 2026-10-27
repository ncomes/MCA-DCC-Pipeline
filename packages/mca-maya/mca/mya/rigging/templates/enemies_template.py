"""
Rig templates for the enemy characters.

``GildedGrux`` is a heavier biped variant (FK clavicles, three fingers, no attach or equip points) with a full set
of FK face, cloth and pouch chains. ``RabbitTemplate`` is the player body with FK ears.
"""

from mca.common import log
from mca.mya.rigging.templates import biped_template
from mca.mya.rigging import frag
from mca.mya.rigging.templates import player_male_template

logger = log.MCA_LOGGER


class GildedGrux(biped_template.BipedTemplate):
    """
    Gilded Grux: FK clavicles, FK-first arms, three fingers per hand and a plain combined weapon follow.

    On top of the biped it carries FK chains for the jaw, cheeks, ears, brows, eyes and eyelids, plus cloth and
    pouch chains on the hips. The class name has no ``Template`` suffix because shipped rigs are stamped with it.
    """

    VERSION = 1
    ASSET_ID = 'grux'
    ASSET_TYPE = 'enemies'

    CLAVICLE_COMPONENT = frag.FKComponent
    FINGER_REGIONS = ('index_finger', 'middle_finger', 'thumb')
    UPPER_TORSO_JOINT = None
    BUILD_ATTACH = False
    BUILD_EQUIP_FLAGS = False
    BUILD_HEAD_FOLLOW = False
    BUILD_SPINE_FOLLOW = False
    ARMS_DEFAULT_TO_IK = False
    SPLIT_RIGHT_WEAPON_FOLLOW = False

    FACE_REGIONS = ('cheek', 'ear', 'brow', 'eye')
    HIP_REGIONS = ('fnt_cloth', 'bk_cloth', 'fnt_pouch', 'bk_pouch')

    def extend(self):
        """
        Add the face, cloth and pouch chains. All of them are primary flags.
        """

        scale = biped_template.SMALL_FLAG_SCALE
        head_joint = self.neck_chain[1]

        hip_regions = [(side, region) for side in biped_template.SIDES for region in self.HIP_REGIONS]
        self._build_fk_chains(hip_regions, self.pelvis_component, self.pelvis_joint, scale=scale)

        self._build_fk_chains([('center', 'jaw')], self.neck_component, head_joint, scale=scale)
        face_regions = [(side, region) for side in biped_template.SIDES for region in self.FACE_REGIONS]
        face_components = self._build_fk_chains(face_regions, self.neck_component, head_joint, scale=scale)

        # Eyelids ride the eye joint so they stay put when the eye flag looks around.
        for side in biped_template.SIDES:
            eye_component = face_components[(side, 'eye')]
            eye_joint = self.chain.get_chain('eye', side)[0]
            self._build_fk_chains([(side, 'eyelid_upper'), (side, 'eyelid_lower')], eye_component, eye_joint,
                                  scale=scale)


class RabbitTemplate(player_male_template.PlayerMaleTemplate):
    """
    Rabbit: the player body plus a pair of FK ears whose root flags are sub flags.
    """

    VERSION = 1
    ASSET_ID = 'rabbit'
    ASSET_TYPE = 'enemies'

    def extend(self):
        """
        Add the ears under the head.
        """

        head_joint = self.neck_chain[-1]
        for side in biped_template.SIDES:
            ear_chain = self.chain.get_chain('ear', side)
            ear_component = self._fk_flag(self.frag_rig, ear_chain[0], ear_chain[-1], side, 'ears',
                                          scale=biped_template.SMALL_FLAG_SCALE, lock_root_translate_axes=[])
            ear_component.attach_component(self.neck_component, head_joint)
            ear_component.get_flags()[0].set_as_sub()
