"""
The Maya MCP server: open Maya, work in it, close it, with nothing else running.

Nine tools, and the first three are the ones that were missing::

    maya_status            which Mayas are running, and can they be reached
    maya_launch            start one, wait until it answers
    maya_quit              close one, with or without saving
    maya_execute           run Python in one and get back what it said
    maya_run_file          the same, from a file on disk
    maya_scene_info        what is open, and is it modified
    maya_open_scene        open a file
    maya_save_scene        save, optionally to a new path
    maya_new_scene         start a new one

Everything routes through ``mca.mcp.core.control``, so the command line, a test and this
server all do the same thing the same way.

Run it::

    python -m mca.mcp.maya.server

It speaks MCP over stdio, which is what an MCP client expects to spawn.
"""

# python imports
import argparse
import asyncio
import json
import logging
import os
import sys

# The package root, so this runs as a module or as a plain script.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# third party imports
import mcp.server.stdio
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

# mca imports
from mca import mcp as mca_mcp
from mca.mcp.core import control, link


logger = logging.getLogger('mca-mcp')

SERVER_NAME = 'MCAMaya'

#: Every tool, with the schema a client needs to call it. Written out rather than generated,
#: because the description is the only documentation the assistant on the other end gets -
#: and a vague one produces a tool call that does the wrong thing confidently.
TOOLS = [
    Tool(
        name='maya_status',
        description=(
            'List the Maya sessions running on this machine and whether each can be reached. '
            'Use this first when anything is unclear: it answers "is Maya even open", "which '
            'version", "what scene", and "can I talk to it". Reaching a Maya requires the '
            'pipeline bootstrap, which opens its command port; a Maya started outside the '
            'pipeline will not appear.'),
        inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False},
    ),
    Tool(
        name='maya_launch',
        description=(
            'Start Maya through the MCA launcher and wait until it can be talked to. The '
            'launcher installs that version\'s Python dependencies first if they are missing, '
            'so the first start of a version can take several minutes. Returns the process '
            'id. Use maya_status afterwards if you need the port.'),
        inputSchema={
            'type': 'object',
            'properties': {
                'version': {'type': 'string',
                            'description': 'Maya version, for example "2025". Omit for the '
                                           'launcher\'s remembered choice.'},
                'project': {'type': 'string',
                            'description': 'Project name. Omit for the current project.'},
                'wait': {'type': 'boolean', 'default': True,
                         'description': 'Wait for Maya to answer before returning.'},
            },
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_quit',
        description=(
            'Close a running Maya. Refuses when the scene has unsaved changes unless save or '
            'force is set - which is deliberate: an assistant should not throw away '
            'somebody\'s work on a guess.'),
        inputSchema={
            'type': 'object',
            'properties': {
                'pid': {'type': 'integer', 'description': 'Which Maya, by process id.'},
                'save': {'type': 'boolean', 'default': False,
                         'description': 'Save the scene first. Only works on a scene that '
                                        'already has a name.'},
                'force': {'type': 'boolean', 'default': False,
                          'description': 'Close even with unsaved changes.'},
            },
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_execute',
        description=(
            'Run Python inside a running Maya and return what it produced. The script runs on '
            'Maya\'s main thread, so maya.cmds works normally. Set a variable named "result" '
            'to choose what comes back; anything printed is returned as well. This is the '
            'general tool - prefer it for anything the specific tools do not cover.'),
        inputSchema={
            'type': 'object',
            'properties': {
                'script': {'type': 'string', 'description': 'The Python to run.'},
                'pid': {'type': 'integer',
                        'description': 'Which Maya, when more than one is running.'},
                'timeout': {'type': 'number', 'default': 120,
                            'description': 'Seconds to wait for an answer.'},
            },
            'required': ['script'],
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_run_file',
        description=(
            'Run a Python file from disk inside Maya. The file is read by Maya itself, so it '
            'can be any size - unlike maya_execute, which sends the source down a socket.'),
        inputSchema={
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Absolute path to a .py file.'},
                'pid': {'type': 'integer', 'description': 'Which Maya.'},
                'timeout': {'type': 'number', 'default': 300},
            },
            'required': ['path'],
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_scene_info',
        description='What scene a Maya has open, whether it has unsaved changes, and what is '
                    'in it by node type.',
        inputSchema={
            'type': 'object',
            'properties': {'pid': {'type': 'integer', 'description': 'Which Maya.'}},
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_open_scene',
        description=(
            'Open a scene file. Refuses when the current scene has unsaved changes unless '
            'force is set.'),
        inputSchema={
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Absolute path to a .ma or .mb.'},
                'force': {'type': 'boolean', 'default': False,
                          'description': 'Discard unsaved changes in the current scene.'},
                'pid': {'type': 'integer', 'description': 'Which Maya.'},
            },
            'required': ['path'],
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_save_scene',
        description='Save the open scene, optionally to a new path.',
        inputSchema={
            'type': 'object',
            'properties': {
                'path': {'type': 'string',
                         'description': 'Save here instead. Omit to save in place.'},
                'pid': {'type': 'integer', 'description': 'Which Maya.'},
            },
            'additionalProperties': False,
        },
    ),
    Tool(
        name='maya_new_scene',
        description=('Start a new scene. Refuses when the current one has unsaved changes '
                     'unless force is set.'),
        inputSchema={
            'type': 'object',
            'properties': {
                'force': {'type': 'boolean', 'default': False},
                'pid': {'type': 'integer', 'description': 'Which Maya.'},
            },
            'additionalProperties': False,
        },
    ),
]

server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools():
    """
    :return: Every tool this server offers.
    :rtype: list(Tool)
    """

    return TOOLS


@server.call_tool()
async def call_tool(name, arguments):
    """
    Run one tool and answer with text.

    Every failure comes back as a sentence rather than an exception, because the client on
    the other end is a language model: a traceback tells it that something broke, while
    "no running Maya was found - start one with maya_launch" tells it what to do next.

    :param str name: The tool.
    :param dict arguments: Its arguments.
    :return: The answer.
    :rtype: list(TextContent)
    """

    arguments = arguments or {}
    try:
        handler = HANDLERS[name]
    except KeyError:
        return _text('There is no tool called {}. This server offers: {}.'
                     .format(name, ', '.join(sorted(HANDLERS))))

    try:
        # Each handler blocks on sockets and on Maya. Off the event loop it goes, so a slow
        # scene open does not stall the whole server.
        answer = await asyncio.get_event_loop().run_in_executor(
            None, lambda: handler(arguments))
    except Exception as error:
        logger.exception('%s failed', name)
        return _text('{} failed: {}'.format(name, error))

    return _text(answer)


# ---------------------------------------------------------------------------- #
# The handlers
# ---------------------------------------------------------------------------- #
def _status(arguments):
    found = control.running()
    if not found:
        return ('No Maya is running, or none has the pipeline bootstrap loaded. Start one '
                'with maya_launch.')
    lines = ['{} Maya session(s):'.format(len(found))]
    for session in found:
        lines.append(
            '  Maya {} - pid {}, python port {}, {}, scene: {}'.format(
                session.get('version', '?'), session.get('pid'), session.get('python_port'),
                'reachable' if session.get('reachable') else 'NOT answering',
                os.path.basename(session.get('scene') or '') or 'untitled'))
    return '\n'.join(lines)


def _launch(arguments):
    answer = control.launch(version=arguments.get('version'),
                            project=arguments.get('project'),
                            wait=bool(arguments.get('wait', True)))
    return answer['message']


def _quit(arguments):
    answer = control.quit_maya(pid=arguments.get('pid'), save=bool(arguments.get('save')),
                               force=bool(arguments.get('force')))
    return answer['message']


def _execute(arguments):
    answer = control.execute(arguments['script'], pid=arguments.get('pid'),
                             timeout=float(arguments.get('timeout', 120)))
    return _render(answer)


def _run_file(arguments):
    path = arguments['path']
    script = ("import io, runpy\n"
              "result = runpy.run_path({!r}, run_name='__mca_mcp__').get('result')\n"
              .format(path))
    answer = control.execute(script, pid=arguments.get('pid'),
                             timeout=float(arguments.get('timeout', 300)))
    return _render(answer)


def _scene_info(arguments):
    script = (
        "import maya.cmds as cmds\n"
        "from collections import Counter\n"
        "counts = Counter(cmds.nodeType(node) for node in (cmds.ls(long=True) or []))\n"
        "result = {'scene': cmds.file(query=True, sceneName=True) or '',\n"
        "          'modified': bool(cmds.file(query=True, modified=True)),\n"
        "          'version': cmds.about(version=True),\n"
        "          'top_node_types': counts.most_common(12),\n"
        "          'meshes': len(cmds.ls(type='mesh') or []),\n"
        "          'joints': len(cmds.ls(type='joint') or [])}\n")
    return _render(control.execute(script, pid=arguments.get('pid'), timeout=60.0))


def _open_scene(arguments):
    script = (
        "import maya.cmds as cmds\n"
        "force = {force!r}\n"
        "if cmds.file(query=True, modified=True) and not force:\n"
        "    result = {{'refused': 'The open scene has unsaved changes. Save it, or call "
        "again with force.'}}\n"
        "else:\n"
        "    cmds.file({path!r}, open=True, force=True)\n"
        "    result = {{'opened': cmds.file(query=True, sceneName=True)}}\n"
    ).format(force=bool(arguments.get('force')), path=arguments['path'])
    return _render(control.execute(script, pid=arguments.get('pid'), timeout=600.0))


def _save_scene(arguments):
    path = arguments.get('path')
    if path:
        script = ("import maya.cmds as cmds\n"
                  "cmds.file(rename={path!r})\n"
                  "result = cmds.file(save=True, type='mayaAscii' if {path!r}.endswith('.ma') "
                  "else 'mayaBinary')\n").format(path=path)
    else:
        script = ("import maya.cmds as cmds\n"
                  "if not cmds.file(query=True, sceneName=True):\n"
                  "    result = {'refused': 'This scene has never been saved, so it has no "
                  "name. Pass a path.'}\n"
                  "else:\n"
                  "    result = cmds.file(save=True)\n")
    return _render(control.execute(script, pid=arguments.get('pid'), timeout=600.0))


def _new_scene(arguments):
    script = (
        "import maya.cmds as cmds\n"
        "force = {force!r}\n"
        "if cmds.file(query=True, modified=True) and not force:\n"
        "    result = {{'refused': 'The open scene has unsaved changes. Save it, or call "
        "again with force.'}}\n"
        "else:\n"
        "    cmds.file(new=True, force=True)\n"
        "    result = 'new scene'\n"
    ).format(force=bool(arguments.get('force')))
    return _render(control.execute(script, pid=arguments.get('pid'), timeout=120.0))


HANDLERS = {
    'maya_status': _status,
    'maya_launch': _launch,
    'maya_quit': _quit,
    'maya_execute': _execute,
    'maya_run_file': _run_file,
    'maya_scene_info': _scene_info,
    'maya_open_scene': _open_scene,
    'maya_save_scene': _save_scene,
    'maya_new_scene': _new_scene,
}


# ---------------------------------------------------------------------------- #
# Turning an answer into something worth reading
# ---------------------------------------------------------------------------- #
def _render(answer):
    """
    :param dict answer: What control.execute brought back.
    :return: The parts worth reading, in the order they matter.
    :rtype: str
    """

    if not answer.get('ok'):
        pieces = ['The script raised in Maya: {}'.format(answer.get('error') or 'no message')]
        if answer.get('traceback'):
            pieces.append(answer['traceback'].strip()[-1500:])
        if answer.get('output'):
            pieces.append('Printed before it failed:\n{}'.format(answer['output'].strip()))
        return '\n\n'.join(pieces)

    pieces = []
    result = answer.get('result')
    if result is not None:
        pieces.append(json.dumps(result, indent=2, default=str)
                      if isinstance(result, (dict, list)) else str(result))
    if answer.get('output'):
        pieces.append('Output:\n{}'.format(answer['output'].rstrip()))
    if not pieces:
        pieces.append('Done. The script set no result and printed nothing.')
    pieces.append('({:.2f}s in Maya {})'.format(answer.get('seconds', 0.0),
                                                answer.get('version') or '?'))
    return '\n\n'.join(pieces)


def _text(message):
    """
    :param str message: What to say.
    :return: It, as MCP content.
    :rtype: list(TextContent)
    """

    return [TextContent(type='text', text=str(message))]


# ---------------------------------------------------------------------------- #
# Running
# ---------------------------------------------------------------------------- #
def _setup_logging(level):
    """
    Log to a file, never to stdout.

    stdout **is** the MCP transport: one stray print corrupts the protocol and the client
    disconnects with an unhelpful parse error.

    :param str level: The level.
    """

    if os.name == 'nt':
        base = os.getenv('LOCALAPPDATA') or os.path.expanduser('~')
    else:
        base = os.path.expanduser('~')
    folder = os.path.join(base, 'MCA', 'logs')
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        handler = logging.FileHandler(os.path.join(folder, 'mca_maya_mcp.log'),
                                      encoding='utf-8')
    except Exception:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(logging.Formatter(
        '%(asctime)s  %(levelname)-7s  %(filename)s:%(lineno)d  %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False


async def run():
    """Serve MCP over stdio until the client goes away."""

    async with mcp.server.stdio.stdio_server() as (reader, writer):
        await server.run(
            reader, writer,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=mca_mcp.__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(), experimental_capabilities={}),
            ),
        )


def main(argv=None):
    """
    :param list(str) argv: Arguments, or None for sys.argv.
    :return: The exit code.
    :rtype: int
    """

    parser = argparse.ArgumentParser(prog='mca-maya-mcp',
                                     description='MCP server for driving Maya.')
    parser.add_argument('--port', type=int, default=None,
                        help='Maya MEL command port to assume (default 7001).')
    parser.add_argument('--log-level', default='INFO')
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)

    _setup_logging(arguments.log_level)
    if arguments.port:
        link.DEFAULT_MEL_PORT = arguments.port

    logger.info('%s %s starting', SERVER_NAME, mca_mcp.__version__)
    asyncio.run(run())
    return 0


if __name__ == '__main__':
    sys.exit(main())
