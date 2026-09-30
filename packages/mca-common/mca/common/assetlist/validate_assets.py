"""
Check the asset registry from a command line, and say what is wrong with it.

    python -m mca.common.assetlist.validate_assets --json

Meant for a build step: it answers 0 when the registry is sound and 1 when it is not, and
``--json`` gives a machine the same report the log gives a person.

``--skip-gear`` **did nothing** in the version this replaces. It collected the ids to ignore
with ``manager.iter_category('Gear')``, and ``Gear`` is not a category: gear lives in
categories of its own - Hats, Armor, Shirts - each flagged as gear in the project's config. So
the set was always empty and every gear problem was reported anyway. It asks the config now.

It also wrote ``project_paths.MCA_PROJECT_ROOT`` when given ``--project-root``, which was a
module-level snapshot of the environment that no longer exists: the paths modules read the
environment when asked, which is the whole point of them.
"""

from __future__ import annotations

# python imports
import argparse
import json
import os
import sys

# MCA python imports
from mca.common import log
from mca.common.assetlist import asset_manager, asset_paths
from mca.common.startup.configs import consts


logger = log.MCA_LOGGER


def report_to_dict(report) -> dict:
    """
    :param report: An :class:`asset_manager.AssetValidationReport`, or None.
    :return: The same thing, as plain values a machine can read.
    :rtype: dict
    """

    if not report:
        return {}

    return {
        'missing_required_fields': {asset_id: sorted(fields)
                                    for asset_id, fields in report.missing_required_fields.items()},
        'dangling_parents': dict(report.dangling_parents),
        'duplicate_namespaces': {namespace: sorted(asset_ids)
                                 for namespace, asset_ids in report.duplicate_namespaces.items()},
        'duplicate_names': {name: sorted(asset_ids)
                            for name, asset_ids in report.duplicate_names.items()},
        'cyclic_dependencies': [list(cycle) for cycle in report.cyclic_dependencies],
    }


def gear_asset_ids(manager) -> set:
    """
    Every asset in a category the project has flagged as gear.

    :param manager: An :class:`asset_manager.AssetManager`.
    :return: Their ids.
    :rtype: set
    """

    categories = asset_paths.AssetDictData.load()
    gear_categories = {name for name in categories.categories_names
                       if categories.get_category_data(name).is_gear}

    return {record.asset_id for record in manager.iter_all()
            if record.category in gear_categories}


def without_gear(report, gear_ids):
    """
    Take everything about gear out of a report.

    :param report: The report, changed in place.
    :param set gear_ids: The assets to ignore.
    :return: The report.
    """

    report.missing_required_fields = {asset_id: fields for asset_id, fields
                                      in report.missing_required_fields.items()
                                      if asset_id not in gear_ids}
    report.dangling_parents = {asset_id: parent for asset_id, parent
                               in report.dangling_parents.items() if asset_id not in gear_ids}

    for attribute in ('duplicate_namespaces', 'duplicate_names'):
        kept = {}
        for key, asset_ids in getattr(report, attribute).items():
            remaining = set(asset_ids) - gear_ids
            if len(remaining) > 1:
                kept[key] = remaining
        setattr(report, attribute, kept)

    report.cyclic_dependencies = [cycle for cycle in report.cyclic_dependencies
                                  if not any(node in gear_ids for node in cycle)]

    return report


def main(argv=None) -> int:
    """
    :param argv: The command line, or None for the real one.
    :return: 0 when the registry is sound, 1 when it is not.
    :rtype: int
    """

    parser = argparse.ArgumentParser(description='Check the MCA asset registry.')
    parser.add_argument('--project-root', help='Which project to check, rather than the '
                                               'one the environment names.')
    parser.add_argument('--json', action='store_true', help='Write the report as JSON.')
    parser.add_argument('--skip-gear', action='store_true',
                        help='Say nothing about assets in gear categories.')
    arguments = parser.parse_args(argv)

    if arguments.project_root:
        os.environ[consts.MCA_PROJECT_ROOT] = arguments.project_root
        # The categories are read once and kept, so a different project has to be asked for.
        asset_paths.reload()

    manager = asset_manager.get_asset_manager(force_reload=True)
    report = manager.validation_report

    if arguments.skip_gear and report:
        report = without_gear(report, gear_asset_ids(manager))

    is_valid = report.is_valid() if report else True

    if arguments.json:
        json.dump({'success': bool(is_valid), 'report': report_to_dict(report)},
                  sys.stdout, indent=2, sort_keys=True, default=sorted)
        sys.stdout.write('\n')
    elif not report:
        logger.info('Nothing was checked: there is no report.')
    else:
        logger.info('Checked %s assets. Sound: %s.', len(list(manager.iter_all())), is_valid)
        if report.missing_required_fields:
            logger.warning('Assets missing fields they need: %s', report.missing_required_fields)
        if report.dangling_parents:
            logger.warning('Assets whose parent is not in the registry: %s', report.dangling_parents)
        if report.duplicate_namespaces:
            logger.warning('Namespaces more than one asset uses: %s', report.duplicate_namespaces)
        if report.duplicate_names:
            logger.warning('Names more than one asset answers to, so only the first can be '
                           'opened by name: %s', report.duplicate_names)
        if report.cyclic_dependencies:
            logger.warning('Assets that are their own ancestor: %s', report.cyclic_dependencies)

    return 0 if is_valid else 1


if __name__ == '__main__':                                           # pragma: no cover
    raise SystemExit(main())
