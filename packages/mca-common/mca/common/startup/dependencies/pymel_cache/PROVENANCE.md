# PyMEL API caches vendored for Maya versions PyMEL does not ship

## Why this folder exists

Maya stopped shipping PyMEL after 2025, and PyMEL's last official release (1.5.0,
28 October 2024) predates Maya 2026, so it carries prebuilt caches for Maya
2022-2025 and none for 2026.

Without a cache, PyMEL rebuilds one from Maya's local HTML documentation. Maya 2026
does not install that documentation, so the rebuild fails outright. Two separate
failures, from two separate caches:

- `mayaApi{year}.py` missing -> `IOError: Cannot find maya documentation. Expected
  to find it at ...` raised by `pymel/internal/parsers.py` when `ApiCache.rebuild()`
  constructs an `ApiDocParser`.
- `mayaCmdsList{year}.py` missing -> `RuntimeError: could not find list of internal
  commands` raised by `pymel/internal/cmdcache.py:getInternalCmds()`, which reads
  `internalCommandList.txt` out of Maya's documentation folder.

Both files are therefore required. The remaining caches are not:
`mayaCmdsDocs{year}.py` is read through `factories.loadCmdDocCache(ignoreError=True)`
and only supplies docstrings; `mayaCmdsExamples{year}.py` only supplies examples.

The launcher copies whatever is here into the per-Maya dependency folder after the
import check catches the failure - see `mca.launcher.core.dependencies.recover_pymel_cache`.

## What these files are

Pure data. Each file is exactly two top-level assignments, `version` and `data`,
containing only literals - no imports, no calls, no executable code. Verified by
parsing each file with `ast` and walking its top level.

They are loaded by `pymel/internal/cachebase.py`, which declares
`PY_CACHE_FORMAT_VERSION = (1, 2)`. Both files declare `version = (1, 2)`, so
PyMEL 1.5.0 reads them with no code change.

Structure checked against PyMEL 1.5.0's own `_CACHE_NAMES` declarations:

| File | Expected members (`_CACHE_NAMES`) | Found |
|---|---|---|
| `mayaApi2026.py` | apiTypesToApiEnums, apiEnumsToApiTypes, mayaTypesToApiTypes, apiTypesToApiClasses, apiClassInfo | 5 dicts: 1216, 1212, 889, 837, 357 entries |
| `mayaCmdsList2026.py` | cmdlist, nodeHierarchy, uiClassList, nodeCommandList, moduleCmds | dict 4691, list 870, list 124, list 236, dict 12 - matches `ITEM_TYPES` |

## Source

Taken verbatim from the `iamsleepy/pymel` fork of `LumaPictures/pymel` at tag
`1.6.0rc2` (11 November 2025), the first tag carrying a generated Maya 2026 cache.

    https://github.com/iamsleepy/pymel  tag 1.6.0rc2
    pymel/cache/mayaApi2026.py
    pymel/cache/mayaCmdsList2026.py

| File | Bytes | SHA-256 |
|---|---|---|
| `mayaApi2026.py` | 6843043 | `85b4da99ca15c3c1159c998bc9ff828f2baff2679c4e312778adf2b568fbb5c8` |
| `mayaCmdsList2026.py` | 11011015 | `880d46033c1bab0e0c957c741797b724efeea6bb030a8aff097a36b56cfa4323` |

Only these two generated data files were taken. None of that fork's code changes
were adopted: a commit-by-commit diff against upstream showed its non-cache changes
are Python-2 removal (`__future__`, `future.utils.with_metaclass`,
`past.builtins.basestring`, `PY2` branches) and packaging, with no Maya-2026-specific
logic. Its Maya 2024 and 2025 caches are byte-identical to upstream 1.5.0's.

Note for anyone tempted to adopt that fork wholesale: as of its `1.7.1rc1` tag,
`pymel/core/uitypes.py` line 3 still carries an unconditional
`from past.builtins import basestring`, while its `pyproject.toml` has dropped the
`future` dependency that provides `past`. Installing it into a clean interpreter
gives `ModuleNotFoundError: past` on `import pymel.core`. PyPI's PyMEL 1.5.0 still
declares `future >= 0.18`, which is one reason this framework installs 1.5.0 from
PyPI and vendors only the caches.

## Generating these yourself instead

These are generated files from an unreleased third-party fork. To own the provenance,
build them on one machine that has the Maya 2026 documentation installed:

    # in mayapy for the target Maya version, with the docs installed
    import pymel.internal.apicache as apicache
    import pymel.internal.cmdcache as cmdcache
    apicache.ApiCache().rebuild()
    cmdcache.CmdCache().rebuild()

The results land in the PyMEL package's own `cache/` folder. Copy them here, replace
the hashes above, and record the Maya build they came from.

## Licence

PyMEL is BSD 3-clause, Copyright (c) 2009 Chad Dombrova. The full licence text is in
`LICENSE-pymel` beside this file, as clause 1 requires for source redistribution.
