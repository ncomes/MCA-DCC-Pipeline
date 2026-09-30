"""
One category's assets: the ``.alist`` file they live in, read and written.

```python
from mca.common.assetlist import unified_registry

registry = unified_registry.UnifiedAssetRegistry.load('Characters')
entry = registry.get_asset_entry_by_name('Hero Bot')
```

A registry is a category's file - ``Assetlists/Characters.alist`` - holding asset id to
fields. It reads JSON or the YAML the ``.alist`` files used to be, without being told which,
and writes JSON.

Three things about the version this replaces:

- **A new category's file was never added to source control.** ``save`` wrote the file and
  *then* asked ``if not os.path.exists(file_name)`` before adding it - after writing it, so
  the answer was always no. Every registry file made since has been sitting on disk unadded.
- **An empty file read as no file at all.** ``load`` answered None for a registry with no
  assets in it, which is exactly what a new category has, so the first asset could never be
  added to one.
- **Every add and remove rebuilt every entry in the category**, and threw away the entry
  objects anything was holding. A caller who fetched an entry, then added another, was left
  editing an object the registry no longer knew about - and ``save`` rebuilds the file from
  the entries it does know about, so those edits went nowhere. Entries are built once and
  kept.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common import sourcecontrol
from mca.common.assetlist import unified_entry
from mca.common.paths import paths
from mca.common.textio import alistio
from mca.common.utils import fileio


logger = log.MCA_LOGGER

#: What a category's file is called.
EXTENSION = '.alist'


class UnifiedAssetRegistry(object):
    """
    Every asset in one category.
    """

    def __init__(self, registry_dict=None, category_name=''):
        """
        :param dict registry_dict: Asset id to fields, as the file holds it.
        :param str category_name: Which category this is. Needed for an empty registry, which
            has no entry to ask.
        """

        self._registry_dict = registry_dict if registry_dict is not None else {}
        self._category_name = category_name or ''
        self._entries = {}
        self._build_entries()

    def __repr__(self):
        return 'UnifiedAssetRegistry({0!r}, {1} assets)'.format(self.category, len(self._entries))

    def __len__(self):
        return len(self._entries)

    # -- reading and writing the file ----------------------------------- #
    @classmethod
    def file_path(cls, category, folder=''):
        """
        :param str category: A category name.
        :param str folder: Where to look. The project's Assetlists folder by default.
        :return: The file, or ``''`` when there is no project and no folder was named.
        :rtype: str
        """

        if not category:
            return ''
        folder = folder or paths.get_asset_lists_path()
        if not folder:
            return ''

        return os.path.normpath(os.path.join(folder, '{0}{1}'.format(category, EXTENSION)))

    @classmethod
    def load(cls, category, folder='', create=False):
        """
        One category's assets.

        :param str category: The category name, which is the file's name.
        :param str folder: Where to look. The project's Assetlists folder by default.
        :param bool create: True answers an empty registry for a category with no file yet,
            rather than None - which is what registering the first asset in a new category
            needs.
        :return: The registry, or None when there is no such file and ``create`` is False.
        :rtype: UnifiedAssetRegistry or None
        """

        file_path = cls.file_path(category, folder=folder)
        if not file_path:
            logger.warning('There is no project, so the "%s" asset list cannot be found.', category)
            return cls({}, category_name=category) if create else None

        if not os.path.isfile(file_path):
            # Gear used to fall back to a folder of its own. It does not any more: gear lives
            # in Assetlists with everything else, and falling back served pre-migration data.
            if create:
                logger.info('Starting a new asset list for "%s".', category)
                return cls({}, category_name=category)
            logger.warning('No asset list for the category "%s" (%s).', category, file_path)
            return None

        # A file with nothing in it is a category with no assets yet, not a missing file: the
        # version this replaces answered None for it, so the first asset could never be added.
        registry_dict = alistio.read_alist_file(filename=file_path, default={})
        if not isinstance(registry_dict, dict):
            logger.error('The asset list for "%s" could not be read: %s', category, file_path)
            return None

        return cls(registry_dict, category_name=category)

    def save(self, folder=''):
        """
        Write the file, and put it into source control.

        :param str folder: Where to write. The project's Assetlists folder by default.
        :return: The file written, or ``''``.
        :rtype: str
        """

        if not self.category:
            logger.error('This registry has no category, so there is no file name to save it '
                         'under. The version this replaces wrote it to ".alist".')
            return ''

        file_path = self.file_path(self.category, folder=folder)
        if not file_path:
            logger.warning('There is no project, so the "%s" asset list was not saved.',
                           self.category)
            return ''

        existed = os.path.isfile(file_path)
        self.update_registry_dict()

        if existed:
            fileio.touch_path(file_path)
            sourcecontrol.checkout(file_path)
        else:
            fileio.touch_path(file_path)

        written = alistio.write_alist_file(data=self._registry_dict, filename=file_path, fmt='json')
        if not written:
            logger.error('The "%s" asset list could not be written: %s', self.category, file_path)
            return ''

        if not existed:
            # A file that did not exist before has to be *added*, and the version this
            # replaces asked whether it existed after writing it - so it never was.
            sourcecontrol.add(file_path)

        logger.info('Saved %s assets to %s.', len(self._entries), file_path)

        return written

    # -- what is in it -------------------------------------------------- #
    @property
    def registry_dict(self):
        """
        :return: Asset id to fields, as the file holds it.
        :rtype: dict
        """

        return self._registry_dict

    @property
    def category(self):
        """
        :return: Which category this is: what it was told, or what its first asset says.
        :rtype: str
        """

        if self._category_name:
            return self._category_name
        for entry in self._entries.values():
            return entry.category

        return ''

    def _build_entries(self):
        """
        Wrap every asset in the file.

        Once, at load. The version this replaces did this again on every add and every remove,
        rebuilding every entry in the category - so adding assets one at a time cost the square
        of their number, and every entry object anything was holding was quietly replaced.
        """

        self._entries = {}
        for asset_id, fields in self._registry_dict.items():
            try:
                self._entries[asset_id] = unified_entry.UnifiedAssetEntry({asset_id: fields})
            except Exception as error:                               # noqa: BLE001
                # One unreadable asset must not cost the whole category.
                logger.warning('The asset "%s" in %s could not be read: %s',
                               asset_id, self.category or '?', error)

    def get_asset_entries(self):
        """
        :return: Every asset in this category.
        :rtype: list[unified_entry.UnifiedAssetEntry]
        """

        return list(self._entries.values())

    def get_asset_entry(self, asset_id, skip_dialog=False):
        """
        :param str asset_id: An asset id.
        :param bool skip_dialog: True says nothing when there is no such asset.
        :return: It, or None.
        :rtype: unified_entry.UnifiedAssetEntry or None
        """

        entry = self._entries.get(asset_id)
        if entry is None and not skip_dialog:
            logger.warning('No asset with the id "%s" in %s.', asset_id, self.category or '?')

        return entry

    def get_asset_entry_by_name(self, asset_name, skip_dialog=False):
        """
        :param str asset_name: An asset's name, as a person reads it.
        :param bool skip_dialog: True says nothing when there is no such asset.
        :return: It, or None.
        :rtype: unified_entry.UnifiedAssetEntry or None
        """

        for entry in self._entries.values():
            if entry.name == asset_name:
                return entry

        if not skip_dialog:
            logger.warning('No asset called "%s" in %s.', asset_name, self.category or '?')

        return None

    def get_all_asset_names(self):
        """
        :return: Every asset's name, sorted.
        :rtype: list[str]
        """

        return sorted(entry.name for entry in self._entries.values())

    def add_asset_entry(self, asset_entry):
        """
        Put an asset in, or replace the one already there under that id.

        :param unified_entry.UnifiedAssetEntry asset_entry: The asset.
        :return: Whether it went in.
        :rtype: bool
        """

        if asset_entry is None or not asset_entry.asset_id:
            return False

        self._registry_dict[asset_entry.asset_id] = asset_entry.fields
        self._entries[asset_entry.asset_id] = asset_entry

        return True

    def remove_asset_entry(self, asset_id):
        """
        :param str asset_id: An asset id.
        :return: Whether it was there.
        :rtype: bool
        """

        if asset_id not in self._registry_dict and asset_id not in self._entries:
            logger.warning('No asset with the id "%s" to remove from %s.',
                           asset_id, self.category or '?')
            return False

        self._registry_dict.pop(asset_id, None)
        self._entries.pop(asset_id, None)

        return True

    def update_registry_dict(self):
        """
        Make the dictionary match the entries, which is what gets written.

        :return: The dictionary.
        :rtype: dict
        """

        self._registry_dict = {asset_id: entry.fields
                               for asset_id, entry in self._entries.items()}

        return self._registry_dict
