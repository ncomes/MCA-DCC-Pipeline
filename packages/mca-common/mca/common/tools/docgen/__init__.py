"""
Turning an installed package's own docstrings into documentation a language model can read.

```
python -m mca.common.tools.docgen --output D:/AIDocs/Maya/pymel
```

It imports PyMel, walks its core submodules, and writes a JSON file and a Markdown file per
function plus one index over all of them - so the in-DCC AI and the MCP tools can answer a
question about a PyMel command from the docstrings of the version that is actually installed.

This was ``doccrawler``, and most of it scraped Autodesk's documentation website: a crawler
(197 lines), an HTML parser (342) and a second crawler for ``maya.cmds`` (476), all of which
its own README called the less reliable half next to introspection. None of that has come
across. Introspection needs no network, cannot be broken by somebody restyling a web page, and
reads the version of PyMel this machine has rather than whichever one is on the internet.

Nor have the paths: the version this replaces had a previous employer's depot written into two
module-level constants - where the docs would be written, and where PyMel was to be found.
``MCA_AI_DOCS_PATH`` says the first, a command-line argument says either, and PyMel is imported
the ordinary way when nobody says otherwise.

``maya.cmds`` is not covered. The honest way to document it is ``cmds.help(command)`` from
inside Maya, which is introspection rather than scraping; that can be added here when something
needs it.
"""

# python imports
import argparse
import os
import sys

# MCA python imports
from mca.common import log
from mca.common.tools.docgen import introspect, write_docs


logger = log.MCA_LOGGER

#: Where to write, when nobody says. A folder for AI documentation, not a folder in the depot.
OUTPUT_VARIABLE = 'MCA_AI_DOCS_PATH'

#: What goes under it, so several packages' docs can live side by side.
PYMEL_SUBFOLDER = os.path.join('Maya', 'pymel')


def default_output_folder(version=''):
    """
    :param str version: A Maya version, which gets its own folder so two versions' docs do not
        overwrite each other.
    :return: Where the docs go when nobody says, or ``''`` when nothing says where.
    :rtype: str
    """

    root = os.environ.get(OUTPUT_VARIABLE, '')
    if not root:
        return ''

    parts = [root, PYMEL_SUBFOLDER]
    if version:
        parts.append(str(version))

    return os.path.normpath(os.path.join(*parts))


def generate_pymel_docs(output_folder='', pymel_path='', version='', skip_existing=False):
    """
    Read the installed PyMel and write the documentation.

    :param str output_folder: Where to write. Empty uses :func:`default_output_folder`.
    :param str pymel_path: The folder holding a ``pymel`` package to read, for one that is not
        already importable. Empty imports whatever is on the path.
    :param str version: The Maya version, for the records and the folder name.
    :param bool skip_existing: True leaves functions whose files are already there, so an
        interrupted run carries on rather than starting again.
    :return: ``{'ok': bool, 'result': {...}, 'message': str}`` - the same shape the framework's
        other headless APIs answer, so a script or an MCP tool can read it.
    :rtype: dict
    """

    output_folder = output_folder or default_output_folder(version)
    if not output_folder:
        return {'ok': False, 'result': None,
                'message': 'Nowhere to write to. Pass an output folder, or set {0}.'.format(
                    OUTPUT_VARIABLE)}

    records = introspect.pymel_records(pymel_path=pymel_path, version=version)
    if not records:
        return {'ok': False, 'result': None,
                'message': 'PyMel could not be read, so nothing was written. It has to be '
                           'importable by this Python - Maya\'s own interpreter, or a path '
                           'passed in.'}

    written = write_docs.write_all(records, output_folder, skip_existing=skip_existing)

    return {'ok': True, 'result': written,
            'message': 'Wrote {0} of {1} function(s) to {2}.'.format(
                written['written'], len(records), output_folder)}


def main(argv=None):
    """
    :param argv: The command line, or None for the real one.
    :return: 0 when something was written.
    :rtype: int
    """

    parser = argparse.ArgumentParser(
        description='Write documentation for the installed PyMel, for an AI to read.')
    parser.add_argument('--output', default='',
                        help='Where to write. Defaults to {0}.'.format(OUTPUT_VARIABLE))
    parser.add_argument('--pymel-path', default='',
                        help='A folder holding a pymel package, if it is not importable.')
    parser.add_argument('--version', default='',
                        help='The Maya version these docs are for.')
    parser.add_argument('--resume', action='store_true',
                        help='Leave functions whose files are already written.')
    arguments = parser.parse_args(argv)

    answer = generate_pymel_docs(output_folder=arguments.output,
                                 pymel_path=arguments.pymel_path,
                                 version=arguments.version,
                                 skip_existing=arguments.resume)
    logger.info(answer['message'])

    return 0 if answer['ok'] else 1


if __name__ == '__main__':                                           # pragma: no cover
    sys.exit(main())
