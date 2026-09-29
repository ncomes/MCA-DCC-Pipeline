"""
One reader and one writer, for every data file the pipeline keeps.

YAML, JSON and ``.alist`` were three modules doing the same job three times, each with its
own version of the same two mistakes, and every caller choosing between them by looking at
the extension. That choice is made here now, once. ``yamlio``, ``jsonio`` and ``alistio``
still exist and still have the names they had - they are what the framework imports - and
they all come through this.

What the three had in common, and what is fixed here:

- **A missing file raised.** Every reader called ``os.stat(filename)`` to check for an empty
  file *before* checking the file was there, so reading a path that does not exist raised
  ``FileNotFoundError`` from a function documented to answer ``None``.
- **A write could truncate the file it was replacing.** ``open(path, 'w')`` empties the file
  and then writes; a crash, a full disk or a network hiccup in between leaves nothing. Here
  the new content is written beside the file and moved over it, which on every platform this
  runs on is one step: the old file is there, or the new one is, never neither.
- **No encoding was named**, so every file was read and written in the machine's code page -
  cp1252 inside Maya. UTF-8 is written and read, explicitly.
- ``maintain_order`` and the ``yamlordereddictloader`` dependency were both about keeping
  dictionary order. Dictionaries have kept their order since Python 3.7, which is the oldest
  interpreter this package supports, so the argument is accepted and ignored rather than
  quietly pulling in a package that may not be installed.
"""

# python imports
import json
import os

import yaml

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: Everything is UTF-8.
ENCODING = 'utf-8'

#: Which format an extension means. Anything else is read by sniffing it.
FORMATS = {
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.json': 'json',
    '.alist': 'alist',
}

#: What a new file of an unknown kind is written as. ``.alist`` files were YAML and are
#: being moved to JSON, so a new one is JSON and an existing one keeps what it already is.
DEFAULT_FORMAT = 'json'


def format_of(path, contents=None):
    """
    Which format a file is in.

    :param str path: The file's path.
    :param str contents: Its text, when it has already been read.
    :return: 'yaml' or 'json'.
    :rtype: str
    """

    named = FORMATS.get(os.path.splitext(str(path))[1].lower(), '')
    if named in ('yaml', 'json'):
        return named

    # An .alist or something unfamiliar: JSON is a subset of YAML in practice, so the cheap
    # and reliable test is whether json can read it.
    if contents is None:
        contents = read_text(path)
    if not contents:
        return DEFAULT_FORMAT
    try:
        json.loads(contents)
        return 'json'
    except ValueError:
        return 'yaml'


def read_text(path, default=''):
    """
    :param str path: A file.
    :param str default: What to answer when it is not there or will not open.
    :return: Its text.
    :rtype: str
    """

    if not path or not os.path.isfile(path):
        return default
    try:
        with open(path, 'r', encoding=ENCODING, errors='replace') as opened:
            return opened.read()
    except OSError as error:
        logger.warning('Could not read %s: %s', path, error)
        return default


def read(path, default=None, strict=False):
    """
    Read a data file, whatever format it is in.

    :param str path: The file.
    :param default: What to answer for a file that is missing, empty, or unreadable.
    :param bool strict: Raise on a file that is there but will not parse, rather than
        answering the default. For a caller that would rather stop than carry on with
        nothing.
    :return: What was in it.
    :rtype: object
    :raises ValueError: Only when ``strict`` and the file will not parse.
    """

    # Existence first. The version this replaces asked for the size first, so a missing file
    # raised out of a function whose docstring promised None.
    if not path or not os.path.isfile(path):
        logger.debug('No file to read at %s.', path)
        return default

    contents = read_text(path, default=None)
    if contents is None:
        return default
    if not contents.strip():
        return default

    kind = format_of(path, contents)
    try:
        if kind == 'json':
            return json.loads(contents)
        return yaml.safe_load(contents)
    except (ValueError, yaml.YAMLError) as error:
        message = 'Could not read {} as {}: {}'.format(path, kind, error)
        if strict:
            raise ValueError(message)
        logger.warning(message)
        return default


def write(data, path, fmt=None, indent=2, **kwargs):
    """
    Write a data file, atomically.

    :param data: What to write.
    :param str path: Where to write it.
    :param str fmt: 'yaml' or 'json'. None keeps an existing file's format and uses JSON for
        a new one.
    :param int indent: How far to indent.
    :param kwargs: Passed through to the dumper.
    :return: The path written, or '' when it could not be.
    :rtype: str
    """

    if not path:
        logger.warning('No path was given to write to.')
        return ''

    kind = fmt or (format_of(path) if os.path.isfile(path) else
                   FORMATS.get(os.path.splitext(str(path))[1].lower(), DEFAULT_FORMAT))
    if kind == 'alist':
        kind = DEFAULT_FORMAT

    try:
        text = _dump(data, kind, indent, kwargs)
    except Exception as error:                                       # noqa: BLE001
        # A dictionary holding something that cannot be represented is worth a clear
        # sentence, not a traceback out of the dumper.
        logger.error('Could not turn that data into %s for %s: %s', kind, path, error)
        return ''

    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except OSError as error:
            logger.error('Could not create %s: %s', folder, error)
            return ''

    temporary = '{}.mca-tmp'.format(path)
    try:
        with open(temporary, 'w', encoding=ENCODING, newline='\n') as opened:
            opened.write(text)
        os.replace(temporary, path)
    except OSError as error:
        logger.error('Could not write %s: %s', path, error)
        if os.path.isfile(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
        return ''

    logger.debug('Wrote %s', path)
    return os.path.normpath(path)


def validate(data, fmt='json'):
    """
    Whether this data can be written in that format at all.

    :param data: What would be written.
    :param str fmt: 'yaml' or 'json'.
    :return: Whether it would work.
    :rtype: bool
    """

    try:
        _dump(data, fmt, 2, {})
        return True
    except Exception:                                                # noqa: BLE001
        return False


def _dump(data, kind, indent, kwargs):
    """
    :param data: What to write.
    :param str kind: 'yaml' or 'json'.
    :param int indent: How far to indent.
    :param dict kwargs: Extra arguments for the dumper.
    :return: The text to write.
    :rtype: str
    """

    if kind == 'json':
        return json.dumps(data, indent=indent, **kwargs)

    kwargs.setdefault('default_flow_style', False)
    kwargs.setdefault('width', 200)
    kwargs.setdefault('sort_keys', False)
    try:
        return yaml.safe_dump(data, indent=indent, **kwargs)
    except yaml.representer.RepresenterError:
        # Something safe_dump will not represent - an OrderedDict out of an older file, a
        # tuple. The full dumper handles those, and reading is safe_load either way.
        return yaml.dump(data, indent=indent, **kwargs)
