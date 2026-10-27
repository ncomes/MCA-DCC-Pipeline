"""
FRAG component that pins a single joint to a mesh surface and lets its flag slide across that surface.

Built for things like an arm stuck onto a jelly bean body, where the attachment point has to ride the
body mesh and the animator wants to drag the attachment around the surface.

How it works (VERSION 2):

- Two ``uvPin`` nodes read the pin mesh. The REST pin sits at a fixed UV (the joint's rest spot) and
  carries the flag: the flag lives under a group driven by ``restPin.outputMatrix`` so it follows the
  mesh through skinning and blendshapes, oriented to the surface frame (X normal, Y along U, Z along V).
  The SLIDE pin carries the rig joint that drives the skeleton joint; its coordinates are driven by the
  flag's translateY / translateZ.
- The flag's translate is a plain translate in the rest surface frame. That keeps the move gizmo
  stable: the flag moves exactly along its own axes when dragged, while the joint slides along the
  mesh underneath. (VERSION 1 fed the negated translate back into the flag's own offsetParentMatrix to
  keep the flag glued to the joint; the gizmo axes moved under the mouse and jittered.) On curved
  areas the flag drifts off the surface for large slides; the joint never does.
- The UV-per-world-unit ratio is measured from the mesh at build time so one unit of flag translate
  is roughly one world unit of slide, with the sign matched to the pin's tangent axes.
- Limits: the slide pin's UV shell is sampled and shrunk to a rectangle that lies fully on the shell
  (``uvpin_utils.get_uv_shell_rect``), converted to translate limits and applied as transform limits
  plus a clamp node. ``slide_limit_u`` / ``slide_limit_v`` cap them further in flag units, so a
  template can keep the slide inside an artistic range.
- Rotation is locked by default (pure slide control). Unlocked, the flag rotate turns the joint about
  its own position in the slide surface frame. Translate X (the surface normal) is locked by default.
- UV sets: a uvPin can only slide inside ONE UV shell, and render UVs are usually cut into many. Pass
  ``uv_set`` to read a hand made slide set, or ``create_uv_set=True`` to generate one with
  ``uvpin_utils.create_planar_uv_set`` (``uvslide_<side>_<region>``). The mesh's current UV set is
  left untouched for rendering.

The pin / mesh UV helpers live in ``mca.mya.utils.uvpin_utils``; this module only holds the rig wiring.

Requires: pymel
Side effects: creates two uvPin nodes connected to the pin mesh's worldMesh, transform limits on the flag,
optionally a new UV set on the pin mesh's original shape.
"""

import pymel.core as pm

from mca.common import log
from mca.common.utils import lists
from mca.mya.modeling import rivets
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging import chain_markup, joint_utils
from mca.mya.rigging.flags import frag_flag
from mca.mya.rigging.frag import keyable_component
from mca.mya.utils import attr_utils, constraint, naming, uvpin_utils

logger = log.MCA_LOGGER

# Name pattern for generated slide UV sets.
SLIDE_UV_SET_NAME = 'uvslide_{side}_{region}'
# Flag translate channel -> (child of the raw translate, child of the clamp output, clamp min/max suffix, pin coord).
SLIDE_CHANNELS = (('ty', 'translateY', 'outputG', 'G', 'U'),
                  ('tz', 'translateZ', 'outputB', 'B', 'V'))
# "No limit" range used on the clamp node when a channel has no limits.
UNLIMITED = (-1e6, 1e6)


class UVSlideComponent(keyable_component.KeyableComponent):
    """
    Keyable component that pins one joint to a mesh surface with a flag that slides it across the mesh.

    On top of the KeyableComponent groups it creates a ``<side>_<region>_uvpin_rest_grp`` under the flag group
    (carrying the flag), a ``<side>_<region>_uvpin_grp`` / ``_uvpin_pivot`` pair under the noTouch group
    (carrying the pin joint), two uvPin nodes and the clamp / mult / add slide network. Message attributes
    ``pinJoint``, ``pinNode``, ``restPinNode`` and ``slideNodes`` link those nodes back to the component and
    the build arguments are serialized into the ``buildKwargs`` compound attribute.
    """

    VERSION = 2

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent,
               bind_joint,
               pin_mesh,
               side,
               region,
               scale=1.0,
               uv=None,
               uv_set=None,
               create_uv_set=False,
               uv_set_radius=0.0,
               lock_normal_translate=True,
               lock_rotate_axes=attr_utils.ROTATION_ATTRS,
               lock_scale_axes=attr_utils.SCALE_ATTRS,
               slide_limits=True,
               slide_limit_u=None,
               slide_limit_v=None,
               **kwargs):
        """
        Creates a UV slide component: one flag pinned to a mesh surface whose translate slides a joint across the mesh.

        :param FRAGNode frag_parent: FRAG Rig FRAGNode.
        :param pm.nt.Joint bind_joint: The skeleton joint this component drives.
        :param pm.nt.Transform pin_mesh: The shaped transform of the mesh the joint is pinned to. Must have UVs.
        :param str side: The side in which the component is on the body.
        :param str region: The name of the region. EX: "arm"
        :param float scale: Scale value for the created flag.
        :param list[float] uv: Optional U, V coordinate to pin at (in the pin's UV set). Defaults to the closest
            point on the mesh to the bind joint.
        :param str uv_set: UV set on the pin mesh to slide in. Defaults to the mesh's current set. Ignored
            when create_uv_set is True unless given, in which case it names the generated set.
        :param bool create_uv_set: Generate a dedicated slide UV set (planar projection of the connected, non
            overlapping faces facing the attachment point) named uv_set or 'uvslide_<side>_<region>'. Rebuilt on
            every create. Render UV sets are untouched.
        :param float uv_set_radius: Optional world distance cap from the attachment for faces included in a
            generated set. 0 means no cap.
        :param bool lock_normal_translate: Lock the flag's translateX (the surface normal) so it only slides.
        :param list[str] lock_rotate_axes: Rotation channels to lock on the flag. All of them by default.
        :param list[str] lock_scale_axes: Scale channels to lock on the flag.
        :param bool slide_limits: Limit the slide channels (transform limits + clamp) to a rectangle inside the
            UV shell so the pin never snaps to the origin past the shell edge.
        :param tuple(float, float) slide_limit_u: Optional (min, max) cap on translateY (the U slide) in flag
            units (about world units). Intersected with the shell limits.
        :param tuple(float, float) slide_limit_v: Optional (min, max) cap on translateZ (the V slide).
        :param dict kwargs: Unused extra build arguments accepted so templates can pass a shared kwargs dict.
        :return: Returns an instance of UVSlideComponent.
        :rtype: UVSlideComponent
        """

        bind_joint = pm.PyNode(bind_joint)
        pin_mesh = pm.PyNode(pin_mesh)
        if not pin_mesh.getShape():
            raise pm.MayaNodeError('UVSlideComponent: pin mesh {0} has no shape.'.format(pin_mesh))

        lock_rotate_axes = list(lock_rotate_axes)
        lock_scale_axes = list(lock_scale_axes)
        slide_limit_u = _clean_limit(slide_limit_u)
        slide_limit_v = _clean_limit(slide_limit_v)

        # Set Namespace
        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set=f'{root_namespace}:')

        node = keyable_component.KeyableComponent.create(frag_parent,
                                                         UVSlideComponent.__name__,
                                                         UVSlideComponent.VERSION,
                                                         side=side,
                                                         region=region,
                                                         align_component=bind_joint)

        flag_grp = node.pynode.flagGroup.get()
        nt_grp = node.pynode.noTouch.get()

        # --- Pin joint -----------------------------------------------------------------
        # The rig owns a duplicate of the bind joint; the skeleton joint just follows it. This keeps the
        # rig self contained and matches how the other components hand animation to the skeleton.
        pin_joint = joint_utils.duplicate_joint(bind_joint, duplicate_name=f'{naming.get_basename(bind_joint)}_pin')
        pin_joint.setParent(nt_grp)
        constraint.parent_constraint_safe(pin_joint, bind_joint)
        joint_position = pin_joint.getTranslation(space='world')

        # --- UV set ------------------------------------------------------------------------
        # Decide which UV set the pins read. The pin coordinate is looked up in that set directly, so the
        # mesh's current (render) set is never touched.
        render_uv_set = pm.polyUVSet(pin_mesh, q=True, currentUVSet=True)
        render_uv_set = render_uv_set[0] if render_uv_set else None
        if create_uv_set:
            uv_set = uv_set or SLIDE_UV_SET_NAME.format(side=side, region=region)
            uvpin_utils.create_planar_uv_set(pin_mesh, uv_set, joint_position,
                                             radius=uv_set_radius if uv_set_radius and uv_set_radius > 0 else None)
        elif uv_set:
            if uv_set not in (pm.polyUVSet(pin_mesh, q=True, allUVSets=True) or []):
                raise pm.MayaNodeError('UVSlideComponent: UV set {0} does not exist on {1}.'.format(uv_set, pin_mesh))
        else:
            uv_set = render_uv_set

        if not uv and uv_set:
            uv = uvpin_utils.get_uv_at_point(pin_mesh, joint_position, uv_set)

        # --- Rest pin group (flag side) ----------------------------------------------------
        # Fixed at the rest UV. Its world matrix is the rest surface frame: X normal, Y along U, Z along V.
        # The flag hangs here, so its translate is a clean move in that frame (stable gizmo).
        rest_grp = pm.group(em=True, w=True, n=f'{side}_{region}_uvpin_rest_grp')
        rest_grp.setParent(flag_grp)
        pm.delete(constraint.parent_constraint_safe(pin_joint, rest_grp))
        rest_pin = _create_pin(pin_mesh, rest_grp, uv, uv_set, f'{side}_{region}_rest')
        base_uv = {'U': rest_pin.coordinate[0].coordinateU.get(), 'V': rest_pin.coordinate[0].coordinateV.get()}

        # --- Slide pin group (joint side) --------------------------------------------------
        # Same start coordinate, but its U / V are driven by the flag below. The pin joint follows this frame.
        slide_grp = pm.group(em=True, w=True, n=f'{side}_{region}_uvpin_grp')
        slide_grp.setParent(nt_grp)
        pm.delete(constraint.parent_constraint_safe(pin_joint, slide_grp))
        slide_pin = _create_pin(pin_mesh, slide_grp, [base_uv['U'], base_uv['V']], uv_set, f'{side}_{region}')

        # --- Flag ------------------------------------------------------------------------
        # Build the flag at the joint position but oriented to the rest frame, so Y/Z translate is "along the
        # surface". A throwaway frame transform gives Flag.create something to match.
        frame_grp = pm.group(em=True, w=True, n=f'{side}_{region}_uvpin_frame')
        frame_grp.setParent(rest_grp)
        frame_grp.rotate.set(0, 0, 0)
        frame_grp.setTranslation(joint_position, space='world')

        pin_flag = frag_flag.Flag.create(frame_grp,
                                         label=naming.get_basename(bind_joint),
                                         scale=scale,
                                         add_align_transform=True,
                                         meta_connect=False)
        attr_utils.connect_nodes_with_message_attrs(pin_flag.node, 'driven_transform', pin_joint, 'driver_flag')
        flag_align_transform = pin_flag.get_align_transform()
        flag_align_transform.setParent(rest_grp)
        pm.delete(frame_grp)

        # --- Joint pivot -------------------------------------------------------------------
        # A transform under the slide frame at the joint's offset from the surface. The pin joint follows it
        # (maintaining its offset), and the flag's rotate is copied onto it so an unlocked rotation turns the
        # joint about its own position in the slide surface frame.
        pivot_grp = pm.group(em=True, w=True, n=f'{side}_{region}_uvpin_pivot')
        pivot_grp.setParent(slide_grp)
        pivot_grp.rotate.set(0, 0, 0)
        pivot_grp.setTranslation(joint_position, space='world')
        pin_flag.node.rotateOrder >> pivot_grp.rotateOrder
        pin_flag.node.rotate >> pivot_grp.rotate
        pm.parentConstraint(pivot_grp, pin_joint, w=1, mo=True)

        # --- Slide source ------------------------------------------------------------------
        # Transform limits stop the manipulator but leave the channel value unclamped, so the UV drive reads the
        # flag translate through a clamp node that carries the same limits. Typed values past the limit then
        # still keep the pin on the shell.
        slide_nodes = []
        use_clamp = slide_limits or slide_limit_u or slide_limit_v
        slide_source = pin_flag.node.translate
        clamp_node = None
        if use_clamp:
            clamp_node = pm.createNode(pm.nt.Clamp, n=f'{side}_{region}_slide_clamp')
            clamp_node.min.set(UNLIMITED[0], UNLIMITED[0], UNLIMITED[0])
            clamp_node.max.set(UNLIMITED[1], UNLIMITED[1], UNLIMITED[1])
            pin_flag.node.translate >> clamp_node.input
            slide_source = clamp_node.output
            slide_nodes.append(clamp_node)

        # --- Translate -> UV -------------------------------------------------------------
        # Sample the mesh while the slide pin coordinates are still free: UV density for the slide ratio, and
        # a rectangle inside the UV shell for the limits. Off the shell a uvPin snaps to the origin, so the
        # limits stop the flag before that happens.
        u_per_unit, v_per_unit = uvpin_utils.measure_uv_per_unit(slide_pin)
        uv_per_unit = {'U': u_per_unit, 'V': v_per_unit}
        shell_rect = {}
        if slide_limits:
            shell_rect = uvpin_utils.get_uv_shell_rect(slide_pin)
        user_limits = {'U': slide_limit_u, 'V': slide_limit_v}
        applied_limits = {}

        for channel, raw_child, clamped_child, clamp_suffix, coord_name in SLIDE_CHANNELS:
            source_attr = slide_source.attr(clamped_child if clamp_node else raw_child)

            mult_node = pm.createNode(pm.nt.MultDoubleLinear, n=f'{side}_{region}_slide{coord_name}_mult')
            add_node = pm.createNode(pm.nt.AddDoubleLinear, n=f'{side}_{region}_slide{coord_name}_add')
            source_attr >> mult_node.input1
            mult_node.input2.set(uv_per_unit[coord_name])
            mult_node.output >> add_node.input1
            add_node.input2.set(base_uv[coord_name])
            add_node.output >> slide_pin.coordinate[0].attr(f'coordinate{coord_name}')
            slide_nodes += [mult_node, add_node]

            limit_min, limit_max = UNLIMITED
            if slide_limits:
                # Convert the shell rectangle into translate limits. The sign of uv_per_unit decides which is min.
                low_uv, high_uv = shell_rect[coord_name]
                limit_a = (low_uv - base_uv[coord_name]) / uv_per_unit[coord_name]
                limit_b = (high_uv - base_uv[coord_name]) / uv_per_unit[coord_name]
                limit_min, limit_max = min(limit_a, limit_b), max(limit_a, limit_b)
            if user_limits[coord_name]:
                # Template caps only ever tighten the shell limits.
                limit_min = max(limit_min, user_limits[coord_name][0])
                limit_max = min(limit_max, user_limits[coord_name][1])
            if limit_max < limit_min:
                limit_min = limit_max = 0.0
            if (limit_min, limit_max) != UNLIMITED:
                clamp_node.attr(f'min{clamp_suffix}').set(limit_min)
                clamp_node.attr(f'max{clamp_suffix}').set(limit_max)
                pm.transformLimits(pin_flag.node, **{channel: (limit_min, limit_max), f'e{channel}': (True, True)})
                applied_limits[coord_name] = (limit_min, limit_max)
                logger.debug('UVSlideComponent {0}_{1}: {2} limits {3:.2f}..{4:.2f} ({5})'.format(
                    side, region, channel, limit_min, limit_max, coord_name))

        # --- Lock flag channels ----------------------------------------------------------
        locked_attrs = ['v'] + lock_rotate_axes + lock_scale_axes
        if lock_normal_translate:
            locked_attrs.append('tx')
        attr_utils.lock_and_hide_attrs(pin_flag, locked_attrs)

        # --- Meta connections ------------------------------------------------------------
        # Single links use connect_node so the attrs read back as one node, not a list.
        node.connect_nodes(pin_flag, 'flags', 'fragParent')
        node.connect_node(pin_joint, 'pinJoint', 'fragParent')
        node.connect_nodes(bind_joint, 'bindJoints')
        node.connect_node(slide_pin, 'pinNode', 'fragParent')
        node.connect_node(rest_pin, 'restPinNode', 'fragParent')
        node.connect_nodes(slide_nodes, 'slideNodes', 'fragParent')

        # Serialize build kwargs last so the measured base UV is stored; a rebuild lands on the same spot
        # even if the joint has been moved. pin_mesh is stored as a message link so renames survive.
        kwargs_dict = {}
        kwargs_dict['pin_mesh'] = pin_mesh
        kwargs_dict['scale'] = scale
        kwargs_dict['uv'] = [base_uv['U'], base_uv['V']]
        kwargs_dict['uv_set'] = uv_set or ''
        kwargs_dict['create_uv_set'] = create_uv_set
        kwargs_dict['uv_set_radius'] = float(uv_set_radius or 0.0)
        kwargs_dict['lock_normal_translate'] = lock_normal_translate
        kwargs_dict['lock_rotate_axes'] = lock_rotate_axes
        kwargs_dict['lock_scale_axes'] = lock_scale_axes
        kwargs_dict['slide_limits'] = slide_limits
        kwargs_dict['slide_limit_u'] = list(slide_limit_u) if slide_limit_u else []
        kwargs_dict['slide_limit_v'] = list(slide_limit_v) if slide_limit_v else []
        attr_utils.set_compound_attribute_groups(node.pynode, 'buildKwargs', kwargs_dict)

        logger.info('UVSlideComponent {0}_{1}: pinned {2} to {3} (set {4}) at UV ({5:.3f}, {6:.3f}), '
                    'U/unit {7:.4f}, V/unit {8:.4f}, limits {9}.'.format(side, region, bind_joint, pin_mesh, uv_set,
                                                                        base_uv['U'], base_uv['V'], u_per_unit,
                                                                        v_per_unit, applied_limits))
        return node

    # quick access properties
    @property
    def pin_flag(self):
        """
        Returns the component's single flag.

        :return: The surface flag.
        :rtype: frag_flag.Flag
        """

        flags = self.get_flags()
        return flags[0] if flags else None

    @property
    def pin_node(self):
        """
        Returns the slide uvPin node that carries the pin joint.

        :return: The uvPin node.
        :rtype: pm.nt.UvPin
        """

        return lists.get_first_in_list(self.pynode.pinNode.listConnections())

    @property
    def rest_pin_node(self):
        """
        Returns the rest uvPin node that carries the flag (VERSION 2 rigs only).

        :return: The uvPin node, or None on a VERSION 1 component.
        :rtype: pm.nt.UvPin or None
        """

        if self.pynode.hasAttr('restPinNode'):
            return lists.get_first_in_list(self.pynode.restPinNode.listConnections())
        return None

    @property
    def pin_joint(self):
        """
        Returns the rig side joint that drives the bind joint.

        :return: The pin joint.
        :rtype: pm.nt.Joint
        """

        return lists.get_first_in_list(self.pynode.pinJoint.listConnections())

    @property
    def pin_mesh(self):
        """
        Returns the mesh the component is pinned to.

        :return: The pin mesh transform.
        :rtype: pm.nt.Transform
        """

        if self.pynode.hasAttr('buildKwargs_pin_mesh'):
            return self.pynode.buildKwargs_pin_mesh.get()
        return None

    @property
    def uv_set(self):
        """
        Returns the UV set the pin slides in.

        :return: UV set name.
        :rtype: str
        """

        pin_node = self.pin_node
        return pin_node.uvSetName.get() if pin_node else ''

    def get_uv(self):
        """
        Returns the slide pin's current UV coordinate, including any flag slide.

        :return: U, V.
        :rtype: list[float]
        """

        pin_node = self.pin_node
        return [pin_node.coordinate[0].coordinateU.get(), pin_node.coordinate[0].coordinateV.get()]

    def get_slide_limits(self):
        """
        Returns the translate limits on the flag's slide channels.

        :return: {'ty': (min, max), 'tz': (min, max)}; a channel without limits is absent.
        :rtype: dict[str, tuple(float, float)]
        """

        pin_flag = self.pin_flag
        limits = {}
        if not pin_flag:
            return limits
        for channel, _, _, _, _ in SLIDE_CHANNELS:
            if pm.transformLimits(pin_flag.node, q=True, **{f'e{channel}': True}) == [True, True]:
                limits[channel] = tuple(pm.transformLimits(pin_flag.node, q=True, **{channel: True}))
        return limits

    def get_flags(self):
        """
        Returns all the flags connected to the component.

        :return: Returns all the flags connected to the component.
        :rtype: list(frag_flag.Flag)
        """

        flags = self.pynode.flags.listConnections()
        flags = [frag_flag.Flag(x) for x in flags]
        return flags

    def select_flags(self):
        """
        Selected all the flags.
        """

        pm.select(self.get_flags())

    def key_flags(self):
        """
        Sets a keyframe on all the flags in the scene
        """

        flags = self.get_flags()
        pm.setKeyframe(flags)

    def to_default_pose(self):
        """
        Sets all the flags to there default position.
        """

        flags = self.get_flags()
        for _flag in flags:
            attr_utils.reset_attrs(_flag)

    def remove(self):
        """
        Remove this component, its build groups, both uvPins and the slide utility nodes.

        The base removal only deletes the build groups; the pins and slide nodes live outside them and would
        otherwise keep evaluating against the mesh. A generated UV set is left on the mesh (harmless, and a
        rebuild replaces it).
        """

        nodes_to_delete = []
        for attr_name in ('pinNode', 'restPinNode', 'slideNodes'):
            if self.pynode.hasAttr(attr_name):
                nodes_to_delete += [x for x in self.pynode.attr(attr_name).listConnections() if x]
        if nodes_to_delete:
            pm.delete(nodes_to_delete)
        super().remove()

    def attach_to_skeleton(self, attach_skeleton_root, mo=True):
        """
        Drive the component with a given skeleton.

        The flag follows the matching skeleton joint's rotation on any unlocked rotate channel. Translation is
        skipped on purpose: the flag's translate channels are UV slide inputs, not a world position, so a
        skeleton cannot drive them directly. With all rotation locked (the default) nothing is constrained.

        :param Joint attach_skeleton_root: Top level joint of the hierarchy to drive the component.
        :param bool mo: If object offsets should be maintained.
        :return: A list of all created constraints.
        :rtype: list[Constraint]
        """

        target_root_hierarchy = chain_markup.ChainMarkup(attach_skeleton_root)
        constraint_list = []

        pin_flag = self.pin_flag
        bind_joint_list = self.bind_joints

        skel_region = None
        skel_side = None
        if bind_joint_list:
            wrapped_node = chain_markup.JointMarkup(bind_joint_list[0])
            skel_region = wrapped_node.region
            skel_side = wrapped_node.side

        skel_region = skel_region or self.region
        skel_side = skel_side or self.side

        # Prefer a name match: pin joints often share one markup region per side (arm and leg pins both
        # 'uvpin'), and ChainMarkup keeps only one start per region, so the markup lookup can pick the wrong pin.
        skel_joint = None
        if bind_joint_list:
            bind_name = naming.get_basename(bind_joint_list[0])
            skeleton_joints = pm.listRelatives(attach_skeleton_root, ad=True, type=pm.nt.Joint) + [attach_skeleton_root]
            skel_joint = lists.get_first_in_list([x for x in skeleton_joints if naming.get_basename(x) == bind_name])
        if not skel_joint:
            skel_joint = target_root_hierarchy.get_start(skel_region, skel_side)
        if skel_joint and pin_flag:
            constraint_node = constraint.parent_constraint_safe(skel_joint, pin_flag,
                                                                skip_translate_attrs=['x', 'y', 'z'], mo=mo)
            if constraint_node:
                constraint_list.append(constraint_node)
        return constraint_list


def _create_pin(pin_mesh, driven_grp, uv, uv_set, name):
    """
    Creates a uvPin on a mesh with the frame layout the component relies on.

    :param pm.nt.Transform pin_mesh: Mesh to read.
    :param pm.nt.Transform driven_grp: Transform whose offsetParentMatrix the pin drives.
    :param list[float] uv: U, V to pin at.
    :param str uv_set: UV set the pin reads. Always set explicitly: a pin on a missing set evaluates garbage.
    :param str name: Pin name prefix.
    :return: The pin node.
    :rtype: pm.nt.UvPin
    """

    pin_node = rivets.create_uv_pin(pin_mesh, driven_grp, uv=list(uv) if uv else None, name=name)
    if not pin_node:
        raise pm.MayaNodeError('UVSlideComponent: failed to create a uvPin on {0}.'.format(pin_mesh))
    if uv_set:
        pin_node.uvSetName.set(uv_set)
    # Pin the frame layout down: X is the surface normal, Y the U tangent, Z the V tangent. The slide
    # mapping and the density measurement both rely on this.
    pin_node.normalAxis.set(uvpin_utils.PIN_NORMAL_ROW)
    pin_node.tangentAxis.set(uvpin_utils.PIN_U_ROW)
    return pin_node


def _clean_limit(limit):
    """
    Normalizes a user slide limit into an ordered (min, max) tuple or None.

    :param tuple(float, float) limit: Raw limit; empty / None means no cap.
    :return: (min, max) or None.
    :rtype: tuple(float, float) or None
    """

    if not limit or len(limit) != 2:
        return None
    low, high = float(limit[0]), float(limit[1])
    return (min(low, high), max(low, high))
