"""
Writing the records out: a JSON file and a Markdown file per function, and one index over all
of them.

Both formats on purpose. The JSON is for a program looking a function up by name; the Markdown
is what gets pasted into a model's context, where headings and fenced code read better than
braces.

The index is written **once**, at the end. The version this replaces read the whole index file,
scanned it linearly for the function it was adding, and wrote the whole thing back - per
function. Two thousand functions meant two thousand reads and two thousand writes of a file
that grew as it went, and the linear scan made it quadratic on top.
"""

# python imports
import json
import os

# MCA python imports
from mca.common import log


logger = log.MCA_LOGGER

#: Where each kind of file goes under the output folder.
JSON_FOLDER = 'json'
MARKDOWN_FOLDER = 'markdown'
INDEX_NAME = 'index.json'

#: How much of a summary the index carries.
INDEX_SUMMARY_LIMIT = 200

#: How many keywords a function gets.
KEYWORD_LIMIT = 12

#: Words too common to be worth searching for.
STOP_WORDS = frozenset(('the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
                        'this', 'that', 'these', 'those', 'it', 'its'))


def write_json(record, output_folder):
    """
    :param dict record: One function's record.
    :param str output_folder: The folder the whole set is being written to.
    :return: The file written, or ``''``.
    :rtype: str
    """

    folder = os.path.join(output_folder, JSON_FOLDER)
    path = os.path.join(folder, '{0}.json'.format(record.get('command', 'unknown')))
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as opened:
            json.dump(record, opened, indent=2, ensure_ascii=False)
    except OSError as error:
        logger.error('Could not write %s: %s', path, error)
        return ''

    return path


def markdown(record):
    """
    One function as Markdown, for a model to read.

    :param dict record: The record.
    :return: The text.
    :rtype: str
    """

    name = record.get('command', 'unknown')
    lines = ['# {0}'.format(name), '']

    summary = record.get('summary') or ''
    if summary:
        lines += [summary, '']

    facts = [('Module', record.get('module')), ('Category', record.get('category')),
             ('Version', record.get('version'))]
    stated = ['**{0}:** {1}'.format(label, value) for label, value in facts if value]
    if stated:
        lines += stated + ['']

    syntax = record.get('syntax') or ''
    if syntax:
        lines += ['## Syntax', '', '```python', syntax, '```', '']

    parameters = record.get('parameters') or {}
    if parameters:
        lines += ['## Parameters', '']
        for parameter_name in sorted(parameters):
            about = parameters[parameter_name]
            if isinstance(about, dict):
                type_name = about.get('type') or ''
                description = about.get('description') or ''
            else:
                type_name, description = '', str(about)
            written = '- **{0}**'.format(parameter_name)
            if type_name:
                written += ' (`{0}`)'.format(type_name)
            if description:
                written += ' - {0}'.format(description)
            lines.append(written)
        lines.append('')

    examples = record.get('examples') or []
    if examples:
        lines += ['## Examples', '']
        for example in examples:
            lines += ['```python', example, '```', '']

    return '\n'.join(lines).rstrip() + '\n'


def write_markdown(record, output_folder):
    """
    :param dict record: One function's record.
    :param str output_folder: The folder the whole set is being written to.
    :return: The file written, or ``''``.
    :rtype: str
    """

    folder = os.path.join(output_folder, MARKDOWN_FOLDER)
    path = os.path.join(folder, '{0}.md'.format(record.get('command', 'unknown')))
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as opened:
            opened.write(markdown(record))
    except OSError as error:
        logger.error('Could not write %s: %s', path, error)
        return ''

    return path


def keywords(record):
    """
    What to let somebody search a function by.

    :param dict record: The record.
    :return: Its name, its category, and the words in its summary worth keeping.
    :rtype: list[str]
    """

    found = []
    seen = set()

    def add(word):
        word = str(word or '').strip().lower().strip('.,;:!?()[]{}"\'')
        if word and word not in seen:
            seen.add(word)
            found.append(word)

    add(record.get('command'))
    add(record.get('category'))
    for word in str(record.get('summary') or '').split():
        if len(found) >= KEYWORD_LIMIT:
            break
        cleaned = word.strip('.,;:!?()[]{}"\'').lower()
        if len(cleaned) > 3 and cleaned not in STOP_WORDS:
            add(cleaned)

    return found[:KEYWORD_LIMIT]


def build_index(records):
    """
    One entry per function, for looking one up without opening every file.

    :param records: The records.
    :return: ``{'version', 'count', 'commands': [...]}``.
    :rtype: dict
    """

    commands = []
    for record in records:
        commands.append({
            'name': record.get('command', ''),
            'module': record.get('module', ''),
            'category': record.get('category', ''),
            'summary': (record.get('summary') or '')[:INDEX_SUMMARY_LIMIT],
            'keywords': keywords(record),
        })
    commands.sort(key=lambda entry: entry['name'].lower())

    return {'version': '2.0', 'count': len(commands), 'commands': commands}


def write_index(records, output_folder):
    """
    :param records: The records.
    :param str output_folder: Where the set is being written.
    :return: The index file, or ``''``.
    :rtype: str
    """

    path = os.path.join(output_folder, INDEX_NAME)
    try:
        os.makedirs(output_folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as opened:
            json.dump(build_index(records), opened, indent=2, ensure_ascii=False)
    except OSError as error:
        logger.error('Could not write %s: %s', path, error)
        return ''

    return path


def write_all(records, output_folder, skip_existing=False):
    """
    Write every record, both ways, and the index over them.

    :param records: The records.
    :param str output_folder: Where to write.
    :param bool skip_existing: True leaves a function alone when its JSON is already there,
        which is how a run that was interrupted picks up where it stopped.
    :return: ``{'written': int, 'skipped': int, 'index': str}``.
    :rtype: dict
    """

    written = 0
    skipped = 0
    for record in records:
        name = record.get('command', '')
        if not name:
            continue
        if skip_existing and os.path.isfile(
                os.path.join(output_folder, JSON_FOLDER, '{0}.json'.format(name))):
            skipped += 1
            continue
        if write_json(record, output_folder) and write_markdown(record, output_folder):
            written += 1

    index = write_index(records, output_folder)
    logger.info('Wrote %s function(s) to %s%s.', written, output_folder,
                ', skipped {0} already there'.format(skipped) if skipped else '')

    return {'written': written, 'skipped': skipped, 'index': index}
