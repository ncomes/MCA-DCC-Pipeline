"""
Module Asset Registry Data
"""

# System global imports
import os

# software specific imports
import pymel.core as pm
# MCA python imports
from mca.common import log
from mca.common.paths import paths, path_utils
from mca.common.assetlist import get_asset_manager, unified_registry
from mca.common.pyqt.pygui import qtwidgets, qtcore
from mca.common.pyqt import common_windows
from mca.common.resources import resources
from mca.common.tools.assetregister import asset_ui_data, unified_register

from mca.mya.utils import camera_utils, optionvars
from mca.mya.pyqt import dialogs
from mca.mya.rigging import skel_utils, rig_utils
from mca.mya.tools.summoner import summoner_utils
from mca.mya.tools.summoner import variant_api

logger = log.MCA_LOGGER
# Module-level cache removed - we now get fresh references to avoid stale data


def summoner_window(widget):
    """
    Walk up from a tab widget to the Summoner window that owns it.

    The trees sit inside a container QWidget, so the window is a grandparent
    rather than a parent.

    :param widget: Any widget inside the Summoner.
    :return: The window, or None when the tree is parented somewhere else.
    """

    node = widget
    while node is not None:
        if hasattr(node, 'refresh_all'):
            return node
        node = node.parent()
    return None


class ModelShopCharOptionVars(optionvars.MCAOptionVars):
    """
    This handles keeping track of The Model Shops UI values to be restored or used during various UI functions.
    """

    ModelShopCharFullSkel = {'default_value': False, 'docstring': 'If the full skeleton should be merged in.'}
    ModelShopCharModelOnly = {'default_value': False, 'docstring': 'Only the model should be imported.'}
    ModelShopCharSKOnly = {'default_value': False, 'docstring': 'SK will be imported'}
    ModelShopSknUpd = {'default_value': False, 'docstring': 'Skinning will be exported and saved.'}
    ModelShopCharExpMa = {'default_value': False, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopCharSubCat = {'default_value': 0, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopCharExpSkel = {'default_value': 0, 'docstring': 'Will export and update the skeleton data.'}
    ModelShopRigsOnly = {'default_value': False, 'docstring': 'Will export and update the skeleton data.'}

    ModelShopVehFullSkel = {'default_value': False, 'docstring': 'If the full skeleton should be merged in.'}
    ModelShopVehModelOnly = {'default_value': False, 'docstring': 'Only the model should be imported.'}
    ModelShopVehSKOnly = {'default_value': False, 'docstring': 'SK will be imported'}
    ModelShopVehSknUpd = {'default_value': False, 'docstring': 'Skinning will be exported and saved.'}
    ModelShopVehExpMa = {'default_value': False, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopVehSubCat = {'default_value': 0, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopVehExpSkel = {'default_value': 0, 'docstring': 'Will export and update the skeleton data.'}
    ModelShopVehRigsOnly = {'default_value': False, 'docstring': 'Will export and update the skeleton data.'}

    ModelShopPropFullSkel = {'default_value': False, 'docstring': 'If the full skeleton should be merged in.'}
    ModelShopPropModelOnly = {'default_value': False, 'docstring': 'Only the model should be imported.'}
    ModelShopPropSKOnly = {'default_value': False, 'docstring': 'SK will be imported'}
    ModelShopPropSknUpd = {'default_value': False, 'docstring': 'Skinning will be exported and saved.'}
    ModelShopPropExpMa = {'default_value': False, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopPropSubCat = {'default_value': 0, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopPropExpSkel = {'default_value': 0, 'docstring': 'Will export and update the skeleton data.'}
    ModelShopPropRigsOnly = {'default_value': False, 'docstring': 'Will export and update the skeleton data.'}

    ModelShopWeapFullSkel = {'default_value': False, 'docstring': 'If the full skeleton should be merged in.'}
    ModelShopWeapModelOnly = {'default_value': False, 'docstring': 'Only the model should be imported.'}
    ModelShopWeapSKOnly = {'default_value': False, 'docstring': 'SK will be imported'}
    ModelShopWeapSknUpd = {'default_value': False, 'docstring': 'Skinning will be exported and saved.'}
    ModelShopWeapExpMa = {'default_value': False, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopWeapSubCat = {'default_value': 0, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopWeapExpSkel = {'default_value': 0, 'docstring': 'Will export and update the skeleton data.'}
    ModelShopWeapRigsOnly = {'default_value': False, 'docstring': 'Will export and update the skeleton data.'}

    ModelShopHeadsFullSkel = {'default_value': False, 'docstring': 'If the full skeleton should be merged in.'}
    ModelShopHeadsModelOnly = {'default_value': False, 'docstring': 'Only the model should be imported.'}
    ModelShopHeadsSKOnly = {'default_value': False, 'docstring': 'SK will be imported'}
    ModelShopHeadsSknUpd = {'default_value': False, 'docstring': 'Skinning will be exported and saved.'}
    ModelShopHeadsExpMa = {'default_value': False, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopHeadsSubCat = {'default_value': 0, 'docstring': 'Will save the file as the source Maya file.'}
    ModelShopHeadsExpSkel = {'default_value': 0, 'docstring': 'Will export and update the skeleton data.'}
    ModelShopHeadsRigsOnly = {'default_value': False, 'docstring': 'Will export and update the skeleton data.'}


# ui_name → set of legacy optionvar attribute suffixes for each tracked field.
# Only the original five categories have persisted optionvars; manifest-driven
# categories (Faces, Cameras, ...) fall through to in-memory defaults via
# _UNTRACKED_UI_DEFAULTS below. Adding persisted state for a new category means
# adding ModelShop<Cat><Field> attrs to ModelShopCharOptionVars and a row here.
_LEGACY_OPTIONVAR_SUFFIX = {
    'char':     {'full_skel': 'ModelShopCharFullSkel',  'model_only': 'ModelShopCharModelOnly',
                 'sk_model': 'ModelShopCharSKOnly',     'skn_update': 'ModelShopSknUpd',
                 'export_ma': 'ModelShopCharExpMa',     'sub_category': 'ModelShopCharSubCat',
                 'exp_skel': 'ModelShopCharExpSkel',    'as_rig': 'ModelShopRigsOnly'},
    'vehicles': {'full_skel': 'ModelShopVehFullSkel',   'model_only': 'ModelShopVehModelOnly',
                 'sk_model': 'ModelShopVehSKOnly',      'skn_update': 'ModelShopVehSknUpd',
                 'export_ma': 'ModelShopVehExpMa',      'sub_category': 'ModelShopVehSubCat',
                 'exp_skel': 'ModelShopVehExpSkel',     'as_rig': 'ModelShopVehRigsOnly'},
    'props':    {'full_skel': 'ModelShopPropFullSkel',  'model_only': 'ModelShopPropModelOnly',
                 'sk_model': 'ModelShopPropSKOnly',     'skn_update': 'ModelShopPropSknUpd',
                 'export_ma': 'ModelShopPropExpMa',     'sub_category': 'ModelShopPropSubCat',
                 'exp_skel': 'ModelShopPropExpSkel',    'as_rig': 'ModelShopPropRigsOnly'},
    'weapons':  {'full_skel': 'ModelShopWeapFullSkel',  'model_only': 'ModelShopWeapModelOnly',
                 'sk_model': 'ModelShopWeapSKOnly',     'skn_update': 'ModelShopWeapSknUpd',
                 'export_ma': 'ModelShopWeapExpMa',     'sub_category': 'ModelShopWeapSubCat',
                 'exp_skel': 'ModelShopWeapExpSkel',    'as_rig': 'ModelShopWeapRigsOnly'},
    'heads':    {'full_skel': 'ModelShopHeadsFullSkel', 'model_only': 'ModelShopHeadsModelOnly',
                 'sk_model': 'ModelShopHeadsSKOnly',    'skn_update': 'ModelShopHeadsSknUpd',
                 'export_ma': 'ModelShopHeadsExpMa',    'sub_category': 'ModelShopHeadsSubCat',
                 'exp_skel': 'ModelShopHeadsExpSkel',   'as_rig': 'ModelShopHeadsRigsOnly'},
}

# Safe defaults returned by getters when the ui_name has no persisted optionvars.
# These match the type that Qt expects (bool for checkboxes, int for combo index).
_UNTRACKED_UI_DEFAULTS = {
    'full_skel': False, 'model_only': False, 'sk_model': False, 'skn_update': False,
    'export_ma': False, 'sub_category': 0, 'exp_skel': 0, 'as_rig': False,
}


class ModelShopAllOptionvars:
    def __init__(self, ui_name):
        self.ui_name = ui_name

        self.optionvars = ModelShopCharOptionVars()
        # In-memory fallback for categories without persisted optionvars. Lives only
        # for the lifetime of this widget, but that's fine — picking sub-category
        # state has to survive between actions in one session, not across sessions,
        # and adding persisted state is a one-line addition above.
        self._scratch = dict(_UNTRACKED_UI_DEFAULTS)

    def _legacy_attr(self, field):
        """Returns the ModelShopCharOptionVars attribute name for this ui_name's
        ``field``, or None if the ui_name isn't one of the legacy five."""

        return _LEGACY_OPTIONVAR_SUFFIX.get(self.ui_name, {}).get(field)

    def _get(self, field):
        """Generic getter shared by all per-field properties."""

        attr = self._legacy_attr(field)
        if attr is not None:
            return getattr(self.optionvars, attr)
        return self._scratch.get(field, _UNTRACKED_UI_DEFAULTS[field])

    def _set(self, field, value):
        """Generic setter shared by all per-field properties."""

        attr = self._legacy_attr(field)
        if attr is not None:
            setattr(self.optionvars, attr, value)
        else:
            self._scratch[field] = value

    @property
    def full_skel(self): return self._get('full_skel')
    @full_skel.setter
    def full_skel(self, value): self._set('full_skel', value)

    @property
    def model_only(self): return self._get('model_only')
    @model_only.setter
    def model_only(self, value): self._set('model_only', value)

    @property
    def sk_model(self): return self._get('sk_model')
    @sk_model.setter
    def sk_model(self, value): self._set('sk_model', value)

    @property
    def skn_update(self): return self._get('skn_update')
    @skn_update.setter
    def skn_update(self, value): self._set('skn_update', value)

    @property
    def export_ma(self): return self._get('export_ma')
    @export_ma.setter
    def export_ma(self, value): self._set('export_ma', value)

    @property
    def sub_category(self): return self._get('sub_category')
    @sub_category.setter
    def sub_category(self, value): self._set('sub_category', value)

    @property
    def exp_skel(self): return self._get('exp_skel')
    @exp_skel.setter
    def exp_skel(self, value): self._set('exp_skel', value)

    @property
    def as_rig(self): return self._get('as_rig')
    @as_rig.setter
    def as_rig(self, value): self._set('as_rig', value)


class AssetShopCharTreeWidget(common_windows.MCAMainWindow):
    VERSION = '1.0.1'

    def __init__(self, gear_category, categories, ui_name, parent=None):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'summoner_asset_tree.ui')
        super().__init__(title='Summoner Asset Tree',
                            ui_path=ui_path,
                            show_window=False,
                            version=self.VERSION,
                            parent=parent)

        self.gear_category = gear_category
        self.categories = categories
        self.ui_name = ui_name

        self.optionvars = ModelShopAllOptionvars(self.ui_name)

        self.char_tree = qtwidgets.QTreeWidget(self)
        # The header names the category this tree is showing. It used to say "Characters"
        # on every tab, so the Props tab claimed to be listing characters.
        self.char_tree.setHeaderLabels([categories[0] if categories else 'Assets'])
        self.ui.char_tree_layout.addWidget(self.char_tree)

        self.asset_items = []
        self.variant_items = []
        self.tree_item = None

        self.on_startup()

        ###################################
        # Signals
        ###################################
        self.char_tree.setContextMenuPolicy(qtcore.Qt.CustomContextMenu)
        self.char_tree.customContextMenuRequested.connect(self.show_context_menu)

        self.char_tree.itemSelectionChanged.connect(self.get_selected_item)
        self.char_tree.itemDoubleClicked.connect(self.import_clicked)
        self.ui.import_pushButton.clicked.connect(self.import_clicked)
        self.ui.new_icon_pushButton.clicked.connect(self.create_image_clicked)
        self.ui.full_skel_checkBox.clicked.connect(self.skel_chbx)
        self.ui.as_rig_checkBox.clicked.connect(self.rig_chbx)
        self.ui.model_checkBox.clicked.connect(self.model_chbx)
        self.ui.sk_checkBox.clicked.connect(self.sk_chbx)
        self.ui.reg_new_pushButton.clicked.connect(self.register_new_asset_clicked)
        self.ui.org_grp_pushButton.clicked.connect(self.create_org_group)
        self.ui.remove_pushButton.clicked.connect(self.remove_entry)
        self.ui.upd_skn_checkBox.clicked.connect(self.update_optionvars)
        self.ui.ma_checkBox.clicked.connect(self.update_optionvars)
        self.ui.export_pushButton.clicked.connect(self.export_selected_clicked)
        self.ui.sub_cats_comboBox.currentIndexChanged.connect(self.add_to_tree)

    ###################################
    # Slots
    ###################################
    def on_startup(self):
        """
        Runs at startup.
        """

        self.block_signals()
        self.populate_sub_categories()
        try:
            self.ui.sub_cats_comboBox.setCurrentIndex(self.optionvars.sub_category)
        except:
            self.ui.sub_cats_comboBox.setCurrentIndex(0)
        self.add_to_tree()
        self.ui.full_skel_checkBox.setChecked(self.optionvars.full_skel)
        self.ui.model_checkBox.setChecked(self.optionvars.model_only)
        self.ui.sk_checkBox.setChecked(self.optionvars.sk_model)
        self.ui.ma_checkBox.setChecked(self.optionvars.export_ma)
        self.ui.upd_skn_checkBox.setChecked(self.optionvars.skn_update)
        self.ui.upd_skel_checkBox.setChecked(self.optionvars.exp_skel)
        self.ui.as_rig_checkBox.setChecked(self.optionvars.as_rig)
        self.block_signals(False)

    def block_signals(self, block=True):
        """
        Blocks signals to the QWidgets.

        :param bool block: If True, will block the signals to the QWidgets.
        """

        self.ui.full_skel_checkBox.blockSignals(block)
        self.ui.model_checkBox.blockSignals(block)
        self.ui.sk_checkBox.blockSignals(block)
        self.ui.ma_checkBox.blockSignals(block)
        self.ui.upd_skn_checkBox.blockSignals(block)
        self.ui.sub_cats_comboBox.blockSignals(block)
        self.ui.as_rig_checkBox.blockSignals(block)

    def skel_chbx(self):
        """
        Sets the skeleton checkbox.
        """

        self.ui.model_checkBox.setChecked(False)
        self.ui.sk_checkBox.setChecked(False)
        self.ui.as_rig_checkBox.setChecked(False)
        self.update_optionvars()

    def model_chbx(self):
        """
        Sets the model only checkbox.
        """

        self.ui.full_skel_checkBox.setChecked(False)
        self.ui.sk_checkBox.setChecked(False)
        self.ui.as_rig_checkBox.setChecked(False)
        self.update_optionvars()

    def sk_chbx(self):
        """
        Sets the update skinning checkbox.
        """

        self.ui.model_checkBox.setChecked(False)
        self.ui.full_skel_checkBox.setChecked(False)
        self.ui.as_rig_checkBox.setChecked(False)
        self.update_optionvars()

    def rig_chbx(self):
        """
        Sets the update skinning checkbox.
        """

        self.ui.model_checkBox.setChecked(False)
        self.ui.full_skel_checkBox.setChecked(False)
        self.ui.sk_checkBox.setChecked(False)
        self.update_optionvars()

    def create_org_group(self):
        """
        Creates the Org Group to export model assets.  This group organizes the scene.
        """

        if not self.tree_item:
            return

        group = summoner_utils.get_org_group(asset_entry=self.tree_item.asset, attr_name='modelshop')
        if group:
            result = dialogs.question_prompt(title='Create New Group?', text=f'Create a new organization group for: \n"{self.tree_item.asset.name}"?'
                                                                             f'\nThis will delete the existing group!')
            if result != 'Yes':
                return
        summoner_utils.create_asset_org_grp(asset_entry=self.tree_item.asset, attr_name='modelshop', delete_exiting=True)

    def remove_entry(self):
        """
        Removes an asset entry from the asset list.
        """

        if not self.tree_item:
            return

        result = dialogs.question_prompt(title='Remove Entry', text=f'Remove "{self.tree_item.asset.name}" from the asset list?'
                                                                         f'\nThis will delete/remove the asset from the registry!')
        if result != 'Yes':
            return

        self.tree_item.asset.remove_from_assetlist()
        self.populate_sub_categories()
        self.add_to_tree()

    def update_optionvars(self):
        self.optionvars.full_skel = self.ui.full_skel_checkBox.isChecked()
        self.optionvars.model_only = self.ui.model_checkBox.isChecked()
        self.optionvars.sk_model = self.ui.sk_checkBox.isChecked()
        self.optionvars.export_ma = self.ui.ma_checkBox.isChecked()
        self.optionvars.skn_update = self.ui.upd_skn_checkBox.isChecked()
        self.optionvars.sub_category = self.ui.sub_cats_comboBox.currentIndex()
        self.optionvars.exp_skel = self.ui.upd_skel_checkBox.isChecked()
        self.optionvars.as_rig = self.ui.as_rig_checkBox.isChecked()

    def add_to_tree(self):
        """
        Updates the character tree with all associated assets.
        """

        self.char_tree.clear()
        self.asset_items = []
        self.variant_items = []
        # Get Sub Category to help filter
        sub_category = self.ui.sub_cats_comboBox.currentText()

        asset_dict = self.get_asset_dict()

        # get all assets registered with in the category
        for asset, variants in asset_dict.items():
            if not sub_category == 'All' and sub_category != asset.subtype:
                continue
            asset_item = AssetShopTreeItem(asset=asset, parent=self.char_tree)
            asset_item.is_variant = False
            self.asset_items.append(asset_item)
            for variant in variants:
                variant_item = AssetShopTreeItem(asset=variant, parent=asset_item)
                variant_item.is_variant = True
                variant_item.parent_item = asset
                self.variant_items.append(variant)
        if not self.asset_items:
            return
        self.char_tree.setCurrentItem(self.char_tree.topLevelItem(0))
        self.get_selected_item()

    def set_description(self):
        """ Sets the description in the text box in the UI. """

        self.ui.text_info_textEdit.setText(self.tree_item.asset_description())

    def get_asset_dict(self):
        """
        Returns the asset dictionary associated with the category.
        Gets fresh AssetManager reference to avoid stale caches.

        :return: Returns the asset dictionary associated with the category.
        :rtype: dict
        """

        category = self.categories[0]
        assets = {}
        variants = {}
        # Get fresh manager reference (singleton, but no module-level cache)
        manager = get_asset_manager()
        for record in manager.iter_category(category):
            entry = record.source_entry or record
            asset_type = (record.asset_type or '').lower()
            if asset_type == 'variant':
                parent_id = record.parent_id
                if parent_id:
                    variants.setdefault(parent_id, []).append(entry)
                continue
            assets[entry] = []
        for asset_entry in assets.keys():
            assets[asset_entry] = variants.get(asset_entry.asset_id, [])
        return assets

    def populate_sub_categories(self):
        """
        Populates the sub category names.
        """

        asset_types = []
        for asset, gear_list in self.get_asset_dict().items():
            asset_types.append(asset.subtype)
        asset_types = list(set(asset_types))
        asset_types.insert(0, 'All')
        self.ui.sub_cats_comboBox.clear()
        self.ui.sub_cats_comboBox.addItems(asset_types)

    def get_selected_item(self):
        """
        Returns the TreeWidgetItem with the asset entry.

        :return: Returns the TreeWidgetItem with the asset entry.
        :rtype: AssetShopTreeItem
        """

        self.tree_item = self.char_tree.currentItem()
        self.set_description()
        self.set_image()
        return self.tree_item

    def show_context_menu(self, point):
        """
        Offer the variant actions on a character.

        Double-click still imports, because that is the primary thing this tree
        is for. Swapping the body of the character already in the scene is a
        different intent, so it lives here rather than competing for the same
        gesture.

        :param qtcore.QPoint point: Position the menu was asked for, in tree
            viewport coordinates.
        """

        item = self.char_tree.itemAt(point)
        if item is None or not hasattr(item, 'asset'):
            return
        self.char_tree.setCurrentItem(item)

        menu = qtwidgets.QMenu(self.char_tree)
        apply_action = menu.addAction('Apply as Variant')
        apply_action.setToolTip('Swap the body of the character in the scene for this one. '
                                'Equipped gear stays on.')
        revert_action = menu.addAction('Revert to Base Body')

        # Only offer applying when this asset really is a variant of whatever is
        # in the scene - the API refuses otherwise, and a greyed-out entry says
        # so before the user clicks it.
        listed = variant_api.list_variants()
        family = set()
        if listed['ok']:
            family = {v['asset_id'] for v in listed['result']['variants']}
            family.add(listed['result']['base']['asset_id'])
        asset_id = getattr(item.asset, 'asset_id', '')
        apply_action.setEnabled(bool(family) and asset_id in family)
        revert_action.setEnabled(listed['ok'] and not listed['result'].get('current') ==
                                 listed['result'].get('base', {}).get('asset_id'))

        chosen = menu.exec_(self.char_tree.viewport().mapToGlobal(point))
        if chosen == apply_action:
            self.apply_variant_clicked()
        elif chosen == revert_action:
            self.revert_variant_clicked()

    def apply_variant_clicked(self):
        """
        Swap the scene character's body for the selected variant.
        """

        item = self.char_tree.currentItem()
        if item is None or not hasattr(item, 'asset'):
            return
        response = variant_api.apply_variant(item.asset.asset_id)
        if not response['ok']:
            logger.warning(response['message'])
            dialogs.info_prompt(title='Could not apply variant', text=response['message'])
            return
        logger.info(response['message'])

    def revert_variant_clicked(self):
        """
        Put the scene character's base body back.
        """

        response = variant_api.revert_variant()
        if not response['ok']:
            logger.warning(response['message'])
            dialogs.info_prompt(title='Could not revert', text=response['message'])
            return
        logger.info(response['message'])

    def register_new_asset_clicked(self):
        """Opens the unified asset registration UI."""

        self._reg_window = unified_register.UnifiedRegisterUI(parent=self)
        self._reg_window.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Refresh the tree when the registration window closes."""

        if hasattr(self, '_reg_window') and obj is self._reg_window:
            if event.type() == qtcore.QEvent.Close:
                # Refresh the whole window, not just this tab: an asset registered
                # here can belong to any category, and a new gear category needs a
                # tab that does not exist yet.
                window = summoner_window(self)
                if window is not None:
                    window.refresh_all()
                else:
                    get_asset_manager(force_reload=True)
                    self.populate_sub_categories()
                    self.add_to_tree()
        return super().eventFilter(obj, event)

    def import_rig(self):
        """ Imports the rig """
        asset = self.tree_item.asset
        rig_path = asset.src_rig_path
        if not os.path.exists(rig_path):
            logger.warning(f'Rig asset: "{asset.name}", Does not Exist!')
        rig_utils.import_asset(asset.asset_id)

    def import_clicked(self):
        """
        Imports the selected asset.
        """

        if not self.tree_item:
            return

        if self.ui.as_rig_checkBox.isChecked():
            self.import_rig()
            return

        organization_group, skel_root_dict = summoner_utils.import_asset(asset_entry=self.tree_item.asset,
                                                                        as_model=self.ui.model_checkBox.isChecked(),
                                                                        skel_root_dict=None)
        if self.ui.full_skel_checkBox.isChecked():
            bind_root = skel_root_dict.get(self.tree_item.asset.skel_path)
            if not bind_root:
                bind_root = skel_root_dict.get('default')
            if bind_root:
                skel_path = self.tree_item.asset.skel_path
                skel_utils.import_merge_skeleton(skel_path, bind_root)

    def create_image_clicked(self):
        """
        Takes a screenshot and creates an image file.
        """

        if not self.tree_item:
            return
        result = dialogs.question_prompt(title='Capture New Icon?', text=f'Capture new icon for: \n"{self.tree_item.asset.name}"?')
        if result != 'Yes':
            return
        self.create_image(force=True, skip_dialog=True, auto_capture=False)

    def create_image(self, force=False, skip_dialog=False, auto_capture=True):
        """
        Creates an image file.
        :param bool force: Will force image creation.
        :param bool skip_dialog: If True, dialogs will not be printed.
        :param bool auto_capture: If True, it will attempt to fit the image in the screen before taking the image.
        :return: Returns the image file full path.
        :rtype: str
        """

        if os.path.exists(self.tree_item.icon_path) and not force:
            if not skip_dialog:
                logger.warning('Icon already exists')
            return

        image_name = f'{self.tree_item.asset.name}'
        path = os.path.dirname(self.tree_item.icon_path)
        group = summoner_utils.get_org_group(self.tree_item.asset, attr_name='modelshop')
        focus_objects = None
        if group:
            focus_objects = group.getChildren(type=pm.nt.Transform)
        if not focus_objects:
            logger.warning('Unable to find the asset group.  Could not capture image.')
            return
        focal_length = 90
        jnt = False
        for obj in focus_objects:
            if isinstance(obj, pm.nt.Joint):
                jnt = True
        if not jnt:
            focal_length = 70
        image = camera_utils.create_center_capture(focus_objects,
                                                   file_path=path,
                                                   image_name=image_name,
                                                   resolution=(150, 300),
                                                   focal_length=focal_length,
                                                   auto_capture=auto_capture)

        resources.update_common_resources()

        # Write the image path back to the unified registry so the
        # Registration UI can pick it up automatically.
        if image and os.path.isfile(image):
            self._update_registry_image(image)

        self.ui.char_info_icon_label.clear()
        self.set_image()
        return image

    def _update_registry_image(self, image_path):
        """
        Store the captured image path on the asset's unified registry entry.

        Converts the absolute path to a relative path from the Icons directory
        (e.g. 'Icons/Characters/hyena.jpg') and saves it to the .alist file.

        :param str image_path: Absolute path to the captured image.
        """

        asset = self.tree_item.asset
        category = getattr(asset, 'category', None)
        asset_id = getattr(asset, 'asset_id', None)
        if not category or not asset_id:
            return

        registry = unified_registry.UnifiedAssetRegistry.load(category)
        if not registry:
            return

        entry = registry.get_asset_entry(asset_id, skip_dialog=True)
        if not entry:
            return

        # Build a relative path from the Icons root
        icons_root = paths.get_common_icons_path()
        normed = os.path.normpath(image_path)
        normed_root = os.path.normpath(icons_root)
        if normed.lower().startswith(normed_root.lower()):
            rel_path = os.path.relpath(normed, os.path.dirname(normed_root))
        else:
            rel_path = image_path
        rel_path = rel_path.replace('\\', '/')

        # Only save if the image path actually changed
        if entry.image == rel_path:
            return

        entry.image = rel_path
        registry.update_registry_dict()
        registry.save()
        logger.info(f'Updated image for "{asset.name}": {rel_path}')

    def set_image(self):
        """ Set the image in the UI. """

        path = self.tree_item.icon_path
        if not os.path.exists(path):
            self.ui.char_info_icon_label.clear()
            return
        rel_path = path_utils.to_relative_path(path, paths.get_common_icons_path())
        self.ui.char_info_icon_label.setPixmap(resources.pixmap(rel_path))

    def export_selected_clicked(self):
        """
        For each selected asset export their SK/SM and optionally save their source file.

        """
        if not self.tree_item:
            return

        org_grp = summoner_utils.get_org_group(self.tree_item.asset, attr_name='modelshop')
        if not org_grp:
            dialogs.info_prompt(title='No Organization Group', text='Please Create an organization group.\n'
                                                                    'And organize all associated nodes under the organization group.')
            return

        result = dialogs.question_prompt(title='Export Asset?', text=f'Export: \n"{self.tree_item.asset.name}"?')
        if result != 'Yes':
            return

        # Save UI settings
        self.update_optionvars()

        self.create_image(force=False, skip_dialog=True)

        summoner_utils.export_asset(node=org_grp,
                                     asset_entry=self.tree_item.asset,
                                     update_skn=self.ui.upd_skn_checkBox.isChecked(),
                                     save_source=self.ui.ma_checkBox.isChecked(),
                                     full_skeleton=self.ui.full_skel_checkBox.isChecked())
        pm.select(cl=True)


class AssetShopTreeItem(asset_ui_data.AssetMainTreeItem):
    """
    Custom QTreeWidgetItem with Widgets
    """

    def __init__(self, asset, parent):
        super().__init__(asset=asset, parent=parent)
