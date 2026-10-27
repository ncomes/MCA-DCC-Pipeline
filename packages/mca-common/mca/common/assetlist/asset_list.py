"""
What every asset in the registry has, whatever kind of asset it is.

:class:`AssetBaseEntry` is one asset's record: its id, its name, its category, where it lives,
and the folders inside it. A subclass says how a folder is worked out - :class:`UnifiedAssetEntry`
in :mod:`unified_entry` is the one the registry uses - and everything else is here.

What changed:

- **The record now knows its own id.** An entry is stored as a dictionary of one key, the asset
  id, to the asset's fields, and every single property in the version this replaces re-derived
  that id by listing the dictionary's keys and taking the first - on every read of every
  attribute. The id is worked out once, and the fields are held directly.
- **An unset path answered None** out of two properties documented to answer a string, after
  logging a warning, so a caller joining onto it got ``TypeError: expected str, not
  NoneType`` a long way from the asset that had no path. They answer ``''``.
- **Two setters did nothing at all.** ``sm_path`` and ``sk_path`` each stored what they were
  given in ``self._sm_path`` / ``self._sk_path``, and their getters rebuilt the path from the
  asset's name and never read either. Setting one and reading it back gave the old value.
- **The abstract methods were not abstract.** ``@abc.abstractmethod`` does nothing on a class
  that is not an ABC, so ``AssetBaseEntry`` could be built directly and ``get_required_path``
  answered None - which every folder property then joined onto.
- ``create_folders`` called ``fileio.touch_and_checkout``, which reached into Perforce from a
  file helper; it goes through the source control interface now, and it makes the folders from
  full paths rather than relative ones.
"""

# python imports
import abc
import os

# MCA python imports
from mca.common import log
from mca.common import sourcecontrol
from mca.common.assetlist import asset_paths, asset_prefixes
from mca.common.paths import path_utils, paths, project_paths
from mca.common.utils import fileio


logger = log.MCA_LOGGER

def _art_root():
    """
    The folder an asset's relative path is relative to.

    Assets are recorded relative to the art root, not the project root. In the original
    depot those were the same folder, so joining onto the project root worked by accident;
    in a project that keeps its art in a subfolder it silently pointed one level too high
    and every asset reported a folder that does not exist.

    :return: The art root, or the project root when no art path is set.
    :rtype: str
    """

    return project_paths.get_art_path() or paths.project_root()


class AssetBaseEntry(object, metaclass=abc.ABCMeta):
    """
    One asset in the registry.

    Stored as ``{asset_id: {field: value}}``, which is how it goes into the registry file, so
    :attr:`asset_dict` hands back the dictionary the registry holds and changes made through
    this record are changes to it.
    """

    def __init__(self, asset_dict):
        """
        :param dict asset_dict: ``{asset_id: fields}`` - one key.
        :raises ValueError: When it is empty. An entry with no id is not an entry, and every
            property in the version this replaces would have raised further along anyway.
        """

        if not asset_dict:
            raise ValueError('An asset entry needs an id and some fields.')

        self._asset_dict = asset_dict
        self._asset_id = next(iter(asset_dict))
        if len(asset_dict) > 1:
            logger.warning('The asset entry %s was given %s ids and is using the first.',
                           self._asset_id, len(asset_dict))
        self._fields = asset_dict[self._asset_id]
        if self._fields is None:
            self._fields = {}
            asset_dict[self._asset_id] = self._fields

    def __repr__(self):
        return '{0}({1!r}, {2!r})'.format(type(self).__name__, self._asset_id, self.name)

    @property
    def asset_dict(self):
        """
        :return: The entry as the registry stores it, ``{asset_id: fields}``.
        :rtype: dict
        """

        return self._asset_dict

    @property
    def fields(self):
        """
        :return: Just this asset's fields, which is what every property reads.
        :rtype: dict
        """

        return self._fields

    @property
    def asset_id(self):
        """
        :return: The asset's id.
        :rtype: str
        """

        return self._asset_id

    # -- what it is ----------------------------------------------------- #
    @property
    def name(self):
        """
        :return: What it is called, or ``''``.
        :rtype: str
        """

        return self._fields.get('name') or ''

    @name.setter
    def name(self, value):
        self._fields['name'] = value

    @property
    def file_name(self):
        """
        :return: Its name as it appears in a file name: lower case, spaces as underscores.
            ``''`` for an asset with no name, where the version this replaces raised
            AttributeError on None.
        :rtype: str
        """

        return self.name.lower().replace(' ', '_')

    @property
    def category(self):
        """
        :return: Its category - ``Characters``, ``Props``.
        :rtype: str
        """

        return self._fields.get('category') or ''

    @category.setter
    def category(self, value):
        self._fields['category'] = value

    @property
    def namespace(self):
        """
        :return: The namespace its nodes are brought into a scene under.
        :rtype: str
        """

        return self._fields.get('namespace') or ''

    @namespace.setter
    def namespace(self, value):
        self._fields['namespace'] = value

    @property
    def faction(self):
        """
        :return: Which faction it belongs to, or ``''``.
        :rtype: str
        """

        return self._fields.get('faction') or ''

    @faction.setter
    def faction(self, value):
        self._fields['faction'] = value

    @property
    def gender(self):
        """
        :return: Its gender tag - ``Male``, ``Female``, ``Neutral`` or ``''``. A label only:
            it has no effect on where anything is stored.
        :rtype: str
        """

        return self._fields.get('gender') or ''

    @gender.setter
    def gender(self, value):
        self._fields['gender'] = value

    @property
    def asset_type(self):
        """
        :return: What kind of thing it is - ``SkeletalMesh``, ``StaticMesh``.
        :rtype: str
        """

        return self._fields.get('type') or ''

    @asset_type.setter
    def asset_type(self, value):
        self._fields['type'] = value

    @property
    def archetype(self):
        """
        :return: Its archetype, or ``''``.
        :rtype: str
        """

        return self._fields.get('archetype') or ''

    @archetype.setter
    def archetype(self, value):
        self._fields['archetype'] = value

    @property
    def parent(self):
        """
        :return: The id of the asset this one belongs to - a hat's character - or ``''``.
        :rtype: str
        """

        return self._fields.get('parent') or ''

    @parent.setter
    def parent(self, value):
        self._fields['parent'] = value

    # -- where it is ---------------------------------------------------- #
    @property
    def path(self):
        """
        :return: Where it lives, relative to the project, or ``''``.
        :rtype: str
        """

        path = self._fields.get('path') or ''
        if not path:
            logger.debug('The asset "%s" has no path registered.', self.name or self.asset_id)

        return path

    @path.setter
    def path(self, value):
        self._fields['path'] = path_utils.to_relative_path(value)

    @property
    def full_path(self):
        """
        :return: Where it lives on this machine, or ``''``.
        :rtype: str
        """

        path = self.path
        if not path:
            return ''

        return path_utils.to_full_path(path, added_path=_art_root() or None)

    # -- the folders inside it ------------------------------------------ #
    @abc.abstractmethod
    def get_required_path(self, path_name):
        """
        Where one of this asset's folders is.

        :param str path_name: A key - ``'RIGS_PATH'``, ``'SRC_MODELS_PATH'``.
        :return: The full path, or ``''``.
        :rtype: str
        """

    @property
    def rigs_path(self):
        """
        :return: Where its built rigs go.
        :rtype: str
        """

        return self.get_required_path('RIGS_PATH')

    @property
    def flags_path(self):
        """
        :return: Where its animation controls go, which is a folder inside the source rigs.
        :rtype: str
        """

        source = self.src_rig_path
        if not source:
            return ''

        return os.path.normpath(os.path.join(source, asset_paths.FLAGS_FOLDER))

    @property
    def models_path(self):
        """
        :return: Where its exported meshes go.
        :rtype: str
        """

        return self.get_required_path('MODELS_PATH')

    @property
    def textures_path(self):
        """
        :return: Where its textures go.
        :rtype: str
        """

        return self.get_required_path('TEXTURES_PATH')

    @property
    def animations_path(self):
        """
        :return: Where its exported animations go.
        :rtype: str
        """

        return self.get_required_path('ANIMATIONS_PATH')

    @property
    def src_rig_path(self):
        """
        :return: Where its working rig scenes go.
        :rtype: str
        """

        return self.get_required_path('SRC_RIGS_PATH')

    @property
    def src_models_path(self):
        """
        :return: Where its working mesh scenes go.
        :rtype: str
        """

        return self.get_required_path('SRC_MODELS_PATH')

    @property
    def src_animations_path(self):
        """
        :return: Where its working animation scenes go.
        :rtype: str
        """

        return self.get_required_path('SRC_ANIMATIONS_PATH')

    # -- the files in it ------------------------------------------------ #
    @property
    def sm_path(self):
        """
        :return: Its static mesh, or ``''`` when there is nowhere to put one. A path that was
            set with :attr:`sm_path` is answered as given; otherwise it is built from the
            asset's name.
        :rtype: str
        """

        recorded = self._fields.get('sm_path') or ''
        if recorded:
            return os.path.normpath(recorded)

        models = self.models_path
        if not models:
            return ''

        return os.path.normpath(os.path.join(models, '{0}{1}.fbx'.format(asset_prefixes.SM, self.name)))

    @sm_path.setter
    def sm_path(self, value):
        self._fields['sm_path'] = path_utils.to_relative_path(value)

    @property
    def sk_path(self):
        """
        :return: Its skeletal mesh, or ``''``. As with :attr:`sm_path`, a recorded path wins
            over one built from the name.
        :rtype: str
        """

        recorded = self._fields.get('sk_path') or ''
        if recorded:
            return os.path.normpath(recorded)

        models = self.models_path
        if not models:
            return ''

        return os.path.normpath(os.path.join(models, '{0}{1}.fbx'.format(asset_prefixes.SK, self.name)))

    @sk_path.setter
    def sk_path(self, value):
        self._fields['sk_path'] = path_utils.to_relative_path(value)

    @property
    def sm_fullpath(self):
        """
        :return: Its static mesh on this machine, or ``''``.
        :rtype: str
        """

        return self._on_this_machine(self.sm_path)

    @property
    def sk_fullpath(self):
        """
        :return: Its skeletal mesh on this machine, or ``''``.
        :rtype: str
        """

        return self._on_this_machine(self.sk_path)

    @property
    def skin_path(self):
        """
        :return: The file its skinning is exported to, beside its static mesh, or ``''``.
        :rtype: str
        """

        full = self.sm_fullpath
        if not full:
            return ''

        # os.path.splitext, where the version this replaces split the whole path on '.' and
        # joined all but the last piece back together.
        return os.path.splitext(full)[0] + '_skn.fbx'

    def _on_this_machine(self, relative_path):
        """
        :param str relative_path: A path relative to the project.
        :return: It, on this machine, or ``''`` when either half is missing.
        :rtype: str
        """

        if not relative_path:
            return ''
        if os.path.isabs(relative_path):
            return os.path.normpath(relative_path)

        root = _art_root()
        if not root:
            return ''

        return os.path.normpath(os.path.join(root, relative_path))

    def get_rig_list(self):
        """
        Every Maya rig file this asset has.

        Looks in its source rigs folder for ``*_rig.ma`` files whose names contain every word
        of the asset's name. A rig the asset names itself comes first, so tooling opens the
        one it was told about rather than whatever the search turned up.

        :return: Full paths, newest first not promised. Empty when there is no folder or
            nothing in it matches.
        :rtype: list[str]
        """

        recorded = ''
        resolve = getattr(self, 'resolve_file', None)
        if callable(resolve):
            recorded = resolve('rig') or ''

        source = self.src_rig_path
        rigs = []
        if source and os.path.isdir(source):
            tokens = [token for token in self.name.lower().replace('_', ' ').split(' ') if token]
            rigs = [found for found in path_utils.all_file_types_in_directory(source, '.ma')
                    if found.lower().endswith('_rig.ma')
                    and all(token in os.path.basename(found).lower() for token in tokens)]

        if recorded:
            rigs = [recorded] + [found for found in rigs
                                 if os.path.normcase(found) != os.path.normcase(recorded)]

        return rigs

    # -- making and unmaking -------------------------------------------- #
    def create_folders(self):
        """
        Make the folders this asset needs, and check them out where source control wants that.

        :return: The folders made.
        :rtype: list[str]

        The version this replaces appended a literal ``'\\\\'`` to each path to keep the last
        folder from being read as a file name, and handed the result to
        ``fileio.touch_and_checkout`` - which is Perforce, called out of a file helper. It also
        used the folders' *relative* paths, so on any machine whose working directory was not
        the project root it made them somewhere else entirely.
        """

        wanted = [self.src_models_path, self.src_animations_path, self.textures_path,
                  self.src_rig_path]
        made = []
        for folder in wanted:
            if not folder:
                continue
            folder = self._on_this_machine(folder)
            if not folder:
                continue
            if not os.path.isdir(folder):
                try:
                    os.makedirs(folder)
                except OSError as error:
                    logger.warning('Could not make %s: %s', folder, error)
                    continue
            made.append(folder)

        if made:
            sourcecontrol.checkout(made)

        return made

    @abc.abstractmethod
    def remove_from_assetlist(self):
        """
        Take this asset out of the registry.

        :return: Whether it was there.
        :rtype: bool
        """


def touch_and_checkout(file_path):
    """
    Make a file's folder, make the file writable, and check it out.

    :param str file_path: The file about to be written.
    :return: The path.
    :rtype: str

    This is the shape of the ``fileio.touch_and_checkout`` that the registry used to call, kept
    here - beside the code that wants it - rather than in ``fileio``, which has no business
    knowing what source control is.
    """

    fileio.touch_path(file_path)
    sourcecontrol.checkout(file_path)

    return file_path
