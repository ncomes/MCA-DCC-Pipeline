"""
Module that has Rigging Tools.
"""

# System global imports
import os
# Software specific imports
import pymel.core as pm
# Qt imports
# MCA python imports
from mca.common import log
from mca.mya.pyqt import mayawindows, dialogs
from mca.mya.rigging import skel_utils, joint_utils
from mca.mya.utils import optionvars, attr_utils
from mca.mya.modifiers import ma_decorators


logger = log.MCA_LOGGER


class RiggingToolsOptionVars(optionvars.MCAOptionVars):
    """
    This handles keeping track of Summoner's last UI values to be restored or used during various UI functions.
    """

    MCARiggingToolsAimPos = {'default_value': False, 'docstring': 'Last opened category in Summoner.'}
    MCARiggingToolsUpPos = {'default_value': False, 'docstring': 'Last selected rig in Summoner.'}
    MCARiggingToolsAimX = {'default_value': True, 'docstring': 'Aim Constraint, Aim Vector.'}
    MCARiggingToolsAimY = {'default_value': False, 'docstring': 'Aim Constraint, Aim Vector.'}
    MCARiggingToolsAimZ = {'default_value': False, 'docstring': 'Aim Constraint, Aim Vector.'}
    MCARiggingToolsUpX = {'default_value': False, 'docstring': 'Aim Constraint, Aim Vector.'}
    MCARiggingToolsUpY = {'default_value': True, 'docstring': 'Aim Constraint, Aim Vector.'}
    MCARiggingToolsUpZ = {'default_value': False, 'docstring': 'Aim Constraint, Aim Vector.'}
    MCARiggingToolsSibling = {'default_value': False, 'docstring': 'Aim Constraint, Aim Vector.'}


class RiggingTools(mayawindows.MCAMayaWindow):
    VERSION = '1.0.0'

    def __init__(self):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'rigging_tools.ui')
        super().__init__(title='Rigging Tools',
                         ui_path=ui_path,
                         version=RiggingTools.VERSION)

        self.setMinimumSize(405, 650)
        print('Starting Rigging Tools...')
        self.optionvars = RiggingToolsOptionVars()

        self.ui.aim_pos_checkBox.setChecked(self.optionvars.MCARiggingToolsAimPos)
        self.ui.up_pos_checkBox.setChecked(self.optionvars.MCARiggingToolsUpPos)
        self.ui.aim_x_checkBox.setChecked(self.optionvars.MCARiggingToolsAimX)
        self.ui.aim_y_checkBox.setChecked(self.optionvars.MCARiggingToolsAimY)
        self.ui.aim_z_checkBox.setChecked(self.optionvars.MCARiggingToolsAimZ)
        self.ui.up_x_checkBox.setChecked(self.optionvars.MCARiggingToolsUpX)
        self.ui.up_y_checkBox.setChecked(self.optionvars.MCARiggingToolsUpY)
        self.ui.up_z_checkBox.setChecked(self.optionvars.MCARiggingToolsUpZ)
        self.ui.zero_checkBox.setChecked(self.optionvars.MCARiggingToolsSibling)

        # ==============================
        # Signals
        # ==============================
        self.ui.planar_pushButton.clicked.connect(self.make_planar_clicked)
        self.ui.align_pushButton.clicked.connect(self.orient_joints_clicked)
        self.ui.twist_pushButton.clicked.connect(self.twist_clicked)
        self.ui.left_mirror_pushButton.clicked.connect(self.mirror_left_clicked)
        self.ui.set_markup_pushButton.clicked.connect(self.set_markup_clicked)
        self.ui.rename_pushButton.clicked.connect(self.rename_joint_chain_clicked)
        self.ui.remove_markup_pushButton.clicked.connect(self.remove_markup_clicked)

    # ==============================
    # Slots
    # ==============================
    def mirror_left_clicked(self):

        joints = pm.mirrorJoint(mirrorYZ=True, mirrorBehavior=True, searchReplace = ("_l", "_r"))
        joints = [pm.PyNode(x) for x in joints]
        [x.skelSide.set('right') for x in joints if x.hasAttr('skelSide')]

    @ma_decorators.undo_decorator
    def make_planar_clicked(self):
        selection = pm.selected()
        if len(selection) == 3:
            planar_chain = skel_utils.make_planar_chain(selection)
            for joint_node, planar_node in zip(selection, planar_chain):
                joint_children = joint_node.getChildren()
                if joint_children:
                    pm.parent(joint_children, None)
                pm.delete(pm.parentConstraint(planar_node, joint_node))
                if joint_children:
                    pm.parent(joint_children, joint_node)
            pm.makeIdentity(selection, apply=True, t=0, r=1, s=0, n=0)
            pm.delete(planar_chain)
        else:
            dialogs.error_prompt('Selection Error', 'Exactly 3 objects must be selected to make them planar.')

        self.update_optionvars()

    @ma_decorators.undo_decorator
    def twist_clicked(self):
        joints = pm.selected()
        if len(joints) < 3:
            return
        parent_joint = joints.pop(0)
        child_joint = joints.pop(0)
        skel_utils.position_twist_joints(joints, parent_joint, child_joint)

        self.update_optionvars()

    def orient_joints_clicked(self):
        joints = pm.selected()
        if len(joints) < 2:
            return

        self.orient_joints(joints[0], joints[1])
        aim_pos = 1
        up_pos = 1
        if not self.ui.aim_pos_checkBox.isChecked():
            aim_pos = -1
        if not self.ui.up_pos_checkBox.isChecked():
            up_pos = -1
        aim_x = int(self.ui.aim_x_checkBox.isChecked()) * aim_pos
        aim_y = int(self.ui.aim_y_checkBox.isChecked()) * aim_pos
        aim_z = int(self.ui.aim_z_checkBox.isChecked()) * aim_pos

        up_x = int(self.ui.up_x_checkBox.isChecked()) * up_pos
        up_y = int(self.ui.up_y_checkBox.isChecked()) * up_pos
        up_z = int(self.ui.up_z_checkBox.isChecked()) * up_pos

        siblings = self.ui.zero_checkBox.isChecked()

        self.orient_joints(parent_joint=joints[0],
                           child_joint=joints[1],
                           zero_siblings=siblings,
                           aim_x=aim_x,
                           aim_y=aim_y,
                           aim_z=aim_z,
                           up_x=up_x,
                           up_y=up_y,
                           up_z=up_z)

        self.update_optionvars()

    @ma_decorators.undo_decorator
    def orient_joints(self,
                      parent_joint,
                      child_joint,
                      zero_siblings=False,
                      aim_x=1,
                      aim_y=0,
                      aim_z=0,
                      up_x=0,
                      up_y=1,
                      up_z=0):

        pm.parent(child_joint, w=True)

        loc = pm.spaceLocator(n='DELETE_ME_LOC')
        pm.delete(pm.parentConstraint(parent_joint, loc, w=1))
        pm.move(loc, (0, 30, 0), r=True, os=True, wd=True)

        aim = pm.aimConstraint(child_joint,
                               parent_joint,
                               offset=(0, 0, 0),
                               weight=1,
                               aimVector=(aim_x, aim_y, aim_z),
                               upVector=(up_x, up_y, up_z),
                               worldUpType="object",
                               worldUpObject=loc)

        pm.delete([aim, loc])

        pm.parent(child_joint, parent_joint)
        pm.makeIdentity(parent_joint, apply=True, t=True, r=True, s=True, n=False, pn=True)
        if zero_siblings:
            siblings = child_joint.getChildren()
            if not siblings:
                child_joint.jointOrient.set(0, 0, 0)

    def update_optionvars(self):
        self.optionvars.MCARiggingToolsAimPos = self.ui.aim_pos_checkBox.isChecked()
        self.optionvars.MCARiggingToolsUpPos = self.ui.up_pos_checkBox.isChecked()
        self.optionvars.MCARiggingToolsAimX = self.ui.aim_x_checkBox.isChecked()
        self.optionvars.MCARiggingToolsAimY = self.ui.aim_y_checkBox.isChecked()
        self.optionvars.MCARiggingToolsAimZ = self.ui.aim_z_checkBox.isChecked()
        self.optionvars.MCARiggingToolsUpX = self.ui.up_x_checkBox.isChecked()
        self.optionvars.MCARiggingToolsUpY = self.ui.up_y_checkBox.isChecked()
        self.optionvars.MCARiggingToolsUpZ = self.ui.up_z_checkBox.isChecked()
        self.optionvars.MCARiggingToolsSibling = self.ui.zero_checkBox.isChecked()

    def set_markup_clicked(self):
        joints = pm.selected(type=pm.nt.Joint)
        if not joints:
            return

        region = str(self.ui.region_lineEdit.text()).strip()
        side = str(self.ui.side_lineEdit.text()).strip()

        if len(joints) == 1 and not self.ui.twist_checkBox.isChecked():
            self.add_markup_attrs(joint=joints[0], start=True, end=True)
            self.set_markup_attrs(joint=joints[0], region=region, side=side, start=True, end=True)

        elif len(joints) == 2 and not self.ui.twist_checkBox.isChecked():
            parent_joint = joints[0]
            child_joint = joints[-1]
            joint_hierarchy = self.get_joint_hierarchy(joints)

            # Parent Joint
            self.add_markup_attrs(parent_joint, start=True)
            self.set_markup_attrs(parent_joint, region=region, side=side, start=True)

            # Child Joint
            self.add_markup_attrs(child_joint, end=True)
            self.set_markup_attrs(child_joint, region=region, side=side, end=True)

            for joint in joint_hierarchy:
                self.add_markup_attrs(joint)
                self.set_markup_attrs(joint, region=region, side=side)
        elif self.ui.twist_checkBox.isChecked():
            self.ui.anim_checkBox.setChecked(False)
            self.ui.sk_checkBox.setChecked(True)

            for joint in joints:
                self.add_markup_attrs(joint, twist=True)
                self.set_markup_attrs(joint, region=region, side=side)

    def add_markup_attrs(self, joint, start=False, end=False, twist=False):
        self.remove_markup(joints=joint)
        if start:
            joint.addAttr('chainStart', dt='string')
        if end:
            joint.addAttr('chainEnd', dt='string')
        if twist:
            joint.addAttr('chainTwist', dt='string')
        joint.addAttr('skelRegion', dt='string')
        joint.addAttr('skelSide', dt='string')
        joint.addAttr('skExport', at='bool')
        joint.addAttr('animationExport', at='bool')
        joint.addAttr('skelTwist', at='bool')

    def set_markup_attrs(self, joint, region, side, start=False, end=False, twist=False):
        if start:
            joint.chainStart.set(region)
        if end:
            joint.chainEnd.set(region)
        if twist:
            joint.chainTwist.set(region)
        joint.skelRegion.set(region)
        joint.skelSide.set(side)
        joint.skExport.set(self.ui.sk_checkBox.isChecked())
        joint.animationExport.set(self.ui.anim_checkBox.isChecked())
        joint.skelTwist.set(self.ui.twist_checkBox.isChecked())

    @ma_decorators.undo_decorator
    def rename_joint_chain_clicked(self):
        joints = pm.selected(type=pm.nt.Joint)
        if not joints:
            return
        name = str(self.ui.rename_lineEdit.text()).strip()

        if len(joints) == 1:
            joints[0].rename(name)

        elif len(joints) == 2:
            joint_hierarchy = self.get_joint_hierarchy(joints)

            for x, joint in enumerate(joint_hierarchy):
                if x < 100:
                    joint.rename(f'{name}_{str(x + 1).zfill(2)}')
                else:
                    joint.rename(f'{name}_{str(x + 1).zfill(3)}')
        else:
            for x, joint in enumerate(joints):
                if x < 100:
                    joint.rename(f'{name}_{str(x + 1).zfill(2)}')
                else:
                    joint.rename(f'{name}_{str(x + 1).zfill(3)}')

    def get_joint_hierarchy(self, joints):
        parent_joint = joints[0]
        child_joint = joints[-1]
        joint_hierarchy = []
        full_joint_hierarchy = joint_utils.get_joint_hierarchy(parent_joint)
        for joint in full_joint_hierarchy:
            if joint.nodeName() == parent_joint.nodeName():
                continue
            if joint.nodeName() == child_joint.nodeName():
                break
            joint_hierarchy.append(joint)
        return joint_hierarchy

    def remove_markup_clicked(self):
        joints = pm.selected(type=pm.nt.Joint)
        if not joints:
            return
        if not joints:
            logger.warning('No joints selected')
            return
        self.remove_markup(joints=joints)


    def remove_markup(self, joints):
        if not isinstance(joints, (tuple, list)):
            joints = [joints]
        if len(joints) == 2:
            joint_hierarchy = self.get_joint_hierarchy(joints)
            attr_utils.purge_user_defined_attrs(joint_hierarchy)
        elif len(joints) > 2:
            attr_utils.purge_user_defined_attrs(joints)
        else:
            attr_utils.purge_user_defined_attrs(joints)
