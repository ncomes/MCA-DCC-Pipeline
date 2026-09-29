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
import sys

# mca imports
from mca.launcher.core import platform_paths


logger = logging.getLogger('mca-launcher')

#: What counts as an installer in a studio's installer folder.
#:
#: A studio's "installer" is often not an installer at all: it is a ``.bat`` that copies a
#: prepared build off a share, or a ``.ps1`` that drives a silent MSI, or a ``.py`` that
#: talks to a licence server first. The old launcher hard coded one ``.exe`` name per DCC -
#: ``MAYA_Install.exe``, ``Mobu_Install.exe`` - and had nothing at all for Unreal, so a
#: studio whose Unreal arrives by batch file had no way to say so and got a dead entry.
INSTALLER_SUFFIXES = ('.bat', '.cmd', '.exe', '.msi', '.ps1', '.py', '.lnk', '.url')


def version_sort_key(version):
    """
    Sort '2026' after '2025' and '5.5' after '5.4', without assuming either shape.

    :param str version: A version, as a folder name or a registry key name.
    :return: Something comparable.
    :rtype: list(int)
    """

    parts = []
    for piece in str(version).replace('-', '.').replace('_', '.').split('.'):
        digits = ''.join(character for character in piece if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return parts


def installer_command(installer):
    """
    How to run an installer, which depends on what kind of file it is.

    A ``.exe`` starts itself; a ``.bat`` needs a shell; an ``.msi`` needs ``msiexec``. The
    old launcher passed ``shell=True`` and let Windows work it out, which happens to run a
    batch file but also means the argument goes through cmd's own parsing - so an installer
    under a path with an ampersand in it silently became two commands.

    :param str installer: The installer's path.
    :return: The command to run.
    :rtype: list(str)
    """

    lowered = str(installer).lower()
    shell = os.environ.get('COMSPEC') or 'cmd.exe'
    if lowered.endswith(('.bat', '.cmd')):
        return [shell, '/c', installer]
    if lowered.endswith('.ps1'):
        return ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', installer]
    if lowered.endswith('.msi'):
        return ['msiexec', '/i', installer]
    if lowered.endswith('.py'):
        return [sys.executable, installer]
    if lowered.endswith(('.lnk', '.url')):
        # Nothing runs a shortcut directly: the shell resolves it.
        return [shell, '/c', 'start', '', installer]
    return [installer]


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

    #: Where a version comes from when the machine does not have it. Opened in a browser
    #: when no studio installer is configured, so somebody cloning this repo still has a
    #: way forward rather than a dead dropdown entry.
    download_url = ''

    #: Subfolder of the project's installer folder holding this DCC's installers. Inside it,
    #: one folder per version, and inside that whatever the studio put there. Every DCC has
    #: one, Unreal included - an engine a studio deploys with a batch file is still a version
    #: the launcher can offer.
    installer_folder = ''

    #: The file name the old launcher expected, preferred when it is there so an existing
    #: studio layout behaves exactly as it did. Never required: anything in
    #: ``INSTALLER_SUFFIXES`` is accepted, because a studio renaming its installer should not
    #: silently turn into a download page with nothing saying why.
    installer_name = ''

    def installer(self, version, installers_root):
        """
        The installer to run for a version, if the project has one.

        :param str version: The version wanted.
        :param str installers_root: The project's installer folder, or ''.
        :return: The installer's path, or '' when there is not one.
        :rtype: str
        """

        folder = self.installer_folder_for(version, installers_root)
        if not folder:
            return ''

        # The name the old launcher expected, first.
        if self.installer_name:
            named = os.path.join(folder, self.installer_name)
            if os.path.isfile(named):
                return os.path.normpath(named)

        # Then whatever the studio actually put there.
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if name.lower().endswith(INSTALLER_SUFFIXES) and os.path.isfile(path):
                return os.path.normpath(path)
        return ''

    def installer_folder_for(self, version, installers_root):
        """
        :param str version: The version wanted.
        :param str installers_root: The project's installer folder, or ''.
        :return: The folder that version's installer lives in, or ''.
        :rtype: str
        """

        if not installers_root or not self.installer_folder:
            return ''
        folder = os.path.join(installers_root, self.installer_folder, str(version))
        return folder if os.path.isdir(folder) else ''

    def installer_versions(self, installers_root):
        """
        Which versions the project can install, whether or not this launcher knows them.

        A studio that adds a folder for a version nobody hard coded gets it in the dropdown
        by doing that and nothing else, which is the point of reading the folder rather than
        a list in the code.

        :param str installers_root: The project's installer folder, or ''.
        :return: The version names found, in folder order.
        :rtype: list(str)
        """

        if not installers_root or not self.installer_folder:
            return []
        folder = os.path.join(installers_root, self.installer_folder)
        if not os.path.isdir(folder):
            return []

        found = []
        try:
            names = sorted(os.listdir(folder))
        except OSError as error:
            logger.warning('Could not read the installer folder %s: %s', folder, error)
            return []
        for name in names:
            if os.path.isdir(os.path.join(folder, name)) and self.installer(name,
                                                                           installers_root):
                found.append(name)
        return found

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

    def available(self, installers_root=''):
        """
        Everything that could be started or installed: what is here, what this launcher
        supports, and what the project has an installer for.

        The dropdown shows all of it with the missing ones marked - which is how somebody
        finds out 2026 is supported before they have it, rather than after. A version only
        the studio's installer folder knows about is in here too, so a studio does not have
        to get a code change to offer one.

        :param str installers_root: The project's installer folder, or ''.
        :return: One entry per version, newest first.
        :rtype: list(LaunchTarget)
        """

        keys = []
        for target in self.targets():
            if target.key not in keys:
                keys.append(target.key)
        for version in list(self.known_versions) + self.installer_versions(installers_root):
            version = str(version)
            if version not in keys:
                keys.append(version)

        found = []
        for version in sorted(keys, key=version_sort_key, reverse=True):
            installed = self.is_installed(version)
            if installed:
                detail = self.install_folder(version)
            else:
                # Say where it would come from. "not installed" on its own leaves the next
                # question - and who to ask - unanswered.
                detail = self.installer(version, installers_root) or self.download_url
            found.append(LaunchTarget(self.name, version,
                                      '{} {}'.format(self.label, version),
                                      installed=installed, detail=detail))
        return found

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
