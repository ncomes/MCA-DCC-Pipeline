"""
Module that contains fncs for dealing with mca's asset registry list.
"""

# System global imports
# software specific imports
# MCA python imports
from mca.common.pyqt.pygui import qtwidgets
from mca.common import log
from mca.common.assetlist import get_asset_manager

from mca.mya.rigging import rig_utils
from mca.mya.pyqt import mayawindows
from mca.mya.animation import time_utils

logger = log.MCA_LOGGER


class SkelAssetSelection(mayawindows.MCAMayaWindow):
    VERSION = '1.0.0'

    def __init__(self, frag_rig, skel_root, reanimate_window, category=None):
        super().__init__(title='Skeleton Assets',
                         ui_path=None,
                         version=SkelAssetSelection.VERSION,
                         show_window=True)
        
        self.category = category
        if not self.category:
            self.category = 'Characters'
            
        self.reanimate_window = reanimate_window
        self.frag_rig = frag_rig
        self.skel_root = skel_root
        self._asset_manager = get_asset_manager()
        
        self.label = qtwidgets.QLabel('Choose Skeleton: ')
        self.label.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.label)
        
        self.tree_widget = qtwidgets.QTreeWidget()
        self.tree_widget.setHeaderLabels(["Assets"])
        self.tree_widget.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.tree_widget)
        
        self.h_layout = qtwidgets.QHBoxLayout()
        self.h_layout.setContentsMargins(2, 0, 2, 6)
        self.main_layout.addLayout(self.h_layout)
        
        self.retarget = qtwidgets.QPushButton()
        self.retarget.setText(' Retarget ')
        self.h_layout.addWidget(self.retarget)
        
        self.cancel = qtwidgets.QPushButton()
        self.cancel.setText(' Cancel ')
        self.h_layout.addWidget(self.cancel)
        
        
        self.asset_items = []
        self.tree_item = None
        
        self.on_startup()
        
        ###################################
        # Signals
        ###################################
        self.tree_widget.itemSelectionChanged.connect(self.get_selected_item)
        self.tree_widget.itemDoubleClicked.connect(self.retarget_clicked)
        self.cancel.clicked.connect(self.close)
        self.retarget.clicked.connect(self.retarget_clicked)
        
    ###################################
    # Slots
    ###################################
        
    def on_startup(self):
        self.add_to_tree()
    
    def retarget_clicked(self):
        logger.debug('Baking animation to rig.')
        self.close()
        skel_path = self.tree_item.asset.skel_path
        
        start_frame, end_frame = self.reanimate_window._get_ui_time_range()
        asset_id = rig_utils.animate_rig_from_skeleton_cmd(frag_rig=self.frag_rig,
                                                           skel_root=self.skel_root,
                                                           start_frame=start_frame,
                                                           end_frame=end_frame,
                                                           append=self.reanimate_window.ui.append_checkBox.isChecked(),
                                                           motion_encode=self.reanimate_window.ui.motion_encode_checkBox.isChecked(),
                                                           diff_skel_path=skel_path)
        time_utils.reframe_visible_range()
    
    @property
    def asset_entries(self):
        """
        Returns a list of all the assets in the specific category.

        :return: 
        :rtype: list[AssetEntries]
        """
        
        records = list(self._asset_manager.iter_category(self.category))
        return sorted(records, key=lambda record: record.name.lower())
    
    def get_selected_item(self):
        """
        Returns the selected asset item.

        :return: Returns the selected asset item.
        :rtype: list[AssetEntry]
        """
        
        tree_item = self.tree_widget.currentItem()
        if not tree_item:
            self.tree_item = None
            return
        self.tree_item = tree_item
    
    def add_to_tree(self):
        """
        Updates the character tree with all associated assets. 
        """

        self.tree_widget.clear()
        for asset in self.asset_entries:
            asset_item = SkelAssetTreeItem(asset=asset, parent=self.tree_widget)
            asset_item.is_variant = False
            self.asset_items.append(asset_item)
        
        self.tree_widget.setCurrentItem(self.tree_widget.topLevelItem(0))


class SkelAssetTreeItem(qtwidgets.QTreeWidgetItem):
    """
    Custom QTreeWidgetItem with Widgets
    """
    
    def __init__(self, asset, parent):
        super().__init__(parent)
        self._asset = asset
        self.is_variant = True
        self.parent_item = None
        
        # Set the Text
        self.setText(0, self.asset.name)
    
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
    
        
        
