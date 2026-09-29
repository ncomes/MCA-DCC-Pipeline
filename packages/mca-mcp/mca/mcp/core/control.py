"""
Starting Maya, stopping Maya, and knowing which ones are running.

The outside half of "do whatever to Maya". Starting one goes through the launcher's API,
because that is where the knowledge already lives - which versions are installed, which
project, what environment, and whether that version's Python dependencies are in place. A
second implementation here would be a second thing to keep right.

The launcher is an optional import on purpose: without it everything else still works
against a Maya that is already running, and the message says what to install.
"""

# python imports
import logging
import os
import time

# mca imports
from mca.mcp.core import link, sessions


logger = logging.getLogger('mca-mcp')

#: How long to wait for a starting Maya to answer its port. A cold start with a big
#: userSetup is slow, and the failure people report is "it timed out", not "it hung".
START_TIMEOUT = 240.0

#: How long to wait for a Maya to actually exit after being asked.
QUIT_TIMEOUT = 60.0


def running():
    """
    :return: The Mayas that are running and reachable, newest first.
    :rtype: list(dict)
    """

    found = []
    for session in sessions.live_sessions():
        session = dict(session)
        session['reachable'] = link.is_listening(session.get('python_port')
                                                 or link.python_port())
        found.append(session)
    return found


def pick(pid=None, port=None):
    """
    Work out which Maya a call is about.

    :param int pid: A specific process id.
    :param int port: A specific Python command port.
    :return: The session, or a bare dict naming the port when no session file exists - a
        Maya somebody started by hand with the ports open is still perfectly usable.
    :rtype: dict
    :raises RuntimeError: When there is nothing to talk to.
    """

    live = running()

    if pid:
        for session in live:
            if int(session.get('pid', 0)) == int(pid):
                return session
        raise RuntimeError('No running Maya has process id {}. Running: {}.'
                           .format(pid, _describe(live) or 'none'))

    if port:
        return {'python_port': int(port), 'pid': None, 'version': '',
                'reachable': link.is_listening(int(port))}

    reachable = [one for one in live if one.get('reachable')]
    if len(reachable) == 1:
        return reachable[0]
    if len(reachable) > 1:
        # More than one is ambiguous, and quietly picking the newest is how the wrong scene
        # gets edited. Name them and make the caller choose.
        raise RuntimeError('There are {} Mayas running ({}). Say which one with pid or port.'
                           .format(len(reachable), _describe(reachable)))

    # Nothing announced itself - but a Maya may still be sitting on the default port.
    default = link.python_port()
    if link.is_listening(default):
        return {'python_port': default, 'pid': None, 'version': '', 'reachable': True}

    raise RuntimeError(
        'No running Maya was found. Start one with maya_launch, or if Maya is already open, '
        'it was started without the pipeline bootstrap - run '
        '"from mca.mcp.maya import bootstrap; bootstrap.start()" in its script editor.')


def execute(script, pid=None, port=None, timeout=link.DEFAULT_TIMEOUT):
    """
    Run Python in a Maya.

    :param str script: The Python to run.
    :param int pid: Which Maya, by process id.
    :param int port: Which Maya, by Python command port.
    :param float timeout: How long to wait.
    :return: The result, plus which Maya answered.
    :rtype: dict
    """

    session = pick(pid=pid, port=port)
    answer = link.execute(script, port=session.get('python_port'), timeout=timeout)
    answer['pid'] = session.get('pid')
    answer['version'] = session.get('version', '')
    return answer


def launch(version=None, project=None, wait=True, timeout=START_TIMEOUT):
    """
    Start Maya through the launcher, and wait until it can be talked to.

    :param str version: Maya version. None uses the launcher's remembered choice.
    :param str project: Project name. None uses the current one.
    :param bool wait: Wait for the command port before answering.
    :param float timeout: How long to wait for it.
    :return: What happened, including the pid and how long it took.
    :rtype: dict
    :raises RuntimeError: When the launcher is not installed, or refused.
    """

    try:
        from mca.launcher import api as launcher_api
    except ImportError as error:
        raise RuntimeError(
            'Starting Maya needs the mca-launcher package, which is not importable here ({}). '
            'Install it, or put its folder on PYTHONPATH. Everything else works against a '
            'Maya that is already running.'.format(error))

    before = {int(one['pid']) for one in running() if one.get('pid')}

    started = launcher_api.launch('maya', version, project=project)
    if not started['ok']:
        # The launcher refuses for good reasons - dependencies not installed, project not
        # set up - and its message already says which. Pass it straight through.
        raise RuntimeError(started['message'])

    answer = {'ok': True, 'launcher': started['result'], 'message': started['message'],
              'pid': started['result'].get('pid'), 'waited': 0.0, 'reachable': False}

    if not wait:
        return answer

    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        for session in running():
            if session.get('pid') in before:
                continue
            if session.get('reachable'):
                answer['session'] = session
                answer['pid'] = session.get('pid')
                answer['reachable'] = True
                answer['waited'] = round(time.time() - (deadline - float(timeout)), 1)
                answer['message'] = ('Maya {} is up and answering on port {} after {:.0f}s. {}'
                                     .format(session.get('version', ''),
                                             session.get('python_port'), answer['waited'],
                                             started['message']))
                return answer
        time.sleep(1.0)

    answer['ok'] = False
    answer['message'] = (
        'Maya was started, but nothing answered its command port within {:.0f} seconds. It '
        'may still be loading, or it may have started without the pipeline bootstrap. {}'
        .format(timeout, started['message']))
    return answer


def quit_maya(pid=None, port=None, save=False, force=False, timeout=QUIT_TIMEOUT):
    """
    Ask a Maya to close.

    :param int pid: Which Maya.
    :param int port: Which Maya, by port.
    :param bool save: Save the open scene first. Only when it has a name - "save" on an
        untitled scene means a file dialog nobody is there to answer.
    :param bool force: Quit even with unsaved changes. Without it, a modified scene refuses
        and says so, which is the behaviour anybody would want from an assistant.
    :param float timeout: How long to wait for the process to go.
    :return: What happened.
    :rtype: dict
    :raises RuntimeError: When there are unsaved changes and neither save nor force was asked
        for.
    """

    session = pick(pid=pid, port=port)

    state = link.execute(
        "import maya.cmds as cmds\n"
        "result = {'modified': bool(cmds.file(query=True, modified=True)),\n"
        "          'scene': cmds.file(query=True, sceneName=True) or ''}\n",
        port=session.get('python_port'), timeout=30.0)
    if not state.get('ok'):
        raise RuntimeError('Could not ask Maya about its scene: {}'
                           .format(state.get('error') or 'no answer'))

    modified = bool(state['result'].get('modified'))
    scene = state['result'].get('scene') or ''

    if modified and not (save or force):
        raise RuntimeError(
            'That Maya has unsaved changes{}. Pass save=true to save first, or force=true to '
            'throw them away.'.format(' in ' + os.path.basename(scene) if scene else
                                      ' in an untitled scene'))

    if save:
        if not scene:
            raise RuntimeError('That scene has never been saved, so there is nowhere to save '
                               'it. Save it by name first, or pass force=true to close '
                               'without saving.')
        saved = link.execute("import maya.cmds as cmds\nresult = cmds.file(save=True)\n",
                             port=session.get('python_port'), timeout=300.0)
        if not saved.get('ok'):
            raise RuntimeError('Maya would not save {}: {}'
                               .format(scene, saved.get('error') or 'no answer'))

    # The quit is sent and not waited on: Maya stops answering as it goes, so a reply would
    # be a reply from a process on its way out.
    try:
        link.execute("import maya.cmds as cmds\nfrom mca.mcp.maya import bootstrap\n"
                     "bootstrap.stop()\ncmds.quit(force=True)\n",
                     port=session.get('python_port'), timeout=5.0)
    except link.MayaTimedOut:
        pass
    except link.MayaNotRunning:
        pass

    pid = session.get('pid')
    waited = 0.0
    if pid:
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if not sessions.is_alive(pid):
                sessions.forget(pid)
                waited = round(float(timeout) - (deadline - time.time()), 1)
                return {'ok': True, 'pid': pid, 'saved': bool(save), 'waited': waited,
                        'message': 'Maya {} closed{}.'.format(pid,
                                                              ' after saving' if save else '')}
            time.sleep(0.5)
        return {'ok': False, 'pid': pid, 'saved': bool(save), 'waited': float(timeout),
                'message': 'Maya {} was asked to close but is still running after {:.0f} '
                           'seconds. It may be showing a dialog.'.format(pid, timeout)}

    return {'ok': True, 'pid': None, 'saved': bool(save), 'waited': waited,
            'message': 'Maya was asked to close.'}


def _describe(found):
    """
    :param list(dict) found: Sessions.
    :return: A short readable list of them.
    :rtype: str
    """

    return ', '.join('{} (pid {}, port {})'.format(one.get('version', 'Maya'), one.get('pid'),
                                                   one.get('python_port'))
                     for one in found)
