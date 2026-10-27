"""
What the settings window reads and writes.

Kept apart from the window so the values can be asked for, and the resolved paths listed,
without a Qt application - which is also how this gets tested outside Maya.

Only Maya's own settings are editable here. Project paths are cross-DCC: MotionBuilder and
Unreal read the same ones, the launcher owns them, and they are shown read-only so that
"what did it actually resolve?" has an answer that is not a log file.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.paths import paths, project_paths
from mca.common.startup.configs import consts


logger = log.MCA_LOGGER

#: The editable Maya options, as (attribute on MayaDefaultStartOptions, label, kind).
#: ``kind`` is what the window should build: 'bool', 'int', or a tuple of choices.
MAYA_FIELDS = (
    ('use_defaults', 'Apply these when Maya starts', 'bool'),
    ('working_unit_linear', 'Linear unit', ('mm', 'cm', 'm', 'in', 'ft', 'yd')),
    ('working_unit_time', 'Time unit', ('game', 'film', 'pal', 'ntsc', 'show', 'palf',
                                        'ntscf')),
    ('playback_min', 'Playback start', 'int'),
    ('playback_max', 'Playback end', 'int'),
    ('playback_min_range', 'Range start', 'int'),
    ('playback_max_range', 'Range end', 'int'),
    ('grid_size', 'Grid size', 'int'),
    ('grid_spacing', 'Grid spacing', 'int'),
    ('grid_divisions', 'Grid divisions', 'int'),
)

#: Settings Maya only reads while it is starting. Changing these saves, but does not take
#: effect until the next launch, and the window says so rather than pretending otherwise.
RESTART_REQUIRED = ('use_defaults',)


def resolved_values():
    """
    What the framework actually resolved this session.

    Not what a preferences file says - what the accessors answer right now, which is the
    question that is actually hard to answer from inside Maya. An empty value means the
    preference behind it is not set, and that is worth seeing.

    :return: ``[(label, value), ...]`` in the order a window should show them.
    :rtype: list(tuple)
    """

    try:
        from mca.common import sourcecontrol
        backend = sourcecontrol.current().name
    except Exception as error:                                       # noqa: BLE001
        backend = 'could not be read: {}'.format(error)

    return [
        ('Project', project_paths.get_project_name()),
        ('Project root', project_paths.get_project_path()),
        ('Framework packages', os.getenv(consts.MCA_FRAMEWORK_PATH) or ''),
        ('Art root', project_paths.get_art_path()),
        ('Common tools', paths.get_common_tools_path()),
        ('Asset list', paths.get_asset_list_path()),
        ('Categories manifest', paths.get_categories_manifest_path()),
        ('Icons', paths.get_icons_path()),
        ('Source control', backend),
    ]


def load_options():
    """
    :return: Maya's start-up options, from the preferences file or the defaults.
    :rtype: mca.mya.startup.configs.ma_configs.MayaDefaultStartOptions
    """

    from mca.mya.startup.configs import ma_configs

    return ma_configs.MayaDefaultStartOptions.load()


def save_options(options, apply_now=True):
    """
    Write the options out, and put them into this Maya as well.

    :param options: The options to save.
    :param bool apply_now: Also apply them to the running Maya, for the ones Maya will take
        at any time. Saving without applying leaves the window disagreeing with the
        application until the next launch, which is its own kind of confusing.
    :return: What happened, for showing the person.
    :rtype: str
    """

    options.save()
    if not apply_now:
        return 'Saved. They take effect next time Maya starts.'

    try:
        options.apply_maya_defaults()
    except Exception as error:                                       # noqa: BLE001
        logger.exception('Saving the settings worked; applying them did not.')
        return 'Saved, but could not be applied to this Maya: {}'.format(error)

    return 'Saved and applied.'
