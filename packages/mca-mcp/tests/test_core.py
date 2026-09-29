"""
The MCP layer, checked with no Maya, no MCP client and no network.

Run it with any Python 3.9 or newer::

    python tests/test_core.py

What is checked here is everything that can be wrong without a DCC: the program that gets
sent to Maya, the session bookkeeping, and the rules about which Maya a call is about - the
last being the one that decides whether an assistant edits the right scene.
"""

# python imports
import base64
import json
import os
import shutil
import sys
import tempfile
import traceback


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CHECKS = []
FAILURES = []


def check(label, condition, detail=''):
    CHECKS.append(label)
    passed = bool(condition)
    if not passed:
        FAILURES.append('{}  |  {}'.format(label, detail))
    print('{}  {}'.format('ok  ' if passed else 'FAIL', label))
    if not passed and detail:
        print('      {}'.format(detail))
    return passed


def raises(label, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except Exception as error:
        check(label, True)
        return str(error)
    check(label, False, 'it did not raise')
    return ''


def main():
    temp = tempfile.mkdtemp(prefix='mca-mcp-')
    os.environ['MCA_SESSIONS_ROOT'] = os.path.join(temp, 'sessions')

    from mca.mcp.core import control, link, sessions

    # ------------------------------------------------------------------ #
    # The program that gets sent to Maya
    # ------------------------------------------------------------------ #
    script = "import maya.cmds as cmds\nresult = cmds.ls('pCube*')\nprint('hello')\n"
    program = link._wrapper(script, 'C:/Temp/result.json')

    check('the program compiles', _compiles(program))
    check('and is ONE line, because Maya\'s command port executes what it receives line by '
          'line - a multi-line program arrives as fragments and simply never answers',
          len(program.strip().splitlines()) == 1, repr(program[:120]))
    check('the single line is an exec of something encoded, not source in the clear',
          program.startswith("exec(__import__('base64')"), program[:60])
    import re

    inner = base64.b64decode(
        re.search(r"b64decode\('([^']+)'\)", program).group(1)).decode('utf-8')
    check('what Maya will actually run is a valid program too', _compiles(inner))
    check('the script travels base64-encoded, so quotes and backslashes cannot be mangled',
          base64.b64encode(script.encode('utf-8')).decode('ascii') in inner)
    check('the script itself is nowhere in the clear',
          "cmds.ls('pCube*')" not in program and "cmds.ls('pCube*')" not in inner)
    check('the work is deferred onto Maya\'s main thread', 'executeDeferred' in inner)
    check('the result path is embedded',
          'C:/Temp/result.json' in inner and '__RESULT_PATH__' not in inner)

    nasty = 'result = "quotes \\" and \'single\' and {braces} and \\\\ backslash"\n'
    check('a script full of quotes and braces still produces a valid program',
          _compiles(link._wrapper(nasty, 'C:/x.json')))

    check('the python port is always one above the MEL port',
          link.python_port(7001) == 7002 and link.python_port(50000) == 50001)

    # Nothing is listening on a port nobody opened.
    check('an unused port reads as not listening', not link.is_listening(59321))
    message = raises('and waiting for one gives up with a sentence, not a hang',
                     link.wait_until_listening, 59321, 1.0)
    check('which says what might be wrong',
          'bootstrap' in message or 'starting' in message, message)
    message = raises('executing against a dead port refuses',
                     link.execute, 'result = 1', 59321)
    check('and names both the port and what to do about it',
          '59321' in message and 'launcher' in message, message)

    # ------------------------------------------------------------------ #
    # Sessions
    # ------------------------------------------------------------------ #
    check('the sessions folder honours MCA_SESSIONS_ROOT',
          sessions.sessions_folder() == os.path.normpath(os.environ['MCA_SESSIONS_ROOT']))
    check('with nothing running, there are no sessions', sessions.live_sessions() == [])

    mine = {'pid': os.getpid(), 'version': '2025', 'mel_port': 7001, 'python_port': 7002,
            'scene': r'C:\Temp\teapot.ma', 'started': '2026-09-29 01:00:00'}
    path = sessions.write(mine)
    check('a session file is written', os.path.isfile(path))
    check('and reads back', sessions.read(path)['version'] == '2025')
    check('this process counts as alive', sessions.is_alive(os.getpid()))
    check('and a process id that cannot exist does not', not sessions.is_alive(999999999))

    live = sessions.live_sessions()
    check('a live session is listed', len(live) == 1 and live[0]['pid'] == os.getpid())

    dead = dict(mine)
    dead['pid'] = 999999998
    sessions.write(dead)
    check('a session whose process is gone is not listed',
          [one['pid'] for one in sessions.live_sessions()] == [os.getpid()])
    check('and its file is cleaned up on the way past',
          not os.path.isfile(sessions.session_file(999999998)))

    # ------------------------------------------------------------------ #
    # Which Maya a call is about
    # ------------------------------------------------------------------ #
    real_listening = link.is_listening

    link.is_listening = lambda port, host=link.HOST, timeout=0.4: True
    session = control.pick()
    check('with one reachable Maya, it is picked without being asked',
          session['pid'] == os.getpid(), str(session))

    second = dict(mine)
    second['pid'] = os.getpid() + 0    # a second live one: use this process twice is not
    # possible, so write a session for the parent process instead, which is also alive.
    second['pid'] = os.getppid()
    second['python_port'] = 7012
    if sessions.is_alive(os.getppid()) and os.getppid() != os.getpid():
        sessions.write(second)
        message = raises('with two running, it refuses to guess', control.pick)
        check('and names them both so the caller can choose',
              str(os.getpid()) in message and str(os.getppid()) in message, message)
        check('while asking for one by pid still works',
              control.pick(pid=os.getpid())['pid'] == os.getpid())
        message = raises('and an unknown pid is refused by name', control.pick, 424242)
        check('with the running ones listed', '424242' in message, message)
        sessions.forget(os.getppid())

    link.is_listening = lambda port, host=link.HOST, timeout=0.4: False
    sessions.forget(os.getpid())
    message = raises('with nothing running at all, it says so', control.pick)
    check('and tells the caller how to fix it',
          'maya_launch' in message and 'bootstrap' in message, message)

    link.is_listening = real_listening

    # ------------------------------------------------------------------ #
    # Launching without the launcher installed
    # ------------------------------------------------------------------ #
    import builtins

    real_import = builtins.__import__

    def no_launcher(name, *args, **kwargs):
        if name.startswith('mca.launcher'):
            raise ImportError('no module named mca.launcher')
        return real_import(name, *args, **kwargs)

    builtins.__import__ = no_launcher
    try:
        message = raises('launching without the launcher package refuses', control.launch)
        check('and says which package is missing',
              'mca-launcher' in message, message)
    finally:
        builtins.__import__ = real_import

    # ------------------------------------------------------------------ #
    # The bootstrap, outside Maya
    # ------------------------------------------------------------------ #
    from mca.mcp.maya import bootstrap

    os.environ['MCA_MAYA_COMMAND_PORTS'] = '1'
    answer = bootstrap.start()
    check('the bootstrap refuses politely when it is not inside Maya',
          not answer['ok'] and 'not Maya' in answer['message'], answer['message'])
    os.environ.pop('MCA_MAYA_COMMAND_PORTS')

    os.environ.pop('MCA_MAYA_COMMAND_PORTS', None)
    check('the ports stay shut unless something asks for them', not bootstrap.enabled())
    answer = bootstrap.start()
    check('and a Maya nobody asked about is left alone, with a reason given',
          not answer['ok'] and 'not set' in answer['message'], answer['message'])
    os.environ['MCA_MAYA_COMMAND_PORTS'] = '1'
    check('the launcher asking for them turns them on', bootstrap.enabled())
    os.environ['MCA_MAYA_COMMAND_PORTS'] = '0'
    check('and an explicit off is still off', not bootstrap.enabled())
    os.environ.pop('MCA_MAYA_COMMAND_PORTS')

    os.environ['MCA_MAYA_MEL_PORT'] = '7100'
    check('the port can be moved by environment', bootstrap.mel_port() == 7100)
    os.environ['MCA_MAYA_MEL_PORT'] = 'nonsense'
    check('and nonsense falls back to the default rather than raising',
          bootstrap.mel_port() == bootstrap.DEFAULT_MEL_PORT)
    os.environ.pop('MCA_MAYA_MEL_PORT')

    shutil.rmtree(temp, ignore_errors=True)


def _compiles(source):
    try:
        compile(source, '<generated>', 'exec')
        return True
    except SyntaxError:
        return False


if __name__ == '__main__':
    error = None
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        print(error)
    passed = len(CHECKS) - len(FAILURES)
    print('')
    print('mcp core: {}/{} passed'.format(passed, len(CHECKS)))
    for failure in FAILURES:
        print('  FAILED  {}'.format(failure))
    sys.exit(1 if (FAILURES or error) else 0)
