"""
JSON files, by the names the framework already calls them.

The work is in :mod:`mca.common.textio.datafile`.

One behaviour changed on purpose: ``read_json_file`` used to re-raise whatever the parser
threw, while its YAML twin returned None for the same situation. A caller could not tell
which it was talking to. Both answer the default now and log the file and the reason; a
caller that would rather stop can ask for ``strict``.
"""

# python imports
import json

# mca imports
from mca.common import log
from mca.common.textio import datafile


logger = log.MCA_LOGGER


def validate_json(input_dict):
    """
    :param input_dict: What would be written.
    :return: Whether it can be written as JSON.
    :rtype: bool
    """

    return datafile.validate(input_dict, 'json')


def convert_dict_to_string(input_dict):
    """
    :param dict input_dict: A dictionary.
    :return: It as a JSON string, or '' when it holds something JSON cannot carry.
    :rtype: str
    """

    try:
        return json.dumps(input_dict)
    except (TypeError, ValueError) as error:
        logger.error('That data cannot be written as JSON: %s', error)
        return ''


def write_to_json_file(data, filename, **kwargs):
    """
    :param data: What to write.
    :param str filename: Where to write it.
    :param kwargs: ``indent`` and anything else ``json.dumps`` takes.
    :return: The path written, or '' when it could not be.
    :rtype: str
    """

    return datafile.write(data, filename, fmt='json', indent=kwargs.pop('indent', 2),
                          **kwargs)


def read_json_file(filename, maintain_order=False, default=None, strict=False):
    """
    :param str filename: The file to read.
    :param bool maintain_order: Accepted and ignored; dictionaries keep their order.
    :param default: What to answer for a file that is missing, empty or unreadable.
    :param bool strict: Raise when the file is there but will not parse.
    :return: What was in it.
    :rtype: object
    """

    return datafile.read(filename, default=default, strict=strict)
