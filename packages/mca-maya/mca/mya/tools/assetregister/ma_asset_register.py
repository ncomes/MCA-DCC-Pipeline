"""
Asset manager UIs for Maya.

Hosts a thin wrapper around the DCC-agnostic common tool so it parents
correctly to Maya's main window:

- MayaUnifiedRegister wraps the unified asset register UI used from the
  Mechanical Art menu and the toolbox.

The older MayaAssetRegister wrapper was removed along with the legacy
AssetMainRegister it extended. Its only caller was Face Staging's
"register new head", which now opens MayaUnifiedRegister.
"""

# MCA python imports
from mca.common.tools.assetregister import unified_register
from mca.common import log
from mca.mya.pyqt.utils import ma_main_window

MAYA_MAIN_WINDOW = ma_main_window.get_maya_window()

logger = log.MCA_LOGGER


class MayaUnifiedRegister(unified_register.UnifiedRegisterUI):
    """
    Maya wrapper around the unified asset register.

    The base UI is fully DCC-agnostic — this subclass just ensures the
    window is parented to Maya's main window so it docks and closes with
    Maya sessions correctly.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent or MAYA_MAIN_WINDOW)
