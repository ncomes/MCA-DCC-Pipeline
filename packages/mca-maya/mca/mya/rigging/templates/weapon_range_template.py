"""
Rig templates for ranged weapons (rifles).

Holds ``WeaponRangeTemplate`` (world, weapon, trigger and magazine flags), ``AR4Template`` (the range base plus
charge handle, shell eject, eject hatch, fire mode and magazine bullet flags), ``WeaponRangeTemplate2`` (bolt,
breech, breech door and magazine variant), ``WeaponLeverActionTemplate`` (bolt carrier, carrier door, loading
hinge, trigger and hammer) and ``WeaponArmatusTemplate`` (bolt carrier and trigger).

``AR4Template`` finds its joints through chain markup; the other templates predate that and address joints by
their hard-coded names.

Requires: pymel and a weapon skeleton already in the scene.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging.templates import rig_templates

logger = log.MCA_LOGGER


class WeaponRangeTemplate(rig_templates.RigTemplates):
    """
    Base template for rifles.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root``, an FK ``weapon`` flag, a
    ``trigger`` flag that only rotates around Y and a ``magazine`` flag. The weapon flag gets a ``hand_prop``
    follow space and the magazine a follow space over the weapon, world and root flags. Joints are addressed by
    their hard-coded names (``weapon``, ``trigger``, ``magazine``).
    """

    VERSION = 1
    ASSET_ID = 'SR25'  # Asset registry id of the rifle this template was written for.
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the rifle rig for the skeleton in the current scene.

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

        world_component = frag.WorldComponent.create(frag_rig,
                                                     root_joint,
                                                     'center',
                                                     'world',
                                                     orientation=[-90, 0, 0])  # Flat on the ground plane.
        world_flag = world_component.world_flag
        root_flag = world_component.root_flag

        weapon_joint = pm.PyNode('weapon')
        weapon_component = frag.FKComponent.create(frag_rig,
                                                   weapon_joint,
                                                   weapon_joint,
                                                   side='center',
                                                   region='weapon',
                                                   lock_root_translate_axes=['v'])
        weapon_component.attach_component(world_component, root_joint)
        weapon_flag = weapon_component.get_end_flag()

        trigger_joint = pm.PyNode('trigger')
        trigger_component = frag.FKComponent.create(frag_rig,
                                                    trigger_joint,
                                                    trigger_joint,
                                                    side='center',
                                                    region='trigger',
                                                    lock_root_translate_axes=['ty', 'tz', 'tx', 'rx', 'rz', 'v'])
        trigger_component.attach_component(weapon_component, weapon_joint)

        magazine_joint = pm.PyNode('magazine')
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
                                    target_list=[world_flag, root_flag],
                                    switch_obj=None)

        # The magazine can follow the weapon (default), the world or the root.
        frag.MultiConstraint.create(frag_rig,
                                    side='center',
                                    region='magazine',
                                    source_object=magazine_flag,
                                    target_list=[weapon_flag, world_flag, root_flag],
                                    switch_obj=None)

        return self.finalize_rig(frag_rig, finalize)


class AR4Template(WeaponRangeTemplate):
    """
    AR4 rifle: the rifle base rig plus translate-only FK flags for the ``chargehandle``, ``shelleject``,
    ``shelleject_hatch``, ``firemode`` and ``mag_bullets`` joints, all attached to the weapon. Joints are found
    through chain markup.
    """

    VERSION = 1
    ASSET_ID = 'ar4'
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the rifle base rig, then add the moving parts of the AR4.

        :param bool finalize: If the rig should be finalized (display layers, flag swap, colours).
        :return: The FRAG rig that was built.
        :rtype: FRAGRig
        """

        frag_rig = super().build(finalize=False)

        chain = chain_markup.ChainMarkup(pm.PyNode('root'))

        weapon_component = lists.get_first_in_list(frag_rig.get_frag_children(of_type=frag.FKComponent,
                                                                              side='center',
                                                                              region='weapon'))
        if not weapon_component:
            logger.warning('{0}: no center "weapon" FK component on the rig; the moving parts were not '
                           'built.'.format(self.asset_id))
            return self.finalize_rig(frag_rig, finalize)

        weapon_joint = chain.get_start('weapon', 'center')

        # Every moving part is a single joint flag that slides along the weapon, so rotation is locked.
        chargehandle_joint = chain.get_start('chargehandle', 'center')
        chargehandle_component = frag.FKComponent.create(frag_rig,
                                                         chargehandle_joint,
                                                         chargehandle_joint,
                                                         side='center',
                                                         region='chargehandle',
                                                         lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        chargehandle_component.attach_component(weapon_component, weapon_joint)

        shelleject_joint = chain.get_start('shelleject', 'center')
        shelleject_component = frag.FKComponent.create(frag_rig,
                                                       shelleject_joint,
                                                       shelleject_joint,
                                                       side='center',
                                                       region='shelleject',
                                                       lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        shelleject_component.attach_component(weapon_component, weapon_joint)

        shelleject_hatch = chain.get_start('shelleject_hatch', 'center')
        shelleject_hatch_component = frag.FKComponent.create(frag_rig,
                                                             shelleject_hatch,
                                                             shelleject_hatch,
                                                             side='center',
                                                             region='shelleject_hatch',
                                                             lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        shelleject_hatch_component.attach_component(weapon_component, weapon_joint)

        firemode = chain.get_start('firemode', 'center')
        firemode_component = frag.FKComponent.create(frag_rig,
                                                     firemode,
                                                     firemode,
                                                     side='center',
                                                     region='firemode',
                                                     lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        firemode_component.attach_component(weapon_component, weapon_joint)

        mag_bullets = chain.get_start('mag_bullets', 'center')
        mag_bullets_component = frag.FKComponent.create(frag_rig,
                                                        mag_bullets,
                                                        mag_bullets,
                                                        side='center',
                                                        region='mag_bullets',
                                                        lock_root_translate_axes=['rx', 'ry', 'rz', 'v'])
        mag_bullets_component.attach_component(weapon_component, weapon_joint)

        return self.finalize_rig(frag_rig, finalize)


class WeaponRangeTemplate2(rig_templates.RigTemplates):
    """
    Rifle variant with a bolt and a breech.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root``, an FK ``weapon`` flag, a
    ``bolt`` sub flag that slides along X, a right side ``breech`` flag that slides along X, a ``breech_door``
    flag that rotates around X and a ``magazine`` flag. The weapon flag gets a ``hand_prop`` follow space and the
    magazine a follow space over the weapon, world, root and flags group. Joints are addressed by their hard-coded
    names.
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
        Build the bolt rifle rig for the skeleton in the current scene.

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

        bolt_joint = pm.PyNode('bolt_01')
        bolt_component = frag.FKComponent.create(frag_rig,
                                                 bolt_joint,
                                                 bolt_joint,
                                                 side='center',
                                                 region='bolt',
                                                 lock_root_translate_axes=['ty', 'tz', 'rx', 'ry', 'rz', 'v'])
        bolt_component.attach_component(weapon_component, weapon_joint)
        bolt_flag = bolt_component.get_end_flag()
        bolt_flag.set_as_sub()

        breech_joint = pm.PyNode('breech_01')
        breech_component = frag.FKComponent.create(frag_rig,
                                                   breech_joint,
                                                   breech_joint,
                                                   side='right',
                                                   region='breech',
                                                   lock_root_translate_axes=['ty', 'tz', 'rx', 'ry', 'rz', 'v'])
        breech_component.attach_component(weapon_component, weapon_joint)

        breech_door_joint = pm.PyNode('breech_door_01')
        breech_door_component = frag.FKComponent.create(frag_rig,
                                                        breech_door_joint,
                                                        breech_door_joint,
                                                        side='right',
                                                        region='breech_door',
                                                        lock_root_translate_axes=['ty', 'tz', 'tx', 'ry', 'rz', 'v'])
        breech_door_component.attach_component(weapon_component, weapon_joint)

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


class WeaponLeverActionTemplate(rig_templates.RigTemplates):
    """
    Lever action rifle.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root``, an FK ``weapon`` flag and free
    moving FK flags for the ``bolt_carrier_01``, ``bolt_carrier_door_01``, ``loading_hinge_01``, ``trigger_01``
    and ``hammer_01`` joints, all attached to the weapon. The weapon flag gets a ``hand_prop`` follow space.
    Joints are addressed by their hard-coded names.
    """

    VERSION = 1
    ASSET_ID = '0izd-squ37-ksv3j-388j'  # Asset registry id of the lever action rifle this template was written for.
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the lever action rifle rig for the skeleton in the current scene.

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

        bolt_joint = pm.PyNode('bolt_carrier_01')
        bolt_component = frag.FKComponent.create(frag_rig,
                                                 bolt_joint,
                                                 bolt_joint,
                                                 side='center',
                                                 region='bolt',
                                                 lock_root_translate_axes=['v'])
        bolt_component.attach_component(weapon_component, weapon_joint)

        bolt_door_joint = pm.PyNode('bolt_carrier_door_01')
        bolt_door_component = frag.FKComponent.create(frag_rig,
                                                      bolt_door_joint,
                                                      bolt_door_joint,
                                                      side='center',
                                                      region='bolt_carrier',
                                                      lock_root_translate_axes=['v'])
        bolt_door_component.attach_component(weapon_component, weapon_joint)

        hinge_joint = pm.PyNode('loading_hinge_01')
        hinge_component = frag.FKComponent.create(frag_rig,
                                                  hinge_joint,
                                                  hinge_joint,
                                                  side='center',
                                                  region='hinge',
                                                  lock_root_translate_axes=['v'])
        hinge_component.attach_component(weapon_component, weapon_joint)

        trigger_joint = pm.PyNode('trigger_01')
        trigger_component = frag.FKComponent.create(frag_rig,
                                                    trigger_joint,
                                                    trigger_joint,
                                                    side='center',
                                                    region='trigger',
                                                    lock_root_translate_axes=['v'])
        trigger_component.attach_component(weapon_component, weapon_joint)

        hammer_joint = pm.PyNode('hammer_01')
        hammer_component = frag.FKComponent.create(frag_rig,
                                                   hammer_joint,
                                                   hammer_joint,
                                                   side='center',
                                                   region='hammer',
                                                   lock_root_translate_axes=['v'])
        hammer_component.attach_component(weapon_component, weapon_joint)

        frag.MultiConstraint.create(frag_rig,
                                    side='right',
                                    region='hand_prop',
                                    source_object=weapon_flag,
                                    target_list=[world_flag, root_flag, flags_all],
                                    switch_obj=None)

        return self.finalize_rig(frag_rig, finalize)


class WeaponArmatusTemplate(rig_templates.RigTemplates):
    """
    Armatus rifle.

    Creates the FRAG root, skeletal mesh and rig, a world component on ``root``, an FK ``weapon`` flag and free
    moving FK flags for the ``bolt_carrier_01`` and ``trigger_01`` joints attached to the weapon. The weapon flag
    gets a ``hand_prop`` follow space. Joints are addressed by their hard-coded names.
    """

    VERSION = 1
    ASSET_ID = '7hww-o4nip-3n02l-mtkz'  # Asset registry id of the Armatus rifle this template was written for.
    ASSET_TYPE = 'weapon'

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)

    def build(self, finalize=True):
        """
        Build the Armatus rifle rig for the skeleton in the current scene.

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

        bolt_joint = pm.PyNode('bolt_carrier_01')
        bolt_component = frag.FKComponent.create(frag_rig,
                                                 bolt_joint,
                                                 bolt_joint,
                                                 side='center',
                                                 region='bolt',
                                                 lock_root_translate_axes=['v'])
        bolt_component.attach_component(weapon_component, weapon_joint)

        trigger_joint = pm.PyNode('trigger_01')
        trigger_component = frag.FKComponent.create(frag_rig,
                                                    trigger_joint,
                                                    trigger_joint,
                                                    side='center',
                                                    region='trigger',
                                                    lock_root_translate_axes=['v'])
        trigger_component.attach_component(weapon_component, weapon_joint)

        frag.MultiConstraint.create(frag_rig,
                                    side='right',
                                    region='hand_prop',
                                    source_object=weapon_flag,
                                    target_list=[world_flag, root_flag, flags_all],
                                    switch_obj=None)

        return self.finalize_rig(frag_rig, finalize)
