"""
Reading what is on a class.

``get_properties`` answered an empty list unless it was given something to filter out: the
append sat inside ``if filter_out:``, so the ordinary call - ``get_properties(thing)`` -
found every property and then returned nothing at all.

``strip_type_hints`` is gone. It rewrote a source file in place by running two regular
expressions over it, and ``:\\s*[\\w\\[\\],\\. ]+`` matches a dictionary literal, a slice and
an annotation alike - so it would quietly turn ``{'a': 1}`` into ``{'a'}``. Nothing in any
package called it.
"""

# python imports
import inspect


def get_properties(cls_inst, filter_out=None):
    """
    Everything readable on an object that is not a method and not private.

    :param cls_inst: An instance, or a class.
    :param filter_out: Names to leave out.
    :return: (name, value) for each, in name order.
    :rtype: list(tuple)
    """

    unwanted = set(filter_out or ())
    found = []
    for name, value in inspect.getmembers(cls_inst):
        if name.startswith('_'):
            continue
        if inspect.ismethod(value) or inspect.isfunction(value) or inspect.isbuiltin(value):
            continue
        if name in unwanted:
            continue
        found.append((name, value))
    return found


def get_property_names(cls_inst, filter_out=None):
    """
    :param cls_inst: An instance, or a class.
    :param filter_out: Names to leave out.
    :return: Just the names.
    :rtype: list(str)
    """

    return [name for name, _ in get_properties(cls_inst, filter_out)]
