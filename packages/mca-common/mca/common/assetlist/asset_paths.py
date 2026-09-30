"""
What a project's asset categories are, and where each one's folders go.

The data lives in ``asset_data.config``, a YAML file in the project's Assetlist folder, which
artists edit through the register: the categories, each one's factions and subcategories, the
folders its assets have, and a ``_Global`` block of things shared across all of them -
skeletons, body types, slots, attach sockets. :class:`AssetDictData` is that file;
:class:`CategoryData` is one category in it; :class:`GlobalData` is the ``_Global`` block.

A new project's file is seeded from ``asset_path_templates.yaml``, which ships with the
framework - see :mod:`asset_path_config`.

Three things about the version this replaces:

- **It could not be used without Qt.** It began ``from mca.common.pyqt import common_windows``
  and never used it, so importing the asset registry - to read it from a farm job, an MCP
  server, a test, or Unreal's Python - needed PySide to be importable first.
- **It read the file from disk every time anything asked.** ``AssetDictData.load()`` parses
  the YAML, and ``unified_entry`` calls it while working out a single asset's folder, so
  building a registry of several hundred assets read and parsed the same file several hundred
  times. It is read once now, and :func:`reload` is how a change is picked up.
- **Half of it was a previous generation.** ``ASSET_LIST_CHARACTERS`` and its five siblings,
  ``CATEGORIES``, ``GEAR``, ``CATEGORY_CONSTS``, ``AssetPathData``, ``GearPathData`` and six
  module functions built dictionaries at import time that nothing anywhere in the framework
  read - about five hundred lines of it.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common import sourcecontrol
from mca.common.assetlist import asset_path_config
from mca.common.paths import paths
from mca.common.textio import yamlio
from mca.common.utils import fileio


logger = log.MCA_LOGGER

#: The project's own file, in its Assetlist folder.
ASSET_DATA_FILE = 'asset_data.config'

_folder_names = asset_path_config.folder_names()

#: What the folders inside an asset are called. From the templates file, with what they have
#: always been as the fallback, so a broken install still builds the paths it used to.
SOURCE_FOLDER = _folder_names.get('source', '_Source')
RIGS_FOLDER = _folder_names.get('rigs', 'Rigs')
MODELS_FOLDER = _folder_names.get('models', 'Meshes')
ANIMATIONS_FOLDER = _folder_names.get('animations', 'Animations')
TEXTURES_FOLDER = _folder_names.get('textures', 'Textures')
FLAGS_FOLDER = _folder_names.get('flags', 'Flags')

#: Where a gear category's assets sit unless the category names somewhere else.
DEFAULT_GEAR_ROOT = 'Gear'

#: The keys of the folders every asset has.
REQUIRED_KEY = 'REQUIRED'
OPTIONAL_KEY = 'OPTIONAL'
SUBCATEGORIES_KEY = 'SUBCATEGORIES'
FACTIONS_KEY = 'FACTIONS'
ADDITIONAL_TYPES_KEY = 'ADDITIONAL_TYPES'
IS_GEAR_KEY = 'IS_GEAR'
GEAR_ROOT_KEY = 'GEAR_ROOT'

#: The one already read, so that asking twice costs nothing.
_LOADED = None


def normalize_gear_root(value):
    """
    Tidy a typed gear root into a relative path with forward slashes.

    ``'Gear\\'``, ``'/Gear/'`` and ``' Gear '`` all come back as ``'Gear'``.

    :param str value: What somebody typed.
    :return: The tidied path, or ``''`` when nothing usable is left.
    :rtype: str
    """

    if not value:
        return ''

    segments = [segment.strip() for segment in str(value).replace('\\', '/').split('/')]
    segments = [segment for segment in segments if segment and segment != '.']

    return '/'.join(segments)


def new_category_block(subcategories=(), is_gear=False, gear_root='', factions=()):
    """
    A category as it looks the moment it is made.

    :param subcategories: The subcategories it starts with.
    :param bool is_gear: Whether its assets are worn or carried by another asset.
    :param str gear_root: Where its paths start, when it is gear.
    :param factions: The factions it starts with.
    :return: The block, ready to go into the file.
    :rtype: dict
    """

    return {
        SUBCATEGORIES_KEY: sorted(subcategories),
        FACTIONS_KEY: sorted(factions),
        ADDITIONAL_TYPES_KEY: [],
        IS_GEAR_KEY: bool(is_gear),
        GEAR_ROOT_KEY: normalize_gear_root(gear_root) or DEFAULT_GEAR_ROOT,
        OPTIONAL_KEY: {},
        REQUIRED_KEY: asset_path_config.required_paths(),
    }


def seed_dictionary():
    """
    Every category a new project starts with.

    :return: Category name to its block.
    :rtype: dict

    The version this replaces built these as seven module-level dictionaries, each calling a
    helper with a hardcoded list of subcategories as a fallback - and those fallbacks had gone
    stale, saying ``NPCs`` where the file said ``NPC`` and ``Handguns`` where it said
    ``Handgun``. It also left out ``Faces``, which the same file declared and every real
    project has, so a fresh checkout came up without one.
    """

    seeded = {}
    for name, block in asset_path_config.seed_categories().items():
        seeded[name] = new_category_block(subcategories=block['subcategories'],
                                         is_gear=block['is_gear'],
                                         gear_root=block['gear_root'])

    return seeded


class CategoryData(object):
    """
    One category: what its assets may be, and where their folders go.
    """

    def __init__(self, category_dict):
        """
        :param dict category_dict: ``{name: block}`` - one key, as it is stored.
        """

        self._category_dict = category_dict
        # Worked out once. Every property in the version this replaced read
        # list(dict.keys())[0] again, on every single access.
        self._category = next(iter(category_dict), '')
        block = category_dict.get(self._category)
        if not isinstance(block, dict):
            # Put the new block back where it came from, so that changes made through this
            # object reach the dictionary the file holds rather than a copy of it.
            block = {}
            if self._category:
                category_dict[self._category] = block
        self._block = block

    def __repr__(self):
        return 'CategoryData({0!r})'.format(self._category)

    @property
    def category_dict(self):
        """
        :return: The category as it is stored, which is what gets written back out.
        :rtype: dict
        """

        return self._category_dict

    @property
    def category(self):
        """
        :return: Its name.
        :rtype: str
        """

        return self._category

    # -- gear ----------------------------------------------------------- #
    @property
    def is_gear(self):
        """
        :return: Whether its assets are worn or carried by another asset, which puts their
            folders under :attr:`gear_root`.
        :rtype: bool
        """

        return bool(self._block.get(IS_GEAR_KEY, False))

    @is_gear.setter
    def is_gear(self, value):
        self._block[IS_GEAR_KEY] = bool(value)

    @property
    def gear_root(self):
        """
        :return: Where its paths start - ``'Gear'``, ``'Characters/Gear'``. Always something.
        :rtype: str
        """

        return normalize_gear_root(self._block.get(GEAR_ROOT_KEY, '')) or DEFAULT_GEAR_ROOT

    @gear_root.setter
    def gear_root(self, value):
        self._block[GEAR_ROOT_KEY] = normalize_gear_root(value) or DEFAULT_GEAR_ROOT

    # -- lists ---------------------------------------------------------- #
    @property
    def factions(self):
        """
        :return: Its factions.
        :rtype: list[str]
        """

        return list(self._block.get(FACTIONS_KEY) or [])

    @factions.setter
    def factions(self, list_value):
        self._block[FACTIONS_KEY] = sorted(set(list_value))

    def add_faction(self, faction):
        """
        :param str faction: One to add. Already being there is not a failure.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add(FACTIONS_KEY, faction)

    def remove_faction(self, faction):
        """
        :param str faction: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._remove(FACTIONS_KEY, faction)

    @property
    def subcategories(self):
        """
        :return: Its subcategories.
        :rtype: list[str]
        """

        return list(self._block.get(SUBCATEGORIES_KEY) or [])

    @subcategories.setter
    def subcategories(self, list_value):
        self._block[SUBCATEGORIES_KEY] = sorted(set(list_value))

    def add_subcategory(self, subcategory):
        """
        :param str subcategory: One to add.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add(SUBCATEGORIES_KEY, subcategory)

    def remove_subcategory(self, subcategory):
        """
        :param str subcategory: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._remove(SUBCATEGORIES_KEY, subcategory)

    @property
    def additional_types(self):
        """
        :return: Extra asset types this category allows beyond the project's own.
        :rtype: list[str]
        """

        return list(self._block.get(ADDITIONAL_TYPES_KEY) or [])

    @additional_types.setter
    def additional_types(self, list_value):
        self._block[ADDITIONAL_TYPES_KEY] = sorted(set(list_value))

    def add_additional_type(self, additional_type):
        """
        :param str additional_type: One to add.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add(ADDITIONAL_TYPES_KEY, additional_type)

    def remove_additional_type(self, additional_type):
        """
        :param str additional_type: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._remove(ADDITIONAL_TYPES_KEY, additional_type)

    def _add(self, key, value):
        """
        Add to one of the lists, through its setter.

        :param str key: Which list.
        :param str value: What to add.
        :return: Whether it was added.
        :rtype: bool

        Every ``add_`` method in the version this replaces read the list, and if it was not
        empty called ``.append`` **on the list the file holds** - so the value went in
        unsorted, past the setter that sorts, and on a category with no such key at all it
        appended to a throwaway list and was lost.
        """

        if not value:
            return False

        current = list(self._block.get(key) or [])
        if value in current:
            return False

        current.append(value)
        self._block[key] = sorted(set(current))

        return True

    def _remove(self, key, value):
        """
        :param str key: Which list.
        :param str value: What to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        current = list(self._block.get(key) or [])
        if value not in current:
            return False

        current.remove(value)
        self._block[key] = current

        return True

    # -- folders -------------------------------------------------------- #
    @property
    def required_paths(self):
        """
        :return: The folders every asset in this category has, by key.
        :rtype: dict
        """

        return dict(self._block.get(REQUIRED_KEY) or {})

    def get_required_path(self, path_name):
        """
        Where one of an asset's folders goes.

        :param str path_name: A key - ``'RIGS_PATH'``, ``'SRC_MODELS_PATH'``.
        :return: The folder, relative to the asset, or ``''``.
        :rtype: str

        Looked up exactly. The version this replaces matched **substrings** - 
        ``if path_name in req_name`` - and answered the first key that contained what was
        asked for, in whatever order the file happened to list them. Asking for
        ``RIGS_PATH`` gave the right answer only because ``RIGS_PATH`` is listed before
        ``SRC_RIGS_PATH``; write the file the other way round and every rig in the project
        resolves to the source folder. It also indexed ``[REQUIRED]`` without checking, so a
        category with no folder block raised KeyError out of a function documented to answer
        None.
        """

        required = self._block.get(REQUIRED_KEY) or {}
        if path_name in required:
            return required[path_name] or ''

        # Kept as a fallback because tools do ask for 'RIGS' and 'MODELS', and they used to
        # get an answer. An exact key wins first, so this can no longer shadow one.
        for key, path in required.items():
            if path_name and path_name in key:
                logger.debug('Asked for the folder "%s" and matched "%s".', path_name, key)
                return path or ''

        return ''

    def set_required_path(self, path_name, folder):
        """
        :param str path_name: A key - ``'RIGS_PATH'``.
        :param str folder: Where it goes, relative to the asset.
        """

        self._block.setdefault(REQUIRED_KEY, {})[path_name] = folder

    @property
    def rig_folder(self):
        """
        :return: Where built rigs go.
        :rtype: str
        """

        return self.get_required_path('RIGS_PATH')

    @rig_folder.setter
    def rig_folder(self, path):
        self.set_required_path('RIGS_PATH', path)

    @property
    def mesh_folder(self):
        """
        :return: Where exported meshes go.
        :rtype: str
        """

        return self.get_required_path('MODELS_PATH')

    @mesh_folder.setter
    def mesh_folder(self, path):
        self.set_required_path('MODELS_PATH', path)

    @property
    def textures_folder(self):
        """
        :return: Where textures go.
        :rtype: str
        """

        return self.get_required_path('TEXTURES_PATH')

    @textures_folder.setter
    def textures_folder(self, path):
        self.set_required_path('TEXTURES_PATH', path)

    @property
    def animations_folder(self):
        """
        :return: Where exported animations go.
        :rtype: str
        """

        return self.get_required_path('ANIMATIONS_PATH')

    @animations_folder.setter
    def animations_folder(self, path):
        self.set_required_path('ANIMATIONS_PATH', path)

    @property
    def src_mesh_folder(self):
        """
        :return: Where the working mesh scenes go.
        :rtype: str
        """

        return self.get_required_path('SRC_MODELS_PATH')

    @src_mesh_folder.setter
    def src_mesh_folder(self, path):
        self.set_required_path('SRC_MODELS_PATH', path)

    @property
    def src_animations_folder(self):
        """
        :return: Where the working animation scenes go.
        :rtype: str
        """

        return self.get_required_path('SRC_ANIMATIONS_PATH')

    @src_animations_folder.setter
    def src_animations_folder(self, path):
        self.set_required_path('SRC_ANIMATIONS_PATH', path)


class GlobalData(object):
    """
    The ``_Global`` block: what every category shares.
    """

    GLOBAL_KEY = '_Global'

    SKELETONS_KEY = 'SKELETONS'
    BODY_TYPES_KEY = 'BODY_TYPES'
    SLOTS_KEY = 'SLOTS'
    ATTACH_SOCKETS_KEY = 'ATTACH_SOCKETS'
    ASSET_TYPES_KEY = 'ASSET_TYPES'

    def __init__(self, global_dict=None):
        """
        :param dict global_dict: The block, as it is stored.
        """

        self._global_dict = global_dict if global_dict is not None else {}

    @property
    def global_dict(self):
        """
        :return: The block as it is stored, which is what gets written back out.
        :rtype: dict
        """

        return self._global_dict

    def _list(self, key):
        """
        :param str key: Which list.
        :return: A copy of it.
        :rtype: list
        """

        return list(self._global_dict.get(key) or [])

    def _set_list(self, key, values):
        """
        :param str key: Which list.
        :param values: What it should hold.
        """

        self._global_dict[key] = sorted(set(values))

    def _add_to(self, key, value):
        """
        :param str key: Which list.
        :param str value: What to add.
        :return: Whether it was added.
        :rtype: bool
        """

        if not value or value in self._list(key):
            return False
        self._set_list(key, self._list(key) + [value])

        return True

    def _remove_from(self, key, value):
        """
        :param str key: Which list.
        :param str value: What to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        current = self._list(key)
        if value not in current:
            return False
        current.remove(value)
        self._global_dict[key] = current

        return True

    @property
    def skeletons(self):
        """
        :return: Every skeleton the project rigs to.
        :rtype: list[str]
        """

        return self._list(self.SKELETONS_KEY)

    @skeletons.setter
    def skeletons(self, list_value):
        self._set_list(self.SKELETONS_KEY, list_value)

    def add_skeleton(self, skeleton):
        """
        :param str skeleton: One to add.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add_to(self.SKELETONS_KEY, skeleton)

    def remove_skeleton(self, skeleton):
        """
        :param str skeleton: One to take away. Any body type using it is taken away with it.
        :return: Whether it was there.
        :rtype: bool
        """

        if not self._remove_from(self.SKELETONS_KEY, skeleton):
            return False

        for body_type, used in list(self.body_types.items()):
            if used == skeleton:
                self.remove_body_type(body_type)

        return True

    @property
    def body_types(self):
        """
        :return: Body type to the skeleton it uses.
        :rtype: dict
        """

        return dict(self._global_dict.get(self.BODY_TYPES_KEY) or {})

    @body_types.setter
    def body_types(self, dict_value):
        self._global_dict[self.BODY_TYPES_KEY] = dict(dict_value)

    def add_body_type(self, body_type, skeleton):
        """
        :param str body_type: What to call it.
        :param str skeleton: The skeleton it uses, which is registered too if it is new.
        :return: Whether it was added.
        :rtype: bool
        """

        if not body_type or not skeleton:
            return False

        types = self.body_types
        types[body_type] = skeleton
        self.body_types = types
        self.add_skeleton(skeleton)

        return True

    def remove_body_type(self, body_type):
        """
        :param str body_type: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        types = self.body_types
        if body_type not in types:
            return False
        types.pop(body_type)
        self.body_types = types

        return True

    @property
    def slots(self):
        """
        :return: Where gear can go on a character - ``Head``, ``Chest``, ``WeaponRight``.
        :rtype: list[str]
        """

        return self._list(self.SLOTS_KEY)

    @slots.setter
    def slots(self, list_value):
        self._set_list(self.SLOTS_KEY, list_value)

    def add_slot(self, slot):
        """
        :param str slot: One to add.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add_to(self.SLOTS_KEY, slot)

    def remove_slot(self, slot):
        """
        :param str slot: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._remove_from(self.SLOTS_KEY, slot)

    @property
    def attach_sockets(self):
        """
        :return: The sockets on a skeleton something can be attached to.
        :rtype: list[str]
        """

        return self._list(self.ATTACH_SOCKETS_KEY)

    @attach_sockets.setter
    def attach_sockets(self, list_value):
        self._set_list(self.ATTACH_SOCKETS_KEY, list_value)

    def add_attach_socket(self, socket):
        """
        :param str socket: One to add.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add_to(self.ATTACH_SOCKETS_KEY, socket)

    def remove_attach_socket(self, socket):
        """
        :param str socket: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._remove_from(self.ATTACH_SOCKETS_KEY, socket)

    @property
    def asset_types(self):
        """
        :return: What an asset can be - ``SkeletalMesh``, ``StaticMesh``, ``Material``.
        :rtype: list[str]
        """

        return self._list(self.ASSET_TYPES_KEY)

    @asset_types.setter
    def asset_types(self, list_value):
        self._set_list(self.ASSET_TYPES_KEY, list_value)

    def add_asset_type(self, asset_type):
        """
        :param str asset_type: One to add.
        :return: Whether it was added.
        :rtype: bool
        """

        return self._add_to(self.ASSET_TYPES_KEY, asset_type)

    def remove_asset_type(self, asset_type):
        """
        :param str asset_type: One to take away.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._remove_from(self.ASSET_TYPES_KEY, asset_type)


class AssetDictData(object):
    """
    The project's ``asset_data.config``: every category, and the ``_Global`` block.
    """

    def __init__(self, asset_dict=None):
        """
        :param dict asset_dict: The file's contents, or None to start from the framework's
            seed.
        """

        # A copy: the version this replaces popped '_Global' out of the dictionary it was
        # handed, so the caller's own copy of the file quietly lost its global block.
        self._asset_dict = dict(asset_dict) if asset_dict else seed_dictionary()
        self._global_data = GlobalData(self._asset_dict.pop(GlobalData.GLOBAL_KEY, {}) or {})

    @property
    def asset_dict(self):
        """
        :return: Every category, by name. Without the ``_Global`` block, which is
            :attr:`global_data`.
        :rtype: dict
        """

        return self._asset_dict

    @property
    def global_data(self):
        """
        :return: What every category shares.
        :rtype: GlobalData
        """

        return self._global_data

    @property
    def categories_names(self):
        """
        :return: Every category's name, in order.
        :rtype: list[str]
        """

        return list(self._asset_dict.keys())

    @property
    def categories(self):
        """
        :return: Every category.
        :rtype: list[CategoryData]
        """

        return self.get_categories()

    def get_categories(self):
        """
        :return: Every category, each wrapping the block the file holds - so changing one
            changes the file.
        :rtype: list[CategoryData]
        """

        return [CategoryData({name: block}) for name, block in self._asset_dict.items()]

    def get_category_data(self, category):
        """
        :param str category: A category name.
        :return: It, or None. Changes to it are changes to this file.
        :rtype: CategoryData or None
        """

        if category not in self._asset_dict:
            return None

        return CategoryData({category: self._asset_dict[category]})

    def update_category(self, category_data):
        """
        Put a category back.

        :param CategoryData category_data: The one to store.
        :return: Whether anything was stored.
        :rtype: bool

        The version this replaces rebuilt the whole dictionary from its list of categories to
        do this, which reordered the file and dropped any category the list had not been
        rebuilt to include.
        """

        if not category_data or not category_data.category:
            return False

        self._asset_dict[category_data.category] = category_data.category_dict[category_data.category]

        return True

    def add_category(self, name, is_gear=False, gear_root='', subcategories=(), factions=()):
        """
        Make a new category.

        :param str name: What to call it.
        :param bool is_gear: Whether its assets are worn or carried.
        :param str gear_root: Where its paths start, when it is gear.
        :param subcategories: The subcategories it starts with.
        :param factions: The factions it starts with.
        :return: Whether it was made. False when it is already there. Nothing is written to
            disk: call :meth:`save`.
        :rtype: bool
        """

        if not name or name in self._asset_dict:
            return False

        self._asset_dict[name] = new_category_block(subcategories=subcategories,
                                                    is_gear=is_gear,
                                                    gear_root=gear_root,
                                                    factions=factions)

        return True

    def remove_category(self, name):
        """
        :param str name: One to take away. The assets in it are not touched - this is the
            category list, not the registry.
        :return: Whether it was there.
        :rtype: bool
        """

        return self._asset_dict.pop(name, None) is not None

    # -- the file ------------------------------------------------------- #
    @classmethod
    def file_path(cls):
        """
        :return: Where the file is, or ``''`` when there is no project.
        :rtype: str
        """

        assetlist = paths.get_asset_list_path()
        if not assetlist:
            return ''

        return os.path.normpath(os.path.join(assetlist, ASSET_DATA_FILE))

    @classmethod
    def load(cls, force=False):
        """
        The project's category data.

        :param bool force: Read the file again rather than answering with what was read
            before.
        :return: It. A project with no file yet gets one, written from the framework's seed.
        :rtype: AssetDictData

        **Read once.** ``unified_entry`` asks for this while working out one asset's folder,
        so the version this replaces parsed the YAML once per asset - several hundred times to
        build a registry. :func:`reload` is how a change made elsewhere is picked up.
        """

        global _LOADED
        if _LOADED is not None and not force:
            return _LOADED

        file_path = cls.file_path()
        if not file_path:
            logger.warning('There is no project, so the asset categories are the framework\'s '
                           'defaults and nothing will be saved.')
            _LOADED = cls()
            return _LOADED

        if not os.path.isfile(file_path):
            logger.info('Starting a new asset category file: %s', file_path)
            _LOADED = cls()
            _LOADED.save()
            return _LOADED

        asset_dict = yamlio.read_yaml_file(filename=file_path)
        if not isinstance(asset_dict, dict):
            logger.error('The asset category file could not be read, so the framework\'s '
                         'defaults are being used: %s', file_path)
            _LOADED = cls()
            return _LOADED

        instance = cls(asset_dict)

        # A category added to the framework's seed after this project's file was written has
        # to be put into it, or it only ever appears on a fresh checkout. What is already
        # there is left exactly as it is: those are artists' edits.
        added = [name for name in seed_dictionary() if name not in instance.asset_dict]
        for name in added:
            instance.asset_dict[name] = seed_dictionary()[name]
        if added:
            logger.info('Added missing categories to %s: %s', ASSET_DATA_FILE, ', '.join(added))
            instance.save()

        _LOADED = instance

        return _LOADED

    def save(self):
        """
        Write the file.

        :return: Whether it was written.
        :rtype: bool
        """

        file_path = self.file_path()
        if not file_path:
            logger.warning('There is no project, so the asset categories were not saved.')
            return False

        contents = {GlobalData.GLOBAL_KEY: self._global_data.global_dict}
        contents.update(self._asset_dict)

        fileio.touch_path(file_path)
        # The version this replaces called fileio.touch_and_checkout, which reached into
        # Perforce from a file-writing helper. Which source control this is, if any, is the
        # interface's business now.
        sourcecontrol.checkout(file_path)
        yamlio.write_to_yaml_file(contents, file_path)

        return True


def reload():
    """
    Forget the category data that was read, so the next question reads the file again.

    :return: What it says now.
    :rtype: AssetDictData
    """

    global _LOADED
    _LOADED = None

    return AssetDictData.load()
