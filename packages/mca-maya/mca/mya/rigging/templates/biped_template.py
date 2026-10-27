"""
Shared build logic for two-legged character rigs.

Every biped in the project (players, enemies, patrons, familiars) is the same rig with a few knobs turned: which
clavicle component to use, whether the legs get a reverse foot or a Z-leg, whether weapon equip flags exist, and
so on. ``BipedTemplate`` builds that rig once from the skeleton's chain markup and exposes the knobs as class
attributes plus a handful of hook methods. Concrete templates are then a few lines of configuration and an
``extend`` override for the parts that are unique to the character (armour, cloth, ears, ponytails...).

Build order (also the order subclasses can rely on in ``extend``):

1. ``_build_world``        world / root / offset flags
2. ``_build_attach``       optional attach flag
3. ``_build_torso``        cog, pelvis, spine, neck
4. ``_build_clavicles``    left and right clavicles
5. ``_build_arms``         IKFK arms and hand weapon flags
6. ``_build_equip_flags``  optional weapon / thigh equip flags
7. ``_build_legs``         legs
8. ``_build_fingers``      FK finger chains
9. ``_build_constraints``  every multi constraint (follow spaces)
10. ``extend``             subclass additions
11. finalize

Requires: a skeleton in the scene whose joints carry chain markup (see ``chain_markup``).
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging.templates import rig_templates

logger = log.MCA_LOGGER

SIDES = ('left', 'right')

# Orientation applied to the world, cog and pelvis flags so they lie flat on the ground plane.
FLAT_FLAG_ORIENTATION = [-90, 0, 0]
# Orientation of the IK flags and pole vectors on the limbs.
LIMB_IK_ORIENTATION = [-90, 0, 0]
# Flag scale used for small helper flags (attach, weapons, fingers, equip points).
SMALL_FLAG_SCALE = 0.1


def other_side(side):
    """
    :param str side: 'left' or 'right'.
    :return: The opposite side.
    :rtype: str
    """

    return 'right' if side == 'left' else 'left'


class BipedTemplate(rig_templates.RigTemplates):
    """
    Base template for two-legged character rigs.

    Configuration knobs (override on a subclass):

    * ``CLAVICLE_COMPONENT``   ``frag.ClavicleComponent`` (default) or ``frag.FKComponent``.
    * ``LEG_COMPONENT``        ``frag.ReverseFootComponent`` (default) or ``frag.ZLegComponent``.
    * ``FK_STUB_LEGS``         Build a single FK flag instead of ``LEG_COMPONENT`` when a leg chain is too short
                               for a reverse foot (thigh only).
    * ``FINGER_REGIONS``       Markup regions built as FK finger chains under each hand.
    * ``UPPER_TORSO_JOINT``    Joint the neck, clavicles and equip flags hang from. None uses the spine chain end.
    * ``BUILD_ATTACH``         Build the optional ``attach`` chain flag.
    * ``ATTACH_FLAG_TRANSLATES`` Leave the attach flag's translation unlocked.
    * ``BUILD_EQUIP_FLAGS``    Build the weapon_equip / thigh_equip flags when the skeleton has them.
    * ``BUILD_HEAD_FOLLOW``    Give the head flag a rotate follow space.
    * ``BUILD_SPINE_FOLLOW``   Give the spine sections rotate follow spaces (needs an RFK spine with sub flags).
    * ``ARMS_DEFAULT_TO_IK``   Start the arm IKFK switches in IK.
    * ``SPLIT_RIGHT_WEAPON_FOLLOW`` Give the right hand weapon separate rotate and point follow spaces (two handed
                               weapons) instead of one combined follow.

    During ``build`` the main components and flags are stored on the instance (``self.spine_component``,
    ``self.arm_components['left']``, ``self.offset_flag``...) so ``extend`` and the follow-target hooks can reach
    them without querying the rig.
    """

    VERSION = 1
    ASSET_ID = ''
    ASSET_TYPE = ''

    CLAVICLE_COMPONENT = frag.ClavicleComponent
    LEG_COMPONENT = frag.ReverseFootComponent
    FK_STUB_LEGS = False
    # A reverse foot needs thigh, calf, foot and ball joints.
    REVERSE_FOOT_MIN_JOINTS = 4
    FINGER_REGIONS = ('index_finger', 'middle_finger', 'ring_finger', 'pinky_finger', 'thumb')
    UPPER_TORSO_JOINT = 'spine_04'
    BUILD_ATTACH = True
    ATTACH_FLAG_TRANSLATES = True
    BUILD_EQUIP_FLAGS = True
    BUILD_HEAD_FOLLOW = True
    BUILD_SPINE_FOLLOW = True
    ARMS_DEFAULT_TO_IK = True
    SPLIT_RIGHT_WEAPON_FOLLOW = True

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)
        self.frag_rig = None
        self.root_joint = None
        self.chain = None
        # Every component created through _register, keyed by (side, region).
        self.components = {}

        self.world_component = None
        self.world_flag = None
        self.root_flag = None
        self.offset_flag = None
        self.attach_flag = None

        self.cog_component = None
        self.cog_flag = None
        self.pelvis_component = None
        self.pelvis_joint = None
        self.pelvis_flag = None
        self.spine_component = None
        self.spine_chain = None
        self.spine_sub_flags = []
        # The flag the arms and head follow by default, and the (component, joint) the upper body hangs from.
        self.upper_torso_flag = None
        self.upper_torso_parent = None
        self.neck_component = None
        self.neck_chain = None
        self.neck_flag = None
        self.mid_neck_flag = None
        self.head_flag = None

        self.clav_components = {}
        self.clav_flags = {}
        self.clav_chains = {}
        self.arm_components = {}
        self.arm_chains = {}
        self.hand_weapon_flags = {}
        self.leg_components = {}
        self.leg_chains = {}
        self.finger_components = {}
        # Equip flags keyed by (side, region); only present when the skeleton carries the joints.
        self.equip_flags = {}

    # --- Entry point --------------------------------------------------------------------------------------------

    def build(self, finalize=True):
        """
        Build the biped rig for the skeleton in the current scene.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        self._setup_scene()
        self._build_world()
        if self.BUILD_ATTACH:
            self._build_attach()
        self._build_torso()
        self._build_clavicles()
        self._build_arms()
        if self.BUILD_EQUIP_FLAGS:
            self._build_equip_flags()
        self._build_legs()
        self._build_fingers()
        self._build_constraints()
        self.extend()
        return self.finalize_rig(self.frag_rig, finalize)

    def extend(self):
        """
        Hook for subclasses to add character specific components after the shared biped is built.

        Runs after the follow constraints and before finalization, with all the instance attributes populated.
        The default does nothing.
        """

        pass

    # --- Lookup helpers -----------------------------------------------------------------------------------------

    def get_component(self, side, region):
        """
        Return a component this template built.

        :param str side: Component side.
        :param str region: Component region.
        :return: The component, or None if it was not built.
        :rtype: FRAGNode or None
        """

        return self.components.get((side, region))

    def _register(self, component):
        """
        Remember a component so ``get_component`` and subclasses can find it.

        :param FRAGNode component: A component created by this template.
        :return: The same component, for chaining.
        :rtype: FRAGNode
        """

        self.components[(component.side, component.region)] = component
        return component

    def _upper_torso_joint(self):
        """
        :return: The joint the neck, clavicles and equip flags hang from.
        :rtype: pm.nt.Joint
        """

        if self.UPPER_TORSO_JOINT and pm.objExists(self.UPPER_TORSO_JOINT):
            return pm.PyNode(self.UPPER_TORSO_JOINT)
        return self.spine_chain[1]

    def _fk_flag(self, frag_rig, start_joint, end_joint, side, region, **kwargs):
        """
        Build and register a single FK component. Thin wrapper that keeps the call sites short.

        :param FRAGRig frag_rig: The rig the component belongs to.
        :param pm.nt.Joint start_joint: First joint of the chain.
        :param pm.nt.Joint end_joint: Last joint of the chain.
        :param str side: Component side.
        :param str region: Component region.
        :param kwargs: Extra arguments for ``FKComponent.create``.
        :return: The FK component.
        :rtype: FKComponent
        """

        component = frag.FKComponent.create(frag_rig, start_joint, end_joint, side=side, region=region, **kwargs)
        return self._register(component)

    # --- Build steps --------------------------------------------------------------------------------------------

    def _setup_scene(self):
        """
        Create the FRAG root, skeletal mesh and rig nodes for the skeleton in the scene and read its markup.
        """

        pm.namespace(set=':')
        self.root_joint = pm.PyNode('root')
        frag_root = frag.FRAGRoot.create(self.root_joint, self.asset_type, self.asset_id)
        frag.SkeletalMesh.create(frag_root)
        self.frag_rig = frag.FRAGRig.create(frag_root)
        self.chain = chain_markup.ChainMarkup(self.root_joint)

    def _build_world(self):
        """
        Build the world component: the world, root and offset flags everything else follows.
        """

        self.world_component = frag.WorldComponent.create(self.frag_rig,
                                                          self.root_joint,
                                                          'center',
                                                          'world',
                                                          orientation=FLAT_FLAG_ORIENTATION)
        self._register(self.world_component)
        self.world_flag = self.world_component.world_flag
        self.root_flag = self.world_component.root_flag
        self.root_flag.set_as_sub()
        self.offset_flag = self.world_component.offset_flag
        self.offset_flag.set_as_detail()

    def _build_attach(self):
        """
        Build the attach flag when the skeleton carries an ``attach`` chain. Used to mount the character onto
        vehicles and props; the follow constraint later lets it ride the world or the root.
        """

        attach_chain = self.chain.get_chain('attach', 'center')
        if not attach_chain:
            return
        kwargs = {'scale': SMALL_FLAG_SCALE}
        if self.ATTACH_FLAG_TRANSLATES:
            # Only lock visibility so the flag can be moved off the root.
            kwargs['lock_root_translate_axes'] = ['v']
        attach_component = self._fk_flag(self.frag_rig, attach_chain[0], attach_chain[1], 'center', 'attach',
                                         **kwargs)
        attach_component.attach_component(self.world_component, self.root_joint)
        self.attach_flag = attach_component.get_flags()[0]
        self.attach_flag.set_as_detail()

    def _build_torso(self):
        """
        Build the cog, pelvis, spine and neck. The spine is built through ``_build_spine`` so subclasses can swap
        the spine component or re-point where the upper body hangs from.
        """

        self.pelvis_joint = self.chain.get_start('pelvis', 'center')
        self.spine_chain = self.chain.get_chain('spine', 'center')

        # Cog
        self.cog_component = frag.CogComponent.create(self.frag_rig,
                                                      self.pelvis_joint,
                                                      self.pelvis_joint,
                                                      'center',
                                                      'cog',
                                                      orientation=FLAT_FLAG_ORIENTATION)
        self._register(self.cog_component)
        self.cog_component.attach_component(self.world_component, pm.PyNode(self.offset_flag))
        self.cog_flag = self.cog_component.get_flags()[0]

        # Pelvis: pelvis joint to the first spine joint.
        self.pelvis_component = frag.PelvisComponent.create(self.frag_rig,
                                                            self.pelvis_joint,
                                                            self.spine_chain[0],
                                                            'center',
                                                            'pelvis',
                                                            orientation=FLAT_FLAG_ORIENTATION)
        self._register(self.pelvis_component)
        self.pelvis_component.attach_component(self.cog_component, pm.PyNode(self.cog_flag))
        self.pelvis_flag = self.pelvis_component.get_flags()[0]

        self._build_spine()

        # Neck: an RFK chain without sub flags. Its start is the neck flag, its end the head flag.
        self.neck_chain = self.chain.get_chain('neck', 'center')
        self.neck_component = frag.RFKComponent.create(self.frag_rig,
                                                       self.neck_chain[0],
                                                       self.neck_chain[1],
                                                       'center',
                                                       'neck',
                                                       False)
        self._register(self.neck_component)
        self.neck_component.attach_component(*self.upper_torso_parent)
        self.head_flag = self.neck_component.end_flag
        self.neck_flag = self.neck_component.start_flag
        self.neck_flag.set_as_sub()
        self.mid_neck_flag = self.neck_component.mid_flags[0]
        self.mid_neck_flag.set_as_detail()

    def _build_spine(self):
        """
        Build the RFK spine and record where the upper body hangs from.

        Sets ``self.spine_component``, ``self.spine_sub_flags``, ``self.upper_torso_flag`` (the spine's upper sub
        flag) and ``self.upper_torso_parent`` (the spine component plus the upper torso joint).
        """

        self.spine_component = frag.RFKComponent.create(self.frag_rig,
                                                        self.spine_chain[0],
                                                        self.spine_chain[1],
                                                        'center',
                                                        'spine')
        self._register(self.spine_component)
        self.spine_component.attach_component(self.cog_component, pm.PyNode(self.cog_flag))
        self.spine_sub_flags = self.spine_component.sub_flags
        self.upper_torso_flag = self.spine_sub_flags[1]
        self.upper_torso_parent = (self.spine_component, self._upper_torso_joint())

    def _build_clavicles(self):
        """
        Build both clavicles with ``CLAVICLE_COMPONENT`` and hang them off the upper torso.
        """

        for side in SIDES:
            clav_chain = self.chain.get_chain('clav', side)
            self.clav_chains[side] = clav_chain
            if self.CLAVICLE_COMPONENT is frag.ClavicleComponent:
                component = frag.ClavicleComponent.create(self.frag_rig, clav_chain[0], side=side)
                flag = component.get_start_flag()
            else:
                component = self.CLAVICLE_COMPONENT.create(self.frag_rig,
                                                           clav_chain[0],
                                                           clav_chain[1],
                                                           side=side,
                                                           region='clav',
                                                           lock_root_translate_axes=['v'])
                flag = component.get_flags()[0]
            self._register(component)
            component.attach_component(*self.upper_torso_parent)
            self.clav_components[side] = component
            self.clav_flags[side] = flag

    def _limb_parent(self, limb, side):
        """
        Return what a limb component attaches to. Hook for templates that put something between the body and
        the limb (surface pins on the familiars).

        :param str limb: 'arm' or 'leg'.
        :param str side: Limb side.
        :return: The parent component and the object the limb's groups are constrained to.
        :rtype: tuple(FRAGNode, pm.nt.Transform)
        """

        if limb == 'arm':
            return self.clav_components[side], self.clav_chains[side][0]
        return self.pelvis_component, self.pelvis_joint

    def _build_arms(self):
        """
        Build the IKFK arms and the hand weapon flag on each hand.
        """

        for side in SIDES:
            self.arm_chains[side] = self.chain.get_chain('arm', side)

        for side in SIDES:
            arm_chain = self.arm_chains[side]
            parent_component, parent_object = self._limb_parent('arm', side)
            arm_component = frag.IKFKComponent.create(self.frag_rig,
                                                      arm_chain[0],
                                                      arm_chain[1],
                                                      side=side,
                                                      region='arm',
                                                      ik_flag_pv_orient=LIMB_IK_ORIENTATION)
            self._register(arm_component)
            arm_component.attach_component(parent_component, parent_object)
            self.arm_components[side] = arm_component
            if self.ARMS_DEFAULT_TO_IK:
                arm_component.switch_flag.ikfk_switch.set(0)

            # Hand weapon: a free moving flag on the weapon joint so props can be posed independently.
            weapon_joint = self.chain.get_start('weapon', side)
            weapon_component = self._fk_flag(self.frag_rig, weapon_joint, weapon_joint, side, 'hand_weapon',
                                             scale=SMALL_FLAG_SCALE, lock_root_translate_axes=[])
            weapon_component.attach_component(arm_component, arm_chain[1])
            weapon_flag = weapon_component.get_flags()[0]
            weapon_flag.set_as_sub()
            self.hand_weapon_flags[side] = weapon_flag

    def _build_equip_flags(self):
        """
        Build the optional weapon equip flags (back, both hips) and thigh equip flags. Each only exists when the
        skeleton carries the joint, so the follow constraints check ``self.equip_flags``.
        """

        equip_points = [('center', 'weapon_equip', self.upper_torso_parent),
                        ('left', 'weapon_equip', self.upper_torso_parent),
                        ('right', 'weapon_equip', self.upper_torso_parent),
                        ('left', 'thigh_equip', (self.pelvis_component, self.pelvis_joint)),
                        ('right', 'thigh_equip', (self.pelvis_component, self.pelvis_joint))]
        for side, region, parent in equip_points:
            joint = self.chain.get_start(region, side)
            if not joint:
                continue
            component = self._fk_flag(self.frag_rig, joint, joint, side, region,
                                      scale=SMALL_FLAG_SCALE, lock_root_translate_axes=[])
            component.attach_component(*parent)
            flag = component.get_flags()[0]
            flag.set_as_detail()
            self.equip_flags[(side, region)] = flag

    def _build_legs(self):
        """
        Build both legs with ``LEG_COMPONENT``, or a single FK flag for stub legs when ``FK_STUB_LEGS`` is on.
        """

        for side in SIDES:
            leg_chain = self.chain.get_chain('leg', side)
            self.leg_chains[side] = leg_chain
            parent_component, parent_object = self._limb_parent('leg', side)

            full_chain = self.chain.get_full_chain('leg', side)
            if self.FK_STUB_LEGS and len(full_chain) < self.REVERSE_FOOT_MIN_JOINTS:
                # Stub leg: one FK flag with translation free so the leg can be offset from its attachment.
                leg_component = self._fk_flag(self.frag_rig, leg_chain[0], leg_chain[1], side, 'leg',
                                              lock_root_translate_axes=[])
            else:
                leg_component = self.LEG_COMPONENT.create(self.frag_rig,
                                                          leg_chain[0],
                                                          leg_chain[1],
                                                          side=side,
                                                          region='leg',
                                                          ik_flag_pv_orient=LIMB_IK_ORIENTATION,
                                                          ik_flag_orient=LIMB_IK_ORIENTATION)
                self._register(leg_component)
            leg_component.attach_component(parent_component, parent_object)
            self.leg_components[side] = leg_component

    def _build_fingers(self):
        """
        Build an FK chain for every finger region the skeleton has, parented to the hand.
        """

        for side in SIDES:
            arm_component = self.arm_components[side]
            hand_joint = self.arm_chains[side][1]
            for region in self.FINGER_REGIONS:
                finger_chain = self.chain.get_chain(region, side)
                if not finger_chain:
                    continue
                component = self._fk_flag(self.frag_rig, finger_chain[0], finger_chain[1], side, region,
                                          scale=SMALL_FLAG_SCALE)
                component.attach_component(arm_component, hand_joint)
                self.finger_components[(side, region)] = component

    # --- Follow spaces ------------------------------------------------------------------------------------------

    def _ik_arm_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Follow targets for the IK hand flag, first entry is the default.
        :rtype: list
        """

        return [self.offset_flag,
                self.clav_flags[side],
                self.arm_chains[other_side(side)][1],
                self.cog_flag,
                self.upper_torso_flag]

    def _fk_arm_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Rotate follow targets for the FK upper arm flag.
        :rtype: list
        """

        return [self.clav_flags[side], self.upper_torso_flag, self.offset_flag, self.cog_flag]

    def _arm_pv_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Follow targets for the arm pole vector.
        :rtype: list
        """

        return [self.offset_flag, self.clav_flags[side], self.upper_torso_flag, self.cog_flag]

    def _foot_follow_targets(self, side):
        """
        :param str side: Leg side.
        :return: Follow targets for the IK foot flag.
        :rtype: list
        """

        return [self.offset_flag, self.pelvis_flag, self.cog_flag]

    def _fk_leg_follow_targets(self, side):
        """
        :param str side: Leg side.
        :return: Rotate follow targets for an FK stub leg.
        :rtype: list
        """

        return [self.pelvis_flag, self.cog_flag, self.offset_flag]

    def _build_constraints(self):
        """
        Create every follow space (multi constraint) on the shared biped.
        """

        frag_rig = self.frag_rig

        frag.MultiConstraint.create(frag_rig,
                                    side='center',
                                    region='root',
                                    source_object=self.root_flag,
                                    target_list=[self.world_flag, self.offset_flag])

        if self.attach_flag:
            frag.MultiConstraint.create(frag_rig,
                                        side='center',
                                        region='attach',
                                        source_object=self.attach_flag,
                                        target_list=[self.world_flag, self.offset_flag, self.root_flag])

        for side in SIDES:
            arm_component = self.arm_components[side]
            frag.MultiConstraint.create(frag_rig,
                                        side=side,
                                        region='arm',
                                        source_object=arm_component.ik_flag,
                                        target_list=lists.remove_none(self._ik_arm_follow_targets(side)),
                                        switch_obj=arm_component.switch_flag,
                                        switch_attr='follow')
            frag.MultiConstraint.create(frag_rig,
                                        side=side,
                                        region='fk_arm',
                                        source_object=arm_component.fk_flags[0],
                                        target_list=lists.remove_none(self._fk_arm_follow_targets(side)),
                                        t=False,
                                        switch_attr='rotateFollow')
            frag.MultiConstraint.create(frag_rig,
                                        side=side,
                                        region='arm_pv',
                                        source_object=arm_component.pv_flag,
                                        target_list=lists.remove_none(self._arm_pv_follow_targets(side)),
                                        switch_obj=None)

        if self.BUILD_HEAD_FOLLOW:
            frag.MultiConstraint.create(frag_rig,
                                        side='center',
                                        region='head',
                                        source_object=self.head_flag,
                                        target_list=[self.offset_flag, self.neck_flag, self.mid_neck_flag,
                                                     self.cog_flag],
                                        switch_obj=None,
                                        translate=False,
                                        switch_attr='rotateFollow')

        self._build_leg_constraints()
        if self.BUILD_SPINE_FOLLOW:
            self._build_spine_constraints()
        self._build_weapon_constraints()

    def _build_leg_constraints(self):
        """
        Follow spaces for the legs: IK foot and pole vector for full legs, a rotate follow for FK stub legs.
        """

        for side in SIDES:
            leg_component = self.leg_components[side]
            ik_flag = getattr(leg_component, 'ik_flag', None)
            if ik_flag:
                frag.MultiConstraint.create(self.frag_rig,
                                            side=side,
                                            region='foot',
                                            source_object=ik_flag,
                                            target_list=lists.remove_none(self._foot_follow_targets(side)),
                                            switch_obj=leg_component.switch_flag)
                frag.MultiConstraint.create(self.frag_rig,
                                            side=side,
                                            region='leg_pv',
                                            source_object=leg_component.pv_flag,
                                            target_list=[self.offset_flag, ik_flag, self.cog_flag],
                                            switch_obj=None)
            else:
                frag.MultiConstraint.create(self.frag_rig,
                                            side=side,
                                            region='fk_leg',
                                            source_object=leg_component.get_flags()[0],
                                            target_list=lists.remove_none(self._fk_leg_follow_targets(side)),
                                            t=False,
                                            switch_attr='rotateFollow')

    def _build_spine_constraints(self):
        """
        Rotate follow spaces down the spine so each section can follow its neighbour or the cog.
        """

        spine = self.spine_component
        spine_sections = [('spine_top', self.upper_torso_flag, [spine.end_flag, spine.mid_flags[1]]),
                          ('spine_mid_top', spine.mid_flags[1], [spine.mid_offset_groups[1], spine.mid_flags[0]]),
                          ('spine_mid_bottom', spine.mid_flags[0], [spine.mid_offset_groups[0], spine.start_flag])]
        for region, source_flag, targets in spine_sections:
            frag.MultiConstraint.create(self.frag_rig,
                                        side='center',
                                        region=region,
                                        source_object=source_flag,
                                        target_list=targets + [self.cog_flag],
                                        switch_obj=None,
                                        translate=False,
                                        switch_attr='rotateFollow',
                                        default_name='default')

    def _build_weapon_constraints(self):
        """
        Follow spaces for the hand weapon flags. The right hand weapon gets separate rotate and point follows so a
        two handed weapon can sit in one hand while aiming with the other; equip flags join the list when present.
        """

        l_weapon_flag = self.hand_weapon_flags['left']
        r_weapon_flag = self.hand_weapon_flags['right']
        l_hand = self.arm_chains['left'][1]
        r_hand = self.arm_chains['right'][1]
        c_equip_flag = self.equip_flags.get(('center', 'weapon_equip'))

        if c_equip_flag:
            # The back equip point can follow the spine, cog, head or world for holstering.
            equip_targets = [self.spine_component.get_flags()[-1], self.cog_flag, self.head_flag, self.offset_flag]
            frag.MultiConstraint.create(self.frag_rig,
                                        side='center',
                                        region='rotate_equip_weapon',
                                        source_object=c_equip_flag,
                                        target_list=equip_targets,
                                        translate=False,
                                        scale=False,
                                        switch_obj=None,
                                        switch_attr='rotateFollow')
            frag.MultiConstraint.create(self.frag_rig,
                                        side='right',
                                        region='equip_weapon',
                                        source_object=c_equip_flag,
                                        target_list=equip_targets,
                                        rotate=False,
                                        switch_obj=None,
                                        switch_attr='pointFollow')

        r_weapon_targets = [r_hand, l_weapon_flag, self.cog_flag, self.head_flag]
        if c_equip_flag:
            r_weapon_targets += [c_equip_flag,
                                 self.equip_flags.get(('right', 'weapon_equip')),
                                 self.equip_flags.get(('left', 'weapon_equip'))]
        r_weapon_targets.append(self.offset_flag)
        r_weapon_targets = lists.remove_none(r_weapon_targets)

        if self.SPLIT_RIGHT_WEAPON_FOLLOW:
            frag.MultiConstraint.create(self.frag_rig,
                                        side='right',
                                        region='rotate_weapon',
                                        source_object=r_weapon_flag,
                                        target_list=r_weapon_targets,
                                        translate=False,
                                        scale=False,
                                        switch_obj=None,
                                        switch_attr='rotateFollow',
                                        default_name='r_hand')
            frag.MultiConstraint.create(self.frag_rig,
                                        side='right',
                                        region='weapon',
                                        source_object=r_weapon_flag,
                                        target_list=r_weapon_targets,
                                        rotate=False,
                                        switch_obj=None,
                                        switch_attr='pointFollow',
                                        default_name='r_hand')
        else:
            frag.MultiConstraint.create(self.frag_rig,
                                        side='right',
                                        region='weapon',
                                        source_object=r_weapon_flag,
                                        target_list=r_weapon_targets,
                                        switch_obj=None,
                                        default_name='r_hand')
        frag.MultiConstraint.create(self.frag_rig,
                                    side='left',
                                    region='weapon',
                                    source_object=l_weapon_flag,
                                    target_list=[l_hand, r_weapon_flag, self.cog_flag, self.head_flag,
                                                 self.offset_flag],
                                    switch_obj=None,
                                    default_name='l_hand')

    # --- Shared extension helpers -------------------------------------------------------------------------------

    def _build_fk_chains(self, regions, parent_component, parent_object, scale=1.0, mark=None, end_flag_only=False,
                         **kwargs):
        """
        Build an FK chain for each (side, region) pair and attach it to one parent. Used by subclasses for cloth,
        pouches, armour plates, ears and similar secondary chains.

        :param list(tuple(str, str)) regions: (side, region) pairs to build. Missing chains are skipped with a
            warning.
        :param FRAGNode parent_component: Component the chains attach to.
        :param pm.nt.Transform parent_object: Object the chain groups are constrained to.
        :param float scale: Flag scale.
        :param str mark: 'detail' or 'sub' to mark the flags as detail or sub flags; None leaves them primary.
        :param bool end_flag_only: Only mark the end flag rather than every flag on the chain.
        :param kwargs: Extra arguments for ``FKComponent.create`` (``lock_root_translate_axes``...).
        :return: The components that were built, keyed by (side, region).
        :rtype: dict
        """

        built = {}
        for side, region in regions:
            joints = self.chain.get_chain(region, side)
            if not joints:
                logger.warning('{0}: no "{1}" chain on the {2} side, skipping.'.format(self.asset_id, region, side))
                continue
            component = self._fk_flag(self.frag_rig, joints[0], joints[1], side, region, scale=scale, **kwargs)
            component.attach_component(parent_component, parent_object)
            if mark:
                flags = [component.get_end_flag()] if end_flag_only else component.get_flags()
                for flag in flags:
                    if mark == 'sub':
                        flag.set_as_sub()
                    else:
                        flag.set_as_detail()
            built[(side, region)] = component
        return built
