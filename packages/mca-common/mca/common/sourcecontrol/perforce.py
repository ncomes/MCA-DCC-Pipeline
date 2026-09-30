"""
Perforce, as the framework uses it: check a file out, add it, sync it, send it in.

Every command is an argument list handed straight to ``p4``. The version this replaced built
each one as a string and ran it through ``shell=True``:

    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} edit -c {cl_val} {file_path}'

so **any path with a space in it went to p4 as two paths** - which is most of an artist's
machine - and anything else the shell finds meaningful in a file name was interpreted rather
than passed along.

It also guarded every operation with ``if not p4_info: return``, where ``p4_info`` is an
object with no ``__bool__``: always truthy, so the guard never once fired. On a machine
without Perforce the class gave up in its constructor, left ``user``, ``workspace`` and
``port`` as None, and every command ran as ``P4 -p None -c None edit ...``.
"""

# python imports
import os
import shutil
import subprocess

# MCA python imports
from mca.common import log
from mca.common.sourcecontrol import base
from mca.common.startup.configs import consts
from mca.common.utils import platforms


logger = log.MCA_LOGGER

#: Where Perforce keeps the current connection's settings on Windows.
REGISTRY_KEY = r'SOFTWARE\Perforce\Environment'

#: Which registry value holds what.
REGISTRY_VALUES = (('P4CLIENT', 'workspace'), ('P4USER', 'user'), ('P4PORT', 'port'))

#: Long enough for a sync of a few files, short enough that a hung p4 does not hang Maya.
TIMEOUT = 300


class Perforce(base.SourceControl):
    """
    Perforce through its command line client.

    What it knows about the connection - user, workspace, port - is read once and kept, since
    working it out means asking the registry and then running ``p4 clients``, and every
    operation would otherwise pay for it.
    """

    name = 'perforce'

    #: Perforce does not version directories, so an empty folder cannot be submitted.
    placeholder_name = '.p4keep'

    def __init__(self):
        self.executable = shutil.which('p4') or ''
        self.user = ''
        self.port = ''
        self.workspace = ''
        self._read_environment()
        if self.executable and self.user and not self.workspace:
            self.workspace = self.find_workspace()

    # -- what we know about this machine -------------------------------- #
    def _read_environment(self):
        """
        Read the connection out of the registry, then let real environment variables win.

        The version this replaces logged ``CRITICAL ERROR: Install perforce`` at error level
        whenever the key was missing, which is every machine that does not have Perforce -
        including every build agent and every artist at a studio that uses something else.
        Not having Perforce is not an error.
        """

        if platforms.IS_WINDOWS:
            try:
                import winreg

                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                    for value_name, attribute in REGISTRY_VALUES:
                        try:
                            value = winreg.QueryValueEx(key, value_name)[0]
                        except OSError:
                            continue
                        # A value can hold several, comma separated, most recent first.
                        first = str(value).split(',')[0].strip()
                        if first:
                            setattr(self, attribute, first)
            except OSError:
                logger.debug('No Perforce connection in the registry (%s).', REGISTRY_KEY)

        # P4PORT and friends in the environment are how a farm job or a second workspace is
        # pointed somewhere else, so they come after the registry, not before it.
        for value_name, attribute in REGISTRY_VALUES:
            value = os.environ.get(value_name, '')
            if value:
                setattr(self, attribute, value.strip())

    def available(self):
        """
        :return: Whether ``p4`` is installed and we know which workspace to talk about.
        :rtype: bool
        """

        return bool(self.executable and self.workspace)

    def info(self):
        """
        :return: The connection, or ``{}`` when Perforce is not set up here.
        :rtype: dict
        """

        if not self.executable:
            return {}

        return {'user': self.user, 'workspace': self.workspace, 'port': self.port,
                'executable': self.executable}

    def workspaces(self):
        """
        :return: Every workspace this user has, by name.
        :rtype: list[str]
        """

        return [line.split()[1] for line in self._client_lines() if len(line.split()) > 1]

    def find_workspace(self):
        """
        Work out which of the user's workspaces is this project's, by looking in each one's
        root for the project config file.

        :return: The workspace name, or ``''``.
        :rtype: str

        The version this replaces put its ``break`` in the inner loop of two, so a later
        workspace overwrote the one it had already found - the *last* match won, not the
        first. It also kept the names on a mutable class attribute of a singleton and
        appended without clearing, so the list grew every time anything asked.
        """

        for line in self._client_lines():
            parts = line.split()
            # Client <name> <date> root <root> '<description>'
            if len(parts) < 5:
                continue
            name, root = parts[1], parts[4]
            if os.path.isfile(os.path.normpath(os.path.join(root, consts.MCA_PROJECT_CONFIG_NAME))):
                return name

        return ''

    def _client_lines(self):
        """
        :return: A line per workspace, from ``p4 clients``.
        :rtype: list[str]
        """

        if not self.executable or not self.user:
            return []

        result, output = self._run(['clients', '-u', self.user], connected=False)
        if not result:
            return []

        # The old version split on '\r', which on Windows leaves every line but the first
        # starting with a newline.
        return [line for line in output.splitlines() if line.strip()]

    # -- running p4 ----------------------------------------------------- #
    def _run(self, arguments, connected=True, send=None, tagged=False):
        """
        Run one p4 command.

        :param list[str] arguments: The command and its arguments, without ``p4`` itself.
        :param bool connected: True passes the port and workspace, which is what an operation
            on a file needs and what asking for the workspace list must not need.
        :param str send: Text to write to p4's standard input - a filled-in form.
        :param bool tagged: True asks for ``-ztag`` output, which is field names and values
            rather than a sentence meant for a person, and so is safe to read.
        :return: Whether it worked, and everything it printed.
        :rtype: (Result, str)
        """

        if not self.executable:
            return base.Result(False, 'p4 is not installed on this machine.'), ''

        command = [self.executable]
        if tagged:
            command.append('-ztag')
        if connected:
            if self.port:
                command += ['-p', self.port]
            if self.workspace:
                command += ['-c', self.workspace]
        command += [str(argument) for argument in arguments]

        try:
            finished = subprocess.run(
                command,
                input=send,
                stdin=None if send is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=TIMEOUT,
                creationflags=0x08000000 if platforms.IS_WINDOWS else 0)
        except subprocess.TimeoutExpired:
            message = 'p4 {0} took longer than {1} seconds and was given up on.'.format(
                arguments[0] if arguments else '', TIMEOUT)
            logger.warning(message)
            return base.Result(False, message), ''
        except OSError as error:
            logger.warning('Could not run p4: %s', error)
            return base.Result(False, str(error)), ''

        output = (finished.stdout or '').strip()
        if finished.returncode:
            logger.debug('p4 %s answered %s: %s', ' '.join(arguments[:1]), finished.returncode, output)
            return base.Result(False, output or 'p4 answered {0}.'.format(finished.returncode)), output

        return base.Result(True, output), output

    def _per_file(self, verb, paths, changelist='', extra=()):
        """
        Run the same command once per file, and report the first thing that went wrong.

        :param str verb: The p4 command - ``edit``, ``add``, ``reconcile``.
        :param paths: One path or many.
        :param str changelist: A changelist number, when there is one.
        :param extra: Any flags to add before the file.
        :return: How it went, over all of them.
        :rtype: base.Result
        """

        paths = base.as_paths(paths)
        if not paths:
            return base.Result(False, 'No files were given to {0}.'.format(verb))

        problems = []
        for path in paths:
            arguments = [verb]
            if changelist:
                arguments += ['-c', str(changelist)]
            arguments += list(extra)
            arguments.append(path)
            result, _ = self._run(arguments)
            if not result:
                problems.append('{0}: {1}'.format(os.path.basename(path), result.message))

        if problems:
            return base.Result(False, '\n'.join(problems))

        return base.Result(True, '{0} {1} file(s).'.format(verb, len(paths)))

    # -- the interface -------------------------------------------------- #
    def checkout(self, paths, changelist=''):
        """
        ``p4 reconcile``, which works out whether each file is an edit, an add or a delete.

        :param paths: One path or many.
        :param str changelist: Where to put them.
        :return: How it went.
        :rtype: base.Result
        """

        return self._per_file('reconcile', paths, changelist=changelist)

    def add(self, paths, changelist=''):
        """
        :param paths: One path or many.
        :param str changelist: Where to put them.
        :return: How it went.
        :rtype: base.Result
        """

        return self._per_file('add', paths, changelist=changelist)

    def delete(self, paths, changelist=''):
        """
        :param paths: One path or many.
        :param str changelist: Where to put them.
        :return: How it went.
        :rtype: base.Result
        """

        return self._per_file('delete', paths, changelist=changelist)

    def revert(self, paths, unchanged_only=True):
        """
        :param paths: One path or many.
        :param bool unchanged_only: ``-a``: only the files nobody has actually changed.
        :return: How it went.
        :rtype: base.Result
        """

        # -k leaves the file on disk as it is, which is what every caller here wants: the
        # point is to stop having it checked out, not to lose what is in it.
        extra = ['-k', '-a'] if unchanged_only else ['-k']

        return self._per_file('revert', paths, extra=extra)

    def sync(self, paths, force=False):
        """
        :param paths: One path or many.
        :param bool force: Give the files back first, then take the latest whatever happens.
        :return: How it went.
        :rtype: base.Result
        """

        if force:
            self.revert(paths, unchanged_only=False)

        return self._per_file('sync', paths, extra=['-f'] if force else ())

    def submit(self, paths, description=''):
        """
        Reconcile the files into a changelist of their own and send it in.

        :param paths: One path or many.
        :param str description: What changed.
        :return: How it went, with p4's own words when it did not.
        :rtype: base.Result
        """

        description = description or 'mca: auto-submit'
        paths = [path for path in base.as_paths(paths) if os.path.exists(path)]
        if not paths:
            return base.Result(False, 'None of those files are on disk, so there is nothing to submit.')

        if not self.available():
            return base.Result(False, 'There is no Perforce workspace on this machine.')

        changelist = self.create_changelist(description)
        if not changelist:
            return base.Result(False, 'Could not make a changelist to submit in.')

        moved = self._per_file('reconcile', paths, changelist=changelist)
        if not moved:
            return moved

        result, output = self._run(['submit', '-c', str(changelist)])
        if not result:
            logger.error('Submitting changelist %s failed: %s', changelist, output)
            return base.Result(False, output or 'p4 submit failed.')

        logger.info('Submitted changelist %s: %s', changelist, description)

        return base.Result(True, output)

    # -- changelists ---------------------------------------------------- #
    def pending(self):
        """
        :return: This workspace's pending changelists, number to description.
        :rtype: dict

        Read from ``-ztag`` output, which names its fields. The version this replaces ran
        ``p4 changes`` and then ``p4 describe`` on every changelist it found - one process per
        changelist, on a command everybody agrees is slow - and read the description out of
        the third line of a report meant for a person.
        """

        if not self.available():
            return {}

        result, output = self._run(['changes', '-c', self.workspace, '-s', 'pending'], tagged=True)
        if not result:
            return {}

        changelists = {}
        number = ''
        description = []
        for line in output.splitlines():
            if line.startswith('... change '):
                number = line[len('... change '):].strip()
                description = []
            elif line.startswith('... desc '):
                description = [line[len('... desc '):]]
            elif line.startswith('... '):
                continue
            elif line.strip() and description:
                # A description over several lines continues without a field name.
                description.append(line)
            elif not line.strip() and number:
                changelists[number] = '\n'.join(description).strip()
                number, description = '', []

        if number:
            changelists[number] = '\n'.join(description).strip()

        return changelists

    def create_changelist(self, description):
        """
        A changelist with this description, reusing one that is already there.

        :param str description: What it is for.
        :return: Its number, or ``''``.
        :rtype: str

        The version this replaces piped ``p4 change -o`` into ``p4 change -i`` through the
        shell and read the second word of the first line it printed. Which works, and needs a
        shell, and says nothing when it does not. ``p4 --field`` does the same thing without
        one.
        """

        for number, existing in self.pending().items():
            if existing == description:
                return number

        # Ask p4 for a blank changelist form with the description already in it, then hand
        # that form back to p4 on standard input. The version this replaces did the same
        # thing by piping one p4 into another through a shell, which is where the quoting
        # problems come from.
        result, form = self._run([
            '--field', 'Description={0}'.format(description),
            '--field', 'Files=',
            'change', '-o'])
        if not result or not form:
            logger.warning('Could not read a changelist form: %s', form)
            return ''

        result, output = self._run(['change', '-i'], send=form + '\n')
        if not result:
            logger.warning('Could not create a changelist: %s', output)
            return ''

        # 'Change 12345 created.'
        for line in output.splitlines():
            parts = line.split()
            if len(parts) > 1 and parts[0] == 'Change':
                return parts[1]

        return ''
