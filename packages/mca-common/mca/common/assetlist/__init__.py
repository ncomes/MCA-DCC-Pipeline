"""
The asset registry: what the project's assets are, and where each one's files live.

```python
from mca.common.assetlist import asset_manager

hero = asset_manager.get_asset_manager().get_record_by_name('Hero Bot')
```

The pieces, from the bottom up:

``asset_path_config``
    The framework's own folder templates, which a new project is seeded from.
``asset_paths``
    The project's own category file: its categories, their factions and subcategories, and
    the folders each category's assets have.
``asset_list``
    What every asset record has, whatever kind of asset it is.
``unified_entry`` / ``unified_registry``
    Writing: one asset, and one category's ``.alist`` file.
``asset_manager``
    Reading: every asset, indexed by id, name, category and what belongs to what.
``validate_assets``
    A command line check, for a build step.

Import the module rather than its contents - except :func:`get_asset_manager`, which is
re-exported because some twenty call sites across mca-maya and mca-ue already import it by
name from the package.
"""

from mca.common.assetlist.asset_manager import get_asset_manager

__all__ = ['get_asset_manager']
