"""
Working with lists.

The module imported ``sys``, ``time``, ``ctypes``, ``inspect``, ``importlib``, ``traceback``
and ``Counter`` and used exactly one of them - a set of list helpers that pulled in ctypes.

And one it got wrong: ``get_index_in_list`` tested ``len(list_arg) > abs(index)``, which is
off by one for negative indices, so **the last item of a one-item list could not be read**.
``get_last_in_list(['hero'])`` answered the default rather than ``'hero'``, and
``get_index_in_list(['a', 'b'], -2)`` answered the default rather than ``'a'``. A rig with
one of something - one spine, one root - is the normal case, so this was reached often and
answered None quietly.
"""

# python imports
from collections import Counter


def force_list(var):
    """
    :param var: Anything.
    :return: It as a list. None is an empty list; a tuple or a set becomes a list; anything
        else is a list of one.
    :rtype: list
    """

    if var is None:
        return []
    if isinstance(var, list):
        return var
    if isinstance(var, (tuple, set, frozenset)):
        return list(var)
    return [var]


def force_tuple(var):
    """
    :param var: Anything.
    :return: It as a tuple.
    :rtype: tuple
    """

    if var is None:
        return ()
    if isinstance(var, tuple):
        return var
    if isinstance(var, (list, set, frozenset)):
        return tuple(var)
    return (var,)


def index_exists_in_list(items_list, index):
    """
    :param items_list: A list or tuple.
    :param int index: An index, positive or negative.
    :return: Whether that index can be read.
    :rtype: bool
    """

    if not items_list:
        return False
    length = len(items_list)
    return -length <= index < length


def get_index_in_list(list_arg, index, default=None):
    """
    :param list_arg: A list.
    :param int index: Which item, counting from the end when negative.
    :param default: What to answer when there is no such item.
    :return: The item, or the default.
    """

    if not list_arg or not index_exists_in_list(list_arg, index):
        return default
    return list_arg[index]


def get_first_in_list(list_arg, default=None):
    """
    :param list_arg: A list.
    :param default: What to answer when it is empty.
    :return: Its first item, or the default.
    """

    return get_index_in_list(list_arg, 0, default=default)


def get_last_in_list(list_arg, default=None):
    """
    :param list_arg: A list.
    :param default: What to answer when it is empty.
    :return: Its last item, or the default. A one-item list answers that item, which is what
        the version this replaces could not do.
    """

    return get_index_in_list(list_arg, -1, default=default)


def get_duplicates(iterable):
    """
    :param iterable: Anything that can be walked.
    :return: The values that appear more than once, in the order they were seen again.
    :rtype: list
    """

    seen = set()
    duplicates = []
    for item in iterable or []:
        if item in seen:
            duplicates.append(item)
        else:
            seen.add(item)
    return duplicates


def get_most_common_item_in_list(iterable):
    """
    :param iterable: A list.
    :return: Whichever item appears most often, or None when there is nothing.
    """

    items = list(iterable or [])
    if not items:
        return None
    return Counter(items).most_common(1)[0][0]


def pairwise(iterable):
    """
    :param iterable: Anything that can be walked.
    :return: Its items two at a time - (0, 1), (2, 3) - dropping a lone last one.
    """

    walker = iter(iterable)
    return zip(walker, walker)


def flatten_list(list_arg):
    """
    :param list_arg: A list that may hold lists, however deeply.
    :return: One flat list of what was in it.
    :rtype: list
    """

    flat = []
    for item in force_list(list_arg):
        if isinstance(item, (list, tuple)):
            flat.extend(flatten_list(item))
        else:
            flat.append(item)
    return flat


def remove_none(list_arg):
    """
    :param list_arg: A list that may hold None.
    :return: The same items without them, in order. Useful for a constraint list where some
        optional flags may not exist on a given rig.
    :rtype: list
    """

    return [item for item in (list_arg or []) if item is not None]


def set_list_value_at(initial_list, index, value, buffer_value=None):
    """
    Put a value at an index, growing the list until that index exists.

    A negative index grows the list at the front::

        set_list_value_at([2, 3], -2, 0)  ->  [0, None, 2, 3]

    :param list initial_list: The list to work on.
    :param int index: Where to put it.
    :param value: What to put there.
    :param buffer_value: What to fill the new places with.
    :return: The list.
    :rtype: list
    :raises IndexError: When the index is not a whole number.
    """

    if not isinstance(index, int) or isinstance(index, bool):
        raise IndexError('An index has to be a whole number, not {!r}.'.format(index))

    initial_list = list(initial_list or [])
    if index < 0:
        initial_list = [buffer_value] * abs(index) + initial_list
        index = 0
    elif len(initial_list) <= index:
        initial_list = initial_list + [buffer_value] * (index + 1 - len(initial_list))

    initial_list[index] = value
    return initial_list
