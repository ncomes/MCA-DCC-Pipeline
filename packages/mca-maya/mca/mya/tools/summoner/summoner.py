"""
Main UI for the Summoner asset import/export tool.

Summoner provides a unified interface for:
- Importing assets (rigs, skeletal meshes, static meshes, full skeletons)
- Exporting assets with skinning and skeleton data
- Registering new assets to the asset registry
- Managing organization groups for export workflows
"""

# python imports
import os
import webbrowser
# software specific imports
# Qt imports
from mca.common.pyqt.pygui import qtwidgets, qtcore
# MCA python imports
from mca.common import log
from mca.common.assetlist import get_asset_manager
from mca.common.paths import paths
from mca.common.textio import alistio

from mca.mya.tools.summoner import gear_api
from mca.mya.tools.summoner import summoner_asset_tree, summoner_gear_tree
from mca.mya.pyqt import mayawindows
from mca.mya.utils import optionvars


logger = log.MCA_LOGGER

SUMMONER_DOC = r'https://worldsuntold.atlassian.net/wiki/spaces/MCA/pages/757497890/Model+Shop'

# Maps manifest category names to the legacy ``ui_name`` strings that
# AssetShopCharTreeWidget.optionvars uses to persist per-tab UI state
# (full-skel checkbox, sub-category index, etc.). Categories without an entry
# fall through to a slugified default and use in-memory state — fine for new
# tabs like Cameras/Faces, which have no persisted state to honor anyway.
_LEGACY_UI_NAME_MAP = {
    'Characters': 'char',
    'Heads': 'heads',
    'Props': 'props',
    'Vehicles': 'vehicles',
    'Weapons': 'weapons',
}


class SummonerMainUIOptionVars(optionvars.MCAOptionVars):
    """
    Handles keeping track of Summoner UI values to be restored or used during various UI functions.
    """
    SummonerMainUITab = {'default_value': 0, 'docstring': 'Selected Tab.'}
    # Backward compatibility - check old ModelShop option vars as fallback
    ModelShopMainUITab = {'default_value': 0, 'docstring': 'Selected Tab (legacy).'}

    @property
    def tabs(self):
        # Try new name first, fallback to old ModelShop name
        return self.SummonerMainUITab if self.SummonerMainUITab != 0 else self.ModelShopMainUITab

    @tabs.setter
    def tabs(self, value):
        self.SummonerMainUITab = value


class SummonerUI(mayawindows.MCAMayaWindow):
    VERSION = '2.0.0'  # Major version bump - merged ModelShop + old Summoner

    def __init__(self):
        root_path = os.path.dirname(os.path.realpath(__file__))
        ui_path = os.path.join(root_path, 'ui', 'summoner.ui')
        super().__init__(title='Summoner',
                         ui_path=ui_path,
                         version=SummonerUI.VERSION)

        self.setMinimumSize(600, 600)
        self.optionvars = SummonerMainUIOptionVars()

        self.on_startup()

        ###################################
        # Signals
        ###################################
        self.ui.import_tabWidget.currentChanged.connect(self._set_tabs)
        self.ui.actionDocumentation.triggered.connect(self.tools_documentation)

    ###################################
    # Slots
    ###################################
    def on_startup(self):
        # --- Primary asset tabs (built from manifest) ----------------------- #
        # The .ui ships with only the static Gear meta-tab; primary tabs (Characters,
        # Heads, Weapons, Props, Vehicles, Cameras, ...) are inserted before it from
        # the categories.json manifest so adding a new primary category only requires
        # a manifest entry, not a UI file edit.
        self._setup_primary_tabs()

        # --- Gear tab: dynamic sub-tabs from categories manifest ------------ #
        self._setup_gear_tabs()

        # Restore the previously-active tab AFTER the tab set has been built so the
        # saved index lines up. Clamp to the actual tab count to handle a saved
        # index that's now out of range (e.g. categories were removed since last
        # session). Signals stay blocked so we don't immediately persist a tab
        # change we just restored.
        self.block_signals()
        tab_count = self.ui.import_tabWidget.count()
        if tab_count:
            self.ui.import_tabWidget.setCurrentIndex(min(self.optionvars.tabs, tab_count - 1))
        self.block_signals(False)

    def _manifest_tab_categories(self, key):
        """
        Read one of the manifest's tab lists, in display order.

        ``primary_categories`` / ``gear_categories`` are a curated presentation
        split kept alongside the v2.0 ``categories`` load list. If the key is
        missing - which is what happens when something rewrites the manifest
        without carrying them across - fall back to every declared category and
        say so, rather than silently building a window with no tabs.

        :param str key: 'primary_categories' or 'gear_categories'.
        :return: Category names, in display order.
        :rtype: list[str]
        """

        manifest_path = paths.get_categories_manifest_path()
        manifest = alistio.read_alist_file(manifest_path)
        if not manifest:
            logger.warning('Could not read categories manifest at: %s', manifest_path)
            return []

        entries = manifest.get(key) or []
        if not entries:
            logger.warning(
                'categories manifest at %s has no %r; falling back to every declared '
                'category. Restore that list to get the intended tabs back.',
                manifest_path, key)
            entries = manifest.get('categories') or []

        entries = sorted(entries, key=lambda c: c.get('display_order', 0))
        return [e.get('name', '') for e in entries if e.get('name')]

    def _gear_tab_categories(self):
        """
        Work out which categories deserve a gear sub-tab, from the data.

        A category earns a tab when it actually holds gear, as
        :func:`gear_api.is_gear_record` defines it - a parent in ``built_for``,
        or a Maya source file on disk where the registry never recorded one.
        The second half matters: every JellyBean shirt is parentless, so a
        parent-only rule left the Shirts tab out of the Summoner entirely.

        The curated ``gear_categories`` list only sets the order of the ones it
        names; any other category holding gear is appended after them.

        This is deliberately not driven by ``asset_data.config``'s ``is_gear``
        flag: that flag disagrees with the data (Armor is flagged False while
        every Armor asset has a parent), so trusting it would drop real tabs.

        :return: Category names, curated order first.
        :rtype: list[str]
        """

        with_gear = set(gear_api.gear_categories())

        ordered = [name for name in self._manifest_tab_categories('gear_categories')
                   if name in with_gear]
        extra = sorted(with_gear - set(ordered))
        if extra:
            logger.info('Gear found in categories outside gear_categories; '
                        'adding tabs for: %s', ', '.join(extra))
        return ordered + extra

    def _setup_primary_tabs(self):
        """
        Reads the categories manifest and inserts one primary asset tab per declared
        primary category, in front of the static Gear meta-tab. Each tab hosts an
        :class:`AssetShopCharTreeWidget` filtered to that category. Trees are stashed
        on ``self.primary_trees`` keyed by category name so callers can find them
        later (used by tooling that programmatically selects a tab).

        """

        self.primary_trees = {}

        # Insert each primary tab in order at index 0..N, pushing the existing static
        # Gear tab right. Inserting (rather than appending) keeps Gear last regardless
        # of how many primaries the manifest declares.
        for insert_index, cat_name in enumerate(
                self._manifest_tab_categories('primary_categories')):
            ui_name = _LEGACY_UI_NAME_MAP.get(cat_name, cat_name.lower())
            tree = summoner_asset_tree.AssetShopCharTreeWidget(gear_category='Outfits',
                                                               categories=[cat_name],
                                                               ui_name=ui_name,
                                                               parent=self)
            container = qtwidgets.QWidget(self)
            layout = qtwidgets.QVBoxLayout(container)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.addWidget(tree)
            self.ui.import_tabWidget.insertTab(insert_index, container, cat_name)
            self.primary_trees[cat_name] = tree

    def _setup_gear_tabs(self):
        """
        Creates one gear sub-tab per category that actually holds gear.

        The manifest's ``gear_categories`` supplies the order; any other
        category holding assets with a parent is appended, so registering gear
        in a new category makes its tab appear without editing the manifest.

        Each sub-tab contains a :class:`GearTreeWidget` that shows the
        Character > Slot > Item hierarchy for that gear category.
        """

        # Remove the placeholder Collections / Parts sub-tabs from the .ui.
        self.ui.apparel_tabWidget.clear()

        self.gear_trees = {}

        for cat_name in self._gear_tab_categories():
            tree = summoner_gear_tree.GearTreeWidget(gear_category=cat_name, parent=self)
            self.ui.apparel_tabWidget.addTab(tree, cat_name)
            self.gear_trees[cat_name] = tree

    def refresh_all(self):
        """
        Bring every tab back in step with the registry.

        Scheduled rather than run now, because the caller is usually an event
        filter on the registration window and this may destroy the very widget
        whose filter is on the stack - rebuilding the gear tabs replaces those
        tree widgets. Deferring to the next turn of the event loop lets the
        filter return first.
        """

        qtcore.QTimer.singleShot(0, self._refresh_now)

    def _refresh_now(self):
        """
        Reload the registry and repopulate every tab.

        The per-tab refresh this replaces rebuilt only the tree you happened to
        register from, so a new asset stayed invisible in every other tab, and a
        category that gained its first gear never grew a tab at all.
        """

        get_asset_manager(force_reload=True)

        for category, tree in getattr(self, 'primary_trees', {}).items():
            try:
                tree.populate_sub_categories()
                tree.add_to_tree()
            except Exception:
                logger.exception('Summoner: the %s tab could not be refreshed.', category)

        # Gear tabs are data driven - which categories hold gear can change with
        # the asset that was just registered - so rebuild them when the set moves.
        try:
            wanted = self._gear_tab_categories()
        except Exception:
            logger.exception('Summoner: could not work out the gear tabs.')
            return

        if wanted != list(getattr(self, 'gear_trees', {})):
            self._setup_gear_tabs()
            return

        for category, tree in self.gear_trees.items():
            try:
                tree._populate_tree()
            except Exception:
                logger.exception('Summoner: the %s gear tab could not be refreshed.', category)

    def _set_tabs(self):
        """
        Sets the optionvar that keeps track of which tab was selected and updates the tab info.
        """

        index = self.ui.import_tabWidget.currentIndex()
        self.optionvars.tabs = index

    def block_signals(self, block=True):
        self.ui.import_tabWidget.blockSignals(block)

    def tools_documentation(self):
        """
        Opens the Confluence page for Summoner documentation.
        """

        webbrowser.open(SUMMONER_DOC)

