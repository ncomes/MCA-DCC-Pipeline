"""
Rig templates for the familiar creatures (jellybeans).

A familiar is the biped with three twists: the limbs can hang off surface pin joints that slide over the body
mesh (``UVSlideComponent``), the spine is a squash and stretch RFK, and a leg may be a single stub joint that
gets one FK flag instead of a reverse foot. The emote variant also exposes the blend shape targets as animatable
channels on the head flag so Unreal receives them as curves.

Requires: a skeleton whose pin joints carry a ``uvpin*`` markup region between each limb and its parent.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.deformations import skin_utils
from mca.mya.rigging import chain_markup
from mca.mya.rigging import frag
from mca.mya.rigging.templates import biped_template
from mca.mya.utils import attr_utils
from mca.mya.utils import uvpin_utils

logger = log.MCA_LOGGER

# Skeleton markup region (prefix) of a joint that sits between a limb chain and its parent and rides the body
# surface. Jellybean skeletons mark these 'uvpin'; a per limb region such as 'uvpin_arm' also matches.
UV_PIN_REGION_PREFIX = 'uvpin'
# How far the jellybean limbs may slide from their rest spot, in flag units (about world units). U runs around
# the body (flag translateY), V runs up / down (translateZ). Tune here; the UV shell limits still apply on top.
JELLYBEAN_PIN_SLIDE_LIMITS = {'arm_pin': {'u': (-10.0, 10.0), 'v': (-10.0, 10.0)},
                              'leg_pin': {'u': (-8.0, 8.0), 'v': (-6.0, 6.0)}}


class BaseFamiliarTemplate(biped_template.BipedTemplate):
    """
    Familiar biped: surface pinned limbs, a stretch spine, optional stub legs, no fingers and no equip flags.

    Pin knobs (override on a subclass):

    * ``PIN_MESH``          Body mesh the pin joints ride. None picks the closest skinned mesh that is not weighted
                            to the pin joint (or anything under it), which keeps the pin from driving the surface
                            it reads.
    * ``PIN_UV_SET``        Hand authored single shell UV set on that mesh to slide in. When the mesh does not carry
                            it the component generates a planar slide set instead.
    * ``PIN_LOCK_ROTATE``   Pin flags are pure slide controls with rotation locked. False lets the flag rotate the
                            limb joint.
    * ``PIN_SLIDE_LIMITS``  Slide caps per pin region in flag units, ``{'arm_pin': {'u': (min, max), 'v': ...}}``.
                            They tighten the automatic UV shell limits.
    """

    VERSION = 2
    ASSET_ID = 'familiar'
    ASSET_TYPE = 'familiar'

    FINGER_REGIONS = ()
    BUILD_EQUIP_FLAGS = False
    FK_STUB_LEGS = True

    PIN_MESH = None
    PIN_UV_SET = 'rig_uv'
    PIN_LOCK_ROTATE = True
    PIN_SLIDE_LIMITS = {}

    def __init__(self, asset_id=ASSET_ID, asset_type=ASSET_TYPE):
        """
        :param str asset_id: Asset registry id the rig is built for.
        :param str asset_type: Asset category stored on the FRAG root.
        """

        super().__init__(asset_id, asset_type)
        # Surface pin components keyed by (side, region) so subclasses can reach the pin flags.
        self.pin_components = {}
        # Follow target per limb (side, 'arm' / 'leg'): the pin JOINT rather than the pin flag. The flag sits in a
        # fixed rest frame and never turns, so following it would leave the limb at its world orientation while
        # the attachment slides around the body; the joint takes the surface orientation.
        self.pin_follow = {}

    # --- Build step overrides -----------------------------------------------------------------------------------

    def _build_spine(self):
        """
        Build a squash and stretch RFK spine. Spine leaf joints, when the skeleton has them, take the scaling so
        the primary spine joints stay scale free.
        """

        spine_leaf_joints = self.chain.get_full_chain('spine_leaf', 'center')
        self.spine_component = frag.RFKStretchComponent.create(self.frag_rig,
                                                               self.spine_chain[0],
                                                               self.spine_chain[1],
                                                               'center',
                                                               'spine',
                                                               leaf_joint_list=spine_leaf_joints)
        self._register(self.spine_component)
        self.spine_component.attach_component(self.cog_component, pm.PyNode(self.cog_flag))
        self.spine_sub_flags = self.spine_component.sub_flags
        self.upper_torso_flag = self.spine_sub_flags[1]
        self.upper_torso_parent = (self.spine_component, self._upper_torso_joint())

    def _limb_parent(self, limb, side):
        """
        Attach a limb below its surface pin joint when the skeleton has one, otherwise to the body as usual.

        Building the pin here (rather than in a separate step) keeps the pin and the limb that rides it together.

        :param str limb: 'arm' or 'leg'.
        :param str side: Limb side.
        :return: The parent component and the object the limb's groups are constrained to.
        :rtype: tuple(FRAGNode, pm.nt.Transform)
        """

        body_component, body_object = super()._limb_parent(limb, side)
        chain_start = (self.arm_chains if limb == 'arm' else self.leg_chains)[side][0]
        pin_component = self._create_limb_pin(chain_start, side, '{0}_pin'.format(limb), body_component, body_object)
        if not pin_component:
            return body_component, body_object
        pin_joint = chain_start.getParent()
        self.pin_follow[(side, limb)] = pin_joint
        return pin_component, pin_joint

    def _create_limb_pin(self, chain_start, side, region, parent_component, parent_object):
        """
        Build the surface pin component for a limb when its chain start sits under a uvpin joint.

        :param pm.nt.Joint chain_start: First joint of the limb chain (upper arm, thigh).
        :param str side: Side of the limb.
        :param str region: Component region, e.g. 'arm_pin'.
        :param FRAGNode parent_component: Component the pin hangs off (clavicle, pelvis).
        :param pm.nt.Transform parent_object: Object the pin's groups are constrained to.
        :return: The pin component, or None when the skeleton has no pin joint for this limb.
        :rtype: UVSlideComponent or None
        """

        pin_joint = get_pin_parent_joint(chain_start)
        if not pin_joint:
            return None

        pin_mesh = None
        if self.PIN_MESH and pm.objExists(self.PIN_MESH):
            pin_mesh = pm.PyNode(self.PIN_MESH)
        region_limits = self.PIN_SLIDE_LIMITS.get(region, {})
        lock_rotate_axes = attr_utils.ROTATION_ATTRS if self.PIN_LOCK_ROTATE else ()
        pin_component = create_surface_pin(self.frag_rig, pin_joint, side, region, pin_mesh=pin_mesh,
                                           uv_set=self.PIN_UV_SET,
                                           lock_rotate_axes=lock_rotate_axes,
                                           slide_limit_u=region_limits.get('u'),
                                           slide_limit_v=region_limits.get('v'))
        if pin_component:
            self._register(pin_component)
            pin_component.attach_component(parent_component, parent_object)
            self.pin_components[(side, region)] = pin_component
        return pin_component

    # --- Follow space overrides ---------------------------------------------------------------------------------
    # The pin joint is the limb's real shoulder / hip when the skeleton has one: it leads the follow lists so the
    # limb rides the surface by default (IK hand and pole vector included). World follow stays available.

    def _ik_arm_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Follow targets for the IK hand, pin joint first.
        :rtype: list
        """

        return [self.pin_follow.get((side, 'arm'))] + super()._ik_arm_follow_targets(side)

    def _fk_arm_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Rotate follow targets for the FK upper arm, pin joint first.
        :rtype: list
        """

        return [self.pin_follow.get((side, 'arm'))] + super()._fk_arm_follow_targets(side)

    def _arm_pv_follow_targets(self, side):
        """
        :param str side: Arm side.
        :return: Follow targets for the arm pole vector, pin joint first.
        :rtype: list
        """

        return [self.pin_follow.get((side, 'arm'))] + super()._arm_pv_follow_targets(side)

    def _foot_follow_targets(self, side):
        """
        :param str side: Leg side.
        :return: Follow targets for the IK foot with the pin joint after the world offset.
        :rtype: list
        """

        return [self.offset_flag, self.pin_follow.get((side, 'leg')), self.pelvis_flag, self.cog_flag]

    def _fk_leg_follow_targets(self, side):
        """
        :param str side: Leg side.
        :return: Rotate follow targets for an FK stub leg, pin joint first.
        :rtype: list
        """

        return [self.pin_follow.get((side, 'leg'))] + super()._fk_leg_follow_targets(side)

    def _build_weapon_constraints(self):
        """
        Hand weapon follow spaces. Familiars carry no equip points and the right hand only needs a point follow.
        """

        l_weapon_flag = self.hand_weapon_flags['left']
        r_weapon_flag = self.hand_weapon_flags['right']
        frag.MultiConstraint.create(self.frag_rig,
                                    side='left',
                                    region='weapon',
                                    source_object=l_weapon_flag,
                                    target_list=[self.arm_chains['left'][1], r_weapon_flag, self.cog_flag,
                                                 self.head_flag, self.offset_flag],
                                    switch_obj=None,
                                    default_name='l_hand')
        frag.MultiConstraint.create(self.frag_rig,
                                    side='right',
                                    region='weapon',
                                    source_object=r_weapon_flag,
                                    target_list=[self.arm_chains['right'][1], l_weapon_flag, self.cog_flag,
                                                 self.head_flag, self.offset_flag],
                                    rotate=False,
                                    switch_obj=None,
                                    switch_attr='pointFollow',
                                    default_name='r_hand')


class JellybeanFamiliarTemplate(BaseFamiliarTemplate):
    """
    Jellybean familiar: the arms and legs pin to the bean body mesh.
    """

    VERSION = 2
    ASSET_ID = 'jellybeanbase'
    ASSET_TYPE = 'jellybean'
    # The limb mesh is skinned to the pin joints and must not be used as the pin surface.
    PIN_MESH = 'Familiar_low'
    PIN_SLIDE_LIMITS = JELLYBEAN_PIN_SLIDE_LIMITS


class JellybeanEmoteFamiliarTemplate(JellybeanFamiliarTemplate):
    """
    Jellybean familiar rig plus animatable emote blend shape curves for Unreal.

    A mini face setup: every target on the scene's blend shape node(s) (e.g. BS_Emotes - Smile, Sad, Angry...)
    is exposed as a 0-1 attribute on the head flag and proxied onto the root joint through a
    ChannelFloatComponent. The exporter bakes those root attributes into the FBX as custom-attribute curves,
    which Unreal imports as anim curves that auto-drive the morph targets of the same name.
    """

    VERSION = 2

    def extend(self):
        """
        Expose the blend shape targets on the head flag so animators key them alongside the head.
        """

        head_flag = self.neck_component.end_flag
        setup_blendshape_channels(self.frag_rig, head_flag.node)


# --- Surface pin helpers ------------------------------------------------------------------------------------------

def get_pin_parent_joint(joint):
    """
    Return the surface pin joint directly above a limb chain start, if the skeleton has one.

    A pin joint is recognised by its skeleton markup region starting with UV_PIN_REGION_PREFIX, so both a shared
    'uvpin' region and per limb regions ('uvpin_arm') work. Lookup is by hierarchy rather than markup region
    because several pin joints per side share the same region and ChainMarkup only keeps one start per region.

    :param pm.nt.Joint joint: First joint of a limb chain.
    :return: The pin joint above it, or None.
    :rtype: pm.nt.Joint or None
    """

    if not joint:
        return None
    parent = joint.getParent()
    if not parent or not isinstance(parent, pm.nt.Joint):
        return None
    region = chain_markup.JointMarkup(parent).region or ''
    if region.startswith(UV_PIN_REGION_PREFIX):
        return parent
    return None


def find_pin_mesh(pin_joint):
    """
    Return the skinned mesh a pin joint can ride: the closest one not weighted to the joint or its descendants.

    A pin drives the joint that follows it, so a mesh deformed by that joint would feed back into the pin. Meshes
    weighted to the pin joint or anything under it (the limb mesh) are skipped.

    :param pm.nt.Joint pin_joint: The surface pin joint.
    :return: The closest eligible skinned mesh transform, or None.
    :rtype: pm.nt.Transform or None
    """

    excluded = set([pin_joint] + pin_joint.listRelatives(ad=True, type=pm.nt.Joint))
    joint_position = pin_joint.getTranslation(space='world')
    best_mesh = None
    best_distance = None
    for skin_node in pm.ls(type=pm.nt.SkinCluster):
        if excluded & set(skin_node.getInfluence()):
            continue
        for shape in skin_node.getOutputGeometry():
            mesh = shape.getParent()
            if not isinstance(shape, pm.nt.Mesh) or not mesh:
                continue
            closest_point, _, _ = uvpin_utils.get_closest_point_normal(mesh, joint_position)
            distance = (closest_point - joint_position).length()
            if best_distance is None or distance < best_distance:
                best_mesh, best_distance = mesh, distance
    if best_mesh:
        logger.debug(f'Pin mesh for {pin_joint}: {best_mesh} ({best_distance:.3f} units away).')
    return best_mesh


def remove_pin_feedback_influences(pin_mesh, pin_joint):
    """
    Drop zero weight influences that would loop a surface pin back through the mesh it reads.

    The pin drives the pin joint, so the joint (or anything under it) being a skinCluster influence on the pin
    mesh is a DG cycle even at zero weight: the skinCluster still reads the joint's world matrix. Leftover
    zero weight influences (a thigh once painted on the body, then cleaned up) are removed; influences that
    carry real weight are left alone and reported, since removing them would change the deformation.

    :param pm.nt.Transform pin_mesh: The mesh the pin reads.
    :param pm.nt.Joint pin_joint: The joint the pin drives.
    :return: The influences that were removed.
    :rtype: list(pm.nt.Joint)
    """

    skin_node = skin_utils.get_skin_cluster_from_geometry(pin_mesh)
    if not skin_node:
        return []
    skin_node = pm.PyNode(skin_node)
    feedback_joints = set([pin_joint] + pin_joint.listRelatives(ad=True, type=pm.nt.Joint))
    influences = set(skin_node.getInfluence())
    # weightedInfluence only lists influences with non zero weights somewhere on the mesh.
    weighted = set(pm.skinCluster(skin_node, q=True, weightedInfluence=True) or [])

    removed = []
    for influence in sorted(influences & feedback_joints, key=lambda x: x.nodeName()):
        if influence in weighted:
            logger.warning(f'{pin_mesh} is weighted to {influence}, which sits under the pin joint {pin_joint}: '
                           'this is an evaluation cycle. Move those weights off the limb joints.')
            continue
        pm.skinCluster(skin_node, e=True, removeInfluence=influence)
        removed.append(influence)
        logger.info(f'Removed zero weight influence {influence} from {skin_node} to keep {pin_joint} cycle free.')
    return removed


def create_surface_pin(frag_rig, pin_joint, side, region, pin_mesh=None, uv_set=None, **kwargs):
    """
    Build a UVSlideComponent for a pin joint, choosing the mesh and UV set to slide in.

    Uses uv_set when the mesh carries it (a hand authored single shell set); otherwise the component generates a
    planar slide set around the attachment point.

    :param FRAGRig frag_rig: The rig the component is parented to.
    :param pm.nt.Joint pin_joint: Skeleton joint that rides the surface.
    :param str side: Component side.
    :param str region: Component region.
    :param pm.nt.Transform pin_mesh: Mesh to pin to. Defaults to find_pin_mesh(pin_joint).
    :param str uv_set: Preferred UV set on the mesh.
    :param kwargs: Extra UVSlideComponent.create arguments (scale, lock_rotate_axes...).
    :return: The pin component, or None when no eligible mesh was found.
    :rtype: UVSlideComponent or None
    """

    pin_mesh = pin_mesh or find_pin_mesh(pin_joint)
    if not pin_mesh:
        logger.warning(f'{pin_joint}: no skinned mesh to pin to, skipping the surface pin.')
        return None
    remove_pin_feedback_influences(pin_mesh, pin_joint)

    uv_sets = pm.polyUVSet(pin_mesh, q=True, allUVSets=True) or []
    if uv_set and uv_set in uv_sets:
        kwargs['uv_set'] = uv_set
    else:
        if uv_set:
            logger.info(f'{pin_mesh} has no "{uv_set}" UV set; generating a slide set for {pin_joint}.')
        kwargs['create_uv_set'] = True

    return frag.UVSlideComponent.create(frag_rig, pin_joint, pin_mesh, side=side, region=region, **kwargs)


# --- Emote channel helpers ----------------------------------------------------------------------------------------

def get_export_blendshape_nodes():
    """
    Return the blendShape nodes that deform a skinned (export) mesh.

    Shape transfer workflows leave blendShape nodes on the target meshes themselves (e.g. a node on the Angry
    target with a single 'Familiar_low' target). Those must not become animator channels, so only nodes whose
    deformed geometry also carries a skinCluster count.

    :return: Blend shape nodes on skinned meshes.
    :rtype: list(pm.nt.BlendShape)
    """

    export_nodes = []
    for blendnode in pm.ls(type=pm.nt.BlendShape):
        deformed = blendnode.getOutputGeometry() or []
        if any(skin_utils.get_skin_cluster_from_geometry(shape) for shape in deformed):
            export_nodes.append(blendnode)
        else:
            logger.info(f'{blendnode}: deforms {deformed}, no skinCluster there, not exposing its targets.')
    return export_nodes


def setup_blendshape_channels(frag_rig, flag_node, joint=None, blendshape_nodes=None,
                              component_name='emote_channels'):
    """
    Expose blend shape targets as flag attributes and mirror them onto an export joint for Unreal.

    For each target the flag gains a keyable 0-1 float attribute (named exactly after the target) that drives
    the blendShape weight directly. A ChannelFloatComponent then proxies each attribute onto the export joint,
    so animation exports carry one custom-attribute curve per shape; in Unreal those curves auto-drive the
    morph targets because the names match.

    Targets whose weights are already driven by another node (correctives, combos) are skipped so existing
    wiring is never broken.

    :param FRAGRig frag_rig: The FRAGRig the channel component is parented to.
    :param pm.nt.Transform flag_node: Flag transform that receives the animatable attributes.
    :param pm.nt.Joint joint: Export joint that receives the proxy attributes. Defaults to the root joint.
    :param list(pm.nt.BlendShape) blendshape_nodes: Blend shape nodes to expose. Defaults to the blendShape nodes
        that deform a skinned mesh (see get_export_blendshape_nodes), so transfer helpers on target meshes are
        ignored.
    :param str component_name: Region name used for the ChannelFloatComponent.
    :return: The created ChannelFloatComponent, or None when there were no targets to expose.
    :rtype: ChannelFloatComponent or None
    """

    if joint is None:
        joint = pm.PyNode('root')
    if blendshape_nodes is None:
        blendshape_nodes = get_export_blendshape_nodes()

    channel_dicts = []
    for blendnode in blendshape_nodes:
        # The multi indices on .weight are aliased to the target names (e.g. BS_Emotes.Smile).
        target_names = pm.listAttr(blendnode.attr('weight'), multi=True) or []
        for target_name in target_names:
            weight_attr = blendnode.attr(target_name)
            if weight_attr.isDestination():
                logger.info(f'{weight_attr}: already driven, leaving existing connection in place.')
                continue
            if not flag_node.hasAttr(target_name):
                flag_node.addAttr(target_name, at='float', min=0.0, max=1.0, dv=0.0, k=True)
            flag_node.attr(target_name) >> weight_attr
            channel_dicts.append(frag.create_channel_float_dict(obj_attr_name=target_name,
                                                                joint_attr_name=target_name,
                                                                attr_min=0.0,
                                                                attr_max=1.0,
                                                                default_value=0.0,
                                                                keyable=True))

    if not channel_dicts:
        logger.warning('No free blend shape targets found; no emote channels were created.')
        return None

    # One channel component fans all of the flag attributes onto the export joint.
    return frag.ChannelFloatComponent.create(frag_parent=frag_rig,
                                             obj=flag_node,
                                             joint=joint,
                                             channel_dict_list=channel_dicts,
                                             component_name=component_name)
