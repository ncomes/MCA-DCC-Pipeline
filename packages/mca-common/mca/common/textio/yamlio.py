"""
YAML files, by the names the framework already calls them.

The work is in :mod:`mca.common.textio.datafile`; this is the YAML-shaped door into it, kept
so that the hundred or so ``from mca.common.textio import yamlio`` lines in the framework do
not have to change to gain atomic writes, a named encoding, and a read that answers instead
of raising when the file is not there.
"""

# mca imports
from mca.common.textio import datafile


def validate_yaml(data):
    """
    :param data: What would be written.
    :return: Whether it can be written as YAML.
    :rtype: bool
    """

    return datafile.validate(data, 'yaml')


def write_to_yaml_file(data, filename, **kwargs):
    """
    :param data: What to write.
    :param str filename: Where to write it.
    :param kwargs: ``indent`` and anything else the dumper takes.
    :return: The path written, or '' when it could not be.
    :rtype: str
    """

    return datafile.write(data, filename, fmt='yaml', indent=kwargs.pop('indent', 2),
                          **kwargs)


def read_yaml_file(filename, maintain_order=False, default=None):
    """
    :param str filename: The file to read.
    :param bool maintain_order: Accepted and ignored: dictionaries have kept their order
        since Python 3.7, and honouring this used to mean importing ``yamlordereddictloader``,
        which is not installed everywhere the framework runs.
    :param default: What to answer for a file that is missing, empty or unreadable.
    :return: What was in it.
    :rtype: object
    """

    return datafile.read(filename, default=default)
