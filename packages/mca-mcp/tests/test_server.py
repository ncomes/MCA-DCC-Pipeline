"""
The MCP layer, against whichever ``mcp`` SDK is installed here.

This suite exists because of a failure that cost an evening: the server was written against
the 1.x decorator API, met 2.2.0 on a real machine, and died on
``AttributeError: 'Server' object has no attribute 'list_tools'`` - once per reconnection
attempt, in a log that never mentioned a version. Nothing about the tool list or the dispatch
needs a client on the other end of stdio, so all of it is checkable here.

    python tests/test_server.py

Skips cleanly where ``mcp`` is not installed, which is the state of every DCC interpreter.
"""

# python imports
import asyncio
import os
import sys
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


def main():
    try:
        import mcp  # noqa: F401
    except ImportError as error:
        print('SKIPPED: mcp is not installed for this interpreter ({}).'.format(error))
        return

    from mca.mcp.core import mcp_compat
    from mca.mcp.maya import server

    print('mcp {}, {} API'.format(mcp_compat.sdk_version(),
                                  'decorator (1.x)' if mcp_compat.DECORATOR_API
                                  else 'constructor (2.x)'))
    print('')

    # ---------------------------------------------------------------- #
    # The tool table
    # ---------------------------------------------------------------- #
    names = [one['name'] for one in server.TOOLS]
    check('every tool has a name, a description and a schema',
          all(one.get('name') and one.get('description') and one.get('schema') is not None
              for one in server.TOOLS), str(names))
    check('the names are unique', len(names) == len(set(names)), str(names))
    check('every tool has a handler',
          set(names) == set(server.HANDLERS), str(set(names) ^ set(server.HANDLERS)))
    check('the three that did not exist before are there',
          {'maya_status', 'maya_launch', 'maya_quit'} <= set(names), str(names))

    for one in server.TOOLS:
        schema = one['schema']
        if not check('{} has an object schema'.format(one['name']),
                     schema.get('type') == 'object', str(schema)):
            continue
        for argument, definition in (schema.get('properties') or {}).items():
            check('  {}.{} says what it is for'.format(one['name'], argument),
                  bool(definition.get('description')) or argument in ('force', 'wait'),
                  str(definition))

    # ---------------------------------------------------------------- #
    # The SDK accepts them
    # ---------------------------------------------------------------- #
    built = [mcp_compat.make_tool(one['name'], one['description'], one['schema'])
             for one in server.TOOLS]
    check('the installed SDK accepts every tool', len(built) == len(server.TOOLS))
    check('and keeps the schema on them',
          all(getattr(tool, 'inputSchema', None) or getattr(tool, 'input_schema', None)
              for tool in built))

    # ---------------------------------------------------------------- #
    # Dispatch, without a transport
    # ---------------------------------------------------------------- #
    list_tools, call_tool = mcp_compat.handlers_for_testing(server.TOOLS, server.dispatch)

    listed = asyncio.new_event_loop().run_until_complete(list_tools())
    check('listing the tools works through the shim', len(listed) == len(server.TOOLS))

    loop = asyncio.new_event_loop()

    answer = loop.run_until_complete(call_tool('maya_status'))
    check('maya_status answers with a sentence rather than raising',
          isinstance(answer, str) and answer, repr(answer)[:200])
    check('and with no Maya running it says so and what to do',
          'No Maya is running' in answer and 'maya_launch' in answer, answer[:200])

    answer = loop.run_until_complete(call_tool('maya_nonsense'))
    check('an unknown tool name is answered, not raised',
          'no tool called' in answer, answer[:200])
    check('and the answer lists what there is',
          'maya_status' in answer and 'maya_execute' in answer, answer[:200])

    # A handler that explodes must still come back as a sentence.
    real = server.HANDLERS['maya_status']
    def angry(arguments):
        raise RuntimeError('the cage is inside out')
    server.HANDLERS['maya_status'] = angry
    try:
        answer = loop.run_until_complete(call_tool('maya_status'))
        check('a handler that raises is reported, not propagated',
              'maya_status failed' in answer and 'inside out' in answer, answer[:200])
    finally:
        server.HANDLERS['maya_status'] = real

    # Executing against no Maya: the message has to name the fix, since that is all the
    # caller has to go on.
    answer = loop.run_until_complete(call_tool('maya_execute', {'script': 'result = 1'}))
    check('executing with no Maya running explains itself',
          'maya_launch' in answer or 'bootstrap' in answer, answer[:300])

    loop.close()


if __name__ == '__main__':
    error = None
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        print(error)
    print('')
    print('mcp server: {}/{} passed'.format(len(CHECKS) - len(FAILURES), len(CHECKS)))
    for failure in FAILURES:
        print('  FAILED  {}'.format(failure))
    sys.exit(1 if (FAILURES or error) else 0)
