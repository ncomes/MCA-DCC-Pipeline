"""
Working with dictionaries.
"""


def get_dict_slice(starting_dict, index, default_value=None):
    """
    Take the same position out of every list in a dictionary.

    :param dict starting_dict: Keys whose values are lists.
    :param int index: Which position to take.
    :param default_value: What to answer for a list that is too short.
    :return: The same keys, each holding one value.
    :rtype: dict
    """

    sliced = {}
    for key, values in (starting_dict or {}).items():
        try:
            sliced[key] = values[index]
        except (IndexError, TypeError, KeyError):
            # Too short, or not something that can be indexed at all.
            sliced[key] = default_value
    return sliced


def merge(first, second):
    """
    Two dictionaries into one, nested ones included.

    :param dict first: The one underneath.
    :param dict second: The one on top, whose values win.
    :return: A new dictionary. Neither of the two is changed.
    :rtype: dict
    """

    merged = dict(first or {})
    for key, value in (second or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged
