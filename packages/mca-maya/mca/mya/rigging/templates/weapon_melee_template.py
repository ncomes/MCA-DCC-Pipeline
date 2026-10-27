"""
Rig templates for melee weapons.

Holds ``WeaponMelee`` (a single handle flag under the world component, the base for hand held melee props),
``WhipTemplate`` (handle plus a retractable spline chain and a lantern) and ``ConduitSwordV1Template`` (the melee
base with an FK chain hanging off the weapon).

Requires: pymel and a weapon skeleton (``root`` / ``weapon`` joints, plus chain markup for the whip and the sword)
already in the scene.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging.templates import rig_templates

logger = log.MCA_LOGGER


class WeaponMelee(rig_templates.RigTemplates):
    """
    Base template for hand held melee weapons.

    Creates the FRAG root, skeletal mesh and rig for the skeleton in the scene, a world component on ``root`` and a
    single FK flag in the ``handle`` region on the ``weapon`` joint, with a ``hand_prop`` follow space over the
    world flag, the root flag and the flags group. Joints are addressed by their hard-coded names.
    """

    VERSION = 1
    ASSET_ID = ''
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the melee weapon rig for the skeleton in the current scene.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        if self.asset_id == '':
            raise RuntimeError('Please enter an asset id.')

        pm.namespace(set=':')
        root_joint = pm.PyNode('root')

        # The template creates the whole FRAG hierarchy itself; the skeleton must already be in the scene.
        frag_root = frag.FRAGRoot.create(root_joint, self.asset_type, self.asset_id)
        frag.SkeletalMesh.create(frag_root)
        frag_rig = frag.FRAGRig.create(frag_root)

        # The flags group (flagsAll) is used as a follow target alongside the world and root flags; kept as built.
        flags_all = frag_rig.pynode.flagsAll.get()

        world_component = frag.WorldComponent.create(frag_rig,
                                                     root_joint,
                                                     'center',
                                                     'world',
                                                     orientation=[-90, 0, 0])  # Flat on the ground plane.
        world_flag = world_component.world_flag
        root_flag = world_component.root_flag
        root_flag.set_as_sub()
        world_component.offset_flag.set_as_detail()

        weapon_joint = pm.PyNode('weapon')
        weapon_component = frag.FKComponent.create(frag_rig,
                                                   weapon_joint,
                                                   weapon_joint,
                                                   side='center',
                                                   region='handle',
                                                   lock_root_translate_axes=['v'])
        weapon_component.attach_component(world_component, root_joint)
        weapon_flag = weapon_component.get_end_flag()

        frag.MultiConstraint.create(frag_rig,
                                    side='right',
                                    region='hand_prop',
                                    source_object=weapon_flag,
                                    target_list=[world_flag, root_flag, flags_all],
                                    switch_obj=None)

        return self.finalize_rig(frag_rig, finalize)


class WhipTemplate(rig_templates.RigTemplates):
    """
    Template for the chain whip.

    Creates a world component, an FK ``weapon`` flag on the handle, a ``SporeTongueComponent`` spline over the
    ``chain_hi`` joints (driven by the ``chain_start`` / ``chain_mid`` / ``chain_end`` helpers, with leaf joints
    and retract) and an FK ``lantern`` flag that rides the end of the chain. Joints are found through the
    skeleton's chain markup.
    """

    VERSION = 1
    ASSET_ID = ''
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the whip rig for the skeleton in the current scene.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        if self.asset_id == '':
            raise RuntimeError('Please enter an asset id.')

        pm.namespace(set=':')
        root = pm.PyNode('root')
        chain = chain_markup.ChainMarkup(root)
        frag_root = frag.FRAGRoot.create(root, self.asset_type, self.asset_id)
        frag.SkeletalMesh.create(frag_root)
        frag_rig = frag.FRAGRig.create(frag_root)

        start_joint = chain.get_start(region='root', side='center')
        world_component = frag.WorldComponent.create(frag_rig,
                                                     start_joint,
                                                     'center',
                                                     'world',
                                                     orientation=[-90, 0, 0])  # Flat on the ground plane.
        world_component.root_flag.set_as_sub()
        world_component.offset_flag.set_as_detail()

        weapon_joints = chain.get_chain(region='weapon', side='center')
        weapon_component = frag.FKComponent.create(frag_rig,
                                                   weapon_joints[0],
                                                   weapon_joints[0],
                                                   side='center',
                                                   region='weapon',
                                                   lock_root_translate_axes=['v'])
        weapon_component.attach_component([world_component], [root])

        # Chain spline: the hi-res chain is shaped by the start / mid / end helper joints and can retract into the
        # handle.
        chain_start, chain_end = chain.get_chain('chain_hi', 'center')
        start_chain_joint = chain.get_chain('chain_start', 'center')[0]
        mid_chain_joint = chain.get_chain('chain_mid', 'center')[0]
        end_chain_joint = chain.get_chain('chain_end', 'center')[0]
        leaf_joints = chain.get_full_chain('chain_leaf', 'center')
        whip_component = frag.SporeTongueComponent.create(frag_parent=frag_rig,
                                                          start_joint=chain_start,
                                                          end_joint=chain_end,
                                                          end_helper_joint=end_chain_joint,
                                                          mid_helper_joint=mid_chain_joint,
                                                          start_helper_joint=start_chain_joint,
                                                          leaf_joint_list=leaf_joints,
                                                          side='center',
                                                          region='chain_whip',
                                                          mid_flag=True,
                                                          can_retract=True)
        whip_component.attach_component(weapon_component, weapon_joints[0])

        lantern_joint = chain.get_start(region='lantern', side='center')
        lantern_component = frag.FKComponent.create(frag_rig,
                                                    lantern_joint,
                                                    lantern_joint,
                                                    side='center',
                                                    region='lantern',
                                                    lock_root_translate_axes=['v'])
        lantern_component.attach_component([whip_component], [chain_end])

        return self.finalize_rig(frag_rig, finalize)


class ConduitSwordV1Template(WeaponMelee):
    """
    Conduit sword: the melee base rig plus an FK ``chain`` component hanging off the weapon.

    The chain joints come from chain markup and the component attaches to the FK component the base built in the
    ``weapon`` region.
    """

    VERSION = 1
    ASSET_ID = 'swordv1'
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the melee base rig, then add the sword's chain.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        frag_rig = super().build(finalize=False)

        chain = chain_markup.ChainMarkup(pm.PyNode('root'))

        # The base template builds the weapon handle flag in the 'handle' region; the chain hangs off it.
        weapon_component = lists.get_first_in_list(frag_rig.get_frag_children(of_type=frag.FKComponent,
                                                                              side='center',
                                                                              region='handle'))
        if not weapon_component:
            logger.warning('{0}: no center "handle" FK component on the rig; the chain was not built.'.format(
                self.asset_id))
            return self.finalize_rig(frag_rig, finalize)

        chain_start, chain_end = chain.get_chain(region='chain', side='center')
        chain_component = frag.FKComponent.create(frag_rig,
                                                  chain_start,
                                                  chain_end,
                                                  side='center',
                                                  region='chain',
                                                  lock_root_translate_axes=['v'])
        chain_component.attach_component(weapon_component, pm.PyNode('weapon'))

        return self.finalize_rig(frag_rig, finalize)
