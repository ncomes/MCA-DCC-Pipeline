"""
Summoner utility functions for importing and exporting asset files.

Provides core functionality for:
- Importing assets (FBX files): rigs, skeletal meshes, static meshes, full skeletons
- Exporting assets with skinning and skeleton data
- Managing organization groups for export workflows
- Asset registry integration

Note: Organization groups use 'modelshop' attribute name for backward
compatibility with existing artist scenes.
"""

# System global imports
import os
import shutil
# software specific imports
import pymel.core as pm
import maya.cmds as cmds
# MCA python imports
from mca.common import log
from mca.common.utils import lists, fileio
from mca.common.p4v import perforce

from mca.mya.utils import fbx_utils, material_utils, dag, scene_utils, attr_utils
from mca.mya.deformations import skin_utils
from mca.mya.rigging import skel_utils, joint_utils

logger = log.MCA_LOGGER

NODE_WHITE_LIST = (pm.nt.Transform, pm.nt.Mesh, pm.nt.SkinCluster, pm.nt.BlendShape, pm.nt.DagPose,
                   pm.nt.Phong, pm.nt.Blinn, pm.nt.Lambert, pm.nt.ShadingEngine, pm.nt.GroupId, pm.nt.GroupParts, pm.nt.MaterialInfo,
                   pm.nt.Reverse, pm.nt.RemapValue, pm.nt.Bump2d, pm.nt.Place2dTexture, pm.nt.File)


def get_org_group(asset_entry, attr_name='modelshop'):
    groups = [x for x in pm.ls(type=pm.nt.Transform) if
              x.hasAttr(attr_name) and x.attr(attr_name).attr(f'{attr_name}_name').get() == asset_entry.name]
    group = None
    if groups:
        group = groups[0]
    return group


def get_all_org_groups(attr_name='modelshop'):
    groups = [x for x in pm.ls(type=pm.nt.Transform) if
              x.hasAttr(attr_name) and x.hasAttr(f'{attr_name}_isModelShop') and x.hasAttr(f'{attr_name}_isOrgGroup')]
    return groups


def create_asset_org_grp(asset_entry, attr_name='modelshop', delete_exiting=False):
    """
    Creates a group node to organize an asset_entry.

    :param AssetEntry asset_entry: An instance of AssetEntry
    :param attr_name: name of the compound_attr
    :return: Returns a group node to organize an asset
    :rtype: pm.nt.Group
    """
    
    groups = [x for x in pm.ls(type=pm.nt.Transform) if
              x.hasAttr(attr_name) and x.attr(attr_name).attr(f'{attr_name}_name').get() == asset_entry.name]
    group = None
    if groups:
        group = groups[0]
        if not delete_exiting:
            return group
        existing_children = group.getChildren()
        if existing_children:
            pm.delete(existing_children)
    
    if not group:
        group = pm.group(n=asset_entry.name, em=True, w=True)
        attr_dict = {'name': asset_entry.name,
                     'asset_id': asset_entry.asset_id,
                     'isModelShop': True,
                     'isOrgGroup': True,
                     }
        attr_utils.set_compound_attribute_groups(node=group, compound_attr_name=attr_name, attribute_dict=attr_dict)
    # if asset_entry.asset_type == gear_registry.ASSET_TYPE:
    #     parent_asset = asset_entry.get_parent_asset()
    #     print(f'This is the parent asset!: {parent_asset}')
    #     if parent_asset:
    #         parent_grp = create_asset_org_grp(parent_asset)
    #         pm.parent(group, parent_grp)
    
    return group


def import_source_file(file_path):
    """
    Model Shop core function for importing and cleaning fbx files for use in organizing scenes.
    Based on the NODE_WHITE_LIST established at the head of this file all other node types are removed.
    NOTE this function should be modified to support other file times if required.

    :param str file_path: A full path to a given .fbx file.
    :return: A list of all imported nodes that are part of a type matching those in the NODE_WHITE_LIST.
    :rtype: list[PyNode]
    """
    
    return_list = []
    imported_node_list = []
    things_to_delete = []
    if file_path.lower().endswith('.fbx'):
        imported_node_list = fbx_utils.import_fbx(file_path)
        material_list = [x for x in imported_node_list if x.hasAttr('texture_path')]
        material_utils.consolidate_materials(material_list)
        pm.delete(pm.ls(imported_node_list, type=pm.nt.DisplayLayer))
    
    for x in imported_node_list:
        if not cmds.objExists(x.name()):
            continue
        if isinstance(x, NODE_WHITE_LIST):
            return_list.append(x)
        else:
            things_to_delete.append(x)
    pm.delete(things_to_delete)
    return return_list


def get_imported_shape_nodes(node_list):
    parentable_object_list = []
    shaped_transform_list = []
    for node in node_list:
        if isinstance(node, pm.nt.Transform):
            if node.getShape():
                shaped_transform_list.append(node)
            
            if node.getParent():
                continue
            else:
                if isinstance(node, (pm.nt.Locator, pm.nt.Joint)):
                    # this may need to be revisited but it's normally reserved for nodes under another shaped transform.
                    continue
            parentable_object_list.append(node)
    return [parentable_object_list, shaped_transform_list]


def import_asset(asset_entry, as_model=True, skel_root_dict=None):
    """
    From a Model Shops Data class import and organize the asset.

    :param Asset asset_entry: MCAAsset data class which contains information on how to import and construct the scene hierarchy.
    :param bool as_model: If skinning should be kept or applied to the imported models.
    :param dict{str|Joint} skel_root_dict: A dictionary of rig asset ids to the joints they represent. When importing
        with skinning if the rig asset id matches the incoming asset it will be bound against it instead of deleted.
        If skinning is enabled but a root dict was not provided this will be generated during the import process.
    :return: The imported organization group, and the skel_root_dict
    :rtype: Transform, dict{str|Joint}
    """
    
    if skel_root_dict is None:
        skel_root_dict = {}
    
    # Create the Organize Group
    organization_group = create_asset_org_grp(asset_entry=asset_entry, delete_exiting=True)
    if not os.path.exists(asset_entry.sm_path):
        logger.warning(f'{asset_entry.name}: Cannot find the import path\n {asset_entry.sm_path} \nExiting!')
        return
    
    # Import the asset
    sm_path = asset_entry.sm_path
    sk_path = asset_entry.sk_path
    import_path = sk_path if os.path.exists(sk_path) else sm_path
    node_list = import_source_file(import_path)
    
    # organize the imported Nodes
    parentable_object_list, shaped_transform_list = get_imported_shape_nodes(node_list)
    if parentable_object_list:
        pm.parent(parentable_object_list, organization_group)
    
    # Get the Joints
    imported_joints = pm.ls(node_list, type=pm.nt.Joint)
    root_joint = None
    if imported_joints:
        root_joint = dag.get_absolute_parent(obj_node=imported_joints[0], node_type=pm.nt.Joint)
        #pm.parent(root_joint, organization_group)
    
    # if we don't want joints, remove them
    if as_model:
        pm.delete(imported_joints)
        attr_utils.set_attr_state(shaped_transform_list, False)
    
    else:
        # if we want the asset skinned lets try and do so.
        if imported_joints:
            # if it's already skinned because it came in with joints
            if skel_root_dict and asset_entry.skel_path in skel_root_dict:
                skin_utils.rebind_mesh_to_skel(shaped_transform_list, skel_root_dict[asset_entry.skel_path])
                pm.delete(imported_joints)
            elif skel_root_dict and 'default' in skel_root_dict:
                skin_utils.rebind_mesh_to_skel(shaped_transform_list, skel_root_dict['default'])
                pm.delete(imported_joints)
            else:
                # we do not have a skel root for this type of asset so lets register it and pass it down.
                imported_root = dag.get_absolute_parent(imported_joints[0], node_type=pm.nt.Joint)
                if not imported_root.hasAttr('asset_id'):
                    imported_root.addAttr('asset_id', dt='string')
                imported_root.setAttr('asset_id', asset_entry.asset_id)
                skel_root_dict[asset_entry.skel_path] = imported_root
                if 'default' not in skel_root_dict:
                    skel_root_dict['default'] = imported_root
        else:
            if asset_entry.skel_path not in skel_root_dict:
                # we didn't have a skeleton from import, so lets see if we have a root joint to bind against for this type.
                skel_path = asset_entry.skel_path
                if skel_path and os.path.exists(skel_path):
                    bind_root = skel_utils.import_skeleton(skel_path)
                    if bind_root:
                        bind_root.setAttr('asset_id', asset_entry.asset_id)
                        skel_root_dict[asset_entry.skel_path] = bind_root
            if asset_entry.skel_path in skel_root_dict:
                # we should almost never hit this. Either an asset will be skinned with an SK or there is a reason
                # we never exported it with skinning to being with.
                if asset_entry.skin_path:
                    asset_shop_copy_skn_weights(skel_root_dict[asset_entry.skel_path], shaped_transform_list, asset_entry.skin_path)
                else:
                    for node in shaped_transform_list:
                        # if we don't have a skin file bind them all to the root.
                        pm.skinCluster(node, [skel_root_dict[asset_entry.skel_path]], tsb=True,
                                       normalizeWeights=1, maximumInfluences=skin_utils.DEFAULT_MAX_INFLUENCES,
                                       obeyMaxInfluences=True, removeUnusedInfluence=False)
    
    # displaylayer_node = lists.get_first_in_list(pm.ls(f'{asset_entry.file_name}_dl', type=pm.nt.DisplayLayer))
    # if not displaylayer_node:
    #     displaylayer_node = pm.createDisplayLayer(n=f'{asset_entry.file_name}_dl', nr=True, e=True)
    # displaylayer_node.addMembers(organization_group)
    if as_model:
        source_ma_path = os.path.join(asset_entry.src_models_path, 'Maya', f'{asset_entry.file_name}.ma')
        fileio.touch_path(source_ma_path)
        pm.renameFile(source_ma_path)
    return organization_group, skel_root_dict


def asset_shop_copy_skn_weights(bind_root, node_list, skin_path):
    """
    From a save skin weights file, import and copy skins.

    :param Joint bind_root: The root joint of the skeleton our meshes will be bound to.
    :param list[Transform] node_list: A list of all shaped transforms that need skinning data.
    :param str skin_path: The path to a save skin weights file.
    """
    
    unbound_nodes = []
    for node in node_list:
        if isinstance(node, pm.nt.Transform):
            if node.getShape() and not skin_utils.find_related_skin_cluster(node):
                unbound_nodes.append(node)
            else:
                child_list = node.getChildren(type=pm.nt.Transform)
                for child_node in child_list:
                    if child_node.getShape() and not skin_utils.find_related_skin_cluster(child_node):
                        unbound_nodes.append(child_node)
    
    if not unbound_nodes:
        return
    
    if not os.path.exists(skin_path):
        for node in unbound_nodes:
            pm.skinCluster(node, [bind_root], tsb=True,
                           normalizeWeights=1, maximumInfluences=skin_utils.DEFAULT_MAX_INFLUENCES,
                           obeyMaxInfluences=True, removeUnusedInfluence=False)
    else:
        imported_skin_node_list = fbx_utils.import_fbx(skin_path)
        
        skinned_node_list = [node for node in imported_skin_node_list if
                             isinstance(node, pm.nt.Transform) and node.getShape() and
                             skin_utils.find_related_skin_cluster(node)]
        
        # bind to the imported skeleton
        # $TODO FSchorch Maybe make something that does the bind rebind at the same time?
        skin_utils.copy_skin_weights(skinned_node_list, unbound_nodes, match_influences=True)
        skin_utils.rebind_mesh_to_skel(unbound_nodes, bind_root)
        
        pm.delete(imported_skin_node_list)


def export_asset(node, asset_entry, update_skn=False, save_source=False, full_skeleton=False):
    """
    Export an asset (SM/SK) from the scene with optional skinning and skeleton export.

    Note: Organization groups use 'modelshop' attribute for backward compatibility with existing scenes.
    """
    """
    From a given node find all valid exportable groups and export them to their file paths.

    :param Transform node: A node in the export hierarchy.
    :param bool update_skn: If the skn file associated with this model should be updated.
    :param bool save_source: If a source .ma should be saved during export.
    :param bool register_assets: If the exported assets should be added to our helios asset registry.
    """
    
    # safety save.
    scene_utils.backup_scene('summoner_export')
    
    # collect all potential bind roots
    bind_root_list = skin_utils.get_all_hierarchy_bind_roots(node)
    bind_dict = {}
    
    deletable_roots = []
    for bind_root in bind_root_list:
        # make a bind dict for asset_id lookups.
        if bind_root.hasAttr('asset_id') and bind_root.getAttr('asset_id'):
            bind_dict[bind_root.getAttr('asset_id')] = bind_root
            if len(bind_root_list) == 1:
                # If we only have a single root also assign this as the default fallback.
                bind_dict['default'] = bind_root
        else:
            bind_dict['default'] = bind_root
    
    delete_root_after_export = False
    # Get Export Path
    export_path = asset_entry.full_path
    if not export_path:
        logger.warning('Cannot export asset.  No export path found!')
        return
    
    exportable_node_list = get_exportable_meshes(node)
    if not exportable_node_list:
        logger.warning('Cannot export asset.  No exportable nodes found!')
        return
    
    node_list = exportable_node_list[:]  # ?
    
    sm_export = True
    if len(node_list) == 1:
        if len(node_list[0].vtx) == 4:
            sm_export = False
    
    # if full_skeleton:
    #     joint_list = pm.ls(node_list, type=pm.nt.Joint)
    #     print(f'JOINT LIST: {joint_list}')
    #     if joint_list:
    #         root_joint = dag.get_absolute_parent(joint_list[0])
    #         if not root_joint.hasAttr('asset_id'):
    #             root_joint.addAttr('asset_id', dt='string')
    #         root_joint.setAttr('asset_id', asset_entry.asset_id)
    #         if os.path.exists(asset_entry.skel_path):
    #             fileio.touch_and_checkout(asset_entry.skel_path)
    #             skel_utils.export_skeleton(asset_entry.skel_path, root_joint)
    #         else:
    #             skel_utils.export_skeleton(asset_entry.skel_path, root_joint)
    #             perforce.p4_add(asset_entry.skel_path)
    
    # cleanup for skinning, we'll need valid binds to generate an SK file.
    if asset_entry.asset_id not in bind_dict and 'default' not in bind_dict:
        delete_root_after_export = True
        if asset_entry.asset_id:
            skel_path = asset_entry.skel_path
            bind_root = None
            if skel_path and os.path.exists(skel_path):
                bind_root = skel_utils.import_skeleton(skel_path)
            else:
                logger.warning(f'{asset_entry.asset_id} was not found in the asset list. '
                               f'We will attempt to recover a skeleton from the SK file.')
                sk_path = asset_entry.sk_path
                if os.path.exists(sk_path):
                    imported_nodes = fbx_utils.import_fbx(sk_path)
                    imported_joint_list = pm.ls(imported_nodes, type=pm.nt.Joint)
                    if imported_joint_list:
                        pm.delete(set(imported_nodes).difference(set(imported_joint_list)))
                        bind_root = dag.get_absolute_parent(imported_joint_list[0])
                else:
                    logger.warning(f'Unable to recover a skeleton from an SK file. '
                                   f'Only the SM will be exported.')
            if bind_root:
                deletable_roots.append(bind_root)
                bind_dict[asset_entry.asset_id] = bind_root
    
    if asset_entry.asset_id in bind_dict:
        bind_root = bind_dict[asset_entry.asset_id]
        if asset_entry and os.path.exists(asset_entry.skel_path):
            # Reset rotations so we don't export accidental model changes.
            skel_utils.restore_skeleton_bindpose(asset_entry.skel_path, bind_root)
        else:
            for joint_node in bind_root.listRelatives(ad=True, type=pm.nt.Joint):
                # Reset rotations so we don't export accidental model changes.
                try:
                    joint_node.r.set([0, 0, 0])
                except:
                    pass
        
        # if we neither had a bind root nor were able to import one continue. Some assets might only be static
        # meshes, for instance anything working with Nanite.
        copy_skins_path = None
        if os.path.exists(asset_entry.skin_path):
            # try our local skn first
            copy_skins_path = asset_entry.skin_path
        else:
            # if we don't have a local skin path try our rig's sk.
            if asset_entry:
                copy_skins_path = asset_entry.sk_path
        if copy_skins_path:
            asset_shop_copy_skn_weights(bind_dict[asset_entry.asset_id], node_list, copy_skins_path)
            node_list += [bind_dict[asset_entry.asset_id]]
            if asset_entry and os.path.exists(asset_entry.skel_path):
                # Importing an old skel can overwrite markup so restore it. Likely a bug with FBX importing.
                skel_utils.restore_skeleton_markup(asset_entry.skel_path, bind_dict[asset_entry.asset_id])
    elif 'default' in bind_dict:
        bind_root = bind_dict['default']
        
        for joint_node in bind_root.listRelatives(ad=True, type=pm.nt.Joint):
            # Reset rotations so we don't export accidental model changes.
            for x in attr_utils.ROTATION_ATTRS:
                joint_node.disconnectAttr(x)
                joint_node.setAttr(x, 0)
        
        node_list += [bind_dict['default']]
    
    # time to export, first a sk, an options skn, and a sm.
    pm.parent(exportable_node_list, None)
    
    # we will always have an SM, but not always an SK.
    sm_path = asset_entry.sm_path
    skn_path = asset_entry.skin_path
    sk_path = asset_entry.sk_path
    source_ma_path = os.path.join(asset_entry.src_models_path, 'Maya', f'{asset_entry.file_name}.ma')
    
    do_triangulate = fbx_utils.FBXExportTriangulate(q=True)
    fbx_utils.FBXExportTriangulate(v=False)
    root_joint = None
    if bind_dict:
        if asset_entry.asset_id in bind_dict or 'default' in bind_dict:
            # only export the SK if we have an actual skeleton.
            fileio.touch_and_checkout(sk_path)
            joint_list = pm.ls(node_list, type=pm.nt.Joint)
            if not os.path.exists(asset_entry.skel_path) or full_skeleton:
                # If we have no skel registered with this asset export one before we trim joints.
                # Filter to Joint type: when the bind skeleton is parented under the org group,
                # walking parents without filtering would return the group instead of the root joint.
                root_joint = dag.get_absolute_parent(joint_list[0], node_type=pm.nt.Joint)
                if not root_joint.hasAttr('asset_id'):
                    root_joint.addAttr('asset_id', dt='string')
                root_joint.setAttr('asset_id', asset_entry.asset_id)
                if os.path.exists(asset_entry.skel_path):
                    fileio.touch_and_checkout(asset_entry.skel_path)
                    skel_utils.export_skeleton(asset_entry.skel_path, root_joint)
                else:
                    skel_utils.export_skeleton(asset_entry.skel_path, root_joint)
                    perforce.p4_add(asset_entry.skel_path)
                fileio.touch_path(asset_entry.skel_path)
                skel_utils.export_skeleton(asset_entry.skel_path, root_joint)
            if joint_list:
                _trim_exportable_joints(dag.get_absolute_parent(joint_list[0], node_type=pm.nt.Joint))
            fbx_utils.export_fbx(sk_path, node_list)
            if update_skn and sm_export:
                fileio.touch_path(skn_path, True)
                shutil.copy2(sk_path, skn_path)
    
    if sm_export:
        with pm.UndoChunk():
            if asset_entry.asset_id in bind_dict:
                pm.delete(bind_dict[asset_entry.asset_id])
            if 'default' in bind_dict and pm.objExists(bind_dict['default']):
                pm.delete(bind_dict['default'])
            if save_source:
                fileio.touch_path(source_ma_path)
                scene_utils.save_as(source_ma_path)
            fileio.touch_path(sm_path)
            fbx_utils.export_fbx(sm_path, exportable_node_list)
        
        pm.undo()
    pm.parent(exportable_node_list, node)
    fbx_utils.FBXExportTriangulate(v=do_triangulate)
    
    if delete_root_after_export and deletable_roots:
        pm.delete(deletable_roots)

    root_joint = joint_utils.get_root_joint_from_list(node_list)
    if root_joint and full_skeleton:
        skel_utils.import_merge_skeleton(asset_entry.skel_path, root_joint)


def get_exportable_meshes(export_group):
    """
    From a valid export group find all exportable meshes. This is used during SM/SK exports.

    :param Transform export_group: A group that represents a valid exportable group.
    :return: A list of all valid shaped transforms or groups containing valid shaped transforms.
    :rtype: list[Transform]
    """
    
    exportable_node_list = []
    blendshape_targets = []
    for node in export_group.getChildren(type=pm.nt.Transform):
        if node.hasAttr('modelshop') or not pm.objExists(node):
            continue
        # Joints that live under the org group (e.g. a parented bind skeleton) are handled
        # separately via bind_dict. Excluding them here prevents stale references in
        # exportable_node_list after the skeleton is deleted between SK and SM export.
        if isinstance(node, pm.nt.Joint):
            continue

        # Take all objects not marked up with Helios' markup. Since we can have nested exports we want to make sure
        # we're only grabbing one representative of it at a time.
        node_shape = node.getShape()
        if node_shape:
            blend_node = lists.get_first_in_list(node_shape.listConnections(type=pm.nt.BlendShape))
            if blend_node:
                blendshape_targets += pm.blendShape(blend_node, q=True, target=True)
        
        node_children = node.getChildren()
        if node_children:
            # We're recursively running this to find and delete blendshape targets. They're restored on import.
            # They become embedded in the FBX file.
            get_exportable_meshes(node)
        
        exportable_node_list.append(node)
    
    exportable_node_list = [x for x in exportable_node_list if x not in blendshape_targets]
    pm.delete(blendshape_targets)
    return exportable_node_list


def _trim_exportable_joints(skel_root):
    """
    Trim null joints before exporting.

    :param Joint skel_root: Skeletal root joint.
    """
    
    deletable_joints = [x for x in pm.listRelatives(skel_root, ad=True, type=pm.nt.Joint) if 'null' in x.name()]
    pm.delete(deletable_joints)






