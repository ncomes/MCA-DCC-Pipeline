"""
Headless Maya Startup - Batch/Standalone Mode

This module provides MCA framework initialization for headless Maya sessions
(batch mode, command line tools, automation scripts, etc.).

Key differences from normal startup:
- NO Qt/UI imports or operations
- NO menu creation
- NO window management
- NO toolbox opening
- Core functionality only (paths, environment, resources)

Usage:
    from mca.mya.startup import headless_startup
    headless_startup.init()

Use Cases:
- Animation batch exporters
- Asset processing scripts
- Automated rigging operations
- Render farm submissions
- CI/CD Maya automation
"""

import os
import pymel.core as pm
from mca import mya
from mca.common import log
from mca.common.startup.configs import config, common_env, consts
from mca.common.paths import project_paths
from mca.common.resources import resources
from mca.mya.startup.configs import ma_envs, ma_configs, ma_consts


logger = log.MCA_LOGGER
DEPOT_VERSION = '2.0.0'


def init(project_name=None, skip_logging=False):
    """
    Initialize MCA framework for headless/batch Maya.

    This provides core functionality without any GUI/Qt dependencies.
    Safe to call in maya.exe -batch mode or standalone Python.

    :param str project_name: The project to start. None reads MCA_PROJECT_NAME,
        which the launcher exports, so a batch job inherits the project it was
        started for rather than a name written into the source.
    :param bool skip_logging: If True, suppresses log output.
    """
    if not skip_logging:
        logger.info('Initializing MCA framework (headless mode)...')

    # Verify we're actually in batch mode
    if not pm.about(batch=True):
        logger.warning('headless_startup.init() called but Maya is NOT in batch mode!')
        logger.warning('For normal Maya, use: from mca.mya.startup import startup; startup.startup_init()')

    project_name = project_name or os.getenv(consts.MCA_PROJECT_NAME)
    if not project_name:
        logger.error('No project to start: pass project_name, or set MCA_PROJECT_NAME '
                     '(the launcher exports it when it starts a DCC).')
        return False

    # Set up project environment variables (MCA_PROJECT_ROOT, etc.)
    # This MUST happen before any resource registration or asset manager usage
    common_env.create_project_envs(project_name, skip_dialog=True)
    if not skip_logging:
        logger.info(f'Project environment variables created for: {project_name}')

    # Set up tools and common environment variables
    common_env.create_tools_envs(skip_dialog=True)
    common_env.create_common_envs(skip_dialog=True)
    if not skip_logging:
        logger.info('Framework environment variables created')

    # Create Maya-specific environment variables
    ma_envs.create_maya_envs()
    if not skip_logging:
        logger.info('Maya environment variables created')

    # Reload modules so they pick up the newly-set environment variables
    # This is CRITICAL - modules like project_paths cache environment variables at import time
    config.reload_modules()
    if not skip_logging:
        logger.info('Modules reloaded with new environment variables')

    # Register resources (icons, etc.) - safe even without GUI
    resources.register_resources()
    if not skip_logging:
        logger.info('Resources registered')

    # Add Studio Library paths
    studiolibrary_paths = os.getenv(ma_consts.STUDIOLIBRARY, None)
    if studiolibrary_paths:
        ma_configs.add_maya_system_paths(studiolibrary_paths)
        if not skip_logging:
            logger.info('Studio Library paths added')

    # Add Pose Wrangler paths
    pose_wrangler_paths = os.getenv(ma_consts.POSE_WRANGLER, None)
    if pose_wrangler_paths:
        ma_configs.add_maya_system_paths(pose_wrangler_paths)
        if not skip_logging:
            logger.info('Pose Wrangler paths added')

    # Add third-party tool paths
    third_party_paths = os.getenv(ma_consts.THIRDPARTY, None)
    if third_party_paths:
        ma_configs.add_maya_system_paths(third_party_paths)
        if not skip_logging:
            logger.info('Third-party tool paths added')

    # Add Maya dependencies paths
    depend_paths = os.getenv(ma_consts.DEPS_ROOT, None)
    if depend_paths:
        ma_configs.add_maya_system_paths(depend_paths)
        if not skip_logging:
            logger.info('Maya dependencies paths added')

    # Set project workspace. No project root set means there is no workspace to
    # open, and openWorkspace on an empty path is an error rather than a no-op.
    project_root = project_paths.get_project_path()
    if project_root:
        pm.workspace(project_root, openWorkspace=True)
        if not skip_logging:
            logger.info(f'Project workspace set: {project_root}')
    elif not skip_logging:
        logger.warning('No project root is set, so the Maya workspace was left alone.')

    # Apply default Maya settings (viewport, units, etc.)
    new_prefs = ma_configs.MayaDefaultStartOptions.load()
    new_prefs.apply_maya_defaults()
    if not skip_logging:
        logger.info('Maya default settings applied')

    if not skip_logging:
        logger.info(f'MCA headless initialization complete (version {DEPOT_VERSION})')


def shutdown(skip_logging=False):
    """
    Clean shutdown for headless Maya sessions.

    Removes added paths and cleans up environment.

    :param bool skip_logging: If True, suppresses log output.
    """
    if not skip_logging:
        logger.info('Shutting down MCA framework (headless mode)...')

    # Remove Maya's paths from sys.path
    depend_paths = os.getenv(ma_consts.DEPS_ROOT, None)
    maya_root_path = mya.MAYA_PATH
    if depend_paths:
        config.remove_sys_path([depend_paths, maya_root_path])

    if not skip_logging:
        logger.info('MCA headless shutdown complete')