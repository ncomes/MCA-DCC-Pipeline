"""
What every DCC has to be able to answer.

The shape is deliberately small. A DCC knows four things about itself - which versions are
here, where the program is, which Python is its own, and how it wants to be started - and
the launcher knows nothing else about it.
"""

# python imports
import logging
import os
import subprocess

# mca imports
from mca.launcher.core import platform_paths


logger = logging.getLogger('mca-launcher')


class LaunchTarget(object):
    """
    One thing the artist can start: a DCC version, or a specific Unreal project.

    Both kinds live in the same list in the window, so they answer the same questions. A
    Maya target's key is its version ('2025'); an Unreal target's key is its project path.
    """

    def __init__(self, dcc_name, key, label, installed=True, detail=''):
        self.dcc_name = dcc_name
        self.key = str(key)
        self.label = label or str(key)
        self.installed = bool(installed)
        self.detail = detail

    def as_dict(self):
        """
        :return: The target as plain data, which is what the API hands back.
        :rtype: dict
        """

        return {'dcc': self.dcc_name, 'key': self.key, 'label': self.label,
                'installed': self.installed, 'detail': self.detail}

    def __repr__(self):
        return '<{} {}:{}>'.format(type(self).__name__, self.dcc_name, self.key)


class Dcc(object):
    """
    A DCC the launcher can start.

    Subclasses fill in the registry keys and the paths inside the install folder. The
    lookup itself is here, once.
    """

    #: Lower case, and the name used everywhere: in the API, the CLI and the deps folder.
    name = ''

    #: What a person calls it.
    label = ''

    #: Icon file in ``resources/icons``.
    icon = ''

    #: Registry key holding the install folder, with ``{version}`` in it.
    registry_key = ''

    #: Value name under that key.
    registry_value = ''

    #: Versions worth asking about. Asking the registry for each is cheaper and more
    #: reliable than enumerating, and keeps the answer in a sensible order.
    known_versions = ()

    #: Relative path of the program, inside the install folder.
    executable_relative = ''

    #: Candidate relative paths of the DCC's own Python, best first. The first that exists
    #: wins, because Autodesk moves it between versions.
    interpreter_relatives = ()

    #: Name of the folder under ``mca-common/mca/common/startup/dccs`` holding the
    #: bootstrap scripts for this DCC.
    startup_folder = ''

    # ------------------------------------------------------------------ #
    # Where it is
    # ------------------------------------------------------------------ #
    def install_folder(self, version):
        """
        :param str version: The DCC version.
        :return: Where it is installed, or '' when that version is not installed.
        :rtype: str
        """

        if not self.registry_key:
            return ''
        value = platform_paths.registry_value(
            self.registry_key.format(version=version), self.registry_value)
        if not value:
            return ''
        return os.path.normpath(value)

    def executable(self, version):
        """
        :param str version: The DCC version.
        :return: The program to start, or '' when it is not there.
        :rtype: str
        """

        folder = self.install_folder(version)
        if not folder:
            return ''
        path = os.path.normpath(os.path.join(folder, self.executable_relative))
        return path if os.path.isfile(path) else ''

    def interpreter(self, version):
        """
        The DCC's own Python - the one that must install its dependencies.

        :param str version: The DCC version.
        :return: The interpreter, or '' when it cannot be found.
        :rtype: str
        """

        folder = self.install_folder(version)
        if not folder:
            return ''
        for relative in self.interpreter_relatives:
            path = os.path.normpath(os.path.join(folder, relative))
            if os.path.isfile(path):
                return path
        return ''

    def is_installed(self, version):
        """
        :param str version: The DCC version.
        :return: Whether both the program and its Python are present.
        :rtype: bool
        """

        return bool(self.executable(version)) and bool(self.interpreter(version))

    # ------------------------------------------------------------------ #
    # What can be started
    # ------------------------------------------------------------------ #
    def targets(self):
        """
        Every version of this DCC that is installed on this machine.

        Read from the registry, which is what "installed" actually means. The old launcher
        listed a folder of installers inside the depot instead, so a clean clone offered
        nothing to launch and said nothing about why.

        :return: The targets, newest first.
        :rtype: list(LaunchTarget)
        """

        found = []
        for version in self.known_versions:
            if self.is_installed(version):
                found.append(LaunchTarget(self.name, version,
                                          '{} {}'.format(self.label, version),
                                          detail=self.install_folder(version)))
        found.reverse()
        return found

    # ------------------------------------------------------------------ #
    # Starting it
    # ------------------------------------------------------------------ #
    def deps_key(self, key):
        """
        Which dependency folder this target uses.

        For Maya and MotionBuilder that is the version. Unreal overrides it, because a
        project's dependencies belong to the engine it opens with, not to the project.

        :param str key: The version, or for Unreal the project path.
        :return: The key used in ``%LOCALAPPDATA%/MCA/deps/<dcc>-<key>``.
        :rtype: str
        """

        return str(key)

    def command(self, key):
        """
        :param str key: The version, or for Unreal the project path.
        :return: The command to run.
        :rtype: list(str)
        """

        executable = self.executable(key)
        if not executable:
            raise ValueError('{} {} is not installed on this machine, or its files have '
                             'moved.'.format(self.label, key))
        return [executable]

    def launch(self, key, environment):
        """
        Start it.

        :param str key: The version, or for Unreal the project path.
        :param dict environment: The whole environment to start it with.
        :return: The process id.
        :rtype: int
        """

        command = self.command(key)
        logger.info('launching: %s', ' '.join(command))
        # No pipes. The old launcher passed stdout=PIPE and never read it, so a chatty DCC
        # could fill the pipe buffer and block - and it also meant the DCC's own output went
        # nowhere anybody could see.
        process = subprocess.Popen(command, env=environment,
                                   cwd=os.path.dirname(command[0]) or None)
        return process.pid
