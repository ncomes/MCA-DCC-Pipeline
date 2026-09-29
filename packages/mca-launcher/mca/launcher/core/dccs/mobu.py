"""
Autodesk MotionBuilder.

Its interpreter is ``mobupy.exe``, not a ``python.exe`` - measured on 2024, where
``bin/x64/mobupy.exe`` is Python 3.10.8 with pip 22.3.1, and ``bin/x64/python`` holds the
runtime rather than an executable. The old launcher never installed anything for
MotionBuilder at all; it pointed the environment at a ``python310`` folder under a
``python311`` one, which did not exist.
"""

# mca imports
from mca.launcher.core.dccs.base import Dcc


class MotionBuilder(Dcc):
    """Autodesk MotionBuilder."""

    name = 'mobu'
    label = 'MotionBuilder'
    icon = 'mobu-2023.png'

    registry_key = r'SOFTWARE\Autodesk\MotionBuilder\{version}'
    registry_value = 'InstallPath'

    known_versions = ('2022', '2023', '2024', '2025', '2026')

    executable_relative = r'bin\x64\motionbuilder.exe'
    interpreter_relatives = (r'bin\x64\mobupy.exe', r'bin\x64\python\python.exe')

    startup_folder = 'mobu'

    download_url = ('https://www.autodesk.com/products/motionbuilder/free-trial')
    installer_folder = 'Mobu'
    installer_name = 'Mobu_Install.exe'
