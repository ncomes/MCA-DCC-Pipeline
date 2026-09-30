"""
Reading a package's documentation out of the package itself.

Point it at an installed PyMel - or anything else - and it walks the modules, reads each
function's signature and docstring, and hands back one record per function. No network, and no
Maya: the package has to be importable, and that is all.

The docstring parser is the part that mattered and the part that was wrong. The version this
replaces took a Sphinx line like ``:param str path: where to save`` and split it on ``:``,
then used the *second* piece as the parameter's name - so every parameter came out called
``param str path`` rather than ``path``. For a bullet line like ``- path: where to save`` it
used the second piece as the name as well, which there is the *description*, so the name and
the description swapped places. The whole point of these files is to give a language model
accurate parameter names.
"""

# python imports
import datetime
import inspect
import re
import sys

# MCA python imports
from mca.common import log


logger = log.MCA_LOGGER

#: The submodules of ``pymel.core`` worth reading. Anything else it re-exports comes from one
#: of these.
PYMEL_SUBMODULES = ('animation', 'effects', 'general', 'language', 'modeling', 'other',
                    'rendering', 'system', 'windows')

#: How long a summary may be before it is cut short.
SUMMARY_LIMIT = 500

#: Which category a module's functions belong to, by what its name contains. First match wins,
#: so the order is the order they are tried in.
MODULE_CATEGORIES = (
    ('animation', 'animation'),
    ('modeling', 'modeling'),
    ('rendering', 'rendering'),
    ('effects', 'effects'),
    ('general', 'general'),
    ('system', 'system'),
    ('windows', 'ui'),
    ('language', 'scripting'),
)

#: And when the module name says nothing, by what the function's name and summary contain.
KEYWORD_CATEGORIES = (
    (('joint', 'skin', 'weight', 'rig'), 'rigging'),
    (('mesh', 'poly', 'vertex', 'edge'), 'modeling'),
    (('anim', 'key', 'constraint'), 'animation'),
    (('select', 'list', 'find', 'query'), 'selection'),
)

#: A docstring line naming a parameter, in either of the two styles the docstrings use:
#: ``:param str path: what it is`` and ``:parameter path: what it is``.
SPHINX_PARAM = re.compile(r'^:param(?:eter)?\s+(?P<body>[^:]+):\s*(?P<description>.*)$')

#: A bullet line naming one: ``- path (str): what it is``, ``* path: what it is``.
BULLET_PARAM = re.compile(r'^[-*]\s+(?P<name>[A-Za-z_][A-Za-z_0-9]*)\s*'
                          r'(?:\((?P<type>[^)]*)\))?\s*:\s*(?P<description>.*)$')

#: Section headings that start the parameters, and ones that end them.
PARAMETER_HEADINGS = ('parameters:', 'args:', 'arguments:', 'keyword arguments:')
OTHER_HEADINGS = ('returns:', 'return:', 'yields:', 'raises:', 'examples:', 'example:',
                  'notes:', 'note:', 'see also:', 'attributes:')


def parameter_name(body):
    """
    The parameter's own name, out of the part of a Sphinx line before the colon.

    ``str path`` is a type and a name; ``path`` is just a name. The name is the last word
    either way.

    :param str body: What stood between ``:param`` and the second colon.
    :return: ``(name, type)``, either of which may be ``''``.
    :rtype: (str, str)
    """

    words = str(body or '').split()
    if not words:
        return '', ''
    if len(words) == 1:
        return words[0], ''

    return words[-1], ' '.join(words[:-1])


def _indented_block(lines, start, indent):
    """
    The lines below a parameter that are indented further than it is, as one piece of text.

    :param list[str] lines: Every line of the docstring.
    :param int start: The line to start looking at.
    :param int indent: How far the parameter's own line was indented.
    :return: The text, or ``''`` when the next line is not indented further.
    :rtype: str
    """

    collected = []
    for line in lines[start:]:
        if not line.strip():
            break
        if len(line) - len(line.lstrip()) <= indent:
            break
        collected.append(line.strip())

    return ' '.join(collected)


def parse_docstring(docstring):
    """
    Pull a summary, the parameters and any examples out of a docstring.

    :param str docstring: The docstring, as ``inspect.getdoc`` hands it over.
    :return: ``(summary, parameters, examples)`` - the parameters keyed by name, each one
        ``{'type': str, 'description': str}``.
    :rtype: (str, dict, list)
    """

    if not docstring or not str(docstring).strip():
        return '', {}, []

    lines = str(docstring).splitlines()

    # The summary is the first paragraph, on one line.
    summary_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if summary_lines:
                break
            continue
        if stripped.startswith(':') or stripped.lower() in PARAMETER_HEADINGS:
            break
        summary_lines.append(stripped)
    summary = ' '.join(summary_lines)
    if len(summary) > SUMMARY_LIMIT:
        summary = summary[:SUMMARY_LIMIT - 3].rstrip() + '...'

    parameters = {}
    examples = []
    in_parameters = False
    in_examples = False
    example_lines = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        lowered = stripped.lower()

        if lowered in PARAMETER_HEADINGS:
            in_parameters, in_examples = True, False
            continue
        if lowered in ('examples:', 'example:'):
            in_parameters, in_examples = False, True
            continue
        if lowered in OTHER_HEADINGS:
            if in_examples and example_lines:
                examples.append('\n'.join(example_lines))
                example_lines = []
            in_parameters = in_examples = False
            continue

        # A Sphinx line names its own parameter wherever it appears, heading or no heading.
        match = SPHINX_PARAM.match(stripped)
        if match:
            name, type_name = parameter_name(match.group('body'))
            if name:
                parameters[name] = {'type': type_name,
                                    'description': match.group('description').strip()}
            continue

        if in_parameters:
            match = BULLET_PARAM.match(stripped)
            if match:
                parameters[match.group('name')] = {
                    'type': (match.group('type') or '').strip(),
                    'description': match.group('description').strip()}
                continue
            # ``path (str): what it is``, and the numpy shape, where the type follows the
            # colon and the description is indented underneath:
            #
            #     path : str
            #         what it is
            if ':' in stripped:
                head, _, tail = stripped.partition(':')
                words = head.strip().rstrip(')').replace('(', ' ').split()
                if len(words) in (1, 2) and words and words[0].isidentifier():
                    tail = tail.strip()
                    type_name = words[1] if len(words) > 1 else ''
                    description = tail
                    if not type_name and tail and ' ' not in tail:
                        # One word after the colon and the next line indented under it: that
                        # word is the type, not the description.
                        following = _indented_block(lines, index + 1, len(line) - len(stripped))
                        if following:
                            type_name, description = tail, following
                    parameters[words[0]] = {'type': type_name, 'description': description}
                continue

        if in_examples and stripped:
            example_lines.append(stripped)

    if example_lines:
        examples.append('\n'.join(example_lines))

    return summary, parameters, examples


def categorise(name, module_name, summary):
    """
    Which bucket a function belongs in.

    :param str name: The function's name.
    :param str module_name: The module it came from.
    :param str summary: Its first line.
    :return: A category, always something.
    :rtype: str
    """

    module_name = str(module_name or '').lower()
    for fragment, category in MODULE_CATEGORIES:
        if fragment in module_name:
            return category

    text = '{0} {1}'.format(name or '', summary or '').lower()
    for keywords, category in KEYWORD_CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return category

    return 'general'


def function_record(function, name, module_name, version='', prefix='pm.'):
    """
    One function, as a record.

    :param function: The function itself.
    :param str name: What it is called.
    :param str module_name: The module it came from.
    :param str version: The DCC version these docs are for, for the record's own sake.
    :param str prefix: How a caller writes it - ``pm.`` for PyMel.
    :return: The record, or None when the function cannot be read at all.
    :rtype: dict or None
    """

    try:
        signature = '{0}{1}{2}'.format(prefix, name, inspect.signature(function))
    except (ValueError, TypeError):
        # A C function often has no signature Python can read.
        signature = '{0}{1}(...)'.format(prefix, name)

    summary, parameters, examples = parse_docstring(inspect.getdoc(function))

    return {
        'command': name,
        'module': module_name,
        'category': categorise(name, module_name, summary),
        'version': version,
        'read_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'summary': summary,
        'syntax': signature,
        'parameters': parameters,
        'examples': examples,
        'documented': bool(summary),
    }


def module_records(module, module_name, version='', own_prefix='', prefix='pm.'):
    """
    Every public function a module defines.

    :param module: The module.
    :param str module_name: What to record it as.
    :param str version: The DCC version, for the record.
    :param str own_prefix: Only read functions whose ``__module__`` starts with this, so a
        module's re-exports are left to the module that defines them. ``''`` reads everything.
        The version this replaces had ``pymel.core`` written into the middle of this function,
        which is documented as taking any module at all.
    :param str prefix: How a caller writes these - ``pm.``.
    :return: One record per function.
    :rtype: list[dict]
    """

    records = []
    for name, found in inspect.getmembers(module):
        if name.startswith('_') or not callable(found):
            continue
        if own_prefix:
            where = getattr(found, '__module__', '') or ''
            if where and not where.startswith(own_prefix):
                continue
        record = function_record(found, name, module_name, version=version, prefix=prefix)
        if record:
            records.append(record)

    return records


def pymel_records(pymel_path='', version=''):
    """
    Read an installed PyMel.

    :param str pymel_path: The folder holding the ``pymel`` package, for a copy that is not
        already importable. Empty uses whatever ``import pymel`` finds.
    :param str version: The Maya version these docs are for, for the record.
    :return: One record per function, across every core submodule. Empty when PyMel cannot be
        imported, which is said out loud rather than raised - this is a tool somebody runs.
    :rtype: list[dict]
    """

    if pymel_path and pymel_path not in sys.path:
        sys.path.insert(0, pymel_path)

    try:
        import pymel.core
    except ImportError as error:
        logger.error('PyMel could not be imported%s: %s',
                     ' from {0}'.format(pymel_path) if pymel_path else '', error)
        return []

    records = []
    for submodule_name in PYMEL_SUBMODULES:
        submodule = getattr(pymel.core, submodule_name, None)
        if submodule is None:
            logger.warning('pymel.core has no %s, so it was skipped.', submodule_name)
            continue
        found = module_records(submodule, 'pymel.core.{0}'.format(submodule_name),
                               version=version, own_prefix='pymel.core')
        logger.info('Read %s functions from pymel.core.%s.', len(found), submodule_name)
        records.extend(found)

    logger.info('Read %s functions in all.', len(records))

    return records
