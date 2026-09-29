"""
The whole chain, against a real Maya, with no MCP client and no editor running.

    python tests/test_live.py            the launcher's remembered version
    python tests/test_live.py 2025

What it does, in order: find or start Maya, run Python in it, read the scene, make something,
save to a temp file, open it again, and close Maya. If every line of this passes, an
assistant can do the same through MCP - the tools are thin wrappers over exactly these calls.

It leaves the machine as it found it: a Maya it started is closed again, and one that was
already running is used and left alone.
"""

# python imports
import os
import sys
import tempfile
import time
import traceback


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(os.path.dirname(ROOT), 'mca-launcher')):
    if path not in sys.path:
        sys.path.insert(0, path)

CHECKS = []
FAILURES = []


def check(label, condition, detail=''):
    CHECKS.append(label)
    if not condition:
        FAILURES.append('{}  |  {}'.format(label, detail))
    print('{}  {}'.format('ok  ' if condition else 'FAIL', label))
    if not condition and detail:
        print('      {}'.format(detail))
    return bool(condition)


def main(version=None):
    print('Python:     {}'.format(sys.executable))
    print('Version:    {}'.format(sys.version.split()[0]))
    for module, why in (('yaml', 'reading the launcher\'s preferences'),
                        ('mca.mcp.core.link', 'talking to Maya'),
                        ('mca.launcher.api', 'starting Maya')):
        try:
            __import__(module)
            print('  has {:<22} ({})'.format(module, why))
        except Exception as error:
            print('  MISSING {:<19} ({}) - {}'.format(module, why, error))
    print('')

    from mca.mcp.core import control, link

    started_by_us = None

    running = control.running()
    print('Maya sessions already running: {}'.format(
        [(one.get('version'), one.get('pid')) for one in running] or 'none'))

    if not running:
        print('Starting Maya{}... this can take a couple of minutes on a cold start.'
              .format(' ' + version if version else ''))
        began = time.time()
        answer = control.launch(version=version)
        if not check('Maya starts and answers its command port', answer['ok'],
                     answer['message']):
            return
        started_by_us = answer.get('pid')
        print('   up in {:.0f}s: {}'.format(time.time() - began, answer['message']))
    else:
        check('a Maya is already running and reachable',
              any(one.get('reachable') for one in running), str(running))

    # --- the general tool, which is the one that matters ---------------- #
    answer = control.execute("import maya.cmds as cmds\n"
                             "result = cmds.about(version=True)\n")
    check('python runs inside Maya and the result comes back',
          answer.get('ok') and answer.get('result'), str(answer)[:300])
    print('   Maya says it is version {}'.format(answer.get('result')))

    answer = control.execute("print('printed from Maya')\nresult = 6 * 7\n")
    check('printed output comes back too',
          answer.get('ok') and 'printed from Maya' in (answer.get('output') or ''),
          str(answer)[:300])
    check('and the result is the value, not a string of it', answer.get('result') == 42,
          repr(answer.get('result')))

    answer = control.execute("result = 1 / 0\n")
    check('a script that raises comes back as a failure with its traceback',
          not answer.get('ok') and 'ZeroDivisionError' in (answer.get('error') or ''),
          str(answer)[:300])
    check('and the failure does not kill the connection',
          control.execute("result = 'still here'\n").get('result') == 'still here')

    # --- something that needs the main thread --------------------------- #
    answer = control.execute(
        "import maya.cmds as cmds\n"
        "cmds.file(new=True, force=True)\n"
        "cube = cmds.polyCube(name='mcp_test_cube')[0]\n"
        "cmds.setAttr(cube + '.translateY', 3)\n"
        "result = {'cube': cube, 'y': cmds.getAttr(cube + '.translateY')}\n")
    check('maya.cmds works, which means the work ran on Maya\'s main thread',
          answer.get('ok') and answer['result']['y'] == 3.0, str(answer)[:300])

    # --- scene round trip ------------------------------------------------ #
    scene = os.path.join(tempfile.gettempdir(), 'mca_mcp_live_test.ma').replace('\\', '/')
    answer = control.execute(
        "import maya.cmds as cmds\n"
        "cmds.file(rename={!r})\n"
        "result = cmds.file(save=True, type='mayaAscii')\n".format(scene))
    check('the scene saves', answer.get('ok') and os.path.isfile(scene), str(answer)[:300])

    answer = control.execute(
        "import maya.cmds as cmds\n"
        "cmds.file(new=True, force=True)\n"
        "cmds.file({!r}, open=True, force=True)\n"
        "result = cmds.ls('mcp_test_cube')\n".format(scene))
    check('and opens again with what was in it',
          answer.get('ok') and answer.get('result'), str(answer)[:300])

    control.execute("import maya.cmds as cmds\ncmds.file(new=True, force=True)\n")
    try:
        os.remove(scene.replace('/', os.sep))
    except OSError:
        pass

    # --- who is running --------------------------------------------------- #
    sessions = control.running()
    check('the session is listed with its version and port',
          sessions and sessions[0].get('python_port'), str(sessions))

    # --- closing ---------------------------------------------------------- #
    if started_by_us:
        answer = control.quit_maya(pid=started_by_us)
        check('the Maya we started closes again', answer['ok'], answer['message'])
        check('and stops being listed',
              started_by_us not in [one.get('pid') for one in control.running()])
    else:
        print('Leaving the Maya that was already open alone.')


if __name__ == '__main__':
    error = None
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception:
        error = traceback.format_exc()
        print(error)
    print('')
    print('live: {}/{} passed'.format(len(CHECKS) - len(FAILURES), len(CHECKS)))
    for failure in FAILURES:
        print('  FAILED  {}'.format(failure))
    sys.exit(1 if (FAILURES or error) else 0)
