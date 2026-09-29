"""
Working with text: names, numbers in names, and the odd random one.

Three things were wrong:

- ``clean_file_string`` is documented as replacing ``/`` and ``\\`` with ``_``. It replaced
  ``\\``, and handled ``/`` only when the whole string was a single slash - so ``'rig/hero'``
  came back unchanged and went on to be used as a file name.
- ``get_numbers_from_string`` answered a ``map`` object rather than a list, so ``len()`` on
  it raised and walking it twice gave nothing the second time. It also pulled out digits one
  at a time, so ``'spine_012'`` answered ``[0, 1, 2]`` rather than ``[12]``.
- ``debug_object_string`` used ``obj.im_class`` for a method, which is Python 2 only and
  raises ``AttributeError`` here - and answered None for anything that was not a module,
  class, method or function.
"""

# python imports
import inspect
import random
import re
import string

# mca imports
from mca.common import log


logger = log.MCA_LOGGER

#: Not allowed in a file name on Windows, and best kept out of any name.
UNSAFE_IN_NAMES = '\\/:*?"<>|'


def generate_random_string(length=5, alpha_only=False, alpha_safe=True):
    """
    :param int length: How many characters.
    :param bool alpha_only: Letters only, no digits.
    :param bool alpha_safe: Start with a letter, so the result is a valid node name.
    :return: The string. An unusable length answers '' rather than None, so a caller can
        add to it without checking.
    :rtype: str
    """

    if not isinstance(length, int) or isinstance(length, bool) or length < 1:
        logger.warning('A random string needs a length of at least one, not %r.', length)
        return ''

    letters = string.ascii_lowercase
    choices = letters if alpha_only else letters + string.digits
    made = []
    for index in range(length):
        made.append(random.choice(letters if (alpha_safe and not index) else choices))
    return ''.join(made)


def generate_guid():
    """
    :return: A unique-enough identifier, in groups of 4-5-5-4, for an asset list entry.
    :rtype: str
    """

    return '-'.join(generate_random_string(size, alpha_safe=False) for size in (4, 5, 5, 4))


def clean_file_string(string_to_clean, replacement='_'):
    """
    :param str string_to_clean: A name that may hold path separators.
    :param str replacement: What to put in their place.
    :return: A name that can be written to disk - both separators replaced, which is what
        this always said it did.
    :rtype: str
    """

    cleaned = str(string_to_clean or '')
    for character in UNSAFE_IN_NAMES:
        cleaned = cleaned.replace(character, replacement)
    return cleaned


def get_trailing_numbers(text):
    """
    :param str text: A name such as ``'spine_04'``.
    :return: The number on the end, or None.
    :rtype: int or None
    """

    if not text or not isinstance(text, str):
        return None
    found = re.search(r'\d+$', text)
    return int(found.group()) if found else None


def get_numbers_from_string(_string, as_string=False):
    """
    :param str _string: Text with numbers in it, such as ``'vtx[12:14]'``.
    :param bool as_string: Answer them as text rather than whole numbers.
    :return: The numbers, each one whole: ``'spine_012'`` answers ``[12]``, not ``[0, 1, 2]``.
    :rtype: list(int) or list(str)
    """

    found = re.findall(r'\d+', str(_string or ''))
    return found if as_string else [int(one) for one in found]


def append_extension(input_string, extension):
    """
    :param str input_string: A file name.
    :param str extension: The extension it should have, with or without its dot.
    :return: The name with that extension, added only if it is not already there.
    :rtype: str
    """

    extension = str(extension or '')
    if extension and not extension.startswith('.'):
        extension = '.{}'.format(extension)

    name = str(input_string or '')
    while name.endswith('.'):
        name = name[:-1]
    if extension and not name.lower().endswith(extension.lower()):
        name = '{}{}'.format(name, extension)
    return name


def remove_chars(input_string, chars='[^a-zA-Z0-9_ ]+'):
    """
    :param str input_string: Some text.
    :param str chars: A regular expression matching what to take out. The default keeps
        letters, numbers, underscores and spaces.
    :return: What is left.
    :rtype: str
    """

    return re.compile(chars).sub('', str(input_string or ''))


def create_namespace(str_name=None):
    """
    :param str str_name: A name to shorten.
    :return: Three lower-case letters: the first three of the name, or random ones when
        there is no name. It used to raise TypeError on None.
    :rtype: str
    """

    name = str(str_name or '')
    if len(name) >= 3:
        return name[:3].lower()
    return generate_random_string(length=3, alpha_only=True, alpha_safe=True)


def debug_object_string(obj, msg):
    """
    Say what something is, for a message about it.

    :param obj: A module, class, method, function, or anything else.
    :param str msg: What to say about it.
    :return: The message with the thing named.
    :rtype: str
    """

    if inspect.ismodule(obj):
        return '[{} module] :: {}'.format(obj.__name__, msg)
    if inspect.isclass(obj):
        return '[{}.{} class] :: {}'.format(obj.__module__, obj.__name__, msg)
    if inspect.ismethod(obj):
        # __qualname__, not im_class: that attribute is Python 2 and raises here.
        return '[{}.{} method] :: {}'.format(getattr(obj, '__module__', '?'),
                                             getattr(obj, '__qualname__', obj.__name__), msg)
    if inspect.isfunction(obj):
        return '[{}.{} function] :: {}'.format(obj.__module__,
                                               getattr(obj, '__qualname__', obj.__name__),
                                               msg)
    # Anything else - an instance, a builtin, a number - gets named rather than answering
    # None, which is what a message about it needed in the first place.
    return '[{} {}] :: {}'.format(type(obj).__name__, obj, msg)
