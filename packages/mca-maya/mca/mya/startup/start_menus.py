"""
These are the Maya menus that get loaded
"""

# python imports
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional

# software specific imports
from mca.common.pyqt.pygui import qtwidgets, qtcore
# mca python imports
from mca.mya.pyqt.utils import ma_main_window
from mca.common import log
from mca.common.startup import startup_menus
from mca.common.pyqt.qt_utils import qt_menus
from mca.common.resources import resources

from mca.mya.tools.summoner import summoner
from mca.mya.tools.reanimator import reanimator
from mca.mya.tools.animationexporter import animationexporter_ui
from mca.mya.tools.assetregister import ma_asset_register
from mca.mya.utils import ma_fileio, optionvars
from mca.mya.pyqt import mayawindows


logger = log.MCA_LOGGER

# Registering resources at import time is what turned a missing icon folder into a dead
# toolset: this module is imported by mya/startup/startup.py, which already calls
# register_resources() itself, in startup_init, where a failure can be reported.


ACTION_PROJ_DOCS = 'ProjectDocuments'
MENU_HELP_DOCS = 'HelpDocuments'
ACTION_ANIM_DOCS = 'Animation Help'
ACTION_MODEL_DOCS = 'Modeling Help'
ACTION_RIG_DOCS = 'Rigging Help'
ACTION_TRACKER_DOCS = 'Issue Tracker'

MENU_MCA_TOOLS = 'Mechanical Art'
MENU_MCA_TOOLBOX = 'Toolbox'

try:
    from mca.ai.utils.config_loader import load_config as _LOAD_CONFIG
except ImportError:  # pragma: no cover
    _LOAD_CONFIG = None

_AI_PACKAGE_NAMES = ("mca-ai",)
_AI_NAMESPACE_PATHS = (
    ("mca", "mca-ai", "mca"),
)
_AI_RUNTIME: Dict[str, object] = {}
_AI_STARTED = False


def action_proj_docs(maya_menu_bar, maya_window):
    """
    Adds the help docs to Maya's main window.

    :param QMainWindow maya_window: Maya's main window
    """

    menu_inst = qt_menus.MainWindowsMenus(maya_menu_bar, maya_window)

    # Add Project Documents Action
    menu_inst.add_action(ACTION_PROJ_DOCS, startup_menus.project_url_menu, icon=resources.icon(r'company_logos\default_logo.png'))


def menu_help_urls(maya_window):
    """
    Adds the Help docs to Maya's main window.

    :param QMainWindow maya_window: Maya's main window
    """

    menu_inst = qt_menus.MainWindowsMenus.create(MENU_HELP_DOCS, maya_window, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_inst.add_action(ACTION_ANIM_DOCS, startup_menus.animation_url_menu, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_inst.add_action(ACTION_MODEL_DOCS, startup_menus.modeling_url_menu, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_inst.add_action(ACTION_RIG_DOCS, startup_menus.rigging_url_menu, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_inst.add_separator()
    menu_inst.add_action(ACTION_TRACKER_DOCS, startup_menus.tracker_url_menu, icon=resources.icon(r'company_logos\default_logo.png'))


def menu_mca_tools(maya_window):
    """
    Adds the toolbox to Maya's main window.

    :param QMainWindow maya_window: Maya's main window
    """

    menu_tools_inst = qt_menus.MainWindowsMenus.create(MENU_MCA_TOOLBOX, maya_window)
    _attach_toolbox_menu(menu_tools_inst.menu)


def _attach_toolbox_menu(menu):
    """
    Fill a menu with the toolboxes each time it opens. The toolbox module is imported lazily so building the menus
    at startup does not load the toolbox UI.

    :param qtwidgets.QMenu menu: The menu to fill.
    """

    def fill():
        from mca.mya.tools.toolbox import ma_toolbox_ui
        # Connect the real filler once, then run it for this first opening.
        menu.aboutToShow.disconnect(fill)
        ma_toolbox_ui.attach_toolbox_menu(menu)
        ma_toolbox_ui.fill_toolbox_menu(menu)

    menu.aboutToShow.connect(fill)


def _open_settings():
    """
    Open the MCA settings window.

    Imported here rather than at module level: ``start_menus`` is imported while Maya is
    starting, and a settings window is not something a menu needs in order to be drawn.
    """

    from mca.mya.tools.settings import settings_ui

    return settings_ui.show_settings()


def menu_mca_quick_tools(maya_window):
    """
    Adds the toolbox to Maya's main window.

    :param QMainWindow maya_window: Maya's main window
    """

    menu_tools_inst = qt_menus.MainWindowsMenus.create(MENU_MCA_TOOLS, maya_window) #, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_toolbars = qt_menus.MainWindowsMenus(menu_tools_inst.menu, maya_window)
    # Top-level entry point for the unified asset register (alongside the
    # submenus below). Kept at the top of the menu for quick access.
    menu_toolbars.add_action(
        'Asset Register',
        lambda sacrificial=False: ma_asset_register.MayaUnifiedRegister(),
        icon=resources.icon(r'company_logos\mca.png'),
    )
    # Maya's own settings, and a read-only view of what the framework resolved. Imported
    # inside the callback so building the menus does not pull in the window.
    menu_toolbars.add_action(
        'Settings',
        lambda sacrificial=False: _open_settings(),
        icon=resources.icon(r'company_logos\mca.png'),
    )

    menu_tools_inst = qt_menus.MainWindowsMenus.create(MENU_MCA_TOOLS, maya_window)
    menu_toolbars = qt_menus.MainWindowsMenus(menu_tools_inst.menu, maya_window)
    menu_toolbars.add_menu('General')
    menu_toolbars.add_action('Check Out Scene', ma_fileio.checkout_current_scene, icon=resources.icon(r'software\p4v.png'))
    # menu_toolbars.add_action(
    #     'Start MCA AI Agent',
    #     lambda sacrificial=False: start_ai_agent(),
    #     icon=resources.icon(r'company_logos\default_logo.png'),
    # )
    # menu_toolbars.add_action(
    #     'Shutdown MCA AI Agent',
    #     lambda sacrificial=False: shutdown_ai_agent(),
    #     icon=resources.icon(r'company_logos\default_logo.png'),
    # )
    # The AI Tools submenu lived here. Its three entries all opened mca.mya.tools
    # .ai_wizard, which is not part of this repository, so the menu is not built
    # rather than offering three items that cannot open.
    menu_tools_inst = qt_menus.MainWindowsMenus.create(MENU_MCA_TOOLS, maya_window)
    menu_toolbars = qt_menus.MainWindowsMenus(menu_tools_inst.menu, maya_window)
    menu_toolbars.add_menu('Modeling')
    menu_toolbars.add_action('Summoner', summoner.SummonerUI, icon=resources.icon(r'company_logos\mca.png'))
    # DEPRECATED 2025-01-14: Model Shop merged into Summoner
    # menu_toolbars.add_action('Model Shop', modelshop.ModelShopUI, icon=resources.icon(r'company_logos\mca.png'))
    menu_tools_inst = qt_menus.MainWindowsMenus.create(MENU_MCA_TOOLS, maya_window)
    menu_toolbars = qt_menus.MainWindowsMenus(menu_tools_inst.menu, maya_window)
    menu_toolbars.add_menu('Animation')
    menu_toolbars.add_action('Re-Animator', reanimator.Reanimator, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_toolbars.add_action('Export Animations', animationexporter_ui.AnimationExporter, icon=resources.icon(r'company_logos\default_logo.png'))
    menu_toolbars.add_action('Animation Library', _launch_animation_library, icon=resources.icon(r'company_logos\default_logo.png'))
    # The Face submenu lived here. Face Staging and Face Skinning both need the
    # mya.face package, which is not part of this repository.
    # UE Tools submenu
    menu_tools_inst = qt_menus.MainWindowsMenus.create(MENU_MCA_TOOLS, maya_window)
    menu_toolbars = qt_menus.MainWindowsMenus(menu_tools_inst.menu, maya_window)
    menu_toolbars.add_menu('UE Tools')
    # ML Deformer nested submenu
    menu_ml_deformer = qt_menus.MainWindowsMenus(menu_toolbars.menu, maya_window)
    menu_ml_deformer.add_menu('ML Deformer')
    menu_ml_deformer.add_action('Pose Generator', _launch_ml_deformer_ui, icon=resources.icon(r'software\ue-logo.png'))
    menu_ml_deformer.add_action('Export to Unreal', _launch_ml_export_ui, icon=resources.icon(r'software\ue-logo.png'))
    menu_ml_deformer.add_action('Pose Extraction', _launch_ml_pose_extraction_ui, icon=resources.icon(r'software\ue-logo.png'))
    menu_ml_deformer.add_action('Pose Remixer', _launch_ml_pose_remixer_ui, icon=resources.icon(r'software\ue-logo.png'))
    # ToolBox submenu
    menu_toolbars = qt_menus.MainWindowsMenus(menu_tools_inst.menu, maya_window)
    toolbox_menu = menu_toolbars.add_menu('ToolBox')
    _attach_toolbox_menu(toolbox_menu)


# Every menu this module puts on Maya's menu bar, so one list drives both building and
# tearing down and the two cannot drift apart.
MCA_MENUS = (MENU_HELP_DOCS, MENU_MCA_TOOLS, MENU_MCA_TOOLBOX)


def create_menus():
    """
    Build the framework's menus on Maya's main menu bar.

    Safe to call more than once: whatever is already there comes down first.

    It was not safe before, and calling it twice - reloading the tools, re-running
    start-up - gave a second copy of every entry. The guard that was meant to prevent
    that looked for ACTION_PROJ_DOCS on the menu bar before clearing anything, and that
    action has not existed since action_proj_docs() was commented out, so the guard never
    matched and nothing was ever cleared. menu_mca_quick_tools() then called add_menu()
    for each section, which builds a new QMenu unconditionally, so the submenus
    multiplied along with the actions.
    """

    maya_window = ma_main_window.get_maya_window()
    if maya_window is None:
        logger.debug('No Maya main window, so there is nowhere to hang the menus.')
        return

    remove_menus()

    # Add Project URL Documents Action
    #action_proj_docs(maya_menu_bar, maya_window)
    # Help URLs
    #menu_help_urls(maya_window)
    # Tools
    menu_mca_quick_tools(maya_window)
    # Toolbox
    #menu_mca_tools(maya_window)


def remove_menus():
    """
    Take the framework's menus back off Maya's menu bar.

    A menu that is not there is left alone. This used to reach for
    ``MainWindowsMenus.create``, which *builds* a menu when it is missing - so removing
    menus that had never been built built them, and in a batch Maya, where create answers
    None, the ``.remove_menu()`` on the following line raised AttributeError.
    """

    maya_window = ma_main_window.get_maya_window()
    if maya_window is None:
        return

    for menu_name in MCA_MENUS:
        found = qt_menus.MainWindowsMenus.find(menu_name, maya_window)
        if found is not None:
            found.remove_menu()

    maya_menu_bar = ma_main_window.get_main_menu_menubar()
    if maya_menu_bar is not None:
        qt_menus.MainWindowsMenus(maya_menu_bar, maya_window).remove_action(ACTION_PROJ_DOCS)

    force_remove_actions()


def force_remove_actions():
    """
    Drop any framework action left sitting directly on the menu bar.
    """

    menu_bar = ma_main_window.get_main_menu_menubar()
    if menu_bar is None:
        return

    for child in menu_bar.children():
        name = child.objectName()
        if any(action_name in name for action_name in (ACTION_PROJ_DOCS,)):
            child.deleteLater()


# The Perforce workspace combo box that used to be inserted into Maya's status line
# lived here. It is gone, and so are P4vMainFrame and MCAP4vMainMenuOptionVars.
#
# It read the machine's Perforce client at start-up to list every workspace on the
# machine, which is the same machine-wide guess that put another project's workspace
# on this one. Which source control a project uses, and which workspace, is declared
# in that project's preferences now and set in the launcher's project setup.
#
# Removing it also takes one more piece of start-up work off Maya's main window.


def start_ai_agent(skip_dialog: bool = False) -> None:
    """
    Start the MCA AI stack on demand by injecting the package paths and running startup hooks.

    :param bool skip_dialog: When ``True`` suppresses verbose startup logs.
    :return: ``None``.
    :rtype: None
    """

    global _AI_STARTED
    if _AI_STARTED:
        logger.info('MCA AI agent is already running.')
        return

    added_paths = _ensure_ai_sys_path()
    try:
        from importlib import import_module

        import_module("mca")
    except ModuleNotFoundError:
        logger.exception('Base MCA package is not available; cannot start AI agent.')
        _cleanup_ai_paths(added_paths)
        return

    _extend_mca_namespace()
    if added_paths:
        logger.info(f'Added MCA AI package paths: {added_paths}')
    logger.debug(f'MCA packages root resolved to: {_packages_root()}')
    _ensure_ai_config_env()

    existing_mca = sys.modules.get("mca")
    if existing_mca is not None and not hasattr(existing_mca, "__path__"):
        logger.info('Reloading MCA namespace module to enable AI integrations.')
        sys.modules.pop("mca")

    try:
        ai_startup = _import_ai_module('mca.ai.startup.startup')
        maya_startup = _import_ai_module('mca.mya.ai.startup.ai_startup')
    except ImportError:
        logger.exception('Failed to import MCA AI startup modules.')
        _cleanup_ai_paths(added_paths)
        return

    gateway_proc = _maybe_launch_gateway(ai_startup)

    try:
        ai_state = ai_startup.startup_init(skip_dialog=skip_dialog)
        maya_state = maya_startup.startup_init(skip_dialog=skip_dialog)
    except Exception:
        logger.exception('Error while starting MCA AI agent.')
        try:
            maya_startup.shutdown(skip_dialog=True)
        except Exception:
            logger.debug('Maya AI shutdown skipped or failed during rollback.', exc_info=True)
        try:
            ai_startup.shutdown()
        except Exception:
            logger.debug('AI Core shutdown skipped or failed during rollback.', exc_info=True)
        _cleanup_ai_paths(added_paths)
        if gateway_proc is not None:
            _stop_gateway_process(gateway_proc, ai_startup)
        return

    if gateway_proc is not None:
        if hasattr(ai_startup, "register_gateway_process"):
            ai_startup.register_gateway_process(gateway_proc)
        _AI_RUNTIME['gateway_proc'] = gateway_proc

    _AI_RUNTIME.update(
        {
            'paths': added_paths,
            'ai_startup': ai_startup,
            'maya_startup': maya_startup,
            'ai_state': ai_state,
            'maya_state': maya_state,
        }
    )
    _AI_STARTED = True
    logger.info('MCA AI agent started successfully.')


def shutdown_ai_agent(skip_dialog: bool = False) -> None:
    """
    Shutdown the MCA AI stack if it is currently running.

    :param bool skip_dialog: When ``True`` suppresses verbose shutdown logs.
    :return: ``None``.
    :rtype: None
    """

    global _AI_STARTED
    if not _AI_STARTED:
        logger.info('MCA AI agent is not running; shutdown skipped.')
        return

    maya_startup = _AI_RUNTIME.get('maya_startup')
    ai_startup = _AI_RUNTIME.get('ai_startup')

    if maya_startup is not None:
        try:
            maya_startup.shutdown(skip_dialog=skip_dialog)
        except Exception:
            logger.exception('Failed to shutdown MCA Maya AI cleanly.')

    if ai_startup is not None:
        try:
            ai_startup.shutdown()
        except Exception:
            logger.exception('Failed to shutdown MCA AI Core cleanly.')

    gateway_proc = _AI_RUNTIME.get('gateway_proc')
    if gateway_proc is not None:
        _stop_gateway_process(gateway_proc, ai_startup)

    _AI_RUNTIME.clear()
    _AI_STARTED = False
    logger.info('MCA AI agent shutdown complete.')


def _ensure_ai_sys_path() -> List[str]:
    """
    Ensure the optional AI package directories are available on ``sys.path``.

    :return: List of path entries that were newly added.
    :rtype: List[str]
    """

    packages_root = _packages_root()
    added: List[str] = []
    for package_name in _AI_PACKAGE_NAMES:
        package_path = str(packages_root / package_name)
        if package_path not in sys.path:
            sys.path.insert(0, package_path)
            added.append(package_path)
    return added


def _cleanup_ai_paths(paths: List[str]) -> None:
    """
    Remove paths previously added to ``sys.path`` during a failed startup.

    :param List[str] paths: Path entries to remove.
    :return: ``None``.
    :rtype: None
    """

    for path in paths:
        try:
            sys.path.remove(path)
        except ValueError:
            continue


def _extend_mca_namespace() -> None:
    """
    Extend the existing ``mca`` namespace package with the AI Core module path when present.

    :return: ``None``.
    :rtype: None
    """

    from importlib import invalidate_caches

    for namespace, package_root, relative in _AI_NAMESPACE_PATHS:
        module = sys.modules.get(namespace)
        if module is None:
            continue

        namespace_path = getattr(module, "__path__", None)
        if namespace_path is None:
            continue

        candidate = str(_packages_root() / package_root / relative)
        if candidate not in namespace_path:
            namespace_path.append(candidate)
            invalidate_caches()
            logger.debug(f'Extended namespace {namespace} with {candidate}')


def _import_ai_module(module_name: str) -> ModuleType:
    """
    Import the requested module lazily to avoid upfront dependency costs.

    :param str module_name: Dotted path for the module to import.
    :return: Imported module object.
    :rtype: ModuleType
    """

    from importlib import import_module

    return import_module(module_name)


def _ensure_ai_config_env() -> None:
    """
    Ensure the environment variables for AI configuration point to valid files.

    :return: ``None``.
    :rtype: None
    """

    default_config = _packages_root() / "mca-ai" / "config.yaml"
    if not default_config.exists():
        logger.warning('Default MCA AI config file not found at %s', default_config)
        return

    for env_var in ("MCA_AI_CORE_CONFIG", "MCA_MAYA_AI_CONFIG_PATH"):
        override = os.environ.get(env_var)
        if override:
            override_path = Path(override).expanduser()
            if override_path.exists():
                continue
            logger.warning('%s points to missing file %s. Using default %s.', env_var, override_path, default_config)
        os.environ[env_var] = str(default_config)


def _maybe_launch_gateway(ai_startup: ModuleType) -> Optional[subprocess.Popen]:
    """
    Launch the mock AI gateway if auto-start is enabled and not already running.

    :param ModuleType ai_startup: AI Core startup module used for process registration.
    :return: Mock gateway process handle or ``None`` when skipped.
    :rtype: Optional[subprocess.Popen]
    """

    if not _should_auto_launch_gateway():
        return None

    existing = _AI_RUNTIME.get('gateway_proc')
    if isinstance(existing, subprocess.Popen):
        if existing.poll() is None:
            if hasattr(ai_startup, "register_gateway_process"):
                ai_startup.register_gateway_process(existing)
            logger.debug('MCA AI mock gateway already running; reusing existing process.')
            return existing
        _AI_RUNTIME.pop('gateway_proc', None)

    script_path = _packages_root() / "mca-ai" / "mock_gateway.py"
    if not script_path.exists():
        logger.warning('Mock gateway script not found at %s; skipping auto-start.', script_path)
        return None

    python_executable = _python_executable()
    logger.debug('Launching mock gateway with interpreter: %s', python_executable)
    command = [python_executable, str(script_path)]

    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        process = subprocess.Popen(
            command,
            cwd=str(script_path.parent),
            creationflags=creationflags,
        )
    except Exception:
        logger.exception('Failed to launch MCA AI mock gateway.')
        return None

    logger.info('MCA AI mock gateway started (PID %s).', process.pid)
    return process


def _python_executable() -> str:
    """
    Determine the Python executable to use when spawning subprocesses.

    :return: Python executable path or command.
    :rtype: str
    """

    executable = sys.executable or ""
    if executable:
        exe_path = Path(executable)
        exe_lower = exe_path.name.lower()
        if exe_lower.startswith("maya"):
            mayapy = exe_path.with_name("mayapy.exe")
            if mayapy.exists():
                return str(mayapy)
            mayapy_unix = exe_path.with_name("mayapy")
            if mayapy_unix.exists():
                return str(mayapy_unix)
        return str(exe_path)

    maya_location = os.environ.get("MAYA_LOCATION")
    if maya_location:
        maya_path = Path(maya_location) / "bin"
        mayapy = maya_path / "mayapy.exe"
        if mayapy.exists():
            return str(mayapy)
        mayapy_unix = maya_path / "mayapy"
        if mayapy_unix.exists():
            return str(mayapy_unix)

    env_executable = os.environ.get("PYTHON_EXECUTABLE")
    if env_executable:
        return env_executable

    return "python"


def _should_auto_launch_gateway() -> bool:
    """
    Return whether the mock gateway should be auto-started.

    :return: ``True`` when auto-start is enabled.
    :rtype: bool
    """

    flag = os.environ.get("MCA_AI_AUTO_GATEWAY", "1").lower()
    if flag in {"0", "false", "no"}:
        return False

    if _config_uses_remote_gateway():
        return False

    return True


def _config_uses_remote_gateway() -> bool:
    """
    Determine whether the current configuration points to a remote gateway.

    :return: ``True`` when the config URL is not a local mock endpoint.
    :rtype: bool
    """

    config_path = os.environ.get("MCA_AI_CORE_CONFIG")
    if not config_path:
        config_path = str(_packages_root() / "mca-ai" / "config.yaml")

    try:
        config = _get_config_loader()(config_path)
    except Exception:
        return False

    url = str(config.get("AI_GATEWAY_URL") or "").lower()
    if not url:
        return False

    local_prefixes = (
        "http://127.",
        "https://127.",
        "http://localhost",
        "https://localhost",
        "http://0.0.0.0",
        "https://0.0.0.0",
    )
    return not url.startswith(local_prefixes)


def _get_config_loader():
    """Return a callable that loads the AI Core configuration."""

    global _LOAD_CONFIG

    if _LOAD_CONFIG is None:
        try:
            from importlib import import_module

            module = import_module("mca.ai.utils.config_loader")
            _LOAD_CONFIG = module.load_config
        except Exception:
            _LOAD_CONFIG = _load_config_fallback

    return _LOAD_CONFIG or _load_config_fallback


def _load_config_fallback(path):
    """Minimal configuration loader used when AI Core helpers are unavailable."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)

    try:
        import json

        with resolved.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        try:
            import yaml

            with resolved.open("r", encoding="utf-8") as handle:
                return yaml.safe_load(handle)
        except Exception as exc:
            raise exc


def _stop_gateway_process(process: subprocess.Popen, ai_startup: Optional[ModuleType]) -> None:
    """
    Terminate the mock gateway process gracefully.

    :param subprocess.Popen process: Process handle to terminate.
    :param Optional[ModuleType] ai_startup: AI startup module for process deregistration.
    :return: ``None``.
    :rtype: None
    """

    if ai_startup is not None and hasattr(ai_startup, "register_gateway_process"):
        ai_startup.register_gateway_process(None)

    if process.poll() is not None:
        _AI_RUNTIME.pop('gateway_proc', None)
        return

    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    except Exception:
        logger.exception('Failed to terminate MCA AI mock gateway process cleanly.')
    finally:
        _AI_RUNTIME.pop('gateway_proc', None)


def _packages_root():
    """
    Return the shared framework packages directory that hosts AI dependencies.

    :return: Packages root path.
    :rtype: pathlib.Path
    """

    from pathlib import Path

    return Path(__file__).resolve().parents[4]


# --- Face Launchers ---

def _launch_animation_library(*args, **kwargs):
    """
    Open the Animation Library.

    Imported lazily, like the face tools: the library pulls in pymel and the
    catalog, and neither is worth paying for at boot when the menu may never be
    clicked.

    :return: The window.
    :rtype: AnimationLibrary
    """

    from mca.mya.tools.animlibrary import animlibrary_ui
    return animlibrary_ui.AnimationLibrary()


# --- UE Tools Launchers ---

def _launch_ml_deformer_ui():
    """
    Launch MLDeformer Random Pose Generator UI.

    Lazy-imports the MLDeformer module to avoid loading dependencies until needed.
    """
    try:
        from mldeformer.ui.maya.integration.menu.maya_menu import show_deformer_ui
        show_deformer_ui()
    except ImportError as e:
        logger.error(f'Failed to launch ML Deformer UI: {e}')
        logger.error('Make sure MLDeformer module is loaded.')


def _launch_ml_export_ui():
    """
    Launch MLDeformer Export to Unreal UI.

    Lazy-imports the MLDeformer module to avoid loading dependencies until needed.
    """
    try:
        from mldeformer.ui.maya.integration.menu.maya_menu import show_export_ui
        show_export_ui()
    except ImportError as e:
        logger.error(f'Failed to launch ML Deformer Export UI: {e}')
        logger.error('Make sure MLDeformer module is loaded.')


def _launch_ml_pose_extraction_ui():
    """
    Launch MLDeformer Pose Extraction UI.

    Lazy-imports the MLDeformer module to avoid loading dependencies until needed.
    """
    try:
        from mldeformer.ui.maya.integration.menu.maya_menu import show_pose_extraction_ui
        show_pose_extraction_ui()
    except ImportError as e:
        logger.error(f'Failed to launch ML Deformer Pose Extraction UI: {e}')
        logger.error('Make sure MLDeformer module is loaded.')


def _launch_ml_pose_remixer_ui():
    """
    Launch MLDeformer Pose Remixer UI.

    Lazy-imports the MLDeformer module to avoid loading dependencies until needed.
    """
    try:
        from mldeformer.ui.maya.integration.menu.maya_menu import show_pose_remixer_ui
        show_pose_remixer_ui()
    except ImportError as e:
        logger.error(f'Failed to launch ML Deformer Pose Remixer UI: {e}')
        logger.error('Make sure MLDeformer module is loaded.')


