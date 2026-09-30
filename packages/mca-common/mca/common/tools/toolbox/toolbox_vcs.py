"""
Version control for shared toolbox files.

Shared toolbox files live in the depot, so every write goes through a backend that checks the file out first, adds
new files and marks deleted files. Personal (local) files use :class:`LocalBackend`, which only touches disk.

The Perforce backend syncs a file before opening it for edit so a user always edits the latest section, and it
reports when someone else already has the file open (toolbox YAML is plain text, so Perforce allows that and merges
at submit). Nothing here ever submits.

Which backend a library uses is :func:`shared_backend`'s answer, and that asks
:mod:`mca.common.sourcecontrol`. The version this replaces had ``P4Backend()`` as the library's
default outright, so on a machine with no Perforce every ``p4 fstat`` came back "not installed",
``prepare_edit`` read that as a file it could not check out, and **every edit to a shared
toolbox failed with an error box** - on a contractor's laptop, a build agent, or anybody whose
studio uses something else.

The lifecycle here - prepare a file for writing, say what to warn the user about, mark a
deletion - is not what the source control interface does, which is checkout/add/submit over a
list of paths. So the toolbox keeps its own small backends and takes the connection details from
the interface, rather than either one pretending to be the other.

Requires: the ``p4`` command line client on PATH for :class:`P4Backend`.
Side effects: runs ``p4 sync / edit / add / delete / revert`` on the files it is given.
"""

# python imports
import os
import stat
import subprocess

# MCA python imports
from mca.common import log
from mca.common import sourcecontrol

logger = log.MCA_LOGGER

__all__ = ['ToolboxWriteError', 'LocalBackend', 'P4Backend', 'shared_backend']

# Seconds before a p4 call is abandoned, so a dead server cannot hang the DCC forever.
P4_TIMEOUT = 30


class ToolboxWriteError(Exception):
    """
    Raised when a toolbox file cannot be made writable or saved. The message is written for artists.
    """


class LocalBackend:
    """
    No version control: files are written straight to disk. Used for personal toolboxes and tests.
    """

    name = 'local'

    def prepare_edit(self, path):
        """
        Make sure an existing file can be written.

        :param str path: Absolute file path.
        :return: Warnings for the user (always empty here).
        :rtype: list[str]
        """

        if os.path.isfile(path) and not os.access(path, os.W_OK):
            raise ToolboxWriteError(f'{os.path.basename(path)} is read-only.')
        return []

    def after_write(self, path, is_new):
        """
        Called after a file was written.

        :param str path: Absolute file path.
        :param bool is_new: True when the file did not exist before the write.
        :return: Warnings for the user.
        :rtype: list[str]
        """

        return []

    def delete(self, path):
        """
        Delete a file.

        :param str path: Absolute file path.
        :return: Warnings for the user.
        :rtype: list[str]
        """

        if os.path.isfile(path):
            os.remove(path)
        return []


class P4Backend(LocalBackend):
    """
    Perforce backend built on the ``p4`` command line client.

    The port and workspace come from :mod:`mca.common.sourcecontrol`, which reads them from the
    registry and the environment; failing that, from the ``p4`` client's own environment.
    """

    name = 'perforce'

    def __init__(self, changelist=None):
        """
        :param str|int changelist: Pending changelist to open files in. None uses the default changelist.
        """

        self.changelist = str(changelist) if changelist else None
        # Files this session already has open, so repeated edits to one section skip the p4 round trips.
        self._opened = set()

    # --- p4 plumbing ---------------------------------------------------------------------------------------------

    def _base_command(self):
        """
        :return: ``p4`` plus the port/workspace flags for the active workspace.
        :rtype: list[str]
        """

        details = sourcecontrol.info()
        command = [details.get('executable') or 'p4']
        if details.get('port'):
            command += ['-p', details['port']]
        if details.get('workspace'):
            command += ['-c', details['workspace']]

        return command

    def _run(self, *args):
        """
        Run one p4 command.

        :param str args: Arguments after ``p4 [-p port -c client]``.
        :return: (return code, combined stdout/stderr text).
        :rtype: tuple[int, str]
        """

        command = self._base_command() + list(args)
        # CREATE_NO_WINDOW keeps a console from flashing up when called from a GUI DCC.
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=P4_TIMEOUT,
                                    creationflags=flags)
        except FileNotFoundError:
            return 1, 'The p4 command line client is not installed or not on PATH.'
        except subprocess.TimeoutExpired:
            return 1, f'Perforce did not answer within {P4_TIMEOUT} seconds.'
        text = result.stdout.decode('utf-8', errors='replace').strip()
        logger.debug(f'Toolbox p4 {" ".join(args)} -> {result.returncode}: {text}')
        return result.returncode, text

    def _fstat(self, path):
        """
        Read the tagged fstat fields of a file.

        :param str path: Absolute file path.
        :return: Field name -> value. Empty when the file is not in the depot.
        :rtype: dict
        """

        code, text = self._run('-ztag', 'fstat', path)
        fields = {}
        for line in text.splitlines():
            if line.startswith('... '):
                key, _, value = line[4:].partition(' ')
                fields[key] = value
        if 'no such file' in text or 'not under client' in text or 'not in client view' in text:
            fields['_not_in_depot'] = '1'
        return fields

    def _changelist_args(self):
        """
        :return: ``['-c', cl]`` when a changelist was given, else an empty list.
        :rtype: list[str]
        """

        return ['-c', self.changelist] if self.changelist else []

    # --- backend API ---------------------------------------------------------------------------------------------

    def prepare_edit(self, path):
        """
        Sync and check out an existing shared file so it can be written.

        :param str path: Absolute file path.
        :return: Warnings for the user, e.g. who else has the file open.
        :rtype: list[str]
        """

        norm = os.path.normcase(os.path.abspath(path))
        if not os.path.isfile(path) or norm in self._opened:
            return []

        warnings = []
        fields = self._fstat(path)
        if fields.get('_not_in_depot'):
            # A file that exists on disk but not in the depot (e.g. written offline). Adding it happens after write.
            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            return warnings

        others = [value for key, value in fields.items() if key.startswith('otherOpen') and key != 'otherOpen']
        if others:
            warnings.append(f'{os.path.basename(path)} is also checked out by {", ".join(others)}.')

        if not fields.get('action'):
            # Not open yet: get the latest revision first so the edit is made on top of other people's changes.
            if fields.get('headRev') and fields.get('haveRev') != fields.get('headRev'):
                self._run('sync', path)
            code, text = self._run('edit', *self._changelist_args(), path)
            if code != 0 or not os.access(path, os.W_OK):
                raise ToolboxWriteError(f'Could not check out {os.path.basename(path)}:\n{text}')
        self._opened.add(norm)
        return warnings

    def after_write(self, path, is_new):
        """
        Mark a newly written file for add.

        :param str path: Absolute file path.
        :param bool is_new: True when the file did not exist before the write.
        :return: Warnings for the user.
        :rtype: list[str]
        """

        if not is_new:
            return []
        code, text = self._run('add', *self._changelist_args(), path)
        if code != 0:
            return [f'Saved {os.path.basename(path)}, but Perforce could not add it:\n{text}']
        self._opened.add(os.path.normcase(os.path.abspath(path)))
        return []

    def delete(self, path):
        """
        Mark a shared file for delete. A file that was only opened for add is reverted and removed instead.

        :param str path: Absolute file path.
        :return: Warnings for the user.
        :rtype: list[str]
        """

        if not os.path.isfile(path):
            return []
        fields = self._fstat(path)
        self._opened.discard(os.path.normcase(os.path.abspath(path)))
        if fields.get('_not_in_depot'):
            os.remove(path)
            return []
        if fields.get('action') == 'add':
            self._run('revert', path)
            if os.path.isfile(path):
                os.remove(path)
            return []
        if fields.get('action'):
            # Open for edit: revert first, p4 delete refuses files that are already open.
            self._run('revert', path)
        code, text = self._run('delete', *self._changelist_args(), path)
        if code != 0 and os.path.isfile(path):
            raise ToolboxWriteError(f'Could not mark {os.path.basename(path)} for delete:\n{text}')
        return []


def shared_backend():
    """
    The backend shared toolbox files should be written through on this machine.

    :return: :class:`P4Backend` where Perforce is set up, and :class:`LocalBackend` where it is
        not - which writes the file and says nothing, rather than failing every edit.
    :rtype: LocalBackend
    """

    if sourcecontrol.name() == 'perforce' and sourcecontrol.available():
        return P4Backend()

    logger.debug('Toolbox: no Perforce on this machine, so shared files are written straight '
                 'to disk.')

    return LocalBackend()
