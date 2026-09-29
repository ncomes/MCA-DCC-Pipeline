"""
Speaking to whichever version of the ``mcp`` SDK is installed.

The SDK changed shape at 2.0, and an MCP server does not get to choose which version the
machine it lands on has:

- **1.x** registers handlers with decorators - ``@server.list_tools()`` and
  ``@server.call_tool()`` - and the handlers return a plain list.
- **2.x** takes the handlers as constructor arguments - ``on_list_tools`` and
  ``on_call_tool`` - and they return ``ListToolsResult`` and ``CallToolResult``. ``FastMCP``
  was renamed to ``MCPServer`` in the same release.

Written against 1.x, this server met 2.2.0 on a real machine and died on
``AttributeError: 'Server' object has no attribute 'list_tools'`` - once per reconnection
attempt, in a log that never named the version. So the version handling lives here, in one
module, tested against what is installed, and the server above it describes its tools as
plain data and knows nothing about either API.

The detection is by feature rather than by version string, because that is the thing that
actually matters and it cannot be wrong about a fork or a pre-release.
"""

# python imports
import logging


logger = logging.getLogger('mca-mcp')

# third party imports
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

#: True for the 1.x decorator API, False for the 2.x constructor API.
DECORATOR_API = hasattr(Server, 'list_tools')


def sdk_version():
    """
    :return: The installed SDK version, or 'unknown'.
    :rtype: str
    """

    try:
        import importlib.metadata

        return importlib.metadata.version('mcp')
    except Exception:
        return 'unknown'


def make_tool(name, description, schema):
    """
    Build a Tool the installed SDK accepts.

    1.x names the field ``inputSchema``; 2.x renamed it to ``input_schema`` and keeps the old
    name as an alias. Both are tried rather than assumed.

    :param str name: The tool name.
    :param str description: What it does, in the words the calling model will read.
    :param dict schema: Its JSON schema.
    :return: The tool.
    """

    for field in ('inputSchema', 'input_schema'):
        try:
            return Tool(name=name, description=description, **{field: schema})
        except Exception as error:
            last = error
    raise RuntimeError('Neither inputSchema nor input_schema was accepted by mcp {}: {}'
                       .format(sdk_version(), last))


async def serve(name, version, specs, dispatch):
    """
    Serve MCP over stdio, whichever SDK is installed.

    :param str name: The server name.
    :param str version: Its version.
    :param list(dict) specs: One ``{'name', 'description', 'schema'}`` per tool.
    :param dispatch: ``async dispatch(tool_name, arguments) -> str``.
    """

    tools = [make_tool(one['name'], one['description'], one['schema']) for one in specs]
    logger.info('mcp SDK %s, %s API, %d tool(s)', sdk_version(),
                'decorator' if DECORATOR_API else 'constructor', len(tools))

    if DECORATOR_API:
        await _serve_v1(name, version, tools, dispatch)
    else:
        await _serve_v2(name, version, tools, dispatch)


async def _serve_v1(name, version, tools, dispatch):
    """The 1.x path: decorators, and handlers that return plain values."""

    from mcp.server.models import InitializationOptions

    server = Server(name)

    @server.list_tools()
    async def _list_tools():
        return tools

    @server.call_tool()
    async def _call_tool(tool_name, arguments):
        return [TextContent(type='text', text=await dispatch(tool_name, arguments or {}))]

    options = InitializationOptions(
        server_name=name,
        server_version=version,
        capabilities=server.get_capabilities(notification_options=NotificationOptions(),
                                             experimental_capabilities={}),
    )
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, options)


async def _serve_v2(name, version, tools, dispatch):
    """The 2.x path: handlers on the constructor, and results wrapped in result types."""

    from mcp.types import CallToolResult, ListToolsResult

    async def on_list_tools(context, params):
        return ListToolsResult(tools=tools)

    async def on_call_tool(context, params):
        text = await dispatch(params.name, params.arguments or {})
        return CallToolResult(content=[TextContent(type='text', text=text)])

    server = Server(name, version=version, on_list_tools=on_list_tools,
                    on_call_tool=on_call_tool)
    options = server.create_initialization_options()
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, options)


def handlers_for_testing(specs, dispatch):
    """
    The two handlers, without a transport, so a test can call them.

    Serving needs a client on the other end of stdio; the handlers do not. This is what makes
    the tool list and the dispatch checkable on any machine, under whichever SDK it has.

    :param list(dict) specs: The tool specs.
    :param dispatch: ``async dispatch(name, arguments) -> str``.
    :return: ``(list_tools, call_tool)`` - both awaitable, both taking no transport.
    :rtype: tuple
    """

    tools = [make_tool(one['name'], one['description'], one['schema']) for one in specs]

    async def list_tools():
        return tools

    async def call_tool(tool_name, arguments=None):
        return await dispatch(tool_name, arguments or {})

    return list_tools, call_tool
