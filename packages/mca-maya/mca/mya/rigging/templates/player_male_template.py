"""
Rig templates for the player character and the hero variants built on its skeleton.

``PlayerMaleTemplate`` is the stock biped (reverse foot legs, clavicle components, weapon equip flags). The
hero templates keep that body and add their own props: a ponytail, armour plates, a chain whip, a second pair of
power glove arms.
"""

import pymel.core as pm

from mca.common import log
from mca.mya.rigging import frag
from mca.mya.rigging.templates import biped_template
from mca.mya.utils import constraint

logger = log.MCA_LOGGER


class PlayerMaleTemplate(biped_template.BipedTemplate):
    """
    The stock player biped. Every default knob on ``BipedTemplate`` describes this rig.
    """

    VERSION = 1
    ASSET_ID = 'player_male'
    ASSET_TYPE = 'player'


class FrontWindTemplate(PlayerMaleTemplate):
    """
    Frostwind: the player body plus an FK ponytail hanging off the head.

    The class name predates the asset's final spelling and is kept so existing rigs keep matching their
    ``rigTemplate`` stamp.
    """

    VERSION = 1
    ASSET_ID = 'frostwind'
    ASSET_TYPE = 'heroes'

    def extend(self):
        """
        Add the ponytail chain under the head.
        """

        self._build_fk_chains([('center', 'pony_tail')], self.neck_component, self.neck_chain[1],
                              scale=biped_template.SMALL_FLAG_SCALE)


class ConduitTemplate(PlayerMaleTemplate):
    """
    Conduit: the player body plus a left shoulder plate and two right knee armour plates.
    """

    VERSION = 1
    ASSET_ID = 'conduit'
    ASSET_TYPE = 'heroes'

    def extend(self):
        """
        Add the armour plates, each following the limb joint it sits on.
        """

        l_arm_chain = self.arm_chains['left']
        self._build_fk_chains([('left', 'shoulder_armor')], self.arm_components['left'], l_arm_chain[0], scale=0.5)

        # The knee plates ride the calf joint (second joint of the full leg chain).
        r_calf_joint = self.chain.get_full_chain('leg', 'right')[1]
        r_leg_component = self.leg_components['right']
        self._build_fk_chains([('right', 'knee_armor_01')], r_leg_component, r_calf_joint, scale=0.5)
        self._build_fk_chains([('right', 'knee_armor_02')], r_leg_component, r_calf_joint, scale=0.3)


class LifeCallerTemplate(PlayerMaleTemplate):
    """
    Life Caller: the player body plus a chain whip with a lantern on its tip.

    The whip is a retractable spline chain hung off the right hand weapon joint, so it follows whatever the hand
    weapon flag is doing.
    """

    VERSION = 1
    ASSET_ID = 'lifecaller'
    ASSET_TYPE = 'heroes'

    def extend(self):
        """
        Add the whip handle, the spline whip chain and the lantern.
        """

        chain = self.chain
        frag_rig = self.frag_rig
        hand_weapon_component = self.get_component('right', 'hand_weapon')
        hand_weapon_joint = hand_weapon_component.bind_joints[0]

        # Whip handle: a single flag on the whip weapon joint, riding the hand weapon.
        whip_joint = chain.get_chain('whip_weapon', 'center')[0]
        whip_weapon_component = self._fk_flag(frag_rig, whip_joint, whip_joint, 'center', 'whip_weapon',
                                              lock_root_translate_axes=['v'])
        whip_weapon_component.attach_component([hand_weapon_component], hand_weapon_joint)

        # The whip itself: a spline chain with helper joints at the start, middle and end.
        chain_start, chain_end = chain.get_chain('chain_hi', 'center')
        whip_component = frag.SporeTongueComponent.create(frag_parent=frag_rig,
                                                          start_joint=chain_start,
                                                          end_joint=chain_end,
                                                          end_helper_joint=chain.get_chain('chain_end', 'center')[0],
                                                          mid_helper_joint=chain.get_chain('chain_mid', 'center')[0],
                                                          start_helper_joint=chain.get_chain('chain_start',
                                                                                             'center')[0],
                                                          leaf_joint_list=chain.get_full_chain('chain_leaf',
                                                                                               'center'),
                                                          side='center',
                                                          region='chain_whip',
                                                          mid_flag=True,
                                                          can_retract=True)
        self._register(whip_component)
        whip_component.attach_component(hand_weapon_component, whip_joint)

        # Lantern on the tip of the whip.
        lantern_joint = chain.get_start('lantern', 'center')
        lantern_component = self._fk_flag(frag_rig, lantern_joint, lantern_joint, 'center', 'lantern',
                                          lock_root_translate_axes=['v'])
        lantern_component.attach_component([whip_component], [chain_end])


class PowerGloveTemplate(PlayerMaleTemplate):
    """
    Power Gloves: the player body plus a second, oversized pair of arms.

    The glove arms are full IKFK arms with their own fingers and weapon flags. Once built they drive the
    matching flags of the regular arms, and the regular arm, finger and hand weapon flags are hidden so the
    animator only ever poses the gloves.
    """

    VERSION = 1
    ASSET_ID = 'powergloves'
    ASSET_TYPE = 'heroes'

    PG_FINGER_REGIONS = ('pg_index_finger', 'pg_middle_finger', 'pg_ring_finger', 'pg_pinky_finger',
                         'pg_thumb_finger')

    def extend(self):
        """
        Build the glove arms, hook them up to the regular arms and hide the regular arm controls.
        """

        chain = self.chain
        frag_rig = self.frag_rig
        pg_arm_components = {}
        pg_arm_chains = {}
        pg_weapon_flags = {}

        for side in biped_template.SIDES:
            pg_arm_chain = chain.get_chain('pg_arm', side)
            pg_arm_chains[side] = pg_arm_chain
            pg_arm_component = frag.IKFKComponent.create(frag_rig,
                                                         pg_arm_chain[0],
                                                         pg_arm_chain[1],
                                                         side=side,
                                                         region='pg_arm',
                                                         ik_flag_pv_orient=biped_template.LIMB_IK_ORIENTATION)
            self._register(pg_arm_component)
            pg_arm_component.attach_component(self.clav_components[side], self.clav_chains[side][0])
            pg_arm_component.switch_flag.ikfk_switch.set(0)
            pg_arm_components[side] = pg_arm_component

            pg_hand_joint = pg_arm_chain[1]
            for region in self.PG_FINGER_REGIONS:
                finger_chain = chain.get_chain(region, side)
                finger_component = self._fk_flag(frag_rig, finger_chain[0], finger_chain[1], side, region,
                                                 scale=biped_template.SMALL_FLAG_SCALE)
                finger_component.attach_component(pg_arm_component, pg_hand_joint)

            weapon_joint = chain.get_start('pg_weapon', side)
            weapon_component = self._fk_flag(frag_rig, weapon_joint, weapon_joint, side, 'pg_weapon',
                                             scale=biped_template.SMALL_FLAG_SCALE, lock_root_translate_axes=[])
            weapon_component.attach_component(pg_arm_component, pg_hand_joint)
            weapon_flag = weapon_component.get_flags()[0]
            weapon_flag.set_as_sub()
            pg_weapon_flags[side] = weapon_flag

        # Follow spaces for the glove arms mirror the regular arms.
        for side in biped_template.SIDES:
            other = biped_template.other_side(side)
            pg_arm_component = pg_arm_components[side]
            frag.MultiConstraint.create(frag_rig,
                                        side=side,
                                        region='pg_arm',
                                        source_object=pg_arm_component.ik_flag,
                                        target_list=[self.offset_flag,
                                                     self.clav_flags[side],
                                                     pg_arm_chains[other][1],
                                                     self.cog_flag,
                                                     self.upper_torso_flag],
                                        switch_obj=pg_arm_component.switch_flag,
                                        switch_attr='follow')

        weapon_targets = {side: [pg_arm_chains[side][1],
                                 pg_weapon_flags[biped_template.other_side(side)],
                                 self.cog_flag,
                                 self.offset_flag] for side in biped_template.SIDES}
        frag.MultiConstraint.create(frag_rig,
                                    side='left',
                                    region='pg_weapon',
                                    source_object=pg_weapon_flags['left'],
                                    target_list=weapon_targets['left'],
                                    switch_obj=None)
        frag.MultiConstraint.create(frag_rig,
                                    side='right',
                                    region='pg_rotate_weapon',
                                    source_object=pg_weapon_flags['right'],
                                    target_list=weapon_targets['right'],
                                    translate=False,
                                    scale=False,
                                    switch_obj=None,
                                    switch_attr='rotateFollow')
        frag.MultiConstraint.create(frag_rig,
                                    side='right',
                                    region='pg_weapon',
                                    source_object=pg_weapon_flags['right'],
                                    target_list=weapon_targets['right'],
                                    rotate=False,
                                    switch_obj=None,
                                    switch_attr='pointFollow')

        # The glove flags drive the regular arm flags, so posing the gloves poses both arms.
        for side in biped_template.SIDES:
            pg_arm_component = pg_arm_components[side]
            arm_component = self.arm_components[side]
            for pg_flag, arm_flag in zip(pg_arm_component.fk_flags, arm_component.fk_flags):
                constraint.parent_constraint_safe(pg_flag, arm_flag, mo=True)
            constraint.parent_constraint_safe(pg_arm_component.ik_flag, arm_component.ik_flag, mo=True)
            constraint.parent_constraint_safe(pg_arm_component.pv_flag, arm_component.pv_flag, mo=True)

        # Hide the regular arm, finger and hand weapon controls; the gloves replace them.
        hidden_components = list(self.arm_components.values()) + list(self.finger_components.values())
        hidden_components += [self.get_component(side, 'hand_weapon') for side in biped_template.SIDES]
        for component in hidden_components:
            component.flag_group.v.set(0)
