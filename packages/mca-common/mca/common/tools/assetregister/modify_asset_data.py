"""
Editor for a category's sub-categories and factions.

Opened from the Unified Asset Register's "Modify Data" button. Edits the
sub-category and faction lists stored on one category in ``asset_data.config``.

:Requires: mca.common.assetlist.asset_paths, mca.common.pyqt
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_paths
from mca.common.pyqt import common_windows
from mca.common.utils import strings


logger = log.MCA_LOGGER


class ModifyAssetPathsUI(common_windows.MCAMainWindow):
    VERSION = '1.0.0'

    def __init__(self, category, parent=None):
        """
        Build the editor for one category.

        :param str category: Name of the category whose sub-categories and
            factions are being edited.
        :param QWidget parent: Optional parent window.
        :raises ValueError: If ``category`` is empty or unknown to the config.
        """

        if not category:
            raise ValueError('ModifyAssetPathsUI requires a category name.')

        asset_data = asset_paths.AssetDictData.load()
        category_data = asset_data.get_category_data(category)
        if category_data is None:
            raise ValueError(
                'Category {!r} is not present in asset_data.config.'.format(category))

        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'modify_data.ui')
        super().__init__(title='Modify Asset Data',
                         ui_path=ui_path,
                         show_window=True,
                         version=self.VERSION,
                         parent=parent)
        self.category = category
        self.asset_data = asset_data
        self.category_data = category_data

        self.setMinimumSize(540, 600)
        self.on_startup()

        ###################################
        # Signals
        ###################################
        self.ui.add_cat_pushButton.clicked.connect(self.add_subcategory)
        self.ui.new_sub_lineEdit.returnPressed.connect(self.add_subcategory)
        self.ui.add_fac_pushButton.clicked.connect(self.add_faction)
        self.ui.new_fac_lineEdit.returnPressed.connect(self.add_faction)
        self.ui.rem_pushButton.clicked.connect(self.remove_subcategory)
        self.ui.fac_rem_pushButton.clicked.connect(self.remove_faction)
        self.ui.new_sub_clear_pushButton.clicked.connect(self.clear_new_subcategory)
        self.ui.new_fac_clear_pushButton.clicked.connect(self.clear_new_faction)
        self.ui.save_pushButton.clicked.connect(self.save_data)

    ###################################
    # Slots
    ###################################
    def on_startup(self):
        """ Runs at Startup """

        # Set the Category label
        self.ui.cat_label.setText(f'Category: {self.category} ')
        # Populate the QListWidgets
        self.populate_subcategories()
        self.populate_factions()

    def get_subcategories(self):
        """
        Gets all the subcategories of the category.
        """

        return self.category_data.subcategories

    def get_factions(self):
        """
        Gets all the factions of the category.
        """

        return self.category_data.factions

    def populate_subcategories(self):
        """ Populates the QListWidget for the subcategories. """

        self.ui.sub_listWidget.clear()
        self.ui.sub_listWidget.addItems(self.get_subcategories())

    def populate_factions(self):
        """ Populates the QListWidget for the factions. """

        self.ui.fac_listWidget.clear()
        self.ui.fac_listWidget.addItems(self.get_factions())

    def clear_new_subcategory(self):
        self.ui.new_sub_lineEdit.clear()

    def clear_new_faction(self):
        self.ui.new_fac_lineEdit.clear()

    def add_subcategory(self):
        """
        Adds a subcategory to the asset data.
        """

        sub_text = (self.ui.new_sub_lineEdit.text()).strip()
        if sub_text == '' or not sub_text:
            return
        sub_text = strings.remove_chars(sub_text)
        items = listwidget_utils.get_qlist_widget_items(self.ui.sub_listWidget)
        if sub_text in items:
            return

        self.category_data.add_subcategory(sub_text)
        self.asset_data.update_category(self.category_data)
        self.populate_subcategories()
        self.ui.new_sub_lineEdit.clear()

    def add_faction(self):
        """
        Adds a faction to the asset data.
        """

        sub_text = (self.ui.new_fac_lineEdit.text()).strip()
        if sub_text == '' or not sub_text:
            return
        sub_text = strings.remove_chars(sub_text)
        items = listwidget_utils.get_qlist_widget_items(self.ui.fac_listWidget)
        if sub_text in items:
            return

        self.category_data.add_faction(sub_text)
        self.asset_data.update_category(self.category_data)
        self.populate_factions()
        self.ui.new_fac_lineEdit.clear()

    def remove_subcategory(self):
        selected_item = listwidget_utils.get_qlist_widget_selected_items(self.ui.sub_listWidget)
        if not selected_item:
            return
        selected_item = selected_item[0]
        self.category_data.remove_subcategory(selected_item)
        self.asset_data.update_category(self.category_data)
        self.populate_subcategories()

    def remove_faction(self):
        selected_item = listwidget_utils.get_qlist_widget_selected_items(self.ui.fac_listWidget)
        if not selected_item:
            return
        selected_item = selected_item[0]
        self.category_data.remove_faction(selected_item)
        self.asset_data.update_category(self.category_data)
        self.populate_factions()

    def save_data(self):
        self.asset_data.save()

