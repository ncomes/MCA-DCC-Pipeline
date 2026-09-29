"""
``.alist`` asset list files, which are JSON now and were YAML.

Both are read without being told which is which, and an existing file keeps the format it
already has, so the change happens one file at a time as things are saved rather than in one
migration nobody has time for.
"""

# mca imports
from mca.common.textio import datafile


def read_alist_file(filename, default=None):
    """
    :param str filename: The .alist file.
    :param default: What to answer for a file that is missing, empty or unreadable.
    :return: What was in it.
    :rtype: dict or None
    """

    return datafile.read(filename, default=default)


def detect_format(filename):
    """
    :param str filename: The .alist file.
    :return: 'json' or 'yaml', or None when there is nothing to look at.
    :rtype: str or None
    """

    import os

    if not filename or not os.path.isfile(filename):
        return None
    contents = datafile.read_text(filename)
    if not contents.strip():
        return None
    return datafile.format_of(filename, contents)


def write_alist_file(data, filename, fmt=None):
    """
    :param data: What to write.
    :param str filename: The .alist file.
    :param str fmt: 'json' or 'yaml'. None keeps what the file already is, and writes JSON
        for a new one.
    :return: The path written, or '' when it could not be.
    :rtype: str
    """

    return datafile.write(data, filename, fmt=fmt or detect_format(filename) or 'json')
