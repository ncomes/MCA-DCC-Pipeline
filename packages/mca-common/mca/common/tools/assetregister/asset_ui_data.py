"""
Asset registry UI data: preference paths and the shared asset tree item.

The VariantTreeWidget that used to live here was removed with the legacy
register; AssetMainTreeItem is the only part still in use, by the Summoner.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.paths import paths
from mca.common.pyqt.pygui import qtwidgets
from mca.common.resources import resources
from mca.common.textio import yamlio


logger = log.MCA_LOGGER

MAIN_ASSET_PREFS = 'asset_prefs_main.prefs'
ASSET_PREFS = 'asset_prefs.prefs'
GEAR_ASSET_PREFS = 'gear_prefs.prefs'


def asset_reg_base_prefs_path():
    """
    Returns the path to the local preferences folder path.
    
    :return: Returns the path to the local preferences folder path.
    :rtype: str
    """
    
    path = os.path.join(paths.get_local_preferences_folder(), 'AssetRegistry')
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.normpath(path)


def asset_main_ui_prefs_path():
    """
    Returns the path to the main ui folder path.

    :return: Returns the path to the main ui folder path.
    :rtype: str
    """
    
    path = os.path.join(asset_reg_base_prefs_path(), 'main_ui')
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.normpath(path)


def asset_register_prefs_path():
    """
    Returns the path to the asset tools ui folder path.

    :return: Returns the path to the asset tools ui folder path.
    :rtype: str
    """
    
    path = os.path.join(asset_reg_base_prefs_path(), 'asset_ui')
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.normpath(path)


def gear_register_prefs_path():
    """
    Returns the path to the gear tools ui folder path.

    :return: Returns the path to the gear tools ui folder path.
    :rtype: str
    """
    
    path = os.path.join(asset_reg_base_prefs_path(), 'gear_ui')
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.normpath(path)


def asset_main_ui_prefs_filepath():
    """
    The asset main ui preferences file path.
    
    :return: Returns the path to the asset main ui preferences file path.
    :rtype: str
    """
    
    path = os.path.join(asset_main_ui_prefs_path(), MAIN_ASSET_PREFS)
    if not os.path.exists(path):
        yamlio.write_to_yaml_file(data={}, filename=path)
    return os.path.normpath(path)


def asset_tool_ui_prefs_filepath():
    """
    The asset tools ui preferences file path.

    :return: Returns the path to the asset tools ui preferences file path.
    :rtype: str
    """
    
    path = os.path.join(asset_register_prefs_path(), ASSET_PREFS)
    if not os.path.exists(path):
        yamlio.write_to_yaml_file(data={}, filename=path)
    return os.path.normpath(path)

    
class AssetMainTreeItem(qtwidgets.QTreeWidgetItem):
    """
    Custom QTreeWidgetItem with Widgets
    """
    
    def __init__(self, asset, parent):
        super().__init__(parent)
        self._asset = asset
        self.parent_item = None
        # Set the Text
        self.setText(0, self.asset.name)
        self.setIcon(0, resources.icon(r'company_logos\default_logo.png'))
    
    @property
    def variant_of(self):
        """
        The asset id of the character this one restyles, if any.

        Replaces an ``is_variant`` attribute that was hardcoded True and, in
        the info panel, reported ``bool(built_for)`` - the test for gear, not
        for a variant.

        :return: Base character asset id, or ''.
        :rtype: str
        """

        return getattr(self._asset, 'variant_of', '') or ''

    @property
    def name(self):
        """
        Returns the asset name
        :return: the asset name
        :rtype: str
        """
        
        return self.text(0)
    
    @property
    def asset(self):
        """
        Returns the asset instance
        :return: Returns the asset instance
        :rtype: str
        """
        
        return self._asset
    
    @property
    def asset_id(self):
        """
        Returns the asset id
        :return: Returns the asset id
        :rtype: str
        """
        
        return self.asset.asset_id
    
    @property
    def icon_path(self):
        """
        Returns the string path to the icon.

        :return: Returns the string path to the icon.
        :rtype: str
        """
        
        name = f'{self.name.lower()}.jpg'
        path = os.path.join(paths.get_common_icons_path(), 'Characters', name)
        return os.path.normpath(path)
    
    def asset_description(self):
        """
        Formats the asset description.

        :return: Returns the asset description.
        :rtype: str
        """
        
        name = self.name
        path = self.asset.path
        asset_type = self.asset.category
        text_des = f"""Asset Name: {name}\nAsset Category: {asset_type}\nVariant Of: {self.variant_of or '-'}\nAsset Path: {path}\nAsset Id: {self.asset_id}
        """
        return text_des





















