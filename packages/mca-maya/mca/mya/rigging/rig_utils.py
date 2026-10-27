"""
Rig level utilities for FRAG rigs: baking, attaching, reanimating, switching, mirroring, and importing.

Covers the animator facing rig commands (the ``*_cmd`` functions operate on the current selection and are wired to
menus) and the functions behind them: baking rig animation down to a duplicate skeleton, attaching a rig to an
animated skeleton and baking the flags, attaching/detaching two rigs, overdrivers, IK/FK switching, animation
mirroring, asset import via the asset registry, twist component setup, flag shape export, and dead FRAG node cleanup.
Also holds a few small node helpers (align transforms, live NURBS lines, locators, primary axis lookup).

Requires: pymel, maya.cmds, the MCA asset registry (an AssetManager is created at import).
Side effects: most functions create and delete nodes, namespaces, constraints, and keyframes in the current scene.
"""

import os
import re

import maya.cmds as cmds
import pymel.core as pm

from mca.common import log
from mca.common.assetlist import asset_manager
from mca.common.utils import lists, strings, pymaths
from mca.common.paths import paths, project_paths
from mca.common.pyqt import messages
from mca.mya.animation import anim_curves, baking, time_utils
from mca.mya.deformations import cluster
from mca.mya.modifiers import ma_decorators
from mca.mya.pyqt import dialogs
from mca.mya.rigging import frag, chain_markup, skel_utils, joint_utils, ik_utils
from mca.mya.rigging.flags import frag_flag, flag_utils
from mca.mya.utils import groups, naming, constraint, dag, material_utils, namespace, attr_utils, fbx_utils

logger = log.MCA_LOGGER
# The asset registry is loaded once at import and shared by every asset lookup in this module.
_ASSET_MANAGER = asset_manager.get_asset_manager()


def create_align_transform(obj, orient_obj=None):
    """
    Creates a transform at the given object's location then parents the object to that transform to effectively
    "zero out" all transformation attributes. If a align transform already exists for the object then return it.

    Marks align transform itself with a alignObject attribute, then creates a alignTransform attribute on the given
    object and hooks align transform's alignObject attribute into it for tracking purposes.

    :param pm.nt.Transform obj: Transform to create align group node.
    :param Transform orient_obj: Override rotation alignment object.
    :return: Newly created or existing align transform.
    :rtype: nt.Transform
    """

    transform = groups.create_aligned_parent_group(obj,
                                                   suffix='align_transform',
                                                   attr_name='alignTransform',
                                                   obj_attr='alignObject',
                                                   orient_obj=orient_obj)
    return transform


def create_line_between(obj_a, obj_b, name=None):
    """
    Creates a referenced NURBs line that traces between two objects. This is a live setup.

    :param str or nt.Transform obj_a: Start of the line
    :param str or nt.Transform obj_b: End of the line
    :param str name: Optional name for the curve and its clusters; defaults to the curve's generated name.
    :return: Transform of created curve which draws the line
    :rtype: pm.nt.Transform
    """

    pos1 = obj_a.getTranslation(space='world')
    pos2 = obj_b.getTranslation(space='world')
    # Linear curve
    line = pm.curve(d=1, p=[pos1, pos2], k=[0, 1])
    node_name = name or naming.get_basename(line)
    _, obj_a_cluster = cluster.create_cluster_from_component_names(line.cv[0], f'{node_name}_a')
    _, obj_b_cluster = cluster.create_cluster_from_component_names(line.cv[1], f'{node_name}_b')
    pm.parent([obj_a_cluster, obj_b_cluster], line)
    line.inheritsTransform.set(0)
    obj_a_cluster.inheritsTransform.set(0)
    obj_b_cluster.inheritsTransform.set(0)
    obj_a_cluster.hide()
    obj_b_cluster.hide()
    pm.pointConstraint(obj_a, obj_a_cluster, w=1, mo=1)
    pm.pointConstraint(obj_b, obj_b_cluster, w=1, mo=1)
    line_shape = pm.PyNode(line).getShape()
    line_shape.overrideEnabled.set(1)
    line_shape.overrideDisplayType.set(1)  # 1 = template, so the line cannot be selected in the viewport.
    line_shape.overrideColor.set(3)  # Maya colour index 3 = gray.
    # gets around double namespaces.
    line.rename(node_name)
    line.getShape().rename(f'{node_name}Shape')
    return line


def get_asset_skeleton(asset_id):
    """
    From an asset id return the .skel associated with it.

    :param str asset_id: AssetId lookup for a given asset.
    :return: Full path to a given skel file.
    :rtype: str
    """

    mca_asset = _ASSET_MANAGER.get_record(asset_id)

    if not mca_asset:
        # failed to find asset registered
        logger.warning(f'Looks like the asset has not been registered in the asset list '
                       f'or the infomation is incorrect: {asset_id}')
        return

    return mca_asset.skel_path


@ma_decorators.keep_namespace_decorator
@ma_decorators.keep_current_frame_decorator
@ma_decorators.undo_decorator
def bake_skeleton_from_rig(frag_rig, start_frame=None, end_frame=None, set_to_zero=True):
    """
    From a selected rig, duplicate and attach the skeleton, before baking rig animation to it.

    :param FRAGRig frag_rig: The frag rig we're going to duplicate the skeleton from.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    :param bool set_to_zero: If the animation should start at frame 0 after bake.
    :return: Root joint of the duplicate hierarchy.
    :rtype: Joint
    """

    # retrieve a valid frame range.
    if any(x is None for x in [start_frame, end_frame]):
        start_frame, end_frame = time_utils.get_keyframe_range_from_nodes(frag_rig.get_flags())

    frag_root = frag.get_frag_root(frag_rig)

    if any(x is None for x in [start_frame, end_frame]):
        # unable to retrieve a valid framerange.
        logger.warning(f'No keyframes found on: {frag_root.pynode.getAttr("assetName")}')
        return

    asset_id = frag_root.pynode.assetID.get()
    skel_path = get_asset_skeleton(asset_id)
    if not os.path.exists(skel_path):
        # skel path is missing file.
        logger.warning(f'Sync {skel_path}, missing .skl file aborting bake.')
        return
    root_joint = skel_utils.import_skeleton(skel_path)

    # duplicate and attach our skels.
    skel_root = frag_root.pynode.getAttr('rootJoint')

    current_scale = frag_rig.rig_scale
    if current_scale != 1.0:
        frag_rig.rig_scale = 1.0

    custom_attr_list = list(set(attach_skeletons_by_name(skel_root, root_joint)))

    bake_hierarchy = chain_markup.ChainMarkup(root_joint)
    baking.bake_objects(bake_hierarchy._animationJoints, bake_range=[start_frame, end_frame],
                        custom_attrs=custom_attr_list)

    # Strip the constraints (and anything else non joint) that attaching left under the duplicate skeleton.
    pm.delete([x for x in pm.listRelatives(root_joint, ad=True, type=pm.nt.Transform)
               if not isinstance(x, pm.nt.Joint)])

    # shift keys if it was requested.
    if set_to_zero and start_frame != 0:
        anim_curves.change_curve_start_time(bake_hierarchy._animationJoints, 0 - start_frame)

    if current_scale != 1.0:
        frag_rig.rig_scale = current_scale

    return bake_hierarchy.root


def attach_skeletons_by_name(driver_skel, target_skel):
    """
    Attach two skeletons via naming dictionaries.

    :param Joint driver_skel: The skeleton root of the hierarchy which will drive the pair of attached skeletons.
    :param Joint target_skel: The skeleton root of the hierarchy which will follow the driver.
    :return: A list of all the custom attributes that were bound in this process.
    :rtype: list(str)
    """
    source_skeleton_dict = joint_utils.create_skeleton_dict(driver_skel)
    bake_hierarchy = chain_markup.ChainMarkup(target_skel)
    target_skeleton_dict = bake_hierarchy.skeleton_dict
    custom_attr_list = []
    for joint_name, joint_node in source_skeleton_dict.items():
        if joint_name in target_skeleton_dict:
            target_joint = target_skeleton_dict.get(joint_name, None)
            if target_joint not in bake_hierarchy._animationJoints:
                continue
            if target_joint:
                constraint.parent_constraint_safe(joint_node, target_joint)
                constraint.scale_constraint_safe(joint_node, target_joint)
                for attr in target_joint.listAttr(ud=True, k=True, se=True):
                    if attr.type() not in ['string', 'message', 'bool']:
                        attr_name = attr.attrName()
                        if joint_node.hasAttr(attr_name):
                            attr.disconnect()
                            joint_node.attr(attr_name) >> attr
                            custom_attr_list.append(attr_name)
    return custom_attr_list


@ma_decorators.keep_selection_decorator
def bake_skeleton_from_rig_cmd(start_frame=None, end_frame=None, set_to_zero=True):
    """
    From a selected rig, duplicate and attach the skeleton, before baking rig animation to it.

    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    :param bool set_to_zero: If the animation should start at frame 0 after bake.
    :return: Root joint of the baked duplicate hierarchy, or None if no rig or keyframes were found.
    :rtype: pm.nt.Joint or None
    """

    selection = pm.selected()
    frag_root = None
    frag_rig = None
    for selected_node in selection:
        # find us a valid frag_rig
        frag_rig = frag.get_frag_rig(selected_node)
        if frag_rig:
            frag_root = frag_rig.get_root()
            break

    if not frag_root:
        logger.warning(f'Unable to locate a FRAGRig from selection: {selection}')
        return

    # retrieve a valid frame range.
    if any(x is None for x in [start_frame, end_frame]):
        start_frame, end_frame = time_utils.get_keyframe_range_from_nodes(frag_rig.get_flags())

    if any(x is None for x in [start_frame, end_frame]):
        # unable to retrieve a valid framerange.
        logger.warning(f'No keyframes found on: {frag_root.pynode.getAttr("assetName")}')
        return

    bake_root = bake_skeleton_from_rig(frag_rig, start_frame, end_frame, set_to_zero)
    return bake_root


@ma_decorators.keep_selection_decorator
@ma_decorators.undo_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
def attach_rigs_cmd():
    """
    Given a selection of two rigs, match up their components by side and region then constrain their flags.

    :return: The asset id of the last FRAGRig found in the selection, or None if the selection was not valid.
    :rtype: str or None
    """

    selection = pm.selected()

    if not selection or len(selection) < 2:
        dialogs.info_prompt(title='No Selections', text='Please select exactly two separate FRAG rigs')
        return

    frag_rig = None
    asset_id = ''
    rig_list = []
    for selected_node in selection:
        frag_rig = frag.get_frag_rig(selected_node)
        if not frag_rig and frag_flag.is_flag_node(selected_node):
            wrapped_node = frag_flag.Flag(selected_node)
            rig_component = frag.FRAGNode(wrapped_node.getAttr('fragParent'))
            frag_rig = rig_component.get_frag_parent()
        rig_list.append(frag_rig)

    if not rig_list or rig_list[0] == rig_list[-1]:
        dialogs.info_prompt(title='No Selections', text='Please select exactly two separate FRAG rigs')
        return
    head_rig = [x for x in rig_list if frag.get_frag_root(x).pynode.assetType.get() == 'head']
    if head_rig:
        driven_rig = head_rig[0]
        driver_rig = [x for x in rig_list if x != driven_rig][0]
    else:
        driver_rig, driven_rig = rig_list
    attach_rigs(driver_rig, driven_rig)
    if frag_rig:
        asset_id = frag_rig.get_asset_id(frag_rig)
    return asset_id


@ma_decorators.undo_decorator
def attach_rigs(driver_rig, driven_rig):
    """
    From the two given rigs, match up their components by side and region then constrain their flags.

    :param FRAGRig driver_rig: The FRAGRig that will drive the pair of rigs.
    :param FRAGRig driven_rig: The FRAGRIG that will be puppeted by the driver rig.
    """
    if driven_rig.pynode.hasAttr('attached_to') and driven_rig.pynode.getAttr('attached_to'):
        logger.warning(f'{driven_rig.pynode.getAttr("rigTemplate")} already has a driver rig.')
        return

    driver_rig_dict = {}
    for rig_component in driver_rig.get_frag_children():
        if isinstance(rig_component, frag.MultiConstraint):
            continue
        rig_side = rig_component.side
        rig_region = rig_component.region
        if rig_side and rig_region:
            if rig_side not in driver_rig_dict:
                driver_rig_dict[rig_side] = {}
            driver_rig_dict[rig_side][rig_region] = rig_component

    for rig_component in driven_rig.get_frag_children():
        rig_side = rig_component.side
        rig_region = rig_component.region
        driver_component = driver_rig_dict.get(rig_side, {}).get(rig_region, None)
        if driver_component:
            logger.info(f'found {driver_component}')
            try:
                driver_flags = driver_component.get_flags()
                driven_flags = rig_component.get_flags()

                # When the flag counts differ the zip pairing is unreliable, so fall back to matching by name.
                do_name_check = len(driver_flags) != len(driven_flags)
                for driver_node, driven_node in zip(driver_flags, driven_flags):
                    driver_flag_name, driven_flag_name = [naming.get_basename(x) for x in [driver_node, driven_node]]
                    driver_node_namespace = naming.get_node_name_parts(pm.PyNode(driver_node))[1]

                    if driver_flag_name != driven_flag_name and do_name_check:
                        driver_flag_names = [naming.get_basename(x) for x in driver_flags]
                        driver_node = next((x for x in driver_flag_names if x == driven_flag_name))
                        if driver_node_namespace:
                            driver_node = f'{driver_node_namespace}:{driver_node}'

                    constraint.parent_constraint_safe(driver_node, driven_node)
                    driven_node.getParent().v.set(False)
            except Exception as exc:
                # One component failing to pair up (no name match, missing namespace) should not stop the rest.
                logger.debug(f'Failed to attach {rig_component}: {exc}')

    if not driven_rig.pynode.hasAttr('attached_to'):
        driven_rig.pynode.addAttr('attached_to', at='message')
    driver_rig.pynode.message >> driven_rig.pynode.attached_to


@ma_decorators.keep_selection_decorator
@ma_decorators.undo_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
def detach_rig_cmd(bake_animation=False, start_frame=None, end_frame=None):
    """
    Wrapped fnc for the detach_rig fnc.

    :param bool bake_animation: If the animation should be baked down to the attached rig.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    :return: The asset id of the detached rig, or None if no rig was selected.
    :rtype: str or None
    """

    selection = pm.selected()
    if not selection:
        dialogs.info_prompt(title='Select a rig', text='Please select a FRAG rig')
        return

    selected_node = lists.get_first_in_list(selection)
    frag_rig = frag.get_frag_rig(selected_node)
    if not frag_rig and frag_flag.is_flag_node(selected_node):
        wrapped_node = frag_flag.Flag(selected_node)
        rig_component = frag.FRAGNode(wrapped_node.getAttr('fragParent'))
        frag_rig = rig_component.get_frag_parent()

    if not frag_rig:
        dialogs.info_prompt(title='Select a rig', text='Please select a FRAG rig')
        return

    detach_rig(frag_rig, bake_animation, start_frame, end_frame)
    asset_id = frag_rig.get_asset_id(frag_rig)
    return asset_id


@ma_decorators.undo_decorator
def detach_rig(driven_rig, bake_animation, start_frame=None, end_frame=None):
    """
    Remove the connection between the driver and driven rigs. Optionally bake down the animation.

    :param FRAGRig driven_rig: The rig currently being driven through its 'attached_to' connection.
    :param bool bake_animation: If the animation should be baked down to the attached rig.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    attached_flags = []
    custom_attr_list = []
    constraint_list = []
    if driven_rig.pynode.hasAttr('attached_to') and driven_rig.pynode.getAttr('attached_to'):
        driver_rig = frag.FRAGNode(driven_rig.pynode.getAttr('attached_to'))
        for flag_node in driven_rig.get_flags():
            if not flag_node.hasAttr('overdriven_by') or not flag_node.getAttr('overdriven_by'):
                attached_flags.append(flag_node)
                constraint_list += flag_node.getChildren(type=pm.nt.Constraint)
                flag_group = flag_node.getParent()
                flag_group.setAttr('v', True)
                for attr in flag_node.listAttr(ud=True, k=True, se=True):
                    attr_name = attr.attrName()
                    if 'blendParent' not in attr_name:
                        custom_attr_list.append(attr_name)
    else:
        logger.warning(f'{driven_rig.pynode.getAttr("rigTemplate")} is not attached to another rig.')
        return

    if not constraint_list:
        return

    if attached_flags and bake_animation:
        if not start_frame or not end_frame:
            frame_range = time_utils.get_times(driver_rig.get_flags())
            start_frame = start_frame or frame_range[0]
            end_frame = end_frame or frame_range[1]
        baking.bake_objects(attached_flags, custom_attrs=list(set(custom_attr_list)),
                            bake_range=[start_frame, end_frame])

    pm.delete(constraint_list)
    driven_rig.pynode.disconnectAttr('attached_to')


@ma_decorators.keep_selection_decorator
@ma_decorators.undo_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
def create_overdriver_cmd(skip_rotate_attrs=None, skip_translate_attrs=None, point_orient=False):
    """
    Constrain a flag to a given driver object, or create and align a temporary driver object.

    The first selected node drives the last. Selecting a single flag creates a locator overdriver aligned to it.

    :param list[str] skip_rotate_attrs: Rotate attributes to leave unconstrained.
    :param list[str] skip_translate_attrs: Translate attributes to leave unconstrained.
    :param bool point_orient: If True use separate point and orient constraints instead of a parent constraint.
    :return: The asset id of the overdriven flag's rig, an empty string when the driven node was not a lone flag,
        or None if nothing was selected.
    :rtype: str or None
    """

    selection = pm.selected()

    if not selection:
        return

    skip_rotate_attrs = skip_rotate_attrs or []
    skip_translate_attrs = skip_translate_attrs or []

    driver_object = selection[0]
    driven_object = selection[-1]

    flag = None
    if driver_object == driven_object and frag_flag.is_flag_node(driven_object):
        driver_object = pm.spaceLocator(n=f'{naming.get_basename(driven_object)}_overdriver')
        pm.delete(pm.parentConstraint(driven_object, driver_object))
        flag = driven_object

    driven_keyframes = pm.keyframe(driven_object, q=True)
    driver_keyframes = pm.keyframe(driver_object, q=True)
    if driven_keyframes and not driver_keyframes:
        temp_constraint = constraint.parent_constraint_safe(driven_object, driver_object, mo=True)
        baking.bake_objects(driver_object, bake_range=[min(driven_keyframes), max(driven_keyframes)])
        pm.delete(temp_constraint)

    if point_orient:
        constraint.point_constraint_safe(source_node=driver_object, driven_node=driven_object,
                                         skip_attrs=skip_translate_attrs, mo=True)
        constraint.orient_constraint_safe(source_node=driver_object, driven_node=driven_object,
                                          skip_attrs=skip_rotate_attrs, mo=True)
    else:
        constraint.parent_constraint_safe(driver_object,
                                            driven_object,
                                            skip_rotate_attrs=skip_rotate_attrs,
                                            skip_translate_attrs=skip_translate_attrs,
                                            mo=True)

    if not driven_object.hasAttr('overdriven_by'):
        driven_object.addAttr('overdriven_by', at='message')
    driver_object.message >> driven_object.overdriven_by

    asset_id = ''
    if flag:
        frag_root = frag.get_frag_root(flag)
        asset_id = frag_root.asset_id
        return asset_id
    return asset_id


@ma_decorators.keep_selection_decorator
@ma_decorators.undo_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
def bake_overdriver_cmd(bake_animation=True, start_frame=None, end_frame=None):
    """
    For any constrained flags, find their parent and bake the keyframe range found.

    :param bool bake_animation: If the overdriver animation should be baked to the flags before the constraints
        are removed.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    selection = pm.selected()

    constraint_list = []
    bakeable_node_list = []
    driver_list = []
    for node in selection:
        if not frag_flag.is_flag_node(node):
            continue
        if node.hasAttr('overdriven_by') and node.getAttr('overdriven_by'):
            overdriver_constraint = lists.get_first_in_list(node.listRelatives(type=pm.nt.Constraint))
            if not overdriver_constraint:
                node.disconnectAttr('overdriven_by')
                logger.debug(f'{naming.get_basename(node)}, was not constrained.')
                continue
            constraint_list.append(overdriver_constraint)
            driver_object = node.getAttr('overdriven_by')
            driver_list.append(driver_object)
            bakeable_node_list.append(node)

    if bake_animation:
        if not start_frame or not end_frame:
            time_range = time_utils.get_times(driver_list)
            start_frame = start_frame or time_range[0]
            end_frame = end_frame or time_range[1]
        baking.bake_objects(bakeable_node_list, bake_range=[start_frame, end_frame])
    pm.delete(constraint_list)


@ma_decorators.keep_selection_decorator
def animate_rig_from_skeleton_cmd(frag_rig,
                                  skel_root,
                                  start_frame=None,
                                  end_frame=None,
                                  append=False,
                                  motion_encode=True,
                                  diff_skel_path=None):
    """
    UI command to attach a rig to a given skeleton, then bake all animation from it.

    :param FRAGNode frag_rig: The Frag Rig node.
    :param pm.nt.Joint skel_root: The root joint of the skeleton. If None an FBX is picked through a file dialog.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    :param bool append: If the animation should be attached at the end of the current animation.
    :param bool motion_encode: If the hierarchy start joint should be matched during append.
    :param str diff_skel_path: Path to a different .skl file when the animation comes from another skeleton.
    :return: The asset id of the reanimated rig, or None if no skeleton was imported.
    :rtype: str or None
    """

    frag_root = frag.get_frag_root(frag_rig)
    asset_type = frag_root.pynode.getAttr('assetType')
    head_rig = asset_type == 'head'
    asset_id = frag_root.pynode.getAttr('assetID')
    imported_anim = False
    if not skel_root:
        skel_root = select_and_import_anim(asset_id)
        if not skel_root:
            return
        imported_anim = True

    if append:
        # do our append logic here.
        motion_encode_grp = None
        align_grp = None

        frame_range = time_utils.get_keyframe_range_from_nodes(frag_rig.get_flags())
        rig_start_frame, start_frame = (0, 0) if None in frame_range else frame_range
        if None not in [rig_start_frame, start_frame]:
            # new bake start time is the end of the current rig animation.
            skeleton_node_list = [skel_root] + pm.listRelatives(skel_root, ad=True, type=pm.nt.Joint)
            skel_start_frame, skel_end_frame = time_utils.get_times(skeleton_node_list)

            shift_length = start_frame - skel_start_frame
            logger.debug(f'Bake starts at {start_frame}, incoming animation will be shifted {shift_length} frames.')
            # new bake end time is the duration of the new animation + the new start time.
            end_frame = start_frame + skel_end_frame - skel_start_frame

            anim_curves.change_curve_start_time(skeleton_node_list, shift_length)

            if motion_encode and None not in frame_range:
                skel_path = get_asset_skeleton(asset_id)

                if skel_path:
                    # Go to the last frame of the current baked animation.
                    # This lets us get the last position of the root of the rig.
                    motion_encode_grp = pm.group(n='motion_encoder', w=True, empty=True)
                    cmds.currentTime(start_frame)
                    skel_root.setParent(motion_encode_grp)

                    align_grp = pm.group(n='align_grp', w=True, empty=True)
                    pm.delete(pm.parentConstraint(skel_root, align_grp))
                    motion_encode_grp.setParent(align_grp)

                    # We're going to align the align_grp to the root of the rig.
                    # This aligns the incomming animation to the end of the existing animation.
                    frag_root = frag_rig.get_frag_parent()
                    rig_skel_root = frag_root.root_joint

                    pm.delete(pm.parentConstraint(rig_skel_root, align_grp))
                else:
                    # we failed to find the skeleton path there is a chance motion encoding will fail.
                    logger.warning('Skel file not found, animation will be appended without encoding.')

    reanimate_body_rig = True
    if head_rig:
        animate_head_rig_from_skel(frag_rig, skel_root, start_frame=start_frame, end_frame=end_frame)
        if frag_rig.pynode.hasAttr('attached_to') and frag_rig.pynode.getAttr('attached_to'):
            reanimate_body_rig = False
    if reanimate_body_rig:
        animate_rig_from_skeleton(frag_rig, skel_root, start_frame=start_frame, end_frame=end_frame,
                                  diff_skel_path=diff_skel_path)
    if append and motion_encode:
        # cleanup our temp nodes when doing motion encoding.
        if motion_encode_grp:
            pm.parent(motion_encode_grp.getChildren(), None)
            pm.delete(align_grp)
    if imported_anim:
        namespace.purge_namespace('temp_anim')

    return asset_id


def select_and_import_anim(asset_id):
    """
    Opens file dialog to an asset's animation folder and returns the imported animation's skeleton root

    :param str asset_id: Asset whose animation folder we want to open
    :return: The imported skel root
    :rtype: pm.nt.Joint
    """
    project_root = project_paths.get_project_path()
    anim_dir = os.path.join(project_root, paths.get_asset_animations_path(asset_id))
    if not os.path.exists(anim_dir):
        anim_dir = project_root
    asset_anim_dir = pm.fileDialog2(fileFilter="FBX Files (*.fbx)", dialogStyle=1, fm=1, dir=anim_dir,
                                    cap='Import Animation')
    if asset_anim_dir:
        if not pm.namespace(exists='temp_anim'):
            pm.namespace(addNamespace='temp_anim')
        anim = fbx_utils.import_fbx(asset_anim_dir[0], import_namespace='temp_anim')
        imported_joint = next((x for x in anim if isinstance(x, pm.nt.Joint)))
        if not imported_joint:
            return None
        imported_root = dag.get_absolute_parent(imported_joint, node_type=pm.nt.Joint, inclusive=True)
        return imported_root


@ma_decorators.keep_namespace_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
@ma_decorators.undo_decorator
def animate_rig_from_skeleton(frag_rig, skel_root, start_frame=None, end_frame=None, diff_skel_path=None):
    """
    Connect a rig to a skeleton then bake animation back to the flags.

    :param FRAGRig frag_rig: The FRAGRig of the rig to attach to the skeleton
    :param Joint skel_root: The animated skeleton we will be transfering animation from.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    :param str diff_skel_path: Path to a different .skl file when the animation comes from another skeleton.
    """

    if not isinstance(skel_root, pm.nt.Joint):
        # we need a valid skeleton to steal animation from
        logger.warning(f'{skel_root} is not a valid joint.')
        return

    if not frag.is_frag_node(frag_rig):
        # not a frag node
        logger.warning(f'{frag_rig} is not a valid FRAGNode.')
        return
    else:
        frag_rig = frag.FRAGNode(frag_rig)
        if isinstance(frag_rig, frag.FRAGRoot):
            # If we have a root instead of a rig, just grab the rig.
            frag_rig = frag_rig.get_rig()

        if not isinstance(frag_rig, frag.FRAGRig):
            # we need the FRAGRig to process from
            logger.warning(f'{frag_rig} is not a valid FRAGRig.')
            return

    if None in [start_frame, end_frame]:
        # get_times only needs the min/max key over the joints, so the root itself is not required in the list.
        found_min, found_max = time_utils.get_times(pm.listRelatives(skel_root, ad=True, type=pm.nt.Joint))
        start_frame = start_frame or found_min
        end_frame = end_frame or found_max

    pm.autoKeyframe(state=False)

    frag_root = frag_rig.get_frag_parent()
    asset_id = frag_root.pynode.getAttr('assetID')
    if not diff_skel_path:
        skel_path = get_asset_skeleton(asset_id)
    else:
        skel_path = diff_skel_path
    cmds.currentTime(start_frame - 1)

    current_scale = frag_rig.rig_scale
    if current_scale != 1.0:
        frag_rig.rig_scale = 1.0

    if skel_path:
        skel_utils.restore_skeleton_markup(skel_path, skel_root)
        skel_scale = skel_root.scale.get()
        skel_utils.restore_skeleton_bindpose(skel_path, skel_root)
        skel_root.scale.set(skel_scale)
    else:
        # unable to find a skel file, will attempt to attach at min_frame
        logger.warning('Unable to set skel to bind, will attempt an attach at the min frame.')

    # reset rig position
    for wrapped_flag in frag_rig.get_flags():
        flag_frag_parent = frag.FRAGNode(pm.listConnections(f'{wrapped_flag}.fragParent')[0])
        # remove any existing constraints as it'll prevent a clean bake. Constraints that came from attaching two
        # rigs are restored at the end by re-running attach_rigs.
        if not isinstance(flag_frag_parent, (frag.FaceFKComponent, frag.EyeCenterComponent, frag.EyeComponent)):
            pm.delete(wrapped_flag.getChildren(type=pm.nt.ParentConstraint))
            for attr_type in 'tr':
                for axis_type in 'xyz':
                    current_attr = wrapped_flag.attr(f'{attr_type}{axis_type}')
                    if not current_attr.isLocked():
                        current_attr.set(0)

    bakeable_node_list, custom_attr_list, things_to_delete = attach_rig_to_skeleton(frag_rig, skel_root,
                                                                                    maintain_offset=True)

    driver_rig = None
    if frag_rig.pynode.hasAttr('attached_to'):
        driver_rig = frag.FRAGNode(frag_rig.pynode.getAttr('attached_to'))
        frag_rig.pynode.disconnectAttr('attached_to')

    # snap frame after constraints to catch the rig up.
    cmds.currentTime(start_frame - 1)
    baking.bake_objects(bakeable_node_list, bake_range=[start_frame, end_frame],
                        custom_attrs=list(set(custom_attr_list)))
    pm.delete(things_to_delete)

    if current_scale != 1.0:
        frag_rig.rig_scale = current_scale

    if driver_rig:
        attach_rigs(driver_rig, frag_rig)


def animate_head_rig_from_skel(frag_rig, other_root, start_frame=None, end_frame=None):
    """
    Reanimates head rig components

    :param FRAGRig frag_rig: The FRAGRig of the rig to attach to the skeleton
    :param pm.nt.Joint other_root: The animated skeleton we will be transferring animation from.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    frag_children = frag_rig.get_frag_children()
    for frag_child in frag_children:
        if isinstance(frag_child, (frag.FaceFKComponent, frag.EyeCenterComponent, frag.EyeComponent)):
            frag_child.reanimate(other_root, start_time=start_frame, end_time=end_frame)


@ma_decorators.keep_namespace_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_selection_decorator
@ma_decorators.keep_current_frame_decorator
@ma_decorators.undo_decorator
def switch_multiconstraint(rig_multi_dict, switch_target, start_frame=None, end_frame=None):
    """
    Switch a rig's multicconstraint target, and bake animation across.

    :param dict{} rig_multi_dict: A dictionary containing FRAGRigs and a list of mulitconstraints to be switched.
    :param Transform switch_target: The object the multiconstraints will be switched to.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    root_namespace = ''

    temp_namespace = strings.generate_random_string(5)
    namespace.set_namespace(temp_namespace)
    flag_list = []
    pm.autoKeyframe(state=False)
    rig = None
    for frag_rig, multi_constraint_list in rig_multi_dict.items():
        all_grp = frag_rig.pynode.getAttr('all')
        driver_all_grp = pm.duplicate(all_grp, upstreamNodes=True, returnRootsOnly=True)[0]
        driver_rig = frag.FRAGNode(driver_all_grp.getAttr('fragParent'))
        rig = frag_rig

        for multiconstraint_node in multi_constraint_list:
            root_namespace = multiconstraint_node.pynode.namespace()

            switch_node = multiconstraint_node.pynode.getAttr('switchObject')
            source_node = multiconstraint_node.pynode.getAttr('sourceObject')

            rig_component = frag.FRAGNode(source_node.getAttr('fragParent'))
            flag_index = rig_component.get_flags().index(source_node)

            driver_component = get_frag_keyable_component(driver_rig, rig_component.region, rig_component.side)
            driver_source_node = driver_component.get_flags()[flag_index]
            follow_string = 'follow'
            if switch_node.hasAttr('follow'):
                follow_attr = switch_node.follow
            else:
                follow_attr = switch_node.rotateFollow
                follow_string = 'rotateFollow'
            attr_target_dict = follow_attr.getEnums()
            target_name = naming.get_basename(switch_target)
            if target_name in attr_target_dict:
                pm.cutKey(follow_attr)
                switch_node.setAttr(follow_string, attr_target_dict[target_name])
            else:
                # failed to find switch target.
                continue

            # since we're aligning flag to flag from a duplicate rig we don't need to zero either first
            constraint.parent_constraint_safe(driver_source_node, source_node)
            flag_list.append(source_node)
            # Jump to a frame well outside any animation so the new constraints evaluate before baking.
            cmds.currentTime(-1337)

    if None in [start_frame, end_frame]:
        start_frame, end_frame = time_utils.get_times(flag_list)

    namespace.set_namespace(root_namespace)
    baking.bake_objects(flag_list, bake_range=[start_frame, end_frame])
    namespace.purge_namespace(temp_namespace)
    if rig:
        return rig.get_asset_id(rig)
    return


def create_locator_at_object(obj, label=None):
    """
    Creates a locator at object, matching position a rotation.

    :param pm.nt.Transform obj: Object in a scene to match position.
    :param str label: Renames the locator to the given name.
    :return: Returns the locator.
    :rtype: pm.nt.Locator
    """

    if not obj or not pm.objExists(obj):
        locator = pm.spaceLocator(p=[0, 0, 0])
        if label:
            locator.rename(label)
    else:
        obj = pm.PyNode(obj)
        locator = pm.spaceLocator(p=[0, 0, 0])

        if label:
            locator.rename(label)

        else:
            locator.rename(obj.name() + "_loc")

        if obj.hasAttr('rotateOrder'):
            locator.rotateOrder.set(obj.rotateOrder.get())
        pm.delete(pm.parentConstraint(obj, locator, w=True, mo=False))
    return locator


def create_locator_at_point(point, name=None):
    """
    Creates a locator object at point given.
    :param pm.dt.Point point: Point position.
    :param str name: Name of the locator .
    :return: Returns a locator.
    :rtype: pm.nt.spaceLocator
    """
    point = pm.dt.Point(point)
    locator = pm.spaceLocator(p=[0, 0, 0])

    if name:
        locator.rename(name)

    locator.translate.set(point)

    return locator


def find_primary_axis(node):
    """
    From the current node's translation or the translation of it's first child. Find the largest deviant and return it.

    :param Transform node: The node to check for the primary axis.
    :return: The axis letter ('X', 'Y', or 'Z') with the largest translate value and whether that value is positive.
    :rtype: str, bool
    """

    child_node = lists.get_first_in_list(node.getChildren())

    target_node = child_node or node

    max_val = 0
    primary_axis = 'X'
    axis_is_positive = True
    for axis_name, x in zip('XYZ', target_node.t.get()):
        if abs(x) > max_val:
            max_val = abs(x)
            primary_axis = axis_name
            if x > 0:
                axis_is_positive = True
            else:
                axis_is_positive = False
    return primary_axis, axis_is_positive


def attach_rig_to_skeleton(frag_rig, skel_root, maintain_offset=True):
    """
    Attaches all of the keyable components of a frag_rig to the passed skeleton.

    :param FRAGRig frag_rig: The FRAGRig of the rig to attach to the skeleton.
    :param Joint skel_root: The root joint of the skeleton to attach to.
    :param bool maintain_offset: If when attaching to the skeleton the rig should maintain its offset.
    :return: Three lists containing: The bakeable nodes, a list of custom attrs found, and the constraints to delete
        after baking
    :rtype: list, list, list
    """

    bakable_node_list = []
    custom_attr_list = []
    things_to_delete = []
    for rig_component in frag_rig.get_frag_children():
        if isinstance(rig_component, frag.KeyableComponent):
            if not isinstance(rig_component, (frag.FaceFKComponent, frag.EyeCenterComponent, frag.EyeComponent,
                                              frag.ChannelFloatComponent)):
                rig_component.attach_to_skeleton(skel_root, mo=maintain_offset)
                node_list, attr_list, constraint_list = rig_component.get_bakeable_rig_nodes()
                bakable_node_list += node_list
                custom_attr_list += attr_list
                things_to_delete += constraint_list
    return bakable_node_list, custom_attr_list, things_to_delete


def get_frag_keyable_component(rig_root, region, side):
    """
    From the attached children get the keyable component with the matching markup.
    This should be used to find an exact component.

    :param FRAGRoot rig_root: The frag structure to search.
    :param str region: The string value of the region
    :param str side: The string value of the side.
    :return: The requested keyable component, or None if no child matches.
    :rtype: KeyableComponent or None
    """

    if rig_root.pynode.hasAttr('fragChildren'):
        frag_children = rig_root.pynode.fragChildren.listConnections()
        for child_node in frag_children:
            wrapped_node = frag.FRAGNode(child_node)
            if not isinstance(wrapped_node, frag.KeyableComponent):
                continue

            if wrapped_node.side != side:
                continue

            if wrapped_node.region != region:
                continue

            return wrapped_node


def purge_rig_cmd():
    """
    Purge every FRAG rig found in the current selection, after the user confirms.

    Called by the Toolbox "Purge Rig" button (by string, so no importer shows up in a code search).
    """

    result = dialogs.question_prompt(title='Purge Rig?', text='You are about to purge a rig/rigs!\nContinue?')
    if result != 'Yes':
        return

    selection = pm.selected()
    if not selection:
        dialogs.info_prompt(title='Purge Rig', text='Please make sure you select at least one FRAG rig!')
        logger.warning('Please make sure you select at least one FRAG rig!')
        return
    for x in selection:
        frag_rig = frag.get_frag_rig(x)
        if frag_rig:
            purge_rig(frag_rig)


@ma_decorators.undo_decorator
def purge_rig(frag_rig):
    """
    From a given frag_rig find and delete its major components.
    NOTE: This does leave behind materials and a handful of nodes if the rig is not within a namespace.
    NOTE: This will PURGE a namespace if the rig is within one.

    :param FRAGRig frag_rig: The FRAGRig to be purged from the scene.
    """

    namespace_name = frag_rig.pynode.namespace()
    if namespace_name:
        namespace.set_namespace('')
        namespace.purge_namespace(namespace_name)
    else:
        frag_root = frag_rig.get_root()
        display_layer_network_node = lists.get_first_in_list(
            [x for x in frag_rig.pynode.listConnections(type=pm.nt.Network) if 'DisplayLayers' in x.name()])

        # Build list of items to delete
        items_to_delete = frag_root.get_frag_children() + [frag_rig.all_grp] + frag_rig.get_frag_children()

        # Add display layer connections if display layers exist
        if display_layer_network_node:
            items_to_delete.extend(display_layer_network_node.layers.listConnections())

        pm.delete(items_to_delete)


@ma_decorators.keep_namespace_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
@ma_decorators.undo_decorator
def single_frame_switch(rig_components_dict, start_frame=None, end_frame=None):
    """
    Switches between IK and FK settings on components with switching feature, matches position, and sets key.

    :param dict rig_components_dict: A dictionary of FRAGRigs to a list of switchable components.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    temp_namespace = strings.generate_random_string(5)

    for frag_rig, component_list in rig_components_dict.items():

        root_namespace = frag_rig.pynode.namespace()
        og_ikfk_flag_list = []
        flag_list = []
        for rig_component in component_list:
            if not isinstance(rig_component, (frag.IKFKComponent, frag.ReverseFootComponent,
                                              frag.IKFKRibbonComponent, frag.ZLegComponent)):
                logger.warning(f'Skipping {rig_component}, as it is not one of the supported component types.')
                continue

            pm.autoKeyframe(state=False)

            # Flip the switch flag.
            switch_flag = rig_component.pynode.getAttr('switchFlag')
            switch_setting = switch_flag.getAttr('ikfk_switch')
            pm.setKeyframe(switch_flag, t=start_frame)
            is_ik = bool(switch_setting)
            switch_flag.setAttr('ikfk_switch', (not switch_setting))
            pm.setKeyframe(switch_flag, t=end_frame)

            namespace.set_namespace(temp_namespace)

            if is_ik:
                if isinstance(rig_component, (frag.ReverseFootComponent, frag.ZLegComponent)):
                    fk_flag_list = rig_component.fk_flags
                else:
                    fk_flag_list = rig_component.fk_flags[:3]
                flag_list += fk_flag_list

                for fk_flag, ik_joint_node in list(zip(fk_flag_list, rig_component.pynode.ikChain.listConnections())):
                    constraint.parent_constraint_safe(ik_joint_node, fk_flag, mo=False)
                og_ikfk_flag_list += rig_component.ik_flags

            else:
                ik_flag = rig_component.ik_flag
                pv_flag = rig_component.pv_flag
                flag_list += [ik_flag, pv_flag]
                fk_joint_list = rig_component.pynode.fkChain.listConnections()[:3]

                if isinstance(rig_component, (frag.ReverseFootComponent, frag.ZLegComponent)):
                    ik_loc = create_locator_at_object(rig_component.pynode.ikChain.listConnections()[-2])
                    toe_flag = rig_component.pynode.ikToeFlag.listConnections()[0]
                    flag_list.append(toe_flag)
                    constraint.parent_constraint_safe(ik_loc, ik_flag, mo=True)
                    constraint.parent_constraint_safe(rig_component.pynode.fkChain.listConnections()[-2], ik_loc,
                                                      mo=False)
                    constraint.parent_constraint_safe(rig_component.pynode.fkChain.listConnections()[-1], toe_flag,
                                                      mo=False)
                else:
                    constraint.parent_constraint_safe(fk_joint_list[-1], ik_flag, mo=False)

                pv_loc = ik_utils.create_pole_vector_locator(fk_joint_list)
                pv_loc.setParent(fk_joint_list[1])
                constraint.parent_constraint_safe(pv_loc, pv_flag, mo=False)
                og_ikfk_flag_list += rig_component.fk_flags

            namespace.set_namespace(root_namespace)

        pm.setKeyframe(flag_list, t=end_frame)
        pm.setKeyframe(og_ikfk_flag_list, t=start_frame)

    namespace.purge_namespace(temp_namespace)


def anim_curve_retarget(source_frag_rig, target_frag_rig):
    """
    Transfers all animations from one rig to another using animation curves.

    :param frag.FRAGRig source_frag_rig: The rig that initially has the animations
    :param frag.FRAGRig target_frag_rig: The animation that is receiving the animations
    """

    anim_comp = frag.AnimatedCurvesComponent.create(source_frag_rig)

    flags = source_frag_rig.get_flags()

    for flag in flags:
        if flag.hasAttr('ikfk_switch'):
            pm.setKeyframe(flag)

    anim_comp.store_all_animation_curves(obj_list=flags,
                                         keep_animation=True,
                                         min_time_range=None,
                                         max_time_range=None,
                                         merge_layers=True,
                                         start_time=None)

    dup_flags = target_frag_rig.get_flags()

    anim_comp.restore_all_animation_curves(obj_list=dup_flags,
                                            force_unlock=True,
                                            keep_curves=False,
                                            delete_old_curves=True,
                                            start_time=None)

    anim_comp.remove()


def transfer_animation_curves_to_rig(source_frag_rig, target_frag_rig, preserve_layers=True, start_time=None):
    """
    Transfers animation from one FRAG rig to another using the AnimatedCurvesComponent.

    This is the layer-preserving cousin of ``anim_curve_retarget``.  When ``preserve_layers``
    is True, each flag's animation layer stack is recorded on the component's
    ``animationLayers`` compound connection and rebuilt on the target rig; when False, the
    layers are flattened to a single merged curve before transfer (faster, matches the
    behaviour of ``anim_curve_retarget``).  The source rig keeps its original animation -
    the component duplicates curves on its way in and disconnects from the target on its way
    out, then deletes itself.

    The source and target rigs must share the same flag naming scheme, since the component
    reconnects curves by basename-stripped attribute lookup.

    :param frag.FRAGRig source_frag_rig: The rig that currently has the animations.
    :param frag.FRAGRig target_frag_rig: The rig that will receive the animations.
    :param bool preserve_layers: If True, animation layers are preserved.  If False, layers
        are flattened before transfer.
    :param int start_time: Optional start frame to offset the transferred animation to.
    """

    # Create the staging node parented under the source rig.  It lives just long enough to
    # carry the curves across to the target.
    anim_comp = frag.AnimatedCurvesComponent.create(source_frag_rig)

    source_flags = source_frag_rig.get_flags()

    # IK/FK switch values are state-ful - make sure there is a key so the state is captured
    # into the stored curve set rather than lost on transfer.
    for flag in source_flags:
        if flag.hasAttr('ikfk_switch'):
            pm.setKeyframe(flag)

    # Store curves off the source flags.  ``merge_layers=False`` is the important bit - it
    # is what causes store_animation_curves() to wire the source's AnimLayer nodes into the
    # component's ``animationLayers`` message attribute for later reconstruction.
    anim_comp.store_all_animation_curves(obj_list=source_flags,
                                            keep_animation=True,
                                            merge_layers=not preserve_layers,
                                            start_time=start_time)

    # Push the stored curves onto the target rig's flags.  keep_curves=False hands
    # ownership of the curves to the target and disconnects the staging compound attrs.
    target_flags = target_frag_rig.get_flags()
    anim_comp.restore_all_animation_curves(obj_list=target_flags,
                                            force_unlock=True,
                                            keep_curves=False,
                                            delete_old_curves=True,
                                            start_time=start_time)

    # The staging node has served its purpose; tearing it down leaves the target rig with
    # clean ownership of the curves (and the original AnimLayer nodes if preserved).
    anim_comp.remove()


@ma_decorators.keep_namespace_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
@ma_decorators.undo_decorator
def switch_ikfk_components(rig_components_dict, start_frame=None, end_frame=None):
    """
    Given a dictionary of rigs and a list of ik/fk components switch or rebuild the component, while retaining the
    original animation.

    If a frame range is not provided we use the start/end keyframe in the scene, or best guess.

    :param dict rig_components_dict: A dictionary of FRAGRigs to a list of switchable components.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    temp_namespace = strings.generate_random_string(5)
    namespace.set_namespace(temp_namespace)

    for frag_rig, component_list in rig_components_dict.items():
        root_namespace = frag_rig.pynode.namespace()

        # Import a fresh copy of the rig to act as the driver; it carries the original animation so the switched
        # flags on the real rig can be constrained to it and baked.
        asset_id = frag_rig.get_root().asset_id
        dup_frag_root = import_asset(asset_id=asset_id, ns=temp_namespace)
        target_frag_rig = dup_frag_root.get_rig()

        driver_all_grp = target_frag_rig.all_grp

        anim_curve_retarget(frag_rig, target_frag_rig)

        driver_rig = frag.FRAGNode(driver_all_grp.getAttr('fragParent'))

        flag_list = []
        driver_flag_list = []
        for rig_component in component_list:
            if not isinstance(rig_component, (frag.IKFKComponent, frag.ReverseFootComponent,
                                              frag.IKComponent, frag.FKComponent,
                                              frag.IKFKRibbonComponent, frag.ZLegComponent)):
                logger.warning(f'Skipping {rig_component}, as it is not one of the supported component types.')
                continue
            driver_component = get_frag_keyable_component(driver_rig, rig_component.region,
                                                          rig_component.side)

            is_ik = False
            switch_flag = None
            switch_setting = None
            pm.autoKeyframe(state=False)
            if isinstance(rig_component, (frag.IKFKComponent, frag.ReverseFootComponent, frag.IKFKRibbonComponent,
                                          frag.ZLegComponent)):
                # this handles ik/fk components and the reverse foot component. It's arguable this sorta functionality
                # should live with the component, but we can reduce the amount of duplicating by running it all in
                # one space here.

                # reset flags on the OG rig since we'll be overriding that stuff anyway
                switch_flag = rig_component.pynode.getAttr('switchFlag')
                switch_setting = switch_flag.getAttr('ikfk_switch')
                pm.cutKey(switch_flag.ikfk_switch)
                is_ik = bool(switch_setting)

                # be surgical here since our reverse foot component includes several additional
                # FK flags that are always on, this should just get us the first three primary chain flags.
                original_flag_list = rig_component.fk_flags[:3] + [rig_component.ik_flag, rig_component.pv_flag]
                pm.cutKey(original_flag_list)
                for wrapped_flag in original_flag_list:
                    attr_utils.reset_attrs(wrapped_flag.node)

                # Flip the switch flag.
                switch_flag.setAttr('ikfk_switch', (not switch_setting))

            else:
                # Pure IK or FK components cannot be switched without removing and rebuilding the component, which
                # would also require saving and restoring attachments and multiconstraints. That is not implemented,
                # so this branch only records the direction of the switch.
                for og_rig_component in frag_rig.get_frag_children():
                    if not isinstance(og_rig_component, frag.KeyableComponent):
                        continue

                if isinstance(rig_component, frag.IKComponent):
                    # Would remove the IK component and build an FK component.
                    is_ik = True

                elif isinstance(rig_component, frag.FKComponent):
                    # Would remove the FK component and build an IK component.
                    is_ik = False

            # align rigs.
            for wrapped_flag in frag_rig.get_flags() + driver_rig.get_flags():
                # Unkeyed non default values are lost here; they may need saving and restoring in the future.

                # this specifically handles issues with the reverse foot component since the IK/FK chains
                # don't align at the ankle.
                for attr_type in 'tr':
                    for axis_type in 'xyz':
                        current_attr = wrapped_flag.attr(f'{attr_type}{axis_type}')
                        if not current_attr.isLocked():
                            current_attr.set(0)

            if is_ik:
                driver_flag_list += driver_component.get_flags()
                fk_flag_list = rig_component.fk_flags[:3]
                flag_list += fk_flag_list
                for fk_flag, ik_joint_node in list(zip(fk_flag_list,
                                                       driver_component.pynode.ikChain.listConnections())):
                    constraint.parent_constraint_safe(ik_joint_node, fk_flag, mo=True)
            else:
                driver_flag_list += driver_component.get_flags()
                ik_flag = rig_component.ik_flag
                pv_flag = rig_component.pv_flag
                flag_list += [ik_flag, pv_flag]
                fk_joint_list = driver_component.pynode.fkChain.listConnections()[:3]
                constraint.parent_constraint_safe(fk_joint_list[-1], ik_flag, mo=True)
                pv_loc = ik_utils.create_pole_vector_locator(fk_joint_list)
                pv_loc.setParent(fk_joint_list[1])
                constraint.parent_constraint_safe(pv_loc, pv_flag, mo=True)
            # Jump to a frame well outside any animation so the new constraints evaluate before baking.
            cmds.currentTime(-1337)
            # reattach components.

        if None in [start_frame, end_frame]:
            start_frame, end_frame = time_utils.get_times(driver_flag_list)

        namespace.set_namespace(root_namespace)
        baking.bake_objects(flag_list, bake_range=[start_frame, end_frame])

        if pm.objExists(target_frag_rig.pynode):
            purge_rig(target_frag_rig)

    namespace.purge_namespace(temp_namespace)


@ma_decorators.keep_selection_decorator
def switch_ikfk_components_cmd(start_frame=None, end_frame=None):
    """
    Switch IK/FK on the components that own the selected flags.

    Called by the Toolbox "IK/FK Switch" buttons (by string, so no importer shows up in a code search). A two frame
    range (``end - start == 1``) runs the single frame switch; any other range, or none, bakes the whole switch.
    If a frame range is not provided the start/end keyframes in the scene are used.

    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    selection = pm.selected()
    flag_filter_list = [x for x in selection if frag_flag.is_flag_node(x)]

    # Group the switchable components by the rig that owns them.
    rig_components_dict = {}
    for wrapped_flag in flag_filter_list:
        rig_component = frag.FRAGNode(wrapped_flag.fragParent.get())
        frag_rig = rig_component.get_frag_parent()

        if isinstance(rig_component, (frag.IKFKComponent, frag.ReverseFootComponent,
                                      frag.IKComponent, frag.FKComponent,
                                      frag.IKFKRibbonComponent, frag.ZLegComponent)):
            if frag_rig not in rig_components_dict:
                rig_components_dict[frag_rig] = []
            rig_components_dict[frag_rig].append(rig_component)

    single_frame = False
    if end_frame is not None and start_frame is not None:
        single_frame = abs(end_frame - start_frame) + 1 == 2
    if single_frame:
        single_frame_switch(rig_components_dict, start_frame=start_frame, end_frame=end_frame)
    else:
        switch_ikfk_components(rig_components_dict, start_frame, end_frame)


def reload_rig_cmd():
    """
    Wrapped fnc for the reload_rig fnc.

    :return: The asset ids of every reloaded rig, or None if nothing was selected.
    :rtype: list[str] or None
    """

    selection = pm.selected()
    frag_rigs = []
    if not selection:
        dialogs.info_prompt(title='Reload Rig', text='Please make sure you select at least one FRAG rig!')
        logger.warning('Please make sure you select at least one FRAG rig!')
        return
    for x in selection:
        frag_rig = frag.get_frag_rig(x)
        if frag_rig:
            reload_rig(frag_rig)
            frag_rigs.append(frag_rig)
    asset_ids = [x.get_asset_id(x) for x in frag_rigs]
    return asset_ids


@ma_decorators.undo_decorator
def reload_rig(frag_rig):
    """
    From the given frag_rig bake the animation down to a skeleton, reimport the rig, then restore the animation to it.

    :param FRAGRig frag_rig: The rig to reload. Its namespace is purged and replaced by the fresh import.
    :return: The re-imported FRAGRig
    :rtype: FRAGRig
    """

    asset_id = frag_rig.get_asset_id(frag_rig)
    skel_root = bake_skeleton_from_rig(frag_rig, set_to_zero=False)

    namespace.purge_namespace(frag_rig.pynode.namespace())
    frag_root = import_asset(asset_id)
    frag_rig = frag_root.get_rig()

    animate_rig_from_skeleton(frag_rig, skel_root)
    pm.delete(skel_root)
    return frag_rig


@ma_decorators.keep_namespace_decorator
def import_asset(asset_id, ns=None):
    """
    From the asset id import the skeleton and rig. If the .skel and .rg files are missing default to the .ma file.

    :param str asset_id: AssetId lookup for a given asset.
    :param str ns: Namespace.
    :return: The FRAGRoot of the imported asset.
    :rtype: FRAGRoot
    """

    mca_asset = _ASSET_MANAGER.get_record(asset_id)
    if not mca_asset:
        # failed to find asset registered
        logger.warning(f'Unable to find asset: {asset_id}')
        return

    maya_path = lists.get_first_in_list(mca_asset.get_rig_list())
    skel_path = mca_asset.skel_path
    # short circuit rig path for now.
    rig_path = ''

    msg = f'The path was not found on disk.  Please make sure you have the file.'

    if not maya_path or (not os.path.isfile(maya_path) and not os.path.isfile(rig_path)):
        dialogs.info_prompt(title='Import Asset', text=msg)
        logger.warning(msg)
        return

    namespace_to_use = ns
    if not namespace_to_use:
        # Handle namespace
        namespace_to_use = mca_asset.namespace

        if not namespace_to_use:
            base_namespace = re.sub('[^a-zA-Z]+', '', mca_asset.name[:3])
            i = 4
            while len(base_namespace) < 3 and i <= 20:
                base_namespace = re.sub('[^a-zA-Z]+', '', mca_asset.name[:i])
                i += 1
            if base_namespace == '':
                base_namespace = 'zzz'
            found_namespace = namespace.get_namespace(f'{base_namespace}')

            if found_namespace:
                i = 0
                while namespace.get_namespace(found_namespace) != '':
                    i += 1
                    found_namespace = f'{base_namespace}{i}'
            namespace_to_use = found_namespace if found_namespace != '' else base_namespace
        namespace_to_use = namespace_to_use.lower()
    namespace.set_namespace(namespace_to_use)

    frag_root = None
    if all(os.path.isfile(x) for x in [rig_path, skel_path]):
        root_joint = skel_utils.import_skeleton(skel_path)
        if not root_joint:
            # failed to import a skeleton
            logger.warning(f'Skeleton failed to import from. {skel_path}')
            return
        frag_root = frag.FRAGRoot.create(root_joint, mca_asset.asset_type, asset_id)
        frag_rig = frag.FRAGRig.create(frag_root)

        import_rig(rig_path, frag_rig)
    elif os.path.isfile(maya_path):
        imported_node_list = pm.importFile(maya_path, returnNewNodes=True)
        for node in pm.ls(imported_node_list, type=pm.nt.Network):
            if node.name().endswith('FRAGRoot'):
                frag_root = frag.FRAGNode(node)
                break
        pm.refresh()
        material_utils.refresh_file_nodes()
    namespace.delete_empty_namespaces()
    return frag_root


def import_rig(rig_path, rig_root):
    """
    From a serialized rig file, build a rig.

    This is a stub: serialized .rg rig files are not supported yet, so it does nothing and returns None.
    ``import_asset`` short circuits the rig path so this is never reached in practice.

    :param str rig_path: Path to a serialized rig file.
    :param FRAGRig rig_root: The FRAGRig the rig would be built under.
    :return: None
    :rtype: None
    """

    return


@ma_decorators.keep_selection_decorator
def mirror_rig_cmd(start_frame=None, end_frame=None):
    """
    Mirrors the frame range on a particular rig. This only works on nearly symmetrical rigs.

    If a frame range is not provided we use the start/end keyframe in the scene, or best guess.

    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    :return: The asset ids of every mirrored rig, or None if nothing was selected or no keyframes were found.
    :rtype: list[str] or None
    """

    selection = pm.selected()

    if not selection:
        dialogs.info_prompt(title='Mirror Rig', text='Please make sure you select at least one FRAG rig!')
        logger.warning('Please make sure you select at least one FRAG rig!')
        return

    frag_roots = []
    for x in selection:
        frag_rig = frag.get_frag_rig(x)
        if frag_rig:
            frag_root = frag_rig.get_root()
            frag_roots.append(frag_root)

            # retrieve a valid frame range.
            if any(x is None for x in [start_frame, end_frame]):
                start_frame, end_frame = time_utils.get_keyframe_range_from_nodes(frag_rig.get_flags())

            if any(x is None for x in [start_frame, end_frame]):
                # unable to retrieve a valid framerange.
                logger.warning(f'No keyframes found on: {frag_root.pynode.getAttr("assetName")}')
                return

            mirror_rig(frag_rig, start_frame, end_frame)
    asset_ids = [x.asset_id for x in frag_roots]
    return asset_ids


@ma_decorators.keep_namespace_decorator
@ma_decorators.keep_autokey_decorator
@ma_decorators.keep_current_frame_decorator
@ma_decorators.undo_decorator
def mirror_rig(frag_rig, start_frame, end_frame):
    """
    This mirrors a rig's animation by baking it down to a skeleton, mirroring the skeleton then reattaching it to the
    active rig.

    :param FRAGRig frag_rig: The Frag rig which animation's should be mirrored.
    :param int start_frame: The first frame in the bake range.
    :param int end_frame: The last frame in the bake range.
    """

    frag_root = frag_rig.get_root()
    asset_id = frag_root.asset_id

    # Setup our working name space and disable autokey.
    temp_namespace = strings.generate_random_string(5)
    namespace.set_namespace(temp_namespace)
    pm.autoKeyframe(state=False)

    skel_path = get_asset_skeleton(asset_id)

    if end_frame - start_frame > 1:
        # If we're doing more than just a pose bake the frame range.
        drive_root = bake_skeleton_from_rig(frag_rig, start_frame, end_frame, False)
    else:
        # If it's a single pose duplicate the skeleton and match it to the pose
        drive_root = pm.duplicate(frag_root.root_joint)[0]
        drive_root.setParent(None)
        pm.setKeyframe([drive_root] + drive_root.listRelatives(ad=True, type=pm.nt.Joint))

    # Align skeletons and rig.
    skel_utils.restore_skeleton_bindpose(skel_path, drive_root)
    rev_root = pm.duplicate(drive_root, upstreamNodes=True, returnRootsOnly=True)[0]
    skel_utils.restore_skeleton_bindpose(skel_path, rev_root)

    # Flip our mirror to get the inverse.
    mirror_group = pm.group(n='mirror_grp', em=True, w=True)
    rev_root.setParent(mirror_group)
    mirror_group.sx.set(-1)
    final_root = skel_utils.import_skeleton(skel_path)
    rev_skel_hierarchy = chain_markup.ChainMarkup(rev_root)
    final_skel_hierarchy = chain_markup.ChainMarkup(final_root)

    # Constrain our joints through the hierarchies. If a joint isn't found on the mirror, just copy what the original
    # was doing. If the rig is not symmetrical this could end up pretty weird.
    for drv_joint in [drive_root] + drive_root.listRelatives(ad=True, type=pm.nt.Joint):
        joint_name = naming.get_basename(drv_joint)
        if joint_name.endswith('_l'):
            rev_joint_name = joint_name[:-2] + '_r'
        elif joint_name.endswith('_r'):
            rev_joint_name = joint_name[:-2] + '_l'
        else:
            rev_joint_name = joint_name

        rev_joint = rev_skel_hierarchy.skeleton_dict.get(rev_joint_name, None)
        fin_joint = final_skel_hierarchy.skeleton_dict.get(joint_name, None)

        # Only pair joints whose mirrored twin lands within 2 units; anything further is treated as asymmetrical.
        drv_position = pm.xform(drv_joint, q=True, ws=True, t=True)
        rev_position = pm.xform(rev_joint, q=True, ws=True, t=True)
        if pymaths.get_vector_length(pymaths.sub_vectors(drv_position, rev_position)) < 2:
            constraint.parent_constraint_safe(rev_joint, fin_joint, mo=True)
        else:
            logger.warning(f'{joint_name} was not mirrored as a reverse joint was not found within range.')
            constraint.parent_constraint_safe(drv_joint, fin_joint)

    # Reset the namespace so we can keep our keys after the purge.
    namespace.set_namespace(':')
    animate_rig_from_skeleton(frag_rig, final_root, start_frame=start_frame, end_frame=end_frame)

    namespace.purge_namespace(temp_namespace)


def setup_twist_components(frag_rig):
    """
    Purge old twist components and rebuild them.

    :param FRAGRig frag_rig: The FRAGRig to have new twist joints built on.
    """

    existing_twist_component_list = frag_rig.get_frag_children(of_type=frag.TwistFixUpComponent)
    for twist_component in existing_twist_component_list:
        if twist_component.get_version() != frag.TwistFixUpComponent.VERSION:
            pm.delete([twist_component.noTouch.get(), twist_component.get_pynode()])

    frag_root = frag_rig.get_root()
    skel_root = frag_root.root_joint

    flag_utils.zero_flags([frag_rig])

    skel_hierarchy = chain_markup.ChainMarkup(skel_root)
    for side, entry_dict in skel_hierarchy.twist_joints.items():
        for twist_chain, data_dict in entry_dict.items():
            frag.TwistFixUpComponent.create(frag_rig, data_dict['joints'], side, twist_chain)


@ma_decorators.keep_selection_decorator
def export_flag_shapes_cmd():
    """
    From the selected frag rigs export all flag shapes to their local flags directories.
    """

    selection = pm.selected()

    if not selection:
        messages.info_message('Selection Error', 'Please select flag replacement shapes.', icon='error')
        return

    exported_rig_list = []
    for x in selection:
        frag_rig = frag.get_frag_rig(x)
        if frag_rig and frag_rig not in exported_rig_list:
            exported_rig_list.append(frag_rig)
            export_flag_shapes(frag_rig)


def export_flag_shapes(frag_rig):
    """
    From a given frag rig export all flag shapes to its local flags directory.

    :param FRAGRig frag_rig: The FRAGRig to have export shapes from.
    """

    frag_root = frag_rig.get_root()
    asset_id = frag_root.asset_id
    mca_asset = _ASSET_MANAGER.get_record(asset_id)
    # Bail out with a useful message if the rig's stored assetID is not in the
    # asset registry (common when rigs were built against an older registry
    # schema). Without this guard, we would hit an AttributeError on flags_path.
    if not mca_asset:
        msg = (f'Asset id "{asset_id}" was not found in the asset registry. '
               f'Register the asset via the Asset Register tool before exporting flag shapes.')
        logger.warning(msg)
        messages.info_message('Export Flags', msg, icon='error')
        return

    base_flag_path = mca_asset.flags_path
    if not base_flag_path:
        msg = (f'Asset "{mca_asset.name}" has no flags_path configured in the registry. '
               f'Check the asset record before exporting flag shapes.')
        logger.warning(msg)
        messages.info_message('Export Flags', msg, icon='error')
        return

    for flag_node in frag_rig.get_flags():
        flag_path = os.path.join(base_flag_path, f'{naming.get_basename(flag_node)}.flag')
        frag_flag.export_flag(flag_node.node, flag_path)


def remove_dead_frag_nodes(ignore_types=None):
    """
    Removes dead (non-connected) FRAG nodes. Ignores CineSequenceComponent and FRAGSequencer by default as these
    are not expected to be connected to a rig.

    :param tuple(type) ignore_types: A list of types to ignore.
    :return: Returns a list of the names of the removed nodes.
    :rtype: list[str]
    """

    # These types are not expected to be connected to a rig, so ignore them.
    if not ignore_types:
        ignore_types = (frag.CineSequenceComponent, frag.FRAGSequencer)

    # Get all rigs and any nodes connected to them.
    f_rigs = frag.get_frag_rigs()
    all_connections = []
    for f_rig in f_rigs:
        f_root = frag.get_frag_root(f_rig)
        rig_connections = f_rig.pynode.listConnections()
        root_connections = f_root.pynode.listConnections()
        all_connections = list(set(rig_connections + root_connections + [f_rig, f_root] + all_connections))

    # Get all network nodes in scene and check if they are abandoned.
    abandoned_frag_nodes = []
    scene_network_nodes = pm.ls(type=pm.nt.Network)
    for network_node in scene_network_nodes:
        # If not a FRAG node, skip it.
        if not frag.is_frag_node(network_node):
            continue
        frag_node = frag.FRAGNode(network_node)
        if frag_node not in all_connections:
            # If it is connected to a rig just further down the line than to have caught it on
            # FRAGRig connections, skip it.
            if any(x in all_connections for x in frag_node.pynode.listConnections()):
                pass
            # If not connected and not in ignore_types, add it to the abandoned list.
            elif not isinstance(frag.FRAGNode(network_node), ignore_types):
                abandoned_frag_nodes.append(frag_node)

    # Get a list of all Maya nodes connected to the abandoned FRAG nodes.
    delete_nodes = []
    for abandoned_node in abandoned_frag_nodes:
        node_connections = abandoned_node.pynode.listConnections()
        for node_connection in node_connections:
            delete_nodes.append(node_connection)

    # Getting string names of removed nodes for logging purposes.
    abandoned_frag_nodes_names = [x.name() for x in abandoned_frag_nodes]
    delete_nodes_list = list(set(delete_nodes))
    delete_nodes_names_list = [x.name() for x in delete_nodes_list]

    # Unlock all nodes in the removal list and delete.
    for node in delete_nodes_list:
        node.setLocked(False)
    pm.delete(delete_nodes_list)

    logger.warning(f'Full removal list: {delete_nodes_names_list}')
    logger.warning(f'Removed {len(abandoned_frag_nodes_names)} dead frag nodes: {abandoned_frag_nodes_names}')

    return abandoned_frag_nodes_names
