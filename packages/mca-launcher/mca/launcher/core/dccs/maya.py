"""
Autodesk Maya.

Measured on a machine with four of them installed: 2022 is Python 3.7.7, 2024 is 3.10.8,
2025 is 3.11.4 and 2026 is 3.11.9. Every one of those has a working ``mayapy -m pip``, and
every one ships its own Qt - PySide2 5.15 in 2022 and 2024, PySide6 6.5.3 in 2025 and 2026.
That is why dependencies are installed per version, by ``mayapy``, and never include Qt.
"""

# mca imports
from mca.launcher.core.dccs.base import Dcc


class Maya(Dcc):
    """Autodesk Maya."""

    name = 'maya'
    label = 'Maya'
    icon = 'maya-2023.png'

    registry_key = r'SOFTWARE\Autodesk\Maya\{version}\Setup\InstallPath'
    registry_value = 'MAYA_INSTALL_LOCATION'

    # Every version the plug-ins are built for, plus the two either side of them so a
    # machine with something older or newer still gets offered what it has.
    known_versions = ('2020', '2022', '2023', '2024', '2025', '2026', '2027')

    executable_relative = r'bin\maya.exe'
    interpreter_relatives = (r'bin\mayapy.exe',)

    startup_folder = 'maya'

    download_url = 'https://www.autodesk.com/products/maya/free-trial'
    installer_folder = 'Maya'
    installer_name = 'MAYA_Install.exe'
