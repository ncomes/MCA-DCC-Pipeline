"""
Rig templates for shotguns.

Holds ``WeaponShotgunTemplate`` (world, weapon, trigger and magazine flags with ``hand_prop`` and ``magazine``
follow spaces) and ``SG870ArmatusTemplate`` (the shotgun base plus bolt carrier, forestock, forestock grip and
loading hinge flags).

Requires: pymel and a shotgun skeleton with chain markup already in the scene.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging.templates import rig_templates

logger = log.MCA_LOGGER


class WeaponShotgunTemplate(rig_templates.RigTemplates):
    """
    Base template for shotguns.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root``, an FK ``weapon`` flag, a
    ``trigger`` flag locked to rotation only and a ``magazine`` flag. The weapon flag gets a ``hand_prop`` follow
    space and the magazine a follow space over the weapon, world and root flags. Joints are found through the
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
        Build the shotgun rig for the skeleton in the current scene.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        if self.asset_id == '':
            raise RuntimeError('Please enter an asset id.')

        pm.namespace(set=':')
        root_joint = pm.PyNode('root')
        chain = chain_markup.ChainMarkup(root_joint)

        # The template creates the whole FRAG hierarchy itself; the skeleton must already be in the scene.
        frag_root = frag.FRAGRoot.create(root_joint, self.asset_type, self.asset_id)
        frag.SkeletalMesh.create(frag_root)
        frag_rig = frag.FRAGRig.create(frag_root)

        # The flags group (flagsAll) is used as a follow target alongside the world and root flags; kept as built.
        flags_all = frag_rig.pynode.flagsAll.get()

        start_joint = chain.get_start('root', 'center')
        world_component = frag.WorldComponent.create(frag_rig,
                                                     start_joint,
                                                     'center',
                                                     'world',
                                                     orientation=[-90, 0, 0])  # Flat on the ground plane.
        world_flag = world_component.world_flag
        root_flag = world_component.root_flag
        root_flag.set_as_sub()
        world_component.offset_flag.set_as_detail()

        weapon_joint = chain.get_start('weapon', 'center')
        weapon_component = frag.FKComponent.create(frag_rig,
                                                   weapon_joint,
                                                   weapon_joint,
                                                   side='center',
                                                   region='weapon',
                                                   lock_root_translate_axes=['v'])
        weapon_component.attach_component(world_component, root_joint)
        weapon_flag = weapon_component.get_end_flag()

        trigger_joint = chain.get_start('trigger', 'center')
        trigger_component = frag.FKComponent.create(frag_rig,
                                                    trigger_joint,
                                                    trigger_joint,
                                                    side='center',
                                                    region='trigger',
                                                    lock_root_translate_axes=['ty', 'tz', 'tx', 'v'])
        trigger_component.attach_component(weapon_component, weapon_joint)

        magazine_joint = chain.get_start('magazine', 'center')
        magazine_component = frag.FKComponent.create(frag_rig,
                                                     magazine_joint,
                                                     magazine_joint,
                                                     side='center',
                                                     region='magazine',
                                                     lock_root_translate_axes=['v'])
        magazine_component.attach_component(weapon_component, weapon_joint)
        magazine_flag = magazine_component.get_end_flag()

        frag.MultiConstraint.create(frag_rig,
                                    side='right',
                                    region='hand_prop',
                                    source_object=weapon_flag,
                                    target_list=[world_flag, root_flag, flags_all],
                                    switch_obj=None)

        # The magazine can follow the weapon (default), the world, the root or the flags group.
        frag.MultiConstraint.create(frag_rig,
                                    side='center',
                                    region='magazine',
                                    source_object=magazine_flag,
                                    target_list=[weapon_flag, world_flag, root_flag, flags_all],
                                    switch_obj=None)

        return self.finalize_rig(frag_rig, finalize)


class SG870ArmatusTemplate(WeaponShotgunTemplate):
    """
    SG870 Armatus shotgun: the shotgun base rig plus translate-only FK flags for the right ``bolt_carrier``, the
    ``forestock``, the ``forestock_grip`` and the ``loading_hinge``, all attached to the weapon.
    """

    VERSION = 1
    ASSET_ID = 'sg870armatus'
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the shotgun base rig, then add the moving parts of the SG870.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        frag_rig = super().build(finalize=False)
        root_joint = pm.PyNode('root')
        chain = chain_markup.ChainMarkup(root_joint)

        weapon_component = lists.get_first_in_list(frag_rig.get_frag_children(of_type=frag.FKComponent,
                                                                              side='center',
                                                                              region='weapon'))
        if not weapon_component:
            logger.warning('{0}: no center "weapon" FK component on the rig; the moving parts were not '
                           'built.'.format(self.asset_id))
            return self.finalize_rig(frag_rig, finalize)
        weapon_joint = chain.get_start('weapon', 'center')

        # Every moving part is a single joint flag that slides along the weapon, so rotation is locked.
        bolt_carrier = chain.get_start('bolt_carrier', 'right')
        bolt_carrier_component = frag.FKComponent.create(frag_rig,
                                                         bolt_carrier,
                                                         bolt_carrier,
                                                         side='right',
                                                         region='bolt_carrier',
                                                         lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        bolt_carrier_component.attach_component(weapon_component, weapon_joint)

        forestock = chain.get_start('forestock', 'center')
        forestock_component = frag.FKComponent.create(frag_rig,
                                                      forestock,
                                                      forestock,
                                                      side='center',
                                                      region='forestock',
                                                      lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        forestock_component.attach_component(weapon_component, weapon_joint)

        forestock_grip = chain.get_start('forestock_grip', 'center')
        forestock_grip_component = frag.FKComponent.create(frag_rig,
                                                           forestock_grip,
                                                           forestock_grip,
                                                           side='center',
                                                           region='forestock_grip',
                                                           lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        forestock_grip_component.attach_component(weapon_component, weapon_joint)

        loading_hinge = chain.get_start('loading_hinge', 'center')
        loading_hinge_component = frag.FKComponent.create(frag_rig,
                                                          loading_hinge,
                                                          loading_hinge,
                                                          side='center',
                                                          region='loading_hinge',
                                                          lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        loading_hinge_component.attach_component(weapon_component, weapon_joint)

        return self.finalize_rig(frag_rig, finalize)
