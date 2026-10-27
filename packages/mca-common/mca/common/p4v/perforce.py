"""
Module that contains functions for interacting with p4v.
"""

# mca python imports
import os
import subprocess
try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - non-Windows environments
    winreg = None
# software specific imports
# Project python imports
from mca.common import log
from mca.common.startup.configs import consts
from mca.common.modifiers import singleton

logger = log.MCA_LOGGER

#: Seconds any single p4 command may take before it is abandoned.
#:
#: Every call in this module used to run with no timeout at all, so an unreachable
#: server did not fail - it blocked, on whatever thread asked. Maya's start-up calls
#: in here (start_menus.set_p4_combobox, since removed), which is why a p4 outage froze the launch
#: rather than costing the Perforce menu.
P4_TIMEOUT = int(os.getenv('MCA_P4_TIMEOUT', '15'))

#: Seconds the one "is the server there" check may take. Short on purpose: it is paid
#: before the first real command and its whole job is to fail fast.
P4_PROBE_TIMEOUT = int(os.getenv('MCA_P4_PROBE_TIMEOUT', '5'))

#: None until asked, then True/False for the rest of the session. Without this every
#: one of the dozen commands below would pay the timeout separately.
_SERVER_REACHABLE = None


def _run(command, timeout=None):
    """
    Run a p4 command, and give up rather than hang.

    :param str command: The command line.
    :param int timeout: Seconds to allow. Defaults to :data:`P4_TIMEOUT`.
    :return: ``(ok, output)`` - ok is False on a timeout or a failure to start, and
        output is '' in that case. Never raises.
    :rtype: tuple(bool, str)
    """

    # shell=False matters as much as the timeout. Through cmd.exe, p4 is a grandchild
    # that inherits the pipe: the timeout kills the shell, then the read blocks until
    # the orphaned p4 finally exits, so a 5s timeout still cost 21s. Without a shell,
    # p4 is the child and killing it ends the call. Windows parses the command line
    # itself, so the quoting these commands use is unchanged.
    try:
        done = subprocess.run(command, shell=False, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              timeout=timeout or P4_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning('Perforce did not answer within %ss, so this was abandoned: %s',
                       timeout or P4_TIMEOUT, command)
        global _SERVER_REACHABLE
        _SERVER_REACHABLE = False
        return False, ''
    except Exception as error:
        logger.warning('Perforce could not be run (%s): %s', error, command)
        return False, ''

    output = (done.stdout or b'').decode('utf-8', errors='replace')
    return done.returncode == 0, output


def _run_lines(command, timeout=None):
    """
    :param str command: The command line.
    :param int timeout: Seconds to allow.
    :return: The output split into lines, or [] when the command did not answer.
    :rtype: list(str)
    """

    _, output = _run(command, timeout=timeout)
    return output.splitlines()


def _run_input(command, text, timeout=None):
    """
    Run a p4 command that reads a spec on stdin.

    Replaces a shell pipe, which could not be timed out: see :func:`_run`.

    :param str command: The command line.
    :param str text: What to feed it on stdin.
    :param int timeout: Seconds to allow.
    :return: Output lines, or [] when it did not answer.
    :rtype: list(str)
    """

    try:
        done = subprocess.run(command, shell=False, input=text.encode('utf-8'),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout or P4_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning('Perforce did not answer within %ss, so this was abandoned: %s',
                       timeout or P4_TIMEOUT, command)
        return []
    except Exception as error:
        logger.warning('Perforce could not be run (%s): %s', error, command)
        return []

    return (done.stdout or b'').decode('utf-8', errors='replace').splitlines()


def server_available(force=False):
    """
    Whether the Perforce server answers, asked once and remembered.

    :param bool force: Ask again rather than using the remembered answer.
    :return: True when p4 answered.
    :rtype: bool
    """

    global _SERVER_REACHABLE
    if _SERVER_REACHABLE is not None and not force:
        return _SERVER_REACHABLE

    ok, _ = _run('p4 info', timeout=P4_PROBE_TIMEOUT)
    _SERVER_REACHABLE = ok
    if not ok:
        logger.info('Perforce is not answering, so source control is off for this '
                    'session. Everything else carries on; call '
                    'perforce.server_available(force=True) to look again.')
    return ok


class P4Info(singleton.SimpleSingleton):
    """
    Singleton class that handles the user/workspace/port information of a given user. Singleton usage reduces the time
    To get this information on each p4 op. Which are slow to begin with.
    """
    
    user = None
    workspace = None
    port = None
    all_workspaces = []
    
    def __init__(self):
        if not winreg:  # pragma: no cover - non-Windows fallback
            logger.debug('Perforce registry access unavailable on this platform.')
            return
        key_val = r'SOFTWARE\Perforce\Environment'
        sub_key_list = [['P4CLIENT', 'workspace'], ['P4USER', 'user'], ['P4PORT', 'port']]
        try:
            key = winreg.OpenKey(winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER), key_val)
            for sub_key, dict_key in sub_key_list:
                try:
                    found_data = [x for x in winreg.QueryValueEx(key, sub_key)][0].split(', ')
                    if not found_data:
                        found_data = [x for x in winreg.QueryValueEx(key, sub_key.lower())][0].split(', ')
                    if found_data:
                        setattr(self, dict_key, found_data[0])
                except:
                    logger.error(f'CRITICAL ERROR: Open and close your Connection >> '
                                 f'Environment Settings in p4, ensure "Use current connection for environment '
                                 f'settings" is checked. Unable to find registry key. {sub_key}')
                    return
        except:
            logger.debug(f'CRITICAL ERROR: Install perforce, primary registry key is missing.')
            return
        
        self.workspace_data = []
        self.get_workspace_data()
        self.get_workspace()
        self.get_workspace_names()
        
    def get_workspace_data(self):
        """
        Looks through the p4 workspaces and finds the art depot.
        If it finds the depot, it sets the p4 workspace variable.
        """
        
        if not server_available():
            self.workspace_data = []
            return self.workspace_data

        # Get the p4 workspace info
        wk_cmd = f'p4 clients -u {self.user}'
        _, output = _run(wk_cmd)

        # Split the data into chunks
        self.workspace_data = output.split('\r')
        return self.workspace_data
        
    def get_workspace(self):
        """
        Returns get the workspace name.

        :return: Returns a list of workspace names.
        :rtype: list(str)
        """
        
        # Split the data into more chunks and extract the workspace name and root directory
        workspace_new_list = []
        for ws in self.workspace_data:
            ws_list = ws.split()
            if not ws_list:
                continue
            workspace_new_list.append({ws_list[1]: ws_list[4]})
        
        # Find the python .config file.  This file lives in the art root directory.
        # If we find it, then set the workspace to that workspace name.
        for ws_dicts in workspace_new_list:
            for workspace, root in ws_dicts.items():
                path = os.path.join(root, consts.MCA_PROJECT_CONFIG_NAME)
                path = os.path.normpath(path)
                if os.path.exists(path):
                    self.workspace = workspace
                    break
        
    def get_workspace_names(self):
        """
        Returns a list of workspace names.
        
        :return: Returns a list of workspace names.
        :rtype: list(str)
        """
        
        # Split the data into more chunks and extract the workspace name
        if not self.workspace_data:
            return []
        for ws in self.workspace_data:
            ws_list = ws.split()
            if not ws_list:
                continue
            self.all_workspaces.append(ws_list[1])
        return self.all_workspaces
        
        
def get_workspace_names():
    """
    Returns a list of all p4 workspace names.
    
    :return: Returns a list of all p4 workspace names.
    :rtype: str
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}
    if not server_available():
        return []

    # Get the p4 workspace info
    wk_cmd = f'p4 clients -u {p4_info.user}'
    _, output = _run(wk_cmd)

    # Split the data into chunks
    workspace_new_list = []
    workspace_list = output.split('\r')
    
    # Split the data into more chunks and extract the workspace name
    if not workspace_list:
        return []
    for ws in workspace_list:
        ws_list = ws.split()
        if not ws_list:
            continue
        workspace_new_list.append(ws_list[1])
    return workspace_new_list


def p4_describe_cl(cl_val):
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}

    if not server_available():
        return {}

    p4_cmd = f'P4 describe {cl_val}'
    _, cl_info = _run(p4_cmd)
    
    replace_str_list = [' ...', '... ', '\t']
    for replace_str in replace_str_list:
        cl_info = cl_info.replace(replace_str, '')
    cl_info = [x for x in cl_info.split('\r\n') if x]
    info_dict = {}
    try:
        info_dict['changelist'] = cl_info[0].split(' ')[1]
        info_dict['description'] = cl_info[1]
        info_dict['files'] = [x.split('#')[0] for x in cl_info[3:]]
    except:
        pass
    return info_dict


def p4_get_pending():
    """
    Grab a dictionary of all local pending changelists.

    :return: A dictionary containing all pending changelists.
    :rtype: dict
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}

    if not server_available():
        return {}

    cl_info_dict = {}
    p4_cmd = f'P4 -p {p4_info.port} changes -c {p4_info.workspace} -s pending'
    for entry_str in _run_lines(p4_cmd):
        if not entry_str.strip():
            continue
        cl_number = entry_str.split(' ')[1]
        info_dict = p4_describe_cl(cl_number)
        cl_info_dict[cl_number] = info_dict.get('description')
    return cl_info_dict


def p4_add(file_path, cl_val=None):
    """
    Adds a file to a given changelist as an add.

    :param str cl_val: Unique int value as a string which represents a changelist.
    :param str file_path: The absolute path to a given file.
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return
    
    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} add -c {cl_val} {file_path}'
    if not cl_val:
        p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} add {file_path}'
    _run(p4_cmd)


def p4_delete(file_path, cl_val=None):
    """
    Adds a file to a given changelist as a delete.

    :param str cl_val: Unique int value as a string which represents a changelist.
    :param str file_path: The absolute path to a given file.
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return

    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} delete -c {cl_val} {file_path}'
    if not cl_val:
        p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} delete {file_path}'
    _run(p4_cmd)


def p4_edit(file_path, cl_val=None):
    """
    Adds a file to a given changelist as an edit.

    :param str cl_val: Unique int value as a string which represents a changelist.
    :param str file_path: The absolute path to a given file.
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return
    
    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} edit -c {cl_val} {file_path}'
    if not cl_val:
        p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} edit {file_path}'
    _run(p4_cmd)


def p4_reopen(file_path, cl_val=None):
    """
    Moves a checked out file from one changelist to another.

    :param str cl_val: Unique int value as a string which represents a changelist.
    :param str file_path: The absolute path to a given file.
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}
    
    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} reopen -c {cl_val} {file_path}'
    if not cl_val:
        p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} reopen {file_path}'
    _run(p4_cmd)


def p4_reconcile(file_path, cl_val=None):
    """
    Correctly checks out a file using the appropriate operation to a given changelist.

    :param str cl_val: Unique int value as a string which represents a changelist.
    :param str file_path: The absolute path to a given file.
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}
    
    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} reconcile -c {cl_val} {file_path}'
    if not cl_val:
        p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} reconcile {file_path}'

    _run(p4_cmd)


def p4_revert(file_path, safe=True):
    """
    Reverts a file if it is checked out.

    :param str file_path: The absolute path to a given file.
    :param bool safe: If only safe reverts should be performed. Will only revert unchanged files.
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}

    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} revert -k {"-a " if safe else ""}{file_path}'
    _run(p4_cmd)


def p4_sync(file_path, force=False):
    """
    Correctly checks out a file using the appropriate operation to a given changelist.

    :param str file_path: The absolute path to a given file.
    :param bool force: If the file should be forcefully sunk. (revert, force to head)
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}

    if force:
        # If we're forcing this revert the file before syncing.
        p4_revert(file_path, safe=False)

    p4_cmd = f'P4 -p {p4_info.port} -c {p4_info.workspace} sync {"-f " if force else ""}{file_path}'
    _run(p4_cmd)


def p4_create_cl(cl_discript='pysc: New Pending Changelist'):
    """
    Create a new changelist or find an existing changelist with the same description.

    :param str cl_discript: The description of the new changelist.
    :return: The CL number of the found or newly created changelist.
    :rtype: str
    """
    
    p4_info = P4Info()
    if not p4_info or not server_available():
        return {}

    for cl_num, description in p4_get_pending().items():
        if cl_discript == description:
            return cl_num

    spec_cmd = (f'p4 -p {p4_info.port} -c {p4_info.workspace} '
                f'--field "Description={cl_discript}" --field "Files=" change -o')
    ok, spec = _run(spec_cmd)
    if not ok or not spec.strip():
        logger.error('Perforce did not answer when asking for a changelist spec.')
        return None

    lines = _run_input('p4 change -i', spec)
    if not lines:
        logger.error('Perforce did not answer when creating a changelist.')
        return None
    return lines[0].split(' ')[1]


def checkout(file_path_list, cl_val=None, sync=False, force=True):
    """
    Using p4 reconcile preform the correct operation on a given file and add it to the passed CL.
    Easy onestop shop to handle all p4 commands on a list of files.

    NOTES: You need to edit a file for this to trigger an add or edit. It will not mark a file if it is unchanged.

    :param str cl_val: Unique int value as a string which represents a changelist.
    :param list(str) file_path_list: A list of the absolute path to a given file.
    :param bool sync: If True, perforce will attempt to sync to the latest on the file list.
    :param bool force: If files should be moved to the specified changelist even if already checked out on a different one.
    """
    
    if not isinstance(file_path_list, list):
        file_path_list = [file_path_list]
    
    if sync:
        sync_files(file_path_list, force=force)
    
    for file_path in file_path_list:
        p4_reconcile(file_path, cl_val=cl_val)
        if force:
            p4_reopen(file_path, cl_val=cl_val)


def p4_submit(file_path_list, description='pysc: auto-submit'):
    """
    Submit the given files to Perforce under a new changelist with the
    supplied description.  The files are reconciled, moved into a fresh
    pending CL, and the CL is submitted in one shot.

    :param list(str) file_path_list: Absolute paths to the files to submit.
    :param str description: Changelist description for the submit.
    :return: True on a successful submit, False otherwise.
    :rtype: bool
    """

    p4_info = P4Info()
    if not p4_info or not p4_info.workspace or not server_available():
        logger.warning('No Perforce workspace available; skipping submit.')
        return False

    if not isinstance(file_path_list, list):
        file_path_list = [file_path_list]

    # Filter to existing files — p4 submit on a path that is not in the
    # depot / workspace fails the whole CL, so drop them up front.
    file_path_list = [p for p in file_path_list if p and os.path.exists(p)]
    if not file_path_list:
        logger.warning('p4_submit called with no valid files.')
        return False

    # Dedicated CL per submit keeps unrelated default-CL work out of it.
    cl_val = p4_create_cl(cl_discript=description)
    if not cl_val:
        logger.error('Could not create or find a pending changelist for submit.')
        return False
    cl_val = str(cl_val).strip()

    # Reconcile (add/edit/delete as appropriate) and move into our CL.
    # These must run synchronously — the module-level p4_reconcile/p4_reopen
    # helpers use fire-and-forget Popen calls, which race the submit below
    # and produce "No files to submit." Run them inline and wait, so the CL is
    # fully populated before we submit.
    for file_path in file_path_list:
        reconcile_cmd = (f'P4 -p {p4_info.port} -c {p4_info.workspace} '
                         f'reconcile -c {cl_val} {file_path}')
        _run(reconcile_cmd)
        reopen_cmd = (f'P4 -p {p4_info.port} -c {p4_info.workspace} '
                      f'reopen -c {cl_val} {file_path}')
        _run(reopen_cmd)

    submit_cmd = (f'P4 -p {p4_info.port} -c {p4_info.workspace} '
                  f'submit -c {cl_val}')
    try:
        ok, out_text = _run(submit_cmd)
        if not ok:
            logger.error(
                f'p4 submit failed (cl {cl_val}): {out_text.strip()}')
            return False
        logger.info(f'Submitted CL {cl_val}: {description}')
        if out_text.strip():
            logger.debug(out_text.strip())
        return True
    except Exception as err:
        logger.exception(f'p4 submit raised an exception: {err}')
        return False


def sync_files(file_path_list, force=False):
    """
    Sync the list of files to the head revision, optionally forcibly doing so.

    :param list(str) file_path_list: A list of absolute paths to be sunk.
    :param bool force: Forcibly revert and sync the files to the head revision.
    """
    
    if not isinstance(file_path_list, list):
        file_path_list = [file_path_list]

    for file_path in file_path_list:
        p4_sync(file_path, force)
