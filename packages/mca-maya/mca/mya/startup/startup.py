"""
Initializes all the Packages needed to run the python codebase in Maya.

This module handles both core Maya startup and AI subsystem initialization.
AI startup occurs at the END of the main startup to ensure all Maya systems
are ready before AI tool registration.
"""

# python imports
import os
import sys
# software specific imports
# maya.cmds, not pymel, on purpose.
#
# Every use below is about the session rather than the scene - batch mode, the Maya
# version, the workspace - and maya.cmds answers all of them. Importing pymel here
# made the whole framework depend on it at start-up, which is how Maya 2026 ended up
# with no menus at all: Maya has not shipped pymel since 2025, pymel's last release
# predates 2026, and the import died before anything loaded. Tools that want pymel
# still import it themselves and fail on their own if it is unavailable.
import maya.cmds as cmds
# mca python imports
from mca.mya.startup import start_menus
from mca import mya
from mca.common import log
from mca.common.startup.configs import consts, config
from mca.common.pyqt.qt_utils import windows
from mca.common.paths import project_paths
from mca.mya.pyqt.utils import ma_main_window
from mca.mya.startup.configs import ma_envs, ma_configs, ma_consts
from mca.mya.utils import plugins
from mca.common.resources import resources


logger = log.MCA_LOGGER
DEPOT_VERSION = '2.0.0'

# AI state tracking
_AI_INITIALIZED = False


def _check_ai_dependencies():
    """
    Check if AI dependencies are available.

    AI dependencies (vosk, sounddevice) should be installed via pip from
    requirements.txt. This function just verifies they can be imported.

    :return: True if core AI dependencies are available
    :rtype: bool
    """
    try:
        # Core AI dependencies - these should be pip installed
        import vosk
        import sounddevice
        logger.debug('AI voice dependencies available')
        return True
    except ImportError as e:
        logger.debug(f'AI voice dependencies not available: {e}')
        return False


def _init_ai(skip_dialog=False, is_batch=False):
    """
    Initialize Maya AI subsystem.

    This is called at the END of Maya startup. It:
    1. Adds AI dependencies to sys.path
    2. Initializes AI Core (mca.ai) if not already done
    3. Registers Maya tool functions with FunctionRegistry

    :param bool skip_dialog: If True, suppress console output
    :param bool is_batch: If True, running in batch/headless mode
    """
    global _AI_INITIALIZED

    if _AI_INITIALIZED:
        logger.debug('Maya AI already initialized')
        return

    # Check AI dependencies are available (installed via pip)
    _check_ai_dependencies()

    # Configure voice models directory
    # Models are in the dependencies folder alongside vosk/sounddevice
    try:
        from mca.ai.tools.wizard import voice_input
        deps_path = os.environ.get('MCA_COMMON_DEPEND', '')
        if deps_path:
            vosk_models_dir = os.path.join(deps_path, 'vosk_models')
            if os.path.isdir(vosk_models_dir):
                voice_input.set_models_dir(vosk_models_dir)
                logger.debug(f'Voice models directory set: {vosk_models_dir}')
            else:
                logger.debug(f'Voice models directory not found: {vosk_models_dir}')
    except ImportError:
        pass  # Voice input not available
    except Exception as e:
        logger.debug(f'Failed to configure voice models: {e}')

    # Verify AI Core is initialized
    try:
        from mca.ai.startup.configs import ai_configs
        if not ai_configs.MCA_AI_STATE.get('started', False):
            # Initialize AI core first
            from mca.ai.startup import startup as ai_startup
            ai_startup.startup_init()
            logger.debug('AI Core initialized from Maya startup')
    except ImportError as e:
        logger.debug(f'AI Core not available: {e}')
        return
    except Exception as e:
        logger.warning(f'Failed to check/initialize AI Core: {e}')
        return

    logger.debug('AI Core ready, proceeding with Maya AI initialization...')

    if not skip_dialog and not is_batch:
        logger.info('Initializing Maya AI...')

    # Register Maya-AI tool functions with FunctionRegistry
    # This makes functions available for AI tool-calls
    try:
        from mca.mya.ai.actions.register_functions import register_all_functions
        register_all_functions()
        if not skip_dialog and not is_batch:
            logger.debug('Registered Maya AI tool functions')
    except ImportError as e:
        logger.debug(f'Could not import register_functions: {e}')
    except Exception as e:
        logger.error(f'Failed to register tool functions: {e}')
        # Non-fatal - continue without tool functions

    _AI_INITIALIZED = True

    if not skip_dialog and not is_batch:
        print("""
     __      __                        __     _____
    |  \    /  | __ _ __   __ __ _    /  \   |_   _|
    | \ \  / / |/ _` |\ \ / // _` |  / /\ \    | |
    | |\ \/ /| | (_| | \ V /| (_| | / /__\ \  _| |_
    |_| \__/ |_|\__,_|  |_|  \__,_|/_/    \_\|_____|""")
        print('\n' + '=' * 118 + '\n')
        logger.info('Maya AI Initialized!')


def _shutdown_ai(skip_dialog=False):
    """
    Shut down Maya AI subsystem.

    This is called at the START of Maya shutdown. It:
    1. Shuts down AI Core

    :param bool skip_dialog: If True, suppress console output
    """
    global _AI_INITIALIZED

    if not _AI_INITIALIZED:
        logger.debug('Maya AI not initialized, nothing to shut down')
        return

    try:
        from mca.ai.startup.configs import ai_configs
        if not ai_configs.MCA_AI_STATE.get('started', False):
            logger.debug('AI Core not started, nothing to shut down')
            _AI_INITIALIZED = False
            return
    except ImportError:
        _AI_INITIALIZED = False
        return

    if not skip_dialog:
        logger.info('Shutting down Maya AI...')

    # Shut down AI Core
    try:
        from mca.ai.startup import startup as ai_startup
        ai_startup.shutdown()
        logger.debug('AI Core shut down')
    except Exception as e:
        logger.warning(f'Failed to shut down AI Core: {e}')

    _AI_INITIALIZED = False

    if not skip_dialog:
        logger.info('Maya AI shutdown complete')


def startup_init(skip_dialog=False):
    """
    Initializes  Packages.
    """
    # Check if running in batch mode (headless Maya)
    is_batch = cmds.about(batch=True)

    if not skip_dialog and not is_batch:
        logger.info('Creating  Python Maya framework environment ...')
        print("""
 __      __
|  \    /  | __ _ __   __ __ _
| \ \  / / |/ _` |\ \ / // _` |
| |\ \/ /| | (_| | \ V /| (_| |
|_| \__/ |_|\__,_|  |_|  \__,_|""")
        print('\n' + '=' * 118 + '\n')
    elif is_batch:
        logger.info('Initializing MCA framework in batch mode (headless)...')

    ma_envs.create_maya_envs()
    if not skip_dialog and not is_batch:
        logger.info('Maya Environment Variables Created...')

    resources.register_resources()
    if not is_batch:
        logger.info('Registered Resources...')
        print('\n' + '=' * 118 + '\n')

    # Skip all GUI operations in batch mode
    if not is_batch:
        start_menus.create_menus()
        if not skip_dialog:
            logger.info('Maya Main Window Menus Created...')
            print('\n' + '=' * 118 + '\n')

        # make sure there are no old windows open
        maya_main_window = ma_main_window.get_maya_window()
        if maya_main_window:
            # A missing icon answers None, and setWindowIcon(None) raises rather than
            # leaving the icon alone - which took the whole start-up down for the sake
            # of a decoration.
            window_icon = resources.icon(r'company_logos\default_logo.png')
            if window_icon:
                maya_main_window.setWindowIcon(window_icon)
            else:
                logger.warning('The window icon is not registered, so Maya keeps its own.')
            windows.close_all_mca_docked_windows(maya_main_window)
        if not skip_dialog:
            logger.info('Double Checked to make sure all windows are closed...')
    else:
        logger.info('Skipping GUI initialization (batch mode)...')

    studiolibrary_paths = os.getenv(ma_consts.STUDIOLIBRARY, None)
    if studiolibrary_paths:
        ma_configs.add_maya_system_paths(studiolibrary_paths)
        if not skip_dialog:
            logger.info('Maya Studio Library path added...')

    pose_wrangler_paths = os.getenv(ma_consts.POSE_WRANGLER, None)
    if pose_wrangler_paths:
        ma_configs.add_maya_system_paths(pose_wrangler_paths)
        #disable plugin
        #load_plugins()
        if not skip_dialog:
            logger.info('Maya Epic Pose Wrangler path added...')

    # ue_ml_deformer = os.getenv(ma_consts.MCA_UE_ML_DEFORMER, None)
    # if ue_ml_deformer:
    #     ml_loaded = False
    #     ml_loaded = ma_configs.add_maya_module(ue_ml_deformer)
    #     if not skip_dialog and ml_loaded:
    #         logger.info('Maya Epic ML Deformer path added...')
    #     elif not skip_dialog and not ml_loaded:
    #         logger.info(f'ML Deformer Path: {ue_ml_deformer}\n')

    third_party_paths = os.getenv(ma_consts.THIRDPARTY, None)
    if third_party_paths:
        ma_configs.add_maya_system_paths(third_party_paths)
        if not skip_dialog:
            logger.info('Maya Third Party Tools path added...')
    #
    # Maya Dependencies paths
    depend_paths = os.getenv(ma_consts.DEPS_ROOT, None)
    if depend_paths:
        ma_configs.add_maya_system_paths(depend_paths)
        if not skip_dialog:
            logger.info('Maya Dependencies paths added...')

    # Refill toolbox docks that already exist (restart / restored workspace) and open the toolboxes flagged "Open On
    # Startup" (skip in batch mode). Imported here because the toolbox window pulls in Maya's UI mixin, which headless
    # sessions don't need.
    if not is_batch:
        from mca.mya.tools.toolbox import ma_toolbox_ui
        ma_toolbox_ui.open_startup_toolboxes()

    # Set Project path. An empty root is not a workspace, and openWorkspace on one
    # errors instead of doing nothing.
    project_root = project_paths.get_project_path()
    if project_root:
        cmds.workspace(project_root, openWorkspace=True)
    else:
        logger.warning('No project root is set, so the Maya workspace was left alone.')


    # set default settings #################################
    new_prefs = ma_configs.MayaDefaultStartOptions.load()
    new_prefs.apply_maya_defaults()

    print(f'DEPOT VERSION: {DEPOT_VERSION}')
    print('\n' + '=' * 118 + '\n')

    # # Initialize Maya AI at the END of Maya startup
    # # This must happen last so all Maya systems are ready
    # try:
    #     _init_ai(skip_dialog=skip_dialog, is_batch=is_batch)
    # except Exception as e:
    #     # Log but don't fail startup if AI init fails
    #     logger.warning(f'Maya AI initialization failed: {e}')


def shutdown(skip_dialog=False):
    """
    Shutdown the MCA Maya framework.

    :param bool skip_dialog: If True, nothing will be written to the console.
    """

    # Shutdown Maya AI first (before removing menus/windows)
    try:
        _shutdown_ai(skip_dialog=skip_dialog)
    except Exception as e:
        logger.warning(f'Maya AI shutdown failed: {e}')

    start_menus.remove_menus()

    maya_main_window = ma_main_window.get_maya_window()
    windows.close_all_mca_docked_windows(maya_main_window)
    if not cmds.about(batch=True):
        # Toolboxes dock through workspace controls, which close_all_mca_docked_windows does not see. Empty the docks
        # but keep them, so startup_init refills each toolbox where the user had it docked.
        try:
            from mca.mya.tools.toolbox import ma_toolbox_ui
            ma_toolbox_ui.release_toolboxes()
        except Exception as e:
            logger.warning(f'Toolbox windows could not be closed: {e}')

    main_window_obj_names = ['MCA_p4v_workspace']
    windows.remove_widgets_by_name(parent_window=maya_main_window, widget_names=main_window_obj_names)

    # Remove Maya's paths from sys.path
    depend_paths = os.getenv(ma_consts.DEPS_ROOT, None)
    maya_root_path = mya.MAYA_PATH
    if depend_paths:
        config.remove_sys_path([depend_paths, maya_root_path])

    if not skip_dialog:
        logger.info('Maya menus removed successfully')
        logger.info('Maya docked windows closed successfully')
        logger.info('Maya framework shutdown successfully')
        logger.info('\n' + '=' * 160 + '\n')


def init(skip_dialog=False):
    """
    This is a temporary fix.  We will need to change all the init calls to the startup init.
    So we can remove this function.
    # ToDo @comes Change all the init calls to the startup_init.

    :param bool skip_dialog: If True, will not print any dialogs
    """

    startup_init(skip_dialog=skip_dialog)


def load_plugins():
    pose_wrangler_paths = os.getenv(ma_consts.POSE_WRANGLER, None)
    version = cmds.about(version=True)
    plugin_path = f'plug-ins\\windows\\{version}\\MayaUERBFPlugin.mll'
    if pose_wrangler_paths:
        path = os.path.join(os.path.dirname(os.getenv(ma_consts.POSE_WRANGLER)), plugin_path)
        loaded = plugins.load_plugin(os.path.normpath(path))
        if loaded:
            logger.info('Epic Pose Wrangler Plug-in loaded successfully')
