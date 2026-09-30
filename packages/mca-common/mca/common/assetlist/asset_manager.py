"""
Every asset in the project, read once and indexed: by id, by name, by category, and by what
belongs to what.

```python
from mca.common.assetlist import asset_manager

manager = asset_manager.get_asset_manager()
hero = manager.get_record_by_name('Hero Bot')
for gear in manager.iter_children(hero.asset_id):
    ...
```

The read layer. It loads the categories the project's ``categories.json`` declares, reads each
one's ``.alist`` file, and builds an :class:`AssetRecord` per asset - a frozen snapshot, so
nothing here can change what is on disk. Writing is :mod:`unified_registry`'s job.

What changed:

- **Cycles were only looked for from the roots.** ``_validate`` walked down from every root
  asset, so a cycle that is not reachable from one - A's parent is B and B's parent is A, where
  neither is a root - was never visited. The cycles that can hang a rig build are exactly the
  ones nothing could find. Every record is a starting point now.
- **Two assets sharing a display name went unreported.** ``get_record_by_name`` answers the
  first one loaded and the other becomes unreachable by name, which is how an artist ends up
  building the wrong asset. The validation report says so now, beside the duplicate namespaces
  it already reported.
- ``get_required_path`` answered None behind ``except Exception``, and the folder properties
  built on it are documented to answer a path. They answer ``''``.
- The messages that told an artist to run ``migrate_to_unified`` name something that is not
  here any more: that conversion has been run, and the script stayed in the depot's history.
"""

from __future__ import annotations

import dataclasses
import os
from collections import defaultdict
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Set

from mca.common import log
from mca.common import sourcecontrol
from mca.common.assetlist import unified_entry
from mca.common.paths import paths
from mca.common.textio import alistio, jsonio
from mca.common.utils import fileio

logger = log.MCA_LOGGER

#: What the file listing a project's categories is called, for saying so in a message.
CATEGORIES_MANIFEST = 'categories.json'

_CORE_KEYS = {
    "name",
    "category",
    "type",
    "subtype",
    "namespace",
    "parent",
    "parent_category",
    "path",
    "faction",
    "archetype",
    "local_asset_list",
}


@dataclasses.dataclass(frozen=True)
class AssetRecord:
    """
    Immutable runtime representation of a single asset entry.

    The record mirrors the contents of the `.alist` definition while providing
    convenience properties for hierarchy traversal and filesystem resolution.
    """

    asset_id: str
    name: str
    category: str
    type: Optional[str]
    subtype: Optional[str]
    namespace: Optional[str]
    faction: Optional[str]
    parent_id: Optional[str]
    parent_category: Optional[str]
    relative_path: Optional[str]
    resolved_path: Optional[str]
    full_path: Optional[str]
    # The UnifiedAssetEntry this record was built from. Path helpers below
    # delegate to it via get_required_path().
    source_entry: Optional["unified_entry.UnifiedAssetEntry"] = dataclasses.field(
        default=None, repr=False, compare=False)
    raw: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    # --- Gear-specific fields (default None for non-gear assets) ---------- #
    slot: Optional[str] = None
    engine_path: Optional[str] = None
    # The first parent, kept as a plain string for callers that predate
    # multi-parent gear. built_for_all carries every parent.
    built_for: Optional[str] = None
    built_for_all: Sequence[str] = dataclasses.field(default_factory=tuple)
    parent_ids: Sequence[str] = dataclasses.field(default_factory=tuple)
    # A whole-character restyle names its base here, by asset id. See
    # UnifiedAssetEntry.variant_of for why this is an id and built_for is a name.
    variant_of: Optional[str] = None
    skeleton: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    attach_sockets: Optional[Sequence[str]] = None

    # --- Unified format fields (added for the new registration system) ---- #
    body_type: Optional[str] = None
    additional_types: Optional[Sequence[str]] = None
    asset_type: Optional[str] = None
    engine_textures: Optional[Sequence[str]] = None

    @classmethod
    def from_unified_entry(cls, entry, category_override=None):
        """
        Build a record instance from a :class:`UnifiedAssetEntry`.

        Populates all fields including the unified-format additions
        (body_type, additional_types, asset_type, engine_textures).

        :param entry: Source unified entry.
        :param str category_override: Explicit category override.
        :return: Immutable record representing the asset.
        :rtype: AssetRecord
        """

        data = entry.fields
        category = data.get("category") or category_override

        # These answer '' rather than raising, so there is nothing to guard against here;
        # the version this replaces wrapped each in `except Exception`.
        resolved_path = entry.path
        full_path = entry.full_path

        # Determine parent from 'parent' field or leave for built_for resolution
        parent_id = data.get("parent") or None
        # built_for is a name or a list of names; the entry normalises both.
        built_for_names = tuple(entry.built_for_all)
        built_for_value = built_for_names[0] if built_for_names else ""

        return cls(
            asset_id=entry.asset_id,
            name=entry.name,
            category=category or "",
            type=data.get("type") or data.get("asset_type", "SkeletalMesh"),
            subtype=data.get("subtype"),
            namespace=data.get("namespace"),
            faction=data.get("faction"),
            parent_id=parent_id,
            parent_category=data.get("parent_category") or category,
            relative_path=data.get("path"),
            resolved_path=resolved_path,
            full_path=full_path,
            raw=dict(data),
            source_entry=entry,
            slot=data.get("slot", ""),
            engine_path=data.get("engine_path", ""),
            built_for=built_for_value,
            built_for_all=built_for_names,
            variant_of=entry.variant_of or None,
            skeleton=data.get("skeleton", ""),
            description=data.get("description", ""),
            image=data.get("image", ""),
            attach_sockets=data.get("attach_sockets"),
            body_type=data.get("body_type", ""),
            additional_types=data.get("additional_types"),
            asset_type=data.get("asset_type", ""),
            engine_textures=data.get("engine_textures"),
        )

    @property
    def archetype(self) -> Optional[str]:
        """
        Accessor for the archetype field when present.

        :return: Archetype identifier or None.
        :rtype: str or None
        """

        return self.raw.get("archetype")

    @property
    def local_asset_list(self) -> Sequence[str]:
        """
        Local asset list declared on this record.

        :return: Sequence of asset ids declared as local assets.
        :rtype: Sequence[str]
        """

        value = self.raw.get("local_asset_list", [])
        if isinstance(value, (list, tuple)):
            return value
        return [value]

    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Dictionary of dynamically defined fields stored on the record.

        :return: Mapping excluding standard keys.
        :rtype: dict
        """

        return {key: value for key, value in self.raw.items() if key not in _CORE_KEYS}

    @property
    def path(self) -> Optional[str]:
        """
        Relative asset path as defined in the registry.
        """

        return self.relative_path

    @property
    def asset_subtype(self) -> Optional[str]:
        """
        Compatibility accessor mirroring :attr:`AssetEntry.asset_subtype`.
        """

        return self.subtype

    def get_required_path(self, path_name: str) -> str:
        """
        Where one of this asset's folders is.

        :param str path_name: A key - ``'ANIMATIONS_PATH'``, ``'SRC_RIGS_PATH'``.
        :return: The full path, or ``''``.
        :rtype: str
        """

        if not self.source_entry:
            return ''

        return self.source_entry.get_required_path(path_name)

    @property
    def animations_path(self) -> str:
        """
        Relative animations path for this asset, matching the legacy API.
        """

        return self.get_required_path("ANIMATIONS_PATH")

    @property
    def src_rig_path(self) -> str:
        """
        Source rig path helper to maintain backwards compatibility.
        """

        return self.get_required_path("SRC_RIGS_PATH")

    @property
    def models_path(self) -> str:
        """
        Model path helper mirroring :class:`AssetEntry`.
        """

        return self.get_required_path("MODELS_PATH")

    @property
    def textures_path(self) -> str:
        """
        Texture path helper mirroring :class:`AssetEntry`.
        """

        return self.get_required_path("TEXTURES_PATH")

    @property
    def rigs_path(self) -> str:
        """
        Rigs directory path.

        :return: Full path to the rigs folder.
        :rtype: str or None
        """

        return self.get_required_path("RIGS_PATH")

    @property
    def flags_path(self) -> str:
        """
        Flags directory path.

        :return: Full path to the flags folder.
        :rtype: str or None
        """

        return self.get_required_path("FLAGS_PATH")

    @property
    def skin_data_path(self) -> str:
        """
        Skin weights data directory path.

        Returns the path to the skin data folder where skinning weight files
        are stored. This is typically located at ``{src_rigs_path}/Skin_Data``.

        :return: Full path to the skin data folder.
        :rtype: str or None
        """

        src_rigs = self.get_required_path("SRC_RIGS_PATH")
        if not src_rigs:
            return ''

        return os.path.join(src_rigs, "Skin_Data")

    @property
    def skin_path(self) -> str:
        """
        Skinning FBX file path.

        Returns the path to the skinning FBX file used for weight transfer.
        This is typically derived from the source models path.

        :return: Full path to the skinning FBX file.
        :rtype: str or None
        """

        if not self.source_entry:
            return ''

        return getattr(self.source_entry, "skin_path", '') or ''

    def __getattr__(self, item: str) -> Any:
        """
        Delegate attribute access to the original :class:`AssetEntry` when
        possible so legacy callers can rely on existing helpers.
        """

        if self.source_entry and hasattr(self.source_entry, item):
            return getattr(self.source_entry, item)
        raise AttributeError(f"{self.__class__.__name__} object has no attribute '{item}'")

    def to_serializable(self) -> Dict[str, Any]:
        """
        Merge the canonical fields back into a serializable dictionary.

        :return: Dictionary suitable for writing back to disk.
        :rtype: dict
        """

        data = dict(self.raw)
        data.update(
            {
                "name": self.name,
                "category": self.category,
                "type": self.type,
                "subtype": self.subtype,
                "namespace": self.namespace,
                "faction": self.faction,
                "parent": self.parent_id,
                "parent_category": self.parent_category,
                "path": self.relative_path,
            }
        )
        # Include unified-format fields when present
        if self.body_type is not None:
            data["body_type"] = self.body_type
        if self.additional_types is not None:
            data["additional_types"] = list(self.additional_types)
        if self.asset_type is not None:
            data["asset_type"] = self.asset_type
        if self.engine_textures is not None:
            data["engine_textures"] = list(self.engine_textures)
        return data


@dataclasses.dataclass
class AssetValidationReport:
    """
    Summary of validation results generated by :class:`AssetManager`.
    """

    missing_required_fields: Dict[str, Set[str]] = dataclasses.field(default_factory=dict)
    dangling_parents: Dict[str, str] = dataclasses.field(default_factory=dict)
    duplicate_namespaces: Dict[str, Set[str]] = dataclasses.field(default_factory=dict)
    #: Display names that more than one asset answers to. Only the first is reachable by
    #: name, so the others are assets an artist can see in a list and cannot open.
    duplicate_names: Dict[str, Set[str]] = dataclasses.field(default_factory=dict)
    cyclic_dependencies: List[List[str]] = dataclasses.field(default_factory=list)

    def is_valid(self) -> bool:
        """
        Convenience helper that returns True when no issues were captured.

        :return: True if no warnings/errors were detected.
        :rtype: bool
        """

        return not (
            self.missing_required_fields
            or self.dangling_parents
            or self.duplicate_namespaces
            or self.duplicate_names
            or self.cyclic_dependencies
        )


class AssetManager:
    """
    Aggregates all `.alist` files into an indexed, queryable view.

    The manager exposes helpers to look up assets by id/category, walk parent
    chains, and validate the dataset. It does not mutate registry files; write
    helpers can be layered on top if needed.
    """

    def __init__(self, run_validation: bool = True):
        self._records_by_id: Dict[str, AssetRecord] = {}
        self._records_by_name: Dict[str, AssetRecord] = {}
        self._records_by_category: Dict[str, Dict[str, List[AssetRecord]]] = defaultdict(lambda: defaultdict(list))
        self._children_by_parent: Dict[Optional[str], List[AssetRecord]] = defaultdict(list)
        self._variants_by_base: Dict[str, List[AssetRecord]] = defaultdict(list)
        self._roots: Set[str] = set()
        self._validation_report: Optional[AssetValidationReport] = None
        self.reload(run_validation=run_validation)

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #
    def reload(self, run_validation: bool = True) -> None:
        """
        Reload assets from disk and rebuild indexes.

        :param bool run_validation: Whether to rerun validation after the load.
        """

        self._records_by_id.clear()
        self._records_by_category.clear()
        self._records_by_name.clear()
        self._children_by_parent.clear()
        self._variants_by_base.clear()
        self._roots.clear()

        self._collect_asset_records()

        if run_validation:
            self._validation_report = self._validate()
        else:
            self._validation_report = None

    def iter_all(self) -> Iterator[AssetRecord]:
        """
        Iterate across every loaded asset record.

        :return: Iterator of all records.
        :rtype: Iterator[AssetRecord]
        """

        return iter(self._records_by_id.values())

    def get_record(self, asset_id: str) -> Optional[AssetRecord]:
        """
        Fetch a record by asset id.

        :param str asset_id: Unique asset identifier.
        :return: Matching record or None.
        :rtype: AssetRecord or None
        """

        return self._records_by_id.get(asset_id)

    def get_record_by_name(self, asset_name: str) -> Optional[AssetRecord]:
        """
        Fetch a record by its display name (case-insensitive).

        :param str asset_name: Human-readable asset name.
        :return: Matching record or None.
        :rtype: AssetRecord or None
        """

        if not asset_name:
            return None
        record = self._records_by_name.get(asset_name.lower())
        if record:
            return record
        # Fallback to id lookup for legacy callers storing asset ids.
        return self._records_by_id.get(asset_name)

    def get_parent_chain(self, asset_id: str) -> List[AssetRecord]:
        """
        Collect a list of ancestors starting at the immediate parent.

        :param str asset_id: Child asset identifier.
        :return: Ancestors ordered from parent → root.
        :rtype: list[AssetRecord]
        """

        chain: List[AssetRecord] = []
        visited: Set[str] = set()
        current = self.get_record(asset_id)
        while current and current.parent_id:
            parent_id = current.parent_id
            if parent_id in visited:
                logger.warning("Cycle detected while building parent chain for '%s'", asset_id)
                break
            visited.add(parent_id)
            parent = self.get_record(parent_id)
            if not parent:
                break
            chain.append(parent)
            current = parent
        return chain

    def iter_children(self, asset_id: str) -> Iterator[AssetRecord]:
        """
        Iterate through immediate children of a given asset.

        :param str asset_id: Parent identifier.
        :return: Iterator yielding direct child records.
        :rtype: Iterator[AssetRecord]
        """

        for record in self._children_by_parent.get(asset_id, []):
            yield record

    def iter_descendants(self, asset_id: str) -> Iterator[AssetRecord]:
        """
        Depth-first traversal of all descendant records.

        :param str asset_id: Parent identifier.
        :return: Iterator across hierarchical descendants.
        :rtype: Iterator[AssetRecord]
        """

        # A record can be a child of several parents, so the same asset is
        # reachable by more than one route; seen keeps it to one yield.
        seen: Set[str] = {asset_id}
        stack: List[AssetRecord] = list(self._children_by_parent.get(asset_id, []))
        while stack:
            current = stack.pop()
            if current.asset_id in seen:
                continue
            seen.add(current.asset_id)
            yield current
            stack.extend(self._children_by_parent.get(current.asset_id, []))

    def iter_category(self, category: str, subtype: Optional[str] = None) -> Iterator[AssetRecord]:
        """
        Iterate all records for a category (optionally filtered by subtype).

        :param str category: Category name such as ``Characters`` or ``Gear``.
        :param str subtype: Optional subtype filter.
        :return: Iterator of matching records.
        """

        category_map = self._records_by_category.get(category)
        if not category_map:
            return iter(())

        if subtype is None:
            buckets = category_map.values()
        else:
            buckets = [category_map.get(subtype, [])]

        return iter(record for bucket in buckets for record in bucket)

    def get_roots(self, category: Optional[str] = None) -> List[AssetRecord]:
        """
        Return root assets (entries without a valid parent).

        :param str category: Optional category filter.
        :return: List of root records.
        :rtype: list[AssetRecord]
        """

        roots = [self._records_by_id[asset_id] for asset_id in self._roots]
        if category:
            return [record for record in roots if record.category == category]
        return roots

    @property
    def validation_report(self) -> Optional[AssetValidationReport]:
        """
        Latest validation report, if validation ran during ``reload``.

        :return: Validation report or None.
        :rtype: AssetValidationReport or None
        """

        return self._validation_report

    def to_json_serializable(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        Export a dictionary shaped for JSON serialization.

        :return: Nested dictionary keyed by category → asset_id → asset data.
        :rtype: dict
        """

        export: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        for record in self._records_by_id.values():
            export[record.category][record.asset_id] = record.to_serializable()
        return export

    # ---------------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------------- #
    def _collect_asset_records(self) -> None:
        """
        Load all asset records from the categories manifest.

        Reads ``categories.json`` to discover the categories, then loads the
        corresponding .alist files. Every entry is in the unified format, so
        there is a single ingestion path.
        """

        manifest = self._load_categories_manifest()

        if manifest:
            self._ingest_manifest_categories(manifest)
        else:
            # Without a manifest nothing can be located. The previous fallback
            # scanned the directories through the legacy registries; those are
            # gone, and categories.json is written by the migration.
            manifest_path = paths.get_categories_manifest_path()
            if not manifest_path:
                logger.warning('There is no project, so there are no assets to load.')
            else:
                logger.error(
                    'There is no category manifest at %s, so no assets could be loaded. A '
                    'project needs a categories.json listing its categories.', manifest_path)

        # Resolve built_for names to parent_id after all records are loaded.
        self._resolve_built_for_references()
        self._compute_roots()

    def _load_categories_manifest(self):
        """
        Load the categories.json manifest if it exists.

        :return: Parsed manifest dict, or None if the file is missing.
        :rtype: dict or None
        """

        manifest_path = paths.get_categories_manifest_path()
        if not os.path.isfile(manifest_path):
            logger.debug("No category manifest at %s.", manifest_path)
            return None

        manifest = alistio.read_alist_file(manifest_path)
        if not manifest:
            logger.warning("Categories manifest is empty: %s", manifest_path)
            return None

        return manifest

    def _ingest_manifest_categories(self, manifest):
        """
        Load asset records for every category the manifest declares.

        The manifest is the flat v2 layout: one ``categories`` list, each entry
        naming the folder its .alist file lives in. A v1 manifest
        (``primary_categories`` / ``gear_categories``) is reported rather than
        guessed at, because it means the migration has not been run and the
        gear half of the data would be read with the wrong precedence.

        :param dict manifest: The parsed categories.json manifest.
        """

        version = str(manifest.get('version', '1.0'))
        if not version.startswith('2'):
            logger.error(
                'categories.json says version %s, and this reads 2.x. No assets were loaded, '
                'rather than reading half the data with the wrong precedence. A registry '
                'still on the old layout has to be converted first.', version)
            return

        asset_list_root = paths.get_asset_list_path()
        declared = set()
        for category in manifest.get('categories', []):
            name = category.get('name')
            if not name:
                continue
            declared.add(name)
            folder = os.path.join(asset_list_root, category.get('folder', 'Assetlists'))
            self._ingest_category_file(folder, name)

        # A category the project's own config has but the manifest does not is loaded anyway.
        # **Nothing in the framework wrote this manifest**: the migration did, and it has been
        # run. So a category added through the register - which writes asset_data.config and
        # nothing else - was declared nowhere, and every asset registered into it was written
        # to its .alist file and then loaded by nothing, because this is what every tool reads
        # the registry through. The register declares a new category now
        # (:func:`declare_category`), and this picks up the ones added before it did.
        from mca.common.assetlist import asset_paths

        configured = set(asset_paths.AssetDictData.load().categories_names)
        missing = sorted(configured - declared)
        for name in missing:
            self._ingest_category_file(os.path.join(asset_list_root, 'Assetlists'), name)
        if missing:
            logger.info('These categories are in asset_data.config but not in %s, and were '
                        'loaded anyway: %s', CATEGORIES_MANIFEST, ', '.join(missing))

    def _ingest_category_file(self, folder, category_name):
        """
        Load a single .alist file from the given folder and category name.

        :param str folder: Absolute path to the folder holding the .alist file.
        :param str category_name: Category name, matching the .alist filename.
        """

        file_path = os.path.join(folder, f'{category_name}.alist')
        if not os.path.isfile(file_path):
            # Not an error - a declared category may have no entries yet.
            logger.debug("No .alist file for category '%s' at %s", category_name, file_path)
            return

        data = alistio.read_alist_file(file_path)
        if not data:
            return

        for asset_id, asset_data in data.items():
            if not unified_entry.is_unified_format(asset_data):
                # Pre-migration data. Skipped loudly rather than guessed at:
                # the legacy entry classes no longer exist.
                logger.warning(
                    "The asset '%s' in %s is not in the format this reads, and was skipped.",
                    asset_id, file_path)
                continue

            entry = unified_entry.UnifiedAssetEntry(asset_dict={asset_id: asset_data})
            record = AssetRecord.from_unified_entry(entry, category_override=category_name)
            self._register_record(record)

    def _resolve_built_for_references(self) -> None:
        """
        Resolve ``built_for`` character names to parent asset ids.

        Gear entries store one or more character display names in ``built_for``
        rather than an asset id. This runs after every record is loaded so the
        names can be looked up, and registers the gear under **each** parent it
        names - a piece of gear worn by two characters appears under both.

        ``parent_id`` stays the first resolved parent so callers that predate
        multi-parent gear keep working; ``parent_ids`` holds them all.
        """

        for asset_id, record in list(self._records_by_id.items()):
            if not record.built_for_all:
                continue

            resolved = []
            for name in record.built_for_all:
                parent = self._records_by_name.get(name.lower())
                if parent is None:
                    logger.debug(
                        "Gear item '%s' has built_for='%s' but no matching asset was found.",
                        asset_id, name)
                    continue
                if parent.asset_id == asset_id:
                    # An asset cannot be built for itself; that would make it
                    # its own child and show up as a cycle.
                    logger.warning("Asset '%s' lists itself in built_for; ignoring.", asset_id)
                    continue
                if parent.asset_id not in resolved:
                    resolved.append(parent.asset_id)

            if not resolved:
                continue

            # An explicit 'parent' field still wins for parent_id.
            primary = record.parent_id or resolved[0]
            parent_ids = tuple(resolved)

            # AssetRecord is frozen, so replace it with an updated copy.
            updated = dataclasses.replace(record, parent_id=primary, parent_ids=parent_ids)
            self._records_by_id[asset_id] = updated

            name_key = record.name.lower()
            if self._records_by_name.get(name_key) is record:
                self._records_by_name[name_key] = updated

            subtype = record.subtype or "__unspecified__"
            cat_list = self._records_by_category[record.category][subtype]
            for i, r in enumerate(cat_list):
                if r is record:
                    cat_list[i] = updated
                    break

            # One entry per parent, so the gear is reachable from every
            # character that can wear it.
            for parent_id in parent_ids:
                self._children_by_parent[parent_id].append(updated)

        self._resolve_variant_references()

    def _resolve_variant_references(self) -> None:
        """
        Index every variant under the base character it restyles.

        A variant_of naming an asset that does not exist is dropped with a
        warning rather than indexed, so a typo shows up in the log instead of
        creating a base nobody can load.
        """

        for record in self._records_by_id.values():
            base_id = (record.variant_of or "").strip()
            if not base_id:
                continue
            if base_id == record.asset_id:
                logger.warning(
                    "Asset '%s' lists itself as its own variant base; ignoring.",
                    record.asset_id,
                )
                continue
            if base_id not in self._records_by_id:
                logger.warning(
                    "Asset '%s' is a variant of '%s', which is not in the registry.",
                    record.asset_id,
                    base_id,
                )
                continue
            self._variants_by_base[base_id].append(record)

    def iter_variants(self, asset_id: str) -> Iterator[AssetRecord]:
        """
        Yield the variants registered against a base character.

        :param str asset_id: The base character's asset id.
        :return: Its variants, in registry order.
        :rtype: Iterator[AssetRecord]
        """

        for record in self._variants_by_base.get(asset_id, []):
            yield record

    def get_variant_base(self, asset_id: str) -> Optional[AssetRecord]:
        """
        Return the base character a variant restyles.

        :param str asset_id: A variant's asset id.
        :return: The base record, or None when this is not a variant.
        :rtype: AssetRecord or None
        """

        record = self._records_by_id.get(asset_id)
        if record is None or not record.variant_of:
            return None
        return self._records_by_id.get(record.variant_of)

    def get_variant_family(self, asset_id: str) -> List[AssetRecord]:
        """
        Return the base and every variant in one list, base first.

        Works from any member: pass a variant or the base itself. This is what a
        "swap this character for another look" picker wants - from whichever
        body is in the scene, every body it could become.

        :param str asset_id: Any member of the family.
        :return: Base record first, then its variants. Empty when unknown.
        :rtype: list[AssetRecord]
        """

        record = self._records_by_id.get(asset_id)
        if record is None:
            return []
        base = self._records_by_id.get(record.variant_of) if record.variant_of else record
        if base is None:
            return []
        return [base] + list(self.iter_variants(base.asset_id))

    def _register_record(self, record: AssetRecord) -> None:
        existing = self._records_by_id.get(record.asset_id)
        if existing:
            # When both records share the same category, merge the new record's
            # extra fields into the existing one.  This lets Gear/Characters.alist
            # enrich records already loaded from Assetlists/Characters.alist with
            # fields like image, description, and skeleton.
            if existing.category == record.category:
                merged_raw = dict(existing.raw)
                for key, value in record.raw.items():
                    if key not in merged_raw or not merged_raw[key]:
                        merged_raw[key] = value
                updated = dataclasses.replace(
                    existing,
                    raw=merged_raw,
                    # Populate gear fields from the incoming record if the
                    # existing record doesn't already have them.
                    description=existing.description or record.description,
                    image=existing.image or record.image,
                    skeleton=existing.skeleton or record.skeleton,
                    engine_path=existing.engine_path or record.engine_path,
                    slot=existing.slot or record.slot,
                    built_for=existing.built_for or record.built_for,
                    built_for_all=existing.built_for_all or record.built_for_all,
                    variant_of=existing.variant_of or record.variant_of,
                    attach_sockets=existing.attach_sockets or record.attach_sockets,
                )
                self._records_by_id[record.asset_id] = updated
                # Update the name index to point to the merged record.
                name_key = existing.name.lower()
                if self._records_by_name.get(name_key) is existing:
                    self._records_by_name[name_key] = updated
                logger.debug(
                    "Merged gear fields into existing asset '%s' in category '%s'.",
                    record.asset_id,
                    record.category,
                )
            else:
                logger.debug(
                    "Duplicate asset id '%s' detected in categories '%s' and '%s'; keeping the first instance.",
                    record.asset_id,
                    existing.category,
                    record.category,
                )
            return

        self._records_by_id[record.asset_id] = record

        name_key = record.name.lower()
        self._records_by_name.setdefault(name_key, record)

        subtype = record.subtype or "__unspecified__"
        self._records_by_category[record.category][subtype].append(record)

        self._children_by_parent[record.parent_id].append(record)

    def _compute_roots(self) -> None:
        referenced_parents = {record.parent_id for record in self._records_by_id.values() if record.parent_id}
        known_ids = set(self._records_by_id.keys())
        for asset_id, record in self._records_by_id.items():
            if not record.parent_id or record.parent_id not in known_ids:
                self._roots.add(asset_id)
        # Track parents that were referenced but missing – validation handles reporting.
        missing = referenced_parents - known_ids
        if missing:
            logger.debug("Missing parent assets referenced: %s", sorted(missing))

    def _validate(self) -> AssetValidationReport:
        report = AssetValidationReport()
        # "type" was a legacy field dropped by the unified schema; asking for it
        # here flagged every single record as incomplete.
        required_fields = ("name", "category", "asset_type", "path")

        for record in self._records_by_id.values():
            missing = {field for field in required_fields if not record.raw.get(field)}
            if missing:
                report.missing_required_fields.setdefault(record.asset_id, set()).update(missing)

        # Validate parent ids.
        for parent_id, children in self._children_by_parent.items():
            if not parent_id:
                continue
            if parent_id not in self._records_by_id:
                for child in children:
                    report.dangling_parents[child.asset_id] = parent_id

        # Two assets with one display name: get_record_by_name answers the first one loaded,
        # so the other cannot be opened by name at all. Nothing reported this.
        name_index: Dict[str, Set[str]] = defaultdict(set)
        for record in self._records_by_id.values():
            if record.name:
                name_index[record.name.lower()].add(record.asset_id)
        for name, asset_ids in name_index.items():
            if len(asset_ids) > 1:
                report.duplicate_names[name] = asset_ids

        # Namespace uniqueness.
        namespace_index: Dict[str, Set[str]] = defaultdict(set)
        for record in self._records_by_id.values():
            if record.namespace:
                namespace_index[record.namespace].add(record.asset_id)
        for namespace, asset_ids in namespace_index.items():
            if len(asset_ids) > 1:
                report.duplicate_namespaces[namespace] = asset_ids

        # Cycle detection.
        visited: Set[str] = set()
        stack: Set[str] = set()

        def _dfs(node_id: str, path: List[str]) -> None:
            if node_id in stack:
                cycle_start = path.index(node_id)
                report.cyclic_dependencies.append(path[cycle_start:] + [node_id])
                return
            if node_id in visited:
                return
            visited.add(node_id)
            stack.add(node_id)
            for child in self._children_by_parent.get(node_id, []):
                _dfs(child.asset_id, path + [child.asset_id])
            stack.remove(node_id)

        # From every record, not only the roots. A cycle that no root can reach - A's parent
        # is B and B's parent is A, so neither is a root - was never visited by the version
        # this replaces, which is to say the cycles that matter were the ones it could not
        # find.
        for asset_id in self._records_by_id:
            _dfs(asset_id, [asset_id])

        return report


def declare_category(name: str, folder: str = 'Assetlists') -> bool:
    """
    Put a category into the project's ``categories.json``, so that everything reading the
    registry knows it exists.

    :param str name: The category's name, which is also its ``.alist`` file's name.
    :param str folder: Which folder under the asset list root holds that file.
    :return: Whether the manifest was written. False when there is no project, or when the
        category was already declared.
    :rtype: bool

    Nothing in the framework did this. The manifest was written once, by the migration, and the
    register - the one place a person adds a category - wrote only ``asset_data.config``. So a
    new category was declared nowhere, and the assets registered into it were loaded by
    nothing.
    """

    manifest_path = paths.get_categories_manifest_path()
    if not name or not manifest_path:
        return False

    manifest = {}
    if os.path.isfile(manifest_path):
        manifest = alistio.read_alist_file(manifest_path, default={}) or {}
    if not isinstance(manifest, dict):
        logger.error('%s could not be read, so "%s" was not declared in it.',
                     CATEGORIES_MANIFEST, name)
        return False

    manifest.setdefault('version', '2.0')
    categories = manifest.setdefault('categories', [])
    if any(isinstance(entry, dict) and entry.get('name') == name for entry in categories):
        return False

    categories.append({'name': name, 'folder': folder})
    fileio.touch_path(manifest_path)
    existed = os.path.isfile(manifest_path)
    sourcecontrol.checkout(manifest_path)
    jsonio.write_to_json_file(manifest, manifest_path)
    if not existed:
        sourcecontrol.add(manifest_path)
    logger.info('Declared the category "%s" in %s.', name, CATEGORIES_MANIFEST)

    return True


_DEFAULT_MANAGER: Optional[AssetManager] = None


def get_asset_manager(force_reload: bool = False) -> AssetManager:
    """
    Retrieve a shared :class:`AssetManager` instance.

    :param bool force_reload: When True the underlying manager reloads `.alist`
        files before being returned.
    :return: Shared asset manager configured with gear support enabled.
    :rtype: AssetManager
    """

    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = AssetManager(run_validation=True)
    elif force_reload:
        _DEFAULT_MANAGER.reload(run_validation=True)
    return _DEFAULT_MANAGER
