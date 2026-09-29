"""
The half that runs **inside** Maya. Import it there; never anywhere else.

It does two things, once, at Maya start-up:

1. opens Maya's MEL and Python command ports, and
2. writes a session file saying which Maya this is and how to reach it.

Why it exists at all: these ports used to be opened by the MCA Editor's Maya plug-in. That
made an AI assistant's reach depend on whether a *code editor* happened to be loaded -
close the editor and every tool that drives Maya goes blind, mid-session, with no
explanation. Opening the ports belongs to the pipeline, which is loaded in every Maya the
launcher starts.

To load it, one line in the pipeline's Maya ``userSetup.py``::

    from mca.mcp.maya import bootstrap; bootstrap.start()

It is safe to call more than once, safe when the ports are already open, and it never
raises: a Maya that will not start because its command port is busy would be a bad trade for
a convenience.

**What this opens.** A command port is unauthenticated remote code execution, so it binds to
localhost only, and ``MCA_MAYA_COMMAND_PORTS=0`` turns the whole thing off for anyone who
would rather it were not there.
"""

# python imports
import logging
import os
import sys


logger = logging.getLogger('mca-mcp')

#: Default MEL port. The Python port is always this plus one.
DEFAULT_MEL_PORT = 7001

#: Set to '0', 'false' or 'off' to keep the ports shut.
ENABLE_VARIABLE = 'MCA_MAYA_COMMAND_PORTS'

#: Overrides the MEL port.
PORT_VARIABLE = 'MCA_MAYA_MEL_PORT'

#: Set once the ports are open, so a second call is a no-op rather than a second attempt.
_state = {'started': False, 'mel_port': None, 'python_port': None, 'session_file': None}


def enabled():
    """
    :return: Whether the ports should be opened at all.
    :rtype: bool
    """

    value = str(os.getenv(ENABLE_VARIABLE, '1')).strip().lower()
    return value not in ('0', 'false', 'off', 'no')


def mel_port():
    """
    :return: The MEL port to open.
    :rtype: int
    """

    try:
        return int(os.getenv(PORT_VARIABLE, DEFAULT_MEL_PORT))
    except (TypeError, ValueError):
        logger.warning('%s is not a number; using %s.', PORT_VARIABLE, DEFAULT_MEL_PORT)
        return DEFAULT_MEL_PORT


def start(port=None, write_session=True):
    """
    Open the command ports and announce this Maya. Safe to call twice.

    :param int port: The MEL port. Defaults to the environment, then 7001.
    :param bool write_session: Also write the session file.
    :return: What happened: ``{'ok', 'mel_port', 'python_port', 'session_file', 'message'}``
    :rtype: dict
    """

    if _state['started']:
        return _answer(True, 'The command ports were already open on this Maya.')

    if not enabled():
        return _answer(False, '{} is set to off, so the command ports were not opened.'
                              .format(ENABLE_VARIABLE))

    try:
        import maya.cmds as cmds
        import maya.utils
    except ImportError:
        return _answer(False, 'This is not Maya - mca.mcp.maya.bootstrap only runs inside it.')

    chosen = mel_port() if port is None else int(port)

    def _open():
        """Open both ports. Deferred, because start-up is not a safe place to bind."""

        opened = []
        for number, source in ((chosen, 'mel'), (chosen + 1, 'python')):
            name = ':{}'.format(number)
            try:
                if cmds.commandPort(name, query=True):
                    opened.append(number)
                    logger.info('Command port %s was already open.', name)
                    continue
            except Exception:
                # Querying a port that has never existed raises on some versions; that is
                # simply "not open".
                pass
            try:
                cmds.commandPort(name=name, sourceType=source, echoOutput=False)
                opened.append(number)
                logger.info('Opened %s command port %s.', source, name)
            except RuntimeError as error:
                # Almost always "port already in use" - another Maya has it. Worth saying
                # once, clearly, rather than failing the whole start-up.
                logger.warning('Could not open %s command port %s: %s', source, name, error)

        _state['started'] = bool(opened)
        _state['mel_port'] = chosen if chosen in opened else None
        _state['python_port'] = chosen + 1 if (chosen + 1) in opened else None

        if write_session and _state['python_port']:
            try:
                _state['session_file'] = write_session_file(chosen)
            except Exception as error:
                logger.warning('Could not write the session file: %s', error)

    maya.utils.executeDeferred(_open)
    return _answer(True, 'Opening command ports {} and {} as Maya finishes starting.'
                         .format(chosen, chosen + 1))


def write_session_file(port=None):
    """
    Say which Maya this is, and how to reach it.

    :param int port: The MEL port this Maya answers on.
    :return: The file written.
    :rtype: str
    """

    from mca.mcp.core import sessions

    import maya.cmds as cmds

    chosen = mel_port() if port is None else int(port)
    session = {
        'pid': os.getpid(),
        'version': cmds.about(version=True),
        'mel_port': chosen,
        'python_port': chosen + 1,
        'scene': cmds.file(query=True, sceneName=True) or '',
        'project': os.getenv('MCA_PROJECT_NAME', ''),
        'batch': bool(cmds.about(batch=True)),
        'started': _started_at(),
        'executable': sys.executable,
    }
    path = sessions.write(session)
    logger.info('Wrote %s', path)
    return path


def refresh():
    """
    Update this Maya's session file - after opening a scene, say.

    :return: The file written, or '' when there is nothing to update.
    :rtype: str
    """

    if not _state['started']:
        return ''
    try:
        return write_session_file(_state['mel_port'])
    except Exception as error:
        logger.warning('Could not refresh the session file: %s', error)
        return ''


def stop():
    """
    Close the ports and forget this session. Called on the way out.

    :return: What happened.
    :rtype: dict
    """

    from mca.mcp.core import sessions

    try:
        import maya.cmds as cmds
    except ImportError:
        return _answer(False, 'This is not Maya.')

    for number in (_state['mel_port'], _state['python_port']):
        if not number:
            continue
        try:
            if cmds.commandPort(':{}'.format(number), query=True):
                cmds.commandPort(name=':{}'.format(number), close=True)
                logger.info('Closed command port %s.', number)
        except Exception as error:
            logger.warning('Could not close command port %s: %s', number, error)

    sessions.forget(os.getpid())
    _state.update({'started': False, 'mel_port': None, 'python_port': None,
                   'session_file': None})
    return _answer(True, 'Command ports closed.')


def status():
    """
    :return: What this Maya thinks its state is.
    :rtype: dict
    """

    return dict(_state)


def _answer(ok, message):
    """
    :param bool ok: Did it work.
    :param str message: A sentence for a person.
    :return: The state plus the verdict.
    :rtype: dict
    """

    answer = dict(_state)
    answer['ok'] = bool(ok)
    answer['message'] = message
    logger.info(message)
    return answer


def _started_at():
    """
    :return: When this Maya announced itself, for ordering a list of running ones. It is for
        reading, not for arithmetic.
    :rtype: str
    """

    import time

    return time.strftime('%Y-%m-%d %H:%M:%S')
