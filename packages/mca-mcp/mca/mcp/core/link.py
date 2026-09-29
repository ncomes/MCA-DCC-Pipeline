"""
Talking to a running Maya over its Python command port.

The transport is the one the previous server proved out, kept because it earned it:

- **base64 in, file out.** The script is base64-encoded before it goes down the socket, so
  quotes, newlines and backslashes in the code cannot be mangled on the way. The *result*
  comes back through a temp file rather than the socket, because what a command port returns
  is whatever happened to be printed, interleaved with anything else Maya said.
- **Deferred by default.** ``maya.utils.executeDeferred`` puts the work on Maya's main
  thread. Maya 2024's command port crashes when ``maya.cmds`` runs inside the socket
  handler; deferring is not a workaround for one version so much as the only correct way to
  touch a DCC from another thread.
- **Two-phase read.** Wait up to a few seconds for Maya to start answering, then treat a
  short silence as the end. A single timeout either gives up on a slow scene open or adds a
  fixed delay to every call.

Nothing here imports Maya. This is the outside half.
"""

# python imports
import base64
import json
import logging
import os
import socket
import tempfile
import time


logger = logging.getLogger('mca-mcp')

#: Maya's MEL command port. The Python port is always this plus one.
DEFAULT_MEL_PORT = 7001

#: Only ever localhost. A command port is an unauthenticated remote code execution service;
#: it has no business on a network interface.
HOST = '127.0.0.1'

#: Seconds to wait for the socket itself.
CONNECT_TIMEOUT = 5.0

#: Seconds to wait for a result file before giving up.
DEFAULT_TIMEOUT = 120.0

#: How often to look for the result file.
POLL_INTERVAL = 0.05


class MayaNotRunning(RuntimeError):
    """Raised when there is nothing listening on the port."""


class MayaTimedOut(RuntimeError):
    """Raised when Maya took the work but never wrote a result."""


def python_port(mel_port=DEFAULT_MEL_PORT):
    """
    :param int mel_port: Maya's MEL command port.
    :return: The matching Python port.
    :rtype: int
    """

    return int(mel_port) + 1


def is_listening(port, host=HOST, timeout=0.4):
    """
    Is anything accepting connections on a port.

    :param int port: The port.
    :param str host: The host.
    :param float timeout: How long to wait.
    :return: Whether the port answered.
    :rtype: bool
    """

    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect((host, int(port)))
        return True
    except (socket.timeout, OSError):
        return False
    finally:
        connection.close()


def wait_until_listening(port, timeout=180.0, host=HOST):
    """
    Wait for a port to start answering - for instance while Maya starts up.

    :param int port: The port.
    :param float timeout: How long to wait in total.
    :param str host: The host.
    :return: How long it took, in seconds.
    :rtype: float
    :raises MayaTimedOut: When it never answered.
    """

    started = time.time()
    while time.time() - started < timeout:
        if is_listening(port, host=host):
            return time.time() - started
        time.sleep(0.5)
    raise MayaTimedOut('Nothing answered on port {} within {:.0f} seconds. Maya may still be '
                       'starting, or the pipeline bootstrap did not run in it.'
                       .format(port, timeout))


def _result_paths():
    """
    :return: (path for us, the same path written the way Maya's Python wants it)
    :rtype: tuple(str, str)
    """

    folder = os.path.join(tempfile.gettempdir(), 'mca_mcp_results')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    name = 'result_{}.json'.format('{:.6f}'.format(time.time()).replace('.', '_'))
    path = os.path.join(folder, name)
    return path, path.replace('\\', '/')


def _wrapper(script, result_path):
    """
    Build the little program Maya actually runs.

    It defers the real work onto the main thread, runs the caller's script in a namespace of
    its own, and writes either its value or its traceback to a file. The caller's script can
    set ``result`` to say what it wants to hand back; if it does not, whatever the last
    expression evaluated to is used, and failing that, anything it printed.

    :param str script: The caller's Python.
    :param str result_path: Where to write the answer, Maya-style slashes.
    :return: The program to send.
    :rtype: str
    """

    encoded = base64.b64encode(script.encode('utf-8')).decode('ascii')
    # Written as a template with two markers rather than a format string: the program is
    # mostly dict literals, and every brace in it would otherwise need escaping - which is
    # exactly the class of quoting bug this transport exists to avoid.
    return (_PROGRAM
            .replace('__ENCODED__', encoded)
            .replace('__RESULT_PATH__', result_path))


#: The program sent down the socket. Runs the caller's script on Maya's main thread and
#: writes one JSON file with everything worth knowing about how it went.
_PROGRAM = """import base64, json, io, traceback, contextlib
import maya.utils


def _mca_run():
    payload = {'ok': False, 'result': None, 'output': '', 'error': '', 'traceback': ''}
    namespace = {'__name__': '__mca_mcp__'}
    printed = io.StringIO()
    try:
        source = base64.b64decode('__ENCODED__').decode('utf-8')
        with contextlib.redirect_stdout(printed):
            exec(compile(source, '<mca-mcp>', 'exec'), namespace)
        value = namespace.get('result', None)
        payload['ok'] = True
        try:
            json.dumps(value)
            payload['result'] = value
        except (TypeError, ValueError):
            payload['result'] = repr(value)
    except Exception as error:
        payload['error'] = type(error).__name__ + ': ' + str(error)
        payload['traceback'] = traceback.format_exc()
    payload['output'] = printed.getvalue()
    try:
        with open('__RESULT_PATH__', 'w') as handle:
            json.dump(payload, handle, default=str)
    except Exception:
        pass


maya.utils.executeDeferred(_mca_run)
"""


def execute(script, port=None, timeout=DEFAULT_TIMEOUT, host=HOST):
    """
    Run Python inside a running Maya and bring back what it said.

    :param str script: The Python to run. Set ``result`` in it to choose what comes back.
    :param int port: Maya's **Python** command port. Defaults to 7002.
    :param float timeout: How long to wait for an answer.
    :param str host: The host.
    :return: ``{'ok', 'result', 'output', 'error', 'traceback', 'seconds'}``
    :rtype: dict
    :raises MayaNotRunning: When nothing is listening.
    :raises MayaTimedOut: When Maya never wrote a result.
    """

    port = python_port() if port is None else int(port)
    result_path, maya_path = _result_paths()
    program = _wrapper(script, maya_path)

    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(CONNECT_TIMEOUT)
    try:
        connection.connect((host, port))
    except (socket.timeout, OSError) as error:
        connection.close()
        raise MayaNotRunning(
            'Nothing is listening on {}:{} - so either Maya is not running, or it is running '
            'without the pipeline bootstrap that opens its command port. Start Maya through '
            'the launcher, or run mca.mcp.maya.bootstrap.start() in it. ({})'
            .format(host, port, error))

    started = time.time()
    try:
        connection.sendall(program.encode('utf-8') + b'\n')
    finally:
        connection.close()

    deadline = started + float(timeout)
    while time.time() < deadline:
        if os.path.isfile(result_path):
            try:
                with open(result_path, 'r', encoding='utf-8') as handle:
                    payload = json.load(handle)
            except (ValueError, OSError):
                # Still being written. Worth a retry rather than a failure.
                time.sleep(POLL_INTERVAL)
                continue
            try:
                os.remove(result_path)
            except OSError:
                pass
            payload['seconds'] = round(time.time() - started, 3)
            return payload
        time.sleep(POLL_INTERVAL)

    raise MayaTimedOut(
        'Maya took the work but had not answered after {:.0f} seconds. It may be busy, or '
        'showing a dialog that is waiting for somebody. Nothing was cancelled - the script '
        'is still running in Maya.'.format(timeout))
