"""
Rig templates for props.

Holds ``PropTemplate`` (world component plus a free moving ``base`` flag, an optional floor contact flag and an
optional ``sub_prop_01`` flag) and ``PottedMonsteraTemplate`` (pot base plus the FK stem and branch chains of the
potted monstera plant).

Requires: pymel and a prop skeleton with chain markup already in the scene.
"""

import pymel.core as pm

from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging.templates import rig_templates


class PropTemplate(rig_templates.RigTemplates):
    """
    Generic prop template.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root`` and a free moving FK ``base``
    flag under the offset flag. When the skeleton carries them it also builds a ``floor_contact`` flag (a contact
    flag that is not constrained to the offset) and a ``sub_base`` flag on the ``sub_prop_01`` joint parented to
    the base. Joints are found through chain markup.
    """

    VERSION = 1
    ASSET_ID = 'baseprop'
    ASSET_TYPE = 'prop'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the prop rig for the skeleton in the current scene.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        pm.namespace(set=':')
        root_joint = pm.PyNode('root')

        # The template creates the whole FRAG hierarchy itself; the skeleton must already be in the scene.
        frag_root = frag.FRAGRoot.create(root_joint, self.asset_type, self.asset_id)
        frag.SkeletalMesh.create(frag_root)
        frag_rig = frag.FRAGRig.create(frag_root)

        root = frag_root.root_joint
        hierarchy_markup = chain_markup.ChainMarkup(root)

        world_component = frag.WorldComponent.create(frag_rig,
                                                     root,
                                                     'center',
                                                     'world',
                                                     orientation=[-90, 0, 0])  # Flat on the ground plane.
        root_flag = world_component.root_flag
        root_flag.set_as_sub()
        offset_flag = world_component.offset_flag
        offset_flag.set_as_detail()

        # Base: the main prop flag, free to translate.
        base_joint = hierarchy_markup.get_start('base', 'center')
        base_component = frag.FKComponent.create(frag_rig,
                                                 base_joint,
                                                 base_joint,
                                                 side='center',
                                                 region='base',
                                                 lock_root_translate_axes=[])
        base_component.attach_component(world_component, pm.PyNode(offset_flag))

        # Floor contact: lives under the world component but is not constrained to it so it can stay on the ground.
        floor_joint = hierarchy_markup.get_start('floor', 'center')
        if floor_joint:
            floor_component = frag.FKComponent.create(frag_rig,
                                                      floor_joint,
                                                      floor_joint,
                                                      side='center',
                                                      region='floor_contact',
                                                      lock_root_translate_axes=[])
            floor_component.attach_component(world_component, pm.PyNode(offset_flag), point=False, orient=False)
            floor_flag = floor_component.get_end_flag()
            floor_flag.set_as_contact()

        # Optional secondary prop riding on the base.
        sub_base_joint = hierarchy_markup.get_start('sub_prop_01', 'center')
        if sub_base_joint:
            sub_prop_01_component = frag.FKComponent.create(frag_rig,
                                                            sub_base_joint,
                                                            sub_base_joint,
                                                            side='center',
                                                            region='sub_base',
                                                            lock_root_translate_axes=[])
            sub_prop_01_component.attach_component(base_component, base_joint)

        return self.finalize_rig(frag_rig, finalize)


class PottedMonsteraTemplate(rig_templates.RigTemplates):
    """
    Rig template for the potted monstera plant with its animated stem chains.

    Creates the FRAG root, skeletal mesh and rig, a world component, an FK ``pot_base`` flag and three stem bases
    (front, mid, back) hanging off the pot, each carrying its FK stem and branch chains (eleven chains in total).
    All stem flags are scaled down for detail work. Joints are found through chain markup, except the branch
    joints the chains attach to, which are addressed by name.
    """

    VERSION = 1
    ASSET_ID = 'pottedmonstera'
    ASSET_TYPE = 'prop'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the potted monstera rig with a world component and the FK stem chains.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        pm.namespace(set=':')
        root_joint = pm.PyNode('root')

        # The FRAG hierarchy has to be created in this order: root, skeletal mesh, rig.
        frag_root = frag.FRAGRoot.create(root_joint, self.asset_type, self.asset_id)
        frag.SkeletalMesh.create(frag_root)
        frag_rig = frag.FRAGRig.create(frag_root)

        hierarchy_markup = chain_markup.ChainMarkup(root_joint)

        # The world component is always first so everything else can attach to it.
        world_component = frag.WorldComponent.create(
            frag_rig, root_joint, 'center', 'world', orientation=[-90, 0, 0]  # Flat on the ground plane.
        )
        root_flag = world_component.root_flag
        root_flag.set_as_sub()
        offset_flag = world_component.offset_flag

        # Pot base FK component. The pot flag is a little larger (0.15) than the stem detail flags (0.1).
        pot_base = hierarchy_markup.get_start('pot_base', 'center')
        pot_component = frag.FKComponent.create(
            frag_rig, pot_base, pot_base,
            side='center', region='pot_base', scale=0.15
        )
        pot_component.attach_component(world_component, pm.PyNode(offset_flag))

        # --- Front stem section ---
        # Main front stem base (single joint)
        stem_base_frnt = hierarchy_markup.get_start('stem_base_frnt', 'center')
        stem_base_frnt_component = frag.FKComponent.create(
            frag_rig, stem_base_frnt, stem_base_frnt,
            side='center', region='stem_base_frnt', scale=0.1
        )
        stem_base_frnt_component.attach_component(pot_component, pm.PyNode(pot_base))

        # Front stem chain (3 joints)
        stem_frnt_start, stem_frnt_end = hierarchy_markup.get_chain('stem_base_stem_frnt', 'center')
        stem_frnt_component = frag.FKComponent.create(
            frag_rig, stem_frnt_start, stem_frnt_end,
            side='center', region='stem_base_stem_frnt', scale=0.1
        )
        stem_frnt_component.attach_component(stem_base_frnt_component, pm.PyNode(stem_base_frnt))

        # Front side stem chain (3 joints)
        stem_frnt_side_start, stem_frnt_side_end = hierarchy_markup.get_chain('stem_base_stem_frnt_side', 'center')
        stem_frnt_side_component = frag.FKComponent.create(
            frag_rig, stem_frnt_side_start, stem_frnt_side_end,
            side='center', region='stem_base_stem_frnt_side', scale=0.1
        )
        stem_frnt_side_component.attach_component(stem_base_frnt_component, pm.PyNode(stem_base_frnt))

        # --- Mid stem section ---
        # Main mid stem base (single joint)
        stem_base_mid = hierarchy_markup.get_start('stem_base_mid', 'center')
        stem_base_mid_component = frag.FKComponent.create(
            frag_rig, stem_base_mid, stem_base_mid,
            side='center', region='stem_base_mid', scale=0.1
        )
        stem_base_mid_component.attach_component(pot_component, pm.PyNode(pot_base))

        # Mid stem chain (3 joints), attached to its parent joint in the hierarchy rather than the base joint.
        stem_mid_start, stem_mid_end = hierarchy_markup.get_chain('stem_base_stem_mid', 'center')
        stem_mid_component = frag.FKComponent.create(
            frag_rig, stem_mid_start, stem_mid_end,
            side='center', region='stem_base_stem_mid', scale=0.1
        )
        stem_base_branch_mid_01 = pm.PyNode('stem_base_branch_mid_01')
        stem_mid_component.attach_component(stem_base_mid_component, stem_base_branch_mid_01)

        # Long branch chain (4 joints); the remaining mid chains all hang off the same branch joint.
        stem_long_start, stem_long_end = hierarchy_markup.get_chain('stem_long_branch', 'center')
        stem_long_component = frag.FKComponent.create(
            frag_rig, stem_long_start, stem_long_end,
            side='center', region='stem_long_branch', scale=0.1
        )
        stem_base_stem_branch_01 = pm.PyNode('stem_base_stem_branch_01')
        stem_long_component.attach_component(stem_base_mid_component, stem_base_stem_branch_01)

        # Mid branch chain (3 joints)
        stem_mid_br_start, stem_mid_br_end = hierarchy_markup.get_chain('stem_mid_branch', 'center')
        stem_mid_br_component = frag.FKComponent.create(
            frag_rig, stem_mid_br_start, stem_mid_br_end,
            side='center', region='stem_mid_branch', scale=0.1
        )
        stem_mid_br_component.attach_component(stem_base_mid_component, stem_base_stem_branch_01)

        # Side branch chain (3 joints)
        stem_side_start, stem_side_end = hierarchy_markup.get_chain('stem_side_branch', 'center')
        stem_side_component = frag.FKComponent.create(
            frag_rig, stem_side_start, stem_side_end,
            side='center', region='stem_side_branch', scale=0.1
        )
        stem_side_component.attach_component(stem_base_mid_component, stem_base_stem_branch_01)

        # Back branch chain (3 joints)
        stem_bk_br_start, stem_bk_br_end = hierarchy_markup.get_chain('stem_bk_branch', 'center')
        stem_bk_br_component = frag.FKComponent.create(
            frag_rig, stem_bk_br_start, stem_bk_br_end,
            side='center', region='stem_bk_branch', scale=0.1
        )
        stem_bk_br_component.attach_component(stem_base_mid_component, stem_base_stem_branch_01)

        # Long mid chain (3 joints)
        stem_long_mid_start, stem_long_mid_end = hierarchy_markup.get_chain('stem_long_mid', 'center')
        stem_long_mid_component = frag.FKComponent.create(
            frag_rig, stem_long_mid_start, stem_long_mid_end,
            side='center', region='stem_long_mid', scale=0.1
        )
        stem_long_mid_component.attach_component(stem_base_mid_component, stem_base_stem_branch_01)

        # --- Back stem section ---
        # Main back stem base (single joint)
        stem_base_bk = hierarchy_markup.get_start('stem_base_bk', 'center')
        stem_base_bk_component = frag.FKComponent.create(
            frag_rig, stem_base_bk, stem_base_bk,
            side='center', region='stem_base_bk', scale=0.1
        )
        stem_base_bk_component.attach_component(pot_component, pm.PyNode(pot_base))

        # Back stem chain (3 joints); the back chains hang off the back branch joint.
        stem_bk_start, stem_bk_end = hierarchy_markup.get_chain('stem_base_stem_bk', 'center')
        stem_bk_component = frag.FKComponent.create(
            frag_rig, stem_bk_start, stem_bk_end,
            side='center', region='stem_base_stem_bk', scale=0.1
        )
        stem_base_branch_bk_01 = pm.PyNode('stem_base_branch_bk_01')
        stem_bk_component.attach_component(stem_base_bk_component, stem_base_branch_bk_01)

        # Back side stem chain (3 joints)
        stem_bk_side_start, stem_bk_side_end = hierarchy_markup.get_chain('stem_base_stem_bk_side', 'center')
        stem_bk_side_component = frag.FKComponent.create(
            frag_rig, stem_bk_side_start, stem_bk_side_end,
            side='center', region='stem_base_stem_bk_side', scale=0.1
        )
        stem_bk_side_component.attach_component(stem_base_bk_component, stem_base_branch_bk_01)

        # Small stem chain (3 joints)
        stem_small_start, stem_small_end = hierarchy_markup.get_chain('stem_small_stem', 'center')
        stem_small_component = frag.FKComponent.create(
            frag_rig, stem_small_start, stem_small_end,
            side='center', region='stem_small_stem', scale=0.1
        )
        stem_small_component.attach_component(stem_base_bk_component, stem_base_branch_bk_01)

        return self.finalize_rig(frag_rig, finalize)
