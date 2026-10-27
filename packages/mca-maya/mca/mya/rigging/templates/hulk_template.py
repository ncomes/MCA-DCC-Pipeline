"""
Rig templates for the hulk family of enemies.

The hulk body is the player biped with simpler clavicles (plain FK), arms that start in FK and no weapon equip
points. The gilded variant adds a left arm armour set and cloth strips on the hips.
"""

from mca.common import log
from mca.mya.rigging import frag
from mca.mya.rigging.templates import biped_template

logger = log.MCA_LOGGER


class HulkTemplate(biped_template.BipedTemplate):
    """
    Base hulk biped: FK clavicles, FK-first arms, a non translating attach flag and no equip flags.
    """

    VERSION = 1
    ASSET_ID = ''
    ASSET_TYPE = 'enemies'

    CLAVICLE_COMPONENT = frag.FKComponent
    ATTACH_FLAG_TRANSLATES = False
    BUILD_EQUIP_FLAGS = False
    ARMS_DEFAULT_TO_IK = False


class GildedHulkTemplate(HulkTemplate):
    """
    Gilded hulk: the hulk body plus a layered left shoulder armour set, a left elbow guard and hip cloth.

    The ``should_armor_*`` region names are misspelt on the skeleton and in shipped animation, so the component
    regions keep that spelling on purpose.
    """

    VERSION = 1
    ASSET_ID = 'hulk'
    ASSET_TYPE = 'enemies'

    def extend(self):
        """
        Add the armour plates and cloth strips. Every plate is a single detail flag riding the joint under it.
        """

        chain = self.chain
        l_arm_component = self.arm_components['left']
        l_arm_full_chain = chain.get_full_chain('arm', 'left')

        # Elbow guard on the forearm, shoulder plate on the upper arm.
        self._build_armor_plate('elbow_guard', 'elbow_guard', [l_arm_component], l_arm_full_chain[1])
        shoulder_plate, shoulder_joint = self._build_armor_plate('shoulder_armor', 'shoulder_armor',
                                                                 [l_arm_component], l_arm_full_chain[0])

        # Three sub plates chained under each other, then a front and back plate on the shoulder.
        parent_plate, parent_joint = shoulder_plate, shoulder_joint
        for index in (1, 2, 3):
            region = 'should_armor_sub_0{0}'.format(index)
            parent_plate, parent_joint = self._build_armor_plate(region, region, [parent_plate], parent_joint)
        self._build_armor_plate('shoulder_armor_bck', 'should_armor_bck', [shoulder_plate], shoulder_joint)
        self._build_armor_plate('shoulder_armor_fnt', 'should_armor_fnt', [shoulder_plate], shoulder_joint)

        cloth_regions = [(side, region) for side in biped_template.SIDES for region in ('fnt_cloth', 'bk_cloth')]
        self._build_fk_chains(cloth_regions, [self.pelvis_component], self.pelvis_joint, mark='detail',
                              end_flag_only=True, lock_root_translate_axes=['v'])

    def _build_armor_plate(self, markup_region, region, parent_components, parent_object):
        """
        Build one single-joint FK plate on the left side and mark its flag as a detail flag.

        :param str markup_region: Skeleton markup region of the plate joint.
        :param str region: Component region to build the plate as.
        :param list(FRAGNode) parent_components: Components the plate attaches to.
        :param pm.nt.Transform parent_object: Object the plate's groups are constrained to.
        :return: The plate component and its joint, so the next plate can hang off it.
        :rtype: tuple(FKComponent, pm.nt.Joint)
        """

        plate_joint = self.chain.get_chain(markup_region, 'left')[0]
        plate_component = self._fk_flag(self.frag_rig, plate_joint, plate_joint, 'left', region,
                                        lock_root_translate_axes=['v'])
        plate_component.attach_component(parent_components, parent_object)
        plate_component.get_end_flag().set_as_detail()
        return plate_component, plate_joint
