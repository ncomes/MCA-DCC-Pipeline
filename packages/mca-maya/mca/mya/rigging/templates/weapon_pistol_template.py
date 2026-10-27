"""
Rig templates for pistols.

Holds ``WeaponPistolTemplate`` (world, weapon, trigger and magazine flags with ``hand_prop`` and ``magazine``
follow spaces) and ``AlienPistolTemplate`` (the pistol base plus a sliding breech flag).

Requires: pymel and a pistol skeleton (``root`` / ``weapon`` / ``trigger_01`` / ``magazine_01``, plus ``breech``
for the alien pistol) already in the scene.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.rigging import frag
from mca.mya.rigging.templates import rig_templates

logger = log.MCA_LOGGER


class WeaponPistolTemplate(rig_templates.RigTemplates):
    """
    Base template for pistols.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root``, an FK ``weapon`` flag, a
    ``trigger`` flag locked to rotation only and a ``magazine`` flag. The weapon flag gets a ``hand_prop`` follow
    space and the magazine a follow space over the weapon, world and root flags.

    This template predates chain markup lookups, so it addresses joints by their hard-coded names (``weapon``,
    ``trigger_01``, ``magazine_01``).
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
        Build the pistol rig for the skeleton in the current scene.

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
                                                   region='weapon',
                                                   lock_root_translate_axes=['v'])
        weapon_component.attach_component(world_component, root_joint)
        weapon_flag = weapon_component.get_end_flag()

        trigger_joint = pm.PyNode('trigger_01')
        trigger_component = frag.FKComponent.create(frag_rig,
                                                    trigger_joint,
                                                    trigger_joint,
                                                    side='center',
                                                    region='trigger',
                                                    lock_root_translate_axes=['ty', 'tz', 'tx', 'v'])
        trigger_component.attach_component(weapon_component, weapon_joint)

        magazine_joint = pm.PyNode('magazine_01')
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


class AlienPistolTemplate(WeaponPistolTemplate):
    """
    Alien pistol: the pistol base rig plus a ``breech`` FK flag that only translates, attached to the weapon.
    """

    VERSION = 1
    ASSET_ID = 'alienpistol'
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the pistol base rig, then add the breech flag.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        frag_rig = super().build(finalize=False)

        weapon_component = lists.get_first_in_list(frag_rig.get_frag_children(of_type=frag.FKComponent,
                                                                              side='center',
                                                                              region='weapon'))
        if not weapon_component:
            logger.warning('{0}: no center "weapon" FK component on the rig; the breech was not built.'.format(
                self.asset_id))
            return self.finalize_rig(frag_rig, finalize)

        breech_joint = pm.PyNode('breech')
        breech_component = frag.FKComponent.create(frag_rig,
                                                   breech_joint,
                                                   breech_joint,
                                                   side='center',
                                                   region='breech',
                                                   lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        breech_component.attach_component(weapon_component, pm.PyNode('weapon'))

        return self.finalize_rig(frag_rig, finalize)
