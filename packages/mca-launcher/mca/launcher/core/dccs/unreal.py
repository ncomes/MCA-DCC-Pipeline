"""
Unreal Engine.

Unreal is the odd one, and the abstraction has to bend for it rather than pretend:

- What the artist picks is a **project**, not a version. The engine comes from the
  project's ``EngineAssociation``.
- So its dependencies belong to the **engine**, not the project. Two projects on 5.5 share
  one dependency folder, which is why ``deps_key`` is overridden here.
- Its Python is the engine's bundled one:
  ``Engine/Binaries/ThirdParty/Python3/Win64/python.exe`` - 3.11.8 in 5.5, with pip.

An engine can be installed from the project's installer folder the same way Maya can -
``<installers>/Unreal/5.5/`` holding whatever the studio deploys with, ``.bat`` included.

The old launcher started a project with ``Popen([uproject], shell=True)``, which hands the
path to the shell and hopes the file association is right. It also means the environment it
so carefully built may or may not reach the editor. Starting ``UnrealEditor.exe`` with the
project as an argument is the same click without the guesswork.
"""

# python imports
import json
import logging
import os

# mca imports
from mca.launcher.core import platform_paths
from mca.launcher.core.dccs.base import Dcc, LaunchTarget


logger = logging.getLogger('mca-launcher')

#: Where the installed engines are listed.
ENGINE_KEYS = (r'SOFTWARE\EpicGames\Unreal Engine',
               r'SOFTWARE\WOW6432Node\EpicGames\Unreal Engine')


class Unreal(Dcc):
    """Unreal Engine."""

    name = 'unreal'
    label = 'Unreal Engine'
    icon = 'ue-logo.png'

    executable_relative = r'Engine\Binaries\Win64\UnrealEditor.exe'
    interpreter_relatives = (r'Engine\Binaries\ThirdParty\Python3\Win64\python.exe',)

    startup_folder = 'unreal'

    download_url = 'https://www.unrealengine.com/en-US/download'

    # Unreal gets an installer folder like everything else. The old launcher had none - Maya
    # and MotionBuilder could be installed from the project, Unreal could not be installed at
    # all - and a studio that deploys its engine with a batch file (a source build copied off
    # a share, a launcher script that sets the licence up first) had nowhere to put it. The
    # version folders here are engine versions: 'Unreal/5.5/deploy.bat'.
    installer_folder = 'Unreal'
    installer_name = ''

    # ------------------------------------------------------------------ #
    # Engines
    # ------------------------------------------------------------------ #
    def engine_versions(self):
        """
        :return: The installed engine versions, newest first.
        :rtype: list(str)
        """

        found = []
        for key in ENGINE_KEYS:
            for name in platform_paths.registry_sub_keys(key):
                folder = platform_paths.registry_value(key + '\\' + name, 'InstalledDirectory')
                if folder and os.path.isdir(folder) and name not in found:
                    found.append(name)

        def sortable(version):
            parts = []
            for piece in str(version).split('.'):
                parts.append(int(piece) if piece.isdigit() else 0)
            return parts

        return sorted(found, key=sortable, reverse=True)

    def engine_folder(self, version):
        """
        :param str version: An engine version, for example '5.5'.
        :return: Where it is installed, or ''.
        :rtype: str
        """

        for key in ENGINE_KEYS:
            folder = platform_paths.registry_value(key + '\\' + str(version),
                                                   'InstalledDirectory')
            if folder and os.path.isdir(folder):
                return os.path.normpath(folder)
        return ''

    def engine_for_project(self, project):
        """
        Which engine a ``.uproject`` opens with.

        :param str project: Path to the .uproject file.
        :return: The engine version, or '' when the project does not say or says a GUID -
            which is what a source build looks like, and which this cannot resolve.
        :rtype: str
        """

        if not project or not os.path.isfile(project):
            return ''
        try:
            with open(project, 'r', encoding='utf-8') as opened:
                data = json.load(opened)
        except Exception as error:
            logger.warning('Could not read %s: %s', project, error)
            return ''

        association = str(data.get('EngineAssociation') or '').strip()
        if not association or association.startswith('{'):
            # A GUID means a source build registered per user. Fall back to the newest
            # installed engine and say so rather than failing silently.
            newest = self.engine_versions()
            if newest:
                logger.info('%s is associated with a source build (%s); using engine %s.',
                            os.path.basename(project), association or 'nothing', newest[0])
                return newest[0]
            return ''
        return association

    # ------------------------------------------------------------------ #
    # The Dcc interface, with a project or an engine version as the key
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_project(key):
        return str(key).lower().endswith('.uproject')

    def _folder_for(self, key):
        version = self.engine_for_project(key) if self._is_project(key) else key
        return self.engine_folder(version) if version else ''

    def install_folder(self, version):
        """
        :param str version: An engine version, or a project path.
        :return: The engine folder, or ''.
        :rtype: str
        """

        return self._folder_for(version)

    def deps_key(self, key):
        """
        :param str key: An engine version, or a project path.
        :return: The engine version, because the dependencies belong to the engine.
        :rtype: str
        """

        if self._is_project(key):
            return self.engine_for_project(key) or 'unknown'
        return str(key)

    def targets(self):
        """
        :return: One target per installed engine. Projects come from preferences, and the
            API pairs them with these.
        :rtype: list(LaunchTarget)
        """

        found = []
        for version in self.engine_versions():
            folder = self.engine_folder(version)
            found.append(LaunchTarget(self.name, version,
                                      '{} {}'.format(self.label, version),
                                      installed=bool(folder), detail=folder))
        return found

    def command(self, key):
        """
        :param str key: A project path, or an engine version to start the editor bare.
        :return: The command.
        :rtype: list(str)
        """

        executable = self.executable(key)
        if not executable:
            if self._is_project(key):
                raise ValueError('Cannot start {}: the engine it asks for ({}) is not '
                                 'installed here.'
                                 .format(os.path.basename(str(key)),
                                         self.engine_for_project(key) or 'unspecified'))
            raise ValueError('Unreal Engine {} is not installed on this machine.'.format(key))

        if self._is_project(key):
            if not os.path.isfile(key):
                raise ValueError('That Unreal project is no longer there: {}'.format(key))
            return [executable, os.path.normpath(key)]
        return [executable]
