"""
Reading a package's own docstrings, and writing them where a model can use them.

    python tests/test_docgen.py

No Maya and no network: the suite builds a module of its own and introspects that, which
exercises everything except the ``import pymel`` line.
"""

# python imports
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.tools import docgen  # noqa: E402
from mca.common.tools.docgen import introspect, write_docs  # noqa: E402


SPHINX = '''Move something about the scene.

A second paragraph, which is not part of the summary.

:param str name: the thing to move
:param float distance: how far to move it
:param on_axis: which way
:returns: nothing much
'''

GOOGLE = '''Rotate something.

Parameters:
    - name (str): the thing to rotate
    * degrees: how far round
    axis : str
        which way

Returns:
    Nothing.

Examples:
    pm.rotate('thing', 90)
    pm.rotate('thing', -90)
'''


def example_module():
    """
    :return: A module with a couple of functions in it, one of them borrowed from elsewhere.
    :rtype: module
    """

    module = types.ModuleType('pretend.core.general')

    def move(name, distance=1.0, on_axis='x'):
        """Move something about the scene.

        :param str name: the thing to move
        :param float distance: how far to move it
        """

    def _private(name):
        """Not for anybody else."""

    module.move = move
    module._private = _private
    module.NOT_A_FUNCTION = 12
    # Something the module re-exports rather than defines: json.dumps belongs to json.
    module.dumps = json.dumps
    for function in (move, _private):
        function.__module__ = 'pretend.core.general'

    return module


def body(suite):
    # ---------------------------------------------------------------- #
    # the parameter name, which every file got wrong
    # ---------------------------------------------------------------- #
    # ':param str path: where to save' was split on ':' and the second piece used as the name,
    # so every parameter in every file came out called 'param str path'.
    suite.check('a parameter with a type in front of it is named for the parameter',
                introspect.parameter_name('str path') == ('path', 'str'))
    suite.check('and one without a type is just itself',
                introspect.parameter_name('path') == ('path', ''))
    suite.check('and nothing at all is nothing',
                introspect.parameter_name('') == ('', '') and
                introspect.parameter_name(None) == ('', ''))

    summary, parameters, examples = introspect.parse_docstring(SPHINX)
    suite.check('the summary is the first paragraph, and stops there',
                summary == 'Move something about the scene.', summary)
    suite.check('every Sphinx parameter is keyed by its own name',
                sorted(parameters) == ['distance', 'name', 'on_axis'], str(sorted(parameters)))
    suite.check('with its type and its description kept apart',
                parameters['name'] == {'type': 'str', 'description': 'the thing to move'},
                str(parameters['name']))
    suite.check('a parameter with no type still has a description',
                parameters['on_axis']['description'] == 'which way' and
                parameters['on_axis']['type'] == '')
    suite.check('and a returns line is not mistaken for a parameter',
                'returns' not in parameters and 'nothing much' not in str(parameters))

    summary, parameters, examples = introspect.parse_docstring(GOOGLE)
    suite.check('a bulleted parameter list is read the right way round, name first',
                parameters.get('name', {}).get('description') == 'the thing to rotate' and
                parameters.get('name', {}).get('type') == 'str',
                str(parameters))
    suite.check('however the bullet is written',
                'degrees' in parameters and
                parameters['degrees']['description'] == 'how far round',
                str(parameters.get('degrees')))
    suite.check('and the numpy shape, where the type is after the colon and the description '
                'is indented underneath it',
                parameters.get('axis') == {'type': 'str', 'description': 'which way'},
                str(parameters.get('axis')))
    suite.check('the examples come across as code, both of them together',
                examples and 'pm.rotate' in examples[0] and 'Nothing.' not in examples[0],
                str(examples))

    suite.check('a docstring that is not there is not a summary saying so',
                introspect.parse_docstring('') == ('', {}, []) and
                introspect.parse_docstring(None) == ('', {}, []))
    long_summary = introspect.parse_docstring('word ' * 400)[0]
    suite.check('a very long summary is cut short rather than carried whole',
                len(long_summary) <= introspect.SUMMARY_LIMIT and long_summary.endswith('...'),
                str(len(long_summary)))

    # ---------------------------------------------------------------- #
    # which bucket a function goes in
    # ---------------------------------------------------------------- #
    suite.check('the module a function came from picks its category',
                introspect.categorise('move', 'pymel.core.animation', '') == 'animation' and
                introspect.categorise('move', 'pymel.core.windows', '') == 'ui')
    suite.check('and where the module says nothing, its name and summary do',
                introspect.categorise('skinCluster', 'pretend.thing', 'bind a joint') ==
                'rigging')
    suite.check('and failing that, everything is general',
                introspect.categorise('frobnicate', 'pretend.thing', 'does a thing') ==
                'general')

    # ---------------------------------------------------------------- #
    # reading a module
    # ---------------------------------------------------------------- #
    module = example_module()
    records = introspect.module_records(module, 'pretend.core.general', version='2025',
                                       own_prefix='pretend.core')
    names = sorted(record['command'] for record in records)
    suite.check('a module\'s public functions are read, and nothing else',
                names == ['move'], str(names))
    suite.check('a function the module only re-exports is left to the module that defines it',
                'dumps' not in names)
    record = records[0]
    suite.check('a record carries the signature as somebody would type it',
                record['syntax'].startswith('pm.move(') and 'distance' in record['syntax'],
                record['syntax'])
    suite.check('and the parameters read out of its docstring',
                sorted(record['parameters']) == ['distance', 'name'],
                str(sorted(record['parameters'])))
    suite.check('and says which version it was read for, and when',
                record['version'] == '2025' and record['read_at'] and record['documented'])

    without_filter = introspect.module_records(module, 'pretend.core.general')
    suite.check('with no filter, a re-export is read as well - which is the caller\'s choice '
                'now, rather than pymel.core being written into the middle of the function',
                'dumps' in [row['command'] for row in without_filter])

    class NoSignature(object):
        """Something callable that Python cannot read a signature from."""

        def __call__(self, *arguments):                              # pragma: no cover
            return None

    unreadable = introspect.function_record(len, 'len', 'builtins')
    suite.check('a function with no readable signature still gets a record',
                unreadable['syntax'].endswith('(...)') or '(' in unreadable['syntax'],
                unreadable['syntax'])

    suite.check('and with no PyMel about, reading it answers nothing rather than raising',
                introspect.pymel_records() == [])

    # ---------------------------------------------------------------- #
    # writing it out
    # ---------------------------------------------------------------- #
    text = write_docs.markdown(record)
    suite.check('the Markdown has a heading, the syntax and the parameters',
                text.startswith('# move') and '## Syntax' in text and '## Parameters' in text,
                text[:80])
    suite.check('a parameter reads as a name, a type and what it is for',
                '**distance** (`float`)' in text, text)
    bare = write_docs.markdown({'command': 'bare'})
    suite.check('and a function with nothing to say gets no empty sections',
                '## Parameters' not in bare and '## Examples' not in bare, bare)

    found = write_docs.keywords(record)
    suite.check('a function is searchable by its name and its category',
                'move' in found and record['category'] in found, str(found))
    suite.check('words too common to search for are left out, and there is a limit',
                'the' not in found and len(found) <= write_docs.KEYWORD_LIMIT, str(found))

    index = write_docs.build_index([record, {'command': 'aardvark', 'summary': 'first'}])
    suite.check('the index counts what is in it and is in order',
                index['count'] == 2 and
                [entry['name'] for entry in index['commands']] == ['aardvark', 'move'],
                str([entry['name'] for entry in index['commands']]))

    output = os.path.join(suite.temp, 'AIDocs')
    written = write_docs.write_all([record], output)
    suite.check('writing puts a JSON file and a Markdown file in their own folders',
                os.path.isfile(os.path.join(output, 'json', 'move.json')) and
                os.path.isfile(os.path.join(output, 'markdown', 'move.md')),
                str(written))
    # It used to read, scan and rewrite the whole index once per function.
    suite.check('and one index over all of them, written once at the end',
                written['index'] and os.path.isfile(written['index']) and
                json.loads(open(written['index'], encoding='utf-8').read())['count'] == 1)
    again = write_docs.write_all([record], output, skip_existing=True)
    suite.check('a run that was interrupted can carry on rather than starting again',
                again['skipped'] == 1 and again['written'] == 0, str(again))

    # ---------------------------------------------------------------- #
    # where it writes, which used to be somebody's depot
    # ---------------------------------------------------------------- #
    was = os.environ.pop(docgen.OUTPUT_VARIABLE, None)
    try:
        suite.check('with nowhere named, it says so rather than writing into a path that was '
                    'written into the code',
                    docgen.default_output_folder() == '' and
                    docgen.generate_pymel_docs()['ok'] is False and
                    docgen.OUTPUT_VARIABLE in docgen.generate_pymel_docs()['message'])
        os.environ[docgen.OUTPUT_VARIABLE] = output
        suite.check('and with one named, every version gets a folder of its own',
                    docgen.default_output_folder('2025').endswith(
                        os.path.join('Maya', 'pymel', '2025')),
                    docgen.default_output_folder('2025'))
        answer = docgen.generate_pymel_docs(version='2025')
        suite.check('with no PyMel to read, it answers a failure that says what is needed',
                    answer['ok'] is False and 'importable' in answer['message'],
                    answer['message'])
        suite.check('and the command line answers non-zero for it',
                    docgen.main(['--version', '2025']) == 1)
    finally:
        os.environ.pop(docgen.OUTPUT_VARIABLE, None)
        if was is not None:
            os.environ[docgen.OUTPUT_VARIABLE] = was

    suite.note('records written', written['written'])


if __name__ == '__main__':
    sys.exit(harness.run('docgen', body))
